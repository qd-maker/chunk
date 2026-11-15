"""给演示库 data-demo 铺一些假的练习历史，好看进度墙和延迟曲线长什么样。只动 data-demo，不碰真实数据。
会清空并重建 data-demo，素材用 examples/library.example.json（下面 PLAN 里的 id 都来自它）。

用法：.venv/Scripts/python scripts/seed_demo.py   （先停掉演示服务，跑完再启动）
"""
import json
import os
import random
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "data-demo"
if DEMO.exists():
    shutil.rmtree(DEMO)
DEMO.mkdir()
shutil.copy(ROOT / "examples" / "library.example.json", DEMO / "library.json")
os.environ.update(FAKE_UPSTREAM="true", DATA_DIR=str(DEMO), APP_PASSWORD="")
sys.path.insert(0, str(ROOT))

from app import db, fake, sched  # noqa: E402

# (表达, 几天前激活, 之后每次复习的结果)
PLAN = [
    ("IV-09", 12, "ppp"), ("VI-01-c2", 12, "pp"), ("IV-05", 11, "pfp"), ("V-02", 10, "tp"), ("VI-02-c3", 9, "php"),
    ("IV-01", 8, "pt"), ("VI-03-c1", 7, "p"), ("V-03", 6, "pf"), ("IV-03", 5, "p"), ("VI-02-c5", 4, "h"),
    ("IV-08", 3, "p"), ("VI-03-c4", 2, ""), ("V-01", 1, ""), ("IV-12", 60, "ppppp"),
]
VARIANT = {"p": "pass", "t": "tip", "h": "hold", "f": "fail"}   # t = 表达用对、别处有错，照样升级


def answer(item_id: str, day: date, variant: str, rng: random.Random, speed: float) -> None:
    row = db.get_item(item_id)
    s = db.state_of(row)
    mode, kind = sched.mode_of(s), sched.kind_of(s)
    prompt = db.fresh_prompt(item_id, kind) or db.stale_prompt(item_id, kind)
    fake.FORCE = variant
    said, first = fake.transcript(row, prompt, 0)
    verdict = fake.judge(row, prompt, said)
    result = sched.result_of(verdict["used"], verdict["target_ok"], False)
    after = sched.apply(s, result, day)
    think = int(rng.uniform(1800, 4200) * speed)
    stamp = f"{day.isoformat()}T20:{rng.randint(10, 59)}:00+08:00"
    db.add_review(item_id, after, {
        "prompt_id": prompt["id"], "kind": kind, "mode": mode, "transcript": said, "used": int(verdict["used"]),
        "correct": int(verdict["target_ok"] and not verdict["fix"]), "hinted": 0, "fix_json": json.dumps(verdict["fix"], ensure_ascii=False) if verdict["fix"] else "",
        "natural": verdict["natural"], "result": result, "think_ms": think, "latency_ms": think + int(first * 1000),
        "before_json": json.dumps(s.__dict__), "after_json": json.dumps(after.__dict__), "audio": "", "day": day.isoformat(), "created_at": stamp})


def main() -> None:
    db.init()
    rng, today = random.Random(7), date.today()
    for item_id, ago, results in PLAN:
        row, start = db.get_item(item_id), today - timedelta(days=ago)
        gen = fake.generate(row, [], ("swap", "cross", "self"))
        db.add_prompts(item_id, gen["prompts"])
        db.set_state(item_id, sched.activate(start, 3), frame=gen["frame"], frame_zh=gen["frame_zh"], scene=gen["scene"],
                     activated_at=f"{start.isoformat()}T20:00:00+08:00")
        for _ in range(3):
            answer(item_id, start, "pass", rng, 1.2)
        for r in results:
            due = date.fromisoformat(db.get_item(item_id)["due"])
            if due > today:
                break
            speed = 0.55 + 0.6 * (today - due).days / 14      # 越近的练习开口越快
            answer(item_id, due, VARIANT[r], rng, speed)
            while db.get_item(item_id)["drills_owed"]:
                answer(item_id, due, "pass", rng, speed)
    fake.FORCE = None
    rows = [r for r in db.all_items() if r["status"] != "library"]
    print(f"铺了 {len(rows)} 个表达：", ", ".join(f"{r['id']}={'毕业' if r['status'] == 'graduated' else r['step']}" for r in rows))


if __name__ == "__main__":
    main()
