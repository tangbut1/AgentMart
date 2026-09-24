"""评测筛选维度：可解释的「可信度检查清单」。

选择参考哪些评测时不只看粉丝数，而是逐项检查：
1. 是否实际测试了该型号；
2. 是否提供测试方法与可复核的数据；
3. 是否说明使用条件与局限；
4. 是否披露商业合作关系；
5. 观点是否有足够内容支撑。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from ..domain.enums import CommercialRelation, CurationStatus
from ..domain.models import Review
from ..domain.matching import extract_signature


@dataclass
class CriteriaCheck:
    dimension: str
    met: bool
    note: str


@dataclass
class ReviewAssessment:
    checks: List[CriteriaCheck]
    score: float  # 0-1
    recommend_reference: bool  # 是否建议作为决策参考


def _tokens(text: Optional[str]) -> set:
    if not text:
        return set()
    return extract_signature(text).model_tokens


def evaluate_review(review: Review, query_model: Optional[str] = None) -> ReviewAssessment:
    checks: List[CriteriaCheck] = []

    # 1. 型号实测
    tested = bool(review.model_tested)
    matched_model = False
    if tested and query_model:
        q_tokens = _tokens(query_model)
        m_tokens = _tokens(review.model_tested or "")
        matched_model = bool(q_tokens & m_tokens)
    checks.append(CriteriaCheck(
        dimension="实际测试该型号",
        met=tested and (matched_model or not query_model),
        note=(
            f"整理记录显示测试型号：{review.model_tested}"
            if tested else "整理记录未填写测试型号，无法确认是否测过该商品"
        ),
    ))

    # 2. 测试方法与数据
    has_evidence = bool(review.test_evidence)
    checks.append(CriteriaCheck(
        dimension="提供测试方法与可复核数据",
        met=has_evidence,
        note=(
            "记录了测试方法/数据点：" + "；".join(review.test_evidence[:3])
            if has_evidence else "未记录测试方法或数据点，结论可复核性弱"
        ),
    ))

    # 3. 条件与局限
    has_limits = bool(review.scenarios) or bool(review.curator_notes)
    checks.append(CriteriaCheck(
        dimension="说明使用条件与局限",
        met=has_limits,
        note=(
            "记录了适用场景/局限：" + "；".join((review.scenarios or [review.curator_notes or ""])[:3])
            if has_limits else "未说明适用条件与局限"
        ),
    ))

    # 4. 商业关系披露
    disclosed = review.commercial_relation in (
        CommercialRelation.NONE_DISCLOSED,
        CommercialRelation.DISCLOSED,
    )
    checks.append(CriteriaCheck(
        dimension="披露商业合作关系",
        met=disclosed,
        note={
            CommercialRelation.NONE_DISCLOSED: "已披露无商业合作",
            CommercialRelation.DISCLOSED: "已披露存在商业合作/带货，阅读时请注意",
            CommercialRelation.UNDISCLOSED: "未披露商业合作关系，无法排除推广可能",
            CommercialRelation.UNKNOWN: "商业合作关系尚待核实",
        }.get(review.commercial_relation, "商业合作关系尚待核实"),
    ))

    # 5. 内容支撑
    support_count = len(review.pros) + len(review.cons) + len(review.quotes)
    checks.append(CriteriaCheck(
        dimension="观点有足够内容支撑",
        met=support_count >= 3,
        note=(
            f"整理了 {len(review.pros)} 条优点、{len(review.cons)} 条缺点、"
            f"{len(review.quotes)} 条原话引用"
            if support_count else "缺少观点与引用支撑"
        ),
    ))

    score = sum(1 for c in checks if c.met) / len(checks)
    return ReviewAssessment(
        checks=checks,
        score=round(score, 2),
        recommend_reference=(
            review.curation_status == CurationStatus.VERIFIED and score >= 0.6
        ),
    )
