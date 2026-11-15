// 几个页面共用的小零件：状态方块、阶梯、表达高亮、参考答案、骨架块、底部弹层、日期和秒数的写法。
import type { CSSProperties, ReactNode } from "react";
import type { Item, Kind, Mode } from "./api";
import { useBackLayer } from "./back";

export const STEPS = [1, 3, 7, 14, 30];
export const KIND_LABEL: Record<Kind, string> = { swap: "换内容", cross: "换话题", self: "说自己" };
export const SOURCE_LABEL: Record<Item["source"], string> = {
  pattern: "句式", link: "衔接", chunk: "词块", topic_pattern: "话题句式", fix: "纠错", custom: "自己加的",
};

export function modeLabel(mode: Mode, step: number, round: number, rounds: number): string {
  if (mode === "intro") return `新表达 ${round}/${rounds}`;
  if (mode === "drill") return `补练 ${round}/${rounds}`;
  if (mode === "check") return "毕业抽查";
  return `第 ${STEPS[Math.max(0, step - 1)]} 天`;
}

export const secs = (ms: number) => `${(ms / 1000).toFixed(1)}s`;

export function dayDiff(due: string, today: string): number {
  return Math.round((Date.parse(due) - Date.parse(today)) / 86_400_000);
}
export function dueLabel(due: string | null, today: string): string {
  if (!due) return "—";
  const d = dayDiff(due, today);
  if (d <= 0) return "今天";
  if (d === 1) return "明天";
  return d <= 30 ? `${d} 天后` : due.slice(5);
}
export const todayStr = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

/** 状态小方块：空心 = 没练过，蓝色水位 = 爬到第几级，青柠 = 毕业，斜纹 = 暂停。 */
export function Mark({ item }: { item: Pick<Item, "status" | "step"> }) {
  if (item.status === "graduated") return <span className="mark grad" aria-label="已毕业" />;
  if (item.status === "paused") return <span className="mark paused" aria-label="已暂停" />;
  const fill = item.status === "active" ? `${Math.max(12, (item.step / 5) * 100)}%` : "0%";
  return <span className="mark" style={{ "--fill": fill } as CSSProperties} aria-label={item.status === "active" ? `第 ${item.step} 级` : "没练过"} />;
}

/** 阶梯 1·3·7·14·30：实心 = 已通过，粗框 = 下一次要过的那一级。fresh 指刚刚升上来的那一格（播一次落下动画）。 */
export function Ladder({ step, status, fresh }: { step: number; status: string; fresh?: number }) {
  const grad = status === "graduated";
  return (
    <div className={`ladder${grad ? " grad" : ""}`} role="img" aria-label={grad ? "已毕业" : `阶梯第 ${step} 级`}>
      {STEPS.map((d, i) => {
        const n = i + 1;
        const cls = grad || n < step ? "done" : n === step ? "next" : "";
        return <div key={d} className={`${cls}${fresh === n ? " new" : ""}`}>{d}</div>;
      })}
    </div>
  );
}

