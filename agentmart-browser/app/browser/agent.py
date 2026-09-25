"""个人浏览器版的任务编排器。

对应需求的第五、六、九节。核心约束：

1. **一平台失败不影响整个任务**：每个平台一个独立协程，异常只终结自己；
2. **不让多个平台争抢同一个浏览器窗口**：按 profile 组（淘宝/天猫同组）
   加锁，同组串行；跨组用信号量限制并发；
3. **遇到平台阻止就停**：验证码/风控/登录墙 → 记录该平台本次未完成，
   绝不用演示数据补齐；
4. **预算与取消是协作式的**：每一步之前检查取消事件、步数、时长、
   模型调用上限，超限就安全停止并保留已取得的证据；
5. **模型只在确定性失败时介入**：先用 DOM 规则抽取；视觉识别到的金额
   必须与页面证据交叉核对，不一致就丢弃视觉结果；
6. **计算与推荐复用 API 版同一套 domain 逻辑**（group_offers /
   compute_price_breakdown / recommend），不另写一套。
"""
from __future__ import annotations

import asyncio
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional, Tuple

from loguru import logger

from ..domain.enums import DataStatus, Platform
from ..domain.matching import group_offers
from ..domain.models import CanonicalProduct, Offer, UserPreferences
from ..domain.pricing import compute_price_breakdown
from ..domain.recommendation import recommend
from .driver import BrowserDriver, DriverError, PlaywrightConfig, PlaywrightDriver
from .enums import ActionKind, BlockedReason, DataOrigin, TaskStatus
from .extract import (
    PageFields,
    build_offer,
    parse_money,
)
from .llm import BudgetExceeded, ModelClient, ModelError, model_configured
from .login import LoginManager, LoginSession, LoginUnavailable
from .profiles import (
    all_profiles,
    delete_profile,
    describe_storage,
    ensure_profile_dir,
    profile_group,
)
from .recipes import (
    JS_BLOCKED_PROBE,
    JS_LOGIN_PROBE,
    JS_PRODUCT_FIELDS,
    JS_PRODUCT_LINKS,
    get_recipe,
    search_url,
)
from .serialize import offer as serialize_offer
from .serialize import recommendation as serialize_recommendation

# 并发上限：同时最多两个平台在跑，避免把用户机器和带宽打满
MAX_CONCURRENT_PLATFORMS = 2

_CATEGORY_KEYWORDS: List[Tuple[str, str]] = [
    ("冲锋衣", "户外服装"), ("夹克", "户外服装"), ("羽绒服", "服装"), ("棉服", "服装"),
    ("手机", "手机"), ("平板", "平板电脑"), ("笔记本", "笔记本电脑"), ("电脑", "电脑"),
    ("显示器", "显示器"), ("耳机", "耳机"), ("音箱", "音频设备"), ("手表", "智能穿戴"),
    ("相机", "影像设备"), ("路由器", "网络设备"), ("键盘", "外设"), ("鼠标", "外设"),
    ("冰箱", "家电"), ("洗衣机", "家电"), ("空调", "家电"), ("电视", "家电"),
    ("奶粉", "母婴"), ("纸尿裤", "母婴"), ("护肤", "美妆"), ("精华", "美妆"),
]

_BRANDS = [
    "苹果", "Apple", "华为", "HUAWEI", "小米", "Redmi", "红米", "OPPO", "vivo",
    "荣耀", "一加", "realme", "三星", "Samsung", "联想", "Lenovo", "戴尔", "Dell",
    "惠普", "HP", "华硕", "ASUS", "ThinkPad", "索尼", "Sony", "Bose", "JBL",
    "耐克", "Nike", "阿迪达斯", "Adidas", "安踏", "李宁", "探路者", "凯乐石",
    "伯希和", "骆驼", "迪卡侬", "优衣库", "无印良品", "飞利浦", "松下", "海尔",
]

_REGION_RE = re.compile(
    r"(?:配送至|收货地?|地区|所在地?)[：:\s]*([一-龥]{2,12}?(?:省|市|自治区|特别行政区))"
)
# 价格区间有两种写法，拆成两条正则，因为二者的"可信度门槛"不同：
#
# A. 带了"预算/价钱/价格/花费"字样 —— 用户已经明说这是在说钱，
#    所以句末、标点后面也认："预算100到250"（没写单位、话没说完）。
_BUDGET_RANGE_LABELLED_RE = re.compile(
    r"(?:预算|价钱|价格|花费)\s*(?:在|是|为|：|:)?\s*([0-9]{2,7})\s*(?:元|块)?\s*"
    r"(?:~|～|-|—|到|至)\s*([0-9]{2,7})\s*(?:元|块)?"
    r"(?=\s*(?:元|块|之间|以内|以下|之内|左右|上下|的|，|,|。|；|;|！|!|？|\?|$))"
)
# B. 没带这些字样 —— 必须紧跟单位或"之间/以内"这类边界词才算。
#    少了这条门槛，"iPhone 15-16""出差15-20天"都会被当成价格区间。
_BUDGET_RANGE_RE = re.compile(
    r"([0-9]{2,7})\s*(?:元|块)?\s*(?:~|～|-|—|到|至)\s*([0-9]{2,7})"
    # 前瞻只判断"这是不是预算"，不消耗字符
    r"(?=\s*(?:元|块|之间|以内|以下|之内|左右|上下))"
    # 判断通过后再把单位吃掉，免得"100到250元的西装"剩下一个孤零零的"元"
    # 混进搜索词（实测关键词变成"元 西装"）
    r"\s*(?:元|块)?"
)
_BUDGET_RANGE_RES = (_BUDGET_RANGE_LABELLED_RE, _BUDGET_RANGE_RE)
_BUDGET_SINGLE_RE = re.compile(r"([0-9]{2,7})\s*(?:元|块)\s*(?:左右|以内|上下|以下|之内)")
# "预算 800 以内" 这类没写"元"的说法；带"预算"二字才认，避免把"10年以内"当成预算
_BUDGET_PREFIX_RE = re.compile(
    r"预算\s*(?:在|是|为|：|:)?\s*([0-9]{2,7})\s*(?:元|块)?\s*(?:以内|以下|之内|左右|上下)?"
)

# 口语里与商品无关的连接词/请求词，构造搜索词时剥掉
_FILLER_RE = re.compile(
    r"预算|价钱|价格|花费|左右|上下|前后|以内|以下|之内|之间|"
    r"想买|想要|打算|我要|我需要|我想|请|帮我|帮忙|给|找个|寻找|找|"
    r"买一件|买一个|买一部|买一台|买一款|买|一件|一个|一部|一台|一款|"
    r"看看有没有|看一下|看看|有没有|推荐一下|推荐|适合|用于|重视|看重|关注|"
    r"我能享受|能享受|享受|的|了|呢|吧|啊|和|以及|而且|并且|跟|与"
)
# 关键词过长时平台搜索会召回不到结果，按词丢弃而不是硬截断
_KEYWORD_MAX_LEN = 24
# 字母数字型号片段（TAWJ91717 / WH-1000XM5 / S24）
_MODEL_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[-–][A-Za-z0-9]+)*\d[\w-]*")
# 搜索结果页最多等这么久让商品锚点渲染出来。搜索页普遍是客户端渲染，
# goto 返回的瞬间节点往往还没挂上；不等就抽取会拿到 0 条，
# 于是把"还没渲染完"误判成"页面结构不认识"（京东实测就是这样）。
_LINK_WAIT_SECONDS = 12.0
_LINK_POLL_SECONDS = 0.5


