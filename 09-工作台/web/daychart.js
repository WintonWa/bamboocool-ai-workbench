/* 逐日销量与需求图 · 外壳共享组件
 *
 * 原来在 web/modules/inventory/daychart.js。2026-09-04 提升到外壳共享层，
 * 因为面料预投模块也要用同一张图 —— 用户原话：「不是让你把库存那个搬过来吗？
 * 然后你把预投的那个阶段给圈出来就行啊……你同样都是跑 90 天的预测，
 * 你为什么非要在这再跑一遍呢？」
 *
 * 两个模块共用一份而不是各画一张：图一改两边都变，不会漂移。
 * 放在外壳层而不是让预投 import 库存，是因为契约 §8.5 禁止模块间代码依赖
 * （门禁 G12 会红）。这与 web/aimark.js 是同一种处理。
 *
 * 数据形状仍然是库存 compute 产出的 `assessment.chart`。预投模块通过
 * 库存声明的对外路由 /api/inventory/child/<asin> 取它 —— 那是数据依赖，
 * 不是代码依赖，契约允许。
 *
 * 新增可选参数 opts.highlight = { from, to, label }：在图上圈出一段并加背景带。
 * 预投用它圈销售月；库存不传就跟以前一样。
 */

/* 数字格式化从 util.js 导入。
 *
 * 18810 版里这个文件是普通脚本，和 app.js 同处全局作用域，能直接用它定义的
 * n0/n1/n2。改成 ES module 后作用域隔离，这些函数搬进了 util.js，
 * 必须显式导入 —— 漏了不会在加载时报错，只在 tooltip 格式化和当天详情
 * **被真正调用时**才抛 ReferenceError，也就是鼠标碰到图的那一刻。
 * 这正是只验 option 结构、不调 option 里的回调的门禁抓不到的东西。 */
/* 组件自带样式，只注入一次。
 *
 * 为什么自带而不是放进 base.css 或某个模块的 CSS：
 *   放 modules/inventory.css 里 → 选择器带 [data-module="inventory"]，
 *     预投页用同一张图就完全没有样式（图会塌成 0 高）
 *   放 base.css 里 → 要同时改外壳文件，而这些规则只服务这一个组件
 * 所以规则跟着组件走：谁 import 它，样式就跟到哪里。**不带 [data-module] 前缀**，
 * 因为两个模块都要它生效；类名都是 day* / dd-* 前缀，不会撞别人。
 *
 * 逐条从 modules/inventory.css 原样搬来（2026-09-04），只去掉了作用域前缀。
 * 用到的变量全部是 tokens.css 已有的，没有新增色值或字号（契约 G3）。
 */
const STYLE_ID = 'wb-daychart-style';
const CSS = `
.daychart{height:452px;width:100%;background:var(--bg1)}
.daydetail{margin-top:10px;background:var(--bg2);border-radius:var(--r2);
  padding:12px 14px;min-height:44px;font-size:var(--fs-body);line-height:1.7}
.daydetail .dim{color:var(--fg3);font-size:var(--fs-meta)}
.daydetail .na{color:var(--fg3);font-size:var(--fs-anno);font-style:normal}
.dd-h{font-weight:600;font-size:var(--fs-body);color:var(--fg);
  margin-bottom:14px;display:flex;align-items:center;gap:7px}
.dd-dot{width:8px;height:8px;border-radius:50%;flex:0 0 auto}
.dd-p{color:var(--fg2);font-size:var(--fs-body);margin:4px 0;line-height:1.75}
.dd-q{font-weight:600;color:var(--fg);font-size:var(--fs-body);margin:16px 0 6px}
.dd-q:first-of-type{margin-top:0}
.dd-l{margin:0;padding-left:18px;color:var(--fg2)}
.dd-l li{margin:3px 0}
.dd-l b{color:var(--fg)}
.daydetail table{width:100%;border-collapse:collapse;margin-top:4px}
.daydetail table th{text-align:left;font-weight:500;color:var(--fg3);
  font-size:var(--fs-axis);padding:3px 8px 3px 0}
.daydetail table td{padding:3px 8px 3px 0;vertical-align:top;color:var(--fg2)}
.daydetail table tbody tr:nth-child(odd){background:rgba(255,255,255,.6)}
`;

function ensureStyle() {
  if (document.getElementById(STYLE_ID)) return;
  const el = document.createElement('style');
  el.id = STYLE_ID;
  el.textContent = CSS;
  document.head.appendChild(el);
}

/* 数字格式化自带一份。这个文件是**外壳共享组件**（两个模块都用它），
   所以不能 import 某个模块的 util —— 那会让外壳依赖模块（契约 8.4）。
   三个函数与 modules/inventory/util.js 里同名函数的行为一致。 */
const _NF = (min, max) => new Intl.NumberFormat('zh-CN',
  { minimumFractionDigits: min, maximumFractionDigits: max });
const _F0 = _NF(0, 0), _F1 = _NF(1, 1), _F2 = _NF(2, 2);
const n0 = (v) => (v === null || v === undefined || Number.isNaN(v) ? '—' : _F0.format(v));
const n1 = (v) => (v === null || v === undefined || Number.isNaN(v) ? '—' : _F1.format(v));
const n2 = (v) => (v === null || v === undefined || Number.isNaN(v) ? '—' : _F2.format(v));

