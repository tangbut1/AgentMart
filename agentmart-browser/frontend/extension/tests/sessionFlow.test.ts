/** 会话池的端到端联通测试（不跑浏览器，用假的 chrome API 顶替）。
 *
 *  单元测试只能证明「纯逻辑对」，这一步要证明的是「接线通」：
 *  内容脚本上报的指纹能进池子、两个平台的同款能并成一组、侧边栏能把它变成
 *  可对比的 OfferView、关掉标签页池子真的会少一项。
 *
 *  chrome.storage.session 用一个内存 Map 顶替，读写都是异步的 —— 和真的一样，
 *  这样并发写入互相覆盖那类问题才会暴露出来。
 */

import assert from "node:assert/strict";
import { beforeEach, describe, it } from "node:test";

import type { PageFields } from "../core/offer.ts";
import type { PageFingerprintMessage } from "../protocol.ts";
import { autoCompareFromPool, buildCompareGroups, entryToOfferView } from "../core/index.ts";
import { poolTabViews, revivePool } from "../core/session.ts";
import type { OfferView } from "../../src/lib/browserApi.ts";

/** 内存版 chrome.storage.session。故意保留异步边界。 */
function installChromeStub(): void {
  const store = new Map<string, unknown>();
  const session = {
    get: async (keys: string | string[] | null): Promise<Record<string, unknown>> => {
      await Promise.resolve();
      const wanted = keys === null ? [...store.keys()] : Array.isArray(keys) ? keys : [keys];
      const out: Record<string, unknown> = {};
      for (const key of wanted) out[key] = store.get(key);
      return out;
    },
    set: async (items: Record<string, unknown>): Promise<void> => {
      await Promise.resolve();
      for (const [key, value] of Object.entries(items)) store.set(key, value);
    },
  };
  (globalThis as { chrome?: unknown }).chrome = {
    storage: { session },
    runtime: {},
    tabs: {},
  };
}

function fields(over: Partial<PageFields> = {}): PageFields {
  return {
    url: "https://item.jd.com/100012043978.html",
    title: "Apple iPhone 15 Pro 256GB 黑色",
    priceText: "2499.00",
    shopName: "Apple 产品京东自营旗舰店",
    selfOperatedHint: true,
    skuText: "256GB 黑色",
    couponTexts: [],
    policyTexts: [],
    ...over,
  };
}

function fingerprint(over: Partial<PageFields>, isProduct = true): PageFingerprintMessage {
  return { type: "page-fingerprint", reason: "load", isProduct, fields: fields(over) };
}

/** 每次测试都重新导入，拿到干净的 writeChain 和存储。 */
async function freshBackground(): Promise<typeof import("../background/session.ts")> {
  installChromeStub();
  return import(`../background/session.ts?case=${Math.random()}`);
}

