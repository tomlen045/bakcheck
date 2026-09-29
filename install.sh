#!/bin/sh
# bakcheck 安装脚本 —— 拉单文件到 ~/.local/bin（或当前目录）
set -e
DEST="${BAKCHECK_DEST:-$HOME/.local/bin}"
mkdir -p "$DEST"
BASE_URLS=(
  "https://gitee.com/tomlen/bakcheck/raw/main/bakcheck.py"
  "https://raw.githubusercontent.com/tomlen045/bakcheck/main/bakcheck.py"
  "https://cdn.jsdelivr.net/gh/tomlen045/bakcheck@main/bakcheck.py"
)
ok=""
for u in "${BASE_URLS[@]}"; do
  if curl -fsSL --max-time 30 "$u" -o "$DEST/bakcheck.py.tmp" 2>/dev/null; then
    # 404 页面伪装成功拦截：真脚本必有 argparse 主入口
    if grep -q "add_subparsers" "$DEST/bakcheck.py.tmp" && grep -q "备份哨兵" "$DEST/bakcheck.py.tmp"; then
      ok="$u"
      break
    fi
  fi
  rm -f "$DEST/bakcheck.py.tmp"
done
if [ -z "$ok" ]; then
  echo "✘ 三个镜像都拉取失败，请手动下载 bakcheck.py" >&2
  exit 1
fi
mv "$DEST/bakcheck.py.tmp" "$DEST/bakcheck.py"
chmod +x "$DEST/bakcheck.py"
echo "✔ 已装到 $DEST/bakcheck.py（来源: $ok）"
"$DEST/bakcheck.py" selftest | tail -2
echo "上手: bakcheck.py scan /path/to/backups"
