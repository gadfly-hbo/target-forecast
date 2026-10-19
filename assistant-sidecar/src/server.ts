/**
 * 测算工作台助手 sidecar——pi-agent-runtime 真身（Path A 全托管）。
 *
 * - POST /chat：接收 {messages, tools, write_actions}（私有协议：write_actions 为
 *   写工具名清单，映射 SDK Tool.effect），拍平为 prompt（system 并入首段——MIMO
 *   token-plan 端点不遵循 system 通道的战训约束），runAgent 托管工具循环：
 *   读工具 execute() 代理回壳 /api/assistant/exec_read（中文摘要），写工具代理
 *   /api/assistant/stage（仅登记 pending，不执行效果——效果由 Python 在用户
 *   确认后执行，P3 授权即浏览器确认）。
 * - 返回 {reply, tool_calls(执行摘要透传), orchestrated:true}。
 * - GET /health：{ok, model, provider, baseUrl, sdk}
 *
 * 运行护栏：共享内存 BudgetStore + 稳定 taskId + cumulative:'unlimited'
 * （uncapped 五元组）；整 run 唯一界限 = 每请求 AbortSignal(140s < Python 150s)；
 * 同 taskId lease 唯一 → 模块级串行队列；audit JSONL 同步落盘（启动时 >5MiB 轮转）。
 */
import {createHash, randomUUID} from "node:crypto";
import {createServer, type IncomingMessage, type ServerResponse} from "node:http";
import {appendFileSync, existsSync, mkdirSync, readFileSync, renameSync, rmSync, statSync} from "node:fs";
import {createRequire} from "node:module";
import {join} from "node:path";
import {pathToFileURL} from "node:url";
import {createRuntime, createPiTransport} from "pi-agent-runtime";
import {createFileBudgetStore} from "./budget-store.js";
import type {AuditSink, ConversationCheckpoint, JsonValue, ModelConfig, ModelTransport, RunResult, Tool} from "pi-agent-runtime";

const PORT = Number(process.env.WORKBENCH_SIDECAR_PORT ?? 8321);
const BASE_URL = process.env.WORKBENCH_LLM_BASE_URL ?? "https://token-plan-cn.xiaomimimo.com/v1";
const API_KEY = process.env.WORKBENCH_LLM_API_KEY ?? "";
const MODEL_ID = process.env.WORKBENCH_LLM_MODEL ?? "mimo-v2.6-pro";
const PROVIDER = "xiaomi-mimo";

// SDK 版本动态读取真实安装（禁止硬编码——此前 /health 写死 0.4.3 与实装 0.5.3-harness.3 不符）
const require_ = createRequire(import.meta.url);
function sdkVersion(): string {
  try {
    const entry = require_.resolve("pi-agent-runtime"); // …/dist/index.js
    const pkg = JSON.parse(readFileSync(join(entry, "..", "..", "package.json"), "utf8"));
    return `pi-agent-runtime@${pkg.version ?? "unknown"}`;
  } catch {
    return "pi-agent-runtime@unknown";
  }
}
export const SDK_VERSION = sdkVersion();
export function healthPayload(): Record<string, unknown> {
  return {ok: true, model: MODEL_ID, provider: PROVIDER, baseUrl: BASE_URL, sdk: SDK_VERSION};
}
const TIMEOUT_MS = Number(process.env.WORKBENCH_LLM_TIMEOUT_MS ?? 120_000);
const RUN_SIGNAL_MS = 140_000; // 必须 < Python PiSidecarBackend 150s socket 超时
// 稳定任务 ID（标准：不可每请求随机）——工具定义参与 config hash，故按
// 工具集派生后缀：不同工具集 = 不同任务身份（各自台账），同集稳定复用。
function taskIdFor(tools: OpenAiTool[], writeNames: readonly string[]): string {
  const defs = tools.map((t) => `${t.function?.name ?? ""}:${writeNames.includes(t.function?.name ?? "") ? "w" : "r"}`).sort().join("|");
  return `workbench-assistant:${createHash("sha256").update(defs).digest("hex").slice(0, 10)}`;
}

const modelConfig: ModelConfig = {
  provider: PROVIDER, id: MODEL_ID, protocol: "openai-completions",
  endpoint: BASE_URL, contextWindow: 1_000_000, maxOutputTokens: 8_192, reasoning: false,
};

