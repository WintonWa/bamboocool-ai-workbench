/* 竞品分析模块前端。契约 8.2：ES module，零全局声明，只导出下面这些。
   $ / el / 格式化 / 浮层 / 抽屉一律从 ctx 取，不自己实现，也不碰 document。
   状态只读写 state.modules.competitor；选中对象与筛选由外壳持有。 */

import { renderTimeline, laneLegend } from "./competitor/timeline.js";

export const id = "competitor";
export const apiVersion = 1;
/* 外壳把侧栏做成可折叠抽屉，显隐由 syncRail(impl.usesRail) 决定。
   其余模块都显式声明，这里跟上，别靠 undefined 走默认。 */
export const usesRail = true;

export const filters = [
  { key: "q", kind: "search", label: "竞品或父 ASIN" },
  { key: "sub", kind: "select", label: "子类目", optionsFrom: "meta.sub_categories" },
  {
    key: "domain", kind: "select", label: "变化类型",
    options: [
      { value: "price_promo", label: "活动与价格" },
      { value: "market", label: "市场表现" },
      { value: "keyword", label: "关键词位置" },
      { value: "traffic", label: "流量结构" },
    ],
  },
  {
    key: "evidence", kind: "select", label: "证据状态",
    options: ["正常", "过期", "缺失", "待确认"].map((v) => ({ value: v, label: v })),
  },
];

const PAGE_IDS = new Set(["cmp-overview", "cmp-rival"]);
const PAGE_ALIAS = { overview: "cmp-overview", rival: "cmp-rival" };

let body = null;
let rail = null;
let ctx = null;
let meta = null;
let chart = null;
let agentPanel = null;
let detailSnapshot = null;
let taskPollTimer = null;
let activePollToken = 0;

const AGENT_POLL_MS = 3000;
const AGENT_POLL_LIMIT_MS = 2 * 60 * 1000;
const AGENT_THRESHOLD_DEFAULTS = Object.freeze({
  price_drop_pct: 5,
  gap_shift_pct: 10,
  rank_shift_pct: 15,
  kw_rank_shift: 3,
  min_duration_days: 7,
  family_coverage_pct: 30,
  stale_days: 14,
});

function disposeChart() {
  if (chart) { try { chart.dispose(); } catch (e) { /* 已卸载 */ } chart = null; }
}

function stopTaskPolling() {
  activePollToken += 1;
  if (taskPollTimer !== null) clearTimeout(taskPollTimer);
  taskPollTimer = null;
}

export async function mount(nodes, context) {
  body = nodes.body;
  rail = nodes.rail;
  ctx = context;
  await render(context);
}

export function unmount() {
  stopTaskPolling();
  disposeChart();
  body = null;
  rail = null;
  ctx = null;
  meta = null;
  agentPanel = null;
  detailSnapshot = null;
}

/* 契约 8.8：URL 即状态。只返回尾段，外壳自己拼 /competitor 前缀。
   段名直接用页面 id —— 外壳的 applyUrl() 在 impl 加载前解析一次 URL，
   那时拿不到 parsePath，会回落到「段名匹配 pages[].id」。 */
export function pathFor({ pageId, objectId } = {}) {
  const seg = [];
  if (PAGE_IDS.has(pageId) && pageId !== "cmp-overview") seg.push(pageId);
  else if (objectId) seg.push("cmp-rival");
  if (objectId) seg.push(encodeURIComponent(objectId));
  return seg.join("/");
}

export function parsePath(segments = []) {
  const s = (segments || []).filter(Boolean);
  let pageId = "cmp-overview";
  let rest = s;
  if (PAGE_IDS.has(s[0])) { pageId = s[0]; rest = s.slice(1); }
  else if (PAGE_ALIAS[s[0]]) { pageId = PAGE_ALIAS[s[0]]; rest = s.slice(1); }
  let objectId;
  if (rest.length) {
    const raw = rest[rest.length - 1];
    try { objectId = decodeURIComponent(raw); } catch { objectId = raw; }
  }
  if (objectId && pageId === "cmp-overview") pageId = "cmp-rival";
  return { pageId, objectId };
}

export async function render(context) {
  ctx = context || ctx;
  if (!body || !ctx) return;
  stopTaskPolling();
  disposeChart();
  agentPanel = null;
  detailSnapshot = null;
  if (!meta) meta = await ctx.api("meta");
  const page = ctx.pageId || "cmp-overview";
  const objectId = ctx.objectId;

  if (page === "cmp-rival" && !objectId) {
    rail.replaceChildren(railBlock(null));
    body.replaceChildren(ctx.placeholder(
      "先选一个竞品产品族",
      "从总览的威胁比较表或左侧快捷位进入", "空结果"));
    return;
  }

  try {
    if (page === "cmp-rival") {
      const d = await ctx.api(`rival/${encodeURIComponent(objectId)}`);
      if (d.condition === "缺失" || d.condition === "空结果") {
        rail.replaceChildren(railBlock(objectId));
        body.replaceChildren(ctx.placeholder("这个竞品打不开", d.message || "", d.condition));
        return;
      }
      rail.replaceChildren(railBlock(objectId));
      detailSnapshot = d;
      body.replaceChildren(detailView(d));
      resumeTaskPolling(d);
    } else {
      const d = await ctx.api("rivals");
      rail.replaceChildren(railBlock(null, d));
      body.replaceChildren(overviewView(d));
    }
  } catch (err) {
    body.replaceChildren(ctx.placeholder(
      "这一页暂时打不开", String((err && err.message) || err), "失败"));
  }
}

