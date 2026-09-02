// 最小 DOM 垫片：让真模块跑在 Node 里，抓运行时错误与图表配置。
// 宿主从 new Function(裸脚本) 换成 import() 真 ES module + 假 ctx 调 mount()。
const errors = [];
const made = [];
function mkNode(tag) {
  const n = {
    tagName: tag, className: '', _html: '', children: [], dataset: {}, value: '', textContent: '',
    style: {}, disabled: false,
    set innerHTML(v) { this._html = String(v); }, get innerHTML() { return this._html; },
    appendChild(c) { this.children.push(c); return c; },
    addEventListener() {}, classList: { toggle() {}, add() {}, remove() {}, contains: () => false },
    querySelector: () => mkNode('div'), querySelectorAll: () => [],
    closest: () => null, contains: () => false, offsetWidth: 300,
    getBoundingClientRect: () => ({ top: 0, left: 0, bottom: 0, right: 0, width: 0, height: 0 }),
  };
  made.push(n);
  return n;
}
const registry = new Map();
global.document = {
  createElement: mkNode,
  body: mkNode('body'),
  addEventListener() {},
  querySelector(sel) { if (!registry.has(sel)) registry.set(sel, mkNode('div')); return registry.get(sel); },
  querySelectorAll() { return []; },
};
global.window = global;
global.innerWidth = 1440;
global.scrollY = 0;
global.scrollX = 0;
global.addEventListener = () => {};
global.fetch = async (u) => {
  const res = await (await import('node:https')).default ? null : null;
  const r = await (await import('node:http')).default.get;
  return new Promise((resolve, reject) => {
    require('node:http').get('http://127.0.0.1:18820' + u, (resp) => {
      let d = ''; resp.on('data', c => d += c);
      resp.on('end', () => resolve({ json: async () => JSON.parse(d) }));
    }).on('error', reject);
  });
};
global.require = (await import('node:module')).createRequire(import.meta.url);
process.on('unhandledRejection', (e) => errors.push('unhandledRejection: ' + (e && e.stack || e)));


// ECharts stub: records the option so the chart config can be checked without a
// canvas. Real rendering still needs the browser -- this only verifies wiring.
const chartOptions = [];
let detailNode = null;
// 桩必须把回调**记下来**，不能吞掉。吞掉的后果实测过一次：
// 8 条门禁全绿，而页面上鼠标一碰图表就抛 ReferenceError（n0/n1/n2 在
// ES module 化之后没跟着导入），因为 tooltip 格式化和点击处理从没被调用过。
const zrHandlers = {};      // 事件名 -> 处理函数
const chartHandlers = {};
global.echarts = {
  version: 'stub',
  init: () => ({
    setOption: (o) => chartOptions.push(o),
    on: (name, fn) => { chartHandlers[name] = fn; },
    getZr: () => ({ on: (name, fn) => { zrHandlers[name] = fn; } }),
    dispose: () => {},
    resize: () => {},
    dispatchAction: () => {},
    // 点击走 zrender 层按 x 反查列，所以这两个必须能返回可用值，
    // 否则处理函数会在第一个 if 就 return，等于没测到。
    containPixel: () => true,
    convertFromPixel: (_finder, [x]) => [Math.max(0, Math.round(x)), 0],
  }),
  getInstanceByDom: () => null,
};

// ---- 造一个假 ctx，调真模块的 mount() -------------------------------------
// 这比原来的 new Function 更接近真实：走的是外壳与模块之间的契约本身。
// el 与外壳 web/shell.js 的实现保持一致（class / text / html / on* / 其余 setAttribute）。
function el(tag, attrs = {}, children = []) {
  const node = mkNode(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') node.className = v;
    else if (k === 'text') node.textContent = v;
    else if (k === 'html') node.innerHTML = v;
    else if (k.startsWith('on') && typeof v === 'function') { /* 垫片不派发事件 */ }
    else node.dataset[k] = v;
  }
  for (const c of [].concat(children)) if (c) node.appendChild(c);
  return node;
}

const DASH = '—';
const PROBE_ASIN = 'B0F4R834YP';   // 2 类事件 12 段 + 59 缺货日，见文件末尾的靶子说明

