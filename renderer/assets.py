"""AI 素材的确定性装入：cover/contain、锚点、旋转、alpha 包围盒、背景 wash/scrim、软阴影。

契约（cover/contain 不可混用）：
- cover: 等比填满盒，超出部分按 anchor 裁切，不留白。
- contain: 等比完整显示，不裁切，留白由背景承接。
"""
from __future__ import annotations

from PIL import Image, ImageDraw, ImageFilter

CANVAS_W = 1080
CANVAS_H = 1440


def load_rgba(path: str) -> Image.Image:
    return Image.open(path).convert("RGBA")


def _anchor_pos(obj_w: int, obj_h: int, box: tuple[int, int, int, int], anchor: str,
                extra_x: int = 0, extra_y: int = 0) -> tuple[int, int]:
    x, y, w, h = box
    if "left" in anchor:
        px = x
    elif "right" in anchor:
        px = x + w - obj_w
    else:
        px = x + (w - obj_w) // 2
    if "top" in anchor:
        py = y
    elif "bottom" in anchor:
        py = y + h - obj_h
    else:
        py = y + (h - obj_h) // 2
    return px + extra_x, py + extra_y


def fit_cover(img: Image.Image, box: tuple[int, int, int, int], anchor: str = "center") -> Image.Image:
    x, y, w, h = box
    sw, sh = img.size
    scale = max(w / sw, h / sh)
    nw, nh = max(1, round(sw * scale)), max(1, round(sh * scale))
    resized = img.resize((nw, nh), Image.LANCZOS)
    px, py = _anchor_pos(nw, nh, (0, 0, w, h), anchor)
    # 裁出盒大小
    left = max(0, -px)
    top = max(0, -py)
    return resized.crop((left, top, left + w, top + h))


def fit_contain(img: Image.Image, box: tuple[int, int, int, int], anchor: str = "center",
                margin: int = 0, max_scale: float = 1.0) -> tuple[Image.Image, tuple[int, int]]:
    x, y, w, h = box
    sw, sh = img.size
    avail_w, avail_h = w - 2 * margin, h - 2 * margin
    scale = min(avail_w / sw, avail_h / sh, max_scale)
    nw, nh = max(1, round(sw * scale)), max(1, round(sh * scale))
    resized = img.resize((nw, nh), Image.LANCZOS)
    px, py = _anchor_pos(nw, nh, (x + margin, y + margin, avail_w, avail_h), anchor)
    return resized, (px, py)


def rotate_contain(img: Image.Image, rotation: float) -> Image.Image:
    if not rotation:
        return img
    return img.rotate(rotation, resample=Image.BICUBIC, expand=True, fillcolor=(0, 0, 0, 0))


def alpha_bbox_on_canvas(layer: Image.Image, threshold: int = 24):
    """对贴到 1080x1440 透明层上的素材求阈值 alpha 包围盒；无内容返回 None。"""
    if layer.size != (CANVAS_W, CANVAS_H):
        raise ValueError("alpha_bbox 需要全画布层")
    a = layer.getchannel("A")
    a = a.point(lambda v: 255 if v >= threshold else 0)
    return a.getbbox()


def paste_asset(canvas: Image.Image, asset: Image.Image, pos: tuple[int, int]) -> None:
    # 小图贴到大画布：用自身 alpha 作 mask
    canvas.paste(asset, pos, asset)


# ----------------------------- 背景处理 -------------------------------------

def apply_wash(canvas: Image.Image, rgb: tuple[int, int, int], alpha: int) -> None:
    if alpha <= 0:
        return
    layer = Image.new("RGBA", canvas.size, rgb + (alpha,))
    canvas.alpha_composite(layer)


def apply_linear_scrim(canvas: Image.Image, direction: str, rgb: tuple[int, int, int],
                       stops: list[dict]) -> None:
    """线性渐变压色层。stops: [{y:0..1, alpha:0..255}]，沿 direction 插值。"""
    w, h = canvas.size
    vertical = direction in ("top", "bottom")
    n = h if vertical else w
    grad = Image.new("L", (1, n))
    for i in range(n):
        t = i / max(1, n - 1)
        if direction in ("bottom", "right"):
            t = 1 - t
        # 线性插值；区间外取端值
        if t <= stops[0]["y"]:
            a = stops[0]["alpha"]
        elif t >= stops[-1]["y"]:
            a = stops[-1]["alpha"]
        else:
            for s1, s2 in zip(stops, stops[1:]):
                if s1["y"] <= t <= s2["y"]:
                    k = (t - s1["y"]) / max(1e-6, s2["y"] - s1["y"])
                    a = round(s1["alpha"] + (s2["alpha"] - s1["alpha"]) * k)
                    break
        grad.putpixel((0, i), a)
    mask = grad.resize((w, h)) if vertical else grad.rotate(90, expand=True).resize((w, h))
    layer = Image.new("RGBA", (w, h), rgb + (255,))
    canvas.paste(layer, (0, 0), mask)


def soft_ellipse_shadow(canvas: Image.Image, cx: float, cy: float, w: float, h: float,
                        rgb: tuple[int, int, int], alpha: int, blur: float) -> None:
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.ellipse((cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2), fill=rgb + (alpha,))
    layer = layer.filter(ImageFilter.GaussianBlur(blur))
    canvas.alpha_composite(layer)
