/** 跨标签页「购物会话记忆池」的纯逻辑。
 *
 *  用户在同一款商品的好几个平台标签页之间来回切，不应该每切一次就手点一次
 *  「读取」。所以每个商品页自己上报一份指纹，这里负责把它们归成「同款组」，
 *  并记住哪个标签页是当前活动的那个。
 *
 *  三条边界写死在实现里：
 *  1. 只存纯 JSON 元数据（标题/价格文本/店铺名/优惠文案），不存 DOM、
 *     不存 document.body 全文、不存任何账号或 cookie 信息；
 *  2. 认不出同款就单独成组，绝不为凑一个对比表把两件不同的商品排在一起；
 *  3. 这里不碰 chrome.*、不碰 DOM，因此既能在 service worker 里跑，也能在
 *     侧面板里跑，还能在 Node 里直接跑单元测试。
 */

import { PLATFORM_LABELS, type Platform } from "./enums.ts";
import { parseMoney } from "./money.ts";
import type { PageFields } from "./offer.ts";
import { platformFromUrl } from "./platforms.ts";
import { modelTokens, sharedModelTokens } from "./modelTokens.ts";

/** 池子里最多留几个标签页。超出就丢最早不活跃的那个 —— 侧边栏只摆得下这么多。 */
export const MAX_SESSION_TABS = 24;

/** 链接长得像商品详情页。和 content/extractPage.ts 的 extractProductLinks 同规则。 */
const PRODUCT_URL_RE = /item\.|\/product[./]|\/detail\/|\/goods\/|\/sku\/|id=\d{4,}|\/p\/|haohuo\./;

/** 标题至少这么长才当它是商品名，避免把「购物车」「我的订单」当成商品页。 */
const MIN_TITLE_LENGTH = 6;

/** 一个标签页上报上来的商品页指纹。 */
export interface SessionEntry {
  tabId: number;
  platform: Platform;
  url: string;
  title: string;
  /** 页面上的价格原文。可能是 null —— 页面没写价格时不猜。 */
  priceText: string | null;
  shopName: string | null;
  /** 从标题+规格里挑出来的型号 token，同款归组唯一依据。 */
  modelTokens: string[];
  /** 这个条目是什么时候进池子的。定组身份用，激活标签页不会改它。 */
  firstSeenAt: number;
  /** 最近一次活跃（打开/切入/刷新）的时间。排序和淘汰用。 */
  lastActiveAt: number;
  /** 页面字段原文，供侧面板本地 buildOffer。纯 JSON，不含 DOM。 */
  fields: PageFields | null;
}

/** 同款组。tabs 用 tabId 做键 —— 每个标签页在池子里只出现一次。 */
export interface ProductCluster {
  clusterId: string;
  /** 组内最早加入的那个条目的型号 token，就是这一组的「身份」。
   *  后来加入的条目只跟它比，不跟组内其他成员比 —— 否则会传递漂移：
   *  A 和 B 同款、B 和 C 同款，推不出 A 和 C 同款。 */
  anchorTokens: string[];
  tabs: Record<number, SessionEntry>;
}

export interface SessionPool {
  version: 1;
  /** 当前活动的标签页。侧边栏据此标「(当前)」。 */
  activeTabId: number | null;
  clusters: ProductCluster[];
}

export function emptyPool(): SessionPool {
  return { version: 1, activeTabId: null, clusters: [] };
}

/** 这个地址+字段看起来是不是商品详情页。
 *
 *  认不出来就当「不是」：平台搜索页、活动页、购物车都不进池子，
 *  免得侧边栏摆一堆没用的标签。 */
export function looksLikeProductPage(url: string, fields: PageFields | null): boolean {
  if (typeof url !== "string" || !/^https?:/.test(url)) return false;
  if (platformFromUrl(url) === null) return false;
  const title = (fields?.title ?? "").trim();
  if (Array.from(title).length < MIN_TITLE_LENGTH) return false;
  // 价格抽到了，或者链接本身长得像商品页 —— 两条满足一条就算。
  // 京东有些品类页价格要登录后才渲染，不能因为没抽到价格就整页丢掉。
  return parseMoney(fields?.priceText ?? null) !== null || PRODUCT_URL_RE.test(url);
}

/** 把内容脚本抽到的字段变成池子里的条目。 */
export function entryFromFields(
  tabId: number,
  fields: PageFields,
  at: number,
): SessionEntry | null {
  const url = (fields.url ?? "").trim();
  const platform = platformFromUrl(url);
  if (platform === null) return null;
  return {
    tabId,
    platform,
    url,
    title: (fields.title ?? "").trim() || url,
    priceText: (fields.priceText ?? "").trim() || null,
    shopName: (fields.shopName ?? "").trim() || null,
    modelTokens: modelTokens(`${fields.title ?? ""} ${fields.skuText ?? ""}`),
    firstSeenAt: at,
    lastActiveAt: at,
    fields,
  };
}

