# -*- coding: utf-8 -*-
"""包级元信息与代码规范测试。

这里的用例不测业务行为，而是**锁住已经付过代价才改好的规范**，
防止后续迭代悄悄退回去：

* 版本号格式、包可导入
* HEX 格式化只能走 `rgb_to_hex`（此前 5 处手写 `"#%02X%02X%02X"`，改一次格式要改 5 处）
* 标签颜色只能由 QSS 的 objectName 角色决定（此前 46 处内联 setStyleSheet 重复声明）
* 函数长度上限（此前最长 82 行，界面构造函数 70+ 行）
"""

import ast
import re
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import app  # noqa: E402

APP_DIR = PROJECT_ROOT / "app"

# 允许超长的函数：Win32 消息循环是一段不可拆的阻塞式过程，
# 拆开反而更难保证 GetMessage/DispatchMessage 的成对关系。
_LONG_FUNCTION_ALLOWLIST = {"_message_loop", "_com_create"}

_MANUAL_HEX = re.compile(r'"#%02X%02X%02X"')
_INLINE_LABEL_STYLE = re.compile(
    r'setStyleSheet\(f?"color: \{Palette\.(text|text_dim|text_faint)\}; background: transparent;"\)')


def _sources():
    for path in sorted(APP_DIR.rglob("*.py")):
        yield path, path.read_text(encoding="utf-8")


class TestMeta(unittest.TestCase):
    def test_version_is_semver(self):
        self.assertIsInstance(app.__version__, str)
        parts = app.__version__.split(".")
        self.assertEqual(len(parts), 3)
        self.assertTrue(any(ch.isdigit() for ch in app.__version__))
        for part in parts:
            self.assertTrue(part.isdigit(), f"版本段非数字: {part!r}")

    def test_app_package_importable(self):
        self.assertTrue(hasattr(app, "__version__"))


class TestCodeHygiene(unittest.TestCase):
    def test_no_manual_hex_formatting(self):
        """HEX 只能由 rgb_to_hex 生成，禁止手写格式化串。"""
        offenders = []
        for path, text in _sources():
            if _MANUAL_HEX.search(text):
                offenders.append(str(path.relative_to(PROJECT_ROOT)))
        self.assertEqual(offenders, [], f"请改用 rgb_to_hex：{offenders}")

    def test_no_duplicate_inline_label_colors(self):
        """标签颜色走 QSS 角色（SectionLabel/DimLabel/FaintLabel），不要内联重复声明。"""
        offenders = []
        for path, text in _sources():
            if _INLINE_LABEL_STYLE.search(text):
                offenders.append(str(path.relative_to(PROJECT_ROOT)))
        self.assertEqual(offenders, [], f"请改用 setObjectName 角色：{offenders}")

    def test_function_length_budget(self):
        """单个函数不超过 60 行（界面构造函数尤其容易失控）。"""
        offenders = []
        for path, text in _sources():
            tree = ast.parse(text)
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if node.name in _LONG_FUNCTION_ALLOWLIST:
                    continue
                end = getattr(node, "end_lineno", node.lineno)
                body = [ln for ln in text.splitlines()[node.lineno - 1:end] if ln.strip()]
                if len(body) > 60:
                    offenders.append(f"{path.relative_to(PROJECT_ROOT)}::{node.name} ({len(body)} 行)")
        self.assertEqual(offenders, [], f"函数过长，请拆分：{offenders}")

    def test_core_layer_has_no_upward_imports(self):
        """依赖方向必须是 ui → services → data → core，core 不得反向依赖上层。"""
        offenders = []
        for path, text in _sources():
            if "core" not in path.parts:
                continue
            if re.search(r"^from \.\.(ui|services|data)", text, re.MULTILINE):
                offenders.append(str(path.relative_to(PROJECT_ROOT)))
        self.assertEqual(offenders, [], f"core 层出现反向依赖：{offenders}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
