#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数独 for M5Stack CardputerZero — 移植自 car-dash/games/sudoku (web 版)

逻辑 1:1 移植: 位掩码回溯生成全解 → 挖洞逐步唯一解校验 → 三档难度;
错误即时标红(对照唯一解), 笔记模式, 同数高亮, 剩余计数, 计时最佳纪录.

键位 (键盘基础层, 无需 Fn):
  1-9    填数字(笔记模式下写候选)   0/Backspace  擦除
  h j k l / 方向键  移动光标          n    笔记模式
  r      重开一局(有进度时确认)      d/Tab 切换难度
  Enter  对话框确认                  Esc  退出/关闭对话框
"""

import array
import glob
import re
import subprocess
import json
import mmap
import math
import os
import random
import select
import struct
import sys
import time

import pygame

try:
    VOL_EVT = pygame.event.custom_type()
except Exception:
    VOL_EVT = pygame.USEREVENT + 1

# ── 常量 ────────────────────────────────────────────────────────────────────
W, H = 320, 170

BG        = (14, 14, 19)
PANEL     = (28, 28, 38)
GRID      = (58, 58, 72)
GRID3     = (140, 140, 158)
GIVEN_C   = (235, 235, 242)   # 题目给定数字
USER_C    = (255, 176, 32)    # 玩家填入(琥珀)
BAD_C     = (255, 82, 82)     # 错误
HL_C      = (40, 52, 80)      # 同行/列/宫 淡高亮
SEL_C     = (255, 176, 32)
SAME_C    = (120, 200, 255)   # 同数高亮
TEXT_C    = (185, 185, 198)
DIM_C     = (108, 108, 124)
NOTE_C    = (150, 170, 200)
GREEN_C   = (90, 220, 130)

# 板面几何: 9 格 × 18px, 纵向占满 (上下/左侧各留边距)
BX, BY, CELL = 4, 4, 18
BOARD = CELL * 9

# 右侧状态面板 (时间/难度/操作/余数全在这, 棋盘上下不再有文字行)
PANEL_X, PANEL_W = 168, 150
BTN_H = 20
BTN_GAP = 3

LEVELS = [
    {"key": "easy", "nm": "轻松", "givens": 40},
    {"key": "mid",  "nm": "标准", "givens": 32},
    {"key": "hard", "nm": "挑战", "givens": 26},
]
STATE_DIR = os.path.expanduser("~/.local/share/sudokuzero")
BEST_FILE = os.path.join(STATE_DIR, "best.json")

FONT_CANDIDATES = [
    "/usr/share/APPLaunch/share/font/AlibabaPuHuiTi-3-55-Regular.ttf",  # 设备
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "font.ttf"),
]


def fmt(sec):
    return "%d:%02d" % (sec // 60, sec % 60)


# ── 字体 ────────────────────────────────────────────────────────────────────
_ft = None
def load_font():
    global _ft
    if _ft is not None:
        return _ft
    try:
        from pygame import freetype as ft          # 常规路径
    except Exception:
        from pygame import _freetype as ft         # py3.14 循环导入绕行
    ft.init()
    for p in FONT_CANDIDATES:
        try:
            _ft = ft.Font(p)
            _ft.origin = False
            return _ft
        except Exception:
            continue
    raise RuntimeError("no CJK font found: %s" % FONT_CANDIDATES)

_cache = {}
def textw(s, size):
    """测量文本渲染宽度."""
    key = (s, size, (255, 255, 255))
    if key not in _cache:
        f = load_font()
        f.size = size
        _cache[key] = f.render(s, fgcolor=(255, 255, 255))
    return _cache[key][0].get_width()


def text(surf, s, size, color, xy, center=False):
    """渲染文本(带缓存). center=True 时 xy 为中心点."""
    key = (s, size, color)
    if key not in _cache:
        f = load_font()
        f.size = size
        _cache[key] = f.render(s, fgcolor=color)
    r = _cache[key][0]
    if center:
        surf.blit(r, (xy[0] - r.get_width() // 2, xy[1] - r.get_height() // 2))
    else:
        surf.blit(r, xy)


# ── 音效: 合成短音, 不依赖素材 ───────────────────────────────────────────────
class Snd:
    ok = False

    @classmethod
    def init(cls):
        if cls.ok is not None and cls.ok is False and getattr(cls, "tried", False):
            return
        cls.tried = True
        try:
            pygame.mixer.init(22050, -16, 1, 256)
            cls.tap = cls._tone(620, 680, .04, .22)
            cls.put = cls._tone(520, 640, .07, .28, tri=True)
            cls.bad = cls._tone(260, 205, .14, .28)
            cls.win = cls._arp([523, 659, 784, 1047], .16, .28)
            cls.ok = True
        except Exception:
            cls.ok = False

    @staticmethod
    def _tone(f0, f1, dur, vol=.5, tri=False):
        rate = 22050
        n = int(rate * dur)
        buf = array.array("h")
        ph = 0.0
        for i in range(n):
            t = i / n
            f = f0 + (f1 - f0) * t
            ph += 2 * math.pi * f / rate
            v = math.sin(ph)
            if tri:
                v = 2 / math.pi * math.asin(v)
            buf.append(max(-32767, min(32767, int(v * vol * 32767))))
        return pygame.mixer.Sound(buffer=buf.tobytes())

    @staticmethod
    def _arp(freqs, note, vol):
        rate = 22050
        gap = int(rate * 0.11)
        total = array.array("h", bytes(0))
        for k, f0 in enumerate(freqs):
            n = int(rate * note)
            seg = array.array("h")
            for i in range(n):
                v = math.sin(2 * math.pi * f0 * i / rate)
                env = min(1.0, (n - i) / (n * .6))
                seg.append(int(v * vol * env * 32767))
            total.extend(seg)
            total.extend(array.array("h", bytes(2 * gap)))
        return pygame.mixer.Sound(buffer=total.tobytes())

    @classmethod
    def play(cls, name):
        if cls.ok:
            try:
                getattr(cls, name).play()
            except Exception:
                pass


# ── 数独核心 (移植 game.js, 位掩码回溯) ─────────────────────────────────────
def _rcb(i):
    r, c = divmod(i, 9)
    return r, c, (r // 3) * 3 + c // 3


def count_solutions(a, limit=2):
    rows = [0] * 9; cols = [0] * 9; boxes = [0] * 9
    for i in range(81):
        v = a[i]
        if not v:
            continue
        bit = 1 << (v - 1)
        r, c, b = _rcb(i)
        if (rows[r] | cols[c] | boxes[b]) & bit:
            return 0
        rows[r] |= bit; cols[c] |= bit; boxes[b] |= bit
    count = 0

    def dfs(i):
        nonlocal count
        if count >= limit:
            return
        while i < 81 and a[i]:
            i += 1
        if i == 81:
            count += 1
            return
        r, c, b = _rcb(i)
        for d in range(1, 10):
            bit = 1 << (d - 1)
            if (rows[r] | cols[c] | boxes[b]) & bit:
                continue
            a[i] = d; rows[r] |= bit; cols[c] |= bit; boxes[b] |= bit
            dfs(i + 1)
            a[i] = 0; rows[r] &= ~bit; cols[c] &= ~bit; boxes[b] &= ~bit
            if count >= limit:
                return

    dfs(0)
    return count


def generate_full():
    a = [0] * 81
    rows = [0] * 9; cols = [0] * 9; boxes = [0] * 9

    def dfs(i):
        if i == 81:
            return True
        r, c, b = _rcb(i)
        ds = list(range(1, 10))
        random.shuffle(ds)
        for d in ds:
            bit = 1 << (d - 1)
            if (rows[r] | cols[c] | boxes[b]) & bit:
                continue
            a[i] = d; rows[r] |= bit; cols[c] |= bit; boxes[b] |= bit
            if dfs(i + 1):
                return True
            a[i] = 0; rows[r] &= ~bit; cols[c] &= ~bit; boxes[b] &= ~bit
        return False

    dfs(0)
    return a


def make_puzzle(givens):
    full = generate_full()
    puz = full[:]
    order = list(range(81))
    random.shuffle(order)
    left = 81
    for i in order:
        if left <= givens:
            break
        v = puz[i]
        puz[i] = 0
        if count_solutions(puz[:], 2) != 1:
            puz[i] = v
        else:
            left -= 1
    return puz, full


def load_best():
    try:
        with open(BEST_FILE) as f:
            return {k: int(v) for k, v in json.load(f).items()}
    except Exception:
        return {}


def save_best(best):
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(BEST_FILE, "w") as f:
            json.dump(best, f)
    except Exception:
        pass


# ── 游戏 ────────────────────────────────────────────────────────────────────
class Game:
    def __init__(self):
        self.lvl_idx = 1
        self.best = load_best()
        self.reset(LEVELS[self.lvl_idx])

    def reset(self, lvl):
        self.lvl = lvl
        self.puz, self.sol = make_puzzle(lvl["givens"])
        self.cur = self.puz[:]
        self.given = [v > 0 for v in self.puz]
        self.notes = [set() for _ in range(81)]
        self.sel = 40
        self.note_mode = False
        self.started = False
        self.won = False
        self.start_t = None
        self.sec = 0
        self.win_best = False
        self.dialog = None      # None | ("new",) | ("diff",) | ("win",)
        self.osd = None         # (文本, 到期时间) 音量提示

    # ── 交互 ──
    def started_or_progress(self):
        return self.started or any(v and not g for v, g in zip(self.cur, self.given))

    def move(self, dx, dy):
        r, c = divmod(self.sel, 9)
        c = max(0, min(8, c + dx))
        r = max(0, min(8, r + dy))
        self.sel = r * 9 + c
        Snd.play("tap")

    def place(self, d):
        if self.won or self.given[self.sel]:
            Snd.play("bad")
            return
        if self.note_mode:
            if self.cur[self.sel]:
                return
            if d in self.notes[self.sel]:
                self.notes[self.sel].discard(d)
            else:
                self.notes[self.sel].add(d)
            Snd.play("tap")
            return
        if self.cur[self.sel] == d:      # 再按同数字 = 擦除
            self.cur[self.sel] = 0
        else:
            self.cur[self.sel] = d
            self.notes[self.sel].clear()
            self.start_t = self.start_t or time.monotonic()
            self.started = True
            Snd.play("put" if self.cur[self.sel] == self.sol[self.sel] else "bad")
            if self.cur == self.sol:
                self.win()

    def erase(self):
        if self.won or self.given[self.sel] or not (self.cur[self.sel] or self.notes[self.sel]):
            return
        self.cur[self.sel] = 0
        self.notes[self.sel].clear()
        Snd.play("tap")

    def win(self):
        self.won = True
        self.sec = int(time.monotonic() - self.start_t)
        b = self.best.get(self.lvl["key"])
        self.win_best = b is None or self.sec < b
        if self.win_best:
            self.best[self.lvl["key"]] = self.sec
            save_best(self.best)
        Snd.play("win")
        self.dialog = ("win",)

    def restart(self):
        self.reset(LEVELS[self.lvl_idx])

    def cycle_diff(self):
        self.lvl_idx = (self.lvl_idx + 1) % len(LEVELS)
        self.restart()

    def adjust_volume(self, code):
        """Fn+A 静音 / Fn+S 音量+ / Fn+D 音量- (系统级, pactl/PipeWire)."""
        try:
            if code == 113:
                subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"],
                               timeout=2, check=False)
            elif code == 114:                    # Fn+D 音量-
                subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "-5%"],
                               timeout=2, check=False)
            else:                                  # Fn+S 音量+
                subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "+5%"],
                               timeout=2, check=False)
            vol = subprocess.run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"],
                                 capture_output=True, text=True, timeout=2).stdout
            mute = subprocess.run(["pactl", "get-sink-mute", "@DEFAULT_SINK@"],
                                  capture_output=True, text=True, timeout=2).stdout
            m = re.search(r"(\d+)%", vol)
            label = "音量 " + m.group(1) + "%" if m else "音量?"
            if "yes" in mute:
                label = "静音 " + label
            self.osd = (label, time.monotonic() + 1.2)
        except Exception:
            self.osd = ("音量调节不可用", time.monotonic() + 1.0)

    # ── 事件 ──
    def key(self, ev):
        k = ev.key
        if self.dialog:
            kind = self.dialog[0]
            if kind == "win":
                if k in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    self.restart()
                elif k == pygame.K_ESCAPE:
                    pygame.event.post(pygame.event.Event(pygame.QUIT))
            else:   # new / diff 确认框
                if k in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_y):
                    self.dialog = None
                    if kind == "new":
                        self.restart()
                    else:
                        self.cycle_diff()
                elif k in (pygame.K_ESCAPE, pygame.K_n):
                    self.dialog = None
            return

        if k in (pygame.K_h, pygame.K_z, pygame.K_LEFT):
            self.move(-1, 0)
        elif k in (pygame.K_l, pygame.K_c, pygame.K_RIGHT):
            self.move(1, 0)
        elif k in (pygame.K_k, pygame.K_f, pygame.K_UP):
            self.move(0, -1)
        elif k in (pygame.K_j, pygame.K_x, pygame.K_DOWN):
            self.move(0, 1)
        elif pygame.K_1 <= k <= pygame.K_9:
            self.place(k - pygame.K_1 + 1)
        elif k in (pygame.K_0, pygame.K_BACKSPACE, pygame.K_DELETE):
            self.erase()
        elif k == pygame.K_n:
            self.note_mode = not self.note_mode
            Snd.play("tap")
        elif k == pygame.K_r:
            if self.started_or_progress():
                self.dialog = ("new",)
            else:
                self.restart()
        elif k in (pygame.K_d, pygame.K_TAB):
            if self.started_or_progress():
                self.dialog = ("diff",)
            else:
                self.cycle_diff()
        elif k == pygame.K_ESCAPE:
            pygame.event.post(pygame.event.Event(pygame.QUIT))

    # ── 渲染 ──
    def tick_time(self):
        if self.start_t and not self.won:
            self.sec = int(time.monotonic() - self.start_t)
        return self.sec

    def draw(self, surf):
        surf.fill(BG)
        self.draw_board(surf)
        self.draw_panel(surf)
        if self.osd and time.monotonic() < self.osd[1]:
            t = self.osd[0]
            w = textw(t, 11)
            bx = W // 2
            pygame.draw.rect(surf, (10, 10, 14), (bx - w // 2 - 10, 58, w + 20, 20),
                             border_radius=5)
            pygame.draw.rect(surf, SEL_C, (bx - w // 2 - 10, 58, w + 20, 20), 1,
                             border_radius=5)
            text(surf, t, 11, (235, 235, 240), (bx, 68), center=True)
        if self.dialog:
            self.draw_dialog(surf)

    def draw_status(self, surf):
        b = self.best.get(self.lvl["key"])
        cx = PANEL_X + PANEL_W // 2
        t1 = "用时 " + fmt(self.tick_time())
        t2 = "最佳 " + (fmt(b) if b else "-")
        w1, w2 = textw(t1, 11), textw(t2, 11)
        x0 = cx - (w1 + 8 + w2) // 2
        text(surf, t1, 11, USER_C, (x0, 5))
        text(surf, t2, 11, TEXT_C, (x0 + w1 + 8, 5))
        text(surf, self.lvl["nm"], 11, (225, 225, 240), (cx, 26), center=True)

    def draw_board(self, surf):
        pygame.draw.rect(surf, (0, 0, 0), (BX - 1, BY - 1, BOARD + 2, BOARD + 2))
        sr, sc = divmod(self.sel, 9)
        sv = self.cur[self.sel] if self.sel >= 0 else 0
        for i in range(81):
            r, c = divmod(i, 9)
            x, y = BX + c * CELL, BY + r * CELL
            # 高亮: 所在行列宫
            if i != self.sel and (r == sr or c == sc or
                                  (r // 3 == sr // 3 and c // 3 == sc // 3)):
                surf.fill(HL_C, (x, y, CELL, CELL))
            # 同数外框
            if sv and self.cur[i] == sv and i != self.sel:
                pygame.draw.rect(surf, SAME_C, (x + 1, y + 1, CELL - 2, CELL - 2), 1)
            v = self.cur[i]
            bad = v and v != self.sol[i]
            if v:
                text(surf, str(v), 13,
                     BAD_C if bad else (GIVEN_C if self.given[i] else USER_C),
                     (x + CELL // 2, y + CELL // 2 + 1), center=True)
            elif self.notes[i]:
                for d in range(1, 10):
                    if d in self.notes[i]:
                        nr, nc = divmod(d - 1, 3)
                        text(surf, str(d), 7, NOTE_C,
                             (x + nc * 6 + 2, y + nr * 6 + 1))
        # 网格线
        for g in range(10):
            thick = g % 3 == 0
            color = GRID3 if thick else GRID
            x = BX + g * CELL
            pygame.draw.line(surf, color, (x, BY), (x, BY + BOARD), 1 if thick else 1)
            y = BY + g * CELL
            pygame.draw.line(surf, color, (BX, y), (BX + BOARD, y), 1)
        # 外框加粗
        pygame.draw.rect(surf, GRID3, (BX, BY, BOARD, BOARD), 1)
        # 选中格
        cx, cy = BX + sc * CELL, BY + sr * CELL
        pygame.draw.rect(surf, SEL_C, (cx, cy, CELL, CELL), 2)

    def draw_panel(self, surf):
        self.draw_status(surf)
        # 操作按钮列: 笔记 / 擦除 / 新局 / 难度
        btns = [
            ("● 笔记中 [n]" if self.note_mode else "笔记 [n]", self.note_mode),
            ("擦除 [0]", False),
            ("新局 [r]", False),
            ("难度 → %s [d]" % LEVELS[(self.lvl_idx + 1) % 3]["nm"], False),
        ]
        y = 34
        for label, on in btns:
            pygame.draw.rect(surf, SEL_C if on else PANEL,
                             (PANEL_X, y, PANEL_W, BTN_H), border_radius=4)
            text(surf, label, 11, BG if on else TEXT_C,
                 (PANEL_X + PANEL_W // 2, y + BTN_H // 2 + 1), center=True)
            y += BTN_H + BTN_GAP
        # 余数统计 3×3 (信息展示, 非输入)
        used = [0] * 10
        for v in self.cur:
            if v:
                used[v] += 1
        gy = y + 3
        cw = PANEL_W // 3
        for d in range(1, 10):
            col, row = (d - 1) % 3, (d - 1) // 3
            x = PANEL_X + col * cw
            left = 9 - used[d]
            if left == 0:
                pygame.draw.rect(surf, (24, 40, 30), (x + 2, gy + row * 13, cw - 4, 12),
                                 border_radius=2)
            text(surf, "%d·%d" % (d, left), 9,
                 GREEN_C if left == 0 else NOTE_C,
                 (x + cw // 2, gy + row * 13 + 6), center=True)

    def draw_dialog(self, surf):
        kind = self.dialog[0]
        ov = pygame.Surface((W, H), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 170))
        surf.blit(ov, (0, 0))
        bx, bw, bh = 70, 180, 62
        by = (H - bh) // 2
        pygame.draw.rect(surf, PANEL, (bx, by, bw, bh), border_radius=6)
        pygame.draw.rect(surf, SEL_C, (bx, by, bw, bh), 1, border_radius=6)
        if kind == "win":
            text(surf, "★ 通关 ★", 13, GREEN_C, (W // 2, by + 12), center=True)
            text(surf, fmt(self.sec), 17, USER_C, (W // 2, by + 28), center=True)
            sub = ("新纪录! " if self.win_best else "最佳 " + fmt(self.best[self.lvl["key"]]) + " · ") + self.lvl["nm"]
            text(surf, sub, 8, TEXT_C, (W // 2, by + 42), center=True)
            text(surf, "Enter 再来一局 · Esc 退出", 8, DIM_C, (W // 2, by + 53), center=True)
        else:
            title = "重开一局?" if kind == "new" else "换难度为 " + LEVELS[(self.lvl_idx + 1) % 3]["nm"] + "?"
            text(surf, title, 11, USER_C, (W // 2, by + 12), center=True)
            text(surf, "当前进度将丢弃", 8, DIM_C, (W // 2, by + 27), center=True)
            text(surf, "Enter 确认 · Esc 取消", 8, TEXT_C, (W // 2, by + 45), center=True)


# ── 设备帧缓冲输出: 与内置 APP 同路径 (/dev/fb_lcd 直写) ──────────────────────
class Framebuffer:
    """渲染到内存 surface, 转设备色彩格式后 mmap 直写 /dev/fb_lcd."""

    def __init__(self):
        self.dev = open("/dev/fb_lcd", "r+b", buffering=0)
        bpp = 16
        try:
            bpp = int(open("/sys/class/graphics/fb_lcd/bits_per_pixel").read().strip())
        except Exception:
            pass
        if bpp == 32:
            self.conv = pygame.Surface((W, H), depth=32,
                                       masks=(0xFF0000, 0xFF00, 0xFF, 0xFF000000))
        else:                                   # RGB565 (little-endian)
            self.conv = pygame.Surface((W, H), depth=16,
                                       masks=(0xF800, 0x07E0, 0x001F, 0))
        self.mm = mmap.mmap(self.dev.fileno(), W * H * bpp // 8)

    def blit(self, canvas):
        self.conv.blit(canvas, (0, 0))
        self.mm.seek(0)
        self.mm.write(self.conv.get_buffer().raw)

    def close(self):
        try:
            self.mm.close()
        finally:
            self.dev.close()


# ── 设备键盘: 裸 evdev (TCA8418) → pygame 事件 ──────────────────────────────
EV_KEY = 0x01

def find_keyboard():
    """返回 tca8418 键盘的 /dev/input/eventX 路径."""
    for name_f in glob.glob("/sys/class/input/input*/name"):
        try:
            if open(name_f).read().strip() != "tca8418c":
                continue
            base = os.path.dirname(name_f)
            for dev_dir in glob.glob(base + "/event*"):
                n = os.path.basename(dev_dir)
                if os.path.exists("/dev/input/" + n):
                    return "/dev/input/" + n
        except Exception:
            continue
    return None


# evdev keycode → pygame key (仅游戏所需键集)
# 本机键盘丝印方向键: F=↑ X=↓ Z=← C=→ (直接映射, 无需 Fn)
EVDEV_MAP = {
    1: pygame.K_ESCAPE, 2: pygame.K_1, 3: pygame.K_2, 4: pygame.K_3, 5: pygame.K_4,
    6: pygame.K_5, 7: pygame.K_6, 8: pygame.K_7, 9: pygame.K_8, 10: pygame.K_9,
    11: pygame.K_0, 14: pygame.K_BACKSPACE, 15: pygame.K_TAB, 28: pygame.K_RETURN,
    96: pygame.K_KP_ENTER, 111: pygame.K_DELETE,
    19: pygame.K_r, 32: pygame.K_d, 35: pygame.K_h, 37: pygame.K_k, 38: pygame.K_j,
    40: pygame.K_l, 49: pygame.K_n, 21: pygame.K_y, 22: pygame.K_u, 57: pygame.K_SPACE,
    33: pygame.K_UP, 44: pygame.K_LEFT, 45: pygame.K_DOWN, 46: pygame.K_RIGHT,
    103: pygame.K_UP, 108: pygame.K_DOWN, 105: pygame.K_LEFT, 106: pygame.K_RIGHT,
}


class EvKeyboard:
    def __init__(self):
        self.path = find_keyboard()
        self.fd = os.open(self.path, os.O_RDONLY | os.O_NONBLOCK) if self.path else None

    def poll(self):
        """读出所有按下事件, 生成 pygame KEYDOWN; 未知键码记日志便于排查."""
        if self.fd is None:
            return
        while True:
            r, _, _ = select.select([self.fd], [], [], 0)
            if not r:
                return
            try:
                buf = os.read(self.fd, 24 * 16)
            except BlockingIOError:
                return
            for off in range(0, len(buf) - 23, 24):
                _, _, typ, code, val = struct.unpack_from("qqHHi", buf, off)
                if typ != EV_KEY or val != 1:
                    continue
                if code in (113, 114, 115):          # Fn+A 静音 / Fn+S+ / Fn+D-
                    pygame.event.post(pygame.event.Event(VOL_EVT, code=code))
                elif code in EVDEV_MAP:
                    k = EVDEV_MAP[code]
                    pygame.event.post(pygame.event.Event(
                        pygame.KEYDOWN, key=k, mod=0,
                        unicode=chr(k) if 32 <= k < 127 else ""))
                else:
                    try:
                        with open("/tmp/sudoku_unmapped_keys.log", "a") as f:
                            f.write("code=%d\n" % code)
                    except Exception:
                        pass

    def close(self):
        if self.fd is not None:
            os.close(self.fd)


# ── 演示模式 (商店截图用): CPZ_DEMO=mid|win ─────────────────────────────────
def _apply_demo(game, mode):
    if not mode:
        return
    if mode == "mid":
        # 中盘: 已填若干正确 + 1 个错误 + 笔记 + 计时中
        game.start_t = time.monotonic() - 754
        game.started = True
        empty = [i for i in range(81) if not game.given[i]]
        for k, i in enumerate(empty[:9]):
            game.cur[i] = game.sol[i]
        if empty[9]:
            game.sel = empty[9]
            game.cur[empty[9]] = 1 + (game.sol[empty[9]] % 9)
            if game.cur[empty[9]] == game.sol[empty[9]]:
                game.cur[empty[9]] = 1 + (game.sol[empty[9]] + 3) % 9
        for d in (2, 5, 8):
            if empty[11] and d != game.sol[empty[11]]:
                game.notes[empty[11]].add(d)
    elif mode == "win":
        for i in range(81):
            game.cur[i] = game.sol[i]
        game.start_t = time.monotonic() - 321
        game.started = True
        game.win()


# ── 主循环 ──────────────────────────────────────────────────────────────────
def main():
    windowed = "--window" in sys.argv
    on_device = not windowed and os.path.exists("/dev/fb_lcd")
    if on_device:
        # 必须在 pygame.init() 之前设置: 否则 SDL 自动探测会抢面板 DRM master,
        # 旁路 fbdev 通路, 导致 /dev/fb_lcd 写入被丢弃
        os.environ["SDL_VIDEODRIVER"] = "dummy"
    pygame.init()
    Snd.init()

    fb = None
    kbd = None
    if on_device:
        pygame.display.set_mode((1, 1))              # pygame 仅做离屏渲染
        fb = Framebuffer()
        kbd = EvKeyboard()
        canvas = pygame.Surface((W, H))
    elif windowed:
        surf = pygame.display.set_mode((W * 2, H * 2))
        pygame.display.set_caption("数独 · CardputerZero")
        canvas = pygame.Surface((W, H))
    else:                                           # 无 fb 的无头环境 (CI/测试)
        os.environ["SDL_VIDEODRIVER"] = "dummy"
        pygame.display.set_mode((W, H))
        canvas = pygame.Surface((W, H))

    game = Game()
    _apply_demo(game, os.environ.get("CPZ_DEMO", ""))
    clock = pygame.time.Clock()
    running = True
    while running:
        if kbd:
            kbd.poll()
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False
            elif ev.type == pygame.KEYDOWN:
                game.key(ev)
            elif ev.type == VOL_EVT:
                game.adjust_volume(getattr(ev, "code", 115))
        game.draw(canvas)
        if fb:
            fb.blit(canvas)
        elif windowed:
            pygame.transform.scale(canvas, (W * 2, H * 2), surf)
            pygame.display.flip()
        # 静止时降到 ~5fps 省电; 计时中 30fps
        active = game.start_t and not game.won
        clock.tick(30 if active else 5)

    if fb:
        fb.close()
    if kbd:
        kbd.close()
    pygame.quit()


if __name__ == "__main__":
    main()
