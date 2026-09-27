#!/bin/bash
# 一键启动测算工作台（双端通用:macmini / MacBook）
# 流程:准备虚拟环境 → 起壳服务(单端口,承载全部测算工具) → 打开浏览器。
# 双机同步:代码与配置随仓库走 git——变动端 git-commit-push 到 GitHub,另一端手动触发 git-pull-sync 拉取(拉取前先停本服务);data/ 与 coupon_data/ 数据不入库,两端各自维护。
set -e
cd "$(dirname "$0")"

echo "== 测算工作台 =="
PORT="${PORT:-8300}"

if [ ! -x .venv/bin/python ]; then
  echo "[首次运行] 创建虚拟环境并安装依赖…"
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
fi

# 已在运行:直接打开,不重复起服务
if curl -sf -o /dev/null --max-time 1 "http://127.0.0.1:$PORT/api/state"; then
  echo "[已在运行] http://127.0.0.1:$PORT"
  open "http://127.0.0.1:$PORT"
  exit 0
fi

# 数据布局收编（P1）：旧 data/ coupon_data/ output/ 无损迁移到 workspace/（幂等，冲突跳过不覆盖）
if [ -d data ] || [ -d coupon_data ] || [ -d output ]; then
  echo "[迁移] 收编存量数据到 workspace/ …"
  .venv/bin/python -m workbench migrate || echo "[警告] 迁移未完成（见上方错误），服务仍启动；可手动运行: .venv/bin/python -m workbench migrate"
fi

# 端口被其他进程占用时自动换空闲端口(可用 PORT=xxxx 覆盖)
if ! .venv/bin/python -c "import socket; s=socket.socket(); s.bind(('127.0.0.1',$PORT))" 2>/dev/null; then
  echo "[端口] $PORT 已被其他进程占用,自动更换…"
  PORT=$(.venv/bin/python -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')
fi

cleanup() {
  kill "$SERVER_PID" 2>/dev/null || true
}
trap cleanup EXIT

echo "[启动] 本机服务 http://127.0.0.1:$PORT (Ctrl+C 退出)"
.venv/bin/python -m workbench serve --port "$PORT" &
SERVER_PID=$!

for i in $(seq 1 40); do
  if curl -sf -o /dev/null "http://127.0.0.1:$PORT/api/state"; then break; fi
  sleep 1
done
open "http://127.0.0.1:$PORT"

wait "$SERVER_PID"