const slots = { rail: mkNode('aside'), body: mkNode('div') };
const fakeCtx = {
  moduleId: 'inventory',
  $: (s) => document.querySelector(s), $$: () => [], el,
  fmt: {
    int: (v) => (v == null ? DASH : Math.round(v).toLocaleString('zh-CN')),
    num: (v, d = 1) => (v == null ? DASH : Number(v).toFixed(d)),
    pct: (v, d = 1) => (v == null ? DASH : `${(Number(v) * 100).toFixed(d)}%`),
    money: (v, d = 2) => (v == null ? DASH : `$${Number(v).toFixed(d)}`),
    days: (v, d = 1) => (v == null ? DASH : `${Number(v).toFixed(d)} 天`),
    date: (v) => v || DASH, dash: DASH,
  },
  nature: () => null, cond: () => null,
  state: {}, shared: {}, filters: {},
  objectId: PROBE_ASIN, pageId: 'inv-detail', asOf: '2026-08-03',
  setShared() {}, setFilters() {}, open() {},
  async api(resource) {
    const r = await fetch('/api/inventory/' + resource);
    return r.json();
  },
  drawer: { open() {}, close() {} },
  pop: { show() {}, close() {} },
  placeholder: (t, d) => el('div', { html: `<div class="ph">${t}${d ? ' · ' + d : ''}</div>` }),
};

let impl = null;
// 三个页面都渲染一遍。只渲染 inv-detail 的话，异常总览与库存全览
// 任何一个运行时错误都抓不到 —— 曾经就是这样漏掉了 SEV_LABEL 未导入。
const pageHtml = {};
try {
  impl = await import(new URL('../../../web/modules/inventory.js', import.meta.url).href);
  await impl.mount(slots, fakeCtx);
  for (const pid of ['inv-detail', 'inv-risk', 'inv-scope']) {
    fakeCtx.pageId = pid;
    fakeCtx.objectId = pid === 'inv-detail' ? PROBE_ASIN : null;
    slots.body = mkNode('div');
    slots.rail = mkNode('aside');
    try {
      await impl.render(fakeCtx);
      pageHtml[pid] = collect(slots.body);
    } catch (e) {
      errors.push(`render(${pid}) throw: ` + (e && e.stack || e));
      pageHtml[pid] = '';
    }
  }
  fakeCtx.pageId = 'inv-detail';
  fakeCtx.objectId = PROBE_ASIN;
} catch (e) {
  errors.push('mount throw: ' + (e && e.stack || e));
}

// 垫片的 innerHTML 只存在被赋值的那个节点上，所以要连子树一起收
function collect(node) {
  if (!node) return '';
  let out = node._html || '';
  for (const c of node.children || []) out += collect(c);
  return out;
}
// 图表入口从模块里取，不再靠 new Function 传出来
const renderDayChart = impl
  ? (await import(new URL('../../../web/modules/inventory/daychart.js', import.meta.url).href)).renderDayChart
  : null;
await new Promise(r => setTimeout(r, 1500));
const detail = made.concat([slots.rail, slots.body], [...registry.values()])
  .map(n => (n && n._html) || '').join('');
console.log('runtime errors:', errors.length);
errors.slice(0, 8).forEach(e => console.log('  ✗', e));
console.log('rendered html chars:', detail.length);
let bad = 0;
for (const probe of ['产品与盘点结果','销量与需求','库存盘点','在途与到货','库存承接','库龄','仓储费','风险点与形成原因','数据与口径']) {
  const ok = detail.includes(probe);
  if (!ok) bad++;
  console.log(`  ${ok ? '✓' : '✗'} 板块 ${probe}`);
}

