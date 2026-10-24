# -*- coding: utf-8 -*-
"""色号库自检（含溯源校验）。

    python scripts/check_paint_db.py

检查项：字段完整性、hex 合法性、色号重复、品牌存在性、标准色号覆盖率、
「同一品牌同色号不同 hex」这类数据打架，以及**来源可追溯性**。

两类结论分开处理：

* ``problems`` —— 直接失败（退出码 1）。来源引用不存在、未标注却自称官方，
  都属于这一类。**这是「不得编造来源」的机械保证。**
* ``warnings`` —— 只打印不阻断。来源过期、推定占比过高、跨品牌同标准色号
  色值打架，都是需要人看一眼的事，不该让 CI 红。
"""

from __future__ import annotations

import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.data.brands import BRANDS  # noqa: E402
from app.data.paint_db import get_database  # noqa: E402
from app.data.paint_seed import SEED_TABLES, FINISH_LABELS, OPACITY_LABELS  # noqa: E402
from app.data import sources as src_mod  # noqa: E402
from app.data.sources import SOURCES, SOURCE_KINDS, ENTRY_SOURCES  # noqa: E402
from app.core.delta_e import delta_e  # noqa: E402

_HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")

# 跨品牌声明同一个标准色号，但色值差到这个程度，就认为数据打架
STANDARD_CONFLICT_DE = 12.0
# 推定条目占比超过这个比例要报警
DERIVED_RATIO_WARN = 0.90


def _check_seed(problems: list, warnings: list) -> Counter:
    """校验种子表本身。返回来源 ID 使用计数（供孤儿检测用）。"""
    used_source_ids: Counter = Counter()

    for brand_key, rows in SEED_TABLES.items():
        if brand_key not in BRANDS:
            problems.append(f"品牌未定义: {brand_key}")
        seen_codes: Counter = Counter()
        for row in rows:
            if len(row) not in (8, 12):
                problems.append(f"{brand_key} 字段数不为 8 或 12: {row}")
                continue
            code, name, name_en, hex_value, finish, opacity, standards, note = row[:8]
            seen_codes[code] += 1
            if not _HEX_RE.match(hex_value or ""):
                problems.append(f"{brand_key}:{code} 非法 hex: {hex_value}")
            if not name and not name_en:
                problems.append(f"{brand_key}:{code} 缺少名称")
            if finish not in FINISH_LABELS:
                problems.append(f"{brand_key}:{code} 未知 finish: {finish}")
            if opacity not in OPACITY_LABELS:
                problems.append(f"{brand_key}:{code} 未知 opacity: {opacity}")

            # ---- 溯源：行内字段 ----
            if len(row) >= 12:
                src_kind, src_ref, src_date = row[8], row[9], row[10]
                if src_kind not in SOURCE_KINDS:
                    problems.append(
                        f"{brand_key}:{code} 未知 src_kind: {src_kind}")
                elif src_kind != "derived" and not src_ref:
                    # 反编造：自称官方/标准/第三方，却拿不出来源 ID
                    problems.append(
                        f"{brand_key}:{code} src_kind={src_kind} 但 src_ref 为空")
                if src_ref and src_ref not in SOURCES:
                    # 反编造：引用了注册表里不存在的来源
                    problems.append(
                        f"{brand_key}:{code} 引用了不存在的来源: {src_ref}")
                if src_ref:
                    used_source_ids[src_ref] += 1
                if src_date and not re.match(r"^\d{4}-\d{2}$", src_date):
                    problems.append(
                        f"{brand_key}:{code} src_date 格式应为 YYYY-MM: {src_date}")
        for code, count in seen_codes.items():
            if count > 1:
                problems.append(f"{brand_key}:{code} 重复 {count} 次")

    # ---- 溯源：逐条标注表 ----
    for uid, item in ENTRY_SOURCES.items():
        if not isinstance(item, (tuple, list)) or len(item) != 3:
            problems.append(f"ENTRY_SOURCES[{uid}] 必须是 (kind, ref, date) 三元组")
            continue
        kind, ref, date_text = item
        if kind not in SOURCE_KINDS:
            problems.append(f"ENTRY_SOURCES[{uid}] 未知 src_kind: {kind}")
        if ref and ref not in SOURCES:
            problems.append(f"ENTRY_SOURCES[{uid}] 引用了不存在的来源: {ref}")
        if ref:
            used_source_ids[ref] += 1

    orphans = src_mod.orphan_sources(used_source_ids.keys())
    if orphans:
        warnings.append("注册表中有来源未被任何色号引用（确认是否漏标）："
                        + "、".join(orphans))
    return used_source_ids


