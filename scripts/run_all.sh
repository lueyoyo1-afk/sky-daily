#!/usr/bin/env bash
# 一键更新资讯（真实优先）：聚合国服复刻 + 真实每日任务(9game) + 新季节(ali213)
#   -> 更新 data.json -> 重新内联进 index.html（保证 file:// 双击打开也是最新全量数据）
set -e
cd "$(dirname "$0")/.."
echo "[$(date '+%F %T')] >>> 1/3 聚合国服资讯（复刻 + 真实每日任务 + 新季节）"
python3.11 scripts/fetch_data.py

# 如需用「运营上传的真实微博每日任务图」以 OCR 填充，取消下面两行注释（会覆盖真实抓取结果）：
# echo "[$(date '+%F %T')] >>> OCR 识别每日任务图 (input/ 目录)"
# python3.11 scripts/ocr_tasks.py

echo "[$(date '+%F %T')] >>> 2/3 内联全量数据进 index.html"
python3.11 scripts/build_inline.py

echo "[$(date '+%F %T')] >>> 3/3 完成，刷新页面即可看到更新"