interface OpenAiMessage {
  role: string;
  content?: string;
  name?: string;
  tool_call_id?: string;
}
interface OpenAiTool {
  type?: string;
  function?: {name?: string; description?: string; parameters?: unknown};
}
export interface ToolCallRecord {
  name: string; args: unknown; summary: string;
  stage_pending?: boolean; call_id?: string; preview?: string;
  /** (c)-resume：blocked 路径的提案已落检查点 stash，确认将走 /resume */
  checkpoint_staged?: boolean;
}

interface StashEntry {checkpoint: ConversationCheckpoint; createdAt: number;
  proposal: {name: string; args: unknown}; tools: OpenAiTool[]; writeActions: string[]}

/** 检查点 stash（A1 覆盖语义）：blocked run 收场时把"最后一条 assistant 有未配对
 * calls 且无 toolFailed 的 ready 检查点"按新铸 call_id 落表；随进程内存（R7）。 */
const stash = new Map<string, StashEntry>();
const STASH_MAX = 8;

interface CheckpointBlob {state?: string; messages?: {role?: string; content?: unknown,
  calls?: {id?: string; name?: string; arguments?: unknown}[], toolFailed?: boolean,
  text?: string}[]}

function readyCandidate(blob: CheckpointBlob, writeNames: readonly string[]): {writeCallId: string; name: string; args: unknown; text: string} | null {
  if (blob.state !== "ready" || !Array.isArray(blob.messages)) return null;
  const lastA = [...blob.messages].reverse().find((m) => m.role === "assistant");
  if (!lastA || !Array.isArray(lastA.calls) || lastA.calls.length === 0) return null;
  const ids = new Set(blob.messages.filter((m) => m.role === "tool").map((m) => (m as {toolId?: string}).toolId));
  const pending = lastA.calls.filter((c) => !ids.has(c.id ?? ""));
  if (pending.length === 0) return null;
  if (blob.messages.some((m) => m.role === "tool" && m.toolFailed)) return null;
  const write = pending.find((c) => c.name && writeNames.includes(c.name)) ?? pending[0];
  const text = Array.isArray(lastA.content)
    ? lastA.content.filter((c): c is {type: "text"; text: string} => (c as {type?: string}).type === "text")
        .map((c) => c.text).join("")
    : String(lastA.text ?? "");
  return {writeCallId: write.id ?? "", name: write.name ?? "", args: write.arguments, text};
}

/** 拍平：system 首段 + 角色行历史（工具行仅确认路径出现）+ run 内多轮由 SDK 原生承载。 */
export function flatten(messages: OpenAiMessage[]): string {
  const system = messages.filter((m) => m.role === "system").map((m) => m.content ?? "").join("\n").trim();
  const lines: string[] = system ? [system] : [];
  for (const m of messages) {
    if (m.role === "system") continue;
    if (m.role === "user") lines.push(`用户：${m.content ?? ""}`);
    else if (m.role === "assistant") lines.push(`助手：${m.content ?? ""}`);
    else if (m.role === "tool") lines.push(`工具 ${m.name ?? m.tool_call_id ?? ""} 返回：${m.content ?? ""}`);
  }
  return lines.join("\n\n");
}

async function postJson(url: string, body: unknown): Promise<Record<string, unknown>> {
  const res = await fetch(url, {method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify(body), signal: AbortSignal.timeout(110_000)});
  const text = await res.text();
  if (!res.ok) throw new Error(`shell ${url} -> HTTP ${res.status}: ${text.slice(0, 200)}`);
  return JSON.parse(text) as Record<string, unknown>;
}

