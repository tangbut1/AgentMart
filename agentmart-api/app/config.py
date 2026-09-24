"""AgentMart 官方 API 架构版 — 应用配置。

所有凭据只从环境变量 / .env 读取，源码里不放任何可用凭据。
每个平台凭据都是可选的：没配就在界面上显示「未接入」，
不会用演示数据冒充真实报价。
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

    # ---- Cache ----
    CACHE_TTL_SECONDS: int = 900
    CACHE_MAX_ENTRIES: int = 2000

    # ---- Outbound HTTP ----
    HTTP_TIMEOUT_SECONDS: float = 12.0
    HTTP_MAX_RETRIES: int = 2

    # ---- JD ----
    JD_APP_KEY: str = ""
    JD_APP_SECRET: str = ""
    JD_ACCESS_TOKEN: str = ""
    JD_API_BASE_URL: str = "https://api.jd.com/routerjson"

    # ---- Taobao / Tmall ----
    TAOBAO_APP_KEY: str = ""
    TAOBAO_APP_SECRET: str = ""
    TAOBAO_ACCESS_TOKEN: str = ""
    TAOBAO_API_BASE_URL: str = "https://eco.taobao.com/router/rest"

    # ---- Pinduoduo ----
    PDD_CLIENT_ID: str = ""
    PDD_CLIENT_SECRET: str = ""
    PDD_API_BASE_URL: str = "https://gw-api.pinduoduo.com/api/router"

    # ---- Douyin ----
    DOUYIN_CLIENT_KEY: str = ""
    DOUYIN_CLIENT_SECRET: str = ""
    DOUYIN_ACCESS_TOKEN: str = ""
    DOUYIN_API_BASE_URL: str = "https://open.douyin.com"
    # 商品搜索接口路径：在开放平台控制台「已授权接口」中查找后填写，
    # 例如 /goodlife/v1/goods/search（团购）或电商应用对应的商品查询路径。
    DOUYIN_GOODS_SEARCH_PATH: str = ""
    # 价格单位：yuan=接口返回元（默认，不做任何换算）/ cent=接口返回分。
    # 不按金额大小猜测单位——猜错会让真实售价 >=1000 元的商品价格错 100 倍。
    DOUYIN_PRICE_UNIT: str = "yuan"

    # ---- Bilibili ----
    BILIBILI_SESSDATA: str = ""

    # ---- LLM (optional) ----
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "https://api.deepseek.com/v1"
    LLM_MODEL: str = "deepseek-chat"

    # ---- Curation ----
    CURATION_ADMIN_TOKEN: str = ""

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
