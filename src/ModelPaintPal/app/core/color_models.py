# -*- coding: utf-8 -*-
"""色彩空间转换、数值解析与格式化。

约定：
* 对外接口一律使用 0-255 的 sRGB 整数三元组（``RGB``）。
* 内部做 Lab / ΔE 计算时先线性化，避免伽马误差。
* 参考白点固定为 D65（sRGB 标准），与主流配色软件的默认一致。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Sequence, Tuple

__all__ = [
    "RGB",
    "Lab",
    "ColorSample",
    "hex_to_rgb",
    "rgb_to_hex",
    "rgb_to_hsv",
    "hsv_to_rgb",
    "rgb_to_hsl",
    "hsl_to_rgb",
    "rgb_to_lab",
    "lab_to_rgb",
    "rgb_to_linear",
    "linear_to_rgb",
    "linear_to_lab",
    "parse_color_text",
    "format_rgb",
    "format_lab",
    "relative_luminance",
    "contrast_text_color",
]

RGB = Tuple[int, int, int]
Lab = Tuple[float, float, float]

# D65 参考白（CIE 1931 2° 观察者）
WHITE_D65 = (95.047, 100.000, 108.883)
_EPSILON = 216.0 / 24389.0
_KAPPA = 24389.0 / 27.0

_HEX_RE = re.compile(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
# CSS 的 #RGBA 缩写（4 位）单独匹配：`_HEX_RE` 允许 3/6/8 位，若把 4 位并进去会
# 让 `hex_to_rgb` 取 body[4:6] 时越界，所以只让 `parse_color_text` 处理它。
_HEX4_RE = re.compile(r"^#([0-9a-fA-F]{4})$")
_RGB_FUNC_RE = re.compile(
    r"^rgba?\(\s*(\d{1,3})\s*[, ]\s*(\d{1,3})\s*[, ]\s*(\d{1,3})\s*(?:[,/]\s*[\d.]+\s*)?\)$"
)
_TRIPLE_RE = re.compile(r"^(\d{1,3})\s*[,;\s]\s*(\d{1,3})\s*[,;\s]\s*(\d{1,3})$")
_HSL_FUNC_RE = re.compile(
    r"^hsla?\(\s*(\d{1,3})%?\s*[, ]\s*(\d{1,3})%?\s*[, ]\s*(\d{1,3})%?\s*(?:[,/]\s*[\d.]+\s*)?\)$"
)
_0X_HEX_RE = re.compile(r"^0x([0-9a-fA-F]{6})$", re.IGNORECASE)


def _clamp(value: float, low: float = 0.0, high: float = 255.0) -> float:
    return low if value < low else high if value > high else value


def _clamp_unit(value: float) -> float:
    return 0.0 if value < 0.0 else 1.0 if value > 1.0 else value


def normalize_rgb(rgb: Sequence[float]) -> RGB:
    """把任意数值三元组收敛为合法的 0-255 整数 RGB。"""
    if len(rgb) < 3:
        raise ValueError(f"需要 3 个通道值，收到 {len(rgb)} 个")
    return (
        int(round(_clamp(float(rgb[0])))),
        int(round(_clamp(float(rgb[1])))),
        int(round(_clamp(float(rgb[2])))),
    )


def hex_to_rgb(text: str) -> RGB:
    """把 ``#RRGGBB`` / ``RGB`` 形式的字符串转为 RGB。"""
    match = _HEX_RE.match((text or "").strip())
    if not match:
        raise ValueError(f"无法解析的十六进制颜色: {text!r}")
    body = match.group(1)
    if len(body) == 3:
        body = "".join(ch * 2 for ch in body)
    return (
        int(body[0:2], 16),
        int(body[2:4], 16),
        int(body[4:6], 16),
    )


def rgb_to_hex(rgb: Sequence[float], prefix: str = "#") -> str:
    r, g, b = normalize_rgb(rgb)
    return f"{prefix}{r:02X}{g:02X}{b:02X}"


