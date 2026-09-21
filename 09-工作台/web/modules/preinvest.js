/* 面料预投模块 · 前端入口
 *
 * 判断对象是**子 ASIN**（款号×组合×尺码），342 个 —— 运营就是逐尺码填预投的。
 * 做过配色组（57 个）那一版是错的：实测库存表逐月预投列 713 处各尺码值不同。
 *
 * 两页（考核页已按用户要求删除）：
 *   pre-plan    预投表    342 行全列的批量审批，Buffer 由运营填
 *   pre-detail  单品依据  逐日图圈一段 + 需求预测 Agent 的判断
 */

import { renderPlan } from './preinvest/page-plan.js';
import { renderDetail } from './preinvest/page-detail.js';
import { disposeCharts } from './preinvest/charts.js';
import { n0, n1, pc } from './preinvest/util.js';

export const id = 'preinvest';
export const apiVersion = 1;
export const usesRail = true;

/* 不做筛选 —— 这是一次批量审批，342 行全列（用户点名过这一条）。
   侧栏只做定位与跳转，不做过滤。 */
export const filters = [];

export function pathFor({ pageId, objectId }) {
  const page = pageId || 'pre-plan';
  return objectId ? `${page}/${encodeURIComponent(objectId)}` : page;
}

export function parsePath(segments) {
  if (!segments.length) return { pageId: 'pre-plan', objectId: null };
  return {
    pageId: segments[0],
    objectId: segments[1] ? decodeURIComponent(segments[1]) : null,
  };
}

let host = null;
let meta = null;
let popOff = null;
let autoOpened = false;

export async function mount(slots, ctx) {
  host = slots;
  installPop(ctx);
  await render(ctx);
}

export function unmount() {
  disposeCharts();
  if (popOff) popOff();
  popOff = null;
  host = null;
  meta = null;
  autoOpened = false;
}

export async function render(ctx) {
  if (!host) return;
  if (!meta) meta = await ctx.api('meta');
  const plan = await ctx.api('plan');
  renderRail(ctx, plan);
  host.body.textContent = '';

  const pageId = ctx.pageId || 'pre-plan';
  if (pageId === 'pre-plan') {
    renderPlan(host.body, plan, meta, ctx);
    return;
  }

  let cid = ctx.objectId;
  if (!cid) {
    const first = plan.rows[0];
    if (first && !autoOpened) {
      autoOpened = true;
      ctx.open(first.child_asin, 'pre-detail');
      return;
    }
    host.body.appendChild(ctx.placeholder('未选择子 ASIN', '从左边清单里点一个'));
    return;
  }
  const d = await ctx.api(`child/${encodeURIComponent(cid)}`);
  if (!d || !d.child_asin) {
    host.body.appendChild(ctx.placeholder(
      '子 ASIN 不可用', (d && d.message) ? d.message : '', 'error'));
    return;
  }
  renderDetail(host.body, d, meta, ctx);
}

/* -------------------------------------------------------------- 侧栏 --- */

function renderRail(ctx, plan) {
  const { el } = ctx;
  const wrap = el('div');
  wrap.appendChild(el('div', { class: 'pre-listmeta',
    html: `<span title="全部子 ASIN">${plan.child_count} 个子 ASIN</span>
           <span class="num" title="销售月预估销量（盒）">预估</span>` }));

  const list = el('div', { class: 'pre-list' });
  let lastGroup = null;
  for (const r of plan.rows) {
    if (r.group_id !== lastGroup) {
      lastGroup = r.group_id;
      list.appendChild(el('div', { class: 'pre-listgrp',
        text: `${r.style_no} · ${r.combination}` }));
    }
    const on = ctx.objectId === r.child_asin;
    const node = el('div', { class: 'row' + (on ? ' on' : ''), tabindex: '0' });
    node.innerHTML =
      `<div class="id"><div class="gid">${r.size || '—'}　${r.child_asin}</div>
         <div class="sub">${r.forecast_source_label}</div></div>
       <div class="num" title="销售月预估销量（盒）">${n0(r.forecast_p50)}</div>`;
    node.addEventListener('click', () => ctx.open(r.child_asin, 'pre-detail'));
    node.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault(); ctx.open(r.child_asin, 'pre-detail');
      }
    });
    list.appendChild(node);
  }
  wrap.appendChild(list);

  wrap.appendChild(el('div', { class: 'pre-railfoot',
    html: `<div class="t">${plan.target_sales_month} 这一轮</div>
      <div class="h"><span>预估销量合计</span><span>${n0(plan.forecast_p50_total)} 盒</span></div>
      <div class="h"><span>预估经 Agent 判断</span><span>${
        plan.agent_judged_children} / ${plan.child_count}</span></div>` }));

  host.rail.textContent = '';
  host.rail.appendChild(wrap);
}

function installPop(ctx) {
  const onClick = (e) => {
    const openTask = e.target.closest ? e.target.closest('[data-open-task]') : null;
    if (openTask) {
      e.preventDefault();
      document.querySelector('#wb-handle')?.click();
      return;
    }
    const mark = e.target.closest ? e.target.closest('[data-pop]') : null;
    if (!mark) return;
    e.preventDefault();
    const body = ctx.el('div', { class: 'pre-pop' });
    body.dataset.module = 'preinvest';
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

export { n0, n1, pc };
