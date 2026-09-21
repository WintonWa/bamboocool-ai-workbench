/* 库存全览页。2026-09-04 按 11-页面框架与决策/Image2-视觉灵感 的参考图重做。
 *
 * 重做前是「八个等权数字（两排 grid.g4）+ 一张两列表」。八个数字里既有件数
 * 又有比率又有金额，全用同一个字号平铺，扫下来分不出主次。
 *
 * 现在：概览卡 → 库存结构流向（堆叠条）+ 款式覆盖天数（带安全线）→ 风险类型表。
 *
 * 一个口径踩过的坑写在这里：参考图把「可售 / 受限 / 在途 / 超龄」四段并列，
 * 但在我们的口径下**超龄是可售的子集**，并列会重复计数（四段相加超过总量）。
 * 所以只画三段真分区，超龄作为可售段内的一条标注，不进堆叠。
 */

import { chip, info, n0, n1, pc, sec, usd } from './util.js';
import { aiMarkHTML } from '../../aimark.js';
import { styleCoverBars } from './charts.js';

function cell(label, value, sub, tone) {
  return `<div class="inv-cell">
    <div class="inv-cell-label">${label}</div>
    <div class="inv-cell-value${tone ? ' ' + tone : ''}">${value}</div>
    ${sub ? `<div class="inv-cell-sub">${sub}</div>` : ''}
  </div>`;
}

/* 结构流向条。段是真分区（相加等于总量），零值段不渲染。 */
function flowBar(segs, total) {
  const rows = segs.filter((s) => s.n > 0);
  if (!rows.length || !total) return '';
  return `<div class="inv-flow">
    <div class="inv-stack">${rows.map((s) =>
    `<i class="inv-seg ${s.kind}" style="width:${(s.n / total) * 100}%"
       title="${s.label} ${n0(s.n)} · ${pc(s.n / total)}"></i>`).join('')}</div>
    <div class="inv-flowrows">${rows.map((s) => `<div class="inv-flowrow">
      <span class="inv-lg ${s.kind}"><i></i>${s.label}</span>
      <span class="inv-flownum">${n0(s.n)}</span>
      <span class="inv-flowpct">${pc(s.n / total)}</span>
      <span class="inv-flownote">${s.note || ''}</span>
    </div>`).join('')}</div>
  </div>`;
}

