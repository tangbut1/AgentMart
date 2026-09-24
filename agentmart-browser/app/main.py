"""AgentMart 个人浏览器版 — FastAPI 入口。

本地启动：
    uvicorn app.main:app --reload --port 8000

前端构建产物（frontend/dist）存在时由本服务直接托管，
实现「一个端口跑完整应用」；未构建时仅提供 /api 与 /docs。

安全边界在代码层面强制：没有任何「领券/加购/下单/付款」端点，
也没有预留后门。
"""
from __future__ import annotations

import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from . import VERSION, ARCHITECTURE
from .config import settings
from .database import init_db
from .routers import browser, health

FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"AgentMart 个人浏览器版 {VERSION} 启动中…")
    await init_db()
    logger.info("数据库就绪")
    logger.info("启动完成")
    yield
    logger.info("AgentMart 关闭")
    # 关掉可能还开着的浏览器/登录窗口，避免残留进程
    try:
        from .browser.service import service as browser_service

        await browser_service.agent.close_all_sessions()
    except Exception:
        logger.exception("关闭浏览器会话失败")


app = FastAPI(
    title="AgentMart（个人浏览器版）",
    description=(
        "用你自己的浏览器登录会话，在五个平台同台比价。\n\n"
        f"版本：{VERSION}（{ARCHITECTURE}）\n\n"
        "**不代领优惠券、不代下单、不代付款。** 账号密码、短信验证码、扫码"
        "都由你本人在弹出的可见窗口里完成；Agent 只读取页面上的商品、价格、"
        "账号可见的优惠与售后政策。\n\n"
        "需要走平台开放接口的版本，请使用同仓库的官方 API 架构版项目。"
    ),
    version=VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    elapsed = (time.perf_counter() - start) * 1000
    response.headers["X-Process-Time"] = f"{elapsed:.1f}ms"
    return response


# ---- 路由 ----
app.include_router(health.router)
app.include_router(browser.router)


@app.get("/api", tags=["系统"])
async def api_root():
    return {
        "message": "Welcome to AgentMart（个人浏览器版）",
        "version": VERSION,
        "architecture": ARCHITECTURE,
        "docs": "/docs",
        "endpoints": [
            "GET /api/browser/mode",
            "GET /api/browser/platforms",
            "POST /api/browser/platforms/{group}/login",
            "POST /api/browser/platforms/{group}/login/close",
            "POST /api/browser/platforms/{group}/clear",
            "GET/POST/DELETE /api/browser/model",
            "POST /api/browser/model/test",
            "GET /api/browser/model/usage",
            "POST /api/browser/parse",
            "POST /api/browser/tasks",
            "GET /api/browser/tasks",
            "GET /api/browser/tasks/{id}",
            "GET /api/browser/tasks/{id}/result",
            "POST /api/browser/tasks/{id}/start",
            "POST /api/browser/tasks/{id}/answer",
            "POST /api/browser/tasks/{id}/reviews",
            "POST /api/browser/tasks/{id}/cancel",
            "POST /api/browser/tasks/{id}/platforms/{platform}/pause",
            "POST /api/browser/tasks/{id}/platforms/{platform}/resume",
            "POST /api/browser/tasks/{id}/platforms/{platform}/cancel",
        ],
    }


# ---- 前端静态资源（构建后存在时启用） ----
if FRONTEND_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        # /api/* 拼错路径时若回退成 index.html，调用方会拿到 200 + HTML，
        # 把「接口不存在」误判成「请求成功」，所以 API 前缀一律按 404 处理
        if full_path == "api" or full_path.startswith("api/"):
            return JSONResponse(
                {"detail": f"接口不存在：/{full_path}", "docs": "/docs"}, status_code=404
            )
        index = FRONTEND_DIST / "index.html"
        if index.is_file():
            from fastapi.responses import FileResponse

            return FileResponse(index)
        return JSONResponse({"detail": "前端未构建"}, status_code=404)
else:
    logger.warning(
        "未找到 frontend/dist，仅启动 API。构建前端：cd frontend && npm install && npm run build"
    )
