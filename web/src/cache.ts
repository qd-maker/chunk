// 很小的数据缓存：有缓存先拿来渲染，同时后台重新请求，回来后悄悄换上。只有第一次完全没数据才显示骨架。
import { useCallback, useEffect, useSyncExternalStore } from "react";
import { api, ApiErr, type Answer, type Item, type Library, type Today, type Wall } from "./api";

type Entry = { data?: unknown; error?: string };
const store = new Map<string, Entry>();
const fetchers = new Map<string, () => Promise<unknown>>();
const inflight = new Map<string, Promise<void>>();
const gen = new Map<string, number>();       // 每个 key 的请求代数：旧请求晚回来就丢掉
const mounted = new Map<string, number>();   // 每个 key 现在有几个页面在用
const subs = new Set<() => void>();
let epoch = 0;                               // 清缓存（401）时 +1，之前发出的请求全部作废

const emit = () => subs.forEach(f => f());
const put = (key: string, e: Entry) => { store.set(key, e); emit(); };

/** 重新请求一个 key。force = 有改动刚发生，哪怕已有请求在路上也要再发一次新的。 */
export function revalidate(key: string, force = false): Promise<void> {
  const fetcher = fetchers.get(key);
  if (!fetcher) return Promise.resolve();
  const running = inflight.get(key);
  if (running && !force) return running;
  const g = (gen.get(key) ?? 0) + 1;
  gen.set(key, g);
  const ep = epoch;
  const p = fetcher().then(
    data => { if (ep === epoch && gen.get(key) === g) put(key, { data }); },
    e => {
      if (ep !== epoch || gen.get(key) !== g) return;
      // 有旧数据就继续用旧的，不打扰；没有才把错误露出来
      const old = store.get(key);
      put(key, { data: old?.data, error: old?.data === undefined ? (e instanceof ApiErr ? e.message : "加载失败") : undefined });
    },
  ).finally(() => { if (inflight.get(key) === p) inflight.delete(key); });
  inflight.set(key, p);
  return p;
}

export function register<T>(key: string, fetcher: () => Promise<T>) { if (!fetchers.has(key)) fetchers.set(key, fetcher); }

/** 有改动后调用：页面正在显示的立刻重拉；没在显示的等下次打开时再拉（打开时总会重拉一次）。 */
export function invalidate(keys: string[], eager = false) {
  keys.forEach(k => { if (eager || (mounted.get(k) ?? 0) > 0) void revalidate(k, true); });
}

export function peek<T>(key: string): T | undefined { return store.get(key)?.data as T | undefined; }

/** 直接改缓存里的数据（比如把刚激活的那条换成新状态），不发请求。 */
export function patch<T>(key: string, fn: (old: T) => T) {
  const old = store.get(key);
  if (old?.data !== undefined) put(key, { data: fn(old.data as T) });
}

export function clearCache() {
  epoch += 1;
  store.clear();
  inflight.clear();
  emit();
}

const subscribe = (f: () => void) => { subs.add(f); return () => { subs.delete(f); }; };

export function useCached<T>(key: string, fetcher: () => Promise<T>): { data: T | undefined; error: string; reload: () => void } {
  register(key, fetcher);
  const entry = useSyncExternalStore(subscribe, () => store.get(key));
  useEffect(() => {
    mounted.set(key, (mounted.get(key) ?? 0) + 1);
    void revalidate(key);   // 每次打开都后台刷新一次
    return () => { mounted.set(key, (mounted.get(key) ?? 1) - 1); };
  }, [key]);
  const reload = useCallback(() => { void revalidate(key, true); }, [key]);
  return { data: entry?.data as T | undefined, error: entry?.error ?? "", reload };
}

// ---- 三个主页面的数据 ----
export const K = { today: "today", library: "library", wall: "wall" } as const;
const ALL = [K.today, K.library, K.wall];
register(K.today, api.today);
register(K.library, api.library);
register(K.wall, api.wall);

export const useToday = () => useCached<Today>(K.today, api.today);
export const useLibrary = () => useCached<Library>(K.library, api.library);
export const useWall = () => useCached<Wall>(K.wall, api.wall);

/** 登录后预取，第一次切过去也不用等。 */
export function prefetchAll() { ALL.forEach(k => void revalidate(k)); }

/** 练完回首页：三页全部重拉。 */
export function refreshAll() { invalidate(ALL, true); }

/** 在缓存里找一条表达，打开详情弹层时先拿它顶上。 */
export function peekItem(id: string): Item | undefined {
  return peek<Library>(K.library)?.items.find(i => i.id === id) ?? peek<Wall>(K.wall)?.bricks.find(i => i.id === id);
}

/** 把一条表达的新状态写进库和墙的缓存；removed = 删掉了。 */
function patchItem(item: Item | null, removedId?: string) {
  const id = item?.id ?? removedId;
  patch<Library>(K.library, lib => {
    const old = lib.items.find(i => i.id === id);
    const items = removedId ? lib.items.filter(i => i.id !== removedId) : old ? lib.items.map(i => (i.id === id ? item! : i)) : [item!, ...lib.items];
    // 话题的「已激活」小格和今天剩余名额也跟着改，不用等重拉
    const wasLive = !!old && old.status !== "library", isLive = !!item && item.status !== "library";
    const topics = old?.topic_no == null || wasLive === isLive ? lib.topics
      : lib.topics.map(t => (t.no === old.topic_no ? { ...t, active: t.active + (isLive ? 1 : -1) } : t));
    const activated = !!old && old.status === "library" && isLive;
    return { ...lib, items, topics, new_left: activated ? Math.max(0, lib.new_left - 1) : lib.new_left };
  });
  patch<Wall>(K.wall, w => ({
    ...w, bricks: removedId ? w.bricks.filter(b => b.id !== removedId) : w.bricks.map(b => (b.id === id ? item! : b)),
  }));
}

/** 激活、暂停、恢复、删除、新建纠错之后：先改缓存，再三页全部重拉。 */
export function afterItemChange(item: Item | null, removedId?: string) {
  patchItem(item, removedId);
  refreshAll();
}

/** 答题、改判之后：库和墙先就地改这一条，正在显示的页面（练习时首页在底下）立刻重拉。 */
export function afterAnswer(a: Answer) {
  patchItem(a.item);
  invalidate(ALL);
}
