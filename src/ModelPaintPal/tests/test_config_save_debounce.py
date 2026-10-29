# -*- coding: utf-8 -*-
"""配置落盘去抖。

`save_config` 是原子写 + fsync（实测 3.8 ms/次）。「用量参数」页每拖一格都会触发
`valueChanged`，50 格就是 190 ms 的主线程卡顿，而这些中间值没人要——真正要保存的
只有用户停手时的最终值。

这里测三件事：连续变更只落盘一次、停手后确实落了盘、关闭窗口不会丢配置。
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
from app.ui.main_window import _SAVE_DEBOUNCE_MS, MainWindow  # noqa: E402


def _app() -> QApplication:
    existing = QApplication.instance()
    if existing is not None:
        if not isinstance(existing, QApplication):
            raise AssertionError("进程内已存在 QCoreApplication，无法创建 QApplication")
        return existing
    return QApplication([])


def _pump(app: QApplication, seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)


def _wait_until(app: QApplication, predicate, timeout: float = 3.0) -> bool:
    """等到条件成立（而不是固定 sleep 一段时间）。

    固定 sleep 在机器忙的时候会偶发失败——整套测试跑过一次「1 failure」，
    重跑又全绿，就是这类等待写得不稳。等条件既更快也更可靠。
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


class ConfigSaveDebounceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()
        config = AppConfig()
        config.show_onboarding = False
        cls.config = config

    def setUp(self):
        self.saves = []
        patcher = patch("app.ui.main_window.save_config",
                        side_effect=lambda cfg: self.saves.append(cfg))
        self.addCleanup(patcher.stop)
        patcher.start()
        self.window = MainWindow(self.config)
        self.window.setAttribute(
            __import__("PySide6.QtCore", fromlist=["Qt"]).Qt.WA_DontShowOnScreen, True)

    def tearDown(self):
        self.window._onboarding.hide()
        self.window.deleteLater()
        _pump(self.app, 0.05)

    def test_rapid_changes_write_once(self):
        """连拖 30 格只应落盘一次（原来会写 30 次、每次 3.8 ms）。"""
        self.saves.clear()
        for _ in range(30):
            self.window._on_coverage_changed()
        self.assertEqual(self.saves, [], "去抖窗口内不应立刻落盘")
        self.assertTrue(_wait_until(self.app, lambda: len(self.saves) >= 1),
                        "停手后应落盘")
        self.assertEqual(len(self.saves), 1, "连拖 30 格只应落盘一次")

    def test_flush_writes_immediately(self):
        """关闭/离散操作走 flush，不依赖定时器。"""
        self.saves.clear()
        self.window._schedule_config_save()
        self.window._flush_config()
        self.assertEqual(len(self.saves), 1)

    def test_close_flushes_config(self):
        """关窗时必须把当前配置写下去，不能因为去抖还没到点就丢掉。"""
        self.saves.clear()
        self.window._config.area_m2 = 0.42
        self.window._on_coverage_changed()
        self.window.close()
        saved = [cfg for cfg in self.saves if abs(cfg.area_m2 - 0.42) < 1e-9]
        self.assertTrue(saved, "关窗时应把最新配置写盘")

    def test_debounce_is_shorter_than_user_patience(self):
        """去抖窗口不能长到让用户以为「设置没保存」。"""
        self.assertLessEqual(_SAVE_DEBOUNCE_MS, 1000)
        self.assertGreaterEqual(_SAVE_DEBOUNCE_MS, 200)


class SettingsPanelDebounceTest(unittest.TestCase):
    """设置页：数值控件只「请求落盘」，热键输入等停手再注册。

    热键输入框是 textChanged，逐字符触发。原来每敲一个键就写一次盘、并把
    Win32 热键注销重注册一次（要停线程），输 "Ctrl+Shift+X" 就是 12 次。
    """

    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        from app.ui.panels.settings_panel import SettingsPanel

        self.config = AppConfig()
        self.panel = SettingsPanel(self.config)
        self.persist, self.hotkeys, self.changed = [], [], []
        self.panel.persistRequested.connect(lambda: self.persist.append(1))
        self.panel.hotkeysChanged.connect(lambda: self.hotkeys.append(1))
        self.panel.settingsChanged.connect(lambda: self.changed.append(1))

    def tearDown(self):
        self.panel.deleteLater()
        _pump(self.app, 0.05)

    def test_spinbox_does_not_persist_directly(self):
        """改数值控件只发 persistRequested，不在这里写盘。"""
        self.persist.clear()
        self.panel._tolerance.setValue(1.5)
        self.assertGreaterEqual(len(self.persist), 1)
        _pump(self.app, 0.05)
        self.assertEqual(len(self.persist), 1, "一次改动应只请求一次落盘")

    def test_hotkey_typing_is_debounced(self):
        """逐字符输入只应在停手后触发一次热键重注册。"""
        self.hotkeys.clear()
        field = self.panel._pick_hotkey
        for text in ("C", "Ct", "Ctr", "Ctrl", "Ctrl+", "Ctrl+S", "Ctrl+Sh", "Ctrl+Shift+X"):
            field.setText(text)
        self.assertEqual(self.hotkeys, [], "输入过程中不应反复重注册热键")
        self.assertTrue(_wait_until(self.app, lambda: len(self.hotkeys) >= 1),
                        "停手后应重注册热键")
        self.assertEqual(len(self.hotkeys), 1, "停手后应只重注册一次")
        self.assertEqual(self.config.pick_hotkey, "Ctrl+Shift+X")


class SyncUnlockTest(unittest.TestCase):
    """``sync_from_config`` 中途失败也必须解锁。

    ``_updating`` 一旦卡在 True，用户在这个页面上的所有改动都会被 ``_commit``
    静默丢弃——界面还在，设置不再生效，而且没有任何提示。这类「锁没解开」的
    故障最难排查，所以用 try/finally 兜住，并在这里验证。
    """

    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def test_updating_flag_is_released_on_error(self):
        from app.ui.panels.settings_panel import SettingsPanel

        panel = SettingsPanel(AppConfig())
        try:
            panel._refresh_calibration = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
            with self.assertRaises(RuntimeError):
                panel.sync_from_config()
            self.assertFalse(panel._updating, "_updating 卡在 True，页面会静默失效")
        finally:
            panel.deleteLater()
            _pump(self.app, 0.05)

    def test_commit_still_works_after_failed_sync(self):
        from app.ui.panels.settings_panel import SettingsPanel

        panel = SettingsPanel(AppConfig())
        saved = []
        panel.persistRequested.connect(lambda: saved.append(1))
        try:
            panel._refresh_calibration = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
            try:
                panel.sync_from_config()
            except RuntimeError:
                pass
            saved.clear()
            panel._tolerance.setValue(4.5)
            self.assertEqual(len(saved), 1, "同步失败后设置页应仍然可用")
        finally:
            panel.deleteLater()
            _pump(self.app, 0.05)


if __name__ == "__main__":
    unittest.main()
