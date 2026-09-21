/* 玻璃面板实时调参工具（开发用）
 *
 * 用 ?tune=1 打开，不带参数时这个文件什么都不做 —— 客户演示看不到。
 *
 * 它直接改 :root 上的 CSS 自定义属性，所以调的是**真面板**，不是一个仿制的预览。
 * 调完点「复制 tokens」拿到可直接粘进 web/tokens.css 的文本。
 *
 * 自己不用毛玻璃：调玻璃的工具如果也是玻璃，就没法判断了。实底白面板，放左侧，
 * 避免和右侧的任务面板重叠。
 */

/* 滑块初值必须和 tokens.css 里的当前默认值一致，否则一开调参器面板就跳回旧样子。
 * 改了 tokens.css 的 --glass-* / --rail-* / --panel-* 记得同步这里。
 *
 * 位置用「贴边 + 偏移」描述，不用绝对坐标：
 *   参照点 = 面板所贴那条视口边的垂直中心（任务面板贴右缘，对象栏贴左缘）
 *   离边距离 = 到那条边的距离；纵向偏移 = 相对垂直中心上下偏多少（可负）
 * { sep: "..." } 是分组标题，不是滑块。 */
const KNOBS = [
  { sep: "任务面板 · 外观" },
  { key: "alpha", label: "透明度", min: 0, max: 1, step: 0.01, val: 0.02, digits: 2,
    hint: "越小越透。浅色页面上这是「看得见背后」的主旋钮" },
  { key: "blur", label: "模糊", min: 0, max: 48, step: 1, val: 7, unit: "px", digits: 0,
    hint: "越大越糊。加大会把稀疏内容糊成白，反而不像玻璃" },
  { key: "tint", label: "底色明度", min: 200, max: 255, step: 1, val: 208, digits: 0,
    hint: "越低越灰。灰调给面板「材质感」，但会牺牲通透" },
  { key: "saturate", label: "饱和度", min: 100, max: 260, step: 5, val: 140, unit: "%", digits: 0 },
  { key: "brightness", label: "亮度", min: 0.85, max: 1.08, step: 0.01, val: 0.91, digits: 2,
    hint: "低于 1 会压暗背景，让玻璃有厚度" },
  { key: "hi", label: "亮边", min: 0, max: 1, step: 0.02, val: 0, digits: 2,
    hint: "内高光。为 0 时边界完全靠阴影撑" },
  { key: "shadow", label: "阴影", min: 0, max: 2, step: 0.05, val: 0.5, digits: 2 },
  { key: "radius", label: "圆角", min: 0, max: 40, step: 1, val: 34, unit: "px", digits: 0 },

  { sep: "任务面板 · 尺寸与位置" },
  { key: "w", label: "宽度", min: 15, max: 56, step: 1, val: 20, unit: "vw", digits: 0 },
  { key: "h", label: "高度", min: 25, max: 96, step: 1, val: 89, unit: "vh", digits: 0 },
  { key: "edge", label: "离右边距", min: 0, max: 200, step: 2, val: 16, unit: "px", digits: 0,
    hint: "参照点是右缘垂直中心，这是到右缘的距离" },
  { key: "dy", label: "纵向偏移", min: -300, max: 300, step: 4, val: 0, unit: "px", digits: 0,
    hint: "相对垂直中心上下偏移，负数往上" },

  { sep: "对象栏 · 外观" },
  { key: "railAlpha", label: "透明度", min: 0, max: 1, step: 0.01, val: 0.02, digits: 2,
    hint: "对象栏背后是最密的数据区，太透会两层文字打架" },
  { key: "railBlur", label: "模糊", min: 0, max: 48, step: 1, val: 7, unit: "px", digits: 0 },
  { key: "railTint", label: "底色明度", min: 200, max: 255, step: 1, val: 208, digits: 0 },
  { key: "railR", label: "圆角", min: 0, max: 40, step: 1, val: 34, unit: "px", digits: 0 },

  { sep: "对象栏 · 尺寸与位置" },
  { key: "railW", label: "宽度", min: 15, max: 56, step: 1, val: 22, unit: "vw", digits: 0,
    hint: "同时决定 push 模式下的栅格列宽" },
  { key: "railH", label: "高度", min: 25, max: 96, step: 1, val: 89, unit: "vh", digits: 0 },
  { key: "railEdge", label: "离左边距", min: 0, max: 200, step: 2, val: 16, unit: "px", digits: 0,
    hint: "参照点是左缘垂直中心，这是到左缘的距离" },
  { key: "railDy", label: "纵向偏移", min: -300, max: 300, step: 4, val: 0, unit: "px", digits: 0,
    hint: "相对垂直中心上下偏移，负数往上" },

  { sep: "外壳 · 字号" },
  { key: "fsPage", label: "页面标题", min: 24, max: 40, step: 1, val: 28, unit: "px", digits: 0,
    hint: "阶梯第九档 --fs-page。下限 24 是板块标题，等于 24 就没有层级差了；到 30 会和「单个数字」撞档" },

  { sep: "滚动条" },
  { key: "sbAlpha", label: "深浅", min: 0, max: 1, step: 0.05, val: 0.55, digits: 2,
    hint: "滑块的黑度。轨道恒为透明，不会出现白底" },
  { key: "sbSize", label: "粗细", min: 4, max: 16, step: 1, val: 8, unit: "px", digits: 0 },
];

