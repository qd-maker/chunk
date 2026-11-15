"""Chunk：把句式和词块练到能脱口而出的间隔复习工具。接口约定见 docs/API.md。"""
import json
import re
import sqlite3
import statistics
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta

from fastapi import FastAPI, File, Form, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse

from . import auth, coach, db, fake, sched
from .config import ROOT, settings
from .schemas import (AnswerOut, CreateItemIn, Fix, Health, HistoryRow, ItemDetail, ItemOut, LatencyPoint, LibraryOut,
                      LoginIn, NextOut, OverrideIn, PromptOut, Task, TodayOut, TopicOut, WallOut)
from .upstream import ApiError, transcribe

STATIC = ROOT / "static"
MAX_AUDIO = 8 * 1024 * 1024
MIN_WORDS = 3            # 转写不足这么多词就当没听清
AUDIO_EXT = {"audio/webm": "webm", "audio/mp4": "m4a", "audio/x-m4a": "m4a", "audio/wav": "wav", "audio/x-wav": "wav",
             "audio/ogg": "ogg", "audio/mpeg": "mp3", "video/webm": "webm", "video/mp4": "m4a"}
OPEN_PATHS = {"/api/health", "/api/session", "/api/login"}


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init()
    (settings.data_dir / "audio").mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="Chunk", lifespan=lifespan)


def today() -> date:
    return datetime.now().astimezone().date()


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


@app.middleware("http")
async def _require_login(request: Request, call_next):
    p = request.url.path
    if auth.enabled() and p.startswith("/api/") and p not in OPEN_PATHS \
            and not auth.valid_token(request.cookies.get(auth.COOKIE)):
        return _error(401, "UNAUTHORIZED", "请先登录。")
    resp = await call_next(request)
    if not p.startswith("/assets/"):
        resp.headers["Cache-Control"] = "no-store"   # 页面和接口都不缓存，避免手机上看到旧版本
    return resp


@app.exception_handler(ApiError)
async def _api_error(_: Request, e: ApiError):
    return _error(e.status, e.code, e.message)


@app.exception_handler(RequestValidationError)
async def _validation_error(_: Request, e: RequestValidationError):
    first = e.errors()[0] if e.errors() else {}
    return _error(422, "VALIDATION_ERROR", f"{'.'.join(str(x) for x in first.get('loc', [])[1:])}: {first.get('msg', '参数不合法')}")


# ---------- 登录 ----------

@app.get("/api/health", response_model=Health)
def health():
    key = bool(settings.openrouter_api_key)
    return Health(fake=settings.fake_upstream, asr_ready=settings.fake_upstream or key,
                  llm_ready=settings.fake_upstream or key or bool(settings.llm_api_key), auth_required=auth.enabled())


@app.get("/api/session")
def session(request: Request):
    return {"auth_required": auth.enabled(),
            "authed": not auth.enabled() or auth.valid_token(request.cookies.get(auth.COOKIE))}


@app.post("/api/login", status_code=204)
def login(body: LoginIn, request: Request):
    if not auth.enabled():
        return Response(status_code=204)
    ip = auth.client_ip(request.headers, request.client.host if request.client else None)
    if auth.locked(ip):
        raise ApiError(429, "LOCKED", "输错次数太多，10 分钟后再试。")
    if not auth.check_password(ip, body.password):
        raise ApiError(401, "BAD_PASSWORD", "密码不对。")
    resp = Response(status_code=204)
    secure = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
    resp.set_cookie(auth.COOKIE, auth.make_token(), max_age=auth.MAX_AGE, httponly=True, samesite="lax", secure=secure)
    return resp


@app.post("/api/logout", status_code=204)
def logout():
    resp = Response(status_code=204)
    resp.delete_cookie(auth.COOKIE)
    return resp


# ---------- 小工具 ----------

def item_out(row: sqlite3.Row, latency: dict[str, int] | None = None) -> ItemOut:
    d = dict(row)
    d["first_batch"] = bool(d["first_batch"])
    return ItemOut(**d, latency_ms=(latency or {}).get(row["id"]))


