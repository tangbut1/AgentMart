/** 金额一律用「分」为单位的整数运算。
 *
 * 为什么不用 number 直接算钱：0.1 + 0.2 !== 0.3 这类误差在比价里会直接
 * 变成「到手价算错一毛」。Python 侧用 Decimal，这里用整数分 + 显式的
 * 舍入规则，保证两侧对同一组输入算出同一个数。
 *
 * 舍入规则必须是**银行家舍入（half-even）**，因为 Python 的
 * Decimal.quantize 默认就是 half-even；用 JS 的 Math.round（half-up）
 * 会在 x.xx5 这种边界上和后端差一分钱，而比价工具差一分钱就是错的。
 */

/** 以「分」为单位的金额。 */
export type Cents = number;

const HUNDRED = 100;

/** 把「12.3」这样的元字符串转成 1230 分；解析不了返回 null（不猜）。 */
export function parseMoney(text: string | null | undefined): Cents | null {
  if (text === null || text === undefined) return null;
  const raw = typeof text === "string" ? text : `${text}`;
  const trimmed = raw.trim();
  if (!trimmed) return null;
  // 去掉千分位（半角与全角逗号都要去）
  const cleaned = trimmed.replace(/[,，]/g, "");
  // 优先取带货币符号的数值；没有货币符号时取第一个数值
  const withSymbol = cleaned.match(/[¥￥]\s*([0-9]+(?:\.[0-9]{1,2})?)/);
  const match = withSymbol ?? cleaned.match(/([0-9]+(?:\.[0-9]{1,2})?)/);
  if (!match) return null;
  const value = Number(match[1]);
  if (!Number.isFinite(value)) return null;
  if (value <= 0 || value > 100000000) return null;
  return Math.round(value * HUNDRED);
}

/** 1234 → "12.34"；-50 → "-0.50"。 */
export function formatMoney(cents: Cents): string {
  const sign = cents < 0 ? "-" : "";
  const abs = Math.abs(Math.trunc(cents));
  const yuan = Math.floor(abs / HUNDRED);
  const rest = abs % HUNDRED;
  return `${sign}${yuan}.${String(rest).padStart(2, "0")}`;
}

/** 正则已经保证是数字时的换算：只换单位，不做正负/范围过滤。
 *
 *  与 parseMoney 的区别是故意的 —— 后端的优惠解析用的是裸 Decimal()，
 *  "满100减0" 这种文案在那边得到 0 而不是 None，分支走向不一样。
 *  页面金额普遍不超过两位小数，这里按分取整。 */
export function decimalToCents(text: string): Cents | null {
  const match = text.match(/^-?[0-9]+(?:\.[0-9]+)?/);
  if (!match) return null;
  return Math.round(Number(match[0]) * HUNDRED);
}

/** 后端 serialize.money 的语义：None → 空串，否则两位小数。 */
export function moneyOrEmpty(cents: Cents | null | undefined): string {
  return cents === null || cents === undefined ? "" : formatMoney(cents);
}

/** n / d 的 half-even 舍入。d 必须为正。 */
export function divRoundHalfEven(numerator: number, denominator: number): number {
  if (denominator <= 0) throw new Error("denominator must be positive");
  const quotient = Math.trunc(numerator / denominator);
  const remainder = numerator - quotient * denominator;
  const twice = Math.abs(remainder) * 2;
  if (twice > denominator) return quotient + Math.sign(numerator || 1);
  if (twice < denominator) return quotient;
  // 正好在一半上：取偶数那一侧
  return quotient % 2 === 0 ? quotient : quotient + Math.sign(numerator || 1);
}

/** 百分比 → 精确有理数，避免 "13.5" 之类的小数在浮点里失真。 */
export interface Rational {
  num: number;
  den: number;
  /** 原始文本的 Decimal 归一形式，用于原样展示 */
  text: string;
}

export function rational(raw: string): Rational {
  const body = raw.startsWith("-") ? raw.slice(1) : raw;
  const dot = body.indexOf(".");
  const intPart = dot === -1 ? body : body.slice(0, dot);
  const fracPart = dot === -1 ? "" : body.slice(dot + 1);
  const digits = `${intPart}${fracPart}` || "0";
  const num = (raw.startsWith("-") ? -1 : 1) * Number(digits);
  return { num, den: 10 ** fracPart.length, text: decimalStr(raw) };
}

/** Python str(Decimal(x)) 的等价物：去掉整数部分前导零，小数部分原样保留。 */
export function decimalStr(raw: string): string {
  const negative = raw.startsWith("-");
  const body = negative ? raw.slice(1) : raw;
  const dot = body.indexOf(".");
  let intPart = dot === -1 ? body : body.slice(0, dot);
  const fracPart = dot === -1 ? "" : body.slice(dot + 1);
  intPart = intPart.replace(/^0+(?=\d)/, "");
  if (intPart === "") intPart = "0";
  return `${negative ? "-" : ""}${fracPart ? `${intPart}.${fracPart}` : intPart}`;
}
