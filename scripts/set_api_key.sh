#!/usr/bin/env bash
# 保存第三方光遇 API 的密钥
#   用法: bash scripts/set_api_key.sh 你的KEY
# KEY 免费申请: https://api.t1qq.com 注册 -> https://api.t1qq.com/user/key
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
KEY="${1:-}"
if [ -z "$KEY" ]; then
  read -rp "请粘贴你的 KEY: " KEY
fi
if [ -z "$KEY" ]; then
  echo "✗ KEY 不能为空"; exit 1
fi
mkdir -p "$ROOT/config"
cat > "$ROOT/config/api.env" <<EOF
# 光遇国服第三方数据接口密钥
# 免费申请： https://api.t1qq.com  注册后到 https://api.t1qq.com/user/key 复制
# 这个文件只保存在本机，不要外传；也不要提交到公开仓库。
SKY_API_KEY=$KEY
EOF
chmod 600 "$ROOT/config/api.env"
echo "✓ 已保存到 $ROOT/config/api.env（权限 600）"
echo
echo "下一步，跑自检看看通不通："
echo "  python3.11 scripts/check_api.py"
