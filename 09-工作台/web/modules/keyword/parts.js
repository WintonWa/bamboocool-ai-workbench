/* 关键词模块 · 承载体组件库
 *
 * 设计见 07-关键词分析模块/01-方案与数据需求/09-页面承载体设计.md。
 *
 * 这个文件的存在理由是一条设计决定：**Agent 的文字必须落进固定槽位**。
 * 重构前每条证据在正文里铺四行自由长度的文字（类型行 / conclusion /
 * main_basis / 库存约束），子体盘点页一次铺 36 条 = 144 行，其中 13 条同一类、
 * 文案只差一个关键词名。那不是「字多」，是**没有承载形式**：
 * Agent 写多少字页面就长多少。
 *
 * 所以这里每个组件都自带空间预算，超了降级而不是换行：
 *   - 结论句一律单行（写不下说明结论没提炼够，不给它换行的权利）
 *   - main_basis 一个字都不上正文，只进 ⓘ 浮层
 *   - 同类证据不逐条平铺，收成「组头 + 行」
 *
 * 所有取色、字号都走 tokens.css 的变量（G3 / G20 / G21）；这里出现的裸 hex
 * 只在 SVG 里，且逐个对应一个既有 token —— canvas / SVG 属性吃不进 CSS 变量，
 * 竞品模块的 sparkSVG 同一处理，两边一致。
 */

/* SVG 里能用的颜色。值必须与 tokens.css 逐字一致，改那边要一起改。 */
const C = {
  ink: "#111113",
  fg3: "#6b6b73",
  good: "#3a7d43",
  warn: "#a8620d",
  alert: "#c9372c",
  calm: "#6b4fa8",
  accent: "#2563eb",
  mute: "#9ca3af",
};

export { C as SVG_COLORS };

/* ============================================================ 板块外壳 */

/* 板块 → 背后的 Agent。只有真由 Agent 判断的板块标，其余是工作台算术。
   全标了徽标就没有区分意义，而区分正是它存在的理由（G26 与注册表交叉核对）。 */
export const KW_AGENT = {
  "关键词机会、缺口与风险": "关键词机会与风险",
  "关键词缺口、机会与风险": "关键词机会与风险",
  "关键词与产品关系": "子体关键词布局",
};

/* 导出走 <a download>：文件名由后端 Content-Disposition 决定，前端不重拼。 */
function downloadExport(btn, url) {
  const prev = btn.textContent;
  btn.textContent = "导出中…";
  btn.disabled = true;
  const a = document.createElement("a");
  a.href = url;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
  // 下载由浏览器接手，页面拿不到完成事件，所以按时间恢复。
  setTimeout(() => { btn.textContent = prev; btn.disabled = false; }, 1200);
}

/* 板块。骨架是固定的：标题行 → 指标条 → 图 → extra → 表 → after。
   `note` 只收「口径」这一类必须常驻的短句；长说明走 `info`，进浮层。

   参数 chart 与 table 分开收而不是塞进 children，是为了让「每个板块必须有一张图」
   这条能被机械检查到 —— 缺图时这里能报，塞进 children 就查不出来。

   extra 在表**前**，after 在表**后**。两个槽都要，因为顺序是语义：
   构成条这类概览属于表前，「这个词还没有形成证据」这类结论属于表后 ——
   把结论放到明细表前面，读的人会以为它是对上面那句话的补充（踩过一次）。 */
export function section(ctx, {
  title, metrics: figs, note, info, chart, table: tbl, extra, after, exportUrl,
} = {}) {
  const el = ctx.el;
  const agent = KW_AGENT[title];
  const mark = agent ? ctx.aiMark(agent) : null;
  const head = [
    el("div", { class: "kw-sec-title" }, [
      el("span", { text: title }),
      mark,
      mark ? ctx.schemePicker(agent) : null,
      info ? infoDot(ctx, info) : null,
      exportUrl
        ? el("button", {
          class: "wb-export", type: "button",
          title: "导出成 Excel（.xlsx），可直接给其他部门下单用",
          onclick: (e) => downloadExport(e.currentTarget, exportUrl),
          text: "导出 Excel",
        })
        : null,
    ]),
  ];
  const m = metricRow(ctx, figs);
  if (m) head.push(m);
  if (note) head.push(el("div", { class: "kw-sec-note", text: note }));
  return el("section", { class: "kw-sec" }, [
    el("div", { class: "kw-sec-head" }, head),
    chart ? el("div", { class: "kw-figure" }, [chart]) : null,
    extra || null,
    tbl ? el("div", { class: "kw-table-wrap" }, [tbl]) : null,
    after || null,
  ]);
}

