/* 广告分析模块 · 页面二的图形原语
 *
 * 设计见 04-广告分析模块/01-方案与数据需求/07-页面二屏幕决策设计.md。
 *
 * 三条纪律：
 *   1. **一律返回 HTML 字符串**，由调用方用 el('div',{html}) 落地。
 *      外壳的 el() 走 document.createElement，建不出 SVG 命名空间的节点，
 *      所以 SVG 只能走 innerHTML —— 竞品模块的 sparkline 也是这么做的。
 *   2. **SVG 里的文字不写字号**，一律挂 class 由 ads.css 给（门禁 G23：
 *      JS 里出现 font-size 就红。内联字号在 CSS 层扫不到，是真该禁）。
 *   3. **不判断**。tone 只由调用方按明确口径传进来；这里不认识"好"和"坏"。
 *      唯一的例外是排名斜线，"名次变小=向上"是排名这个量的定义，不是业务判断。
 */

const DASH = "—";

/* 所有进 innerHTML 的文本都过这道。数据全部来自本机只读库，
   但转义是廉价的，而漏一处就是把库里的字符当标记执行。 */
export function esc(v) {
  if (v === null || v === undefined) return "";
  return String(v).replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch]));
}

const n0 = (v) => (v === null || v === undefined || Number.isNaN(v)) ? DASH
  : Number(v).toLocaleString("zh-CN", { maximumFractionDigits: 0 });
const n1 = (v) => (v === null || v === undefined || Number.isNaN(v)) ? DASH
  : Number(v).toLocaleString("zh-CN", { minimumFractionDigits: 1,
                                        maximumFractionDigits: 1 });
const pc1 = (v) => (v === null || v === undefined || Number.isNaN(v)) ? DASH
  : (Number(v) * 100).toFixed(1) + "%";

export const fmtNum = n0;
export const fmtOne = n1;
export const fmtPct = pc1;

export function fmtUsd(v, dp = 0) {
  if (v === null || v === undefined || Number.isNaN(v)) return DASH;
  return "$" + Number(v).toLocaleString("zh-CN",
    { minimumFractionDigits: dp, maximumFractionDigits: dp });
}

/* 按 kind 格式化。kind 由后端 REVIEW_METRICS 给，两边用同一套名字。 */
export function fmtKind(v, kind) {
  if (v === null || v === undefined || Number.isNaN(v)) return DASH;
  if (kind === "pct") return pc1(v);
  if (kind === "usd") return fmtUsd(v, 0);
  if (kind === "usd2") return fmtUsd(v, 2);
  if (kind === "x") return Number(v).toFixed(2);
  return n0(v);
}

/* 带符号的百分比。0 与 null 必须看得出区别：null 是取不到，0 是没变。 */
export function signPct(v, dp = 1) {
  if (v === null || v === undefined || Number.isNaN(v)) return DASH;
  const p = Number(v) * 100;
  return (p > 0 ? "+" : "") + p.toFixed(dp) + "%";
}

/* ------------------------------------------------------------ 一、横条行 */

/** 「名称 + 条 + 数值」若干行。页面里最常用的那种图。
 *  rows: [{ label, sub, share(0..1), text, tone, badge }]
 *  share 为 null 时不画条 —— 不要拿 0 顶替，0 是"量是零"，null 是"没这个数"。 */
export function barRows(rows, opts = {}) {
  const cls = opts.dense ? " ads-brs-dense" : "";
  const body = (rows || []).map((r) => {
    const w = r.share === null || r.share === undefined
      ? null : Math.max(0, Math.min(1, Number(r.share))) * 100;
    return `<div class="ads-br">
      <span class="ads-br-l">${esc(r.label)}${
        r.sub ? `<em>${esc(r.sub)}</em>` : ""}</span>
      <span class="ads-br-t">${w === null
        ? `<span class="ads-br-na">${DASH}</span>`
        : `<span class="ads-br-f${r.tone ? " ads-t-" + r.tone : ""}"
             style="width:${w.toFixed(2)}%"></span>`}</span>
      <span class="ads-br-v num">${esc(r.text)}</span>
      ${r.badge ? `<span class="ads-br-b">${esc(r.badge)}</span>` : ""}
    </div>`;
  }).join("");
  return `<div class="ads-brs${cls}">${body}</div>`;
}

/* -------------------------------------------------------- 二、自然位斜线 */

/** 自然排名的走势。**名次越小越好，所以轴是反的**：prev=7 → now=9
 *  必须画成向下。这是排名这个量的定义，不是业务判断。
 *  没有名次记录时返回一个明确的"未进榜"标记，不画一条平线冒充有位置。 */
