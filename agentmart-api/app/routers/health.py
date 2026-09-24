"""系统健康检查。"""
from __future__ import annotations

from fastapi import APIRouter

from .. import VERSION
from ..config import settings

router = APIRouter(tags=["系统"])


@router.get("/health", summary="健康检查")
async def health() -> dict:
    return {
        "status": "ok",
        "version": VERSION,
        "env": settings.APP_ENV,
    }
