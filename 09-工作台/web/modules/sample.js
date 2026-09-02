/* 接入范例 · 前端模块（契约 8.2 的参考实现）
 *
 * 零全局声明，只有 export。$ / el / fmt / 徽标 / 浮层 / 抽屉全部从 ctx 取，
 * 不自己实现 —— 旧两个模块各写了一份浮层，合并时会互相抢当前打开的是谁。
 */

export const id = "sample";
export const apiVersion = 1;
export const usesRail = true;

/* 声明式筛选项。外壳用 label 渲染 chip —— 不声明的话 chip 上会写 query 键名，
 * 那是内部叫法上屏。value 由 ctx.setFilters 写入 URL，模块不自己碰 location。 */
export const filters = [
  { key: "parent", label: "父体" },
  { key: "q", label: "搜索" },
];

/* 可选：覆盖默认路由方案。这里演示写法，行为与默认一致。
 * parsePath 收到的是模块名之后的段，pathFor 返回模块名之后的尾巴。 */
export function parsePath(segments) {
  if (!segments.length) return { pageId: "list", objectId: null };
  if (segments[0] === "detail") return { pageId: "detail", objectId: segments[1] || null };
  return { pageId: "detail", objectId: segments[0] };
}

export function pathFor({ pageId, objectId }) {
  if (pageId === "detail" && objectId) return `detail/${encodeURIComponent(objectId)}`;
  if (pageId === "detail") return "detail";
  return "";
}

let host = null;
let ctxRef = null;

export async function mount(slots, ctx) {
  host = slots;
  ctxRef = ctx;
  await render(ctx);
}

export function unmount() {
  host = null;
  ctxRef = null;
}

export async function render(ctx) {
  ctxRef = ctx || ctxRef;
  if (!host) return;
  await Promise.all([renderRail(ctxRef), renderBody(ctxRef)]);
}

async function renderRail(ctx) {
  const { el } = ctx;
  const meta = await ctx.api("meta");
  const wrap = el("div", { class: "smp-rail" });

  const search = el("input", {
    class: "smp-search",
    type: "search",
    placeholder: "搜子 ASIN 或品名",
    value: ctx.filters.q || "",
    onchange: (e) => ctx.setFilters({ q: e.target.value.trim() || undefined }),
  });
  wrap.appendChild(search);

  wrap.appendChild(el("div", { class: "smp-rail-label", text: `父体 ${meta.parents.length} 个` }));
  const list = el("div", { class: "smp-parents" });
  for (const p of meta.parents) {
    list.appendChild(
      el("button", {
        class: "smp-parent",
        type: "button",
        text: p.label || p.parent_asin,
        onclick: () => ctx.setFilters({ parent: p.parent_asin }),
      })
    );
  }
  wrap.appendChild(list);

  host.rail.textContent = "";
  host.rail.appendChild(wrap);
}

async function renderBody(ctx) {
  const { el, fmt, nature, cond } = ctx;

  if (ctx.pageId === "detail") {
    if (!ctx.objectId) {
      host.body.textContent = "";
      host.body.appendChild(ctx.placeholder("未选择对象", "从对象清单里点一行进来"));
      return;
    }
    const body = await ctx.api(`child/${encodeURIComponent(ctx.objectId)}`);
    host.body.textContent = "";
    if (!body || !body.child_asin) {
      host.body.appendChild(ctx.placeholder("对象不可用", body && body.message ? body.message : "", "error"));
      return;
    }
    const card = el("section", { class: "smp-card" });
    const head = el("div", { class: "smp-id" }, [
      el("span", { class: "wb-mono smp-asin", text: body.child_asin }),
      nature(body.nature),
      cond(body.condition),
    ]);
    card.appendChild(head);
    if (body.parent_name || body.parent_asin) {
      card.appendChild(
        el("p", { class: "smp-sub", text: `父体 ${body.parent_name || ""} ${body.parent_asin || ""}`.trim() })
      );
    }
    const kv = el("dl", { class: "smp-kv" });
    for (const f of body.fields || []) {
      kv.appendChild(el("dt", { text: f.label }));
      kv.appendChild(el("dd", { class: "wb-mono", text: String(f.value) }));
    }
    card.appendChild(kv);
    host.body.appendChild(card);
    return;
  }

  const payload = await ctx.api("children");
  host.body.textContent = "";
  if (!payload.total) {
    host.body.appendChild(ctx.placeholder("没有匹配对象", "调整筛选后重试"));
    return;
  }

  const card = el("section", { class: "smp-card" });

  // 数据性质是恒定值时不要在每一行重复 50 遍 —— 那是噪音。
  // 在概要里说一次，只给和主体不同的行打标。
  const kinds = new Set(payload.items.map((r) => r.nature));
  const uniform = kinds.size === 1 ? payload.items[0].nature : null;

  card.appendChild(
    el("div", { class: "smp-lead" }, [
      el("strong", { class: "wb-num smp-big", text: fmt.int(payload.total) }),
      el("span", { class: "smp-lead-unit", text: "个对象命中" }),
      payload.shown < payload.total
        ? el("span", { class: "smp-sub", text: `当前显示前 ${fmt.int(payload.shown)} 个` })
        : null,
      uniform ? nature(uniform) : null,
    ])
  );

  const table = el("table", { class: "smp-table" });
  const headCells = [
    el("th", { text: "子 ASIN" }),
    el("th", { text: "品名" }),
    el("th", { text: "颜色" }),
    el("th", { text: "尺码" }),
  ];
  if (!uniform) headCells.push(el("th", { text: "数据性质" }));
  table.appendChild(el("thead", {}, [el("tr", {}, headCells)]));

  const tb = el("tbody");
  for (const r of payload.items) {
    const cells = [
      el("td", { class: "wb-mono", text: r.child_asin }),
      el("td", { text: r.name || fmt.dash }),
      el("td", { text: r.colorway || fmt.dash }),
      el("td", { text: r.size || fmt.dash }),
    ];
    if (!uniform) cells.push(el("td", {}, [nature(r.nature)]));
    tb.appendChild(
      el("tr", { class: "smp-row", tabindex: "0", onclick: () => ctx.open(r.child_asin, "detail") }, cells)
    );
  }
  table.appendChild(tb);
  card.appendChild(table);
  host.body.appendChild(card);
}
