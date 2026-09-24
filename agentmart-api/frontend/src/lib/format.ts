/** 展示层格式化与枚举文案（单一来源，避免各处硬编码中文）。 */
import type {
  CommercialRelation,
  ConditionKind,
  ConnectionStatus,
  CurationStatus,
  DataStatus,
  DiscountKind,
  Platform,
  PolicyScope,
  ReviewPlatform,
  ShopType,
} from "./api";

export const PLATFORM_LABEL: Record<Platform, string> = {
  jd: "京东",
  taobao: "淘宝",
  tmall: "天猫",
  pdd: "拼多多",
  douyin: "抖音商城",
};

export const PLATFORM_ORDER: Platform[] = ["jd", "taobao", "tmall", "pdd", "douyin"];

export const SHOP_TYPE_LABEL: Record<ShopType, string> = {
  self_operated: "平台自营",
  official_flagship: "品牌官方旗舰店",
  flagship: "旗舰店",
  authorized: "授权店",
  third_party: "第三方店铺",
  unknown: "店铺类型未知",
};

export const DATA_STATUS_LABEL: Record<DataStatus, string> = {
  real: "真实数据",
  demo: "演示数据",
  stale: "数据可能过期",
  unverified: "未核实",
};

export const DISCOUNT_KIND_LABEL: Record<DiscountKind, string> = {
  coupon: "优惠券",
  subsidy: "补贴",
  activity: "活动价",
  payment: "支付优惠",
  trade_in: "以旧换新",
  free_shipping: "包邮",
};

export const CONDITION_KIND_LABEL: Record<ConditionKind, string> = {
  unconditional: "无条件",
  conditional: "有条件",
  unverifiable: "条件待核验",
};

export const POLICY_SCOPE_LABEL: Record<PolicyScope, string> = {
  platform_rule: "平台规则",
  shop_promise: "店铺承诺",
  product_page_promise: "商品页承诺",
  pending_verification: "待核实",
};

export const POLICY_SCOPE_NOTE: Record<PolicyScope, string> = {
  platform_rule: "由平台规则文件规定，通常可稳定预期",
  shop_promise: "由店铺自行承诺，需以店铺页面与客服确认为准",
  product_page_promise: "仅在商品页展示，可能随活动变化",
  pending_verification: "尚未核实，仅供参考",
};

export const CONNECTION_STATUS_LABEL: Record<ConnectionStatus, string> = {
  connected: "已接入",
  not_configured: "未接入",
  error: "接入异常",
  rate_limited: "触发限流",
};

export const REVIEW_PLATFORM_LABEL: Record<ReviewPlatform, string> = {
  bilibili: "哔哩哔哩",
  douyin: "抖音",
  user_submitted: "用户提交",
};

export const CURATION_STATUS_LABEL: Record<CurationStatus, string> = {
  pending: "待整理",
  verified: "已核实",
  rejected: "已排除",
  ai_summary: "含 AI 归纳",
};

export const COMMERCIAL_RELATION_LABEL: Record<CommercialRelation, string> = {
  none_disclosed: "未声明商业合作",
  sponsored: "已声明商单",
  affiliate: "含带货佣金",
  unknown: "合作关系未知",
};

export const PICK_TYPE_LABEL: Record<string, string> = {
  best_overall: "首选",
  cheapest: "更省钱",
  safest: "更稳妥",
};

export const PRIORITY_LABEL: Record<string, string> = {
  price: "更看重价格",
  service: "更看重售后",
  balanced: "价格与售后平衡",
};

/** 金额格式化为「¥1,234.50」，去掉无意义的尾随 0。 */
export function formatMoney(value: string | number | null | undefined): string {
  if (value == null) return "—";
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return "—";
  return n.toLocaleString("zh-CN", {
    minimumFractionDigits: Number.isInteger(n) ? 0 : 2,
    maximumFractionDigits: 2,
  });
}

/** 拆分整数与小数部分，供大号价格数字排版使用。 */
export function splitMoney(value: string | number | null | undefined) {
  if (value == null) return { int: "—", frac: "" };
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return { int: "—", frac: "" };
  const fixed = n.toFixed(2);
  const [int, frac] = fixed.split(".");
  const intFormatted = Number(int).toLocaleString("zh-CN");
  return { int: intFormatted, frac: frac === "00" ? "" : `.${frac}` };
}

export function formatPercent(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${Math.round(value * 100)}%`;
}

export function formatCount(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  if (value >= 100_000_000) return `${(value / 100_000_000).toFixed(1)} 亿`;
  if (value >= 10_000) return `${(value / 10_000).toFixed(1)} 万`;
  return value.toLocaleString("zh-CN");
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return "";
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

/** 相对时间：今天 / N 天前 / 日期。 */
export function formatRelativeTime(iso: string | null | undefined): string {
  if (!iso) return "时间未知";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "时间未知";
  const now = Date.now();
  const diff = now - d.getTime();
  const minute = 60_000;
  const hour = 60 * minute;
  const day = 24 * hour;
  if (diff < minute) return "刚刚";
  if (diff < hour) return `${Math.floor(diff / minute)} 分钟前`;
  if (diff < day) return `${Math.floor(diff / hour)} 小时前`;
  if (diff < 30 * day) return `${Math.floor(diff / day)} 天前`;
  return formatDate(iso);
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${formatDate(iso)} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** 判断字符串是否像 URL（首页两种搜索模式用）。 */
export function looksLikeUrl(text: string): boolean {
  return /^https?:\/\/\S+$/i.test(text.trim());
}

/**
 * 展示用的最低确定到手价。
 * 后端的 best_definite_price 有意排除演示数据（不参与结论），
 * 因此演示-only 组在前端回退为「演示报价中的最低价」并标记为演示。
 */
export function displayLowestPrice(product: {
  best_definite_price: string | null;
  offers: { list_price: string; breakdown: { definite_total: string } | null }[];
}): { value: string | null; demo: boolean } {
  if (product.best_definite_price) {
    return { value: product.best_definite_price, demo: false };
  }
  const totals = product.offers
    .map((o) => Number(o.breakdown?.definite_total ?? o.list_price))
    .filter((n) => Number.isFinite(n));
  if (totals.length === 0) return { value: null, demo: false };
  return { value: String(Math.min(...totals)), demo: true };
}

export function hostOf(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}
