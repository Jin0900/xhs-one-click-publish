# -*- coding: utf-8 -*-
"""run-002 第⑥–⑨步：Pillow 排版合成。
cover：AI 背景(element_img2) + 抠图瓶身 + 抠图绿叶点缀 + 中文标题
page1/2/3：AI 浅色背景 + 标题/要点卡片 + 小主体装饰
输出 1024x1536：cover.png page1.png page2.png page3.png
"""
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE / "libs"))
from PIL import Image, ImageDraw, ImageFilter, ImageFont  # noqa: E402

W, H = 1024, 1536
FONT_BOLD = r"C:\Windows\Fonts\msyhbd.ttc"
FONT_REG = r"C:\Windows\Fonts\msyh.ttc"
INK = (34, 58, 52)
GREEN = (74, 140, 96)
SUB = (96, 112, 106)


def font(size, bold=True):
    return ImageFont.truetype(FONT_BOLD if bold else FONT_REG, size)


def cover_crop(src: Path) -> Image.Image:
    """等比缩放填满 1024x1536 后居中裁剪。"""
    img = Image.open(src).convert("RGBA")
    scale = max(W / img.width, H / img.height)
    img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    x = (img.width - W) // 2
    y = (img.height - H) // 2
    return img.crop((x, y, x + W, y + H))


def fit_height(img: Image.Image, h: int) -> Image.Image:
    return img.resize((round(img.width * h / img.height), h), Image.LANCZOS)


def text_size(draw, text, fnt):
    box = draw.textbbox((0, 0), text, font=fnt)
    return box[2] - box[0], box[3] - box[1], box[0], box[1]


