# -*- coding: utf-8 -*-
"""重新构建 任禹狗.exe。

用法（在项目根目录，用带 PyInstaller 的 Python 解释器运行）：

    <python> tools/build_exe.py

流程：
  1. tools/build_assets.py  重新把素材内嵌进 src/assets.py，并生成 build/renyugou.ico
  2. PyInstaller 单文件打包到 dist/任禹狗.exe

想换立绘：改 tools/build_assets.py 的 SHEETS 路径，然后重跑本脚本即可。
想换启动图标：SHEETS 里的第一条（COVER_PNG）同时用来生成 exe 图标，换它即可。
想改音效：四段音效已经裁好并随仓库提交在 media/audio 下，直接替换同名 PCM WAV 即可
          （22050Hz / 单声道 / 16bit），再跑本脚本；不需要本机装 ffmpeg。
          片段名与触发时机在 src/app.py 的 SOUND_WAV / play_sound()。
想加互动按钮：改 src/app.py 的 BTN_DEFS（文件上部），补 MSG_TEXTS / CAPTIONS / MSG_COLORS，
            若要加减数值再补一条 DELTAS；布局常量 OPS_CARD 高度与 BTN_GAP 按行数调。
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
BUILD = os.path.join(ROOT, "build")


def run(cmd):
    print(">> " + " ".join(cmd))
    subprocess.check_call(cmd)


def main():
    os.makedirs(BUILD, exist_ok=True)
    run([sys.executable, os.path.join(ROOT, "tools", "build_assets.py")])
    # 注意：不要用 --clean，也不要自己 rmtree build/pyi。
    # 沙箱有「批量删除保护」（单次删除超过 50 个文件即拒绝，且会直接中断进程），
    # 而 build/pyi 累积后会远超这个数。PyInstaller 不带 --clean 时会按时间戳重算缓存，
    # 源文件变了照样能正确重打包。
    run([sys.executable, "-m", "PyInstaller",
         "--noconfirm", "--onefile", "--windowed",
         "--name", "任禹狗",
         "--icon", os.path.join(BUILD, "renyugou.ico"),
         "--distpath", os.path.join(ROOT, "dist"),
         "--workpath", os.path.join(BUILD, "pyi"),
         "--specpath", BUILD,
         # 本解释器里还装着 faster-whisper 等开发工具，numpy 会被 PIL 的 hook 顺带拉进来
         # （+12MB），程序本身用不到，直接排除。
         "--exclude-module", "numpy",
         "--exclude-module", "ctranslate2",
         "--exclude-module", "onnxruntime",
         "--exclude-module", "faster_whisper",
         "--exclude-module", "av",
         "--exclude-module", "tokenizers",
         "--exclude-module", "huggingface_hub",
         os.path.join(SRC, "app.py")])
    exe = os.path.join(ROOT, "dist", "任禹狗.exe")
    size = os.path.getsize(exe) / 1024.0 / 1024.0 if os.path.exists(exe) else 0
    print("\n完成: %s (%.2f MB)" % (exe, size))


if __name__ == "__main__":
    main()
