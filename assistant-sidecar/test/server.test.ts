/**
 * Path A 合成套件：真 SDK runAgent 循环 + 脚本式假 transport + 假壳端点。
 * 覆盖：读工具代理（exec_read 摘要）、写工具 stage 不执行、非 succeeded→502、
 * 无 key→503、响应契约（orchestrated + summary 形状）。
 */
import assert from "node:assert/strict";
import test from "node:test";
import {createServer, type Server} from "node:http";
import {mkdtempSync} from "node:fs";
import {tmpdir} from "node:os";
import {join} from "node:path";
import {createMemoryBudgetStore} from "pi-agent-runtime";
import type {ModelReply, ModelTransport} from "pi-agent-runtime";
import {createAssistant, flatten} from "../dist/server.js";

interface Shell {server: Server; url: string; reads: {name: string; args: unknown}[]; stages: {name: string; args: unknown}[]}

async function startShell(): Promise<Shell> {
  const reads: Shell["reads"] = [], stages: Shell["stages"] = [];
  const server = createServer((req, res) => {
    let body = "";
    req.on("data", (c) => {body += c;});
    req.on("end", () => {
      const data = JSON.parse(body || "{}");
      res.setHeader("Content-Type", "application/json");
      if (req.url === "/api/assistant/exec_read") {
        reads.push(data);
        res.end(JSON.stringify({summary: `摘要：${data.name}`}));
      } else if (req.url === "/api/assistant/stage") {
        stages.push(data);
        res.end(JSON.stringify({call_id: "cid-1", action: data.name, args: data.args, preview: "旧值→新值"}));
      } else {
        res.statusCode = 404;
        res.end("{}");
      }
    });
  });
  await new Promise<void>((r) => server.listen(0, "127.0.0.1", r));
  return {server, url: `http://127.0.0.1:${(server.address() as {port: number}).port}`, reads, stages};
}

function writeRes(port: {head: number; body: string}) {
  return {writeHead(code: number) {port.head = code;}, end(b: string) {port.body = b;}} as never;
}

function scriptTransport(script: ModelReply[]): ModelTransport {
  let turn = 0;
  return async () => script[turn++] ?? {content: [{kind: "text", text: "兜底"}], stop: "complete",
                                        usage: {inputTokens: 1, outputTokens: 1}};
}

const TOOLS = [{type: "function", function: {name: "roi__get_state", description: "读状态",
                                             parameters: {type: "object", properties: {}}}},
               {type: "function", function: {name: "roi__set_plan_params", description: "写参数",
                                             parameters: {type: "object", properties: {}}}}];
const LIMITS = {cumulative: "unlimited", maxOutputTokens: 512, modelTimeoutMs: 5000,
                toolTimeoutMs: 5000, controlTimeoutMs: 5000} as const;

async function run(deps: Parameters<typeof createAssistant>[0], body: unknown) {
  const handle = createAssistant({...deps, auditFile: join(mkdtempSync(join(tmpdir(), "sc-")), "audit.jsonl"),
                                  budgets: createMemoryBudgetStore()});
  const port = {head: 0, body: ""};
  await handle(body as never, writeRes(port));
  return {status: port.head, json: JSON.parse(port.body || "{}")};
}

test("读工具经 exec_read 代理并回传摘要", async () => {
  const shell = await startShell();
  try {
    const transport = scriptTransport([
      {content: [{kind: "tool", id: "c1", name: "roi__get_state", arguments: {}}], stop: "tools",
       usage: {inputTokens: 1, outputTokens: 2}},
      {content: [{kind: "text", text: "状态已读"}], stop: "complete", usage: {inputTokens: 1, outputTokens: 1}},
    ]);
    const out = await run({transport, shellUrl: shell.url}, {
      messages: [{role: "system", content: "系统"}, {role: "user", content: "看状态"}],
      tools: TOOLS, write_actions: ["roi__set_plan_params"]});
    assert.equal(out.status, 200);
    assert.equal(out.json.orchestrated, true);
    assert.equal(out.json.reply, "状态已读");
    assert.deepEqual(out.json.tool_calls, [{name: "roi__get_state", args: {}, summary: "摘要：roi__get_state"}]);
    assert.equal(shell.reads.length, 1);
    assert.equal(shell.stages.length, 0);
  } finally {shell.server.close();}
});

