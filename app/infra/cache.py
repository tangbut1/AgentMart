"""带 TTL 的内存缓存（可选 Redis 后端由同一接口扩展）。"""
from __future__ import annotations

import time
from typing import Any, Optional

from cachetools import TTLCache

from ..config import settings


class TTLCacheStore:
    def __init__(self, max_entries: Optional[int] = None, ttl: Optional[int] = None):
        self.ttl = ttl if ttl is not None else settings.CACHE_TTL_SECONDS
        self._cache: TTLCache = TTLCache(
            maxsize=max_entries or settings.CACHE_MAX_ENTRIES, ttl=self.ttl
        )
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Optional[Any]:
        value = self._cache.get(key)
        if value is None:
            self.misses += 1
            return None
        self.hits += 1
        return value

    def set(self, key: str, value: Any) -> None:
        self._cache[key] = value

    def stats(self) -> dict:
        return {
            "entries": len(self._cache),
            "hits": self.hits,
            "misses": self.misses,
            "ttl_seconds": self.ttl,
        }


cache = TTLCacheStore()
