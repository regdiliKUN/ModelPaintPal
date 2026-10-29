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
from . import vector_scan
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

# 双色细化最多还能在粗扫最优点附近压低多少 ΔE。
# 细化窗口只有粗扫步长的一半（±1/(2·_COARSE_STEPS) 的 t 区间），ΔE 在该区间
# 内近似二次型，改善量被曲率限制在远小于 1 的范围内；取 1.5 作为保守上界，
# 只有当粗扫最优点已经比当前最优差出这个余量时才跳过细化。
_PAIR_REFINE_MARGIN = 1.5

# 三色细化的余量。与双色不同，三色的细化窗口只有 ±_TRIPLE_REFINE_WIN 档
# （±0.03 的权重区间，仅覆盖粗格 1/10 的 30%），可改善量比双色更小；实测把余量
# 从 0 调到 1.5，12 个目标色 × 6 条建议的配方与 ΔE 完全不变、耗时也无可测差异
# （见 tests/test_search_cache.py 的三色剪枝用例），因此保留更省的 0。
# 单独列成常量而不是内联 0，是为了让「为什么两者不一样」有地方写清楚，
# 也让这条结论可以被测试直接改参数验证。
_TRIPLE_REFINE_MARGIN = 0.0

# 少于此数的色号对不值得开向量化（一次数组运算的固定开销 ≈ 3 对的标量评估）
_VECTOR_MIN_PAIRS = 8
_VECTOR_MIN_TRIPLES = 6

# 色号对缓存的两个哨兵：只做过粗扫 / 细化后配比越界作废
_UNREFINED = object()
_INVALID = object()


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


def _coarse_pair(pair, target_lab, model, de_fn):
    """双色粗扫：返回 ``(最优 t, 该 t 下的 ΔE)``，``t`` 是第二个组分的体积分数。"""
    best_t, best_v = 0.5, None
    for step in range(_COARSE_STEPS + 1):
        t = step / _COARSE_STEPS
        value = _de_of_profiles(pair, (1.0 - t, t), target_lab, model, de_fn)
        if best_v is None or value < best_v:
            best_v, best_t = value, t
    return best_t, best_v


def _refine_pair(pair, coarse_t, coarse_v, target_lab, model, de_fn):
    """在粗扫最优点两侧各半个粗格内细化，返回 ``(ΔE, t)`` 或 ``_INVALID``。"""
    span = 1.0 / _COARSE_STEPS
    for step in range(-_REFINE_STEPS, _REFINE_STEPS + 1):
        t = coarse_t + span * step / _REFINE_STEPS
        if not 0.0 <= t <= 1.0:
            continue
        value = _de_of_profiles(pair, (1.0 - t, t), target_lab, model, de_fn)
        if value < coarse_v:
            coarse_v, coarse_t = value, t
    # 只保留有效配比（各组分不低于 5%，避免出现「1 滴兑 20 滴」的废方案）
    if coarse_t < 0.05 or coarse_t > 0.95:
        return _INVALID
    return (coarse_v, coarse_t)


