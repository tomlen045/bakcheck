# bakcheck

[中文](README.md) | [English](README_EN.md)

**Backup Sentinel** — "the backup job said OK" is the biggest lie in ops: exit code 0 ≠ restorable artifact.
cronguard watches whether the job ran ([cronguard](https://github.com/tomlen045/cronguard)), capguard watches how many days until the disk fills ([capguard](https://github.com/tomlen045/capguard)), **bakcheck watches the backup artifacts themselves**.

bakcheck only trusts the artifact: freshness / non-empty / integrity probes / size band / gap detection / restore-drill certificate.

[![tests](https://img.shields.io/badge/self--tests-26%2F26-green)]() [![deps](https://img.shields.io/badge/deps-zero-yellow)]() [![license](https://img.shields.io/badge/license-MIT-blue)]()

---

## What problem does it solve

* Backup jobs report "success" every day, and restore day reveals a truncated tar → **streaming integrity probes**: gzip/bz2/xz fully decompressed to EOF, tar member-by-member header walk, zip full-member CRC, sqlite `quick_check` — truncation and corruption surface on the spot
* The backup directory got wiped/moved silently → **an empty backup dir is a top-level RED alarm**, never a silent pass
* The latest backup shrank to 1/3 of its usual size (broken script / lost DB connection) → **size band**: median + MAD learns the historical range; shrink = RED, bloat = AMBER; with fewer than 3 historical samples it explicitly says "insufficient samples, skipping trend inference" — never invents a number
* Backups silently stopped 5 days ago → **gap detection**: max interval > 2.5× the median interval gets called out
* The filename says today but the file is last week's renamed copy → **filename-date vs mtime mismatch** (over 48h = AMBER)
* Postmortems can't answer "who knew what, when" → **every verdict appends a JSONL event**, `accept` stamps the audit trail; `verdict` issues a **restore-drill certificate** (with SHA256 fingerprint) you can screenshot and archive
* Tighter SLA? → `--sla-hours` (default 26h = daily backup + 2h grace)

## Install

```bash
# One-shot installer (Gitee → GitHub → jsDelivr failover)
curl -fsSL https://gitee.com/tomlen/bakcheck/raw/main/install.sh | sh

# Or grab the single file directly (stdlib only, Python 3.8+)
curl -fsSLO https://gitee.com/tomlen/bakcheck/raw/main/bakcheck.py
```

## 30-second start

```bash
# 1) Scan backup dirs (recursive; grouped into "families" by date-stripped filename)
python3 bakcheck.py scan /var/backups /data/db-dumps

# 2) Stricter: 4-hour SLA (a DB backed up every 2 hours)
python3 bakcheck.py scan /var/backups --sla-hours 4

# 3) Issue a restore-drill certificate for one artifact (screenshot into the on-call log)
python3 bakcheck.py verdict /var/backups/app-20260929.tar.gz

# 4) Stamp an AMBER/RED after handling (audit trail)
python3 bakcheck.py accept "app-{date}.tar.gz" amber --note "manually verified, untars clean"

# 5) In cron: JSON + exit code (0 green / 1 amber / 2 red)
python3 bakcheck.py scan /var/backups --json; echo $?
```

## Verdict rules

| Level | Trigger |
|---|---|
| RED | stale beyond SLA / zero bytes / integrity probe failure / size collapse / no backups at all |
| AMBER | abnormal bloat / sampling gap / filename-date vs mtime mismatch |
| GREEN | all checks pass |
| SKIP | formats without a standard probe (.sql/.dump/.7z/.zst) get tail-reach + non-all-zero checks only, not graded |

## Four invariants

1. **Read-only** — scan/verdict never write a single byte into the backup target; all probes are list/verify mode
2. **No extrapolation on thin samples** — fewer than 3 history samples: hard checks only, and it says so
3. **No backups = top alarm** — an empty dir is RED, never a silent pass
4. **Every verdict leaves a trail** — JSONL events, accept stamps, complete audit chain

## Design boundaries (said up front)

* bakcheck verifies the artifact, **not a full restore drill** — for real DR, periodically restore one into a sandbox
* The size band needs ≥3 history samples; on cold start use `--min-bytes` as a manual floor
* Probes dispatch by extension: streaming formats fully decompress (`--probe-cap-mb` caps it, default 512MB); non-standard formats degrade to tail-reach checks

## Self-test

```bash
python3 bakcheck.py selftest   # 26/26 green (incl. skewed-distribution robustness & read-only invariants)
```

## LICENSE

MIT
