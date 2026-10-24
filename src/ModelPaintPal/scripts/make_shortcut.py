"""Create a Windows .lnk shortcut without COM/Add-Type (sandbox-safe, pure file I/O).

Builds a LINKINFO-based link carrying the absolute target path, plus StringData
(Name / WorkingDir / IconLocation). Verified by parsing the bytes back.

桌面目录必须走注册表解析：`Path.home()/"Desktop"` 在桌面被重定向（如 D:\\Desktop）
或 OneDrive 接管时指向的是一个**空目录**，快捷方式会写进那里而用户看不到。
"""
import argparse
import os
import struct
import sys
from pathlib import Path

SHELL_LINK_CLSID = bytes([0x01, 0x14, 0x02, 0x00, 0x00, 0x00, 0x00, 0x00,
                          0xC0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x46])


def _u16(s: str):
    return s.encode("utf-16-le")


def _ansi(s: str) -> bytes:
    """LINKINFO 里的路径/卷标用系统默认代码页（ANSI），**不是** UTF-16。

    MS-SHLLINK 的 Unicode 标志只作用于 StringData 段；LINKINFO 的 LocalBasePath
    始终是 ANSI。写成 UTF-16 会让 shell 读到乱码路径，双击报
    「没有应用程序与此操作关联」(ERROR_NO_ASSOCIATION, 1155)。
    路径含非 ANSI 字符时退回 UTF-8 转不了就抛错，让调用方看到明确原因。
    """
    try:
        return s.encode("mbcs")
    except (LookupError, UnicodeEncodeError) as exc:
        raise ValueError(f"路径无法用 ANSI 代码页表示，无法写入 LINKINFO: {s!r}") from exc


def _volume_id(target_path: str) -> bytes:
    """构造 LINKINFO 的 VolumeID 段。

    之前只写了 Size+DriveType 两个 DWORD（Size=8），这是合法的「最短 VolumeID」，
    但部分 shell 解析实现会按 DriveType/DriveSerialNumber/VolumeLabelOffset 顺序
    取值，读到垃圾导致快捷方式解析失败。这里补全成标准结构，盘符类型与序列号
    尽量取自真实卷（ctypes GetVolumeInformationW），取不到就用保守默认值。
    """
    import ctypes

    drive_type = 3          # DRIVE_FIXED
    serial = 0
    label = ""
    root = os.path.splitdrive(target_path)[0] + "\\" if os.path.splitdrive(target_path)[0] else ""
    if root:
        try:
            k32 = ctypes.windll.kernel32
            buf = ctypes.create_unicode_buffer(261)
            fs = ctypes.create_unicode_buffer(261)
            serial_c = ctypes.c_ulong(0)
            max_len = ctypes.c_ulong(0)
            flags = ctypes.c_ulong(0)
            if k32.GetVolumeInformationW(ctypes.c_wchar_p(root), buf, 261,
                                         ctypes.byref(serial_c), ctypes.byref(max_len),
                                         ctypes.byref(flags), fs, 261):
                drive_type = k32.GetDriveTypeW(ctypes.c_wchar_p(root))
                serial = serial_c.value
                label = buf.value
        except Exception:            # noqa: BLE001 — 取不到信息就用默认值
            pass

    # VolumeID = { Size(自含), DriveType, DriveSerialNumber, VolumeLabelOffset=0x10, label }
    # —— 与真实 .lnk（如 D:\Desktop\Oopz.lnk：size 30 / type 3 / serial / labeloff 16）逐字段一致。
    # 注意 Size 必须包含 Size 字段本身，且这里**只有这四个 DWORD**，不能再多一个头字段
    # （之前多写了 0x10，把 DriveType/Serial 挤后 4 字节，shell 解析失败 → 双击无反应）。
    label_bytes = _ansi(label + "\x00")
    size = 4 + 12 + len(label_bytes)
    body = struct.pack("<IIII", size, drive_type, serial, 0x10) + label_bytes
    return body


