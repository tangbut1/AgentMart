"""扩展 TypeScript 核心与 Python 实现的一致性校验。

第四步把比价/防套路/补贴逻辑移植到了 frontend/extension/core/（TypeScript），
侧面板里跑的就是那份代码。移植最容易出的错不是语法，而是**同一个页面两边
算出不同的结论**：舍入差一分、文案少一个字、某条文案走到了另一个分支。

所以这里做的是把同一份语料
（frontend/extension/tests/corpus/page-fields.json）
分别喂给 Python 的 build_offer/compute_price_breakdown/serialize.offer 和
TypeScript 的 buildOffer/computePriceBreakdown/offerView，然后逐字段比对。

两边故意保留的差异只有一处，都在代码里写了原因：
- ``credibility``：Python 用浮点连加再 round，在「认识店铺 + 无证据 +
  价格来自截图」这一种组合下会得到 0.7000000000000001；TypeScript 按整数
  百分数累加得到 0.7。这里用 1e-9 容差比对。

跑这个测试需要 node（用来执行 extension/tests/parity-emit.ts）。没有 node 时
测试会 skip，不会假装通过。
"""

from __future__ import annotations

import json
import shutil
import subprocess
from decimal import Decimal
from pathlib import Path

import pytest

from app.browser.enums import DataOrigin
from app.browser.extract import PageFields, build_offer
from app.browser.serialize import offer as serialize_offer
from app.domain.pricing import compute_price_breakdown

REPO_ROOT = Path(__file__).resolve().parents[1]
CORPUS_PATH = (
    REPO_ROOT / "frontend" / "extension" / "tests" / "corpus" / "page-fields.json"
)
EMITTER = REPO_ROOT / "frontend" / "extension" / "tests" / "parity-emit.ts"

# 两侧实现不同但都"对"的字段：见模块 docstring。
TOLERANT_FIELDS = {"credibility": 1e-9}


def _load_corpus() -> list[dict]:
    if not CORPUS_PATH.exists():
        pytest.skip(f"语料文件不存在：{CORPUS_PATH}")
    data = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    return data["cases"]


def _python_view(case: dict) -> dict:
    """Python 侧跑一遍完整流程，得到和前端 OfferView 同形的字典。"""
    fields = PageFields.from_js(case["fields"])
    offer, problems = build_offer(
        offer_platform(case["platform"]),
        fields,
        DataOrigin.REAL_PLATFORM_PAGE,
        source_label=case.get("source_label", "side-panel"),
    )
    assert offer is not None
    breakdown = compute_price_breakdown(offer)
    return {
        "view": serialize_offer(offer, breakdown, case.get("user_region")),
        "problems": list(problems),
    }


def offer_platform(value: str):
    from app.domain.enums import Platform

    return Platform(value)


def _typescript_views(corpus_path: Path, out_path: Path) -> dict:
    """调用 node 跑 TypeScript 侧的执行器。"""
    node = shutil.which("node")
    if node is None:
        pytest.skip("环境里没有 node，跳过 TS/Python 一致性校验")
    result = subprocess.run(
        [node, str(EMITTER), str(corpus_path), str(out_path)],
        capture_output=True,
        text=True,
        timeout=180,
        cwd=str(REPO_ROOT),
    )
    if result.returncode != 0:
        pytest.fail(
            "TypeScript 执行器失败：\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return json.loads(out_path.read_text(encoding="utf-8"))


def _diff_paths(python: object, ts: object, path: str = "") -> list[str]:
    """逐字段比对，返回人类可读的差异列表。"""
    problems: list[str] = []
    if isinstance(python, dict) and isinstance(ts, dict):
        for key in sorted(set(python) | set(ts)):
            if key not in python:
                problems.append(f"{path}.{key}: TS 多出字段 {ts[key]!r}")
            elif key not in ts:
                problems.append(f"{path}.{key}: TS 缺少字段（Python 是 {python[key]!r}）")
            else:
                problems.extend(_diff_paths(python[key], ts[key], f"{path}.{key}"))
        return problems
    if isinstance(python, list) and isinstance(ts, list):
        if len(python) != len(ts):
            problems.append(f"{path}: 列表长度不同 Python={len(python)} TS={len(ts)}")
        for index, (left, right) in enumerate(zip(python, ts)):
            problems.extend(_diff_paths(left, right, f"{path}[{index}]"))
        return problems
    if path.rsplit(".", 1)[-1] in TOLERANT_FIELDS:
        if python is None or ts is None:
            if python != ts:
                problems.append(f"{path}: Python={python!r} TS={ts!r}")
            return problems
        if abs(Decimal(str(python)) - Decimal(str(ts))) > Decimal(str(TOLERANT_FIELDS[path.rsplit('.', 1)[-1]])):
            problems.append(f"{path}: Python={python!r} TS={ts!r}")
        return problems
    if python != ts:
        problems.append(f"{path}: Python={python!r} TS={ts!r}")
    return problems


@pytest.mark.parametrize("case", _load_corpus(), ids=lambda case: case["name"])
def test_typescript_matches_python(case: dict, tmp_path: Path) -> None:
    """同一条语料，两边必须产出逐字段一致的 OfferView。"""
    corpus_path = tmp_path / "corpus.json"
    corpus_path.write_text(
        json.dumps({"cases": [case]}, ensure_ascii=False), encoding="utf-8"
    )
    out_path = tmp_path / "ts.json"
    ts_result = _typescript_views(corpus_path, out_path)[case["name"]]
    python_result = _python_view(case)

    # fetched_at 是"现在"，两边必然不同；只校验格式，内容另行断言。
    for result, label in ((python_result, "Python"), (ts_result, "TS")):
        fetched_at = result["view"].get("fetched_at")
        if fetched_at is not None:
            assert len(fetched_at) == 19 and fetched_at[10] == " ", (
                f"{label} 的 fetched_at 格式应为 'YYYY-MM-DD HH:MM:SS'，实际 {fetched_at!r}"
            )
    python_view = {k: v for k, v in python_result["view"].items() if k != "fetched_at"}
    ts_view = {k: v for k, v in ts_result["view"].items() if k != "fetched_at"}

    differences = _diff_paths(python_view, ts_view)
    differences.extend(_diff_paths(python_result["problems"], ts_result["problems"], "problems"))
    assert not differences, (
        f"语料 {case['name']} 两侧实现不一致：\n" + "\n".join(differences)
    )


def test_corpus_covers_required_branches() -> None:
    """语料本身要覆盖到关键分支，否则一致性校验会漏掉真正的坑。"""
    cases = _load_corpus()
    names = [case["name"] for case in cases]
    required = [
        "plain-jd-self-operated",
        "coupon-threshold-missed",
        "subsidy-percent-region-matches",
        "subsidy-percent-region-conflicts",
        "trap-activation-locked",
        "trap-non-mainland-in-title",
        "trap-special-no-return-dedup",
        "vision-price-unverified",
        "no-price-no-shop",
    ]
    missing = [name for name in required if name not in names]
    assert not missing, f"语料缺少关键用例：{missing}"
    assert len(cases) >= 15, "语料用例太少，覆盖不足"


def test_corpus_has_no_credential_like_values() -> None:
    """语料是给两侧实现喂的输入，不该夹带任何可复用的凭据字样。"""
    raw = CORPUS_PATH.read_text(encoding="utf-8").lower()
    banned = ["password", "passwd", "secret", "api_key", "apikey", "token", "cookie"]
    hits = [word for word in banned if word in raw]
    assert not hits, f"语料里出现凭据相关字样：{hits}"
