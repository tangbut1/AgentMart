"""手动登录窗口：给用户一个**显式**的登录入口。

为什么单独做这一层：登录只能由用户本人在官方页面完成。原来的设计是
「任务跑起来、发现没登录、再弹窗等你」，问题是用户没法**提前**登录——
他想先登好再开始比价，或者只想看看某个平台登上去没有，都没有入口。

这里补上的就是这个入口：用户点「登录」→ 弹出该平台的可见浏览器窗口 →
用户自己扫码/输账号 → Agent 每隔几秒只探测「是否已登录」→ 探到了就告诉你登好了。

硬约束（都在代码里）：
- 同一个 profile 目录同时只能被一个 Chromium 持久化上下文占用，
  所以登录窗口和任务窗口对同一个组**互斥**，`agent._acquire_session` 会挡住任务；
- 探测脚本只读 DOM 判断有没有登录入口/用户标识，**不读账号、不读 cookie、
  不读任何输入框内容**，也不把结果发给模型；
- 不代填账号密码、不代输验证码、不尝试识别或绕过验证码；
- 窗口开太久（用户忘了关）自动收掉，避免一直占着 profile 目录。
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from loguru import logger

from ..domain.enums import Platform
from .driver import BrowserDriver, PlaywrightConfig, PlaywrightDriver
from .profiles import ensure_profile_dir, mark_verified, platforms_for_group
from .recipes import JS_LOGIN_PROBE, get_recipe

# 轮询间隔：够快让用户一登完就看到状态，又不至于频繁求值打扰页面
POLL_INTERVAL_SECONDS = 2.0
# 登录窗口最长存在时间，超时自动关闭（用户忘了关时兜底）
MAX_LOGIN_WINDOW_SECONDS = 30 * 60

# 登录窗口状态
OPENING = "opening"              # 窗口正在拉起
WAITING_LOGIN = "waiting_login"  # 窗口已打开，等你登录
LOGGED_IN = "logged_in"          # 探测到已登录
CLOSED = "closed"                # 窗口已关闭（你关的或超时收的）
FAILED = "failed"                # 窗口没打开起来

_LABELS = {
    OPENING: "正在打开窗口",
    WAITING_LOGIN: "等待你登录",
    LOGGED_IN: "已登录",
    CLOSED: "窗口已关闭",
    FAILED: "打开失败",
}


class LoginUnavailable(RuntimeError):
    """打不开登录窗口（组名不认识 / 该组正被任务占用 / 浏览器起不来）。"""


@dataclass
class LoginSession:
    """一个平台组的手动登录窗口。"""

    group: str
    platform: Platform
    driver: BrowserDriver
    status: str = OPENING
    message: str = ""
    opened_at: datetime = field(default_factory=datetime.now)
    last_checked_at: Optional[datetime] = None
    poller: Optional[asyncio.Task] = None

    @property
    def status_label(self) -> str:
        return _LABELS.get(self.status, self.status)

    @property
    def is_open(self) -> bool:
        return self.status in (OPENING, WAITING_LOGIN, LOGGED_IN)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "group": self.group,
            "platform": self.platform.value,
            "platforms": [p.value for p in platforms_for_group(self.group)],
            "status": self.status,
            "status_label": self.status_label,
            "message": self.message,
            "opened_at": self.opened_at.strftime("%H:%M:%S"),
            "last_checked_at": (
                self.last_checked_at.strftime("%H:%M:%S") if self.last_checked_at else None
            ),
        }


class LoginManager:
    """管理各平台组的手动登录窗口（挂在 ShoppingAgent 上，随服务生命周期）。"""

    def __init__(self) -> None:
        self._sessions: Dict[str, LoginSession] = {}

    # ---- 查询 ----
    def get(self, group: str) -> Optional[LoginSession]:
        session = self._sessions.get(group)
        # 已结束的窗口不占着记录，也不该再显示成"开着"
        if session is not None and not session.is_open:
            return session
        return session

    def open_groups(self) -> List[str]:
        return [g for g, s in self._sessions.items() if s.is_open]

    def is_busy(self, group: str) -> bool:
        session = self._sessions.get(group)
        return session is not None and session.is_open

    def status(self) -> List[Dict[str, Any]]:
        """所有组的登录窗口状态（没有开过窗口的组也列出来，方便前端统一渲染）。"""
        out: List[Dict[str, Any]] = []
        for group in sorted({g for g in self._sessions} | set(_all_groups())):
            session = self._sessions.get(group)
            if session is None:
                out.append(
                    {
                        "group": group,
                        "platforms": [p.value for p in platforms_for_group(group)],
                        "status": "idle",
                        "status_label": "未打开",
                        "message": "",
                        "opened_at": None,
                        "last_checked_at": None,
                    }
                )
            else:
                out.append(session.to_dict())
        return out

    # ---- 开窗 ----
    async def open(
        self,
        group: str,
        *,
        driver_factory=None,
        busy_groups: Optional[List[str]] = None,
    ) -> LoginSession:
        platforms = platforms_for_group(group)  # 组名不认识时这里就抛错
        platform = platforms[0]

        existing = self._sessions.get(group)
        if existing is not None and existing.is_open:
            # 已经开着就复用，不重复弹窗（重复弹会把用户搞糊涂）
            return existing

        if busy_groups and group in busy_groups:
            raise LoginUnavailable(
                "该平台正在执行比价任务，请先等任务结束，或先取消该平台"
            )

        if driver_factory is not None:
            driver = driver_factory(platform)
        else:
            # 登录窗口必须可见：用户要自己看到页面、自己扫码、自己输账号
            driver = PlaywrightDriver(
                str(ensure_profile_dir(platform)),
                PlaywrightConfig(headless=False, slow_mo_ms=0),
            )

        session = LoginSession(group=group, platform=platform, driver=driver)
        self._sessions[group] = session
        try:
            await driver.start()
        except Exception as exc:
            session.status = FAILED
            session.message = f"浏览器窗口没能打开：{exc}"
            logger.warning(f"登录窗口打开失败[{group}]: {exc}")
            raise LoginUnavailable(session.message) from exc

        # 打开平台首页，让用户直接在这个页面登录
        home = get_recipe(platform).home_url
        try:
            await driver.goto(home)
            session.message = f"已在可见窗口打开 {home}，请你自己完成登录或扫码。"
        except Exception as exc:
            # 页面没打开也把窗口留给用户，他自己能输地址
            session.message = f"窗口已打开，但没能自动跳到 {home}（{exc}），请手动访问。"
            logger.warning(f"登录窗口跳转失败[{group}]: {exc}")

        session.status = WAITING_LOGIN
        session.poller = asyncio.create_task(self._poll(session))
        return session

    # ---- 关窗 ----
    async def close(self, group: str) -> Dict[str, Any]:
        session = self._sessions.get(group)
        if session is None:
            return {"group": group, "closed": False, "message": "这个平台没有打开过登录窗口"}
        await self._teardown(session, CLOSED, "窗口已关闭")
        return {
            "group": group,
            "closed": True,
            "message": "窗口已关闭。登录态仍保留在本机，下次任务可以直接用。",
        }

    async def close_all(self) -> None:
        for group in list(self._sessions):
            session = self._sessions[group]
            if session.is_open:
                await self._teardown(session, CLOSED, "服务关闭，窗口已收起")

    # ---- 内部 ----
    async def _poll(self, session: LoginSession) -> None:
        """只探测登录状态，不读账号、不读 cookie、不碰任何输入框。"""
        deadline = asyncio.get_running_loop().time() + MAX_LOGIN_WINDOW_SECONDS
        while True:
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            if not session.is_open:
                return
            if asyncio.get_running_loop().time() > deadline:
                await self._teardown(
                    session,
                    CLOSED,
                    f"登录窗口已开满 {MAX_LOGIN_WINDOW_SECONDS // 60} 分钟，自动收起来了；"
                    "登录态若已保存仍然有效。",
                )
                return
            try:
                probe = await session.driver.evaluate(JS_LOGIN_PROBE)
            except Exception as exc:
                # 求值失败基本都是用户把窗口关了，或浏览器崩了
                logger.info(f"登录窗口探测中断[{session.group}]: {exc}")
                await self._teardown(session, CLOSED, "浏览器窗口已关闭")
                return
            session.last_checked_at = datetime.now()
            if isinstance(probe, dict) and probe.get("looksLoggedIn"):
                session.status = LOGGED_IN
                session.message = (
                    "检测到已登录。可以关掉这个窗口了——登录态保存在本机，"
                    "接下来的比价任务会直接用。"
                )
                # 落一个本机标记，否则窗口一关、服务一重启，界面又退回
                # "有登录态，未验证"，用户刚登好的账号像没登一样
                mark_verified(session.group)
                logger.info(f"登录窗口探测到已登录[{session.group}]")
                return
            if session.status == OPENING:
                session.status = WAITING_LOGIN

    async def _teardown(self, session: LoginSession, status: str, message: str) -> None:
        session.status = status
        session.message = message
        poller = session.poller
        session.poller = None
        if poller is not None and not poller.done():
            poller.cancel()
        try:
            await session.driver.stop()
        except Exception as exc:  # 关不掉也不能让服务挂掉
            logger.warning(f"关闭登录窗口失败[{session.group}]: {exc}")


def _all_groups() -> List[str]:
    from .profiles import all_profiles

    return [p.group for p in all_profiles()]