// 三页都必须真渲染出东西。空白页不该算通过 —— 外壳会把渲染异常吃成占位块，
// 页面上看着是"模块渲染出错"，而只看 detail 的门禁照样全绿。
for (const [pid, label, need] of [['inv-detail','单品盘点','销量与需求'],
                                  ['inv-risk','异常总览','风险版图'],
                                  ['inv-scope','库存全览','范围概览']]) {
  const html = pageHtml[pid] || '';
  const ok = html.length > 400 && html.includes(need);
  if (!ok) bad++;
  console.log(`  ${ok ? '✓' : '✗'} ${label} 渲染出内容（${html.length} 字符，含「${need}」${html.includes(need)}）`);
}
// method notes must be behind a click marker, not inline prose
const marks = (detail.match(/class="info"/g) || []).length;
console.log(`  ${marks >= 6 ? '✓' : '✗'} 方法说明标记 ${marks} 个`);
if (marks < 6) bad++;
console.log(`  ${detail.includes('<details class="fold"') ? '✓' : '✗'} 底部折叠区`);
if (!detail.includes('<details class="fold"')) bad++;
// defensive prose must be gone from the page surface
for (const gone of ['不代表客户经营事实','不作为判断依据','差异不抹平','不是 Amazon 公布费率',
                    '仅作节奏参考','P1 阶段','数据包已知限制','未与客户月度仓储费总额对账','收货日为假设']) {
  const present = detail.includes(gone);
  if (present) bad++;
  console.log(`  ${present ? '✗ 仍在页面上' : '✓ 已移除'} ${gone}`);
}
// internal enum keys must never reach the screen as labels
for (const key of ['can_absorb', 'cannot_absorb', '>limited<', 'customer_actual_derived', 'per_sellable_unit']) {
  const present = detail.includes(key);
  if (present) bad++;
  console.log(`  ${present ? '✗ 枚举值漏到界面' : '✓ 无枚举泄漏'} ${key}`);
}
// percentage-width bars must not sit on inline elements (width/height are ignored there)
const css = require('node:fs').readFileSync(new URL('../../../web/modules/inventory.css', import.meta.url), 'utf8');
const fillRule = (css.match(/\.bars \.fill\{[^}]*\}/) || [''])[0];
const fillOk = /display:block/.test(fillRule) && /position:absolute/.test(fillRule);
console.log(`  ${fillOk ? '✓' : '✗'} 库龄柱 .bars .fill 是 block+absolute（行内会塌成 0 宽）`);
if (!fillOk) bad++;

// --- 交互回调门禁（真调，不只看配置）------------------------------------------ //
// 这一组是补一个真实事故：ES module 化切断了原来靠全局作用域共享的
// n0/n1/n2，加载时不报错，只在 tooltip 格式化与当天详情**被调用的那一刻**
// 才抛 ReferenceError。也就是说，只有鼠标碰上去才会暴露。
// 所以门禁必须把回调请出来跑一遍，而不是确认它存在。
{
  const opt = chartOptions[chartOptions.length - 1];

  // 1) tooltip 格式化：拿 axis 触发的真实参数形状调一次
  let tipOk = false, tipErr = '', tipLen = 0;
  try {
    const fmt = (opt.tooltip && [].concat(opt.tooltip)[0] || {}).formatter;
    if (typeof fmt !== 'function') throw new Error('tooltip.formatter 不是函数');
    const html = fmt([{ dataIndex: 700, seriesName: '实际销量', value: 12 }]);
    tipLen = String(html || '').length;
    tipOk = typeof html === 'string' && tipLen > 40;
    if (!tipOk) tipErr = `返回 ${typeof html}，长度 ${tipLen}`;
  } catch (e) { tipErr = e.message; }
  console.log(`  ${tipOk ? '✓' : '✗'} tooltip 格式化真调不抛错（产出 ${tipLen} 字符）${tipErr ? ' —— ' + tipErr : ''}`);
  if (!tipOk) bad++;

  // 2) 点击：zrender 层的处理函数按 x 反查列，然后写当天详情
  // 详情节点从垫片的全局节点表里找，不从某个 mount 里找 ——
  // 垫片的 querySelector 每次返回新节点，而这段门禁跑在探针循环之前，
  // 依赖执行顺序会取到空引用（第一版就是这么失败的）。
  let clickOk = false, clickErr = '';
  try {
    const fn = zrHandlers.click;
    if (typeof fn !== 'function') throw new Error('没有注册 zrender click 处理函数');
    const node = made.filter(
      (n) => n && typeof n.className === 'string' && n.className.includes('daydetail')
    ).pop();
    if (!node) throw new Error('没找到 .daydetail 节点');
    const before = node._html || '';
    fn({ offsetX: 700, offsetY: 200, target: {} });
    const after = node._html || '';
    clickOk = !!after && after !== before && after.length > 80;
    if (!clickOk) clickErr = `详情长度 ${after.length}，与点击前${after === before ? '相同' : '不同'}`;
  } catch (e) { clickErr = e.message; }
  console.log(`  ${clickOk ? '✓' : '✗'} 点击写出当天详情${clickErr ? ' —— ' + clickErr : ''}`);
  if (!clickOk) bad++;

  // 3) 时间条必须在（拖不动等于 820 天全挤在一屏）
  const zooms = (opt.dataZoom || []).map(z => z.type);
  const zoomOk = zooms.includes('slider') && zooms.includes('inside');
  console.log(`  ${zoomOk ? '✓' : '✗'} 时间条 slider + inside 都在（${zooms.join(' ') || '无'}）`);
  if (!zoomOk) bad++;
}

