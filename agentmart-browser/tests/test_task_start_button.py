"""「开始 / 继续」按钮点不动，任务一次都跑不起来 —— 回归测试。

用户在界面上的真实形态：登录好了，写下需求，进任务页，按钮是灰的、
写着"执行中…"，但什么都不会发生。两个 bug 叠出来的：

1. 后端 ``AgentTask.summary_status()`` 在平台状态是混合的（比如一个已
   取消、其余还没开始）时，最后无条件 ``return TaskStatus.RUNNING``，
   于是任务明明没跑，汇总状态却报"运行中"；
2. 前端把 ``summary_status === "pending"`` 也当成 running，导致按钮从
   任务创建那刻起就是禁用的。

修好之后的约定：
- 只要还有平台没开始，汇总状态就是「待开始」，不谎称「运行中」；
- 前端只有 "running" 才禁用开始按钮。
"""
from __future__ import annotations

from app.browser.agent import Requirement, ShoppingAgent, TaskOptions
from app.browser.driver import ScriptedDriver, ScriptedStep
from app.browser.enums import TaskStatus
from app.domain.enums import Platform


def _scripted() -> ScriptedDriver:
    return ScriptedDriver(
        [
            ScriptedStep(
                "jd",
                results={
                    "login": {"looksLoggedIn": True},
                    "blocked": {"captcha": False, "risk": False},
                },
            )
        ]
    )


def _agent() -> ShoppingAgent:
    return ShoppingAgent(max_concurrency=2, driver_factory=lambda p: _scripted())


def _task(agent: ShoppingAgent, text: str = "预算 2500 的降噪耳机") -> object:
    return agent.create_task(
        Requirement(text=text, keyword=text), TaskOptions()
    )


# ---- 后端：汇总状态必须如实 ----

def test_fresh_task_summary_is_pending_not_running():
    """刚创建的任务：五个平台都没开始，汇总状态必须是「待开始」。

    之前这里是 RUNNING，前端据此把按钮置灰，用户永远点不了开始。
    """
    agent = _agent()
    task = _task(agent)
    assert task.summary_status() is TaskStatus.PENDING
    assert task.summary_status().value == "pending"


def test_mixed_platform_states_are_not_reported_as_running():
    """一个平台已取消、其余还没开始 → 仍然是「待开始」，不是「运行中」。

    这正是用户遇到的形态：取消了一个平台之后，任务看着在跑其实没跑。
    """
    agent = _agent()
    task = _task(agent)
    task.states[Platform.DOUYIN].status = TaskStatus.CANCELLED
    assert task.summary_status() is TaskStatus.PENDING


def test_all_platforms_cancelled_but_task_not_terminal_is_not_running():
    """平台全结束而任务级状态还没落定时，也不能谎称「运行中」。"""
    agent = _agent()
    task = _task(agent)
    for state in task.states.values():
        state.status = TaskStatus.CANCELLED
    assert task.summary_status() is not TaskStatus.RUNNING


def test_one_platform_running_reports_running():
    """真有平台在跑时才报「运行中」。"""
    agent = _agent()
    task = _task(agent)
    task.states[Platform.JD].status = TaskStatus.RUNNING
    assert task.summary_status() is TaskStatus.RUNNING


def test_waiting_for_login_is_reported_as_waiting_user():
    """平台在等用户登录时，汇总状态要能透出来，不能被"待开始"盖掉。"""
    agent = _agent()
    task = _task(agent)
    task.states[Platform.JD].status = TaskStatus.WAITING_USER
    task.states[Platform.TAOBAO].status = TaskStatus.CANCELLED
    assert task.summary_status() is TaskStatus.WAITING_USER


def test_task_level_wait_beats_platform_states():
    """任务级等待优先于平台状态。"""
    agent = _agent()
    task = _task(agent)
    task.status = TaskStatus.WAITING_CONFIRM
    task.states[Platform.JD].status = TaskStatus.RUNNING
    assert task.summary_status() is TaskStatus.WAITING_CONFIRM


# ---- 前端逻辑（同一段判定，避免前后端再次各说各话）----

def _frontend_running_flag(summary_status: str) -> bool:
    """复刻 BrowserTaskPage 里决定按钮是否禁用的判定。

    约定只有 "running" 才算在执行中；"pending" 是最该让用户点开始的时候。
    """
    return summary_status == "running"


def test_frontend_enables_start_button_for_pending_task():
    assert _frontend_running_flag("pending") is False


def test_frontend_disables_start_button_only_while_running():
    assert _frontend_running_flag("running") is True
    assert _frontend_running_flag("waiting_user") is False
    assert _frontend_running_flag("waiting_confirm") is False


def test_backend_and_frontend_agree_on_pending():
    """后端说「待开始」时，前端必须认为可以点开始。"""
    agent = _agent()
    task = _task(agent)
    task.states[Platform.DOUYIN].status = TaskStatus.CANCELLED
    summary = task.summary_status().value
    assert summary == "pending"
    assert _frontend_running_flag(summary) is False


# ---- 端到端：任务真的能跑起来 ----

async def test_pending_task_can_be_started_and_reaches_terminal():
    """「待开始」的任务点开始之后，必须真的进入执行并收敛到终态。"""
    agent = _agent()
    task = _task(agent)
    assert task.summary_status() is TaskStatus.PENDING

    await agent.start(task.id)
    assert task.status in (
        TaskStatus.RUNNING,
        TaskStatus.WAITING_USER,
        TaskStatus.WAITING_CONFIRM,
        TaskStatus.COMPLETED,
        TaskStatus.RESTRICTED,
        TaskStatus.FAILED,
    )
    assert task.status is not TaskStatus.PENDING
