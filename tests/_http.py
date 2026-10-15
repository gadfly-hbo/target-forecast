# -*- coding: utf-8 -*-
"""共享 HTTP 测试助手（阶段5 C1）。

三种 GET 语义刻意分开（红队实测地图）：
- get_raw：返回 bytes，HTTPError 抛出（被 404 的 pytest.raises 测试依赖）
- get_json：返回 parsed JSON，HTTPError 抛出
- get_json_or_error：返回 parsed JSON，HTTPError 捕获为 (code, body)

POST 家族共享响应处理：post(JSON 体) / post_raw(bytes 体，畸形 body 门禁用）。
"""
import json
import urllib.error
import urllib.request


def post(url, obj, timeout=60):
    req = urllib.request.Request(url, data=json.dumps(obj).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def post_raw(url, data: bytes, timeout=60):
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def get_raw(url, timeout=30):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.status, r.read()


def get_json(url, timeout=30):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.status, json.loads(r.read())


def get_json_or_error(url, timeout=30):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())
