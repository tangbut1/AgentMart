"""「要不要加入专业评测分析」这个待决问题的回归测试。

这个 bug 的真实形态：答完"不要"之后，任务并没有往下跑，而是又被
问了一遍同样的问题 —— 因为 start() 只看 pending_question 是否为空。
用户在界面上看到的现象是"卡在第 2 步，永远不动"。

覆盖：
- start() 会把问题问出来，并把任务置为等待确认；
- 汇总状态如实报"等待您确认"，不谎称"待开始"；
- 答完之后再 start 会直接开跑，问题不会第二次出现；
- 问题连同等待原因一起落库，重启回读后不会"问过又忘了"。
"""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.browser.agent import Requirement, ShoppingAgent, TaskOptions
from app.browser.driver import ScriptedDriver, ScriptedStep
from app.browser.enums import TaskStatus
from app.browser.login import WAITING_LOGIN
from app.browser import store
from app.database import Base
from app.domain.enums import Platform


def _agent() -> ShoppingAgent:
    return ShoppingAgent(max_concurrency=2, driver_factory=lambda p: _scripted())


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


def _task(agent: ShoppingAgent):
    return agent.create_task(
        Requirement(text="预算 600 元买冲锋衣", keyword="冲锋衣"),
        TaskOptions(
            platforms=[Platform.JD],
            max_candidates=1,
            login_wait_seconds=0.5,
            max_task_seconds=20.0,
        ),
    )


# ─── 问题只问一次 ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_asks_the_review_question_once():
    agent = _agent()
    task = _task(agent)

    await agent.start(task.id)
    assert task.status is TaskStatus.WAITING_CONFIRM
    assert task.pending_question is not None
    assert task.pending_question["key"] == "include_reviews"
    assert "专业评测" in task.waiting_reason
    # 汇总状态要如实反映"在等用户"，不能显示成"待开始"
    assert task.summary_status() is TaskStatus.WAITING_CONFIRM
    assert task.summary_status().label == "等待您确认"

    await agent.cancel_task(task.id)


@pytest.mark.asyncio
async def test_answering_unblocks_the_task_and_question_never_returns():
    """核心回归：答完必须能开跑，且不能再被问第二遍。"""
    agent = _agent()
    task = _task(agent)

    await agent.start(task.id)
    assert task.status is TaskStatus.WAITING_CONFIRM

    agent.answer_question(task.id, "include_reviews", "不要")
    assert task.pending_question is None
    assert task.requirement.include_reviews is False
    assert any("未开启" in note for note in task.notes)

    # 用户点"开始"（前端 answer 后会自动继续，这里等价地手动调一次）
    await agent.start(task.id)
    assert task.status is TaskStatus.RUNNING
    assert task.waiting_reason is None

    # 跑一会儿：期间问题绝不能自己冒出来
    for _ in range(10):
        await asyncio.sleep(0.05)
        assert task.pending_question is None, "问题被重复询问，任务会再次卡住"
        assert task.status is not TaskStatus.WAITING_CONFIRM

    await agent.cancel_task(task.id)
    assert task.status is TaskStatus.CANCELLED


@pytest.mark.asyncio
async def test_answering_yes_also_proceeds():
    agent = _agent()
    task = _task(agent)
    await agent.start(task.id)

    agent.answer_question(task.id, "include_reviews", "要")
    assert task.requirement.include_reviews is True
    assert any("已开启" in note for note in task.notes)

    await agent.start(task.id)
    assert task.status is TaskStatus.RUNNING
    assert task.pending_question is None
    await agent.cancel_task(task.id)


@pytest.mark.asyncio
async def test_question_can_be_skipped_by_option():
    """测试夹具关掉提问时不应出现任何待决问题。"""
    agent = _agent()
    task = agent.create_task(
        Requirement(text="测试", keyword="冲锋衣"),
        TaskOptions(
            platforms=[Platform.JD],
            ask_review_question=False,
            max_candidates=1,
            max_task_seconds=20.0,
        ),
    )
    await agent.start(task.id)
    assert task.status is TaskStatus.RUNNING
    assert task.pending_question is None
    await agent.cancel_task(task.id)


@pytest.mark.asyncio
async def test_unknown_question_key_is_rejected():
    agent = _agent()
    task = _task(agent)
    await agent.start(task.id)
    with pytest.raises(ValueError):
        agent.answer_question(task.id, "something_else", "要")
    # 问错不影响任务继续等在原问题上
    assert task.pending_question["key"] == "include_reviews"
    await agent.cancel_task(task.id)


