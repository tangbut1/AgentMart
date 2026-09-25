/** 优惠券树与双轨净价。
 *
 *  锁的是两件事：
 *
 *  1. **不会报出用户拿不到的价**。两张同层互斥的券不能都减掉 —— 那正是
 *     "界面写着到手价 39.00，结算页却要 59.00" 的来源。被挤掉的那张必须
 *     仍然出现在树上，还要写明是被谁挤掉的。
 *  2. **两个轨不混**。公开轨只算谁来看都成立的抵扣；账号券只进我的轨。
 *     跨平台比价用公开轨，否则比出来的是账号差异不是商品差异。
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { buildOffer, type PageFields } from "../core/offer.ts";
import {
  accountGap,
  buildCouponTree,
  contributingLayers,
  couponTreeView,
} from "../core/couponTree.ts";
import { discountLayer, interpretCouponText } from "../core/discount.ts";
import type { Discount, Offer } from "../core/model.ts";
import { computePriceBreakdown } from "../core/pricing.ts";

function offer(...discounts: Discount[]): Offer {
  return {
    platform: "jd",
    platform_product_id: "1",
    title: "测试商品",
    url: "https://item.jd.com/1.html",
    list_price: 249900,
    shop_name: null,
    shop_type: "unknown",
    sku_text: null,
    sales_text: null,
    shipping_fee: 0,
    region: null,
    discounts: [...discounts],
    policies: [],
    data_status: "real",
    source: "test",
    source_url: null,
    fetched_at: null,
    credibility: 0.8,
    affiliate: false,
    match_confidence: null,
    match_notes: [],
  };
}

function discount(overrides: Partial<Discount> = {}): Discount {
  return {
    kind: "coupon",
    label: "测试券",
    amount: 0,
    percent: null,
    condition: "",
    condition_kind: "unconditional",
    stack_group: null,
    layer: null,
    certainty: null,
    max_amount: null,
    region_limit: null,
    eligibility: null,
    source_url: null,
    data_status: "real",
    note: null,
    ...overrides,
  };
}

function treeOf(target: Offer) {
  const breakdown = computePriceBreakdown({
    list_price: target.list_price,
    shipping_fee: target.shipping_fee,
    discounts: target.discounts,
    data_status: target.data_status,
  });
  return { breakdown, tree: buildCouponTree(target, breakdown) };
}

// ─── 层级推断 ──────────────────────────────────────────────────

describe("discountLayer 层级推断", () => {
  it("按文案分层", () => {
    assert.equal(discountLayer("店铺券满1000减50", "coupon"), "shop");
    assert.equal(discountLayer("本店满200减20", "coupon"), "shop");
    assert.equal(discountLayer("跨店每满300减40", "activity"), "platform");
    assert.equal(discountLayer("平台券满300减30", "coupon"), "platform");
    assert.equal(discountLayer("满2000减200", "activity"), "product");
  });

  it("kind 优先于文案：平台补贴是补贴层，不是平台层", () => {
    // "平台补贴" 同时命中平台层关键词和补贴关键词。它是补贴 —— 补贴层
    // 永远只按资格算，混进平台层会被当成能直接叠加的抵扣。
    assert.equal(discountLayer("平台补贴", "subsidy"), "subsidy");
    assert.equal(discountLayer("白条立减50", "payment"), "payment");
    assert.equal(discountLayer("包邮", "free_shipping"), "shipping");
  });

  it("平台层优先于店铺层：跨店满减含「店」字", () => {
    assert.equal(discountLayer("跨店满减每300减40", "activity"), "platform");
  });
});

// ─── 互斥：不报出拿不到的价 ────────────────────────────────────

describe("同层互斥", () => {
  it("两张店铺券只算一张", () => {
    const { breakdown, tree } = treeOf(
      offer(
        discount({ label: "店铺券满1000减50", amount: 5000, layer: "shop", certainty: "account_coupon" }),
        discount({ label: "店铺券满2000减80", amount: 8000, layer: "shop", certainty: "account_coupon" }),
      ),
    );
    // 两张都减会得到 236900，那是结算页拿不到的价
    assert.equal(breakdown.account_total, 241900);
    const shop = tree.layers.find((layer) => layer.key === "shop");
    assert.ok(shop);
    assert.deepEqual(
      shop.entries.filter((entry) => entry.counted).map((entry) => entry.label),
      ["店铺券满2000减80"],
    );
  });

  it("被挤掉的券仍然在树上，并写明被谁挤掉", () => {
    const { tree } = treeOf(
      offer(
        discount({ label: "店铺券A", amount: 5000, layer: "shop" }),
        discount({ label: "店铺券B", amount: 8000, layer: "shop" }),
      ),
    );
    const labels = tree.layers.flatMap((layer) => layer.entries.map((entry) => entry.label));
    assert.deepEqual(labels, ["店铺券A", "店铺券B"]);
    const loser = tree.layers[0].entries.find((entry) => !entry.counted);
    assert.equal(loser?.beaten_by, "店铺券B");
  });

  it("不同层的券都算", () => {
    const { breakdown } = treeOf(
      offer(
        discount({ label: "满2000减200", amount: 20000, layer: "product", certainty: "page_public" }),
        discount({ label: "店铺券", amount: 5000, layer: "shop", certainty: "account_coupon" }),
      ),
    );
    assert.equal(breakdown.public_total, 229900);
    assert.equal(breakdown.account_total, 224900);
  });

  it("多层同时成立时说明叠加关系是推断的", () => {
    const { tree } = treeOf(
      offer(
        discount({ label: "满2000减200", amount: 20000, layer: "product", certainty: "page_public" }),
        discount({ label: "店铺券", amount: 5000, layer: "shop", certainty: "account_coupon" }),
      ),
    );
    assert.equal(tree.stacking_confidence, "inferred");
    assert.ok(tree.notes.some((note) => note.includes("按各优惠所属层级推断")));
  });

  it("显式 stack_group 优先于推断的层级", () => {
    const { breakdown } = treeOf(
      offer(
        discount({ label: "组内A", amount: 5000, layer: "shop", stack_group: "promo" }),
        discount({ label: "组内B", amount: 8000, layer: "shop", stack_group: "promo" }),
      ),
    );
    assert.equal(breakdown.account_total, 241900);
    assert.ok(breakdown.applied_groups.includes("promo"));
  });

  it("没填层级时按老契约各自成立", () => {
    // 互斥只能由 stack_group 或 layer 表达，两个都没有就没有依据合并。
    // 采集侧一定填 layer（下面有测试守着），所以这条保守路径在扩展里走不到。
    const { breakdown } = treeOf(
      offer(discount({ label: "券A", amount: 5000 }), discount({ label: "券B", amount: 8000 })),
    );
    assert.equal(breakdown.account_total, 236900);
  });
});

// ─── 双轨净价 ──────────────────────────────────────────────────

describe("双轨净价", () => {
  it("账号券只进我的轨", () => {
    const { breakdown } = treeOf(
      offer(discount({ label: "店铺券", amount: 8000, layer: "shop", certainty: "account_coupon" })),
    );
    assert.equal(breakdown.public_total, 249900);
    assert.equal(breakdown.account_total, 241900);
    assert.equal(breakdown.account_total - breakdown.public_total, -8000);
  });

  it("页面公开活动两个轨都减", () => {
    const { breakdown } = treeOf(
      offer(discount({ label: "秒杀优惠", amount: 20000, layer: "product", certainty: "page_public" })),
    );
    assert.equal(breakdown.public_total, 229900);
    assert.equal(breakdown.account_total, 229900);
  });

  it("无法核实的两个轨都不进", () => {
    const { breakdown } = treeOf(
      offer(
        discount({
          label: "国补",
          amount: 30000,
          kind: "subsidy",
          layer: "subsidy",
          certainty: "unverifiable",
          condition_kind: "unverifiable",
        }),
      ),
    );
    assert.equal(breakdown.public_total, 249900);
    assert.equal(breakdown.account_total, 249900);
    assert.equal(breakdown.unverifiable_total, 30000);
  });

  it("满足条件的只进潜在价", () => {
    const { breakdown } = treeOf(
      offer(
        discount({
          label: "待领取券",
          amount: 8000,
          layer: "shop",
          certainty: "conditional",
          condition_kind: "conditional",
        }),
      ),
    );
    assert.equal(breakdown.public_total, 249900);
    assert.equal(breakdown.account_total, 249900);
    assert.equal(breakdown.potential_total, 241900);
  });

  it("没填确定性时按公开处理（API 版没有账号上下文）", () => {
    const { breakdown } = treeOf(
      offer(discount({ label: "活动直降", amount: 20000, layer: "product" })),
    );
    assert.equal(breakdown.public_total, 229900);
  });

  it("演示抵扣一个轨都不进", () => {
    const { breakdown } = treeOf(
      offer(discount({ label: "演示券", amount: 50000, layer: "shop", data_status: "demo" })),
    );
    assert.equal(breakdown.public_total, 249900);
    assert.equal(breakdown.account_total, 249900);
  });
});

// ─── 树结构 ────────────────────────────────────────────────────

describe("树结构", () => {
  it("按商品层→店铺层→平台层→支付层→补贴层排序", () => {
    const { tree } = treeOf(
      offer(
        discount({ label: "国补", amount: 30000, kind: "subsidy", layer: "subsidy" }),
        discount({ label: "白条立减", amount: 5000, kind: "payment", layer: "payment" }),
        discount({ label: "店铺券", amount: 8000, layer: "shop" }),
        discount({ label: "满2000减200", amount: 20000, layer: "product" }),
      ),
    );
    assert.deepEqual(
      tree.layers.map((layer) => layer.key),
      ["product", "shop", "payment", "subsidy"],
    );
  });

  it("每层金额按轨拆分", () => {
    const { tree } = treeOf(
      offer(
        discount({ label: "满2000减200", amount: 20000, layer: "product", certainty: "page_public" }),
        discount({ label: "店铺券", amount: 8000, layer: "shop", certainty: "account_coupon" }),
      ),
    );
    const product = tree.layers.find((layer) => layer.key === "product");
    const shop = tree.layers.find((layer) => layer.key === "shop");
    assert.equal(product?.public_amount, 20000);
    assert.equal(product?.account_amount, 0);
    assert.equal(shop?.public_amount, 0);
    assert.equal(shop?.account_amount, 8000);
  });

  it("accountGap 与 contributingLayers", () => {
    const { tree } = treeOf(
      offer(
        discount({ label: "满2000减200", amount: 20000, layer: "product", certainty: "page_public" }),
        discount({ label: "店铺券", amount: 8000, layer: "shop", certainty: "account_coupon" }),
      ),
    );
    assert.equal(accountGap(tree), 8000);
    assert.deepEqual(contributingLayers(tree), ["product", "shop"]);
  });

  it("序列化出的视图带中文标签", () => {
    const { tree } = treeOf(offer(discount({ label: "店铺券", amount: 8000, layer: "shop" })));
    const view = couponTreeView(tree);
    assert.equal(view.layers[0].layer, "shop");
    assert.equal(view.layers[0].layer_label, "店铺层");
    assert.equal(view.layers[0].entries[0].condition_kind_label, "无条件成立");
    // 没写确定性的券按「公开可见」算（见 isPagePublic），所以进公开轨
    assert.equal(view.layers[0].public_amount, "80.00");
    assert.equal(view.layers[0].account_amount, "0.00");
    assert.equal(view.account_gap, "0.00");
  });

  it("确定性标签由后端给，前端不自己翻译", () => {
    // 前端如果自己维护一份中文映射，就会出现「一边改了另一边没改」，
    // 而这种漂移在运行时不报错，只是界面上多出一个空白标签。
    const { tree } = treeOf(
      offer(
        discount({
          label: "店铺券 满2000减80 已领取",
          amount: 8000,
          layer: "shop",
          certainty: "account_coupon",
        }),
        discount({
          label: "限时秒杀 优惠200元",
          amount: 20000,
          layer: "product",
          certainty: "page_public",
        }),
      ),
    );
    const view = couponTreeView(tree);
    const shop = view.layers.find((layer) => layer.layer === "shop");
    const product = view.layers.find((layer) => layer.layer === "product");
    assert.equal(shop?.entries[0].certainty, "account_coupon");
    assert.equal(shop?.entries[0].certainty_label, "账号可见可用券");
    assert.equal(product?.entries[0].certainty, "page_public");
    assert.equal(product?.entries[0].certainty_label, "页面公开价");
  });
});

// ─── 端到端：页面文案 → 树 ─────────────────────────────────────

describe("页面文案一路建到树", () => {
  const fields: PageFields = {
    url: "https://item.jd.com/1.html",
    title: "测试商品",
    priceText: "¥2499.00",
    couponTexts: ["满2000减200", "店铺券满1000减50", "店铺券满2000减80", "国补15%"],
  };

  it("每条券都带上层级", () => {
    const { offer: built } = buildOffer("jd", fields, { sourceLabel: "side-panel" });
    assert.ok(built.discounts.length > 0);
    for (const entry of built.discounts) {
      assert.ok(entry.layer, entry.label);
    }
  });

  it("同层互斥在真实文案上生效", () => {
    const { offer: built } = buildOffer("jd", fields, { sourceLabel: "side-panel" });
    const { breakdown, tree } = treeOf(built);
    // 这些文案都没写「已领取/直降」，都是「满足条件才成立」：确定价不动，
    // 全进潜在价。店铺层两张券互斥，只算 80 那张。
    assert.equal(breakdown.account_total, 249900);
    assert.equal(breakdown.potential_total, 221900);
    const shop = tree.layers.find((layer) => layer.key === "shop");
    assert.equal(shop?.entries.filter((entry) => entry.counted).length, 1);
    assert.equal(shop?.entries[0].beaten_by, "店铺券满2000减80");
  });

  it("公开轨和我的轨在真实文案上分开", () => {
    const { offer: built } = buildOffer(
      "jd",
      {
        ...fields,
        couponTexts: ["限时秒杀 优惠200元", "店铺券 满1000减50 已领取"],
      },
      { sourceLabel: "side-panel" },
    );
    const { breakdown, tree } = treeOf(built);
    assert.equal(breakdown.public_total, 229900);
    assert.equal(breakdown.account_total, 224900);
    const product = tree.layers.find((layer) => layer.key === "product");
    const shop = tree.layers.find((layer) => layer.key === "shop");
    assert.equal(product?.public_amount, 20000);
    assert.equal(shop?.account_amount, 5000);
  });

  it("「限时活动 8.5折 已领取」是账号券，不是公开活动", () => {
    // 同时含「限时活动」和「已领取」：已领取优先，否则会把用户自己的券
    // 算成谁来看都成立的公开抵扣。
    const reading = interpretCouponText("限时活动 8.5折 已领取");
    assert.ok(reading);
    assert.equal(reading.certainty, "account_coupon");
  });
});
