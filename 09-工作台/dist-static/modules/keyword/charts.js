/* 关键词模块 · 图层
 *
 * 「每个板块必须有一张图」这条来自 09-页面承载体设计.md 第二层：
 * 表格是「给我看全部」，图是「告诉我该看哪个」，缺图就等于没有先后顺序。
 * 重构前关键词三页一共零张真图 —— 有几处 CSS 条形（等高细黑柱），
 * 在 182 天 × 66 词的密度下读不出任何趋势，那是占位不是图。
 *
 * echarts.min.js 放外壳 /assets/ 由各模块共用一份，不每个模块各带一份。
 *
 * G24：canvas 里画的字不继承 CSS，字体栈与字号必须在 JS 里镜像一份并显式注入，
 * 否则会落到浏览器默认 sans-serif —— 两边单独看都没问题，所以这是最容易漏的不一致。
 */

/* 与 tokens.css 的 --sans 逐字一致，**两边要一起改**。
   设计图用的是 SF Pro，而系统字体就是它，所以放最前；Plex/Inter 给非 macOS 兜底。 */
const FONT = '-apple-system, "SF Pro Text", BlinkMacSystemFont, "IBM Plex Sans", Inter, '
  + '"PingFang SC", "Microsoft YaHei", sans-serif';

/* 字号镜像。每一项都必须落在 tokens.css 的阶梯档位上（G24 逐个核对）。 */
const FS = {
  axis: 11,        // 轴刻度            --fs-axis
  anno: 12,        // 图上标注的日期    --fs-anno
  legend: 13,      // 图例、轴名        --fs-meta
  label: 13,       // 柱上/点上标注     --fs-meta
  tip: 14,         // tooltip 正文      --fs-body
};

/* 语义色。值与 tokens.css 逐字一致 —— canvas 吃不进 CSS 变量。 */
const C = {
  ink: "#111113",
  fg2: "#4a4a4e",
  fg3: "#6b6b73",
  line: "#e6e6e8",
  accent: "#2563eb",
  alert: "#c9372c",
  warn: "#a8620d",
  good: "#3a7d43",
  calm: "#6b4fa8",
  mute: "#c8c8cd",
};

let loading = null;

/* 有没有 DOM。图表必须有活元素才能画，而渲染态门禁（tests/test_keyword_render.mjs）
   在 Node 里用假 ctx 渲染整页、没有 document —— 没有这道守卫，
   图层的 document.createElement 会把整页渲染带崩，门禁报的错跟被测的事毫无关系。
   浏览器里 document 恒存在，所以这道守卫只在测试环境生效，不会掩盖真问题。 */
function hasDOM() {
  return typeof document !== "undefined" && !!document.createElement;
}

function loadECharts() {
  if (!hasDOM()) return Promise.reject(new Error("无 DOM 环境，不加载图表库"));
  if (typeof window !== "undefined" && window.echarts) return Promise.resolve(window.echarts);
  if (loading) return loading;
  loading = new Promise((resolve, reject) => {
    const tag = document.createElement("script");
    tag.src = "/assets/echarts.min.js";
    tag.onload = () => resolve(window.echarts);
    tag.onerror = () => reject(new Error("echarts.min.js 加载失败"));
    document.head.appendChild(tag);
  });
  return loading;
}

/* 每个挂载点最多一个实例。切对象 / 改筛选会重渲染，不 dispose 会泄漏并叠加。 */
const LIVE = new WeakMap();

function mountBox(host, height) {
  const prev = LIVE.get(host);
  if (prev) { try { prev.dispose(); } catch { /* 已被移除 */ } LIVE.delete(host); }
  host.textContent = "";
  const box = document.createElement("div");
  box.className = "kw-chartbox";
  box.style.height = `${height}px`;
  host.appendChild(box);
  return box;
}

/* 所有图共用的底座。tooltip / 轴 / 图例的字体字号只在这里给一次。 */
function baseOption(extra = {}) {
  return {
    textStyle: { fontFamily: FONT, fontSize: FS.axis, color: C.fg2 },
    animation: false,
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "shadow" },
      backgroundColor: "rgba(255,255,255,.97)",
      borderColor: C.line,
      borderWidth: 1,
      padding: [8, 10],
      textStyle: { fontFamily: FONT, fontSize: FS.tip, color: C.ink },
      extraCssText: "box-shadow:0 10px 30px rgba(9,9,11,.13);border-radius:10px",
    },
    ...extra,
  };
}

