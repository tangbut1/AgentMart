/** 扩展内部的领域模型：与后端 app/domain/models.py 同构，但金额用整数分。
 *
 *  单独放一个文件是因为 pricing / offer / serialize 三个模块都要用它，
 *  而它们彼此之间又有依赖 —— 类型集中在一处就不会出现循环 import。
 */

import type { Cents, Rational } from "./money.ts";
import {
  DISCOUNT_LAYER_LABELS,
  type ConditionKind,
  type DataStatus,
  type DiscountKind,
  type DiscountLayer,
  type Platform,
  type PolicyCategory,
  type PolicyScope,
  type PriceCertainty,
  type ShopType,
} from "./enums.ts";

export interface Discount {
  kind: DiscountKind;
  label: string;
  /** 正数，表示可抵扣的金额（分） */
  amount: Cents;
  /** 百分比有理数；与 amount 二选一 */
  percent: Rational | null;
  condition: string;
  condition_kind: ConditionKind;
  /** 数据源显声明的互斥组名（API 版用） */
  stack_group: string | null;
  /** 归属层级。数据源没填时互斥判定退回 stack_group，两者都空则单独成池 */
  layer: DiscountLayer | null;
  /** 页面文案对应的确定性档位。双轨净价靠它区分公开轨和我的轨 */
  certainty: PriceCertainty | null;
  max_amount: Cents | null;
  region_limit: string | null;
  eligibility: string | null;
  source_url: string | null;
  data_status: DataStatus;
  note: string | null;
}

/** 互斥判定用的池键。显式声明的 stack_group 优先于推断出的层级。 */
export function discountLayerKey(discount: Discount): string {
  if (discount.stack_group) return discount.stack_group;
  if (discount.layer) return discount.layer;
  return "";
}

/** 池的中文名，用于向用户解释「为什么这张券没算进去」。 */
export function discountLayerLabel(discount: Discount): string {
  if (discount.stack_group) return discount.stack_group;
  if (discount.layer) return DISCOUNT_LAYER_LABELS[discount.layer];
  return "未分层";
}

export interface PriceLine {
  label: string;
  kind: DiscountKind;
  amount: Cents;
  condition_kind: ConditionKind;
  condition: string;
  source_url: string | null;
  data_status: DataStatus;
}

/** 可解释的到手价拆解。双轨净价见字段注释。 */
export interface PriceBreakdown {
  list_price: Cents;
  shipping_fee: Cents;
  lines: PriceLine[];
  definite_total: Cents;
  potential_total: Cents;
  unverifiable_total: Cents;
  applied_groups: string[];
  notes: string[];
  /** 公开轨：只算「谁来看都成立」的抵扣。跨平台比价用这一轨 */
  public_total: Cents;
  /** 我的轨：再加「页面显示本账号已可用」的券。等于 definite_total */
  account_total: Cents;
}

/** 公开轨被抵扣掉的部分（分）。 */
export function publicDiscount(breakdown: PriceBreakdown): Cents {
  return breakdown.list_price + breakdown.shipping_fee - breakdown.public_total;
}

/** 我的轨比公开轨便宜了多少 —— 账号权益带来的那部分（分）。
 *
 *  必须 ≥ 0：账号权益只会更便宜。真算出负数说明把不该进公开轨的抵扣
 *  算进去了，调用方应当当错误处理而不是展示出来。 */
export function accountGap(breakdown: PriceBreakdown): Cents {
  return breakdown.public_total - breakdown.account_total;
}

export interface Policy {
  scope: PolicyScope;
  category: PolicyCategory;
  title: string;
  summary: string;
  data_status: DataStatus;
}

export interface Offer {
  platform: Platform;
  platform_product_id: string;
  title: string;
  url: string;
  list_price: Cents;
  shop_name: string | null;
  shop_type: ShopType;
  sku_text: string | null;
  sales_text: string | null;
  shipping_fee: Cents;
  /** 页面"配送至"显示的地区（登录账号默认地址，未必是用户要送的地方） */
  region: string | null;
  discounts: Discount[];
  policies: Policy[];
  data_status: DataStatus;
  source: string;
  source_url: string | null;
  fetched_at: string | null;
  credibility: number;
  affiliate: boolean;
  match_confidence: number | null;
  match_notes: string[];
  /** 与组内基准规格的关系。matched / variant / unknown，由匹配层填 */
  sku_sync: "matched" | "variant" | "unknown";
}

export function offerId(offer: Offer): string {
  return `${offer.platform}:${offer.platform_product_id}`;
}
