// 表达库：素材库里的句式、衔接表达、话题词块，加上自己的纠错。只有激活的才进排期。顶上可以搜。
import { useMemo, useRef, useState, type FormEvent } from "react";
import { api, ApiErr, type Item, type Library as Lib, type Topic } from "./api";
import { afterItemChange, useLibrary } from "./cache";
import { ItemSheet } from "./ItemSheet";
import { Mark, Sheet, Sk, SOURCE_LABEL } from "./ui";

type Tab = "pattern" | "link" | "topics" | "mine";
const GROUPS: Record<string, string> = { A: "A · 生活型", B: "B · 经历型", C: "C · 观点型" };

function Row({ item, no, onOpen }: { item: Item; no: string; onOpen: (id: string) => void }) {
  return (
    <button className="row" onClick={() => onOpen(item.id)}>
      <span className="no">{no}</span>
      <span>
        <p className="en">{item.text}</p>
        <small>{item.zh}{item.first_batch && <span className="star"> · 首批</span>}</small>
      </span>
      <Mark item={item} />
    </button>
  );
}

function groupBy<T>(xs: T[], key: (x: T) => string): [string, T[]][] {
  const m = new Map<string, T[]>();
  xs.forEach(x => m.set(key(x), [...(m.get(key(x)) ?? []), x]));
  return [...m.entries()];
}

/** 第一次加载的骨架：分段按钮、名额条、一列行。 */
function LibrarySkeleton() {
  return (
    <div aria-busy="true" aria-label="加载中">
      <div className="seg">{[64, 64, 64, 96].map((w, i) => <Sk key={i} h={44} w={`${w}px`} r="12px" style={{ flex: "none" }} />)}</div>
      <Sk h={14} w="80%" r="4px" style={{ marginBottom: 16 }} />
      <div className="rows">{Array.from({ length: 8 }, (_, i) => <Sk key={i} h={68} r="var(--r-m)" />)}</div>
    </div>
  );
}

// 按来源分好组，只在库数据变化时算一次（素材库可能有几百条，别每次渲染都过滤）
function useGroups(lib: Lib | undefined) {
  return useMemo(() => {
    const m = { pattern: [] as Item[], link: [] as Item[], chunk: [] as Item[], topic_pattern: [] as Item[], mine: [] as Item[] };
    lib?.items.forEach(i => m[i.source === "fix" || i.source === "custom" ? "mine" : i.source].push(i));
    return {
      ...m,
      links: groupBy(m.link, i => i.topic_zh),
      topicGroups: groupBy(lib?.topics ?? [], t => t.grp),
    };
  }, [lib]);
}

