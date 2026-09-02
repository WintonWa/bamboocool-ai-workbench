/* 关键词分析模块前端。契约 8.2：ES module，零全局声明，只导出下面这些。
   $ / el / 格式化 / 浮层 / 抽屉一律从 ctx 取，不自己实现。
   状态只读写 state.modules.keyword；跨模块上下文只读，写走 ctx.setShared。
   A1 骨架：范围与数据状态 + 子体清单已实装，三页正文在 A2-A4 填。 */

export const id = "keyword";
export const apiVersion = 1;

export const filters = [
  { key: "q", kind: "search", label: "关键词或子 ASIN" },
  {
    key: "dimension", kind: "select", label: "需求维度",
    optionsFrom: "meta.demand_dimensions",
  },
  {
    key: "role", kind: "select", label: "运营角色",
    options: [
      { value: "core", label: "核心词" },
      { value: "explore", label: "探索词" },
      { value: "longtail", label: "长尾词" },
      { value: "pending_validation", label: "待验证词" },
    ],
  },
  {
    key: "evidence", kind: "select", label: "证据类型",
    optionsFrom: "meta.distributions.evidence_type",
  },
  {
    key: "state", kind: "select", label: "数据状态",
    options: ["正常", "过期", "缺失", "待确认", "空结果"].map((v) => ({ value: v, label: v })),
  },
];

let root = null;
let rail = null;
let ctx = null;
let meta = null;

/* 外壳调用 impl.mount({ rail, body }, ctx)，首屏由 mount 自己渲染；
   之后同模块内的状态变化走 render(ctx)。两者签名都不是 (node, state)。 */
export async function mount(nodes, context) {
  root = nodes.body;
  rail = nodes.rail;
  ctx = context;
  await render(context);
}

export function unmount() {
  root = null;
  rail = null;
  ctx = null;
  meta = null;
}

/* 契约 8.8：URL 即状态。两个纯函数，无副作用，可单测。
   pathFor 只返回尾段 —— 外壳自己拼 /keyword 前缀，这里再加就会变成 /keyword/keyword/...

   段名直接用页面 id（kw-child 而不是 child）：外壳的 applyUrl() 在模块 impl 加载前
   就解析一次 URL，那时拿不到 impl.parsePath，会回落到「段名匹配 pages[].id」的默认方案。
   用短别名的话首屏深链会被解析成 objectId，页签停在第一页。parsePath 仍兼容短别名。 */
const PAGE_ALIAS = { market: "kw-market", child: "kw-child", overview: "kw-overview" };
const PAGE_IDS = new Set(["kw-overview", "kw-market", "kw-child"]);

export function pathFor({ pageId, objectId } = {}) {
  const seg = [];
  if (PAGE_IDS.has(pageId) && pageId !== "kw-overview") seg.push(pageId);
  else if (objectId) seg.push("kw-overview");
  if (objectId) seg.push(encodeURIComponent(objectId));
  return seg.join("/");
}

export function parsePath(segments = []) {
  const s = segments.filter(Boolean);
  const head = s[0];
  let pageId = "kw-overview";
  let rest = s;
  if (PAGE_IDS.has(head)) { pageId = head; rest = s.slice(1); }
  else if (PAGE_ALIAS[head]) { pageId = PAGE_ALIAS[head]; rest = s.slice(1); }
  let objectId;
  if (rest.length) {
    const raw = rest[rest.length - 1];
    try { objectId = decodeURIComponent(raw); } catch { objectId = raw; }
  }
  return { pageId, objectId };
}

export async function render(context) {
  ctx = context || ctx;
  if (!root || !ctx) return;
  const page = ctx.pageId || "kw-overview";
  const objectId = ctx.objectId;
  if (!meta) meta = await ctx.api("meta");

  if (page === "kw-child" && !objectId) {
    root.replaceChildren(scopeBand(), await childList());
    return;
  }
  if (page === "kw-child") {
    let d;
    try {
      d = await ctx.api(`child/${encodeURIComponent(objectId)}`);
    } catch (err) {
      root.replaceChildren(ctx.placeholder("这一页暂时打不开",
        String(err.message || err), "失败"));
      return;
    }
    if (d.condition === "缺失" || d.condition === "空结果") {
      root.replaceChildren(ctx.placeholder(d.condition, d.message || "", d.condition));
      return;
    }
    renderChildPage(d);
    return;
  }
  if (page === "kw-market") {
    let d;
    try {
      d = await ctx.api(objectId ? `term/${encodeURIComponent(objectId)}` : "terms");
    } catch (err) {
      root.replaceChildren(ctx.placeholder("这一页暂时打不开",
        String(err.message || err), "失败"));
      return;
    }
    if (d.condition === "缺失" || d.condition === "空结果") {
      root.replaceChildren(ctx.placeholder(d.condition, d.message || "", d.condition));
      return;
    }
    if (objectId) renderTermPage(d);
    else renderLibraryPage(d);
    return;
  }
  let body;
  try {
    body = await ctx.api("overview");
  } catch (err) {
    root.replaceChildren(ctx.placeholder("这一页暂时打不开",
      String(err.message || err), "失败"));
    return;
  }
  if (body.condition !== "正常") {
    root.replaceChildren(ctx.placeholder(body.condition, body.message || "",
      body.condition));
    return;
  }
  renderOverviewPage(body);
}

/* ================= 页面一：关键词动态与机会总览 ================= */

function renderOverviewPage(d) {
  root.replaceChildren(
    sourceBand(d),
    reportBand(d),
    scopeStatusBand(d),
    groupChangeBand(d),
    coreChangeBand(d),
    priorityBand(d)
  );
}

