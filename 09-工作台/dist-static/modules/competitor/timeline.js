/* 竞品共同时间线 · ECharts
 *
 * 方案 §4.8 要求把市场结果、价格活动、关键词流量对齐到同一根横轴。
 * 之前那版只画了事件条，轨底下没有数据，读起来是一段文字陈述；
 * 这版三格共用一根 x 轴，事件带压在真实序列上，同期关系才看得出来。
 *
 *   grid 0  价格与活动   件单价折线 + 活动期阴影带 + 自有件单价参考线
 *   grid 1  市场表现     小类排名折线（inverse，第 1 名在顶）+ 月新增评论柱
 *   grid 2  事件与状态   固定量程隐藏轴上的泳道：价格活动 / 关键词位置 / 数据状态
 *
 * echarts.min.js 放外壳 /assets/ 由各模块共用一份，不每个模块各带一份。
 */

/* 与 tokens.css 的 --sans 逐字一致，两边要一起改。CSS 变量进不了 canvas，
   所以这里是唯一允许重复一份字体栈与字号的地方。 */
const FONT = '-apple-system, "SF Pro Text", BlinkMacSystemFont, "IBM Plex Sans", Inter, '
  + '"PingFang SC", "Microsoft YaHei", sans-serif';

/* 字号镜像 tokens.css 的阶梯，不许出现档外值。 */
const FS = {
  axis: 11,   // --fs-axis  轴刻度、dataZoom
  anno: 12,   // --fs-anno  图上标注的日期与条内文字
  meta: 13,   // --fs-meta  图例、格内说明、轨名
  body: 14,   // --fs-body  tooltip 正文
};

/* 与 tokens.css 同值。canvas 画不到 CSS 变量，这里是唯一允许出现色值的地方。 */
const CH = {
  ink: '#111113', fg2: '#4a4a4e', fg3: '#6b6b73', line: '#d4d4d8',
  bg2: '#f4f4f5', bg3: '#fafafa',
  accent: '#2563eb', alert: '#c9372c', warn: '#a8620d', good: '#3a7d43',
  calm: '#6b4fa8', faint: '#e4e4e7',
};

const LANES = [
  { key: 'price', y: 3, label: '价格活动', color: CH.alert },
  { key: 'keyword', y: 2, label: '关键词位置', color: CH.accent },
  { key: 'market', y: 1, label: '市场表现', color: CH.calm },
  { key: 'status', y: 0, label: '数据状态', color: CH.fg3 },
];
const LANE_MAX = 4;

let loading = null;

function loadECharts() {
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

function cnDay(iso) {
  if (!iso) return '';
  const [y, m, d] = iso.split('-').map(Number);
  const names = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];
  return `${m} 月 ${d} 日 ${names[new Date(y, m - 1, d).getDay()]}`;
}

/* 把详情载荷摊成一根日期轴 + 各序列。日期轴取价格与市场两条序列的并集。 */
function buildAxis(d) {
  const set = new Set();
  (d.price.series || []).forEach((r) => set.add(r.date));
  (d.market.series || []).forEach((r) => set.add(r.date));
  const dates = [...set].sort();
  const idx = new Map(dates.map((x, i) => [x, i]));
  const col = (rows, field) => {
    const arr = new Array(dates.length).fill(null);
    (rows || []).forEach((r) => {
      const i = idx.get(r.date);
      if (i !== undefined) arr[i] = r[field];
    });
    return arr;
  };
  return { dates, idx, col };
}

/* 恒定序列不能交给 scale:true —— 轴会自动摊成 0.4~1.6 这种噪音刻度，
   一条直线配一排假刻度，读起来像有波动其实没有。 */
function flatness(vals) {
  const v = vals.filter((x) => x !== null && x !== undefined);
  if (!v.length) return { empty: true };
  const min = Math.min(...v), max = Math.max(...v);
  const mid = Math.abs(v[v.length - 1]) || 1;
  return { empty: false, min, max, last: v[v.length - 1], flat: (max - min) / mid < 0.02 };
}


