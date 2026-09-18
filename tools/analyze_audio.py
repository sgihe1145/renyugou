# -*- coding: utf-8 -*-
"""音频包络分析：找出「发声段」的精确起止时间。

用于给字幕时间轴吸附到真实的音符边界——因为字幕显示时刻和歌声不完全同步，
裁音效必须按音频本身来切。

用法：python tools/analyze_audio.py [--from 0 --to 12]
输出 build/_envelope.txt
"""
import argparse
import os
import sys

import av
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "build", "_envelope.txt")

HOP = 0.010          # 10ms 一帧
WIN = 0.030          # 30ms 窗
REL_THRESHOLD = 0.10     # 相对峰值的阈值（判断"有人在唱"）
MIN_SIL = 0.06       # 连续低于阈值这么久才算断句
MIN_SEG = 0.12       # 发声段最短时长


def envelope(src):
    container = av.open(src)
    stream = container.streams.audio[0]
    rate = stream.rate
    chunks = []
    for frame in container.decode(stream):
        arr = frame.to_ndarray()
        if arr.ndim == 2 and arr.shape[0] > 1:
            arr = arr.mean(axis=0)
        else:
            arr = arr.reshape(-1)
        chunks.append(arr.astype(np.float32))
    container.close()
    sig = np.concatenate(chunks) if chunks else np.zeros(1, dtype=np.float32)
    step = max(1, int(round(rate * HOP)))
    win = max(step, int(round(rate * WIN)))
    n = max(1, (len(sig) - win) // step + 1)
    rms = np.empty(n, dtype=np.float32)
    for i in range(n):
        seg = sig[i * step:i * step + win]
        rms[i] = float(np.sqrt(np.mean(seg * seg))) if len(seg) else 0.0
    return rms, rate


def segments(rms):
    peak = float(np.percentile(rms, 99.5)) or 1.0
    th = peak * REL_THRESHOLD
    loud = rms > th
    segs = []
    i = 0
    n = len(loud)
    while i < n:
        if loud[i]:
            j = i
            while j < n and loud[j]:
                j += 1
            a, b = i * HOP, j * HOP
            if b - a >= MIN_SEG:
                segs.append([a, b])
            i = j
        else:
            i += 1
    # 合并间隔很短的段（同一个字/气口）
    merged = []
    for s in segs:
        if merged and s[0] - merged[-1][1] < MIN_SIL:
            merged[-1][1] = s[1]
        else:
            merged.append(s)
    return merged, th


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=os.path.join(
        ROOT, "media", "欸？大狗！ [BV1xyJA6BEBN].mp3"))
    ap.add_argument("--from", dest="t0", type=float, default=0.0)
    ap.add_argument("--to", dest="t1", type=float, default=49.5)
    args = ap.parse_args()

    rms, rate = envelope(args.src)
    segs, th = segments(rms)

    lines = ["source: %s" % args.src,
             "rate=%d  frames=%d  hop=%.3fs  threshold=%.5f" % (rate, len(rms), HOP, th),
             "",
             "=== 全部发声段（秒）==="]
    for a, b in segs:
        lines.append("  %6.2f -> %6.2f   (%.2fs)" % (a, b, b - a))

    lines.append("")
    lines.append("=== 目标区间内的 100ms 包络（0=静，1=峰值）===")
    peak = float(np.percentile(rms, 99.5)) or 1.0
    i0 = int(args.t0 / HOP)
    i1 = min(len(rms), int(args.t1 / HOP))
    step = 10                     # 每 10 帧 = 100ms
    for i in range(i0, i1, step):
        vals = rms[i:i + step]
        lvl = float(vals.max()) / peak if len(vals) else 0.0
        t = i * HOP
        bar = "#" * int(round(lvl * 46))
        lines.append("  %6.2f  %.2f %s" % (t, lvl, bar))

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\n".join(lines[:40]))


if __name__ == "__main__":
    main()
