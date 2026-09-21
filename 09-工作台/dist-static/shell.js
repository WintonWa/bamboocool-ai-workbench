/* 工作台外壳（V6）
 *
 * 职责边界很硬：外壳管导航、路由、URL 状态、筛选快照、返回态恢复、AI 槽位、
 * 浮层与抽屉、以及给模块的 ctx 工具。业务表达一律由模块渲染。
 *
 * 模块由 /api/modules 发现后动态 import，外壳里没有任何模块清单。
 * import 与 mount 都包 try/catch：一个模块坏了只在它自己的容器里显示占位，
 * 导航和其他模块照常可用（契约 8.4）。
 */

import { aiMark, aiMarkHTML, loadSchemes, schemePicker } from "./aimark.js";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k === "html") node.innerHTML = v;
    else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : String(v));
  }
  for (const c of [].concat(children)) {
    if (c === null || c === undefined || c === false) continue;
    node.appendChild(typeof c === "string" || typeof c === "number" ? document.createTextNode(String(c)) : c);
  }
  return node;
}

/* ---- 格式化。旧两个模块各写了一份 pc()，一个固定 1 位小数一个可传位数，
 *      空值一个用「—」一个用「--」。这里统一，模块不要再自己写。 ------------ */

const DASH = "—";

const fmt = {
  int(v) {
    return v === null || v === undefined || Number.isNaN(v) ? DASH : Math.round(v).toLocaleString("zh-CN");
  },
  num(v, d = 1) {
    return v === null || v === undefined || Number.isNaN(v) ? DASH : Number(v).toFixed(d);
  },
  pct(v, d = 1) {
    return v === null || v === undefined || Number.isNaN(v) ? DASH : `${(Number(v) * 100).toFixed(d)}%`;
  },
  money(v, d = 2) {
    return v === null || v === undefined || Number.isNaN(v) ? DASH : `$${Number(v).toFixed(d)}`;
  },
  days(v, d = 1) {
    return v === null || v === undefined || Number.isNaN(v) ? DASH : `${Number(v).toFixed(d)} 天`;
  },
  date(v) {
    return v || DASH;
  },
  dash: DASH,
};

/* 数据性质与状态徽标（契约 6.6）。只接受词表内的值，别的返回 null，
 * 这样内部枚举名想上屏也上不去。 */
const NATURES = new Set(["真实", "推导", "模拟", "混合"]);
const CONDITIONS = new Set(["正常", "过期", "缺失", "待确认", "失败", "加载中", "空结果"]);

function nature(v) {
  return NATURES.has(v) ? el("span", { class: "wb-nature", "data-v": v, text: v }) : null;
}

function cond(v) {
  if (!CONDITIONS.has(v) || v === "正常") return null;
  return el("span", { class: "wb-cond", "data-v": v, text: v });
}

/* ---- 状态 ------------------------------------------------------------- */

const S = {
  meta: null,
  modules: [],
  moduleId: null,
  pageId: null,
  objectId: null,
  shared: {},          // 跨模块共享上下文，模块只读
  filters: {},         // 业务筛选，裸键，进 query
  params: {},          // 可调参数，带模块前缀，进 query
  moduleState: {},     // moduleId -> 模块自己的 state 子树（契约 8.3）
  impls: {},           // moduleId -> 已 import 的模块命名空间
  mounted: null,
};

const dom = {};

function moduleInfo(id) {
  return S.modules.find((m) => m.id === id) || null;
}

function firstUsable() {
  return S.modules.find((m) => !m.degraded) || S.modules[0] || null;
}

/* ---- 路由：URL 即状态（契约 8.8，借自 V5 的 types.ts） ------------------
 * 默认方案 /<模块>/<页面?>/<对象?>：第二段先按声明的 page id 匹配，
 * 匹配不上就当成对象 id 落在默认页。模块可用 pathFor / parsePath 覆盖。 */

function parsePath(pathname) {
  const seg = pathname.split("/").filter(Boolean).map(decodeSafe);
  if (!seg.length) {
    const m = firstUsable();
    return { moduleId: m ? m.id : null, pageId: null, objectId: null };
  }
  const info = moduleInfo(seg[0]);
  if (!info) {
    const m = firstUsable();
    return { moduleId: m ? m.id : null, pageId: null, objectId: null };
  }
  const impl = S.impls[info.id];
  if (impl && typeof impl.parsePath === "function") {
    try {
      const r = impl.parsePath(seg.slice(1)) || {};
      return { moduleId: info.id, pageId: r.pageId || null, objectId: r.objectId || null };
    } catch (err) {
      console.error(`[${info.id}] parsePath 出错，回落默认方案`, err);
    }
  }
  const ids = (info.pages || []).map((p) => p.id);
  if (seg[1] && ids.includes(seg[1])) {
    return { moduleId: info.id, pageId: seg[1], objectId: seg[2] || null };
  }
  return { moduleId: info.id, pageId: ids[0] || null, objectId: seg[1] || null };
}

