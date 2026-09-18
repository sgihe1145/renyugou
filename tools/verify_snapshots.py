# -*- coding: utf-8 -*-
"""对自检截图做像素级校验 + 对自检日志做数值断言。

覆盖：
  1. 立绘位置/尺寸/内容（与期望素材等比缩放结果比对平均绝对差）
  2. 收起/升起过渡帧确实处于中间高度
  3. 状态栏五条进度条的实际填充宽度（反推数值是否正确落到界面上）
  4. 三个按钮的可用/禁用颜色（忙碌灰、打球冷却灰、解除后恢复）
  5. 复位一致性：立绘卡片区与系统提示区分别比对
  6. 忙碌中点击后画面零变化
  7. 自检日志里的数值结算序列、冷却事件、拒绝重复点击
"""
import base64
import io
import os
import sys

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAP = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "build", "snap")
OUT = os.path.join(os.path.dirname(SNAP.rstrip("\\/")),
                   "_verify_" + os.path.basename(SNAP.rstrip("\\/")) + ".txt")
sys.path.insert(0, os.path.join(ROOT, "src"))
import assets  # noqa: E402

CLIENT_W, CLIENT_H = 1060, 720

PET_STAGE = (460, 116, 556, 410)
STAGE_BOTTOM = PET_STAGE[1] + PET_STAGE[3]           # 526
STAGE_BG = (0xF7, 0xF9, 0xFC)
PET_FIT = (540, 405)

REGION_PET = (440, 100, 596, 472)      # 立绘卡片
REGION_MSG = (24, 588, 1012, 108)      # 系统提示条（整体）
REGION_MSG_TEXT = (40, 632, 720, 40)   # 提示条内实际写字的这一行（比较文案用）

BTN_X, BTN_Y0, BTN_W, BTN_H = 44, 148, 360, 52
BTN_GAP = 14
BTN_Y = [BTN_Y0 + i * (BTN_H + BTN_GAP) for i in range(3)]

STAT_BAR_X, STAT_BAR_W = 110, 176
STAT_ROW0, STAT_ROW_H = 430, 27
BAR_Y_OFF, BAR_H = 10, 8

COL_GRAY = (0xE9, 0xEC, 0xEF)          # 禁用底
COL_TEAL = (0x17, 0x9A, 0x8A)          # 打篮球基色

STAT_KEYS = ["mood", "vitality", "intimacy", "intellect", "stomach"]
STAT_RGB = {
    "mood": (0xE0, 0x5A, 0x7E),
    "vitality": (0x35, 0xA8, 0x6B),
    "intimacy": (0x8B, 0x5C, 0xE0),
    "intellect": (0x2F, 0x6F, 0xEB),
    "stomach": (0xE0, 0x7B, 0x39),
}

IMG_KEYS = [
    ("cover", assets.COVER_PNG),
    ("read", assets.READ_PNG),
    ("eat", assets.EAT_PNG),
    ("basket_play", assets.BASKET_PLAY_PNG),
    ("basket_fall", assets.BASKET_FALL_PNG),
    ("basket_happy", assets.BASKET_HAPPY_PNG),
    ("basket_angry", assets.BASKET_ANGRY_PNG),
]

# 每张截图在那一刻应当显示的立绘；None = 过渡帧（另行断言高度）
# 注意：20~23 这几张故意留空 —— 它们上面叠着气泡/爱心/抖动，
# 整体比对必然有差，它们由下面「5.5 摸摸头互动」专门断言。
SHOT_PET = {
    "01_idle": "cover",
    "02_read_collapse": None,
    "03_read_rise": None,
    "04_read_hold": "read",
    "05_after_busy_click": "read",
    "06_read_hold_late": "read",
    "07_read_back": "cover",
    "08_eat_hold": "eat",
    "09_eat_back": "cover",
    "10_basket_play": "basket_play",
    "11_basket_fall": "basket_fall",
    "12_after_busy_click": "basket_fall",
    "13_basket_back_gray": "cover",
    "14_cooldown_click": "cover",
    "15_after_eat_cancel": "cover",
    "16_basket_happy": "basket_happy",
    "17_rest_gray": "cover",
    "18_after_cooldown": "cover",
    "19_basket_angry": "basket_angry",
}

