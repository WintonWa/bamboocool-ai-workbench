/* Agent 配置 · 前端模块
 *
 * 展现形式参考 Kiro 的 Agent 列表：卡片网格 + 头像 + 状态徽标 + 分隔线 +
 * 2×2 带标签的字段区 + 末尾一张虚线「新建」卡。点卡片进详情。
 *
 * 与 Kiro 有一处刻意不同：**名称与值不用等宽字体。**
 * 视觉基准要则第二节明令全站只用系统无衬线，需要数字列对齐用 tabular-nums，
 * 门禁 G22 也在守这条。要换回等宽得先改要则和门禁，不是这里私自开口子。
 *
 * 另两条约束沿用上一版：
 * - 不新建阈值存储。值来自各模块 MODULE["params"]，改值走 ctx.setParams。
 * - 存档归外壳（shell.js 的 PARAM_STORE），不在这个模块里 ——
 *   客户改过的门槛必须在所有页面生效，实测踩过放在模块里的错。
 */

export const id = "agentcfg";
export const apiVersion = 1;
export const usesRail = false;

/* 输出记录页的路由段。写成常量是因为它同时是 MODULE["pages"] 里的页面 id
 * 与 URL 里那一段，两处必须一致。 */
const RUNS = "runs";

/* 筛选项的中文标签。外壳的 chip 拿不到声明就会把 query 键名摆到屏上（G18）。
 * 值也用中文 Agent 名而不是 id —— chip 上显示的就是这个值。 */
export const filters = [{ key: "agent", kind: "select", label: "Agent" }];

/* 深链：/agentcfg 是网格，/agentcfg/<agentId> 是详情，/agentcfg/runs 是输出记录。
 * 第二页不带对象（详情走抽屉），所以 runs 后面不再接段。
 * "list" 也显式认一下：外壳的 pathFor 会把首页 id 从 URL 里省掉，
 * 但 /agentcfg/list 是门禁 G16 会直接访问的地址，不接住它会被当成一个叫 list 的 Agent。 */
export function parsePath(segments) {
  const head = segments[0] || "";
  if (head === RUNS) return { pageId: RUNS, objectId: null };
  if (head === "" || head === "list") return { pageId: "list", objectId: null };
  return { pageId: "list", objectId: decodeURIComponent(head) };
}

export function pathFor({ pageId, objectId }) {
  if (pageId === RUNS) return RUNS;
  return objectId ? encodeURIComponent(objectId) : "";
}

let host = null;
let cache = null;
let runsCache = null;

export async function mount(slots, ctx) {
  host = slots;
  await render(ctx);
}

export function unmount() {
  host = null;
  cache = null;
  runsCache = null;
}

/** 归属模块的中文名。owner 是模块 id，上屏要用外壳已经给过的 label —— 
 * 模块 id 是内部叫法，不上屏。 */
function ownerLabel(ctx, owner) {
  const hit = (ctx.allModules || []).find((m) => m.id === owner);
  return hit ? hit.label : owner;
}

/* ---- 头像 --------------------------------------------------------------
 * Kiro 用的是像素小人。这里不引任何图片资源，按 id 算一个确定的像素方格：
 * 同一个 Agent 永远是同一张脸，改名才会变。5×5 左右对称，所以看起来像个东西
 * 而不是随机噪点。 */

