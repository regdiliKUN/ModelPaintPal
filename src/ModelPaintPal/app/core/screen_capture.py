# -*- coding: utf-8 -*-
"""屏幕像素采集。

设计要点：
* Windows 下显式声明 Per-Monitor DPI Awareness，保证 ``GetCursorPos`` 返回的
  是**物理像素**坐标，和 mss 抓到的位图坐标一致；否则在 125%/150% 缩放下
  吸色会整体偏移。
* 优先使用 mss（快、跨屏可靠），失败时回落到 Pillow 的 ImageGrab。
* 抓图过程中的任何异常都向上抛给调用方，由 UI 层决定提示方式。
"""

from __future__ import annotations

import ctypes
from typing import List, Tuple

from .logging_setup import get_logger

logger = get_logger(__name__)

__all__ = ["ScreenCapture", "set_dpi_aware", "IS_WINDOWS", "CaptureError"]

try:  # pragma: no cover - 依赖环境
    import mss  # type: ignore
except ImportError:  # pragma: no cover
    mss = None  # type: ignore

try:  # pragma: no cover
    from PIL import Image, ImageGrab  # type: ignore
except ImportError:  # pragma: no cover
    Image = None  # type: ignore
    ImageGrab = None  # type: ignore

import platform

IS_WINDOWS = platform.system() == "Windows"


class CaptureError(RuntimeError):
    """抓屏失败。"""


def set_dpi_aware() -> bool:
    """声明进程级 DPI 感知。返回是否成功（失败不影响主流程，只是精度下降）。"""
    if not IS_WINDOWS:
        return False
    try:
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
        ok = ctypes.windll.shcore.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        if ok:
            return True
    except (AttributeError, OSError) as exc:
        logger.debug("SetProcessDpiAwarenessContext 不可用: %s", exc)
    try:
        return bool(ctypes.windll.user32.SetProcessDPIAware())
    except (AttributeError, OSError) as exc:
        logger.debug("SetProcessDPIAware 不可用: %s", exc)
        return False


class _Win32Cursor:
    """Windows 物理像素光标位置 + 按键状态查询。"""

    VK_LBUTTON = 0x01
    VK_RBUTTON = 0x02
    VK_ESCAPE = 0x1B

    @staticmethod
    def pos() -> Tuple[int, int]:
        import ctypes.wintypes as wt

        pt = wt.POINT()
        if ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
            return int(pt.x), int(pt.y)
        raise CaptureError("GetCursorPos 调用失败")

    @staticmethod
    def key_down(virtual_key: int) -> bool:
        state = ctypes.windll.user32.GetAsyncKeyState(virtual_key)
        return bool(state & 0x8000)


