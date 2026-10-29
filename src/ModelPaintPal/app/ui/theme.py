# -*- coding: utf-8 -*-
"""暗色主题与统一样式。

集中定义配色与 QSS，避免各面板各写一套导致视觉不一致。
"""

from __future__ import annotations

from typing import Tuple

from PySide6.QtGui import QColor, QFont

from ..core.logging_setup import get_logger

logger = get_logger(__name__)

__all__ = [
    "Palette",
    "stylesheet",
    "font",
    "hex_to_qcolor",
    "mix_with_bg",
    "ui_font_family",
    "mono_font_family",
]

# 中文字体候选链：按优先级探测系统实际安装的字体。
# 硬编码单一字体族在某些环境（精简版 Windows、Wine、无字体的离屏渲染）会整屏变方框。
_FONT_CANDIDATES = (
    "Microsoft YaHei UI", "Microsoft YaHei", "微软雅黑",
    "Source Han Sans SC", "Noto Sans CJK SC", "Noto Sans SC",
    "PingFang SC", "Segoe UI", "Arial",
)
_MONO_CANDIDATES = (
    "Cascadia Mono", "Consolas", "Sarasa Mono SC", "DejaVu Sans Mono",
    "Courier New",
)

_resolved_family: str = ""
_resolved_mono: str = ""
_resolved = False


def _pick_family(candidates, fallback: str = "") -> str:
    try:
        from PySide6.QtGui import QFontDatabase

        available = set(QFontDatabase.families())
    except Exception as exc:  # pragma: no cover - 字体子系统不可用时交回 Qt 默认
        logger.debug("字体列表探测失败，使用回退字体: %s", exc)
        return fallback
    if not available:
        return fallback
    for name in candidates:
        if name in available:
            return name
    return fallback


def _resolve_fonts() -> None:
    global _resolved_family, _resolved_mono, _resolved
    if _resolved:
        return
    _resolved_family = _pick_family(_FONT_CANDIDATES)
    _resolved_mono = _pick_family(_MONO_CANDIDATES, _resolved_family)
    _resolved = True


def ui_font_family() -> str:
    _resolve_fonts()
    return _resolved_family


def mono_font_family() -> str:
    _resolve_fonts()
    return _resolved_mono or ui_font_family()


def _font_stack() -> str:
    """QSS 用的字体族串（带兜底，Qt 会依次尝试）。"""
    parts = [name for name in (_resolved_family, _resolved_mono) if name]
    return ", ".join(f'"{name}"' for name in parts) or "sans-serif"


class Palette:
    bg = "#12141A"
    bg_alt = "#171A21"
    surface = "#1E222B"
    surface_alt = "#252A35"
    border = "#2E3440"
    border_strong = "#3C4453"
    text = "#E6E9EF"
    text_dim = "#9AA4B5"
    text_faint = "#6B7482"
    accent = "#4C8DFF"
    accent_dim = "#2F5FB8"
    success = "#3FB950"
    warn = "#D29922"
    danger = "#F85149"
    highlight = "#56A8F5"


def font(size: int = 10, bold: bool = False, mono: bool = False) -> QFont:
    family = mono_font_family() if mono else ui_font_family()
    f = QFont(family, size) if family else QFont()
    if not family:
        f.setPointSize(size)
    f.setBold(bold)
    return f


def hex_to_qcolor(value: str) -> QColor:
    return QColor(value)


def mix_with_bg(value: str, ratio: float = 0.18) -> Tuple[int, int, int]:
    """把任意颜色向背景色靠拢，用于生成柔和的边框/底纹。"""
    color = QColor(value)
    bg = QColor(Palette.bg)
    ratio = max(0.0, min(1.0, ratio))
    return (
        int(color.red() * (1 - ratio) + bg.red() * ratio),
        int(color.green() * (1 - ratio) + bg.green() * ratio),
        int(color.blue() * (1 - ratio) + bg.blue() * ratio),
    )


