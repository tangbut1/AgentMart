/** 扩展内部的领域模型：与后端 app/domain/models.py 同构，但金额用整数分。
 *
 *  单独放一个文件是因为 pricing / offer / serialize 三个模块都要用它，
 *  而它们彼此之间又有依赖 —— 类型集中在一处就不会出现循环 import。
 */

import type { Cents, Rational } from "./money.ts";
import type {
  ConditionKind,
  DataStatus,
  DiscountKind,
  Platform,
  PolicyCategory,
  PolicyScope,
  ShopType,
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
  stack_group: string | null;
  max_amount: Cents | null;
  region_limit: string | null;
  eligibility: string | null;
  source_url: string | null;
  data_status: DataStatus;
  note: string | null;
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

export interface PriceBreakdown {
  list_price: Cents;
  shipping_fee: Cents;
  lines: PriceLine[];
  definite_total: Cents;
  potential_total: Cents;
  unverifiable_total: Cents;
  applied_groups: string[];
  notes: string[];
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
}

export function offerId(offer: Offer): string {
  return `${offer.platform}:${offer.platform_product_id}`;
}