class ScreenCapture:
    """抓屏服务（惰性初始化，可反复 start/stop）。"""

    def __init__(self) -> None:
        self._sct = None
        self._dpi_set = False

    # ------------------------------------------------------------ 生命周期
    def start(self) -> "ScreenCapture":
        if not self._dpi_set:
            self._dpi_set = set_dpi_aware()
        if mss is not None and self._sct is None:
            try:
                self._sct = mss.mss()
            except Exception as exc:  # mss 内部异常类型不固定
                logger.warning("mss 初始化失败，回落到 ImageGrab: %s", exc)
                self._sct = None
        return self

    def stop(self) -> None:
        if self._sct is not None:
            try:
                self._sct.close()
            except Exception:  # pragma: no cover
                pass
            self._sct = None

    def __enter__(self) -> "ScreenCapture":
        return self.start()

    def __exit__(self, *exc_info) -> None:
        self.stop()

    # ---------------------------------------------------------------- 查询
    @property
    def backend(self) -> str:
        return "mss" if self._sct is not None else "imagegrab"

    def monitors(self) -> List[dict]:
        """返回显示器矩形列表（物理像素）。索引 0 为虚拟桌面整体。"""
        if self._sct is not None:
            return [dict(m) for m in self._sct.monitors]
        return [self._fallback_monitor()]

    def cursor_pos(self) -> Tuple[int, int]:
        if IS_WINDOWS:
            try:
                return _Win32Cursor.pos()
            except CaptureError:
                logger.debug("GetCursorPos 失败，回落到 Qt 光标")
        from PySide6.QtGui import QCursor

        pos = QCursor.pos()
        return int(pos.x()), int(pos.y())

    def is_mouse_down(self, button: str = "left") -> bool:
        """非阻塞查询鼠标键是否按下，用于吸色确认（无钩子、无需管理员权限）。"""
        if IS_WINDOWS:
            vk = _Win32Cursor.VK_LBUTTON if button == "left" else _Win32Cursor.VK_RBUTTON
            return _Win32Cursor.key_down(vk)
        from PySide6.QtWidgets import QApplication

        buttons = QApplication.mouseButtons()
        from PySide6.QtCore import Qt

        return bool(buttons & (Qt.LeftButton if button == "left" else Qt.RightButton))

    def is_key_down(self, virtual_key: int) -> bool:
        if IS_WINDOWS:
            return _Win32Cursor.key_down(virtual_key)
        return False

    # ---------------------------------------------------------------- 抓图
    def grab(self, left: int, top: int, width: int, height: int):
        """抓取指定矩形，返回 PIL.Image（RGB）。宽度/高度至少为 1。"""
        width = max(1, int(width))
        height = max(1, int(height))
        if self._sct is not None:
            try:
                shot = self._sct.grab({
                    "left": int(left), "top": int(top),
                    "width": width, "height": height,
                })
                return Image.frombytes("RGB", shot.size, shot.rgb)
            except Exception as exc:
                raise CaptureError(f"mss 抓屏失败: {exc}") from exc
        if ImageGrab is None:
            raise CaptureError("没有可用的抓屏后端（mss 与 Pillow 均不可用）")
        try:
            box = (left, top, left + width, top + height)
            return ImageGrab.grab(bbox=box, all_screens=True).convert("RGB")
        except Exception as exc:
            raise CaptureError(f"ImageGrab 抓屏失败: {exc}") from exc

    def pixel(self, x: int, y: int) -> Tuple[int, int, int]:
        img = self.grab(int(x), int(y), 1, 1)
        return img.getpixel((0, 0))[:3]

    def region(self, x: int, y: int, size: int):
        """以 (x, y) 为中心抓取 size×size 的区域。

        返回 ``(image, left, top)``，其中 ``left/top`` 为真实抓图的左上角坐标
        （可能被夹取到屏幕范围内，见下）。光标贴近屏幕边缘时，以光标为中心的区域
        会越出显示器边界，mss 直接抛 ``ScreenShotError`` 让整个吸色会话崩溃；这里
        把抓取矩形夹取到「全部显示器的外接矩形」之内，并把真实原点一并返回，调用方
        据此在图内定位光标像素，做到「边缘也能正常吸色且不崩」。
        """
        size = max(1, int(size))
        half = size // 2
        left = int(x) - half
        top = int(y) - half
        # monitor[0] 为全部显示器的外接矩形（虚拟桌面）
        monitors = self.monitors()
        if monitors:
            vb = monitors[0]
            vx0 = int(vb.get("left", 0))
            vy0 = int(vb.get("top", 0))
            vx1 = vx0 + int(vb.get("width", 0))
            vy1 = vy0 + int(vb.get("height", 0))
            if vx1 > vx0 and vy1 > vy0:
                left = max(vx0, min(left, vx1 - size))
                top = max(vy0, min(top, vy1 - size))
        image = self.grab(left, top, size, size)
        return image, left, top

    @staticmethod
    def _fallback_monitor() -> dict:
        from PySide6.QtWidgets import QApplication

        screen = QApplication.primaryScreen()
        geo = screen.geometry() if screen else None
        if geo is None:
            return {"left": 0, "top": 0, "width": 1920, "height": 1080}
        return {"left": geo.left(), "top": geo.top(), "width": geo.width(), "height": geo.height()}


def average_pixels(image, size: int = 1, cx: int = None, cy: int = None) -> Tuple[int, int, int]:
    """对 PIL 图像取以 ``(cx, cy)`` 为中心的 ``size×size`` 区域的平均值。

    ``cx/cy`` 省略时默认取图像中心。在屏幕边缘抓取导致区域被夹取后，调用方应传入
    光标在图内的真实坐标，保证取到的是光标处的像素而非偏移后的中心。
    """
    width, height = image.size
    if cx is None:
        cx = width // 2
    if cy is None:
        cy = height // 2
    half = max(0, int(size) // 2)
    left = max(0, cx - half)
    top = max(0, cy - half)
    right = min(width, cx + half + 1)
    bottom = min(height, cy + half + 1)
    # 极端偏移下整块落在图外（left>=right 或 top>=bottom），PIL 会直接抛错；
    # 这里提前回落纯黑，保证吸色在屏幕极端角落也不会崩。
    if right <= left or bottom <= top:
        return (0, 0, 0)
    crop = image.crop((left, top, right, bottom))
    pixels = list(crop.getdata())
    if not pixels:
        return (0, 0, 0)
    total = [0, 0, 0]
    for pixel in pixels:
        total[0] += pixel[0]
        total[1] += pixel[1]
        total[2] += pixel[2]
    n = len(pixels)
    return (total[0] // n, total[1] // n, total[2] // n)
