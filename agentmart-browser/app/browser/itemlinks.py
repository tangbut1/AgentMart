"""商品链接/分享口令的识别与归一化。

这是「单品跨平台对决」模式的入口。用户真实场景是：在京东看中一款
索尼 WH-1000XM5，想知道淘宝/拼多多同款多少钱 —— 他手里有的是**商品
详情页链接**，不是一个搜索词。

为什么值得单独做一条管道：商品详情页为了 SEO 和外部引流，基本是公开
开放的，静态数据多、JSON-LD 完备；而搜索列表页是平台流量变现和商家竞价
的核心，反爬盾最厚。绕过搜索页，`JS_PRODUCT_FIELDS` 才能吃到真实数据。

这里只做**确定性的字符串解析**：能认出平台就认，认不出就如实返回 unknown，
绝不猜测链接指向哪个平台。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlsplit, urlunsplit

from ..domain.enums import Platform

# 各平台域名片段 → 平台。顺序无关紧要，匹配是互斥的。
_DOMAIN_HINTS: Tuple[Tuple[str, Platform], ...] = (
    ("jd.com", Platform.JD),
    ("3.cn", Platform.JD),            # 京东短链
    ("taobao.com", Platform.TAOBAO),
    ("tmall.com", Platform.TMALL),
    ("pinduoduo.com", Platform.PDD),
    ("yangkeduo.com", Platform.PDD),  # 拼多多旧域名
    ("jinritemai.com", Platform.DOUYIN),
    ("douyin.com", Platform.DOUYIN),
    ("haohuo.jinritemai.com", Platform.DOUYIN),
    # 淘宝/天猫的短链服务。m.tb.cn 本身不含平台字样，但它是淘宝官方
    # 短链，打开后 302 到 item.taobao.com 或 detail.tmall.com。
    # 用户从「分享 → 复制链接」拿到的常常就是它，不认就整条口令都废了。
    ("m.tb.cn", Platform.TAOBAO),
    ("e.tb.cn", Platform.TAOBAO),
)

# 淘口令/分享文本里嵌的链接。淘口令本身形如 ¥AbC123¥ + 描述文字，
# 真正能打开的是后面跟着的 m.tb.cn 短链。
_URL_RE = re.compile(r"https?://[^\s\"'<>`）)】\]，,。;；]+", re.IGNORECASE)
# 淘口令的token：两个 ¥ 之间的一段。没有链接时只能靠它，而它无法在服务端解析。
_TOKEN_RE = re.compile(r"[¥$￥]\s*([A-Za-z0-9]{6,})\s*[¥$￥]")

# 明显不是商品页的链接：活动页、首页、登录页。收进来也抽不到商品，
# 不如当场告诉用户。
_HOME_HOSTS = (
    r"jd\.com", r"taobao\.com", r"tmall\.com", r"pinduoduo\.com",
    r"yangkeduo\.com", r"jinritemai\.com", r"douyin\.com",
)
# 只有 host、没有路径的（detail.tmall.com 这种）
_BARE_HOST_RE = re.compile(
    r"^https?://(?:[a-z0-9-]+\.)*(?:" + "|".join(_HOME_HOSTS) + r")/?$", re.I
)
# 账号/交易相关的路径，都不是商品详情页
_NON_ITEM_PATH_RE = re.compile(
    r"/(?:login|member|cart|order|trade|buyer|mytaobao|settle|pay|confirm"
    r"|list_bought|address|refund)",
    re.I,
)


@dataclass
class LinkParse:
    """一条用户输入解析后的结果。"""

    raw: str
    url: str = ""
    platform: Optional[Platform] = None
    # 认不出平台 / 不是商品页时给出人能看懂的原因
    problem: Optional[str] = None
    # 输入里只有淘口令 token、没有可打开链接时为 True
    token_only: bool = False

    @property
    def ok(self) -> bool:
        return bool(self.url) and self.platform is not None and not self.problem


def platform_for_url(url: str) -> Optional[Platform]:
    """按域名判断链接属于哪个平台；认不出返回 None。"""
    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:
        return None
    if not host:
        return None
    # 先匹配更具体的（haohuo.jinritemai.com 含 jinritemai.com）
    for hint, platform in sorted(
        _DOMAIN_HINTS, key=lambda item: len(item[0]), reverse=True
    ):
        if host == hint or host.endswith("." + hint):
            return platform
    return None


def normalize_url(url: str) -> str:
    """去掉跟踪参数和 fragment，让同一商品的不同分享链接归一到一条。

    只保留路径和 query 里与商品标识相关的部分。做得保守：认不出的参数就
    留着，避免把真正必要的参数删掉导致页面打不开。
    """
    url = url.strip()
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    query = parts.query
    if query:
        keep: List[str] = []
        for pair in query.split("&"):
            if not pair:
                continue
            key = pair.split("=", 1)[0].lower()
            # utm_*/spm/scm/share/scene 之类是推广跟踪参数，去掉不影响商品页
            if key.startswith(("utm_", "spm", "scm", "share", "scene", "from_")):
                continue
            keep.append(pair)
        query = "&".join(keep)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))


def _looks_like_item_page(url: str) -> Optional[str]:
    if _BARE_HOST_RE.match(url) or _NON_ITEM_PATH_RE.search(url):
        return "这个链接看起来不是商品详情页（是首页/登录页/购物车一类）"
    return None


def _token_only_problem(text: str) -> LinkParse:
    return LinkParse(
        raw=text,
        token_only=True,
        problem=(
            "只识别到淘口令口令码，没有可打开的链接。"
            "请在商品页点「分享 → 复制链接」，把 http(s) 链接一起贴进来。"
        ),
    )


def parse_user_input(raw: str) -> List[LinkParse]:
    """解析用户粘贴的一段文本，抽出其中所有可用的商品链接。

    用户可能粘进来：
    - 一条裸链接：``https://item.jd.com/100012043978.html``
    - 一整段淘口令：``¥AbC123¥ 【索尼 WH-1000XM5】... https://m.tb.cn/h.abc123 ...``
    - 多条链接混在一段文字里

    认不出的部分不会静默丢弃，而是带 problem 返回，让界面告诉用户。
    """
    text = (raw or "").strip()
    if not text:
        return []

    results: List[LinkParse] = []
    seen: set[str] = set()
    url_spans: List[Tuple[int, int]] = []

    for match in _URL_RE.finditer(text):
        candidate = match.group(0).rstrip(".,;，。；")
        url = normalize_url(candidate)
        url_spans.append((match.start(), match.end()))
        if url in seen:
            continue
        seen.add(url)
        platform = platform_for_url(url)
        problem = _looks_like_item_page(url)
        if platform is None and problem is None:
            problem = "认不出这个链接属于哪个平台（只支持京东/淘宝/天猫/拼多多/抖音）"
        results.append(
            LinkParse(raw=text, url=url, platform=platform, problem=problem)
        )

    if results:
        # 有链接也再扫一遍口令码：用户常把两条商品的分享文本一起贴进来，
        # 其中一条只有口令码。不报出来的话，用户以为两条都比了，实际只有一条。
        # 但口令码后面跟着链接的，是同一段分享文本里的正常形态，不能误报。
        for token in _TOKEN_RE.finditer(text):
            if any(start >= token.start() for start, _ in url_spans):
                continue
            results.append(_token_only_problem(text))
        return results

    # 一条链接都没有：看看是不是只有淘口令 token
    if _TOKEN_RE.search(text):
        return [_token_only_problem(text)]
    return [
        LinkParse(raw=text, problem="没有在这段文字里找到 http(s) 链接")
    ]


def group_links_by_platform(
    parses: List[LinkParse],
) -> Dict[Platform, List[str]]:
    """把可用的链接按平台分组，供各平台管道直接打开。"""
    grouped: Dict[Platform, List[str]] = {}
    for item in parses:
        if not item.ok:
            continue
        grouped.setdefault(item.platform, []).append(item.url)
    return grouped


def summarize(parses: List[LinkParse]) -> dict:
    """给前端/接口用的汇总：认出了几条、各平台几条、有哪些问题。"""
    ok = [p for p in parses if p.ok]
    grouped = group_links_by_platform(ok)
    return {
        "total": len(parses),
        "usable": len(ok),
        "by_platform": {
            platform.value: len(urls) for platform, urls in grouped.items()
        },
        "problems": [p.problem for p in parses if p.problem],
        "links": [
            {"url": p.url, "platform": p.platform.value if p.platform else None}
            for p in ok
        ],
    }


__all__ = [
    "LinkParse",
    "parse_user_input",
    "platform_for_url",
    "normalize_url",
    "group_links_by_platform",
    "summarize",
]
