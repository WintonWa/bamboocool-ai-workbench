/* 单品盘点页。函数体逐字来自 18810 版 app.js 的 renderDetail。 */

import {
  CAP_LABEL, SEV_LABEL, balanceChart, bucketBars, chip, fold,
  info, n0, n1, na, packManifest, pc,
  sec, usd,
} from './util.js';

/* 需求判断（Agent 或统计口径回落）。交底见
   00-通用方法与规范/07-需求判断上屏交底.md。

   两种来源故意不画成一样：没跑过判断的对象只有一个回测分数，
   画成和判断一样会让运营以为 342 个对象都被判断过了。 */

/* tone 只给这三档。其余不加 —— 方向由 +/- 符号表达，不用颜色。
   给「淡季 -5%」标警示色是错的：淡季不是问题，是季节。 */
const JUDGE_TONE = { '重度扭曲': 'alert', '轻度扭曲': 'warn', '衰退': 'warn' };

/* impact_pct 是小数。null = Agent 判断不出，与 0（判断为无影响）是两件事，
   必须视觉可区分，所以 null 给「—」。 */
function impactText(v) {
  if (v === null || v === undefined) return '—';
  const pct = Number(v) * 100;
  const sign = pct > 0 ? '+' : '';
  return `${sign}${pct.toFixed(2)}%`;
}

/* 「跑于 …」点开的执行过程。步骤的中文 label / detail / sources 全由 Agent 给，
   页面不翻译也不补写（`tool` 那列是码值，载荷里就没带 —— G9）。

   不显示每步耗时：七步合计只有几毫秒，而一次运行实测 107 秒，模型耗时没被归到
   任何一步。把那个数摆上去，读的人会以为这次运行只花了几毫秒。
   归因修好之前不显示，见 01-方案与数据需求/13-需求预测Agent分段运行需求.md R5。 */
function stepsPop(steps) {
  const rows = steps.map((s) => `<li>
    <span class="inv-st-label">${s.label || '—'}</span>
    ${s.status && s.status !== '完成' ? `<span class="inv-st-bad">${s.status}</span>` : ''}
    <span class="inv-st-detail">${s.detail || '—'}</span>
    ${(s.sources || []).length
      ? `<span class="inv-st-src">${s.sources.join(' · ')}</span>` : ''}
  </li>`).join('');
  return `<b>这一次是怎么跑的</b><ol class="inv-steps">${rows}</ol>`;
}

function judgmentStrip(j) {
  if (!j) return '';

  // 判断置信度只在 Agent 那种显示。回落那种的 confidence 就是回测分数分档，
  // 与头部「预测置信度」同值同理由，再显示一遍就撞上「两数相等不分两句」。
  const conf = j.is_agent && j.confidence
    ? `<span class="inv-jd-conf">判断置信度 <b>${j.confidence}</b>${
        j.confidence_reason ? info(`<b>判断置信度</b><br>${j.confidence_reason}`) : ''}</span>`
    : '';

  // Agent 那种带跑于时间，回落那种不带 —— 回落没有 run。
  // 步骤齐全时这个戳可点开，展示这一次真实的执行过程。
  const steps = j.steps || [];
  const stampText = j.is_agent && j.run
    ? `跑于 ${String(j.run.created_at || '').slice(0, 16).replace('T', ' ')}`
      + (j.run.trigger_label ? ' · ' + j.run.trigger_label : '')
    : '';
  const stamp = !stampText
    ? ''
    : steps.length
      ? `<button type="button" class="inv-jd-stamp inv-jd-stamp-on"`
        + ` data-pop="${encodeURIComponent(stepsPop(steps))}">${stampText} · 看过程</button>`
      : `<span class="inv-jd-stamp">${stampText}</span>`;

  const head = `<div class="inv-jd-head">
    <span class="inv-jd-title">需求判断</span>
    <span class="inv-jd-origin" data-agent="${j.is_agent ? '1' : '0'}">${j.origin_label || ''}</span>
    ${stamp}${conf}
  </div>`;

  // 回落：不铺五条空行，也不重复头部。
  // model_label 与 confidence_reason 在头部四格里已经有了（选用模型 / 预测置信度），
  // 这里再列一遍是重复；回落态唯一头部没说的事实是「还没跑过判断」。
  if (!j.is_agent) {
    return `<div class="inv-judge" data-agent="0">${head}
      <div class="inv-jd-fallback">还没跑过需求判断</div></div>`;
  }

  // ord 是 Agent 定的先后，直接按它排 —— 哪一项排第一是判断结果的一部分。
  const rows = (j.factors || [])
    .slice()
    .sort((x, y) => (x.ord || 0) - (y.ord || 0))
    .map((f) => {
      const tone = JUDGE_TONE[f.state] || '';
      // 只用 label。factor 与 numbers 里的键都是英文码值，一个字都不上屏。
      return `<div class="inv-jd-row"${tone ? ` data-tone="${tone}"` : ''}>
        <span class="inv-jd-name">${f.label}</span>
        <span class="inv-jd-state">${f.state}</span>
        <span class="inv-jd-impact num">${impactText(f.impact_pct)}</span>
        ${f.because ? info(`<b>${f.label} · ${f.state}</b><br>${f.because}`) : ''}
      </div>`;
    })
    .join('');

  return `<div class="inv-judge" data-agent="1">${head}
    ${j.summary ? `<div class="inv-jd-say">${j.summary}</div>` : ''}
    <div class="inv-jd-rows">${rows}</div></div>`;
}

