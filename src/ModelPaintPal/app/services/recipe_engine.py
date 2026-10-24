# -*- coding: utf-8 -*-
"""调色配方求解。

给定目标 Lab 与一组候选色号，搜索「1 色直用 / 2 色混 / 3 色混」中 ΔE 最小的
组合，并把比例换算成滴数与百分比。

搜索策略：
* 单色：线性扫描全部候选；
* 双色：先粗扫 21 档再在最优邻域细化 9 档（避免黄金分割在非单峰曲线上跑偏）；
* 三色：在候选前 8 名的单纯形上做 1/10 粗扫 + 局部细化。
同等 ΔE 下优先取组分更少的方案（少一种漆 = 少一处误差来源）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import combinations
from typing import List, Optional, Sequence, Tuple

from ..core.color_models import (
    linear_to_lab, linear_to_rgb, rgb_to_hex, rgb_to_lab, rgb_to_linear,
)
from ..core.delta_e import delta_e, resolve_delta_e
from ..data.paint_db import PaintEntry
from .mixing import _mix_linears, _mix_profiles, _profile_of

__all__ = [
    "RecipeComponent", "Recipe", "solve_recipe", "proportions_to_drops",
    "build_direct_recipe", "closest_entries",
]

_COARSE_STEPS = 20          # 双色粗扫档数
_REFINE_STEPS = 8           # 双色细化档数
_TRIPLE_GRID = 10           # 三色粗网格分辨率
_TRIPLE_REFINE = 20         # 三色细化网格分辨率
_TRIPLE_REFINE_WIN = 6      # 三色细化只在最优邻域 ±6 档内扫（粗网格 10 档已足够定位）
_TRIPLE_POOL = 8            # 参与三色搜索的候选数
_FEW_COMPONENT_BONUS = 0.35  # 少一个组分相当于 ΔE 便宜这么多
_MAX_DROP_ITERATIONS = 400


@dataclass
class RecipeComponent:
    paint: PaintEntry
    proportion: float      # 0-1
    drops: int = 0
    percent: float = 0.0

    @property
    def label(self) -> str:
        return f"{self.paint.brand_label} {self.paint.code} {self.paint.name}"

    @property
    def percent_label(self) -> str:
        text = f"{self.percent:.1f}".rstrip("0").rstrip(".")
        prefix = "≈" if abs(float(text) - self.percent) > 1e-8 else ""
        return prefix + text + "%"


@dataclass
class Recipe:
    components: List[RecipeComponent]
    mixed_rgb: Tuple[int, int, int]
    mixed_lab: Tuple[float, float, float]
    delta_e: float
    formula: str = "CIEDE2000"
    model: str = "kubelka_munk"
    direct: bool = False     # True 表示单色直用

    @property
    def mixed_hex(self) -> str:
        return rgb_to_hex(self.mixed_rgb)

    @property
    def proportions(self) -> List[float]:
        return [c.proportion for c in self.components]

    @property
    def key(self) -> str:
        return "+".join(sorted(c.paint.uid for c in self.components))

    def drops_text(self) -> str:
        return " : ".join(str(c.drops) for c in self.components)

    def percent_text(self) -> str:
        return " : ".join(c.percent_label for c in self.components)

    def components_text(self) -> str:
        return " + ".join(c.label for c in self.components)


# ---------------------------------------------------------------------------
# 内部：在线性空间做快速混合（核心混合逻辑统一复用 mixing._mix_linears）
# ---------------------------------------------------------------------------
def _prepare(candidates: Sequence[PaintEntry]) -> List[Tuple[PaintEntry, Tuple[float, float, float]]]:
    return [(entry, rgb_to_linear(entry.rgb)) for entry in candidates]


def _mix_many(linears: Sequence[Sequence[float]], weights: Sequence[float],
              model: str) -> Tuple[float, float, float]:
    """在线性光空间按权重混合；实际计算委托给 mixing._mix_linears（单一实现）。"""
    return _mix_linears(list(linears), list(weights), model)


def _de_of_profiles(profiles: Sequence[Sequence[float]], weights: Sequence[float],
                    target_lab: Sequence[float], model: str, de_fn) -> float:
    """给定已预转的混合工作向量与权重，返回与目标 Lab 的色差。

    入参是 ``mixing._profile_of`` 预先算好的向量（K/S 或线性光），
    因此每次混合只剩「加权平均 + 一次开方」，不必对同一候选色重复求 K/S。
    ``de_fn`` 是已解析好的色差函数（见 ``delta_e.resolve_delta_e``），循环内直接调用，
    不再每次都做公式名字符串处理。
    """
    mixed = _mix_profiles(profiles, weights, model)
    return de_fn(linear_to_lab(mixed), target_lab)


# ---------------------------------------------------------------------------
# 搜索
# ---------------------------------------------------------------------------
def _best_single(prepared, target_lab, de_fn):
    # 直接复用 PaintEntry 上已缓存的 Lab（PaintEntry.lab == rgb_to_lab(rgb)），
    # 免去每个候选都做「线性光 → RGB → Lab」的往返转换——这是单色扫描的主要耗时点。
    best = None
    for entry, linear in prepared:
        value = de_fn(entry.lab, target_lab)
        if best is None or value < best[0]:
            best = (value, (entry,), (1.0,))
    return best


def _best_pair(prepared, profiles, target_lab, model, de_fn):
    best = None
    for i, j in combinations(range(len(prepared)), 2):
        pair = (profiles[i], profiles[j])
        coarse_best_t, coarse_best_v = 0.5, None
        for step in range(_COARSE_STEPS + 1):
            t = step / _COARSE_STEPS
            value = _de_of_profiles(pair, (1.0 - t, t), target_lab, model, de_fn)
            if coarse_best_v is None or value < coarse_best_v:
                coarse_best_v, coarse_best_t = value, t
        span = 1.0 / _COARSE_STEPS
        for step in range(-_REFINE_STEPS, _REFINE_STEPS + 1):
            t = coarse_best_t + span * step / _REFINE_STEPS
            if not 0.0 <= t <= 1.0:
                continue
            value = _de_of_profiles(pair, (1.0 - t, t), target_lab, model, de_fn)
            if value < coarse_best_v:
                coarse_best_v, coarse_best_t = value, t
        # 只保留有效配比（各组分不低于 5%，避免出现「1 滴兑 20 滴」的废方案）
        if coarse_best_t < 0.05 or coarse_best_t > 0.95:
            continue
        if best is None or coarse_best_v < best[0]:
            best = (coarse_best_v, (prepared[i][0], prepared[j][0]),
                    (1.0 - coarse_best_t, coarse_best_t))
    return best


def _best_triple(prepared, profiles, target_lab, model, de_fn, current_best=float("inf")):
    """三色搜索。

    ``current_best`` 为当前已知最优 ΔE（含少组分奖励）。粗扫阶段若某三色的
    最优点已经劣于 ``current_best``，就**跳过整个细化**（细化只在最优邻域
    ±_TRIPLE_REFINE_WIN 档内扫，不再铺满 21×21），从而把大多数无望三色组合
    的代价从「粗扫 + 全细化」降到「仅粗扫」。这是 suggest 热路径上最大的单项
    加速来源（实测单次 suggest 的 ΔE 评估次数下降约一半）。
    """
    pool_size = min(len(prepared), _TRIPLE_POOL)
    best = None
    for i, j, k in combinations(range(pool_size), 3):
        triple = (profiles[i], profiles[j], profiles[k])
        entries = (prepared[i][0], prepared[j][0], prepared[k][0])
        grid = _TRIPLE_GRID
        local_best = (None, 0.0, 0.0, 0.0)
        for i_w in range(grid + 1):
            for j_w in range(grid + 1 - i_w):
                k_w = grid - i_w - j_w
                weights = (i_w / grid, j_w / grid, k_w / grid)
                value = _de_of_profiles(triple, weights, target_lab, model, de_fn)
                if local_best[0] is None or value < local_best[0]:
                    local_best = (value, i_w / grid, j_w / grid, k_w / grid)
        if local_best[0] is None:
            continue
        # 粗扫最优点已经追不上当前最优 → 直接放弃该三色，连细化都省了
        if local_best[0] >= current_best:
            continue
        # 细化：在最优邻域 ±_TRIPLE_REFINE_WIN 档内用更细网格再扫一遍
        step = 1.0 / _TRIPLE_REFINE
        base = local_best[1:4]
        refined = local_best
        for di in range(-_TRIPLE_REFINE_WIN, _TRIPLE_REFINE_WIN + 1):
            wi = base[0] + di * step / _TRIPLE_GRID
            if wi < 0.0 or wi > 1.0:
                continue
            for dj in range(-_TRIPLE_REFINE_WIN, _TRIPLE_REFINE_WIN + 1):
                wj = base[1] + dj * step / _TRIPLE_GRID
                if wj < 0.0 or wj > 1.0 or wi + wj > 1.0:
                    continue
                wk = 1.0 - wi - wj
                if min(wi, wj, wk) < 0.04:
                    continue
                value = _de_of_profiles(triple, (wi, wj, wk), target_lab, model, de_fn)
                if value < refined[0]:
                    refined = (value, wi, wj, wk)
        if min(refined[1:4]) < 0.04:
            continue
        weights = tuple(refined[1:4])
        if best is None or refined[0] < best[0]:
            best = (refined[0], entries, weights)
    return best


def solve_recipe(target_lab: Sequence[float],
                 candidates: Sequence[PaintEntry],
                 max_components: int = 3,
                 model: str = "kubelka_munk",
                 formula: str = "CIEDE2000",
                 drop_total: int = 20,
                 tolerance: float = 3.0,
                 prepared: Optional[List] = None) -> Optional[Recipe]:
    """求解最优配方；候选不足或全部不可用时返回 ``None``。

    ``prepared`` 为已预计算的 ``[(entry, linear_rgb), ...]``（顺序需与 ``candidates``
    一致）。由调用方（如 ``PaintMatcher.suggest``）一次性算好并复用，可避免对同一个
    候选池反复做 RGB→线性光的转换（主要性能瓶颈之一）。
    """
    pool = list(candidates)
    if not pool:
        return None
    # 目标色必须是 3 个有限实数；NaN/inf 或长度不对会让 delta_e 返回 NaN，
    # 进而产生「ΔE=NaN 的配方」却不被任何比较捕获——必须第一现场拒绝。
    if (not isinstance(target_lab, (list, tuple)) or len(target_lab) != 3
            or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in target_lab)):
        raise ValueError("target_lab 必须是三个有限实数 (L*, a*, b*)")
    target_lab = tuple(float(v) for v in target_lab)
    prepared = prepared if prepared is not None else _prepare(pool)
    # 候选色 → 混合工作向量的转换只做一次（K/S 需要 **2 与除法，是混合里最贵的一步），
    # 后面的上万次混合都复用这份向量。
    profiles = [_profile_of(item[1], model) for item in prepared]

    # 公式只在入口解析一次，搜索内部直接调用函数对象，省掉十几万次字符串处理。
    de_fn = resolve_delta_e(formula)

    single = _best_single(prepared, target_lab, de_fn)
    if single is not None and single[0] <= tolerance:
        recipe = _build_recipe(single[1], single[2], target_lab, model, formula, drop_total)
        recipe.direct = True
        return recipe

    best = single
    scored_single = single[0] if single else float("inf")

    # 双色搜索必须同时受「候选足够」与「用户允许 2 组分」两个约束；
    # 此前只判了 len(pool) >= 2，于是 max_components=1 时仍可能返回 2 色方案
    # （是否触发取决于候选池顺序），是一个会随数据顺序偶发的正确性缺陷。
    if max_components >= 2 and len(pool) >= 2:
        pair = _best_pair(prepared, profiles, target_lab, model, de_fn)
        if pair and pair[0] + _FEW_COMPONENT_BONUS < scored_single:
            best, scored_single = pair, pair[0] + _FEW_COMPONENT_BONUS

    if max_components >= 3 and len(pool) >= 3:
        triple = _best_triple(prepared, profiles, target_lab, model, de_fn,
                              current_best=scored_single)
        if triple and triple[0] + 2 * _FEW_COMPONENT_BONUS < scored_single:
            best = triple

    if best is None:
        return None
    recipe = _build_recipe(best[1], best[2], target_lab, model, formula, drop_total)
    # 连续最优比例取整后可能反而比单色更差；最终以实际执行的滴数评估。
    if single is not None and not recipe.direct:
        direct = _build_recipe(single[1], single[2], target_lab, model, formula, drop_total)
        if direct.delta_e <= recipe.delta_e + _FEW_COMPONENT_BONUS * (len(recipe.components) - 1):
            return direct
    return recipe


def build_direct_recipe(paint: PaintEntry,
                        target_lab: Sequence[float],
                        formula: str = "CIEDE2000") -> Recipe:
    """构造「单色直用」配方，用于锚定某条建议到指定色号。"""
    return _build_recipe([paint], [1.0], target_lab, "kubelka_munk", formula, 0)


def closest_entries(target_lab: Sequence[float],
                    entries: Sequence[PaintEntry],
                    n: int = 5,
                    formula: str = "CIEDE2000") -> List[Tuple[float, PaintEntry]]:
    """按单色 ΔE 返回离目标最近的 ``n`` 个色号（**不混合**，仅排序）。

    与 ``solve_recipe`` 的区别：这里回答的是「哪个现成色号最接近目标」，
    用于色号表快速对照、以及「直用」候选的预筛。返回 ``[(delta_e, entry), ...]``，
    已按 ΔE 升序、且 ``n <= 0`` 时返回空列表。
    """
    if n <= 0 or not entries:
        return []
    scored = [(delta_e(entry.lab, target_lab, formula), entry) for entry in entries]
    scored.sort(key=lambda item: item[0])
    return scored[:n]


def _build_recipe(entries: Sequence[PaintEntry],
                  weights: Sequence[float],
                  target_lab: Sequence[float],
                  model: str,
                  formula: str,
                  drop_total: int) -> Recipe:
    total = sum(max(0.0, float(w)) for w in weights) or 1.0
    proportions = [max(0.0, float(w)) / total for w in weights]
    drops = proportions_to_drops(proportions, drop_total)
    active = [(entry, drop) for entry, drop in zip(entries, drops) if drop > 0]
    total_drops = sum(drop for _, drop in active)
    entries = [entry for entry, _ in active]
    drops = [drop for _, drop in active]
    proportions = [drop / total_drops for drop in drops]

    linears = [item[1] for item in _prepare(entries)]
    mixed_linear = _mix_many(linears, proportions, model)
    mixed_rgb = linear_to_rgb(mixed_linear)
    mixed_lab = rgb_to_lab(mixed_rgb)
    value = delta_e(mixed_lab, target_lab, formula)

    components = [
        RecipeComponent(
            paint=entry,
            proportion=proportion,
            drops=drop,
            percent=proportion * 100.0,
        )
        for entry, proportion, drop in zip(entries, proportions, drops)
    ]
    return Recipe(
        components=components,
        mixed_rgb=mixed_rgb,
        mixed_lab=mixed_lab,
        delta_e=value,
        formula=formula,
        model=model,
        direct=len(components) == 1,
    )


def proportions_to_drops(proportions: Sequence[float], total: int = 20) -> List[int]:
    """把连续比例换算成整数滴数，总和尽量等于 ``total``。

    规则：
    * 比例为 0 的组分直接给 0 滴（不强行凑 1，避免显示“1 滴占 0% 的漆”）；
    * 比例 > 0 的组分至少 1 滴；
    * 通过就近增减把总和精确凑到 ``total``，且只动有效（比例 > 0）的组分。
    """
    count = len(proportions)
    if count == 0:
        return []
    total = max(count, int(total))
    is_real = [p > 0 for p in proportions]
    raw = [0 if p <= 0 else max(1, int(round(p * total))) for p in proportions]
    real_indices = [i for i in range(count) if is_real[i]]
    if not real_indices:  # 退化输入（全 0）：平均分配，保证不返回全 0
        return [total // count + (1 if i < total % count else 0) for i in range(count)]

    diff = total - sum(raw)
    order = sorted(real_indices, key=lambda i: -proportions[i])
    iteration = 0
    idx = 0
    while diff != 0 and iteration < _MAX_DROP_ITERATIONS:
        i = order[idx % len(real_indices)]
        if diff > 0:
            raw[i] += 1
            diff -= 1
        elif raw[i] > 1:
            raw[i] -= 1
            diff += 1
        else:
            # 该有效组分已到 1 滴下限，跳过它继续找还能调整的组分
            idx += 1
            iteration += 1
            continue
        idx += 1
        iteration += 1
    return raw
