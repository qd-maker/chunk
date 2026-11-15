"""排期：纯函数，不碰数据库。

阶梯 step 1–5 对应第 1 / 3 / 7 / 14 / 30 天的复习。曲线只决定「哪天练」，
每次练什么由题型决定：越往后提示越少（同类场景 → 换话题 → 说自己）。
"""
from dataclasses import dataclass, replace
from datetime import date, timedelta

INTERVALS = [1, 3, 7, 14, 30]            # INTERVALS[step-1] = 通过第 step-1 级后隔几天
KIND_BY_STEP = {0: "swap", 1: "swap", 2: "cross", 3: "cross", 4: "self", 5: "self"}
MAX_STEP = 5
CHECK_EVERY = 30                          # 毕业后每 30 天抽查一次
RELAPSE_STEP = 3                          # 抽查没用上：退回第 7 天那一级


@dataclass(frozen=True)
class State:
    status: str        # library / active / graduated / paused
    step: int
    due: str | None    # YYYY-MM-DD
    intro_left: int
    drills_owed: int
    lapses: int


def result_of(used: bool, target_ok: bool, hinted: bool) -> str:
    """阶梯只看目标表达：没用上 fail；表达本身形式错或看了提示 hold；句子别处的错不影响升级。"""
    if not used:
        return "fail"
    return "pass" if target_ok and not hinted else "hold"


def mode_of(s: State) -> str:
    if s.drills_owed > 0:
        return "drill"
    if s.intro_left > 0:
        return "intro"
    return "check" if s.status == "graduated" else "review"


def kind_of(s: State) -> str:
    mode = mode_of(s)
    if mode in ("drill", "intro"):
        return "swap"
    return "self" if mode == "check" else KIND_BY_STEP[s.step]


def _plus(today: date, days: int) -> str:
    return (today + timedelta(days=days)).isoformat()


def activate(today: date, intro_rounds: int) -> State:
    return State("active", 0, today.isoformat(), intro_rounds, 0, 0)


def apply(s: State, result: str, today: date, drill_rounds: int = 2) -> State:
    """答完一题后的新状态。intro / drill 只消耗轮数，不看对错；review / check 才动阶梯。"""
    mode = mode_of(s)
    if mode == "drill":
        return replace(s, drills_owed=s.drills_owed - 1)
    if mode == "intro":
        left = s.intro_left - 1
        return replace(s, intro_left=left) if left else replace(s, intro_left=0, step=1, due=_plus(today, INTERVALS[0]))
    if mode == "check":
        if result == "pass":
            return replace(s, due=_plus(today, CHECK_EVERY))
        if result == "hold":
            return replace(s, due=_plus(today, 7))
        return replace(s, status="active", step=RELAPSE_STEP, due=_plus(today, 1), lapses=s.lapses + 1, drills_owed=drill_rounds)
    if result == "pass":
        if s.step >= MAX_STEP:
            return replace(s, status="graduated", due=_plus(today, CHECK_EVERY))
        return replace(s, step=s.step + 1, due=_plus(today, INTERVALS[s.step]))
    if result == "hold":
        return replace(s, due=_plus(today, 1))
    return replace(s, step=max(1, s.step - 1), due=_plus(today, 1), lapses=s.lapses + 1, drills_owed=drill_rounds)
