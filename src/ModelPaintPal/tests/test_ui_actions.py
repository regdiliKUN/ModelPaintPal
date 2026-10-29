# -*- coding: utf-8 -*-
"""主窗口的叶子动作（导出 / 分享 / 关于）。

这些动作从 `main_window` 搬到 `ui/actions.py` 之后，用鸭子类型的假窗口就能测——
不必造 QWidget。测的是「没有取色时的分支」「导出类型映射」「写盘失败要说出来」
这几条容易在搬家过程中悄悄改坏的行为。
"""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.core.color_models import ColorSample  # noqa: E402
from app.ui import actions  # noqa: E402


class _FakeWindow:
    """只提供 actions 真正用到的那几个成员。"""

    def __init__(self, sample=None, suggestions=None, report="{}"):
        self.sample = sample
        self.suggestions = suggestions or []
        self._report = report

    def export_report(self) -> str:
        return self._report


class ExportActionTest(unittest.TestCase):
    def setUp(self):
        self.saved = []
        self.toasts = []
        patcher = patch.object(actions, "save_text",
                               side_effect=lambda w, t, n, p: self.saved.append((t, n, p)))
        self.addCleanup(patcher.stop)
        patcher.start()
        toast_patcher = patch.object(actions, "show_toast",
                                     side_effect=lambda w, m, kind="info", ms=0: self.toasts.append((m, kind)))
        self.addCleanup(toast_patcher.stop)
        toast_patcher.start()

    def test_json_export_works_without_sample(self):
        """JSON 导出走 export_report()，没取色时也应有内容（空对象），不该弹警告。"""
        window = _FakeWindow(report='{"suggestions": []}')
        actions.export_suggestions(window, "json")
        self.assertEqual(len(self.saved), 1)
        text, name, pattern = self.saved[0]
        self.assertEqual(text, '{"suggestions": []}')
        self.assertEqual(name, "配色建议.json")
        self.assertIn("*.json", pattern)
        self.assertEqual(self.toasts, [])

    def test_markdown_export_needs_a_sample(self):
        window = _FakeWindow(sample=None)
        actions.export_suggestions(window, "markdown")
        self.assertEqual(self.saved, [])
        self.assertEqual(self.toasts[-1][1], "warn")

    def test_csv_export_uses_current_sample_and_suggestions(self):
        sample = ColorSample.from_rgb((120, 96, 72), source="test")
        window = _FakeWindow(sample=sample)
        actions.export_suggestions(window, "csv")
        self.assertEqual(len(self.saved), 1)
        _, name, pattern = self.saved[0]
        self.assertEqual(name, "配色建议.csv")
        self.assertIn("*.csv", pattern)

    def test_unknown_kind_is_ignored(self):
        window = _FakeWindow(sample=ColorSample.from_rgb((1, 2, 3)))
        actions.export_suggestions(window, "xml")
        self.assertEqual(self.saved, [])

    def test_share_text_without_sample_warns(self):
        copied = []
        with patch.object(actions, "copy_to_clipboard", side_effect=copied.append):
            actions.copy_share_text(_FakeWindow(sample=None))
        self.assertEqual(copied, [])
        self.assertEqual(self.toasts[-1][1], "warn")

    def test_share_text_copies_when_sample_exists(self):
        copied = []
        window = _FakeWindow(sample=ColorSample.from_rgb((120, 96, 72)))
        def _copy(text):
            copied.append(text)
            return True

        with patch.object(actions, "copy_to_clipboard", side_effect=_copy):
            actions.copy_share_text(window)
        self.assertEqual(len(copied), 1)
        self.assertIn("#786048", copied[0])
        self.assertEqual(self.toasts[-1][1], "success")


class SaveTextTest(unittest.TestCase):
    def test_write_failure_is_reported(self):
        """写盘失败（只读目录/权限）要弹错误，不能静默吞掉。"""
        toasts = []
        with patch("PySide6.QtWidgets.QFileDialog.getSaveFileName",
                   return_value=("Z:/definitely/not/here/x.json", "")):
            with patch.object(actions, "show_toast",
                              side_effect=lambda w, m, kind="info", ms=0: toasts.append((m, kind))):
                actions.save_text(_FakeWindow(), "{}", "x.json", "JSON 文件 (*.json)")
        self.assertEqual(len(toasts), 1)
        self.assertEqual(toasts[0][1], "error")

    def test_cancelled_dialog_writes_nothing(self):
        toasts = []
        with patch("PySide6.QtWidgets.QFileDialog.getSaveFileName", return_value=("", "")):
            with patch.object(actions, "show_toast",
                              side_effect=lambda w, m, kind="info", ms=0: toasts.append((m, kind))):
                actions.save_text(_FakeWindow(), "{}", "x.json", "JSON 文件 (*.json)")
        self.assertEqual(toasts, [])


if __name__ == "__main__":
    unittest.main()
