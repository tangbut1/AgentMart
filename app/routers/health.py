"""系统健康检查。"""
from __future__ import annotations

from fastapi import APIRouter

from ..config import settings

router = APIRouter(tags=["系统"])


@router.get("/health", summary="健康检查")
async def health() -> dict:
    return {
        "status": "ok",
        "version": "1.0.0",
        "env": settings.APP_ENV,
    }