function pathFor({ moduleId, pageId, objectId }) {
  const info = moduleInfo(moduleId);
  const impl = S.impls[moduleId];
  if (impl && typeof impl.pathFor === "function") {
    try {
      const tail = impl.pathFor({ pageId, objectId });
      if (typeof tail === "string") return `/${moduleId}${tail ? "/" + tail : ""}`;
    } catch (err) {
      console.error(`[${moduleId}] pathFor 出错，回落默认方案`, err);
    }
  }
  const ids = info ? (info.pages || []).map((p) => p.id) : [];
  const parts = [moduleId];
  if (pageId && pageId !== ids[0]) parts.push(pageId);
  if (objectId) parts.push(encodeURIComponent(objectId));
  return "/" + parts.join("/");
}

function decodeSafe(v) {
  try {
    return decodeURIComponent(v);
  } catch {
    return v;
  }
}

/* 会话级开关，不属于业务状态但必须在 URL 重写后存活。
 * 外壳启动时会 history.replaceState 成 currentUrl()，而 currentUrl() 只拼
 * 共享上下文/筛选/参数三类键 —— 不把这些 flag 带上，?tune=1 会在调参器读到它
 * 之前就被剥掉，等于开关永远打不开。 */
const SESSION_FLAGS = ["tune", "rail", "glass"];

function queryString() {
  const q = new URLSearchParams();
  const cur = new URLSearchParams(location.search);
  for (const f of SESSION_FLAGS) {
    const val = cur.get(f);
    if (val !== null && val !== "") q.set(f, val);
  }
  for (const [k, v] of Object.entries(S.shared)) if (v) q.set(k, v);
  for (const [k, v] of Object.entries(S.filters)) if (v !== "" && v !== null && v !== undefined) q.set(k, v);
  for (const [k, v] of Object.entries(S.params)) if (v !== "" && v !== null && v !== undefined) q.set(k, v);
  const s = q.toString();
  return s ? `?${s}` : "";
}

function currentUrl() {
  return pathFor(S) + queryString();
}

async function navigate(patch = {}, { replace = false, keepScroll = false } = {}) {
  const prevModule = S.moduleId;
  Object.assign(S, patch);
  // 门槛改动即刻存档。这是客户自定义要"存下来"的那一步，
  // 不等任何保存按钮 —— 有按钮就会有人忘按，然后以为系统没存。
  if ("params" in patch) saveParamStore(S.params);
  if (patch.moduleId && patch.moduleId !== prevModule && !("pageId" in patch)) {
    const info = moduleInfo(patch.moduleId);
    S.pageId = info && info.pages && info.pages[0] ? info.pages[0].id : null;
    S.objectId = null;
    S.filters = {};
  }
  const url = currentUrl();
  const state = { y: keepScroll ? window.scrollY : 0 };
  if (replace) history.replaceState(state, "", url);
  else history.pushState(state, "", url);
  await render({ restoreY: state.y });
}

/* ---- 渲染 ------------------------------------------------------------- */

function renderNav() {
  dom.tabs.textContent = "";
  for (const m of S.modules) {
    dom.tabs.appendChild(
      el("button", {
        class: "wb-tab",
        type: "button",
        role: "tab",
        "data-degraded": m.degraded ? "1" : null,
        "aria-current": m.id === S.moduleId ? "page" : null,
        title: m.degraded ? `不可用：${m.reason || ""}` : m.label,
        text: m.label,
        onclick: () => {
          if (m.degraded) return;
          navigate({ moduleId: m.id });
        },
      })
    );
  }
}

function renderHead() {
  const info = moduleInfo(S.moduleId);

  // 只留基准日。脊椎口数与数据状态挪出这里 —— 它们是模块内部要交代的事，
  // 顶栏只回答"整页数据说到哪一天"。
  dom.state.textContent = "";
  if (S.meta && S.meta.as_of) {
    dom.state.appendChild(el("span", { html: `<b>${S.meta.as_of}</b>` }));
  }

  dom.pages.textContent = "";
  const ink = el("span", { class: "wb-tabs-ink", id: "wb-pages-ink" });
  ink.hidden = true;
  dom.pages.appendChild(ink);
  const pages = (info && info.pages) || [];
  // 只有一个页面时整行隐藏，否则会留一条空的居中轨道
  dom.head.hidden = pages.length <= 1;
  if (pages.length > 1) {
    for (const p of pages) {
      dom.pages.appendChild(
        el("button", {
          class: "wb-tab",
          type: "button",
          "aria-current": p.id === S.pageId ? "page" : null,
          text: p.label,
          onclick: () => navigate({ pageId: p.id, objectId: null }),
        })
      );
    }
    syncPageInk();
  }

  const hasParams = info && !info.degraded && (info.params || []).length > 0;
  dom.paramsBtn.hidden = !hasParams;
}

/* 把滑块摆到选中的那个 tab 底下。位置从实测的 offsetLeft/offsetWidth 来，
 * 不按页面名的字数估 —— 字数估法在中英混排和字号变化下必然错位。 */