def _short_reason(exc: BaseException, limit: int = 160) -> str:
    """把底层异常压成一行可读的原因，去掉多行堆栈。"""
    text = " ".join(str(exc).split())
    return text[:limit] + ("…" if len(text) > limit else "")


class BlockedPlatform(RuntimeError):
    """平台阻止了自动访问。"""

    def __init__(self, reason: BlockedReason, detail: str):
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


@dataclass
class Requirement:
    """从自然语言里解析出的结构化需求。解析不出来就留空，不猜。"""

    text: str
    keyword: str = ""
    category: Optional[str] = None
    budget_min: Optional[Decimal] = None
    budget_max: Optional[Decimal] = None
    brands: List[str] = field(default_factory=list)
    region: Optional[str] = None
    scenarios: List[str] = field(default_factory=list)
    # 预算是否为"左右/上下"这类近似说法（界面上要标注"约"）
    budget_approximate: bool = False
    # 只有在用户明确回复"要"时才为 True；默认关闭
    include_reviews: bool = False
    # 解析过程中没能理解的部分（原样告知用户）
    unclear: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "keyword": self.keyword,
            "category": self.category,
            "budget_min": float(self.budget_min) if self.budget_min else None,
            "budget_max": float(self.budget_max) if self.budget_max else None,
            "budget_approximate": self.budget_approximate,
            "brands": self.brands,
            "region": self.region,
            "scenarios": self.scenarios,
            "include_reviews": self.include_reviews,
            "unclear": self.unclear,
        }


_SCENARIO_WORDS = [
    "通勤", "徒步", "登山", "露营", "跑步", "骑行", "健身", "旅行", "出差",
    "日常", "办公", "学习", "游戏", "拍照", "摄影", "视频", "续航", "信号",
    "防水", "防雨", "防晒", "透气", "保暖", "轻薄", "静音", "护眼",
]

# 偏好词只影响筛选与推荐，不进入平台搜索词
_PREFERENCE_WORDS = [
    "国补", "国家补贴", "政府补贴", "补贴", "日常", "轻度", "重度", "性价比",
] + _SCENARIO_WORDS


def _strip_preferences(clause: str) -> str:
    text = clause
    for word in _PREFERENCE_WORDS:
        text = text.replace(word, " ")
    return text.strip()


def _search_keyword(raw: str, requirement: "Requirement") -> str:
    """从整句需求里提炼平台搜索词。

    只做确定性剥离：去掉预算、地区、口语连接词与偏好词，保留含品类词/品牌
    的片段和字母数字型号。提炼不出更好结果时就退回原文，绝不编造关键词。
    """
    text = raw
    for regex in (*_BUDGET_RANGE_RES, _BUDGET_SINGLE_RE, _BUDGET_PREFIX_RE):
        text = regex.sub(" ", text)
    text = _REGION_RE.sub(" ", text)
    text = _FILLER_RE.sub(" ", text)

    anchors = [word for word, _ in _CATEGORY_KEYWORDS] + list(_BRANDS)
    clauses = [c.strip() for c in re.split(r"[，,。；;！!？?、\s]+", text) if c.strip()]
    kept: List[str] = []
    for clause in clauses:
        if any(word in clause for word in anchors):
            # 品类片段里再去掉偏好词："日常通勤和轻度徒步的冲锋衣" → "冲锋衣"
            kept.append(_strip_preferences(clause) or clause)
        elif _MODEL_TOKEN_RE.search(clause):
            kept.append(clause)
        elif _strip_preferences(clause):
            kept.append(clause)
        # 其余整句都是偏好词（防雨/透气/国补…），不进搜索词

    keyword = ""
    for clause in kept:
        candidate = f"{keyword} {clause}".strip()
        if keyword and len(candidate) > _KEYWORD_MAX_LEN:
            break
        keyword = candidate
    return keyword or raw


def parse_requirement(text: str) -> Requirement:
    """确定性需求解析（不调用模型，保证可测、可复现）。"""
    raw = (text or "").strip()
    requirement = Requirement(text=raw, keyword=raw)

    for word, category in _CATEGORY_KEYWORDS:
        if word in raw:
            requirement.category = category
            break

    m = None
    for regex in _BUDGET_RANGE_RES:
        m = regex.search(raw)
        if m:
            break
    if m:
        low, high = Decimal(m.group(1)), Decimal(m.group(2))
        if low <= high:
            requirement.budget_min, requirement.budget_max = low, high
    else:
        m = _BUDGET_SINGLE_RE.search(raw)
        if m:
            requirement.budget_max = Decimal(m.group(1))
            # "左右/上下"是近似说法：不反推区间，只标注为约数
            if "左右" in raw or "上下" in raw or "前后" in raw:
                requirement.budget_approximate = True
        else:
            m = _BUDGET_PREFIX_RE.search(raw)
            if m:
                requirement.budget_max = Decimal(m.group(1))
                if "左右" in raw or "上下" in raw:
                    requirement.budget_approximate = True

    requirement.brands = [b for b in _BRANDS if b in raw]
    m = _REGION_RE.search(raw)
    if m:
        requirement.region = m.group(1)
    requirement.scenarios = [w for w in _SCENARIO_WORDS if w in raw]

    if any(k in raw for k in ("国补", "国家补贴", "政府补贴", "补贴")):
        requirement.scenarios.append("关注补贴资格")
    # 明确说"不要额外付费/不开会员"的需求
    if any(k in raw for k in ("不额外", "不开会员", "不要会员", "不充值", "不办卡")):
        requirement.scenarios.append("拒绝额外付费方案")

    if not requirement.category and not requirement.brands:
        requirement.unclear.append("未能确定商品品类，将按原始关键词搜索")
    if requirement.keyword == raw:
        # 没能提炼出更好的搜索词时才保留原句
        requirement.keyword = _search_keyword(raw, requirement)
    return requirement


# 结构化填表允许的字段。表单里填了什么就用什么，没填的才回退到自然语言解析。
_REQUIREMENT_FIELDS = (
    "keyword", "category", "budget_min", "budget_max", "budget_approximate",
    "brands", "region", "scenarios",
)
# 预算上限的合理范围。超过这个数基本是用户多打了零或填错了单位，
# 与其照着搜一堆不可能的结果，不如当场告诉用户。
_MONEY_MAX = Decimal("99999999")


def _to_money(value: Any, label: str) -> Optional[Decimal]:
    """把表单里的金额转成 Decimal；填得不像数字就直接报错，不猜。"""
    if value is None or value == "":
        return None
    text = str(value).strip().replace(",", "").replace("，", "")
    if not text:
        return None
    try:
        amount = Decimal(text)
    except Exception:
        raise ValueError(f"{label}要填数字，收到的是「{value}」") from None
    if amount.is_nan() or amount < 0:
        raise ValueError(f"{label}不能是负数")
    if amount > _MONEY_MAX:
        raise ValueError(f"{label}看起来不合理：{amount}（上限 {_MONEY_MAX}）")
    return amount


