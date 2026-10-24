# -*- coding: utf-8 -*-
"""Windows 全局快捷键。

采用「后台线程 + 仅消息窗口 + RegisterHotKey」方案：
* 不需要管理员权限，也不依赖第三方全局钩子库；
* 热键消息在独立线程的消息循环里被捕获，再通过 Qt 信号（跨线程自动排队）
  安全地投递到主线程；
* 非 Windows 平台直接降级为「不启用全局热键」，应用内快捷键仍然有效。
"""

from __future__ import annotations

import ctypes
import platform
import threading
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QObject, Signal

from .logging_setup import get_logger

logger = get_logger(__name__)

__all__ = ["HotkeyManager", "parse_hotkey", "IS_WINDOWS", "MODIFIER_LABELS"]

IS_WINDOWS = platform.system() == "Windows"

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN = 0x0001, 0x0002, 0x0004, 0x0008
MOD_NOREPEAT = 0x4000

MODIFIER_LABELS = ("Ctrl", "Shift", "Alt", "Win")

_NAMED_KEYS: Dict[str, int] = {
    "ESC": 0x1B, "ESCAPE": 0x1B, "SPACE": 0x20, "ENTER": 0x0D, "RETURN": 0x0D,
    "TAB": 0x09, "BACKSPACE": 0x08, "DELETE": 0x2E, "INSERT": 0x2D,
    "HOME": 0x24, "END": 0x23, "PAGEUP": 0x21, "PAGEDOWN": 0x22,
    "UP": 0x26, "DOWN": 0x28, "LEFT": 0x25, "RIGHT": 0x27,
    **{f"F{i}": 0x6F + i for i in range(1, 25)},
}


def _virtual_key(token: str) -> int:
    upper = token.upper()
    if upper in _NAMED_KEYS:
        return _NAMED_KEYS[upper]
    if len(upper) == 1:
        code = ord(upper)
        if 0x30 <= code <= 0x39 or 0x41 <= code <= 0x5A:
            return code
    raise ValueError(f"不支持的按键: {token}")


def parse_hotkey(combo: str) -> Tuple[int, int]:
    """``"Ctrl+Shift+X"`` -> ``(modifiers, virtual_key)``。"""
    if not combo or not combo.strip():
        raise ValueError("快捷键为空")
    tokens = [t.strip() for t in combo.replace("+", "+").split("+") if t.strip()]
    if not tokens:
        raise ValueError(f"快捷键格式无效: {combo!r}")
    modifiers = 0
    key_token = ""
    for token in tokens:
        upper = token.upper()
        if upper in ("CTRL", "CONTROL"):
            modifiers |= MOD_CONTROL
        elif upper == "SHIFT":
            modifiers |= MOD_SHIFT
        elif upper == "ALT":
            modifiers |= MOD_ALT
        elif upper in ("WIN", "META", "SUPER"):
            modifiers |= MOD_WIN
        else:
            if key_token:
                raise ValueError(f"快捷键只能有一个主键: {combo!r}")
            key_token = token
    if not key_token:
        raise ValueError(f"快捷键缺少主键: {combo!r}")
    return modifiers | MOD_NOREPEAT, _virtual_key(key_token)


def format_hotkey(modifiers: int, vk: int) -> str:
    parts = []
    if modifiers & MOD_CONTROL:
        parts.append("Ctrl")
    if modifiers & MOD_SHIFT:
        parts.append("Shift")
    if modifiers & MOD_ALT:
        parts.append("Alt")
    if modifiers & MOD_WIN:
        parts.append("Win")
    for name, code in _NAMED_KEYS.items():
        if code == vk and len(name) > 1:
            parts.append(name.title() if name.islower() else name)
            break
    else:
        parts.append(chr(vk))
    return "+".join(parts)


