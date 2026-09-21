/* 广告分析模块 · 页面二（单一子 ASIN 广告决策）
 *
 * 施工单：04-广告分析模块/01-方案与数据需求/07-页面二屏幕决策设计.md
 *
 * 六个板块 = 王楠说的那条链，一节都不混：
 *   决策条  结论先行的四个大数字
 *   ① 市场需求与竞争    事实，Agent 跑之前就存在
 *   ② 本品广告事实      事实
 *   ③ 本品判断          Agent（B0b / B0cd / B0e / B3 / B3b）
 *   ④ 策略建议与审批    Agent（B4）+ 人
 *   ⑤ 执行后效果监控    事后事实（复盘记录），没有就如实说没有
 *   ⑥ 决策沿革与回测    版本沿革 + 回测未接入的接入位
 *
 * 长文一律收进 ⓘ，卡面只放首句 —— 这是这次重构最主要的一刀。
 */

import {
  barRows, chain, coverageGrid, deltaRows, dilution, esc, fmtKind, fmtNum,
  fmtOne, fmtPct, fmtUsd, matrix, rankSlope, signPct, timeline,
} from "./charts.js";
import {
  cnOf, firstSentence, infoBtn, isTruncated, labelOf, popText, subhead, usd,
} from "./util.js";

/* 一个板块的外壳。标题 / 副题 / ⓘ / 右侧插件 / 正文。 */
function sec(c, opts, body) {
  const head = c.el("div", { class: "ads-secthead" }, [
    c.el("h2", { class: "ads-h2" },
      [opts.no ? c.el("i", { class: "ads-secno" }, opts.no) : null,
       opts.title,
       opts.ai ? c.aiMark(opts.ai) : null,
       opts.scheme ? c.schemePicker(opts.scheme) : null].filter(Boolean)),
    opts.note ? c.el("span", { class: "ads-mut" }, opts.note) : null,
    opts.info ? infoBtn(c, opts.title, opts.info) : null,
    opts.right || null,
  ].filter(Boolean));
  return c.el("section", { class: "ads-card" + (opts.cls ? " " + opts.cls : "") },
    [head].concat([].concat(body).filter(Boolean)));
}

/* 一格大数字。kind=num 走 --fs-num，kind=word 走 --fs-value（文字型）。
   要则第一节：页面里最大的东西应该是数字，文字型的值降一档。 */
function statCell(c, label, value, foot, kind, tone) {
  return c.el("div", { class: "ads-st" }, [
    c.el("div", { class: "ads-st-l" }, label),
    c.el("div", { class: "ads-st-v" + (kind === "word" ? " ads-st-word" : "")
      + (tone ? " ads-t-" + tone : "") }, value),
    foot ? c.el("div", { class: "ads-st-f" }, foot) : null,
  ].filter(Boolean));
}

function svgBox(c, html, cls) {
  return c.el("div", { class: cls || "ads-fig", html });
}

/* 一句话 + ⓘ 全文。长文只在这里落地。 */
function saying(c, text, popTitle, full) {
  const row = c.el("div", { class: "ads-say" },
    [c.el("span", {}, firstSentence(text))]);
  if (isTruncated(text) || (full && full !== text)) {
    row.appendChild(infoBtn(c, popTitle || "完整说明", full || text));
  }
  return row;
}

/* ================================================================ 决策条 */

export function heroBar(c, d, run, onVersion) {
  const x = d.context;
  const r = d.readiness || {};
  const pts = (run && run.points) || {};
  const diag = pts.B3 || [];
  const props = pts.B4 || [];
  const struct = d.existing_structure || [];
  const shared = struct.filter((s) => s.is_shared).length;
  const p1 = diag.filter((y) => (y.priority || "") === "P1").length;

  const modeTone = r.mode === "正式判断" ? "good"
    : r.mode === "条件性判断" ? "warn" : "alert";

  const stats = c.el("div", { class: "ads-stats" }, [
    statCell(c, "本期诊断", run && run.run_id ? String(diag.length) : "—",
      run && run.run_id ? (p1 ? `其中最高优先级 ${p1} 条` : "无最高优先级")
        : "尚未运行 Agent"),
    statCell(c, "待办建议", run && run.run_id ? String(props.length) : "—",
      run && run.run_id ? "点开每条可审批" : "尚未运行 Agent"),
    statCell(c, "广告对象", String(struct.length),
      shared ? `${shared} 个与其他子 ASIN 共享归因` : "全部独占"),
    statCell(c, "判断档位", r.mode || "—",
      x.goal_confirmed_label === "已确认" ? "产品目标已确认"
        : "产品目标待运营确认", "word", modeTone),
  ]);

  // 版本切换。当前版加粗不可点，历史版可点切过去。
  const vers = c.el("div", { class: "ads-vers" },
    [c.el("span", { class: "ads-mut" }, "决策版本 ")]);
  (d.versions || []).forEach((v, i) => {
    if (i) vers.appendChild(c.el("span", { class: "ads-mut" }, " · "));
    if (v.is_current) {
      vers.appendChild(c.el("b", { class: "num" }, v.decision_at));
    } else {
      const a = c.el("button", { class: "ads-ref", type: "button" },
        v.decision_at);
      a.addEventListener("click", () => onVersion(v.decision_id));
      vers.appendChild(a);
    }
  });

  const stamp = [];
  if (run && run.run_id) {
    stamp.push(c.el("span", { class: "ads-hr-stamp num" },
      "跑于 " + String(run.completed_at || run.created_at || "")
        .slice(0, 16).replace("T", " ")));
    if (run.model_version) {
      stamp.push(c.el("span", { class: "ads-hr-model" }, run.model_version));
    }
    if (run.seam_bypass) {
      stamp.push(c.el("span", { class: "ads-chip ads-chip-alert" },
        "接缝联调旁路 · 非有效结论"));
    }
    if ((run.pending_points || []).length) {
      stamp.push(c.el("span", { class: "ads-chip ads-chip-warn" },
        "还缺 " + run.pending_points.length + " 个输出点"));
    }
  } else if (run && run.message) {
    stamp.push(c.el("span", { class: "ads-chip ads-chip-warn" }, run.message));
  }

  return c.el("section", { class: "ads-card ads-hero" }, [
    c.el("div", { class: "ads-hr-id" }, [
      c.el("div", { class: "ads-hr-asin" }, [
        c.el("b", {}, x.child_asin),
        c.el("span", { class: "ads-hr-parent num" },
          "父体 " + (x.parent_asin || "—")),
      ]),
      c.el("div", { class: "ads-hr-goal" }, x.product_goal || "—"),
      c.el("div", { class: "ads-hr-meta" }, [
        x.goal_type_label
          ? c.el("span", { class: "ads-chip ads-chip-calm" }, x.goal_type_label)
          : null,
        c.el("span", { class: "ads-mut num" },
          "观察窗口 " + (x.observe_window_start || "—") + " — "
          + (x.observe_window_end || "—")),
      ].filter(Boolean)),
      (r.notes || []).length
        ? saying(c, (r.notes || []).join("；"), "判断为什么停在这一档",
          (r.notes || []).concat(r.blockers || []).join("\n"))
        : null,
    ].filter(Boolean)),
    stats,
    c.el("div", { class: "ads-hr-run" }, [vers].concat(stamp)),
  ]);
}

