/* 测算工作台壳前端（无框架、离线）：工具导航 + iframe 装载 + ?tool= 深链 + 状态栏 + 助手。
   左右两侧栏均可收起，状态记在 localStorage。 */
"use strict";

const $ = (id) => document.getElementById(id);
const LS_SIDEBAR = "wb-sidebar-collapsed";
const LS_ASSISTANT = "wb-assistant-collapsed";

async function loadToolState(id) {
  // 数据源标记只来自工具现有 /api/state（PRD D5），无 demo_used 字段的工具不显示
  try {
    const st = await (await fetch(`t/${id}/api/state`)).json();
    $("sb-demo").classList.toggle("hidden", !st.demo_used);
  } catch {
    $("sb-demo").classList.add("hidden");
  }
}

async function main() {
  const st = await (await fetch("api/state")).json();
  const nav = $("nav");
  nav.innerHTML = st.tools
    .map((t) => `<a class="nav-item" data-id="${t.id}" href="t/${t.id}/"><span class="nav-icon">${t.icon}</span><span class="nav-label">${t.name}</span></a>`)
    .join("");

  const items = [...nav.querySelectorAll(".nav-item")];
  const select = (id) => {
    const tool = st.tools.find((t) => t.id === id);
    items.forEach((a) => a.classList.toggle("active", a.dataset.id === id));
    $("sb-tool").textContent = tool ? `${tool.name}` : id;
    loadToolState(id);
    if ($("frame").src.endsWith(`/t/${id}/`)) return;
    $("frame").src = `t/${id}/`;
  };
  items.forEach((a) =>
    a.addEventListener("click", (e) => {
      e.preventDefault();
      select(a.dataset.id);
      history.replaceState(null, "", `?tool=${a.dataset.id}`);
    })
  );

  $("sb-product").textContent = `测算工作台 v${st.version}`;
  const requested = new URLSearchParams(location.search).get("tool");
  const first = st.tools.find((t) => t.id === requested) || st.tools[0];
  if (first) select(first.id);
  initAssistant(() => document.querySelector(".nav-item.active")?.dataset.id || first?.id);
  initSidebars();
}

/* ---------- 侧栏收合（状态持久化） ---------- */
function initSidebars() {
  const sidebar = $("sidebar");
  const assistant = $("assistant");

  const applySidebar = (collapsed) => {
    sidebar.classList.toggle("sidebar-collapsed", collapsed);
    $("sidebar-toggle").textContent = collapsed ? "»" : "«";
    localStorage.setItem(LS_SIDEBAR, collapsed ? "1" : "0");
  };
  const applyAssistant = (collapsed) => {
    assistant.classList.toggle("collapsed", collapsed);
    localStorage.setItem(LS_ASSISTANT, collapsed ? "1" : "0");
  };

  applySidebar(localStorage.getItem(LS_SIDEBAR) === "1");
  applyAssistant(localStorage.getItem(LS_ASSISTANT) === "1");

  $("sidebar-toggle").addEventListener("click", () =>
    applySidebar(!sidebar.classList.contains("sidebar-collapsed")));
  $("assistant-close").addEventListener("click", () => applyAssistant(true));
  $("assistant-toggle").addEventListener("click", () => {
    const willOpen = assistant.classList.contains("collapsed");
    applyAssistant(!willOpen);
    if (willOpen) $("as-input").focus();
  });
}

/* ---------- 测算助手：右侧面板，两步确认门，503 降级 ---------- */
const As = { history: [], currentTool: null };

function asEsc(s) { return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }

function asMsg(cls, text) {
  const empty = $("as-msgs").querySelector(".as-empty");
  if (empty) empty.remove();
  const el = document.createElement("div");
  el.className = `as-msg ${cls}`;
  el.textContent = text;
  $("as-msgs").appendChild(el);
  $("as-msgs").scrollTop = $("as-msgs").scrollHeight;
  return el;
}

async function asSend(payload) {
  const res = await fetch("api/assistant/chat", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
  });
  const data = await res.json().catch(() => ({}));
  if (res.status === 503) {
    asMsg("err", `助手未配置 LLM 后端。\n${data.setup_hint || ""}`);
    return null;
  }
  if (!res.ok) { asMsg("err", `请求失败：${data.error || res.status}`); return null; }
  return data;
}

async function asAsk() {
  const text = $("as-input").value.trim();
  if (!text) return;
  $("as-input").value = "";
  asMsg("user", text);
  As.history.push({ role: "user", content: text });
  const data = await asSend({ message: text, history: As.history.slice(-10), tool_id: As.currentTool });
  if (!data) return;
  if (data.pending_confirmation) {
    As.history.push({ role: "assistant", content: data.reply });
    asMsg("bot", data.reply);
    asShowConfirm(data.pending_confirmation);
  } else {
    As.history.push({ role: "assistant", content: data.reply });
    asMsg("bot", data.reply || "（无回复）");
    (data.tool_calls || []).forEach((tc) => asMsg("tool", `⚙ ${tc.name}：${tc.summary || ""}`));
    asRefreshFrame();
  }
}

function asShowConfirm(pending) {
  const box = $("as-confirm");
  box.innerHTML = `
    <div><b>待确认变更</b>（${asEsc(pending.action)}）</div>
    <div>${asEsc(pending.preview)}</div>
    <div class="as-confirm-btns">
      <button type="button" class="primary" id="as-ok">确认执行</button>
      <button type="button" id="as-cancel">取消</button>
    </div>`;
  box.classList.remove("hidden");
  $("as-ok").addEventListener("click", async () => {
    box.classList.add("hidden");
    const data = await asSend({ confirm: pending.call_id, tool_id: As.currentTool });
    if (!data) return;
    As.history.push({ role: "assistant", content: data.reply });
    asMsg("bot", data.reply);
    (data.tool_calls || []).forEach((tc) => asMsg("tool", `⚙ ${tc.name}：${tc.summary || ""}`));
    asRefreshFrame();  // 参数已落盘，刷新工具页使补丁生效
  });
  $("as-cancel").addEventListener("click", async () => {
    box.classList.add("hidden");
    asSend({ cancel: pending.call_id, tool_id: As.currentTool });  // 服务端清理 pending（一次性语义）
    asMsg("bot", "已取消该变更。");
  });
}

function asRefreshFrame() {
  const f = $("frame");
  if (f && f.src) f.contentWindow.location.reload();
}

function initAssistant(currentToolGetter) {
  As.currentTool = currentToolGetter();
  $("as-send").addEventListener("click", asAsk);
  $("as-input").addEventListener("keydown", (e) => { if (e.key === "Enter") asAsk(); });
  // 后端标识（回放模式明示）
  fetch("api/assistant/status").then((r) => r.json()).then((d) => {
    const label = { EchoBackend: "回放模式（非真 LLM）", OpenAiCompatBackend: "LLM 直连", PiSidecarBackend: "pi-agent" }[d.backend] || d.backend;
    $("as-backend").textContent = label;
    $("sb-llm").textContent = `助手：${label}`;
  }).catch(() => {});
  // 工具切换时同步助手上下文
  const nav = $("nav");
  if (nav) nav.addEventListener("click", () => setTimeout(() => { As.currentTool = currentToolGetter(); }, 0));
}

main().catch((e) => {
  $("nav").innerHTML = `<p class="err">工作台加载失败：${e.message}</p>`;
});
