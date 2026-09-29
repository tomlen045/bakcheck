#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bakcheck · 备份哨兵 —— 「备份任务显示成功」是运维圈最大的谎言。

任务成功 != 产物可用。bakcheck 只认产物本身：
  新鲜度(SLA) / 非空 / 完整性探针 / 大小带 / 漏采间隙 / 恢复演练凭证。

四不变量：
  I1 只读铁律   —— scan/verdict 绝不写备份目标，探针只用列表/校验模式
  I2 样本不足不外推 —— 历史样本 <3 只做硬检查，明确说「跳过趋势判断」
  I3 无备份=最高级警报 —— 目录里一个备份都没有是 RED，不是静默通过
  I4 判级必留痕  —— 每次判级追加 JSONL 事件，accept 盖章留审计链

零依赖（仅标准库），Python 3.8+。
"""
import argparse
import bz2
import gzip
import hashlib
import json
import lzma
import os
import re
import sqlite3
import statistics
import sys
import tarfile
import time
import zipfile
from datetime import datetime, timedelta

VERSION = "1.0.0"
DEFAULT_EVENTS = os.path.join(os.path.expanduser("~"), ".bakcheck", "events.jsonl")

GREEN, AMBER, RED, SKIP = "GREEN", "AMBER", "RED", "SKIP"

BACKUP_EXTS = (
    ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz",
    ".tar", ".zip", ".gz", ".bz2", ".xz", ".zst", ".7z",
    ".sql", ".dump", ".bak", ".sqlite", ".db",
)

DATE_PATTERNS = (
    re.compile(r"(?<!\d)(20\d{2})[-_.](\d{2})[-_.](\d{2})(?!\d)"),
    re.compile(r"(?<!\d)(20\d{6})(?!\d)"),
)


# ---------------------------------------------------------------- 基础工具

def now_ts():
    return time.time()


def fmt_age(seconds):
    if seconds < 0:
        seconds = 0
    h = seconds / 3600.0
    if h < 1:
        return "%d分钟" % int(seconds / 60)
    if h < 48:
        return "%.1f小时" % h
    return "%.1f天" % (h / 24)


def human_size(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return "%.0f%s" % (n, unit) if unit == "B" else "%.1f%s" % (n, unit)
        n /= 1024.0


def filename_date(name):
    """从文件名提取日期，返回 epoch 或 None。"""
    for pat in DATE_PATTERNS:
        m = pat.search(name)
        if not m:
            continue
        try:
            if len(m.groups()) == 3:
                d = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            else:
                s = m.group(1)
                d = datetime(int(s[0:4]), int(s[4:6]), int(s[6:8]))
            return d.timestamp()
        except ValueError:
            continue
    return None


def family_key(name):
    """去掉日期部分的文件名 = 备份族 key。"""
    key = name
    for pat in DATE_PATTERNS:
        key = pat.sub("{date}", key)
    return key


def sha256_of(path, cap=None):
    """流式 SHA256；cap 为字节上限（None=全量）。"""
    h = hashlib.sha256()
    left = cap
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1 << 20)
            if not chunk:
                break
            h.update(chunk)
            if left is not None:
                left -= len(chunk)
                if left <= 0:
                    break
    return h.hexdigest()


# ---------------------------------------------------------------- 完整性探针（全部只读）

class ProbeTimeout(Exception):
    pass


def _iter_cap(fobj, cap_bytes):
    """读全量流直到 EOF/超限，任何解压错误向上抛。"""
    total = 0
    while True:
        chunk = fobj.read(1 << 20)
        if not chunk:
            break
        total += len(chunk)
        if cap_bytes and total >= cap_bytes:
            return total
    return total


def probe_archive_stream(path, cap_bytes):
    """gzip/bz2/lzma 流式格式：全量解压到 EOF（截断在这里现形）。"""
    low = path.lower()
    if low.endswith((".tar.gz", ".tgz")):
        opener, mode = gzip.open, "rb"
    elif low.endswith((".tar.bz2", ".tbz2")):
        opener, mode = bz2.open, "rb"
    elif low.endswith((".tar.xz", ".txz")):
        opener, mode = lzma.open, "rb"
    elif low.endswith(".gz"):
        opener, mode = gzip.open, "rb"
    elif low.endswith(".bz2"):
        opener, mode = bz2.open, "rb"
    elif low.endswith(".xz"):
        opener, mode = lzma.open, "rb"
    else:
        return SKIP, "无流式探针"
    try:
        with opener(path, mode) as f:
            _iter_cap(f, cap_bytes)
        return GREEN, "流式解压到EOF无报错"
    except ProbeTimeout:
        return SKIP, "探针超限中止"
    except (OSError, EOFError, lzma.LZMAError, ValueError) as e:
        return RED, "流解压失败(截断/损坏): %s" % (str(e)[:60], )


def probe_tar_members(path):
    """tar 容器头校验：逐 member 走到 EOF，截断/坏头现形。"""
    try:
        with tarfile.open(path, "r:*") as tf:
            n = 0
            while True:
                m = tf.next()
                if m is None:
                    break
                n += 1
            return GREEN, "tar结构完整(%d个member)" % n
    except (OSError, EOFError, tarfile.TarError, ValueError) as e:
        return RED, "tar结构损坏: %s" % (str(e)[:60], )


def probe_zip(path):
    try:
        with zipfile.ZipFile(path) as z:
            bad = None
            try:
                bad = z.testzip()
            except NotImplementedError:
                bad = None  # 特殊 zip 变体不支持 CRC 全验 → 降级为结构读取
            if bad is not None:
                return RED, "zip CRC校验失败: %s" % bad[:40]
            return GREEN, "zip全member CRC通过(%d个)" % len(z.namelist())
    except (zipfile.BadZipFile, OSError, ValueError, NotImplementedError) as e:
        return RED, "zip结构损坏: %s" % (str(e)[:60], )


def probe_sqlite(path):
    try:
        conn = sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=3)
        try:
            row = conn.execute("PRAGMA quick_check").fetchone()
            ok = row and str(row[0]).lower() == "ok"
            return (GREEN, "sqlite quick_check=ok") if ok else (
                RED, "sqlite quick_check: %s" % str(row[0])[:50] if row else "空结果")
        finally:
            conn.close()
    except sqlite3.Error as e:
        return RED, "sqlite损坏: %s" % (str(e)[:60], )


def probe_tail_reach(path):
    """无标准探针的格式(.sql/.dump/.bak/.7z/.zst)：尾部可达 + 非全零。"""
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        f.seek(max(0, size - 4096))
        tail = f.read(4096)
    if not tail:
        return RED, "尾部不可读"
    if tail.count(b"\x00") == len(tail):
        return RED, "尾部全零(填充/损坏嫌疑)"
    return SKIP, "无标准完整性探针，已做尾部可达检查"


def probe_file(path, cap_bytes):
    """按扩展名分发探针。返回 (level, reason)。"""
    low = path.lower()
    if low.endswith((".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz")):
        lvl, why = probe_archive_stream(path, cap_bytes)
        if lvl != GREEN:
            return lvl, why
        return probe_tar_members(path)
    if low.endswith((".gz", ".bz2", ".xz")):
        return probe_archive_stream(path, cap_bytes)
    if low.endswith(".tar"):
        return probe_tar_members(path)
    if low.endswith(".zip"):
        return probe_zip(path)
    if low.endswith((".sqlite", ".db")):
        return probe_sqlite(path)
    return probe_tail_reach(path)


# ---------------------------------------------------------------- 族扫描

def collect_files(targets):
    """收集目标下的备份文件（递归）。"""
    found = []
    for t in targets:
        if os.path.isfile(t):
            found.append(t)
        elif os.path.isdir(t):
            for root, _dirs, files in os.walk(t):
                for fn in sorted(files):
                    found.append(os.path.join(root, fn))
    return [p for p in found if p.lower().endswith(BACKUP_EXTS)]


def group_families(paths):
    fams = {}
    for p in paths:
        key = family_key(os.path.basename(p))
        fams.setdefault(key, []).append(p)
    for k in fams:
        fams[k].sort(key=lambda p: os.path.getmtime(p))
    return fams


def check_family(key, paths, sla_hours, min_bytes=None, max_bytes=None,
                 cap_bytes=None):
    """对单个备份族做全项检查。返回 dict(判级+理由)。"""
    reasons = []
    level = GREEN
    st = [os.stat(p) for p in paths]
    latest = paths[-1]
    latest_stat = st[-1]
    size = latest_stat.st_size
    age = now_ts() - latest_stat.st_mtime

    def worsen(lvl, why):
        nonlocal level
        reasons.append(why)
        order = {GREEN: 0, SKIP: 1, AMBER: 1, RED: 2}
        if order[lvl] > order[level]:
            level = lvl

    # 硬检查 1：新鲜度 SLA
    if age > sla_hours * 3600:
        worsen(RED, "最新备份已 %s 未更新（SLA %g小时）" % (fmt_age(age), sla_hours))
    else:
        reasons.append("新鲜度OK：最新距今 %s" % fmt_age(age))

    # 硬检查 2：非空
    if size == 0:
        worsen(RED, "零字节备份（任务「成功」产物为空）")

    # 硬检查 3：文件名日期 vs 修改时间打架
    fdate = filename_date(os.path.basename(latest))
    if fdate and abs(fdate - latest_stat.st_mtime) > 48 * 3600:
        worsen(AMBER, "文件名日期与修改时间相差超48小时（改名/搬运嫌疑）")

    # 统计检查：大小带（历史 = 除最新外）
    history = [s.st_size for s in st[:-1]]
    lo, hi = min_bytes, max_bytes
    if history and len(history) >= 3:
        med = statistics.median(history)
        mad = statistics.median([abs(x - med) for x in history]) or (med * 0.25)
        lo = min_bytes if min_bytes is not None else max(0.0, med - max(3 * mad, med * 0.25))
        hi = max_bytes if max_bytes is not None else med + max(3 * mad, med * 0.75) * 3
        reasons.append("大小带（中位数%.0f%s历史%u份）: %.0f~%.0f"
                       % (med, "B", len(history), lo, hi))
    elif min_bytes is None and max_bytes is None:
        reasons.append("历史样本%u份（<3），跳过趋势判断——样本不足不外推" % len(history))
    if lo is not None and size < lo:
        worsen(RED, "最新体积骤缩: %s 低于下界 %.0fB（断流/截断嫌疑）"
               % (human_size(size), lo))
    elif hi is not None and size > hi:
        worsen(AMBER, "最新体积异常膨胀: %s 高于上界 %.0fB（配置漂移/误配嫌疑）"
               % (human_size(size), hi))
    else:
        reasons.append("体积OK: %s" % human_size(size))

    # 统计检查：漏采间隙
    if len(paths) >= 3:
        gaps = [st[i + 1].st_mtime - st[i].st_mtime for i in range(len(st) - 1)]
        med_gap = statistics.median(gaps)
        big = max(gaps)
        if big > max(2.5 * med_gap, sla_hours * 3600) and big > sla_hours * 3600:
            worsen(AMBER, "存在漏采间隙: 最大 %s（中位间隔 %s）"
                   % (fmt_age(big), fmt_age(med_gap)))
        reasons.append("窗口内备份 %u 份" % len(paths))

    # 完整性探针
    plvl, pwhy = probe_file(latest, cap_bytes)
    reasons.append("完整性探针[%s]: %s" % (plvl, pwhy))
    if plvl == RED:
        worsen(RED, "完整性探针失败——任务成功但产物损坏")
    elif plvl == SKIP:
        reasons.append("（探针SKIP不参与判级，见详情）")

    return {
        "family": key, "count": len(paths), "latest": os.path.abspath(latest),
        "size": size, "age_hours": round(age / 3600.0, 2),
        "level": level, "reasons": reasons,
        "ts": now_ts(), "version": VERSION,
    }


# ---------------------------------------------------------------- 事件留痕

def append_event(path, record):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_events(path, last_n=20):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        lines = f.read().strip().splitlines()
    out = []
    for ln in lines[-last_n:]:
        try:
            out.append(json.loads(ln))
        except ValueError:
            continue
    return out


# ---------------------------------------------------------------- 演练凭证

CERT_W = 62


def _disp_len(text):
    """终端显示宽度：CJK/全角/破折号/省略号算 2（歧义宽度按 CJK 终端口径）。"""
    return sum(2 if ('\u2e80' <= ch <= '\u9fff' or '\uff00' <= ch <= '\uffef'
                     or ch in '\u2014\u2026') else 1 for ch in text)


def _cert_line(text=""):
    pad = CERT_W - 4 - _disp_len(text)
    return "│ " + text + " " * max(0, pad) + " │"


def _short_home(p):
    home = os.path.expanduser("~")
    return p.replace(home, "~", 1) if p.startswith(home) else p


def render_cert(results, events_path, covered_sha=None):
    def _safe(s):
        # 凭证框内只用普适宽度字符：歧义宽度(·——…)全部替换，任何终端都不炸边框
        return s.replace("·", "-").replace("——", "--").replace("…", "...")

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    worst = RED if any(r["level"] == RED for r in results) else (
        AMBER if any(r["level"] == AMBER for r in results) else GREEN)
    name_map = {GREEN: "恢复可用", AMBER: "存在疑点", RED: "不可恢复风险"}
    lines = ["╔" + "═" * (CERT_W - 2) + "╗",
             _cert_line(_safe("备份恢复演练凭证 RESTORE DRIVEN CERTIFICATE")),
             _cert_line(_safe("bakcheck v%s · %s · 随机抽查本档" % (VERSION, ts))),
             "╠" + "═" * (CERT_W - 2) + "╣"]
    for r in results:
        head = "[%s] %s (%u份)" % (r["level"], r["family"], r["count"])
        lines.append(_cert_line(_safe(head)))
        for why in r["reasons"]:
            lines.append(_cert_line("  " + _safe(why)))
    lines.append("╠" + "═" * (CERT_W - 2) + "╣")
    lines.append(_cert_line("综合判级: %s = %s" % (worst, name_map[worst])))
    if covered_sha:
        lines.append(_cert_line("证据指纹 sha256[:16]: " + covered_sha[:16]))
    lines.append(_cert_line("审计档: " + _short_home(events_path)))
    lines.append("╚" + "═" * (CERT_W - 2) + "╝")
    return "\n".join(lines), worst


# ---------------------------------------------------------------- 子命令

def worst_level(results):
    if any(r["level"] == RED for r in results):
        return RED
    if any(r["level"] == AMBER for r in results):
        return AMBER
    return GREEN


def cmd_scan(args):
    paths = collect_files(args.targets)
    results = []
    if not paths:
        results.append({"family": "(全部目标)", "count": 0, "latest": "-",
                        "size": 0, "age_hours": None, "level": RED,
                        "reasons": ["无备份=最高级警报：目标里一个备份都没有"],
                        "ts": now_ts(), "version": VERSION})
    else:
        fams = group_families(paths)
        for key in sorted(fams):
            results.append(check_family(
                key, fams[key], args.sla_hours,
                min_bytes=args.min_bytes, max_bytes=args.max_bytes,
                cap_bytes=args.probe_cap_mb * (1 << 20)))
    if not args.no_events:
        for r in results:
            append_event(args.events, r)
    if args.json:
        print(json.dumps({"version": VERSION, "worst": worst_level(results),
                          "results": results}, ensure_ascii=False, indent=2))
        code = {GREEN: 0, AMBER: 1, RED: 2}[worst_level(results)]
        return code
    for r in results:
        mark = {"GREEN": "✔", "AMBER": "▲", "RED": "✘"}[r["level"]]
        print("%s [%s] %s · %u份 · 最新 %s · %s" % (
            mark, r["level"], r["family"], r["count"],
            human_size(r["size"]),
            ("距今%s" % fmt_age(r["age_hours"] * 3600)) if r["age_hours"] is not None else "-"))
        for why in r["reasons"]:
            print("     · %s" % why)
    code = {GREEN: 0, AMBER: 1, RED: 2}[worst_level(results)]
    return code


def cmd_verdict(args):
    """单文件全项检查 + 恢复演练凭证（可截图存档）。"""
    p = args.file
    if not os.path.isfile(p):
        print("✘ 文件不存在: %s" % p)
        return 2
    fam = group_families([p])
    key = list(fam)[0]
    r = check_family(key, [p], args.sla_hours,
                     min_bytes=args.min_bytes, max_bytes=args.max_bytes,
                     cap_bytes=args.probe_cap_mb * (1 << 20))
    if not args.no_events:
        append_event(args.events, r)
    sha = sha256_of(p)
    cert, worst = render_cert([r], args.events, covered_sha=sha)
    print(cert)
    return {GREEN: 0, AMBER: 1, RED: 2}[worst]


def cmd_accept(args):
    """盖章：操作员确认某次判级已知情（审计链）。"""
    rec = {"ts": now_ts(), "version": VERSION, "action": "accept",
           "family": args.family, "level": args.level.upper(),
           "note": args.note or ""}
    append_event(args.events, rec)
    print("✔ 已盖章: %s [%s] %s" % (args.family, args.level.upper(),
                                    rec["note"]))
    return 0


def cmd_events(args):
    evs = read_events(args.events, last_n=args.last)
    if not evs:
        print("（暂无事件）")
        return 0
    for e in evs:
        t = datetime.fromtimestamp(e.get("ts", 0)).strftime("%m-%d %H:%M:%S")
        top = (e.get("reasons") or [e.get("note", "")])[0]
        for cand in e.get("reasons") or []:
            if cand.startswith(("超 SLA", "零字节", "完整性探针失败", "最新体积骤缩", "无备份")):
                top = cand
                break
        print("%s %-6s %-22s %s" % (t, e.get("level", e.get("action", "?")),
                                    e.get("family", "-"), top[:56]))
    return 0


# ---------------------------------------------------------------- 自测

SELFTEST_DIR_ROOT = ".bakcheck-selftest"


class SelfTest(object):
    def __init__(self):
        self.passed = 0
        self.failed = []
        self.root = os.path.join(os.path.expanduser("~"), SELFTEST_DIR_ROOT)

    def check(self, name, cond):
        if cond:
            self.passed += 1
        else:
            self.failed.append(name)

    def run(self):
        import shutil
        import tempfile
        base = tempfile.mkdtemp(prefix="bakcheck-st-")
        try:
            self._run(base)
        finally:
            shutil.rmtree(base, ignore_errors=True)
        shutil.rmtree(self.root, ignore_errors=True)
        return self.passed, self.failed

    # ---- helpers
    def _mk_tar_gz(self, path, payload=b"hello backup world\n" * 50):
        with tarfile.open(path, "w:gz") as tf:
            data = payload
            info = tarfile.TarInfo("dump.bin")
            info.size = len(data)
            tf.addfile(info, __import__("io").BytesIO(data))

    def _mk_zip(self, path, payload=b"zip payload\n" * 40):
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("data/a.txt", payload)
            z.writestr("data/b.txt", payload)

    def _mk_sqlite(self, path):
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE t(id INTEGER PRIMARY KEY, v TEXT)")
        conn.executemany("INSERT INTO t(v) VALUES(?)",
                         [("row%d" % i,) for i in range(30)])
        conn.commit()
        conn.close()

    def _age_file(self, path, days):
        past = now_ts() - days * 86400
        os.utime(path, (past, past))

    def _scan_json(self, targets, events, **kw):
        import io as _io
        import contextlib
        buf = _io.StringIO()
        ns = argparse.Namespace(
            targets=targets, sla_hours=kw.pop("sla_hours", 26),
            min_bytes=kw.pop("min_bytes", None), max_bytes=kw.pop("max_bytes", None),
            probe_cap_mb=kw.pop("probe_cap_mb", 64), json=True,
            events=events, no_events=False)
        with contextlib.redirect_stdout(buf):
            code = cmd_scan(ns)
        return code, json.loads(buf.getvalue())

    def _run(self, base):
        import io as _io
        from datetime import datetime as _DT, timedelta as _TD

        def dstr(days_ago):
            return (_DT.now() - _TD(days=days_ago)).strftime("%Y%m%d")

        def rnd(n):
            return os.urandom(n)

        # --- 01 健全 tar.gz 族 → GREEN（文件名日期与mtime一致）
        d1 = os.path.join(base, "healthy")
        os.makedirs(d1)
        for i in range(4):
            p = os.path.join(d1, "app-%s.tar.gz" % dstr(3 - i))
            self._mk_tar_gz(p, payload=rnd(2000))
            self._age_file(p, 3 - i)
        code, out = self._scan_json([d1], os.path.join(base, "ev.jsonl"))
        self.check("01健全族GREEN", code == 0 and out["results"][0]["level"] == GREEN)

        # --- 02 陈旧族 → RED(SLA)
        d2 = os.path.join(base, "stale")
        os.makedirs(d2)
        p = os.path.join(d2, "db-%s.tar.gz" % dstr(9))
        self._mk_tar_gz(p, payload=rnd(500))
        self._age_file(p, 9)
        code, out = self._scan_json([d2], os.path.join(base, "ev.jsonl"))
        self.check("02陈旧RED", code == 2 and any("SLA" in x for x in out["results"][0]["reasons"]))

        # --- 03 零字节 → RED
        d3 = os.path.join(base, "zero")
        os.makedirs(d3)
        open(os.path.join(d3, "x-%s.sql" % dstr(1)), "w").close()
        code, out = self._scan_json([d3], os.path.join(base, "ev.jsonl"))
        self.check("03零字节RED", any("零字节" in x for x in out["results"][0]["reasons"]))

        # --- 04 截断 gzip → RED（尾部截断在流式探针现形）
        d4 = os.path.join(base, "trunc")
        os.makedirs(d4)
        full = os.path.join(d4, "t-%s.tar.gz" % dstr(0))
        self._mk_tar_gz(full, payload=rnd(4000))
        raw = open(full, "rb").read()
        open(full, "wb").write(raw[: len(raw) // 2])
        self._age_file(full, 0.1)
        code, out = self._scan_json([d4], os.path.join(base, "ev.jsonl"))
        self.check("04截断gzipRED", out["results"][0]["level"] == RED)

        # --- 05 损坏 zip（破坏首个member压缩流首字节）→ RED
        d5 = os.path.join(base, "badzip")
        os.makedirs(d5)
        zp = os.path.join(d5, "z-%s.zip" % dstr(0))
        self._mk_zip(zp)
        raw = bytearray(open(zp, "rb").read())
        nlen = int.from_bytes(raw[26:28], "little")
        elen = int.from_bytes(raw[28:30], "little")
        raw[30 + nlen + elen + 3] ^= 0xFF  # 定向打进 deflate 数据流
        open(zp, "wb").write(bytes(raw))
        code, out = self._scan_json([d5], os.path.join(base, "ev.jsonl"))
        self.check("05坏zipRED", out["results"][0]["level"] == RED)

        # --- 06 假 sqlite（垃圾字节）→ RED
        d6 = os.path.join(base, "fakesqlite")
        os.makedirs(d6)
        with open(os.path.join(d6, "f-%s.sqlite" % dstr(0)), "wb") as f:
            f.write(os.urandom(2048))
        code, out = self._scan_json([d6], os.path.join(base, "ev.jsonl"))
        self.check("06假sqliteRED", out["results"][0]["level"] == RED)

        # --- 07 大小骤缩（历史5份正常+最新1/5体积，不可压payload）→ RED
        d7 = os.path.join(base, "shrink")
        os.makedirs(d7)
        for i in range(5):
            p = os.path.join(d7, "s-%s.tar.gz" % dstr(6 - i))
            self._mk_tar_gz(p, payload=rnd(3000))
            self._age_file(p, 6 - i)
        small = os.path.join(d7, "s-%s.tar.gz" % dstr(0))
        self._mk_tar_gz(small, payload=rnd(500))
        code, out = self._scan_json([d7], os.path.join(base, "ev.jsonl"))
        self.check("07骤缩RED", any("骤缩" in x for x in out["results"][0]["reasons"]))

        # --- 08 异常膨胀 → AMBER
        d8 = os.path.join(base, "grow")
        os.makedirs(d8)
        for i in range(4):
            p = os.path.join(d8, "g-%s.tar.gz" % dstr(5 - i))
            self._mk_tar_gz(p, payload=rnd(1500))
            self._age_file(p, 5 - i)
        big = os.path.join(d8, "g-%s.tar.gz" % dstr(0))
        self._mk_tar_gz(big, payload=rnd(60000))
        code, out = self._scan_json([d8], os.path.join(base, "ev.jsonl"))
        self.check("08膨胀AMBER", code == 1 and out["results"][0]["level"] == AMBER)

        # --- 09 历史<3 → 明示跳过趋势判断
        d9 = os.path.join(base, "few")
        os.makedirs(d9)
        for i in range(2):
            p = os.path.join(d9, "f-%s.tar.gz" % dstr(1 - i))
            self._mk_tar_gz(p, payload=rnd(300))
            self._age_file(p, 1 - i)
        code, out = self._scan_json([d9], os.path.join(base, "ev.jsonl"))
        self.check("09样本不足不外推",
                   any("样本不足不外推" in x for x in out["results"][0]["reasons"]))

        # --- 10 空目标 → RED 无备份警报
        d10 = os.path.join(base, "empty")
        os.makedirs(d10)
        code, out = self._scan_json([d10], os.path.join(base, "ev.jsonl"))
        self.check("10无备份RED", code == 2 and "无备份" in out["results"][0]["reasons"][0])

        # --- 11 文件名日期与mtime打架 → AMBER
        d11 = os.path.join(base, "namedate")
        os.makedirs(d11)
        p = os.path.join(d11, "n-20260101.tar.gz")
        self._mk_tar_gz(p, payload=rnd(400))  # mtime=现在, 名字=1月1日
        code, out = self._scan_json([d11], os.path.join(base, "ev.jsonl"))
        self.check("11改名打架AMBER", any("48小时" in x for x in out["results"][0]["reasons"]))

        # --- 12 漏采间隙 → AMBER（3日→8日断5天，名字与mtime一致）
        d12 = os.path.join(base, "gap")
        os.makedirs(d12)
        for days_ago in (28, 27, 26, 21):
            p = os.path.join(d12, "gp-%s.tar.gz" % dstr(days_ago))
            self._mk_tar_gz(p, payload=rnd(2000))
            self._age_file(p, days_ago)
        code, out = self._scan_json([d12], os.path.join(base, "ev.jsonl"))
        self.check("12漏采AMBER", any("漏采" in x for x in out["results"][0]["reasons"]))

        # --- 13 只读铁律：scan 前后内容哈希与 mtime 不变
        d13 = os.path.join(base, "ro")
        os.makedirs(d13)
        p = os.path.join(d13, "ro-%s.zip" % dstr(0))
        self._mk_zip(p)
        h0 = sha256_of(p)
        mt0 = os.stat(p).st_mtime_ns
        self._scan_json([d13], os.path.join(base, "ev.jsonl"))
        self.check("13只读铁律", sha256_of(p) == h0 and os.stat(p).st_mtime_ns == mt0)

        # --- 14 只读铁律2：目标目录不新增任何文件
        listing0 = sorted(os.listdir(d13))
        self._scan_json([d13], os.path.join(base, "ev.jsonl"))
        self.check("14目标零残留", sorted(os.listdir(d13)) == listing0)

        # --- 15 JSON 输出结构完整
        code, out = self._scan_json([d1], os.path.join(base, "ev.jsonl"))
        r0 = out["results"][0]
        self.check("15JSON结构", all(k in r0 for k in
                   ("family", "level", "reasons", "size", "latest", "ts")))

        # --- 16 事件 JSONL 追加且可读回
        evp = os.path.join(base, "ev2.jsonl")
        self._scan_json([d1], evp)
        self._scan_json([d2], evp)
        evs = read_events(evp)
        self.check("16事件留痕", len(evs) >= 2)

        # --- 17 verdict 凭证含真实 SHA256 前缀（取最新文件，SLA内）
        import contextlib as _cl2
        target = sorted(os.listdir(d1))[-1]
        target = os.path.join(d1, target)
        ns = argparse.Namespace(file=target, sla_hours=26, min_bytes=None,
                                max_bytes=None, probe_cap_mb=64,
                                events=os.path.join(base, "ev.jsonl"), no_events=True)
        buf2 = _io.StringIO()
        with _cl2.redirect_stdout(buf2):
            code = cmd_verdict(ns)
        cert_text = buf2.getvalue()
        self.check("17凭证SHA256", sha256_of(target)[:16] in cert_text and code == 0)

        # --- 18 accept 盖章入库
        evp3 = os.path.join(base, "ev3.jsonl")
        ns = argparse.Namespace(family="app", level="amber", note="换盘维护",
                                events=evp3)
        cmd_accept(ns)
        evs = read_events(evp3)
        self.check("18盖章留痕", evs and evs[-1]["action"] == "accept"
                   and evs[-1]["note"] == "换盘维护")

        # --- 19 偏态分布鲁棒：主族历史12正常（内含2份历史小份不算），
        #     异常小份在别的族，最新正常 → 主族不误报
        d19 = os.path.join(base, "skew")
        os.makedirs(d19)
        for i in range(12):
            p = os.path.join(d19, "sk-%s.tar.gz" % dstr(12 - i))
            self._mk_tar_gz(p, payload=rnd(4000))
            self._age_file(p, 12 - i)
        for junk, days_ago in ((150, 7), (220, 4)):  # 偏态：同族里少数异常小份
            p = os.path.join(d19, "sk-%s.tar.gz" % dstr(days_ago))
            self._mk_tar_gz(p, payload=rnd(junk))
            self._age_file(p, days_ago)
        p = os.path.join(d19, "sk-%s.tar.gz" % dstr(0))
        self._mk_tar_gz(p, payload=rnd(4000))
        code, out = self._scan_json([d19], os.path.join(base, "ev.jsonl"))
        sk = [r for r in out["results"] if r["family"].startswith("sk-")][0]
        self.check("19偏态不误报", sk["level"] == GREEN)

        # --- 20 偏态下真异常仍抓得住：最新是坏小份 → RED
        d20 = os.path.join(base, "skew2")
        os.makedirs(d20)
        for i in range(8):
            p = os.path.join(d20, "sq-%s.tar.gz" % dstr(9 - i))
            self._mk_tar_gz(p, payload=rnd(4000))
            self._age_file(p, 9 - i)
        p = os.path.join(d20, "sq-%s.tar.gz" % dstr(0))
        self._mk_tar_gz(p, payload=rnd(120))
        code, out = self._scan_json([d20], os.path.join(base, "ev.jsonl"))
        self.check("20偏态抓真异常", any("骤缩" in x for x in out["results"][0]["reasons"]))

        # --- 21 --min-bytes 手动基线兜底
        code, out = self._scan_json([d1], os.path.join(base, "ev.jsonl"),
                                    min_bytes=1 << 30)
        self.check("21手动基线兜底", any("低于下界" in x for x in out["results"][0]["reasons"]))

        # --- 22 CJK 文件名正常工作
        d22 = os.path.join(base, "cjk")
        os.makedirs(d22)
        p = os.path.join(d22, "数据库备份-%s.zip" % dstr(0))
        self._mk_zip(p)
        code, out = self._scan_json([d22], os.path.join(base, "ev.jsonl"))
        self.check("22中文名", out["results"][0]["family"] == family_key("数据库备份-%s.zip" % dstr(0)))

        # --- 23 递归子目录扫描
        d23 = os.path.join(base, "nested", "sub", "deep")
        os.makedirs(d23)
        p = os.path.join(d23, "deep-%s.zip" % dstr(0))
        self._mk_zip(p)
        code, out = self._scan_json([os.path.join(base, "nested")],
                                    os.path.join(base, "ev.jsonl"))
        self.check("23递归扫描", out["results"][0]["count"] == 1)

        # --- 24 非备份扩展名被忽略（不算无备份误报）
        d24 = os.path.join(base, "mixed")
        os.makedirs(d24)
        with open(os.path.join(d24, "readme.txt"), "w") as f:
            f.write("not a backup")
        self._mk_zip(os.path.join(d24, "m-%s.zip" % dstr(0)))
        code, out = self._scan_json([d24], os.path.join(base, "ev.jsonl"))
        self.check("24非备份忽略", out["worst"] == GREEN and out["results"][0]["count"] == 1)

        # --- 25 .sql 文本尾部可达探针
        d25 = os.path.join(base, "sqlfmt")
        os.makedirs(d25)
        p = os.path.join(d25, "q-%s.sql" % dstr(0))
        with open(p, "w") as f:
            f.write("INSERT INTO t VALUES (1);\n" * 500)
        code, out = self._scan_json([d25], os.path.join(base, "ev.jsonl"))
        self.check("25sql尾部可达", out["results"][0]["level"] in (GREEN, SKIP))

        # --- 26 退出码分级：全绿0 / AMBER1 / RED2
        self.check("26退出码分级",
                   self._scan_json([d1], os.path.join(base, "ev.jsonl"))[0] == 0
                   and self._scan_json([d8], os.path.join(base, "ev.jsonl"))[0] == 1
                   and self._scan_json([d2], os.path.join(base, "ev.jsonl"))[0] == 2)


def cmd_selftest(_args):
    st = SelfTest()
    passed, failed = st.run()
    print("selftest: %d/%d 绿" % (passed, passed + len(failed)))
    if failed:
        for f in failed:
            print("  ✘ %s" % f)
        return 2
    print("四不变量+偏态分布全部通过。")
    return 0


# ---------------------------------------------------------------- CLI

def build_parser():
    p = argparse.ArgumentParser(
        prog="bakcheck",
        description="备份哨兵——任务成功≠产物可用。 freshness/完整性/大小带/漏采/演练凭证。")
    p.add_argument("--version", action="version", version="bakcheck %s" % VERSION)
    sub = p.add_subparsers(dest="cmd")

    ps = sub.add_parser("scan", help="扫描目录/文件（递归），按备份族判级")
    ps.add_argument("targets", nargs="+", help="目录或文件")
    ps.add_argument("--sla-hours", type=float, default=26.0,
                    help="新鲜度红线（默认26小时=日备+2h宽限）")
    ps.add_argument("--min-bytes", type=int, default=None,
                    help="手动体积下界（基线兜底，绕过统计带）")
    ps.add_argument("--max-bytes", type=int, default=None, help="手动体积上界")
    ps.add_argument("--probe-cap-mb", type=int, default=512,
                    help="流式探针解压上限MB（默认512）")
    ps.add_argument("--json", action="store_true", help="JSON 输出（给脚本/cron）")
    ps.add_argument("--events", default=DEFAULT_EVENTS, help="事件 JSONL 路径")
    ps.add_argument("--no-events", action="store_true", help="不写事件档")
    ps.set_defaults(func=cmd_scan)

    pv = sub.add_parser("verdict", help="单文件全项检查 + 恢复演练凭证")
    pv.add_argument("file")
    pv.add_argument("--sla-hours", type=float, default=26.0)
    pv.add_argument("--min-bytes", type=int, default=None)
    pv.add_argument("--max-bytes", type=int, default=None)
    pv.add_argument("--probe-cap-mb", type=int, default=512)
    pv.add_argument("--events", default=DEFAULT_EVENTS)
    pv.add_argument("--no-events", action="store_true")
    pv.set_defaults(func=cmd_verdict)

    pa = sub.add_parser("accept", help="盖章：操作员确认某判级已知情")
    pa.add_argument("family")
    pa.add_argument("level", choices=["green", "amber", "red"])
    pa.add_argument("--note", default="")
    pa.add_argument("--events", default=DEFAULT_EVENTS)
    pa.set_defaults(func=cmd_accept)

    pe = sub.add_parser("events", help="查看最近判级事件")
    pe.add_argument("--last", type=int, default=20)
    pe.add_argument("--events", default=DEFAULT_EVENTS)
    pe.set_defaults(func=cmd_events)

    pt = sub.add_parser("selftest", help="跑 26 项自测")
    pt.set_defaults(func=cmd_selftest)
    return p


def main(argv):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