function hash(s) {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function avatar(ctx, seed, size) {
  const h = hash(seed);
  const hue = h % 360;
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 5 5");
  svg.setAttribute("width", String(size));
  svg.setAttribute("height", String(size));
  svg.setAttribute("class", "agc-ava");
  svg.setAttribute("aria-hidden", "true");
  const bg = document.createElementNS(svg.namespaceURI, "rect");
  bg.setAttribute("width", "5");
  bg.setAttribute("height", "5");
  bg.setAttribute("fill", `hsl(${hue} 42% 92%)`);
  svg.appendChild(bg);
  const ink = `hsl(${hue} 38% 34%)`;
  let bits = h;
  for (let col = 0; col < 3; col++) {
    for (let row = 0; row < 5; row++) {
      bits = Math.imul(bits, 48271) >>> 0;
      if ((bits >>> 16) % 100 < 46) continue;
      for (const c of col === 2 ? [2] : [col, 4 - col]) {
        const r = document.createElementNS(svg.namespaceURI, "rect");
        r.setAttribute("x", String(c));
        r.setAttribute("y", String(row));
        r.setAttribute("width", "1");
        r.setAttribute("height", "1");
        r.setAttribute("fill", ink);
        svg.appendChild(r);
      }
    }
  }
  return svg;
}

/* ---- 取数 -------------------------------------------------------------- */

/** 把所有模块声明的参数摊平成 key -> 声明，供门槛区查表。 */
function paramIndex(ctx) {
  const idx = {};
  for (const m of ctx.allModules) {
    for (const p of m.params || []) idx[p.key] = { ...p, moduleId: m.id, moduleLabel: m.label };
  }
  return idx;
}

/** 被改过 = 当前值与模块声明的默认值不同。以声明为基准，不另存一份基准。 */
function changedKeys(ctx, idx) {
  return Object.keys(idx).filter((k) => {
    const cur = ctx.params[k];
    if (cur === undefined || cur === "") return false;
    return String(cur) !== String(idx[k].default);
  });
}

/* ---- 渲染入口 ---------------------------------------------------------- */

export async function render(ctx) {
  if (!host) return;
  if (ctx.pageId === RUNS) return renderRuns(ctx);
  return renderAgents(ctx);
}

async function renderAgents(ctx) {
  const body = host.body;
  body.textContent = "";
  body.appendChild(ctx.el("div", { class: "agc-loading", text: "读取 Agent 登记表" }));

  let data;
  try {
    data = cache || (cache = await ctx.api("agents"));
  } catch (e) {
    body.textContent = "";
    body.appendChild(ctx.placeholder("读不到 Agent 登记表", String(e.message || e), "error"));
    return;
  }

  const idx = paramIndex(ctx);
  body.textContent = "";

  const one = ctx.objectId && data.agents.find((a) => a.id === ctx.objectId);
  if (ctx.objectId && !one) {
    body.appendChild(ctx.placeholder("没有这个 Agent", `登记表里找不到 ${ctx.objectId}`, "empty"));
    return;
  }
  if (one) {
    body.appendChild(detail(ctx, one, idx, data.triggers));
    return;
  }
  body.appendChild(grid(ctx, data, idx));
}

/* ---- 网格 -------------------------------------------------------------- */

function grid(ctx, data, idx) {
  const { el } = ctx;
  const changed = changedKeys(ctx, idx);
  const pending = data.agents.filter((a) => a.status === "待声明").length;

  const wrap = el("div", { class: "agc-wrap" });

  wrap.appendChild(
    el("section", { class: "agc-top" }, [
      el("div", { class: "agc-h1", text: "Agent 配置" }),
      el("p", { class: "agc-lede", text: "登记我们现在有哪些 Agent、每个判断什么、受哪些门槛约束。点卡片改门槛。" }),
      el("div", { class: "agc-sum" }, [
        el("span", {}, [el("b", { text: String(data.agents.length) }), " 个 Agent"]),
        el("span", {}, [el("b", { text: String(pending) }), " 个分析方式待定"]),
        el("span", {}, [el("b", { text: String(Object.keys(idx).length) }), " 个门槛可改"]),
        el("span", {}, [el("b", { text: String(changed.length) }), " 个已被改过"]),
      ]),
    ])
  );

  const cards = el("div", { class: "agc-grid" });
  for (const a of data.agents) cards.appendChild(cardOf(ctx, a, idx, data.triggers));
  cards.appendChild(newCard(ctx));
  wrap.appendChild(cards);
  return wrap;
}

function field(ctx, label, value, suffix, suffixKind) {
  const { el } = ctx;
  return el("div", { class: "agc-f" }, [
    el("div", { class: "agc-f-k", text: label }),
    el("div", { class: "agc-f-v" }, [
      value || "—",
      suffix ? el("span", { class: "agc-f-sfx", "data-kind": suffixKind || null, text: suffix }) : null,
    ]),
  ]);
}

function cardOf(ctx, a, idx, triggers) {
  const { el } = ctx;
  const keys = (a.thresholds || []).filter((k) => idx[k]);
  const mine = keys.filter((k) => {
    const cur = ctx.params[k];
    return cur !== undefined && cur !== "" && String(cur) !== String(idx[k].default);
  });

  const open = () => ctx.open(a.id);

  return el("article", { class: "agc-card", "data-status": a.status, tabindex: "0",
                         role: "link", onclick: open,
                         onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } } }, [
    el("div", { class: "agc-card-top" }, [
      avatar(ctx, a.id, 44),
      el("div", { class: "agc-idbox" }, [
        el("div", { class: "agc-nameline" }, [
          el("span", { class: "agc-name", text: a.label }),
          el("span", { class: "agc-badge", "data-status": a.status, text: a.status }),
        ]),
        el("p", { class: "agc-desc", text: a.desc || "" }),
      ]),
    ]),
    el("div", { class: "agc-rule" }),
    el("div", { class: "agc-fields" }, [
      field(ctx, "归属模块", ownerLabel(ctx, a.owner), "声明在登记表", "warn"),
      field(ctx, "触发方式", (a.trigger || []).map((t) => triggers[t] || t).join(" · ")),
      field(ctx, "模型", a.model_version || "未定", a.model_version ? null : "待接通", "warn"),
      field(ctx, "数据门槛", `${keys.length} 项`, mine.length ? `已改 ${mine.length}` : null, "on"),
    ]),
  ]);
}