def _best_pair(prepared, profiles, target_lab, model, de_fn,
               bound: float = float("inf"), cache: Optional[dict] = None,
               prefill: Optional[dict] = None):
    """双色搜索。

    ``bound`` 是「还值得继续找」的 ΔE 上界（来自单色最优值）：粗扫最优点已经
    比当前最优差出 ``_PAIR_REFINE_MARGIN`` 以上时，细化不可能把它救回来，直接
    跳过。细化占双色搜索约 45% 的 ΔE 评估量，实测约 85% 的色号对会在这里被跳过。

    ``cache`` 让**同一次** ``suggest`` 里的多个锚点复用已经算过的色号对：同一
    品牌下各锚点的候选池高度重叠（``_pool_for`` 只是把锚点换到队首），实测
    720 个色号对槽位里只有 360 个是不同的。

    缓存键是**有顺序**的 ``(uid_i, uid_j)``，而不是排序后的 uid 对：细化是
    「边走边移动中心」的局部搜索，结果与顺序有关（A→B 与 B→A 会落到不同的
    局部点，ΔE 相差可达 1e-3）。按排序后的对缓存会悄悄改变配方结果，这里
    宁可少命中也不改数。各锚点的池内顺序都沿用全局排序，因此有序键的命中率
    与无序键基本一致。
    """
    best = None
    for i, j in combinations(range(len(prepared)), 2):
        entry_i, entry_j = prepared[i][0], prepared[j][0]
        pair = (profiles[i], profiles[j])
        key = (entry_i.uid, entry_j.uid)

        slot = cache.get(key) if cache is not None else None
        if slot is None and prefill is not None:
            # 向量化预算好的整池粗扫结果（见 vector_scan）：省掉这一对的 21 次评估
            grid = prefill.get((i, j))
            if grid is not None:
                slot = {"t": grid[0], "v": grid[1], "result": _UNREFINED}
                if cache is not None:
                    cache[key] = slot
        if slot is None:
            coarse_t, coarse_v = _coarse_pair(pair, target_lab, model, de_fn)
            slot = {"t": coarse_t, "v": coarse_v, "result": _UNREFINED}
            if cache is not None:
                cache[key] = slot

        result = slot["result"]
        if result is _UNREFINED:
            current = best[0] if best is not None else bound
            if slot["v"] > current + _PAIR_REFINE_MARGIN:
                # 保留 _UNREFINED：后续若上界放松（不同锚点的单色最优不同），
                # 这里还能补做细化，不会把结论钉死。
                continue
            result = _refine_pair(pair, slot["t"], slot["v"],
                                  target_lab, model, de_fn)
            slot["result"] = result
        if result is _INVALID:
            continue
        value, t = result
        if best is None or value < best[0]:
            best = (value, (entry_i, entry_j), (1.0 - t, t))
    return best


def _coarse_triple(triple, target_lab, model, de_fn, candidates=None):
    """三色粗扫：在权重单纯形上按 1/_TRIPLE_GRID 铺网格，返回 ``(ΔE, 权重三元组)``。

    ``candidates`` 给定时只评估这些权重（由 ``vector_scan`` 筛出的候选），并按给定
    顺序取**第一个**最小值——与全网格扫描的平局规则完全一致。这样向量化只负责
    「排除绝大多数网格点」，裁决仍是标量，配方不会因为浮点尾数而漂移。
    """
    grid = _TRIPLE_GRID
    best_v, best_w = None, (1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0)
    if candidates is not None:
        for weights in candidates:
            value = _de_of_profiles(triple, weights, target_lab, model, de_fn)
            if best_v is None or value < best_v:
                best_v, best_w = value, weights
        return best_v, best_w
    for i_w in range(grid + 1):
        for j_w in range(grid + 1 - i_w):
            k_w = grid - i_w - j_w
            weights = (i_w / grid, j_w / grid, k_w / grid)
            value = _de_of_profiles(triple, weights, target_lab, model, de_fn)
            if best_v is None or value < best_v:
                best_v, best_w = value, weights
    return best_v, best_w


def _triple_prefill(prepared, profiles, target_lab, model, formula, pool_size, cache):
    """向量化筛出「缓存里还没有的」三元组的候选网格点；不值得时返回 ``None``。

    ``formula`` 必须传下去：向量化只实现了 CIEDE2000，别的公式要让它自己返回 None
    回退标量路径。漏传的话 CIE76 会拿到「按 CIEDE2000 算出来的候选」——候选本身就
    是错的，结果自然错（实测会让 3 块指纹变化）。
    """
    if not vector_scan.AVAILABLE:
        return None
    pool_n = min(pool_size, _TRIPLE_POOL)
    missing = [
        (i, j, k) for i, j, k in combinations(range(pool_n), 3)
        if cache is None
        or (prepared[i][0].uid, prepared[j][0].uid, prepared[k][0].uid) not in cache
    ]
    if len(missing) < _VECTOR_MIN_TRIPLES:
        return None
    return vector_scan.coarse_triple_candidates(
        profiles[:pool_n], target_lab, model, _TRIPLE_GRID, missing, formula)


