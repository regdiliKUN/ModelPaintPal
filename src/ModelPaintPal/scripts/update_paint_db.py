# -*- coding: utf-8 -*-
"""色号库更新 diff（维护侧工具，不进运行时）。

    python scripts/update_paint_db.py --emit-template      # 生成候选文件模板
    python scripts/update_paint_db.py --from candidates.json
    python scripts/update_paint_db.py --from candidates.json --write patch.json

为什么不做成「运行时联网更新」
------------------------------
色号目录是慢变数据，一年也未必动一次。把它做成启动时联网，等于让每个用户每次
开软件都为一件大概率无事发生的事等一次网络。更糟的是：**自动入库**意味着一条
解析错的数据会静默写进所有人的色号库。

所以这里的定位是维护者手动跑的脚本：

1. 拿到一份候选数据（人工整理或从厂家目录导出）；
2. 与本地库 diff，分成「新增 / 变更 / 一致 / 待确认」四类；
3. **默认只输出报告**；确认无误后 ``--write`` 也只是写出补丁文件，
   由人审阅后再合并进 ``paint_seed.py`` / ``sources.ENTRY_SOURCES``。

脚本不内置任何抓取端点 —— 各品牌官网结构各异，还有 Cloudflare 拦截，
凭空写几个 URL 抓不到是常态，还会让人误以为在正常工作。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.color_models import hex_to_rgb, rgb_to_lab          # noqa: E402
from app.core.delta_e import delta_e                              # noqa: E402
from app.data.brands import BRANDS                                # noqa: E402
from app.data.paint_db import get_database                        # noqa: E402
from app.data.sources import SOURCE_KINDS, SOURCES                # noqa: E402

# 超过这个色差才算「真的变了」，否则只是取色误差 / 显示器差异
CHANGE_DE = 2.0
# 超过这个色差就要人工确认：这么大的差异多半是抓错了
REVIEW_DE = 12.0

_TEMPLATE = [
    {
        "brand": "tamiya",
        "code": "X-7",
        "name": "亮光红",
        "name_en": "Red",
        "hex": "#C8102E",
        "src_kind": "official",
        "src_ref": "S:tamiya-official",
        "src_date": "2026-10",
    }
]


@dataclass
class Diff:
    added: List[dict] = field(default_factory=list)
    changed: List[dict] = field(default_factory=list)
    review: List[dict] = field(default_factory=list)
    unchanged: int = 0
    skipped: List[str] = field(default_factory=list)


def _load_candidates(path: Path) -> List[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("candidates") or data.get("items") or []
    if not isinstance(data, list):
        raise ValueError("候选文件必须是数组，或含 candidates/items 字段的对象")
    return [item for item in data if isinstance(item, dict)]


def _validate(item: dict, index: int) -> Optional[str]:
    """返回错误原因；合法返回 None。"""
    if not item.get("brand") or not item.get("code"):
        return f"#{index} 缺少 brand / code"
    if item.get("brand") not in BRANDS:
        return f"#{index} 未知品牌: {item.get('brand')}"
    kind = item.get("src_kind") or "official"
    if kind not in SOURCE_KINDS:
        return f"#{index} 未知 src_kind: {kind}"
    ref = item.get("src_ref") or ""
    if kind != "derived" and ref and ref not in SOURCES:
        # 反编造：和 check_paint_db 同一条规矩
        return f"#{index} 引用了不存在的来源: {ref}"
    try:
        hex_to_rgb(item.get("hex", ""))
    except (ValueError, TypeError):
        return f"#{index} 非法 hex: {item.get('hex')}"
    return None


def diff_candidates(candidates: List[dict]) -> Diff:
    db = get_database()
    result = Diff()
    for index, item in enumerate(candidates):
        reason = _validate(item, index)
        if reason:
            result.skipped.append(reason)
            continue
        uid = f"{item['brand']}:{item['code']}"
        entry = db.get(uid)
        if entry is None:
            result.added.append(item)
            continue
        gap = delta_e(entry.lab, rgb_to_lab(hex_to_rgb(item["hex"])), "CIEDE2000")
        if gap <= CHANGE_DE:
            result.unchanged += 1
            continue
        record = {**item, "uid": uid, "old_hex": entry.hex, "delta_e": round(gap, 2)}
        if gap >= REVIEW_DE:
            result.review.append(record)
        else:
            result.changed.append(record)
    return result


def _report(result: Diff) -> None:
    print(f"新增    ：{len(result.added)} 条")
    print(f"变更    ：{len(result.changed)} 条")
    print(f"待确认  ：{len(result.review)} 条（色差 ≥ {REVIEW_DE}，多半抓错了）")
    print(f"一致    ：{result.unchanged} 条")
    if result.skipped:
        print(f"跳过    ：{len(result.skipped)} 条")
        for line in result.skipped[:20]:
            print("  -", line)
    for item in result.review[:10]:
        print(f"  ! {item['uid']}: 本地 {item['old_hex']} → 候选 {item['hex']}"
              f"（ΔE {item['delta_e']}）需人工确认")


def main() -> int:
    parser = argparse.ArgumentParser(description="色号库更新 diff")
    parser.add_argument("--from", dest="source", help="候选数据 JSON 文件")
    parser.add_argument("--write", dest="out", help="写出补丁文件（不自动入库）")
    parser.add_argument("--emit-template", action="store_true",
                        help="生成候选文件模板 candidates.example.json")
    args = parser.parse_args()

    if args.emit_template:
        target = PROJECT_ROOT / "scripts" / "candidates.example.json"
        target.write_text(json.dumps(_TEMPLATE, ensure_ascii=False, indent=2),
                          encoding="utf-8")
        print(f"已写出模板：{target}")
        return 0

    if not args.source:
        parser.error("需要 --from <候选文件>，或 --emit-template 生成模板")

    result = diff_candidates(_load_candidates(Path(args.source)))
    _report(result)

    if args.out:
        payload = {
            "added": result.added,
            "changed": result.changed,
            "review": result.review,
        }
        Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
        print(f"\n补丁已写出：{args.out}（需人工审阅后再合并，脚本不会自动改种子库）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
