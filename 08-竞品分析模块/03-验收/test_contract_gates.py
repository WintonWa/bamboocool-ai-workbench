#!/usr/bin/env python3
"""竞品契约门禁。

两类分清（要则 §10）：
- 约束型（G/A/C 系列）= 提交的不与确定性层矛盾，**不断言结论等于某个值**，不指名某个族该判成哪一档。
- 演示覆盖（INFO 行）= 构造数据够不够铺满页面，依赖判断值，随 Agent 分析进度变，不做 pass/fail。

判断层读 Agent 状态库（`agent.` 前缀，默认 V2 sidecar，可用 WORKBENCH_COMPETITOR_AGENT_DB 覆盖）；
观察层留 main。观察库里那 9 张 legacy fact_competitor_analysis_* 是禁读的，不参与门禁。
"""
from __future__ import annotations

import os
import re
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.join(os.path.dirname(HERE), "02-数据构建", "v0.1.0")
DB = os.path.join(PKG, "competitor_demo.sqlite")
PRODUCT_DB = os.path.join(
    os.path.dirname(os.path.dirname(HERE)),
    "02-产品销售库存模块", "02-数据构建", "v0.3.0",
    "bamboocool_product_sales_inventory_v0.3.0.sqlite",
)
AGENT_DB = os.environ.get(
    "WORKBENCH_COMPETITOR_AGENT_DB",
    os.path.join(
        os.path.dirname(os.path.dirname(HERE)),
        "09-工作台", "modules", "competitor", "derived",
        "competitor_agent_state_v2.sqlite",
    ),
)
VALUE_ORIGINS = {"direct", "derived", "constructed"}

ENUMS = [
    "price_promo", "third_party_estimate", "insufficient", "sufficient", "partial",
    "represents_family", "scheduled", "priority", "escalated", "sustained",
    "eased", "cleared", "hypothesis", "unconfirmed", "observed", "derived",
    "concurrent", "sequential", "independent", "family_asin", "child_asin",
]
TEXT_COLS = [
    ("fact_competitor_analysis_run", ["attention_summary", "evidence_reason", "judgment_summary"]),
    ("fact_competitor_analysis_change", ["label", "current_state", "coverage_note", "basis"]),
    ("fact_competitor_analysis_timeline", ["label", "note"]),
    ("fact_competitor_analysis_concurrency", ["statement", "missing_evidence"]),
    ("fact_competitor_analysis_attention_reason", ["label", "weight_note"]),
    ("fact_competitor_analysis_impact", ["statement"]),
    ("fact_competitor_analysis_open_item", ["statement", "needed_data"]),
    ("fact_competitor_analysis_diff", ["statement"]),
    ("fact_competitor_analysis_report", ["headline", "body", "impact_note", "unconfirmed_note"]),
    ("fact_competitor_evidence_handoff", ["observable_fact", "detail_entry"]),
]

fails: list[str] = []
notes: list[str] = []


def check(gid: str, ok: bool, msg: str):
    (notes if ok else fails).append(f"{'PASS' if ok else 'FAIL'} {gid}  {msg}")


