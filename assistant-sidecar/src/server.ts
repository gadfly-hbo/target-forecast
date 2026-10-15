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
import {createServer, type IncomingMessage, type ServerResponse} from "node:http";
import {appendFileSync, existsSync, mkdirSync, renameSync, rmSync, statSync} from "node:fs";
import {join} from "node:path";
import {pathToFileURL} from "node:url";
import {createRuntime, createPiTransport, createMemoryBudgetStore} from "pi-agent-runtime";
import type {AuditSink, JsonValue, ModelConfig, ModelTransport, RunResult, Tool} from "pi-agent-runtime";

const PORT = Number(process.env.WORKBENCH_SIDECAR_PORT ?? 8321);
const BASE_URL = process.env.WORKBENCH_LLM_BASE_URL ?? "https://token-plan-cn.xiaomimimo.com/v1";
const API_KEY = process.env.WORKBENCH_LLM_API_KEY ?? "";
const MODEL_ID = process.env.WORKBENCH_LLM_MODEL ?? "mimo-v2.6-pro";
const PROVIDER = "xiaomi-mimo";
const TIMEOUT_MS = Number(process.env.WORKBENCH_LLM_TIMEOUT_MS ?? 120_000);
const RUN_SIGNAL_MS = 140_000; // 必须 < Python PiSidecarBackend 150s socket 超时
const TASK_ID = "workbench-assistant"; // 稳定任务 ID（标准：不可每请求随机）

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
        return {summary: String(out.summary ?? "")} as {[key: string]: JsonValue};
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
  budgets?: ReturnType<typeof createMemoryBudgetStore>;
  authorize?: (action: unknown) => Promise<boolean>;
}

export function createAssistant(deps: AssistantDeps = {}) {
  const shellUrl = deps.shellUrl ?? process.env.WORKBENCH_SHELL_URL ?? "http://127.0.0.1:8300";
  const auditFile = deps.auditFile ?? join(process.env.WORKBENCH_ROOT ?? process.cwd(),
                                           "workspace", "assistant", "audit.jsonl");
  const budgets = deps.budgets ?? createMemoryBudgetStore();
  const audit = makeAuditSink(auditFile);

  function runtime() {
    return createRuntime({
      model: modelConfig,
      transport: deps.transport ?? createPiTransport({model: modelConfig, apiKey: API_KEY}),
      // 授权说明（P3）：run 内效果只有 ①模型外发（用户配 key 即预授权）②读工具本地
      // 回环（预授权）③写提案登记（良性）。真实写效果永不发生在 run 内——Python
      // 侧用户确认后才执行；写工具的名门禁在壳端 /stage。
      authorize: deps.authorize ?? (async () => true),
      audit, budgets,
    });
  }

  return async function handleChat(body: {
    messages?: OpenAiMessage[]; tools?: OpenAiTool[]; write_actions?: string[];
  }, res: ServerResponse): Promise<void> {
    if (!API_KEY && !deps.transport) {
      res.writeHead(503, {"Content-Type": "application/json; charset=utf-8"});
      res.end(JSON.stringify({error: "sidecar 缺少 WORKBENCH_LLM_API_KEY"}));
      return;
    }
    const collect: ToolCallRecord[] = [];
    try {
      const result: RunResult<string> = await enqueue(() => runtime().runAgent({
        taskId: TASK_ID,
        prompt: flatten(body.messages ?? []),
        tools: toSdkTools(body.tools ?? [], body.write_actions ?? [], shellUrl, collect),
        limits: {cumulative: "unlimited", maxOutputTokens: 8_192,
                 modelTimeoutMs: TIMEOUT_MS, toolTimeoutMs: 120_000, controlTimeoutMs: 10_000},
        signal: AbortSignal.timeout(RUN_SIGNAL_MS),
      }));
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
    res.end(JSON.stringify({ok: true, model: MODEL_ID, provider: PROVIDER, baseUrl: BASE_URL,
                            sdk: "pi-agent-runtime@0.4.3"}));
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
