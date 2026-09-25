"""风控/验证码的「人机协同接管」。

这是从"遇到风控直接放弃"转向"请用户滑一下、我接着跑"的那一步，
核心约定只有一条：**验证码不猜、不绕，但也不把一个用户能解开的验证
判成平台失败。**

覆盖：
- 遇到验证码/风控 → 平台进入 WAITING_USER，弹出温和提示，窗口调到最前；
- 用户处理完 → 原路返回，状态回 RUNNING，调用方像什么都没发生一样继续；
- 等过预算还没处理 → 如实记 RESTRICTED，并把"您这边没处理完"和
  "平台拦住了我们"在文案上区分开；
- 等待期间取消 → 不把取消伪装成平台限制；
- 网关错误/登录墙不是用户能解的，仍然直接判失败，不往用户身上推。
"""
from __future__ import annotations

import asyncio

import pytest

from app.browser import agent as agent_module
from app.browser.agent import (
    BlockedPlatform,
    NeedsUserTakeover,
    Requirement,
    ShoppingAgent,
    TaskOptions,
)
from app.browser.driver import ScriptedDriver
from app.browser.enums import BlockedReason, TaskStatus
from app.domain.enums import Platform


class FlakyRiskDriver(ScriptedDriver):
    """前 N 次探测报风控，之后恢复正常 —— 模拟用户滑完验证码。"""

    def __init__(self, blocked_times: int, key: str = "risk"):
        super().__init__([])
        self.blocked_times = blocked_times
        self.key = key
        self.blocked_calls = 0
        self.front_calls = 0

    async def evaluate(self, script: str, arg=None):
        head = script.strip()[:60]
        if "captcha" in head.lower() or "风控" in script or "risk" in script.lower():
            self.blocked_calls += 1
            if self.blocked_calls <= self.blocked_times:
                return {self.key: True}
            return {self.key: False}
        return None

    async def bring_to_front(self) -> None:
        self.front_calls += 1


@pytest.fixture(autouse=True)
def fast_takeover_poll(monkeypatch):
    """把 1.5 秒的轮询间隔缩到最小，否则每个接管用例都要干等。"""
    monkeypatch.setattr(agent_module, "_TAKEOVER_POLL_SECONDS", 0.01)


def _agent(driver: FlakyRiskDriver) -> ShoppingAgent:
    return ShoppingAgent(max_concurrency=1, driver_factory=lambda p: driver)


def _task(agent: ShoppingAgent) -> "object":
    return agent.create_task(
        Requirement(text="索尼 WH-1000XM5"),
        TaskOptions(platforms=[Platform.JD]),
    )


# ─── 进入接管 ────────────────────────────────────────────────────

async def test_captcha_enters_waiting_user_with_gentle_prompt():
    driver = FlakyRiskDriver(blocked_times=1, key="captcha")
    agent = _agent(driver)
    task = _task(agent)
    state = task.states[Platform.JD]

    await agent._check_blocked(
        driver, task, state, Platform.JD, asyncio.Event(), asyncio.get_running_loop().time() + 5
    )

    assert state.status is TaskStatus.RUNNING
    assert state.takeover is None
    # 窗口必须调到最前，否则"正在为您展开浏览器窗口"是句空话
    assert driver.front_calls == 1
    # 处理完后要留下痕迹：用户知道他刚帮我们过了个验证
    assert any("安全验证已通过" in s.detail for s in state.steps)
    assert any("安全验证" in s.detail and s.action == "wait_user" for s in state.steps)


async def test_waiting_state_exposes_takeover_for_the_ui():
    """WAITING_USER 期间，前端要能拿到 kind / 提示文案 / 起始时间。"""
    driver = FlakyRiskDriver(blocked_times=3, key="captcha")
    agent = _agent(driver)
    task = _task(agent)
    state = task.states[Platform.JD]
    seen = {}
    serialized = {}

    async def watch():
        while True:
            if state.takeover:
                seen.update(state.takeover)
                serialized.update(state.to_dict()["takeover"])
                return

    watcher = asyncio.create_task(watch())
    await agent._check_blocked(
        driver, task, state, Platform.JD, asyncio.Event(), asyncio.get_running_loop().time() + 5
    )
    await watcher

    assert seen["kind"] == "captcha"
    assert seen["resolved"] is False
    assert "安全验证" in seen["message"]
    assert "滑动" in seen["message"]
    assert "比价" in seen["message"]
    assert seen["since"]
    # 序列化给前端的形状要对得上
    assert serialized["kind"] == "captcha"
    assert serialized["kind_label"]
    assert serialized["message"] == seen["message"]
    # 处理完之后要清掉，卡片就不再显示"需要您接管"
    assert state.to_dict()["takeover"] is None


async def test_task_waiting_reason_points_at_the_platform():
    driver = FlakyRiskDriver(blocked_times=2, key="captcha")
    agent = _agent(driver)
    task = _task(agent)

    assert task.waiting_reason is None
    # 进入等待时任务级原因要被写上，处理完要清掉
    await agent._check_blocked(
        driver,
        task,
        task.states[Platform.JD],
        Platform.JD,
        asyncio.Event(),
        asyncio.get_running_loop().time() + 5,
    )
    assert task.waiting_reason is None


