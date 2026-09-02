/* 广告分析模块 · 前端（契约 8.2）
 *
 * 零全局：只有 export，不往 window / globalThis 挂东西。
 * $ / el / 格式化 / 浮层 / 抽屉 / 徽标全部从 ctx 取，不自己实现。
 *
 * 页面二形态：Agent 不自动跑。
 *   进页面 → context → 渲染板块 1/2/3/5，板块 4/6/7/8 是压低的空壳
 *   点「开始分析」→ run → 四段按序揭示，前端逐段填
 *   点某条方案的决定 → decide → 板块9 交接
 *
 * 「可核验」靠一条机制：Agent 每条输出的 evidence_ids 只引用 context.evidence
 * 里的 id，渲染成可点 chip，点了滚到对应证据并高亮。后端 gate 路由把这条做成门禁。
 */

export const id = "ads";
export const apiVersion = 1;
export const usesRail = true;

export const filters = [
  { key: "risk", label: "库存处境" },
  { key: "q", label: "搜索" },
  { key: "ad_type", label: "广告类型" },
  { key: "campaign", label: "Campaign" },
  { key: "labels", label: "标签组合" },
  { key: "match", label: "匹配方式" },
  { key: "states", label: "数据状态" },
];

export function parsePath(segments) {
  if (!segments.length) return { pageId: "ads-decision", objectId: null };
  if (segments[0] === "ads-catalog") return { pageId: "ads-catalog", objectId: null };
  if (segments[0] === "ads-decision") {
    return { pageId: "ads-decision", objectId: segments[1] || null };
  }
  return { pageId: "ads-decision", objectId: segments[0] };
}

export function pathFor({ pageId, objectId }) {
  if (pageId === "ads-catalog") return "ads-catalog";
  if (objectId) return `ads-decision/${encodeURIComponent(objectId)}`;
  return "ads-decision";
}

const STAGES = ["task", "mapping", "diagnosis", "proposal"];
const STAGE_DELAY = 420;   // 四段是真依赖链，按序揭示让推理过程看得见

let host = null;
let ctxRef = null;
let view = {
  asin: null, ctx: null, run: null, running: false,
  shown: {}, decided: {}, groups: null,
};
// 侧栏交互态：展开的标签族、搜索框内容、Campaign 列表的本地过滤词。
// 放模块级而不进 URL：它们不改变筛选结果，进 URL 会污染可分享的深链。
let expanded = {};
let railQ = null;
let campQ = "";

export async function mount(slots, ctx) {
  host = slots;
  ctxRef = ctx;
  await render(ctx);
}

export function unmount() {
  host = null;
  ctxRef = null;
  expanded = {};
  railQ = null;
  campQ = "";
  view = { asin: null, ctx: null, run: null, running: false,
           shown: {}, decided: {}, groups: null };
}

export async function render(ctx) {
  ctxRef = ctx || ctxRef;
  if (!host) return;
  const c = ctxRef;
  if (c.pageId === "ads-catalog") return renderCatalog(c);
  // 候选必须先到位：侧栏与主体都要读它，
  // 放进 Promise.all 会让主体先跑、读到空 groups 然后渲染「空结果」
  if (!view.groups) {
    try {
      view.groups = (await c.api("candidates")).groups || [];
    } catch (err) {
      host.body.textContent = "";
      host.body.appendChild(c.placeholder("失败", String(err)));
      return;
    }
  }
  const want = c.objectId
    || (view.groups.flatMap((g) => g.rows)[0] || {}).child_asin || null;
  // 没带对象进来时我内部兜了个默认的，但必须回填给外壳——否则外壳的
  // objectId 还是空，任务面板会判「先在页面上选一个对象」把运行按钮锁住。
  // 回填也让地址栏变成真深链，刷新还能回到同一个对象。
  if (want && !c.objectId) {
    c.open(want, "ads-decision");
    return;                       // 这次渲染让给导航，回来时 objectId 已就位
  }
  if (want !== view.asin || !view.ctx) {
    view.asin = want;
    view.ctx = null; view.run = null; view.shown = {}; view.decided = {};
  }
  await Promise.all([renderRail(c), renderDecision(c)]);
}

/* ------------------------------------------------------------------ 侧栏 */
async function renderRail(c) {
  const { el } = c;
  const rail = host.rail;
  rail.textContent = "";
  const risk = (c.filters.risk || "").trim();
  const q = (c.filters.q || "").trim().toLowerCase();
  view.groups.forEach((g) => {
    if (risk && g.key !== risk) return;
    const rows = g.rows.filter((r) => !q
      || r.child_asin.toLowerCase().includes(q));
    if (!rows.length) return;
    const head = el("div", { class: "ads-railhead" }, [
      el("span", { class: "ads-railtitle" }, `${g.label}（${rows.length}）`),
    ]);
    if (g.note) {
      const info = el("button", { class: "ads-ib", type: "button" }, "ⓘ");
      info.addEventListener("click", (e) => {
        e.stopPropagation();
        popText(c, info, `${g.label}`, `${g.note}`);
      });
      head.appendChild(info);
    }
    rail.appendChild(head);
    rows.forEach((r) => {
      const on = r.child_asin === view.asin;
      const row = el("div", { class: "ads-pick" + (on ? " ads-on" : "") }, [
        el("div", { class: "ads-pickmain" }, [
          el("div", { class: "ads-pickname" }, r.child_asin),
          el("div", { class: "ads-picknote" },
            (r.product_goal || r.lifecycle || "").slice(0, 26)),
        ]),
        el("div", { class: "ads-picknum" },
          r.spend == null ? "—" : usd(r.spend, 0)),
      ]);
      row.addEventListener("click", () => c.open(r.child_asin, "ads-decision"));
      rail.appendChild(row);
    });
  });
  if (g_total(view.groups) === 0) {
    rail.appendChild(c.placeholder("空结果", "没有可选的子 ASIN"));
  }
}

function g_total(groups) {
  return (groups || []).reduce((n, g) => n + g.rows.length, 0);
}

/* ---------------------------------------------------------------- 页面一 */
/* 八板块。红线：只回答数字长什么样，不出诊断与建议。 */
async function renderCatalog(c) {
  const { el, fmt } = c;
  const body = host.body;
  const rail = host.rail;
  body.textContent = "";
  rail.textContent = "";
  let d;
  try {
    d = await c.api("catalog");
  } catch (err) {
    body.appendChild(c.placeholder("失败", String(err)));
    return;
  }
  view.cat = d;

  // 板块1 当前范围、对象粒度与数据状态
  const s = d.scope;
  const counts = [
    [s.campaign_total, "Campaign"], [s.ad_group_total, "广告组"],
    [s.target_total, "投放对象"], [s.source_files, "份客户报表"],
  ].map(([n, lab]) => el("div", { class: "ads-sc" }, [
    el("b", {}, fmt.num(n, 0)), el("span", {}, lab),
  ]));
  const states = [
    [`${s.campaign_live} 个 Campaign 本期有投放`, "good"],
    [`${s.campaign_structure_only} 个仅有结构无本期数据`, "warn"],
    [`有日粒度序列：广告组 ${s.with_daily_group}、`
     + `投放对象 ${s.with_daily_target}`, "calm"],
  ].map(([t, k]) => el("span", { class: "ads-chip ads-chip-" + k }, t));
  const attr = Object.entries(s.attribution || {})
    .map(([k, v]) => `${k} ${v} 天`).join(" · ");
  const byT = (o) => Object.entries(o || {})
    .map(([k, v]) => `${k} ${v}`).join(" · ");
  const countsBox = el("div", { class: "ads-counts" }, counts);
  // 「怎么只有 54 个广告组」是看这一屏必然会问的问题，把口径放进 ⓘ
  countsBox.appendChild(infoBtn(c, "范围口径",
    `${s.campaign_total} 个 Campaign 里有 ${s.campaign_no_structure} 个在报表里`
    + "既没有广告组也没有投放对象，只有 Campaign 这一层，"
    + "所以广告组数量比 Campaign 少。\n"
    + `广告组按类型：${byT(s.by_type_group)}\n`
    + `投放对象按类型：${byT(s.by_type_target)}\n`
    + `${s.ad_group_total} 个广告组里 ${s.ad_group_with_month} 个本期有花费数据、`
    + `${s.with_daily_group} 个有日粒度序列，其余在清单里标为无数据。`));
  body.appendChild(el("section", { class: "ads-card ads-scope" }, [
    el("div", { class: "ads-scopemain" }, [
      countsBox,
      el("div", { class: "ads-chips" }, states),
    ]),
    el("div", { class: "ads-attrib" }, [
      el("div", {}, "归因 " + attr),
      el("div", { class: "ads-mut" }, "粒度 " + d.grain_label),
    ]),
  ]));

  // 板块4 筛选结果数据概览
  const a = d.aggregate;
  const support = a.blocks.map((b) => el("div", { class: "ads-hs" }, [
    el("b", {}, fmt.pct(b.acos, 1)),
    el("span", {}, b.ad_types.join("/") + " ACoS"),
    el("em", {}, `${b.attribution_days} 天归因 · ROAS `
      + (b.roas == null ? "—" : b.roas.toFixed(2))),
  ]));
  support.push(el("div", { class: "ads-hs" }, [
    el("b", {}, fmt.num(a.orders, 0)), el("span", {}, "订单"),
  ]));
  support.push(el("div", { class: "ads-hs" }, [
    el("b", {}, fmt.num(a.clicks, 0)), el("span", {}, "点击"),
    el("em", {}, "CTR " + fmt.pct(a.ctr, 2)),
  ]));
  const blocks = a.blocks.map((b) => el("div", { class: "ads-blk" }, [
    el("div", { class: "ads-blkhead" }, [
      el("b", {}, `${b.attribution_days} 天归因 · ${b.ad_types.join(" / ")}`),
      el("span", { class: "ads-mut" }, `${b.objects} 个对象`),
    ]),
    el("div", { class: "ads-statrow" },
      [["花费", usd(b.spend, 0)],
       ["广告销售额", usd(b.ad_sales, 0)],
       ["订单", fmt.num(b.orders, 0)], ["点击", fmt.num(b.clicks, 0)],
       ["CTR", fmt.pct(b.ctr, 2)], ["CPC", usd(b.cpc, 2)],
       ["CVR", fmt.pct(b.cvr, 1)]]
        .map(([k, v]) => el("div", {}, [el("span", {}, k), el("b", {}, v)]))),
  ]));
  const heroLab = el("div", { class: "ads-mut" }, [
    el("span", {}, "当前筛选结果"),
  ]);
  heroLab.appendChild(infoBtn(c, "口径",
    "花费取月度权威口径，与客户报表逐字段对得上。\n"
    + "花费是真实支出，跨归因周期可以相加。\n"
    + "广告销售额不能相加：SP 是 7 天归因、SB / SD 是 14 天归因，"
    + "加在一起做分母会算出一个不存在的合计 ACoS，"
    + "所以 ACoS 和 ROAS 按归因周期分开给。"
    + (d.grain_note ? "\n\n" + d.grain_note.why
      + "\n" + d.grain_note.other_grain_label + "粒度合计 "
      + usd(d.grain_note.other_spend, 0) : "")));
  body.appendChild(el("section", { class: "ads-card" }, [
    el("div", { class: "ads-herotop" }, [
      el("div", { class: "ads-herolead" }, [
        heroLab,
        el("div", { class: "ads-big" }, usd(a.spend, 0)),
        el("div", { class: "ads-mut" }, a.objects + " 个对象"),
      ]),
      el("div", { class: "ads-herosupport" }, support),
    ]),
    el("div", { class: "ads-blocks" }, blocks),
    benchmarkBox(c, d.benchmark),
  ]));

  // 板块5 数值异常对象
  body.appendChild(anomalyCard(c, d));

  // 板块6 横向对比（勾选两行以上才出现）
  const cmp = el("section", { class: "ads-card", "data-cmp": "1" });
  cmp.hidden = true;
  body.appendChild(cmp);

  // 板块7 广告对象数据清单
  body.appendChild(listCard(c, d, cmp));

  // 侧栏：板块2 标签体系 + 板块3 组合筛选
  railFilters(c, d);
}

