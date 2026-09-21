/* 页面一 · 关键词动态与机会总览
 *
 * 骨架（09-页面承载体设计.md 第一层）：来源 → 结论 → 证据 → 追溯。
 *
 * 重构前的两处结构性问题：
 *   1. 「五问五答」是五行「标签 + 2~3 个小数字 + 一整段答句」，五段答句总长
 *      两百多字铺在第一屏，视觉重量全平。现在改成五条**结论行**：
 *      每行一个短名 + 一个关键数字 + 一句单行结论，完整答句与全部数字进 ⓘ。
 *   2. 「数据范围与数据状态」排在第二块，占一整屏讲词库有多少个词 ——
 *      那是**上下文不是结论**，挡在读者和真正的结论之间。移到页尾折叠。
 */

import {
  conclusionBand, deltaCell, evidenceGroups, foldBlock, infoDot, magnitudeCell,
  metricRow, num, popBody, section, shiftTrack, sourceCell, stackBar, table,
  toneOfType, txt,
} from "./parts.js";
import {
  groupChangeChart, rankShiftScatter, trafficSpark,
} from "./charts.js";

const pctSign = (v) => (v == null ? null : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`);

export function renderOverview(ctx, root, d) {
  const el = ctx.el;
  const hosts = { spark: el("div"), group: el("div"), shift: el("div") };
  root.replaceChildren(
    conclusionSection(ctx, d, hosts.spark),
    groupSection(ctx, d, hosts.group),
    coreSection(ctx, d, hosts.shift),
    prioritySection(ctx, d),
    scopeFold(ctx, d),
  );
  // 图在标记落地后再挂 —— ECharts 需要一个已经有尺寸的活元素。
  trafficSpark(hosts.spark, d.reports);
  groupChangeChart(hosts.group, d.group_changes.groups);
  rankShiftScatter(hosts.shift, d.core_changes.recent);
}

/* ---------------------------------------------- ②段：今天该看什么 */

function conclusionSection(ctx, d, sparkHost) {
  const el = ctx.el;
  const f = ctx.fmt;
  const r = (d.reports || [])[0];
  if (!r) return ctx.placeholder("空结果", "本期没有日报", "空结果");
  const cc = d.core_changes;
  const gt = d.group_changes.totals;
  const delta = r.traffic_proxy_delta;

  /* 五条结论行。name 是短名（三到五字），state 是这一问的关键数字，
     say 是 Agent 的答句 —— 单行，写不下就截断，完整句在 ⓘ 里。
     这五行的顺序是固定的：结果 → 变化 → 覆盖 → 新信号 → 下一步。 */
  const rows = [
    {
      name: "流量获取", tone: delta == null ? "" : delta >= 0 ? "good" : "alert",
      state: pctSign(delta) || "无可比", say: r.q1_traffic_result,
      pop: {
        title: "流量获取结果",
        rows: [
          ["当期值", f.int(r.traffic_proxy_value)],
          ["代理指标", r.traffic_proxy_metric],
          ["比较口径", r.compare_period],
          ["基期日", r.compare_base_date],
          ["基期值", r.compare_base_value == null ? null : f.int(r.compare_base_value)],
        ],
        paras: [r.q1_traffic_result, r.compare_note],
      },
    },
    {
      name: "主要变化", tone: gt.down > gt.up ? "warn" : "",
      state: `${gt.up} 涨 / ${gt.down} 跌`, say: r.q2_main_movers,
      pop: {
        title: "主要增长与下降",
        rows: [
          ["上涨词组", f.int(gt.up)], ["下滑词组", f.int(gt.down)],
          ["竞争加剧", f.int(gt.competition)], ["口径不清", f.int(gt.unclear)],
          ["连续 / 单期", `${gt.continuous} / ${gt.single_period}`],
        ],
        paras: [r.q2_main_movers],
      },
    },
    {
      name: "核心词覆盖", tone: cc.lost > cc.gained ? "alert" : "",
      state: `新增 ${cc.gained} / 丢失 ${cc.lost}`, say: r.q3_core_coverage_change,
      pop: {
        title: "核心词覆盖与位置",
        rows: [
          ["窗口内新增覆盖", f.int(cc.gained)],
          ["窗口内丢失覆盖", f.int(cc.lost)],
          ["窗口内涉及核心词", f.int(cc.core_events)],
        ],
        /* 这三个数是**整个观察窗口**的计数，而答句讲的是**当日**。两边都对：
           _gained/_lost 的 to_date 散落在 90/109 个不同日期，基准日那天确实一条都没有；
           而 organic_up/down 那 288 条汇总事件按设计 to_date 全是末日。
           所以口径写在标签上，不改数字 —— 改数字会造出假数据。 */
        paras: [
          r.q3_core_coverage_change,
          "上面三个数是整个观察窗口的累计计数，答句里的「当日」是基准日单日口径。"
          + "两者都对，但不要直接相减。",
        ],
      },
    },
    {
      name: "新出现的信号", tone: cc.significant ? "warn" : "",
      state: `${f.int(cc.significant)} 条显著`, say: r.q4_new_signals,
      pop: {
        title: "新出现的信号",
        rows: [
          ["覆盖或位置变化", f.int(cc.all_events)],
          [`变动超过 ${cc.rank_shift_threshold} 名`, f.int(cc.significant)],
          ["涉及子体", f.int(cc.children_touched)],
        ],
        paras: [r.q4_new_signals],
      },
    },
    {
      name: "下一步先看", state: `${f.int(d.priority.total)} 项待处理`,
      say: r.q5_priority_next,
      pop: {
        title: "最值得继续看",
        rows: [
          ["待处理事项", f.int(d.priority.total)],
          ["取样子体", f.int(cc.sampled_children)],
          ["排序依据", "需求规模 · 变化紧迫 · 主推加权 · 证据完整度"],
        ],
        paras: [r.q5_priority_next, "本模块不出加词、否词、出价与预算动作。"],
      },
    },
  ];

  return conclusionBand(ctx, {
    cells: [
      {
        // traffic_proxy_metric 本身已含「（代理指标）」，不要再拼一次
        label: r.traffic_proxy_metric,
        value: r.traffic_proxy_value,
        sub: delta == null
          ? `${r.compare_period}　窗口内无可比基期`
          : `${r.compare_period} ${pctSign(delta)}　基期 ${r.compare_base_date}`,
        subTone: delta == null ? null : delta >= 0 ? "good" : "alert",
        lead: true,
      },
      {
        label: "本期待处理事项",
        value: d.priority.total,
        sub: `${d.priority.type_counts.length} 类证据`,
      },
      {
        label: "核心词变化（个）",
        value: cc.core_events,
        sub: `新增 ${cc.gained} · 丢失 ${cc.lost}`,
        subTone: cc.lost > cc.gained ? "alert" : null,
      },
      {
        label: "发生变化的词组（组）",
        value: gt.groups_moved,
        sub: `上涨 ${gt.up} · 下滑 ${gt.down}`,
        subTone: gt.down > gt.up ? "warn" : null,
      },
      {
        label: `流量趋势（近 ${d.reports.length} 天）`,
        body: sparkHost,
      },
      sourceCell(ctx, d),
    ],
    verdicts: rows.map((x) => el("div", { class: "kw-vd-row", "data-tone": x.tone || "" }, [
      el("i", { class: "kw-vd-dot" }),
      el("span", { class: "kw-vd-name", text: x.name }),
      el("span", { class: "kw-vd-state", text: x.state }),
      el("span", { class: "kw-vd-say", text: x.say || "" }),
      infoDot(ctx, () => popBody(ctx, x.pop)),
    ])),
  });
}

/* -------------------------------------- ③段：市场需求与词组变化 */

function groupSection(ctx, d, chartHost) {
  const f = ctx.fmt;
  const g = d.group_changes;
  const t = g.totals;
  // 尾部搜索量极小的词组（个位数到 0）铺出来只是拉长表格，折进一行计数。
  const shown = g.groups.filter((x) => x.search_moved >= 1000);
  const tail = g.groups.length - shown.length;
  const max = Math.max(1, ...shown.map((x) => x.search_moved));
  const concentrated = g.top3_share >= 0.6;

  const cols = [
    { label: "需求词组", cell: txt(ctx, (r) => r.group_name, "kw-strong") },
    { label: "维度", cell: txt(ctx, (r) => r.demand_dimension) },
    { label: "涉及词", num: true, cell: num(ctx, (r) => r.term_count) },
    { label: "净向", num: true, cell: (r) => deltaCell(ctx, { value: r.net }) },
    // 图只画上涨/下滑两个方向，竞争加剧没有方向语义，所以由这一列承担。
    { label: "竞争加剧", num: true, cell: (r) => ctx.el("td", {
      class: "kw-num" + (r.competition ? " kw-warn-cell" : " kw-dim"),
      "data-sort": r.competition || 0,
      text: r.competition ? ctx.fmt.int(r.competition) : ctx.fmt.dash,
    }) },
    { label: "连续 / 单期", cell: txt(ctx, (r) => `${r.continuous} / ${r.single_period}`,
      "kw-num") },
    { label: "月搜索量变动", num: true,
      cell: (r) => magnitudeCell(ctx, { value: r.search_moved,
        ratio: r.search_moved / max, kind: "vol" }) },
  ];

  return section(ctx, {
    title: "市场需求与词组变化",
    metrics: [
      ["有变化的词组", f.int(t.groups_moved)],
      ["上涨 / 下滑", `${t.up} / ${t.down}`, t.down > t.up ? "alert" : "good"],
      ["竞争加剧", f.int(t.competition), "warn"],
      ["前三词组占变动", f.pct(g.top3_share, 0), concentrated ? "warn" : null],
      ["集中度", concentrated ? "集中在少数需求" : "散在多个需求"],
    ],
    info: () => popBody(ctx, {
      title: "这一块的口径",
      rows: [
        ["分权", g.dedup_applied ? "一词多组按 1/组数 分权" : "未按权分摊"],
        ["集中度判据", "前三个词组占全部搜索量变动 ≥60% 算集中"],
      ],
      paras: [
        "图按「涉及词数」取前 12 个词组：上涨向右、下滑向左，同一条基线，"
        + "竞争加剧另画一条细柱。表里不再重复上涨/下滑/竞争三列 —— 那是图的职责。",
        tail > 0 ? `另有 ${tail} 个词组本期搜索量变动不足 1,000，未列出。` : null,
      ],
    }),
    chart: chartHost,
    table: table(ctx, { cols, rows: shown, sortable: [2, 3, 4, 6] }),
  });
}

/* ---------------------------- ③段：自有核心词覆盖与位置变化 */

function coreSection(ctx, d, chartHost) {
  const f = ctx.fmt;
  const c = d.core_changes;
  const cap = Math.max(20, ...c.recent.flatMap((e) => [e.from_rank || 0, e.to_rank || 0]));

  const cols = [
    { label: "子 ASIN", cell: txt(ctx, (r) => r.child_asin, "kw-strong") },
    { label: "关键词", cell: txt(ctx, (r) => r.keyword) },
    { label: "变化", cell: txt(ctx, (r) => r.event_type_label) },
    { label: "位次变化（左＝第 1 位）", cell: (r) => ctx.el("td", {
      class: "kw-shiftcell",
      "data-sort": (r.to_rank || 0) - (r.from_rank || 0),
    }, [shiftTrack(ctx, { from: r.from_rank, to: r.to_rank, cap })
      || ctx.el("i", { class: "kw-na-fig" })]) },
    { label: "主推关系", cell: txt(ctx, (r) => r.push_role_label) },
    { label: "日期", cell: txt(ctx, (r) => r.to_date, "kw-num") },
  ];
  const rows = c.recent.map((e) => ({ ...e, __open: e.child_asin }));
  const worst = c.top_declines[0];

  return section(ctx, {
    title: "自有核心词覆盖与位置变化",
    metrics: [
      ["核心词变化", f.int(c.core_events)],
      [`变动超过 ${c.rank_shift_threshold} 名`, f.int(c.significant), "warn"],
      ["新增 / 丢失覆盖", `${c.gained} / ${c.lost}`, c.lost > c.gained ? "alert" : "good"],
      ["涉及子体", f.int(c.children_touched)],
      worst ? ["跌幅最大", `${worst.child_asin}　第 ${worst.from_rank}→${worst.to_rank} 位`,
        "alert"] : null,
    ],
    info: () => popBody(ctx, {
      title: "这一块只陈述事实",
      rows: [
        ["下表取样", `${c.sampled_children} 个子体 · 每体最多 2 条`],
        ["全部变化", f.int(c.all_events)],
      ],
      paras: [
        "散点图的 x 是变化前位次、y 是变化后位次，两轴同尺度。点落在虚线上＝没变，"
        + "落在虚线下方＝位次变差。偏离虚线的距离就是变动幅度。",
        "位置涨跌不等于广告策略对错 —— 本模块不给广告动作，只给该先看谁。",
        "按子体去重取样：organic_up/down 的汇总事件 to_date 全是末日，直接按日期倒排"
        + "会让贡献最多关系对的那个子体霸占整屏，看起来像只有它在动。",
      ],
    }),
    chart: chartHost,
    extra: ctx.el("div", { class: "kw-stackrow" }, [
      stackBar(ctx, c.by_type.map((x) => ({
        label: x.name, n: x.n,
        kind: /下降|丢失|跌出|失败/.test(x.name) ? "alert"
          : /上涨|新增/.test(x.name) ? "good" : "calm",
      })), { label: "变化构成" }),
      stackBar(ctx, c.by_push_role.map((x) => ({
        label: x.name, n: x.n, kind: x.name === "主推" ? "vol" : "mut",
      })), { label: "主推关系构成" }),
    ]),
    table: table(ctx, {
      cols, rows, sortable: [3, 5],
      onRowOpen: (id) => ctx.open(id, "kw-asin"),
    }),
  });
}

/* ------------------------- ③段：关键词机会、缺口与风险（证据组） */

function prioritySection(ctx, d) {
  const f = ctx.fmt;
  const p = d.priority;
  const vmax = Math.max(1, ...p.items.map((e) => e.monthly_search_volume || 0));

  /* 这一页的证据跨子体，排序按需求规模加权，所以 S1 判据图形画**搜索量量级** ——
     它就是排序的主要依据，画出来读者才看得出为什么这条排在前面。
     子体盘点页在讲位置，那边同一个槽位换成位次区间。槽位不变，装的东西按页面职责换。 */
  const spec = {
    graphic: (e) => ctx.el("span", { class: "kw-bar kw-bar-vol kw-bar-inrow" }, [
      ctx.el("i", { style: `width:${Math.max(2,
        ((e.monthly_search_volume || 0) / vmax) * 100)}%` }),
    ]),
    amount: (e) => ctx.el("span", { class: "kw-evrow-num",
      text: e.monthly_search_volume == null ? f.dash : f.int(e.monthly_search_volume) }),
    subject: (e) => e.child_asin,
    objectId: (e) => e.child_asin,
  };

  return section(ctx, {
    title: "关键词机会、缺口与风险",
    exportUrl: "/api/keyword/export",
    metrics: [
      ["待处理事项", f.int(p.total)],
      ["证据类型", `${p.type_counts.length} 类`],
      ["本页展开", `前 ${p.items.length} 条`],
      ["排序权重", p.weights
        ? Object.values(p.weights).map((v) => f.pct(v, 0)).join(" / ") : null],
      ["不在本模块", "加词 · 否词 · 出价 · 预算"],
    ],
    info: () => popBody(ctx, {
      title: "证据怎么读",
      rows: [
        ["排序依据", "需求规模 · 变化紧迫 · 主推加权 · 证据完整度"],
        ["条形的含义", "该词的月搜索量相对本页最大值 —— 排序的主要依据"],
      ],
      paras: [
        "同一类判断收成一组，不逐条平铺：一类里各条的结论句只差一个关键词名，"
        + "铺开等于让人读同一句话 N 遍。类型标签已经表达了「这是哪一类判断」，"
        + "行要回答的是「哪个对象、多重、下一步」。",
        "Agent 写的结论与依据在每行右侧的 ⓘ 里，连同引用的事件与观测日一起。",
        "组头那条细条是该组的证据完整度构成 —— 一组里多数是「证据不足」时，"
        + "这组的条数本身就不该被当成结论。",
      ],
    }),
    chart: ctx.el("div", { class: "kw-stackrow" }, [
      stackBar(ctx, p.type_counts.map((x) => ({
        label: x.name, n: x.n, kind: toneOfType(x.name),
      })), { label: "证据类型构成" }),
      stackBar(ctx, p.next_counts.map((x) => ({
        label: x.name, n: x.n,
        kind: /广告/.test(x.name) ? "vol" : /竞品/.test(x.name) ? "calm" : "mut",
      })), { label: "下一步验证构成" }),
    ]),
    extra: evidenceGroups(ctx, {
      items: p.items, spec, onOpen: (id) => ctx.open(id, "kw-asin"),
    }),
  });
}

/* ------------------------------------------- ④段：范围与口径（折叠） */

function scopeFold(ctx, d) {
  const el = ctx.el;
  const f = ctx.fmt;
  const s = d.scope;
  const blocked = d.blocked_reasons || [];
  return foldBlock(ctx, {
    title: "数据范围与口径",
    meta: blocked.length ? `${blocked.length} 项本期不参与比较` : "本期无受限范围",
    children: [
      metricRow(ctx, [
        ["站点与品线", `${s.site} · ${s.product_line}`],
        ["词库", f.int(s.library_terms)],
        ["监控词", f.int(s.monitored_terms)],
        ["重点子体", f.int(s.focus_children)],
        ["已建关系的词", f.int(s.terms_with_relations)],
      ]),
      metricRow(ctx, [
        ["周快照窗口", `${s.week_window[0]} ~ ${s.week_window[1]}`],
        ["逐日位置窗口", `${s.position_window[0]} ~ ${s.position_window[1]}`],
        ["有当前目标的子体", f.int(s.children_with_goal)],
        ["有库存承接的子体", f.int(s.children_with_absorb)],
        ["有第二来源的词", f.int(s.second_source_terms)],
      ]),
      blocked.length
        ? el("ul", { class: "kw-blocklist" },
          blocked.map((b) => el("li", { text: b })))
        : null,
      el("p", { class: "kw-foldnote",
        text: "覆盖率这类指标的分母按「重点子体」看，不是产品脊椎那 342 个。"
          + "「待处理事项」是整个观察窗口累计，不是当日。" }),
    ],
  });
}
