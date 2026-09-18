# -*- coding: utf-8 -*-
"""检查素材图片的尺寸与体积。"""
import os
from PIL import Image

SRC = [
    ("cover", r"C:\Users\mattq\Pictures\Screenshots\屏幕截图 2026-05-11 230755.png"),
    ("read",  r"C:\Users\mattq\Pictures\Screenshots\屏幕截图 2026-09-14 225222.png"),
    ("eat",   r"C:\Users\mattq\Pictures\Screenshots\屏幕截图 2026-09-14 225215.png"),
]

lines = []
total = 0
for name, path in SRC:
    ok = os.path.exists(path)
    if not ok:
        lines.append(f"{name}: MISSING {path}")
        continue
    size = os.path.getsize(path)
    total += size
    with Image.open(path) as im:
        lines.append(f"{name}: {im.size[0]}x{im.size[1]} mode={im.mode} {size/1024:.1f} KB")
lines.append(f"total raw: {total/1024:.1f} KB")
lines.append(f"base64 estimate: {total*4/3/1024:.1f} KB")
lines.append(f"python exe path: {os.path.dirname(os.path.dirname(os.path.abspath(__file__)))}")

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "_assets_report.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print("\n".join(lines))
