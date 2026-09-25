import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  MAX_SESSION_TABS,
  activateTab,
  clusterModelPartial,
  emptyPool,
  entryFromFields,
  looksLikeProductPage,
  poolCounts,
  poolTabs,
  poolTabViews,
  removeTab,
  revivePool,
  sortedTabs,
  upsertEntry,
  type SessionEntry,
} from "../core/session.ts";
import type { PageFields } from "../core/offer.ts";
import { modelTokens } from "../core/modelTokens.ts";

const T0 = 1_700_000_000_000;

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

function entry(tabId: number, over: Partial<PageFields> = {}, at = T0): SessionEntry {
  const built = entryFromFields(tabId, fields(over), at);
  assert.ok(built, `entry ${tabId} should build`);
  return built;
}

/** 直接构造条目，用来测一些 buildOffer 抽不出来的边界（比如别的平台）。 */
function rawEntry(tabId: number, url: string, title: string, at = T0): SessionEntry {
  const built = entryFromFields(tabId, fields({ url, title, priceText: "99.00" }), at);
  assert.ok(built, `entry ${tabId} should build`);
  return built;
}

describe("looksLikeProductPage", () => {
  it("抽到价格的商品链接算商品页", () => {
    assert.equal(looksLikeProductPage("https://item.jd.com/100012043978.html", fields()), true);
  });

  it("链接长得像商品页但价格还没渲染出来，也算", () => {
    // 京东部分品类价格要登录后才出现，不能因为没抽到价格就整页丢掉
    const noPrice = fields({ priceText: null });
    assert.equal(looksLikeProductPage("https://item.jd.com/100012043978.html", noPrice), true);
  });

  it("价格抽到了但链接完全不像商品页，也算", () => {
    const odd = fields({ url: "https://www.jd.com/" });
    assert.equal(looksLikeProductPage("https://www.jd.com/", odd), true);
  });

  it("不认识的域名一律不算", () => {
    assert.equal(looksLikeProductPage("https://example.com/item/1", fields({ url: "https://example.com/item/1" })), false);
  });

  it("非 http(s) 一律不算", () => {
    assert.equal(looksLikeProductPage("chrome://extensions", fields({ url: "chrome://extensions" })), false);
    assert.equal(looksLikeProductPage("about:blank", null), false);
    assert.equal(looksLikeProductPage("", null), false);
  });

  it("标题太短的不算 —— 购物车、订单页这类", () => {
    const short = fields({ title: "购物车" });
    assert.equal(looksLikeProductPage("https://cart.jd.com/", short), false);
  });

  it("标题和价格都没有的搜索页不算", () => {
    const search = fields({ url: "https://search.jd.com/Search?keyword=iphone", title: null, priceText: null });
    assert.equal(looksLikeProductPage("https://search.jd.com/Search?keyword=iphone", search), false);
  });
});

describe("entryFromFields", () => {
  it("按 URL 认出平台，并从标题+规格里挑型号", () => {
    const built = entry(1);
    assert.equal(built.platform, "jd");
    assert.equal(built.priceText, "2499.00");
    assert.equal(built.shopName, "Apple 产品京东自营旗舰店");
    assert.ok(built.modelTokens.includes("IPHONE15"));
  });

  it("天猫链接归天猫，不归淘宝", () => {
    const built = entry(2, { url: "https://detail.tmall.com/item.htm?id=789" });
    assert.equal(built.platform, "tmall");
  });

  it("认不出平台的返回 null", () => {
    assert.equal(
      entryFromFields(3, fields({ url: "https://example.com/item/1" }), T0),
      null,
    );
  });

  it("标题为空时用 URL 兜底，不当成空标题", () => {
    const built = entry(4, { title: null });
    assert.equal(built.title, "https://item.jd.com/100012043978.html");
  });
});

