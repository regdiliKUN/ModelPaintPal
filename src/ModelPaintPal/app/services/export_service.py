# -*- coding: utf-8 -*-
"""配方导出：剪贴板文本 / Markdown / JSON。

所有导出都从 ``PaintSuggestion`` 生成，保证「界面看到的」和「复制出去的」一致。
"""

from __future__ import annotations

import csv
import io
import json
from typing import List, Sequence

from ..core.color_models import rgb_to_hex
from ..core.delta_e import format_delta_e
from ..core.logging_setup import get_logger
from .alternatives import Alternative
from .mixing import short_model_name
from .paint_matcher import PaintSuggestion
from .recipe_engine import Recipe, RecipeComponent

logger = get_logger(__name__)

__all__ = [
    "recipe_to_text",
    "recipe_to_markdown",
    "suggestion_to_markdown",
    "suggestions_to_json",
    "suggestions_to_csv",
    "suggestions_to_tsv",
    "suggestions_to_share_text",
    "alternatives_to_text",
]


def _md_cell(text: str) -> str:
    """把任意文本塞进 Markdown 表格单元格。

    竖线会把一行拆成两列、换行会把一行拆成两行——两者都会让整张表错位，
    而且错位是**静默**的：表格照样渲染，只是列对不上。当前色号库里没有这种
    字符，但这是数据，不是代码约束；导出是拿去别处用的，转义一次更省心。
    """
    return (str(text).replace("\\", "\\\\").replace("|", "\\|")
            .replace("\r\n", "<br>").replace("\n", "<br>").replace("\r", "<br>"))


def _one_line(text: str) -> str:
    """压成一行（用于列表项、分享文本这类不能有换行的位置）。"""
    return " ".join(str(text).split())


def _component_lines(recipe: Recipe) -> List[str]:
    lines = []
    for comp in recipe.components:
        brand = comp.paint.brand_label
        volume = f"{comp.paint.volume_ml:g}ml"
        lines.append(
            f"{brand} {comp.paint.code} 「{comp.paint.name}」 "
            f"({comp.paint.name_en}) — {comp.drops} 滴 / {comp.percent_label} / {volume}装"
        )
    return lines


def recipe_to_text(recipe: Recipe) -> str:
    lines = [f"调配方案（{short_model_name(recipe.model)} · "
             f"{format_delta_e(recipe.delta_e)} / {recipe.formula}）"]
    lines.append(f"混合色：{recipe.mixed_hex}")
    lines.append("配比：" + recipe.drops_text() + " 滴")
    lines.extend(_component_lines(recipe))
    return "\n".join(lines)


def recipe_to_markdown(recipe: Recipe) -> str:
    rows = ["| 品牌 | 色号 | 名称 | 滴数 | 百分比 |", "| --- | --- | --- | --- | --- |"]
    for comp in recipe.components:
        rows.append(
            f"| {_md_cell(comp.paint.brand_label)} | {_md_cell(comp.paint.code)} "
            f"| {_md_cell(comp.paint.name)} | {comp.drops} | {comp.percent_label} |"
        )
    return "\n".join(rows)


def alternatives_to_text(alts: Sequence[Alternative], limit: int = 3) -> str:
    if not alts:
        return "无替代色号"
    parts = []
    for alt in list(alts)[:limit]:
        # 两条证据链强度差很多：同标准色号是品牌官方标注，跨品牌最近色只是算出来
        # 的接近。导出文本里必须写清楚，否则转发到群里就变成等价推荐了。
        label = getattr(alt, "evidence_label", "")
        tail = f"·{label}" if label else ""
        parts.append(
            f"{alt.paint.brand_label} {alt.paint.code}（{alt.reason}{tail}）"
        )
    return "；".join(parts)


def _provenance_lines(suggestion: PaintSuggestion) -> List[str]:
    """给导出用的来源清单。分享到群里之后，别人也该能查到出处。"""
    prov = getattr(suggestion, "provenance", None)
    if prov is None:
        return []
    return list(prov.as_lines())


def suggestion_to_markdown(suggestion: PaintSuggestion, target_hex: str = "") -> str:
    head = (f"### 方案 {suggestion.rank}：{format_delta_e(suggestion.delta_e)}"
            f"（{suggestion.grade.label}）")
    if target_hex:
        head += f"  目标色 {target_hex}"
    body = [
        head,
        "",
        f"- 混合后色值：`{suggestion.recipe.mixed_hex}`",
        f"- 配比（滴）：{suggestion.recipe.drops_text()}",
        f"- 配比（%）：{suggestion.recipe.percent_text()}",
        "",
        recipe_to_markdown(suggestion.recipe),
        "",
        f"- 预估用量：{suggestion.coverage.as_text()}",
        f"- 各组分用量：{_component_amounts(suggestion)}",
        f"- 替代色号：{alternatives_to_text(suggestion.alternatives)}",
    ]
    if suggestion.notes:
        body.append("")
        body.extend(f"- 提示：{_one_line(note)}" for note in suggestion.notes)
    lines = _provenance_lines(suggestion)
    if lines:
        body.append("")
        body.append("- 来源：" + _one_line("；".join(lines)))
    return "\n".join(body)


