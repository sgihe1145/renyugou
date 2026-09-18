# -*- coding: utf-8 -*-
"""检查新增素材是否存在、尺寸与模式（结果写 build/_new_assets.txt）。"""
import os

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S = r"C:\Users\mattq\Pictures\Screenshots"
FILES = [
    ("COVER", "屏幕截图 2026-05-11 230755.png"),
    ("READ", "屏幕截图 2026-09-14 225222.png"),
    ("EAT", "屏幕截图 2026-09-14 225215.png"),
    ("BASKET_PLAY", "屏幕截图 2026-09-15 213216.png"),
    ("BASKET_FALL", "屏幕截图 2026-09-15 213205.png"),
    ("BASKET_HAPPY", "屏幕截图 2026-09-15 213153.png"),
    ("BASKET_ANGRY", "屏幕截图 2026-09-15 213309.png"),
]
lines = []
for key, name in FILES:
    p = os.path.join(S, name)
    if not os.path.isfile(p):
        lines.append("%-13s MISSING  %s" % (key, name))
        continue
    with Image.open(p) as im:
        lines.append("%-13s %-5s %dx%d  %.1f KB" % (
            key, im.mode, im.size[0], im.size[1], os.path.getsize(p) / 1024.0))

out = os.path.join(ROOT, "build", "_new_assets.txt")
with open(out, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print("\n".join(lines))
