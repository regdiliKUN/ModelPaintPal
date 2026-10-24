# -*- coding: utf-8 -*-
"""冒烟测试：离屏启动主窗口，走一遍核心链路。

    python scripts/smoke_test.py

不依赖显示器（使用 Qt offscreen 插件），适合 CI 与打包前自检。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _check(condition: bool, message: str, failures: list) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {message}")
    if not condition:
        failures.append(message)


def _pump_until(predicate, app, timeout: float = 10.0) -> bool:
    """转事件循环直到条件成立或超时（用于等待后台线程的结果回到主线程）。"""
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


def main() -> int:
    failures: list = []

    from PySide6.QtWidgets import QApplication

    from app.core.config import AppConfig
    from app.data.paint_db import get_database
    from app.services.paint_matcher import PaintMatcher
    from app.ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("ModelPaintPal")

    # 1) 数据库
    db = get_database()
    _check(len(db) >= 200, f"色号库条目 {len(db)} ≥ 200", failures)
    _check(len(db.brands) >= 5, f"品牌数 {len(db.brands)} ≥ 5", failures)

    # 2) 配色引擎
    config = AppConfig()
    matcher = PaintMatcher(db)
    suggestions = matcher.suggest((199, 31, 28), config)
    _check(bool(suggestions), "配色建议非空", failures)
    if suggestions:
        top = suggestions[0]
        _check(top.delta_e >= 0.0, f"ΔE 计算正常 ({top.delta_e:.2f})", failures)
        _check(bool(top.recipe.components), "配方含组分", failures)
        _check(top.coverage.paint_ml > 0, "用量估算 > 0", failures)

    # 3) 主窗口
    window = MainWindow(config)
    _check(window is not None, "主窗口构造成功", failures)
    window._apply_color((76, 76, 76), source="test", remember=True)
    _check(window._sample is not None, "取色后样本已设置", failures)
    # 界面走异步计算：需要转事件循环等后台结果回来（跨线程信号靠事件队列投递）
    _pump_until(lambda: bool(window._suggestions), app, timeout=10.0)
    _check(bool(window._suggestions), "取色后生成了建议", failures)
    _check(len(window._history.all()) >= 1, "历史记录已写入", failures)
    window._favorite_current()
    _check(len(window._favorites.all()) >= 1, "收藏夹已写入", failures)

    report = window.export_report()
    _check("suggestions" in report, "JSON 导出包含建议", failures)

    print("-" * 48)
    if failures:
        print(f"冒烟测试失败 {len(failures)} 项")
        return 1
    print("冒烟测试全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