def _check_database(problems: list, warnings: list) -> None:
    db = get_database()
    print(f"色号总数：{len(db)}")
    print(f"品牌数  ：{len(db.brands)}")
    print("按品牌  ：" + ", ".join(f"{k}={v}" for k, v in db.count_by_brand().items()))

    with_standard = sum(1 for e in db.entries if e.standards)
    print(f"带标准色号的条目：{with_standard}（{with_standard / max(1, len(db)) * 100:.0f}%）")

    by_std: dict = defaultdict(set)
    for entry in db.entries:
        for std in entry.standards:
            by_std[std.upper()].add(entry.brand_key)
    multi = {k: v for k, v in by_std.items() if len(v) >= 2}
    print(f"可跨品牌互换的标准色：{len(multi)} 个（共 {len(by_std)} 个标准色号）")

    # ---- 多源冲突：同一标准色号，不同品牌给出的色值差太多 ----
    conflicts = 0
    entries_by_std: dict = defaultdict(list)
    for entry in db.entries:
        for std in entry.standards:
            entries_by_std[std.upper()].append(entry)
    for std, items in entries_by_std.items():
        if len(items) < 2:
            continue
        worst = 0.0
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                if items[i].brand_key == items[j].brand_key:
                    continue
                worst = max(worst, delta_e(items[i].lab, items[j].lab, "CIEDE2000"))
        if worst > STANDARD_CONFLICT_DE:
            conflicts += 1
            warnings.append(
                f"标准色号 {std} 在不同品牌间色值打架（最大 ΔE {worst:.1f}），"
                f"替代色号的同标准判定可能不可靠")
    print(f"跨品牌色值冲突的标准色号：{conflicts} 个")

    # ---- 溯源统计 ----
    by_kind: Counter = Counter(entry.src_kind for entry in db.entries)
    print("来源分布：" + "、".join(
        f"{src_mod.kind_label(k)}={n}" for k, n in sorted(
            by_kind.items(), key=lambda kv: src_mod.KIND_ORDER.index(kv[0])
            if kv[0] in src_mod.KIND_ORDER else 99)
    ))
    annotated = sum(1 for e in db.entries if e.is_annotated)
    print(f"已标注来源：{annotated} / {len(db)}"
          f"（{annotated / max(1, len(db)) * 100:.0f}%）")
    derived_ratio = (len(db) - annotated) / max(1, len(db))
    if derived_ratio > DERIVED_RATIO_WARN:
        warnings.append(
            f"未标注来源占比 {derived_ratio * 100:.0f}%，超过 {DERIVED_RATIO_WARN * 100:.0f}% "
            "——界面会大面积显示「未标注」，应继续补 ENTRY_SOURCES")
    stale = sum(1 for e in db.entries if e.is_stale)
    print(f"来源已过期的条目：{stale} 个")
    if stale:
        warnings.append(f"{stale} 条色号的来源数据已超过 "
                        f"{src_mod.STALE_MONTHS} 个月，界面应提示「数据可能过期」")

    # ---- 一致性：专有名词 ----
    for entry in db.entries:
        for std in entry.standards:
            if not any(std.upper().startswith(p)
                       for p in ("FS", "RAL", "RLM", "BS", "AMT", "4BO", "7K", "6K")):
                problems.append(f"{entry.uid} 标准色号前缀异常: {std}")


def main() -> int:
    problems: list = []
    warnings: list = []

    _check_seed(problems, warnings)
    _check_database(problems, warnings)

    if warnings:
        print("\n需要关注：")
        for item in warnings:
            print("  -", item)
    if problems:
        print("\n发现问题：")
        for item in problems:
            print("  -", item)
        return 1
    print("\n色号库自检通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