def _item_or_404(item_id: str) -> sqlite3.Row:
    row = db.get_item(item_id)
    if not row:
        raise ApiError(404, "NOT_FOUND", "没有这个表达。")
    return row


def _tasks_left(rows: list[sqlite3.Row]) -> int:
    return sum(r["drills_owed"] or r["intro_left"] or 1 for r in rows)


def _streak(days: list[str], t: date) -> int:
    """连续练习天数：今天还没练不算断，从昨天往前数。"""
    have, d, n = set(days), t, 0
    if d.isoformat() not in have:
        d -= timedelta(days=1)
    while d.isoformat() in have:
        n, d = n + 1, d - timedelta(days=1)
    return n


async def _prompt_for(row: sqlite3.Row, kind: str) -> sqlite3.Row:
    """题库里拿一道没用过的；用完了就让大模型补一批；补不上就拿最久没用的旧题顶上。"""
    p = db.fresh_prompt(row["id"], kind)
    if p:
        return p
    try:
        gen = await coach.generate(row, db.prompt_texts(row["id"]), (kind,))
        db.add_prompts(row["id"], gen["prompts"])
    except ApiError:
        stale = db.stale_prompt(row["id"], kind)
        if stale:
            return stale
        raise
    return db.fresh_prompt(row["id"], kind) or db.stale_prompt(row["id"], kind)


def _fix_of(r: sqlite3.Row) -> Fix | None:
    """旧记录的 fix_json 没有 scope，按 target 处理。"""
    return Fix(**{"scope": "target", **json.loads(r["fix_json"])}) if r["fix_json"] else None


def _collect_id(review_id: int) -> str:
    return f"fix-r{review_id}"


def _answer_out(review_id: int) -> AnswerOut:
    r = db.get_review(review_id)
    before, after = json.loads(r["before_json"]), json.loads(r["after_json"])
    prompt = db.get_prompt(r["prompt_id"])
    return AnswerOut(
        review_id=r["id"], mode=r["mode"], kind=r["kind"], transcript=r["transcript"], used=bool(r["used"]),
        correct=bool(r["correct"]), hinted=bool(r["hinted"]), result=r["result"],
        fix=_fix_of(r), natural=r["natural"],
        ref_en=prompt["ref_en"] if prompt else "", think_ms=r["think_ms"], latency_ms=r["latency_ms"],
        step_before=before["step"], step_after=after["step"], due_after=after["due"],
        graduated=after["status"] == "graduated" and before["status"] != "graduated",
        drills_owed=after["drills_owed"], overridden=bool(r["overridden"]), has_audio=bool(r["audio"]),
        collected=db.get_item(_collect_id(review_id)) is not None, item=item_out(db.get_item(r["item_id"])))


# ---------- 练习 ----------

@app.get("/api/today", response_model=TodayOut)
def today_summary():
    t = today()
    q = db.queue(t, settings.session_cap)
    items = db.all_items()
    upcoming = sorted(r["due"] for r in items if r["status"] in ("active", "graduated") and r["due"] and r["due"] > t.isoformat())
    return TodayOut(
        date=t.isoformat(),
        due=sum(1 for r in q if not r["drills_owed"] and not r["intro_left"]),
        intro=sum(1 for r in q if r["intro_left"] and not r["drills_owed"]),
        drills=sum(1 for r in q if r["drills_owed"]),
        remaining=_tasks_left(q), done_today=db.count_on(t.isoformat()),
        new_left=max(0, settings.new_per_day - db.activated_on(t.isoformat())),
        active=sum(1 for r in items if r["status"] == "active"),
        graduated=sum(1 for r in items if r["status"] == "graduated"),
        streak=_streak(db.review_days(), t), next_due=upcoming[0] if upcoming else None)


