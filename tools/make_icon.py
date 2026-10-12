# -*- coding: utf-8 -*-
"""把一张方形成品图加工成 Windows 应用图标（多尺寸 .ico）。

为什么写成脚本而不是手工导一次：图标将来一定会换（角色改版、配色调整、
适配深色任务栏），手工做一遍步骤就丢了。跑这个脚本可以从母版一致地重建。

它做四件事：

    ① 抠掉外围的白底（从四角泛洪，只吃「与边界连通的浅色」，不伤图标内部的白）
    ② 裁到内容边界并保证正方形
    ③ 输出透明背景的 1024 母版 PNG
    ④ 生成多尺寸 .ico（256/128/64/48/32/16）—— Windows 会按场合自动挑尺寸

⚠️ 依赖 **Pillow**，只在生成图标时用到，程序运行时不需要：
    pip install Pillow
用法：
    python tools/make_icon.py <源图> [--out assets/icon] [--preview <目录>]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

#: 生成的尺寸。256 是 Windows 大图标上限，16 是任务栏真实尺寸。
ICON_SIZES = (256, 128, 64, 48, 32, 16)
#: 泛洪时把「离白色多远」算作背景。JPG 在边缘有压缩噪点，放宽一点才吃得干净。
WHITE_TOLERANCE = 60


def is_light(px: tuple[int, int, int], tol: int = 40) -> bool:
    return min(px) >= 255 - tol


def cut_out_background(src: Image.Image) -> Image.Image:
    """把与四边连通的浅色区域变透明，返回 RGBA。

    关键在「连通」二字：只能从四角往里泛洪，这样图标**内部**的白色
    （月亮、书页、衣服）因为被深色描边隔开，不会被误伤 —— 这是简单的
    「白色变透明」做不到的，那样会把角色身上的白也抠掉。
    """
    img = src.convert('RGBA')
    work = img.convert('RGB').copy()
    w, h = work.size
    magic = (255, 0, 255)          # 一个不会出现在原图里的哨兵色

    corners = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]
    filled = 0
    for corner in corners:
        if is_light(work.getpixel(corner)):
            ImageDraw.floodfill(work, corner, magic, thresh=WHITE_TOLERANCE)
            filled += 1
    if not filled:
        raise SystemExit('四角都不是浅色背景 —— 这张图可能已经被裁过，或背景不是纯色。')

    sentinel = Image.new('RGB', work.size, magic)
    outside = ImageChops.difference(work, sentinel).convert('L').point(
        lambda v: 0 if v == 0 else 255, 'L')      # 0 = 是外部区域

    # 轻微柔化 alpha：泛洪是二值的，直接用它会在圆角处留下硬边
    alpha = outside.filter(ImageFilter.GaussianBlur(0.6))
    img.putalpha(alpha)
    return img


def crop_square(img: Image.Image, margin_ratio: float = 0.0) -> Image.Image:
    """裁到内容边界，并补成正方形（缩放时不会变形）。"""
    bbox = img.getbbox()
    if bbox is None:
        raise SystemExit('抠完之后整张图都是透明的 —— 检查源图。')
    left, top, right, bottom = bbox
    side = max(right - left, bottom - top)
    side = int(side * (1 + margin_ratio * 2))
    cx, cy = (left + right) // 2, (top + bottom) // 2
    box = (cx - side // 2, cy - side // 2, cx + side // 2, cy + side // 2)
    return img.crop(box)


def sharpen_small(size: int, img: Image.Image) -> Image.Image:
    """小尺寸单独锐化。

    16/32 像素下，插画里那些细线（书脊、睫毛、发丝）会糊成一团灰。
    轻微反锐化能把主体轮廓重新拎出来，比纯缩放的观感清楚一档。
    """
    out = img.resize((size, size), Image.LANCZOS)
    if size <= 32:
        out = out.filter(ImageFilter.UnsharpMask(radius=0.8, percent=90, threshold=2))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description='把方形成品图加工成多尺寸 .ico')
    ap.add_argument('source', help='源图（jpg / png 均可）')
    ap.add_argument('--out', default='assets/icon', help='输出目录')
    ap.add_argument('--preview', default='', help='额外导出各尺寸 PNG 供核对')
    args = ap.parse_args()

    src_path = Path(args.source)
    if not src_path.is_file():
        raise SystemExit(f'源图不存在：{src_path}')
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    src = Image.open(src_path)
    print(f'源图：{src_path.name}  {src.size[0]}×{src.size[1]}  {src.mode}')

    cut = cut_out_background(src)
    square = crop_square(cut)
    master_side = max(square.size)
    if master_side != 1024:
        square = square.resize((1024, 1024), Image.LANCZOS)
    print(f'抠图并裁切完成，母版 {square.size[0]}×{square.size[1]}')

    master_path = out_dir / 'app.png'
    square.save(master_path, optimize=True)
    print(f'母版 → {master_path}')

    frames = [sharpen_small(size, square) for size in ICON_SIZES]
    ico_path = out_dir / 'app.ico'
    frames[0].save(ico_path, format='ICO',
                   sizes=[(s, s) for s in ICON_SIZES])
    print(f'图标 → {ico_path}（{len(ICON_SIZES)} 个尺寸：'
          f'{", ".join(str(s) for s in ICON_SIZES)}）')

    if args.preview:
        pv = Path(args.preview)
        pv.mkdir(parents=True, exist_ok=True)
        for size, frame in zip(ICON_SIZES, frames):
            frame.save(pv / f'size_{size:03d}.png')
        # 一张放大的拼图：小尺寸糊不糊，放大才看得出来
        scaled = [f.resize((f.width * 4, f.height * 4), Image.NEAREST)
                  for f in frames if f.width <= 32]
        if scaled:
            sheet = Image.new('RGBA', (sum(s.width for s in scaled) + 40,
                                       max(s.height for s in scaled) + 20),
                              (30, 30, 32, 255))
            x = 10
            for s in scaled:
                sheet.paste(s, (x, 10), s)
                x += s.width + 10
            sheet.save(pv / 'small_sizes_4x.png')
        print(f'各尺寸预览 → {pv}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
