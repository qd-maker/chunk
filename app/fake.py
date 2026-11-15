"""假上游：FAKE_UPSTREAM=true 时不调任何付费接口。用于自动化测试和浏览器验收。

假转写按 pass → tip → hold → fail 轮流出结果，好让界面的每种状态都能看到；测试里用 FORCE 指定。
tip = 目标表达用对了、句子别处有一处错（照样升级，错误只顺带一提）。
"""
import re
import sqlite3

FORCE: str | None = None          # 测试用："pass" / "tip" / "hold" / "fail"
FAIL_TEXT = "I think it is fine."
CYCLE = ("pass", "tip", "hold", "fail")
# tip 变体：把目标表达之外的一个词换成常见的主谓一致 / 单复数错误
TIP_SWAP = {"was": "were", "were": "was", "is": "are", "are": "is", "has": "have", "have": "has", "doesn't": "don't",
            "does": "do", "it's": "they're"}

# 演示题：对应 examples/library.example.json 导入后的三个条目（IV-09、IV-05、VI-01-c2）
DEMO = {
    "IV-09": {
        "frame": "I'm used to + doing", "frame_zh": "已经习惯……了", "scene": "某件一开始不适应的事，现在已经无所谓了。",
        "swap": [("我现在已经习惯自己做饭了。", "I'm used to cooking for myself now.", "生活"),
                 ("我已经习惯每天走路去上课了。", "I'm used to walking to class every day.", "学校"),
                 ("我已经习惯喝不加糖的咖啡了。", "I'm used to drinking coffee without sugar.", "饮食"),
                 ("住得远，我已经习惯每天在地铁上花一小时了。", "I live far away, so I'm used to spending an hour on the subway every day.", "通勤"),
                 ("我已经习惯在吵的地方看书了。", "I'm used to studying in noisy places.", "学习")],
        "cross": [("室友每晚打游戏到很晚，朋友问你会不会被吵到，你怎么回答？", "Not really. I'm used to him playing games late at night.", "宿舍"),
                  ("新工作每天要穿正装，朋友问你感觉怎么样？", "It felt weird at first, but I'm used to wearing a suit now.", "工作")],
        "self": [("有没有什么事，你一开始很不适应，现在已经无所谓了？说说看。", "", "")],
    },
    "IV-05": {
        "frame": "I'm thinking about + doing", "frame_zh": "在考虑……", "scene": "说一件正在打算、还没拿定主意的事。",
        "swap": [("我在考虑这学期去学游泳。", "I'm thinking about learning to swim this semester.", "运动"),
                 ("我在考虑换一部新手机。", "I'm thinking about getting a new phone.", "购物"),
                 ("我在考虑暑假去打份工。", "I'm thinking about working part-time this summer.", "工作"),
                 ("我们在考虑周末去海边。", "We're thinking about going to the beach this weekend.", "周末"),
                 ("我在考虑把头发剪短。", "I'm thinking about cutting my hair short.", "生活")],
        "cross": [("朋友问你毕业后有什么打算，你还没完全想好，怎么说？", "I'm not sure yet, but I'm thinking about going abroad for a master's.", "规划"),
                  ("宿舍最近太吵了，跟朋友聊起这事，你会怎么说？", "My dorm is so noisy. I'm thinking about moving out next term.", "住宿")],
        "self": [("你最近有没有在琢磨、但还没拿定主意的事？讲讲你在犹豫什么。", "", "")],
    },
    "VI-01-c2": {
        "frame": "catch up on sleep", "frame_zh": "补觉", "scene": "前几天睡得少，想多睡一会儿补回来。",
        "swap": [("我这周末只想在家补觉。", "I just want to stay home and catch up on sleep this weekend.", "周末"),
                 ("考完试我要好好补个觉。", "After the exam, I'm going to catch up on sleep.", "学习"),
                 ("我昨晚睡了十二个小时，终于把觉补回来了。", "I slept twelve hours last night and finally caught up on sleep.", "作息"),
                 ("放假第一天我基本都在补觉。", "I spent most of the first day of break catching up on sleep.", "假期"),
                 ("她下了夜班就回家补觉了。", "She went home to catch up on sleep after her night shift.", "工作")],
        "cross": [("连熬了几个通宵赶作业，朋友约你明天出去玩，你想推掉，怎么说？", "Sorry, I've pulled a few all-nighters, so I really need to catch up on sleep tomorrow.", "朋友"),
                  ("坐了一整夜火车刚到家，家人问你下午有什么安排？", "Nothing much. I'm just going to catch up on sleep.", "旅行")],
        "self": [("你上一次特别缺觉是什么时候？后来怎么补回来的？", "", "")],
    },
}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z' ]", "", s.lower()).strip()


