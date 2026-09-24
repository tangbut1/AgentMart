"""评测整理服务（数据库读写 + 整理流程）。

流程设计（诚实、可核验）：
1. 用户提交评测链接 → 通过 B 站公开接口解析真实元数据（标题/UP主/时间/播放量）；
2. 提交人工整理内容（优点/缺点/原话引用/测试依据/商业关系标注）；
3. 管理员核实后标记为 verified，才会进入商品详情页的「评测观点」；
4. 每条评测始终保留原始出处链接与整理时间，方便用户自行核对。

安全说明：所有外部输入（链接、型号、ID）一律通过 SQLAlchemy ORM 的
参数化接口访问数据库，不拼接 SQL 字符串。
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import ReviewRecord
from ..domain.enums import (
    CommercialRelation,
    CurationStatus,
    DataStatus,
    ReviewPlatform,
)
from ..domain.models import Review
from ..domain.matching import extract_signature


def _record_id(review: Review) -> str:
    return review.platform.value + ":" + review.external_id


def _to_record(review: Review) -> ReviewRecord:
    return ReviewRecord(
        id=_record_id(review),
        platform=review.platform.value,
        external_id=review.external_id,
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
        pros=list(review.pros),
        cons=list(review.cons),
        quotes=list(review.quotes),
        test_evidence=list(review.test_evidence),
        scenarios=list(review.scenarios),
        commercial_relation=review.commercial_relation.value,
        curation_status=review.curation_status.value,
        curated_by=review.curated_by,
        curated_at=review.curated_at,
        curator_notes=review.curator_notes,
        ai_summary=review.ai_summary,
        ai_generated_at=review.ai_generated_at,
        data_status=review.data_status.value,
        fetched_at=review.fetched_at,
        related_models=list(review.related_models),
        relevance_note=review.relevance_note,
    )


def _from_record(record: ReviewRecord) -> Review:
    return Review(
        platform=ReviewPlatform(record.platform),
        external_id=record.external_id,
        url=record.url,
        title=record.title,
        creator_name=record.creator_name,
        creator_id=record.creator_id,
        creator_url=record.creator_url,
        cover_url=record.cover_url,
        published_at=record.published_at,
        duration_seconds=record.duration_seconds,
        view_count=record.view_count,
        like_count=record.like_count,
        model_tested=record.model_tested,
        pros=list(record.pros or []),
        cons=list(record.cons or []),
        quotes=list(record.quotes or []),
        test_evidence=list(record.test_evidence or []),
        scenarios=list(record.scenarios or []),
        commercial_relation=CommercialRelation(record.commercial_relation),
        curation_status=CurationStatus(record.curation_status),
        curated_by=record.curated_by,
        curated_at=record.curated_at,
        curator_notes=record.curator_notes,
        ai_summary=record.ai_summary,
        ai_generated_at=record.ai_generated_at,
        data_status=DataStatus(record.data_status),
        fetched_at=record.fetched_at,
        related_models=list(record.related_models or []),
        relevance_note=record.relevance_note,
    )


async def _all_records(session: AsyncSession) -> List[ReviewRecord]:
    result = await session.scalars(select(ReviewRecord))
    return list(result.all())


async def list_reviews(
    session: AsyncSession,
    status: Optional[CurationStatus] = None,
    include_demo: bool = False,
) -> List[Review]:
    reviews = [_from_record(r) for r in await _all_records(session)]
    if status is not None:
        reviews = [r for r in reviews if r.curation_status == status]
    if not include_demo:
        reviews = [r for r in reviews if r.data_status != DataStatus.DEMO]
    reviews.sort(key=lambda r: r.curated_at or datetime.min, reverse=True)
    return reviews


async def get_review(session: AsyncSession, review_id: str) -> Optional[Review]:
    record = await session.get(ReviewRecord, review_id)
    return _from_record(record) if record else None


async def upsert_review(session: AsyncSession, review: Review) -> Review:
    record = await session.get(ReviewRecord, _record_id(review))
    if record:
        # 元数据以新解析结果为准，人工整理内容保留
        for field in (
            "title", "creator_name", "creator_id", "creator_url", "cover_url",
            "published_at", "duration_seconds", "view_count", "like_count", "url",
        ):
            setattr(record, field, getattr(review, field))
        record.fetched_at = datetime.utcnow()
    else:
        session.add(_to_record(review))
    await session.commit()
    return review


async def curate_review(
    session: AsyncSession,
    review_id: str,
    *,
    status: CurationStatus,
    curator: str,
    payload: dict,
) -> Optional[Review]:
    record = await session.get(ReviewRecord, review_id)
    if record is None:
        return None
    record.curation_status = status.value
    record.curated_by = curator
    record.curated_at = datetime.utcnow()
    for field in (
        "model_tested", "pros", "cons", "quotes", "test_evidence",
        "scenarios", "commercial_relation", "curator_notes", "related_models",
        "relevance_note",
    ):
        if field in payload and payload[field] is not None:
            setattr(record, field, payload[field])
    await session.commit()
    await session.refresh(record)
    return _from_record(record)


async def find_reviews_for_model(
    session: AsyncSession, model_query: str, include_demo: bool = False
) -> List[Review]:
    """按型号找到相关的已核实评测（在内存中做 token 匹配）。"""
    reviews = await list_reviews(
        session, status=CurationStatus.VERIFIED, include_demo=include_demo
    )
    query_tokens = extract_signature(model_query).model_tokens
    matched: List[Review] = []
    for review in reviews:
        haystack = " ".join(
            filter(None, [review.title, review.model_tested, *review.related_models])
        )
        review_tokens = extract_signature(haystack).model_tokens
        if query_tokens and (query_tokens & review_tokens):
            matched.append(review)
        elif model_query and model_query.lower() in haystack.lower():
            matched.append(review)
    return matched


async def seed_demo_reviews(session: AsyncSession, keyword: str = "演示商品") -> None:
    """写入演示评测（虚构，标记 DEMO），仅用于无真实数据时走查界面。"""
    from ..adapters.demo import demo_reviews

    for review in demo_reviews(keyword):
        if await session.get(ReviewRecord, _record_id(review)) is None:
            session.add(_to_record(review))
    await session.commit()
