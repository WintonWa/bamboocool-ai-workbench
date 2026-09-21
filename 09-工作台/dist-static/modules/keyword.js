/* 关键词分析模块 · 前端入口
 *
 * $ / el / 格式化 / 浮层 / 抽屉一律从 ctx 取，不自己实现。
 * 状态只读写 state.modules.keyword；跨模块上下文只读，写走 ctx.setShared。
 *
 * 2026-09-04 重构：正文按页拆到 keyword/ 子目录，本文件只留路由与装载。
 * 拆分的理由不是文件太长，是**承载体要能复用**：三页共用同一套板块壳、结论行、
 * 证据组与图形件（keyword/parts.js），否则每页各写一套，「固定形式」就无从谈起。
 * 设计见 07-关键词分析模块/01-方案与数据需求/09-页面承载体设计.md。
 */

import { renderOverview } from "./keyword/page-overview.js";
import { renderLibrary, renderTerm } from "./keyword/page-market.js";
import { renderChild, renderChildList } from "./keyword/page-child.js";
import { renderRail, disposeRail } from "./keyword/rail.js";

export const id = "keyword";
export const apiVersion = 1;

export const filters = [
  { key: "q", kind: "search", label: "关键词或子 ASIN" },
  {
    key: "dimension", kind: "select", label: "需求维度",
    optionsFrom: "meta.demand_dimensions",
  },
  {
    key: "role", kind: "select", label: "运营角色",
    options: [
      { value: "core", label: "核心词" },
      { value: "explore", label: "探索词" },
      { value: "longtail", label: "长尾词" },
      { value: "pending_validation", label: "待验证词" },
    ],
  },
  {
    key: "evidence", kind: "select", label: "证据类型",
    optionsFrom: "meta.distributions.evidence_type",
  },
  {
    key: "state", kind: "select", label: "数据状态",
    options: ["正常", "过期", "缺失", "待确认", "空结果"].map((v) => ({ value: v, label: v })),
  },
];

let root = null;
let rail = null;
let ctx = null;
let meta = null;

/* 外壳调用 impl.mount({ rail, body }, ctx)，首屏由 mount 自己渲染；
   之后同模块内的状态变化走 render(ctx)。两者签名都不是 (node, state)。 */
export async function mount(nodes, context) {
  root = nodes.body;
  rail = nodes.rail;
  ctx = context;
  await render(context);
}

export function unmount() {
  disposeRail();
  root = null;
  rail = null;
  ctx = null;
  meta = null;
}

/* 契约 8.8：URL 即状态。两个纯函数，无副作用，可单测。
   pathFor 只返回尾段 —— 外壳自己拼 /keyword 前缀，这里再加会变成 /keyword/keyword/...

   段名直接用页面 id（kw-asin 而不是 asin）：外壳的 applyUrl() 在模块 impl 加载前
   就解析一次 URL，那时拿不到 impl.parsePath，会回落到「段名匹配 pages[].id」的默认方案。
   用短别名的话首屏深链会被解析成 objectId，页签停在第一页。parsePath 仍兼容短别名。

   2026-09-04 拆页：单词深研与子体盘点从列表页的 objectId 子视图提成独立页面
   （kw-term / kw-asin）。旧深链 /keyword/kw-child/<asin> 仍要能开，所以
   parsePath 把「列表页 + 带对象」重定向到对应的单对象页 —— 客户和同事手上
   已经有那种链接了，让它 404 或者停在列表页都是回退。 */
const PAGE_ALIAS = {
  overview: "kw-overview",
  market: "kw-market",
  child: "kw-child",
  term: "kw-term",
  asin: "kw-asin",
};
const PAGE_IDS = new Set(["kw-overview", "kw-market", "kw-child", "kw-term", "kw-asin"]);
/* 带对象时列表页要跳到它的单对象页 */
const DETAIL_OF = { "kw-market": "kw-term", "kw-child": "kw-asin" };

export function pathFor({ pageId, objectId } = {}) {
  const seg = [];
  if (PAGE_IDS.has(pageId) && pageId !== "kw-overview") seg.push(pageId);
  else if (objectId) seg.push("kw-overview");
  if (objectId) seg.push(encodeURIComponent(objectId));
  return seg.join("/");
}

export function parsePath(segments = []) {
  const s = segments.filter(Boolean);
  const head = s[0];
  let pageId = "kw-overview";
  let rest = s;
  if (PAGE_IDS.has(head)) { pageId = head; rest = s.slice(1); }
  else if (PAGE_ALIAS[head]) { pageId = PAGE_ALIAS[head]; rest = s.slice(1); }
  let objectId;
  if (rest.length) {
    const raw = rest[rest.length - 1];
    try { objectId = decodeURIComponent(raw); } catch { objectId = raw; }
  }
  if (objectId && DETAIL_OF[pageId]) pageId = DETAIL_OF[pageId];
  return { pageId, objectId };
}

/* 取载荷。三种失败各自出对应状态，不混成一个「加载失败」——
   「缺失」和「打不开」对读的人是两件事。 */
async function fetchPayload(resource) {
  try {
    return { ok: true, d: await ctx.api(resource) };
  } catch (err) {
    return { ok: false, err: String(err.message || err) };
  }
}

function bail(res) {
  if (!res.ok) {
    root.replaceChildren(ctx.placeholder("这一页暂时打不开", res.err, "失败"));
    return true;
  }
  const c = res.d.condition;
  if (c === "缺失" || c === "空结果") {
    root.replaceChildren(ctx.placeholder(c, res.d.message || "", c));
    return true;
  }
  return false;
}

export async function render(context) {
  ctx = context || ctx;
  if (!root || !ctx) return;
  const objectId = ctx.objectId;
  /* 列表页拿到对象就按单对象页渲染。parsePath 已经在 URL 层做过这个重定向，
     但外壳的历史记录、以及别处直接调 navigate 都可能递进来这个组合 ——
     两处都兜住，否则旧链接会静默停在列表页，看起来像点了没反应。 */
  let page = ctx.pageId || "kw-overview";
  if (objectId && DETAIL_OF[page]) page = DETAIL_OF[page];
  if (!meta) meta = await ctx.api("meta");

  // 对象栏是选择器，五个页面都要有（8-31 会上的「Agent 前置输入口径」）
  renderRail(rail, ctx);

  if (page === "kw-asin") {
    if (!objectId) return renderChildList(ctx, root, { picker: true });
    const res = await fetchPayload(`child/${encodeURIComponent(objectId)}`);
    if (bail(res)) return;
    return renderChild(ctx, root, res.d);
  }

  if (page === "kw-term") {
    if (!objectId) {
      root.replaceChildren(ctx.placeholder(
        "先选一个关键词",
        "左侧对象栏切到「关键词」，点一条进单词分析。也可以在市场关键词库里点行进来。",
        "待确认"));
      return;
    }
    const res = await fetchPayload(`term/${encodeURIComponent(objectId)}`);
    if (bail(res)) return;
    return renderTerm(ctx, root, res.d);
  }

  if (page === "kw-child") return renderChildList(ctx, root);

  if (page === "kw-market") {
    const res = await fetchPayload("terms");
    if (bail(res)) return;
    return renderLibrary(ctx, root, res.d);
  }

  const res = await fetchPayload("overview");
  if (bail(res)) return;
  if (res.d.condition !== "正常") {
    root.replaceChildren(ctx.placeholder(res.d.condition, res.d.message || "",
      res.d.condition));
    return;
  }
  return renderOverview(ctx, root, res.d);
}
