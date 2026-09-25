/** 防套路：把页面上「看着便宜、其实有坑」的信号挑出来。
 *
 *  与后端 app/domain/traps.py 逐条对应。规矩也只有那一条：
 *  **没有页面证据就不说有坑，证据是否定式的就按限制报，页面没提的按
 *  「未显示」报并让用户自己去确认。** 宁可少报一个坑，不能把一个保护
 *  讲成坑，也不能把坑讲成保护。
 */

export const TRAP_KINDS = [
  "no_return_window",
  "activation_locked",
  "non_mainland",
  "no_freight_insurance",
  "special_no_return",
  "subsidy_unverified",
] as const;
export type TrapKind = (typeof TRAP_KINDS)[number];

export const TRAP_SEVERITIES = ["blocker", "major", "minor"] as const;
export type TrapSeverity = (typeof TRAP_SEVERITIES)[number];

const SEVERITY_LABELS = {
  blocker: "买前必须先确认",
  major: "明显影响决策",
  minor: "值得知道",
} as const;

const BASIS_LABELS = {
  page_text: "页面原文",
  not_shown: "页面未显示",
} as const;

// ─── 模式 ──────────────────────────────────────────────────────

/** 否定式退货限制 */
const NO_RETURN_RE = new RegExp(
  [
    "(?:不支持|不可|非|不享|无)(?:七天|7天|7 天)?\\s*无理由",
    "无理由\\s*(?:不支持|不可|不适用)",
    "不退不换|不予退换|不支持退换",
  ].join("|"),
);
/** 激活/拆封后不退：先出现"激活/拆封"，紧跟一个否定词，再落到退换上。
 *  限定标点窗口，避免把"激活后可享受7天无理由"里的"激活"误抓出来。 */
const ACTIVATION_RE = new RegExp(
  "(?:激活|拆封|拆包|开机|绑定)[^。；，,\\n]{0,10}" +
    "(?:不支持|不可|不予|无法|不能)[^。；，,\\n]{0,8}(?:退货|退款|退换|无理由)",
);
/** 非国行版本 */
const NON_MAINLAND_RE = new RegExp(
  "非国行|港版|港行|海外版|美版|日版|欧版|韩版|台版|水货|跨境版",
);
/** 特价/清仓类不退：两个信号必须挨着出现，只出现"特价"不算 */
const SPECIAL_NO_RETURN_RE = new RegExp(
  "(?:特价|清仓|尾货|处理品|样品|二手|翻新)[^。；，,\\n]{0,12}" +
    "(?:不退不换|不予退换|不支持|不可退|不可换|无法退|无法换)",
);
const FREIGHT_INSURANCE_RE = new RegExp("运费险|退货运费险|退货包运费");
/** 7 天无理由（正面） */
const RETURN_WINDOW_RE = new RegExp("七天无理由|7天无理由|7 天无理由");
const SUBSIDY_RE = new RegExp("国补|国家补贴|政府补贴|能效补贴|以旧换新|换新补贴");

export interface Trap {
  kind: TrapKind;
  label: string;
  /** blocker=买前必须先确认 major=明显影响决策 minor=值得知道 */
  severity: TrapSeverity;
  detail: string;
  /** 页面原文；basis 为 not_shown 时为空 */
  evidence: string;
  /** 要用户自己回答的问题；basis 为 not_shown 时必填 */
  question: string;
  /** page_text=页面写了 not_shown=页面没写（不等于没有） */
  basis: "page_text" | "not_shown";
}

function firstMatch(
  pattern: RegExp,
  texts: readonly string[],
): string | null {
  for (const text of texts) {
    if (text && pattern.test(text)) return text.trim();
  }
  return null;
}

