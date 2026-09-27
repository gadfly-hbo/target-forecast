/**
 * 测算工作台助手 sidecar（pi-ai 真身）。
 *
 * - POST /chat：接收 OpenAI 格式 {messages, tools}，转 pi TranscriptContext，
 *   用 streamSimple(openai-completions) 调小米 MIMO，返回 {reply, tool_calls}
 * - GET /health：{ok, model}
 *
 * 实测约束（沿用 deep-research 战训记录）：小米 MIMO token-plan 端点不遵循
 * system 通道，system 指令必须并入首条 user 消息。
 */
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { streamSimple } from "@earendil-works/pi-ai/api/openai-completions";
import { normalizeContext } from "@earendil-works/pi-ai/utils/transcript";
import type { Context, Message, Model, Tool } from "@earendil-works/pi-ai";

const PORT = Number(process.env.WORKBENCH_SIDECAR_PORT ?? 8321);
const BASE_URL = process.env.WORKBENCH_LLM_BASE_URL ?? "https://token-plan-cn.xiaomimimo.com/v1";
const API_KEY = process.env.WORKBENCH_LLM_API_KEY ?? "";
const MODEL_ID = process.env.WORKBENCH_LLM_MODEL ?? "mimo-v2.6-pro";
const PROVIDER = "xiaomi-mimo";
const TIMEOUT_MS = Number(process.env.WORKBENCH_LLM_TIMEOUT_MS ?? 120_000);

const model = {
  id: MODEL_ID,
  name: MODEL_ID,
  api: "openai-completions",
  provider: PROVIDER,
  baseUrl: BASE_URL,
  reasoning: false,
  input: ["text"],
  cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
  contextWindow: 1_000_000,
  maxTokens: 8_192,
} as Model<"openai-completions">;

interface OpenAiMessage {
  role: string;
  content?: string;
  name?: string;
  tool_call_id?: string;
  tool_calls?: { id?: string; function?: { name?: string; arguments?: string } }[];
}

/** OpenAI tools（{type:"function", function:{name,...}}）-> pi Tool[]（扁平 name/description/parameters）。 */
function toTools(tools: { type?: string; function?: { name?: string; description?: string; parameters?: unknown } }[] | unknown[]): Tool[] {
  const list = tools as { type?: string; function?: { name?: string; description?: string; parameters?: unknown } }[];
  return list.map((t) => ({
    name: t.function?.name ?? "",
    description: t.function?.description ?? "",
    parameters: (t.function?.parameters ?? { type: "object", properties: {} }) as Tool["parameters"],
  }));
}

/** OpenAI 消息列表 -> pi Context；system 并入首条 user 消息（MIMO 端点实测约束）。 */
function toContext(messages: OpenAiMessage[], tools: Tool[]): Context {
  const systemText = messages.filter((m) => m.role === "system").map((m) => m.content ?? "").join("\n").trim();
  const pi: Message[] = [];
  let systemMerged = !systemText;
  for (const m of messages) {
    if (m.role === "system") continue;
    const stamp = Date.now();
    if (m.role === "user") {
      const text = systemMerged ? (m.content ?? "") : `${systemText}\n\n${m.content ?? ""}`;
      systemMerged = true;
      pi.push({ role: "user", content: [{ type: "text", text }], timestamp: stamp } as Message);
    } else if (m.role === "assistant") {
      const content = [];
      if (m.content) content.push({ type: "text", text: m.content });
      for (const tc of m.tool_calls ?? []) {
        let args = {};
        try { args = JSON.parse(tc.function?.arguments ?? "{}"); } catch { /* 保持空对象 */ }
        content.push({ type: "toolCall", id: tc.id ?? "", name: tc.function?.name ?? "", arguments: args });
      }
      pi.push({
        role: "assistant", content, api: model.api, provider: PROVIDER, model: MODEL_ID,
        usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, stopReason: "stop", timestamp: stamp,
      } as unknown as Message);
    } else if (m.role === "tool") {
      // pi 的 toolResult.content 是内容块数组（convertMessages 按块过滤取文本），
      // 传字符串会被静默丢弃——这是「工具结果为空」的根因
      pi.push({
        role: "toolResult", toolCallId: m.tool_call_id ?? m.name ?? "",
        content: [{ type: "text", text: m.content ?? "" }], timestamp: stamp,
      } as unknown as Message);
    }
  }
  return { messages: pi, tools: tools.length ? tools : undefined };
}

async function handleChat(body: { messages?: OpenAiMessage[]; tools?: unknown[] }, res: ServerResponse) {
  if (!API_KEY) {
    res.writeHead(503, { "Content-Type": "application/json; charset=utf-8" });
    res.end(JSON.stringify({ error: "sidecar 缺少 WORKBENCH_LLM_API_KEY" }));
    return;
  }
  const context = toContext(body.messages ?? [], toTools(body.tools ?? []));
  let text = "";
  const toolCalls: { name: string; args: unknown }[] = [];
  try {
    for await (const event of streamSimple(model, normalizeContext(context), {
      apiKey: API_KEY, maxRetries: 1, maxRetryDelayMs: 5_000,
      signal: AbortSignal.timeout(TIMEOUT_MS),
    })) {
      if (event.type === "text_delta") {
        text += (event as { delta?: string }).delta ?? "";
      } else if (event.type === "done" && event.message) {
        for (const part of event.message.content) {
          if (part.type === "toolCall") toolCalls.push({ name: part.name, args: part.arguments });
        }
      } else if (event.type === "error") {
        const err = (event as { error?: { errorMessage?: string } }).error;
        res.writeHead(502, { "Content-Type": "application/json; charset=utf-8" });
        res.end(JSON.stringify({ error: `模型调用失败：${err?.errorMessage ?? JSON.stringify(event).slice(0, 300)}` }));
        return;
      }
    }
  } catch (err) {
    res.writeHead(502, { "Content-Type": "application/json; charset=utf-8" });
    res.end(JSON.stringify({ error: `模型调用异常：${String(err).slice(0, 300)}` }));
    return;
  }
  res.writeHead(200, { "Content-Type": "application/json; charset=utf-8" });
  res.end(JSON.stringify({ reply: text.trim(), tool_calls: toolCalls }));
}

function readBody(req: IncomingMessage): Promise<string> {
  return new Promise((resolve, reject) => {
    let data = "";
    req.on("data", (c) => { data += c; });
    req.on("end", () => resolve(data));
    req.on("error", reject);
  });
}

const server = createServer(async (req, res) => {
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  if (req.method === "GET" && req.url === "/health") {
    res.writeHead(200);
    res.end(JSON.stringify({ ok: true, model: MODEL_ID, provider: PROVIDER, baseUrl: BASE_URL }));
    return;
  }
  if (req.method === "POST" && req.url === "/chat") {
    try {
      await handleChat(JSON.parse(await readBody(req) || "{}"), res);
    } catch (err) {
      res.writeHead(400);
      res.end(JSON.stringify({ error: `请求不合法：${String(err).slice(0, 200)}` }));
    }
    return;
  }
  res.writeHead(404);
  res.end(JSON.stringify({ error: "not found" }));
});

server.listen(PORT, "127.0.0.1", () => {
  console.log(`[sidecar] pi-ai(${PROVIDER}/${MODEL_ID}) listening on http://127.0.0.1:${PORT}`);
});
