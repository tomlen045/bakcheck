#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bakcheck 文章证据图 x6 (1200x675) — 内容 100% 取自 demo-run/ 真实输出，路径已脱敏。"""
from PIL import Image, ImageDraw, ImageFont
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "screenshots")
os.makedirs(OUT, exist_ok=True)
FONT_CJK = "/System/Library/Fonts/STHeiti Medium.ttc"
FONT_MONO = "/System/Library/Fonts/Menlo.ttc"
W, H = 1200, 675
BG, BAR, LINE = "#1b1d23", "#2a2d35", "#0d1117"
GREEN, WHITE, GREY, RED, GOLD, BLUE = "#98c379", "#e6edf3", "#7f8794", "#e06c75", "#e5c07b", "#61afef"

_fc = {}


def F(size, mono):
    key = (size, mono)
    if key not in _fc:
        _fc[key] = ImageFont.truetype(FONT_MONO if mono else FONT_CJK, size)
    return _fc[key]


def has_cjk(t):
    return any('\u2e80' <= ch <= '\u9fff' for ch in t)


def shot(name, lines, title="bakcheck — zsh"):
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 44], fill=BAR)
    d.ellipse([24, 15, 36, 27], fill="#ff5f57")
    d.ellipse([44, 15, 56, 27], fill="#febc2e")
    d.ellipse([64, 15, 76, 27], fill="#28c840")
    tw = d.textlength(title, font=F(16, False))
    d.text(((W - tw) / 2, 13), title, font=F(16, False), fill="#8b90a0")
    d.rectangle([0, 44, W, 46], fill=LINE)
    y = 70
    for text, color, size, mono in lines:
        if text:
            font = F(size, mono and not has_cjk(text))
            d.text((56, y), text, font=font, fill=color)
        y += int(size * 1.62)
    img.save(os.path.join(OUT, name + ".png"))
    print(name, "OK")


# ---- 1. 四族四种死法（demo-run/01-scan.txt 真实输出，路径脱敏）
shot("bk-shot-1-scan", [
    ("$ python3 bakcheck.py scan ~/backups", WHITE, 24, True),
    ("bakcheck v1.0.0 -- 备份哨兵", GREY, 22, False),
    ("X [RED] configdb-{date}.sql · 1份 · 最新 0B", RED, 22, True),
    ("     · 零字节备份（任务「成功」产物为空）", WHITE, 22, False),
    ("X [RED] filesrv-{date}.zip · 最新 4.1KB · 距今8.0天", RED, 22, True),
    ("     · 最新备份已 8.0天 未更新（SLA 26小时）", WHITE, 22, False),
    ("X [RED] oradb-full-{date}.tar.gz · 5份", RED, 22, True),
    ("     · 完整性探针失败: 流解压失败(截断/损坏)", WHITE, 22, False),
    ("V [GREEN] webapp-{date}.tar.gz · 7份 · 完整", GREEN, 22, True),
    ("# 任务全部显示「成功」，产物三种死法", GREY, 22, False),
])

# ---- 2. 截断 tar.gz 当场现形（demo-run/03-verdict-trunc 摘录）
shot("bk-shot-2-trunc", [
    ("$ bakcheck.py verdict ~/backups/oradb/oradb-full-20260929.tar.gz", WHITE, 21, True),
    ("X [RED] oradb-full-{date}.tar.gz (5份)", RED, 22, True),
    ("   最新体积骤缩: 2.5KB 低于下界 3891B（断流/截断嫌疑）", WHITE, 21, False),
    ("   完整性探针[RED]: 流解压失败(截断/损坏):", GOLD, 21, False),
    ("   Compressed file ended before the end-of-stream", GREY, 21, True),
    ("   marker was reached", GREY, 21, True),
    ("", None, 0, True),
    ("# 这份备份由备份任务亲手生成、亲手报告「成功」", GREY, 22, False),
    ("# 但 gzip 流在半截就断了——恢复时才会现形？不，现在就现形", GREY, 22, False),
])

