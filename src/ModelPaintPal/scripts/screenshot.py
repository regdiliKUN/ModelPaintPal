# -*- coding: utf-8 -*-
"""离屏渲染界面截图（视觉回归 / 文档配图用）。

    python scripts/screenshot.py                # 输出到 build/screens/
    python scripts/screenshot.py --out docs/screenshots

不依赖显示器：用 Qt 的 offscreen 平台插件渲染，再 `QWidget.grab()` 取图。
改动界面后重跑一遍逐张核对，是发现「只有看图才发现」的问题的唯一办法。
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
# 注意：**不要**切到 offscreen 平台。Qt 的 offscreen 插件在 Windows 上拿不到系统字体
# （QFontDatabase.families() 返回 0），渲染出来全是方框，看不出任何排版问题。
# 改用真实平台 + WA_DontShowOnScreen：窗口完成布局与绘制，但不会真的弹到桌面上。
os.environ.pop("QT_QPA_PLATFORM", None)

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.core.config import AppConfig  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402

SHOTS = [
    # (文件名, 说明, 需要取色, 目标标签页, 窗口尺寸)
    ("10-empty.png", "空状态", False, 0, (1280, 860)),
    ("11-suggest.png", "配色建议", True, 0, (1280, 860)),
    ("12-visual.png", "色卡对比", True, 1, (1280, 860)),
    ("13-coverage.png", "用量参数", True, 2, (1280, 860)),
    ("14-settings.png", "设置", True, 3, (1280, 860)),
    ("15-onboarding.png", "新手引导", True, 0, (1280, 860)),
    ("16-narrow.png", "窄窗口 1024×720", True, 1, (1024, 720)),
    ("17-tall.png", "窄高窗口 900×1000", True, 0, (900, 1000)),
    ("18-tuner.png", "调色微调展开", True, 0, (1280, 860)),
    ("19-error.png", "输入错误提示", False, 0, (1280, 860)),
]


def _pump(app: QApplication, seconds: float = 0.6) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "build" / "screens"))
    parser.add_argument("--color", default="120,96,72")
    args = parser.parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    rgb = tuple(int(part) for part in args.color.split(","))

    app = QApplication.instance() or QApplication([])
    config = AppConfig()
    config.show_onboarding = False
    config.auto_copy_on_pick = False

    for name, caption, need_color, tab, (width, height) in SHOTS:
        window = MainWindow(config)
        window.setAttribute(Qt.WA_DontShowOnScreen, True)
        window.resize(width, height)
        window.show()
        _pump(app, 0.35)
        if need_color:
            window._apply_color(rgb, source="screenshot", remember=False)
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline and not window._suggestions:
                app.processEvents()
                time.sleep(0.01)
            window._render_suggestions()
        window._tabs.setCurrentIndex(tab)
        if name.startswith("15"):
            window._start_onboarding()
        if name.startswith("18"):
            window._pick_panel.tuner().expand(True)
        if name.startswith("19"):
            window._pick_panel._input.setText("这不是颜色")
            window._pick_panel._submit_manual()
        _pump(app, 0.7)
        path = out_dir / name
        window.grab().save(str(path))
        print(f"{caption:<16} -> {path}")
        window._onboarding.hide()
        window.close()
        window.deleteLater()
        _pump(app, 0.1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
