/* 预投表页（pre-plan）
 *
 * 形态由用户 2026-09-04 定：
 *   「可以有一个 2026-10 预投，然后就直接开始给表格就行。」
 *   「你这个不要做筛选，你就把所有的都给列出来就行，因为它这个相当于是一个
 *     批量的审批的一个东西。」
 *   「左边能有图片，然后能有这个产品的定位，然后还有一些信息……你为什么要把它
 *     堆在一起呢？」
 *   「你不需要有一个你自己算的 buffer，你就直接有一个 Agent 估的销量就行了，
 *     然后你把 buffer 给到运营。」
 *
 * 所以：342 行全给、不分堆不筛选；每行左边一块产品身份（图 + 三行分开的信息，
 * 不堆成一坨）；buffer 是页头一个输入框，运营填多少就按多少算，后端不乘。
 *
 * 一行一个**子 ASIN**（款号×组合×尺码），不是配色组 —— 运营就是逐尺码填预投的。
 */

import { info, kv, n0, n1, n2, pc, sgn } from './util.js';
import { aiMarkHTML } from '../../aimark.js';

const STORE_KEY = 'preinvest.overrides.v1';
const BUFFER_KEY = 'preinvest.buffer.v1';

export function loadOverrides() {
  try {
    const raw = localStorage.getItem(STORE_KEY);
    const o = raw ? JSON.parse(raw) : {};
    return (o && typeof o === 'object') ? o : {};
  } catch { return {}; }
}

export function saveOverride(id, units) {
  const o = loadOverrides();
  if (units === null || units === undefined || units === '') delete o[id];
  else o[id] = Number(units);
  try { localStorage.setItem(STORE_KEY, JSON.stringify(o)); } catch { /* 隐私模式 */ }
  return o;
}

export function loadBuffer(fallback) {
  try {
    const v = localStorage.getItem(BUFFER_KEY);
    if (v === null || v === '') return fallback;
    const n = Number(v);
    return Number.isFinite(n) ? n : fallback;
  } catch { return fallback; }
}

function saveBuffer(v) {
  try {
    if (v === null || v === '') localStorage.removeItem(BUFFER_KEY);
    else localStorage.setItem(BUFFER_KEY, String(v));
  } catch { /* 同上 */ }
}

let GPB = 666.67;
const tons = (b) => (Number(b) || 0) * GPB / 1e6;

/* ------------------------------------------------------------------ 渲染 --- */

export function renderPlan(root, p, meta, ctx) {
  if (p.fabric_g_per_box) GPB = Number(p.fabric_g_per_box);
  const buf = loadBuffer(p.buffer_hint);
  const ov = loadOverrides();

  root.innerHTML =
    head(p, buf, ov)
    + table(p, buf, ov)
    + foot(p);
  wire(root, p, meta, ctx);
}

function sug(p50, buf) {
  return (p50 === null || p50 === undefined) ? null : Math.round(p50 * (1 + buf));
}

function totals(p, buf, ov) {
  let s = 0, f = 0;
  for (const r of p.rows) {
    const a = sug(r.forecast_p50, buf) || 0;
    const v = ov[r.child_asin];
    s += a;
    f += (v === undefined || v === null) ? a : Number(v);
  }
  return { sug: s, final: f };
}

/* ---- 页头：标题 + buffer + AI 标记 + 方案 + 导出 ---------------------- */

