# -*- coding: utf-8 -*-
"""UI 冒烟测试（offscreen）：窗口能建起来、取色后能渲染建议、导出/复制不崩。

这类测试不追求像素级校验，只兜住「改了底层逻辑导致界面炸掉」这种最贵的回归：
信号连接断开、渲染函数拿到空列表、导出函数签名变化等。
"""

import os
import sys
import time
import unittest
from tests import qt_cleanup
from pathlib import Path

qt_cleanup.install()

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.core.config import AppConfig  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402


def _app() -> QApplication:
    """整个进程只允许存在一个 QApplication。"""
    existing = QApplication.instance()
    if existing is not None:
        # 若别的测试模块先建了 QCoreApplication，这里拿到的是它而不是 QApplication，
        # 继续往下建 QWidget 会让 Qt 直接 abort。明确报错比无声崩溃好定位得多。
        if not isinstance(existing, QApplication):
            raise AssertionError(
                "进程内已存在 QCoreApplication，无法创建 QApplication；"
                "请检查其它测试模块是否抢先创建了它"
            )
        return existing
    return QApplication([])


class TestMainWindowSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        self.config = AppConfig()
        # 关掉自动复制，避免测试期间污染系统剪贴板
        self.config.auto_copy_on_pick = False
        self.window = MainWindow(self.config)

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def _wait_suggestions(self, timeout: float = 8.0) -> None:
        """UI 用后台线程算建议，跨线程信号要靠事件循环投递，这里手动转事件循环。"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.app.processEvents()
            if self.window._suggestions:
                return
            time.sleep(0.01)
        self.fail("等待配色建议超时（后台计算未返回）")

    def test_window_constructs(self):
        self.assertIn("3D 打印模型涂装配色助手", self.window.windowTitle())
        self.assertIsNone(self.window._sample)

    def test_apply_color_renders_suggestions(self):
        """取色后应算出建议并渲染，且目标色被记录下来。"""
        self.window._apply_color((120, 90, 60), source="test", remember=False)
        self._wait_suggestions()
        self.assertIsNotNone(self.window._sample)
        self.assertEqual(tuple(self.window._sample.rgb), (120, 90, 60))
        self.assertTrue(self.window._suggestions, "取色后应至少有一条建议")
        # 渲染过程不应抛错，且面板拿到的是同一批数据
        self.window._render_suggestions()

    def test_apply_color_extreme_values(self):
        """纯黑/纯白/越界值都不能让界面崩。"""
        for rgb in [(0, 0, 0), (255, 255, 255), (-5, 300, 128)]:
            with self.subTest(rgb=rgb):
                self.window._suggestions = []
                self.window._apply_color(rgb, source="test", remember=False)
                self._wait_suggestions()
                self.assertIsNotNone(self.window._sample)
                for channel in self.window._sample.rgb:
                    self.assertGreaterEqual(channel, 0)
                    self.assertLessEqual(channel, 255)

    def test_export_report_after_pick(self):
        """导出口径与 UI 一致：取色后能拿到完整报告文本。"""
        self.window._apply_color((90, 120, 60), source="test", remember=False)
        self._wait_suggestions()
        report = self.window.export_report()
        self.assertIsInstance(report, str)
        self.assertIn("suggestions", report)

    def test_share_text_action_without_sample_is_safe(self):
        """没取色时点分享：只提示，不崩。"""
        self.window._copy_share_text()  # 应走「还没有取色」分支

    def test_menu_contains_share_action(self):
        titles = []
        for action in self.window.menuBar().actions():
            menu = action.menu()
            if menu is not None:
                titles.extend(a.text() for a in menu.actions())
        self.assertIn("复制分享文本", titles)
        self.assertIn("导出建议为 CSV…", titles)


if __name__ == "__main__":
    unittest.main()
