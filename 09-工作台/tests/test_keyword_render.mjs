/* 渲染态禁词扫描：跑真实的 keyword.js 渲染函数 + 真实 API 数据，
   把渲染出来的全部文本拼起来扫内部枚举码（契约 G9 / G17）。

   为什么不扫 API 载荷就够：中间还隔着一层 JS 拼字符串。载荷里
   evidence_completeness_label 是干净的中文，但页面代码要是写成
   `${e.evidence_completeness}` 少了 _label 后缀，载荷干净、页面照样脏。
   本地没有 playwright，所以用最小 DOM shim 跑真渲染代码 —— 缺的只有布局，
   而 innerText 扫描不需要布局。

   用法：先 start.py start，然后 node tests/test_keyword_render.mjs */

import { mount, unmount } from "../web/modules/keyword.js";

const BASE = "http://127.0.0.1:18820/api/keyword/";

/* 库里的内部叫法，一个都不许出现在渲染文本里。
   前六个来自契约 G9 的 LEAK_WORDS，后面是本模块自己的枚举与 v0.3.0 的风险码。 */
const LEAK = [
  "value_origin", "source_status", "source_ref", "provenance",
  "can_absorb", "cannot_absorb", "report_month_total",
  "complete", "partial", "missing",
  "direct", "derived", "constructed",
  "organic_only", "ad_only", "not_covered", "beyond_depth", "collect_failed",
  "not_monitored", "unconfirmed", "covered",
  "volume_push", "hold_position", "niche_explore", "brand_defend",
  "clear_stock", "maintain_base",
  "replenish_first", "normal_only", "can_absorb_extra",
  "replenishment_gap", "stockout", "overstock", "aged_inventory_risk", "healthy",
  "demand_up", "demand_down", "competition_up", "head_asin_replaced",
  "insufficient_history", "not_comparable", "single_period", "continuous",
  "market_opportunity", "coverage_gap", "core_position_risk",
  "scene_longtail_signal", "inventory_limited", "insufficient_data",
  "pending_competitor_verification",
  "organic_up", "organic_down", "organic_gained", "organic_lost",
  "ad_gained", "ad_lost", "top_of_search", "rest_of_search", "product_page",
  "weekly", "manual", "priority",
  "kw3", "kw2", "synthetic_demo", "customer_real",
];

/* 防御性表述：契约第 11 节文案类明令不上屏 */
const DEFENSIVE = [
  "不作为判断依据", "不代表客户经营事实", "阈值均待客户确认",
  "一次只能选一种粒度", "P1 阶段", "P2 实现", "仅供参考", "不构成建议",
];

