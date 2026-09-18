# -*- coding: utf-8 -*-
"""从视频里自动定位每一句字幕的时间区间。

思路：逐帧解码 -> 裁字幕区域 -> 与上一帧比差异 -> 差异突变的时刻即字幕切换点。
输出：
  build/_subtitle_timeline.txt   切换时刻列表 + 每个区间的代表帧文件名
  build\subs\seg_XX.png          每个区间的代表帧（供人工识别文字）
"""
import os
import sys

import av
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "build", "subs")
LOG = os.path.join(ROOT, "build", "_subtitle_timeline.txt")

# 字幕区域（1920x1080 下）。上下都留够，因为主/副字幕位置会变
CROP = (300, 850, 1620, 1060)
DIFF_THRESHOLD = 2.4          # 平均绝对差超过它算一次切换
MIN_GAP = 0.20                # 两次切换至少间隔这么久，避免抖动


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        ROOT, "media", "欸？大狗！ [BV1xyJA6BEBN]_H264.mp4")
    os.makedirs(OUT_DIR, exist_ok=True)
    for f in os.listdir(OUT_DIR):
        if f.endswith(".png"):
            os.remove(os.path.join(OUT_DIR, f))

    container = av.open(src)
    stream = container.streams.video[0]
    tb = stream.time_base

    changes = []          # (时间, 差异值)
    prev = None
    last_change = -9.0
    for frame in container.decode(stream):
        t = float(frame.pts * tb) if frame.pts is not None else 0.0
        img = frame.to_image().crop(CROP).convert("L")
        arr = np.asarray(img, dtype=np.float32)
        if prev is not None:
            d = float(np.abs(arr - prev).mean())
            if d > DIFF_THRESHOLD and (t - last_change) > MIN_GAP:
                changes.append((t, d))
                last_change = t
        prev = arr
    duration = float(container.duration) / av.time_base if container.duration else 0.0
    container.close()

    # 用切换点切出区间，抽每段中间帧作为代表帧
    bounds = [0.0] + [c[0] for c in changes] + [duration]
    lines = ["source: %s" % src,
             "duration: %.2fs" % duration,
             "切换点 %d 个" % len(changes), ""]

    container = av.open(src)
    stream = container.streams.video[0]
    tb = stream.time_base
    targets = []          # (目标时间, 文件名)
    segs = []
    for i in range(len(bounds) - 1):
        a, b = bounds[i], bounds[i + 1]
        if b - a < 0.15:
            continue
        mid = (a + b) / 2.0
        fname = "seg_%02d_%06.2f-%06.2f.png" % (len(segs), a, b)
        targets.append((mid, fname))
        segs.append((a, b, fname))
        lines.append("[%6.2f -> %6.2f]  %5.2fs  %s" % (a, b, b - a, fname))

    idx = 0
    for frame in container.decode(stream):
        if idx >= len(targets):
            break
        t = float(frame.pts * tb) if frame.pts is not None else 0.0
        while idx < len(targets) and t >= targets[idx][0]:
            frame.to_image().crop(CROP).save(os.path.join(OUT_DIR, targets[idx][1]))
            idx += 1
    container.close()

    with open(LOG, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