/** 组内条目按最近活跃排序。池子用 tabId 做键，JSON 往返后数字键会变成
 *  字符串，排序不能依赖对象键序，必须显式比时间。 */
export function sortedTabs(cluster: ProductCluster): SessionEntry[] {
  return Object.values(cluster.tabs).sort((a, b) => b.lastActiveAt - a.lastActiveAt);
}

/** 摊平整个池子：先按组，组内按最近活跃。 */
export function poolTabs(pool: SessionPool): SessionEntry[] {
  const out: SessionEntry[] = [];
  for (const cluster of pool.clusters) out.push(...sortedTabs(cluster));
  return out;
}

/** 重新分组。
 *
 *  按进池子的先后处理：每个条目去找第一个「锚点 token 有交集」的组，找不到
 *  就自己当新组的锚点。排序用 firstSeenAt 而不是 lastActiveAt —— 后者会被
 *  「用户切回旧标签页」改写，锚点跟着变，同一组商品的身份就飘了：先打开
 *  XM5、再打开「XM5 与 XM4 对比」、最后打开 XM4，用户切回第一个标签页时
 *  三个页面会并成一组，而它们并不是同一款。 */
function recluster(entries: SessionEntry[]): ProductCluster[] {
  const ordered = [...entries].sort((a, b) => a.firstSeenAt - b.firstSeenAt);
  const clusters: ProductCluster[] = [];
  for (const entry of ordered) {
    // 认不出型号的条目一律自己一组：它跟谁都不算同款，不能因为「都没认出」
    // 就把两件不同的商品归到一起。
    if (entry.modelTokens.length === 0) {
      clusters.push(newCluster(entry, []));
      continue;
    }
    const host = clusters.find(
      (cluster) => sharedModelTokens(cluster.anchorTokens, entry.modelTokens).length > 0,
    );
    if (host) host.tabs[entry.tabId] = entry;
    else clusters.push(newCluster(entry, entry.modelTokens));
  }
  return clusters;
}

function newCluster(entry: SessionEntry, anchorTokens: string[]): ProductCluster {
  return {
    clusterId: clusterIdFor(anchorTokens, entry.tabId),
    anchorTokens,
    tabs: { [entry.tabId]: entry },
  };
}

/** 组的稳定标识。锚点 token 之间两两不相交（有交集就并组了），所以拼起来
 *  不会重名；认不出型号的用 tabId 兜底。 */