function syncPageInk() {
  const ink = dom.pages.querySelector(".wb-tabs-ink");
  const on = dom.pages.querySelector('.wb-tab[aria-current="page"]');
  if (!ink || !on) {
    if (ink) ink.hidden = true;
    return;
  }
  ink.hidden = false;
  ink.style.left = `${on.offsetLeft}px`;
  ink.style.width = `${on.offsetWidth}px`;
}

function filterLabel(key) {
  // chip 上不能写 query 键名 —— 那是内部叫法。模块用 export const filters 声明中文标签。
  const impl = S.impls[S.moduleId];
  const decl = (impl && impl.filters) || [];
  const hit = decl.find((f) => f.key === key);
  return hit ? hit.label : key;
}

function renderFilters() {
  dom.filters.textContent = "";
  const entries = Object.entries(S.filters).filter(([, v]) => v !== "" && v !== null && v !== undefined);
  if (!entries.length) return;
  for (const [k, v] of entries) {
    dom.filters.appendChild(
      el("span", { class: "wb-chip" }, [
        el("span", { text: filterLabel(k) }),
        el("b", { text: String(v) }),
        el("button", {
          type: "button",
          "aria-label": `清除筛选 ${filterLabel(k)}`,
          text: "✕",
          onclick: () => {
            const next = { ...S.filters };
            delete next[k];
            navigate({ filters: next }, { keepScroll: true });
          },
        }),
      ])
    );
  }
  dom.filters.appendChild(
    el("button", {
      class: "wb-icon-btn",
      type: "button",
      text: "全部清除",
      onclick: () => navigate({ filters: {} }, { keepScroll: true }),
    })
  );
}

function placeholder(title, detail, kind) {
  return el("div", { class: "wb-placeholder", "data-kind": kind || null }, [
    el("h2", { text: title }),
    el("p", { text: detail || "" }),
  ]);
}

function makeCtx(moduleId) {
  S.moduleState[moduleId] = S.moduleState[moduleId] || {};
  return {
    moduleId,
    $, $$, el, fmt, nature, cond, aiMark, aiMarkHTML,
    // 配置方案下拉。ctx 自己传进去，模块不用管参数怎么写回。
    schemePicker(label) { return schemePicker(label, this); },
    state: S.moduleState[moduleId],          // 只有自己这一棵子树
    get shared() { return { ...S.shared }; }, // 共享上下文只读
    get filters() { return { ...S.filters }; },
    // 门槛参数只读一份、只写一处。Agent 配置页要改别的模块的阈值，
    // 走的仍然是这一套 —— 不给它另开一个存储，否则阈值就有两个真相来源。
    get params() { return { ...S.params }; },
    get allModules() { return S.modules.map((m) => ({ ...m })); },
    get objectId() { return S.objectId; },
    get pageId() { return S.pageId; },
    get asOf() { return S.meta ? S.meta.as_of : ""; },
    setShared(patch) { navigate({ shared: { ...S.shared, ...patch } }, { keepScroll: true }); },
    setFilters(patch) { navigate({ filters: { ...S.filters, ...patch } }, { keepScroll: true }); },
    setParams(patch) { navigate({ params: { ...S.params, ...patch } }, { keepScroll: true }); },
    open(objectId, pageId) { navigate({ objectId, pageId: pageId || S.pageId }); },
    // resource 可以带路径段，例如 api("child/" + encodeURIComponent(asin))。
    // 当前的筛选、共享上下文和参数会自动带上，模块不用自己拼 query。
    // 第三个参数给了就走 POST 并把它当 JSON 请求体发（服务端用 c.json() / c.arg() 取）。
    // 读一律用 GET；只有「要写东西」才用 POST。
    async api(resource, extra = {}, body = null) {
      const q = new URLSearchParams(queryString().slice(1));
      for (const [k, v] of Object.entries(extra)) if (v !== undefined && v !== null) q.set(k, v);
      const qs = q.toString();
      const url = `/api/${moduleId}/${resource}${qs ? "?" + qs : ""}`;
      const init = body == null
        ? undefined
        : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
      const res = await fetch(url, init);
      const payload = await res.json().catch(() => ({ error: "响应不是合法 JSON" }));
      if (!res.ok) throw new Error(payload.error || `接口返回 ${res.status}`);
      return payload;
    },
    drawer: { open: openDrawer, close: closeDrawer },
    pop: { show: showPop, close: closePop },
    placeholder,
  };
}

async function loadImpl(moduleId) {
  if (S.impls[moduleId]) return S.impls[moduleId];
  const impl = await import(`/modules/${moduleId}.js`);
  S.impls[moduleId] = impl;
  const css = `/modules/${moduleId}.css`;
  if (!$(`link[data-module-css="${moduleId}"]`)) {
    document.head.appendChild(el("link", { rel: "stylesheet", href: css, "data-module-css": moduleId }));
  }
  return impl;
}

