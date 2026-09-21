/* 页面三 · 子 ASIN 关键词盘点
 *
 * 这一页是与库存单品盘点页最可比的一页，形状照那边对齐（主图方块 + 身份 +
 * 结论先行 + 规格收进浮层），不另发明。
 *
 * 重构前最刺眼的三处：
 *   1. **身份出现两次**：hero 写「B0B3LWGP36 待处理的关键词事项」，
 *      隔一条结论下面又是独立的一块「B0B3LWGP36　TH22AM-097男士长平角」，
 *      中间还夹着一条结论。三层重复合成一块。
 *   2. **逐日位置图是 CSS 条形**：182 天 × 66 词的密度下是一片乱柱，读不出趋势。
 *      换 ECharts：位次折线（y 轴反向，线高＝位置好）+ 五态构成细带 + 采集失败背景。
 *   3. **36 条证据铺 144 行**：13 条同类文案只差一个关键词名。改证据组。
 */

import {
  evidenceGroups, foldBlock, heatCell, magnitudeCell, num, overviewCard, popBody,
  rangeTrack, section, sourceCell, sparkLine, stackBar, table, toneOfType, txt,
  verdictRow,
} from "./parts.js";
import { auditTrendChart, dailyPositionChart, gapBarChart } from "./charts.js";

export function renderChild(ctx, root, d) {
  const el = ctx.el;
  const hosts = { gap: el("div"), daily: el("div"), audit: el("div") };
  root.replaceChildren(
    identityAndVerdict(ctx, d),
    coverageSection(ctx, d.coverage, hosts.gap),
    positionSection(ctx, d.positions, hosts.daily),
    evidenceSection(ctx, d),
    auditFold(ctx, d.audits, hosts.audit),
  );
  gapBarChart(hosts.gap, d.coverage.groups);
  dailyPositionChart(hosts.daily, d.positions);
  auditTrendChart(hosts.audit, d.audits.runs);
}

/* ------------------------------- ②段：身份 + 盘点结论（合并三层） */

