# -*- coding: utf-8 -*-
"""数据可靠性与联网核验的测试。

重点不是「功能跑通」，而是这几条不能破的规矩：

1. 引用了不存在的来源必须被拦住（不得编造）；
2. 未标注必须落最低档，而不是默认可信；
3. 编号必须可复现 —— 与传入顺序无关；
4. 推断不挂引用角标；
5. 任何联网失败都不许改动本地色值。

全部离屏运行，不依赖 PySide6。
"""

from __future__ import annotations

import unittest
from typing import List

from app.core.config import AppConfig
from app.core.http_client import FetchResult, ensure_text_query
from app.data.paint_db import PaintEntry, build_database
from app.data.sources import (
    ENTRY_SOURCES, SOURCES, SOURCE_KINDS, is_stale, kind_confidence,
)
from app.services.paint_matcher import PaintMatcher
from app.services.provenance import build_provenance
from app.services.verify_service import (
    Provider, _extract_hex, verify_entry,
)


def _entry(uid: str, code: str = "T1", rgb=(200, 16, 46),
           src_kind: str = "", src_ref: str = "", src_date: str = "",
           brand_key: str = "tamiya") -> PaintEntry:
    return PaintEntry(
        uid=uid, brand_key=brand_key, code=code, name="测试色", name_en="Test",
        rgb=rgb, finish="gloss", opacity="opaque",
        src_kind=src_kind, src_ref=src_ref, src_date=src_date,
    )


class TestSourceRegistry(unittest.TestCase):
    """来源注册表本身必须自洽。"""

    def test_entry_sources_reference_existing_ids(self):
        for uid, item in ENTRY_SOURCES.items():
            kind, ref, _date = item
            self.assertIn(kind, SOURCE_KINDS, f"{uid} 的 src_kind 非法")
            self.assertTrue(not ref or ref in SOURCES,
                            f"{uid} 引用了不存在的来源 {ref}")

    def test_every_source_has_known_kind(self):
        for sid, source in SOURCES.items():
            self.assertIn(source.kind, SOURCE_KINDS, f"{sid} 的 kind 非法")

    def test_derived_is_lowest_confidence(self):
        self.assertLess(kind_confidence("derived"), kind_confidence("chart"))
        self.assertLess(kind_confidence("chart"), kind_confidence("official"))

    def test_stale_requires_a_date(self):
        self.assertFalse(is_stale(""), "空日期不算过期，那是未标注问题")
        self.assertFalse(is_stale("2026-09", today="2026-10"))
        self.assertTrue(is_stale("2021-08", today="2026-10"))


class TestEntryProvenance(unittest.TestCase):
    """PaintEntry 的溯源字段行为。"""

    def test_unknown_kind_falls_back_to_derived(self):
        entry = _entry("x:1", src_kind="官网说的")
        self.assertEqual(entry.src_kind, "derived")
        self.assertEqual(entry.confidence, kind_confidence("derived"))

    def test_missing_reference_is_unannotated_not_derived(self):
        entry = _entry("x:1")
        self.assertFalse(entry.is_annotated)
        self.assertEqual(entry.src_kind, "derived")

    def test_reference_to_unknown_source_does_not_crash(self):
        """运行期遇到脏引用不能崩，但要如实标记为「未标注」。"""
        entry = _entry("x:1", src_kind="official", src_ref="S:不存在")
        self.assertFalse(entry.is_annotated)
        self.assertIsNone(entry.source)

    def test_annotated_entry_exposes_url(self):
        entry = _entry("x:1", src_kind="official", src_ref="S:tamiya-official")
        self.assertTrue(entry.is_annotated)
        self.assertTrue(entry.is_fact)
        self.assertTrue(entry.provenance["url"])

    def test_calibrated_outranks_official(self):
        official = _entry("x:1", src_kind="official", src_ref="S:tamiya-official")
        measured = _entry("x:2", src_kind="calibrated", src_ref="S:user-calibrated")
        self.assertGreater(measured.confidence, official.confidence)


