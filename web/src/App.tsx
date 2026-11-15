import { useEffect, useState, type FormEvent } from "react";
import { api, ApiErr, setUnauthorizedHandler } from "./api";
import { clearCache, prefetchAll, refreshAll } from "./cache";
import { Library } from "./Library";
import { Practice } from "./Practice";
import { Today } from "./Today";
import { Wall } from "./Wall";

type Tab = "today" | "library" | "wall";
const TABS: { id: Tab; label: string }[] = [{ id: "today", label: "练" }, { id: "library", label: "库" }, { id: "wall", label: "墙" }];

export function App() {
  const [authed, setAuthed] = useState<boolean | null>(null);
  const [demo, setDemo] = useState(false);
  const [tab, setTab] = useState<Tab>("today");
  const [practicing, setPracticing] = useState(false);

  useEffect(() => {
    setUnauthorizedHandler(() => { clearCache(); setAuthed(false); });   // 登录过期：缓存全清掉
    api.session().then(s => setAuthed(s.authed)).catch(() => setAuthed(true));
    api.health().then(h => setDemo(h.fake)).catch(() => {});
  }, []);
  // 登录通过后预取三页数据，第一次切过去也不用等
  useEffect(() => { if (authed) prefetchAll(); }, [authed]);

  if (authed === null) return <div className="splash"><i /></div>;
  if (!authed) return <Login onDone={() => setAuthed(true)} />;

  const now = new Date();
  return (
    <>
      <div className="app">
        <header className="top">
          <span className="logo"><i />chunk</span>
          <span className="mono dim">{now.getMonth() + 1}.{String(now.getDate()).padStart(2, "0")} · {"日一二三四五六"[now.getDay()]}</span>
        </header>
        <main key={tab}>
          {tab === "today" && <Today demo={demo} onStart={() => setPracticing(true)} onLibrary={() => setTab("library")} />}
          {tab === "library" && <Library />}
          {tab === "wall" && <Wall onLibrary={() => setTab("library")} />}
        </main>
      </div>
      <nav className="tabs" aria-label="主导航">
        <span className="slider" style={{ transform: `translateX(${TABS.findIndex(t => t.id === tab) * 76}px)` }} />
        {TABS.map(t => <button key={t.id} aria-current={tab === t.id ? "page" : undefined} onClick={() => { setTab(t.id); window.scrollTo(0, 0); }}>{t.label}</button>)}
      </nav>
      {practicing && <Practice demo={demo} onExit={() => { setPracticing(false); refreshAll(); }} />}
    </>
  );
}

function Login({ onDone }: { onDone: () => void }) {
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr("");
    try {
      await api.login(password);
      onDone();
    } catch (x) {
      setErr(x instanceof ApiErr ? x.message : "登录失败");
    } finally {
      setBusy(false);
    }
  };
  return (
    <form className="login" onSubmit={submit}>
      <span className="logo"><i />chunk</span>
      <p style={{ color: "var(--ink-2)" }}>把句式和词块练到脱口而出。</p>
      <input type="password" autoComplete="current-password" placeholder="密码" value={password} onChange={e => setPassword(e.target.value)} aria-label="密码" />
      {err && <p className="err">{err}</p>}
      <button className="btn" disabled={busy || !password}>进入</button>
    </form>
  );
}