function identityAndVerdict(ctx, d) {
  const el = ctx.el;
  const f = ctx.fmt;
  const c = d.context;
  const cov = d.coverage.summary;
  const ev = d.evidence;
  const top = ev.items[0];
  const risk = (ev.type_counts.find((t) => t.name === "核心位置风险") || {}).n || 0;
  const gapGroups = d.coverage.groups.filter((g) => g.gap > 0).length;
  const declining = d.positions.tracks.filter((t) => t.is_continuous_decline).length;
  const toAds = ev.items.filter((e) => e.next_verification_label === "进入广告决策处理").length;
  const toRival = ev.items.filter((e) =>
    e.next_verification_label === "进入竞品分析验证").length;

  /* 规格收进浮层。判据是库存页那条：新字段进第一屏前先问运营是否本来就知道 ——
     颜色、尺码、装盒数是他自己的产品属性，不需要占第一屏。 */
  const specPop = () => popBody(ctx, {
    title: "产品信息",
    rows: [
      ["父体", c.parent_asin], ["款号", c.style_no],
      ["颜色", c.colorway], ["尺码", c.size], ["装盒", c.combination],
      ["产品阶段", c.lifecycle], ["小类排名", c.category_rank], ["评分", c.rating],
      ["数据性质", c.nature],
    ],
  });

  /* 结论行。**这几条是工作台算术，不是 Agent 判断** ——
     Agent 判的那部分在下面「关键词缺口、机会与风险」板块里，那块才带 AI 徽标。
     最后一行是 Agent 排在第一的那条结论，明确标出它的来源。 */
  const rows = [
    verdictRow(ctx, {
      tone: cov.not_covered ? "warn" : "good",
      name: "覆盖", state: `${cov.organic_covered} / ${cov.related} 有自然位`,
      say: gapGroups
        ? `${gapGroups} 个需求词组还有缺口，缺口最大的是「${
          d.coverage.groups[0] ? d.coverage.groups[0].group_name : "—"}」`
        : "监控词组内没有留下缺口",
      detail: () => popBody(ctx, {
        title: "覆盖口径",
        rows: [
          ["本子体相关词", f.int(cov.related)],
          ["有自然位", f.int(cov.organic_covered)],
          ["有广告位", f.int(cov.ad_covered)],
          ["自然与广告同时有", f.int(cov.both_covered)],
          ["确认未覆盖", f.int(cov.not_covered)],
        ],
        paras: ["自然与广告分别判断：只有广告流量不代表已形成自然覆盖。"],
      }),
    }),
    verdictRow(ctx, {
      tone: declining ? "alert" : "",
      name: "位置", state: declining ? `${declining} 个词在连续走弱` : "无连续走弱",
      say: declining
        ? `平滑后自然位连续变差达到 ${d.positions.tracks[0]
          && d.positions.tracks[0].down_streak_days || 0} 天的词，需要看是市场在动还是自己掉了`
        : `窗口 ${d.positions.date_from} ~ ${d.positions.date_to} 内没有出现连续走弱`,
      detail: () => popBody(ctx, {
        title: "连续走弱怎么判",
        paras: [
          "先做 7 天移动均值再判单调。直接对逐日位次判严格单调是取不到的：位次每天有抖动，"
          + "连续 7 天不回头几乎不可能 —— 实测主演示对象 66 条轨迹里「连续下滑」恒为 0，"
          + "而事件表同期有 24 条自然位下降。平滑掉抖动、保留趋势才判得出来。",
        ],
      }),
    }),
    verdictRow(ctx, {
      tone: risk ? "alert" : "good",
      name: "风险", state: risk ? `${risk} 条核心位置风险` : "无核心位置风险",
      say: c.absorb_state_label
        ? `库存承接为「${c.absorb_state_label}」${c.absorb_detail ? "：" + c.absorb_detail : ""}`
        : "库存承接结果缺失，暂不判断能否扩量",
      detail: c.absorb_detail ? () => popBody(ctx, {
        title: "库存承接",
        rows: [
          ["承接状态", c.absorb_state_label],
          ["最晚下单日", c.latest_order_date],
          ["距最晚下单日", c.days_to_latest_order == null
            ? null : `${c.days_to_latest_order} 天`],
        ],
        paras: [c.absorb_detail,
          "承接结果来自产品与库存模块，本页只读不改 —— 关键词发现了机会，"
          + "能不能吃下由库存那边说。"],
      }) : null,
    }),
    verdictRow(ctx, {
      tone: "",
      name: "下一步", state: `${toAds} 进广告 / ${toRival} 进竞品`,
      say: "本模块不出加词、否词、出价与预算动作，只交出该处理什么和为什么",
      detail: () => popBody(ctx, {
        title: "交接口径",
        rows: [
          ["待交给广告决策", f.int(toAds)],
          ["待进竞品分析验证", f.int(toRival)],
          ["证据条数", f.int(ev.total)],
        ],
      }),
    }),
    top ? verdictRow(ctx, {
      tone: toneOfType(top.evidence_type_label),
      name: "Agent 首位", state: top.evidence_type_label,
      say: top.conclusion,
      detail: () => popBody(ctx, {
        title: `${top.evidence_type_label} · ${top.keyword}`,
        rows: [
          ["证据完整度", top.evidence_completeness_label],
          ["下一步", top.next_verification_label],
          ["观测日", top.ref_position_date],
        ],
        paras: [top.conclusion, top.main_basis],
      }),
    }) : null,
  ];

  return el("section", { class: "kw-sec kw-idsec" }, [
    overviewCard(ctx, {
      cells: [
        {
          label: "已选子 ASIN",
          lead: true,
          media: el("div", { class: "kw-cell-thumb" }, [
            el("img", { src: "/assets/product-placeholder.png", alt: "商品主图" }),
            el("span", { class: "kw-thumbtag", text: "示意" }),
          ]),
          text: c.child_asin,
          /* 副行只放品名。父体、款号、颜色尺码全在「产品信息」浮层里 ——
             塞进副行会在「产品阶／段」这种位置断词（CJK 默认可任意断行）。 */
          sub: c.product_name || null,
          action: el("span", {
            class: "kw-specbtn", role: "button", tabindex: "0", text: "产品信息",
            onclick: (e) => ctx.pop.show(e.currentTarget, specPop()),
          }),
        },
        {
          label: "产品目标",
          text: c.product_goal_label || "未设定",
          sub: [c.push_role_label, c.lifecycle].filter(Boolean).join(" · ") || null,
          tone: c.product_goal_label ? null : "warn",
        },
        {
          label: "库存与产能",
          text: c.absorb_state_label || "缺承接结果",
          sub: c.days_to_latest_order != null && c.days_to_latest_order < 0
            ? `最晚下单日已过 ${-c.days_to_latest_order} 天`
            : c.days_to_latest_order != null
              ? `距最晚下单日 ${c.days_to_latest_order} 天`
              : "无最晚下单日",
          tone: /不可/.test(c.absorb_state_label || "") ? "warn" : null,
        },
        {
          label: "关键词判断（整体）",
          value: ev.total,
          sub: `自然位 ${cov.organic_covered}/${cov.related} · 风险 ${risk} 条`,
          subTone: risk ? "alert" : null,
        },
        {
          label: "缺口与走弱",
          text: `${gapGroups} 组 / ${declining} 词`,
          sub: "有缺口词组 / 连续走弱",
        },
        sourceCell(ctx, d),
      ],
    }),
    el("div", { class: "kw-verdicts" }, rows.filter(Boolean)),
    (c.blocked_reasons || []).length
      ? el("ul", { class: "kw-blocklist" },
        c.blocked_reasons.map((r) => el("li", { text: r })))
      : null,
    c.goal_history.length
      ? el("div", { class: "kw-sec-note",
        text: `目标改过：${c.goal_history.map((g) =>
          `${g.from} 起为「${g.product_goal_label}」`).join("；")}` })
      : null,
  ]);
}


