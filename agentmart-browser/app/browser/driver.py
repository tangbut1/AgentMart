"""浏览器驱动抽象：Playwright 实现 + 测试用脚本化驱动。

为什么选 Playwright：
- 支持 ``launch_persistent_context``：每个平台一个独立的用户数据目录，
  登录态天然隔离，用户可以在**可见窗口**里亲自登录；
- 异步 API 能与 FastAPI 事件环共存，浏览器是独立进程，用户随时可以
  在窗口里操作、扫码、关掉；
- 选择器与 DOM 求值稳定，先用确定性步骤、只在必要时才用视觉模型。

测试用 ``ScriptedDriver``：不发浏览器、不联网，按脚本返回求值结果，
用于状态机 / 预算 / 取消 / 隔离等逻辑回归。
"""
from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol


class DriverError(RuntimeError):
    pass


class BrowserDriver(Protocol):
    """驱动协议：只暴露只读动作。"""

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def goto(self, url: str, timeout_ms: int = 20000) -> bool: ...

    async def evaluate(self, script: str, arg: Any = None) -> Any: ...

    async def screenshot_clip(self, selector: Optional[str] = None) -> Optional[bytes]: ...

    @property
    def current_url(self) -> str: ...


@dataclass
class PlaywrightConfig:
    headless: bool = False
    slow_mo_ms: int = 0
    viewport: Dict[str, int] = field(default_factory=lambda: {"width": 1280, "height": 900})
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )


class PlaywrightDriver:
    """基于 Playwright 的可见浏览器驱动（每平台一个持久化上下文）。"""

    def __init__(self, user_data_dir: str, config: Optional[PlaywrightConfig] = None):
        self.user_data_dir = user_data_dir
        self.config = config or PlaywrightConfig()
        self._playwright = None
        self._context = None
        self._page = None

    async def start(self) -> None:
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        # 持久化上下文：登录态落在 user_data_dir，用户可见、可随时接管
        self._context = await self._playwright.chromium.launch_persistent_context(
            self.user_data_dir,
            headless=self.config.headless,
            slow_mo=self.config.slow_mo_ms,
            viewport=self.config.viewport,
            user_agent=self.config.user_agent,
            # 刻意不传 --disable-blink-features=AutomationControlled：
            # 那会抹掉 navigator.webdriver，属于"隐藏自动化身份"，
            # 与产品的安全边界冲突。宁可被平台识别出来，也不做规避。
        )
        pages = self._context.pages
        self._page = pages[0] if pages else await self._context.new_page()
        self._page.set_default_timeout(20000)

    async def stop(self) -> None:
        try:
            if self._context is not None:
                await self._context.close()
        finally:
            if self._playwright is not None:
                await self._playwright.stop()
            self._context = None
            self._page = None
            self._playwright = None

    async def goto(self, url: str, timeout_ms: int = 20000) -> bool:
        if self._page is None:
            raise DriverError("浏览器尚未启动")
        try:
            await self._page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            return True
        except Exception as exc:  # Playwright 抛出的异常类型很多，统一收敛
            raise DriverError(f"打开页面失败: {exc}") from exc

    async def evaluate(self, script: str, arg: Any = None) -> Any:
        if self._page is None:
            raise DriverError("浏览器尚未启动")
        return await self._page.evaluate(script, arg)

    async def screenshot_clip(self, selector: Optional[str] = None) -> Optional[bytes]:
        """只截取商品区域，避免把整页个人信息拍进证据。"""
        if self._page is None:
            return None
        try:
            if selector:
                locator = self._page.locator(selector).first
                return await locator.screenshot()
            return await self._page.screenshot()
        except Exception:
            return None

    @property
    def current_url(self) -> str:
        return self._page.url if self._page is not None else ""

    def encode_image(self, raw: Optional[bytes]) -> Optional[str]:
        if not raw:
            return None
        return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")


@dataclass
class ScriptedStep:
    """脚本化驱动的一步：匹配 URL 子串 → 返回求值结果。"""

    url_contains: str
    results: Dict[str, Any] = field(default_factory=dict)


class ScriptedDriver:
    """测试驱动：按脚本返回结果，不起浏览器、不联网。"""

    def __init__(self, steps: List[ScriptedStep], goto_delay: float = 0.0):
        self.steps = steps
        self.current_url = ""
        self.goto_calls: List[str] = []
        self.evaluate_calls: List[str] = []
        self.started = False
        self.stopped = False
        self.goto_delay = goto_delay
        self._raise_on_goto: Optional[str] = None

    def raise_on_goto(self, url_contains: str) -> None:
        self._raise_on_goto = url_contains

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def goto(self, url: str, timeout_ms: int = 20000) -> bool:
        self.goto_calls.append(url)
        if self.goto_delay:
            await asyncio.sleep(self.goto_delay)
        if self._raise_on_goto and self._raise_on_goto in url:
            raise DriverError(f"模拟打开失败: {url}")
        self.current_url = url
        return True

    def _match(self) -> Optional[ScriptedStep]:
        for step in self.steps:
            if step.url_contains in self.current_url:
                return step
        return None

    async def evaluate(self, script: str, arg: Any = None) -> Any:
        self.evaluate_calls.append(script[:60])
        step = self._match()
        if step is None:
            return None
        key = self._script_key(script)
        return step.results.get(key)

    @staticmethod
    def _script_key(script: str) -> str:
        head = script.strip()[:24]
        if "loginname" in script or "hasLoginEntry" in script:
            return "login"
        if "captcha" in script.lower():
            return "blocked"
        if "looksLikeItem" in script:
            return "links"
        if "jsonld" in script:
            return "fields"
        return head

    async def screenshot_clip(self, selector: Optional[str] = None) -> Optional[bytes]:
        return None


async def run_with_timeout(coro, seconds: float):
    return await asyncio.wait_for(coro, timeout=seconds)
