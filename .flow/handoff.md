# 交接卡：(c)-resume 检查点重放（完成于 2026-10-16）——Path A 遗留全部清零

## 已完成

- 四提交（3fcabd4→d525b6e→6d87e4b→16d0235，均推 origin/main）：
  1. sidecar：写工具授权拒绝→blocked 200 + 检查点 stash（A1 覆盖语义：第一份 ready(pending)，跳过 tool-admitted/toolFailed；新铸 call_id；8 条 FIFO + 2MiB 守卫）+ /resume（A2 只认 call_id；R1 prompt:''；A4 与 /chat 字节一致；首写绑 exec_write 其余良性取消 A3；executed 标志）
  2. Python：exec_write 端点（名门禁 + call_id 在真实执行点一次性弹出）+ checkpoint_staged 透传建 pending（preview 由 _preview 生成，前端零改动）+ _confirm 双模三路分类（ok 透传/明确失败降级恰一次/maybe 不重执行/超时保留条目）
  3. 真实冒烟抓出并修复**双弹出真 bug**（合成测试盲区——exec_write 422 只有真链路暴露）
  4. REVIEW F2 修复（2xx 解析失败→maybe_executed）
- 红队实证（T1-T7，脚本 /tmp/rt-redteam/）：裁定提案原机制"必死"（tool-admitted 不可恢复）并给出可行路径——全部采纳
- 验证：pytest **241 passed**；node --test **12/12**；**真实 MIMO 完整恢复链通过**（audit 印证：blocked run 无 tool.finished、恢复 run 写 admitted+finished 于循环内、重放零模型调用、终稿一轮；落盘 cvr=0.06；终稿带完整上下文）
- 确认门语义零弱化（REVIEW 八项猎杀全净）；Echo 套件与前端零改动

## 架构现状（最终态）

写流程：提案→授权拒绝→blocked(200)+检查点→pending_confirmation（前端不变）→用户确认→/resume→SDK 免模型重放→exec_write 授权循环内执行→完整上下文终稿。降级链：stash 失效/明确失败→现行 Python 路径；executed:true→人工核对；超时→保留可重试。

## 遗留（non-blocking，已记录）

- F1：并发双确认窗口可双执行（UI 缓解+幂等写，如需加 in-flight 标记）
- F3：超时→重确认→降级重执行（若超时恢复服务端实际完成）——设计内接受
- /stage 端点与 toSdkTools 写分支成为不可达路径（保留兼容，可在后续清理批移除）

## 过程备注

- 红队子代理首次 429 中断后恢复完成（非降级）；真实冒烟再次证明其不可替代性（抓出合成盲区 bug）
- Path A 四项遗留至此全部清零
