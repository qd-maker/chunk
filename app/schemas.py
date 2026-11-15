from typing import Literal

from pydantic import BaseModel, Field

Result = Literal["pass", "hold", "fail"]
Kind = Literal["swap", "cross", "self"]
Mode = Literal["intro", "review", "drill", "check"]


class Health(BaseModel):
    ok: bool = True
    fake: bool
    asr_ready: bool
    llm_ready: bool
    auth_required: bool


class LoginIn(BaseModel):
    password: str = Field(min_length=1, max_length=200)


class ItemOut(BaseModel):
    id: str
    source: str
    topic_no: int | None
    topic_zh: str
    grp: str
    text: str
    zh: str
    example: str
    example_zh: str
    usage: str
    wrong: str
    first_batch: bool
    frame: str
    frame_zh: str
    scene: str
    status: str
    step: int
    due: str | None
    intro_left: int
    drills_owed: int
    reps: int
    lapses: int
    activated_at: str | None
    latency_ms: int | None = None


class PromptOut(BaseModel):
    id: int
    kind: Kind
    zh: str
    topic: str


class Task(BaseModel):
    mode: Mode
    kind: Kind
    round: int
    rounds: int
    prompt: PromptOut
    item: ItemOut


class NextOut(BaseModel):
    task: Task | None
    remaining: int


class Fix(BaseModel):
    quote: str
    better: str
    why: str
    scope: Literal["target", "other"] = "target"   # target = 错在目标表达本身；other = 错在句子别处（不影响升级）


class AnswerOut(BaseModel):
    review_id: int
    mode: Mode
    kind: Kind
    transcript: str
    used: bool
    correct: bool
    hinted: bool
    result: Result
    fix: Fix | None
    natural: str
    ref_en: str
    think_ms: int
    latency_ms: int
    step_before: int
    step_after: int
    due_after: str | None
    graduated: bool
    drills_owed: int
    overridden: bool
    has_audio: bool
    collected: bool        # 这条练习里的错误是否已经收进「我的纠错」
    item: ItemOut


class OverrideIn(BaseModel):
    result: Result


class TodayOut(BaseModel):
    date: str
    due: int
    intro: int
    drills: int
    remaining: int
    done_today: int
    new_left: int
    active: int
    graduated: int
    streak: int
    next_due: str | None


class TopicOut(BaseModel):
    no: int
    zh: str
    grp: str
    total: int
    active: int


class LibraryOut(BaseModel):
    items: list[ItemOut]
    topics: list[TopicOut]
    new_left: int
    new_per_day: int


class CreateItemIn(BaseModel):
    kind: Literal["fix", "custom"]
    text: str = Field(min_length=2, max_length=300, description="正确、自然的英文说法")
    zh: str = Field(default="", max_length=300, description="中文意思，或这条纠错的说明")
    wrong: str = Field(default="", max_length=300, description="当时说错的原话（纠错才有）")


class HistoryRow(BaseModel):
    review_id: int
    day: str
    mode: Mode
    kind: Kind
    result: Result
    prompt_zh: str
    ref_en: str            # 这道题的参考英文，「说自己」题型为空
    natural: str           # 判定时给的自然说法
    transcript: str
    latency_ms: int
    fix: Fix | None        # 那次指出的一处错误


class ItemDetail(BaseModel):
    item: ItemOut
    history: list[HistoryRow]


class LatencyPoint(BaseModel):
    day: str
    ms: int
    n: int


class WallOut(BaseModel):
    bricks: list[ItemOut]
    by_step: list[int]          # 下标 0–5 是阶梯，6 是已毕业
    latency: list[LatencyPoint]
    reviews_7d: int
    pass_rate_7d: float | None
    streak: int
