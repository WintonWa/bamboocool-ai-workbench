/* 产品与库存模块 · 前端入口
 *
 * 零全局声明，只有 export。$ / el / 浮层 / 抽屉 / 占位全部从 ctx 取。
 * 数字格式化是唯一保留本地实现的一项，理由写在 inventory/util.js 的文件头。
 *
 * 三个页面各自一个文件，这里只做取数、侧栏、分派：
 *   inv-detail 单品盘点   inventory/page-detail.js
 *   inv-risk   异常总览   inventory/page-risk.js
 *   inv-scope  库存全览   inventory/page-scope.js
 */

import { disposeDayChart } from './inventory/daychart.js';
import { renderDetail } from './inventory/page-detail.js';
import { renderRisk } from './inventory/page-risk.js';
import { renderScope } from './inventory/page-scope.js';
import { n0, n1 } from './inventory/util.js';

export const id = 'inventory';
export const apiVersion = 1;
export const usesRail = true;

/* 声明式筛选。label 必须给（门禁 G18）—— 不给的话 chip 上会写 query 键名，
   那是内部叫法上屏。键名与后端 listing.apply_filters 读的键一一对应。 */
export const filters = [
  { key: 'q', label: '搜子 ASIN / 款号 / 父体' },
  { key: 'risk_type', label: '风险类型' },
  { key: 'severity', label: '严重度' },
  { key: 'style_no', label: '款号' },
  { key: 'combination', label: '组合' },
  { key: 'size', label: '尺码' },
  { key: 'operator', label: '运营' },
  { key: 'goods_status', label: '货品状态' },
  { key: 'product_lifecycle', label: '生命周期' },
  { key: 'sort', label: '排序' },
];

/* 路径里的段名必须就是 pages[].id：外壳的 applyUrl() 在模块加载前就解析 URL，
   那时拿不到 parsePath，会回落到按 pages[].id 匹配段名（别人踩过的坑之三）。
   pathFor 只返回模块名之后的尾段，返回完整路径会得到 /inventory/inventory/…… */
export function pathFor({ pageId, objectId }) {
  const page = pageId || 'inv-detail';
  return objectId ? `${page}/${encodeURIComponent(objectId)}` : page;
}

export function parsePath(segments) {
  if (!segments.length) return { pageId: 'inv-detail', objectId: null };
  return { pageId: segments[0], objectId: segments[1] ? decodeURIComponent(segments[1]) : null };
}

/* ---------------------------------------------------------------- 状态 --- */

let host = null;
let meta = null;          // /api/inventory/meta 只取一次
let popOff = null;        // 委托监听的解绑函数
let autoOpened = false;   // 详情页无对象时自动开第一个，只做一次，避免导航回环

/* ---------------------------------------------------------- 生命周期 --- */

export async function mount(slots, ctx) {
  host = slots;
  installPop(ctx);
  await render(ctx);
}

export function unmount() {
  disposeDayChart();          // ECharts 实例不清会留着监听和 canvas
  if (popOff) popOff();
  popOff = null;
  host = null;
  meta = null;
  autoOpened = false;
}

export async function render(ctx) {
  if (!host) return;

  if (!meta) meta = await ctx.api('meta');
  const payload = await ctx.api('children');

  renderRail(ctx, payload);

  const pageId = ctx.pageId || 'inv-detail';
  host.body.textContent = '';

  if (pageId === 'inv-risk') {
    renderRisk(host.body, payload.overview, meta);
    return;
  }
  if (pageId === 'inv-scope') {
    renderScope(host.body, payload.scope, meta);
    return;
  }

  // 单品盘点
  let asin = ctx.objectId;
  if (!asin) {
    if (payload.rows.length && !autoOpened) {
      autoOpened = true;
      ctx.open(payload.rows[0].child_asin, 'inv-detail');   // 会重新进 render
      return;
    }
    host.body.appendChild(
      ctx.placeholder('未选择对象', payload.rows.length ? '从左边清单里点一行' : '当前筛选没有结果')
    );
    return;
  }

  const a = await ctx.api(`child/${encodeURIComponent(asin)}`);
  if (!a || !a.child_asin) {
    host.body.appendChild(
      ctx.placeholder('对象不可用', (a && a.message) ? a.message : '', 'error')
    );
    return;
  }
  await renderDetail(host.body, a, meta);
}

/* -------------------------------------------------------------- 侧栏 --- */

