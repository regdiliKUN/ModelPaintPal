# -*- coding: utf-8 -*-
"""色差算法正确性验证。

验证策略（双层）：
1. 绝对正确：用 Sharma 论文公布的权威锚点值（ΔE00 = 2.0425 / 2.3669 / 0.0）锚定；
2. 相对正确：与一份**独立重写**的 CIEDE2000 参考实现逐项比对，两者都按标准公式
   实现但代码路径完全不同，若结果一致则互为佐证（两份独立端口不太可能犯同样的错）。
"""

import math
import unittest

from app.core.delta_e import (delta_e, delta_e_2000, delta_e_76, delta_e_94,
                             delta_e_cmc, grade_delta_e, resolve_delta_e,
                             sl_scale_max)


def _reference_ciede2000(lab1, lab2):
    """独立参考实现（基于 ISO/CIE 标准公式，与产品代码无共享逻辑）。"""
    l1, a1, b1 = lab1
    l2, a2, b2 = lab2
    c1 = math.hypot(a1, b1)
    c2 = math.hypot(a2, b2)
    cbar = (c1 + c2) / 2.0
    g = 0.5 * (1 - math.sqrt(cbar ** 7 / (cbar ** 7 + 25 ** 7))) if cbar > 0 else 0.0
    a1p = (1 + g) * a1
    a2p = (1 + g) * a2
    c1p = math.hypot(a1p, b1)
    c2p = math.hypot(a2p, b2)

    def _hue(ap, bb):
        if ap == 0 and bb == 0:
            return 0.0
        h = math.degrees(math.atan2(bb, ap))
        return h + 360.0 if h < 0 else h

    h1p = _hue(a1p, b1)
    h2p = _hue(a2p, b2)
    dl = l2 - l1
    dc = c2p - c1p
    if c1p * c2p == 0:
        dh = 0.0
    else:
        if abs(h2p - h1p) <= 180:
            dh = h2p - h1p
        elif h2p - h1p > 180:
            dh = h2p - h1p - 360
        else:
            dh = h2p - h1p + 360
        dh = 2 * math.sqrt(c1p * c2p) * math.sin(math.radians(dh / 2))
    lbar = (l1 + l2) / 2.0
    cbar_p = (c1p + c2p) / 2.0
    if c1p * c2p == 0:
        hbar = h1p + h2p
    else:
        if abs(h1p - h2p) <= 180:
            hbar = (h1p + h2p) / 2.0
        elif h1p + h2p < 360:
            hbar = (h1p + h2p + 360) / 2.0
        else:
            hbar = (h1p + h2p - 360) / 2.0
    t = (1 - 0.17 * math.cos(math.radians(hbar - 30))
         + 0.24 * math.cos(math.radians(2 * hbar))
         + 0.32 * math.cos(math.radians(3 * hbar + 6))
         - 0.20 * math.cos(math.radians(4 * hbar - 63)))
    dtheta = 30 * math.exp(-(((hbar - 275) / 25) ** 2))
    rc = 2 * math.sqrt(cbar_p ** 7 / (cbar_p ** 7 + 25 ** 7)) if cbar_p > 0 else 0.0
    sl = 1 + (0.015 * (lbar - 50) ** 2) / math.sqrt(20 + (lbar - 50) ** 2)
    sc = 1 + 0.045 * cbar_p
    sh = 1 + 0.015 * cbar_p * t
    rt = -math.sin(math.radians(2 * dtheta)) * rc
    return math.sqrt((dl / sl) ** 2 + (dc / sc) ** 2 + (dh / sh) ** 2
                     + rt * (dc / sc) * (dh / sh))