/* ---- 值与存档 -----------------------------------------------------------
 * 拖完刷新一次全回默认，等于白调 —— 所以存档，而且是刷新后立刻生效，
 * 不需要再打开一次调参器。
 *
 * 只存"被动过的那几个"，不存全部。理由：存全部的话，以后在 tokens.css 里
 * 改一个默认值会被旧存档静默盖掉 —— 手改文件看着像没生效，而且查不出原因。
 * 只存差异，没动过的旋钮就永远跟着 tokens.css 走。
 */
const TUNE_STORE = "wb.tune.values";
const DEFAULTS = {};
for (const k of KNOBS) if (k.key) DEFAULTS[k.key] = k.val;

function loadStore() {
  try {
    const raw = JSON.parse(localStorage.getItem(TUNE_STORE) || "{}");
    const out = {};
    // 只认还存在的旋钮：删过的键留在存档里会变成幽灵
    for (const [key, val] of Object.entries(raw)) {
      if (key in DEFAULTS && typeof val === "number" && Number.isFinite(val)) out[key] = val;
    }
    return out;
  } catch {
    return {};                                     // 存档坏了就当没存过，不该崩
  }
}

function saveStore() {
  try {
    const out = {};
    for (const [key, val] of Object.entries(v)) {
      if (val !== DEFAULTS[key]) out[key] = val;
    }
    if (Object.keys(out).length) localStorage.setItem(TUNE_STORE, JSON.stringify(out));
    else localStorage.removeItem(TUNE_STORE);
  } catch {
    /* 隐私模式下写不进，降级为只在本次会话有效 */
  }
}

const stored = loadStore();
const v = { ...DEFAULTS, ...stored };

/* 每个 CSS 令牌写成 {令牌, 依赖哪几个旋钮, 怎么算}。
 * 有了依赖表就能只写"受影响的那几个令牌"，而不是每次把二十多个全内联 ——
 * 全内联的后果是 tokens.css 从此被行内样式压住，手改文件看着像没生效。 */
function specs() {
  const t = Math.round(v.tint);
  const rt = Math.round(v.railTint);
  const s = v.shadow;
  return [
    { p: "--glass-bg", d: ["tint", "alpha"],
      f: () => `rgba(${t}, ${Math.min(255, t + 1)}, ${Math.min(255, t + 3)}, ${v.alpha})` },
    { p: "--glass-filter", d: ["saturate", "blur", "brightness"],
      f: () => `saturate(${Math.round(v.saturate)}%) blur(${Math.round(v.blur)}px) brightness(${v.brightness})` },
    { p: "--glass-hi", d: ["hi"], f: () => `rgba(255, 255, 255, ${v.hi})` },
    { p: "--glass-shadow", d: ["shadow"],
      f: () => `0 ${Math.round(20 * s)}px ${Math.round(60 * s)}px rgba(9,9,11,${(0.2 * s).toFixed(3)}), ` +
               `0 2px ${Math.round(10 * s)}px rgba(9,9,11,${(0.07 * s).toFixed(3)})` },
    { p: "--panel-r", d: ["radius"], f: () => `${Math.round(v.radius)}px` },
    { p: "--panel-w", d: ["w"], f: () => `${Math.round(v.w)}vw` },
    { p: "--panel-h", d: ["h"], f: () => `${Math.round(v.h)}vh` },
    { p: "--panel-edge", d: ["edge"], f: () => `${Math.round(v.edge)}px` },
    { p: "--panel-dy", d: ["dy"], f: () => `${Math.round(v.dy)}px` },
    // 对象栏独立一组。色调公式与任务面板一致，同样的滑块值出来的颜色才真的一样。
    { p: "--rail-bg", d: ["railTint", "railAlpha"],
      f: () => `rgba(${rt}, ${Math.min(255, rt + 1)}, ${Math.min(255, rt + 3)}, ${v.railAlpha})` },
    { p: "--rail-filter", d: ["saturate", "railBlur", "brightness"],
      f: () => `saturate(${Math.round(v.saturate)}%) blur(${Math.round(v.railBlur)}px) brightness(${v.brightness})` },
    { p: "--rail-r", d: ["railR"], f: () => `${Math.round(v.railR)}px` },
    { p: "--rail-w", d: ["railW"], f: () => `${Math.round(v.railW)}vw` },
    { p: "--rail-h", d: ["railH"], f: () => `${Math.round(v.railH)}vh` },
    { p: "--rail-edge", d: ["railEdge"], f: () => `${Math.round(v.railEdge)}px` },
    { p: "--rail-dy", d: ["railDy"], f: () => `${Math.round(v.railDy)}px` },
    // 外壳字号。第九档，页面标题必须大于板块标题 24，否则层级读反。
    { p: "--fs-page", d: ["fsPage"], f: () => `${Math.round(v.fsPage)}px` },
    // 滚动条。--sb-thumb 由 --sb-alpha 拼出来，所以只改 alpha 就够。
    { p: "--sb-alpha", d: ["sbAlpha"], f: () => `${v.sbAlpha}` },
    { p: "--sb-size", d: ["sbSize"], f: () => `${Math.round(v.sbSize)}px` },
  ];
}