function benchmarkBox(c, rows) {
  const { el, fmt } = c;
  if (!rows || !rows.length) return el("div", {});
  const top = rows[0];
  const box = el("details", { class: "ads-cov" }, [
    el("summary", {}, `类目基准对照　CTR ${fmt.pct(top.own_ctr, 2)} · `
      + `同类中位 ${fmt.pct(top.peer_ctr_median, 2)}　`
      + `ACoS ${fmt.pct(top.own_acos, 1)} · `
      + `同类中位 ${fmt.pct(top.peer_acos_median, 1)}`),
  ]);
  const t = el("div", { class: "ads-bmk" });
  t.appendChild(el("div", { class: "ads-bmkrow ads-kwhead" },
    ["类目层级", "CTR 我方 / 同类中位", "ACoS 我方 / 同类中位",
     "ROAS 我方 / 同类中位"].map((x) => el("div", {}, x))));
  rows.forEach((r) => t.appendChild(el("div", { class: "ads-bmkrow" }, [
    el("div", {}, r.category || ""),
    el("div", { class: "ads-kwnum" },
      fmt.pct(r.own_ctr, 2) + " / " + fmt.pct(r.peer_ctr_median, 2)),
    el("div", { class: "ads-kwnum" },
      fmt.pct(r.own_acos, 1) + " / " + fmt.pct(r.peer_acos_median, 1)),
    el("div", { class: "ads-kwnum" },
      (r.own_roas == null ? "—" : r.own_roas.toFixed(2)) + " / "
      + (r.peer_roas_median == null ? "—" : r.peer_roas_median.toFixed(2))),
  ])));
  box.appendChild(t);
  return box;
}

function anomalyCard(c, d) {
  const { el, fmt } = c;
  const an = d.anomalies;
  const byClass = {};
  d.rules.forEach((r) => {
    byClass[r.class_label] = (byClass[r.class_label] || 0) + 1;
  });
  const toggles = Object.entries(byClass).map(([k, n]) =>
    el("span", { class: "ads-chip ads-chip-calm" }, `${k} ${n}`));
  const box = el("div", { class: "ads-rules" });
  const max = Math.max(1, ...Object.values(an.by_rule));
  Object.entries(an.by_rule).sort((x, y) => y[1] - x[1]).forEach(([k, n]) => {
    const bar = el("div", { class: "ads-hb" },
      [el("i", { style: `width:${Math.max(3, (n / max) * 100)}%` })]);
    box.appendChild(el("div", { class: "ads-rr" }, [
      el("div", { class: "ads-rn" }, k),
      el("div", { class: "ads-rc" }, String(n)),
      bar, el("div", {}),
    ]));
  });
  const sec = el("section", { class: "ads-card" }, [
    el("div", { class: "ads-secthead" }, [
      el("h2", { class: "ads-h2" }, "数值异常对象"),
      ...toggles,
    ]),
    el("div", { class: "ads-big ads-lead" }, `${an.objects_hit} / ${d.returned}`),
    el("div", { class: "ads-mut" }, `${an.total} 条异常`
      + (an.campaign_total
        ? ` · Campaign 级 ${an.campaign_total} 条，落在 `
          + `${an.campaigns_hit} / ${an.campaigns_in_scope} 个 Campaign` : "")),
    box,
  ]);
  if (an.campaign_rows.length) {
    const ct = el("div", { class: "ads-camprows" }, [
      el("div", { class: "ads-subhead" }, [
        el("span", {}, "Campaign 级异常"),
      ]),
    ]);
    ct.querySelector(".ads-subhead").appendChild(infoBtn(c,
      "Campaign 级异常",
      "预算和无效流量的客户报表只到 Campaign 粒度。\n"
      + "这两类规则按 Campaign 计一次，不摊到它下面的每个对象上——"
      + "否则会被投放对象数量放大成几百条。"));
    const cmax = Math.max(...an.campaign_rows.map((x) => x.observed || 0), 1);
    an.campaign_rows.forEach((x) => {
      const bar = el("div", { class: "ads-hb" }, [el("i", {
        style: `width:${Math.max(3, ((x.observed || 0) / cmax) * 100)}%;`
          + "background:var(--warn)" })]);
      const val = el("div", { class: "ads-rc" }, fmt.pct(x.observed, 1));
      val.addEventListener("click", (e) => {
        e.stopPropagation();
        popText(c, val, `${x.campaign}\n${x.rule_name}`
          + `\n依据：${x.basis}`);
      });
      ct.appendChild(el("div", { class: "ads-cr" }, [
        el("div", { class: "ads-cn" }, (x.campaign || "").replace(/^002-/, "")),
        el("div", { class: "ads-crule" }, x.rule_name),
        bar, val, el("div", {}),
      ]));
    });
    sec.appendChild(ct);
  }
  return sec;
}

const L_COLS = [
  ["sel", "", 30], ["name", "对象", 210], ["labels", "标签", 172],
  ["impressions", "展示", 78], ["clicks", "点击", 62],
  ["spend", "花费", 90], ["orders", "订单", 58],
  ["ad_sales", "广告销售额", 98], ["ctr", "CTR", 54],
  ["cpc", "CPC", 60], ["cvr", "CVR", 54], ["acos", "ACoS", 58],
  ["roas", "ROAS", 54], ["chg", "环比 ACoS", 82],
  ["state", "数据状态", 132],
];

function listCard(c, d, cmpBox) {
  const { el, fmt } = c;
  const picked = new Set();
  const table = el("div", { class: "ads-ltable" });
  table.appendChild(el("div", { class: "ads-lrow ads-lhead" },
    L_COLS.map(([k, lab, w]) => el("div",
      { class: "ads-ld" + (["impressions", "clicks", "spend", "orders",
                            "ad_sales", "ctr", "cpc", "cvr", "acos", "roas",
                            "chg"].includes(k) ? " ads-tnum" : ""),
        style: `width:${w}px;flex:0 0 ${w}px` }, lab))));
  d.rows.forEach((r) => {
    const cb = el("input", { type: "checkbox", class: "ads-selbox" });
    cb.addEventListener("click", (e) => {
      e.stopPropagation();
      if (cb.checked) picked.add(r.ad_object_id);
      else picked.delete(r.ad_object_id);
      refreshCompare(c, cmpBox, [...picked]);
    });
    const cells = L_COLS.map(([k, , w]) => {
      const cls = ["impressions", "clicks", "spend", "orders", "ad_sales",
                   "ctr", "cpc", "cvr", "acos", "roas", "chg"].includes(k)
        ? "ads-ld ads-tnum" : "ads-ld";
      const box = el("div", { class: cls,
                              style: `width:${w}px;flex:0 0 ${w}px` });
      if (k === "sel") box.appendChild(cb);
      else if (k === "name") {
        box.appendChild(el("b", {}, r.name || ""));
        box.appendChild(el("em", {}, (r.campaign || "").replace(/^002-/, "")));
      } else if (k === "labels") {
        box.appendChild(el("span", { class: "ads-tag" }, r.purpose || "—"));
      } else if (k === "state") {
        (r.state_labels || []).slice(0, 1).forEach((t) =>
          box.appendChild(el("span", { class: "ads-tag" }, t)));
        if ((r.state_labels || []).length > 1) {
          const more = el("span", { class: "ads-ref" },
            "+" + (r.state_labels.length - 1));
          more.addEventListener("click", (e) => {
            e.stopPropagation();
            popText(c, more, "数据状态\n"
              + r.state_labels.join("\n"));
          });
          box.appendChild(more);
        }
      } else if (k === "chg") {
        box.textContent = r.acos_change_rate == null ? "无可比前窗"
          : (r.acos_change_rate > 0 ? "+" : "")
            + (r.acos_change_rate * 100).toFixed(1) + "%";
      } else if (["spend", "ad_sales"].includes(k)) {
        box.textContent = usd(r[k], 0);
      } else if (["ctr", "cvr", "acos"].includes(k)) {
        box.textContent = fmt.pct(r[k], k === "ctr" ? 2 : 1);
      } else if (k === "cpc") {
        box.textContent = usd(r[k], 2);
      } else if (k === "roas") {
        box.textContent = r[k] == null ? "—" : r[k].toFixed(2);
      } else {
        box.textContent = fmt.num(r[k], 0);
      }
      return box;
    });
    const row = el("div", { class: "ads-lrow" }, cells);
    row.addEventListener("click", () => openDetail(c, r.ad_object_id));
    table.appendChild(row);
  });
  return el("section", { class: "ads-card" }, [
    el("div", { class: "ads-secthead" }, [
      el("h2", { class: "ads-h2" }, "广告对象数据清单"),
      el("span", { class: "ads-mut" },
        `${d.returned} / ${d.total} 个${d.grain_label}`),
    ]),
    el("div", { class: "ads-ltablewrap" }, [table]),
  ]);
}

