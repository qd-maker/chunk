// 练习流程（全屏）：看中文 → 开口说 → 看判定。每道题只显示中文，原句和骨架都不露出来。
import { useCallback, useEffect, useRef, useState, type CSSProperties } from "react";
import { api, ApiErr, type Answer, type Result, type Task } from "./api";
import { useBackLayer } from "./back";
import { afterAnswer, afterItemChange } from "./cache";
import { BARS, micErrorMessage, useRecorder, useWakeLock } from "./recorder";
import { ChunkText, dueLabel, KIND_LABEL, Ladder, Mic, modeLabel, refAnswer, sameSentence, secs, Stop, todayStr, ZhText } from "./ui";

type Phase = "loading" | "intro" | "ask" | "busy" | "result" | "done";
const VERDICT: Record<Result, string> = { pass: "用上了", hold: "用上了，差一点", fail: "没用上" };

export function Practice({ demo, onExit }: { demo: boolean; onExit: () => void }) {
  const [phase, setPhase] = useState<Phase>("loading");
  const [task, setTask] = useState<Task | null>(null);
  const [remaining, setRemaining] = useState(0);
  const [total, setTotal] = useState(0);   // 进度条总格数：已答 + 取题时还剩的
  const answered = useRef(0);
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [tally, setTally] = useState<Result[]>([]);
  const [hinted, setHinted] = useState(false);
  const [rejudge, setRejudge] = useState(false);
  const [err, setErr] = useState("");
  const [failed, setFailed] = useState<Blob | null>(null);   // 提交失败时留下的那段录音
  const [collecting, setCollecting] = useState(false);
  const [collectErr, setCollectErr] = useState("");
  const shownAt = useRef(0);
  const thinkMs = useRef(0);
  const rec = useRecorder(demo);

  const load = useCallback(async () => {
    setPhase("loading");
    setErr("");
    setFailed(null);
    try {
      const r = await api.next();
      setTask(r.task);
      setRemaining(r.remaining);
      setTotal(Math.min(24, answered.current + r.remaining));
      setAnswer(null);
      setHinted(false);
      setRejudge(false);
      setCollectErr("");
      if (!r.task) return setPhase("done");
      const showCard = r.task.mode === "intro" && r.task.round === 1;
      if (!showCard) shownAt.current = performance.now();
      setPhase(showCard ? "intro" : "ask");
    } catch (e) {
      setErr(e instanceof ApiErr ? e.message : "出题失败，再试一次。");
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  // 交一段录音去转写 + 判定。失败时把录音留着，可以原样再交一次
  const submit = async (blob: Blob) => {
    if (!task) return;
    setErr("");
    setFailed(null);
    setPhase("busy");
    try {
      const a = await api.answer(task.prompt.id, blob, thinkMs.current, hinted);
      setAnswer(a);
      afterAnswer(a);
      setTally(t => [...t, a.result]);
      answered.current += 1;
      setPhase("result");
    } catch (e) {
      const code = e instanceof ApiErr ? e.code : "";
      setErr(e instanceof ApiErr ? e.message : "提交失败了。");
      // 没听到声音、录音太大：同一段再交也没用，只能重说
      setFailed(code === "NO_SPEECH" || code === "AUDIO_TOO_LARGE" ? null : blob);
      shownAt.current = performance.now();
      setPhase("ask");
    }
  };

  const toggleRecord = async () => {
    if (!task) return;
    setErr("");
    setFailed(null);
    if (rec.phase === "idle") {
      thinkMs.current = performance.now() - shownAt.current;
      try { await rec.start(); } catch (e) { setErr(micErrorMessage(e)); }
      return;
    }
    await submit(await rec.stop());
  };

  const exit = () => { rec.cancel(); onExit(); };
  // 返回键：录音中先取消录音，留在这道题；否则退出练习
  useBackLayer(() => {
    if (rec.phase === "recording") { rec.cancel(); return true; }
    exit();
    return false;
  });
  // 录音和等判定期间屏幕不熄
  useWakeLock(rec.phase === "recording" || phase === "busy");

  const override = async (result: Result) => {
    if (!answer) return;
    try {
      const a = await api.override(answer.review_id, result);
      setAnswer(a);
      afterAnswer(a);
      setTally(t => [...t.slice(0, -1), a.result]);
      setRejudge(false);
    } catch (e) {
      setErr(e instanceof ApiErr ? e.message : "改判失败。");
    }
  };

  // 「顺带一提」的错收进我的纠错：新建一条纠错，库的缓存就地加上
  const collect = async () => {
    if (!answer || collecting) return;
    setCollecting(true);
    setCollectErr("");
    try {
      const it = await api.collect(answer.review_id);
      setAnswer(a => (a && a.review_id === answer.review_id ? { ...a, collected: true } : a));
      afterItemChange(it);
    } catch (e) {
      setCollectErr(e instanceof ApiErr ? e.message : "没收进去，再试一次。");
    } finally {
      setCollecting(false);
    }
  };

  const item = task?.item;
  const ref = answer ? refAnswer(answer.ref_en, answer.natural) : null;
  // 目标表达用对了、错在别处：只是提醒，不是扣分项
  const tip = !!answer?.fix && answer.used && answer.fix.scope === "other";

  return (
    <div className="practice">
      <div className="practice-in">
        <div className="pbar">
          <button className="close" onClick={exit} aria-label="退出练习">✕</button>
          <div className="dots" aria-label={`已完成 ${tally.length} 道，还剩 ${remaining} 道`}>
            {Array.from({ length: total }, (_, i) => {
              const doneCount = phase === "result" ? tally.length - 1 : tally.length;
              return <i key={i} className={i < doneCount ? "on" : i === doneCount && phase !== "done" ? "now" : ""} />;
            })}
          </div>
          {task && phase !== "done" && <span className="tag blue">{modeLabel(task.mode, task.item.step, task.round, task.rounds)}</span>}
        </div>

        {phase === "loading" && (
          <div className="stage">
            <div className="grow" />
            {err ? <><p className="err">{err}</p><button className="btn ghost" style={{ marginTop: 16 }} onClick={() => void load()}>重试</button></>
              : <p className="dim" style={{ textAlign: "center" }}>正在出题…</p>}
            <div className="grow" />
          </div>
        )}

        {phase === "intro" && item && (
          <div className="stage intro" key={`intro-${item.id}`}>
            <span className="tag">先认识一下，合上再练</span>
            <h1 className="en">{item.frame || item.text}</h1>
            <p className="zh">{item.frame_zh || item.zh}</p>
            {item.wrong && <div className="card"><p className="en wrong">{item.wrong}</p><small>你当时说的</small></div>}
            <div className="card"><p className="en"><ChunkText text={item.text} frame={item.frame} /></p><small>{item.zh}</small></div>
            {item.example && <div className="card"><p className="en"><ChunkText text={item.example} frame={item.frame} /></p><small>{item.example_zh}</small></div>}
            {(item.scene || item.usage) && <div className="card"><p style={{ fontSize: 15 }}>{item.scene || item.usage}</p><small>什么时候用</small></div>}
            <div className="grow" />
            <button className="btn" onClick={() => { shownAt.current = performance.now(); setPhase("ask"); }}>合上，开口练</button>
          </div>
        )}

        {(phase === "ask" || phase === "busy") && task && item && (
          <div className="stage" key={`ask-${task.prompt.id}`}>
            <div className="ask">
              <span className="tag">{KIND_LABEL[task.kind]}{task.prompt.topic ? ` · ${task.prompt.topic}` : ""}</span>
              <h1><ZhText text={task.prompt.zh} /></h1>
              <p>{task.kind === "self" ? "想一件真事，用英文说两三句。" : "用英文说出来。"}</p>
              <div className="hint">
                {hinted ? <><span className="tile frame en">{item.frame || item.text}</span><span className="mono dim">看了提示，这次不升级</span></>
                  : phase === "ask" && rec.phase === "idle" && <button className="link" onClick={() => setHinted(true)}>卡住了？看一眼骨架</button>}
              </div>
            </div>
            <div className="rec">
              <p className="rec-tip">{err ? <span className="err">{err}{failed && " 录音还在，可以直接再交一次。"}</span>
                : phase === "busy" ? "正在听你说的…" : rec.phase === "recording" ? "说完点一下" : "点一下，开口说"}</p>
              {failed && phase === "ask" && rec.phase === "idle" ? (
                <div className="retry">
                  <button className="btn" onClick={() => void submit(failed)}>重新提交</button>
                  <button className="btn ghost" onClick={() => void toggleRecord()}>重新说</button>
                </div>
              ) : <button className={`rec-btn${rec.phase === "recording" ? " on" : ""}${phase === "busy" ? " busy" : ""}`} disabled={phase === "busy"}
                onClick={() => void toggleRecord()} aria-label={rec.phase === "recording" ? "结束录音" : "开始录音"}>
                {phase === "busy" ? <span className="meter">{Array.from({ length: BARS }, (_, i) => <i key={i} style={{ "--i": i } as CSSProperties} />)}</span>
                  : rec.phase === "recording" ? <>
                    <span className="mono">{String(Math.floor(rec.seconds / 60)).padStart(2, "0")}:{String(rec.seconds % 60).padStart(2, "0")}</span>
                    <span className="meter">{rec.levels.map((v, i) => <i key={i} style={{ height: `${Math.max(10, v * 100)}%` }} />)}</span>
                    <Stop />
                  </> : <Mic />}
              </button>}
            </div>
          </div>
        )}

        {phase === "result" && answer && item && (
          <div className={`stage ${answer.result}`} key={`res-${answer.review_id}-${answer.result}`}>
            <div className="verdict">
              <span className="glyph" />
              <h1>{answer.result === "hold" && answer.hinted && answer.fix?.scope !== "target" ? "用上了，但看了提示" : VERDICT[answer.result]}</h1>
            </div>
            <div className="block card">
              <h3>你说的{answer.has_audio && !demo && <> · <button className="link" style={{ padding: 0, fontSize: 11 }}
                onClick={() => void new Audio(`/api/reviews/${answer.review_id}/audio`).play()}>听一遍</button></>}</h3>
              <p className="said en"><ChunkText text={answer.transcript} frame={answer.item.frame} quote={answer.fix?.quote} lime={answer.result === "pass"} /></p>
            </div>
            {answer.fix && tip && (
              <div className="block tip">
                <h3>顺带一提</h3>
                <div className="fixrow en"><s>{answer.fix.quote}</s><b>{answer.fix.better}</b></div>
                <p className="why">{answer.fix.why}</p>
                <div className="collect">
                  <button className="btn ghost small" disabled={answer.collected || collecting} onClick={() => void collect()}>
                    {answer.collected ? "已收进纠错" : collecting ? "正在收…" : "收进我的纠错"}
                  </button>
                  {collectErr && <span className="err">{collectErr}</span>}
                </div>
              </div>
            )}
            {answer.fix && !tip && (
              <div className="block card">
                <h3>{answer.used ? "改这一处" : "可以这样用进来"}</h3>
                {answer.used
                  ? <div className="fixrow en"><s>{answer.fix.quote}</s><b>{answer.fix.better}</b></div>
                  : <p className="en"><ChunkText text={answer.fix.better} frame={answer.item.frame} lime /></p>}
                <p style={{ fontSize: 15, marginTop: 8 }}>{answer.fix.why}</p>
              </div>
            )}
            {/* 题面 + 参考答案：不管判定如何都显示，空心框，比「你说的」安静一档 */}
            <div className="block ref">
              <h3>题目</h3>
              <p className="ref-zh">{task && <ZhText text={task.prompt.zh} />}</p>
              {ref && <>
                <h3>{ref.label}</h3>
                <p className="en"><ChunkText text={ref.text} frame={answer.item.frame} /></p>
              </>}
              {ref?.natural && !sameSentence(ref.natural, answer.transcript) && <>
                <h3>顺着你的说法</h3>
                <p className="en"><ChunkText text={ref.natural} frame={answer.item.frame} /></p>
              </>}
            </div>
            <div className="meta">
              <div className="card"><h3 className="mono dim" style={{ fontWeight: 400, marginBottom: 6 }}>开口用了</h3><b>{secs(answer.latency_ms)}</b></div>
              <div className="card"><h3 className="mono dim" style={{ fontWeight: 400, marginBottom: 6 }}>下次再练</h3>
                <b style={{ fontFamily: "var(--display)" }}>{answer.drills_owed > 0 || answer.item.intro_left > 0 ? "马上" : answer.graduated ? "毕业了" : dueLabel(answer.due_after, todayStr())}</b></div>
            </div>
            <div className="block card">
              <h3>{answer.graduated ? "五级都过了，以后每 30 天抽查一次" : answer.mode === "intro" ? "新表达当天先练 3 道，明天开始爬阶梯"
                : answer.mode === "drill" ? "补练不动阶梯" : "阶梯（天）"}</h3>
              <Ladder step={answer.step_after} status={answer.item.status} fresh={answer.step_after > answer.step_before ? answer.step_before : answer.graduated ? 5 : undefined} />
            </div>
            <div className="grow" />
            <div className="actions">
              {err && <p className="err">{err}</p>}
              <button className="btn" onClick={() => void load()}>{answer.drills_owed > 0 ? `补练 ${answer.drills_owed} 道` : remaining > 1 ? "下一题" : "完成"}</button>
              {rejudge ? (
                <div className="rejudge">
                  {(["pass", "hold", "fail"] as Result[]).filter(r => r !== answer.result).map(r =>
                    <button key={r} className="btn ghost small" onClick={() => void override(r)}>其实是「{VERDICT[r]}」</button>)}
                </div>
              ) : <button className="link" onClick={() => setRejudge(true)}>转写或判定不对？改判</button>}
            </div>
          </div>
        )}

        {phase === "done" && (
          <div className="stage">
            <div className="done-hero">
              <h1>今天<br />砌完了。</h1>
              {tally.length > 0 ? <>
                <p>{tally.length} 道题，{tally.filter(r => r === "pass").length} 道一次用上。</p>
                <div className="tally">{tally.map((r, i) => <i key={i} className={r} style={{ "--i": i } as CSSProperties} />)}</div>
              </> : <p className="dim">没有到期的表达。</p>}
            </div>
            <button className="btn ink" onClick={exit}>回首页</button>
          </div>
        )}
      </div>
    </div>
  );
}