test("写提案 → blocked 200 + 检查点 stash（不经 stage/exec_read）", async () => {
  const shell = await startShell();
  try {
    const transport = scriptTransport([
      {content: [{kind: "tool", id: "c1", name: "roi__set_plan_params",
                  arguments: {plan: "计划1", params: {cvr: 0.05}}}], stop: "tools",
       usage: {inputTokens: 1, outputTokens: 2}},
    ]);
    const out = await run({transport, shellUrl: shell.url}, {
      messages: [{role: "user", content: "调参数"}], tools: TOOLS, write_actions: ["roi__set_plan_params"]});
    assert.equal(out.status, 200);
    assert.equal(out.json.blocked, true);
    assert.equal(out.json.orchestrated, true);
    const tc = out.json.tool_calls[0];
    assert.equal(tc.stage_pending, true);
    assert.equal(tc.checkpoint_staged, true);
    assert.match(String(tc.call_id), /^[0-9a-f]{12}$/);
    assert.ok(String(out.json.reply).includes("尚未生效"));
    assert.equal(shell.stages.length, 0);   // 检查点路径不再调 /stage
    assert.equal(shell.reads.length, 0);
  } finally {shell.server.close();}
});

test("模型失败映射 502", async () => {
  const transport: ModelTransport = async () => {throw new Error("provider down");};
  const out = await run({transport, shellUrl: "http://127.0.0.1:1"}, {
    messages: [{role: "user", content: "hi"}], tools: [], write_actions: []});
  assert.equal(out.status, 502);
  assert.ok(String(out.json.error).length > 0);
});

test("全量授权拒绝（无候选检查点）→ blocked 200 + 登记失败提示", async () => {
  const shell = await startShell();
  try {
    const transport = scriptTransport([
      {content: [{kind: "text", text: "不该到达"}], stop: "complete", usage: {inputTokens: 1, outputTokens: 1}},
    ]);
    const out = await run({transport, shellUrl: shell.url, authorize: async () => false}, {
      messages: [{role: "user", content: "hi"}], tools: [], write_actions: []});
    assert.equal(out.status, 200);
    assert.equal(out.json.blocked, true);
    assert.match(String(out.json.reply), /登记失败|尚未生效/);
  } finally {shell.server.close();}
});

test("无 key 且无 transport 注入 → 503", async () => {
  const out = await run({shellUrl: "http://127.0.0.1:1"}, {messages: [], tools: [], write_actions: []});
  assert.equal(out.status, 503);
  assert.match(String(out.json.error), /WORKBENCH_LLM_API_KEY/);
});

test("拍平：system 首段 + 角色行 + 工具行", () => {
  const text = flatten([
    {role: "system", content: "系统指令"},
    {role: "user", content: "第一问"},
    {role: "assistant", content: "第一答"},
    {role: "tool", name: "roi__get_state", content: "摘要：ok"},
    {role: "user", content: "第二问"},
  ]);
  assert.equal(text, "系统指令\n\n用户：第一问\n\n助手：第一答\n\n工具 roi__get_state 返回：摘要：ok\n\n用户：第二问");
});

test("持久预算账本：跨实例累计计量与配置身份", async () => {
  const {createFileBudgetStore} = await import("../dist/budget-store.js");
  const file = join(mkdtempSync(join(tmpdir(), "bs-")), "budget.json");
  const limits = {cumulative: "unlimited", maxOutputTokens: 512, modelTimeoutMs: 5000,
                  toolTimeoutMs: 5000, controlTimeoutMs: 5000} as const;
  const A = createFileBudgetStore(file);
  const lease = await A.claimUncapped("t1", "run-1", "cfg-1", limits);
  const reserved = await lease.reserveModelUpTo(512);  // uncapped 策略须显式上限（与内存版语义一致）
  await lease.settleModelUsage(reserved, {inputTokens: 7, outputTokens: 3});
  await lease.release(100);
  // 跨实例（= 跨重启）：计量持久
  const B = createFileBudgetStore(file);
  const snap = (await B.claimUncapped("t1", "run-2", "cfg-1", limits)).snapshot();
  assert.equal(snap.outputTokens, 3);
  assert.equal(snap.inputTokens, 7);
  assert.equal(snap.activeMs, 100);
  // 配置身份变化拒绝
  await assert.rejects(() => B.claimUncapped("t1", "run-3", "cfg-2", limits),
                       (e: Error & {reason?: string}) => e.reason === "CONFIGURATION_CHANGED");
});

test("health 契约：sdk 版本动态读取真实安装（不再硬编码 0.4.3）", async () => {
  const {healthPayload} = await import("../dist/server.js");
  const {readFileSync} = await import("node:fs");
  const {fileURLToPath} = await import("node:url");
  const pkgPath = join(fileURLToPath(new URL(".", import.meta.url)), "..",
                       "node_modules", "pi-agent-runtime", "package.json");
  const installed = JSON.parse(readFileSync(pkgPath, "utf8"));
  const payload = healthPayload() as {ok: boolean; sdk: string; model: string};
  assert.equal(payload.ok, true);
  assert.equal(payload.sdk, `pi-agent-runtime@${installed.version}`);
  assert.notEqual(payload.sdk, "pi-agent-runtime@0.4.3");
  assert.match(payload.model, /.+/);
});
