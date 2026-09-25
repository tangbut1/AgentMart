/** 到手价拆解与优惠叠加。
 *
 *  锁的是四条原则：无条件才算确定价、条件性只进潜在价、无法核实两边都不进、
 *  同组互斥取最优。以及「金额相同取条件更宽松的，再相同取先出现的」这条
 *  与后端 max(...) 完全一致的平手规则。
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { rational } from "../core/money.ts";
import type { Discount } from "../core/model.ts";
import { computePriceBreakdown, definiteDiscount, potentialDiscount, resolvedAmount } from "../core/pricing.ts";

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

describe("resolvedAmount", () => {
  it("固定金额原样返回", () => {
    assert.equal(resolvedAmount(discount({ amount: 2000 }), 100000), 2000);
  });

  it("百分比按基础价折算，银行家舍入", () => {
    // 5.00 元 × 8.5 折 = 0.425 → 0.42（不是 0.43）
    assert.equal(resolvedAmount(discount({ percent: rational("8.5") }), 500), 42);
  });

  it("封顶生效", () => {
    const capped = discount({ percent: rational("50"), max_amount: 1000 });
    assert.equal(resolvedAmount(capped, 100000), 1000);
  });

  it("封顶不生效时按比例", () => {
    const capped = discount({ percent: rational("50"), max_amount: 60000 });
    assert.equal(resolvedAmount(capped, 100000), 50000);
  });
});

describe("computePriceBreakdown 分层", () => {
  it("无条件抵扣只进确定价", () => {
    const result = computePriceBreakdown({
      list_price: 100000,
      shipping_fee: 0,
      discounts: [discount({ amount: 20000 })],
    });
    assert.equal(result.definite_total, 80000);
    assert.equal(result.potential_total, 80000);
    assert.equal(result.unverifiable_total, 0);
    assert.equal(definiteDiscount(result), 20000);
  });

  it("条件性抵扣只进潜在价，确定价不动", () => {
    const result = computePriceBreakdown({
      list_price: 100000,
      shipping_fee: 0,
      discounts: [discount({ amount: 20000, condition_kind: "conditional" })],
    });
    assert.equal(result.definite_total, 100000);
    assert.equal(result.potential_total, 80000);
    assert.equal(definiteDiscount(result), 0);
    assert.equal(potentialDiscount(result), 20000);
  });

  it("无法核实的抵扣两个价都不进，单独累计", () => {
    const result = computePriceBreakdown({
      list_price: 100000,
      shipping_fee: 0,
      discounts: [discount({ amount: 20000, condition_kind: "unverifiable" })],
    });
    assert.equal(result.definite_total, 100000);
    assert.equal(result.potential_total, 100000);
    assert.equal(result.unverifiable_total, 20000);
    assert.ok(result.notes.some((n) => n.includes("无法核实")));
  });

  it("以旧换新永远只作为条件性抵扣", () => {
    const result = computePriceBreakdown({
      list_price: 100000,
      shipping_fee: 0,
      discounts: [discount({ kind: "trade_in", amount: 30000 })],
    });
    assert.equal(result.definite_total, 100000);
    assert.equal(result.potential_total, 70000);
  });

  it("运费计入两个价，没有包邮优惠时给说明", () => {
    const result = computePriceBreakdown({ list_price: 100000, shipping_fee: 1200, discounts: [] });
    assert.equal(result.definite_total, 101200);
    assert.equal(result.potential_total, 101200);
    assert.ok(result.notes.some((n) => n.includes("含运费 ¥12.00")));
  });

  it("有包邮优惠时不再提示运费", () => {
    const result = computePriceBreakdown({
      list_price: 100000,
      shipping_fee: 1200,
      discounts: [discount({ kind: "free_shipping", amount: 0 })],
    });
    assert.ok(!result.notes.some((n) => n.includes("未找到包邮")));
  });

  it("抵扣超过标价时确定价可以为负，不偷偷截断", () => {
    const result = computePriceBreakdown({
      list_price: 9900,
      shipping_fee: 0,
      discounts: [discount({ amount: 20000 })],
    });
    assert.equal(result.definite_total, -10100);
  });

  it("真实商品上的演示抵扣不进任何合计，但行仍然列出", () => {
    const result = computePriceBreakdown({
      list_price: 100000,
      shipping_fee: 0,
      discounts: [discount({ amount: 20000, data_status: "demo" })],
      data_status: "real",
    });
    assert.equal(result.definite_total, 100000);
    assert.equal(result.lines.length, 1);
  });
});

describe("resolveStackable 互斥组", () => {
  it("同组取金额最高项，其余记进 notes", () => {
    const result = computePriceBreakdown({
      list_price: 100000,
      shipping_fee: 0,
      discounts: [
        discount({ label: "券A", amount: 5000, stack_group: "g1" }),
        discount({ label: "券B", amount: 15000, stack_group: "g1" }),
      ],
    });
    assert.equal(result.definite_total, 85000);
    assert.deepEqual(result.applied_groups, ["g1"]);
    assert.ok(result.notes.some((n) => n.includes("券A") && n.includes("互斥")));
  });

  it("金额相同取条件更宽松的（无条件胜过条件性）", () => {
    const result = computePriceBreakdown({
      list_price: 100000,
      shipping_fee: 0,
      discounts: [
        discount({ label: "条件券", amount: 15000, condition_kind: "conditional", stack_group: "g1" }),
        discount({ label: "无条件券", amount: 15000, condition_kind: "unconditional", stack_group: "g1" }),
      ],
    });
    // 先出现的是条件券，但无条件的那张更宽松，应当胜出
    assert.equal(result.definite_total, 85000);
    assert.equal(result.potential_total, 85000);
    assert.equal(result.lines[0].label, "无条件券");
  });

  it("金额和条件都相同时保留先出现的那一张（与后端 max 一致）", () => {
    const result = computePriceBreakdown({
      list_price: 100000,
      shipping_fee: 0,
      discounts: [
        discount({ label: "先出现的", amount: 15000, stack_group: "g1" }),
        discount({ label: "后出现的", amount: 15000, stack_group: "g1" }),
      ],
    });
    assert.equal(result.lines[0].label, "先出现的");
  });

  it("不同组可叠加", () => {
    const result = computePriceBreakdown({
      list_price: 100000,
      shipping_fee: 0,
      discounts: [
        discount({ amount: 5000, stack_group: "g1" }),
        discount({ amount: 3000, stack_group: "g2" }),
      ],
    });
    assert.equal(result.definite_total, 92000);
    assert.deepEqual(result.applied_groups, ["g1", "g2"]);
  });

  it("没有 stack_group 的优惠直接叠加，不参与互斥", () => {
    const result = computePriceBreakdown({
      list_price: 100000,
      shipping_fee: 0,
      discounts: [discount({ amount: 5000 }), discount({ amount: 3000 })],
    });
    assert.equal(result.definite_total, 92000);
    assert.deepEqual(result.applied_groups, []);
  });

  it("以旧换新不参与互斥组", () => {
    const result = computePriceBreakdown({
      list_price: 100000,
      shipping_fee: 0,
      discounts: [
        discount({ kind: "trade_in", amount: 20000, stack_group: "g1" }),
        discount({ amount: 5000, stack_group: "g1" }),
      ],
    });
    // 以旧换新单独作为条件性信息，固定券照常生效
    assert.equal(result.definite_total, 95000);
    assert.equal(result.potential_total, 75000);
  });

  it("组里只有一项时不产生互斥说明", () => {
    const result = computePriceBreakdown({
      list_price: 100000,
      shipping_fee: 0,
      discounts: [discount({ amount: 5000, stack_group: "only" })],
    });
    assert.ok(!result.notes.some((n) => n.includes("互斥")));
  });
});
