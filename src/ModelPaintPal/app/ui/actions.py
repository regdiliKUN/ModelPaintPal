# -*- coding: utf-8 -*-
"""主窗口的「叶子动作」：导出、分享、关于、桌面快捷方式。

这些动作只读主窗口的几个状态（当前样本、建议列表），不参与任何计算编排，
与「何时算、怎么算」完全无关。把它们从 `main_window` 里搬出来，是为了让那个
文件只留窗口装配与计算编排——它已经接近千行，再往里塞导出分支就该没人看得懂了。
"""

from __future__ import annotations

from ..core.logging_setup import get_logger
from ..services.export_service import (
    copy_to_clipboard, suggestions_to_csv, suggestions_to_markdown,
    suggestions_to_share_text,
)
from .widgets.toast import show_toast

logger = get_logger(__name__)

__all__ = [
    "create_desktop_shortcut",
    "copy_share_text",
    "export_suggestions",
    "save_text",
    "show_about",
]

#: 导出类型 → (默认文件名, 文件对话框过滤器)
_EXPORT_KINDS = {
    "json": ("配色建议.json", "JSON 文件 (*.json)"),
    "markdown": ("配色建议.md", "Markdown 文件 (*.md)"),
    "csv": ("配色建议.csv", "CSV 文件 (*.csv)"),
}


def _require_sample(window) -> bool:
    """没有取色时给出提示并返回 False（三个导出入口共用同一句话）。"""
    if window.sample is None:
        show_toast(window, "还没有取色", "warn")
        return False
    return True


def export_suggestions(window, kind: str) -> None:
    """把当前建议导出为文件。``kind`` 取 ``json`` / ``markdown`` / ``csv``。"""
    if kind not in _EXPORT_KINDS:
        logger.warning("未知的导出类型: %r", kind)
        return
    default_name, pattern = _EXPORT_KINDS[kind]
    if kind == "json":
        # JSON 走 MainWindow.export_report()，那是给自动化/测试用的公开入口
        text = window.export_report()
    else:
        if not _require_sample(window):
            return
        target = window.sample.rgb
        if kind == "markdown":
            text = suggestions_to_markdown(window.suggestions, target)
        else:
            text = suggestions_to_csv(window.suggestions, target)
    save_text(window, text, default_name, pattern)


def save_text(window, text: str, default_name: str, pattern: str) -> None:
    """弹保存对话框并写文件；失败时把原因显示出来而不是静默。"""
    from PySide6.QtWidgets import QFileDialog

    path, _ = QFileDialog.getSaveFileName(window, "导出", default_name, pattern)
    if not path:
        return
    try:
        with open(path, "w", encoding="utf-8") as fp:
            fp.write(text)
        show_toast(window, f"已导出到 {path}", "success")
    except OSError as exc:
        logger.error("导出失败: %s", exc)
        show_toast(window, f"导出失败：{exc}", "error")


def copy_share_text(window) -> None:
    """一键把「目标色 + 前两套配比」复制成纯文本，便于发群/发帖。"""
    if not _require_sample(window):
        return
    text = suggestions_to_share_text(
        window.suggestions, window.sample.rgb,
        title=f"涂装配色：{window.sample.hex}",
    )
    if copy_to_clipboard(text):
        show_toast(window, "分享文本已复制", "success")
    else:
        show_toast(window, "复制失败", "error")


def create_desktop_shortcut(window) -> None:
    """按需创建桌面快捷方式（启动时不再自动创建，见 1.1.0 的说明）。"""
    from ..core.shortcut import ensure_desktop_shortcut

    result = ensure_desktop_shortcut()
    show_toast(window, "桌面快捷方式已就绪" if result else
               "创建未成功，请查看日志；也可为 ModelPaintPal.exe 手动创建快捷方式")


def show_about() -> None:
    """关于对话框（版本与色号库规模）。"""
    from PySide6.QtWidgets import QMessageBox

    from .. import __version__
    from ..data.paint_db import get_database

    db = get_database()
    QMessageBox.information(
        None, "关于",
        f"ModelPaintPal v{__version__}\n\n"
        f"3D 打印模型涂装配色助手\n"
        f"色号库：{len(db)} 条 / {len(db.brands)} 个品牌\n\n"
        "色值为基于官方色卡的屏幕近似值，用于相对匹配与配比估算；\n"
        "正式喷涂前请务必小量试喷确认。",
    )