async function refreshCompare(c, box, ids) {
  if (ids.length < 2) { box.hidden = true; box.textContent = ""; return; }
  const { el, fmt } = c;
  const d = await c.api("compare", { ids: ids.join(",") });
  box.textContent = "";
  box.hidden = false;
  box.appendChild(el("div", { class: "ads-secthead" }, [
    el("h2", { class: "ads-h2" }, "横向对比"),
    el("span", { class: "ads-mut" }, (d.blockers || []).join("；")),
  ]));
  (d.groups || []).forEach((g) => {
    box.appendChild(el("div", { class: "ads-subhead" },
      `${g.attribution_days} 天归因 · ${g.n} 个对象`
      + (g.median_acos == null ? ""
        : `　组内中位 ACoS ${fmt.pct(g.median_acos, 1)}`)));
    const t = el("div", { class: "ads-bmk" });
    t.appendChild(el("div", { class: "ads-cmprow ads-kwhead" },
      ["对象", "花费", "广告销售额", "ACoS", "ROAS", "环比 ACoS"]
        .map((x) => el("div", {}, x))));
    g.rows.forEach((r) => t.appendChild(el("div", { class: "ads-cmprow" }, [
      el("div", {}, r.name || ""),
      el("div", { class: "ads-kwnum" }, usd(r.spend, 0)),
      el("div", { class: "ads-kwnum" }, usd(r.ad_sales, 0)),
      el("div", { class: "ads-kwnum" }, fmt.pct(r.acos, 1)),
      el("div", { class: "ads-kwnum" },
        r.roas == null ? "—" : r.roas.toFixed(2)),
      el("div", { class: "ads-kwnum" },
        r.acos_change_rate == null ? "—"
          : (r.acos_change_rate > 0 ? "+" : "")
            + (r.acos_change_rate * 100).toFixed(1) + "%"),
    ])));
    box.appendChild(t);
  });
}

async function openDetail(c, oid) {
  const { el, fmt } = c;
  const d = await c.api("object/" + encodeURIComponent(oid));
  // 外壳的抽屉挂在 body 下，不在 [data-module="ads"] 里，
  // 模块 CSS 一条都不会生效。自己给渲染进去的容器补上作用域标记——
  // 这是我的内容，不算改外壳。
  const body = el("div", { "data-module": "ads", class: "ads-drawer" });
  if (d.condition !== "正常") {
    body.appendChild(el("div", { class: "ads-hint" }, d.message || ""));
    c.drawer.open(oid, body);
    return;
  }
  const kv = (title, pairs) => {
    const items = [];
    pairs.forEach(([k, v]) => {
      if (v === null || v === undefined || v === "") return;
      items.push(el("dt", {}, k), el("dd", {}, String(v)));
    });
    if (!items.length) return;
    body.appendChild(el("div", { class: "ads-evrow" }, [
      el("div", { class: "ads-evhead" }, [el("b", {}, title)]),
      el("dl", { class: "ads-kv" }, items),
    ]));
  };
  kv("本期数字", [
    ["展示", fmt.num(d.metrics.impressions, 0)],
    ["点击", fmt.num(d.metrics.clicks, 0)],
    ["花费", usd(d.metrics.spend, 0)],
    ["订单", fmt.num(d.metrics.orders, 0)],
    ["广告销售额", usd(d.metrics.ad_sales, 0)],
    ["CTR", fmt.pct(d.ratios.ctr, 2)], ["CPC", usd(d.ratios.cpc, 2)],
    ["CVR", fmt.pct(d.ratios.cvr, 1)], ["ACoS", fmt.pct(d.ratios.acos, 1)],
    ["ROAS", d.ratios.roas == null ? null : d.ratios.roas.toFixed(2)],
    ["归因窗口", d.attribution_days ? d.attribution_days + " 天" : null],
    ["数据性质", d.nature],
  ]);
  const h = d.history || {};
  if (h.comparable) {
    kv("相对自身历史", [
      ["ACoS 环比", h.acos_change_rate == null ? null
        : (h.acos_change_rate * 100).toFixed(1) + "%"],
      ["转化率环比", h.cvr_change_rate == null ? null
        : (h.cvr_change_rate * 100).toFixed(1) + "%"],
      ["CPC 环比", h.cpc_change_rate == null ? null
        : (h.cpc_change_rate * 100).toFixed(1) + "%"],
      ["前后半月天数", `${h.days_prev} / ${h.days_curr}`],
    ]);
  } else {
    kv("相对自身历史", [["不可比原因", h.why]]);
  }
  if (d.budget) kv("预算与预算错失（Campaign 级）", [
    ["预算", usd(d.budget.budget, 0)],
    ["预算范围内时间", fmt.pct(d.budget.time_in_budget, 1)],
    ["预计错失展示", `${fmt.num(d.budget.lost_impressions_min, 0)}—`
      + fmt.num(d.budget.lost_impressions_max, 0)],
    ["预计错失销售额", `${usd(d.budget.lost_sales_min, 0)}—`
      + usd(d.budget.lost_sales_max, 0)],
  ]);
  if (d.invalid) kv("无效流量（Campaign 级）", [
    ["总点击", fmt.num(d.invalid.total_clicks, 0)],
    ["无效点击", fmt.num(d.invalid.invalid_clicks, 0)],
    ["无效点击率", fmt.pct(d.invalid.invalid_click_rate, 1)],
  ]);
  if (d.yoy) kv("去年同期（Campaign 级）", [
    ["去年展示", fmt.num(d.yoy.last_year_impressions, 0)],
    ["去年点击", fmt.num(d.yoy.last_year_clicks, 0)],
    ["去年花费", usd(d.yoy.last_year_spend, 0)],
  ]);
  if ((d.placements || []).length) {
    const t = el("div", { class: "ads-bmk" });
    t.appendChild(el("div", { class: "ads-cmprow ads-kwhead" },
      ["广告位", "展示", "点击", "花费", "ACoS", "ROAS"]
        .map((x) => el("div", {}, x))));
    d.placements.forEach((p) => t.appendChild(
      el("div", { class: "ads-cmprow" }, [
        el("div", {}, p.placement || ""),
        el("div", { class: "ads-kwnum" }, fmt.num(p.impressions, 0)),
        el("div", { class: "ads-kwnum" }, fmt.num(p.clicks, 0)),
        el("div", { class: "ads-kwnum" }, usd(p.spend, 0)),
        el("div", { class: "ads-kwnum" }, fmt.pct(p.acos, 1)),
        el("div", { class: "ads-kwnum" },
          p.roas == null ? "—" : p.roas.toFixed(2)),
      ])));
    const w = el("div", { class: "ads-evrow" }, [
      el("div", { class: "ads-evhead" }, [el("b", {}, "广告位（Campaign 级）")]),
      t,
    ]);
    w.querySelector(".ads-evhead").appendChild(infoBtn(c, "广告位",
      "广告位报表只到 Campaign 粒度，这些数字属于该对象所在的 Campaign，"
      + "不是这一个广告组或投放对象自己的。"));
    body.appendChild(w);
  }
  // 标签与生效历史
  const lg = el("div", { class: "ads-bmk" });
  lg.appendChild(el("div", { class: "ads-lblrow ads-kwhead" },
    ["类别", "取值", "来源", "确认状态", "生效"].map((x) => el("div", {}, x))));
  (d.labels || []).forEach((x) => lg.appendChild(
    el("div", { class: "ads-lblrow" }, [
      el("div", {}, x.family_label), el("div", {}, x.label_value),
      el("div", {}, x.source_label), el("div", {}, x.confirm_label),
      el("div", { class: "ads-mono" },
        (x.effective_from || "") + (x.effective_to
          ? " — " + x.effective_to : " 起")),
    ])));
  const lw = el("div", { class: "ads-evrow" }, [
    el("div", { class: "ads-evhead" }, [el("b", {}, "标签与生效历史")]),
    lg,
  ]);
  lw.querySelector(".ads-evhead").appendChild(infoBtn(c,
    "标签来源与确认状态",
    "报表属性是客户报表里的原字段，直接确认。\n"
    + "命名映射从 Campaign 命名规范解出，AI 建议和组继承是推断。\n"
    + "推断出来的一律停在待确认，要运营点过才转确认。"));
  body.appendChild(lw);
  kv("数据状态", (d.state_labels || []).map((t, i) => ["状态 " + (i + 1), t]));
  c.drawer.open(d.name || oid, body);
}

/* 板块2 标签体系 + 板块3 标签组合与对象筛选，都放侧栏。

   方案 3.5 的语义是「跨标签族 AND、族内 OR」：
   「某个子 ASIN 下的全部 SP 广告组」是产品关系 AND 广告属性，
   「投放某个关键词或某类关键词的全部 Target」是投放对象族内 OR。
   每族的候选数都在「其他族已生效、本族自己的选择先摘掉」的集合上算，
   所以勾了一项不会把同族其他项打成 0；候选数为 0 的取值置灰但仍列出，
   让人看见这个组合选不出东西，而不是选项凭空消失。 */
function railFilters(c, d) {
  const { el } = c;
  const rail = host.rail;
  const grain = d.grain;

  const lock = el("div", { class: "ads-grainlock" });
  [["AD_GROUP", "广告组"], ["TARGET", "投放对象"]].forEach(([k, lab]) => {
    const b = el("button",
      { class: "ads-gl" + (k === grain ? " ads-on" : ""), type: "button" },
      lab);
    b.addEventListener("click", () => {
      // 换粒度时清掉标签与匹配方式：两个粒度的分类轴不是同一套，
      // 带着旧条件过去大概率一个对象都选不出来
      c.setFilters({ "ads.grain": k, labels: "", match: "", campaign: "" });
    });
    lock.appendChild(b);
  });
  rail.appendChild(lock);
  rail.appendChild(el("div", { class: "ads-mut ads-grainhint" },
    `${d.returned} / ${d.total} 个${d.grain_label}`));

  // 搜索：按名字找对象，也搜 Campaign 名和广告目的
  const inp = el("input", {
    class: "ads-sinput", type: "search", autocomplete: "off",
    placeholder: `搜${d.grain_label}名 / Campaign`,
    "aria-label": `搜索${d.grain_label}`,
  });
  inp.value = c.filters.q || "";
  let timer = null;
  inp.addEventListener("input", () => {
    railQ = inp.value;
    clearTimeout(timer);
    // 防抖：每敲一个字都请求会把焦点冲掉，也白打一堆请求
    timer = setTimeout(() => c.setFilters({ q: inp.value.trim() }), 380);
  });
  rail.appendChild(el("div", { class: "ads-search" }, [inp]));
  if (railQ !== null) {
    // 重渲染后把焦点和光标位置还回去，否则打第二个字要重新点一次
    requestAnimationFrame(() => {
      if (!inp.isConnected) return;
      inp.focus();
      inp.setSelectionRange(inp.value.length, inp.value.length);
    });
  }

  // 已选条件：每条可单独摘掉
  const act = d.active || [];
  if (act.length) {
    const bar = el("div", { class: "ads-actbar" });
    act.forEach((a) => {
      const chip = el("button", { class: "ads-actchip", type: "button",
                                  "aria-label": `取消 ${a.value}` },
        `${a.family}：${a.value} ×`);
      chip.addEventListener("click", () => dropFilter(c, a));
      bar.appendChild(chip);
    });
    const clr = el("button", { class: "ads-clr", type: "button" }, "清空");
    clr.addEventListener("click", () => {
      railQ = "";
      c.setFilters({ labels: "", match: "", campaign: "", q: "",
                     ad_type: "", states: "" });
    });
    bar.appendChild(clr);
    rail.appendChild(bar);
  }

  (d.facets || []).forEach((f) => {
    const open = expanded[f.type] === true;
    const shown = open ? f.values : f.values.slice(0, 8);
    rail.appendChild(el("div", { class: "ads-railhead" }, [
      el("span", { class: "ads-railtitle" },
        `${f.label}（${f.values.length}）`),
    ]));
    if (f.key === "campaign" && f.values.length > 12) {
      const cf = el("input", { class: "ads-sinput ads-cfilter",
                               type: "search", placeholder: "过滤 Campaign",
                               "aria-label": "过滤 Campaign" });
      cf.value = campQ;
      cf.addEventListener("input", () => {
        campQ = cf.value;
        rail.querySelectorAll("[data-camp]").forEach((n) => {
          const hit = n.getAttribute("data-camp").toLowerCase()
            .includes(campQ.toLowerCase());
          n.classList.toggle("ads-off", !hit);
        });
      });
      rail.appendChild(cf);
    }
    shown.forEach((v) => {
      const zero = !v.n && !v.on;
      const b = el("button", {
        class: "ads-fopt" + (v.on ? " ads-on" : "")
          + (zero ? " ads-zero" : ""),
        type: "button", "aria-pressed": v.on ? "true" : "false",
      }, [
        el("span", { class: "ads-fbox" }, v.on ? "✓" : ""),
        el("span", { class: "ads-fname" }, v.value),
        el("span", { class: "ads-fn" }, String(v.n)),
      ]);
      if (f.key === "campaign") b.setAttribute("data-camp", v.value);
      if (zero) {
        b.disabled = true;
        b.title = "当前其它条件下选不出对象";
      } else {
        b.addEventListener("click", () => toggleFacet(c, f, v));
      }
      rail.appendChild(b);
    });
    if (f.values.length > 8) {
      const more = el("button", { class: "ads-more", type: "button" },
        open ? "收起" : `还有 ${f.values.length - 8} 个`);
      more.addEventListener("click", () => {
        expanded[f.type] = !open;
        render(c);             // 只是展开，不改筛选条件
      });
      rail.appendChild(more);
    }
  });
}

