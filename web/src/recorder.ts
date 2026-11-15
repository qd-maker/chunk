// 录音：点一下开始，再点一下结束。录的时候把音量切成一排小方块的高度。
import { useCallback, useEffect, useRef, useState } from "react";

export const BARS = 28;
type Phase = "idle" | "recording";

function pickMime(): string {
  const want = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"];
  return want.find(m => typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported(m)) ?? "";
}

export function micErrorMessage(e: unknown): string {
  const err = e as { name?: string; message?: string };
  if (err.name === "NotAllowedError") return "麦克风权限被拒绝。在浏览器或系统设置里允许本站使用麦克风，再回来重试。";
  if (err.name === "NotFoundError" || err.name === "OverconstrainedError") return "找不到麦克风。";
  if (err.name === "NotReadableError" || err.name === "AbortError") return "麦克风被别的应用占着，关掉后再试。";
  return err.message || "打不开麦克风。";
}

/** 屏幕常亮：active 期间申请 wakeLock，不支持就算了；切到后台会被系统收回，回到前台还 active 就再申请一次。 */
export function useWakeLock(active: boolean) {
  useEffect(() => {
    if (!active || !("wakeLock" in navigator)) return;
    let lock: WakeLockSentinel | null = null;
    let alive = true;
    const grab = () => {
      if (document.visibilityState !== "visible") return;
      navigator.wakeLock.request("screen").then(l => { if (alive) lock = l; else void l.release(); }).catch(() => {});
    };
    const onVis = () => { if (document.visibilityState === "visible" && (!lock || lock.released)) grab(); };
    grab();
    document.addEventListener("visibilitychange", onVis);
    return () => {
      alive = false;
      document.removeEventListener("visibilitychange", onVis);
      void lock?.release().catch(() => {});
    };
  }, [active]);
}

/** demo = true（假上游）时，拿不到麦克风也能走完流程：音量用假的，录音是一小段空数据。 */
export function useRecorder(demo: boolean) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [levels, setLevels] = useState<number[]>(() => Array(BARS).fill(0));
  const [seconds, setSeconds] = useState(0);
  const ref = useRef<{ stream?: MediaStream; rec?: MediaRecorder; ctx?: AudioContext; raf?: number; timer?: number; chunks: Blob[]; t0: number }>({ chunks: [], t0: 0 });

  const cleanup = useCallback(() => {
    const r = ref.current;
    if (r.raf) cancelAnimationFrame(r.raf);
    if (r.timer) clearInterval(r.timer);
    r.stream?.getTracks().forEach(t => t.stop());
    r.ctx?.close().catch(() => {});
    ref.current = { chunks: [], t0: 0 };
  }, []);
  useEffect(() => cleanup, [cleanup]);

  const start = useCallback(async () => {
    const r = ref.current;
    r.chunks = [];
    r.t0 = performance.now();
    setSeconds(0);
    setLevels(Array(BARS).fill(0));
    let analyser: AnalyserNode | null = null;
    try {
      if (!navigator.mediaDevices?.getUserMedia) throw new Error("这个浏览器不能录音：需要 https 页面，推荐 Chrome、Edge 或 Safari。");
      r.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
      const mime = pickMime();
      r.rec = new MediaRecorder(r.stream, mime ? { mimeType: mime } : undefined);
      r.rec.ondataavailable = e => { if (e.data.size) r.chunks.push(e.data); };
      r.rec.start(250);
      r.ctx = new AudioContext();
      analyser = r.ctx.createAnalyser();
      analyser.fftSize = 512;
      r.ctx.createMediaStreamSource(r.stream).connect(analyser);
    } catch (e) {
      cleanup();
      if (!demo) throw e;
      ref.current.t0 = performance.now();
    }
    const buf = new Uint8Array(512);
    let last = 0;
    const tick = (t: number) => {
      if (t - last > 70) {
        last = t;
        let v: number;
        if (analyser) {
          analyser.getByteTimeDomainData(buf);
          let sum = 0;
          for (const x of buf) { const y = (x - 128) / 128; sum += y * y; }
          v = Math.min(1, Math.sqrt(sum / buf.length) * 5);
        } else {
          v = 0.25 + 0.55 * Math.abs(Math.sin(t / 190) * Math.sin(t / 67));
        }
        setLevels(prev => [...prev.slice(1), v]);
      }
      ref.current.raf = requestAnimationFrame(tick);
    };
    ref.current.raf = requestAnimationFrame(tick);
    ref.current.timer = window.setInterval(() => setSeconds(Math.floor((performance.now() - ref.current.t0) / 1000)), 250);
    setPhase("recording");
  }, [cleanup, demo]);

  const stop = useCallback(async (): Promise<Blob> => {
    const r = ref.current;
    const rec = r.rec;
    let blob: Blob;
    if (rec && rec.state !== "inactive") {
      blob = await new Promise<Blob>(resolve => {
        rec.onstop = () => resolve(new Blob(r.chunks, { type: rec.mimeType || "audio/webm" }));
        rec.stop();
      });
    } else {
      blob = new Blob([new Uint8Array(64)], { type: "audio/webm" });
    }
    cleanup();
    setPhase("idle");
    return blob;
  }, [cleanup]);

  const cancel = useCallback(() => { cleanup(); setPhase("idle"); }, [cleanup]);

  return { phase, levels, seconds, start, stop, cancel };
}
