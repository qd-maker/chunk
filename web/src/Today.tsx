// 首页：今天有几道题，按「到期复习 / 新表达 / 补练」三种砖摆出来。
import { useToday } from "./cache";
import { dueLabel, Sk } from "./ui";

/** 第一次加载的骨架：大数字、三色条、按钮、三格统计。 */
function TodaySkeleton() {
  return (
    <div aria-busy="true" aria-label="加载中">
      <div className="hero"><Sk h={124} w="132px" r="var(--r-m)" /><Sk h={22} w="72px" style={{ marginBottom: 6 }} /></div>
      <Sk h={76} r="var(--r-m)" style={{ marginBottom: 24 }} />
      <Sk h={60} r="var(--r-m)" />
      <div className="stats">{[0, 1, 2].map(i => <Sk key={i} h={64} r="var(--r-m)" />)}</div>
    </div>
  );
}

export function Today({ demo, onStart, onLibrary }: { demo: boolean; onStart: () => void; onLibrary: () => void }) {
  const { data: d, error, reload } = useToday();

  if (!d) return error ? <><p className="err">{error}</p><button className="link" onClick={reload}>重试</button></> : <TodaySkeleton />;
  const parts = [
    { cls: "due", n: d.due, label: "到期复习" },
    { cls: "new", n: d.intro, label: "新表达" },
    { cls: "drill", n: d.drills, label: "补练" },
  ].filter(p => p.n > 0);

  return (
    <>
      {d.remaining > 0 ? <>
        <div className="hero">
          <b>{d.remaining}</b>
          <span>道题<small>约 {Math.max(1, Math.round(d.remaining * 0.6))} 分钟</small></span>
        </div>
        {parts.length > 1 ? (
          <div className="stack">
            {parts.map(p => <div key={p.cls} className={p.cls} style={{ flexGrow: p.n }}><b>{p.n}</b>{p.label}</div>)}
          </div>
        ) : <p className="note" style={{ margin: "0 0 24px" }}>全部是{parts[0]?.label}。</p>}
        <button className="btn" onClick={onStart}>开始练</button>
      </> : <>
        <div className="done-hero" style={{ margin: "8px 0 24px" }}>
          <h1>{d.active + d.graduated === 0 ? <>墙还是<br />空的。</> : <>今天<br />砌完了。</>}</h1>
          <p style={{ color: "var(--ink-2)" }}>
            {d.active + d.graduated === 0 ? "去库里挑两三个你最近真会用到的表达，激活后今天就开始练。"
              : d.next_due ? `下一块${dueLabel(d.next_due, d.date)}到期。` : "没有排着的表达了。"}
          </p>
        </div>
        <button className={d.active + d.graduated === 0 ? "btn" : "btn ghost"} onClick={onLibrary}>
          {d.new_left > 0 ? `去库里挑新的（今天还能加 ${d.new_left} 个）` : "去库里看看"}
        </button>
      </>}

      <div className="stats">
        <div><b>{d.streak}</b>连续天数</div>
        <div><b>{d.active}</b>在练</div>
        <div><b>{d.graduated}</b>已毕业</div>
      </div>
      {d.done_today > 0 && <p className="note">今天已经开口 {d.done_today} 次。</p>}
      {demo && <p className="note">演示模式：没有调用转写和大模型，判定结果是内置的假数据。</p>}
    </>
  );
}