/* 盘点结论带：五条，最要紧的在最上面。
   两条来源同一个形状（Agent 的最新一次 run / 确定性规则兜底），所以这里不分支，
   只在右上角标明来源与跑于何时。设计见
   01-方案与数据需求/10-盘点结论Agent接口契约.md v0.2 §6。 */
function verdictBand(a) {
  const v = a.verdict;
  if (!v || !v.items || !v.items.length) return '';

  const stamp = v.origin === 'agent' && v.run
    ? `跑于 ${v.run.created_at ? String(v.run.created_at).slice(0, 16).replace('T', ' ') : v.run.run_date}`
      + `${v.run.trigger_label ? ' · ' + v.run.trigger_label : ''}`
    : '规则判定';

  const rows = v.items.map((it) => {
    const nums = Object.entries(it.numbers || {});
    return `<div class="inv-vd-row" data-tone="${it.tone}" data-refs="${(it.refs || []).join(',')}">
      <span class="inv-vd-dot"></span>
      <span class="inv-vd-name">${it.label}</span>
      <span class="inv-vd-state">${it.state}</span>
      <span class="inv-vd-say">${it.verdict}</span>
      ${it.because ? info(`<b>${it.label}</b><br>${it.because}`) : ''}
    </div>`;
  }).join('');

  return `<div class="inv-verdicts">
    <div class="inv-vd-head">
      <span class="inv-vd-title">盘点结论</span>
      <span class="inv-vd-stamp">${stamp}</span>
      <button class="inv-vd-btn" type="button" data-open-task="1">分析任务</button>
    </div>
    ${rows}
  </div>`;
}

/* 主图边长 = 右侧信息块高度（两者齐平）。CSS 做不到，理由见 inventory.css 的注释。
   用 ResizeObserver 是因为标题换行、组合内容排数变化都会改右列高度 ——
   只在渲染后量一次，窗口变窄导致换行时就会错位。 */
function sizeIdSquare(root) {
  const wrap = root.querySelector('.idimgwrap');
  const main = root.querySelector('.idmain');
  if (!wrap || !main) return;

  const apply = () => {
    const h = Math.round(main.getBoundingClientRect().height);
    if (h > 0) {
      wrap.style.width = h + 'px';
      wrap.style.height = h + 'px';
    }
  };
  apply();

  if (typeof ResizeObserver === 'function') {
    if (root.__idRo) root.__idRo.disconnect();
    root.__idRo = new ResizeObserver(apply);
    root.__idRo.observe(main);
  }
}

import { renderDayChart } from '../../daychart.js';
import { aiMarkHTML } from '../../aimark.js';