/* 证据卡。当某一栏抽不出结构化事实时，至少把"有哪几条证据"如实列出来 ——
   比写「本对象没有市场侧证据」诚实：证据存在，只是这条链的 payload 形状
   不同、抽不出可画图的字段。
   **不渲染 payload 的键**：那些是库里的英文列名，上屏违反 G9。 */
function evCard(c, e) {
  return c.el("div", { class: "ads-evc" }, [
    c.el("b", {}, e.evidence_title || e.evidence_id),
    c.el("span", { class: "ads-chip ads-chip-calm" }, e.nature || ""),
    e.observed_at
      ? c.el("span", { class: "ads-mut num" }, e.observed_at) : null,
    e.condition && e.condition !== "正常"
      ? c.el("span", { class: "ads-chip ads-chip-warn" }, e.condition) : null,
    e.caveat ? c.el("span", { class: "ads-evc-c" }, e.caveat) : null,
  ].filter(Boolean));
}

/* ================================================ ① 市场需求与竞争（事实） */

export function sectionMarket(c, d) {
  const v = d.view || {};
  const facts = v.facts || {};
  const kws = d.keywords || [];
  const body = [];

  // 1a 核心词需求与本品位置
  if (kws.length) {
    const maxS = Math.max(...kws.map((k) => k.monthly_search || 0), 1);
    const head = `<div class="ads-kw ads-kw-head">
      <span class="ads-kw-n">核心需求词</span>
      <span class="ads-kw-s">月搜索量</span>
      <span class="ads-kw-r">自然位变化</span>
      <span class="ads-kw-a">广告位</span>
      <span class="ads-kw-i">广告展示份额</span>
      <span class="ads-kw-c">承接</span></div>`;
    const rows = kws.map((k) => {
      const sw = ((k.monthly_search || 0) / maxS * 100).toFixed(2);
      const iw = ((k.ad_impression_share || 0) * 100).toFixed(2);
      const trend = cnOf("position_trend", k.position_trend);
      const lim = k.limited_by && k.limited_by !== "none"
        ? cnOf("limited_by", k.limited_by) : "";
      return `<div class="ads-kw">
        <span class="ads-kw-n"><b>${esc(k.keyword)}</b>
          <em>${esc(k.match_label || cnOf("match_level", k.match_level))}${
            lim ? " · " + esc(lim) : ""}</em></span>
        <span class="ads-kw-s"><span class="ads-br-t"><span
          class="ads-br-f" style="width:${sw}%"></span></span>
          <b class="num">${esc(fmtNum(k.monthly_search))}</b></span>
        <span class="ads-kw-r">${rankSlope(k.organic_rank_prev,
          k.organic_rank)}<em>${esc(trend)}</em></span>
        <span class="ads-kw-a num">${k.ad_rank === null
          || k.ad_rank === undefined ? "—" : esc(k.ad_rank)}</span>
        <span class="ads-kw-i"><span class="ads-br-t"><span
          class="ads-br-f ads-t-calm" style="width:${iw}%"></span></span>
          <b class="num">${esc(fmtPct(k.ad_impression_share))}</b></span>
        <span class="ads-kw-c">${k.covered_by_ad
          ? '<i class="ads-dotf"></i>已覆盖'
          : '<i class="ads-doth"></i>未覆盖'}</span></div>`;
    }).join("");
    body.push(svgBox(c, head + rows, "ads-kwtbl"));
    body.push(c.el("div", { class: "ads-lg" }, [
      c.el("span", {}, "自然位越小越好，所以斜线向上代表位置变好"),
      c.el("span", {}, "● 广告已覆盖　○ 未覆盖"),
    ]));
  }

  // 1b 搜索词展示份额
  const sh = facts.share;
  if (sh && (sh.terms || []).length) {
    body.push(subhead(c, "搜索词展示份额（按展示量降序）"));
    const maxI = Math.max(...sh.terms.map((t) => t.impressions || 0), 1);
    body.push(svgBox(c, barRows(sh.terms.map((t) => ({
      label: t.term,
      sub: t.rank ? `展示位次 ${t.rank}` : "",
      share: (t.impressions || 0) / maxI,
      text: fmtPct(t.share),
      badge: fmtNum(t.impressions) + " 次展示",
    })), { dense: true })));
    if (sh.caveat) {
      body.push(c.el("div", { class: "ads-cav" }, sh.caveat));
    }
  }

  // 1c 竞品压力矩阵
  const pm = v.pressure;
  if (pm && (pm.rows || []).length) {
    body.push(subhead(c, "竞品压力（品牌 × 压力类型）"));
    body.push(svgBox(c, matrix(pm.cols, pm.rows)));
    const detail = (d.competitor || [])
      .map((p) => `${p.brand || p.competitor_asin}｜${p.type_label
        || cnOf("pressure_type", p.pressure_type)}：${p.detail || ""}`)
      .join("\n");
    if (detail) {
      body.push(c.el("div", { class: "ads-fold" }, [
        infoBtn(c, "竞品压力逐条", detail),
        c.el("span", { class: "ads-mut" },
          `逐条说明 ${(d.competitor || []).length} 条`),
      ]));
    }
  }

  if (!body.length) {
    // 抽不出可画图的字段不等于没有证据。把市场侧证据如实列出来，
    // 而不是说「本对象没有市场侧证据」—— 两条决策链的 payload 形状不同，
    // 这一条的关键词证据是数组、竞品证据在另一张表，都抽不出图但确实存在。
    const mkt = (d.evidence || []).filter((e) => e.board === "market");
    if (mkt.length) {
      body.push(c.el("div", { class: "ads-hint" },
        "这条决策链的市场证据形状不同，抽不出可画图的字段，"
        + "所以这里只列出证据本身："));
      mkt.forEach((e) => body.push(evCard(c, e)));
    } else {
      body.push(c.el("div", { class: "ads-hint" }, "本对象没有市场侧证据"));
    }
  }

  return sec(c, {
    no: "①", title: "市场需求与竞争",
    note: `${kws.length} 个核心词 · ${(d.competitor || []).length} 类竞品压力`,
    info: "这一屏全是事实，Agent 跑之前就存在，页面不在这里做任何判断。\n"
      + "自然位与广告位越小越好；斜线向上代表名次变小、位置变好。\n"
      + "展示份额是相对同类广告的位置，不是绝对量。\n"
      + "不画竞品价格带：价格只存在于文字说明里，事实层没有结构化的价格列，"
      + "从文字里抽数字画图等于把判断当数据源。",
  }, body);
}

/* ============================================== ② 本品广告事实（事实层） */