@app.get("/api/next", response_model=NextOut)
async def next_task():
    q = db.queue(today(), settings.session_cap)
    if not q:
        return NextOut(task=None, remaining=0)
    row = q[0]
    s = db.state_of(row)
    mode, kind = sched.mode_of(s), sched.kind_of(s)
    prompt = await _prompt_for(row, kind)
    if mode == "intro":
        rounds, rnd = settings.intro_rounds, settings.intro_rounds - s.intro_left + 1
    elif mode == "drill":
        rounds, rnd = settings.drill_rounds, settings.drill_rounds - s.drills_owed + 1
    else:
        rounds, rnd = 1, 1
    return NextOut(remaining=_tasks_left(q), task=Task(
        mode=mode, kind=kind, round=max(1, rnd), rounds=rounds, item=item_out(row),
        prompt=PromptOut(id=prompt["id"], kind=prompt["kind"], zh=prompt["zh"], topic=prompt["topic"])))


@app.post("/api/answer", response_model=AnswerOut)
async def answer(prompt_id: int = Form(...), think_ms: int = Form(0, ge=0, le=3_600_000), hinted: int = Form(0, ge=0, le=1),
                 audio: UploadFile = File(...)):
    prompt = db.get_prompt(prompt_id)
    if not prompt:
        raise ApiError(404, "NOT_FOUND", "没有这道题。")
    row = _item_or_404(prompt["item_id"])
    if row["status"] not in ("active", "graduated"):
        raise ApiError(409, "BAD_STATE", "这个表达现在不在练习队列里。")
    data = await audio.read()
    if len(data) > MAX_AUDIO:
        raise ApiError(413, "AUDIO_TOO_LARGE", "录音太大了（超过 8 MB），说短一点再试。")
    ext = AUDIO_EXT.get((audio.content_type or "").split(";")[0].strip().lower(), "webm")

    if settings.fake_upstream:
        said, first = fake.transcript(row, prompt, len(db.reviews_since("")))
    else:
        if len(data) < 1000:
            raise ApiError(422, "NO_SPEECH", "没录到声音，再说一次。")
        said, first = await transcribe(data, ext)
    # 录音太短或几乎没声音时，Whisper 会凭空编出 "You"、"Thank you." 这类词。
    # 一句完整的回答不会少于 3 个词，所以不足 3 个词就当没听清，不拿去判定，免得表达被冤枉退级。
    if len(re.findall(r"[A-Za-z']+", said)) < MIN_WORDS:
        raise ApiError(422, "NO_SPEECH", "没听清你说的，再说一次。")
    verdict = await coach.judge(row, prompt, said)

    before, t = db.state_of(row), today()
    # 阶梯只看目标表达本身；句子别处的错只顺带一提，不挡升级
    result = sched.result_of(verdict["used"], verdict["target_ok"], bool(hinted))
    after = sched.apply(before, result, t, settings.drill_rounds)
    name = f"{uuid.uuid4().hex[:16]}.{ext}"
    (settings.data_dir / "audio" / name).write_bytes(data)
    review_id = db.add_review(row["id"], after, {
        "prompt_id": prompt["id"], "kind": prompt["kind"], "mode": sched.mode_of(before), "transcript": said,
        # correct 存「整句没问题」：表达用对且没有任何要改的地方
        "used": int(verdict["used"]), "correct": int(verdict["target_ok"] and not verdict["fix"]), "hinted": int(bool(hinted)),
        "fix_json": json.dumps(verdict["fix"], ensure_ascii=False) if verdict["fix"] else "",
        "natural": verdict["natural"], "result": result, "think_ms": think_ms, "latency_ms": think_ms + int(first * 1000),
        "before_json": json.dumps(before.__dict__), "after_json": json.dumps(after.__dict__),
        "audio": name, "day": t.isoformat(), "created_at": db.now_iso()})
    return _answer_out(review_id)


