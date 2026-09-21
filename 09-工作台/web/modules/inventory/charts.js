/* 库存模块 · 异常总览与库存全览的图层
 *
 * 这两页原来是「四个等权数字 + 一张纯数字表 + 三列 dt/dd」，看得出大小、
 * 看不出结构。2026-09-04 按 11-页面框架与决策/Image2-视觉灵感 的参考图重做。
 *
 * **所有交叉表都从 children 载荷的 rows 逐行算出来，不是编的。**
 * rows 每行带 primary_risk / primary_severity / capacity_level / confidence /
 * risk_qty / style_no / cover_days，所以「风险类型 × 严重度」和
 * 「严重度 × 承接能力」都是真交叉。overview.by_risk_type 里只有边缘分布
 * （每类的对象数与影响件数），拿它拼不出交叉 —— 那才是要编的。
 *
 * 一个口径必须说清：严重度是**主风险**那一条的严重度（primary_severity），
 * 不是每一类风险各自的严重度。所以堆叠按「主风险分类」，标题里写明，
 * 否则一个同时命中两类风险的对象会被算两次、且第二类的严重度是借来的。
 *
 * echarts.min.js 放外壳 /assets/ 由各模块共用一份。
 * G24：canvas 里的字不继承 CSS，字体栈与字号必须在 JS 里镜像并显式注入。
 */

/* 与 tokens.css 的 --sans、以及 daychart.js 的 FONT 逐字一致，三处要一起改。 */
const FONT = '-apple-system, "SF Pro Text", BlinkMacSystemFont, "IBM Plex Sans", Inter, '
  + '"PingFang SC", "Microsoft YaHei", sans-serif';

/* 字号镜像。每一项都必须落在 tokens.css 的阶梯档位上（G24 逐个核对）。 */
const FS = {
  axis: 11,      // 轴刻度        --fs-axis
  legend: 13,    // 图例、轴名    --fs-meta
  label: 13,     // 格子里的数    --fs-meta
  tip: 14,       // tooltip 正文  --fs-body
};

/* 语义色，值与 tokens.css 逐字一致 —— canvas 吃不进 CSS 变量。 */
const C = {
  ink: '#111113',
  fg2: '#4a4a4e',
  fg3: '#6b6b73',
  line: '#e6e6e8',
  accent: '#2563eb',
  alert: '#c9372c',
  warn: '#a8620d',
  good: '#3a7d43',
  calm: '#6b4fa8',
  mute: '#c8c8cd',
};

const SEV = [
  ['high', '高', C.alert],
  ['medium', '中', C.warn],
  ['low', '低', C.mute],
];
/* 承接能力的档位顺序照库存模块自己的判断，不另立一套（util.js 的 CAP_LABEL）。 */
const CAP = [
  ['can_absorb', '可承接'],
  ['limited', '有限承接'],
  ['cannot_absorb', '不可承接'],
  ['unknown', '无法判断'],
  ['unavailable', '缺库存快照'],
];

let loading = null;
const LIVE = new WeakMap();

function hasDOM() {
  return typeof document !== 'undefined' && !!document.createElement;
}

function loadECharts() {
  if (!hasDOM()) return Promise.reject(new Error('无 DOM 环境'));
  if (typeof window !== 'undefined' && window.echarts) return Promise.resolve(window.echarts);
  if (loading) return loading;
  loading = new Promise((resolve, reject) => {
    const tag = document.createElement('script');
    tag.src = '/assets/echarts.min.js';
    tag.onload = () => resolve(window.echarts);
    tag.onerror = () => reject(new Error('echarts.min.js 加载失败'));
    document.head.appendChild(tag);
  });
  return loading;
}

async function mount(host, height, build) {
  if (!host || !hasDOM()) return null;
  let echarts;
  try {
    echarts = await loadECharts();
  } catch {
    host.textContent = '图表库没能加载，本块只给表格';
    return null;
  }
  const prev = LIVE.get(host);
  if (prev) { try { prev.dispose(); } catch { /* 已移除 */ } LIVE.delete(host); }
  host.textContent = '';
  const box = document.createElement('div');
  box.style.height = `${height}px`;
  host.appendChild(box);
  const inst = echarts.init(box, null, { renderer: 'canvas' });
  inst.setOption(build());
  LIVE.set(host, inst);
  if (typeof ResizeObserver === 'function') new ResizeObserver(() => inst.resize()).observe(box);
  return inst;
}

