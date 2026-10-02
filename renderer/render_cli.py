"""渲染入口：page_data.json -> final/01_cover.png..04_page3.png + validation.json。

用法（系统 Python 3.13，无需全局安装 Pillow，自动复用 run-002/libs）：
  python renderer/render_cli.py --run output/run-004          # 四页一次渲染+合并校验
  python renderer/render_cli.py --run output/run-003 --template cover  # 单页
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# --- 复用 run-002/libs 中的 Pillow 12.3.0（不污染全局环境） -------------------
_ROOT = Path(__file__).resolve().parent.parent
_PIL_LIBS = _ROOT / "output" / "run-002" / "libs"
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if _PIL_LIBS.exists() and str(_PIL_LIBS) not in sys.path:
    sys.path.insert(0, str(_PIL_LIBS))

from renderer.model import Spec, PageData, ModelError  # noqa: E402
from renderer.engine_pillow import Engine  # noqa: E402
from renderer.validate import validate_run  # noqa: E402

PAGE_FILES = {"cover": "01_cover.png", "page1": "02_page1.png",
              "page2": "03_page2.png", "page3": "04_page3.png"}


def render_page(run_dir: Path, key: str, page: PageData):
    """渲染单页：模板 key.json + page.view(key)，保存并执行完整 V1-V9 校验。"""
    tpl_path = _ROOT / "templates" / "xhs_3x4" / f"{key}.json"
    spec = Spec(tpl_path)
    result = Engine(spec, page.view(key)).render()
    out_name = PAGE_FILES[key]
    out_path = run_dir / "final" / out_name
    result.image.convert("RGB").save(out_path, "PNG")
    report = validate_run(
        spec=spec,
        manifest=result.manifest,
        engine_errors=result.errors,
        font_report=result.font_report,
        out_files=[{"key": key, "path": str(out_path), "expected_name": out_name}],
    )
    return result, report, out_path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="output/run-004")
    ap.add_argument("--template", default="all",
                    help="cover|page1|page2|page3|all（默认 all 渲染四页）")
    args = ap.parse_args()

    run_dir = (_ROOT / args.run).resolve()
    data_path = run_dir / "page_data.json"
    final_dir = run_dir / "final"
    final_dir.mkdir(parents=True, exist_ok=True)

    keys = list(PAGE_FILES) if args.template == "all" else [args.template]
    for k in keys:
        if k not in PAGE_FILES:
            print(f"[FAIL] 未知模板: {k}（可选: {'/'.join(PAGE_FILES)}|all）")
            return 1

    try:
        page = PageData(data_path)
    except ModelError as e:
        print("[FAIL] 数据结构校验失败:")
        for err in e.errors:
            print("  -", err)
        return 1

    page_reports: dict[str, dict] = {}
    manifests: dict[str, dict] = {}
    failed = False
    try:
        for key in keys:
            result, report, out_path = render_page(run_dir, key, page)
            manifests[key] = result.manifest
            page_reports[key] = report
            print(f"[PAGE] {key} -> {out_path.name}  "
                  + "  ".join(f"{c}:{r['status']}" for c, r in report["checks"].items()))
            if not report["render_success"]:
                failed = True
    except ModelError as e:
        print("[FAIL] 模板/数据结构校验失败:")
        for err in e.errors:
            print("  -", err)
        return 1

    # --- 合并整个 run 的校验报告 ---------------------------------------------
    all_errors = [f"[{k}] {e}" for k, r in page_reports.items() for e in r["errors"]]
    all_warnings = [f"[{k}] {w}" for k, r in page_reports.items() for w in r["warnings"]]
    validation = {
        "run": run_dir.name,
        "width": 1080,
        "height": 1440,
        "ratio": "3:4",
        "pages": page_reports,
        "overall": {
            "render_success": not failed,
            "text_overflow": any(r["text_overflow"] for r in page_reports.values()),
            "element_collision": any(r["element_collision"] for r in page_reports.values()),
            "font_valid": all(r["font_valid"] for r in page_reports.values()),
            "errors": all_errors,
            "warnings": all_warnings,
            "outputs": [o for r in page_reports.values() for o in r["outputs"]],
        },
    }
    with open(run_dir / "validation.json", "w", encoding="utf-8") as f:
        json.dump(validation, f, ensure_ascii=False, indent=2)
    with open(run_dir / "layout_manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifests, f, ensure_ascii=False, indent=2)

    print(f"[DONE] {len(keys)} 页 -> {final_dir}")
    if failed:
        print("[FAIL] 存在阻断性问题，未通过发布前校验：")
        for e in all_errors:
            print("  -", e)
        return 1
    print("[OK] 校验通过" + ("（含 WARN，需人工确认）" if all_warnings else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
