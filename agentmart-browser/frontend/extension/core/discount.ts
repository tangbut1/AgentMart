/** 页面优惠/政策文案的解释规则。
 *
 * 与后端 app/browser/extract.py 的 interpret_coupon_text /
 * classify_shop / extract_policies 逐条对应。两侧对同一段文案必须得出
 * 同一个结论，所以这里的正则、关键词表、判断顺序都照抄，只把 Decimal
 * 换成整数分。
 *
 * 一条总规矩：**看不懂就不猜**。文案里没有可量化金额时，要么明确标成
 * 「无法核实」，要么不当成优惠 —— 绝不用常见值补一个数出来。
 */

import type { Cents } from "./money.ts";
import { decimalStr, decimalToCents } from "./money.ts";
import type { ConditionKind, DiscountKind, PolicyCategory, PolicyScope, ShopType } from "./enums.ts";
import { truncate } from "./text.ts";

// ─── 关键词表 ──────────────────────────────────────────────────

/** 明确表示"已领取/已可用" —— 必须优先于动作词判断：
 *  "已领取"里含"领取"，不能当成"还需要去领"。 */
const CLAIMED_HINTS = ["已领取", "已领", "已获得", "已入手", "已享", "券后", "优惠后"];
const AVAILABLE_HINTS = ["可用", "立减"];
const ACTION_HINTS = [
  "去领取",
  "立即领取",
  "点击领取",
  "待领取",
  "需领取",
  "去使用",
  "立即抢",
  "抢券",
];
const UNAVAILABLE_HINTS = ["已抢光", "已过期", "不可用", "已失效", "暂不可用"];
const SUBSIDY_HINTS = [
  "国补",
  "国家补贴",
  "政府补贴",
  "以旧换新",
  "换新补贴",
  "平台补贴",
  "百亿补贴",
];
const PAYMENT_HINTS = [
  "支付立减",
  "银行卡",
  "花呗",
  "白条",
  "微信支付",
  "支付宝",
  "分期免息",
];

const THRESHOLD_RE = /满\s*([0-9]+(?:\.[0-9]+)?)\s*(?:元)?\s*减\s*([0-9]+(?:\.[0-9]+)?)/;
const OFF_RE = /(?:减|优惠|立减|券)\s*([0-9]+(?:\.[0-9]{1,2})?)\s*元/;
const DISCOUNT_RE = /([0-9]+(?:\.[0-9]+)?)\s*折/;

function anyHint(text: string, hints: readonly string[]): boolean {
  return hints.some((hint) => text.includes(hint));
}

// ─── 优惠解释 ──────────────────────────────────────────────────

export interface CouponReading {
  raw_text: string;
  kind: DiscountKind;
  amount: Cents | null;
  /** 原始百分比文本，如 "8.5"；用于展示，也用于精确计算 */
  percent_text: string | null;
  threshold: Cents | null;
  /** 门槛原文，如 "100" 或 "100.5"；展示用，不做两位小数补齐 */
  threshold_text: string | null;
  certainty: "page_public" | "account_coupon" | "conditional" | "prepayment" | "unverifiable";
  reason: string;
}

/** 解释一条优惠文案。看不懂就返回 null（不猜）。 */
export function interpretCouponText(text: string): CouponReading | null {
  const raw = (text ?? "").trim();
  if (raw.length < 3) return null;

  let threshold: Cents | null = null;
  let thresholdText: string | null = null;
  let amount: Cents | null = null;
  let percentText: string | null = null;

  const thresholdMatch = raw.match(THRESHOLD_RE);
  if (thresholdMatch) {
    thresholdText = decimalStr(thresholdMatch[1]);
    threshold = decimalToCents(thresholdMatch[1]);
    amount = decimalToCents(thresholdMatch[2]);
  } else {
    const offMatch = raw.match(OFF_RE);
    if (offMatch) {
      amount = decimalToCents(offMatch[1]);
    } else {
      const discountMatch = raw.match(DISCOUNT_RE);
      if (discountMatch) percentText = discountMatch[1];
    }
  }

  if (amount === null && percentText === null) {
    // 补贴类文案常常只写比例或只写"有补贴"，没有可量化金额。
    // 仍然要把它列出来（用户需要知道有这回事），但明确标为无法核实。
    if (anyHint(raw, SUBSIDY_HINTS)) {
      return {
        raw_text: raw,
        kind: "subsidy",
        amount: null,
        percent_text: null,
        threshold: null,
        threshold_text: null,
        certainty: "unverifiable",
        reason: "页面提到补贴但未给出可核实金额，资格需本人核实",
      };
    }
    return null; // 文案里没有可量化金额，不当成优惠
  }

  const kind: DiscountKind = anyHint(raw, SUBSIDY_HINTS)
    ? "subsidy"
    : anyHint(raw, PAYMENT_HINTS)
      ? "payment"
      : "coupon";

  if (anyHint(raw, UNAVAILABLE_HINTS)) {
    return {
      raw_text: raw,
      kind,
      amount,
      percent_text: percentText,
      threshold,
      threshold_text: thresholdText,
      certainty: "unverifiable",
      reason: "页面显示该优惠当前不可用",
    };
  }

  if (anyHint(raw, SUBSIDY_HINTS)) {
    // 补贴资格（地区/品类/售价门槛/是否已领取）几乎无法从页面确认
    return {
      raw_text: raw,
      kind,
      amount,
      percent_text: percentText,
      threshold,
      threshold_text: thresholdText,
      certainty: "unverifiable",
      reason: "补贴资格需本人核实（地区/品类/售价门槛/是否已领取）",
    };
  }

  if (
    anyHint(raw, CLAIMED_HINTS) ||
    (anyHint(raw, AVAILABLE_HINTS) && !anyHint(raw, ACTION_HINTS))
  ) {
    return {
      raw_text: raw,
      kind,
      amount,
      percent_text: percentText,
      threshold,
      threshold_text: thresholdText,
      certainty: "account_coupon",
      reason: "页面显示该优惠已可用于当前商品",
    };
  }

  return {
    raw_text: raw,
    kind,
    amount,
    percent_text: percentText,
    threshold,
    threshold_text: thresholdText,
    certainty: "conditional",
    reason: "页面显示可领/需满足条件，适用范围与叠加关系待确认",
  };
}

