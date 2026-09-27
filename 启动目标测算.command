#!/bin/bash
# 兼容入口:目标测算已整合进「测算工作台」,本脚本启动同一壳服务并直达目标测算页。
# 流程:壳服务已在运行 → 只打开浏览器;未运行 → 起壳服务后打开 /?tool=forecast。
set -e
cd "$(dirname "$0")"

PORT="${PORT:-8300}"
URL="http://127.0.0.1:$PORT"

if curl -sf -o /dev/null --max-time 1 "$URL/api/state"; then
  echo "[已在运行] 打开目标测算…"
  open "$URL/?tool=forecast"
  exit 0
fi

if [ ! -x .venv/bin/python ]; then
  echo "[首次运行] 创建虚拟环境并安装依赖…"
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
fi

# 数据布局收编（P1）：旧 data/ coupon_data/ output/ 无损迁移到 workspace/（幂等，冲突跳过不覆盖）
if [ -d data ] || [ -d coupon_data ] || [ -d output ]; then
  echo "[迁移] 收编存量数据到 workspace/ …"
  .venv/bin/python -m workbench migrate || echo "[警告] 迁移未完成（见上方错误），服务仍启动；可手动运行: .venv/bin/python -m workbench migrate"
fi

# 端口被其他进程占用时自动换空闲端口
if ! .venv/bin/python -c "import socket; s=socket.socket(); s.bind(('127.0.0.1',$PORT))" 2>/dev/null; then
  echo "[端口] $PORT 已被其他进程占用,自动更换…"
  PORT=$(.venv/bin/python -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')
  URL="http://127.0.0.1:$PORT"
fi

echo "[提示] 目标测算已整合进测算工作台(左侧导航可切换其他工具)"
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
open "$URL/?tool=forecast"

wait "$SERVER_PID"
