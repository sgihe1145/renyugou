"""探测本机 python.org Python 安装是否可被 PATH 正确解析，并实测 tkinter 开窗。

输出写入 build/_env_probe.txt（PowerShell 不回显 stdout）。
"""
import os
import subprocess
import sys
import winreg

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "build", "_env_probe.txt")
lines = []


def say(s=""):
    lines.append(str(s))


def reg_path(hive, key, name):
    try:
        with winreg.OpenKey(hive, key) as h:
            v, _ = winreg.QueryValueEx(h, name)
            return v
    except OSError:
        return ""


# 1. PATH 解析模拟（系统 PATH 在前，用户 PATH 在后，与 Windows 实际行为一致）
sys_path = reg_path(winreg.HKEY_LOCAL_MACHINE,
                    r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment", "Path")
usr_path = reg_path(winreg.HKEY_CURRENT_USER, "Environment", "Path")
full = [p for p in (sys_path + ";" + usr_path).split(";") if p.strip()]

say("--- PATH 中 python 命中顺序（新会话） ---")
found = 0
for d in full:
    for exe in ("python.exe", "python3.exe"):
        p = os.path.join(d, exe)
        if os.path.isfile(p) and os.path.getsize(p) > 0:
            found += 1
            say("[%d] %s" % (found, p))
            if found >= 3:
                break
    if found >= 3:
        break
if not found:
    say("未找到任何非 0 字节的 python.exe")

# 2. 真实解释器验证
PY = os.path.join(os.environ.get("LOCALAPPDATA", ""),
                  r"Programs\Python\Python313\python.exe")
say()
say("--- 解释器 ---")
say("path: %s" % PY)
say("exists: %s" % os.path.isfile(PY))
if os.path.isfile(PY):
    for args in (["-V"], ["-c", "import sys;print(sys.executable)"],
                 ["-c", "import tkinter;print('tkinter', tkinter.TkVersion)"],
                 ["-m", "pip", "--version"]):
        r = subprocess.run([PY] + args, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        say("$ python %s" % " ".join(args))
        say("  rc=%d" % r.returncode)
        if r.stdout.strip():
            say("  out: " + r.stdout.strip().replace("\n", " | "))
        if r.stderr.strip():
            say("  err: " + r.stderr.strip().replace("\n", " | "))

    # 3. 实测 tkinter 真的能开窗口（无头环境也能创建，只要不是服务会话）
    code = (
        "import tkinter as tk\n"
        "r = tk.Tk()\n"
        "r.title('probe')\n"
        "r.geometry('200x100+50+50')\n"
        "tk.Label(r, text='hello').pack()\n"
        "r.update_idletasks(); r.update()\n"
        "print('window ok', r.winfo_width(), r.winfo_height())\n"
        "r.destroy()\n"
    )
    r = subprocess.run([PY, "-c", code], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=60)
    say()
    say("--- tkinter 开窗实测 ---")
    say("rc=%d" % r.returncode)
    if r.stdout.strip():
        say("out: " + r.stdout.strip())
    if r.stderr.strip():
        say("err: " + r.stderr.strip())

with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print("\n".join(lines))
