"""个人浏览器版任务存储（SQLite）。

任务执行期间状态在内存里（agent.py），这里负责：
- 任务摘要落库，刷新页面/重启服务后仍能看到历史任务；
- 已完成任务的结果快照落库（含证据与来源），便于复核；
- 全部读写走 SQLAlchemy ORM 的对象接口（get / add / delete / scalars），
  代码里不手写任何 SQL 文本，也就不存在拼接或格式化组装查询的可能；
  所有字段值由 ORM 作为绑定参数下发。

刻意**不**入库的内容：浏览器 cookie、登录态、模型 API Key、
截图原图、用户账号信息。证据只以元信息（URL/时间/字段定位）保存，
原图留在本地临时目录。
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import DateTime, Integer, String, Text, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from .agent import AgentTask


class BrowserTaskRecord(Base):
    """一次个人浏览器购物任务的快照。"""

    __tablename__ = "browser_tasks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    origin: Mapped[str] = mapped_column(String(24), nullable=False)
    requirement_text: Mapped[str] = mapped_column(Text, default="")
    # 任务参数与平台状态（JSON 字符串，仅含可展示信息）
    options: Mapped[str] = mapped_column(Text, default="")
    platforms: Mapped[str] = mapped_column(Text, default="")
    # 结果快照（JSON 字符串）
    result: Mapped[str] = mapped_column(Text, default="")
    # 解析后的需求（JSON 字符串）：重启后不能靠重新解析文本来复原，
    # 同一句话在不同版本解析器下的结果可能不同，必须以当时入库的为准
    requirement: Mapped[str] = mapped_column(Text, default="")
    offer_count: Mapped[int] = mapped_column(Integer, default=0)
    group_count: Mapped[int] = mapped_column(Integer, default=0)
    model_usage: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _loads(value: Any) -> Any:
    if value in (None, ""):
        return {}
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return {}


def _snapshot(task: AgentTask, result: Optional[dict] = None) -> Dict[str, Any]:
    """把任务转成一条可持久化的字段字典。"""
    return {
        "status": task.status.value,
        "origin": task.origin.value,
        "requirement_text": task.requirement.text,
        "options": _dumps(task.options.to_dict()),
        "platforms": _dumps([task.states[p].to_dict() for p in task.options.platforms]),
        "result": _dumps(result or {}),
        "requirement": _dumps(task.requirement.to_dict()),
        "offer_count": len(task.real_offers),
        "group_count": len(task.canonical),
        "model_usage": _dumps(task.model_usage),
        "notes": _dumps(list(task.notes)),
        "updated_at": datetime.utcnow(),
    }


async def _upsert(session: AsyncSession, task: AgentTask, result: Optional[dict]) -> None:
    record = await session.get(BrowserTaskRecord, task.id)
    fields = _snapshot(task, result)
    if record is None:
        session.add(BrowserTaskRecord(id=task.id, created_at=datetime.utcnow(), **fields))
    else:
        for key, value in fields.items():
            setattr(record, key, value)
    await session.commit()


async def save_task(session: AsyncSession, task: AgentTask) -> None:
    """写入或更新任务快照（含进行中的状态）。"""
    await _upsert(session, task, None)


async def save_result(session: AsyncSession, task: AgentTask, result: dict) -> None:
    """任务结束后保存结果快照。"""
    await _upsert(session, task, result)


async def list_tasks(session: AsyncSession, limit: int = 20) -> List[Dict[str, Any]]:
    stmt = select(BrowserTaskRecord).order_by(BrowserTaskRecord.created_at.desc())
    rows = (await session.scalars(stmt)).all()
    return [_summary(row) for row in rows[: max(0, int(limit))]]


async def get_task_record(
    session: AsyncSession, task_id: str
) -> Optional[Dict[str, Any]]:
    record = await session.get(BrowserTaskRecord, task_id)
    if record is None:
        return None
    data = _summary(record)
    data["result"] = _loads(record.result)
    data["requirement"] = _loads(record.requirement)
    data["options"] = _loads(record.options)
    data["platforms"] = _loads(record.platforms)
    return data


async def delete_task(session: AsyncSession, task_id: str) -> bool:
    record = await session.get(BrowserTaskRecord, task_id)
    if record is None:
        return False
    await session.delete(record)
    await session.commit()
    return True


def _summary(record: BrowserTaskRecord) -> Dict[str, Any]:
    return {
        "id": record.id,
        "status": record.status,
        "origin": record.origin,
        "requirement_text": record.requirement_text,
        "offer_count": record.offer_count or 0,
        "group_count": record.group_count or 0,
        "model_usage": _loads(record.model_usage),
        "notes": _loads(record.notes),
        "created_at": _fmt(record.created_at),
        "updated_at": _fmt(record.updated_at),
    }


def _fmt(value: Any) -> Optional[str]:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value) if value else None


def result_to_json(result: Dict[str, Any]) -> str:
    """调试用：把结果转成可读 JSON（不含密钥）。"""
    return json.dumps(result, ensure_ascii=False, indent=2)


def task_view_from_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """用落库快照重建任务视图（服务重启后任务已不在内存时使用）。

    重建出的字段与 ``AgentTask.to_dict()`` 保持一致，前端无需区分
    「内存中的实时任务」和「重启后从库里读回来的历史任务」。
    """
    from .enums import DataOrigin, TaskStatus

    status = TaskStatus(record["status"])
    origin = DataOrigin(record.get("origin") or DataOrigin.REAL_PLATFORM_PAGE.value)
    result = record.get("result") or {}
    platforms = record.get("platforms") or []
    requirement = record.get("requirement") or {}
    if not requirement:
        # 老记录没有存需求字典，只能退回重新解析（可能和当时不完全一致）
        from .agent import parse_requirement

        requirement = parse_requirement(
            str(record.get("requirement_text") or "")
        ).to_dict()
    return {
        "id": record["id"],
        "status": status.value,
        "status_label": status.label,
        "summary_status": status.value,
        "summary_status_label": status.label,
        "origin": origin.value,
        "origin_label": origin.label,
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
        "requirement": requirement,
        "options": record.get("options") or {},
        "platforms": platforms,
        "waiting_reason": None,
        "pending_question": None,
        "budget_exhausted": bool(result.get("budget_exhausted")),
        "model_usage": record.get("model_usage") or {},
        "notes": list(record.get("notes") or []),
        "offer_count": int(record.get("offer_count") or 0),
        "group_count": int(record.get("group_count") or 0),
        "restored": True,
    }
