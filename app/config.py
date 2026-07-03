from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import List
import json


class Settings(BaseSettings):
    # App
    APP_ENV: str = "development"
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    DEBUG: bool = True
    SECRET_KEY: str = "change-me-in-production"

    # Database
    DATABASE_URL: str = "postgresql://agentmart:password@localhost:5432/agentmart"
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_CACHE_TTL: int = 3600

    # JD
    JD_APP_KEY: str = ""
    JD_APP_SECRET: str = ""
    JD_ACCESS_TOKEN: str = ""
    JD_API_BASE_URL: str = "https://api.jd.com/routerjson"

    # Taobao / Tmall
    TAOBAO_APP_KEY: str = ""
    TAOBAO_APP_SECRET: str = ""
    TAOBAO_ACCESS_TOKEN: str = ""
    TAOBAO_API_BASE_URL: str = "https://eco.taobao.com/router/rest"

    # Bilibili
    BILIBILI_SESSDATA: str = ""
    BILIBILI_BILI_JCT: str = ""
    BILIBILI_BUVID3: str = ""
    BILIBILI_DEDEUSERID: str = ""

    # Douyin
    DOUYIN_CLIENT_KEY: str = ""
    DOUYIN_CLIENT_SECRET: str = ""
    DOUYIN_ACCESS_TOKEN: str = ""

    # LLM
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    OPENAI_MODEL: str = "gpt-4o"
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com/v1"
    DEEPSEEK_MODEL: str = "deepseek-chat"
    CLAUDE_API_KEY: str = ""
    CLAUDE_MODEL: str = "claude-3-5-sonnet-20241022"

    # Whisper
    WHISPER_MODEL: str = "base"
    WHISPER_DEVICE: str = "cpu"

    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # CORS
    CORS_ORIGINS: str = '["http://localhost:3000","http://localhost:5173","http://127.0.0.1:5500"]'

    def get_cors_origins(self) -> List[str]:
        try:
            return json.loads(self.CORS_ORIGINS)
        except Exception:
            return ["*"]

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
