# 部署

服务端是一个 Docker 容器：FastAPI 同时提供接口和页面，数据是 SQLite 文件和录音，放在挂载的数据目录里。手机上可以直接用浏览器打开，也可以装 `apk/` 打出来的安卓壳。

```text
手机浏览器 / 安卓壳 ──HTTPS──▶ 反向代理或隧道 ──▶ chunk 容器（127.0.0.1:8781）
                                                  ├─ 转写 → OpenRouter（whisper-1）
                                                  └─ 出题、判定 → OpenAI 兼容接口
```

下文用 `your-server.example` 代表你的域名。

## 1. 准备服务器

需要 Docker 和 Docker Compose。把仓库放到服务器上（`git clone` 或上传都行），在仓库根目录操作：

```bash
cp .env.example .env
mkdir -p server-data
chown 1000:1000 server-data          # 容器里以 UID 1000 运行，要能写这个目录
cp examples/library.example.json server-data/library.json   # 或者换成你自己的素材，见 docs/LIBRARY.md
```

编辑 `.env`，至少填这几项：

| 变量 | 说明 |
|------|------|
| `OPENROUTER_API_KEY` | 转写用，必填 |
| `LLM_BASE_URL` | 大模型接口地址，到 `/v1` 这一层；不填走 OpenRouter |
| `LLM_API_KEY` | 大模型 key；不填用 `OPENROUTER_API_KEY` |
| `LLM_MODEL` | 模型名，默认 `anthropic/claude-sonnet-5.5` |
| `APP_PASSWORD` | 登录密码。公网部署必须设 |
| `SESSION_SECRET` | Cookie 签名密钥，`openssl rand -hex 32` 生成 |

可选项（一般不用改）：

| 变量 | 默认 | 说明 |
|------|------|------|
| `NEW_PER_DAY` | 3 | 每天建议激活几个新表达，超过要确认 |
| `NEW_HARD_MAX` | 5 | 每天激活的硬上限 |
| `SESSION_CAP` | 15 | 一天最多排多少道到期复习 |
| `INTRO_ROUNDS` | 3 | 新表达当天做几道替换题 |
| `DRILL_ROUNDS` | 2 | 没用上时当场补几道 |
| `ASR_MODEL` | `openai/whisper-1` | 转写模型 |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | 转写接口地址 |
| `ASR_TIMEOUT` / `LLM_TIMEOUT` | 45 / 60 | 上游超时秒数 |
| `FAKE_UPSTREAM` | false | true 时用假转写和假判定，不花钱 |

`DATA_DIR` 已经在 `docker-compose.yml` 里设成 `/data`，不用写进 `.env`。

容器时区是 `Asia/Shanghai`（见 `Dockerfile`），「今天到期」按这个时区的零点算。不在这个时区就改 `Dockerfile` 里的 `TZ`。

## 2. 启动

```bash
docker compose up -d --build
docker compose ps                              # 等到 healthy
curl -s http://127.0.0.1:8781/api/health       # {"ok": true, ...}
```

`health` 里 `asr_ready`、`llm_ready` 为 false 说明对应的 key 没配上。

## 3. 对外提供 HTTPS

容器只监听服务器本机的 `127.0.0.1:8781`。浏览器只在 HTTPS 下允许录音，所以外面要套一层 HTTPS，两种做法选一种。

**反向代理**（服务器有公网 IP、能开 80/443）。以 Caddy 为例，它会自动申请证书：

```text
your-server.example {
    reverse_proxy 127.0.0.1:8781
}
```

用 Nginx 也一样：`proxy_pass http://127.0.0.1:8781;`，并把 `client_max_body_size` 设到 10m 以上（录音上限 8 MB）。

**隧道**（没有公网 IP，或不想开端口）。例如 Cloudflare Tunnel：在面板里给隧道加一个公开主机名 `your-server.example`，服务指向 `http://127.0.0.1:8781`；如果 cloudflared 也跑在 Docker 里，就让两个容器加入同一个 docker 网络，服务写 `http://chunk:8781`。

代理要转发 `X-Forwarded-Proto`（Caddy 和 Cloudflare 默认会带），登录 Cookie 据此加上 Secure。

## 4. 数据目录和备份

`server-data/` 里是：

| 文件 | 内容 |
|------|------|
| `chunk.db` | 表达、题库、练习记录 |
| `audio/` | 每次练习的录音 |
| `library.json` | 素材库，只在数据库为空时导入一次 |

备份就是复制这个目录。为了拿到一致的数据库文件，先停容器再复制：

```bash
docker compose stop
tar czf chunk-backup-$(date +%F).tgz server-data
docker compose start
```

不想停服务可以用 SQLite 的在线备份：`sqlite3 server-data/chunk.db ".backup chunk-backup.db"`，录音目录直接复制。

## 5. 升级

```bash
tar czf chunk-backup-$(date +%F).tgz server-data      # 先备份
git pull                                              # 或者上传新代码，覆盖除 .env 和 server-data 以外的文件
docker compose build
docker compose up -d
```

重建容器不会动 `server-data/`。表结构用 `CREATE TABLE IF NOT EXISTS` 建，没有自动迁移，升级前看一眼 `app/db.py` 的 `SCHEMA` 有没有改。

## 6. 安卓壳

`apk/` 是 Capacitor 壳，打开就加载你部署的地址，页面和逻辑都在服务器上：以后改页面只要重新部署服务器，不用重装 APK。

仓库里只有模板（`apk/templates/`，地址是占位的 `https://your-server.example`）。`apk/configure.mjs` 按模板生成 `apk/capacitor.config.json` 和 `apk/www/` 下的两个页面，这些生成物不进仓库。

需要：Node.js 22、JDK 21、Android SDK（设好 `JAVA_HOME`、`ANDROID_HOME`）。

```bash
cd apk
npm install
echo '{"url": "https://your-server.example"}' > server.config.json   # 你的地址，这个文件不进仓库
node configure.mjs            # 读 server.config.json；也可以直接 node configure.mjs https://your-server.example
npx cap sync android
cd android && ./gradlew assembleRelease
```

Windows 上可以直接运行 `apk\build-apk.cmd`，它会依次做 configure、`cap sync`、`assembleRelease`。

产物在 `apk/android/app/build/outputs/apk/release/app-release.apk`。

签名：在 `apk/android/keystore.properties` 里写 `storeFile`、`storePassword`、`keyAlias`、`keyPassword`（路径相对 `apk/android/app/`），没有这个文件就只能打出未签名的包。生成密钥：

```bash
keytool -genkeypair -v -keystore apk/chunk-release.keystore -alias chunk -keyalg RSA -keysize 2048 -validity 10000
```

`*.keystore` 和 `keystore.properties` 都不进仓库，自己备份好：丢了就不能给已安装的 APK 做覆盖升级，只能卸载重装。

`node configure.mjs --reset` 会把生成物写回占位地址。

安装：把 APK 发到手机点开，第一次要允许「安装未知应用」。打开后输入密码，第一次录音时允许麦克风。