/* 指标条：标签 + 值两段式，最多五格。
   空值直接不出，不留空槽 —— 留空槽会让人以为数据坏了。 */
export function metricRow(ctx, items, max = 5) {
  const el = ctx.el;
  const cells = (items || [])
    .filter((x) => x && x[1] !== null && x[1] !== undefined && x[1] !== "")
    .slice(0, max)
    .map(([lab, v, kind]) => el("span", { class: "kw-m" + (kind ? ` kw-m-${kind}` : "") }, [
      el("em", { text: lab }),
      el("b", { text: String(v) }),
    ]));
  return cells.length ? el("div", { class: "kw-metrics" }, cells) : null;
}

/* ⓘ。点开才出的口径与算法说明。板块上不留说明文字行 —— 那是产品规则，
   不是排版偏好。库存页同一处理。contentFn 延迟到点击才建节点。 */
export function infoDot(ctx, contentFn) {
  const el = ctx.el;
  const dot = el("i", {
    class: "kw-info", title: "口径与算法", text: "i", role: "button", tabindex: "0",
  });
  const open = () => {
    const body = typeof contentFn === "function" ? contentFn() : contentFn;
    ctx.pop.show(dot, typeof body === "string"
      ? el("div", { class: "kw-popbody" }, [el("p", { text: body })])
      : body);
  };
  dot.addEventListener("click", (e) => { e.stopPropagation(); open(); });
  dot.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); }
  });
  return dot;
}

/* 浮层正文的标准形状：标题 + 若干「名称 / 值」行 + 若干整段。
   Agent 的 conclusion 与 main_basis 就落在 paras 里 —— 这是它们唯一的上屏位置。 */
export function popBody(ctx, { title, rows, paras } = {}) {
  const el = ctx.el;
  return el("div", { class: "kw-popbody" }, [
    title ? el("b", { text: title }) : null,
    (rows || []).length
      ? el("dl", {}, (rows || []).flatMap(([k, v]) => (
        v === null || v === undefined || v === "" ? []
          : [el("dt", { text: k }), el("dd", { text: String(v) })]
      )))
      : null,
    ...(paras || []).filter(Boolean).map((p) => el("p", { text: p })),
  ]);
}

/* 折叠区：追溯段用。默认收起，不占阅读流。 */
export function foldBlock(ctx, { title, meta, children } = {}) {
  const el = ctx.el;
  return el("details", { class: "kw-fold" }, [
    el("summary", {}, [
      el("span", { text: title }),
      meta ? el("i", { text: meta }) : null,
    ]),
    el("div", { class: "kw-foldbody" }, [].concat(children || [])),
  ]);
}

/* ====================================================== 结论区（②段） */

/* 结论行。固定四槽：状态点 + 名称 + 状态词 + 一句话（单行）+ ⓘ。
   形状照搬库存页 verdictBand —— 那个形状已经验证过，不另发明第二套。 */
export function verdictRow(ctx, { tone, name, state, say, detail } = {}) {
  const el = ctx.el;
  return el("div", { class: "kw-vd-row", "data-tone": tone || "" }, [
    el("i", { class: "kw-vd-dot" }),
    el("span", { class: "kw-vd-name", text: name }),
    state ? el("span", { class: "kw-vd-state", text: state }) : null,
    el("span", { class: "kw-vd-say", text: say || "" }),
    detail ? infoDot(ctx, detail) : null,
  ]);
}

/* ====================================================== 概览卡（②段） */

