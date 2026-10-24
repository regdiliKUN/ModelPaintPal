"""生成应用图标（多尺寸 .ico）与预览图。

设计意图：一个 **调色盘**（宽椭圆 + 拇指孔）+ 四个颜料池 + 一支画笔，
底色是深石板渐变，保证在浅色/深色任务栏上都够对比；
先用 4× 超采样绘制再降采样，16px 下边缘才不会糊成一团。

用法：
    python scripts/make_icon.py                # 生成 app/resources/icon.ico + 预览 PNG
    python scripts/make_icon.py --size 1024    # 只改超采样尺寸
"""
from __future__ import annotations

import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ICO_PATH = PROJECT_ROOT / "app" / "resources" / "icon.ico"
PREVIEW_PATH = PROJECT_ROOT / "app" / "resources" / "icon-preview.png"

# 四色颜料：红 / 黄 / 绿 / 蓝（与 CIEDE2000 判级色（好/一般/差）刻意区分开）
PAINTS = [(229, 72, 77), (245, 165, 36), (63, 185, 80), (76, 141, 255)]


def _vertical_gradient(size: int, top, bottom):
    from PIL import Image

    grad = Image.new("RGB", (1, size))
    for y in range(size):
        t = y / max(1, size - 1)
        grad.putpixel((0, y), tuple(round(a + (b - a) * t) for a, b in zip(top, bottom)))
    return grad.resize((size, size))


def build_icon(ss: int = 1024):
    from PIL import Image, ImageDraw, ImageFilter

    img = Image.new("RGBA", (ss, ss), (0, 0, 0, 0))

    # ---- 底：圆角方块 + 垂直渐变 + 内侧高光 ----
    radius = int(ss * 0.22)
    mask = Image.new("L", (ss, ss), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, ss - 1, ss - 1], radius=radius, fill=255)
    bg = _vertical_gradient(ss, (44, 50, 62), (22, 25, 32)).convert("RGBA")
    img.paste(bg, (0, 0), mask)

    draw = ImageDraw.Draw(img)
    pad = int(ss * 0.045)
    draw.rounded_rectangle([pad, pad, ss - pad - 1, ss - pad - 1],
                           radius=radius - pad, outline=(255, 255, 255, 26), width=max(2, ss // 220))

    # ---- 调色盘：宽椭圆（白瓷）----
    px0, py0 = int(ss * 0.135), int(ss * 0.245)
    px1, py1 = int(ss * 0.865), int(ss * 0.775)
    plate = Image.new("RGBA", img.size, (0, 0, 0, 0))
    pd = ImageDraw.Draw(plate)
    pd.ellipse([px0, py0, px1, py1], fill=(238, 241, 247, 255))
    pd.ellipse([px0 + int(ss * 0.012), py0 + int(ss * 0.012),
                px1 - int(ss * 0.012), py1 - int(ss * 0.055)], fill=(248, 250, 253, 255))
    img.alpha_composite(plate)

    # ---- 颜料池：4 个圆点，带一点点亮部 ----
    wells = [
        (0.285, 0.435), (0.445, 0.375), (0.605, 0.375), (0.745, 0.445),
    ]
    r = ss * 0.062
    for (fx, fy), color in zip(wells, PAINTS):
        cx, cy = ss * fx, ss * fy
        box = [cx - r, cy - r, cx + r, cy + r]
        draw.ellipse(box, fill=color + (255,))
        hl = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(hl).ellipse([box[0] + r * 0.30, box[1] + r * 0.26,
                                    box[0] + r * 0.92, box[1] + r * 0.86],
                                   fill=(255, 255, 255, 90))
        img.alpha_composite(hl.filter(ImageFilter.GaussianBlur(ss * 0.004)))

    # ---- 画笔：从左下斜插到右上，深木杆 + 金属箍 + 颜料尖 ----
    brush = Image.new("RGBA", img.size, (0, 0, 0, 0))
    bd = ImageDraw.Draw(brush)
    x0, y0 = ss * 0.255, ss * 0.845
    x1, y1 = ss * 0.815, ss * 0.235
    w = ss * 0.052
    bd.line([x0, y0, x1, y1], fill=(58, 44, 36, 255), width=int(w))
    bd.line([x0, y0, x1, y1], fill=(92, 68, 52, 255), width=int(w * 0.55))
    # 金属箍
    fx, fy = x0 + (x1 - x0) * 0.70, y0 + (y1 - y0) * 0.70
    bd.line([fx, fy, fx + (x1 - x0) * 0.14, fy + (y1 - y0) * 0.14],
            fill=(196, 203, 214, 255), width=int(w * 1.15))
    # 笔尖（颜料色，稍长一点更醒目）
    tip0x, tip0y = x1 - (x1 - x0) * 0.09, y1 - (y1 - y0) * 0.09
    bd.line([tip0x, tip0y, x1, y1], fill=PAINTS[3] + (255,), width=int(w * 1.3))
    img.alpha_composite(brush)

    return img


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="生成应用图标")
    parser.add_argument("--size", type=int, default=1024, help="超采样画布尺寸")
    args = parser.parse_args(argv)

    big = build_icon(args.size)
    from PIL import Image

    resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS", 1)
    ICO_PATH.parent.mkdir(parents=True, exist_ok=True)
    big.save(ICO_PATH, format="ICO",
             sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)],
             bitmap_format="png")
    big.resize((512, 512), resample).save(PREVIEW_PATH, format="PNG")
    print(f"ICON  {ICO_PATH} ({ICO_PATH.stat().st_size} bytes)")
    print(f"PREVIEW {PREVIEW_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
