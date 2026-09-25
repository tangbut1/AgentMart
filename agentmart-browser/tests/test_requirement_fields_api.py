"""接口层：结构化填表走 HTTP 也要生效，且填错要被拒绝。

前端表单提交的就是这些字段。这里用 TestClient 打真实路由，
确认 ``fields`` 不会被中途丢掉、也不会被"重新解析"改掉 —— 用户在表单里
看到的数字，必须就是最终用的数字。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'fields.db'}")
    monkeypatch.setattr("app.database.engine", engine)
    monkeypatch.setattr(
        "app.database.async_session_factory",
        async_sessionmaker(engine, expire_on_commit=False),
    )
    with TestClient(app) as c:
        yield c


def test_parse_endpoint_reports_budget_range(client):
    """/parse 是"一句话自动填表"用的，必须把区间认对。"""
    resp = client.post("/api/browser/parse", json={"text": "预算100到250之间的西装"})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["keyword"] == "西装"
    assert data["budget_min"] == 100
    assert data["budget_max"] == 250


def test_create_task_accepts_structured_fields(client):
    payload = {
        "text": "",
        "fields": {
            "keyword": "西装",
            "category": "服装",
            "budget_min": 100,
            "budget_max": 250,
            "brands": "优衣库",
            "region": "广东省深圳市",
            "scenarios": ["通勤"],
        },
        "platforms": ["jd"],
    }
    resp = client.post("/api/browser/tasks", json=payload)
    assert resp.status_code == 200, resp.text
    req = resp.json()["requirement"]
    assert req["keyword"] == "西装"
    assert req["category"] == "服装"
    assert req["budget_min"] == 100
    assert req["budget_max"] == 250
    assert req["brands"] == ["优衣库"]
    assert req["region"] == "广东省深圳市"
    assert req["scenarios"] == ["通勤"]


def test_fields_beat_natural_language_over_http(client):
    """表单优先：即使原话解析出的区间不同，也以表单为准。"""
    resp = client.post(
        "/api/browser/tasks",
        json={
            "text": "预算100到250之间的西装",
            "fields": {"keyword": "西装", "budget_min": 300, "budget_max": 900},
            "platforms": ["jd"],
        },
    )
    assert resp.status_code == 200, resp.text
    req = resp.json()["requirement"]
    assert req["budget_min"] == 300
    assert req["budget_max"] == 900


def test_model_configured_flag_is_present(client):
    """任务视图必须带 model_configured，前端才能解释"模型调用 0 次"。"""
    resp = client.post(
        "/api/browser/tasks",
        json={"text": "预算 2500 的降噪耳机", "platforms": ["jd"]},
    )
    assert resp.status_code == 200, resp.text
    assert "model_configured" in resp.json()
    assert isinstance(resp.json()["model_configured"], bool)


@pytest.mark.parametrize(
    "fields",
    [
        {"keyword": "西装", "budget_min": 250, "budget_max": 100},  # 下限比上限大
        {"keyword": "西装", "budget_max": "两百多"},                 # 不是数字
        {"keyword": "西装", "budget_max": -5},                       # 负数
    ],
)
def test_invalid_fields_are_rejected_with_422(client, fields):
    resp = client.post(
        "/api/browser/tasks", json={"fields": fields, "platforms": ["jd"]}
    )
    assert resp.status_code == 422, resp.text


def test_empty_request_is_rejected(client):
    """既没填表也没写一句话，要明确告知，不能建一个空任务。"""
    resp = client.post("/api/browser/tasks", json={"platforms": ["jd"]})
    assert resp.status_code == 422
    assert "商品名称" in resp.json()["detail"]


def test_fields_must_be_an_object(client):
    resp = client.post(
        "/api/browser/tasks", json={"text": "西装", "fields": "西装", "platforms": ["jd"]}
    )
    assert resp.status_code == 422