def generate(item: sqlite3.Row, avoid: list[str], kinds: tuple[str, ...]) -> dict:
    demo = DEMO.get(item["id"])
    if demo:
        prompts = [{"kind": k, "zh": zh, "en": en, "topic": topic} for k in kinds for zh, en, topic in demo[k] if zh not in avoid]
        meta = {k: demo[k] for k in ("frame", "frame_zh", "scene")}
    else:
        prompts, meta = [], {"frame": item["text"] if item["source"] == "chunk" else "", "frame_zh": item["zh"][:10], "scene": item["usage"] or "（演示模式）真实出题需要配置大模型。"}
    n = len(avoid)
    for k in kinds:   # 演示库里没有、或已经用完的题型：用原句兜底，保证流程能一直走下去
        if not any(p["kind"] == k for p in prompts):
            prompts += [{"kind": k, "zh": f"{item['zh']}（演示题 {n + i + 1}）", "en": "" if k == "self" else item["text"], "topic": "演示"}
                        for i in range(3)]
    return {**meta, "prompts": prompts}


def _reference(item: sqlite3.Row, prompt: sqlite3.Row) -> str:
    return prompt["ref_en"] or item["example"] or item["text"]


def _target_words(item: sqlite3.Row) -> set[str]:
    # 假出题时句式没有骨架：粗略把原句前 4 个词当成目标表达
    frame = item["frame"] or " ".join(item["text"].split()[:4])
    return {w for w in re.findall(r"[a-z']+", frame.lower()) if w not in ("doing", "do", "sth", "sb", "something", "someone")}


def _hits_target(word: str, target: set[str]) -> bool:
    return any(word == t or (len(t) >= 4 and word.startswith(t[:4])) for t in target)


def _hold(ref: str) -> str:
    """目标表达本身的错：把一个 -ing 词改回原形（used to getting → used to get）。"""
    broken = re.sub(r"\b(\w{3,}?)(?:p|t|n)?ing\b", r"\1", ref, count=1)
    return broken if broken != ref else ref.rsplit(" ", 1)[0]


def _tip(item: sqlite3.Row, ref: str) -> str:
    """目标表达不动，别处换一个词：优先 was/were 这类，找不到就给最后一个长词加减 s。"""
    words, target = ref.split(" "), _target_words(item)
    core = [(i, re.sub(r"[^a-z']", "", w.lower())) for i, w in enumerate(words)]
    core = [(i, w) for i, w in core if w and not _hits_target(w, target)]
    for i, w in core:
        if w in TIP_SWAP:
            words[i] = re.sub(re.escape(w), TIP_SWAP[w], words[i], count=1, flags=re.I)
            return " ".join(words)
    for i, w in reversed(core):
        if len(w) >= 4 and w.isalpha():
            m = re.search(r"[A-Za-z]+", words[i])
            core_w = m.group(0)
            words[i] = words[i].replace(core_w, core_w[:-1] if core_w.endswith("s") else core_w + "s", 1)
            return " ".join(words)
    return ref


def transcript(item: sqlite3.Row, prompt: sqlite3.Row, n: int) -> tuple[str, float]:
    """按第 n 次作答决定演示哪种结果，返回（假转写，第一个词的起始秒数）。"""
    want = FORCE or CYCLE[n % len(CYCLE)]
    ref = _reference(item, prompt)
    if want == "fail":
        return FAIL_TEXT, 1.6
    if want == "hold":
        return _hold(ref), 1.1
    if want == "tip":
        return _tip(item, ref), 0.8
    return ref, 0.6


def _diff(said: str, ref: str, before: int = 1) -> tuple[str, str]:
    """第一处不同的词，连同前面 before 个词。"""
    a, b = said.split(), ref.split()
    i = next((k for k, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)) - 1)
    return " ".join(a[max(0, i - before):i + 1]), " ".join(b[max(0, i - before):i + 1])


def judge(item: sqlite3.Row, prompt: sqlite3.Row, said: str) -> dict:
    ref = _reference(item, prompt)
    if _norm(said) == _norm(ref):
        return {"used": True, "target_ok": True, "fix": None, "natural": ref}
    if said == FAIL_TEXT:
        return {"used": False, "target_ok": False, "natural": ref,
                "fix": {"quote": said, "better": ref, "why": "意思接近，但没用上目标表达。", "scope": "target"}}
    quote, better = _diff(said, ref)
    if said == _tip(item, ref):
        quote, better = _diff(said, ref, 0)   # 只引改动的那个词，免得和目标表达的砖块重叠、波浪线标不上
        return {"used": True, "target_ok": True, "natural": ref,
                "fix": {"quote": quote, "better": better, "why": "这里主谓或单复数没对上。", "scope": "other"}}
    return {"used": True, "target_ok": False, "natural": ref,
            "fix": {"quote": quote, "better": better, "why": "这里的词形不对。", "scope": "target"}}
