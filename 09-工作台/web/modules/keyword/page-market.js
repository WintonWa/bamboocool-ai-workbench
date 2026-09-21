/* 页面二 · 市场关键词库与单词深研
 *
 * 两个视图共用这一页：无 objectId 出词库列表，有 objectId 出单词深研。
 *
 * 重构前的两处「数据罗列」：
 *   1. 比较区是 200 行 × 10 列纯数字表。它回答不了这一屏真正的问题
 *      ——「哪些词高需求、低竞争」。现在前面加一张需求散点图（x 月搜索量取对数、
 *      y 需供比、点径 在售商品数），右下角就是答案区，表退成明细。
 *   2. 两来源对照是四列表格加「一致 / 不一致」文字，看得出有没有分歧，
 *      看不出哪个指标分歧最大。改哑铃图：两点一线，线长就是分歧幅度。
 */

import {
  chip, conclusionBand, dotLegend, evidenceGroups, foldBlock, heatCell, magnitudeCell,
  metricRow, num, popBody, rangeTrack, section, sourceCell, stackBar, table, txt,
} from "./parts.js";
import {
  barLineChart, demandScatter, dumbbellChart, shareBarChart, termSeriesChart,
} from "./charts.js";

/* ==================================================== 视图一：词库列表 */

export function renderLibrary(ctx, root, d) {
  const el = ctx.el;
  const hosts = { group: el("div"), scatter: el("div") };
  root.replaceChildren(
    libraryBand(ctx, d),
    groupStructureSection(ctx, d, hosts.group),
    compareSection(ctx, d, hosts.scatter),
    libraryFold(ctx, d),
  );
  barLineChart(hosts.group, d.groups.slice(0, 14), {
    catKey: "group_name", barKey: "search_volume", barLabel: "月搜索量",
    lineKey: "monitored_count", lineLabel: "其中监控词", rotate: 30,
  });
  demandScatter(hosts.scatter, d.terms, {
    onPick: (id) => ctx.open(id, "kw-term"),
  });
}

function libraryBand(ctx, d) {
  const s = d.summary;
  /* 词库状态与运营角色是**分类**，不是好坏，所以走中性色阶不套语义色 ——
     把「噪声词」染红会被读成风险，而它只是分类里的一档。浓度按条目顺序递减。 */
  const statusDots = dotLegend(ctx, d.library_status.map((x, i) => ({
    label: x.label, n: x.n, kind: `n${Math.min(5, i + 1)}`,
  })));
  const roleDots = dotLegend(ctx, d.monitored_role.map((x, i) => ({
    label: x.label, n: x.n,
    kind: x.label === "核心词" ? "n1" : `n${Math.min(5, i + 2)}`,
  })));
  return conclusionBand(ctx, {
    cells: [
      {
        label: "共享市场词库（唯一关键词）",
        value: s.total,
        sub: "本品线共用一套；未绑定子体时只出市场事实",
        lead: true,
      },
      { label: "在监控范围内", value: s.monitored,
        sub: `拼写变体族 ${ctx.fmt.int(s.variant_families)}` },
      { label: "需求词组", value: d.groups.length,
        sub: `运营已确认角色 ${ctx.fmt.int(s.role_confirmed)}` },
      { label: "词库状态构成", body: statusDots },
      { label: "运营角色构成", body: roleDots },
      sourceCell(ctx, d),
    ],
  });
}