async function render({ restoreY = null } = {}) {
  renderNav();
  renderHead();
  renderFilters();

  const info = moduleInfo(S.moduleId);
  if (!info) {
    dom.body.textContent = "";
    dom.body.appendChild(placeholder("没有可用模块", "modules/ 目录下没有发现任何模块", "error"));
    dom.main.dataset.rail = "0";
    return;
  }
  if (info.degraded) {
    dom.body.textContent = "";
    dom.body.appendChild(
      placeholder(`模块「${info.label}」当前不可用`, info.reason || "加载失败", "error")
    );
    dom.rail.textContent = "";
    dom.main.dataset.rail = "0";
    return;
  }

  // 切模块时先卸载上一个，让它清掉自己的定时器与监听
  if (S.mounted && S.mounted !== S.moduleId) {
    const prev = S.impls[S.mounted];
    try {
      if (prev && typeof prev.unmount === "function") prev.unmount();
    } catch (err) {
      console.error(`[${S.mounted}] unmount 出错`, err);
    }
    dom.rail.textContent = "";
    dom.body.textContent = "";
    S.mounted = null;
  }

  let impl;
  try {
    impl = await loadImpl(S.moduleId);
  } catch (err) {
    console.error(`[${S.moduleId}] 模块脚本加载失败`, err);
    dom.body.textContent = "";
    dom.body.appendChild(placeholder(`模块「${info.label}」加载失败`, String(err.message || err), "error"));
    return;
  }

  dom.rail.dataset.module = S.moduleId;
  dom.body.dataset.module = S.moduleId;
  syncRail(impl.usesRail);

  const ctx = makeCtx(S.moduleId);
  try {
    if (S.mounted !== S.moduleId) {
      dom.body.textContent = "";
      dom.body.appendChild(placeholder("正在加载", "读取模块数据"));
      await impl.mount({ rail: dom.rail, body: dom.body }, ctx);
      S.mounted = S.moduleId;
    } else if (typeof impl.render === "function") {
      await impl.render(ctx);
    }
  } catch (err) {
    console.error(`[${S.moduleId}] 渲染出错`, err);
    dom.body.textContent = "";
    dom.body.appendChild(placeholder(`模块「${info.label}」渲染出错`, String(err.message || err), "error"));
    return;
  }

  if (restoreY !== null) window.scrollTo({ top: restoreY });
  if (taskOpen && !taskBusy) renderTask();   // 面板跟着当前对象/页面走
}

/* ---- 浮层与抽屉：全站唯一实现。旧两个模块各写了一份，合并会互相抢当前打开的是谁。 --- */

let popOwner = null;

function showPop(anchor, content) {
  closePop();
  const pop = dom.pop;
  pop.textContent = "";
  pop.appendChild(typeof content === "string" ? document.createTextNode(content) : content);
  pop.hidden = false;
  const r = anchor.getBoundingClientRect();
  const pw = pop.offsetWidth;
  const left = Math.min(Math.max(8, r.left), window.innerWidth - pw - 8);
  pop.style.left = `${left + window.scrollX}px`;
  pop.style.top = `${r.bottom + 6 + window.scrollY}px`;
  popOwner = anchor;
}

function closePop() {
  dom.pop.hidden = true;
  dom.pop.textContent = "";
  popOwner = null;
}

function openDrawer(title, content, side) {
  dom.drawerTitle.textContent = title;
  dom.drawerBody.textContent = "";
  dom.drawerBody.appendChild(typeof content === "string" ? document.createTextNode(content) : content);
  dom.drawer.dataset.side = side === "left" ? "left" : "right";
  dom.drawer.hidden = false;
  dom.scrim.hidden = false;
}

function closeDrawer() {
  dom.drawer.hidden = true;
  dom.scrim.hidden = true;
  dom.drawerBody.textContent = "";
}

/* ---- 参数面板 --------------------------------------------------------- */

function openParams() {
  const info = moduleInfo(S.moduleId);
  if (!info || !(info.params || []).length) return;
  const groups = new Map();
  for (const p of info.params) {
    const g = p.group || "参数";
    if (!groups.has(g)) groups.set(g, []);
    groups.get(g).push(p);
  }
  const wrap = el("div");
  for (const [g, items] of groups) {
    wrap.appendChild(el("h3", { text: g, style: "font-size:13px;margin:16px 0 8px" }));
    for (const p of items) {
      const value = S.params[p.key] !== undefined ? S.params[p.key] : p.value;
      const input = el("input", {
        type: p.kind === "num" ? "number" : "text",
        value: String(value),
        min: p.lo,
        max: p.hi,
        step: p.step,
        style: "width:96px;font-family:var(--mono)",
        onchange: (e) => {
          navigate({ params: { ...S.params, [p.key]: e.target.value } }, { keepScroll: true });
        },
      });
      wrap.appendChild(
        el("label", { style: "display:flex;align-items:center;gap:8px;padding:4px 0;min-width:0" }, [
          el("span", { text: p.label, style: "flex:1 1 auto;min-width:0" }),
          input,
        ])
      );
    }
  }
  wrap.appendChild(
    el("button", {
      class: "wb-btn",
      type: "button",
      text: "恢复默认",
      style: "margin-top:16px",
      onclick: () => navigate({ params: {} }, { keepScroll: true }),
    })
  );
  openDrawer(`${info.label} · 参数`, wrap);
}

/* ---- AI 助手：全站唯一入口，反代到独立 Agent 服务（契约第 9 节） -------- */

