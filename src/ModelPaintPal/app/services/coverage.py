# -*- coding: utf-8 -*-
"""喷涂用量估算。

模型（全部参数可在设置里调整）：

    原漆用量 = 面积 × 层数 × 原漆单位用量 × 施工损耗 × 基材系数 × 余量 + 固定原漆损耗
    稀释剂用量 = 纯漆用量 × 稀释比
    混合液用量 = 纯漆用量 + 稀释剂用量

兼容旧参数：mix_ml_per_m2_per_coat 表示参考1:1稀释时的单位混合液量，
除以2得到固定的原漆单位量。默认110 -> 55 ml/m²/层，保留旧版1:1的估算。
这只是旧参数的迁移约定，不是对汽车工艺资料的物理换算，也不是模型漆实测值。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, asdict
from typing import Dict

__all__ = [
    "CoverageInput",
    "CoverageEstimate",
    "estimate_coverage",
    "APPLICATION_FACTORS",
    "SURFACE_FACTORS",
    "LOW_OPACITY_HINT",
    "ANCHORS",
    "anchor_provenance",
    "REFERENCE_DILUTION_FACTOR",
]

REFERENCE_DILUTION_FACTOR = 2.0

# 施工方式造成的过喷/残留损耗
APPLICATION_FACTORS: Dict[str, float] = {
    "airbrush": 1.35,
    "brush": 1.05,
    "spray_can": 1.60,
}

# 基材对吸漆量的影响：3D 打印件未上水补土时层纹会显著多吃漆
SURFACE_FACTORS: Dict[str, float] = {
    "primed": 1.00,
    "raw_print": 1.30,
    "glossy": 1.10,
}

# ---------------------------------------------------------------------------
# 用量锚点的出处
#
# 这几个数字此前只活在 DATA_ITERATIONS.md 里，代码里是一个光秃秃的 1.30。
# 用量是要拿去买漆的，用户有权知道「1.30 是谁说的」。
#
# confidence 普遍给得低：锚点来自**汽车底色漆**的工艺数据，而模型漆膜更薄，
# 这是跨领域外推，不是实测。这也是为什么这几个参数全部开放校准。
# ---------------------------------------------------------------------------
ANCHORS: Dict[str, Dict[str, object]] = {
    "mix_ml_per_m2_per_coat": {
        "value": 110.0,
        "kind": "derived",
        "source": "旧版参数按参考1:1稀释保留估算；非模型漆实喷数据",
        "confidence": 0.35,
        "note": "界面显示原漆基准55 ml/m²/层；需按具体产品与喷笔实喷校准",
    },
    "raw_print": {
        "value": 1.30,
        "kind": "retail",
        "source": "3D 打印后处理工艺文 / 水补土喷涂教程（层纹多吃约 30%）",
        "confidence": 0.50,
        "note": "不同层高与打磨程度差异很大，先喷一层水补土更稳",
    },
    "glossy": {
        "value": 1.10,
        "kind": "derived",
        "source": "按光面塑料吸漆量推定",
        "confidence": 0.40,
        "note": "无独立实测来源",
    },
    "airbrush": {
        "value": 1.35,
        "kind": "derived",
        "source": "按喷笔常见过喷损耗推定",
        "confidence": 0.45,
        "note": "雾化程度、气压、走枪速度都会影响",
    },
    "brush": {
        "value": 1.05,
        "kind": "derived",
        "source": "按笔涂残留损耗推定",
        "confidence": 0.55,
        "note": "笔涂损耗小，置信度相对高",
    },
    "spray_can": {
        "value": 1.60,
        "kind": "derived",
        "source": "按喷罐雾化损耗推定（Tamiya 喷罐说明：100ml 约喷 2~3 个 1/48 飞机）",
        "confidence": 0.45,
        "note": "喷罐不可调压，个体差异大",
    },
}


def anchor_provenance(inp: "CoverageInput") -> list:
    """列出本次估算实际用到的锚点及其出处，供 UI / 导出显示。

    只返回**参与计算**的那几个（施工方式、基材、单位用量），不把所有锚点都
    摊出来 —— 用户不需要看六个数字里的三个跟他无关的数字。
    """
    keys = ["mix_ml_per_m2_per_coat", inp.surface, inp.application]
    out = []
    for key in keys:
        anchor = ANCHORS.get(key)
        if anchor:
            out.append(dict(anchor, key=key))
    return out

# 遮盖力弱的色系（黄/橙/红/白）需要更多层数
LOW_OPACITY_HINT = "遮盖力偏弱：建议先薄喷白/灰底，再分层叠加"


@dataclass
class CoverageInput:
    area_m2: float = 0.05
    coats: int = 2
    thinner_ratio: float = 1.0      # 稀释剂 / 漆
    application: str = "airbrush"
    surface: str = "primed"
    mix_ml_per_m2_per_coat: float = 110.0
    waste_buffer: float = 1.15
    fixed_paint_loss_ml: float = 0.0

    def normalized(self) -> "CoverageInput":
        self.area_m2 = max(0.0005, float(self.area_m2))
        self.coats = max(1, int(self.coats))
        self.thinner_ratio = max(0.0, float(self.thinner_ratio))
        if self.application not in APPLICATION_FACTORS:
            self.application = "airbrush"
        if self.surface not in SURFACE_FACTORS:
            self.surface = "primed"
        self.mix_ml_per_m2_per_coat = max(10.0, float(self.mix_ml_per_m2_per_coat))
        self.waste_buffer = max(1.0, float(self.waste_buffer))
        self.fixed_paint_loss_ml = max(0.0, float(self.fixed_paint_loss_ml))
        return self


@dataclass
class CoverageEstimate:
    area_m2: float
    coats: int
    mix_ml: float         # 已稀释混合液
    paint_ml: float       # 纯漆
    thinner_ml: float     # 稀释剂
    bottles: float        # 需要的瓶数（按整瓶容量）
    per_component_ml: Dict[str, float]  # 按配方比例拆分到各组分
    notes: list

    def as_text(self) -> str:
        parts = [
            f"面积 {self.area_m2 * 10000:.0f} cm² × {self.coats} 层",
            f"纯漆 {self.paint_ml:.2f} ml",
            f"稀释剂 {self.thinner_ml:.2f} ml",
            f"混合液 {self.mix_ml:.2f} ml",
        ]
        if self.bottles:
            parts.append(f"≈ {self.bottles:.2f} 瓶")
        return " · ".join(parts)


def _validated_copy(inp: "CoverageInput", proportions, bottle_ml: float) -> "CoverageInput":
    """校验并复制输入，返回可安全改动的副本。

    拒绝非有限输入：NaN/inf 会被 max() 直接放行（Python 的 max 遇 NaN 返回 NaN），
    一路乘进面积、稀释比，最终给出「NaN ml」却不触发任何报错——必须在第一现场挡住。
    ``bottle_ml`` 是唯一漏网过的输入：它决定「约几瓶」，NaN 会让 bottles 变成 NaN
    而不触发任何报错（NaN 参与的比较全为假，连 ``bottle_ml > 0`` 都拦不住它）。
    """
    if inp is None:
        raise ValueError("用量估算缺少输入 CoverageInput")
    for name in ("area_m2", "thinner_ratio", "mix_ml_per_m2_per_coat", "waste_buffer", "coats",
                 "fixed_paint_loss_ml"):
        value = getattr(inp, name, None)
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"CoverageInput.{name} 必须是有限实数，收到 {value!r}")
    if proportions:
        for key, value in proportions.items():
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"proportions[{key!r}] 必须是有限实数，收到 {value!r}")
    if not isinstance(bottle_ml, (int, float)) or not math.isfinite(bottle_ml):
        raise ValueError(f"bottle_ml 必须是有限实数，收到 {bottle_ml!r}")
    # 先拷贝再归一化，绝不修改调用方传入的 CoverageInput（避免隐藏的副作用：
    # 之前 inp.normalized() 会就地修改原对象，共享同一实例时会导致二次调用结果漂移）。
    return CoverageInput(**asdict(inp)).normalized()


def _coverage_notes(cfg: "CoverageInput") -> list:
    """按本次参数生成提示语（只写和当前设置相关的，不摊无关说明）。"""
    notes = ["用量为经验估算，原漆需求不随额外稀释比减少；请按个人喷笔校准"]
    if cfg.fixed_paint_loss_ml:
        notes.append(f"已另计固定原漆损耗 {cfg.fixed_paint_loss_ml:g} ml（不乘面积或层数）")
    if cfg.surface == "raw_print":
        notes.append("3D 打印件未上水补土，层纹会多吃约 30% 的漆，建议先喷一层水补土")
    if cfg.thinner_ratio <= 0.0:
        notes.append("未稀释：仅适合笔涂或预稀释漆（如 Vallejo Model Air、SMS）")
    elif cfg.thinner_ratio >= 2.0:
        notes.append("稀释度偏高，遮盖力会下降，需增加层数")
    if cfg.application == "spray_can":
        notes.append("喷罐损耗大，估算已按 1.6 倍计入")
    return notes


def estimate_coverage(inp: CoverageInput,
                      proportions: Dict[str, float] | None = None,
                      bottle_ml: float = 0.0) -> CoverageEstimate:
    """估算用量。``proportions`` 为 {组分标识: 0-1 比例}，可为空。

    ``bottle_ml`` 给 0 时不计算瓶数（多品牌混合没有单一容量）。
    """
    cfg = _validated_copy(inp, proportions, bottle_ml)
    application_factor = APPLICATION_FACTORS[cfg.application]
    surface_factor = SURFACE_FACTORS[cfg.surface]

    paint_rate = cfg.mix_ml_per_m2_per_coat / REFERENCE_DILUTION_FACTOR
    paint_ml = (cfg.area_m2 * cfg.coats * paint_rate
                * application_factor * surface_factor * cfg.waste_buffer + cfg.fixed_paint_loss_ml)
    thinner_ml = paint_ml * cfg.thinner_ratio
    mix_ml = paint_ml + thinner_ml

    per_component: Dict[str, float] = {}
    if proportions:
        total = sum(max(0.0, float(v)) for v in proportions.values())
        if total > 0:
            per_component = {
                key: paint_ml * (max(0.0, float(value)) / total)
                for key, value in proportions.items()
            }

    return CoverageEstimate(
        area_m2=cfg.area_m2,
        coats=cfg.coats,
        mix_ml=round(mix_ml, 3),
        paint_ml=round(paint_ml, 3),
        thinner_ml=round(thinner_ml, 3),
        bottles=round(paint_ml / bottle_ml, 2) if bottle_ml > 0 else 0.0,
        per_component_ml={k: round(v, 3) for k, v in per_component.items()},
        notes=_coverage_notes(cfg),
    )


def suggest_coats(finish: str, opacity: str, base_coats: int) -> int:
    """按漆种遮盖力微调建议层数。"""
    coats = max(1, int(base_coats))
    if opacity == "semi":
        coats += 1
    elif opacity == "clear":
        coats = max(1, coats - 1)
    if finish == "fluor":
        coats += 1
    return min(8, coats)


def to_dict(estimate: CoverageEstimate) -> dict:
    data = asdict(estimate)
    return data
