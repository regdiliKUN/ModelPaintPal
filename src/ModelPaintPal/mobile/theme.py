# -*- coding: utf-8 -*-
"""移动端主题：配色与尺寸约定（触摸友好）。"""

from __future__ import annotations

# 深色调（与桌面端暗色主题一致），并适配手机
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

# 基础漆固定色（与 scheme_engine._BASE_PAINTS 的 role 对应）
BASE_COLORS = {
    "红": "#e62121",
    "黄": "#ebd517",
    "蓝": "#225de6",
    "白": "#ffffff",
    "黑": "#0f0f0f",
}

# 通用尺寸（dp 近似，Kivy 用 px；这里直接给 px，适配常见手机）
SPACING = 10
PAD = 14
RADIUS = 14
CARD_H = 92
BTN_H = 48
BOTTOM_NAV_H = 60
TITLE = 22
BODY = 16
SMALL = 13
HEADER_H = 56


def rgb255_to_kivy(rgb) -> tuple:
    """(r,g,b) 0-255 -> Kivy rgba 0-1。"""
    r, g, b = (int(v) for v in rgb[:3])
    return (r / 255.0, g / 255.0, b / 255.0, 1.0)


def hex_to_kivy(hex_str: str) -> tuple:
    h = hex_str.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return (r / 255.0, g / 255.0, b / 255.0, 1.0)
