#!/usr/bin/env python3
"""Build clean advertising-Agent facts without reading replay conclusions.

Phase 1 intentionally exposes only B0b. The bridge reads operator-set goals,
raw advertising facts, raw product facts, and (when present) a real upstream
inventory-Agent run. It never imports the workbench replay calculator and it
never reads any ``ext_*`` answer table.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any


PROJECT = Path(__file__).resolve().parents[1]
REBUILD = PROJECT.parent
ADS_DB = REBUILD / "04-广告分析模块/02-数据构建/v0.2.0/advertising_demo.sqlite"
EXT_DB = REBUILD / "04-广告分析模块/02-数据构建/page2-ext/page2_decision_ext.sqlite"
PRODUCT_DB = REBUILD / "02-产品销售库存模块/02-数据构建/v0.3.0/bamboocool_product_sales_inventory_v0.3.0.sqlite"
COMPETITOR_DB = REBUILD / "08-竞品分析模块/02-数据构建/v0.1.0/competitor_demo.sqlite"
INVENTORY_AGENT_DB = REBUILD / "09-工作台/modules/inventory/derived/verdict_agent.sqlite"

DATASET_VERSION = "ads-v0.2.0+product-v0.3.0"
RULE_VERSION = "ads-b0b-constraint-v2"
PROMO_ROLES = ("promoted_asin", "positive_spend_asin", "target_asin", "matched_asin")


def connect_ro(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def one(con: sqlite3.Connection, sql: str, args: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    row = con.execute(sql, args).fetchone()
    return dict(row) if row is not None else None


def rows(con: sqlite3.Connection, sql: str, args: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(row) for row in con.execute(sql, args)]


def evidence(evidence_id: str, evidence_type: str,
             subject_kind: str, subject_id: str,
             observed_at: str, valid_as_of: str,
             payload: dict[str, Any], value_origin: str,
             source_ref: str) -> dict[str, Any]:
    origin = str(value_origin or "constructed")
    if origin not in {"direct", "derived", "constructed"}:
        origin = "derived" if "derived" in origin else "constructed"
    return {
        "evidence_id": evidence_id,
        "evidence_type": evidence_type,
        "subject_kind": subject_kind,
        "subject_id": subject_id,
        "observed_at": observed_at,
        "valid_as_of": valid_as_of,
        "payload": payload,
        "value_origin": origin,
        "source_ref": source_ref,
    }


def load_identity_and_goal(child_asin: str) -> tuple[dict[str, Any], dict[str, Any]]:
    with connect_ro(EXT_DB) as con:
        context = one(
            con,
            """
            SELECT decision_id, child_asin, parent_asin, goal_version,
                   observe_window_start, observe_window_end, data_as_of,
                   rule_status, decision_at, previous_decision_id
            FROM ext_decision_context WHERE child_asin=?
            ORDER BY decision_at DESC LIMIT 1
            """,
            (child_asin,),
        )
        if context is None:
            raise ValueError(f"unsupported_demo_asin:{child_asin}")
        goal = one(
            con,
            """
            SELECT goal_version, child_asin, goal_type, goal_label, goal_status,
                   rationale, value_origin, source_ref
            FROM ext_product_goal WHERE goal_version=?
            """,
            (context["goal_version"],),
        )
        if goal is None:
            raise ValueError(f"missing_operator_goal:{child_asin}")

    with connect_ro(PRODUCT_DB) as con:
        # product_lifecycle is deliberately absent: it is a forbidden conclusion.
        identity = one(
            con,
            """
            SELECT child_asin, parent_asin, product_name, style_name, colorway,
                   size, category, category_rank, rating, operator
            FROM dim_product_child WHERE child_asin=?
            """,
            (child_asin,),
        )
        if identity is None:
            raise ValueError(f"child_asin_not_in_product_spine:{child_asin}")
    return {**context, "identity": identity}, goal


def load_product_evidence(child_asin: str, data_as_of: str) -> list[dict[str, Any]]:
    as_of = date.fromisoformat(data_as_of)
    start_28 = (as_of - timedelta(days=27)).isoformat()
    start_14 = (as_of - timedelta(days=13)).isoformat()
    previous_start = (as_of - timedelta(days=27)).isoformat()
    previous_end = (as_of - timedelta(days=14)).isoformat()
    future_end = (as_of + timedelta(days=90)).isoformat()

    with connect_ro(PRODUCT_DB) as con:
        inventory = one(
            con,
            """
            SELECT date, closing_fba_sellable, fba_reserved, fba_receiving,
                   fba_inbound, overseas_available, overseas_inbound,
                   local_available, stockout_flag, quality_status, value_origin,
                   method_version, provenance
            FROM fact_child_inventory_daily
            WHERE child_asin=? AND date<=?
            ORDER BY date DESC LIMIT 1
            """,
            (child_asin, data_as_of),
        )
        sales = one(
            con,
            """
            SELECT COUNT(*) AS observed_days,
                   ROUND(SUM(units_sold), 4) AS units_28d,
                   ROUND(AVG(units_sold), 4) AS avg_units_28d,
                   ROUND(SUM(CASE WHEN date>=? THEN units_sold ELSE 0 END), 4) AS units_recent_14d,
                   ROUND(SUM(CASE WHEN date BETWEEN ? AND ? THEN units_sold ELSE 0 END), 4) AS units_previous_14d,
                   MIN(value_origin) AS value_origin
            FROM fact_child_sales_daily
            WHERE child_asin=? AND date BETWEEN ? AND ?
            """,
            (start_14, previous_start, previous_end, child_asin, start_28, data_as_of),
        ) or {}
        promotions = rows(
            con,
            """
            SELECT promotion_id, promotion_type, promotion_status,
                   MIN(date) AS start_date, MAX(date) AS end_date,
                   MAX(discount_rate) AS max_discount_rate,
                   MAX(preset_uplift) AS preset_uplift,
                   MIN(value_origin) AS value_origin
            FROM fact_child_promotion_daily
            WHERE child_asin=? AND date>? AND date<=?
              AND promotion_id IS NOT NULL
              AND (is_planned=1 OR promotion_status IS NOT NULL)
            GROUP BY promotion_id, promotion_type, promotion_status
            ORDER BY start_date, promotion_id
            """,
            (child_asin, data_as_of, future_end),
        )

    out: list[dict[str, Any]] = []
    if inventory:
        origin = str(inventory.pop("value_origin") or "constructed")
        observed_at = str(inventory["date"])
        out.append(evidence(
            f"product.inventory_snapshot.{child_asin}.{observed_at}",
            "INVENTORY_CONTEXT", "child_asin", child_asin,
            observed_at, data_as_of, inventory, origin,
            "prod.fact_child_inventory_daily",
        ))
    sales_origin = str(sales.pop("value_origin", "constructed") or "constructed")
    out.append(evidence(
        f"product.sales_history.{child_asin}.{start_28}.{data_as_of}",
        "SALES_HISTORY", "child_asin", child_asin, data_as_of, data_as_of,
        {
            "window_start": start_28,
            "window_end": data_as_of,
            "recent_14d_start": start_14,
            "previous_14d_start": previous_start,
            "previous_14d_end": previous_end,
            **sales,
        },
        sales_origin, "prod.fact_child_sales_daily",
    ))
    if promotions:
        out.append(evidence(
            f"product.promotion_plan.{child_asin}.{data_as_of}.{future_end}",
            "BUSINESS_EVENT", "child_asin", child_asin, data_as_of, data_as_of,
            {"window_end": future_end, "plans": promotions},
            "constructed" if any(p.get("value_origin") == "constructed" for p in promotions) else "direct",
            "prod.fact_child_promotion_daily",
        ))
    return out


def load_ads_evidence(child_asin: str, data_as_of: str) -> list[dict[str, Any]]:
    role_marks = ",".join("?" for _ in PROMO_ROLES)
    relation_params = (child_asin, *PROMO_ROLES)
    with connect_ro(ADS_DB) as con:
        performance = rows(
            con,
            f"""
            SELECT f.attribution_days,
                   COUNT(DISTINCT f.ad_object_id) AS object_count,
                   ROUND(SUM(f.spend), 4) AS spend,
                   ROUND(SUM(f.ad_sales), 4) AS ad_sales,
                   SUM(f.impressions) AS impressions,
                   SUM(f.clicks) AS clicks,
                   SUM(f.orders) AS orders
            FROM fact_ad_performance f
            JOIN (
                SELECT DISTINCT ad_object_id
                FROM bridge_ad_object_product
                WHERE child_asin=? AND relation_role IN ({role_marks})
            ) b ON b.ad_object_id=f.ad_object_id
            WHERE f.metric_basis='report_month_total'
            GROUP BY f.attribution_days ORDER BY f.attribution_days
            """,
            relation_params,
        )
        for block in performance:
            spend = float(block.get("spend") or 0)
            sales = float(block.get("ad_sales") or 0)
            clicks = int(block.get("clicks") or 0)
            orders = int(block.get("orders") or 0)
            block["acos"] = round(spend / sales, 6) if sales else None
            block["roas"] = round(sales / spend, 6) if spend else None
            block["cvr"] = round(orders / clicks, 6) if clicks else None

        campaign_ids = [r["campaign_id"] for r in rows(
            con,
            f"""
            SELECT DISTINCT o.campaign_id
            FROM dim_ad_object o
            JOIN bridge_ad_object_product b ON b.ad_object_id=o.ad_object_id
            WHERE b.child_asin=? AND b.relation_role IN ({role_marks})
              AND o.campaign_id IS NOT NULL
            """,
            relation_params,
        )]
        budget: list[dict[str, Any]] = []
        invalid: list[dict[str, Any]] = []
        if campaign_ids:
            campaign_marks = ",".join("?" for _ in campaign_ids)
            budget = rows(
                con,
                f"""
                SELECT campaign_id, budget, recommended_budget, time_in_budget,
                       lost_impressions_min, lost_impressions_max,
                       lost_clicks_min, lost_clicks_max, source_status
                FROM fact_budget WHERE campaign_id IN ({campaign_marks})
                ORDER BY campaign_id
                """,
                tuple(campaign_ids),
            )
            invalid = rows(
                con,
                f"""
                SELECT campaign_id, total_clicks, invalid_clicks,
                       invalid_click_rate, state, source_status
                FROM fact_invalid_traffic WHERE campaign_id IN ({campaign_marks})
                ORDER BY campaign_id
                """,
                tuple(campaign_ids),
            )

    return [
        evidence(
            f"ads.performance.{child_asin}.{data_as_of}.by_attribution",
            "AD_PERFORMANCE", "child_asin", child_asin, data_as_of, data_as_of,
            {
                "attribution_blocks": performance,
                "aggregate_spend": round(sum(float(block.get("spend") or 0) for block in performance), 4),
                "aggregate_ad_sales": None,
                "aggregate_acos": None,
                "aggregate_roas": None,
                "aggregation_note": "花费可加；7天与14天归因销售额、ACoS、ROAS不可相加",
            },
            "direct", "ads.fact_ad_performance",
        ),
        evidence(
            f"ads.campaign_control.{child_asin}.{data_as_of}",
            "CAMPAIGN_CONTROL", "child_asin", child_asin, data_as_of, data_as_of,
            {
                "campaign_count": len(campaign_ids),
                "budget_rows": budget,
                "invalid_traffic_rows": invalid,
                "counting_rule": "Campaign级规则每个Campaign只计一次",
            },
            "direct", "ads.fact_budget+fact_invalid_traffic",
        ),
    ]


def load_keyword_evidence(child_asin: str, data_as_of: str) -> tuple[list[dict[str, Any]], list[str]]:
    with connect_ro(EXT_DB) as con:
        keyword_rows = rows(
            con,
            """
            SELECT kw_id, keyword, monthly_search, organic_rank,
                   organic_rank_prev, ad_rank, ad_impression_share,
                   covered_by_ad, observed_at, value_origin, source_ref
            FROM ext_keyword_position
            WHERE child_asin=? ORDER BY monthly_search DESC, kw_id
            """,
            (child_asin,),
        )
    out = []
    keywords = []
    for row in keyword_rows:
        origin = str(row.pop("value_origin") or "constructed")
        source_ref = str(row.pop("source_ref") or "ext.ext_keyword_position")
        observed_at = str(row.get("observed_at") or data_as_of)
        row["covered_by_ad"] = bool(row.get("covered_by_ad"))
        keywords.append(str(row["keyword"]))
        out.append(evidence(
            f"keyword.position.{child_asin}.{row['kw_id']}.{observed_at}",
            "KEYWORD_POSITION", "keyword", str(row["kw_id"]),
            observed_at, data_as_of, row, origin, source_ref,
        ))
    return out, keywords


def load_structure_evidence(child_asin: str, data_as_of: str) -> list[dict[str, Any]]:
    role_marks = ",".join("?" for _ in PROMO_ROLES)
    with connect_ro(ADS_DB) as con:
        relevant = rows(
            con,
            f"""
            SELECT DISTINCT ad_object_id
            FROM bridge_ad_object_product
            WHERE child_asin=? AND relation_role IN ({role_marks})
            ORDER BY ad_object_id
            """,
            (child_asin, *PROMO_ROLES),
        )
        out = []
        for rel in relevant:
            object_id = rel["ad_object_id"]
            obj = one(
                con,
                """
                SELECT ad_object_id, object_level, ad_type, campaign_id,
                       campaign_name, ad_group_name, target_text, match_type,
                       parent_ad_object_id, key_kind, mapping_status,
                       source_status, source_ref
                FROM dim_ad_object WHERE ad_object_id=?
                """,
                (object_id,),
            )
            if obj is None:
                continue
            current_roles = rows(
                con,
                """
                SELECT relation_role, attribution_scope, source_role,
                       is_scope_product, effective_from, effective_to,
                       source_status, source_ref
                FROM bridge_ad_object_product
                WHERE ad_object_id=? AND child_asin=?
                ORDER BY relation_role, source_role
                """,
                (object_id, child_asin),
            )
            shared = one(
                con,
                f"""
                SELECT COUNT(DISTINCT child_asin) AS child_count
                FROM bridge_ad_object_product
                WHERE ad_object_id=? AND relation_role IN ({role_marks})
                """,
                (object_id, *PROMO_ROLES),
            ) or {"child_count": 0}
            performance = rows(
                con,
                """
                SELECT window_start, window_end, attribution_days,
                       metric_basis, impressions, clicks, spend, orders,
                       ad_sales, ctr, cpc, cvr, acos, roas, source_status
                FROM fact_ad_performance
                WHERE ad_object_id=? AND metric_basis='report_month_total'
                ORDER BY attribution_days, window_end
                """,
                (object_id,),
            )
            labels = rows(
                con,
                """
                SELECT label_type, label_value, label_source,
                       confirmation_status, effective_from, effective_to,
                       basis, source_status, source_ref
                FROM fact_ad_label_version
                WHERE ad_object_id=? AND label_source<>'ai_suggested'
                  AND (effective_to IS NULL OR effective_to>=?)
                ORDER BY label_type, label_version_id
                """,
                (object_id, data_as_of),
            )
            out.append(evidence(
                f"ads.structure.{child_asin}.{object_id}", "AD_STRUCTURE",
                str(obj["object_level"] or "ad_object").lower(), object_id,
                data_as_of, data_as_of,
                {
                    "object": obj,
                    "current_child_relations": current_roles,
                    "promoted_child_count": int(shared.get("child_count") or 0),
                    "performance_by_attribution": performance,
                    "non_ai_labels": labels,
                },
                str(obj.get("source_status") or "direct"),
                "ads.dim_ad_object+bridge_ad_object_product+fact_ad_label_version",
            ))

        purchased_only = rows(
            con,
            f"""
            SELECT DISTINCT p.ad_object_id
            FROM bridge_ad_object_product p
            WHERE p.child_asin=? AND p.relation_role='purchased_asin'
              AND NOT EXISTS (
                SELECT 1 FROM bridge_ad_object_product x
                WHERE x.ad_object_id=p.ad_object_id AND x.child_asin=p.child_asin
                  AND x.relation_role IN ({role_marks})
              )
            ORDER BY p.ad_object_id
            """,
            (child_asin, *PROMO_ROLES),
        )
        if purchased_only:
            out.append(evidence(
                f"ads.structure.{child_asin}.purchased_only", "AD_STRUCTURE",
                "child_asin", child_asin, data_as_of, data_as_of,
                {
                    "relationship": "purchased_asin_without_promotion_relation",
                    "object_count": len(purchased_only),
                    "ad_object_ids": [row["ad_object_id"] for row in purchased_only],
                },
                "direct", "ads.bridge_ad_object_product",
            ))
    return out


def load_competitor_evidence(child_asin: str, data_as_of: str,
                             category: str, keywords: list[str]) -> list[dict[str, Any]]:
    competitor_category = "Men's Boxer Briefs" if "长平角" in (category or "") else None
    with connect_ro(PRODUCT_DB) as con:
        own_price = one(
            con,
            """
            SELECT date, list_price, selling_price, coupon_amount,
                   discount_rate, price_event, value_origin
            FROM fact_child_price_daily
            WHERE child_asin=? AND date<=? ORDER BY date DESC LIMIT 1
            """,
            (child_asin, data_as_of),
        )
    with connect_ro(COMPETITOR_DB) as con:
        if competitor_category:
            families = rows(
                con,
                """
                SELECT f.*,
                       COALESCE(m.rank_sub, 999999) AS latest_rank_sub,
                       COALESCE(m.units_rolling30, 0) AS latest_units_rolling30,
                       m.date AS market_date, m.rating AS market_rating,
                       m.rating_count AS market_rating_count,
                       m.value_origin AS market_value_origin
                FROM dim_competitor_family f
                LEFT JOIN fact_competitor_market_daily m
                  ON m.family_asin=f.family_asin AND m.date=(
                    SELECT MAX(m2.date) FROM fact_competitor_market_daily m2
                    WHERE m2.family_asin=f.family_asin AND m2.date<=?
                  )
                WHERE f.in_analysis_scope=1 AND f.sub_category=?
                ORDER BY latest_rank_sub, latest_units_rolling30 DESC, f.family_asin
                LIMIT 3
                """,
                (data_as_of, competitor_category),
            )
        else:
            families = rows(
                con,
                """
                SELECT f.*, 999999 AS latest_rank_sub, 0 AS latest_units_rolling30,
                       NULL AS market_date, NULL AS market_rating,
                       NULL AS market_rating_count, NULL AS market_value_origin
                FROM dim_competitor_family f WHERE f.in_analysis_scope=1
                ORDER BY f.family_asin LIMIT 3
                """,
            )
        out = []
        for family in families:
            family_asin = family["family_asin"]
            main_child = one(
                con,
                """
                SELECT child_asin, size_label, color_label, pack_count,
                       pack_resolved, snapshot_price, unit_price,
                       sales_rank_sub, is_main_variant
                FROM dim_competitor_child WHERE family_asin=?
                ORDER BY is_main_variant DESC, child_asin LIMIT 1
                """,
                (family_asin,),
            )
            latest_price = None
            if main_child:
                latest_price = one(
                    con,
                    """
                    SELECT child_asin, date, list_price, deal_price, final_price,
                           unit_price, coupon_pct, promo_kind, value_origin, source
                    FROM fact_competitor_price_daily
                    WHERE child_asin=? AND date<=? ORDER BY date DESC LIMIT 1
                    """,
                    (main_child["child_asin"], data_as_of),
                )
            keyword_rows = []
            for keyword in keywords:
                matched = one(
                    con,
                    """
                    SELECT b.keyword, b.entry_type, b.first_observed,
                           b.last_observed, r.observed_date, r.organic_rank,
                           r.ad_slot, r.is_top3, r.click_share,
                           r.conversion_share, r.value_origin, r.source
                    FROM bridge_competitor_keyword b
                    LEFT JOIN fact_competitor_keyword_rank r
                      ON r.family_asin=b.family_asin AND r.keyword=b.keyword
                     AND r.observed_date=(
                       SELECT MAX(r2.observed_date)
                       FROM fact_competitor_keyword_rank r2
                       WHERE r2.family_asin=b.family_asin
                         AND r2.keyword=b.keyword AND r2.observed_date<=?
                     )
                    WHERE b.family_asin=? AND lower(b.keyword)=lower(?)
                    """,
                    (data_as_of, family_asin, keyword),
                )
                if matched:
                    keyword_rows.append(matched)
            origin_values = [family.get("market_value_origin")]
            if latest_price:
                origin_values.append(latest_price.get("value_origin"))
            origin = "constructed" if "constructed" in origin_values else "derived"
            observed_at = str(family.get("market_date") or data_as_of)
            out.append(evidence(
                f"competitor.market.{child_asin}.{family_asin}.{observed_at}",
                "COMPETITOR_MARKET", "competitor_family", family_asin,
                observed_at, data_as_of,
                {
                    "own_product": {"child_asin": child_asin, "category": category,
                                    "latest_price": own_price},
                    "competitor_family": family,
                    "main_child": main_child,
                    "latest_price": latest_price,
                    "keyword_entries": keyword_rows,
                },
                origin, "competitor.dim_family+price_daily+market_daily+keyword_rank",
            ))
    return out


def load_upstream_inventory_agent(child_asin: str) -> dict[str, Any]:
    if not INVENTORY_AGENT_DB.is_file():
        return {"available": False, "reason": "库存Agent sidecar不存在"}
    try:
        with connect_ro(INVENTORY_AGENT_DB) as con:
            run = one(
                con,
                """
                SELECT * FROM fact_child_verdict_run
                WHERE child_asin=? AND model_version<>'seed'
                ORDER BY datetime(created_at) DESC LIMIT 1
                """,
                (child_asin,),
            )
            if run is None:
                return {"available": False, "reason": "该子ASIN没有真实库存Agent运行"}
            items = rows(
                con,
                """
                SELECT block, ord, state, verdict, because, refs, numbers
                FROM fact_child_verdict_item WHERE run_id=? ORDER BY ord
                """,
                (run["run_id"],),
            )
            for item in items:
                item["refs"] = json.loads(item["refs"] or "[]")
                item["numbers"] = json.loads(item["numbers"] or "{}")
            return {"available": True, "run": run, "items": items}
    except (sqlite3.Error, json.JSONDecodeError) as exc:
        return {"available": False, "reason": f"库存Agent结果不可读:{type(exc).__name__}"}


def build(child_asin: str) -> dict[str, Any]:
    context, goal = load_identity_and_goal(child_asin)
    data_as_of = str(context["data_as_of"])
    goal_fact = evidence(
        f"ads.operator_goal.{goal['goal_version']}", "PRODUCT_GOAL",
        "child_asin", child_asin, data_as_of, data_as_of,
        {
            "goal_version": goal["goal_version"],
            "goal_type": goal["goal_type"],
            "goal_label": goal["goal_label"],
            "goal_status": goal["goal_status"],
            "rationale": goal["rationale"],
            "product_identity": context["identity"],
        },
        str(goal["value_origin"]), str(goal["source_ref"]),
    )
    keyword_facts, keywords = load_keyword_evidence(child_asin, data_as_of)
    facts = [
        goal_fact,
        *load_product_evidence(child_asin, data_as_of),
        *load_ads_evidence(child_asin, data_as_of),
        *load_structure_evidence(child_asin, data_as_of),
        *keyword_facts,
        *load_competitor_evidence(
            child_asin, data_as_of,
            str(context["identity"].get("category") or ""), keywords,
        ),
    ]
    upstream = load_upstream_inventory_agent(child_asin)
    if upstream.get("available"):
        run = upstream["run"]
        facts.append(evidence(
            f"inventory.agent.{run['run_id']}.verdict", "INVENTORY_CONTEXT",
            "child_asin", child_asin, str(run["data_as_of"]), data_as_of,
            {"run_id": run["run_id"], "model_version": run["model_version"], "items": upstream["items"]},
            "derived", "inventory.verdict_agent",
        ))

    clean_input = {
        "child_asin": child_asin,
        "context_id": context["decision_id"],
        "data_as_of": data_as_of,
        "observe_window": [context["observe_window_start"], context["observe_window_end"]],
        "identity": context["identity"],
        "operator_goal": {key: goal[key] for key in ("goal_version", "goal_type", "goal_label", "goal_status", "rationale", "source_ref")},
        "rule_status": context["rule_status"],
        "upstream_inventory_agent": {
            "available": bool(upstream.get("available")),
            "reason": upstream.get("reason"),
            "run_id": (upstream.get("run") or {}).get("run_id"),
        },
        "evidence": facts,
        "input_limits": [
            "没有读取ext_goal_constraint或其他ext_*结论表",
            "没有读取产品生命周期",
            "库存Agent没有运行时，不得把产品包投影字段当作替代答案",
            "7天与14天归因销售额、ACoS、ROAS必须保持隔离",
            "规则状态未确认，成本与流量阈值只能作为观察，不能伪装成客户硬规则",
        ],
    }
    canonical = json.dumps(clean_input, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    input_digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    mode = "正式判断" if goal["goal_status"] == "confirmed" and context["rule_status"] == "confirmed" else "条件性判断"
    return {
        "ok": True,
        "run_type": "child_decision",
        "subject_kind": "child_asin",
        "subject_id": child_asin,
        "child_asin": child_asin,
        "source_data_as_of": data_as_of,
        "source_context_id": context["decision_id"],
        "input_digest": input_digest,
        "dataset_version": DATASET_VERSION,
        "rule_version": RULE_VERSION,
        "mode": mode,
        "condition": "正常",
        "goal_version": goal["goal_version"],
        "operator_goal": clean_input["operator_goal"],
        "identity": clean_input["identity"],
        "upstream_inventory_agent": clean_input["upstream_inventory_agent"],
        "input_limits": clean_input["input_limits"],
        "evidence": facts,
        "evidence_index": facts,
        "open_output_point": "B0b",
        "output_contract": {
            "constraint_id": "text",
            "goal_version": goal["goal_version"],
            "kind": ["hard", "observe"],
            "domain": ["inventory", "cost", "traffic", "event"],
            "label": "中文短标签",
            "detail": "中文展开说明；引用数字必须来自所指证据",
            "is_satisfied": [0, 1, None],
            "evidence_ref": "本次evidence_id",
        },
    }


def main() -> int:
    child_asin = (sys.argv[1] if len(sys.argv) > 1 else "B0B3LWGP36").strip().upper()
    try:
        payload = build(child_asin)
    except (ValueError, sqlite3.Error, OSError) as exc:
        print(json.dumps({"ok": False, "child_asin": child_asin, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
