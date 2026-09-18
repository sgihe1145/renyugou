# -*- coding: utf-8 -*-
"""
任禹狗 —— 桌面萌宠小软件
==========================

实现方式：Python + 纯 Win32 API（ctypes）+ Pillow
  * 不依赖 tkinter / Qt 等任何 GUI 框架，单 exe 可直接运行、体积小
  * 所有界面元素（卡片、按钮、状态条、提示框、立绘）由 GDI 自绘，便于扩展

界面结构
  * 标题区：左上角程序名
  * 操作栏：三个按钮「让任禹狗读书 / 让任禹狗吃饭 / 打篮球」
  * 状态栏：心情 / 活力 / 亲密度 / 智力 / 胃袋（数值 + 进度条，变化时右侧浮出 ±N）
  * 提示区：底部整条，只读系统提示文字
  * 舞台区：右侧任禹狗立绘（底边对齐）

数值规则
  * 上限：心情 100 / 活力 100 / 胃袋 100；智力与亲密度不设上限
  * 下限：全部为 0
  * 读书：智力+15 心情+10 亲密度+5
  * 吃饭：胃袋+20（并且在打篮球冷却期间吃饭会立刻解除冷却）
  * 打篮球：随机三种结局，见 BASKET_* 与 DELTAS
  * 摸摸头：直接点右侧立绘，亲密度+1 心情+1（600ms 节流，防连点刷分）

趣味功能（v1.4）
  * 随机台词库：每个动作都有多条文案，随机抽且不连续重复，见 ACTION_LINES
  * 摸摸头：鼠标移到立绘上会冒对话气泡；点下去会抖动 + 冒爱心 + 随机吐槽，
    短时间内连续点击会触发专属「撸秃了」系列台词
  * 称号：按累计互动次数 / 单项数值解锁，见 TITLE_DEFS；解锁时右侧提示条会发贺电
  * 待机吐槽：空闲时右下提示随机换句子；饥饿 / 心情差时还会主动提醒

立绘切换动画（所有互动共用）
  收起当前立绘（高度压到 0、底边对齐）-> 新立绘从底边升起 -> 停留 -> 再收起 -> 初始立绘升起
  整个流程期间按钮禁用，无法重复点击。

本地存档
  * 存档目录：%LOCALAPPDATA%\\任禹狗\\  （save.json + 行动记录.txt）
  * 退出时自动保存，每次互动结算后也会立即落盘（中途崩溃也不丢）
  * 保存内容：五项状态值、累计互动次数、最近 200 条行动记录、打球冷却的到期时刻
  * 冷却按「墙上时钟」存，关掉程序再打开仍会继续倒计时
  * 按 F2 重置存档（需连按两次确认）
  * 排查问题：设环境变量 RYG_DEBUG_LOG=<文件路径>，运行日志会同时写进该文件

运行参数
  --snapshot <目录>   自检模式：自动跑一遍完整流程并输出截图，供开发校验用
  --selftest          只跑数值逻辑自检（不开窗），结果写 build\\_selftest.txt

音效
  启动播「欸，大狗！」，读书播「哒哒哒哒哒」，吃饭播「叫叫叫！」，打篮球播「大狗大狗」。
  四段都是从原曲裁好的 PCM WAV，base64 内嵌进 assets.py，运行期落到临时文件后
  交给 winsound 异步播放（播放新片段会自动打断上一段）。
"""

import base64
import ctypes
import io
import json
import math
import os
import random
import sys
import tempfile
import time
from ctypes import wintypes

from PIL import Image, ImageFilter

try:
    import winsound
except ImportError:                      # 仅非 Windows 环境会出现
    winsound = None

import assets

# ---------------------------------------------------------------- 音效

# 片段名 -> (assets 里的常量名, 落盘文件名)
SOUND_WAV = {
    "open": ("SOUND_OPEN_WAV", "renyugou_open.wav"),        # 启动：欸，大狗！
    "read": ("SOUND_READ_WAV", "renyugou_read.wav"),        # 读书：哒哒哒哒哒
    "eat": ("SOUND_EAT_WAV", "renyugou_eat.wav"),           # 吃饭：叫叫叫！
    "basket": ("SOUND_BASKET_WAV", "renyugou_basket.wav"),  # 打篮球：大狗大狗
}

SOUND_DIR = "renyugou_snd"

# ---------------------------------------------------------------- 布局常量

APP_NAME = "任禹狗"
APP_SUBTITLE = "桌面萌宠 · v1.4"

CLIENT_W, CLIENT_H = 1060, 720
MARGIN = 24

TITLE_Y = 20

OPS_CARD = (24, 100, 400, 268)            # x, y, w, h
STAT_CARD = (24, 384, 400, 188)
PET_CARD = (440, 100, 596, 472)
MSG_CARD = (24, 588, 1012, 108)

PET_STAGE = (460, 116, 556, 410)          # 立绘舞台区（底边对齐用它的下沿）
PET_FIT = (540, 405)                      # 立绘等比缩放上限
PET_CAPTION_Y = 542
PET_HOVER_POINT = (738, 300)              # 自检里模拟摸头/悬停的坐标（落在封面立绘上）

BTN_W, BTN_H = 360, 52
BTN_GAP = 14
BTN_TOP_OFFSET = 48                       # 第一个按钮相对操作栏顶部的偏移

STAT_ROW_H = 27
STAT_ROWS_OFFSET = 46                     # 第一行相对状态栏顶部的偏移

# 动画时长（毫秒）
COLLAPSE_MS = 180
RISE_MS = 260
HOLD_MS = 3000                            # 读书 / 吃饭的停留时长
BASKET_PLAY_MS = 1500                     # 「正在打球」停留
BASKET_RESULT_MS = 1500                   # 打球结局停留
COOLDOWN_MS = 60 * 1000                   # 打球冷却 1 分钟
SNAP_COOLDOWN_MS = 8000                   # 自检模式下用短冷却，便于验证冷却结束

DELTA_SHOW_MS = 1800                      # 数值变化提示停留时长

# 摸摸头相关的动画/节流时长（毫秒）
SHAKE_MS = 420                            # 立绘抖动
HEART_MIN_MS, HEART_MAX_MS = 700, 1150    # 爱心粒子寿命
BUBBLE_MS = 2200                          # 对话气泡停留
HOVER_REPEAT_MS = 1600                    # 悬停气泡的最小间隔
PET_GAIN_MS = 600                         # 两次有效摸头的最小间隔（防连点刷数值）
COMBO_MS = 2000                           # 连点判定窗口
FLASH_MS = 2800                           # 临时消息（称号贺电）停留
NOTICE_DELAY_MS = 900                     # 动画播完多久才弹贺电，别糊掉动作台词
PET_LOG_EVERY = 5                         # 每摸这么多次，往行动记录里汇总一条

# 爱心粒子：横向/纵向速度（px per ms）与尺寸范围
HEART_VX = (-0.075, 0.075)
HEART_VY = (-0.105, -0.055)
HEART_SIZE = (7.0, 13.0)

# ---------------------------------------------------------------- 颜色（COLORREF = 0x00BBGGRR）


def rgb(r, g, b):
    return r | (g << 8) | (b << 16)


C_BG = rgb(0xF4, 0xF6, 0xF9)
C_CARD = rgb(0xFF, 0xFF, 0xFF)
C_CARD_SOFT = rgb(0xF7, 0xF9, 0xFC)
C_BORDER = rgb(0xE3, 0xE7, 0xEC)
C_DIVIDER = rgb(0xEC, 0xEF, 0xF3)
C_TRACK = rgb(0xEE, 0xF1, 0xF5)
C_TITLE = rgb(0x1F, 0x24, 0x30)
C_TEXT = rgb(0x33, 0x3B, 0x48)
C_SUB = rgb(0x8A, 0x90, 0x99)

C_BLUE = rgb(0x2F, 0x6F, 0xEB)
C_BLUE_HOVER = rgb(0x27, 0x62, 0xD6)
C_BLUE_DOWN = rgb(0x1F, 0x50, 0xB4)
C_ORANGE = rgb(0xE0, 0x7B, 0x39)
C_ORANGE_HOVER = rgb(0xC9, 0x6A, 0x2C)
C_ORANGE_DOWN = rgb(0xAE, 0x59, 0x22)
C_TEAL = rgb(0x17, 0x9A, 0x8A)
C_TEAL_HOVER = rgb(0x13, 0x86, 0x79)
C_TEAL_DOWN = rgb(0x0F, 0x6E, 0x64)
C_DISABLED_BG = rgb(0xE9, 0xEC, 0xEF)
C_DISABLED_FG = rgb(0xAC, 0xB2, 0xBA)
C_WHITE = rgb(0xFF, 0xFF, 0xFF)

C_UP = rgb(0x2E, 0xA0, 0x5B)              # 数值上升
C_DOWN = rgb(0xD1, 0x3B, 0x3B)            # 数值下降

# 爱心粒子配色
C_HEART_COLORS = (rgb(0xF2, 0x6B, 0x9C), rgb(0xFF, 0x94, 0xB8),
                  rgb(0xE8, 0x5A, 0x86), rgb(0xF7, 0xB2, 0xC8))

# 状态项颜色
C_MOOD = rgb(0xE0, 0x5A, 0x7E)
C_VITAL = rgb(0x35, 0xA8, 0x6B)
C_INTIM = rgb(0x8B, 0x5C, 0xE0)
C_INTEL = rgb(0x2F, 0x6F, 0xEB)
C_STOMACH = rgb(0xE0, 0x7B, 0x39)

C_RED = rgb(0xD1, 0x3B, 0x3B)
C_GREEN = rgb(0x2E, 0xA0, 0x5B)
C_AMBER = rgb(0xD8, 0x6A, 0x2E)
C_GOLD = rgb(0xC8, 0x8A, 0x1E)            # 称号贺电用

MSG_COLORS = {
    "idle": C_SUB,
    "read": C_BLUE,
    "eat": C_ORANGE,
    "basket_play": C_TEAL,
    "basket_fall": C_RED,
    "basket_happy": C_GREEN,
    "basket_angry": C_AMBER,
    "basket_rest": C_SUB,
    "basket_cd": C_TEAL,
    "reset_armed": C_AMBER,
    "reset_done": C_GREEN,
    "notice": C_GOLD,
}

# ---------------------------------------------------------------- 台词库

# 每个词条若干句随机文案；挑句子的规则见 LinePicker（绝不连续重复同一句）
# 带数值后缀的句子必须把实际结算的数值写清楚，避免玩家误会
ACTION_LINES = {
    "read": [
        "任禹狗读书了 这使他的气场大增(*^_^*)  智力+15 心情+10 亲密度+5",
        "任禹狗翻开《大狗的自我修养》，看得直点头  智力+15 心情+10 亲密度+5",
        "任禹狗学会了一个新词，现在他会说「汪学」了  智力+15 心情+10 亲密度+5",
        "任禹狗把书啃出了牙印，但知识确实进脑子了  智力+15 心情+10 亲密度+5",
        "任禹狗读书自带 BGM，气场一路飘到天花板  智力+15 心情+10 亲密度+5",
    ],
    "eat": [
        "任禹狗吃饭 这使他的胃袋塞满  胃袋+20",
        "任禹狗正在干饭……碗已经被舔干净了  胃袋+20",
        "任禹狗一口炫完，还眼巴巴盯着你的碗  胃袋+20",
        "任禹狗吃饭的声音传遍了整个房间  胃袋+20",
        "任禹狗宣布：这顿饭他给满分  胃袋+20",
    ],
    "basket_play": [
        "任禹狗正在打球……",
        "任禹狗运球过人，气势如虹……",
        "任禹狗在三分线外蓄势待发……",
    ],
    "basket_fall": [
        "任禹狗打篮球时受伤了，心情-30，活力-15，亲密度+10",
        "任禹狗摔了个狗吃屎，你心疼地抱了抱他  心情-30，活力-15，亲密度+10",
        "任禹狗脚一滑，一大坨躺在地上不想起来  心情-30，活力-15，亲密度+10",
    ],
    "basket_happy": [
        "任禹狗打得十分开心，心情+25，亲密度+20，活力-10",
        "任禹狗投中绝杀！他绕着场子跑了三圈  心情+25，亲密度+20，活力-10",
        "任禹狗今天手感火热，连他自己都佩服自己  心情+25，亲密度+20，活力-10",
    ],
    "basket_angry": [
        "任禹狗打的十分不高兴，心情-10，活力-10，亲密度+15",
        "任禹狗被吹了犯规，冲着裁判汪汪叫  心情-10，活力-10，亲密度+15",
        "任禹狗投了十个都没进，气得把球坐扁了  心情-10，活力-10，亲密度+15",
    ],
    # 剩 %d 秒：渲染时会被填成实际秒数
    "basket_rest": [
        "任禹狗正在休息，打球冷却中（还剩 %d 秒）",
        "任禹狗瘫在地上回血……还需 %d 秒",
        "任禹狗表示腿已经不是自己的了，%d 秒后再战",
    ],
    "basket_cd": [
        "刚打完篮球 任禹狗需要休息哦（1分钟）",
        "不行！任禹狗现在连抬爪子的力气都没有",
        "任禹狗用眼神拒绝了你的篮球邀请",
    ],
    "idle": [
        "等待指令……",
        "任禹狗正蹲在原地思考狗生",
        "任禹狗在等你想起他",
        "（任禹狗摇了摇尾巴）",
        "任禹狗：汪。",
        "任禹狗盯着你，好像有事要说",
        "（任禹狗打了个哈欠）",
    ],
    "reset_armed": [
        "再按一次 F2 确认：清空本地存档，状态值与互动记录全部归零",
    ],
    "reset_done": [
        "存档已清空，任禹狗回到初始状态",
    ],
}