/* --------------------------------------- ③段：关键词覆盖结构 */

function coverageSection(ctx, cov, chartHost) {
  const f = ctx.fmt;
  const s = cov.summary;
  const maxGap = Math.max(1, ...cov.groups.map((g) => g.gap));
  const partition = (s.organic_only || 0) + (s.both_covered || 0)
    + (s.ad_only || 0) + (s.not_covered || 0);
  const rest = Math.max(0, (s.related || 0) - partition);

  const cols = [
    { label: "需求词组", cell: txt(ctx, (g) => g.group_name, "kw-strong") },
    { label: "维度", cell: txt(ctx, (g) => g.demand_dimension) },
    { label: "组内监控词", num: true, cell: num(ctx, (g) => g.monitored_in_group,
      (v) => f.num(v, 0)) },
    { label: "本子体相关", num: true, cell: num(ctx, (g) => g.related_here,
      (v) => f.num(v, 0)) },
    // 用「本子体相关 ÷ 组内监控词」而不是「自然覆盖 ÷ 本子体相关」：
    // 后者在锚点齐全的子体上整列恒为 100%，一列没有信息量。
    { label: "组内覆盖率", num: true, cell: (g) => heatCell(ctx, {
      text: f.pct(g.group_reach, 0), ratio: g.group_reach, kind: "good",
      sort: g.group_reach }) },
    { label: "自然 / 广告覆盖", cell: (g) => ctx.el("td", { class: "kw-num",
      "data-sort": g.organic_covered,
      text: `${f.num(g.organic_covered, 0)} / ${f.num(g.ad_covered, 0)}` }) },
    { label: "缺口", num: true, cell: (g) => magnitudeCell(ctx, {
      value: g.gap, ratio: g.gap / maxGap, kind: "gap", digits: 0 }) },
  ];

  return section(ctx, {
    title: "关键词覆盖结构",
    metrics: [
      ["本子体相关词", f.int(s.related)],
      ["有自然位 / 有广告位", `${s.organic_covered} / ${s.ad_covered}`],
      [`自然位在第 ${s.weak_rank_threshold} 位之后`,
        s.weak_position ? f.int(s.weak_position) : "本期无", s.weak_position ? "warn" : null],
      ["有缺口的词组", cov.groups.filter((g) => g.gap > 0).length || "本期无"],
      ["缺口口径", cov.dedup_applied ? "一词多组按权分摊" : "未按权分摊"],
    ],
    info: () => popBody(ctx, {
      title: "覆盖结构的口径",
      rows: [
        ["组内覆盖率", "本子体相关 ÷ 组内监控词"],
        ["缺口", "组内监控词 − 本子体相关"],
      ],
      paras: [
        "不用「自然覆盖 ÷ 本子体相关」当覆盖率：那个在锚点齐全的子体上整列恒为 100%，"
        + "一列没有信息量。",
        "图按缺口降序取前 12 个词组，柱是缺口词数、线是组内覆盖率 —— 回答「先补哪个需求」。",
        "堆叠条那四段是真分区（不重叠）；「有自然位」「有广告位」是它们的合计，"
        + "混进同一条会重复计数，所以只留在指标条里。",
      ],
    }),
    chart: chartHost,
    extra: stackBar(ctx, [
      { label: "自然与广告同时有", n: s.both_covered, kind: "good" },
      { label: "只有自然位", n: s.organic_only, kind: "calm" },
      { label: "只有广告位", n: s.ad_only, kind: "warn" },
      { label: "确认未覆盖", n: s.not_covered, kind: "alert" },
      { label: "其余状态", n: rest, kind: "mut" },
    ], { label: "覆盖分区" }),
    table: table(ctx, { cols, rows: cov.groups, sortable: [2, 3, 4, 6] }),
  });
}