class HotkeyManager(QObject):
    """管理一组全局热键，热键命中时发射携带名称的 ``triggered`` 信号。"""

    triggered = Signal(str)   # 热键名称
    failed = Signal(str, str)  # (名称, 失败原因)

    _WM_HOTKEY = 0x0312
    _WM_QUIT = 0x0012

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._bindings: List[Tuple[str, str]] = []
        self._thread: Optional[threading.Thread] = None
        self._thread_id: Optional[int] = None
        self._next_id = 1
        self._enabled = False
        self._ready = threading.Event()
        self._stop_requested = threading.Event()

    # ------------------------------------------------------------ 绑定管理
    @property
    def bindings(self) -> List[Tuple[str, str]]:
        return list(self._bindings)

    @property
    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def set_bindings(self, bindings: List[Tuple[str, str]]) -> None:
        """替换全部绑定并按需重启监听线程。"""
        normalized = [(name, combo) for name, combo in bindings if combo]
        if normalized == self._bindings and self.is_running:
            return
        self._bindings = normalized
        if self._enabled:
            self.restart()

    def start(self) -> bool:
        self._enabled = True
        if not IS_WINDOWS:
            logger.info("非 Windows 平台，跳过全局热键注册")
            return False
        if self.is_running or not self._bindings:
            return self.is_running
        self._ready.clear()
        self._stop_requested.clear()
        self._thread = threading.Thread(
            target=self._run, name="GlobalHotkeyListener", daemon=True
        )
        self._thread.start()
        return True

    def restart(self) -> None:
        self.stop()
        self.start()

    def stop(self) -> None:
        self._enabled = False
        self._stop_requested.set()
        if not self._thread or not self._thread.is_alive():
            self._thread = None
            return
        # PostThreadMessage在线程创建消息队列前会失败；等待窗口就绪或启动失败。
        self._ready.wait(timeout=2.0)
        if IS_WINDOWS and self._thread_id and self._thread.is_alive():
            try:
                ctypes.windll.user32.PostThreadMessageW(self._thread_id, self._WM_QUIT, 0, 0)
            except (AttributeError, OSError) as exc:
                logger.debug("投递退出消息失败: %s", exc)
        self._thread.join(timeout=2.0)
        if self._thread.is_alive():
            logger.warning("热键监听线程仍在停止中，保留线程引用以避免重复启动")
            return
        self._thread = None
        self._thread_id = None

    # -------------------------------------------------------------- 线程体
    def _run(self) -> None:  # pragma: no cover - 依赖真实窗口系统
        if not IS_WINDOWS:
            return
        try:
            self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
            self._message_loop()
        except Exception as exc:  # 兜底，绝不让监听线程把进程带崩
            logger.error("热键监听线程异常退出: %s", exc)
        finally:
            self._ready.set()

    def _message_loop(self) -> None:  # pragma: no cover
        import ctypes.wintypes as wt

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        LRESULT = ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_long
        WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)

        # 必须显式声明签名：否则 ctypes 会把 64 位的 WPARAM/LPARAM 当成 c_int 传递，
        # 在窗口过程里触发 “int too long to convert”。
        user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
        user32.DefWindowProcW.restype = LRESULT
        user32.CreateWindowExW.argtypes = [
            wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID]
        user32.CreateWindowExW.restype = wt.HWND
        user32.RegisterHotKey.argtypes = [wt.HWND, ctypes.c_int, wt.UINT, wt.UINT]
        user32.RegisterHotKey.restype = wt.BOOL
        user32.UnregisterHotKey.argtypes = [wt.HWND, ctypes.c_int]
        user32.UnregisterHotKey.restype = wt.BOOL
        user32.DestroyWindow.argtypes = [wt.HWND]
        user32.DestroyWindow.restype = wt.BOOL
        user32.UnregisterClassW.argtypes = [wt.LPCWSTR, wt.HINSTANCE]
        user32.UnregisterClassW.restype = wt.BOOL
        user32.GetMessageW.argtypes = [wt.LPMSG, wt.HWND, wt.UINT, wt.UINT]
        user32.GetMessageW.restype = wt.BOOL
        user32.TranslateMessage.argtypes = [wt.LPMSG]
        user32.DispatchMessageW.argtypes = [wt.LPMSG]
        user32.DispatchMessageW.restype = LRESULT
        kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
        kernel32.GetModuleHandleW.restype = wt.HMODULE

        class WNDCLASSEXW(ctypes.Structure):
            _fields_ = [
                ("cbSize", wt.UINT), ("style", wt.UINT), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON), ("hCursor", wt.HICON),
                ("hbrBackground", wt.HBRUSH), ("lpszMenuName", wt.LPCWSTR),
                ("lpszClassName", wt.LPCWSTR), ("hIconSm", wt.HICON),
            ]

        hotkey_ids: Dict[int, str] = {}

        def _wnd_proc(hwnd, msg, wparam, lparam):
            if msg == self._WM_HOTKEY:
                name = hotkey_ids.get(int(wparam))
                if name:
                    self.triggered.emit(name)
                return 0
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        proc = WNDPROC(_wnd_proc)
        class_name = f"ModelPaintPalHotkeyWindow_{id(self)}_{self._thread_id}"
        wcex = WNDCLASSEXW()
        wcex.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wcex.lpfnWndProc = proc
        wcex.lpszClassName = class_name
        wcex.hInstance = kernel32.GetModuleHandleW(None)
        if not user32.RegisterClassExW(ctypes.byref(wcex)):
            logger.error("热键窗口类注册失败: %s", ctypes.get_last_error())
            return

        hwnd = user32.CreateWindowExW(
            0, class_name, "ModelPaintPal Hotkey", 0, 0, 0, 0, 0,
            wt.HWND(-3), None, wcex.hInstance, None,   # HWND_MESSAGE = (HWND)-3
        )
        if not hwnd:
            logger.error("热键窗口创建失败: %s", ctypes.get_last_error())
            user32.UnregisterClassW(class_name, wcex.hInstance)
            return
        self._ready.set()
        try:
            if not self._stop_requested.is_set():
                self._register_bindings(user32, hwnd, hotkey_ids)
                msg = wt.MSG()
                while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                    user32.TranslateMessage(ctypes.byref(msg))
                    user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            for hotkey_id in list(hotkey_ids):
                user32.UnregisterHotKey(hwnd, hotkey_id)
            user32.DestroyWindow(hwnd)
            # 窗口类不能继续指向即将被Python释放的WNDPROC回调。
            user32.UnregisterClassW(class_name, wcex.hInstance)
        logger.info("热键监听线程已退出")

    def _register_bindings(self, user32, hwnd, hotkey_ids: Dict[int, str]) -> None:
        for name, combo in self._bindings:
            try:
                modifiers, vk = parse_hotkey(combo)
            except ValueError as exc:
                self.failed.emit(name, str(exc))
                continue
            hotkey_id = self._next_id
            self._next_id += 1
            if user32.RegisterHotKey(hwnd, hotkey_id, modifiers, vk):
                hotkey_ids[hotkey_id] = name
                logger.info("已注册全局热键 %s -> %s", combo, name)
            else:
                reason = "可能被其它程序占用"
                self.failed.emit(name, f"{combo} 注册失败（{reason}）")
                logger.warning("热键注册失败: %s (%s)", combo, ctypes.get_last_error())
