"""平台适配器统一接口。

每个平台一个 Adapter，职责：
- 声明所需凭据（只从 settings / 环境变量读取，源码中不出现真实值）；
- 未配置凭据时返回 NOT_CONNECTED，并给出接入指引 —— 绝不返回假数据；
- 已配置时调用平台开放 API，完成限流、重试、缓存与日志；
- 把平台响应解析为统一的 Offer / Discount / Policy 模型。
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional

from ..config import settings
from ..domain.enums import ConnectionStatus, DataStatus, Platform
from ..domain.models import Offer


@dataclass
class AdapterResult:
    platform: Platform
    status: ConnectionStatus
    offers: List[Offer] = field(default_factory=list)
    error: Optional[str] = None
    message: str = ""
    elapsed_ms: int = 0


@dataclass
class AdapterStatusInfo:
    """给前端展示的接入状态（不含任何敏感信息）。"""

    platform: Platform
    adapter: str
    status: ConnectionStatus
    message: str
    docs_url: str = ""
    required_env: List[str] = field(default_factory=list)
    data_freshness: str = ""


class PlatformAdapter(ABC):
    platform: Platform
    adapter_name: str
    display_name: str
    docs_url: str = ""
    required_env: List[str] = []

    # ---- 凭据检查 ----
    def _credential_map(self) -> dict:
        return {name: bool(getattr(settings, name, "")) for name in self.required_env}

    @property
    def is_configured(self) -> bool:
        return all(self._credential_map().values())

    def missing_credentials(self) -> List[str]:
        return [name for name, ok in self._credential_map().items() if not ok]

    def not_connected_message(self) -> str:
        missing = "、".join(self.missing_credentials())
        return (
            f"未接入：需要配置环境变量 {missing} 才能获取 {self.display_name} 真实数据。"
            f"申请指引见 {self.docs_url or 'README'}。"
        )

    def status_info(self, status: Optional[ConnectionStatus] = None) -> AdapterStatusInfo:
        if status is None:
            status = (
                ConnectionStatus.CONNECTED if self.is_configured
                else ConnectionStatus.NOT_CONNECTED
            )
        message = (
            "已配置凭据，可请求真实数据" if status == ConnectionStatus.CONNECTED
            else self.not_connected_message()
        )
        return AdapterStatusInfo(
            platform=self.platform,
            adapter=self.adapter_name,
            status=status,
            message=message,
            docs_url=self.docs_url,
            required_env=list(self.required_env),
        )

    # ---- 主入口 ----
    async def search(self, keyword: str, **kwargs) -> AdapterResult:
        start = time.monotonic()
        if not self.is_configured:
            return AdapterResult(
                platform=self.platform,
                status=ConnectionStatus.NOT_CONNECTED,
                message=self.not_connected_message(),
                elapsed_ms=int((time.monotonic() - start) * 1000),
            )
        try:
            offers = await self._search(keyword, **kwargs)
            for offer in offers:
                offer.data_status = DataStatus.REAL
                offer.source = self.adapter_name
            return AdapterResult(
                platform=self.platform,
                status=ConnectionStatus.CONNECTED,
                offers=offers,
                message=f"返回 {len(offers)} 条 {self.display_name} 真实数据",
                elapsed_ms=int((time.monotonic() - start) * 1000),
            )
        except Exception as exc:  # 适配器内部错误不应拖垮整个搜索
            return AdapterResult(
                platform=self.platform,
                status=ConnectionStatus.ERROR,
                error=str(exc),
                message=f"{self.display_name} 数据请求失败：{exc}",
                elapsed_ms=int((time.monotonic() - start) * 1000),
            )

    @abstractmethod
    async def _search(self, keyword: str, **kwargs) -> List[Offer]:
        """调用平台 API 并解析为 Offer 列表。"""
