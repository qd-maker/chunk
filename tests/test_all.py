"""排期规则 + 接口全流程。全部走假上游，不花钱。"""
import json
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app import auth, coach, db, fake, main, sched
from app.config import settings

D = date(2026, 11, 13)
# 测试用的小素材库（原创句子，结构同 examples/library.example.json）
LIBRARY = {
    "patterns": [{"no": 9, "text": "I'm used to getting up early now.", "zh": "我现在已经习惯早起了。",
                  "example": "I'm used to living on my own.", "example_zh": "我已经习惯一个人住了。", "first_batch": True}],
    "links": [{"no": 2, "cat": "补充", "text": "On top of that, the food there is great.", "zh": "而且，那儿的东西还特别好吃。",
               "example": "On top of that, it's only ten minutes from my school.", "example_zh": "而且，离我学校只要十分钟。",
               "usage": "已经给了一个理由，再加一个更有分量的。"}],
    "topics": [{"no": 1, "group": "A", "zh": "最近的生活", "en": "Life Lately",
                "chunks": [{"text": "have been pretty busy lately", "zh": "最近挺忙的"},
                           {"text": "catch up on sleep", "zh": "补觉"}],
                "patterns": [{"text": "Nothing much, just the usual.", "zh": "没什么，还是老样子。"}],
                "questions": [{"text": "What have you been up to lately?", "zh": "你最近在忙什么？"}]}],
}


# ---------- 排期（纯函数） ----------

def test_ladder_from_activation_to_graduation():
    s = sched.activate(D, 3)
    assert (sched.mode_of(s), sched.kind_of(s)) == ("intro", "swap")
    for _ in range(3):
        s = sched.apply(s, "fail", D)                      # intro 不看对错，只消耗轮数
    assert (s.step, s.due, s.lapses) == (1, "2026-11-14", 0)
    day, seen = D, []
    for gap, kind in [(1, "swap"), (3, "cross"), (7, "cross"), (14, "self"), (30, "self")]:
        day = date.fromisoformat(s.due)
        seen.append(((day - D).days, sched.kind_of(s)))
        s = sched.apply(s, "pass", day)
    assert [k for _, k in seen] == ["swap", "cross", "cross", "self", "self"]
    assert [d for d, _ in seen] == [1, 4, 11, 25, 55]       # 1、+3、+7、+14、+30
    assert s.status == "graduated" and s.due == (day + timedelta(days=30)).isoformat()
    assert (sched.mode_of(s), sched.kind_of(s)) == ("check", "self")


def test_hold_stays_and_fail_drops_with_drills():
    s = sched.State("active", 3, D.isoformat(), 0, 0, 0)
    hold = sched.apply(s, "hold", D)
    assert (hold.step, hold.due, hold.drills_owed) == (3, "2026-11-14", 0)
    bad = sched.apply(s, "fail", D)
    assert (bad.step, bad.due, bad.lapses, bad.drills_owed) == (2, "2026-11-14", 1, 2)
    assert sched.mode_of(bad) == "drill"
    after = sched.apply(sched.apply(bad, "fail", D), "pass", D)   # 两道补练做完，不再动阶梯
    assert (after.step, after.drills_owed, after.lapses) == (2, 0, 1)
    assert sched.apply(sched.State("active", 1, D.isoformat(), 0, 0, 0), "fail", D).step == 1   # 最低退到第 1 级


def test_graduated_check():
    g = sched.State("graduated", 5, D.isoformat(), 0, 0, 0)
    assert sched.apply(g, "pass", D).due == "2026-12-13"
    back = sched.apply(g, "fail", D)
    assert (back.status, back.step, back.drills_owed) == ("active", 3, 2)


def test_result_rule():
    assert sched.result_of(True, True, False) == "pass"
    assert sched.result_of(True, True, True) == "hold"      # 看了提示
    assert sched.result_of(True, False, False) == "hold"    # 用上了但表达本身形式错
    assert sched.result_of(False, True, False) == "fail"    # 没用上


# ---------- 接口 ----------