def _component_amounts(suggestion: PaintSuggestion) -> str:
    """把「每支漆各要多少 ml」拼成一行，与界面上的用量芯片同源。"""
    parts = []
    for comp in suggestion.recipe.components:
        amount = suggestion.coverage.per_component_ml.get(comp.paint.uid)
        if amount:
            parts.append(f"{comp.paint.code} {amount:.2f} ml")
    return " · ".join(parts) if parts else "—"


def _component_to_dict(comp: RecipeComponent) -> dict:
    """所有JSON配方组分共享一套执行比例与来源字段。"""
    return {
        "brand": comp.paint.brand_key,
        "brand_label": comp.paint.brand_label,
        "code": comp.paint.code,
        "name": comp.paint.name,
        "name_en": comp.paint.name_en,
        "drops": comp.drops,
        "percent": round(comp.percent, 1),
        "hex": comp.paint.hex,
        "src_kind": comp.paint.src_kind,
        "src_ref": comp.paint.src_ref,
        "src_date": comp.paint.src_date,
        "confidence": comp.paint.confidence,
    }


def suggestions_to_json(suggestions: Sequence[PaintSuggestion],
                        target: Sequence[int]) -> str:
    payload = {
        "schema_version": 2,
        "ratio_basis": "integer_drops",
        "delta_e_kind": "predicted_swatch",
        "target": {
            "rgb": list(target),
            "hex": rgb_to_hex(target),
        },
        "suggestions": [],
    }
    for item in suggestions:
        payload["suggestions"].append({
            "rank": item.rank,
            "delta_e": round(item.delta_e, 3),
            "grade": item.grade.label,
            "mixed_hex": item.recipe.mixed_hex,
            "direct": item.is_direct,
            "mode": item.mode_label,
            "within_tolerance": item.is_within_tolerance,
            "tolerance": item.tolerance,
            "components": [_component_to_dict(comp) for comp in item.recipe.components],
            "coverage_ml": {
                "paint": item.coverage.paint_ml,
                "thinner": item.coverage.thinner_ml,
                "mix": item.coverage.mix_ml,
                "bottles": item.coverage.bottles,
                "per_component": dict(item.coverage.per_component_ml),
            },
            "alternatives": [
                {
                    "brand_label": alt.paint.brand_label,
                    "code": alt.paint.code,
                    "name": alt.paint.name,
                    "reason": alt.reason,
                    "evidence": getattr(alt, "evidence", "nearest"),
                    "delta_e": round(alt.delta_e, 2),
                }
                for alt in item.alternatives
            ],
            "notes": list(item.notes),
            "provenance": getattr(item, "provenance", None) and
                         item.provenance.to_dict(),
        })
    return json.dumps(payload, ensure_ascii=False, indent=2)


def suggestions_to_markdown(suggestions: Sequence[PaintSuggestion],
                            target: Sequence[int]) -> str:
    lines = [f"# 配色建议（目标色 {rgb_to_hex(target)}）", ""]
    for item in suggestions:
        lines.append(suggestion_to_markdown(item, rgb_to_hex(target)))
        lines.append("")
    return "\n".join(lines)


_TABLE_HEADER = [
    "rank", "target_hex", "mixed_hex", "delta_e", "grade", "direct",
    "components", "drops", "percent",
    "paint_ml", "thinner_ml", "mix_ml", "bottles",
    "alternatives", "notes",
    # 溯源列追加在末尾：旧脚本按列号取值不受影响，按列名取值多拿两列
    "confidence", "sources",
]


def _confidence_text(item: "PaintSuggestion") -> str:
    """导出用的置信度单元格。

    这里原本是一个 ``f"{prov and prov.confidence:.2f}" if prov else ""`` 的条件
    表达式：既难读，又会在「有 provenance 但 confidence 不是数字」时把
    ``TypeError`` 抛到导出流程里——用户点「导出 CSV」直接失败。缺失/异常一律
    输出空串，让表格列数保持稳定。
    """
    prov = getattr(item, "provenance", None)
    confidence = getattr(prov, "confidence", None)
    if not isinstance(confidence, (int, float)):
        return ""
    return f"{float(confidence):.2f}"


