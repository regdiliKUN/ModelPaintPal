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

    def test_delta_e_text_goes_through_formatter(self):
        """「ΔE 2.96」这类文案必须走 ``format_delta_e``，不能各处手写位数。

        同一条建议的 ΔE 会同时出现在卡片角标、状态栏、分享文本、导出表格里。
        只要有一处手写 ``:.1f``，用户就会看到「卡片 2.96、分享文本 3.0」，
        然后怀疑数据。本轮把散落的 12 处手写统一到 formatter，并把门槛设成 0。
        """
        offenders = []
        pattern = re.compile(r'f"[^"]*ΔE \{')
        for path, text in _sources():
            if path.name == "delta_e.py":
                continue          # 格式化实现本身就在这里
            for lineno, line in enumerate(text.splitlines(), start=1):
                if pattern.search(line):
                    offenders.append(f"{path.relative_to(PROJECT_ROOT)}:{lineno}")
        self.assertEqual(offenders, [], f"请改用 format_delta_e：{offenders}")

    def test_broad_except_leaves_a_trace(self):
        """捕获 ``Exception`` 的处理块必须留下痕迹（记日志或重新抛出）。

        宽泛捕获本身是对的——抓屏、热键、剪贴板、字体子系统这些外部依赖抛什么
        都有可能，不该把进程带崩。但「吞掉且不留痕」会让「某个功能悄悄不工作了」
        变成无法排查的问题：用户只能说「放大镜有时候是空的」，日志里一个字都没有。
        这里用「处理块内必须出现 ``logger.`` 或 ``raise``」做机械校验。
        """
        offenders = []
        for path, text in _sources():
            lines = text.splitlines()
            for node in ast.walk(ast.parse(text)):
                if not isinstance(node, ast.ExceptHandler):
                    continue
                caught = node.type
                if caught is None:
                    offenders.append(f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}（裸 except）")
                    continue
                name = getattr(caught, "id", None) or getattr(caught, "attr", None)
                if name != "Exception":
                    continue
                end = node.end_lineno or node.lineno
                body = "\n".join(lines[node.lineno - 1:end])
                if "logger." not in body and "raise" not in body:
                    offenders.append(f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}")
        self.assertEqual(offenders, [], f"兜底异常没有留日志：{offenders}")

    def test_installer_version_matches_package(self):
        """安装脚本里的版本号必须与包版本一致。

        `installer.iss` 停在 1.0.0 而包已经到 1.2.0 时，打出来的安装包文件名、
        「添加/删除程序」里显示的版本、以及用户报障时说的版本号全是错的。
        """
        text = (PROJECT_ROOT / "installer.iss").read_text(encoding="utf-8")
        match = re.search(r'#define\s+MyAppVersion\s+"([^"]+)"', text)
        self.assertIsNotNone(match, "installer.iss 里找不到 MyAppVersion")
        self.assertEqual(match.group(1), app.__version__)

    def test_public_functions_are_annotated(self):
        """公开函数必须有返回注解。

        370 个公开函数里只剩 8 个没写，补齐之后把门槛设成 0：新加的公开函数
        一旦漏注解，这里会失败。私有函数（``_`` 开头）不在此列——它们大多返回
        元组或临时结构，强加注解只会变成噪声。
        """
        offenders = []
        for path, text in _sources():
            tree = ast.parse(text)
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if node.name.startswith("_") or node.returns is not None:
                    continue
                offenders.append(f"{path.relative_to(PROJECT_ROOT)}::{node.name}")
        self.assertEqual(offenders, [], f"公开函数缺少返回注解：{offenders}")

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
