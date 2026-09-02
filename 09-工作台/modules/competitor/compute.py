"""竞品模块装配层：把观察事实与 Agent 判断组装成两页载荷。

结构遵循 01-方案与数据需求/03-屏幕决策设计.md：
- 总览 = 洞察带（不重复比较表结论）+ 变化计数带（可点过滤）+ 威胁比较表（唯一焦点）
- 详情 = 判断带 + 四轨共同时间线 + 产品族报价 + 关键词入口证据 + 事实假设三分 + 记录交接

这里不产生新的业务判断：分级、依据、影响、同期关系全部来自 Agent 表。
装配层只做组织、计数去重、排序和词表映射。
"""

from __future__ import annotations

from . import data as D

THRESHOLD_KEYS = (
    "price_drop_pct", "gap_shift_pct", "rank_shift_pct", "kw_rank_shift",
    "min_duration_days", "family_coverage_pct", "stale_days",
)
THRESHOLD_DEFAULTS = {
    "price_drop_pct": 5.0, "gap_shift_pct": 10.0, "rank_shift_pct": 15.0,
    "kw_rank_shift": 3, "min_duration_days": 7,
    "family_coverage_pct": 30.0, "stale_days": 14,
}


def _thresholds(params: dict) -> dict:
    return {key: params.get(key, THRESHOLD_DEFAULTS[key]) for key in THRESHOLD_KEYS}


def _analysis_state(con, family_asin: str, params: dict) -> str:
    if D.latest_execution(con, family_asin) is None:
        return "not_run"
    context_hash = D.source_context_hash(con, family_asin, _thresholds(params))
    return D.analysis_state(con, family_asin, context_hash)


def _pct(a, b):
    if not a or not b:
        return None
    return round((a - b) / b * 100, 1)


def _evidence_state(run: dict | None, statuses: list[dict]) -> str:
    """上屏数据状态：只用契约 6.6 的固定词表。"""
    if run is None:
        return "空结果"
    if run["evidence_level"] == "insufficient":
        return "待确认"
    kinds = {s["status"] for s in statuses}
    if "stale" in kinds:
        return "过期"
    if kinds & {"interrupted", "missing"}:
        return "缺失"
    if "conflict" in kinds:
        return "待确认"
    return "正常"


# ---------------- 总览 ----------------

def _strip_origin(rows):
    """value_origin 只在服务端用来算 nature，不进载荷（契约 6.6：码值不上屏）。"""
    return [{k: v for k, v in r.items() if k != "value_origin"} for r in rows]