const axisCommon = {
  axisLine: { lineStyle: { color: C.line } },
  axisTick: { show: false },
  axisLabel: { fontFamily: FONT, fontSize: FS.axis, color: C.fg3 },
  splitLine: { lineStyle: { color: C.line, type: "dashed" } },
  nameTextStyle: { fontFamily: FONT, fontSize: FS.legend, color: C.fg3 },
};

async function render(host, height, build) {
  if (!hasDOM()) return null;
  let echarts;
  try {
    echarts = await loadECharts();
  } catch {
    host.textContent = "";
    host.appendChild(Object.assign(document.createElement("div"),
      { className: "kw-empty", textContent: "图表库没能加载，本块只给表格" }));
    return null;
  }
  const box = mountBox(host, height);
  const inst = echarts.init(box, null, { renderer: "canvas" });
  inst.setOption(build());
  LIVE.set(host, inst);
  if (typeof ResizeObserver === "function") {
    const ro = new ResizeObserver(() => inst.resize());
    ro.observe(box);
  }
  return inst;
}

/* ============================================ 1. 子体逐日自然位（页面三）

   主信息是当日平均自然位，位次越好线越高（y 轴反向）。
   不画五态堆叠柱：覆盖齐全的子体上 covered 占九成以上，整张图会是一片纯黑，
   看不出任何结构；这块要回答的问题是位置趋势。
   五态构成降为底部一条细带，采集失败日画成背景区间不占泳道。 */
export function dailyPositionChart(host, p) {
  const daily = p.daily || [];
  if (!daily.length) return Promise.resolve(null);
  const dates = daily.map((d) => d.date);
  const ranks = daily.map((d) => d.avg_organic_rank);
  const known = ranks.filter((v) => v != null);
  const lo = known.length ? Math.min(...known) : 1;
  const hi = known.length ? Math.max(...known) : 1;

  // 采集失败日：背景区间。逐日连成段，避免 90 个单日 markArea 把图压慢。
  const fails = new Set(p.collect_fail_days || []);
  const areas = [];
  let open = null;
  dates.forEach((d, i) => {
    if (fails.has(d) && open === null) open = i;
    if (!fails.has(d) && open !== null) { areas.push([open, i - 1]); open = null; }
    if (i === dates.length - 1 && open !== null) areas.push([open, i]);
  });

  const states = [
    ["有排名", "covered", C.ink],
    ["超出采集深度", "beyond_depth", C.warn],
    ["确认未覆盖", "not_covered", C.alert],
    ["当日采集失败", "collect_failed", C.calm],
    ["未纳入监控", "not_monitored", C.mute],
  ];

  return render(host, 268, () => ({
    ...baseOption({
      legend: {
        data: ["当日平均自然位", ...states.map((s) => s[0])],
        selected: states.reduce((a, s) => ({ ...a, [s[0]]: false }), {}),
        top: 0, right: 0, itemGap: 14, icon: "roundRect",
        itemWidth: 10, itemHeight: 10,
        textStyle: { fontFamily: FONT, fontSize: FS.legend, color: C.fg2 },
      },
    }),
    grid: [
      { left: 46, right: 16, top: 34, height: 150 },
      { left: 46, right: 16, top: 200, height: 34 },
    ],
    xAxis: [
      { ...axisCommon, type: "category", data: dates, gridIndex: 0,
        axisLabel: { ...axisCommon.axisLabel, show: false }, splitLine: { show: false } },
      { ...axisCommon, type: "category", data: dates, gridIndex: 1,
        splitLine: { show: false },
        axisLabel: { ...axisCommon.axisLabel, interval: Math.ceil(dates.length / 8) } },
    ],
    yAxis: [
      // 位次是反向量：第 1 位最好，所以 y 轴倒过来，线高 = 位置好。
      // 轴名放 start —— inverse 之后 start 是顶端，也就是「位次好」那一端；
      // 放默认位置会压在左下角的刻度标签上（第一版就是）。
      // 边界必须取整：lo/hi 是**平均**自然位（带小数），直接 hi+2 会让 ECharts
      // 把 19.3 当成一个刻度画出来 —— 位次没有零点几位。
      { ...axisCommon, type: "value", inverse: true, gridIndex: 0,
        min: Math.max(1, Math.floor(lo) - 2), max: Math.ceil(hi) + 2, minInterval: 1,
        axisLabel: { ...axisCommon.axisLabel, formatter: (v) => `第${v}` } },
      { ...axisCommon, type: "value", gridIndex: 1,
        axisLabel: { show: false }, splitLine: { show: false } },
    ],
    series: [
      { name: "当日平均自然位", type: "line", xAxisIndex: 0, yAxisIndex: 0,
        data: ranks, showSymbol: false, connectNulls: false,
        lineStyle: { width: 1.8, color: C.ink },
        areaStyle: { color: "rgba(17,17,19,.05)" },
        markArea: areas.length ? {
          silent: true,
          itemStyle: { color: "rgba(107,79,168,.10)" },
          data: areas.map(([a, b]) => ([{ xAxis: dates[a] }, { xAxis: dates[b] }])),
        } : undefined,
      },
      ...states.map(([label, key, color]) => ({
        name: label, type: "bar", stack: "st", xAxisIndex: 1, yAxisIndex: 1,
        data: daily.map((d) => d[key] || 0),
        itemStyle: { color }, barWidth: "96%", silent: true,
      })),
    ],
  }));
}