function head(p, buf, ov) {
  const t = totals(p, buf, ov);
  const w = p.window;
  const edited = Object.keys(ov).length;
  return `<div class="pre-head">
      <div class="pre-headl">
        <div class="pre-h1">${w.month} 预投 ${aiMarkHTML('需求预测')}</div>
        <div class="pre-sub1">交给生产端 · ${p.child_count} 个子 ASIN 全列 ·
          8 月预投对应 ${w.month} 销量（M+${w.months_ahead}）·
          这批最早 ${w.arrive_earliest} 到货${info(POP_WHY)}</div>
      </div>
      <div class="pre-headr">
        <span data-scheme-slot></span>
        <button class="wb-export" type="button" data-export>导出 Excel</button>
      </div>
    </div>

    <section class="pre-bufbar">
      <div class="pre-bufitem">
        <div class="k">${w.month} 预估销量合计</div>
        <div class="v">${n0(p.forecast_p50_total)} <span class="u">盒</span></div>
        <div class="s">需求预测 Agent 估的，这一列不由预投改</div>
      </div>
      <div class="pre-bufitem on">
        <div class="k">Buffer${info(POP_BUFFER)}</div>
        <div class="v"><input class="pre-inp buf" type="number" min="0" max="100" step="1"
          value="${(buf * 100).toFixed(0)}" aria-label="Buffer 百分比"
          data-buffer> <span class="u">%</span></div>
        <div class="s">你填多少就按多少算，留空按 ${pc(p.buffer_hint)}</div>
      </div>
      <div class="pre-bufitem">
        <div class="k">系统建议预投合计</div>
        <div class="v" data-sug-total>${n0(t.sug)} <span class="u">盒</span></div>
        <div class="s">预估 × (1 + Buffer)</div>
      </div>
      <div class="pre-bufitem">
        <div class="k">这份表当前合计</div>
        <div class="v" data-final-total>${n0(t.final)} <span class="u">盒</span></div>
        <div class="s" data-final-sub>折面料 <b data-final-tons>${n2(tons(t.final))} 吨</b>${
          edited ? ` · 已手工调整 ${edited} 行` : ''}</div>
      </div>
    </section>`;
}

/* ---- 表：一行一个子 ASIN，左边一块产品身份 --------------------------- */

function table(p, buf, ov) {
  return `<table class="pre-t pre-asintable"><thead><tr>
      <th class="idcol">产品</th>
      <th class="num">${p.window.month} 预估</th>
      <th class="num">系统建议</th>
      <th class="num">我要投</th>
      <th class="num">折面料</th>
      <th></th>
    </tr></thead><tbody>
    ${p.rows.map((r) => row(r, buf, ov)).join('')}
    </tbody></table>`;
}

/* 产品身份：图 + 三行分开排。不堆在一坨 —— 用户点名过这一条。 */
function idCell(r) {
  return `<div class="pre-idc">
    <div class="pre-idimg">
      <img src="/assets/product-placeholder.png" alt="商品主图" loading="lazy">
      <span class="tag">示意图</span>
    </div>
    <div class="pre-idtxt">
      <div class="l1">${r.child_asin}<span class="sz">${r.size || '—'}</span></div>
      <div class="l2">${r.style_no} · ${r.combination}　${r.category || ''}</div>
      <div class="l3">
        <span class="pre-flag" data-code="${lifeCode(r.lifecycle)}">${r.lifecycle || '—'}</span>
        <span>${r.operator || '—'}</span>
        <span>${r.pack_size ? r.pack_size + ' 条装' : '条数缺失'}</span>
        ${r.category_rank ? `<span>小类排名 ${r.category_rank}</span>` : ''}
        ${r.rating ? `<span>评分 ${n1(r.rating)}</span>` : ''}
      </div>
      <div class="l4" title="${r.colorway || ''}">${r.colorway || ''}</div>
    </div>
  </div>`;
}

function lifeCode(x) {
  return x === '成长期' ? 'ramp' : (x === '衰退期' ? 'missed' : 'ok');
}

function row(r, buf, ov) {
  const a = sug(r.forecast_p50, buf);
  const cur = ov[r.child_asin];
  const has = cur !== undefined && cur !== null;
  const final = has ? Number(cur) : a;
  const d = (has && a !== null) ? final - a : null;
  return `<tr data-cid="${r.child_asin}"${has ? ' class="edited"' : ''}>
    <td class="idcol">${idCell(r)}</td>
    <td class="num">${n0(r.forecast_p50)}
      <div class="pre-cellsub">${r.forecast_source_label}${
        r.forecast_p10 === null ? '' : ` · ${n0(r.forecast_p10)}~${n0(r.forecast_p90)}`}</div></td>
    <td class="num" data-sug="${r.child_asin}">${n0(a)}</td>
    <td class="num">
      <input class="pre-inp" type="number" min="0" step="1"
             value="${has ? final : ''}" placeholder="${a === null ? '' : n0(a)}"
             aria-label="${r.child_asin} 我要投多少盒" data-input-cid="${r.child_asin}">
      <div class="pre-cellsub" data-delta="${r.child_asin}">${d === null ? '' : sgn(d) + ' 盒'}</div></td>
    <td class="num" data-tons="${r.child_asin}">${n2(tons(final))} 吨</td>
    <td class="pre-drill"><a href="#" data-open="${r.child_asin}">看依据</a></td>
  </tr>`;
}