def build_link(target: str, working_dir: str, icon: str, description: str) -> bytes:
    link_flags = 0
    link_flags |= 0x02  # HasLinkInfo
    link_flags |= 0x80  # IsUnicode
    link_flags |= 0x04  # HasName
    link_flags |= 0x10  # HasWorkingDir
    link_flags |= 0x40  # HasIconLocation

    # ---- LINKINFO (absolute local path) ----
    local_path = _ansi(target + "\x00")          # ANSI（系统代码页），NUL terminated
    volume_id = _volume_id(target)

    header_size = 28
    volume_id_offset = header_size
    local_path_offset = volume_id_offset + len(volume_id)
    common_suffix_offset = local_path_offset + len(local_path)

    body = b""
    body += struct.pack("<I", header_size)              # HeaderSize
    body += struct.pack("<I", 0x01)                     # LinkInfoFlags: VolumeIDAndLocalPath
    body += struct.pack("<I", volume_id_offset)         # VolumeIDOffset
    body += struct.pack("<I", local_path_offset)        # LocalPathOffset
    body += struct.pack("<I", 0)                        # CommonNetworkRelativeLinkOffset
    body += struct.pack("<I", common_suffix_offset)     # CommonPathSuffixOffset
    body += volume_id
    body += local_path
    body += _ansi("\x00")                                # CommonPathSuffix: 空串
    linkinfo = struct.pack("<I", len(body) + 4) + body  # Size (includes the Size field itself)

    # ---- STRING DATA (order: Name, [RelPath], WorkingDir, [Args], Icon) ----
    def strblock(s: str) -> bytes:
        return struct.pack("<H", len(s) + 1) + _u16(s + "\x00")

    name = strblock(description)
    workdir = strblock(working_dir)
    iconloc = strblock(f"{icon},0")

    # ---- HEADER ----
    header = b""
    header += struct.pack("<I", 76)            # HeaderSize
    header += SHELL_LINK_CLSID
    header += struct.pack("<I", link_flags)
    header += struct.pack("<I", 0x20)          # FileAttributes: FILE_ATTRIBUTE_ARCHIVE
    header += struct.pack("<Q", 0)             # CreationTime
    header += struct.pack("<Q", 0)             # AccessTime
    header += struct.pack("<Q", 0)             # WriteTime
    header += struct.pack("<I", 0)             # FileSize
    header += struct.pack("<i", 0)             # IconIndex
    header += struct.pack("<I", 1)             # ShowCommand: SW_SHOWNORMAL
    header += struct.pack("<H", 0)             # HotKey
    header += struct.pack("<H", 0)             # Reserved1
    header += struct.pack("<I", 0)             # Reserved2
    header += struct.pack("<I", 0)             # Reserved3

    # ---- EXTRA DATA：必须以 TerminalBlock（4 字节全 0）收尾 ----
    # 这是 MS-SHLLINK 的硬性要求；之前缺了它，Explorer 会把文件当损坏的快捷方式，
    # 双击弹「此快捷方式指向的项目已更改或移动」甚至直接拒绝打开。
    terminal_block = b"\x00\x00\x00\x00"
    return header + linkinfo + name + workdir + iconloc + terminal_block


def resolve_desktop() -> Path:
    """返回「用户真正看到的桌面」目录。

    优先级：注册表 User Shell Folders\\Desktop（REG_EXPAND_SZ，需展开 %USERPROFILE%）
    → Shell Folders\\Desktop（已展开的缓存值）→ 环境变量 → <home>/Desktop。
    只返回存在的目录；全部落空时退回 <home>/Desktop（至少不会崩）。
    """
    if sys.platform != "win32":
        return Path.home() / "Desktop"

    import winreg

    candidates = []
    for sub, name in (
        (r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders", "Desktop"),
        (r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders", "Desktop"),
    ):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, sub) as key:
                raw = winreg.QueryValueEx(key, name)[0]
        except OSError:
            continue
        if raw:
            candidates.append(Path(os.path.expandvars(raw)))

    env = os.environ.get("USERPROFILE")
    if env:
        candidates.append(Path(env) / "Desktop")
    candidates.append(Path.home() / "Desktop")

    for path in candidates:
        if path.is_dir():
            return path
    return candidates[0]


def main(argv=None):
    parser = argparse.ArgumentParser(description="创建桌面快捷方式（纯文件写入，无需 COM）")
    parser.add_argument("--desktop", help="显式指定桌面目录（默认从注册表解析）")
    parser.add_argument("--name", default="3D 打印模型涂装配色助手.lnk", help="快捷方式文件名")
    parser.add_argument("--dry-run", action="store_true", help="只打印将写入的位置，不落盘")
    args = parser.parse_args(argv)

    dst = Path.home() / "AppData" / "Local" / "Programs" / "ModelPaintPal"
    exe = dst / "ModelPaintPal.exe"
    desktop = Path(args.desktop).expanduser() if args.desktop else resolve_desktop()
    lnk = desktop / args.name

    if not exe.exists():
        print(f"ERROR: target exe not found: {exe}")
        return 1

    print(f"DESKTOP dir: {desktop}")
    if args.dry_run:
        print(f"WOULD WRITE {lnk}")
        return 0

    data = build_link(str(exe), str(dst), str(exe), "ModelPaintPal - 3D 打印模型涂装配色助手")
    try:
        desktop.mkdir(parents=True, exist_ok=True)
        lnk.write_bytes(data)
    except PermissionError as exc:
        print(f"ERROR: 无法写入 {lnk}（{exc}）。若文件被资源管理器占用，先删除旧文件再试。")
        return 2
    print(f"WROTE {lnk} ({len(data)} bytes)")

    # ---- verify by parsing the LocalPath back ----
    lip = 76
    lp_off = struct.unpack_from("<I", data, lip + 16)[0]
    start = lip + lp_off
    end = data.index(b"\x00", start)
    decoded = data[start:end].decode("mbcs")
    print(f"VERIFY target path in link: {decoded}")
    print("OK" if decoded == str(exe) else "MISMATCH")
    return 0


if __name__ == "__main__":
    sys.exit(main())