# ─── 落库往返 ──────────────────────────────────────────────────────


@pytest.fixture
async def db(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'review.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_sessions_are_released_when_the_task_ends():
    """任务结束后浏览器会话必须收掉，否则登录窗口打不开。

    持久化上下文会一直占着 profile 目录；不主动收的话，
    用户想登录自己账号时会被"该平台正在执行比价任务"挡住。
    """
    agent = _agent()
    task = _task(agent)
    await agent.start(task.id)
    agent.answer_question(task.id, "include_reviews", "不要")
    await agent.start(task.id)

    for _ in range(120):
        if task.status.is_terminal:
            break
        await asyncio.sleep(0.05)
    assert task.status.is_terminal
    assert agent._sessions == {}, "任务结束后仍残留浏览器会话"

    # 会话收了，登录窗口就能开
    session = await agent.open_login_window("jd")
    assert session.status == WAITING_LOGIN
    await agent.close_login_window("jd")


@pytest.mark.asyncio
async def test_pending_question_survives_a_restart(db):
    """重启后回读，等待原因和待决问题都要原样还给用户。"""
    agent = _agent()
    task = _task(agent)
    await agent.start(task.id)
    assert task.pending_question is not None

    async with db() as session:
        await store.save_task(session, task)
        record = await store.get_task_record(session, task.id)
        view = store.task_view_from_record(record)

    assert view["status"] == TaskStatus.WAITING_CONFIRM.value
    assert view["waiting_reason"] == task.waiting_reason
    assert view["pending_question"]["key"] == "include_reviews"
    assert view["pending_question"]["question"] == task.pending_question["question"]
    assert view["summary_status"] == TaskStatus.WAITING_CONFIRM.value
    assert view["summary_status_label"] == "等待您确认"

    await agent.cancel_task(task.id)


@pytest.mark.asyncio
async def test_question_is_cleared_once_answered(db):
    agent = _agent()
    task = _task(agent)
    await agent.start(task.id)
    agent.answer_question(task.id, "include_reviews", "不要")

    async with db() as session:
        await store.save_task(session, task)
        record = await store.get_task_record(session, task.id)
        view = store.task_view_from_record(record)

    assert view["pending_question"] is None
    assert view["waiting_reason"] is None
    await agent.cancel_task(task.id)


# ─── 接口层 ────────────────────────────────────────────────────────


@pytest.fixture
def client(tmp_path, monkeypatch):
    """把应用数据库换成临时文件，并让编排器用脚本驱动（不起浏览器）。"""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'api.db'}")
    monkeypatch.setattr("app.database.engine", engine)
    monkeypatch.setattr(
        "app.database.async_session_factory",
        async_sessionmaker(engine, expire_on_commit=False),
    )
    from fastapi.testclient import TestClient

    from app.browser.agent import agent as live_agent
    from app.main import app as fastapi_app

    # 不换成脚本驱动的话，这个用例会真的去拉起 Chromium 访问京东
    original = live_agent._driver_factory
    live_agent.set_driver_factory(lambda platform: _scripted())
    with TestClient(fastapi_app) as c:
        yield c
    live_agent.set_driver_factory(original)
    asyncio.run(live_agent.close_all_sessions())


def test_answer_endpoint_starts_the_task(client):
    """HTTP 上回答一次就该开跑，且状态里不再带待决问题。"""
    created = client.post(
        "/api/browser/tasks",
        json={"text": "预算 700 元的冲锋衣", "platforms": ["jd"]},
    )
    assert created.status_code == 200, created.text
    task_id = created.json()["id"]

    started = client.post(f"/api/browser/tasks/{task_id}/start")
    assert started.status_code == 200
    assert started.json()["status"] == "waiting_confirm"
    assert started.json()["pending_question"]["key"] == "include_reviews"
    assert started.json()["summary_status"] == "waiting_confirm"

    answered = client.post(
        f"/api/browser/tasks/{task_id}/answer",
        json={"key": "include_reviews", "value": "不要"},
    )
    assert answered.status_code == 200, answered.text
    body = answered.json()
    # 脚本驱动下商品页取不到字段，平台会以"结构无法识别"结束，
    # 但关键是：它真的往下跑了，没有再被问一遍
    assert body["pending_question"] is None
    assert body["waiting_reason"] is None
    assert body["status"] != "waiting_confirm"
    assert body["summary_status"] != "waiting_confirm"
    assert body["status"] in ("running", "completed", "restricted", "failed", "cancelled")
    assert any("未开启" in note for note in body["notes"])
