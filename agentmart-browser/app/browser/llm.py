"""用户自带模型客户端（OpenAI 兼容接口）。

安全与诚实原则：
- API Key 只从本地配置文件或环境变量读取，**不进入前端产物、Git、
  普通日志或分享报告**；日志一律脱敏；
- 配置文件放在仓库之外的用户目录（``~/.agentmart/model.json``），
  权限尽量设为仅当前用户可读写，并提供删除入口；
- ``supports_vision`` 必须经过真实探测：给模型发一张图，失败就禁用视觉，
  绝不让不支持视觉的模型假装"看"了网页；
- 未配置 Key 时应用照常启动，界面可用，但任何 AI 相关按钮都明确说明
  "未配置模型"，不会把演示流程说成真实 AI 购物。
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from typing import List, Optional

import httpx
from loguru import logger

from .profiles import AGENTMART_HOME

MODEL_CONFIG_PATH = AGENTMART_HOME / "model.json"

# 日志脱敏：任何形如密钥的长串都替换为掩码
_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9_\-\.]{8,}"),
    re.compile(r"(?i)\b(api[_-]?key|token|secret|password)\s*[:=]\s*['\"]?[A-Za-z0-9_\-\.]{8,}"),
]


def redact(text: str) -> str:
    """把文本中的密钥样内容替换为掩码，用于日志与错误信息。"""
    if not text:
        return text
    out = text
    for pattern in _SECRET_PATTERNS:
        out = pattern.sub(lambda m: (m.group(1) + "***") if m.lastindex else "***", out)
    return out


@dataclass
class ModelConfig:
    """用户配置的模型服务。"""

    provider: str = "openai-compatible"
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    # 视觉能力：必须经探测确认，不允许用户或代码"假定"支持
    supports_vision: bool = False
    vision_verified_at: Optional[float] = None
    # 单次任务预算（用户自设）
    max_calls_per_task: int = 40
    max_cost_per_task: float = 0.0   # 0 = 不设费用上限
    # 每千 token 的估算单价（仅用于界面提示，不等于最终账单）
    est_input_price_per_1k: float = 0.0
    est_output_price_per_1k: float = 0.0
    timeout_seconds: float = 60.0
    note: str = ""

    def public_dict(self) -> dict:
        """给前端的视图：绝不包含 api_key。"""
        data = asdict(self)
        data.pop("api_key", None)
        data["api_key_configured"] = bool(self.api_key)
        data["config_path"] = str(MODEL_CONFIG_PATH)
        return data


@dataclass
class CallUsage:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    vision_calls: int = 0
    estimated_cost: float = 0.0
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class ModelError(RuntimeError):
    """模型调用失败。消息已脱敏。"""


class BudgetExceeded(RuntimeError):
    """达到用户设置的调用/费用上限。"""


def _write_config(config: ModelConfig) -> None:
    MODEL_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(asdict(config), ensure_ascii=False, indent=2)
    # 先写临时文件再替换，避免半截配置
    tmp = MODEL_CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(payload, encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass  # Windows 上 chmod 语义有限，尽力而为
    os.replace(tmp, MODEL_CONFIG_PATH)


def model_configured() -> bool:
    """本机是否配了可用的模型（有 Key 且有 base_url）。

    个人浏览器版的取数走确定性 DOM 规则，本来就不依赖模型；
    配了只是让它在规则失败时多一次兜底。所以"没配"是正常状态，
    不是错误 —— 界面要能据此把"模型调用 0 次"解释清楚。
    """
    config = load_config()
    return bool(config.api_key and config.base_url and config.model)


def load_config() -> ModelConfig:
    """读取本地模型配置；环境变量可覆盖（便于 CI/测试）。"""
    config = ModelConfig()
    if MODEL_CONFIG_PATH.is_file():
        try:
            data = json.loads(MODEL_CONFIG_PATH.read_text(encoding="utf-8"))
            known = {f for f in ModelConfig.__dataclass_fields__}
            config = ModelConfig(**{k: v for k, v in data.items() if k in known})
        except (json.JSONDecodeError, OSError, TypeError) as exc:
            logger.warning(f"模型配置文件读取失败，使用默认配置: {redact(str(exc))}")
    env_key = os.environ.get("AGENTMART_MODEL_API_KEY", "")
    if env_key:
        config.api_key = env_key
    if os.environ.get("AGENTMART_MODEL_BASE_URL"):
        config.base_url = os.environ["AGENTMART_MODEL_BASE_URL"]
    if os.environ.get("AGENTMART_MODEL_NAME"):
        config.model = os.environ["AGENTMART_MODEL_NAME"]
    return config


def save_config(config: ModelConfig) -> ModelConfig:
    if not config.base_url.startswith(("http://", "https://")):
        raise ModelError("base_url 必须以 http:// 或 https:// 开头")
    _write_config(config)
    return config


def delete_config() -> bool:
    """删除本地模型配置（含 API Key）。"""
    if MODEL_CONFIG_PATH.is_file():
        MODEL_CONFIG_PATH.unlink()
        return True
    return False


class ModelClient:
    """OpenAI 兼容的聊天/视觉客户端，带预算与脱敏。"""

    def __init__(self, config: Optional[ModelConfig] = None):
        self.config = config or load_config()
        self.usage = CallUsage()

    # ---- 可用性 ----
    @property
    def configured(self) -> bool:
        return bool(self.config.base_url and self.config.api_key and self.config.model)

    def reset_usage(self) -> None:
        self.usage = CallUsage()

    def _check_budget(self, is_vision: bool) -> None:
        if self.usage.calls >= self.config.max_calls_per_task:
            raise BudgetExceeded(
                f"已达单次任务调用上限（{self.config.max_calls_per_task} 次），已停止调用模型"
            )
        if (
            self.config.max_cost_per_task > 0
            and self.usage.estimated_cost >= self.config.max_cost_per_task
        ):
            raise BudgetExceeded(
                f"已达单次任务费用上限（¥{self.config.max_cost_per_task}），已停止调用模型"
            )
        if is_vision and not self.config.supports_vision:
            raise ModelError("当前模型未通过视觉能力探测，不能用于识别网页截图")

    def _account(self, response: dict, is_vision: bool) -> None:
        usage = response.get("usage") or {}
        prompt = int(usage.get("prompt_tokens") or 0)
        completion = int(usage.get("completion_tokens") or 0)
        self.usage.calls += 1
        self.usage.prompt_tokens += prompt
        self.usage.completion_tokens += completion
        if is_vision:
            self.usage.vision_calls += 1
        cost = (
            prompt / 1000 * self.config.est_input_price_per_1k
            + completion / 1000 * self.config.est_output_price_per_1k
        )
        self.usage.estimated_cost = round(self.usage.estimated_cost + cost, 6)

    async def _post(self, payload: dict, is_vision: bool) -> dict:
        self._check_budget(is_vision)
        if not self.configured:
            raise ModelError("尚未配置模型服务（base_url / api_key / model）")
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        try:
            async with httpx.AsyncClient(
                timeout=self.config.timeout_seconds, trust_env=False
            ) as client:
                response = await client.post(url, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise ModelError(f"模型请求失败: {redact(str(exc))}") from exc
        if response.status_code >= 400:
            # 不把响应体整体写进日志（可能回显请求内容），只记状态码
            raise ModelError(f"模型返回错误状态 {response.status_code}")
        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise ModelError("模型响应不是合法 JSON") from exc
        self._account(data, is_vision)
        return data

    # ---- 文本对话 ----
    async def chat(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.1,
        max_tokens: int = 1200,
    ) -> str:
        payload = {
            "model": self.config.model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        data = await self._post(payload, is_vision=False)
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelError("模型响应缺少 choices[0].message.content") from exc

    # ---- 视觉 ----
    async def vision(
        self,
        system: str,
        user: str,
        image_data_url: str,
        *,
        max_tokens: int = 800,
    ) -> str:
        payload = {
            "model": self.config.model,
            "temperature": 0,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user},
                        {"type": "image_url", "image_url": {"url": image_data_url}},
                    ],
                },
            ],
        }
        data = await self._post(payload, is_vision=True)
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelError("模型响应缺少 choices[0].message.content") from exc

    # ---- 连接与能力探测 ----
    async def test_connection(self) -> dict:
        """测试连通性；同时验证视觉能力。返回可展示的结论（不含密钥）。"""
        if not self.configured:
            return {
                "ok": False,
                "message": "尚未配置 base_url / api_key / model",
                "vision": False,
            }
        started = time.perf_counter()
        try:
            text = await self.chat(
                "你是连通性测试。只回复 OK 两个字符。",
                "ping",
                max_tokens=8,
            )
        except ModelError as exc:
            return {
                "ok": False,
                "message": str(exc),
                "vision": self.config.supports_vision,
            }
        elapsed = int((time.perf_counter() - started) * 1000)

        vision_ok = False
        vision_message = ""
        try:
            vision_ok = await self._probe_vision()
        except ModelError as exc:
            vision_message = str(exc)
        # 探测结果写回配置：只有真能识图的模型才允许用于看网页
        self.config.supports_vision = vision_ok
        self.config.vision_verified_at = time.time() if vision_ok else None
        try:
            _write_config(self.config)
        except OSError as exc:
            logger.warning(f"视觉探测结果写入失败: {redact(str(exc))}")

        return {
            "ok": True,
            "message": f"连接成功（{elapsed}ms），模型回复：{redact(text)[:40]}",
            "vision": vision_ok,
            "vision_message": vision_message
            or ("模型可识别图片" if vision_ok else "模型不支持图片输入，已禁用视觉能力"),
            "usage": self.usage.to_dict(),
        }

    async def _probe_vision(self) -> bool:
        """发一张 1x1 PNG 让模型描述颜色，据实判断是否支持视觉。"""
        # 1x1 透明 PNG
        pixel = (
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8"
            "AAAAB/AAB/xx4pPAAAAABJRU5ErkJggg=="
        )
        reply = await self.vision(
            "你是视觉能力探针。只回答一个词：yes 或 no。",
            "这张图是什么颜色？如果能看见图片回答 yes，看不见回答 no。",
            f"data:image/png;base64,{pixel}",
            max_tokens=8,
        )
        normalized = (reply or "").strip().lower()
        if "yes" in normalized:
            return True
        if "no" in normalized:
            return False
        # 语义不明时保守视为不支持
        return False
