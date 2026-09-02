/* 运营总览 · 前端模块
 *
 * 四个板块，回答的经营问题分别是（契约 G10 要逐板块说得出来）：
 *   1 今天该看什么   —— 现在最该动手的是哪几件事
 *   2 模块结论卡     —— 每个模块当前的一句话判断，以及从哪儿进去看细节
 *   3 构成图         —— 那些数字是怎么摊在对象上的（哪一类占了大头）
 *   4 齐备度与口径   —— 这一屏的话立在什么数据上，以及现在还缺哪些结论
 *
 * 结论句子由后端 module.py 的 COPY 组装（人写的示例文案 + 真数字填槽），
 * 这里只渲染，不在前端拼任何句子、不硬编码任何中文风险名或类型名 ——
 * 那些词全部由各模块自己的接口给，经 /api/overview/digest 透传过来。
 *
 * $ / el / fmt / cond / 浮层 / 占位全部从 ctx 取，本文件不自己实现。
 */

export const id = 'overview';
export const apiVersion = 1;
export const usesRail = false;          // 总览没有对象清单，让正文占满整宽

/* 单页模块：路径里不带页面段也不带对象段。 */
export function parsePath() {
  return { pageId: 'home', objectId: null };
}

export function pathFor() {
  return '';
}

/* ---------------------------------------------------------------- 状态 --- */

let host = null;
let lastCtx = null;      // unmount 时要用它关掉可能还开着的浮层

/* ---------------------------------------------------------- 生命周期 --- */

export async function mount(slots, ctx) {
  host = slots;
  await render(ctx);
}

export function unmount() {
  // 卸载时浮层可能还开着，且它挂在文档顶层不随本模块容器清空 —— 显式关掉。
  if (lastCtx) lastCtx.pop.close();
  lastCtx = null;
  host = null;
}

export async function render(ctx) {
  if (!host) return;
  lastCtx = ctx;
  host.body.textContent = '';

  let d = null;
  try {
    d = await ctx.api('digest');
  } catch (err) {
    host.body.appendChild(ctx.placeholder('总览取数失败', String(err.message || err), 'error'));
    return;
  }

  const lines = (d.headline && d.headline.lines) || [];
  const cards = d.cards || [];
  const anyValue = cards.some((c) => c.value !== null && c.value !== undefined);

  // 四个模块全没给出可读结果时（都没加载、或都降级）走外壳的空态，
  // 不渲染一屏空壳子 —— 空的头条面板加四张空卡片比一句「还没有内容」更难懂。
  if (!lines.length && !anyValue) {
    host.body.appendChild(
      ctx.placeholder('总览还没有可汇总的结论', '四个模块当前都没有返回可读的判断结果', 'empty')
    );
    return;
  }

  const wrap = ctx.el('div', { class: 'ovw' });
  if (lines.length) wrap.appendChild(renderHeadline(ctx, d));
  wrap.appendChild(renderCards(ctx, d));
  for (const chart of d.charts || []) wrap.appendChild(renderChart(ctx, chart));
  wrap.appendChild(renderCoverage(ctx, d));
  host.body.appendChild(wrap);
}

/* -------------------------------------------------------------- 通用 --- */

/* 状态徽标：非正常态用外壳的 .wb-cond（全站一个样子），
   正常态外壳刻意返回 null（避免满屏「正常」），这里补一个安静的自有 chip ——
   总览上「这个模块的数据是好的」和「没去读它」必须能分开。 */
function condChip(ctx, v, tone) {
  /* 状态词的色调由后端一处映射给（module.py 的 COND_TONE），前端不自己判词。
     外壳的 ctx.cond 负责非正常态的形状，这里只补 data-tone —— 本模块的 CSS
     作用域只在 [data-module="overview"] 内，不会改到别的页面上的同类徽标。 */
  const node = ctx.cond(v) || ctx.el('span', { class: 'ovw-chip-ok', text: v || '' });
  if (tone) node.setAttribute('data-tone', tone);
  return node;
}

