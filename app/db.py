"""SQLite：表达 items、题库 prompts、练习记录 reviews。单用户自用，不上 ORM。"""
import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime

from .config import settings
from .sched import State

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,              -- pattern / link / chunk / topic_pattern / fix / custom
    topic_no INTEGER, topic_zh TEXT NOT NULL DEFAULT '', grp TEXT NOT NULL DEFAULT '',
    text TEXT NOT NULL, zh TEXT NOT NULL DEFAULT '',
    example TEXT NOT NULL DEFAULT '', example_zh TEXT NOT NULL DEFAULT '',
    usage TEXT NOT NULL DEFAULT '', wrong TEXT NOT NULL DEFAULT '',
    first_batch INTEGER NOT NULL DEFAULT 0,
    frame TEXT NOT NULL DEFAULT '', frame_zh TEXT NOT NULL DEFAULT '', scene TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'library',
    step INTEGER NOT NULL DEFAULT 0, due TEXT,
    intro_left INTEGER NOT NULL DEFAULT 0, drills_owed INTEGER NOT NULL DEFAULT 0,
    reps INTEGER NOT NULL DEFAULT 0, lapses INTEGER NOT NULL DEFAULT 0,
    activated_at TEXT, last_reviewed TEXT, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_items_due ON items(status, due);
CREATE TABLE IF NOT EXISTS prompts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    kind TEXT NOT NULL, zh TEXT NOT NULL, ref_en TEXT NOT NULL DEFAULT '', topic TEXT NOT NULL DEFAULT '',
    used_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_prompts_item ON prompts(item_id, kind, used_at);
CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    prompt_id INTEGER NOT NULL, kind TEXT NOT NULL, mode TEXT NOT NULL,
    transcript TEXT NOT NULL, used INTEGER NOT NULL, correct INTEGER NOT NULL, hinted INTEGER NOT NULL,
    fix_json TEXT NOT NULL DEFAULT '', natural TEXT NOT NULL DEFAULT '',
    result TEXT NOT NULL, think_ms INTEGER NOT NULL DEFAULT 0, latency_ms INTEGER NOT NULL DEFAULT 0,
    before_json TEXT NOT NULL, after_json TEXT NOT NULL,
    audio TEXT NOT NULL DEFAULT '', day TEXT NOT NULL, created_at TEXT NOT NULL, overridden INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_reviews_item ON reviews(item_id, id);