# 每张截图时刻的期望数值（与 app.py 的 DELTAS / 自检时间表一致）：心情 活力 亲密度 智力 胃袋
# 摸头不产 ±N 之外的结算：到读书前共 2 次生效（第 2 次被 600ms 节流挡掉），各 +1
SHOT_STATS = {
    "01_idle": (70, 80, 10, 10, 30),
    "20_pet_hover": (70, 80, 10, 10, 30),
    "21_pet_touch": (71, 80, 11, 10, 30),
    "22_pet_combo": (72, 80, 12, 10, 30),
    "23_pet_settled": (72, 80, 12, 10, 30),
    "02_read_collapse": (82, 80, 17, 25, 30),
    "03_read_rise": (82, 80, 17, 25, 30),
    "04_read_hold": (82, 80, 17, 25, 30),
    "05_after_busy_click": (82, 80, 17, 25, 30),
    "06_read_hold_late": (82, 80, 17, 25, 30),
    "07_read_back": (82, 80, 17, 25, 30),
    "08_eat_hold": (82, 80, 17, 25, 50),
    "09_eat_back": (82, 80, 17, 25, 50),
    "10_basket_play": (82, 80, 17, 25, 50),
    "11_basket_fall": (52, 65, 27, 25, 50),
    "12_after_busy_click": (52, 65, 27, 25, 50),
    "13_basket_back_gray": (52, 65, 27, 25, 50),
    "14_cooldown_click": (52, 65, 27, 25, 50),
    "15_after_eat_cancel": (52, 65, 27, 25, 70),
    "16_basket_happy": (77, 55, 47, 25, 70),
    "17_rest_gray": (77, 55, 47, 25, 70),
    "18_after_cooldown": (77, 55, 47, 25, 70),
    "19_basket_angry": (67, 45, 62, 25, 70),
}

# 每张截图时刻「打篮球」按钮应为灰（True）还是可用色（False）；未列出的不检查
SHOT_BASKET_GRAY = {
    "02_read_collapse": True,      # 忙碌中：全部按钮灰
    "04_read_hold": True,
    "08_eat_hold": True,
    "10_basket_play": True,
    "11_basket_fall": True,
    "12_after_busy_click": True,
    "13_basket_back_gray": True,   # 冷却中
    "14_cooldown_click": True,     # 冷却中点击后仍灰
    "15_after_eat_cancel": False,  # 吃饭已解除冷却 -> 恢复可用
    "16_basket_happy": True,
    "17_rest_gray": True,
    "18_after_cooldown": False,    # 冷却自然到期 -> 解锁
    "19_basket_angry": True,
}

ALL_SHOTS = ["01_idle", "20_pet_hover", "21_pet_touch", "22_pet_combo", "23_pet_settled",
             "02_read_collapse", "03_read_rise", "04_read_hold",
             "05_after_busy_click", "06_read_hold_late", "07_read_back",
             "08_eat_hold", "09_eat_back", "10_basket_play", "11_basket_fall",
             "12_after_busy_click", "13_basket_back_gray", "14_cooldown_click",
             "15_after_eat_cancel", "16_basket_happy", "17_rest_gray",
             "18_after_cooldown", "19_basket_angry"]

# 摸摸头相关截图的像素断言
HOVER_SHOT = "20_pet_hover"                     # 悬停：立绘头顶应出现气泡
TOUCH_SHOT = "21_pet_touch"                     # 摸一下：抖动 + 爱心
COMBO_SHOT = "22_pet_combo"                     # 连点：爱心更多、吐槽换档
SETTLED_SHOT = "23_pet_settled"                 # 粒子散尽后回到稳态

HEART_RGB = [(0xF2, 0x6B, 0x9C), (0xFF, 0x94, 0xB8),
             (0xE8, 0x5A, 0x86), (0xF7, 0xB2, 0xC8)]
REGION_STAGE = (460, 116, 556, 410)             # 立绘舞台，爱心就飘在这里
REGION_ABOVE_PET = (460, 126, 556, 130)         # 立绘头顶那块，气泡固定落在这一带
REGION_STAT_INTIMACY = (360, 486, 46, 22)       # 亲密度那一行右侧的 ±N 浮标

