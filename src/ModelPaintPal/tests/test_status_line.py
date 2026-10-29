# -*- coding: utf-8 -*-
"""共享状态行 ``StatusLine`` 的行为。

两个面板（配色建议 / 基础配色）此前各自复制了一份「计算中」逻辑，还各自维护一个
只写不读的 ``_busy`` 字段。合并成一个控件之后，这里把它的状态机钉死：忙碌不能
吞掉空闲文案、清空之后不能把旧文案闪回来。
"""

import os
import sys
import unittest
from pathlib import Path

from tests import qt_cleanup

qt_cleanup.install()

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.ui.widgets.status_line import StatusLine  # noqa: E402


def _app() -> QApplication:
    existing = QApplication.instance()
    if existing is not None:
        if not isinstance(existing, QApplication):
            raise AssertionError("进程内已存在 QCoreApplication，无法创建 QApplication")
        return existing
    return QApplication([])


class StatusLineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        self.line = StatusLine()

    def test_busy_then_idle_restores_previous_text(self):
        """忙碌态结束后要回到上一次的空闲文案，而不是留一个空标签。"""
        self.line.set_idle("6 条建议 · 色号库 672 色")
        self.line.set_busy(True)
        self.assertEqual(self.line.text(), "计算中…")
        self.assertTrue(self.line.is_busy)
        self.line.set_busy(False)
        self.assertEqual(self.line.text(), "6 条建议 · 色号库 672 色")
        self.assertFalse(self.line.is_busy)

    def test_busy_does_not_erase_idle_text(self):
        self.line.set_idle("甲")
        self.line.set_busy(True)
        self.line.set_busy(False)
        self.assertEqual(self.line.text(), "甲")

    def test_clear_text_forgets_idle_text(self):
        """切到空状态后，忙碌结束不该把旧文案闪回来。"""
        self.line.set_idle("甲")
        self.line.clear_text()
        self.assertEqual(self.line.text(), "")
        self.line.set_busy(True)
        self.line.set_busy(False)
        self.assertEqual(self.line.text(), "")

    def test_set_idle_clears_busy(self):
        """设置空闲文案本身就是一次「算完了」，应同时退出忙碌态。"""
        self.line.set_busy(True)
        self.line.set_idle("乙")
        self.assertFalse(self.line.is_busy)
        self.assertEqual(self.line.text(), "乙")

    def test_idle_state_is_dimmed(self):
        """空闲态用弱化色，忙碌态用强调色——两者的内联样式必须真的不同。"""
        self.line.set_idle("甲")
        idle_style = self.line.styleSheet()
        self.line.set_busy(True)
        self.assertNotEqual(idle_style, self.line.styleSheet())


if __name__ == "__main__":
    unittest.main()