@app.post("/api/reviews/{review_id}/override", response_model=AnswerOut)
def override(review_id: int, body: OverrideIn):
    r = db.get_review(review_id)
    if not r:
        raise ApiError(404, "NOT_FOUND", "没有这条练习记录。")
    if db.latest_review_id(r["item_id"]) != review_id:
        raise ApiError(409, "BAD_STATE", "只能改判这个表达最新的一次练习。")
    before = sched.State(**json.loads(r["before_json"]))
    after = sched.apply(before, body.result, date.fromisoformat(r["day"]), settings.drill_rounds)
    db.override_review(review_id, r["item_id"], body.result, used=body.result != "fail", correct=body.result == "pass", after=after)
    return _answer_out(review_id)


@app.post("/api/reviews/{review_id}/collect", response_model=ItemOut, status_code=201)
def collect(review_id: int, response: Response):
    """把这条练习里「顺带一提」的错误收进我的纠错：新建一条 fix 表达（不自动激活）。重复调用返回已有那条。"""
    r = db.get_review(review_id)
    if not r:
        raise ApiError(404, "NOT_FOUND", "没有这条练习记录。")
    fix = _fix_of(r)
    if not fix or fix.scope != "other":
        raise ApiError(409, "BAD_STATE", "这条练习没有可以收进纠错的错误。")
    item_id = _collect_id(review_id)
    old = db.get_item(item_id)
    if old:
        response.status_code = 200
        return item_out(old)
    text = r["natural"] or r["transcript"].replace(fix.quote, fix.better)
    db.insert_item({"id": item_id, "source": "fix", "text": text[:300], "wrong": r["transcript"][:300],
                    "zh": f"「{fix.quote}」→「{fix.better}」：{fix.why}"[:300], "created_at": db.now_iso()})
    return item_out(db.get_item(item_id))


@app.get("/api/reviews/{review_id}/audio")
def review_audio(review_id: int):
    r = db.get_review(review_id)
    f = settings.data_dir / "audio" / r["audio"] if r and r["audio"] else None
    if not f or not f.exists():
        raise ApiError(404, "NOT_FOUND", "这条练习没有录音。")
    return FileResponse(f)


# ---------- 表达库 ----------

@app.get("/api/library", response_model=LibraryOut)
def library():
    rows, lat = db.all_items(), db.last_latency()
    topics: dict[int, TopicOut] = {}
    for r in rows:
        if r["topic_no"] is None:
            continue
        t = topics.setdefault(r["topic_no"], TopicOut(no=r["topic_no"], zh=r["topic_zh"], grp=r["grp"], total=0, active=0))
        t.total += 1
        t.active += r["status"] != "library"
    return LibraryOut(items=[item_out(r, lat) for r in rows], topics=sorted(topics.values(), key=lambda x: x.no),
                      new_left=max(0, settings.new_per_day - db.activated_on(today().isoformat())), new_per_day=settings.new_per_day)


@app.get("/api/items/{item_id}", response_model=ItemDetail)
def item_detail(item_id: str):
    row = _item_or_404(item_id)
    hist = []
    for r in db.item_history(item_id):
        p = db.get_prompt(r["prompt_id"])
        hist.append(HistoryRow(review_id=r["id"], day=r["day"], mode=r["mode"], kind=r["kind"], result=r["result"],
                               prompt_zh=p["zh"] if p else "", ref_en=p["ref_en"] if p else "", natural=r["natural"],
                               transcript=r["transcript"], latency_ms=r["latency_ms"], fix=_fix_of(r)))
    return ItemDetail(item=item_out(row, db.last_latency()), history=hist)


@app.post("/api/items", response_model=ItemOut, status_code=201)
def create_item(body: CreateItemIn):
    item_id = f"{'fix' if body.kind == 'fix' else 'my'}-{uuid.uuid4().hex[:8]}"
    db.insert_item({"id": item_id, "source": body.kind, "text": body.text.strip(), "zh": body.zh.strip(),
                    "wrong": body.wrong.strip(), "created_at": db.now_iso()})
    return item_out(db.get_item(item_id))


