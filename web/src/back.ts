// 安卓返回键：APK 里返回键 = history.back()，没有历史就退出应用。
// 练习页、弹层打开时各压一条历史；按返回关掉最上面那层；用界面按钮关时自己把那条历史退掉，历史栈不越堆越多。
import { useEffect, useRef } from "react";

type Layer = { onBack: () => boolean };   // onBack 返回 true = 这次返回被吃掉了，层继续开着（比如先取消录音）
const stack: Layer[] = [];
let skip = 0;   // 自己调 history.back() 引起的 popstate 次数，收到时忽略

if (typeof window !== "undefined") {
  window.addEventListener("popstate", () => {
    if (skip > 0) { skip -= 1; return; }
    const top = stack.pop();
    if (!top) return;
    if (top.onBack()) {             // 吃掉了：层放回去，那条历史也补回去
      stack.push(top);
      history.pushState({ chunkLayer: true }, "");
    }
  });
}

/** 组件挂着时占一条历史；按返回会调 onBack，返回 false 时由 onBack 自己把组件关掉。 */
export function useBackLayer(onBack: () => boolean) {
  const ref = useRef(onBack);
  ref.current = onBack;
  useEffect(() => {
    const layer: Layer = { onBack: () => ref.current() };
    stack.push(layer);
    history.pushState({ chunkLayer: true }, "");
    return () => {
      const i = stack.indexOf(layer);
      if (i < 0) return;            // 已经被返回键关掉了，历史也已经退过
      stack.splice(i, 1);
      skip += 1;
      history.back();               // 按钮关的：把自己那条历史退掉
    };
  }, []);
}
