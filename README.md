# bakcheck

[中文](README.md) | [English](README_EN.md)

**备份哨兵** —— 「备份任务显示成功」是运维圈最大的谎言：任务退出码 0 ≠ 产物能恢复。
cronguard 盯任务跑没跑（[cronguard](https://github.com/tomlen045/cronguard)），capguard 盯磁盘还剩几天（[capguard](https://github.com/tomlen045/capguard)），**bakcheck 盯备份产物本身的死活**。

bakcheck 只认产物：新鲜度 / 非空 / 完整性探针 / 大小带 / 漏采间隙 / 恢复演练凭证。

[![tests](https://img.shields.io/badge/self--tests-26%2F26-green)]() [![deps](https://img.shields.io/badge/deps-zero-yellow)]() [![license](https://img.shields.io/badge/license-MIT-blue)]()

---

## 解决什么问题

* 备份任务天天「成功」，恢复时才发现 tar 是半截 → **流式完整性探针**：gzip/bz2/xz 全量解压到 EOF、tar 逐 member 走头、zip 全 member CRC、sqlite `quick_check`——截断和损坏当场现形
* 备份目录被悄悄清空/迁移，任务没报错 → **目录里一个备份都没有 = RED 最高级警报**，绝不静默通过
* 最新备份体积掉到平时的 1/3（脚本改错了/数据库连接断）→ **大小带**：中位数+MAD 自学历史区间，骤缩 RED / 膨胀 AMBER；历史样本 <3 明确输出「样本不足不外推」，绝不硬编
* 备份隔了 5 天没跑但没人发现 → **漏采间隙**：最大间隔超过中位间隔 2.5 倍就点名
* 文件名写着今天、实际是上周改名的旧文件 → **文件名日期与修改时间打架**检测（超 48 小时 AMBER）
* 复盘时说不清「当时谁知道」→ **每次判级追加 JSONL 事件**，`accept` 盖章留审计链；`verdict` 出**恢复演练凭证**（含产物 SHA256 指纹），可截图存档、随机抽查
* 想按更严的口径盯 → `--sla-hours` 自定义红线（默认 26 小时=日备+2h 宽限）

## 安装

```bash
# 方式一：一键脚本（Gitee → GitHub → jsDelivr 三镜像自动切换）
curl -fsSL https://gitee.com/tomlen/bakcheck/raw/main/install.sh | sh

# 方式二：直接拉单文件（仅标准库，Python 3.8+）
curl -fsSLO https://gitee.com/tomlen/bakcheck/raw/main/bakcheck.py
```

## 30 秒上手

```bash
# 1) 扫描备份目录（递归，按「备份族」= 去日期文件名分组判级）
python3 bakcheck.py scan /var/backups /data/db-dumps

# 2) 严一点：4 小时 SLA（每 2 小时一备的库）
python3 bakcheck.py scan /var/backups --sla-hours 4

# 3) 对某份备份出「恢复演练凭证」（可截图贴到值班记录里）
python3 bakcheck.py verdict /var/backups/app-20260929.tar.gz

# 4) AMBER/RED 处理完盖章留痕（审计链）
python3 bakcheck.py accept "app-{date}.tar.gz" amber --note "已人工核对可解压"

# 5) cron 里用 JSON + 退出码（0绿/1琥珀/2红）
python3 bakcheck.py scan /var/backups --json; echo $?
```

## 判级规则

| 级别 | 触发 |
|---|---|
| RED | 超 SLA 未更新 / 零字节 / 完整性探针失败 / 体积骤缩 / 目录无任何备份 |
| AMBER | 体积异常膨胀 / 漏采间隙 / 文件名日期与修改时间打架 |
| GREEN | 全项通过 |
| SKIP | 无标准探针的格式（.sql/.dump/.7z/.zst）只做尾部可达+非全零检查，不参与判级 |

## 四不变量

1. **只读铁律** —— scan/verdict 绝不写备份目标一个字节，探针全部用列表/校验模式
2. **样本不足不外推** —— 历史 <3 份只做硬检查，明说「跳过趋势判断」
3. **无备份=最高级警报** —— 空目录是 RED，不是静默通过
4. **判级必留痕** —— 每次判级追加 JSONL，accept 盖章，审计链完整

## 设计边界（说在前面）

* bakcheck 验「产物可用」，**不等于完整恢复演练**——真恢复请定期抽一份到沙箱还原库
* 大小带自学需要 ≥3 份历史；冷启动期可 `--min-bytes` 手动兜底
* 完整性探针按扩展名分发：流式格式全量解压（`--probe-cap-mb` 限上限，默认 512MB），非标准格式降级为尾部可达检查

## 自测

```bash
python3 bakcheck.py selftest   # 26/26 绿（含偏态分布鲁棒与只读铁律验证）
```

## LICENSE

MIT
