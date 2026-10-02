"""Pillow 确定性渲染：按模板 slot 把内容绘到 1080x1440 画布。

原则：
- 任何位置来自模板盒模型，任何尺寸来自测量，不做“估计坐标硬塞”。
- 文字永远最后绘制（最上层），保证不被素材遮挡。
- 超预算/超盒：先走压缩阶梯，仍超 -> errors（FAIL），绝不缩到最小字号以下。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from PIL import Image, ImageDraw, ImageColor

from . import assets
from .model import Spec, PageData, CANVAS_W, CANVAS_H
from .text_layout import FontResolver, layout_text, text_width


@dataclass
class RenderResult:
    image: Image.Image
    manifest: dict
    errors: list[str] = field(default_factory=list)
    font_report: dict = field(default_factory=dict)


def _rgb(theme: dict, token: str) -> tuple[int, int, int]:
    return ImageColor.getrgb(theme["color"][token])


class Engine:
    def __init__(self, spec: Spec, page: PageData):
        self.spec = spec
        self.tpl = spec.tpl
        self.theme = spec.theme
        self.page = page
        self.fonts = FontResolver(spec.fonts)
        self.canvas = Image.new("RGBA", (CANVAS_W, CANVAS_H), (255, 255, 255, 255))
        self.manifest: dict = {"slots": {}}
        self.errors: list[str] = []
        self._slots = {s["id"]: s for s in spec.slots}

    # ---------------- 基础文字绘制 -------------------------------------------
    def _draw_line(self, draw: ImageDraw.ImageDraw, x: float, y: float, text: str,
                   font, rgb, letter_spacing: float = 0.0) -> None:
        """逐字绘制（支持字距）。x/y 为 Pillow anchor='la' 原点：
        每个字符的 bearing/基线位置由 Pillow 内部 offset 处理，天然基线对齐。
        注意：不可对单字做 y-t 补偿——那会把整行字符的墨迹顶部拉到同一水平线，
        导致全角标点（top bearing 大）被抬到字框顶部。"""
        pen = x
        for ch in text:
            draw.text((pen, y), ch, font=font, fill=rgb)
            pen += float(font.getlength(ch)) + letter_spacing

    def _line_rect(self, x: float, y_pen: float, text: str, font,
                   letter_spacing: float) -> tuple[float, float, float, float]:
        l, t, r, b = font.getbbox(text or "")
        w = text_width(font, text, letter_spacing)
        return (x, y_pen + t, x + w, y_pen + b)

    # ---------------- 主入口 -------------------------------------------------
    def render(self) -> RenderResult:
        self.font_report = self.fonts.smoke_test(self.spec.fonts.get("glyphSmokeTest", []))

        self._render_background()
        # 先放素材（装饰在下，主体+阴影在上）
        for s in self.spec.slots:
            if s["type"] == "media" and s["media"]["assetRole"] == "decoration":
                self._render_media(s)
        for s in self.spec.slots:
            if s["type"] == "media" and s["media"]["assetRole"] == "subject":
                self._render_media(s)
        # 形状与文字（文字最上层）
        for s in self.spec.slots:
            if s["type"] == "shape":
                self._render_shape(s)
        for s in self.spec.slots:
            if s["type"] == "text":
                self._render_text(s)
            elif s["type"] == "step_row":
                self._render_step_row(s)
            elif s["type"] == "tag_row":
                self._render_tag_row(s)

        return RenderResult(image=self.canvas, manifest=self.manifest,
                            errors=self.errors, font_report=self.font_report)

    # ---------------- 背景 ---------------------------------------------------
    def _render_background(self) -> None:
        bg = self.tpl["background"]
        src = self.page.assets[bg["sourceKey"]]
        img = assets.load_rgba(src)
        cover = assets.fit_cover(img, (0, 0, CANVAS_W, CANVAS_H), bg.get("anchor", "center"))
        self.canvas.paste(cover, (0, 0), cover)
        if bg.get("wash"):
            assets.apply_wash(self.canvas, _rgb(self.theme, bg["wash"]["colorToken"]),
                              bg["wash"].get("alpha", 0))
        for sc in bg.get("scrim", []):
            assets.apply_linear_scrim(
                self.canvas, sc["direction"], _rgb(self.theme, sc["colorToken"]), sc["stops"]
            )

    # ---------------- 媒体槽 -------------------------------------------------
    def _render_media(self, slot: dict) -> None:
        md = slot["media"]
        bx, by, bw, bh = (slot["box"][k] for k in ("x", "y", "width", "height"))
        src = self.page.assets[md["sourceKey"]]
        img = assets.load_rgba(src)
        if md.get("trimTransparent", False):
            bbox = img.getbbox()
            if bbox:
                img = img.crop(bbox)
        img = assets.rotate_contain(img, md.get("rotation", 0))
        fitted, pos = assets.fit_contain(
            img, (bx, by, bw, bh), md.get("anchor", "center"),
            margin=md.get("margin", 0), max_scale=md.get("maxScale", 1.0),
        )

        layer = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
        layer.paste(fitted, pos, fitted)
        pixel_box = assets.alpha_bbox_on_canvas(layer)

        shadow = md.get("shadow") or {}
        if shadow.get("enabled") and pixel_box:
            x1, y1, x2, y2 = pixel_box
            assets.soft_ellipse_shadow(
                self.canvas,
                cx=(x1 + x2) / 2,
                cy=y2 + shadow.get("offsetY", 8),
                w=(x2 - x1) * shadow.get("widthRatio", 0.8),
                h=max(20, (y2 - y1) * shadow.get("heightRatio", 0.1)),
                rgb=_rgb(self.theme, shadow.get("colorToken", "ink")),
                alpha=shadow.get("alpha", 30),
                blur=shadow.get("blur", 20),
            )
        self.canvas.alpha_composite(layer)

        self.manifest["slots"][slot["id"]] = {
            "type": "media",
            "assetRole": md["assetRole"],
            "box": [bx, by, bw, bh],
            "placedSize": [fitted.size[0], fitted.size[1]],
            "placedPos": [pos[0], pos[1]],
            "pixelBox": list(pixel_box) if pixel_box else None,
            "keepOut": md.get("keepOut", []),
            "keepOutMargin": slot.get("keepOutMargin", 0),
        }

    # ---------------- 形状 ---------------------------------------------------
    def _render_shape(self, slot: dict) -> None:
        x, y, w, h = (slot["box"][k] for k in ("x", "y", "width", "height"))
        cfg = slot["shape"]
        layer = Image.new("RGBA", self.canvas.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        rgb = _rgb(self.theme, cfg.get("colorToken", "ink"))
        alpha = cfg.get("alpha", 255)
        r = cfg.get("cornerRadius", 0)
        outline = None
        if cfg.get("outlineToken"):
            outline = _rgb(self.theme, cfg["outlineToken"]) + (cfg.get("outlineAlpha", 255),)
        d.rounded_rectangle(
            (x, y, x + w, y + h), radius=r, fill=rgb + (alpha,),
            outline=outline, width=cfg.get("outlineWidth", 2) if outline else 0,
        )
        self.canvas.alpha_composite(layer)
        self.manifest["slots"][slot["id"]] = {
            "type": "shape", "box": [x, y, w, h],
            "solidRects": [[x, y, x + w, y + h]], "textRects": [],
        }

    # ---------------- 文字槽 -------------------------------------------------
    def _typography(self, slot: dict):
        typo = self.spec.role_typo(slot["role"])
        size = typo["size"]
        weight = typo["weight"]
        lh = slot.get("style", {}).get("lineHeight", typo["lineHeight"])
        return typo, size, weight, lh

    def _render_text(self, slot: dict) -> None:
        sid = slot["id"]
        content = self.page.content.get(slot["contentKey"], "")
        if slot.get("required") and not str(content).strip():
            self.errors.append(f"[{sid}] 必填内容为空 (contentKey={slot['contentKey']})")
            content = content or ""

        bx, by, bw, bh = (slot["box"][k] for k in ("x", "y", "width", "height"))
        style = slot.get("style", {})
        typo, size, weight, lh = self._typography(slot)
        ls = style.get("letterSpacing", 0.0)
        font = self.fonts.font(weight, size)

        # 1) 字符预算（粗校验）
        char_count = len(str(content).replace("\n", "").replace(" ", ""))
        if char_count > slot["maxChars"]:
            self.errors.append(
                f"[{sid}] 字符超预算: {char_count} > maxChars={slot['maxChars']}，请上游精简文案"
            )

        # 2) 压缩阶梯：行距下调到下限（绝不动字号）
        pol = slot.get("overflow", {})
        block = layout_text(str(content), font, bw, size, lh, slot["maxLines"],
                            letter_spacing=ls, kinsoku=slot.get("kinsoku", True))
        if (block.overflow or block.height > bh) and pol.get("strategy") == "compress_then_fail":
            lh2 = max(lh, pol.get("minLineHeight", lh))
            if lh2 < lh:
                lh = lh2
                block = layout_text(str(content), font, bw, size, lh, slot["maxLines"],
                                    letter_spacing=ls, kinsoku=slot.get("kinsoku", True))

        if block.overflow:
            self.errors.append(f"[{sid}] 行数溢出: {block.overflow_reason}")
        if size < typo["minSize"]:
            self.errors.append(f"[{sid}] 字号 {size} 低于最小地板 {typo['minSize']}")

        # 3) 纵向对齐
        va = style.get("verticalAlign", "top")
        if va == "middle":
            top = by + (bh - block.height) / 2
        elif va == "bottom":
            top = by + bh - block.height
        else:
            top = by

        line_colors = style.get("lineColors") or []
        text_rects: list[list[float]] = []
        line_geoms: list[tuple[float, float, str]] = []  # (lx, pen_y, line)

        align = style.get("align", "left")
        for i, line in enumerate(block.lines):
            lw = block.widths[i]
            if align == "center":
                lx = bx + (bw - lw) / 2
            elif align == "right":
                lx = bx + bw - lw
            else:
                lx = bx
            pen_y = top + i * block.pitch
            line_geoms.append((lx, pen_y, line))
            text_rects.append([round(v, 1) for v in
                               self._line_rect(lx, pen_y, line, font, ls)])

        # 4) 底色块（胶囊）：尺寸贴合文字
        bg_token = style.get("backgroundToken")
        pad_x = self.theme["space"]["chipPadX"]
        pad_y = self.theme["space"]["chipPadY"]
        solid_rects: list[list[float]] = []
        if bg_token and block.lines:
            max_w = max(block.widths)
            bg_w = max_w + 2 * pad_x
            bg_h = size + 2 * pad_y
            bg_x = bx + (bw - bg_w) / 2
            bg_y = top + (block.height - size) / 2 - pad_y
            layer = Image.new("RGBA", self.canvas.size, (0, 0, 0, 0))
            ImageDraw.Draw(layer).rounded_rectangle(
                (bg_x, bg_y, bg_x + bg_w, bg_y + bg_h),
                radius=style.get("cornerRadius", self.theme["radius"]["chip"]),
                fill=_rgb(self.theme, bg_token) + (style.get("backgroundAlpha", 255),),
            )
            self.canvas.alpha_composite(layer)
            solid_rects.append([bg_x, bg_y, bg_x + bg_w, bg_y + bg_h])

        # 5) 马克笔层（必须在文字之下）
        marker = style.get("marker")
        if marker:
            marker_layer = Image.new("RGBA", self.canvas.size, (0, 0, 0, 0))
            md = ImageDraw.Draw(marker_layer)
            m_rgb = _rgb(self.theme, marker["colorToken"])
            for i, (lx, pen_y, line) in enumerate(line_geoms):
                if marker.get("lineIndex") != i:
                    continue
                _, t0, _, b0 = font.getbbox(line)
                lw = block.widths[i]
                md.rounded_rectangle(
                    (lx - marker["padX"], pen_y + t0 - marker["padY"],
                     lx + lw + marker["padX"], pen_y + b0 + marker["padY"]),
                    radius=marker.get("radius", 12),
                    fill=m_rgb + (marker.get("alpha", 200),),
                )
            if marker.get("rotate"):
                marker_layer = marker_layer.rotate(
                    marker["rotate"], resample=Image.BICUBIC,
                    center=(CANVAS_W / 2, CANVAS_H / 2),
                )
            self.canvas.alpha_composite(marker_layer)

        # 6) 文字（最后绘制，永远在最上层）
        draw = ImageDraw.Draw(self.canvas)
        for i, (lx, pen_y, line) in enumerate(line_geoms):
            color_token = line_colors[i] if i < len(line_colors) else style.get("colorToken", "ink")
            self._draw_line(draw, lx, pen_y, line, font, _rgb(self.theme, color_token), ls)

        self.manifest["slots"][sid] = {
            "type": "text", "role": slot["role"], "box": [bx, by, bw, bh],
            "fontSize": size, "weight": weight, "lineHeight": round(lh, 3),
            "charCount": char_count, "maxChars": slot["maxChars"],
            "maxLines": slot["maxLines"], "lineCount": len(block.lines),
            "lines": block.lines, "textRects": text_rects, "solidRects": solid_rects,
        }

    # ---------------- 步骤组 -------------------------------------------------
    def _render_step_row(self, slot: dict) -> None:
        sid = slot["id"]
        cfg = slot["stepRow"]
        items = self.page.content.get(slot["contentKey"], [])
        bx, by, bw, bh = (slot["box"][k] for k in ("x", "y", "width", "height"))

        if not (cfg.get("minItems", 0) <= len(items) <= cfg.get("maxItems", 99)):
            self.errors.append(f"[{sid}] 步骤数量 {len(items)} 不在允许范围")

        n = cfg["columns"]
        col_w = bw / n
        centers = [bx + col_w * (i + 0.5) for i in range(n)]
        cy = by + 56
        r = cfg["circle"]["radius"]

        text_rects: list[list[float]] = []
        solid_rects: list[list[float]] = []

        layer = Image.new("RGBA", self.canvas.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        # 连接线
        conn = cfg.get("connector")
        if conn and n >= 2:
            d.rounded_rectangle(
                (centers[0] + r + 8, cy - conn["width"] / 2,
                 centers[-1] - r - 8, cy + conn["width"] / 2),
                radius=conn["width"] / 2,
                fill=_rgb(self.theme, conn["colorToken"]) + (255,),
            )
        # 圆圈
        stroke_rgb = _rgb(self.theme, cfg["circle"]["strokeToken"])
        fill_rgb = _rgb(self.theme, cfg["circle"].get("fillToken", "paper0"))
        for cx in centers:
            d.ellipse((cx - r, cy - r, cx + r, cy + r),
                      fill=fill_rgb + (cfg.get("circleFillAlpha", 235),))
            d.ellipse((cx - r, cy - r, cx + r, cy + r),
                      outline=stroke_rgb + (255,), width=cfg["circle"]["strokeWidth"])
        self.canvas.alpha_composite(layer)
        for cx in centers:
            solid_rects.append([cx - r, cy - r, cx + r, cy + r])

        draw = ImageDraw.Draw(self.canvas)
        f_num = self.fonts.font(self.spec.role_typo(cfg["numberRole"])["weight"],
                                self.spec.role_typo(cfg["numberRole"])["size"])
        f_lab = self.fonts.font(self.spec.role_typo(cfg["labelRole"])["weight"],
                                self.spec.role_typo(cfg["labelRole"])["size"])
        en_typo = self.spec.role_typo(cfg["enRole"])
        f_en = self.fonts.font(en_typo["weight"], en_typo["size"])

        label_top = cy + r + 30
        en_top = label_top + self.spec.role_typo(cfg["labelRole"])["size"] + 16

        for i in range(n):
            cx = centers[i]
            item = items[i] if i < len(items) else {"label": "", "en": ""}
            label = str(item.get("label", ""))
            en = str(item.get("en", ""))
            if len(label) > cfg.get("labelMaxChars", 99):
                self.errors.append(f"[{sid}] 第{i+1} 项标签超 labelMaxChars")

            num = f"{i + 1:02d}"
            nl, nt, nr, nb = f_num.getbbox(num)
            # 按墨迹包围盒精确居中
            draw.text((cx - (nl + nr) / 2, cy - (nt + nb) / 2), num,
                      font=f_num, fill=stroke_rgb)

            # 中文词
            lw = text_width(f_lab, label)
            lab_x = cx - lw / 2
            l, t, r2, b = f_lab.getbbox(label)
            draw.text((lab_x, label_top), label, font=f_lab,
                      fill=_rgb(self.theme, "ink"))
            text_rects.append([lab_x, label_top + t, lab_x + lw, label_top + b])

            # 英文小标
            ew = text_width(f_en, en, cfg.get("enLetterSpacing", 0))
            en_x = cx - ew / 2
            el, et, er, eb = f_en.getbbox(en)
            pen_x = en_x
            for ch in en:
                draw.text((pen_x, en_top), ch, font=f_en,
                          fill=_rgb(self.theme, "faint"))
                pen_x += float(f_en.getlength(ch)) + cfg.get("enLetterSpacing", 0)
            text_rects.append([en_x, en_top + et, en_x + ew, en_top + eb])

        if label_top < by or en_top + en_typo["size"] > by + bh:
            self.errors.append(f"[{sid}] 步骤内容超出盒模型 {by}..{by + bh}")

        self.manifest["slots"][sid] = {
            "type": "step_row", "box": [bx, by, bw, bh],
            "textRects": [[round(v, 1) for v in r] for r in text_rects],
            "solidRects": [[round(v, 1) for v in r] for r in solid_rects],
            "fontSize": self.spec.role_typo(cfg["labelRole"])["size"],
        }

    # ---------------- 标签行 -------------------------------------------------
    def _render_tag_row(self, slot: dict) -> None:
        sid = slot["id"]
        tags = self.page.content.get(slot["contentKey"], [])
        cfg = slot.get("tagRow", {})
        typo = self.spec.role_typo(cfg.get("role", "caption"))
        bx, by, bw, bh = (slot["box"][k] for k in ("x", "y", "width", "height"))
        font = self.fonts.font(typo["weight"], typo["size"])
        rgb = _rgb(self.theme, cfg.get("colorToken", "sub"))

        joined = " ".join(tags)
        if len(joined.replace(" ", "")) > slot.get("maxChars", 99):
            self.errors.append(f"[{sid}] 标签超 maxChars 预算")

        d = ImageDraw.Draw(self.canvas)
        pill = cfg.get("pill") or {}
        if pill.get("enabled"):
            pill_layer = Image.new("RGBA", self.canvas.size, (0, 0, 0, 0))
            pd = ImageDraw.Draw(pill_layer)
            p_rgb = _rgb(self.theme, pill.get("backgroundToken", "brand_soft"))
            p_alpha = pill.get("backgroundAlpha", 235)
            p_radius = pill.get("cornerRadius", self.theme["radius"]["chip"])
            pad_x = pill.get("padX", self.theme["space"]["chipPadX"] - 6)
            pad_y = pill.get("padY", self.theme["space"]["chipPadY"] - 4)
        x = float(bx)
        y = by + (bh - typo["size"]) / 2
        text_rects = []
        solid_rects = []
        tag_geoms = []
        for i, tag in enumerate(tags):
            l, t, r, b = font.getbbox(tag)
            w = text_width(font, tag)
            tag_geoms.append((x, y, tag, l, t, w))
            if pill.get("enabled"):
                rect = [x - pad_x, y - pad_y, x + w + pad_x, y + typo["size"] + pad_y]
                pd.rounded_rectangle(rect, radius=p_radius, fill=p_rgb + (p_alpha,))
                solid_rects.append(rect)
            x += w + (2 * pad_x if pill.get("enabled") else 0) + cfg.get("gap", 24)
        if pill.get("enabled"):
            self.canvas.alpha_composite(pill_layer)
        for x, y, tag, l, t, w in tag_geoms:
            d.text((x, y), tag, font=font, fill=rgb)
            text_rects.append([x, y + t, x + w, y + (t or 0) + typo["size"]])
        if x - cfg.get("gap", 24) > bx + bw:
            self.errors.append(f"[{sid}] 标签行超宽")

        self.manifest["slots"][sid] = {
            "type": "tag_row", "box": [bx, by, bw, bh],
            "fontSize": typo["size"],
            "textRects": [[round(v, 1) for v in r] for r in text_rects],
            "solidRects": [[round(v, 1) for v in r] for r in solid_rects],
        }
