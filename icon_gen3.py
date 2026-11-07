#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数独图标 v2 — 复刻用户设计: 软糖饼干风 S-U-数 / D-★-O / K-U-独
橄榄绿底 + 米白圆角厚底方块 + 橙色高亮块 + 中央星星"""
import math
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from savepng import save_png
os.environ["SDL_VIDEODRIVER"] = "dummy"
import pygame

pygame.init()
try:
    from pygame import freetype as ft
except Exception:
    from pygame import _freetype as ft
ft.init()

BASE = os.path.dirname(os.path.abspath(__file__))
F_LATIN = ft.Font(os.path.join(BASE, "assets", "montserrat-bold.ttf"))
F_CJK = ft.Font(os.path.join(BASE, "assets", "notocjk.ttc"))
for f in (F_LATIN, F_CJK):
    f.origin = False

BG      = (94, 125, 80)     # 橄榄绿 #5E7D50
CREAM   = (242, 239, 230)   # 米白 #F2EFE6
CREAM_D = (219, 214, 198)   # 米白厚底 #DBD6C6
ORANGE  = (232, 162, 92)    # 橙 #E8A25C
ORANGE_D= (206, 136, 67)    # 橙厚底 #CE8843
BROWN   = (83, 57, 31)      # 深棕 #53391F
YELLOW  = (245, 212, 94)    # 汉字黄 #F5D45E
STAR_Y  = (247, 224, 110)   # 星星黄 #F7E06E

S = 512
TILE, GAP, MARGIN = 124, 26, 44
THICK = 12       # 厚底偏移
RAD = 26         # 圆角半径


def rounded_tile(img, x, y, tile, main, dark):
    rad = tile * 20 // 100
    pygame.draw.rect(img, dark, (x, y + THICK, tile, tile), border_radius=rad)
    pygame.draw.rect(img, main, (x, y, tile, tile), border_radius=rad)


def blit_center(img, surf, cx, cy):
    img.blit(surf, (round(cx - surf.get_width() / 2), round(cy - surf.get_height() / 2)))


def render(f, ch, size, color):
    f.size = size
    return f.render(ch, fgcolor=color)[0]


def render_stroked(f, ch, size, fill, stroke, radius):
    """描边文字: 沿圆环偏移渲染 stroke 色, 中心渲染 fill 色."""
    f.size = size
    base = f.render(ch, fgcolor=fill)[0]
    ring = f.render(ch, fgcolor=stroke)[0]
    pad = radius + 2
    out = pygame.Surface((ring.get_width() + pad * 2, ring.get_height() + pad * 2), pygame.SRCALPHA)
    steps = 24
    for i in range(steps):
        a = 2 * math.pi * i / steps
        out.blit(ring, (pad + round(math.cos(a) * radius), pad + round(math.sin(a) * radius)))
    out.blit(base, (pad, pad))
    return out


def star_points(cx, cy, r_out, r_in):
    pts = []
    for i in range(10):
        r = r_out if i % 2 == 0 else r_in
        a = -math.pi / 2 + i * math.pi / 5
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def make(mode="badge"):
    img = pygame.Surface((S, S), pygame.SRCALPHA)
    tile, gap = 124, 26
    x0 = (S - (3 * tile + 2 * gap)) // 2
    y0 = 40
    if mode == "badge":
        pygame.draw.rect(img, BG, (10, 10, S-20, S-20), border_radius=92)
    cells = {
        (0, 0): ("S", False), (0, 1): ("U", False), (0, 2): ("数", True),
        (1, 0): ("D", False), (1, 2): ("O", False),
        (2, 0): ("K", False), (2, 1): ("U", False), (2, 2): ("独", True),
    }
    for (row, col), (ch, orange) in cells.items():
        x = x0 + col * (tile + gap)
        y = y0 + row * (tile + gap)
        rounded_tile(img, x, y, tile, ORANGE if orange else CREAM, ORANGE_D if orange else CREAM_D)
        cx, cy = x + tile / 2, y + tile / 2 - THICK / 2
        if orange:
            surf = render_stroked(F_CJK, ch, 70, YELLOW, BROWN, 8)
        else:
            surf = render(F_LATIN, ch, 76, BROWN)
        blit_center(img, surf, cx, cy)
    # 中央星星
    cx = x0 + tile + gap + tile / 2
    cy = y0 + tile + gap + tile / 2
    pygame.draw.polygon(img, BROWN, star_points(cx, cy + 4, 50, 21))
    pygame.draw.polygon(img, STAR_Y, star_points(cx, cy, 46, 19))
    pygame.draw.circle(img, STAR_Y, (cx, cy - 10), 4)
    out = pygame.transform.smoothscale(img, (256, 256))
    save_png(out, f"icon-{mode}.png")
    print("saved icon-" + mode)


make("badge")   # 圆角绿徽章
make("glyph")   # 纯透明底
