# -*- coding: utf-8 -*-
"""中文字体注册。

Kivy 默认字体 Roboto 不含中日韩字形，未注册中文字体时所有汉字都会渲染成方框。
这里优先使用随包内置的 Noto Sans SC，找不到时回退到各平台自带的中文字体；
并把默认的 ``Roboto`` 一并指向该字体，使所有未显式指定 ``font_name`` 的控件
（Spinner / TextInput / 原生 Label）也能正常显示中文。
"""

from __future__ import annotations

import os

from kivy.core.text import LabelBase

FONT_NAME = "MppCJK"
_font_path = None
_done = False

_CANDIDATES = (
    # 随包内置（打包进 APK，最可靠）
    os.path.join(os.path.dirname(__file__), "assets", "fonts",
                 "NotoSansSC-Regular.otf"),
    # Android 系统字体
    "/system/fonts/NotoSansCJK-Regular.ttc",
    "/system/fonts/NotoSansSC-Regular.otf",
    "/system/fonts/NotoSansCJKsc-Regular.otf",
    "/system/fonts/DroidSansFallback.ttf",
    # Windows
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/msyh.ttf",
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/simsun.ttc",
    # macOS
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    # Linux
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/arphic/uming.ttc",
)


def find_font():
    for path in _CANDIDATES:
        try:
            if path and os.path.exists(path) and os.path.getsize(path) > 0:
                return path
        except OSError:
            continue
    return None


def register() -> str:
    """注册中文字体并返回可用的 font_name。"""
    global _done, _font_path
    if _done:
        return FONT_NAME if _font_path else "Roboto"

    _done = True
    _font_path = find_font()
    if not _font_path:
        return "Roboto"

    try:
        LabelBase.register(name=FONT_NAME, fn_regular=_font_path,
                           fn_bold=_font_path)
        # 覆盖默认字体：让所有控件（包括 Spinner / TextInput）都能显示中文
        LabelBase.register(name="Roboto", fn_regular=_font_path,
                           fn_bold=_font_path)
    except Exception:
        _font_path = None
        return "Roboto"
    return FONT_NAME


def font_path():
    return _font_path
