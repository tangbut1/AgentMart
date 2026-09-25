/** 领域模型 → 前端契约（OfferView / GroupView）。
 *
 *  与后端 app/browser/serialize.py 的 offer() / breakdown_dict() 逐字段对应。
 *  侧面板直接复用 frontend/src/components 下的 PurchaseCard 和 BrowserCompare，
 *  所以这里吐出来的对象必须和它们在网页版里收到的形状完全一致 —— 一个字段
 *  名对不上，组件就会渲染成空白而不是报错，那种 bug 很难发现。
 */

import type {
  BreakdownView,
  DiscountView,
  OfferView,
  PolicyView,
  PriceLineView,
  SubsidyScenarioView,
  SubsidyView,
  TrapView,
} from "../../src/lib/browserApi.ts";
import {
  CONDITION_KIND_LABELS,
  DATA_STATUS_LABELS,
  DISCOUNT_LAYER_LABELS,
  PLATFORM_LABELS,
  POLICY_CATEGORY_LABELS,
  POLICY_SCOPE_LABELS,
  PRICE_CERTAINTY_LABELS,
  SHOP_TYPE_LABELS,
  type ConditionKind,
  type PriceCertainty,
} from "./enums.ts";
import { formatMoney } from "./money.ts";
import type { Discount, Offer, PriceBreakdown, PriceLine, Policy } from "./model.ts";
import { accountGap, offerId, publicDiscount } from "./model.ts";
import { definiteDiscount, potentialDiscount } from "./pricing.ts";
import { couponTreeView } from "./couponTree.ts";
import { buildCouponTree } from "./couponTree.ts";
import { interpretSubsidyText, subsidyScenarios, subsidyFitLabel } from "./subsidy.ts";
import { detectTraps, summarizeTraps, trapBasisLabel, trapSeverityLabel, worstSeverity } from "./traps.ts";

function money(value: number | null | undefined): string {
  if (value === null || value === undefined) return "";
  return formatMoney(value);
}

function conditionLabel(kind: ConditionKind): string {
  return CONDITION_KIND_LABELS[kind];
}

/** 价格确定性：取该商品上已识别到的最高档位。
 *
 *  注意这只反映"我们在页面上看到了什么"，不等于用户最终能拿到这个价；
 *  最终到手价一律以平台结算页为准。 */
function certaintyOf(offer: Offer): OfferView["certainty"] {
  const rank: Record<PriceCertainty, number> = {
    page_public: 0,
    account_coupon: 1,
    conditional: 2,
    prepayment: 3,
    unverifiable: 4,
  };
  let best: PriceCertainty = "page_public";
  for (const discount of offer.discounts) {
    // 确定性等级是从 condition_kind 推出来的（后端把它写进 note 再解析回来，
    // 这里直接存了结构化的值，结论一致但不必依赖字符串匹配）
    const level: PriceCertainty =
      discount.condition_kind === "unconditional"
        ? "account_coupon"
        : discount.condition_kind === "conditional"
          ? "conditional"
          : "page_public";
    if (rank[level] > rank[best]) best = level;
  }
  if (offer.discounts.some((d) => d.condition_kind === "unverifiable")) {
    best = "unverifiable";
  }
  return {
    level: best,
    label: PRICE_CERTAINTY_LABELS[best],
    note: "最终到手价以平台结算页显示为准",
  };
}

function discountLine(line: PriceLine): PriceLineView {
  return {
    label: line.label,
    kind: line.kind,
    amount: money(line.amount),
    condition_kind: line.condition_kind,
    condition_kind_label: conditionLabel(line.condition_kind),
    condition: line.condition,
    source_url: line.source_url,
    data_status: line.data_status,
    data_status_label: DATA_STATUS_LABELS[line.data_status],
  };
}

function breakdownView(breakdown: PriceBreakdown): BreakdownView {
  return {
    list_price: money(breakdown.list_price),
    shipping_fee: money(breakdown.shipping_fee),
    definite_total: money(breakdown.definite_total),
    potential_total: money(breakdown.potential_total),
    unverifiable_total: money(breakdown.unverifiable_total),
    definite_discount: money(definiteDiscount(breakdown)),
    potential_discount: money(potentialDiscount(breakdown)),
    public_total: money(breakdown.public_total),
    public_discount: money(publicDiscount(breakdown)),
    account_total: money(breakdown.account_total),
    account_gap: money(accountGap(breakdown)),
    lines: breakdown.lines.map(discountLine),
    applied_groups: [...breakdown.applied_groups],
    notes: [...breakdown.notes],
  };
}