function groupStructureSection(ctx, d, chartHost) {
  const f = ctx.fmt;
  const max = Math.max(1, ...d.groups.map((g) => g.search_volume));
  const worst = d.groups.reduce((a, b) => (b.double_count > a.double_count ? b : a),
    d.groups[0] || { double_count: 0, group_name: "" });

  const cols = [
    { label: "需求词组", cell: txt(ctx, (r) => r.group_name, "kw-strong") },
    { label: "维度", cell: txt(ctx, (r) => r.demand_dimension) },
    { label: "词数", num: true, cell: num(ctx, (r) => r.term_count) },
    { label: "其中监控", num: true, cell: num(ctx, (r) => r.monitored_count) },
    { label: "监控占比", num: true, cell: (r) => heatCell(ctx, {
      text: f.pct(r.term_count ? r.monitored_count / r.term_count : null, 0),
      ratio: r.term_count ? r.monitored_count / r.term_count : 0, kind: "good",
    }) },
    { label: "月搜索量", num: true, cell: (r) => magnitudeCell(ctx, {
      value: r.search_volume, ratio: r.search_volume / max, kind: "vol",
    }) },
    { label: "重复计入", num: true, cell: (r) => ctx.el("td", {
      class: "kw-num" + (r.double_count ? " kw-warn-cell" : ""),
      "data-sort": r.double_count || 0,
      text: r.double_count ? f.int(r.double_count) : ctx.fmt.dash,
    }) },
  ];

  return section(ctx, {
    title: "需求词组与市场结构",
    metrics: [
      ["需求词组", f.int(d.groups.length)],
      ["分权", d.dedup_applied ? "一词多组按 1/组数 分摊" : "未按权分摊"],
      ["重复计入最多", worst.group_name || null],
      ["若不分权会多算", worst.double_count ? f.int(worst.double_count) : "本期无",
        worst.double_count ? "warn" : null],
    ],
    info: () => popBody(ctx, {
      title: "分权是怎么算的",
      paras: [
        "一个词可以属于多个需求词组。不分权时它的月搜索量会在每个组里各算一次，"
        + "各组相加会超过词库总量。分权后按 1/组数 分摊，组间可加。",
        d.dedup_applied
          ? `当前已分权。不分权时「${worst.group_name}」会多算 `
            + `${f.int(worst.double_count)} 次月搜索量。`
          : "当前未分权，一词多组的搜索量在多个组里各算一次。",
        "「重复计入」这一列就是分权前后的差，可以直接看出哪些组吃了重复量。",
      ],
    }),
    chart: chartHost,
    table: table(ctx, { cols, rows: d.groups.slice(0, 20), sortable: [2, 3, 4, 5, 6] }),
  });
}

function compareSection(ctx, d, chartHost) {
  const f = ctx.fmt;
  const vmax = Math.max(1, ...d.terms.map((t) => t.monthly_search_volume || 0));

  const cols = [
    { label: "关键词", cell: (t) => ctx.el("td", {}, [
      ctx.el("span", { class: "kw-kwname", text: t.keyword }),
      t.keyword_cn ? ctx.el("i", { class: "kw-kwcn", text: t.keyword_cn }) : null,
    ]) },
    { label: "角色", cell: txt(ctx, (t) => t.operator_role_label) },
    { label: "月搜索量", num: true, cell: (t) => magnitudeCell(ctx, {
      value: t.monthly_search_volume,
      ratio: (t.monthly_search_volume || 0) / vmax, kind: "vol",
    }) },
    { label: "购买率", num: true, cell: (t) => heatCell(ctx, {
      text: f.pct(t.purchase_rate, 2), ratio: Math.min(1, (t.purchase_rate || 0) * 8),
      kind: "good", sort: t.purchase_rate,
    }) },
    { label: "需供比", num: true, cell: num(ctx, (t) => t.demand_supply_ratio,
      (v) => f.num(v, 2)) },
    { label: "在售商品数", num: true, cell: num(ctx, (t) => t.product_count) },
    { label: "广告竞品数", num: true, cell: num(ctx, (t) => t.ad_competitor_count) },
    { label: "头部三名点击占比", num: true, cell: (t) => heatCell(ctx, {
      text: f.pct(t.click_share_top3, 1), ratio: t.click_share_top3 || 0,
      kind: "warn", sort: t.click_share_top3,
    }) },
    { label: "两来源", cell: (t) => ctx.el("td", {
      class: t.has_conflict ? "kw-warn-cell" : "kw-dim",
      text: t.has_conflict ? `${t.conflict_fields.length} 项不一致` : "一致",
    }) },
  ];
  const rows = d.terms.map((t) => ({ ...t, __open: t.keyword_id }));

  return section(ctx, {
    title: "市场关键词比较区",
    metrics: [
      ["匹配到的词", f.int(d.total_matched)],
      ["本页展示", f.int(d.shown)],
      ["两来源数值冲突", d.conflict_terms ? f.int(d.conflict_terms) : "本期无",
        d.conflict_terms ? "warn" : null],
      ["冲突处理", "并列保留，不合并"],
    ],
    info: () => popBody(ctx, {
      title: "散点图怎么读",
      paras: [
        "x 是月搜索量，取对数轴 —— 搜索量跨三个数量级（1.7 万到 170 万），"
        + "线性轴会把九成的点挤在左边一条竖线上。",
        "y 是需供比，点径是在售商品数。右下角是高需求、低竞争、在售少的区域，"
        + "那里的词是这一屏真正要找的东西。点一下点就进那个词的深研页。",
        "颜色按运营角色分。表格是明细，回答「全部长什么样」；图回答「该看哪个」。",
        "ABA 月排名没有进表：它与月搜索量高度相关，两列并排只是占位置，"
        + "需要时在单词深研页看。",
      ],
    }),
    chart: chartHost,
    table: table(ctx, {
      cols, rows, sortable: [2, 3, 4, 5, 6, 7],
      onRowOpen: (id) => ctx.open(id, "kw-term"),
    }),
  });
}

