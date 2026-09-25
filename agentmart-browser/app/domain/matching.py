"""规格解析与跨平台商品匹配。

匹配的第一原则是「不错配」：容量、版本（国行/海外）、成色（全新/二手）、
套装等硬性规格不同时绝不合组；颜色等软性差异允许合组但给出提示。
匹配不确定时产出 warning，由界面提示用户确认，而不是强行合并。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List, Optional, Set, Tuple

from .models import Offer

# ─── 词库 ──────────────────────────────────────────────────────

KNOWN_BRANDS = [
    "Apple", "苹果", "华为", "HUAWEI", "小米", "Xiaomi", "Redmi", "红米",
    "OPPO", "vivo", "iQOO", "一加", "OnePlus", "荣耀", "HONOR", "三星",
    "Samsung", "索尼", "SONY", "联想", "Lenovo", "ThinkPad", "华硕", "ASUS",
    "戴尔", "Dell", "惠普", "HP", "罗技", "Logitech", "雷蛇", "Razer",
    "漫步者", "Edifier", "Bose", "JBL", "森海塞尔", "Sennheiser", "任天堂",
    "Nintendo", "微软", "Microsoft", "松下", "Panasonic", "飞利浦", "PHILIPS",
    "海尔", "美的", "格力", "西门子", "SIEMENS", "博世", "BOSCH", "大疆",
    "DJI", "GoPro", "佳能", "Canon", "尼康", "Nikon", "适马", "SIGMA",
    "Anker", "安克", "贝尔金", "Belkin", "雷柏", "RAPOO", "达尔优", "IKBC",
    "阿米洛", "Varmilo", "洛斐", "Lofree", "攀升", "京东京造", "网易严选",
    # 户外与服装（冲锋衣/羽绒服/鞋服是高频购物类目）
    "探路者", "TOREAD", "凯乐石", "KAILAS", "伯希和", "PELLIOT", "骆驼",
    "CAMEL", "迪卡侬", "Decathlon", "挪客", "Naturehike", "牧高笛", "MobiGarden",
    "北面", "TheNorthFace", "Columbia", "哥伦比亚", "狼爪", "JackWolfskin",
    "猛犸象", "Mammut", "始祖鸟", "Arc'teryx", "巴塔哥尼亚", "Patagonia",
    "优衣库", "Uniqlo", "无印良品", "MUJI", "海澜之家", "太平鸟", "波司登",
    "Bosideng", "雪中飞", "安踏", "Anta", "李宁", "Lining", "特步", "Xtep",
    "361度", "匹克", "Peak", "鸿星尔克", "ERKE", "回力", "Warrior",
    "耐克", "Nike", "阿迪达斯", "Adidas", "彪马", "Puma", "新百伦",
    "NewBalance", "亚瑟士", "ASICS", "斐乐", "Fila", "匡威", "Converse",
    "万斯", "Vans", "Skechers", "斯凯奇", "安德玛", "UnderArmour", "Lululemon",
]

VERSION_PATTERNS: List[Tuple[str, str]] = [
    (r"国行|大陆行货|大陆版|国内行货", "cn"),
    (r"港版|港行|香港行货", "hk"),
    (r"美版|美行", "us"),
    (r"日版|日行", "jp"),
    (r"欧版|英版|德版|欧行", "eu"),
    (r"海外版|国际版|全球版|水货|跨境", "oversea"),
]

# 品牌别名归一：中文名与英文名指向同一 canonical 名
BRAND_ALIASES: Dict[str, str] = {
    "索尼": "Sony", "苹果": "Apple", "华为": "Huawei", "小米": "Xiaomi",
    "红米": "Redmi", "荣耀": "Honor", "三星": "Samsung", "联想": "Lenovo",
    "华硕": "ASUS", "戴尔": "Dell", "惠普": "HP", "罗技": "Logitech",
    "雷蛇": "Razer", "漫步者": "Edifier", "森海塞尔": "Sennheiser",
    "任天堂": "Nintendo", "微软": "Microsoft", "松下": "Panasonic",
    "飞利浦": "Philips", "海尔": "Haier", "美的": "Midea", "格力": "Gree",
    "西门子": "Siemens", "博世": "Bosch", "大疆": "DJI", "佳能": "Canon",
    "尼康": "Nikon", "安克": "Anker", "一加": "OnePlus",
}

_ALIAS_BY_LOWER: Dict[str, str] = {
    alias.lower(): canonical for alias, canonical in BRAND_ALIASES.items()
}
_ALIAS_BY_LOWER.update({
    canonical.lower(): canonical for canonical in BRAND_ALIASES.values()
})


def canonical_brand(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    return _ALIAS_BY_LOWER.get(name.strip().lower(), name.strip())

CONDITION_PATTERNS: List[Tuple[str, str]] = [
    (r"二手|9成新|99新|95新|8成新|闲置|已激活使用", "used"),
    (r"官翻|官换机|翻新| refurbished", "refurbished"),
    (r"全新|未拆封|未激活|正品全新", "new"),
]

BUNDLE_PATTERNS = [r"套装", r"礼盒", r"套餐", r"含.{0,6}(配件|保护套|键盘|鼠标|充电器)", r"套餐版"]

COLOR_WORDS = [
    "曜石黑", "星空黑", "暗夜黑", "磨砂黑", "亮黑色", "深空黑", "黑色", "黑",
    "白色", "月光白", "珍珠白", "银色", "深空灰", "太空灰", "灰色", "钛金色",
    "金色", "香槟金", "玫瑰金", "粉色", "樱花粉", "蓝色", "海蓝色", "天蓝色",
    "绿色", "苍岭绿", "翡翠绿", "紫色", "橘色", "橙色", "黄色", "红色", "珊瑚色",
    "星光色", "午夜色", "原色", "钛金属", "远峰蓝", "湖光蓝色", "云白色",
    "black", "white", "silver", "gold", "gray", "grey", "blue", "green",
    "pink", "purple", "red", "orange", "yellow",
]

_STORAGE_RE = re.compile(
    r"(?<![\d.])(?P<num>\d{1,4})\s*(?P<unit>GB|TB|MB|G|T)(?![\w.])", re.IGNORECASE
)
# 字母数字型号（WH-1000XM5 / RTX4070 / S24）
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[-–][A-Za-z0-9]+)*\d[\w-]*")
# 「单词 + 数字」型号（iPhone 15 / Galaxy S24 的 S24 由上一规则捕获）
_WORD_NUM_RE = re.compile(r"\b([A-Za-z]{2,})\s+(\d{1,4}[A-Za-z]{0,6})\b")
# 尺码：字母尺码 / 「42码」/「175/96A」号型。
# 字母尺码要求两侧都不是字母数字，且前面不是「数字+空格」，
# 这样 "5G"、"S24"、"M330"、"1.5 L" 都不会被误当成尺码。
_SIZE_RE = re.compile(
    r"(?<![\d.])(?<!\d\s)(?P<alpha>\d?X{0,3}L|\d?XL|XS|S|M)(?![A-Za-z0-9])"
    r"|(?<![\d.])(?P<num>\d{2,3})\s*(?=码)"
    r"|(?<![\d.])(?P<eu>\d{3}/\d{2,3}[A-D])"
)
# 存储单位的归一写法
_STORAGE_UNIT = {"G": "GB", "T": "TB", "GB": "GB", "TB": "TB", "MB": "MB"}


def _is_plausible_storage(num: str, unit: str) -> bool:
    """排除把网络制式/容量单位误判成存储的情况。

    "5G" 是网络制式不是 5GB；裸写 G/T 时至少两位才可能是存储容量。
    """
    if unit.upper() in ("GB", "TB", "MB"):
        return True
    return len(num) >= 2


# ─── 签名 ──────────────────────────────────────────────────────

@dataclass
class ModelSignature:
    brand: Optional[str] = None
    model_tokens: Set[str] = field(default_factory=set)
    storages: Set[str] = field(default_factory=set)
    # 服装/鞋类的尺码（L/XL/42码/175/96A）。不同尺码是不同 SKU，硬冲突。
    sizes: Set[str] = field(default_factory=set)
    color: Optional[str] = None
    version: Optional[str] = None      # cn/hk/us/jp/eu/oversea/None
    condition: Optional[str] = None    # new/used/refurbished/None
    bundle: bool = False

    @property
    def storage(self) -> Optional[str]:
        """取最大存储规格作为主规格（16GB+512GB 中取 512GB）。"""
        if not self.storages:
            return None

        def size_key(s: str) -> Tuple[int, int]:
            num, unit = s[:-2], s[-2:].upper()
            multiplier = 1024 if unit == "TB" else 1
            return (int(num) * multiplier, 0)

        return sorted(self.storages, key=size_key)[-1]

    def key(self) -> str:
        parts = [
            (self.brand or "").upper(),
            "-".join(sorted(self.model_tokens)),
            self.storage or "",
            self.version or "",
            self.condition or "",
            "bundle" if self.bundle else "",
        ]
        return "|".join(parts)


def _normalize_storage(num: str, unit: str) -> str:
    unit = unit.upper()
    if unit == "T":
        unit = "TB"
    if unit == "G":
        unit = "GB"
    return f"{num}{unit}"


def extract_signature(title: str, brand_hint: Optional[str] = None) -> ModelSignature:
    sig = ModelSignature(brand=canonical_brand(brand_hint))
    text = title or ""

    if not sig.brand:
        for brand in KNOWN_BRANDS:
            if re.search(re.escape(brand), text, re.IGNORECASE):
                sig.brand = canonical_brand(brand)
                break

    # 先剥离容量写法，避免 "Pro 256GB" 被误判为型号 token
    text_wo_storage = _STORAGE_RE.sub(" ", text)

    for match in _TOKEN_RE.findall(text_wo_storage):
        token = re.sub(r"[^A-Za-z0-9]", "", match).upper()
        if len(token) >= 3 and any(ch.isdigit() for ch in token):
            if re.fullmatch(r"\d+(GB|TB|G|T)", token, re.IGNORECASE):
                continue
            sig.model_tokens.add(token)

    # "iPhone 15" 这类跨词型号
    for word, num in _WORD_NUM_RE.findall(text_wo_storage):
        token = (word + num).upper()
        if len(token) <= 14:
            sig.model_tokens.add(token)

    for num, unit in _STORAGE_RE.findall(text):
        # "5G" 是网络制式不是存储；裸写 G/T 且只有一位时不认
        if not _is_plausible_storage(num, unit):
            continue
        sig.storages.add(_normalize_storage(num, _STORAGE_UNIT[unit.upper()]))

    for match in _SIZE_RE.finditer(text):
        value = match.group(0).strip().upper()
        if value:
            sig.sizes.add(value)

    for word in COLOR_WORDS:
        if re.search(r"(?<![A-Za-z])" + re.escape(word) + r"(?![A-Za-z])", text, re.IGNORECASE):
            sig.color = word
            break

    for pattern, version in VERSION_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            sig.version = version
            break

    for pattern, condition in CONDITION_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            sig.condition = condition
            break

    if any(re.search(p, text, re.IGNORECASE) for p in BUNDLE_PATTERNS):
        sig.bundle = True

    return sig


def brand_as_written(text: str) -> str:
    """返回品牌在标题里的原始写法（"索尼"而不是归一后的 "Sony"）。

    跨平台搜同款时用原标题里的写法：中文平台搜「索尼 WH-1000XM5」比搜
    「Sony WH-1000XM5」命中的同款更多。
    """
    best = ""
    best_at = len(text) + 1
    for brand in KNOWN_BRANDS:
        match = re.search(re.escape(brand), text, re.IGNORECASE)
        if match and match.start() < best_at:
            best, best_at = match.group(0), match.start()
    return best


# 型号后面的档位词：Pro/Max 和标准版是不同 SKU、不同价，必须一起搜。
_SERIES_SUFFIX_RE = re.compile(r"\b(Pro|Max|Plus|Ultra|Air|Mini|Lite|SE|Note|GT)\b", re.I)

# 「单词 + 数字」型号（iPhone 15 / Galaxy S24 的 S24 由 _TOKEN_RE 捕获）。
# 数字后面不能紧跟小数或计量单位：MacBook Air「13.6英寸」是屏幕尺寸不是型号。
_WORD_NUM_MODEL_RE = re.compile(
    r"\b([A-Za-z]{2,}|[A-Za-z]\d)\s+(\d{1,4}[A-Za-z]{0,6})"
    r"(?!\.\d)(?!\s*(?:英寸|寸|厘米|米|毫米|mm|cm|kg|克|瓦|w|wh|小时|分钟|年|月|日|款|代|核|hz|bit))\b",
    re.IGNORECASE,
)

# 短型号（X1 / M2 / S9）。字母开头、带数字、不超过 6 位。
# 边界用 (?<![A-Za-z0-9]) 而不是 \b：\b 把中文也算词内字符，
# "M2芯片" 这种紧贴中文的型号会整个匹配不上。
_SHORT_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9])([A-Za-z]{1,2}\d[A-Za-z0-9]*)(?![A-Za-z0-9])")
# 这些是参数不是型号：网络制式、分辨率、接口。
_NON_MODEL_TOKENS = {
    "3G", "4G", "5G", "2G", "2K", "4K", "8K", "1080P", "720P", "HDR", "LED",
    "LCD", "OLED", "USB", "HDMI", "WIFI", "TYPE", "PD", "QC", "A4", "B5", "A3",
}


def _series_suffix(text: str, start: int) -> str:
    """取型号后面紧跟的档位词（最多两个），如 "15 Pro Max" 的 "Pro Max"。"""
    picked: List[str] = []
    for word in text[start:].split():
        if len(picked) == 2 or not _SERIES_SUFFIX_RE.fullmatch(word):
            break
        picked.append(word)
    return " " + " ".join(picked) if picked else ""


def search_keyword_from_title(title: str, *, max_tokens: int = 2) -> str:
    """从商品标题提炼「品牌 + 型号 + 容量」，作为跨平台搜同款的关键词。

    只保留能唯一定位同一 SKU 的信息。颜色/套装/成色刻意不加进关键词：
    加多了会把同款的其它配色搜丢，而错配的风险由 ``group_offers`` 的
    签名比对兜底，那边发现规格不符会明确告知而不是硬合组。

    型号保留标题里的原始写法（大小写、连字符原样）——搜「WH-1000XM5」
    比搜归一后的「WH1000XM5」准得多。

    提炼不出品牌以外的区分信息时返回空串：只拿一个品牌名去搜，搜回来
    的是一整页不相关商品，硬拿它们比价会误导人。
    """
    text = (title or "").strip()
    if not text:
        return ""
    sig = extract_signature(text)
    brand = brand_as_written(text) or sig.brand or ""

    without_storage = _STORAGE_RE.sub(" ", text)
    wanted = {token.upper() for token in sig.model_tokens}
    found: List[str] = []
    for match in _TOKEN_RE.finditer(without_storage):
        raw = match.group(0)
        # 紧跟在数字后面的字母数字串基本是芯片/参数名（骁龙8Gen2），不是型号
        if match.start() > 0 and text[match.start() - 1].isdigit():
            continue
        if re.sub(r"[^A-Za-z0-9]", "", raw).upper() in wanted and raw not in found:
            found.append(raw)

    if not found:
        for match in _WORD_NUM_MODEL_RE.finditer(without_storage):
            raw = match.group(0) + _series_suffix(without_storage, match.end())
            if raw not in found:
                found.append(raw)

    if not found:
        # 最后才放宽到短型号（X1 / M2）。这类串太容易撞上参数名，
        # 所以只在不带单位、且不在参数黑名单里时才认。
        for match in _SHORT_TOKEN_RE.finditer(without_storage):
            raw = match.group(1)
            upper = raw.upper()
            if upper in _NON_MODEL_TOKENS or len(upper) > 6:
                continue
            if match.start() > 0 and text[match.start() - 1].isdigit():
                continue
            if raw not in found:
                found.append(raw)
    found.sort(key=len, reverse=True)
    found = found[:max_tokens]

    if not found and not sig.storage:
        return ""
    parts = ([brand] if brand else []) + found + ([sig.storage] if sig.storage else [])
    return " ".join(part for part in parts if part).strip()


# ─── 匹配 ──────────────────────────────────────────────────────

_HARD_FIELDS = ("version", "condition", "bundle")


def hard_conflict(a: ModelSignature, b: ModelSignature) -> Optional[str]:
    """返回硬冲突说明；None 表示无硬冲突。"""
    if a.version and b.version and a.version != b.version:
        return "版本不同（国行/海外版混在一起）"
    if a.condition and b.condition and a.condition != b.condition:
        return "成色不同（全新/二手混在一起）"
    if a.bundle != b.bundle:
        return "套装与单品混在一起"
    if a.storage and b.storage and a.storage != b.storage:
        return f"容量不同（{a.storage} / {b.storage}）"
    if a.sizes and b.sizes and a.sizes != b.sizes:
        return f"尺码不同（{'/'.join(sorted(a.sizes))} / {'/'.join(sorted(b.sizes))}）"
    return None


def match_score(a: ModelSignature, b: ModelSignature) -> Tuple[float, List[str]]:
    """0-1 匹配分与理由。存在硬冲突时直接返回 0。"""
    conflict = hard_conflict(a, b)
    if conflict:
        return 0.0, [conflict]

    score = 0.0
    reasons: List[str] = []
    tokens_a, tokens_b = a.model_tokens, b.model_tokens
    if tokens_a and tokens_b:
        shared = tokens_a & tokens_b
        if not shared:
            return 0.0, ["型号标识不一致"]
        jaccard = len(shared) / len(tokens_a | tokens_b)
        score += 0.55 * jaccard
        if jaccard >= 0.99:
            reasons.append(f"型号一致（{'/'.join(sorted(shared))}）")
        else:
            reasons.append(f"型号部分一致（{'/'.join(sorted(shared))}）")
    elif tokens_a or tokens_b:
        score += 0.2
        reasons.append("一方缺少明确型号标识")

    if a.brand and b.brand:
        if canonical_brand(a.brand) == canonical_brand(b.brand):
            score += 0.2
            reasons.append(f"品牌一致（{canonical_brand(a.brand)}）")
        else:
            return 0.0, [f"品牌不同（{a.brand} / {b.brand}）"]
    elif a.brand or b.brand:
        score += 0.1

    if a.storage and b.storage and a.storage == b.storage:
        score += 0.15
        reasons.append(f"容量一致（{a.storage}）")
    elif a.storage and b.storage:
        score += 0.05

    if a.color and b.color and a.color != b.color:
        reasons.append(f"颜色不同（{a.color} / {b.color}），价格可能略有差异")
    elif a.color and b.color:
        score += 0.1

    return min(score, 1.0), reasons


@dataclass
class MatchGroup:
    signature: ModelSignature
    offers: List[Offer]
    warnings: List[str]
    confidence: float


MATCH_THRESHOLD = 0.45


def group_offers(offers: List[Offer]) -> List[MatchGroup]:
    """把 offer 列表按规格签名聚成匹配组（并查集）。"""
    signatures = [extract_signature(o.title, o.brand) for o in offers]
    n = len(offers)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[max(rx, ry)] = min(rx, ry)

    for i in range(n):
        for j in range(i + 1, n):
            score, _ = match_score(signatures[i], signatures[j])
            if score >= MATCH_THRESHOLD:
                union(i, j)

    clusters: Dict[int, List[int]] = {}
    for i in range(n):
        clusters.setdefault(find(i), []).append(i)

    groups: List[MatchGroup] = []
    for members in clusters.values():
        group_offers_list = [offers[i] for i in members]
        sigs = [signatures[i] for i in members]
        warnings: List[str] = []
        # 组内两两检查软冲突
        colors = {s.color for s in sigs if s.color}
        if len(colors) > 1:
            warnings.append(
                "组内包含不同颜色：" + "、".join(sorted(colors)) + "，请按需选择"
            )
        brands = {canonical_brand(s.brand) for s in sigs if s.brand}
        if len(brands) > 1:
            warnings.append("组内品牌标识不一致，请人工确认")
        confidences = [
            match_score(sigs[0], s)[0] for s in sigs[1:]
        ]
        confidence = min(confidences) if confidences else 1.0
        # 把匹配信息写回 offer
        for offer in group_offers_list:
            offer.match_confidence = round(confidence, 3)
            offer.match_notes = list(warnings)
        groups.append(MatchGroup(
            signature=sigs[0],
            offers=group_offers_list,
            warnings=warnings,
            confidence=round(confidence, 3),
        ))

    # 组按（有真实数据的）最低确定到手价排序
    from .pricing import compute_price_breakdown

    def group_key(g: MatchGroup) -> Tuple[int, Decimal]:
        real = [o for o in g.offers if o.data_status.value != "demo"]
        if real:
            return (0, min(compute_price_breakdown(o).definite_total for o in real))
        return (1, Decimal("0"))

    groups.sort(key=group_key)
    return groups