function toggleFacet(c, f, v) {
  if (f.key === "campaign") {
    c.setFilters({ campaign: v.on ? "" : v.value });
    return;
  }
  if (f.key === "match") {
    const cur = (c.filters.match || "").split("\x01").filter(Boolean);
    const next = cur.includes(v.value)
      ? cur.filter((x) => x !== v.value) : cur.concat([v.value]);
    c.setFilters({ match: next.join("\x01") });
    return;
  }
  const token = `${f.type}:${v.value}`;
  const cur = (c.filters.labels || "").split("\x01").filter(Boolean);
  const next = cur.includes(token)
    ? cur.filter((x) => x !== token) : cur.concat([token]);
  c.setFilters({ labels: next.join("\x01") });
}

function dropFilter(c, a) {
  if (a.key === "labels") {
    const cur = (c.filters.labels || "").split("\x01").filter(Boolean);
    c.setFilters({ labels: cur.filter((x) => x !== a.token).join("\x01") });
  } else if (a.key === "match") {
    const cur = (c.filters.match || "").split("\x01").filter(Boolean);
    c.setFilters({ match: cur.filter((x) => x !== a.token).join("\x01") });
  } else if (a.key === "q") {
    railQ = "";
    c.setFilters({ q: "" });
  } else {
    c.setFilters({ [a.key]: "" });
  }
}

/* ------------------------------------------------------------------ 页面二 */
async function renderDecision(c) {
  const { el } = c;
  const body = host.body;
  body.textContent = "";

  if (!view.asin) {
    body.appendChild(c.placeholder("空结果", "没有可判断的子 ASIN"));
    return;
  }
  if (!view.ctx) {
    try {
      view.ctx = await c.api("context", { child_asin: view.asin });
    } catch (err) {
      body.appendChild(c.placeholder("失败", String(err)));
      return;
    }
  }
  const d = view.ctx;
  if (!d.context) {
    body.appendChild(sectionCtxThin(c, d));
    return;
  }
  // Agent 不由浏览器触发（外壳拿不到请求体），Runner 是本地脚本，
  // 所以读 sidecar 是纯读操作，进页面就该读——B0b 属于板块2，
  // 等点按钮才读的话板块2 永远只能显示预烤约束。
  if (view.run === null) {
    try {
      view.run = await c.api("run", { child_asin: view.asin });
    } catch (err) {
      view.run = { condition: "失败", message: String(err), points: {},
                   stages: [] };
    }
  }
  body.appendChild(sectionContext(c, d));
  body.appendChild(sectionEvidence(c, d));
  STAGES.forEach((s) => body.appendChild(sectionStage(c, s)));
  body.appendChild(sectionStructure(c, d));
}

/* 板块1 子 ASIN 决策上下文 */
function sectionContext(c, d) {
  const { el } = c;
  const x = d.context;
  const r = d.readiness;
  const chips = [];
  const chip = (t, k) => chips.push(el("span",
    { class: "ads-chip ads-chip-" + (k || "calm") }, t));
  chip(r.mode, r.mode === "正式判断" ? "good"
    : r.mode === "条件性判断" ? "warn" : "alert");
  chip("产品目标 " + x.goal_confirmed_label,
    x.goal_confirmed_label === "已确认" ? "good" : "warn");
  if (x.goal_type_label) chip(x.goal_type_label, "calm");
  chip("证据 " + d.evidence.length + " 条", "calm");
  chip("广告对象 " + d.existing_structure.length + " 个", "calm");
  chip("观察窗口 " + (x.observe_window_start || "—")
    + " — " + (x.observe_window_end || "—"), "calm");
  if (r.stale_evidence.length)
    chip(r.stale_evidence.length + " 条证据已过期", "warn");

  // Agent 在本地脚本里跑，浏览器点按钮不会真触发。所以这个按钮的语义是
  // 「把已落库的结果显示出来」，不是「现场跑一次」——叫「开始分析」会让人
  // 以为点下去正在跑。分工文档 §4。
  const ran = view.run && view.run.run_id;
  const btn = el("button",
    { class: "ads-run" + (ran ? "" : " ads-run-off"), type: "button" },
    view.running ? "展开中…" : ran ? "查看分析结果" : "尚未运行");
  if (ran && !view.running) {
    btn.addEventListener("click", () => runAgent(c));
  } else {
    btn.disabled = true;
    btn.title = ran ? "" : "需在本地执行广告 Agent Runner";
  }
  if (ran) {
    chip("本次分析 " + String(view.run.completed_at || "").slice(0, 16)
      .replace("T", " "), "calm");
    if (view.run.model_version) chip(view.run.model_version, "calm");
    if (view.run.seam_bypass) chip("接缝联调旁路 · 非有效结论", "alert");
    if ((view.run.pending_points || []).length) {
      chip("还缺 " + view.run.pending_points.length + " 个输出点", "warn");
    }
  } else if (view.run && view.run.message) {
    chip(view.run.message, "warn");
  }
  const vers = el("div", { class: "ads-vers" },
    [el("span", { class: "ads-mut" }, "决策版本 ")]);
  d.versions.forEach((v, i) => {
    if (i) vers.appendChild(el("span", { class: "ads-mut" }, " · "));
    if (v.is_current) {
      vers.appendChild(el("b", { class: "ads-mono" }, v.decision_at));
    } else {
      const a = el("button", { class: "ads-ref", type: "button" },
        v.decision_at);
      a.addEventListener("click", async () => {
        view.ctx = await c.api("context",
          { child_asin: view.asin, decision_id: v.decision_id });
        view.run = null; view.shown = {}; view.decided = {};
        render(c);
      });
      vers.appendChild(a);
    }
  });

  return el("section", { class: "ads-card ads-ctxbar" }, [
    el("div", { class: "ads-ctxmain" }, [
      el("div", { class: "ads-ctxhead" }, [
        el("b", { class: "ads-asin" }, x.child_asin),
        el("span", { class: "ads-mut ads-mono" },
          "父体 " + (x.parent_asin || "—")),
        el("div", { class: "ads-goal" }, x.product_goal || "—"),
      ]),
      el("div", { class: "ads-chips" }, chips),
    ]),
    el("div", { class: "ads-ctxrun" }, [
      vers, btn,
      el("div", { class: "ads-mut ads-note" },
        (r.notes || []).join("；") || (r.blockers || []).join("；")),
    ]),
  ]);
}

function sectionCtxThin(c, d) {
  const { el } = c;
  const r = d.readiness || {};
  return el("section", { class: "ads-card" }, [
    el("div", { class: "ads-ctxhead" }, [
      el("b", { class: "ads-asin" }, d.child_asin || "—"),
      el("div", { class: "ads-goal" }, "尚无决策版本"),
    ]),
    el("div", { class: "ads-chips" },
      [el("span", { class: "ads-chip ads-chip-alert" },
        r.mode || "暂时无法判断")].concat(
        (r.notes || []).map((t) =>
          el("span", { class: "ads-chip ads-chip-warn" }, t)))),
  ]);
}

