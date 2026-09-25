/** SKU 规格同步测试：价格必须对应同一个规格，否则不能比。
 *
 *  与后端 tests/test_sku.py 对等。核心场景：很多平台把颜色/尺码只放在
 *  规格选择器里，标题里不写 —— 标题相同的两件商品，一个选的是黑色 L、
 *  一个是蓝色 M，标题比对完全看不出差别。
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import type { OfferView } from "../../src/lib/browserApi.ts";
import { buildCompareGroups, breakdownFor } from "../core/grouping.ts";
import { buildOffer } from "../core/offer.ts";
import { offerView } from "../core/serialize.ts";
import {
  describeSku,
  hardSkuConflict,
  parseSku,
  skuRelation,
  skuSpecIsEmpty,
} from "../core/sku.ts";

/** 走真实链路造 OfferView：页面字段 → Offer → 视图。
 *
 *  不手搓视图字面量 —— 手搓的那个会和序列化契约脱节，测的就不是
 *  用户在界面上真正看到的东西了。 */
function view(
  skuText: string | null,
  platform: Parameters<typeof buildOffer>[0] = "jd",
  overrides: Partial<Parameters<typeof buildOffer>[1]> = {},
): OfferView {
  const { offer } = buildOffer(
    platform,
    {
      url:
        platform === "pdd"
          ? "https://mobile.pinduoduo.com/goods.html?goods_id=2987654321"
          : "https://item.jd.com/100012043978.html",
      title: "冲锋衣 TAWJ91719 三合一",
      priceText: "1299.00",
      shopName: "京东自营旗舰店",
      skuText,
      ...overrides,
    },
    { sourceLabel: "test" },
  );
  return offerView(offer, breakdownFor(offer), {});
}

describe("parseSku 归一化", () => {
  it("颜色别名归一到同一个值", () => {
    assert.equal(parseSku("曜石黑 L码").color, "黑");
    assert.equal(parseSku("黑色 L").color, "黑");
    assert.equal(parseSku("月光白").color, "白");
    assert.equal(parseSku("deep space gray").color, "灰");
  });

  it("尺码去掉「码」后缀并统一大写", () => {
    assert.deepEqual(parseSku("曜石黑 L码").sizes, ["L"]);
    assert.deepEqual(parseSku("42码").sizes, ["42"]);
    assert.deepEqual(parseSku("175/96A").sizes, ["175/96A"]);
    assert.deepEqual(parseSku("XXL").sizes, ["XXL"]);
  });

  it("不把网络制式和型号当成尺码", () => {
    assert.deepEqual(parseSku("5G").sizes, []);
    assert.deepEqual(parseSku("S24").sizes, []);
    assert.deepEqual(parseSku("M330").sizes, []);
    assert.deepEqual(parseSku("1.5L").sizes, []);
  });

  it("不把营销词当尺码", () => {
    assert.deepEqual(parseSku("S级音质").sizes, []);
    assert.deepEqual(parseSku("M系列").sizes, []);
  });

  it("容量取最大：内存不冒充存储", () => {
    assert.equal(parseSku("12GB+256GB").storage, "256GB");
    assert.equal(parseSku("深空灰 256GB 国行 全新").storage, "256GB");
    assert.equal(parseSku("5G").storage, null);
  });

  it("读出版本、成色、套装", () => {
    const spec = parseSku("深空灰 256GB 国行 全新");
    assert.equal(spec.version, "cn");
    assert.equal(spec.condition, "new");
    assert.equal(parseSku("套装 含保护套").bundle, true);
  });

  it("空规格被认成空", () => {
    assert.ok(skuSpecIsEmpty(parseSku("")));
    assert.ok(skuSpecIsEmpty(parseSku(null)));
    assert.ok(!skuSpecIsEmpty(parseSku("黑色 L")));
  });

  it("describe 给界面一句话", () => {
    assert.equal(describeSku(parseSku("曜石黑 L码")), "黑色 L");
    assert.equal(describeSku(parseSku("深空灰 256GB 国行 全新")), "灰色 256GB 国行 全新");
    assert.equal(describeSku(parseSku("")), "");
  });
});

describe("skuRelation", () => {
  it("尺码不同是 variant", () => {
    assert.equal(skuRelation(parseSku("黑色 L"), parseSku("蓝色 M")), "variant");
  });

  it("归一后同一个规格是 matched", () => {
    assert.equal(skuRelation(parseSku("曜石黑 L码"), parseSku("黑色 L")), "matched");
  });

  it("读不到规格是 unknown，不假装一致", () => {
    assert.equal(skuRelation(parseSku("黑色 L"), parseSku("")), "unknown");
    assert.equal(skuRelation(parseSku(""), parseSku("")), "unknown");
  });

  it("容量/版本/成色/套装不同都是硬冲突", () => {
    assert.ok(hardSkuConflict(parseSku("256GB"), parseSku("512GB")));
    assert.ok(hardSkuConflict(parseSku("国行"), parseSku("港版")));
    assert.ok(hardSkuConflict(parseSku("全新"), parseSku("二手")));
    assert.ok(hardSkuConflict(parseSku("套装"), parseSku("单品")));
  });

  it("只有颜色不同不构成硬冲突", () => {
    assert.equal(hardSkuConflict(parseSku("黑色 L"), parseSku("蓝色 L")), null);
    // 但颜色不同仍然算 variant：界面上要写明颜色不同
    assert.equal(skuRelation(parseSku("黑色 L"), parseSku("蓝色 L")), "variant");
  });
});

describe("归组时的规格同步", () => {
  it("规格不同的报价标成 variant 并给出警告", () => {
    const a = view("黑色 L");
    const b = view("蓝色 M", "pdd");
    const { groups } = buildCompareGroups(a, [b]);
    const statuses = Object.fromEntries(
      groups[0].offers.map((o) => [o.id, o.sku_sync]),
    );
    assert.equal(statuses[a.id], "matched");
    assert.equal(statuses[b.id], "variant");
    assert.equal(groups[0].sku_status, "mixed");
    assert.ok(groups[0].warnings.some((w) => w.includes("规格不一致")));
  });

  it("读不到规格时是 unknown，不是 matched", () => {
    const a = view("黑色 L");
    const b = view("", "pdd");
    const { groups } = buildCompareGroups(a, [b]);
    const statuses = Object.fromEntries(
      groups[0].offers.map((o) => [o.id, o.sku_sync]),
    );
    assert.equal(statuses[a.id], "matched");
    assert.equal(statuses[b.id], "unknown");
    assert.equal(groups[0].sku_status, "unknown");
  });

  it("归一后同一规格归为 matched", () => {
    const a = view("曜石黑 L码");
    const b = view("黑色 L", "pdd");
    const { groups } = buildCompareGroups(a, [b]);
    assert.equal(groups[0].sku_status, "matched");
    assert.ok(!groups[0].warnings.some((w) => w.includes("规格不一致")));
  });
});