def _refine_triple(triple, coarse_v, base, target_lab, model, de_fn):
    """在粗扫最优点邻域 ±_TRIPLE_REFINE_WIN 档内细化，返回 ``(ΔE, 权重)`` 或 ``_INVALID``。"""
    step = 1.0 / _TRIPLE_REFINE
    refined_v, refined_w = coarse_v, base
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
            if value < refined_v:
                refined_v, refined_w = value, (wi, wj, wk)
    # 只保留有效配比（各组分不低于 4%，否则等于把某个组分从配方里删掉）
    if min(refined_w) < 0.04:
        return _INVALID
    return refined_v, refined_w


def _best_triple(prepared, profiles, target_lab, model, de_fn, current_best=float("inf"),
                 cache: Optional[dict] = None, prefill: Optional[dict] = None):
    """三色搜索。

    ``current_best`` 为当前已知最优 ΔE（含少组分奖励）。粗扫阶段若某三色的
    最优点已经劣于 ``current_best``，就**跳过整个细化**（细化只在最优邻域
    ±_TRIPLE_REFINE_WIN 档内扫，不再铺满 21×21），从而把大多数无望三色组合
    的代价从「粗扫 + 全细化」降到「仅粗扫」。这是 suggest 热路径上最大的单项
    加速来源（实测单次 suggest 的 ΔE 评估次数下降约一半）。

    剪枝余量与双色不同（见 ``_TRIPLE_REFINE_MARGIN``）：三色细化窗口更窄、
    可改善量更小，实测放宽余量到 1.5 结果完全不变，故取 0 以省时间。

    ``cache`` 与双色共用同一份 dict：**2 元组键 = 色号对，3 元组键 = 色号三元组**，
    长度不同天然不会撞。缓存键有顺序（与双色同理：细化是「边走边移动中心」的
    局部搜索，A→B→C 与 C→B→A 会落到不同局部点），所以按 uid 原始顺序存。

    ``prefill`` 为向量化预算好的整池粗扫结果（``{(i, j): (t, ΔE)}``），命中时
    直接建槽、跳过这一对的 21 次标量评估；没有 numpy 或非 CIEDE2000 公式时为 None。

    命中缓存的收益比双色小：三色池只取前 ``_TRIPLE_POOL`` 条，各锚点之间重叠
    约 7/8，实测能省掉三成左右的三元组评估。
    """
    pool_size = min(len(prepared), _TRIPLE_POOL)
    best = None
    for i, j, k in combinations(range(pool_size), 3):
        triple = (profiles[i], profiles[j], profiles[k])
        entries = (prepared[i][0], prepared[j][0], prepared[k][0])
        key = (entries[0].uid, entries[1].uid, entries[2].uid)

        slot = cache.get(key) if cache is not None else None
        if slot is None:
            candidates = prefill.get((i, j, k)) if prefill is not None else None
            coarse_v, coarse_w = _coarse_triple(triple, target_lab, model, de_fn, candidates)
            slot = {"v": coarse_v, "w": coarse_w, "result": _UNREFINED}
            if cache is not None:
                cache[key] = slot

        result = slot["result"]
        if result is _UNREFINED:
            # 粗扫最优点已经追不上当前最优 → 放弃该三色，连细化都省了。
            # 保留 _UNREFINED：上界在不同锚点间会变，别把结论钉死。
            if slot["v"] >= current_best + _TRIPLE_REFINE_MARGIN:
                continue
            result = _refine_triple(triple, slot["v"], slot["w"],
                                    target_lab, model, de_fn)
            slot["result"] = result
        if result is _INVALID:
            continue
        value, weights = result
        if best is None or value < best[0]:
            best = (value, entries, weights)
    return best


