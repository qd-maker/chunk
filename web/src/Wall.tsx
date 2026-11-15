// 进度墙：每个激活的表达是一块砖，颜色越实说明爬得越高，青柠是毕业。下面是开口延迟的趋势。
import { useState, type CSSProperties } from "react";
import type { Item } from "./api";
import { useWall } from "./cache";
import { ItemSheet } from "./ItemSheet";
import { secs, Sk, todayStr } from "./ui";

const label = (i: Item) => (i.frame || i.text).replace(/[.!?]$/, "");
function brickClass(i: Item, today: string): string {
  const tone = i.status === "graduated" ? "grad" : i.status === "paused" ? "paused" : `s${i.step}`;
  const due = i.status !== "paused" && !!i.due && i.due <= today;
  return `brick en ${tone}${due ? " duenow" : ""}`;
}
// 砖的宽度跟着文字长度走，一行排满后自动错缝，看起来像砌出来的墙
const basis = (text: string) => (text.length < 13 ? "24%" : text.length < 21 ? "34%" : "48%");

/** 第一次加载的骨架：大数字、一面空砖墙、开口延迟的框。 */
function WallSkeleton() {
  return (
    <div aria-busy="true" aria-label="加载中">
      <div className="wall-head"><Sk h={56} w="160px" r="var(--r-s)" /><Sk h={14} w="220px" r="4px" style={{ marginTop: 12 }} /></div>
      <div className="wall">{["34%", "48%", "48%", "24%", "24%", "34%", "34%", "48%", "24%"].map((b, i) =>
        <Sk key={i} h={48} r="12px" style={{ flex: `1 1 ${b}` }} />)}</div>
      <Sk h={14} w="70%" r="4px" style={{ margin: "12px 0 32px" }} />
      <Sk h={22} w="96px" r="4px" style={{ marginBottom: 12 }} />
      <Sk h={132} r="var(--r-m)" />
    </div>
  );
}

export function Wall({ onLibrary }: { onLibrary: () => void }) {
  const { data: w, error, reload } = useWall();
  const [open, setOpen] = useState<string | null>(null);

  if (!w) return error ? <><p className="err">{error}</p><button className="link" onClick={reload}>重试</button></> : <WallSkeleton />;
  const today = todayStr();
  const grad = w.by_step[6];
  const live = w.bricks.length - grad;

  if (!w.bricks.length) {
    return (
      <>
        <div className="wall" aria-hidden="true" style={{ opacity: .55 }}>
          {["34%", "48%", "48%", "24%", "24%", "34%", "34%", "48%", "24%"].map((b, i) => <span key={i} className="brick" style={{ flexBasis: b, "--i": i } as CSSProperties} />)}
        </div>
        <div className="empty">
          <h2>还没有砖</h2>
          <p>每激活一个表达，这里就多一块砖。按 1、3、7、14、30 天回来用它说新的事，砖会一级一级变实。</p>
        </div>
        <button className="btn" onClick={onLibrary}>去库里挑第一块</button>
      </>
    );
  }

  return (
    <>
      <div className="wall-head">
        <h1>{live}<small>块在练</small>{grad > 0 && <> {grad}<small>块毕业</small></>}</h1>
        <p className="mono dim" style={{ marginTop: 8 }}>
          连续 {w.streak} 天 · 近 7 天开口 {w.reviews_7d} 次{w.pass_rate_7d !== null && ` · 一次用上 ${Math.round(w.pass_rate_7d * 100)}%`}
        </p>
      </div>

      <div className="wall">
        {w.bricks.map((b, i) => (
          <button key={b.id} className={brickClass(b, today)} style={{ flexBasis: basis(label(b)), "--i": Math.min(i, 30) } as CSSProperties}
            onClick={() => setOpen(b.id)} title={b.text}>{label(b)}</button>
        ))}
      </div>
      <div className="legend">
        <span><i style={{ boxShadow: "inset 0 0 0 1.5px var(--line)" }} />刚开始</span>
        <span><i style={{ background: "color-mix(in srgb, var(--blue) 42%, var(--bg))" }} />第 7 天</span>
        <span><i style={{ background: "var(--blue)" }} />第 30 天</span>
        <span><i style={{ background: "var(--lime)" }} />毕业</span>
        <span>右上角有点 = 今天到期</span>
      </div>

      <h2 className="sec">开口延迟</h2>
      <p>看到题到开口的时间，每天取中位数。一格是半秒，越矮说明越接近脱口而出。</p>
      {w.latency.length ? (
        <div className="lat">
          {w.latency.map(p => (
            <div className="col" key={p.day} title={`${p.day} · ${secs(p.ms)} · ${p.n} 次`}>
              {Array.from({ length: Math.max(1, Math.min(12, Math.round(p.ms / 500))) }, (_, i) => <i key={i} />)}
              <span>{p.day.slice(8)}</span>
            </div>
          ))}
        </div>
      ) : <p className="dim">练过之后这里会出现记录。</p>}
      {w.latency.length > 0 && <p className="mono dim" style={{ marginTop: 8 }}>最近一天 {secs(w.latency[w.latency.length - 1].ms)}</p>}

      {open && <ItemSheet id={open} onClose={() => setOpen(null)} />}
    </>
  );
}
