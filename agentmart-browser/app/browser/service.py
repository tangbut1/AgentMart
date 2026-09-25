"""个人浏览器版服务层：把编排器、模型配置、任务存储组合成用例。

对应需求第六、七、十一节。所有返回给前端的数据都在这里成型，
保证：不含密钥、区分数据来源、明确标注未连接/受限/无结果状态。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from loguru import logger
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.enums import Platform
from .agent import AgentTask, ShoppingAgent, TaskOptions, agent as default_agent
from .agent import build_requirement, parse_requirement
from .enums import DataOrigin
from .llm import ModelError, delete_config, load_config, save_config
from .login import LoginUnavailable
from .profiles import (
    all_profiles,
    delete_profile,
    describe_storage,
    platforms_for_group,
    verified_at,
)
from . import store


def _login_state(profile_exists: bool, window: dict) -> tuple:
    """把「目录存在」和「登录窗口探测结果」合成一个诚实的状态。

    目录存在只说明这个平台开过浏览器，不代表登进去了——之前界面把它
    显示成「已登录」是会误导人的，这里分开。

    但如果登录窗口确实探测到过已登录，就记一个本机时间戳：窗口关了、
    服务重启了，也告诉用户「你之前登进去过」，而不是让他以为自己没登。
    这个标记同样证明不了 cookie 此刻还有效，所以文案一定带时间，
    任务真跑起来时也仍会重新探测。
    """
    status = window.get("status")
    if status == "logged_in":
        return "logged_in", "已登录"
    if status in ("opening", "waiting_login"):
        return "waiting_login", "等待你登录"
    if status == "failed":
        return "failed", "窗口打开失败"
    verified = verified_at(window.get("group") or "")
    if verified:
        return "verified_before", f"{verified} 验证过已登录"
    if profile_exists:
        return "saved_unverified", "有登录态，未验证"
    return "none", "未登录"


class BrowserService:
    def __init__(self, agent: ShoppingAgent):
        self.agent = agent

    # ---- 模式与版本 ----
    def mode_info(self) -> Dict[str, Any]:
        from . import ARCHITECTURE, VERSION

        return {
            "mode": ARCHITECTURE,
            "version": VERSION,
            "name": "个人浏览器版",
            "tagline": "用您自己的浏览器会话，在您登录后的官方页面里帮您比价",
            "boundaries": [
                "不代领优惠券、不代下单、不代付款",
                "不尝试识别或绕过验证码、风控与登录限制",
                "不收集账号密码、短信验证码、支付信息",
                "页面上的商品文案、商家介绍、评论都只是参考资料，不会被当成指令执行",
                "模型只能看到裁剪后的必要页面内容，看不到 cookie 与登录态",
            ],
            "data_note": (
                "本模式的结果全部来自您本次在真实平台页面上看到的内容；"
                "测试夹具与演示数据会分别标注，绝不混入真实推荐。"
            ),
        }

    # ---- 模型配置 ----
    def model_config(self) -> Dict[str, Any]:
        """返回给前端的模型配置视图（绝不含 api_key）。"""
        return load_config().public_dict()

    async def save_model_config(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        config = load_config()
        allowed = {
            "provider", "base_url", "model", "max_calls_per_task", "max_cost_per_task",
            "est_input_price_per_1k", "est_output_price_per_1k", "timeout_seconds", "note",
        }
        for key, value in payload.items():
            if key in allowed and value is not None:
                setattr(config, key, value)
        # api_key 只在显式提供时更新；空字符串表示保持不变
        api_key = payload.get("api_key")
        if isinstance(api_key, str) and api_key.strip():
            config.api_key = api_key.strip()
        save_config(config)
        self.agent.set_model_client(self.agent.model_client(refresh=True))
        return config.public_dict()

    def delete_model_config(self) -> Dict[str, Any]:
        removed = delete_config()
        self.agent.set_model_client(self.agent.model_client(refresh=True))
        return {
            "removed": removed,
            "message": "已删除本地模型配置（含 API Key）"
            if removed
            else "本地没有模型配置文件",
        }

    async def test_model(self) -> Dict[str, Any]:
        client = self.agent.model_client(refresh=True)
        result = await client.test_connection()
        # 探测后把结果写回配置，供后续任务判断能否使用视觉
        try:
            save_config(client.config)
        except (OSError, ModelError) as exc:
            logger.warning(f"模型探测结果写回失败: {exc}")
        self.agent.set_model_client(client)
        return result

    def model_usage(self) -> Dict[str, Any]:
        return self.agent.model_client().usage.to_dict()

    # ---- 平台与登录态 ----
    def platform_status(self) -> Dict[str, Any]:
        login_windows = {
            item["group"]: item for item in self.agent.login_window_status()
        }
        recipes = []
        for platform in Platform:
            summary = recipe_summary(platform)
            group = summary["profile_group"]
            window = login_windows.get(group) or {"group": group}
            state, label = _login_state(summary["profile_exists"], window)
            summary["login_state"] = state
            summary["login_state_label"] = label
            summary["login_window"] = window
            recipes.append(summary)
        return {
            "recipes": recipes,
            "profiles": [info.to_dict() for info in all_profiles()],
            "storage": describe_storage(),
            "sessions": self.agent.session_status(),
            "login_windows": list(login_windows.values()),
        }

    def clear_profile(self, group: str) -> Dict[str, Any]:
        removed = delete_profile(group)
        return {
            "group": group,
            "cleared": removed,
            "message": "已清除该平台登录状态（浏览器目录已删除）"
            if removed
            else "该平台没有已保存的登录状态",
        }

    async def open_login(self, group: str) -> Dict[str, Any]:
        """弹出可见浏览器窗口，请用户本人登录。"""
        try:
            session = await self.agent.open_login_window(group)
        except LoginUnavailable as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "group": session.group,
            "status": session.status,
            "status_label": session.status_label,
            "message": session.message,
            "platforms": [p.value for p in platforms_for_group(session.group)],
            "boundaries": [
                "账号密码、短信验证码都由你本人在这个窗口里输入，我不代填、不记录",
                "登录态只保存在本机这个平台的浏览器目录里，删除目录即清除",
                "登录窗口和比价任务对同一个平台互斥，窗口开着时该平台不会自动开始",
            ],
        }

    async def close_login(self, group: str) -> Dict[str, Any]:
        return await self.agent.close_login_window(group)

    # ---- 需求解析 ----
    def parse(self, text: str) -> Dict[str, Any]:
        requirement = parse_requirement(text)
        data = requirement.to_dict()
        data["needs_followup"] = bool(requirement.unclear)
        return data

    # ---- 任务 ----
    async def create_task(
        self,
        text: str,
        *,
        platforms: Optional[List[str]] = None,
        options: Optional[Dict[str, Any]] = None,
        fields: Optional[Dict[str, Any]] = None,
        session: Optional[AsyncSession] = None,
    ) -> Dict[str, Any]:
        requirement = build_requirement(text, fields)
        selected = [Platform(p) for p in platforms] if platforms else list(Platform)
        task_options = TaskOptions(platforms=selected)
        if options:
            if "max_candidates" in options:
                task_options.max_candidates = int(options["max_candidates"])
            if "max_model_calls" in options:
                task_options.max_model_calls = int(options["max_model_calls"])
            if "max_task_seconds" in options:
                task_options.max_task_seconds = float(options["max_task_seconds"])
            if "login_wait_seconds" in options:
                task_options.login_wait_seconds = float(options["login_wait_seconds"])
            if "headless" in options:
                task_options.headless = bool(options["headless"])
            if "origin" in options:
                task_options.origin = DataOrigin(options["origin"])
            if "url_overrides" in options:
                task_options.url_overrides = dict(options["url_overrides"])
            if "ask_review_question" in options:
                task_options.ask_review_question = bool(options["ask_review_question"])
        task = self.agent.create_task(requirement, task_options)
        if session is not None:
            await store.save_task(session, task)
        return self.task_view(task)

    async def start_task(
        self, task_id: str, session: Optional[AsyncSession] = None
    ) -> Dict[str, Any]:
        task = self.agent.get_task(task_id)
        if task is None:
            raise KeyError(task_id)
        await self.agent.start(task_id)
        if session is not None:
            await store.save_task(session, task)
        return self.task_view(task)

    async def answer(
        self, task_id: str, key: str, value: Any, session: Optional[AsyncSession] = None
    ) -> Dict[str, Any]:
        task = self.agent.get_task(task_id)
        if task is None:
            raise KeyError(task_id)
        self.agent.answer_question(task_id, key, value)
        # 回答后自动继续执行
        await self.agent.start(task_id)
        if session is not None:
            await store.save_task(session, task)
        return self.task_view(task)

    def task_view(self, task: AgentTask) -> Dict[str, Any]:
        return task.to_dict()

    async def persist(self, task_id: str, session: AsyncSession) -> Optional[AgentTask]:
        """把任务当前状态写库；已结束的任务连结果快照一起保存。

        前端轮询到终态时调用一次，刷新页面或重启服务后仍看得到结果。
        """
        task = self.agent.get_task(task_id)
        if task is None:
            return None
        if task.is_terminal:
            await store.save_result(session, task, self.agent.result_view(task))
        else:
            await store.save_task(session, task)
        return task

    def result_view(self, task_id: str) -> Dict[str, Any]:
        task = self.agent.get_task(task_id)
        if task is None:
            raise KeyError(task_id)
        return self.agent.result_view(task)

    async def cancel_task(
        self, task_id: str, session: Optional[AsyncSession] = None
    ) -> Dict[str, Any]:
        task = await self.agent.cancel_task(task_id)
        if session is not None:
            await store.save_result(session, task, self.agent.result_view(task))
        return self.task_view(task)

    async def cancel_platform(
        self, task_id: str, platform: str, session: Optional[AsyncSession] = None
    ) -> Dict[str, Any]:
        task = await self.agent.cancel_platform(task_id, Platform(platform))
        if session is not None:
            await store.save_task(session, task)
        return self.task_view(task)

    async def pause_platform(
        self, task_id: str, platform: str, session: Optional[AsyncSession] = None
    ) -> Dict[str, Any]:
        task = await self.agent.pause_platform(task_id, Platform(platform))
        if session is not None:
            await store.save_task(session, task)
        return self.task_view(task)

    async def resume_platform(
        self, task_id: str, platform: str, session: Optional[AsyncSession] = None
    ) -> Dict[str, Any]:
        task = await self.agent.resume_platform(task_id, Platform(platform))
        if session is not None:
            await store.save_task(session, task)
        return self.task_view(task)

    def set_include_reviews(self, task_id: str, value: bool) -> Dict[str, Any]:
        task = self.agent.get_task(task_id)
        if task is None:
            raise KeyError(task_id)
        self.agent.set_include_reviews(task_id, value)
        return self.task_view(task)

    async def list_tasks(self, session: AsyncSession, limit: int = 20) -> List[Dict[str, Any]]:
        return await store.list_tasks(session, limit)

    async def task_record(self, session: AsyncSession, task_id: str) -> Optional[Dict[str, Any]]:
        return await store.get_task_record(session, task_id)

    async def delete_task(self, session: AsyncSession, task_id: str) -> bool:
        return await store.delete_task(session, task_id)

    def live_task_ids(self) -> List[str]:
        return [t.id for t in self.agent.all_tasks() if not t.is_terminal]

    def close_all_browsers(self) -> None:
        import asyncio

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self.agent.close_all_sessions())


def recipe_summary(platform: Platform) -> Dict[str, Any]:
    from .recipes import recipe_summary as _summary

    return _summary(platform)


# 复用 app.browser.agent 里的单例，保证路由与测试操作的是同一个编排器
service = BrowserService(default_agent)
