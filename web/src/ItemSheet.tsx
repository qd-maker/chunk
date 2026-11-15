// 一个表达的详情弹层：库里没练过的可以激活；练着的显示阶梯、下次时间和最近的练习记录（点开看题面和参考答案）。
import { useEffect, useState, type CSSProperties } from "react";
import { api, ApiErr, type HistoryRow, type Item } from "./api";
import { afterItemChange, peekItem } from "./cache";
import { BARS } from "./recorder";
import { ChunkText, dueLabel, KIND_LABEL, Ladder, refAnswer, sameSentence, secs, Sheet, SOURCE_LABEL, todayStr } from "./ui";

const ACTIVATING = "activate";

/** 激活要等后端调大模型出题（15–20 秒）：砖块律动 + 已等秒数。期间弹层锁住，不能关。 */
function Activating() {
  const [s, setS] = useState(0);
  useEffect(() => {
    const t0 = Date.now();
    const t = window.setInterval(() => setS(Math.floor((Date.now() - t0) / 1000)), 500);
    return () => clearInterval(t);
  }, []);
  return (
    <div className="activating busy" role="status" aria-live="polite">
      <span className="meter">{Array.from({ length: BARS }, (_, i) => <i key={i} style={{ "--i": i } as CSSProperties} />)}</span>
      <p>正在为这个表达出题，大约 15 秒</p>
      <span className="mono dim">已等 {s} 秒 · 出完题前这一页关不掉</span>
    </div>
  );
}

export function ItemSheet({ id, onClose }: { id: string; onClose: () => void }) {
  // 缓存里有这条就先显示出来，练习记录随后补上
  const [item, setItem] = useState<Item | null>(() => peekItem(id) ?? null);
  const [history, setHistory] = useState<HistoryRow[] | null>(null);
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");
  const [overLimit, setOverLimit] = useState(false);
  const [openRow, setOpenRow] = useState<number | null>(null);

  useEffect(() => {
    api.item(id).then(r => { setItem(r.item); setHistory(r.history); }).catch(e => setErr(e instanceof ApiErr ? e.message : "加载失败"));
  }, [id]);

  const run = async (label: string, fn: () => Promise<Item | void>, close = false) => {
    setBusy(label);
    setErr("");
    try {
      const next = await fn();
      if (next) setItem(next);
      setOverLimit(false);
      afterItemChange(next || null, next ? undefined : id);
      if (close) onClose();
    } catch (e) {
      if (e instanceof ApiErr && e.code === "DAILY_NEW_LIMIT" && !overLimit) setOverLimit(true);
      setErr(e instanceof ApiErr ? e.message : "操作失败");
    } finally {
      setBusy("");
    }
  };

  if (!item) return <Sheet onClose={onClose}><p className={err ? "err" : "dim"}>{err || "加载中…"}</p></Sheet>;
  const live = item.status !== "library";
  const today = todayStr();

  return (
    <Sheet onClose={onClose} locked={!!busy}>
      <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
        <span className="tag">{SOURCE_LABEL[item.source]}</span>
        {item.topic_zh && <span className="tag">{item.topic_zh}</span>}
        {item.first_batch && <span className="tag blue">首批推荐</span>}
      </div>
      <h2 className="en"><ChunkText text={item.text} frame={item.frame} /></h2>
      <p className="zh">{item.zh}</p>

      <div className="rows">
        {item.wrong && <div className="card"><p className="en" style={{ textDecoration: "line-through", textDecorationColor: "var(--miss)" }}>{item.wrong}</p><small className="dim">你当时说的</small></div>}
        {live && item.frame && <div className="card"><b className="en" style={{ fontSize: 18 }}>{item.frame}</b><br /><small className="dim">骨架 · {item.frame_zh}</small></div>}
        {item.example && <div className="card"><p className="en"><ChunkText text={item.example} frame={item.frame} /></p><small className="dim">{item.example_zh}</small></div>}
        {(item.scene || item.usage) && <div className="card"><p>{item.scene || item.usage}</p><small className="dim">什么时候用</small></div>}
      </div>

      {live && <>
        <div className="gap" />
        <Ladder step={item.step} status={item.status} />
        <p className="mono dim" style={{ marginTop: 8 }}>
          {item.status === "paused" ? "已暂停" : item.status === "graduated" ? `已毕业 · ${dueLabel(item.due, today)}抽查` : item.step === 0 ? "今天的新表达" : `下次 ${dueLabel(item.due, today)}`}
          {" · "}练过 {item.reps} 次{item.lapses > 0 && ` · 退过 ${item.lapses} 级`}
        </p>
        {history && history.length > 0 && <>
          <div className="gap" />
          <p className="group">练习记录 · 点一条看题目和参考答案</p>
          <div className="hist">
            {history.slice(0, 6).map(h => {
              const on = openRow === h.review_id;
              const ref = refAnswer(h.ref_en, h.natural);
              return (
                <button key={h.review_id} className="hrow" aria-expanded={on} onClick={() => setOpenRow(on ? null : h.review_id)}>
                  <i className={h.result} />
                  <span><span className="said-line en">{h.transcript}</span><small className={on ? "" : "clip"}>{h.prompt_zh}</small></span>
                  <span className="mono dim">{h.day.slice(5)} · {KIND_LABEL[h.kind]}<br />{secs(h.latency_ms)}</span>
                  {on && (
                    <span className="hmore">
                      {h.fix && <>
                        <small>{h.result === "fail" ? "可以这样用进来" : h.fix.scope === "other" ? "顺带一提" : "改这一处"}</small>
                        {h.result === "fail"
                          ? <span className="en"><ChunkText text={h.fix.better} frame={item.frame} /></span>
                          : <span className="fixrow en"><s>{h.fix.quote}</s><b>{h.fix.better}</b></span>}
                        <small>{h.fix.why}</small>
                      </>}
                      {ref ? <>
                        <small>{ref.label}</small>
                        <span className="en"><ChunkText text={ref.text} frame={item.frame} /></span>
                        {ref.natural && !sameSentence(ref.natural, h.transcript) && <>
                          <small>顺着你的说法</small>
                          <span className="en"><ChunkText text={ref.natural} frame={item.frame} /></span>
                        </>}
                      </> : <small>这道题没有参考答案</small>}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        </>}
      </>}

      <div className="gap" />
      {err && <p className="err" style={{ marginBottom: 12 }}>{err}</p>}
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {busy === ACTIVATING ? <Activating /> : item.status === "library" && (overLimit
          ? <button className="btn ink" disabled={!!busy} onClick={() => void run(ACTIVATING, () => api.activate(id, true))}>还是要加</button>
          : <button className="btn" disabled={!!busy} onClick={() => void run(ACTIVATING, () => api.activate(id))}>激活，今天开始练</button>)}
        {(item.status === "active" || item.status === "graduated") &&
          <button className="btn ghost" disabled={!!busy} onClick={() => void run("…", () => api.pause(id))}>先暂停</button>}
        {item.status === "paused" &&
          <button className="btn" disabled={!!busy} onClick={() => void run("…", () => api.resume(id))}>恢复练习</button>}
        {(item.source === "fix" || item.source === "custom") &&
          <button className="link" disabled={!!busy} onClick={() => { if (confirm("删除这条？练习记录也会一起删掉。")) void run("…", () => api.remove(id), true); }}>删除这条</button>}
      </div>
    </Sheet>
  );
}