export function sectionOwnFacts(c, d, mountDaily) {
  const v = d.view || {};
  const facts = v.facts || {};
  const body = [];

  // 2a 归因两口径并排 —— 绝不给跨桶合计
  const buckets = v.attribution || [];
  if (buckets.length) {
    const cols = buckets.map((b) => {
      const cells = [
        statCell(c, "花费", usd(b.spend, 0)),
        statCell(c, "广告销售额", usd(b.ad_sales, 0)),
        statCell(c, "ACoS", fmtPct(b.acos), null, "word"),
        statCell(c, "ROAS", b.roas === null || b.roas === undefined
          ? "—" : Number(b.roas).toFixed(2), null, "word"),
      ];
      const ch = chain([
        { label: "曝光", text: fmtNum(b.impressions) },
        { label: "点击", text: fmtNum(b.clicks),
          gapLabel: "点击率", gapText: fmtPct(b.ctr) },
        { label: "订单", text: fmtNum(b.orders),
          gapLabel: "转化率", gapText: fmtPct(b.cvr),
          gapTone: b.ratio_impossible ? "alert" : "" },
      ]);
      const kids = [
        c.el("div", { class: "ads-bk-h" }, [
          c.el("b", {}, b.label),
          c.el("span", { class: "ads-mut" },
            `${b.ad_types.join(" / ") || "—"} · ${b.object_count} 个对象`),
        ]),
        c.el("div", { class: "ads-stats ads-stats-4" }, cells),
        svgBox(c, ch),
      ];
      if (b.ratio_impossible) {
        kids.push(c.el("div", { class: "ads-warnline" },
          "这一桶的订单数超过点击数，转化率在算术上不成立 —— "
          + "分子与分母不是同一批流量，说明整桶指标被当成了单品归因。"));
      }
      kids.push(svgBox(c, dilution(b.max_shared)));
      return c.el("div", { class: "ads-bk" }, kids);
    });
    body.push(c.el("div", { class: "ads-bks" }, cols));
    body.push(c.el("div", { class: "ads-warnline ads-warnline-flat" },
      "两个归因窗口的口径不同，不可相加，所以这里不给合计数。"));
  }

  // 2b 归因边界：成交归属但非推广
  const pg = facts.purchase_gap;
  if (pg && pg.objects) {
    const own = (buckets.reduce((s, b) => s + (b.spend || 0), 0)) || null;
    body.push(subhead(c, "成交归属到本品、但推的不是本品"));
    body.push(c.el("div", { class: "ads-stats ads-stats-3" }, [
      statCell(c, "这样的广告对象", fmtNum(pg.objects) + " 个"),
      statCell(c, "它们的花费", usd(pg.spend, 0),
        own ? `本品自己的广告花费合计 ${usd(own, 0)}` : ""),
      statCell(c, "它们的广告销售额", usd(pg.ad_sales, 0),
        pg.caveat || ""),
    ]));
  }

  // 2c/2d 销量趋势与库存承接并排 —— 两块都是"本品自己的量"，
  // 竖着堆会各占一整行，横排一屏能一起看到（要则第四节：节奏按 0.8 倍收）
  const tr = facts.trend;
  const inv = facts.inventory;
  const twoCols = [];
  if (tr && (tr.bars || []).length) {
    const maxV = Math.max(...tr.bars.map((b) => b.value || 0), 1);
    twoCols.push(c.el("div", { class: "ads-half" }, [
      subhead(c, "销量趋势 · 六个嵌套窗口的日均"),
      svgBox(c, barRows(tr.bars.map((b) => ({
        label: b.label,
        share: b.value === null ? null : (b.value || 0) / maxV,
        text: fmtOne(b.value) + " 件/天",
      })), { dense: true })),
      c.el("div", { class: "ads-lg" }, [
        c.el("span", {}, tr.caveat || ""),
        tr.short_vs_long === null || tr.short_vs_long === undefined ? null
          : c.el("span", { class: tr.short_vs_long < 0 ? "ads-t-warn" : "" },
            `近 3 天日均相对近 90 天 ${signPct(tr.short_vs_long)}`),
      ].filter(Boolean)),
    ]));
  }
  if (inv) {
    twoCols.push(c.el("div", { class: "ads-half" }, [
      subhead(c, "库存承接"),
      c.el("div", { class: "ads-stats ads-stats-4" }, [
        statCell(c, "当前可售", fmtNum(inv.sellable)),
        statCell(c, "在途", fmtNum(inv.inbound)),
        statCell(c, "覆盖天数", inv.coverage_days === null
          ? "—" : fmtOne(inv.coverage_days),
          inv.safety_days ? `安全库存 ${fmtNum(inv.safety_days)} 天` : ""),
        statCell(c, "建议补货", inv.suggested_qty === null
          ? "—" : fmtNum(inv.suggested_qty) + " 件"),
      ]),
    ]));
  }
  if (twoCols.length) {
    body.push(c.el("div", { class: "ads-two" }, twoCols));
  }

  // 库存关键日期轴单独占一行 —— 标注是两行文字，挤在半栏里会互相压字
  if (inv) {
    const asOf = inv.observed_at || c.asOf;
    const marks = [];
    if (inv.latest_order_date) {
      const past = asOf && inv.latest_order_date < asOf;
      marks.push({ date: inv.latest_order_date,
        label: past ? "最晚下单日（已过）" : "最晚下单日",
        tone: past ? "alert" : "warn" });
    }
    if (asOf) marks.push({ date: asOf, label: "数据基准日", shape: "hollow" });
    if (inv.safety_breach_date) {
      marks.push({ date: inv.safety_breach_date, label: "安全线突破",
        tone: "warn" });
    }
    if (inv.base_stockout_date) {
      marks.push({ date: inv.base_stockout_date, label: "基准断货",
        tone: "alert" });
    }
    if (inv.stress_stockout_date) {
      marks.push({ date: inv.stress_stockout_date, label: "压力断货",
        tone: "alert" });
    }
    if (marks.length > 1) {
      body.push(svgBox(c, timeline(marks, { note: inv.caveat || "" }),
        "ads-fig ads-fig-tl"));
    }
  }

  // 2e 逐日趋势
  const dl = v.daily || {};
  if ((dl.objects || []).length) {
    const o = dl.objects[0];
    body.push(subhead(c, `逐日趋势 · ${o.name}`));
    body.push(c.el("div", { class: "ads-mut" },
      `${o.ad_type || ""} ${o.attribution_days ? o.attribution_days + " 天归因" : ""}`
      + ` · ${o.days} 天 · 口径「${dl.basis_label}」`));
    body.push(c.el("div", { class: "ads-daymount" }));
  }
  if ((dl.no_daily || []).length) {
    body.push(c.el("div", { class: "ads-hint" },
      "这些对象没有逐日记录，不画空图："
      + dl.no_daily.map((x) => x.name).join("、")));
  }

  // 2f 广告对象清单。行可被 ③ 的「定位对象」高亮，所以带 data-oid。
  // 按花费降序只出前 10：实测有对象多到 24 个，全列会让这一张表
  // 独占一屏，而后面 20 行的花费都在尾部。要看全的走页面一。
  const allRows = d.existing_structure || [];
  const CAP = 10;
  const rows = allRows.slice(0, CAP);
  if (allRows.length) {
    body.push(subhead(c, `广告对象 ${allRows.length} 个`
      + (allRows.length > CAP ? `（按花费降序取前 ${CAP}）` : "")));
    const head = ["广告对象", "类型", "广告目的", "共享", "花费",
                  "广告销售额", "ACoS", "ROAS", "点击", "订单"];
    const tbl = c.el("div", { class: "ads-table" }, [
      c.el("div", { class: "ads-trow ads-thead" },
        head.map((t, i) => c.el("div",
          { class: "ads-td" + (i >= 4 ? " ads-tnum" : "") }, t))),
    ]);
    rows.forEach((r) => {
      tbl.appendChild(c.el("div",
        { class: "ads-trow", "data-oid": r.ad_object_id }, [
          c.el("div", { class: "ads-td" }, [
            c.el("b", {}, r.name || ""),
            c.el("em", {}, (r.level_label || "")
              + (r.attribution_days
                ? " · 归因 " + r.attribution_days + " 天" : "")),
          ]),
          c.el("div", { class: "ads-td" }, r.ad_type || "—"),
          c.el("div", { class: "ads-td" },
            [c.el("span", { class: "ads-tag" },
              (r.purpose || "—").split(",")[0])]),
          c.el("div", { class: "ads-td" },
            r.is_shared ? String(r.shared_child_count) : "独占"),
          c.el("div", { class: "ads-td ads-tnum" }, usd(r.spend, 0)),
          c.el("div", { class: "ads-td ads-tnum" }, usd(r.ad_sales, 0)),
          c.el("div", { class: "ads-td ads-tnum" }, fmtPct(r.acos)),
          c.el("div", { class: "ads-td ads-tnum" },
            r.roas === null || r.roas === undefined
              ? "—" : Number(r.roas).toFixed(2)),
          c.el("div", { class: "ads-td ads-tnum" }, fmtNum(r.clicks)),
          c.el("div", { class: "ads-td ads-tnum" }, fmtNum(r.orders)),
        ]));
    });
    body.push(c.el("div", { class: "ads-tablewrap" }, [tbl]));
    if (allRows.length > CAP) {
      // 「定位对象」可能指向被截掉的行，所以要说清它去哪了
      body.push(c.el("div", { class: "ads-hint" },
        `另有 ${allRows.length - CAP} 个花费更低的对象没有列出，`
        + "在「广告分类与数据查看」里可以按标签筛选查看全部。"));
    }
  }

  const s = sec(c, {
    no: "②", title: "本品广告事实",
    note: `${(d.existing_structure || []).length} 个广告对象`,
    info: "这一屏也全是事实。\n"
      + "两个归因窗口（SP 7 天、SD/SB 14 天）口径不同不可相加，所以分两块显示，"
      + "不给一个跨口径的合计数。\n"
      + "六窗口是嵌套累计值：近 3 天那格是最近 3 天的日均，不是第 1–3 天。"
      + "短窗低于长窗就是在走低。\n"
      + "逐日只能从搜索词报表拿到，两种口径算出的环比变化率相同、只有水平值不同，"
      + "由「日粒度口径」参数选一种，不求和。",
  }, body);
  if ((dl.objects || []).length) mountDaily(s.querySelector(".ads-daymount"), dl);
  return s;
}

