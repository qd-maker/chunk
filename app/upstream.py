"""两个上游调用：语音转写（OpenRouter whisper-1）和大模型（任意 OpenAI 兼容接口）。上游错误统一转成 ApiError。"""
import asyncio
import base64
import json
import logging
import re

import httpx

from .config import settings

log = logging.getLogger("uvicorn.error")
RETRY_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 520, 522, 524, 529}
# 示范里带口头禅，Whisper 就更倾向于逐字转写、少替人改错
VERBATIM_PROMPT = "Um, well, I mean, uh, I think... Verbatim transcript, keep fillers and repetitions."


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message


async def _post(url: str, key: str, body: dict, timeout: float, fail_code: str, retries: int = 1) -> dict:
    if not key:
        raise ApiError(503, "SERVICE_NOT_CONFIGURED", "没有配置 API key，请在 .env 里填写。")
    err = ApiError(502, fail_code, "上游没有响应。")
    for i in range(retries + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.post(url, headers={"Authorization": f"Bearer {key}", "X-Title": "Chunk"}, json=body)
        except httpx.TimeoutException:
            err = ApiError(504, "UPSTREAM_TIMEOUT", f"上游超过 {timeout:.0f} 秒没有响应。")
        except httpx.HTTPError as e:
            err = ApiError(502, fail_code, f"连接上游失败：{e.__class__.__name__}")
        else:
            if r.status_code == 200:
                try:
                    return r.json()
                except ValueError:
                    err = ApiError(502, fail_code, "上游返回的不是 JSON。")
            else:
                err = ApiError(502, fail_code, f"上游返回 {r.status_code}：{r.text[:200]}")
                if r.status_code not in RETRY_STATUS:
                    raise err
        log.warning("%s 第 %d 次失败：%s", url, i + 1, err.message)
        if i < retries:
            await asyncio.sleep(1.5 * (i + 1))
    raise err


async def transcribe(audio: bytes, ext: str) -> tuple[str, float]:
    """返回（转写文本，第一个词的起始秒数）。"""
    body = {
        "model": settings.asr_model,
        "input_audio": {"data": base64.b64encode(audio).decode(), "format": ext},
        "response_format": "verbose_json", "timestamp_granularities": ["word"],
        "language": "en", "temperature": 0, "prompt": VERBATIM_PROMPT,
    }
    j = await _post(f"{settings.openrouter_base_url}/audio/transcriptions", settings.openrouter_api_key, body,
                    settings.asr_timeout, "ASR_FAILED")
    words = j.get("words") or []
    try:
        first = float(words[0]["start"]) if words else 0.0
    except (KeyError, TypeError, ValueError):
        first = 0.0
    return (j.get("text") or "").strip(), first


async def chat_json(system: str, user: str, max_tokens: int = 2000) -> dict:
    """调大模型并把回复解析成 JSON 对象；解析不了算上游失败。"""
    model = settings.llm_model
    body: dict = {"model": model, "max_tokens": max_tokens,
                  "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    if "claude" not in model:
        body["temperature"] = 0   # Claude 新模型经中转站直连官方接口时不接受 temperature
    base = settings.llm_base_url or settings.openrouter_base_url
    # 模型偶尔会在字符串里写没转义的引号，JSON 就坏了。实测重问一次基本都好，所以解析失败再问一次。
    for attempt in (1, 2):
        j = await _post(f"{base}/chat/completions", settings.llm_api_key or settings.openrouter_api_key, body,
                        settings.llm_timeout, "LLM_FAILED")
        usage = j.get("usage") or {}
        log.info("llm tokens: in=%s cached=%s out=%s", usage.get("prompt_tokens"),
                 (usage.get("prompt_tokens_details") or {}).get("cached_tokens"), usage.get("completion_tokens"))
        try:
            text = j["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            raise ApiError(502, "LLM_FAILED", f"大模型返回格式异常：{str(j)[:200]}")
        try:
            return parse_json(text)
        except ApiError:
            if attempt == 2:
                raise
            log.warning("大模型返回的 JSON 解析失败，重问一次：%s", text[:200])
    raise ApiError(502, "LLM_FAILED", "大模型没有按约定返回 JSON。")


def parse_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    try:
        data = json.loads(m.group(0)) if m else None
    except ValueError:
        data = None
    if not isinstance(data, dict):
        raise ApiError(502, "LLM_FAILED", "大模型没有按约定返回 JSON。")
    return data
