/* 关键词模块 · 对象栏（左侧）
 *
 * 一个选择器管五个页面。关键词模块有**两类判断对象**（市场关键词、子 ASIN），
 * 所以顶部带类型切换；选中一条就进对应的单对象分析页。
 *
 * 为什么必须有它：8-31 会上定的第 4 条 ——「每个 Agent 加前置输入口径，
 * 不要点一下跑全量」。没有选择器的时候，右侧任务面板只能跑全量，
 * 那正是要改掉的东西。选择器就是那个「前置输入口径」。
 *
 * 对象栏的外壳只给了 .wb-rail 这一个容器，里面的标记归模块自己（同库存模块）。
 *
 * 搜索走接口而不是本地过滤：词库 1,991 个词，列表只取前 60 条，
 * 本地过滤会在词存在却不在这 60 条里时显示「搜不到」—— 那是撒谎。
 */

const TYPES = [
  { key: "term", label: "关键词", page: "kw-term" },
  { key: "child", label: "子 ASIN", page: "kw-asin" },
];

const LIMIT = 60;
let timer = null;

/* 有没有真 DOM。渲染态门禁（tests/test_keyword_render.mjs）用假节点在 Node 里
   渲染整页，那边没有 document、也没有真的 <input>，而对象栏要挂 input 事件、
   还要在重渲染后还原光标位置。没这道守卫，对象栏会把整页渲染带崩，
   门禁报的错跟被测的事毫无关系（charts.js 踩过同一个坑）。
   浏览器里 document 恒存在，所以守卫只在测试环境生效。 */
function hasDOM() {
  return typeof document !== "undefined" && !!document.createElement;
}

/* 当前该选哪一类。
   页面只定**初值**，用户手动切过之后以手动为准 —— 第一版按 pageId 强制，
   于是站在子 ASIN 盘点页上点「关键词」那个页签毫无反应，
   对象栏就变成了死路（从 ASIN 页没法用它跳到关键词页）。
   判据是「页面有没有换」：换页跟随页面，同一页内不覆盖手动选择。 */
function activeType(ctx) {
  const implied = ctx.pageId === "kw-asin" ? "child"
    : ctx.pageId === "kw-term" ? "term" : null;
  if (ctx.state.railPage !== ctx.pageId) {
    ctx.state.railPage = ctx.pageId;
    if (implied) ctx.state.railType = implied;
  }
  return ctx.state.railType || implied || "term";
}

export async function renderRail(rail, ctx) {
  if (!rail || !hasDOM()) return;
  const el = ctx.el;
  const type = activeType(ctx);
  ctx.state.railType = type;
  const q = ctx.state.railQuery || "";

  const wrap = el("div", { class: "kw-rail" });

  // 类型切换
  wrap.appendChild(el("div", { class: "kw-rail-tabs" }, TYPES.map((t) =>
    el("button", {
      class: "kw-rail-tab" + (t.key === type ? " on" : ""),
      type: "button", text: t.label,
      onclick: () => {
        ctx.state.railType = t.key;
        ctx.state.railQuery = "";
        renderRail(rail, ctx);
      },
    }))));

  // 搜索
  const box = el("input", {
    class: "kw-rail-search", type: "search", value: q,
    placeholder: type === "term" ? "搜关键词" : "搜子 ASIN 或款号",
    "aria-label": type === "term" ? "搜关键词" : "搜子 ASIN 或款号",
  });
  box.addEventListener("input", () => {
    ctx.state.railQuery = box.value;
    clearTimeout(timer);
    // 打字每个字符都发一次请求会把服务端刷满，等停手 260ms 再查
    timer = setTimeout(() => renderRail(rail, ctx), 260);
  });
  wrap.appendChild(box);

  const listHost = el("div", { class: "kw-rail-list" }, [
    el("div", { class: "kw-rail-note", text: "读取中…" }),
  ]);
  wrap.appendChild(listHost);
  rail.textContent = "";
  rail.appendChild(wrap);
  // 重渲染会重建输入框，正在打字时要把焦点和光标位置还回去
  if (document.activeElement !== box && q) {
    box.focus();
    box.setSelectionRange(q.length, q.length);
  }

  let rows = [];
  let total = 0;
  try {
    if (type === "term") {
      const d = await ctx.api("terms", { q, limit: LIMIT });
      total = d.total_matched;
      rows = (d.terms || []).map((t) => ({
        id: t.keyword_id,
        main: t.keyword,
        sub: [t.keyword_cn, t.operator_role_label].filter(Boolean).join(" · "),
        num: t.monthly_search_volume,
        numTitle: "月搜索量",
      }));
    } else {
      const d = await ctx.api("children", { q });
      total = d.total;
      rows = (d.rows || []).map((r) => ({
        id: r.child_asin,
        main: r.child_asin,
        sub: [r.style_no, r.push_role_label].filter(Boolean).join(" · "),
        num: r.pair_count,
        numTitle: "关系词数",
      }));
    }
  } catch (err) {
    listHost.textContent = "";
    listHost.appendChild(el("div", { class: "kw-rail-note",
      text: `清单读不到：${String(err.message || err)}` }));
    return;
  }

  const page = TYPES.find((t) => t.key === type).page;
  listHost.textContent = "";
  if (!rows.length) {
    listHost.appendChild(el("div", { class: "kw-rail-note",
      text: q ? `「${q}」没有匹配的对象` : "本期没有可选对象" }));
    return;
  }
  for (const r of rows) {
    const on = ctx.objectId === r.id;
    const node = el("div", {
      class: "kw-rail-row" + (on ? " on" : ""), tabindex: "0",
      role: "button", "aria-current": on ? "true" : null,
    }, [
      el("div", { class: "kw-rail-id" }, [
        el("b", { text: r.main }),
        r.sub ? el("span", { text: r.sub }) : null,
      ]),
      el("span", { class: "kw-rail-num", title: r.numTitle,
        text: r.num == null ? ctx.fmt.dash : ctx.fmt.int(r.num) }),
    ]);
    const go = () => ctx.open(r.id, page);
    node.addEventListener("click", go);
    node.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); }
    });
    listHost.appendChild(node);
  }
  listHost.appendChild(el("div", { class: "kw-rail-note",
    text: total > rows.length
      ? `显示前 ${rows.length} / 共 ${ctx.fmt.int(total)} 个，用搜索缩小范围`
      : `共 ${ctx.fmt.int(total)} 个` }));
}

export function disposeRail() {
  clearTimeout(timer);
  timer = null;
}