/* ================================================== ③ 本品判断（Agent） */

const PRI_TONE = { P0: "alert", P1: "alert", P2: "warn", P3: "" };

export function sectionJudgment(c, d, run, onFlash) {
  const v = d.view || {};
  const pts = (run && run.points) || {};
  const body = [];
  const hasRun = !!(run && run.run_id);

  if (!hasRun) {
    body.push(c.el("div", { class: "ads-hint" },
      (run && run.message) || "这个子 ASIN 还没有完成一次 Agent 运行，"
      + "所以没有判断。事实层（① ②）不依赖 Agent，照常显示。"));
    return sec(c, { no: "③", title: "本品判断", ai: "广告异常与决策",
      scheme: "广告异常与决策", note: "未运行" }, body);
  }

  // 3a 诊断结论带
  const diag = pts.B3 || [];
  if (diag.length) {
    const rows = diag.map((y) => {
      const name = labelOf(y, "problem_type", "problem_label");
      const pri = y.priority || "";
      const full = [
        y.what_happened ? "发生了什么\n" + y.what_happened : "",
        y.check_direction ? "\n\n下一步核查\n" + y.check_direction : "",
        y.missing_input ? "\n\n缺什么输入\n" + y.missing_input : "",
        y.uncertainty ? "\n\n不确定项\n" + y.uncertainty : "",
      ].join("");
      const row = c.el("div", { class: "ads-vd" }, [
        c.el("i", { class: "ads-vd-dot"
          + (PRI_TONE[pri] ? " ads-t-" + PRI_TONE[pri] : "") }),
        c.el("span", { class: "ads-vd-pri" }, pri || "—"),
        c.el("b", { class: "ads-vd-name" }, name),
        c.el("span", { class: "ads-vd-say" },
          firstSentence(y.what_happened, 92)),
        c.el("span", { class: "ads-vd-conf" },
          "可信 " + labelOf(y, "confidence", null, "confidence")),
        infoBtn(c, name, full),
      ]);
      if (y.task_id) {
        row.setAttribute("data-task", y.task_id);
      }
      return row;
    });
    body.push(c.el("div", { class: "ads-vds" }, rows));
  } else {
    body.push(c.el("div", { class: "ads-hint" },
      "本次运行没有产出诊断条目。"));
  }

  // 3b 诊断覆盖
  const cov = run.diagnosis_coverage || pts.B3b || [];
  if (cov.length) {
    const hit = cov.filter((x) => x.hit).length;
    body.push(subhead(c, `逐项核对了 ${cov.length} 类问题，本次命中 ${hit} 类`));
    body.push(svgBox(c, coverageGrid(cov.map((x) => ({
      ...x,
      problem_label: x.problem_label
        || cnOf("problem_type", x.problem_type),
    })))));
    body.push(c.el("div", { class: "ads-lg" }, [
      c.el("span", {}, "▲ 本次命中　· 查过但本次未命中（悬停看原因）"),
    ]));
  }

  // 3c 目标约束四域
  const doms = v.constraint_domains || [];
  const agentCons = pts.B0b || null;
  if (doms.length) {
    body.push(subhead(c, "目标约束"
      + (agentCons ? "（本次分析判定）" : "")));
    const cells = doms.map((dm) => {
      const rows = agentCons
        ? agentCons.filter((x) => (x.domain || "") === dm.key)
        : dm.rows;
      const hard = rows.filter((x) => x.kind === "hard").length;
      const kids = [
        c.el("div", { class: "ads-cd-h" }, [
          c.el("b", {}, dm.label),
          c.el("span", { class: "ads-mut" }, rows.length
            ? (hard ? `${hard} 硬性 / ${rows.length - hard} 观察`
              : `${rows.length} 项观察`)
            : "本期无"),
        ]),
      ];
      rows.forEach((x) => {
        const line = c.el("div", { class: "ads-cd-i" }, [
          c.el("i", { class: "ads-cd-k"
            + (x.kind === "hard" ? " ads-t-alert" : "") },
            x.kind === "hard" ? "硬" : "观"),
          c.el("span", {}, x.label || ""),
        ]);
        if (x.detail) line.appendChild(infoBtn(c, x.label || "约束", x.detail));
        kids.push(line);
      });
      if (!rows.length) {
        kids.push(c.el("div", { class: "ads-cd-none" }, "—"));
      }
      return c.el("div", { class: "ads-cd" }, kids);
    });
    body.push(c.el("div", { class: "ads-cds" }, cells));
  }

  // 3d 结构问题
  const issues = pts.B0e || d.structure_issues || [];
  if (issues.length) {
    body.push(subhead(c, `结构问题 ${issues.length} 处`));
    issues.forEach((x) => {
      const name = labelOf(x, "issue_type", "type_label", "issue_type");
      const row = c.el("div", { class: "ads-iss" }, [
        c.el("span", { class: "ads-chip ads-chip-warn" }, name),
        c.el("span", { class: "ads-iss-say" }, firstSentence(x.label, 96)),
        infoBtn(c, name, (x.label || "") + "\n\n" + (x.detail || "")),
      ]);
      if (x.ad_object_id) {
        const j = c.el("button", { class: "ads-ref", type: "button" }, "定位对象");
        j.addEventListener("click", () => onFlash(x.ad_object_id));
        row.appendChild(j);
      }
      body.push(row);
    });
  }

  return sec(c, {
    no: "③", title: "本品判断", ai: "广告异常与决策",
    scheme: "广告异常与决策",
    note: `${diag.length} 条诊断 · ${(pts.B0e || []).length} 处结构问题`,
    info: "这一屏是 Agent 的判断，不是事实。\n"
      + "每条只在卡面放第一句，全文点 ⓘ 看 —— 页面不改写 Agent 的任何一句话。\n"
      + "覆盖网格里没命中的那些也是结论：Agent 查过并说明了为什么不算。",
  }, body);
}