function libraryFold(ctx, d) {
  const f = ctx.fmt;
  const s = d.summary;
  return foldBlock(ctx, {
    title: "词库范围与质量明细",
    meta: `${f.int(s.brands)} 个品牌`,
    children: [
      metricRow(ctx, [
        ["品牌", f.int(s.brands)],
        ["其中竞品品牌", f.int(s.competitor_brands)],
        ["最早出现", s.first_seen],
        ["最近更新", s.last_updated],
      ]),
      ctx.el("div", { class: "kw-chips" },
        (d.brand_role || []).map((x) => chip(ctx, x.label, x.n))),
      ctx.el("p", { class: "kw-foldnote",
        text: "共享词库是本品线共用的一套。一个词在没有绑定任何子体之前，"
          + "这一页只出市场事实，不出产品级机会结论。" }),
    ],
  });
}

/* ==================================================== 视图二：单词深研 */

export function renderTerm(ctx, root, d) {
  const el = ctx.el;
  const hosts = {
    month: el("div"), week: el("div"), dumb: el("div"), head: el("div"),
  };
  root.replaceChildren(
    termBand(ctx, d),
    termSeriesSection(ctx, d, hosts.month, hosts.week),
    termCompareSection(ctx, d, hosts.dumb),
    termHeadSection(ctx, d, hosts.head),
    termRelationSection(ctx, d),
    termFold(ctx, d),
  );
  termSeriesChart(hosts.month, d.series.month, {
    barKey: "monthly_search_volume", barLabel: "月搜索量",
    lineKey: "purchase_rate", lineLabel: "购买率",
  });
  termSeriesChart(hosts.week, d.series.week, {
    barKey: "product_count", barLabel: "在售商品数",
    lineKey: "aba_week_rank", lineLabel: "ABA 周排名", invertLine: true,
  });
  dumbbellChart(hosts.dumb, d.compare);
  shareBarChart(hosts.head, d.head_asins.filter((h) => h.rank_slot <= 3));
}

function termBand(ctx, d) {
  const el = ctx.el;
  const f = ctx.fmt;
  const i = d.identity;
  const m = d.series.month;
  const cur = m.length ? m[m.length - 1] : {};
  const back = el("button", { class: "kw-back", type: "button", text: "← 回词库" });
  back.addEventListener("click", () => ctx.open(null, "kw-market"));
  return el("div", { class: "kw-termhead" }, [
    back,
    conclusionBand(ctx, {
      cells: [
        {
          label: `「${i.keyword}」${i.keyword_cn || ""} · 月搜索量`,
          value: cur.monthly_search_volume,
          sub: `月购买量 ${f.int(cur.monthly_purchase_volume)}　`
            + `购买率 ${f.pct(cur.purchase_rate, 2)}`,
          lead: true,
        },
        { label: "ABA 月排名", value: cur.aba_month_rank,
          sub: `月快照 ${m.length} 期 · 周快照 ${d.series.week.length} 期` },
        { label: "头部里的自有产品", value: d.own_in_head,
          sub: d.head_replaced ? "第一名窗口内换过人" : "第一名窗口内没变",
          tone: d.own_in_head ? "good" : null },
        { label: "已建关系的子体", value: d.relations.length,
          sub: d.evidence.length ? `${d.evidence.length} 条证据` : "尚无产品级证据" },
        {
          /* 只留三个。五个标签在一格 175px 里会堆成五行，把整张卡撑到 225px
             （参考实现的头部卡约 110~130px）。品牌属性与数据性质移进页尾折叠区。 */
          label: "词身份",
          body: el("div", { class: "kw-chips kw-chips-cell" }, [
            chip(ctx, "状态", i.library_status_label),
            chip(ctx, "角色", (i.operator_role_label || "")
              + (i.operator_role_confirmed && i.operator_role !== "unset" ? "·已确认" : "")),
            chip(ctx, "监控", i.is_monitored ? "在内" : "不在内"),
          ]),
        },
        sourceCell(ctx, d),
      ],
    }),
  ]);
}