/* renderDetail(容器, ...) 的第一个参数是容器不是 ctx，而方案下拉要 ctx.setParams。
   所以由 inventory.js 在渲染前交一次。 */
let PAGE_CTX = null;
export function setPageCtx(ctx) { PAGE_CTX = ctx; }

export async function renderDetail(c, a, meta) {
  if (!a) { c.innerHTML = '<p class="na" style="margin-top:40px">当前筛选没有结果</p>'; return; }
  const id = a.identity, d = a.demand, inv = a.inventory, p = a.projection, ag = a.aging, fee = a.fee;
  const conf = p.available ? p.scopes.sellable_plus_confirmed : null;
  const only = p.available ? p.scopes.sellable_only : null;
  const primary = a.risks[0];

  let h = `<div class="idblock">
    <div class="idimgwrap">
      <img class="idimg" src="/assets/product-placeholder.png" alt="商品主图">
      <span class="idimgtag">示意图</span>
    </div>
    <div class="idmain">
      <div class="inv-h1">${id.child_asin}${id.product_name ? `<span class="nick">（${id.product_name}）</span>` : ''}</div>
      <div class="idrow">
        <span class="idparent">父体 <b>${id.parent_asin || '—'}</b></span>
        <span class="idbtn" data-pop="${encodeURIComponent(`<b>产品信息</b><dl>
          <dt>款号</dt><dd>${id.style_no || '—'}</dd>
          <dt>组合 / 尺码</dt><dd>${id.combination || '—'} / ${id.size || '—'}</dd>
          <dt>装盒数</dt><dd>${a.economics.pack_size ? a.economics.pack_size + ' 条/盒' : '—'}</dd>
          <dt>SKU</dt><dd>${id.sku || '—'}</dd>
          <dt>FNSKU</dt><dd>${id.fnsku || '—'}</dd>
          <dt>店铺</dt><dd>${id.store || '—'}</dd>
          <dt>负责人</dt><dd>${id.operator || '—'}</dd>
          <dt>品类</dt><dd>${id.category || '—'}</dd>
          <dt>属性完整度</dt><dd>${id.attribute_quality || '—'}</dd>
        </dl>`)}">产品信息</span>
      </div>
      <dl class="specwide idpack"><dt>组合内容</dt><dd>${packManifest(id, a.economics.pack_size)}</dd></dl>
    </div>
  </div>`;

  // 1. 产品与盘点结果
  const CAP_TONE = {can_absorb:'good', limited:'warn', cannot_absorb:'alert', unknown:'', unavailable:''};
  const cap = [CAP_LABEL[a.capacity.level] || '—', CAP_TONE[a.capacity.level] || ''];
  // 结论先行：五条在两个灰框上面。标题旁原有的数据性质标注已删 ——
  // 它对运营没有决策价值，而且把盘点结论标成「派生」本身就不对（结论来自 Agent）。
  h += sec('产品与盘点结果' + aiMarkHTML('盘点结论') +
        '<span data-scheme-slot="盘点结论"></span>', '', `
    ${verdictBand(a)}
    <div class="verdict-side">
      <span class="v-tag ${cap[1]}">承接<b>${cap[0]}</b>${a.capacity.note ? info(`<b>承接判断</b><br>${a.capacity.note}`) : ''}</span>
      <span class="v-tag ${a.risks.length ? (primary && primary.severity === 'high' ? 'alert' : 'warn') : 'good'}">风险<b>${a.risks.length ? a.risks.length + ' 类' : '无'}</b></span>
      <span class="v-tag">${id.product_lifecycle || '未分类'} · ${id.goods_status || '—'}</span>
    </div>
    <div class="states">${a.states.map(st =>
      `<span class="state" data-pop="${encodeURIComponent(`<b>${st.state}</b><br>${st.detail}`)}">${st.state}</span>`).join('')}</div>
    <div class="spec spec2">
      <div class="col"><span class="st">市场表现</span>
        <dt>小类排名</dt><dd class="text">${id.category_rank || '—'}</dd>
        <dt>评分</dt><dd>${id.rating ?? '—'}</dd>
        <dt>单位成本</dt><dd>${a.economics.unit_cost ? usd(a.economics.unit_cost, 2) : '—'} ${a.economics.unit_cost ? chip(a.economics.unit_cost_origin) : ''}</dd>
      </div>
      <div class="col"><span class="st">2026-06 经营</span>
        <dt>销量</dt><dd>${n0(a.monthly.units_sold)}</dd>
        <dt>净销售额</dt><dd>${usd(a.monthly.net_sales)}</dd>
        <dt>毛利</dt><dd>${usd(a.monthly.order_gross_profit)}</dd>
        <dt>毛利率</dt><dd>${pc(a.monthly.order_gross_margin)}</dd>
      </div>
    </div>`);

  // 2. 销量与需求 —— 逐日柱状图（R2）
  {
    const ch = a.chart, av = d.available;
    const head = [];
    if (av) {
      head.push(`<div><div class="lbl">预测来源</div><div class="big2">${d.run.model_label || '—'}</div>
        <div class="dim">${d.run.origin === 'agent'
          ? `同批次产出 ${d.run.horizon_days} 天逐日预测与五项判断`
          : (d.run.model_wape == null ? '' : `${d.run.validation_days} 天回测偏差 ${(d.run.model_wape * 100).toFixed(1)}%`)}</div></div>`);
      head.push(`<div><div class="lbl">预估日均</div><div class="big">${n1(d.forecast_daily)}</div>
        <div class="dim">${d.horizon_effective_days} 天累计 ${n0(d.forecast_90d)} 件</div></div>`);
      head.push(`<div><div class="lbl">近 7 天实际日均</div><div class="big">${n1(d.recent_actual_daily)}</div>
        <div class="dim">${d.vs_recent_actual == null ? '无可比' : '预估为其 ' + n1(d.vs_recent_actual) + ' 倍'}</div></div>`);
      /* 置信度只在回落态放头部。Agent 那种它和判断带的「判断置信度」同出一条 run 行，
         值和理由逐字相同，两处都显示就撞上「两数相等不分两句」。
         留判断带那处，因为置信度说的是那次判断有多可信，跟判断待在一起。
         （这一格原先叫「置信度」，我改名成「预测置信度」是因为当时两者真不同 ——
         头部是回测偏差、判断带是 Agent 自信度。职责恢复后 model_wape/bias/mae
         全为 null，回测偏差没有了，改名的前提也就没了。） */
      if (d.run.origin !== 'agent') {
        head.push(`<div><div class="lbl">预测置信度</div><div class="big2">${d.confidence_label}</div>
          <div class="dim">${d.confidence_reason || ''}</div></div>`);
      }
    }

    h += sec('销量与需求' + aiMarkHTML('需求预测') +
        '<span data-scheme-slot="需求预测"></span>' +
        /* 导出。2026-08-31 会上王楠：柱状图「不方便做工作」，
           「他给其他部门下单也是用文件下单」。所以给的是 xlsx 不是 CSV。 */
        `<button class="inv-vd-btn inv-export" type="button"
           data-export-daily="${a.child_asin}">导出 Excel</button>`,
      (av ? '实际 客户真实值 · 预估 预测 Agent' : '实际 客户真实值') + info(`
      <b>这个板块的算法分工</b><br>
      需求预测<b>不在页面上算</b>。由独立的预测 Agent 离线判断：哪段历史该采信、
      活动影响多大、生命周期在哪一段 —— 这些是逐例判断，加权平均做不到。
      <dl><dt>Agent 给</dt><dd>未来逐日销量、预测区间、关键调整项及依据</dd>
        <dt>本页算</dt><dd>逐日库存余额、覆盖天数、警戒日、断货日、缺口、超量、补货量、承接能力、五类风险</dd>
        ${av && d.run.origin === 'agent' ? `<dt>本次 Agent 运行</dt><dd>基准日 ${d.run.as_of_date} · 连续预测 ${d.run.horizon_days} 天
          · 逐日 P10/P50/P90、五项需求判断与过程步骤共用一个 run_id</dd>
        <dt>模型</dt><dd>${d.run.model_version || 'Pi 本地配置模型'}</dd>` : (av ? `<dt>快照运行</dt><dd>基准日 ${d.run.as_of_date} · 预估 ${d.run.horizon_days} 天
          · 候选模型 ${(d.run.candidate_model_labels || []).join(' / ')}，本对象选用 ${d.run.model_label}</dd>
        <dt>回测</dt><dd>${d.run.validation_days} 天，平均偏差 ${d.run.model_wape == null ? '—' : (d.run.model_wape * 100).toFixed(1) + '%'}
          ，偏向 ${d.run.model_bias == null ? '—' : (d.run.model_bias > 0 ? '偏高' : '偏低') + ' ' + Math.abs(d.run.model_bias * 100).toFixed(1) + '%'}</dd>` : '')}
      </dl>
      <b>柱子怎么读</b><br>深色柱是实际销量；浅色柱是预估，柱顶细线是预估区间；
      斜纹浅灰柱是当天缺货 —— 那个数字是「能卖出去多少」，不是「有多少人要买」。
      图上方的横条是活动区间，每类活动一条，可以在图例里单独关掉。`),
      `${av ? `<div class="grid g4">${head.join('')}</div>` : `
        <div class="notice">${d.reason}。${d.detail || ''}</div>`}
      ${d.horizon_note ? `<div class="notice sm">${d.horizon_note}</div>` : ''}
      ${judgmentStrip(a.forecast_judgment)}
      <div class="inv-chartmount" style="margin-top:14px"></div>`);
  }

  // 3. 库存盘点
  if (!inv.available) h += sec('库存盘点', '', `<div class="na">${inv.reason}</div>`);
  else h += sec('库存盘点', chip('customer_actual') + (inv.identity_note ? info(`<b>口径说明</b><br>${inv.identity_note}`) : ''), `
    <div class="grid g4">
      <div><div class="lbl">当前可售</div><div class="big ${inv.sellable_qty ? '' : 'zero'}">${n0(inv.sellable_qty)}</div></div>
      <div><div class="lbl">受限（预留+待调仓+入库中）</div><div class="big">${n0(inv.restricted_qty)}</div></div>
      <div><div class="lbl">FBA 可用率</div><div class="big">${pc(inv.availability_rate)}</div></div>
      <div><div class="lbl">已知总库存</div><div class="big">${n0(inv.total_known_qty)}</div></div>
    </div>
    <div class="grid g2" style="margin-top:12px">
      <table><thead><tr><th>库存状态</th><th class="num">件数</th><th>可立即销售</th></tr></thead><tbody>
        ${inv.states.map(s => `<tr><td>${s.state}</td><td class="num">${n0(s.qty)}</td>
          <td class="dim">${s.immediate ? '是' : '否'}</td></tr>`).join('')}</tbody></table>
      <table><thead><tr><th>库存位置</th><th class="num">可售</th><th class="num">受限</th><th class="num">合计</th></tr></thead><tbody>
        ${inv.locations.map(l => `<tr><td>${l.location}</td><td class="num">${n0(l.sellable)}</td>
          <td class="num">${n0(l.restricted)}</td><td class="num">${n0(l.total)}</td></tr>`).join('')}</tbody></table>
    </div>`);

  // 4. 在途与批次
  h += sec('在途与到货', chip('customer_actual') + ' 数量 · ' + chip('estimated') + ' 多数 ETA' + info(`
    <b>在途口径</b><br>子 ASIN 的在途件数取客户实际值。下表出货记录的粒度是「出货行 × 款号」，
    盒数是整个款号的量，未分摊到子 ASIN，因此两者不应相加。
    ${p.available ? '<br>' + p.inbound_note : ''}`), `
    <div class="grid g3">
      <div><div class="lbl">FBA 在途（子体真实数量）</div><div class="big">${n0(inv.inbound_qty || 0)}</div></div>
      <div><div class="lbl">款号级出货记录</div><div class="big">${a.style_events.length}</div></div>
      <div><div class="lbl">其中原表 ETA</div><div class="big">${a.style_events.filter(e => e.eta_origin === 'customer_actual').length}</div></div>
    </div>
    ${a.style_events.length ? `<table style="margin-top:10px"><thead><tr><th>货件</th><th>创建</th><th class="num">盒数</th>
      <th>最早到货</th><th>最晚到货</th><th>ETA 来源</th><th>状态</th></tr></thead><tbody>
      ${a.style_events.slice(-8).map(e => `<tr><td>${e.shipment_id || '—'}</td><td class="dim">${(e.created_at || '').slice(0,10)}</td>
        <td class="num">${n0(e.sellable_units)}</td><td>${e.eta_earliest_effective || '—'}</td><td>${e.eta_latest_effective || '—'}</td>
        <td>${chip(e.eta_origin)}</td><td class="dim">${e.event_status_as_of}</td></tr>`).join('')}</tbody></table>` : '<div class="na">该款号无出货记录</div>'}
`);

  // 5. 库存承接
  if (!p.available) h += sec('库存承接', '', `<div class="na">${p.reason}</div>`);
  else h += sec('库存承接', chip('derived') + ` 安全库存 ${p.safety_days} 天 ` + chip(p.safety_days_origin) + info(`
    <b>覆盖与缺口口径</b>
    <dl><dt>覆盖天数</dt><dd>（可售 + 窗口内已确认到货）÷ 预测日均</dd>
      <dt>已确认到货</dt><dd>有 ETA 的在途批次，入库后延迟 ${meta.parameters.find(x => x.key === 'internal_release_lag_days').value} 天转可售</dd>
      <dt>安全库存</dt><dd>${p.safety_days} 天 × 预测日均 = ${n0(conf.safety_stock_qty)} 件</dd>
      <dt>断货日</dt><dd>逐日余额首次 ≤ 0 的日期</dd>
      <dt>合理上限</dt><dd>${n0(p.reasonable_max_qty)} 件（${meta.parameters.find(x => x.key === 'max_cover_days').value} 天消化上限）</dd>
      <dt>消化天数</dt><dd>已知总库存 ÷ 预测日均</dd></dl>`), `
    <div class="grid g4">
      <div><div class="lbl">覆盖天数 · 仅可售</div><div class="big">${only.cover_days === null ? '—' : n1(only.cover_days)}</div>
        ${only.cover_days === null ? na(only.cover_days_unavailable_reason) : ''}</div>
      <div><div class="lbl">覆盖天数 · 可售+确认转可售</div><div class="big">${conf.cover_days === null ? '—' : n1(conf.cover_days)}</div></div>
      <div><div class="lbl">预计断货日</div><div class="big compact">${conf.stockout_date || '窗口内不断货'}</div></div>
      <div><div class="lbl">安全线突破日</div><div class="big compact">${conf.safety_breach_date || '窗口内未突破'}</div></div>
    </div>
    <div class="grid g4" style="margin-top:12px">
      <div><div class="lbl">30 天缺口</div><div class="big">${n0(conf.shortage_30d)}</div></div>
      <div><div class="lbl">${d.daily.length} 天缺口</div><div class="big">${n0(conf.shortage_90d)}</div></div>
      <div><div class="lbl">超量件数（超出合理上限 ${n0(p.reasonable_max_qty)} 件）</div><div class="big">${n0(p.excess_qty)}</div></div>
      <div><div class="lbl">消化天数</div><div class="big">${p.depletion_days === null ? '—' : n1(p.depletion_days)}</div>
        ${p.depletion_days === null ? na(p.depletion_unavailable_reason) : ''}</div>
    </div>
    <div style="margin-top:14px"><div class="lbl">未来 ${d.daily.length} 天可用库存余额（可售 + 确认转可售）</div>
      ${balanceChart(conf.series, conf.safety_stock_qty)}
      <div class="legend"><span><i style="background:var(--ink)"></i>余额</span>
        <span><i style="background:var(--alert)"></i>零线</span><span><i style="background:var(--warn)"></i>安全库存</span></div></div>
`);

  // 6. 库龄
  h += sec('库龄', chip('derived') + ' 前滚至基准日' + info(`
    <b>库龄推算方式</b><br>由 ${meta.data.age_source_date} 的库龄档按 1 天粒度均匀切片反推收货日，
    按 ${meta.data.depletion_sensitivity.applied_method} 扣减真实 ${meta.data.age_rollforward.window_days} 天销量，
    再对齐到 ${meta.data.as_of_date} 的 FBA 总库存。
    <dl><dt>批次条数</dt><dd>${ag.lot_count}</dd>
      <dt>跨 180 天</dt><dd>批次剩余库龄 ≤ 3 / 7 天的件数合计</dd></dl>`), `
    <div class="grid g4">
      <div><div class="lbl">181 天以上</div><div class="big">${n0(ag.aged_181_qty)}</div></div>
      <div><div class="lbl">181+ 占比</div><div class="big">${pc(ag.aged_181_share)}</div></div>
      <div><div class="lbl">未来 3 天跨 180 天</div><div class="big ${ag.crossing_180_within_3d ? '' : 'zero'}">${n0(ag.crossing_180_within_3d)}</div></div>
      <div><div class="lbl">未来 7 天跨 180 天</div><div class="big ${ag.crossing_180_within_7d ? '' : 'zero'}">${n0(ag.crossing_180_within_7d)}</div></div>
    </div>
    <div style="margin-top:12px">${bucketBars(ag.as_of_buckets, ag.june_buckets)}</div>
    <div class="grid g2" style="margin-top:12px">
      <div><div class="lbl">批次（共 ${ag.lot_count} 条，按库龄倒序取前 8）</div>
        <table style="margin-top:4px"><thead><tr><th>收货日</th><th class="num">库龄</th><th class="num">距 180 天</th><th class="num">件数</th><th>来源</th></tr></thead><tbody>
        ${[...ag.lots].sort((x, y) => y.age_days - x.age_days).slice(0, 8).map(l => `<tr><td>${l.received_at}</td>
          <td class="num">${l.age_days}</td><td class="num">${l.days_to_180}</td><td class="num">${n0(l.quantity)}</td>
          <td>${chip(l.value_origin)}</td></tr>`).join('')}</tbody></table></div>
      <div><dl class="kv">
        <dt>2026-06-30 开账</dt><dd>${n0(ag.rollforward.opening_qty_2026_06_30)}</dd>
        <dt>期间消耗（真实窗口）</dt><dd>${n0(ag.rollforward.consumption_applied)}</dd>
        <dt>推定到货</dt><dd>${n0(ag.rollforward.implied_arrival_qty)}</dd>
        <dt>额外扣减</dt><dd>${n0(ag.rollforward.extra_depletion_to_match_snapshot)}</dd>
        <dt>2026-08-03 收账</dt><dd>${n0(ag.rollforward.closing_qty_2026_08_03)}</dd>
        <dt>与 FBA 总库存差</dt><dd>${n0(ag.rollforward.balance_residual)}</dd>
      </dl>
      </div>
    </div>`);

  // 7. 仓储费
  if (!fee.available) h += sec('仓储费', '', `<div class="na">${fee.reason}</div>`);
  else h += sec('仓储费', chip('estimated') + info(`
    <b>估算方式</b><br>计费体积 × 月费率，181 天以上部分另加超龄附加费。
    <dl><dt>计费体积</dt><dd>${fee.billed_volume_m3} m³ = 件数 × ${fee.unit_volume_m3} m³/盒</dd>
      <dt>月费率</dt><dd>${usd(meta.parameters.find(x => x.key === 'fee_rate_per_m3_month').value, 2)} / m³</dd></dl>`), `
    <div class="grid g4">
      <div><div class="lbl">估算月仓储费</div><div class="big">${usd(fee.total_fee, 2)}</div></div>
      <div><div class="lbl">正常费 / 超龄附加费</div><div class="big compact">${usd(fee.regular_fee, 2)} / ${usd(fee.aged_surcharge, 2)}</div></div>
      <div><div class="lbl">占净销售额</div><div class="big">${pc(fee.sales_ratio)}</div></div>
      <div><div class="lbl">占毛利</div><div class="big">${fee.gross_ratio === null ? '—' : pc(fee.gross_ratio)}</div>
        ${fee.gross_ratio === null ? na(fee.gross_ratio_unavailable_reason) : ''}</div>
    </div>
    <dl class="kv" style="margin-top:12px"><dt>计费体积</dt><dd>${fee.billed_volume_m3} m³</dd>
      <dt>单件体积</dt><dd>${fee.unit_volume_m3} m³/盒</dd></dl>`);

  // 8. 风险与原因
  h += sec('风险点与形成原因', chip('derived') + ` 规则 ${a.rule_version}`, a.risks.length ? a.risks.map(r => `
    <div class="risk ${r.severity}"><div class="rh"><span class="rt">${r.label}</span>
      <span class="rs">${SEV_LABEL[r.severity] || r.severity}危 · 排序分 ${r.risk_score} · 影响 ${n0(r.affected_qty)} 件</span>
      ${info(`<b>判定依据</b><dl>${Object.entries(r.evidence).map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('')}</dl>`)}</div>
      <div class="head">${r.headline}</div>
      <ul>${r.reasons.filter(Boolean).map(x => `<li>${x}</li>`).join('')}</ul></div>`).join('')
    : '<div class="na">五类风险在当前阈值下均未命中</div>');

  // 9. 数据与口径（折叠）
  h += fold('数据与口径', a.unavailable_outputs.length ? `${a.unavailable_outputs.length} 项不可计算` : '', `
    <dl class="kv" style="grid-template-columns:auto 1fr">
      <dt>数据包</dt><dd>v${meta.data.dataset_version}（生成于 ${meta.data.generated_at}）</dd>
      <dt>盘点基准日</dt><dd>${a.as_of_date}</dd>
      <dt>库龄来源日</dt><dd>${meta.data.age_source_date} → 前滚 ${meta.data.age_rollforward.window_days} 天</dd>
      <dt>规则版本</dt><dd>${a.rule_version}</dd>
    </dl>
    ${a.unavailable_outputs.length ? `<div style="margin-top:10px"><div class="lbl">本对象不可计算的输出</div>
      <ul class="inv-reasons">${a.unavailable_outputs.map(u => `<li>${u.item}：${u.reason}</li>`).join('')}</ul></div>` : ''}`);

  c.innerHTML = h;
  // ECharts needs a live element, so the chart mounts after the markup lands.
  sizeIdSquare(c);

  /* 导出按钮。用委托挂在容器上 —— 这个函数每次切对象都重跑，
     直接给按钮绑会在重渲染后失效。
     走 <a download> 而不是 fetch + blob：文件名由后端的
     Content-Disposition 决定，浏览器原生下载就用它，不必在前端重拼一遍。 */
  if (!c.dataset.exportBound) {
    c.dataset.exportBound = '1';
    c.addEventListener('click', (e) => {
      const btn = e.target.closest('[data-export-daily]');
      if (!btn) return;
      const asin = btn.getAttribute('data-export-daily');
      if (!asin) return;
      const prev = btn.textContent;
      btn.textContent = '导出中…';
      btn.disabled = true;
      const link = document.createElement('a');
      link.href = `/api/inventory/export-daily/${encodeURIComponent(asin)}`;
      link.rel = 'noopener';
      document.body.appendChild(link);
      link.click();
      link.remove();
      // 下载是浏览器接手的，页面拿不到完成事件，所以按时间恢复按钮。
      setTimeout(() => { btn.textContent = prev; btn.disabled = false; }, 1200);
    });
  }

  /* 方案下拉。这一页是拼字符串的，schemePicker 回的是 DOM 节点，
     所以先在标题里留槽，渲染完再挂进去。ctx 由 inventory.js 通过
     setPageCtx() 交下来 —— renderDetail 的第一个参数是容器不是 ctx。 */
  if (PAGE_CTX && PAGE_CTX.schemePicker) {
    for (const slot of c.querySelectorAll('[data-scheme-slot]')) {
      const node = PAGE_CTX.schemePicker(slot.getAttribute('data-scheme-slot'));
      if (node) slot.replaceWith(node);
      else slot.remove();
    }
  }

  const mount = c.querySelector('.inv-chartmount');
  if (mount) await renderDayChart(mount, a);
}