@app.post("/api/items/{item_id}/activate", response_model=ItemOut)
async def activate(item_id: str, force: bool = False):
    row = _item_or_404(item_id)
    if row["status"] != "library":
        raise ApiError(409, "BAD_STATE", "这个表达已经激活过了。")
    t = today()
    n = db.activated_on(t.isoformat())
    if n >= settings.new_hard_max:
        raise ApiError(409, "DAILY_NEW_LIMIT", f"今天已经激活 {n} 个表达了，到上限了。先把它们练熟，明天再加。")
    if n >= settings.new_per_day and not force:
        raise ApiError(409, "DAILY_NEW_LIMIT", f"今天已经激活 {n} 个表达了。每天只加少量新表达更容易练扎实，确定还要加吗？")
    gen = await coach.generate(row, [])
    db.add_prompts(item_id, gen["prompts"])
    db.set_state(item_id, sched.activate(t, settings.intro_rounds), frame=gen["frame"] or (row["text"] if row["source"] == "chunk" else ""),
                 frame_zh=gen["frame_zh"], scene=gen["scene"] or row["usage"], activated_at=db.now_iso())
    return item_out(db.get_item(item_id))


@app.post("/api/items/{item_id}/pause", response_model=ItemOut)
def pause(item_id: str):
    row = _item_or_404(item_id)
    if row["status"] not in ("active", "graduated"):
        raise ApiError(409, "BAD_STATE", "只有练习中的表达可以暂停。")
    db.set_state(item_id, sched.replace(db.state_of(row), status="paused"))
    return item_out(db.get_item(item_id))


@app.post("/api/items/{item_id}/resume", response_model=ItemOut)
def resume(item_id: str):
    row = _item_or_404(item_id)
    if row["status"] != "paused":
        raise ApiError(409, "BAD_STATE", "这个表达没有暂停。")
    t = today().isoformat()
    db.set_state(item_id, sched.replace(db.state_of(row), status="active", due=max(row["due"] or t, t)))
    return item_out(db.get_item(item_id))


@app.delete("/api/items/{item_id}", status_code=204)
def delete_item(item_id: str):
    row = _item_or_404(item_id)
    if row["source"] not in ("fix", "custom"):
        raise ApiError(409, "BAD_STATE", "素材库里的表达不能删除，可以暂停。")
    db.delete_item(item_id)
    return Response(status_code=204)


# ---------- 进度墙 ----------

@app.get("/api/wall", response_model=WallOut)
def wall():
    t, lat = today(), db.last_latency()
    rows = [r for r in db.all_items() if r["status"] != "library"]
    by_step = [0] * 7
    for r in rows:
        by_step[6 if r["status"] == "graduated" else min(r["step"], 5)] += 1
    recent = db.reviews_since((t - timedelta(days=13)).isoformat())
    per_day: dict[str, list[int]] = {}
    for r in recent:
        if r["mode"] != "drill" and r["latency_ms"] > 0:
            per_day.setdefault(r["day"], []).append(r["latency_ms"])
    week = [r for r in recent if r["day"] >= (t - timedelta(days=6)).isoformat()]
    graded = [r for r in week if r["mode"] in ("review", "check")]
    rows.sort(key=lambda r: (r["status"] == "graduated", r["step"], r["activated_at"] or ""), reverse=True)
    return WallOut(
        bricks=[item_out(r, lat) for r in rows], by_step=by_step,
        latency=[LatencyPoint(day=d, ms=int(statistics.median(v)), n=len(v)) for d, v in sorted(per_day.items())],
        reviews_7d=len(week), pass_rate_7d=round(sum(r["result"] == "pass" for r in graded) / len(graded), 2) if graded else None,
        streak=_streak(db.review_days(), t))


# ---------- 前端静态文件 ----------

@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    f = (STATIC / path).resolve()
    if path and f.is_file() and STATIC.resolve() in f.parents:
        return FileResponse(f)
    index = STATIC / "index.html"
    if path.startswith("api/") or not index.exists():
        return _error(404, "NOT_FOUND", "没有这个地址。")
    return FileResponse(index)