/* ⓘ 标记。方法与口径说明收进点开的浮层，不写成正文一行字。
 *
 * 浮层内容自己带一个 data-module="overview" 的包裹节点 —— 外壳的 #wb-pop
 * 挂在文档顶层，在本模块作用域之外，不带这个节点样式一条都不生效。
 * 注意包裹节点**自己**就是那个 [data-module] 元素，所以内部样式只能挂在
 * 它的子节点类名上：写 `[data-module="overview"] .ovw-pop b` 选不中任何东西
 * （那要求 .ovw-pop 是某个 data-module 元素的后代，而它就是那个元素本身）。
 * 第一版栽在这里，标题字号被外壳的 .wb-pop 盖成 12px 而看不出哪儿错。
 */
function info(ctx, title, paras) {
  const btn = ctx.el('button', {
    class: 'ovw-i',
    type: 'button',
    'aria-label': '说明：' + title,
    text: 'ⓘ',
  });
  btn.addEventListener('click', (e) => {
    e.preventDefault();
    const body = ctx.el('div', { class: 'ovw-pop' }, [
      ctx.el('span', { class: 'ovw-pop-t', text: title }),
      ...[].concat(paras).map((p) => ctx.el('p', { class: 'ovw-pop-p', text: p })),
    ]);
    body.dataset.module = 'overview';
    ctx.pop.show(btn, body);
  });
  return btn;
}

function sectionHead(ctx, title, tail) {
  const h = ctx.el('div', { class: 'ovw-sec-head' }, [ctx.el('span', { class: 'ovw-sec-title', text: title })]);
  for (const t of [].concat(tail || [])) if (t) h.appendChild(t);
  return h;
}

/* 跳到另一个模块。ctx 没有跨模块导航的方法（它只管本模块的对象与页面），
   所以点的是外壳导航里那一格。按 ctx.allModules 的下标定位 ——
   外壳的 renderNav 就是按这个顺序渲染的；再用标签文字复核一次，
   对不上就不拦截，交给 <a href> 走整页跳转（深链本来就可直接访问）。 */
function jump(ctx, moduleId) {
  const mods = ctx.allModules || [];
  const i = mods.findIndex((m) => m.id === moduleId);
  if (i < 0) return false;
  const tabs = document.querySelectorAll('#wb-tabs .wb-tab');
  const btn = tabs[i];
  if (!btn || btn.textContent.trim() !== String(mods[i].label || '').trim()) return false;
  btn.click();
  return true;
}

function moduleLink(ctx, moduleId, route, text) {
  const a = ctx.el('a', { class: 'ovw-go', href: route, text });
  a.addEventListener('click', (e) => {
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;   // 让新窗口照常打开
    if (jump(ctx, moduleId)) e.preventDefault();
  });
  return a;
}

/* --------------------------------------------------- 1 今天该看什么 --- */

function renderHeadline(ctx, d) {
  const sec = ctx.el('section', { class: 'ovw-sec ovw-lede' });

  const why = [
    '库存的风险判断、关键词的优先级事项、竞品的分析结论、广告的异常与证据链，' +
      '各自由那个模块用它自己的口径和门槛算出来，总览只做摘取与排版，不算第二遍。',
    '句子本身是人写的示例文案，句里每个数字都是从上面那些接口取的；' +
      '取不到的整句不显示。',
  ];

  sec.appendChild(
    sectionHead(ctx, '今天该看什么', [
      ctx.el('span', { class: 'ovw-src', text: d.source_label || '' }),
      info(ctx, '这一屏读的是四个模块自己已经产出的结论', why),
    ])
  );

  const list = ctx.el('div', { class: 'ovw-lede-list' });
  (d.headline.lines || []).forEach((ln, i) => {
    const row = ctx.el('div', { class: 'ovw-lede-row' });
    row.appendChild(ctx.el('span', { class: 'ovw-lede-no', text: String(i + 1) }));
    row.appendChild(ledeText(ctx, ln));
    row.appendChild(moduleLink(ctx, ln.module, '/' + ln.module, ln.module_label + ' →'));
    list.appendChild(row);
  });
  sec.appendChild(list);
  return sec;
}

/* 结论句。后端按真实槽位把句子拆成「文字 / 数字」两种段落，这里只负责
   把数字挑出来加重、把「—— 」之后那半句（要人动手的部分）单独标出来。
   拆分在后端做的原因：只有它知道哪个数字是填进去的 ——
   「同时压着三项以上」的「三」是模板里本来就有的字，不该被强调。

   拿不到 parts 就退回整句纯文本，不为了样式丢内容。 */
