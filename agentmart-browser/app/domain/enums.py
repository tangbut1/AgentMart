"""Domain enums shared across adapters, pricing, matching and API layers."""

from enum import Enum


class Platform(str, Enum):
    JD = "jd"                # 京东
    TAOBAO = "taobao"        # 淘宝
    TMALL = "tmall"          # 天猫
    PDD = "pdd"              # 拼多多
    DOUYIN = "douyin"        # 抖音电商

    @property
    def label(self) -> str:
        return {
            Platform.JD: "京东",
            Platform.TAOBAO: "淘宝",
            Platform.TMALL: "天猫",
            Platform.PDD: "拼多多",
            Platform.DOUYIN: "抖音电商",
        }[self]


class ShopType(str, Enum):
    """店铺类型 —— 仅在能核实时标注，未知时用 UNKNOWN，不得猜测。"""
    SELF_OPERATED = "self_operated"      # 平台自营（如京东自营）
    OFFICIAL_FLAGSHIP = "official_flagship"  # 品牌官方旗舰店
    FLAGSHIP = "flagship"                # 旗舰店（非官方授权待核实）
    AUTHORIZED = "authorized"            # 授权专营店
    THIRD_PARTY = "third_party"          # 第三方个人/企业店
    UNKNOWN = "unknown"

    @property
    def label(self) -> str:
        return {
            ShopType.SELF_OPERATED: "自营",
            ShopType.OFFICIAL_FLAGSHIP: "官方旗舰店",
            ShopType.FLAGSHIP: "旗舰店",
            ShopType.AUTHORIZED: "授权店",
            ShopType.THIRD_PARTY: "第三方店铺",
            ShopType.UNKNOWN: "店铺类型待核实",
        }[self]


class DataStatus(str, Enum):
    """数据可信状态。DEMO 数据必须与真实数据隔离展示。"""
    REAL = "real"            # 来自已接入平台接口的真实数据
    DEMO = "demo"            # 演示数据（虚构，仅用于开发联调）
    STALE = "stale"          # 真实数据但已过期
    UNVERIFIED = "unverified"  # 来源存在但未能核验

    @property
    def label(self) -> str:
        return {
            DataStatus.REAL: "真实数据",
            DataStatus.DEMO: "演示数据",
            DataStatus.STALE: "数据已过期",
            DataStatus.UNVERIFIED: "待核实",
        }[self]


class DiscountKind(str, Enum):
    COUPON = "coupon"            # 优惠券（店铺券/平台券）
    SUBSIDY = "subsidy"          # 补贴（国补/以旧换新补贴/平台补贴）
    ACTIVITY = "activity"        # 活动优惠（满减/秒杀/直降）
    PAYMENT = "payment"          # 支付优惠（银行卡/支付平台立减）
    TRADE_IN = "trade_in"        # 以旧换新抵扣
    FREE_SHIPPING = "free_shipping"  # 包邮


class ConditionKind(str, Enum):
    """优惠成立条件等级 —— 决定它能否计入“确定到手价”。"""
    UNCONDITIONAL = "unconditional"  # 无条件成立（页面价即到手价）
    CONDITIONAL = "conditional"      # 满足条件才成立（需领券/满减/资格）
    UNVERIFIABLE = "unverifiable"    # 规则无法核实，不得计入确定价


class PolicyScope(str, Enum):
    """政策归属层级。"""
    PLATFORM_RULE = "platform_rule"          # 平台通用规则
    SHOP_PROMISE = "shop_promise"            # 店铺承诺
    PRODUCT_PAGE_PROMISE = "product_page_promise"  # 商品页面承诺
    PENDING_VERIFICATION = "pending_verification"   # 尚待核实


class PolicyCategory(str, Enum):
    AFTER_SALES = "after_sales"    # 售后/退换
    RETURN_RESTRICTION = "return_restriction"  # 退换限制（不支持/激活不退等否定式）
    WARRANTY = "warranty"          # 保修
    SHIPPING = "shipping"          # 发货/物流
    AUTHENTICITY = "authenticity"  # 正品保障
    INVOICE = "invoice"            # 发票
    PRICE_PROTECTION = "price_protection"  # 价保


class ReviewPlatform(str, Enum):
    BILIBILI = "bilibili"
    DOUYIN = "douyin"
    OTHER = "other"

    @property
    def label(self) -> str:
        return {"bilibili": "哔哩哔哩", "douyin": "抖音", "other": "其他"}[self.value]


class CommercialRelation(str, Enum):
    NONE_DISCLOSED = "none_disclosed"  # 已披露无商业合作
    DISCLOSED = "disclosed"            # 已披露商业合作/带货
    UNDISCLOSED = "undisclosed"        # 未披露（无法确认）
    UNKNOWN = "unknown"                # 尚待核实


class CurationStatus(str, Enum):
    PENDING = "pending"      # 已提交，待整理
    VERIFIED = "verified"    # 已人工核实整理
    REJECTED = "rejected"    # 已否决（非真实评测/不相关）


class ConnectionStatus(str, Enum):
    CONNECTED = "connected"          # 已配置凭据，可请求真实数据
    NOT_CONNECTED = "not_connected"  # 未配置凭据
    ERROR = "error"                  # 已配置但最近请求失败
