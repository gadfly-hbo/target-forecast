# REVIEW 发现（Path A 迁移，2026-10-15，fresh-context 子代理×2）

## 首审：FAIL（1 blocking）→ 修复 64ba6dc → 复审：PASS

- **B1（blocking，已修复）**：PiSidecarBackend.chat 未解析 orchestrated——真实路径落回旧循环：sidecar 已执行的读被再执行、已登记的写被再登记（红队 K3 预警的双登记；确认门未弱化但 _relay_orchestrated 成死码）。修复：完整透传 tool_calls 字段 + orchestrated 解析 + 真 HTTP 解析缝回归测试。复审确认：backend 修复/测试/25 passed/无夹带 全过。
- **N1（non-blocking，记录不修）**：_relay_orchestrated 只透传 staged[0]——多写 run 的后续 _pending 项不可确认且无 dropped 提示（_stage_write 有）。PRD 单写范围 + 单 pending 确认门设计下可接受；多写支持留后续。
- **N2（已修）**：README/backend docstring 过期 pi-ai 描述（复审发现 README:69 残留，已补修）。
- 九项猎杀全净：无 pi-ai 直接 import（lockfile 为传递依赖）、确认门四层核验、五键 limits、140s<150s、启动轮转、凭据未入库、taskId 工具集派生（标准认可）、范围合规、file: 锁定。

## 冒烟期现场问题（已修，记录）

- 远古僵尸服务器（13:10 起）占 8399 → 首冒烟工具 404 → 清理后正常；后续注意 kill %1 在新 shell 无效。
- taskId 未随工具集派生 → 同 store CONFIGURATION_CHANGED → 已按定义摘要派生。
