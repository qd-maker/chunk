# Chunk · API 约定

所有接口前缀 `/api`，JSON 收发（录音上传用 multipart）。设置了 `APP_PASSWORD` 时，除 `health / session / login` 外都要带登录 Cookie。

## 错误格式

```json
{ "error": { "code": "DAILY_NEW_LIMIT", "message": "今天已经激活 3 个表达了。" } }
```

| HTTP | code | 含义 |
|------|------|------|
| 401 | `UNAUTHORIZED` | 没登录或 Cookie 过期 |
| 401 | `BAD_PASSWORD` | 密码错 |
| 429 | `LOCKED` | 输错太多次，10 分钟后再试 |
| 404 | `NOT_FOUND` | 表达 / 题目 / 记录不存在 |
| 409 | `DAILY_NEW_LIMIT` | 今天新激活数到上限（带 `force=true` 可越过，硬上限 5） |
| 409 | `BAD_STATE` | 当前状态不能做这个操作（如重复激活、改判的不是最新一条、收进纠错的练习没有「顺带一提」的错） |
| 413 | `AUDIO_TOO_LARGE` | 录音超过 8 MB |
| 422 | `VALIDATION_ERROR` | 参数不合法 |
| 422 | `NO_SPEECH` | 没听清（转写为空或不足 3 个词，后者多半是转写模型在近乎无声时编出来的），不判定、不记录 |
| 502 | `ASR_FAILED` / `LLM_FAILED` | 转写或大模型上游出错 |
| 503 | `SERVICE_NOT_CONFIGURED` | 没配 API key |
| 504 | `UPSTREAM_TIMEOUT` | 上游超时 |

## 概念

- **表达 item**：一条句式、衔接表达、词块或纠错。`status`：`library`（在库里没练）→ `active`（在排期里）→ `graduated`（毕业，每 30 天抽查）；`paused` 是暂停。
- **阶梯 step**：1–5 对应第 1 / 3 / 7 / 14 / 30 天的复习。刚激活是 0，当天做 3 道替换题（intro）后变 1。
- **题型 kind**：`swap` 同类场景换内容（intro、第 1 天）、`cross` 换话题（第 3、7 天）、`self` 说自己（第 14、30 天和毕业抽查）。
- **结果 result**：阶梯只衡量「这个表达会不会调用」。
  - `fail` 没说出目标表达 → 退一级、明天再来、当场补 2 道替换题（drill）。
  - `hold` 说出了目标表达，但表达本身形式错了（骨架里的固定词缺失、顺序错，或骨架规定的形式没做到，如 `I'm used to + doing` 说成 `I'm used to get up`），或者看了提示 → 同级明天再来。
  - `pass` 目标表达用对了且没看提示 → 升一级。句子别处有错（用词、搭配、时态、三单、单复数、意思说反等）也照样 pass，那处错误放在 `fix` 里、`scope="other"`，只顺带一提，可以收进「我的纠错」。
- **fix.scope**：`target` 错在目标表达本身（没用上时 fix 讲怎么用进来，也是 target）；`other` 错在句子别处。旧记录没有这个字段，按 `target` 处理。
- **correct**：整句有没有问题 = 目标表达用对且没有 fix。只用于展示，不决定升级。

## 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | `{ok, fake, asr_ready, llm_ready, auth_required}` |
| GET | `/session` | `{authed, auth_required}` |
| POST | `/login` | `{password}` → 204，写 Cookie |
| POST | `/logout` | 204 |
| GET | `/today` | 今日概况：`{date, due, intro, drills, done_today, new_left, active, graduated, streak, next_due}` |
| GET | `/next` | 取下一道题：`{task, remaining}`；没题时 `task=null`。顺序：补练 → 到期复习 → 今天新激活的 |
| POST | `/answer` | multipart：`prompt_id`、`audio`、`think_ms`（看到题到按下录音的毫秒数）、`hinted`（0/1）→ `AnswerOut` |
| POST | `/reviews/{id}/override` | `{result: pass\|hold\|fail}` 改判（只能改这个表达最新的一条）→ `AnswerOut` |
| POST | `/reviews/{id}/collect` | 把这条练习里 `scope=other` 的错收进「我的纠错」：新建 `source=fix`、`status=library` 的表达，id 为 `fix-r{id}` → 201 `ItemOut`；已收过 → 200 返回已有那条；没有 other 类的 fix → 409 `BAD_STATE`；练习不存在 → 404 |
| GET | `/reviews/{id}/audio` | 回放自己的录音 |
| GET | `/library` | 全部表达 + 话题列表 + 各来源数量 |
| GET | `/items/{id}` | 表达详情 + 最近 20 条练习记录 |
| POST | `/items` | 新建纠错 / 自定义：`{kind: fix\|custom, text, zh, wrong?}` → 201 `ItemOut` |
| POST | `/items/{id}/activate?force=` | 激活：生成题库、进入排期 → `ItemOut` |
| POST | `/items/{id}/pause` · `/resume` | 暂停 / 恢复 |
| DELETE | `/items/{id}` | 只能删纠错和自定义 → 204 |
| GET | `/wall` | 进度墙：每个已激活表达一块砖 + 开口延迟趋势 + 近 7 天通过率 |