/* 概览卡。**标签在上、值在下，永远不出现没有标签的裸数字。**
 *
 * 第一版把主数字直接摆在页面左上角、下面挂一句散文当说明，右侧另起构成条，
 * 再往下第三条基线放四个支撑格 —— 三块拼在一起，而且读的人先看到「1,991」
 * 才知道它是什么。王楠的原话是「有一个不明不白的数字」。
 *
 * 改成一张有边框的卡：若干列，竖发丝线分隔，每列同一套语法
 *   标签（--fs-meta 灰） → 值（--fs-num 单数字 / --fs-value 文字型） → 副行（--fs-meta 灰）
 * 列里可以不放数字而放任意内容（构成条、迷你图、缩略图、标签组），
 * 但**标签那一行必须有**，这是这个组件唯一的硬约束。
 *
 * 分隔线用 `gap:1px` + 卡片底色，不用 border-left：列在窄屏换行时
 * border-left 会在每一行的首列留一道竖线，gap 方案换行也不会错。
 */
export function overviewCard(ctx, { cells } = {}) {
  const el = ctx.el;
  const list = (cells || []).filter(Boolean);
  if (!list.length) return null;
  /* 轨数显式给死，不靠 auto-fit 算。auto-fit 会在某些宽度下把最后一格挤到第二行，
     变成一个孤格加一大片空白（第一版的「判断来源」就这样掉下去了）。
     首列占两轨（它的副行最长），所以轨数 = 格数 + 1。 */
  const tracks = Math.min(8, list.length + (list.some((c) => c.lead) ? 1 : 0));
  return el("div", { class: "kw-card", "data-cols": String(tracks) },
    list.map((c) => cardCell(ctx, c)));
}

/* 卡内构成图例。**只给色点，不画条** —— 参考实现里同位置就是一排色点，
   而条 + 图例两样都放会把这一列撑到别的列的两倍高（第一版折了三行）。
   条留给板块正文里的 stackBar，那里有横向空间。 */
export function dotLegend(ctx, items) {
  const el = ctx.el;
  const rows = (items || []).filter((x) => x && x.n > 0);
  if (!rows.length) return null;
  return el("div", { class: "kw-dots" }, rows.map((x) =>
    el("span", { class: `kw-lg kw-seg-${x.kind || "calm"}` }, [
      el("i", {}), el("span", { text: x.label }), el("b", { text: ctx.fmt.int(x.n) }),
    ])));
}

/* 一列。value 与 body 二选一：value 走数字排版，body 装任意节点。
   media 给的是缩略图那一类，图与「值＋副行」并排（参考图里的「已选子 ASIN」格）。 */
export function cardCell(ctx, {
  label, value, text, sub, tone, subTone, body, lead, media, action,
} = {}) {
  const el = ctx.el;
  const zero = value === 0 || value === null || value === undefined;
  const valueNode = body ? null : el("div", {
    class: "kw-cell-value" + (text ? " kw-cell-value-text" : "")
      + (tone ? ` kw-cell-${tone}` : "") + (zero && text == null ? " kw-cell-zero" : ""),
    text: text != null ? text : (zero ? "本期无" : ctx.fmt.int(value)),
  });
  /* 涨跌染在**副行**而不是主值上：主值是「有多少」，那本身不是好或坏；
     方向才有好坏。参考实现里主数字是墨色，只有下面那行涨幅是绿的。 */
  const subNode = sub ? el("div", {
    class: "kw-cell-sub" + (subTone ? ` kw-cell-${subTone}` : ""), text: sub,
  }) : null;
  const stack = media
    ? el("div", { class: "kw-cell-media" }, [
      media,
      el("div", { class: "kw-cell-mediatext" }, [valueNode, subNode]),
    ])
    : null;
  return el("div", { class: "kw-cell" + (lead ? " kw-cell-lead" : "") }, [
    el("div", { class: "kw-cell-head" }, [
      el("span", { class: "kw-cell-label", text: label }),
      action || null,
    ]),
    stack || valueNode,
    body || null,
    stack ? null : subNode,
  ]);
}

/* 结论区。概览卡 + 结论行块。
   结论行块单独包一层边框，读起来是一个单元而不是散落在页面上的五行。 */