export function detectTraps(options: {
  policy_texts: readonly string[];
  coupon_texts?: readonly string[];
  sku_text?: string;
  title?: string;
}): Trap[] {
  const coupons = [...(options.coupon_texts ?? [])];
  const policy = (options.policy_texts ?? []).filter((t) => t && t.trim());
  // 版本相关信号要看全：政策栏、规格、标题三处
  const versionTexts = [
    ...policy,
    ...(options.sku_text ? [options.sku_text] : []),
    ...(options.title ? [options.title] : []),
  ];
  const traps: Trap[] = [];

  const add = (trap: Trap): void => {
    traps.push(trap);
  };

  // 1) 激活/拆封后不退 —— 最贵的一个坑，排最前
  const activation = firstMatch(ACTIVATION_RE, versionTexts);
  if (activation) {
    add({
      kind: "activation_locked",
      label: "激活后不支持退换",
      severity: "blocker",
      detail:
        "页面写明激活（或拆封）之后就不能退换。这类商品到手即锁定，" +
        "买错型号、买错颜色都没有后悔余地。",
      evidence: activation,
      question: "这件商品激活/拆封后就不能退，你确定型号和配置都对吗？",
      basis: "page_text",
    });
  }

  // 2) 非国行 —— 影响保修、发票、入网，也是 blocker
  const nonMainland = firstMatch(NON_MAINLAND_RE, versionTexts);
  if (nonMainland) {
    // 标题里同时写了"国行"和别的词时，仍然是"页面同时出现两种说法"，
    // 必须报出来让用户自己看，不替用户判定。
    add({
      kind: "non_mainland",
      label: "页面出现非国行版本描述",
      severity: "blocker",
      detail:
        "港版/海外版通常不享国内全国联保，发票和入网许可也可能不同，" +
        "售后要自己找店。价格低往往正是低在这里。",
      evidence: nonMainland,
      question: "这是国行吗？港版/海外版的保修和发票与国行不一样。",
      basis: "page_text",
    });
  }

  // 3) 明确不支持 7 天无理由
  const noReturn = firstMatch(NO_RETURN_RE, policy);
  // 4) 特价/清仓不退不换。和上一条证据相同时只留更具体的这条 ——
  // 同一句"特价商品不支持7天无理由，不退不换"报两遍只是噪音。
  const special = firstMatch(SPECIAL_NO_RETURN_RE, policy);
  const sameText = special !== null && special === noReturn;
  if (noReturn && !sameText) {
    add({
      kind: "no_return_window",
      label: "页面写明不支持7天无理由",
      severity: "major",
      detail: "这件商品不适用 7 天无理由退货，到手后基本只能换不能退。",
      evidence: noReturn,
      question: "不支持7天无理由，你还想买吗？",
      basis: "page_text",
    });
  } else if (!noReturn && !firstMatch(RETURN_WINDOW_RE, policy)) {
    // 政策栏里完全没有"7天无理由"—— 这是"没看到"，不是"没有"。
    // 但页面已经白纸黑字写了"不退不换"时（哪怕为了去重只报了 special），
    // 不能再问一遍"支持7天无理由退货吗"：那句话问的是页面没答的事，
    // 而这里页面已经答了。
    add({
      kind: "no_return_window",
      label: "页面未显示7天无理由",
      severity: "minor",
      detail:
        "商品页的政策栏里没有找到 7 天无理由退货。可能是页面没加载全，" +
        "也可能这件商品确实不支持。",
      evidence: "",
      question: "下单前确认一下：这件支持 7 天无理由退货吗？",
      basis: "not_shown",
    });
  }

  if (special) {
    add({
      kind: "special_no_return",
      label: "特价/清仓商品不退不换",
      severity: "major",
      detail: "页面写明这类商品不退不换。低价来自这里，不是来自平台补贴。",
      evidence: special,
      question: "特价商品不退不换，这个价格对应的是这个条件，你能接受吗？",
      basis: "page_text",
    });
  }

  // 5) 运费险 —— 没有它，退货要自己掏运费
  if (!firstMatch(FREIGHT_INSURANCE_RE, policy)) {
    add({
      kind: "no_freight_insurance",
      label: "页面未显示退货运费险",
      severity: "minor",
      detail:
        "政策栏里没有看到退货运费险。没有运费险时，退货的运费要自己承担" +
        "（大件可能几十元）。",
      evidence: "",
      question: "退货运费谁承担？没有运费险的话可能得自己掏。",
      basis: "not_shown",
    });
  }

  // 6) 补贴资格没核实 —— 这是"钱上的坑"，不是"货上的坑"
  const subsidy = firstMatch(SUBSIDY_RE, coupons);
  if (subsidy) {
    add({
      kind: "subsidy_unverified",
      label: "页面提到补贴，但资格未核实",
      severity: "major",
      detail:
        "国补/以旧换新的资格取决于收货地区、商品品类、能效等级和是否已领取，" +
        "这些都无法从商品页确认。本工具不代您认定资格，也没有把它计入到手价。",
      evidence: subsidy,
      question:
        "你本人符合这个补贴的资格吗（地区/品类/是否已领取）？" +
        "不符合的话，到手价要按没有补贴算。",
      basis: "page_text",
    });
  }

  return traps;
}

export function worstSeverity(traps: readonly Trap[]): TrapSeverity | null {
  if (traps.length === 0) return null;
  let worst: TrapSeverity = "minor";
  for (const trap of traps) {
    if (severityRank(trap.severity) < severityRank(worst)) worst = trap.severity;
  }
  return worst;
}

function severityRank(severity: TrapSeverity): number {
  return severity === "blocker" ? 0 : severity === "major" ? 1 : 2;
}

export function summarizeTraps(traps: readonly Trap[]): string {
  if (traps.length === 0) return "页面未发现明显的退换或版本限制";
  const blockers = traps.filter((t) => t.severity === "blocker");
  const majors = traps.filter((t) => t.severity === "major");
  const parts: string[] = [];
  if (blockers.length > 0) parts.push(blockers.map((t) => t.label).join("、"));
  if (majors.length > 0) parts.push(majors.map((t) => t.label).join("、"));
  let head = parts.join("；");
  const minors = traps.length - blockers.length - majors.length;
  if (minors > 0) head += `；另有 ${minors} 项待确认`;
  return head;
}

export function trapSeverityLabel(severity: TrapSeverity): string {
  return SEVERITY_LABELS[severity];
}

export function trapBasisLabel(basis: Trap["basis"]): string {
  return BASIS_LABELS[basis];
}