/** touched 给 null 表示"全写一遍"（调参器开着时用）；给键集合则只写受影响的令牌。 */
function apply(touched) {
  const r = document.documentElement.style;
  for (const s of specs()) {
    if (touched && !s.d.some((dep) => touched.has(dep))) continue;
    r.setProperty(s.p, s.f());
  }
}

/** 恢复默认 = 把行内样式摘掉，让 tokens.css 重新说话，而不是把默认值内联回去。 */
function clearInline() {
  const r = document.documentElement.style;
  for (const s of specs()) r.removeProperty(s.p);
}


function tokenText() {
  const t = Math.round(v.tint);
  return [
    "  /* 由 ?tune=1 调参工具导出 */",
    `  --glass-bg: rgba(${t}, ${Math.min(255, t + 1)}, ${Math.min(255, t + 3)}, ${v.alpha});`,
    `  --glass-filter: saturate(${Math.round(v.saturate)}%) blur(${Math.round(v.blur)}px) brightness(${v.brightness});`,
    `  --glass-hi: rgba(255, 255, 255, ${v.hi});`,
    `  --glass-shadow: 0 ${Math.round(20 * v.shadow)}px ${Math.round(60 * v.shadow)}px rgba(9,9,11,${(0.2 * v.shadow).toFixed(3)}), 0 2px ${Math.round(10 * v.shadow)}px rgba(9,9,11,${(0.07 * v.shadow).toFixed(3)});`,
    `  --panel-r: ${Math.round(v.radius)}px;`,
    `  --panel-w: ${Math.round(v.w)}vw;`,
    `  --panel-h: ${Math.round(v.h)}vh;`,
    `  --panel-edge: ${Math.round(v.edge)}px;`,
    `  --panel-dy: ${Math.round(v.dy)}px;`,
    `  --rail-bg: rgba(${Math.round(v.railTint)}, ${Math.min(255, Math.round(v.railTint) + 1)}, ${Math.min(255, Math.round(v.railTint) + 3)}, ${v.railAlpha});`,
    `  --rail-filter: saturate(${Math.round(v.saturate)}%) blur(${Math.round(v.railBlur)}px) brightness(${v.brightness});`,
    `  --rail-r: ${Math.round(v.railR)}px;`,
    `  --rail-w: ${Math.round(v.railW)}vw;`,
    `  --rail-h: ${Math.round(v.railH)}vh;`,
    `  --rail-edge: ${Math.round(v.railEdge)}px;`,
    `  --rail-dy: ${Math.round(v.railDy)}px;`,
    `  --fs-page: ${Math.round(v.fsPage)}px;`,
    `  --sb-alpha: ${v.sbAlpha};`,
    `  --sb-size: ${Math.round(v.sbSize)}px;`,
  ].join("\n");
}

