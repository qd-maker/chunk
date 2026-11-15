"""单用户密码登录：部署到服务器后防止别人用你的 API 余额。

- 设置了 APP_PASSWORD 才启用；本地双击 start.bat 不设，就不需要登录。
- 登录成功后发一个签名 Cookie（HttpOnly，90 天有效），签名密钥来自 SESSION_SECRET。
- 同一 IP 连续输错 5 次，锁 10 分钟；所有 IP 合计 10 分钟内输错 20 次，全部锁 10 分钟（防换 IP 暴力猜）。
  已登录设备的 Cookie 不受影响。
"""
import hashlib
import hmac
import secrets
import time

from .config import settings

COOKIE = "chunk_session"
MAX_AGE = 90 * 24 * 3600
_failures: dict[str, list[float]] = {}
LOCK_AFTER, LOCK_WINDOW = 5, 600
GLOBAL_LOCK_AFTER = 20
ANY = "*"   # 全局计数用的键


def enabled() -> bool:
    return bool(settings.app_password)


def _secret() -> bytes:
    # 没单独配置 SESSION_SECRET 时，用密码派生一个；改密码会让旧 Cookie 全部失效
    base = settings.session_secret or ("derived:" + settings.app_password)
    return hashlib.sha256(base.encode()).digest()


def make_token(now: float | None = None) -> str:
    exp = int((now or time.time()) + MAX_AGE)
    sig = hmac.new(_secret(), str(exp).encode(), hashlib.sha256).hexdigest()
    return f"{exp}.{sig}"


def valid_token(token: str | None, now: float | None = None) -> bool:
    if not token or "." not in token:
        return False
    exp, sig = token.split(".", 1)
    if not exp.isdigit() or int(exp) < (now or time.time()):
        return False
    good = hmac.new(_secret(), exp.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, good)


def client_ip(headers, peer: str | None) -> str:
    """经 Cloudflare 隧道进来时，真实 IP 在 CF-Connecting-IP（Cloudflare 自己写，客户端改不了）；
    X-Forwarded-For 可以被客户端伪造，不拿来做锁定。"""
    return headers.get("cf-connecting-ip") or peer or "?"


def _recent(key: str, now: float) -> list[float]:
    recent = [t for t in _failures.get(key, []) if now - t < LOCK_WINDOW]
    _failures[key] = recent
    return recent


def locked(ip: str, now: float | None = None) -> bool:
    now = now or time.time()
    return len(_recent(ip, now)) >= LOCK_AFTER or len(_recent(ANY, now)) >= GLOBAL_LOCK_AFTER


def check_password(ip: str, password: str) -> bool:
    ok = secrets.compare_digest(password.encode(), settings.app_password.encode())
    if ok:
        _failures.pop(ip, None)
    else:
        _failures.setdefault(ip, []).append(time.time())
        _failures.setdefault(ANY, []).append(time.time())
    return ok
