/* 面料预投模块 · 图表
 *
 * ⚠️ 逐日图不在这里 —— 那张图是 web/daychart.js（外壳共享组件，与库存单品盘点页
 * 共用同一份）。这里曾经有一个自写的 windowChart，2026-09-04 删掉了：
 * 同一件事画两张图必然漂移，而库存那张更全（缺货带、活动泳道、叠加指标）。
 *
 * 剩下这两张原本服务已删除的预投考核页，暂时无人调用，保留待用：
 *   histogram  达成率分布     考核线画成一条竖线，看偏差是普遍性还是少数整批错
 *   pace       分批下单节奏   一次预投对应多批下单，缺口就是没用掉的面料
 *
 * 计划页与依据页不用图表。它们要回答的是「该投多少」和「这个数该不该改」，
 * 答案是一个可改的数字加几条并列的事实 —— 那些用表格和数字块比用图准确。
 * （上一版这里有一张「预投构成瀑布」，画的是三段 AI 判断各调了多少。
 *   它在 Agent 未接通时三段全空，而接通后同样的信息在依据页用三张理由卡
 *   讲得更清楚，所以整块删掉，不留死代码。）
 *
 * ECharts 从外壳的 assets 取（已在 index.html 里加载为全局 echarts）。
 * 实例存在这里，unmount 时统一 dispose —— 不清会留着 resize 监听和 canvas。
 */

/* 字号与字体栈：与外壳 web/tokens.css 的 --fs-* 阶梯同一组值。
   图表里不能写 var(--fs-*)（ECharts 只吃数字），所以镜像一份。
   镜像天生会漂，所以门禁 G24 机械核对这份表与 tokens.css 一致，
   G23 禁止在使用处写裸数字 —— 只准写 FS.axis 这种名字。 */
const FS = {
  axis: 11,        // 轴刻度              --fs-axis
  anno: 12,        // 图上标注的日期        --fs-anno
  meta: 13,        // 图例、轴名、标注名称   --fs-meta
};

const CHARTS = new Map();

/* ECharts 不在 index.html 里 —— 外壳不预加载它，库存模块是自己按需注入
   script 标签的（web/modules/inventory/daychart.js 的 loadECharts）。
   这里照同一条路走，并且**共用 window.echarts**：两个模块各注入一次会
   重复下载 1 MB。

   第一版这里写成 `if (!window.echarts) return null;` —— 结果是图区一片空白
   且控制台没有任何报错，是最难查的那种。所以现在：加载失败要在页面上
   看得见（renderFail），绝不静默留白。 */
let loading = null;

function loadECharts() {
  if (window.echarts) return Promise.resolve(window.echarts);
  if (loading) return loading;
  loading = new Promise((resolve, reject) => {
    const tag = document.createElement('script');
    tag.src = '/assets/echarts.min.js';
    tag.onload = () => resolve(window.echarts);
    tag.onerror = () => reject(new Error('图表库加载失败'));
    document.head.appendChild(tag);
  });
  return loading;
}

function renderFail(node, why) {
  node.textContent = '';
  const d = document.createElement('div');
  d.className = 'pre-chartfail';
  d.textContent = why;
  node.appendChild(d);
}

