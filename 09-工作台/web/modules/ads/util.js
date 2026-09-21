/* 广告分析模块 · 两个页面共用的小工具
 *
 * 从 ads.js 抽出来，页面一与页面二都 import 这一份。
 * **不要在任何一边再抄一份中文映射表** —— 抄一份就是第二个真相来源，
 * 而这个项目里近义命名 / 双写是最主要的失效模式。
 */

/* ---------------------------------------------------------------- 格式化 */

/* 外壳的 fmt.money 用 toFixed，不带千分位，六位数会渲染成 $313663。
   fmt.int 是带的（toLocaleString），只有 money 漏了。
   这该在外壳修，但模块不许碰 shell.js，所以模块内自己包一层。 */
export function usd(v, d = 0) {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const n = Number(v);
  return "$" + n.toLocaleString("zh-CN", { minimumFractionDigits: d,
                                           maximumFractionDigits: d });
}

/* ------------------------------------------------------------ 浮层与标题 */

/* 外壳的 pop.show 用 textContent 落地，传 HTML 会被整段转义摆到屏上，
   所以 ⓘ 内容一律纯文本、用 \n 分行。但 #wb-pop 是 white-space: normal，
   \n 会被当空格吃掉 —— 浮层和抽屉一样在模块作用域外，同样靠内容侧的
   标记把作用域带过去（见 ads.css 的 .ads-popbody）。 */
export function popText(c, anchor, title, body) {
  // body 可省：调用点已经把多行拼成一整段时，整段就是 title。
  // 不无条件拼 title + body —— 缺参会把 undefined 摆到客户面前。
  c.pop.show(anchor, body === undefined ? String(title)
    : String(title) + "\n" + String(body));
}

export function infoBtn(c, title, html) {
  const b = c.el("button", { class: "ads-ib", type: "button",
                             title: "计算方法与口径" }, "ⓘ");
  b.addEventListener("click", (e) => {
    e.stopPropagation();
    popText(c, b, title, html);
  });
  return b;
}

export function colHead(c, title, note) {
  return c.el("h3", { class: "ads-h3" }, [
    c.el("span", {}, title),
    c.el("span", { class: "ads-mut" }, " " + (note || "")),
  ]);
}

export function subhead(c, t) {
  return c.el("div", { class: "ads-subhead" }, t);
}

/* ------------------------------------------------------------ 文件下载 */

/* 页面一的「导出 Excel」。
   **这个函数原来根本不存在** —— ads.js 第 450 行一直在调一个未定义的名字，
   点下去只会在控制台抛 ReferenceError，按钮看着好的、其实是死的。
   未定义标识符不是静态错误，只在执行到那一行才抛，所以没人发现。

   走 <a download> 而不是 fetch + blob：文件名由后端的 Content-Disposition
   决定，浏览器原生下载就用它，不必在前端重拼一遍（中文名还要再编码一次）。 */
export function downloadExport(btn, url) {
  const prev = btn ? btn.textContent : "";
  if (btn) { btn.textContent = "导出中…"; btn.disabled = true; }
  const a = document.createElement("a");
  a.href = url;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
  // 下载由浏览器接手，页面拿不到完成事件，所以按时间恢复按钮。
  if (btn) {
    setTimeout(() => { btn.textContent = prev; btn.disabled = false; }, 1200);
  }
}

/* ------------------------------------------------------------ 首句截断 */

/* Agent 写的 what_happened / detail / rationale 实测 200–500 字。
   卡面只放第一句，全文进 ⓘ。
   **只截不改写**：摘要是二次判断，会产出 Agent 没说过的话。
   截不到句号就按字数截并显式带省略号，让人知道后面还有。 */
export function firstSentence(text, max = 76) {
  const s = String(text || "").trim();
  if (!s) return "";
  const m = s.search(/[。；！？]/);
  if (m >= 0 && m + 1 <= max) return s.slice(0, m + 1);
  if (s.length <= max) return s;
  return s.slice(0, max) + "…";
}

/* 长文有没有被截 —— 决定要不要挂 ⓘ */
export function isTruncated(text, max = 76) {
  const s = String(text || "").trim();
  if (!s) return false;
  return firstSentence(s, max).length < s.length;
}

/* --------------------------------------------------------- 码值翻中文 */

/* Agent 落表时既写码值也写中文 label（实测 task_type + task_label 并存），
   回放路径则由服务端翻译。两条路命名不完全一致，所以取值走这一个口子：
   有 label 用 label，没有就用本地映射，都没有才退到中性兜底 ——
   任何情况下都不把码值摆到屏上（契约 G9）。 */
