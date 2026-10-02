# -*- coding: utf-8 -*-
"""run-002 第③步：主图/副图生成。
复用 D:\\Traeeeeee\\AI image 项目中实测可用的 GPT-Image-2 服务。
产物保存到本脚本所在目录。不删除/覆盖任何其他文件。
"""
import os
import sys
import time
import hashlib
from pathlib import Path

# 1) 读取旧项目 .env（不打印 KEY）
env_path = r"D:\Traeeeeee\AI image\.env"
for line in Path(env_path).read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

# 2) 引入旧项目实测过的生图服务
sys.path.insert(0, r"D:\Traeeeeee\AI image")
from backend.services.ai_image import generate_image  # noqa: E402

OUT = Path(__file__).resolve().parent

# 3 张素材：主图（便于后续抠图，纯白底居中）、副图1、副图2
JOBS = [
    (
        "main_image",
        "A minimalist white skincare lotion bottle with a pump dispenser, "
        "standing upright and centered on a plain pure white seamless background, "
        "soft even studio lighting, professional e-commerce product photography, "
        "sharp focus, high resolution, no label text, no logo, no brand, no watermark, no people",
    ),
    (
        "element_img1",
        "Fresh clear water droplets on vibrant green plant leaves, "
        "plain pure white background, crisp macro photography, hydrating fresh feeling, "
        "high resolution, no text, no logo, no watermark, no people",
    ),
    (
        "element_img2",
        "Soft bright summer sunlight through sheer curtains, gentle light blue to warm cream "
        "gradient background, airy breezy minimal atmosphere, empty scene with no objects, "
        "high resolution, no text, no logo, no watermark, no people",
    ),
]


def detect_ext(b: bytes) -> str:
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if b[:3] == b"\xff\xd8\xff":
        return "jpg"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "webp"
    return "bin"


def run_one(name: str, prompt: str) -> None:
    print(f"[START] {name} 提交生图任务...", flush=True)
    t0 = time.time()
    try:
        result = generate_image(prompt)
    except Exception as e:  # noqa: BLE001
        status = getattr(e, "status", None)
        # 竖版尺寸不被支持时，回退方形重试一次
        if status == 400 and os.environ.get("IMAGE_SIZE") != "1024x1024":
            print(f"[RETRY] {name} 1024x1536 被拒({e})，回退 1024x1024", flush=True)
            os.environ["IMAGE_SIZE"] = "1024x1024"
            try:
                result = generate_image(prompt)
            except Exception as e2:  # noqa: BLE001
                print(f"[FAILED] {name}: {type(e2).__name__}: {e2}", flush=True)
                return
        else:
            print(f"[FAILED] {name}: {type(e).__name__}: {e}", flush=True)
            return
    data = result["image_bytes"]
    ext = detect_ext(data)
    path = OUT / f"{name}.{ext}"
    path.write_bytes(data)
    md5 = hashlib.md5(data).hexdigest()
    print(
        f"[OK] {name}: {path.name} | {len(data)} bytes | {ext} | "
        f"md5={md5} | 耗时 {time.time() - t0:.0f}s",
        flush=True,
    )


if __name__ == "__main__":
    # 默认尝试竖版 1024x1536（2:3，接近小红书竖版比例）
    os.environ["IMAGE_SIZE"] = "1024x1536"
    print(f"输出目录: {OUT}", flush=True)
    for job_name, job_prompt in JOBS:
        run_one(job_name, job_prompt)
    print("[DONE] 第③步全部任务结束", flush=True)
