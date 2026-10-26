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
    hsl_to_rgb, hsv_to_rgb, normalize_rgb, rgb_to_hex, rgb_to_hsl, rgb_to_hsv,
)
from ..core.config import AppConfig
from ..core.logging_setup import get_logger
from ..services.coverage import CoverageInput
from ..services.paint_matcher import PaintMatcher, PaintSuggestion

logger = get_logger(__name__)

RGB = Tuple[int, int, int]

__all__ = [
    "SchemeType", "SCHEME_ORDER", "SCHEME_LABELS", "SCHEME_DESC",
    "SchemeColor", "SchemeStop", "generate_scheme_colors", "build_scheme",
    "default_param_for",
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