function ledeText(ctx, ln) {
  const p = ctx.el('p', { class: 'ovw-lede-text' });
  const parts = ln.parts || [];
  if (!parts.length) {
    p.textContent = ln.text || '';
    return p;
  }
  for (const seg of parts) {
    if (seg.sep) {
      p.appendChild(ctx.el('span', { class: 'ovw-lede-sep', text: String(seg.v) }));
      continue;
    }
    const cls = [
      seg.t === 'n' ? 'ovw-lede-n' : 'ovw-lede-s',
      seg.punch ? 'ovw-lede-punch' : null,
    ].filter(Boolean).join(' ');
    p.appendChild(
      ctx.el(seg.t === 'n' ? 'b' : 'span', {
        class: cls,
        text: seg.t === 'n' ? ctx.fmt.int(seg.v) : String(seg.v),
      })
    );
  }
  return p;
}

/* ------------------------------------------------- 2 模块结论卡 --- */

function renderCards(ctx, d) {
  const sec = ctx.el('section', { class: 'ovw-sec' });
  sec.appendChild(sectionHead(ctx, '四个模块当前的判断'));

  const grid = ctx.el('div', { class: 'ovw-cards' });
  for (const c of d.cards || []) {
    const card = ctx.el('div', { class: 'ovw-card' });

    const head = ctx.el('div', { class: 'ovw-card-head' }, [
      ctx.el('span', { class: 'ovw-card-name', text: c.label }),
    ]);
    head.appendChild(condChip(ctx, c.condition, c.tone));
    card.appendChild(head);

    const val = ctx.el('div', { class: 'ovw-card-val' });
    val.appendChild(ctx.el('b', { text: c.value === null || c.value === undefined ? ctx.fmt.dash : ctx.fmt.int(c.value) }));
    if (c.value_suffix) val.appendChild(ctx.el('span', { class: 'ovw-card-den', text: c.value_suffix }));
    card.appendChild(val);
    card.appendChild(ctx.el('div', { class: 'ovw-card-vlabel', text: c.value_label || '' }));

    if (c.line) card.appendChild(ctx.el('p', { class: 'ovw-card-line', text: c.line }));

    /* 分类徽标。中性色（pale）排到最后 —— 它是「这一周期不用动」的那一类，
       排在前面会把要处理的量挤到看不见的位置。 */
    if ((c.chips || []).length) {
      const chips = ctx.el('div', { class: 'ovw-chips' });
      const order = { alert: 0, warn: 1, calm: 2, good: 3, pale: 4 };
      for (const ch of [...c.chips].sort((a, b) => (order[a.tone] ?? 9) - (order[b.tone] ?? 9))) {
        chips.appendChild(
          ctx.el('span', { class: 'ovw-chip', 'data-tone': ch.tone || 'mid' }, [
            ctx.el('span', { text: ch.label }),
            ctx.el('b', { text: ch.n == null ? ctx.fmt.dash : ctx.fmt.int(ch.n) }),
          ])
        );
      }
      card.appendChild(chips);
    }

    if (c.quote) {
      const q = ctx.el('div', { class: 'ovw-quote' }, [ctx.el('span', { class: 'ovw-quote-text', text: c.quote })]);
      if (c.quote_from) q.appendChild(ctx.el('span', { class: 'ovw-quote-from', text: c.quote_from }));
      card.appendChild(q);
    }

    if ((c.detail || []).length) {
      const kv = ctx.el('div', { class: 'ovw-kv' });
      for (const it of c.detail) {
        kv.appendChild(ctx.el('span', { class: 'ovw-kv-k', text: it.k }));
        const v = ctx.el('span', { class: 'ovw-kv-v' });
        if (it.n === null || it.n === undefined) {
          v.textContent = it.v || ctx.fmt.dash;
        } else {
          v.textContent = ctx.fmt.int(it.n) + (it.unit || '');
        }
        kv.appendChild(v);
      }
      card.appendChild(kv);
    }

    card.appendChild(moduleLink(ctx, c.module, c.route, '打开' + c.label + ' →'));
    grid.appendChild(card);
  }
  sec.appendChild(grid);
  return sec;
}

