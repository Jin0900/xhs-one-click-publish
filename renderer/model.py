"""模板与内容数据加载、结构校验（不依赖 jsonschema 库，手写必需规则）。"""
from __future__ import annotations

import json
from pathlib import Path

CANVAS_W = 1080
CANVAS_H = 1440


class ModelError(Exception):
    def __init__(self, errors):
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))


def load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8-sig") as f:  # utf-8-sig 兼容带 BOM 的文件
        return json.load(f)


_TOKEN_STYLE_KEYS = (
    "colorToken", "backgroundToken", "marker.colorToken", "shape.colorToken",
)


def _collect_color_tokens(tpl: dict) -> list[str]:
    tokens: list[str] = []
    bg = tpl.get("background", {})
    if "wash" in bg:
        tokens.append(bg["wash"].get("colorToken"))
    for s in bg.get("scrim", []):
        tokens.append(s.get("colorToken"))
    for slot in tpl.get("slots", []):
        st = slot.get("style", {})
        tokens.append(st.get("colorToken"))
        tokens.append(st.get("backgroundToken"))
        tokens.extend(st.get("lineColors", []))
        if "marker" in st:
            tokens.append(st["marker"].get("colorToken"))
        if "shape" in slot:
            tokens.append(slot["shape"].get("colorToken"))
        sr = slot.get("stepRow", {})
        if sr:
            c = sr.get("circle", {})
            tokens.append(c.get("strokeToken"))
            tokens.append(c.get("fillToken"))
            tokens.append(sr.get("connector", {}).get("colorToken"))
        tr = slot.get("tagRow", {})
        if tr:
            tokens.append(tr.get("colorToken"))
        md = slot.get("media", {})
        if md.get("shadow"):
            tokens.append(md["shadow"].get("colorToken"))
    return [t for t in tokens if t]


class Spec:
    def __init__(self, template_path: str | Path):
        self.path = Path(template_path)
        self.dir = self.path.parent
        self.tpl = load_json(self.path)
        self.theme = load_json(self.dir / self.tpl["theme"])
        self.fonts = load_json(self.dir / self.tpl["fonts"])
        self._validate()

    @property
    def canvas(self):
        return self.tpl["canvas"]

    @property
    def slots(self):
        return self.tpl["slots"]

    def role_typo(self, role: str) -> dict:
        return self.theme["typeScale"][role]

    # ---- structural validation -------------------------------------------------
    def _validate(self):
        errors: list[str] = []
        tpl = self.tpl
        cv = tpl.get("canvas", {})
        if cv.get("width") != CANVAS_W or cv.get("height") != CANVAS_H:
            errors.append(f"画布必须为 {CANVAS_W}x{CANVAS_H}，当前 {cv.get('width')}x{cv.get('height')}")
        m = cv.get("safeMargin", 0)

        ids = [s.get("id") for s in tpl.get("slots", [])]
        if len(ids) != len(set(ids)):
            errors.append("slot id 存在重复")
        idset = set(ids)

        known_tokens = set(self.theme.get("color", {}).keys())
        for tok in _collect_color_tokens(tpl):
            if tok not in known_tokens:
                errors.append(f"颜色令牌未在 theme 中定义: {tok}")

        for s in tpl.get("slots", []):
            sid = s.get("id", "<?id>")
            box = s.get("box", {})
            try:
                x, y, w, h = box["x"], box["y"], box["width"], box["height"]
            except KeyError:
                errors.append(f"slot {sid} 缺少 box 字段")
                continue
            if w <= 0 or h <= 0:
                errors.append(f"slot {sid} box 宽高必须为正数")
            if x < m or y < m or x + w > CANVAS_W - m or y + h > CANVAS_H - m:
                errors.append(
                    f"slot {sid} 超出安全区(margin={m}): box=({x},{y},{w},{h}) "
                    f"允许范围 x[{m},{CANVAS_W - m}] y[{m},{CANVAS_H - m}]"
                )
            if "role" in s and s["role"] not in self.theme.get("typeScale", {}):
                errors.append(f"slot {sid} role 未在 typeScale 定义: {s['role']}")
            md = s.get("media")
            if md:
                for ref in md.get("keepOut", []):
                    if ref not in idset:
                        errors.append(f"slot {sid}.keepOut 引用了不存在的 slot: {ref}")
            sr = s.get("stepRow")
            if sr:
                for rk in ("numberRole", "labelRole", "enRole"):
                    if sr.get(rk) not in self.theme.get("typeScale", {}):
                        errors.append(f"slot {sid} stepRow.{rk} 未定义: {sr.get(rk)}")

        font_roles = {f["role"] for f in self.fonts.get("families", [])}
        for role, typo in self.theme.get("typeScale", {}).items():
            w = typo.get("weight", "regular")
            fam = "bold" if w == "bold" else w
            if fam not in font_roles:
                errors.append(f"字体角色缺失: weight {w} (role {role})")

        if errors:
            raise ModelError(errors)


class PageView:
    """单个页面的内容/素材视图（素材路径已解析为绝对路径）。"""

    def __init__(self, content: dict, assets: dict):
        self.content = content
        self.assets = assets


class PageData:
    def __init__(self, data_path: str | Path):
        self.path = Path(data_path)
        self.dir = self.path.parent
        self.raw = load_json(self.path)
        self.content = self.raw.get("content", {})
        self.assets = dict(self.raw.get("assets", {}))
        self.pages = self.raw.get("pages", {})
        self.publish = self.raw.get("publish", {})
        self._validate()

    def _validate(self):
        errors: list[str] = []
        for key, rel in self.assets.items():
            p = (self.dir / rel).resolve()
            if not p.exists():
                errors.append(f"素材不存在: {key} -> {rel}")
            else:
                self.assets[key] = str(p)
        for pkey, pview in self.pages.items():
            for key, rel in (pview.get("assets") or {}).items():
                p = (self.dir / rel).resolve()
                if not p.exists():
                    errors.append(f"素材不存在: page={pkey} {key} -> {rel}")
        if errors:
            raise ModelError(errors)

    def view(self, key: str) -> PageView:
        """返回某一页的内容/素材视图；无 pages 结构时（run-003 兼容）返回整包。"""
        if not self.pages:
            return PageView(self.content, self.assets)
        if key not in self.pages:
            raise ModelError([f"page_data.json 的 pages 中缺少页面: {key}"])
        pv = self.pages[key]
        assets = {k: str((self.dir / v).resolve()) for k, v in (pv.get("assets") or {}).items()}
        return PageView(pv.get("content") or {}, assets)

    def require_content(self, key: str):
        return self.content.get(key)