/** 末尾那张虚线卡。新建 Agent 是往模块里加一段声明，所以这里说清怎么加。 */
function newCard(ctx) {
  const { el } = ctx;
  return el("button", {
    class: "agc-new",
    type: "button",
    onclick: () =>
      ctx.drawer.open(
        "新建 Agent",
        el("div", { class: "agc-howto", "data-module": "agentcfg" }, [
          el("p", { text: "Agent 不在界面上新建，而是由它所属的模块声明 —— 和参数、任务一样，谁的东西谁声明，外壳不持有清单。" }),
          el("p", { text: "在该模块的 module.py 里加一段：" }),
          el("pre", { class: "agc-pre", text: SNIPPET }),
          el("p", { text: "三条硬要求，门禁 G25 逐条核：thresholds 只能写真实存在的参数键（写错一个字母那一项会静默消失）；判断与算术的分界照 07 契约切；没拍定的字段留空数组，不要编。" }),
          el("p", { text: "完整形状见 00-通用方法与规范/02-模块接入契约.md v1.4 第 8.1 节。" }),
        ]),
        "right"
      ),
  }, [el("span", { class: "agc-new-plus", text: "+" }), el("span", { text: "新建 Agent" })]);
}

const SNIPPET = `MODULE["agents"] = [
    {
        "id": "demand-forecast",
        "label": "需求预测",
        "desc": "一句话说清它干什么",
        "owner": "inventory",        # 必须等于本模块 id
        "status": "未接通",
        "model_version": None,
        "trigger": ["weekly", "manual"],
        "judges": [...],             # 普通代码做不了的判断
        "computed": [...],           # 确定性算术，留在工作台
        "needs": [...],              # 缺一项就不该开跑
        "outputs": [...],            # 中文，不写表名
        "thresholds": ["inv.safety_days_override"],
        "contract": "01-方案与数据需求/07-预测Agent接口契约.md",
    },
]`;

/* ---- 详情 -------------------------------------------------------------- */

function detail(ctx, a, idx, triggers) {
  const { el } = ctx;
  const wrap = el("div", { class: "agc-wrap" });

  wrap.appendChild(
    el("button", { class: "agc-back", type: "button", text: "← 全部 Agent",
                   onclick: () => ctx.open(null) })
  );

  wrap.appendChild(
    el("section", { class: "agc-dhead" }, [
      avatar(ctx, a.id, 56),
      el("div", { class: "agc-idbox" }, [
        el("div", { class: "agc-nameline" }, [
          el("span", { class: "agc-dname", text: a.label }),
          el("span", { class: "agc-badge", "data-status": a.status, text: a.status }),
        ]),
        el("p", { class: "agc-desc", text: a.desc || "" }),
      ]),
    ])
  );

  wrap.appendChild(
    el("div", { class: "agc-fields agc-fields-4" }, [
      field(ctx, "归属模块", ownerLabel(ctx, a.owner), "声明在登记表", "warn"),
      field(ctx, "触发方式", (a.trigger || []).map((t) => triggers[t] || t).join(" · ")),
      field(ctx, "模型", a.model_version || "未定", a.model_version ? null : "待接通", "warn"),
      field(ctx, "契约", a.contract ? a.contract.split("/").pop() : "未立"),
    ])
  );

  wrap.appendChild(block(ctx, "Agent 判断什么", a.judges,
    "这一段还没拍定。它决定客户买到的是判断还是阈值命中，所以不替它写。"));
  wrap.appendChild(block(ctx, "工作台自己算什么", a.computed,
    "确定性算术不进 Agent。算术留在工作台，下面的门槛才能改完立刻重算。"));
  wrap.appendChild(block(ctx, "需要什么上下文", a.needs, "缺一项就不该开跑。"));
  wrap.appendChild(block(ctx, "产出什么", a.outputs, "产出契约未定。"));

  if (a.note) wrap.appendChild(el("p", { class: "agc-note", text: a.note }));

  wrap.appendChild(thresholds(ctx, a, idx));
  wrap.appendChild(schemeBlock(ctx, a, idx));
  return wrap;
}

