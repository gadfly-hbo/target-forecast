#!/bin/bash
# 一键启动目标测算工作台(双端通用:macmini / MacBook)
# 流程:准备虚拟环境 → 起本机服务 → 打开浏览器。data/ 为空时自动生成演示数据。
# 双机同步:代码与配置随仓库走 git——变动端 git-commit-push 到 GitHub,另一端手动触发 git-pull-sync 拉取(拉取前先停本服务);data/ 数据不入库,两端各自维护。
set -e
cd "$(dirname "$0")"

echo "== 目标测算工作台 =="
if [ ! -d .venv ]; then
  echo "[首次运行] 创建虚拟环境并安装依赖…"
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
fi

# 端口:默认 8300,被占用时自动换空闲端口(可用 PORT=xxxx 覆盖)
PORT="${PORT:-8300}"
if curl -s -o /dev/null --max-time 1 "http://127.0.0.1:$PORT/api/state"; then
  echo "[端口] $PORT 已被占用,自动更换…"
  PORT=$(.venv/bin/python -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')
fi

cleanup() {
  kill "$SERVER_PID" 2>/dev/null || true
}
trap cleanup EXIT
trap 'echo "[错误] 启动失败,请把上方报错截图反馈"; read -r _' ERR

echo "[启动] 本机服务 http://127.0.0.1:$PORT (Ctrl+C 退出)"
.venv/bin/python main.py serve --port "$PORT" &
SERVER_PID=$!

for i in $(seq 1 40); do
  if curl -s -o /dev/null "http://127.0.0.1:$PORT/api/state"; then break; fi
  sleep 1
done
open "http://127.0.0.1:$PORT"

wait "$SERVER_PID"
