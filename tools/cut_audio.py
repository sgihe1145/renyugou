# -*- coding: utf-8 -*-
"""从原曲里裁出四段音效，转成 exe 内嵌用的 PCM WAV。

用法：
    python tools/cut_audio.py                 # 用下面 CLIPS 里记录的时间点
    python tools/cut_audio.py --source xxx.mp3

产物：build/audio/*.wav（由 tools/build_assets.py 打进 src/assets.py）
运行期用 winsound.PlaySound(path, SND_FILENAME | SND_ASYNC) 播放。
"""
import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SRC = os.path.join(ROOT, "media", "欸？大狗！ [BV1xyJA6BEBN].mp3")
OUT_DIR = os.path.join(ROOT, "build", "audio")
FFMPEG = r"C:\Users\mattq\.workbuddy\binaries\python\envs\default\Lib\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe"

# 名称 -> (起点秒, 时长秒, 备注)
# 起点/时长来自 tools/analyze_audio.py 的包络分段 + tools/subtitle_timeline.py 的字幕时间轴：
#   0.80~2.00  「欸 大狗」    字幕 1.0s 显示"欸 云朵"、1.5s 显示"欸 大狗"；2.0~2.2s 有气口
#   2.22~3.90  「哒哒哒哒哒」  字幕 2.5 / 3.0 / 3.5s 连续显示
#   5.35~6.48  「叫叫叫！」    字幕 5.4~6.4s 显示；6.5~6.65s 有气口
#   8.55~9.45  「大狗叫叫」    字幕 8.9s 显示"看 大狗叫叫"
CLIPS = {
    "open_intro": (0.80, 1.20, "启动：欸，大狗！"),
    "read": (2.22, 1.68, "读书：哒哒哒哒哒"),
    "eat": (5.35, 1.13, "吃饭：叫叫叫！"),
    "basket": (8.55, 0.90, "打篮球：大狗叫叫"),
}

FADE_IN = 0.03
FADE_OUT = 0.12


def cut(src, start, dur, dst):
    fo_at = max(0.0, dur - FADE_OUT)
    afilter = ("afade=t=in:st=0:d=%.3f,afade=t=out:st=%.3f:d=%.3f"
               % (FADE_IN, fo_at, FADE_OUT))
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
           "-ss", "%.3f" % start, "-t", "%.3f" % dur, "-i", src,
           "-af", afilter, "-ac", "1", "-ar", "22050",
           "-c:a", "pcm_s16le", dst]
    subprocess.run(cmd, check=True)
    return os.path.getsize(dst)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=DEFAULT_SRC)
    args = ap.parse_args()
    if not os.path.exists(args.source):
        print("源文件不存在：%s" % args.source)
        return 1
    os.makedirs(OUT_DIR, exist_ok=True)
    log = []
    for name, (start, dur, note) in CLIPS.items():
        dst = os.path.join(OUT_DIR, name + ".wav")
        size = cut(args.source, start, dur, dst)
        try:
            shown = note.encode("utf-8").decode("utf-8")
        except Exception:
            shown = name
        log.append("%-11s start=%5.2fs dur=%4.2fs  %6.1f KB  %s"
                   % (name, start, dur, size / 1024.0, shown))
    with open(os.path.join(ROOT, "build", "_cut_audio.log"), "w", encoding="utf-8") as f:
        f.write("\n".join(log))
    print("\n".join(log))
    return 0


if __name__ == "__main__":
    sys.exit(main())
