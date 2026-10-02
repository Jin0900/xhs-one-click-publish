# -*- coding: utf-8 -*-
"""run-002 第④步 图片主体处理（白底去背）。
方法：从图像四边多点种子 flood fill 标记与边缘连通的白底（阈值 30），
再由标记生成 alpha 通道并做 1.2px 高斯羽化，输出透明 PNG。
说明：element_img2 是全屏夏日氛围背景图，无独立主体，作为背景层保留，不抠图。
"""
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE / "libs"))
from PIL import Image, ImageDraw, ImageFilter, ImageChops  # noqa: E402

MARKER = (255, 0, 255, 255)  # RGBA 必须用 4 元组，否则 floodfill 静默失效
THRESH = 40
FEATHER = 1.0


def remove_white_bg(src: Path, dst: Path) -> None:
    img = Image.open(src).convert("RGBA")
    w, h = img.size
    px = img.load()

    # 四边每隔 64px 取种子，仅在种子本身为近白背景时才填充
    step = 64
    seeds = []
    for x in range(0, w, step):
        seeds += [(x, 0), (x, h - 1)]
    for y in range(0, h, step):
        seeds += [(0, y), (w - 1, y)]
    seeds += [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]

    # 四边 flood fill 去除与边缘连通的白底
    used = 0
    for x, y in seeds:
        r, g, b, _ = px[x, y]
        if r > 230 and g > 230 and b > 230:
            ImageDraw.floodfill(img, (x, y), MARKER, thresh=THRESH)
            used += 1

    r, g, b, _ = img.split()
    # 品红染色量 = min(r,b) - g：纯品红=255，白/灰/绿叶≈0，边缘半染色=中间值
    min_rb = ImageChops.darker(r, b)
    stain = ImageChops.subtract(min_rb, g)
    # 软 alpha：染色量放大截断后反转（纯品红→透明，粉边→半透明）
    alpha = stain.point(lambda v: 255 - min(v * 2, 255))
    # 颜色去溢：把染色像素的 g 提升到 min(r,b)，消除粉边，正常像素不变
    g_fixed = ImageChops.lighter(g, min_rb)
    img = Image.merge("RGBA", (r, g_fixed, b, alpha.filter(ImageFilter.GaussianBlur(FEATHER))))
    img.save(dst)

    hist = alpha.histogram()
    transparent = hist[0]
    total = w * h
    print(
        f"[OK] {src.name} -> {dst.name} | 种子数 {used} | "
        f"透明占比 {transparent/total:.1%} | {dst.stat().st_size} bytes",
        flush=True,
    )


def main() -> None:
    # 主图优先使用无阴影的 v2，失败时回退原始素材
    main_src = "main_image_v2.png" if (BASE / "main_image_v2.png").exists() else "main_image.png"
    print(f"[INFO] 主图源使用: {main_src}", flush=True)
    targets = [
        (main_src, "main_image_cutout.png"),
        ("element_img1.png", "element_img1_cutout.png"),
    ]
    for src_name, dst_name in targets:
        src = BASE / src_name
        dst = BASE / dst_name
        if not src.exists():
            print(f"[FAILED] 缺少素材 {src}", flush=True)
            continue
        remove_white_bg(src, dst)
    bg = BASE / "element_img2.png"
    print(
        f"[SKIP] {bg.name} 为全屏氛围背景图，无独立主体，保留原图作为背景层（不抠图）",
        flush=True,
    )
    print("[DONE] 第④步结束", flush=True)


if __name__ == "__main__":
    main()