/* ========================================== ④ 策略建议与审批（Agent + 人） */

/* 标准化字段表。字段顺序与中文标签由后端 proposal_schema.FIELDS 定，
   这里只排版 —— 前端不许另排一次顺序，排两次就有两个真相来源。

   会上原话决定的骨架（00:36:42「我把动作、原因、然后预期结果都列出来之后，
   给到人去做审批」）：三栏就叫动作 / 原因 / 预期结果，字段按语义分进三栏。 */
const FIELD_COL = {
  act: ["target", "lever", "from_to", "delta", "goal"],
  why: ["guard"],
  exp: ["time_threshold", "volume_threshold", "trigger_rule",
        "pass_rule", "on_fail", "origin"],
};

/* 一格字段。值是「本次运行未给出」时压低显示 —— 要看得见，但不抢戏。
   这一格空着本身是信息：它是 Agent 侧下一步要补的输出点。 */
function fieldRow(c, label, value) {
  const miss = value === "本次运行未给出"
    || String(value || "").startsWith("规则未确认");
  return c.el("div", { class: "ads-fr" + (miss ? " ads-fr-miss" : "") }, [
    c.el("dt", {}, label),
    c.el("dd", {}, value === null || value === undefined || value === ""
      ? "本次运行未给出" : String(value)),
  ]);
}

function fieldGrid(c, keys, labels, fields) {
  const g = c.el("dl", { class: "ads-fg" });
  keys.forEach((k) => {
    if (!(k in fields)) return;
    g.appendChild(fieldRow(c, labels[k] || k, fields[k]));
  });
  return g;
}

/* 监控指标表：指标 / 基准值 / 目标值 三列。
   会上原话 00:40:39「这几个数指标都是要监控的指标」——所以它是表不是一句话。
   Agent 现在给的是一串句子，没有基准与目标两列，那两格就显示未给出。 */
function watchTable(c, watch) {
  const t = c.el("div", { class: "ads-wt" }, [
    c.el("div", { class: "ads-wt-r ads-wt-head" }, [
      c.el("span", {}, "监控指标"), c.el("span", {}, "基准值"),
      c.el("span", {}, "目标值"),
    ]),
  ]);
  (watch || []).forEach((w) => {
    const miss = (v) => v === "本次运行未给出";
    t.appendChild(c.el("div", { class: "ads-wt-r" }, [
      c.el("span", {}, w.metric),
      c.el("span", { class: miss(w.baseline) ? "ads-fr-miss" : "" },
        w.baseline),
      c.el("span", { class: miss(w.target) ? "ads-fr-miss" : "" }, w.target),
    ]));
  });
  return t;
}

/* 一条建议 = 一张卡。**Agent 产出与模板示例走的是这同一个函数**，
   所以形式上不可区分；来源写在字段表最后一行「产出来源」里，
   要能审计，但不靠视觉上把它隔离出去。 */
function proposalCard(c, r, labels, ctxData, state, cb, onFlash) {
  const dir = labelOf({ direction: r.direction_code }, "direction",
    null, "direction");
  const diagName = ctxData.diagName || {};

  const act = c.el("div", { class: "ads-pc-col ads-pc-act" }, [
    c.el("div", { class: "ads-pc-cl" }, "动作"),
    c.el("div", { class: "ads-pc-dir" }, dir),
    fieldGrid(c, FIELD_COL.act, labels, r.fields),
  ]);
  const whyKids = [
    c.el("div", { class: "ads-pc-cl" }, "原因"),
    r.reason ? saying(c, r.reason, "判断依据全文", r.reason)
      : c.el("div", { class: "ads-fr-miss" }, "本次运行未给出判断依据"),
  ];
  if (r.diagnosis_id) {
    whyKids.push(c.el("div", { class: "ads-pc-from" },
      "来自诊断：" + (diagName[r.diagnosis_id] || r.diagnosis_id)));
  }
  whyKids.push(fieldGrid(c, FIELD_COL.why, labels, r.fields));
  const why = c.el("div", { class: "ads-pc-col" }, whyKids);

  const exp = c.el("div", { class: "ads-pc-col" }, [
    c.el("div", { class: "ads-pc-cl" }, "预期结果"),
    watchTable(c, r.watch),
    fieldGrid(c, FIELD_COL.exp, labels, r.fields),
  ]);

  // 卡底：优先级 · 风险/不确定项 · 审批
  const foot = c.el("div", { class: "ads-pc-foot" }, [
    r.priority ? c.el("span", { class: "ads-pri-tag" }, r.priority) : null,
  ].filter(Boolean));
  const tag = (label, text) => {
    if (!text) return;
    const b = c.el("button", { class: "ads-tagbtn", type: "button" }, label);
    b.addEventListener("click", () => popText(c, b, label, text));
    foot.appendChild(b);
  };
  if ((r.risks || []).length) {
    tag("风险 " + r.risks.length, r.risks.join("\n"));
  }
  tag("不确定项", r.uncertainty);
  if (r.ad_object_id && onFlash) {
    const j = c.el("button", { class: "ads-ref", type: "button" }, "定位对象");
    j.addEventListener("click", () => onFlash(r.ad_object_id));
    foot.appendChild(j);
  }

  const key = r.recommendation_id;
  const done = r.is_template ? state.decidedDemo[key] : state.decided[key];
  const dec = c.el("div", { class: "ads-decide" });
  if (done) {
    const lab = r.is_template ? done : done.decision_label;
    const hand = r.is_template
      ? (lab === "拒绝" ? "已拒绝" : "待执行") : done.handoff_label;
    dec.appendChild(c.el("span", { class: "ads-decided" },
      "已" + lab + " · " + hand));
    const again = c.el("button", { class: "ads-btn", type: "button" }, "改回未决");
    again.addEventListener("click", () => (r.is_template
      ? cb.onUndoDemo(r) : cb.onUndo(r)));
    dec.appendChild(again);
  } else {
    /* 勾选框在四个按钮左边：单条照旧一键点，多条勾上去交给顶部那条批量条。
       会上原话（JACK 2026-09-04）：「他给到调整建议，他必须要具备批量性操作
       的这个功能」「如果说你一个一个点，我告诉你，你都得点一上午」。
       已决定的卡没有勾选框 —— 决定过的不该再被一次批量操作扫进去。 */
    const pick = c.el("input", { type: "checkbox", class: "ads-pcsel" });
    pick.checked = state.picked.has(key);
    pick.setAttribute("aria-label", "选中这条建议，参与批量审批");
    pick.addEventListener("change", () => cb.onPick(key, pick.checked));
    dec.appendChild(pick);
    [["accept", "接受"], ["modify", "修改后接受"],
     ["reject", "拒绝"], ["defer", "暂缓"]].forEach(([code, lab]) => {
      const b = c.el("button", { class: "ads-btn", type: "button" }, lab);
      b.addEventListener("click", () => (r.is_template
        ? cb.onDecideDemo(r, lab) : cb.onDecide(r, code)));
      dec.appendChild(b);
    });
  }
  foot.appendChild(dec);

  const card = c.el("div", { class: "ads-pc" }, [
    c.el("div", { class: "ads-pc-cols" }, [act, why, exp]), foot,
  ]);

  if (done) {
    const f = r.fields;
    card.appendChild(c.el("div", { class: "ads-handoff" }, [
      c.el("div", { class: "ads-mut" }, "交接给执行与复盘"),
      c.el("dl", { class: "ads-kv" }, [
        c.el("dt", {}, "调整对象"), c.el("dd", {}, f.target),
        c.el("dt", {}, "调整维度"), c.el("dd", {}, f.lever),
        c.el("dt", {}, "当前值 → 目标值"), c.el("dd", {}, f.from_to),
        c.el("dt", {}, "时间阈值"), c.el("dd", {}, f.time_threshold),
        c.el("dt", {}, "数据量阈值"), c.el("dd", {}, f.volume_threshold),
        c.el("dt", {}, "达标判据"), c.el("dd", {}, f.pass_rule),
        c.el("dt", {}, "不达标处置"), c.el("dd", {}, f.on_fail),
        c.el("dt", {}, "运营决定"),
        c.el("dd", {}, r.is_template ? done : done.decision_label),
      ]),
    ]));
  }
  return card;
}