function build() {
  const box = document.createElement("aside");
  box.className = "wb-tune";
  box.setAttribute("aria-label", "玻璃面板调参");

  const head = document.createElement("div");
  head.className = "wb-tune-head";
  head.textContent = "面板调参";
  const close = document.createElement("button");
  close.className = "wb-tune-x";
  close.type = "button";
  close.textContent = "✕";
  close.setAttribute("aria-label", "关闭调参");
  close.onclick = () => box.remove();
  head.appendChild(close);
  box.appendChild(head);

  const rows = document.createElement("div");
  rows.className = "wb-tune-rows";
  for (const k of KNOBS) {
    if (k.sep) {
      const sep = document.createElement("div");
      sep.className = "wb-tune-sep";
      sep.textContent = k.sep;
      rows.appendChild(sep);
      continue;
    }
    const row = document.createElement("label");
    row.className = "wb-tune-row";
    if (k.hint) row.title = k.hint;

    const name = document.createElement("span");
    name.className = "wb-tune-name";
    name.textContent = k.label;

    const input = document.createElement("input");
    input.type = "range";
    input.min = k.min;
    input.max = k.max;
    input.step = k.step;
    input.value = k.val;
    input.className = "wb-tune-range";

    const out = document.createElement("span");
    out.className = "wb-tune-val";
    const show = () => {
      out.textContent = Number(v[k.key]).toFixed(k.digits) + (k.unit || "");
    };
    show();

    input.oninput = () => {
      v[k.key] = Number(input.value);
      show();
      apply(new Set([k.key]));                     // 只重算受这个旋钮影响的令牌
      saveStore();                                 // 拖一下就存一次，没有"保存"按钮可忘按
    };

    row.append(name, input, out);
    rows.appendChild(row);
  }
  box.appendChild(rows);

  const foot = document.createElement("div");
  foot.className = "wb-tune-foot";

  const copy = document.createElement("button");
  copy.className = "wb-tune-btn";
  copy.type = "button";
  copy.textContent = "复制 tokens";
  copy.onclick = async () => {
    const txt = tokenText();
    try {
      await navigator.clipboard.writeText(txt);
      copy.textContent = "已复制";
    } catch {
      copy.textContent = "见下方";
    }
    pre.hidden = false;
    pre.textContent = txt;
    setTimeout(() => { copy.textContent = "复制 tokens"; }, 1600);
  };

  const reset = document.createElement("button");
  reset.className = "wb-tune-btn";
  reset.type = "button";
  reset.textContent = "恢复默认";
  reset.onclick = () => {
    for (const k of KNOBS) if (k.key) v[k.key] = k.val;
    // 摘掉行内样式让 tokens.css 重新说话，而不是把默认值内联回去 ——
    // 内联回去的话，以后手改 tokens.css 会被这层行内样式压住。
    clearInline();
    saveStore();                                   // 全等于默认 -> 存档被删掉
    box.remove();
    build();
  };

  foot.append(copy, reset);
  box.appendChild(foot);

  const pre = document.createElement("pre");
  pre.className = "wb-tune-pre";
  pre.hidden = true;
  box.appendChild(pre);

  document.body.appendChild(box);
  return box;
}

const OPEN_BY_URL = new URLSearchParams(location.search).get("tune") === "1";

function start() {
  if (document.querySelector(".wb-tune")) return;   // 已经开了就不再开一个
  build();                                          // 存档在启动时已经套上，这里不必再 apply
  // 调参得看得见面板，自动展开一次
  const h = document.querySelector("#wb-handle");
  if (h && !h.hidden) h.click();
}

/* 存档立刻生效 —— 不等打开调参器。
 * 这是"刷新一次调的就白调了"那个 bug 的真正修法：光存下来不够，
 * 得在每次加载时把存过的令牌写回去，否则只有开着调参器时才看得到自己调的样子。
 * 只写存过的那几个：没动过的旋钮继续由 tokens.css 说话。 */
if (Object.keys(stored).length) apply(new Set(Object.keys(stored)));

/* 两种打开方式：
 *   1. URL 加 ?tune=1
 *   2. 键盘 Shift + T（输入框里打字时不触发）
 * 快捷键始终注册，所以不带 ?tune=1 也能随时叫出来。 */
document.addEventListener("keydown", (e) => {
  if (!e.shiftKey || e.key.toLowerCase() !== "t") return;
  const t = e.target;
  const typing = t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable);
  if (typing) return;
  const open = document.querySelector(".wb-tune");
  if (open) open.remove();
  else start();
});

if (OPEN_BY_URL) {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => setTimeout(start, 600));
  } else {
    setTimeout(start, 600);
  }
}
