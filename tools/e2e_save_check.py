# -*- coding: utf-8 -*-
"""真机端到端：启动 dist\\任禹狗.exe -> 关掉窗口 -> 检查 %LOCALAPPDATA%\\任禹狗\\save.json。

两阶段：
  阶段一  无存档启动 -> 退出 -> 应生成一份合法存档（验证「保存」路径）
  阶段二  塞入一份改过的存档 -> 启动 -> 退出 -> 存档应保留改过的数值
          （若读档没生效，数值会被写回 70/10 默认值，直接暴露）

结果写 build/_e2e_save.txt
"""
import ctypes
import json
import os
import subprocess
import sys
import time
from ctypes import wintypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXE = os.path.join(ROOT, "dist", "任禹狗.exe")
sys.path.insert(0, os.path.join(ROOT, "src"))
import app as A  # noqa: E402

# 本测试进程不是 DPI 感知的，窗口是 DPI 感知的：投递的鼠标坐标会被系统按显示缩放
# 虚拟化（实测 150% 屏上被乘 1.5）。所以每次点击都按「本进程看到的客户区 / 程序真实客户区」换算。

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.FindWindowW.restype = wintypes.HWND
user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]

save_dir = os.path.join(os.environ.get("LOCALAPPDATA", ""), "任禹狗")
save_path = os.path.join(save_dir, "save.json")

lines, fails = [], []


def check(label, got, want):
    ok = got == want
    if not ok:
        fails.append(label)
    lines.append("%-34s got=%-38s want=%-38s %s"
                 % (label, got, want, "OK" if ok else "FAIL"))