/* ============================== 2. 词组变化双向条形（页面一 · 市场需求）

   上涨向右、下滑向左，同一条基线。19 行 × 9 列的表读不出「哪个需求在动」，
   这张图三秒就给出来。

   只画上涨与下滑两个方向。第一版把「竞争加剧」也堆进来，它没有方向语义，
   堆在上涨那一侧会被读成「上涨的一部分」，橙条压在绿条上分不清 ——
   竞争加剧留在表格里做一列。 */
export function groupChangeChart(host, groups) {
  const rows = (groups || []).filter((g) => g.up || g.down)
    .sort((a, b) => (b.up + b.down) - (a.up + a.down)).slice(0, 12).reverse();
  if (!rows.length) return Promise.resolve(null);
  return render(host, Math.max(200, rows.length * 24 + 62), () => ({
    ...baseOption({
      legend: { data: ["上涨", "下滑"], top: 0, right: 0,
        itemWidth: 10, itemHeight: 10, icon: "roundRect",
        textStyle: { fontFamily: FONT, fontSize: FS.legend, color: C.fg2 } },
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" },
        backgroundColor: "rgba(255,255,255,.97)", borderColor: C.line, borderWidth: 1,
        textStyle: { fontFamily: FONT, fontSize: FS.tip, color: C.ink },
        extraCssText: "box-shadow:0 10px 30px rgba(9,9,11,.13);border-radius:10px",
        valueFormatter: (v) => String(Math.abs(v)) },
    }),
    grid: { left: 4, right: 24, top: 32, bottom: 26, containLabel: true },
    xAxis: { ...axisCommon, type: "value",
      axisLabel: { ...axisCommon.axisLabel, formatter: (v) => String(Math.abs(v)) } },
    yAxis: { ...axisCommon, type: "category", data: rows.map((g) => g.group_name),
      splitLine: { show: false }, axisLabel: { ...axisCommon.axisLabel, width: 132,
        overflow: "truncate" } },
    series: [
      { name: "上涨", type: "bar", stack: "a", data: rows.map((g) => g.up),
        itemStyle: { color: C.good }, barWidth: 12 },
      { name: "下滑", type: "bar", stack: "a", data: rows.map((g) => -g.down),
        itemStyle: { color: C.alert }, barWidth: 12 },
    ],
  }));
}

/* ======================= 3. 核心词位次变化散点（页面一 · 自有核心词）

   x = 变化前位次，y = 变化后位次，两轴同尺度并画一条对角线。
   点落在对角线上 = 没变；落在线下方 = 位次变差（数字变大）。
   偏离对角线的垂直距离就是变动幅度 —— 16 行「自然位上涨 / 下降」的表读不出这件事。 */
