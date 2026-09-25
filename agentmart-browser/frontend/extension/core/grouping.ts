/** 跨平台同款归组。
 *
 *  扩展侧的比对场景很窄：用户正在看 A 商品，想知道 B/C 平台同一款多少钱。
 *  所以这里只做**保守的文本匹配** —— 有共同的强型号特征才归为一组，
 *  否则单独列出来并说明「没认出来是同一款」，绝不为了凑一个对比表把两件
 *  不同的商品排在一起。
 *
 *  和后端 app/domain/matching.py 的区别要说清楚：那边跑在完整商品库上，
 *  能做品牌/规格/参数的多路归一；扩展只有标题和规格两段文本，所以这里的
 *  置信度上限更低，界面上也必须如实标注「跨平台匹配仅依据标题与规格文本」。
 */

import type { GroupView, OfferView } from "../../src/lib/browserApi.ts";
import { computePriceBreakdown } from "./pricing.ts";
import type { Offer } from "./model.ts";
import { modelTokens, sharedModelTokens } from "./modelTokens.ts";

// 转发出去，让 core/index.ts 的调用方继续从 grouping.ts 拿到这两个函数
export * from "./modelTokens.ts";

function tokensOf(offer: OfferView): string[] {
  return modelTokens(`${offer.title} ${offer.sku_text ?? ""}`);
}

export interface MatchReading {
  shared: string[];
  confidence: number;
  warnings: string[];
}

/** 判断候选商品和主角商品是不是同一款。认不出来就不说它们是。 */
export function matchOffer(primary: OfferView, candidate: OfferView): MatchReading {
  const primaryTokens = tokensOf(primary);
  const candidateTokens = tokensOf(candidate);
  const shared = sharedModelTokens(primaryTokens, candidateTokens);
  const warnings: string[] = [];

  if (primaryTokens.length === 0 || candidateTokens.length === 0) {
    warnings.push("有一侧标题/规格里认不出型号，无法确认是不是同一款");
    return { shared, confidence: 0, warnings };
  }
  if (shared.length === 0) {
    return { shared, confidence: 0, warnings };
  }

  const union = new Set([...primaryTokens, ...candidateTokens]);
  const confidence = Math.round((shared.length / union.size) * 100) / 100;
  // 只要有一侧还有没对上的型号 token，就不能当成「确认同款」：
  // "WH-1000XM5 与 WH-1000XM4 对比" 这种页面会把另一代的型号一起带出来。
  if (confidence < 1) {
    warnings.push("型号只有部分重合，规格可能不同，请以两边商品页为准");
  }
  return { shared, confidence, warnings };
}

export interface CompareResult {
  groups: GroupView[];
  /** 没认成同款的候选，单独列出来，不混进对比表 */
  unmatched: OfferView[];
}

/** 以主角商品为基准归组。 */
export function buildCompareGroups(primary: OfferView, candidates: OfferView[]): CompareResult {
  const matched: OfferView[] = [];
  const unmatched: OfferView[] = [];
  const warnings: string[] = [];
  const specs: Record<string, string> = {};

  for (const candidate of candidates) {
    if (candidate.id === primary.id) continue;
    const reading = matchOffer(primary, candidate);
    if (reading.shared.length === 0) {
      unmatched.push(candidate);
      continue;
    }
    matched.push(candidate);
    for (const token of reading.shared) specs[`型号 ${token}`] = token;
    for (const warning of reading.warnings) {
      if (!warnings.includes(warning)) warnings.push(warning);
    }
  }

  const offers = [primary, ...matched];
  const confidence =
    matched.length === 0
      ? 1
      : Math.round(
          (matched.reduce((sum, offer) => sum + matchOffer(primary, offer).confidence, 0) /
            matched.length) *
            100,
        ) / 100;

  const group: GroupView = {
    id: `${primary.platform}:${primary.id}`,
    title: primary.title,
    brand: null,
    specs,
    confidence,
    warnings,
    best_definite_price: bestDefinitePrice(offers),
    best_public_price: bestPublicPrice(offers),
    offers,
  };
  return { groups: [group], unmatched };
}

/** 有没有真实的价格证据。
 *
 *  页面没渲染出价格时 buildOffer 给的 list_price 是 0， breakdown 也会跟着算成
 *  0.00。那个 0 不是「免费」，是「没读到」—— 绝不能让它赢了最低价比拼，
 *  否则界面上会写出「最低确定价 0.00 元」这种凭空造出来的数。 */
function hasPrice(offer: OfferView): boolean {
  return !offer.is_demo && Number(offer.list_price) > 0;
}

function bestDefinitePrice(offers: readonly OfferView[]): string | null {
  const totals = offers
    .filter(hasPrice)
    .map((offer) => Number(offer.breakdown.definite_total))
    .filter((value) => Number.isFinite(value));
  if (totals.length === 0) return null;
  return Math.min(...totals).toFixed(2);
}

/** 公开轨上的最低到手价（与后端 CanonicalProduct.best_public_price 同规则）。 */
function bestPublicPrice(offers: readonly OfferView[]): string | null {
  const totals = offers
    .filter(hasPrice)
    .map((offer) => Number(offer.breakdown.public_total))
    .filter((value) => Number.isFinite(value));
  if (totals.length === 0) return null;
  return Math.min(...totals).toFixed(2);
}

/** 单个商品的拆解。侧面板读当前页时用。 */
export function breakdownFor(offer: Offer) {
  return computePriceBreakdown({
    list_price: offer.list_price,
    shipping_fee: offer.shipping_fee,
    discounts: offer.discounts,
    data_status: offer.data_status,
  });
}
