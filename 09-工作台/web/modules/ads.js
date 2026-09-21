/* 广告分析模块 · 前端（契约 8.2）
 *
 * 零全局：只有 export，不往 window / globalThis 挂东西。
 * $ / el / 格式化 / 浮层 / 抽屉 / 徽标全部从 ctx 取，不自己实现。
 *
 * 本文件 = 页面一（广告分类与数据查看）+ 侧栏 + 两页分派。
 * 页面二整页在 ./ads/page2.js，图形原语在 ./ads/charts.js，
 * 两页共用的格式化与中文映射在 ./ads/util.js（**只此一份，不许各抄一份**）。
 *
 * 页面二形态：Agent 不自动跑，页面读它已落库的最新一次完成运行。
 * 「可核验」靠一条机制：Agent 每条输出的 evidence_ids 只引用 context.evidence
 * 里的 id，后端 gate 路由把这条做成门禁。
 */

import { renderPage2, disposeDaily } from "./ads/page2.js";
import { downloadExport, infoBtn, popText, subhead, usd } from "./ads/util.js";

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

let host = null;
let ctxRef = null;
let view = {
  asin: null, ctx: null, run: null, decided: {}, groups: null,
  // 示例调整方案：默认 null = 没载入。点按钮才请求，绝不自动取
  demo: null, decidedDemo: {},
  // 建议区批量审批勾选的 recommendation_id。只活在这次会话里，
  // 不进 URL 也不落库 —— 勾选是操作过程，不是可分享的页面状态。
  picked: new Set(),
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
  // 切模块时必须 dispose ECharts 实例，否则它连着已被清空的 DOM 泄漏
  disposeDaily();
  host = null;
  ctxRef = null;
  expanded = {};
  railQ = null;
  campQ = "";
  view = { asin: null, ctx: null, run: null, decided: {}, groups: null,
           demo: null, decidedDemo: {}, picked: new Set() };
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
    view.ctx = null; view.run = null; view.decided = {};
    view.demo = null; view.decidedDemo = {};
    view.picked = new Set();   // 换了 ASIN，上一屏勾的那几条不能跟过来
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

  // 板块4 指标视图 —— 照 2026-09-04 参考稿的构图：
  // 左侧竖排「总览 / 趋势」页签，右侧两个归因块并排，每块九个指标，
  // 每个指标下面挂真实的环比（后半月对前半月，两侧各 15 天等长）。
  body.appendChild(metricView(c, d));

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

/* 指标视图（照 2026-09-04 参考稿构图）
 *
 * 左侧竖排页签「总览 / 趋势」，右侧两个归因块并排。
 * 每块九个指标一行排开，每个指标下面挂环比。
 *
 * 环比是**真的**：由 page1.py 的 half_change() 把块内每个对象的前后半窗汇总
 * 相加再算比率做比值，基准「后半月对前半月，两侧各 15 天等长」，
 * 样本不足的对象不进汇总。参考稿上那个「较上期」不是装饰，所以不允许编。
 *
 * 两块必须分开：SP 是 7 天归因、SB/SD 是 14 天归因，归因销售额加在一起
 * 做分母会算出一个不存在的合计 ACoS（page1.py 文件头第一条口径）。
 *
 * 比率类指标的环比用**百分点**，量类用百分比 —— ACoS 从 20% 到 25% 是
 * 涨了 5 个点、不是涨了 25%，两种说法在屏幕上必须分得开。
 */
const METRIC_SPEC = [
  ["spend", "花费", "usd0", "vol"],
  ["ad_sales", "广告销售额", "usd0", "vol"],
  ["orders", "订单", "int", "vol"],
  ["clicks", "点击", "int", "vol"],
  ["ctr", "CTR", "pct2", "rate"],
  ["cpc", "CPC", "usd2", "vol"],
  ["cvr", "CVR", "pct1", "rate"],
  ["acos", "ACoS", "pct2", "rate"],
  ["roas", "ROAS", "x2", "vol"],
];
// 哪个方向算好。花费/点击/曝光本身没有好坏，不着色（与页面二同一口径）。
const METRIC_BETTER = {
  ad_sales: "up", orders: "up", ctr: "up", cvr: "up", roas: "up",
  cpc: "down", acos: "down",
};

function fmtMetric(c, v, kind) {
  const { fmt } = c;
  if (v === null || v === undefined) return "—";
  if (kind === "usd0") return usd(v, 0);
  if (kind === "usd2") return usd(v, 2);
  // fmt.num 走 toFixed，不带千分位 —— 13124 会渲染成「13124」。
  // 带分隔符的是 fmt.int，外壳只有 money 那个漏了（见 util.js 的 usd）。
  if (kind === "int") return fmt.int(v);
  if (kind === "pct1") return fmt.pct(v, 1);
  if (kind === "pct2") return fmt.pct(v, 2);
  if (kind === "x2") return Number(v).toFixed(2);
  return String(v);
}

/* 环比一格：箭头 + 幅度。比率类给百分点，量类给百分比。 */
function deltaCell(c, key, rate, base, mode) {
  const { el } = c;
  if (rate === null || rate === undefined || Number.isNaN(rate)) {
    return el("span", { class: "ads-dl ads-dl-na" }, "—");
  }
  const up = rate > 0;
  const better = METRIC_BETTER[key];
  const tone = !better ? "" : ((up ? better === "up" : better === "down")
    ? "good" : "alert");
  let text;
  if (mode === "rate" && base !== null && base !== undefined) {
    // 百分点：目标值与基准值之差，不是相对变化
    const pp = base * rate * 100;
    text = (up ? "↑ " : "↓ ") + Math.abs(pp).toFixed(2) + "pp";
  } else {
    text = (up ? "↑ " : "↓ ") + Math.abs(rate * 100).toFixed(2) + "%";
  }
  return el("span", { class: "ads-dl" + (tone ? " ads-t-" + tone : "") }, text);
}

function metricBlock(c, b) {
  const { el } = c;
  const ch = b.change || {};
  const cells = METRIC_SPEC.map(([key, label, kind, mode]) => el(
    "div", { class: "ads-mv-cell" }, [
      el("div", { class: "ads-mv-lab" }, label),
      el("div", { class: "ads-mv-val" }, fmtMetric(c, b[key], kind)),
      deltaCell(c, key, ch[key], b[key], mode),
    ]));
  const head = el("div", { class: "ads-mv-head" }, [
    el("b", {}, `${b.attribution_days} 天归因`),
    el("span", { class: "ads-mut" },
      `${b.ad_types.join(" / ")} · ${b.objects} 个对象`),
    infoBtn(c, `${b.attribution_days} 天归因`,
      `广告类型：${b.ad_types.join(" / ")}，共 ${b.objects} 个对象。\n`
      + (ch.objects
        ? `环比纳入 ${ch.objects} / ${ch.of} 个对象（前后半窗各至少 `
          + `${ch.min_clicks_per_half} 次点击），基准是${ch.basis}。\n`
          + "比率类指标的环比按百分点给，量类按百分比给。"
        : "环比不可比：" + (ch.why || "样本不足") + "。\n"
          + "日线只能从搜索词报表拿到，只覆盖 SP，所以这一块没有可比的前后半窗。")
      + "\n\n花费是真实支出，跨归因周期可以相加；"
      + "广告销售额不能相加，所以两块分开给，不出合计 ACoS。"),
  ]);
  return el("div", { class: "ads-mvblk" }, [
    head, el("div", { class: "ads-mv-cells" }, cells),
    ch.objects
      ? el("div", { class: "ads-mv-foot" },
        `较上期 · 纳入 ${ch.objects}/${ch.of} 个对象`)
      : el("div", { class: "ads-mv-foot ads-mv-foot-na" },
        "较上期不可比 · " + (ch.why || "样本不足")),
  ]);
}

/* 趋势页签：块内逐日汇总。花费与广告销售额画柱，ACoS 画线（独立轴从 0 起）。 */
function trendBlock(c, b) {
  const { el } = c;
  const s = b.daily || [];
  if (!s.length) {
    return el("div", { class: "ads-mvblk" }, [
      el("div", { class: "ads-mv-head" }, [
        el("b", {}, `${b.attribution_days} 天归因`),
        el("span", { class: "ads-mut" }, b.ad_types.join(" / ")),
      ]),
      el("div", { class: "ads-hint" }, b.daily_note || "没有逐日序列"),
    ]);
  }
  const maxV = Math.max(...s.map((x) => Math.max(x.spend || 0,
    x.ad_sales || 0)), 1);
  const rows = s.map((x) => {
    const sw = ((x.spend || 0) / maxV * 100).toFixed(2);
    const aw = ((x.ad_sales || 0) / maxV * 100).toFixed(2);
    return `<span class="ads-tb" title="${x.date}">
      <span class="ads-tb-t">
        <span class="ads-tb-s" style="height:${sw}%"></span>
        <span class="ads-tb-a" style="height:${aw}%"></span>
      </span></span>`;
  }).join("");
  return el("div", { class: "ads-mvblk" }, [
    el("div", { class: "ads-mv-head" }, [
      el("b", {}, `${b.attribution_days} 天归因`),
      el("span", { class: "ads-mut" },
        `${b.ad_types.join(" / ")} · ${s.length} 天`),
      infoBtn(c, "逐日口径",
        "块内逐日 = 把这一归因窗口下每个对象的日线按日期相加。\n"
        + "日线只能从搜索词报表拿到，口径由「日粒度口径」参数选，"
        + "两种口径算出的环比变化率相同、只有水平值不同。\n"
        + "每天参与汇总的对象数不同（首日 "
        + (s[0].objects || 0) + " 个，末日 "
        + (s[s.length - 1].objects || 0) + " 个），"
        + "所以这条线看走势不看绝对值。"),
    ]),
    el("div", { class: "ads-tbwrap", html: rows }),
    el("div", { class: "ads-mv-foot" }, [
      el("span", {}, s[0].date), el("span", {}, s[s.length - 1].date),
    ]),
    el("div", { class: "ads-lg" }, [
      el("span", {}, "深色 花费"), el("span", {}, "浅色 广告销售额"),
    ]),
  ]);
}

function metricView(c, d) {
  const { el } = c;
  const a = d.aggregate;
  const tab = view.metricTab || "总览";
  const rail = el("div", { class: "ads-mvrail" },
    ["总览", "趋势"].map((t) => {
      const b = el("button", { class: "ads-mvtab" + (t === tab ? " ads-on" : ""),
                               type: "button" }, t);
      b.addEventListener("click", () => { view.metricTab = t; render(c); });
      return b;
    }));
  const blocks = (a.blocks || []).map((b) => (tab === "趋势"
    ? trendBlock(c, b) : metricBlock(c, b)));
  return el("section", { class: "ads-card ads-mvcard" }, [
    el("div", { class: "ads-mvleft" }, [
      el("div", { class: "ads-mvtitle" }, "指标视图"),
      rail,
    ]),
    el("div", { class: "ads-mvblks" }, blocks),
  ]);
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

/* 广告对象清单（照 2026-09-04 两张参考稿的表格构图）
 *
 * 从稿子上照抄的六样：
 *   1. 状态计数页签行（稿 A 的「全部 256 / 投放中 158 / 预算耗尽 12 …」）
 *   2. 两级列组表头（稿 B 的「对象信息 | 7 天归因 | 14 天归因 | 操作」）
 *   3. 状态用彩色圆点 + 文字，不是纯文字
 *   4. 选中行整行高亮
 *   5. 底部分页条：共 N 条 · 每页显示 ▾ · 页码 · 前往 __ 页
 *   6. 行尾 ⋯ 操作菜单
 *
 * 三处照不了、换成真实等价物的地方 —— 稿子的数据模型和这个包不一样：
 *   · **没有投放状态**。`dim_ad_object` 里没有 state 列，所以「投放中 / 已暂停 /
 *     已结束」这几个词造不出来。换成包里真有且自带计数的**数据状态**
 *     （覆盖完整窗口 20 / 覆盖不足 18 / 无日线 16 / 共享多子体 44 …）。
 *   · **第二组列不能是 14 天归因**。一个对象只属于一个归因窗口（SP 是 7 天、
 *     SB/SD 是 14 天），两组都填就是给它编一份不存在的另一口径数据。
 *     换成「较上期」——那是刚做出来的真环比，九个指标都有。
 *   · **预算是 Campaign 粒度**（`fact_budget.campaign_id`），表是广告组粒度，
 *     所以不做稿子里那一列「预算 $20.00/天」。
 *
 * 状态点的颜色不是我定的：该对象有没有命中「数据状态」类异常规则，
 * 从 `anomalies.rows` 读出来。命中就是 warn，没命中就中性灰。
 */

// 三组列。第一组是身份，第二组是本期指标，第三组是环比，最后是操作。
const L_INFO = [
  ["sel", "", 32], ["name", "对象名称", 224], ["ad_type", "类型", 52],
  ["attr", "归因", 58], ["state", "数据状态", 150],
];
const L_METRIC = [
  ["spend", "花费", 88], ["ad_sales", "广告销售额", 96],
  ["orders", "订单", 58], ["clicks", "点击", 66],
  ["ctr", "CTR", 56], ["cpc", "CPC", 58],
  ["cvr", "CVR", 56], ["acos", "ACoS", 60], ["roas", "ROAS", 52],
];
const L_ACT = [["act", "", 44]];
const NUMK = new Set(["spend", "ad_sales", "orders", "clicks", "ctr", "cpc",
                      "cvr", "acos", "roas"]);
const PAGE_SIZES = [20, 50, 100];

function cellVal(c, r, k) {
  const { fmt } = c;
  if (k === "spend" || k === "ad_sales") return usd(r[k], 0);
  if (k === "cpc") return usd(r[k], 2);
  if (k === "ctr") return fmt.pct(r[k], 2);
  if (k === "cvr" || k === "acos") return fmt.pct(r[k], 1);
  if (k === "roas") return r[k] == null ? "—" : Number(r[k]).toFixed(2);
  return fmt.int(r[k]);
}

/* 环比一格。比率类给百分点、量类给百分比，与指标视图同一口径。 */
function chgCell(c, r, k) {
  const { el } = c;
  if (!r.change_comparable) {
    return el("div", { class: "ads-ld ads-tnum ads-dl-na" }, "—");
  }
  const v = (r.change || {})[k];
  if (v === null || v === undefined) {
    return el("div", { class: "ads-ld ads-tnum ads-dl-na" }, "—");
  }
  const up = v > 0;
  const better = METRIC_BETTER[k];
  const tone = !better ? "" : ((up ? better === "up" : better === "down")
    ? "good" : "alert");
  const isRate = k === "ctr" || k === "cvr" || k === "acos";
  const base = r[k];
  const text = (isRate && base != null)
    ? (up ? "↑" : "↓") + Math.abs(base * v * 100).toFixed(2) + "pp"
    : (up ? "↑" : "↓") + Math.abs(v * 100).toFixed(1) + "%";
  return el("div", { class: "ads-ld ads-tnum" + (tone ? " ads-t-" + tone : "") },
    text);
}

function listCard(c, d, cmpBox) {
  const { el } = c;
  const st = view.list || (view.list = { picked: new Set(), tab: "",
                                         page: 1, size: 50, showChg: true });
  // 命中「数据状态」类异常的对象 —— 状态点标 warn 的依据，从数据读不自己定
  const flagged = new Set();
  ((d.anomalies || {}).rows || []).forEach((x) => {
    if ((x.anomalies || []).some((a) => a.class_label === "数据状态")) {
      flagged.add(x.ad_object_id);
    }
  });

  /* ① 状态计数页签。计数来自真实 state_labels 分布 */
  const cnt = {};
  d.rows.forEach((r) => (r.state_labels || []).forEach((s) => {
    cnt[s] = (cnt[s] || 0) + 1;
  }));
  const tabs = el("div", { class: "ads-ltabs" });
  const mkTab = (key, label, n) => {
    const b = el("button", { class: "ads-ltab" + (st.tab === key ? " ads-on" : ""),
                             type: "button" },
      [el("span", {}, label), el("i", {}, String(n))]);
    b.addEventListener("click", () => {
      st.tab = st.tab === key ? "" : key;
      st.page = 1;
      render(c);
    });
    return b;
  };
  tabs.appendChild(mkTab("", "全部", d.rows.length));
  (d.state_vocab || []).forEach((v) => {
    if (cnt[v.label]) tabs.appendChild(mkTab(v.label, v.label, cnt[v.label]));
  });

  /* 筛选 + 分页切片 */
  const all = st.tab
    ? d.rows.filter((r) => (r.state_labels || []).includes(st.tab))
    : d.rows;
  const pages = Math.max(1, Math.ceil(all.length / st.size));
  if (st.page > pages) st.page = pages;
  const rows = all.slice((st.page - 1) * st.size, st.page * st.size);

  /* ② 两级列组表头 */
  const cols = L_INFO.concat(L_METRIC,
    st.showChg ? L_METRIC.map(([k, l, w]) => ["chg_" + k, l, w]) : [], L_ACT);
  const w = (arr) => arr.reduce((n, x) => n + x[2], 0);
  const grp = el("div", { class: "ads-lrow ads-lgrp" }, [
    el("div", { class: "ads-ld ads-lgc", style: `width:${w(L_INFO)}px;flex:0 0 ${w(L_INFO)}px` },
      "对象信息"),
    el("div", { class: "ads-ld ads-lgc", style: `width:${w(L_METRIC)}px;flex:0 0 ${w(L_METRIC)}px` },
      "本期指标"),
  ]);
  if (st.showChg) {
    grp.appendChild(el("div", { class: "ads-ld ads-lgc",
      style: `width:${w(L_METRIC)}px;flex:0 0 ${w(L_METRIC)}px` },
      [el("span", {}, "较上期"),
       infoBtn(c, "较上期",
         "后半月对前半月，两侧各 15 天等长，中间那天不计入任何一侧。\n"
         + "要求前后两个半窗各自有点击样本，不够就整行给「—」"
         + "（本页共 " + d.rows.filter((r) => !r.change_comparable).length
         + " 行不可比）。\n"
         + "比率类指标给百分点，量类给百分比 —— ACoS 从 20% 到 25% 是"
         + "涨了 5 个点，不是涨了 25%。")]));
  }
  grp.appendChild(el("div", { class: "ads-ld ads-lgc",
    style: `width:${w(L_ACT)}px;flex:0 0 ${w(L_ACT)}px` }, "操作"));

  const head = el("div", { class: "ads-lrow ads-lhead" },
    cols.map(([k, lab, cw]) => el("div", {
      class: "ads-ld" + (NUMK.has(k) || k.startsWith("chg_") ? " ads-tnum" : ""),
      style: `width:${cw}px;flex:0 0 ${cw}px`,
    }, lab)));

  const table = el("div", { class: "ads-ltable" }, [grp, head]);

  rows.forEach((r) => {
    const on = st.picked.has(r.ad_object_id);
    const row = el("div", { class: "ads-lrow" + (on ? " ads-lsel" : "") });
    const cb = el("input", { type: "checkbox", class: "ads-selbox" });
    cb.checked = on;
    cb.addEventListener("click", (e) => {
      e.stopPropagation();
      if (cb.checked) st.picked.add(r.ad_object_id);
      else st.picked.delete(r.ad_object_id);
      row.classList.toggle("ads-lsel", cb.checked);
      refreshCompare(c, cmpBox, [...st.picked]);
    });

    cols.forEach(([k, , cw]) => {
      if (k.startsWith("chg_")) {
        const box = chgCell(c, r, k.slice(4));
        box.style.width = cw + "px";
        box.style.flex = `0 0 ${cw}px`;
        row.appendChild(box);
        return;
      }
      const box = el("div", {
        class: "ads-ld" + (NUMK.has(k) ? " ads-tnum" : ""),
        style: `width:${cw}px;flex:0 0 ${cw}px`,
      });
      if (k === "sel") box.appendChild(cb);
      else if (k === "name") {
        box.appendChild(el("b", {}, r.name || ""));
        box.appendChild(el("em", {}, (r.campaign || "").replace(/^002-/, "")));
      } else if (k === "ad_type") {
        box.appendChild(el("span", { class: "ads-tag" }, r.ad_type || "—"));
      } else if (k === "attr") {
        // 归因窗口：说明这一行的指标是哪个口径，替代稿子里那第二组列
        box.textContent = r.ad_type === "SP" ? "7 天" : "14 天";
      } else if (k === "state") {
        const bad = flagged.has(r.ad_object_id);
        const first = (r.state_labels || [])[0] || "—";
        box.appendChild(el("i", { class: "ads-sdot"
          + (bad ? " ads-sdot-warn" : "") }));
        box.appendChild(el("span", { class: "ads-stxt" }, first));
        if ((r.state_labels || []).length > 1) {
          const more = el("button", { class: "ads-ref", type: "button" },
            "+" + (r.state_labels.length - 1));
          more.addEventListener("click", (e) => {
            e.stopPropagation();
            popText(c, more, "数据状态", r.state_labels.join("\n"));
          });
          box.appendChild(more);
        }
      } else if (k === "act") {
        const m = el("button", { class: "ads-more", type: "button" }, "⋯");
        m.addEventListener("click", (e) => {
          e.stopPropagation();
          popText(c, m, r.name || "操作",
            "点这一行任意位置打开对象详情。\n"
            + "勾选左侧复选框加入横向对比（选两个以上出对比栏）。\n"
            + "所属 Campaign：" + (r.campaign || "—")
            + "\n投放目的：" + (r.purpose || "未识别")
            + "\n数据性质：" + (r.nature || "—"));
        });
        box.appendChild(m);
      } else {
        box.textContent = cellVal(c, r, k);
      }
      row.appendChild(box);
    });
    row.addEventListener("click", () => openDetail(c, r.ad_object_id));
    table.appendChild(row);
  });

  /* 工具条（照参考稿 A 表格上方那一排）：
     报告范围 · 搜索 · 粒度 · 列 · 批量 · 导出。
     **报告范围是只读的**：这个数据包只有 2026-07-01~07-31 一个静态窗口，
     摆一个能拖的日期选择器上去，拖了没反应才是真的不正式。 */
  const win = (d.scope || {}).window || ["2026-07-01", "2026-07-31"];
  const dateBtn = el("button", { class: "ads-tbtn ads-tbtn-date", type: "button" },
    [el("i", {}, "📅"), el("span", {}, `${win[0]} ~ ${win[1]}`)]);
  dateBtn.addEventListener("click", () => popText(c, dateBtn, "报告范围",
    `这个数据包是一次静态快照：报表窗口固定 ${win[0]} 至 ${win[1]}，`
    + "基准日 " + (c.asOf || "—") + "。\n"
    + "所以这里不给可拖的日期选择器 —— 拖了没有第二个窗口可切，"
    + "那种控件比没有更误导。\n"
    + "接上领星 API 之后这一格才会变成真的范围选择。"));

  const q = el("input", {
    class: "ads-tsearch", type: "search",
    placeholder: "搜索广告活动 / 组 / 投放对象",
    value: (c.filters.q || ""),
  });
  q.addEventListener("change", () => c.setFilters({ q: q.value.trim() }));
  q.addEventListener("keydown", (e) => {
    if (e.key === "Enter") c.setFilters({ q: q.value.trim() });
  });

  // 粒度：广告组 / 投放对象。这是真参数（ads.grain），换了整表重算
  const grainSel = el("select", { class: "ads-lsize" },
    [["AD_GROUP", "广告组"], ["TARGET", "投放对象"]].map(([v, lab]) => {
      const o = el("option", { value: v }, lab);
      if ((c.params["ads.grain"] || "AD_GROUP") === v) o.selected = true;
      return o;
    }));
  grainSel.addEventListener("change", () =>
    c.setParams({ "ads.grain": grainSel.value }));

  const bulk = el("button", { class: "ads-btn", type: "button" },
    st.picked.size ? `清空已选 ${st.picked.size}` : "批量操作");
  bulk.addEventListener("click", () => {
    st.picked.clear();
    refreshCompare(c, cmpBox, []);
    render(c);
  });
  const colBtn = el("button", { class: "ads-btn", type: "button" },
    st.showChg ? "隐藏较上期" : "显示较上期");
  colBtn.addEventListener("click", () => { st.showChg = !st.showChg; render(c); });

  /* ⑤ 底部分页条 */
  const pager = el("div", { class: "ads-lpager" });
  pager.appendChild(el("span", { class: "ads-mut" },
    `共 ${all.length} 条` + (st.tab ? `（已按「${st.tab}」筛选）` : "")));
  const right = el("div", { class: "ads-lpright" });
  const sizeSel = el("select", { class: "ads-lsize" },
    PAGE_SIZES.map((n) => {
      const o = el("option", { value: String(n) }, `每页 ${n}`);
      if (n === st.size) o.selected = true;
      return o;
    }));
  sizeSel.addEventListener("change", () => {
    st.size = Number(sizeSel.value) || 50;
    st.page = 1;
    render(c);
  });
  right.appendChild(sizeSel);
  const go = (n) => { st.page = Math.min(Math.max(1, n), pages); render(c); };
  const nav = (lab, to, off) => {
    const b = el("button", { class: "ads-pgb" + (off ? " ads-pgb-off" : ""),
                             type: "button" }, lab);
    if (!off) b.addEventListener("click", () => go(to));
    else b.disabled = true;
    return b;
  };
  right.appendChild(nav("‹", st.page - 1, st.page <= 1));
  for (let i = 1; i <= pages; i += 1) {
    const b = el("button", { class: "ads-pgb"
      + (i === st.page ? " ads-on" : ""), type: "button" }, String(i));
    b.addEventListener("click", () => go(i));
    right.appendChild(b);
  }
  right.appendChild(nav("›", st.page + 1, st.page >= pages));
  pager.appendChild(right);

  return el("section", { class: "ads-card" }, [
    el("div", { class: "ads-secthead" }, [
      el("h2", { class: "ads-h2" }, "广告对象清单"),
      el("span", { class: "ads-mut" }, `${d.total} 个${d.grain_label}`),
      infoBtn(c, "这张表的口径",
        "每行只有一个归因窗口的指标：SP 是 7 天归因、SB / SD 是 14 天归因，"
        + "所以「归因」那一列说明这一行的指标是哪个口径。\n"
        + "参考稿把 7 天与 14 天并排成两组列，这个数据包做不到 —— "
        + "一个对象只属于一个窗口，两组都填就是编一份不存在的数据。\n"
        + "状态那一列的圆点标黄，表示这个对象命中了「数据状态」类异常规则，"
        + "不是我另定的一套严重度。"),
    ]),
    tabs,
    el("div", { class: "ads-ltools" }, [
      dateBtn, q, grainSel,
      el("span", { class: "ads-tsp" }),
      bulk, colBtn,
      el("button", {
        class: "wb-export", type: "button",
        title: "导出成 Excel（.xlsx），可直接给其他部门下单用",
        onclick: (e) => downloadExport(e.currentTarget, "/api/ads/export"),
      }, "导出 Excel"),
    ]),
    el("div", { class: "ads-ltablewrap" }, [table]),
    pager,
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

/* 横条行。页面二 charts.js 里那个 barRows 是同一个形状，
   但那是页面二的模块文件，页面一直接 import 会把两页的依赖绑在一起 ——
   这里只用到最简的一档，就地写一份三十行的，不跨页 import。 */
function barRowsHTML(rows) {
  const esc = (v) => String(v === null || v === undefined ? "" : v)
    .replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;",
                                    '"': "&quot;", "'": "&#39;" }[ch]));
  return `<div class="ads-brs">${(rows || []).map((r) => {
    const w = r.share === null || r.share === undefined ? null
      : Math.max(0, Math.min(1, Number(r.share))) * 100;
    return `<div class="ads-br">
      <span class="ads-br-l">${esc(r.label)}${
      r.sub ? `<em>${esc(r.sub)}</em>` : ""}</span>
      <span class="ads-br-t">${w === null ? ""
      : `<span class="ads-br-f" style="width:${w.toFixed(2)}%"></span>`}</span>
      <span class="ads-br-v num">${esc(r.text)}</span>
      ${r.badge ? `<span class="ads-br-b">${esc(r.badge)}</span>` : ""}
    </div>`;
  }).join("")}</div>`;
}

/* 抽屉里的趋势图。花费柱 + 广告销售额线 + ACoS 线，比率独立轴从 0 起。
   字体栈与字号镜像 tokens.css —— canvas 里的字不继承 CSS（门禁 G24）。 */
const DR_FONT = '-apple-system, "SF Pro Text", BlinkMacSystemFont, '
  + '"IBM Plex Sans", Inter, "PingFang SC", "Microsoft YaHei", sans-serif';
const DR_FS = { axis: 11, tip: 13 };
let drEcharts = null;
let drInst = null;

function drLoadECharts() {
  if (typeof window !== "undefined" && window.echarts) {
    return Promise.resolve(window.echarts);
  }
  if (drEcharts) return drEcharts;
  drEcharts = new Promise((resolve, reject) => {
    const tag = document.createElement("script");
    tag.src = "/assets/echarts.min.js";
    tag.onload = () => resolve(window.echarts);
    tag.onerror = () => reject(new Error("ECharts 加载失败"));
    document.head.appendChild(tag);
  });
  return drEcharts;
}

async function mountDrawerChart(box, s) {
  let ec;
  try {
    ec = await drLoadECharts();
  } catch (err) {
    box.textContent = "趋势图加载失败：" + String(err);
    return;
  }
  if (!ec || !box.isConnected) return;
  if (drInst) { drInst.dispose(); drInst = null; }
  drInst = ec.init(box, null, { renderer: "canvas" });
  drInst.setOption({
    textStyle: { fontFamily: DR_FONT },
    grid: { left: 54, right: 54, top: 14, bottom: 24 },
    tooltip: { trigger: "axis",
               textStyle: { fontFamily: DR_FONT, fontSize: DR_FS.tip } },
    xAxis: { type: "category", data: s.map((x) => x.date),
             axisLabel: { fontFamily: DR_FONT, fontSize: DR_FS.axis },
             axisTick: { alignWithLabel: true } },
    // 金额与比率分轴：比率跟金额共轴会被压成贴零轴的一条直线（要则第六节）
    yAxis: [
      { type: "value", min: 0,
        axisLabel: { fontFamily: DR_FONT, fontSize: DR_FS.axis } },
      { type: "value", name: "ACoS %", min: 0,
        nameTextStyle: { fontFamily: DR_FONT, fontSize: DR_FS.axis },
        axisLabel: { fontFamily: DR_FONT, fontSize: DR_FS.axis },
        splitLine: { show: false } },
    ],
    series: [
      { name: "广告花费", type: "bar", barMaxWidth: 13,
        data: s.map((x) => x.spend), itemStyle: { color: "#111113" } },
      { name: "广告销售额", type: "line", symbol: "circle", symbolSize: 3,
        data: s.map((x) => x.ad_sales),
        lineStyle: { width: 1.6, color: "#3a7d43" },
        itemStyle: { color: "#3a7d43" } },
      { name: "ACoS", type: "line", yAxisIndex: 1, symbol: "circle",
        symbolSize: 3, connectNulls: false,
        data: s.map((x) => x.acos === null || x.acos === undefined
          ? null : Number((x.acos * 100).toFixed(2))),
        lineStyle: { width: 1.6, color: "#2563eb" },
        itemStyle: { color: "#2563eb" } },
    ],
  });
}

/* 对象详情抽屉（照 2026-09-04 参考稿 A 右侧那个抽屉）
 *
 * 稿子的结构，从上到下：
 *   标题 + ×
 *   元信息一行五格：广告活动 / 广告类型 / 广告目的 / 归因天数 / 数据状态
 *   数据趋势：右上角 7天/14天/30天 切换，三个图例带当期值，柱+双线三轴
 *   核心指标：展示/点击/CTR/CPC/订单/CVR/ROAS，每格下面挂环比
 *   异常规则匹配：规则/异常指标/当前值/对比范围/偏差/查看证据
 *   异常解读（灰框）+ 去优化建议（蓝按钮）
 *
 * 原来这里是一个 dl 键值堆 —— 和页面二重构前一样的病：想写一句话就得先起
 * 一个三五字标签，于是所有信息一个重量。
 *
 * 最后一节我不照抄：**页面一的红线是只回答「数字长什么样」，不出诊断和建议**
 * （page1.py 文件头）。所以「异常解读」那段话不写、「去优化建议」不做成一个
 * 假按钮，换成一条真链接：跳到页面二那个子 ASIN 的广告决策 —— 判断在那边，
 * 由 Agent 出。编一段解读放在这里，等于把页面一的红线自己踩了。
 */

const DR_RANGES = [["7", "近 7 天"], ["14", "近 14 天"], ["0", "全窗口"]];

/* 趋势图。花费画柱，广告销售额与 ACoS 画线，比率独立轴从 0 起（要则第六节）。 */
function drawerTrend(c, d, box) {
  const { el } = c;
  /* 对象级日线是 fact_ad_daily 的原始行：日期字段叫 stat_date（不是 date），
     而且**没有 acos 列** —— 块级聚合那个序列才有。第一版直接拿 x.date 与
     x.acos 用，结果 X 轴整排 undefined、ACoS 线一个点都没画。
     所以在入口归一成 {date, spend, ad_sales, acos}，acos 由当天两个量算。 */
  const all = (d.daily || []).map((x) => {
    const sp = x.spend || 0;
    const sa = x.ad_sales || 0;
    return {
      date: x.stat_date || x.date,
      spend: sp, ad_sales: sa,
      clicks: x.clicks || 0, orders: x.orders || 0,
      impressions: x.impressions || 0,
      acos: sa ? sp / sa : null,
    };
  }).filter((x) => x.date);
  if (!all.length) {
    box.appendChild(el("div", { class: "ads-hint" },
      "这个对象没有逐日序列。日线只能从搜索词报表拿到，"
      + "只覆盖被报表命中的对象。"));
    return;
  }
  const st = view.drawer || (view.drawer = { range: "14" });
  const n = Number(st.range) || 0;
  const s = n ? all.slice(-n) : all;
  const sum = (k) => s.reduce((t, x) => t + (x[k] || 0), 0);
  const spend = sum("spend");
  const sales = sum("ad_sales");
  const acos = sales ? spend / sales : null;

  const tabs = el("div", { class: "ads-drtabs" }, DR_RANGES.map(([v, lab]) => {
    const b = el("button", { class: "ads-drtab" + (st.range === v ? " ads-on" : ""),
                             type: "button" }, lab);
    b.addEventListener("click", () => {
      st.range = v;
      box.textContent = "";
      drawerTrend(c, d, box);
    });
    return b;
  }));

  const legend = el("div", { class: "ads-drleg" }, [
    el("div", {}, [el("i", { class: "ads-lg-bar" }),
      el("span", {}, "广告花费"), el("b", {}, usd(spend, 2))]),
    el("div", {}, [el("i", { class: "ads-lg-line1" }),
      el("span", {}, "广告销售额"), el("b", {}, usd(sales, 2))]),
    el("div", {}, [el("i", { class: "ads-lg-line2" }),
      el("span", {}, "ACoS"), el("b", {}, c.fmt.pct(acos, 2))]),
  ]);

  box.appendChild(el("div", { class: "ads-drhead" }, [
    el("h3", { class: "ads-h3" }, "数据趋势"), tabs,
  ]));
  box.appendChild(legend);
  const mount = el("div", { class: "ads-drchart" });
  box.appendChild(mount);
  box.appendChild(el("div", { class: "ads-mut" },
    `${s[0].date} — ${s[s.length - 1].date}`
    + `　口径「放大到月度总额」，与月度权威口径对齐`));
  mountDrawerChart(mount, s);
}

/* 核心指标：七格 + 每格下面挂环比。稿子那一格写「较前14天」，
   这里写真实基准「较前半窗」—— 因为环比的基准是后半月对前半月。 */
function drawerCore(c, d) {
  const { el } = c;
  const h = d.history || {};
  const SPEC = [
    ["impressions", "展示", "int"], ["clicks", "点击", "int"],
    ["ctr", "CTR", "pct2"], ["cpc", "CPC", "usd2"],
    ["orders", "订单", "int"], ["cvr", "CVR", "pct1"],
    ["acos", "ACoS", "pct1"], ["roas", "ROAS", "x2"],
  ];
  const src = { ...d.metrics, ...d.ratios };
  const cells = SPEC.map(([k, lab, kind]) => {
    const v = src[k];
    const rate = h.comparable ? h[k + "_change_rate"] : null;
    return el("div", { class: "ads-drc" }, [
      el("div", { class: "ads-drc-l" }, lab),
      el("div", { class: "ads-drc-v" }, fmtMetric(c, v, kind)),
      deltaCell(c, k, rate, v,
        (k === "ctr" || k === "cvr" || k === "acos") ? "rate" : "vol"),
    ]);
  });
  return el("div", { class: "ads-drsec" }, [
    el("div", { class: "ads-drhead" }, [
      el("h3", { class: "ads-h3" }, "核心指标"),
      el("span", { class: "ads-mut" }, h.comparable
        ? `较前半窗 · 前 ${h.days_prev} 天对后 ${h.days_curr} 天`
        : "无可比前半窗：" + (h.why || "样本不足")),
      infoBtn(c, "核心指标与环比",
        "指标取月度权威口径，与客户报表逐字段对得上。\n"
        + "环比基准：后半月对前半月，两侧各 15 天等长，"
        + "中间那天不计入任何一侧。\n"
        + "比率类给百分点，量类给百分比。"),
    ]),
    el("div", { class: "ads-drcs" }, cells),
  ]);
}

/* 异常规则匹配。判据、当前值、对比范围全部来自 detect_anomalies()，
   页面不另写一套判断。 */
function drawerAnomalies(c, d) {
  const { el, fmt } = c;
  const rows = d.anomalies || [];
  const head = ["规则", "类别", "当前值", "判据", "对比范围"];
  const t = el("div", { class: "ads-drtable" }, [
    el("div", { class: "ads-drtr ads-drth" },
      head.map((x) => el("div", {}, x))),
  ]);
  const fmtObs = (v) => {
    if (v === null || v === undefined) return "—";
    return Math.abs(v) < 3 ? (v * 100).toFixed(1) + "%" : Number(v).toFixed(2);
  };
  rows.forEach((a) => {
    t.appendChild(el("div", { class: "ads-drtr" }, [
      el("div", {}, a.rule_name || ""),
      el("div", {}, [el("span", { class: "ads-tag" }, a.class_label || "")]),
      el("div", { class: "ads-tnum ads-t-warn" }, fmtObs(a.observed)),
      el("div", { class: "ads-tnum" }, a.threshold === null
        || a.threshold === undefined ? "—" : fmtObs(a.threshold)),
      el("div", { class: "ads-mut" }, a.basis || ""),
    ]));
  });
  return el("div", { class: "ads-drsec" }, [
    el("div", { class: "ads-drhead" }, [
      el("h3", { class: "ads-h3" }, "异常规则匹配"),
      el("span", { class: "ads-mut" }, rows.length
        ? `命中 ${rows.length} 条` : "本期未命中任何规则"),
    ]),
    rows.length ? t : el("div", { class: "ads-hint" },
      "在当前阈值下这个对象没有命中异常规则。"),
  ]);
}

/* 广告位分布。稿子没有这一节，但这是包里真有的东西，
   而且「顶部广告位比例」正是页面二那些建议要动的东西。 */
function drawerPlacements(c, d) {
  const { el, fmt } = c;
  const rows = (d.placements || []).slice()
    .sort((a, b) => (b.spend || 0) - (a.spend || 0));
  if (!rows.length) return null;
  const max = Math.max(...rows.map((r) => r.spend || 0), 1);
  const bars = rows.map((r) => ({
    label: r.placement || "—",
    sub: r.attribution_days ? r.attribution_days + " 天归因" : "",
    share: (r.spend || 0) / max,
    text: usd(r.spend, 0),
    badge: `ACoS ${fmt.pct(r.acos, 1)} · 点击 ${fmt.int(r.clicks)}`,
  }));
  return el("div", { class: "ads-drsec" }, [
    el("div", { class: "ads-drhead" }, [
      el("h3", { class: "ads-h3" }, "广告位分布"),
      el("span", { class: "ads-mut" }, `${rows.length} 个广告位 · Campaign 级`),
      infoBtn(c, "广告位口径",
        "广告位数据是 Campaign 粒度，不是这个广告组的。\n"
        + "同一个 Campaign 下的广告组共享这份分布，"
        + "所以它说明的是这个 Campaign 的投放位置结构。"),
    ]),
    el("div", { html: barRowsHTML(bars) }),
  ]);
}

async function openDetail(c, oid) {
  const { el, fmt } = c;
  let d;
  try {
    d = await c.api("object/" + encodeURIComponent(oid));
  } catch (err) {
    c.drawer.open(oid, el("div", { "data-module": "ads", class: "ads-drawer" },
      [el("div", { class: "ads-hint" }, String(err))]));
    return;
  }
  // 外壳的抽屉挂在 body 下，不在 [data-module="ads"] 里，
  // 模块 CSS 一条都不会生效。自己给渲染进去的容器补上作用域标记 ——
  // 这是我的内容，不算改外壳。
  const body = el("div", { "data-module": "ads", class: "ads-drawer" });
  if (d.condition !== "正常") {
    body.appendChild(el("div", { class: "ads-hint" }, d.message || "读取失败"));
    c.drawer.open(oid, body);
    return;
  }

  const purpose = (d.labels || [])
    .filter((x) => x.label_type === "AD_PURPOSE")
    .map((x) => x.label_value)[0] || "未识别";
  const bad = (d.anomalies || []).length;

  /* 元信息一行。稿子五格，这里六格 —— 多一格「数据性质」，
     因为这个包里有构造与派生数据，不标出来看的人会当成全是实测。 */
  body.appendChild(el("div", { class: "ads-drmeta" },
    [["广告活动", d.campaign || "—"],
     ["广告类型", (d.ad_type || "—") + " · " + (d.level === "TARGET"
       ? "投放对象" : d.level === "AD_GROUP" ? "广告组" : "Campaign")],
     ["投放目的", purpose],
     ["归因天数", d.attribution_days ? d.attribution_days + " 天" : "未标注"],
     ["数据性质", d.nature || "—"],
     ["数据状态", (d.state_labels || []).join(" · ") || "—"]]
      .map(([k, v]) => el("div", { class: "ads-drm" }, [
        el("div", { class: "ads-drm-l" }, k),
        el("div", { class: "ads-drm-v" }, v),
      ]))));

  if (bad) {
    body.appendChild(el("div", { class: "ads-drflag" }, [
      el("i", { class: "ads-sdot ads-sdot-warn" }),
      el("span", {}, `本期命中 ${bad} 条异常规则`),
    ]));
  }

  const trend = el("div", { class: "ads-drsec" });
  body.appendChild(trend);
  drawerTrend(c, d, trend);
  body.appendChild(drawerCore(c, d));
  body.appendChild(drawerAnomalies(c, d));
  const pl = drawerPlacements(c, d);
  if (pl) body.appendChild(pl);

  /* 稿子最后是「异常解读 + 去优化建议」。**这一页不出诊断和建议**
     （page1.py 的红线），所以不编那段解读，改成一条真链接：
     判断在页面二，由 Agent 出。 */
  const goBtn = el("button", { class: "ads-loadbtn", type: "button" },
    "去看这个对象的广告决策");
  goBtn.addEventListener("click", () => {
    c.drawer.close();
    c.open(null, "ads-decision");
  });
  body.appendChild(el("div", { class: "ads-drfoot" }, [
    el("div", { class: "ads-drfoot-t" }, [
      el("b", {}, "这一页只回答数字长什么样"),
      el("span", {}, "异常解读、调整方向与调整幅度不在这一页出 —— "
        + "那是判断，由「单一子 ASIN 广告决策」那页的 Agent 产出，"
        + "并且要经人审批才执行。"),
    ]),
    goBtn,
  ]));

  c.drawer.open(d.name || oid, body);
}

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

/* ------------------------------------------------------------------ 页面二
 *
 * 2026-09-04 重构：整页搬到 ./ads/page2.js。
 * 这里只留三件事 —— 取数、把回调接回来、调 renderPage2。
 * 板块的形状与顺序都在 page2.js，施工单是
 * 04-广告分析模块/01-方案与数据需求/07-页面二屏幕决策设计.md。
 */
async function renderDecision(c) {
  const body = host.body;

  if (!view.asin) {
    body.textContent = "";
    body.appendChild(c.placeholder("空结果", "没有可判断的子 ASIN"));
    return;
  }
  if (!view.ctx) {
    try {
      view.ctx = await c.api("context", { child_asin: view.asin });
    } catch (err) {
      body.textContent = "";
      body.appendChild(c.placeholder("失败", String(err)));
      return;
    }
  }
  // Agent 不由浏览器触发（外壳拿不到请求体），Runner 是本地脚本，
  // 所以读 sidecar 是纯读操作，进页面就该读 —— 判断层与建议层要靠它，
  // 等点按钮才读的话客户滚下去看到的是四个空板块（重构前就是这样）。
  if (view.run === null) {
    try {
      view.run = await c.api("run", { child_asin: view.asin });
    } catch (err) {
      view.run = { condition: "失败", message: String(err), points: {},
                   stages: [] };
    }
  }

  renderPage2(c, body, view.ctx, view.run,
    { decided: view.decided, demo: view.demo,
      decidedDemo: view.decidedDemo, picked: view.picked }, {
    async onVersion(decisionId) {
      view.ctx = await c.api("context",
        { child_asin: view.asin, decision_id: decisionId });
      view.run = null;
      view.decided = {};
      view.picked = new Set();
      render(c);
    },
    async onDecide(p, act) {
      try {
        const d = await c.api("decide", {
          child_asin: view.asin, recommendation_id: p.recommendation_id,
          decision: act,
        });
        if (d.condition !== "正常") return;
        view.decided[p.recommendation_id] = d;
        view.picked.delete(p.recommendation_id);
        render(c);
      } catch (err) { /* 外壳已提示，不再重复 */ }
    },
    onUndo(p) {
      delete view.decided[p.recommendation_id];
      render(c);
    },
    /* 勾选与批量拍板。JACK 2026-09-04 要的就是这个：一条条点会点一上午。 */
    onPick(id, on) {
      if (on) view.picked.add(id);
      else view.picked.delete(id);
      render(c);
    },
    onPickAll(ids, on) {
      ids.forEach((id) => (on ? view.picked.add(id) : view.picked.delete(id)));
      render(c);
    },
    /* 批量走的是同一个单条 decide 接口，一条一条落 ——
       后端没有批量路由，前端假装一次提交只会把失败藏起来。
       所以逐条落、失败的留在待决定里，最后重绘一次。 */
    async onDecideBulk(act, label) {
      const ids = [...view.picked];
      const tpl = new Set(((view.demo || {}).items || [])
        .map((x) => x.recommendation_id));
      for (const id of ids) {
        if (tpl.has(id)) {
          // 示例卡只走本地态：真 decide 路由校验 B4 的 id，示例 id 会 404
          view.decidedDemo[id] = label;
          view.picked.delete(id);
          continue;
        }
        try {
          const d = await c.api("decide", {
            child_asin: view.asin, recommendation_id: id, decision: act,
          });
          if (d.condition !== "正常") continue;   // 失败的留在勾选里
          view.decided[id] = d;
          view.picked.delete(id);
        } catch (err) { /* 外壳已提示；这一条留在待决定 */ }
      }
      render(c);
    },
    // 示例调整方案。只有点了按钮才发这个请求。
    async onLoadDemo() {
      try {
        view.demo = await c.api("demo-script", { child_asin: view.asin });
      } catch (err) {
        view.demo = { available: false, message: String(err) };
      }
      render(c);
    },
    onHideDemo() {
      view.demo = null;
      view.decidedDemo = {};
      view.picked = new Set();   // 示例卡撤了，勾在它们上面的选择也没了
      render(c);
    },
    // 脚本卡的审批只走本地态：decide 路由校验真 B4 的 id，
    // 拿脚本 id 去请求只会 404。演示要的是点下去有反应。
    onDecideDemo(p, label) {
      view.decidedDemo[p.recommendation_id] = label;
      view.picked.delete(p.recommendation_id);
      render(c);
    },
    onUndoDemo(p) {
      delete view.decidedDemo[p.recommendation_id];
      render(c);
    },
  });
}
