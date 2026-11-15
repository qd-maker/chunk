# chunk

一个练英语口语的间隔复习工具：把常用句式和词块练到开口就能用。

这是自用项目：单用户、一个密码、一份数据，没有多用户，也不带计费。要给别人用，得每人各部署一份，并自备 key。

和背单词软件不一样的地方：到期时不给你看原句，也不让你回忆原句。它给你一句新的中文场景，你用录音把它说成英文，并且要用上那个表达。排期只决定哪天练，每次练的内容都不同。

## 怎么练

- 在「库」里挑两三个最近用得上的表达，点激活。每天建议不超过 3 个。
- 激活当天先做 3 道替换题。之后在第 1、3、7、14、30 天回来复习。
- 题型随阶段变化，提示越来越少：
  - 换内容（swap）：同一类生活场景，只换具体内容。
  - 换话题（cross）：换到工作、旅行、家人等别的话题，题面是一个情境，不直接给出那个中文说法。
  - 说自己（self）：讲一件你最近真实发生的事。
- 每次只给中文，一次一题。说完由大模型判定，结果有三种：
  - 通过：用上了目标表达，形式也对，升一级。
  - 原地：用上了但表达本身说错了，或者看了提示，明天同一级再来。
  - 没用上：退一级，当场补 2 道替换题。
- 目标表达用对了、句子别处有个小错（三单、时态、单复数之类），照样通过。那处错误会「顺带一提」，可以一键收进「我的纠错」，以后当成新表达来练。
- 第 30 天那一级通过算毕业，之后每 30 天抽查一次。
- 「墙」里每个表达是一块砖，练得越稳颜色越实。下面的柱子是从看到题到开口的秒数。

## 需要自备什么

- 一个 [OpenRouter](https://openrouter.ai) 的 key：语音转写走它的 `openai/whisper-1`。
- 一个 OpenAI 兼容的大模型接口：用来出题和判定。不单独配就也走 OpenRouter。
- 素材：一份你想练的句式和词块，格式见 [docs/LIBRARY.md](docs/LIBRARY.md)。没有的话先用仓库里的示例 `examples/library.example.json`。
- 本机：Python 3.12、Node.js 22。

## 先看演示（不花钱）

演示用内置的假转写和假判定，不调任何付费接口，数据放在单独的 `data-demo/`。

```bash
# 1. 后端环境
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt     # macOS / Linux 用 .venv/bin/python

# 2. 构建页面（输出到 static/）
cd web && npm install && npm run build && cd ..

# 3. 铺一些假的练习记录，然后启动
.venv/Scripts/python scripts/seed_demo.py
.venv/Scripts/python scripts/run_demo.py
```

打开 http://127.0.0.1:8771 。第 3 步的 `seed_demo.py` 可以不跑，那样进度墙是空的。它每次都会清空 `data-demo/` 重建。

假判定按「通过 → 顺带一提 → 原地 → 没用上」轮流出结果，好让每种界面都能看到。录音内容不会被识别。

## 用真实接口

1. `.env.example` 复制成 `.env`，填上 `OPENROUTER_API_KEY`；大模型想用别家就填 `LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL`。每项去哪拿见文件里的注释。
2. 素材放到 `data/library.json`：`cp examples/library.example.json data/library.json`，或者换成你自己的。
3. 启动：Windows 双击 `start.bat`（第一次会用 [uv](https://docs.astral.sh/uv/) 建环境并构建页面）；其他系统运行

   ```bash
   .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8781
   ```

4. 打开 http://127.0.0.1:8781 。

本机不设 `APP_PASSWORD` 就不用登录。花费大致是：激活一个表达调 1 次大模型出题，每答一题调 1 次转写和 1 次大模型。

## 部署和安卓包

服务端用 Docker：

```bash
cp .env.example .env            # 填 key，必须设 APP_PASSWORD 和 SESSION_SECRET
mkdir -p server-data && cp examples/library.example.json server-data/library.json
docker compose up -d --build
```

服务只监听服务器本机的 8781 端口，外网要套一层 HTTPS（反向代理或隧道）。浏览器只在 HTTPS 下允许录音。

`apk/` 是一个 Capacitor 安卓壳，打开就加载你部署的地址。打包前先写入地址：`node apk/configure.mjs https://your-server.example`。

完整步骤、环境变量表、备份和升级见 [docs/DEPLOY.md](docs/DEPLOY.md)。

## 测试

```bash
.venv/Scripts/python -m pytest -q
```

全部走假上游，不花钱。

## 项目结构

| 位置 | 内容 |
|------|------|
| `app/main.py` | 接口，约定见 [docs/API.md](docs/API.md) |
| `app/sched.py` | 排期规则（1/3/7/14/30 天的阶梯），纯函数 |
| `app/coach.py` | 出题和判定的提示词、判定结果解析 |
| `app/upstream.py` | 转写和大模型调用 |
| `app/fake.py` | 假上游，测试和演示用 |
| `app/db.py` | SQLite：表达、题库、练习记录；首次启动导入素材库 |
| `app/auth.py` | 单密码登录 |
| `web/src` | 前端（React + TypeScript + Vite），构建到 `static/` |
| `apk/` | 安卓壳（Capacitor），地址模板在 `apk/templates/` |
| `examples/` | 示例素材库 |
| `scripts/` | 演示服务和演示数据 |
| `tests/` | 排期和接口的测试 |
| `docs/` | 接口约定、素材库格式、部署 |

## 致谢

练法参考了 Albert 的《英语口语训练指南》，本仓库不包含该指南的任何内容。

## 协议

[MIT](LICENSE)
