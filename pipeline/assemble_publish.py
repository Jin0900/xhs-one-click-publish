"""组装发布准备包：校验 final/ 四图与 publish 字段 -> publish_data.json。

用法（纯标准库，无第三方依赖）：
  python pipeline/assemble_publish.py --run output/run-004

校验项（任一失败退出码 1，不产出发布包）：
  1. validation.json overall.render_success == true
  2. final/ 下四张图存在且为 PNG、严格 1080x1440 (3:4)
  3. publish.images 恰好 4 张，顺序 cover -> page1 -> page2 -> page3
  4. publish.title 非空且 <= 20 字；publish.content 非空且 <= 1000 字
通过后：
  - 写 publish_data.json（发布包清单，含每张图绝对路径与尺寸）
  - page_data.json 的 publish.status 更新为 ready_for_review（发布前必须人工确认）
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

EXPECTED_ORDER = [("cover", "01_cover.png"), ("page1", "02_page1.png"),
                  ("page2", "03_page2.png"), ("page3", "04_page3.png")]
CANVAS_W, CANVAS_H = 1080, 1440


def png_size(path: Path) -> tuple[int, int]:
    with open(path, "rb") as f:
        head = f.read(24)
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"非 PNG 文件: {path}")
    return struct.unpack(">II", head[16:24])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="output/run-004")
    args = ap.parse_args()

    run_dir = Path(args.run).resolve()
    pd_path = run_dir / "page_data.json"
    with open(pd_path, "r", encoding="utf-8-sig") as f:
        page_data = json.load(f)
    publish = page_data.get("publish", {})

    errors: list[str] = []

    # 1) 渲染校验必须通过
    with open(run_dir / "validation.json", "r", encoding="utf-8-sig") as f:
        validation = json.load(f)
    overall = validation.get("overall", {})
    if not overall.get("render_success"):
        errors.append("validation.json overall.render_success != true，禁止进入发布准备")

    # 2) 四张图存在 / PNG / 尺寸
    images_meta: list[dict] = []
    for role, fname in EXPECTED_ORDER:
        p = run_dir / "final" / fname
        if not p.exists():
            errors.append(f"缺少图片: final/{fname}")
            continue
        try:
            w, h = png_size(p)
        except ValueError as e:
            errors.append(str(e))
            continue
        if (w, h) != (CANVAS_W, CANVAS_H):
            errors.append(f"final/{fname} 尺寸 {w}x{h}，必须严格 {CANVAS_W}x{CANVAS_H}")
        images_meta.append({"role": role, "file": fname,
                            "path": str(p), "width": w, "height": h})

    # 3) images 数量与顺序
    listed = publish.get("images", [])
    want = [f"final/{fname}" for _, fname in EXPECTED_ORDER]
    if listed != want:
        errors.append(f"publish.images 数量/顺序不符: 实际 {listed}，应为 {want}")

    # 4) 文案契约
    title = str(publish.get("title", "")).strip()
    content = str(publish.get("content", "")).strip()
    if not title:
        errors.append("publish.title 为空")
    elif len(title) > 20:
        errors.append(f"publish.title 超平台限制: {len(title)} > 20 字")
    if not content:
        errors.append("publish.content 为空")
    elif len(content) > 1000:
        errors.append(f"publish.content 超限: {len(content)} > 1000 字")

    if errors:
        print("[FAIL] 发布准备包校验未通过：")
        for e in errors:
            print("  -", e)
        return 1

    # 5) 产出发布包清单 + 状态流转
    publish_data = {
        "schemaVersion": 1,
        "run": run_dir.name,
        "title": title,
        "content": content,
        "images": images_meta,
        "order": [role for role, _ in EXPECTED_ORDER],
        "status": "ready_for_review",
        "validation": {
            "render_success": True,
            "errors": overall.get("errors", []),
            "warnings": overall.get("warnings", []),
        },
    }
    with open(run_dir / "publish_data.json", "w", encoding="utf-8") as f:
        json.dump(publish_data, f, ensure_ascii=False, indent=2)

    publish["status"] = "ready_for_review"
    with open(pd_path, "w", encoding="utf-8") as f:
        json.dump(page_data, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"[DONE] 发布准备包: {run_dir / 'publish_data.json'}")
    print(f"  title   : {title}（{len(title)} 字）")
    print(f"  content : {len(content)} 字")
    for m in images_meta:
        print(f"  [{m['role']:>6}] {m['file']}  {m['width']}x{m['height']}")
    print("  status  : ready_for_review（等待人工确认，不自动发布）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
