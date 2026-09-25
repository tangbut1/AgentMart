/** 优惠/政策文案解释。
 *
 *  这些用例锁的是「诚实」规则，不只是正则行为：
 *  - 看不懂就不猜（返回 null，不当成优惠）；
 *  - 「已领取」优先于「去领取」（同一个"领"字，结论相反）；
 *  - 否定式退换限制优先于肯定式，否则保护会被讲成坑。
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  classifyShop,
  certaintyToCondition,
  extractPolicies,
  interpretCouponText,
} from "../core/discount.ts";

describe("interpretCouponText 分支选择", () => {
  it("已领取 → 账号可见可用券（可计入确定到手价）", () => {
    const reading = interpretCouponText("满2000减200 已领取");
    assert.ok(reading);
    // 门槛 2000 元 = 200000 分；抵扣 200 元 = 20000 分
    assert.equal(reading.threshold, 200000);
    assert.equal(reading.amount, 20000);
    assert.equal(reading.certainty, "account_coupon");
    assert.equal(certaintyToCondition(reading.certainty), "unconditional");
  });

  it("「已领取」里含「领取」，不能被当成还需要去领", () => {
    const reading = interpretCouponText("已领取 满100减10");
    assert.ok(reading);
    assert.equal(reading.certainty, "account_coupon");
  });

  it("去领取/点击领取 → 满足条件才成立", () => {
    for (const text of ["去领取 满500减50", "立即领取 满300减30", "点击领取 满100减5"]) {
      const reading = interpretCouponText(text);
      assert.ok(reading, text);
      assert.equal(reading.certainty, "conditional", text);
      assert.equal(certaintyToCondition(reading.certainty), "conditional");
    }
  });

  it("「可用」且没有动作词 → 已可用", () => {
    const reading = interpretCouponText("本店优惠券可用 减20元");
    assert.ok(reading);
    assert.equal(reading.certainty, "account_coupon");
  });

  it("「可用」但有动作词 → 仍然conditional", () => {
    const reading = interpretCouponText("优惠券可用，去领取 减20元");
    assert.ok(reading);
    assert.equal(reading.certainty, "conditional");
  });

  it("已抢光/已失效 → 无法核实，绝不计入到手价", () => {
    for (const text of ["已抢光 满200减30", "已过期 满100减10", "已失效 满500减20"]) {
      const reading = interpretCouponText(text);
      assert.ok(reading, text);
      assert.equal(reading.certainty, "unverifiable", text);
      assert.equal(certaintyToCondition(reading.certainty), "unverifiable");
    }
  });

  it("补贴一律无法核实 —— 资格没有一项能从商品页确认", () => {
    const reading = interpretCouponText("国补15% 限江苏省用户");
    assert.ok(reading);
    assert.equal(reading.kind, "subsidy");
    assert.equal(reading.certainty, "unverifiable");
  });

  it("只写「有补贴」没有金额时也列出来，但标为无法核实", () => {
    const reading = interpretCouponText("百亿补贴 限时抢购");
    assert.ok(reading);
    assert.equal(reading.kind, "subsidy");
    assert.equal(reading.amount, null);
    assert.equal(reading.certainty, "unverifiable");
  });

  it("文案里没有可量化金额、也不是补贴 → 返回 null（不猜）", () => {
    assert.equal(interpretCouponText("限时活动火热进行中"), null);
    assert.equal(interpretCouponText("加入购物车"), null);
    assert.equal(interpretCouponText("满"), null);
  });

  it("支付类关键词归到 payment", () => {
    const reading = interpretCouponText("支付宝支付立减20元");
    assert.ok(reading);
    assert.equal(reading.kind, "payment");
  });

  it("门槛原文照抄，不做两位小数补齐", () => {
    const reading = interpretCouponText("已领取 满99.5减10");
    assert.ok(reading);
    assert.equal(reading.threshold_text, "99.5");
    assert.equal(reading.threshold, 9950);
  });

  it("「满100减0」在两边都要得到 0 而不是 null", () => {
    const reading = interpretCouponText("已领取 满100减0");
    assert.ok(reading);
    assert.equal(reading.amount, 0);
    assert.equal(reading.threshold, 10000);
  });
});

describe("classifyShop", () => {
  it("只在页面明示时标注，否则 unknown", () => {
    assert.equal(classifyShop(null, false).shop_type, "unknown");
    assert.equal(classifyShop("", false).shop_type, "unknown");
    assert.equal(classifyShop("   ", false).shop_type, "unknown");
  });

  it("自营提示或店名含「自营」都算自营", () => {
    assert.equal(classifyShop("某店", true).shop_type, "self_operated");
    assert.equal(classifyShop("某某自营店", false).shop_type, "self_operated");
  });

  it("官方旗舰店优先于普通旗舰店", () => {
    assert.equal(classifyShop("某某官方旗舰店", false).shop_type, "official_flagship");
    assert.equal(classifyShop("某某旗舰店", false).shop_type, "flagship");
  });

  it("专营/授权", () => {
    assert.equal(classifyShop("某某专营店", false).shop_type, "authorized");
    assert.equal(classifyShop("某某授权店", false).shop_type, "authorized");
  });

  it("普通店铺", () => {
    assert.equal(classifyShop("某某工厂店", false).shop_type, "third_party");
  });
});

describe("extractPolicies 否定式优先", () => {
  it("「激活后不支持7天无理由」归成退换限制，不是售后/退换", () => {
    const policies = extractPolicies(["激活后不支持7天无理由退货"]);
    assert.equal(policies.length, 1);
    assert.equal(policies[0].category, "return_restriction");
  });

  it("肯定式的「7天无理由」归售后/退换", () => {
    const policies = extractPolicies(["7天无理由退货"]);
    assert.equal(policies.length, 1);
    assert.equal(policies[0].category, "after_sales");
  });

  it("「特价商品不退不换」归退换限制", () => {
    const policies = extractPolicies(["特价商品不退不换"]);
    assert.equal(policies[0].category, "return_restriction");
  });

  it("命中不了任何模式就跳过，不硬造一条政策", () => {
    assert.deepEqual(extractPolicies(["支持以旧换新", "新品尝鲜"]), []);
  });

  it("同文案同分类去重", () => {
    const policies = extractPolicies(["7天无理由退货", "7天无理由退货"]);
    assert.equal(policies.length, 1);
  });

  it("分类齐全", () => {
    const policies = extractPolicies([
      "7天无理由退货",
      "全国联保",
      "运费险",
      "假一赔十",
      "可开发票",
      "价保30天",
    ]);
    assert.deepEqual(
      policies.map((p) => p.category),
      ["after_sales", "warranty", "shipping", "authenticity", "invoice", "price_protection"],
    );
  });

  it("「退货运费险」按退换类归，不按物流类归（与后端同一套模式顺序）", () => {
    // 模式的先后顺序是 7天无理由 → 退换 → 保修 → 包邮/运费险，
    // 「退货运费险」先命中「退货」。这条只锁住两侧不漂移：
    // 它影响的是政策归到哪一栏，文案本身照原样展示，不会把限制讲成保障。
    const policies = extractPolicies(["退货运费险"]);
    assert.equal(policies[0].category, "after_sales");
  });

  it("scope 固定为商品页承诺", () => {
    assert.equal(extractPolicies(["7天无理由退货"])[0].scope, "product_page_promise");
  });
});