def _suggestion_row(item: "PaintSuggestion", target_hex: str) -> list:
    """把一条建议扁平化成一行字段（CSV 与 TSV 共用，保证两者列义完全一致）。"""
    recipe = item.recipe
    return [
        item.rank,
        target_hex,
        recipe.mixed_hex,
        f"{item.delta_e:.2f}",
        item.grade.label,
        "yes" if item.is_direct and item.is_within_tolerance else "no",
        " + ".join(c.paint.full_label for c in recipe.components),
        recipe.drops_text(),
        recipe.percent_text(),
        f"{item.coverage.paint_ml:.2f}",
        f"{item.coverage.thinner_ml:.2f}",
        f"{item.coverage.mix_ml:.2f}",
        f"{item.coverage.bottles:.2f}",
        alternatives_to_text(item.alternatives),
        " | ".join(item.notes),
        _confidence_text(item),
        " ".join(_provenance_lines(item)) or "—",
    ]


def _suggestions_to_table(suggestions: Sequence[PaintSuggestion],
                          target: Sequence[int], delimiter: str) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=delimiter)
    writer.writerow(_TABLE_HEADER)
    target_hex = rgb_to_hex(target)
    for item in suggestions:
        writer.writerow(_suggestion_row(item, target_hex))
    return buffer.getvalue()


def suggestions_to_csv(suggestions: Sequence[PaintSuggestion],
                       target: Sequence[int]) -> str:
    """导出为扁平 CSV（每行一条建议），方便在 Excel / 表格软件里二次处理。

    配方组分用「 + 」拼到单列，滴数/百分比同样合并，避免列数随组分数量漂移。
    """
    return _suggestions_to_table(suggestions, target, ",")


def suggestions_to_tsv(suggestions: Sequence[PaintSuggestion],
                       target: Sequence[int]) -> str:
    """导出为 TSV（制表符分隔）。

    与 CSV 列义完全一致，但字段内若含逗号/引号不会被再次转义，直接粘进
    Excel / WPS / 表格类工具时更干净；适合已经习惯「选中整列复制」的用户。
    """
    return _suggestions_to_table(suggestions, target, "\t")


def suggestions_to_share_text(suggestions: Sequence[PaintSuggestion],
                              target: Sequence[int],
                              limit: int = 2,
                              title: str = "") -> str:
    """生成可直接粘贴到论坛 / 群聊的纯文本配色卡。

    刻意不用 Markdown 表格：很多论坛和即时通讯只认纯文本，宽表格会错行。
    只保留「目标色 + 前 N 套配比 + 用量」，一行一个组分，短到能一屏看完。
    """
    target_hex = rgb_to_hex(target)
    lines: List[str] = []
    if title:
        lines.append(title)
        lines.append("")
    lines.append(f"目标色 {target_hex}  RGB{tuple(int(v) for v in target)}")
    if not suggestions:
        lines.append("（没有匹配到色号）")
        return "\n".join(lines)

    for item in list(suggestions)[: max(1, limit)]:
        recipe = item.recipe
        lines.append("")
        if item.is_direct:
            lines.append(f"方案 {item.rank}｜直接使用｜{format_delta_e(item.delta_e)}")
        else:
            lines.append(f"方案 {item.rank}｜{format_delta_e(item.delta_e)}（{item.grade.label}）")
        for comp in recipe.components:
            amount = item.coverage.per_component_ml.get(comp.paint.uid)
            tail = f" ≈{amount:.1f}ml" if amount else ""
            lines.append(
                f"  · {_one_line(comp.paint.brand_label)} {_one_line(comp.paint.code)} "
                f"{_one_line(comp.paint.name)} {comp.drops}滴（{comp.percent_label}）{tail}"
            )
        lines.append(f"  混合后 {recipe.mixed_hex}｜预估 {item.coverage.mix_ml:.2f}ml 混合漆")
        if item.alternatives:
            lines.append(f"  替代：{alternatives_to_text(item.alternatives, limit=2)}")
        prov_lines = _provenance_lines(item)
        if prov_lines:
            lines.append(f"  来源：{prov_lines[0]}")
            for extra in prov_lines[1:]:
                lines.append(f"        {extra}")

    lines.append("")
    lines.append("（ModelPaintPal 生成，色值为屏幕近似值，喷涂前请小量试喷）")
    return "\n".join(lines)


def copy_to_clipboard(text: str) -> bool:
    """写入系统剪贴板。失败返回 False，由调用方提示用户。"""
    try:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is None:
            return False
        app.clipboard().setText(text)
        return True
    except Exception as exc:  # pragma: no cover - 剪贴板不可用（远程桌面/权限）
        logger.debug("写入剪贴板失败: %s", exc)
        return False
