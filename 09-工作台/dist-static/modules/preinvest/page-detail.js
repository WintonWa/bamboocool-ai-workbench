/* 单品依据页（pre-detail）
 *
 * 对象是一个**子 ASIN**。两块内容：
 *   1. 逐日图 —— 把销售月那一段圈出来，那段求和就是预估销量
 *   2. 为什么这么预估 —— 需求预测 Agent 的判断，一句话总结 + 五项因子 + 确定程度
 *
 * 用户 2026-09-04：「库存那个单品盘点那个柱状图，我觉得它会更全，它会把为什么
 * 这么预估都标记起来。比如说就是会说哎这个产品怎么样，然后它是新品还是怎么的，
 * 然后后面有什么规划，然后之前是什么情况，它就是一个 Agent 的样子。这样你下面
 * 这个判断这个数该不该改就不需要了呀，因为你前面已经解释清楚了。」
 *
 * 所以三张证据卡（去年同期/上一轮/活动）与尺码拆分都已删除 ——
 * 那些内容 Agent 的五项因子里本来就讲了，而尺码这一层现在就是对象本身。
 *
 * 五项因子的文字**一个字都不由这个模块编**，全部原样来自 Agent 落库的 because。
 */

import { renderDayChart, disposeDayChart } from '../../daychart.js';
import { info, kv, n0, n1, n2, pc, sec, sgn } from './util.js';
import { loadBuffer, loadOverrides, saveOverride } from './page-plan.js';

let GPB = 666.67;
const tons = (b) => (Number(b) || 0) * GPB / 1e6;

export function renderDetail(root, d, meta, ctx) {
  if (d.fabric_g_per_box) GPB = Number(d.fabric_g_per_box);
  const buf = loadBuffer(d.buffer_hint);
  const ov = loadOverrides();

  root.innerHTML =
    head(d, buf, ov)
    + chartBlock(d)
    + judgeBlock(d)
    + historyBlock(d);

  mountChart(root, d);
  wire(root, d, buf, ctx);
}

/* ---- 图：库存那张逐日图，圈出销售月那一段 -----------------------------
 *
 * **用的就是库存那张图本身**（web/daychart.js，已提升为外壳共享组件），
 * 不是另画一张。用户 2026-09-04：「不是让你把库存那个搬过来吗？然后你把预投的
 * 那个阶段给圈出来就行啊……你同样都是跑 90 天的预测，你为什么非要在这再跑一遍呢？」
 *
 * 数据也不重算：直接取库存声明的对外路由 /api/inventory/child/<asin> 里的
 * `chart`。那是**数据依赖**（契约允许跨模块读对方声明的输出），
 * 不是代码依赖（G12 禁的是 import 别的模块的代码）。
 *
 * 代价要说清：库存模块降级时这张图取不到数据。所以取数失败要优雅降级，
 * 显式说「逐日图暂不可用」而不是留白 —— 留白会被读成「这个对象没数据」。
 */
async function mountChart(root, d) {
  const box = root.querySelector('[data-chart]');
  if (!box) return;
  box.innerHTML = '<div class="daydetail"><span class="dim">正在取逐日数据…</span></div>';
  let payload;
  try {
    const res = await fetch(
      `/api/inventory/child/${encodeURIComponent(d.child_asin)}`
      + (location.search || ''));
    if (!res.ok) throw new Error(`接口返回 ${res.status}`);
    payload = await res.json();
  } catch (err) {
    box.innerHTML = `<div class="daydetail"><span class="dim">逐日图暂不可用（${
      String(err.message || err)}）。上面的预估销量与建议预投照常可用 ——
      它们不依赖这张图。</span></div>`;
    return;
  }
  if (!payload || !payload.chart) {
    box.innerHTML = '<div class="daydetail"><span class="dim">'
      + '这个子 ASIN 没有逐日数据可画。</span></div>';
    return;
  }
  const w = d.window;
  await renderDayChart(box, payload, {
    highlight: { from: w.from, to: w.to, label: `${w.month} 预投窗口` },
  });
}

/* ---- 顶部：这个 ASIN 该投多少 ----------------------------------------- */