describe("指纹 → 池子 → 侧边栏", () => {
  beforeEach(() => {
    installChromeStub();
  });

  it("两个平台的同款页面并成一组，侧边栏拿到两项", async () => {
    const bg = await freshBackground();
    await bg.handleFingerprint(fingerprint({}), 11);
    await bg.handleFingerprint(
      fingerprint({
        url: "https://item.taobao.com/item.htm?id=778899",
        title: "Apple iPhone 15 Pro 256GB 黑色",
        priceText: "2449.00",
        shopName: "Apple Store 官方旗舰店",
        selfOperatedHint: false,
      }),
      22,
    );
    const pool = await readPool(bg);
    const views = poolTabViews(pool);
    assert.equal(views.length, 2);
    assert.deepEqual(
      views.map((view) => view.platform).sort(),
      ["jd", "taobao"],
    );
    // 同一组：说明后台真的按型号认过同款
    assert.equal(new Set(views.map((view) => view.clusterId)).size, 1);
  });

  it("池子里的条目能变成 OfferView 并排比较", async () => {
    const bg = await freshBackground();
    await bg.handleFingerprint(fingerprint({}), 11);
    await bg.handleFingerprint(
      fingerprint({
        url: "https://item.taobao.com/item.htm?id=778899",
        title: "Apple iPhone 15 Pro 256GB 黑色",
        priceText: "2449.00",
        shopName: "Apple Store 官方旗舰店",
        selfOperatedHint: false,
      }),
      22,
    );
    const pool = await readPool(bg);
    const group = pool.clusters[0];
    const offers = Object.values(group.tabs)
      .map((entry) => entryToOfferView(entry, "江苏"))
      .filter((offer) => offer !== null);
    assert.equal(offers.length, 2);
    const compared = buildCompareGroups(offers[0], offers.slice(1));
    assert.equal(compared.groups.length, 1);
    assert.equal(compared.groups[0].offers.length, 2);
    assert.equal(compared.unmatched.length, 0, "同款不该被扔进未匹配列表");
    // 价格取自各自页面，不是编的。list_price 是「2499.00」这样的两位小数字符串
    const prices = compared.groups[0].offers.map((offer) => offer.list_price).sort();
    assert.deepEqual(prices, ["2449.00", "2499.00"]);
    assert.deepEqual(
      compared.groups[0].offers.map((offer) => offer.shop_name).sort(),
      ["Apple Store 官方旗舰店", "Apple 产品京东自营旗舰店"],
    );
  });

  it("不同型号的两页各自成组，不摆成一副能比的样子", async () => {
    const bg = await freshBackground();
    await bg.handleFingerprint(fingerprint({}), 11);
    await bg.handleFingerprint(
      fingerprint({
        url: "https://item.taobao.com/item.htm?id=778899",
        title: "华为 Mate 60 Pro 12GB+512GB 雅丹黑",
        priceText: "6499.00",
      }),
      22,
    );
    const views = poolTabViews(await readPool(bg));
    assert.equal(views.length, 2);
    assert.equal(new Set(views.map((view) => view.clusterId)).size, 2);
  });

  it("关掉标签页，池子里立刻就少一项", async () => {
    const bg = await freshBackground();
    await bg.handleFingerprint(fingerprint({}), 11);
    await bg.handleFingerprint(
      fingerprint({
        url: "https://item.taobao.com/item.htm?id=778899",
        title: "Apple iPhone 15 Pro 256GB 黑色",
        priceText: "2449.00",
      }),
      22,
    );
    await bg.onTabRemoved(22);
    const views = poolTabViews(await readPool(bg));
    assert.deepEqual(
      views.map((view) => view.tabId),
      [11],
    );
  });

  it("连着关两个标签页，两个都关得掉（写链串行，不互相覆盖）", async () => {
    const bg = await freshBackground();
    for (const tabId of [11, 22, 33]) {
      await bg.handleFingerprint(
        fingerprint({ url: `https://item.jd.com/${tabId}.html`, title: `商品 ${tabId} 型号 A${tabId}` }),
        tabId,
      );
    }
    // 不等第一个关完就发第二个：这正是会互相覆盖的时序
    const first = bg.onTabRemoved(22);
    const second = bg.onTabRemoved(33);
    await Promise.all([first, second]);
    const views = poolTabViews(await readPool(bg));
    assert.deepEqual(
      views.map((view) => view.tabId),
      [11],
    );
  });

  it("页面不是商品页时，把该标签页从池子里清掉", async () => {
    const bg = await freshBackground();
    await bg.handleFingerprint(fingerprint({}), 11);
    await bg.handleFingerprint(
      fingerprint({ url: "https://search.jd.com/Search?keyword=iphone", title: null, priceText: null }, false),
      11,
    );
    const views = poolTabViews(await readPool(bg));
    assert.equal(views.length, 0);
  });

  it("切到某个标签页，侧边栏把它标成当前", async () => {
    const bg = await freshBackground();
    await bg.handleFingerprint(fingerprint({}), 11);
    await bg.handleFingerprint(
      fingerprint({
        url: "https://item.taobao.com/item.htm?id=778899",
        title: "Apple iPhone 15 Pro 256GB 黑色",
        priceText: "2449.00",
      }),
      22,
    );
    await bg.onTabActivated({ tabId: 22 });
    const views = poolTabViews(await readPool(bg));
    assert.deepEqual(
      views.filter((view) => view.isActive).map((view) => view.tabId),
      [22],
    );
  });

  it("没有 tabId 的上报直接忽略，不造出幽灵条目", async () => {
    const bg = await freshBackground();
    await bg.handleFingerprint(fingerprint({}), undefined);
    assert.equal(poolTabViews(await readPool(bg)).length, 0);
  });

  it("字段不全的上报不会把池子写坏", async () => {
    const bg = await freshBackground();
    await bg.handleFingerprint(
      { type: "page-fingerprint", reason: "load", isProduct: true, fields: {} as PageFields },
      11,
    );
    assert.equal(poolTabViews(await readPool(bg)).length, 0);
  });

  it("存储被写坏时读回来是空池，不是崩在侧边栏上", async () => {
    const bg = await freshBackground();
    await chrome.storage.session.set({ "agentmart.sessionPool": "一堆垃圾" });
    assert.deepEqual(revivePool(await rawPool(bg)), revivePool(null));
  });
});