/* ---------------- 侧栏 ---------------- */
function railBlock(currentAsin, ov) {
  const el = ctx.el;
  const kids = [];

  if (ov && ov.insight) {
    const ins = ov.insight;
    kids.push(el("div", {}, [
      el("div", { class: "cmp-rail-h", text: "本周期最值得关注" }),
      el("div", { class: "cmp-insight" }, [
        el("div", { class: "cmp-insight-head", text: ins.headline }),
        el("div", { class: "cmp-insight-sub" }, [
          `${ins.brand} · ${ins.period[0]} ~ ${ins.period[1]}`
          + (ins.pressure ? ` · 压力在${ins.pressure}` : ""),
        ]),
        ins.impact_note
          ? el("div", { class: "cmp-insight-sub", text: `可能影响：${ins.impact_note}` })
          : null,
        ins.unconfirmed_note
          ? el("div", { class: "cmp-insight-sub", text: `仍需确认：${ins.unconfirmed_note}` })
          : null,
        el("div", { class: "cmp-insight-sub" }, [
          el("button", {
            class: "cmp-inline-btn", text: "查看它的共同时间线",
            onclick: () => ctx.open(ins.family_asin, "cmp-rival"),
          }),
          ins.more > 0 ? `　另有 ${ins.more} 条` : null,
        ]),
      ]),
    ]));
  }

  if (ov && ov.count_band) {
    const active = ctx.filters.domain || "";
    kids.push(el("div", {}, [
      el("div", { class: "cmp-rail-h", text: "变化类型 · 点数字筛主表" }),
      el("div", { class: "cmp-counts" }, ov.count_band.map((c) =>
        el("button", {
          class: "cmp-count",
          "aria-pressed": String(active === c.domain),
          onclick: () => ctx.setFilters({ domain: active === c.domain ? "" : c.domain }),
        }, [
          el("span", { class: "cmp-count-n", text: ctx.fmt.int(c.family_count) }),
          el("span", { class: "cmp-count-k" }, [
            c.label,
            el("div", { class: "cmp-sub", text: "个产品族" }),
          ]),
        ]))),
    ]));
  }

  kids.push(el("div", {}, [
    el("div", { class: "cmp-rail-h", text: `快捷位 · ${meta.quick_slot.length} 个常看竞品` }),
    el("div", { class: "cmp-quick" }, meta.quick_slot.map((q) =>
      el("button", {
        class: "cmp-quick-item",
        "aria-current": String(q.family_asin === currentAsin),
        onclick: () => ctx.open(q.family_asin, "cmp-rival"),
      }, [
        el("span", { class: "cmp-quick-name" }, [
          q.brand,
          el("div", { class: "cmp-sub wb-mono", text: ctx.fmt.money(q.unit_price) + " / 件" }),
        ]),
        el("span", { class: "cmp-sev-word", "data-sev": q.attention_key, text: q.attention }),
      ]))),
  ]));

  kids.push(el("div", {}, [
    el("div", { class: "cmp-rail-h", text: "数据状态与更新" }),
    el("div", { class: "cmp-sub" }, meta.freshness.map((f) =>
      ctx.el("div", { text: `${f.name} 更新至 ${ctx.fmt.date(f.updated)}` }))),
    el("div", { class: "cmp-sub", text: " " }),
    el("div", {}, meta.data_status.map((s) =>
      ctx.el("span", { class: "wb-chip" }, [
        ctx.cond(s.label) || ctx.el("span", { text: s.label }),
        ctx.el("b", { class: "wb-num", text: ` ${s.n}` }),
      ]))),
    el("div", { class: "cmp-sub" }, [
      `监控 ${meta.monitored} 族 · 分析 ${meta.analyzed} 族 · `,
      el("button", {
        class: "cmp-inline-btn", text: "口径与未确认项",
        onclick: () => ctx.drawer.open("竞品分析的口径与未确认项", unconfirmedPanel()),
      }),
    ]),
  ]));

  return el("div", { class: "cmp-rail" }, kids);
}

function unconfirmedPanel() {
  const el = ctx.el;
  return el("div", {}, [
    el("div", { class: "cmp-sec-h" }, [
      el("span", { text: "判断对象" }),
      el("span", { class: "cmp-sec-note", text: meta.judgment_object }),
    ]),
    el("div", { class: "cmp-sub" }, [
      `${meta.scope_label}　观察窗 ${meta.window[0]} ~ ${meta.window[1]}`,
      el("div", { text: meta.product_spine }),
      el("div", { text: `竞争关系 ${meta.relations.total} 条，已确认 ${meta.relations.confirmed} 条` }),
      el("div", { text: `重点关键词 ${meta.keywords.total} 个，与自有共同竞争 ${meta.keywords.battleground} 个` }),
    ]),
    el("div", { class: "cmp-rail-h", text: "以下口径客户还没确认" }),
    el("ul", { class: "cmp-list" }, meta.unconfirmed.map((u) =>
      el("li", { class: "cmp-li", text: u }))),
    el("div", { class: "cmp-rail-h", text: "价差口径" }),
    el("div", { class: "cmp-sub", text: "竞品多为 6 件装、自有为 3/4/7 件装，所以价差一律按件单价比较；装盒数解析不出的对象不进价差结论。" }),
  ]);
}

/* ---------------- 总览 ---------------- */
const COLS = [
  "竞品身份", "当前威胁 / 变化", "市场结果", "价格与促销",
  "流量与关键词", "发生时间", "证据", "",
];

