"""SKU 级规格同步：让「价格」始终对应「同一个规格」。

很多平台把颜色、尺码只放在规格选择器里，标题里不写。标题相同的两件商品，
一个选的是黑色 L、一个是蓝色 M，标题签名完全一致 —— 不处理的话它们会被
合成一组、并排比价，把 200 元的规格差价算成平台差异，用户会以为
「另一平台同款便宜 200」，买回来发现不是自己要的那个规格。

所以规格文本（sku_text）要和标题一样参与签名比对：尺码、容量、版本、成色
是硬冲突，颜色是软差异（同款不同色可以并排，但要写明颜色不同）。

颜色词必须归一：京东写「曜石黑」、淘宝写「黑色」、拼多多写「黑」，
不归一就永远是「颜色不同」，同款反而被拆开。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Set

from .matching import (
    CONDITION_PATTERNS,
    VERSION_PATTERNS,
    _normalize_storage,
    _STORAGE_RE,
    _STORAGE_UNIT,
    _is_plausible_storage,
)

# ─── 颜色归一 ──────────────────────────────────────────────────

# 同一种颜色的各种写法。键是归一后的颜色，值是该颜色的所有别称。
# 顺序无关，但每个别称只应出现在一个键下 —— 测试会守住这一点。
COLOR_SYNONYMS: dict = {
    "黑": [
        "曜石黑", "星空黑", "暗夜黑", "深空黑", "磨砂黑", "亮黑色", "纯黑色",
        "钛黑色", "幻夜黑", "极夜黑", "墨黑", "碳素黑", "黑色", "黑",
    ],
    "白": ["月光白", "珍珠白", "云白色", "陶瓷白", "乳白色", "纯白色", "白色", "白"],
    "灰": ["深空灰", "太空灰", "钛灰色", "烟灰色", "高级灰", "灰色", "灰"],
    "银": ["银色", "银河银", "冰河银", "银"],
    "金": ["钛金色", "香槟金", "沙金色", "流沙金", "金色", "金"],
    "蓝": ["海蓝色", "天蓝色", "远峰蓝", "湖光蓝", "宝石蓝", "深蓝色", "蓝色", "蓝"],
    "绿": ["苍岭绿", "翡翠绿", "松林绿", "墨绿色", "绿色", "绿"],
    "粉": ["樱花粉", "蜜桃粉", "玫瑰粉", "粉色", "粉"],
    "紫": ["淡紫色", "暗紫色", "紫色", "紫"],
    "橙": ["橘色", "橙色", "落日橙", "橙"],
    "黄": ["柠檬黄", "明黄色", "黄色", "黄"],
    "红": ["珊瑚色", "中国红", "酒红色", "红色", "红"],
}

_COLOR_BY_ALIAS = {
    alias: canonical
    for canonical, aliases in COLOR_SYNONYMS.items()
    for alias in aliases
}
# 长别名优先：先匹配「曜石黑」再匹配「黑」，否则「曜石黑」会被切成「曜石」+「黑」
_COLOR_ALIASES_BY_LEN: List[str] = sorted(_COLOR_BY_ALIAS, key=len, reverse=True)

# 英文颜色（规格里常和中文混写，如 "Black / 黑"）
_COLOR_EN: dict = {
    "black": "黑", "white": "白", "gray": "灰", "grey": "灰", "silver": "银",
    "gold": "金", "blue": "蓝", "green": "绿", "pink": "粉", "purple": "紫",
    "red": "红", "orange": "橙", "yellow": "黄",
}

# ─── 尺码归一 ──────────────────────────────────────────────────

# 字母尺码：S/M/L/XL/XXL/XXXL，可带「码」「号」后缀。
# 两侧都要求不是字母数字 —— 这样 "5G"、"S24"、"M330"、"1.5L" 都不会被
# 误当成尺码（与 app/domain/matching.py 的 _SIZE_RE 同一套边界约定）。
_ALPHA_SIZE_RE = re.compile(
    r"(?<![A-Za-z0-9])(?P<alpha>X{0,3}S|X{0,3}M|X{0,3}L)(?![A-Za-z0-9])", re.IGNORECASE
)
# 数字尺码：42码 / 42 码 / 尺码42
_NUM_SIZE_RE = re.compile(r"(?<!\d)(?P<num>\d{2,3})\s*(?:码|号)")
# 号型：175/96A
_EU_SIZE_RE = re.compile(r"(?<!\d)(?P<eu>\d{3}/\d{2,3}[A-D])")
# 尺码后面跟这些词时是营销词不是尺码：「S级音质」「M系列」
_SIZE_MARKETING_RE = re.compile(r"^[级系列款版]")


def _normalize_alpha_size(value: str) -> str:
    """XL/xxl/XXL → XL，M/m → M。统一大写，去掉「码」。"""
    return value.strip().upper().rstrip("码号")


def _find_color(text: str) -> Optional[str]:
    for alias in _COLOR_ALIASES_BY_LEN:
        if re.search(r"(?<![A-Za-z])" + re.escape(alias) + r"(?![A-Za-z])", text, re.IGNORECASE):
            return _COLOR_BY_ALIAS[alias]
    lowered = text.lower()
    for word, canonical in _COLOR_EN.items():
        if re.search(r"(?<![A-Za-z])" + word + r"(?![A-Za-z])", lowered):
            return canonical
    return None


def _find_sizes(text: str) -> Set[str]:
    """规格文本里的尺码集合。"""
    found: Set[str] = set()
    for match in _ALPHA_SIZE_RE.finditer(text):
        # 「S级」「M系列」是营销词不是尺码
        if _SIZE_MARKETING_RE.match(text[match.end():]):
            continue
        found.add(_normalize_alpha_size(match.group("alpha")))
    for match in _NUM_SIZE_RE.finditer(text):
        found.add(match.group("num"))
    for match in _EU_SIZE_RE.finditer(text):
        found.add(match.group("eu"))
    return found


def _find_storage(text: str) -> Optional[str]:
    """容量。取最大值：'12GB+256GB' 里 12GB 是内存，256GB 才是存储。"""
    values: List[str] = []
    for num, unit in _STORAGE_RE.findall(text):
        if not _is_plausible_storage(num, unit):
            continue
        values.append(_normalize_storage(num, _STORAGE_UNIT[unit.upper()]))

    def size_key(value: str) -> int:
        num, unit = value[:-2], value[-2:].upper()
        return int(num) * (1024 if unit == "TB" else 1)

    return max(values, key=size_key) if values else None


@dataclass
class SkuSpec:
    """一件商品在某个平台上被选中的那个规格。"""

    raw: str = ""
    color: Optional[str] = None
    sizes: Set[str] = field(default_factory=set)
    storage: Optional[str] = None
    version: Optional[str] = None      # cn/hk/us/jp/eu/oversea/None
    condition: Optional[str] = None    # new/used/refurbished/None
    bundle: bool = False

    @property
    def size(self) -> Optional[str]:
        """主尺码：多个尺码时取字典序最小的，保证同一输入永远得到同一输出。"""
        return min(self.sizes) if self.sizes else None

    @property
    def is_empty(self) -> bool:
        return not (self.color or self.sizes or self.storage or self.version
                    or self.condition or self.bundle)

    def describe(self) -> str:
        """给界面用的一句话规格描述。空规格返回空串。"""
        if self.is_empty:
            return ""
        parts: List[str] = []
        if self.color:
            parts.append(self.color + "色")
        if self.size:
            parts.append(self.size + ("码" if self.size.isdigit() else ""))
        if self.storage:
            parts.append(self.storage)
        if self.version:
            parts.append({"cn": "国行", "hk": "港版", "us": "美版", "jp": "日版",
                          "eu": "欧版", "oversea": "海外版"}.get(self.version, self.version))
        if self.condition:
            parts.append({"new": "全新", "used": "二手",
                          "refurbished": "翻新"}.get(self.condition, self.condition))
        if self.bundle:
            parts.append("套装")
        return " ".join(parts)


def parse_sku(text: Optional[str]) -> SkuSpec:
    """从规格文本里解析出归一化规格。认不出来的字段留 None，不猜。"""
    raw = (text or "").strip()
    if not raw:
        return SkuSpec()

    spec = SkuSpec(raw=raw)
    spec.color = _find_color(raw)
    spec.sizes = _find_sizes(raw)
    spec.storage = _find_storage(raw)

    for pattern, version in VERSION_PATTERNS:
        if re.search(pattern, raw, re.IGNORECASE):
            spec.version = version
            break

    for pattern, condition in CONDITION_PATTERNS:
        if re.search(pattern, raw, re.IGNORECASE):
            spec.condition = condition
            break

    if re.search(r"套装|礼盒|套餐|含.{0,6}(配件|保护套|键盘|鼠标|充电器)", raw, re.IGNORECASE):
        spec.bundle = True

    return spec


def hard_sku_conflict(a: SkuSpec, b: SkuSpec) -> Optional[str]:
    """规格层面的硬冲突。None 表示没有硬冲突。

    尺码/容量/版本/成色/套装不同就是不同 SKU，价格不可比；
    颜色不同不构成冲突（同款不同色可以并排，但界面要写明颜色不同）。
    """
    if a.sizes and b.sizes and a.sizes != b.sizes:
        return f"尺码不同（{'/'.join(sorted(a.sizes))} / {'/'.join(sorted(b.sizes))}）"
    if a.storage and b.storage and a.storage != b.storage:
        return f"容量不同（{a.storage} / {b.storage}）"
    if a.version and b.version and a.version != b.version:
        return f"版本不同（{a.version} / {b.version}）"
    if a.condition and b.condition and a.condition != b.condition:
        return f"成色不同（{a.condition} / {b.condition}）"
    if a.bundle != b.bundle:
        return "套装与单品混在一起"
    return None


def sku_relation(a: SkuSpec, b: SkuSpec) -> str:
    """两个规格之间的关系：matched / variant / unknown。

    matched  —— 同一 SKU，价格可以直接比
    variant   —— 同款但规格不同，价格差里含规格差异，不能直接比
    unknown   —— 至少一侧读不到规格，无法确认
    """
    if a.is_empty or b.is_empty:
        return "unknown"
    if hard_sku_conflict(a, b):
        return "variant"
    if a.color and b.color and a.color != b.color:
        return "variant"
    return "matched"


def sku_sync_note(spec: Optional[SkuSpec], relation: str) -> str:
    """给界面的一句话说明。"""
    if relation == "unknown" or spec is None:
        return "未读到规格，无法确认是不是同一个 SKU，价格请以两边商品页为准"
    if relation == "matched":
        described = spec.describe()
        return f"规格一致（{described}），价格可直接比较" if described else "规格一致，价格可直接比较"
    return ""
