#!/usr/bin/env python3
# 封面 900x383 PIL 渲染 — bakcheck 备份哨兵（自研工具：对话钩子形态，不晒星数，晒硬指标）
# 用 /usr/bin/python3 跑（homebrew 无 PIL）。出图后必须 vision_analyze 验字。
import os
from PIL import Image, ImageDraw, ImageFont

W, H = 900, 383
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "cover-900x383.png")
DESK = os.path.expanduser("~/Desktop/bakcheck-cover.png")
FONT = "/System/Library/Fonts/STHeiti Medium.ttc"


def F(sz):
    return ImageFont.truetype(FONT, sz)


# 对角渐变 #0b0e1a → #1a0f2e (135deg)
c0, c1 = (11, 14, 26), (26, 15, 46)
img = Image.new("RGB", (W, H))
px = img.load()
for y in range(H):
    for x in range(W):
        t = (x / W + y / H) / 2
        px[x, y] = (
            int(c0[0] + (c1[0] - c0[0]) * t),
            int(c0[1] + (c1[1] - c0[1]) * t),
            int(c0[2] + (c1[2] - c0[2]) * t),
        )
d = ImageDraw.Draw(img)
GOLD = (240, 180, 41)
WHITE = (255, 255, 255)
GRAY = (139, 148, 158)
GREEN = (63, 185, 80)
RED = (248, 81, 73)

# 左金竖条(锚住主标题)
d.rectangle([34, 90, 40, 224], fill=GOLD)

# 红行黑衬底(先画底)
t_red = "备份任务显示「成功」，恢复时才是半截"
f_red = F(25)
bb = d.textbbox((48, 262), t_red, font=f_red)
d.rectangle([bb[0] - 12, bb[1] - 8, bb[2] + 12, bb[3] + 8], fill=(8, 9, 15))

items = [
    ("我是小薅薅 · 运维工具箱 ⑦", (48, 34), 24, GOLD),
    ("备份哨兵:", (48, 86), 58, WHITE),
    ("只认产物不认报告", (48, 162), 58, WHITE),
    ("自测 26/26", (596, 96), 46, GREEN),
    ("零依赖单文件 · MIT", (626, 162), 22, GRAY),
    (t_red, (48, 262), 25, RED),
    ("bakcheck：新鲜度+完整性探针+大小带 · 演练凭证 · git clone 即用", (48, 322), 19, GRAY),
]
# 出图前 bounds 自检（防超边）
for text, (x, y), sz, color in items:
    f = F(sz)
    b = d.textbbox((x, y), text, font=f)
    if b[2] > W - 10 or b[3] > H - 6 or b[0] < 10:
        raise SystemExit("TEXT OUT OF BOUNDS: %r bbox=%s" % (text, b))
for text, (x, y), sz, color in items:
    d.text((x, y), text, font=F(sz), fill=color)

img.save(OUT)
img.save(DESK)
print("saved:", OUT)
print("saved:", DESK)
