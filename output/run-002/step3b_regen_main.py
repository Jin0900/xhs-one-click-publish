# -*- coding: utf-8 -*-
"""重新生成主图 main_image_v2.png：悬浮、无接触阴影，便于干净抠图。原 main_image.png 保留。"""
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
    "A minimalist white skincare lotion bottle with a pump dispenser, floating upright "
    "and centered in the frame, plain pure white seamless background, "
    "absolutely no shadow, no contact shadow, no ground, no reflection, "
    "soft even studio lighting, professional product photography, sharp focus, "
    "no label text, no logo, no brand, no watermark, no people"
)

for attempt in range(1, 4):
    print(f"[TRY {attempt}] main_image_v2", flush=True)
    try:
        data = generate_image(prompt)["image_bytes"]
        (OUT / "main_image_v2.png").write_bytes(data)
        print(f"[OK] main_image_v2.png | {len(data)} bytes | md5={hashlib.md5(data).hexdigest()[:12]} | {time.strftime('%H:%M:%S')}", flush=True)
        break
    except Exception as e:  # noqa: BLE001
        print(f"[FAILED {attempt}] {type(e).__name__}: {e}", flush=True)
        time.sleep(5)
else:
    print("[GIVEUP] 主图 v2 生成失败，请回退使用 main_image.png", flush=True)