/* ---- 最小 DOM shim ---------------------------------------------------- */
class Node2 {
  constructor(tag) {
    this.tag = tag;
    this.children = [];
    this.attrs = {};
    this._text = "";
    this.dataset = {};
    this._cls = new Set();
    this.parent = null;
  }
  /* className 走 Set：sortable() 用 classList.add 给表头加可排序标记 */
  set className(v) {
    this._cls = new Set(String(v || "").split(/\s+/).filter(Boolean));
  }
  get className() {
    return Array.from(this._cls).join(" ");
  }
  get classList() {
    const s = this._cls;
    return {
      add: (...c) => c.forEach((x) => s.add(x)),
      remove: (...c) => c.forEach((x) => s.delete(x)),
      contains: (c) => s.has(c),
      toggle: (c, on) => (on === undefined
        ? (s.has(c) ? s.delete(c) : s.add(c))
        : (on ? s.add(c) : s.delete(c))),
    };
  }
  set textContent(v) {
    this._text = v == null ? "" : String(v);
    this.children = [];
  }
  get textContent() {
    return this._text + this.children.map((c) => c.textContent).join("");
  }
  /* 重新 append 一个已有子节点必须先摘走：真浏览器的 appendChild 是移动语义。
     照抄成「只 push」的话，排序会把每一行复制一遍，文本扫描看到双份内容。 */
  appendChild(c) {
    if (!c) return c;
    if (c.parent) {
      const i = c.parent.children.indexOf(c);
      if (i >= 0) c.parent.children.splice(i, 1);
    }
    c.parent = this;
    this.children.push(c);
    return c;
  }
  replaceChildren(...cs) {
    this.children = cs.filter(Boolean);
    this.children.forEach((c) => { c.parent = this; });
    this._text = "";
  }
  setAttribute(k, v) {
    this.attrs[k] = String(v);
  }
  getAttribute(k) {
    return k in this.attrs ? this.attrs[k] : null;
  }
  hasAttribute(k) {
    return k in this.attrs;
  }
  removeAttribute(k) {
    delete this.attrs[k];
  }
  addEventListener(type, fn) {
    (this._on || (this._on = {}))[type] = fn;
  }
  /* 处理函数只有被真调用一次才算验过（给排序门禁用） */
  click() {
    if (this._on && this._on.click) this._on.click({ target: this });
  }
  closest() {
    return null;
  }
  _walk(out) {
    for (const c of this.children) { out.push(c); c._walk(out); }
    return out;
  }
  _match(sel) {
    return sel.startsWith(".") ? this._cls.has(sel.slice(1)) : this.tag === sel;
  }
  /* 只支持「标签/类名」和两段后代选择器 —— sortable 用的是 "thead th" 与 "tbody" */
  querySelectorAll(sel) {
    const parts = sel.trim().split(/\s+/);
    const all = this._walk([]);
    if (parts.length === 1) return all.filter((n) => n._match(parts[0]));
    return all.filter((n) => {
      if (!n._match(parts[parts.length - 1])) return false;
      let a = n.parent;
      while (a) { if (a._match(parts[0])) return true; a = a.parent; }
      return false;
    });
  }
  querySelector(sel) {
    return this.querySelectorAll(sel)[0] || null;
  }
  /* 只统计真正会被人看见的文本：hidden 的折叠区不算（它要点开才出现，
     但内容同样要干净，所以单独收集、单独扫） */
  visibleText() {
    if (this.hasAttribute("hidden")) return "";
    return this._text + this.children.map((c) => c.visibleText()).join("");
  }
  hiddenText() {
    if (this.hasAttribute("hidden")) return this.textContent;
    return this.children.map((c) => c.hiddenText()).join("");
  }
}

const el = (tag, attrs = {}, children = []) => {
  const n = new Node2(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") n.className = String(v);
    else if (k === "text") n._text = String(v);
    else if (k.startsWith("data-")) n.dataset[k.slice(5).replace(/-(\w)/g,
      (_, c) => c.toUpperCase())] = String(v);
    else n.setAttribute(k, v);
  }
  for (const c of [].concat(children)) if (c) n.appendChild(c);
  return n;
};

const DASH = "—";
const fmt = {
  int: (v) => (v == null || Number.isNaN(v) ? DASH : Math.round(v).toLocaleString("zh-CN")),
  num: (v, d = 1) => (v == null || Number.isNaN(v) ? DASH : Number(v).toFixed(d)),
  pct: (v, d = 1) => (v == null || Number.isNaN(v) ? DASH : `${(Number(v) * 100).toFixed(d)}%`),
  money: (v, d = 2) => (v == null ? DASH : `$${Number(v).toFixed(d)}`),
  days: (v, d = 1) => (v == null ? DASH : `${Number(v).toFixed(d)} 天`),
  date: (v) => v || DASH,
  dash: DASH,
};

function makeCtx(pageId, objectId) {
  return {
    moduleId: "keyword", el, fmt,
    pageId, objectId,
    nature: (v) => el("span", { text: v }),
    cond: (v) => el("span", { text: v }),
    placeholder: (t, d) => el("div", {}, [el("h2", { text: t }), el("p", { text: d })]),
    open() {},
    setShared() {},
    setFilters() {},
    drawer: { open() {}, close() {} },
    pop: { show() {}, close() {} },
    async api(resource) {
      const res = await fetch(BASE + resource);
      if (!res.ok) throw new Error(`接口返回 ${res.status}`);
      return res.json();
    },
  };
}

/* ---- 跑 ---------------------------------------------------------------- */
const SCREENS = [
  ["kw-overview", undefined, "页面一 总览"],
  ["kw-market", undefined, "页面二 词库列表"],
  ["kw-market", "kw_00001", "页面二 单词深研 mens underwear"],
  ["kw-child", undefined, "页面三 子体清单"],
  ["kw-child", "B0B3LWGP36", "页面三 盘点 B0B3LWGP36（66 对全锚点）"],
  ["kw-child", "B0CBPXNC1M", "页面三 盘点 B0CBPXNC1M（五态齐全）"],
];

