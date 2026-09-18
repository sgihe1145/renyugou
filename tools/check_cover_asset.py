"""检查新的默认立绘素材尺寸与通道。"""
import os
from PIL import Image

SRC = r"C:\Users\mattq\Pictures\Screenshots\屏幕截图 2026-09-15 213339.png"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_cover_report.txt")

lines = []
if not os.path.exists(SRC):
    lines.append("MISSING: " + SRC)
else:
    im = Image.open(SRC)
    lines.append("path   : %s" % SRC)
    lines.append("mode   : %s" % im.mode)
    lines.append("size   : %s" % (im.size,))
    rgba = im.convert("RGBA")
    a = rgba.getchannel("A")
    lines.append("alpha  : min=%d max=%d" % (a.getextrema()))
    # 采样四角与中心
    w, h = rgba.size
    px = rgba.load()
    for name, (x, y) in {
        "topleft": (1, 1), "topright": (w - 2, 1),
        "bottomleft": (1, h - 2), "bottomright": (w - 2, h - 2),
        "center": (w // 2, h // 2),
    }.items():
        lines.append("px %-11s: %s" % (name, px[x, y]))
    lines.append("ratio  : %.4f" % (w / float(h)))
    lines.append("filesize: %d bytes" % os.path.getsize(SRC))

with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print("\n".join(lines))
