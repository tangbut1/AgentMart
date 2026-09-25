/** 跨平台同款归组与平台识别。
 *
 *  核心规矩：认不出是同款就单独列，绝不为了凑一个对比表把两件不同的
 *  商品排在一起。
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { offerId } from "../core/model.ts";
import { buildCompareGroups, breakdownFor, matchOffer, modelTokens } from "../core/grouping.ts";
import { otherPlatforms, platformFromUrl, recipeFor, searchUrl } from "../core/platforms.ts";
import { buildOffer } from "../core/offer.ts";
import { offerView } from "../core/serialize.ts";

function viewOf(fields: Parameters<typeof buildOffer>[1], platform: Parameters<typeof buildOffer>[0] = "jd") {
  const { offer } = buildOffer(platform, fields, { sourceLabel: "test" });
  return offerView(offer, breakdownFor(offer), {});
}

describe("modelTokens", () => {
  it("挑出含数字、长度够的 token", () => {
    assert.deepEqual(modelTokens("Sony WH-1000XM5 无线降噪耳机"), ["WH-1000XM5"]);
    assert.deepEqual(modelTokens("Redmi Buds 6 Pro 蓝牙耳机"), ["BUDS6"]);
  });

  it("「单词 + 数字」型号能认出来（iPhone 15 这类最常见）", () => {
    assert.deepEqual(modelTokens("Apple iPhone 15 Pro 256GB 黑色"), ["IPHONE15"]);
    assert.deepEqual(modelTokens("Galaxy S24 Ultra"), ["S24"]);
    // 两边写法不同也能对上：京东「iPhone 15」天猫「苹果 iPhone 15」
    assert.deepEqual(modelTokens("苹果 iPhone 15"), ["IPHONE15"]);
  });

  it("屏幕尺寸、电池容量不当成型号", () => {
    assert.deepEqual(modelTokens("MacBook Air 13.6英寸 笔记本电脑"), []);
    assert.deepEqual(modelTokens("手机 5000mAh 大电池"), []);
    assert.deepEqual(modelTokens("显示器 27 英寸 2K"), []);
  });

  it("品牌名没有数字就不当型号（型号里几乎总有数字）", () => {
    assert.deepEqual(modelTokens("Bose QuietComfort 消噪耳机"), []);
    assert.deepEqual(modelTokens("Dyson 吸尘器"), []);
  });

  it("通用规格词不当成型号", () => {
    const tokens = modelTokens("iPhone 15 128GB 黑色 5G TYPE-C A3092");
    assert.ok(!tokens.includes("128GB"));
    assert.ok(!tokens.includes("TYPE-C"));
    assert.ok(!tokens.includes("5G"));
    assert.ok(tokens.includes("A3092"));
  });

  it("纯字母的词不当成型号（型号里几乎总有数字）", () => {
    assert.deepEqual(modelTokens("Sony 无线降噪耳机"), []);
  });

  it("太短的 token 丢掉", () => {
    assert.deepEqual(modelTokens("商品 A1 型号"), ["A1"].filter((t) => t.length >= 3));
  });

  it("大小写归一", () => {
    assert.deepEqual(modelTokens("bose qc45"), modelTokens("BOSE QC45"));
  });
});

describe("matchOffer", () => {
  const primary = viewOf({
    url: "https://item.jd.com/100012043978.html",
    title: "Sony WH-1000XM5 头戴式无线降噪耳机 蓝牙5.2",
    priceText: "2899.00",
    shopName: "索尼官方旗舰店",
    policyTexts: ["7天无理由退货", "运费险"],
    evidence: { price: "x" },
  });

  it("同一款：型号重合，置信度高", () => {
    const same = viewOf(
      {
        url: "https://detail.tmall.com/item.htm?id=678901234567",
        title: "Sony WH-1000XM5 头戴式降噪耳机 无线蓝牙",
        priceText: "2799.00",
        shopName: "索尼官方旗舰店",
        policyTexts: ["7天无理由退货", "运费险"],
        evidence: { price: "x" },
      },
      "tmall",
    );
    const reading = matchOffer(primary, same);
    assert.deepEqual(reading.shared, ["WH-1000XM5"]);
    assert.ok(reading.confidence >= 0.34);
  });

  it("不同款：没有共同型号就不说是同款", () => {
    const other = viewOf(
      {
        url: "https://detail.tmall.com/item.htm?id=678901234568",
        title: "Bose QuietComfort 45 消噪耳机",
        priceText: "1899.00",
        shopName: "BOSE官方旗舰店",
        policyTexts: [],
        evidence: {},
      },
      "tmall",
    );
    const reading = matchOffer(primary, other);
    assert.deepEqual(reading.shared, []);
    assert.equal(reading.confidence, 0);
  });

  it("一侧认不出型号时明确说无法确认", () => {
    const noModel = viewOf(
      {
        url: "https://detail.tmall.com/item.htm?id=678901234569",
        title: "无线降噪耳机 长续航",
        priceText: "299.00",
        shopName: "配件店",
        policyTexts: [],
        evidence: {},
      },
      "tmall",
    );
    const reading = matchOffer(primary, noModel);
    assert.equal(reading.confidence, 0);
    assert.ok(reading.warnings.some((w) => w.includes("无法确认")));
  });

  it("型号只部分重合时给出规格提醒", () => {
    const partial = viewOf(
      {
        url: "https://detail.tmall.com/item.htm?id=678901234570",
        title: "Sony WH-1000XM5 与 WH-1000XM4 对比 新款",
        priceText: "2899.00",
        shopName: "索尼官方旗舰店",
        policyTexts: [],
        evidence: {},
      },
      "tmall",
    );
    const reading = matchOffer(primary, partial);
    assert.ok(reading.confidence > 0 && reading.confidence < 1);
    assert.ok(reading.warnings.some((w) => w.includes("规格可能不同")));
  });
});

describe("buildCompareGroups", () => {
  const primary = viewOf({
    url: "https://item.jd.com/100012043978.html",
    title: "Sony WH-1000XM5 头戴式无线降噪耳机",
    priceText: "2899.00",
    shopName: "索尼官方旗舰店",
    policyTexts: ["7天无理由退货", "运费险"],
    evidence: { price: "x" },
  });
  const sameOnTmall = viewOf(
    {
      url: "https://detail.tmall.com/item.htm?id=678901234567",
      title: "Sony WH-1000XM5 头戴式降噪耳机 无线蓝牙",
      priceText: "2799.00",
      shopName: "索尼官方旗舰店",
      policyTexts: ["7天无理由退货", "运费险"],
      evidence: { price: "x" },
    },
    "tmall",
  );
  const different = viewOf(
    {
      url: "https://item.taobao.com/item.htm?id=712345678902",
      title: "Bose QuietComfort 45 消噪耳机",
      priceText: "1899.00",
      shopName: "BOSE官方旗舰店",
      policyTexts: [],
      evidence: {},
    },
    "taobao",
  );

  it("同款进对比表，不同款单独列出来", () => {
    const result = buildCompareGroups(primary, [sameOnTmall, different]);
    assert.equal(result.groups.length, 1);
    assert.equal(result.groups[0].offers.length, 2);
    assert.deepEqual(
      result.unmatched.map((o) => o.id),
      [different.id],
    );
  });

  it("最低确定价取组内最小值", () => {
    const result = buildCompareGroups(primary, [sameOnTmall]);
    assert.equal(result.groups[0].best_definite_price, "2799.00");
  });

  it("只有主角时置信度为 1，不给虚假的高置信", () => {
    const result = buildCompareGroups(primary, [different]);
    assert.equal(result.groups[0].offers.length, 1);
    assert.equal(result.groups[0].confidence, 1);
    assert.equal(result.unmatched.length, 1);
  });

  it("主角自己不会重复进组", () => {
    const result = buildCompareGroups(primary, [primary, sameOnTmall]);
    assert.equal(result.groups[0].offers.length, 2);
  });

  it("组 id 以主角平台和商品 id 拼成", () => {
    const result = buildCompareGroups(primary, [sameOnTmall]);
    assert.equal(result.groups[0].id, `jd:${primary.id}`);
    // offerId 本身就是「平台:商品 id」
    const { offer } = buildOffer(
      "jd",
      {
        url: "https://item.jd.com/100012043978.html",
        title: "Sony WH-1000XM5",
        priceText: "2899.00",
        shopName: "索尼官方旗舰店",
        policyTexts: [],
        evidence: {},
      },
      { sourceLabel: "test" },
    );
    assert.equal(offerId(offer), "jd:100012043978");
  });

  it("规格栏只写共同认出的型号", () => {
    const result = buildCompareGroups(primary, [sameOnTmall]);
    assert.deepEqual(Object.keys(result.groups[0].specs), ["型号 WH-1000XM5"]);
  });
});

describe("platformFromUrl", () => {
  it("天猫要在淘宝之前判断（tmall.com 也出现在淘宝的 hosts 里）", () => {
    assert.equal(platformFromUrl("https://detail.tmall.com/item.htm?id=1"), "tmall");
    assert.equal(platformFromUrl("https://item.taobao.com/item.htm?id=1"), "taobao");
    assert.equal(platformFromUrl("https://www.tmall.com/"), "tmall");
  });

  it("五个平台都能认", () => {
    assert.equal(platformFromUrl("https://item.jd.com/100012043978.html"), "jd");
    assert.equal(platformFromUrl("https://item.jd.hk/1.html"), "jd");
    assert.equal(platformFromUrl("https://mobile.pinduoduo.com/goods.html"), "pdd");
    assert.equal(platformFromUrl("https://haohuo.jinritemai.com/goods/1"), "douyin");
  });
  it("认不出来返回 null，不猜", () => {
    assert.equal(platformFromUrl("https://www.example.com/item/1"), null);
    assert.equal(platformFromUrl("not a url"), null);
    assert.equal(platformFromUrl(""), null);
  });
});

describe("平台配方", () => {
  it("搜索地址做 URL 编码", () => {
    const url = searchUrl("jd", "索尼 WH-1000XM5");
    assert.ok(url.startsWith("https://search.jd.com/Search?keyword="));
    assert.ok(!url.includes(" "));
  });

  it("除主角外都参与比价", () => {
    assert.deepEqual(otherPlatforms("jd"), ["taobao", "tmall", "pdd", "douyin"]);
  });

  it("每个平台都有 home 和搜索地址", () => {
    for (const platform of ["jd", "taobao", "tmall", "pdd", "douyin"] as const) {
      const recipe = recipeFor(platform);
      assert.ok(recipe.home_url.startsWith("https://"), platform);
      assert.ok(recipe.search_url_template.includes("{kw}"), platform);
    }
  });

  it("未知平台抛错，不静默返回空", () => {
    assert.throws(() => recipeFor("unknown" as never));
  });
});
