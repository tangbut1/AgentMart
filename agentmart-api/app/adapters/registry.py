"""适配器注册表：统一管理平台适配器与接入状态。"""
from __future__ import annotations

from typing import Dict, List

from ..domain.enums import ConnectionStatus, Platform
from .base import AdapterStatusInfo, PlatformAdapter
from .douyin import DouyinAdapter
from .jd import JDAdapter
from .pdd import PddAdapter
from .taobao import TmallAdapter, TaobaoAdapter

_adapters: List[PlatformAdapter] = [
    JDAdapter(),
    TaobaoAdapter(),
    TmallAdapter(),
    PddAdapter(),
    DouyinAdapter(),
]

_by_platform: Dict[Platform, PlatformAdapter] = {a.platform: a for a in _adapters}


def get_adapter(platform: Platform) -> PlatformAdapter:
    return _by_platform[platform]


def all_adapters() -> List[PlatformAdapter]:
    return list(_adapters)


def platform_statuses(last_errors: Dict[Platform, str] | None = None) -> List[AdapterStatusInfo]:
    last_errors = last_errors or {}
    infos: List[AdapterStatusInfo] = []
    for adapter in _adapters:
        status = (
            ConnectionStatus.CONNECTED if adapter.is_configured
            else ConnectionStatus.NOT_CONNECTED
        )
        info = adapter.status_info(status)
        if adapter.platform in last_errors:
            info.status = ConnectionStatus.ERROR
            info.message = last_errors[adapter.platform]
        infos.append(info)
    return infos
