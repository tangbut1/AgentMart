"""数据来源与平台接入状态接口。"""
from __future__ import annotations

from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..reviews import curation as curation_service
from ..schemas import DataSourceInfo, PlatformStatus
from ..services import search_service

router = APIRouter(prefix="/api", tags=["数据来源"])


@router.get("/sources", response_model=List[DataSourceInfo], summary="数据来源与可信状态")
async def data_sources(
    session: AsyncSession = Depends(get_session),
) -> List[DataSourceInfo]:
    now = datetime.now()
    infos: List[DataSourceInfo] = []

    for status in search_service.platform_status_list():
        infos.append(DataSourceInfo(
            name=f"{status.platform.label}（{status.adapter}）",
            kind="platform_api",
            status=status.status.value,
            description=status.message,
            last_updated=None,
            url=status.docs_url or None,
        ))

    reviews = await curation_service.list_reviews(session)
    verified = [r for r in reviews if r.curation_status.value == "verified"]
    latest = max((r.curated_at for r in reviews if r.curated_at), default=None)
    infos.append(DataSourceInfo(
        name="评测元数据（B 站公开接口）",
        kind="review_metadata",
        status="connected" if reviews else "empty",
        description=(
            f"通过 B 站公开接口解析用户提交的评测链接元数据；"
            f"当前已整理 {len(reviews)} 条，其中已核实 {len(verified)} 条。"
        ),
        last_updated=latest,
        url="https://www.bilibili.com/",
    ))
    infos.append(DataSourceInfo(
        name="人工整理内容",
        kind="curated",
        status="connected",
        description=(
            "评测观点由人工整理并标注整理时间与商业合作关系；"
            "AI 归纳（如配置 LLM）会单独标注，不与人工内容混合。"
        ),
        last_updated=latest,
    ))
    infos.append(DataSourceInfo(
        name="演示数据",
        kind="demo",
        status="available",
        description=(
            "搜索时勾选「包含演示数据」可查看虚构的演示商品，"
            "用于开发联调；演示数据不参与真实价格结论与推荐。"
        ),
        last_updated=now,
    ))
    return infos


@router.get("/platforms", response_model=List[PlatformStatus], summary="各平台接入状态")
async def platform_status() -> List[PlatformStatus]:
    return search_service.platform_status_list()