# 忙碌中点击后，画面必须与点击前逐像素一致
NOOP_PAIRS = [("05_after_busy_click", "04_read_hold"),
              ("12_after_busy_click", "11_basket_fall")]

# 提示文字应当不同的对照
MSG_DIFF_PAIRS = [("04_read_hold", "01_idle"),
                  ("08_eat_hold", "01_idle"),
                  ("11_basket_fall", "01_idle"),
                  ("14_cooldown_click", "01_idle"),
                  ("14_cooldown_click", "13_basket_back_gray"),
                  ("19_basket_angry", "01_idle")]

EXPECT_STATS_SEQ = [
    "mood=70 vitality=80 intimacy=10 intellect=10 stomach=30",
    "mood=82 vitality=80 intimacy=17 intellect=25 stomach=30",
    "mood=82 vitality=80 intimacy=17 intellect=25 stomach=50",
    "mood=52 vitality=65 intimacy=27 intellect=25 stomach=50",
    "mood=52 vitality=65 intimacy=27 intellect=25 stomach=70",
    "mood=77 vitality=55 intimacy=47 intellect=25 stomach=70",
    "mood=67 vitality=45 intimacy=62 intellect=25 stomach=70",
]

# 自检流程只够把「初次见面」打出来；更高阶称号的判定由 app.py 的纯逻辑自检覆盖
EXPECT_TITLES = [
    "初次见面",     # 第 1 次读书
]

EXPECT_LOGS = [
    "action=read",
    "action=basket outcome=fall",
    "action=basket outcome=happy",
    "action=basket outcome=angry",
    "ignored=read(busy)",
    "ignored=basket(busy)",
    "ignored=basket(cooldown",
    "cooldown start=8000ms",
    "cooldown cancelled by eat",
    "cooldown expired -> basket unlocked",
    "sound=open",
    "sound=read",
    "sound=eat",
    "sound=basket",
]

# 音效播放次数：启动 1 次 + 摸头生效 2 次 = open 3；读书 1 次；吃饭 2 次（含解除冷却那次）；打球 3 次
EXPECT_SOUND_COUNTS = {
    "sound=open": 3,
    "sound=read": 1,
    "sound=eat": 2,
    "sound=basket": 3,
}

# 自检模式下必须禁用真实存档，否则每次跑自检数值都不是初始值
EXPECT_LOGS.append("save=disabled(自检模式)")

# 摸摸头：节流日志 + 称号解锁日志
EXPECT_LOGS.append("pet ignored(throttle")
for _name in EXPECT_TITLES:
    EXPECT_LOGS.append("title unlocked")
    EXPECT_LOGS.append(_name)

# 任何播放失败/缺失都不允许出现
FORBID_LOGS = ["MISSING", "FAILED", "SKIPPED", "WRITE-FAILED"]

fails = []


def check(cond, text):
    if not cond:
        fails.append(text)
    return cond


def flatten(im):
    base = Image.new("RGBA", im.size, (255, 255, 255, 255))
    return Image.alpha_composite(base, im.convert("RGBA")).convert("RGB")


def fit(im, box):
    w, h = im.size
    s = min(box[0] / float(w), box[1] / float(h))
    return im.resize((max(1, int(round(w * s))), max(1, int(round(h * s)))), Image.LANCZOS)


EXPECT = {}
for key, b64 in IMG_KEYS:
    im = fit(flatten(Image.open(io.BytesIO(base64.b64decode(b64)))), PET_FIT)
    EXPECT[key] = (im, im.size[0], im.size[1], STAGE_BOTTOM - im.size[1])


def img_top(img):
    """在舞台区自上而下找到立绘上边缘（与舞台底色差异明显的首行）。"""
    px = img.load()
    for y in range(PET_STAGE[1], STAGE_BOTTOM):
        diff = 0
        for x in range(PET_STAGE[0] + 20, PET_STAGE[0] + PET_STAGE[2] - 20, 4):
            p = px[x, y]
            if abs(p[0] - STAGE_BG[0]) + abs(p[1] - STAGE_BG[1]) + abs(p[2] - STAGE_BG[2]) > 45:
                diff += 1
        if diff >= 8:
            return y
    return None


