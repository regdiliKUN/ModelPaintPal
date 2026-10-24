# -*- coding: utf-8 -*-
"""色号数据库（PaintDatabase）的单元测试（不依赖 Qt）。"""

import os
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.data.paint_db import PaintEntry, get_database  # noqa: E402


class TestPaintDatabase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = get_database()

    def test_database_is_populated(self):
        # 与 scripts/smoke_test.py 的阈值对齐：至少 200 条 / 5 个品牌
        self.assertGreaterEqual(len(self.db), 200)
        self.assertGreaterEqual(len(self.db.brands), 5)

    def test_entries_have_computed_lab(self):
        entry = self.db.by_brand(self.db.brands[0])[0]
        lab = entry.lab
        self.assertEqual(len(lab), 3)
        self.assertTrue(all(isinstance(v, float) for v in lab))

    def test_get_returns_entry(self):
        first = self.db.by_brand(self.db.brands[0])[0]
        self.assertIs(self.db.get(first.uid), first)

    def test_get_missing_returns_none(self):
        self.assertIsNone(self.db.get("__no_such_uid__"))

    def test_by_brand_only_that_brand(self):
        brand = self.db.brands[0]
        for entry in self.db.by_brand(brand):
            self.assertEqual(entry.brand_key, brand)

    def test_by_brands_order_preserved_and_deduped(self):
        """by_brands 必须按调用方给的品牌顺序拼接，且重复品牌只取一次（R42）。"""
        a, b = self.db.brands[0], self.db.brands[1]
        forward = self.db.by_brands([a, b])
        expected = ([e.uid for e in self.db.by_brand(a)]
                    + [e.uid for e in self.db.by_brand(b)])
        self.assertEqual([e.uid for e in forward], expected)
        # 重复品牌不应重复拼接
        dup = self.db.by_brands([a, a, b])
        self.assertEqual([e.uid for e in dup], expected)

    def test_by_brands_union(self):
        a, b = self.db.brands[0], self.db.brands[1]
        combined = self.db.by_brands([a, b])
        expected = len(self.db.by_brand(a)) + len(self.db.by_brand(b))
        self.assertEqual(len(combined), expected)
        for entry in combined:
            self.assertIn(entry.brand_key, (a, b))

    def test_search_by_code(self):
        code = self.db.by_brand(self.db.brands[0])[0].code
        found = self.db.search(code, brand_keys=[self.db.brands[0]])
        self.assertTrue(any(entry.code == code for entry in found))
        # 空关键字返回整池（按品牌过滤后）
        self.assertEqual(len(self.db.search("", brand_keys=[self.db.brands[0]])),
                         len(self.db.by_brand(self.db.brands[0])))

    def test_is_mixable_flags(self):
        def mk(finish, opacity):
            return PaintEntry(uid="u", brand_key="tamiya", code="C", name="n",
                              name_en="n", rgb=(1, 2, 3), finish=finish, opacity=opacity)

        self.assertTrue(mk("flat", "opaque").is_mixable())
        self.assertFalse(mk("clear", "opaque").is_mixable())
        self.assertTrue(mk("clear", "opaque").is_mixable(allow_clear=True))
        self.assertFalse(mk("metal", "opaque").is_mixable())
        self.assertTrue(mk("metal", "opaque").is_mixable(allow_metallic=True))

    def test_search_unknown_returns_empty(self):
        self.assertEqual(self.db.search("__no_such_code__"), [])

    def test_by_standard_and_standards_of(self):
        with_std = next((e for e in self.db if e.standards), None)
        self.assertIsNotNone(with_std, "种子数据应含有标准色关联")
        std = with_std.standards[0]
        self.assertIn(with_std.uid, [e.uid for e in self.db.by_standard(std)])
        self.assertIn(std.upper(), self.db.standards_of(with_std))

    def test_count_by_brand_keys_match(self):
        counts = self.db.count_by_brand()
        self.assertEqual(set(counts.keys()), set(self.db.brands))

    def test_entry_to_dict_roundtrip_fields(self):
        entry = self.db.by_brand(self.db.brands[0])[0]
        payload = entry.to_dict()
        self.assertEqual(payload["uid"], entry.uid)
        self.assertEqual(payload["code"], entry.code)
        self.assertIn("hex", payload)
        # 由种子重建后仍是同一 uid
        rebuilt = PaintEntry.from_dict(payload)
        self.assertEqual(rebuilt.uid, entry.uid)
        self.assertEqual(rebuilt.rgb, entry.rgb)


if __name__ == "__main__":
    unittest.main(verbosity=2)
