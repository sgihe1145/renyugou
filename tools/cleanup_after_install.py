"""删除 Python 安装包与本次安装过程产生的临时探测日志（保留 _env_probe.txt 作为凭证）。"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGETS = [
    os.path.join("build", "python-3.13.15-amd64.exe"),  # 28MB 安装包，需要可随时重新下载
    os.path.join("build", "_pydetect.txt"),
    os.path.join("build", "_dl.txt"),
    os.path.join("build", "_install.txt"),
    os.path.join("build", "_verify_py.txt"),
    os.path.join("build", "_path_check.txt"),
    os.path.join("build", "_path_check2.txt"),
    os.path.join("build", "_x.txt"),
]

log = []
for rel in TARGETS:
    p = os.path.join(ROOT, rel)
    if not os.path.exists(p):
        continue
    try:
        size = os.path.getsize(p)
        os.remove(p)
        log.append("deleted %s (%.1f KB)" % (rel, size / 1024.0))
    except OSError as exc:
        log.append("FAILED %s -> %s" % (rel, exc))

out = os.path.join(ROOT, "build", "_cleanup_install.log")
with open(out, "w", encoding="utf-8") as f:
    f.write("\n".join(log) if log else "nothing to delete")
print("\n".join(log))
