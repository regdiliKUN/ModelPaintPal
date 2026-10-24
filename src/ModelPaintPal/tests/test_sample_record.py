# -*- coding: utf-8 -*-
"""样本记录解析的健壮性测试（R13：单条脏数据不能拖垮整段加载）。"""

import unittest

from app.core.sample_record import (  # noqa: E402
    SampleRecord, record_from_dict, record_from_rgb,
)


class TestRecordRoundtrip(unittest.TestCase):
    def test_to_dict_from_dict_roundtrip(self):
        rec = record_from_rgb((12, 34, 56), name="测试", tags=["a", "b"], uid="fixed")
        back = record_from_dict(rec.to_dict())
        self.assertEqual(back.rgb, (12, 34, 56))
        self.assertEqual(back.name, "测试")
        self.assertEqual(back.tags, ["a", "b"])
        self.assertEqual(back.uid, "fixed")

    def test_display_name_falls_back_to_hex(self):
        self.assertEqual(record_from_rgb((255, 0, 0)).display_name, "#FF0000")
        self.assertEqual(record_from_rgb((255, 0, 0), name="红").display_name, "红")

    def test_time_text_format(self):
        rec = record_from_rgb((0, 0, 0), created_at=0.0)
        self.assertRegex(rec.time_text, r"^\d{2}-\d{2} \d{2}:\d{2}$")

    def test_overflow_channels_clamped(self):
        rec = record_from_dict({"rgb": [999, -20, 128]})
        self.assertEqual(rec.rgb, (255, 0, 128))


class TestRecordFromDictRobust(unittest.TestCase):
    def test_normal_dict(self):
        rec = record_from_dict({
            "uid": "abc", "rgb": [10, 20, 30], "hex": "#0a141e",
            "name": "x", "source": "screen",
        })
        self.assertEqual(rec.rgb, (10, 20, 30))
        self.assertEqual(rec.uid, "abc")

    def test_rgb_as_string_does_not_crash(self):
        # 改动前：回退分支复用原始非法 rgb，二次构造仍抛错 → all() 崩溃
        rec = record_from_dict({"rgb": "red"})
        self.assertEqual(rec.rgb, (0, 0, 0))

    def test_rgb_too_short_falls_back(self):
        rec = record_from_dict({"rgb": [1, 2]})
        self.assertEqual(rec.rgb, (0, 0, 0))

    def test_rgb_numeric_strings_parsed(self):
        rec = record_from_dict({"rgb": ["12", "34", "56"]})
        self.assertEqual(rec.rgb, (12, 34, 56))

    def test_non_dict_returns_safe_record(self):
        rec = record_from_dict("garbage")
        self.assertEqual(rec.rgb, (0, 0, 0))

    def test_none_rgb_falls_back(self):
        rec = record_from_dict({"rgb": None})
        self.assertEqual(rec.rgb, (0, 0, 0))

    def test_bulk_mixed_bad_entries_never_raise(self):
        items = [
            {"uid": "1", "rgb": [10, 20, 30]},
            {"uid": "2", "rgb": "broken"},
            {"uid": "3", "rgb": [1, 2]},
            "totally-broken",
            {"uid": "4", "rgb": [200, 100, 50]},
        ]
        records = [record_from_dict(it) for it in items]
        # 全部成功解析为合法 SampleRecord，且不抛异常
        for rec in records:
            self.assertIsInstance(rec, SampleRecord)
            self.assertEqual(len(rec.rgb), 3)


if __name__ == "__main__":
    unittest.main()