async def test_other_platform_still_waiting_keeps_task_reason():
    """五个平台并发跑：京东处理完了，淘宝还在等，任务级原因不能清空。"""
    driver = FlakyRiskDriver(blocked_times=99, key="risk")
    agent = _agent(driver)
    task = agent.create_task(
        Requirement(text="x"),
        TaskOptions(platforms=[Platform.JD, Platform.TAOBAO]),
    )
    task.states[Platform.TAOBAO].status = TaskStatus.WAITING_USER
    task.states[Platform.TAOBAO].takeover = {
        "kind": "captcha",
        "kind_label": "安全验证",
        "message": "淘宝页面出现了安全验证，正在为您展开浏览器窗口，请您在窗口中滑动一下，完成后我将继续为您比价……",
        "since": "10:00:00",
        "resolved": False,
    }

    reason = agent._other_waiting_reason(task, Platform.JD)
    assert "淘宝" in reason

    assert agent._other_waiting_reason(task, Platform.TAOBAO) is None


# ─── 等过预算 ────────────────────────────────────────────────────

async def test_timeout_marks_restricted_and_blames_the_right_side():
    """超时要如实说"等您处理但没完成"，不能含混其辞成"平台拦截"。"""
    driver = FlakyRiskDriver(blocked_times=99, key="captcha")
    agent = _agent(driver)
    task = _task(agent)
    state = task.states[Platform.JD]

    with pytest.raises(BlockedPlatform) as excinfo:
        await agent._check_blocked(
            driver,
            task,
            state,
            Platform.JD,
            asyncio.Event(),
            asyncio.get_running_loop().time() + 0.05,
        )

    assert excinfo.value.reason is BlockedReason.CAPTCHA
    assert state.status is TaskStatus.RESTRICTED
    assert state.takeover is None
    assert "没有完成" in state.blocked_detail
    assert "不会替您处理验证" in state.blocked_detail
    assert any("超时" in s.detail for s in state.steps)
    assert any("等待您处理后超时" in n for n in task.notes)


# ─── 取消 ────────────────────────────────────────────────────────

async def test_cancel_during_takeover_is_not_reported_as_platform_limit():
    driver = FlakyRiskDriver(blocked_times=99, key="risk")
    agent = _agent(driver)
    task = _task(agent)
    state = task.states[Platform.JD]
    cancel = asyncio.Event()
    cancel.set()

    with pytest.raises(asyncio.CancelledError):
        await agent._check_blocked(
            driver,
            task,
            state,
            Platform.JD,
            cancel,
            asyncio.get_running_loop().time() + 5,
        )

    assert state.status is TaskStatus.CANCELLED
    assert state.takeover is None
    assert state.blocked_reason is None


# ─── 不是用户能解的，仍然直接判失败 ──────────────────────────────

@pytest.mark.parametrize(
    "key,reason",
    [
        ("unavailable", BlockedReason.NAVIGATION_FAILED),
        ("loginWall", BlockedReason.LOGIN_REQUIRED),
    ],
)
async def test_non_takeoverable_blocks_still_fail_fast(key, reason):
    """网关 502 / 登录墙不是用户滑一下能解决的，不往用户身上推。"""
    driver = FlakyRiskDriver(blocked_times=1, key=key)
    agent = _agent(driver)
    task = _task(agent)
    state = task.states[Platform.JD]

    with pytest.raises(BlockedPlatform) as excinfo:
        await agent._check_blocked(
            driver,
            task,
            state,
            Platform.JD,
            asyncio.Event(),
            asyncio.get_running_loop().time() + 5,
        )

    assert excinfo.value.reason is reason
    assert state.status is not TaskStatus.WAITING_USER
    assert driver.front_calls == 0


async def test_normal_page_passes_through_untouched():
    driver = FlakyRiskDriver(blocked_times=0)
    agent = _agent(driver)
    task = _task(agent)
    state = task.states[Platform.JD]

    await agent._check_blocked(
        driver,
        task,
        state,
        Platform.JD,
        asyncio.Event(),
        asyncio.get_running_loop().time() + 5,
    )

    # 没遇到验证：状态原样不动，不弹窗、不记日志、不占预算
    assert state.status is TaskStatus.PENDING
    assert state.takeover is None
    assert driver.front_calls == 0
    assert state.steps == []


# ─── _still_blocked 只盯自己那一项 ───────────────────────────────

async def test_still_blocked_only_checks_its_own_flag():
    """处理验证码时页面可能短暂冒出别的提示，不能因此判成"没处理完"。"""
    driver = FlakyRiskDriver(blocked_times=1, key="captcha")
    agent = _agent(driver)

    assert await agent._still_blocked(driver, BlockedReason.CAPTCHA) is True
    # 只盯着 risk：captcha 那一项还开着，也不算 risk 没过
    assert await agent._still_blocked(driver, BlockedReason.RISK_CONTROL) is False

    driver.blocked_calls = 0
    driver.blocked_times = 0
    assert await agent._still_blocked(driver, BlockedReason.CAPTCHA) is False


async def test_still_blocked_treats_evaluate_error_as_cleared():
    """页面跳转时求值会失败，这是验证通过后的正常现象。"""

    class Boom(ScriptedDriver):
        async def evaluate(self, script, arg=None):
            raise RuntimeError("execution context was destroyed")

    agent = _agent(Boom([]))
    assert await agent._still_blocked(Boom([]), BlockedReason.CAPTCHA) is False


async def test_needs_user_takeover_carries_reason_and_detail():
    exc = NeedsUserTakeover(BlockedReason.CAPTCHA, "页面出现验证码")
    assert exc.reason is BlockedReason.CAPTCHA
    assert exc.detail == "页面出现验证码"
    assert isinstance(exc, RuntimeError)