// --- 字号阶梯门禁 ----------------------------------------------------------- //
// 视觉基准要则第一节：字号只用七级，模块里不得出现字号字面量。
// 查之前先剥注释 —— 注释里会写"原来是 font-size:17px"这类说明，那是文档不是规则。
{
  const LADDER = new Set(['--fs-axis','--fs-anno','--fs-meta','--fs-body',
                          '--fs-sub','--fs-value','--fs-title','--fs-num']);
  const strip = (t) => t.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');

  const cssRaw = require('node:fs').readFileSync(
    new URL('../../../web/modules/inventory.css', import.meta.url), 'utf8');
  const css = strip(cssRaw);

  const lits = css.match(/font-size:\s*[\d.]+px/g) || [];
  console.log(`  ${lits.length === 0 ? '✓' : '✗'} CSS 无字号字面量${lits.length ? '（' + [...new Set(lits)].join(' ') + '）' : ''}`);
  if (lits.length) bad++;

  const vars = [...new Set((css.match(/font-size:\s*var\((--fs-[a-z]+)\)/g) || [])
    .map(m => m.match(/(--fs-[a-z]+)/)[1]))];
  const unknown = vars.filter(v => !LADDER.has(v));
  console.log(`  ${unknown.length === 0 ? '✓' : '✗'} CSS 只用七级阶梯（用到 ${vars.length} 档${unknown.length ? '，档外 ' + unknown.join(' ') : ''}）`);
  if (unknown.length) bad++;

  // JS 里的内联字号：CSS 层扫不到，所以必须单独查
  const jsFiles = ['inventory.js', 'inventory/util.js', 'inventory/page-detail.js',
                   'inventory/page-risk.js', 'inventory/page-scope.js'];
  let inline = [];
  for (const f of jsFiles) {
    const t = strip(require('node:fs').readFileSync(
      new URL('../../../web/modules/' + f, import.meta.url), 'utf8'));
    for (const m of t.match(/font-size:\s*[\d.]+px/g) || []) inline.push(f + ' ' + m);
  }
  console.log(`  ${inline.length === 0 ? '✓' : '✗'} JS 无内联字号${inline.length ? '（' + inline.slice(0,3).join('; ') + '）' : ''}`);
  if (inline.length) bad++;

  // 字族：模块内不得用等宽。设计图用的是 SF Pro（比值指纹偏差 0.0220），
  // 等宽的 SF Mono 偏差 0.1115 —— "1" 被画上底衬线撑满字身，比设计图宽近一倍。
  const monoUse = (css.match(/font-family:\s*var\(--mono\)/g) || []).length;
  console.log(`  ${monoUse === 0 ? '✓' : '✗'} CSS 不用等宽字族${monoUse ? '（' + monoUse + ' 处）' : '，全部走 var(--sans)'}`);
  if (monoUse) bad++;

  // 需要列对齐的数字必须带 tabular-nums：换成比例字体后，
  // 不加它多行数字就不对齐了 —— 这是换字族的代价，要显式补上。
  const tabular = (css.match(/font-variant-numeric:\s*tabular-nums/g) || []).length;
  console.log(`  ${tabular >= 10 ? '✓' : '✗'} 数字列对齐声明 ${tabular} 处（需 >=10）`);
  if (tabular < 10) bad++;

  // canvas 侧的字体栈必须与 tokens.css 的 --sans 首项一致。
  // 两处重复，只改一边不会报错，但页面与图表会是两种字形。
  {
    const tok = require('node:fs').readFileSync(
      new URL('../../../web/tokens.css', import.meta.url), 'utf8');
    const m = tok.match(/--sans:\s*([^;]+);/);
    const first = m ? m[1].split(',')[0].trim() : '';
    const dcRaw = require('node:fs').readFileSync(
      new URL('../../../web/modules/inventory/daychart.js', import.meta.url), 'utf8');
    const fm = dcRaw.match(/const FONT = '([^']+)'/);
    const dcFirst = fm ? fm[1].split(',')[0].trim() : '';
    const ok = first && first === dcFirst;
    console.log(`  ${ok ? '✓' : '✗'} 图表字体栈与 --sans 首项一致（${first} / ${dcFirst}）`);
    if (!ok) bad++;
  }

  // canvas 侧的 FS 镜像必须与阶梯同值（CSS 变量进不了 canvas，所以重复了一份）
  const dc = strip(require('node:fs').readFileSync(
    new URL('../../../web/modules/inventory/daychart.js', import.meta.url), 'utf8'));
  const fsBlock = dc.slice(dc.indexOf('const FS = {'), dc.indexOf('};', dc.indexOf('const FS = {')));
  const fsVals = [...fsBlock.matchAll(/^\s*(\w+):\s*(\d+)/gm)].map(m => [m[1], +m[2]]);
  const STEPS = new Set([11,12,13,14,16,22,24,30]);
  const offLadder = fsVals.filter(([, v]) => !STEPS.has(v));
  console.log(`  ${offLadder.length === 0 ? '✓' : '✗'} daychart 的 FS 镜像全在档（${fsVals.length} 项${offLadder.length ? '，档外 ' + offLadder.map(x=>x.join('=')).join(' ') : ''}）`);
  if (offLadder.length) bad++;

  // 硬编码在 option 里、绕过 FS 的字号
  const raw = require('node:fs').readFileSync(
    new URL('../../../web/modules/inventory/daychart.js', import.meta.url), 'utf8');
  const hard = (strip(raw).match(/fontSize:\s*\d+/g) || []);
  console.log(`  ${hard.length === 0 ? '✓' : '✗'} daychart 无绕过 FS 的硬编码字号${hard.length ? '（' + hard.join(' ') + '）' : ''}`);
  if (hard.length) bad++;
}