const CH = {
  actualBar: '#3f3f46',
  forecastBar: '#b8b8c0',
  forecastEdge: '#5b5b63',
  stockoutBar: '#e4e4e7',
  anomalyBar: '#3f3f46',
  whisker: '#8b8b93',
  // 高亮窗口内的预估柱。用 tokens.css 的 --accent 同一个蓝（#2563eb），
  // 但比预估柱深一档、实心 —— 它要能在一片中性灰里被一眼挑出来。
  // 这是「圈出来」的主要表达手段，不用背景色块（那样只是把一段涂淡）。
  highlightBar: '#2563eb',
  stockoutDot: '#a8620d',
  anomalyDot: '#c9372c',
  axis: '#d4d4d8',
  label: '#6b6b73',
  divider: '#111113',
  // 键必须和数据里的 event_type 完全一致。v0.3.0 用的是 BD / LD / Coupon /
  // PriceDiscount（大写），曾经写成小写导致全部落到 fallback 灰 ——
  // 而彩色在这张图上唯一的职责就是区分事件类型，一灰就等于没做。
  // 叠加折线的配色：避开事件占用的红/橙/砖红/绿，也不跟柱子的中性墨色抢
  metric: {
    售价: '#6b4fa8', 标价: '#a493c9',
    销售额: '#2f6f6f', 广告花费: '#4a6fa5', 广告销售额: '#89a6cb',
    访问量: '#6b6b73', 转化率: '#3a7d7d', ACoS: '#7a6a8a',
  },
  lane: {
    BD: '#c9372c',
    LD: '#b4451f',
    Coupon: '#a8620d',
    PriceDiscount: '#3a7d43',
    ad: '#6b4fa8',
    market: '#6b6b73',
    other: '#9ca3af',
  },
};

const LANE_H = 0.70;      // 泳道横条高度，单位是泳道轴的刻度

/* 字号与字体栈：与外壳 web/tokens.css 的 --fs-* 阶梯同一组值。
   图表在 canvas 里画字，拿不到 CSS 变量，所以在这里镜像一份 —— **两边要一起改**。
   规范见 00-通用方法与规范/06-视觉基准要则.md 第一、二节。 */
const FS = {
  axis: 11,              // 轴刻度        --fs-axis
  anno: 12,              // 事件标注日期  设计图字形 9px  → 12
  annoName: 13,          // 事件标注名称  设计图字形 10px → 13（名称比日期大一档，
                         //               名称是信息、日期只是定位）
  legend: 13,            // 图例          --fs-meta
  legendSub: 11,         // 叠加行图例
  axisName: 13,          // y 轴名「件」  --fs-meta
};
// 与 tokens.css 的 --sans 逐字一致，**两边要一起改**。
// 设计图用的是 SF Pro（比值指纹偏差 0.0220，次优的 Helvetica 是 0.0390），
// 而系统字体就是它，所以放最前；Plex/Inter 留给非 macOS 兜底。
const FONT = '-apple-system, "SF Pro Text", BlinkMacSystemFont, "IBM Plex Sans", Inter, '
  + '"PingFang SC", "Microsoft YaHei", sans-serif';

/* 事件标注的垂直排布，全部按设计图量得（1x 图）：
     横条厚 4，名称底距横条顶 10，日期底距名称顶 9。
   字形高度按字号估：日期 12px 数字 ≈9，名称 11px 拉丁 ≈8。 */
const ANNO = {
  barH: 4,
  nameGap: 9,            // 名称底 → 横条顶   设计图量得 9
  dateGap: 8,            // 日期底 → 名称顶   设计图量得 8
  nameBand: 10,          // 名称字形高（13px 拉丁）
  dateBand: 9,           // 日期字形高（12px 数字）
};
ANNO.nameTop = ANNO.barH / 2 + ANNO.nameGap + ANNO.nameBand;   // 距横条中线
ANNO.dateTop = ANNO.nameTop + ANNO.dateGap + ANNO.dateBand;
const ROW_H_PX = Math.ceil(ANNO.dateTop + ANNO.barH / 2 + 6);  // 一行标注占的像素
let chartInst = null;     // 当前实例，切换子体时要 dispose

/* ECharts 是 UMD 全局脚本，ES module 里直接引用不到，所以按需注入一次。
   放外壳级 /assets/ 是为了多模块共用一份，1 MB 不该每个模块各带一份。 */
let echartsLoading = null;

function loadECharts() {
  if (typeof window !== 'undefined' && window.echarts) return Promise.resolve(window.echarts);
  if (echartsLoading) return echartsLoading;
  echartsLoading = new Promise((resolve, reject) => {
    const tag = document.createElement('script');
    tag.src = '/assets/echarts.min.js';
    tag.onload = () => resolve(window.echarts);
    tag.onerror = () => reject(new Error('ECharts 加载失败'));
    document.head.appendChild(tag);
  });
  return echartsLoading;
}

export function disposeDayChart() {
  disposeChart();
}

function disposeChart() {
  if (chartInst) {
    chartInst.dispose();
    chartInst = null;
  }
}

