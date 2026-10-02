# -*- coding: utf-8 -*-
"""run-002 第④步前置检查：两个旧项目 venv 中是否已有抠图/图像处理能力。只读检查。"""
import importlib
import subprocess
import sys
from pathlib import Path

INTERPRETERS = [
    r"D:\Traeeeeee\AI image\.venv\Scripts\python.exe",
    r"D:\Traeeeeee\完整版 AI生图\python-service\venv\Scripts\python.exe",
]
MODS = ["PIL", "numpy", "rembg", "cv2", "onnxruntime"]

CHECK_CODE = (
    "import importlib\n"
    "mods = ['PIL','numpy','rembg','cv2','onnxruntime']\n"
    "for m in mods:\n"
    "    try:\n"
    "        mod = importlib.import_module(m)\n"
    "        print('[OK]  ', m, getattr(mod, '__version__', ''))\n"
    "    except Exception:\n"
    "        print('[MISS]', m)\n"
)

for interp in INTERPRETERS:
    print("===", interp, "===")
    if not Path(interp).exists():
        print("解释器不存在\n")
        continue
    proc = subprocess.run([interp, "-c", CHECK_CODE], capture_output=True, text=True)
    print(proc.stdout or proc.stderr)

# 本解释器（系统 Python）也查一次
print("=== system python ===", sys.executable)
for m in MODS:
    try:
        mod = importlib.import_module(m)
        print("[OK]  ", m, getattr(mod, "__version__", ""))
    except Exception:
        print("[MISS]", m)
