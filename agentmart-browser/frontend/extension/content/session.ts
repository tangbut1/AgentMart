/** 常驻内容脚本：把商品页的轻量指纹报给 service worker。
 *
 *  用户在几个平台的同款商品页之间来回切，不应该每切一次就手点一次「读取」。
 *  所以这里在商品页加载完（以及 SPA 换页）时抽一份指纹发上去，由
 *  background 维护「购物会话记忆池」，侧边栏直接读池子展示。
 *
 *  边界（和 content/extractPage.ts 一样写死在实现里）：
 *  - 只读。不点任何按钮、不提交表单、不领券、不下单；
 *  - 不读输入框内容、不读 cookie、不读任何账号信息；
 *  - 不修改页面 DOM；
 *  - 不轮询。只在导航和标题变化时各抽一次，页面挂着不动就不打扰它。
 *
 *  这个文件会被单独打包成 classic script（见 scripts/build-extension.mjs），
 *  所以可以引用同目录的模块，不需要像 executeScript 注入那样自包含。
 */

import { extractProductPage } from "./extractPage.ts";
import { looksLikeProductPage } from "../core/session.ts";
import type { PageFields } from "../core/offer.ts";

/** 报一次之后多久内不重复报。SPA 连续换页时避免刷屏。 */
const REPOST_COOLDOWN_MS = 700;

/** 页面标题变化也可能意味着换了商品（有些平台换品不改 URL）。 */
const TITLE_OBSERVER_CONFIG: MutationObserverInit = {
  childList: true,
  subtree: true,
  characterData: true,
};

function post(message: unknown): void {
  // 收不到人不报错：扩展重载后旧内容脚本会留在已打开的页面里，
  // 这时候没有接收方是正常的，等下一次导航就接上了。
  void chrome.runtime.sendMessage(message).catch(() => undefined);
}

function report(fields: PageFields, reason: string): void {
  const isProduct = looksLikeProductPage(fields.url, fields);
  post({ type: "page-fingerprint", reason, isProduct, fields });
}

/** 标记已经打过补丁，避免内容脚本被注入两次时把 history 包两层。 */
const PATCHED = "__agentmartSessionPatched";

function patchHistory(onNavigate: () => void): void {
  const marker = (history as unknown as Record<string, unknown>)[PATCHED];
  if (marker === true) return;
  for (const method of ["pushState", "replaceState"] as const) {
    const original = history[method];
    if (typeof original !== "function") continue;
    try {
      history[method] = function patched(
        this: History,
        ...args: Parameters<typeof original>
      ): ReturnType<typeof original> {
        // 原方法照原样跑完，返回值原样返回 —— 只在其后通知一下，不改变页面行为
        const result = original.apply(this, args);
        onNavigate();
        return result;
      } as History[typeof method];
    } catch {
      // 个别页面把 history 设成不可写：那就不监听 SPA 换页，
      // 首屏和 popstate 仍然有效，不因此报错
      return;
    }
  }
  (history as unknown as Record<string, unknown>)[PATCHED] = true;
}

function install(): void {
  let lastUrl = location.href;
  let lastPostedAt = 0;

  const once = (reason: "load" | "history" | "popstate" | "title"): void => {
    const now = Date.now();
    if (now - lastPostedAt < REPOST_COOLDOWN_MS) return;
    lastPostedAt = now;
    let fields: PageFields;
    try {
      fields = extractProductPage();
    } catch {
      // 页面结构抽不动就算了，不猜也不报错
      return;
    }
    report(fields, reason);
  };

  /** 地址变了才抽。换页后 DOM 还没更新，等一帧。 */
  const onMaybeNavigate = (): void => {
    if (location.href === lastUrl) return;
    lastUrl = location.href;
    window.setTimeout(() => once("history"), 0);
  };

  // 1) 首次加载。document_idle 时 DOM 基本就绪，价格多数已经渲染。
  once("load");

  // 2) SPA 换页：淘宝/抖音详情页切换商品时不重新加载文档。
  patchHistory(onMaybeNavigate);

  window.addEventListener("popstate", onMaybeNavigate);

  // 3) 有些平台换规格/换品只改标题不改地址。看 <title> 就够，
  //    不用 MutationObserver 盯整页 —— 那在商品页上太吵。
  const titleElement = document.querySelector("title");
  if (titleElement) {
    let lastTitle = document.title;
    new MutationObserver(() => {
      if (document.title === lastTitle) return;
      lastTitle = document.title;
      window.setTimeout(() => once("title"), 0);
    }).observe(titleElement, TITLE_OBSERVER_CONFIG);
  }
}

install();