def read_save_file():
    try:
        with open(save_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def run_exe_and_close(wait=3.0, click=None):
    """启动 exe，等窗口出现，（可选）往窗口发一次鼠标点击，再发 WM_CLOSE。

    click = (client_x, client_y)；用 PostMessage 发 WM_LBUTTONDOWN/UP，
    窗口过程里的命中测试照常走，等于真的点了一下按钮。
    """
    proc = subprocess.Popen([EXE], cwd=os.path.dirname(EXE))
    hwnd, deadline = 0, time.time() + 20
    while time.time() < deadline:
        hwnd = user32.FindWindowW("RenYuGouWndCls", None)
        if hwnd:
            break
        time.sleep(0.2)
    if not hwnd:
        proc.kill()
        return "NO-WINDOW", None
    time.sleep(1.0)
    if click:
        # 把「程序真实客户区坐标」换算成本进程投递时要用的坐标
        rc = wintypes.RECT()
        user32.GetClientRect(hwnd, ctypes.byref(rc))
        scale = (rc.right / float(A.CLIENT_W)) if rc.right else 1.0
        lp = (int(round(click[1] * scale)) << 16) | int(round(click[0] * scale))
        user32.PostMessageW(hwnd, 0x0201, 1, lp)     # WM_LBUTTONDOWN
        time.sleep(0.15)
        user32.PostMessageW(hwnd, 0x0202, 0, lp)     # WM_LBUTTONUP
    time.sleep(wait)
    user32.PostMessageW(hwnd, 0x0010, 0, 0)          # WM_CLOSE
    try:
        rc = proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        rc = "TIMEOUT"
    return rc, read_save_file()


lines.append("exe: %s (%s MB)" % (EXE, round(os.path.getsize(EXE) / 1024.0 / 1024, 2)))
lines.append("存档: %s" % save_path)
lines.append("")

# ---------------- 阶段一：首次启动应生成存档
if os.path.exists(save_path):
    os.remove(save_path)
rc, data = run_exe_and_close()
check("阶段一 关闭后进程正常退出", rc, 0)
check("阶段一 退出后存档已生成", isinstance(data, dict), True)
if data:
    check("阶段一 会话数=1", data.get("sessions"), 1)
    check("阶段一 初始数值", data.get("stats"),
          {"mood": 70, "vitality": 80, "intimacy": 10, "intellect": 10, "stomach": 30})
    check("阶段一 有 saved_at", bool(data.get("saved_at")), True)

# ---------------- 阶段二：改过的存档必须被读回来
doctored = {
    "version": 1,
    "saved_at": "2026-01-01 00:00:00",
    "sessions": 5,
    "stats": {"mood": 42, "vitality": 7, "intimacy": 999, "intellect": 1234, "stomach": 88},
    "totals": {"read": 7, "eat": 3, "basket": 2},
    "history": [{"t": "01-01 09:00", "action": "read", "label": "读书",
                 "changes": "intellect+15", "stats": "mood=42"}],
    "cooldown_deadline": 0,
}
os.makedirs(save_dir, exist_ok=True)
with open(save_path, "w", encoding="utf-8") as f:
    json.dump(doctored, f, ensure_ascii=False)

rc2, data2 = run_exe_and_close()
check("阶段二 关闭后进程正常退出", rc2, 0)
if data2:
    check("阶段二 数值被读回（未被写回默认值）", data2.get("stats"), doctored["stats"])
    check("阶段二 会话数 5->6", data2.get("sessions"), 6)
    check("阶段二 累计次数保留",
          [data2["totals"].get(k) for k in ("read", "eat", "basket")], [7, 3, 2])
    check("阶段二 历史保留", len(data2.get("history") or []), 1)
    check("阶段二 无上限项未溢出", data2["stats"]["intellect"], 1234)
else:
    check("阶段二 能读出合法 JSON", False, True)

# 阶段三里再塞一份越界存档，验证夹取（不会算出负数/超上限）
bad = dict(doctored)
bad["stats"] = {"mood": 9999, "vitality": -50, "intimacy": 10, "intellect": 10, "stomach": 30}
with open(save_path, "w", encoding="utf-8") as f:
    json.dump(bad, f, ensure_ascii=False)
rc3, data3 = run_exe_and_close(wait=2.0)
if data3:
    check("阶段三 越界值被夹取", data3.get("stats"),
          {"mood": 100, "vitality": 0, "intimacy": 10, "intellect": 10, "stomach": 30})
else:
    check("阶段三 能读出合法 JSON", False, True)

# ---------------- 阶段四：真的点一下「读书」，验证结算与行动日志
with open(save_path, "w", encoding="utf-8") as f:
    json.dump({"version": 1, "saved_at": "", "sessions": 1,
               "stats": {"mood": 70, "vitality": 80, "intimacy": 10, "intellect": 10,
                         "stomach": 30},
               "totals": {"read": 0, "eat": 0, "basket": 0}, "history": [],
               "cooldown_deadline": 0}, f, ensure_ascii=False)
log_path = os.path.join(save_dir, "行动记录.txt")
if os.path.exists(log_path):
    os.remove(log_path)

# 「让任禹狗读书」按钮的客户端中心点：操作栏 x=24 + 内边距 20 + 半宽 180 = 224；y=100+48+26 = 174
rc4, data4 = run_exe_and_close(wait=6.0, click=(224, 174))
check("阶段四 关闭后进程正常退出", rc4, 0)
if data4:
    check("阶段四 读书结算已写入", data4.get("stats"),
          {"mood": 80, "vitality": 80, "intimacy": 15, "intellect": 25, "stomach": 30})
    check("阶段四 累计次数 read=1", (data4.get("totals") or {}).get("read"), 1)
    check("阶段四 历史有 1 条", len(data4.get("history") or []), 1)
    if data4.get("history"):
        check("阶段四 历史记录的动作", data4["history"][-1].get("action"), "read")
n_lines = 0
if os.path.exists(log_path):
    with open(log_path, "r", encoding="utf-8") as f:
        n_lines = len([x for x in f.read().splitlines() if x.strip()])
check("阶段四 行动记录.txt 有 1 行", n_lines, 1)
if n_lines:
    with open(log_path, "r", encoding="utf-8") as f:
        lines.append("      行动记录.txt: " + f.read().splitlines()[0])

# 还原成一份干净的存档（用户的任禹狗从初始状态开始）
with open(save_path, "w", encoding="utf-8") as f:
    json.dump({"version": 1, "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"), "sessions": 1,
               "stats": {"mood": 70, "vitality": 80, "intimacy": 10, "intellect": 10,
                         "stomach": 30},
               "totals": {"read": 0, "eat": 0, "basket": 0}, "history": [],
               "cooldown_deadline": 0}, f, ensure_ascii=False, indent=2)
if os.path.exists(log_path):
    os.remove(log_path)
lines.append("")
lines.append("已把存档与行动记录重置为初始状态，供正式使用。")

out = os.path.join(ROOT, "build", "_e2e_save.txt")
head = ["--- exe 真机存档端到端测试 ---", ""]
tail = ["", "结果：%d 项通过，%d 项失败"
        % (len([x for x in lines if x.endswith("OK")]), len(fails))]
for f in fails:
    tail.append("  FAIL " + f)
with open(out, "w", encoding="utf-8") as f:
    f.write("\n".join(head + lines + tail))
print("\n".join(tail))
sys.exit(1 if fails else 0)
