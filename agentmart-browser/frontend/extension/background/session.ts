/** service worker 里的「购物会话记忆池」。
 *
 *  内容脚本上报指纹 → 这里维护池子 → 侧面板直接读 chrome.storage.session。
 *  池子存在 session 里而不是 background 的内存里：MV3 会随时把 service
 *  worker 回收，存内存的话用户切个标签回来池子就空了。
 *
 *  存的全是纯 JSON 元数据（标题/价格文本/店铺名/优惠文案/型号 token），
 *  不存 DOM、不存 document.body 全文、不碰 cookie 和账号信息。
 */

import {
  activateTab,
  emptyPool,
  entryFromFields,
  looksLikeProductPage,
  removeTab,
  revivePool,
  upsertEntry,
  type SessionPool,
} from "../core/session.ts";
import type { PageFingerprintMessage } from "../protocol.ts";

export const SESSION_POOL_KEY = "agentmart.sessionPool";

/** 串起所有写操作的 Promise 链。
 *
 *  storage.session 的读写是异步的，而标签页关闭、切换、内容脚本上报会在几毫秒
 *  内接连触发。若各自「读-改-写」，后写的会盖掉前一份的结果 —— 用户连关两个
 *  标签页时第二个就可能关不掉。串成一条链就没有这个窗口。 */
let writeChain: Promise<unknown> = Promise.resolve();

function load(): Promise<SessionPool> {
  return chrome.storage.session
    .get(SESSION_POOL_KEY)
    .then((store) => revivePool(store[SESSION_POOL_KEY]))
    .catch(() => emptyPool());
}

/** 读-改-写一气做完。存不进去不抛：池子是体验增强，不是功能前提。 */
function update(change: (pool: SessionPool) => SessionPool): Promise<SessionPool> {
  const task = writeChain.then(async () => {
    const pool = await load();
    const next = change(pool);
    try {
      await chrome.storage.session.set({ [SESSION_POOL_KEY]: next });
    } catch {
      /* 存储配额或异常：内存里的 next 照常返回，只是下次启动要从头再来 */
    }
    return next;
  });
  // 链上任何一个环节失败都不能把后面全堵死
  writeChain = task.catch(() => undefined);
  return task;
}

/** 内容脚本上报上来的指纹。 */
export function handleFingerprint(
  message: PageFingerprintMessage,
  tabId: number | undefined,
): Promise<void> {
  if (tabId === undefined) return Promise.resolve();
  const fields = message.fields;
  if (!fields || typeof fields.url !== "string") return Promise.resolve();

  // 不是商品页：把这个标签页从池子里拿掉。
  // 用户从商品页跳到搜索页时，侧边栏不该继续挂着那个已经不存在的商品。
  if (!message.isProduct || !looksLikeProductPage(fields.url, fields)) {
    return update((pool) => removeTab(pool, tabId)).then(() => undefined);
  }
  const entry = entryFromFields(tabId, fields, Date.now());
  if (entry === null) {
    return update((pool) => removeTab(pool, tabId)).then(() => undefined);
  }
  return update((pool) => upsertEntry(pool, entry)).then(() => undefined);
}

/** 标签页关了就把它从池子里拿掉。DoD 要求 200ms 内干净消失、不留残影。
 *  返回 Promise 是为了让调用方（测试、或别的编排代码）能等它写完。 */
export function onTabRemoved(tabId: number): Promise<SessionPool> {
  return update((pool) => removeTab(pool, tabId));
}

/** 切到某个标签页：标成「当前」，并更新它的活跃时间。 */
export function onTabActivated(activeInfo: { tabId: number }): Promise<SessionPool> {
  return update((pool) => activateTab(pool, activeInfo.tabId, Date.now()));
}

/** service worker 醒来时把「当前」标记清掉。
 *
 *  没有 tabs 权限就查不到现在活动的是哪个标签页，硬留着一个旧 tabId 会让
 *  侧边栏把已经不在前台的页面标成「(当前)」。onActivated 会在用户切换时补上。 */
export function clearActiveOnStartup(): Promise<SessionPool> {
  return update((pool) => (pool.activeTabId === null ? pool : { ...pool, activeTabId: null }));
}
