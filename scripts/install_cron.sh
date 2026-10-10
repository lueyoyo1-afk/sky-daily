#!/usr/bin/env bash
# 安装定时任务：按光遇的 00:00 刷新节奏自动更新
#   用法: bash scripts/install_cron.sh
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$(command -v python3.11 || command -v python3)"

if [ -z "$PY" ]; then
  echo "✗ 找不到 python3.11 / python3"; exit 1
fi

run="$PY $ROOT/scripts/autopilot.py --once >> $ROOT/logs/cron.log 2>&1"

# 节奏说明：
#   00:05 起，每 20 分钟一次直到 12:00 —— 站方什么时候发文都能在 20 分钟内接住
#   白天每 2 小时一次 —— 抓临时公告、活动上新
#   @reboot —— 开机自动拉起常驻守护（它才是真正「过了 0 点就立刻抓」的那一位）
ENTRIES=(
  "5,25,45 0-11 * * * $run"
  "15 13,15,17,19,21,23 * * * $run"
  "@reboot sleep 30 && cd $ROOT && nohup $PY $ROOT/scripts/autopilot.py >> $ROOT/logs/cron.log 2>&1 &"
)

mkdir -p "$ROOT/logs"
TMP="$(mktemp)"
crontab -l 2>/dev/null | grep -v "scripts/autopilot.py" | grep -v "scripts/fetch_data.py" > "$TMP" || true
for e in "${ENTRIES[@]}"; do echo "$e" >> "$TMP"; done
crontab "$TMP"
rm -f "$TMP"

echo "✓ 已安装定时任务："
crontab -l | grep -E "autopilot|fetch_data" | sed 's/^/  /'
cat <<EOF

说明：
  · 00:05 起每 20 分钟一次（至 12:00），站方发文后平均 10 分钟内接住
  · 白天每 2 小时一次，用于抓活动上新 / 公告
  · 开机自动拉起常驻守护 autopilot.py —— 它会在跨到 00:00 的那一刻立刻抓取
  · 立即手动更新：  bash $ROOT/scripts/refresh.sh
  · 想长期常驻（推荐）： nohup $PY $ROOT/scripts/autopilot.py &
  · 卸载：            crontab -l | grep -v autopilot.py | crontab -
EOF