const tip = (extra = {}) => ({
  backgroundColor: 'rgba(255,255,255,.97)',
  borderColor: C.line,
  borderWidth: 1,
  padding: [8, 10],
  textStyle: { fontFamily: FONT, fontSize: FS.tip, color: C.ink },
  extraCssText: 'box-shadow:0 10px 30px rgba(9,9,11,.13);border-radius:10px',
  ...extra,
});

const axisCommon = {
  axisLine: { lineStyle: { color: C.line } },
  axisTick: { show: false },
  axisLabel: { fontFamily: FONT, fontSize: FS.axis, color: C.fg3 },
  splitLine: { lineStyle: { color: C.line, type: 'dashed' } },
};

const base = (extra = {}) => ({
  textStyle: { fontFamily: FONT, fontSize: FS.axis, color: C.fg2 },
  animation: false,
  ...extra,
});

const wan = (v) => (v >= 10000 ? `${(v / 10000).toFixed(1)}万` : String(v));

/* ============ 1. 各主风险类型影响件数（按严重度堆叠，降序） ============

   x = 影响件数，y = 主风险类型，段 = 该对象主风险的严重度。
   原来这块是一张「风险类型 / 子ASIN / 占比 / 影响件数」四列表 ——
   看得出哪类多，看不出哪类里有多少是高危。 */
export function riskSeverityBars(host, rows, riskLabels) {
  const agg = new Map();
  for (const r of rows || []) {
    const k = r.primary_risk;
    if (!k) continue;
    if (!agg.has(k)) agg.set(k, { high: 0, medium: 0, low: 0, total: 0 });
    const qty = (r.risk_qty && r.risk_qty[k]) || 0;
    const sev = SEV.some((s) => s[0] === r.primary_severity) ? r.primary_severity : 'low';
    const a = agg.get(k);
    a[sev] += qty;
    a.total += qty;
  }
  const list = [...agg.entries()].sort((a, b) => a[1].total - b[1].total);
  if (!list.length) return Promise.resolve(null);
  const cats = list.map(([k]) => (riskLabels && riskLabels[k]) || k);
  return mount(host, Math.max(210, list.length * 34 + 74), () => ({
    ...base({
      legend: {
        data: SEV.map((s) => s[1]), top: 0, right: 0,
        itemWidth: 10, itemHeight: 10, icon: 'roundRect',
        textStyle: { fontFamily: FONT, fontSize: FS.legend, color: C.fg2 },
      },
      tooltip: tip({ trigger: 'axis', axisPointer: { type: 'shadow' },
        valueFormatter: (v) => `${Math.round(v).toLocaleString('zh-CN')} 件` }),
    }),
    grid: { left: 4, right: 56, top: 34, bottom: 22, containLabel: true },
    xAxis: { ...axisCommon, type: 'value',
      axisLabel: { ...axisCommon.axisLabel, formatter: wan } },
    yAxis: { ...axisCommon, type: 'category', data: cats, splitLine: { show: false } },
    series: SEV.map(([key, label, color], i) => ({
      name: label, type: 'bar', stack: 'sev', barWidth: 14,
      itemStyle: { color },
      data: list.map(([, a]) => a[key]),
      // 合计标在最后一段的末端，省掉参考图里那一列「影响件数（件）」
      label: i === SEV.length - 1 ? {
        show: true, position: 'right', fontFamily: FONT, fontSize: FS.label,
        color: C.fg2,
        formatter: (p) => Math.round(list[p.dataIndex][1].total).toLocaleString('zh-CN'),
      } : { show: false },
    })),
  }));
}

/* ============ 2. 严重度 × 承接能力矩阵（子 ASIN 数量） ============

   真交叉表：逐行数 primary_severity × capacity_level。
   回答的是「高危里有多少是根本吃不下的」—— 两个边缘分布并排永远答不了这个。 */
