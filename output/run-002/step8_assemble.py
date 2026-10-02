# -*- coding: utf-8 -*-
"""run-002 第⑩⑪步：图片整理/内容组合 + 发布准备。
- final/ 按发布顺序复制 4 张成图（01_cover ... 04_page3），校验数量/尺寸/去重
- manifest.json 记录顺序、尺寸、MD5
- publish_data.json 符合 SKILL.md 最终发布数据结构
"""
import hashlib
import json
import shutil
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE / "libs"))
from PIL import Image  # noqa: E402

FINAL = BASE / "final"
FINAL.mkdir(exist_ok=True)

ORDER = [
    ("cover", "cover.png", "01_cover.png"),
    ("page1", "page1.png", "02_page1.png"),
    ("page2", "page2.png", "03_page2.png"),
    ("page3", "page3.png", "04_page3.png"),
]

TITLE = "夏季护肤做减法"
CONTENT = (
    "夏天护肤不用堆太多步骤\n"
    "\n"
    "第一步：温和清洁\n"
    "夏天出油出汗多，选一款温和的洁面，早晚各洗一次就够了，别过度清洁\n"
    "\n"
    "第二步：清爽保湿\n"
    "换掉厚重的面霜，用清爽的乳液或啫喱，薄薄一层就够\n"
    "\n"
    "第三步：出门防晒\n"
    "白天出门前一定要涂防晒，这是夏季护肤最重要的一步\n"
    "\n"
    "护肤精简三步：清洁、保湿、防晒，清爽过夏天"
)

# ---- ⑩ 图片整理 ----
items = []
md5_seen = {}
errors = []
for key, src_name, dst_name in ORDER:
    src = BASE / src_name
    if not src.exists():
        errors.append(f"缺少 {src_name}")
        continue
    with Image.open(src) as im:
        size = im.size
    data = src.read_bytes()
    digest = hashlib.md5(data).hexdigest()
    if digest in md5_seen:
        errors.append(f"{src_name} 与 {md5_seen[digest]} MD5 重复")
    md5_seen[digest] = src_name
    shutil.copyfile(src, FINAL / dst_name)
    items.append({
        "order": len(items) + 1,
        "key": key,
        "file": dst_name,
        "size_px": list(size),
        "bytes": len(data),
        "md5": digest,
    })
    print(f"[OK] {dst_name} | {size} | {len(data)} bytes | md5={digest[:12]}", flush=True)

manifest = {
    "run": "run-002",
    "topic": "夏季护肤产品",
    "count": len(items),
    "order_rule": "cover -> page1 -> page2 -> page3",
    "images": items,
}
(FINAL / "manifest.json").write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
)

# ---- 自动验证 ----
print("\n=== 自动验证 ===", flush=True)
checks = {
    "title 非空": bool(TITLE),
    "title <= 20字": len(TITLE) <= 20,
    "content 非空": bool(CONTENT),
    "content <= 1000字": len(CONTENT) <= 1000,
    "图片数量=4": len(items) == 4,
    "图片顺序正确": [i["key"] for i in items] == ["cover", "page1", "page2", "page3"],
    "全部竖版1024x1536": all(i["size_px"] == [1024, 1536] for i in items),
    "无重复图片": not errors,
}
for name, ok in checks.items():
    print(f"[{'PASS' if ok else 'FAIL'}] {name}", flush=True)

# ---- ⑪ 发布准备 ----
publish_data = {
    "title": TITLE,
    "content": CONTENT,
    "images": ["cover", "page1", "page2", "page3"],
}
(BASE / "publish_data.json").write_text(
    json.dumps(publish_data, ensure_ascii=False, indent=2), encoding="utf-8"
)
# 伴随字段（不属于发布内容本身）
(BASE / "publish_meta.json").write_text(
    json.dumps({"zhanghao": "测试账号（发布前需替换为真实小红书账号）",
                "image_dir": "output/run-002/final"}, ensure_ascii=False, indent=2),
    encoding="utf-8",
)
print("\n[OK] publish_data.json / publish_meta.json / final/manifest.json 已生成", flush=True)
print(f"[{'DONE' if all(checks.values()) and not errors else 'HAS_ERRORS'}] 第⑩⑪步结束", flush=True)
