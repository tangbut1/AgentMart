"""每来源令牌桶限流，防止适配器打爆平台接口。"""
from __future__ import annotations

import time
from threading import Lock
from typing import Dict


class TokenBucket:
    def __init__(self, rate_per_sec: float, burst: int = 1):
        self.rate = rate_per_sec
        self.capacity = float(burst)
        self.tokens = float(burst)
        self.updated = time.monotonic()
        self.lock = Lock()

    def allow(self) -> bool:
        with self.lock:
            now = time.monotonic()
            self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
            self.updated = now
            if self.tokens >= 1.0:
                self.tokens -= 1.0
                return True
            return False

    def wait_time(self) -> float:
        with self.lock:
            if self.tokens >= 1.0:
                return 0.0
            return (1.0 - self.tokens) / self.rate


class RateLimiter:
    def __init__(self):
        self._buckets: Dict[str, TokenBucket] = {}

    def bucket(self, name: str, rate_per_sec: float = 1.0, burst: int = 1) -> TokenBucket:
        if name not in self._buckets:
            self._buckets[name] = TokenBucket(rate_per_sec, burst)
        return self._buckets[name]

    def allow(self, name: str, rate_per_sec: float = 1.0, burst: int = 1) -> bool:
        return self.bucket(name, rate_per_sec, burst).allow()


rate_limiter = RateLimiter()