@pytest.fixture
def client(tmp_path, monkeypatch):
    (tmp_path / "library.json").write_text(json.dumps(LIBRARY, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "fake_upstream", True)
    monkeypatch.setattr(settings, "app_password", "")
    monkeypatch.setattr(settings, "new_per_day", 3)
    monkeypatch.setattr(main, "today", lambda: D)
    monkeypatch.setattr(fake, "FORCE", "pass")
    auth._failures.clear()
    with TestClient(main.app) as c:
        yield c


def say(c, hinted=0, think_ms=1500):
    task = c.get("/api/next").json()["task"]
    r = c.post("/api/answer", data={"prompt_id": task["prompt"]["id"], "think_ms": think_ms, "hinted": hinted},
               files={"audio": ("a.webm", b"x" * 20, "audio/webm")})
    assert r.status_code == 200, r.text
    return task, r.json()


def intro(c, item_id="IV-09"):
    assert c.post(f"/api/items/{item_id}/activate").status_code == 200
    for _ in range(3):
        say(c)


def test_library_is_imported(client):
    lib = client.get("/api/library").json()
    assert {i["id"] for i in lib["items"]} == {"IV-09", "V-02", "VI-01-c1", "VI-01-c2", "VI-01-p1"}
    assert lib["topics"] == [{"no": 1, "zh": "最近的生活", "grp": "A", "total": 3, "active": 0}]
    assert all(i["status"] == "library" for i in lib["items"]) and lib["new_left"] == 3


def test_library_file_name_fallback(tmp_path, monkeypatch):
    """优先 library.json；没有时认旧文件名 guide.json（已有部署在用）。"""
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    (tmp_path / "guide.json").write_text(json.dumps(LIBRARY, ensure_ascii=False), encoding="utf-8")
    assert db.library_file().name == "guide.json" and db.init() == 5
    (tmp_path / "library.json").write_text("{}", encoding="utf-8")
    assert db.library_file().name == "library.json"
    assert db.init() == 5                                          # 库里已有数据：不再导入


def test_example_library_imports():
    from pathlib import Path
    lib = json.loads((Path(__file__).resolve().parent.parent / "examples" / "library.example.json").read_text(encoding="utf-8"))
    assert (len(lib["patterns"]), len(lib["links"]), len(lib["topics"])) == (12, 6, 3)
    assert sum(p["first_batch"] for p in lib["patterns"]) == 5
    assert all(len(t["chunks"]) == 6 and len(t["patterns"]) == 2 and len(t["questions"]) == 3 for t in lib["topics"])
    assert set(fake.DEMO) <= {f"IV-{p['no']:02d}" for p in lib["patterns"]} | {f"VI-{t['no']:02d}-c{i}" for t in lib["topics"] for i in range(1, 7)}


def test_activate_then_intro_three_swaps(client):
    item = client.post("/api/items/IV-09/activate").json()
    assert (item["status"], item["step"], item["intro_left"], item["frame_zh"]) == ("active", 0, 3, "已经习惯……了")
    seen = []
    for rnd in (1, 2, 3):
        task, out = say(client)
        assert (task["mode"], task["kind"], task["round"], task["rounds"]) == ("intro", "swap", rnd, 3)
        assert not any(ch.isascii() and ch.isalpha() for ch in task["prompt"]["zh"])   # 题面只有中文
        assert out["result"] == "pass" and out["latency_ms"] == 1500 + 600
        seen.append(task["prompt"]["zh"])
    assert len(set(seen)) == 3                                    # 每道题都换内容
    item = client.get("/api/items/IV-09").json()
    assert (item["item"]["step"], item["item"]["due"], len(item["history"])) == (1, "2026-11-14", 3)
    h = item["history"][0]                                        # 最新一条：能看到题面、参考答案和自然说法
    assert h["prompt_zh"] == seen[-1] and h["ref_en"].startswith("I") and "used to" in h["ref_en"]
    assert h["natural"] == h["ref_en"]                            # 假判定的 natural 就是参考答案
    assert out["ref_en"] == h["ref_en"]
    assert client.get("/api/next").json() == {"task": None, "remaining": 0}
    assert client.get("/api/today").json()["done_today"] == 3


def test_fail_gives_two_drills_then_comes_back_tomorrow(client, monkeypatch):
    intro(client)
    monkeypatch.setattr(main, "today", lambda: D + timedelta(days=1))
    monkeypatch.setattr(fake, "FORCE", "fail")
    task, out = say(client)
    assert (task["mode"], out["result"], out["used"], out["drills_owed"]) == ("review", "fail", False, 2)
    assert out["fix"]["why"] and out["step_after"] == 1 and out["due_after"] == "2026-11-15"
    monkeypatch.setattr(fake, "FORCE", "pass")
    for rnd in (1, 2):
        task, out = say(client)
        assert (task["mode"], task["kind"], task["round"]) == ("drill", "swap", rnd)
    assert client.get("/api/next").json()["task"] is None
    it = client.get("/api/items/IV-09").json()["item"]
    assert (it["step"], it["lapses"], it["due"], it["drills_owed"]) == (1, 1, "2026-11-15", 0)


def test_pass_climbs_and_changes_question_kind(client, monkeypatch):
    intro(client)
    monkeypatch.setattr(main, "today", lambda: D + timedelta(days=1))
    task, out = say(client)
    assert (task["kind"], out["step_after"], out["due_after"]) == ("swap", 2, "2026-11-17")
    monkeypatch.setattr(main, "today", lambda: D + timedelta(days=4))
    task, out = say(client)
    assert (task["kind"], out["step_after"], out["due_after"]) == ("cross", 3, "2026-11-24")


def test_hint_or_error_holds(client, monkeypatch):
    intro(client)
    monkeypatch.setattr(main, "today", lambda: D + timedelta(days=1))
    _, out = say(client, hinted=1)
    assert (out["result"], out["step_after"], out["due_after"]) == ("hold", 1, "2026-11-15")
    monkeypatch.setattr(main, "today", lambda: D + timedelta(days=2))
    monkeypatch.setattr(fake, "FORCE", "hold")
    _, out = say(client)
    assert (out["used"], out["correct"], out["result"]) == (True, False, "hold") and out["fix"]["better"]
    assert out["fix"]["scope"] == "target" and out["collected"] is False   # 表达本身形式错：仍然 hold


def test_tip_passes_and_climbs(client, monkeypatch):
    """表达用对、句子别处有错：照样升级，错误只顺带一提。"""
    intro(client)
    monkeypatch.setattr(main, "today", lambda: D + timedelta(days=1))
    monkeypatch.setattr(fake, "FORCE", "tip")
    _, out = say(client)
    assert (out["used"], out["correct"], out["result"]) == (True, False, "pass")
    assert (out["step_before"], out["step_after"], out["due_after"]) == (1, 2, "2026-11-17")
    assert out["fix"]["scope"] == "other" and out["fix"]["quote"] in out["transcript"] and out["collected"] is False
    h = client.get("/api/items/IV-09").json()["history"][0]
    assert h["result"] == "pass" and h["fix"] == out["fix"]


def test_hint_plus_tip_still_holds(client, monkeypatch):
    intro(client)
    monkeypatch.setattr(main, "today", lambda: D + timedelta(days=1))
    monkeypatch.setattr(fake, "FORCE", "tip")
    _, out = say(client, hinted=1)
    assert (out["result"], out["step_after"], out["fix"]["scope"]) == ("hold", 1, "other")


def test_collect_tip_into_fixes(client, monkeypatch):
    intro(client)
    monkeypatch.setattr(main, "today", lambda: D + timedelta(days=1))
    monkeypatch.setattr(fake, "FORCE", "tip")
    _, out = say(client)
    rid, fix = out["review_id"], out["fix"]
    r = client.post(f"/api/reviews/{rid}/collect")
    assert r.status_code == 201, r.text
    item = r.json()
    assert (item["id"], item["source"], item["status"]) == (f"fix-r{rid}", "fix", "library")
    assert item["text"] == out["natural"] and item["wrong"] == out["transcript"]
    assert item["zh"] == f"「{fix['quote']}」→「{fix['better']}」：{fix['why']}"
    again = client.post(f"/api/reviews/{rid}/collect")                    # 幂等
    assert again.status_code == 200 and again.json()["id"] == item["id"]
    assert sum(i["id"] == item["id"] for i in client.get("/api/library").json()["items"]) == 1
    assert client.post(f"/api/reviews/{rid}/override", json={"result": "pass"}).json()["collected"] is True
    assert client.delete(f"/api/items/{item['id']}").status_code == 204
    # 删掉纠错后 collected 变回 false（改判接口返回的是同一个 AnswerOut）
    assert client.post(f"/api/reviews/{rid}/override", json={"result": "pass"}).json()["collected"] is False
    assert client.post("/api/reviews/999/collect").status_code == 404


def test_collect_needs_other_fix(client, monkeypatch):
    intro(client)
    monkeypatch.setattr(main, "today", lambda: D + timedelta(days=1))
    monkeypatch.setattr(fake, "FORCE", "hold")
    _, out = say(client)
    r = client.post(f"/api/reviews/{out['review_id']}/collect")
    assert r.status_code == 409 and r.json()["error"]["code"] == "BAD_STATE"
    clean = client.get("/api/items/IV-09").json()["history"][-1]          # intro 时说得完全对，没有 fix
    assert clean["fix"] is None and client.post(f"/api/reviews/{clean['review_id']}/collect").status_code == 409


def test_old_fix_json_without_scope(client, monkeypatch):
    intro(client)
    monkeypatch.setattr(main, "today", lambda: D + timedelta(days=1))
    monkeypatch.setattr(fake, "FORCE", "tip")
    _, out = say(client)
    with db.conn() as c:   # 模拟改版前的记录：fix_json 里没有 scope
        c.execute("UPDATE reviews SET fix_json = ? WHERE id = ?",
                  (json.dumps({"quote": "used to get", "better": "used to getting", "why": "接 doing"}, ensure_ascii=False), out["review_id"]))
    h = client.get("/api/items/IV-09").json()["history"][0]
    assert h["fix"] == {"quote": "used to get", "better": "used to getting", "why": "接 doing", "scope": "target"}
    assert client.post(f"/api/reviews/{out['review_id']}/collect").status_code == 409
    assert client.post(f"/api/reviews/{out['review_id']}/override", json={"result": "hold"}).json()["fix"]["scope"] == "target"


def test_parse_verdict_is_forgiving():
    fix = {"quote": "don't", "better": "doesn't", "why": "三单"}
    v = coach.parse_verdict({"used": True, "correct": True, "fix": None, "natural": "x"})       # 旧字段 correct
    assert (v["used"], v["target_ok"], v["fix"]) == (True, True, None)
    v = coach.parse_verdict({"used": True, "target_ok": True, "fix": {**fix, "scope": "target"}})  # 矛盾：以 target_ok 为准
    assert v["fix"]["scope"] == "other" and v["target_ok"] is True
    assert coach.parse_verdict({"used": True, "target_ok": True, "fix": {**fix, "scope": "?"}})["fix"]["scope"] == "other"
    assert coach.parse_verdict({"used": True, "target_ok": False, "fix": fix})["fix"]["scope"] == "target"
    v = coach.parse_verdict({"used": "false", "target_ok": True, "fix": {**fix, "scope": "other"}}, "ref")
    assert (v["used"], v["target_ok"], v["fix"]["scope"], v["natural"]) == (False, False, "target", "ref")


def test_override_rejudges_latest_only(client, monkeypatch):
    intro(client)
    monkeypatch.setattr(main, "today", lambda: D + timedelta(days=1))
    monkeypatch.setattr(fake, "FORCE", "fail")
    _, out = say(client)
    r = client.post(f"/api/reviews/{out['review_id']}/override", json={"result": "pass"}).json()
    assert (r["result"], r["step_after"], r["drills_owed"], r["overridden"]) == ("pass", 2, 0, True)
    assert client.get("/api/items/IV-09").json()["item"]["lapses"] == 0
    old = client.get("/api/items/IV-09").json()["history"][-1]["review_id"]
    assert client.post(f"/api/reviews/{old}/override", json={"result": "fail"}).json()["error"]["code"] == "BAD_STATE"


def test_daily_new_limit(client, monkeypatch):
    monkeypatch.setattr(settings, "new_per_day", 1)
    monkeypatch.setattr(settings, "new_hard_max", 2)
    # activated_at 用的是真实时钟，这里的「今天」也得用真实日期，否则只有 D 当天才能通过
    monkeypatch.setattr(main, "today", lambda: date.fromisoformat(db.now_iso()[:10]))
    assert client.post("/api/items/IV-09/activate").status_code == 200
    r = client.post("/api/items/V-02/activate")
    assert r.status_code == 409 and r.json()["error"]["code"] == "DAILY_NEW_LIMIT"
    assert client.post("/api/items/V-02/activate?force=true").status_code == 200
    assert client.post("/api/items/VI-01-c1/activate?force=true").status_code == 409      # 硬上限
    assert client.post("/api/items/IV-09/activate").json()["error"]["code"] == "BAD_STATE"


def test_fix_items_and_errors(client):
    r = client.post("/api/items", json={"kind": "fix", "text": "I sent out more than ten resumes.", "zh": "可数名词复数",
                                        "wrong": "I send more than ten resume."})
    assert r.status_code == 201 and r.json()["source"] == "fix" and r.json()["wrong"]
    fix_id = r.json()["id"]
    assert client.post(f"/api/items/{fix_id}/activate").json()["status"] == "active"
    assert client.get("/api/next").json()["task"]["item"]["id"] == fix_id
    assert client.delete(f"/api/items/{fix_id}").status_code == 204
    assert client.delete("/api/items/IV-09").json()["error"]["code"] == "BAD_STATE"
    bad = client.post("/api/items", json={"kind": "nope", "text": "x"})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "VALIDATION_ERROR"
    assert client.get("/api/items/nope").json() == {"error": {"code": "NOT_FOUND", "message": "没有这个表达。"}}
    assert client.post("/api/answer", data={"prompt_id": 999}, files={"audio": ("a.webm", b"x", "audio/webm")}).status_code == 404


def test_pause_resume_and_wall(client, monkeypatch):
    intro(client)
    assert client.post("/api/items/IV-09/pause").json()["status"] == "paused"
    monkeypatch.setattr(main, "today", lambda: D + timedelta(days=5))
    assert client.get("/api/next").json()["task"] is None                       # 暂停的不出题
    assert client.post("/api/items/IV-09/resume").json()["due"] == "2026-11-18"   # 恢复后今天就到期
    wall = client.get("/api/wall").json()
    assert [b["id"] for b in wall["bricks"]] == ["IV-09"] and wall["by_step"][1] == 1
    assert wall["latency"] == [{"day": "2026-11-13", "ms": 2100, "n": 3}]
    t = client.get("/api/today").json()
    assert (t["due"], t["active"], t["streak"]) == (1, 1, 0)


def test_password_login(client, monkeypatch):
    monkeypatch.setattr(settings, "app_password", "s3cret")
    assert client.get("/api/health").json()["auth_required"] is True
    assert client.get("/api/today").json()["error"]["code"] == "UNAUTHORIZED"
    assert client.post("/api/login", json={"password": "wrong"}).json()["error"]["code"] == "BAD_PASSWORD"
    assert client.post("/api/login", json={"password": "s3cret"}).status_code == 204
    assert client.get("/api/today").status_code == 200
    client.post("/api/logout")
    assert client.get("/api/today").status_code == 401


def test_too_short_transcript_is_not_judged(client, monkeypatch):
    """Whisper 在录音太短时会编出 "You" 这类词：不判定、不记录、不动排期，让他再说一次。"""
    client.post("/api/items/IV-09/activate")
    task = client.get("/api/next").json()["task"]
    monkeypatch.setattr(fake, "transcript", lambda *a: ("You", 0.2))
    r = client.post("/api/answer", data={"prompt_id": task["prompt"]["id"]}, files={"audio": ("a.webm", b"x" * 20, "audio/webm")})
    assert r.status_code == 422 and r.json()["error"]["code"] == "NO_SPEECH"
    it = client.get("/api/items/IV-09").json()
    assert it["history"] == [] and it["item"]["intro_left"] == 3
    assert client.get("/api/next").json()["task"]["prompt"]["id"] == task["prompt"]["id"]   # 还是同一道题


def test_chat_json_retries_once_on_bad_json(monkeypatch):
    """大模型偶尔返回坏掉的 JSON：自动重问一次，第二次好了就用；两次都坏才报错。"""
    import asyncio
    from app import upstream
    replies = ['{"used": true, "why": "用 "doesn\'t" 才对"}', '{"used": true}']
    calls = []

    async def fake_post(url, key, body, timeout, code, retries=1):
        calls.append(1)
        return {"choices": [{"message": {"content": replies[min(len(calls), len(replies)) - 1]}}], "usage": {"prompt_tokens": 10}}

    monkeypatch.setattr(upstream, "_post", fake_post)
    assert asyncio.run(upstream.chat_json("s", "u")) == {"used": True}
    assert len(calls) == 2
    replies[1] = "还是坏的"
    calls.clear()
    with pytest.raises(upstream.ApiError):
        asyncio.run(upstream.chat_json("s", "u"))
    assert len(calls) == 2
