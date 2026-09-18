# -*- coding: utf-8 -*-
"""把素材图、音效与窗口图标打包成 src/assets.py（base64 内嵌，保证单个 exe 可独立运行）。

大尺寸照片会先等比缩到长边 ≤ MAX_SIDE 再内嵌（显示区最大只有 540x405，
缩放后肉眼无差别，但能把 exe 体积压下来）。

音效说明：运行期用 winsound.PlaySound(SND_MEMORY|SND_ASYNC) 播放，
必须是 PCM WAV。由 tools/cut_audio.py 从原曲中裁出，放在 build/audio 下。
"""
import base64
import io
import os

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(ROOT, "src")
BUILD_DIR = os.path.join(ROOT, "build")

MAX_SIDE = 800

# 立绘素材：统一放在 media/pet 下（长边已限到 MAX_SIDE），随仓库一起走，
# 这样任何人 clone 下来都能重新生成 assets.py，不依赖本机的截图目录。
S = os.path.join(ROOT, "media", "pet")
SHEETS = [
    ("COVER_PNG", os.path.join(S, "cover.png")),
    ("READ_PNG", os.path.join(S, "read.png")),
    ("EAT_PNG", os.path.join(S, "eat.png")),
    ("BASKET_PLAY_PNG", os.path.join(S, "basket_play.png")),
    ("BASKET_FALL_PNG", os.path.join(S, "basket_fall.png")),
    ("BASKET_HAPPY_PNG", os.path.join(S, "basket_happy.png")),
    ("BASKET_ANGRY_PNG", os.path.join(S, "basket_angry.png")),
]

# 音效：常量名 <- build/audio 下的 PCM WAV
SOUNDS = [
    ("SOUND_OPEN_WAV", "open_intro.wav"),      # 启动：「欸，大狗！」
    ("SOUND_READ_WAV", "read.wav"),            # 读书：「哒哒哒哒哒」
    ("SOUND_EAT_WAV", "eat.wav"),              # 吃饭：「叫叫叫！」
    ("SOUND_BASKET_WAV", "basket.wav"),        # 打篮球：「大狗大狗」
]
AUDIO_DIR = os.path.join(BUILD_DIR, "audio")


def pack(path):
    """读入 -> 去无用 alpha -> 长边限幅 -> 无损重编码 PNG，返回 (bytes, 说明)。"""
    with Image.open(path) as im:
        im = im.convert("RGBA")
        note = []
        # 照片类截图 alpha 全 255 时直接丢掉 alpha 通道，省约 25% 体积
        alpha = im.getchannel("A")
        if alpha.getextrema() == (255, 255):
            im = im.convert("RGB")
            note.append("drop-alpha")
        w, h = im.size
        if max(w, h) > MAX_SIDE:
            s = MAX_SIDE / float(max(w, h))
            im = im.resize((max(1, int(round(w * s))), max(1, int(round(h * s)))), Image.LANCZOS)
            note.append("%dx%d->%dx%d" % (w, h, im.size[0], im.size[1]))
        buf = io.BytesIO()
        im.save(buf, format="PNG", optimize=True)
        return buf.getvalue(), " ".join(note)


def main():
    os.makedirs(BUILD_DIR, exist_ok=True)
    lines = [
        "# -*- coding: utf-8 -*-",
        '"""自动生成：内嵌素材。请勿手工修改，改动请编辑 tools/build_assets.py 后重新生成。"""',
        "",
    ]
    log = []
    for name, path in SHEETS:
        raw, note = pack(path)
        with Image.open(io.BytesIO(raw)) as im:
            log.append("%-17s <- %-34s %dx%d  %6.1f KB  %s"
                       % (name, os.path.basename(path), im.size[0], im.size[1],
                          len(raw) / 1024.0, note))
        lines.append("%s = %r" % (name, base64.b64encode(raw).decode("ascii")))
        lines.append("")

    # 图标：用封面图生成多尺寸 ico（居中裁成正方形，避免出现透明边）
    with Image.open(SHEETS[0][1]) as im:
        im = im.convert("RGBA")
        side = min(im.size)
        left = (im.size[0] - side) // 2
        top = (im.size[1] - side) // 2
        square = im.crop((left, top, left + side, top + side))
        ico_path = os.path.join(BUILD_DIR, "renyugou.ico")
        square.resize((256, 256), Image.LANCZOS).save(
            ico_path, format="ICO",
            sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
        )
    with open(ico_path, "rb") as f:
        lines.append("ICON_ICO = %r" % base64.b64encode(f.read()).decode("ascii"))
        lines.append("")
    log.append("ICON_ICO <- build/renyugou.ico")

    # 音效（PCM WAV，运行期交给 winsound 播）
    for name, fname in SOUNDS:
        path = os.path.join(AUDIO_DIR, fname)
        if not os.path.exists(path):
            log.append("%-17s !! 缺失，跳过：%s" % (name, path))
            continue
        with open(path, "rb") as f:
            raw = f.read()
        lines.append("%s = %r" % (name, base64.b64encode(raw).decode("ascii")))
        lines.append("")
        log.append("%-17s <- %-16s %6.1f KB" % (name, fname, len(raw) / 1024.0))

    out = os.path.join(SRC_DIR, "assets.py")
    os.makedirs(SRC_DIR, exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))
    log.append("wrote %s (%.1f KB)" % (out, os.path.getsize(out) / 1024.0))

    with open(os.path.join(BUILD_DIR, "_build_assets.log"), "w", encoding="utf-8") as f:
        f.write("\n".join(log))
    print("\n".join(log))


if __name__ == "__main__":
    main()