export function conclusionBand(ctx, { cells, verdicts } = {}) {
  const el = ctx.el;
  const rows = (verdicts || []).filter(Boolean);
  return el("section", { class: "kw-sec kw-hero" }, [
    overviewCard(ctx, { cells }),
    rows.length ? el("div", { class: "kw-verdicts" }, rows.slice(0, 5)) : null,
  ]);
}

/* 支撑格。留给不在卡里的场合（折叠区内的小指标）。
   0 是真实信号，但裸的粗体 0 读起来像板块坏了 —— 降调并写「本期无」。 */
export function statCell(ctx, { label, value, text, sub, kind } = {}) {
  const el = ctx.el;
  const zero = text == null && (value === 0 || value === null || value === undefined);
  return el("div", {
    class: "kw-stat" + (zero ? " kw-stat-zero" : "") + (kind ? ` kw-stat-${kind}` : ""),
  }, [
    el("span", { text: label }),
    el("b", { class: text ? "kw-stat-text" : null,
      text: text != null ? text : (zero ? "本期无" : ctx.fmt.int(value)) }),
    sub ? el("i", { text: sub }) : null,
  ]);
}

/* ======================================================== 证据组（③段） */

/* 证据组。**同类不再逐条平铺。**
 *
 * 一类 = 一个组头（类型 + 条数 + 证据完整度构成）+ N 行。
 * 每行五槽定宽：判据图形 / 对象 / 量 / 状态标签 / ⓘ。
 *
 * conclusion 与 main_basis **不出现在行上**，只在 ⓘ 里。
 * 理由：同一类 13 条的 conclusion 只差一个关键词名，逐条铺开等于让人读
 * 13 遍同一句话；而 main_basis 是 conclusion 的数字版重述，两行并排是重复。
 * 类型标签本身已经表达了「这是哪一类判断」，行要回答的是「哪个对象、多重、下一步」。
 *
 * spec.graphic(item) 出 S1，spec.amount(item) 出 S3 —— 同一个承载体在总览页
 * 与子体页装不同内容：总览页按需求规模排序所以 S1 画搜索量量级，
 * 子体页在讲位置所以 S1 画位次区间。槽位不变，装的东西按页面职责换。
 */
const GROUP_EXPAND = 4;

export function evidenceGroups(ctx, { items, spec, onOpen } = {}) {
  const el = ctx.el;
  const byType = new Map();
  for (const e of items || []) {
    const k = e.evidence_type_label || "未分类";
    if (!byType.has(k)) byType.set(k, []);
    byType.get(k).push(e);
  }
  const wrap = el("div", { class: "kw-evgroups" }, [...byType].map(([type, list]) => {
    const shown = list.slice(0, GROUP_EXPAND);
    const rest = list.slice(GROUP_EXPAND);
    const hidden = rest.length
      ? el("div", { class: "kw-evrows", hidden: "" },
        rest.map((e) => evidenceRow(ctx, e, spec)))
      : null;
    return el("div", { class: "kw-evgroup", "data-kind": toneOfType(type) }, [
      el("div", { class: "kw-evgroup-head" }, [
        el("span", { class: "kw-tag", text: type }),
        el("span", { class: "kw-evgroup-n", text: `${list.length} 条` }),
        completenessBar(ctx, list),
      ]),
      el("div", { class: "kw-evrows" }, shown.map((e) => evidenceRow(ctx, e, spec))),
      hidden,
      rest.length ? foldToggle(ctx, hidden, type, rest.length) : null,
    ]);
  }));
  if (onOpen) {
    wrap.addEventListener("click", (ev) => {
      const row = ev.target.closest("[data-open]");
      if (row) onOpen(row.getAttribute("data-open"));
    });
  }
  return wrap;
}

function foldToggle(ctx, list, type, n) {
  const el = ctx.el;
  const btn = el("button", {
    class: "kw-fold-btn", type: "button", text: `另有 ${n} 条${type}，展开`,
  });
  btn.addEventListener("click", () => {
    const open = !list.hasAttribute("hidden");
    if (open) { list.setAttribute("hidden", ""); btn.textContent = `另有 ${n} 条${type}，展开`; }
    else { list.removeAttribute("hidden"); btn.textContent = `收起这 ${n} 条`; }
  });
  return btn;
}