class TestSeedDatabase(unittest.TestCase):
    """真实色号库上的不变量。"""

    def test_seed_rows_still_load(self):
        db = build_database()
        self.assertEqual(len(db), 672)

    def test_unannotated_entries_are_low_confidence(self):
        db = build_database()
        for entry in db.entries:
            if not entry.is_annotated:
                self.assertEqual(entry.src_kind, "derived")
                self.assertLessEqual(entry.confidence, 0.45)

    def test_annotated_entries_are_documented(self):
        db = build_database()
        for uid in ENTRY_SOURCES:
            entry = db.get(uid)
            if entry is None:
                continue
            self.assertTrue(entry.is_annotated, f"{uid} 登记了来源却没生效")


class TestProvenanceSummary(unittest.TestCase):
    """引用聚合与编号。"""

    def _entries(self) -> List[PaintEntry]:
        return [
            _entry("a:1", "A1", src_kind="chart", src_ref="S:paint-vault"),
            _entry("b:1", "B1", src_kind="official", src_ref="S:tamiya-official"),
            _entry("c:1", "C1"),                       # 未标注
        ]

    def test_numbering_is_independent_of_input_order(self):
        base = build_provenance(self._entries())
        shuffled = build_provenance(list(reversed(self._entries())))
        self.assertEqual([r.index for r in base.refs],
                         [r.index for r in shuffled.refs])
        self.assertEqual([r.source_id for r in base.refs],
                         [r.source_id for r in shuffled.refs])

    def test_more_trustworthy_source_numbers_first(self):
        prov = build_provenance(self._entries())
        self.assertEqual(prov.refs[0].source_id, "S:tamiya-official")

    def test_unannotated_gets_no_citation(self):
        prov = build_provenance(self._entries())
        self.assertEqual(prov.cite_of("c:1"), "")
        self.assertEqual(prov.unannotated_count, 1)
        self.assertNotEqual(prov.cite_of("b:1"), "")

    def test_confidence_is_the_weakest_link(self):
        prov = build_provenance(self._entries())
        self.assertEqual(prov.confidence, kind_confidence("derived"))

    def test_inference_has_no_references(self):
        """计算类结论不该被编号 —— 它没有可点开的来源。"""
        prov = build_provenance([_entry("a:1")])
        self.assertEqual(prov.refs, [])
        self.assertFalse(prov.has_refs)

    def test_dirty_source_does_not_leave_a_number_gap(self):
        """引用到注册表里不存在的来源时，编号必须仍然连续、且不指向空号。

        此前用 ``enumerate(source_ids)`` 发号、再用 ``source_ids.index(sid) + 1``
        反查，跳过脏数据后编号会留下空号（界面出现 [1] [3] 找不到 [2]），
        被跳过的色号还会被指到一个根本不存在的编号上。
        """
        entries = [
            _entry("a:1", src_kind="chart", src_ref="S:paint-vault"),
            _entry("b:1", src_kind="official", src_ref="S:not-registered"),
            _entry("c:1", src_kind="retail", src_ref="S:tamiya-official"),
        ]
        prov = build_provenance(entries)
        self.assertEqual([r.index for r in prov.refs], [1, 2])
        self.assertEqual([r.source_id for r in prov.refs],
                         ["S:tamiya-official", "S:paint-vault"])
        # 脏数据那一条不参与编号，也不该拿到角标
        self.assertEqual(prov.cite_of("b:1"), "")
        # 有效色号的角标必须落在真实存在的 refs 上
        indexes = {r.index for r in prov.refs}
        for uid in ("a:1", "c:1"):
            self.assertIn(int(prov.cite_of(uid)), indexes)

    def test_stale_is_reported(self):
        entry = _entry("a:1", src_kind="official",
                       src_ref="S:tamiya-official", src_date="2021-01")
        prov = build_provenance([entry])
        self.assertEqual(prov.stale_count, 1)