/* ---- 槽位 6 任务面板：全站唯一 Agent 入口（契约第 9 节） -----------------
 *
 * agent 是任务执行器，不是对话。所以这里没有聊天输入框 —— 列的是"这个对象能跑
 * 什么任务、上次跑成什么样、过程是什么"。
 *
 * 两条归属规则写进了实现：
 *   1. 结论落在拥有该对象的模块页，面板只显示过程与指针，不渲染结论本体
 *   2. 落表是唯一产物通道，面板读模块的 run 路由，自己不持有结果
 *
 * 任务由模块在 MODULE["tasks"] 里声明，外壳零硬编码：
 *   { id, label, needs?: "object", run: "<模块路由名>", hint? }
 */

let taskOpen = false;
let taskBusy = false;
/* 运行中的 AbortController。取消只断开这一侧的等待 —— Agent 那边不会停，
   所以取消的提示必须把这件事说出来，否则运营会以为已经拦住了。 */
let taskAbort = null;
const REVEAL_MS = 220;      // 揭示节奏。放慢是为了可读，但显示的耗时永远是真实值。

/* ---- 左侧对象栏开合 -----------------------------------------------------
 * 栏是外壳拥有的（#wb-rail），所以这套开合做一次，五个模块全覆盖，模块零改动。
 *
 * 模式：**overlay 是默认**（王楠 2026-08-31 定）。玻璃浮层，和任务面板一套语言。
 *   ?rail=push 可切到另一种：展开时作为栅格列把内容推开、不遮数据。
 *
 * overlay 下默认**收起**：浮层展开会盖住第一屏主指标，开局就盖住不合理。
 * 想改成默认展开就把 RAIL_OPEN_DEFAULT 改成 true。
 */
const RAIL_OPEN_DEFAULT = { overlay: false, push: true };
const railMode =
  new URLSearchParams(location.search).get("rail") === "push" ? "push" : "overlay";
let railOpen = RAIL_OPEN_DEFAULT[railMode];

function syncRail(usesRail) {
  const on = usesRail !== false;
  const open = on && railOpen;
  dom.handleL.hidden = !on;
  dom.rail.hidden = !open;
  dom.main.dataset.railmode = open ? railMode : "off";
  // push 模式展开时才占一列；overlay 展开时是浮层，主区仍然满宽
  dom.main.dataset.rail = open && railMode === "push" ? "1" : "0";
  dom.handleL.dataset.state = open ? "open" : "closed";
  dom.handleL.setAttribute("aria-expanded", String(open));
  dom.handleLTxt.textContent = open ? "收起" : "对象";
  dom.handleL.title = open ? "收起对象栏" : "展开对象栏";
  // 手柄位置按栏的实际右边界算，不跟 --rail-w 写死耦合
  if (open) {
    const r = dom.rail.getBoundingClientRect();
    dom.handleL.style.left = `${Math.max(0, Math.round(r.right) - 1)}px`;
  } else {
    dom.handleL.style.left = "0px";
  }
}

function toggleRail() {
  railOpen = !railOpen;
  const impl = S.impls[S.moduleId];
  syncRail(impl ? impl.usesRail : true);
}

function taskDecl() {
  const info = moduleInfo(S.moduleId);
  return (info && !info.degraded && Array.isArray(info.tasks) && info.tasks) || [];
}

function openTask() {
  taskOpen = true;
  dom.task.hidden = false;
  dom.handle.hidden = true;
  dom.handle.setAttribute("aria-expanded", "true");
  renderTask();
}

function closeTask() {
  if (taskBusy) return;       // 跑到一半不收，否则过程看不到了
  taskOpen = false;
  dom.task.hidden = true;
  dom.handle.hidden = false;
  dom.handle.setAttribute("aria-expanded", "false");
}

function toggleTask() {
  if (taskOpen) closeTask();
  else openTask();
}

function stepRow(step) {
  const row = el("div", { class: "wb-step", "data-status": step.status || "完成" }, [
    el("span", { class: "wb-step-dot" }),
    el("span", { class: "wb-step-label", text: step.label || "" }),
  ]);
  if (step.detail) row.appendChild(el("div", { class: "wb-step-detail", text: step.detail }));
  // 数据来源用中文名。库里的表名（fact_* 这类）不上屏，映射在读取边界做。
  if (Array.isArray(step.sources) && step.sources.length) {
    row.appendChild(
      el("div", { class: "wb-step-src" }, step.sources.map((s) => el("span", { class: "wb-src", text: s })))
    );
  }
  return row;
}

/* 边跑边显示。触发那次调用**不 await** —— 它跑完才回（实测 87~107 秒），
   等它等于让面板整段时间只有一个不动的字。进度从模块声明的 `poll` 路由读，
   那是 Agent 分步落库的真实步骤，不是按固定节奏播出来的。

   用「起跑前的 run_id」区分这一次和上一次的结果：不看这个的话，poll 第一拍
   读到的是上次那条已完成的 run，面板会立刻宣布「运行完成」。 */