export function rankShiftScatter(host, events) {
  const pts = (events || []).filter((e) => e.from_rank && e.to_rank);
  if (pts.length < 3) return Promise.resolve(null);
  const all = pts.flatMap((e) => [e.from_rank, e.to_rank]);
  const max = Math.max(...all, 10);
  const worse = pts.filter((e) => e.to_rank > e.from_rank);
  const better = pts.filter((e) => e.to_rank <= e.from_rank);
  const pack = (list) => list.map((e) => ({
    value: [e.from_rank, e.to_rank],
    name: `${e.keyword}　${e.child_asin || ""}`,
  }));
  return render(host, 300, () => ({
    ...baseOption({
      legend: { data: ["位置变差", "位置变好"], top: 0, right: 0,
        itemWidth: 10, itemHeight: 10, icon: "circle",
        textStyle: { fontFamily: FONT, fontSize: FS.legend, color: C.fg2 } },
      tooltip: {
        trigger: "item",
        backgroundColor: "rgba(255,255,255,.97)", borderColor: C.line, borderWidth: 1,
        textStyle: { fontFamily: FONT, fontSize: FS.tip, color: C.ink },
        extraCssText: "box-shadow:0 10px 30px rgba(9,9,11,.13);border-radius:10px",
        formatter: (o) => `${o.data.name}<br/>第 ${o.value[0]} 位 → 第 ${o.value[1]} 位`,
      },
    }),
    grid: { left: 10, right: 42, top: 38, bottom: 34, containLabel: true },
    // 两个轴名分置：x 放右端、y 放顶端。都用默认位置会一起挤在左下角，
    // 而 y 轴是 inverse 的，"end" 恰好也是底部 —— 第一版两个轴名压在了一起。
    xAxis: { ...axisCommon, type: "value", name: "变化前", min: 1, max,
      nameLocation: "end", nameGap: 8,
      axisLabel: { ...axisCommon.axisLabel, formatter: (v) => `第${v}` } },
    yAxis: { ...axisCommon, type: "value", name: "变化后", min: 1, max, inverse: true,
      nameLocation: "start", nameGap: 12,
      axisLabel: { ...axisCommon.axisLabel, formatter: (v) => `第${v}` } },
    series: [
      { name: "位置变差", type: "scatter", symbolSize: 9, data: pack(worse),
        itemStyle: { color: C.alert, opacity: 0.75 },
        markLine: {
          silent: true, symbol: "none",
          lineStyle: { color: C.fg3, type: "dashed", width: 1 },
          label: { show: true, formatter: "没有变化", position: "middle",
            fontFamily: FONT, fontSize: FS.anno, color: C.fg3,
            backgroundColor: "rgba(255,255,255,.9)", padding: [2, 4] },
          data: [[{ coord: [1, 1] }, { coord: [max, max] }]],
        },
      },
      { name: "位置变好", type: "scatter", symbolSize: 9, data: pack(better),
        itemStyle: { color: C.good, opacity: 0.75 } },
    ],
  }));
}

/* ============================ 4. 词库需求散点（页面二 · 市场关键词比较区）

   x = 月搜索量（对数），y = 需供比，点径 = 在售商品数。
   200 行 × 10 列的表回答不了「哪些词高需求低竞争」，这张图的右下角就是答案区。 */
export function demandScatter(host, terms, { onPick } = {}) {
  const pts = (terms || []).filter((t) =>
    t.monthly_search_volume > 0 && t.demand_supply_ratio != null);
  if (pts.length < 5) return Promise.resolve(null);
  const counts = pts.map((t) => t.product_count || 0);
  const cmax = Math.max(...counts, 1);
  const ROLE = { 核心词: C.ink, 探索词: C.accent, 长尾词: C.calm, 待验证词: C.warn };
  const byRole = new Map();
  for (const t of pts) {
    const r = t.operator_role_label || "未定角色";
    if (!byRole.has(r)) byRole.set(r, []);
    byRole.get(r).push(t);
  }
  return render(host, 320, () => ({
    ...baseOption({
      legend: { data: [...byRole.keys()], top: 0, right: 0,
        itemWidth: 10, itemHeight: 10, icon: "circle",
        textStyle: { fontFamily: FONT, fontSize: FS.legend, color: C.fg2 } },
      tooltip: {
        trigger: "item",
        backgroundColor: "rgba(255,255,255,.97)", borderColor: C.line, borderWidth: 1,
        textStyle: { fontFamily: FONT, fontSize: FS.tip, color: C.ink },
        extraCssText: "box-shadow:0 10px 30px rgba(9,9,11,.13);border-radius:10px",
        formatter: (o) => {
          const t = o.data.raw;
          return `<b>${t.keyword}</b><br/>月搜索量 ${Math.round(t.monthly_search_volume)
            .toLocaleString("zh-CN")}<br/>需供比 ${Number(t.demand_supply_ratio).toFixed(2)}`
            + `<br/>在售商品数 ${Math.round(t.product_count || 0).toLocaleString("zh-CN")}`;
        },
      },
    }),
    grid: { left: 8, right: 20, top: 34, bottom: 30, containLabel: true },
    // 搜索量跨三个数量级（1.7 万 ~ 170 万），线性轴会把九成的点挤在左边一条竖线上。
    xAxis: { ...axisCommon, type: "log", name: "月搜索量", logBase: 10,
      axisLabel: { ...axisCommon.axisLabel,
        formatter: (v) => (v >= 10000 ? `${Math.round(v / 10000)}万` : String(v)) } },
    yAxis: { ...axisCommon, type: "value", name: "需供比" },
    series: [...byRole].map(([role, list]) => ({
      name: role, type: "scatter",
      data: list.map((t) => ({
        value: [t.monthly_search_volume, t.demand_supply_ratio],
        raw: t, id: t.keyword_id,
      })),
      symbolSize: (v, p) => 6 + Math.sqrt((p.data.raw.product_count || 0) / cmax) * 16,
      itemStyle: { color: ROLE[role] || C.fg3, opacity: 0.62 },
    })),
  })).then((inst) => {
    if (inst && onPick) {
      inst.on("click", (e) => { if (e.data && e.data.id) onPick(e.data.id); });
    }
    return inst;
  });
}

