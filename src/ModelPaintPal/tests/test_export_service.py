# -*- coding: utf-8 -*-
"""导出链路的结构性约束。

导出的东西是**离开程序之后才被消费**的：贴到群里、粘进 Excel、被别人的脚本解析。
所以这里测的不是文案好不好看，而是「列数固定、字段可解析、缺失不炸」——
这几条一旦破了，用户那边的失败是静默的。
"""

import csv
import io
import json
import os
import re
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.core.config import AppConfig  # noqa: E402
from app.services.export_service import (  # noqa: E402
    _TABLE_HEADER, _confidence_text, _suggestion_row, suggestions_to_csv,
    suggestions_to_json, suggestions_to_share_text, suggestions_to_tsv,
)
from app.services.paint_matcher import PaintMatcher  # noqa: E402
from app.services.provenance import ProvenanceSummary  # noqa: E402

TARGET = (120, 96, 72)


class ExportTableTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.matcher = PaintMatcher()
        cls.config = AppConfig().validate()
        cls.suggestions = cls.matcher.suggest(TARGET, cls.config)

    def test_row_width_matches_header(self):
        """每行字段数必须与表头一致，否则 Excel/脚本按列取值会整体错位。"""
        for item in self.suggestions:
            self.assertEqual(len(_suggestion_row(item, "#000000")), len(_TABLE_HEADER))

    def test_csv_and_tsv_parse_back_to_same_columns(self):
        for render, delimiter in ((suggestions_to_csv, ","), (suggestions_to_tsv, "\t")):
            rows = list(csv.reader(io.StringIO(render(self.suggestions, TARGET)),
                                   delimiter=delimiter))
            self.assertEqual(rows[0], _TABLE_HEADER)
            for row in rows[1:]:
                self.assertEqual(len(row), len(_TABLE_HEADER))

    def test_json_is_parseable_and_keeps_schema_marker(self):
        payload = json.loads(suggestions_to_json(self.suggestions, TARGET))
        self.assertEqual(payload["schema_version"], 2)
        self.assertEqual(payload["ratio_basis"], "integer_drops")
        self.assertEqual(len(payload["suggestions"]), len(self.suggestions))
        first = payload["suggestions"][0]
        self.assertIn("components", first)
        self.assertTrue(first["components"])

    def test_share_text_survives_without_suggestions(self):
        """没匹配到色号时也要给出可读的一段话，而不是空字符串。"""
        text = suggestions_to_share_text([], TARGET)
        self.assertIn("没有匹配到色号", text)


class ConfidenceCellTest(unittest.TestCase):
    """置信度单元格：缺失或异常一律输出空串，绝不把异常抛进导出流程。"""

    class _Item:
        def __init__(self, provenance):
            self.provenance = provenance

    def test_missing_provenance(self):
        self.assertEqual(_confidence_text(self._Item(None)), "")

    def test_normal_value(self):
        prov = ProvenanceSummary(confidence=0.45)
        self.assertEqual(_confidence_text(self._Item(prov)), "0.45")

    def test_broken_value_does_not_raise(self):
        prov = ProvenanceSummary()
        prov.confidence = None            # 脏数据：类型不对
        self.assertEqual(_confidence_text(self._Item(prov)), "")
        prov.confidence = "0.5"
        self.assertEqual(_confidence_text(self._Item(prov)), "")