# 数值告急时的待机提醒（比普通吐槽优先）
IDLE_WARN_LINES = [
    ("stomach", 20, "任禹狗的肚子在抗议了，要不要喂点东西？"),
    ("mood", 20, "任禹狗情绪有点低落，陪他玩会儿吧……"),
    ("vitality", 20, "任禹狗困得睁不开眼了，让他休息一下"),
]

# 鼠标停在立绘上时，头顶冒出的气泡
HOVER_LINES = [
    "嗯？你在看我？",
    "（歪头）你手里的东西能吃吗？",
    "汪？",
    "再盯下去我要收门票了",
    "（尾巴摇起来了）",
    "盯——",
]

# 摸一下的即时反馈
PET_LINES = [
    "被摸了！舒服得眯起眼",
    "（蹭了蹭你的手）",
    "汪汪~！",
    "呼噜呼噜……",
    "摸摸头，是摸摸头！",
    "这里，再往下一丢丢",
]

# 短时间连续点击的专属吐槽（combo ≥ 3 起）
PET_COMBO_LINES = [
    "还摸？毛都要被撸秃了！",
    "行行行，摸够了吧！",
    "（任禹狗躲开了）",
    "你的手不累吗？",
    "再摸下去要收费了啊！",
]

# MSG_TEXTS 只是兜底：真正显示的是上面台词库随机抽出来的那一句
MSG_TEXTS = dict((k, v[0]) for k, v in ACTION_LINES.items())
MSG_TEXTS["notice"] = "★ %s"

CAPTIONS = {
    "cover": "封面形态",
    "read": "读书中",
    "eat": "干饭中",
    "basket_play": "打篮球中",
    "basket_fall": "打球受伤了",
    "basket_happy": "打球超开心",
    "basket_angry": "打球不高兴",
}

# ---------------------------------------------------------------- 称号

TITLE_NONE_TEXT = "尚无称号"


def _total_cmds(totals):
    """「指令类」互动总次数（不含摸头，摸头有单独的称号线）。"""
    return int(totals.get("read", 0)) + int(totals.get("eat", 0)) + int(totals.get("basket", 0))


# id, 称号, 解锁说明, 判定函数(totals, stats)
TITLE_DEFS = [
    ("newbie", "初次见面", "完成 1 次互动",
     lambda t, s: _total_cmds(t) >= 1),
    ("bookworm", "小书虫", "读书 5 次",
     lambda t, s: int(t.get("read", 0)) >= 5),
    ("foodie", "干饭人", "吃饭 5 次",
     lambda t, s: int(t.get("eat", 0)) >= 5),
    ("rookie", "球场新秀", "打篮球 3 次",
     lambda t, s: int(t.get("basket", 0)) >= 3),
    ("touchee", "撸狗新手", "摸头 10 次",
     lambda t, s: int(t.get("pet", 0)) >= 10),
    ("regular", "熟面孔", "累计指令 15 次",
     lambda t, s: _total_cmds(t) >= 15),
    ("reader", "饱学之士", "读书 20 次",
     lambda t, s: int(t.get("read", 0)) >= 20),
    ("sticky", "黏人精", "亲密度 ≥ 50",
     lambda t, s: int(s.get("intimacy", 0)) >= 50),
    ("wise", "小智者", "智力 ≥ 100",
     lambda t, s: int(s.get("intellect", 0)) >= 100),
    ("bigbelly", "大胃王", "吃饭 25 次",
     lambda t, s: int(t.get("eat", 0)) >= 25),
    ("full", "圆滚滚", "胃袋塞满（100）",
     lambda t, s: int(s.get("stomach", 0)) >= 100),
    ("cheer", "没烦恼", "心情满值（100）",
     lambda t, s: int(s.get("mood", 0)) >= 100),
    ("keeper", "铲屎官", "累计指令 40 次",
     lambda t, s: _total_cmds(t) >= 40),
    ("toucher", "撸狗狂魔", "摸头 60 次",
     lambda t, s: int(t.get("pet", 0)) >= 60),
    ("baller", "灌篮高手", "打篮球 20 次",
     lambda t, s: int(t.get("basket", 0)) >= 20),
    ("smartest", "任博士", "智力 ≥ 300",
     lambda t, s: int(s.get("intellect", 0)) >= 300),
    ("soulmate", "一生挚友", "累计指令 100 次",
     lambda t, s: _total_cmds(t) >= 100),
]

TITLE_IDS = set(t[0] for t in TITLE_DEFS)

# ---------------------------------------------------------------- 按钮与数值定义

BTN_DEFS = [
    ("read", "让任禹狗读书", C_BLUE, C_BLUE_HOVER, C_BLUE_DOWN),
    ("eat", "让任禹狗吃饭", C_ORANGE, C_ORANGE_HOVER, C_ORANGE_DOWN),
    ("basket", "打篮球", C_TEAL, C_TEAL_HOVER, C_TEAL_DOWN),
]

BTN_Y = [OPS_CARD[1] + BTN_TOP_OFFSET + i * (BTN_H + BTN_GAP) for i in range(len(BTN_DEFS))]

# key, 名称, 初始值, 上限（None = 无上限）, 颜色
STAT_DEFS = [
    ("mood", "心情", 70, 100, C_MOOD),
    ("vitality", "活力", 80, 100, C_VITAL),
    ("intimacy", "亲密度", 10, None, C_INTIM),
    ("intellect", "智力", 10, None, C_INTEL),
    ("stomach", "胃袋", 30, 100, C_STOMACH),
]

BASKET_OUTCOMES = ("fall", "happy", "angry")

# 每个动作带来的数值变化
DELTAS = {
    "read": {"intellect": 15, "mood": 10, "intimacy": 5},
    "eat": {"stomach": 20},
    "basket_fall": {"mood": -30, "vitality": -15, "intimacy": 10},
    "basket_happy": {"mood": 25, "intimacy": 20, "vitality": -10},
    "basket_angry": {"mood": -10, "vitality": -10, "intimacy": 15},
}

# 存档：行动记录里用的中文名（key 与 DELTAS 对应）
ACTION_LABELS = {
    "read": "读书",
    "eat": "吃饭",
    "basket_fall": "打篮球（摔倒）",
    "basket_happy": "打篮球（开心）",
    "basket_angry": "打篮球（发怒）",
    "pet": "摸摸头",
}

# 摸一只狗给多少；摸头有自己的节流与称号，不和其它动作混算
PET_DELTAS = {"intimacy": 1, "mood": 1}

SAVE_VERSION = 2
SAVE_FILE = "save.json"
ACTION_LOG_FILE = "行动记录.txt"
HISTORY_MAX = 200                        # 存档里最多保留多少条行动记录

# ---------------------------------------------------------------- Win32 绑定

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

WS_OVERLAPPED = 0x00000000
WS_CAPTION = 0x00C00000
WS_SYSMENU = 0x00080000
WS_MINIMIZEBOX = 0x00020000
WS_EX_APPWINDOW = 0x00040000
CS_HREDRAW, CS_VREDRAW = 0x0002, 0x0001

SW_SHOWNORMAL = 1

WM_DESTROY = 0x0002
WM_PAINT = 0x000F
WM_CLOSE = 0x0010
WM_ERASEBKGND = 0x0014
WM_SETCURSOR = 0x0020
WM_MOUSELEAVE = 0x02A3
WM_TIMER = 0x0113
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_PRINTCLIENT = 0x0318
WM_KEYDOWN = 0x0100

VK_F2 = 0x71

IDC_ARROW, IDC_HAND = 32512, 32649
IMAGE_ICON, LR_LOADFROMFILE = 1, 0x0010
ICON_SMALL, ICON_BIG = 0, 1

DT_LEFT, DT_CENTER, DT_RIGHT = 0x0000, 0x0001, 0x0002
DT_VCENTER, DT_SINGLELINE, DT_WORDBREAK, DT_NOPREFIX = 0x0004, 0x0020, 0x0010, 0x0800
DT_CALCRECT = 0x0400

TRANSPARENT, NULL_PEN, NULL_BRUSH = 1, 8, 5
HALFTONE, SRCCOPY, DIB_RGB_COLORS = 4, 0x00CC0020, 0

FW_NORMAL, FW_SEMIBOLD, FW_BOLD = 400, 600, 700
PS_SOLID = 0

PW_CLIENTONLY = 0x00000001
TME_LEAVE = 0x00000002

TIMER_ANIM, TIMER_SNAP, TIMER_IDLE = 1, 2, 3

FONT_FACE = "Microsoft YaHei UI"


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT), ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR),
        ("hIconSm", wintypes.HICON),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
        ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD), ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", ctypes.c_long), ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD),
    ]


class PAINTSTRUCT(ctypes.Structure):
    _fields_ = [
        ("hdc", wintypes.HDC), ("fErase", wintypes.BOOL), ("rcPaint", wintypes.RECT),
        ("fRestore", wintypes.BOOL), ("fIncUpdate", wintypes.BOOL),
        ("rgbReserved", ctypes.c_byte * 32),
    ]


class TRACKMOUSEEVENT(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
        ("hwndTrack", wintypes.HWND), ("dwHoverTime", wintypes.DWORD),
    ]


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


