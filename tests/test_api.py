"""API 端到端测试（TestClient，不走外网 —— 平台均未配置凭据）。"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_platforms_all_not_connected_without_credentials(client):
    resp = client.get("/api/platforms")
    assert resp.status_code == 200
    platforms = resp.json()
    assert len(platforms) == 5
    codes = {p["platform"] for p in platforms}
    assert codes == {"jd", "taobao", "tmall", "pdd", "douyin"}
    for p in platforms:
        assert p["status"] == "not_connected"
        assert p["required_env"]  # 必须告诉用户需要哪些配置


def test_search_without_demo_returns_no_fake_data(client):
    resp = client.get("/api/search", params={"keyword": "iPhone 15 Pro"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_real_data"] is False
    assert data["groups"] == []
    assert data["demo_included"] is False
    # 未接入平台必须明确提示
    messages = " ".join(p["message"] for p in data["platform_results"])
    assert "未接入" in messages


def test_search_with_demo_is_labeled(client):
    resp = client.get(
        "/api/search",
        params={"keyword": "索尼 WH-1000XM5", "include_demo": True},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["demo_included"] is True
    assert data["demo_notice"]
    assert data["groups"], "演示模式下应有商品组"
    for group in data["groups"]:
        for offer in group["offers"]:
            assert offer["data_status"] == "demo"
        # 到手价三层结构必须完整
        offer = group["offers"][0]
        assert "definite_total" in offer["breakdown"]
        assert "potential_total" in offer["breakdown"]
        assert "unverifiable_total" in offer["breakdown"]


def test_product_detail_demo_mode(client):
    search = client.get(
        "/api/search",
        params={"keyword": "索尼 WH-1000XM5", "include_demo": True},
    ).json()
    group_id = search["groups"][0]["id"]
    resp = client.get("/api/products/detail", params={
        "keyword": "索尼 WH-1000XM5",
        "group_id": group_id,
        "include_demo": True,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["group"]["id"] == group_id
    # 纯演示数据不得产生推荐结论
    if data["recommendation"]:
        assert data["recommendation"]["options"] == []
        assert data["recommendation"]["confidence"] == 0.0


def test_product_detail_unknown_group(client):
    resp = client.get("/api/products/detail", params={
        "keyword": "不存在的商品", "group_id": "cp_nonexistent",
    })
    assert resp.status_code == 200
    assert resp.json()["group"] is None


def test_link_query_does_not_scrape(client):
    resp = client.get("/api/search", params={
        "keyword": "https://item.jd.com/100050557484.html",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_link_query"] is True
    assert data["link_notice"]
    assert "不抓取" in data["link_notice"]


def test_sources_endpoint(client):
    resp = client.get("/api/sources")
    assert resp.status_code == 200
    sources = resp.json()
    kinds = {s["kind"] for s in sources}
    assert "platform_api" in kinds
    assert "demo" in kinds


def test_unknown_api_path_returns_json_404_not_spa_html(client):
    """拼错 /api/* 不能回退成 200 + 前端页面，否则调用方会误判为请求成功。"""
    resp = client.get("/api/browser/does-not-exist")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/json")
    assert "不存在" in resp.json()["detail"]


def test_spa_deep_link_still_served(client):
    index = Path(__file__).resolve().parent.parent / "frontend" / "dist" / "index.html"
    if not index.is_file():  # 未构建前端时没有 SPA 回退，跳过
        pytest.skip("frontend/dist 未构建")
    resp = client.get("/browser/task/some-id")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert 'id="root"' in resp.text


def test_resolve_rejects_non_bilibili(client):
    resp = client.post("/api/reviews/resolve", json={
        "url": "https://www.douyin.com/video/123",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert data["notice"]


def test_submit_review_requires_title_for_unresolvable(client):
    resp = client.post("/api/reviews", json={
        "url": "https://example.com/not-a-video",
    })
    assert resp.status_code == 400


def test_compare_endpoint(client):
    search = client.get(
        "/api/search",
        params={"keyword": "索尼 WH-1000XM5", "include_demo": True},
    ).json()
    group_id = search["groups"][0]["id"]
    resp = client.post("/api/compare", json={
        "keyword": "索尼 WH-1000XM5",
        "group_ids": [group_id],
        "include_demo": True,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["groups"]) == 1
