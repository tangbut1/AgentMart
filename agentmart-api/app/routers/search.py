"""搜索与商品接口。"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..domain.models import UserPreferences
from ..schemas import (
    CompareRequest,
    CompareResponse,
    ProductDetailResponse,
    SearchResponse,
)
from ..services import search_service

router = APIRouter(prefix="/api", tags=["搜索与商品"])


@router.get("/search", response_model=SearchResponse, summary="跨平台搜索商品")
async def search(
    keyword: str = Query(..., min_length=1, max_length=200,
                         description="商品名称、型号或商品链接"),
    include_demo: bool = Query(False, description="是否包含演示数据（虚构）"),
) -> SearchResponse:
    return await search_service.search_products(keyword, include_demo=include_demo)


@router.get("/products/detail", response_model=ProductDetailResponse,
            summary="商品详情：购买选项、到手价拆解、政策、评测与推荐")
async def product_detail(
    keyword: str = Query(..., min_length=1, max_length=200),
    group_id: str = Query(..., description="搜索结果中的商品组 ID"),
    include_demo: bool = Query(False),
    budget_max: Optional[float] = Query(None, description="预算上限（可选）"),
    priority: str = Query("balanced", pattern="^(price|service|balanced)$"),
    scenario: Optional[str] = Query(None),
    region: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_session),
) -> ProductDetailResponse:
    from decimal import Decimal

    preferences = UserPreferences(
        budget_max=Decimal(str(budget_max)) if budget_max is not None else None,
        priority=priority,
        scenario=scenario,
        region=region,
    )
    group, recommendation, reviews, demo_included = await search_service.get_product_detail(
        keyword, group_id, include_demo=include_demo,
        preferences=preferences, session=session,
    )
    return ProductDetailResponse(
        group=group,
        reviews=reviews,
        recommendation=recommendation,
        demo_included=demo_included,
    )


@router.post("/compare", response_model=CompareResponse, summary="多商品横向对比")
async def compare(
    request: CompareRequest,
    session: AsyncSession = Depends(get_session),
) -> CompareResponse:
    preferences: Optional[UserPreferences] = None
    if request.preferences:
        preferences = UserPreferences(
            budget_max=request.preferences.budget_max,
            priority=request.preferences.priority,
            scenario=request.preferences.scenario,
            region=request.preferences.region,
        )
    return await search_service.compare_products(
        request.keyword,
        request.group_ids,
        include_demo=request.include_demo,
        preferences=preferences,
        session=session,
    )