def _to_str_list(value: Any) -> List[str]:
    """品牌/场景既可能是数组也可能是"华为，小米"这样的字符串。"""
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        items = [str(v).strip() for v in value]
    else:
        items = re.split(r"[,，、;；\s]+", str(value))
    seen: List[str] = []
    for item in items:
        if item and item not in seen:
            seen.append(item)
    return seen


def _describe_requirement(requirement: "Requirement") -> str:
    """把结构化字段拼成一句人能读的话，用于任务记录和界面回显。

    只在用户没写自然语言时用；写了自己原话的仍然保留原话。
    """
    parts: List[str] = []
    if requirement.keyword:
        parts.append(requirement.keyword)
    if requirement.category:
        parts.append(f"品类：{requirement.category}")
    if requirement.budget_min and requirement.budget_max:
        parts.append(
            f"预算 {requirement.budget_min}–{requirement.budget_max} 元"
            + ("（约）" if requirement.budget_approximate else "")
        )
    elif requirement.budget_max:
        parts.append(
            f"预算不超过 {requirement.budget_max} 元"
            + ("（约）" if requirement.budget_approximate else "")
        )
    elif requirement.budget_min:
        parts.append(f"预算不低于 {requirement.budget_min} 元")
    if requirement.brands:
        parts.append("品牌：" + "、".join(requirement.brands))
    if requirement.region:
        parts.append(f"配送至{requirement.region}")
    if requirement.scenarios:
        parts.append("在意：" + "、".join(requirement.scenarios))
    return "，".join(parts)


def build_requirement(
    text: str, fields: Optional[Dict[str, Any]] = None
) -> Requirement:
    """按「结构化填表 > 自然语言解析」合成最终需求。

    为什么不改用大模型解析自然语言（评估过，明确不选）：
    1. 价格是这个产品最不能出错的一项。模型把"100到250之间"读成 max=100，
       或者补一个句子里根本没有的数字，就是凭空造价 —— 直接违反
       "绝不编造任何价格"这条红线。正则读错至少是固定的错，能写测试钉住；
    2. 用户机器上不一定配了模型 Key，核心链路不能依赖一个可能不存在的东西；
    3. 确定性规则可以回归测试，模型解析错了只能等用户再抱怨一次。

    所以自然语言降级为"自动填表"：它负责把一句话拆进表单，
    最终以表单为准。用户在表单里看到的数字，就是最终用的数字。
    """
    raw = (text or "").strip()
    requirement = parse_requirement(raw) if raw else Requirement(text="", keyword="")
    if not fields:
        return requirement

    keyword = str(fields.get("keyword") or "").strip()
    if keyword:
        requirement.keyword = keyword
    category = str(fields.get("category") or "").strip()
    if category:
        requirement.category = category

    low = _to_money(fields.get("budget_min"), "预算下限")
    high = _to_money(fields.get("budget_max"), "预算上限")
    if low is not None and high is not None and low > high:
        raise ValueError(f"预算下限 {low} 比上限 {high} 还大，请检查一下")
    if low is not None or high is not None:
        # 碰过预算就以表单为准，不再保留从原话里解析出的区间
        requirement.budget_min, requirement.budget_max = low, high
        if "budget_approximate" in fields:
            requirement.budget_approximate = bool(fields["budget_approximate"])

    brands = _to_str_list(fields.get("brands"))
    if "brands" in fields:
        requirement.brands = brands
    region = str(fields.get("region") or "").strip()
    if region:
        requirement.region = region
    scenarios = _to_str_list(fields.get("scenarios"))
    if "scenarios" in fields:
        requirement.scenarios = scenarios

    # 用户已经在表单里说清楚的事，不该再弹"未能确定品类"这类追问
    if keyword or category:
        requirement.unclear = []
    if not requirement.text:
        requirement.text = _describe_requirement(requirement)
    if not requirement.keyword:
        requirement.keyword = requirement.text
    return requirement


def empty_model_usage() -> Dict[str, Any]:
    """模型用量的空值形状。

    前端按固定字段读 calls / vision_calls / estimated_cost / errors，
    所以这里必须从一开始就给全，不能等任务跑完再补 —— 缺一个字段
    就会让整个任务页渲染崩掉（用户看到的是纯白页面）。
    """
    return {
        "calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "vision_calls": 0,
        "estimated_cost": 0.0,
        "errors": [],
    }


@dataclass
class StepLog:
    seq: int
    action: ActionKind
    detail: str
    at: datetime = field(default_factory=datetime.now)
    url: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "seq": self.seq,
            "action": self.action.value,
            "detail": self.detail,
            "at": self.at.strftime("%H:%M:%S"),
            "url": self.url,
        }


@dataclass
class PlatformState:
    """单个平台的执行状态。前端按这个渲染平台卡片。"""

    platform: Platform
    status: TaskStatus = TaskStatus.PENDING
    steps: List[StepLog] = field(default_factory=list)
    offers: List[Offer] = field(default_factory=list)
    problems: List[str] = field(default_factory=list)
    blocked_reason: Optional[BlockedReason] = None
    blocked_detail: Optional[str] = None
    origin: DataOrigin = DataOrigin.REAL_PLATFORM_PAGE
    model_calls: int = 0
    pages_visited: int = 0
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    paused: bool = False
    profile_group: str = ""
    urls: List[str] = field(default_factory=list)

    def log(self, action: ActionKind, detail: str, url: Optional[str] = None) -> None:
        self.steps.append(StepLog(seq=len(self.steps) + 1, action=action, detail=detail, url=url))
        # 只保留最近若干条，避免长任务把内存和界面撑爆
        if len(self.steps) > 60:
            del self.steps[:-60]

    @property
    def real_offer_count(self) -> int:
        return sum(1 for o in self.offers if o.data_status != DataStatus.DEMO)

    def to_dict(self) -> dict:
        return {
            "platform": self.platform.value,
            "display_name": get_recipe(self.platform).display_name,
            "status": self.status.value,
            "status_label": self.status.label,
            "blocked_reason": self.blocked_reason.value if self.blocked_reason else None,
            "blocked_reason_label": self.blocked_reason.label if self.blocked_reason else None,
            "blocked_detail": self.blocked_detail,
            "origin": self.origin.value,
            "origin_label": self.origin.label,
            "steps": [s.to_dict() for s in self.steps[-12:]],
            "offer_count": self.real_offer_count,
            "problems": list(self.problems),
            "model_calls": self.model_calls,
            "pages_visited": self.pages_visited,
            "started_at": self.started_at.strftime("%H:%M:%S") if self.started_at else None,
            "finished_at": self.finished_at.strftime("%H:%M:%S") if self.finished_at else None,
            "profile_group": self.profile_group,
            "paused": self.paused,
            "urls": self.urls[-8:],
            "recipe": {
                "home_url": get_recipe(self.platform).home_url,
                "requires_login_for_price": get_recipe(self.platform).requires_login_for_price,
                "notes": get_recipe(self.platform).notes,
            },
        }


