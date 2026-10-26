# -*- coding: utf-8 -*-
"""选图与照片载入（Android 走 Intent + ContentResolver，桌面走 tkinter）。

**为什么不用 ``plyer.filechooser``**

它的 Android 实现是 ``intent.getData().getPath()``。现代图库（相册、Google 相册、
DocumentsUI）返回的是 ``content://media/picker/.../1234`` 这类 URI，``getPath()``
只会给出 ``/document/image:1234`` 这种 **假路径** —— 既不存在于文件系统，
也不是真实文件名。于是 ``PIL.Image.open()`` 直接抛 ``FileNotFoundError``，
界面就停在「尚未选择照片」，用户只看到选完照片什么都没发生。

这里改成自己发 Intent，拿到 URI 后用 ``ContentResolver`` 把字节读出来，
转换成一张普通的本地 PNG 缓存，再交给 Kivy 显示。顺带解决三件事：

* 手机照片带 EXIF 旋转标记，Kivy 不认 —— 这里先摆正再存；
* 长边超过 2560px 的图会缩到 2560，省内存也避开部分 GPU 的纹理尺寸上限；
* 只保留最近几张缓存，不会悄悄吃满存储。
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

MAX_EDGE = 2560          # 长边上限（像素）
KEEP_CACHE = 5           # 缓存里保留最近几张照片
_REQUEST_CODE = 0x4D50   # 'MP'，与其它 intent 区分

_pending = False


@dataclass
class Photo:
    """载入后的照片：``pil`` 用来取样，``path`` 给界面的 Image 控件。"""

    pil: object            # PIL.Image.Image（已转 RGB、已摆正、已缩放）
    path: str              # 本地缓存 PNG 路径
    width: int
    height: int


# ------------------------------------------------------------------ 公共入口
def pick_image(on_done: Callable[[Optional[Photo], str], None]) -> None:
    """打开图库选一张照片。

    ``on_done(photo, error)`` 在主线程回调：成功时 ``error`` 为空串，
    取消时 ``photo`` 为 None 且 ``error`` 为空串，失败时 ``error`` 是给用户看的中文提示。
    """
    global _pending
    if _pending:                     # 连点两下不要弹两个图库
        return
    _pending = True

    def finish(photo: Optional[Photo], error: str) -> None:
        global _pending
        _pending = False
        _deliver(on_done, photo, error)

    try:
        if is_android():
            _pick_android(finish)
        else:
            _pick_desktop(finish)
    except Exception as exc:         # pragma: no cover - 设备相关
        finish(None, f"打不开图库（{type(exc).__name__}）")


def is_android() -> bool:
    return "ANDROID_ARGUMENT" in os.environ


def cache_dir() -> Path:
    from app.core.paths import user_path

    folder = Path(user_path("photo_cache"))
    folder.mkdir(parents=True, exist_ok=True)
    return folder


# ------------------------------------------------------------------ 主线程回调
def _deliver(on_done, photo, error) -> None:
    from kivy.clock import Clock

    def _run(*_args):
        try:
            on_done(photo, error)
        except Exception:            # pragma: no cover - 回调本身出错不应拖垮 App
            pass

    Clock.schedule_once(_run, 0)


# ------------------------------------------------------------------ Android
def _pick_android(finish) -> None:
    from android import activity
    from jnius import autoclass

    Intent = autoclass("android.content.Intent")
    PythonActivity = autoclass("org.kivy.android.PythonActivity")

    def on_result(request_code, result_code, intent):
        if request_code != _REQUEST_CODE:
            return
        try:
            activity.unbind(on_activity_result=on_result)
        except Exception:
            pass
        if result_code != -1 or intent is None:      # -1 == RESULT_OK
            return finish(None, "")                  # 用户取消，静默返回
        uri = intent.getData()
        if uri is None:
            return finish(None, "没有拿到照片地址")

        # 读字节 + 解码缩放可能要好几百毫秒（上亿像素的照片更久），
        # 放在主线程会卡住界面甚至触发系统 ANR，所以丢到后台线程。
        # finish → _deliver 本身会切回主线程。
        def work():
            try:
                finish(_load_bytes(_read_uri(uri)), "")
            except Exception as exc:
                finish(None, f"照片载入失败（{type(exc).__name__}）")

        threading.Thread(target=work, daemon=True).start()

    activity.bind(on_activity_result=on_result)

    intent = Intent(Intent.ACTION_GET_CONTENT)
    intent.addCategory(Intent.CATEGORY_OPENABLE)
    intent.setType("image/*")
    try:
        PythonActivity.mActivity.startActivityForResult(intent, _REQUEST_CODE)
    except Exception:
        # 个别精简系统没有实现 GET_CONTENT，退回最老的相册选择
        MediaStore = autoclass("android.provider.MediaStore$Images$Media")
        pick = Intent(Intent.ACTION_PICK, MediaStore.EXTERNAL_CONTENT_URI)
        PythonActivity.mActivity.startActivityForResult(pick, _REQUEST_CODE)


def _read_uri(uri) -> bytes:
    """把 content:// URI 的字节读出来。优先走真实 fd，退路是 InputStream。"""
    if (uri.getScheme() or "").lower() == "file":
        with open(uri.getPath(), "rb") as fh:
            return fh.read()

    from jnius import autoclass

    resolver = autoclass(
        "org.kivy.android.PythonActivity").mActivity.getContentResolver()
    pfd = resolver.openFileDescriptor(uri, "r")
    if pfd is None:
        raise IOError("无法打开这张照片")

    data = b""
    try:
        fd = pfd.getFd()
        chunks = []
        while True:
            block = os.read(fd, 1 << 16)
            if not block:
                break
            chunks.append(block)
        data = b"".join(chunks)
    except OSError:
        data = _read_stream(resolver, uri)
    finally:
        try:
            pfd.close()
        except Exception:
            pass

    if not data:
        raise IOError("照片内容为空")
    return data


