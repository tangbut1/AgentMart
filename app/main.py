"""FastAPI 应用入口。

本地启动：
    uvicorn app.main:app --reload --port 8000

前端构建产物（frontend/dist）存在时由本服务直接托管，
实现「一个端口跑完整应用」；未构建时仅提供 /api 与 /docs。
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

from .config import settings
from .database import init_db
from .routers import health, reviews, search, sources

FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("AgentMart 启动中…")
    await init_db()
    logger.info("数据库就绪")
    # 演示评测入库（标记为 DEMO，仅在显式请求演示数据时返回）
    try:
        from .database import async_session_factory
        from .reviews.curation import seed_demo_reviews

        async with async_session_factory() as session:
            await seed_demo_reviews(session)
    except Exception:
        logger.exception("演示评测入库失败（不影响启动）")
    logger.info("AgentMart 启动完成")
    yield
    logger.info("AgentMart 关闭")


app = FastAPI(
    title="AgentMart API",
    description=(
        "跨平台智能购物决策平台：多平台商品与优惠对比、可解释到手价、"
        "政策差异标注、评测观点整理与可解释推荐。"
    ),
    version="1.0.0",
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


# ---- API 路由 ----
app.include_router(health.router)
app.include_router(search.router)
app.include_router(reviews.router)
app.include_router(sources.router)


@app.get("/api", tags=["系统"])
async def api_root():
    return {
        "message": "Welcome to AgentMart API",
        "docs": "/docs",
        "endpoints": [
            "GET /api/search?keyword=",
            "GET /api/products/detail?keyword=&group_id=",
            "POST /api/compare",
            "GET /api/reviews",
            "POST /api/reviews/resolve",
            "POST /api/reviews",
            "POST /api/reviews/{id}/curate",
            "POST /api/reviews/{id}/ai-summary",
            "GET /api/sources",
            "GET /api/platforms",
        ],
    }


# ---- 前端静态资源（构建后存在时启用） ----
if FRONTEND_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        index = FRONTEND_DIST / "index.html"
        if index.is_file():
            from fastapi.responses import FileResponse

            return FileResponse(index)
        return JSONResponse({"detail": "前端未构建"}, status_code=404)
else:
    logger.warning(
        "未找到 frontend/dist，仅启动 API。构建前端：cd frontend && npm install && npm run build"
    )
