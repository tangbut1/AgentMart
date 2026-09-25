/** MV3 service worker：开标签页、等加载、跑只读抽取、关标签页。
 *
 *  边界（与整个项目的边界一致，这里再钉一次）：
 *  - 只读。不点按钮、不提交表单、不领券、不加购、不下单、不改页面；
 *  - 不读 cookie、不读账号信息、不读输入框内容；
 *  - 不破解验证码、不伪装身份、不绕过风控。遇到登录墙/验证码就停下来
 *    告诉用户「请您在这个标签页里自己处理」，然后由用户重新触发；
 *  - 每个平台串行打开、每次只开少量页面，两次加载之间留间隔，
 *    保持人的节奏，不做高频抓取。
 */

import {
  buildOffer,
  computePriceBreakdown,
  offerView,
  platformFromUrl,
  recipeFor,
  searchUrl,
} from "../core/index.ts";
import { extractProductLinks, extractProductPage } from "../content/extractPage.ts";
import type {
  CompareRequest,
  CompareResponse,
  ExtensionRequest,
  ExtensionResponse,
  ReadPageRequest,
  ReadPageResponse,
} from "../protocol.ts";

/** 两次页面加载之间的间隔。保持人的节奏，不做高频抓取。 */
const PAGE_PAUSE_MS = 1200;
/** 等一个标签页加载完成的最长时间 */
const LOAD_TIMEOUT_MS = 20000;
/** 每个平台最多打开几个商品页 */
const MAX_PRODUCTS_PER_PLATFORM = 2;

// MV3 里拿「当前标签页」只有这一个入口，包一层是为了别处复用同一个语义
const queryTabs = chrome.tabs.query;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function activeTab(): Promise<chrome.tabs.Tab | null> {
  const tabs = await queryTabs({ active: true, currentWindow: true });
  return tabs[0] ?? null;
}

function waitForTabComplete(tabId: number, timeoutMs: number): Promise<boolean> {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (value: boolean): void => {
      if (settled) return;
      settled = true;
      chrome.tabs.onUpdated.removeListener(listener);
      window.clearTimeout(timer);
      resolve(value);
    };
    const listener = (id: number, info: chrome.tabs.TabChangeInfo): void => {
      if (id === tabId && info.status === "complete") finish(true);
    };
    const timer = window.setTimeout(() => finish(false), timeoutMs);
    chrome.tabs.onUpdated.addListener(listener);
    void chrome.tabs.get(tabId).then((tab) => {
      if (tab && tab.status === "complete") finish(true);
    });
  });
}

/** 在指定标签页里跑只读抽取。抽不到就返回 null，不猜。 */
async function readFields(
  tabId: number,
): Promise<ReturnType<typeof extractProductPage> | null> {
  const [result] = await chrome.scripting.executeScript({
    target: { tabId },
    func: extractProductPage,
  });
  return (result?.result as ReturnType<typeof extractProductPage> | undefined) ?? null;
}

async function readLinks(tabId: number, maxLinks: number): Promise<string[]> {
  const [result] = await chrome.scripting.executeScript({
    target: { tabId },
    func: extractProductLinks,
    args: [maxLinks],
  });
  const links = (result?.result ?? []) as Array<{ url: string; title: string }>;
  return links.map((link) => link.url);
}

function closeTab(tabId: number | undefined): Promise<void> {
  if (tabId === undefined) return Promise.resolve();
  return chrome.tabs.remove(tabId).then(
    () => undefined,
    () => undefined,
  );
}

function describe(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}

function nowText(): string {
  const now = new Date();
  const pad = (value: number): string => String(value).padStart(2, "0");
  return (
    now.getFullYear() +
    "-" +
    pad(now.getMonth() + 1) +
    "-" +
    pad(now.getDate()) +
    " " +
    pad(now.getHours()) +
    ":" +
    pad(now.getMinutes()) +
    ":" +
    pad(now.getSeconds())
  );
}

async function handleReadPage(request: ReadPageRequest): Promise<ReadPageResponse> {
  const tab = request.tabId ? await chrome.tabs.get(request.tabId) : await activeTab();
  if (!tab || tab.id === undefined) {
    return { ok: false, reason: "找不到当前标签页" };
  }
  const url = tab.url ?? "";
  if (!/^https?:/.test(url)) {
    return { ok: false, reason: "这个页面不是 http(s) 商品页：" + (url || "空白页") };
  }
  const platform = platformFromUrl(url);
  if (platform === null) {
    return { ok: false, reason: "这个地址不在已支持的五个平台里，只读不猜" };
  }

  let fields: ReturnType<typeof extractProductPage> | null = null;
  try {
    fields = await readFields(tab.id);
  } catch (error) {
    return {
      ok: false,
      reason:
        "无法读取这个页面（" +
        describe(error) +
        "）。若是平台要求登录，请先在这个标签页里登录后重试。",
    };
  }
  if (!fields) {
    return { ok: false, reason: "页面里没有抽到任何字段，可能还没加载完，稍等一下重试" };
  }

  const built = buildOffer(platform, fields, {
    sourceLabel: "side-panel",
    fetchedAt: nowText(),
  });
  const breakdown = computePriceBreakdown({
    list_price: built.offer.list_price,
    shipping_fee: built.offer.shipping_fee,
    discounts: built.offer.discounts,
  });
  return {
    ok: true,
    url,
    platform,
    offer: offerView(built.offer, breakdown),
    problems: built.problems,
    fields,
  };
}