function discountView(discount: Discount): DiscountView {
  // 与后端一致：percent 为 0 时按 None 处理，不在界面上显示一个"0%"的优惠
  const percent =
    discount.percent !== null && discount.percent.num !== 0 ? discount.percent.text : null;
  return {
    kind: discount.kind,
    label: discount.label,
    amount: money(discount.amount),
    percent,
    condition: discount.condition,
    condition_kind: discount.condition_kind,
    condition_kind_label: conditionLabel(discount.condition_kind),
    layer: discount.layer,
    layer_label: discount.layer ? DISCOUNT_LAYER_LABELS[discount.layer] : null,
    certainty: discount.certainty,
    region_limit: discount.region_limit,
    eligibility: discount.eligibility,
    source_url: discount.source_url,
    verified_at: null,
    data_status: discount.data_status,
    note: discount.note,
  };
}

function policyView(policy: Policy): PolicyView {
  return {
    scope: policy.scope,
    scope_label: POLICY_SCOPE_LABELS[policy.scope],
    category: policy.category,
    category_label: POLICY_CATEGORY_LABELS[policy.category],
    title: policy.title,
    summary: policy.summary,
    data_status: policy.data_status,
  };
}

function trapView(trap: ReturnType<typeof detectTraps>[number]): TrapView {
  return {
    kind: trap.kind,
    label: trap.label,
    severity: trap.severity,
    severity_label: trapSeverityLabel(trap.severity),
    detail: trap.detail,
    evidence: trap.evidence,
    question: trap.question,
    basis: trap.basis,
    basis_label: trapBasisLabel(trap.basis),
  };
}

export interface SerializeOptions {
  /** 用户自己填写的收货地，只用于判断补贴文案的地区限制对不上对得上 */
  userRegion?: string | null;
}

export function offerView(
  offer: Offer,
  breakdown: PriceBreakdown,
  options: SerializeOptions = {},
): OfferView {
  const traps = detectTraps({
    policy_texts: offer.policies.map((p) => p.title),
    coupon_texts: offer.discounts.map((d) => d.label),
    sku_text: offer.sku_text ?? "",
    title: offer.title,
  });

  let subsidy: SubsidyView | null = null;
  // 收货地优先用用户自己填的；没填才退到页面"配送至"，并且标明出处 ——
  // 那个地址是登录账号的默认地址，未必是用户真正要送的地方。
  let region = (options.userRegion ?? "").trim() || null;
  let regionSource: "user" | "page" = "user";
  if (!region && (offer.region ?? "").trim()) {
    region = (offer.region ?? "").trim();
    regionSource = "page";
  }
  for (const entry of offer.discounts) {
    if (entry.kind !== "subsidy") continue;
    const reading = interpretSubsidyText(entry.label, region);
    if (reading === null) continue;
    const scenarios = subsidyScenarios(breakdown.definite_total, reading);
    subsidy = {
      raw_text: reading.raw_text,
      percent: reading.percent === null ? null : reading.percent.text,
      amount: reading.amount_text === null ? null : reading.amount_text,
      region_limit: reading.region_limit,
      user_region: reading.user_region,
      fit: reading.fit,
      fit_label: subsidyFitLabel(reading.fit),
      reason: reading.reason,
      questions: [...reading.questions],
      region_source: regionSource,
      scenarios: scenarios
        ? ({
            with_subsidy: scenarios.with_subsidy === null ? null : money(scenarios.with_subsidy),
            without_subsidy: money(scenarios.without_subsidy),
            note: scenarios.note,
          } satisfies SubsidyScenarioView)
        : null,
    };
    break;
  }

  return {
    id: offerId(offer),
    platform: offer.platform,
    platform_label: PLATFORM_LABELS[offer.platform],
    title: offer.title,
    url: offer.url,
    source_url: offer.source_url || offer.url,
    shop_name: offer.shop_name,
    shop_type: offer.shop_type,
    shop_type_label: SHOP_TYPE_LABELS[offer.shop_type],
    sku_text: offer.sku_text,
    sales_text: offer.sales_text,
    list_price: money(offer.list_price),
    shipping_fee: money(offer.shipping_fee),
    discounts: offer.discounts.map(discountView),
    policies: offer.policies.map(policyView),
    traps: traps.map(trapView),
    trap_summary: summarizeTraps(traps),
    worst_trap_severity: worstSeverity(traps),
    subsidy,
    breakdown: breakdownView(breakdown),
    coupon_tree: couponTreeView(buildCouponTree(offer, breakdown)),
    data_status: offer.data_status,
    data_status_label: DATA_STATUS_LABELS[offer.data_status],
    source: offer.source,
    fetched_at: offer.fetched_at,
    verified_at: null,
    credibility: offer.credibility,
    affiliate: offer.affiliate,
    certainty: certaintyOf(offer),
    is_demo: false,
    match_confidence: offer.match_confidence,
    match_notes: [...offer.match_notes],
  };
}
