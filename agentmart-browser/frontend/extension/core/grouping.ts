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

/** 这些词是规格或营销词，不是型号 —— 拿它们当同款依据会把不同商品归到一起。 */
const GENERIC_TOKENS = new Set([
  "5G", "4G", "WIFI", "WLAN", "TYPE-C", "TYPEC", "USB", "HDMI", "BLUETOOTH", "NFC",
  "PLUS", "PRO", "MAX", "ULTRA", "MINI", "LITE", "NEW", "SE", "AIR",
  "128GB", "256GB", "512GB", "1TB", "2TB", "64GB", "32GB",
  "2023", "2024", "2025", "2026",
  "BLACK", "WHITE", "BLUE", "GREEN", "PINK", "GOLD", "SILVER", "GRAY",
  "黑", "白", "蓝", "绿", "粉", "金", "银", "灰",
]);

/** 容量写法先摘掉：不摘的话「Pro 256GB」会被当成「PRO256GB」这个型号。 */
const STORAGE_RE = /(?<![\d.])(\d{1,4})\s*(GB|TB|MB|G|T)(?![\w.])/gi;

/** 「单词 + 数字」型号：iPhone 15、Galaxy S24、AirPods Pro 2。
 *
 *  数字后面不能紧跟单位 —— MacBook Air「13.6英寸」是屏幕尺寸不是型号，
 *  电池「5000mAh」、重量「1.5kg」同理。 */
const WORD_NUM_RE =
  /([A-Za-z]{2,}|[A-Za-z]\d)\s+(\d{1,4}[A-Za-z]{0,6})(?!\.\d)(?!\s*(?:英寸|寸|厘米|米|毫米|mm|cm|kg|克|瓦|w|wh|小时|分钟|年|月|日|款|代|核|hz|bit))\b/gi;

/** 字母数字型号（WH-1000XM5 / A3092）。必须以字母开头 —— 以数字开头的
 *  串基本是尺寸、容量、参数（13.6、5000mAh），不是型号。 */
const TOKEN_RE = /[A-Za-z][A-Za-z0-9]*(?:[-–][A-Za-z0-9]+)*[A-Za-z0-9]*/g;

/** 从标题/规格里挑出「像型号」的 token：含数字、长度够、不是通用词。 */
export function modelTokens(text: string): string[] {
  const source = (text ?? "").replace(STORAGE_RE, " ");
  const tokens: string[] = [];
  const push = (token: string): void => {
    if (token.length < 3) return;
    if (!/[0-9]/.test(token)) return; // 型号里几乎总有数字
    if (GENERIC_TOKENS.has(token)) return;
    if (!tokens.includes(token)) tokens.push(token);
  };

  for (const raw of source.match(TOKEN_RE) ?? []) {
    push(raw.replace(/^[+\-.]+|[+\-.]+$/g, "").toUpperCase());
  }
  for (const match of source.matchAll(WORD_NUM_RE)) {
    push((match[1] + match[2]).toUpperCase());
  }
  return tokens;
}

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
  const shared = primaryTokens.filter((token) => candidateTokens.includes(token));
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
    offers,
  };
  return { groups: [group], unmatched };
}

function bestDefinitePrice(offers: readonly OfferView[]): string | null {
  const totals = offers
    .filter((offer) => !offer.is_demo)
    .map((offer) => Number(offer.breakdown.definite_total))
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