def _read_stream(resolver, uri) -> bytes:
    """兜底：直接从 Java InputStream 按块读（比 fd 慢，但总能拿到数据）。"""
    from jnius import jarray

    stream = resolver.openInputStream(uri)
    if stream is None:
        raise IOError("无法打开这张照片")
    buf = jarray("b")([0] * 65536)
    out = []
    try:
        while True:
            n = stream.read(buf, 0, 65536)
            if not n or n <= 0:
                break
            out.append(bytes(bytearray(buf[:n])))
    finally:
        try:
            stream.close()
        except Exception:
            pass
    return b"".join(out)


# ------------------------------------------------------------------ 桌面
def _pick_desktop(finish) -> None:
    path = ""
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        try:
            root.attributes("-topmost", True)
        except Exception:
            pass
        path = filedialog.askopenfilename(
            title="选择照片",
            filetypes=[("图片", "*.jpg *.jpeg *.png *.bmp *.webp"),
                       ("所有文件", "*.*")]) or ""
        root.destroy()
    except Exception:
        path = ""

    if not path:
        try:
            from plyer import filechooser
        except Exception:
            return finish(None, "此环境没有可用的文件选择器")
        box = {}
        filechooser.open_file(on_selection=lambda sel: box.setdefault("v", sel))
        sel = box.get("v") or []
        path = sel[0] if sel else ""
    if not path:
        return finish(None, "")

    try:
        with open(path, "rb") as fh:
            finish(_load_bytes(fh.read()), "")
    except Exception as exc:
        finish(None, f"照片载入失败（{type(exc).__name__}）")


# ------------------------------------------------------------------ 解码落盘
def _resample():
    from PIL import Image as PILImage

    try:
        return PILImage.Resampling.LANCZOS
    except AttributeError:               # Pillow < 9.1
        return PILImage.LANCZOS


def _load_bytes(data: bytes) -> Photo:
    import io

    from PIL import Image as PILImage
    from PIL import ImageOps

    img = PILImage.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img) or img        # 手机照片的旋转标记
    img = img.convert("RGB")
    if max(img.size) > MAX_EDGE:
        img.thumbnail((MAX_EDGE, MAX_EDGE), _resample())

    folder = cache_dir()
    path = folder / f"picked-{int(time.time() * 1000)}.png"
    img.save(str(path), "PNG")
    _prune(folder)
    return Photo(pil=img, path=str(path), width=img.size[0], height=img.size[1])


def _prune(folder: Path) -> None:
    try:
        files = sorted(folder.glob("picked-*.png"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return
    for old in files[KEEP_CACHE:]:
        try:
            old.unlink()
        except OSError:
            pass


__all__ = ["Photo", "pick_image", "is_android", "cache_dir"]
