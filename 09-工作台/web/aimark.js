/* AI 能力徽标 · 唯一来源
 *
 * 为什么单独一个文件：库存模块的子页是 renderDetail(容器, ...) 这样调的，
 * 手里没有 ctx，拿不到 ctx.aiMark。所以字形与词表放在这里，
 * 外壳 import 它挂到 ctx 上给 DOM 派模块用，库存子页直接 import 用字符串派。
 * 两边同一份字形，改一处都变。
 *
 * 用纯 DOM API 建节点，不借外壳的 el() —— 否则 shell.js 和这个文件互相 import。
 *
 * 由来：2026-08-31 会上王楠提的第一条 ——「所有有 AI 功能的部分，你能不能加一个
 * logo 标识……否则就是哪些是看板，哪些是 agent，我很难判断」。
 *
 * 它标的是「这个板块有 Agent 能力」（产品层面的事实，稳定），
 * 不是「这个数这次是谁算的」—— 后者由 --nature-* 那套性质徽标管。
 * 两者不要混：混了以后 Agent 没跑通的板块会看起来像数据造假。
 */

/* 词表必须与 modules/agentcfg/registry_seed.py 的九个 label 一致，门禁 G25 机械核对。
 * 对不上就是「页面标了 AI，但 Agent 配置页里查不到这个 Agent」。
 *
 * 为什么不去拉 /api/agentcfg/agents 自动同步：外壳不能依赖某个具体模块的接口
 * （契约 8.4 —— 一个模块坏了不能连累外壳）。所以留一份镜像，用门禁挡漂移。 */
export const AI_AGENTS = new Set([
  "需求预测", "盘点结论", "库存总体分析",
  "关键词机会与风险", "子体关键词布局",
  "竞品威胁判定",
  "广告异常与决策", "广告目的标签",
  "运营总览",
]);

/* 四角星加一颗小的。控制点落在中心斜对角 1.1 处，四条边等量内凹。
 * 画成内联 SVG 不用 emoji：emoji 各平台字形不同，而且会破掉
 * 「全站只用系统字体一种」那条。 */
const GLYPH =
  '<svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">' +
  '<path fill="currentColor" d="M6.8 2.9 Q7.8 8.2 13.1 9.2 Q7.8 10.2 6.8 15.5' +
  ' Q5.8 10.2 0.5 9.2 Q5.8 8.2 6.8 2.9 Z"/>' +
  '<path fill="currentColor" d="M13.1 0.7 Q13.55 2.85 15.7 3.3 Q13.55 3.75 13.1 5.9' +
  ' Q12.65 3.75 10.5 3.3 Q12.65 2.85 13.1 0.7 Z"/>' +
  '</svg>';

function tip(label) {
  return label + " Agent 参与本板块的判断 · 阈值与运行方式可在「Agent 配置」中调整";
}

/* DOM 形态。词表外的一律返回 null —— 跟 nature()/cond() 同一个把关方式，
 * 这样内部名字想上屏也上不去。 */
export function aiMark(label) {
  if (!AI_AGENTS.has(label)) return null;
  const t = tip(label);
  const span = document.createElement("span");
  span.className = "wb-ai";
  span.setAttribute("data-agent", label);
  span.setAttribute("title", t);
  span.setAttribute("aria-label", t);
  const g = document.createElement("span");
  g.className = "wb-ai-glyph";
  g.innerHTML = GLYPH;
  const txt = document.createElement("span");
  txt.textContent = "AI";
  span.appendChild(g);
  span.appendChild(txt);
  return span;
}

/* 字符串形态，给还在用模板拼 HTML 的模块（库存）。
 * label 只可能来自上面那个词表，不是外部输入，所以直接拼是安全的。 */
export function aiMarkHTML(label) {
  if (!AI_AGENTS.has(label)) return "";
  const t = tip(label);
  return '<span class="wb-ai" data-agent="' + label + '" title="' + t +
         '" aria-label="' + t + '"><span class="wb-ai-glyph">' + GLYPH +
         '</span><span>AI</span></span>';
}


