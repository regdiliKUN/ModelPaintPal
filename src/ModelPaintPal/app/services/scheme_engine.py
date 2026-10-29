# -*- coding: utf-8 -*-
"""基础色配色方案引擎（纯逻辑，不依赖 Qt）。

把「吸到的基色」展开成几类经典配色方案（基础色盘 / 互补 / 分裂互补 / 三角 /
矩形四角 / 邻近 / 单色），每个方案色再复用 ``PaintMatcher`` 找出库内最适配的
**真实漆配方**（单色直用或 2–3 色调配），从而把"红黄蓝之类的基础配色"直接落到
你手头所有涂料品牌上。

色相旋转在 HSV 空间做；单色系在 HSL 空间只动明度。所有输出都是 0-255 的 RGB，
可直接喂给下面的匹配层与渲染层。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from ..core.color_models import (
    hsl_to_rgb, hsv_to_rgb, linear_to_rgb, normalize_rgb, rgb_to_hex, rgb_to_hsl,
    rgb_to_hsv, rgb_to_lab, rgb_to_linear,
)
from ..core.config import AppConfig
from ..core.delta_e import delta_e as _delta_e
from ..core.logging_setup import get_logger
from ..services.coverage import CoverageInput
from ..services.paint_matcher import PaintMatcher, PaintSuggestion, get_database
from ..services.recipe_engine import proportions_to_drops

logger = get_logger(__name__)

RGB = Tuple[int, int, int]

__all__ = [
    "SchemeType", "SCHEME_ORDER", "SCHEME_LABELS", "SCHEME_DESC",
    "SchemeColor", "SchemeStop", "generate_scheme_colors", "build_scheme",
    "default_param_for",
    # 基础漆调配（把任意目标色分解为红/黄/蓝/白/黑五瓶的配比）
    "MixRecipe", "MixComponent", "compute_base_mix",
]


class SchemeType:
    """配色方案类型（字符串常量，便于序列化与配置）。"""

    BASIC = "basic"               # 基础色盘：经典红/黄/蓝/白/黑
    COMPLEMENTARY = "complementary"
    SPLIT = "split"
    TRIADIC = "triadic"          # 三原色式三角（红/黄/蓝风）
    TETRADIC = "tetradic"        # 矩形四角
    ANALOGOUS = "analogous"      # 邻近色
    MONOCHROMATIC = "monochromatic"


# 下拉框顺序：基础色盘放第一个，最贴合"红黄蓝等等"的诉求
SCHEME_ORDER: List[Tuple[str, str, str]] = [
    (SchemeType.BASIC, "基础色盘",
     "经典基础色（红/黄/蓝/白/黑），给出每个基础色在库内的最近漆"),
    (SchemeType.COMPLEMENTARY, "互补色",
     "基色 + 色环正对面（180°），对比最强"),
    (SchemeType.SPLIT, "分裂互补",
     "基色 + 补色两侧（±30°），对比强但不刺眼"),
    (SchemeType.TRIADIC, "三角色",
     "基色 + 120° + 240°，三原色式均衡三角，最像红/黄/蓝的搭配"),
    (SchemeType.TETRADIC, "矩形四角",
     "两组互补色（±60° / 180°），四色最丰富"),
    (SchemeType.ANALOGOUS, "邻近色",
     "基色两侧相邻色相，和谐自然，适合做过渡与过渡高光"),
    (SchemeType.MONOCHROMATIC, "单色系",
     "同色相不同明度，统一干净，适合阴影/高光层次"),
]
SCHEME_LABELS = {key: label for key, label, _ in SCHEME_ORDER}
SCHEME_DESC = {key: desc for key, _, desc in SCHEME_ORDER}

# 需要"数量/步数"参数的方案（邻近色的色数、单色系的层次数）
_PARAM_SCHEMES = (SchemeType.ANALOGOUS, SchemeType.MONOCHROMATIC)
ANALOGOUS_DEFAULT = 5
MONOCHROMATIC_DEFAULT = 5


def default_param_for(scheme_type: str) -> int:
    """返回该方案类型的默认参数（仅邻近/单色有意义）。"""
    if scheme_type == SchemeType.ANALOGOUS:
        return ANALOGOUS_DEFAULT
    if scheme_type == SchemeType.MONOCHROMATIC:
        return MONOCHROMATIC_DEFAULT
    return 0


@dataclass
class SchemeColor:
    """一个方案色（角色名 + 颜色）。"""

    role: str
    rgb: RGB

    @property
    def hex(self) -> str:
        return rgb_to_hex(self.rgb)


@dataclass
class SchemeStop:
    """方案里的一个"停靠点"：角色 + 目标色 + 它在库内的最适配漆配方。"""

    role: str
    target_rgb: RGB
    suggestion: Optional[PaintSuggestion] = None

    @property
    def target_hex(self) -> str:
        return rgb_to_hex(self.target_rgb)


# ---------------------------------------------------------------------------
# 方案色生成（纯 HSV/HSL 旋转，不碰漆库）
# ---------------------------------------------------------------------------
def _rotated(hue: float, sat: float, val: float) -> RGB:
    """在 HSV 空间按给定色相/饱和度/明度生成一个 0-255 RGB。"""
    return hsv_to_rgb((hue % 360.0, max(0.0, min(100.0, sat)),
                       max(0.0, min(100.0, val))))


def _basic_palette() -> List[SchemeColor]:
    """经典基础色盘：红/黄/蓝/白/黑，最朴素的一组基础漆。

    这五瓶就是用户的"基础漆库"——其它颜色都靠它们调配。红/黄/蓝取鲜艳
    纯色；白/黑为无彩色的极亮/极暗，固定不随吸到的基色变化。
    """
    specs = [
        ("红", 0.0, 85.0, 90.0),
        ("黄", 54.0, 90.0, 92.0),
        ("蓝", 222.0, 85.0, 90.0),
        ("白", 0.0, 0.0, 100.0),
        ("黑", 0.0, 0.0, 6.0),
    ]
    return [SchemeColor(role, _rotated(h, s, v)) for role, h, s, v in specs]


def _analogous(base_h: float, base_s: float, base_v: float, count: int,
               step: float = 30.0) -> List[SchemeColor]:
    count = max(2, min(7, int(count)))
    half = (count - 1) / 2.0
    out: List[SchemeColor] = []
    for i in range(count):
        offset = (i - half) * step
        out.append(_rotated(base_h + offset, base_s, base_v))
    # 基色居中：把中间那个标成"基色"
    roles = [f"邻近 {i+1}" for i in range(count)]
    mid = count // 2
    roles[mid] = "基色"
    return [SchemeColor(r, c) for r, c in zip(roles, out)]


def _monochromatic(base_rgb: RGB, count: int) -> List[SchemeColor]:
    count = max(3, min(7, int(count)))
    h, s, l = rgb_to_hsl(base_rgb)
    # 围绕基色明度向暗、亮两侧均匀展布；明度已极端时由 _clamp 收敛
    span = 30.0  # 单侧最大偏移
    half = (count - 1) / 2.0
    out: List[SchemeColor] = []
    for i in range(count):
        offset = (i - half) / half * span if half else 0.0
        new_l = max(8.0, min(94.0, l + offset))
        # 极亮/极暗时略降饱和度，更接近真实漆的明暗层次
        new_s = s * (0.82 if new_l > 80 or new_l < 18 else 1.0)
        out.append(hsl_to_rgb((h, max(0.0, min(100.0, new_s)), new_l)))
    roles = [f"层次 {i+1}" for i in range(count)]
    mid = count // 2
    roles[mid] = "基色"
    return [SchemeColor(r, c) for r, c in zip(roles, out)]


def generate_scheme_colors(base_rgb: Sequence[int],
                           scheme_type: str,
                           param: int = 0) -> List[SchemeColor]:
    """从基色生成一组方案色（不含漆库匹配）。"""
    base = normalize_rgb(base_rgb)
    h, s, v = rgb_to_hsv(base)

    if scheme_type == SchemeType.BASIC:
        return _basic_palette()
    if scheme_type == SchemeType.COMPLEMENTARY:
        return [SchemeColor("基色", base),
                SchemeColor("互补色", _rotated(h + 180.0, s, v))]
    if scheme_type == SchemeType.SPLIT:
        return [SchemeColor("基色", base),
                SchemeColor("分裂互补 1", _rotated(h + 150.0, s, v)),
                SchemeColor("分裂互补 2", _rotated(h + 210.0, s, v))]
    if scheme_type == SchemeType.TRIADIC:
        return [SchemeColor("①", base),
                SchemeColor("②", _rotated(h + 120.0, s, v)),
                SchemeColor("③", _rotated(h + 240.0, s, v))]
    if scheme_type == SchemeType.TETRADIC:
        return [SchemeColor("①", base),
                SchemeColor("②", _rotated(h + 60.0, s, v)),
                SchemeColor("③", _rotated(h + 180.0, s, v)),
                SchemeColor("④", _rotated(h + 240.0, s, v))]
    if scheme_type == SchemeType.ANALOGOUS:
        return _analogous(h, s, v, param or ANALOGOUS_DEFAULT)
    if scheme_type == SchemeType.MONOCHROMATIC:
        return _monochromatic(base, param or MONOCHROMATIC_DEFAULT)

    logger.warning("未知方案类型 %r，回退到互补色", scheme_type)
    return [SchemeColor("基色", base),
            SchemeColor("互补色", _rotated(h + 180.0, s, v))]


# ---------------------------------------------------------------------------
# 落到真实漆库：每个方案色找最适配的漆配方
# ---------------------------------------------------------------------------
def build_scheme(matcher: PaintMatcher,
                 base_rgb: Sequence[int],
                 config: AppConfig,
                 brands: Optional[Sequence[str]] = None,
                 coverage_input: Optional[CoverageInput] = None,
                 scheme_type: str = SchemeType.BASIC,
                 param: int = 0,
                 max_results_per_stop: int = 1) -> List[SchemeStop]:
    """生成方案色，并为每个方案色求一次"最适配漆配方"。

    ``brands`` 语义与 ``PaintMatcher.suggest`` 一致（``None``=首选品牌，
    ``[]``=全库）；这样方案会自动跟随你在建议页选的品牌范围。
    返回 ``SchemeStop`` 列表，顺序与方案色一致。
    """
    colors = generate_scheme_colors(base_rgb, scheme_type, param)
    stops: List[SchemeStop] = []
    for color in colors:
        try:
            suggestions = matcher.suggest(
                target_rgb=color.rgb,
                config=config,
                brands=brands,
                coverage_input=coverage_input,
                max_results=max_results_per_stop,
            )
        except Exception as exc:  # 单停失败不应拖垮整页
            logger.exception("方案色 %s 求配方失败: %s", color.role, exc)
            suggestions = []
        best = suggestions[0] if suggestions else None
        stops.append(SchemeStop(role=color.role, target_rgb=color.rgb, suggestion=best))
    return stops


# ---------------------------------------------------------------------------
# 基础漆调配：把任意目标色分解为红/黄/蓝/白/黑五瓶基础漆的配比
# ---------------------------------------------------------------------------
@dataclass
class MixComponent:
    """配方里的一个基础漆组分（红/黄/蓝/白/黑）。"""

    role: str                       # 红 / 黄 / 蓝 / 白 / 黑
    base_rgb: RGB                   # 该基础漆的理想色（用于画混色条）
    weight: float                   # 0-1 体积分数
    percent: float                  # 百分比
    drops: int                     # 整数滴数
    suggestion: Optional[PaintSuggestion] = None  # 库内最适配的真实漆（含品牌）

    @property
    def target_hex(self) -> str:
        return rgb_to_hex(self.base_rgb)


@dataclass
class MixRecipe:
    """一份"用五瓶基础漆调出目标色"的配方。"""

    target_rgb: RGB
    predicted_rgb: RGB              # 按配比混出的近似色
    delta_e: float                  # 近似色与目标色的色差
    total_drops: int
    components: List[MixComponent]


# 五瓶基础漆的"理想色"——只用于减法混合计算与混色条着色，不参与真实漆匹配。
# 红/黄/蓝取纯正的画家基色，白/黑为极亮/极暗的无彩色。
_BASE_PAINTS: List[Tuple[str, RGB]] = [
    ("红", (200, 30, 35)),
    ("黄", (230, 200, 45)),
    ("蓝", (35, 70, 200)),
    ("白", (244, 244, 244)),
    ("黑", (18, 18, 18)),
]


def _srgb_to_ks(rgb: RGB) -> Tuple[float, float, float]:
    """sRGB 反射率 → Kubelka-Munk 的 K/S（每通道）。"""
    r, g, b = rgb_to_linear(rgb)
    out = []
    for c in (r, g, b):
        c = max(0.003, min(0.997, c))       # 避免除零 / 无穷
        out.append((1.0 - c) ** 2 / (2.0 * c))
    return (out[0], out[1], out[2])


def _ks_to_srgb(ks: Sequence[float]) -> RGB:
    """K/S → sRGB 反射率，反解 R = 1 + x - sqrt(x² + 2x)。"""
    out = []
    for k in ks:
        k = max(0.0, float(k))
        r = 1.0 + k - (k * k + 2.0 * k) ** 0.5
        out.append(max(0.0, min(1.0, r)))
    return linear_to_rgb((out[0], out[1], out[2]))


def _project_simplex(v: Sequence[float]) -> List[float]:
    """把向量投影到单纯形 {w≥0, Σw=1}（欧氏距离最小）。"""
    n = len(v)
    if n == 1:
        return [max(0.0, x) for x in v]
    if sum(v) <= 0:
        return [1.0 / n] * n
    u = sorted(v, reverse=True)
    cssv = []
    acc = 0.0
    for x in u:
        acc += x
        cssv.append(acc)
    rho = 1
    for i in range(1, n + 1):
        if u[i - 1] - (cssv[i - 1] - 1.0) / i > 0:
            rho = i
    theta = (cssv[rho - 1] - 1.0) / rho
    return [max(0.0, x - theta) for x in v]


def _solve_mix_weights(target_ks: Sequence[float],
                       A: Sequence[Sequence[float]],
                       weights: Optional[Sequence[float]] = None) -> List[float]:
    """求 5 瓶基础漆的体积分数 w（≥0, Σw=1），使 K/S 减法混色最接近目标。

    纯 Python 投影梯度下降 + 单纯形投影（不依赖 numpy/scipy）：
    混色在 K/S 空间对 w 是线性的，故这是加权最小二乘，梯度下降稳定收敛。

    ``weights`` 给每通道不同的重要度：默认按 1/(K/S+ε) 加权，让"高反射（亮）
    通道"权重更大，避免亮色被黑/深色拉暗（否则纯红会被误算成红+大量黑）。
    """
    n = len(A[0])
    w = [1.0 / n] * n
    t = list(target_ks)
    if weights is None:
        weights = [1.0 / (t[c] + 0.1) for c in range(3)]
    W = list(weights)
    for _ in range(3000):
        aw = [sum(A[r][c] * w[c] for c in range(n)) for r in range(3)]
        resid = [aw[r] - t[r] for r in range(3)]
        g = [2.0 * sum(A[r][c] * W[r] * resid[r] for r in range(3)) for c in range(n)]
        if max(abs(x) for x in g) < 1e-9:
            break
        d = [-x for x in g]
        ad = [sum(A[r][c] * d[c] for c in range(n)) for r in range(3)]
        denom = 2.0 * sum(W[r] * ad[r] * ad[r] for r in range(3))
        if denom <= 0:
            break
        alpha = sum(x * x for x in g) / denom
        w = _project_simplex([w[c] - alpha * g[c] for c in range(n)])
    if sum(w) <= 0:
        w = [1.0 / n] * n
    return w


def compute_base_mix(target_rgb: Sequence[int],
                     config: AppConfig,
                     brands: Optional[Sequence[str]] = None,
                     coverage_input: Optional[CoverageInput] = None,
                     matcher: Optional[PaintMatcher] = None,
                     total_drops: Optional[int] = None) -> MixRecipe:
    """把任意目标色分解为红/黄/蓝/白/黑五瓶基础漆的配比。

    - 用 Kubelka-Munk 减法混色在 K/S 空间求 5 瓶的体积分数；
    - 把配比换算成百分比与整数滴数（``total_drops`` 缺省取 ``config.drop_total``）；
    - 为每瓶基础漆在库内找最适配的真实漆（跟随品牌范围），从而做到"漆就这五瓶，
      但牌子可以有区别"。
    """
    target = normalize_rgb(target_rgb)
    if matcher is None:
        matcher = PaintMatcher(get_database())
    if total_drops is None:
        total_drops = int(getattr(config, "drop_total", 20) or 20)
    # 每瓶基础漆至少要 1 滴，所以总滴数不可能少于瓶数；不在这里对齐的话，
    # 传 total_drops=0 会得到「总滴数 0」而各组分实际是 1+1+1+1+1 滴——
    # 界面上比例条的标题和段内数字互相打架。
    total_drops = max(len(_BASE_PAINTS), int(total_drops))

    target_ks = _srgb_to_ks(target)
    base_ks = [_srgb_to_ks(rgb) for _, rgb in _BASE_PAINTS]   # 5 个 (r,g,b)
    A = [[base_ks[c][r] for c in range(len(_BASE_PAINTS))] for r in range(3)]  # 3×5

    weights = _solve_mix_weights(target_ks, A)
    mixed_ks = [sum(weights[c] * base_ks[c][r] for c in range(len(_BASE_PAINTS)))
                for r in range(3)]
    predicted = _ks_to_srgb(mixed_ks)
    de = _delta_e(rgb_to_lab(target), rgb_to_lab(predicted))

    percents = [w * 100.0 for w in weights]
    drops = proportions_to_drops(weights, total_drops)

    components: List[MixComponent] = []
    for (role, base), w, p, d in zip(_BASE_PAINTS, weights, percents, drops):
        sug = None
        try:
            sugg_list = matcher.suggest(
                target_rgb=base, config=config, brands=brands,
                coverage_input=coverage_input, max_results=1,
            )
            sug = sugg_list[0] if sugg_list else None
        except Exception as exc:  # 单瓶匹配失败不应拖垮整份配方
            logger.exception("基础漆 %s 求真实漆失败: %s", role, exc)
        components.append(MixComponent(role=role, base_rgb=base, weight=w,
                                      percent=p, drops=d, suggestion=sug))
    return MixRecipe(target_rgb=target, predicted_rgb=predicted, delta_e=de,
                     total_drops=total_drops, components=components)