/** OpenAI tools + 写名册 → SDK Tools（定义字节稳定；execute 闭包按请求构造，config hash 不含 execute）。 */
export function toSdkTools(tools: OpenAiTool[], writeNames: readonly string[],
                           shellUrl: string, collect: ToolCallRecord[]): Tool[] {
  return tools.map((t): Tool => {
    const name = t.function?.name ?? "";
    const isWrite = writeNames.includes(name);
    return {
      name,
      description: t.function?.description ?? "",
      effect: isWrite ? "write" : "read",
      resourceUnits: 1,
      parameters: (t.function?.parameters ?? {type: "object", properties: {}}) as Tool["parameters"],
      execute: async (args: Record<string, unknown>) => {
        if (isWrite) {
          const staged = await postJson(`${shellUrl}/api/assistant/stage`, {name, args});
          const callId = String(staged.call_id ?? ""), preview = String(staged.preview ?? "");
          collect.push({name, args, summary: "写提案已登记，等待用户确认", stage_pending: true,
                        call_id: callId, preview});
          return {staged: true, call_id: callId, preview} as {[key: string]: JsonValue};
        }
        const out = await postJson(`${shellUrl}/api/assistant/exec_read`, {name, args});
        collect.push({name, args, summary: String(out.summary ?? "")});
        // result 补摘要信息损失（如计划名清单）；summary 仍供前端展示
        return (out.result === undefined ? {summary: String(out.summary ?? "")}
                : {summary: String(out.summary ?? ""), result: out.result}) as {[key: string]: JsonValue};
      },
    };
  });
}

function makeAuditSink(file: string): AuditSink {
  try {
    if (existsSync(file) && statSync(file).size > 5 * 1024 * 1024) {
      rmSync(`${file}.1`, {force: true});
      renameSync(file, `${file}.1`);
    }
    mkdirSync(join(file, ".."), {recursive: true});
  } catch { /* 审计目录初始化失败由 append 时暴露 */ }
  return {append: async (event) => {appendFileSync(file, `${JSON.stringify(event)}\n`);}};
}

/** 同 taskId lease 唯一 → 并发 chat 串行（ThreadingHTTPServer 允许双发，此处排队防 TASK_BUSY）。 */
let queue: Promise<unknown> = Promise.resolve();
function enqueue<T>(job: () => Promise<T>): Promise<T> {
  const next = queue.then(job, job);
  queue = next.catch(() => {});
  return next;
}

export interface AssistantDeps {
  transport?: ModelTransport;
  shellUrl?: string;
  auditFile?: string;
  budgets?: ReturnType<typeof createFileBudgetStore>;
  authorize?: (action: unknown) => Promise<boolean>;
}

