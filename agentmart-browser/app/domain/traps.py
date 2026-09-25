"""防套路：把页面上「看着便宜、其实有坑」的信号挑出来。

比价真正难的从来不是找到最低价，而是三个价格根本不可比：
- 一个支持 7 天无理由，一个激活了就不给退；
- 一个是国行全国联保，一个是港版自己找店修；
- 一个带运费险（退货不用掏运费），一个退货运费自理。

这些差异页面上都有，但都写在不起眼的政策栏里，且**多数是否定式的**
——「不支持7天无理由」「激活后不可退」。现有的政策抽取会把它们
和「7天无理由」归成同一类，用户在「售后与保障」里看到一排政策，
根本分不清哪条是保护、哪条是限制。

这里的规矩只有一条：**没有页面证据就不说有坑，证据是否定式的就按
限制报，页面没提的按「未显示」报并让用户自己去确认。**
宁可少报一个坑，不能把一个保护讲成坑，也不能把坑讲成保护。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional


class TrapKind(str, Enum):
    """坑的种类。"""

    NO_RETURN_WINDOW = "no_return_window"      # 没有/不支持 7 天无理由
    ACTIVATION_LOCKED = "activation_locked"    # 激活后不退
    NON_MAINLAND = "non_mainland"              # 非国行（港版/海外版）
    NO_FREIGHT_INSURANCE = "no_freight_insurance"  # 页面未显示运费险
    SPECIAL_NO_RETURN = "special_no_return"    # 特价/清仓/尾货不退不换
    SUBSIDY_UNVERIFIED = "subsidy_unverified"  # 有补贴但资格没核实


class TrapSeverity(str, Enum):
    """严重程度。blocker = 可能直接让这件商品不能买。"""

    BLOCKER = "blocker"    # 买之前必须先解决（非国行、激活不退）
    MAJOR = "major"        # 明显影响决策（不支持7天无理由）
    MINOR = "minor"        # 值得知道，不影响主决策（没有运费险）


# ─── 模式 ────────────────────────────────────────────────────────

# 否定式退货限制：「不支持7天无理由」「不可7天无理由」「非7天无理由商品」
_NO_RETURN_RE = re.compile(
    r"(?:不支持|不可|非|不享|无)(?:七天|7天|7 天)?\s*无理由"
    r"|无理由\s*(?:不支持|不可|不适用)"
    r"|不退不换|不予退换|不支持退换"
)
# 激活/拆封后不退：先出现"激活/拆封"，紧跟一个否定词，再落到退换上。
# 限定标点窗口，避免把"激活后可享受7天无理由"里的"激活"误抓出来。
_ACTIVATION_RE = re.compile(
    r"(?:激活|拆封|拆包|开机|绑定)[^。；，,\n]{0,10}"
    r"(?:不支持|不可|不予|无法|不能)[^。；，,\n]{0,8}"
    r"(?:退货|退款|退换|无理由)"
)
# 非国行版本
_NON_MAINLAND_RE = re.compile(
    r"非国行|港版|港行|海外版|美版|日版|欧版|韩版|台版|水货|跨境版"
)
# 明确是国行（正面证据，用来避免误报）
_MAINLAND_OK_RE = re.compile(r"国行|国内行货|大陆行货|全国联保")
# 特价/清仓类不退：两个信号必须挨着出现，只出现"特价"不算
_SPECIAL_NO_RETURN_RE = re.compile(
    r"(?:特价|清仓|尾货|处理品|样品|二手|翻新)[^。；，,\n]{0,12}"
    r"(?:不退不换|不予退换|不支持|不可退|不可换|无法退|无法换)"
)
# 运费险
_FREIGHT_INSURANCE_RE = re.compile(r"运费险|退货运费险|退货包运费")
# 7 天无理由（正面）
_RETURN_WINDOW_RE = re.compile(r"七天无理由|7天无理由|7 天无理由")
# 补贴
_SUBSIDY_RE = re.compile(r"国补|国家补贴|政府补贴|能效补贴|以旧换新|换新补贴")


class TrapBasis(str, Enum):
    """这条提示的证据来自哪里。

    ``PAGE_TEXT`` = 页面上白纸黑字写了（包括明确写了"不支持"）；
    ``NOT_SHOWN`` = 页面上没看到 —— 这只是"没找到"，不等于"没有"，
    所以必须配一个待确认问题，绝不能写成"不支持"。
    """

    PAGE_TEXT = "page_text"
    NOT_SHOWN = "not_shown"


@dataclass
class Trap:
    """一条「防套路」提示。

    ``evidence`` 必须是页面上的原文。``basis`` 为 NOT_SHOWN 时
    ``evidence`` 为空，``question`` 必填 —— 那是要用户自己去确认的事。
    """

    kind: TrapKind
    label: str
    severity: TrapSeverity
    detail: str
    evidence: str = ""
    question: str = ""
    basis: TrapBasis = TrapBasis.PAGE_TEXT
    source_url: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "kind": self.kind.value,
            "label": self.label,
            "severity": self.severity.value,
            "severity_label": _SEVERITY_LABEL[self.severity],
            "detail": self.detail,
            "evidence": self.evidence,
            "question": self.question,
            "basis": self.basis.value,
            "basis_label": _BASIS_LABEL[self.basis],
        }


_SEVERITY_LABEL = {
    TrapSeverity.BLOCKER: "买前必须先确认",
    TrapSeverity.MAJOR: "明显影响决策",
    TrapSeverity.MINOR: "值得知道",
}
_BASIS_LABEL = {
    TrapBasis.PAGE_TEXT: "页面原文",
    TrapBasis.NOT_SHOWN: "页面未显示",
}


def _first_match(pattern: re.Pattern, texts: List[str]) -> Optional[str]:
    for text in texts:
        if pattern.search(text):
            return text.strip()
    return None


def detect_traps(
    policy_texts: List[str],
    coupon_texts: Optional[List[str]] = None,
    sku_text: str = "",
    title: str = "",
    source_url: Optional[str] = None,
) -> List[Trap]:
    """从页面文案里挑出「套路」信号。

    只看页面上真实出现的文字。sku/title 也参与，因为"港版""非国行"
    经常只写在规格或标题里，政策栏反而没有。
    """
    coupons = list(coupon_texts or [])
    policy = [t for t in (policy_texts or []) if t and t.strip()]
    # 版本相关信号要看全：政策栏、规格、标题三处
    version_texts = policy + ([sku_text] if sku_text else []) + ([title] if title else [])
    traps: List[Trap] = []

    def add(
        kind: TrapKind,
        label: str,
        severity: TrapSeverity,
        detail: str,
        evidence: str = "",
        question: str = "",
        basis: TrapBasis = TrapBasis.PAGE_TEXT,
    ) -> None:
        traps.append(
            Trap(
                kind=kind,
                label=label,
                severity=severity,
                detail=detail,
                evidence=evidence,
                question=question,
                basis=basis,
                source_url=source_url,
            )
        )

    # 1) 激活/拆封后不退 —— 最贵的一个坑，排最前
    evidence = _first_match(_ACTIVATION_RE, version_texts)
    if evidence:
        add(
            TrapKind.ACTIVATION_LOCKED,
            "激活后不支持退换",
            TrapSeverity.BLOCKER,
            "页面写明激活（或拆封）之后就不能退换。这类商品到手即锁定，"
            "买错型号、买错颜色都没有后悔余地。",
            evidence=evidence,
            question="这件商品激活/拆封后就不能退，你确定型号和配置都对吗？",
        )

    # 2) 非国行 —— 影响保修、发票、入网，也是 blocker
    non_mainland = _first_match(_NON_MAINLAND_RE, version_texts)
    if non_mainland:
        # 标题里同时写了"国行"和别的词时，仍然是"页面同时出现两种说法"，
        # 必须报出来让用户自己看，不替用户判定。
        add(
            TrapKind.NON_MAINLAND,
            "页面出现非国行版本描述",
            TrapSeverity.BLOCKER,
            "港版/海外版通常不享国内全国联保，发票和入网许可也可能不同，"
            "售后要自己找店。价格低往往正是低在这里。",
            evidence=non_mainland,
            question="这是国行吗？港版/海外版的保修和发票与国行不一样。",
        )

    # 3) 明确不支持 7 天无理由
    no_return = _first_match(_NO_RETURN_RE, policy)
    # 4) 特价/清仓不退不换。和上一条证据相同时只留更具体的这条 ——
    # 同一句"特价商品不支持7天无理由，不退不换"报两遍只是噪音。
    special = _first_match(_SPECIAL_NO_RETURN_RE, policy)
    same_text = special is not None and special == no_return
    if no_return and not same_text:
        add(
            TrapKind.NO_RETURN_WINDOW,
            "页面写明不支持7天无理由",
            TrapSeverity.MAJOR,
            "这件商品不适用 7 天无理由退货，到手后基本只能换不能退。",
            evidence=no_return,
            question="不支持7天无理由，你还想买吗？",
        )
    elif not _first_match(_RETURN_WINDOW_RE, policy):
        # 政策栏里完全没有"7天无理由"—— 这是"没看到"，不是"没有"。
        add(
            TrapKind.NO_RETURN_WINDOW,
            "页面未显示7天无理由",
            TrapSeverity.MINOR,
            "商品页的政策栏里没有找到 7 天无理由退货。可能是页面没加载全，"
            "也可能这件商品确实不支持。",
            question="下单前确认一下：这件支持 7 天无理由退货吗？",
            basis=TrapBasis.NOT_SHOWN,
        )

    if special:
        add(
            TrapKind.SPECIAL_NO_RETURN,
            "特价/清仓商品不退不换",
            TrapSeverity.MAJOR,
            "页面写明这类商品不退不换。低价来自这里，不是来自平台补贴。",
            evidence=special,
            question="特价商品不退不换，这个价格对应的是这个条件，你能接受吗？",
        )

    # 5) 运费险 —— 没有它，退货要自己掏运费
    if not _first_match(_FREIGHT_INSURANCE_RE, policy):
        add(
            TrapKind.NO_FREIGHT_INSURANCE,
            "页面未显示退货运费险",
            TrapSeverity.MINOR,
            "政策栏里没有看到退货运费险。没有运费险时，退货的运费要自己承担"
            "（大件可能几十元）。",
            question="退货运费谁承担？没有运费险的话可能得自己掏。",
            basis=TrapBasis.NOT_SHOWN,
        )

    # 6) 补贴资格没核实 —— 这是"钱上的坑"，不是"货上的坑"
    subsidy = _first_match(_SUBSIDY_RE, coupons)
    if subsidy:
        add(
            TrapKind.SUBSIDY_UNVERIFIED,
            "页面提到补贴，但资格未核实",
            TrapSeverity.MAJOR,
            "国补/以旧换新的资格取决于收货地区、商品品类、能效等级和是否已领取，"
            "这些都无法从商品页确认。本工具不代您认定资格，也没有把它计入到手价。",
            evidence=subsidy,
            question="你本人符合这个补贴的资格吗（地区/品类/是否已领取）？"
                     "不符合的话，到手价要按没有补贴算。",
        )

    return traps


def worst_severity(traps: List[Trap]) -> Optional[TrapSeverity]:
    """这一堆坑里最严重的一个，用于排序和摘要。"""
    order = {TrapSeverity.BLOCKER: 0, TrapSeverity.MAJOR: 1, TrapSeverity.MINOR: 2}
    present = [t.severity for t in traps]
    if not present:
        return None
    return min(present, key=lambda s: order[s])


def summarize_traps(traps: List[Trap]) -> str:
    """一句话说清这件商品的坑，用于对比表和建议文案。"""
    if not traps:
        return "页面未发现明显的退换或版本限制"
    blockers = [t for t in traps if t.severity is TrapSeverity.BLOCKER]
    majors = [t for t in traps if t.severity is TrapSeverity.MAJOR]
    parts = []
    if blockers:
        parts.append("、".join(t.label for t in blockers))
    if majors:
        parts.append("、".join(t.label for t in majors))
    head = "；".join(parts)
    minors = len(traps) - len(blockers) - len(majors)
    if minors > 0:
        head += f"；另有 {minors} 项待确认"
    return head