/* ---- 配置方案下拉（方案一 / 方案二 / 方案三…） -------------------------
 *
 * 2026-08-31 会上王楠：「你在这个板块，就是你右上角只需要加一个方案一。
 * 默认方案，或者方案一、方案二、方案三」。动机在后面那句：
 * 「其他家他会在这过程中做他自己的方案……我能拿来卖钱的」。
 *
 * 一个方案 = 某个 Agent 的一套阈值取值。选中就把那几个阈值写进 ctx.setParams，
 * 页面按既有机制重算 —— 不另建一条应用路径，否则「方案」和「手动调参」会打架。
 *
 * 「当前是哪个方案」不另存状态，靠比对现有参数值反推：
 * 全等于某个方案就显示它，都不等就显示「自定义」。存了状态反而会跟手动调参不一致。
 */

let SCHEME_CACHE = null;
let PARAM_DEFAULTS = null;

export async function loadSchemes() {
  if (SCHEME_CACHE) return SCHEME_CACHE;
  try {
    const r = await fetch("/api/agentcfg/schemes");
    if (!r.ok) throw new Error(String(r.status));
    const d = await r.json();
    SCHEME_CACHE = new Map((d.agents || []).map((a) => [a.label, a]));
    // 声明里的默认值。ctx.params 只装**显式设过**的参数，没动过的键根本不在里面，
    // 所以判断「当前是哪个方案」时必须拿它回落 —— 否则全新页面会判成「自定义」。
    PARAM_DEFAULTS = {};
    for (const [k, v] of Object.entries(d.params || {})) PARAM_DEFAULTS[k] = v.default;
  } catch {
    // 方案是增强项。取不到就不显示下拉，页面其余部分照常。
    SCHEME_CACHE = new Map();
  }
  return SCHEME_CACHE;
}

/* 参数值可能是数字也可能是字符串（query 里过一趟就成字符串），所以宽松比。 */
function sameValue(a, b) {
  if (a === b) return true;
  if (a === null || a === undefined || b === null || b === undefined) return false;
  const na = Number(a), nb = Number(b);
  if (!Number.isNaN(na) && !Number.isNaN(nb)) return na === nb;
  return String(a) === String(b);
}

function effective(params, key) {
  const v = params[key];
  if (v === undefined || v === null || v === "") {
    return PARAM_DEFAULTS ? PARAM_DEFAULTS[key] : undefined;
  }
  return v;
}

function activeScheme(agent, params) {
  for (const s of agent.schemes || []) {
    const keys = Object.keys(s.values || {});
    if (keys.length && keys.every((k) => sameValue(effective(params, k), s.values[k]))) {
      return s.id;
    }
  }
  return "";
}

/* 同步渲染，用已缓存的方案表。没缓存或这个 Agent 没有可调阈值就返回 null ——
   没阈值的 Agent 给个只有「默认」一项的下拉是噪音。 */
export function schemePicker(label, ctx) {
  if (!SCHEME_CACHE) return null;
  const agent = SCHEME_CACHE.get(label);
  if (!agent || !(agent.thresholds || []).length) return null;

  const params = ctx.params || {};
  const cur = activeScheme(agent, params);

  const sel = document.createElement("select");
  sel.className = "wb-scheme";
  sel.setAttribute("data-agent", agent.id);
  sel.setAttribute("title",
    label + " 的配置方案 · 选中即按该方案的阈值重算，可在「Agent 配置」里增删");
  sel.setAttribute("aria-label", label + " 的配置方案");

  for (const s of agent.schemes || []) {
    const o = document.createElement("option");
    o.value = s.id;
    o.textContent = s.name;
    if (s.id === cur) o.selected = true;
    sel.appendChild(o);
  }
  if (!cur) {
    // 手动调过参数、对不上任何方案时才出现这一项，且不可回选 ——
    // 回选「自定义」没有意义，它不是一套值。
    const o = document.createElement("option");
    o.value = "";
    o.textContent = "自定义";
    o.selected = true;
    sel.appendChild(o);
  }

  sel.addEventListener("change", () => {
    const s = (agent.schemes || []).find((x) => x.id === sel.value);
    if (!s) return;
    ctx.setParams({ ...s.values });
  });

  const wrap = document.createElement("span");
  wrap.className = "wb-scheme-wrap";
  const cap = document.createElement("span");
  cap.className = "wb-scheme-cap";
  cap.textContent = "方案";
  wrap.appendChild(cap);
  wrap.appendChild(sel);
  return wrap;
}
