# -*- coding: utf-8 -*-
"""存档端到端测试（不开窗）：模拟一次会话 -> 退出落盘 -> 重新打开读回。

结果写到 build/_persist_test.txt
"""
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import app as A  # noqa: E402

lines = []
fails = []


def check(label, got, want):
    ok = got == want
    if not ok:
        fails.append(label)
    lines.append("%-30s got=%-46s want=%-46s %s" % (label, got, want, "OK" if ok else "FAIL"))


def make(tmp):
    """造一个「用临时目录当存档目录」的 App 实例（不开窗）。"""
    a = A.App()
    a.persist = True
    a.save_path = os.path.join(tmp, A.SAVE_FILE)
    a.action_log_path = os.path.join(tmp, A.ACTION_LOG_FILE)
    return a


tmp = tempfile.mkdtemp(prefix="ryg_persist_")

# ---- 第一次会话
a = make(tmp)
a._load_state()
check("首次启动：无存档", a.sessions, 1)
check("首次启动：初始数值", a.stats.dump(),
      "mood=70 vitality=80 intimacy=10 intellect=10 stomach=30")

a._settle("read")
a._settle("eat")
a._settle("basket_happy")
a.cooldown_until = A._now() + 45000          # 模拟刚打完球，冷却还剩 45 秒
a._save_state("exit")

# 心情 70 +10(读书) +25(打球开心) = 105 -> 夹到上限 100
expect_after = "mood=100 vitality=70 intimacy=35 intellect=25 stomach=50"
check("三次互动后数值", a.stats.dump(), expect_after)
check("累计次数", [a.totals["read"], a.totals["eat"], a.totals["basket"]], [1, 1, 1])
check("历史条数", len(a.history), 3)
check("存档文件已生成", os.path.exists(os.path.join(tmp, A.SAVE_FILE)), True)
log_txt = os.path.join(tmp, A.ACTION_LOG_FILE)
n_log = 0
if os.path.exists(log_txt):
    with open(log_txt, "r", encoding="utf-8") as f:
        n_log = len([x for x in f.read().splitlines() if x.strip()])
check("行动记录.txt 行数", n_log, 3)

# ---- 第二次会话（重新打开程序）
b = make(tmp)
b._load_state()
check("重开：会话数递增", b.sessions, 2)
check("重开：数值恢复", b.stats.dump(), expect_after)
check("重开：累计次数恢复", [b.totals["read"], b.totals["eat"], b.totals["basket"]], [1, 1, 1])
check("重开：历史恢复", len(b.history), 3)
check("重开：上次行动", b.last_action.split(" · ")[0], "打篮球（开心）")
left = b._cooldown_left()
check("重开：冷却继续倒计时(40~46s)", 40000 < left < 46000, True)

# ---- 第三次：吃饭解除冷却 + 再存
b._cancel_cooldown("eat")
check("解除冷却后剩余", b._cooldown_left(), 0)
b._save_state("exit")
c = make(tmp)
c._load_state()
check("重开：冷却已解除", c._cooldown_left(), 0)

# ---- 自检模式不得写真实存档
d = A.App(snapshot_dir=os.path.join(tmp, "snap"))
check("自检模式禁用存档", d.persist, False)
check("自检模式不落盘", d._save_state("x"), False)
check("自检模式未污染存档", os.path.exists(os.path.join(tmp, "snap")), False)

# ---- 称号：解锁、排序、称号话以及存档往返
g = make(tmp)
check("初始无称号", g._current_title(), None)
g._settle("read")
check("首次互动解锁称号", g.titles, ["newbie"])
g.titles = ["newbie", "keeper", "soulmate"]
check("当前称号取最高阶", g._current_title(), "一生挚友")
check("称号行文字", g._title_note(), "称号 · 一生挚友（3/%d）" % len(A.TITLE_DEFS))
check("状态行含称号", "称号：一生挚友" in g._save_hint(), True)
g._save_state("title")
g2 = make(tmp)
g2._load_state()
check("称号存档往返", g2.titles, ["newbie", "keeper", "soulmate"])
try:
    os.remove(os.path.join(tmp, A.SAVE_FILE))
except OSError:
    pass

# ---- 标题右侧存档状态行：实测文字宽度，不能顶出窗口
import ctypes                                    # noqa: E402
from ctypes import wintypes                      # noqa: E402


class _SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]


A.gdi32.GetTextExtentPoint32W.argtypes = [wintypes.HDC, wintypes.LPCWSTR, ctypes.c_int,
                                          ctypes.POINTER(_SIZE)]   # 注意在 gdi32 里
A.gdi32.GetTextExtentPoint32W.restype = wintypes.BOOL


def hint_width(obj, text):
    obj._build_fonts()
    dc = A.user32.GetDC(None)
    A.gdi32.SelectObject(dc, obj.fonts["hint"])
    sz = _SIZE()
    A.gdi32.GetTextExtentPoint32W(dc, text, len(text), ctypes.byref(sz))
    return sz.cx


avail = A.CLIENT_W - 2 * A.MARGIN
for label, sess, totals, last, cd in (
        ("首次启动", 1, {"read": 0, "eat": 0, "basket": 0}, "", 0),
        ("累计很多次", 128, {"read": 88, "eat": 66, "basket": 33},
         "打篮球（开心） · 12-31 23:59", 0),
        ("冷却中", 9, {"read": 12, "eat": 8, "basket": 5},
         "打篮球（摔倒） · 12-31 23:59", 45000)):
    e = A.App()
    e.sessions, e.totals, e.last_action = sess, totals, last
    e.cooldown_until = (A._now() + cd) if cd else 0
    text = e._save_hint()
    w = hint_width(e, text)
    check("状态行宽度[%s] 不超宽" % label, w <= avail, True)
    lines.append("      %s: %dpx / 可用 %dpx  |  %s" % (label, w, avail, text))

shutil.rmtree(tmp, ignore_errors=True)

out = os.path.join(ROOT, "build", "_persist_test.txt")
os.makedirs(os.path.dirname(out), exist_ok=True)
head = ["--- 存档端到端测试 ---", ""]
tail = ["", "结果：%d 项通过，%d 项失败" % (len(lines) - len(fails), len(fails))]
for f in fails:
    tail.append("  FAIL " + f)
text = "\n".join(head + lines + tail)
with open(out, "w", encoding="utf-8") as f:
    f.write(text)
print(text)
sys.exit(1 if fails else 0)