function clusterIdFor(anchorTokens: readonly string[], tabId: number): string {
  if (anchorTokens.length === 0) return `tab-${tabId}`;
  return anchorTokens
    .join("-")
    .toLowerCase()
    .replace(/[^a-z0-9\u4e00-\u9fa5]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

/** 超出容量时丢最早不活跃的，但正在写入的这个和当前活动的不丢。 */
function capEntries(entries: SessionEntry[], activeTabId: number | null): SessionEntry[] {
  if (entries.length <= MAX_SESSION_TABS) return entries;
  const keep = new Set(
    [...entries]
      .sort((a, b) => b.lastActiveAt - a.lastActiveAt)
      .slice(0, MAX_SESSION_TABS)
      .map((entry) => entry.tabId),
  );
  return entries.filter(
    (entry) => keep.has(entry.tabId) || entry.tabId === activeTabId,
  );
}

/** 新增/更新一个标签页的指纹，然后重新分组。 */
export function upsertEntry(pool: SessionPool, entry: SessionEntry): SessionPool {
  const rest = poolTabs(pool).filter((item) => item.tabId !== entry.tabId);
  const entries = capEntries([...rest, entry], pool.activeTabId);
  return {
    version: 1,
    activeTabId: pool.activeTabId,
    clusters: recluster(entries),
  };
}

/** 标签页关了就把它从池子里拿掉。 */
export function removeTab(pool: SessionPool, tabId: number): SessionPool {
  if (!poolTabs(pool).some((entry) => entry.tabId === tabId)) return pool;
  return {
    version: 1,
    activeTabId: pool.activeTabId === tabId ? null : pool.activeTabId,
    clusters: recluster(poolTabs(pool).filter((entry) => entry.tabId !== tabId)),
  };
}

/** 切到某个标签页：更新时间戳，并让它成为「当前」。
 *
 *  tabId 不在池子里也照记：等它自己的内容脚本上报指纹时，侧边栏才知道
 *  该把哪一项标成「(当前)」。 */
export function activateTab(pool: SessionPool, tabId: number, at: number): SessionPool {
  return {
    version: 1,
    activeTabId: tabId,
    clusters: recluster(
      poolTabs(pool).map((entry) =>
        entry.tabId === tabId ? { ...entry, lastActiveAt: at } : entry,
      ),
    ),
  };
}

/** 侧边栏指示条用的一行。每个标签页一项，当前活动的那项标出来。 */
export interface SessionTabView {
  tabId: number;
  clusterId: string;
  platform: Platform;
  platformLabel: string;
  url: string;
  title: string;
  isActive: boolean;
  lastActiveAt: number;
  hasPrice: boolean;
  /** 这一组的型号与组内其他页面只有部分重合 —— 展示时必须带上这句提醒。 */
  modelPartial: boolean;
}

/** 组的型号是否在成员之间只有部分重合。
 *
 *  比如组里同时有「WH-1000XM5」和「WH-1000XM5 与 XM4 对比」两个页面时，
 *  不能默默把它们当成同一款的两口价。判据是「成员的型号集合和锚点不一样」——
 *  用集合而不是「成员有没有锚点没有的 token」：后者查不出「锚点自己带了
 *  两个型号，成员各带一个」这种最危险的情况。 */
export function clusterModelPartial(cluster: ProductCluster): boolean {
  if (cluster.anchorTokens.length === 0) return false;
  const anchor = new Set(cluster.anchorTokens);
  return sortedTabs(cluster).some((entry) => {
    const tokens = new Set(entry.modelTokens);
    if (tokens.size !== anchor.size) return true;
    for (const token of tokens) {
      if (!anchor.has(token)) return true;
    }
    return false;
  });
}

export function poolTabViews(pool: SessionPool): SessionTabView[] {
  return poolTabs(pool).map((entry) => {
    const cluster = pool.clusters.find((item) => item.tabs[entry.tabId] !== undefined);
    return {
      tabId: entry.tabId,
      clusterId: cluster?.clusterId ?? "",
      platform: entry.platform,
      platformLabel: PLATFORM_LABELS[entry.platform],
      url: entry.url,
      title: entry.title,
      isActive: pool.activeTabId === entry.tabId,
      lastActiveAt: entry.lastActiveAt,
      hasPrice: parseMoney(entry.priceText) !== null,
      modelPartial: cluster ? clusterModelPartial(cluster) : false,
    };
  });
}

/** 池子里有几个标签页、分了几组。 */
export function poolCounts(pool: SessionPool): { tabs: number; clusters: number } {
  return { tabs: poolTabs(pool).length, clusters: pool.clusters.length };
}

function isPlatform(value: unknown): value is Platform {
  return typeof value === "string" && value in PLATFORM_LABELS;
}

function str(value: unknown): string {
  return typeof value === "string" ? value : "";
}

/** 从 chrome.storage.session 里读回来的值复原成池子。
 *
 *  JSON 往返会把 Record<number, …> 的键变成字符串，也可能会读到旧版本或
 *  被写坏的数据 —— 一律按「空池」处理，不让脏数据带着走。 */
export function revivePool(raw: unknown): SessionPool {
  if (!raw || typeof raw !== "object") return emptyPool();
  const value = raw as Partial<SessionPool>;
  if (value.version !== 1 || !Array.isArray(value.clusters)) return emptyPool();
  const entries: SessionEntry[] = [];
  for (const cluster of value.clusters) {
    if (!cluster || typeof cluster !== "object") continue;
    // 锚点不读存储里的值：recluster 会按同样规则重算，读旧值反而会和
    // 重算结果打架。这里只负责把条目捞回来。
    const tabs = (cluster.tabs ?? {}) as Record<string, unknown>;
    for (const [key, rawEntry] of Object.entries(tabs)) {
      const tabId = Number(key);
      if (!Number.isInteger(tabId) || !rawEntry || typeof rawEntry !== "object") continue;
      const item = rawEntry as Partial<SessionEntry>;
      const url = str(item.url);
      if (!isPlatform(item.platform) || !/^https?:/.test(url)) continue;
      entries.push({
        tabId,
        platform: item.platform,
        url,
        title: str(item.title) || url,
        priceText: typeof item.priceText === "string" ? item.priceText : null,
        shopName: typeof item.shopName === "string" ? item.shopName : null,
        modelTokens: Array.isArray(item.modelTokens)
          ? item.modelTokens.filter((token): token is string => typeof token === "string")
          : [],
        firstSeenAt: typeof item.firstSeenAt === "number" ? item.firstSeenAt : 0,
        lastActiveAt: typeof item.lastActiveAt === "number" ? item.lastActiveAt : 0,
        fields:
          item.fields && typeof item.fields === "object" ? (item.fields as PageFields) : null,
      });
    }
  }
  const activeTabId =
    typeof value.activeTabId === "number" && Number.isInteger(value.activeTabId)
      ? value.activeTabId
      : null;
  return {
    version: 1,
    activeTabId: entries.some((entry) => entry.tabId === activeTabId) ? activeTabId : null,
    clusters: recluster(entries),
  };
}