class DeltaEReferenceTest(unittest.TestCase):
    """绝对正确：Sharma 论文权威锚点。"""

    def test_sharma_anchor_2_0425(self):
        de = delta_e_2000((50.0, 2.6772, -79.7751), (50.0, 0.0, -82.7485))
        self.assertAlmostEqual(de, 2.0425, places=3)

    def test_sharma_anchor_2_3669(self):
        de = delta_e_2000((50.0, 0.0, 0.0), (50.0, -1.0, 2.0))
        self.assertAlmostEqual(de, 2.3669, places=3)

    def test_identical_is_zero(self):
        self.assertAlmostEqual(delta_e_2000((40.0, 10.0, 20.0), (40.0, 10.0, 20.0)), 0.0, places=6)

    def test_symmetry(self):
        a, b = (35.0, -20.0, 15.0), (60.0, 40.0, -10.0)
        self.assertAlmostEqual(delta_e_2000(a, b), delta_e_2000(b, a), places=9)


class DeltaECrossCheckTest(unittest.TestCase):
    """相对正确：与独立参考实现逐项比对。"""

    _SAMPLES = [
        (50, 0, 0), (50, 10, 10), (50, -10, 20), (50, 30, -30), (50, -40, 5),
        (35, 20, -15), (70, -25, 40), (20, 5, 5), (90, 0, 0), (50, 2.6772, -79.7751),
        (50, -1, 2), (63.0, 50.0, 30.0), (43.0, -10.0, -5.0), (80.0, 12.0, -45.0),
        (25.0, -30.0, 20.0), (55.0, 40.0, 40.0), (50.0, -50.0, -50.0),
    ]

    def test_ciede2000_vs_reference(self):
        for i, lab1 in enumerate(self._SAMPLES):
            for lab2 in self._SAMPLES[i:]:
                got = delta_e_2000(lab1, lab2)
                ref = _reference_ciede2000(lab1, lab2)
                self.assertAlmostEqual(got, ref, places=6,
                                      msg=f"CIEDE2000 mismatch {lab1} vs {lab2}: {got} != {ref}")

    def test_cie76_vs_reference(self):
        for lab1, lab2 in [((50, 0, 0), (50, 3, 4)), ((35, 10, -5), (70, -20, 30))]:
            expected = math.sqrt(sum((a - b) ** 2 for a, b in zip(lab1, lab2)))
            self.assertAlmostEqual(delta_e_76(lab1, lab2), expected, places=6)

    def test_cie94_positive_and_finite(self):
        for lab1, lab2 in [((50, 0, 0), (50, 3, 4)), ((35, 10, -5), (70, -20, 30))]:
            val = delta_e_94(lab1, lab2)
            self.assertGreaterEqual(val, 0.0)
            self.assertTrue(math.isfinite(val))

    def test_cmc_positive_and_finite(self):
        for lab1, lab2 in [((50, 0, 0), (50, 3, 4)), ((35, 10, -5), (70, -20, 30))]:
            val = delta_e_cmc(lab1, lab2)
            self.assertGreaterEqual(val, 0.0)
            self.assertTrue(math.isfinite(val))


