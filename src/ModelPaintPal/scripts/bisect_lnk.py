"""二分排查：逐个变体生成 .lnk（目标 notepad），用 os.startfile 实测哪个能被 shell 接受。"""
import ctypes
import ctypes.wintypes as wt
import os
import struct
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_shortcut import _ansi, SHELL_LINK_CLSID  # noqa: E402

TARGET = r"C:\Windows\System32\notepad.exe"


def build(flags=0x02, strings=True, volume=True, terminal=True, fileattr=0x20,
          target=TARGET, workdir=None, icon=None, label=""):
    # LINKINFO
    local_path = _ansi(target + "\x00")
    if volume:
        vb = struct.pack("<IIII", 16 + len(_ansi(label + "\x00")), 3, 0x1234ABCD, 0x10)
        vb += _ansi(label + "\x00")
    else:
        vb = b""
    hs = 28
    voff = hs if volume else 0
    lpoff = voff + len(vb) if volume else hs
    csoff = lpoff + len(local_path)
    body = struct.pack("<IIIIII", hs, 0x01, voff, lpoff, 0, csoff) + vb + local_path + _ansi("\x00")
    linkinfo = struct.pack("<I", len(body) + 4) + body

    extra = b""
    if strings:
        def blk(s):
            return struct.pack("<H", len(s) + 1) + s.encode("utf-16-le") + "\x00".encode("utf-16-le")
        name = blk("test") if (flags & 0x04) else b""
        work = blk(workdir) if (flags & 0x10) else b""
        iconb = blk(icon + ",0") if (flags & 0x40) else b""
        extra = name + work + iconb
    if terminal:
        extra += b"\x00\x00\x00\x00"

    h = struct.pack("<I", 76) + SHELL_LINK_CLSID + struct.pack("<I", flags)
    h += struct.pack("<I", fileattr)
    h += struct.pack("<Q", 0) * 3
    h += struct.pack("<I", 0) + struct.pack("<i", 0) + struct.pack("<I", 1)
    h += struct.pack("<H", 0) + struct.pack("<H", 0) + struct.pack("<I", 0) + struct.pack("<I", 0)
    return h + linkinfo + extra


def running(sub="notepad"):
    k32 = ctypes.windll.kernel32
    arr = (wt.DWORD * 4096)()
    needed = wt.DWORD()
    ctypes.windll.psapi.EnumProcesses(ctypes.byref(arr), ctypes.sizeof(arr), ctypes.byref(needed))
    for pid in arr[: needed.value // ctypes.sizeof(wt.DWORD)]:
        if not pid:
            continue
        h = k32.OpenProcess(0x0400 | 0x0010, False, pid)
        if not h:
            continue
        name = ctypes.create_unicode_buffer(260)
        n = wt.DWORD(260)
        ctypes.windll.psapi.GetModuleFileNameExW(h, None, name, ctypes.byref(n))
        k32.CloseHandle(h)
        if sub in name.value.lower():
            return pid
    return None


def kill_notepads():
    k32 = ctypes.windll.kernel32
    while True:
        pid = running()
        if not pid:
            return
        h = k32.OpenProcess(0x0001, False, pid)
        if h:
            k32.TerminateProcess(h, 0)
            k32.CloseHandle(h)
        time.sleep(0.2)


VARIANTS = [
    ("v1_min_flags02", dict()),
    ("v2_no_volume", dict(volume=False)),
    ("v3_no_terminal", dict(terminal=False)),
    ("v4_fileattr0", dict(fileattr=0)),
    ("v5_no_label", dict(label="")),
    ("v6_with_label", dict(label="系统盘")),
    ("v7_min_plus_strings", dict(flags=0x04 | 0x10 | 0x40, workdir=r"C:\Windows\System32",
                                 icon=r"C:\Windows\System32\notepad.exe")),
    ("v8_full_mine", dict(flags=0x04 | 0x10 | 0x40, workdir=r"C:\Windows\System32",
                          icon=r"C:\Windows\System32\notepad.exe", label="系统盘")),
]


def main():
    tmp = tempfile.mkdtemp(prefix="mpal_bisect_")
    for tag, kw in VARIANTS:
        lnk = os.path.join(tmp, tag + ".lnk")
        data = build(**kw)
        with open(lnk, "wb") as f:
            f.write(data)
        try:
            os.startfile(lnk)
            time.sleep(2.5)
            pid = running()
            if pid:
                print(f"[{tag}] OPEN+RUN pid={pid}")
                kill_notepads()
            else:
                print(f"[{tag}] accepted but notepad not detected")
        except OSError as exc:
            print(f"[{tag}] FAIL: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
