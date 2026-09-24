"""AgentMart 个人浏览器版 — 数据库访问层。

只存任务快照与结果，不存 cookie、登录态、截图原图、账号信息。
默认使用本地 SQLite（零配置启动）。
"""
from __future__ import annotations

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from .config import settings
from loguru import logger


class Base(DeclarativeBase):
    pass


engine = create_async_engine(settings.DATABASE_URL, echo=False)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _add_missing_columns(conn)


# 本地 SQLite 没有迁移工具，新增列时由这里补齐（列名写死在代码里，
# 不涉及任何外部输入）。生产环境建议改用 Alembic。
_ADDED_COLUMNS = {
    "browser_tasks": (
        ("requirement", "TEXT DEFAULT ''"),
        ("waiting_reason", "TEXT DEFAULT ''"),
        ("pending_question", "TEXT DEFAULT ''"),
    ),
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