/* 证据类型 → 语气。判据只看类型名里的字，不读码值（G9）。 */
export function toneOfType(name) {
  const s = String(name || "");
  if (/风险/.test(s)) return "alert";
  if (/机会/.test(s)) return "good";
  if (/不足|待/.test(s)) return "mute";
  return "calm";
}

/* 组头的证据完整度构成条。回答「这一组有多少可信」——
   一组里多数是「证据不足」时，这组的条数本身就不该被当成结论。 */
function completenessBar(ctx, list) {
  const el = ctx.el;
  const order = ["证据完整", "证据部分可用", "证据不足"];
  const kind = { 证据完整: "good", 证据部分可用: "warn", 证据不足: "mute" };
  const n = {};
  for (const e of list) {
    const k = e.evidence_completeness_label || "证据不足";
    n[k] = (n[k] || 0) + 1;
  }
  const segs = order.filter((k) => n[k]);
  if (segs.length < 2) return null;
  const total = list.length;
  return el("span", { class: "kw-evgroup-comp", title: segs.map((k) => `${k} ${n[k]}`).join("　") },
    segs.map((k) => el("i", {
      class: `kw-seg-${kind[k]}`, style: `width:${(n[k] / total) * 100}%`,
    })));
}

/* 证据行。五槽，缺项留空不塌陷 —— 塌陷会让同组的行左右错位，扫不成一列。 */
export function evidenceRow(ctx, e, spec = {}) {
  const el = ctx.el;
  const graphic = spec.graphic ? spec.graphic(e) : null;
  const amount = spec.amount ? spec.amount(e) : null;
  const objectId = spec.objectId ? spec.objectId(e) : null;
  return el("div", {
    class: "kw-evrow", "data-open": objectId || null,
  }, [
    el("span", { class: "kw-evrow-fig" }, [graphic || el("i", { class: "kw-na-fig" })]),
    el("span", { class: "kw-evrow-obj" }, [
      el("b", { text: e.keyword || "—" }),
      spec.subject ? el("i", { text: spec.subject(e) }) : null,
    ]),
    el("span", { class: "kw-evrow-amt" }, [amount || el("i", { text: ctx.fmt.dash })]),
    el("span", { class: "kw-evrow-tags" }, [
      e.next_verification_label
        ? el("span", { class: "kw-minitag", text: e.next_verification_label }) : null,
      e.inventory_limit_label
        ? el("span", { class: "kw-minitag kw-minitag-warn", text: e.inventory_limit_label })
        : null,
      e.push_role_label === "主推"
        ? el("span", { class: "kw-minitag kw-minitag-push", text: "主推" }) : null,
    ]),
    infoDot(ctx, () => popBody(ctx, {
      title: `${e.evidence_type_label || "判断"} · ${e.keyword || ""}`,
      rows: [
        ["对象", e.child_asin],
        ["证据完整度", e.evidence_completeness_label],
        ["下一步", e.next_verification_label],
        ["竞品核对", e.competitor_verification_label],
        ["当前目标", e.product_goal_label],
        ["主推关系", e.push_role_label],
        ["库存约束", e.inventory_limit_label],
        ["月搜索量", e.monthly_search_volume == null
          ? null : ctx.fmt.int(e.monthly_search_volume)],
        ["观测日", e.ref_position_date],
      ],
      // Agent 的两句话就落在这里，这是它们唯一的上屏位置。
      paras: [e.conclusion, e.main_basis],
    })),
  ]);
}

/* ============================================================== 图形件 */

/* 位次区间游标。位次是反向量（第 1 位最好），轨道左端是 1，游标越靠左越好。
   最好到最差的跨度就是波动幅度 —— 三个并排的数字读不出这件事。 */