/* ---- 板块一：动态关键词日报（五问五答，日报只负责总结和指路） ---- */
function reportBand(d) {
  const el = ctx.el;
  const r = d.reports[0];
  if (!r) return ctx.placeholder("空结果", "本期没有日报", "空结果");
  const delta = r.traffic_proxy_delta;
  const cc = d.core_changes;
  const gt = d.group_changes.totals;
  const f = ctx.fmt;
  const pctSign = (v) => (v == null ? null
    : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`);
  /* 五问五答原来是 <dl> 铺五段整句。答句是判断层产物、页面只读不改，
     但可以换重量：每问先给页面自算的结构化数字，答句降为次级说明。
     这样眼睛先拿到数，句子退成「为什么」。 */
  const qa = [
    { q: "流量获取结果", a: r.q1_traffic_result, figs: [
      ["较前一日", pctSign(delta), delta == null ? null : (delta >= 0 ? "good" : "alert")],
      ["基期", `${r.compare_base_date}　${f.int(r.compare_base_value)}`],
    ] },
    { q: "主要增长与下降", a: r.q2_main_movers, figs: [
      ["上涨词组", f.int(gt.up), "good"],
      ["下滑词组", f.int(gt.down), "alert"],
      ["竞争加剧", f.int(gt.competition), "warn"],
    ] },
    /* 这三个数是**整个观察窗口**的计数，而答句 q3 讲的是**当日**。
       两者并排且都不标口径时看起来像自相矛盾：窗口内新增 162 条，
       而答句说「当日新增覆盖 0 条…其中涉及核心词 114 条」。
       实测两边都对 —— _gained/_lost 的 to_date 散落在 90/109 个不同日期，
       2026-08-03 那天确实一条都没有；而 organic_up/down 这 288 条汇总事件
       按设计 to_date 全是末日，所以当日那 114 条核心词事件全是它们。
       修法是把口径写到标签上，不是改数字 —— 改数字会造出假数据。 */
    { q: "核心词覆盖与位置", a: r.q3_core_coverage_change, figs: [
      ["窗口内新增覆盖", f.int(cc.gained), "good"],
      ["窗口内丢失覆盖", f.int(cc.lost), "alert"],
      ["窗口内涉及核心词", f.int(cc.core_events)],
    ] },
    { q: "新出现的信号", a: r.q4_new_signals, figs: [
      ["覆盖或位置变化", f.int(cc.all_events)],
      ["其中显著", f.int(cc.significant), "warn"],
      ["涉及子体", f.int(cc.children_touched)],
    ] },
    { q: "最值得继续看", a: r.q5_priority_next, figs: [
      ["待处理事项", f.int(d.priority.total)],
      ["取样子体", f.int(cc.sampled_children)],
    ] },
  ];
  const older = d.reports.slice(1, 8);
  const spark = older.length
    ? el("span", { class: "kw-spark" }, d.reports.slice().reverse().map((x) => {
      const vals = d.reports.map((y) => y.traffic_proxy_value || 0);
      const hi = Math.max(1, ...vals);
      return el("i", {
        class: "kw-spark-bar",
        style: `height:${12 + ((x.traffic_proxy_value || 0) / hi) * 88}%`,
        title: `${x.report_date}　${ctx.fmt.int(x.traffic_proxy_value)}`,
      });
    }))
    : null;
  return el("section", { class: "kw-sec kw-hero" }, [
    el("div", { class: "kw-hero-main" }, [
      el("b", { text: ctx.fmt.int(r.traffic_proxy_value) }),
      el("span", { text: `${r.traffic_proxy_metric}　${r.report_date}　${r.compare_period}` }),
    ]),
    el("div", { class: "kw-statrow" }, [
      statText("较前一日", delta == null ? null
        : `${delta >= 0 ? "+" : ""}${(delta * 100).toFixed(1)}%`),
      stat("本期优先事项", d.priority.total),
      stat("核心词变化", d.core_changes.core_events),
      stat("发生变化的词组", d.group_changes.totals.groups_moved),
    ]),
    spark ? el("div", { class: "kw-kv" }, [
      el("span", { class: "kw-kv-item" }, [
        el("span", { text: "近 14 天" }), spark,
      ]),
    ]) : null,
    el("div", { class: "kw-qa" }, qa.map((x, i) => el("div", { class: "kw-qa-row" }, [
      el("div", { class: "kw-qa-q" }, [
        el("i", { class: "kw-qa-n", text: String(i + 1) }),
        el("b", { text: x.q }),
      ]),
      el("div", { class: "kw-qa-body" }, [
        metrics(x.figs),
        el("p", { class: "kw-qa-a", text: x.a }),
      ]),
    ]))),
  ]);
}

/* ---- 板块二：数据范围与数据状态（缺失要说清受影响范围） ---- */
function scopeStatusBand(d) {
  const el = ctx.el;
  const s = d.scope;
  const rows = [
    el("div", { class: "kw-kv" }, [
      kv("站点与品线", `${s.site} · ${s.product_line}`),
      kv("词库", s.library_terms), kv("监控词", s.monitored_terms),
      kv("重点子体", s.focus_children),
      kv("已建关系的词", s.terms_with_relations),
    ]),
    el("div", { class: "kw-kv" }, [
      kv("周快照窗口", `${s.week_window[0]} ~ ${s.week_window[1]}`),
      kv("逐日位置窗口", `${s.position_window[0]} ~ ${s.position_window[1]}`),
    ]),
    el("div", { class: "kw-chips" }, [
      chip("有当前产品目标的子体", s.children_with_goal),
      chip("有库存承接结果的子体", s.children_with_absorb),
      chip("已形成证据的子体", s.children_with_evidence),
      chip("有第二来源的词", s.second_source_terms),
    ]),
  ];
  for (const b of d.blocked_reasons || []) {
    rows.push(el("div", { class: "kw-blocked", text: b }));
  }
  return sec("数据范围与数据状态",
    "本页只对已建立关键词关系的子体出结论；下面几行说明哪些范围本期不参与比较",
    el("div", { class: "kw-band" }, rows));
}

/* ---- 板块三：市场需求与词组变化 ---- */
function groupChangeBand(d) {
  const el = ctx.el;
  const g = d.group_changes;
  const t = g.totals;
  const head = ["需求词组", "维度", "涉及词", "上涨", "下滑", "竞争加剧",
    "净向", "连续/单期", "月搜索量"];
  // 尾部搜索量极小的词组（个位数到 0）铺出来只是拉长表格，折进一行计数
  const shown = g.groups.filter((x) => x.search_moved >= 1000);
  const tail = g.groups.length - shown.length;
  const max = Math.max(1, ...shown.map((x) => x.search_moved));
  const body = shown.map((x) => el("tr", {
    class: "kw-row", "data-dimension": x.demand_dimension,
  }, [
    el("td", { text: x.group_name }),
    el("td", { text: x.demand_dimension }),
    el("td", { class: "kw-num", text: ctx.fmt.int(x.term_count) }),
    el("td", { class: "kw-num", text: x.up || "—" }),
    el("td", { class: "kw-num", text: x.down || "—" }),
    el("td", { class: "kw-num", text: x.competition || "—" }),
    el("td", {
      class: "kw-num" + (x.net < 0 ? " kw-warn-cell" : ""),
      text: x.net === 0 ? "持平" : `${x.net > 0 ? "+" : ""}${x.net}`,
    }),
    el("td", { class: "kw-num", text: `${x.continuous} / ${x.single_period}` }),
    el("td", { class: "kw-gapcell" }, [
      el("span", { class: "kw-gapnum kw-wide", text: ctx.fmt.int(x.search_moved) }),
      bar(x.search_moved / max, "vol"),
    ]),
  ]));
  const concentrated = g.top3_share >= 0.6;
  const samples = g.groups.slice(0, 3).flatMap((x) => x.samples.slice(0, 1));
  return sec("市场需求与词组变化",
    [["有变化的词组", ctx.fmt.int(t.groups_moved)],
      ["上涨", ctx.fmt.int(t.up), "good"],
      ["下滑", ctx.fmt.int(t.down), "alert"],
      ["竞争加剧", ctx.fmt.int(t.competition), "warn"],
      ["连续 / 单期", `${t.continuous} / ${t.single_period}`],
      ["前三词组占变动", ctx.fmt.pct(g.top3_share, 0),
        concentrated ? "warn" : null],
      ["集中度", concentrated ? "集中在少数需求" : "散在多个需求"],
      ["分权", g.dedup_applied ? "一词多组按权分摊" : "未按权分摊"]],
    el("div", { class: "kw-band" }, [
      samples.length ? el("ul", { class: "kw-evlist" }, samples.map((s) =>
        el("li", { class: "kw-ev" }, [
          el("div", { class: "kw-ev-head" }, [
            el("span", { class: "kw-tag", text: s.event_type_label }),
            el("span", { class: "kw-ev-meta", text: s.continuity_label }),
          ]),
          el("div", { class: "kw-ev-concl", text: s.label }),
        ]))) : null,
      el("div", { class: "kw-table-wrap" }, [table(head, body)]),
      tail > 0 ? el("div", { class: "kw-sec-note",
        text: `另有 ${tail} 个词组本期搜索量变动不足 1,000，未列出` }) : null,
    ]));
}

/* ---- 板块四：自有核心词覆盖与位置变化（只陈述事实） ---- */
function coreChangeBand(d) {
  const el = ctx.el;
  const c = d.core_changes;
  const head = ["子 ASIN", "关键词", "变化", "从", "到", "主推关系", "当前目标", "日期"];
  const body = c.recent.map((e) => el("tr", {
    class: "kw-row", "data-child": e.child_asin,
  }, [
    el("td", { text: e.child_asin }),
    el("td", { text: e.keyword }),
    el("td", { text: e.event_type_label }),
    el("td", { class: "kw-num", text: e.from_rank == null ? "—" : e.from_rank }),
    el("td", { class: "kw-num", text: e.to_rank == null ? "—" : e.to_rank }),
    el("td", { text: e.push_role_label || "—" }),
    el("td", { text: e.product_goal_label || "—" }),
    el("td", { text: e.to_date }),
  ]));
  const tbl = table(head, body);
  tbl.addEventListener("click", (ev) => {
    const tr = ev.target.closest("tr[data-child]");
    if (tr) ctx.open(tr.dataset.child, "kw-child");
  });
  const worst = c.top_declines[0];
  return sec("自有核心词覆盖与位置变化",
    [["核心词变化", ctx.fmt.int(c.core_events)],
      ["全部变化", ctx.fmt.int(c.all_events)],
      [`变动超过 ${c.rank_shift_threshold} 名`, ctx.fmt.int(c.significant), "warn"],
      ["新增覆盖", ctx.fmt.int(c.gained), "good"],
      ["丢失覆盖", ctx.fmt.int(c.lost), "alert"],
      ["涉及子体", ctx.fmt.int(c.children_touched)],
      ["下表取样", `${c.sampled_children} 个子体 · 每体最多 2 条`],
      worst ? ["跌幅最大",
        `${worst.child_asin}　第 ${worst.from_rank} → ${worst.to_rank} 位`, "alert"] : null],
    el("div", { class: "kw-band" }, [
      // 两排 chips 换成堆叠条：变化的构成是比例问题，chips 只给得出大小
      stackBar(c.by_type.map((x) => ({
        label: x.name, n: x.n,
        kind: /下降|丢失|跌出|失败/.test(x.name) ? "alert"
          : /上涨|新增/.test(x.name) ? "good" : "calm",
      }))),
      stackBar(c.by_push_role.map((x) => ({
        label: x.name, n: x.n,
        kind: x.name === "主推" ? "vol" : "mut",
      }))),
      el("div", { class: "kw-table-wrap" }, [sortable(tbl, [3, 4])]),
    ]));
}

/* ---- 板块五：机会与风险优先列表（只说先分析什么，不给广告动作） ---- */
function priorityBand(d) {
  const el = ctx.el;
  const p = d.priority;
  const items = p.items.slice(0, 12).map((e) => {
    const li = el("li", { class: "kw-ev kw-row", "data-child": e.child_asin }, [
      el("div", { class: "kw-ev-head" }, [
        el("span", { class: "kw-tag", text: e.evidence_type_label }),
        el("span", { class: "kw-ev-kw", text: `${e.child_asin} · ${e.keyword}` }),
        el("span", { class: "kw-ev-meta", text: e.evidence_completeness_label }),
        el("span", { class: "kw-ev-meta", text: e.next_verification_label }),
        e.push_role_label
          ? el("span", { class: "kw-ev-meta", text: e.push_role_label }) : null,
      ]),
      el("div", { class: "kw-ev-concl", text: e.conclusion }),
      el("div", { class: "kw-ev-basis", text: e.main_basis }),
      e.inventory_limit_label
        ? el("div", { class: "kw-ev-limit",
          text: `库存限制：${e.inventory_limit_label}` }) : null,
    ]);
    return li;
  });
  const ul = el("ul", { class: "kw-evlist" }, items);
  ul.addEventListener("click", (ev) => {
    const li = ev.target.closest("li[data-child]");
    if (li) ctx.open(li.dataset.child, "kw-child");
  });
  return sec("关键词机会、缺口与风险",
    [["待处理事项", ctx.fmt.int(p.total)],
      ["本页展开", `前 ${items.length} 条`],
      ["排序依据", "需求规模 · 变化紧迫 · 主推加权 · 证据完整度"],
      ["权重", p.weights ? Object.values(p.weights)
        .map((v) => ctx.fmt.pct(v, 0)).join(" / ") : null],
      ["不在本模块", "加词 · 否词 · 出价 · 预算"]],
    el("div", { class: "kw-band" }, [
      // 证据七类与下一步三态换成堆叠条：这两组本来就是构成，不是排行
      stackBar(p.type_counts.map((x) => ({
        label: x.name, n: x.n,
        kind: /风险/.test(x.name) ? "alert" : /机会/.test(x.name) ? "good"
          : /不足|待/.test(x.name) ? "mut" : "calm",
      }))),
      stackBar(p.next_counts.map((x) => ({
        label: x.name, n: x.n,
        kind: /广告/.test(x.name) ? "vol" : /竞品/.test(x.name) ? "calm" : "mut",
      }))),
      ul,
    ]));
}

function statText(label, text) {
  const el = ctx.el;
  const zero = text == null;
  return el("div", { class: "kw-stat" + (zero ? " kw-stat-zero" : "") }, [
    el("b", { text: zero ? "无可比" : text }),
    el("span", { text: label }),
  ]);
}

/* ================= 页面二：市场关键词库与单词深研 ================= */

function renderLibraryPage(d) {
  root.replaceChildren(sourceBand(d), libraryBand(d), groupBand(d),
    compareBand(d));
}

/* ---- 板块一：共享词库范围与数据质量 ---- */
function libraryBand(d) {
  const el = ctx.el;
  const s = d.summary;
  return el("section", { class: "kw-sec kw-hero" }, [
    el("div", { class: "kw-hero-main" }, [
      el("b", { text: ctx.fmt.int(s.total) }),
      el("span", { text: "共享市场词库，本品线共用一套；未绑定子体时只出市场事实" }),
    ]),
    el("div", { class: "kw-statrow" }, [
      stat("监控范围", s.monitored),
      stat("需求词组", d.groups.length),
      stat("拼写变体", s.variant_families),
      stat("运营已确认角色", s.role_confirmed),
    ]),
    el("div", { class: "kw-chips" }, d.library_status.map((x) => chip(x.label, x.n))),
    el("div", { class: "kw-chips" }, d.monitored_role.map((x) => chip(x.label, x.n))),
    el("div", { class: "kw-kv" }, [
      kv("品牌", s.brands), kv("其中竞品品牌", s.competitor_brands),
      kv("最早出现", s.first_seen), kv("最近更新", s.last_updated),
    ]),
  ]);
}

/* ---- 板块二：需求词组与市场结构 ---- */
function groupBand(d) {
  const el = ctx.el;
  const head = ["需求词组", "维度", "词数", "其中监控词", "月搜索量", "多算"];
  const max = Math.max(1, ...d.groups.map((g) => g.search_volume));
  const body = d.groups.slice(0, 20).map((g) => el("tr", {}, [
    el("td", { text: g.group_name }),
    el("td", { text: g.demand_dimension }),
    el("td", { class: "kw-num", text: ctx.fmt.int(g.term_count) }),
    el("td", { class: "kw-num", text: ctx.fmt.int(g.monitored_count) }),
    el("td", { class: "kw-gapcell" }, [
      el("span", { class: "kw-gapnum kw-wide", text: ctx.fmt.int(g.search_volume) }),
      bar(g.search_volume / max, "vol"),
    ]),
    el("td", {
      class: "kw-num" + (g.double_count ? " kw-warn-cell" : ""),
      text: g.double_count ? ctx.fmt.int(g.double_count) : "—",
    }),
  ]));
  const worst = d.groups.reduce((a, b) => (b.double_count > a.double_count ? b : a),
    d.groups[0] || { double_count: 0, group_name: "" });
  return sec("需求词组与市场结构",
    d.dedup_applied
      ? `一词多组按 1/组数 分权；不分权时「${worst.group_name}」会多算 `
        + `${ctx.fmt.int(worst.double_count)} 次月搜索量`
      : "当前未按权分摊，一词多组的搜索量在多个组里各算一次",
    el("div", { class: "kw-table-wrap" }, [table(head, body)]));
}

/* ---- 板块三：市场关键词比较区 ---- */
function compareBand(d) {
  const el = ellipsisHost();
  const head = ["关键词", "角色", "月搜索量", "购买率", "ABA 月排名", "在售商品数",
    "需供比", "广告竞品数", "头部三名点击占比", "两来源"];
  const body = d.terms.map((t) => el("tr", {
    class: "kw-row", "data-term": t.keyword_id,
  }, [
    el("td", {}, [
      el("span", { class: "kw-kwname", text: t.keyword }),
      t.keyword_cn ? el("span", { class: "kw-ev-meta", text: ` ${t.keyword_cn}` }) : null,
    ]),
    el("td", { text: t.operator_role_label || "—" }),
    el("td", { class: "kw-num", text: ctx.fmt.int(t.monthly_search_volume) }),
    el("td", { class: "kw-num", text: ctx.fmt.pct(t.purchase_rate, 2) }),
    el("td", { class: "kw-num", text: ctx.fmt.int(t.aba_month_rank) }),
    el("td", { class: "kw-num", text: ctx.fmt.int(t.product_count) }),
    el("td", { class: "kw-num", text: ctx.fmt.num(t.demand_supply_ratio, 2) }),
    el("td", { class: "kw-num", text: ctx.fmt.int(t.ad_competitor_count) }),
    el("td", { class: "kw-num", text: ctx.fmt.pct(t.click_share_top3, 1) }),
    el("td", {
      class: t.has_conflict ? "kw-warn-cell" : null,
      text: t.has_conflict ? `${t.conflict_fields.length} 项不一致` : "一致",
    }),
  ]));
  const tbl = table(head, body);
  tbl.addEventListener("click", (ev) => {
    const tr = ev.target.closest("tr[data-term]");
    if (tr) ctx.open(tr.dataset.term, "kw-market");
  });
  return sec("市场关键词比较区",
    [["匹配到的词", ctx.fmt.int(d.total_matched)],
      ["本页展示", ctx.fmt.int(d.shown)],
      ["两来源数值冲突", d.conflict_terms ? ctx.fmt.int(d.conflict_terms) : "本期无",
        d.conflict_terms ? "warn" : "zero"],
      ["冲突处理", "并列保留，不合并"]],
    el("div", { class: "kw-table-wrap" }, [tbl]));
}

function ellipsisHost() {
  return ctx.el;
}

/* ---- 单词深研 ---- */
function renderTermPage(d) {
  root.replaceChildren(
    sourceBand(d),
    termHead(d),
    termSeriesBand(d),
    termCompareBand(d),
    termHeadAsinBand(d),
    termRelationBand(d)
  );
}

function termHead(d) {
  const el = ctx.el;
  const i = d.identity;
  const m = d.series.month;
  const cur = m.length ? m[m.length - 1] : {};
  const chips = [
    chipText("词库状态", i.library_status_label),
    chipText("运营角色", i.operator_role_label
      + (i.operator_role_confirmed && i.operator_role !== "unset" ? "（已确认）" : "")),
    chipText("品牌属性", i.brand_role_label),
    chipText("数据性质", d.nature),
    i.is_monitored ? chipText("监控范围", "在内") : chipText("监控范围", "不在内"),
  ];
  const back = el("button", { class: "kw-fold", type: "button", text: "← 回词库" });
  back.addEventListener("click", () => ctx.open(null, "kw-market"));
  return el("section", { class: "kw-sec kw-hero" }, [
    back,
    el("div", { class: "kw-hero-main" }, [
      el("b", { text: ctx.fmt.int(cur.monthly_search_volume) }),
      el("span", { text: `「${i.keyword}」${i.keyword_cn || ""}　月搜索量` }),
    ]),
    el("div", { class: "kw-statrow" }, [
      stat("月购买量", cur.monthly_purchase_volume),
      stat("ABA 月排名", cur.aba_month_rank),
      stat("头部里的自有产品", d.own_in_head),
      stat("已建关系的子体", d.relations.length),
    ]),
    el("div", { class: "kw-chips" }, chips),
    el("div", { class: "kw-kv" }, [
      kv("所属类目", i.category_path), kv("主要分类", i.primary_category),
      kv("相关度", i.relevance),
      kv("角色种子词", i.operator_role_seed_word),
      kv("原始写法数", i.raw_variant_count),
    ]),
    d.aliases.length
      ? el("div", { class: "kw-sec-note",
        text: "同义与变体：" + d.aliases.map((a) =>
          `${a.alias_text}（${a.alias_type_label}）`).join("　") })
      : null,
    d.groups.length
      ? el("div", { class: "kw-sec-note",
        text: "所属需求词组：" + d.groups.map((g) =>
          `${g.group_name} × ${g.dedup_weight}`).join("　") })
      : null,
  ]);
}

/* 双频率两条线，绝不把月搜索量折算成周（方案 §6.3） */
function termSeriesBand(d) {
  const el = ctx.el;
  const s = d.series;
  const blocks = [
    lineChart("月度：搜索量（柱）与购买率（点）", s.month, "monthly_search_volume",
      s.month_measure, (x) => x.purchase_rate, "购买率"),
    // 标题必须写清哪个是柱哪个是点：原来写「ABA 排名与在售商品数」但柱画的是
    // 在售商品数，读的人会以为柱高是排名，正好读反。
    lineChart("周度：在售商品数（柱）与 ABA 周排名（点）", s.week, "product_count",
      s.week_measure, (x) => x.aba_week_rank, "ABA 周排名", true),
  ];
  const notes = [];
  if (s.not_comparable.length) {
    notes.push(el("div", { class: "kw-blocked",
      text: s.not_comparable.map((x) =>
        `${x.period_end}：${x.reason}`).join("；") }));
  }
  if (d.market_events.length) {
    notes.push(el("ul", { class: "kw-evlist" }, d.market_events.map((e) =>
      el("li", { class: "kw-ev" }, [
        el("div", { class: "kw-ev-head" }, [
          el("span", { class: "kw-tag", text: e.event_type_label }),
          el("span", { class: "kw-ev-meta", text: e.continuity_label }),
          el("span", { class: "kw-ev-meta",
            text: `${e.from_period_end || "—"} → ${e.to_period_end}` }),
        ]),
        el("div", { class: "kw-ev-concl", text: e.label }),
      ]))));
  }
  return sec("单词市场事实深研",
    "两种频率各自成线；月搜索量与周排名口径不同，不折算成同一周期",
    el("div", { class: "kw-band" }, blocks.concat(notes)));
}

function lineChart(title, series, key, measure, altFn, altLabel, invertAlt) {
  const el = ctx.el;
  const vals = series.map((x) => x[key]).filter((v) => v != null);
  if (!vals.length) {
    return el("div", { class: "kw-sec-note", text: `${title}：本期无数据` });
  }
  const lo = Math.min(...vals);
  const hi = Math.max(...vals);
  const span = Math.max(1, hi - lo);
  const alts = series.map(altFn).filter((v) => v != null);
  const aLo = alts.length ? Math.min(...alts) : 0;
  const aHi = alts.length ? Math.max(...alts) : 1;
  const aSpan = Math.max(1e-9, aHi - aLo);
  const cols = series.map((x) => {
    const v = x[key];
    const h = v == null ? 0 : 12 + ((v - lo) / span) * 88;
    const a = altFn(x);
    let ah = null;
    if (a != null) {
      const norm = (a - aLo) / aSpan;
      ah = 8 + (invertAlt ? 1 - norm : norm) * 84;
    }
    return el("div", {
      class: "kw-col",
      title: `${x.period_end}　${title.split("：")[1] || key} ${v == null ? "无" : v}`
        + (a == null ? "" : `　${altLabel} ${a}`)
        + `　${x.state}${x.comparable ? "" : "　本期不可比"}　${x.nature}`,
    }, [
      ah == null ? null : el("i", { class: "kw-dot", style: `bottom:${ah}%` }),
      el("i", { class: "kw-rankbar", style: `height:${h}%` }),
    ]);
  });
  return el("div", { class: "kw-chart" }, [
    el("div", { class: "kw-chart-axis" }, [
      el("span", { text: `${title}　${ctx.fmt.int(lo)} ~ ${ctx.fmt.int(hi)}` }),
      el("span", { text: `${series[0].period_end} ~ ${series[series.length - 1].period_end}` }),
    ]),
    el("div", { class: "kw-cols" }, cols),
    el("div", { class: "kw-legend" }, [
      el("span", { class: "kw-lg" }, [
        el("i", { class: "kw-rankbar kw-lg-dot" }),
        el("span", { text: title.split("：")[1] || key }),
      ]),
      el("span", { class: "kw-lg" }, [
        el("i", { class: "kw-dot kw-lg-dot kw-lg-static" }),
        el("span", { text: altLabel + (invertAlt ? "（越高越好）" : "") }),
      ]),
      measure ? el("span", { class: "kw-lg" }, [
        el("span", { text: measure })]) : null,
    ]),
  ]);
}

/* 两来源并列，冲突不合并 */
function termCompareBand(d) {
  const el = ctx.el;
  const head = ["指标", "关键词3", "关键词2", ""];
  const body = d.compare.map((c) => el("tr", {}, [
    el("td", { text: c.metric }),
    el("td", { class: "kw-num", text: fmtAny(c.primary) }),
    el("td", { class: "kw-num", text: fmtAny(c.second) }),
    el("td", {
      class: c.conflict ? "kw-warn-cell" : null,
      text: c.conflict ? "不一致" : (c.second == null ? "第二来源无此项" : "一致"),
    }),
  ]));
  return sec("两份来源的同期数值",
    [["对照项", ctx.fmt.int(body.length)],
      ["不一致", d.conflict_count ? ctx.fmt.int(d.conflict_count) : "本期无",
        d.conflict_count ? "warn" : "zero"],
      ["处理方式", "并列保留，不做合并"],
      ["第二来源", d.second_source_note || null]],
    el("div", { class: "kw-table-wrap" }, [table(head, body)]));
}

function fmtAny(v) {
  if (v == null) return "—";
  if (typeof v === "number" && !Number.isInteger(v)) return ctx.fmt.num(v, 4);
  return ctx.fmt.int(v);
}

/* 头部 ASIN 与竞品证据入口。头部 ASIN 不等于已确认竞品。
   前三名带点击与转化共享，4-10 名源表只给 ASIN —— 分两段呈现，
   不要拉成一张表让 7 行共享列全是「—」，那看起来像坏了。 */
function termHeadAsinBand(d) {
  const el = ctx.el;
  const top3 = d.head_asins.filter((h) => h.rank_slot <= 3);
  const rest = d.head_asins.filter((h) => h.rank_slot > 3);
  const head = ["位次", "ASIN", "点击共享", "转化共享", "归属"];
  const body = top3.map((h) => el("tr", {
    class: h.is_own_asin ? "kw-own-row" : null,
  }, [
    el("td", { class: "kw-num", text: h.rank_slot }),
    el("td", { text: h.asin }),
    el("td", { class: "kw-num", text: ctx.fmt.pct(h.click_share, 2) }),
    el("td", { class: "kw-num", text: ctx.fmt.pct(h.conversion_share, 2) }),
    el("td", { text: h.is_own_asin ? "自有产品" : "外部 ASIN" }),
  ]));
  const hist = d.head_slot1_history;
  const note = d.head_replaced && hist.length
    ? `第一名在窗口内换过人：${hist[0][1]} → ${hist[hist.length - 1][1]}，`
      + "需要进竞品分析核对价格、促销与流量是否同期变化"
    : "第一名在窗口内没有变化";
  const parts = [el("div", { class: "kw-table-wrap" }, [table(head, body)])];
  if (rest.length) {
    parts.push(el("div", { class: "kw-sec-note", text: `第 4-10 名` }));
    parts.push(el("div", { class: "kw-chips" }, rest.map((h) =>
      el("span", {
        class: "kw-chip" + (h.is_own_asin ? " kw-chip-own" : ""),
        text: `${h.rank_slot}. ${h.asin}${h.is_own_asin ? "　自有" : ""}`,
      }))));
  }
  return sec("头部 ASIN 与竞品线索", note, el("div", { class: "kw-band" }, parts));
}

/* 关键词与产品关系区：绑定子体后才出产品判断 */
function termRelationBand(d) {
  const el = ctx.el;
  if (!d.relations.length) {
    return sec("关键词与产品关系",
      "这个词还没有和任何子体建立关系，因此只给市场事实，不给产品机会结论",
      el("div", { class: "kw-pending", text: "无已建立关系的子 ASIN" }));
  }
  const head = ["子 ASIN", "款号", "锚点", "当前自然位", "当前广告位", "状态",
    "当前目标", "库存承接"];
  const body = d.relations.map((r) => el("tr", {
    class: "kw-row" + (r.weak ? " kw-warn-row" : ""), "data-child": r.child_asin,
  }, [
    el("td", { text: r.child_asin }),
    el("td", { text: r.style_no || "—" }),
    el("td", { text: r.anchor_band_label || "构造" }),
    el("td", { class: "kw-num", text: r.organic_rank == null ? "—" : r.organic_rank }),
    el("td", { class: "kw-num", text: r.ad_rank == null ? "—" : r.ad_rank }),
    el("td", { text: r.organic_state_label }),
    el("td", { text: r.product_goal_label || "—" }),
    el("td", { text: r.absorb_state_label || "—" }),
  ]));
  const tbl = table(head, body);
  tbl.addEventListener("click", (ev) => {
    const tr = ev.target.closest("tr[data-child]");
    if (tr) ctx.open(tr.dataset.child, "kw-child");
  });
  const evList = d.evidence.length
    ? el("ul", { class: "kw-evlist" }, d.evidence.slice(0, 6).map((e) =>
      el("li", { class: "kw-ev" }, [
        el("div", { class: "kw-ev-head" }, [
          el("span", { class: "kw-tag", text: e.evidence_type_label }),
          el("span", { class: "kw-ev-kw", text: e.child_asin }),
          el("span", { class: "kw-ev-meta", text: e.evidence_completeness_label }),
          el("span", { class: "kw-ev-meta", text: e.next_verification_label }),
        ]),
        el("div", { class: "kw-ev-concl", text: e.conclusion }),
        el("div", { class: "kw-ev-basis", text: e.main_basis }),
      ])))
    : el("div", { class: "kw-sec-note", text: "这个词上还没有形成产品级证据结论" });
  return sec("关键词与产品关系",
    [["已建立关系的子体", ctx.fmt.int(d.relations.length)],
      ["操作", "点行进入该子体的关键词盘点"]],
    el("div", { class: "kw-band" }, [
      el("div", { class: "kw-table-wrap" }, [tbl]), evList,
    ]));
}

/* ================= 页面三：子 ASIN 关键词盘点 ================= */

function renderChildPage(d) {
  root.replaceChildren(
    sourceBand(d),
    decisionBand(d),
    contextBand(d.context),
    coverageBand(d.coverage),
    positionBand(d.positions),
    evidenceBand(d.evidence),
    auditBand(d.audits)
  );
}

/* 板块外壳。第二参数原来只收一段散文，现在也收 [[标签, 值], ...]
   —— 收数组就渲染成指标条，收字符串仍按口径说明渲染（口径确实是句子）。 */
function sec(title, note, body) {
  const el = ctx.el;
  const head = [el("div", { class: "kw-sec-title", text: title })];
  if (Array.isArray(note)) {
    const m = metrics(note);
    if (m) head.push(m);
  } else if (note) {
    head.push(el("div", { class: "kw-sec-note", text: note }));
  }
  return el("section", { class: "kw-sec" }, [
    el("div", { class: "kw-sec-head" }, head), body,
  ]);
}

/* ---- 决策摘要：一个主数字 + 少量支撑，不做四张等权卡 ---- */
function decisionBand(d) {
  const el = ctx.el;
  const f = ctx.fmt;
  const top = d.evidence.items[0];
  const risk = (d.evidence.type_counts.find((t) => t.name === "核心位置风险") || {}).n || 0;
  const gapGroups = d.coverage.groups.filter((g) => g.gap > 0).length;
  const declining = d.positions.tracks.filter((t) => t.is_continuous_decline).length;
  const toAds = d.evidence.items.filter(
    (e) => e.next_verification_label === "进入广告决策处理").length;
  // 支撑槽固定，但选的是在覆盖丰富与零覆盖两类子体上都有值的四项。
  // 「自然位偏弱」不放这里：锚点齐全的子体上它恒为 0，留在覆盖结构板块里。
  return el("section", { class: "kw-sec kw-hero" }, [
    el("div", { class: "kw-hero-main" }, [
      el("b", { text: f.int(d.evidence.total) }),
      el("span", { text: `${d.child_asin} 待处理的关键词事项` }),
    ]),
    el("div", { class: "kw-statrow" }, [
      stat("有缺口的需求词组", gapGroups),
      stat("自然位在连续走弱", declining),
      stat("核心位置风险", risk),
      stat("待交给广告决策", toAds),
    ]),
    top ? el("div", { class: "kw-top-call" }, [
      el("span", { class: "kw-tag", text: top.evidence_type_label }),
      el("span", { class: "kw-top-text", text: top.conclusion }),
    ]) : null,
  ]);
}

/* ---- 板块一：产品上下文 ---- */
function contextBand(c) {
  const el = ctx.el;
  const chips = [
    c.product_goal_label && chipText("当前目标", c.product_goal_label),
    c.push_role_label && chipText("主推关系", c.push_role_label),
    c.lifecycle && chipText("产品阶段", c.lifecycle),
    c.absorb_state_label && chipText("库存承接", c.absorb_state_label),
    chipText("数据性质", c.nature),
  ].filter(Boolean);
  const rows = [
    el("div", { class: "kw-chips" }, chips),
    el("div", { class: "kw-kv" }, [
      kv("父体", c.parent_asin), kv("款号", c.style_no),
      kv("颜色", c.colorway), kv("尺码", c.size),
      kv("装盒", c.combination), kv("小类排名", c.category_rank),
      kv("评分", c.rating), kv("最晚下单日", c.latest_order_date),
    ]),
  ];
  if (c.absorb_detail) {
    rows.push(el("div", { class: "kw-sec-note", text: c.absorb_detail }));
  }
  if (c.goal_history.length) {
    rows.push(el("div", { class: "kw-sec-note",
      text: `目标改过：${c.goal_history.map((g) =>
        `${g.from} 起为「${g.product_goal_label}」`).join("；")}` }));
  }
  for (const r of c.blocked_reasons || []) {
    rows.push(el("div", { class: "kw-blocked", text: r }));
  }
  return sec(`${c.child_asin}　${c.product_name || ""}`,
    [["关键词关系", ctx.fmt.int(c.pair_count)],
      ["有客户榜单锚点", c.anchored_count ? ctx.fmt.int(c.anchored_count) : "本期无",
        c.anchored_count ? null : "zero"],
      ["锚点占比", c.pair_count
        ? ctx.fmt.pct(c.anchored_count / c.pair_count, 0) : null]],
    el("div", { class: "kw-band" }, rows));
}

/* ---- 板块二：覆盖结构 ----
   原来是六个并排数字加一张表。六个数看得出大小，看不出构成比例，
   而这块要回答的就是「这个子体的覆盖长什么样」—— 那是个比例问题。
   organic_only / both / ad_only / not_covered 是真分区（不重叠），
   能直接画成一条堆叠条；organic_covered 与 ad_covered 是它们的合计，
   混进同一条会重复计数，所以只留在指标条里。 */
function coverageBand(cov) {
  const el = ctx.el;
  const s = cov.summary;
  const head = ["需求词组", "维度", "组内监控词", "本子体相关", "组内覆盖率",
    "自然覆盖", "广告覆盖", "缺口"];
  const maxGap = Math.max(1, ...cov.groups.map((g) => g.gap));
  const body = cov.groups.map((g) => el("tr", {}, [
    el("td", { text: g.group_name }),
    el("td", { text: g.demand_dimension }),
    el("td", { class: "kw-num", text: ctx.fmt.num(g.monitored_in_group, 0) }),
    el("td", { class: "kw-num", text: ctx.fmt.num(g.related_here, 0) }),
    // 用「本子体相关 ÷ 组内监控词」而不是「自然覆盖 ÷ 本子体相关」：
    // 后者在锚点齐全的子体上整列恒为 100%，一列没有信息量。
    // 上色阶：一列扫下来深浅就是排序，不用逐行读百分数。
    heatCell(ctx.fmt.pct(g.group_reach, 0), g.group_reach, "good"),
    el("td", { class: "kw-num", text: ctx.fmt.num(g.organic_covered, 0) }),
    el("td", { class: "kw-num", text: ctx.fmt.num(g.ad_covered, 0) }),
    el("td", { class: "kw-gapcell", "data-sort": g.gap }, [
      el("span", { class: "kw-gapnum", text: ctx.fmt.num(g.gap, 0) }),
      bar(g.gap / maxGap, "gap"),
    ]),
  ]));
  const partition = (s.organic_only || 0) + (s.both_covered || 0)
    + (s.ad_only || 0) + (s.not_covered || 0);
  const rest = Math.max(0, (s.related || 0) - partition);
  return sec("关键词覆盖结构",
    [["本子体相关词", ctx.fmt.int(s.related)],
      ["有自然位", ctx.fmt.int(s.organic_covered)],
      ["有广告位", ctx.fmt.int(s.ad_covered)],
      [`自然位在第 ${s.weak_rank_threshold} 位之后`,
        s.weak_position ? ctx.fmt.int(s.weak_position) : "本期无",
        s.weak_position ? "warn" : "zero"],
      ["缺口口径", cov.dedup_applied ? "一词多组按权分摊" : "未按权分摊"]],
    el("div", { class: "kw-band" }, [
      stackBar([
        { label: "自然与广告同时有", n: s.both_covered, kind: "good" },
        { label: "只有自然位", n: s.organic_only, kind: "calm" },
        { label: "只有广告位", n: s.ad_only, kind: "warn" },
        { label: "确认未覆盖", n: s.not_covered, kind: "alert" },
        { label: "其余状态", n: rest, kind: "mut" },
      ]),
      el("div", { class: "kw-table-wrap" },
        [sortable(table(head, body), [2, 3, 4, 5, 6, 7])]),
    ]));
}

/* ---- 板块三：自然位与广告位变化 ----
   「最好 71 / 最差 77」两个并排数字读不出波动幅度，也读不出这个词整体
   处在深位还是浅位。合成一条轨道加游标：轨道左端是第 1 位，
   横条是最好到最差的跨度，圆点是当前位置。跨度长 = 这个词在颠。 */
function positionBand(p) {
  const el = ctx.el;
  const tracks = p.tracks.slice(0, 12);
  const head = ["关键词", "角色", "锚点", "当前自然位", "当前广告位", "状态",
    "位次区间（左=第1位）", "连降天数", "趋势"];
  const body = tracks.map((t) => el("tr", { class: t.is_continuous_decline ? "kw-warn-row" : null }, [
    el("td", { text: t.keyword }),
    el("td", { text: t.operator_role_label || "—" }),
    el("td", { text: t.anchor_band_label || "—" }),
    el("td", { class: "kw-num", text: t.current_organic == null ? "—" : t.current_organic }),
    el("td", { class: "kw-num", text: t.current_ad == null ? "—" : t.current_ad }),
    el("td", { text: t.current_state_label }),
    el("td", { class: "kw-rangecell", "data-sort": t.best_rank == null ? 9999 : t.best_rank },
      [rangeTrack(t.best_rank, t.current_organic, t.worst_rank, p.collect_depth)]),
    el("td", { class: "kw-num" + (t.is_continuous_decline ? " kw-warn-cell" : ""),
      text: t.down_streak_days ? `${t.down_streak_days} 天` : "—",
      "data-sort": t.down_streak_days || 0 }),
    el("td", {}, [sparkBars(t.points)]),
  ]));
  const declines = p.tracks.filter((t) => t.is_continuous_decline).length;
  return sec("自然位与广告位变化",
    [["窗口", `${p.date_from} ~ ${p.date_to}`],
      ["自然位采集深度", `第 ${p.collect_depth} 位`],
      ["自然位连续走弱", declines ? `${declines} 个词` : "本期无",
        declines ? "warn" : "zero"],
      ["采集失败", (p.collect_fail_days || []).length
        ? `${p.collect_fail_days.length} 天　${p.collect_fail_days.join("、")}`
        : "本期无", (p.collect_fail_days || []).length ? "warn" : "zero"],
      ["展开", `${tracks.length} / ${p.tracks.length} 个词`]],
    el("div", { class: "kw-band" }, [
      dayChart(p),
      stackBar((p.event_counts || []).map((e) => ({
        label: e.name, n: e.n,
        kind: /下降|丢失|跌出|失败/.test(e.name) ? "alert"
          : /上涨|新增/.test(e.name) ? "good" : "calm",
      }))),
      el("div", { class: "kw-table-wrap" },
        [sortable(table(head, body), [3, 4, 6, 7])]),
    ]));
}

/* 逐日图。主信息是平均自然位（位次越好条越高），五态构成降为底部细带。
   不用五态堆叠柱：覆盖齐全的子体上 covered 占九成以上，整张图是一片纯黑，
   看不出任何结构；位次趋势才是这块要回答的问题。
   采集失败日与未纳入监控是状态区间，画成背景不占泳道。 */
function dayChart(p) {
  const el = ctx.el;
  const ranks = p.daily.map((d) => d.avg_organic_rank).filter((v) => v != null);
  const lo = ranks.length ? Math.min(...ranks) : 1;
  const hi = ranks.length ? Math.max(...ranks) : 1;
  const span = Math.max(1, hi - lo);
  const stateMax = Math.max(1, ...p.daily.map((d) =>
    d.covered + d.not_covered + d.beyond_depth + d.collect_failed + d.not_monitored));

  const cols = p.daily.map((d) => {
    const v = d.avg_organic_rank;
    const h = v == null ? 0 : 14 + (1 - (v - lo) / span) * 86;
    const band = [
      ["covered", d.covered], ["weak", d.beyond_depth], ["none", d.not_covered],
      ["fail", d.collect_failed], ["off", d.not_monitored],
    ].filter(([, n]) => n > 0).map(([k, n]) =>
      el("i", { class: `kw-seg kw-seg-${k}`, style: `flex:${n / stateMax} 1 0` }));
    return el("div", {
      class: "kw-col" + (d.is_collect_fail_day ? " kw-col-fail" : ""),
      title: `${d.date}　平均自然位 ${v == null ? "无" : v}`
        + `　有排名 ${d.covered}　确认未覆盖 ${d.not_covered}`
        + `　超出采集深度 ${d.beyond_depth}　当日采集失败 ${d.collect_failed}`
        + `　未纳入监控 ${d.not_monitored}`,
    }, [
      el("i", { class: "kw-rankbar", style: h ? `height:${h}%` : "height:0" }),
      el("span", { class: "kw-stateband" }, band),
    ]);
  });

  const legend = [["covered", "有排名"], ["weak", "超出采集深度"], ["none", "确认未覆盖"],
    ["fail", "当日采集失败"], ["off", "未纳入监控"]].map(([k, label]) =>
    el("span", { class: "kw-lg" }, [
      el("i", { class: `kw-seg kw-seg-${k} kw-lg-dot` }),
      el("span", { text: label }),
    ]));
  return el("div", { class: "kw-chart" }, [
    // 值域写成一句，不左右分置 —— 分置会被读成「左边是起点、右边是终点」，
    // 而它其实是纵轴的上下端；这次数据恰好也是从好走到差，更容易误读。
    el("div", { class: "kw-chart-axis" }, [
      el("span", { text: `当日平均自然位 第 ${lo} 位（最好）~ 第 ${hi} 位（最差）` }),
      el("span", { text: `${p.date_from} ~ ${p.date_to}` }),
    ]),
    el("div", { class: "kw-cols" }, cols),
    el("div", { class: "kw-legend" }, [
      el("span", { class: "kw-lg" }, [
        el("i", { class: "kw-rankbar kw-lg-dot" }),
        el("span", { text: "当日平均自然位（条越高位置越好）" }),
      ]),
      ...legend,
    ]),
  ]);
}

/* CSS-only sparkline：位次越好条越高。不用 SVG，避免 createElementNS。 */
function sparkBars(points) {
  const el = ctx.el;
  const vals = points.map((x) => x.organic);
  const nums = vals.filter((v) => v != null);
  if (!nums.length) return el("span", { class: "kw-sec-note", text: "无排名区间" });
  const lo = Math.min(...nums);
  const hi = Math.max(...nums);
  const span = Math.max(1, hi - lo);
  return el("span", { class: "kw-spark" }, vals.map((v) =>
    el("i", {
      class: "kw-spark-bar" + (v == null ? " kw-spark-gap" : ""),
      style: v == null ? null : `height:${12 + (1 - (v - lo) / span) * 88}%`,
    })));
}

/* ---- 板块四：缺口、机会与风险 ---- */
/* 同类折叠：主演示对象 36 条里 13 条是核心位置风险，文案高度雷同，
   全铺出来是模板刷屏。每类最多展开 3 条，其余收成一行可展开的同类计数。 */
const EV_EXPAND = 3;

function evidenceBand(ev) {
  const el = ctx.el;
  const byType = new Map();
  for (const e of ev.items) {
    if (!byType.has(e.evidence_type_label)) byType.set(e.evidence_type_label, []);
    byType.get(e.evidence_type_label).push(e);
  }
  const blocks = [];
  for (const [type, list] of byType) {
    const shown = list.slice(0, EV_EXPAND);
    blocks.push(el("li", { class: "kw-ev-group" }, [
      el("div", { class: "kw-ev-grouphead" }, [
        el("span", { class: "kw-tag", text: type }),
        el("span", { class: "kw-ev-meta", text: `${list.length} 条` }),
      ]),
      el("ul", { class: "kw-evlist" }, shown.map(evItem)),
      list.length > shown.length ? foldRow(type, list.slice(EV_EXPAND)) : null,
    ]));
  }
  return sec("关键词缺口、机会与风险",
    [["证据条数", ctx.fmt.int(ev.total)],
      ["证据类型", `${ev.type_counts.length} 类`],
      ["同类展开", `前 ${EV_EXPAND} 条`],
      ["排序权重", ev.weights ? Object.values(ev.weights)
        .map((v) => ctx.fmt.pct(v, 0)).join(" / ") : null]],
    el("div", { class: "kw-band" }, [
      stackBar(ev.type_counts.map((t) => ({
        label: t.name, n: t.n,
        kind: /风险/.test(t.name) ? "alert" : /机会/.test(t.name) ? "good"
          : /不足|待/.test(t.name) ? "mut" : "calm",
      }))),
      el("ul", { class: "kw-evlist" }, blocks),
    ]));
}

function evItem(e) {
  const el = ctx.el;
  return el("li", { class: "kw-ev" }, [
    el("div", { class: "kw-ev-head" }, [
      el("span", { class: "kw-ev-kw", text: e.keyword }),
      el("span", { class: "kw-ev-meta", text: e.evidence_completeness_label }),
      el("span", { class: "kw-ev-meta", text: e.next_verification_label }),
    ]),
    el("div", { class: "kw-ev-concl", text: e.conclusion }),
    el("div", { class: "kw-ev-basis", text: e.main_basis }),
    e.inventory_limit_label
      ? el("div", { class: "kw-ev-limit", text: `库存限制：${e.inventory_limit_label}` })
      : null,
  ]);
}

function foldRow(type, rest) {
  const el = ctx.el;
  const list = el("ul", { class: "kw-evlist", hidden: "" }, rest.map(evItem));
  const btn = el("button", {
    class: "kw-fold", type: "button",
    text: `另有 ${rest.length} 条${type}，展开`,
  });
  btn.addEventListener("click", () => {
    const open = !list.hasAttribute("hidden");
    if (open) {
      list.setAttribute("hidden", "");
      btn.textContent = `另有 ${rest.length} 条${type}，展开`;
    } else {
      list.removeAttribute("hidden");
      btn.textContent = `收起这 ${rest.length} 条`;
    }
  });
  return el("div", { class: "kw-foldwrap" }, [btn, list]);
}

/* ---- 板块五：盘点记录 ---- */
function auditBand(au) {
  const el = ctx.el;
  const head = ["盘点日期", "关系数", "有自然位", "有广告位", "双覆盖",
    "覆盖未确认", "最好位次", "中位位次", "证据条数", "与上次比"];
  const body = au.runs.map((r) => {
    const d = r.delta;
    return el("tr", {}, [
      el("td", { text: r.run_date }),
      el("td", { class: "kw-num", text: ctx.fmt.int(r.pair_count) }),
      el("td", { class: "kw-num", text: ctx.fmt.int(r.organic_covered_count) }),
      el("td", { class: "kw-num", text: ctx.fmt.int(r.ad_covered_count) }),
      el("td", { class: "kw-num", text: ctx.fmt.int(r.both_covered_count) }),
      el("td", { class: "kw-num", text: ctx.fmt.int(r.unconfirmed_count) }),
      el("td", { class: "kw-num", text: r.best_organic_rank == null ? "—" : r.best_organic_rank }),
      el("td", { class: "kw-num", text: r.median_organic_rank == null ? "—" : r.median_organic_rank }),
      el("td", { class: "kw-num", text: ctx.fmt.int(r.evidence_count) }),
      el("td", { text: d ? deltaText(d) : "首次盘点" }),
    ]);
  });
  return sec("关键词盘点记录", "同一子体历次盘点，用来比较关键词状态的变化",
    el("div", { class: "kw-table-wrap" }, [table(head, body)]));
}

function deltaText(d) {
  const parts = [];
  if (d.organic_covered) parts.push(`自然位 ${sign(d.organic_covered)}`);
  if (d.ad_covered) parts.push(`广告位 ${sign(d.ad_covered)}`);
  if (d.median_organic_rank) {
    parts.push(`中位位次 ${d.median_organic_rank > 0 ? "退" : "进"}`
      + `${Math.abs(d.median_organic_rank)} 位`);
  }
  if (d.unconfirmed) parts.push(`未确认 ${sign(d.unconfirmed)}`);
  return parts.length ? parts.join("，") : "无变化";
}

function sign(n) {
  return (n > 0 ? "+" : "") + n;
}

/* 判断来源条。读 `agent_result` —— 那是 modules/keyword/agent_result.py 的选库结果，
   六个路由都会带。三态与它的 condition 一一对应：

     缺失 → 没有已发布的 Agent 结果，页面显示的判断层内容是构造脚手架
     过期 → Agent 发布时的参数（比较周期 / 优先级权重）与当前请求不一致
     正常 → 正在用 Agent 那一份，run_id 就是这次的身份

   为什么必须上屏：《07-Agent运行与落库口径.md》§七 —— 上游没跑过时下游必须
   降级说明，不能悄悄回落到预烤值。缺失态尤其要说，否则页面上那些结论看起来
   像是 Agent 判的。 */
function sourceBand(d) {
  const el = ctx.el;
  const a = d && d.agent_result;
  if (!a) return null;
  const cond = a.condition || "缺失";
  const kind = cond === "正常" ? "agent" : cond === "过期" ? "stale" : "scaffold";
  const figs = cond === "正常"
    ? [["本次 run", a.run_id || "—"], ["判断层来源", "Agent 产出", "good"]]
    : cond === "过期"
      ? [["已发布的 run", a.run_id || "—"],
        ["当前用的", "构造脚手架", "warn"],
        ["原因", "参数与该 run 不一致"]]
      : [["判断层来源", "构造脚本产出", "warn"],
        ["Agent 结果", "尚未发布"]];
  const label = cond === "正常" ? "本次 Agent 判断"
    : cond === "过期" ? "Agent 结果已过期，本页回落到构造内容"
      : "尚未接入关键词 Agent";
  return el("section", {
    class: "kw-sec kw-srcband",
    "data-source": kind,
  }, [
    el("div", { class: "kw-sec-head" }, [
      el("div", { class: "kw-sec-title kw-srctitle" }, [
        el("i", { class: "kw-srcdot" }),
        el("span", { text: label }),
      ]),
      metrics(figs),
    ]),
    a.message ? el("div", { class: "kw-srcdetail", text: a.message }) : null,
  ]);
}

/* ---- 小件 ---- */

/* 指标条：板块标题下原来挂的是一段拼接出来的散文，改成「标签 + 值」两段式。
   这是覆盖面最大的一处改动 —— 想写一句话就得先给它起个三五字的标签，
   散文在这个结构里没有落地的地方。空值直接不出，不留空槽。 */
function metrics(items) {
  const el = ctx.el;
  const cells = (items || []).filter((x) => x && x[1] !== null
    && x[1] !== undefined && x[1] !== "").map(([lab, v, kind]) =>
    el("span", { class: "kw-m" + (kind ? ` kw-m-${kind}` : "") }, [
      el("em", { text: lab }),
      el("b", { text: String(v) }),
    ]));
  return cells.length ? el("div", { class: "kw-metrics" }, cells) : null;
}

/* 堆叠比例条：把「六个数字并排」换成一条按比例分段的条。
   构成比例是数字列表读不出来的东西 —— 六个数看得出大小，看不出谁占几成。
   段宽用百分比内联，零值段不渲染（渲染成 0 宽会留下一条缝）。 */
function stackBar(segments) {
  const el = ctx.el;
  const rows = (segments || []).filter((s) => s && s.n > 0);
  if (!rows.length) return null;
  const total = rows.reduce((a, s) => a + s.n, 0);
  return el("div", { class: "kw-stackwrap" }, [
    el("div", { class: "kw-stack" }, rows.map((s) => el("i", {
      class: `kw-stack-seg kw-seg-${s.kind || "calm"}`,
      style: `width:${(s.n / total) * 100}%`,
      title: `${s.label}　${ctx.fmt.int(s.n)}　${ctx.fmt.pct(s.n / total, 0)}`,
    }))),
    el("div", { class: "kw-stacklegend" }, rows.map((s) =>
      el("span", { class: `kw-lg kw-seg-${s.kind || "calm"}` }, [
        el("i", {}), el("span", { text: s.label }),
        el("b", { text: ctx.fmt.int(s.n) }),
      ]))),
  ]);
}

/* 区间游标：最好 / 当前 / 最差三个数字画成一条轨道加一个游标。
   位次是反向量（第 1 位最好），所以轨道左端是 1，游标越靠左越好；
   最好到最差的跨度就是波动幅度 —— 三个并排的数字读不出这件事。 */
function rangeTrack(best, cur, worst, cap) {
  const el = ctx.el;
  if (best == null || worst == null) return el("span", { class: "kw-na", text: "—" });
  const hi = Math.max(cap || 1, worst, 1);
  const pos = (v) => Math.max(0, Math.min(100, ((v - 1) / hi) * 100));
  const span = Math.max(1.5, pos(worst) - pos(best));
  return el("span", {
    class: "kw-range",
    title: `最好第 ${best} 位 · 最差第 ${worst} 位`
      + (cur == null ? "" : ` · 当前第 ${cur} 位`),
  }, [
    el("i", { class: "kw-range-span", style: `left:${pos(best)}%;width:${span}%` }),
    cur == null ? null
      : el("i", { class: "kw-range-dot", style: `left:${pos(cur)}%` }),
  ]);
}

/* 色阶格：数值自己带上背景浓度，一列扫下来深浅就是排序。
   契约禁止模块定义新色值，所以不用 color-mix，改嵌套 <i> 调 opacity，
   底色只引用已有的语义 token。 */
function heatCell(text, ratio, kind) {
  const el = ctx.el;
  const r = Math.max(0, Math.min(1, ratio || 0));
  return el("td", { class: "kw-num kw-heat" }, [
    el("i", { class: `kw-heat-bg kw-seg-${kind || "vol"}`,
      style: `opacity:${(r * 0.5).toFixed(3)}` }),
    el("span", { text: text }),
  ]);
}

/* 数值列点表头排序。ads 模块没有排序，但关键词这几张表更长，
   而「谁最大」是这些表要回答的第一个问题。
   取值从 data-sort 读，没有就退回 textContent 去掉千分位。 */
function sortable(tableEl, numCols) {
  const ths = tableEl.querySelectorAll("thead th");
  const state = { col: -1, dir: -1 };
  numCols.forEach((ci) => {
    const th = ths[ci];
    if (!th) return;
    th.classList.add("kw-th-sort");
    th.addEventListener("click", () => {
      state.dir = state.col === ci ? -state.dir : -1;
      state.col = ci;
      ths.forEach((t) => t.removeAttribute("data-dir"));
      th.setAttribute("data-dir", state.dir < 0 ? "desc" : "asc");
      const tb = tableEl.querySelector("tbody");
      const val = (tr) => {
        const td = tr.children[ci];
        if (!td) return -Infinity;
        if (td.dataset.sort !== undefined) return Number(td.dataset.sort);
        const n = parseFloat(String(td.textContent).replace(/[,%\s]/g, ""));
        return Number.isNaN(n) ? -Infinity : n;
      };
      Array.from(tb.children)
        .sort((a, b) => (val(a) - val(b)) * state.dir)
        .forEach((tr) => tb.appendChild(tr));
    });
  });
  return tableEl;
}

function table(head, body) {
  const el = ctx.el;
  return el("table", { class: "kw-table" }, [
    el("thead", {}, [el("tr", {}, head.map((t) => el("th", { text: t })))]),
    el("tbody", {}, body),
  ]);
}

function bar(ratio, kind) {
  return ctx.el("span", { class: `kw-bar kw-bar-${kind}` }, [
    ctx.el("i", { style: `width:${Math.max(2, Math.min(100, ratio * 100))}%` }),
  ]);
}

function kv(label, value) {
  if (value == null || value === "") return null;
  return ctx.el("span", { class: "kw-kv-item" }, [
    ctx.el("span", { text: label }),
    ctx.el("b", { text: String(value) }),
  ]);
}

function chipText(label, value) {
  return ctx.el("span", { class: "kw-chip" }, [
    ctx.el("span", { text: label + " " }),
    ctx.el("b", { text: value }),
  ]);
}

/* ---------------- 范围与数据状态 ---------------- */
function scopeBand() {
  const el = ctx.el;
  const f = ctx.fmt;
  const d = meta;
  const dist = d.distributions;
  return el("section", { class: "kw-band" }, [
    el("div", { class: "kw-lead" }, [
      el("b", { text: f.int(d.library_terms) }),
      el("span", { text: "共享市场词库（唯一关键词）" }),
    ]),
    el("div", { class: "kw-statrow" }, [
      stat("监控词", d.monitored_terms),
      stat("重点子 ASIN", d.focus_children),
      stat("关键词 × 子ASIN 关系", d.counts.pair),
      stat("逐日位置记录", d.counts.position_daily),
      stat("证据结论", d.counts.evidence),
      stat("暂不可比较的快照", d.not_comparable_rows),
    ]),
    chips(dist.library_status),
    chips(dist.position_state),
    el("div", { class: "kw-chips" }, [
      chip(`周快照 ${d.window.week[0]} ~ ${d.window.week[1]}`, 26),
      chip(`月快照 ${d.window.month[0]} ~ ${d.window.month[1]}`, 12),
      chip(`逐日位置 ${d.window.position[0]} ~ ${d.window.position[1]}`,
        d.counts.position_daily),
      chip("自然位采集深度", d.window.collect_depth),
    ]),
  ]);
}

function stat(label, value) {
  const el = ctx.el;
  // 0 是真实信号（覆盖齐全的子体上「核心位置风险」本来就是 0），
  // 但裸的粗体 0 读起来像板块坏了。0 降调并写「本期无」，读成「查过，没有」。
  const zero = value === 0 || value === null || value === undefined;
  return el("div", { class: "kw-stat" + (zero ? " kw-stat-zero" : "") }, [
    el("b", { text: zero ? "本期无" : ctx.fmt.int(value) }),
    el("span", { text: label }),
  ]);
}

function chip(label, n) {
  const el = ctx.el;
  return el("span", { class: "kw-chip" }, [
    el("span", { text: label + " " }),
    el("b", { text: ctx.fmt.int(n) }),
  ]);
}

function chips(list) {
  return ctx.el("div", { class: "kw-chips" }, (list || []).map((s) => chip(s.label, s.n)));
}

/* ---------------- 子体清单（页面三入口） ---------------- */
async function childList() {
  const el = ctx.el;
  const d = await ctx.api("children");
  const head = ["子 ASIN", "父体", "款号", "关系词数", "真实锚点", "产品目标",
    "主推关系", "库存承接"];
  const rows = d.rows.map((r) =>
    el("tr", { class: "kw-row", "data-child": r.child_asin }, [
      el("td", { text: r.child_asin }),
      el("td", { text: r.parent_asin }),
      el("td", { text: r.style_no || "—" }),
      el("td", { class: "kw-num", text: ctx.fmt.int(r.pair_count) }),
      el("td", { class: "kw-num", text: ctx.fmt.int(r.anchor_count) }),
      el("td", { text: r.product_goal_label || "—" }),
      el("td", { text: r.push_role_label || "—" }),
      el("td", { text: r.absorb_state_label || "—" }),
    ]));
  const table = el("table", { class: "kw-table" }, [
    el("thead", {}, [el("tr", {}, head.map((t) => el("th", { text: t })))]),
    el("tbody", {}, rows),
  ]);
  table.addEventListener("click", (ev) => {
    const tr = ev.target.closest("tr[data-child]");
    // 选中对象由外壳持有（契约 8.3 / 8.8：URL 即状态），模块不自己碰 history
    if (tr) ctx.open(tr.dataset.child, "kw-child");
  });
  return ctx.el("section", { class: "kw-band" }, [
    ctx.el("div", { class: "kw-stat" }, [
      ctx.el("b", { text: `${d.total} 个重点子 ASIN` }),
      ctx.el("span", { text: "按真实锚点数降序；锚点来自客户头部与前十字段" }),
    ]),
    ctx.el("div", { class: "kw-table-wrap" }, [table]),
  ]);
}

function pending(body) {
  return ctx.el("section", { class: "kw-band kw-pending" }, [
    ctx.el("div", { text: body && body.message ? body.message : "待实装" }),
  ]);
}
