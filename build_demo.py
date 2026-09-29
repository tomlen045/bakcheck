#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""建演示备份库 + 真实跑 bakcheck 全流程，输出全部 tee 进 demo-run/ 供实拍图取材。"""
import io
import os
import subprocess
import sys
import tarfile
import zipfile
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "bakcheck.py")
DEMO = os.path.join(HERE, "demo-backups")
RUN = os.path.join(HERE, "demo-run")
os.makedirs(RUN, exist_ok=True)


def dstr(days_ago):
    return (datetime.now() - timedelta(days=days_ago)).strftime("%Y%m%d")


def age(path, days):
    past = datetime.now().timestamp() - days * 86400
    os.utime(path, (past, past))


def mk_tar_gz(path, n):
    with tarfile.open(path, "w:gz") as tf:
        data = os.urandom(n)
        info = tarfile.TarInfo("dump/data.bin")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))


def mk_zip(path, n):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("etc/app.conf", os.urandom(n))
        z.writestr("etc/hosts.txt", os.urandom(n // 3))


# ---- 族1 webapp: 健康日备 (day6..0)
fam1 = os.path.join(DEMO, "webapp")
os.makedirs(fam1, exist_ok=True)
for d in range(6, -1, -1):
    p = os.path.join(fam1, "webapp-%s.tar.gz" % dstr(d))
    mk_tar_gz(p, 4000)
    age(p, d)

# ---- 族2 oradb: 最新一份是截断的 tar.gz（任务成功产物半截）
fam2 = os.path.join(DEMO, "oradb")
os.makedirs(fam2, exist_ok=True)
for d in range(4, 0, -1):
    p = os.path.join(fam2, "oradb-full-%s.tar.gz" % dstr(d))
    mk_tar_gz(p, 5000)
    age(p, d)
p = os.path.join(fam2, "oradb-full-%s.tar.gz" % dstr(0))
mk_tar_gz(p, 5000)
raw = open(p, "rb").read()
open(p, "wb").write(raw[: len(raw) // 2])  # 截断
age(p, 0)

# ---- 族3 configdb: 零字节 .sql（任务退出码0但产物空）
fam3 = os.path.join(DEMO, "configdb")
os.makedirs(fam3, exist_ok=True)
p = os.path.join(fam3, "configdb-%s.sql" % dstr(0))
open(p, "w").close()

# ---- 族4 filesrv: 8天没更新（SLA超时）
fam4 = os.path.join(DEMO, "filesrv")
os.makedirs(fam4, exist_ok=True)
p = os.path.join(fam4, "filesrv-%s.zip" % dstr(8))
mk_zip(p, 3000)
age(p, 8)

EV = os.path.join(DEMO, "events.jsonl")
if os.path.exists(EV):
    os.remove(EV)

CMDS = [
    ("01-scan.txt", [sys.executable, TOOL, "scan", DEMO, "--events", EV]),
    ("02-verdict.txt", [sys.executable, TOOL, "verdict",
                        os.path.join(fam1, "webapp-%s.tar.gz" % dstr(0)),
                        "--events", EV, "--no-events"]),
    ("03-verdict-trunc.txt", [sys.executable, TOOL, "verdict",
                              os.path.join(fam2, "oradb-full-%s.tar.gz" % dstr(0)),
                              "--events", EV, "--no-events"]),
    ("04-selftest.txt", [sys.executable, TOOL, "selftest"]),
    ("05-events.txt", [sys.executable, TOOL, "events", "--events", EV, "--last", "8"]),
    ("06-accept.json.txt", [sys.executable, TOOL, "scan", DEMO, "--json",
                            "--events", EV, "--no-events"]),
]
for name, cmd in CMDS:
    r = subprocess.run(cmd, capture_output=True, text=True)
    out = ("$ %s\n" % " ".join(cmd[1:])) + r.stdout
    if r.returncode:
        out += "\n[exit %d]\n%s" % (r.returncode, r.stderr)
    with open(os.path.join(RUN, name), "w", encoding="utf-8") as f:
        f.write(out)
    print("==", name, "exit", r.returncode)
print("demo built at", DEMO)
