# -*- coding: utf-8 -*-
"""桌面快捷方式自安装的测试（COM 部分用 mock，真实调用只在用户环境发生）。"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.core import shortcut  # noqa: E402


class TestShortcut(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mpal_sc_"))
        self.desktop = self.tmp / "Desktop"
        self.desktop.mkdir()
        self.exe_dir = self.tmp / "app"
        self.exe_dir.mkdir()
        self.exe = self.exe_dir / "ModelPaintPal.exe"
        self.exe.write_bytes(b"MZ fake")

    def _patched(self, load_target=""):
        """mock COM 读取：第一次调用返回 load_target（既有快捷方式状态），
        之后（创建后回读）返回当前 exe，模拟真实创建成功。"""
        calls = []

        def fake_load(path):
            calls.append(path)
            # 首次调用 = 读取既有快捷方式；仅当文件真实存在时才给 load_target，
            # 否则（创建后的回读）一律返回当前 exe，模拟真实创建成功。
            if len(calls) == 1 and Path(path).exists():
                return load_target
            return str(self.exe)

        return (
            mock.patch.object(shortcut.sys, "frozen", True, create=True),
            mock.patch.object(shortcut.sys, "executable", str(self.exe)),
            mock.patch.object(shortcut, "resolve_desktop", return_value=self.desktop),
            mock.patch.object(shortcut, "_com_load_target", side_effect=fake_load),
            mock.patch.object(shortcut, "_com_create"),  # 纯 mock，绝不触发真实 COM
        )

    def test_skipped_in_dev_mode(self):
        # 非 frozen（开发模式）必须直接跳过，不碰任何东西
        with mock.patch.object(shortcut, "_com_create") as create:
            self.assertIsNone(shortcut.ensure_desktop_shortcut())
            create.assert_not_called()

    def test_creates_when_missing(self):
        patches = self._patched()
        with patches[0], patches[1], patches[2], patches[3], patches[4] as create:
            lnk = shortcut.ensure_desktop_shortcut()
        self.assertEqual(lnk, self.desktop / shortcut.SHORTCUT_NAME)
        create.assert_called_once()
        args = create.call_args[0]
        self.assertEqual(args[0], str(self.exe))
        self.assertEqual(args[1], str(self.desktop / shortcut.SHORTCUT_NAME))

    def _make_lnk(self) -> Path:
        lnk = self.desktop / shortcut.SHORTCUT_NAME
        lnk.write_bytes(b"\x4c\x00\x00\x00 placeholder")
        return lnk

    def test_idempotent_when_target_matches(self):
        self._make_lnk()  # 文件必须真实存在，才会走「读取既有目标」分支
        patches = self._patched(load_target=str(self.exe))
        with patches[0], patches[1], patches[2], patches[3], patches[4] as create:
            lnk = shortcut.ensure_desktop_shortcut()
        self.assertEqual(lnk, self.desktop / shortcut.SHORTCUT_NAME)
        create.assert_not_called()  # 已指向当前 exe，不应重建

    def test_recreates_when_target_differs(self):
        self._make_lnk()
        # 快捷方式存在但指向别处 → 必须重建
        patches = self._patched(load_target=r"C:\old\place.exe")
        with patches[0], patches[1], patches[2], patches[3], patches[4] as create:
            shortcut.ensure_desktop_shortcut()
        create.assert_called_once()

    def test_recreates_when_lnk_unreadable(self):
        self._make_lnk()
        # 损坏快捷方式（Load 失败 → 空串）也要重建
        patches = self._patched(load_target="")
        with patches[0], patches[1], patches[2], patches[3], patches[4] as create:
            shortcut.ensure_desktop_shortcut()
        create.assert_called_once()

    def test_rejects_degenerate_lnk(self):
        # COM「成功」但写出的 lnk 里没有 exe 名（如被环境改写成指向「此电脑」）
        # → 必须判定失败并删掉半成品，不能把坏快捷方式留在桌面。
        def fake_create(target, lnk_path, workdir, icon, desc):
            Path(lnk_path).write_bytes(b"\x4c\x00\x00\x00 degenerate no exe name")

        patches = self._patched()
        with patches[0], patches[1], patches[2], patches[3], \
             mock.patch.object(shortcut, "_com_create", side_effect=fake_create):
            result = shortcut.ensure_desktop_shortcut()
        self.assertIsNone(result)
        self.assertFalse((self.desktop / shortcut.SHORTCUT_NAME).exists())

    def test_accepts_lnk_that_mentions_exe(self):
        # COM 回读拿不到路径（如目标只存在 IDList 里）时，字节级校验要能放行
        def fake_create(target, lnk_path, workdir, icon, desc):
            name_utf16 = "ModelPaintPal.exe".encode("utf-16-le")
            Path(lnk_path).write_bytes(b"\x4c\x00\x00\x00 idlist " + name_utf16)

        patches = self._patched()
        with patches[0], patches[1], patches[2], patches[3], \
             mock.patch.object(shortcut, "_com_create", side_effect=fake_create):
            result = shortcut.ensure_desktop_shortcut()
        self.assertEqual(result, self.desktop / shortcut.SHORTCUT_NAME)
        self.assertTrue((self.desktop / shortcut.SHORTCUT_NAME).exists())

    def test_keeps_existing_lnk_when_com_read_fails_but_bytes_match(self):
        """COM 读不出目标、但字节里确实写着本 exe：不要反复删除重建。

        受限环境（沙箱 / 部分安全软件）下 COM 回读经常拿不到路径，
        以前的逻辑会「删掉 → 重建 → 校验失败 → 再删掉」，每次启动都把
        用户桌面上的入口折腾一遍。
        """
        lnk = self.desktop / shortcut.SHORTCUT_NAME
        name_utf16 = "ModelPaintPal.exe".encode("utf-16-le")
        lnk.write_bytes(b"\x4c\x00\x00\x00 idlist " + name_utf16)

        patches = self._patched(load_target="")
        with patches[0], patches[1], patches[2], patches[3], patches[4] as create:
            result = shortcut.ensure_desktop_shortcut()
        self.assertEqual(result, lnk)
        create.assert_not_called()
        self.assertTrue(lnk.exists())

    def test_restores_previous_lnk_when_new_one_fails_validation(self):
        """重建失败时必须还原用户原来的快捷方式，而不是删掉。"""
        lnk = self.desktop / shortcut.SHORTCUT_NAME
        original = b"\x4c\x00\x00\x00 original valid " + "ModelPaintPal.exe".encode("utf-16-le")
        lnk.write_bytes(original)

        def degenerate_create(target, lnk_path, workdir, icon, desc):
            Path(lnk_path).write_bytes(b"\x4c\x00\x00\x00 degenerate")

        patches = self._patched()
        with patches[0], patches[1], patches[2], \
             mock.patch.object(shortcut, "_com_load_target",
                               side_effect=[r"C://old//place.exe", ""]), \
             mock.patch.object(shortcut, "_com_create", side_effect=degenerate_create):
            result = shortcut.ensure_desktop_shortcut()
        self.assertIsNone(result)
        self.assertTrue(lnk.exists(), "原快捷方式必须被还原，而不是删除")
        self.assertEqual(lnk.read_bytes(), original)

    def test_failure_never_raises(self):
        # COM 崩了也不能影响应用启动
        patches = self._patched()
        with patches[0], patches[1], patches[2], patches[3], \
             mock.patch.object(shortcut, "_com_create",
                               side_effect=OSError("COM boom")):
            self.assertIsNone(shortcut.ensure_desktop_shortcut())

    def test_lnk_path_uses_resolved_desktop(self):
        # 注册表重定向（D:\Desktop）场景：不能落到 <home>/Desktop
        lnk = shortcut.default_lnk_path(self.desktop)
        self.assertEqual(lnk.parent, self.desktop)
        self.assertTrue(lnk.name.endswith(".lnk"))

    def test_resolve_desktop_returns_existing_dir(self):
        if sys.platform != "win32":
            self.skipTest("仅 Windows")
        desktop = shortcut.resolve_desktop()
        self.assertTrue(desktop.is_absolute())
        self.assertTrue(desktop.is_dir(), f"解析出的桌面不存在: {desktop}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