/* ============================== 5. 单词双频率序列（页面二 · 单词深研）

   柱 = 量，线 = 比率或排名，双轴。原来是 CSS 柱 + 绝对定位圆点，
   标题得写清「哪个是柱哪个是点」才不被读反 —— 有真轴就不用靠标题解释。
   叠加轴一律 min:0（要则第六节）：不从 0 起会把只波动 1.5% 的线画成大起大落。 */
export function termSeriesChart(host, series, {
  barKey, barLabel, lineKey, lineLabel, invertLine, height = 236,
} = {}) {
  const rows = (series || []).filter((s) => s[barKey] != null || s[lineKey] != null);
  if (rows.length < 2) return Promise.resolve(null);
  return render(host, height, () => ({
    ...baseOption({
      legend: { data: [barLabel, lineLabel], top: 0, right: 0,
        itemWidth: 10, itemHeight: 10,
        textStyle: { fontFamily: FONT, fontSize: FS.legend, color: C.fg2 } },
    }),
    grid: { left: 8, right: 8, top: 34, bottom: 24, containLabel: true },
    xAxis: { ...axisCommon, type: "category", data: rows.map((s) => s.period_end),
      splitLine: { show: false } },
    yAxis: [
      { ...axisCommon, type: "value", min: 0,
        axisLabel: { ...axisCommon.axisLabel,
          formatter: (v) => (v >= 10000 ? `${(v / 10000).toFixed(0)}万` : String(v)) } },
      { ...axisCommon, type: "value", min: 0, inverse: !!invertLine,
        splitLine: { show: false } },
    ],
    series: [
      { name: barLabel, type: "bar", yAxisIndex: 0, barWidth: "58%",
        data: rows.map((s) => s[barKey]),
        itemStyle: { color: "rgba(17,17,19,.82)" } },
      { name: lineLabel, type: "line", yAxisIndex: 1, smooth: false,
        data: rows.map((s) => s[lineKey]), symbolSize: 5,
        lineStyle: { width: 1.8, color: C.accent },
        itemStyle: { color: C.accent } },
    ],
  }));
}

/* ============================ 6. 两来源分歧哑铃图（页面二 · 单词深研）

   两个点一条线，线长就是分歧幅度。原来是四列表格加「一致 / 不一致」文字，
   看得出有没有分歧，看不出哪个指标分歧最大。

   量纲差几个数量级，所以每行各自归一 —— 但基准取的是**两值的均值**，不是最大值。
   取最大值时较大的那一个恒等于 1.0，于是九行里七行的点全堆在右端、左边七成画布空着
   （第一版就是这样）。以均值为 1.0 之后：两来源一致的行两点重合在中线，
   分歧的行朝两侧对称张开，张开量就是分歧率。行内可比，行间不比。 */
