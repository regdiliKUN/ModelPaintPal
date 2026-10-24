# -*- coding: utf-8 -*-
"""来源聚合：把一条建议涉及的来源去重、排序、编号。

三条设计约束
------------

1. **编号必须可复现。**
   项目里 ``paint_db.by_brands()`` 刻意不用 ``set`` 迭代，因为哈希随机化会让
   候选顺序漂移。这里同理：编号按 ``(kind 权重, source_id)`` 排序得出，与传入
   顺序无关 —— 同一条建议在任何进程里都必须拿到同一组编号。

2. **推断不挂编号。**
   编号只发给「能被点开核实的来源」。配方比例、用量估算、跨品牌最近色都是算
   出来的，给它们编号会让用户以为点得开，点了却没有来源。这些走另一套视觉语言
   （虚线 chip + 「推算」）。

3. **未标注 ≠ 推定。**
   没有来源 ID 的条目记到 ``unannotated``，不参与编号，也不混进「推定」里。
   「来源不明」和「有人推过」是两回事，合并起来就是撒谎。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence

from ..data.paint_db import PaintEntry
from ..data.sources import KIND_ORDER, get_source, kind_label, is_fact_kind

__all__ = ["ProvenanceRef", "ProvenanceSummary", "build_provenance"]


def _kind_rank(kind: str) -> int:
    return KIND_ORDER.index(kind) if kind in KIND_ORDER else len(KIND_ORDER)


@dataclass(frozen=True)
class ProvenanceRef:
    """一条可点击的来源引用。"""

    index: int
    source_id: str
    name: str
    url: str
    kind: str
    kind_label: str
    date: str
    confidence: float
    is_fact: bool
    stale: bool

    def as_text(self) -> str:
        """给 Markdown / 分享文本用的一行。"""
        tail = f"（采集于 {self.date}）" if self.date else ""
        url = f" {self.url}" if self.url else ""
        return f"[{self.index}] {self.name}{tail}{url}"


@dataclass
class ProvenanceSummary:
    """一条建议的溯源总览。"""

    refs: List[ProvenanceRef] = field(default_factory=list)
    index_of: Dict[str, int] = field(default_factory=dict)   # uid -> 编号
    confidence: float = 1.0
    unannotated_count: int = 0
    derived_count: int = 0
    stale_count: int = 0
    calibrated: bool = False

    # ------------------------------------------------------------------ 查询
    def label_for(self, uid: str) -> str:
        """取该色号的引用角标文本；没有来源时返回空串（UI 据此不画角标）。"""
        index = self.index_of.get(uid)
        return f"[{index}]" if index else ""

    def cite_of(self, uid: str) -> str:
        """角标里显示的数字（不带方括号），供 UI 自绘小角标用。"""
        index = self.index_of.get(uid)
        return str(index) if index else ""

    @property
    def has_refs(self) -> bool:
        return bool(self.refs)

    @property
    def has_gap(self) -> bool:
        """是否存在来源缺口（未标注 / 推定 / 过期）。"""
        return bool(self.unannotated_count or self.derived_count or self.stale_count)

    def as_lines(self) -> List[str]:
        """给导出 / 剪贴板用的来源列表。"""
        lines = [ref.as_text() for ref in self.refs]
        if self.unannotated_count:
            lines.append(f"（另有 {self.unannotated_count} 个色号未登记来源，"
                         f"色值仅用于相对匹配）")
        if self.stale_count:
            lines.append(f"（{self.stale_count} 个来源已超过 24 个月，数据可能过期）")
        return lines

    def to_dict(self) -> dict:
        return {
            "confidence": round(self.confidence, 2),
            "calibrated": self.calibrated,
            "unannotated": self.unannotated_count,
            "derived": self.derived_count,
            "stale": self.stale_count,
            "refs": [
                {
                    "index": r.index, "id": r.source_id, "name": r.name,
                    "url": r.url, "kind": r.kind, "kind_label": r.kind_label,
                    "date": r.date, "confidence": r.confidence,
                    "is_fact": r.is_fact, "stale": r.stale,
                }
                for r in self.refs
            ],
        }


def build_provenance(entries: Iterable[Optional[PaintEntry]]) -> ProvenanceSummary:
    """把若干色号的来源聚合成一份带编号的溯源总览。

    传入顺序不影响编号结果（见模块文档第 1 条）。
    """
    items = [e for e in entries if e is not None]

    # 先按 uid 归拢「哪个色号引用了哪个来源」，再按 kind 权重 + id 排序。
    # 不用 set / dict 迭代来定序 —— 那会引入哈希随机化。
    pair_map: Dict[str, str] = {}          # uid -> source_id
    source_ids: List[str] = []             # 有序去重
    seen_sources: set = set()
    for entry in items:
        ref = entry.src_ref
        if ref and ref not in seen_sources:
            seen_sources.add(ref)
            source_ids.append(ref)
        if ref:
            pair_map[entry.uid] = ref

    source_ids.sort(key=lambda sid: (
        _kind_rank(get_source(sid).kind if get_source(sid) else "derived"),
        sid,
    ))

    refs: List[ProvenanceRef] = []
    index_of: Dict[str, int] = {}
    for number, sid in enumerate(source_ids, start=1):
        source = get_source(sid)
        if source is None:
            # 理论上到不了这里：check_paint_db 会拦住不存在的引用。
            # 但运行期不该因为脏数据崩掉，跳过即可（宁可少一个角标）。
            continue
        refs.append(ProvenanceRef(
            index=number,
            source_id=sid,
            name=source.name,
            url=source.url,
            kind=source.kind,
            kind_label=kind_label(source.kind),
            date=source.accessed,
            confidence=round(
                min((e.confidence or 0.0) for e in items
                    if e.src_ref == sid), 2),
            is_fact=is_fact_kind(source.kind),
            stale=source.accessed and any(
                e.is_stale for e in items if e.src_ref == sid),
        ))
    for uid, sid in pair_map.items():
        if sid in source_ids:
            index_of[uid] = source_ids.index(sid) + 1

    confidences = [float(e.confidence or 0.0) for e in items]
    unannotated = sum(1 for e in items if not e.is_annotated)
    derived = sum(1 for e in items if e.src_kind == "derived" and e.is_annotated)
    stale = sum(1 for e in items if e.is_stale)

    return ProvenanceSummary(
        refs=refs,
        index_of=index_of,
        confidence=round(min(confidences), 2) if confidences else 1.0,
        unannotated_count=unannotated,
        derived_count=derived,
        stale_count=stale,
        calibrated=any(e.src_kind == "calibrated" for e in items),
    )


def provenance_of(suggestion_entries: Sequence[PaintEntry],
                  alternatives: Iterable = ()) -> ProvenanceSummary:
    """一条建议的完整溯源：配方组分 + 替代色号。"""
    pool: List[PaintEntry] = list(suggestion_entries)
    for alt in alternatives or ():
        paint = getattr(alt, "paint", None)
        if paint is not None:
            pool.append(paint)
    return build_provenance(pool)