/* ---- 底部：导出 ------------------------------------------------------- */

/* 底部只留「清除我的调整」。导出按钮搬到了页头标题栏右侧 ——
   跟库存「销量与需求」那个板块一样的位置，运营找它的地方是一致的。 */
function foot(p) {
  return `<section class="pre-act">
    <div class="pre-actmain">
      <button class="wb-icon-btn" type="button" data-reset>清除我的调整</button>
      <span class="pre-actnote inline">导出的表里「系统建议」与「运营最终」分两列，
        另有一列记录人工调整了多少盒，Buffer 写在表头。
        我的调整存在这台浏览器本地，换机器不会带过去。${info(POP_DRAFT)}</span>
    </div>
  </section>`;
}

/* ------------------------------------------------------------------ 交互 --- */

function cssEsc(s) {
  return (window.CSS && CSS.escape) ? CSS.escape(s) : String(s);
}

function wire(root, p, meta, ctx) {
  // 方案下拉挂到页头右边（外壳统一实现，模块只放位置）
  const slot = root.querySelector('[data-scheme-slot]');
  if (slot && ctx.schemePicker) {
    const picker = ctx.schemePicker('需求预测');
    if (picker) slot.appendChild(picker);
  }

  // Buffer 改一次，整表的「系统建议」与合计全部重算 —— 不重绘整表，
  // 重绘会让输入框失焦，连着调 buffer 的手感就断了。
  const bufInp = root.querySelector('[data-buffer]');
  const recalc = () => {
    const raw = bufInp.value.trim();
    const buf = raw === '' ? p.buffer_hint : Number(raw) / 100;
    saveBuffer(raw === '' ? '' : raw);
    const ov = loadOverrides();
    for (const r of p.rows) {
      const a = sug(r.forecast_p50, buf);
      const el = root.querySelector(`[data-sug="${cssEsc(r.child_asin)}"]`);
      if (el) el.textContent = n0(a);
      const inp = root.querySelector(`[data-input-cid="${cssEsc(r.child_asin)}"]`);
      if (inp) inp.placeholder = a === null ? '' : n0(a);
      const has = ov[r.child_asin] !== undefined && ov[r.child_asin] !== null;
      const final = has ? Number(ov[r.child_asin]) : a;
      const tn = root.querySelector(`[data-tons="${cssEsc(r.child_asin)}"]`);
      if (tn) tn.textContent = n2(tons(final)) + ' 吨';
      const dl = root.querySelector(`[data-delta="${cssEsc(r.child_asin)}"]`);
      if (dl) dl.textContent = (has && a !== null) ? sgn(final - a) + ' 盒' : '';
    }
    paintTotals(root, p, buf, ov);
  };
  bufInp.addEventListener('change', recalc);
  bufInp.addEventListener('input', recalc);

  root.querySelectorAll('[data-input-cid]').forEach((inp) => {
    const commit = () => {
      const cid = inp.dataset.inputCid;
      const raw = inp.value.trim();
      const ov = saveOverride(cid, raw === '' ? null : raw);
      const bufRaw = bufInp.value.trim();
      const buf = bufRaw === '' ? p.buffer_hint : Number(bufRaw) / 100;
      const r = p.rows.find((x) => x.child_asin === cid);
      const a = sug(r ? r.forecast_p50 : null, buf);
      const has = raw !== '';
      const final = has ? Number(raw) : a;
      const dl = root.querySelector(`[data-delta="${cssEsc(cid)}"]`);
      if (dl) dl.textContent = (has && a !== null) ? sgn(final - a) + ' 盒' : '';
      const tn = root.querySelector(`[data-tons="${cssEsc(cid)}"]`);
      if (tn) tn.textContent = n2(tons(final)) + ' 吨';
      inp.closest('tr')?.classList.toggle('edited', has);
      paintTotals(root, p, buf, ov);
    };
    inp.addEventListener('change', commit);
    inp.addEventListener('blur', commit);
  });

  root.querySelector('[data-reset]')?.addEventListener('click', () => {
    try { localStorage.removeItem(STORE_KEY); } catch { /* 隐私模式 */ }
    renderPlan(root, p, meta, ctx);
  });

  root.querySelectorAll('[data-open]').forEach((a) => {
    a.addEventListener('click', (e) => {
      e.preventDefault();
      ctx.open(a.dataset.open, 'pre-detail');
    });
  });

  root.querySelector('[data-export]')?.addEventListener('click', (e) =>
    exportXlsx(e.currentTarget, bufInp));
}