function readVar(name, fallback) {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

/* 颜色一律从 tokens.css 取，模块不定义自己的色值（G3）。 */
function palette() {
  return {
    ink: readVar('--ink', '#111113'),
    dim: readVar('--fg3', '#6b6b73'),
    line: readVar('--glass-line', 'rgba(17,17,19,0.10)'),
    accent: readVar('--accent', '#2563eb'),
    good: readVar('--good', '#3a7d43'),
    warn: readVar('--warn', '#a8620d'),
    bad: readVar('--alert', '#c9372c'),
    surface: readVar('--bg1', '#ffffff'),
  };
}

async function mount(node, key) {
  let lib;
  try {
    lib = await loadECharts();
  } catch (e) {
    renderFail(node, '图表库加载失败，数字仍可在下方表格与摘要里读到');
    return null;
  }
  if (!lib) { renderFail(node, '图表库不可用，数字仍可在下方表格与摘要里读到'); return null; }
  let inst = CHARTS.get(key);
  if (inst && inst.getDom() !== node) { inst.dispose(); inst = null; }
  if (!inst) { inst = lib.init(node); CHARTS.set(key, inst); }
  return inst;
}

export function disposeCharts() {
  for (const inst of CHARTS.values()) { try { inst.dispose(); } catch { /* 已 dispose */ } }
  CHARTS.clear();
}

const BASE_TEXT = (p) => ({
  fontFamily: readVar('--sans', 'system-ui'),
  color: p.ink,
});

/* ------------------------------------------------------------------------
 * §4.2 达成率分布 —— 考核线单独一条竖线，线左侧警示色
 *
 * 桶边界在后端已经把考核线做成一条边（compute.audit 的 edges），
 * 所以这里不需要再判断某个桶是否跨线 —— 跨线的桶会让「达标几个」
 * 和图上看到的对不上。
 * ---------------------------------------------------------------------- */
export async function histogram(node, buckets, lineLabel, opts = {}) {
  const inst = await mount(node, opts.key || 'histogram');
  if (!inst) return;
  const p = palette();
  const firstOk = buckets.findIndex((b) => !b.below_line);

  inst.setOption({
    animation: false,
    textStyle: BASE_TEXT(p),
    grid: { left: 8, right: 8, top: 30, bottom: 34, containLabel: true },
    tooltip: {
      trigger: 'axis', axisPointer: { type: 'shadow' },
      backgroundColor: p.surface, borderColor: p.line, textStyle: { color: p.ink },
      formatter: (arr) => {
        const b = buckets[arr[0].dataIndex];
        return `<b>达成率 ${b.label}</b><br>${b.count} 个配色组`
             + `<br><span style="color:${p.dim}">${b.below_line ? '未达考核线' : '达标'}</span>`;
      },
    },
    xAxis: {
      type: 'category', data: buckets.map((b) => b.label),
      axisLabel: { color: p.dim, fontSize: FS.axis, interval: 0 },
      axisLine: { lineStyle: { color: p.line } }, axisTick: { show: false },
    },
    yAxis: {
      type: 'value', name: '配色组数',
      nameTextStyle: { color: p.dim, fontSize: FS.axis },
      axisLabel: { color: p.dim, fontSize: FS.axis },
      splitLine: { lineStyle: { color: p.line, type: 'dashed' } },
    },
    series: [{
      type: 'bar', barMaxWidth: 60,
      data: buckets.map((b) => ({
        value: b.count,
        itemStyle: { color: b.below_line ? p.bad : p.good },
      })),
      label: { show: true, position: 'top', color: p.ink, fontSize: FS.axis },
      markLine: firstOk > 0 ? {
        silent: true, symbol: 'none',
        lineStyle: { color: p.ink, width: 1, type: 'solid' },
        label: { formatter: lineLabel || '考核线', color: p.ink, fontSize: FS.axis,
                 position: 'insideEndTop' },
        data: [{ xAxis: firstOk - 0.5 }],
      } : undefined,
    }],
  }, true);
  inst.resize();
}

/* ------------------------------------------------------------------------
 * §4.8 分批下单节奏 —— 预投是水平线，累计下单是阶梯，两线之间就是闲置
 *
 * 闲置画成 areaStyle 填充的缺口，让「投了但没用掉」变成一块可见的面积，
 * 而不是一个要自己减的数。
 * ---------------------------------------------------------------------- */
export async function pace(node, batches, preinvestLine, opts = {}) {
  const inst = await mount(node, opts.key || 'pace');
  if (!inst) return;
  const p = palette();
  const dates = batches.map((b) => b.batch_date);
  const cum = batches.map((b) => b.cumulative);

  inst.setOption({
    animation: false,
    textStyle: BASE_TEXT(p),
    grid: { left: 8, right: 16, top: 30, bottom: 34, containLabel: true },
    tooltip: {
      trigger: 'axis',
      backgroundColor: p.surface, borderColor: p.line, textStyle: { color: p.ink },
      formatter: (arr) => {
        const k = arr[0].dataIndex;
        const b = batches[k];
        const gap = preinvestLine - b.cumulative;
        return `<b>第 ${b.batch_no} 批 · ${b.batch_date}</b>`
             + `<br>本批下单 ${b.order_units.toLocaleString('zh-CN')} 盒（${b.group_count} 个配色组）`
             + `<br>累计下单 ${b.cumulative.toLocaleString('zh-CN')} 盒`
             + `<br><span style="color:${p.dim}">距预投量还差 ${gap.toLocaleString('zh-CN')} 盒</span>`;
      },
    },
    xAxis: {
      type: 'category', data: dates,
      axisLabel: { color: p.dim, fontSize: FS.axis },
      axisLine: { lineStyle: { color: p.line } }, axisTick: { show: false },
    },
    yAxis: {
      type: 'value', name: '盒', min: 0,
      max: Math.ceil(preinvestLine * 1.05),
      nameTextStyle: { color: p.dim, fontSize: FS.axis },
      axisLabel: { color: p.dim, fontSize: FS.axis },
      splitLine: { lineStyle: { color: p.line, type: 'dashed' } },
    },
    series: [
      { name: '累计下单', type: 'line', step: 'end', data: cum,
        symbol: 'circle', symbolSize: 6,
        lineStyle: { color: p.accent, width: 2 },
        itemStyle: { color: p.accent },
        areaStyle: { color: p.accent, opacity: 0.10 },
        markLine: {
          silent: true, symbol: 'none',
          lineStyle: { color: p.bad, width: 1, type: 'dashed' },
          label: { formatter: `预投 ${preinvestLine.toLocaleString('zh-CN')} 盒`,
                   color: p.bad, fontSize: FS.axis, position: 'insideStartTop' },
          data: [{ yAxis: preinvestLine }],
        } },
    ],
  }, true);
  inst.resize();
}