export function dumbbellChart(host, compare) {
  const rows = (compare || []).filter((c) => c.primary != null && c.second != null);
  if (!rows.length) return Promise.resolve(null);
  const norm = rows.map((c) => {
    const a = Number(c.primary), b = Number(c.second);
    const mean = (Math.abs(a) + Math.abs(b)) / 2 || 1;
    return { metric: c.metric, a: a / mean, b: b / mean, ra: a, rb: b, conflict: c.conflict };
  }).reverse();
  // 轴范围按实际最大偏离撑开，至少留 ±6% 否则全一致时轴会退化成一个点
  const dev = Math.max(0.06, ...norm.map((r) => Math.max(
    Math.abs(r.a - 1), Math.abs(r.b - 1))));
  const pad = dev * 1.35;
  return render(host, Math.max(210, norm.length * 26 + 62), () => ({
    ...baseOption({
      legend: { data: ["关键词3", "关键词2"], top: 0, right: 0,
        itemWidth: 10, itemHeight: 10, icon: "circle",
        textStyle: { fontFamily: FONT, fontSize: FS.legend, color: C.fg2 } },
      tooltip: {
        trigger: "axis", axisPointer: { type: "shadow" },
        backgroundColor: "rgba(255,255,255,.97)", borderColor: C.line, borderWidth: 1,
        textStyle: { fontFamily: FONT, fontSize: FS.tip, color: C.ink },
        extraCssText: "box-shadow:0 10px 30px rgba(9,9,11,.13);border-radius:10px",
        formatter: (ps) => {
          const r = norm[ps[0].dataIndex];
          const gap = r.rb === 0 ? null : Math.abs(r.ra - r.rb) / Math.abs(r.rb);
          return `<b>${r.metric}</b><br/>关键词3 ${r.ra}<br/>关键词2 ${r.rb}`
            + (r.conflict
              ? `<br/>相差 ${gap == null ? "—" : (gap * 100).toFixed(1) + "%"}`
                + "，并列保留不合并"
              : "<br/>两来源一致");
        },
      },
    }),
    grid: { left: 4, right: 30, top: 34, bottom: 12, containLabel: true },
    // 归一后的相对位置。中线 1.0 = 两来源均值，刻度本身没有业务含义，故不给标签。
    xAxis: { ...axisCommon, type: "value", min: 1 - pad, max: 1 + pad,
      axisLabel: { show: false }, axisLine: { show: false },
      splitLine: { show: false } },
    yAxis: { ...axisCommon, type: "category", data: norm.map((r) => r.metric),
      splitLine: { show: false } },
    series: [
      // 连线：两端同 y 不同 x，线长即分歧幅度
      { name: "分歧", type: "custom", silent: true,
        renderItem: (params, api) => {
          const i = params.dataIndex;
          const y = api.coord([1, i])[1];
          const x1 = api.coord([norm[i].a, i])[0];
          const x2 = api.coord([norm[i].b, i])[0];
          return {
            type: "line",
            shape: { x1: Math.min(x1, x2), y1: y, x2: Math.max(x1, x2), y2: y },
            style: { stroke: norm[i].conflict ? C.warn : C.line, lineWidth: 2 },
          };
        },
        data: norm.map((r) => [r.a, r.b]),
        markLine: {
          silent: true, symbol: "none",
          lineStyle: { color: C.line, type: "dashed", width: 1 },
          label: { show: false },
          data: [{ xAxis: 1 }],
        },
      },
      { name: "关键词3", type: "scatter", symbolSize: 10,
        data: norm.map((r) => r.a), itemStyle: { color: C.ink } },
      { name: "关键词2", type: "scatter", symbolSize: 10,
        data: norm.map((r) => r.b), itemStyle: { color: C.calm } },
    ],
  }));
}

/* ======================== 7. 词组缺口条形（页面二/三 · 覆盖结构）

   缺口 = 组内监控词 − 本子体相关。按缺口降序，配一条覆盖率折线在次轴。
   回答「先补哪个需求词组」。 */
export function gapBarChart(host, groups, { limit = 12 } = {}) {
  const rows = (groups || []).filter((g) => g.gap > 0)
    .sort((a, b) => b.gap - a.gap).slice(0, limit);
  if (!rows.length) return Promise.resolve(null);
  return render(host, Math.max(230, rows.length * 24 + 96), () => ({
    ...baseOption({
      // 图例右置：左置会压在 y 轴第一个刻度标签上（第一版「缺口词数」压住了「50」）。
      legend: { data: ["缺口词数", "组内覆盖率"], top: 0, right: 0,
        itemWidth: 10, itemHeight: 10,
        textStyle: { fontFamily: FONT, fontSize: FS.legend, color: C.fg2 } },
    }),
    grid: { left: 4, right: 16, top: 34, bottom: 46, containLabel: true },
    xAxis: { ...axisCommon, type: "category", data: rows.map((g) => g.group_name),
      splitLine: { show: false },
      axisLabel: { ...axisCommon.axisLabel, rotate: 28, width: 108,
        overflow: "truncate", hideOverlap: false } },
    yAxis: [
      { ...axisCommon, type: "value", min: 0, minInterval: 1 },
      { ...axisCommon, type: "value", min: 0, max: 1,
        splitLine: { show: false },
        axisLabel: { ...axisCommon.axisLabel,
          formatter: (v) => `${Math.round(v * 100)}%` } },
    ],
    series: [
      { name: "缺口词数", type: "bar", barWidth: "52%", yAxisIndex: 0,
        data: rows.map((g) => g.gap), itemStyle: { color: C.warn } },
      { name: "组内覆盖率", type: "line", yAxisIndex: 1, symbolSize: 5,
        data: rows.map((g) => g.group_reach),
        lineStyle: { width: 1.6, color: C.good }, itemStyle: { color: C.good } },
    ],
  }));
}

