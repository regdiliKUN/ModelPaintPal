# -*- coding: utf-8 -*-
"""吸色流程控制器。

把「抓屏 → 放大镜跟随 → 点击确认 → 发信号」封装成一个可复用的会话：
* 用定时器轮询，不安装全局鼠标钩子（无需管理员权限，也不会被杀软拦）；
* 只有检测到一次**完整的按下动作**才取色，避免启动吸色时那一次点击被误判；
* Esc / 右键取消，异常统一收敛为 ``failed`` 信号。
"""

from __future__ import annotations

from typing import Optional, Tuple

from PySide6.QtCore import QObject, QTimer, Signal

from ...core.logging_setup import get_logger
from ...core.screen_capture import CaptureError, ScreenCapture, average_pixels
from .magnifier import MagnifierWindow

logger = get_logger(__name__)

__all__ = ["PickerController", "POLL_INTERVAL_MS"]

POLL_INTERVAL_MS = 30
_VK_ESCAPE = 0x1B


class PickerController(QObject):
    """一次吸色会话。"""

    colorPicked = Signal(tuple)     # (r, g, b)
    cancelled = Signal()
    failed = Signal(str)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._capture = ScreenCapture()
        self._magnifier: Optional[MagnifierWindow] = None
        self._timer: Optional[QTimer] = None
        self._active = False
        self._armed = False          # 是否已经见过“鼠标未按下”的干净状态
        self._prev_down = False
        self._grid = 15
        self._zoom = 12
        self._follow = True
        self._average = 1

    # ------------------------------------------------------------------ 状态
    @property
    def is_active(self) -> bool:
        return self._active

    def configure(self, grid: int, zoom: int, follow: bool, average: int = 1) -> None:
        self._grid = max(3, int(grid))
        self._zoom = max(2, int(zoom))
        self._follow = bool(follow)
        self._average = max(1, int(average))
        if self._magnifier is not None:
            self._magnifier.configure(self._grid, self._zoom)

    # ------------------------------------------------------------------ 会话
    def start(self) -> bool:
        if self._active:
            return True
        try:
            self._capture.start()
        except Exception as exc:  # 抓屏后端不可用时给出明确提示
            logger.error("抓屏初始化失败: %s", exc)
            self.failed.emit(f"无法启动屏幕捕获：{exc}")
            return False

        self._magnifier = MagnifierWindow(self._grid, self._zoom)
        self._magnifier.show()

        self._active = True
        self._armed = False
        self._prev_down = False
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_INTERVAL_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        return True

    def stop(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer.deleteLater()
            self._timer = None
        if self._magnifier is not None:
            self._magnifier.close()
            self._magnifier.deleteLater()
            self._magnifier = None
        if self._active:
            self._capture.stop()
        self._active = False

    def cancel(self) -> None:
        if not self._active:
            return
        self.stop()
        self.cancelled.emit()

    # ------------------------------------------------------------------ 轮询
    def _tick(self) -> None:
        if not self._active:
            return
        try:
            if self._capture.is_key_down(_VK_ESCAPE):
                self.cancel()
                return
            if self._capture.is_mouse_down("right"):
                self.cancel()
                return

            cursor = self._capture.cursor_pos()
            down = self._capture.is_mouse_down("left")
            if not down:
                self._armed = True
            self._refresh(cursor)
            if self._armed and down and not self._prev_down:
                self._commit(cursor)
                return
            self._prev_down = down
        except CaptureError as exc:
            logger.error("抓屏失败: %s", exc)
            self.stop()
            self.failed.emit(str(exc))
        except Exception as exc:  # 兜底：任何异常都结束会话而不是卡死
            logger.exception("吸色过程异常: %s", exc)
            self.stop()
            self.failed.emit(f"吸色异常：{exc}")

    def _refresh(self, cursor: Tuple[int, int]) -> None:
        if self._magnifier is None:
            return
        image, left, top = self._capture.region(cursor[0], cursor[1], self._grid)
        rgb = average_pixels(image, self._average, cursor[0] - left, cursor[1] - top)
        self._magnifier.set_sample(image, rgb, cursor)
        self._magnifier.follow(cursor, self._follow)

    def _commit(self, cursor: Tuple[int, int]) -> None:
        image, left, top = self._capture.region(cursor[0], cursor[1], self._grid)
        rgb = average_pixels(image, self._average, cursor[0] - left, cursor[1] - top)
        self.stop()
        self.colorPicked.emit(rgb)
