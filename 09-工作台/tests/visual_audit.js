/* 视觉审计 —— 用 DOM 断言替代「看一眼截图」。
 *
 * 为什么要它：读图工具在某些会话里会连续失效，而 G11 要求必须真验视觉。
 * 这里把「眼睛能发现、普通测试抓不到」的那批问题逐条做成机械判据。
 * 本项目这一路真正靠截图才发现的 bug 全部在下面有对应检查：
 *
 *   文字竖排           关键词表七列轨道塞进窄列，第一列压成一个字宽
 *   列被挤出容器       grid 用 1fr 配 nowrap，长名字顶爆轨道吞掉数字
 *   内容塌成 0×0       行内 span 给 width/height 无效
 *   整块空白           flex 列里 overflow:auto 的子项漏 min-height:0
 *   看不见的遮罩       [hidden] 被作者 display 覆盖，元素照样吃点击
 *   枚举值上屏         ACOS_UP_VS_SELF_HISTORY / derived 直接摆给客户
 *   字段错位           undefined / NaN / [object Object] / JSON 原文
 *   数字左右跳         数字列缺 tabular-nums
 *
 * 用法：把本文件内容整体贴进 browser_evaluate，或
 *       await import('/tests/visual_audit.js').then(m => m.audit())
 */

export function audit(opts = {}) {
  const scope = opts.scope ? document.querySelector(opts.scope) : document.body;
  const out = [];
  const fail = (kind, detail) => out.push({ level: "FAIL", kind, detail });
  const warn = (kind, detail) => out.push({ level: "WARN", kind, detail });
  const desc = (e) => e.tagName.toLowerCase()
    + (e.id ? "#" + e.id : "")
    + (typeof e.className === "string" && e.className.trim()
      ? "." + e.className.trim().split(/\s+/).slice(0, 2).join(".") : "");
  const vis = (e) => {
    const s = getComputedStyle(e);
    if (s.display === "none" || s.visibility === "hidden") return false;
    const r = e.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  const all = [...scope.querySelectorAll("*")].filter(vis);

  /* 1. [hidden] 必须真不可见——作者样式写了 display 会盖掉 UA 的
        [hidden]{display:none}，元素照样有几何并遮挡整页 */
  document.querySelectorAll("[hidden]").forEach((e) => {
    const s = getComputedStyle(e);
    const r = e.getBoundingClientRect();
    if (s.display !== "none" || r.width || r.height) {
      fail("hidden 元素仍有几何", `${desc(e)} display=${s.display} `
        + `${Math.round(r.width)}×${Math.round(r.height)}`);
    }
  });

  /* 2. 有内容却零尺寸 */
  all.forEach((e) => {
    if (!e.children.length && !(e.textContent || "").trim()) return;
    const r = e.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) {
      fail("内容塌成 0", `${desc(e)} "${(e.textContent || "").trim().slice(0, 24)}"`);
    }
  });

  /* 3. 子元素横向溢出容器。跳过自身可滚的容器——那是设计好的横滚。 */
  const boxes = [...scope.querySelectorAll("section,[class*=card],[class*=panel]")]
    .filter(vis);
  const overflow = new Set();
  boxes.forEach((box) => {
    const s = getComputedStyle(box);
    if (["auto", "scroll"].includes(s.overflowX)) return;
    const br = box.getBoundingClientRect();
    box.querySelectorAll("*").forEach((e) => {
      let p = e.parentElement;
      while (p && p !== box) {
        if (["auto", "scroll"].includes(getComputedStyle(p).overflowX)) return;
        p = p.parentElement;
      }
      if (!vis(e)) return;
      const r = e.getBoundingClientRect();
      const d = Math.max(r.right - br.right, br.left - r.left);
      if (d > 1.5) overflow.add(`${desc(e)} 超 ${Math.round(d)}px 于 ${desc(box)}`);
    });
  });
  [...overflow].slice(0, 6).forEach((t) => fail("元素出界", t));

  /* 4. 文字竖排：高度是行高数倍但内容只有一两个字符宽 */
  all.forEach((e) => {
    if (e.children.length) return;
    const t = (e.textContent || "").trim();
    if (!t || t.length > 40) return;
    const s = getComputedStyle(e);
    const lh = parseFloat(s.lineHeight) || parseFloat(s.fontSize) * 1.4;
    const r = e.getBoundingClientRect();
    if (r.height > lh * 2.5 && r.width < parseFloat(s.fontSize) * 2.5) {
      fail("文字竖排", `${desc(e)} "${t.slice(0, 16)}" `
        + `${Math.round(r.width)}×${Math.round(r.height)}px 行高${Math.round(lh)}`);
    }
  });

  /* 5. grid 轨道被压爆：声明了固定宽却拿不到 */
  [...scope.querySelectorAll("*")].filter((e) =>
    getComputedStyle(e).display.includes("grid") && vis(e)).forEach((g) => {
    const decl = getComputedStyle(g).gridTemplateColumns.split(/\s+/);
    [...g.children].forEach((ch, i) => {
      const want = parseFloat(decl[i]);
      if (!want || want < 20) return;
      const got = ch.getBoundingClientRect().width;
      if (got < want - 2) {
        warn("轨道被压缩", `${desc(g)} 第${i + 1}列 声明${Math.round(want)}px `
          + `实得${Math.round(got)}px`);
      }
    });
  });

  /* 6. 文字被硬裁且没有省略号兜底 */
  all.forEach((e) => {
    if (e.children.length) return;
    const s = getComputedStyle(e);
    if (s.overflowX !== "hidden" || s.textOverflow === "ellipsis") return;
    if (e.scrollWidth > e.clientWidth + 2) {
      warn("文字被硬裁", `${desc(e)} "${(e.textContent || "").trim().slice(0, 20)}"`);
    }
  });

  /* 7. 同级元素框重叠 */
  const rows = [...scope.querySelectorAll("[class*=row],tr,li")].filter(vis);
  let overlap = 0;
  rows.forEach((row) => {
    const kids = [...row.children].filter(vis);
    for (let i = 0; i + 1 < kids.length; i++) {
      const a = kids[i].getBoundingClientRect();
      const b = kids[i + 1].getBoundingClientRect();
      if (a.right > b.left + 2 && a.top < b.bottom && b.top < a.bottom) {
        overlap++;
        if (overlap <= 3) {
          fail("同级元素重叠", `${desc(row)} 第${i + 1}与第${i + 2}列 `
            + `重叠 ${Math.round(a.right - b.left)}px`);
        }
      }
    }
  });

  /* 8. 字号过小 / 文字与背景同色（看不见的文字） */
  const bg = (e) => {
    let p = e;
    while (p) {
      const c = getComputedStyle(p).backgroundColor;
      if (c && c !== "rgba(0, 0, 0, 0)" && c !== "transparent") return c;
      p = p.parentElement;
    }
    return "rgb(255, 255, 255)";
  };
  all.forEach((e) => {
    if (e.children.length || !(e.textContent || "").trim()) return;
    const s = getComputedStyle(e);
    const fs = parseFloat(s.fontSize);
    if (fs && fs < 10) {
      warn("字号过小", `${desc(e)} ${fs}px "${e.textContent.trim().slice(0, 16)}"`);
    }
    if (s.color === bg(e)) {
      fail("文字与背景同色", `${desc(e)} ${s.color}`);
    }
  });

  /* 9. 字段错位与占位符泄漏 */
  const txt = scope.innerText || "";
  [["undefined", "字段取空"], ["NaN", "数值算错"],
   ["[object Object]", "对象直接拼字符串"], ["Infinity", "除零"]]
    .forEach(([needle, why]) => {
      if (txt.includes(needle)) fail("占位符上屏", `${needle}（${why}）`);
    });
  if (/\{"[A-Za-z_]/.test(txt)) fail("JSON 原文上屏", "有未格式化的载荷");

  /* 10. 内部枚举值上屏：全大写下划线，或库里常见的小写枚举 */
  const enums = new Set();
  (txt.match(/\b[A-Z][A-Z0-9]*(_[A-Z0-9]+){1,}\b/g) || [])
    .forEach((m) => enums.add(m));
  ["value_origin", "report_month_total", "self_history", "confirmed_rule",
   "replenishment_gap", "aged_inventory_risk", "overstock",
   "promoted_asin", "positive_spend_asin", "metric_basis"]
    .forEach((k) => { if (txt.includes(k)) enums.add(k); });
  [...enums].slice(0, 8).forEach((m) => fail("枚举值上屏", m));

  /* 11. 数字列缺 tabular-nums，上下行小数点对不齐 */
  const numish = [...scope.querySelectorAll("[class*=num],[class*=tnum],td")]
    .filter(vis).filter((e) => /[\d,.]{3,}/.test(e.textContent || ""));
  const noTab = numish.filter((e) =>
    !getComputedStyle(e).fontVariantNumeric.includes("tabular-nums"));
  if (noTab.length) {
    warn("数字列缺 tabular-nums",
      `${noTab.length}/${numish.length} 个，例 ${desc(noTab[0])}`);
  }

  /* 12. 表格行高是否一致（参差说明某列在换行） */
  const groups = {};
  rows.forEach((r) => {
    const k = r.className || r.tagName;
    (groups[k] = groups[k] || []).push(Math.round(
      r.getBoundingClientRect().height));
  });
  Object.entries(groups).forEach(([k, hs]) => {
    if (hs.length < 4) return;
    const lo = Math.min(...hs), hi = Math.max(...hs);
    if (hi > lo * 1.8) {
      warn("行高参差", `${k} 最低${lo}px 最高${hi}px（${hs.length} 行）`);
    }
  });

  const f = out.filter((x) => x.level === "FAIL");
  const w = out.filter((x) => x.level === "WARN");
  return {
    verdict: f.length ? "FAIL" : (w.length ? "PASS_WITH_WARN" : "PASS"),
    fail: f.length, warn: w.length,
    checked: all.length,
    page_height: document.documentElement.scrollHeight,
    items: out.slice(0, 30),
  };
}