/* ============================ 8. 盘点记录趋势（页面三 · 追溯段）

   三次盘点的覆盖数与中位位次。10 列纯数字表读不出「在变好还是变差」。 */
export function auditTrendChart(host, runs) {
  const rows = runs || [];
  if (rows.length < 2) return Promise.resolve(null);
  return render(host, 200, () => ({
    ...baseOption({
      legend: { data: ["有自然位", "双覆盖", "中位自然位"], top: 0, right: 0,
        itemWidth: 10, itemHeight: 10,
        textStyle: { fontFamily: FONT, fontSize: FS.legend, color: C.fg2 } },
    }),
    grid: { left: 8, right: 8, top: 34, bottom: 22, containLabel: true },
    xAxis: { ...axisCommon, type: "category", data: rows.map((r) => r.run_date),
      splitLine: { show: false } },
    yAxis: [
      { ...axisCommon, type: "value", min: 0, minInterval: 1 },
      { ...axisCommon, type: "value", min: 0, inverse: true, minInterval: 1,
        splitLine: { show: false } },
    ],
    series: [
      { name: "有自然位", type: "bar", barWidth: "26%", yAxisIndex: 0,
        data: rows.map((r) => r.organic_covered_count),
        itemStyle: { color: "rgba(17,17,19,.82)" } },
      { name: "双覆盖", type: "bar", barWidth: "26%", yAxisIndex: 0,
        data: rows.map((r) => r.both_covered_count), itemStyle: { color: C.good } },
      { name: "中位自然位", type: "line", yAxisIndex: 1, symbolSize: 6,
        data: rows.map((r) => r.median_organic_rank),
        lineStyle: { width: 1.8, color: C.accent }, itemStyle: { color: C.accent } },
    ],
  }));
}

/* 14 天流量迷你趋势（页面一结论区）。不要轴不要图例。

   用柱不用折线：14 个点的折线在这个高度上几乎是一条平线，配 areaStyle 之后
   整块变成一片灰色色块 —— 第一版就是这样，看着像页面坏了。
   柱能读出「14 天」这个粒度，也读得出哪天高哪天低。
   基线不从 0 起而是从最小值下探一点：这里要看的是日间相对起伏，不是绝对量级。 */
export function trafficSpark(host, reports) {
  const rows = (reports || []).slice().reverse();
  if (rows.length < 3) return Promise.resolve(null);
  const vals = rows.map((r) => r.traffic_proxy_value || 0);
  const lo = Math.min(...vals);
  const hi = Math.max(...vals);
  const floor = Math.max(0, lo - (hi - lo) * 0.6);
  const last = vals.length - 1;
  return render(host, 52, () => ({
    ...baseOption({
      tooltip: {
        trigger: "axis", axisPointer: { type: "shadow" },
        backgroundColor: "rgba(255,255,255,.97)", borderColor: C.line, borderWidth: 1,
        textStyle: { fontFamily: FONT, fontSize: FS.tip, color: C.ink },
        extraCssText: "box-shadow:0 10px 30px rgba(9,9,11,.13);border-radius:10px",
        formatter: (ps) => `${ps[0].axisValue}　${Math.round(ps[0].value)
          .toLocaleString("zh-CN")}`,
      },
    }),
    grid: { left: 0, right: 0, top: 6, bottom: 2 },
    xAxis: { type: "category", data: rows.map((r) => r.report_date), show: false },
    yAxis: { type: "value", show: false, min: floor, max: hi },
    series: [{
      type: "bar", barWidth: "62%",
      data: vals.map((v, i) => ({
        value: v,
        // 最新一天染深色：这一屏的主数字就是它，图上要能对上。
        itemStyle: { color: i === last ? C.ink : "rgba(17,17,19,.24)",
          borderRadius: [2, 2, 0, 0] },
      })),
    }],
  }));
}

export function disposeAll(hosts) {
  for (const h of hosts || []) {
    const inst = LIVE.get(h);
    if (inst) { try { inst.dispose(); } catch { /* 已移除 */ } LIVE.delete(h); }
  }
}

/* ==================== 9. 通用「柱 + 线」图（页面二 · 词组结构等）

   两个量纲共处一图的标准形状：柱给规模，线给比率或计数。
   叠加轴一律 min:0（要则第六节）。 */
