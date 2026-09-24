"""数据库访问层。

默认使用本地 SQLite（零配置启动）；通过 DATABASE_URL 可切换 Postgres：
    postgresql+asyncpg://user:pass@host:5432/agentmart
表结构在应用启动时自动创建（create_all），生产环境建议改用 Alembic。
"""
from __future__ import annotations

from datetime import datetime
from typing import AsyncGenerator

from sqlalchemy import JSON, DateTime, Float, Integer, String, Text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .config import settings
from loguru import logger


class Base(DeclarativeBase):
    pass


class ReviewRecord(Base):
    """经人工整理流程入库的评测。"""

    __tablename__ = "review_records"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    platform: Mapped[str] = mapped_column(String(16), nullable=False)
    external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    url: Mapped[str] = mapped_column(String(512), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    creator_name: Mapped[str] = mapped_column(String(128), nullable=False)
    creator_id: Mapped[str | None] = mapped_column(String(64))
    creator_url: Mapped[str | None] = mapped_column(String(512))
    cover_url: Mapped[str | None] = mapped_column(String(512))
    published_at: Mapped[datetime | None] = mapped_column(DateTime)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    view_count: Mapped[int | None] = mapped_column(Integer)
    like_count: Mapped[int | None] = mapped_column(Integer)
    # 人工整理内容
    model_tested: Mapped[str | None] = mapped_column(String(256))
    pros: Mapped[list] = mapped_column(JSON, default=list)
    cons: Mapped[list] = mapped_column(JSON, default=list)
    quotes: Mapped[list] = mapped_column(JSON, default=list)
    test_evidence: Mapped[list] = mapped_column(JSON, default=list)
    scenarios: Mapped[list] = mapped_column(JSON, default=list)
    commercial_relation: Mapped[str] = mapped_column(String(32), default="unknown")
    curation_status: Mapped[str] = mapped_column(String(16), default="pending")
    curated_by: Mapped[str | None] = mapped_column(String(128))
    curated_at: Mapped[datetime | None] = mapped_column(DateTime)
    curator_notes: Mapped[str | None] = mapped_column(Text)
    # 可选 AI 归纳（与人工整理分开）
    ai_summary: Mapped[str | None] = mapped_column(Text)
    ai_generated_at: Mapped[datetime | None] = mapped_column(DateTime)
    # 溯源
    data_status: Mapped[str] = mapped_column(String(16), default="real")
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime)
    related_models: Mapped[list] = mapped_column(JSON, default=list)
    relevance_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class PriceObservation(Base):
    """一次价格采集的快照，用于来源与新鲜度展示。"""

    __tablename__ = "price_observations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(16), nullable=False)
    platform_product_id: Mapped[str] = mapped_column(String(64), nullable=False)
    offer_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(512))
    url: Mapped[str] = mapped_column(String(512))
    source: Mapped[str] = mapped_column(String(64))
    data_status: Mapped[str] = mapped_column(String(16), default="real")
    definite_total: Mapped[float | None] = mapped_column(Float)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


engine = create_async_engine(settings.DATABASE_URL, echo=False)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _add_missing_columns(conn)


# 本地 SQLite 没有迁移工具，新增列时由这里补齐（列名写死在代码里，
# 不涉及任何外部输入）。生产环境建议改用 Alembic。
_ADDED_COLUMNS = {
    "browser_tasks": (("requirement", "TEXT DEFAULT ''"),),
}


async def _add_missing_columns(conn) -> None:
    if conn.dialect.name != "sqlite":
        return
    for table, columns in _ADDED_COLUMNS.items():
        rows = await conn.exec_driver_sql(f"PRAGMA table_info({table})")
        existing = {row[1] for row in rows}
        for name, ddl in columns:
            if name not in existing:
                await conn.exec_driver_sql(
                    f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"
                )
                logger.info(f"已为 {table} 补充字段 {name}")


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session