/* 悬停一天时的 tooltip。R2.3：带星期、带时区、只列有值的行、合计在最前。 */
function dayTooltip(ch, idx) {
  const d = ch.dates[idx];
  const wd = ch.weekdays[idx];
  const a = ch.actual[idx];
  const f = ch.forecast[idx];
  const rows = [];
  const row = (k, v, cls) =>
    `<tr><td class="tk">${k}</td><td class="tv ${cls || ''}">${v}</td></tr>`;

  let head = `${d} ${wd}（${ch.timezone_label}）`;
  let total = '';

  if (a) {
    total = `<div class="tt-total"><span>销量</span><b>${n0(a.value)}</b></div>`;
    if (a.trust_note) rows.push(row('', `<span class="tt-warn">${a.trust_note}</span>`));
    const so = (ch.stockout_bands || []).find(b => idx >= b.from_index && idx <= b.to_index);
    if (so) rows.push(row('缺货区间', `${so.from} ~ ${so.to}，共 ${so.days} 天`));
    if (a.price != null) rows.push(row('价格', '$' + n2(a.price)));
    if (a.net_sales != null) rows.push(row('销售额', '$' + n2(a.net_sales)));
    if (a.gross_profit != null) rows.push(row('毛利', '$' + n2(a.gross_profit)));
    if (a.ad_spend != null) rows.push(row('广告花费', '$' + n2(a.ad_spend)));
    if (a.sessions != null) rows.push(row('访问量', n0(a.sessions)));
    if (a.conversion_rate != null) rows.push(row('转化率', n2(a.conversion_rate * 100) + '%'));
  }
  if (f) {
    const label = a ? '预估（当时）' : '预估销量';
    if (!a) total = `<div class="tt-total"><span>${label}</span><b>${n1(f.value)}</b></div>`;
    else rows.push(row(label, n1(f.value)));
    rows.push(row('区间', n1(f.lower) + ' ~ ' + n1(f.upper)));
  }

  // 当天的事件：区间与点都算
  const evs = [];
  ch.bands.forEach(b => {
    if (idx >= b.from_index && idx <= b.to_index) {
      evs.push([b.type_label, b.label + `（第 ${idx - b.from_index + 1}/${b.days} 天）`]);
    }
  });
  ch.points.forEach(pt => {
    if (pt.from_index === idx) evs.push([pt.type_label, pt.label]);
  });
  evs.forEach(([k, v]) => rows.push(row(k, v)));

  return `<div class="tt"><div class="tt-h">${head}</div>${total}
    <table>${rows.join('')}</table>
    ${a || f ? '<div class="tt-f">点击这一天看为什么是这个数</div>' : ''}</div>`;
}

/* 点击一天：R2.4 悬停出事实，点击出解释。 */
function dayDetail(a, ch, idx) {
  const d = ch.dates[idx];
  const wd = ch.weekdays[idx];
  const act = ch.actual[idx];
  const fc = ch.forecast[idx];
  const future = !act && fc;
  const parts = [];

  // 状态圆点：颜色跟当天状态走，红=柱高不可信，橙=活动期，灰=常规
  const evsNow = ch.bands.filter(b => idx >= b.from_index && idx <= b.to_index);
  let dotColor = '#9ca3af';
  if (act && act.is_stockout) dotColor = CH.stockoutDot;
  else if (act && act.is_anomaly) dotColor = CH.anomalyDot;
  else if (evsNow.length) dotColor = CH.lane[evsNow[0].event_type] || CH.lane.other;
  parts.push(`<div class="dd-h"><span class="dd-dot" style="background:${dotColor}"></span>`
    + `${d} ${wd}<span class="dim"> · ${ch.timezone_label}</span></div>`);

  if (act) {
    parts.push(`<div class="dd-q">这天为什么是 ${n0(act.value)} 件</div>`);
    const lines = [];
    if (act.is_stockout) {
      const so = (ch.stockout_bands || []).find(b => idx >= b.from_index && idx <= b.to_index);
      lines.push(`当天缺货。这个数字是「能卖出去多少」，不是「有多少人要买」，`
        + `用它判断需求会把断货读成需求下降。`
        + (so ? `本次缺货 ${so.from} ~ ${so.to}，共 ${so.days} 天，`
            + `期间累计出单 ${n0(so.units_in_span)} 件。` : ''));
    }
    if (act.is_anomaly) {
      // 方向从相邻的正常日比出来，不写死「偏离」
      const near = [];
      for (let k = Math.max(0, idx - 7); k <= Math.min(ch.actual.length - 1, idx + 7); k += 1) {
        const x = ch.actual[k];
        if (k !== idx && x && !x.is_stockout && !x.is_anomaly) near.push(x.value);
      }
      near.sort((p1, p2) => p1 - p2);
      const mid = near.length ? near[Math.floor(near.length / 2)] : null;
      const dir = mid == null ? '明显偏离' : (act.value >= mid ? '明显偏高' : '明显偏低');
      lines.push(`当天数据异常。与相邻日相比${dir}，采信前先核对源数据。`);
    }
    evsNow.forEach(b => {
      lines.push(`${b.type_label}：${b.label}。${b.from} ~ ${b.to}，共 ${b.days} 天，`
        + `这天是第 ${idx - b.from_index + 1} 天。`);
    });
    if (act.conversion_rate != null && act.sessions != null) {
      lines.push(`流量 ${n0(act.sessions)}，转化 ${n2(act.conversion_rate * 100)}%`
        + `${act.ad_spend ? `，广告花费 $${n2(act.ad_spend)}` : ''}。`);
    }
    if (!lines.length) lines.push('这天没有记录到活动、缺货或异常，是一个常规日。');
    parts.push(lines.map(t => `<div class="dd-p">${t}</div>`).join(''));

    if (fc) {
      const diff = act.value - fc.value;
      const inBand = act.value >= fc.lower && act.value <= fc.upper;
      parts.push(`<div class="dd-q">预估对得上吗</div>
        <div class="dd-p">当时预估 ${n1(fc.value)} 件，区间 ${n1(fc.lower)} ~ ${n1(fc.upper)}，
        实际 ${n0(act.value)} 件，${diff >= 0 ? '高出' : '低于'} ${n1(Math.abs(diff))} 件，
        ${inBand ? '落在区间内' : '落在区间外'}。</div>`);
    }
  } else if (future) {
    parts.push(`<div class="dd-q">这天的预估怎么来的</div>`);
    const d2 = a.demand;
    const rows = [`<div class="dd-p">预估 ${n1(fc.value)} 件，区间 ${n1(fc.lower)} ~ ${n1(fc.upper)}。</div>`];
    if (d2.available) {
      rows.push(d2.run.origin === 'agent'
        ? `<div class="dd-p">基准日 ${d2.run.as_of_date}，由本次 Pi Agent 同批次产出逐日预测与五项判断，置信度${d2.confidence_label}。</div>`
        : `<div class="dd-p">基准日 ${d2.run.as_of_date}，快照选用「${d2.run.model_label}」，置信度${d2.confidence_label}。</div>`);
      // 因子分解：这一天的预测是怎么从基线乘出来的
      const fx = [
        ['星期', fc.weekday_factor], ['季节', fc.seasonality_factor],
        ['生命周期', fc.lifecycle_factor], ['广告', fc.ad_ratio],
        ['价格', fc.price_ratio], ['活动', fc.promotion_ratio],
      ].filter(([, v]) => v != null && Math.abs(v - 1) > 0.005);
      if (fc.baseline != null) {
        rows.push(`<div class="dd-p">基线 ${n1(fc.baseline)} 件${fx.length ? '，再乘 ' +
          fx.map(([k, v]) => `${k} ${v > 1 ? '+' : ''}${((v - 1) * 100).toFixed(0)}%`).join('、') : ''}。</div>`);
      }
      if (d2.confidence_reason) rows.push(`<div class="dd-p">${d2.confidence_reason}</div>`);
    }
    parts.push(rows.join(''));
    if (d2.available && d2.factors.length) {
      parts.push(`<div class="dd-q">本次预估的关键调整项</div>
        <table class="tight"><thead><tr><th>调整项</th><th>依据</th></tr></thead><tbody>
        ${d2.factors.map(f => `<tr><td>${f.label}</td><td class="dim">${f.basis}</td></tr>`).join('')}
        </tbody></table>`);
    }
  } else {
    parts.push('<div class="na">这一天既没有实际数据也没有预估。</div>');
  }
  return parts.join('');
}

