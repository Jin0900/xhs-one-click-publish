# -*- coding: utf-8 -*-
"""仅重试 bg_page3（上游失败重试，不重跑其他图）。"""
import os
import sys
import time
import hashlib
from pathlib import Path

env_path = r"D:\Traeeeeee\AI image\.env"
for line in Path(env_path).read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

sys.path.insert(0, r"D:\Traeeeeee\AI image")
from backend.services.ai_image import generate_image  # noqa: E402

OUT = Path(__file__).resolve().parent
os.environ["IMAGE_SIZE"] = "1024x1536"
prompt = (
    "vertical mobile wallpaper 1024x1536, soft airy minimalist background, "
    "smooth gradient of warm cream and soft sunlight beige fading to clean white, "
    "subtle bokeh light spots, large clean empty space for text overlay, "
    "no objects, no people, no text, no logo, no watermark, gentle dreamy aesthetic, high resolution"
)

for attempt in range(1, 4):
    print(f"[RETRY {attempt}] bg_page3", flush=True)
    try:
        data = generate_image(prompt)["image_bytes"]
        path = OUT / "bg_page3.png"
        path.write_bytes(data)
        print(f"[OK] bg_page3.png | {len(data)} bytes | md5={hashlib.md5(data).hexdigest()[:12]}", flush=True)
        break
    except Exception as e:  # noqa: BLE001
        print(f"[FAILED {attempt}] {type(e).__name__}: {e}", flush=True)
        time.sleep(5)
else:
    print("[GIVEUP] bg_page3 三次重试均失败", flush=True)