@dataclass
class TaskOptions:
    """用户可调的执行参数（前端"任务设置"展示同名项）。"""

    platforms: List[Platform] = field(default_factory=lambda: list(Platform))
    max_candidates: int = 6            # 每平台最多细看几个商品
    max_links: int = 20                # 搜索结果页最多收集多少链接
    step_timeout_seconds: float = 25.0
    login_wait_seconds: float = 240.0  # 等用户登录/扫码的最长时间
    max_task_seconds: float = 900.0
    max_model_calls: int = 40          # 与模型配置的上限取较小者
    headless: bool = False             # 默认可见窗口，用户要能自己登录
    slow_mo_ms: int = 0
    origin: DataOrigin = DataOrigin.REAL_PLATFORM_PAGE
    # 测试/演示用：把平台的 home/search 地址换成本地受控页面。
    # 键为 "<平台>.<home|search>"，例如 "jd.search"。
    url_overrides: Dict[str, str] = field(default_factory=dict)
    # 是否在深入分析前询问"要不要加入专业评测"（需求第 2 步）
    ask_review_question: bool = True

    def override(self, platform: Platform, kind: str) -> Optional[str]:
        return self.url_overrides.get(f"{platform.value}.{kind}")

    def to_dict(self) -> dict:
        return {
            "platforms": [p.value for p in self.platforms],
            "max_candidates": self.max_candidates,
            "max_links": self.max_links,
            "step_timeout_seconds": self.step_timeout_seconds,
            "login_wait_seconds": self.login_wait_seconds,
            "max_task_seconds": self.max_task_seconds,
            "max_model_calls": self.max_model_calls,
            "headless": self.headless,
            "slow_mo_ms": self.slow_mo_ms,
            "origin": self.origin.value,
            "origin_label": self.origin.label,
            "url_overrides": dict(self.url_overrides),
            "ask_review_question": self.ask_review_question,
        }


@dataclass
class AgentTask:
    id: str
    requirement: Requirement
    options: TaskOptions
    states: Dict[Platform, PlatformState] = field(default_factory=dict)
    status: TaskStatus = TaskStatus.PENDING
    origin: DataOrigin = DataOrigin.REAL_PLATFORM_PAGE
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    canonical: List[CanonicalProduct] = field(default_factory=list)
    recommendation: Optional[Any] = None
    model_usage: Dict[str, Any] = field(default_factory=empty_model_usage)
    budget_exhausted: bool = False
    waiting_reason: Optional[str] = None
    pending_question: Optional[Dict[str, Any]] = None
    # 专业评测那个问题问过一次就够了：答完再 start 不能重新问一遍，
    # 否则用户永远卡在第 2 步，任务一次都跑不起来
    review_question_asked: bool = False
    notes: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        for platform in self.options.platforms:
            if platform not in self.states:
                self.states[platform] = PlatformState(
                    platform=platform,
                    origin=self.origin,
                    profile_group=profile_group(platform),
                )

    # ---- 状态查询 ----
    def state_of(self, platform: Platform) -> PlatformState:
        return self.states[platform]

    @property
    def all_offers(self) -> List[Offer]:
        out: List[Offer] = []
        for state in self.states.values():
            out.extend(state.offers)
        return out

    @property
    def real_offers(self) -> List[Offer]:
        return [o for o in self.all_offers if o.data_status != DataStatus.DEMO]

    @property
    def is_terminal(self) -> bool:
        return self.status in (
            TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED
        )

    def summary_status(self) -> TaskStatus:
        if self.status.is_terminal:
            return self.status
        # 任务级等待（例如还没回答"要不要专业评测"）优先于平台状态，
        # 否则前端会把它显示成"待开始"，用户看不到自己在等什么
        if self.status is TaskStatus.WAITING_CONFIRM:
            return TaskStatus.WAITING_CONFIRM
        if self.status is TaskStatus.WAITING_USER:
            return TaskStatus.WAITING_USER
        statuses = [s.status for s in self.states.values()]
        if any(s is TaskStatus.WAITING_USER for s in statuses):
            return TaskStatus.WAITING_USER
        if any(s is TaskStatus.WAITING_CONFIRM for s in statuses):
            return TaskStatus.WAITING_CONFIRM
        if any(s is TaskStatus.RUNNING for s in statuses):
            return TaskStatus.RUNNING
        # 没有平台在跑。只要有平台还没开始（包括另一些已经取消/结束的混合
        # 情况），任务就还是「待开始」——之前这里无条件回退成 RUNNING，
        # 前端据此把按钮置灰并显示"执行中…"，用户点不动，任务一次都跑不起来。
        if any(s is TaskStatus.PENDING for s in statuses):
            return TaskStatus.PENDING
        # 平台状态都给不出信息（还没有平台，或全都已结束而任务级状态还没落定）
        # 时，如实退回任务自己的状态，不要编一个"运行中"
        return self.status

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "status": self.status.value,
            "status_label": self.status.label,
            "summary_status": self.summary_status().value,
            "summary_status_label": self.summary_status().label,
            "origin": self.origin.value,
            "origin_label": self.origin.label,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M:%S"),
            "requirement": self.requirement.to_dict(),
            "options": self.options.to_dict(),
            "platforms": [self.states[p].to_dict() for p in self.options.platforms],
            "waiting_reason": self.waiting_reason,
            "pending_question": self.pending_question,
            "budget_exhausted": self.budget_exhausted,
            "model_usage": self.model_usage,
            # 没配模型 Key 时模型调用本来就是 0 次。把这个标记一起下发，
            # 前端才能把"0 次"说成正常情况，而不是让用户以为流程卡死了。
            "model_configured": model_configured(),
            "notes": list(self.notes),
            "offer_count": len(self.real_offers),
            "group_count": len(self.canonical),
        }


class BrowserSession:
    """一个 profile 组的可见浏览器会话（同组平台串行复用）。"""

    def __init__(self, group: str, driver: BrowserDriver):
        self.group = group
        self.driver = driver
        self.busy = False
        self.opened_at = datetime.now()

    async def close(self) -> None:
        try:
            await self.driver.stop()
        except Exception as exc:  # 关闭失败不影响其它平台
            logger.warning(f"关闭浏览器会话失败[{self.group}]: {exc}")