function block(ctx, title, items, emptyHint) {
  const { el } = ctx;
  const kids = [el("div", { class: "agc-f-k", text: title })];
  if (!items || !items.length) kids.push(el("div", { class: "agc-empty", text: emptyHint }));
  else kids.push(el("ul", { class: "agc-ul" }, items.map((t) => el("li", { text: t }))));
  return el("section", { class: "agc-block" }, kids);
}

/* ---- 配置方案（方案一 / 方案二 / 方案三…） ----------------------------
 *
 * 2026-08-31 会上王楠要的：每个 Agent 各自能存几套配置，用得到这个 Agent 的
 * 板块上给个下拉切。这里是这些方案的管理处。
 *
 * 「另存为方案」存的是**当前门槛的现值**（下面那一片改完就按现值存），
 * 不是让人在这里再填一遍值 —— 填两遍必然会有一遍是错的。
 */

async function fetchSchemes(agentId) {
  try {
    const r = await fetch("/api/agentcfg/schemes");
    if (!r.ok) throw new Error(String(r.status));
    const d = await r.json();
    return (d.agents || []).find((x) => x.id === agentId) || null;
  } catch {
    return null;
  }
}

function schemeBlock(ctx, a, idx) {
  const { el } = ctx;
  const keys = (a.thresholds || []).filter((k) => idx[k]);
  const wrap = el("div", { class: "agc-schemes" }, [
    el("div", { class: "agc-f-k", text: "配置方案" }),
  ]);

  if (!keys.length) {
    wrap.appendChild(el("p", { class: "agc-note",
      text: "这个 Agent 没有可调门槛，所以没有方案可存。" }));
    return wrap;
  }

  const list = el("div", { class: "agc-scheme-list", text: "读取方案…" });
  wrap.appendChild(list);

  const redraw = async () => {
    const info = await fetchSchemes(a.id);
    list.textContent = "";
    if (!info) {
      list.appendChild(el("div", { class: "agc-bad", text: "读不到方案清单" }));
      return;
    }
    for (const s of info.schemes || []) {
      const vals = Object.entries(s.values || {})
        .map(([k, v]) => `${(idx[k] && idx[k].label) || k} ${v}`).join("　");
      list.appendChild(el("div", { class: "agc-scheme-row" }, [
        el("span", { class: "agc-scheme-name", text: s.name }),
        el("span", { class: "agc-scheme-vals", text: vals || "（无取值）" }),
        s.builtin
          ? el("span", { class: "agc-scheme-tag", text: "代码里的默认值，不可改" })
          : el("button", { class: "agc-scheme-del", type: "button",
              title: "删掉这个方案",
              onclick: async () => {
                await fetch("/api/agentcfg/scheme-delete", {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ agent_id: a.id, id: s.id }),
                });
                redraw();
              } }, "删除"),
      ]));
    }

    /* 另存为。取当前门槛现值 —— ctx.params 里没有的键回落到声明的默认值，
       否则没动过的门槛会存成空。 */
    const input = el("input", { class: "agc-in agc-scheme-in", type: "text",
      placeholder: "给这套门槛起个名，例如「方案二 激进备货」", maxlength: "24" });
    const msg = el("span", { class: "agc-scheme-msg" });
    const save = el("button", { class: "agc-scheme-save", type: "button" },
      "把当前门槛另存为方案");
    save.addEventListener("click", async () => {
      const name = (input.value || "").trim();
      if (!name) { msg.textContent = "先起个名字"; return; }
      const cur = ctx.params || {};
      const values = {};
      for (const k of keys) {
        const v = cur[k];
        values[k] = (v === undefined || v === null || v === "") ? idx[k].default : v;
      }
      msg.textContent = "保存中…";
      const r = await fetch("/api/agentcfg/scheme-save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ agent_id: a.id, name, values }),
      }).then((x) => x.json()).catch(() => ({ ok: false, message: "网络错误" }));
      msg.textContent = r.ok ? "已保存" : (r.message || "保存失败");
      if (r.ok) { input.value = ""; redraw(); }
    });
    list.appendChild(el("div", { class: "agc-scheme-add" }, [input, save, msg]));
  };
  redraw();
  return wrap;
}