/* 板块2/3 判断依据 = Agent 的输入 */
function sectionEvidence(c, d) {
  const { el } = c;
  const by = { goal: [], market: [], ads: [], history: [], other: [] };
  d.evidence.forEach((e) => (by[e.board] || by.other).push(e));

  // 约束分档（B0b）是 Agent 的判断。它到位就用它，不用预烤表。
  // 分工文档 §6：页面绝不回落到回放，所以两者只能显示一个，且要标出来源。
  const agentCons = (view.run && view.run.points
    && view.run.points.B0b) || null;
  const cons = agentCons || d.constraints || [];
  const fromAgent = !!agentCons;

  const goalCol = el("div", { class: "ads-evcol" }, [
    colHead(c, "产品目标与经营约束",
      `${by.goal.length} 条证据 · `
      + `${cons.filter((x) => x.kind === "hard").length} 硬性 / `
      + `${cons.filter((x) => x.kind !== "hard").length} 观察`
      + (fromAgent ? (view.run.seam_bypass
        ? "　本次分析判定（联调旁路，非有效结论）" : "　本次分析判定") : "")),
  ]);
  const hard = cons.filter((x) => x.kind === "hard");
  const obs = cons.filter((x) => x.kind !== "hard");
  if (hard.length) {
    goalCol.appendChild(subhead(c, "硬性条件 · 不解决不能扩量"));
    hard.forEach((x) => goalCol.appendChild(constraintRow(c, x)));
  }
  if (obs.length) {
    goalCol.appendChild(subhead(c, "需要持续观察"));
    obs.forEach((x) => goalCol.appendChild(constraintRow(c, x)));
  }
  by.goal.forEach((e) => goalCol.appendChild(evidenceRow(c, e)));

  // B0cd 词与竞品判断挂进板块3。Agent 判的是外部市场，和证据卡同栏。
  const agentB0cd = (view.run && view.run.points
    && view.run.points.B0cd) || null;

  const adsCol = el("div", { class: "ads-evcol" }, [
    colHead(c, "广告表现与历史复盘", by.ads.length + " 条"),
  ]);
  by.ads.concat(by.history, by.other)
    .forEach((e) => adsCol.appendChild(evidenceRow(c, e)));
  (d.history.reviews || []).forEach((r) =>
    adsCol.appendChild(reviewRow(c, r)));

  const mktCol = el("div", { class: "ads-evcol ads-evwide" }, [
    colHead(c, "关键词与竞品证据",
      `${d.keywords.length} 词 · ${d.competitor.length} 类压力`),
  ]);
  if (d.keywords.length) {
    mktCol.appendChild(subhead(c, "核心关键词位置与匹配度"));
    mktCol.appendChild(keywordTable(c, d.keywords));
  }
  // B0cd 是 Agent 的判断（词匹配度 + 竞品压力分类），到位就用它，
  // 不用预烤的 ext_keyword_match / ext_competitor_pressure。
  if (agentB0cd) {
    mktCol.appendChild(subhead(c, "词与竞品判断 · 本次分析判定"));
    agentB0cd.forEach((x) => mktCol.appendChild(b0cdRow(c, x)));
  } else if (d.competitor.length) {
    mktCol.appendChild(subhead(c, "竞品压力"));
    d.competitor.forEach((p) => mktCol.appendChild(pressureRow(c, p)));
  }
  by.market.forEach((e) => mktCol.appendChild(evidenceRow(c, e)));

  return el("section", { class: "ads-card" }, [
    el("div", { class: "ads-secthead" }, [
      el("h2", { class: "ads-h2" }, "判断依据"),
      infoBtn(c, "判断依据",
        "这一屏是 Agent 的输入，不是它的产出。\n"
        + "每条带来源、观察时间、性质和使用注意。\n"
        + "下面每条结论后面的依据 chip 都指回这里，点一下会跳到对应那条。"),
    ]),
    el("div", { class: "ads-evgrid" }, [goalCol, adsCol, mktCol]),
  ]);
}

function colHead(c, title, note) {
  return c.el("h3", { class: "ads-h3" }, [
    c.el("span", {}, title),
    c.el("span", { class: "ads-mut" }, " " + (note || "")),
  ]);
}

function subhead(c, t) {
  return c.el("div", { class: "ads-subhead" }, t);
}

/* 外壳的 fmt.money 用 toFixed，不带千分位，六位数会渲染成 $313663。
   fmt.int 是带的（toLocaleString），只有 money 漏了。
   这该在外壳修，但模块不许碰 shell.js，所以模块内自己包一层。 */
function usd(v, d = 0) {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const n = Number(v);
  return "$" + n.toLocaleString("zh-CN", { minimumFractionDigits: d,
                                           maximumFractionDigits: d });
}

/* 外壳的 pop.show 用 textContent 落地，传 HTML 会被整段转义摆到屏上，
   所以 ⓘ 内容一律纯文本、用 \n 分行。但 #wb-pop 是 white-space: normal，
   \n 会被当空格吃掉——浮层和抽屉一样在模块作用域外，同样靠内容侧的
   标记把作用域带过去（见 ads.css 的 .ads-popbody）。 */
function popText(c, anchor, title, body) {
  // body 可省：调用点已经把多行拼成一整段时，整段就是 title。
  // 不无条件拼 title + body——缺参会把 undefined 摆到客户面前。
  c.pop.show(anchor, body === undefined ? String(title)
    : String(title) + "\n" + String(body));
  const p = document.querySelector("#wb-pop");
  if (p) {
    p.setAttribute("data-module", "ads");
    p.classList.add("ads-popbody");
  }
}

function infoBtn(c, title, html) {
  const b = c.el("button", { class: "ads-ib", type: "button",
                             "aria-label": title + " 说明" }, "ⓘ");
  b.addEventListener("click", (e) => {
    e.stopPropagation();
    popText(c, b, title, html);
  });
  return b;
}

function evrefChip(c, eid) {
  const e = ((view.ctx || {}).evidence || [])
    .find((x) => x.evidence_id === eid);
  const label = e ? (e.evidence_title || eid) : eid;
  const b = c.el("button", { class: "ads-ref", type: "button",
                             "data-ev": eid, title: "跳到「" + label + "」" },
    label.length > 12 ? label.slice(0, 12) : label);
  b.addEventListener("click", (ev) => {
    ev.stopPropagation();
    flashEvidence(eid);
  });
  return b;
}

function evrefs(c, ids) {
  if (!ids || !ids.length) return null;
  const w = c.el("div", { class: "ads-refs" },
    [c.el("span", { class: "ads-mut" }, "依据 ")]);
  ids.forEach((i) => w.appendChild(evrefChip(c, i)));
  return w;
}

function flashEvidence(eid) {
  const row = host && host.body
    ? host.body.querySelector(`[data-evid="${eid}"]`) : null;
  if (!row) return;
  host.body.querySelectorAll(".ads-flash")
    .forEach((r) => r.classList.remove("ads-flash"));
  row.classList.add("ads-flash");
  row.scrollIntoView({ block: "center", behavior: "smooth" });
  setTimeout(() => row.classList.remove("ads-flash"), 2400);
}

function evidenceRow(c, e) {
  const { el } = c;
  const w = el("div", { class: "ads-evrow", "data-evid": e.evidence_id }, [
    el("div", { class: "ads-evhead" }, [
      el("b", {}, e.evidence_title),
      el("span", { class: "ads-chip ads-chip-calm" }, e.kind),
      el("span", { class: "ads-chip ads-chip-" + (
        e.nature === "真实" ? "good" : "calm") }, e.nature),
      ...(e.condition === "过期"
        ? [el("span", { class: "ads-chip ads-chip-warn" }, "过期")] : []),
      el("span", { class: "ads-mut ads-mono" }, e.valid_as_of || ""),
    ]),
    payloadDl(c, e),
  ]);
  if (e.caveat) w.appendChild(el("div", { class: "ads-cav" }, "注 · " + e.caveat));
  return w;
}

/* 不同证据类型的载荷形状不同，各挑关键项，不铺全量 JSON */
function payloadDl(c, e) {
  const { el, fmt } = c;
  const p = e.payload || {};
  const items = [];
  const kv = (k, v) => {
    if (v === null || v === undefined || v === "") return;
    items.push(el("dt", {}, k), el("dd", {}, String(v)));
  };
  const t = e.evidence_type;
  if (t === "INVENTORY") {
    kv("当前可售", fmt.num(p.closing_fba_sellable, 0));
    kv("覆盖天数", p.coverage_days == null ? null
      : p.coverage_days.toFixed(1) + " 天");
    kv("库存判定", riskCn(p.risk_status));
    kv("安全库存击穿", p.safety_breach_date);
    kv("基准断货", p.base_stockout_date === "none" ? "不断货"
      : p.base_stockout_date);
    kv("压力断货", p.stress_stockout_date === "none" ? "不断货"
      : p.stress_stockout_date);
    kv("最晚下单日", p.latest_order_date);
    kv("建议补货", p.suggested_replenishment_qty == null ? null
      : fmt.num(p.suggested_replenishment_qty, 0) + " 件");
  } else if (t === "PRODUCT_STAGE") {
    kv("生命周期", p.lifecycle);
    kv("品名", (p.product_name || "").slice(0, 30));
    kv("颜色 / 尺码", [p.colorway, p.size].filter(Boolean).join(" · "));
    // 库里这列是「类目名：排名」的字符串（例 Men's Boxer Briefs：9），
    // 不是纯数字。按数字格式化会得 NaN，原值直接显示。
    kv("小类目排名", p.category_rank == null ? null
      : String(p.category_rank));
    kv("评分", p.rating);
    kv("负责运营", p.operator);
  } else if (t === "SALES_TREND") {
    [["3 日", "daily_avg_3d"], ["7 日", "daily_avg_7d"],
     ["30 日", "daily_avg_30d"], ["90 日", "daily_avg_90d"]]
      .forEach(([lab, k]) => {
        if (p[k] != null) kv(lab + "日均", p[k].toFixed(0) + " 件");
      });
    if (p.daily_avg_3d != null && p.daily_avg_90d) {
      const dd = p.daily_avg_3d / p.daily_avg_90d - 1;
      kv("3 日对 90 日", (dd > 0 ? "+" : "") + (dd * 100).toFixed(0) + "%");
    }
  } else if (t === "BUSINESS_EVENT") {
    mergeSegs(p.planned).forEach((s) => kv("计划中 " + s.type,
      s.from + (s.to && s.to !== s.from ? " — " + s.to : "")));
    (p.inbound || []).forEach((x, i) => kv("到货批次 " + (i + 1),
      x.eta_earliest + " — " + x.eta_latest
      + (x.qty ? "　" + fmt.num(x.qty, 0) + " 件" : "")));
  } else if (t === "ATTRIBUTION_GAP") {
    kv("对象数", p.objects == null ? null : p.objects + " 个");
    kv("这些对象花费", p.spend == null ? null : usd(p.spend, 0));
    kv("其中广告销售额", p.ad_sales == null ? null
      : usd(p.ad_sales, 0));
  } else if (t === "AD_PLACEMENT") {
    (p.terms || []).forEach((x) => kv((x.term || "").slice(0, 22),
      "第 " + (x.rank == null ? "—" : x.rank) + " 位"
      + "　份额 " + fmt.pct(x.share, 2)
      + "　展示 " + fmt.num(x.impressions, 0)));
  } else if (t === "AD_PERFORMANCE") {
    kv("推广对象", p.object_count == null ? null : p.object_count + " 个");
    kv("合计花费", p.spend == null ? null : usd(p.spend, 0));
    kv("合计 ACoS", p.acos == null ? null : fmt.pct(p.acos, 1));
  } else if (t === "KEYWORD") {
    kv("监控词数", p.count == null ? null : p.count + " 个");
    kv("有广告覆盖", p.covered == null ? null : p.covered + " 个");
    kv("位置在下滑", p.losing == null ? null : p.losing + " 个");
    if ((p.absent_high_match || []).length)
      kv("高匹配但零覆盖", p.absent_high_match.join("、"));
  } else if (t === "COMPETITOR") {
    kv("竞品", (p.competitor || p.asin || "")
      + (p.brand ? " · " + p.brand : ""));
  } else if (t === "PRODUCT_GOAL") {
    kv("目标", p.goal_label || p.goal);
  } else if (t === "CATEGORY_BENCHMARK") {
    kv("CTR 我方 / 同类中位",
      fmt.pct(p.own_ctr, 2) + " / " + fmt.pct(p.peer_ctr_median, 2));
    kv("ACoS 我方 / 同类中位",
      fmt.pct(p.own_acos, 1) + " / " + fmt.pct(p.peer_acos_median, 1));
  } else {
    Object.entries(p).slice(0, 5).forEach(([k, v]) =>
      kv(k, typeof v === "object" ? "" : v));
  }
  return c.el("dl", { class: "ads-kv" }, items);
}

