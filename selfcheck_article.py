#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""公众号排版 HTML 发布前自检：标签配对/双分号/87%宽度/显式对齐/敏感信息扫描。"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TARGET = os.path.join(HERE, "公众号排版版.html")
html = open(TARGET, encoding="utf-8").read()
errors = []

# 1. 标签配对（自闭合与 void 元素除外）
stack = []
voids = {"br", "img", "meta", "hr", "input", "link"}
for m in re.finditer(r"<(/?)([a-zA-Z0-9]+)([^>]*?)(/?)>", html):
    close, tag, attrs, selfclose = m.groups()
    if tag.lower() in voids or selfclose:
        continue
    if not close:
        stack.append((tag, m.start()))
    else:
        if not stack or stack[-1][0].lower() != tag.lower():
            errors.append("标签错配: </%s> at %d" % (tag, m.start()))
        else:
            stack.pop()
if stack:
    errors.append("未闭合标签: %s" % [s[0] for s in stack])

# 2. 双分号
if ";;" in html:
    errors.append("存在双分号 ;; (%d处)" % html.count(";;"))

# 3. 卡片 section 87% + margin auto + box-sizing
cards = re.findall(r'<section style="([^"]*)"', html)
for i, st in enumerate(cards):
    for need in ("width:87%", "margin-left:auto", "margin-right:auto", "box-sizing:border-box"):
        if need not in st:
            errors.append("卡片%d缺 %s" % (i + 1, need))

# 4. 显式对齐：所有 p/section 必须带 text-align
nodes = re.findall(r"<(p|section)([^>]*)>", html)
noalign = [i for i, (tag, attrs) in enumerate(nodes) if "text-align" not in attrs]
if noalign:
    errors.append("%d 个 p/section 缺显式对齐: %s" % (len(noalign), noalign[:5]))

# 5. 敏感信息（含空格变体）
sensitive = [
    r"172\.16\.", r"172\.18\.", r"10\.92[ .]", r"10\.213\.", r"Appmobsf",
    r"Aixdr#", r"352c9c67", r"ghp_[A-Za-z0-9]", r"br-624580c9bf89",
    r"ssh-ed25519", r"192\.168\.(?!1\.1\b)", r"root@",
]
for pat in sensitive:
    for m in re.finditer(pat, html):
        errors.append("敏感信息命中 %r: ...%s..." % (pat, html[max(0, m.start()-20):m.end()+20].replace("\n", " ")))

# 6. 图片：CDN 或同目录存在
for m in re.finditer(r'<img src="([^"]+)"', html):
    src = m.group(1)
    if src.startswith("https://cdn.jsdelivr.net/gh/tomlen045/bakcheck@main/"):
        local = os.path.join(HERE, src.split("@main/", 1)[1])
        if not os.path.exists(local):
            errors.append("CDN 图无本地对应: %s" % local)
    elif not src.startswith("http"):
        if not os.path.exists(os.path.join(HERE, src)):
            errors.append("本地图不存在: %s" % src)

print("自检 %s" % ("FAIL" if errors else "PASS"))
for e in errors:
    print("  ✘", e)
if not errors:
    print("  标签配对 OK / 无双分号 / %d 卡片87%%规格 OK / %d 节点显式对齐 OK / 敏感信息零命中 / 图源齐全"
          % (len(cards), len(nodes)))
sys.exit(1 if errors else 0)