function termSeriesSection(ctx, d, monthHost, weekHost) {
  const el = ctx.el;
  const s = d.series;
  return section(ctx, {
    title: "单词市场事实深研",
    metrics: [
      ["月快照", `${s.month.length} 期`],
      ["周快照", `${s.week.length} 期`],
      ["本期不可比", s.not_comparable.length ? `${s.not_comparable.length} 期` : "本期无",
        s.not_comparable.length ? "warn" : null],
      ["市场变化事件", d.market_events.length || "本期无"],
    ],
    info: () => popBody(ctx, {
      title: "为什么分两张图",
      rows: [
        ["月度口径", s.month_measure],
        ["周度口径", s.week_measure],
      ],
      paras: [
        "月搜索量与周排名口径不同，不折算成同一周期 —— 折算会造出一个源表里"
        + "不存在的数。所以两种频率各自成图。",
        "周度那张的 ABA 周排名轴是倒过来的：排名数字小＝排得好，线在上面＝表现好。",
        "叠加轴都从 0 起。不从 0 起会把只波动百分之一两的线画成大起大落，"
        + "而叠加轴通常没有刻度可参照，看的人只能读到一个错误的印象。",
      ],
    }),
    chart: el("div", { class: "kw-chartpair" }, [
      el("div", { class: "kw-chartcell" }, [
        el("div", { class: "kw-chartcap", text: "月度：搜索量与购买率" }), monthHost]),
      el("div", { class: "kw-chartcell" }, [
        el("div", { class: "kw-chartcap", text: "周度：在售商品数与 ABA 周排名" }), weekHost]),
    ]),
    extra: (s.not_comparable.length || d.market_events.length)
      ? el("div", { class: "kw-eventstrip" }, [
        ...s.not_comparable.map((x) => el("span", { class: "kw-evtag kw-evtag-warn",
          text: `${x.period_end}　${x.reason}` })),
        ...d.market_events.slice(0, 8).map((e) => el("span", {
          class: "kw-evtag",
          title: e.label,
          text: `${e.to_period_end}　${e.event_type_label}　${e.continuity_label}`,
        })),
      ])
      : null,
  });
}

function termCompareSection(ctx, d, chartHost) {
  const f = ctx.fmt;
  const fmtAny = (v) => (v == null ? f.dash
    : (typeof v === "number" && !Number.isInteger(v) ? f.num(v, 4) : f.int(v)));
  const cols = [
    { label: "指标", cell: txt(ctx, (c) => c.metric, "kw-strong") },
    { label: "关键词3", num: true, cell: (c) => ctx.el("td", {
      class: "kw-num", "data-sort": c.primary ?? -Infinity, text: fmtAny(c.primary) }) },
    { label: "关键词2", num: true, cell: (c) => ctx.el("td", {
      class: "kw-num", "data-sort": c.second ?? -Infinity, text: fmtAny(c.second) }) },
    { label: "一致性", cell: (c) => ctx.el("td", {
      class: c.conflict ? "kw-warn-cell" : "kw-dim",
      text: c.conflict ? "不一致" : (c.second == null ? "第二来源无此项" : "一致") }) },
  ];
  return section(ctx, {
    title: "两份来源的同期数值",
    metrics: [
      ["对照项", f.int(d.compare.length)],
      ["不一致", d.conflict_count ? f.int(d.conflict_count) : "本期无",
        d.conflict_count ? "warn" : null],
      ["处理方式", "并列保留，不做合并"],
      ["第二来源说明", d.second_source_note || null],
    ],
    info: () => popBody(ctx, {
      title: "哑铃图怎么读",
      paras: [
        "每行两个点一条线：黑点是关键词3，紫点是关键词2，线长就是两者的分歧幅度。"
        + "线染成橙色的那几行是本期真的不一致。",
        "各指标量纲差几个数量级，所以每行各自归一到自己那一行的最大值 —— "
        + "行内可比，行间不比。所以 x 轴不给刻度：那个位置没有业务含义。",
        "两来源冲突一律并列保留不合并。合并成一个数就等于替客户裁定哪份文件是对的，"
        + "而这件事页面判不了。",
      ],
    }),
    chart: chartHost,
    table: table(ctx, { cols, rows: d.compare }),
  });
}

