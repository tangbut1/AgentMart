"""个人浏览器版的枚举：任务状态、价格确定性、数据来源。

价格确定性对应需求里的四档，并映射到 domain 的 ConditionKind：

1. ``PAGE_PUBLIC``      页面公开标价/页面价          → 标价本身，不是优惠
2. ``ACCOUNT_COUPON``   用户账号可见的已领券/可用券   → UNCONDITIONAL
                       （仅当页面本身显示它适用于该商品）
3. ``CONDITIONAL``      满足条件后的预计价            → CONDITIONAL
4. ``PREPAYMENT``       结算页显示但尚未付款的待支付金额 → CONDITIONAL
                       （未经用户确认不得作为结论）

任何一档无法核实 → ``UNVERIFIABLE``，只列示、不计入到手价。
"""
from __future__ import annotations

from enum import Enum


class TaskStatus(str, Enum):
    """平台任务状态机。"""

    PENDING = "pending"              # 待开始
    RUNNING = "running"              # 运行中
    WAITING_USER = "waiting_user"    # 等待用户登录/接管
    WAITING_CONFIRM = "waiting_confirm"  # 等待用户对某个具体动作确认
    COMPLETED = "completed"          # 完成
    RESTRICTED = "restricted"        # 平台阻止自动访问（验证码/风控/限制）
    FAILED = "failed"                # 失败
    CANCELLED = "cancelled"          # 用户取消

    @property
    def label(self) -> str:
        return {
            TaskStatus.PENDING: "待开始",
            TaskStatus.RUNNING: "运行中",
            TaskStatus.WAITING_USER: "等待您接管",
            TaskStatus.WAITING_CONFIRM: "等待您确认",
            TaskStatus.COMPLETED: "已完成",
            TaskStatus.RESTRICTED: "平台限制",
            TaskStatus.FAILED: "失败",
            TaskStatus.CANCELLED: "已取消",
        }[self]

    @property
    def is_terminal(self) -> bool:
        return self in (
            TaskStatus.COMPLETED,
            TaskStatus.RESTRICTED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        )


class PriceCertainty(str, Enum):
    """价格/优惠的确定性等级（见模块 docstring）。"""

    PAGE_PUBLIC = "page_public"
    ACCOUNT_COUPON = "account_coupon"
    CONDITIONAL = "conditional"
    PREPAYMENT = "prepayment"
    UNVERIFIABLE = "unverifiable"

    @property
    def label(self) -> str:
        return {
            PriceCertainty.PAGE_PUBLIC: "页面公开价",
            PriceCertainty.ACCOUNT_COUPON: "账号可见可用券",
            PriceCertainty.CONDITIONAL: "满足条件的预计价",
            PriceCertainty.PREPAYMENT: "结算页待支付金额",
            PriceCertainty.UNVERIFIABLE: "无法核实",
        }[self]


class DataOrigin(str, Enum):
    """结果数据的来源类型 —— 前端必须原样展示，不得混淆。"""

    REAL_PLATFORM_PAGE = "real_platform_page"  # 用户本次在真实平台页面核对到
    USER_PROVIDED = "user_provided"            # 用户手动提供的链接/优惠/截图
    TEST_FIXTURE = "test_fixture"              # 本地受控测试页面
    DEMO = "demo"                              # 演示数据（虚构）

    @property
    def label(self) -> str:
        return {
            DataOrigin.REAL_PLATFORM_PAGE: "真实平台页面",
            DataOrigin.USER_PROVIDED: "您手动提供",
            DataOrigin.TEST_FIXTURE: "测试夹具",
            DataOrigin.DEMO: "演示数据",
        }[self]


class ActionKind(str, Enum):
    """Agent 允许执行的动作。

    只读动作可直接执行；``MUTATING`` 一类必须逐次取得用户明确同意，
    本版本不实现任何 MUTATING 动作。
    """

    NAVIGATE = "navigate"      # 打开页面
    READ = "read"              # 读取页面字段
    SCROLL = "scroll"          # 滚动以加载内容
    SCREENSHOT = "screenshot"  # 裁剪截图作为证据
    WAIT_USER = "wait_user"    # 等待用户完成登录/接管
    ASK_CONFIRM = "ask_confirm"  # 请求用户确认下一步
    MUTATING = "mutating"      # 会改变账号状态的动作（本版本不执行）

    @property
    def is_read_only(self) -> bool:
        return self is not ActionKind.MUTATING


class BlockedReason(str, Enum):
    """平台阻止自动访问的原因。"""

    CAPTCHA = "captcha"
    RISK_CONTROL = "risk_control"
    LOGIN_REQUIRED = "login_required"
    LOGIN_EXPIRED = "login_expired"
    RATE_LIMITED = "rate_limited"
    NAVIGATION_FAILED = "navigation_failed"
    STRUCTURE_UNKNOWN = "structure_unknown"

    @property
    def label(self) -> str:
        return {
            BlockedReason.CAPTCHA: "需要验证码",
            BlockedReason.RISK_CONTROL: "触发平台风控",
            BlockedReason.LOGIN_REQUIRED: "需要登录",
            BlockedReason.LOGIN_EXPIRED: "登录已过期",
            BlockedReason.RATE_LIMITED: "访问过于频繁",
            BlockedReason.NAVIGATION_FAILED: "页面打开失败",
            BlockedReason.STRUCTURE_UNKNOWN: "页面结构无法识别",
        }[self]