function overviewView(d) {
  const el = ctx.el;
  const rows = d.table.map(rowFor);
  return el("div", { class: "cmp-body" }, [
    el("section", { class: "cmp-sec" }, [
      el("div", { class: "cmp-sec-h" }, [
        el("span", { text: `威胁比较表 · ${d.totals.shown} / ${d.totals.analyzed} 个竞品产品族` }),
        el("span", { class: "cmp-sec-note" }, [
          `父 ASIN 是判断对象，子体与报价在详情展开　`,
          el("button", {
            class: "cmp-inline-btn", text: "为什么不给威胁分数",
            onclick: (ev) => ctx.pop.show(ev.currentTarget,
              "关注程度由可观察变化、竞争关系、影响范围和证据完整程度共同形成，"
              + "页面同步给出依据条目。正式规则确认前不生成综合分数——"
              + "一个算不出来源的分数没法核对，也没法反驳。"),
          }),
        ]),
      ]),
      rows.length
        ? el("div", { class: "cmp-wrap" }, [
          el("table", { class: "cmp-table" }, [
            el("thead", {}, [el("tr", {}, COLS.map((c) =>
              el("th", { class: "cmp-th", text: c })))]),
            el("tbody", {}, rows),
          ]),
        ])
        : ctx.placeholder("当前筛选下没有竞品", "清掉筛选或换一个变化类型", "空结果"),
    ]),
  ]);
}

function rowFor(r) {
  const el = ctx.el;
  const f = ctx.fmt;
  return el("tr", { class: "cmp-tr", "data-sev": r.attention_key }, [
    el("td", { class: "cmp-td cmp-td-lead" }, [
      el("div", { class: "cmp-strong", text: r.brand }),
      el("div", { class: "cmp-sub wb-mono", text: r.family_asin }),
    ]),
    el("td", { class: "cmp-td" }, [
      el("div", { class: "cmp-sev-word", text: r.attention }),
      r.threat_label ? el("div", { text: r.threat_label }) : null,
      el("div", { class: "cmp-sub" }, [
        r.transition ? `较上次 ${r.transition}` : null,
        r.in_quick_slot ? "　快捷位" : null,
      ]),
    ]),
    cellOf(r.market_cell, r.threat_label, [
      el("div", { class: "cmp-trend" }, [
        el("span", { class: "cmp-spark", html: sparkSVG(r.spark_rank, { invert: true, color: "#6b4fa8" }) }),
        el("span", { class: "cmp-sub wb-mono", text: `第 ${f.int(r.rank_now)} 名` }),
      ]),
      el("div", { class: "cmp-sub wb-mono", text: `月量级 ${f.int(r.units_now)}` }),
    ]),
    el("td", { class: "cmp-td" }, [
      el("div", { class: "cmp-trend" }, [
        el("span", { class: "cmp-spark",
          html: r.unit_price_now ? sparkSVG(r.spark_price) : "" }),
        el("span", { class: "wb-mono", text: `${f.money(r.unit_price_now)} / 件` }),
      ]),
      el("div", { class: "cmp-sub wb-mono" }, [
        `整包 ${f.money(r.price_band[0])} ~ ${f.money(r.price_band[1])}`,
      ]),
      r.gap_multiple
        ? el("div", { class: "cmp-sub" }, [
          "自有 ",
          el("span", { class: "cmp-dir",
            "data-d": r.gap_multiple > 1 ? "worse" : "better",
            text: `${r.gap_multiple}×` }),
          r.gap_multiple > 1 ? " 贵" : " 便宜",
        ])
        : null,
      r.price_cell && r.price_cell.label !== r.threat_label
        ? el("div", { class: "cmp-sub", text: r.price_cell.label }) : null,
    ]),
    el("td", { class: "cmp-td" }, [
      r.keyword_cell && r.keyword_cell.label !== r.threat_label
        ? el("div", { text: r.keyword_cell.label }) : null,
      r.traffic_cell ? el("div", { class: "cmp-sub", text: r.traffic_cell.label }) : null,
      !r.keyword_cell && !r.traffic_cell
        ? el("div", { class: "cmp-sub", text: "无位置变化" }) : null,
    ]),
    el("td", { class: "cmp-td wb-mono cmp-nowrap" }, [
      el("div", { text: f.date(r.happened_from) }),
      el("div", { class: "cmp-sub", text: r.happened_state || "" }),
    ]),
    el("td", { class: "cmp-td" }, [
      ctx.nature(r.nature) || el("span", { text: r.nature }),
      ctx.cond(r.state),
      r.state !== "正常" && r.evidence_reason
        ? el("div", {}, [el("button", {
          class: "cmp-inline-btn", text: "为什么",
          onclick: (ev) => ctx.pop.show(ev.currentTarget, r.evidence_reason),
        })]) : null,
    ]),
    el("td", { class: "cmp-td" }, [
      el("button", {
        class: "wb-btn cmp-nowrap", text: "时间线",
        onclick: () => ctx.open(r.family_asin, "cmp-rival"),
      }),
    ]),
  ]);
}

function cellOf(c, threatLabel, extra) {
  const el = ctx.el;
  if (!c) {
    return el("td", { class: "cmp-td" }, [
      el("div", { class: "cmp-sub", text: "无变化" }), ...(extra || []),
    ]);
  }
  const mag = c.magnitude == null ? ""
    : (c.magnitude_kind === "pct" ? `${c.magnitude > 0 ? "+" : ""}${c.magnitude}%`
      : `${c.magnitude > 0 ? "+" : ""}${c.magnitude}`);
  return el("td", { class: "cmp-td" }, [
    c.label === threatLabel ? null : el("div", { text: c.label }),
    el("div", { class: "cmp-sub" }, [
      mag ? el("span", { class: "cmp-dir", "data-d": c.direction, text: mag }) : null,
      mag ? " · " : null,
      c.nature,
      c.represents_family ? null : " · 仅局部对象",
    ]),
    ...(extra || []),
  ]);
}