export function rangeTrack(ctx, { best, cur, worst, cap, title } = {}) {
  const el = ctx.el;
  if (best == null || worst == null) return null;
  const hi = Math.max(cap || 1, worst, 1);
  const pos = (v) => Math.max(0, Math.min(100, ((v - 1) / hi) * 100));
  const span = Math.max(1.5, pos(worst) - pos(best));
  return el("span", {
    class: "kw-range",
    title: title || `最好第 ${best} 位 · 最差第 ${worst} 位`
      + (cur == null ? "" : ` · 当前第 ${cur} 位`),
  }, [
    el("i", { class: "kw-range-span", style: `left:${pos(best)}%;width:${span}%` }),
    cur == null ? null : el("i", { class: "kw-range-dot", style: `left:${pos(cur)}%` }),
  ]);
}

/* 位次变化。从 → 到 画成一段有方向的轨：起点空心、终点实心，
   段长 = 变动名次。位次数字变大是变差，所以变差的段染 alert。 */
export function shiftTrack(ctx, { from, to, cap } = {}) {
  const el = ctx.el;
  if (from == null || to == null) return null;
  const hi = Math.max(cap || 1, from, to, 1);
  const pos = (v) => Math.max(0, Math.min(100, ((v - 1) / hi) * 100));
  const a = pos(Math.min(from, to));
  const b = pos(Math.max(from, to));
  const worse = to > from;
  return el("span", {
    class: "kw-shift" + (worse ? " kw-shift-worse" : " kw-shift-better"),
    title: `第 ${from} 位 → 第 ${to} 位`,
  }, [
    el("i", { class: "kw-shift-span", style: `left:${a}%;width:${Math.max(1.5, b - a)}%` }),
    el("i", { class: "kw-shift-from", style: `left:${pos(from)}%` }),
    el("i", { class: "kw-shift-to", style: `left:${pos(to)}%` }),
  ]);
}

/* 量级格：条在数字后、整列右对齐。条是给「谁最大」用的，数字是给读值用的。 */
export function magnitudeCell(ctx, { value, ratio, kind, digits } = {}) {
  const el = ctx.el;
  return el("td", { class: "kw-magcell", "data-sort": value == null ? -1 : value }, [
    el("span", { class: "kw-magnum", text: digits != null
      ? ctx.fmt.num(value, digits) : ctx.fmt.int(value) }),
    el("span", { class: `kw-bar kw-bar-${kind || "vol"}` }, [
      el("i", { style: `width:${Math.max(2, Math.min(100, (ratio || 0) * 100))}%` }),
    ]),
  ]);
}

/* 色阶格：数值自己带背景浓度，一列扫下来深浅就是排序，不用逐行读百分数。
   契约禁止模块定义新色值，所以不用 color-mix，改嵌套 <i> 调 opacity。 */
export function heatCell(ctx, { text, ratio, kind, sort } = {}) {
  const el = ctx.el;
  const r = Math.max(0, Math.min(1, ratio || 0));
  return el("td", { class: "kw-num kw-heat", "data-sort": sort != null ? sort : r }, [
    el("i", { class: `kw-heat-bg kw-seg-${kind || "vol"}`, style: `opacity:${(r * 0.5).toFixed(3)}` }),
    el("span", { text: text }),
  ]);
}

/* 堆叠比例条。构成比例是数字列表读不出来的东西 ——
   六个数看得出大小，看不出谁占几成。零值段不渲染（0 宽会留一条缝）。 */
export function stackBar(ctx, segments, { label } = {}) {
  const el = ctx.el;
  const rows = (segments || []).filter((s) => s && s.n > 0);
  if (!rows.length) return null;
  const total = rows.reduce((a, s) => a + s.n, 0);
  return el("div", { class: "kw-stackwrap" }, [
    label ? el("div", { class: "kw-stacklab", text: label }) : null,
    el("div", { class: "kw-stack" }, rows.map((s) => el("i", {
      class: `kw-stack-seg kw-seg-${s.kind || "calm"}`,
      style: `width:${(s.n / total) * 100}%`,
      title: `${s.label}　${ctx.fmt.int(s.n)}　${ctx.fmt.pct(s.n / total, 0)}`,
    }))),
    el("div", { class: "kw-stacklegend" }, rows.map((s) =>
      el("span", { class: `kw-lg kw-seg-${s.kind || "calm"}` }, [
        el("i", {}), el("span", { text: s.label }), el("b", { text: ctx.fmt.int(s.n) }),
      ]))),
  ]);
}

