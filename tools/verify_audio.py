# -*- coding: utf-8 -*-
"""校验裁出的音效：时长、峰值、RMS，确认不是静音、也没被切掉。"""
import os
import struct
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "media", "欸？大狗！ [BV1xyJA6BEBN].mp3")
AUDIO = os.path.join(ROOT, "build", "audio")
OUT = os.path.join(ROOT, "build", "_verify_audio.txt")

EXPECT = {
    "open_intro": (0.80, 1.20),
    "read": (2.22, 1.68),
    "eat": (5.35, 1.13),
    "basket": (8.55, 0.90),
}


def stats(path):
    with wave.open(path, "rb") as w:
        n, sw, ch, rate = w.getnframes(), w.getsampwidth(), w.getnchannels(), w.getframerate()
        raw = w.readframes(n)
    fmt = {1: "b", 2: "h"}[sw]
    total = n * ch
    vals = struct.unpack("<%d%s" % (total, fmt), raw)
    peak = max(abs(v) for v in vals)
    rms = (sum(float(v) * v for v in vals) / total) ** 0.5
    return n / float(rate), peak, rms, rate, ch, sw


lines = []
ok = 0
for name, (start, dur) in EXPECT.items():
    path = os.path.join(AUDIO, name + ".wav")
    if not os.path.exists(path):
        lines.append("%-11s MISSING" % name)
        continue
    length, peak, rms, rate, ch, sw = stats(path)
    good = (abs(length - dur) < 0.03) and peak > 2000 and rms > 300
    ok += 1 if good else 0
    lines.append("%-11s start=%5.2f dur=%5.2fs  实际=%5.2fs  峰值=%6d  RMS=%7.1f  "
                 "%dHz %dch %dbit  %s"
                 % (name, start, dur, length, peak, rms, rate, ch, sw * 8,
                    "OK" if good else "FAIL"))

lines.append("")
lines.append("通过 %d / %d" % (ok, len(EXPECT)))
with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print("\n".join(lines))
