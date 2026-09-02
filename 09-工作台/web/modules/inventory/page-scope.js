/* 库存全览页。函数体逐字来自 18810 版 app.js 的 renderScope。 */

import {
  chip, info, n0, n1, pc, sec,
  usd,
} from './util.js';

export function renderScope(c, scope, meta) {
  const s = scope;
  c.innerHTML = `<div class="inv-h1">库存全览</div><div class="sub1">当前筛选范围的汇总 · 由子 ASIN 结果重算</div>` +
    sec('范围概览', chip('derived') + info(`<b>范围口径</b><br>${s.cover_days_note}`), `
      <div class="grid g4">
        <div><div class="lbl">子 ASIN / 父体 / 款号</div><div class="big compact">${s.child_count} / ${s.parent_count} / ${s.style_count}</div></div>
        <div><div class="lbl">可售 / FBA 合计</div><div class="big compact">${n0(s.sellable_qty)} / ${n0(s.fba_total_qty)}</div></div>
        <div><div class="lbl">已知总库存</div><div class="big">${n0(s.total_known_qty)}</div></div>
        <div><div class="lbl">近 30 天销量</div><div class="big">${n0(s.units_30d)}</div></div>
      </div>
      <div class="grid g4" style="margin-top:12px">
        <div><div class="lbl">范围可用率（总量重算）</div><div class="big">${pc(s.availability_rate)}</div></div>
        <div><div class="lbl">181+ 件数 / 占比</div><div class="big compact">${n0(s.aged_181_qty)} · ${pc(s.aged_181_share)}</div></div>
        <div><div class="lbl">覆盖天数中位数</div><div class="big">${s.cover_days_median === null ? '—' : n1(s.cover_days_median)}</div></div>
        <div><div class="lbl">估算仓储费合计</div><div class="big">${usd(s.fee_total)}</div></div>
      </div>
      <table style="margin-top:14px"><thead><tr><th>风险类型</th><th class="num">范围内子 ASIN</th></tr></thead><tbody>
        ${Object.entries(s.by_risk_type).map(([k, v]) => `<tr><td>${meta.risk_labels[k]}</td><td class="num">${v}</td></tr>`).join('')}
      </tbody></table>
`);
}

/* ------------------------------------------------------------------ params */