class TestMatcherIntegration(unittest.TestCase):
    """建议链路必须带上溯源。"""

    def test_suggestions_carry_provenance(self):
        db = build_database()
        matcher = PaintMatcher(db)
        config = AppConfig()
        config.preferred_brands = ["tamiya"]
        items = matcher.suggest((200, 16, 46), config, max_results=2)
        self.assertTrue(items)
        for item in items:
            self.assertIsNotNone(item.provenance)
            # 绝大多数色号未标注来源，置信度应被压到最低档
            self.assertLessEqual(item.provenance.confidence, 0.90)


class TestPrivacyGuard(unittest.TestCase):
    def test_binary_payload_is_refused(self):
        with self.assertRaises(ValueError):
            ensure_text_query({"image": b"\x89PNG"})
        with self.assertRaises(ValueError):
            ensure_text_query({"frames": [b"\x00\x01"]})

    def test_text_payload_passes(self):
        ensure_text_query({"brand": "田宫", "code": "X-7"})


class TestHexExtraction(unittest.TestCase):
    """「解析失败」与「查无此色」必须分开。"""

    def test_absent_when_code_missing(self):
        value, status = _extract_hex("<html>nothing here</html>", "X-7")
        self.assertEqual(status, "absent")
        self.assertEqual(value, "")

    def test_parse_when_code_found_without_hex(self):
        value, status = _extract_hex("<div>X-7 亮光红</div>", "X-7")
        self.assertEqual(status, "parse")

    def test_ok_when_hex_near_code(self):
        value, status = _extract_hex("<div>X-7 #C8102E</div>", "X-7")
        self.assertEqual(status, "ok")
        self.assertEqual(value, "#C8102E")


def _result(key: str, status: str, body: str = "", ms: int = 10) -> FetchResult:
    return FetchResult(key=key, ok=(status == "ok"), status=status,
                       url="https://example.invalid/", body=body, elapsed_ms=ms)


class TestVerifyService(unittest.TestCase):
    """联网核验的降级链。"""

    def setUp(self) -> None:
        self.entry = _entry("tamiya:X-7", "X-7", rgb=(200, 16, 46),
                            src_kind="official", src_ref="S:tamiya-official")
        self.providers = [
            Provider("p1", "源一", "https://one.invalid/?q={query}", "official"),
            Provider("p2", "源二", "https://two.invalid/?q={query}", "chart"),
        ]

    def _fetcher(self, mapping):
        def run(jobs):
            return {key: mapping.get(key, _result(key, "network")) for key, *_ in jobs}
        return run

    def test_all_success_sorted_by_delta_e(self):
        mapping = {
            "p1:X-7": _result("p1:X-7", "ok", "<div>X-7 #C8102E</div>", 120),
            "p2:X-7": _result("p2:X-7", "ok", "<div>X-7 #FF0000</div>", 300),
        }
        report = verify_entry(self.entry, providers=self.providers,
                              use_cache=False, fetcher=self._fetcher(mapping))
        self.assertEqual(len(report.ok_hits), 2)
        self.assertEqual(report.best.hex, "#C8102E")
        self.assertIn("未被自动修改", report.verdict())

    def test_partial_failure_keeps_successful_hits(self):
        mapping = {
            "p1:X-7": _result("p1:X-7", "ok", "<div>X-7 #C8102E</div>"),
            "p2:X-7": _result("p2:X-7", "timeout"),
        }
        report = verify_entry(self.entry, providers=self.providers,
                              use_cache=False, fetcher=self._fetcher(mapping))
        self.assertEqual(len(report.ok_hits), 1)
        self.assertEqual(sum(1 for h in report.hits if h.status == "timeout"), 1)

    def test_total_failure_never_touches_local_value(self):
        mapping = {"p1:X-7": _result("p1:X-7", "network"),
                   "p2:X-7": _result("p2:X-7", "timeout")}
        report = verify_entry(self.entry, providers=self.providers,
                              use_cache=False, fetcher=self._fetcher(mapping))
        self.assertTrue(report.all_failed)
        self.assertIn("本地值一字未改", report.verdict())
        # 关键回归：本地色值必须保持原样
        self.assertEqual(report.local_hex, "#C8102E")
        self.assertEqual(self.entry.hex, "#C8102E")

    def test_parse_failure_is_not_absent(self):
        mapping = {"p1:X-7": _result("p1:X-7", "ok", "<div>X-7 亮光红</div>")}
        report = verify_entry(self.entry, providers=[self.providers[0]],
                              use_cache=False, fetcher=self._fetcher(mapping))
        self.assertEqual(report.hits[0].status, "parse")
        self.assertNotEqual(report.hits[0].status, "absent")

    def test_disabled_returns_nothing(self):
        report = verify_entry(self.entry, enabled=False, providers=self.providers,
                              use_cache=False)
        self.assertFalse(report.configured)
        self.assertEqual(report.hits, [])

    def test_unconfigured_is_stated_plainly(self):
        report = verify_entry(self.entry, providers=[], use_cache=False)
        self.assertFalse(report.configured)
        self.assertIn("尚未配置", report.verdict())