def rgb_to_hsv(rgb: Sequence[float]) -> Tuple[float, float, float]:
    """返回 ``(hue 0-360, saturation 0-100, value 0-100)``。"""
    r, g, b = (c / 255.0 for c in normalize_rgb(rgb))
    max_c, min_c = max(r, g, b), min(r, g, b)
    delta = max_c - min_c
    hue = 0.0
    if delta > 0.0:
        if max_c == r:
            hue = 60.0 * (((g - b) / delta) % 6.0)
        elif max_c == g:
            hue = 60.0 * ((b - r) / delta + 2.0)
        else:
            hue = 60.0 * ((r - g) / delta + 4.0)
    saturation = 0.0 if max_c == 0.0 else delta / max_c * 100.0
    return (round(hue % 360.0, 1), round(saturation, 1), round(max_c * 100.0, 1))


def hsv_to_rgb(hsv: Sequence[float]) -> RGB:
    hue = float(hsv[0]) % 360.0
    saturation = _clamp_unit(float(hsv[1]) / 100.0)
    value = _clamp_unit(float(hsv[2]) / 100.0)
    c = value * saturation
    x = c * (1.0 - abs((hue / 60.0) % 2.0 - 1.0))
    m = value - c
    sector = int(hue // 60.0) % 6
    table = (
        (c, x, 0.0),
        (x, c, 0.0),
        (0.0, c, x),
        (0.0, x, c),
        (x, 0.0, c),
        (c, 0.0, x),
    )[sector]
    return normalize_rgb([(channel + m) * 255.0 for channel in table])


def rgb_to_hsl(rgb: Sequence[float]) -> Tuple[float, float, float]:
    """返回 ``(hue 0-360, saturation 0-100, lightness 0-100)``。"""
    r, g, b = (c / 255.0 for c in normalize_rgb(rgb))
    max_c, min_c = max(r, g, b), min(r, g, b)
    lightness = (max_c + min_c) / 2.0
    delta = max_c - min_c
    if delta == 0.0:
        return (0.0, 0.0, round(lightness * 100.0, 1))
    saturation = delta / (2.0 - max_c - min_c) if lightness > 0.5 else delta / (max_c + min_c)
    if max_c == r:
        hue = 60.0 * (((g - b) / delta) % 6.0)
    elif max_c == g:
        hue = 60.0 * ((b - r) / delta + 2.0)
    else:
        hue = 60.0 * ((r - g) / delta + 4.0)
    return (round(hue % 360.0, 1), round(saturation * 100.0, 1), round(lightness * 100.0, 1))


def hsl_to_rgb(hsl: Sequence[float]) -> RGB:
    """``(hue 0-360, saturation 0-100, lightness 0-100)`` → sRGB 0-255。"""
    hue = float(hsl[0]) % 360.0
    saturation = _clamp_unit(float(hsl[1]) / 100.0)
    lightness = _clamp_unit(float(hsl[2]) / 100.0)
    if saturation == 0.0:
        value = int(round(lightness * 255.0))
        return (value, value, value)
    # 标准 HSL→RGB 临时量：注意 L<0.5 时是 L*(1+S)，不是 L+S
    q = lightness * (1.0 + saturation) if lightness < 0.5 else (lightness + saturation - lightness * saturation)
    p = 2.0 * lightness - q
    hue_k = hue / 360.0

    def _channel(t: float) -> int:
        if t < 0.0:
            t += 1.0
        elif t > 1.0:
            t -= 1.0
        if t < 1.0 / 6.0:
            color = p + (q - p) * 6.0 * t
        elif t < 0.5:
            color = q
        elif t < 2.0 / 3.0:
            color = p + (q - p) * (2.0 / 3.0 - t) * 6.0
        else:
            color = p
        return int(round(color * 255.0))

    return (
        _channel(hue_k + 1.0 / 3.0),
        _channel(hue_k),
        _channel(hue_k - 1.0 / 3.0),
    )


def rgb_to_linear(rgb: Sequence[float]) -> Tuple[float, float, float]:
    """sRGB(0-255) -> 线性光(0-1)。涂料混合必须在线性空间做，否则高光会偏暗。"""
    out: List[float] = []
    for channel in normalize_rgb(rgb):
        c = channel / 255.0
        out.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return (out[0], out[1], out[2])


def linear_to_rgb(linear: Sequence[float]) -> RGB:
    out: List[float] = []
    for c in linear:
        c = _clamp_unit(c)
        srgb = c * 12.92 if c <= 0.0031308 else 1.055 * (c ** (1.0 / 2.4)) - 0.055
        out.append(srgb * 255.0)
    return normalize_rgb(out)


def _xyz_to_lab_channel(t: float) -> float:
    return t ** (1.0 / 3.0) if t > _EPSILON else (_KAPPA * t + 16.0) / 116.0


def linear_to_lab(linear: Sequence[float]) -> Lab:
    """线性光(0-1) 直接转 CIELab，**不经 8bit 量化**。

    配方搜索里每次混合都要算一次 Lab（单次求建议几十万次），走
    ``linear_to_rgb`` → ``rgb_to_lab`` 会多做一次 gamma 反变换 + 取整，
    既有性能开销，也把中间结果压到 1/255 精度（深色区尤其粗糙）。
    这里直接线性→XYZ→Lab，既快又更准。
    """
    r = _clamp_unit(linear[0])
    g = _clamp_unit(linear[1])
    b = _clamp_unit(linear[2])
    x = (r * 0.4124564 + g * 0.3575761 + b * 0.1804375) * 100.0
    y = (r * 0.2126729 + g * 0.7151522 + b * 0.0721750) * 100.0
    z = (r * 0.0193339 + g * 0.1191920 + b * 0.9503041) * 100.0
    fx = _xyz_to_lab_channel(x / WHITE_D65[0])
    fy = _xyz_to_lab_channel(y / WHITE_D65[1])
    fz = _xyz_to_lab_channel(z / WHITE_D65[2])
    return (116.0 * fy - 16.0, 500.0 * (fx - fy), 200.0 * (fy - fz))


def rgb_to_lab(rgb: Sequence[float]) -> Lab:
    return linear_to_lab(rgb_to_linear(rgb))


def lab_to_rgb(lab: Sequence[float]) -> RGB:
    """Lab -> sRGB，超出色域时按通道裁剪（涂料配色里可接受的最小惊讶行为）。"""
    l_val, a_val, b_val = float(lab[0]), float(lab[1]), float(lab[2])
    fy = (l_val + 16.0) / 116.0
    fx = fy + a_val / 500.0
    fz = fy - b_val / 200.0
    x = WHITE_D65[0] * (fx ** 3 if fx ** 3 > _EPSILON else (116.0 * fx - 16.0) / _KAPPA)
    y = WHITE_D65[1] * (fy ** 3 if l_val > _KAPPA * _EPSILON else l_val / _KAPPA)
    z = WHITE_D65[2] * (fz ** 3 if fz ** 3 > _EPSILON else (116.0 * fz - 16.0) / _KAPPA)
    # sRGB 逆矩阵（X/Y/Z 取 0-100 量程，故系数 = 标准矩阵 ÷ 100），
    # 结果即 0-1 线性光，不能再除以 100。系数取足位数，否则白色回算会偏黄。
    r = x * 0.032404542 + y * -0.015371385 + z * -0.004985314
    g = x * -0.009692660 + y * 0.018760108 + z * 0.000415560
    b = x * 0.000556434 + y * -0.002040259 + z * 0.010572252
    return linear_to_rgb((r, g, b))


def relative_luminance(rgb: Sequence[float]) -> float:
    """WCAG 相对亮度，用于自动挑选叠加文字颜色。"""
    r, g, b = rgb_to_linear(rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_text_color(rgb: Sequence[float]) -> RGB:
    """在给定底色上返回可读的前景色（黑或白）。"""
    return (18, 18, 20) if relative_luminance(rgb) > 0.35 else (238, 238, 242)


def parse_color_text(text: str) -> RGB:
    """解析用户粘贴的颜色串，支持多种常见写法：

    * ``#RRGGBB`` / ``#RGB`` / ``#RGBA``（alpha 被忽略，仅取 RGB）
    * ``0xRRGGBB``
    * ``rgb(r, g, b)`` / ``rgba(r, g, b, a)``（alpha 被忽略）
    * ``hsl(h, s%, l%)`` / ``hsla(...)``
    * ``r, g, b`` / ``r g b``（空格/逗号/分号分隔）
    """
    raw = (text or "").strip()
    if not raw:
        raise ValueError("颜色输入为空")

    match4 = _HEX4_RE.match(raw)
    if match4:  # #RGBA：取 RGB 三位后各自双写，alpha 丢弃
        return hex_to_rgb("#" + "".join(ch * 2 for ch in match4.group(1)[:3]))

    match = _HEX_RE.match(raw)
    if match:
        body = match.group(1)
        if len(body) == 8:  # #RRGGBBAA → 取 RGB
            body = body[:6]
        if len(body) == 3:
            body = "".join(ch * 2 for ch in body)
        return hex_to_rgb("#" + body)

    match = _0X_HEX_RE.match(raw)
    if match:
        return hex_to_rgb("#" + match.group(1))

    match = _RGB_FUNC_RE.match(raw)
    if match:
        return normalize_rgb([int(match.group(1)), int(match.group(2)), int(match.group(3))])

    match = _HSL_FUNC_RE.match(raw)
    if match:
        return hsl_to_rgb([int(match.group(1)), int(match.group(2)), int(match.group(3))])

    match = _TRIPLE_RE.match(raw)
    if match:
        return normalize_rgb([int(match.group(1)), int(match.group(2)), int(match.group(3))])
    raise ValueError(f"无法识别的颜色格式: {text!r}")


def format_rgb(rgb: Sequence[float]) -> str:
    r, g, b = normalize_rgb(rgb)
    return f"rgb({r}, {g}, {b})"


def format_lab(lab: Sequence[float]) -> str:
    return f"L* {lab[0]:.1f}  a* {lab[1]:.1f}  b* {lab[2]:.1f}"


@dataclass(frozen=True)
class ColorSample:
    """一次取色结果的不可变快照，所有派生量惰性计算后缓存。"""

    rgb: RGB
    source: str = "unknown"

    @classmethod
    def from_rgb(cls, rgb: Sequence[float], source: str = "unknown") -> "ColorSample":
        return cls(normalize_rgb(rgb), source)

    @classmethod
    def from_hex(cls, text: str, source: str = "unknown") -> "ColorSample":
        return cls(hex_to_rgb(text), source)

    @property
    def hex(self) -> str:
        return rgb_to_hex(self.rgb)

    @property
    def hsv(self) -> Tuple[float, float, float]:
        return rgb_to_hsv(self.rgb)

    @property
    def hsl(self) -> Tuple[float, float, float]:
        return rgb_to_hsl(self.rgb)

    @property
    def lab(self) -> Lab:
        return rgb_to_lab(self.rgb)

    @property
    def text_color(self) -> RGB:
        return contrast_text_color(self.rgb)

    def as_row(self) -> dict:
        """供表格/导出使用的扁平字典。"""
        h, s, v = self.hsv
        l_val, a_val, b_val = self.lab
        return {
            "hex": self.hex,
            "rgb": self.rgb,
            "hsv": (h, s, v),
            "lab": (round(l_val, 2), round(a_val, 2), round(b_val, 2)),
            "source": self.source,
        }


def average_rgb(colors: Iterable[Sequence[float]]) -> RGB:
    """对一组颜色求算术平均（用于历史色统计/区域平均取色）。"""
    total = [0.0, 0.0, 0.0]
    count = 0
    for color in colors:
        r, g, b = normalize_rgb(color)
        total[0] += r
        total[1] += g
        total[2] += b
        count += 1
    if count == 0:
        raise ValueError("没有可用于求平均的颜色")
    return normalize_rgb([total[0] / count, total[1] / count, total[2] / count])