class DeltaETextConsistencyTest(unittest.TestCase):
    """同一条建议在四处出现的 ΔE 必须同位数、同数值。

    项目自己写过「卡片写 ΔE 2.96、状态栏写 3.0 会让人以为是两次不同的计算」，
    但分享文本/剪贴板文本当时还是 1 位小数。这里把口径钉死：凡是「ΔE 数字」，
    一律两位小数，且与 suggestion.delta_e 对得上。
    """

    @classmethod
    def setUpClass(cls):
        cls.matcher = PaintMatcher()
        cls.config = AppConfig().validate()
        cls.suggestions = cls.matcher.suggest(TARGET, cls.config)

    def test_all_delta_e_texts_use_two_decimals(self):
        """文本里出现的**每一个** ΔE（含替代色号自己的色差）都必须是两位小数。"""
        from app.services.export_service import recipe_to_text, suggestion_to_markdown

        texts = [
            recipe_to_text(self.suggestions[0].recipe),
            suggestion_to_markdown(self.suggestions[0], "#000000"),
            suggestions_to_share_text(self.suggestions, TARGET, limit=2),
        ]
        for text in texts:
            self.assertIsNone(re.search(r"ΔE \d+\.\d(?!\d)", text),
                              f"存在 1 位小数的 ΔE：{text[:80]}")
            self.assertIsNone(re.search(r"ΔE \d+(?!\.)", text),
                              f"存在无小数的 ΔE：{text[:80]}")

    def test_headline_matches_suggestion_value(self):
        from app.services.export_service import recipe_to_text, suggestion_to_markdown

        item = self.suggestions[0]
        expected = f"ΔE {item.delta_e:.2f}"
        self.assertIn(expected, recipe_to_text(item.recipe).splitlines()[0])
        self.assertIn(expected, suggestion_to_markdown(item, "#000000").splitlines()[0])
        self.assertIn(expected, suggestions_to_share_text(self.suggestions, TARGET, limit=1))

    def test_recipe_header_has_no_raw_model_key(self):
        """剪贴板标题里不能出现 kubelka_munk 这种开发者术语。"""
        from app.services.export_service import recipe_to_text

        head = recipe_to_text(self.suggestions[0].recipe).splitlines()[0]
        self.assertNotIn("kubelka_munk", head)
        self.assertNotIn("linear_rgb", head)
        self.assertIn("ΔE", head)


class MarkdownStructureTest(unittest.TestCase):
    """导出文本的结构安全：竖线与换行不能把表格/列表拆坏。

    当前色号库里没有这种字符，但那是数据而不是约束——补一条新色号、改一个
    品牌名就可能引入。错位是静默的：表格照样渲染，只是列对不上。
    """

    @classmethod
    def setUpClass(cls):
        cls.matcher = PaintMatcher()
        cls.config = AppConfig().validate()
        cls.suggestions = cls.matcher.suggest(TARGET, cls.config)

    def test_pipe_in_name_does_not_split_cells(self):
        from app.services.export_service import recipe_to_markdown

        recipe = self.suggestions[0].recipe
        original = recipe.components[0].paint.name
        recipe.components[0].paint.name = "A|B"
        try:
            rows = recipe_to_markdown(recipe).splitlines()
        finally:
            recipe.components[0].paint.name = original
        for row in rows:
            # 5 列表格：行首 + 4 个分隔 + 行尾 = 6 个**未转义**的竖线
            self.assertEqual(len(re.findall(r"(?<!\\)\|", row)), 6,
                             f"表格行被拆坏：{row}")
        self.assertIn("A\\|B", rows[2])

    def test_newline_in_name_does_not_add_rows(self):
        from app.services.export_service import recipe_to_markdown

        recipe = self.suggestions[0].recipe
        original = recipe.components[0].paint.name
        recipe.components[0].paint.name = "第一行\n第二行"
        try:
            rows = recipe_to_markdown(recipe).splitlines()
        finally:
            recipe.components[0].paint.name = original
        self.assertEqual(len(rows), 2 + len(recipe.components))

    def test_newline_in_note_stays_on_one_bullet(self):
        from app.services.export_service import suggestion_to_markdown

        item = self.suggestions[0]
        original = list(item.notes)
        item.notes = ["第一段\n第二段"]
        try:
            lines = suggestion_to_markdown(item, "#000000").splitlines()
        finally:
            item.notes = original
        bullets = [line for line in lines if line.startswith("- 提示：")]
        self.assertEqual(len(bullets), 1)
        self.assertIn("第一段 第二段", bullets[0])


if __name__ == "__main__":
    unittest.main()