const POLL_MS = 1500;
const POLL_START_GRACE_MS = 25000;   // 这么久还没出现新 run 就当没开跑
const POLL_DEADLINE_MS = 600000;

async function pollTask(task, runUrl, qs, foot, traceHost) {
  const pollUrl = `/api/${S.moduleId}/${task.poll}${qs ? "?" + qs : ""}`;
  const readStatus = async () => {
    const r = await fetch(pollUrl, { signal: taskAbort.signal });
    return r.ok ? r.json() : null;
  };

  let beforeId = null;
  try { beforeId = ((await readStatus()) || {}).run?.run_id ?? null; } catch { /* 读不到就当没有 */ }

  // 发出去，不等。失败也不在这里报 —— 状态接口会说，报两遍会撞上同一件事两处说。
  fetch(runUrl, { signal: taskAbort.signal }).catch(() => {});

  const t0 = Date.now();
  let last = null;
  for (;;) {
    await new Promise((r) => setTimeout(r, POLL_MS));
    if (taskAbort.signal.aborted) throw Object.assign(new Error("aborted"), { name: "AbortError" });

    let s = null;
    try { s = await readStatus(); } catch (e) { if (e.name === "AbortError") throw e; }
    const run = (s && s.run) || {};
    const elapsed = Date.now() - t0;

    // 刷新页面后重新点击时，Agent 服务会复用仍在运行的任务。它的 run_id
    // 与起跑前相同，但「加载中」说明这不是上一条终态，应该继续跟踪。
    const reusedRunning = run.run_id && run.run_id === beforeId && run.status === "加载中";
    if (!run.run_id || (run.run_id === beforeId && !reusedRunning)) {
      if (run.status === "失败" && run.message) {
        foot.textContent = "";
        foot.appendChild(el("span", { text: `没有开跑：${run.message}`, style: "color:var(--alert)" }));
        return null;
      }
      if (elapsed > POLL_START_GRACE_MS) {
        foot.textContent = "";
        foot.appendChild(el("span", { text: "没有开跑 —— 状态接口里没有出现新的运行记录", style: "color:var(--alert)" }));
        return null;
      }
      continue;
    }

    last = s;
    // 每拍整块重画。12 行重画一次很便宜，比做增量少一整类「漏掉一步」的错。
    await renderTrace(traceHost, s.steps || [], { live: false });
    const live = foot.querySelector(".wb-task-item-sub");
    if (live && run.current_step && run.total_steps) {
      const now = (s.steps || []).find((x) => x.status === "加载中");
      live.textContent = `第 ${run.current_step}/${run.total_steps} 步`
        + (now && now.label ? ` · ${now.label}` : "");
    }
    if (run.status === "完成" || run.status === "失败") return last;
    if (elapsed > POLL_DEADLINE_MS) {
      foot.textContent = "";
      foot.appendChild(el("span", { text: "等太久了，停止跟踪。Agent 可能还在跑，刷新页面看结果", style: "color:var(--alert)" }));
      return null;
    }
  }
}

async function renderTrace(host, steps, { live }) {
  host.textContent = "";
  for (const step of steps) {
    host.appendChild(stepRow(step));
    host.scrollTop = host.scrollHeight;
    if (live) await new Promise((r) => setTimeout(r, REVEAL_MS));
  }
}

function runSummary(run) {
  const bits = [];
  if (run.run_date || run.created_at) bits.push(`运行于 ${run.run_date || run.created_at}`);
  if (run.data_as_of) bits.push(`数据截止 ${run.data_as_of}`);
  if (run.model_version) bits.push(run.model_version);
  return bits.join(" · ");
}

