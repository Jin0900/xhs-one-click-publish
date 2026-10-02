"""发布前校验 V1-V9。FAIL 阻断；WARN 需人工确认。输出 validation.json。"""
from __future__ import annotations

from pathlib import Path

from .model import CANVAS_W, CANVAS_H, Spec


def _rects_intersect(a, b, margin=0.0) -> bool:
    return not (
        a[2] + margin <= b[0] or b[2] + margin <= a[0]
        or a[3] + margin <= b[1] or b[3] + margin <= a[1]
    )


def validate_run(
    spec: Spec,
    manifest: dict,
    engine_errors: list[str],
    font_report: dict,
    out_files: list[dict],          # [{"key","path","expected_name"}]
    title_platform_limit: int = 20,
) -> dict:
    checks: dict[str, dict] = {}
    errors: list[str] = []
    warnings: list[str] = []

    def fail(code, msg):
        checks[code] = {"status": "FAIL", "detail": msg}
        errors.append(f"[{code}] {msg}")

    def pass_(code, msg=""):
        checks[code] = {"status": "PASS", "detail": msg}

    def warn(code, msg):
        checks[code] = {"status": "WARN", "detail": msg}
        warnings.append(f"[{code}] {msg}")

    # V1 严格尺寸 + 3:4 -------------------------------------------------------
    from PIL import Image
    size_ok = True
    size_details = []
    for f in out_files:
        p = Path(f["path"])
        if not p.exists():
            fail("V1", f"输出文件不存在: {f['expected_name']}")
            size_ok = False
            continue
        with Image.open(p) as im:
            w, h = im.size
        ratio_eq = (w / h) == 0.75
        size_details.append({"file": f["expected_name"], "width": w, "height": h, "ratio_ok": ratio_eq})
        if (w, h) != (CANVAS_W, CANVAS_H) or not ratio_eq:
            fail("V1", f"{f['expected_name']} 尺寸 {w}x{h}，必须严格 {CANVAS_W}x{CANVAS_H} (3:4)")
            size_ok = False
    if size_ok:
        pass_("V1", f"全部 {len(out_files)} 张严格 {CANVAS_W}x{CANVAS_H}，width/height==0.75")

    # V2 数量与顺序 -----------------------------------------------------------
    expected_order = {"cover": "01_cover.png", "page1": "02_page1.png",
                      "page2": "03_page2.png", "page3": "04_page3.png"}
    names = [Path(f["path"]).name for f in out_files]
    want = [expected_order[f["key"]] for f in out_files]
    if names == want and len(set(names)) == len(names):
        pass_("V2", f"数量={len(names)}，顺序={names}")
    else:
        fail("V2", f"文件名/顺序不符: 实际 {names}，应为 {want}")

    # V3 字符预算 & V4 溢出（来自引擎实测） -----------------------------------
    overflow = [e for e in engine_errors if ("溢出" in e or "超预算" in e or "超宽" in e
                                            or "超出盒模型" in e or "超 labelMaxChars" in e)]
    if overflow:
        fail("V4", "；".join(overflow))
    else:
        # 复核 manifest 行数/预算
        bad = []
        for sid, m in manifest["slots"].items():
            if m["type"] == "text":
                if m["lineCount"] > m["maxLines"] or m["charCount"] > m["maxChars"]:
                    bad.append(sid)
        if bad:
            fail("V4", f"槽位超行/超字: {bad}")
        else:
            pass_("V4", "无文字溢出，全部在盒模型与行数预算内")

    # 平台标题字数
    title_m = manifest["slots"].get("title")
    if title_m and title_m["charCount"] > title_platform_limit:
        fail("V3", f"平台标题限制 {title_platform_limit} 字，当前 {title_m['charCount']} 字")
    else:
        pass_("V3", f"标题 {title_m['charCount'] if title_m else 0} 字 ≤ {title_platform_limit}")

    # V5 最小字号地板 ----------------------------------------------------------
    floor_bad = []
    for sid, m in manifest["slots"].items():
        if "fontSize" not in m:
            continue
        role = m.get("role") or {"step_row": "body"}.get(m["type"])
        if role and role in spec.theme["typeScale"]:
            floor = spec.theme["typeScale"][role]["minSize"]
            if m["fontSize"] < floor:
                floor_bad.append(f"{sid}:{m['fontSize']}<{floor}")
    if floor_bad:
        fail("V5", "低于最小字号地板: " + ",".join(floor_bad))
    else:
        pass_("V5", "所有文字字号 ≥ role 最小地板")

    # V6 安全边距（model 加载时强校验；这里复核 manifest box） ------------------
    margin = spec.canvas["safeMargin"]
    oob = []
    for sid, m in manifest["slots"].items():
        x, y, w, h = m["box"]
        if x < margin or y < margin or x + w > CANVAS_W - margin or y + h > CANVAS_H - margin:
            oob.append(sid)
    if oob:
        fail("V6", f"槽位越出安全区 {margin}px: {oob}")
    else:
        pass_("V6", f"全部槽位位于 {margin}px 安全区内")

    # V7 碰撞检测 --------------------------------------------------------------
    collisions: list[str] = []
    non_media = {sid: m for sid, m in manifest["slots"].items() if m["type"] != "media"}
    # a) 非媒体槽盒模型两两不重叠
    def box_rect(m):
        x, y, w, h = m["box"]
        return [x, y, x + w, y + h]

    keys = list(non_media.keys())
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            a, b = non_media[keys[i]], non_media[keys[j]]
            if _rects_intersect(box_rect(a), box_rect(b), margin=1):
                collisions.append(f"盒模型重叠: {keys[i]} <-> {keys[j]}")
    # b) 媒体实际 alpha 包围盒 vs keepOut 目标的文字/实体矩形
    for sid, m in manifest["slots"].items():
        if m["type"] != "media" or not m.get("pixelBox"):
            continue
        pb = m["pixelBox"]
        tol = m.get("keepOutMargin", 0)
        for target in m.get("keepOut", []):
            tm = manifest["slots"].get(target)
            if not tm:
                continue
            for r in tm.get("textRects", []) + tm.get("solidRects", []):
                if _rects_intersect(pb, r, margin=tol):
                    collisions.append(f"{sid} 实际像素遮挡 {target}: pixelBox={pb} rect={r}")
    if collisions:
        fail("V7", "；".join(collisions))
    else:
        pass_("V7", "无元素重叠，主体未遮挡文字")

    # V8 信息密度（四等分带） WARN ---------------------------------------------
    band_h = CANVAS_H // 4
    coverages = []
    for b in range(4):
        band_rect = [0, b * band_h, CANVAS_W, (b + 1) * band_h]
        area = 0
        for m in manifest["slots"].values():
            x, y, w, h = m["box"]
            r = [x, y, x + w, y + h]
            ix1, iy1 = max(r[0], band_rect[0]), max(r[1], band_rect[1])
            ix2, iy2 = min(r[2], band_rect[2]), min(r[3], band_rect[3])
            if ix2 > ix1 and iy2 > iy1:
                area += (ix2 - ix1) * (iy2 - iy1)
        coverages.append(round(area / (CANVAS_W * band_h), 3))
    empty_bands = [i + 1 for i, c in enumerate(coverages) if c < 0.20]
    if empty_bands:
        warn("V8", f"信息带 {empty_bands} 填充率<0.20，疑似空带；各带覆盖率={coverages}")
    else:
        pass_("V8", f"四信息带均有内容，覆盖率={coverages}")

    # V9 字体可用性 -------------------------------------------------------------
    if font_report.get("ok"):
        pass_("V9", f"字体可用: {font_report.get('fonts')}，字形抽检通过")
    else:
        fail("V9", f"字体/字形异常: missing={font_report.get('missing')} fonts={font_report.get('fonts')}")

    other_errors = [e for e in engine_errors if e not in overflow]
    if other_errors:
        fail("VX", "其他渲染错误: " + "；".join(other_errors))

    render_success = not errors
    report = {
        "width": CANVAS_W,
        "height": CANVAS_H,
        "ratio": "3:4",
        "text_overflow": bool(overflow),
        "element_collision": bool(collisions),
        "font_valid": bool(font_report.get("ok")),
        "render_success": render_success,
        "checks": checks,
        "errors": errors,
        "warnings": warnings,
        "outputs": [{"key": f["key"], "file": Path(f["path"]).name, **d}
                    for f, d in zip(out_files, size_details)],
    }
    return report