export function certaintyToCondition(
  certainty: CouponReading["certainty"],
): ConditionKind {
  switch (certainty) {
    case "account_coupon":
    case "page_public":
      return "unconditional";
    case "conditional":
    case "prepayment":
      return "conditional";
    default:
      return "unverifiable";
  }
}

// ─── 店铺类型 ──────────────────────────────────────────────────

export interface ShopReading {
  shop_type: ShopType;
  reason: string;
}

/** 店铺类型只在页面明示时标注，否则 UNKNOWN。 */
export function classifyShop(
  shopName: string | null | undefined,
  selfOperatedHint: boolean,
): ShopReading {
  const name = (shopName ?? "").trim();
  if (selfOperatedHint || name.includes("自营")) {
    return { shop_type: "self_operated", reason: "页面标注自营" };
  }
  if (name.includes("官方旗舰店") || name.includes("官方旗舰")) {
    return { shop_type: "official_flagship", reason: "店铺名含官方旗舰店" };
  }
  if (name.includes("旗舰店") || name.includes("旗舰")) {
    return { shop_type: "flagship", reason: "店铺名含旗舰店" };
  }
  if (name.includes("专营店") || name.includes("授权")) {
    return { shop_type: "authorized", reason: "店铺名含专营/授权" };
  }
  if (name) return { shop_type: "third_party", reason: "按普通店铺处理" };
  return { shop_type: "unknown", reason: "页面未显示店铺名称" };
}

// ─── 政策 ──────────────────────────────────────────────────────

/** 否定式退换限制。必须**先于**下面的肯定式模式判断：
 *  "激活后不支持7天无理由"里同时含"激活"和"无理由"，如果按肯定式归类，
 *  用户会在「售后与保障」里看到一条看起来像保护的限制，正好被套路。 */
const NO_RETURN_RESTRICTION_RE = new RegExp(
  [
    "不支持\\s*(?:七天|7天)?\\s*无理由",
    "不可\\s*(?:七天|7天)?\\s*无理由",
    "不退不换|不予退换|不支持退换",
    "(?:激活|拆封|拆包|开机)[^。；，,\\n]{0,10}(?:不支持|不可|不予|无法|不能)[^。；，,\\n]{0,8}(?:退货|退款|退换|无理由)",
    "(?:特价|清仓|尾货|处理品|样品|二手|翻新)[^。；，,\\n]{0,12}(?:不退不换|不予退换|不支持|不可退|不可换|无法退|无法换)",
  ].join("|"),
);

const POLICY_PATTERNS: ReadonlyArray<[RegExp, PolicyCategory]> = [
  [/7天|七天|无理由/, "after_sales"],
  [/退换|退货|换货/, "after_sales"],
  [/保修|质保|全国联保/, "warranty"],
  [/包邮|免运费|运费险/, "shipping"],
  [/正品|假一赔|官方质检/, "authenticity"],
  [/发票|开票/, "invoice"],
  [/价保|价格保护/, "price_protection"],
];

export interface PolicyReading {
  scope: PolicyScope;
  category: PolicyCategory;
  title: string;
  summary: string;
}

export function extractPolicies(texts: readonly string[]): PolicyReading[] {
  const seen = new Set<string>();
  const policies: PolicyReading[] = [];
  for (const text of texts) {
    if (!text) continue;
    // 否定式优先：同一条文案里"不支持无理由"和"无理由"都会命中，
    // 归成限制才对用户有用。
    let category: PolicyCategory | null = null;
    if (NO_RETURN_RESTRICTION_RE.test(text)) {
      category = "return_restriction";
    } else {
      for (const [pattern, candidate] of POLICY_PATTERNS) {
        if (pattern.test(text)) {
          category = candidate;
          break;
        }
      }
      if (category === null) continue;
    }
    const key = `${category}\u0000${text}`;
    if (seen.has(key)) continue;
    seen.add(key);
    policies.push({
      scope: "product_page_promise",
      category,
      title: truncate(text, 40),
      summary: truncate(text, 200),
    });
  }
  return policies;
}
