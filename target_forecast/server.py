"""本地 HTML 工作台：静态页 + JSON API。

只用标准库 http.server，无新增依赖；数据与测算全部在本机完成。
v2（当前）：GET / 为整页方案工作区（static/v2/），业务 API 在 /api/v2/*（见 v2http.py）。
已退役（404 JSON，code=retired）：/api/state、/api/calc、/api/assistant_params
——固定 workspace 测算与助手直写参数已重构为方案工作区 + AI 提案双轨（G2）。
保留的旧路径：/api/export/*（旧版产物只读下载，界面标注未关联新运行）。
"""

from __future__ import annotations

import re
import urllib.parse
from pathlib import Path

import yaml

from tools_common.httpkit import Responder, make_dispatch_handler, serve_quiet

from . import v2http

STATIC_DIR = Path(__file__).resolve().parent / "static"
V2_STATIC = STATIC_DIR / "v2"


def load_cfg(root: Path) -> dict:
    with open(root / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _retired(r: Responder, use: str) -> None:
    r.json({"error": "旧版接口已退役（固定 workspace 测算已重构为方案工作区）",
            "code": "retired", "use": use}, 404)


def make_routes(root: Path):
    """forecast 工具完整路由（壳内 /t/forecast/ 与 standalone 共用同一组）。

    v2：/ 与 /style.css /app.js /api.js → static/v2/；/api/v2/* → v2http。
    退役：/api/state、/api/calc、/api/assistant_params → 404 JSON（code=retired）。
    保留：/api/export/*（旧版产物只读下载，界面标注未关联新运行）。
    """
    root = Path(root).resolve()
    load_cfg(root)  # 启动即校验 config

    def handle_get(h, path: str) -> bool:
        if v2http.route_get(root, h, path):
            return True
        p = path.split("?")[0]
        r = Responder(h, V2_STATIC)
        try:
            if p in ("/", "/index.html"):
                r.static("index.html")
            elif p in ("/style.css", "/app.js", "/api.js"):
                r.static(p.lstrip("/"))
            elif p == "/api/state":
                _retired(r, "/api/v2/state")
            elif p == "/api/assistant_params":
                _retired(r, "/api/v2/plans（AI 改为提案双轨，不再直写参数）")
            elif p == "/api/export/report":
                f = root / "workspace" / "forecast" / "output" / "目标测算报告.xlsx"
                if not f.is_file():
                    r.json({"error": "报表不存在：先运行 main.py run 生成"}, 404)
                else:
                    r.send(200, f.read_bytes(),
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            elif m := re.fullmatch(r"/api/export/metrics/([^/?]+)(\?.*)?", p):
                platform = urllib.parse.unquote(m.group(1))
                if "/" in platform or "\\" in platform or ".." in platform:
                    r.json({"error": "非法平台名"}, 404)
                    return True
                f = (root / "workspace" / "forecast" / "output" / "中间指标"
                     / f"月度指标_{platform}.csv")
                if not f.is_file():
                    r.json({"error": f"中间指标不存在：{platform}（先运行 main.py run 生成）"}, 404)
                else:
                    r.send(200, f.read_bytes(), "text/csv; charset=utf-8")
            else:
                return False
        except Exception as e:  # noqa: BLE001 —— 本地工作台把错误如实回给页面
            r.json({"error": f"{type(e).__name__}: {e}"}, 500)
        return True

    def handle_post(h, path: str) -> bool:
        if v2http.route_post(root, h, path):
            return True
        p = path.split("?")[0]
        r = Responder(h, V2_STATIC)
        try:
            if p == "/api/calc":
                _retired(r, "/api/v2/plans")
            elif p == "/api/assistant_params":
                _retired(r, "/api/v2/plans（AI 改为提案双轨，不再直写参数）")
            else:
                return False
        except Exception as e:  # noqa: BLE001
            r.json({"error": f"{type(e).__name__}: {e}"}, 500)
        return True

    return handle_get, handle_post


def make_handler(root: Path):
    handle_get, handle_post = make_routes(root)
    return make_dispatch_handler(handle_get, handle_post)


def serve(root: Path, port: int = 8300) -> None:
    load_cfg(root)  # 启动即校验 config，失败早暴露
    serve_quiet(make_handler(root), port,
                f"目标测算工作台已启动 → http://127.0.0.1:{port}  （Ctrl+C 退出；数据不出本机）")
