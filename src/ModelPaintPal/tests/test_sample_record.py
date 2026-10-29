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


class RecordOrNoneTest(unittest.TestCase):
    """历史/收藏列表的严格解析：还原不出颜色就丢掉，不要伪造纯黑。

    `record_from_dict` 刻意宽容（解析失败回落纯黑），这对「必须返回一条记录」的
    调用方是对的；但列表 UI 不能这么干——一块纯黑色块和真实记录长得一模一样，
    用户会以为自己取过这个颜色，删都不知道删哪条。
    """

    def test_valid_rgb(self):
        from app.core.sample_record import record_or_none

        record = record_or_none({"rgb": [10, 20, 30], "hex": "#0A141E"})
        self.assertIsNotNone(record)
        self.assertEqual(record.hex, "#0A141E")

    def test_hex_only_is_accepted(self):
        from app.core.sample_record import record_or_none

        self.assertIsNotNone(record_or_none({"hex": "#112233"}))
        self.assertIsNotNone(record_or_none({"hex": "112233"}))

    def test_unusable_entries_are_dropped(self):
        from app.core.sample_record import record_or_none

        for bad in ("不是字典", None, 42, {}, {"bad": 1},
                    {"hex": "zzz"}, {"rgb": "red"}, {"rgb": [1, 2]}):
            self.assertIsNone(record_or_none(bad), f"{bad!r} 不该被当成有效记录")

    def test_out_of_range_rgb_is_clamped_not_dropped(self):
        """越界通道值能夹紧就夹紧——它是能还原的颜色，不该丢。"""
        from app.core.sample_record import record_or_none

        record = record_or_none({"rgb": [999, -20, 128]})
        self.assertIsNotNone(record)
        self.assertEqual(record.rgb, (255, 0, 128))


class StoreDropsCorruptEntriesTest(unittest.TestCase):
    """存储层确实把无效条目过滤掉了（而不只是函数能返回 None）。"""

    def test_history_and_favorites_skip_corrupt_rows(self):
        import json
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        from app.core.favorites_store import FavoritesStore
        from app.core.history_store import HistoryStore

        rows = [{"hex": "#112233", "rgb": [17, 34, 51]}, "不是字典",
                {"hex": "zzz"}, {"bad": 1}]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "history.json").write_text(json.dumps(rows), encoding="utf-8")
            (root / "favorites.json").write_text(json.dumps(rows), encoding="utf-8")
            with patch("app.core.storage.user_path", side_effect=lambda *p: root.joinpath(*p)):
                history = HistoryStore(limit=10).all()
                favorites = FavoritesStore(limit=10).all()
        self.assertEqual([rec.hex for rec in history], ["#112233"])
        self.assertEqual([rec.hex for rec in favorites], ["#112233"])
