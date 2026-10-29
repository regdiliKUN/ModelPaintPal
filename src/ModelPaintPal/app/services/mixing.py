# -*- coding: utf-8 -*-
"""涂料混合模型。

模型涂装的调色是**减色混合**，直接对 sRGB 做加权平均会高估亮度。
这里提供两种近似：

* ``kubelka_munk``：把反射率换算成 K/S 再加权平均，最贴近不透明漆的实干效果，
  是本应用的默认模型；
* ``linear_rgb``：在线性光空间做加权平均，适用于透明漆/墨水的叠加估算。

两种模型都在**线性光**下计算，避免伽马带来的偏差。
"""

from __future__ import annotations

import math
from typing import Sequence, Tuple

from ..core.color_models import linear_to_rgb, normalize_rgb, rgb_to_linear

__all__ = [
    "mix_colors", "mix_lab_approx", "MIXING_MODELS", "describe_model",
    "short_model_name",
    "_mix_linears", "_profile_of", "_mix_profiles",
]

_REFLECTANCE_MIN = 0.004
_REFLECTANCE_MAX = 0.996

MIXING_MODELS = ("kubelka_munk", "linear_rgb")


def _clamp_reflectance(value: float) -> float:
    return max(_REFLECTANCE_MIN, min(_REFLECTANCE_MAX, value))


def _reflectance_to_kubelka(reflectance: float) -> float:
    r = _clamp_reflectance(reflectance)
    return (1.0 - r) ** 2 / (2.0 * r)


def _kubelka_to_reflectance(kubelka: float) -> float:
    k = max(0.0, kubelka)
    return _clamp_reflectance(1.0 + k - ((k ** 2) + 2.0 * k) ** 0.5)


def _all_finite(seq: Sequence[float]) -> bool:
    return all(isinstance(v, (int, float)) and math.isfinite(v) for v in seq)


def mix_colors(colors: Sequence[Sequence[float]],
               weights: Sequence[float],
               model: str = "kubelka_munk") -> Tuple[int, int, int]:
    """按比例混合若干颜色，返回混合后的 sRGB。

    ``weights`` 会自动归一化，顺序与 ``colors`` 一致。
    """
    if not colors:
        raise ValueError("至少需要一种颜色参与混合")
    if len(colors) != len(weights):
        raise ValueError("颜色数量与权重数量不一致")
    # 非有限值（NaN/inf）会让 K/S 或线性光计算污染整段搜索结果，必须尽早拒绝
    if not all(_all_finite(c) for c in colors):
        raise ValueError("颜色分量必须都是有限实数")
    if not _all_finite(weights):
        raise ValueError("权重必须都是有限实数")

    total_weight = float(sum(max(0.0, float(w)) for w in weights))
    if total_weight <= 0.0:
        raise ValueError("权重之和必须大于 0")

    if len(colors) == 1:
        # 单色混合应和多色路径保持完全一致的输出约定（四舍五入 + 钳制到 0-255），
        # 此前用 int() 截断会在浮点输入下与多色路径结果不一致。
        return normalize_rgb(colors[0])

    normalized = [max(0.0, float(w)) / total_weight for w in weights]
    linears = [rgb_to_linear(color) for color in colors]
    return linear_to_rgb(_mix_linears(linears, normalized, model))


def _mix_linears(linears: Sequence[Sequence[float]],
                 weights: Sequence[float],
                 model: str = "kubelka_munk") -> Tuple[float, float, float]:
    """在线性光空间按权重混合任意数量的颜色（核心算法，唯一实现）。

    ``linears`` 为已转换好的线性光三元组；``weights`` 不需归一化（内部会归一）。
    两种模型都在线性光下计算，避免伽马带来的偏差：
    * ``kubelka_munk``：先转 K/S 再加权平均，最贴近不透明漆实干效果（默认）；
    * ``linear_rgb``：直接线性加权平均，适合透明漆/墨水叠加。
    """
    total = float(sum(weights)) or 1.0
    mixed = [0.0, 0.0, 0.0]
    for channel in range(3):
        if model == "linear_rgb":
            acc = sum(lin[channel] * w for lin, w in zip(linears, weights)) / total
        else:  # kubelka_munk
            acc = sum(_reflectance_to_kubelka(lin[channel]) * w
                      for lin, w in zip(linears, weights)) / total
            acc = _kubelka_to_reflectance(acc)
        mixed[channel] = acc
    return (mixed[0], mixed[1], mixed[2])


def _profile_of(linear: Sequence[float], model: str = "kubelka_munk") -> Tuple[float, float, float]:
    """把线性光色预转成「混合工作向量」。

    * ``kubelka_munk``：向量是 K/S（含 ``**2`` 与除法），是整个混合里最贵的一步；
    * ``linear_rgb``：向量就是线性光本身。

    配方搜索会对同一批候选色反复混合上万次，把这一步提到外层只算一次，
    后续每次混合就退化成「加权平均 + 一次开方」。
    """
    if model == "linear_rgb":
        return (linear[0], linear[1], linear[2])
    return (
        _reflectance_to_kubelka(linear[0]),
        _reflectance_to_kubelka(linear[1]),
        _reflectance_to_kubelka(linear[2]),
    )


def _mix_profiles(profiles: Sequence[Sequence[float]],
                  weights: Sequence[float],
                  model: str = "kubelka_munk") -> Tuple[float, float, float]:
    """用法与 ``_mix_linears`` 相同，但入参是 ``_profile_of`` 预转好的向量。

    这是配方搜索的**最内层热函数**（单次 suggest 调用上万次）。实现上：
    * 把 ``model`` 判断提到循环外，避免每个通道都判一次；
    * 用单趟累加代替「三趟 zip+生成器求和」，减少 Python 层对象开销；
    * 先乘 ``1/total`` 再累加，与原地 ``/total`` 数学等价。
    """
    total = float(sum(weights)) or 1.0
    inv = 1.0 / total
    m0 = m1 = m2 = 0.0
    for (p0, p1, p2), w in zip(profiles, weights):
        w *= inv
        m0 += p0 * w
        m1 += p1 * w
        m2 += p2 * w
    if model == "linear_rgb":
        return (m0, m1, m2)
    return (_kubelka_to_reflectance(m0), _kubelka_to_reflectance(m1), _kubelka_to_reflectance(m2))


def mix_lab_approx(colors: Sequence[Sequence[float]],
                   weights: Sequence[float],
                   model: str = "kubelka_munk") -> Tuple[float, float, float]:
    """混合后返回 Lab，避免调用方重复转换。"""
    from ..core.color_models import rgb_to_lab

    return rgb_to_lab(mix_colors(colors, weights, model))


def describe_model(model: str) -> str:
    return {
        "kubelka_munk": "Kubelka-Munk 三通道近似（默认，需试喷验证）",
        "linear_rgb": "线性光平均（数字颜色对比，非实漆预测）",
    }.get(model, model)


def short_model_name(model: str) -> str:
    """模型短名，给「一行内要写清楚」的场合用（剪贴板标题、导出表头）。

    ``describe_model`` 是给设置页解释用的长句，塞进标题会套出一层括号；
    两处口径必须同源，否则同一个模型在设置页和导出里叫两个名字。
    """
    return {
        "kubelka_munk": "Kubelka-Munk 减色模型",
        "linear_rgb": "线性光平均",
    }.get(model, model)