function decodeURIComponentSafe(url: string): string {
  try {
    return decodeURIComponent(url);
  } catch {
    return url;
  }
}

async function handleCompare(request: CompareRequest): Promise<CompareResponse> {
  const recipe = recipeFor(request.platform);
  const displayName = recipe.display_name;
  const problems: string[] = [];
  const offers: CompareResponse["offers"] = [];
  const primaryTokens = request.primaryTokens ?? [];
  const maxProducts = Math.max(1, Math.min(request.maxProducts ?? MAX_PRODUCTS_PER_PLATFORM, 3));

  if (recipe.notes.includes("暂不可用")) {
    return {
      ok: false,
      platform: request.platform,
      offers: [],
      problems: [displayName + "：" + recipe.notes],
    };
  }

  let searchTabId: number | undefined;
  try {
    const searchTab = await chrome.tabs.create({
      url: searchUrl(request.platform, request.keyword),
      active: false,
    });
    searchTabId = searchTab.id;
    if (searchTabId === undefined) throw new Error("打开搜索页失败");
    const loaded = await waitForTabComplete(searchTabId, LOAD_TIMEOUT_MS);
    if (!loaded) {
      problems.push(displayName + "：搜索页加载超时，已跳过");
      return { ok: false, platform: request.platform, offers: [], problems };
    }
    await sleep(PAGE_PAUSE_MS);

    const links = await readLinks(searchTabId, 24);
    if (links.length === 0) {
      problems.push(
        displayName +
          "：搜索页里没有找到商品链接。可能需要登录，请在浏览器里打开该平台登录后重试。",
      );
      return { ok: false, platform: request.platform, offers: [], problems };
    }

    // 只用链接文本挑同款；挑不出来就打开前几个让用户自己看，
    // 但必须说明「这几个没认成同款」。
    const matched: string[] = [];
    const rest: string[] = [];
    for (const link of links) {
      const text = decodeURIComponentSafe(link);
      const hit = primaryTokens.some((token) => text.includes(token));
      if (primaryTokens.length > 0 && hit) matched.push(link);
      else rest.push(link);
    }
    const chosen = [...matched, ...rest].slice(0, maxProducts);
    if (matched.length === 0) {
      problems.push(
        displayName +
          "：搜索结果里没有认出同款，下面给出的是前 " +
          chosen.length +
          " 个结果，请自行核对型号。",
      );
    }

    const opened: number[] = [];
    for (const link of chosen) {
      const tab = await chrome.tabs.create({ url: link, active: false });
      if (tab.id === undefined) continue;
      opened.push(tab.id);
      const done = await waitForTabComplete(tab.id, LOAD_TIMEOUT_MS);
      if (!done) {
        problems.push(displayName + "：商品页加载超时，已跳过");
        continue;
      }
      await sleep(PAGE_PAUSE_MS);
      try {
        const fields = await readFields(tab.id);
        if (!fields) continue;
        const built = buildOffer(request.platform, fields, {
          sourceLabel: "side-panel",
          fetchedAt: nowText(),
        });
        if (built.problems.length > 0) problems.push(...built.problems);
        const breakdown = computePriceBreakdown({
          list_price: built.offer.list_price,
          shipping_fee: built.offer.shipping_fee,
          discounts: built.offer.discounts,
        });
        offers.push(offerView(built.offer, breakdown));
      } catch (error) {
        problems.push(displayName + "：读取商品页失败（" + describe(error) + "）");
      }
    }
    for (const id of opened) {
      await closeTab(id);
    }
    if (offers.length === 0) {
      problems.push(displayName + "：没有读到可用的商品页");
      return { ok: false, platform: request.platform, offers: [], problems };
    }
    return { ok: true, platform: request.platform, offers, problems };
  } catch (error) {
    return {
      ok: false,
      platform: request.platform,
      offers: [],
      problems: [displayName + "：" + describe(error)],
    };
  } finally {
    await closeTab(searchTabId);
  }
}

chrome.runtime.onMessage.addListener(
  (message: ExtensionRequest, _sender, sendResponse): boolean => {
    void (async (): Promise<void> => {
      let response: ExtensionResponse;
      switch (message.type) {
        case "ping":
          response = { ok: true, pong: true };
          break;
        case "read-page":
          response = await handleReadPage(message);
          break;
        case "compare-platform":
          response = await handleCompare(message);
          break;
        default:
          response = { ok: false, reason: "未知消息" } as ReadPageResponse;
      }
      sendResponse(response);
    })();
    return true;
  },
);

// 点工具栏图标直接开侧边栏，不用用户去菜单里找
void chrome.sidePanel
  .setPanelBehavior({ openPanelOnActionClick: true })
  .catch(() => undefined);
