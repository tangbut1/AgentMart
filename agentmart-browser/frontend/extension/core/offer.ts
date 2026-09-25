/** 页面字段 → 领域 Offer。
 *
 *  与后端 app/browser/extract.py 的 build_offer 对应。内容脚本抽到的原始
 *  字段先经过这里，再交给 pricing / traps / subsidy 三个模块。
 *
 *  抽不到的字段一律留空并记进 problems，由界面展示 —— 不用常见值填充。
 */

import { formatMoney, parseMoney, rational } from "./money.ts";
import type { DataStatus, Platform, ShopType } from "./enums.ts";
import { classifyShop, certaintyToCondition, extractPolicies, interpretCouponText } from "./discount.ts";
import type { Discount, Offer, Policy } from "./model.ts";
import { offerId } from "./model.ts";
import { certaintyLabel } from "./enums.ts";
import { truncate } from "./text.ts";

/** 内容脚本抽取返回的原始字段。字段名与后端 PageFields.from_js 一致。 */
export interface PageFields {
  url: string;
  title?: string | null;
  priceText?: string | null;
  priceSource?: "dom" | "vision";
  shopName?: string | null;
  selfOperatedHint?: boolean;
  skuText?: string | null;
  couponTexts?: string[];
  policyTexts?: string[];
  regionText?: string | null;
  salesText?: string | null;
  evidence?: Record<string, string>;
  fetchedAt?: string | null;
}

export interface BuildOfferResult {
  offer: Offer;
  problems: string[];
}

function productIdFromUrl(url: string): string | null {
  const patterns = [/[?&]id=(\d{5,})/, /\/item[/.]?(\d{5,})/, /(\d{10,})/];
  for (const pattern of patterns) {
    const match = url.match(pattern);
    if (match) return match[1];
  }
  return null;
}

/** 扩展里数据只可能来自用户此刻正在看的真实平台页面。
 *
 *  用「百分之一」为单位的整数累加，不用浮点连加。Python 那边是
 *  0.4+0.25+0.15+0.1 连续相加再 round(...,2)，在「认识店铺、无证据、
 *  价格来自截图」这一种组合下会得到 0.7000000000000001；这里按整数算，
 *  同一种组合得到的就是数学上该有的 0.7。一致性测试对 credibility 用
 *  1e-9 的容差比对，原因就是这个，不是漏改。 */
function credibility(shopType: ShopType, hasEvidence: boolean, vision: boolean): number {
  let score = 40 + 25; // REAL_PLATFORM_PAGE
  if (shopType !== "unknown") score += 15;
  if (hasEvidence) score += 10;
  if (vision) score -= 10;
  return Math.min(100, score) / 100;
}

export function buildOffer(
  platform: Platform,
  fields: PageFields,
  options: { sourceLabel: string; fetchedAt?: string | null; affiliate?: boolean } = {
    sourceLabel: "side-panel",
  },
): BuildOfferResult {
  const problems: string[] = [];
  const url = fields.url ?? "";
  const listPrice = parseMoney(fields.priceText ?? null);
  if (listPrice === null) {
    problems.push("未能从页面确定价格（无价格证据）");
  }

  const shop = classifyShop(fields.shopName ?? null, fields.selfOperatedHint === true);
  if (shop.shop_type === "unknown") {
    problems.push("未能确认店铺类型");
  }

  const priceSource = fields.priceSource ?? "dom";
  const discounts: Discount[] = [];
  for (const text of fields.couponTexts ?? []) {
    const reading = interpretCouponText(text);
    if (reading === null) continue;
    let condition = certaintyToCondition(reading.certainty);
    let reason = reading.reason;
    // 门槛检查：已领取但商品价格没到门槛，本单就用不上，
    // 必须从"确定可用"下调为"满足条件才成立"。
    // 门槛原文照抄页面写法（"100.5" 不会变成 "100.50"），页面价是已经
    // 量化过的两位小数 —— 两边都和 Python 的 Decimal 展示一致。
    if (reading.threshold !== null && listPrice !== null && listPrice < reading.threshold) {
      condition = "conditional";
      reason =
        `该优惠需满 ${reading.threshold_text} 元，本商品页面价 ${formatMoney(listPrice)} 元未达门槛，` +
        "本单不适用";
    }
    discounts.push({
      kind: reading.kind,
      label: truncate(reading.raw_text, 40),
      amount: reading.amount ?? 0,
      percent: reading.percent_text ? rational(reading.percent_text) : null,
      condition: reason,
      condition_kind: condition,
      stack_group: null,
      max_amount: null,
      region_limit: null,
      eligibility: null,
      source_url: url || null,
      data_status: "real",
      note: `确定性：${certaintyLabel(condition)}；原文：${reading.raw_text}`,
    });
    if (reading.threshold !== null) {
      discounts[discounts.length - 1].condition = `${reason}；门槛：满 ${reading.threshold_text} 元`;
    }
  }

  const policies: Policy[] = extractPolicies(fields.policyTexts ?? []).map((policy) => ({
    scope: policy.scope,
    category: policy.category,
    title: policy.title,
    summary: policy.summary,
    data_status: "real" as DataStatus,
  }));

  const productId = productIdFromUrl(url) ?? url.slice(-32);
  // 价格来自截图识别、没有页面文本字段交叉核对时，数据状态降级为
  // 「待核实」：它仍然会被展示，但绝不被当成已核验的价格。
  // 扩展的内容脚本只抽 DOM 字段，走不到 vision 这一条；保留它是为了和
  // 后端 build_offer 的字段契约保持一致（ Parity 测试会覆盖到）。
  let dataStatus: DataStatus = "real";
  if (priceSource === "vision") {
    dataStatus = "unverified";
    const shown = listPrice === null ? "" : `价格 ${formatMoney(listPrice)} `;
    problems.push(
      `${shown}来自截图识别，未经页面文本字段交叉核对，` +
        "已标记为待核实，请以平台结算页为准",
    );
  }

  const offer: Offer = {
    platform,
    platform_product_id: productId,
    title: fields.title || url,
    url,
    list_price: listPrice ?? 0,
    shipping_fee: 0,
    shop_name: fields.shopName ?? null,
    shop_type: shop.shop_type,
    sku_text: fields.skuText ?? null,
    sales_text: fields.salesText ?? null,
    // 页面"配送至"的地址：登录账号的默认地址，不一定和用户要送的地方一致，
    // 所以单独放着，不覆盖用户自己填的收货地。
    region: fields.regionText ?? null,
    discounts,
    policies,
    data_status: dataStatus,
    source: `browser:${options.sourceLabel}`,
    source_url: url || null,
    fetched_at: options.fetchedAt ?? null,
    credibility: credibility(
      shop.shop_type,
      Object.keys(fields.evidence ?? {}).length > 0,
      priceSource === "vision",
    ),    affiliate: options.affiliate === true,
    match_confidence: null,
    match_notes: [],
  };

  if (listPrice === null) {
    problems.push("该链接已记录，但价格缺失，不参与价格比较");
  }
  return { offer, problems };
}

export { offerId };
