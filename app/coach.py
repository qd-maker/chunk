"""出题和判定。做法：只给中文、一次一题、场景不断变化；判定只看目标表达用上没有，
最多指出一处真正影响表达的错误，不把正确的句子改高级。"""
import re
import sqlite3

from . import fake
from .config import settings
from .upstream import ApiError, chat_json

KINDS = ("swap", "cross", "self")
POOL = {"swap": 5, "cross": 4, "self": 3}

GEN_SYSTEM = """你在帮一位中国大学生练英语口语。方法是：围绕一个固定的英语表达，只给他中文，让他开口说英文，每道题换一个场景，练的是「内容变了还能调用同一个表达」。
只输出一个 JSON 对象，不要任何解释：
{"frame": "...", "frame_zh": "...", "scene": "...", "swap": [{"zh": "...", "en": "...", "topic": "..."}], "cross": [...], "self": [{"zh": "..."}]}

字段要求：
- frame：这个表达里可以反复套用的骨架，英文，例如 "I ended up + doing"、"It's not that ...; it's just that ..."；词块就写词块本身（动词用原形）。
- frame_zh：给他的中文提示，10 个字以内，例如「最后还是……」。不能出现英文。
- scene：一句中文，说清楚什么情况下会用它，30 个字以内。
- swap：和原句同一类生活场景，只换具体内容。
- cross：换到别的话题，每道题的话题互不相同，也和原句不同（工作、学习、朋友、旅行、健康、购物、家人、天气、饮食等）。这是情境题，不是翻译题：zh 写成一个具体的情境加一个要他回应的点，例如「朋友约你这周末出去玩，你想拒绝，怎么跟他说？」。中文里不要直接写出目标表达对应的那个中文说法（目标是「最后还是……」就别写「最后还是」，目标是「手头事情多」就别写「事情特别多」），也不要用「最后」「结果」「后来」这类字眼去暗示它，但在这个情境里用目标表达是最自然的说法。
- swap：zh 是一句大学生或年轻人真会说的口语化中文，8–28 个字，要说的意思直接写出来，它最自然的英文说法正好用到目标表达；不能出现英文。
- swap 和 cross 的 en：用上目标表达的一句自然英文，词汇保持简单。swap 的 en 必须是 zh 的忠实翻译，zh 里有的信息都要有、zh 里没有的不要加；cross 的 en 是这个情境里一个自然的回答。topic：两到四个字的话题名。
- self：一句中文的提问或邀请，让他讲自己最近真实发生的事，而这件事正好适合用目标表达；用中文把意思点出来，不能出现英文表达本身。
- 如果给了「他原来的错误说法」，目标就是那个被纠正的点：每道题都必须逼他用到这个点。
- 不要和「已经出过的题」重复或雷同。"""

JUDGE_SYSTEM = """你在判定一位中国学生的一句口语回答。他看到一句中文提示，要开口用英文表达，并且要用上指定的目标表达。
回答是语音转写的文本：可能没有标点，停顿、口头禅、重复、改口都是正常的，不算错误。
只输出一个 JSON 对象，不要任何解释：
{"used": true, "target_ok": true, "fix": null, "natural": "..."}

判定规则：
- used：他有没有去用目标表达。说出了骨架的核心就算用上，时态、人称、词形变化都算，替换内容当然不同；骨架里可有可无的小成分没说（比如 for me）也算用上。只要说出了目标表达，哪怕形式用错了（比如 end up 后面接了原形），used 也是 true，错误交给 target_ok 和 fix。意思说对了但用的是别的说法、根本没说出目标表达 → false。
- target_ok：只看目标表达本身对不对。只有骨架里的固定词说错、漏了关键词、顺序不对，或者骨架明确标出的形式没做到（比如骨架是 end up + doing，他说成 ended up lie），才是 false。骨架空位里填的内容不管有什么问题（用词、语法、意思），都不影响 target_ok。used 为 false 时 target_ok 也写 false。
- fix：全句最多指出一处最值得改的地方，{"quote": "他的原话片段，照转写原样抄", "better": "自然的改法", "why": "中文说明，30 个字以内", "scope": "target 或 other"}。
  优先级：目标表达本身的错（scope 写 target）＞ 会影响理解或明显的语法、搭配错误（scope 写 other，例如三单、时态、单复数、动词形式、搭配不当、把意思说反）。
  只是不够地道、可以说得更高级的地方不算错，不要指出。没有值得改的就写 null，不要为了给反馈而挑错。
  used 为 false 时，fix 说明目标表达应该怎么用进来，scope 写 target。
- 他的回答内容不必和中文提示逐字对应：他可以换一个说法、换一个细节、甚至讲了另一件事，只要用上了目标表达就行。不要因为内容和提示不一致而挑错；但如果把提示里的意思明显说反了，可以作为 other 指出。
- natural：一句完整自然的英文，保留他想表达的意思，用上目标表达，并且已经改掉 fix 指出的那处错。
- 如果给了「他原来的错误说法」，重点看他这次有没有把那个点说对：说对了 used 为 true，又犯了同样的错 used 为 false。"""