class DeltaEDispatchContractTest(unittest.TestCase):
    """正确性：分发器必须按公式名精确路由，未知公式回落到 CIEDE2000。"""

    _L1 = (50.0, 10.0, -20.0)
    _L2 = (55.0, -5.0, 15.0)

    def test_ciede2000_aliases(self):
        base = delta_e_2000(self._L1, self._L2)
        for alias in ("CIEDE2000", "2000", "ΔE00", "CIEDE", "ciede2000"):
            self.assertAlmostEqual(delta_e(self._L1, self._L2, alias), base, places=9)

    def test_cie94_aliases(self):
        base = delta_e_94(self._L1, self._L2)
        for alias in ("CIE94", "94"):
            self.assertAlmostEqual(delta_e(self._L1, self._L2, alias), base, places=9)

    def test_cie76_aliases(self):
        base = delta_e_76(self._L1, self._L2)
        for alias in ("CIE76", "76", "LAB"):
            self.assertAlmostEqual(delta_e(self._L1, self._L2, alias), base, places=9)

    def test_cmc_alias(self):
        self.assertAlmostEqual(delta_e(self._L1, self._L2, "CMC"),
                               delta_e_cmc(self._L1, self._L2), places=9)

    def test_unknown_formula_falls_back_to_2000(self):
        self.assertAlmostEqual(delta_e(self._L1, self._L2, "不存在的公式"),
                               delta_e_2000(self._L1, self._L2), places=9)

    def test_delta_e_rgb_convenience(self):
        from app.core.color_models import rgb_to_lab
        from app.core.delta_e import delta_e_rgb

        a, b = (255, 0, 0), (250, 5, 5)
        self.assertAlmostEqual(delta_e_rgb(a, b),
                               delta_e(rgb_to_lab(a), rgb_to_lab(b)), places=9)

    def test_available_formulas(self):
        from app.core.delta_e import available_formulas

        fs = available_formulas()
        self.assertIsInstance(fs, tuple)
        for name in ("CIEDE2000", "CIE94", "CIE76", "CMC"):
            self.assertIn(name, fs)

    def test_resolve_delta_e(self):
        # 热路径复用的解析器：别名映射与未知回落必须与 delta_e 一致
        self.assertIs(resolve_delta_e("CIEDE2000"), delta_e_2000)
        self.assertIs(resolve_delta_e("76"), delta_e_76)
        self.assertIs(resolve_delta_e("CMC"), delta_e_cmc)
        self.assertIs(resolve_delta_e("nonsense"), delta_e_2000)
        self.assertIs(resolve_delta_e(None), delta_e_2000)

    def test_empty_formula_falls_back_to_2000(self):
        # 配置里公式为空/None 时也必须回落到 CIEDE2000，而非崩溃
        for odd in ("", None):
            self.assertAlmostEqual(delta_e(self._L1, self._L2, odd),
                                   delta_e_2000(self._L1, self._L2), places=9)

    def test_cie76_exact_value(self):
        # ΔE76 = 欧氏距离：(0,0,0) 与 (0,3,4) 精确等于 5
        self.assertAlmostEqual(delta_e_76((0.0, 0.0, 0.0), (0.0, 3.0, 4.0)), 5.0, places=9)

    def test_all_formulas_zero_on_identical(self):
        lab = (48.0, -12.0, 33.0)
        for fn in (delta_e_2000, delta_e_94, delta_e_76, delta_e_cmc):
            self.assertAlmostEqual(fn(lab, lab), 0.0, places=9)

    def test_all_formulas_non_negative_finite(self):
        pairs = [((50, 0, 0), (50, 3, 4)), ((20, -30, 10), (80, 40, -50)),
                 ((90, 0, 0), (10, 0, 0))]
        for lab1, lab2 in pairs:
            for fn in (delta_e_2000, delta_e_94, delta_e_76, delta_e_cmc):
                val = fn(lab1, lab2)
                self.assertGreaterEqual(val, 0.0)
                self.assertTrue(math.isfinite(val))

    def test_grade_monotonic(self):
        values = [grade_delta_e(v).value for v in (0.0, 1.0, 2.0, 4.0, 8.0, 20.0)]
        self.assertEqual(values, sorted(values))

    def test_grade_sweep_labels_non_empty(self):
        prev = -1.0
        for v in (0.0, 0.5, 1.0, 2.0, 3.0, 4.0, 6.0, 10.0, 30.0):
            grade = grade_delta_e(v)
            self.assertTrue(grade.label)
            self.assertGreaterEqual(grade.value, prev - 1e-9)
            prev = grade.value

    def test_grade_rejects_non_finite(self):
        """NaN/inf 不能被静默归到「完全不同的两个颜色」。"""
        for bad in (float("nan"), float("inf"), float("-inf"), None, "abc"):
            grade = grade_delta_e(bad)
            self.assertIn("无法判定", grade.label)

    def test_grade_buckets(self):
        self.assertEqual(grade_delta_e(0.3).label, "肉眼几乎无法分辨")
        self.assertEqual(grade_delta_e(1.5).label, "极接近，仅并排对比可察觉")
        self.assertEqual(grade_delta_e(3.0).label, "近距离可见差异，喷涂可接受")
        self.assertEqual(grade_delta_e(4.5).label, "明显不同，需接受色偏")
        self.assertEqual(grade_delta_e(9.0).label, "完全不同的两个颜色")
        # 其它色值应按数值单调（颜色越偏、标签越“严重”）
        grades = [grade_delta_e(v).value for v in (0.5, 2.5, 4.0, 7.0)]
        self.assertEqual(grades, sorted(grades))


