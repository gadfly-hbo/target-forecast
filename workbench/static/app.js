/* 测算工作台壳前端（无框架、离线）：工具导航 + iframe 装载 + ?tool= 深链。 */
"use strict";

const $ = (id) => document.getElementById(id);

async function main() {
  const st = await (await fetch("api/state")).json();
  const nav = $("nav");
  nav.innerHTML = st.tools
    .map((t) => `<a class="nav-item" data-id="${t.id}" href="t/${t.id}/"><span class="icon">${t.icon}</span><span>${t.name}</span></a>`)
    .join("");

  const items = [...nav.querySelectorAll(".nav-item")];
  const select = (id) => {
    items.forEach((a) => a.classList.toggle("active", a.dataset.id === id));
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

  const requested = new URLSearchParams(location.search).get("tool");
  const first = st.tools.find((t) => t.id === requested) || st.tools[0];
  if (first) select(first.id);
}

main().catch((e) => {
  $("nav").innerHTML = `<p class="err">工作台加载失败：${e.message}</p>`;
});