function thresholds(ctx, a, idx) {
  const { el } = ctx;
  const keys = (a.thresholds || []).filter((k) => idx[k]);
  const missing = (a.thresholds || []).filter((k) => !idx[k]);
  const kids = [el("div", { class: "agc-f-k", text: `数据门槛边界 · ${keys.length} 项可改` })];

  if (missing.length) {
    kids.push(el("div", { class: "agc-bad", text: `声明里有 ${missing.length} 个键在模块里不存在：${missing.join(" ")}` }));
  }

  for (const key of keys) {
    const p = idx[key];
    const cur = ctx.params[key] !== undefined && ctx.params[key] !== "" ? ctx.params[key] : p.value;
    const isChanged = String(cur) !== String(p.default);

    const control =
      p.kind === "enum"
        ? el("select", { class: "agc-in", onchange: (e) => ctx.setParams({ [key]: e.target.value }) },
            (p.choices || []).map((c) =>
              el("option", { value: c.value, text: c.label, selected: String(c.value) === String(cur) })))
        : el("input", {
            class: "agc-in",
            type: p.kind === "bool" ? "checkbox" : "number",
            value: p.kind === "bool" ? undefined : String(cur),
            checked: p.kind === "bool" ? String(cur) === "1" || cur === true : undefined,
            min: p.lo, max: p.hi, step: p.step,
            onchange: (e) =>
              ctx.setParams({ [key]: p.kind === "bool" ? (e.target.checked ? "1" : "0") : e.target.value }),
          });

    kids.push(
      el("label", { class: "agc-row", "data-changed": isChanged ? "1" : null }, [
        el("span", { class: "agc-lbl" }, [p.label, el("span", { class: "agc-mod", text: p.moduleLabel })]),
        el("span", { class: "agc-range", text: p.kind === "num" ? `${p.lo} ~ ${p.hi}` : p.kind === "bool" ? "开 / 关" : "枚举" }),
        control,
        el("span", { class: "agc-dflt", text: isChanged ? `默认 ${p.default}` : "" }),
      ])
    );
    if (p.note) kids.push(el("div", { class: "agc-hint", text: p.note }));
  }

  kids.push(
    el("div", { class: "agc-acts" }, [
      el("button", { class: "agc-btn", type: "button", text: "复制这份配置",
                     onclick: (e) => copyConfig(ctx, a, idx, e.target) }),
      el("button", { class: "agc-btn", type: "button", text: "恢复声明默认",
                     onclick: () => {
                       const clear = {};
                       for (const k of keys) clear[k] = "";
                       ctx.setParams(clear);
                     } }),
    ])
  );
  return el("section", { class: "agc-thr" }, kids);
}

/* 把当前门槛导出成可粘贴的文字。demo 阶段配置以文字体现，和前端文件一样 ——
 * 所以要能一键取到"客户定成什么样了"这段文本，而不是只存在某台机器的浏览器里。 */
function copyConfig(ctx, a, idx, btn) {
  const keys = (a.thresholds || []).filter((k) => idx[k]);
  const lines = [
    `# Agent ${a.label}（${a.id}）· 归属 ${a.owner}`,
    `# 数据基准日 ${ctx.asOf}　门槛 ${keys.length} 项，标 ← 的是被改过的`,
    "",
  ];
  for (const k of keys) {
    const p = idx[k];
    const cur = ctx.params[k] !== undefined && ctx.params[k] !== "" ? ctx.params[k] : p.value;
    const mark = String(cur) !== String(p.default) ? `   ← 原 ${p.default}` : "";
    lines.push(`${k} = ${cur}${mark}    # ${p.label}`);
  }
  const txt = lines.join("\n");
  const done = (word) => {
    const old = btn.textContent;
    btn.textContent = word;
    setTimeout(() => { btn.textContent = old; }, 1600);
  };
  navigator.clipboard.writeText(txt).then(() => done("已复制"), () => {
    ctx.drawer.open("这份配置", ctx.el("pre", { class: "agc-pre", text: txt }), "right");
    done("见侧页");
  });
}