/* --------------------------------- ③段：自然位与广告位变化 */

function positionSection(ctx, p, chartHost) {
  const f = ctx.fmt;
  const SHOW = 16;
  const tracks = p.tracks.slice(0, SHOW);
  const declines = p.tracks.filter((t) => t.is_continuous_decline).length;

  const cols = [
    { label: "关键词", cell: (t) => ctx.el("td", {}, [
      ctx.el("span", { class: t.is_core ? "kw-strong kw-core" : null, text: t.keyword }),
    ]) },
    { label: "角色", cell: txt(ctx, (t) => t.operator_role_label) },
    { label: "锚点", cell: txt(ctx, (t) => t.anchor_band_label) },
    { label: "位次区间（左＝第 1 位）", cell: (t) => ctx.el("td", {
      class: "kw-shiftcell", "data-sort": t.best_rank == null ? 9999 : t.best_rank,
    }, [rangeTrack(ctx, { best: t.best_rank, cur: t.current_organic,
      worst: t.worst_rank, cap: p.collect_depth }) || ctx.el("i", { class: "kw-na-fig" })]) },
    { label: "当前自然位", num: true, cell: num(ctx, (t) => t.current_organic,
      (v) => `第 ${v} 位`) },
    { label: "当前广告位", num: true, cell: num(ctx, (t) => t.current_ad,
      (v) => `第 ${v} 位`) },
    { label: "连降天数", num: true, cell: (t) => ctx.el("td", {
      class: "kw-num" + (t.is_continuous_decline ? " kw-warn-cell" : ""),
      "data-sort": t.down_streak_days || 0,
      text: t.down_streak_days ? `${t.down_streak_days} 天` : ctx.fmt.dash }) },
    { label: "90 天轨迹", cell: (t) => ctx.el("td", { class: "kw-sparkcell" }, [
      ctx.el("span", { class: "kw-spark",
        html: sparkLine(t.points.map((x) => x.organic), { invert: true })
          || "" })]) },
  ];
  const rows = tracks.map((t) => ({
    ...t, __tone: t.is_continuous_decline ? "warn" : null,
  }));

  return section(ctx, {
    title: "自然位与广告位变化",
    metrics: [
      ["窗口", `${p.date_from} ~ ${p.date_to}`],
      ["采集深度", `第 ${p.collect_depth} 位`],
      ["自然位连续走弱", declines ? `${declines} 个词` : "本期无", declines ? "warn" : null],
      ["采集失败", (p.collect_fail_days || []).length
        ? `${p.collect_fail_days.length} 天` : "本期无",
      (p.collect_fail_days || []).length ? "warn" : null],
      ["下表展开", `${tracks.length} / ${p.tracks.length} 个词`],
    ],
    info: () => popBody(ctx, {
      title: "这张图怎么读",
      rows: [
        ["采集失败日", (p.collect_fail_days || []).join("、") || "本期无"],
        [`变动超过 ${p.rank_shift_threshold} 名`, f.int(p.significant_events)],
      ],
      paras: [
        "折线是当日平均自然位，y 轴是倒过来的 —— 位次数字小＝排得好，"
        + "所以线在上面＝位置好。紫色背景带是整日采集失败，那几天的空缺不是掉出排名。",
        "五态构成是下面那条细带，默认关着，图例里可以逐个打开。不画成堆叠柱的原因："
        + "覆盖齐全的子体上「有排名」占九成以上，整张图会是一片纯黑，看不出结构。",
        "表里「位次区间」那条轨：左端是第 1 位，横条是最好到最差的跨度，圆点是当前位置。"
        + "跨度长＝这个词在颠。「90 天轨迹」那条线极差不到中位数 2% 时按水平线画 —— "
        + "把噪声铺成波形会读成有波动，那和一排等高柱是同一个错。",
      ],
    }),
    chart: chartHost,
    extra: stackBar(ctx, (p.event_counts || []).map((e) => ({
      label: e.name, n: e.n,
      kind: /下降|丢失|跌出|失败/.test(e.name) ? "alert"
        : /上涨|新增/.test(e.name) ? "good" : "calm",
    })), { label: "覆盖与位置事件构成" }),
    table: table(ctx, { cols, rows, sortable: [3, 4, 5, 6] }),
  });
}