function mergeSegs(list) {
  const out = [];
  (list || []).slice()
    .sort((a, b) => String(a.from).localeCompare(String(b.from)))
    .forEach((x) => {
      const last = out[out.length - 1];
      const gap = last
        ? (new Date(x.from) - new Date(last.to)) / 86400000 : 99;
      if (last && last.type === x.type && gap <= 1) {
        if (String(x.to) > String(last.to)) last.to = x.to;
      } else {
        out.push({ type: x.type, from: x.from, to: x.to });
      }
    });
  return out;
}

function riskCn(v) {
  return ({ replenishment_gap: "需要补货", overstock: "超量备货",
            aged_inventory_risk: "高库龄风险", healthy: "健康",
            stockout: "断货" })[v] || v;
}

function constraintRow(c, x) {
  const { el } = c;
  const w = el("div", { class: "ads-evrow", "data-evid": x.evidence_ref || "" }, [
    el("div", { class: "ads-evhead" }, [
      el("span", { class: "ads-chip ads-chip-"
        + (x.kind === "hard" ? "alert" : "warn") },
        labelOf(x, "kind", "kind_label", "constraint_kind")),
      el("b", {}, x.label),
      // Agent 给的领域（成本 / 流量 / 库存 / 事件），之前没显示
      ...(x.domain
        ? [el("span", { class: "ads-chip ads-chip-calm" },
            labelOf(x, "domain", "domain_label", "constraint_domain"))] : []),
      ...(x.is_satisfied === 0
        ? [el("span", { class: "ads-chip ads-chip-alert" }, "未满足")]
        : x.is_satisfied === 1
          ? [el("span", { class: "ads-chip ads-chip-good" }, "已满足")] : []),
    ]),
  ]);
  if (x.detail) w.appendChild(el("div", { class: "ads-cav" }, x.detail));
  if (x.evidence_ref) {
    const r = evrefs(c, [x.evidence_ref]);
    if (r) w.appendChild(r);
  }
  return w;
}

function keywordTable(c, rows) {
  const { el, fmt } = c;
  const w = el("div", { class: "ads-kwtable" });
  w.appendChild(el("div", { class: "ads-kwrow ads-kwhead" },
    ["关键词", "月搜索", "自然位", "广告位", "份额", "位置变化", "与产品匹配"]
      .map((t, i) => el("div",
        { class: i === 0 ? "ads-kwname" : "ads-kwcell" }, t))));
  rows.forEach((k) => {
    const nm = el("div", { class: "ads-kwname" },
      [el("b", {}, k.keyword)]);
    if (k.limited_label)
      nm.appendChild(el("span",
        { class: "ads-chip ads-chip-warn" }, k.limited_label));
    const m = el("span", { class: "ads-match ads-match-" + k.match_level },
      k.match_label);
    m.addEventListener("click", (e) => {
      e.stopPropagation();
      popText(c, m, `${k.keyword} · ${k.match_label}\n`
        + `词表达的需求：${k.demand_side || "—"}\n`
        + `产品对应的：${k.product_side || "—"}\n`
        + `判断依据：${k.basis || "—"}`);
    });
    w.appendChild(el("div", { class: "ads-kwrow" }, [
      nm,
      el("div", { class: "ads-kwcell ads-kwnum" }, fmt.num(k.monthly_search, 0)),
      el("div", { class: "ads-kwcell ads-kwnum" },
        k.organic_rank == null ? "—" : String(k.organic_rank)
        + (k.organic_rank_prev != null
          && k.organic_rank_prev !== k.organic_rank
          ? " ← " + k.organic_rank_prev : "")),
      el("div", { class: "ads-kwcell ads-kwnum" },
        k.ad_rank == null ? "—" : String(k.ad_rank)),
      el("div", { class: "ads-kwcell ads-kwnum" },
        fmt.pct(k.ad_impression_share, 2)),
      el("div", { class: "ads-kwcell" },
        [el("span", { class: "ads-trend ads-trend-" + k.position_trend },
          k.trend_label)]),
      el("div", { class: "ads-kwcell" }, [m]),
    ]));
  });
  return w;
}

function pressureRow(c, p) {
  const { el } = c;
  const w = el("div", { class: "ads-evrow" }, [
    el("div", { class: "ads-evhead" }, [
      el("span", { class: "ads-chip ads-chip-warn" }, p.type_label),
      el("b", {}, p.pressure_label),
      el("span", { class: "ads-chip ads-chip-"
        + (p.is_verified ? "good" : "calm") }, p.verify_label),
    ]),
  ]);
  if (p.detail) w.appendChild(el("div", { class: "ads-cav" }, p.detail));
  return w;
}

function reviewRow(c, r) {
  const { el, fmt } = c;
  const b = r.baseline_metrics || {};
  const o = r.observed_metrics || {};
  const items = [];
  const kv = (k, v) => items.push(el("dt", {}, k), el("dd", {}, v));
  kv("ACoS", fmt.pct(b.acos, 1) + " → " + fmt.pct(o.acos, 1));
  kv("CVR", fmt.pct(b.cvr, 1) + " → " + fmt.pct(o.cvr, 1));
  kv("广告销售额",
    usd(b.ad_sales, 0) + " → " + usd(o.ad_sales, 0));
  const w = el("div", { class: "ads-evrow" }, [
    el("div", { class: "ads-evhead" }, [
      el("b", {}, r.review_window + " 复盘"),
      el("span", { class: "ads-mut ads-mono" }, r.review_at || ""),
    ]),
    el("dl", { class: "ads-kv" }, items),
  ]);
  if (r.conclusion) w.appendChild(el("div", { class: "ads-cav" }, r.conclusion));
  if ((r.concurrent_variables || []).length)
    w.appendChild(el("div", { class: "ads-cav" },
      "同期变量未控制 · " + r.concurrent_variables.join("、")));
  return w;
}

/* 板块4/6/7/8 Agent 输出 */
const STAGE_TITLE = {
  task: "应有广告任务", mapping: "目标—结构—表现对照",
  diagnosis: "广告诊断与优先级", proposal: "广告调整方案",
};

function sectionStage(c, stage) {
  const { el } = c;
  const shown = view.shown[stage];
  const sec = el("section",
    { class: "ads-card ads-agent" + (shown ? "" : " ads-idle"),
      "data-stage": stage });
  const tag = el("span", { class: "ads-stagetag" + (shown ? " ads-done" : "") },
    shown ? shown.items.length + " 条"
      : view.running ? "分析中…" : "未运行");
  sec.appendChild(el("div", { class: "ads-secthead" }, [
    el("h2", { class: "ads-h2" }, STAGE_TITLE[stage]), tag,
  ]));
  const box = el("div", { class: "ads-agentbody" });
  if (!shown) {
    box.appendChild(el("div", { class: "ads-hint" }, view.running
      ? "等待上一段完成…"
      : "Agent 不会自动跑。确认上面的依据没问题，再点「开始分析」。"));
  } else {
    const R = { task: rowTask, mapping: rowMapping,
                diagnosis: rowDiagnosis, proposal: rowProposal };
    shown.items.forEach((it) => box.appendChild(R[stage](c, it)));
    if (stage === "diagnosis") {
      const cov = coverageBox(c);
      if (cov) box.appendChild(cov);
    }
  }
  sec.appendChild(box);
  return sec;
}

function aiCard(c, main, side) {
  return c.el("div", { class: "ads-ai" }, [main, side]);
}

function line(c, main, lab, v) {
  if (!v) return;
  main.appendChild(c.el("div", { class: "ads-line" }, [
    c.el("em", {}, lab), c.el("span", {}, v),
  ]));
}

/* Agent 落表时既写码值也写中文 label（实测 task_type + task_label 并存），
   回放路径则由服务端翻译。两条路命名不完全一致，所以取值走这一个口子：
   有 label 用 label，没有就用本地映射，都没有才退到「待确认」——
   任何情况下都不把码值摆到屏上。 */
const LOCAL_CN = {
  // 与 compute.py 顶部的映射表同源。Agent 只出码值，中文一律在这里翻；
  // 缺映射时 labelOf 给中性兜底并 console.warn，不把码值摆上屏。
  task_type: {
    VERIFY_INBOUND_BEFORE_SCALE: "先核验入库再扩量",
    PROTECT_CORE_QUERY_VISIBILITY: "守住核心词可见性",
    CONTROL_EFFICIENCY_DRIFT: "控制效率漂移",
    OBSERVE_EFFICIENCY: "观察效率",
    CLEAR_AGED_INVENTORY: "处理高库龄库存",
    ACCELERATE_SELL_THROUGH: "加速去库存",
    COVER_MATCHED_QUERY_GAP: "补上匹配词的覆盖缺口",
    CLARIFY_ATTRIBUTION_BOUNDARY: "厘清归因边界",
    MAINTAIN_CURRENT_SETUP: "维持当前配置",
  },
  problem_type: {
    INVENTORY_COVERAGE_RISK: "库存承接不足",
    CORE_QUERY_DEFENSE: "核心词守位存在缺口",
    ACOS_UP_VS_SELF_HISTORY: "ACoS 高于自身历史",
    EFFICIENCY_VARIATION: "效率波动",
    KEYWORD_COVERAGE_GAP: "关键词机会存在但覆盖不足",
    ATTRIBUTION_UNCLEAR: "广告对象与子 ASIN 关系不清",
    GOAL_PURPOSE_MISMATCH: "产品目标与广告目的不一致",
    MIXED_PURPOSE_GROUP: "一个广告组混合多个目的",
    REQUIRED_TASK_MISSING: "必要广告任务缺失",
    DUPLICATE_TASK_OWNERS: "多个广告组重复承担同一任务",
    PERFORMANCE_NOT_SUPPORTING: "表现不支撑已确认的目的",
    COMPETITOR_NO_TASK: "竞品压力存在但无对应任务",
    INSUFFICIENT_EVIDENCE: "证据或规则不足暂时无法判断",
    NO_ADJUSTMENT_NEEDED: "本期无需调整",
  },
  direction: {
    KEEP: "保持",
    OBSERVE: "继续观察",
    ADJUST: "调整",
    PAUSE: "暂停",
    RESUME: "恢复",
    SPLIT: "拆分",
    MERGE: "合并",
    BUILD: "补建",
    TEST: "低成本测试",
    DEFER: "暂缓",
    REQUEST_INFO: "先补信息",
    PREREQUISITE: "前置条件",
    NEW_STRUCTURE: "补建结构",
  },
  task_direction: {
    KEEP: "保持",
    OBSERVE: "继续观察",
    ADJUST: "调整",
    PAUSE: "暂停",
    RESUME: "恢复",
    SPLIT: "拆分",
    MERGE: "合并",
    BUILD: "补建",
    TEST: "低成本测试",
    DEFER: "暂缓",
    REQUEST_INFO: "先补信息",
    PREREQUISITE: "前置条件",
    NEW_STRUCTURE: "补建结构",
  },
  confidence: {
    high: "高",
    medium: "中",
    low: "低",
  },
  attribution_limit: {
    exclusive: "只归本品", shared: "与其他子 ASIN 共享",
    unattributed: "无法归因",
  },
  gap_source: {
    structure: "结构没建", evidence: "证据不足", none: "无差距",
  },
  basis: {
    confirmed_rule: "客户已确认阈值", self_history: "自身历史",
    peer: "可比对象", conditional: "条件判断",
  },
  constraint_kind: { hard: "硬性条件", observe: "需要观察" },
  judgment_mode: {
    formal: "正式判断", conditional: "条件性判断", unable: "暂时无法判断",
  },
  match_level: { high: "高匹配", medium: "中匹配", low: "低匹配" },
  pressure_type: {
    price: "价格压制", rank: "排名压制", keyword_entry: "核心词入口被占",
    review: "评价压制", variant: "变体覆盖更广", promotion: "活动压制",
  },
  issue_type: {
    shared: "共享给多个子 ASIN", unexplained: "无法归到任何广告目的",
    duplicate: "多个对象重复承担", orphan: "无对应产品关系",
  },
  constraint_domain: {
    cost: "成本", traffic: "流量", inventory: "库存", event: "事件",
  },
};

