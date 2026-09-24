"""个人浏览器版：任务落库 / 服务层 / 接口 的回归测试。

这些测试全部走本地受控数据：
- 存储测试用临时 SQLite 文件，不碰开发库 agentmart.db；
- 接口测试通过 TestClient，并在启动前把引擎换成临时库。
不发起任何真实网络请求，也不启动浏览器。
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.browser.agent import Requirement, ShoppingAgent, TaskOptions, agent as live_agent
from app.browser import store
from app.database import Base
from app.domain.enums import Platform
from app.main import app


def _make_task(agent: ShoppingAgent, text: str = "预算 600 元买冲锋衣"):
    return agent.create_task(
        Requirement(text=text, keyword="冲锋衣"),
        TaskOptions(platforms=[Platform.JD], ask_review_question=False),
    )


@pytest.fixture
async def db(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'browser.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_task_view_can_be_rebuilt_from_record(db):
    """服务重启后任务不在内存，也要能读出与实时视图一致的字段。"""
    agent = ShoppingAgent()
    task = _make_task(agent)
    async with db() as session:
        await store.save_result(session, task, {"groups": [], "budget_exhausted": True})
        record = await store.get_task_record(session, task.id)
        view = store.task_view_from_record(record)

    assert view["id"] == task.id
    assert view["status"] == task.status.value
    assert view["status_label"] == task.status.label
    assert view["origin"] == task.origin.value
    assert view["origin_label"] == task.origin.label
    assert view["requirement"]["keyword"] == "冲锋衣"
    assert view["platforms"], "平台状态应随快照重建"
    assert view["platforms"][0]["platform"] == Platform.JD.value
    assert view["budget_exhausted"] is True
    assert view["restored"] is True
    # 缺字段的记录也不能把视图炸掉
    minimal = store.task_view_from_record({"id": "x", "status": "completed"})
    assert minimal["id"] == "x" and minimal["platforms"] == []


@pytest.mark.asyncio
async def test_task_snapshot_round_trip(db):
    """创建 → 落库 → 列表 → 读取详情 → 写结果 → 删除。"""
    agent = ShoppingAgent()
    task = _make_task(agent)
    async with db() as session:
        await store.save_task(session, task)
        await store.save_result(session, task, {"groups": [], "demo_included": False})

        rows = await store.list_tasks(session, limit=10)
        assert len(rows) == 1
        assert rows[0]["id"] == task.id
        assert rows[0]["requirement_text"] == "预算 600 元买冲锋衣"

        record = await store.get_task_record(session, task.id)
        assert record is not None
        assert record["platforms"], "平台状态应随快照一起落库"
        assert record["result"] == {"groups": [], "demo_included": False}
        assert record["options"]["max_candidates"] > 0
        # 落库内容绝不能包含密钥或 cookie
        blob = str(record)
        assert "api_key" not in blob and "cookie" not in blob.lower()

        assert await store.delete_task(session, task.id) is True
        assert await store.get_task_record(session, task.id) is None
        assert await store.delete_task(session, task.id) is False


@pytest.mark.asyncio
async def test_list_tasks_limit_is_applied(db):
    agent = ShoppingAgent()
    async with db() as session:
        for i in range(4):
            await store.save_task(session, _make_task(agent, f"需求{i}"))
        assert len(await store.list_tasks(session, limit=2)) == 2
        assert len(await store.list_tasks(session, limit=0)) == 0


@pytest.mark.asyncio
async def test_snapshot_update_keeps_single_row(db):
    agent = ShoppingAgent()
    task = _make_task(agent)
    async with db() as session:
        await store.save_task(session, task)
        await store.save_result(session, task, {"groups": [{"a": 1}]})
        record = await store.get_task_record(session, task.id)
        assert record["result"]["groups"] == [{"a": 1}]
    async with db() as session:
        rows = await store.list_tasks(session)
        assert len(rows) == 1


@pytest.mark.asyncio
async def test_result_is_persisted_once_task_is_terminal(db):
    """任务结束后，结果快照必须落库，否则刷新页面就看不到了。"""
    from app.browser.agent import Requirement, TaskOptions
    from app.browser.enums import TaskStatus
    from app.browser.service import service
    from app.domain.enums import Platform

    def make(status: TaskStatus, text: str):
        task = service.agent.create_task(
            Requirement(text=text, keyword="冲锋衣"),
            TaskOptions(platforms=[Platform.JD], ask_review_question=False),
        )
        task.status = status
        return task

    finished = make(TaskStatus.COMPLETED, "已完成的需求")
    running = make(TaskStatus.RUNNING, "还在跑的需求")

    async with db() as session:
        assert await service.persist("不在编排器里的id", session) is None
        await store.save_task(session, finished)
        await store.save_task(session, running)
        await service.persist(finished.id, session)
        await service.persist(running.id, session)

        done = await store.get_task_record(session, finished.id)
        assert done is not None
        assert done["result"], "终态任务应连结果一起落库"
        pending = await store.get_task_record(session, running.id)
        assert pending is not None
        assert pending["result"] == {}, "未结束的任务只存状态，不存结果"


@pytest.fixture
def client(tmp_path, monkeypatch):
    """把应用数据库换成临时文件，避免污染开发库。"""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'api.db'}")
    monkeypatch.setattr("app.database.engine", engine)
    monkeypatch.setattr(
        "app.database.async_session_factory",
        async_sessionmaker(engine, expire_on_commit=False),
    )
    with TestClient(app) as c:
        yield c
    # 关掉可能由其它测试拉起的浏览器会话
    import asyncio

    asyncio.run(live_agent.close_all_sessions())


def test_only_allowlisted_endpoints_can_change_state(client):
    """会改变状态的接口必须逐一登记；新增写操作要显式加进白名单才会被允许。

    白名单里没有任何"领券/加购/下单/付款"类端点 —— 这是产品边界，
    不是漏写。发现白名单外的新写接口，说明有人加了会改变账号状态的能力。
    """
    allowed = {
        ("/api/browser/model", "post"),
        ("/api/browser/model", "delete"),
        ("/api/browser/model/test", "post"),
        ("/api/browser/parse", "post"),
        ("/api/browser/platforms/{group}/clear", "post"),
        # 登录窗口：只是弹出一个用户可见的浏览器让人自己登录，
        # 不开券、不加购、不下单、不付款，因此登记为允许的写接口
        ("/api/browser/platforms/{group}/login", "post"),
        ("/api/browser/platforms/{group}/login/close", "post"),
        ("/api/browser/tasks", "post"),
        ("/api/browser/tasks/{task_id}", "delete"),
        ("/api/browser/tasks/{task_id}/answer", "post"),
        ("/api/browser/tasks/{task_id}/cancel", "post"),
        ("/api/browser/tasks/{task_id}/start", "post"),
        ("/api/browser/tasks/{task_id}/reviews", "post"),
        ("/api/browser/tasks/{task_id}/platforms/{platform}/cancel", "post"),
        ("/api/browser/tasks/{task_id}/platforms/{platform}/pause", "post"),
        ("/api/browser/tasks/{task_id}/platforms/{platform}/resume", "post"),
        ("/api/compare", "post"),
        ("/api/reviews", "post"),
        ("/api/reviews/resolve", "post"),
        ("/api/reviews/{review_id}/ai-summary", "post"),
        ("/api/reviews/{review_id}/curate", "post"),
    }
    schema = client.get("/openapi.json").json()
    found = set()
    for path, methods in schema["paths"].items():
        for method in methods:
            if method in ("post", "put", "patch", "delete"):
                found.add((path, method))
    unexpected = found - allowed
    assert not unexpected, f"出现未登记的写接口：{sorted(unexpected)}"


def test_agent_only_issues_read_only_actions():
    """浏览器 Agent 的动作集合里，只有 MUTATING 会改变账号状态，且永不执行。"""
    from app.browser.enums import ActionKind

    assert ActionKind.MUTATING.is_read_only is False
    read_only = [k for k in ActionKind if k.is_read_only]
    assert {k.value for k in read_only} == {
        "navigate",
        "read",
        "scroll",
        "screenshot",
        "wait_user",
        "ask_confirm",
    }


def test_browser_mode_endpoint_explains_boundaries(client):
    resp = client.get("/api/browser/mode")
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "personal-browser"
    boundaries = " ".join(data["boundaries"])
    assert "不代领优惠券" in boundaries
    assert "不代付款" in boundaries
    assert "api_key" not in str(data).lower()


def test_browser_platforms_endpoint_lists_five(client):
    resp = client.get("/api/browser/platforms")
    assert resp.status_code == 200
    data = resp.json()
    codes = {r["platform"] for r in data["recipes"]}
    assert codes == {"jd", "taobao", "tmall", "pdd", "douyin"}
    assert data["storage"]["inside_repo"] is False


def test_browser_model_endpoint_never_returns_key(client):
    resp = client.get("/api/browser/model")
    assert resp.status_code == 200
    assert "api_key" not in resp.json()
    assert resp.json()["api_key_configured"] is False


def test_browser_task_survives_restart_via_db(client, monkeypatch):
    """编排器里没有的任务（服务重启过）也要能读到状态和结果。"""
    from app.browser.agent import Requirement, TaskOptions
    from app.browser.service import service as live_service
    from app.browser.enums import TaskStatus

    task = live_service.agent.create_task(
        Requirement(text="重启后仍要能看见的任务", keyword="冲锋衣"),
        TaskOptions(platforms=[Platform.JD], ask_review_question=False),
    )
    task.status = TaskStatus.COMPLETED

    async def seed():
        from app.database import async_session_factory

        async with async_session_factory() as session:
            await store.save_result(
                session,
                task,
                {
                    "groups": [{"id": "g1", "offers": []}],
                    "budget_exhausted": True,
                    "origin": "real_platform_page",
                },
            )

    asyncio.run(seed())
    # 模拟重启：内存里不再有这个任务
    live_service.agent._tasks.pop(task.id, None)

    detail = client.get(f"/api/browser/tasks/{task.id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["restored"] is True
    assert body["status_label"] == "已完成"
    assert body["requirement"]["keyword"] == "冲锋衣"
    assert body["platforms"][0]["platform"] == Platform.JD.value

    result = client.get(f"/api/browser/tasks/{task.id}/result")
    assert result.status_code == 200
    assert result.json()["groups"][0]["id"] == "g1"
    assert result.json()["budget_exhausted"] is True

    assert client.get("/api/browser/tasks/从未存在/result").status_code == 404


def test_browser_task_lifecycle_over_http(client):
    created = client.post(
        "/api/browser/tasks", json={"text": "预算 700 元的冲锋衣", "platforms": ["jd"]}
    )
    assert created.status_code == 200, created.text
    task_id = created.json()["id"]

    listed = client.get("/api/browser/tasks")
    assert listed.status_code == 200
    assert any(row["id"] == task_id for row in listed.json())

    detail = client.get(f"/api/browser/tasks/{task_id}")
    assert detail.status_code == 200
    assert detail.json()["requirement"]["keyword"] == "冲锋衣"

    record = client.get(f"/api/browser/tasks/{task_id}/record")
    assert record.status_code == 200
    assert record.json()["id"] == task_id

    assert client.get("/api/browser/tasks/不存在").status_code == 404

    deleted = client.delete(f"/api/browser/tasks/{task_id}")
    assert deleted.status_code == 200
    assert client.get(f"/api/browser/tasks/{task_id}/record").status_code == 404


def test_browser_create_task_rejects_empty_text(client):
    resp = client.post("/api/browser/tasks", json={"text": "   "})
    assert resp.status_code == 422


def test_browser_parse_endpoint(client):
    resp = client.post(
        "/api/browser/parse",
        json={"text": "预算 500～800 元，日常通勤和轻度徒步的冲锋衣，重视防雨透气"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["keyword"]
    assert data["budget_min"] == 500 and data["budget_max"] == 800
    assert "徒步" in data["scenarios"]