def _bind():
    u, g, k = user32, gdi32, kernel32
    k.GetModuleHandleW.restype = wintypes.HMODULE
    k.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    k.GetTickCount64.restype = ctypes.c_ulonglong
    k.GetTickCount64.argtypes = []

    u.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
    u.RegisterClassExW.restype = wintypes.ATOM
    u.CreateWindowExW.restype = wintypes.HWND
    u.CreateWindowExW.argtypes = [
        wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
    u.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    u.DefWindowProcW.restype = LRESULT
    u.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
    u.GetMessageW.restype = ctypes.c_int
    u.BeginPaint.restype = wintypes.HDC
    u.BeginPaint.argtypes = [wintypes.HWND, ctypes.POINTER(PAINTSTRUCT)]
    u.EndPaint.argtypes = [wintypes.HWND, ctypes.POINTER(PAINTSTRUCT)]
    u.GetDC.restype = wintypes.HDC
    u.GetDC.argtypes = [wintypes.HWND]
    u.LoadCursorW.restype = wintypes.HANDLE
    u.LoadCursorW.argtypes = [wintypes.HINSTANCE, wintypes.LPVOID]
    u.AdjustWindowRectEx.argtypes = [ctypes.POINTER(wintypes.RECT), wintypes.DWORD,
                                     wintypes.BOOL, wintypes.DWORD]
    u.SetTimer.restype = wintypes.UINT
    u.SetTimer.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.LPVOID]
    u.InvalidateRect.argtypes = [wintypes.HWND, wintypes.LPVOID, wintypes.BOOL]
    u.SetCursor.restype = wintypes.HANDLE
    u.SetCursor.argtypes = [wintypes.HANDLE]
    u.LoadImageW.restype = wintypes.HANDLE
    u.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
                             ctypes.c_int, ctypes.c_int, wintypes.UINT]
    u.SetProcessDPIAware.restype = wintypes.BOOL
    u.SetProcessDPIAware.argtypes = []
    u.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
    u.TrackMouseEvent.argtypes = [ctypes.POINTER(TRACKMOUSEEVENT)]
    u.GetSystemMetrics.restype = ctypes.c_int
    u.GetSystemMetrics.argtypes = [ctypes.c_int]

    g.CreateCompatibleDC.restype = wintypes.HDC
    g.CreateCompatibleDC.argtypes = [wintypes.HDC]
    g.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    g.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    g.CreateDIBSection.restype = wintypes.HBITMAP
    g.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.POINTER(BITMAPINFOHEADER), wintypes.UINT,
                                   ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
    g.SelectObject.restype = wintypes.HGDIOBJ
    g.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    g.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    g.DeleteDC.argtypes = [wintypes.HDC]
    g.CreateSolidBrush.restype = wintypes.HBRUSH
    g.CreateSolidBrush.argtypes = [wintypes.DWORD]
    g.CreatePen.restype = wintypes.HPEN
    g.CreatePen.argtypes = [ctypes.c_int, ctypes.c_int, wintypes.DWORD]
    g.CreateFontW.restype = wintypes.HFONT
    g.CreateFontW.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                              wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                              wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                              wintypes.LPCWSTR]
    g.GetStockObject.restype = wintypes.HGDIOBJ
    g.GetStockObject.argtypes = [ctypes.c_int]
    g.SaveDC.restype = ctypes.c_int
    g.SaveDC.argtypes = [wintypes.HDC]
    g.RestoreDC.restype = wintypes.BOOL
    g.RestoreDC.argtypes = [wintypes.HDC, ctypes.c_int]
    g.RoundRect.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                            ctypes.c_int, ctypes.c_int]
    u.FillRect.argtypes = [wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.HBRUSH]
    u.DrawTextW.argtypes = [wintypes.HDC, wintypes.LPCWSTR, ctypes.c_int,
                            ctypes.POINTER(wintypes.RECT), wintypes.UINT]
    g.SetTextColor.argtypes = [wintypes.HDC, wintypes.DWORD]
    g.SetBkMode.restype = ctypes.c_int
    g.SetBkMode.argtypes = [wintypes.HDC, ctypes.c_int]
    g.SetStretchBltMode.restype = ctypes.c_int
    g.SetStretchBltMode.argtypes = [wintypes.HDC, ctypes.c_int]
    g.SetBrushOrgEx.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.LPVOID]
    g.StretchBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                             wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                             wintypes.DWORD]
    g.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                         wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
    g.Ellipse.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
    g.Polygon.argtypes = [wintypes.HDC, ctypes.POINTER(POINT), ctypes.c_int]


_bind()


def _res_id(value):
    """MAKEINTRESOURCE：把整数资源 ID 传给需要指针的 Win32 接口。"""
    return ctypes.cast(ctypes.c_void_p(value), wintypes.LPVOID)


def _now():
    return kernel32.GetTickCount64()


# ---------------------------------------------------------------- 素材处理


def _decode_rgba(b64):
    return Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGBA")


def _flatten(im, bg=(255, 255, 255)):
    base = Image.new("RGBA", im.size, bg + (255,))
    return Image.alpha_composite(base, im).convert("RGB")


def _fit(im, box):
    bw, bh = box
    w, h = im.size
    s = min(bw / float(w), bh / float(h))
    out = im.resize((max(1, int(round(w * s))), max(1, int(round(h * s)))), Image.LANCZOS)
    if s > 1.2:                      # 素材分辨率偏低，放大后轻微锐化
        out = out.filter(ImageFilter.UnsharpMask(radius=1.4, percent=55, threshold=3))
    return out


class Surface(object):
    """预渲染位图 + 它自己的源 DC。"""

    def __init__(self, ref_dc, pil_img):
        self.w, self.h = pil_img.size
        bmi = BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.biWidth = self.w
        bmi.biHeight = -self.h          # 负数 = 自上而下
        bmi.biPlanes = 1
        bmi.biBitCount = 32
        bmi.biCompression = 0           # BI_RGB
        ppv = ctypes.c_void_p()
        self.hbmp = gdi32.CreateDIBSection(ref_dc, ctypes.byref(bmi), DIB_RGB_COLORS,
                                           ctypes.byref(ppv), None, 0)
        if not self.hbmp:
            raise ctypes.WinError(ctypes.get_last_error())
        data = pil_img.tobytes("raw", "BGRX")
        ctypes.memmove(ppv, data, len(data))
        self.dc = gdi32.CreateCompatibleDC(ref_dc)
        gdi32.SelectObject(self.dc, self.hbmp)

    def blit(self, dst_dc, x, y, w, h):
        if w < 1 or h < 1:
            return
        gdi32.SetStretchBltMode(dst_dc, HALFTONE)
        gdi32.SetBrushOrgEx(dst_dc, 0, 0, None)
        gdi32.StretchBlt(dst_dc, x, y, w, h, self.dc, 0, 0, self.w, self.h, SRCCOPY)


# ---------------------------------------------------------------- 台词抽取


class LinePicker(object):
    """从一个词条池里随机抽一句，且绝不与上一条重复。
    
    做法：先在 0..n-2 里随机，再加到「上一条 + 1」上取模 —— 相当于在环里
    从下一条开始跳 k 步，天然跳过上一次那条，也不用洗牌。
    """

    def __init__(self):
        self.last = {}

    def pick(self, key, pool):
        if not pool:
            return ""
        n = len(pool)
        if n == 1:
            return pool[0]
        prev = self.last.get(key)
        i = random.randrange(n - 1)
        if prev is not None:
            i = (prev + 1 + i) % n
        self.last[key] = i
        return pool[i]


# ---------------------------------------------------------------- 数值系统


class Stats(object):
    """五项状态值：带上限的夹取 + 无上限的无限增长，并记录最近一次变化量。"""

    def __init__(self):
        self.order = []
        self.label = {}
        self.value = {}
        self.cap = {}
        self.color = {}
        self.delta = {}                      # key -> (变化量, 过期 tick)
        for key, label, init, cap, color in STAT_DEFS:
            self.order.append(key)
            self.label[key] = label
            self.value[key] = init
            self.cap[key] = cap
            self.color[key] = color

    def load_values(self, data):
        """从存档恢复：只认已知项，并按上下限夹一遍（存档可能被手改）。"""
        for key in self.order:
            v = data.get(key)
            if not isinstance(v, (int, float)):
                continue
            v = int(v)
            if v < 0:
                v = 0
            cap = self.cap[key]
            if cap is not None and v > cap:
                v = cap
            self.value[key] = v

    def reset(self):
        for key, label, init, cap, color in STAT_DEFS:
            self.value[key] = init

    def apply(self, changes, now=None):
        """按 delta 增减；返回 [(key, 实际变化量, 新值)]。"""
        now = _now() if now is None else now
        applied = []
        for key, amount in changes.items():
            old = self.value[key]
            v = old + amount
            if v < 0:
                v = 0                        # 下限统一为 0
            cap = self.cap[key]
            if cap is not None and v > cap:
                v = cap                      # 有上限的夹到上限
            self.value[key] = v
            real = v - old
            if real:
                self.delta[key] = (real, now + DELTA_SHOW_MS)
            applied.append((key, real, v))
        return applied

    def dump(self):
        return " ".join("%s=%d" % (k, self.value[k]) for k in self.order)


# ---------------------------------------------------------------- 本地存档


def save_dir():
    """存档目录：%LOCALAPPDATA%\\任禹狗（取不到就退回临时目录）。"""
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or tempfile.gettempdir()
    return os.path.join(base, APP_NAME)