describe("同款聚类", () => {
  it("两个平台的同款页面进同一组", () => {
    let pool = emptyPool();
    pool = upsertEntry(pool, entry(1));
    pool = upsertEntry(pool, rawEntry(2, "https://item.taobao.com/item.htm?id=777", "Apple iPhone 15 Pro 256GB 黑色", T0 + 1000));
    assert.equal(pool.clusters.length, 1);
    assert.equal(poolTabs(pool).length, 2);
    assert.deepEqual(poolCounts(pool), { tabs: 2, clusters: 1 });
  });

  it("不同型号各自成组，不硬凑", () => {
    let pool = emptyPool();
    pool = upsertEntry(pool, entry(1));
    pool = upsertEntry(pool, rawEntry(2, "https://item.taobao.com/item.htm?id=777", "华为 Mate 60 Pro 12GB+512GB", T0 + 1000));
    assert.equal(pool.clusters.length, 2);
  });

  it("同一标签页重复上报只留一份", () => {
    let pool = emptyPool();
    pool = upsertEntry(pool, entry(1, {}, T0));
    pool = upsertEntry(pool, entry(1, { priceText: "2399.00" }, T0 + 500));
    assert.equal(poolTabs(pool).length, 1);
    assert.equal(poolTabs(pool)[0].priceText, "2399.00");
  });

  it("认不出型号的页面自己一组，不和别的未识别页面合并", () => {
    let pool = emptyPool();
    pool = upsertEntry(pool, rawEntry(1, "https://item.jd.com/1.html", "京东超市 日用百货优惠装", T0));
    pool = upsertEntry(pool, rawEntry(2, "https://item.taobao.com/item.htm?id=5", "天猫超市 洗护组合装", T0 + 1000));
    assert.equal(pool.clusters.length, 2);
    assert.deepEqual(pool.clusters[0].anchorTokens, []);
    assert.deepEqual(pool.clusters[1].anchorTokens, []);
  });

  it("锚点固定为最早加入的条目，不随后来成员改变", () => {
    let pool = emptyPool();
    // 先打开的是纯 XM5 页面，它当锚点
    pool = upsertEntry(pool, rawEntry(1, "https://item.jd.com/1.html", "Sony WH-1000XM5 头戴式耳机", T0));
    // 再打开一个对比页：它带 XM5 和 XM4 两个 token，其中 XM4 是锚点没有的
    pool = upsertEntry(pool, rawEntry(2, "https://item.jd.com/2.html", "Sony WH-1000XM5 与 WH-1000XM4 对比 怎么选", T0 + 1000));
    // 又来一个纯 XM4 页面：只跟锚点比，锚点只有 XM5，所以并不进这一组
    pool = upsertEntry(pool, rawEntry(3, "https://item.jd.com/3.html", "Sony WH-1000XM4 头戴式耳机", T0 + 2000));
    // 用户又切回 tab 1：锚点不能因为切换而变
    pool = activateTab(pool, 1, T0 + 9000);
    assert.equal(pool.clusters.length, 2);
    const xm5Group = pool.clusters.find((cluster) => cluster.anchorTokens.includes("WH-1000XM5"));
    assert.ok(xm5Group);
    assert.deepEqual(
      Object.keys(xm5Group.tabs).map(Number).sort(),
      [1, 2],
    );
    const xm4Group = pool.clusters.find((cluster) => cluster.anchorTokens.includes("WH-1000XM4"));
    assert.ok(xm4Group);
    assert.deepEqual(Object.keys(xm4Group.tabs).map(Number), [3]);
  });

  it("锚点自己带了两个型号时，成员各带一个也能被发现", () => {
    let pool = emptyPool();
    // 对比页先打开，它带着 XM5 和 XM4 两个型号当锚点
    pool = upsertEntry(pool, rawEntry(1, "https://item.jd.com/1.html", "Sony WH-1000XM5 与 WH-1000XM4 对比", T0));
    pool = upsertEntry(pool, rawEntry(2, "https://item.jd.com/2.html", "Sony WH-1000XM5 头戴式耳机", T0 + 1000));
    pool = upsertEntry(pool, rawEntry(3, "https://item.jd.com/3.html", "Sony WH-1000XM4 头戴式耳机", T0 + 2000));
    assert.equal(pool.clusters.length, 1);
    // 三个页面全在一组里，但型号并不一致 —— 必须报警
    assert.equal(clusterModelPartial(pool.clusters[0]), true);
  });

  it("组内出现部分重合时给出提醒", () => {
    let pool = emptyPool();
    pool = upsertEntry(pool, rawEntry(1, "https://item.jd.com/1.html", "Sony WH-1000XM5 头戴式耳机", T0));
    pool = upsertEntry(pool, rawEntry(2, "https://item.jd.com/2.html", "Sony WH-1000XM5 与 WH-1000XM4 对比", T0 + 1000));
    assert.equal(clusterModelPartial(pool.clusters[0]), true);
    const views = poolTabViews(pool);
    assert.ok(views.every((view) => view.modelPartial));
  });

  it("组内完全一致时不提醒", () => {
    let pool = emptyPool();
    pool = upsertEntry(pool, entry(1));
    pool = upsertEntry(pool, rawEntry(2, "https://item.taobao.com/item.htm?id=777", "Apple iPhone 15 Pro 256GB 黑色", T0 + 1000));
    assert.equal(clusterModelPartial(pool.clusters[0]), false);
  });
});

