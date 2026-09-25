/** 与后端 app/domain/enums.py 一一对应的取值集合。
 *
 * 这里用 const 对象而不是 enum：扩展产物要在 MV3 service worker 里以 classic
 * script 运行，且单元测试直接用 Node 的 type-stripping 跑，enum 的运行时产物
 * 两边都不划算。字符串取值必须与 Python 侧完全一致 —— 两侧的输出会做逐字段
 * 比对（见 tests/parity.test.ts 与 tests/test_extension_parity.py）。
 */

export const PLATFORM_LABELS = {
  jd: "京东",
  taobao: "淘宝",
  tmall: "天猫",
  pdd: "拼多多",
  douyin: "抖音电商",
} as const;
export type Platform = keyof typeof PLATFORM_LABELS;

export const SHOP_TYPE_LABELS = {
  self_operated: "自营",
  official_flagship: "官方旗舰店",
  flagship: "旗舰店",
  authorized: "授权店",
  third_party: "第三方店铺",
  unknown: "店铺类型待核实",
} as const;
export type ShopType = keyof typeof SHOP_TYPE_LABELS;

export const DATA_STATUS_LABELS = {
  real: "真实数据",
  demo: "演示数据",
  stale: "数据已过期",
  unverified: "待核实",
} as const;
export type DataStatus = keyof typeof DATA_STATUS_LABELS;

export const DISCOUNT_KINDS = [
  "coupon",
  "subsidy",
  "activity",
  "payment",
  "trade_in",
  "free_shipping",
] as const;
export type DiscountKind = (typeof DISCOUNT_KINDS)[number];

export const CONDITION_KINDS = ["unconditional", "conditional", "unverifiable"] as const;
export type ConditionKind = (typeof CONDITION_KINDS)[number];

/** 优惠归属层级（app/domain/enums.py 的 DiscountLayer）。
 *
 *  同一层里的优惠几乎一定不能叠加（一个商品页不会同时让你用两张店铺券），
 *  不同层通常可以。文案没写的归 product —— 最保守：认不出归属的券和商品层
 *  优惠挤在一个池里只取最优，绝不会把两张其实互斥的券都算进到手价。 */
export const DISCOUNT_LAYERS = [
  "product",
  "shop",
  "platform",
  "payment",
  "subsidy",
  "shipping",
] as const;
export type DiscountLayer = (typeof DISCOUNT_LAYERS)[number];

export const DISCOUNT_LAYER_LABELS = {
  product: "商品层",
  shop: "店铺层",
  platform: "平台层",
  payment: "支付层",
  subsidy: "补贴层",
  shipping: "运费层",
} as const;

export const CONDITION_KIND_LABELS = {
  unconditional: "无条件成立",
  conditional: "满足条件才成立",
  unverifiable: "无法核实",
} as const;

export const POLICY_SCOPE_LABELS = {
  platform_rule: "平台通用规则",
  shop_promise: "店铺承诺",
  product_page_promise: "商品页承诺",
  pending_verification: "尚待核实",
} as const;
export type PolicyScope = keyof typeof POLICY_SCOPE_LABELS;

export const POLICY_CATEGORIES = [
  "after_sales",
  "return_restriction",
  "warranty",
  "shipping",
  "authenticity",
  "invoice",
  "price_protection",
] as const;
export type PolicyCategory = (typeof POLICY_CATEGORIES)[number];

export const POLICY_CATEGORY_LABELS = {
  after_sales: "售后/退换",
  return_restriction: "退换限制",
  warranty: "保修",
  shipping: "发货/物流",
  authenticity: "正品保障",
  invoice: "发票",
  price_protection: "价保",
} as const;

/** 价格确定性档位（app/browser/enums.py 的 PriceCertainty）。 */
export const PRICE_CERTAINTY_LABELS = {
  page_public: "页面公开价",
  account_coupon: "账号可见可用券",
  conditional: "满足条件的预计价",
  prepayment: "结算页待支付金额",
  unverifiable: "无法核实",
} as const;
export type PriceCertainty = keyof typeof PRICE_CERTAINTY_LABELS;

/** 条件等级 → 确定性档位标签。写进 Discount.note，前端据此展示。 */
export const CONDITION_TO_CERTAINTY_LABEL = {
  unconditional: PRICE_CERTAINTY_LABELS.account_coupon,
  conditional: PRICE_CERTAINTY_LABELS.conditional,
  unverifiable: PRICE_CERTAINTY_LABELS.unverifiable,
} as const;

export function certaintyLabel(condition: ConditionKind): string {
  return CONDITION_TO_CERTAINTY_LABEL[condition];
}