function head(d, buf, ov) {
  const id = d.identity;
  const f = d.forecast;
  const a = f.p50 === null || f.p50 === undefined ? null : Math.round(f.p50 * (1 + buf));
  const cur = ov[d.child_asin];
  const has = cur !== undefined && cur !== null;
  const final = has ? Number(cur) : a;
  return `<div class="pre-h1">${d.child_asin}
      <span class="pre-h1sub">${id.size || ''}　${id.style_no} · ${id.combination}</span></div>
    <div class="pre-sub1">${id.category || '—'} · ${id.operator || '—'} ·
      ${id.pack_size ? id.pack_size + ' 条一盒' : '单包条数缺失'} ·
      ${id.product_lifecycle || '—'} · ${id.goods_status || '—'}
      ${id.category_rank ? ' · 小类排名 ' + id.category_rank : ''}
      ${id.rating ? ' · 评分 ' + n1(id.rating) : ''}</div>

    <section class="pre-decide">
      <div class="pre-decidemain">
        <div class="pre-decidecol">
          <div class="k">${d.window.month} 预估销量</div>
          <div class="v">${n0(f.p50)} <span class="u">盒</span></div>
          <div class="s">${f.p10 === null ? '' : n0(f.p10) + ' ~ ' + n0(f.p90)}</div>
        </div>
        <div class="pre-decidearrow" aria-hidden="true">+${(buf * 100).toFixed(0)}%</div>
        <div class="pre-decidecol">
          <div class="k">系统建议</div>
          <div class="v" data-sug>${n0(a)} <span class="u">盒</span></div>
          <div class="s">Buffer 在预投表页头改</div>
        </div>
        <div class="pre-decidearrow" aria-hidden="true">→</div>
        <div class="pre-decidecol on">
          <div class="k">我要投</div>
          <div class="v"><input class="pre-inp big" type="number" min="0" step="1"
            value="${has ? final : ''}" placeholder="${a === null ? '' : n0(a)}"
            aria-label="我要投多少盒" data-cid="${d.child_asin}"> <span class="u">盒</span></div>
          <div class="s" data-delta>${(has && a !== null)
            ? sgn(final - a) + ' 盒 · 已手工调整' : '留空就按建议走'}</div>
        </div>
        <div class="pre-decidecol">
          <div class="k">折面料</div>
          <div class="v" data-tons>${n2(tons(final))} <span class="u">吨</span></div>
          <div class="s" data-tiao>${id.pack_size
            ? n0((final || 0) * id.pack_size) + ' 条' : '条数缺失'}</div>
        </div>
      </div>
    </section>`;
}

/* ---- 图：圈出销售月那一段 --------------------------------------------- */

function chartBlock(d) {
  const w = d.window;
  const gap = w.covered_days < w.total_days
    ? `<div class="pre-note" data-warn>${w.month} 有 ${w.total_days} 天，
        而需求预估只到 ${w.forecast_to} —— 窗口里只有 <b>${w.covered_days}</b> 天有预估。</div>`
    : '';
  return sec(`预投圈的是哪一段${info(POP_CHART)}`,
    `<span class="pre-nature" data-nature="${d.forecast.source === 'agent' ? '混合' : '模拟'}">${
      d.forecast.source === 'agent' ? '混合' : '模拟'}</span>
     <button class="wb-export" type="button"
       data-export-child="${d.child_asin}">导出 Excel</button>`,
    `<div data-chart></div>
     <div class="pre-note">这就是库存单品盘点页那张逐日图 ——
       同一份 90 天预估，没有再跑一遍。蓝色框住的是这次预投要覆盖的销售月
       （${w.from} ~ ${w.to}），框内预估加起来 ${n0(d.forecast.p50)} 盒。<br>
       这批货最早 ${w.arrive_earliest} 到，所以 ${w.month} 上半月卖的还是现有库存。</div>
     ${gap}`);
}

/* ---- 为什么这么预估：Agent 的五项判断 --------------------------------- */

/* 状态词的语义色。词表来自 Agent 落库的 state，这里只决定用哪个色，
   不改词、不新造词 —— 落词表外的一律不上色。 */