/* ======================================================================
 * 第二页 · Agent 输出记录
 *
 * 存档就是一条时间线：跑过的每一次运行按真实时刻从新到旧排下来，
 * 点开一条能看到那次运行的全部字段。
 *
 * **这一页一个 JS 时间对象都不造。** 六张表的时间戳有三种格式（带 Z、带偏移、
 * 什么都不带），`new Date("…Z")` 与 `new Date("…")` 在 JS 里分属两种时区解释，
 * 拿它们排序会把更晚发生的运行排到更早的下面、而界面上完全看不出异常。
 * 所以时刻的解析、换算、排序全在后端 Python 侧做完（module.py 的 _stamp），
 * 这里只按接口给的顺序渲染 —— filter 保序，不重排。
 * ====================================================================== */

async function renderRuns(ctx) {
  const { el } = ctx;
  const body = host.body;
  body.textContent = "";
  body.appendChild(el("div", { class: "agc-loading", text: "读取 Agent 运行记录" }));

  let data;
  try {
    data = runsCache || (runsCache = await ctx.api("runs"));
  } catch (e) {
    body.textContent = "";
    body.appendChild(ctx.placeholder("读不到运行记录", String(e.message || e), "error"));
    return;
  }

  body.textContent = "";
  const wrap = el("div", { class: "agc-wrap" });
  const runs = data.runs || [];

  // 有记录的 Agent 与各自的次数。筛选按钮只列真的有记录的，
  // 列一个点进去空着的按钮等于给自己挖坑。
  const byAgent = new Map();
  for (const r of runs) byAgent.set(r.agent_label, (byAgent.get(r.agent_label) || 0) + 1);

  const pick = ctx.filters.agent || "";
  const shown = pick ? runs.filter((r) => r.agent_label === pick) : runs;

  wrap.appendChild(
    el("section", { class: "agc-top" }, [
      el("div", { class: "agc-h1" }, [
        "Agent 输出记录",
        el("button", {
          class: "agc-info", type: "button", "aria-label": "这一页的口径",
          text: "ⓘ",
          onclick: (e) => ctx.pop.show(e.currentTarget, calibre(ctx)),
        }),
      ]),
      el("p", { class: "agc-lede", text: "跑过的每一次运行都留在这里，按时间从新到旧。点一条看那次运行的全部字段。" }),
      el("div", { class: "agc-sum" }, [
        el("span", {}, [el("b", { text: String(data.total || 0) }), " 次运行"]),
        el("span", {}, [el("b", { text: String(byAgent.size) }), " 个 Agent 有记录"]),
        el("span", {}, ["最近一次 ", el("b", { text: runs[0] ? runs[0].ran_at : "—" })]),
      ]),
    ])
  );

  // 来源读不动的时候必须说出来，不能静默当成"没跑过"
  if (data.unreadable) {
    wrap.appendChild(
      el("div", { class: "agc-bad" }, [
        (data.sources || [])
          .filter((s) => s.condition !== "正常")
          .map((s) => `${s.source}：${s.reason || s.condition}`)
          .join("；"),
      ])
    );
  }

  wrap.appendChild(agentPicker(ctx, byAgent, pick));

  if (!shown.length) {
    wrap.appendChild(
      ctx.placeholder(
        pick ? `${pick} 还没有运行记录` : "还没有任何运行记录",
        pick ? "换一个 Agent 看看。" : "六张运行表都是空的。",
        "empty"
      )
    );
    body.appendChild(wrap);
    return;
  }

  // 按天分组。day 由后端按换算后的本机时刻给，这里只比字符串是否相等，不做时间运算。
  const list = el("div", { class: "agc-arch" });
  let day = null;
  for (const r of shown) {
    if (r.day !== day) {
      day = r.day;
      const n = shown.filter((x) => x.day === day).length;
      list.appendChild(
        el("div", { class: "agc-day" }, [
          el("span", { class: "agc-day-d", text: day || "时间不明" }),
          el("span", { class: "agc-day-w", text: r.weekday || "" }),
          el("span", { class: "agc-day-n", text: `${n} 次` }),
        ])
      );
    }
    list.appendChild(runRow(ctx, r));
  }
  wrap.appendChild(list);
  body.appendChild(wrap);
}

/* 这一页的口径。栏目怎么算的收进 ⓘ，不写成正文一行字。
 *
 * 内容节点自己带 data-module —— 外壳的浮层与抽屉都挂在 #wb-body 外面，
 * 模块 CSS 全部作用在 [data-module="agentcfg"] 下（契约 8.3 / 门禁 G2），
 * 不把作用域随内容带过去，这段文字就完全没有样式。 */