/* ---------------- 详情 ---------------- */
function agentTaskStore() {
  if (!ctx.state.agentTasks) ctx.state.agentTasks = {};
  return ctx.state.agentTasks;
}

function agentTask(familyAsin) {
  return agentTaskStore()[familyAsin] || null;
}

function saveAgentTask(familyAsin, patch) {
  const store = agentTaskStore();
  store[familyAsin] = { ...(store[familyAsin] || {}), ...patch };
  return store[familyAsin];
}

function agentThresholds() {
  const params = ctx.params;
  return Object.fromEntries(Object.entries(AGENT_THRESHOLD_DEFAULTS).map(([key, fallback]) => {
    const value = Number(params[key]);
    return [key, Number.isFinite(value) ? value : fallback];
  }));
}

function requestKey(familyAsin) {
  const suffix = globalThis.crypto && typeof globalThis.crypto.randomUUID === "function"
    ? globalThis.crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `workbench:manual:${familyAsin}:${suffix}`;
}

async function agentApi(url, init) {
  const response = await fetch(url, init);
  const payload = await response.json().catch(() => ({ reason: "Agent 服务返回了无法识别的响应" }));
  if (!response.ok) {
    throw new Error(payload.reason || payload.error || payload.message || `Agent 服务返回 ${response.status}`);
  }
  return payload;
}

function taskPayload(payload) {
  return payload && payload.task && typeof payload.task === "object"
    ? { ...payload, ...payload.task }
    : (payload || {});
}

function taskIdOf(payload) {
  const task = taskPayload(payload);
  return task.task_id || task.taskId || null;
}

function taskStatusOf(payload) {
  const task = taskPayload(payload);
  const status = String(task.state || task.status || "").toLowerCase();
  return status === "completed" ? "done" : status;
}

function taskReasonOf(payload) {
  const task = taskPayload(payload);
  return task.reason || task.error || task.message || null;
}

function paintAgentPanel() {
  if (!agentPanel || !detailSnapshot) return;
  agentPanel.replaceChildren(...agentPanelChildren(detailSnapshot));
}

function scheduleTaskPoll(familyAsin, taskId, startedAt, token, delay = AGENT_POLL_MS) {
  if (token !== activePollToken) return;
  taskPollTimer = setTimeout(
    () => pollAgentTask(familyAsin, taskId, startedAt, token), delay);
}

async function applyTaskPayload(familyAsin, payload, startedAt, token) {
  const status = taskStatusOf(payload);
  const taskId = taskIdOf(payload) || (agentTask(familyAsin) || {}).taskId;
  const common = {
    taskId,
    startedAt,
    reason: taskReasonOf(payload),
    runId: taskPayload(payload).run_id || null,
  };

  if (status === "queued" || status === "running") {
    saveAgentTask(familyAsin, { ...common, phase: status });
    paintAgentPanel();
    scheduleTaskPoll(familyAsin, taskId, startedAt, token);
    return;
  }
  if (status === "done") {
    saveAgentTask(familyAsin, { ...common, phase: "done" });
    paintAgentPanel();
    meta = null;
    await render(ctx);
    return;
  }
  if (status === "skipped" || status === "failed") {
    saveAgentTask(familyAsin, { ...common, phase: status });
    paintAgentPanel();
    return;
  }

  saveAgentTask(familyAsin, {
    ...common,
    phase: "failed",
    reason: "Agent 服务返回了未知任务状态，旧结果未受影响",
  });
  paintAgentPanel();
}

async function pollAgentTask(familyAsin, taskId, startedAt, token) {
  if (token !== activePollToken) return;
  if (Date.now() - startedAt >= AGENT_POLL_LIMIT_MS) {
    saveAgentTask(familyAsin, {
      phase: "timed_out",
      taskId,
      startedAt,
      reason: "已停止自动轮询，任务可能仍在后台运行；稍后重新进入本页查看结果",
    });
    paintAgentPanel();
    return;
  }

  try {
    const payload = await agentApi(
      `/api/agent/competitor/tasks/${encodeURIComponent(taskId)}`);
    await applyTaskPayload(familyAsin, payload, startedAt, token);
  } catch (error) {
    saveAgentTask(familyAsin, {
      phase: "retrying",
      taskId,
      startedAt,
      reason: `暂时无法读取任务状态，正在重试：${String((error && error.message) || error)}`,
    });
    paintAgentPanel();
    scheduleTaskPoll(familyAsin, taskId, startedAt, token);
  }
}

function resumeTaskPolling(d) {
  const task = agentTask(d.band.family_asin);
  if (!task || !task.taskId || !["submitting", "queued", "running", "retrying"].includes(task.phase)) return;
  const token = activePollToken;
  const startedAt = task.startedAt || Date.now();
  scheduleTaskPoll(d.band.family_asin, task.taskId, startedAt, token);
}

