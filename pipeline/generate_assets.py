# -*- coding: utf-8 -*-
"""节点③ 图片生成（路线 A：gpt-image-2 直出透明 PNG，无抠图后处理）。

输入：<run>/asset_jobs.json
  {
    "jobs": [
      {"key":"subject", "file":"assets/main_subject.png", "transparent": true,
       "quality":"medium", "size":"1024x1024", "prompt":"..."},
      {"key":"background", "file":"assets/element_2.png", "transparent": false,
       "quality":"auto", "size":"1024x1536", "prompt":"..."}
    ]
  }

输出：
- 每个 job 的图片文件
- <run>/assets_manifest.json：字节数/md5/尺寸/mode/alpha 统计/验收结论
- 已存在的文件默认跳过（省钱，可 --force 重生成）

验收门禁（素材入槽前）：
- transparent=true：必须 PNG/RGBA、四角 alpha<=8、透明占比>30%、主体占比 5%~95%
- transparent=false：必须能被 Pillow 打开且短边>=512
任一失败 -> 退出码 1，不允许进入排版。

用法：
  python pipeline/generate_assets.py --run output/run-004
  python pipeline/generate_assets.py --run output/run-004 --env D:/path/to/.env --force
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_PIL_LIBS = _ROOT / "output" / "run-002" / "libs"
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if _PIL_LIBS.exists() and str(_PIL_LIBS) not in sys.path:
    sys.path.insert(0, str(_PIL_LIBS))


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            import os
            os.environ.setdefault(k.strip(), v.strip())


def _alpha_stats(path: Path) -> dict:
    from PIL import Image
    im = Image.open(path)
    mode = im.mode
    rgba = im.convert("RGBA")
    w, h = rgba.size
    a = rgba.getchannel("A")
    corners = [a.getpixel(p) for p in [(2, 2), (w - 3, 2), (2, h - 3), (w - 3, h - 3)]]
    hist = a.histogram()
    n = sum(hist)
    transparent = sum(hist[:9]) / n          # alpha 0..8
    opaque = sum(hist[247:]) / n             # alpha 247..255
    return {
        "mode": mode, "width": w, "height": h,
        "cornerAlpha": corners,
        "transparentShare": round(transparent, 4),
        "opaqueShare": round(opaque, 4),
        "partialShare": round(1 - transparent - opaque, 4),
    }


def _verify(job: dict, path: Path) -> tuple[bool, str, dict]:
    stats = _alpha_stats(path)
    if job.get("transparent"):
        ok = (
            stats["mode"] == "RGBA"
            and all(c <= 8 for c in stats["cornerAlpha"])
            and stats["transparentShare"] > 0.30
            and 0.05 < stats["opaqueShare"] < 0.95
        )
        reason = "透明素材验收通过" if ok else (
            f"透明验收失败: mode={stats['mode']} corners={stats['cornerAlpha']} "
            f"transparent={stats['transparentShare']} opaque={stats['opaqueShare']}"
        )
        return ok, reason, stats
    ok = min(stats["width"], stats["height"]) >= 512
    reason = "普通素材验收通过" if ok else f"普通素材分辨率过低: {stats['width']}x{stats['height']}"
    return ok, reason, stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--env", default=str(_ROOT / ".env"), help="可选 .env 路径（读取 APIMART_API_KEY）")
    ap.add_argument("--force", action="store_true", help="已存在的素材也重新生成（付费）")
    args = ap.parse_args()

    _load_env(Path(args.env))
    from services.gpt_image2 import generate_image, ImageServiceError

    run_dir = (_ROOT / args.run).resolve()
    jobs_path = run_dir / "asset_jobs.json"
    spec = json.loads(jobs_path.read_text(encoding="utf-8"))

    manifest: list[dict] = []
    failed = False
    for job in spec["jobs"]:
        out = run_dir / job["file"]
        rec = {"key": job["key"], "file": job["file"], "transparent": bool(job.get("transparent"))}
        if out.exists() and not args.force:
            ok, reason, stats = _verify(job, out)
            print(f"[SKIP] {job['key']} 已存在 -> {out.name}（{reason}）", flush=True)
            rec.update({"skipped": True, "ok": ok, "reason": reason, **stats})
            manifest.append(rec)
            failed |= not ok
            continue

        out.parent.mkdir(parents=True, exist_ok=True)
        print(f"[START] {job['key']} 提交 gpt-image-2（transparent={job.get('transparent', False)}）", flush=True)
        try:
            res = generate_image(
                job["prompt"],
                size=job.get("size", "1024x1024"),
                quality=job.get("quality", "auto"),
                background="transparent" if job.get("transparent") else None,
                output_format="png" if job.get("transparent") else None,
            )
        except ImageServiceError as e:
            print(f"[FAIL] {job['key']}: {e}", flush=True)
            rec.update({"ok": False, "reason": f"生图服务错误: {e}"})
            manifest.append(rec)
            failed = True
            continue

        data = res["image_bytes"]
        out.write_bytes(data)
        ok, reason, stats = _verify(job, out)
        md5 = hashlib.md5(data).hexdigest()
        print(f"[{'OK' if ok else 'FAIL'}] {job['key']}: {out.name} | {len(data)}B | md5={md5[:10]} | {reason}", flush=True)
        rec.update({"skipped": False, "ok": ok, "reason": reason, "bytes": len(data),
                    "md5": md5, "taskId": res["task_id"], **stats})
        manifest.append(rec)
        failed |= not ok

    (run_dir / "assets_manifest.json").write_text(
        json.dumps({"all_ok": not failed, "assets": manifest}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if failed:
        print("[FAIL] 素材验收未全部通过，禁止进入排版", flush=True)
        return 1
    print(f"[DONE] 全部 {len(manifest)} 个素材验收通过", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
