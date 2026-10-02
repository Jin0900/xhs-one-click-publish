# -*- coding: utf-8 -*-
"""run-002 为⑥–⑨生成 3 张内容页 AI 背景（统一浅色极简风，竖版）。复用 GPT-Image-2。"""
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

STYLE = (
    "vertical mobile wallpaper 1024x1536, soft airy minimalist background, "
    "smooth gradient, subtle bokeh light spots, large clean empty space for text overlay, "
    "no objects, no people, no text, no logo, no watermark, gentle dreamy aesthetic, high resolution"
)
JOBS = [
    ("bg_page1", "pale sky blue fading to clean white, cool fresh summer morning tones, " + STYLE),
    ("bg_page2", "pale fresh mint green fading to clean white, hydrating natural tones, " + STYLE),
    ("bg_page3", "warm cream and soft sunlight beige fading to clean white, gentle golden tones, " + STYLE),
]

for name, prompt in JOBS:
    print(f"[START] {name}", flush=True)
    t0 = time.time()
    try:
        data = generate_image(prompt)["image_bytes"]
    except Exception as e:  # noqa: BLE001
        print(f"[FAILED] {name}: {type(e).__name__}: {e}", flush=True)
        continue
    ext = "png" if data[:8] == b"\x89PNG\r\n\x1a\n" else "jpg"
    path = OUT / f"{name}.{ext}"
    path.write_bytes(data)
    print(f"[OK] {path.name} | {len(data)} bytes | md5={hashlib.md5(data).hexdigest()[:12]} | {time.time()-t0:.0f}s", flush=True)

print("[DONE] 内容页背景生成结束", flush=True)
