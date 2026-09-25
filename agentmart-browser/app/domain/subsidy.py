"""国补（政府补贴）资格与到手价的两套算法。

为什么不能"自动匹配"成一个数：国补的资格取决于收货地区、商品品类、
能效等级、单件售价上限、以及每人已领次数 —— 这些**没有一项能从商品页
确认**。页面上那句"国补 15%"只说明"有这个活动"，不说明"你能拿到"。
所以这里做的是把两种情形都算出来、都标清楚，让用户自己对照：

- 不符合资格时的到手价（确定要付的）；
- 符合资格时预计还能再减多少（标注为"仅当你本人符合资格"）。

两个数都摆出来，不合并、不挑好看的那个。补贴永远不进"确定到手价"。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import List, Optional


class SubsidyFit(str, Enum):
    """页面文字能否支撑我们对这次补贴作出判断。"""

    # 页面写明了地区限制，且和用户收货地对得上
    REGION_MATCHES = "region_matches"
    # 页面写明了地区限制，但和用户收货地对不上
    REGION_CONFLICTS = "region_conflicts"
    # 页面没写地区限制，无法判断
    UNKNOWN = "unknown"


# 文案里写死的地区限制，例如"限江苏用户""仅限北京地区""指定广东"。
# 用前瞻收边界而不是把后缀吃进分组：真实文案里"江苏用户""江苏省""江苏地区"
# 三种写法都有，核心地名要拿出来单独比。
_REGION_LIMIT_RE = re.compile(
    r"(?:限|仅限|仅支持|只支持|指定)\s*"
    r"([一-龥]{2,8}?)(?=省|市|自治区|特别行政区|地区|用户|，|,|。|；|;|$)"
)
# 补贴比例 / 金额
_SUBSIDY_PERCENT_RE = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*%")
_SUBSIDY_AMOUNT_RE = re.compile(r"(?:减|补贴|抵扣)\s*([0-9]+(?:\.[0-9]{1,2})?)\s*元")
# 国补常见的封顶比例（用于说明"比例之外还有上限"，不替用户认定资格）
_TYPICAL_CAP_PERCENT = Decimal("15")


@dataclass
class SubsidyReading:
    """一条补贴文案 + 用户收货地 的解释结果。"""

    raw_text: str
    percent: Optional[Decimal] = None
    amount: Optional[Decimal] = None
    region_limit: Optional[str] = None
    user_region: Optional[str] = None
    fit: SubsidyFit = SubsidyFit.UNKNOWN
    reason: str = ""
    questions: List[str] = field(default_factory=list)

    @property
    def has_quantified_benefit(self) -> bool:
        return self.percent is not None or self.amount is not None

    def to_dict(self) -> dict:
        return {
            "raw_text": self.raw_text,
            "percent": str(self.percent) if self.percent is not None else None,
            "amount": str(self.amount) if self.amount is not None else None,
            "region_limit": self.region_limit,
            "user_region": self.user_region,
            "fit": self.fit.value,
            "fit_label": _FIT_LABEL[self.fit],
            "reason": self.reason,
            "questions": list(self.questions),
        }


_FIT_LABEL = {
    SubsidyFit.REGION_MATCHES: "地区与您填写的一致",
    SubsidyFit.REGION_CONFLICTS: "地区与您填写的不一致",
    SubsidyFit.UNKNOWN: "页面未写地区限制",
}


def _normalize_region(text: str) -> str:
    """把"江苏省""江苏""南京市"归到可比的形式。

    只做最保守的归一：去掉行政区划后缀。这样"江苏"和"江苏省"能对上，
    但"江苏"和"南京"仍然对不上 —— 那本来就需要用户自己确认。
    """
    text = (text or "").strip()
    for suffix in ("特别行政区", "自治区", "省", "市"):
        if text.endswith(suffix) and len(text) > len(suffix):
            return text[: -len(suffix)]
    return text


def interpret_subsidy_text(
    text: str, user_region: Optional[str] = None
) -> Optional[SubsidyReading]:
    """解释一条补贴文案。没有补贴关键词就返回 None（不猜）。"""
    raw = (text or "").strip()
    if not raw or "国补" not in raw and "补贴" not in raw:
        return None

    percent: Optional[Decimal] = None
    amount: Optional[Decimal] = None
    m = _SUBSIDY_PERCENT_RE.search(raw)
    if m:
        percent = Decimal(m.group(1))
    m = _SUBSIDY_AMOUNT_RE.search(raw)
    if m:
        amount = Decimal(m.group(1))

    region_limit: Optional[str] = None
    m = _REGION_LIMIT_RE.search(raw)
    if m:
        region_limit = m.group(1)

    questions: List[str] = []
    fit = SubsidyFit.UNKNOWN
    reason = "页面未写地区限制，资格需本人核实"

    if region_limit:
        if user_region:
            if _normalize_region(region_limit) == _normalize_region(user_region):
                fit = SubsidyFit.REGION_MATCHES
                reason = f"页面写明限{region_limit}，与您填写的收货地一致"
            else:
                fit = SubsidyFit.REGION_CONFLICTS
                reason = (
                    f"页面写明限{region_limit}，与您填写的收货地"
                    f"（{user_region}）不一致"
                )
        else:
            reason = f"页面写明限{region_limit}，您还没有填写收货地"
            questions.append(f"你的收货地是{region_limit}吗？")
    else:
        questions.append("你本人符合这个补贴的资格吗（品类/能效等级/是否已领取）？")

    if not questions:
        questions.append(
            "品类、能效等级、售价上限和每人已领次数都符合吗？"
            "有一项不符合就享受不到。"
        )

    return SubsidyReading(
        raw_text=raw,
        percent=percent,
        amount=amount,
        region_limit=region_limit,
        user_region=user_region,
        fit=fit,
        reason=reason,
        questions=questions,
    )


@dataclass
class SubsidyScenario:
    """同一件商品在"有补贴/无补贴"两种情形下的到手价。"""

    with_subsidy: Optional[Decimal]
    without_subsidy: Decimal
    note: str

    def to_dict(self) -> dict:
        return {
            "with_subsidy": str(self.with_subsidy) if self.with_subsidy is not None else None,
            "without_subsidy": str(self.without_subsidy),
            "note": self.note,
        }


def subsidy_scenarios(
    definite_total: Decimal,
    reading: Optional[SubsidyReading],
) -> Optional[SubsidyScenario]:
    """按"是否符合资格"算出两个到手价。

    没有任何可量化补贴时返回 None —— 不硬凑一个数出来。
    """
    if reading is None or not reading.has_quantified_benefit:
        return None

    benefit: Optional[Decimal] = None
    if reading.amount is not None:
        benefit = reading.amount
    elif reading.percent is not None:
        benefit = (definite_total * reading.percent / Decimal("100")).quantize(
            Decimal("0.01")
        )

    if benefit is None:
        return None

    with_subsidy = (definite_total - benefit).quantize(Decimal("0.01"))
    if with_subsidy < Decimal("0"):
        with_subsidy = Decimal("0.00")

    note = (
        f"左侧是确定要付的 {definite_total} 元；右侧仅在您本人符合补贴资格时成立，"
        f"预计再减 {benefit} 元。资格未经核实，本工具不代您认定。"
    )
    if reading.fit is SubsidyFit.REGION_CONFLICTS:
        note += "另外，页面写明的补贴地区与您填写的收货地不一致，右侧情形很可能不成立。"
    return SubsidyScenario(
        with_subsidy=with_subsidy, without_subsidy=definite_total, note=note
    )
