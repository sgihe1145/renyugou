# -*- coding: utf-8 -*-
"""转录音频并输出带时间戳的歌词，用于精确定位要截取的片段。

用法：python tools/transcribe_audio.py <音频文件>
结果写 build/_transcript.txt
"""
import os
import sys

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
# 走 hf-mirror 时必须关掉 xet：xet 的 CAS 服务不打镜像，会 401
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "build", "_transcript.txt")

MODEL_SIZE = os.environ.get("WHISPER_SIZE", "small")


def fmt(t):
    return "%6.2f" % t


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        ROOT, "media", "欸？大狗！ [BV1xyJA6BEBN].mp3")
    lines = ["file: %s" % src, "model: %s" % MODEL_SIZE, ""]

    from faster_whisper import WhisperModel
    model = WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8",
                         download_root=os.path.join(ROOT, "build", "_models"))

    segments, info = model.transcribe(src, language="zh", word_timestamps=True,
                                      beam_size=5, condition_on_previous_text=False)
    lines.append("duration: %.2fs" % info.duration)
    lines.append("")
    lines.append("=== 分段 ===")
    for seg in segments:
        lines.append("[%s -> %s] %s" % (fmt(seg.start), fmt(seg.end), seg.text.strip()))
        for w in (seg.words or []):
            lines.append("      [%s -> %s] %r p=%.2f"
                         % (fmt(w.start), fmt(w.end), w.word, w.probability))

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\n".join(lines[:12]))
    print("... written to", OUT)


if __name__ == "__main__":
    main()