async function startAgentRun(d) {
  const familyAsin = d.band.family_asin;
  const current = agentTask(familyAsin);
  if (current && ["submitting", "queued", "running", "retrying"].includes(current.phase)) return;

  stopTaskPolling();
  const token = activePollToken;
  const startedAt = Date.now();
  saveAgentTask(familyAsin, { phase: "submitting", startedAt, taskId: null, reason: null });
  paintAgentPanel();

  const request = {
    trigger: "manual",
    family_asin: familyAsin,
    window_from: d.band.window[0],
    window_to: d.band.window[1],
    data_as_of: d.as_of,
    requested_by: "workbench-local-demo",
    request_key: requestKey(familyAsin),
    thresholds: agentThresholds(),
  };

  try {
    const payload = await agentApi("/api/agent/competitor/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    });
    const taskId = taskIdOf(payload);
    if (!taskId) throw new Error("Agent 服务未返回 task_id");
    await applyTaskPayload(familyAsin, payload, startedAt, token);
  } catch (error) {
    saveAgentTask(familyAsin, {
      phase: "failed",
      startedAt,
      taskId: null,
      reason: String((error && error.message) || error),
    });
    paintAgentPanel();
  }
}

function analysisStateCopy(state) {
  return ({
    current: ["结论已是最新", "当前结论与观察数据和阈值一致。"],
    not_run: ["尚未分析", "V2 Agent 还没有产生这个竞品族的结论。"],
    stale: ["建议重新分析", "观察数据或判断阈值已变化，页面仍保留上一版结果。"],
    insufficient: ["证据不足", "本次不给关注结论，可在数据补齐后重新分析。"],
    incomplete: ["任务未完成", "新任务还没有发布，已完成的旧结果仍可查看。"],
    damaged: ["结果不完整", "最新分析未通过完整性检查，建议重新分析。"],
  })[state] || ["可重新分析", "运行时会继续保留当前页面结果。"];
}

function agentPanelCopy(d, task) {
  if (!task) {
    const [title, detail] = analysisStateCopy(d.analysis_state);
    return { phase: d.analysis_state || "idle", title, detail };
  }
  const copy = {
    submitting: ["正在提交", "正在把这个竞品族送入 Pi Agent 任务队列。"],
    queued: ["已排队", "任务已接收；开始运行前，当前页面结果保持不变。"],
    running: ["分析中", "Pi Agent 正在依次执行 8 个判断步骤，页面继续显示上一版结果。"],
    retrying: ["正在重试", task.reason || "暂时未取到任务状态，页面将继续轮询。"],
    done: ["分析完成", "新结果已发布，页面数据已重新读取。"],
    skipped: ["无需重跑", task.reason || "数据、阈值和方法版本未变，继续使用当前结果。"],
    failed: ["本次未完成", task.reason || "Agent 任务失败，旧结果未受影响。"],
    timed_out: ["已停止自动等待", task.reason],
  }[task.phase];
  return copy
    ? { phase: task.phase, title: copy[0], detail: copy[1] }
    : { phase: "idle", title: "可重新分析", detail: "运行时会继续保留当前页面结果。" };
}

function agentPanelChildren(d) {
  const el = ctx.el;
  const task = agentTask(d.band.family_asin);
  const copy = agentPanelCopy(d, task);
  const pending = Boolean(task && ["submitting", "queued", "running", "retrying"].includes(task.phase));
  const timedOut = Boolean(task && task.phase === "timed_out" && task.taskId);
  return [
    el("div", { class: "cmp-agent-copy" }, [
      el("div", { class: "cmp-agent-title" }, [
        el("span", { text: "Pi Agent" }),
        el("span", { class: "cmp-agent-state", "data-state": copy.phase, text: copy.title }),
      ]),
      el("div", { class: "cmp-agent-detail", "aria-live": "polite", text: copy.detail }),
      task && task.taskId
        ? el("div", { class: "cmp-agent-id wb-mono", text: `task ${task.taskId}` })
        : null,
    ]),
    el("button", {
      class: "wb-btn cmp-agent-action",
      type: "button",
      disabled: pending,
      "aria-busy": String(pending),
      text: pending ? "分析进行中" : (timedOut ? "检查任务状态" : "重新分析"),
      onclick: () => timedOut ? resumeTimedOutTask(d, task) : startAgentRun(d),
    }),
  ];
}

function resumeTimedOutTask(d, task) {
  stopTaskPolling();
  const startedAt = Date.now();
  const token = activePollToken;
  saveAgentTask(d.band.family_asin, {
    phase: "retrying",
    startedAt,
    reason: "正在重新读取后台任务状态。",
  });
  paintAgentPanel();
  scheduleTaskPoll(d.band.family_asin, task.taskId, startedAt, token, 0);
}

function agentRunPanel(d) {
  agentPanel = ctx.el("section", { class: "cmp-agent-panel" }, agentPanelChildren(d));
  return agentPanel;
}

function detailView(d) {
  const el = ctx.el;
  return el("div", { class: "cmp-body" }, [
    agentRunPanel(d),
    judgmentBand(d),
    section("共同时间线",
      "价格、市场与事件共用一根横轴；活动期压在价格线上，同期关系直接可读",
      timelineBox(d)),
    section("市场表现与价格活动", "窗口内逐日观察", twoCols(d)),
    section("关键词入口证据", "只列该竞品当期落在前三的重点词", keywordTable(d)),
    section("事实、模拟、假设与因果未知", "四者分开，不混为一谈", evidenceCols(d)),
    section("分析记录与证据交付", "下游引用的是某一次分析，不是「最新」", recordBlock(d)),
  ]);
}

/* 共同时间线容器。图表必须在节点进 DOM 之后再 init，否则 ECharts 量不到宽高
   会画成 0×0 —— 这类 bug 门禁全绿也抓不到，只有看屏幕才发现。 */
function timelineBox(d) {
  const el = ctx.el;
  const box = el("div", { class: "cmp-chart" });
  const legend = el("div", { class: "cmp-lane-legend" }, laneLegend().map((l) =>
    el("span", { class: "cmp-lane-key" }, [
      el("i", { style: `background:${l.color}` }), l.label,
    ])));
  const hint = el("div", { class: "cmp-sub", text: "悬停看当天各轨的值，点一下看那天落在哪些区间" });

  requestAnimationFrame(async () => {
    if (!box.isConnected) return;
    chart = await renderTimeline(box, d, {
      onDayClick: (date, bands) => {
        const lines = bands.length
          ? bands.map((b) => `${b.lane.label} · ${b.label}`
            + `\n${b.from}${b.to ? " ~ " + b.to : " 起"}`
            + (b.note ? `\n${b.note}` : "")).join("\n\n")
          : "这一天没有落在任何事件或状态区间里";
        ctx.pop.show(box, `${date}\n\n${lines}`);
      },
    });
  });

  return el("div", {}, [legend, box, hint]);
}

function section(title, note, node) {
  const el = ctx.el;
  return el("section", { class: "cmp-sec" }, [
    el("div", { class: "cmp-sec-h" }, [
      el("span", { text: title }),
      note ? el("span", { class: "cmp-sec-note", text: note }) : null,
    ]),
    node,
  ]);
}

function judgmentBand(d) {
  const el = ctx.el;
  const f = ctx.fmt;
  const b = d.band;
  const p = d.price;
  return el("section", { class: "cmp-sec" }, [
    el("div", { class: "cmp-band" }, [
      el("div", {}, [
        el("div", { class: "cmp-hero-k" }, [
          `${b.brand} · `,
          el("span", { class: "wb-mono", text: b.family_asin }),
          b.sub_category ? ` · ${b.sub_category}` : "",
        ]),
        el("div", { class: "cmp-hero-v", "data-sev": b.attention_key, text: b.attention }),
        el("div", { class: "cmp-stat-s", text: b.attention_summary }),
        el("div", { class: "cmp-stat-s", text: b.causal_note }),
        b.reasons.length
          ? el("ul", { class: "cmp-reasons" }, b.reasons.map((r) =>
            el("li", { class: "cmp-reason" }, [
              r.label,
              r.note ? el("div", { class: "cmp-sub", text: r.note }) : null,
            ])))
          : null,
      ]),
      stat("件单价中位", f.money(b.unit_price_median),
        `整包 ${f.money(b.price_band[0])} ~ ${f.money(b.price_band[1])}`),
      stat("自有件单价倍数", p.gap_multiple ? `${p.gap_multiple}×` : f.dash,
        `自有 ${f.money(p.own_unit_price)} · ${p.own_child_count} 个子体`),
      stat("在售子体 / 自报变体", `${b.captured_children} / ${b.variant_count || f.dash}`,
        b.coverage_note),
      el("div", {}, [
        el("div", { class: "cmp-stat-k", text: "数据与本次分析" }),
        el("div", { class: "cmp-stat-v" }, [
          ctx.nature(b.nature) || el("span", { text: b.nature }),
          ctx.cond(b.state),
        ]),
        el("div", { class: "cmp-stat-s" }, [
          b.run_date ? `${f.date(b.run_date)} · ${b.trigger}` : "尚未分析",
          el("div", { text: `${b.window[0]} ~ ${b.window[1]}` }),
          b.evidence_reason
            ? el("button", {
              class: "cmp-inline-btn", text: b.evidence,
              onclick: (ev) => ctx.pop.show(ev.currentTarget, b.evidence_reason),
            })
            : null,
        ]),
      ]),
    ]),
  ]);
}

function stat(k, v, s) {
  const el = ctx.el;
  return el("div", {}, [
    el("div", { class: "cmp-stat-k", text: k }),
    el("div", { class: "cmp-stat-v", text: String(v) }),
    s ? el("div", { class: "cmp-stat-s", text: s }) : null,
  ]);
}

/* 表格里的迷你趋势线：内联 SVG 字符串经 el 的 html 通道注入，不碰 document。
   一行只有几个数字时读起来是文字陈述，给一条 40 点的轨才看得出在涨还是在退。 */
function sparkSVG(vals, opts = {}) {
  const v = (vals || []).filter((x) => x !== null && x !== undefined);
  if (v.length < 3) return "";
  const w = 68, h = 20, pad = 2;
  const min = Math.min(...v), max = Math.max(...v);
  const mid = Math.abs(v[v.length - 1]) || 1;
  const flat = (max - min) / mid < 0.02;
  const span = (max - min) || 1;
  const pts = v.map((x, i) => {
    const px = pad + i * (w - pad * 2) / (v.length - 1);
    // 极差不到中位数 2% 时按水平线画：把这点噪声铺开成波形，
    // 读起来像有波动其实没有，和一排等高柱是同一个错。
    const t = flat ? 0.5 : (x - min) / span;
    const py = pad + (flat ? t : (opts.invert ? t : 1 - t)) * (h - pad * 2);
    return `${px.toFixed(1)},${py.toFixed(1)}`;
  }).join(" ");
  const stroke = flat ? "#9ca3af" : (opts.color || "#111113");
  const last = v[v.length - 1], first = v[0];
  const better = opts.invert ? last < first : last > first;
  return `<svg viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" aria-hidden="true">
    <polyline points="${pts}" fill="none" stroke="${stroke}" stroke-width="1.3"
      vector-effect="non-scaling-stroke"/>
    ${flat ? "" : `<circle cx="${(pad + (w - pad * 2)).toFixed(1)}"
      cy="${(pad + (opts.invert ? (last - min) / span : 1 - (last - min) / span) * (h - pad * 2)).toFixed(1)}"
      r="1.8" fill="${better ? "#3a7d43" : "#c9372c"}"/>`}
  </svg>`;
}

/* 位置条：窗口起点 → 当前，画在 1..N 的刻度上，方向一眼可见 */
function bulletBar(from, to, scale) {
  const el = ctx.el;
  const cap = Math.max(scale || 20, from || 1, to || 1);
  const pos = (v) => `${Math.min(100, ((v || cap) / cap) * 100).toFixed(1)}%`;
  const gained = (to || cap) < (from || cap);
  return el("span", { class: "cmp-bullet" }, [
    el("span", { class: "cmp-bullet-from", style: `left:${pos(from)}` }),
    el("span", {
      class: "cmp-bullet-to",
      "data-dir": gained ? "better" : (to === from ? "flat" : "worse"),
      style: `left:${pos(to)}`,
    }),
  ]);
}

/* 纯 div 微柱条：不引图表库，也不碰 document */
function twoCols(d) {
  const el = ctx.el;
  const f = ctx.fmt;
  const m = d.market;
  const p = d.price;
  const left = el("div", {}, [
    el("div", { class: "cmp-band", style: "grid-template-columns:repeat(3,minmax(0,1fr));border:0;padding:0" }, [
      stat("小类排名", f.int(m.rank_now), `窗口起点 ${f.int(m.rank_start)}`),
      stat("销量量级（月）", f.int(m.units_now), "第三方估算"),
      stat("评分 / 评分数", `${f.num(m.rating_now, 1)} / ${f.int(m.rating_count_now)}`, ""),
    ]),
    el("div", { class: "cmp-sub" }, [
      `窗口内 ${m.series.length} 天连续观察　`, ctx.nature(m.nature) || m.nature,
    ]),
  ]);
  const right = el("div", {}, [
    el("div", { class: "cmp-band", style: "grid-template-columns:repeat(3,minmax(0,1fr));border:0;padding:0" }, [
      stat("当前成交价", f.money(p.final_now), `件单价 ${f.money(p.unit_now)}`),
      stat("窗口起点", f.money(p.start), `${p.observed_days} 天观察`),
      stat("活动天数", f.int(p.promo_days), "含 Deal 与 Coupon"),
    ]),
    el("div", { class: "cmp-sub" }, [
      `成交价轨 · 主销子体 ${p.child_asin}　`, ctx.nature(p.nature) || p.nature,
      "　",
      el("button", {
        class: "cmp-inline-btn", text: "产品族与报价关系",
        onclick: () => ctx.drawer.open("产品族与报价关系", familyPanel(d)),
      }),
    ]),
  ]);
  return el("div", { class: "cmp-cols2" }, [left, right]);
}

function familyPanel(d) {
  const el = ctx.el;
  const f = ctx.fmt;
  const head = ["子 ASIN", "尺码", "装盒数", "整包价", "件单价", ""];
  const rows = d.family.children.map((k) => el("tr", { class: "cmp-tr" }, [
    el("td", { class: "cmp-td wb-mono", text: k.child_asin }),
    el("td", { class: "cmp-td", text: k.size_label || f.dash }),
    el("td", { class: "cmp-td wb-mono", text: k.pack_count ? `${k.pack_count} 件` : "未解析" }),
    el("td", { class: "cmp-td wb-mono", text: f.money(k.snapshot_price) }),
    el("td", { class: "cmp-td wb-mono", text: f.money(k.unit_price) }),
    el("td", { class: "cmp-td", text: k.is_main_variant ? "主销" : "" }),
  ]));
  return el("div", {}, [
    el("table", { class: "cmp-table" }, [
      el("thead", {}, [el("tr", {}, head.map((t) => el("th", { class: "cmp-th", text: t })))]),
      el("tbody", {}, rows),
    ]),
    el("div", { class: "cmp-rail-h", text: "当前报价与卖家" }),
    el("div", {}, d.family.offers.map((o) =>
      el("span", { class: "wb-chip", text:
        `${o.seller_name}${o.is_buybox ? " · 当前 BuyBox" : " · 跟卖"} · ${o.fulfillment}` }))),
    el("div", { class: "cmp-rail-h", text: "与自有产品的竞争关系" }),
    el("ul", { class: "cmp-list" }, d.family.relations.slice(0, 8).map((r) =>
      el("li", { class: "cmp-li" }, [
        el("span", { class: "wb-mono", text: r.child_asin }),
        r.product_name ? ` · ${r.product_name}` : "",
        r.combination ? ` · ${r.combination}` : "",
        el("div", { class: "cmp-sub", text:
          `${r.relation_basis}${r.confirm_status === "pending_review" ? " · 待确认" : ""}` }),
      ]))),
    el("div", { class: "cmp-sub", text: d.family.unit_price_note }),
  ]);
}

function keywordTable(d) {
  const el = ctx.el;
  const f = ctx.fmt;
  const traffic = trafficLine(d.traffic);
  if (!d.keywords.length) {
    return el("div", {}, [
      el("div", { class: "cmp-empty",
        text: "该竞品当期没有落在重点词前三，暂无位置观察" }),
      traffic,
    ]);
  }
  const head = ["关键词", "自然位（起点 → 当前）", "点击共享", "转化共享", "月搜索量", "数据"];
  const rows = d.keywords.map((k) => el("tr", { class: "cmp-tr" }, [
    el("td", { class: "cmp-td" }, [
      k.keyword,
      k.battleground ? el("span", { class: "wb-chip", text: "共同竞争" }) : null,
      k.keyword_cn ? el("div", { class: "cmp-sub", text: k.keyword_cn }) : null,
    ]),
    el("td", { class: "cmp-td" }, [
      el("div", { class: "cmp-trend" }, [
        bulletBar(k.rank_start, k.rank_now, 12),
        el("span", { class: "wb-mono", text: `${f.int(k.rank_start)} → ${f.int(k.rank_now)}` }),
      ]),
    ]),
    el("td", { class: "cmp-td wb-mono", text: f.pct(k.click_share) }),
    el("td", { class: "cmp-td wb-mono", text: f.pct(k.conversion_share, 2) }),
    el("td", { class: "cmp-td wb-mono", text: f.int(k.monthly_search) }),
    el("td", { class: "cmp-td" }, [ctx.nature(k.nature) || k.nature]),
  ]));
  return el("div", {}, [
    el("div", { class: "cmp-wrap" }, [
      el("table", { class: "cmp-table" }, [
        el("thead", {}, [el("tr", {}, head.map((t) => el("th", { class: "cmp-th", text: t })))]),
        el("tbody", {}, rows),
      ]),
    ]),
    traffic,
  ]);
}

function trafficLine(t) {
  const el = ctx.el;
  const f = ctx.fmt;
  if (!t.latest) return el("div", { class: "cmp-empty", text: "无流量结构观察" });
  return el("div", { class: "cmp-sub" }, [
    `自然 ${f.pct(t.latest.organic_share, 0)}　广告 ${f.pct(t.latest.ad_share, 0)}　其他 ${f.pct(t.latest.other_share, 0)}　`,
    ctx.nature(t.nature) || t.nature,
    "　",
    el("button", {
      class: "cmp-inline-btn", text: "口径",
      onclick: (ev) => ctx.pop.show(ev.currentTarget, t.note),
    }),
  ]);
}

function evidenceCols(d) {
  const el = ctx.el;
  const ev = d.evidence;
  const col = (title, items, make, emptyText = "无") => el("div", {}, [
    el("div", { class: "cmp-rail-h", text: `${title} · ${items.length}` }),
    items.length
      ? el("ul", { class: "cmp-list" }, items.map(make))
      : el("div", { class: "cmp-empty", text: emptyText }),
  ]);
  return el("div", { class: "cmp-cols4" }, [
    col("可观察事实", ev.facts, (x) => el("li", { class: "cmp-li" }, [
      x.label,
      el("div", { class: "cmp-sub" }, [
        `${x.basis}`,
        el("div", { text: `${x.domain} · ${x.date_from}${x.date_to ? " ~ " + x.date_to : " 起"}` }),
        x.represents_family ? null : el("div", { text: "仅局部对象，未上卷到产品族" }),
      ]),
    ]), "本次没有真实或推导来源的变化；已识别变化全部来自模拟数据，见下一栏。"),
    col("模拟数据得出的变化", ev.simulated, (x) => el("li", { class: "cmp-li" }, [
      x.label,
      el("div", { class: "cmp-sub" }, [x.basis, "　", ctx.nature(x.nature) || x.nature]),
    ])),
    col("分析假设与待观察", ev.hypotheses, (x) => el("li", { class: "cmp-li" }, [
      x.statement,
      el("div", { class: "cmp-sub", text:
        [x.needed_data ? `需要：${x.needed_data}` : "",
          x.watch_until ? `观察至 ${x.watch_until}` : ""].filter(Boolean).join(" · ") }),
    ])),
    col("不能确认的因果", ev.unknown_causal, (x) => el("li", { class: "cmp-li" }, [
      x.statement,
      el("div", { class: "cmp-sub", text: `还缺：${x.missing_evidence || "更长周期观察"}` }),
    ])),
  ]);
}

function recordBlock(d) {
  const el = ctx.el;
  const rec = d.record;
  const imp = d.evidence.impacts;
  return el("div", { class: "cmp-cols2" }, [
    el("div", {}, [
      el("div", { class: "cmp-rail-h", text: "可能影响的自有产品与关键词" }),
      imp.length
        ? el("ul", { class: "cmp-list" }, imp.map((i) => el("li", { class: "cmp-li" }, [
          i.statement,
          el("div", { class: "cmp-sub" }, [
            i.shared_keyword ? `共同词 ${i.shared_keyword}　` : "",
            i.own_child_asin ? el("span", { class: "wb-mono", text: i.own_child_asin }) : null,
          ]),
        ])))
        : el("div", { class: "cmp-empty", text: "本次没有判定影响范围" }),
    ]),
    el("div", {}, [
      el("div", { class: "cmp-rail-h" }, [
        "分析记录　",
        el("span", { class: "wb-mono cmp-sub", text: rec.run_id || "" }),
      ]),
      rec.diff
        ? el("div", { class: "cmp-li" }, [
          `较上一版：${rec.diff.transition}`,
          el("div", { class: "cmp-sub", text: rec.diff.statement }),
        ])
        : null,
      rec.data_status.length
        ? el("ul", { class: "cmp-list" }, rec.data_status.map((s) =>
          el("li", { class: "cmp-li" }, [
            s.label,
            el("div", { class: "cmp-sub" }, [
              ctx.cond(s.state) || s.state, `　${s.range[0]} ~ ${s.range[1]}`,
            ]),
          ])))
        : null,
      el("div", { class: "cmp-rail-h", text: "交给下游" }),
      rec.handoffs.length
        ? el("ul", { class: "cmp-list" }, rec.handoffs.map((h) =>
          el("li", { class: "cmp-li" }, [
            `交给${h.target}：${h.fact}`,
            el("div", { class: "cmp-sub", text: `引用入口 ${h.entry}` }),
            el("div", { class: "cmp-sub", text: `冻结于 ${h.frozen_run_id} · ${h.evidence}` }),
          ])))
        : el("div", { class: "cmp-empty", text: "本次没有向下游交付证据" }),
    ]),
  ]);
}