describe("0 次点击的自动对比（阶段一 DoD）", () => {
  beforeEach(() => {
    installChromeStub();
  });

  /** 造一个「用户在京东开了 iPhone 页、又去淘宝开了同款页」的池子。
   *
   *  两步之间故意等几毫秒：否则 Date.now() 可能落在同一毫秒里，
   *  「最近活跃」的排序不确定，测试会随机绿随机红。 */
  async function twoPlatformPool(): Promise<ReturnType<typeof revivePool>> {
    const bg = await freshBackground();
    await bg.handleFingerprint(fingerprint({}), 11);
    await tick(5);
    await bg.handleFingerprint(
      fingerprint({
        url: "https://item.taobao.com/item.htm?id=778899",
        title: "Apple iPhone 15 Pro 256GB 黑色",
        priceText: "2449.00",
        shopName: "Apple Store 官方旗舰店",
        selfOperatedHint: false,
      }),
      22,
    );
    return readPool(bg);
  }

  it("一次都没点「读取」时，池子自己就能摆出并排对比", async () => {
    const pool = await twoPlatformPool();
    const groups = autoCompareFromPool(pool, null, "江苏");
    assert.equal(groups.length, 1);
    assert.equal(groups[0].offers.length, 2);
    assert.deepEqual(
      groups[0].offers.map((offer) => offer.platform).sort(),
      ["jd", "taobao"],
    );
    // 价格取自各自页面，没被谁覆盖
    assert.deepEqual(
      groups[0].offers.map((offer) => offer.list_price).sort(),
      ["2449.00", "2499.00"],
    );
  });

  it("对比基准是最近活跃的那个标签页", async () => {
    const bg = await freshBackground();
    await bg.handleFingerprint(fingerprint({}), 11);
    await bg.handleFingerprint(
      fingerprint({
        url: "https://item.taobao.com/item.htm?id=778899",
        title: "Apple iPhone 15 Pro 256GB 黑色",
        priceText: "2449.00",
      }),
      22,
    );
    // 三条操作可能落在同一毫秒里，排序就不确定了。等几毫秒再激活，
    // 保证「最近活跃」是真的更近。
    await tick(5);
    await bg.onTabActivated({ tabId: 22 });
    const groups = autoCompareFromPool(await readPool(bg), null, "江苏");
    assert.equal(groups[0].offers[0].platform, "taobao", "基准该是刚激活的那个");
  });

  it("用户手动读过的页面在池子里时，以它为基准", async () => {
    const pool = await twoPlatformPool();
    const manual = entryToOfferView(pool.clusters[0].tabs[11], "江苏");
    assert.ok(manual);
    const groups = autoCompareFromPool(pool, manual, "江苏");
    assert.equal(groups[0].offers[0].platform, "jd");
    assert.equal(groups[0].offers[0].id, manual.id);
  });

  it("用户读过的页面已经不在池子里，就退回池子自己的基准", async () => {
    const pool = await twoPlatformPool();
    const stale = {
      id: "jd:000",
      platform: "jd" as const,
      platform_label: "京东",
      title: "别的商品",
      url: "https://item.jd.com/000.html",
      list_price: "1.00",
    } as unknown as OfferView;
    const groups = autoCompareFromPool(pool, stale, "江苏");
    assert.equal(groups.length, 1);
    assert.equal(groups[0].offers.length, 2);
  });

  it("只有一页在池子里时返回空 —— 一页谈不上对比", async () => {
    const bg = await freshBackground();
    await bg.handleFingerprint(fingerprint({}), 11);
    assert.deepEqual(autoCompareFromPool(await readPool(bg), null, "江苏"), []);
  });

  it("空池子返回空，不抛错", () => {
    assert.deepEqual(autoCompareFromPool(revivePool(null), null, ""), []);
  });

  it("不同款的两页各成一组，绝不摆成一副能比的样子", async () => {
    const bg = await freshBackground();
    await bg.handleFingerprint(fingerprint({}), 11);
    await bg.handleFingerprint(
      fingerprint({
        url: "https://item.taobao.com/item.htm?id=778899",
        title: "华为 Mate 60 Pro 12GB+512GB 雅丹黑",
        priceText: "6499.00",
      }),
      22,
    );
    const pool = await readPool(bg);
    // 池子里有两页，但自动对比一页都不该摆
    assert.equal(poolTabViews(pool).length, 2);
    assert.deepEqual(autoCompareFromPool(pool, null, "江苏"), []);
  });

  it("没抽到价格的页面进不了最低价比拼，但也不会把整组拖没", async () => {
    const bg = await freshBackground();
    await bg.handleFingerprint(fingerprint({}), 11);
    await bg.handleFingerprint(
      fingerprint({
        url: "https://item.taobao.com/item.htm?id=778899",
        title: "Apple iPhone 15 Pro 256GB 黑色",
        priceText: "2449.00",
      }),
      22,
    );
    await bg.handleFingerprint(
      fingerprint({
        url: "https://item.jd.com/100012043979.html",
        title: "Apple iPhone 15 Pro 256GB 黑色",
        priceText: null,
      }),
      33,
    );
    const groups = autoCompareFromPool(await readPool(bg), null, "江苏");
    assert.equal(groups.length, 1);
    assert.equal(groups[0].offers.length, 3);
    const withoutPrice = groups[0].offers.find((offer) => offer.id.endsWith("100012043979"));
    assert.ok(withoutPrice, "缺价那页也该露面，只是标注不参与比价");
    assert.equal(withoutPrice.list_price, "0.00");
    // 关键：那个 0 是「没读到」，不是「免费」，不能赢了最低价
    assert.equal(groups[0].best_definite_price, "2449.00");
  });

  it("整组都没价格时，最低价显示「—」而不是 0.00", async () => {
    const bg = await freshBackground();
    await bg.handleFingerprint(fingerprint({ priceText: null }), 11);
    await bg.handleFingerprint(
      fingerprint({
        url: "https://item.taobao.com/item.htm?id=778899",
        title: "Apple iPhone 15 Pro 256GB 黑色",
        priceText: null,
      }),
      22,
    );
    const groups = autoCompareFromPool(await readPool(bg), null, "江苏");
    assert.equal(groups.length, 1);
    assert.equal(groups[0].best_definite_price, null);
  });
});

/** 等几毫秒。会话池用 Date.now() 打时间戳，同一毫秒内排序不确定。 */
async function tick(ms: number): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, ms));
}

async function readPool(bg: typeof import("../background/session.ts")): Promise<ReturnType<typeof revivePool>> {
  const store = await chrome.storage.session.get(bg.SESSION_POOL_KEY);
  return revivePool(store[bg.SESSION_POOL_KEY]);
}

async function rawPool(bg: typeof import("../background/session.ts")): Promise<unknown> {
  const store = await chrome.storage.session.get(bg.SESSION_POOL_KEY);
  return store[bg.SESSION_POOL_KEY];
}
