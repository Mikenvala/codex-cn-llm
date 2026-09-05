#!/usr/bin/python3
# 生成 Codex 助手 logo：App 图标 (.icns) + 状态栏 template 图标
from PIL import Image, ImageDraw, ImageFilter
import os, math

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
os.makedirs(OUT, exist_ok=True)

# 闪电多边形（归一化 0..1 坐标）
LIGHTNING = [
    (0.585, 0.075),
    (0.255, 0.560),
    (0.455, 0.560),
    (0.335, 0.925),
    (0.715, 0.420),
    (0.510, 0.420),
    (0.655, 0.075),
]

def lightning(draw, box, color, smooth=0):
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    pts = [(x0 + px * w, y0 + py * h) for (px, py) in LIGHTNING]
    if smooth:
        # 圆角：用粗线先画再叠加
        pass
    draw.polygon(pts, fill=color)

def round_rect_gradient(size, c1, c2, radius):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    # 渐变
    grad = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    for y in range(size):
        t = y / size
        r = int(c1[0] + (c2[0] - c1[0]) * t)
        g = int(c1[1] + (c2[1] - c1[1]) * t)
        b = int(c1[2] + (c2[2] - c1[2]) * t)
        gd.line([(0, y), (size, y)], fill=(r, g, b, 255))
    # 圆角蒙版
    mask = Image.new("L", (size, size), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    img.paste(grad, (0, 0), mask)
    return img

def make_master():
    S = 1024
    c1 = (22, 104, 220)   # #1668dc
    c2 = (106, 61, 232)   # #6a3de8
    img = round_rect_gradient(S, c1, c2, radius=int(S * 0.22))
    d = ImageDraw.Draw(img)
    # 白色闪电
    lightning(d, (0.28 * S, 0.16 * S, 0.72 * S, 0.84 * S), (255, 255, 255, 255))
    return img

def make_menu_icon():
    # 状态栏 template：黑色闪电 + 透明背景（NSImage template 自动反色）
    S = 64
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    lightning(d, (0.10 * S, 0.04 * S, 0.90 * S, 0.96 * S), (0, 0, 0, 255))
    return img

master = make_master()
master.save(os.path.join(OUT, "icon_1024.png"))

menu = make_menu_icon()
menu.save(os.path.join(OUT, "menu_icon.png"))
menu.save(os.path.join(OUT, "menu_icon@2x.png"))

# iconset 目录
iconset = os.path.join(OUT, "AppIcon.iconset")
os.makedirs(iconset, exist_ok=True)
sizes = {
    "icon_16x16.png": 16, "icon_16x16@2x.png": 32,
    "icon_32x32.png": 32, "icon_32x32@2x.png": 64,
    "icon_128x128.png": 128, "icon_128x128@2x.png": 256,
    "icon_256x256.png": 256, "icon_256x256@2x.png": 512,
    "icon_512x512.png": 512, "icon_512x512@2x.png": 1024,
}
for name, s in sizes.items():
    master.resize((s, s), Image.LANCZOS).save(os.path.join(iconset, name))

print("assets generated in", OUT)
