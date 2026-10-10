#!/usr/bin/env bash
# 光遇每日资讯 —— 手动一键更新
#   1) 抓每日任务 / 大蜡烛 / 季蜡 / 复刻   -> data.json
#   2) 自动发现新活动 / 联动 / 新季节       -> events.json + data.json
#   3) 有变化才把全量数据内联进 index.html
# 想让它每天 00:00 自动跑：bash scripts/install_cron.sh
set -u
cd "$(dirname "$0")/.."
LOG_DIR="$PWD/logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/update-$(date '+%Y%m%d').log"
PY="$(command -v python3.11 || command -v python3)"
FORCE=""; [ "${1:-}" = "--force" ] && FORCE="--force"

{
  echo "=============== $(date '+%F %T') 开始更新 ==============="
  if [ "$FORCE" = "--force" ]; then
    $PY scripts/fetch_data.py
    $PY scripts/discover_events.py
    $PY scripts/build_inline.py
  else
    # 已是今天的数据就只做增量巡检，有变化才重建内联
    $PY scripts/autopilot.py --once
  fi
  echo "=============== $(date '+%F %T') 更新完成 ==============="
} >> "$LOG" 2>&1

echo "已写入日志: $LOG"
tail -n 16 "$LOG"