/* 模板覆盖率条：这一批建议里每个字段有几条真填上了。
   这是给 Agent 侧的验收单 —— 哪一格是 0，就是下一步要补的输出点。 */
function coverageBar(c, cov, labels) {
  if (!cov || !cov.total) return null;
  const cells = (cov.fields || []).map((f) => {
    const ok = f.filled === f.total;
    const none = f.filled === 0;
    return c.el("span", { class: "ads-cvi"
      + (ok ? " ads-cvi-ok" : none ? " ads-cvi-none" : " ads-cvi-part") },
      [c.el("b", {}, labels[f.key] || f.key),
       c.el("i", {}, f.filled + "/" + f.total)]);
  });
  return c.el("div", { class: "ads-cv" }, [
    c.el("div", { class: "ads-subhead" }, "标准模板字段覆盖 · 本次 Agent 运行"),
    c.el("div", { class: "ads-cvrow" }, cells),
  ]);
}

/* 批量审批条。只在有未决定的卡时出现。
   JACK 2026-09-04：「这个好不好批量去操作啊……他必须要具备批量性操作的这个
   功能，你一个一个点，你都得点一上午。」
   这里做的是**同一批建议的批量审批**：勾几条 → 一次拍板。
   跨 ASIN 把所有建议汇总到一张表再批量筛（他原话里的第二层）是另一个页面，
   不在这一屏 —— 那一层要先有跨 ASIN 的建议库，现在每次运行只出一个 ASIN。 */
function bulkBar(c, rows, state, cb) {
  const pend = rows.filter((r) => !(r.is_template
    ? state.decidedDemo[r.recommendation_id]
    : state.decided[r.recommendation_id]));
  if (!pend.length) return null;
  const ids = pend.map((r) => r.recommendation_id);
  const n = ids.filter((id) => state.picked.has(id)).length;
  const allOn = n === ids.length;

  const box = c.el("input", { type: "checkbox", class: "ads-pcsel" });
  box.checked = allOn;
  box.indeterminate = n > 0 && !allOn;
  box.setAttribute("aria-label", allOn ? "取消全选" : "全选待决定的建议");
  box.addEventListener("change", () => cb.onPickAll(ids, box.checked));

  const kids = [box, c.el("span", { class: "ads-mut" },
    n ? `已选 ${n} / ${ids.length} 条待决定` : `${ids.length} 条待决定`)];

  if (n) {
    [["accept", "接受"], ["modify", "修改后接受"],
     ["reject", "拒绝"], ["defer", "暂缓"]].forEach(([code, lab]) => {
      const b = c.el("button", { class: "ads-btn", type: "button" },
        lab + " " + n + " 条");
      b.addEventListener("click", () => cb.onDecideBulk(code, lab));
      kids.push(b);
    });
  }
  kids.push(c.el("span", { class: "ads-bulknote" }, n
    ? "一条一条落库，中间失败的会留在待决定里"
    : "勾上要一起拍板的几条，按钮就出来"));

  return c.el("div", { class: "ads-bulk" }, kids);
}

export function sectionProposals(c, d, run, state, cb, onFlash) {
  const pts = (run && run.points) || {};
  const labels = (d.view || {}).proposal_field_labels || {};
  const diagName = {};
  (pts.B3 || []).forEach((y) => {
    diagName[y.diagnosis_id] = labelOf(y, "problem_type", "problem_label");
  });
  const ctxData = { diagName };

  // Agent 的建议已由后端过一遍标准模板（run.proposals）
  const agentRows = (run && run.proposals) || [];
  const tplRows = (state.demo && state.demo.available)
    ? (state.demo.items || []) : [];
  // 合成一张列表，按优先级排 —— 不按来源分组。
  const PRI = { P0: 0, P1: 1, P2: 2, P3: 3 };
  const rows = agentRows.concat(tplRows).slice().sort((a, b) =>
    (PRI[a.priority] ?? 9) - (PRI[b.priority] ?? 9));

  const body = [];
  if (!rows.length) {
    body.push(c.el("div", { class: "ads-hint" },
      run && run.run_id ? "本次运行没有产出建议。"
        : "尚未运行 Agent，没有建议。"));
  }
  const bulk = bulkBar(c, rows, state, cb);
  if (bulk) body.push(bulk);
  rows.forEach((r) => body.push(
    proposalCard(c, r, labels, ctxData, state, cb, onFlash)));

  if (state.demo && state.demo.available
      && (state.demo.dropped || []).length) {
    state.demo.dropped.forEach((x) => body.push(
      c.el("div", { class: "ads-hint" },
        `第 ${x.seq} 条没有显示：${x.why}`)));
  }

  // 覆盖率条放最后：它是对上面那批 Agent 卡的机械统计，不是建议本身
  const cov = coverageBar(c, run && run.field_coverage, labels);
  if (cov) body.push(cov);

  const decidedN = Object.keys(state.decided).length
    + Object.keys(state.decidedDemo).length;
  const hasScript = ((d.view || {}).has_demo_script) === true;
  let right = null;
  if (hasScript && !state.demo) {
    right = c.el("button", { class: "ads-loadbtn", type: "button" },
      "补齐标准模板示例");
    right.addEventListener("click", () => cb.onLoadDemo());
  } else if (state.demo) {
    right = c.el("button", { class: "ads-btn", type: "button" }, "收起示例");
    right.addEventListener("click", () => cb.onHideDemo());
  }

  return sec(c, {
    no: "④", title: "广告策略建议与审批", ai: "广告异常与决策",
    right,
    note: rows.length
      ? `${rows.length} 条建议${decidedN ? ` · 已决定 ${decidedN} 条` : ""}`
      : "无建议",
    info: "会上定的形态（2026-09-03 00:36:42）：AI 不直接执行，"
      + "只把动作、原因、预期结果列出来，由人审批，认可之后才去调广告 API。\n"
      + "所以每条建议是一张固定字段表，字段全部来自会上原话：\n"
      + "调整对象 / 调整维度 / 方向 / 当前值→目标值 / 幅度 / 调整目标"
      + "（00:36「把 top placement 比例从 40% 上调到 50%」）；\n"
      + "时间阈值 / 数据量阈值 / 先到先算"
      + "（00:38「我有两个阈值……三天之后，或者数量达到之后」）；\n"
      + "监控指标带基准值与目标值、达标判据、不达标处置"
      + "（00:40「这几个数指标都是要监控的指标……没达到就是有问题的」）。\n"
      + "灰掉的格子是本次 Agent 运行没有输出的字段 —— 那一格就是 Agent 侧"
      + "下一步要补的输出点，底部覆盖率条是这批卡的机械统计。",
  }, body);
}