_STYLE_TEMPLATE = f"""
QWidget {{
    background-color: {Palette.bg};
    color: {Palette.text};
    font-family: __FONT_STACK__;
    font-size: 10pt;
}}
QMainWindow, QDialog {{
    background-color: {Palette.bg};
}}
QMenuBar {{
    background-color: {Palette.bg_alt};
    border-bottom: 1px solid {Palette.border};
}}
QMenuBar::item:selected {{ background-color: {Palette.surface}; }}
QMenu {{
    background-color: {Palette.surface};
    border: 1px solid {Palette.border};
}}
QMenu::item:selected {{ background-color: {Palette.accent_dim}; }}

QLabel#TitleLabel {{
    font-size: 15pt;
    font-weight: 600;
    color: {Palette.text};
}}
QLabel#SubTitleLabel {{
    color: {Palette.text_dim};
    font-size: 9pt;
}}
QLabel#SectionLabel {{
    font-size: 10pt;
    font-weight: 600;
    color: {Palette.text};
}}
QLabel#DimLabel {{
    color: {Palette.text_dim};
}}
QLabel#FaintLabel {{
    color: {Palette.text_faint};
}}
QLabel#MonoLabel {{
    font-family: __MONO_STACK__;
}}
/* 标签一律透明底：全局 QWidget 规则会给每个控件刷上不透明背景，
   压在卡片/色块上的文字会被"贴"一块底色。在这里统一声明一次，
   各面板就不必再逐个 setStyleSheet("...background: transparent")。 */
QLabel {{
    background-color: transparent;
}}
QLabel#Chip {{
    color: {Palette.text_dim};
    background-color: {Palette.bg_alt};
    border: 1px solid {Palette.border};
    border-radius: 7px;
    padding: 2px 7px;
    font-size: 8pt;
}}
QLabel#ChipAccent {{
    color: {Palette.text};
    background-color: {Palette.bg_alt};
    border: 1px solid {Palette.accent_dim};
    border-radius: 7px;
    padding: 2px 7px;
    font-size: 8pt;
}}
QLabel#HintLabel {{
    color: {Palette.text_faint};
    font-size: 8pt;
}}
QLabel#ErrorLabel {{
    color: {Palette.danger};
    font-size: 8pt;
}}

QFrame#Card {{
    background-color: {Palette.surface};
    border: 1px solid {Palette.border};
    border-radius: 10px;
}}
QFrame#CardAlt {{
    background-color: {Palette.surface_alt};
    border: 1px solid {Palette.border};
    border-radius: 8px;
}}
QFrame#Divider {{
    background-color: {Palette.border};
    max-height: 1px;
    min-height: 1px;
}}

QPushButton {{
    background-color: {Palette.surface_alt};
    border: 1px solid {Palette.border_strong};
    border-radius: 6px;
    padding: 6px 12px;
    color: {Palette.text};
}}
QPushButton:hover {{
    background-color: #2E3443;
    border-color: {Palette.accent_dim};
}}
QPushButton:pressed {{
    background-color: {Palette.accent_dim};
}}
QPushButton:disabled {{
    background-color: {Palette.surface};
    color: {Palette.text_faint};
    border-color: {Palette.border};
}}
QPushButton#PrimaryButton {{
    background-color: {Palette.accent};
    border: 1px solid {Palette.accent};
    color: #FFFFFF;
    font-weight: 600;
}}
QPushButton#PrimaryButton:hover {{
    background-color: #5C99FF;
}}
QPushButton#PrimaryButton:disabled {{
    background-color: {Palette.accent_dim};
    border-color: {Palette.accent_dim};
    color: #C9D4E8;
}}
QPushButton#GhostButton {{
    background-color: transparent;
    border: 1px solid {Palette.border};
    color: {Palette.text_dim};
}}
QPushButton#GhostButton:hover {{
    color: {Palette.text};
    border-color: {Palette.accent_dim};
    background-color: {Palette.surface};
}}
QPushButton#IconButton {{
    padding: 4px 8px;
    min-width: 26px;
}}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background-color: {Palette.bg_alt};
    border: 1px solid {Palette.border_strong};
    border-radius: 6px;
    padding: 5px 8px;
    color: {Palette.text};
    selection-background-color: {Palette.accent_dim};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border-color: {Palette.accent};
}}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{
    background-color: {Palette.surface};
    border: 1px solid {Palette.border};
    selection-background-color: {Palette.accent_dim};
}}

QTabWidget::pane {{
    border: 1px solid {Palette.border};
    border-radius: 8px;
    background-color: {Palette.bg_alt};
    top: -1px;
}}
QTabBar::tab {{
    background-color: {Palette.bg_alt};
    color: {Palette.text_dim};
    border: 1px solid {Palette.border};
    padding: 6px 14px;
    margin-right: 2px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
}}
QTabBar::tab:selected {{
    background-color: {Palette.surface};
    color: {Palette.text};
    border-bottom-color: {Palette.surface};
}}
QTabBar::tab:hover {{ color: {Palette.text}; }}

QScrollArea {{ border: none; background-color: transparent; }}
QScrollBar:vertical {{
    background-color: {Palette.bg_alt};
    width: 10px;
    margin: 0px;
}}
QScrollBar::handle:vertical {{
    background-color: {Palette.border_strong};
    border-radius: 5px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background-color: #4A5464; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
QScrollBar:horizontal {{ height: 10px; background-color: {Palette.bg_alt}; }}
QScrollBar::handle:horizontal {{
    background-color: {Palette.border_strong};
    border-radius: 5px;
    min-width: 30px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0px; }}

QListWidget {{
    background-color: {Palette.bg_alt};
    border: 1px solid {Palette.border};
    border-radius: 8px;
    padding: 4px;
}}
QListWidget::item {{ padding: 4px; border-radius: 4px; }}
QListWidget::item:selected {{ background-color: {Palette.accent_dim}; }}

QCheckBox {{ spacing: 6px; color: {Palette.text}; }}
QCheckBox::indicator {{
    width: 15px; height: 15px;
    border: 1px solid {Palette.border_strong};
    border-radius: 3px;
    background-color: {Palette.bg_alt};
}}
QCheckBox::indicator:checked {{
    background-color: {Palette.accent};
    border-color: {Palette.accent};
}}

QSlider::groove:horizontal {{
    background-color: {Palette.bg_alt};
    height: 4px;
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background-color: {Palette.accent};
    width: 14px;
    margin: -5px 0;
    border-radius: 7px;
}}
QSlider::sub-page:horizontal {{ background-color: {Palette.accent_dim}; border-radius: 2px; }}

QToolTip {{
    background-color: {Palette.surface_alt};
    color: {Palette.text};
    border: 1px solid {Palette.border_strong};
    padding: 4px 6px;
}}

QStatusBar {{
    background-color: {Palette.bg_alt};
    color: {Palette.text_dim};
    border-top: 1px solid {Palette.border};
}}
"""


def stylesheet() -> str:
    """生成当前字体环境下的完整 QSS（结果缓存，避免重复格式化）。"""
    global _STYLE_CACHE
    if _STYLE_CACHE is None:
        _resolve_fonts()
        mono = mono_font_family() or "monospace"
        _STYLE_CACHE = (_STYLE_TEMPLATE
                        .replace("__FONT_STACK__", _font_stack())
                        .replace("__MONO_STACK__", f'"{mono}"'))
    return _STYLE_CACHE


_STYLE_CACHE = None