def overview(con, params: dict, flt: dict | None = None) -> dict:
    flt = flt or {}
    man = D.manifest(con)
    as_of = man["as_of"]
    fams = {f["family_asin"]: f for f in D.families(con)}
    runs = D.latest_runs(con)
    by_run = D.all_changes(con)
    snap_rank = D.market_snapshot(con, as_of)
    fam_ids = [fa for fa, f in fams.items() if f["in_analysis_scope"]]
    spark_rank = D.spark_series(con, "fact_competitor_market_daily",
                                "family_asin", "rank_sub", fam_ids)
    spark_price = D.child_spark_price(con, fam_ids)
    own_unit = D.own_unit_price_all(con, as_of)
    cmp_unit = D.competitor_unit_price_all(con, as_of)
    status_all: dict[str, list[dict]] = {}
    for s in D.rows(con, "SELECT * FROM fact_competitor_data_status"):
        status_all.setdefault(s["object_id"], []).append(s)

    # 变化计数带：一个族的多类变化各自归类，但族数不重复计
    counts = {k: set() for k in D.DOMAIN}
    for run in runs.values():
        if run["evidence_level"] == "insufficient":
            continue
        for c in by_run.get(run["run_id"], []):
            counts[c["domain"]].add(run["family_asin"])
    count_band = [
        {"domain": k, "label": v, "family_count": len(counts[k])}
        for k, v in D.DOMAIN.items()
    ]

    # 洞察带：只取报告第一条，且只说比较表不重复的那部分（涉及范围与证据入口）
    rpt = D.report(con)
    insight = None
    if rpt:
        top = rpt[0]
        run = runs.get(top["family_asin"])
        insight = {
            "headline": top["headline"],
            "brand": top["brand"],
            "family_asin": top["family_asin"],
            "period": [top["period_from"], top["period_to"]],
            "pressure": D.DOMAIN.get(
                (by_run.get(top["ref_run_id"]) or [{}])[0].get("domain", ""), ""),
            "impact_note": top["impact_note"],
            "unconfirmed_note": top["unconfirmed_note"],
            "evidence_entry": top["ref_run_id"],
            "more": len(rpt) - 1,
        }

    # 威胁比较表
    table = []
    for fa, f in fams.items():
        if not f["in_analysis_scope"]:
            continue
        run = runs.get(fa)
        chs = by_run.get(run["run_id"], []) if run else []
        st = status_all.get(fa, [])
        by_domain = {}
        for c in chs:
            by_domain.setdefault(c["domain"], c)
        first = chs[0] if chs else None
        origins = {c["value_origin"] for c in chs} or {"constructed"}
        ou, cu = own_unit.get(fa), cmp_unit.get(fa)
        row = {
            "family_asin": fa,
            "rank_now": (snap_rank.get(fa) or {}).get("rank_sub"),
            "units_now": (snap_rank.get(fa) or {}).get("units_rolling30"),
            "own_unit_price": ou,
            "unit_price_now": cu,
            "spark_rank": spark_rank.get(fa, []),
            "spark_price": spark_price.get(fa, []),
            "gap_multiple": round(ou / cu, 2) if (ou and cu) else None,
            "brand": f["brand"],
            "sub_category": f["sub_category"],
            "unit_price_median": f["unit_price_median"],
            "price_band": [f["price_band_low"], f["price_band_high"]],
            "captured_children": f["captured_children"],
            "variant_count": f["variant_count"],
            "in_quick_slot": f["in_quick_slot"],
            "attention_key": run["attention_level"] if run else "unanalyzed",
            "attention": (
                "本次不给关注结论" if run and run["evidence_level"] == "insufficient"
                else D.term(D.ATTENTION, run["attention_level"]) if run else "尚未分析"
            ),
            "threat_label": first["label"] if first else None,
            "market_cell": _cell(by_domain.get("market")),
            "price_cell": _cell(by_domain.get("price_promo")),
            "keyword_cell": _cell(by_domain.get("keyword")),
            "traffic_cell": _cell(by_domain.get("traffic")),
            "happened_from": first["date_from"] if first else None,
            "happened_state": first["current_state"] if first else None,
            "nature": D.mix_nature(origins),
            "state": _evidence_state(run, st),
            "evidence": D.term(D.EVIDENCE, run["evidence_level"]) if run else None,
            "evidence_reason": run["evidence_reason"] if run else None,
            "transition": (D.term(D.TRANSITION, (D.diff(con, run["run_id"]) or {})
                                  .get("transition")) if run else None),
            "run_id": run["run_id"] if run else None,
            "run_date": run["run_date"] if run else None,
            "trigger": D.term(D.TRIGGER, run["trigger"]) if run else None,
            "analysis_state": _analysis_state(con, fa, params),
        }
        table.append(row)

    table = _apply_filters(table, flt, params)
    table.sort(key=_sorter(params.get("sort_by") or "attention"))

    return {
        "as_of": as_of,
        "condition": "正常" if table else "空结果",
        "window": [man["window_from"], man["window_to"]],
        "scope_label": man.get("scope", ""),
        "insight": insight,
        "count_band": count_band,
        "table": table,
        "totals": {
            "monitored": len(fams),
            "analyzed": sum(1 for f in fams.values() if f["in_analysis_scope"]),
            "quick_slot": sum(1 for f in fams.values() if f["in_quick_slot"]),
            "with_run": len(runs),
            "shown": len(table),
        },
        "params": params,
    }