# ---- 3. 恢复演练凭证（demo-run/02-verdict.txt 真实输出；边框用画线保证对齐）
img = Image.new("RGB", (W, H), BG)
d = ImageDraw.Draw(img)
d.rectangle([0, 0, W, 44], fill=BAR)
d.ellipse([24, 15, 36, 27], fill="#ff5f57")
d.ellipse([44, 15, 56, 27], fill="#febc2e")
d.ellipse([64, 15, 76, 27], fill="#28c840")
_title = "$ bakcheck.py verdict ~/backups/webapp/webapp-20260929.tar.gz"
d.text((56, 70), _title, font=F(21, True), fill=WHITE)
# 凭证框：图形画线边框
BX0, BX1, BY0, BY1 = 56, W - 56, 116, 512
d.rectangle([BX0, BY0, BX1, BY1], outline=GOLD, width=2)
d.line([BX0, BY0 + 80, BX1, BY0 + 80], fill=GOLD, width=1)
d.line([BX0, BY1 - 118, BX1, BY1 - 118], fill=GOLD, width=1)
_cert_rows = [
    ("备份恢复演练凭证 RESTORE DRIVEN CERTIFICATE", GOLD, False),
    ("bakcheck v1.0.0  -  2026-09-29 10:18:18", GREY, True),
]
yy = BY0 + 16
for text, color, mono in _cert_rows:
    d.text((BX0 + 24, yy), text, font=F(21, mono and not has_cjk(text)), fill=color)
    yy += 34
_body = [
    ("[GREEN] webapp-{date}.tar.gz (1份)", GREEN, True),
    ("新鲜度OK：最新距今 0分钟", WHITE, False),
    ("历史样本0份（<3），跳过趋势判断--样本不足不外推", WHITE, False),
    ("体积OK: 4.1KB", WHITE, False),
    ("完整性探针[GREEN]: tar结构完整(1个member)", WHITE, False),
]
yy = BY0 + 84
for text, color, mono in _body:
    d.text((BX0 + 24, yy), text, font=F(21, mono and not has_cjk(text)), fill=color)
    yy += 34
_foot = [
    ("综合判级: GREEN = 恢复可用", GREEN, False),
    ("证据指纹 sha256[:16]: 6e92eb5682c2d442", BLUE, True),
    ("审计档: ~/backups/events.jsonl", GREY, True),
]
yy = BY1 - 102
for text, color, mono in _foot:
    d.text((BX0 + 24, yy), text, font=F(21, mono and not has_cjk(text)), fill=color)
    yy += 34
d.text((56, BY1 + 22), "# 值班记录可以贴截图了：指纹+判级+时间戳", font=F(22, False), fill=GREY)
img.save(os.path.join(OUT, "bk-shot-3-cert.png"))
print("bk-shot-3-cert OK")

# ---- 4. 探针覆盖矩阵（README 事实）
shot("bk-shot-4-probes", [
    ("# 每种格式死法不同，探针也不同", GOLD, 24, False),
    (".tar.gz/.tgz/.bz2/.xz  全量流式解压到 EOF", WHITE, 23, True),
    (".tar                  逐 member 走头到包尾", WHITE, 23, True),
    (".zip                  全 member CRC 校验", WHITE, 23, True),
    (".sqlite/.db           PRAGMA quick_check", WHITE, 23, True),
    (".sql/.dump/.7z/.zst   尾部可达 + 非全零", WHITE, 23, True),
    ("", None, 0, True),
    ("探针全部只读：scan 不碰备份目标一个字节", GREEN, 23, False),
    ("大文件不慌: --probe-cap-mb 限流（默认 512MB）", GREY, 22, False),
])

# ---- 5. cron JSON + 退出码（README 事实 + demo-run/06 真实 exit 2）
shot("bk-shot-5-cron", [
    ("$ crontab -l", WHITE, 24, True),
    ("# 每天早上 6:30 体检备份库，出事才吵你", GREY, 22, False),
    ("30 6 * * * bakcheck.py scan ~/backups --json", WHITE, 22, True),
    ("  >> ~/bakcheck.log ; echo $? >> ~/bakcheck.rc", GREY, 22, True),
    ("", None, 0, True),
    ("$ cat ~/bakcheck.rc", WHITE, 24, True),
    ("2   # 0绿 / 1琥珀 / 2红", RED, 22, True),
    ("", None, 0, True),
    ("$ bakcheck.py accept \"app-{date}.tar.gz\" amber \\", WHITE, 23, True),
    ("    --note \"已人工核对可解压\"      # 盖章留审计链", GREY, 22, True),
])

# ---- 6. 自测全绿（demo-run/04-selftest.txt 真实输出）
shot("bk-shot-6-selftest", [
    ("$ python3 bakcheck.py selftest", WHITE, 24, True),
    ("selftest: 26/26 绿", GREEN, 28, True),
    ("四不变量+偏态分布全部通过。", WHITE, 23, False),
    ("", None, 0, True),
    ("# 四不变量:", GOLD, 23, False),
    ("1 只读铁律        scan 不写备份目标一个字节", WHITE, 22, False),
    ("2 样本不足不外推   历史<3份 明说跳过趋势判断", WHITE, 22, False),
    ("3 无备份=最高级警报 空目录是 RED 不是静默通过", WHITE, 22, False),
    ("4 判级必留痕       JSONL 事件 + accept 盖章", WHITE, 22, False),
])