const CALIBRE = [
  "时间：那次运行写库的时刻，六张表三种时间戳格式都换算到本机时区后显示。",
  "数据口径：那次运行判断时用的基准日，不是它运行的那一天。",
  "摘要：Agent 自己写的那句话，有的运行表没有这一列。",
];

function calibre(ctx) {
  return ctx.el(
    "div",
    { class: "agc-cal", "data-module": "agentcfg" },
    CALIBRE.map((t) => ctx.el("p", { text: t }))
  );
}

function agentPicker(ctx, byAgent, pick) {
  const { el } = ctx;
  const box = el("div", { class: "agc-pick" });
  box.appendChild(
    el("button", {
      class: "agc-chip", type: "button", "aria-pressed": pick ? "false" : "true",
      text: "全部",
      onclick: () => ctx.setFilters({ agent: "" }),
    })
  );
  for (const [label, n] of byAgent) {
    box.appendChild(
      el("button", {
        class: "agc-chip", type: "button",
        "aria-pressed": pick === label ? "true" : "false",
        onclick: () => ctx.setFilters({ agent: label }),
      }, [label, el("b", { text: String(n) })])
    );
  }
  return box;
}

function runRow(ctx, r) {
  const { el } = ctx;
  const open = () => openRun(ctx, r);
  const foot = [r.source, r.trigger, r.model_version, r.data_as_of ? `数据口径 ${r.data_as_of}` : null,
                r.lasted ? `耗时 ${r.lasted}` : null].filter(Boolean).join(" · ");

  return el("article", {
    class: "agc-run", tabindex: "0", role: "link",
    onclick: open,
    onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } },
  }, [
    el("div", { class: "agc-run-t", text: r.clock || "—" }),
    el("div", { class: "agc-run-main" }, [
      el("div", { class: "agc-run-head" }, [
        el("span", { class: "agc-run-agent", text: r.agent_label }),
        r.status ? el("span", { class: "agc-badge", "data-status": r.status, text: r.status }) : null,
        el("span", { class: "agc-run-obj", text: r.subject || "—" }),
        ...(r.tags || []).map((t) => el("span", { class: "agc-tag" }, [t.k, el("b", { text: t.v })])),
      ]),
      r.summary ? el("p", { class: "agc-run-sum", text: r.summary }) : null,
      r.error ? el("p", { class: "agc-run-sum", "data-kind": "warn", text: r.error }) : null,
      el("div", { class: "agc-run-foot", text: foot }),
    ]),
    el("span", { class: "agc-run-open", text: "详情" }),
  ]);
}

/* 一次运行的全部字段。库里写的时间戳原文也照实摆出来 ——
 * 存档要能回答"这条记录是什么时候写进去的"，而这六张表的写法确实不一样。 */
function openRun(ctx, r) {
  const { el } = ctx;
  const box = el("div", { class: "agc-runbox", "data-module": "agentcfg" });

  if (r.summary) box.appendChild(el("p", { class: "agc-runsum", text: r.summary }));
  if (r.error) box.appendChild(el("p", { class: "agc-runsum", "data-kind": "warn", text: r.error }));

  const rows = [
    ["运行编号", r.run_id],
    [r.subject_kind || "判断对象", r.subject],
    ["跑的时间", r.ran_at],
    ["库里写的", r.raw_stamp ? `${r.raw_stamp}（${r.stamp_shape}）` : null],
    ["耗时", r.lasted],
    ["数据口径", r.data_as_of],
    ["触发方式", r.trigger],
    ["模型版本", r.model_version],
    ["运行状态", r.status],
    ...(r.tags || []).map((t) => [t.k, t.v]),
    ...(r.extra || []).map((t) => [t.k, t.v]),
    ["记录来源", r.source],
  ];

  const dl = el("div", { class: "agc-dl" });
  for (const [k, v] of rows) {
    if (v === null || v === undefined || v === "") continue;   // 空就不摆这一行，不填默认值
    dl.appendChild(el("div", { class: "agc-dl-k", text: k }));
    dl.appendChild(el("div", { class: "agc-dl-v", text: String(v) }));
  }
  box.appendChild(dl);
  ctx.drawer.open(`${r.agent_label} · ${r.ran_at || "时间不明"}`, box, "right");
}