function laneBars(d, idx, dates) {
  /* 每条泳道一个 custom 序列：用 renderItem 画横条，起止落在日期索引上。 */
  const items = [];
  const push = (laneKey, label, from, to, note) => {
    const a = idx.get(from);
    const b = idx.get(to || dates[dates.length - 1]);
    if (a === undefined || b === undefined) return;
    const lane = LANES.find((l) => l.key === laneKey) || LANES[0];
    items.push({ value: [a, lane.y, Math.max(b, a + 1)], lane, label, from, to, note });
  };

  (d.price.promo_bands || []).forEach((b) => push('price', b.label, b.date_from, b.date_to));
  (d.tracks || []).forEach((t) => {
    const laneKey = t.track === 'data_status' ? 'status'
      : t.track === 'price_promo' ? 'price'
        : t.track === 'keyword' ? 'keyword' : 'market';
    (t.items || []).forEach((i) => push(laneKey, i.label, i.date_from, i.date_to, i.note));
  });
  (d.record.data_status || []).forEach((s) =>
    push('status', s.label, s.range[0], s.range[1], s.state));

  // 每条泳道垫一条贯穿窗口的观察底带：空轨读作「有观察、无该类变化」，
  // 而不是读作「这轨没数据」——两者对判断的含义完全不同。
  const base = LANES.map((lane) => ({
    value: [0, lane.y, dates.length - 1], lane, label: '', base: true,
    from: dates[0], to: dates[dates.length - 1],
    note: '',
  }));
  // 同一条轨里区间重叠的事件必须错开：都画在一行时后画的会把前一条整段盖掉，
  // 那是丢信息不是省空间。按轨分组做行内分层，renderItem 再按 subRow 偏移。
  for (const lane of LANES) {
    const mine = items.filter((it) => it.lane.key === lane.key)
      .sort((a, b) => a.value[0] - b.value[0]);
    const ends = [];
    for (const it of mine) {
      let row = ends.findIndex((e) => it.value[0] >= e + 1);
      if (row < 0) { row = ends.length; ends.push(0); }
      ends[row] = it.value[2];
      it.subRow = row;
      it.subRows = 1;
    }
    mine.forEach((it) => { it.subRows = ends.length; });
  }
  return base.concat(items);
}

function tooltipHTML(params, ctxData) {
  const first = params.find((p) => p.axisValue !== undefined);
  if (!first) return '';
  const date = first.axisValue;
  const rows = [];
  for (const p of params) {
    if (p.seriesType === 'custom') continue;
    const v = Array.isArray(p.value) ? p.value[1] : p.value;
    if (v === null || v === undefined) continue;
    const fmt = p.seriesName === '件单价' ? `$${Number(v).toFixed(2)}`
      : p.seriesName === '小类排名' ? `第 ${v} 名`
        : Number(v).toLocaleString('en-US');
    rows.push(`<div style="display:flex;gap:10px;justify-content:space-between">
      <span style="color:${CH.fg3}">${p.marker}${p.seriesName}</span>
      <b style="font-family:${FONT};font-variant-numeric:tabular-nums">${fmt}</b></div>`);
  }
  const bands = (ctxData.lanes || []).filter((it) =>
    !it.base && it.from <= date && (it.to || '9999') >= date);
  const bandHTML = bands.length
    ? `<div style="margin-top:6px;padding-top:6px;border-top:1px solid ${CH.faint};
        color:${CH.fg2}">${bands.map((b) =>
      `<div>${b.lane.label} · ${b.label}</div>`).join('')}</div>`
    : '';
  return `<div style="font-family:${FONT};font-size:var(--fs-anno);min-width:190px">
    <div style="color:${CH.fg3};margin-bottom:4px">${cnDay(date)}</div>
    ${rows.join('')}${bandHTML}</div>`;
}

