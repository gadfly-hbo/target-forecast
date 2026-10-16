# 任务清单：Path A 助手全托管迁移 pi-agent-runtime

> 来源：`.flow/prd.md`（含红队 4 先决 + GRILL 6 决议）。无 issue tracker。

- [x] 1. 阻塞前置 — 证据：imports ok + 55 passed（serve 顺序=先探端口→sidecar(shell_url)→build_service→httpd）
- [x] 2. Python 侧 — 证据：c6f2985，imports ok
- [x] 3. pytest 先行 — 证据：57 passed in 49.45s（防回归 2 条新增，既有 55 零改动）
- [x] 4. sidecar 重写 — 证据：72268b1 构建/合成绿
- [x] 5. 合成套件 — 证据：6/6 pass（读代理/写stage/502×2/503/拍平）
- [x] 6. 构建启动链 — 证据：npm install/build 过、/health 含 sdk 字段、PiSidecarBackend 探测、僵尸清理后 boot 正常
- [x] 7. 真实冒烟 — 证据：读问多工具循环+中文摘要回流；写提案→stage→pending重建→确认→执行→落盘（净贡献31776.00元）；audit 48 事件；写后现场恢复（c48dd42）
- [x] 8. 全量回归 — 证据：233 passed in 108.40s（223+10 新：防回归2+合成外http补丁）

## 每片验收要点

1. **任务1**：`maybe_start_sidecar(root, shell_url)`；serve() 先 httpd 后 sidecar；`test_workbench.py` 既有 serve_background 路径不破（它不启 sidecar）。
2. **任务2**：两新端点挂 workbench/server.py（POST only；名门禁 `_by_name[name]["x-write"]`）；ChatResult 加 `orchestrated: bool = False`；service.py orchestrated 分支不进 `_execute`/`_stage_write` 循环、重建 pending_confirmation。
3. **任务3**：`tests/test_assistant_service.py` 追加防回归（stub orchestrated=True）；既有测试**零改动**全绿。
4. **任务4**：依赖 `file:../../pi-agent-runtime`（0.4.3）；共享 store/taskId `workbench-assistant`/cumulative unlimited 五元组/140s signal/模块级串行队列/启动轮转 5MiB；x-write 映射 effect；system 并入 prompt 首段；工具定义从 manifest 字节稳定生成；503 文案与降级链保持。
5. **任务5**：读循环、写 stage 不执行、Authorization 拒绝→blocked→502 映射、无 key 503、响应契约（orchestrated+summary）——`node --test`（package.json scripts.test）。
6. **任务6**：`npm install && npm run build`；boot /health 含 provider/model；临时删 assistant.env 验证 503+降级（Echo 仍绿）。
7. **任务7**：`python -m workbench serve`（真 key）→ 前端或 curl 一问读工具 + 一写提案→确认→执行→落盘断言；有界（≤6 次模型调用）。
8. **任务8**：全量 `pytest`（223+新增）；`test_engine_fingerprint` 等门禁绿；REVIEW 用 fresh-context 子代理。

## Blocked by

1→2→3（Python 链）；4 依赖 1（shell URL）与 2（端点）；5 依赖 4；6 依赖 4/5；7 依赖 6；8 收尾。
