# -*- coding: utf-8 -*-
"""清理开发过程中的临时日志/探测文件（保留可复现的构建与校验产物）。"""
import os
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGETS = [
    "_ls.txt", "_probe.txt", "_probe2.txt", "_probe3.txt",
    os.path.join("tools", "_assets_report.txt"),
    os.path.join("build", "_scaffold_test"),
    os.path.join("build", "_run1.log"), os.path.join("build", "_run1_u8.txt"),
    os.path.join("build", "_run2.log"), os.path.join("build", "_run3.log"),
    os.path.join("build", "_chk.txt"), os.path.join("build", "_pip.log"),
    os.path.join("build", "_pip_u8.txt"), os.path.join("build", "_snap_log_u8.txt"),
    os.path.join("build", "_verify_console.txt"), os.path.join("build", "_build_assets.log"),
    os.path.join("build", "_exe_run.log"), os.path.join("build", "_snapshot.log"),
    os.path.join("build", "_del.txt"), os.path.join("build", "_tree.txt"),
    # 2026-09-15 扩展状态栏/打篮球时新增的临时文件
    os.path.join("build", "_new_assets.txt"), os.path.join("build", "_assets.log"),
    os.path.join("build", "_selftest_console.txt"), os.path.join("build", "_run.log"),
    os.path.join("build", "_snap_u8.txt"), os.path.join("build", "_verify_rc.txt"),
    os.path.join("build", "_verify_tail.txt"), os.path.join("build", "_exe_rc.txt"),
    os.path.join("build", "_after.txt"), os.path.join("build", "_x.txt"),
    os.path.join("build", "_pydetect.txt"), os.path.join("build", "_dl.txt"),
    os.path.join("build", "_install.txt"), os.path.join("build", "_verify_py.txt"),
    os.path.join("build", "_path_check.txt"), os.path.join("build", "_path_check2.txt"),
    os.path.join("build", "_z.txt"),
    os.path.join("tools", "_cleanup2.py"),
    os.path.join("tools", "_cover_report.txt"),
    # 2026-09-15 换立绘 + 加音效时新增的临时文件
    os.path.join("build", "_fw.log"), os.path.join("build", "_transcribe_console.txt"),
    os.path.join("build", "_model_probe.txt"), os.path.join("build", "_models"),
    os.path.join("build", "_frames.log"), os.path.join("build", "_subs.log"),
    os.path.join("build", "_full.log"), os.path.join("build", "_subtl_console.txt"),
    os.path.join("build", "_big.log"), os.path.join("build", "_fine.log"),
    os.path.join("build", "_fine2.log"), os.path.join("build", "_transcribe.log"),
    os.path.join("build", "_cut_console.txt"), os.path.join("build", "_build.log"),
    os.path.join("build", "_build2.log"), os.path.join("build", "_build3.log"),
    os.path.join("build", "_build4.log"), os.path.join("build", "_mp3.log"),
    os.path.join("build", "_dl_audio.log"), os.path.join("build", "_dl_video.log"),
    os.path.join("build", "_ff.log"), os.path.join("build", "_yt.log"),
    os.path.join("build", "_probe_media.txt"), os.path.join("build", "_transcode.log"),
    os.path.join("build", "_subtitle_timeline.txt"), os.path.join("build", "_cut_audio.log"),
    os.path.join("build", "_assets_u8.txt"), os.path.join("build", "_selftest_u8.txt"),
    os.path.join("build", "_verify_rc.txt"), os.path.join("build", "_final.txt"),
    os.path.join("build", "_cleanup_u8.txt"), os.path.join("build", "_transcribe_console.txt"),
    os.path.join("build", "_models"),
    # 2026-09-15 加本地存档时新增的临时文件
    os.path.join("build", "_persist_console.txt"), os.path.join("build", "_persist_rc.txt"),
    os.path.join("build", "_snap_u8.txt"),
    # exe 自检会在 exe 同目录写一份结果，交付目录不留它
    os.path.join("dist", "_selftest.txt"),
    # 点击坐标探针（DPI 虚拟化排查用，结论已写进 skill）
    os.path.join("tools", "_probe_click.py"),
    os.path.join("build", "_probe_click.txt"), os.path.join("build", "_probe_click_u8.txt"),
    os.path.join("build", "_probe_console.txt"), os.path.join("build", "_probe_rc.txt"),
    os.path.join("build", "_click_debug.log"), os.path.join("build", "_diag.txt"),
    os.path.join("build", "_e2e_console.txt"),
]

# 这些只删目录里的图，且目录本身保留（字幕抽帧图，数量多，沙箱可能拒绝批量删除）
DIR_TARGETS = [
    os.path.join("build", "frames"),
    os.path.join("build", "subs"),
]

done, failed = [], []
for rel in TARGETS:
    p = os.path.join(ROOT, rel)
    if not os.path.exists(p):
        continue
    try:
        shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
        done.append(rel)
    except OSError as exc:
        failed.append("%s -> %s" % (rel, exc))

for rel in DIR_TARGETS:
    p = os.path.join(ROOT, rel)
    if not os.path.isdir(p):
        continue
    for name in os.listdir(p):
        try:
            os.remove(os.path.join(p, name))
            done.append(os.path.join(rel, name))
        except OSError as exc:
            failed.append("%s/%s -> %s" % (rel, name, exc))
            break                      # 被沙箱拦就停手，剩下的留着不影响交付

with open(os.path.join(ROOT, "build", "_cleanup.log"), "w", encoding="utf-8") as f:
    f.write("removed:\n" + "\n".join(done) + "\nfailed:\n" + "\n".join(failed) + "\n")
