@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo First run: creating environment...
  uv venv --python 3.12 .venv
  uv pip install --python .venv\Scripts\python.exe -r requirements.txt
)
if not exist static\index.html (
  echo Building web page...
  pushd web
  call npm install
  call npm run build
  popd
)
start "" http://127.0.0.1:8781
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8781
