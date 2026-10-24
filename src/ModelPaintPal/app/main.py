# -*- coding: utf-8 -*-
"""应用入口。

负责：高 DPI 声明 → 日志 → Qt 应用实例 → 主窗口 → 全局异常兜底。
"""

from __future__ import annotations

import sys
import traceback
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from .core.config import load_config
from .core.logging_setup import get_logger, setup_logging
from .core.screen_capture import set_dpi_aware
from .ui.main_window import MainWindow
from .ui.theme import stylesheet

logger = get_logger(__name__)

__all__ = ["main", "create_app"]


def create_app(argv: Optional[list] = None) -> QApplication:
    """创建 QApplication（含高 DPI 策略）。"""
    # 必须在 QApplication 构造前声明 DPI 感知，否则吸色坐标会偏移
    Qt.ApplicationAttribute
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(argv or sys.argv)
    app.setApplicationName("ModelPaintPal")
    from . import __version__

    app.setApplicationVersion(__version__)
    app.setApplicationDisplayName("3D 打印模型涂装配色助手")
    app.setOrganizationName("ModelPaintPal")
    app.setStyleSheet(stylesheet())
    return app


def _install_excepthook() -> None:
    """把未捕获异常记进日志并弹窗，避免窗口直接消失。"""
    def _hook(exc_type, exc_value, exc_tb):
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        logger.error("未捕获异常:\n%s", text)
        try:
            QMessageBox.critical(
                None, "程序异常",
                f"发生了未处理的异常：\n{exc_value}\n\n详细信息已写入日志。",
            )
        except Exception:  # pragma: no cover
            pass
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = _hook


def main(argv: Optional[list] = None) -> int:
    setup_logging()
    set_dpi_aware()
    app = create_app(argv)
    _install_excepthook()

    # 快捷方式由安装器或帮助菜单显式创建，启动时不写用户桌面。

    try:
        config = load_config()
    except Exception as exc:  # 配置损坏时回落到默认，保证能启动
        logger.error("配置加载失败，使用默认配置: %s", exc)
        from .core.config import AppConfig

        config = AppConfig()

    window = MainWindow(config)
    window.show()
    logger.info("主窗口已启动")
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