export function rankSlope(prev, now) {
  const W = 46, H = 26, PAD = 5;
  const has = (v) => v !== null && v !== undefined && !Number.isNaN(v);
  if (!has(prev) && !has(now)) {
    return `<span class="ads-rk ads-rk-none">未进榜</span>`;
  }
  if (!has(prev) || !has(now)) {
    const only = has(now) ? now : prev;
    return `<span class="ads-rk ads-rk-one num">${esc(only)}</span>`;
  }
  const a = Number(prev), b = Number(now);
  const lo = Math.min(a, b), hi = Math.max(a, b);
  const span = Math.max(hi - lo, 1);
  // y 反向：名次小 → 画在上面
  const y = (v) => PAD + ((v - lo) / span) * (H - PAD * 2);
  const tone = b < a ? "good" : b > a ? "warn" : "";
  const arrow = b < a ? "↑" : b > a ? "↓" : "→";
  return `<span class="ads-rkwrap">
    <svg class="ads-rksvg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}"
         aria-hidden="true">
      <line class="ads-rkline${tone ? " ads-t-" + tone : ""}"
            x1="${PAD}" y1="${y(a).toFixed(1)}"
            x2="${W - PAD}" y2="${y(b).toFixed(1)}"/>
      <circle class="ads-rkdot ads-rkdot-a" cx="${PAD}"
              cy="${y(a).toFixed(1)}" r="2.4"/>
      <circle class="ads-rkdot${tone ? " ads-t-" + tone : ""}"
              cx="${W - PAD}" cy="${y(b).toFixed(1)}" r="3.1"/>
    </svg>
    <span class="ads-rktxt num">${esc(a)}<i>→</i>${esc(b)}</span>
    <span class="ads-rkar${tone ? " ads-t-" + tone : ""}">${arrow}</span>
  </span>`;
}

/* ------------------------------------------------------------ 三、量的链 */

/** 曝光 → 点击 → 订单，转折处放转化率。
 *  为什么不画漏斗：实测 14 天共享桶里订单 6373 > 点击 3932，
 *  漏斗画出来会变成倒锥，看的人只会以为图画错了。链式把两个比率
 *  显式摆在中间，比率不成立时由调用方传 warn 标出来。 */
export function chain(steps) {
  const cells = [];
  (steps || []).forEach((s, i) => {
    if (i) {
      cells.push(`<span class="ads-cn-r${s.gapTone ? " ads-t-" + s.gapTone : ""}">
        <em>${esc(s.gapLabel || "")}</em>
        <b class="num">${esc(s.gapText || DASH)}</b></span>`);
    }
    cells.push(`<span class="ads-cn-s">
      <b class="num">${esc(s.text)}</b>
      <em>${esc(s.label)}</em></span>`);
  });
  return `<div class="ads-cn">${cells.join("")}</div>`;
}

/* -------------------------------------------------------- 四、归因稀释条 */

/** 这个广告对象同时推 N 个子 ASIN，本品只是其中一个。
 *  N=75 时那条实心几乎看不见 —— 这正是要让人看见的东西。
 *  给最小宽度 0.8% 是为了别完全消失（消失了会像渲染失败）。 */
export function dilution(n, opts = {}) {
  const cnt = Math.max(1, Number(n) || 1);
  const w = Math.max(0.8, 100 / cnt);
  const tone = cnt > 1 ? "warn" : "good";
  return `<div class="ads-dil">
    <span class="ads-dil-t"><span class="ads-dil-f ads-t-${tone}"
      style="width:${w.toFixed(2)}%"></span></span>
    <span class="ads-dil-x">${cnt > 1
      ? `本品是这个对象推广的 <b class="num">${cnt}</b> 个子 ASIN 之一`
      : "本品独占这个对象"}${opts.note ? "，" + esc(opts.note) : ""}</span>
  </div>`;
}

/* ------------------------------------------------------------ 五、时间轴 */

/** 日期标记轴。points: [{date, label, tone, shape}]
 *  轴范围由传入日期决定，越界的（如已经过去的最晚下单日）照样画在左端，
 *  并由调用方给 alert —— 把它藏起来才是错的。 */
export function timeline(points, opts = {}) {
  const pts = (points || []).filter((p) => p && p.date);
  if (!pts.length) return "";
  const t = (d) => new Date(d + "T00:00:00").getTime();
  const xs = pts.map((p) => t(p.date));
  const lo = Math.min(...xs), hi = Math.max(...xs);
  const span = hi - lo || 1;
  const W = 100;                                   // 百分比坐标
  const marks = pts.map((p) => {
    const x = ((t(p.date) - lo) / span) * (W - 8) + 4;
    return `<span class="ads-tl-m${p.tone ? " ads-t-" + p.tone : ""}"
      style="left:${x.toFixed(2)}%">
      <i class="ads-tl-dot${p.shape === "hollow" ? " ads-tl-hollow" : ""}"></i>
      <b class="ads-tl-lb">${esc(p.label)}</b>
      <em class="ads-tl-dt num">${esc(p.date)}</em></span>`;
  }).join("");
  return `<div class="ads-tl">
    <span class="ads-tl-axis"></span>${marks}
  </div>${opts.note ? `<div class="ads-tl-note">${esc(opts.note)}</div>` : ""}`;
}

