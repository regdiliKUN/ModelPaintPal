# -*- coding: utf-8 -*-
"""代码质量与交互性能度量（优化前后对比用）。

    python scripts/quality_metrics.py            # 打印当前指标
    python scripts/quality_metrics.py --json     # 输出 JSON（便于存档对比）

度量口径刻意选成「可被机器重复计算」的客观指标，避免主观描述：

* ``max_func_lines``   最长函数行数（含装饰器、不含空行）
* ``funcs_over_60``    超过 60 行的函数个数
* ``inline_style``     内联 ``setStyleSheet`` 调用次数（样式重复的直接来源）
* ``manual_hex``       手写 ``"#%02X%02X%02X"`` 格式化次数（格式化逻辑重复）
* ``dup_line_ratio``   重复非空代码行占比（同一行在 ≥2 处出现即算重复）
* ``total_lines``      应用代码总行数
* ``window_build_ms``  主窗口构造耗时
* ``render_ms``        一次建议渲染耗时（6 条卡片）
* ``suggest_ms``       一次配色建议计算耗时
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

APP_DIR = ROOT / "app"

_TRIVIAL = re.compile(
    r"^\s*(from |import |#|\"\"\"|'''|\)|\]|\}|else:|try:|pass$|return$|super\(\))"
)


def _iter_sources():
    for path in sorted(APP_DIR.rglob("*.py")):
        yield path, path.read_text(encoding="utf-8")


def _func_lines(path: Path, tree: ast.AST):
    """产出 (函数名, 起始行, 结束行)。"""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end = getattr(node, "end_lineno", node.lineno)
            yield f"{path.relative_to(ROOT)}::{node.name}", node.lineno, end


def static_metrics() -> dict:
    total_lines = 0
    funcs = []
    inline_style = 0
    manual_hex = 0
    dup_counter: dict[str, int] = {}

    for path, text in _iter_sources():
        lines = text.splitlines()
        total_lines += len(lines)
        inline_style += len(re.findall(r"setStyleSheet\(", text))
        manual_hex += len(re.findall(r'"#%02X%02X%02X"', text))
        try:
            tree = ast.parse(text)
        except SyntaxError:  # pragma: no cover
            continue
        for name, start, end in _func_lines(path, tree):
            body = [ln for ln in lines[start - 1:end] if ln.strip()]
            funcs.append((name, len(body)))
        for line in lines:
            stripped = line.strip()
            if len(stripped) < 12 or _TRIVIAL.match(line):
                continue
            dup_counter[stripped] = dup_counter.get(stripped, 0) + 1

    dup_lines = sum(count for count in dup_counter.values() if count > 1)
    counted = sum(dup_counter.values())
    funcs.sort(key=lambda item: item[1], reverse=True)
    return {
        "total_lines": total_lines,
        "func_count": len(funcs),
        "max_func_lines": funcs[0][1] if funcs else 0,
        "max_func_name": funcs[0][0] if funcs else "",
        "funcs_over_60": sum(1 for _, size in funcs if size > 60),
        "inline_style": inline_style,
        "manual_hex": manual_hex,
        "dup_line_ratio": round(dup_lines / counted, 4) if counted else 0.0,
        "top_funcs": funcs[:6],
    }


def runtime_metrics(samples: int = 3) -> dict:
    from PySide6.QtWidgets import QApplication

    from app.core.config import AppConfig
    from app.data.paint_db import get_database
    from app.services.paint_matcher import PaintMatcher
    from app.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    config = AppConfig()
    config.show_onboarding = False
    config.auto_copy_on_pick = False

    builds, renders = [], []
    for _ in range(samples):
        t0 = time.perf_counter()
        window = MainWindow(config)
        window.show()
        app.processEvents()
        builds.append((time.perf_counter() - t0) * 1000.0)

        window._apply_color((120, 96, 72), source="bench", remember=False)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not window._suggestions:
            app.processEvents()
            time.sleep(0.005)
        t1 = time.perf_counter()
        window._render_suggestions()
        app.processEvents()
        renders.append((time.perf_counter() - t1) * 1000.0)
        window.close()
        window.deleteLater()
        app.processEvents()

    matcher = PaintMatcher(get_database())
    costs = []
    for rgb in [(120, 96, 72), (199, 31, 28), (76, 76, 76)]:
        t0 = time.perf_counter()
        matcher.suggest(rgb, config)
        costs.append((time.perf_counter() - t0) * 1000.0)

    return {
        "window_build_ms": round(statistics.median(builds), 1),
        "render_ms": round(statistics.median(renders), 1),
        "suggest_ms": round(statistics.median(costs), 1),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-runtime", action="store_true")
    args = parser.parse_args()

    data = static_metrics()
    if not args.no_runtime:
        data.update(runtime_metrics())
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    print("== 静态指标 ==")
    print(f"应用代码总行数        : {data['total_lines']}")
    print(f"函数总数              : {data['func_count']}")
    print(f"最长函数              : {data['max_func_lines']} 行  ({data['max_func_name']})")
    print(f"超过 60 行的函数      : {data['funcs_over_60']}")
    print(f"内联 setStyleSheet    : {data['inline_style']} 处")
    print(f"手写 HEX 格式化       : {data['manual_hex']} 处")
    print(f"重复代码行占比        : {data['dup_line_ratio'] * 100:.2f}%")
    if not args.no_runtime:
        print("== 运行时指标 ==")
        print(f"主窗口构造            : {data['window_build_ms']} ms")
        print(f"一次建议渲染          : {data['render_ms']} ms")
        print(f"一次建议计算          : {data['suggest_ms']} ms")
    print("== 最长的几个函数 ==")
    for name, size in data["top_funcs"]:
        print(f"  {size:4d} 行  {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