/* 头部 ASIN 不等于已确认竞品。前三名带点击与转化共享，4-10 名源表只给 ASIN ——
   分两段呈现，不拉成一张表让 7 行共享列全是「—」，那看起来像坏了。 */
function termHeadSection(ctx, d, chartHost) {
  const el = ctx.el;
  const f = ctx.fmt;
  const top3 = d.head_asins.filter((h) => h.rank_slot <= 3);
  const rest = d.head_asins.filter((h) => h.rank_slot > 3);
  const hist = d.head_slot1_history;
  return section(ctx, {
    title: "头部 ASIN 与竞品线索",
    metrics: [
      ["头部位次", f.int(d.head_asins.length)],
      ["其中自有产品", d.own_in_head ? f.int(d.own_in_head) : "本期无",
        d.own_in_head ? "good" : null],
      ["第一名", d.head_replaced ? "窗口内换过人" : "窗口内没变",
        d.head_replaced ? "warn" : null],
      ["前三名点击合计", top3.length
        ? f.pct(top3.reduce((a, h) => a + (h.click_share || 0), 0), 1) : null],
    ],
    info: () => popBody(ctx, {
      title: "头部 ASIN 的口径",
      paras: [
        "头部 ASIN 不等于已确认竞品 —— 它只是这个词下点击集中的位置。"
        + "要确认是不是竞品，去竞品分析页核对价格、促销与流量是否同期变化。",
        d.head_replaced && hist.length
          ? `第一名在窗口内换过人：${hist[0][1]} → ${hist[hist.length - 1][1]}。`
          : "第一名在窗口内没有变化。",
        "只有前三名有点击与转化共享，第 4-10 名源表只给 ASIN，所以分两段放，"
        + "不拉成一张表让后面 7 行的共享列全是「—」。",
      ],
    }),
    chart: chartHost,
    extra: rest.length
      ? el("div", { class: "kw-restwrap" }, [
        el("div", { class: "kw-sec-note", text: "第 4-10 名（源表只给 ASIN）" }),
        el("div", { class: "kw-chips" }, rest.map((h) => el("span", {
          class: "kw-chip" + (h.is_own_asin ? " kw-chip-own" : ""),
          text: `${h.rank_slot}. ${h.asin}${h.is_own_asin ? "　自有" : ""}`,
        }))),
      ])
      : null,
  });
}

