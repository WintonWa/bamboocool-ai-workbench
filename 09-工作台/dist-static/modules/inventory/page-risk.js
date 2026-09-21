/* 异常总览页。2026-09-04 按 11-页面框架与决策/Image2-视觉灵感 的参考图重做。
 *
 * 重做前是「四个等权大数字 + 一张四列纯数字表 + 三列 dt/dd 边缘分布」。
 * 三个具体毛病：
 *   1. 四个数字裸放在 grid.g4 里，没有占比也没有容器，读不出 242 是多还是少
 *   2. 风险类型表看得出哪类多，看不出哪类里有多少是高危
 *   3. 严重度分布与承接能力分布两列并排，答不了「高危里有多少是根本吃不下的」
 *      —— 那是交叉表的问题，两个边缘分布怎么摆都答不了
 *
 * 现在：概览卡（标签在上、带占比）→ 两张图（堆叠条 + 交叉矩阵）→ 高风险清单。
 * 两张图的数据都从 rows 逐行算，不是编的（口径见 charts.js 顶部注释）。
 */

import { CAP_LABEL, CONF_LABEL, SEV_LABEL, chip, info, n0, n1, pc, sec } from './util.js';
import { aiMarkHTML } from '../../aimark.js';
import { riskSeverityBars, severityCapacityHeatmap } from './charts.js';

/* 概览卡一格。标签在上、值在下、副行给占比 —— 不出现没有标签的裸数字。 */
function cell(label, value, sub, tone) {
  return `<div class="inv-cell">
    <div class="inv-cell-label">${label}</div>
    <div class="inv-cell-value${tone ? ' ' + tone : ''}">${value}</div>
    ${sub ? `<div class="inv-cell-sub">${sub}</div>` : ''}
  </div>`;
}

/* 构成条。段宽按比例，零值段不渲染（0 宽会留一条缝）。 */
function stack(segs) {
  const rows = segs.filter((s) => s.n > 0);
  if (!rows.length) return '';
  const total = rows.reduce((a, s) => a + s.n, 0);
  return `<div class="inv-stackwrap">
    <div class="inv-stack">${rows.map((s) =>
    `<i class="inv-seg ${s.kind}" style="width:${(s.n / total) * 100}%"
       title="${s.label} ${s.n} · ${pc(s.n / total)}"></i>`).join('')}</div>
    <div class="inv-stacklegend">${rows.map((s) =>
    `<span class="inv-lg ${s.kind}"><i></i>${s.label}<b>${n0(s.n)}</b></span>`).join('')}</div>
  </div>`;
}

