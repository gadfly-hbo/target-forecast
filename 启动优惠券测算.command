#!/bin/bash
# 兼容入口:优惠券测算已整合进「测算工作台」,本脚本启动同一壳服务并直达优惠券测算页。
# 流程:壳服务已在运行 → 只打开浏览器;未运行 → 起壳服务后打开 /?tool=coupon。
set -e
cd "$(dirname "$0")"

PORT="${PORT:-8300}"
URL="http://127.0.0.1:$PORT"

if curl -sf -o /dev/null --max-time 1 "$URL/api/state"; then
  echo "[已在运行] 打开优惠券测算…"
  open "$URL/?tool=coupon"
  exit 0
fi

if [ ! -x .venv/bin/python ]; then
  echo "[首次运行] 创建虚拟环境并安装依赖…"
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
fi

# 端口被其他进程占用时自动换空闲端口
if ! .venv/bin/python -c "import socket; s=socket.socket(); s.bind(('127.0.0.1',$PORT))" 2>/dev/null; then
  echo "[端口] $PORT 已被其他进程占用,自动更换…"
  PORT=$(.venv/bin/python -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')
  URL="http://127.0.0.1:$PORT"
fi

echo "[提示] 优惠券测算已整合进测算工作台(左侧导航可切换其他工具)"
cleanup() {
  kill "$SERVER_PID" 2>/dev/null || true
}
trap cleanup EXIT

.venv/bin/python -m workbench serve --port "$PORT" &
SERVER_PID=$!

for i in $(seq 1 40); do
  if curl -sf -o /dev/null "$URL/api/state"; then break; fi
  sleep 1
done
open "$URL/?tool=coupon"

wait "$SERVER_PID"
