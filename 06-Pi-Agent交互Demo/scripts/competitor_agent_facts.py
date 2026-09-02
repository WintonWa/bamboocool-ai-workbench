#!/usr/bin/env python3
"""Build a read-only competitor Agent context from the observation layer.

This bridge deliberately never selects from the ten historical judgment tables.
It reduces observation rows to locked dates, numbers and object references; Pi is
still responsible for the qualitative decisions and finished Chinese wording.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import sys
from datetime import date
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
WORKBENCH = PROJECT.parent / "09-工作台"
sys.path.insert(0, str(WORKBENCH))

from modules.competitor import data as D  # noqa: E402

DEFAULT_THRESHOLDS = {
    "price_drop_pct": 5.0,
    "gap_shift_pct": 10.0,
    "rank_shift_pct": 15.0,
    "kw_rank_shift": 3,
    "min_duration_days": 7,
    "family_coverage_pct": 30.0,
    "stale_days": 14,
}
STAGES = [
    "context", "evidence", "changes", "representation", "impacts",
    "concurrency", "attention", "outputs", "contract",
]


def _days(date_from: str, date_to: str) -> int:
    return (date.fromisoformat(date_to) - date.fromisoformat(date_from)).days + 1


def _duration_admitted(effects: dict, candidate_id: str, date_from: str, date_to: str) -> tuple[bool, int]:
    duration = _days(date_from, date_to)
    admitted = duration >= int(effects["min_duration_days"]["threshold"])
    effects["min_duration_days"]["evaluations"].append({
        "candidate_id": candidate_id, "duration_days": duration, "admitted": admitted,
    })
    return admitted, duration


def _coverage(family: dict, observed: int, affected: int, main_affected: bool, effects: dict) -> dict:
    pct = round(affected / observed * 100, 1) if observed else 0.0
    required = float(effects["family_coverage_pct"]["threshold"])
    threshold_met = pct >= required
    eligible = threshold_met and main_affected
    effects["family_coverage_pct"]["evaluations"].append({
        "affected_observed_children": affected,
        "observed_children": observed,
        "coverage_pct": pct,
        "threshold_met": threshold_met,
        "main_variant_affected": main_affected,
        "family_eligible": eligible,
    })
    return {
        "affected_observed_children": affected,
        "observed_children": observed,
        "captured_children": family["captured_children"],
        "variant_count": family["variant_count"],
        "coverage_pct": pct,
        "coverage_threshold_pct": required,
        "coverage_threshold_met": threshold_met,
        "main_variant_affected": main_affected,
        "family_eligible": eligible,
    }


def _price_rows(con: sqlite3.Connection, child_asin: str) -> list[dict]:
    return D.rows(con, """
        SELECT date, unit_price, final_price, promo_kind, coupon_pct, value_origin
        FROM fact_competitor_price_daily WHERE child_asin=? ORDER BY date
    """, (child_asin,))


def _price_candidate(con, family: dict, thresholds: dict, effects: dict) -> list[dict]:
    children = D.children(con, family["family_asin"])
    series = {c["child_asin"]: _price_rows(con, c["child_asin"]) for c in children}
    drop = float(thresholds["price_drop_pct"])
    candidates: list[dict] = []

    # A promotion interval is an observable event. Pick the longest one so the
    # model sees the strongest local/family candidate, not every noisy day.
    promo = None
    for child in children:
        rows = series[child["child_asin"]]
        active = [r for r in rows if r["promo_kind"] not in (None, "none")]
        if active and (promo is None or len(active) > len(promo["rows"])):
            promo = {"child": child, "rows": active, "all": rows}
    if promo:
        child, active, rows = promo["child"], promo["rows"], promo["all"]
        baseline = next((r["unit_price"] for r in rows if r["date"] < active[0]["date"]), rows[0]["unit_price"])
        low = min(r["unit_price"] for r in active if r["unit_price"] is not None)
        magnitude = round((low / baseline - 1) * 100, 1) if baseline and low else None
        affected = sum(1 for values in series.values() if any(r["promo_kind"] not in (None, "none") for r in values))
        admitted, duration = _duration_admitted(
            effects, "price-promo-1", active[0]["date"], active[-1]["date"],
        )
        if magnitude is not None and magnitude <= -drop and admitted:
            candidates.append({
            "candidate_id": "price-promo-1",
            "allowed_domains": ["price_promo"],
            "allowed_directions": ["down"],
            "allowed_current_states": ["still_running", "restored", "ended"],
            "object_level": "child",
            "object_id": child["child_asin"],
            "date_from": active[0]["date"],
            "date_to": active[-1]["date"],
            "magnitude_kind": "pct",
            "magnitude_value": magnitude,
            "duration_days": duration,
            "value_origin": "constructed",
            "evidence_ids": [f"price:{child['child_asin']}:{active[0]['date']}:{active[-1]['date']}"],
            "coverage": {**_coverage(
                family, len(children), affected, bool(child["is_main_variant"]), effects,
            ), "is_main_variant": bool(child["is_main_variant"])},
            "locked_fact": f"{child['child_asin']} 活动件单价最大下降 {abs(magnitude or 0):.1f}%，活动区间 {active[0]['date']} 至 {active[-1]['date']}",
            })

    main = next((c for c in children if c["is_main_variant"]), children[0] if children else None)
    if main:
        rows = series[main["child_asin"]]
        if rows and rows[0]["unit_price"] and rows[-1]["unit_price"]:
            magnitude = round((rows[-1]["unit_price"] / rows[0]["unit_price"] - 1) * 100, 1)
            if magnitude <= -drop and not any(c["candidate_id"] == "price-promo-1" for c in candidates):
                threshold_value = rows[0]["unit_price"] * (1 - drop / 100)
                start = next(r for r in rows if r["unit_price"] <= threshold_value)
                affected = 0
                for values in series.values():
                    if values and values[0]["unit_price"] and values[-1]["unit_price"] <= values[0]["unit_price"] * (1 - drop / 100):
                        affected += 1
                admitted, duration = _duration_admitted(
                    effects, "price-trend-1", start["date"], rows[-1]["date"],
                )
                if admitted:
                    candidates.append({
                    "candidate_id": "price-trend-1",
                    "allowed_domains": ["price_promo"],
                    "allowed_directions": ["down"],
                    "allowed_current_states": ["still_running"],
                    "object_level": "family",
                    "object_id": family["family_asin"],
                    "date_from": start["date"],
                    "date_to": None,
                    "magnitude_kind": "pct",
                    "magnitude_value": magnitude,
                    "duration_days": duration,
                    "value_origin": "constructed",
                    "evidence_ids": [f"price:{main['child_asin']}:{rows[0]['date']}:{rows[-1]['date']}"],
                    "coverage": {**_coverage(
                        family, len(children), affected, True, effects,
                    ), "is_main_variant": True},
                    "locked_fact": f"主销子体件单价从 {rows[0]['unit_price']:.3f} 降至 {rows[-1]['unit_price']:.3f}，变化 {magnitude:.1f}%，无活动标记",
                    })
    return candidates


def _market_candidate(con, family: dict, thresholds: dict, effects: dict) -> list[dict]:
    rows = D.market_series(con, family["family_asin"])
    threshold = float(thresholds["rank_shift_pct"])
    effect = effects["rank_shift_pct"]
    effect["input_rows"] = len(rows)
    if len(rows) < 2:
        effect.update({"applicable": False, "reason": "小类排名观察不足两期", "admitted": False})
        return []
    first, last = rows[0], rows[-1]
    baseline, current = first["rank_sub"], last["rank_sub"]
    if not baseline or current is None:
        effect.update({"applicable": False, "reason": "小类排名端点缺失", "admitted": False})
        return []
    shift = round((current / baseline - 1) * 100, 1)
    effect.update({"applicable": True, "observed_shift_pct": shift})
    if abs(shift) < threshold:
        effect.update({"reason": "小类排名变动未达阈值", "admitted": False})
        return []
    improving = shift < 0
    crossed = lambda row: (
        row["rank_sub"] is not None
        and ((baseline - row["rank_sub"]) / baseline * 100 >= threshold if improving
             else (row["rank_sub"] - baseline) / baseline * 100 >= threshold)
    )
    start = next((row for row in rows if crossed(row)), last)
    admitted, duration = _duration_admitted(
        effects, "market-rank-1", start["date"], last["date"],
    )
    effect.update({
        "duration_days": duration,
        "reason": None if admitted else "排名变动持续时长未达阈值",
        "admitted": admitted,
    })
    if not admitted:
        return []
    return [{
        "candidate_id": "market-rank-1",
        "allowed_domains": ["market"],
        "allowed_directions": ["up" if improving else "down"],
        "allowed_current_states": ["still_running"],
        "object_level": "family", "object_id": family["family_asin"],
        "date_from": start["date"], "date_to": None,
        "magnitude_kind": "pct", "magnitude_value": shift,
        "duration_days": duration, "value_origin": last["value_origin"],
        "evidence_ids": [f"market:{family['family_asin']}:{first['date']}:{last['date']}"],
        "coverage": {"family_eligible": True, "affected_observed_children": None,
                     "observed_children": None, "captured_children": family["captured_children"],
                     "variant_count": family["variant_count"], "is_main_variant": None,
                     "coverage_threshold_applicable": False},
        "locked_fact": f"小类排名从 {baseline} 变为 {current}，相对变动 {shift:.1f}%",
    }]


def _keyword_candidates(con, family: dict, thresholds: dict, effects: dict) -> list[dict]:
    fa = family["family_asin"]
    rows = D.keyword_series(con, fa)
    out: list[dict] = []
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row["keyword"], []).append(row)
    for keyword, values in grouped.items():
        first, last = values[0], values[-1]
        applicable = first["organic_rank"] is not None and last["organic_rank"] is not None
        shift = first["organic_rank"] - last["organic_rank"] if applicable else None
        threshold_met = applicable and shift >= int(thresholds["kw_rank_shift"])
        evaluation = {
            "keyword": keyword, "applicable": applicable,
            "observed_shift_positions": shift, "threshold_met": threshold_met,
            "admitted": False,
        }
        effects["kw_rank_shift"]["evaluations"].append(evaluation)
        if threshold_met:
            start = next((row for row in values if row["organic_rank"] is not None
                          and first["organic_rank"] - row["organic_rank"] >= int(thresholds["kw_rank_shift"])), last)
            admitted, duration = _duration_admitted(
                effects, f"keyword-{len(out) + 1}",
                start["observed_date"], last["observed_date"],
            )
            evaluation["duration_days"] = duration
            evaluation["admitted"] = admitted
            if not admitted:
                continue
            out.append({
                "candidate_id": f"keyword-{len(out) + 1}", "allowed_domains": ["keyword"],
                "allowed_directions": ["up"], "allowed_current_states": ["still_running"],
                "object_level": "keyword", "object_id": keyword,
                "date_from": start["observed_date"], "date_to": None,
                "magnitude_kind": "position", "magnitude_value": last["organic_rank"] - first["organic_rank"],
                "duration_days": duration,
                "value_origin": last["value_origin"],
                "evidence_ids": [f"keyword:{fa}:{keyword}:{last['observed_date']}"],
                "coverage": {"family_eligible": True, "affected_observed_children": None,
                             "observed_children": None, "captured_children": family["captured_children"],
                             "variant_count": family["variant_count"], "is_main_variant": None,
                             "coverage_threshold_applicable": False},
                "locked_fact": f"关键词 {keyword} 自然位从 {first['organic_rank']} 变为 {last['organic_rank']}",
            })
    return out


def _traffic_candidate(con, family: dict, effects: dict) -> list[dict]:
    rows = D.traffic_series(con, family["family_asin"])
    effects["traffic_series"] = {"input_rows": len(rows), "applicable": len(rows) >= 2}
    if len(rows) < 2:
        effects["traffic_series"].update({"admitted": False, "reason": "流量结构观察不足两期"})
        return []
    first, last = rows[0], rows[-1]
    if first["ad_share"] is None or last["ad_share"] is None:
        effects["traffic_series"].update({"admitted": False, "reason": "广告流量占比端点缺失"})
        return []
    delta = round((last["ad_share"] - first["ad_share"]) * 100, 1)
    admitted, duration = _duration_admitted(
        effects, "traffic-1", first["period_start"], last["period_end"],
    )
    admitted = admitted and delta != 0
    effects["traffic_series"].update({
        "observed_shift_pct_points": delta,
        "duration_days": duration,
        "admitted": admitted,
        "reason": None if admitted else "流量结构未变或持续时长未达阈值",
    })
    if not admitted:
        return []
    return [{
        "candidate_id": "traffic-1", "allowed_domains": ["traffic"],
        "allowed_directions": ["up" if delta > 0 else "down"],
        "allowed_current_states": ["still_running"],
        "object_level": "family", "object_id": family["family_asin"],
        "date_from": first["period_start"], "date_to": None,
        "magnitude_kind": "pct", "magnitude_value": delta, "duration_days": duration,
        "value_origin": last["value_origin"],
        "evidence_ids": [f"traffic:{family['family_asin']}:{first['period_start']}:{last['period_end']}"],
        "coverage": {"family_eligible": True, "affected_observed_children": None,
                     "observed_children": None, "captured_children": family["captured_children"],
                     "variant_count": family["variant_count"], "is_main_variant": None,
                     "coverage_threshold_applicable": False},
        "locked_fact": f"广告流量占比从 {first['ad_share']:.3f} 变为 {last['ad_share']:.3f}，不能反推花费、预算或出价",
    }]


def _gap_candidate(family: dict, statuses: list[dict]) -> list[dict]:
    interrupted = next((s for s in statuses if s["status"] == "interrupted"), None)
    if not interrupted:
        return []
    return [{
        "candidate_id": "data-gap-1", "allowed_domains": ["price_promo"],
        "allowed_directions": ["neutral"], "allowed_current_states": ["unconfirmed"],
        "object_level": "family", "object_id": family["family_asin"],
        "date_from": interrupted["date_from"], "date_to": interrupted["date_to"],
        "magnitude_kind": None, "magnitude_value": None, "value_origin": "constructed",
        "evidence_gap": True,
        "evidence_ids": [f"status:{interrupted['status_id']}"],
        "coverage": {"family_eligible": False, "affected_observed_children": None,
                     "observed_children": None, "captured_children": family["captured_children"],
                     "variant_count": family["variant_count"], "is_main_variant": None},
        "locked_fact": f"{interrupted['date_from']} 至 {interrupted['date_to']} 观察中断，缺口两端数值不得直接相减",
    }]


def _effective_statuses(statuses: list[dict], thresholds: dict, effects: dict) -> list[dict]:
    effective: list[dict] = []
    stale_limit = int(thresholds["stale_days"])
    stale_effect = effects["stale_days"]
    for item in statuses:
        if item["status"] != "stale":
            effective.append(item)
            continue
        age = _days(item["date_from"], item["date_to"]) - 1
        admitted = age >= stale_limit
        stale_effect["evaluations"].append({
            "status_id": item["status_id"], "age_days": age, "admitted": admitted,
        })
        if admitted:
            effective.append({**item, "age_days": age, "stale_threshold_days": stale_limit})
    if not stale_effect["evaluations"]:
        stale_effect["reason"] = "当前对象没有可重算的过期事件"
    return effective


def _missing_keyword_candidate(family: dict, manifest: dict) -> dict:
    """Represent missing raw rows, never a synthetic keyword result."""
    return {
        "candidate_id": "data-gap-keyword-1", "allowed_domains": ["keyword"],
        "allowed_directions": ["neutral"], "allowed_current_states": ["unconfirmed"],
        "object_level": "family", "object_id": family["family_asin"],
        "date_from": manifest["window_from"], "date_to": manifest["as_of"],
        "magnitude_kind": None, "magnitude_value": None, "value_origin": "derived",
        "evidence_gap": True,
        "evidence_ids": [f"missing:fact_competitor_keyword_rank:{family['family_asin']}"],
        "coverage": {"family_eligible": False, "affected_observed_children": None,
                     "observed_children": None, "captured_children": family["captured_children"],
                     "variant_count": family["variant_count"], "is_main_variant": None},
        "locked_fact": "当前产品族没有关键词位次记录，也没有共同词关系记录，无法形成关键词抢位判断",
    }


def _relations(con, family_asin: str, as_of: str, thresholds: dict, effects: dict) -> list[dict]:
    own = D.own_relations(con, family_asin)
    main = D.one(con, """
        SELECT child_asin FROM dim_competitor_child
        WHERE family_asin=? ORDER BY is_main_variant DESC, child_asin LIMIT 1
    """, (family_asin,))
    competitor_rows = _price_rows(con, main["child_asin"]) if main else []
    first_unit = competitor_rows[0]["unit_price"] if competitor_rows else None
    last_unit = competitor_rows[-1]["unit_price"] if competitor_rows else None
    out: list[dict] = []
    for row in own:
        price = D.one(con, """
            SELECT p.selling_price, c.combination FROM pr.fact_child_price_daily p
            JOIN pr.dim_product_child c USING(child_asin)
            WHERE p.child_asin=? AND p.date=?
        """, (row["child_asin"], as_of))
        pack_match = re.match(r"(\d+)", price["combination"] or "") if price else None
        pack = int(pack_match.group(1)) if pack_match else None
        own_pack_price = price["selling_price"] if price else None
        own_unit = own_pack_price / pack if own_pack_price is not None and pack else None
        applicable = bool(own_unit and first_unit and last_unit)
        shift = round((last_unit / first_unit - 1) * 100, 1) if applicable else None
        eligible = applicable and abs(shift) >= float(thresholds["gap_shift_pct"])
        effects["gap_shift_pct"]["evaluations"].append({
            "rel_id": row["rel_id"], "applicable": applicable,
            "observed_shift_pct": shift, "eligible": eligible,
        })
        out.append({
            **row,
            "own_pack_price": own_pack_price,
            "own_unit_price": round(own_unit, 3) if own_unit is not None else None,
            "gap_shift_pct_value": shift,
            "gap_shift_threshold_pct": float(thresholds["gap_shift_pct"]),
            "gap_shift_applicable": applicable,
            "gap_shift_eligible": eligible,
        })
    if not effects["gap_shift_pct"]["evaluations"]:
        effects["gap_shift_pct"]["reason"] = "当前对象没有可解析的自有竞争关系"
    return out


def _sidecar_previous(family_asin: str) -> dict | None:
    default = WORKBENCH / "modules/competitor/derived/competitor_agent_state.sqlite"
    path = Path(os.environ.get("WORKBENCH_COMPETITOR_AGENT_DB", default))
    if not path.exists():
        return None
    con = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        exists = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='fact_competitor_agent_execution'").fetchone()
        if not exists:
            return None
        row = con.execute("""
            SELECT e.run_id, e.created_at, r.attention_level, r.evidence_level
            FROM fact_competitor_agent_execution e
            JOIN fact_competitor_analysis_run r USING(run_id)
            WHERE e.family_asin=? AND e.status='completed'
            ORDER BY julianday(e.created_at) DESC, e.created_at DESC LIMIT 1
        """, (family_asin,)).fetchone()
        return dict(row) if row else None
    finally:
        con.close()


def build(family_asin: str, thresholds: dict) -> dict:
    con = D.connect()
    try:
        family = D.one(con, "SELECT * FROM dim_competitor_family WHERE family_asin=?", (family_asin,))
        if not family:
            return {"ok": False, "error": "unknown_family", "family_asin": family_asin}
        man = D.manifest(con)
        effects = {
            "price_drop_pct": {"threshold": float(thresholds["price_drop_pct"])},
            "gap_shift_pct": {"threshold": float(thresholds["gap_shift_pct"]), "evaluations": []},
            "rank_shift_pct": {"threshold": float(thresholds["rank_shift_pct"])},
            "kw_rank_shift": {"threshold": int(thresholds["kw_rank_shift"]), "evaluations": []},
            "min_duration_days": {"threshold": int(thresholds["min_duration_days"]), "evaluations": []},
            "family_coverage_pct": {"threshold": float(thresholds["family_coverage_pct"]), "evaluations": []},
            "stale_days": {"threshold": int(thresholds["stale_days"]), "evaluations": []},
        }
        raw_statuses = D.data_status(con, family_asin)
        statuses = _effective_statuses(raw_statuses, thresholds, effects)
        keyword_rows = D.keyword_series(con, family_asin)
        keywords = D.rows(con, """
            SELECT b.keyword, k.is_battleground, k.monthly_search, 'observed' source_kind
            FROM bridge_competitor_keyword b JOIN dim_competitor_keyword k USING(keyword)
            WHERE b.family_asin=? ORDER BY k.is_battleground DESC, k.monthly_search DESC
        """, (family_asin,))
        candidates = _gap_candidate(family, statuses)
        if not candidates:
            price_candidates = _price_candidate(con, family, thresholds, effects)
            candidates.extend(price_candidates)
            market_candidates = _market_candidate(con, family, thresholds, effects)
            keyword_candidates = _keyword_candidates(con, family, thresholds, effects)
            traffic_candidates = _traffic_candidate(con, family, effects)
            candidates.extend(market_candidates)
            candidates.extend(keyword_candidates)
            candidates.extend(traffic_candidates)
            # Traffic-mix estimates alone cannot substitute for absent keyword
            # ranks or a shared-keyword bridge. Keep the raw traffic candidate
            # visible, but make the missing decision-grade input short-circuit.
            if (not price_candidates and not market_candidates and not keyword_candidates
                    and not keyword_rows and not keywords):
                candidates.insert(0, _missing_keyword_candidate(family, man))
        if not candidates:
            # A neutral candidate makes a completed "no significant change" run
            # explicit without inventing a metric movement.
            candidates.append({
                "candidate_id": "stable-1", "allowed_domains": ["market"],
                "allowed_directions": ["neutral"], "allowed_current_states": ["ended"],
                "object_level": "family", "object_id": family_asin,
                "date_from": man["window_from"], "date_to": man["as_of"],
                "magnitude_kind": None, "magnitude_value": None, "value_origin": "constructed",
                "evidence_ids": [f"family:{family_asin}"],
                "coverage": {"family_eligible": True, "affected_observed_children": 0,
                             "observed_children": len(D.children(con, family_asin)),
                             "captured_children": family["captured_children"],
                             "variant_count": family["variant_count"], "is_main_variant": None,
                             "coverage_threshold_applicable": False},
                "locked_fact": "观察窗内未发现达到当前阈值的显著变化",
            })
        relations = _relations(con, family_asin, man["as_of"], thresholds, effects)
        fingerprint = D.source_context_hash(con, family_asin, thresholds)
        threshold_fingerprint = hashlib.sha256(json.dumps(
            thresholds, sort_keys=True, separators=(",", ":")
        ).encode()).hexdigest()
        return {
            "ok": True,
            "family_asin": family_asin,
            "data_as_of": man["as_of"],
            "run_date": man["as_of"],
            "window_from": man["window_from"],
            "window_to": man["window_to"],
            "dataset_version": man.get("dataset_version", "competitor-v0.1.0"),
            "schema_version": "competitor-agent-contract-v1",
            "method_version": "competitor-agent-v1",
            "rule_version": "competitor-thresholds-v1",
            "source_context_hash": fingerprint,
            "threshold_fingerprint": threshold_fingerprint,
            "thresholds": thresholds,
            "stage_order": STAGES,
            "family": family,
            "status_events": statuses,
            "change_candidates": candidates,
            "relation_candidates": relations,
            "shared_keyword_candidates": keywords,
            "threshold_effects": effects,
            "observation_coverage": {
                "keyword_rank_rows": len(keyword_rows),
                "keyword_relation_rows": len(keywords),
            },
            "previous_run": _sidecar_previous(family_asin),
            "source_boundary": {
                "observation_tables_read_only": True,
                "historical_judgment_tables_read": False,
                "traffic_budget_inference_allowed": False,
                "causal_ready": 0,
            },
        }
    finally:
        con.close()


def main() -> int:
    family_asin = (sys.argv[1] if len(sys.argv) > 1 else "B0CJ9QLVPP").strip().upper()
    thresholds = dict(DEFAULT_THRESHOLDS)
    if len(sys.argv) > 2:
        thresholds.update(json.loads(sys.argv[2]))
    payload = build(family_asin, thresholds)
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    return 0 if payload.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