CREATE INDEX IF NOT EXISTS idx_reviews_day ON reviews(day);
"""

STATE_COLS = ("status", "step", "due", "intro_left", "drills_owed", "lapses")


def path():
    return settings.data_dir / "chunk.db"


@contextmanager
def conn():
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path())
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    try:
        yield c
        c.commit()
    finally:
        c.close()


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


LIBRARY_FILES = ("library.json", "guide.json")   # 素材库文件名；guide.json 是旧名字，兼容已有部署


def library_file():
    """数据目录里的素材库文件：优先 library.json，没有再找旧名 guide.json；都没有返回 None。"""
    return next((p for p in (settings.data_dir / n for n in LIBRARY_FILES) if p.exists()), None)


def init() -> int:
    """建表；库是空的且数据目录里有素材库文件时导入。返回表达总数。"""
    with conn() as c:
        c.executescript(SCHEMA)
        n = c.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    src = library_file()
    if n == 0 and src:
        n = import_library(json.loads(src.read_text(encoding="utf-8")))
    return n


def import_library(g: dict) -> int:
    """把素材库（patterns / links / topics）写进 items。id 规则：句式 IV-NN、衔接 V-NN、
    话题词块 VI-NN-cK、话题句式 VI-NN-pK（NN 为两位编号）。已存在的 id 跳过。"""
    rows, now = [], now_iso()

    def add(id_, source, text, zh, **kw):
        rows.append({"id": id_, "source": source, "text": text, "zh": zh, "topic_no": None, "topic_zh": "", "grp": "",
                     "example": "", "example_zh": "", "usage": "", "first_batch": 0, "created_at": now, **kw})

    for p in g["patterns"]:
        add(f"IV-{p['no']:02d}", "pattern", p["text"], p["zh"], example=p["example"], example_zh=p["example_zh"],
            first_batch=int(p.get("first_batch", False)))
    for p in g["links"]:
        add(f"V-{p['no']:02d}", "link", p["text"], p["zh"], example=p["example"], example_zh=p["example_zh"],
            usage=p["usage"], topic_zh=p["cat"])
    for t in g["topics"]:
        common = {"topic_no": t["no"], "topic_zh": t["zh"], "grp": t["group"]}
        for i, x in enumerate(t["chunks"], 1):
            add(f"VI-{t['no']:02d}-c{i}", "chunk", x["text"], x["zh"], **common)
        for i, x in enumerate(t["patterns"], 1):
            add(f"VI-{t['no']:02d}-p{i}", "topic_pattern", x["text"], x["zh"], **common)
    with conn() as c:
        c.executemany(
            "INSERT OR IGNORE INTO items (id, source, topic_no, topic_zh, grp, text, zh, example, example_zh, usage, first_batch, created_at) "
            "VALUES (:id, :source, :topic_no, :topic_zh, :grp, :text, :zh, :example, :example_zh, :usage, :first_batch, :created_at)", rows)
    return len(rows)


# ---------- items ----------

def get_item(item_id: str) -> sqlite3.Row | None:
    with conn() as c:
        return c.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()


def all_items() -> list[sqlite3.Row]:
    with conn() as c:
        return c.execute("SELECT * FROM items ORDER BY source = 'fix' DESC, id").fetchall()


def insert_item(row: dict) -> None:
    with conn() as c:
        c.execute("INSERT INTO items (id, source, text, zh, wrong, created_at) VALUES (:id, :source, :text, :zh, :wrong, :created_at)", row)


def delete_item(item_id: str) -> None:
    with conn() as c:
        c.execute("DELETE FROM items WHERE id = ?", (item_id,))


def state_of(row: sqlite3.Row) -> State:
    return State(*(row[k] for k in STATE_COLS))


def save_state(c: sqlite3.Connection, item_id: str, s: State, **extra) -> None:
    cols = {k: getattr(s, k) for k in STATE_COLS} | extra
    c.execute(f"UPDATE items SET {', '.join(f'{k} = ?' for k in cols)} WHERE id = ?", (*cols.values(), item_id))


def set_state(item_id: str, s: State, **extra) -> None:
    with conn() as c:
        save_state(c, item_id, s, **extra)


def activated_on(day: str) -> int:
    with conn() as c:
        return c.execute("SELECT COUNT(*) FROM items WHERE substr(activated_at, 1, 10) = ?", (day,)).fetchone()[0]


def queue(today: date, cap: int) -> list[sqlite3.Row]:
    """今天要练的表达，顺序：欠补练的 → 到期复习（最早到期的先，最多 cap 个）→ 今天新激活还没做完 intro 的。
    今天已经复习过的到期项不算在 cap 里：cap 限制的是一天的总量。"""
    t = today.isoformat()
    with conn() as c:
        drills = c.execute("SELECT * FROM items WHERE drills_owed > 0 AND status IN ('active', 'graduated') "
                           "ORDER BY last_reviewed DESC").fetchall()
        done = c.execute("SELECT COUNT(DISTINCT item_id) FROM reviews WHERE day = ? AND mode IN ('review', 'check')", (t,)).fetchone()[0]
        due = c.execute("SELECT * FROM items WHERE status IN ('active', 'graduated') AND intro_left = 0 AND drills_owed = 0 "
                        "AND due <= ? ORDER BY due, id LIMIT ?", (t, max(0, cap - done))).fetchall()
        intro = c.execute("SELECT * FROM items WHERE status = 'active' AND intro_left > 0 AND drills_owed = 0 "
                          "ORDER BY activated_at").fetchall()
    return [*drills, *due, *intro]


# ---------- prompts ----------

def add_prompts(item_id: str, rows: list[dict]) -> None:
    with conn() as c:
        c.executemany("INSERT INTO prompts (item_id, kind, zh, ref_en, topic) VALUES (?, ?, ?, ?, ?)",
                      [(item_id, r["kind"], r["zh"], r.get("en", ""), r.get("topic", "")) for r in rows])


def fresh_prompt(item_id: str, kind: str) -> sqlite3.Row | None:
    with conn() as c:
        return c.execute("SELECT * FROM prompts WHERE item_id = ? AND kind = ? AND used_at IS NULL ORDER BY id LIMIT 1",
                         (item_id, kind)).fetchone()


def stale_prompt(item_id: str, kind: str) -> sqlite3.Row | None:
    """题库用完又生成失败时的退路：拿最久没用过的旧题。"""
    with conn() as c:
        return c.execute("SELECT * FROM prompts WHERE item_id = ? AND kind = ? ORDER BY used_at LIMIT 1", (item_id, kind)).fetchone()


def get_prompt(prompt_id: int) -> sqlite3.Row | None:
    with conn() as c:
        return c.execute("SELECT * FROM prompts WHERE id = ?", (prompt_id,)).fetchone()


def prompt_texts(item_id: str) -> list[str]:
    with conn() as c:
        return [r[0] for r in c.execute("SELECT zh FROM prompts WHERE item_id = ?", (item_id,))]


# ---------- reviews ----------

def add_review(item_id: str, after: State, row: dict) -> int:
    """记一条练习，并把表达推进到新状态（同一个事务）。"""
    with conn() as c:
        cur = c.execute(
            "INSERT INTO reviews (item_id, prompt_id, kind, mode, transcript, used, correct, hinted, fix_json, natural, result, "
            "think_ms, latency_ms, before_json, after_json, audio, day, created_at) VALUES (:item_id, :prompt_id, :kind, :mode, "
            ":transcript, :used, :correct, :hinted, :fix_json, :natural, :result, :think_ms, :latency_ms, :before_json, :after_json, "
            ":audio, :day, :created_at)", {"item_id": item_id, **row})
        c.execute("UPDATE prompts SET used_at = ? WHERE id = ?", (row["created_at"], row["prompt_id"]))
        save_state(c, item_id, after, last_reviewed=row["created_at"])
        c.execute("UPDATE items SET reps = reps + 1 WHERE id = ?", (item_id,))
        return cur.lastrowid


def get_review(review_id: int) -> sqlite3.Row | None:
    with conn() as c:
        return c.execute("SELECT * FROM reviews WHERE id = ?", (review_id,)).fetchone()


def latest_review_id(item_id: str) -> int | None:
    with conn() as c:
        r = c.execute("SELECT MAX(id) FROM reviews WHERE item_id = ?", (item_id,)).fetchone()
        return r[0]


def override_review(review_id: int, item_id: str, result: str, used: bool, correct: bool, after: State) -> None:
    with conn() as c:
        c.execute("UPDATE reviews SET result = ?, used = ?, correct = ?, after_json = ?, overridden = 1 WHERE id = ?",
                  (result, int(used), int(correct), json.dumps(after.__dict__), review_id))
        save_state(c, item_id, after)


def set_review_audio(review_id: int, name: str) -> None:
    with conn() as c:
        c.execute("UPDATE reviews SET audio = ? WHERE id = ?", (name, review_id))


def item_history(item_id: str, limit: int = 20) -> list[sqlite3.Row]:
    with conn() as c:
        return c.execute("SELECT * FROM reviews WHERE item_id = ? ORDER BY id DESC LIMIT ?", (item_id, limit)).fetchall()


def review_days() -> list[str]:
    with conn() as c:
        return [r[0] for r in c.execute("SELECT DISTINCT day FROM reviews ORDER BY day DESC")]


def reviews_since(day: str) -> list[sqlite3.Row]:
    with conn() as c:
        return c.execute("SELECT * FROM reviews WHERE day >= ? ORDER BY id", (day,)).fetchall()


def count_on(day: str) -> int:
    with conn() as c:
        return c.execute("SELECT COUNT(*) FROM reviews WHERE day = ?", (day,)).fetchone()[0]


def last_latency() -> dict[str, int]:
    """每个表达最近一次复习（不含补练）的开口延迟。"""
    with conn() as c:
        rows = c.execute("SELECT item_id, latency_ms FROM reviews WHERE id IN "
                         "(SELECT MAX(id) FROM reviews WHERE mode != 'drill' GROUP BY item_id)").fetchall()
    return {r["item_id"]: r["latency_ms"] for r in rows}