def _search_best(prepared, profiles, target_lab, model, de_fn,
                 pool_size: int, max_components: int, single, search_cache=None,
                 prefill: Optional[dict] = None, formula: str = "CIEDE2000"):
    """在「单色 / 双色 / 三色」之间选出最优方案。

    返回 ``(best, scored_single)``：``best`` 形如 ``(ΔE, entries, weights)``；
    ``scored_single`` 是**含少组分奖励**的排序分值，供三色搜索剪枝复用。
    """
    best = single
    scored_single = single[0] if single else float("inf")

    # 双色搜索必须同时受「候选足够」与「用户允许 2 组分」两个约束；
    # 此前只判了 len(pool) >= 2，于是 max_components=1 时仍可能返回 2 色方案
    # （是否触发取决于候选池顺序），是一个会随数据顺序偶发的正确性缺陷。
    if max_components >= 2 and pool_size >= 2:
        # 双色方案要赢过单色，得便宜掉一个「少组分奖励」，所以上界先扣掉它。
        pair = _best_pair(prepared, profiles, target_lab, model, de_fn,
                          bound=scored_single - _FEW_COMPONENT_BONUS,
                          cache=search_cache, prefill=prefill)
        if pair and pair[0] + _FEW_COMPONENT_BONUS < scored_single:
            best, scored_single = pair, pair[0] + _FEW_COMPONENT_BONUS

    if max_components >= 3 and pool_size >= 3:
        triple_prefill = _triple_prefill(prepared, profiles, target_lab, model,
                                        formula, pool_size, search_cache)
        triple = _best_triple(prepared, profiles, target_lab, model, de_fn,
                              current_best=scored_single, cache=search_cache,
                              prefill=triple_prefill)
        if triple and triple[0] + 2 * _FEW_COMPONENT_BONUS < scored_single:
            best = triple
    return best, scored_single


def _pair_prefill(prepared, profiles, target_lab, model, formula, cache):
    """向量化预算「缓存里还没有的」色号对粗扫；不值得开数组时返回 ``None``。

    只算缺的那些：第二个锚点起通常只剩十几对，而一次向量化的固定开销约等于
    3 对的标量评估，太少就不划算了。
    """
    if not vector_scan.AVAILABLE:
        return None
    missing = [
        (i, j) for i, j in combinations(range(len(prepared)), 2)
        if cache is None or (prepared[i][0].uid, prepared[j][0].uid) not in cache
    ]
    if len(missing) < _VECTOR_MIN_PAIRS:
        return None
    return vector_scan.coarse_pair_best(
        profiles, target_lab, model, _COARSE_STEPS, formula, pairs=missing)


def solve_recipe(target_lab: Sequence[float],
                 candidates: Sequence[PaintEntry],
                 max_components: int = 3,
                 model: str = "kubelka_munk",
                 formula: str = "CIEDE2000",
                 drop_total: int = 20,
                 tolerance: float = 3.0,
                 prepared: Optional[List] = None,
                 pair_cache: Optional[dict] = None) -> Optional[Recipe]:
    """求解最优配方；候选不足或全部不可用时返回 ``None``。

    ``prepared`` 为已预计算的 ``[(entry, linear_rgb), ...]``（顺序需与 ``candidates``
    一致）。由调用方（如 ``PaintMatcher.suggest``）一次性算好并复用，可避免对同一个
    候选池反复做 RGB→线性光的转换（主要性能瓶颈之一）。

    ``pair_cache`` 由调用方持有（一次 ``suggest`` 一个），用于跨锚点复用**双色与
    三色**搜索的结果（2 元组键 = 色号对，3 元组键 = 色号三元组，长度不同不会撞）；
    不传则退化为每次重算，行为与旧版逐位一致。参数名沿用 ``pair_cache`` 是为了
    不破坏既有调用方，它现在同时服务两种搜索。
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

    prefill = _pair_prefill(prepared, profiles, target_lab, model, formula, pair_cache)

    single = _best_single(prepared, target_lab, de_fn)
    if single is not None and single[0] <= tolerance:
        recipe = _build_recipe(single[1], single[2], target_lab, model, formula, drop_total)
        recipe.direct = True
        return recipe

    best, _scored_single = _search_best(prepared, profiles, target_lab, model, de_fn,
                                        len(pool), max_components, single,
                                        search_cache=pair_cache, prefill=prefill,
                                        formula=formula)

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
    # 公式只解析一次：这个循环按全库条数跑，逐次 delta_e() 里的字符串处理是纯浪费
    de_fn = resolve_delta_e(formula)
    scored = [(de_fn(entry.lab, target_lab), entry) for entry in entries]
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