def mad(a, b, step=37):
    """平均绝对差。小区域（提示文字）用 step=1 密集采样，否则稀疏采样即可。"""
    if a.size != b.size:
        return -1
    sa = a.tobytes()
    sb = b.tobytes()
    n = len(sa) // step + 1
    return sum(abs(sa[i] - sb[i]) for i in range(0, len(sa), step)) / float(n)


def crop(img, rect):
    x, y, w, h = rect
    return img.crop((x, y, x + w, y + h))


def avg_color(img, rect):
    x, y, w, h = rect
    px = img.load()
    r = g = b = 0
    n = 0
    for xx in range(x, x + w, 3):
        for yy in range(y, y + h, 3):
            p = px[xx, yy]
            r += p[0]; g += p[1]; b += p[2]; n += 1
    return (r // n, g // n, b // n)


def ink(img, rect):
    """区域内「有色像素」数量，用来判断提示文字是不是真的换了。"""
    x, y, w, h = rect
    px = img.load()
    n = 0
    for xx in range(x, x + w, 2):
        for yy in range(y, y + h, 2):
            p = px[xx, yy]
            if p[0] + p[1] + p[2] < 700:
                n += 1
    return n


def dist(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[2] - b[2])


def bar_fill(img, stat_key, row_idx):
    """量出某条进度条实际填充了多少像素（按状态项颜色找最右匹配点）。"""
    px = img.load()
    y = STAT_ROW0 + row_idx * STAT_ROW_H + BAR_Y_OFF + BAR_H // 2
    ref = STAT_RGB[stat_key]
    last = 0
    for x in range(STAT_BAR_X, STAT_BAR_X + STAT_BAR_W + 8):
        p = px[x, y]
        if dist(p, ref) <= 90:
            last = x - STAT_BAR_X + 1
    return last


def heart_pixels(img, rect=REGION_STAGE, tol=28):
    """区域里「爱心色」像素数。立绘本身也有偏粉的地方，所以一律取相对空闲帧的增量。"""
    x, y, w, h = rect
    px = img.load()
    n = 0
    for xx in range(x, x + w, 2):
        for yy in range(y, y + h, 2):
            p = px[xx, yy]
            if any(dist(p, c) <= tol for c in HEART_RGB):
                n += 1
    return n


def bubble_ink(img, rect=REGION_ABOVE_PET):
    """立绘头顶区域里的「气泡白」像素数：有气泡时应该是一大片纯白。"""
    x, y, w, h = rect
    px = img.load()
    n = 0
    for xx in range(x, x + w, 2):
        for yy in range(y, y + h, 2):
            p = px[xx, yy]
            if p[0] > 246 and p[1] > 246 and p[2] > 246:
                n += 1
    return n


def region_mad(img_a, img_b, rect):
    return mad(crop(img_a, rect), crop(img_b, rect))


lines = []
imgs = {}
for n in ALL_SHOTS:
    p = os.path.join(SNAP, n + ".png")
    if os.path.exists(p):
        imgs[n] = Image.open(p).convert("RGB")
    else:
        lines.append("%s MISSING" % n)
lines.append("截图数量：%d / %d" % (len(imgs), len(ALL_SHOTS)))
check(len(imgs) == len(ALL_SHOTS), "截图数量不足")
lines.append("画布尺寸：" + (str(imgs[ALL_SHOTS[0]].size) if imgs else "n/a"))
lines.append("")
lines.append("期望立绘尺寸/上边缘: " + ", ".join(
    "%s=%dx%d top=%d" % (k, v[1], v[2], v[3]) for k, v in EXPECT.items()))
lines.append("")

# ---------- 1. 立绘位置/内容 ----------
lines.append("--- 立绘（上边缘 / 与期望图的平均绝对差 mad，<3 视为一致）---")
ok_pet = 0
for n in ALL_SHOTS:
    im = imgs.get(n)
    if im is None:
        continue
    top = img_top(im)
    h = (STAGE_BOTTOM - top) if top else 0
    key = SHOT_PET.get(n)
    if key:
        exp_img, ew, eh, etop = EXPECT[key]
        ex = PET_STAGE[0] + (PET_STAGE[2] - ew) // 2
        got = im.crop((ex, etop, ex + ew, etop + eh))
        m = mad(got, exp_img)
        good = (abs(top - etop) <= 2) and m < 3.0
        ok_pet += 1 if good else 0
        check(good, "%s 立绘不符：expect=%s top=%d mad=%.2f" % (n, key, etop, m))
        lines.append("%-22s top=%-5s h=%-5s expect=%-12s mad=%.2f %s"
                     % (n, top, h, key, m, "OK" if good else "FAIL"))
    else:
        lines.append("%-22s top=%-5s h=%-5s （过渡帧）" % (n, top, h))
lines.append("立绘比对通过：%d / %d" % (ok_pet, sum(1 for v in SHOT_PET.values() if v)))

# ---------- 2. 过渡帧高度 ----------
lines.append("")
lines.append("--- 过渡帧（应处于中间高度，既不是 0 也不是满高）---")
for n, key in (("02_read_collapse", "cover"), ("03_read_rise", "read")):
    if n not in imgs:
        continue
    full = EXPECT[key][2]
    top = img_top(imgs[n])
    h = (STAGE_BOTTOM - top) if top else 0
    ok = full * 0.4 < h < full * 0.98
    check(ok, "%s 过渡高度异常 h=%d full=%d" % (n, h, full))
    lines.append("%s h=%d（满高 %d，40%%~98%% 区间内）%s" % (n, h, full, "OK" if ok else "FAIL"))

# ---------- 3. 状态栏进度条 ----------
lines.append("")
lines.append("--- 状态栏进度条填充宽度（期望 = 176 * 数值 / 100，容差 ±4px）---")
ok_bar = ok_bar_n = 0
for n in ALL_SHOTS:
    im = imgs.get(n)
    if im is None or n not in SHOT_STATS:
        continue
    got, bad = [], []
    for i, key in enumerate(STAT_KEYS):
        v = SHOT_STATS[n][i]
        want = int(round(STAT_BAR_W * v / 100.0))
        g = bar_fill(im, key, i)
        got.append("%s=%d/%d" % (key, g, want))
        ok_bar_n += 1
        if abs(g - want) <= 4:
            ok_bar += 1
        else:
            bad.append("%s(%d!=%d)" % (key, g, want))
    check(not bad, "%s 进度条不符：%s" % (n, ",".join(bad)))
    lines.append("%-22s %s%s" % (n, " ".join(got), ("  <- " + ",".join(bad)) if bad else ""))
lines.append("进度条断言通过：%d / %d" % (ok_bar, ok_bar_n))

# ---------- 4. 按钮状态 ----------
lines.append("")
lines.append("--- 按钮颜色（取样避开文字）---")
ok_btn = ok_btn_n = 0
for n in ALL_SHOTS:
    im = imgs.get(n)
    if im is None:
        continue
    samples = []
    for i, name in enumerate(("read", "eat", "basket")):
        c = avg_color(im, (BTN_X + 16, BTN_Y[i] + 6, 90, BTN_H - 12))
        samples.append("%s=%s" % (name, "grey" if dist(c, COL_GRAY) < 40 else "brand"))
    note = ""
    if n in SHOT_BASKET_GRAY:
        c = avg_color(im, (BTN_X + 16, BTN_Y[2] + 6, 90, BTN_H - 12))
        got_gray = dist(c, COL_GRAY) < 40
        ok_btn_n += 1
        if got_gray == SHOT_BASKET_GRAY[n]:
            ok_btn += 1
        else:
            note = "  <- 打篮球应为%s，实际%s" % ("灰" if SHOT_BASKET_GRAY[n] else "可用色",
                                                  "灰" if got_gray else "可用色")
            check(False, "%s 打篮球按钮状态错误" % n)
    lines.append("%-22s %s%s" % (n, " ".join(samples), note))
lines.append("按钮状态断言通过：%d / %d" % (ok_btn, ok_btn_n))

# ---------- 5. 复位一致性 / 零变化 / 提示文字差异 ----------
lines.append("")
lines.append("--- 复位一致性：立绘区 + 提示区分别比对（应均为 0.000）---")
for n in ("07_read_back", "09_eat_back", "18_after_cooldown"):
    if n in imgs and "01_idle" in imgs:
        p = mad(crop(imgs[n], REGION_PET), crop(imgs["01_idle"], REGION_PET))
        m = mad(crop(imgs[n], REGION_MSG), crop(imgs["01_idle"], REGION_MSG))
        ok = p == 0 and m == 0
        check(ok, "%s 复位不一致 pet=%s msg=%s" % (n, p, m))
        lines.append("%-22s vs 01_idle  pet=%.3f  msg=%.3f  %s"
                     % (n, p, m, "OK" if ok else "FAIL"))

lines.append("")
lines.append("--- 忙碌中点击必须零变化（与点击前一帧逐像素一致）---")
for a, b in NOOP_PAIRS:
    if a in imgs and b in imgs:
        p = mad(crop(imgs[a], REGION_PET), crop(imgs[b], REGION_PET))
        m = mad(crop(imgs[a], REGION_MSG), crop(imgs[b], REGION_MSG))
        ok = p == 0 and m == 0
        check(ok, "%s 与 %s 不一致 pet=%s msg=%s" % (a, b, p, m))
        lines.append("%-22s vs %-22s pet=%.3f msg=%.3f %s"
                     % (a, b, p, m, "OK" if ok else "FAIL"))

lines.append("")
lines.append("--- 提示区文字应当不同（裁到文字行、密集采样，mad>8 视为确实换了文案）---")
for a, b in MSG_DIFF_PAIRS:
    if a in imgs and b in imgs:
        ia, ib = ink(imgs[a], REGION_MSG), ink(imgs[b], REGION_MSG)
        m = mad(crop(imgs[a], REGION_MSG_TEXT), crop(imgs[b], REGION_MSG_TEXT), step=1)
        ok = (m > 8) and ia > ib
        check(ok, "%s 与 %s 提示区未体现差异 mad=%.2f ink=%d/%d" % (a, b, m, ia, ib))
        lines.append("%-22s vs %-22s text mad=%6.2f ink=%5d / %-5d %s"
                     % (a, b, m, ia, ib, "OK" if ok else "FAIL"))
if "01_idle" in imgs:
    lines.append("01_idle 提示区 ink=%d（“等待指令……”的基准）" % ink(imgs["01_idle"], REGION_MSG))

# ---------- 5.5 摸摸头互动 ----------
lines.append("")
lines.append("--- 摸摸头互动（气泡 / 爱心 / 抖动 / 浮标）---")
if HOVER_SHOT in imgs:
    base = imgs["01_idle"]
    ink0 = bubble_ink(base)
    ink1 = bubble_ink(imgs[HOVER_SHOT])
    above = region_mad(base, imgs[HOVER_SHOT], REGION_ABOVE_PET)
    ok = ink1 > ink0 + 100 and above > 8
    check(ok, "悬停未出现气泡：ink=%d(base %d) mad=%.2f" % (ink1, ink0, above))
    lines.append("%-22s 头顶气泡白像素 %d（空闲 %d，+%d） mad=%.2f %s"
                 % (HOVER_SHOT, ink1, ink0, ink1 - ink0, above, "OK" if ok else "FAIL"))

if TOUCH_SHOT in imgs:
    base = imgs["01_idle"]
    hb = heart_pixels(base)
    h1 = heart_pixels(imgs[TOUCH_SHOT])
    stage_mad = region_mad(base, imgs[TOUCH_SHOT], REGION_STAGE)
    ok = h1 > hb + 8 and stage_mad > 3
    check(ok, "摸头未画出爱心：heart=%d(base %d) mad=%.2f" % (h1, hb, stage_mad))
    lines.append("%-22s 爱心像素 %d（空闲 %d，+%d） 舞台 mad=%.2f %s"
                 % (TOUCH_SHOT, h1, hb, h1 - hb, stage_mad, "OK" if ok else "FAIL"))
    # 亲密度那一行应当浮出 +1
    d = region_mad(base, imgs[TOUCH_SHOT], REGION_STAT_INTIMACY)
    ok = d > 1
    check(ok, "摸头未浮出亲密度变化提示 mad=%.2f" % d)
    lines.append("%-22s 亲密度浮标 mad=%.2f %s" % (TOUCH_SHOT, d, "OK" if ok else "FAIL"))

if COMBO_SHOT in imgs and TOUCH_SHOT in imgs:
    h1 = heart_pixels(imgs[TOUCH_SHOT])
    h2 = heart_pixels(imgs[COMBO_SHOT])
    # 连点帧：文案换到「撸秃了」系列，粒子叠加更多
    txt = region_mad(imgs[COMBO_SHOT], imgs[TOUCH_SHOT], REGION_ABOVE_PET)
    ok = h2 > h1 and txt > 2
    check(ok, "连点档未生效：heart %d -> %d mad=%.2f" % (h1, h2, txt))
    lines.append("%-22s 连点爱心 %d > 首次 %d，气泡文案 mad=%.2f %s"
                 % (COMBO_SHOT, h2, h1, txt, "OK" if ok else "FAIL"))

if SETTLED_SHOT in imgs:
    base = imgs["01_idle"]
    hb = heart_pixels(base)
    ib = bubble_ink(base)
    h = heart_pixels(imgs[SETTLED_SHOT])
    ink = bubble_ink(imgs[SETTLED_SHOT])
    back = region_mad(base, imgs[SETTLED_SHOT], REGION_STAGE)
    ok = h <= hb + 2 and ink <= ib + 5 and back < 1.0
    check(ok, "粒子/气泡未按时消失：heart=%d/%d bubble=%d/%d back=%.2f"
             % (h, hb, ink, ib, back))
    lines.append("%-22s 粒子散尽 heart=%d(基准 %d) 气泡消退 bubble=%d(基准 %d) 回稳 mad=%.2f %s"
                 % (SETTLED_SHOT, h, hb, ink, ib, back, "OK" if ok else "FAIL"))

# ---------- 6. 日志断言 ----------
lines.append("")
lines.append("--- 自检日志断言 ---")
raw = ""
log_path = os.path.join(SNAP, "_snapshot.log")
if os.path.exists(log_path):
    with open(log_path, encoding="utf-8") as f:
        raw = f.read()
else:
    lines.append("_snapshot.log MISSING")
    check(False, "_snapshot.log 缺失")

seq = []
for ln in raw.splitlines():
    if "stats[" in ln:
        seq.append(ln.split("stats[", 1)[1].split("]", 1)[1].strip())
lines.append("数值结算序列（共 %d 条，期望 %d 条）：" % (len(seq), len(EXPECT_STATS_SEQ)))
for i, want in enumerate(EXPECT_STATS_SEQ):
    got = seq[i] if i < len(seq) else "(缺失)"
    if got != want:
        check(False, "结算序列[%d] 不符：%s" % (i, got))
    lines.append("  [%d] %-58s %s" % (i, got, "OK" if got == want else "FAIL 期望: " + want))

ok_log = 0
for want in EXPECT_LOGS:
    n = raw.count(want)
    ok_log += 1 if n else 0
    check(n > 0, "日志缺少事件：%s" % want)
    lines.append("  事件 %-38s 出现 %d 次 %s" % (want, n, "OK" if n else "FAIL"))
lines.append("日志事件覆盖：%d / %d" % (ok_log, len(EXPECT_LOGS)))

lines.append("")
lines.append("--- 音效播放断言 ---")
ok_snd = 0
for want, cnt in EXPECT_SOUND_COUNTS.items():
    n = raw.count(want)
    good = (n == cnt)
    ok_snd += 1 if good else 0
    check(good, "音效 %s 播放 %d 次，期望 %d 次" % (want, n, cnt))
    lines.append("  %-14s 播放 %d 次（期望 %d）%s" % (want, n, cnt, "OK" if good else "FAIL"))
lines.append("音效断言通过：%d / %d" % (ok_snd, len(EXPECT_SOUND_COUNTS)))

for bad in FORBID_LOGS:
    hit = [ln for ln in raw.splitlines() if bad in ln]
    check(not hit, "日志出现音效异常关键字 %s：%s" % (bad, hit[:2] if hit else ""))
    lines.append("  禁止项 %-12s 出现 %d 次 %s" % (bad, len(hit), "OK" if not hit else "FAIL"))

lines.append("")
lines.append("========== 汇总：%s ==========" % ("全部通过" if not fails else "存在 %d 项失败" % len(fails)))
for f in fails:
    lines.append("  FAIL " + f)

with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print("\n".join(lines))
sys.exit(1 if fails else 0)