// 缺映射时按字段给中性兜底，比统一的「待确认」有信息量。
// 与 compute.py 的 _FALLBACK_CN 同源。
const FALLBACK_CN = {
  task_type: "未归类任务",
  problem_type: "未归类问题",
  direction: "待确认方向",
  task_direction: "待确认方向",
  coverage_status: "覆盖情况待确认",
  attribution_limit: "归因边界待确认",
  basis_type: "依据档位待确认",
  basis_level: "依据档位待确认",
  gap_source: "差距归类待确认",
  issue_type: "未归类结构问题",
  pressure_type: "未归类竞品压力",
  match_level: "匹配度待确认",
  judgment_mode: "判断档位待确认",
  confidence: "可信程度待确认",
};

function labelOf(obj, codeKey, labelKey, mapName) {
  const lab = labelKey && obj[labelKey];
  if (lab) return lab;
  const code = obj[codeKey];
  if (code === null || code === undefined || code === "") return "";
  // 映射名缺省就用码值的字段名——LOCAL_CN 的键就是按字段名建的。
  // 之前四处调用漏传第四参，结果全查不到表、全落到「待确认」兜底。
  const m = LOCAL_CN[mapName || codeKey];
  if (m && m[code]) return m[code];
  // 词表外：不摆码值，同时留个痕迹好排查
  console.warn("[ads] 缺中文映射", codeKey, code);
  return FALLBACK_CN[codeKey] || "待确认";
}

function rowTask(c, t) {
  const { el } = c;
  const main = el("div", { class: "ads-aimain" }, [
    el("div", { class: "ads-aihead" }, [
      el("span", { class: "ads-pri ads-pri-" + t.priority }, t.priority),
      el("b", {}, labelOf(t, "task_type", "task_label")),
      el("span", { class: "ads-dir" },
        labelOf(t, "task_direction", "direction_label")),
      ...(t.inventory_constrained
        ? [el("span", { class: "ads-chip ads-chip-warn" }, "受库存约束")] : []),
    ]),
  ]);
  line(c, main, "作用范围", t.target_scope);
  line(c, main, "怎么判断达成", t.evaluation_direction);
  line(c, main, "什么时候停", t.stop_condition);
  line(c, main, "经营约束", (t.constraints || []).join("；"));
  // 适用时间：方案 7.2 要求任务说明优先级与适用时间，之前只显示了优先级
  const from = t.applies_from, to = t.applies_to;
  if (from) line(c, main, "适用时间", to ? `${from} 至 ${to}` : `${from} 起`);
  const r = evrefs(c, t.evidence_ids);
  if (r) main.appendChild(r);
  const side = el("div", { class: "ads-aiside" }, [
    el("div", { class: "ads-mode" },
      labelOf(t, "judgment_mode", "mode", "judgment_mode")),
  ]);
  if (t.exact_values_withheld) {
    side.appendChild(el("div", { class: "ads-withheld" },
      "规则未确认，不给预算 / 竞价 / 广告位数值"));
  } else {
    // 规则确认后 Agent 会给精确值，之前前端完全没有这个分支
    const nums = [["预算", t.exact_budget, 2], ["竞价", t.exact_bid, 2],
                  ["广告位调整", t.exact_placement_adjustment, null]];
    nums.forEach(([lab, v, d]) => {
      if (v === null || v === undefined) return;
      side.appendChild(el("div", { class: "ads-exact" },
        lab + " " + (d === null ? fmt.pct(v, 0) : usd(v, d))));
    });
  }
  return aiCard(c, main, side);
}

function rowMapping(c, m) {
  const { el, fmt } = c;
  const main = el("div", { class: "ads-aimain" }, [
    el("div", { class: "ads-aihead" }, [
      el("b", {}, m.task_label),
      el("span", { class: "ads-cov ads-cov-" + m.coverage_status },
        m.coverage_label),
    ]),
  ]);
  const ao = m.ad_object;
  if (ao) {
    const mm = ao.metrics || {};
    line(c, main, "承担对象", (ao.name || "") + " · " + ao.ad_type);
    main.appendChild(el("div", { class: "ads-line ads-mono" },
      "花费 " + usd(mm.spend, 0) + "　ACoS " + fmt.pct(mm.acos, 1)
      + "　ROAS " + (mm.roas == null ? "—" : mm.roas.toFixed(2))
      + "　归因 " + (ao.attribution_days || "—") + " 天"));
  } else {
    line(c, main, "承担对象", "无——这是结构缺口，当前没有广告对象承接");
  }
  line(c, main, "对象与任务是否匹配", m.target_fit);
  line(c, main, "结果是否支撑目的", m.result_supports_purpose);
  line(c, main, "说明", m.note);
  const r = evrefs(c, m.evidence_ids);
  if (r) main.appendChild(r);
  const side = el("div", { class: "ads-aiside" }, []);
  // Agent 写的是码值（gap_source / basis_level / attribution_limit），
  // 回放路径写的是 *_label。走 labelOf 两条路都能显示，之前这三格是空的。
  const gap = labelOf(m, "gap_source", "gap_label", "gap_source");
  if (gap && gap !== "无差距")
    side.appendChild(el("div", { class: "ads-gap" }, gap));
  const basis = labelOf(m, "basis_level", "basis_label", "basis");
  if (basis) side.appendChild(el("div", {}, "判断依据 " + basis));
  const attr = labelOf(m, "attribution_limit", "attribution_label",
                       "attribution_limit");
  if (attr) side.appendChild(el("div", {}, "归因 " + attr));
  if (m.is_automatic_error)
    side.appendChild(el("div", { class: "ads-withheld" },
      "自动映射存疑，需人工核对"));
  return aiCard(c, main, side);
}

function rowDiagnosis(c, d) {
  const { el } = c;
  const main = el("div", { class: "ads-aimain" }, [
    el("div", { class: "ads-aihead" }, [
      el("span", { class: "ads-pri ads-pri-" + d.priority }, d.priority),
      el("b", {}, labelOf(d, "problem_type", "problem_label")),
    ]),
  ]);
  if (d.what_happened)
    main.appendChild(el("div", { class: "ads-what" }, d.what_happened));
  line(c, main, "影响哪个目标", d.impacted_goal);
  line(c, main, "还缺什么", d.missing_input);
  line(c, main, "不确定项", d.uncertainty);
  line(c, main, "往哪个方向查", d.check_direction);
  line(c, main, "对应任务", d.task_label);
  const r = evrefs(c, d.evidence_ids);
  if (r) main.appendChild(r);
  const side = el("div", { class: "ads-aiside" }, [
    el("div", { class: "ads-mode" },
      labelOf(d, "judgment_mode", "mode", "judgment_mode")),
    el("div", {}, "可信程度 " + labelOf(d, "confidence", "confidence_label", "confidence")),
    el("div", {}, "判断依据 "
      + labelOf(d, "basis_type", "basis_label", "basis")),
    el("div", { class: "ads-withheld" },
      d.causal_claim ? "声明了因果" : "未声明因果，只报同期观察"),
  ]);
  return aiCard(c, main, side);
}

/* B0cd 词与竞品判断。Agent 一步出完，用 item_kind 分两类。
   落在板块3「判断依据」，因为它判的是外部市场事实。 */
function kwMatchRow(c, x) {
  const { el } = c;
  const w = el("div", { class: "ads-evrow" }, [
    el("div", { class: "ads-evhead" }, [
      el("span", { class: "ads-chip ads-chip-"
        + (x.match_level === "high" ? "good"
          : x.match_level === "low" ? "warn" : "calm") },
        labelOf(x, "match_level", "match_level_label", "match_level")),
      el("b", {}, x.kw_id ? kwName(x.kw_id) : "关键词"),
    ]),
  ]);
  // 三段式：词要什么 / 产品是什么 / 所以判成这个档
  if (x.demand_side) line(c, w, "这个词的需求", x.demand_side);
  if (x.product_side) line(c, w, "本品是什么", x.product_side);
  if (x.basis) line(c, w, "为什么这个档", x.basis);
  const r = evrefs(c, x.evidence_ids);
  if (r) w.appendChild(r);
  return w;
}

function pressureRowAgent(c, x) {
  const { el } = c;
  const w = el("div", { class: "ads-evrow" }, [
    el("div", { class: "ads-evhead" }, [
      el("span", { class: "ads-chip ads-chip-warn" },
        labelOf(x, "pressure_type", "pressure_label", "pressure_type")),
      el("b", {}, [x.brand, x.competitor_asin].filter(Boolean).join(" · ")),
      ...(x.is_verified
        ? [el("span", { class: "ads-chip ads-chip-calm" }, "已核验")] : []),
    ]),
  ]);
  if (x.detail) w.appendChild(el("div", { class: "ads-cav" }, x.detail));
  if (x.observed_at)
    w.appendChild(el("div", { class: "ads-mut ads-mono" }, x.observed_at));
  const r = evrefs(c, x.evidence_ids);
  if (r) w.appendChild(r);
  return w;
}

function b0cdRow(c, x) {
  return x.item_kind === "competitor_pressure"
    ? pressureRowAgent(c, x) : kwMatchRow(c, x);
}