/* 迷你折线。SVG 走 html 字符串而不是 createElementNS —— 后者在这套代码里
   踩过一次（命名空间属性设不上，图静默不画）。竞品模块同一处理。

   极差不到中位数 2% 时按水平线画：把这点噪声铺开成波形，读起来像有波动其实没有，
   和一排等高柱是同一个错。 */
export function sparkLine(vals, { invert = false, color, width = 68, height = 20 } = {}) {
  const v = (vals || []).filter((x) => x !== null && x !== undefined);
  if (v.length < 3) return "";
  const w = width, h = height, pad = 2;
  const min = Math.min(...v), max = Math.max(...v);
  const mid = Math.abs(v[v.length - 1]) || 1;
  const flat = (max - min) / mid < 0.02;
  const span = (max - min) || 1;
  const y = (x) => {
    const t = flat ? 0.5 : (x - min) / span;
    return pad + (flat ? t : (invert ? t : 1 - t)) * (h - pad * 2);
  };
  const pts = v.map((x, i) =>
    `${(pad + i * (w - pad * 2) / (v.length - 1)).toFixed(1)},${y(x).toFixed(1)}`).join(" ");
  const last = v[v.length - 1], first = v[0];
  const better = invert ? last < first : last > first;
  const stroke = flat ? C.mute : (color || C.ink);
  return `<svg viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" aria-hidden="true">
    <polyline points="${pts}" fill="none" stroke="${stroke}" stroke-width="1.3"
      vector-effect="non-scaling-stroke"/>
    ${flat ? "" : `<circle cx="${(w - pad).toFixed(1)}" cy="${y(last).toFixed(1)}" r="1.8"
      fill="${better ? C.good : C.alert}"/>`}
  </svg>`;
}

/* 方向格：净变化这类有正负的量。方向由符号和颜色一起给，不只靠颜色。 */
export function deltaCell(ctx, { value, zeroText = "持平", suffix = "" } = {}) {
  const el = ctx.el;
  if (value == null) return el("td", { class: "kw-num", text: ctx.fmt.dash });
  const v = Number(value);
  const tone = v > 0 ? "good" : v < 0 ? "alert" : "zero";
  return el("td", { class: `kw-num kw-delta kw-delta-${tone}`, "data-sort": v }, [
    el("span", { text: v === 0 ? zeroText : `${v > 0 ? "▲" : "▼"}${Math.abs(v)}${suffix}` }),
  ]);
}

/* ================================================================ 表 */

/* 表。`cols` 逐列声明职责，渲染与排序都从它来 ——
   设计里那条「一列只承担一种职责、纯数字列不超过 6」要能被查，
   就不能让每张表各写一套 <td>。 */
export function table(ctx, { cols, rows: data, sortable: sortCols, onRowOpen, empty } = {}) {
  const el = ctx.el;
  if (!(data || []).length) {
    return el("div", { class: "kw-empty", text: empty || "本期无数据" });
  }
  const head = el("tr", {}, cols.map((c) => el("th", {
    class: c.num ? "kw-num" : null, text: c.label,
  })));
  const body = (data || []).map((r) => {
    const tr = el("tr", {
      class: r.__tone ? `kw-row kw-row-${r.__tone}` : "kw-row",
      "data-open": r.__open || null,
    }, cols.map((c) => c.cell(r)));
    return tr;
  });
  const t = el("table", { class: "kw-table" }, [
    el("thead", {}, [head]),
    el("tbody", {}, body),
  ]);
  if (onRowOpen) {
    t.addEventListener("click", (ev) => {
      const tr = ev.target.closest("tr[data-open]");
      if (tr) onRowOpen(tr.getAttribute("data-open"));
    });
  }
  if (sortCols && sortCols.length) makeSortable(t, sortCols);
  return t;
}

