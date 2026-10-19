"""工作台服务冒烟测试（v2）：静态页、退役接口 404、legacy 导出、v2 状态。

旧 /api/state、/api/calc、/api/assistant_params 行为测试已随接口退役删除（G18），
v2 业务链路的覆盖在 tests/test_v2_http.py。
"""

import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from target_forecast import server  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def base_url():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(ROOT))
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def _get(url):
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_static_pages(base_url):
    status, html = _get(base_url + "/")
    assert status == 200
    text = html.decode()
    assert "经营目标测算" in text and "api.js" in text and "app.js" in text
    for asset in ("/style.css", "/app.js", "/api.js"):
        status, body = _get(base_url + asset)
        assert status == 200 and len(body) > 1000, asset


def test_retired_endpoints_404_with_pointer(base_url):
    for path in ("/api/state", "/api/assistant_params"):
        status, body = _get(base_url + path)
        assert status == 404, path
        data = json.loads(body)
        assert data["code"] == "retired" and "/api/v2/" in data["use"]
    req = urllib.request.Request(base_url + "/api/calc", data=b"{}",
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            status, body = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, body = e.code, e.read()
    assert status == 404
    assert json.loads(body)["code"] == "retired"


def test_v2_state_api(base_url):
    status, body = _get(base_url + "/api/v2/state")
    data = json.loads(body)
    assert status == 200
    assert data["engine_version"].startswith("forecast-engine-")
    assert "plans" in data and "runs" in data


def test_legacy_export_listing_and_download(base_url, tmp_path_factory):
    """旧版产物：只读清单 + 下载；不存在的产物 404。"""
    status, body = _get(base_url + "/api/v2/legacy-artifacts")
    assert status == 200
    artifacts = json.loads(body)["artifacts"]
    assert isinstance(artifacts, list)
    status, body = _get(base_url + "/api/v2/legacy-artifacts/%E4%B8%8D%E5%AD%98%E5%9C%A8.xlsx")
    assert status == 404
    # 旧接口形态的报表下载：文件不存在时 404（本仓库 output 为空时）
    status, body = _get(base_url + "/api/export/report")
    assert status in (200, 404)  # 取决于本机是否有旧产物；两种都合法
    if status == 404:
        assert "error" in json.loads(body)