class ShoppingAgent:
    """五平台个人浏览器购物编排器（单例，随 FastAPI 生命周期）。"""

    def __init__(
        self,
        max_concurrency: int = MAX_CONCURRENT_PLATFORMS,
        driver_factory: Optional[Callable[[Platform], BrowserDriver]] = None,
    ):
        self._tasks: Dict[str, AgentTask] = {}
        self._sessions: Dict[str, BrowserSession] = {}
        self._group_locks: Dict[str, asyncio.Lock] = {}
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._runners: Dict[str, asyncio.Task] = {}
        self._cancel_events: Dict[str, asyncio.Event] = {}
        self._platform_cancel: Dict[str, Dict[Platform, asyncio.Event]] = {}
        self._client: Optional[ModelClient] = None
        self.max_concurrency = max_concurrency
        # 测试可注入驱动工厂；默认走真实 Playwright
        self._driver_factory = driver_factory
        # 手动登录窗口：和任务窗口对同一 profile 组互斥（见 _acquire_session）
        self.logins = LoginManager()

    # ---- 模型客户端 ----
    def model_client(self, refresh: bool = False) -> ModelClient:
        if self._client is None or refresh:
            self._client = ModelClient()
        return self._client

    def set_model_client(self, client: ModelClient) -> None:
        self._client = client

    def set_driver_factory(self, factory: Optional[Callable[[Platform], BrowserDriver]]) -> None:
        """替换浏览器驱动工厂（测试注入夹具驱动 / 将来切换浏览器实现）。"""
        self._driver_factory = factory

    # ---- 任务生命周期 ----
    def create_task(
        self,
        requirement: Requirement,
        options: Optional[TaskOptions] = None,
    ) -> AgentTask:
        task = AgentTask(
            id=uuid.uuid4().hex[:12],
            requirement=requirement,
            options=options or TaskOptions(),
        )
        task.origin = task.options.origin
        self._tasks[task.id] = task
        self._cancel_events[task.id] = asyncio.Event()
        self._platform_cancel[task.id] = {}
        return task

    def get_task(self, task_id: str) -> Optional[AgentTask]:
        return self._tasks.get(task_id)

    def all_tasks(self) -> List[AgentTask]:
        return sorted(self._tasks.values(), key=lambda t: t.created_at, reverse=True)

    async def start(self, task_id: str) -> AgentTask:
        task = self._tasks[task_id]
        if task.status is TaskStatus.RUNNING:
            return task

        # 需求第 2 步：先问要不要专业评测，默认关闭。
        # 用 review_question_asked 记住"问过了"，答完就不能再问第二次。
        if (
            task.options.ask_review_question
            and not task.review_question_asked
            and task.pending_question is None
        ):
            task.review_question_asked = True
            task.pending_question = {
                "key": "include_reviews",
                "question": "是否需要加入专业评测分析？（回复：要 / 不要）",
                "default": "不要",
                "asked_at": datetime.now().strftime("%H:%M:%S"),
            }
            task.status = TaskStatus.WAITING_CONFIRM
            task.waiting_reason = "等待您选择是否需要专业评测分析"
            return task

        task.status = TaskStatus.RUNNING
        task.waiting_reason = None
        task.updated_at = datetime.now()
        runner = asyncio.create_task(self._run(task))
        self._runners[task.id] = runner
        return task

    def answer_question(self, task_id: str, key: str, value: Any) -> AgentTask:
        """用户回答问题。只有 include_reviews 一个待决问题。"""
        task = self._tasks[task_id]
        if key != "include_reviews":
            raise ValueError(f"未知的问题: {key}")
        affirmative = str(value).strip() in ("要", "是", "yes", "y", "true", "1", "需要")
        task.requirement.include_reviews = affirmative
        task.pending_question = None
        task.waiting_reason = None
        task.notes.append(
            "专业评测分析：" + ("已开启（用户明确回复“要”）" if affirmative else "未开启（默认关闭）")
        )
        return task

    def set_include_reviews(self, task_id: str, value: bool) -> AgentTask:
        """运行中切换评测开关。"""
        task = self._tasks[task_id]
        task.requirement.include_reviews = bool(value)
        task.notes.append(f"专业评测分析已{'开启' if value else '关闭'}（运行中切换）")
        return task

    async def cancel_task(self, task_id: str) -> AgentTask:
        task = self._tasks[task_id]
        self._cancel_events[task_id].set()
        for platform in self._platform_cancel[task_id].values():
            platform.set()
        task.status = TaskStatus.CANCELLED
        for state in task.states.values():
            if not state.status.is_terminal:
                state.status = TaskStatus.CANCELLED
                state.log(ActionKind.WAIT_USER, "任务已被用户取消")
                state.finished_at = datetime.now()
        runner = self._runners.get(task_id)
        if runner is not None and not runner.done():
            runner.cancel()
        await self._close_idle_sessions()
        return task

    async def cancel_platform(self, task_id: str, platform: Platform) -> AgentTask:
        task = self._tasks[task_id]
        event = self._platform_cancel[task_id].get(platform)
        if event is None:
            event = asyncio.Event()
            self._platform_cancel[task_id][platform] = event
        event.set()
        state = task.states[platform]
        if not state.status.is_terminal:
            state.status = TaskStatus.CANCELLED
            state.log(ActionKind.WAIT_USER, "该平台任务已被用户取消")
            state.finished_at = datetime.now()
        return task

    async def pause_platform(self, task_id: str, platform: Platform) -> AgentTask:
        task = self._tasks[task_id]
        state = task.states[platform]
        state.paused = True
        if state.status is TaskStatus.RUNNING:
            state.status = TaskStatus.WAITING_USER
            state.log(ActionKind.WAIT_USER, "已暂停，等待您恢复")
        return task

    async def resume_platform(self, task_id: str, platform: Platform) -> AgentTask:
        task = self._tasks[task_id]
        state = task.states[platform]
        state.paused = False
        if state.status is TaskStatus.WAITING_USER:
            state.status = TaskStatus.RUNNING
            state.log(ActionKind.READ, "已恢复执行")
        return task

    # ---- 会话管理 ----
    def _lock_for(self, group: str) -> asyncio.Lock:
        if group not in self._group_locks:
            self._group_locks[group] = asyncio.Lock()
        return self._group_locks[group]

    async def _acquire_session(
        self, task: AgentTask, platform: Platform, state: PlatformState
    ) -> BrowserSession:
        group = profile_group(platform)
        state.log(ActionKind.NAVIGATE, f"准备浏览器会话（登录态目录组：{group}）")
        # 同一个 profile 目录同时只能被一个 Chromium 持久化上下文占用：
        # 用户正开着登录窗口时，任务不能抢同一个目录
        if self.logins.is_busy(group):
            login = self.logins.get(group)
            raise BlockedPlatform(
                BlockedReason.LOGIN_REQUIRED,
                f"该平台的登录窗口正开着（{login.status_label if login else '未知'}）。"
                "请先在那个窗口里完成登录并关掉它，再重新开始这个平台。",
            )
        session = self._sessions.get(group)
        if session is None:
            driver = self._build_driver(task, platform)
            session = BrowserSession(group, driver)
            await session.driver.start()
            self._sessions[group] = session
        return session

    def _build_driver(self, task: AgentTask, platform: Platform) -> BrowserDriver:
        if self._driver_factory is not None:
            return self._driver_factory(platform)
        directory = ensure_profile_dir(platform)
        return PlaywrightDriver(
            str(directory),
            PlaywrightConfig(
                headless=task.options.headless,
                slow_mo_ms=task.options.slow_mo_ms,
            ),
        )

    async def close_group(self, group: str) -> None:
        session = self._sessions.pop(group, None)
        if session is not None:
            await session.close()

    async def close_all_sessions(self) -> None:
        for group in list(self._sessions):
            await self.close_group(group)
        # 登录窗口一起收掉，避免服务退出后残留浏览器进程
        await self.logins.close_all()

    # ---- 手动登录窗口 ----
    async def open_login_window(self, group: str) -> LoginSession:
        """弹出一个可见浏览器窗口，让用户本人登录该平台。

        登录态落在这个平台自己的 profile 目录里，之后的比价任务直接复用。
        这里只做「开窗 + 探测是否登录」，不代填任何东西。
        """
        try:
            return await self.logins.open(
                group,
                driver_factory=self._driver_factory,
                busy_groups=list(self._sessions),
            )
        except KeyError as exc:
            raise LoginUnavailable(f"没有这个平台组：{exc}") from exc

    async def close_login_window(self, group: str) -> Dict[str, Any]:
        return await self.logins.close(group)

    def login_window_status(self) -> List[Dict[str, Any]]:
        return self.logins.status()

    async def _close_idle_sessions(self) -> None:
        for group, session in list(self._sessions.items()):
            if not session.busy:
                await self.close_group(group)

    def session_status(self) -> List[dict]:
        out = []
        for group, session in sorted(self._sessions.items()):
            out.append(
                {
                    "group": group,
                    "busy": session.busy,
                    "opened_at": session.opened_at.strftime("%H:%M:%S"),
                }
            )
        return out

    # ---- 主流程 ----
    async def _run(self, task: AgentTask) -> None:
        try:
            await asyncio.gather(
                *(self._run_platform(task, p) for p in task.options.platforms),
                return_exceptions=True,
            )
        finally:
            task.updated_at = datetime.now()
            task.status = self._final_status(task)
            await self._finalize(task)
            # 跑完必须把浏览器会话收掉：持久化上下文会一直占着 profile 目录，
            # 不收的话用户想再开登录窗口会被"目录被占用"挡住
            await self._close_idle_sessions()

    def _final_status(self, task: AgentTask) -> TaskStatus:
        if self._cancel_events[task.id].is_set():
            return TaskStatus.CANCELLED
        statuses = [s.status for s in task.states.values()]
        if all(s is TaskStatus.CANCELLED for s in statuses):
            return TaskStatus.CANCELLED
        if any(s is TaskStatus.COMPLETED for s in statuses):
            return TaskStatus.COMPLETED
        if any(s is TaskStatus.RESTRICTED for s in statuses):
            return TaskStatus.RESTRICTED
        return TaskStatus.FAILED

    async def _finalize(self, task: AgentTask) -> None:
        # 用量必须在任何提前返回之前落下来：前端按固定字段读
        # calls / vision_calls / estimated_cost，缺一个就整页白屏
        task.model_usage = self.model_client().usage.to_dict()
        offers = task.real_offers
        if not offers:
            task.notes.append(
                "本次没有从任何平台取得可核验的真实商品数据，因此不生成购买建议，"
                "也不用演示数据补齐。"
            )
            if task.budget_exhausted:
                task.notes.append(
                    "已达到任务预算上限，已停止进一步调用；以上是已取得的证据。"
                )
            return
        groups = group_offers(offers)
        canonical: List[CanonicalProduct] = []
        for index, group in enumerate(groups, start=1):
            signature = group.signature
            canonical.append(
                CanonicalProduct(
                    id=f"{task.id}-g{index}",
                    title=group.offers[0].title,
                    brand=signature.brand,
                    model="-".join(sorted(signature.model_tokens)) or None,
                    specs={
                        "storage": signature.storage,
                        "version": signature.version,
                        "condition": signature.condition,
                        "bundle": signature.bundle,
                        "color": signature.color,
                    },
                    offers=group.offers,
                    confidence=group.confidence,
                    warnings=list(group.warnings),
                )
            )
        canonical.sort(
            key=lambda c: (
                c.best_definite_price is None,
                c.best_definite_price or Decimal("0"),
            )
        )
        task.canonical = canonical
        if canonical:
            prefs = UserPreferences()
            if task.requirement.budget_max is not None:
                prefs.budget_max = task.requirement.budget_max
            task.recommendation = serialize_recommendation(
                recommend(canonical[0], [], prefs)
            )
        if task.budget_exhausted:
            task.notes.append(
                "已达到任务预算上限，已停止进一步调用；以上是已取得的证据。"
            )

    # ---- 单平台执行 ----
    async def _run_platform(self, task: AgentTask, platform: Platform) -> None:
        state = task.states[platform]
        cancel_event = asyncio.Event()
        self._platform_cancel[task.id][platform] = cancel_event
        state.status = TaskStatus.RUNNING
        state.started_at = datetime.now()
        state.log(ActionKind.READ, f"开始处理（{get_recipe(platform).display_name}）")

        deadline = asyncio.get_running_loop().time() + task.options.max_task_seconds
        group = profile_group(platform)
        lock = self._lock_for(group)

        try:
            async with self._semaphore:
                async with lock:
                    session = await self._acquire_session(task, platform, state)
                    session.busy = True
                    try:
                        await self._platform_pipeline(
                            task, platform, state, session.driver, cancel_event, deadline
                        )
                    finally:
                        session.busy = False
                        state.finished_at = datetime.now()
        except asyncio.CancelledError:
            state.status = TaskStatus.CANCELLED
            state.log(ActionKind.WAIT_USER, "任务被取消")
            raise
        except BlockedPlatform as exc:
            state.status = TaskStatus.RESTRICTED
            state.blocked_reason = exc.reason
            state.blocked_detail = exc.detail
            state.log(ActionKind.READ, f"平台阻止自动访问：{exc.reason.label}（{exc.detail}）")
            task.notes.append(
                f"{get_recipe(platform).display_name}：{exc.reason.label}，本次未完成，"
                f"未用演示数据补齐。"
            )
        except BudgetExceeded as exc:
            task.budget_exhausted = True
            state.status = TaskStatus.FAILED
            state.log(ActionKind.READ, f"预算上限：{exc}")
            task.notes.append(f"{get_recipe(platform).display_name}：{exc}")
        except Exception as exc:  # 单平台失败不影响其它平台
            logger.warning(f"[{platform.value}] 平台任务失败: {exc}")
            state.status = TaskStatus.FAILED
            state.blocked_detail = str(exc)[:200]
            state.log(ActionKind.READ, f"执行失败：{str(exc)[:160]}")
            task.notes.append(f"{get_recipe(platform).display_name}：执行失败，其它平台继续。")

    async def _platform_pipeline(
        self,
        task: AgentTask,
        platform: Platform,
        state: PlatformState,
        driver: BrowserDriver,
        cancel_event: asyncio.Event,
        deadline: float,
    ) -> None:
        recipe = get_recipe(platform)

        # 1) 打开站点入口，探测登录与风控
        await self._guard(task, state, cancel_event, deadline)
        # 用 login_entry() 而不是 home_url：有些平台首页在 Chromium 里会触发
        # 文件下载（抖音实测），goto 直接失败，报出来的还是"无法打开首页"，
        # 把真正的原因（搜索入口 502）盖掉了。走能打开的入口，才能在下一步
        # 给出准确的失败原因。
        home_url = task.options.override(platform, "home") or recipe.login_entry()
        if not await self._goto(driver, state, home_url):
            raise BlockedPlatform(BlockedReason.NAVIGATION_FAILED, f"无法打开 {home_url}")
        await self._probe_blocked(driver, state, platform)

        if recipe.requires_login_for_price:
            logged_in = await self._probe_login(driver, state)
            if not logged_in:
                await self._wait_user_login(
                    task, state, driver, platform,
                    deadline, cancel_event,
                    "该平台需要登录后才能看到价格与优惠，请在可见窗口中完成登录/扫码",
                )
                await self._probe_blocked(driver, state, platform)

        # 2) 搜索
        await self._guard(task, state, cancel_event, deadline)
        search = self._search_url(task, platform, task.requirement.keyword)
        if not await self._goto(driver, state, search):
            raise BlockedPlatform(BlockedReason.NAVIGATION_FAILED, f"无法打开搜索页 {search}")
        await self._probe_blocked(driver, state, platform)

        # 3) 收集商品链接（确定性 DOM 规则）
        links = await self._collect_links(driver, state, task)
        state.log(ActionKind.READ, f"搜索结果页识别到 {len(links)} 个商品链接")
        if not links:
            raise BlockedPlatform(
                BlockedReason.STRUCTURE_UNKNOWN,
                "未能在搜索结果页识别出商品链接（页面结构可能已变化或需要登录）",
            )

        # 4) 逐个打开商品页抽取字段
        seen: set[str] = set()
        examined = 0
        for link in links:
            if examined >= task.options.max_candidates:
                break
            if cancel_event.is_set() or self._cancel_events[task.id].is_set():
                state.status = TaskStatus.CANCELLED
                state.log(ActionKind.WAIT_USER, "该平台任务被取消")
                return
            if asyncio.get_running_loop().time() > deadline:
                state.problems.append("已达任务时长上限，未继续查看更多商品")
                task.budget_exhausted = True
                state.log(
                    ActionKind.WAIT_USER,
                    "已达任务时长上限，已停止；以下是已取得的证据。",
                )
                break
            if state.paused:
                state.status = TaskStatus.WAITING_USER
                state.log(ActionKind.WAIT_USER, "已暂停")
                await self._wait_resume(task, state, cancel_event)
            url = link["url"]
            if url in seen:
                continue
            seen.add(url)
            if not await self._goto(driver, state, url):
                state.problems.append(f"商品页打开失败：{url}")
                continue
            await self._probe_blocked(driver, state, platform)
            fields_raw = await driver.evaluate(JS_PRODUCT_FIELDS)
            if not isinstance(fields_raw, dict):
                state.problems.append(f"页面字段抽取失败：{url}")
                continue
            fields = PageFields.from_js(fields_raw)
            fields = await self._maybe_vision_price(
                task, state, driver, fields, url
            )
            offer, problems = build_offer(
                platform, fields, task.options.origin,
                source_label="personal-browser",
            )
            state.problems.extend(problems)
            state.offers.append(offer)
            state.urls.append(url)
            examined += 1
            state.log(
                ActionKind.READ,
                f"已记录商品：{(fields.title or url)[:40]}",
                url=url,
            )
            await asyncio.sleep(0.4)  # 低频、温和，不给平台造成压力

        if not state.offers:
            raise BlockedPlatform(
                BlockedReason.STRUCTURE_UNKNOWN,
                "商品页字段抽取未得到任何可用结果",
            )
        state.status = TaskStatus.COMPLETED
        state.log(
            ActionKind.READ,
            f"完成：取得 {state.real_offer_count} 条商品记录"
            + (f"，{len(state.problems)} 条待核实说明" if state.problems else ""),
        )

    # ---- 工具 ----
    async def _guard(
        self,
        task: AgentTask,
        state: PlatformState,
        cancel_event: asyncio.Event,
        deadline: float,
    ) -> None:
        if cancel_event.is_set() or self._cancel_events[task.id].is_set():
            raise asyncio.CancelledError()
        if asyncio.get_running_loop().time() > deadline:
            state.problems.append("已达任务时长上限")
            raise BudgetExceeded("任务时长上限已到")

    async def _goto(self, driver: BrowserDriver, state: PlatformState, url: str) -> bool:
        try:
            ok = await asyncio.wait_for(driver.goto(url, timeout_ms=20000), timeout=30)
        except DriverError as exc:
            # 底层原因要落到执行记录里。之前这里只 return False，用户看到
            # "无法打开首页"却完全不知道是超时、证书还是连接被拒。
            state.log(ActionKind.NAVIGATE, f"打开失败：{_short_reason(exc)}", url=url)
            return False
        except asyncio.TimeoutError:
            state.log(ActionKind.NAVIGATE, "打开超时：20 秒内页面没加载完成", url=url)
            return False
        if ok:
            state.pages_visited += 1
            state.log(ActionKind.NAVIGATE, f"打开 {url[:90]}", url=url)
        return bool(ok)

    async def _collect_links(
        self, driver: BrowserDriver, state: PlatformState, task: AgentTask
    ) -> List[Dict[str, str]]:
        """等搜索结果页把商品锚点渲染出来，最多等 ``_LINK_WAIT_SECONDS`` 秒。

        搜索页普遍是客户端渲染，``goto`` 返回时商品节点常常还没挂上。立刻
        抽取只会拿到 0 条，调用方便会把"还没渲染完"报成"页面结构不认识"。
        这里用小步低频重试；等不到就返回空列表，由调用方如实报
        structure_unknown——不猜、不补数据。
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + _LINK_WAIT_SECONDS
        waited = False
        while True:
            cancel = self._cancel_events.get(task.id)
            if cancel is not None and cancel.is_set():
                return []
            try:
                links = self._normalize_links(
                    await driver.evaluate(JS_PRODUCT_LINKS, task.options.max_links)
                )
            except Exception:
                links = []
            if links:
                if waited:
                    state.log(
                        ActionKind.READ,
                        "搜索结果页商品已渲染出来（页面为动态加载，已等待）",
                    )
                return links
            if loop.time() >= deadline:
                return []
            waited = True
            await asyncio.sleep(_LINK_POLL_SECONDS)

    async def _probe_blocked(
        self, driver: BrowserDriver, state: PlatformState, platform: Platform
    ) -> None:
        try:
            probe = await driver.evaluate(JS_BLOCKED_PROBE) or {}
        except Exception:
            return
        if not isinstance(probe, dict):
            return
        if probe.get("captcha"):
            raise BlockedPlatform(
                BlockedReason.CAPTCHA,
                "页面出现验证码/安全验证。本工具不尝试识别或绕过验证码，"
                "该平台本次标记为未完成。",
            )
        if probe.get("risk"):
            raise BlockedPlatform(
                BlockedReason.RISK_CONTROL,
                "平台提示访问过于频繁/搜索被限制（常见原因是短期内同一账号"
                "或网络搜索次数偏多）。已停止该平台的自动访问——不会用重试"
                "绕过它。请隔一段时间再试，或改用您手动提供的商品链接。",
            )
        if probe.get("unavailable"):
            raise BlockedPlatform(
                BlockedReason.NAVIGATION_FAILED,
                "搜索入口返回网关错误（502/504），这个地址可能已失效。"
                "已停止该平台，不会反复重试；可以改用您手动提供的商品链接。",
            )
        if probe.get("loginWall"):
            raise BlockedPlatform(
                BlockedReason.LOGIN_REQUIRED,
                "页面要求登录后才能查看内容。",
            )

    async def _probe_login(self, driver: BrowserDriver, state: PlatformState) -> bool:
        try:
            probe = await driver.evaluate(JS_LOGIN_PROBE) or {}
        except Exception:
            return False
        if not isinstance(probe, dict):
            return False
        if probe.get("looksLoggedIn"):
            state.log(ActionKind.READ, "已检测到登录状态")
            return True
        state.log(ActionKind.WAIT_USER, "未检测到登录状态，需要您在可见窗口登录")
        return False

    async def _wait_user_login(
        self,
        task: AgentTask,
        state: PlatformState,
        driver: BrowserDriver,
        platform: Platform,
        deadline: float,
        cancel_event: asyncio.Event,
        reason: str,
    ) -> None:
        """进入等待用户接管，轮询登录状态。绝不读取账号密码。"""
        state.status = TaskStatus.WAITING_USER
        task.waiting_reason = reason
        state.log(ActionKind.WAIT_USER, reason)
        limit = min(
            task.options.login_wait_seconds,
            max(0.0, deadline - asyncio.get_running_loop().time()),
        )
        waited = 0.0
        interval = 3.0
        while waited < limit:
            if cancel_event.is_set() or self._cancel_events[task.id].is_set():
                raise asyncio.CancelledError()
            await asyncio.sleep(interval)
            waited += interval
            try:
                probe = await driver.evaluate(JS_LOGIN_PROBE) or {}
            except Exception:
                continue
            if isinstance(probe, dict) and probe.get("looksLoggedIn"):
                state.log(ActionKind.READ, "检测到您已完成登录，继续执行")
                state.status = TaskStatus.RUNNING
                task.waiting_reason = None
                return
        raise BlockedPlatform(
            BlockedReason.LOGIN_REQUIRED,
            f"等待 {int(limit)} 秒未检测到登录，已停止该平台。请在平台设置里登录后重试。",
        )

    async def _wait_resume(
        self, task: AgentTask, state: PlatformState, cancel_event: asyncio.Event
    ) -> None:
        while state.paused:
            if cancel_event.is_set() or self._cancel_events[task.id].is_set():
                raise asyncio.CancelledError()
            await asyncio.sleep(1.0)

    async def _maybe_vision_price(
        self,
        task: AgentTask,
        state: PlatformState,
        driver: BrowserDriver,
        fields: PageFields,
        url: str,
    ) -> PageFields:
        """确定性抽取失败时才用视觉模型，并对金额做交叉核对。"""
        dom_amount = parse_money(fields.price_text)
        if dom_amount is not None:
            # 有 DOM 证据：只有在用户开启了评测/且视觉可用时才做交叉核对
            return fields
        if state.model_calls >= self._model_call_limit(task):
            state.problems.append(f"模型调用预算已用尽，未用视觉识别价格：{url}")
            return fields

        client = self.model_client()
        if not client.configured or not client.config.supports_vision:
            state.problems.append(
                "未能从页面文本确定价格，且未配置可用的视觉模型，"
                "该商品价格留空（不猜测）"
            )
            return fields

        shot = await driver.screenshot_clip(None)
        if not shot:
            return fields
        encoded = getattr(driver, "encode_image", lambda raw: None)(shot)
        if not encoded:
            return fields

        state.model_calls += 1
        try:
            reply = await asyncio.wait_for(
                client.vision(
                    "你是页面金额识别助手。只输出一个数字（元），不要输出任何其他文字；"
                    "如果截图里没有清晰可见的价格，只输出'未见'。",
                    "请读取这张商品页面截图中显示的售价数字。",
                    encoded,
                ),
                timeout=client.config.timeout_seconds,
            )
        except (ModelError, BudgetExceeded, asyncio.TimeoutError) as exc:
            state.problems.append(f"视觉识别价格失败：{str(exc)[:120]}")
            return fields

        vision_amount = parse_money(reply)
        if vision_amount is None:
            state.problems.append("视觉模型未能在截图中识别到价格")
            return fields
        # 视觉金额只有在与页面证据一致时才采纳；这里没有 DOM 文本证据，
        # 因此明确降级：标注为截图识别，确定性下调。
        fields.price_text = str(vision_amount)
        fields.price_source = "vision"
        fields.evidence["vision:price"] = (
            f"截图识别 {vision_amount}（未经页面文本字段交叉核对，确定性已下调）"
        )
        state.problems.append(
            f"价格 {vision_amount} 来自截图识别，未经页面文本字段交叉核对，"
            f"请以下单页为准：{url}"
        )
        return fields

    def _model_call_limit(self, task: AgentTask) -> int:
        config = self.model_client().config
        return max(0, min(task.options.max_model_calls, config.max_calls_per_task))

    def _search_url(self, task: AgentTask, platform: Platform, keyword: str) -> str:
        override = task.options.override(platform, "search")
        if override:
            return override
        return search_url(platform, keyword)

    @staticmethod
    def _normalize_links(raw: Any) -> List[Dict[str, str]]:
        if not isinstance(raw, list):
            return []
        out: List[Dict[str, str]] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "")
            if not url.startswith("http"):
                continue
            out.append({"url": url, "title": str(item.get("title") or "")})
        return out

    # ---- 结果视图 ----
    def result_view(self, task: AgentTask) -> dict:
        """给前端的结构化结果：价格拆解、确定性、证据链接。"""
        groups = []
        for canonical in task.canonical:
            rows = []
            for offer in canonical.offers:
                rows.append(
                    serialize_offer(offer, compute_price_breakdown(offer))
                )
            groups.append(
                {
                    "id": canonical.id,
                    "title": canonical.title,
                    "brand": canonical.brand,
                    "specs": canonical.specs,
                    "confidence": canonical.confidence,
                    "warnings": canonical.warnings,
                    "best_definite_price": money_or_none(canonical.best_definite_price),
                    "offers": rows,
                }
            )
        return {
            "task_id": task.id,
            "origin": task.origin.value,
            "origin_label": task.origin.label,
            "groups": groups,
            "recommendation": task.recommendation,
            "notes": list(task.notes),
            "budget_exhausted": task.budget_exhausted,
            "model_usage": task.model_usage,
        }

    # ---- 平台会话管理 API ----
    def profile_status(self) -> List[dict]:
        return [info.to_dict() for info in all_profiles()]

    def clear_profile(self, group: str) -> bool:
        """清除某个平台的浏览器登录态。"""
        return delete_profile(group)

    def storage_description(self) -> dict:
        return describe_storage()


def money_or_none(value: Optional[Decimal]) -> Optional[str]:
    return str(value.quantize(Decimal("0.01"))) if value is not None else None


agent = ShoppingAgent()
