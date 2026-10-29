# -*- coding: utf-8 -*-
"""双色粗扫的向量化实现（numpy 可用时启用）。

为什么单独一个模块：配方搜索里最热的一步是「对每个色号对，在 21 档配比上各算一次
ΔE」。逐个算的话，每次都要走一遍「K/S 加权 → 反射率开方 → XYZ → Lab → CIEDE2000」，
其中绝大部分是逐元素运算——正是 numpy 擅长的事。把整池色号对（16 条候选 → 120 对）
一次性铺成 ``(120, 21, 3)`` 的数组后，整段只需十几次数组运算。

**只做粗扫，不做细化**：细化只有十几到几十次评估，向量化的固定开销（数组分配）
反而更贵。

数值一致性：这里刻意让每一步的运算顺序与标量实现（``recipe_engine._de_of_profiles``
→ ``mixing._mix_profiles`` → ``color_models.linear_to_lab`` → ``delta_e.delta_e_2000``）
逐项对齐，实测 720 个色号对的 ΔE 最大差 3.9e-14（浮点 ULP 级）、最优配比完全一致。
``tests/test_vector_scan.py`` 里有一条与标量实现逐对比较的等价性测试兜底。

numpy 缺失、或用了非 CIEDE2000 公式时返回 ``None``，调用方回退到标量路径——性能是
可选项，正确性不是。

三色粗扫用的是另一套做法（``coarse_triple_candidates``）：三色的权重网格（1/10 分辨率、
66 个点）里存在大量近平局，直接取向量化的 argmin 会因 1e-14 量级的差异选中另一个
网格点，细化从不同起点出发，最终**换掉配方里的一支漆**——实测会让 68 块结果指纹里
6 块变化。所以三色只让向量化负责「找出所有可能是最优的网格点」（容差内的全部候选），
真正的比较仍由标量实现按原网格顺序裁决。速度拿到了，平局规则也没变。
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

from ..core.color_models import WHITE_D65
from ..core.logging_setup import get_logger

try:  # numpy 是可选依赖（见 requirements.txt）
    import numpy as _np
except ImportError:  # pragma: no cover - 取决于安装环境
    _np = None

logger = get_logger(__name__)

__all__ = ["AVAILABLE", "coarse_pair_best", "coarse_triple_candidates",
           "simplex_grid", "list_pairs"]

AVAILABLE = _np is not None

_EPSILON = 216.0 / 24389.0
_KAPPA = 24389.0 / 27.0
_DEG2RAD = math.pi / 180.0
_TWENTY5_7 = 25.0 ** 7
_REFLECTANCE_MIN = 0.004
_REFLECTANCE_MAX = 0.996


def _lab_from_linear(arr):
    """``(..., 3)`` 线性光 → ``(..., 3)`` Lab，与 ``linear_to_lab`` 同序。"""
    np = _np
    r = np.clip(arr[..., 0], 0.0, 1.0)
    g = np.clip(arr[..., 1], 0.0, 1.0)
    b = np.clip(arr[..., 2], 0.0, 1.0)
    x = (r * 0.4124564 + g * 0.3575761 + b * 0.1804375) * 100.0
    y = (r * 0.2126729 + g * 0.7151522 + b * 0.0721750) * 100.0
    z = (r * 0.0193339 + g * 0.1191920 + b * 0.9503041) * 100.0

    def _f(t):
        return np.where(t > _EPSILON, t ** (1.0 / 3.0), (_KAPPA * t + 16.0) / 116.0)

    fx = _f(x / WHITE_D65[0])
    fy = _f(y / WHITE_D65[1])
    fz = _f(z / WHITE_D65[2])
    return np.stack([116.0 * fy - 16.0, 500.0 * (fx - fy), 200.0 * (fy - fz)], axis=-1)


def _delta_e_2000(lab, target) -> object:
    """``lab``: (..., 3)，``target``: (3,) → (...,) 的 CIEDE2000。"""
    np = _np
    l1, a1, b1 = lab[..., 0], lab[..., 1], lab[..., 2]
    l2, a2, b2 = float(target[0]), float(target[1]), float(target[2])

    c1 = np.hypot(a1, b1)
    c2 = math.hypot(a2, b2)
    c_bar = (c1 + c2) / 2.0
    cb7 = c_bar ** 7
    g = np.where(c_bar > 0, 0.5 * (1.0 - np.sqrt(cb7 / (cb7 + _TWENTY5_7))), 0.0)
    a1p = (1.0 + g) * a1
    a2p = (1.0 + g) * a2
    c1p = np.hypot(a1p, b1)
    c2p = np.hypot(a2p, b2)

    def _hue(ap, bb):
        angle = np.arctan2(bb, ap)
        angle = np.where((ap == 0.0) & (bb == 0.0), 0.0, angle)
        return np.where(angle < 0.0, angle + 2.0 * math.pi, angle)

    h1p, h2p = _hue(a1p, b1), _hue(a2p, b2)
    dl_p = l2 - l1
    dc_p = c2p - c1p
    no_chroma = (c1p * c2p) == 0.0
    diff = h2p - h1p
    dh_p = np.where(
        no_chroma, 0.0,
        np.where(np.abs(diff) <= math.pi, diff,
                 np.where(diff > math.pi, diff - 2.0 * math.pi, diff + 2.0 * math.pi)))
    dh_p = 2.0 * np.sqrt(c1p * c2p) * np.sin(dh_p / 2.0)

    l_bar_p = (l1 + l2) / 2.0
    c_bar_p = (c1p + c2p) / 2.0
    hue_sum = h1p + h2p
    h_bar_p = np.where(
        no_chroma, hue_sum,
        np.where(np.abs(h1p - h2p) <= math.pi, hue_sum / 2.0,
                 np.where(hue_sum < 2.0 * math.pi,
                          (hue_sum + 2.0 * math.pi) / 2.0,
                          (hue_sum - 2.0 * math.pi) / 2.0)))

    t = (1.0
         - 0.17 * np.cos(h_bar_p - 30.0 * _DEG2RAD)
         + 0.24 * np.cos(2.0 * h_bar_p)
         + 0.32 * np.cos(3.0 * h_bar_p + 6.0 * _DEG2RAD)
         - 0.20 * np.cos(4.0 * h_bar_p - 63.0 * _DEG2RAD))
    delta_theta = 30.0 * np.exp(-(((h_bar_p - 275.0 * _DEG2RAD) / (25.0 * _DEG2RAD)) ** 2))
    cbp7 = c_bar_p ** 7
    r_c = np.where(c_bar_p > 0, 2.0 * np.sqrt(cbp7 / (cbp7 + _TWENTY5_7)), 0.0)
    l_bar_m50_sq = (l_bar_p - 50.0) ** 2
    s_l = 1.0 + (0.015 * l_bar_m50_sq) / np.sqrt(20.0 + l_bar_m50_sq)
    s_c = 1.0 + 0.045 * c_bar_p
    s_h = 1.0 + 0.015 * c_bar_p * t
    r_t = -np.sin(2.0 * delta_theta * _DEG2RAD) * r_c
    return np.sqrt((dl_p / s_l) ** 2 + (dc_p / s_c) ** 2 + (dh_p / s_h) ** 2
                   + r_t * (dc_p / s_c) * (dh_p / s_h))


def _kubelka_to_reflectance(values):
    np = _np
    k = np.maximum(0.0, values)
    r = 1.0 + k - np.sqrt(k ** 2 + 2.0 * k)
    return np.clip(r, _REFLECTANCE_MIN, _REFLECTANCE_MAX)


def _mix_grid(profiles, pairs, weights_a, weights_b):
    """按给定色号对混合：``(N,3)`` 工作向量 × ``(T,)`` 权重 → ``(P,T,3)``。"""
    pi = profiles[pairs[:, 0]][:, None, :]
    pj = profiles[pairs[:, 1]][:, None, :]
    wa = weights_a[None, :, None]
    wb = weights_b[None, :, None]
    return pairs, wa * pi + wb * pj


def coarse_pair_best(profiles: Sequence[Sequence[float]],
                     target_lab: Sequence[float],
                     model: str,
                     steps: int,
                     formula: str = "CIEDE2000",
                     pairs: Optional[Sequence[Tuple[int, int]]] = None,
                     ) -> Optional[Dict[Tuple[int, int], Tuple[float, float]]]:
    """一次算出指定色号对在 ``steps+1`` 档配比上的最优 ΔE。

    返回 ``{(i, j): (最优 t, 该 t 下的 ΔE)}``，``t`` 是第二个组分（j）的体积分数；
    不可用时返回 ``None``，调用方必须回退到标量实现。

    ``pairs`` 为 None 时算全部组合；调用方通常只传「缓存里还没有的那些对」，
    这样第二个锚点起只需算十几对，不必把已经算过的再算一遍。
    """
    if not AVAILABLE or formula.upper() != "CIEDE2000" or len(profiles) < 2:
        return None
    np = _np
    if pairs is None:
        pairs = list_pairs(len(profiles))
    if not pairs:
        return {}
    pair_array = np.array(pairs, dtype=int)

    ts = np.arange(steps + 1) / steps
    weights_b = ts
    weights_a = 1.0 - ts

    pair_array, mixed = _mix_grid(np.asarray(profiles, dtype=float), pair_array,
                                  weights_a, weights_b)
    if model == "linear_rgb":
        linear = mixed
    else:
        linear = _kubelka_to_reflectance(mixed)
    lab = _lab_from_linear(linear)
    values = _delta_e_2000(lab, target_lab)          # (P, T)

    best = values.argmin(axis=1)
    rows = np.arange(len(pair_array))
    return {
        (int(i), int(j)): (float(ts[k]), float(values[r, k]))
        for (i, j), r, k in zip(pair_array, rows, best)
    }


def list_pairs(n: int) -> List[Tuple[int, int]]:
    """与 ``itertools.combinations(range(n), 2)`` 同序的色号对列表（供测试对照）。"""
    return [(i, j) for i in range(n) for j in range(i + 1, n)]



def simplex_grid(grid: int) -> List[Tuple[float, float, float]]:
    """与标量 ``_coarse_triple`` 完全同序的权重表：``(i_w/grid, j_w/grid, k_w/grid)``。"""
    out = []
    for i_w in range(grid + 1):
        for j_w in range(grid + 1 - i_w):
            k_w = grid - i_w - j_w
            out.append((i_w / grid, j_w / grid, k_w / grid))
    return out


def coarse_triple_candidates(profiles: Sequence[Sequence[float]],
                             target_lab: Sequence[float],
                             model: str,
                             grid: int,
                             triples: Sequence[Tuple[int, int, int]],
                             formula: str = "CIEDE2000",
                             eps: float = 1e-9,
                             ) -> Optional[Dict[Tuple[int, int, int], List[Tuple[float, float, float]]]]:
    """为每个三元组找出「可能是最优」的网格点（按原网格顺序返回权重）。

    只做筛选，不做裁决：返回的是候选列表，调用方要用标量实现复算这几个点，
    再按同样的顺序取第一个最小值。这样向量化只承担「快速排除绝大多数网格点」，
    平局规则与纯标量实现逐位一致。

    ``eps`` 要大于向量化与标量之间的数值差（实测 ≤ 4e-14），又不能大到把真正
    不同的点拉进来——1e-9 两者都满足。
    """
    if not AVAILABLE or formula.upper() != "CIEDE2000" or len(profiles) < 3:
        return None
    np = _np
    if not triples:
        return {}

    weights = np.asarray(simplex_grid(grid), dtype=float)     # (T,3)
    total = weights.sum(axis=1)
    normalized = weights * (1.0 / total)[:, None]             # 与标量同样归一化

    idx = np.asarray(triples, dtype=int)                      # (P,3)
    picked = np.asarray(profiles, dtype=float)[idx]           # (P,3,3)
    mixed = (normalized[None, :, 0, None] * picked[:, 0, None, :]
             + normalized[None, :, 1, None] * picked[:, 1, None, :]
             + normalized[None, :, 2, None] * picked[:, 2, None, :])
    linear = mixed if model == "linear_rgb" else _kubelka_to_reflectance(mixed)
    values = _delta_e_2000(_lab_from_linear(linear), target_lab)   # (P,T)

    best = values.min(axis=1)
    out: Dict[Tuple[int, int, int], List[Tuple[float, float, float]]] = {}
    for row, triple in enumerate(map(tuple, idx)):
        keep = np.nonzero(values[row] <= best[row] + eps)[0]
        out[(int(triple[0]), int(triple[1]), int(triple[2]))] = [
            (float(weights[t, 0]), float(weights[t, 1]), float(weights[t, 2])) for t in keep
        ]
    return out
