# 切片 6 兼容路径手工走查记录（2026-10-19）

环境：standalone `main.py serve --port 8399`（真实 Chrome via playwright-cli）；方案 `plan-20261019-074a9f`（合成示例数据）。
走查项与结论如下，浏览器证据见对话记录与 `workspace/forecast/acceptance-smoke/playwright-raw/` 快照；下载核对物在 `workspace/forecast/acceptance-smoke/`。

## 1. assistant_params.json 差异预览 → 确认并入（未知字段列明）

- 夹具：手写 `workspace/forecast/assistant_params.json`：
  `{"scenarios": {"基准": {"new_customers_growth": 0.22}, "挑战": {"unknown_param": 1}}}`
- 预览（假设与情景页自动出现「旧版助手参数」区）：
  - 差异表 1 行：基准 / new_customers_growth / 旧 0.1 / 并入 0.22 ✓
  - 未知字段列明且不并入：`挑战.unknown_param（未知字段）` ✓
- 点击「确认并入工作稿」→ toast「已并入 1 项旧参数；假设确认已失效，请重新确认后计算」✓
- 落盘核对（GET /api/v2/plans/<id>）：
  - revision 3 → 4（走唯一更新入口，changes[0] = import「并入旧版助手参数（1 项差异）」）✓
  - `scenarios.基准.params.new_customers_growth == 0.22` ✓
  - `unknown_param` 未落盘 ✓
  - 其他情景未被覆盖（挑战 0.18 保留）✓
  - 假设确认 derived 失效（assumptions.confirmed = false）✓
- 同值项不产生差异、无差异时并入为 no-op（pytest test_compat_paths 覆盖）✓
- 走查后删除夹具文件（真实工作区不保留走查垃圾）。

## 2. 「从现有配置创建」

- 首页入口按钮存在（entry-links 区「从现有配置创建」）✓
- 服务端行为（pytest test_from_config_create_freezes_provenance）：
  provenance = {source: config.yaml, hash: 冻结哈希}；参数取 config 值；
  changes[0] 标注「从现有配置导入参数」✓
- 目标与范围页展示「参数来源：config.yaml@<hash 前缀>（创建时冻结；此后以工作稿为准）」✓

## 3. 从工作区目录导入

- 导入弹窗「从工作区目录选择」列出 workspace/forecast/orders|metrics 文件，来源冲突（同平台明细/月度双文件）显示警告并要求只选一种 ✓
- 源文件复制进快照 `source/` 目录、原目录零移动/零删除/零改动（sha256 前后一致，pytest test_workspace_import_copies_sources_and_keeps_directory）✓

## 4. 旧版产物

- 保存与导出页「旧版产物」区列出 workspace/forecast/output 下文件可下载 ✓
- 标注「旧版产物来自重构前的固定输出目录，未关联新运行，不携带输入快照与版本链」；清单条目无 run_id/version 字段（不伪造版本链，pytest test_legacy_artifacts_listed_not_linked_to_runs）✓

## 5. A15 扫描（未接入能力无假成功展示）——见 acceptance-map.md A15 行
