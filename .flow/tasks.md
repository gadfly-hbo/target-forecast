# Tasks — 测算工作台整合 P0

规格源：`.flow/prd.md`（含 GRILL 决议 G1-G7）> 本拆解。验收基线：`.venv/bin/python -m pytest tests -q` 存量断言零修改全绿。

- [x] 1. workbench 壳骨架 + 插件协议
- [x] 2. coupon 插件化（首个真实工具端到端）
- [x] 3. forecast 插件化
- [x] 4. 壳导航前端完成（侧边栏 + iframe + 深链）
- [x] 5. 启动脚本整合 + README

---

## 1. workbench 壳骨架 + 插件协议

**What to build:** 新增 `workbench/` 包：插件协议（manifest：id/name/icon/static_dir/seed_demo/actions=[] + handle_get/handle_post 路由函数，path 已剥离前缀）与显式注册表；壳 server（标准库 ThreadingHTTPServer）：`/` 壳页面、`/api/state` 工具清单、`/t/{id}/` 前缀分发（页面 + API，未知 id → 404）；`python -m workbench serve --port N` CLI。带一个仓库内最小示例插件（hello）验证协议，不作为正式工具出现在导航。

**Acceptance criteria:**
- [ ] `GET /api/state` 返回注册工具清单（id/name/icon），示例插件在列
- [ ] `GET /t/hello/` 页面与 `GET /t/hello/api/ping` API 正常分发，未知工具 404
- [ ] 壳上下文构造显式接收仓库根绝对路径（无 cwd 依赖）
- [ ] tests/test_workbench.py 覆盖以上（起随机端口真实 server，沿用现有 server 冒烟测试模式）

**Blocked by:** None - can start immediately

## 2. coupon 插件化（首个真实工具端到端）

**What to build:** `coupon_tool/plugin.py` 暴露 TOOL manifest 与路由函数；`coupon_tool/server.py` 的路由匹配逻辑提取复用（do_GET/do_POST 调同一函数，独立 server 行为不变——单一事实源）；前端 API 调用全部改相对路径（api() 帮助函数 + 8 处导出 `<a href>`）；静态不变量测试（禁止根绝对 `"/api` 引用）；壳注册 coupon，壳内 `/t/coupon/` 端到端（state + 一次真实 compare 调用）。

**Acceptance criteria:**
- [ ] 存量测试零断言修改全绿（含 test_coupon_server.py 独立入口冒烟）
- [ ] 壳内 `GET /t/coupon/api/state` 200 且与独立运行 `/api/state` 结构一致
- [ ] 壳内 `POST /t/coupon/api/compare` 对演示场景返回合法结果
- [ ] 静态扫描断言 coupon_tool/static/*.js 无根绝对 `"/api` 引用

**Blocked by:** 1

## 3. forecast 插件化

**What to build:** 与切片 2 同构：`target_forecast/plugin.py` + server.py 路由提取复用 + 3 处 fetch 改相对路径；壳注册 forecast，壳内 `/t/forecast/` 端到端（state + POST calc 一次真实测算）。

**Acceptance criteria:**
- [ ] 存量测试零断言修改全绿（含 test_server.py）
- [ ] 壳内 `GET /t/forecast/api/state` 200 且与独立运行结构一致
- [ ] 壳内 `POST /t/forecast/api/calc` 返回三视角 + 全渠道汇总
- [ ] 静态扫描断言 target_forecast/static/*.js 无根绝对 `"/api` 引用

**Blocked by:** 1（与 2 相互独立，顺序按 2→3 执行）

## 4. 壳导航前端完成

**What to build:** 壳页面定稿：窄侧边栏（产品名「测算工作台」+ 工具导航 icon+name + 底部本机运行声明）+ 内容区单 iframe；导航切换只改 iframe src；`?tool={id}` 深链设置初始页与高亮。视觉 token 取全局 `~/.zcode/design/DESIGN.md` 基线（实现前读取）。移除示例 hello 插件出导航（或彻底移除）。

**Acceptance criteria:**
- [ ] 壳页含两工具导航项，`?tool=coupon` 初始加载对应 iframe
- [ ] 壳视觉与全局设计基线 token 一致（配色/密度）
- [ ] 工具 iframe 内交互（导出下载、调参重算）不受壳影响
- [ ] tests/test_workbench.py 增补导航/深链相关断言

**Blocked by:** 2, 3

## 5. 启动脚本整合 + README

**What to build:** 新增 `启动测算工作台.command`（默认 8300，占用自动换端口，模式复用现有脚本）；两个旧 .command 薄壳化——壳在 8300 运行则 `open` 对应 `/t/{id}/?tool=…` 页，未运行则起壳（输出[已整合]提示）后打开对应页；README 更新整合架构与启动方式。

**Acceptance criteria:**
- [ ] 双击新脚本起壳并打开工作台根页
- [ ] 旧脚本在壳运行时只打开浏览器不重复起服务；未运行时起壳并打开对应工具页
- [ ] README 反映单入口 + 插件协议 + 旧入口兼容说明

**Blocked by:** 4