describe("标签页生命周期", () => {
  it("关掉标签页就把它从池子里去掉，组也清掉", () => {
    let pool = emptyPool();
    pool = upsertEntry(pool, entry(1));
    pool = upsertEntry(pool, rawEntry(2, "https://item.taobao.com/item.htm?id=777", "Apple iPhone 15 Pro 256GB 黑色", T0 + 1000));
    pool = removeTab(pool, 2);
    assert.equal(poolTabs(pool).length, 1);
    assert.equal(pool.clusters.length, 1);
    assert.equal(Object.keys(pool.clusters[0].tabs).length, 1);
  });

  it("关掉不存在的标签页时原样返回", () => {
    const pool = upsertEntry(emptyPool(), entry(1));
    assert.equal(removeTab(pool, 999), pool);
  });

  it("关掉的正是当前标签页时，清掉当前标记", () => {
    let pool = emptyPool();
    pool = upsertEntry(pool, entry(1));
    pool = activateTab(pool, 1, T0 + 100);
    pool = removeTab(pool, 1);
    assert.equal(pool.activeTabId, null);
  });

  it("切到标签页会更新它的活跃时间并标为当前", () => {
    let pool = emptyPool();
    pool = upsertEntry(pool, entry(1, {}, T0));
    pool = upsertEntry(pool, rawEntry(2, "https://item.taobao.com/item.htm?id=777", "Apple iPhone 15 Pro 256GB 黑色", T0 + 1000));
    pool = activateTab(pool, 1, T0 + 5000);
    assert.equal(pool.activeTabId, 1);
    assert.equal(sortedTabs(pool.clusters[0])[0].tabId, 1);
    const views = poolTabViews(pool);
    assert.deepEqual(
      views.filter((view) => view.isActive).map((view) => view.tabId),
      [1],
    );
  });

  it("切到一个还没上报过的标签页，也照样记下当前", () => {
    let pool = emptyPool();
    pool = upsertEntry(pool, entry(1));
    pool = activateTab(pool, 42, T0);
    assert.equal(pool.activeTabId, 42);
  });
});

describe("容量上限", () => {
  it("超过上限时丢最早不活跃的", () => {
    let pool = emptyPool();
    for (let i = 1; i <= MAX_SESSION_TABS + 5; i += 1) {
      pool = upsertEntry(pool, rawEntry(i, `https://item.jd.com/${i}.html`, `商品 ${i} 型号 A${i}`, T0 + i * 1000));
    }
    assert.equal(poolTabs(pool).length, MAX_SESSION_TABS);
    // 留下的应该是最新的那几个
    assert.ok(poolTabs(pool).every((item) => item.tabId > 5));
  });

  it("当前活动的标签页不因为超限被丢", () => {
    let pool = emptyPool();
    for (let i = 1; i <= MAX_SESSION_TABS; i += 1) {
      pool = upsertEntry(pool, rawEntry(i, `https://item.jd.com/${i}.html`, `商品 ${i} 型号 A${i}`, T0 + i * 1000));
    }
    pool = activateTab(pool, 1, T0 + 100); // 最早的那个被激活，但时间戳仍是旧的
    pool = upsertEntry(pool, rawEntry(99, "https://item.jd.com/99.html", "商品 99 型号 A99", T0 + 999_000));
    assert.ok(poolTabs(pool).some((item) => item.tabId === 1));
  });
});