/* ----------------------------------------------------- 3 构成图 --- */

/* 横向构成。总览层面没有可比的历史序列，所以只画「摊在对象上的构成」，
   不画趋势线。每一行都自带中文名、绝对数和占比，不靠颜色说话 ——
   深浅只在顶部那条分段带里有含义，含义写在它的图例上。 */
function renderChart(ctx, chart) {
  const sec = ctx.el('section', { class: 'ovw-sec' });
  sec.appendChild(sectionHead(ctx, chart.title, chart.note ? info(ctx, '口径', chart.note) : null));

  const total = Number(chart.total) || 0;
  const share = (n) => (total > 0 ? Number(n) / total : null);
  const unit = chart.unit ? ' ' + chart.unit : '';

  if (chart.strip && (chart.strip.segments || []).length) {
    const strip = ctx.el('div', { class: 'ovw-strip' });
    for (const s of chart.strip.segments) {
      const w = share(s.n);
      strip.appendChild(
        ctx.el('span', {
          class: 'ovw-strip-seg',
          'data-tone': s.tone || 'mid',
          style: 'flex: 0 0 ' + (w === null ? 0 : (w * 100).toFixed(3)) + '%',
          title: s.label + ' ' + ctx.fmt.int(s.n) + unit,
        })
      );
    }
    sec.appendChild(strip);

    const legend = ctx.el('div', { class: 'ovw-legend' });
    for (const s of chart.strip.segments) {
      legend.appendChild(
        ctx.el('span', { class: 'ovw-legend-it' }, [
          ctx.el('i', { class: 'ovw-dot', 'data-tone': s.tone || 'mid' }),
          ctx.el('span', { text: s.label }),
          ctx.el('b', { text: ctx.fmt.int(s.n) + unit }),
          ctx.el('span', { class: 'ovw-legend-pct', text: share(s.n) === null ? ctx.fmt.dash : ctx.fmt.pct(share(s.n)) }),
        ])
      );
    }
    sec.appendChild(legend);
  }

  const max = Math.max(...(chart.rows || []).map((r) => Number(r.n) || 0), 0);
  const hasQty = (chart.rows || []).some((r) => r.qty != null);
  const bars = ctx.el('div', { class: 'ovw-bars', 'data-cols': hasQty ? '5' : '4' });
  for (const r of chart.rows || []) {
    const w = max > 0 ? (Number(r.n) / max) * 100 : 0;
    bars.appendChild(ctx.el('span', { class: 'ovw-bar-k', text: r.label }));

    /* 一条 = 该类的子体数；条内分段 = 库存模块判的严重度。
       没有 parts 的行（无风险、关键词那张图）仍是整条，不硬造分段。 */
    const parts = (r.parts || []).filter((p) => Number(p.n) > 0);
    const fill = ctx.el('span', {
      class: 'ovw-bar-fill',
      'data-rest': r.rest ? '1' : null,
      'data-split': parts.length ? '1' : null,
      style: 'width: ' + w.toFixed(3) + '%',
    });
    for (const p of parts) {
      const inner = Number(r.n) > 0 ? (Number(p.n) / Number(r.n)) * 100 : 0;
      fill.appendChild(
        ctx.el('i', {
          class: 'ovw-bar-part',
          'data-tone': p.tone || 'mid',
          style: 'flex: 0 0 ' + inner.toFixed(3) + '%',
          title: r.label + ' · 严重度' + p.label + ' ' + ctx.fmt.int(p.n) + unit,
        })
      );
    }
    bars.appendChild(ctx.el('span', { class: 'ovw-bar-track' }, [fill]));
    bars.appendChild(ctx.el('span', { class: 'ovw-bar-n', text: ctx.fmt.int(r.n) + unit }));
    bars.appendChild(
      ctx.el('span', { class: 'ovw-bar-pct', text: share(r.n) === null ? ctx.fmt.dash : ctx.fmt.pct(share(r.n)) })
    );
    if (hasQty) {
      bars.appendChild(
        ctx.el('span', {
          class: 'ovw-bar-qty',
          text: r.qty == null ? ctx.fmt.dash : ctx.fmt.int(r.qty) + ' 件',
        })
      );
    }
  }
  sec.appendChild(bars);

  /* 分段的含义必须写出来。不写清楚，这几段颜色会被当成总览自己的分级。 */
  if (chart.parts_legend && (chart.rows || []).some((r) => (r.parts || []).length)) {
    const seen = new Map();
    for (const r of chart.rows || []) {
      for (const p of r.parts || []) if (!seen.has(p.label)) seen.set(p.label, p.tone);
    }
    const note = ctx.el('div', { class: 'ovw-legend ovw-legend-sub' }, [
      ctx.el('span', { class: 'ovw-legend-cap', text: chart.parts_legend }),
    ]);
    for (const [label, tone] of seen) {
      note.appendChild(
        ctx.el('span', { class: 'ovw-legend-it' }, [
          ctx.el('i', { class: 'ovw-dot', 'data-tone': tone || 'mid' }),
          ctx.el('span', { text: label }),
        ])
      );
    }
    if (hasQty) note.appendChild(ctx.el('span', { class: 'ovw-legend-cap', text: '末列是影响件数' }));
    sec.appendChild(note);
  }

  /* 三个此前没上屏的分布：严重度 / 承接能力 / 预测置信度。 */
  const dists = (chart.dists || []).filter((g) => (g.items || []).some((x) => x.n != null));
  if (dists.length) {
    const wrap = ctx.el('div', { class: 'ovw-dists' });
    for (const g of dists) {
      const col = ctx.el('div', { class: 'ovw-dist' }, [
        ctx.el('div', { class: 'ovw-dist-t', text: g.title }),
      ]);
      for (const it of g.items || []) {
        col.appendChild(
          ctx.el('div', { class: 'ovw-dist-r' }, [
            ctx.el('i', { class: 'ovw-dot', 'data-tone': it.tone || 'mid' }),
            ctx.el('span', { class: 'ovw-dist-k', text: it.label }),
            ctx.el('b', { class: 'ovw-dist-n', text: it.n == null ? ctx.fmt.dash : ctx.fmt.int(it.n) }),
          ])
        );
      }
      wrap.appendChild(col);
    }
    sec.appendChild(wrap);
  }

  return sec;
}

