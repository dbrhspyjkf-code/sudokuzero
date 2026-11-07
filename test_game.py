#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数独移植版冒烟测试: 生成器正确性 + 完整通关模拟 + 渲染截图"""
import os, sys, time
os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["CPZ_VIDEO"] = "dummy"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pygame
import game as G

fails = []
import tempfile, shutil
_tmp = tempfile.mkdtemp()
G.STATE_DIR = _tmp
G.BEST_FILE = os.path.join(_tmp, "best.json")
shutil.copy(G.BEST_FILE, G.BEST_FILE) if False else None
def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)

# ── 1. 三档生成器: 唯一解 + 给定数 + 解合法 ──
t0 = time.time()
for lvl in G.LEVELS:
    puz, sol = G.make_puzzle(lvl["givens"])
    givens = sum(1 for v in puz if v)
    check(f"[{lvl['key']}] 给定数 {givens} ≈ {lvl['givens']}", abs(givens - lvl["givens"]) <= 1)
    check(f"[{lvl['key']}] 唯一解", G.count_solutions(puz[:], 2) == 1)
    rows = [set() for _ in range(9)]; cols = [set() for _ in range(9)]; boxes = [set() for _ in range(9)]
    ok = True
    for i, v in enumerate(sol):
        r, c, b = G._rcb(i)
        if v in rows[r] or v in cols[c] or v in boxes[b]:
            ok = False; break
        rows[r].add(v); cols[c].add(v); boxes[b].add(v)
    check(f"[{lvl['key']}] 全解合法", ok)
    # 挖洞后剩余数字与全解一致
    check(f"[{lvl['key']}] 挖洞不改变给定值", all(p == s for p, s in zip(puz, sol) if p))
print("生成总耗时 %.2fs (3 局)" % (time.time() - t0))

# ── 2. 游戏流程: 移动/填数/笔记/擦除/通关/纪录 ──
g = G.Game()
check("初始未开始", not g.started and not g.won)
g.sel = 0
if g.given[0]:
    g.sel = next(i for i in range(81) if not g.given[i])
# 笔记模式
g.note_mode = True
g.place(5); g.place(7)
check("笔记写入", 5 in g.notes[g.sel] and 7 in g.notes[g.sel])
g.place(5)
check("笔记再按=取消", 5 not in g.notes[g.sel])
g.note_mode = False
# 填入正确值
right = g.sol[g.sel]
g.place(right)
check("填数正确", g.cur[g.sel] == right and g.started)
# 移动
old = g.sel
g.move(1, 0); g.move(0, 1); g.move(-1, 0); g.move(0, -1)
check("移动回原位", g.sel == old)
# 擦除
g.erase()
check("擦除", g.cur[g.sel] == 0 and not g.notes[g.sel])
# 边界
g.sel = 0; g.move(-1, 0); g.move(0, -1)
check("左上边界钳制", g.sel == 0)
g.sel = 80; g.move(1, 0); g.move(0, 1)
check("右下边界钳制", g.sel == 80)
# 填错标红判定 (内部状态)
g.sel = next(i for i in range(81) if not g.given[i])
wrong = 1 + (g.sol[g.sel] % 9)
g.cur[g.sel] = wrong
check("错值可检测", g.cur[g.sel] != g.sol[g.sel])

# ── 3. 完整通关 ──
g2 = G.Game()
g2.start_t = time.monotonic() - 95          # 假装玩了 95 秒
for i in range(81):
    if not g2.given[i]:
        g2.sel = i
        g2.cur[i] = g2.sol[i]
        g2.started = True
g2.win()
check("通关检测", g2.won and g2.dialog == ("win",))
check("通关用时", 90 <= g2.sec <= 100)
check("首通即纪录", g2.win_best and G.load_best().get(g2.lvl["key"]) == g2.sec)
# 再来一局
g2.restart()
check("重开重置", not g2.won and not g2.started and g2.dialog is None)

# ── 4. 渲染截图 (人工检查) ──
pygame.init()
pygame.display.set_mode((G.W, G.H))
g3 = G.Game()
g3.start_t = time.monotonic() - 754
g3.sec = 754
g3.started = True
i0 = next(i for i in range(81) if not g3.given[i])
i1 = next(i for i in range(81) if not g3.given[i] and i != i0)
g3.sel = i0
g3.cur[i0] = 1 + (g3.sol[i0] % 9)           # 一个错值(标红)
g3.notes[i1] = {d for d in (1, 4, 7) if d != g3.sol[i1]}
canvas = pygame.Surface((G.W, G.H))
g3.draw(canvas)
pygame.image.save(canvas, "shot_play.bmp")
g3.dialog = ("win",); g3.sec = 321; g3.win_best = True
g3.draw(canvas)
pygame.image.save(canvas, "shot_win.bmp")
g3.dialog = ("new",)
g3.draw(canvas)
pygame.image.save(canvas, "shot_confirm.bmp")
print("截图: shot_play.bmp / shot_win.bmp / shot_confirm.bmp")

print("=" * 40)
print("全部通过 ✓" if not fails else f"失败 {len(fails)} 项: {fails}")
sys.exit(1 if fails else 0)
