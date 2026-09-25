/** 优惠叠加与到手价拆解。
 *
 *  与后端 app/domain/pricing.py + app/domain/stacking.py 对应。原则照抄：
 *
 *  1. 只有「无条件成立」的抵扣才计入确定到手价（definite_total）；
 *  2. 「满足条件才成立」的计入潜在到手价（potential_total）；
 *  3. 「无法核实」的单独列示，绝不计入任何到手价；
 *  4. 同一互斥池内只取金额最高项（池 = stack_group ?? layer）；
 *  5. 双轨净价：public_total 只算谁来看都成立的抵扣，account_total 再加
 *     页面显示本账号可用的券。跨平台比价必须用 public_total —— 否则一边
 *     算公开价一边算自己账号里的券，比出来的是账号差异不是商品差异。
 */

import { divRoundHalfEven, formatMoney, type Cents } from "./money.ts";
import type { DataStatus } from "./enums.ts";
import type { Discount, PriceBreakdown, PriceLine } from "./model.ts";
import { discountLayerKey, discountLayerLabel } from "./model.ts";

/** 未分层的优惠单独成池 —— 这是唯一安全的默认：层级不明就不能假设可叠加。 */
const UNGROUPED_KEY = "__ungrouped__";

function poolKey(discount: Discount): string {
  return discountLayerKey(discount) || UNGROUPED_KEY;
}

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
    const key = poolKey(discount);
    if (key !== UNGROUPED_KEY) {
      const bucket = groups.get(key);
      if (bucket) bucket.push(discount);
      else groups.set(key, [discount]);
    } else {
      ungrouped.push(discount);
    }
  }

  const applied: Discount[] = [...ungrouped];
  const excluded: Array<[string, Discount[]]> = [];

  for (const [, members] of groups) {
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
    if (dropped.length > 0) excluded.push([discountLayerLabel(members[0]), dropped]);
  }
  return { applied, excluded };
}

/** 这项抵扣是不是「谁来看都成立」。
 *
 *  只看确定性档位，不看 condition_kind：account_coupon 也是 unconditional，
 *  但它成立的前提是「你这个账号有这张券」，那不是公开的。certainty 没填时
 *  （API 版数据）按公开处理 —— 那边没有账号上下文，页面价就是公开价。 */
export function isPagePublic(discount: Discount): boolean {
  return discount.certainty === null || discount.certainty === "page_public";
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
    public_total: 0,
    account_total: 0,
  };

  const { applied, excluded } = resolveStackable(input.discounts, base);
  breakdown.applied_groups = [
    ...new Set(applied.map(discountLayerKey).filter((key): key is string => !!key)),
  ].sort();
  for (const [group, dropped] of excluded) {
    breakdown.notes.push(
      `「${group}」内优惠互斥，已取最优项，未计入：${dropped.map((d) => d.label).join("、")}`,
    );
  }

  let definite = base + input.shipping_fee;
  let potential = definite;
  let publicTotal = definite;
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
      if (isPagePublic(discount)) publicTotal -= amount;
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
  breakdown.public_total = publicTotal;
  breakdown.account_total = definite;

  if (input.shipping_fee > 0 && !applied.some(isFreeShipping)) {
    breakdown.notes.push(`含运费 ¥${formatMoney(input.shipping_fee)}，未找到包邮优惠信息`);
  }
  if (unverifiable > 0) {
    breakdown.notes.push("存在无法核实的优惠，未计入到手价；请以商品页面实时显示为准");
  }
  // 多个层级同时贡献了确定抵扣时，叠加关系是按层级推断的，页面没有逐一
  // 说明。这句话必须出现在用户看得到的地方。
  const contributingLayers = new Set(
    applied
      .filter(
        (d) =>
          discountLayerKey(d) &&
          d.condition_kind === "unconditional" &&
          d.kind !== "trade_in" &&
          d.data_status !== "demo",
      )
      .map(discountLayerKey),
  );
  if (contributingLayers.size > 1) {
    breakdown.notes.push(
      "多层优惠同时成立，能否叠加是按各优惠所属层级推断的，页面未逐一说明；最终可叠加项以平台结算页为准",
    );
  }
  const gap = breakdown.public_total - breakdown.account_total;
  if (gap > 0) {
    breakdown.notes.push(
      `其中 ¥${formatMoney(gap)} 来自您账号下已显示可用的优惠，未登录时拿不到`,
    );
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