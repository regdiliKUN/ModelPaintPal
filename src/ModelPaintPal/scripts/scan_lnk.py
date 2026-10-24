"""扫描桌面全部 .lnk，统计结构特征，找与手写结构最接近的模板。"""
import struct
import sys
from pathlib import Path

DESKTOP = r"D:\Desktop"


def parse(p: Path):
    d = p.read_bytes()
    if len(d) < 76 or d[:4] != b"\x4c\x00\x00\x00":
        return None
    fl = struct.unpack_from("<I", d, 20)[0]
    fileattr = struct.unpack_from("<I", d, 24)[0]
    li = 76
    if fl & 1:  # HasIDList
        idsz = struct.unpack_from("<H", d, li)[0]
        li += 2 + idsz
    if li + 4 > len(d):
        return None
    lisz = struct.unpack_from("<I", d, li)[0]
    if lisz < 4 or li + lisz > len(d):
        return {"flags": fl, "error": "linkinfo overflow"}
    lihdr = struct.unpack_from("<IIIII", d, li + 4)
    hsz, liflags = lihdr[0], lihdr[1]
    out = {
        "flags": fl, "idlist": bool(fl & 1), "haslinkinfo": bool(fl & 2),
        "fileattr": fileattr, "liflags": liflags, "lihsz": hsz,
        "cnrl": bool(liflags & 2), "unicode": bool(fl & 0x80),
        "size": len(d),
    }
    # 找 VolumeID 编码方式
    if liflags & 1:
        voff = lihdr[2]
        vsize = struct.unpack_from("<I", d, li + voff)[0]
        out["vsize"] = vsize
        if vsize >= 16:
            dtype = struct.unpack_from("<I", d, li + voff + 4)[0]
            vlabeloff = struct.unpack_from("<I", d, li + voff + 12)[0]
            out["dtype"] = dtype
            out["vlabeloff"] = vlabeloff
            seg = d[li + voff + vlabeloff: li + voff + vsize]
            out["label_gbk"] = seg.decode("gbk", errors="replace").rstrip("\x00")
            out["label_u16"] = seg.decode("utf-16-le", errors="replace").rstrip("\x00")
    # local path 编码判定
    if liflags & 1:
        lpoff = lihdr[3]
        seg = d[li + lpoff: li + lisz]
        out["lp_gbk"] = seg.decode("gbk", errors="replace").split("\x00")[0][:80]
        out["lp_u16"] = seg.decode("utf-16-le", errors="replace").split("\x00")[0][:80]
    return out


def main():
    files = sorted(Path(DESKTOP).glob("*.lnk"))
    print(f"total {len(files)} lnk files")
    no_cnrl = []
    for p in files:
        try:
            info = parse(p)
        except Exception as exc:  # noqa: BLE001
            print("ERR", p.name, exc)
            continue
        if info is None:
            print("SKIP(非 lnk)", p.name)
            continue
        if "error" in info:
            print("ERR", p.name, info["error"])
            continue
        if info["haslinkinfo"] and not info["cnrl"]:
            no_cnrl.append((p, info))
    print(f"\n== 有 LinkInfo 且无 CNRL（与我结构同型）: {len(no_cnrl)} 个 ==")
    for p, info in no_cnrl[:8]:
        print("-", p.name)
        for k in ("flags", "idlist", "fileattr", "liflags", "lihsz", "vsize", "dtype",
                  "vlabeloff", "label_gbk", "label_u16", "lp_gbk", "lp_u16", "size"):
            if k in info:
                print(f"   {k} = {info[k]!r}")


if __name__ == "__main__":
    sys.exit(main())