export function severityCapacityHeatmap(host, rows) {
  const caps = CAP.filter(([k]) => (rows || []).some((r) => r.capacity_level === k));
  if (!caps.length) return Promise.resolve(null);
  const cells = [];
  let max = 0;
  SEV.forEach(([sk], yi) => {
    caps.forEach(([ck], xi) => {
      const n = (rows || []).filter((r) =>
        r.primary_severity === sk && r.capacity_level === ck).length;
      cells.push([xi, yi, n]);
      if (n > max) max = n;
    });
  });
  return mount(host, Math.max(210, SEV.length * 46 + 96), () => ({
    ...base({
      tooltip: tip({
        formatter: (o) => `${SEV[o.value[1]][1]}危 · ${caps[o.value[0]][1]}<br/>`
          + `${o.value[2]} 个子 ASIN`,
      }),
    }),
    grid: { left: 4, right: 8, top: 10, bottom: 58, containLabel: true },
    xAxis: { type: 'category', data: caps.map((c) => c[1]),
      axisLine: { show: false }, axisTick: { show: false }, splitArea: { show: true },
      axisLabel: { fontFamily: FONT, fontSize: FS.axis, color: C.fg3 } },
    yAxis: { type: 'category', data: SEV.map((s) => s[1]),
      axisLine: { show: false }, axisTick: { show: false }, splitArea: { show: true },
      axisLabel: { fontFamily: FONT, fontSize: FS.axis, color: C.fg3 } },
    // 色阶用墨色浓度而不是彩虹：格子里的数是「多少个」，不是好坏
    visualMap: {
      min: 0, max: Math.max(1, max), calculable: false, orient: 'horizontal',
      left: 'center', bottom: 0, itemHeight: 70, itemWidth: 10,
      text: ['多', '少'],
      textStyle: { fontFamily: FONT, fontSize: FS.axis, color: C.fg3 },
      inRange: { color: ['#f4f4f5', 'rgba(17,17,19,.78)'] },
    },
    series: [{
      type: 'heatmap', data: cells,
      label: { show: true, fontFamily: FONT, fontSize: FS.label,
        formatter: (o) => (o.value[2] || ''),
        color: C.ink,
        // 深格子上墨色字读不出来，超过一半浓度换白字
        textBorderColor: 'rgba(255,255,255,.85)', textBorderWidth: 2 },
      itemStyle: { borderColor: '#fff', borderWidth: 2 },
    }],
  }));
}

/* ============ 3. 款式覆盖天数 + 安全线（库存全览） ============

   按款号聚合子体的覆盖天数取中位数（不是平均：覆盖天数长尾很重，
   一个 900 天的滞销子体会把整款拉高）。安全线是一条 markLine。 */
export function styleCoverBars(host, rows, safetyDays, { limit = 14 } = {}) {
  const byStyle = new Map();
  for (const r of rows || []) {
    if (!r.style_no || r.cover_days == null) continue;
    if (!byStyle.has(r.style_no)) byStyle.set(r.style_no, []);
    byStyle.get(r.style_no).push(r.cover_days);
  }
  const median = (a) => {
    const s = a.slice().sort((x, y) => x - y);
    const m = s.length >> 1;
    return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
  };
  const list = [...byStyle.entries()]
    .map(([style, arr]) => ({ style, days: median(arr), n: arr.length }))
    .sort((a, b) => a.days - b.days)
    .slice(0, limit);
  if (list.length < 2) return Promise.resolve(null);
  return mount(host, Math.max(230, list.length * 26 + 76), () => ({
    ...base({
      tooltip: tip({
        trigger: 'axis', axisPointer: { type: 'shadow' },
        formatter: (ps) => {
          const r = list[ps[0].dataIndex];
          const d = r.days - safetyDays;
          return `<b>${r.style}</b><br/>覆盖天数中位 ${r.days.toFixed(1)} 天`
            + `<br/>较安全线 ${d >= 0 ? '+' : ''}${d.toFixed(1)} 天`
            + `<br/>${r.n} 个子 ASIN`;
        },
      }),
    }),
    grid: { left: 4, right: 46, top: 30, bottom: 24, containLabel: true },
    xAxis: { ...axisCommon, type: 'value', name: '天',
      nameTextStyle: { fontFamily: FONT, fontSize: FS.legend, color: C.fg3 } },
    yAxis: { ...axisCommon, type: 'category', data: list.map((r) => r.style),
      splitLine: { show: false } },
    series: [{
      type: 'bar', barWidth: 13,
      data: list.map((r) => ({
        value: r.days,
        // 低于安全线染警示色 —— 这条线是这张图存在的理由
        itemStyle: { color: r.days < safetyDays ? C.alert : 'rgba(17,17,19,.72)' },
      })),
      label: { show: true, position: 'right', fontFamily: FONT, fontSize: FS.label,
        color: C.fg2, formatter: (p) => `${p.value.toFixed(0)}天` },
      markLine: {
        silent: true, symbol: 'none',
        lineStyle: { color: C.warn, type: 'dashed', width: 1 },
        label: { show: true, position: 'end', formatter: `安全线 ${safetyDays} 天`,
          fontFamily: FONT, fontSize: FS.axis, color: C.warn },
        data: [{ xAxis: safetyDays }],
      },
    }],
  }));
}

export function disposeCharts(hosts) {
  for (const h of hosts || []) {
    const inst = LIVE.get(h);
    if (inst) { try { inst.dispose(); } catch { /* 已移除 */ } LIVE.delete(h); }
  }
}