/* ---------------------------------------------------- 六、双向变化对比条 */

/** 效果复盘：基准值 → 观察值。
 *  条从中线向两侧长，长度 = |相对变化| 截到 100%。
 *  tone 由后端按逐指标的 better 方向给，**这里不判断方向** ——
 *  花费涨了是 neutral，给它标红就是替运营做了一个它没做的判断。 */
export function deltaRows(metrics) {
  const body = (metrics || []).map((m) => {
    const ch = m.change;
    const has = ch !== null && ch !== undefined && !Number.isNaN(ch);
    const mag = has ? Math.min(Math.abs(Number(ch)), 1) * 50 : 0;
    const pos = has && Number(ch) > 0;
    return `<div class="ads-dr">
      <span class="ads-dr-l">${esc(m.label)}${
        m.better === "neutral" ? "" :
        `<em>${m.better === "down" ? "越低越好" : "越高越好"}</em>`}</span>
      <span class="ads-dr-b num">${esc(fmtKind(m.baseline, m.kind))}</span>
      <span class="ads-dr-t">
        <span class="ads-dr-mid"></span>
        ${has ? `<span class="ads-dr-f${m.tone ? " ads-t-" + m.tone : ""}"
          style="${pos ? "left:50%" : `right:50%`};width:${mag.toFixed(2)}%"
          ></span>` : ""}
      </span>
      <span class="ads-dr-o num">${esc(fmtKind(m.observed, m.kind))}</span>
      <span class="ads-dr-c num${m.tone ? " ads-t-" + m.tone : ""}">${
        esc(signPct(ch))}${m.points !== null && m.points !== undefined
          ? `<em>${(m.points > 0 ? "+" : "")
            + Number(m.points).toFixed(1)} 个点</em>` : ""}</span>
    </div>`;
  }).join("");
  return `<div class="ads-drs">
    <div class="ads-dr ads-dr-head">
      <span class="ads-dr-l">指标</span><span class="ads-dr-b">动作前</span>
      <span class="ads-dr-t">变化</span><span class="ads-dr-o">观察窗</span>
      <span class="ads-dr-c">幅度</span>
    </div>${body}</div>`;
}

/* -------------------------------------------------------- 七、压力矩阵 */

/** 品牌 × 压力类型。**列固定**：没命中的类型列照样在，
 *  否则看的人分不清"这一类没有压力"和"这一类没查"。 */
export function matrix(cols, rows) {
  const head = `<div class="ads-mx-r ads-mx-head">
    <span class="ads-mx-c ads-mx-name">竞品品牌</span>
    ${(cols || []).map((c) => `<span class="ads-mx-c">${esc(c.label)}</span>`)
      .join("")}</div>`;
  const body = (rows || []).map((r) => `<div class="ads-mx-r">
    <span class="ads-mx-c ads-mx-name">
      <b>${esc(r.brand)}</b><em class="num">${esc((r.asins || []).join(" "))}</em>
    </span>
    ${(cols || []).map((c) => {
      const hit = (r.cells || {})[c.key] || [];
      if (!hit.length) return `<span class="ads-mx-c ads-mx-off">·</span>`;
      const ok = hit.every((h) => h.verified);
      return `<span class="ads-mx-c ads-mx-on${ok ? " ads-mx-ok" : ""}"
        title="${esc(hit.map((h) => h.label).join("；"))}">
        ${ok ? "●" : "○"}</span>`;
    }).join("")}</div>`).join("");
  return `<div class="ads-mx">${head}${body}
    <div class="ads-mx-lg"><span>● 已核实</span><span>○ 未核实</span>
      <span>· 本期未发现这一类压力</span></div></div>`;
}

/* ------------------------------------------------------ 八、覆盖核对网格 */

/** 十类问题查过几类、命中几类。「查过没发现」也是结论，所以全列。 */
export function coverageGrid(items) {
  const body = (items || []).map((x) => `<span
    class="ads-cg-i${x.hit ? " ads-cg-hit" : ""}"
    title="${esc(x.hit ? "本次命中" : (x.why_not || "本次未命中"))}">
    <i>${x.hit ? "▲" : "·"}</i>${esc(x.problem_label || x.problem_type)}</span>`)
    .join("");
  return `<div class="ads-cg">${body}</div>`;
}
