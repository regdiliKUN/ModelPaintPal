# -*- coding: utf-8 -*-
"""品牌元数据与种子色号表的数据完整性测试（不依赖 Qt）。

种子数据是整应用的地基：一个品牌键写错、一行字段数错位、一个非法 hex，
都会让配色/用量/导出在运行时才炸。这里对数据本身做静态体检。
"""

import os
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.core.color_models import hex_to_rgb  # noqa: E402
from app.data.brands import Brand, BRANDS, brand_keys, brand_label, get_brand  # noqa: E402
from app.data.paint_seed import FINISH_LABELS, OPACITY_LABELS, SEED_TABLES  # noqa: E402


class TestBrands(unittest.TestCase):
    def test_brand_keys_match_dict(self):
        self.assertEqual(sorted(brand_keys()), sorted(BRANDS.keys()))

    def test_each_brand_key_consistent(self):
        for key, brand in BRANDS.items():
            self.assertEqual(brand.key, key)
            self.assertTrue(brand.name and brand.short)
            self.assertGreater(brand.volume_ml, 0)

    def test_get_brand_missing(self):
        self.assertIsNone(get_brand("__none__"))
        self.assertEqual(brand_label("__none__"), "__none__")

    def test_brand_label_known(self):
        key = brand_keys()[0]
        self.assertEqual(brand_label(key), BRANDS[key].short)

    def test_type_label_mapping(self):
        self.assertTrue(BRANDS[brand_keys()[0]].type_label)
        custom = Brand(key="x", name="x", short="x", line="l",
                       paint_type="weird", volume_ml=1.0)
        self.assertEqual(custom.type_label, "weird")  # 未知类型原样返回


class TestSeedTables(unittest.TestCase):
    def test_seed_brand_keys_exist(self):
        for brand_key in SEED_TABLES:
            self.assertIn(brand_key, BRANDS, f"种子品牌 {brand_key} 未在 BRANDS 中登记")

    def test_rows_are_well_formed(self):
        count = 0
        for brand_key, rows in SEED_TABLES.items():
            for row in rows:
                self.assertEqual(len(row), 8, f"{brand_key} 行字段数不对: {row!r}")
                code, _name, _name_en, hex_value, finish, opacity, _std, _note = row
                self.assertTrue(code)
                # 合法 hex 必须能解析（否则构建色号库时会被静默跳过）
                rgb = hex_to_rgb(hex_value)
                self.assertEqual(len(rgb), 3)
                self.assertIn(finish, FINISH_LABELS, f"{brand_key}:{code} finish={finish}")
                self.assertIn(opacity, OPACITY_LABELS, f"{brand_key}:{code} opacity={opacity}")
                count += 1
        self.assertGreater(count, 200)

    def test_unique_uids(self):
        seen = set()
        for brand_key, rows in SEED_TABLES.items():
            for row in rows:
                uid = f"{brand_key}:{row[0]}"
                self.assertNotIn(uid, seen, f"重复 uid: {uid}")
                seen.add(uid)


if __name__ == "__main__":
    unittest.main(verbosity=2)