export const LOCAL_CN = {
  // 与 compute.py 顶部的映射表同源。Agent 只出码值，中文一律在这里翻。
  task_type: {
    VERIFY_INBOUND_BEFORE_SCALE: "先核验入库再扩量",
    PROTECT_CORE_QUERY_VISIBILITY: "守住核心词可见性",
    CONTROL_EFFICIENCY_DRIFT: "控制效率漂移",
    OBSERVE_EFFICIENCY: "观察效率",
    CLEAR_AGED_INVENTORY: "处理高库龄库存",
    ACCELERATE_SELL_THROUGH: "加速去库存",
    COVER_MATCHED_QUERY_GAP: "补上匹配词的覆盖缺口",
    CLARIFY_ATTRIBUTION_BOUNDARY: "厘清归因边界",
    MAINTAIN_CURRENT_SETUP: "维持当前配置",
  },
  problem_type: {
    INVENTORY_COVERAGE_RISK: "库存承接不足",
    CORE_QUERY_DEFENSE: "核心词守位存在缺口",
    ACOS_UP_VS_SELF_HISTORY: "ACoS 高于自身历史",
    EFFICIENCY_VARIATION: "效率波动",
    KEYWORD_COVERAGE_GAP: "关键词机会存在但覆盖不足",
    ATTRIBUTION_UNCLEAR: "广告对象与子 ASIN 关系不清",
    GOAL_PURPOSE_MISMATCH: "产品目标与广告目的不一致",
    MIXED_PURPOSE_GROUP: "一个广告组混合多个目的",
    REQUIRED_TASK_MISSING: "必要广告任务缺失",
    DUPLICATE_TASK_OWNERS: "多个广告组重复承担同一任务",
    PERFORMANCE_NOT_SUPPORTING: "表现不支撑已确认的目的",
    COMPETITOR_NO_TASK: "竞品压力存在但无对应任务",
    INSUFFICIENT_EVIDENCE: "证据或规则不足暂时无法判断",
    NO_ADJUSTMENT_NEEDED: "本期无需调整",
  },
  direction: {
    KEEP: "保持", OBSERVE: "继续观察", ADJUST: "调整", PAUSE: "暂停",
    RESUME: "恢复", SPLIT: "拆分", MERGE: "合并", BUILD: "补建",
    TEST: "低成本测试", DEFER: "暂缓", REQUEST_INFO: "先补信息",
    PREREQUISITE: "前置条件", NEW_STRUCTURE: "补建结构",
  },
  task_direction: {
    KEEP: "保持", OBSERVE: "继续观察", ADJUST: "调整", PAUSE: "暂停",
    RESUME: "恢复", SPLIT: "拆分", MERGE: "合并", BUILD: "补建",
    TEST: "低成本测试", DEFER: "暂缓", REQUEST_INFO: "先补信息",
    PREREQUISITE: "前置条件", NEW_STRUCTURE: "补建结构",
  },
  confidence: { high: "高", medium: "中", low: "低" },
  attribution_limit: {
    exclusive: "只归本品", shared: "与其他子 ASIN 共享",
    unattributed: "无法归因",
  },
  coverage_status: {
    covered: "已有对象承接", partial: "部分承接", missing: "无对象承接",
  },
  gap_source: {
    structure: "结构没建", evidence: "证据不足", none: "无差距",
  },
  basis: {
    confirmed_rule: "客户已确认阈值", self_history: "自身历史",
    peer: "可比对象", conditional: "条件判断",
  },
  basis_level: {
    confirmed_rule: "客户已确认阈值", self_history: "自身历史",
    peer: "可比对象", conditional: "条件判断",
  },
  basis_type: {
    confirmed_rule: "客户已确认阈值", self_history: "自身历史",
    peer: "可比对象", conditional: "条件判断",
  },
  constraint_kind: { hard: "硬性条件", observe: "需要观察" },
  judgment_mode: {
    formal: "正式判断", conditional: "条件性判断", unable: "暂时无法判断",
  },
  match_level: { high: "高匹配", medium: "中匹配", low: "低匹配" },
  pressure_type: {
    price: "价格压制", rank: "排名压制", keyword_entry: "核心词入口被占",
    review: "评价压制", variant: "变体覆盖更广", promotion: "活动压制",
    sales: "销量规模差距",
  },
  issue_type: {
    shared: "共享给多个子 ASIN", unexplained: "无法归到任何广告目的",
    duplicate: "多个对象重复承担", orphan: "无对应产品关系",
  },
  constraint_domain: {
    cost: "成本", traffic: "流量", inventory: "库存", event: "事件",
  },
  position_trend: {
    holding: "位置持稳", losing: "位置下滑", gaining: "位置上升",
    absent: "尚未覆盖",
  },
  limited_by: {
    inventory: "受库存限制", budget: "受预算限制", bid: "受竞价限制",
    none: "无限制",
  },
  review_status: { observed: "已观察", pending: "待观察", closed: "已结" },
};

// 缺映射时按字段给中性兜底，比统一的「待确认」有信息量。
// 与 compute.py 的 _FALLBACK_CN 同源。
export const FALLBACK_CN = {
  task_type: "未归类任务",
  problem_type: "未归类问题",
  direction: "待确认方向",
  task_direction: "待确认方向",
  coverage_status: "覆盖情况待确认",
  attribution_limit: "归因边界待确认",
  basis_type: "依据档位待确认",
  basis_level: "依据档位待确认",
  gap_source: "差距归类待确认",
  issue_type: "未归类结构问题",
  pressure_type: "未归类竞品压力",
  match_level: "匹配度待确认",
  judgment_mode: "判断档位待确认",
  confidence: "可信程度待确认",
  position_trend: "位置变化待确认",
  limited_by: "限制项待确认",
  review_status: "复盘状态待确认",
};

export function labelOf(obj, codeKey, labelKey, mapName) {
  const lab = labelKey && obj[labelKey];
  if (lab) return lab;
  const code = obj[codeKey];
  if (code === null || code === undefined || code === "") return "";
  // 映射名缺省就用码值的字段名 —— LOCAL_CN 的键就是按字段名建的。
  // 之前四处调用漏传第四参，结果全查不到表、全落到「待确认」兜底。
  const m = LOCAL_CN[mapName || codeKey];
  if (m && m[code]) return m[code];
  // 词表外：不摆码值，同时留个痕迹好排查
  console.warn("[ads] 缺中文映射", codeKey, code);
  return FALLBACK_CN[codeKey] || "待确认";
}

/* 直接翻一个码值（不带对象）。词表外一律不上屏。 */
export function cnOf(mapName, code, fallbackKey) {
  if (code === null || code === undefined || code === "") return "";
  const m = LOCAL_CN[mapName];
  if (m && m[code]) return m[code];
  console.warn("[ads] 缺中文映射", mapName, code);
  return FALLBACK_CN[fallbackKey || mapName] || "待确认";
}
