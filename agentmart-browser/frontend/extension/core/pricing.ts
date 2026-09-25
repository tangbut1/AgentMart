/** 优惠叠加与到手价拆解。
 *
 *  与后端 app/domain/pricing.py + app/domain/stacking.py 对应。四条原则照抄：
 *
 *  1. 只有「无条件成立」的抵扣才计入确定到手价（definite_total）；
 *  2. 「满足条件才成立」的计入潜在到手价（potential_total）；
 *  3. 「无法核实」的单独列示，绝不计入任何到手价；
 *  4. 同一 stack_group 内互斥，取金额最高项（金额相同取条件更宽松的）。
 */

import { divRoundHalfEven, formatMoney, type Cents } from "./money.ts";
import type { DataStatus } from "./enums.ts";
import type { Discount, PriceBreakdown, PriceLine } from "./model.ts";

/** 按基础价计算实际抵扣额（处理百分比与封顶）。 */
export function resolvedAmount(discount: Discount, base: Cents): Cents {
  if (discount.percent) {
    const value = divRoundHalfEven(base * discount.percent.num, discount.percent.den * 100);
    if (discount.max_amount !== null) return Math.min(value, discount.max_amount);
    return value;
  }
  return discount.amount;
}

/** 同组内谁更优。判定顺序必须和后端 resolve_stackable 的 max(...) 完全一致：
 *  先比金额，再比「是否无条件成立」，两项都相同则保留先出现的那一项
 *  （Python 的 max 在键相等时取第一个，这里用「不更优」实现同一效果）。 */
function better(a: Discount, b: Discount, base: Cents): boolean {
  const byAmount = resolvedAmount(a, base) - resolvedAmount(b, base);
  if (byAmount !== 0) return byAmount > 0;
  if (a.condition_kind === "unconditional" !== (b.condition_kind === "unconditional")) {
    return a.condition_kind === "unconditional";
  }
  return false;
}

export interface StackResult {
  applied: Discount[];
  excluded: Array<[string, Discount[]]>;
}

/** 解析互斥组。以旧换新（trade_in）不参与互斥，单独作为条件性信息。 */
export function resolveStackable(discounts: readonly Discount[], base: Cents): StackResult {
  const groups = new Map<string, Discount[]>();
  const ungrouped: Discount[] = [];

  for (const discount of discounts) {
    if (discount.kind === "trade_in") {
      ungrouped.push(discount);
      continue;
    }
    if (discount.stack_group) {
      const bucket = groups.get(discount.stack_group);
      if (bucket) bucket.push(discount);
      else groups.set(discount.stack_group, [discount]);
    } else {
      ungrouped.push(discount);
    }
  }

  const applied: Discount[] = [...ungrouped];
  const excluded: Array<[string, Discount[]]> = [];

  for (const [group, members] of groups) {
    if (members.length === 1) {
      applied.push(members[0]);
      continue;
    }
    let best = members[0];
    for (const candidate of members.slice(1)) {
      if (better(candidate, best, base)) best = candidate;
    }
    applied.push(best);
    const dropped = members.filter((member) => member !== best);
    if (dropped.length > 0) excluded.push([group, dropped]);
  }
  return { applied, excluded };
}

function isFreeShipping(discount: Discount): boolean {
  return discount.kind === "free_shipping";
}

export function computePriceBreakdown(input: {
  list_price: Cents;
  shipping_fee: Cents;
  discounts: readonly Discount[];
  data_status?: DataStatus;
}): PriceBreakdown {
  const base = input.list_price;
  const breakdown: PriceBreakdown = {
    list_price: base,
    shipping_fee: input.shipping_fee,
    lines: [],
    definite_total: 0,
    potential_total: 0,
    unverifiable_total: 0,
    applied_groups: [],
    notes: [],
  };

  const { applied, excluded } = resolveStackable(input.discounts, base);
  breakdown.applied_groups = [
    ...new Set(applied.map((d) => d.stack_group).filter((g): g is string => !!g)),
  ].sort();
  for (const [group, dropped] of excluded) {
    breakdown.notes.push(
      `「${group}」组内优惠互斥，已取最优项，未计入：${dropped.map((d) => d.label).join("、")}`,
    );
  }

  let definite = base + input.shipping_fee;
  let potential = definite;
  let unverifiable = 0;

  for (const discount of applied) {
    const amount = resolvedAmount(discount, base);
    const line: PriceLine = {
      label: discount.label,
      kind: discount.kind,
      amount,
      condition_kind: discount.condition_kind,
      condition: discount.condition,
      source_url: discount.source_url,
      data_status: discount.data_status,
    };
    breakdown.lines.push(line);

    // 真实商品上的演示折扣不进入任何合计（防御性）；行仍然列出来，
    // 让用户看到「有这么一条，但它不算数」。
    if (discount.data_status === "demo" && (input.data_status ?? "real") !== "demo") continue;
    if (discount.condition_kind === "unconditional" && discount.kind !== "trade_in") {
      definite -= amount;
      potential -= amount;
    } else if (discount.kind === "trade_in" || discount.condition_kind === "conditional") {
      // 以旧换新是抵扣权益而非确定降价，永远只作为条件性抵扣
      potential -= amount;
    } else {
      unverifiable += amount;
    }
  }

  breakdown.definite_total = definite;
  breakdown.potential_total = potential;
  breakdown.unverifiable_total = unverifiable;

  if (input.shipping_fee > 0 && !applied.some(isFreeShipping)) {
    breakdown.notes.push(`含运费 ¥${formatMoney(input.shipping_fee)}，未找到包邮优惠信息`);
  }
  if (unverifiable > 0) {
    breakdown.notes.push("存在无法核实的优惠，未计入到手价；请以商品页面实时显示为准");
  }
  return breakdown;
}

/** 确定到手价里被抵扣掉的部分（分）。 */
export function definiteDiscount(breakdown: PriceBreakdown): Cents {
  return breakdown.list_price + breakdown.shipping_fee - breakdown.definite_total;
}

/** 潜在到手价里被抵扣掉的部分（分）。 */
export function potentialDiscount(breakdown: PriceBreakdown): Cents {
  return breakdown.list_price + breakdown.shipping_fee - breakdown.potential_total;
}
