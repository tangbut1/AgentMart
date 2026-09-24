"""评测接口：链接解析、提交、整理（curation）、AI 归纳（可选）。"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import get_session
from ..domain.enums import CurationStatus, DataStatus, ReviewPlatform
from ..domain.models import Review
from ..reviews import bilibili, curation as curation_service
from ..reviews.criteria import evaluate_review
from ..schemas import (
    ReviewCurateRequest,
    ReviewOut,
    ReviewResolveRequest,
    ReviewResolveResponse,
    ReviewSubmitRequest,
)

router = APIRouter(prefix="/api/reviews", tags=["评测"])


def _check_curation_auth(x_admin_token: Optional[str]) -> None:
    """整理接口的写入鉴权。开发环境且未配置令牌时允许本地调试。"""
    if settings.CURATION_ADMIN_TOKEN:
        if x_admin_token != settings.CURATION_ADMIN_TOKEN:
            raise HTTPException(status_code=401, detail="无效的整理令牌")
    elif not settings.is_development:
        raise HTTPException(
            status_code=401,
            detail="生产环境必须配置 CURATION_ADMIN_TOKEN 才能使用整理接口",
        )


@router.get("", response_model=List[ReviewOut], summary="已整理的评测列表")
async def list_reviews(
    status: Optional[str] = Query(None, pattern="^(pending|verified|rejected)$"),
    include_demo: bool = False,
    session: AsyncSession = Depends(get_session),
) -> List[ReviewOut]:
    curation_status = CurationStatus(status) if status else None
    reviews = await curation_service.list_reviews(
        session, status=curation_status, include_demo=include_demo
    )
    return [_to_out(r) for r in reviews]


@router.post("/resolve", response_model=ReviewResolveResponse,
             summary="解析评测链接，获取真实元数据")
async def resolve_review(
    request: ReviewResolveRequest,
) -> ReviewResolveResponse:
    url = request.url.strip()
    if bilibili.is_bilibili_url(url):
        resolved = await bilibili.resolve_video(url)
        if not resolved.ok:
            return ReviewResolveResponse(ok=False, error=resolved.error)
        return ReviewResolveResponse(
            ok=True,
            review=_to_out(resolved.review),
            notice="元数据来自 B 站公开接口；观点整理需要人工填写，系统不会自动生成评测结论。",
        )
    # 抖音等其他平台：没有公开元数据接口，引导手动填写
    return ReviewResolveResponse(
        ok=False,
        error="暂不支持自动解析该平台的链接元数据",
        notice=(
            "哔哩哔哩链接可自动解析真实元数据；其他平台请手动填写标题、"
            "创作者与发布时间，整理内容同样会标注来源与整理时间。"
        ),
    )


@router.post("", response_model=ReviewOut, summary="提交评测链接与整理内容")
async def submit_review(
    request: ReviewSubmitRequest,
    session: AsyncSession = Depends(get_session),
) -> ReviewOut:
    url = request.url.strip()
    review: Optional[Review] = None
    if bilibili.is_bilibili_url(url):
        resolved = await bilibili.resolve_video(url)
        if resolved.ok:
            review = resolved.review
        # 解析失败时回退到手动填写，保证流程可用
    if review is None:
        if not (request.title and request.creator_name):
            raise HTTPException(
                status_code=400,
                detail="无法自动解析该链接，请至少手动填写标题与创作者名称",
            )
        review = Review(
            platform=_guess_platform(url),
            external_id=_external_id_from_url(url),
            url=url,
            title=request.title,
            creator_name=request.creator_name,
        )
    # 人工整理内容
    review.model_tested = request.model_tested
    review.pros = request.pros
    review.cons = request.cons
    review.quotes = request.quotes
    review.test_evidence = request.test_evidence
    review.scenarios = request.scenarios
    review.commercial_relation = request.commercial_relation
    review.curator_notes = request.curator_notes
    review.related_models = request.related_models
    review.curation_status = CurationStatus.PENDING
    review.curated_by = request.submitter
    review.curated_at = datetime.utcnow()
    review.data_status = DataStatus.REAL
    await curation_service.upsert_review(session, review)
    return _to_out(review)


@router.post("/{review_id}/curate", response_model=ReviewOut,
             summary="核实/修改/否决一条评测")
async def curate_review(
    review_id: str,
    request: ReviewCurateRequest,
    x_admin_token: Optional[str] = Header(None),
    session: AsyncSession = Depends(get_session),
) -> ReviewOut:
    _check_curation_auth(x_admin_token)
    payload = request.model_dump(exclude={"status", "curator"}, exclude_none=True)
    updated = await curation_service.curate_review(
        session, review_id,
        status=request.status,
        curator=request.curator,
        payload=payload,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="评测不存在")
    return _to_out(updated)


@router.post("/{review_id}/ai-summary", response_model=ReviewOut,
             summary="（可选）调用 LLM 归纳评测观点，结果明确标注为 AI 生成")
async def ai_summary(
    review_id: str,
    session: AsyncSession = Depends(get_session),
) -> ReviewOut:
    if not settings.LLM_API_KEY:
        raise HTTPException(
            status_code=400,
            detail="未配置 LLM_API_KEY，无法使用 AI 归纳；人工整理内容不受影响",
        )
    review = await curation_service.get_review(session, review_id)
    if review is None:
        raise HTTPException(status_code=404, detail="评测不存在")
    summary = await _call_llm(review)
    review.ai_summary = summary
    review.ai_generated_at = datetime.utcnow()
    await curation_service.upsert_review(session, review)
    return _to_out(review)


async def _call_llm(review: Review) -> str:
    """调用 OpenAI 兼容接口归纳观点。失败时返回说明，不编造内容。"""
    import httpx

    prompt = (
        "下面是一条商品评测的人工整理内容。请用中文客观归纳其优点、缺点与适用人群，"
        "不要引入整理内容之外的信息，不要下购买结论。\n\n"
        f"标题：{review.title}\n整理优点：{review.pros}\n整理缺点：{review.cons}\n"
        f"原话引用：{review.quotes}\n测试依据：{review.test_evidence}\n"
    )
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                settings.LLM_BASE_URL.rstrip("/") + "/chat/completions",
                headers={"Authorization": f"Bearer {settings.LLM_API_KEY}"},
                json={
                    "model": settings.LLM_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2,
                },
            )
            resp.raise_for_status()
            data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        return f"AI 归纳调用失败：{exc}"


# ─── helpers ───────────────────────────────────────────────────


def _guess_platform(url: str) -> ReviewPlatform:
    lowered = url.lower()
    if "bilibili" in lowered or "b23.tv" in lowered:
        return ReviewPlatform.BILIBILI
    if "douyin" in lowered:
        return ReviewPlatform.DOUYIN
    return ReviewPlatform.OTHER


def _external_id_from_url(url: str) -> str:
    import hashlib
    import re

    match = re.search(r"(BV[0-9A-Za-z]{10})", url)
    if match:
        return match.group(1)
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def _to_out(review: Review) -> ReviewOut:
    assessment = evaluate_review(review)
    from ..schemas import ReviewAssessmentOut

    return ReviewOut(
        id=review.id,
        platform=review.platform,
        url=review.url,
        title=review.title,
        creator_name=review.creator_name,
        creator_id=review.creator_id,
        creator_url=review.creator_url,
        cover_url=review.cover_url,
        published_at=review.published_at,
        duration_seconds=review.duration_seconds,
        view_count=review.view_count,
        like_count=review.like_count,
        model_tested=review.model_tested,
        pros=review.pros,
        cons=review.cons,
        quotes=review.quotes,
        test_evidence=review.test_evidence,
        scenarios=review.scenarios,
        commercial_relation=review.commercial_relation,
        curation_status=review.curation_status,
        curated_by=review.curated_by,
        curated_at=review.curated_at,
        curator_notes=review.curator_notes,
        ai_summary=review.ai_summary,
        ai_generated_at=review.ai_generated_at,
        data_status=review.data_status,
        fetched_at=review.fetched_at,
        related_models=review.related_models,
        relevance_note=review.relevance_note,
        assessment=ReviewAssessmentOut(
            checks=[
                {"dimension": c.dimension, "met": c.met, "note": c.note}
                for c in assessment.checks
            ],
            score=assessment.score,
            recommend_reference=assessment.recommend_reference,
        ),
    )
