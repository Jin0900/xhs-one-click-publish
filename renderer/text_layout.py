"""字体注册/fallback、中英文混排测量、CJK 贪心换行 + 避头尾。

经验要点：
- Pillow 绘制坐标需用 bbox 的 left/top 做 bearing 补偿，否则高亮块/居中会偏移。
- 字距(letterSpacing)通过逐字绘制实现，advance 用 font.getlength。
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

# 避头尾：不可出现在行首 / 行尾的标点
_NO_LINE_START = set("，。、！？：；）】」』》%·.!,;:?)")
_NO_LINE_END = set("（【「『《(")


class FontError(Exception):
    pass


class FontResolver:
    """按 fonts.json 的 chain 顺序加载字体，首个可用即生效；支持 TTC index。"""

    def __init__(self, fonts_cfg: dict):
        self.cfg = fonts_cfg
        self._cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}
        self.loaded: dict[str, dict] = {}   # role -> 实际命中的字体描述
        self.missing_chars: list[str] = []
        self.available = True

    @lru_cache(maxsize=512)
    def _load(self, path: str, index: int, size: int):  # noqa: D401
        return ImageFont.truetype(path, size=size, index=index)

    def font(self, weight: str, size: int) -> ImageFont.FreeTypeFont:
        role = "bold" if weight == "bold" else weight if weight in ("regular", "light") else "regular"
        chain = None
        for fam in self.cfg.get("families", []):
            if fam["role"] == role:
                chain = fam["chain"]
                break
        if chain is None:
            chain = next(f["chain"] for f in self.cfg["families"] if f["role"] == "regular")

        key = (role, size)
        if key in self._cache:
            return self._cache[key]

        last_err = None
        for item in chain:
            p = item["path"]
            if not Path(p).exists():
                last_err = f"字体文件不存在: {p}"
                continue
            try:
                f = self._load(p, item.get("index", 0), size)
                self._cache[key] = f
                self.loaded.setdefault(role, item)
                return f
            except OSError as e:  # 文件损坏/不支持
                last_err = str(e)
                continue
        raise FontError(f"角色 {role} 字号 {size} 无可用字体: {last_err}")

    def smoke_test(self, chars: list[str]) -> dict:
        """抽样验证关键汉字在实际字体里有字形（非 .notdef）。"""
        report = {"ok": True, "missing": [], "fonts": {}}
        try:
            fb = self.font("bold", 48)
            fr = self.font("regular", 48)
        except FontError:
            self.available = False
            report["ok"] = False
            return report
        report["fonts"] = {
            "bold": self.loaded.get("bold", {}).get("label"),
            "regular": self.loaded.get("regular", {}).get("label"),
        }
        for ch in chars:
            if fb.getmask(ch).getbbox() is None or fr.getmask(ch).getbbox() is None:
                report["missing"].append(ch)
        if report["missing"]:
            report["ok"] = False
            self.available = False
            self.missing_chars = report["missing"]
        return report


# ----------------------------- 测量 ----------------------------------------

def text_width(font, text: str, letter_spacing: float = 0.0) -> float:
    if not text:
        return 0.0
    w = sum(float(font.getlength(ch)) for ch in text)
    return w + max(0, len(text) - 1) * letter_spacing


def ink_box(font, text: str, letter_spacing: float = 0.0):
    """返回整行墨迹包围盒 (width, height, x0, y0)，含 bearing。"""
    if not text:
        return 0.0, 0.0, 0, 0
    l, t, r, b = font.getbbox(text)
    return float(r - l) + max(0, len(text) - 1) * letter_spacing, b - t, l, t


# ----------------------------- 换行 ----------------------------------------

def _is_cjk(ch: str) -> bool:
    if "一" <= ch <= "鿿" or "　" <= ch <= "〿" or "＀" <= ch <= "￯":
        return True
    cat = unicodedata.category(ch)
    return cat.startswith("P") and unicodedata.east_asian_width(ch) in ("W", "F")


def _atoms(text: str) -> list[str]:
    """CJK 逐字成原子；连续拉丁/数字成词；空格作为可在行首丢弃的原子。"""
    atoms: list[str] = []
    buf = ""
    for ch in text:
        if ch == " ":
            if buf:
                atoms.append(buf)
                buf = ""
            atoms.append(" ")
        elif _is_cjk(ch):
            if buf:
                atoms.append(buf)
                buf = ""
            atoms.append(ch)
        else:
            buf += ch
    if buf:
        atoms.append(buf)
    return atoms


def _apply_kinsoku(lines: list[str]) -> list[str]:
    if len(lines) < 2:
        return lines
    fixed = [lines[0]]
    for nxt in lines[1:]:
        prev = fixed[-1]
        if prev and prev[-1] in _NO_LINE_END and len(prev) > 1:
            fixed[-1] = prev[:-1]
            nxt = prev[-1] + nxt
        if nxt and nxt[0] in _NO_LINE_START and prev:
            fixed[-1] = prev + nxt[0]
            nxt = nxt[1:]
        fixed.append(nxt)
    return [ln for ln in fixed if ln != ""]


@dataclass
class TextBlock:
    lines: list[str]
    widths: list[float]
    pitch: float
    line_height: float
    letter_spacing: float
    font_size: int
    overflow: bool = False
    overflow_reason: str = ""
    char_count: int = field(default=0)

    @property
    def height(self) -> float:
        return len(self.lines) * self.pitch


def layout_text(
    text: str,
    font,
    box_width: float,
    font_size: int,
    line_height: float,
    max_lines: int,
    letter_spacing: float = 0.0,
    kinsoku: bool = True,
) -> TextBlock:
    """按盒宽自动换行；超过 max_lines 标记 overflow（不截断、不缩字）。"""
    text = (text or "").strip("\n")
    char_count = len(text.replace("\n", "").replace(" ", ""))
    pitch = round(font_size * line_height, 2)

    raw_lines = text.split("\n")
    out_lines: list[str] = []
    for raw in raw_lines:
        cur = ""
        cur_w = 0.0
        for atom in _atoms(raw):
            if atom == " " and not cur:
                continue
            add = float(font.getlength(atom))
            add += letter_spacing if cur else 0.0
            if cur and cur_w + add > box_width:
                out_lines.append(cur)
                if atom == " ":
                    cur, cur_w = "", 0.0
                    continue
                cur, cur_w = atom, text_width(font, atom, letter_spacing)
            else:
                cur += atom
                cur_w += add
        out_lines.append(cur)

    if kinsoku:
        out_lines = _apply_kinsoku(out_lines)
        # 避头尾回推后可能再次超宽（罕见），保险再压一次
        final_lines: list[str] = []
        for ln in out_lines:
            if text_width(font, ln, letter_spacing) <= box_width or len(ln) <= 1:
                final_lines.append(ln)
            else:
                # 极端情况：硬切
                cur = ""
                for ch in ln:
                    if text_width(font, cur + ch, letter_spacing) > box_width and cur:
                        final_lines.append(cur)
                        cur = ch
                    else:
                        cur += ch
                final_lines.append(cur)
        out_lines = final_lines

    widths = [text_width(font, ln, letter_spacing) for ln in out_lines]
    overflow = len(out_lines) > max_lines
    reason = f"需要 {len(out_lines)} 行，超过 maxLines={max_lines}" if overflow else ""
    return TextBlock(
        lines=out_lines, widths=widths, pitch=pitch, line_height=line_height,
        letter_spacing=letter_spacing, font_size=font_size,
        overflow=overflow, overflow_reason=reason, char_count=char_count,
    )