describe("poolTabViews", () => {
  it("每项带平台中文名、当前标记和有无价格", () => {
    let pool = emptyPool();
    pool = upsertEntry(pool, entry(1));
    pool = upsertEntry(pool, rawEntry(2, "https://item.taobao.com/item.htm?id=777", "Apple iPhone 15 Pro 256GB 黑色", T0 + 1000));
    pool = upsertEntry(pool, rawEntry(3, "https://mobile.pinduoduo.com/goods.html?goods_id=9", "Apple iPhone 15 Pro 256GB 黑色", T0 + 2000, ));
    pool = activateTab(pool, 2, T0 + 3000);
    const views = poolTabViews(pool);
    // 组内按最近活跃排序：tab 2 刚被激活，排最前
    assert.deepEqual(views.map((view) => view.platform), ["taobao", "pdd", "jd"]);
    assert.deepEqual(
      views.map((view) => view.platformLabel),
      ["淘宝", "拼多多", "京东"],
    );
    assert.deepEqual(
      views.filter((view) => view.isActive).map((view) => view.platform),
      ["taobao"],
    );
    assert.ok(views.every((view) => view.hasPrice));
    assert.ok(views.every((view) => view.clusterId === views[0].clusterId));
  });

  it("没抽到价格的条目标成没有价格", () => {
    let pool = emptyPool();
    pool = upsertEntry(pool, entry(1, { priceText: null }));
    assert.equal(poolTabViews(pool)[0].hasPrice, false);
  });
});

describe("revivePool", () => {
  it("JSON 往返后数字键能还原", () => {
    let pool = emptyPool();
    pool = upsertEntry(pool, entry(1));
    pool = upsertEntry(pool, rawEntry(2, "https://item.taobao.com/item.htm?id=777", "Apple iPhone 15 Pro 256GB 黑色", T0 + 1000));
    pool = activateTab(pool, 2, T0 + 2000);
    const revived = revivePool(JSON.parse(JSON.stringify(pool)));
    assert.equal(poolTabs(revived).length, 2);
    assert.equal(revived.activeTabId, 2);
    assert.equal(revived.clusters.length, 1);
    assert.deepEqual(sortedTabs(revived.clusters[0]).map((item) => item.tabId), [2, 1]);
  });

  it("读到的不是池子就当空池", () => {
    assert.deepEqual(revivePool(null), emptyPool());
    assert.deepEqual(revivePool(undefined), emptyPool());
    assert.deepEqual(revivePool("nope"), emptyPool());
    assert.deepEqual(revivePool(42), emptyPool());
    assert.deepEqual(revivePool({ version: 2, clusters: [] }), emptyPool());
    assert.deepEqual(revivePool({ version: 1, clusters: "bad" }), emptyPool());
  });

  it("坏条目直接丢掉，不带病进池", () => {
    const dirty = {
      version: 1,
      activeTabId: 1,
      clusters: [
        {
          clusterId: "iphone15",
          anchorTokens: ["IPHONE15"],
          tabs: {
            "1": {
              tabId: 1,
              platform: "jd",
              url: "https://item.jd.com/100012043978.html",
              title: "Apple iPhone 15 Pro",
              priceText: "2499.00",
              shopName: null,
              modelTokens: ["IPHONE15"],
              lastActiveAt: T0,
              fields: null,
            },
            "2": { tabId: 2, platform: "nope", url: "x", title: "", modelTokens: "bad" },
            "3": null,
          },
        },
      ],
    };
    const revived = revivePool(dirty);
    assert.equal(poolTabs(revived).length, 1);
    assert.equal(revived.activeTabId, 1);
    assert.equal(revived.clusters[0].anchorTokens[0], "IPHONE15");
  });

  it("activeTabId 指向的条目不存在时，不当成当前", () => {
    const pool = upsertEntry(emptyPool(), entry(1));
    const revived = revivePool({ ...pool, activeTabId: 77 });
    assert.equal(revived.activeTabId, null);
  });
});

describe("modelTokens（会话池用到的部分）", () => {
  it("容量不混进型号", () => {
    assert.deepEqual(modelTokens("Apple iPhone 15 Pro 256GB 黑色"), ["IPHONE15"]);
  });

  it("纯中文标题认不出型号也不报错", () => {
    assert.deepEqual(modelTokens("洗衣液 深层洁净 补充装 3kg"), []);
  });
});
