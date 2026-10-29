# -*- coding: utf-8 -*-
"""配方结果指纹：给「性能优化」上一道「不许改结果」的保险。

    python scripts/check_regression.py            # 与基线比对，有差异则退出码 1
    python scripts/check_regression.py --write    # 重新生成基线
    python scripts/check_regression.py --show 3   # 打印前 3 个差异块的明细

为什么需要它：`scripts/bench.py` 只回答「快不快」，回答不了「算出来的东西还是不是
同一个东西」。配方搜索里任何一次「看起来等价」的改写（缓存、剪枝、遍历顺序、
浮点结合律）都可能让某个色号在某个目标色下换一支漆——ΔE 只差 0.001，界面上完全
看不出来，但用户买回来的是另一瓶漆。

指纹口径：固定目标色 × 多套色差公式，把「锚点 / 组分 / 滴数 / 比例 / 混合色 /
ΔE / 替代色」全量序列化后取 sha256。任何一位变化都会让指纹变。

基线存在 ``tests/data/suggestion_fingerprint.json``，由 ``--write`` 生成，随仓库
一起提交。**只有当结果变化是本次改动的预期目的时**才重写基线，并在提交信息里
写清原因。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core.config import AppConfig  # noqa: E402
from app.services.paint_matcher import PaintMatcher  # noqa: E402
from app.services.scheme_engine import build_scheme, compute_base_mix  # noqa: E402

BASELINE_PATH = ROOT / "tests" / "data" / "suggestion_fingerprint.json"

# 固定目标色：覆盖深色 / 高饱和 / 近中性 / 肤色 / 极值，避免随机导致基线不稳
TARGETS: List[tuple] = [
    (12, 14, 16), (30, 90, 160), (60, 120, 70), (90, 60, 130),
    (120, 96, 72), (128, 128, 128), (150, 40, 40), (180, 150, 90),
    (205, 145, 147), (216, 118, 68), (217, 161, 140), (239, 168, 64),
    (240, 240, 232), (255, 255, 255), (0, 0, 0),
]
FORMULAS = ("CIEDE2000", "CIE94", "CIE76", "CMC")


def _round(value: float, digits: int = 10) -> float:
    """统一取整，避免平台浮点尾数抖动把指纹搞脏。"""
    return round(float(value), digits)


def _suggestion_detail(item) -> dict:
    """一条建议的完整可比内容。"""
    return {
        "rank": item.rank,
        "anchor": item.anchor.uid,
        "delta_e": _round(item.delta_e),
        "mode": item.mode_label,
        "direct": item.is_direct,
        "within_tolerance": item.is_within_tolerance,
        "mixed_hex": item.recipe.mixed_hex,
        "components": [
            (comp.paint.uid, comp.drops, _round(comp.proportion, 12))
            for comp in item.recipe.components
        ],
        "coverage": {
            "paint": item.coverage.paint_ml,
            "thinner": item.coverage.thinner_ml,
            "mix": item.coverage.mix_ml,
            "bottles": item.coverage.bottles,
            "per_component": dict(item.coverage.per_component_ml),
        },
        "alternatives": [
            (alt.paint.uid, alt.evidence, _round(alt.delta_e))
            for alt in item.alternatives
        ],
        "notes": list(item.notes),
    }


def _mix_detail(recipe) -> dict:
    return {
        "delta_e": _round(recipe.delta_e),
        "predicted_rgb": list(recipe.predicted_rgb),
        "total_drops": recipe.total_drops,
        "components": [
            (comp.role, comp.drops, _round(comp.percent, 8),
             comp.suggestion.anchor.uid if comp.suggestion else None)
            for comp in recipe.components
        ],
    }


def _digest(payload) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def collect() -> List[dict]:
    """跑一遍全部比对块，返回 [{key, digest, detail}]。"""
    matcher = PaintMatcher()
    blocks: List[dict] = []

    for formula in FORMULAS:
        config = AppConfig().validate()
        config.delta_e_formula = formula
        for target in TARGETS:
            items = matcher.suggest(target, config)
            detail = [_suggestion_detail(item) for item in items]
            blocks.append({
                "key": f"suggest/{formula}/{target[0]}-{target[1]}-{target[2]}",
                "digest": _digest(detail),
                "detail": detail,
            })

    config = AppConfig().validate()
    for target in TARGETS[:8]:
        mix = compute_base_mix(target, config, matcher=matcher)
        stops = build_scheme(matcher, target, config, scheme_type="basic")
        detail = {
            "mix": _mix_detail(mix),
            "scheme": [stop.suggestion.anchor.uid if stop.suggestion else None
                       for stop in stops],
        }
        blocks.append({
            "key": f"mix+scheme/{target[0]}-{target[1]}-{target[2]}",
            "digest": _digest(detail),
            "detail": detail,
        })
    return blocks


def _load_baseline() -> dict:
    if not BASELINE_PATH.exists():
        return {}
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="重写基线")
    parser.add_argument("--show", type=int, default=2, help="打印几个差异块的明细")
    args = parser.parse_args()

    blocks = collect()
    fingerprints = {block["key"]: block["digest"] for block in blocks}

    if args.write:
        BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": 1,
            "note": "配方结果指纹基线；仅当结果变化是本次改动的预期目的时才重写",
            "blocks": len(fingerprints),
            "fingerprints": fingerprints,
        }
        BASELINE_PATH.write_text(
            json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"已写入基线：{BASELINE_PATH.relative_to(ROOT)}（{len(fingerprints)} 块）")
        return 0

    baseline = _load_baseline()
    if not baseline:
        print(f"未找到基线 {BASELINE_PATH.relative_to(ROOT)}，先执行 --write", file=sys.stderr)
        return 2

    expected = baseline.get("fingerprints", {})
    changed = [key for key in expected if key in fingerprints
               and fingerprints[key] != expected[key]]
    missing = [key for key in expected if key not in fingerprints]
    added = [key for key in fingerprints if key not in expected]

    detail_of = {block["key"]: block["detail"] for block in blocks}
    for key in changed[: max(0, args.show)]:
        print(f"\n[DIFF] {key}")
        print("  当前：", json.dumps(detail_of[key], ensure_ascii=False)[:600])

    total = len(expected)
    if changed or missing or added:
        print(f"\n结果指纹不一致：{len(changed)} 块变化 / {len(missing)} 块缺失 / "
              f"{len(added)} 块新增（基线共 {total} 块）")
        return 1

    print(f"结果指纹一致：{total} 块全部匹配")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