/* 主入口：把 chart payload 画成 ECharts 配置并挂上交互。
   变成 async 是因为 ECharts 按需加载 —— 调用方要 await，否则图表会晚于
   后面的渲染出现，看起来像"闪一下才有图"。 */
export async function renderDayChart(el, a, opts = {}) {
  ensureStyle();
  const ch = a.chart;
  disposeChart();
  if (!ch.available) {
    el.innerHTML = `<div class="na">${ch.reason}${ch.detail ? '<br>' + ch.detail : ''}</div>`;
    return;
  }
  let echarts;
  try {
    echarts = await loadECharts();
  } catch (err) {
    el.innerHTML = '<div class="na">图表库未加载，无法绘制逐日图</div>';
    return;
  }
  if (!echarts) {
    el.innerHTML = '<div class="na">图表库未加载，无法绘制逐日图</div>';
    return;
  }

  const box = document.createElement('div');
  box.className = 'daychart';
  const detail = document.createElement('div');
  detail.className = 'daydetail';
  detail.innerHTML = `<div class="dim">${ch.hint}</div>`;
  el.innerHTML = '';
  el.appendChild(box);
  el.appendChild(detail);

  const series = [];

  // --- 高亮窗口：预投圈出来的销售月 ------------------------------------- //
  // 只有传了 opts.highlight 才画（库存不传，行为跟以前完全一样）。
  //
  // **不画背景色块。** 一版用了 rgba 浅蓝底，效果是把一段涂淡、柱子还是灰的，
  // 「圈」这件事没有落到数上。现在换成：窗口内的预估柱本身染成强调色
  // （见下面预估柱系列的 itemStyle 回调），这里只补两条上下端点的边界短线
  // 和一个写着合计的标签 —— 边界说明圈到哪里，标签说明圈住的是多少。
  const HL = opts.highlight;
  /* 高亮那个 series 的名字。它**不进图例**（下面第一排图例的 filter 排除它）：
     图例项能被点掉，而柱子的蓝色是预估柱 itemStyle 回调决定的、不受这个
     series 显隐影响 —— 点掉图例会变成「括号消失、蓝柱子还在」，
     一个自相矛盾的状态。窗口是什么、圈住多少，图上那个标签已经写明了。 */
  const HL_SERIES_NAME = (HL && HL.label) || '预投窗口';
  let hlFrom = -1, hlTo = -1, hlSum = 0;
  if (HL && HL.from && HL.to) {
    hlFrom = ch.dates.indexOf(HL.from);
    hlTo = ch.dates.indexOf(HL.to);
    // 窗口末日可能超出预估末日（销售月比预估窗口长），夹到最后一天
    if (hlFrom >= 0 && hlTo < 0) hlTo = ch.dates.length - 1;
    if (hlFrom >= 0 && hlTo >= hlFrom) {
      for (let i = hlFrom; i <= hlTo; i += 1) {
        const f = ch.forecast[i];
        if (f && f.value != null) hlSum += Number(f.value);
      }
    }
  }
  if (hlFrom >= 0 && hlTo >= hlFrom) {
    series.push({
      name: HL_SERIES_NAME,
      type: 'custom',
      xAxisIndex: 1,
      yAxisIndex: 1,
      z: 5,
      silent: true,
      color: CH.highlightBar,
      itemStyle: { color: CH.highlightBar },
      renderItem: (params, api) => {
        const x1 = api.coord([api.value(0), 0])[0];
        const x2 = api.coord([api.value(1), 0])[0];
        const bw = Math.max(1, api.size([1, 0])[0]);
        const top = params.coordSys.y;
        const h = params.coordSys.height;
        const l = x1 - bw / 2;
        const r = x2 + bw / 2;
        const tick = 7;                       // 边界线只在上下端点各露一小段
        const line = (x) => ([
          { type: 'line', shape: { x1: x, y1: top, x2: x, y2: top + tick },
            style: { stroke: CH.highlightBar, lineWidth: 1 } },
          { type: 'line', shape: { x1: x, y1: top + h - tick, x2: x, y2: top + h },
            style: { stroke: CH.highlightBar, lineWidth: 1 } },
        ]);
        return {
          type: 'group',
          children: [
            ...line(l), ...line(r),
            // 顶部横跨一条细线把两个边界连起来，形成一个「」形的括
            { type: 'line', shape: { x1: l, y1: top, x2: r, y2: top },
              style: { stroke: CH.highlightBar, lineWidth: 1 } },
            { type: 'text',
              style: {
                text: `${HL_SERIES_NAME}　${n1(hlSum)}`,
                x: l + 6, y: top + 6, fill: CH.highlightBar,
                font: `500 ${FS.legend}px ${FONT}`, textVerticalAlign: 'top',
              } },
          ],
        };
      },
      encode: { x: [0, 1] },
      data: [[hlFrom, hlTo]],
    });
  }

  // --- 缺货区间：贯穿绘图区的背景色带 ------------------------------------ //
  // 缺货日销量是 0，柱高也就是 0，画不出东西。不画成区域的话那一段是空白，
  // 运营会读成「没数据」而不是「这段没货可卖」。柱子的浅色斜纹只在缺货日
  // 仍有零星出单时才看得见，所以背景带是主要的表达手段。
  if ((ch.stockout_bands || []).length) {
    series.push({
      name: '缺货区间',
      type: 'custom',
      xAxisIndex: 1,
      yAxisIndex: 1,
      z: 1,
      silent: true,
      color: '#ececed',
      itemStyle: { color: '#ececed' },
      renderItem: (params, api) => {
        const x1 = api.coord([api.value(0), 0])[0];
        const x2 = api.coord([api.value(1), 0])[0];
        const bw = Math.max(1, api.size([1, 0])[0]);
        const top = params.coordSys.y;
        const h = params.coordSys.height;
        return {
          type: 'rect',
          shape: { x: x1 - bw / 2, y: top, width: (x2 - x1) + bw, height: h },
          style: { fill: '#e9e9ec' },
        };
      },
      encode: { x: [0, 1] },
      data: ch.stockout_bands.map(b => [b.from_index, b.to_index, b.days]),
    });
  }

  // --- 柱：实际。缺货日与异常日改柱样式，不另开泳道 --------------------- //
  series.push({
    name: '实际销量',
    type: 'bar',
    xAxisIndex: 1,
    yAxisIndex: 1,
    z: 3,
    barGap: '-100%',
    color: CH.actualBar,
    itemStyle: { color: CH.actualBar },
    data: ch.actual.map(x => {
      if (!x) return null;
      // 缺货日：柱高不代表需求，压成浅色 + 斜纹，让人不要拿它读趋势。
      if (x.is_stockout) {
        return { value: x.value, itemStyle: { color: CH.stockoutBar,
          decal: { symbol: 'line', dashArrayX: [1, 0], dashArrayY: [2, 3],
                   rotation: -Math.PI / 4, color: '#a1a1aa' } } };
      }
      // 异常日：柱高是真的，只是可疑，所以保留深色再打网纹标记出来。
      if (x.is_anomaly) {
        return { value: x.value, itemStyle: { color: CH.anomalyBar,
          decal: { symbol: 'line', dashArrayX: [1, 0], dashArrayY: [3, 3],
                   rotation: Math.PI / 4, color: 'rgba(255,255,255,.72)' } } };
      }
      return { value: x.value };
    }),
  });

  // --- 柱：预测 ---------------------------------------------------------- //
  if (ch.has_forecast) {
    series.push({
      name: '预估销量',
      type: 'bar',
      xAxisIndex: 1,
      yAxisIndex: 1,
      z: 2,
      barGap: '-100%',
      color: CH.forecastBar,
      // 落在高亮窗口内的柱子换成强调色实心。**「圈出来」由柱子本身承担**，
      // 不靠一块底色 —— 底色只能说明「这一段被框住了」，柱子变色才说明
      // 「这一段的量就是我们要的那个数」。（一版用浅蓝背景块，糊。）
      itemStyle: (hlFrom >= 0
        ? { color: (o) => ((o.dataIndex >= hlFrom && o.dataIndex <= hlTo)
            ? CH.highlightBar : CH.forecastBar) }
        : { color: CH.forecastBar }),
      data: ch.forecast.map(x => (x ? { value: x.value } : null)),
    });

    // 区间用误差线画在柱顶。Agent 给的是带不是线，这条带是投影跑三遍的输入。
    series.push({
      name: '预估区间',
      type: 'custom',
      xAxisIndex: 1,
      yAxisIndex: 1,
      z: 4,
      itemStyle: { color: CH.whisker },
      color: CH.whisker,
      renderItem: (params, api) => {
        const i = api.value(0);
        const lo = api.coord([i, api.value(1)]);
        const hi = api.coord([i, api.value(2)]);
        const half = Math.max(1.5, api.size([1, 0])[0] * 0.18);
        return {
          type: 'group',
          children: [
            { type: 'line', shape: { x1: hi[0], y1: hi[1], x2: hi[0], y2: lo[1] },
              style: { stroke: CH.whisker, lineWidth: 1 } },
            { type: 'line', shape: { x1: hi[0] - half, y1: hi[1], x2: hi[0] + half, y2: hi[1] },
              style: { stroke: CH.whisker, lineWidth: 1 } },
            { type: 'line', shape: { x1: lo[0] - half, y1: lo[1], x2: lo[0] + half, y2: lo[1] },
              style: { stroke: CH.whisker, lineWidth: 1 } },
          ],
        };
      },
      encode: { x: 0, y: [1, 2] },
      data: ch.forecast.map((x, i) => (x ? [i, x.lower, x.upper] : null)).filter(Boolean),
    });
  }

  // --- 事件标注：日期 + 名称 + 横条，每类一条独立序列可单独开关 ---------- //
  //
  // 行位按「时间是否重叠」排，不按事件类型固定。
  // 原来按类型固定高度，是因为横条上没有字、只能靠位置认；标注带了文字之后
  // 那个前提就不存在了，运营读的是名字。不重叠时挤在同一行，顶部只占一行。
  const annos = [];
  ch.bands.forEach(b => annos.push({ ...b, kind: 'band' }));
  ch.points.forEach(pt => annos.push({ ...pt, kind: 'point' }));
  annos.sort((x, y) => x.from_index - y.from_index || x.to_index - y.to_index);
  const rowEnd = [];                      // 每行已占用到的最右 index
  annos.forEach(an => {
    let r = 0;
    while (r < rowEnd.length && rowEnd[r] >= an.from_index) r += 1;
    an.row = r;
    rowEnd[r] = an.to_index;
  });
  const annoRows = Math.max(1, rowEnd.length);

  const ROW_H = ROW_H_PX;                 // 一行标注占的像素（按设计图的间隔算出来）
  // 阈值取「半宽」：文字居中，相邻两条各让出一半就不重叠。
  // 设计图里 06-12 与 06-16 只隔 4 天，两组标注都完整显示 —— 允许挨着，不允许压字。
  const DATE_W = 20;                      // 「06-09」半宽
  const NAME_W = 40;                      // 「Limited Deal」半宽

  // 文字是居中在横条上的，所以该比的是「两条标注的中心距」，
  // 不是「两条横条之间的空隙」—— 后者对多日区间会严重低估可用宽度，
  // 结果本来放得下的名称被误藏（06-09 Limited Deal 旁边的 06-14 Coupon 就中过）。
  annos.forEach((an, i) => {
    an.centre = (an.from_index + an.to_index) / 2;
    an.prevGap = i === 0 ? 9999 : an.centre - annos[i - 1].centre;
  });

  const drawAnno = (color, list) => (params, api) => {
    const an = list[params.dataIndex];     // 字符串维度不能走 api.value，会得到 NaN
    const x1 = api.coord([an.from_index, 0])[0];
    const x2 = api.coord([an.to_index, 0])[0];
    const bw = Math.max(1, api.size([1, 0])[0]);
    // 直接按上层 grid 的像素排版，不依赖泳道轴刻度 —— 文字高度是像素概念，
    // 用轴刻度换算会随行数变化而漂。
    const cs = params.coordSys;
    const barY = cs.y + cs.height - 5 - an.row * ROW_H;
    const cx = (x1 + x2) / 2;
    const left = x1 - bw / 2;
    const width = (x2 - x1) + bw;
    // 分级降级：空间够就日期+名称，紧了先丢名称留日期，极紧了才都不画。
    // 日期只有五个字符，比名称窄得多 —— 全有全无会在中等间距时白丢掉信息。
    const gapPx = an.prevGap * bw;
    const kids = [];
    if (gapPx >= DATE_W) {
      kids.push({ type: 'text', style: { text: an.from.slice(5), x: cx,
        y: barY - ANNO.dateTop, fill: color, fontFamily: FONT, fontSize: FS.anno,
        fontWeight: 600, align: 'center', verticalAlign: 'top' } });
      if (an.kind !== 'point' && gapPx >= NAME_W) {
        kids.push({ type: 'text', style: { text: an.type_label, x: cx,
          y: barY - ANNO.nameTop, fill: color, fontFamily: FONT, fontSize: FS.annoName,
          align: 'center', verticalAlign: 'top' } });
      }
    }
    if (an.kind === 'point') {
      // 单日事件只给一个圆点：一天的事件没有区间可言
      kids.push({ type: 'circle', shape: { cx, cy: barY, r: 3 }, style: { fill: color } });
    } else {
      kids.push({ type: 'rect',
        shape: { x: left, y: barY - ANNO.barH / 2, width, height: ANNO.barH, r: ANNO.barH / 2 },
        style: { fill: color } });
    }
    return { type: 'group', children: kids };
  };

  ch.lanes.forEach(ln => {
    const color = CH.lane[ln.event_type] || CH.lane.other;
    const mine = annos.filter(an => an.event_type === ln.event_type);
    if (!mine.length) return;
    series.push({
      name: ln.label,
      type: 'custom',
      xAxisIndex: 0,
      yAxisIndex: 0,
      z: 6,
      color: color,
      itemStyle: { color: color },
      // 图例图形：事件用短横线，柱用方块，一眼分清「区间」和「量」
      legendIcon: 'path://M0,1 H28 V5 H0 Z',
      renderItem: drawAnno(color, mine),
      encode: { x: [0, 1] },
      data: mine.map(an => [an.from_index, an.to_index]),
    });
  });

  // --- 叠加折线：不进主图例，走第二排开关，默认全关 --------------------- //
  const metricNames = [];
  ch.lines.forEach(m => {
    const name = m.label + (m.is_constant ? '（未变动）' : '');
    metricNames.push(name);
    const color = CH.metric[m.label] || '#6b6b73';
    series.push({
      name,
      type: 'line',
      xAxisIndex: 1,
      yAxisIndex: m.unit === '$' ? 2 : (m.unit === '%' ? 4 : 3),
      z: 5,
      color,
      itemStyle: { color },
      lineStyle: { width: 1.4, color },
      showSymbol: false,
      connectNulls: false,
      // 价格是「保持到下次变动」的状态量，用台阶画才对；金额流量是逐日量，用折线
      step: (m.key === 'price' || m.key === 'list_price') ? 'end' : false,
      data: m.values,
    });
  });

  // --- 分界线：markLine 必须挂在某条序列上，造一条空序列承载 ------------ //
  const marks = [];
  if (ch.as_of_index != null) {
    marks.push({
      xAxis: ch.as_of_index,
      // 不给文字：markLine 挂在 xAxis 上标签会竖排，很难读，而深色柱转浅色柱
      // 本身已经把「这里之后是预估」说清楚了，再加一行竖字是冗余。
      label: { show: false },
      lineStyle: { color: CH.divider, type: 'solid', width: 1, opacity: 0.5 },
    });
  }
  if (ch.forecast_start_index != null && ch.forecast_start_index !== ch.as_of_index + 1) {
    marks.push({
      xAxis: ch.forecast_start_index,
      label: { show: false },
      lineStyle: { color: CH.label, type: 'dashed', width: 1 },
    });
  }
  series.push({
    name: '__divider__',
    type: 'bar',
    xAxisIndex: 1,
    yAxisIndex: 1,
    data: [],
    silent: true,
    markLine: { silent: true, symbol: 'none', data: marks },
  });


  // 默认视窗：基准日往前 90 天 + 全部预估。两年历史一次画满不可读，
  // 但只给 30 天历史又看不出节奏，所以默认落在这个区间，其余靠缩放。
  const zoomStart = Math.max(0, (ch.as_of_index != null ? ch.as_of_index : ch.dates.length - 1) - 90);

  chartInst = echarts.init(box, null, { renderer: 'canvas' });
  chartInst.setOption({
    animation: false,
    // 图表里的字统一到页面字体栈：ECharts 默认 sans-serif，与 HTML 不是同一套字形
    textStyle: { fontFamily: FONT },
    // 两个 grid：上面一条窄带专放事件泳道，下面是主图。
    // 物理分开，泳道就不会横穿柱子，柱轴也不用为了让位而改量程。
    // 泳道带高度按「所有可能的泳道数」给，不按当前对象用到的条数给：
    // 同一类事件在不同子体上必须落在同一高度，否则运营得重新认一遍。
    // 但一个事件都没有时就整条收起 —— 342 个子体里 334 个没有事件，
    // 那是常见情况不是边缘情况，留着一条空带会让图看起来是坏的。
    // 上层 grid 高度按标注实际行数给（每行 34px 装两行字加一条横条），
    // 没有事件就整条收起 —— 留一条空带会让图看起来是坏的。
    // 顶部留两排图例（第一排 top 4，第二排 top 24），所以 grid 从 48 起
    grid: annoRows === 0 || !ch.lanes.length
      ? [{ left: 52, right: 46, top: 50, height: 1, show: false },
         { left: 52, right: 46, top: 54, bottom: 66 }]
      : [{ left: 52, right: 46, top: 44, height: annoRows * ROW_H_PX + 4 },
         { left: 52, right: 46, top: 44 + annoRows * ROW_H_PX + 10, bottom: 66 }],
    legend: [
      // 第一排：这张图是什么 —— 量 + 那几天做了什么
      {
        type: 'plain', top: 4, left: 8, right: 8,
        itemWidth: 13, itemHeight: 9, itemGap: 16,
        textStyle: { color: '#4a4a4e', fontSize: FS.legend, fontFamily: FONT },
        inactiveColor: '#c7c7cc',
        // 预估区间是预估柱顶那条竖线，不单独占一个图例位
        data: series
          .filter(x => x.name !== '__divider__' && x.name !== '预估区间'
                       && x.name !== HL_SERIES_NAME
                       && metricNames.indexOf(x.name) < 0)
          .map(x => x.name),
      },
      // 第二排：能额外压上来的指标。从属样式，默认全关 —— 八条一起画会糊成一片。
      {
        type: 'scroll', top: 24, left: 56, right: 8,
        itemWidth: 18, itemHeight: 2, itemGap: 13,
        icon: 'path://M0,4 H22 V6 H0 Z',
        textStyle: { color: '#6b6b73', fontSize: FS.legendSub, fontFamily: FONT },
        inactiveColor: '#d4d4d8',
        pageIconSize: 9,
        pageTextStyle: { color: '#6b6b73', fontSize: FS.legendSub },
        selected: Object.fromEntries(metricNames.map(n => [n, false])),
        data: metricNames,
      },
    ],
    // 第二排前面那个小标题。legend 组件本身没有 title，用 graphic 放一个。
    graphic: metricNames.length ? [{
      type: 'text', left: 8, top: 25, silent: true,
      style: { text: '叠加', fill: '#9ca3af', fontSize: FS.legendSub, fontFamily: FONT },
    }] : [],
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'line', lineStyle: { color: '#d4d4d8' } },
      backgroundColor: '#ffffff',
      borderColor: '#e4e4e7',
      borderWidth: 1,
      padding: 0,
      extraCssText: 'box-shadow:0 10px 30px rgba(9,9,11,.13);border-radius:10px;overflow:hidden',
      formatter: params => {
        const i = Array.isArray(params) ? params[0].dataIndex : params.dataIndex;
        return dayTooltip(ch, i);
      },
    },
    // 两个 grid 的十字准线要联动，否则悬停时泳道和柱子对不上同一天。
    axisPointer: { link: [{ xAxisIndex: 'all' }] },
    dataZoom: [
      { type: 'slider', xAxisIndex: [0, 1], height: 20, bottom: 26,
        borderColor: 'transparent', backgroundColor: '#f4f4f5',
        fillerColor: 'rgba(17,17,19,.07)',
        handleStyle: { color: '#ffffff', borderColor: '#a1a1aa' },
        moveHandleSize: 0,
        dataBackground: { lineStyle: { color: '#c7c7cc' }, areaStyle: { color: '#e4e4e7' } },
        selectedDataBackground: { lineStyle: { color: '#8b8b93' }, areaStyle: { color: '#d4d4d8' } },
        textStyle: { color: CH.label, fontSize: FS.axis },
        startValue: zoomStart, endValue: ch.dates.length - 1 },
      { type: 'inside', xAxisIndex: [0, 1], zoomOnMouseWheel: false,
        moveOnMouseWheel: false, moveOnMouseMove: true },
    ],
    xAxis: [
      { type: 'category', gridIndex: 0, data: ch.dates, show: false,
        axisPointer: { show: false } },
      { type: 'category', gridIndex: 1, data: ch.dates,
        axisLine: { lineStyle: { color: CH.axis } },
        axisTick: { show: false },
        // 标签密度交给 ECharts 按可用宽度算：写死 5 天一格在窄容器里会糊成一片
        axisLabel: { color: CH.label, fontSize: FS.axis, hideOverlap: true,
          formatter: v => v.slice(5) } },
    ],
    yAxis: [
      // 0 事件泳道：在上层 grid 里，量程固定，每类事件一个固定整数高度，永不漂移
      // 标注序列的 y 直接按上层 grid 像素排版，这根轴只是它的落脚点
      { type: 'value', gridIndex: 0, show: false, min: 0, max: 1 },
      // 1 件数（柱）
      { type: 'value', gridIndex: 1, name: '件',
        nameTextStyle: { color: CH.label, fontSize: FS.axisName, align: 'right' },
        splitLine: { lineStyle: { color: '#f4f4f5' } },
        axisLabel: { color: CH.label, fontSize: FS.axis } },
      // 叠加折线按量纲分三根轴，且都从 0 起（min: 0, scale: false）。
      //
      // 原来两根轴都开了 scale:true，于是 ECharts 按数据范围自动缩放：售价实测
      // 只有 $50.13~$58.99、波动 1.5%，却被拉满整个绘图高度，一条几乎不动的线
      // 画成了大起大落 —— 而轴是隐藏的，看的人根本无法判断量级。从 0 起之后
      // 平的就看着是平的。
      //
      // 分三组是因为比率和计数没法共轴：转化率 0~0.15 跟访问量几百放一起，
      // 转化率会被压成贴着零轴的一条直线。
      { type: 'value', gridIndex: 1, show: false, min: 0, scale: false },   // 2 金额 $
      { type: 'value', gridIndex: 1, show: false, min: 0, scale: false },   // 3 计数
      { type: 'value', gridIndex: 1, show: false, min: 0, scale: false },   // 4 比率 %
    ],
    series,
  });

  // 悬停是 axis 触发，整列都响应；点击必须一样，否则提示写着「点击这一天」
  // 而用户点在柱子之间就没反应 —— 柱子只有几个像素宽，那是个打不中的靶子。
  // series 的 click 只在命中图形时才触发，所以改成在 zrender 层按 x 反查列。
  chartInst.getZr().on('click', ev => {
    const x = ev.offsetX, y = ev.offsetY;
    let idx = null;
    for (const gi of [1, 0]) {
      if (chartInst.containPixel({ gridIndex: gi }, [x, y])) {
        const v = chartInst.convertFromPixel({ gridIndex: gi }, [x, y]);
        if (v && v[0] != null) { idx = Math.round(v[0]); }
        break;
      }
    }
    if (idx == null || idx < 0 || idx >= ch.dates.length) return;
    detail.innerHTML = dayDetail(a, ch, idx);

    /* 把详情条滚进视口。
     *
     * 这张图 452px 高，详情条又有 300~400px。上面还有页头和指标条时，一个
     * 720p 视口装不下「图 + 详情条」—— 实测预投依据页详情条在 top=867，
     * 视口只有 720，要往下滚 541px 才看得见。用户点了柱子、内容确实换了，
     * 但屏幕上什么都没动，表现成「这个图点不了」。反应必须落在眼睛能看到的地方。
     *
     * block:'nearest' 是关键：只滚最小距离把它带进来，已经可见时一动不动。
     * 用 'end' 或 'center' 会在连着点几天时把页面弹来弹去。
     */
    if (detail.getBoundingClientRect().bottom > window.innerHeight) {
      detail.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }
  });

  if (!window.__chartResizeBound) {
    window.addEventListener('resize', () => { if (chartInst) chartInst.resize(); });
    window.__chartResizeBound = true;
  }
}
