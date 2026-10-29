# -*- coding: utf-8 -*-
"""色号校准的往返：写入 → 重建 → 溯源升级 → 清除。

校准是「把实喷误差交还给用户」的回路，也是唯一会**改数据**的用户操作。
这里用内存版 overrides 存储做隔离，不碰真实的 userdata/paint_overrides.json。

一条真实缺陷作为起点：此前 ``calibrate()`` 对任意 uid 都返回成功，于是给一个
不存在的色号写校准会在设置页留下一条幽灵记录——它不对应任何色号、不影响任何
结果，而单条删除是按色号列表走的，用户只能「清空全部校准」才能弄掉。
"""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.data import paint_db  # noqa: E402


class _MemoryStore:
    """内存版 overrides 存储（替代会写真实用户目录的 JsonStore）。"""

    def __init__(self, data=None):
        self.data = dict(data or {})

    def load(self):
        return dict(self.data)

    def save(self, data):
        self.data = dict(data)
        return True


class CalibrationRoundTripTest(unittest.TestCase):
    def setUp(self):
        self.store = _MemoryStore()
        patcher = patch.object(paint_db, "_overrides_store", self.store)
        self.addCleanup(patcher.stop)
        patcher.start()
        self.addCleanup(paint_db.reload_database)
        paint_db.reload_database()
        self.uid = paint_db.get_database().entries[0].uid
        self.original_hex = paint_db.get_database().get(self.uid).hex

    def test_unknown_uid_is_rejected(self):
        """不存在的色号不能写进校准表。"""
        self.assertFalse(paint_db.calibrate("no-such-brand:X-99", "#FF0000"))
        self.assertEqual(self.store.data, {})
        self.assertEqual(paint_db.calibration_map(), {})

    def test_bad_hex_is_rejected(self):
        self.assertFalse(paint_db.calibrate(self.uid, "not-a-color"))
        self.assertEqual(self.store.data, {})

    def test_calibration_upgrades_provenance(self):
        """校准值来自用户实喷，来源等级应升到 calibrated（置信度最高）。"""
        self.assertTrue(paint_db.calibrate(self.uid, "#123456"))
        entry = paint_db.get_database().get(self.uid)
        self.assertEqual(entry.hex, "#123456")
        self.assertEqual(entry.src_kind, "calibrated")
        self.assertEqual(entry.src_ref, "S:user-calibrated")
        self.assertGreaterEqual(entry.confidence, 0.9)
        self.assertEqual(paint_db.calibration_map()[self.uid], "#123456")

    def test_reset_restores_original_value(self):
        self.assertTrue(paint_db.calibrate(self.uid, "#123456"))
        self.assertTrue(paint_db.reset_calibration(self.uid))
        entry = paint_db.get_database().get(self.uid)
        self.assertEqual(entry.hex, self.original_hex)
        self.assertNotEqual(entry.src_kind, "calibrated")
        self.assertEqual(paint_db.calibration_map(), {})

    def test_phantom_entry_in_file_is_hidden_from_ui(self):
        """文件里残留的无效 uid 不该出现在「已校准」列表里。"""
        self.store.data["ghost:Z-1"] = {"hex": "#ABCDEF", "date": "2026-01"}
        self.store.data[self.uid] = {"hex": "#00FF00", "date": "2026-01"}
        paint_db.reload_database()
        mapping = paint_db.calibration_map()
        self.assertNotIn("ghost:Z-1", mapping)
        self.assertIn(self.uid, mapping)

    def test_calibration_survives_reload(self):
        """重建数据库后校准值仍在（否则每次启动都会退回原色）。"""
        self.assertTrue(paint_db.calibrate(self.uid, "#0F0F0F"))
        paint_db.reload_database()
        self.assertEqual(paint_db.get_database().get(self.uid).hex, "#0F0F0F")


if __name__ == "__main__":
    unittest.main()
