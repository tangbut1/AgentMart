/** 国补（政府补贴）资格与到手价的两套算法。
 *
 *  与后端 app/domain/subsidy.py 对应。为什么不能"自动匹配"成一个数：
 *  国补的资格取决于收货地区、商品品类、能效等级、单件售价上限、以及每人
 *  已领次数 —— 这些**没有一项能从商品页确认**。页面上那句"国补 15%"
 *  只说明"有这个活动"，不说明"你能拿到"。
 *
 *  所以这里做的是把两种情形都算出来、都标清楚，让用户自己对照：
 *  - 不符合资格时的到手价（确定要付的）；
 *  - 符合资格时预计还能再减多少（标注为"仅当你本人符合资格"）。
 *
 *  两个数都摆出来，不合并、不挑好看的那个。补贴永远不进"确定到手价"。
 */

import { divRoundHalfEven, formatMoney, rational, type Cents, type Rational } from "./money.ts";

export const SUBSIDY_FITS = ["region_matches", "region_conflicts", "unknown"] as const;
export type SubsidyFit = (typeof SUBSIDY_FITS)[number];

const FIT_LABELS = {
  region_matches: "地区与您填写的一致",
  region_conflicts: "地区与您填写的不一致",
  unknown: "页面未写地区限制",
} as const;

/** 文案里写死的地区限制，例如"限江苏用户""仅限北京地区""指定广东"。
 *  用前瞻收边界而不是把后缀吃进分组：真实文案里"江苏用户""江苏省""江苏地区"
 *  三种写法都有，核心地名要拿出来单独比。 */
const REGION_LIMIT_RE = new RegExp(
  "(?:限|仅限|仅支持|只支持|指定)\\s*([一-龥]{2,8}?)" +
    "(?=省|市|自治区|特别行政区|地区|用户|，|,|。|；|;|$)",
);
const SUBSIDY_PERCENT_RE = /([0-9]+(?:\.[0-9]+)?)\s*%/;
const SUBSIDY_AMOUNT_RE = /(?:减|补贴|抵扣)\s*([0-9]+(?:\.[0-9]{1,2})?)\s*元/;

export interface SubsidyReading {
  raw_text: string;
  /** 百分比有理数 */
  percent: Rational | null;
  amount: Cents | null;
  /** 金额原文，如 "500" 或 "15.5"；展示用，不做两位小数补齐 */
  amount_text: string | null;
  region_limit: string | null;
  user_region: string | null;
  fit: SubsidyFit;
  reason: string;
  questions: string[];
}

/** 把"江苏省""江苏""南京市"归到可比的形式。
 *
 *  只做最保守的归一：去掉行政区划后缀。这样"江苏"和"江苏省"能对上，
 *  但"江苏"和"南京"仍然对不上 —— 那本来就需要用户自己确认。 */
function normalizeRegion(text: string): string {
  const value = (text ?? "").trim();
  for (const suffix of ["特别行政区", "自治区", "省", "市"]) {
    if (value.endsWith(suffix) && value.length > suffix.length) {
      return value.slice(0, value.length - suffix.length);
    }
  }
  return value;
}

/** 解释一条补贴文案。没有补贴关键词就返回 null（不猜）。 */
export function interpretSubsidyText(
  text: string,
  userRegion: string | null = null,
): SubsidyReading | null {
  const raw = (text ?? "").trim();
  if (!raw || (!raw.includes("国补") && !raw.includes("补贴"))) return null;

  let percent: Rational | null = null;
  const percentMatch = raw.match(SUBSIDY_PERCENT_RE);
  if (percentMatch) percent = rational(percentMatch[1]);
  let amount: Cents | null = null;
  let amountText: string | null = null;
  const amountMatch = raw.match(SUBSIDY_AMOUNT_RE);
  if (amountMatch) {
    amountText = amountMatch[1];
    amount = Math.round(Number(amountMatch[1]) * 100);
  }

  let regionLimit: string | null = null;
  const regionMatch = raw.match(REGION_LIMIT_RE);
  if (regionMatch) regionLimit = regionMatch[1];

  const questions: string[] = [];
  let fit: SubsidyFit = "unknown";
  let reason = "页面未写地区限制，资格需本人核实";

  if (regionLimit) {
    if (userRegion) {
      if (normalizeRegion(regionLimit) === normalizeRegion(userRegion)) {
        fit = "region_matches";
        reason = `页面写明限${regionLimit}，与您填写的收货地一致`;
      } else {
        fit = "region_conflicts";
        reason = `页面写明限${regionLimit}，与您填写的收货地（${userRegion}）不一致`;
      }
    } else {
      reason = `页面写明限${regionLimit}，您还没有填写收货地`;
      questions.push(`你的收货地是${regionLimit}吗？`);
    }
  } else {
    questions.push("你本人符合这个补贴的资格吗（品类/能效等级/是否已领取）？");
  }

  if (questions.length === 0) {
    questions.push("品类、能效等级、售价上限和每人已领次数都符合吗？有一项不符合就享受不到。");
  }

  return {
    raw_text: raw,
    percent,
    amount,
    amount_text: amountText,
    region_limit: regionLimit,
    user_region: userRegion,
    fit,
    reason,
    questions,
  };
}

export interface SubsidyScenario {
  with_subsidy: Cents | null;
  without_subsidy: Cents;
  note: string;
}

/** 按"是否符合资格"算出两个到手价。没有任何可量化补贴时返回 null。 */
export function subsidyScenarios(
  definiteTotal: Cents,
  reading: SubsidyReading | null,
): SubsidyScenario | null {
  if (reading === null) return null;
  if (reading.percent === null && reading.amount === null) return null;

  let benefit: Cents;
  // 文案里直接写了金额时，展示用页面原文（"500" 不会被补成 "500.00"）——
  // 后端那里 benefit 就是裸 Decimal，str() 出来也是原文。按比例算出来的
  // 才需要两位小数，因为它本身是算出来的。
  let benefitText: string;
  if (reading.amount !== null) {
    benefit = reading.amount;
    benefitText = reading.amount_text ?? formatMoney(benefit);
  } else if (reading.percent !== null) {
    benefit = divRoundHalfEven(definiteTotal * reading.percent.num, reading.percent.den * 100);
    benefitText = formatMoney(benefit);
  } else {
    return null;
  }

  let withSubsidy = definiteTotal - benefit;
  if (withSubsidy < 0) withSubsidy = 0;

  let note =
    `左侧是确定要付的 ${formatMoney(definiteTotal)} 元；右侧仅在您本人符合补贴资格时成立，` +
    `预计再减 ${benefitText} 元。资格未经核实，本工具不代您认定。`;
  if (reading.fit === "region_conflicts") {
    note += "另外，页面写明的补贴地区与您填写的收货地不一致，右侧情形很可能不成立。";
  }
  return { with_subsidy: withSubsidy, without_subsidy: definiteTotal, note };
}

export function subsidyFitLabel(fit: SubsidyFit): string {
  return FIT_LABELS[fit];
}