const STATE_TONE = {
  衰退: 'missed', 爬坡: 'ramp', 平稳: 'ok',
  加大: 'ramp', 减少: 'missed',
  重度扭曲: 'missed', 轻度扭曲: 'promo', 无扭曲: 'ok',
  有活动仍在影响: 'promo', 有活动且已回落: 'ok', 无活动: 'ok',
  旺季: 'ramp', 淡季: 'missed', 不明显: 'ok',
  无投放: 'ok',
};

function judgeBlock(d) {
  const j = d.judgment;
  if (!j) {
    // 没跑过就整块不渲染内容，只留一句实话 + 一个入口，不摆空卡
    return sec('为什么这么预估',
      `<span class="pre-state" data-state="缺失">未判断</span>`,
      `<div class="pre-note">这个 ASIN 还没跑过需求预测 Agent，
        所以上面那段预估用的是数据包脚手架，没有判断依据可看。
        342 个子 ASIN 里目前只有 3 个跑过。
        <button class="wb-btn" type="button" data-open-task="1">打开任务面板</button></div>`);
  }
  return sec(`为什么这么预估${info(POP_JUDGE)}`,
    `<span class="pre-nature" data-nature="混合">混合</span>
     <span class="pre-runtag">${j.model_version || '—'} · ${j.run_date || ''}</span>`,
    `<div class="pre-summary2">${j.judgment_summary || ''}</div>
     <div class="pre-factors">
       ${(j.factors || []).map(factorCard).join('')}
     </div>
     ${j.confidence ? `<div class="pre-conf">
       <span class="k">确定程度</span>
       <span class="v">${j.confidence}</span>
       <span class="r">${j.confidence_reason || ''}</span>
     </div>` : ''}`);
}

function factorCard(f) {
  const tone = STATE_TONE[String(f.state || '').trim()] || '';
  const pct = (f.impact_pct === null || f.impact_pct === undefined || f.impact_pct === '')
    ? null : Number(f.impact_pct);
  return `<div class="pre-factor">
    <div class="hd">
      <span class="lb">${f.factor_label}</span>
      <span class="st"${tone ? ` data-tone="${tone}"` : ''}>${f.state || '—'}</span>
      <span class="ad">${pct === null ? '' : (pct > 0 ? '+' : '') + pc(pct)}</span>
    </div>
    <div class="bd">${f.because || '—'}</div>
  </div>`;
}

/* ---- 这个 ASIN 过去投了多少（逐尺码真实历史）-------------------------- */

function historyBlock(d) {
  const rows = d.month_history || [];
  const g = d.group_last_cycle;
  if (!rows.length && !g) return '';
  const max = Math.max(...rows.map((r) => r.units || 0), 1);
  return sec(`这个 ASIN 过去投了多少${info(POP_HIST)}`,
    `<span class="pre-nature" data-nature="真实">真实</span>`,
    (rows.length ? `<table class="pre-t"><thead><tr>
        <th>月份</th><th>类型</th><th class="num">投了</th><th class="bar"></th>
      </tr></thead><tbody>
      ${rows.map((r) => `<tr>
        <td>${r.month}</td>
        <td>${r.kind}</td>
        <td class="num">${n0(r.units)}</td>
        <td class="bar"><span class="pre-bar"><span class="fill" style="width:${
          ((r.units || 0) / max * 100).toFixed(1)}%"></span></span></td>
      </tr>`).join('')}
      </tbody></table>` : '<div class="pre-note">这个 ASIN 在库存表里没有历史预投记录。</div>')
    + (g ? `<div class="pre-note">所属配色组 ${d.identity.style_no}·${d.identity.combination}
        上一轮（${g.period_label}）：首次预投 ${n0(g.preinvest_first)} 盒${
        g.added ? `、追加 ${n0(g.added)} 盒` : ''}，实际下单 ${n0(g.order)} 盒，
        达成率 <b>${pc(g.achieve_rate)}</b>（考核线 ${pc(d.achieve_rate_min)}，
        ${g.passed ? '达标' : '未达标'}）。考核是按配色组算的，所以这一行是组级数字。</div>` : ''));
}

/* ---- 交互 ------------------------------------------------------------- */

