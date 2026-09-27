/* 测算工作台壳前端（无框架、离线）：工具导航 + iframe 装载 + ?tool= 深链 + 状态栏。 */
"use strict";

const $ = (id) => document.getElementById(id);

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
    .map((t) => `<a class="nav-item" data-id="${t.id}" href="t/${t.id}/"><span class="icon">${t.icon}</span><span>${t.name}</span></a>`)
    .join("");

  const items = [...nav.querySelectorAll(".nav-item")];
  const select = (id) => {
    const tool = st.tools.find((t) => t.id === id);
    items.forEach((a) => a.classList.toggle("active", a.dataset.id === id));
    $("sb-tool").textContent = tool ? `${tool.icon} ${tool.name}` : id;
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
}

main().catch((e) => {
  $("nav").innerHTML = `<p class="err">工作台加载失败：${e.message}</p>`;
});