/* --------------------------------------------- 4 齐备度与口径 --- */

function renderCoverage(ctx, d) {
  const cov = d.coverage || {};
  const sec = ctx.el('section', { class: 'ovw-sec' });
  sec.appendChild(
    sectionHead(ctx, '这一屏立在什么数据上', [
      cov.as_of ? ctx.el('span', { class: 'ovw-src', text: cov.as_of }) : null,
    ])
  );

  const tbl = ctx.el('div', { class: 'ovw-tbl' });
  for (const h of ['模块', '数据版本', '历史窗口', '状态']) {
    tbl.appendChild(ctx.el('span', { class: 'ovw-th', text: h }));
  }
  for (const m of cov.modules || []) {
    tbl.appendChild(ctx.el('span', { class: 'ovw-td', text: m.label }));
    tbl.appendChild(ctx.el('span', { class: 'ovw-td ovw-td-n', text: m.dataset_version }));
    tbl.appendChild(ctx.el('span', { class: 'ovw-td ovw-td-n', text: m.window }));
    const cell = ctx.el('span', { class: 'ovw-td' });
    cell.appendChild(condChip(ctx, m.condition, m.tone));
    tbl.appendChild(cell);
  }
  sec.appendChild(tbl);

  if ((cov.gaps || []).length) {
    sec.appendChild(ctx.el('div', { class: 'ovw-sub', text: '现在还缺的结论' }));
    const gaps = ctx.el('div', { class: 'ovw-gaps' });
    for (const g of cov.gaps) {
      gaps.appendChild(ctx.el('span', { class: 'ovw-gap-k', text: g.label }));
      const c = ctx.el('span', { class: 'ovw-gap-c' });
      c.appendChild(condChip(ctx, g.condition, g.tone));
      gaps.appendChild(c);
      gaps.appendChild(ctx.el('span', { class: 'ovw-gap-v', text: g.note || '' }));
    }
    sec.appendChild(gaps);
  }
  return sec;
}