export function barLineChart(host, rows, {
  catKey, barKey, barLabel, lineKey, lineLabel, lineIsPct, barColor,
  rotate = 0, height, limit = 14,
} = {}) {
  const data = (rows || []).slice(0, limit);
  if (data.length < 2) return Promise.resolve(null);
  const h = height || Math.max(210, data.length * 20 + 76);
  return render(host, h, () => ({
    ...baseOption({
      legend: { data: [barLabel, lineLabel].filter(Boolean), top: 0, right: 0,
        itemWidth: 10, itemHeight: 10,
        textStyle: { fontFamily: FONT, fontSize: FS.legend, color: C.fg2 } },
    }),
    grid: { left: 4, right: 16, top: 32, bottom: rotate ? 30 : 22, containLabel: true },
    xAxis: { ...axisCommon, type: "category", data: data.map((r) => r[catKey]),
      splitLine: { show: false },
      axisLabel: { ...axisCommon.axisLabel, rotate, width: 100, overflow: "truncate" } },
    yAxis: [
      { ...axisCommon, type: "value", min: 0,
        axisLabel: { ...axisCommon.axisLabel,
          formatter: (v) => (v >= 10000 ? `${(v / 10000).toFixed(0)}万` : String(v)) } },
      lineKey ? { ...axisCommon, type: "value", min: 0,
        max: lineIsPct ? 1 : null, splitLine: { show: false },
        axisLabel: { ...axisCommon.axisLabel,
          formatter: (v) => (lineIsPct ? `${Math.round(v * 100)}%` : String(v)) } } : null,
    ].filter(Boolean),
    series: [
      { name: barLabel, type: "bar", barWidth: "54%", yAxisIndex: 0,
        data: data.map((r) => r[barKey]),
        itemStyle: { color: barColor || "rgba(17,17,19,.82)" } },
      lineKey ? { name: lineLabel, type: "line", yAxisIndex: 1, symbolSize: 5,
        data: data.map((r) => r[lineKey]),
        lineStyle: { width: 1.6, color: C.accent }, itemStyle: { color: C.accent } } : null,
    ].filter(Boolean),
  }));
}

/* =============== 10. 横向占比条形（页面二 · 头部 ASIN 点击共享）

   两个 series 用**固定色**，不按「是否自有」逐条改色。
   第一版按自有染色（自有绿 / 外部黑），而 legend 取的是 series 默认色（ECharts 自动分蓝绿）
   —— 于是图例说「点击共享」是蓝色，图上的条却是黑的，图例在撒谎。
   「头部里有没有我」由 y 轴标签的「·自有」和指标条里的「其中自有产品」回答，
   不需要靠颜色再说一遍。 */
export function shareBarChart(host, rows, { height } = {}) {
  const data = (rows || []).filter((r) => r.click_share != null);
  if (!data.length) return Promise.resolve(null);
  const list = data.slice().reverse();
  return render(host, height || Math.max(160, list.length * 30 + 58), () => ({
    ...baseOption({
      legend: { data: ["点击共享", "转化共享"], top: 0, right: 0,
        itemWidth: 10, itemHeight: 10, icon: "roundRect",
        textStyle: { fontFamily: FONT, fontSize: FS.legend, color: C.fg2 } },
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" },
        backgroundColor: "rgba(255,255,255,.97)", borderColor: C.line, borderWidth: 1,
        textStyle: { fontFamily: FONT, fontSize: FS.tip, color: C.ink },
        extraCssText: "box-shadow:0 10px 30px rgba(9,9,11,.13);border-radius:10px",
        valueFormatter: (v) => `${(Number(v) * 100).toFixed(2)}%` },
    }),
    grid: { left: 4, right: 40, top: 34, bottom: 16, containLabel: true },
    xAxis: { ...axisCommon, type: "value", min: 0,
      axisLabel: { ...axisCommon.axisLabel,
        formatter: (v) => `${(v * 100).toFixed(0)}%` } },
    yAxis: { ...axisCommon, type: "category", splitLine: { show: false },
      data: list.map((r) => `${r.rank_slot}. ${r.asin}${r.is_own_asin ? " ·自有" : ""}`) },
    series: [
      { name: "点击共享", type: "bar", barWidth: 11,
        itemStyle: { color: "rgba(17,17,19,.82)" },
        data: list.map((r) => r.click_share) },
      { name: "转化共享", type: "bar", barWidth: 6,
        itemStyle: { color: C.mute },
        data: list.map((r) => r.conversion_share) },
    ],
  }));
}