class LightnessLowerBoundTest(unittest.TestCase):
    """亮度下界 ``ΔE ≥ |ΔL| / S_L,max``。

    替代色检索用它做剪枝（``alternatives._nearest``）：亮度差已经超容差的候选
    直接跳过。这条**必须是严格下界**，否则会漏掉合格的替代色号——那是「说没有
    替代品，其实有」，比慢一点严重得多。
    """

    def test_scale_bound_values(self):
        self.assertAlmostEqual(sl_scale_max("CIEDE2000"), 1.747, places=3)
        self.assertAlmostEqual(sl_scale_max("CIE76"), 1.0, places=6)
        self.assertAlmostEqual(sl_scale_max("CIE94"), 1.0, places=6)
        self.assertAlmostEqual(sl_scale_max("CMC"), 1.5, places=6)
        # 未知识别名回落到 CIEDE2000 的界，宁可少剪也不多剪
        self.assertAlmostEqual(sl_scale_max("???"), 1.747, places=3)
        # 也可以直接传已解析的函数对象
        self.assertAlmostEqual(sl_scale_max(resolve_delta_e("CIE76")), 1.0, places=6)

    def test_bound_holds_for_every_formula(self):
        """在真实色号库上穷举验证：不存在违反下界的组合。"""
        from app.data.paint_db import get_database

        entries = get_database().entries
        targets = [entry.lab for entry in entries[::37]] + [
            (0.0, 0.0, 0.0), (100.0, 0.0, 0.0), (50.0, -60.0, 40.0),
        ]
        for formula in ("CIEDE2000", "CIE76", "CIE94", "CMC"):
            de_fn = resolve_delta_e(formula)
            sl_max = sl_scale_max(de_fn)
            for target in targets:
                for entry in entries:
                    value = de_fn(entry.lab, target)
                    bound = abs(entry.lab[0] - target[0]) / sl_max
                    self.assertGreaterEqual(
                        value + 1e-9, bound,
                        f"{formula} 违反亮度下界：{entry.uid} vs {target}")

    def test_nearest_pruning_keeps_every_qualifying_candidate(self):
        """剪枝前后结果必须逐位相同（与不剪枝的暴力实现对照）。"""
        from app.data.paint_db import get_database
        from app.services.alternatives import _nearest

        db = get_database()
        entries = db.entries
        for formula in ("CIEDE2000", "CIE76", "CMC"):
            de_fn = resolve_delta_e(formula)
            for reference in entries[::53]:
                for tolerance in (1.0, 3.0, 6.0):
                    expected = [
                        (de_fn(reference.lab, cand.lab), cand.uid)
                        for cand in entries
                        if cand.uid != reference.uid
                        and cand.brand_key != reference.brand_key
                        and de_fn(reference.lab, cand.lab) <= tolerance
                    ]
                    expected.sort(key=lambda item: item[0])
                    expected = expected[:4]
                    got = _nearest(reference, entries, {reference.uid}, False,
                                   de_fn, sl_scale_max(de_fn), tolerance, 4)
                    self.assertEqual([uid for _, uid in expected],
                                     [cand.uid for _, cand in got],
                                     f"{formula} / 容差 {tolerance} / {reference.uid} 剪枝漏了候选")


if __name__ == "__main__":
    unittest.main()
