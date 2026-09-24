"""B 站评测元数据解析（使用官方公开 web 接口）。

- view 接口（x/web-interface/view）无需登录即可获取视频公开信息：
  标题、UP 主、发布时间、时长、封面、播放/点赞等统计数据；
- 搜索接口带风控，需要登录态 Cookie；不配置 BILIBILI_SESSDATA 时
  本模块只提供「链接解析」，不提供关键词搜索，也不绕过风控。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from loguru import logger

from ..domain.enums import ReviewPlatform
from ..domain.models import Review
from ..infra.http_client import DEFAULT_UA, SafeHttpClient

BILIBILI_API = "https://api.bilibili.com"
# 注意：不要发送 Referer 头 —— 实测会触发 B 站接口风控（412）。
# 仅使用公开接口获取视频公开元数据，不携带任何登录态（除非用户显式配置 SESSDATA）。
_BILIBILI_HEADERS = {"User-Agent": DEFAULT_UA}

_BV_RE = re.compile(r"(BV[0-9A-Za-z]{10})")
_AV_RE = re.compile(r"(?:av|aid=)(\d{2,})", re.IGNORECASE)


@dataclass
class ResolvedVideo:
    ok: bool
    review: Optional[Review] = None
    error: Optional[str] = None


def extract_bvid(url: str) -> Optional[str]:
    match = _BV_RE.search(url or "")
    return match.group(1) if match else None


def extract_aid(url: str) -> Optional[str]:
    match = _AV_RE.search(url or "")
    return match.group(1) if match else None


def is_bilibili_url(url: str) -> bool:
    return bool(re.search(r"(bilibili\.com|b23\.tv)", url or "", re.IGNORECASE))


async def resolve_video(url: str) -> ResolvedVideo:
    """把用户提交的 B 站链接解析为真实元数据（不抓取视频内容本身）。"""
    if not is_bilibili_url(url):
        return ResolvedVideo(ok=False, error="不是有效的哔哩哔哩链接")
    try:
        async with SafeHttpClient() as http:
            bvid = extract_bvid(url)
            if bvid:
                data = await http.get_json(
                    f"{BILIBILI_API}/x/web-interface/view",
                    params={"bvid": bvid},
                    headers=_BILIBILI_HEADERS,
                )
            else:
                aid = extract_aid(url)
                if not aid:
                    return ResolvedVideo(ok=False, error="链接中未找到 BV 号或 av 号")
                data = await http.get_json(
                    f"{BILIBILI_API}/x/web-interface/view",
                    params={"aid": aid},
                    headers=_BILIBILI_HEADERS,
                )
    except Exception as exc:
        logger.warning(f"[bilibili] resolve failed: {exc}")
        return ResolvedVideo(ok=False, error=f"解析失败：{exc}")

    if data.get("code") != 0:
        return ResolvedVideo(ok=False, error=f"B站接口返回错误：{data.get('message')}")

    info = data.get("data") or {}
    owner = info.get("owner") or {}
    stat = info.get("stat") or {}
    pubdate = info.get("pubdate")
    review = Review(
        platform=ReviewPlatform.BILIBILI,
        external_id=info.get("bvid") or str(info.get("aid", "")),
        url=f"https://www.bilibili.com/video/{info.get('bvid') or 'av' + str(info.get('aid', ''))}",
        title=info.get("title", ""),
        creator_name=owner.get("name", "未知 UP 主"),
        creator_id=str(owner.get("mid", "")) or None,
        creator_url=(
            f"https://space.bilibili.com/{owner['mid']}" if owner.get("mid") else None
        ),
        cover_url=info.get("pic"),
        published_at=datetime.fromtimestamp(pubdate) if pubdate else None,
        duration_seconds=info.get("duration"),
        view_count=stat.get("view"),
        like_count=stat.get("like"),
        data_status="real",
        fetched_at=datetime.now(),
        related_models=[],
    )
    return ResolvedVideo(ok=True, review=review)


async def search_videos(keyword: str, page: int = 1) -> ResolvedVideo:
    """关键词搜索视频。需要 BILIBILI_SESSDATA（登录态 Cookie）。

    未配置时明确返回不可用，不尝试绕过风控。
    """
    from ..config import settings

    if not settings.BILIBILI_SESSDATA:
        return ResolvedVideo(
            ok=False,
            error="未配置 BILIBILI_SESSDATA，无法使用视频搜索；请改用「提交评测链接」流程",
        )
    try:
        async with SafeHttpClient() as http:
            data = await http.get_json(
                f"{BILIBILI_API}/x/web-interface/search/type",
                params={"search_type": "video", "keyword": keyword, "page": page},
                headers={**_BILIBILI_HEADERS, "Cookie": f"SESSDATA={settings.BILIBILI_SESSDATA}"},
            )
    except Exception as exc:
        return ResolvedVideo(ok=False, error=f"搜索失败：{exc}")
    # 解析逻辑与 resolve 类似；搜索结果为列表，此处仅返回错误/成功标记，
    # 由上层决定如何展示。保持简单：调用方通过 resolve 逐个补全元数据。
    if data.get("code") != 0:
        return ResolvedVideo(ok=False, error=f"B站搜索返回错误：{data.get('message')}")
    return ResolvedVideo(ok=True)
