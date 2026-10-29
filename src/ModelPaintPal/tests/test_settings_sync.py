# -*- coding: utf-8 -*-
"""「恢复默认设置」之后，依赖配置的界面必须跟着回到默认。

此前只重算建议，于是恢复默认之后：建议页仍用着旧的品牌范围、基础配色页的总滴数
还是旧值、配色方案页没回到「基础色盘」、历史/收藏上限也没生效——配置改了、界面
还停在旧状态，用户只能重启程序。
"""

import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from tests import qt_cleanup

qt_cleanup.install()

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.core.config import AppConfig  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402


def _app() -> QApplication:
    existing = QApplication.instance()
    if existing is not None:
        if not isinstance(existing, QApplication):
            raise AssertionError("进程内已存在 QCoreApplication，无法创建 QApplication")
        return existing
    return QApplication([])


class RestoreDefaultsSyncTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        patcher = patch("app.ui.main_window.save_config", return_value=True)
        self.addCleanup(patcher.stop)
        patcher.start()

        self.config = AppConfig()
        self.config.show_onboarding = False
        # 先设成一组「和默认明显不同」的值
        self.config.preferred_brands = ["humbrol"]
        self.config.mix_brands = ["humbrol"]
        self.config.drop_total = 60
        self.config.scheme_type = "analogous"
        self.config.scheme_param = 7
        self.config.validate()
        self.window = MainWindow(self.config)
        self.window.setAttribute(
            __import__("PySide6.QtCore", fromlist=["Qt"]).Qt.WA_DontShowOnScreen, True)
        self.window.show()
        for _ in range(20):
            self.app.processEvents()
            time.sleep(0.01)

    def tearDown(self):
        self.window._onboarding.hide()
        self.window.close()
        self.window.deleteLater()
        for _ in range(10):
            self.app.processEvents()
            time.sleep(0.01)

    def test_panels_follow_defaults(self):
        self.window._config.reset_to_defaults()
        self.window._config.validate()
        self.window._on_settings_changed()
        cfg = self.window._config

        self.assertEqual(self.window._brand_filter, cfg.preferred_brands)
        self.assertEqual(self.window._mix_brands, cfg.mix_brands)
        self.assertEqual(self.window._total_drops, cfg.drop_total)
        self.assertEqual(self.window._scheme_panel._total_drops, cfg.drop_total)
        self.assertEqual(self.window._plan_panel.scheme_type(), cfg.scheme_type)
        self.assertEqual(self.window._plan_panel.param(), cfg.scheme_param)

    def test_programmatic_brand_sync_does_not_look_like_user_action(self):
        """回填品牌下拉不应触发 brandChanged（否则会多写一次盘、多算一次配方）。"""
        emitted = []
        self.window._scheme_panel.brandChanged.connect(emitted.append)
        self.window._scheme_panel.set_brand(["tamiya"])
        self.assertEqual(emitted, [])


if __name__ == "__main__":
    unittest.main()
