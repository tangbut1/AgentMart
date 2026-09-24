"""AgentMart 个人浏览器版 — 应用配置。

所有凭据只从环境变量 / .env 读取，源码里不放任何可用凭据。
本版本不接入任何电商开放接口，所以没有平台 AppKey 一类配置；
浏览器登录态与模型 Key 都存在 AGENTMART_HOME 下（见 browser/profiles.py）。
"""
from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # ---- App ----
    APP_ENV: str = "development"
    APP_HOST: str = "127.0.0.1"
    APP_PORT: int = 8000
    DEBUG: bool = True
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"

    # ---- Database ----
    DATABASE_URL: str = "sqlite+aiosqlite:///./agentmart.db"

    # ---- 个人浏览器版 ----
    # 浏览器登录态（profile 目录）与 model.json 的根目录。
    # 默认放在用户主目录，仓库外，.gitignore 也覆盖不到它。
    AGENTMART_HOME: str = ""
    # 模型调用上限：超出后该任务停止调用并说明原因，不会继续花钱
    AGENTMART_MODEL_MAX_CALLS: int = 40
    AGENTMART_MODEL_MAX_COST: float = 5.0

    @property
    def cors_origin_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def is_development(self) -> bool:
        return self.APP_ENV.lower() in ("development", "dev", "local", "test")


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