def _sorter(mode: str):
    if mode == "recent":
        return lambda r: (r["happened_from"] is None, _neg_date(r["happened_from"]))
    if mode == "gap":
        return lambda r: -(r.get("gap_multiple") or 0)
    if mode == "rank":
        return lambda r: (r.get("rank_now") is None, r.get("rank_now") or 9999)
    return lambda r: (
        D.ATTENTION_ORDER.get(r["attention_key"], 4),
        0 if r["state"] == "正常" else 1,
        -(r["unit_price_median"] or 0),
    )


def _neg_date(s):
    """降序日期：把 YYYY-MM-DD 变成可反向排序的元组。"""
    if not s:
        return ()
    return tuple(-int(x) for x in s.split("-"))


def _cell(change: dict | None) -> dict | None:
    if not change:
        return None
    return {
        "label": change["label"],
        "direction": change["direction"],
        "magnitude": change["magnitude_value"],
        "magnitude_kind": change["magnitude_kind"],
        "date_from": change["date_from"],
        "state": change["current_state"],
        "represents_family": change["represents_family"],
        "nature": D.nature(change["value_origin"]),
    }


DOMAIN_CELL = {
    "price_promo": "price_cell", "market": "market_cell",
    "keyword": "keyword_cell", "traffic": "traffic_cell",
}


def _apply_filters(table: list[dict], flt: dict, params: dict) -> list[dict]:
    q = (flt.get("q") or "").strip().lower()
    domain = flt.get("domain") or ""
    sub = flt.get("sub") or ""
    ev = flt.get("evidence") or ""
    quick_only = bool(params.get("quick_only"))
    out = []
    for r in table:
        if quick_only and not r["in_quick_slot"]:
            continue
        if q and q not in r["family_asin"].lower() and q not in (r["brand"] or "").lower():
            continue
        if sub and r["sub_category"] != sub:
            continue
        if domain and not r.get(DOMAIN_CELL.get(domain, "")):
            continue
        if ev and r["state"] != ev:
            continue
        out.append(r)
    return out