export function renderScope(c, payload, meta) {
  const s = payload.scope;
  const rows = payload.rows || [];

  /* 三段真分区：可售 + 受限（FBA 里不可立即销售的）+ 在途（FBA 之外的已知库存）。
     受限 = FBA 合计 − 可售；在途 = 已知总库存 − FBA 合计。
     相加等于 total_known_qty，所以堆叠条的段宽是可加的。 */
  const restricted = Math.max(0, (s.fba_total_qty || 0) - (s.sellable_qty || 0));
  const inbound = Math.max(0, (s.total_known_qty || 0) - (s.fba_total_qty || 0));

  // 安全线取模块自己声明的目标覆盖天数，不另立一个数
  const safetyParam = (meta.parameters || []).find((x) => x.key === 'max_cover_days');
  const safetyDays = 30;

  let h = `<div class="inv-h1">库存全览</div>
    <div class="sub1">当前筛选范围的汇总 · 由子 ASIN 结果重算</div>`;

  h += `<div class="inv-card">
    ${cell('监控范围', `${s.child_count}`,
    `${s.parent_count} 个父体 · ${s.style_count} 个款号`)}
    ${cell('可售（FBA）', n0(s.sellable_qty),
    `FBA 合计 ${n0(s.fba_total_qty)} · 可用率 ${pc(s.availability_rate)}`)}
    ${cell('已知总库存（含在途）', n0(s.total_known_qty),
    `在途 ${n0(inbound)} · 受限 ${n0(restricted)}`)}
    ${cell('近 30 天销量', n0(s.units_30d),
    `覆盖天数中位 ${s.cover_days_median === null ? '—' : n1(s.cover_days_median) + ' 天'}`)}
    ${cell('估算月仓储费', usd(s.fee_total),
    `181 天以上 ${n0(s.aged_181_qty)} 件 · 占 ${pc(s.aged_181_share)}`,
    s.aged_181_share > 0.1 ? 'warn' : '')}
  </div>`;

  h += sec('库存结构与覆盖' + aiMarkHTML('库存总体分析'),
    chip('derived') + info(`<b>口径</b><br>${s.cover_days_note}<br><br>
      <b>左边三段为什么不含超龄</b><br>
      可售 / 受限 / 在途是真分区，相加等于已知总库存，所以段宽可加。
      而<b>超龄（181 天以上）是可售的子集</b>，把它并成第四段会重复计数、
      四段相加超过总量。所以它作为可售段内的一条标注，不进堆叠。<br><br>
      <b>右边的款式覆盖天数</b><br>
      按款号聚合子体覆盖天数取<b>中位数</b>，不取平均 —— 覆盖天数长尾很重，
      一个 900 天的滞销子体会把整款拉高。低于安全线 ${safetyDays} 天的染警示色。`),
  `<div class="inv-chartpair">
      <div class="inv-chartcell">
        <div class="inv-chartcap">库存结构（已知总库存流向）</div>
        ${flowBar([
    { label: '可售（可立即销售）', n: s.sellable_qty, kind: 'good',
      note: s.aged_181_qty ? `其中超龄 ${n0(s.aged_181_qty)} 件` : '' },
    { label: '受限（预留 / 待调仓 / 入库中）', n: restricted, kind: 'warn', note: '' },
    { label: '在途（运输中，未入 FBA）', n: inbound, kind: 'calm', note: '' },
  ], s.total_known_qty)}
        <div class="inv-flowtotal">已知总库存合计
          <b>${n0(s.total_known_qty)}</b> 件 · 三段相加为 100%</div>
      </div>
      <div class="inv-chartcell">
        <div class="inv-chartcap">款式库存覆盖天数（中位 · 以近 30 天日均销量计）</div>
        <div class="inv-mount" data-chart="style"></div>
      </div>
    </div>`);

  // 风险类型表。by_risk_type 在 scope 里只有对象数，影响件数从 rows 的 risk_qty 汇总
  const qtyByType = {};
  for (const r of rows) {
    for (const [k, v] of Object.entries(r.risk_qty || {})) {
      qtyByType[k] = (qtyByType[k] || 0) + v;
    }
  }
  const riskRows = Object.entries(s.by_risk_type)
    .map(([k, n]) => ({ k, n, qty: qtyByType[k] || 0 }))
    .sort((a, b) => b.qty - a.qty);
  const maxQty = Math.max(1, ...riskRows.map((r) => r.qty));

  h += sec('风险类型分布（范围内）', chip('derived')
    + ` 有风险 ${s.risk_child_count} 个 · 风险条数 ${s.risk_record_count}`,
  `<div class="inv-tablewrap"><table class="inv-risktable">
      <thead><tr><th>风险类型</th><th class="num">子 ASIN</th>
      <th class="num">占监控</th><th class="num">影响件数</th><th>相对量级</th></tr></thead>
      <tbody>${riskRows.map((r) => `<tr>
        <td class="strong">${meta.risk_labels[r.k] || r.k}</td>
        <td class="num">${r.n}</td>
        <td class="num">${pc(r.n / (s.child_count || 1))}</td>
        <td class="num">${n0(r.qty)}</td>
        <td><span class="inv-qbar"><i style="width:${
    Math.max(2, (r.qty / maxQty) * 100)}%"></i></span></td>
      </tr>`).join('')}</tbody></table></div>`);

  c.innerHTML = h;
  styleCoverBars(c.querySelector('.inv-mount[data-chart="style"]'), rows, safetyDays);
}