/* ============================================== ⑤ 执行后效果监控（事后） */

export function sectionMonitor(c, d) {
  const m = (d.view || {}).monitor || {};
  const body = [];

  // 双阈值
  const th = m.thresholds || {};
  body.push(c.el("div", { class: "ads-stats ads-stats-3" }, [
    statCell(c, "时间阈值", (th.time_windows || []).join(" / ") || "—",
      "到窗口就抓一次指标", "word"),
    statCell(c, "数据量阈值", th.min_clicks === null
      || th.min_clicks === undefined ? "—" : fmtNum(th.min_clicks) + " 次点击",
      "样本不够就不下效率结论", "word"),
    statCell(c, "触发方式", "先到先算", "两个阈值任一满足即复盘", "word"),
  ]));

  if (!m.has_data) {
    body.push(c.el("div", { class: "ads-empty" }, [
      c.el("b", {}, "本对象还没有复盘记录"),
      c.el("span", {}, m.why_empty || ""),
    ]));
    return sec(c, {
      no: "⑤", title: "执行后效果监控", note: "未接入",
      info: "会上定的闭环：人审批采纳 → 执行 → 到达时间阈值或数据量阈值 → "
        + "自动抓关键指标 → 达标即认为策略合理并回灌，未达标则推送运营。\n"
        + "这一屏只显示真实写入的复盘记录。没有记录就说没有，"
        + "不拿构造的数字顶上 —— 半份结果上屏比空板块更糟。",
    }, body);
  }

  (m.cards || []).forEach((cd) => {
    const kids = [
      c.el("div", { class: "ads-mn-h" }, [
        c.el("b", {}, "复盘窗口 " + (cd.window || "—")),
        c.el("span", { class: "ads-mut num" }, cd.review_at || ""),
        c.el("span", { class: "ads-chip ads-chip-calm" },
          cnOf("review_status", cd.status) || cd.status || ""),
        c.el("span", { class: "ads-chip "
          + (cd.sample_ok ? "ads-chip-good" : "ads-chip-warn") },
          cd.sample_ok
            ? `样本达标（${fmtNum(cd.clicks)} 次点击 ≥ ${fmtNum(cd.min_clicks)}）`
            : `样本未达标（${fmtNum(cd.clicks)} 次点击 < ${fmtNum(cd.min_clicks)}）`),
      ]),
      svgBox(c, deltaRows(cd.metrics)),
    ];
    if (cd.conclusion) {
      kids.push(c.el("div", { class: "ads-mn-say" }, cd.conclusion));
    }
    if ((cd.concurrent_variables || []).length) {
      kids.push(c.el("div", { class: "ads-warnline" }, [
        c.el("b", {}, "同期还有这些变量没排除："),
        c.el("span", {}, cd.concurrent_variables.join("、")),
        c.el("span", {}, "所以这段变化不能算成动作造成的。"),
      ]));
    }
    if (cd.next_question) {
      kids.push(c.el("div", { class: "ads-mn-next" },
        "下一个要回答的问题：" + cd.next_question));
    }
    body.push(c.el("div", { class: "ads-mn" }, kids));
  });

  // 决策事件时间线
  if ((m.events || []).length) {
    body.push(subhead(c, `决策事件 ${m.events.length} 条`));
    m.events.forEach((e) => {
      body.push(c.el("div", { class: "ads-ev" }, [
        c.el("span", { class: "ads-ev-d num" }, e.occurred_at || ""),
        c.el("span", { class: "ads-chip ads-chip-calm" }, e.event_label || ""),
        c.el("span", { class: "ads-ev-s" }, e.handoff_label || ""),
        c.el("span", { class: "ads-ev-r" }, e.decision_reason || ""),
        (e.handoff_open_items || []).length
          ? c.el("span", { class: "ads-mut" },
            "未完项：" + e.handoff_open_items.join("、"))
          : null,
      ].filter(Boolean)));
    });
  }

  return sec(c, {
    no: "⑤", title: "执行后效果监控",
    note: `${(m.cards || []).length} 份复盘 · ${(m.events || []).length} 条决策事件`,
    info: "会上定的闭环：审批采纳 → 执行 → 到时间阈值或数据量阈值 → 抓指标 → "
      + "达标即认为策略合理并回灌，未达标推送运营。\n"
      + "方向语义逐指标定：ACoS 越低越好、转化率越高越好，"
      + "而花费涨跌本身没有好坏，所以不着色。\n"
      + "同期变量必须和结论同屏 —— 只画一张「改完就好了」的图是在声明因果。",
  }, body);
}

/* ============================================== ⑥ 决策沿革与回测 */

export function sectionLineage(c, d, onVersion) {
  const lg = (d.view || {}).lineage || {};
  const body = [];

  const vs = lg.versions || [];
  if (vs.length) {
    vs.forEach((v) => {
      const row = c.el("div", { class: "ads-lv" + (v.is_current ? " ads-lv-on" : "") }, [
        c.el("i", { class: "ads-lv-dot" }),
        c.el("span", { class: "ads-lv-d num" }, v.decision_at || ""),
        c.el("span", { class: "ads-lv-g" }, v.product_goal || "—"),
        c.el("span", { class: "ads-mut" }, v.is_current ? "当前版本" : ""),
        c.el("span", { class: "ads-mut" },
          `${v.event_n} 条决策事件 · ${v.review_n} 份复盘`),
      ]);
      if (!v.is_current) {
        const b = c.el("button", { class: "ads-ref", type: "button" }, "看这一版");
        b.addEventListener("click", () => onVersion(v.decision_id));
        row.appendChild(b);
      }
      body.push(row);
    });
    if (!lg.has_history) {
      body.push(c.el("div", { class: "ads-hint" },
        "这个子 ASIN 只有一个决策版本，还没有上一版可比。"));
    }
  }

  // 策略回测：如实标未接入，写清缺什么
  const bt = lg.backtest || {};
  body.push(subhead(c, "策略回测"));
  body.push(c.el("div", { class: "ads-empty" }, [
    c.el("b", {}, "未接入"),
    c.el("span", {}, bt.missing || ""),
    c.el("div", { class: "ads-bt-needs" }, [
      c.el("div", { class: "ads-mut" }, "接上之后它会这样跑："),
      c.el("ol", {}, (bt.needs || []).map((x) => c.el("li", {}, x))),
    ]),
  ]));

  return sec(c, {
    no: "⑥", title: "决策沿革与回测",
    note: `${vs.length} 个决策版本`,
    info: "会上说的「回测」是两件事：\n"
      + "一是过一周之后看这次调整到底 OK 不 OK —— 那是效果复盘，在上一个板块。\n"
      + "二是把策略带回到历史某一天、不给它看之后的数据，看这条策略当时行不行得通"
      + " —— 那是策略回测，当前没有数据也没有 Agent 入口，所以如实标未接入。",
  }, body);
}

