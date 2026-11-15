"""演示 / 验收用的服务：假上游 + 单独的数据目录 data-demo，不花钱，也不碰真实练习数据。

data-demo 里没有素材库时，复制 examples/library.example.json 过去（存成 library.json）。
用法：.venv/Scripts/python scripts/run_demo.py [端口，默认 8771]
"""
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "data-demo"

if __name__ == "__main__":
    DEMO.mkdir(exist_ok=True)
    if not any((DEMO / n).exists() for n in ("library.json", "guide.json")):
        shutil.copy(ROOT / "examples" / "library.example.json", DEMO / "library.json")
    os.environ.update(FAKE_UPSTREAM="true", DATA_DIR=str(DEMO), APP_PASSWORD="")
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=int(sys.argv[1]) if len(sys.argv) > 1 else 8771)