async function runTask(task, foot, traceHost) {
  if (taskBusy) {
    // 不静默 return —— 静默会让人以为按钮坏了，然后反复点。
    const note = foot.querySelector(".wb-task-note") || el("span", { class: "wb-task-note" });
    note.textContent = "这次还在跑，等它跑完或者先取消";
    if (!note.parentNode) foot.appendChild(note);
    return;
  }
  taskBusy = true;
  taskAbort = new AbortController();
  foot.hidden = false;
  foot.textContent = "";
  /* 运行中给一个会动的东西，但**不给秒数**。真实进度要等 Agent 侧把步骤
     分段落库才拿得到（需求见 01-方案与数据需求/13-需求预测Agent分段运行需求.md
     R1/R2）；在那之前任何进度条或百分比都是猜的，而一个不动的「正在运行…」
     在实测 107 秒的运行里就是「卡死」。 */
  foot.appendChild(
    el("span", { class: "wb-task-live" }, [
      el("span", { class: "wb-task-pulse" }),
      el("span", { class: "wb-task-item-sub", text: "正在运行" }),
    ])
  );
  foot.appendChild(
    el("button", {
      class: "wb-btn",
      type: "button",
      text: "取消",
      onclick: () => { if (taskAbort) taskAbort.abort(); },
    })
  );
  traceHost.textContent = "";
  try {
    const q = new URLSearchParams(queryString().slice(1));
    if (S.objectId) q.set("object", S.objectId);
    const qs = q.toString();
    const runUrl = `/api/${S.moduleId}/${task.run}${qs ? "?" + qs : ""}`;

    let body;
    if (task.poll) {
      body = await pollTask(task, runUrl, qs, foot, traceHost);
      if (!body) return;                       // 取消 / 没开跑，pollTask 已经把话说完了
    } else {
      const res = await fetch(runUrl, { signal: taskAbort.signal });
      body = await res.json().catch(() => ({ error: "响应不是合法 JSON" }));
      if (!res.ok) throw new Error(body.error || `接口返回 ${res.status}`);
      await renderTrace(traceHost, body.steps || [], { live: true });
    }

    foot.textContent = "";
    const run = body.run || {};
    const bad = run.status && run.status !== "完成" && run.status !== "正常";
    foot.appendChild(el("span", { text: bad ? `运行未完成：${run.status}` : "运行完成" }));
    // 成功也可能只是一个明确收口的 Smoke，而不是业务结果已发布。
    // 服务端给了 message 就必须显示，不能只在失败时显示。
    if (run.message) foot.appendChild(el("span", { class: "wb-task-note", text: run.message }));
    const c = cond(bad ? "失败" : "正常");
    if (c) foot.appendChild(c);
    // 结论不在面板里渲染 —— 给一个指针，点了跳到拥有该对象的模块页
    if (run.object_id) {
      foot.appendChild(
        el("button", {
          class: "wb-btn",
          type: "button",
          text: "查看结论",
          onclick: () => { closeTask(); navigate({ objectId: run.object_id }); },
        })
      );
    }
    /* 这里原先报「各步 duration_ms 之和」。那个口径本身没错（墙钟含 REVEAL_MS
       的揭示节奏，报墙钟就是拿节奏冒充数字），错在另一头：**真实耗时没被记**。
       实测一次运行 107 秒，九步合计 5.7 毫秒 —— 模型耗时不属于任何一步。
       在屏幕上写「2 ms」会让人以为这次只跑了两毫秒，所以先不报。
       Agent 侧把耗时归到步骤之后（13 号文 R5）再加回来，样式仍在
       base.css 的 .wb-task-elapsed。 */
  } catch (err) {
    foot.textContent = "";
    if (err && err.name === "AbortError") {
      // 取消只停了等待。Agent 仍在跑、跑完仍会写库，这话必须说出来。
      foot.appendChild(el("span", { text: "已取消等待。Agent 那边还在跑，跑完会写进结果库，刷新页面就能看到" }));
    } else {
      foot.appendChild(el("span", { text: `运行失败：${err.message || err}`, style: "color:var(--alert)" }));
    }
  } finally {
    taskBusy = false;
    taskAbort = null;
  }
}

function renderTask() {
  if (!taskOpen) return;
  const info = moduleInfo(S.moduleId);
  dom.taskTitle.textContent = info ? `${info.label} · 任务` : "任务";
  dom.taskScope.textContent = S.objectId
    ? S.objectId
    : (info && (info.pages || []).find((p) => p.id === S.pageId) || {}).label || "";

  const body = dom.taskBody;
  body.textContent = "";
  const tasks = taskDecl();
  if (!tasks.length) {
    dom.taskFoot.hidden = true;
    body.appendChild(placeholder("此页面暂无可运行任务", "任务由模块声明后出现在这里"));
    return;
  }

  // footer 钉在面板底部、在滚动区之外 —— 运行状态和「查看结论」是最该看见的，
  // 第一版把它塞进 body 里，执行过程一长就被滚走了。
  const foot = dom.taskFoot;
  foot.textContent = "";
  foot.hidden = true;
  const traceHost = el("div");

  body.appendChild(el("div", { class: "wb-task-sect", text: "可运行" }));
  for (const t of tasks) {
    const needsObject = t.needs === "object";
    const blocked = needsObject && !S.objectId;
    body.appendChild(
      el("div", { class: "wb-task-item" }, [
        el("div", { class: "wb-task-item-main" }, [
          el("div", { class: "wb-task-item-label", text: t.label || t.id }),
          el("div", {
            class: "wb-task-item-sub",
            text: blocked ? "先在页面上选一个对象" : t.hint || "",
          }),
        ]),
        el("button", {
          class: "wb-btn",
          "data-kind": blocked ? null : "primary",
          type: "button",
          disabled: blocked || null,
          text: "运行",
          onclick: () => runTask(t, foot, traceHost),
        }),
      ])
    );
  }

  body.appendChild(el("div", { class: "wb-task-sect", text: "执行过程" }));
  body.appendChild(traceHost);
  traceHost.appendChild(
    el("div", { class: "wb-task-item-sub", text: "点上面的运行按钮，过程会逐步出现在这里" })
  );
}

/* ---- 启动 ------------------------------------------------------------- */