export function createAssistant(deps: AssistantDeps = {}) {
  const shellUrl = deps.shellUrl ?? process.env.WORKBENCH_SHELL_URL ?? "http://127.0.0.1:8300";
  const root = process.env.WORKBENCH_ROOT ?? process.cwd();
  const auditFile = deps.auditFile ?? join(root, "workspace", "assistant", "audit.jsonl");
  // 持久预算账本（标准终态）：跨重启累计计量；测试可注入内存版
  const budgets = deps.budgets ?? createFileBudgetStore(join(root, "workspace", "assistant", "budget.json"));
  const audit = makeAuditSink(auditFile);

  function runtime(writeGate: boolean) {
    return createRuntime({
      model: modelConfig,
      transport: deps.transport ?? createPiTransport({model: modelConfig, apiKey: API_KEY}),
      // 授权（P3 + (c)-resume）：读工具/模型外发放行（任务级预授权）；写工具在
      // /chat 路径一律拒绝（AUTHORITY_REQUIRED → blocked + 'ready' 检查点，效果
      // 永不发生在未确认 run 内），仅在 /resume（用户已确认）路径放行。
      authorize: deps.authorize ?? (async (action: {kind?: string; effect?: string}) =>
        !(writeGate && action.kind === "tool" && action.effect === "write")),
      audit, budgets,
    });
  }

  const LIMITS = {cumulative: "unlimited", maxOutputTokens: 8_192,
                  modelTimeoutMs: TIMEOUT_MS, toolTimeoutMs: 120_000, controlTimeoutMs: 10_000} as const;

  /** blocked 收场：把 candidate 按新铸 call_id 落 stash（FIFO/2MiB 守卫），返回 pending 条目。 */
  function stashBlocked(candidate: {checkpoint: ConversationCheckpoint; writeCallId: string; name: string; args: unknown; text: string} | null,
                        tools: OpenAiTool[], writeActions: string[]): ToolCallRecord | null {
    if (!candidate) return null;
    if (Buffer.byteLength(JSON.stringify(candidate.checkpoint)) > 2_097_152) return null;  // R6
    const callId = randomUUID().replaceAll("-", "").slice(0, 12);
    if (stash.size >= STASH_MAX) stash.delete(stash.keys().next().value as string);
    stash.set(callId, {checkpoint: candidate.checkpoint as ConversationCheckpoint, createdAt: Date.now(),
                       proposal: {name: candidate.name, args: candidate.args},
                       tools, writeActions});
    return {name: candidate.name, args: candidate.args, summary: "写提案待确认",
            stage_pending: true, call_id: callId, checkpoint_staged: true};
  }

  async function handleResume(body: {call_id?: string}, res: ServerResponse): Promise<void> {
    const callId = String(body.call_id ?? "");
    const entry = stash.get(callId);
    if (!entry) {
      res.writeHead(404, {"Content-Type": "application/json; charset=utf-8"});
      res.end(JSON.stringify({error: "提案不存在或已处理", executed: false}));
      return;
    }
    stash.delete(callId);  // 一次性
    let executed = false;
    const collect: ToolCallRecord[] = [];
    // 首个未确认写绑定 exec_write（call_id 一次性在壳端弹出）；其余写良性取消（A3/R5）
    let writeBound = false;
    const tools: Tool[] = entry.tools.map((t): Tool => {
      const name = t.function?.name ?? "";
      const isWrite = entry.writeActions.includes(name);
      return {
        name, description: t.function?.description ?? "",
        effect: isWrite ? "write" : "read", resourceUnits: 1,
        parameters: (t.function?.parameters ?? {type: "object", properties: {}}) as Tool["parameters"],
        execute: async (args: Record<string, unknown>) => {
          if (!isWrite) {
            const out = await postJson(`${shellUrl}/api/assistant/exec_read`, {name, args});
            collect.push({name, args, summary: String(out.summary ?? "")});
            return (out.result === undefined ? {summary: out.summary}
                    : {summary: out.summary, result: out.result}) as {[key: string]: JsonValue};
          }
          if (!writeBound) {
            writeBound = true;
            const out = await postJson(`${shellUrl}/api/assistant/exec_write`, {call_id: callId, name, args});
            executed = true;  // 置位于执行成功后（exec_write 失败 = 未执行，Python 可降级）
            collect.push({name, args, summary: String(out.summary ?? "")});
            return (out.result === undefined ? {summary: out.summary}
                    : {summary: out.summary, result: out.result}) as {[key: string]: JsonValue};
          }
          collect.push({name, args, summary: "已取消（另有写提案请逐个确认）"});
          return {summary: "已取消（请逐个确认）"} as {[key: string]: JsonValue};
        },
      };
    });
    try {
      const result: RunResult<string> = await enqueue(() => runtime(false).runAgent({
        taskId: taskIdFor(entry.tools, entry.writeActions),  // A4：与 /chat 同派生
        prompt: "", checkpoint: entry.checkpoint,            // R1：恢复必空串
        tools, limits: LIMITS,
        saveCheckpoint: async (cp: unknown) => { void cp; },  // R2：恢复路径检查点不再使用
        signal: AbortSignal.timeout(RUN_SIGNAL_MS),
      }));
      if (result.status !== "succeeded") {
        res.writeHead(500, {"Content-Type": "application/json; charset=utf-8"});
        res.end(JSON.stringify({error: `恢复未成功：${result.status}/${result.reason}`, executed}));
        return;
      }
      res.writeHead(200, {"Content-Type": "application/json; charset=utf-8"});
      res.end(JSON.stringify({reply: (result.value ?? "").trim(), tool_calls: collect, orchestrated: true}));
    } catch (err) {
      res.writeHead(500, {"Content-Type": "application/json; charset=utf-8"});
      res.end(JSON.stringify({error: `恢复异常：${String(err).slice(0, 300)}`, executed}));
    }
  }

  async function chatImpl(body: {
    messages?: OpenAiMessage[]; tools?: OpenAiTool[]; write_actions?: string[];
  }, res: ServerResponse): Promise<void> {
    const collect: ToolCallRecord[] = [];
    const tools = body.tools ?? [];
    const writeActions = body.write_actions ?? [];
    // A1 覆盖语义：单一 candidate，收到合格 ready 即覆盖；tool-admitted/toolFailed 跳过
    let candidate: {checkpoint: ConversationCheckpoint; writeCallId: string; name: string; args: unknown; text: string} | null = null;
    try {
      const result: RunResult<string> = await enqueue(() => runtime(true).runAgent({
        taskId: taskIdFor(tools, writeActions),
        prompt: flatten(body.messages ?? []),
        tools: toSdkTools(tools, writeActions, shellUrl, collect),
        limits: LIMITS,
        ...(writeActions.length ? {saveCheckpoint: async (cp: unknown) => {
          const hit = readyCandidate(cp as CheckpointBlob, writeActions);
          if (hit) candidate = {checkpoint: structuredClone(cp) as ConversationCheckpoint, ...hit};
        }} : {}),
        signal: AbortSignal.timeout(RUN_SIGNAL_MS),
      }));
      if (result.status === "blocked" && result.reason === "AUTHORITY_REQUIRED") {
        const found = candidate as {checkpoint: ConversationCheckpoint; writeCallId: string; name: string; args: unknown; text: string} | null;  // 闭包写入，TS 不追踪窄化
        const pendingTc = stashBlocked(found, tools, writeActions);
        const reply = (found?.text ? found.text + "\n\n" : "")
          + (pendingTc ? "以上参数变更尚未生效，请在下方确认后执行，取消可放弃。"
                       : "该操作需要确认，但提案登记失败，请重试。");
        res.writeHead(200, {"Content-Type": "application/json; charset=utf-8"});
        res.end(JSON.stringify({reply, tool_calls: pendingTc ? [pendingTc] : collect,
                                orchestrated: true, blocked: true}));
        return;
      }
      if (result.status !== "succeeded") {
        res.writeHead(502, {"Content-Type": "application/json; charset=utf-8"});
        res.end(JSON.stringify({error: `模型编排未成功：${result.status}/${result.reason}`}));
        return;
      }
      res.writeHead(200, {"Content-Type": "application/json; charset=utf-8"});
      res.end(JSON.stringify({reply: (result.value ?? "").trim(), tool_calls: collect, orchestrated: true}));
    } catch (err) {
      res.writeHead(502, {"Content-Type": "application/json; charset=utf-8"});
      res.end(JSON.stringify({error: `模型调用异常：${String(err).slice(0, 300)}`}));
    }
  };
  return Object.assign(async function handleChat(body: {
    messages?: OpenAiMessage[]; tools?: OpenAiTool[]; write_actions?: string[];
  }, res: ServerResponse): Promise<void> {
    if (!API_KEY && !deps.transport) {
      res.writeHead(503, {"Content-Type": "application/json; charset=utf-8"});
      res.end(JSON.stringify({error: "sidecar 缺少 WORKBENCH_LLM_API_KEY"}));
      return;
    }
    await chatImpl(body, res);
  }, {resume: handleResume});
}