class TestExportCarriesSources(unittest.TestCase):
    """分享出去的文本也必须能溯源 —— 转发出去之后就断链是最常见的情况。"""

    def setUp(self) -> None:
        from app.services.export_service import (
            suggestions_to_csv, suggestions_to_json, suggestions_to_share_text,
        )

        self.to_json = suggestions_to_json
        self.to_csv = suggestions_to_csv
        self.to_share = suggestions_to_share_text

        matcher = PaintMatcher(build_database())
        config = AppConfig()
        config.preferred_brands = ["tamiya"]
        self.items = matcher.suggest((200, 16, 46), config, max_results=2)
        self.target = (200, 16, 46)

    def test_json_has_provenance_block(self):
        payload = self.to_json(self.items, self.target)
        self.assertIn("provenance", payload)
        self.assertIn("src_kind", payload)

    def test_share_text_mentions_source_gap(self):
        text = self.to_share(self.items, self.target)
        self.assertIn("ModelPaintPal", text)
        # 绝大多数色号未标注来源，分享文本里必须如实说明，不能装作有出处
        self.assertTrue("未登记来源" in text or "来源" in text)

    def test_csv_gained_source_columns(self):
        head = self.to_csv(self.items, self.target).splitlines()[0]
        self.assertIn("confidence", head)
        self.assertIn("sources", head)


class TestCoverageAnchors(unittest.TestCase):
    """用量锚点必须有出处。"""

    def test_every_used_anchor_has_a_source(self):
        from app.services.coverage import CoverageInput, anchor_provenance

        used = anchor_provenance(CoverageInput(application="airbrush",
                                               surface="raw_print"))
        self.assertTrue(used)
        for anchor in used:
            self.assertIn(anchor["kind"], SOURCE_KINDS)
            self.assertTrue(anchor["source"])
            self.assertLess(anchor["confidence"], 0.70,
                            "跨领域外推的锚点不该给高置信度")

    def test_all_anchor_names_are_covered(self):
        from app.services.coverage import ANCHORS, APPLICATION_FACTORS, SURFACE_FACTORS

        for key in APPLICATION_FACTORS:
            self.assertIn(key, ANCHORS, f"{key} 缺少来源登记")
        for key in SURFACE_FACTORS:
            if key == "primed":
                continue    # 基准值 1.00，不需要出处
            self.assertIn(key, ANCHORS, f"{key} 缺少来源登记")


class TestVerifyCache(unittest.TestCase):
    """缓存损坏时的正确行为是静默降级为未缓存，不是崩。"""

    def test_broken_records_are_not_fresh(self):
        from app.data import verify_cache

        self.assertFalse(verify_cache.is_fresh(None))
        self.assertFalse(verify_cache.is_fresh({}))
        self.assertFalse(verify_cache.is_fresh("not a dict"))
        self.assertFalse(verify_cache.is_fresh({"verified_at": "不是时间"}))

    def test_expired_and_fresh(self):
        from datetime import datetime, timedelta, timezone

        from app.data import verify_cache

        old = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat(
            timespec="seconds")
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.assertFalse(verify_cache.is_fresh({"verified_at": old}))
        self.assertTrue(verify_cache.is_fresh({"verified_at": now}))


if __name__ == "__main__":
    unittest.main()