async function boot() {
  // 方案表预载。模块渲染时同步取用，所以要在挂载之前拿到。
  // 取不到不拦启动 —— loadSchemes 内部已兜住，返回空表。
  await loadSchemes();
  Object.assign(dom, {
    tabs: $("#wb-tabs"),
    head: $("#wb-head"),
    pages: $("#wb-pages"),
    state: $("#wb-state"),
    filters: $("#wb-filters"),
    main: $("#wb-main"),
    rail: $("#wb-rail"),
    body: $("#wb-body"),
    scrim: $("#wb-scrim"),
    drawer: $("#wb-drawer"),
    drawerTitle: $("#wb-drawer-title"),
    drawerBody: $("#wb-drawer-body"),
    pop: $("#wb-pop"),
    paramsBtn: $("#wb-params-btn"),
    handle: $("#wb-handle"),
    task: $("#wb-task"),
    taskTitle: $("#wb-task-title"),
    taskScope: $("#wb-task-scope"),
    taskBody: $("#wb-task-body"),
    taskFoot: $("#wb-task-foot"),
    handleL: $("#wb-handle-l"),
    handleLTxt: $("#wb-handle-l-txt"),
  });

  dom.handleL.addEventListener("click", toggleRail);
  // 栏宽会随内容变，手柄位置得跟着走；滑块位置也随换行/字号变
  window.addEventListener("resize", () => {
    const impl = S.impls[S.moduleId];
    if (impl) syncRail(impl.usesRail);
    syncPageInk();
  });

  dom.scrim.addEventListener("click", closeDrawer);
  $("#wb-drawer-close").addEventListener("click", closeDrawer);
  dom.paramsBtn.addEventListener("click", openParams);
  dom.handle.addEventListener("click", openTask);
  $("#wb-task-close").addEventListener("click", closeTask);
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    if (!dom.pop.hidden) closePop();
    else if (!dom.drawer.hidden) closeDrawer();
    else if (taskOpen) closeTask();
  });
  document.addEventListener("click", (e) => {
    if (!dom.pop.hidden && popOwner && !dom.pop.contains(e.target) && !popOwner.contains(e.target)) closePop();
    // 面板是非模态的（无遮罩，页面照常可点），所以收起靠"点在别处"。
    // 用 click 不用 hover：运营的鼠标一直在密集表格上移动，hover 会乱弹。
    // 顶栏那个"任务"按钮已去掉，入口只剩右缘常驻手柄，所以这里也只排除手柄。
    if (taskOpen && !dom.task.contains(e.target) && !dom.handle.contains(e.target)) {
      closeTask();
    }
  });

  try {
    const [meta, mods] = await Promise.all([
      fetch("/api/meta").then((r) => r.json()),
      fetch("/api/modules").then((r) => r.json()),
    ]);
    S.meta = meta;
    S.modules = mods.modules || [];
  } catch (err) {
    dom.body.textContent = "";
    dom.body.appendChild(placeholder("无法连接工作台服务", String(err.message || err), "error"));
    return;
  }

  applyUrl();
  await render({ restoreY: 0 });
  history.replaceState({ y: 0 }, "", currentUrl());

  window.addEventListener("popstate", async (e) => {
    applyUrl();
    await render({ restoreY: (e.state && e.state.y) || 0 });
  });
}

function applyUrl() {
  const route = parsePath(location.pathname);
  Object.assign(S, route);
  const q = new URLSearchParams(location.search);
  const shared = {};
  const filters = {};
  const params = {};
  for (const [k, v] of q.entries()) {
    // 会话开关不是业务筛选，别让它们变成筛选 chip（之前 "tune 1 ✕" 就是这么漏出来的）
    if (SESSION_FLAGS.includes(k)) continue;
    if (k.includes(".")) params[k] = v;
    else if (["site", "from", "to"].includes(k)) shared[k] = v;
    else filters[k] = v;
  }
  S.shared = shared;
  S.filters = filters;
  // 门槛参数存档：URL 没写到的键，用本机存过的值补上。
  // 放在外壳而不是 Agent 配置模块里 —— 客户改过的门槛必须在所有页面都生效，
  // 只在配置页 mount 时套用的话，直接进业务页就回默认了（实测过这个错）。
  // URL 写明的键优先：分享出去的链接仍然精确复现它点名的那些参数。
  S.params = { ...loadParamStore(), ...params };
}

/* ---- 门槛参数的本机存档 -------------------------------------------------
 * 存的是"客户改过哪些键"，不是参数本身的第二份定义 —— 范围、标签、默认值
 * 仍然只在各模块的 MODULE["params"] 里。存档里的陌生键在读取时忽略。 */
const PARAM_STORE = "wb.params.overrides";

function loadParamStore() {
  try {
    const raw = JSON.parse(localStorage.getItem(PARAM_STORE) || "{}");
    const out = {};
    for (const [k, v] of Object.entries(raw)) {
      if (k.includes(".") && v !== "" && v !== null && v !== undefined) out[k] = v;
    }
    return out;
  } catch {
    return {};                                     // 存档坏了就当没存过，不该崩
  }
}

function saveParamStore(params) {
  try {
    const out = {};
    for (const [k, v] of Object.entries(params || {})) {
      if (v !== "" && v !== null && v !== undefined) out[k] = v;
    }
    localStorage.setItem(PARAM_STORE, JSON.stringify(out));
  } catch {
    /* 隐私模式下写不进，功能降级为只在本次会话有效 */
  }
}

boot();
