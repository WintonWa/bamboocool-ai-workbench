#!/usr/bin/env python3
"""Build the keyword Agent's answer-free, allow-listed fact contract.

The five L7/L8/L9 judgment tables are deliberately never queried. Candidate
identities are derived from raw snapshots, daily positions and keyword-child
relationships, so old demo judgments cannot leak through IDs or row counts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections import defaultdict
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PROJECT.parent / "07-关键词分析模块/02-数据构建/v0.1.0/keyword_demo.sqlite"
RULE_VERSION = "keyword-agent-contract-v2"
DATASET_VERSION = "0.1.0"
DEFAULT_PARAMS = {
    "compare": "day",
    "rank_shift": 3,
    "group_dedup": True,
    "weights": {
        "w_demand": 0.30, "w_change": 0.30,
        "w_push": 0.20, "w_evidence": 0.20,
    },
}


def _rows(con: sqlite3.Connection, sql: str, args: tuple = ()) -> list[dict]:
    return [dict(row) for row in con.execute(sql, args)]


def _one(con: sqlite3.Connection, sql: str, args: tuple = ()):
    row = con.execute(sql, args).fetchone()
    return row[0] if row else None


def _terms(con: sqlite3.Connection) -> list[dict]:
    # library_status/operator_role are explicit Demo inputs in contract v2.
    return _rows(con, """
        SELECT keyword_id, keyword, keyword_raw, keyword_cn, alias_key,
               library_status, library_status_label, is_monitored,
               selection_bucket, primary_category, all_category_tags,
               matched_brand, brand_role, brand_role_label,
               operator_role, operator_role_label, operator_role_confirmed,
               operator_role_seed_word, relevance, traffic_word_type,
               first_seen_date, last_updated_date, source_files
        FROM dim_keyword_term ORDER BY keyword_id
    """)


def _market_candidates(con: sqlite3.Connection, monitored: set[str]) -> list[dict]:
    # Deliberately omit change_shape, comparable_block_reason, suggested bids,
    # value_origin and rule_version: all are forbidden by the v2 handoff.
    raw = _rows(con, """
        SELECT snapshot_id, keyword_id, keyword, source_code, period_type,
               period_index, period_start, period_end, measure_definition,
               data_state, comparable_flag, aba_week_rank, product_count,
               demand_supply_ratio, ad_competitor_count, click_share_top3,
               conv_share_top3, monthly_search_volume,
               monthly_purchase_volume, purchase_rate, aba_month_rank,
               impressions, clicks, traffic_share, est_weekly_impressions
        FROM fact_keyword_market_snapshot
        WHERE source_code='kw3' AND period_type IN ('week','month')
        ORDER BY keyword_id, period_type, period_end, period_index
    """)
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in raw:
        if row["keyword_id"] in monitored:
            grouped[(row["keyword_id"], row["period_type"])].append(row)
    output: list[dict] = []
    for (keyword_id, period_type), series in sorted(grouped.items()):
        if not series:
            continue
        window = series[-4:]
        current = window[-1]
        previous = window[-2] if len(window) > 1 else None
        demand_field = "monthly_search_volume" if period_type == "month" else "est_weekly_impressions"
        output.append({
            "candidate_id": f"mc_{keyword_id}_{period_type}",
            "keyword_id": keyword_id,
            "keyword": current["keyword"],
            "source_code": "kw3",
            "period_type": period_type,
            "demand_metric": demand_field,
            "from_snapshot_id": previous["snapshot_id"] if previous else None,
            "to_snapshot_id": current["snapshot_id"],
            "from_period_end": previous["period_end"] if previous else None,
            "to_period_end": current["period_end"],
            "from_value": previous.get(demand_field) if previous else None,
            "to_value": current.get(demand_field),
            "from_data_state": previous["data_state"] if previous else "no_data",
            "to_data_state": current["data_state"],
            "from_comparable": previous["comparable_flag"] if previous else 0,
            "to_comparable": current["comparable_flag"],
            "from_product_count": previous["product_count"] if previous else None,
            "to_product_count": current["product_count"],
            "from_ad_competitor_count": previous["ad_competitor_count"] if previous else None,
            "to_ad_competitor_count": current["ad_competitor_count"],
            "from_demand_supply_ratio": previous["demand_supply_ratio"] if previous else None,
            "to_demand_supply_ratio": current["demand_supply_ratio"],
            "history": [{
                "period_end": r["period_end"], "data_state": r["data_state"],
                "comparable_flag": r["comparable_flag"],
                "demand_value": r.get(demand_field),
                "product_count": r["product_count"],
                "ad_competitor_count": r["ad_competitor_count"],
            } for r in window],
        })
    return output


def _coverage_candidates(con: sqlite3.Connection, as_of_date: str) -> list[dict]:
    pairs = _rows(con, """
        SELECT p.pair_id, p.keyword_id, p.keyword, p.child_asin,
               p.anchor_band, p.monitor_from,
               t.operator_role, t.operator_role_label
        FROM dim_keyword_child_pair p
        JOIN dim_keyword_term t ON t.keyword_id=p.keyword_id
        ORDER BY p.pair_id
    """)
    positions = _rows(con, """
        SELECT pair_id, date, organic_rank, organic_state, ad_rank, ad_state,
               coverage_state, collect_depth
        FROM fact_keyword_child_position_daily
        WHERE date <= ? ORDER BY pair_id, date
    """, (as_of_date,))
    by_pair: dict[str, list[dict]] = defaultdict(list)
    for row in positions:
        by_pair[row["pair_id"]].append(row)
    output: list[dict] = []
    for pair in pairs:
        history = by_pair.get(pair["pair_id"], [])[-4:]
        if not history:
            continue
        current = history[-1]
        previous = history[-2] if len(history) > 1 else None
        for channel in ("organic", "ad"):
            rank_key, state_key = f"{channel}_rank", f"{channel}_state"
            output.append({
                "candidate_id": f"cc_{pair['pair_id']}_{channel}",
                **pair,
                "channel": channel,
                "from_date": previous["date"] if previous else None,
                "to_date": current["date"],
                "from_rank": previous.get(rank_key) if previous else None,
                "to_rank": current.get(rank_key),
                "from_state": previous.get(state_key) if previous else "no_data",
                "to_state": current.get(state_key),
                "from_coverage_state": previous.get("coverage_state") if previous else "no_data",
                "to_coverage_state": current.get("coverage_state"),
                "collect_depth": current.get("collect_depth"),
                "history": [{
                    "date": r["date"], "rank": r.get(rank_key),
                    "state": r.get(state_key),
                    "coverage_state": r.get("coverage_state"),
                } for r in history],
            })
    return output


def _evidence_candidates(con: sqlite3.Connection, as_of_date: str) -> list[dict]:
    # pair_shape(_label) is intentionally omitted: it is a forbidden old
    # judgment. Product goals, inventory absorb and operator role are approved
    # inputs originating from other modules/judgment points.
    return _rows(con, """
        SELECT 'ec_' || p.pair_id AS candidate_id,
               p.pair_id, p.keyword_id, p.keyword, p.child_asin,
               p.anchor_band, p.monitor_from,
               t.library_status, t.library_status_label,
               t.operator_role, t.operator_role_label,
               t.operator_role_confirmed, t.relevance,
               t.primary_category, t.all_category_tags,
               g.product_goal, g.product_goal_label,
               g.push_role, g.push_role_label, g.product_lifecycle,
               a.absorb_state, a.absorb_state_label,
               a.base_stockout_date, a.stress_stockout_date,
               a.latest_order_date, a.days_to_base_stockout,
               a.dynamic_safety_days, a.suggested_replenishment_qty,
               a.projected_lost_sales_units, a.confidence_score,
               d.date AS ref_position_date,
               d.organic_rank, d.organic_state,
               d.ad_rank, d.ad_state, d.coverage_state, d.collect_depth,
               m.monthly_search_volume, m.monthly_purchase_volume,
               m.purchase_rate, m.aba_month_rank,
               m.product_count, m.ad_competitor_count,
               m.demand_supply_ratio
        FROM dim_keyword_child_pair p
        JOIN dim_keyword_term t ON t.keyword_id=p.keyword_id
        LEFT JOIN dim_keyword_child_goal g
          ON g.child_asin=p.child_asin AND g.is_current=1
        LEFT JOIN fact_keyword_child_absorb a ON a.child_asin=p.child_asin
        LEFT JOIN fact_keyword_child_position_daily d
          ON d.pair_id=p.pair_id AND d.date=?
        LEFT JOIN fact_keyword_market_snapshot m
          ON m.keyword_id=p.keyword_id AND m.source_code='kw3'
         AND m.period_type='month' AND m.period_index=(
           SELECT MAX(m2.period_index) FROM fact_keyword_market_snapshot m2
           WHERE m2.keyword_id=p.keyword_id AND m2.source_code='kw3'
             AND m2.period_type='month')
        ORDER BY p.pair_id
    """, (as_of_date,))


def _second_source_observation(con: sqlite3.Connection) -> dict:
    rows = _rows(con, """
        SELECT source_code, period_type, period_end, product_count,
               ad_competitor_count, click_share_top3, conv_share_top3
        FROM fact_keyword_market_snapshot
        WHERE keyword_id='kw_00001' AND source_code IN ('kw2','kw3')
        ORDER BY source_code, period_end DESC
    """)
    latest: dict[str, dict] = {}
    for row in rows:
        latest.setdefault(row["source_code"], row)
    return {"keyword_id": "kw_00001", "sources": latest}


def build_payload(database: Path, scope: str) -> dict:
    if scope != "all":
        raise ValueError("P0 completed 运行只允许 --scope all")
    con = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        scope_row = dict(con.execute("""
            SELECT scope_id, site, product_line, as_of_date,
                   monitored_keyword_count, focus_child_count,
                   focus_child_asins, library_keyword_count
            FROM dim_keyword_scope LIMIT 1
        """).fetchone())
        terms = _terms(con)
        monitored = {r["keyword_id"] for r in terms if r["is_monitored"] == 1}
        market = _market_candidates(con, monitored)
        coverage = _coverage_candidates(con, scope_row["as_of_date"])
        evidence = _evidence_candidates(con, scope_row["as_of_date"])
        counts = {
            "terms": len(terms),
            "market_candidates": len(market),
            "coverage_candidates": len(coverage),
            "evidence_candidates": len(evidence),
            "pairs": _one(con, "SELECT COUNT(*) FROM dim_keyword_child_pair"),
            "children": _one(con, "SELECT COUNT(DISTINCT child_asin) FROM dim_keyword_child_pair"),
        }
        fingerprint = {
            "dataset_version": DATASET_VERSION, "rule_version": RULE_VERSION,
            "scope": scope_row, "params": DEFAULT_PARAMS, "terms": terms,
            "market_candidates": market, "coverage_candidates": coverage,
            "evidence_candidates": evidence,
        }
        encoded = json.dumps(fingerprint, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":")).encode()
        return {
            "ok": True, "database": str(database),
            "dataset_version": DATASET_VERSION, "rule_version": RULE_VERSION,
            "scope": scope, "as_of_date": scope_row["as_of_date"],
            "site": scope_row["site"], "product_line": scope_row["product_line"],
            "context_hash": hashlib.sha256(encoded).hexdigest(),
            "params": DEFAULT_PARAMS, "counts": counts, "terms": terms,
            "market_candidates": market, "coverage_candidates": coverage,
            "evidence_candidates": evidence,
            "golden": {"second_source_observation": _second_source_observation(con)},
        }
    finally:
        con.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--scope", default="all")
    args = parser.parse_args()
    try:
        payload = build_payload(args.database.resolve(), args.scope)
    except (ValueError, sqlite3.Error, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