export function Library() {
  const { data: lib, error, reload } = useLibrary();
  const [tab, setTab] = useState<Tab>("pattern");
  const [topic, setTopic] = useState<Topic | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [input, setInput] = useState("");     // 输入框里的字（含正在拼的拼音）
  const [query, setQuery] = useState("");     // 真正拿去过滤的词：输入法组合期间不更新
  const composing = useRef(false);
  const [firstOnly, setFirstOnly] = useState(false);
  const g = useGroups(lib);
  const topicItems = useMemo(() => topic && lib ? {
    chunk: lib.items.filter(i => i.source === "chunk" && i.topic_no === topic.no),
    topic_pattern: lib.items.filter(i => i.source === "topic_pattern" && i.topic_no === topic.no),
  } : null, [lib, topic]);
  // 搜索用的小写全文，只在库变化时拼一次
  const index = useMemo(() => (lib?.items ?? []).map(i => ({ i, hay: [i.text, i.zh, i.frame, i.frame_zh, i.wrong, i.topic_zh].join("\n").toLowerCase() })), [lib]);
  const q = query.trim().toLowerCase();
  const hits = useMemo(() => {
    const words = q.split(/\s+/).filter(Boolean);   // 空格隔开的几个词都要命中
    return words.length ? index.filter(x => words.every(w => x.hay.includes(w))).map(x => x.i) : [];
  }, [index, q]);
  const firstBatch = useMemo(() => g.pattern.filter(i => i.first_batch), [g]);

  if (!lib) return error ? <><p className="err">{error}</p><button className="link" onClick={reload}>重试</button></> : <LibrarySkeleton />;
  const searching = q.length > 0;
  const setSearch = (v: string) => { setInput(v); if (!composing.current) setQuery(v); };
  const mine = g.mine;
  const tabs: { id: Tab; label: string; n: number }[] = [
    { id: "pattern", label: "句式", n: g.pattern.length }, { id: "link", label: "衔接", n: g.link.length },
    { id: "topics", label: "话题", n: lib.topics.length }, { id: "mine", label: "我的纠错", n: mine.length },
  ];

  return (
    <>
      <div className="search">
        <input type="search" enterKeyHint="search" placeholder="搜英文或中文" aria-label="搜索表达" value={input}
          onChange={e => setSearch(e.target.value)}
          onCompositionStart={() => { composing.current = true; }}
          onCompositionEnd={e => { composing.current = false; setQuery(e.currentTarget.value); }} />
        {input && <button className="clear" aria-label="清空搜索" onClick={() => { composing.current = false; setInput(""); setQuery(""); }}>✕</button>}
      </div>

      {searching ? <>
        {/* 搜索时跨所有来源，最多列 80 条 */}
        <p className="group">{hits.length ? `找到 ${hits.length} 条` : "没有找到，换个词试试"}</p>
        <div className="rows">{hits.slice(0, 80).map(i => <Row key={i.id} item={i} no={SOURCE_LABEL[i.source]} onOpen={setOpen} />)}</div>
        {hits.length > 80 && <p className="note">只列了前 80 条，再多打几个字缩小范围。</p>}
      </> : <>
      <div className="seg">
        {tabs.map(t => <button key={t.id} aria-pressed={tab === t.id} onClick={() => { setTab(t.id); setTopic(null); }}>{t.label}<small>{t.n}</small></button>)}
      </div>
      <div className="quota">
        {Array.from({ length: lib.new_per_day }, (_, i) => <i key={i} className={i < lib.new_left ? "" : "used"} />)}
        <span>{lib.new_left > 0 ? `今天还能激活 ${lib.new_left} 个。每天只练少量，练熟再加。` : "今天的新表达加满了，先把它们练熟。"}</span>
      </div>

      {tab === "pattern" && <>
        <button className="toggle" aria-pressed={firstOnly} onClick={() => setFirstOnly(v => !v)}><i />只看首批推荐<small>{firstBatch.length}</small></button>
        <div className="rows">{(firstOnly ? firstBatch : g.pattern).map(i => <Row key={i.id} item={i} no={i.id.slice(3)} onOpen={setOpen} />)}</div>
      </>}

      {tab === "link" && g.links.map(([cat, items]) => (
        <div key={cat}>
          <p className="group">{cat}</p>
          <div className="rows">{items.map(i => <Row key={i.id} item={i} no={i.id.slice(2)} onOpen={setOpen} />)}</div>
        </div>
      ))}

      {tab === "topics" && !topic && g.topicGroups.map(([grp, ts]) => (
        <div key={grp}>
          <p className="group">{GROUPS[grp] ?? grp} · {ts.length}</p>
          <div className="topics">
            {ts.map(t => (
              <button key={t.no} className="topic" onClick={() => { setTopic(t); window.scrollTo(0, 0); }}>
                <b>{t.zh}</b>
                <span><span className="mono dim">{String(t.no).padStart(2, "0")}</span>
                  <span className="pips">{Array.from({ length: t.total }, (_, i) => <i key={i} className={i < t.active ? "on" : ""} />)}</span></span>
              </button>
            ))}
          </div>
        </div>
      ))}

      {tab === "topics" && topic && <>
        <button className="back" onClick={() => setTopic(null)}>← 全部话题</button>
        <h2 style={{ fontSize: 24, marginBottom: 16 }}>{topic.zh}</h2>
        {([["chunk", "词块"], ["topic_pattern", "句式"]] as const).map(([src, label]) => (
          <div key={src}>
            <p className="group">{label}</p>
            <div className="rows">
              {(topicItems?.[src] ?? []).map((i, k) => <Row key={i.id} item={i} no={String(k + 1).padStart(2, "0")} onOpen={setOpen} />)}
            </div>
          </div>
        ))}
      </>}

      {tab === "mine" && <>
        <button className="btn ink" style={{ marginBottom: 16 }} onClick={() => setAdding(true)}>＋ 记一条纠错</button>
        {mine.length ? <div className="rows">{mine.map((i, k) => <Row key={i.id} item={i} no={String(k + 1).padStart(2, "0")} onOpen={setOpen} />)}</div>
          : <div className="empty"><h2>还没有纠错</h2><p>自由说的时候反复出现的那一两个错误，记在这里，和表达一起按天数回来练。</p></div>}
      </>}
      </>}

      {open && <ItemSheet id={open} onClose={() => setOpen(null)} />}
      {adding && <AddFix onClose={() => setAdding(false)} onAdded={item => { setAdding(false); afterItemChange(item); setOpen(item.id); }} />}
    </>
  );
}

function AddFix({ onClose, onAdded }: { onClose: () => void; onAdded: (item: Item) => void }) {
  const [wrong, setWrong] = useState("");
  const [text, setText] = useState("");
  const [zh, setZh] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      const item = await api.createItem({ kind: "fix", text: text.trim(), zh: zh.trim(), wrong: wrong.trim() });
      onAdded(item);
    } catch (x) {
      setErr(x instanceof ApiErr ? x.message : "保存失败");
      setBusy(false);
    }
  };
  return (
    <Sheet onClose={onClose}>
      <h2 style={{ marginTop: 0 }}>记一条纠错</h2>
      <p className="zh">只记反复出现的错误，一次一条。</p>
      <form className="form" onSubmit={submit}>
        <label>我当时说的<textarea rows={2} value={wrong} onChange={e => setWrong(e.target.value)} placeholder="I send more than ten resume." /></label>
        <label>自然的说法<textarea rows={2} required minLength={2} value={text} onChange={e => setText(e.target.value)} placeholder="I sent out more than ten resumes." /></label>
        <label>错在哪（中文）<input value={zh} onChange={e => setZh(e.target.value)} placeholder="可数名词要用复数；投简历用 send out" /></label>
        {err && <p className="err">{err}</p>}
        <button className="btn" disabled={busy || text.trim().length < 2}>保存</button>
      </form>
    </Sheet>
  );
}
