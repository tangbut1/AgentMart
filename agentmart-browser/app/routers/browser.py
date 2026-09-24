"""个人浏览器版接口。

安全边界在代码层面强制：
- 没有任何"领券/加购/下单/付款"端点，也没有预留后门；
- 模型配置接口永不返回 api_key；
- 清除登录态、清除模型 Key 都是显式端点，用户可以随时执行。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..browser import store
from ..browser.service import service

router = APIRouter(prefix="/api/browser", tags=["个人浏览器版"])


@router.get("/mode", summary="模式说明与边界")
async def mode_info() -> Dict[str, Any]:
    return service.mode_info()


# ---- 平台与登录态 ----

@router.get("/platforms", summary="五平台配方与登录态状态")
async def platforms() -> Dict[str, Any]:
    return service.platform_status()


@router.post("/platforms/{group}/login", summary="打开该平台的登录窗口（用户本人登录）")
async def open_login(group: str) -> Dict[str, Any]:
    """弹出一个可见的浏览器窗口。

    账号密码、短信验证码都由用户本人在这个窗口里输入；
    Agent 只每隔几秒探测一次「是否已登录」，不读取账号与 cookie。
    """
    return await service.open_login(group)


@router.post("/platforms/{group}/login/close", summary="关闭该平台的登录窗口")
async def close_login(group: str) -> Dict[str, Any]:
    return await service.close_login(group)


@router.post("/platforms/{group}/clear", summary="清除某平台浏览器登录态")
async def clear_profile(group: str) -> Dict[str, Any]:
    return service.clear_profile(group)


# ---- 模型配置（自带 Key） ----

@router.get("/model", summary="查看模型配置（不含 Key）")
async def get_model() -> Dict[str, Any]:
    return service.model_config()


@router.post("/model", summary="保存模型配置")
async def save_model(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    try:
        return await service.save_model_config(payload)
    except Exception as exc:  # 配置错误原样反馈，不写日志里的密钥
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/model/test", summary="测试连接与视觉能力")
async def test_model() -> Dict[str, Any]:
    return await service.test_model()


@router.delete("/model", summary="删除本地模型配置（含 API Key）")
async def delete_model() -> Dict[str, Any]:
    return service.delete_model_config()


@router.get("/model/usage", summary="本次会话模型调用统计")
async def model_usage() -> Dict[str, Any]:
    return service.model_usage()


# ---- 需求与任务 ----

@router.post("/parse", summary="解析自然语言需求")
async def parse_requirement(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    text = str(payload.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=422, detail="需求文本不能为空")
    return service.parse(text)


@router.post("/tasks", summary="创建购物任务")
async def create_task(
    payload: Dict[str, Any] = Body(...),
    session: AsyncSession = Depends(get_session),
) -> Dict[str, Any]:
    text = str(payload.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=422, detail="需求文本不能为空")
    platforms = payload.get("platforms")
    options = payload.get("options") or {}
    return await service.create_task(
        text, platforms=platforms, options=options, session=session
    )


@router.get("/tasks", summary="历史任务列表")
async def list_tasks(
    limit: int = 20,
    session: AsyncSession = Depends(get_session),
) -> List[Dict[str, Any]]:
    return await service.list_tasks(session, limit)


@router.get("/tasks/{task_id}", summary="任务实时状态")
async def get_task(
    task_id: str, session: AsyncSession = Depends(get_session)
) -> Dict[str, Any]:
    task = await service.persist(task_id, session)
    if task is not None:
        return service.task_view(task)
    # 任务不在内存（服务重启过）时，用落库快照顶住，历史任务仍可查看
    record = await store.get_task_record(session, task_id)
    if record is not None:
        return store.task_view_from_record(record)
    raise HTTPException(status_code=404, detail="任务不存在或已随服务重启结束")


@router.get("/tasks/{task_id}/result", summary="任务结果（购买卡片/对比/推荐）")
async def get_result(
    task_id: str, session: AsyncSession = Depends(get_session)
) -> Dict[str, Any]:
    try:
        return service.result_view(task_id)
    except KeyError:
        pass
    record = await store.get_task_record(session, task_id)
    result = (record or {}).get("result") or {}
    if not result:
        raise HTTPException(status_code=404, detail="任务不存在或结果尚未生成")
    return result


@router.post("/tasks/{task_id}/start", summary="开始执行")
async def start_task(
    task_id: str, session: AsyncSession = Depends(get_session)
) -> Dict[str, Any]:
    try:
        return await service.start_task(task_id, session=session)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc


@router.post("/tasks/{task_id}/answer", summary="回答任务的待决问题")
async def answer(
    task_id: str,
    payload: Dict[str, Any] = Body(...),
    session: AsyncSession = Depends(get_session),
) -> Dict[str, Any]:
    try:
        return await service.answer(
            task_id, str(payload.get("key") or ""), payload.get("value"), session=session
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/tasks/{task_id}/reviews", summary="运行中开关专业评测")
async def set_reviews(
    task_id: str, payload: Dict[str, Any] = Body(...)
) -> Dict[str, Any]:
    try:
        return service.set_include_reviews(task_id, bool(payload.get("value")))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc


@router.post("/tasks/{task_id}/cancel", summary="取消整个任务")
async def cancel_task(
    task_id: str, session: AsyncSession = Depends(get_session)
) -> Dict[str, Any]:
    try:
        return await service.cancel_task(task_id, session=session)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc


@router.post("/tasks/{task_id}/platforms/{platform}/cancel", summary="取消单个平台")
async def cancel_platform(
    task_id: str, platform: str, session: AsyncSession = Depends(get_session)
) -> Dict[str, Any]:
    try:
        return await service.cancel_platform(task_id, platform, session=session)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc


@router.post("/tasks/{task_id}/platforms/{platform}/pause", summary="暂停单个平台")
async def pause_platform(
    task_id: str, platform: str, session: AsyncSession = Depends(get_session)
) -> Dict[str, Any]:
    try:
        return await service.pause_platform(task_id, platform, session=session)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc


@router.post("/tasks/{task_id}/platforms/{platform}/resume", summary="恢复单个平台")
async def resume_platform(
    task_id: str, platform: str, session: AsyncSession = Depends(get_session)
) -> Dict[str, Any]:
    try:
        return await service.resume_platform(task_id, platform, session=session)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc


@router.get("/tasks/{task_id}/record", summary="从数据库读取任务记录")
async def task_record(
    task_id: str, session: AsyncSession = Depends(get_session)
) -> Optional[Dict[str, Any]]:
    record = await service.task_record(session, task_id)
    if record is None:
        raise HTTPException(status_code=404, detail="没有该任务的持久化记录")
    return record


@router.delete("/tasks/{task_id}", summary="删除任务记录")
async def delete_task(
    task_id: str, session: AsyncSession = Depends(get_session)
) -> Dict[str, Any]:
    removed = await service.delete_task(session, task_id)
    if not removed:
        raise HTTPException(status_code=404, detail="没有该任务的持久化记录")
    return {"removed": True, "id": task_id}