def read_save(path):
    """读存档；不存在或损坏都返回 None（调用方按「首次运行」处理）。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_save(path, data):
    """原子写：先写临时文件再替换，避免写到一半被关掉而损坏存档。"""
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)                    # Windows 上也是原子覆盖


def append_action_log(path, line):
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        return False
    return True


# ---------------------------------------------------------------- 立绘状态机

STEP_COLLAPSE, STEP_RISE, STEP_HOLD = "collapse", "rise", "hold"


def _clamp01(v):
    return 0.0 if v < 0.0 else (1.0 if v > 1.0 else v)


def _ease_in(p):
    return p * p * p


def _ease_out(p):
    return 1.0 - (1.0 - p) ** 3


def _step(kind, key, dur, msg=None, enter=None):
    return {"kind": kind, "key": key, "dur": dur, "msg": msg, "enter": enter}


class Pet(object):
    """任禹狗立绘 + 切换流程。"""

    def __init__(self):
        self.surfaces = {}
        self.showing = "cover"
        self.factor = 1.0
        self.caption = CAPTIONS["cover"]
        self.msg = "idle"
        self.msg_text = None                 # 本次实际要显示的那一句（由 App 随机抽）
        self.line_cb = None                  # fn(key) -> str：抽台词的钩子
        self.shake_t0 = 0                    # 被摸时的抖动起始时刻，0 = 不在抖
        self.busy = False
        self.last_kind = None
        self.outcome = None
        self.steps = []
        self.step_idx = 0
        self.step_t0 = 0
        self.settle_cb = None            # fn(action_key)：结果帧升起时结算数值
        self.end_cb = None               # fn()：整套流程结束时回调（用于启动冷却）

    def _set_msg(self, key):
        """切换提示条文案：主程序会顺手随机抽一句。

        同一个词条在一次流程里会走过好几步（收起 -> 升起 -> 停留），每一步都会
        调到这里。若每次都重抽，点一次吃饭就会看到提示条闪着连换两句 —— 所以
        词条没变时沿用已经抽好的那一句，一次互动只说一句。
        """
        same = (self.msg == key and self.msg_text)
        self.msg = key
        if not same:
            self.msg_text = self.line_cb(key) if self.line_cb else None

    def load(self, ref_dc):
        raw = {
            "cover": _decode_rgba(assets.COVER_PNG),
            "read": _decode_rgba(assets.READ_PNG),
            "eat": _decode_rgba(assets.EAT_PNG),
            "basket_play": _decode_rgba(assets.BASKET_PLAY_PNG),
            "basket_fall": _decode_rgba(assets.BASKET_FALL_PNG),
            "basket_happy": _decode_rgba(assets.BASKET_HAPPY_PNG),
            "basket_angry": _decode_rgba(assets.BASKET_ANGRY_PNG),
        }
        for key, im in raw.items():
            self.surfaces[key] = Surface(ref_dc, _fit(_flatten(im), PET_FIT))

    def trigger(self, kind, outcome=None):
        """kind: 'read' | 'eat' | 'basket'；返回 False 表示正在切换、拒绝操作。"""
        if self.busy:
            return False
        self.busy = True
        self.last_kind = kind

        if kind == "basket":
            outcome = outcome if outcome in BASKET_OUTCOMES else random.choice(BASKET_OUTCOMES)
            self.outcome = outcome
            res_key = "basket_" + outcome
            steps = [
                _step(STEP_COLLAPSE, "cover", COLLAPSE_MS),
                _step(STEP_RISE, "basket_play", RISE_MS, msg="basket_play"),
                _step(STEP_HOLD, "basket_play", BASKET_PLAY_MS),
                _step(STEP_COLLAPSE, "basket_play", COLLAPSE_MS),
                _step(STEP_RISE, res_key, RISE_MS, msg=res_key,
                      enter=lambda: self._settle(res_key)),
                _step(STEP_HOLD, res_key, BASKET_RESULT_MS),
                _step(STEP_COLLAPSE, res_key, COLLAPSE_MS),
                _step(STEP_RISE, "cover", RISE_MS),
            ]
        else:
            self._set_msg(kind)
            steps = [
                _step(STEP_COLLAPSE, "cover", COLLAPSE_MS),
                _step(STEP_RISE, kind, RISE_MS, msg=kind),
                _step(STEP_HOLD, kind, HOLD_MS),
                _step(STEP_COLLAPSE, kind, COLLAPSE_MS),
                _step(STEP_RISE, "cover", RISE_MS),
            ]

        self.steps = steps
        self.step_idx = 0
        self.step_t0 = _now()
        self._enter(steps[0])
        return True

    def _settle(self, key):
        if self.settle_cb:
            self.settle_cb(key)

    def _enter(self, st):
        self.showing = st["key"]
        self.caption = CAPTIONS.get(st["key"], "")
        if st["msg"]:
            self._set_msg(st["msg"])
        self.factor = 0.0 if st["kind"] == STEP_RISE else 1.0
        if st["enter"]:
            st["enter"]()

    def tick(self):
        """按时间推进状态机；返回 True 表示动画尚未结束。"""
        if not self.steps:
            return False
        now = _now()
        while self.step_idx < len(self.steps):
            st = self.steps[self.step_idx]
            dur = st["dur"]
            p = 1.0 if dur <= 0 else _clamp01((now - self.step_t0) / float(dur))
            if p < 1.0:
                self._apply(p)
                return True
            self.step_idx += 1
            self.step_t0 = now
            if self.step_idx < len(self.steps):
                self._enter(self.steps[self.step_idx])
        self.steps = []
        self.showing = "cover"
        self.factor = 1.0
        self.caption = CAPTIONS["cover"]
        self._set_msg("idle")
        self.busy = False
        cb, self.end_cb = self.end_cb, None
        if cb:
            cb()
        return True

    def _apply(self, p):
        kind = self.steps[self.step_idx]["kind"]
        if kind == STEP_COLLAPSE:
            self.factor = 1.0 - _ease_in(p)
        elif kind == STEP_RISE:
            self.factor = _ease_out(p)
        else:
            self.factor = 1.0


# ---------------------------------------------------------------- 应用


class App(object):
    def __init__(self, snapshot_dir=None, cooldown_ms=COOLDOWN_MS):
        if snapshot_dir:
            random.seed(20260917)             # 自检截图要可复现，先固定随机序列
        self.pet = Pet()
        self.stats = Stats()
        self.picker = LinePicker()
        self.hwnd = None
        self.hover = -1
        self.pressed = -1
        self.pet_hover = False
        self.pet_pressed = False
        self.tracking_leave = False
        self.fonts = {}
        self.hdc_back = None
        self.hbmp_back = None
        self.ref_dc = None
        self.icon_path = None
        self.cooldown_ms = cooldown_ms
        self.cooldown_until = 0
        self._cd_shown = -1
        self.snapshot_dir = snapshot_dir
        self.snap_steps = []
        self.snap_idx = 0
        self.snap_t0 = 0
        self.log_lines = []
        self._sound_paths = {}
        self._wndproc_ref = WNDPROC(self._wndproc)
        self.pet.settle_cb = self._settle
        self.pet.line_cb = self._pick_line
        self._init_persist()

    # ---------- 存档
    def _init_persist(self):
        # 自检模式不能碰真实存档（否则每次跑自检数值都不是初始值，截图也没法比）
        self.persist = self.snapshot_dir is None
        if self.persist:
            self.save_dir = save_dir()
            self.save_path = os.path.join(self.save_dir, SAVE_FILE)
            self.action_log_path = os.path.join(self.save_dir, ACTION_LOG_FILE)
        else:
            self.save_dir = tempfile.gettempdir()
            self.save_path = os.path.join(self.save_dir, "renyugou_selftest_save.json")
            self.action_log_path = os.path.join(self.save_dir, "renyugou_selftest_log.txt")
        self.totals = dict((d[0], 0) for d in BTN_DEFS)
        self.totals["pet"] = 0              # 摸头次数（没有对应按钮，单独放）
        self.history = []
        self.sessions = 0
        self.last_action = ""
        self._reset_armed = 0
        self.debug_log = os.environ.get("RYG_DEBUG_LOG") or None

        # ---- 摸头互动的运行时状态
        self.hearts = []                    # 爱心粒子
        self.bubble = None                  # {"text","t0","life"}
        self.pet_rect = None                # 上一次画出来的立绘矩形，命中测试用
        self._last_pet_gain = 0             # 上次真正结算数值的摸头时刻
        self._last_pet_talk = 0
        self.pets_since_log = 0             # 距上次写行动记录又摸了几次
        self._combo = 0

        # ---- 称号与临时消息
        self.titles = []                    # 已解锁的称号 id
        self.msg_queue = []                 # 待显示的贺电
        self._flash_until = 0               # 临时消息占用提示条的截止时间
        self._quiet_since = 0               # 最近一次「不忙」的起始时刻，用于延后贺电
        self.idle_text = "等待指令……"
        self._warning = False
        self._refresh_idle()

    def _load_state(self):
        data = read_save(self.save_path) if self.persist else None
        if data is None:
            self.sessions = 1
            self.log("save=%s path=%s" % ("disabled(自检模式)" if not self.persist else "new",
                                          self.save_path))
            return
        self.stats.load_values(data.get("stats") or {})
        for key in self.totals:
            self.totals[key] = int((data.get("totals") or {}).get(key, 0) or 0)
        self.history = [h for h in (data.get("history") or []) if isinstance(h, dict)][-HISTORY_MAX:]
        self.sessions = int(data.get("sessions", 0) or 0) + 1
        self.titles = [t for t in (data.get("titles") or [])
                       if isinstance(t, str) and t in TITLE_IDS]
        self.pets_since_log = int(data.get("pets_since_log", 0) or 0)
        if self.history:
            last = self.history[-1]
            self.last_action = "%s · %s" % (last.get("label", ""), last.get("t", ""))
        # 冷却按墙上时钟恢复：关掉程序再打开，剩余的秒数继续算
        left = float(data.get("cooldown_deadline", 0) or 0) - time.time()
        if left > 0:
            self.cooldown_until = _now() + int(left * 1000)
            self._say("basket_rest")
            self.log("save=loaded session=%d total=%d cd_left=%dms"
                     % (self.sessions, sum(self.totals.values()), int(left * 1000)))
        else:
            self.log("save=loaded session=%d total=%d" % (self.sessions, sum(self.totals.values())))
        self._log_stats("loaded")
        self._refresh_idle()                 # 按读回来的数值挑一句待机吐槽

    def _save_state(self, tag=""):
        if not self.persist:
            return False
        left = self._cooldown_left()
        data = {
            "version": SAVE_VERSION,
            "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "sessions": self.sessions,
            "stats": dict((k, self.stats.value[k]) for k in self.stats.order),
            "totals": dict(self.totals),
            "titles": list(self.titles),
            "pets_since_log": self.pets_since_log,
            "history": self.history[-HISTORY_MAX:],
            "cooldown_deadline": (time.time() + left / 1000.0) if left else 0,
        }
        try:
            write_save(self.save_path, data)
        except OSError as exc:
            self.log("save FAILED %r" % (exc,))
            return False
        self.log("save written%s total=%d" % ((":" + tag) if tag else "",
                                              sum(self.totals.values())))
        return True

    def _record(self, key, changes, applied=None, bump=True):
        """记一次行动：累计次数、历史、纯文本日志，并立刻落盘。

        bump=False 用于「摸头」——它的累计次数由调用方按实际生效次数维护，
        因为每 PET_LOG_EVERY 次才汇总写一条记录。
        """
        kind = key.split("_")[0]
        if bump:
            self.totals[kind] = self.totals.get(kind, 0) + 1
        entry = {
            "t": time.strftime("%m-%d %H:%M"),
            "action": key,
            "label": ACTION_LABELS.get(key, key),
            "changes": " ".join("%s%+d" % (k, v) for k, v in changes.items()),
            "stats": self.stats.dump(),
        }
        self.history.append(entry)
        if len(self.history) > HISTORY_MAX:
            del self.history[:-HISTORY_MAX]
        self.last_action = "%s · %s" % (entry["label"], entry["t"])
        if self.persist:
            append_action_log(
                self.action_log_path,
                "[%s] 第%d次启动 | %s | %s | %s"
                % (time.strftime("%Y-%m-%d %H:%M:%S"), self.sessions,
                   entry["label"], entry["changes"], entry["stats"]))

    # ---------- 台词 / 提示条 / 称号
    def _pick_line(self, key):
        """给某个提示条词条随机抽一句（挂给 Pet.line_cb）。"""
        return self.picker.pick(key, ACTION_LINES.get(key) or ())

    def _say(self, key):
        """切换提示条到某个词条，并顺手抽好这一句。"""
        self.pet.msg = key
        self.pet.msg_text = self._pick_line(key)

    def _warn_line(self):
        """当前是否有一条「告急」提醒要说；没有就返回 None。"""
        for key, threshold, line in IDLE_WARN_LINES:
            if self.stats.value.get(key, 0) < threshold:
                return line
        return None

    def _refresh_idle(self):
        """挑一句待机吐槽（启动、重置时用）。"""
        self.idle_text = self._warn_line() or self.picker.pick("idle", ACTION_LINES["idle"])
        self._warning = bool(self._warn_line())

    def _apply_idle(self):
        """回到待机时维护那句吐槽：只在「告急与否」翻转时才换。
        
        这样同一会话里 idle 文案是稳定的，画面复位前后能逐像素一致；
        饿了/心情差的提醒又确实会冒出来、也会在被照顾好后换回去。
        """
        warn = self._warn_line()
        if warn:
            if warn != self.idle_text:
                self.idle_text = warn
            self._warning = True
        elif self._warning:
            self._warning = False
            self.idle_text = self.picker.pick("idle", ACTION_LINES["idle"])

    def _to_idle(self):
        """回到待机提示（文案用当前那句 idle，动作前后复位画面才一致）。"""
        self.pet.msg = "idle"
        self._apply_idle()
        self.pet.msg_text = self.idle_text

    def _flash(self, text, ms=FLASH_MS):
        """临时占用提示条（称号贺电）。"""
        self.pet.msg = "notice"
        self.pet.msg_text = text
        self._flash_until = _now() + ms

    def _msg_text(self):
        """当前提示条该显示的那一句话。"""
        key = self.pet.msg
        if key == "idle":
            return self.idle_text
        text = self.pet.msg_text or MSG_TEXTS.get(key, "")
        if key == "basket_rest":
            text = text % max(1, -(-self._cooldown_left() // 1000))
        return text

    def _current_title(self):
        """当前称号 = 已解锁里排在最末（最高阶）的那个。"""
        cur = None
        for tid, name, _desc, _fn in TITLE_DEFS:
            if tid in self.titles:
                cur = name
        return cur

    def _title_note(self):
        name = self._current_title()
        if name:
            return "称号 · %s（%d/%d）" % (name, len(self.titles), len(TITLE_DEFS))
        return "称号 · " + TITLE_NONE_TEXT

    def _check_titles(self):
        """结算后盘点一次：返回本次新解锁的 [(名称, 说明)]，并把贺电排进队列。"""
        vals = dict((k, self.stats.value[k]) for k in self.stats.order)
        newly = []
        for tid, name, desc, fn in TITLE_DEFS:
            if tid in self.titles:
                continue
            try:
                if not fn(self.totals, vals):
                    continue
            except Exception:
                continue                      # 条件算不出来就当没达成，不能崩界面
            self.titles.append(tid)
            newly.append((name, desc))
            self.log("title unlocked %s(%s)" % (tid, name))
        if newly:
            self.msg_queue.append(
                "解锁称号「%s」——达成：%s"
                % ("、".join(n[0] for n in newly), "；".join(n[1] for n in newly)))
        return newly

    # ---------- 摸摸头
    def _hit_pet(self, px, py):
        """是否点/悬停在实际画出来的立绘矩形上（用上一帧记录的位置）。"""
        r = self.pet_rect
        if not r:
            return False
        x, y, w, h = r
        return x <= px < x + w and y <= py < y + h

    def _can_pet(self, px, py):
        return (not self.pet.busy) and self.pet.factor > 0.85 and self._hit_pet(px, py)

    def _spawn_hearts(self, cx, cy, n=8):
        now = _now()
        for _ in range(n):
            # 位置按「生成时刻 + 存活时长」算出，定时器抖动不会影响形态
            self.hearts.append({
                "x0": float(cx) + random.uniform(-20, 20),
                "y0": float(cy) + random.uniform(-10, 10),
                "vx": random.uniform(*HEART_VX),
                "vy": random.uniform(*HEART_VY),
                "t0": now,
                "life": random.randint(HEART_MIN_MS, HEART_MAX_MS),
                "r": random.uniform(*HEART_SIZE),
                "c": random.choice(C_HEART_COLORS),
                "ph": random.uniform(0.0, 6.283),
            })
        if len(self.hearts) > 140:            # 手速再快也不能无限堆
            del self.hearts[:-140]

    def _hover_bubble(self, px, py):
        """鼠标刚挪到立绘上：冒一句气泡（有节流，鼠标乱晃不会刷屏）。"""
        now = _now()
        if self.bubble and now - self.bubble["t0"] < HOVER_REPEAT_MS:
            return
        self.bubble = {"text": self.picker.pick("hover", HOVER_LINES),
                       "t0": now, "life": BUBBLE_MS}
        self.log("pet hover")
        if self.hwnd:
            user32.SetTimer(self.hwnd, TIMER_ANIM, 16, None)

    def _sim_hover(self, px, py):
        """自检用：模拟鼠标移到立绘上。"""
        if self._hit_pet(px, py):
            self.hover = -1
            self.pet_hover = True
            self._hover_bubble(px, py)
            user32.InvalidateRect(self.hwnd, None, False)

    def _pet_touch(self, px, py):
        """摸一下：抖动 + 爱心 + 吐槽气泡，并按节流给数值。"""
        if self.pet.busy:
            return
        now = _now()
        self.pet_hover = False                  # 真点下去了，放大态先收掉
        self.pet.shake_t0 = now
        self._spawn_hearts(px, py, random.randint(6, 9))

        # 连点识别：窗口期内累计，第 3 次起改说「撸秃了」系列
        if now - self._last_pet_talk <= COMBO_MS:
            self._combo += 1
        else:
            self._combo = 1
        self._last_pet_talk = now
        if self._combo >= 3:
            text = self.picker.pick("pet_combo", PET_COMBO_LINES)
        else:
            text = self.picker.pick("pet", PET_LINES)
        self.bubble = {"text": text, "t0": now, "life": BUBBLE_MS}

        effective = now - self._last_pet_gain >= PET_GAIN_MS
        if not effective:
            self.log("pet ignored(throttle %dms)" % (now - self._last_pet_gain))
        else:
            self._last_pet_gain = now
            self.stats.apply(PET_DELTAS)
            self.totals["pet"] = self.totals.get("pet", 0) + 1
            self.pets_since_log += 1
            self.log("pet #%d combo=%d %s" % (self.totals["pet"], self._combo, self.stats.dump()))
            newly = self._check_titles()
            if self.pets_since_log >= PET_LOG_EVERY:
                gain = {"intimacy": self.pets_since_log, "mood": self.pets_since_log}
                self._record("pet", gain, bump=False)
                self.pets_since_log = 0
            self._save_state("pet")
            self.play_sound("open")             # 「欸，大狗！」当被撸的回应

        user32.SetTimer(self.hwnd, TIMER_ANIM, 16, None)
        user32.InvalidateRect(self.hwnd, None, False)

    def _tick_fx(self):
        """推进粒子/抖动/气泡。返回 True 表示还需要 16ms 定时器继续跑。"""
        now = _now()
        alive = False
        if self.hearts:
            self.hearts = [h for h in self.hearts if now - h["t0"] < h["life"]]
            alive = bool(self.hearts)
        if self.pet.shake_t0:
            if now - self.pet.shake_t0 >= SHAKE_MS:
                self.pet.shake_t0 = 0
            else:
                alive = True
        if self.bubble:
            if now - self.bubble["t0"] >= self.bubble["life"]:
                self.bubble = None
            else:
                alive = True
        return alive

    # ---------- 字体
    def _mkfont(self, px, weight=FW_NORMAL):
        return gdi32.CreateFontW(-px, 0, 0, 0, weight, 0, 0, 0, 0, 0, 0, 0, 0, FONT_FACE)

    def _build_fonts(self):
        self.fonts["title"] = self._mkfont(30, FW_BOLD)
        self.fonts["sub"] = self._mkfont(13)
        self.fonts["h2"] = self._mkfont(15, FW_SEMIBOLD)
        self.fonts["btn"] = self._mkfont(17, FW_SEMIBOLD)
        self.fonts["msg"] = self._mkfont(19, FW_BOLD)
        self.fonts["hint"] = self._mkfont(12)
        self.fonts["stat"] = self._mkfont(13)
        self.fonts["statv"] = self._mkfont(13, FW_SEMIBOLD)
        self.fonts["caption"] = self._mkfont(14)
        self.fonts["bubble"] = self._mkfont(13)

    # ---------- 创建
    def create(self):
        user32.SetProcessDPIAware()
        self._load_state()                       # 先读档，后面画的才是上次的状态
        hinst = kernel32.GetModuleHandleW(None)
        self.ref_dc = user32.GetDC(None)
        self.pet.load(self.ref_dc)
        self._build_fonts()

        cls_name = "RenYuGouWndCls"
        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.style = CS_HREDRAW | CS_VREDRAW
        wc.lpfnWndProc = self._wndproc_ref
        wc.hInstance = hinst
        wc.hCursor = user32.LoadCursorW(None, _res_id(IDC_ARROW))
        wc.hbrBackground = gdi32.GetStockObject(NULL_BRUSH)   # 背景完全自绘
        wc.lpszClassName = cls_name
        wc.hIcon = self._load_icon(ICON_BIG)
        wc.hIconSm = self._load_icon(ICON_SMALL)
        if not user32.RegisterClassExW(ctypes.byref(wc)):
            err = ctypes.get_last_error()
            if err != 1410:                       # ERROR_CLASS_ALREADY_EXISTS
                raise ctypes.WinError(err)

        style = WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX
        rect = wintypes.RECT(0, 0, CLIENT_W, CLIENT_H)
        user32.AdjustWindowRectEx(ctypes.byref(rect), style, False, WS_EX_APPWINDOW)
        w, h = rect.right - rect.left, rect.bottom - rect.top
        x = max(0, (user32.GetSystemMetrics(0) - w) // 2)
        y = max(0, (user32.GetSystemMetrics(1) - h) // 4)
        self.hwnd = user32.CreateWindowExW(WS_EX_APPWINDOW, cls_name, APP_NAME, style,
                                           x, y, w, h, None, None, hinst, None)
        if not self.hwnd:
            raise ctypes.WinError(ctypes.get_last_error())
        rc = wintypes.RECT()
        user32.GetClientRect(self.hwnd, ctypes.byref(rc))
        self.log("hwnd=0x%X client=%dx%d(real) %dx%d(const) cooldown=%dms"
                 % (self.hwnd, rc.right, rc.bottom, CLIENT_W, CLIENT_H, self.cooldown_ms))
        self._log_stats("init")
        user32.SetTimer(self.hwnd, TIMER_IDLE, 200, None)
        return self.hwnd

    def _load_icon(self, which):
        if not self.icon_path:
            path = os.path.join(tempfile.gettempdir(), "renyugou_app.ico")
            with open(path, "wb") as f:
                f.write(base64.b64decode(assets.ICON_ICO))
            self.icon_path = path
        size = 0 if which == ICON_BIG else 16
        return user32.LoadImageW(None, self.icon_path, IMAGE_ICON, size, size, LR_LOADFROMFILE)

    # ---------- 音效
    def _sound_path(self, key):
        """把内嵌的 WAV 落成临时文件（winsound 异步播放只认文件名）。"""
        path = self._sound_paths.get(key)
        if path:
            return path
        attr, fname = SOUND_WAV[key]
        raw = getattr(assets, attr, None)
        if not raw:
            return None
        folder = os.path.join(tempfile.gettempdir(), SOUND_DIR)
        try:
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, fname)
            with open(path, "wb") as f:
                f.write(base64.b64decode(raw))
        except OSError as exc:
            self.log("sound=%s WRITE-FAILED %r" % (key, exc))
            return None
        self._sound_paths[key] = path
        return path

    def play_sound(self, key):
        """播放指定片段；返回 False 表示没能播（缺素材或系统拒绝）。"""
        if winsound is None:
            self.log("sound=%s SKIPPED(no winsound)" % key)
            return False
        path = self._sound_path(key)
        if not path:
            self.log("sound=%s MISSING" % key)
            return False
        try:
            winsound.PlaySound(
                path,
                winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
        except Exception as exc:                      # 播放失败不能影响界面
            self.log("sound=%s FAILED %r" % (key, exc))
            return False
        self.log("sound=%s" % key)
        return True

    def stop_sound(self):
        if winsound is None:
            return
        try:
            winsound.PlaySound(None, winsound.SND_PURGE)
        except Exception:
            pass

    def log(self, text):
        line = "[%s] %s" % (time.strftime("%H:%M:%S"), text)
        self.log_lines.append(line)
        if self.debug_log:                       # 设了 RYG_DEBUG_LOG 就把运行日志落到该文件
            try:
                line2 = "%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), text)
                with open(self.debug_log, "a", encoding="utf-8") as f:
                    f.write(line2)
            except OSError:
                self.debug_log = None            # 写不了就关掉，别反复失败
        if self.snapshot_dir:
            try:
                with open(os.path.join(self.snapshot_dir, "_snapshot.log"), "a",
                          encoding="utf-8") as f:
                    f.write(line + "\n")
            except OSError:
                pass

    def _log_stats(self, tag):
        self.log("stats[%s] %s" % (tag, self.stats.dump()))

    # ---------- 数值结算
    def _settle(self, key):
        changes = DELTAS.get(key)
        if not changes:
            return
        applied = self.stats.apply(changes)
        self.log("settle %s nominal=%s real=%s" % (
            key,
            " ".join("%s%+d" % (k, v) for k, v in changes.items()),
            " ".join("%s%+d" % (k, real) for k, real, _v in applied)))
        self._log_stats("after:" + key)
        self._record(key, changes, applied)      # 记进本地存档
        self._check_titles()                     # 顺便看看有没有解锁新称号
        self._save_state(key)

    # ---------- 冷却
    def _cooldown_left(self):
        if not self.cooldown_until:
            return 0
        left = self.cooldown_until - _now()
        return left if left > 0 else 0

    def _basket_finished(self):
        """打球整套流程结束：启动冷却（或保持已取消状态）。"""
        if self.cooldown_until:
            self.log("cooldown kept left=%dms" % self._cooldown_left())
        else:
            self.cooldown_until = _now() + self.cooldown_ms
            self._cd_shown = -1
            self.log("cooldown start=%dms" % self.cooldown_ms)
        self._say("basket_rest")
        self._save_state("cooldown")            # 冷却要按墙上时钟存，跨重启继续倒计时

    def _on_reset_key(self):
        """F2 重置存档：连按两次（4 秒内）确认，避免误触。"""
        now = _now()
        if self._reset_armed and now - self._reset_armed < 4000:
            self._reset_armed = 0
            self.stats.reset()
            self.totals = dict((d[0], 0) for d in BTN_DEFS)
            self.totals["pet"] = 0
            self.history = []
            self.last_action = ""
            self.cooldown_until = 0
            self._cd_shown = -1
            self.titles = []
            self.msg_queue = []
            self._flash_until = 0
            self.pets_since_log = 0
            self._combo = 0
            self.hearts = []
            self.bubble = None
            self._refresh_idle()
            self._say("reset_done")
            self.log("save reset by user(F2)")
            self._save_state("reset")
        else:
            self._reset_armed = now
            self._say("reset_armed")
            self.log("save reset armed(F2 again to confirm)")

    def _cancel_cooldown(self, reason):
        if self.cooldown_until:
            self.log("cooldown cancelled by %s" % reason)
            self.cooldown_until = 0
            self._cd_shown = -1
            if self.pet.msg in ("basket_rest", "basket_cd"):
                self._to_idle()
            self._save_state("cooldown-cancel")

    def _save_hint(self):
        """标题栏右侧的存档状态行。"""
        if not self.persist:
            return "自检模式（本次不写存档）"
        parts = ["第 %d 次启动" % self.sessions, "累计互动 %d 次" % sum(self.totals.values())]
        title = self._current_title()
        if title:
            parts.append("称号：" + title)
        if self.last_action:
            parts.append("上次：" + self.last_action)
        if self._cooldown_left():
            parts.append("打球冷却中")
        parts.append("存档 %%LOCALAPPDATA%%\\%s" % APP_NAME)
        return "自动存档 · " + " · ".join(parts)

    # ---------- 绘制基元（矩形一律用 x, y, w, h）
    @staticmethod
    def _panel(hdc, rect, radius, fill, border=None, border_w=1):
        x, y, w, h = rect
        brush = gdi32.CreateSolidBrush(fill)
        pen = gdi32.CreatePen(PS_SOLID, border_w, border) if border is not None \
            else gdi32.GetStockObject(NULL_PEN)
        gdi32.SaveDC(hdc)
        gdi32.SelectObject(hdc, brush)
        gdi32.SelectObject(hdc, pen)
        gdi32.RoundRect(hdc, x, y, x + w - 1, y + h - 1, radius * 2, radius * 2)
        gdi32.RestoreDC(hdc, -1)
        gdi32.DeleteObject(brush)
        if border is not None:
            gdi32.DeleteObject(pen)

    @staticmethod
    def _fill(hdc, rect, color):
        x, y, w, h = rect
        brush = gdi32.CreateSolidBrush(color)
        rc = wintypes.RECT(x, y, x + w, y + h)
        user32.FillRect(hdc, ctypes.byref(rc), brush)
        gdi32.DeleteObject(brush)

    def _text(self, hdc, text, rect, font_key, color, flags=0):
        x, y, w, h = rect
        gdi32.SaveDC(hdc)
        gdi32.SelectObject(hdc, self.fonts[font_key])
        gdi32.SetTextColor(hdc, color)
        gdi32.SetBkMode(hdc, TRANSPARENT)
        rc = wintypes.RECT(x, y, x + w, y + h)
        user32.DrawTextW(hdc, text, -1, ctypes.byref(rc), flags | DT_NOPREFIX)
        gdi32.RestoreDC(hdc, -1)

    # ---------- 整屏绘制
    def paint(self, hdc):
        self._fill(hdc, (0, 0, CLIENT_W, CLIENT_H), C_BG)
        self._text(hdc, APP_NAME, (MARGIN, TITLE_Y, 300, 40), "title", C_TITLE, DT_LEFT)
        self._text(hdc, APP_SUBTITLE, (MARGIN + 2, TITLE_Y + 42, 400, 20), "sub", C_SUB, DT_LEFT)
        self._text(hdc, self._save_hint(), (MARGIN, TITLE_Y + 44, CLIENT_W - 2 * MARGIN, 20),
                   "hint", C_SUB, DT_RIGHT | DT_SINGLELINE)
        self._paint_pet_card(hdc)
        self._paint_ops_card(hdc)
        self._paint_stat_card(hdc)
        self._paint_msg_card(hdc)

    def _paint_pet_card(self, hdc):
        self._panel(hdc, PET_CARD, 16, C_CARD, C_BORDER)
        self._panel(hdc, PET_STAGE, 12, C_CARD_SOFT, C_DIVIDER)

        surf = self.pet.surfaces[self.pet.showing]
        sx, sy, sw, sh = PET_STAGE
        zoom = 1.03 if (self.pet_hover and not self.pet.busy) else 1.0   # 被盯着会微微凑近
        dw = int(round(surf.w * zoom))
        dh = int(round(surf.h * self.pet.factor * zoom))
        bx = sx + (sw - dw) // 2
        by = sy + sh - dh

        # 被摸的瞬间左右抖两下，幅度随进度衰减
        if self.pet.shake_t0:
            p = _clamp01((_now() - self.pet.shake_t0) / float(SHAKE_MS))
            bx += int(round(math.sin(p * math.pi * 6.0) * 7.0 * (1.0 - p)))
        self.pet_rect = (bx, by, dw, dh)         # 命中测试用这一帧的实位置
        surf.blit(hdc, bx, by, dw, dh)

        self._paint_hearts(hdc)
        self._paint_bubble(hdc)

        x, _y, w, _h = PET_CARD
        self._text(hdc, "任禹狗 · " + self.pet.caption, (x, PET_CAPTION_Y, w, 22),
                   "caption", C_SUB, DT_CENTER | DT_SINGLELINE)

    # ---------- 爱心粒子 / 对话气泡
    @staticmethod
    def _heart(hdc, cx, cy, r, color):
        """两个圆 + 一个倒三角拼出来的实心爱心（纯几何，不依赖字体里有 ♥ 字形）。"""
        d = r * 0.5
        top = cy - d
        brush = gdi32.CreateSolidBrush(color)
        gdi32.SaveDC(hdc)
        gdi32.SelectObject(hdc, brush)
        gdi32.SelectObject(hdc, gdi32.GetStockObject(NULL_PEN))
        gdi32.Ellipse(hdc, int(cx - 2 * d), int(top - d), int(cx) + 1, int(top + d) + 1)
        gdi32.Ellipse(hdc, int(cx), int(top - d), int(cx + 2 * d) + 1, int(top + d) + 1)
        pts = (POINT * 3)(POINT(int(cx - 2 * d), int(top + d * 0.4)),
                          POINT(int(cx + 2 * d), int(top + d * 0.4)),
                          POINT(int(cx), int(cy + d * 2.0)))
        gdi32.Polygon(hdc, pts, 3)
        gdi32.RestoreDC(hdc, -1)
        gdi32.DeleteObject(brush)

    def _paint_hearts(self, hdc):
        if not self.hearts:
            return
        now = _now()
        for h in self.hearts:
            age = now - h["t0"]
            p = _clamp01(age / float(h["life"]))
            x = h["x0"] + h["vx"] * age + math.sin(age / 170.0 + h["ph"]) * 6.0
            y = h["y0"] + h["vy"] * age
            self._heart(hdc, x, y, h["r"] * (1.0 - 0.5 * p), h["c"])

    def _measure(self, hdc, text, font_key):
        gdi32.SaveDC(hdc)
        gdi32.SelectObject(hdc, self.fonts[font_key])
        rc = wintypes.RECT(0, 0, 0, 0)
        user32.DrawTextW(hdc, text, -1, ctypes.byref(rc),
                         DT_SINGLELINE | DT_CALCRECT | DT_NOPREFIX)
        gdi32.RestoreDC(hdc, -1)
        return rc.right, rc.bottom

    def _paint_bubble(self, hdc):
        if not self.bubble:
            return
        now = _now()
        b = self.bubble
        tw, th = self._measure(hdc, b["text"], "bubble")
        bw, bh = tw + 26, th + 18

        sx, sy, sw, sh = PET_STAGE
        pr = self.pet_rect or (sx, sy, sw, sh)
        cx = pr[0] + pr[2] / 2.0
        top = pr[1] - 16 - bh                        # 默认浮在立绘头顶上方
        top = max(sy + 10, min(top, sy + sh - bh - 34))
        x = max(sx + 8, min(int(cx - bw / 2.0), sx + sw - bw - 8))

        p = _clamp01((now - b["t0"]) / 220.0)        # 出现时轻轻往上弹一下
        y = int(top + (1.0 - _ease_out(p)) * 10)

        self._panel(hdc, (x, y, bw, bh), 10, C_CARD, C_BORDER)
        tail = (POINT * 3)(POINT(x + bw // 2 - 8, y + bh - 1),
                           POINT(x + bw // 2 + 8, y + bh - 1),
                           POINT(x + bw // 2, y + bh + 9))
        brush = gdi32.CreateSolidBrush(C_CARD)
        pen = gdi32.CreatePen(PS_SOLID, 1, C_BORDER)
        gdi32.SaveDC(hdc)
        gdi32.SelectObject(hdc, brush)
        gdi32.SelectObject(hdc, pen)
        gdi32.Polygon(hdc, tail, 3)
        gdi32.RestoreDC(hdc, -1)
        gdi32.DeleteObject(brush)
        gdi32.DeleteObject(pen)
        # 尾巴与气泡的接缝盖掉，避免出现一条横线
        self._fill(hdc, (x + bw // 2 - 7, y + bh - 2, 14, 2), C_CARD)
        self._text(hdc, b["text"], (x, y + 2, bw, bh - 4), "bubble", C_TEXT,
                   DT_CENTER | DT_SINGLELINE)

    def _paint_ops_card(self, hdc):
        x, y, w, h = OPS_CARD
        self._panel(hdc, OPS_CARD, 16, C_CARD, C_BORDER)
        self._text(hdc, "操作栏", (x + 20, y + 16, 200, 22), "h2", C_TEXT, DT_LEFT | DT_SINGLELINE)
        self._text(hdc, "点击执行", (x + w - 110, y + 19, 90, 20), "hint", C_SUB,
                   DT_RIGHT | DT_SINGLELINE)

        for i, (_kind, label, base, hov, down) in enumerate(BTN_DEFS):
            rect = (x + 20, BTN_Y[i], BTN_W, BTN_H)
            if not self._enabled(i):
                bg, fg = C_DISABLED_BG, C_DISABLED_FG
            else:
                fg = C_WHITE
                bg = down if self.pressed == i else (hov if self.hover == i else base)
            self._panel(hdc, rect, 10, bg)
            self._text(hdc, label, (rect[0], rect[1] + (BTN_H - 26) // 2, rect[2], 26),
                       "btn", fg, DT_CENTER | DT_SINGLELINE)

        left = self._cooldown_left()
        if self.pet.busy:
            hint, color = "正在执行，请稍候…", MSG_COLORS.get(self.pet.msg, C_SUB)
        elif left:
            hint, color = "打球冷却中（剩 %d 秒）" % (-(-left // 1000)), C_TEAL
        else:
            hint, color = "可进行操作 · 点一下右边的任禹狗也能互动", C_SUB
        self._text(hdc, hint, (x + 20, y + h - 28, 360, 22), "hint", color,
                   DT_LEFT | DT_SINGLELINE)

    def _paint_stat_card(self, hdc):
        x, y, w, h = STAT_CARD
        self._panel(hdc, STAT_CARD, 16, C_CARD, C_BORDER)
        self._text(hdc, "状态栏", (x + 20, y + 14, 200, 22), "h2", C_TEXT, DT_LEFT | DT_SINGLELINE)
        self._text(hdc, self._title_note(), (x + w - 236, y + 17, 216, 20), "hint", C_AMBER,
                   DT_RIGHT | DT_SINGLELINE)
        self._fill(hdc, (x + 20, y + 38, w - 40, 1), C_DIVIDER)

        now = _now()
        for i, key in enumerate(self.stats.order):
            ry = y + STAT_ROWS_OFFSET + i * STAT_ROW_H
            v = self.stats.value[key]
            cap = self.stats.cap[key]

            self._text(hdc, self.stats.label[key], (x + 20, ry + 4, 60, 20), "stat", C_TEXT,
                       DT_LEFT | DT_SINGLELINE)
            val = "%d / %d" % (v, cap) if cap is not None else "%d" % v
            self._text(hdc, val, (x + 268, ry + 4, 66, 20), "statv", C_TEXT,
                       DT_RIGHT | DT_SINGLELINE)

            track = (x + 86, ry + 10, 176, 8)
            self._panel(hdc, track, 4, C_TRACK)
            denom = cap if cap is not None else max(100, v)     # 无上限项按「已达成 / 自身上限」显示
            ratio = 0.0 if denom <= 0 else min(1.0, v / float(denom))
            fw = int(round(track[2] * ratio))
            if fw > 0:
                self._panel(hdc, (track[0], track[1], max(fw, 6), track[3]), 4,
                            self.stats.color[key])

            d = self.stats.delta.get(key)
            if d and now < d[1]:
                self._text(hdc, "%+d" % d[0], (x + 338, ry + 4, 42, 20), "statv",
                           C_UP if d[0] > 0 else C_DOWN, DT_LEFT | DT_SINGLELINE)

    def _paint_msg_card(self, hdc):
        x, y, w, h = MSG_CARD
        self._panel(hdc, MSG_CARD, 16, C_CARD, C_BORDER)
        self._text(hdc, "系统提示", (x + 20, y + 14, 200, 22), "h2", C_TEXT, DT_LEFT | DT_SINGLELINE)
        self._fill(hdc, (x + 20, y + 38, w - 40, 1), C_DIVIDER)

        key = self.pet.msg
        color = MSG_COLORS.get(key, C_SUB)
        text = self._msg_text()

        tx = x + 20
        if key != "idle":
            self._fill(hdc, (x + 20, y + 50, 4, 44), color)
            tx = x + 36
        self._text(hdc, text, (tx, y + 48, w - (tx - x) - 20, h - 62),
                   "msg", color, DT_LEFT | DT_WORDBREAK)

    # ---------- 交互
    def _enabled(self, idx):
        if self.pet.busy:
            return False
        if BTN_DEFS[idx][0] == "basket" and self._cooldown_left() > 0:
            return False                                  # 冷却中：变灰、不可执行
        return True

    def _hit_button(self, px, py):
        """命中测试：冷却中的打篮球按钮仍然可命中（点了要给出提示）。"""
        if self.pet.busy:
            return -1
        x = OPS_CARD[0]
        for i in range(len(BTN_DEFS)):
            bx, by = x + 20, BTN_Y[i]
            if bx <= px < bx + BTN_W and by <= py < by + BTN_H:
                return i
        return -1

    def _wndproc(self, hwnd, msg, wparam, lparam):
        try:
            return self._handle(hwnd, msg, wparam, lparam)
        except Exception as exc:                       # 异常绝不穿透到系统
            self.log("EXC %r" % (exc,))
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _handle(self, hwnd, msg, wparam, lparam):
        if msg == WM_PAINT:
            ps = PAINTSTRUCT()
            hdc = user32.BeginPaint(hwnd, ctypes.byref(ps))
            self._present(hdc)
            user32.EndPaint(hwnd, ctypes.byref(ps))
            return 0

        if msg == WM_PRINTCLIENT:
            self.paint(wintypes.HDC(wparam))
            return 0

        if msg == WM_ERASEBKGND:
            return 1

        if msg == WM_MOUSEMOVE:
            x = ctypes.c_short(lparam & 0xFFFF).value
            y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
            h = self._hit_button(x, y)
            ph = not self.pet.busy and self._hit_pet(x, y)
            if h != self.hover or ph != self.pet_hover:
                self.hover = h
                self.pet_hover = ph
                user32.InvalidateRect(hwnd, None, False)
                if ph:
                    self._hover_bubble(x, y)
            if not self.tracking_leave:
                tme = TRACKMOUSEEVENT(ctypes.sizeof(TRACKMOUSEEVENT), TME_LEAVE, hwnd, 0)
                user32.TrackMouseEvent(ctypes.byref(tme))
                self.tracking_leave = True
            return 0

        if msg == WM_MOUSELEAVE:
            self.tracking_leave = False
            self.hover = -1
            self.pet_hover = False
            self.pet_pressed = False
            user32.InvalidateRect(hwnd, None, False)
            return 0

        if msg == WM_LBUTTONDOWN:
            x = ctypes.c_short(lparam & 0xFFFF).value
            y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
            h = self._hit_button(x, y)
            self.pet_pressed = (h < 0 and self._can_pet(x, y))
            self.log("mouse down x=%d y=%d hit=%d%s"
                     % (x, y, h, " pet" if self.pet_pressed else ""))
            if h >= 0 and self._enabled(h):
                self.pressed = h
                user32.SetCapture(hwnd)
                user32.InvalidateRect(hwnd, None, False)
            elif h >= 0:
                self.pressed = -1                  # 冷却中的按钮不显示按下态
            elif self.pet_pressed:
                user32.SetCapture(hwnd)
            return 0

        if msg == WM_LBUTTONUP:
            user32.ReleaseCapture()
            x = ctypes.c_short(lparam & 0xFFFF).value
            y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
            if self.pressed >= 0:
                h = self._hit_button(x, y)
                idx, self.pressed = self.pressed, -1
                if h == idx:
                    self._activate(idx)
                user32.InvalidateRect(hwnd, None, False)
                return 0
            if self.pet_pressed:
                self.pet_pressed = False
                if self._can_pet(x, y):
                    self._pet_touch(x, y)
                    return 0
            else:
                # 冷却中的打篮球按钮：单击也要给提示
                h = self._hit_button(x, y)
                if h >= 0 and not self._enabled(h):
                    self._activate(h)
            return 0

        if msg == WM_SETCURSOR:
            if (self.hover >= 0 and self._enabled(self.hover)) or self.pet_hover:
                user32.SetCursor(user32.LoadCursorW(None, _res_id(IDC_HAND)))
            else:
                user32.SetCursor(user32.LoadCursorW(None, _res_id(IDC_ARROW)))
            return 1

        if msg == WM_TIMER:
            if wparam == TIMER_ANIM:
                busy = self.pet.tick()
                fx = self._tick_fx()
                if not busy and not fx:
                    user32.KillTimer(hwnd, TIMER_ANIM)
                user32.InvalidateRect(hwnd, None, False)
            elif wparam == TIMER_SNAP:
                self._snapshot_driver()
            elif wparam == TIMER_IDLE:
                if self._tick_idle():
                    user32.InvalidateRect(hwnd, None, False)
            return 0

        if msg == WM_CLOSE:
            self._save_state("close")
            user32.DestroyWindow(hwnd)
            return 0

        if msg == WM_KEYDOWN:
            if wparam == VK_F2:
                self._on_reset_key()
                user32.InvalidateRect(hwnd, None, False)
            return 0

        if msg == WM_DESTROY:
            for tid in (TIMER_ANIM, TIMER_SNAP, TIMER_IDLE):
                user32.KillTimer(hwnd, tid)
            self._save_state("exit")             # 退出前落盘
            self.stop_sound()
            user32.PostQuitMessage(0)
            return 0

        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _tick_idle(self):
        """低频维护：冷却到期、倒计时刷新、数值浮标过期、称号贺电排队。返回是否需要重绘。"""
        now = _now()
        dirty = False

        if self.pet.busy:
            self._quiet_since = 0                 # 正在播动画，贺电先压着
            return dirty

        # 贺电：先等动画播完，安静一小会儿再弹，别把动作台词盖掉
        if self._flash_until:
            if now >= self._flash_until:
                self._flash_until = 0
                self._to_idle()
                dirty = True
            return dirty
        if self.msg_queue:
            if not self._quiet_since:
                self._quiet_since = now
            elif now - self._quiet_since >= NOTICE_DELAY_MS:
                self._quiet_since = 0
                self._flash(self.msg_queue.pop(0))
                dirty = True
            return dirty
        self._quiet_since = 0

        if self.cooldown_until and now >= self.cooldown_until:
            self.cooldown_until = 0
            self._cd_shown = -1
            if self.pet.msg in ("basket_rest", "basket_cd"):
                self._to_idle()
            self.log("cooldown expired -> basket unlocked")
            dirty = True
        elif self.cooldown_until:
            left = -(-(self.cooldown_until - now) // 1000)
            if left != self._cd_shown:
                self._cd_shown = left
                dirty = True

        for _key, (_amount, expire) in list(self.stats.delta.items()):
            if now >= expire:
                if now - expire < 400:          # 刚过期那一拍重绘一次，擦掉 +N
                    dirty = True
                else:
                    self.stats.delta.pop(_key, None)
        return dirty

    def _present(self, hdc):
        if not self.hdc_back:
            self.hdc_back = gdi32.CreateCompatibleDC(hdc)
            self.hbmp_back = gdi32.CreateCompatibleBitmap(hdc, CLIENT_W, CLIENT_H)
            gdi32.SelectObject(self.hdc_back, self.hbmp_back)
        self.paint(self.hdc_back)
        gdi32.BitBlt(hdc, 0, 0, CLIENT_W, CLIENT_H, self.hdc_back, 0, 0, SRCCOPY)

    def _activate(self, idx, outcome=None):
        kind = BTN_DEFS[idx][0]

        if kind == "basket" and self._cooldown_left() > 0:
            self._say("basket_cd")
            self.log("ignored=basket(cooldown left=%dms)" % self._cooldown_left())
            return

        self.pet.end_cb = self._basket_finished if kind == "basket" else None
        if not self.pet.trigger(kind, outcome=outcome):
            self.log("ignored=%s(busy)" % kind)
            return

        if kind == "eat":
            self._cancel_cooldown("eat")        # 进食立刻解除打球冷却

        self.play_sound(kind if kind != "basket" else "basket")
        self.log("action=%s%s" % (kind, (" outcome=" + self.pet.outcome) if kind == "basket" else ""))
        if kind != "basket":
            self._settle(kind)                  # 读书/吃饭：点击即结算
        user32.SetTimer(self.hwnd, TIMER_ANIM, 16, None)
        user32.InvalidateRect(self.hwnd, None, False)

    # ---------- 自检截图
    def _capture(self, path):
        hdc = gdi32.CreateCompatibleDC(self.ref_dc)
        bmi = BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.biWidth, bmi.biHeight = CLIENT_W, -CLIENT_H
        bmi.biPlanes, bmi.biBitCount, bmi.biCompression = 1, 32, 0
        ppv = ctypes.c_void_p()
        hbmp = gdi32.CreateDIBSection(self.ref_dc, ctypes.byref(bmi), DIB_RGB_COLORS,
                                      ctypes.byref(ppv), None, 0)
        old = gdi32.SelectObject(hdc, hbmp)
        ok = user32.PrintWindow(self.hwnd, hdc, PW_CLIENTONLY)
        im = Image.frombytes("RGB", (CLIENT_W, CLIENT_H),
                             ctypes.string_at(ppv, CLIENT_W * CLIENT_H * 4), "raw", "BGRX")
        im.save(path)
        gdi32.SelectObject(hdc, old)
        gdi32.DeleteObject(hbmp)
        gdi32.DeleteDC(hdc)
        self.log("shot=%s printwindow=%s" % (os.path.basename(path), ok))

    def _snapshot_driver(self):
        now = _now()
        while self.snap_idx < len(self.snap_steps):
            at, action = self.snap_steps[self.snap_idx]
            if now < self.snap_t0 + at:
                return
            if action in ("read", "eat", "basket"):
                self._activate([d[0] for d in BTN_DEFS].index(action))
            elif action.startswith("basket:"):
                self._activate([d[0] for d in BTN_DEFS].index("basket"), outcome=action[7:])
            elif action.startswith("try:"):        # 自检：模拟「忙碌/冷却时点击」
                self._activate([d[0] for d in BTN_DEFS].index(action[4:]))
            elif action == "hover":                # 自检：模拟鼠标移到立绘上
                self._sim_hover(*PET_HOVER_POINT)
            elif action == "pet":                  # 自检：模拟摸一下立绘
                self._pet_touch(*PET_HOVER_POINT)
            elif action.startswith("shot:"):
                self._capture(os.path.join(self.snapshot_dir, action[5:] + ".png"))
            elif action == "quit":
                user32.KillTimer(self.hwnd, TIMER_SNAP)
                user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)
                return
            self.snap_idx += 1

    def run_snapshots(self):
        # 时间线按真实时长排：收起 180ms / 升起 260ms；读书·吃饭整套 3880ms；
        # 打篮球整套 5320ms（结束时才起冷却）；自检冷却 8000ms；气泡 2200ms。
        # 每张截图都要躲开上一批气泡/粒子/贺电，否则立绘比对会被它们污染。
        # 完整覆盖：初始 -> 摸摸头(悬停/连点/数值) -> 读书(收起/升起/停留/拒绝重复点击/复位)
        #   -> 吃饭 -> 打球(摔倒) -> 结局中拒绝点击 -> 冷却 -> 冷却点击 -> 吃饭解冷却
        #   -> 打球(开心) -> 自然冷却到期 -> 打球(发怒)
        self.snap_steps = [
            (300, "shot:01_idle"),
            # --- 摸摸头：600~5100ms ---
            (600, "hover"),                       # 鼠标移到立绘上：800ms 后确实可见
            (700, "shot:20_pet_hover"),           # 头顶冒出对话气泡
            (1200, "pet"),                        # 第 1 次：生效（亲密度/心情 +1）
            (1300, "shot:21_pet_touch"),          # 抖动 + 爱心 + 数值浮标
            (1700, "pet"),                        # 第 2 次：距上次 500ms，应被节流拒绝
            (2100, "pet"),                        # 第 3 次：距第 1 次 900ms，生效且进连点吐槽档
            (2200, "shot:22_pet_combo"),          # 连点 -> 「撸秃了」系列 + 爱心更多
            (5100, "shot:23_pet_settled"),        # 气泡(2100+2200)与粒子都散尽，画面回稳态
            # --- 读书：5300~9180ms ---
            (5300, "read"),
            (5390, "shot:02_read_collapse"),      # 封面正在被压扁
            (5570, "shot:03_read_rise"),          # 读书图正在升起
            (6000, "shot:04_read_hold"),
            (6500, "try:read"),                   # 忙碌中重复点击 -> 必须被拒绝
            (6600, "shot:05_after_busy_click"),   # 画面应与 04 完全一致
            (8600, "shot:06_read_hold_late"),     # 接近 3 秒时仍是读书态
            (9300, "shot:07_read_back"),
            # 「初次见面」贺电在 10180~12980ms 弹，先让它播完再动别的
            # --- 吃饭：13100~16980ms ---
            (13100, "eat"),
            (13700, "shot:08_eat_hold"),
            (17100, "shot:09_eat_back"),
            # --- 打篮球（强制摔倒）：17300~22620ms，冷却 22620~30620ms ---
            (17300, "basket:fall"),
            (17900, "shot:10_basket_play"),
            (20300, "shot:11_basket_fall"),
            (20800, "try:basket"),                # 结局动画中点击 -> 必须被拒绝
            (20900, "shot:12_after_busy_click"),  # 画面应与 11 完全一致
            (21800, "shot:13_basket_back_gray"),  # 已回初始图，按钮变灰
            (22100, "try:basket"),                # 冷却中点击 -> 只给提示，不执行
            (22200, "shot:14_cooldown_click"),
            # --- 吃饭解除冷却：23000~26880ms ---
            (23000, "eat"),                       # 冷却结束前出手：吃饭立刻解冷却
            (27100, "shot:15_after_eat_cancel"),  # 吃饭整套跑完，冷却已解除，按钮恢复可用
            # --- 打篮球（强制开心）：27500~32820ms，冷却 32820~40820ms ---
            (27500, "basket:happy"),
            (30600, "shot:16_basket_happy"),
            (33000, "shot:17_rest_gray"),
            (41500, "shot:18_after_cooldown"),    # 冷却自然到期 -> 解锁、画面复位
            # --- 打篮球（强制发怒）：41700~47020ms ---
            (41700, "basket:angry"),
            (44400, "shot:19_basket_angry"),
            (47400, "quit"),
        ]
        self.snap_t0 = _now()
        user32.SetTimer(self.hwnd, TIMER_SNAP, 20, None)
        self.loop()

    def loop(self):
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def show(self):
        user32.ShowWindow(self.hwnd, SW_SHOWNORMAL)
        user32.UpdateWindow(self.hwnd)
        self.play_sound("open")          # 启动音效：欸，大狗！


# ---------------------------------------------------------------- 数值逻辑自检


def _data_app():
    """只带数据成员的 App 实例：给纯逻辑自检用，不开窗也不碰真实存档。"""
    a = App.__new__(App)
    a.pet = Pet()
    a.stats = Stats()
    a.picker = LinePicker()
    a.hwnd = None
    a.fonts = {}
    a.log_lines = []
    a._sound_paths = {}
    a.cooldown_ms = COOLDOWN_MS
    a.cooldown_until = 0
    a._cd_shown = -1
    a.snapshot_dir = "selftest"          # 让 persist=False，避免污染真实存档
    a._init_persist()
    a.pet.line_cb = a._pick_line
    return a


def run_selftest():
    """纯逻辑自检（不开窗）：验证初始值、上限夹取、下限夹取、无上限项增长。"""
    rows = []

    def check(label, got, want):
        rows.append("%-28s got=%-14s want=%-14s %s"
                    % (label, got, want, "OK" if got == want else "FAIL"))

    s = Stats()
    check("初始值", s.dump(),
          "mood=70 vitality=80 intimacy=10 intellect=10 stomach=30")

    s.apply({"mood": 1000})
    check("心情上限夹取", s.value["mood"], 100)
    s.apply({"mood": -1000})
    check("心情下限夹取", s.value["mood"], 0)
    s.apply({"stomach": 1000})
    check("胃袋上限夹取", s.value["stomach"], 100)
    s.apply({"vitality": -1000})
    check("活力下限夹取", s.value["vitality"], 0)

    s2 = Stats()
    s2.apply({"intellect": 1000, "intimacy": 1000})
    s2.apply({"intellect": 1000, "intimacy": 1000})
    check("智力无上限", s2.value["intellect"], 2010)
    check("亲密度无上限", s2.value["intimacy"], 2010)

    # 连续互动的累计结果（与自检时间表一致）
    s3 = Stats()
    for key in ("read", "eat", "basket_fall", "eat", "basket_happy", "basket_angry"):
        s3.apply(DELTAS[key])
    check("六连互动累计", s3.dump(),
          "mood=65 vitality=45 intimacy=60 intellect=25 stomach=70")

    # ---- 存档读写
    sdir = tempfile.mkdtemp(prefix="ryg_save_")
    spath = os.path.join(sdir, SAVE_FILE)
    s4 = Stats()
    s4.apply({"intellect": 1000, "mood": -20})
    write_save(spath, {
        "version": SAVE_VERSION, "saved_at": "now", "sessions": 3,
        "stats": dict((k, s4.value[k]) for k in s4.order),
        "totals": {"read": 2, "eat": 1, "basket": 0},
        "history": [{"t": "09-15 23:00", "action": "read", "label": "读书"}],
        "cooldown_deadline": time.time() + 30,
    })
    back = read_save(spath)
    check("存档可读回", bool(back) and back.get("sessions"), 3)
    s5 = Stats()
    s5.load_values(back["stats"])
    check("存档恢复数值", s5.dump(), s4.dump())
    check("冷却跨重启剩余>25s", int(float(back["cooldown_deadline"]) - time.time()) > 25, True)
    check("行动记录条数", len(back["history"]), 1)
    s5.reset()
    check("重置回初始值", s5.dump(),
          "mood=70 vitality=80 intimacy=10 intellect=10 stomach=30")

    s6 = Stats()                                   # 存档被手改：越界/非法值一律夹掉
    s6.load_values({"mood": 9999, "intellect": -5, "stomach": "x", "unknown": 1})
    check("脏存档夹取", s6.dump(),          # 越界夹到界限内，非法值忽略
          "mood=100 vitality=80 intimacy=10 intellect=0 stomach=30")

    write_save(spath, {"version": SAVE_VERSION})    # 覆盖写不应抛异常
    check("覆盖写存档", read_save(spath).get("version"), SAVE_VERSION)

    # ---- 台词抽取：池子里每条都能抽到，且绝不连续重复
    pk = LinePicker()
    pool = ACTION_LINES["read"]
    got_list = [pk.pick("read", pool) for _ in range(60)]
    dup = [i for i in range(1, len(got_list)) if got_list[i] == got_list[i - 1]]
    check("台词不连续重复", len(dup), 0)
    check("台词都在池子里", all(t in pool for t in got_list), True)
    check("台词抽得到多条", len(set(got_list)) >= 3, True)
    pk2 = LinePicker()
    check("空池返回空串", pk2.pick("nope", ()), "")
    check("单句池恒定", pk2.pick("one", ["唯一"]), "唯一")
    check("兜底表不为空", all(MSG_TEXTS.get(k) for k in ACTION_LINES), True)
    check("每一档台词都够厚", min(len(v) for v in ACTION_LINES.values() if len(v) > 1) >= 3, True)
    check("basket_rest 都带 %d", all("%d" in t for t in ACTION_LINES["basket_rest"]), True)

    # ---- 称号：条件判定 + 只解锁一次 + 最高阶优先
    t = _data_app()
    check("初始无称号", t._current_title(), None)
    t._settle("read")
    check("一次互动解锁「初次见面」", t._current_title(), "初次见面")
    n_after = len(t.titles)
    t._check_titles()
    check("已解锁的不重复入账", len(t.titles), n_after)
    for _ in range(4):
        t._settle("read")
    check("读书 5 次解锁「小书虫」", t.titles[-1], "bookworm")
    t.totals["pet"] = 60
    t._check_titles()
    check("摸头 60 次解锁「撸狗狂魔」", "toucher" in t.titles, True)
    t.totals["read"] = 20
    t.stats.value["intellect"] = 300
    t._check_titles()
    check("智力 300 解锁「任博士」", "smartest" in t.titles, True)
    check("当前称号取最高阶", t._current_title(), "任博士")
    check("称号文案含数量", "称号 · 任博士" in t._title_note(), True)
    check("称号 id 全部带名称", all(isinstance(n, str) and n for _i, n, _d, _f in TITLE_DEFS), True)

    # ---- 摸头：给的数值、节流计数由 totals 自己维护
    p = _data_app()
    n0 = p.stats.value["intimacy"]
    p._last_pet_gain = 0
    p._combo, p._last_pet_talk = 0, 0
    p._pet_touch(700, 300)
    p._pet_touch(700, 300)                   # 紧接着第二次应被节流
    check("摸头次数只算生效的", p.totals["pet"], 1)
    check("摸头涨亲密度", p.stats.value["intimacy"] - n0, 1)
    check("摸头冒爱心", len(p.hearts) > 0, True)
    check("摸头冒气泡", bool(p.bubble), True)
    check("连点进入吐槽档", p._combo, 2)

    # ---- 一次互动只说一句：收起 -> 升起 -> 停留，提示条不许中途换句子
    for kind, pool in (("eat", ACTION_LINES["eat"]), ("read", ACTION_LINES["read"])):
        q = _data_app()
        q.pet.trigger(kind)
        first = q.pet.msg_text
        check("%s 开局就抽好台词" % kind, first in pool, True)
        q.pet.step_t0 = _now() - COLLAPSE_MS - 1        # 直接把「收起」那一步走完
        q.pet.tick()                                    # -> 进入「升起」
        check("%s 升起时沿用同一句" % kind, q.pet.msg_text, first)
        q.pet.step_t0 = _now() - RISE_MS - 1            # 走完升起 -> 进入停留
        q.pet.tick()
        check("%s 停留时仍是同一句" % kind, q.pet.msg_text, first)
    # 两次吃饭之间必须换句子（否则随机台词库就白做了）
    q = _data_app()
    q.pet.trigger("eat")
    first = q.pet.msg_text
    q.pet.steps, q.pet.busy = [], False
    q._to_idle()
    q.pet.trigger("eat")
    check("连续两次吃饭换句子", q.pet.msg_text != first, True)

    try:
        os.remove(spath)
        os.rmdir(sdir)
    except OSError:
        pass

    if getattr(sys, "frozen", False):            # 打包后：写到 exe 同目录
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "build")
    out = os.path.join(base, "_selftest.txt")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    fails = [r for r in rows if not r.endswith("OK")]
    header = ["--- 数值逻辑自检 ---", ""]
    tail = ["", "结果：%d 项通过，%d 项失败" % (len(rows) - len(fails), len(fails))]
    text = "\n".join(header + rows + tail)
    with open(out, "w", encoding="utf-8") as f:
        f.write(text)
    print(text)
    return 1 if fails else 0


def main():
    argv = sys.argv[1:]
    if "--selftest" in argv:
        sys.exit(run_selftest())

    snap = None
    if "--snapshot" in argv:
        i = argv.index("--snapshot")
        snap = argv[i + 1] if i + 1 < len(argv) else os.getcwd()
        os.makedirs(snap, exist_ok=True)
        for name in os.listdir(snap):
            if name.endswith(".png"):
                try:
                    os.remove(os.path.join(snap, name))
                except OSError:
                    pass
        open(os.path.join(snap, "_snapshot.log"), "w", encoding="utf-8").close()

    app = App(snapshot_dir=snap, cooldown_ms=SNAP_COOLDOWN_MS if snap else COOLDOWN_MS)
    app.create()
    app.show()
    if snap:
        app.run_snapshots()
    else:
        app.loop()


if __name__ == "__main__":
    main()
