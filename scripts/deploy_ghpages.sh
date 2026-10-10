#!/usr/bin/env bash
# 一键部署到 GitHub Pages（首次创建 + 后续重推均可用）
#
# 前置：
#   1) gh 已登录：gh auth login（或设置 GH_TOKEN 环境变量）
#   2) 本地 config/api.env 存有 SKY_API_KEY（不会入库，仅灌进仓库 secret）
#
# 用法：
#   bash scripts/deploy_ghpages.sh [仓库名] [--private]
#   仓库名默认 sky-daily
set -eu
cd "$(dirname "$0")/.."

REPO="${1:-sky-daily}"
PRIVATE=""
[[ "${2:-}" == "--private" ]] && PRIVATE="--private"

echo "→ 目标仓库：$REPO"

# 当前 GitHub 账号
OWNER="$(gh api user --jq .login 2>/dev/null || echo "")"
if [ -z "$OWNER" ]; then
  echo "✗ 无法获取 GitHub 用户名，请先 gh auth login"; exit 1
fi
echo "  · 账号：$OWNER"

# 1) 确保远程仓库存在
if ! gh repo view "$OWNER/$REPO" >/dev/null 2>&1; then
  echo "  · 仓库不存在，创建中…"
  gh repo create "$REPO" $PRIVATE --source=. --remote=origin --push
else
  echo "  · 仓库已存在"
  git remote get-url origin >/dev/null 2>&1 \
    || git remote add origin "https://github.com/$OWNER/$REPO.git"
fi

# 2) 灌入 SKY_API_KEY 仓库 secret（从本地 config/api.env 读，绝不写进仓库）
if [ -f config/api.env ]; then
  KEY="$(grep '^SKY_API_KEY=' config/api.env | head -1 | cut -d= -f2- | tr -d '\"'\''')"
  if [ -n "$KEY" ]; then
    echo "  · 写入 secret SKY_API_KEY"
    printf '%s' "$KEY" | gh secret set SKY_API_KEY --repo "$OWNER/$REPO"
  else
    echo "  · config/api.env 未找到 SKY_API_KEY，跳过（接口将不可用，文章兜底）"
  fi
else
  echo "  · 无 config/api.env，跳过 secret（接口将不可用，文章兜底）"
fi

# 3) Pages 源设为 GitHub Actions（首次创建，已存在则更新）
echo "  · 配置 Pages 源 = workflow"
gh api "repos/$OWNER/$REPO/pages" -X POST -f build_type=workflow 2>/dev/null \
  || gh api "repos/$OWNER/$REPO/pages" -X PUT -f build_type=workflow >/dev/null 2>&1 \
  || true

# 4) 推送代码（触发工作流 → 自动构建部署）
echo "  · 推送代码…"
git push -u origin HEAD

# 5) 触发一次手动部署（不等定时）
echo "  · 触发工作流…"
gh workflow run deploy.yml --repo "$OWNER/$REPO" 2>/dev/null || true

echo
echo "✓ 完成。几分钟后可访问：https://$OWNER.github.io/$REPO/"
echo "  查看部署进度：gh run watch --repo $OWNER/$REPO"
