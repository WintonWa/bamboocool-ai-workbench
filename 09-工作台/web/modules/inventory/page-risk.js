/* 异常总览页。函数体逐字来自 18810 版 app.js 的 renderRisk。 */

import {
  CAP_LABEL, CONF_LABEL, SEV_LABEL, chip, info, n0,
  pc, sec,
} from './util.js';

export function renderRisk(c, overview, meta) {
  const o = overview;
  c.innerHTML = `<div class="inv-h1">异常总览</div><div class="sub1">读取与单品盘点同一套结果 · 规则 ${meta.rule_version}</div>` +
    sec('风险版图', chip('derived') + info('<b>说明</b><br>一个子 ASIN 可同时命中多类风险，因此风险条数大于有风险对象数。'), `
      <div class="grid g4">
        <div><div class="lbl">有风险子 ASIN（共 ${o.child_count} 个）</div><div class="big">${o.risk_child_count}</div></div>
        <div><div class="lbl">风险条数</div><div class="big">${o.risk_record_count}</div></div>
        <div><div class="lbl">多风险叠加</div><div class="big">${o.multi_risk_children}</div></div>
        <div><div class="lbl">无风险</div><div class="big">${o.no_risk_children}</div></div>
      </div>
      <table style="margin-top:14px"><thead><tr><th>风险类型</th><th class="num">子 ASIN</th><th class="num">占比</th><th class="num">影响件数</th></tr></thead><tbody>
      ${Object.entries(o.by_risk_type).map(([k, v]) => `<tr><td>${v.label}</td><td class="num">${v.child_count}</td>
        <td class="num">${pc(v.child_count / o.child_count)}</td><td class="num">${n0(v.affected_qty)}</td></tr>`).join('')}
      </tbody></table>
      <div class="spec" style="margin-top:18px">
        <div class="col"><span class="st">严重度分布</span>
          ${['high', 'medium', 'low'].map(k => `<dt>${SEV_LABEL[k]}</dt><dd>${o.severity[k] || 0}</dd>`).join('')}</div>
        <div class="col"><span class="st">承接能力分布</span>
          ${Object.entries(o.capacity).map(([k, v]) => `<dt>${CAP_LABEL[k] || k}</dt><dd>${v}</dd>`).join('')}</div>
        <div class="col"><span class="st">预测置信度分布</span>
          ${Object.entries(o.confidence).map(([k, v]) => `<dt>${CONF_LABEL[k] || k}</dt><dd>${v}</dd>`).join('')}</div>
      </div>
`);
}