function wire(root, d, buf, ctx) {
  /* 导出按钮。走 <a download> 而不是 fetch+blob：文件名由后端的
     Content-Disposition 决定，浏览器原生下载就用它，不必在前端重拼一遍。
     这与库存「销量与需求」那个导出按钮是同一条路。 */
  const ex = root.querySelector('[data-export-child]');
  if (ex) {
    ex.addEventListener('click', () => {
      const prev = ex.textContent;
      ex.textContent = '导出中…';
      ex.disabled = true;
      const link = document.createElement('a');
      link.href = `/api/preinvest/export-child/${encodeURIComponent(d.child_asin)}`;
      link.rel = 'noopener';
      document.body.appendChild(link);
      link.click();
      link.remove();
      // 下载由浏览器接手，页面拿不到完成事件，按时间恢复按钮
      setTimeout(() => { ex.textContent = prev; ex.disabled = false; }, 1200);
    });
  }

  const inp = root.querySelector('[data-cid]');
  if (!inp) return;
  const pack = d.identity.pack_size;
  const a = d.forecast.p50 === null || d.forecast.p50 === undefined
    ? null : Math.round(d.forecast.p50 * (1 + buf));
  const commit = () => {
    const raw = inp.value.trim();
    saveOverride(d.child_asin, raw === '' ? null : raw);
    const has = raw !== '';
    const final = has ? Number(raw) : a;
    const dl = root.querySelector('[data-delta]');
    if (dl) dl.textContent = (has && a !== null)
      ? sgn(final - a) + ' 盒 · 已手工调整' : '留空就按建议走';
    const tn = root.querySelector('[data-tons]');
    if (tn) tn.innerHTML = `${n2(tons(final))} <span class="u">吨</span>`;
    const tj = root.querySelector('[data-tiao]');
    if (tj && pack) tj.textContent = n0((final || 0) * pack) + ' 条';
  };
  inp.addEventListener('change', commit);
  inp.addEventListener('blur', commit);
}

/* ---- ⓘ 说明 ---------------------------------------------------------- */

const POP_CHART = `<b>这张图是什么</b><br>
**就是库存单品盘点页那张逐日图本身**，不是另画的一张 ——
同一份 90 天预估、同一套缺货带与活动泳道、同一套叠加指标。
这一页只多做一件事：把预投要覆盖的销售月用蓝框圈出来。<br><br>
<b>为什么共用一张</b><br>
预估销量本来就是库存那条链的产出（需求预测 Agent）。在预投这边再跑一遍预估、
再画一张图，两边就会开始漂移。所以图提升成了共享组件，数据取库存的对外接口。<br><br>
<b>为什么圈这个月</b><br>
8 月做的预投对应 10 月的销量（M+2），这是客户表里的既有口径。
框内预估加起来就是这次预投的基数，乘 Buffer 得到建议投放量。<br><br>
<b>右上角那个性质标</b><br>
写「混合」= 这个对象的预估经过需求预测 Agent 判断；
写「模拟」= 还没跑过，用的是数据包脚手架。`;

const POP_JUDGE = `<b>这些字是谁写的</b><br>
全部来自需求预测 Agent 落库的判断，这一页只是把它读出来渲染，一个字都没改写。<br><br>
<b>五项因子各是什么</b><br>
生命周期（这个产品是新品还是在衰退）、广告投放（后面有什么投放规划）、
站内活动（之前做过什么、未来排了什么）、缺货扭曲（历史销量有没有被断货压低）、
季节性（跟去年同期比）。每项给一个状态、一个影响幅度、一句带真实数字的依据。<br><br>
<b>为什么这一页没有「该不该改」那种对照卡</b><br>
去年同期、上一轮、未来活动这些，五项因子里本来就讲了。再单独摆一遍是重复。`;

const POP_HIST = `<b>这张表是什么</b><br>
客户库存表里这个 ASIN 逐月的实际预投与补投额 —— 逐尺码的真实历史。<br><br>
<b>为什么下面那行是配色组级的</b><br>
70% 那个达成率考核是按配色组算的（月报表就是按配色组汇总的），
所以达成率只能给到组这一层，不能拆到单个尺码。`;
