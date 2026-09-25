/** 优惠券树：把一件商品上的优惠按归属层级摊开，讲清楚每一层发生了什么。
 *
 *  与后端 app/domain/coupontree.py 逐字段对应。为什么要一棵树而不是一张表：
 *  用户真正想问的是「这个价怎么来的、我能不能拿到」。扁平列表答不了 ——
 *  它分不出「两张券互斥只能选一张」和「两张券都在减」，也分不出「谁来看
 *  都成立」和「只有你登录了才有」。
 *
 *  层键优先用 DiscountLayer；数据源只给了 stack_group 时（API 版）用组名
 *  本身当层键，排在已知层级之后。
 */

import {
  CONDITION_KIND_LABELS,
  DISCOUNT_LAYERS,
  DISCOUNT_LAYER_LABELS,
  PRICE_CERTAINTY_LABELS,
  type ConditionKind,
  type DataStatus,
  type DiscountKind,
  type DiscountLayer,
  type PriceCertainty,
} from "./enums.ts";
import { formatMoney, type Cents } from "./money.ts";
import type { CouponTreeView } from "../../src/lib/browserApi.ts";
import type { Discount, Offer, PriceBreakdown } from "./model.ts";
import { discountLayerKey, discountLayerLabel } from "./model.ts";
import { isPagePublic, resolveStackable, resolvedAmount } from "./pricing.ts";

const LAYER_ORDER: readonly string[] = DISCOUNT_LAYERS;
const UNKNOWN_LAYER_ORDER = LAYER_ORDER.length;

export interface TreeEntry {
  label: string;
  kind: DiscountKind;
  amount: Cents;
  condition: string;
  condition_kind: ConditionKind;
  certainty: PriceCertainty | null;
  source_url: string | null;
  data_status: DataStatus;
  /** 这一条是真正参与计算的，还是被同层互斥挤掉的 */
  counted: boolean;
  /** 被挤掉时，挤掉它的是哪一条 */
  beaten_by: string | null;
}

export interface TreeLayer {
  key: string;
  label: string;
  order: number;
  entries: TreeEntry[];
  /** 这一层在公开轨上抵掉了多少（分） */
  public_amount: Cents;
  /** 这一层在我的轨上抵掉了多少（分） */
  account_amount: Cents;
}

export interface CouponTree {
  layers: TreeLayer[];
  public_total: Cents;
  account_total: Cents;
  potential_total: Cents;
  unverifiable_total: Cents;
  /** 叠加关系是按层级推断的（inferred）还是数据源写明的（evidenced） */
  stacking_confidence: "inferred" | "evidenced";
  notes: string[];
}
/** 我的轨比公开轨便宜了多少 —— 账号权益带来的那部分（分）。 */
export function accountGap(tree: CouponTree): Cents {
  return tree.public_total - tree.account_total;
}

/** 真正减掉了钱的层。用来判断要不要提示「叠加关系是推断的」。 */
export function contributingLayers(tree: CouponTree): string[] {
  return tree.layers
    .filter((layer) => layer.public_amount > 0 || layer.account_amount > 0)
    .map((layer) => layer.key);
}

/** 这项优惠落在哪一层：[键, 中文名, 排序位]。 */
function layerSlot(discount: Discount): [string, string, number] {
  if (discount.layer) {
    return [
      discount.layer,
      DISCOUNT_LAYER_LABELS[discount.layer as DiscountLayer],
      LAYER_ORDER.indexOf(discount.layer),
    ];
  }
  if (discount.stack_group) {
    // 数据源只给了组名：组名就是层名，排在已知层级之后
    return [discount.stack_group, discountLayerLabel(discount), UNKNOWN_LAYER_ORDER];
  }
  return ["product", DISCOUNT_LAYER_LABELS.product, LAYER_ORDER.indexOf("product")];
}

export function buildCouponTree(offer: Offer, breakdown: PriceBreakdown): CouponTree {
  const base = offer.list_price;
  const { applied, excluded } = resolveStackable(offer.discounts, base);
  const appliedIds = new Set(applied);

  // 被挤掉的优惠要说明是被谁挤掉的。同池的胜者在 applied 里，按池键找回。
  const beatenBy = new Map<Discount, string>();
  for (const [, dropped] of excluded) {
    for (const discount of dropped) {
      const key = discountLayerKey(discount);
      const winner = applied.find((candidate) => discountLayerKey(candidate) === key);
      beatenBy.set(discount, winner ? winner.label : "");
    }
  }

  const layers = new Map<string, TreeLayer>();
  for (const discount of offer.discounts) {
    const [key, label, order] = layerSlot(discount);
    let layer = layers.get(key);
    if (!layer) {
      layer = { key, label, order, entries: [], public_amount: 0, account_amount: 0 };
      layers.set(key, layer);
    }
    layer.entries.push({
      label: discount.label,
      kind: discount.kind,
      amount: resolvedAmount(discount, base),
      condition: discount.condition,
      condition_kind: discount.condition_kind,
      certainty: discount.certainty,
      source_url: discount.source_url,
      data_status: discount.data_status,
      counted: appliedIds.has(discount),
      beaten_by: beatenBy.get(discount) ?? null,
    });
  }

  for (const discount of applied) {
    const [key] = layerSlot(discount);
    const layer = layers.get(key);
    if (!layer) continue;
    if (discount.data_status === "demo") continue;
    if (discount.condition_kind === "unconditional" && discount.kind !== "trade_in") {
      if (isPagePublic(discount)) layer.public_amount += resolvedAmount(discount, base);
      else layer.account_amount += resolvedAmount(discount, base);
    }
  }

  return {
    layers: [...layers.values()].sort((a, b) => a.order - b.order),
    public_total: breakdown.public_total,
    account_total: breakdown.account_total,
    potential_total: breakdown.potential_total,
    unverifiable_total: breakdown.unverifiable_total,
    stacking_confidence: offer.discounts.some((d) => d.stack_group)
      ? "evidenced"
      : "inferred",
    notes: [...breakdown.notes],
  };
}

// ─── 序列化成前端契约（与后端 coupontree.to_dict 对应） ─────────
//
// 视图类型直接用 src/lib/browserApi.ts 里那一份，不在这里重复声明 ——
// 重复声明就会出现「两边各改一半」的漂移，而这种漂移在运行时不报错，
// 只是组件渲染成空白。

export function couponTreeView(tree: CouponTree): CouponTreeView {
  return {
    layers: tree.layers.map((layer) => ({
      layer: layer.key,
      layer_label: layer.label,
      entries: layer.entries.map((entry) => ({
        label: entry.label,
        kind: entry.kind,
        amount: formatMoney(entry.amount),
        condition: entry.condition,
        condition_kind: entry.condition_kind,
        condition_kind_label: CONDITION_KIND_LABELS[entry.condition_kind],
        certainty: entry.certainty,
        certainty_label: entry.certainty ? PRICE_CERTAINTY_LABELS[entry.certainty] : null,
        source_url: entry.source_url,
        data_status: entry.data_status,
        counted: entry.counted,
        beaten_by: entry.beaten_by,
      })),
      public_amount: formatMoney(layer.public_amount),
      account_amount: formatMoney(layer.account_amount),
    })),
    public_total: formatMoney(tree.public_total),
    account_total: formatMoney(tree.account_total),
    potential_total: formatMoney(tree.potential_total),
    unverifiable_total: formatMoney(tree.unverifiable_total),
    account_gap: formatMoney(accountGap(tree)),
    stacking_confidence: tree.stacking_confidence,
    notes: [...tree.notes],
  };
}