### Task（`/next` 返回）

```json
{
  "mode": "review",              // intro | review | drill | check
  "kind": "cross",               // swap | cross | self
  "round": 1, "rounds": 1,       // intro 是 1/3、2/3、3/3
  "prompt": { "id": 42, "kind": "cross", "zh": "新工作每天要穿正装，朋友问你感觉怎么样？", "topic": "工作" },
  "item": { "id": "IV-09", "text": "I'm used to getting up early now.", "frame": "I'm used to + doing", "frame_zh": "已经习惯……了", "step": 2, "...": "见 ItemOut" }
}
```

前端在答题前只显示 `prompt.zh`；`mode=intro` 的第 1 轮先展示整张表达卡。

### AnswerOut

```json
{
  "review_id": 7, "transcript": "it was weird at first but I'm used to wear a suit now", "used": true, "correct": false, "hinted": false,
  "result": "hold",
  "fix": { "quote": "used to wear", "better": "used to wearing", "why": "be used to 后面接 doing", "scope": "target" },
  "natural": "It felt weird at first, but I'm used to wearing a suit now.",
  "ref_en": "It felt weird at first, but I'm used to wearing a suit now.",
  "think_ms": 2100, "latency_ms": 2900,
  "step_before": 2, "step_after": 2, "due_after": "2026-11-14", "graduated": false, "drills_owed": 0,
  "overridden": false, "has_audio": true, "collected": false,
  "item": { "...": "更新后的 ItemOut" }
}
```

表达用对、别处有错时：`result="pass"`、`correct=false`、`fix.scope="other"`，阶梯照常升级，例如
`"fix": { "quote": "my roommate play", "better": "my roommate plays", "why": "主语是第三人称单数", "scope": "other" }`。

`collected`：这条练习的错误是否已经收进「我的纠错」（即 `fix-r{review_id}` 这条表达存在）；删掉那条纠错后变回 false。
收进去的纠错：`text` = 这条的 `natural`，`wrong` = 原话 `transcript`，`zh` = `「quote」→「better」：why`。

`latency_ms` = `think_ms` + 录音里第一个词的起始时间，只用来画趋势，不参与判定。

`ref_en` 是出题时生成的参考英文，「说自己」（`kind=self`）的题没有参考答案，为空字符串；`natural` 是判定时根据你说的内容给的自然说法。前端结果页始终显示题面和参考答案：`ref_en` 为空时用 `natural` 顶上；两者忽略大小写和标点后相同只显示一次。

### HistoryRow（`/items/{id}` 的 `history[]`，新的在前）

```json
{
  "review_id": 7, "day": "2026-11-13", "mode": "review", "kind": "cross", "result": "hold",
  "prompt_zh": "新工作每天要穿正装，朋友问你感觉怎么样？",
  "ref_en": "It felt weird at first, but I'm used to wearing a suit now.",
  "natural": "It felt weird at first, but I'm used to wearing a suit now.",
  "transcript": "it was weird at first but I'm used to wear a suit now", "latency_ms": 2900,
  "fix": { "quote": "used to wear", "better": "used to wearing", "why": "be used to 后面接 doing", "scope": "target" }
}
```

`ref_en`、`natural` 含义同 AnswerOut，可能为空字符串；`fix` 是那次指出的一处错误，没有就是 `null`。
