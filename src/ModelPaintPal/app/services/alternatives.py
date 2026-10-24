# -*- coding: utf-8 -*-
"""替代色号检索。

两条证据链，优先级从高到低：
1. **标准色号一致**：都标注了同一个 FS / RAL / RLM / BS 色号（来自品牌官方
   转换表，可信度最高）；
2. **跨品牌最近色**：在 Lab 空间里 ΔE 最小且落在容差内。

返回值带上理由，UI 会显示「为什么它是替代品」，方便用户自己判断。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence

from ..core.delta_e import delta_e
from ..data.paint_db import PaintDatabase, PaintEntry

__all__ = ["Alternative", "find_alternatives", "STANDARD_PREFIXES"]

STANDARD_PREFIXES = ("FS", "RAL", "RLM", "BS", "AMT", "4BO", "7K", "6K")


@dataclass
class Alternative:
    paint: PaintEntry
    reason: str
    delta_e: float
    shared_standard: str = ""
    #: ``standard`` = 同一标准色号（品牌官方标注，证据强）
    #: ``nearest``  = 只是 Lab 空间里碰巧接近（证据弱，换批次就可能不成立）
    #:
    #: 这两条证据链此前在界面上看起来是等价的，只按 ΔE 排序 —— 但「官方说这两
    #: 个是同一个 FS 色」和「我算出来这两个颜色挺像」根本不是一回事。
    #: 分级后 UI 才能把它们区分开。
    evidence: str = "nearest"

    @property
    def reason_label(self) -> str:
        return self.reason

    @property
    def is_strong(self) -> bool:
        return self.evidence == "standard"

    @property
    def evidence_label(self) -> str:
        return "证据强" if self.is_strong else "证据弱"


def _standard_kind(code: str) -> str:
    upper = (code or "").upper()
    for prefix in STANDARD_PREFIXES:
        if upper.startswith(prefix):
            return prefix
    return upper[:2]


def find_alternatives(entry: PaintEntry,
                      db: PaintDatabase,
                      limit: int = 4,
                      tolerance: float = 3.0,
                      formula: str = "CIEDE2000",
                      same_brand: bool = False,
                      brand_scope: Optional[Sequence[str]] = None,
                      exclude: Optional[Sequence[str]] = None) -> List[Alternative]:
    """找出 ``entry`` 的替代色号。

    ``same_brand=False``（默认）时排除同品牌的其它色号 —— 用户要的是
    「买不到 A 牌时买哪个牌」。    ``exclude`` 给出额外要排除的色号 uid（例如当前
    配方里已经用到的组分），避免把配方自身组分当成「替代色号」又列一遍。
    """
    if entry is None:
        # 调用方可能在清空选择后调用（例如 UI 取消选中），不应崩溃。
        return []
    results: List[Alternative] = []
    seen: set = {entry.uid}
    if exclude:
        seen.update(exclude)

    # 1) 标准色号一致
    for standard in entry.standards:
        for candidate in db.by_standard(standard):
            if candidate.uid in seen:
                continue
            if not same_brand and candidate.brand_key == entry.brand_key:
                continue
            if brand_scope and candidate.brand_key not in brand_scope:
                continue
            seen.add(candidate.uid)
            results.append(Alternative(
                paint=candidate,
                reason=f"同为 {standard} 标准色",
                delta_e=delta_e(entry.lab, candidate.lab, formula),
                shared_standard=standard,
                evidence="standard",
            ))

    # 2) 跨品牌最近色
    remaining = max(0, limit - len(results))
    if remaining:
        pool = db.by_brands(brand_scope) if brand_scope else db.entries
        for value, candidate in _nearest(entry, pool, seen, same_brand,
                                         formula, tolerance, remaining):
            seen.add(candidate.uid)
            results.append(Alternative(
                paint=candidate,
                reason=f"色差 ΔE {value:.1f}，跨品牌最接近",
                delta_e=value,
                evidence="nearest",
            ))

    results.sort(key=lambda alt: (0 if alt.shared_standard else 1, alt.delta_e))
    return results[: max(0, limit)]


def _nearest(entry: PaintEntry, pool, seen: set, same_brand: bool,
             formula: str, tolerance: float, limit: int) -> List[tuple]:
    """跨品牌最近色的候选排序（证据强度低于「同标准色号」）。"""
    distance: List[tuple] = []
    for candidate in pool:
        if candidate.uid in seen:
            continue
        if not same_brand and candidate.brand_key == entry.brand_key:
            continue
        value = delta_e(entry.lab, candidate.lab, formula)
        if value <= tolerance:
            distance.append((value, candidate))
    distance.sort(key=lambda item: item[0])
    return distance[:limit]


def find_same_standard(entry: PaintEntry, db: PaintDatabase) -> List[PaintEntry]:
    """列出所有与 ``entry`` 共享标准色号的色号（含同品牌，供对照表使用）。"""
    out: List[PaintEntry] = []
    seen: set = set()
    for standard in entry.standards:
        for candidate in db.by_standard(standard):
            if candidate.uid not in seen:
                seen.add(candidate.uid)
                out.append(candidate)
    return out
