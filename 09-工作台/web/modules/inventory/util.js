/* 库存模块 · 共用小工具
 *
 * 数字格式化保留 18810 版的本地实现，**没有换成 ctx.fmt**。理由是行为不等价：
 *   ctx.fmt.int('')   -> Math.round('') = 0 -> "0"      本地 n0('') -> "—"
 *   ctx.fmt.num(v)    -> toFixed()，无千分位              本地 n1/n2 带千分位
 *   ctx.fmt.int 用 zh-CN 千分位，本地用 en-US
 * 第一条是实质问题：把"缺数据"显示成 0 是错的，不是风格差异。
 * 迁移指导让改用 ctx 的理由是"两个模块各留一份浮层会互相抢当前打开的是谁"，
 * 那条针对浮层与 $ / el，已照办；数字格式化不在那个理由的射程内，
 * 而验收标准是与 18810 数字逐位一致，所以这里保持本地实现。
 */

export const WD = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];

export const n0 = (v) => (v === null || v === undefined || v === '') ? '—'
  : Number(v).toLocaleString('en-US', { maximumFractionDigits: 0 });
export const n1 = (v) => (v === null || v === undefined || v === '') ? '—'
  : Number(v).toLocaleString('en-US', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
export const n2 = (v) => (v === null || v === undefined || v === '') ? '—'
  : Number(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
export const pc = (v) => (v === null || v === undefined) ? '—' : (Number(v) * 100).toFixed(1) + '%';
export const usd = (v, dp) => (v === null || v === undefined || v === '') ? '—'
  : '$' + Number(v).toLocaleString('en-US', { minimumFractionDigits: dp ?? 0, maximumFractionDigits: dp ?? 0 });

export const cnDate = (iso) => {
  if (!iso) return '';
  const [y, m, d] = iso.split('-').map(Number);
  return `${m}月${d}日 ${WD[new Date(y, m - 1, d).getDay()]}`;
};

export const na = (why) => `<span class="na">不可计算${why ? '：' + why : ''}</span>`;

const CHIP = {
  customer_actual: ['real', '真实'], customer_actual_derived: ['real', '真实·同表计算'],
  customer_actual_formula_cache: ['real', '真实·公式缓存'],
  derived: ['derived', '派生'], estimated: ['est', '估算'], supplemented: ['supp', '补造'],
  unknown: ['na', '未知'], demo_default: ['est', '演示预设'],
  demo_override: ['est', '演示改写'], data_layer: ['derived', '数据层'],
};
export const chip = (o) => {
  const c = CHIP[o] || ['na', o || '—'];
  return `<span class="chip ${c[0]}">${c[1]}</span>`;
};

export const CAP_LABEL = { can_absorb: '可承接', limited: '有限承接', cannot_absorb: '不可承接',
  unknown: '无法判断', unavailable: '缺库存快照' };
export const SEV_LABEL = { high: '高', medium: '中', low: '低' };
export const CONF_LABEL = { high: '高', medium: '中', low: '低' };

/* 点开才出的计算方法说明。板块上不留说明文字行 —— 那是产品规则，不是排版偏好。
   标记只写 data-pop，真正的展示由 inventory.js 的委托监听转给 ctx.pop。 */
export const info = (html) =>
  `<i class="info" data-pop="${encodeURIComponent(html)}" title="计算方法">i</i>`;

/* ---- 以下四个小 SVG 图与两个包装函数，从 app.js 逐字搬来 ---- */

export function linePath(vals, w, h, pad, min, max) {
  if (!vals.length) return '';
  const span = (max - min) || 1;
  return vals.map((v, i) => {
    const x = pad + i * (w - pad * 2) / Math.max(vals.length - 1, 1);
    const y = h - pad - (v - min) * (h - pad * 2) / span;
    return `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
}

export function balanceChart(series, safetyQty) {
  const w = 700, h = 170, pad = 26;
  const vals = series.map(d => d.closing);
  const min = Math.min(0, ...vals), max = Math.max(...vals, safetyQty, 1);
  const zeroY = h - pad - (0 - min) * (h - pad * 2) / ((max - min) || 1);
  const safeY = h - pad - (safetyQty - min) * (h - pad * 2) / ((max - min) || 1);
  const first = series[0], last = series[series.length - 1];
  return `<svg viewBox="0 0 ${w} ${h}" width="100%" height="${h}">
    <line class="axis" x1="${pad}" y1="${h - pad}" x2="${w - pad}" y2="${h - pad}"/>
    <line class="zero" x1="${pad}" y1="${zeroY}" x2="${w - pad}" y2="${zeroY}"/>
    <line class="safety" x1="${pad}" y1="${safeY}" x2="${w - pad}" y2="${safeY}"/>
    <path class="bal" d="${linePath(vals, w, h, pad, min, max)}"/>
    <text x="${pad}" y="${h - 8}">${first ? first.date : ''}</text>
    <text x="${w - pad}" y="${h - 8}" text-anchor="end">${last ? last.date : ''}</text>
    <text x="${pad + 3}" y="${safeY - 3}">安全库存 ${n0(safetyQty)}</text>
    <text x="${w - pad}" y="${pad - 8}" text-anchor="end">峰值 ${n0(max)}</text>
  </svg>`;
}

export function parentChart(series, childAvg) {
  if (!series.length) return `<div class="na">该父体无逐日销量历史</div>`;
  const w = 700, h = 130, pad = 24;
  const vals = series.map(d => d.units_sold);
  const min = 0, max = Math.max(...vals, 1);
  const avgY = h - pad - (childAvg - min) * (h - pad * 2) / ((max - min) || 1);
  return `<svg viewBox="0 0 ${w} ${h}" width="100%" height="${h}">
    <line class="axis" x1="${pad}" y1="${h - pad}" x2="${w - pad}" y2="${h - pad}"/>
    <path class="parent" d="${linePath(vals, w, h, pad, min, max)}"/>
    ${childAvg > 0 && avgY > pad ? `<line class="avgline" x1="${pad}" y1="${avgY}" x2="${w - pad}" y2="${avgY}"/>
      <text x="${pad + 3}" y="${avgY - 3}">本子体 30 天日均 ${n1(childAvg)}</text>` : ''}
    <text x="${pad}" y="${h - 8}">${series[0].date}</text>
    <text x="${w - pad}" y="${h - 8}" text-anchor="end">${series[series.length - 1].date}</text>
    <text x="${w - pad}" y="${pad - 6}" text-anchor="end">父体日销峰值 ${n0(max)}</text>
  </svg>`;
}

export function bucketBars(asof, june) {
  const max = Math.max(...asof.map(b => b.qty), ...june.map(b => b.qty), 1);
  const aged = new Set(['181-270天库龄', '271-330天库龄', '331-365天库龄', '大于365天库龄']);
  return '<div class="bars">' + asof.map((b, i) => `
    <div class="b"><span style="color:var(--fg3)">${b.bucket}</span>
      <span class="track">
        <span class="fill ${aged.has(b.bucket) ? 'aged' : ''}" style="width:${b.qty / max * 100}%"></span>
        <span class="fill june" style="width:${june[i].qty / max * 100}%"></span>
      </span>
      <span class="num">${n0(b.qty)}</span></div>`).join('') + '</div>' +
    `<div class="legend"><span><i style="background:var(--ink)"></i>2026-08-03 前滚后</span>
      <span><i style="background:var(--warn)"></i>181 天以上</span>
      <span><i style="background:var(--fg3)"></i>2026-06-30 客户原值（细线）</span></div>`;
}

/* ------------------------------------------------------------------ render */

export function packManifest(id, packSize) {
  const pm = id.pack_manifest || {};
  const items = pm.items || [];
  if (!items.length) return na('源表无配色记录');
  const tally = pm.matches_pack_size === true
    ? `<span class="ok">清单合计 ${pm.total_units} 条，与装盒数一致</span>`
    : pm.total_units === null
      ? `<span class="warn">源表未写件数，无法与装盒数核对</span>`
      : `<span class="warn">清单合计 ${pm.total_units} 条，装盒数 ${packSize ?? '—'} 条</span>`;
  return `<div class="packhead">${id.combination || '—'} · ${packSize ? packSize + ' 条/盒' : '装盒数未知'} · ${tally}</div>
    <div class="packlist">${items.map(it => `<span class="packitem">
      ${it.color_code ? `<b>${it.color_code}</b>` : ''}${it.body_color || it.color_name}
      ${it.waistband_color ? `<i>${it.waistband_color}</i>` : ''}
      <em>×${it.quantity ?? '?'}</em></span>`).join('')}</div>`;
}

export function sec(title, hint, body) {
  return `<section><h2>${title}${hint ? `<span class="hint">${hint}</span>` : ''}</h2>${body}</section>`;
}

/* Folded section: kept out of the reading flow until opened. */

export function fold(title, meta, body) {
  return `<details class="fold"><summary>${title}${meta ? `<span class="c">${meta}</span>` : ''}</summary>
    <div class="foldbody">${body}</div></details>`;
}
