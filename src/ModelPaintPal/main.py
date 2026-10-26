# -*- coding: utf-8 -*-
"""Buildozer 入口（位于 source.dir 根，便于打包）。桌面调试也可直接运行本文件。"""

from __future__ import annotations

import mobile.bootstrap  # noqa: F401 —— 必须在导入任何核心模块前完成路径重定向
from mobile.main import main

if __name__ == "__main__":
    main()