# ---------------- 详情 ----------------
def detail(con, family_asin: str, params: dict) -> dict | None:
    f = D.one(con, "SELECT * FROM dim_competitor_family WHERE family_asin = ?",
              (family_asin,))
    if not f:
        return None
    man = D.manifest(con)
    as_of = man["as_of"]
    run = D.latest_run(con, family_asin)
    rid = run["run_id"] if run else None
    kids = D.children(con, family_asin)
    st = D.data_status(con, family_asin)
    main = next((k["child_asin"] for k in kids if k["is_main_variant"]),
                kids[0]["child_asin"] if kids else None)
    price = D.price_series(con, main) if main else []
    market = D.market_series(con, family_asin)
    kws = D.keyword_series(con, family_asin)
    traffic = D.traffic_series(con, family_asin)
    own = D.own_unit_price(con, family_asin, as_of)

    chs = D.changes(con, rid) if rid else []
    conc = D.concurrency(con, rid) if rid else []
    opens = D.open_items(con, rid) if rid else []
    imps = D.impacts(con, rid) if rid else []

    # 顶部判断带
    analysis_state = _analysis_state(con, family_asin, params)
    band = {
        "brand": f["brand"], "family_asin": family_asin,
        "sub_category": f["sub_category"],
        "unit_price_median": f["unit_price_median"],
        "price_band": [f["price_band_low"], f["price_band_high"]],
        "captured_children": f["captured_children"],
        "variant_count": f["variant_count"],
        "coverage_note": (
            "导出未覆盖全部变体，能否代表整族由分析逐例判断"
            if (f["variant_count"] or 0) > f["captured_children"] else "覆盖完整"),
        "attention": (
            "本次不给关注结论" if run and run["evidence_level"] == "insufficient"
            else D.term(D.ATTENTION, run["attention_level"]) if run else "尚未分析"
        ),
        "attention_key": run["attention_level"] if run else "unanalyzed",
        "attention_summary": run["attention_summary"] if run else
        "该竞品在监控范围内，还没有分析记录",
        "evidence": D.term(D.EVIDENCE, run["evidence_level"]) if run else None,
        "evidence_reason": run["evidence_reason"] if run else None,
        "state": _evidence_state(run, st),
        "nature": D.mix_nature({c["value_origin"] for c in chs}) if chs else "模拟",
        "run_date": run["run_date"] if run else None,
        "trigger": D.term(D.TRIGGER, run["trigger"]) if run else None,
        "window": [run["window_from"], run["window_to"]] if run else
        [man["window_from"], man["window_to"]],
        "reasons": [
            {"label": r["label"], "note": r["weight_note"]}
            for r in (D.attention_reasons(con, rid) if rid else [])
        ],
        "causal_note": "多类变化同期出现时只表述为同期变化，升级为因果需要额外证据",
    }

    # 四轨共同时间线：每轨都出现，没有事件也给观察区间，粒度写在轨名旁
    tl_items = D.timeline(con, rid) if rid else []
    by_track: dict[str, list[dict]] = {}
    for i in tl_items:
        by_track.setdefault(i["track"], []).append(i)
    for s in st:
        by_track.setdefault("data_status", []).append({
            "track": "data_status", "item_seq": 900 + len(by_track.get("data_status", [])),
            "label": s["label"], "date_from": s["date_from"], "date_to": s["date_to"],
            "ref_change_seq": None, "window_before_from": None, "window_before_to": None,
            "window_after_from": None, "window_after_to": None,
            "note": D.term(D.STATUS, s["status"]),
        })
    tracks = []
    for key, label in D.TRACK.items():
        items = by_track.get(key, [])
        tracks.append({
            "track": key, "label": label, "grain": D.TRACK_GRAIN[key],
            "observed_from": band["window"][0], "observed_to": band["window"][1],
            "items": [{
                "label": i["label"], "date_from": i["date_from"], "date_to": i["date_to"],
                "ref_change_seq": i["ref_change_seq"],
                "window_before": [i["window_before_from"], i["window_before_to"]],
                "window_after": [i["window_after_from"], i["window_after_to"]],
                "note": i.get("note"),
            } for i in items],
        })

    # 事实 / 假设 / 不能确认的因果 三分（V5 §4.4）
    facts = [{
        "label": c["label"], "basis": c["basis"], "domain": D.DOMAIN[c["domain"]],
        "object_id": c["object_id"], "date_from": c["date_from"], "date_to": c["date_to"],
        "state": c["current_state"], "represents_family": c["represents_family"],
        "coverage_note": c["coverage_note"], "nature": D.nature(c["value_origin"]),
        "change_seq": c["change_seq"],
    } for c in chs if c["value_origin"] in ("direct", "derived")]
    simulated = [{
        "label": c["label"], "basis": c["basis"], "domain": D.DOMAIN[c["domain"]],
        "nature": D.nature(c["value_origin"]), "change_seq": c["change_seq"],
    } for c in chs if c["value_origin"] == "constructed"]
    hypotheses = [{
        "statement": o["statement"], "needed_data": o["needed_data"],
        "watch_until": o["watch_until"], "kind": o["item_kind"],
    } for o in opens]
    unknown_causal = [{
        "statement": c["statement"], "missing_evidence": c["missing_evidence"],
        "overlap": [c["overlap_from"], c["overlap_to"]],
        "pair": [c["change_seq_a"], c["change_seq_b"]],
    } for c in conc if not c["causal_ready"]]

    # 关键词入口证据：按词收敂到首末观察
    kw_rows: dict[str, list[dict]] = {}
    for r in kws:
        kw_rows.setdefault(r["keyword"], []).append(r)
    keyword_rows = []
    for k, s in kw_rows.items():
        first, last = s[0], s[-1]
        keyword_rows.append({
            "keyword": k, "keyword_cn": last["keyword_cn"],
            "battleground": last["is_battleground"],
            "monthly_search": last["monthly_search"],
            "rank_now": last["organic_rank"], "rank_start": first["organic_rank"],
            "ad_slot": last["ad_slot"], "is_top3": last["is_top3"],
            "click_share": last["click_share"],
            "conversion_share": last["conversion_share"],
            "nature": D.nature(last["value_origin"]),
            "observed_at": last["observed_date"],
        })
    keyword_rows.sort(key=lambda r: (-r["battleground"], r["rank_now"] or 99))

    last_p = price[-1] if price else None
    gap = None
    if own and last_p and last_p["unit_price"]:
        gap = round(own["unit_price"] / last_p["unit_price"], 2)

    return {
        "as_of": as_of,
        "condition": "正常",
        "analysis_state": analysis_state,
        "band": band,
        "tracks": tracks,
        "family": {
            "children": kids,
            "offers": _strip_origin(D.offers(con, family_asin)),
            "relations": _strip_origin(D.own_relations(con, family_asin)),
            "unit_price_note": "价差按件单价比较：竞品多为 6 件装，自有为 3/4/7 件装",
        },
        "market": {
            "series": _strip_origin(market),
            "rank_now": market[-1]["rank_sub"] if market else None,
            "rank_start": market[0]["rank_sub"] if market else None,
            "units_now": market[-1]["units_rolling30"] if market else None,
            "rating_now": market[-1]["rating"] if market else None,
            "rating_count_now": market[-1]["rating_count"] if market else None,
            "nature": D.mix_nature({r["value_origin"] for r in market}),
        },
        "price": {
            "series": _strip_origin(price), "child_asin": main,
            "promo_bands": D.promo_bands(con, main) if main else [],
            "final_now": last_p["final_price"] if last_p else None,
            "unit_now": last_p["unit_price"] if last_p else None,
            "start": price[0]["final_price"] if price else None,
            "promo_days": sum(1 for r in price if r["promo_kind"] not in (None, "none")),
            "observed_days": len(price),
            "own_unit_price": own["unit_price"] if own else None,
            "own_child_count": own["child_count"] if own else 0,
            "gap_multiple": gap,
            "nature": D.mix_nature({r["value_origin"] for r in price}),
        },
        "keywords": keyword_rows,
        "traffic": {
            "series": _strip_origin(traffic),
            "latest": (_strip_origin(traffic[-1:]) or [None])[0],
            "nature": "模拟",
            "note": "流量结构为第三方估算，不用占比反推竞品花费、预算或出价",
        },
        "evidence": {
            "facts": facts, "simulated": simulated,
            "hypotheses": hypotheses, "unknown_causal": unknown_causal,
            "impacts": [{
                "statement": i["statement"], "shared_keyword": i["shared_keyword"],
                "own_child_asin": i["own_child_asin"],
                "own_parent_asin": i["own_parent_asin"],
                "pressure": i["pressure_dimension"],
            } for i in imps],
        },
        "record": {
            "run_id": rid,
            "diff": (lambda d: {
                "transition": D.term(D.TRANSITION, d["transition"]),
                "statement": d["statement"], "prev_run_id": d["prev_run_id"],
            } if d else None)(D.diff(con, rid) if rid else None),
            "handoffs": [{
                "target": "关键词页" if h["target_page"] == "keyword" else "广告页",
                "fact": h["observable_fact"], "entry": h["detail_entry"],
                "frozen_run_id": h["frozen_run_id"],
                "evidence": D.term(D.EVIDENCE, h["evidence_level"]),
            } for h in (D.handoffs(con, rid) if rid else [])],
            "data_status": [{
                "label": s["label"], "state": D.term(D.STATUS, s["status"]),
                "range": [s["date_from"], s["date_to"]],
            } for s in st],
        },
        "params": params,
    }