/* ------------------------- ③段：关键词缺口、机会与风险（证据组） */

function evidenceSection(ctx, d) {
  const f = ctx.fmt;
  const ev = d.evidence;
  const p = d.positions;

  /* S1 判据图形：这一页在讲位置，所以画**位次区间**。
     按关键词关联到 tracks —— 两份数据都已经在载荷里，前端对上就行，
     不在后端解析 main_basis 的文本（那是在猜）。取不到的退化成空槽不塌陷。 */
  const byKw = new Map(p.tracks.map((t) => [t.keyword, t]));
  const spec = {
    graphic: (e) => {
      const t = byKw.get(e.keyword);
      if (!t) return null;
      return rangeTrack(ctx, {
        best: t.best_rank, cur: t.current_organic, worst: t.worst_rank,
        cap: p.collect_depth,
      });
    },
    amount: (e) => {
      const t = byKw.get(e.keyword);
      return ctx.el("span", { class: "kw-evrow-num",
        text: t && t.current_organic ? `第 ${t.current_organic} 位` : f.dash });
    },
    objectId: null,
  };

  return section(ctx, {
    title: "关键词缺口、机会与风险",
    exportUrl: "/api/keyword/export",
    metrics: [
      ["证据条数", f.int(ev.total)],
      ["证据类型", `${ev.type_counts.length} 类`],
      ["同组展开", "前 4 条"],
      ["排序权重", ev.weights
        ? Object.values(ev.weights).map((v) => f.pct(v, 0)).join(" / ") : null],
    ],
    info: () => popBody(ctx, {
      title: "证据怎么读",
      paras: [
        "同一类判断收成一组，不逐条平铺：一类里各条的结论句只差一个关键词名，"
        + "铺开等于让人读同一句话 N 遍。类型标签已经表达了「这是哪一类判断」，"
        + "行要回答的是「哪个词、位置多深、下一步」。",
        "每行最左那条轨是这个词的位次区间：左端第 1 位，横条是窗口内最好到最差的跨度，"
        + "圆点是当前位置。它按关键词与上面那张位置图的轨迹对上，不是从结论文字里解析出来的。",
        "Agent 写的结论与依据在每行右侧的 ⓘ 里。这是它们唯一的上屏位置 —— "
        + "把它们铺到正文就是重构前那 144 行。",
      ],
    }),
    chart: stackBar(ctx, ev.type_counts.map((t) => ({
      label: t.name, n: t.n, kind: toneOfType(t.name),
    })), { label: "证据类型构成" }),
    extra: evidenceGroups(ctx, { items: ev.items, spec }),
  });
}

/* --------------------------------------- ④段：盘点记录（折叠） */

function auditFold(ctx, au, chartHost) {
  const f = ctx.fmt;
  const runs = au.runs || [];
  const cols = [
    { label: "盘点日期", cell: txt(ctx, (r) => r.run_date, "kw-num kw-strong") },
    { label: "关系数", num: true, cell: num(ctx, (r) => r.pair_count) },
    { label: "有自然位 / 广告位", cell: (r) => ctx.el("td", { class: "kw-num",
      "data-sort": r.organic_covered_count,
      text: `${f.int(r.organic_covered_count)} / ${f.int(r.ad_covered_count)}` }) },
    { label: "双覆盖", num: true, cell: num(ctx, (r) => r.both_covered_count) },
    { label: "最好 / 中位位次", cell: (r) => ctx.el("td", { class: "kw-num",
      "data-sort": r.median_organic_rank ?? 9999,
      text: `${r.best_organic_rank ?? f.dash} / ${r.median_organic_rank ?? f.dash}` }) },
    { label: "证据条数", num: true, cell: num(ctx, (r) => r.evidence_count) },
    { label: "与上次比", cell: txt(ctx, (r) => r.delta ? deltaText(r.delta) : "首次盘点") },
  ];
  return foldBlock(ctx, {
    title: "关键词盘点记录",
    meta: runs.length ? `${runs.length} 次 · 最近 ${runs[runs.length - 1].run_date}` : "无记录",
    children: [
      ctx.el("p", { class: "kw-foldnote",
        text: "同一子体历次盘点，用来比较关键词状态的变化。柱是覆盖词数，"
          + "线是中位自然位（轴倒置，线在上面＝位置好）。" }),
      chartHost,
      table(ctx, { cols, rows: runs, empty: "这个子体还没有盘点记录" }),
    ],
  });
}