function renderRail(ctx, payload) {
  const { el } = ctx;
  const wrap = el('div');

  wrap.appendChild(el('div', {
    class: 'inv-listmeta',
    html: `<span title="当前筛选命中 / 全部子 ASIN">${payload.matched} / ${payload.total}</span>
           <span class="num" title="覆盖天数（可售+已确认在途 口径）">覆盖</span>
           <span class="num" title="近 30 天真实销量（件）">30天</span>
           <span class="num" title="当前可售（件）">可售</span>`,
  }));

  const list = el('div', { class: 'inv-list' });
  for (const r of payload.rows) {
    const sev = r.primary_severity || 'none';
    const on = ctx.objectId === r.child_asin;
    const node = el('div', { class: 'row' + (on ? ' on' : ''), tabindex: '0' });
    node.innerHTML =
      `<div class="id"><div class="asin"><span class="sev ${sev}"></span>${r.child_asin}</div>
         <div class="sub">${r.style_no || '—'} · ${r.combination || '—'} · ${r.size || '—'}${r.risk_count > 1 ? ' · ' + r.risk_count + ' 类风险' : ''}</div></div>
       <div class="num" title="覆盖天数（可售+已确认在途 口径）">${r.cover_days === null ? '—' : n1(r.cover_days)}</div>
       <div class="num" title="近30天真实销量（件）">${n0(r.units_30d)}</div>
       <div class="num" title="当前可售（件）">${n0(r.sellable_qty)}</div>`;
    node.addEventListener('click', () => ctx.open(r.child_asin, 'inv-detail'));
    node.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); ctx.open(r.child_asin, 'inv-detail'); }
    });
    list.appendChild(node);
  }
  wrap.appendChild(list);

  if (payload.overview) {
    wrap.appendChild(el('div', { class: 'inv-hits', html: hitsHtml(payload.overview) }));
  }

  host.rail.textContent = '';
  host.rail.appendChild(wrap);
}

function hitsHtml(o) {
  const line = (a, b) => `<div class="h"><span>${a}</span><span>${b}</span></div>`;
  let h = line('有风险 / 总数', `${o.risk_child_count} / ${o.child_count}`) + line('风险条数', o.risk_record_count) +
          line('多风险对象', o.multi_risk_children) + line('无风险', o.no_risk_children);
  for (const [k, v] of Object.entries(o.by_risk_type)) h += line(v.label, `${v.child_count} 个 · ${n0(v.affected_qty)} 件`);
  h += line('high / medium / low', `${o.severity.high || 0} / ${o.severity.medium || 0} / ${o.severity.low || 0}`);
  return '<div class="t">当前阈值命中情况</div>' + h;
}

/* ------------------------------------------------------- ⓘ 点开说明 --- */

/* 页面里的 data-pop 标记全部转给 ctx.pop —— 全站唯一一份浮层实现。
   自己再造一份的话，两个模块会互相抢"当前打开的是谁"。
 *
 * 关键一点：外壳的 #wb-pop 挂在文档顶层，**在 [data-module] 作用域之外**，
 * 所以内容必须自带一个带 data-module 的包裹节点，否则 inventory.css
 * 里那些 [data-module="inventory"] .inv-pop 规则一条都不生效。 */
function installPop(ctx) {
  const onClick = (e) => {
    /* 任务触发是外壳任务面板的活，模块不自己做（契约第 9 节）。
       这个按钮只负责把面板打开，不自己发请求 —— 否则执行过程、失败提示、
       运行中状态都要在模块里再实现一份，而且会出现两个 Agent 入口。
       外壳没在 ctx 上暴露开面板的方法，所以点它的手柄。 */
    const openTask = e.target.closest ? e.target.closest('[data-open-task]') : null;
    if (openTask) {
      e.preventDefault();
      const handle = document.querySelector('#wb-handle');
      if (handle) handle.click();
      return;
    }
    const mark = e.target.closest ? e.target.closest('[data-pop]') : null;
    if (!mark) return;
    e.preventDefault();
    const body = ctx.el('div', { class: 'inv-pop' });
    body.dataset.module = 'inventory';
    body.innerHTML = decodeURIComponent(mark.dataset.pop);
    ctx.pop.show(mark, body);
  };
  host.rail.addEventListener('click', onClick);
  host.body.addEventListener('click', onClick);
  popOff = () => {
    host.rail.removeEventListener('click', onClick);
    host.body.removeEventListener('click', onClick);
  };
}