function termRelationSection(ctx, d) {
  const el = ctx.el;
  const f = ctx.fmt;
  if (!d.relations.length) {
    return section(ctx, {
      title: "关键词与产品关系",
      note: "这个词还没有和任何子体建立关系，因此只给市场事实，不给产品机会结论",
      extra: el("div", { class: "kw-empty", text: "无已建立关系的子 ASIN" }),
    });
  }
  const cap = Math.max(20, ...d.relations.map((r) => r.organic_rank || 0));
  const cols = [
    { label: "子 ASIN", cell: txt(ctx, (r) => r.child_asin, "kw-strong") },
    { label: "款号", cell: txt(ctx, (r) => r.style_no) },
    { label: "锚点", cell: txt(ctx, (r) => r.anchor_band_label || "构造") },
    { label: "自然位（左＝第 1 位）", cell: (r) => el("td", {
      class: "kw-shiftcell", "data-sort": r.organic_rank ?? 9999,
    }, [rangeTrack(ctx, { best: r.organic_rank, cur: r.organic_rank,
      worst: r.organic_rank, cap, title: `当前第 ${r.organic_rank} 位` })
      || el("i", { class: "kw-na-fig" })]) },
    { label: "自然位", num: true, cell: num(ctx, (r) => r.organic_rank,
      (v) => `第 ${v} 位`) },
    { label: "广告位", num: true, cell: num(ctx, (r) => r.ad_rank, (v) => `第 ${v} 位`) },
    { label: "状态", cell: txt(ctx, (r) => r.organic_state_label) },
    { label: "库存承接", cell: txt(ctx, (r) => r.absorb_state_label) },
  ];
  const rows = d.relations.map((r) => ({
    ...r, __open: r.child_asin, __tone: r.weak ? "warn" : null,
  }));
  /* S1 判据图形按 child_asin 关联到上面那张关系表的真实自然位。
     这里曾经画成 best:1 / worst:cap 的恒定满宽轨 —— 那是装饰不是信息，
     每行长得一样就等于没画。取不到的留空槽，不猜。 */
  const byChild = new Map(d.relations.map((r) => [r.child_asin, r]));
  const spec = {
    graphic: (e) => {
      const r = byChild.get(e.child_asin);
      if (!r || !r.organic_rank) return null;
      return rangeTrack(ctx, {
        best: r.organic_rank, cur: r.organic_rank, worst: r.organic_rank, cap,
        title: `${r.child_asin} 当前第 ${r.organic_rank} 位`,
      });
    },
    amount: (e) => {
      const r = byChild.get(e.child_asin);
      return el("span", { class: "kw-evrow-num",
        text: r && r.organic_rank ? `第 ${r.organic_rank} 位` : f.dash });
    },
    subject: (e) => e.child_asin,
    objectId: (e) => e.child_asin,
  };
  return section(ctx, {
    title: "关键词与产品关系",
    metrics: [
      ["已建立关系的子体", f.int(d.relations.length)],
      ["自然位偏弱", d.relations.filter((r) => r.weak).length || "本期无",
        d.relations.some((r) => r.weak) ? "warn" : null],
      ["证据条数", d.evidence.length || "本期无"],
      ["操作", "点行进入该子体的关键词盘点"],
    ],
    chart: stackBar(ctx, [
      { label: "自然位正常", n: d.relations.filter((r) => !r.weak && r.organic_rank).length,
        kind: "good" },
      { label: "自然位偏弱", n: d.relations.filter((r) => r.weak).length, kind: "warn" },
      { label: "无自然位", n: d.relations.filter((r) => !r.organic_rank).length,
        kind: "mut" },
    ], { label: "已建关系子体的自然位分布" }),
    table: table(ctx, {
      cols, rows, sortable: [4, 5],
      onRowOpen: (id) => ctx.open(id, "kw-asin"),
    }),
    // 证据是结论，排在关系明细表之后 —— 放表前会被读成对指标条那句话的补充
    after: d.evidence.length
      ? evidenceGroups(ctx, { items: d.evidence, spec,
        onOpen: (id) => ctx.open(id, "kw-asin") })
      : el("div", { class: "kw-empty", text: "这个词上还没有形成产品级证据结论" }),
  });
}

function termFold(ctx, d) {
  const el = ctx.el;
  const i = d.identity;
  return foldBlock(ctx, {
    title: "词身份、同义变体与所属词组",
    meta: `${d.aliases.length} 个变体 · ${d.groups.length} 个词组`,
    children: [
      metricRow(ctx, [
        ["品牌属性", i.brand_role_label],
        ["数据性质", d.nature],
        ["所属类目", i.category_path],
        ["主要分类", i.primary_category],
        ["相关度", i.relevance],
      ]),
      metricRow(ctx, [
        ["角色种子词", i.operator_role_seed_word],
        ["原始写法数", i.raw_variant_count],
      ]),
      d.aliases.length
        ? el("div", { class: "kw-chips" }, d.aliases.map((a) =>
          chip(ctx, a.alias_type_label, a.alias_text)))
        : null,
      d.groups.length
        ? el("div", { class: "kw-chips" }, d.groups.map((g) =>
          chip(ctx, g.group_name, `×${g.dedup_weight}`)))
        : null,
    ],
  });
}