/* 数值列点表头排序。取值从 data-sort 读，没有就退回 textContent 去掉千分位。 */
function makeSortable(tableEl, numCols) {
  const ths = tableEl.querySelectorAll("thead th");
  const state = { col: -1, dir: -1 };
  numCols.forEach((ci) => {
    const th = ths[ci];
    if (!th) return;
    th.classList.add("kw-th-sort");
    th.addEventListener("click", () => {
      state.dir = state.col === ci ? -state.dir : -1;
      state.col = ci;
      ths.forEach((t) => t.removeAttribute("data-dir"));
      th.setAttribute("data-dir", state.dir < 0 ? "desc" : "asc");
      const tb = tableEl.querySelector("tbody");
      const val = (tr) => {
        const td = tr.children[ci];
        if (!td) return -Infinity;
        if (td.dataset.sort !== undefined) return Number(td.dataset.sort);
        const n = parseFloat(String(td.textContent).replace(/[,%\s第位天]/g, ""));
        return Number.isNaN(n) ? -Infinity : n;
      };
      Array.from(tb.children)
        .sort((a, b) => (val(a) - val(b)) * state.dir)
        .forEach((tr) => tb.appendChild(tr));
    });
  });
}

/* 文字格 / 数字格 —— 两个最常用的列定义，省得每张表重写。 */
export const txt = (ctx, get, cls) => (r) =>
  ctx.el("td", { class: cls || null, text: get(r) ?? ctx.fmt.dash });
export const num = (ctx, get, fmtFn) => (r) => {
  const v = get(r);
  return ctx.el("td", {
    class: "kw-num", "data-sort": v == null ? -Infinity : v,
    text: v == null ? ctx.fmt.dash : (fmtFn ? fmtFn(v) : ctx.fmt.int(v)),
  });
};

/* 小标签 / 芯片 —— 身份类短值。 */
export function chip(ctx, label, value) {
  return ctx.el("span", { class: "kw-chip" }, [
    ctx.el("span", { text: label ? label + " " : "" }),
    ctx.el("b", { text: String(value) }),
  ]);
}

/* ==================================================== 判断来源条（①段） */

/* 读 `agent_result`（modules/keyword/agent_result.py 的选库结果），六个路由都带。
   三态与 condition 一一对应：

     缺失 → 没有已发布的 Agent 结果，判断层内容是构造脚手架
     过期 → Agent 发布时的参数与当前请求不一致
     正常 → 正在用 Agent 那一份，run_id 就是这次的身份

   必须上屏的理由见《07-Agent运行与落库口径.md》§七：上游没跑过时下游必须降级说明，
   不能悄悄回落到预烤值。缺失态尤其要说，否则页面上那些结论看起来像是 Agent 判的。

   重构里它从「一个占三行的板块」压成一行 —— 它是前提不是内容。 */
/* 判断来源。**作为概览卡的一列**返回配置，不再单独占一条横带。

   第一版是页面最上面一条 border-left 加圆角的独立条，渲染出来左端是个橙色圆括号，
   而且它比页面自己的结论还显眼 —— 它是前提不是内容。
   收成卡里一列之后语法和别的列一样（标签在上、值在下），也不再抢视线。 */
export function sourceCell(ctx, d) {
  const a = d && d.agent_result;
  if (!a) return null;
  const cond = a.condition || "缺失";
  return {
    label: "判断来源",
    text: cond === "正常" ? "Agent 产出" : "构造脚手架",
    tone: cond === "正常" ? "good" : "warn",
    sub: cond === "正常" ? (a.run_id ? `run ${a.run_id}` : "本次运行")
      : cond === "过期" ? "已发布结果与当前参数不一致" : "关键词 Agent 尚未接入",
    action: infoDot(ctx, () => popBody(ctx, {
      title: "这一屏的判断从哪来",
      rows: [
        ["状态", cond],
        ["已发布的 run", a.run_id],
        ["当前采用", cond === "正常" ? "Agent 产出" : "构造脚本产出"],
      ],
      paras: [
        a.message,
        cond === "正常" ? null
          : "构造脚手架是为了让页面在 Agent 跑通前也能演示形状。它不是业务事实，"
            + "所以这一列必须留着 —— 去掉之后页面上的结论会看起来像 Agent 判的。",
      ],
    })),
  };
}