function paintTotals(root, p, buf, ov) {
  const t = totals(p, buf, ov);
  const a = root.querySelector('[data-sug-total]');
  if (a) a.innerHTML = `${n0(t.sug)} <span class="u">盒</span>`;
  const b = root.querySelector('[data-final-total]');
  if (b) b.innerHTML = `${n0(t.final)} <span class="u">盒</span>`;
  const c = root.querySelector('[data-final-tons]');
  if (c) c.textContent = n2(tons(t.final)) + ' 吨';
}

async function exportXlsx(btn, bufInp) {
  const old = btn.textContent;
  btn.disabled = true;
  btn.textContent = '导出中…';
  try {
    const raw = bufInp.value.trim();
    const qs = location.search.replace(/^\?/, '');
    const res = await fetch(`/api/preinvest/export-plan${qs ? '?' + qs : ''}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        buffer: raw === '' ? null : Number(raw) / 100,
        overrides: loadOverrides(),
      }),
    });
    if (!res.ok) throw new Error(`接口返回 ${res.status}`);
    const blob = await res.blob();
    const cd = res.headers.get('Content-Disposition') || '';
    const m = /filename\*?=(?:UTF-8''|")?([^";]+)/i.exec(cd);
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = m ? decodeURIComponent(m[1]) : '面料预投表.xlsx';
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    btn.textContent = '已导出';
  } catch (err) {
    btn.textContent = '导出失败：' + (err.message || err);
  } finally {
    btn.disabled = false;
    setTimeout(() => { btn.textContent = old; }, 2600);
  }
}

/* ---- ⓘ 说明 ---------------------------------------------------------- */

const POP_WHY = `<b>为什么是 M+2</b><br>
8 月做的预投对应 10 月的销量。这是客户表里的既有口径 ——
逐月预投列和月报预投下单表都是这么排的。<br><br>
<b>为什么一行一个子 ASIN</b><br>
运营就是逐尺码填预投的。客户库存表里同一个配色组的不同尺码，
预投数是各不相同的（实测 713 处不同、仅 101 处相同），
所以不能按配色组合起来看。<br><br>
<b>「这批最早到货」是什么意思</b><br>
基准日加上前置期（备面料 + 生产 + 物流，约两个半月）。它落在销售月中间，
说明这个月上半月卖的还是现有库存。`;

const POP_BUFFER = `<b>Buffer 由你定</b><br>
系统只给需求预测 Agent 估出来的销量，不替你加余量。
Buffer 填多少，整张表的「系统建议」就按多少算。<br><br>
吴组长举例是「预计卖 100 盒，我可能就会投到 110 盒」，所以默认起点 10%。
这个数留空就用默认。<br><br>
<b>为什么不由系统定</b><br>
余量是拿资金占用换缺货风险，那是运营和公司的取舍，不是一个算得出来的数。`;

const POP_DRAFT = `<b>我的调整存在哪</b><br>
存在这台浏览器的本地存储里，不写进数据库 —— 页面对所有数据源都是只读的。
刷新、翻到依据页再回来都不会丢，换机器就没有了。<br><br>
<b>最终交出去的是那个文件</b><br>
点导出拿到的 .xlsx 才是交付物：「系统建议」与「运营最终」分两列，
另有一列记录人工调整了多少盒，Buffer 写在表头。`;
