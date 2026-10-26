# -*- coding: utf-8 -*-
"""移动端入口（Buildozer 的 source.main 指向此文件）。

用法：
    桌面调试：  python mobile/main.py
    Android：  由 Buildozer 打包，无需手动调用
"""

from __future__ import annotations

import mobile.bootstrap  # noqa: F401  —— 必须在导入任何核心模块前完成路径重定向
_ = mobile.bootstrap.ROOT  # 确保副作用（路径重定向）生效
from mobile.app import MppApp


def main() -> None:
    MppApp().run()


if __name__ == "__main__":
    main()