function deltaText(d) {
  const parts = [];
  const sign = (n) => (n > 0 ? "+" : "") + n;
  if (d.organic_covered) parts.push(`自然位 ${sign(d.organic_covered)}`);
  if (d.ad_covered) parts.push(`广告位 ${sign(d.ad_covered)}`);
  if (d.median_organic_rank) {
    parts.push(`中位位次 ${d.median_organic_rank > 0 ? "退" : "进"}`
      + `${Math.abs(d.median_organic_rank)} 位`);
  }
  if (d.unconfirmed) parts.push(`未确认 ${sign(d.unconfirmed)}`);
  return parts.length ? parts.join("，") : "无变化";
}

/* --------------------------------------- 子体清单（页面三入口） */

/* 子体清单。既是「重点子体清单」这个汇总页的正文，也是单对象盘点页
   还没选对象时的落地页（picker=true 时多给一句怎么选）。 */
export async function renderChildList(ctx, root, { picker = false } = {}) {
  const el = ctx.el;
  const d = await ctx.api("children");
  const f = ctx.fmt;
  const pmax = Math.max(1, ...d.rows.map((r) => r.pair_count || 0));
  const cols = [
    { label: "子 ASIN", cell: txt(ctx, (r) => r.child_asin, "kw-strong") },
    { label: "父体", cell: txt(ctx, (r) => r.parent_asin) },
    { label: "款号", cell: txt(ctx, (r) => r.style_no) },
    { label: "关系词数", num: true, cell: (r) => magnitudeCell(ctx, {
      value: r.pair_count, ratio: (r.pair_count || 0) / pmax, kind: "vol" }) },
    { label: "真实锚点占比", num: true, cell: (r) => heatCell(ctx, {
      text: r.pair_count ? f.pct(r.anchor_count / r.pair_count, 0) : f.dash,
      ratio: r.pair_count ? r.anchor_count / r.pair_count : 0, kind: "good",
      sort: r.pair_count ? r.anchor_count / r.pair_count : 0 }) },
    { label: "产品目标", cell: txt(ctx, (r) => r.product_goal_label) },
    { label: "主推关系", cell: txt(ctx, (r) => r.push_role_label) },
    { label: "库存承接", cell: txt(ctx, (r) => r.absorb_state_label) },
  ];
  const rows = d.rows.map((r) => ({ ...r, __open: r.child_asin }));
  root.replaceChildren(section(ctx, {
    title: picker ? "先选一个子 ASIN" : "重点子 ASIN 清单",
    note: picker
      ? "左侧对象栏切到「子 ASIN」点一条，或在下表里点行，即进入该子体的关键词盘点"
      : null,
    metrics: [
      ["重点子体", f.int(d.total)],
      ["排序", "按真实锚点数降序"],
      ["锚点来源", "客户头部与前十字段"],
      ["操作", "点行进入该子体的关键词盘点"],
    ],
    info: () => popBody(ctx, {
      title: "覆盖范围",
      paras: [
        "关键词盘点只覆盖这些重点子体，不是产品脊椎那 342 个。"
        + "覆盖率这类指标的分母要按这个数看。",
        "「真实锚点占比」是这个子体的关键词关系里有多少条能对上客户原始榜单字段 —— "
        + "占比低的子体，位次数字里构造成分更多。",
      ],
    }),
    table: table(ctx, {
      cols, rows, sortable: [3, 4],
      onRowOpen: (id) => ctx.open(id, "kw-asin"),
    }),
  }));
}