def _target(item: sqlite3.Row) -> str:
    lines = [f"目标表达所在的完整句子：{item['text']}", f"中文意思：{item['zh']}"]
    if item["frame"]:
        lines.append(f"骨架：{item['frame']}")
    if item["example"]:
        lines.append(f"另一个例句：{item['example']}")
    if item["usage"]:
        lines.append(f"用法：{item['usage']}")
    if item["wrong"]:
        lines.append(f"他原来的错误说法：{item['wrong']}")
    if item["topic_zh"] and item["source"] in ("chunk", "topic_pattern"):
        lines.append(f"它出自话题：{item['topic_zh']}")
    return "\n".join(lines)


def _clean(rows, kind: str, need_en: bool) -> list[dict]:
    out = []
    for r in rows if isinstance(rows, list) else []:
        zh = str(r.get("zh", "")).strip() if isinstance(r, dict) else ""
        en = str(r.get("en", "")).strip() if isinstance(r, dict) else ""
        if not zh or re.search(r"[A-Za-z]{3,}", zh) or (need_en and not en):
            continue   # 中文题面里混进了英文 = 泄题，丢掉
        out.append({"kind": kind, "zh": zh, "en": en, "topic": str(r.get("topic", "")).strip()[:8]})
    return out


async def generate(item: sqlite3.Row, avoid: list[str], kinds: tuple[str, ...] = KINDS) -> dict:
    """返回 {"frame", "frame_zh", "scene", "prompts": [...]}。prompts 里每种题型至少要有一道，否则算失败。"""
    if settings.fake_upstream:
        return fake.generate(item, avoid, kinds)
    want = "、".join(f"{k} {POOL[k]} 道" for k in kinds)
    user = f"{_target(item)}\n\n这次要：{want}（没点到的题型给空数组）。"
    if avoid:
        user += "\n\n已经出过的题：\n" + "\n".join(f"- {z}" for z in avoid[-30:])
    data = await chat_json(GEN_SYSTEM, user)
    prompts = [p for k in kinds for p in _clean(data.get(k), k, need_en=k != "self")]
    if any(not [p for p in prompts if p["kind"] == k] for k in kinds):
        raise ApiError(502, "LLM_FAILED", "大模型出的题不完整，请再试一次。")
    return {"frame": str(data.get("frame") or "").strip()[:80], "frame_zh": str(data.get("frame_zh") or "").strip()[:20],
            "scene": str(data.get("scene") or "").strip()[:60], "prompts": prompts}


def _bool(v) -> bool:
    """模型偶尔把布尔写成字符串。"""
    return v.strip().lower() in ("true", "yes", "1") if isinstance(v, str) else bool(v)


def parse_verdict(data: dict, ref_en: str = "") -> dict:
    """把模型输出整理成 {used, target_ok, fix: {quote, better, why, scope} | None, natural}，兼容旧字段 correct。"""
    used = _bool(data.get("used"))
    target_ok = used and _bool(data["target_ok"] if "target_ok" in data else data.get("correct"))
    fix = data.get("fix")
    if not (isinstance(fix, dict) and fix.get("better")):
        fix = None
    else:
        scope = str(fix.get("scope") or "").strip().lower()
        fix = {k: str(fix.get(k) or "").strip()[:200] for k in ("quote", "better", "why")}
        if scope not in ("target", "other"):
            scope = "other" if target_ok else "target"
        if target_ok:
            scope = "other"            # 表达本身没错，错只能在别处
        elif not used:
            scope = "target"           # 没用上：fix 讲的是表达该怎么用进来
        fix["scope"] = scope
    return {"used": used, "target_ok": target_ok, "fix": fix, "natural": str(data.get("natural") or ref_en or "").strip()[:300]}


async def judge(item: sqlite3.Row, prompt: sqlite3.Row, transcript: str) -> dict:
    """返回 {"used", "target_ok", "fix": {quote, better, why, scope} | None, "natural"}。"""
    if settings.fake_upstream:
        return fake.judge(item, prompt, transcript)
    user = (f"{_target(item)}\n\n中文提示：{prompt['zh']}\n"
            + (f"参考说法：{prompt['ref_en']}\n" if prompt["ref_en"] else "")
            + f"\n他的回答（语音转写）：{transcript}")
    data = await chat_json(JUDGE_SYSTEM, user, max_tokens=500)
    return parse_verdict(data if isinstance(data, dict) else {}, prompt["ref_en"])