// ---- 在句子里把目标表达标成一块砖 ----
const PLACEHOLDER = /\b(doing|to do|do|done|sth|something|sb|somebody|someone|adj|noun|verb)\b\.?/gi;
const SWAP: Record<string, string> = {
  i: "(?:i|we|he|she|they|you|it)", my: "(?:my|your|his|her|our|their)", me: "(?:me|you|him|her|us|them)",
  myself: "(?:myself|yourself|himself|herself|ourselves|themselves)",
  be: "(?:be|am|is|are|was|were|been|being|'m|'s|'re)", am: "(?:am|is|are|was|were|'m|'s|'re)", is: "(?:am|is|are|was|were|'m|'s|'re)",
  have: "(?:have|has|had|having|'ve|'d)", "i'm": "(?:i'm|we're|he's|she's|they're|you're|i am|i was)",
  "it's": "(?:it's|it is|it was)", "don't": "(?:don't|doesn't|didn't|do not)", "i've": "(?:i've|we've|they've|you've|he's|she's|i have)",
};
const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
function wordRe(w: string): string {
  const k = w.toLowerCase();
  if (SWAP[k]) return SWAP[k];
  if (!/^[a-z]+$/.test(k) || k.length < 3) return esc(k);
  // ended / ending / ends 都认：先去掉词尾，再放开常见词形
  let stem = (k.length > 4 ? k.replace(/(ing|ed|es|s)$/, "") : k).replace(/e$/, "");
  if (stem.length < 2) stem = k;
  return `${esc(stem)}(?:e|es|ed|d|ing|s)?`;
}
function literalParts(frame: string): string[][] {
  return frame.split(/\+|\.\.\.|…|;|,|\/|\(|\)/)
    .map(p => p.replace(PLACEHOLDER, " ").replace(/[^A-Za-z' ]/g, " ").trim().split(/\s+/).filter(Boolean))
    .filter(ws => ws.join("").length >= 2);
}
/** 返回 text 里属于目标表达的区间。骨架里的占位词（doing、sth）不算；首个代词对不上时去掉再找一次。 */
export function findChunk(text: string, frame: string): [number, number][] {
  const out: [number, number][] = [];
  for (let words of literalParts(frame)) {
    while (words.length && (words.length > 1 || words[0].length >= 4)) {
      const m = new RegExp(`(?<![A-Za-z'])${words.map(wordRe).join("[\\s,]+")}(?![A-Za-z])`, "i").exec(text);
      if (m) { out.push([m.index, m.index + m[0].length]); break; }
      words = words.slice(1);
    }
  }
  return out.sort((a, b) => a[0] - b[0]).filter((r, i, all) => i === 0 || r[0] >= all[i - 1][1]);
}

/** 一句英文：目标表达显示成砖块，quote（要改的原话片段）加波浪线。 */
export function ChunkText({ text, frame, quote, lime }: { text: string; frame: string; quote?: string; lime?: boolean }) {
  const marks: { a: number; b: number; kind: "tile" | "u" }[] = findChunk(text, frame).map(([a, b]) => ({ a, b, kind: "tile" }));
  const q = quote ? text.toLowerCase().indexOf(quote.toLowerCase()) : -1;
  if (q >= 0 && quote && !marks.some(m => q < m.b && q + quote.length > m.a)) marks.push({ a: q, b: q + quote.length, kind: "u" });
  marks.sort((x, y) => x.a - y.a);
  const parts: ReactNode[] = [];
  let at = 0;
  marks.forEach((m, i) => {
    if (m.a > at) parts.push(text.slice(at, m.a));
    const s = text.slice(m.a, m.b);
    // 砖后面紧跟的标点和砖绑在一起，不然句号会单独掉到下一行（砖太长时不绑，让它自己换行）
    const punct = m.kind === "tile" && s.length <= 28 ? (/^[.,!?;:…]+/.exec(text.slice(m.b))?.[0] ?? "") : "";
    const el = m.kind === "tile" ? <span key={i} className={`tile${lime ? " lime" : ""}`}>{s}</span> : <u key={i}>{s}</u>;
    parts.push(punct ? <span key={`${i}p`} style={{ whiteSpace: "nowrap" }}>{el}{punct}</span> : el);
    at = m.b + punct.length;
  });
  if (at < text.length) parts.push(text.slice(at));
  return <>{parts}</>;
}

/** 两句英文是不是一回事：忽略大小写、标点和空格。 */
export const sameSentence = (a: string, b: string) => a.toLowerCase().replace(/[^a-z0-9']/g, "") === b.toLowerCase().replace(/[^a-z0-9']/g, "");

/** 参考答案怎么显示：有 ref_en 就叫「参考答案」，natural 和它不同才另外列；「说自己」没有 ref_en，用 natural 顶上。 */
export function refAnswer(ref_en: string, natural: string): { label: string; text: string; natural: string } | null {
  if (ref_en.trim()) return { label: "参考答案", text: ref_en, natural: natural.trim() && !sameSentence(natural, ref_en) ? natural : "" };
  if (natural.trim()) return { label: "可以这样说", text: natural, natural: "" };
  return null;
}

/** 中文大标题：按标点切成小段，每段尽量不拆开，这样优先在标点后换行，不会「最 / 后还是」这样断。段太长（超过 12 个字）就不包，允许段内换行。 */
export function ZhText({ text }: { text: string }) {
  const segs = text.split(/(?<=[，。；？！、,;?!])/).filter(Boolean);
  return <>{segs.map((s, i) => (s.length > 12 ? <span key={i}>{s}</span> : <span key={i} className="zh-seg">{s}</span>))}</>;
}

/** 骨架块：第一次加载时占住真实内容的位置。 */
export const Sk = ({ h, w, r, style }: { h: number; w?: string; r?: string; style?: CSSProperties }) =>
  <span className="sk" style={{ height: h, width: w, borderRadius: r, ...style }} />;

/** 底部弹层。locked = 正在提交，点遮罩和按返回都不关（防重复提交）。 */
export function Sheet({ onClose, locked, children }: { onClose: () => void; locked?: boolean; children: ReactNode }) {
  useBackLayer(() => {
    if (locked) return true;
    onClose();
    return false;
  });
  return (
    <div className="scrim" onClick={() => { if (!locked) onClose(); }}>
      <div className="sheet" role="dialog" aria-modal="true" onClick={e => e.stopPropagation()}>
        <div className="grab" />
        {children}
      </div>
    </div>
  );
}

export const Mic = () => (
  <svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true">
    <rect x="8.5" y="2.5" width="7" height="12" rx="3.5" fill="currentColor" stroke="none" />
    <path d="M5 11.5a7 7 0 0 0 14 0M12 18.5v3" />
  </svg>
);
export const Stop = () => (
  <svg width="26" height="26" viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="4" width="16" height="16" rx="4" fill="currentColor" /></svg>
);