let fail = 0;
const report = (name, pass, detail = "") => {
  if (!pass) fail += 1;
  console.log(`  [${pass ? "PASS" : "FAIL"}] ${name}${pass ? "" : "  (" + detail + ")"}`);
};

console.log("== 渲染态禁词扫描（真渲染代码 + 真 API 数据）==");
for (const [pageId, objectId, label] of SCREENS) {
  const body = new Node2("div");
  const rail = new Node2("div");
  let text = "";
  let hidden = "";
  try {
    await mount({ rail, body }, makeCtx(pageId, objectId));
    text = body.visibleText() + rail.visibleText();
    hidden = body.hiddenText() + rail.hiddenText();
  } catch (err) {
    report(`${label} 渲染不抛异常`, false, String(err.message || err));
    unmount();
    continue;
  }
  report(`${label} 渲染出内容（${text.length} 字）`, text.length > 200, text.length);

  const hits = LEAK.filter((w) => new RegExp(`\\b${w}\\b`, "i").test(text));
  report(`${label} 可见文本零枚举码`, hits.length === 0, hits.join(", "));

  const hHits = LEAK.filter((w) => new RegExp(`\\b${w}\\b`, "i").test(hidden));
  report(`${label} 折叠区文本零枚举码`, hHits.length === 0, hHits.join(", "));

  const dHits = DEFENSIVE.filter((w) => text.includes(w));
  report(`${label} 无防御性表述`, dHits.length === 0, dHits.join(", "));

  /* 这一轮改视觉时踩到的两类问题，逐个变成门禁 —— 都是渲染态才看得见、
     API 载荷检查抓不到的。 */

  // 1. 数组被当计数拼进文案。collect_fail_days 是日期数组，写 `${它} 天`
  //    会渲染成「2026-03-17,2026-05-06,2026-06-29 天」。逗号连着日期就是信号。
  const arrLeak = /\d{4}-\d{2}-\d{2},\d{4}-\d{2}-\d{2}/.test(text)
    || /\[object Object\]/.test(text) || /undefined|NaN/.test(text);
  report(`${label} 无数组/对象直接拼进文案`, !arrLeak,
    (text.match(/[^\s]{0,12}(?:\d{4}-\d{2}-\d{2},\d{4}-\d{2}-\d{2}|\[object Object\]|undefined|NaN)[^\s]{0,8}/) || [""])[0]);

  // 2. 图形元件塌成 0 尺寸。行内元素上的 width/height 会被忽略，
  //    柱子和堆叠段会全塌成 0×0 —— 门禁全绿也抓不到，只能扫内联样式。
  const sized = [];
  const walk = (n) => {
    const st = n.attrs && n.attrs.style;
    if (st && /(width|height)\s*:/.test(st)) sized.push(st);
    n.children.forEach(walk);
  };
  walk(body);
  const zeroSized = sized.filter((s) =>
    /(?:width|height)\s*:\s*(?:0|0px|0%|NaN%?|undefined)\s*(?:;|$)/.test(s));
  report(`${label} 图形元件无 0 尺寸（共 ${sized.length} 个带内联尺寸）`,
    zeroSized.length === 0, zeroSized.slice(0, 2).join(" | "));

  /* 3. 判断来源必须显式上屏。
     《07-Agent运行与落库口径.md》§七：上游没跑过时下游必须降级说明，
     不能悄悄回落到预烤值。所以页面上必须能读到「这批结论是谁做的」。
     子体清单页没有判断层内容，不要求。 */
  if (pageId !== "kw-child" || objectId) {
    const declared = /尚未接入关键词 Agent|本次 Agent 判断|Agent 结果已过期/
      .test(text);
    report(`${label} 判断来源已上屏`, declared,
      "页面没说这批结论是 Agent 产出还是构造脚手架");
  }

  unmount();
}

console.log(`\n${fail === 0 ? "全部" : ""}检查完成，失败 ${fail} 条`);
process.exit(fail ? 1 : 0);
