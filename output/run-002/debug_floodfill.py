# -*- coding: utf-8 -*-
"""调试 floodfill：检查填充色与模式匹配、填充后像素值。"""
import sys
from pathlib import Path
BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE / "libs"))
from PIL import Image, ImageDraw

src = BASE / "main_image.png"
img = Image.open(src).convert("RGBA")
print("mode:", img.mode, "size:", img.size)
print("corner px before:", img.getpixel((0, 0)))

try:
    ImageDraw.floodfill(img, (0, 0), (255, 0, 255), thresh=30)
    print("3-tuple fill OK, corner after:", img.getpixel((0, 0)))
except Exception as e:
    print("3-tuple fill raised:", type(e).__name__, e)

img2 = Image.open(src).convert("RGBA")
try:
    ImageDraw.floodfill(img2, (0, 0), (255, 0, 255, 255), thresh=30)
    print("4-tuple fill OK, corner after:", img2.getpixel((0, 0)))
    print("center-ish after:", img2.getpixel((512, 700)))
except Exception as e:
    print("4-tuple fill raised:", type(e).__name__, e)
