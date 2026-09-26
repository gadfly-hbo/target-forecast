#!/bin/bash
# 一键启动优惠券测算工作台（模式参考 deep-research/启动深度研究.command）
# 流程：首次运行自动建 venv 装依赖 → 数据为空时播种合成演示场景 → 起本机服务 → 打开浏览器。
# 退出：窗口内 Ctrl+C；已在运行时重复双击只聚焦浏览器，不重复起服务。
set -e
cd "$(dirname "$0")"

PORT=8310
URL="http://127.0.0.1:${PORT}"

echo "== 优惠券测算工作台 =="

# 已在运行：直接打开浏览器退出，不重复起服务
if curl -s -o /dev/null "${URL}/api/state"; then
  echo "[已在运行] ${URL}"
  open "${URL}"
  exit 0
fi

if [ ! -x .venv/bin/python ]; then
  echo "[首次运行] 创建虚拟环境并安装依赖…"
  python3 -m venv .venv
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install -q -r requirements.txt
fi

# 数据目录为空时播种演示场景（合成假设，非真实经营数据；真实数据可在工作台导入）
if [ -z "$(ls -A coupon_data/scenarios 2>/dev/null)" ]; then
  echo "[初始化] 写入合成演示场景（参数为合成假设，非行业真值）…"
  .venv/bin/python - <<'PY'
from coupon_tool import build_synthetic_spec
from coupon_tool.storage import Store

Store("coupon_data").save_spec(build_synthetic_spec())
PY
fi

cleanup() {
  kill "$SERVER_PID" 2>/dev/null || true
}
trap cleanup EXIT

echo "[启动] 本机服务 ${URL} (Ctrl+C 退出)"
.venv/bin/python -m coupon_tool serve --port "$PORT" &
SERVER_PID=$!

for _ in $(seq 1 30); do
  if curl -s -o /dev/null "${URL}/api/state"; then break; fi
  sleep 1
done
open "${URL}"

wait "$SERVER_PID"