def paste_center_x(base, overlay, cy, cx=W // 2):
    base.alpha_composite(overlay, (cx - overlay.width // 2, cy))


def paste_with_shadow(base, overlay, xy, shadow_alpha=0.32, blur=18, offset=(14, 24)):
    """先贴主体柔影，再贴主体。"""
    alpha = overlay.split()[3]
    shadow_layer = Image.new("RGBA", overlay.size, (40, 60, 50, 0))
    shadow_alpha_img = alpha.point(lambda v: int(v * shadow_alpha))
    shadow_layer.putalpha(shadow_alpha_img.filter(ImageFilter.GaussianBlur(blur)))
    base.alpha_composite(shadow_layer, (xy[0] + offset[0], xy[1] + offset[1]))
    base.alpha_composite(overlay, xy)


def rounded_card(draw, box, radius, fill):
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def pill(base, text, fnt, cy, cx, fill, txt_color, pad_x=34, h=64, radius=32):
    draw = ImageDraw.Draw(base)
    tw, th, ox, oy = text_size(draw, text, fnt)
    box = (cx - tw // 2 - pad_x, cy - h // 2, cx + tw // 2 + pad_x, cy + h // 2)
    draw.rounded_rectangle(box, radius=radius, fill=fill)
    draw.text((cx - tw // 2 - ox, cy - th // 2 - oy), text, font=fnt, fill=txt_color)


def multiline_center(draw, lines, fnt, top, cx, fill, gap=20):
    y = top
    for line in lines:
        tw, th, ox, oy = text_size(draw, line, fnt)
        draw.text((cx - tw // 2 - ox, y - oy), line, font=fnt, fill=fill)
        y += th + gap


def build_cover(bottle: Image.Image, leaf: Image.Image) -> Image.Image:
    base = cover_crop(BASE / "element_img2.png")
    draw = ImageDraw.Draw(base)

    # 顶部信息卡
    rounded_card(draw, (60, 84, W - 60, 472), 40, (255, 255, 255, 208))

    f_title = font(96)
    title = "夏季护肤做减法"
    tw, th, ox, oy = text_size(draw, title, f_title)
    draw.text(((W - tw) // 2 - ox, 132 - oy), title, font=f_title, fill=INK)
    # 绿色分隔短线
    draw.rounded_rectangle((W // 2 - 46, 272, W // 2 + 46, 281), radius=5, fill=GREEN)
    f_sub = font(46)
    sub = "三步就够了"
    tw, th, ox, oy = text_size(draw, sub, f_sub)
    draw.text(((W - tw) // 2 - ox, 308 - oy), sub, font=f_sub, fill=SUB)
    pill(base, "清洁 · 保湿 · 防晒", font(32), 416, W // 2, (232, 243, 236, 255), GREEN,
         pad_x=30, h=60, radius=30)

    # 主体瓶身（带柔影）
    bottle_f = fit_height(bottle, 690)
    bx = W // 2 - bottle_f.width // 2
    by = 640
    paste_with_shadow(base, bottle_f, (bx, by), shadow_alpha=0.30, blur=20, offset=(16, 26))

    # 左下角绿叶半出血点缀
    leaf_f = fit_height(leaf, 330)
    base.alpha_composite(leaf_f, (-50, 1180))

    # 底部辅助说明
    pill(base, "精简步骤 · 清爽度夏", font(30), 1486, W // 2, (255, 255, 255, 220), SUB,
         pad_x=28, h=56, radius=28)
    return base


def build_page(bg_name: Path, step: str, title: str, lines: list, footer: str | None,
               bottle: Image.Image, leaf: Image.Image) -> Image.Image:
    base = cover_crop(bg_name)
    draw = ImageDraw.Draw(base)

    # STEP 胶囊
    pill(base, step, font(30), 126, 150, (255, 255, 255, 225), GREEN,
         pad_x=30, h=60, radius=30)

    # 大标题
    f_title = font(92)
    tw, th, ox, oy = text_size(draw, title, f_title)
    draw.text((80 - ox, 206 - oy), title, font=f_title, fill=INK)
    draw.rounded_rectangle((80, 340, 80 + 130, 350), radius=5, fill=GREEN)

    # 正文卡
    card_top, card_bottom = 470, 930
    rounded_card(draw, (60, card_top, W - 60, card_bottom), 40, (255, 255, 255, 214))
    f_body = font(44, bold=False)
    multiline_center(draw, lines, f_body, card_top + 78, W // 2, INK, gap=34)

    # 装饰：page1/2 右下小瓶，page3 右下绿叶
    if footer:
        leaf_f = fit_height(leaf, 260)
        base.alpha_composite(leaf_f, (W - leaf_f.width + 40, 1140))
        pill(base, footer, font(34), 1360, W // 2, (74, 140, 96, 235), (255, 255, 255),
             pad_x=40, h=80, radius=40)
    else:
        bottle_f = fit_height(bottle, 360)
        bx = W - bottle_f.width - 36
        by = 1060
        paste_with_shadow(base, bottle_f, (bx, by), shadow_alpha=0.22, blur=14,
                          offset=(10, 16))
    return base


def main() -> None:
    bottle = Image.open(BASE / "main_image_cutout.png").convert("RGBA")
    leaf = Image.open(BASE / "element_img1_cutout.png").convert("RGBA")

    pages = [
        ("cover.png", lambda: build_cover(bottle, leaf)),
        ("page1.png", lambda: build_page(
            BASE / "bg_page1.png", "STEP 1", "温和清洁",
            ["夏天出油出汗多", "选温和洁面，早晚各一次", "注意不要过度清洁"], None,
            bottle, leaf)),
        ("page2.png", lambda: build_page(
            BASE / "bg_page2.png", "STEP 2", "清爽保湿",
            ["换掉厚重的面霜", "用清爽乳液或啫喱", "薄薄一层就够了"], None,
            bottle, leaf)),
        ("page3.png", lambda: build_page(
            BASE / "bg_page3.png", "STEP 3", "出门防晒",
            ["白天出门前，先涂好防晒", "这是夏季护肤最重要的一步"],
            "清洁 → 保湿 → 防晒，清爽过夏天", bottle, leaf)),
    ]
    for name, builder in pages:
        img = builder()
        path = BASE / name
        img.convert("RGB").save(path, quality=94)
        print(f"[OK] {name} | {path.stat().st_size} bytes | {img.size}", flush=True)
    print("[DONE] 第⑥–⑨步结束", flush=True)


if __name__ == "__main__":
    main()
