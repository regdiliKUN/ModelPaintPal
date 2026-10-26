# -*- coding: utf-8 -*-
"""移动端主题：配色与尺寸约定（触摸友好）。

尺寸统一用「设计值」（dp / sp）描述，实际使用时通过 :func:`D` / :func:`S`
换算为像素，从而在不同屏幕密度与系统字号下保持一致。

注意：Kivy 的 ``dp()`` / ``sp()`` 必须在窗口就绪后调用才准确（窗口未创建时
``Metrics.fontscale`` 为 -1，``sp()`` 会返回负值）；因此本模块只保存设计值，
换算一律放到控件构造时进行。
"""

from __future__ import annotations

from kivy.metrics import Metrics, dp

from .fonts import register as _register_fonts

# 中文字体（Kivy 默认 Roboto 无中文字形，必须替换，否则全是方框）
FONT = _register_fonts()

# ------------------------------------------------------------------ 颜色
BG = "#10131a"
BG_ALT = "#171b24"
CARD = "#1e2430"
CARD_HI = "#262d3b"
TEXT = "#e8edf4"
TEXT_DIM = "#94a0b3"
ACCENT = "#4f9dff"          # 主强调色
ACCENT_2 = "#36d399"        # 成功 / 直用
WARN = "#ffb454"
DANGER = "#ff5c6c"
BORDER = "#2c3342"
NAV_BG = "#080a0f"
BTN = "#2f6fd0"

# 基础漆固定色（与 scheme_engine._BASE_PAINTS 的 role 对应）
BASE_COLORS = {
    "红": "#e62121",
    "黄": "#ebd517",
    "蓝": "#225de6",
    "白": "#ffffff",
    "黑": "#0f0f0f",
}

# ------------------------------------------------------------------ 尺寸（设计值 dp）
PAD = 14          # 卡片内边距 / 屏幕左右边距
SPACING = 10      # 通用间距
RADIUS = 14       # 卡片圆角
BTN_H = 48        # 主要按钮高度（满足 48dp 触摸目标）
CTRL_H = 44       # 输入框 / 下拉框高度
ROW_H = 44        # 列表行高
NAV_H = 56        # 底部导航栏高度
SWATCH = 56       # 颜色色块边长

# ------------------------------------------------------------------ 字号（设计值 sp）
FS_TITLE = 20
FS_SUBTITLE = 16
FS_BODY = 15
FS_SMALL = 12


def D(value: float) -> float:
    """设计值（dp）→ 像素。"""
    return dp(value)


def S(value: float) -> float:
    """设计字号（sp）→ 像素，跟随系统字体缩放。

    窗口尚未创建时 ``Metrics.fontscale`` 为 -1，此处按 1.0 处理，避免出现负字号。
    """
    scale = Metrics.fontscale
    if not scale or scale <= 0:
        scale = 1.0
    return dp(value) * scale


def rgb255_to_kivy(rgb) -> tuple:
    """(r,g,b) 0-255 -> Kivy rgba 0-1。"""
    r, g, b = (int(v) for v in rgb[:3])
    return (r / 255.0, g / 255.0, b / 255.0, 1.0)


def hex_to_kivy(hex_str: str) -> tuple:
    """#RRGGBB / #RGB -> Kivy rgba 0-1。"""
    h = hex_str.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return (r / 255.0, g / 255.0, b / 255.0, 1.0)