export function renderRisk(c, payload, meta) {
  const o = payload.overview;
  const rows = payload.rows || [];
  const total = o.child_count || 1;

  /* 高风险清单：按综合风险得分降序。risk_score 是库存模块自己判的，不另立排序。 */
  const top = rows
    .filter((r) => r.risk_count > 0)
    .sort((a, b) => (b.risk_score || 0) - (a.risk_score || 0))
    .slice(0, 12);

  const SEV_TONE = { high: 'alert', medium: 'warn', low: '' };

  let h = `<div class="inv-h1">异常总览</div>
    <div class="sub1">读取与单品盘点同一套结果 · 规则 ${meta.rule_version}</div>`;

  // 概览卡。占比分母写在标签里，否则「38.4%」不知道是谁的 38.4%。
  h += `<div class="inv-card">
    ${cell('有风险子 ASIN', n0(o.risk_child_count),
    `占监控 ${total} 个的 ${pc(o.risk_child_count / total)}`, 'alert')}
    ${cell('风险条数', n0(o.risk_record_count),
    `平均每个有风险对象 ${n1(o.risk_record_count / (o.risk_child_count || 1))} 条`)}
    ${cell('多风险叠加', n0(o.multi_risk_children),
    `占有风险对象的 ${pc(o.multi_risk_children / (o.risk_child_count || 1))}`, 'warn')}
    ${cell('无风险', n0(o.no_risk_children),
    `占监控 ${total} 个的 ${pc(o.no_risk_children / total)}`, 'good')}
  </div>`;

  // 两张图并排
  h += sec('风险版图' + aiMarkHTML('库存总体分析'),
    chip('derived') + info(`<b>这两张图怎么读</b><br>
      左图按<b>主风险</b>分类堆叠：一个子 ASIN 只落在它的主风险那一行，
      段是该对象的严重度。这样一个同时命中两类风险的对象不会被算两次。
      条末的数字是该类影响件数合计。<br>
      右图是<b>真交叉表</b>：逐个子 ASIN 数「严重度 × 承接能力」。
      它回答的是「高危里有多少是根本吃不下的」—— 严重度分布和承接能力分布
      两列并排答不了这个问题。<br>
      一个子 ASIN 可同时命中多类风险，因此风险条数（${o.risk_record_count}）
      大于有风险对象数（${o.risk_child_count}）。`),
  `<div class="inv-chartpair">
      <div class="inv-chartcell">
        <div class="inv-chartcap">各主风险类型影响件数（按严重度堆叠 · 降序）</div>
        <div class="inv-mount" data-chart="risk"></div>
      </div>
      <div class="inv-chartcell">
        <div class="inv-chartcap">严重度 × 承接能力矩阵（子 ASIN 数量）</div>
        <div class="inv-mount" data-chart="matrix"></div>
      </div>
    </div>
    <div class="inv-substack">
      <div class="inv-substack-lab">预测置信度分布（影响预测可信度，不是风险严重度）</div>
      ${stack([
    { label: CONF_LABEL.high || '高', n: o.confidence.high || 0, kind: 'good' },
    { label: CONF_LABEL.medium || '中', n: o.confidence.medium || 0, kind: 'warn' },
    { label: CONF_LABEL.low || '低', n: o.confidence.low || 0, kind: 'alert' },
  ])}
    </div>`);

  // 高风险清单
  h += sec('高风险子 ASIN（按综合风险得分降序）', chip('derived')
    + ` 前 ${top.length} / 共 ${o.risk_child_count} 个有风险`,
  top.length ? `<div class="inv-tablewrap"><table class="inv-risktable">
      <thead><tr>
        <th>子 ASIN</th><th>款号 / 规格</th><th>主风险</th><th>严重度</th>
        <th class="num">风险条数</th><th class="num">影响件数</th>
        <th class="num">覆盖天数</th><th>承接能力</th><th>预测置信度</th><th></th>
      </tr></thead><tbody>
      ${top.map((r) => {
    const qty = r.risk_qty ? Object.values(r.risk_qty).reduce((a, b) => a + b, 0) : 0;
    return `<tr data-open="${r.child_asin}">
          <td class="strong">${r.child_asin}</td>
          <td class="dim">${r.style_no || '—'} · ${r.combination || '—'} / ${r.size || '—'}</td>
          <td>${meta.risk_labels[r.primary_risk] || r.primary_risk || '—'}</td>
          <td class="${SEV_TONE[r.primary_severity] || ''}">${SEV_LABEL[r.primary_severity] || '—'}</td>
          <td class="num">${r.risk_count}</td>
          <td class="num">${n0(qty)}</td>
          <td class="num${r.cover_days !== null && r.cover_days < 30 ? ' alert' : ''}">${
      r.cover_days === null ? '—' : n1(r.cover_days)}</td>
          <td class="${r.capacity_level === 'cannot_absorb' ? 'alert' : ''}">${
      CAP_LABEL[r.capacity_level] || '—'}</td>
          <td class="${r.confidence === 'low' ? 'warn' : ''}">${CONF_LABEL[r.confidence] || '—'}</td>
          <td><span class="inv-golink">查看盘点 →</span></td>
        </tr>`;
  }).join('')}
    </tbody></table></div>` : '<div class="na">当前阈值下没有命中任何风险</div>');

  c.innerHTML = h;

  // 图在标记落地后再挂 —— ECharts 需要一个已经有尺寸的活元素
  const mountOf = (k) => c.querySelector(`.inv-mount[data-chart="${k}"]`);
  riskSeverityBars(mountOf('risk'), rows, meta.risk_labels);
  severityCapacityHeatmap(mountOf('matrix'), rows);
}
