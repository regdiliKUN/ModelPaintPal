# -*- coding: utf-8 -*-
"""把一条建议翻译成"可渲染的视图模型"（色卡 / 色盘标记 / 图例）。

为什么单独一层：建议卡片和色卡对比页要展示**同一批颜色**，而且必须使用**同一套编号**，
否则卡片上写 ③、色盘上是 ②，用户对不上。以前两边各写一遍组装逻辑，编号和顺序
迟早会漂移；现在只有这一处定义。
"""

from __future__ import annotations

from typing import List, Sequence, Tuple

from ..core.color_models import rgb_to_hex
from ..core.delta_e import delta_e_rgb, format_delta_e
from ..services.paint_matcher import PaintSuggestion
from .widgets.color_wheel import WheelMarker
from .widgets.swatch_card import SwatchItem, index_badge

__all__ = ["build_swatches", "build_markers", "build_legend", "MAX_ALTERNATIVES"]

MAX_ALTERNATIVES = 3


def _de(target_rgb: Sequence[int], rgb: Sequence[int], formula: str = "CIEDE2000") -> float:
    return delta_e_rgb(target_rgb, rgb, formula)


def build_swatches(suggestion: PaintSuggestion,
                   target_rgb: Sequence[int],
                   include_alternatives: bool = True,
                   formula: str = "CIEDE2000") -> List[SwatchItem]:
    """按「目标 → 混合 → 组分 → 替代」的顺序生成带编号的色卡项。"""
    items: List[SwatchItem] = [
        SwatchItem(target_rgb, "目标色", "吸取值", index=1),
    ]
    if not suggestion.is_direct:
        items.append(SwatchItem(
            suggestion.recipe.mixed_rgb, "混合结果",
            format_delta_e(suggestion.delta_e), index=2,
            delta_e=suggestion.delta_e,
        ))

    for comp in suggestion.recipe.components:
        items.append(SwatchItem(
            comp.paint.rgb, comp.paint.code,
            f"{comp.drops} 滴 · {comp.percent_label}",
            uid=comp.paint.uid,
            index=len(items) + 1,
            delta_e=_de(target_rgb, comp.paint.rgb, formula),
        ))

    if include_alternatives:
        for alt in suggestion.alternatives[:MAX_ALTERNATIVES]:
            note = (f"替代 · 同 {alt.shared_standard}" if alt.shared_standard
                    else f"替代 · {alt.paint.brand_label}")
            items.append(SwatchItem(
                alt.paint.rgb, alt.paint.code, note,
                uid=alt.paint.uid,
                index=len(items) + 1,
                delta_e=alt.delta_e,
            ))
    return items


def build_markers(suggestion: PaintSuggestion,
                  target_rgb: Sequence[int]) -> List[WheelMarker]:
    """与 :func:`build_swatches` 编号一致的色盘标记。"""
    markers: List[WheelMarker] = [
        WheelMarker(target_rgb, "目标色", emphasis=True, index=1),
    ]
    if not suggestion.is_direct:
        markers.append(WheelMarker(suggestion.recipe.mixed_rgb, "混合结果", index=2))
    for comp in suggestion.recipe.components:
        markers.append(WheelMarker(comp.paint.rgb, comp.paint.code, index=len(markers) + 1))
    for alt in suggestion.alternatives[:MAX_ALTERNATIVES]:
        markers.append(WheelMarker(alt.paint.rgb, alt.paint.code, index=len(markers) + 1))
    return markers


def build_legend(suggestion: PaintSuggestion,
                 target_rgb: Sequence[int]) -> List[str]:
    """与色卡编号一一对应的图例文本。"""
    lines = [f"{index_badge(1)} 目标色 {rgb_to_hex(target_rgb)}"]
    if not suggestion.is_direct:
        lines.append(f"{index_badge(2)} 混合结果 {suggestion.recipe.mixed_hex}"
                     f"（{format_delta_e(suggestion.delta_e)}）")
    for comp in suggestion.recipe.components:
        lines.append(f"{index_badge(len(lines) + 1)} {comp.paint.brand_label} "
                     f"{comp.paint.code} {comp.paint.name} · {comp.drops} 滴")
    for alt in suggestion.alternatives[:MAX_ALTERNATIVES]:
        lines.append(f"{index_badge(len(lines) + 1)} 替代 {alt.paint.brand_label} "
                     f"{alt.paint.code} {alt.paint.name}")
    return lines


def split_pair(suggestion: PaintSuggestion,
               target_rgb: Sequence[int]) -> Tuple[Sequence[int], Sequence[int], str]:
    """给「分割对比」用的两个颜色与右侧标签。"""
    if suggestion.is_direct:
        label = "直接瓶用色号" if suggestion.is_within_tolerance else "单色近似色号"
        return target_rgb, suggestion.recipe.components[0].paint.rgb, label
    return target_rgb, suggestion.recipe.mixed_rgb, "混合结果"