/* B0e 结构问题识别。落在板块5「现有广告结构」。 */
function structIssueRow(c, x) {
  const { el } = c;
  const w = el("div", { class: "ads-evrow" }, [
    el("div", { class: "ads-evhead" }, [
      el("span", { class: "ads-chip ads-chip-warn" },
        labelOf(x, "issue_type", "issue_label", "issue_type")),
      el("b", {}, x.label || ""),
    ]),
  ]);
  if (x.ad_object_id)
    line(c, w, "涉及对象", objName(x.ad_object_id));
  if (x.detail) w.appendChild(el("div", { class: "ads-cav" }, x.detail));
  const r = evrefs(c, x.evidence_ids);
  if (r) w.appendChild(r);
  return w;
}

/* B3b 诊断覆盖说明。十类逐类，没命中要说为什么没命中。 */
function coverageRow(c, x) {
  const { el } = c;
  return el("div", { class: "ads-covrow" }, [
    el("span", { class: "ads-chip ads-chip-" + (x.hit ? "good" : "calm") },
      x.hit ? "命中" : "未命中"),
    el("span", { class: "ads-covname" },
      labelOf(x, "problem_type", "problem_label")),
    ...(x.why_not
      ? [el("span", { class: "ads-mut" }, x.why_not)] : []),
  ]);
}

function kwName(kwId) {
  const rows = ((view.ctx || {}).keywords) || [];
  const hit = rows.find((k) => k.kw_id === kwId);
  return hit ? hit.keyword : kwId;
}

function rowProposal(c, p) {
  const { el } = c;
  const main = el("div", { class: "ads-aimain" }, [
    el("div", { class: "ads-aihead" }, [
      el("b", {}, labelOf(p, "direction", "direction_label")),
      el("span", { class: "ads-dir" }, p.ad_purpose),
    ]),
  ]);
  line(c, main, "作用对象", p.ad_object_id
    ? objName(p.ad_object_id)
    : (p.structure_gap_id
       ? "当前无广告对象承接，对应结构缺口 " + gapName(p.structure_gap_id)
       : "当前无广告对象承接（结构缺口）"));
  line(c, main, "依据", p.rationale);
  line(c, main, "执行前置条件", (p.preconditions || []).join("；"));
  line(c, main, "主要风险", (p.risks || []).join("；"));
  line(c, main, "不确定项", p.uncertainty);
  line(c, main, "之后观察什么",
    (p.observation_metrics || []).join("、")
    + "　窗口 " + (p.review_windows || []).join(" / "));
  line(c, main, "来自诊断", p.diagnosis_label);
  const pr = evrefs(c, p.evidence_ids);
  if (pr) main.appendChild(pr);
  if (p.d7_not_required)
    main.appendChild(el("div", { class: "ads-line ads-mut" },
      "本条只需 D+3 复盘，不必等 D+7"));

  const dec = el("div", { class: "ads-decide" });
  const done = view.decided[p.recommendation_id];
  if (done) {
    dec.appendChild(el("span", { class: "ads-decided" },
      "已" + done.decision_label + " · " + done.handoff_label));
    const again = el("button", { class: "ads-btn", type: "button" }, "改回未决");
    again.addEventListener("click", () => {
      delete view.decided[p.recommendation_id];
      render(c);
    });
    dec.appendChild(again);
  } else {
    [["accept", "接受"], ["modify", "修改后接受"],
     ["reject", "拒绝"], ["defer", "暂缓"]].forEach(([act, lab]) => {
      const b = el("button", { class: "ads-btn", type: "button" }, lab);
      b.addEventListener("click", () => decide(c, p, act));
      dec.appendChild(b);
    });
  }
  main.appendChild(dec);
  if (done && done.handoff) main.appendChild(handoffBox(c, done.handoff));

  const side = el("div", { class: "ads-aiside" }, [
    el("div", { class: "ads-mode" },
      labelOf(p, "judgment_mode", "mode", "judgment_mode")),
  ]);
  if (p.exact_values_withheld) {
    side.appendChild(el("div", { class: "ads-withheld" },
      "规则未确认，只给方向不给数值"));
  } else if (p.exact_value !== null && p.exact_value !== undefined) {
    // 规则确认后 Agent 会给具体值，之前前端没有这个分支
    side.appendChild(el("div", { class: "ads-exact" },
      "建议值 " + p.exact_value));
  }
  return aiCard(c, main, side);
}

/* 结构缺口 id 不上屏，翻成人话。Agent 给的是 gap_<问题类型> 形式。 */
function gapName(gid) {
  const m = {
    gap_inventory_coverage_risk: "库存承接不足",
    gap_keyword_coverage_gap: "关键词覆盖不足",
    gap_required_task_missing: "必要任务无人承担",
    gap_attribution_unclear: "归因边界不清",
  };
  if (m[gid]) return m[gid];
  console.warn("[ads] 缺结构缺口映射", gid);
  return "待确认";
}

function objName(oid) {
  const s = ((view.ctx || {}).existing_structure || [])
    .find((x) => x.ad_object_id === oid);
  return s ? s.name : oid;
}

function handoffBox(c, h) {
  const { el } = c;
  const items = [];
  Object.entries(h).forEach(([k, v]) => {
    if (v === null || v === undefined || v === ""
      || (Array.isArray(v) && !v.length)) return;
    items.push(el("dt", {}, k),
      el("dd", {}, Array.isArray(v) ? v.join("、") : String(v)));
  });
  return el("div", { class: "ads-handoff" }, [
    el("div", { class: "ads-mut" }, "交接给执行与复盘模块"),
    el("dl", { class: "ads-kv" }, items),
  ]);
}

function coverageBox(c) {
  const { el } = c;
  const cov = (view.run || {}).diagnosis_coverage || [];
  const miss = cov.filter((x) => !x.hit);
  if (!cov.length) return null;
  const box = el("details", { class: "ads-cov" }, [
    el("summary", {}, `已逐项检查 ${cov.length} 类问题，`
      + `本次命中 ${cov.length - miss.length} 类`),
    // Agent 只给 problem_type 码值，中文由 coverageRow 翻。
    // 十类全列出来（含命中的），因为「查过没发现」也是结论。
    el("div", { class: "ads-covlist" }, cov.map((x) => coverageRow(c, x))),
  ]);
  return box;
}

/* --------------------------------------------------------- 展开与决定 */
async function runAgent(c) {
  // 名字保留但语义变了：结果已在进页面时读好，这里只做分段揭示，
  // 让依赖链看得见（B1 → B2 → B3 → B4）。不再发 run 请求。
  if (view.running) return;
  const res = view.run;
  if (!res || !res.run_id) return;
  view.running = true;
  view.shown = {}; view.decided = {};
  render(c);
  for (const st of res.stages || []) {
    await new Promise((r) => setTimeout(r, STAGE_DELAY));
    view.shown[st.stage] = st;
    render(c);
  }
  view.running = false;
  render(c);
}

async function decide(c, p, act) {
  try {
    const d = await c.api("decide", {
      child_asin: view.asin, recommendation_id: p.recommendation_id,
      decision: act,
    });
    if (d.condition !== "正常") return;
    view.decided[p.recommendation_id] = d;
    render(c);
  } catch (err) { /* 外壳已提示，不再重复 */ }
}

/* 板块5 现有广告结构与目的 */
function sectionStructure(c, d) {
  const { el, fmt } = c;
  const rows = d.existing_structure;
  const head = ["广告对象", "类型", "广告目的", "共享", "花费",
                "广告销售额", "ACoS", "ROAS", "点击", "订单"];
  const table = el("div", { class: "ads-table" }, [
    el("div", { class: "ads-trow ads-thead" },
      head.map((t, i) => el("div",
        { class: "ads-td" + (i >= 4 ? " ads-tnum" : "") }, t))),
  ]);
  rows.forEach((r) => {
    table.appendChild(el("div",
      { class: "ads-trow", "data-oid": r.ad_object_id }, [
        el("div", { class: "ads-td" }, [
          el("b", {}, r.name || ""),
          el("em", {}, r.level_label
            + (r.attribution_days ? " · 归因 " + r.attribution_days + " 天" : "")),
        ]),
        el("div", { class: "ads-td" }, r.ad_type),
        el("div", { class: "ads-td" }, [
          el("span", { class: "ads-tag" },
            (r.purpose || "—").split(",")[0]),
        ]),
        el("div", { class: "ads-td" },
          r.is_shared ? String(r.shared_child_count) : "独占"),
        el("div", { class: "ads-td ads-tnum" }, usd(r.spend, 0)),
        el("div", { class: "ads-td ads-tnum" }, usd(r.ad_sales, 0)),
        el("div", { class: "ads-td ads-tnum" }, fmt.pct(r.acos, 1)),
        el("div", { class: "ads-td ads-tnum" },
          r.roas == null ? "—" : r.roas.toFixed(2)),
        el("div", { class: "ads-td ads-tnum" }, fmt.num(r.clicks, 0)),
        el("div", { class: "ads-td ads-tnum" }, fmt.num(r.orders, 0)),
      ]));
  });
  const sec = el("section", { class: "ads-card" }, [
    el("div", { class: "ads-secthead" }, [
      el("h2", { class: "ads-h2" }, "现有广告结构与目的"),
      el("span", { class: "ads-mut" },
        `${rows.length} 个广告对象，`
        + `${rows.filter((r) => r.is_shared).length} 个与其他子 ASIN 共享`),
      infoBtn(c, "现有广告结构",
        "只还原当前这一个子 ASIN 的结构。\n"
        + "批量打标签、按标签筛选、横向比较回「广告分类与数据查看」。\n"
        + "共享列的数字是这个广告对象同时推广的子 ASIN 个数，"
        + "大于 1 时它的结果不能全部归到当前子 ASIN。"),
    ]),
    el("div", { class: "ads-tablewrap" }, [table]),
  ]);
  // B0e 是 Agent 的判断，到位就用它，不用预烤的 ext_structure_issue
  const agentB0e = (view.run && view.run.points
    && view.run.points.B0e) || null;
  const issues = agentB0e || d.structure_issues || [];
  if (issues.length) {
    const box = el("div", { class: "ads-issues" },
      [subhead(c, (agentB0e ? "本次分析判定的结构问题 " : "结构中已确认的问题 ")
        + issues.length + " 处")]);
    issues.forEach((x) => {
      const w = structIssueRow(c, x);
      if (x.ad_object_id) {
        const j = el("button", { class: "ads-ref", type: "button" }, "定位对象");
        j.addEventListener("click", () => flashStruct(x.ad_object_id));
        w.querySelector(".ads-evhead").appendChild(j);
      }
      box.appendChild(w);
    });
    sec.appendChild(box);
  }
  return sec;
}

function flashStruct(oid) {
  const row = host && host.body
    ? host.body.querySelector(`.ads-trow[data-oid="${oid}"]`) : null;
  if (!row) return;
  host.body.querySelectorAll(".ads-flash")
    .forEach((r) => r.classList.remove("ads-flash"));
  row.classList.add("ads-flash");
  row.scrollIntoView({ block: "center", behavior: "smooth" });
  setTimeout(() => row.classList.remove("ads-flash"), 2400);
}