function readBody(req: IncomingMessage): Promise<string> {
  return new Promise((resolve, reject) => {
    let data = "";
    req.on("data", (c) => {data += c;});
    req.on("end", () => resolve(data));
    req.on("error", reject);
  });
}

const handleChat = createAssistant();
const server = createServer(async (req, res) => {
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  if (req.method === "GET" && req.url === "/health") {
    res.writeHead(200);
    res.end(JSON.stringify(healthPayload()));
    return;
  }
  if (req.method === "POST" && req.url === "/resume") {
    try {
      await handleChat.resume(JSON.parse(await readBody(req) || "{}"), res);
    } catch (err) {
      res.writeHead(400);
      res.end(JSON.stringify({error: `请求不合法：${String(err).slice(0, 200)}`}));
    }
    return;
  }
  if (req.method === "POST" && req.url === "/chat") {
    try {
      await handleChat(JSON.parse(await readBody(req) || "{}"), res);
    } catch (err) {
      res.writeHead(400);
      res.end(JSON.stringify({error: `请求不合法：${String(err).slice(0, 200)}`}));
    }
    return;
  }
  res.writeHead(404);
  res.end(JSON.stringify({error: "not found"}));
});

// 入口守卫：import（测试）不监听，dist/server.js 直接启动才监听
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  server.listen(PORT, "127.0.0.1", () => {
    console.log(`[sidecar] pi-agent-runtime(${PROVIDER}/${MODEL_ID}) listening on http://127.0.0.1:${PORT}`);
  });
}