def main():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.execute(f"ATTACH DATABASE 'file:{PRODUCT_DB}?mode=ro' AS pr")
    if not os.path.exists(AGENT_DB):
        print(f"FAIL 门禁无法运行：Agent 状态库不存在 {AGENT_DB}")
        return 1
    con.execute(f"ATTACH DATABASE 'file:{AGENT_DB}?mode=ro' AS agent")
    q = con.execute
    scen = {r[0]: r[1] for r in q("SELECT scenario_id, family_asin FROM dim_competitor_scenario")}
    as_of = q("SELECT value FROM competitor_manifest WHERE key='as_of'").fetchone()[0]

    bad = q(
        "SELECT r.run_id FROM agent.fact_competitor_analysis_run r LEFT JOIN agent.fact_competitor_analysis_change c"
        " USING(run_id) WHERE c.run_id IS NULL"
    ).fetchall()
    empty = q(
        "SELECT COUNT(*) FROM agent.fact_competitor_analysis_change WHERE label='' OR basis='' "
        "OR label IS NULL OR basis IS NULL"
    ).fetchone()[0]
    check("G1", not bad and not empty,
          f"每个 run 至少一条变化且文案非空（无变化 run={len(bad)}，空文案={empty}）")

    # s9 只用于 A3：断更区间是观察层构造出来的**确定性事实**，不是判断值，
    # 指名对象合规（要则 §11 配套边界末句）。判断值类断言一律不指名对象。
    s9 = scen.get("S9")

    # G2 约束型：凡 evidence_level=insufficient 的 run，必须 attention_level=none 且零依据条目。
    # 要则 §11 配套边界：不指名活对象、不断言某个族该判成哪一档——真 Agent 判成 partial
    # 也是合法判断，门禁只管「判成 insufficient 就必须满足这三条」。
    bad2 = q(
        "SELECT r.run_id, r.attention_level, COUNT(ar.reason_seq) n"
        " FROM agent.fact_competitor_analysis_run r"
        " LEFT JOIN agent.fact_competitor_analysis_attention_reason ar USING(run_id)"
        " WHERE r.evidence_level = 'insufficient'"
        " GROUP BY r.run_id HAVING r.attention_level <> 'none' OR n > 0"
    ).fetchall()
    n_insuf = q("SELECT COUNT(*) FROM agent.fact_competitor_analysis_run"
                " WHERE evidence_level = 'insufficient'").fetchone()[0]
    check("G2", not bad2,
          f"证据不足的 run 全部无关注等级且无依据条目"
          f"（{n_insuf} 个证据不足，违例 {[r[0] for r in bad2]}）")

    thin = q(
        "SELECT r.run_id, COUNT(ar.reason_seq) n FROM agent.fact_competitor_analysis_run r"
        " LEFT JOIN agent.fact_competitor_analysis_attention_reason ar USING(run_id)"
        " WHERE r.attention_level <> 'none' GROUP BY r.run_id HAVING n < 2"
    ).fetchall()
    check("G3", not thin, f"有关注等级的 run 至少两条依据条目（不足的 {len(thin)} 个）")

    # 日粒度 domain 必须落在窗口内；traffic 是月度表（period_start 取月初），
    # 允许早于 window_from 但不得早于含 window_from 的那个月之首（契约 2.2 时间粒度）。
    oob = q(
        "SELECT c.run_id, c.change_seq, c.domain, c.date_from FROM agent.fact_competitor_analysis_change c"
        " JOIN agent.fact_competitor_analysis_run r USING(run_id)"
        " WHERE c.date_from > r.window_to"
        "    OR (c.domain <> 'traffic' AND c.date_from < r.window_from)"
        "    OR (c.domain = 'traffic' AND c.date_from < date(r.window_from,'start of month'))"
    ).fetchall()
    monthly = q(
        "SELECT COUNT(*) FROM agent.fact_competitor_analysis_change c"
        " JOIN agent.fact_competitor_analysis_run r USING(run_id)"
        " WHERE c.domain = 'traffic' AND c.date_from < r.window_from"
    ).fetchone()[0]
    check("G4", not oob,
          f"变化起始日在窗口内（越界 {[(x[0][-2:], x[2], x[3]) for x in oob]}）；"
          f"月粒度按区间起点判，{monthly} 条 traffic 早于窗口起点属正常口径")

    miss = 0
    for lvl, oid in q("SELECT object_level, object_id FROM agent.fact_competitor_analysis_change"):
        tbl, col = {
            "family": ("dim_competitor_family", "family_asin"),
            "child": ("dim_competitor_child", "child_asin"),
            "offer": ("dim_competitor_offer", "offer_id"),
            "keyword": ("dim_competitor_keyword", "keyword"),
        }[lvl]
        if not q(f"SELECT 1 FROM {tbl} WHERE {col}=?", (oid,)).fetchone():
            miss += 1
    check("G5", miss == 0, f"变化对象在观察库可解析（找不到 {miss}）")

    leak = q(
        "SELECT COUNT(*) FROM agent.fact_competitor_analysis_report p JOIN agent.fact_competitor_analysis_change c"
        " ON c.run_id = p.ref_run_id WHERE c.represents_family = 0"
        " AND NOT EXISTS (SELECT 1 FROM agent.fact_competitor_analysis_change c2"
        "                 WHERE c2.run_id = p.ref_run_id AND c2.represents_family = 1)"
    ).fetchone()[0]
    s7 = scen.get("S7")
    s7_in_report = q("SELECT COUNT(*) FROM agent.fact_competitor_analysis_report WHERE family_asin=?",
                     (s7,)).fetchone()[0]
    check("G6", leak == 0 and s7_in_report == 0,
          f"局部变化未被当成整族结论（局部对象 {s7} 进报告 {s7_in_report} 次）")

    bad7 = q(
        "SELECT pair_seq FROM agent.fact_competitor_analysis_concurrency"
        " WHERE causal_ready <> 0 OR (relation = 'insufficient' AND causal_ready <> 0)"
    ).fetchall()
    nocause = q(
        "SELECT COUNT(*) FROM agent.fact_competitor_analysis_concurrency"
    ).fetchone()[0]
    check("G7", not bad7,
          f"因果边界成立：{nocause} 条同期关系的 causal_ready 全为 0（违例 {len(bad7)}）")

    dup = q(
        "SELECT family_asin, run_date, COUNT(*) n, COUNT(DISTINCT created_at) d"
        " FROM agent.fact_competitor_analysis_run GROUP BY 1,2 HAVING n <> d"
    ).fetchall()
    check("G8", not dup, f"同族同日多次运行的 created_at 互不相同（冲突 {len(dup)}）")

    hits = []
    for tbl, cols in TEXT_COLS:
        for col in cols:
            for (val,) in q(f"SELECT {col} FROM agent.{tbl} WHERE {col} IS NOT NULL"):
                for e in ENUMS:
                    if re.search(rf"\b{re.escape(e)}\b", str(val)):
                        hits.append(f"{tbl}.{col}: {e}")
    check("G9", not hits, f"中文文案字段无枚举原值泄漏（命中 {len(hits)}：{hits[:3]}）")

    dom = dict(q("SELECT domain, COUNT(DISTINCT r.family_asin) FROM agent.fact_competitor_analysis_change c"
                 " JOIN agent.fact_competitor_analysis_run r USING(run_id) GROUP BY domain"))
    st = dict(q("SELECT status, COUNT(*) FROM fact_competitor_data_status GROUP BY status"))
    ok10 = all(dom.get(d, 0) >= 3 for d in
               ("price_promo", "market", "keyword", "traffic")) and all(
        st.get(s, 0) >= 1 for s in ("interrupted", "stale", "conflict"))
    # 演示覆盖不是契约，不做 pass/fail：它依赖判断值，随 Agent 分析进度变化。
    # 只报事实，让人看见「现在够不够铺满页面」。
    notes.append(
        f"INFO 演示覆盖  已分析族的四类版图 {dom}；观察层数据状态 {st}"
        f"（四类各 ≥3 族才够铺满总览计数带）"
    )

    bad11 = q(
        "SELECT COUNT(*) FROM agent.fact_competitor_analysis_change c"
        " LEFT JOIN dim_competitor_child k ON k.child_asin = c.object_id"
        " WHERE c.label LIKE '%价差%' AND c.object_level='child'"
        " AND (k.pack_resolved IS NULL OR k.pack_resolved = 0)"
    ).fetchone()[0]
    check("G11", bad11 == 0, f"价差类结论的对象装盒数已解析（违例 {bad11}）")

    ghost = q(
        "SELECT COUNT(*) FROM agent.fact_competitor_evidence_handoff h LEFT JOIN agent.fact_competitor_analysis_run r"
        " ON r.run_id = h.frozen_run_id WHERE r.run_id IS NULL"
    ).fetchone()[0]
    check("G12", ghost == 0, f"交接引用的 run 存在（悬空 {ghost}）")

    # 观察库自身的锚点门禁
    bad_end = q(
        "SELECT COUNT(*) FROM dim_competitor_child k JOIN fact_competitor_price_daily p"
        " ON p.child_asin = k.child_asin AND p.date = ?"
        " WHERE ABS(p.final_price - k.snapshot_price) > 0.005", (as_of,)
    ).fetchone()[0]
    check("A1", bad_end == 0, f"末日价格等于快照价格（偏差 {bad_end}）")

    nonmono = q(
        "SELECT COUNT(*) FROM (SELECT family_asin, date, rating_count,"
        " LAG(rating_count) OVER (PARTITION BY family_asin ORDER BY date) prev"
        " FROM fact_competitor_market_daily) WHERE prev IS NOT NULL AND rating_count < prev"
    ).fetchone()[0]
    check("A2", nonmono == 0, f"评论数单调不减（违例 {nonmono}）")

    gap = q(
        "SELECT COUNT(*) FROM fact_competitor_price_daily p"
        " JOIN dim_competitor_child k USING(child_asin)"
        " WHERE k.family_asin = ? AND p.date BETWEEN '2026-06-05' AND '2026-06-18'",
        (s9,)
    ).fetchone()[0]
    check("A3", gap == 0, f"断更区间内无正常观察（{s9} 区间内 {gap} 行）")

    # ---- 契约门禁 ----
    tabs = [r[0] for r in q("SELECT name FROM sqlite_master WHERE type='table'")]
    ok = all(
        x.startswith(("dim_competitor", "fact_competitor", "bridge_competitor",
                      "plan_competitor")) or x == "competitor_manifest"
        for x in tabs if not x.startswith("sqlite_")
    )
    check("C1", ok, f"全部 {len(tabs)} 张表带模块前缀")

    rebuilt = [x for x in tabs if x in ("dim_product_child", "dim_product_parent")]
    check("C2", not rebuilt, f"本包未重建产品维度（契约 6.3），发现 {rebuilt}")

    bad_vo = []
    for tb in ("fact_competitor_price_daily", "fact_competitor_market_daily",
               "fact_competitor_keyword_rank", "fact_competitor_traffic_mix",
               "bridge_competitor_child", "dim_competitor_offer",
               "agent.fact_competitor_analysis_change"):
        for (v,) in q(f"SELECT DISTINCT value_origin FROM {tb}"):
            if v not in VALUE_ORIGINS:
                bad_vo.append(f"{tb}:{v}")
    check("C3", not bad_vo, f"value_origin 只取 direct/derived/constructed（越界 {bad_vo}）")

    orphan = q(
        "SELECT COUNT(*) FROM bridge_competitor_child b"
        " LEFT JOIN pr.dim_product_child c ON c.child_asin = b.child_asin"
        " WHERE c.child_asin IS NULL"
    ).fetchone()[0]
    spine = q("SELECT COUNT(*) FROM pr.dim_product_child").fetchone()[0]
    covered = q(
        "SELECT COUNT(DISTINCT parent_asin) FROM bridge_competitor_child"
    ).fetchone()[0]
    check("C4", orphan == 0 and spine == 342 and covered >= 4,
          f"竞争关系自家一侧全部落在脊椎 {spine} 个子 ASIN 内，覆盖 {covered} 个父体（悬空 {orphan}）")

    ALLOWED_STATUS = {"normal", "interrupted", "stale", "conflict", "missing"}
    bad_st = [r[0] for r in q("SELECT DISTINCT status FROM fact_competitor_data_status")
              if r[0] not in ALLOWED_STATUS]
    check("C5", not bad_st, f"数据状态取值合法（越界 {bad_st}）")

    # C6 约束型：假设与待观察的三态取值域。之前批量改名把两条假设写成了 constructed，
    # 因为不上屏所以 G9/G17 抓不到。只查取值域，不查哪个族该有假设——那是判断值，
    # 真 Agent 重跑会变（要则 §11 配套边界）。
    ALLOWED_KIND = {"hypothesis", "unconfirmed", "watch"}
    kinds = dict(q("SELECT item_kind, COUNT(*) FROM "
                   "agent.fact_competitor_analysis_open_item GROUP BY 1").fetchall())
    bad_kind = [k for k in kinds if k not in ALLOWED_KIND]
    check("C6", not bad_kind,
          f"假设待观察 item_kind 只取 hypothesis/unconfirmed/watch（越界 {bad_kind}）")
    notes.append(
        f"INFO 演示覆盖  假设待观察三态分布 {kinds}"
        f"（三态齐备才能演满「分析假设与待观察」段；缺档不是违约）"
    )

    # C7 report_id 必须能从同一行的 ref_run_id 推出来。写入端盖章字段，
    # 不含全局排位 item_seq——单对象重跑的 Agent 拿不到那个排位。
    rpt = q("SELECT report_id, ref_run_id, item_seq FROM "
            "agent.fact_competitor_analysis_report ORDER BY item_seq").fetchall()
    rpt_bad = [r[0] for r in rpt if not r[0].startswith(f"RPT-{r[1]}-")]
    seq_in_id = [r[0] for r in rpt if r[2] > 1 and r[0].endswith(f"-{r[2]:02d}")]
    check("C7", not rpt_bad and not seq_in_id,
          f"{len(rpt)} 条报告的 report_id 全可由 ref_run_id 推导"
          f"（不合 {rpt_bad}），且未把全局排位写进 id（违规 {seq_in_id}）")

    # C8 handoff_id 同理，且同族同页多次交接不得撞主键：
    # B0C81Q5KRW 一个 run 同时交关键词页和广告页，是真有该特征的对象。
    SUF = {"keyword": "KW", "advertising": "AD"}
    ho = q("SELECT handoff_id, frozen_run_id, target_page FROM "
           "agent.fact_competitor_evidence_handoff").fetchall()
    ho_bad = [r[0] for r in ho if r[0] != f"HO-{r[1]}-{SUF[r[2]]}"]
    multi = q("SELECT frozen_run_id FROM agent.fact_competitor_evidence_handoff "
              "GROUP BY 1 HAVING COUNT(*) > 1").fetchall()
    check("C8", not ho_bad and len(ho) == len({r[0] for r in ho}),
          f"{len(ho)} 条交接的 handoff_id 全可由 frozen_run_id 推导（不合 {ho_bad}），"
          f"主键唯一，且 {[r[0] for r in multi]} 一个 run 交两个下游页未撞键")

    con.close()
    for line in notes + fails:
        print(line)
    print(f"\n{len(notes)} passed, {len(fails)} failed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