// --- 逐日柱状图的配置门禁 --------------------------------------------------- //
// 对着挑好的子体各建一次配置。之前这几条门禁跑在一个既无事件也无缺货的对象上，
// 报「泳道 0 条 / 缺货柱 0 根」还照样打勾 —— 没有检查对象的门禁比没有门禁更糟。
const chartProbes = [
  // 靶子必须真的带着要检查的特征。这两个是从 v0.3.0 里按特征挑的：
  //   B0F4R834YP  2 类事件 12 段 + 59 个缺货日 + 126 个需求被扭曲的日子
  //   B0CGLWQVWR  BD + Coupon 15 段（促销爆发场景），43 个缺货日
  // 分界线只期望 1 条：全部对象的预测都从基准日+1 起，第二条标记在结构上不存在，
  // 期望 2 条等于在断言一个 bug。
  { asin: 'B0F4R834YP', wantLanes: 2, wantAnomaly: true, wantStockout: true, wantMarks: 1, wantBand: 1 },
  { asin: 'B0CGLWQVWR', wantLanes: 2, wantAnomaly: true, wantStockout: true, wantMarks: 1, wantBand: 1 },
];
for (const probe of chartProbes) {
  chartOptions.length = 0;
  let payload = null;
  try {
    payload = await (await fetch('/api/inventory/child/' + probe.asin)).json();
  } catch (e) {
    console.log(`  ✗ 取不到 ${probe.asin}: ${e.message}`);
    bad++;
    continue;
  }
  const mount = mkNode('div');
  try {
    await renderDayChart(mount, payload);
    // 当天详情节点：renderDayChart 往挂载点里塞了 .daychart 与 .daydetail 两个
    detailNode = (mount.children || []).find(
      (n) => n && typeof n.className === 'string' && n.className.includes('daydetail')
    ) || null;
  } catch (e) {
    console.log(`  ✗ ${probe.asin} 建图抛错: ${e.message}`);
    bad++;
    continue;
  }
  if (!chartOptions.length) {
    console.log(`  ✗ ${probe.asin} setOption 未被调用`);
    bad++;
    continue;
  }
  const o = chartOptions[chartOptions.length - 1];
  const ser = o.series || [];
  const tag = probe.asin;

  // 1. 事件泳道必须在上层 grid，放主 grid 会横穿柱子
  // 泳道标签名单要跟着 compute._LANE_LABEL 走。漏一个（曾漏过 Limited Deal）
  // 会让门禁数不到那条泳道，报成图的问题，而图其实是对的。
  const laneNames = ['BD 活动', 'Limited Deal', 'Coupon', '价格调整', '广告加投', '市场变动', '其他'];
  const laneSeries = ser.filter(x => x.name && laneNames.some(n => x.name.startsWith(n)));
  const laneWrong = laneSeries.filter(x => x.xAxisIndex !== 0 || x.yAxisIndex !== 0);
  const laneOk = laneSeries.length >= probe.wantLanes && laneWrong.length === 0;
  console.log(`  ${laneOk ? '✓' : '✗'} ${tag} 事件泳道 ${laneSeries.length} 条（需 >=${probe.wantLanes}）且都在上层 grid`);
  if (!laneOk) bad++;

  // 1b. 每类事件的颜色必须不同。颜色表的键写错大小写会让所有泳道落到同一个
  //     fallback 灰，而彩色在这张图上唯一的职责就是区分事件类型 —— 一灰就等于没做。
  const laneColors = laneSeries.map(x => x.color || (x.itemStyle || {}).color);
  const laneDistinct = new Set(laneColors).size;
  const laneColorOk = laneSeries.length < 2 || laneDistinct === laneSeries.length;
  console.log(`  ${laneColorOk ? '✓' : '✗'} ${tag} 泳道颜色各不相同（${laneDistinct}/${laneSeries.length}）`
    + `：${laneColors.join(' ')}`);
  if (!laneColorOk) bad++;

  // 2. 每条序列都要有显式颜色，否则图例色块与图上标记不一致
  const noColor = ser.filter(x => x.name !== '__divider__' && !x.color
                                  && !(x.itemStyle && x.itemStyle.color));
  console.log(`  ${noColor.length === 0 ? '✓' : '✗'} ${tag} 序列均有显式颜色`
    + (noColor.length ? '：缺 ' + noColor.map(x => x.name).join(',') : ''));
  if (noColor.length) bad++;

  // 3. 双 grid + 泳道轴量程固定且隐藏
  const laneAxis = (o.yAxis || [])[0] || {};
  const gridOk = (o.grid || []).length === 2 && laneAxis.gridIndex === 0
                 && laneAxis.show === false && laneAxis.min != null && laneAxis.max != null;
  console.log(`  ${gridOk ? '✓' : '✗'} ${tag} 双 grid + 泳道轴固定隐藏`);
  if (!gridOk) bad++;

  // 4. 缺货浅色斜纹（柱高无意义）／异常深色网纹（柱高真实但可疑）
  const actual = ser.find(x => x.name === '实际销量');
  const items = ((actual && actual.data) || []).filter(d => d && d.itemStyle);
  const pale = items.filter(d => d.itemStyle.color === '#e4e4e7' && d.itemStyle.decal);
  const dark = items.filter(d => d.itemStyle.color === '#3f3f46' && d.itemStyle.decal);
  let styleOk = (pale.length + dark.length) === items.length;
  if (probe.wantStockout && pale.length === 0) styleOk = false;
  if (probe.wantAnomaly && dark.length === 0) styleOk = false;
  console.log(`  ${styleOk ? '✓' : '✗'} ${tag} 缺货浅色斜纹 ${pale.length} 根 / 异常深色网纹 ${dark.length} 根`);
  if (!styleOk) bad++;

  // 5. 分界线挂在专用空序列上；旧预估的对象应该有两条（基准日 + 预估起点）
  const div = ser.find(x => x.name === '__divider__');
  const marks = (div && div.markLine && div.markLine.data) || [];
  const markOk = marks.length >= probe.wantMarks;
  console.log(`  ${markOk ? '✓' : '✗'} ${tag} 分界线 ${marks.length} 条（需 >=${probe.wantMarks}）：`
    + marks.map(m => m.label.formatter).join(' / '));
  if (!markOk) bad++;

  // 5b. 缺货区间必须画成贯穿绘图区的背景带。缺货日销量是 0，柱高也是 0，
  //     只靠柱子的样式什么都看不见 —— 那一段会变成空白，读成「没有数据」。
  const bandSer = ser.find(x => x.name === '缺货区间');
  const bandCount = (bandSer && bandSer.data || []).length;
  const bandOk = bandCount >= probe.wantBand
                 && (probe.wantBand === 0 || (bandSer && bandSer.z < 2));
  console.log(`  ${bandOk ? '✓' : '✗'} ${tag} 缺货背景带 ${bandCount} 段（需 >=${probe.wantBand}）`
    + (bandSer ? `，z=${bandSer.z} 在柱子之下` : ''));
  if (!bandOk) bad++;

  // 6. 两排图例的分工必须守住：
  //    第一排 = 这张图是什么（量 + 事件），必须干净，不能被 8 条叠加折线占满，
  //             也不能漏出内部序列（预估区间是柱顶那条竖线，__divider__ 是空序列）。
  //    第二排 = 能额外压上来的指标，必须全部默认关闭 —— 八条一起画会糊成一片。
  const legends = Array.isArray(o.legend) ? o.legend : [o.legend];
  const row0 = (legends[0] && legends[0].data) || [];
  const row1 = (legends[1] && legends[1].data) || [];
  const lineSeries = ser.filter(x => x.type === 'line');
  const leaked = row0.filter(x => x === '预估区间' || x === '__divider__'
                                  || row1.indexOf(x) >= 0);
  const sel = (legends[1] && legends[1].selected) || {};
  const onByDefault = Object.entries(sel).filter(([, v]) => v).map(([k]) => k);
  const ok = leaked.length === 0
             && row0.length <= 6
             && row1.length === lineSeries.length
             && lineSeries.length > 0
             && onByDefault.length === 0;
  console.log(`  ${ok ? '✓' : '✗'} ${tag} 主图例 ${row0.length} 项 / 叠加 ${row1.length} 项`
    + `（折线 ${lineSeries.length} 条，默认开 ${onByDefault.length} 条）`
    + `${leaked.length ? '，主图例泄漏 ' + leaked.join(',') : ''}`);
  if (!ok) bad++;

  // 6b. 叠加轴必须从 0 起。曾经开了 scale:true，售价实测只 $50.13~$58.99、
  //     波动 1.5%，被自动缩放拉满整个绘图高度，一条几乎不动的线画成大起大落，
  //     而轴是隐藏的看不出量级。
  const overlayAxes = (o.yAxis || []).filter(x => x.gridIndex === 1 && x.show === false);
  const badAxes = overlayAxes.filter(x => x.min !== 0 || x.scale === true);
  console.log(`  ${badAxes.length === 0 ? '✓' : '✗'} ${tag} 叠加轴 ${overlayAxes.length} 根都从 0 起`);
  if (badAxes.length) bad++;

  // 7. 各数组与日期轴等长，错位一天就会把事件贴到错误的柱子上
  const ch = payload.chart;
  const lenOk = ch.dates.length === ch.actual.length && ch.dates.length === ch.forecast.length
                && ch.dates.length === ch.weekdays.length
                && ch.lines.every(l => l.values.length === ch.dates.length);
  console.log(`  ${lenOk ? '✓' : '✗'} ${tag} 日期轴 ${ch.dates.length} 天，各序列等长`);
  if (!lenOk) bad++;
}

console.log(errors.length || bad ? 'RENDER FAIL' : 'RENDER OK');
