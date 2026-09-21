/* 面料预投模块 · 小工具
 *
 * 数字格式化保留本地实现：ctx.fmt 是外壳的通用档位，而预投这条链上
 * 「盒」是整数、「吨」要两位小数、「达成率」是百分比且 100% 附近要看得出差别
 * （97.6% 和 99.5% 是两种情况），统一档位会把这些揉平。
 */

const NF0 = new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 0 });
const NF1 = new Intl.NumberFormat('zh-CN', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const NF2 = new Intl.NumberFormat('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export const n0 = (v) => (v === null || v === undefined || Number.isNaN(v) ? '—' : NF0.format(v));
export const n1 = (v) => (v === null || v === undefined || Number.isNaN(v) ? '—' : NF1.format(v));
export const n2 = (v) => (v === null || v === undefined || Number.isNaN(v) ? '—' : NF2.format(v));

/* 达成率用一位小数：97.6% 与 99.5% 是两种情况，取整会把它们揉成同一个 98%。 */
export const pc = (v) => (v === null || v === undefined || Number.isNaN(v)
  ? '—' : NF1.format(v * 100) + '%');

/* 带符号，用于差额。0 不写 +0，写 0。 */
export const sgn = (v) => {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  if (v === 0) return '0';
  return (v > 0 ? '+' : '−') + NF0.format(Math.abs(v));
};

/* ⓘ 点开说明。内容进 data-pop（URI 编码），由入口文件的委托监听转给 ctx.pop。
   方法说明收进这里而不是写成正文一行字（契约 §11 文案类第三条）。 */
export const info = (html) =>
  `<button class="pre-i" type="button" data-pop="${encodeURIComponent(html)}"
    aria-label="查看说明" title="查看说明">ⓘ</button>`;

/* 数据性质徽标。只用 6.6 词表里的四个词，映射发生在这里而不是页面里。
   value_origin 的英文码值永远不上屏（G17）。 */
const NATURE_CN = { direct: '真实', derived: '推导', constructed: '模拟', mixed: '混合' };
export const nature = (kind) => {
  const cn = NATURE_CN[kind] || kind;
  if (!Object.values(NATURE_CN).includes(cn)) return '';
  return `<span class="pre-nature" data-nature="${cn}">${cn}</span>`;
};

/* 数据状态徽标。同样只认 6.6 的词表。 */
const STATE_WORDS = new Set(['正常', '加载中', '空结果', '过期', '缺失', '待确认', '失败']);
export const state = (word) =>
  STATE_WORDS.has(word) ? `<span class="pre-state" data-state="${word}">${word}</span>` : '';

/* 板块外壳。标题 + 右上角挂件 + 正文。 */
export const sec = (title, tools, body) =>
  `<section class="pre-sec"><div class="pre-sechead">
     <h2>${title}</h2><div class="pre-sectools">${tools || ''}</div></div>
   <div class="pre-secbody">${body}</div></section>`;

/* 一行「标签 — 数字」，给侧栏和摘要用。 */
export const kv = (label, value, title) =>
  `<div class="pre-kv"${title ? ` title="${title}"` : ''}>
     <span class="k">${label}</span><span class="v">${value}</span></div>`;

/* 水平比例条。宽度用 style 写在 block 元素上 ——
   行内 span 给 width 是无效的，会塌成 0×0（库龄柱状图踩过，已加门禁）。 */
export const bar = (ratio, cls) => {
  const w = Math.max(0, Math.min(1, ratio || 0)) * 100;
  return `<span class="pre-bar"><span class="fill ${cls || ''}" style="width:${w.toFixed(2)}%"></span></span>`;
};