/* ================================================== 逐日图（ECharts） */

// 与 tokens.css 的 --sans 逐字一致，**两边要一起改**（门禁 G24）。
const FONT = '-apple-system, "SF Pro Text", BlinkMacSystemFont, "IBM Plex Sans", '
  + 'Inter, "PingFang SC", "Microsoft YaHei", sans-serif';
// 字号镜像：canvas 里的字不继承 CSS，必须在 JS 里重复一份，
// 每一项都要落在 tokens.css 的阶梯档位上（门禁 G24）。
const FS = { axis: 11, legend: 13, tip: 13 };

let echartsLoading = null;
let dayInst = null;

function loadECharts() {
  if (typeof window !== "undefined" && window.echarts) {
    return Promise.resolve(window.echarts);
  }
  if (echartsLoading) return echartsLoading;
  echartsLoading = new Promise((resolve, reject) => {
    const tag = document.createElement("script");
    tag.src = "/assets/echarts.min.js";
    tag.onload = () => resolve(window.echarts);
    tag.onerror = () => reject(new Error("ECharts 加载失败"));
    document.head.appendChild(tag);
  });
  return echartsLoading;
}

export function disposeDaily() {
  if (dayInst) { dayInst.dispose(); dayInst = null; }
}

export async function mountDailyChart(box, daily) {
  if (!box) return;
  const o = (daily.objects || [])[0];
  if (!o) return;
  let ec;
  try {
    ec = await loadECharts();
  } catch (err) {
    box.textContent = "逐日图加载失败：" + String(err);
    return;
  }
  if (!ec || !box.isConnected) return;
  disposeDaily();
  const dates = o.points.map((p) => p.date);
  const spend = o.points.map((p) => p.spend);
  const sales = o.points.map((p) => p.ad_sales);
  const acos = o.points.map((p) => p.acos === null ? null
    : Number((p.acos * 100).toFixed(2)));
  dayInst = ec.init(box, null, { renderer: "canvas" });
  dayInst.setOption({
    textStyle: { fontFamily: FONT },
    grid: { left: 56, right: 56, top: 34, bottom: 26 },
    legend: {
      top: 0, itemGap: 18,
      textStyle: { fontFamily: FONT, fontSize: FS.legend },
      data: ["花费", "广告销售额", "ACoS"],
    },
    tooltip: {
      trigger: "axis",
      textStyle: { fontFamily: FONT, fontSize: FS.tip },
      axisPointer: { type: "shadow" },
    },
    xAxis: {
      type: "category", data: dates,
      axisLabel: { fontFamily: FONT, fontSize: FS.axis },
      axisTick: { alignWithLabel: true },
    },
    // 金额与比率分轴：比率跟金额共轴会被压成贴零轴的一条直线（要则第六节）
    yAxis: [
      { type: "value", name: "美元", min: 0,
        nameTextStyle: { fontFamily: FONT, fontSize: FS.axis },
        axisLabel: { fontFamily: FONT, fontSize: FS.axis } },
      // 叠加轴必须从 0 起，关掉自动缩放，否则平的会被画成大起大落
      { type: "value", name: "ACoS %", min: 0,
        nameTextStyle: { fontFamily: FONT, fontSize: FS.axis },
        axisLabel: { fontFamily: FONT, fontSize: FS.axis },
        splitLine: { show: false } },
    ],
    series: [
      { name: "花费", type: "bar", data: spend, barMaxWidth: 14,
        itemStyle: { color: "#111113" } },
      { name: "广告销售额", type: "bar", data: sales, barMaxWidth: 14,
        itemStyle: { color: "#b9b9c0" } },
      { name: "ACoS", type: "line", yAxisIndex: 1, data: acos,
        symbol: "circle", symbolSize: 4, connectNulls: false,
        lineStyle: { width: 1.6, color: "#2563eb" },
        itemStyle: { color: "#2563eb" } },
    ],
  });
}

/* ==================================================== 页面二装配入口 */

/* 高亮某个广告对象所在的表格行。被 ③ 的「定位对象」调用。 */
function flashObject(root, oid) {
  if (!root) return;
  const row = root.querySelector(`.ads-trow[data-oid="${oid}"]`);
  if (!row) return;
  root.querySelectorAll(".ads-flash")
    .forEach((r) => r.classList.remove("ads-flash"));
  row.classList.add("ads-flash");
  row.scrollIntoView({ block: "center", behavior: "smooth" });
  setTimeout(() => row.classList.remove("ads-flash"), 2400);
}

/* 没有决策版本的第三态：只有广告事实，判断跑不了。 */
function thinPage(c, d) {
  const r = d.readiness || {};
  return c.el("section", { class: "ads-card" }, [
    c.el("div", { class: "ads-hr-asin" },
      [c.el("b", {}, d.child_asin || "—")]),
    c.el("div", { class: "ads-hr-goal" }, "尚无决策版本"),
    c.el("div", { class: "ads-empty" }, [
      c.el("b", {}, r.mode || "暂时无法判断"),
      c.el("span", {}, (r.notes || []).join("；")),
      c.el("span", {}, (r.blockers || []).join("；")),
    ]),
  ]);
}

/**
 * 渲染页面二。
 * @param c      外壳 ctx
 * @param body   主体容器
 * @param d      /api/ads/context 的载荷（带 view 派生块）
 * @param run    /api/ads/run 的载荷（Agent 最新一次完成运行）
 * @param state  { decided }  本地审批态
 * @param cb     { onVersion, onDecide, onUndo }
 */
export function renderPage2(c, body, d, run, state, cb) {
  body.textContent = "";
  disposeDaily();
  if (!d.context) {
    body.appendChild(thinPage(c, d));
    return;
  }
  body.appendChild(heroBar(c, d, run, cb.onVersion));
  body.appendChild(sectionMarket(c, d));
  body.appendChild(sectionOwnFacts(c, d,
    (box, daily) => { mountDailyChart(box, daily); }));
  body.appendChild(sectionJudgment(c, d, run,
    (oid) => flashObject(body, oid)));
  body.appendChild(sectionProposals(c, d, run, state, cb,
    (oid) => flashObject(body, oid)));
  body.appendChild(sectionMonitor(c, d));
  body.appendChild(sectionLineage(c, d, cb.onVersion));
}
