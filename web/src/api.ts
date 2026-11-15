// 和 docs/API.md 一一对应的类型和请求函数。

export type Result = "pass" | "hold" | "fail";
export type Kind = "swap" | "cross" | "self";
export type Mode = "intro" | "review" | "drill" | "check";

export interface Item {
  id: string; source: "pattern" | "link" | "chunk" | "topic_pattern" | "fix" | "custom";
  topic_no: number | null; topic_zh: string; grp: string;
  text: string; zh: string; example: string; example_zh: string; usage: string; wrong: string; first_batch: boolean;
  frame: string; frame_zh: string; scene: string;
  status: "library" | "active" | "graduated" | "paused";
  step: number; due: string | null; intro_left: number; drills_owed: number; reps: number; lapses: number;
  activated_at: string | null; latency_ms: number | null;
}
export interface Prompt { id: number; kind: Kind; zh: string; topic: string }
export interface Task { mode: Mode; kind: Kind; round: number; rounds: number; prompt: Prompt; item: Item }
// scope：target = 错在目标表达本身（不升级）；other = 错在句子别处（照样升级，只顺带一提）
export interface Fix { quote: string; better: string; why: string; scope: "target" | "other" }
export interface Answer {
  review_id: number; mode: Mode; kind: Kind; transcript: string; used: boolean; correct: boolean; hinted: boolean;
  result: Result; fix: Fix | null; natural: string; ref_en: string; think_ms: number; latency_ms: number;
  step_before: number; step_after: number; due_after: string | null; graduated: boolean; drills_owed: number;
  overridden: boolean; has_audio: boolean;
  collected: boolean;   // 这条的错误是否已经收进「我的纠错」
  item: Item;
}
export interface Today {
  date: string; due: number; intro: number; drills: number; remaining: number; done_today: number; new_left: number;
  active: number; graduated: number; streak: number; next_due: string | null;
}
export interface Topic { no: number; zh: string; grp: string; total: number; active: number }
export interface Library { items: Item[]; topics: Topic[]; new_left: number; new_per_day: number }
export interface HistoryRow {
  review_id: number; day: string; mode: Mode; kind: Kind; result: Result; prompt_zh: string;
  ref_en: string; natural: string;   // 参考答案（「说自己」为空）和判定给的自然说法
  transcript: string; latency_ms: number;
  fix: Fix | null;      // 那次指出的一处错误
}
export interface Wall {
  bricks: Item[]; by_step: number[]; latency: { day: string; ms: number; n: number }[];
  reviews_7d: number; pass_rate_7d: number | null; streak: number;
}
export interface Health { ok: boolean; fake: boolean; asr_ready: boolean; llm_ready: boolean; auth_required: boolean }

export class ApiErr extends Error {
  constructor(public status: number, public code: string, message: string) { super(message); }
}

let onUnauthorized: () => void = () => {};
export const setUnauthorizedHandler = (fn: () => void) => { onUnauthorized = fn; };

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let r: Response;
  try {
    r = await fetch(`/api${path}`, { credentials: "same-origin", ...init });
  } catch {
    throw new ApiErr(0, "NETWORK", "连不上服务，检查一下网络。");
  }
  if (r.status === 204) return undefined as T;
  const body = await r.json().catch(() => null);
  if (!r.ok) {
    if (r.status === 401 && body?.error?.code === "UNAUTHORIZED") onUnauthorized();
    throw new ApiErr(r.status, body?.error?.code ?? "UNKNOWN", body?.error?.message ?? `请求失败（${r.status}）`);
  }
  return body as T;
}

const json = (method: string, data?: unknown): RequestInit =>
  ({ method, headers: { "Content-Type": "application/json" }, body: data === undefined ? undefined : JSON.stringify(data) });

export const api = {
  health: () => call<Health>("/health"),
  session: () => call<{ authed: boolean; auth_required: boolean }>("/session"),
  login: (password: string) => call<void>("/login", json("POST", { password })),
  today: () => call<Today>("/today"),
  next: () => call<{ task: Task | null; remaining: number }>("/next"),
  answer: (promptId: number, audio: Blob, thinkMs: number, hinted: boolean) => {
    const fd = new FormData();
    fd.append("prompt_id", String(promptId));
    fd.append("think_ms", String(Math.max(0, Math.round(thinkMs))));
    fd.append("hinted", hinted ? "1" : "0");
    fd.append("audio", audio, "answer");
    return call<Answer>("/answer", { method: "POST", body: fd });
  },
  override: (reviewId: number, result: Result) => call<Answer>(`/reviews/${reviewId}/override`, json("POST", { result })),
  collect: (reviewId: number) => call<Item>(`/reviews/${reviewId}/collect`, json("POST")),
  library: () => call<Library>("/library"),
  item: (id: string) => call<{ item: Item; history: HistoryRow[] }>(`/items/${id}`),
  createItem: (data: { kind: "fix" | "custom"; text: string; zh: string; wrong: string }) => call<Item>("/items", json("POST", data)),
  activate: (id: string, force = false) => call<Item>(`/items/${id}/activate${force ? "?force=true" : ""}`, json("POST")),
  pause: (id: string) => call<Item>(`/items/${id}/pause`, json("POST")),
  resume: (id: string) => call<Item>(`/items/${id}/resume`, json("POST")),
  remove: (id: string) => call<void>(`/items/${id}`, { method: "DELETE" }),
  wall: () => call<Wall>("/wall"),
};