export async function renderTimeline(box, d, opts = {}) {
  let echarts;
  try {
    echarts = await loadECharts();
  } catch (err) {
    box.textContent = '图表组件未加载，共同时间线暂不可用';
    return null;
  }
  const { dates, idx, col } = buildAxis(d);
  if (!dates.length) {
    box.textContent = '窗口内没有连续观察，画不出共同时间线';
    return null;
  }

  const unitPrice = col(d.price.series, 'unit_price');
  const rank = col(d.market.series, 'rank_sub');
  const newRating = col(d.market.series, 'new_rating');
  const lanes = laneBars(d, idx, dates);
  const own = d.price.own_unit_price;

  const promoAreas = (d.price.promo_bands || []).map((b) => ([
    { xAxis: b.date_from, itemStyle: { color: 'rgba(201,55,44,0.07)' },
      label: { show: true, position: 'insideTop', color: CH.alert, fontSize: FS.anno,
        fontFamily: FONT, formatter: b.label } },
    { xAxis: b.date_to },
  ]));

  const fPrice = flatness(unitPrice);
  const fRank = flatness(rank);
  const rankFlat = fRank.flat || fRank.empty;
  const priceFlat = fPrice.flat || fPrice.empty;
  const fRating = flatness(newRating);
  const rankAxis = fRank.flat && !fRank.empty
    ? { min: Math.max(0, fRank.last - 1), max: fRank.last + 1, interval: 1 }
    : { scale: true };
  const rankName = fRank.flat && !fRank.empty
    ? `小类排名 · 窗口内恒为第 ${fRank.last} 名` : '小类排名';
  const priceDp = fPrice.empty ? 2
    : ((fPrice.max - fPrice.min) < 0.5 ? 2 : 1);
  const priceName = priceFlat && !fPrice.empty
    ? `件单价 · 窗口内基本无波动，恒为 $${fPrice.last.toFixed(2)}`
    : '件单价（$）';
  const priceAxis = priceFlat && !fPrice.empty
    ? { min: fPrice.last - 0.5, max: fPrice.last + 0.5 }
    : { scale: true };

  // 恒定的那条轨只是一条直线，占满高度是浪费，也会把噪声放大成锯齿看着像有波动。
  // 压扁它，把高度让给真有变化的那条。
  const rankH = rankFlat ? 46 : (priceFlat ? 190 : 118);
  const priceTop = 34;
  const priceH = priceFlat ? 56 : (rankFlat ? 220 : 148);
  const rankTop = priceTop + priceH + 40;
  const laneTop = rankTop + rankH + 34;
  const laneH = 82;

  const chart = echarts.init(box, null, { renderer: 'canvas' });
  chart.setOption({
    animation: false,
    textStyle: { fontFamily: FONT },
    grid: [
      { left: 84, right: 24, top: priceTop, height: priceH },
      { left: 84, right: 24, top: rankTop, height: rankH },
      { left: 84, right: 24, top: laneTop, height: laneH },
    ],
    axisPointer: { link: [{ xAxisIndex: 'all' }], label: { show: false } },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'line', lineStyle: { color: CH.line } },
      backgroundColor: '#fff',
      borderColor: CH.faint,
      extraCssText: 'box-shadow:0 10px 30px rgba(9,9,11,.13);border-radius:8px',
      formatter: (p) => tooltipHTML(p, { lanes }),
    },
    graphic: [
      { type: 'text', left: 88, top: priceTop - 14,
        style: { text: priceName, fill: CH.fg3, fontSize: FS.axis, fontFamily: FONT } },
      { type: 'text', left: 88, top: rankTop - 14,
        style: { text: rankName + (rankFlat ? '' : ' · 第 1 名在顶'),
          fill: CH.fg3, fontSize: FS.axis,
          fontFamily: FONT } },
      { type: 'text', left: 88, top: laneTop - 14,
        style: { text: '事件与数据状态', fill: CH.fg3, fontSize: FS.axis, fontFamily: FONT } },
    ],
    legend: {
      top: 4, right: 24, itemGap: 18, itemWidth: 14, itemHeight: 8,
      textStyle: { color: CH.fg2, fontSize: FS.meta, fontFamily: FONT },
      data: ['件单价', '小类排名', '月新增评论'],
    },
    dataZoom: [
      { type: 'slider', xAxisIndex: [0, 1, 2], height: 16, bottom: 4,
        borderColor: CH.faint, fillerColor: 'rgba(37,99,235,0.08)',
        handleStyle: { color: '#fff', borderColor: CH.fg3 },
        textStyle: { color: CH.fg3, fontSize: FS.axis, fontFamily: FONT },
        start: opts.zoomStart ?? 0, end: 100 },
      { type: 'inside', xAxisIndex: [0, 1, 2], zoomOnMouseWheel: false,
        moveOnMouseWheel: false, moveOnMouseMove: false },
    ],
    xAxis: [
      { type: 'category', gridIndex: 0, data: dates, boundaryGap: false,
        axisLabel: { show: false }, axisTick: { show: false },
        axisLine: { lineStyle: { color: CH.faint } } },
      { type: 'category', gridIndex: 1, data: dates, boundaryGap: false,
        axisLabel: { show: false }, axisTick: { show: false },
        axisLine: { lineStyle: { color: CH.faint } } },
      { type: 'category', gridIndex: 2, data: dates, boundaryGap: false,
        axisLabel: { color: CH.fg3, fontSize: FS.axis, fontFamily: FONT, interval: 29,
          margin: 12 },
        axisTick: { show: false }, axisLine: { lineStyle: { color: CH.faint } } },
    ],
    yAxis: [
      { gridIndex: 0, scale: true, splitLine: { lineStyle: { color: CH.bg2 } },
        axisLabel: { color: CH.fg3, fontSize: FS.axis, fontFamily: FONT,
          formatter: (v) => '$' + v.toFixed(1) } },
      Object.assign({
        gridIndex: 1, inverse: true, splitLine: { lineStyle: { color: CH.bg2 } },
        axisLabel: { color: CH.fg3, fontSize: FS.axis, fontFamily: FONT,
          formatter: (v) => (Number.isInteger(v) ? v : '') },
      }, rankAxis),
      { gridIndex: 1, scale: true, splitLine: { show: false },
        axisLabel: { show: false } },
      { gridIndex: 2, min: 0, max: LANE_MAX - 1, interval: 1,
        splitLine: { show: true, lineStyle: { color: CH.bg3 } },
        axisTick: { show: false }, axisLine: { show: false },
        axisLabel: { color: CH.fg2, fontSize: FS.anno, fontFamily: FONT, margin: 10,
          formatter: (v) => (LANES.find((l) => l.y === Math.round(v)) || {}).label || '' } },
    ],
    series: [
      {
        name: '件单价', type: 'line', xAxisIndex: 0, yAxisIndex: 0,
        data: unitPrice, showSymbol: false, smooth: false,
        lineStyle: { width: 1.6, color: CH.ink },
        areaStyle: { color: 'rgba(17,17,19,0.05)' },
        markArea: promoAreas.length ? { silent: true, data: promoAreas } : undefined,
        markLine: own ? {
          silent: true, symbol: 'none',
          data: [{ yAxis: own, lineStyle: { color: CH.good, type: 'dashed', width: 1 },
            label: { formatter: `自有 $${own.toFixed(2)}`, position: 'insideEndTop',
              color: CH.good, fontSize: FS.axis, fontFamily: FONT } }],
        } : undefined,
      },
      {
        name: '小类排名', type: 'line', xAxisIndex: 1, yAxisIndex: 1,
        data: rank, showSymbol: false,
        lineStyle: { width: 1.6, color: CH.calm },
      },
      {
        name: '月新增评论', type: 'bar', xAxisIndex: 1, yAxisIndex: 2,
        // 恒定值画成一排等高柱会被读成有波动，直接不画
        data: fRating.flat ? newRating.map(() => null) : newRating,
        barMaxWidth: 3, itemStyle: { color: CH.faint },
      },
      {
        name: '泳道', type: 'custom', xAxisIndex: 2, yAxisIndex: 3,
        silent: false, data: lanes,
        encode: { x: [0, 2], y: 1 },
        renderItem: (params, api) => {
          const item = lanes[params.dataIndex];
          if (!item) return null;
          const start = api.coord([item.value[0], item.value[1]]);
          const end = api.coord([item.value[2], item.value[1]]);
          const rows = item.subRows || 1;
          const h = item.base ? 4 : (rows > 1 ? 9 : 14);
          const w = Math.max(end[0] - start[0], item.base ? 2 : 6);
          return {
            type: 'group',
            children: [{
              type: 'rect',
              shape: {
                x: start[0],
                y: start[1] - (rows > 1 ? (rows * (h + 2)) / 2 - (item.subRow || 0) * (h + 2) - h : h / 2),
                width: w, height: h, r: 3,
              },
              style: {
                fill: item.base ? CH.bg2
                  : (item.lane.key === 'status' ? CH.bg2 : item.lane.color),
                opacity: item.base ? 1 : (item.lane.key === 'status' ? 1 : 0.85),
                stroke: item.base ? 'transparent'
                  : (item.lane.key === 'status' ? CH.line : 'transparent'),
              },
            }, {
              type: 'text',
              style: {
                text: item.base ? '' : (w > 58 ? item.label : ''),
                fontSize: rows > 1 ? FS.axis : FS.anno,
                x: start[0] + (item.base ? 2 : 5),
                y: start[1] - (item.base ? 8
                  : (rows > 1
                    ? (rows * (h + 2)) / 2 - (item.subRow || 0) * (h + 2) - h / 2
                    : 0)),
                fill: item.base ? CH.fg3
                  : (item.lane.key === 'status' ? CH.fg2 : '#fff'),
                font: `${FS.anno}px ${FONT}`, textVerticalAlign: 'middle',
              },
            }],
          };
        },
      },
    ],
  });

  if (opts.onDayClick) {
    chart.getZr().on('click', (ev) => {
      const p = [ev.offsetX, ev.offsetY];
      for (const gi of [0, 1, 2]) {
        if (chart.containPixel({ gridIndex: gi }, p)) {
          const [i] = chart.convertFromPixel({ xAxisIndex: gi }, p);
          const date = dates[Math.round(i)];
          if (date) opts.onDayClick(date, lanes.filter((it) =>
            !it.base && it.from <= date && (it.to || '9999') >= date));
          return;
        }
      }
    });
  }
  return chart;
}

export function laneLegend() {
  return LANES.map((l) => ({ label: l.label, color: l.color, key: l.key }));
}
