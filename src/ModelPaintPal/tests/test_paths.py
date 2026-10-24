# -*- coding: utf-8 -*-
"""路径工具测试（user_path / ensure_dir / resource_path）。"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.core import paths  # noqa: E402


class TestPaths(unittest.TestCase):
    def test_user_path_joins(self):
        p = paths.user_path("sub", "data.json")
        self.assertEqual(p.name, "data.json")
        self.assertEqual(p.parent.name, "sub")
        self.assertEqual(p.parent.parent, paths.USER_DATA_DIR)

    def test_ensure_dir_creates_nested(self):
        base = Path(tempfile.mkdtemp())
        target = base / "a" / "b" / "c"
        self.assertFalse(target.exists())
        paths.ensure_dir(target)
        self.assertTrue(target.is_dir())
        # 幂等：再次调用不报错
        paths.ensure_dir(target)

    def test_resource_path_joins(self):
        p = paths.resource_path("icons", "app.png")
        self.assertEqual(p.name, "app.png")
        self.assertEqual(p.parent.name, "icons")

    def test_user_data_dir_is_absolute(self):
        self.assertTrue(paths.USER_DATA_DIR.is_absolute())
        self.assertEqual(str(paths.USER_DATA_DIR),
                         os.path.abspath(str(paths.USER_DATA_DIR)))


class TestShortcutScript(unittest.TestCase):
    """快捷方式脚本的桌面目录解析（R101：桌面可能被重定向到 D:\\Desktop）。

    这里只断言「返回一个真实存在、且带盘符的绝对目录」，不绑定具体盘符，
    避免换机器就失败；关键是不能再无脑用 <home>/Desktop（重定向下那是空目录）。
    """

    @classmethod
    def setUpClass(cls):
        import importlib.util

        script = PROJECT_ROOT / "scripts" / "make_shortcut.py"
        spec = importlib.util.spec_from_file_location("make_shortcut", script)
        cls.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.mod)

    def test_resolve_desktop_is_existing_abs_dir(self):
        desktop = self.mod.resolve_desktop()
        self.assertTrue(desktop.is_absolute())
        self.assertTrue(desktop.is_dir(), f"解析出的桌面不存在: {desktop}")

    def test_resolve_desktop_matches_registry_when_available(self):
        if sys.platform != "win32":
            self.skipTest("仅 Windows")
        import winreg

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
            ) as key:
                raw = winreg.QueryValueEx(key, "Desktop")[0]
        except OSError:
            self.skipTest("读不到注册表桌面项")
        expected = Path(os.path.expandvars(raw))
        if not expected.is_dir():
            self.skipTest("注册表指向的桌面目录不存在")
        self.assertEqual(self.mod.resolve_desktop(), expected)

    def test_build_link_roundtrip(self):
        data = self.mod.build_link(
            r"C:\tmp\a.exe", r"C:\tmp", r"C:\tmp\a.exe", "demo")
        header_size = int.from_bytes(data[0:4], "little")
        li = header_size
        off = int.from_bytes(data[li + 16:li + 20], "little")
        raw = data[li + off:li + off + 100]
        # LocalBasePath 是 ANSI（系统代码页），不是 UTF-16
        text = raw.decode("mbcs").split("\x00")[0]
        self.assertEqual(text, r"C:\tmp\a.exe")
        self.assertTrue(data[20] & 0x02)   # HasLinkInfo
        self.assertEqual(data[-4:], b"\x00\x00\x00\x00")  # TerminalBlock 收尾


if __name__ == "__main__":
    unittest.main(verbosity=2)
