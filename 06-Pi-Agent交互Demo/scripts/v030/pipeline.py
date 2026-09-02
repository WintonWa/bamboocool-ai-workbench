import hashlib
import json
import math
import random
import shutil
import sqlite3
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import mean, pstdev
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

from .constants import (
    AS_OF_DATE,
    DATASET_VERSION,
    FORECAST_DAYS,
    FORECAST_END,
    FORECAST_RUN_ID,
    FORECAST_START,
    FUTURE_DAILY_TABLES,
    HISTORICAL_DAILY_TABLES,
    HISTORY_DAYS,
    HISTORY_START,
    METHOD_VERSION,
    OUTPUT_DB_NAME,
    OUTPUT_ROOT,
    PROFILE_BY_ID,
    PROFILES,
    RANDOM_SEED,
    SOURCE_DB,
    SOURCE_ROOT,
    STAGING_ROOT,
    WEEKDAY_FACTORS,
)
from .forecasting import MODEL_NAMES, clamp, evaluate_models, forecast_baseline, interval_ratio, round2
from .schema import TABLE_DDL, create_v030_tables


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def date_range(start: date, days: int) -> List[date]:
    return [start + timedelta(days=index) for index in range(days)]


def stable_seed(value: str) -> int:
    digest = hashlib.sha256((str(RANDOM_SEED) + ":" + value).encode("utf-8")).hexdigest()
    return int(digest[:16], 16)


def stable_rng(value: str) -> random.Random:
    return random.Random(stable_seed(value))


def largest_remainder(total: int, weights: Sequence[float]) -> List[int]:
    if total <= 0:
        return [0] * len(weights)
    positive = [max(0.000001, value) for value in weights]
    weight_sum = sum(positive)
    raw = [total * value / weight_sum for value in positive]
    allocated = [int(math.floor(value)) for value in raw]
    remaining = total - sum(allocated)
    order = sorted(range(len(raw)), key=lambda index: (raw[index] - allocated[index], -index), reverse=True)
    for index in order[:remaining]:
        allocated[index] += 1
    return allocated


def insert_rows(connection: sqlite3.Connection, table: str, rows: Sequence[Tuple[Any, ...]]) -> None:
    if not rows:
        return
    columns = [row[1] for row in connection.execute("PRAGMA table_info(%s)" % table)]
    placeholders = ",".join("?" for _ in columns)
    connection.executemany("INSERT INTO %s VALUES (%s)" % (table, placeholders), rows)


def _source_context(connection: sqlite3.Connection) -> Dict[str, Any]:
    connection.row_factory = sqlite3.Row
    children = [dict(row) for row in connection.execute("""
        SELECT c.child_asin, c.parent_asin, c.product_name, c.style_name, c.owner,
               c.category, c.style_no, c.colorway, c.size, c.product_lifecycle,
               COALESCE(w.units_90d, m.units_sold, 0) AS units_90d,
               COALESCE(w.daily_avg_90d, m.units_sold / 30.0, 0.2) AS daily_avg_90d,
               COALESCE(m.average_price, 0) AS average_price,
               COALESCE(m.ad_spend, 0) AS monthly_ad_spend,
               COALESCE(m.cvr, 0) AS monthly_cvr,
               COALESCE(i.fba_sellable, 0) AS fba_sellable,
               COALESCE(i.fba_reserved, 0) AS fba_reserved,
               COALESCE(i.fba_receiving, 0) AS fba_receiving,
               COALESCE(i.fba_inbound, 0) AS fba_inbound,
               COALESCE(i.overseas_available, 0) AS overseas_available,
               COALESCE(i.overseas_inbound, 0) AS overseas_inbound,
               COALESCE(i.local_available, 0) AS local_available,
               COALESCE(i.total_inventory, 0) AS total_inventory,
               CASE WHEN i.child_asin IS NULL THEN 1 ELSE 0 END AS inventory_missing,
               COALESCE(s.purchase_lead_days, 30) AS purchase_lead_days,
               COALESCE(s.quality_check_days, 3) AS quality_check_days,
               COALESCE(s.overseas_to_fba_days, 14) AS overseas_to_fba_days,
               COALESCE(s.safety_days, 14) AS source_safety_days,
               COALESCE(s.stocking_lead_days, 47) AS stocking_lead_days,
               CASE WHEN b.child_asin IS NULL THEN 1 ELSE 0 END AS identifier_missing
        FROM dim_product_child c
        LEFT JOIN fact_sales_window w ON w.child_asin = c.child_asin
        LEFT JOIN fact_child_sales_monthly m ON m.child_asin = c.child_asin
        LEFT JOIN fact_inventory_snapshot i ON i.child_asin = c.child_asin
        LEFT JOIN fact_supply_plan s ON s.child_asin = c.child_asin
        LEFT JOIN bridge_product_identifier b ON b.child_asin = c.child_asin
        ORDER BY c.parent_asin, c.child_asin
    """)]
    parent_daily: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)
    for row in connection.execute("SELECT * FROM fact_parent_sales_daily"):
        parent_daily[row["parent_asin"]][row["date"]] = dict(row)
    supply_events = [dict(row) for row in connection.execute("SELECT * FROM fact_supply_event ORDER BY supply_event_id")]
    return {"children": children, "parent_daily": parent_daily, "supply_events": supply_events}


def _choose_golden(children: Sequence[Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for child in children:
        grouped[str(child["parent_asin"])].append(dict(child))
    parents = sorted(grouped)
    if len(parents) != len(PROFILES):
        raise RuntimeError("expected exactly five parent ASINs for five golden profiles")
    selected: Dict[str, Dict[str, Any]] = {}
    for parent, profile in zip(parents, PROFILES):
        candidates = [row for row in grouped[parent] if not row["inventory_missing"] and not row["identifier_missing"]]
        if not candidates:
            candidates = grouped[parent]
        if profile["profile_id"] == "stockout_censored":
            candidate = min(
                candidates,
                key=lambda row: (row["fba_sellable"] / max(1.0, row["daily_avg_90d"]), -row["units_90d"]),
            )
        elif profile["profile_id"] == "decline_overstock":
            candidate = max(
                candidates,
                key=lambda row: (row["total_inventory"] / max(1.0, row["daily_avg_90d"]), row["units_90d"]),
            )
        else:
            candidate = max(candidates, key=lambda row: (row["units_90d"], row["fba_sellable"]))
        selected[profile["profile_id"]] = candidate
    return selected


def _parameters(children: Sequence[Mapping[str, Any]], golden: Mapping[str, Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
    golden_by_asin = {row["child_asin"]: profile_id for profile_id, row in golden.items()}
    params: Dict[str, Dict[str, Any]] = {}
    for child in children:
        child_asin = str(child["child_asin"])
        rng = stable_rng(child_asin)
        is_golden = child_asin in golden_by_asin
        profile_id = golden_by_asin.get(child_asin, PROFILES[stable_seed(child_asin + ":profile") % len(PROFILES)]["profile_id"])
        profile = PROFILE_BY_ID[profile_id]
        base_price = float(child["average_price"] or 0)
        if base_price <= 0:
            base_price = round(rng.uniform(18.0, 46.0), 2)
        base_cvr = float(child["monthly_cvr"] or 0)
        if base_cvr <= 0 or base_cvr >= 1:
            base_cvr = rng.uniform(0.075, 0.19)
        base_ad = float(child["monthly_ad_spend"] or 0) / 30
        if base_ad <= 0:
            base_ad = max(1.5, float(child["daily_avg_90d"] or 0.2) * rng.uniform(0.7, 1.8))
        lifecycle = profile["lifecycle"] if is_golden else str(child["product_lifecycle"] or "成熟期")
        params[child_asin] = {
            "child": dict(child),
            "profile_id": profile_id,
            "is_golden": is_golden,
            "base_price": base_price,
            "base_cvr": clamp(base_cvr, 0.04, 0.28),
            "base_ad": base_ad,
            "base_weight": max(0.05, float(child["units_90d"] or 0.2)),
            "lifecycle": lifecycle,
            "trend_annual": profile["trend_annual"] if is_golden else rng.uniform(-0.12, 0.20),
            "ad_elasticity": profile["ad_elasticity"] if is_golden else rng.uniform(0.08, 0.28),
            "price_elasticity": profile["price_elasticity"] if is_golden else rng.uniform(-1.7, -0.75),
            "promo_uplift": profile["promo_uplift"] if is_golden else rng.uniform(0.10, 0.34),
            "volatility": profile["volatility"] if is_golden else rng.uniform(0.07, 0.18),
            "noise_seed": stable_seed(child_asin + ":noise"),
        }
    return params


def _lifecycle_at(param: Mapping[str, Any], day_index: int) -> str:
    profile_id = param["profile_id"]
    if param["is_golden"] and profile_id == "advertising_growth":
        return "新品期" if day_index < 180 else "成长期"
    if param["is_golden"] and profile_id == "decline_overstock":
        return "成熟期" if day_index < 540 else "衰退期"
    return str(param["lifecycle"])


def _lifecycle_factor(param: Mapping[str, Any], day_index: int) -> float:
    annual = float(param["trend_annual"])
    if param["profile_id"] == "decline_overstock" and day_index < 540:
        annual = 0.02
    return max(0.45, (1 + annual) ** ((day_index - HISTORY_DAYS + 1) / 365))


def _historical_promotion(param: Mapping[str, Any], day_index: int) -> Tuple[str, str, float, float]:
    offset = stable_seed(str(param["child"]["child_asin"]) + ":promo") % 113
    profile_id = param["profile_id"]
    if param["is_golden"] and profile_id == "promotion_spike":
        phase = (day_index - 30) % 105
        if phase < 5:
            return ("BD-%03d" % (day_index // 105 + 1), "BD", 0.18, float(param["promo_uplift"]))
    if profile_id == "advertising_growth" and (day_index + offset) % 170 < 4:
        return ("LD-%03d" % (day_index // 170 + 1), "LD", 0.12, float(param["promo_uplift"]))
    if (day_index + offset) % 137 < 3:
        return ("CP-%03d" % (day_index // 137 + 1), "Coupon", 0.08, float(param["promo_uplift"]) * 0.65)
    return ("none", "none", 0.0, 0.0)


def _driver_for_day(param: Mapping[str, Any], current: date, day_index: int) -> Dict[str, Any]:
    rng = random.Random(int(param["noise_seed"]) + day_index * 7919)
    weekday_factor = WEEKDAY_FACTORS[current.weekday()]
    seasonal = 1 + 0.105 * math.sin((2 * math.pi * (current.timetuple().tm_yday - 25)) / 365.25)
    lifecycle_factor = _lifecycle_factor(param, day_index)
    promo_id, promo_type, promo_discount, promo_uplift = _historical_promotion(param, day_index)
    ad_growth = 1.0
    if param["profile_id"] == "advertising_growth":
        ad_growth = 0.72 + 0.62 * (day_index / max(1, HISTORY_DAYS - 1))
    ad_spend_index = max(0.32, ad_growth * (1 + rng.uniform(-0.16, 0.16)))
    ad_effect = 1 + float(param["ad_elasticity"]) * (ad_spend_index - 1)
    list_price = float(param["base_price"]) * (1 + 0.018 * math.sin(day_index / 77))
    selling_price = max(1.0, list_price * (1 - promo_discount))
    price_effect = (selling_price / float(param["base_price"])) ** float(param["price_elasticity"])
    promo_effect = 1 + promo_uplift
    stockout_ratio = 1.0
    if param["is_golden"] and param["profile_id"] == "stockout_censored" and 520 <= day_index <= 533:
        stockout_ratio = 0.34 + 0.08 * ((day_index - 520) % 3)
    noise = max(0.55, 1 + rng.gauss(0, float(param["volatility"])))
    demand_factor = weekday_factor * seasonal * lifecycle_factor * ad_effect * price_effect * promo_effect * noise
    return {
        "weekday_factor": weekday_factor,
        "seasonality_factor": seasonal,
        "lifecycle_factor": lifecycle_factor,
        "lifecycle": _lifecycle_at(param, day_index),
        "promotion_id": promo_id,
        "promotion_type": promo_type,
        "promotion_discount": promo_discount,
        "promotion_uplift": promo_uplift,
        "promotion_effect": promo_effect,
        "ad_spend_index": ad_spend_index,
        "ad_effect": ad_effect,
        "list_price": list_price,
        "selling_price": selling_price,
        "price_effect": price_effect,
        "stockout_ratio": stockout_ratio,
        "noise": noise,
        "demand_factor": demand_factor,
    }


def _synthetic_parent_total(parent_rows: Mapping[str, Mapping[str, Any]], current: date, fallback: float, index: int) -> int:
    if current.isoformat() in parent_rows:
        return int(parent_rows[current.isoformat()]["units_sold"])
    actual_values = [int(row["units_sold"]) for row in parent_rows.values()]
    base = mean(actual_values[-90:]) if actual_values else fallback
    seasonal = 1 + 0.10 * math.sin((2 * math.pi * current.timetuple().tm_yday) / 365.25)
    weekday = WEEKDAY_FACTORS[current.weekday()]
    rng = random.Random(stable_seed("parent:%s:%s" % (index, current.isoformat())))
    return max(0, round(base * seasonal * weekday * max(0.7, 1 + rng.gauss(0, 0.07))))


def _build_lifecycle_and_routes(connection: sqlite3.Connection, params: Mapping[str, Mapping[str, Any]], golden: Mapping[str, Mapping[str, Any]]) -> None:
    profile_rows = []
    for profile in PROFILES:
        golden_child = golden[profile["profile_id"]]
        profile_rows.append((
            profile["profile_id"], profile["profile_name"], profile["description"], profile["lifecycle"],
            golden_child["child_asin"], golden_child["parent_asin"], json_text(profile),
            "synthetic_demo", METHOD_VERSION,
        ))
    insert_rows(connection, "dim_demo_profile", profile_rows)
    route_rows = []
    lifecycle_rows = []
    for child_asin, param in params.items():
        profile = PROFILE_BY_ID[param["profile_id"]]
        analysis_child = golden[param["profile_id"]]["child_asin"]
        route_rows.append((
            child_asin, analysis_child, param["profile_id"], "stable_profile_route_v1",
            "黄金样本直连" if param["is_golden"] else "按固定种子映射到同类演示场景",
            "synthetic_demo", METHOD_VERSION,
        ))
        child = param["child"]
        periods: List[Tuple[date, date, str, str]] = []
        if param["is_golden"] and param["profile_id"] == "advertising_growth":
            periods = [
                (HISTORY_START, HISTORY_START + timedelta(days=179), "新品期", "新品爬坡"),
                (HISTORY_START + timedelta(days=180), FORECAST_END, "成长期", "广告扩量进入成长期"),
            ]
        elif param["is_golden"] and param["profile_id"] == "decline_overstock":
            periods = [
                (HISTORY_START, HISTORY_START + timedelta(days=539), "成熟期", "历史稳定阶段"),
                (HISTORY_START + timedelta(days=540), FORECAST_END, "衰退期", "需求趋势持续下降"),
            ]
        else:
            periods = [(HISTORY_START, FORECAST_END, str(param["lifecycle"]), "当前属性延展")]
        for start, end, stage, reason in periods:
            lifecycle_rows.append((
                child_asin, child["parent_asin"], start.isoformat(), end.isoformat(), stage, reason,
                0.94 if param["is_golden"] else 0.78, "synthetic_demo", METHOD_VERSION,
                json_text({"source": "dim_product_child", "profile": param["profile_id"]}),
            ))
    insert_rows(connection, "bridge_demo_child_route", route_rows)
    insert_rows(connection, "dim_child_lifecycle_history", lifecycle_rows)


def _build_history(
    connection: sqlite3.Connection,
    children: Sequence[Mapping[str, Any]],
    parent_daily: Mapping[str, Mapping[str, Mapping[str, Any]]],
    params: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Dict[str, List[Any]]]:
    dates = date_range(HISTORY_START, HISTORY_DAYS)
    grouped: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for child in children:
        grouped[str(child["parent_asin"])].append(child)
    series: Dict[str, Dict[str, List[Any]]] = {
        child["child_asin"]: {"clean": [], "observed": [], "potential": [], "weekday": [], "ad_spend": [], "price": [], "promo": []}
        for child in children
    }
    for parent_index, (parent_asin, parent_children) in enumerate(sorted(grouped.items())):
        sales_rows: List[Tuple[Any, ...]] = []
        traffic_rows: List[Tuple[Any, ...]] = []
        ad_rows: List[Tuple[Any, ...]] = []
        price_rows: List[Tuple[Any, ...]] = []
        promo_rows: List[Tuple[Any, ...]] = []
        feature_rows: List[Tuple[Any, ...]] = []
        fallback = sum(float(params[row["child_asin"]]["base_weight"]) for row in parent_children) / 90
        for day_index, current in enumerate(dates):
            drivers = [_driver_for_day(params[row["child_asin"]], current, day_index) for row in parent_children]
            weights = [
                float(params[row["child_asin"]]["base_weight"]) * driver["demand_factor"] * driver["stockout_ratio"]
                for row, driver in zip(parent_children, drivers)
            ]
            source_parent = parent_daily.get(parent_asin, {}).get(current.isoformat())
            total_units = int(source_parent["units_sold"]) if source_parent else _synthetic_parent_total(parent_daily.get(parent_asin, {}), current, fallback, parent_index)
            golden_index = next(
                (index for index, row in enumerate(parent_children) if params[row["child_asin"]]["is_golden"]),
                None,
            )
            if golden_index is None:
                allocated_units = largest_remainder(total_units, weights)
            else:
                golden_child = parent_children[golden_index]
                golden_param = params[golden_child["child_asin"]]
                golden_driver = drivers[golden_index]
                golden_target = round(
                    float(golden_param["base_weight"])
                    / 90
                    * float(golden_driver["demand_factor"])
                    * float(golden_driver["stockout_ratio"])
                )
                golden_units = max(0, min(total_units, golden_target))
                other_weights = [weight for index, weight in enumerate(weights) if index != golden_index]
                other_allocations = largest_remainder(total_units - golden_units, other_weights)
                allocated_units = []
                other_cursor = 0
                for index in range(len(parent_children)):
                    if index == golden_index:
                        allocated_units.append(golden_units)
                    else:
                        allocated_units.append(other_allocations[other_cursor])
                        other_cursor += 1
            traffic_weights = [max(0.01, weight / max(0.2, params[row["child_asin"]]["base_cvr"])) for row, weight in zip(parent_children, weights)]
            total_sessions = int(source_parent["sessions"]) if source_parent and source_parent.get("sessions") is not None else max(total_units * 8, len(parent_children))
            allocated_sessions = largest_remainder(total_sessions, traffic_weights)
            ad_weights = [float(params[row["child_asin"]]["base_ad"]) * driver["ad_spend_index"] for row, driver in zip(parent_children, drivers)]
            total_ad_spend = float(source_parent["ad_spend"]) if source_parent and source_parent.get("ad_spend") is not None else sum(ad_weights)
            ad_weight_total = sum(ad_weights) or 1.0
            for child, driver, units, sessions_allocated, ad_weight in zip(parent_children, drivers, allocated_units, allocated_sessions, ad_weights):
                child_asin = child["child_asin"]
                param = params[child_asin]
                origin = "derived_from_actual" if source_parent else "synthetic_demo"
                stockout_ratio = float(driver["stockout_ratio"])
                potential = max(units, round(units / stockout_ratio)) if stockout_ratio < 1 else units
                lost = max(0, potential - units)
                selling_price = round2(float(driver["selling_price"]))
                list_price = round2(float(driver["list_price"]))
                orders = min(units, max(0, round(units / 1.12)))
                sessions = max(orders, sessions_allocated)
                cvr = orders / sessions if sessions else 0.0
                page_views = max(sessions, round(sessions * 1.24))
                refund_units = round(units * (0.025 + (stable_seed(child_asin + current.isoformat()) % 20) / 1000))
                return_units = round(units * 0.018)
                sales_amount = round2(units * selling_price)
                net_sales = round2(max(0.0, sales_amount - (refund_units + return_units) * selling_price))
                ad_spend = round2(total_ad_spend * ad_weight / ad_weight_total)
                cpc = 0.58 + (stable_seed(child_asin + ":cpc") % 90) / 100
                clicks = max(0, round(ad_spend / cpc))
                ctr_target = 0.006 + (stable_seed(child_asin + ":ctr") % 20) / 1000
                impressions = max(clicks, round(clicks / ctr_target)) if clicks else 0
                ad_orders = min(orders, round(clicks * clamp(float(param["base_cvr"]) * 0.82, 0.02, 0.24)))
                ad_sales = round2(ad_orders * selling_price)
                ad_budget = round2(ad_spend * 1.12)
                ctr = clicks / impressions if impressions else 0.0
                ad_cvr = ad_orders / clicks if clicks else 0.0
                acos = ad_spend / ad_sales if ad_sales else 0.0
                acoas = ad_spend / sales_amount if sales_amount else 0.0
                price_change = selling_price / float(param["base_price"]) - 1
                combined_without_noise = max(
                    0.05,
                    float(driver["weekday_factor"])
                    * float(driver["seasonality_factor"])
                    * float(driver["lifecycle_factor"])
                    * float(driver["ad_effect"])
                    * float(driver["price_effect"])
                    * float(driver["promotion_effect"]),
                )
                clean = potential / combined_without_noise
                if stockout_ratio < 1:
                    quality_flag = "stockout_censored"
                    reason = "FBA可售不足，使用流量、同星期与相邻正常日还原需求"
                    confidence = 0.72
                elif driver["promotion_type"] != "none":
                    quality_flag = "promotion_event"
                    reason = "已剥离%s活动提升" % driver["promotion_type"]
                    confidence = 0.88
                elif abs(price_change) >= 0.08:
                    quality_flag = "price_shock"
                    reason = "已剥离价格变化影响"
                    confidence = 0.84
                elif driver["ad_spend_index"] >= 1.28:
                    quality_flag = "ad_shock"
                    reason = "已剥离广告投入突变影响"
                    confidence = 0.86
                elif driver["lifecycle"] == "新品期":
                    quality_flag = "launch_ramp"
                    reason = "新品爬坡日，使用生命周期约束"
                    confidence = 0.76
                else:
                    quality_flag = "normal"
                    reason = "正常销售日"
                    confidence = 0.96 if param["is_golden"] else 0.90
                provenance = json_text({"parent_daily_actual": bool(source_parent), "profile": param["profile_id"]})
                sales_rows.append((
                    current.isoformat(), child_asin, parent_asin, units, potential, lost, orders,
                    sales_amount, net_sales, refund_units, return_units, selling_price,
                    origin, METHOD_VERSION, provenance,
                ))
                traffic_rows.append((
                    current.isoformat(), child_asin, parent_asin, sessions, page_views, orders,
                    round(cvr, 6), "complete", origin, METHOD_VERSION, provenance,
                ))
                ad_rows.append((
                    current.isoformat(), child_asin, parent_asin, ad_budget, ad_spend, impressions,
                    clicks, round2(cpc), ad_orders, ad_sales, round(ctr, 6), round(ad_cvr, 6),
                    round(acos, 6), round(acoas, 6), origin, METHOD_VERSION, provenance,
                ))
                price_rows.append((
                    current.isoformat(), child_asin, parent_asin, list_price, selling_price,
                    round2(list_price - selling_price), round(float(driver["promotion_discount"]), 4),
                    round(price_change, 6), "promotion" if driver["promotion_type"] != "none" else "none",
                    "synthetic_demo", METHOD_VERSION, provenance,
                ))
                promo_rows.append((
                    current.isoformat(), child_asin, parent_asin, driver["promotion_id"],
                    driver["promotion_type"], "completed" if driver["promotion_type"] != "none" else "none",
                    round(float(driver["promotion_discount"]), 4), 0,
                    round(float(driver["promotion_effect"]), 4), round(float(driver["promotion_uplift"]), 4),
                    "synthetic_demo", METHOD_VERSION, provenance,
                ))
                feature_rows.append((
                    current.isoformat(), child_asin, parent_asin, units, round2(potential), round2(clean),
                    round(float(driver["weekday_factor"]), 4), round(float(driver["seasonality_factor"]), 4),
                    round(float(driver["lifecycle_factor"]), 4), round(float(driver["ad_effect"]), 4),
                    round(float(driver["price_effect"]), 4), round(float(driver["promotion_effect"]), 4),
                    quality_flag, reason, round(confidence, 4), 1 if param["is_golden"] else 0,
                    param["profile_id"], origin, METHOD_VERSION, provenance,
                ))
                series[child_asin]["clean"].append(float(clean))
                series[child_asin]["observed"].append(units)
                series[child_asin]["potential"].append(potential)
                series[child_asin]["weekday"].append(current.weekday())
                series[child_asin]["ad_spend"].append(ad_spend)
                series[child_asin]["price"].append(selling_price)
                series[child_asin]["promo"].append(driver["promotion_type"])
        insert_rows(connection, "fact_child_sales_daily", sales_rows)
        insert_rows(connection, "fact_child_traffic_daily", traffic_rows)
        insert_rows(connection, "fact_child_advertising_daily", ad_rows)
        insert_rows(connection, "fact_child_price_daily", price_rows)
        insert_rows(connection, "fact_child_promotion_daily", promo_rows)
        insert_rows(connection, "feature_child_demand_daily", feature_rows)
        connection.commit()
    return series


def _build_inventory(
    connection: sqlite3.Connection,
    children: Sequence[Mapping[str, Any]],
    params: Mapping[str, Mapping[str, Any]],
    series: Mapping[str, Mapping[str, List[Any]]],
) -> Dict[str, Dict[str, int]]:
    dates = date_range(HISTORY_START, HISTORY_DAYS)
    final_inventory: Dict[str, Dict[str, int]] = {}
    rows: List[Tuple[Any, ...]] = []
    for child_index, child in enumerate(children):
        child_asin = child["child_asin"]
        param = params[child_asin]
        observed = series[child_asin]["observed"]
        recent_avg = max(0.2, mean(observed[-90:]))
        target_final = max(0, int(child["fba_sellable"]))
        if child["inventory_missing"]:
            target_final = round(recent_avg * 24)
        current_stock = max(round(recent_avg * (38 + child_index % 18)), target_final)
        scheduled: Dict[int, int] = {}
        lead = max(7, min(60, int(child["stocking_lead_days"])))
        for day_index, current in enumerate(dates):
            opening = current_stock
            received = scheduled.pop(day_index, 0)
            reserved_release = round(recent_avg * 0.4) if day_index % 31 == child_index % 31 else 0
            other_flow = 0
            units = int(observed[day_index])
            forced_stockout = bool(param["is_golden"] and param["profile_id"] == "stockout_censored" and 520 <= day_index <= 533)
            available = opening + received + reserved_release
            if forced_stockout:
                other_flow = units - available
                closing = 0
            else:
                if available < units:
                    other_flow += units - available
                closing = max(0, available + other_flow - units)
            if closing < recent_avg * 14 and day_index + lead < HISTORY_DAYS and not forced_stockout:
                arrival_day = day_index + lead
                if arrival_day not in scheduled:
                    scheduled[arrival_day] = max(1, round(recent_avg * (52 + child_index % 16)))
            if day_index == HISTORY_DAYS - 1:
                other_flow += target_final - closing
                closing = target_final
            upcoming = sum(quantity for index, quantity in scheduled.items() if day_index < index <= day_index + lead)
            fba_reserved = int(child["fba_reserved"]) if day_index == HISTORY_DAYS - 1 else max(0, round(closing * 0.04))
            fba_receiving = int(child["fba_receiving"]) if day_index == HISTORY_DAYS - 1 else max(0, round(upcoming * 0.08))
            fba_inbound = int(child["fba_inbound"]) if day_index == HISTORY_DAYS - 1 else upcoming
            overseas_available = int(child["overseas_available"]) if day_index == HISTORY_DAYS - 1 else max(0, round(closing * 0.22))
            overseas_inbound = int(child["overseas_inbound"]) if day_index == HISTORY_DAYS - 1 else max(0, round(upcoming * 0.20))
            local_available = int(child["local_available"]) if day_index == HISTORY_DAYS - 1 else max(0, round(closing * 0.15))
            coverage = closing / recent_avg
            stockout = 1 if forced_stockout or closing < max(1.0, recent_avg * 1.5) else 0
            provenance = json_text({"target_snapshot": day_index == HISTORY_DAYS - 1, "profile": param["profile_id"]})
            rows.append((
                current.isoformat(), child_asin, child["parent_asin"], opening, received,
                reserved_release, other_flow, units, closing, fba_reserved, fba_receiving,
                fba_inbound, overseas_available, overseas_inbound, local_available,
                stockout, round2(coverage), "complete" if not child["inventory_missing"] else "supplemented",
                "derived_from_actual" if day_index == HISTORY_DAYS - 1 and not child["inventory_missing"] else "synthetic_demo",
                METHOD_VERSION, provenance,
            ))
            current_stock = closing
            if len(rows) >= 12000:
                insert_rows(connection, "fact_child_inventory_daily", rows)
                rows.clear()
        final_inventory[child_asin] = {
            "fba_sellable": target_final,
            "fba_reserved": int(child["fba_reserved"]),
            "fba_receiving": int(child["fba_receiving"]),
            "fba_inbound": int(child["fba_inbound"]),
            "overseas_available": int(child["overseas_available"]),
            "local_available": int(child["local_available"]),
        }
    insert_rows(connection, "fact_child_inventory_daily", rows)
    connection.commit()
    return final_inventory


def _build_supply_bridge(connection: sqlite3.Connection, supply_events: Sequence[Mapping[str, Any]], children: Sequence[Mapping[str, Any]], params: Mapping[str, Mapping[str, Any]]) -> None:
    by_style: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    by_parent: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for child in children:
        by_style[str(child["style_no"] or "")].append(child)
        by_parent[str(child["parent_asin"])].append(child)
    rows: List[Tuple[Any, ...]] = []
    for event in supply_events:
        candidates = by_style.get(str(event.get("style_no") or ""), [])
        if not candidates:
            try:
                parents = json.loads(event.get("matched_parent_asins") or "[]")
            except json.JSONDecodeError:
                parents = []
            candidates = [child for parent in parents for child in by_parent.get(parent, [])]
        if not candidates:
            continue
        total = max(0, int(event.get("sellable_units") or 0))
        allocations = largest_remainder(total, [float(params[child["child_asin"]]["base_weight"]) for child in candidates])
        for child, allocated in zip(candidates, allocations):
            if allocated <= 0:
                continue
            rows.append((
                event["supply_event_id"], child["child_asin"], child["parent_asin"], allocated,
                round(allocated / total, 8) if total else 0.0,
                str(event.get("eta_earliest_effective") or AS_OF_DATE.isoformat()),
                str(event.get("eta_latest_effective") or AS_OF_DATE.isoformat()),
                str(event.get("event_status_as_of") or "unknown"), "style_weighted_by_90d_sales",
                0.82, "derived_from_actual", METHOD_VERSION,
                json_text({"source_event": event["supply_event_id"], "style_no": event.get("style_no")}),
            ))
    insert_rows(connection, "bridge_supply_event_child", rows)
    connection.commit()


def _future_promotion(param: Mapping[str, Any], index: int) -> Tuple[str, str, float, float]:
    profile_id = param["profile_id"]
    if profile_id == "promotion_spike" and 31 <= index <= 36:
        return ("PLAN-BD-01", "BD", 0.20, float(param["promo_uplift"]))
    if profile_id == "advertising_growth" and 57 <= index <= 60:
        return ("PLAN-LD-01", "LD", 0.12, float(param["promo_uplift"]))
    offset = stable_seed(str(param["child"]["child_asin"]) + ":future-promo") % 67
    if (index + offset) % 73 < 3:
        return ("PLAN-CP-%02d" % index, "Coupon", 0.08, float(param["promo_uplift"]) * 0.60)
    return ("none", "none", 0.0, 0.0)


def _build_future_and_forecast(
    connection: sqlite3.Connection,
    children: Sequence[Mapping[str, Any]],
    params: Mapping[str, Mapping[str, Any]],
    series: Mapping[str, Mapping[str, List[Any]]],
) -> Tuple[Dict[str, List[Dict[str, Any]]], Dict[str, Dict[str, Any]]]:
    future_dates = date_range(FORECAST_START, FORECAST_DAYS)
    connection.execute(
        "INSERT INTO fact_child_forecast_run VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            FORECAST_RUN_ID, AS_OF_DATE.isoformat(), FORECAST_DAYS, "golden_only",
            DATASET_VERSION, json_text(MODEL_NAMES), 56, "completed", METHOD_VERSION,
            datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        ),
    )
    ad_plan_rows: List[Tuple[Any, ...]] = []
    price_plan_rows: List[Tuple[Any, ...]] = []
    promo_plan_rows: List[Tuple[Any, ...]] = []
    evaluation_rows: List[Tuple[Any, ...]] = []
    forecast_rows: List[Tuple[Any, ...]] = []
    forecasts: Dict[str, List[Dict[str, Any]]] = {}
    model_summary: Dict[str, Dict[str, Any]] = {}
    for child in children:
        child_asin = child["child_asin"]
        param = params[child_asin]
        values = [max(0.0, float(value)) for value in series[child_asin]["clean"]]
        weekdays = [int(value) for value in series[child_asin]["weekday"]]
        lifecycle = _lifecycle_at(param, HISTORY_DAYS - 1)
        selected, metrics = evaluate_models(values, weekdays, lifecycle)
        selected_metrics = metrics[selected]
        confidence = clamp(1 - selected_metrics["wape"], 0.52, 0.96)
        model_summary[child_asin] = {
            "selected_model": selected,
            "metrics": metrics,
            "confidence": confidence,
        }
        for model_name in MODEL_NAMES:
            metric = metrics[model_name]
            evaluation_rows.append((
                FORECAST_RUN_ID, child_asin, model_name, round(metric["wape"], 6),
                round(metric["bias"], 6), round2(metric["mae"]), int(metric["validation_days"]),
                1 if model_name == selected else 0, round(confidence, 4), METHOD_VERSION,
            ))
        future_weekdays = [current.weekday() for current in future_dates]
        baseline = forecast_baseline(selected, values, weekdays, future_weekdays, lifecycle)
        base_ad = max(0.1, mean(series[child_asin]["ad_spend"][-28:]))
        base_price = max(0.1, mean(series[child_asin]["price"][-28:]))
        ratio = interval_ratio(selected_metrics["wape"], confidence)
        child_forecasts: List[Dict[str, Any]] = []
        for index, (current, base_units) in enumerate(zip(future_dates, baseline)):
            promo_id, promo_type, promo_discount, promo_uplift = _future_promotion(param, index)
            ad_multiplier = 1.0
            if param["profile_id"] == "advertising_growth":
                ad_multiplier = 1.16 + 0.30 * (index / max(1, FORECAST_DAYS - 1))
            elif param["profile_id"] == "decline_overstock":
                ad_multiplier = 0.82
            planned_spend = round2(base_ad * ad_multiplier * (1 + 0.05 * math.sin(index / 6)))
            ad_effect = clamp(1 + float(param["ad_elasticity"]) * (planned_spend / base_ad - 1), 0.72, 1.48)
            list_price = round2(float(param["base_price"]) * (1 + 0.01 * math.sin(index / 19)))
            selling_price = round2(list_price * (1 - promo_discount))
            price_effect = clamp((selling_price / base_price) ** float(param["price_elasticity"]), 0.68, 1.45)
            promo_effect = 1 + promo_uplift
            lifecycle_factor = 1.0
            if param["profile_id"] == "advertising_growth":
                lifecycle_factor = 1 + 0.0007 * index
            elif param["profile_id"] == "decline_overstock":
                lifecycle_factor = max(0.78, 1 - 0.0022 * index)
            seasonality = 1 + 0.105 * math.sin((2 * math.pi * (current.timetuple().tm_yday - 25)) / 365.25)
            weekday_factor = WEEKDAY_FACTORS[current.weekday()]
            adjusted = max(0.0, base_units * ad_effect * price_effect * promo_effect * lifecycle_factor)
            p50 = max(0, round(adjusted))
            p10 = max(0, round(adjusted * (1 - ratio)))
            p90 = max(p50, round(adjusted * (1 + ratio)))
            effect_source = "historical_estimate" if sum(1 for value in series[child_asin]["promo"] if value != "none") >= 5 else "peer_then_plan_fallback"
            provenance = json_text({"selected_model": selected, "profile": param["profile_id"], "fallback": effect_source})
            impressions = max(0, round(planned_spend / 0.92 / 0.012))
            clicks = max(0, round(impressions * 0.012))
            ad_plan_rows.append((
                current.isoformat(), child_asin, child["parent_asin"], round2(planned_spend * 1.12), planned_spend,
                impressions, clicks, round(ad_effect, 4), effect_source, "approved", "customer_plan",
                METHOD_VERSION, provenance,
            ))
            price_plan_rows.append((
                current.isoformat(), child_asin, child["parent_asin"], list_price, selling_price,
                round2(list_price - selling_price), round(promo_discount, 4), round(price_effect, 4),
                effect_source, "approved", "customer_plan", METHOD_VERSION, provenance,
            ))
            promo_plan_rows.append((
                current.isoformat(), child_asin, child["parent_asin"], promo_id, promo_type,
                "approved" if promo_type != "none" else "none", round(promo_discount, 4),
                round(promo_uplift, 4), round(promo_effect, 4), effect_source,
                "customer_plan", METHOD_VERSION, provenance,
            ))
            forecast_rows.append((
                FORECAST_RUN_ID, current.isoformat(), child_asin, child["parent_asin"],
                round2(base_units), round(weekday_factor, 4), round(seasonality, 4),
                round(lifecycle_factor, 4), round(ad_effect, 4), round(price_effect, 4),
                round(promo_effect, 4), p10, p50, p90, selected,
                round(selected_metrics["wape"], 6), effect_source, round(confidence, 4),
                "model_derived", METHOD_VERSION, provenance,
            ))
            child_forecasts.append({
                "date": current, "p10": p10, "p50": p50, "p90": p90,
                "baseline": base_units, "ad_effect": ad_effect, "price_effect": price_effect,
                "promo_effect": promo_effect, "lifecycle_factor": lifecycle_factor,
            })
        forecasts[child_asin] = child_forecasts
    insert_rows(connection, "plan_child_advertising_daily", ad_plan_rows)
    insert_rows(connection, "plan_child_price_daily", price_plan_rows)
    insert_rows(connection, "plan_child_promotion_daily", promo_plan_rows)
    insert_rows(connection, "fact_child_forecast_evaluation", evaluation_rows)
    insert_rows(connection, "fact_child_forecast_daily", forecast_rows)
    connection.commit()
    return forecasts, model_summary


def _build_policy_supply_and_projection(
    connection: sqlite3.Connection,
    children: Sequence[Mapping[str, Any]],
    params: Mapping[str, Mapping[str, Any]],
    series: Mapping[str, Mapping[str, List[Any]]],
    forecasts: Mapping[str, List[Mapping[str, Any]]],
    model_summary: Mapping[str, Mapping[str, Any]],
    final_inventory: Mapping[str, Mapping[str, int]],
) -> Dict[str, Dict[str, Any]]:
    policy_rows: List[Tuple[Any, ...]] = []
    supply_rows: List[Tuple[Any, ...]] = []
    projection_rows: List[Tuple[Any, ...]] = []
    decision_rows: List[Tuple[Any, ...]] = []
    decisions: Dict[str, Dict[str, Any]] = {}
    for child_index, child in enumerate(children):
        child_asin = child["child_asin"]
        param = params[child_asin]
        forecast = forecasts[child_asin]
        recent = [float(value) for value in series[child_asin]["clean"][-90:]]
        recent_mean = max(0.2, mean(recent))
        variation = pstdev(recent) / recent_mean if len(recent) > 1 else 0.0
        stage = _lifecycle_at(param, HISTORY_DAYS - 1)
        lifecycle_days = {"新品期": 28, "成长期": 21, "成熟期": 14, "衰退期": 8}.get(stage, 14)
        lead = max(14, min(90, int(child["stocking_lead_days"])))
        dynamic_days = max(7, min(35, lifecycle_days + round(min(7, variation * 10)) + round(min(7, lead / 18))))
        service_level = 0.97 if stage in ("新品期", "成长期") else 0.95
        if param["profile_id"] == "stable_mature":
            target_coverage = 60
        elif param["profile_id"] == "advertising_growth":
            target_coverage = 50
        else:
            target_coverage = 45 if stage in ("新品期", "成长期") else (30 if stage == "衰退期" else 38)
        preferred_mode = "air+sea" if stage in ("新品期", "成长期") else "sea"
        provenance = json_text({"source_supply_plan": not child["inventory_missing"], "profile": param["profile_id"]})
        policy_rows.append((
            child_asin, child["parent_asin"], FORECAST_START.isoformat(), FORECAST_END.isoformat(),
            service_level, dynamic_days, int(child["purchase_lead_days"]), int(child["quality_check_days"]),
            int(child["overseas_to_fba_days"]), 5, target_coverage, preferred_mode,
            "derived_from_actual", METHOD_VERSION, provenance,
        ))
        total_60 = sum(int(row["p50"]) for row in forecast[:60])
        first_day = 24 if param["profile_id"] != "stockout_censored" else 39
        first_qty = max(1, round(total_60 * (0.68 if stage != "衰退期" else 0.25)))
        second_qty = max(1, round(total_60 * (0.34 if stage != "衰退期" else 0.12)))
        if param["profile_id"] == "stable_mature":
            total_90 = sum(int(row["p50"]) for row in forecast)
            starting_snapshot = int(final_inventory[child_asin]["fba_sellable"])
            first_day = 7
            first_qty = max(1, total_90 + round(recent_mean * dynamic_days) - starting_snapshot)
            second_qty = max(1, round(total_90 * 0.10))
        event_specs = [
            ("A", first_day, first_qty, "high", "sea" if first_day >= 30 else "air"),
            ("B", min(82, first_day + 31), second_qty, "medium", "sea"),
        ]
        event_maps: List[Dict[str, Any]] = []
        for suffix, day_index, units, confidence_level, mode in event_specs:
            eta_earliest = FORECAST_START + timedelta(days=day_index)
            eta_latest = eta_earliest + timedelta(days=3 if confidence_level == "high" else 8)
            event_id = "PLAN-%s-%s" % (child_asin, suffix)
            supply_rows.append((
                event_id, child_asin, child["parent_asin"], units,
                "local" if mode == "air" else "overseas", "FBA", mode,
                eta_earliest.isoformat(), eta_latest.isoformat(), "confirmed" if confidence_level == "high" else "planned",
                confidence_level, "customer_plan", METHOD_VERSION, provenance,
            ))
            event_maps.append({
                "units": units, "confidence": confidence_level,
                "earliest_index": day_index, "latest_index": min(FORECAST_DAYS - 1, day_index + (3 if confidence_level == "high" else 8)),
            })
        starting = int(final_inventory[child_asin]["fba_sellable"])
        if param["is_golden"] and param["profile_id"] == "decline_overstock":
            starting = max(starting, round(sum(row["p50"] for row in forecast) * 1.7))
        scenario_results: Dict[str, List[Dict[str, Any]]] = {}
        for scenario in ("base", "stress", "improvement"):
            stock = starting
            results: List[Dict[str, Any]] = []
            for index, row in enumerate(forecast):
                demand = int(row["p90"] if scenario == "stress" else row["p50"])
                confirmed_arrivals = sum(
                    event["units"] for event in event_maps
                    if event["confidence"] == "high" and event["earliest_index"] == index
                )
                if scenario == "base":
                    considered = confirmed_arrivals
                elif scenario == "stress":
                    considered = sum(
                        event["units"] for event in event_maps
                        if event["confidence"] == "high" and min(FORECAST_DAYS - 1, event["latest_index"] + 7) == index
                    )
                else:
                    considered = sum(event["units"] for event in event_maps if event["earliest_index"] == index)
                opening = stock
                available = opening + considered
                fulfilled = min(available, demand)
                lost = max(0, demand - available)
                closing = max(0, available - fulfilled)
                safety_slice = forecast[index:min(FORECAST_DAYS, index + dynamic_days)]
                safety_units = round(sum(float(item["p50"]) for item in safety_slice))
                next14 = forecast[index:min(FORECAST_DAYS, index + 14)]
                average_next = max(0.2, mean(float(item["p50"]) for item in next14))
                coverage = closing / average_next
                if lost > 0 or closing == 0:
                    risk = "stockout"
                elif closing < safety_units and index < lead:
                    risk = "replenishment_gap"
                elif closing < safety_units:
                    risk = "safety_stock_breach"
                elif coverage > target_coverage * 2 and param["profile_id"] == "decline_overstock":
                    risk = "aged_inventory_risk"
                elif coverage > target_coverage * 2:
                    risk = "overstock"
                else:
                    risk = "healthy"
                projection_rows.append((
                    FORECAST_RUN_ID, scenario, row["date"].isoformat(), child_asin, child["parent_asin"],
                    opening, confirmed_arrivals, considered, demand, fulfilled, lost, closing,
                    safety_units, round2(coverage), risk, "model_derived", METHOD_VERSION,
                    json_text({"profile": param["profile_id"], "arrival_policy": scenario}),
                ))
                results.append({"date": row["date"], "risk": risk, "lost": lost, "closing": closing, "safety": safety_units})
                stock = closing
            scenario_results[scenario] = results
        base = scenario_results["base"]
        stress = scenario_results["stress"]
        breach = next((item["date"] for item in base if item["risk"] != "healthy"), None)
        stockout = next((item["date"] for item in base if item["risk"] == "stockout"), None)
        stress_stockout = next((item["date"] for item in stress if item["risk"] == "stockout"), None)
        latest_order = (stockout or breach or FORECAST_END) - timedelta(days=lead)
        horizon_for_order = min(FORECAST_DAYS, lead + target_coverage)
        required = sum(int(item["p50"]) for item in forecast[:horizon_for_order])
        high_arrivals = sum(event["units"] for event in event_maps if event["confidence"] == "high" and event["earliest_index"] < horizon_for_order)
        dynamic_safety_units = round(sum(float(item["p50"]) for item in forecast[:dynamic_days]))
        suggested = max(0, required + dynamic_safety_units - starting - high_arrivals)
        urgent = stockout is not None and (stockout - FORECAST_START).days < lead
        air = round(suggested * 0.35) if urgent else 0
        sea = max(0, suggested - air)
        lost_total = sum(int(item["lost"]) for item in base)
        ending = int(base[-1]["closing"])
        base_status = next((item["risk"] for item in base if item["risk"] != "healthy"), "healthy")
        summary = (
            "库存健康，现有供给可承接90天需求。" if base_status == "healthy"
            else "基准场景出现%s；建议补货%s件，其中空运%s件、海运%s件。" % (base_status, suggested, air, sea)
        )
        decision_rows.append((
            FORECAST_RUN_ID, child_asin, child["parent_asin"], base_status,
            breach.isoformat() if breach else "none", stockout.isoformat() if stockout else "none",
            stress_stockout.isoformat() if stress_stockout else "none", latest_order.isoformat(),
            suggested, air, sea, lost_total, ending, dynamic_days, dynamic_safety_units,
            summary, round(float(model_summary[child_asin]["confidence"]), 4),
            "model_derived", METHOD_VERSION, provenance,
        ))
        decisions[child_asin] = {
            "base_risk_status": base_status,
            "safety_breach_date": breach.isoformat() if breach else "none",
            "base_stockout_date": stockout.isoformat() if stockout else "none",
            "stress_stockout_date": stress_stockout.isoformat() if stress_stockout else "none",
            "suggested_replenishment_qty": suggested,
            "ending_inventory_units": ending,
            "lost_sales_units": lost_total,
            "dynamic_safety_days": dynamic_days,
        }
    insert_rows(connection, "config_child_inventory_policy", policy_rows)
    insert_rows(connection, "plan_child_supply_event", supply_rows)
    insert_rows(connection, "fact_child_inventory_projection_daily", projection_rows)
    insert_rows(connection, "fact_child_inventory_decision", decision_rows)
    connection.commit()
    return decisions


def _table_specs(connection: sqlite3.Connection) -> Dict[str, Any]:
    specs: Dict[str, Any] = {}
    for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        table = row[0]
        columns = [item[1] for item in connection.execute("PRAGMA table_info(%s)" % table)]
        pk = [item[1] for item in connection.execute("PRAGMA table_info(%s)" % table) if item[5]]
        count = connection.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0]
        specs[table] = {"record_count": count, "fields": columns, "key": pk}
    return specs


def _quality_checks(connection: sqlite3.Connection, golden: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    checks: List[Dict[str, Any]] = []

    def add(name: str, expected: Any, actual: Any, severity: str = "critical") -> None:
        checks.append({"check": name, "expected": expected, "actual": actual, "passed": actual == expected, "severity_if_failed": severity})

    expected_history = 342 * HISTORY_DAYS
    expected_future = 342 * FORECAST_DAYS
    for table in HISTORICAL_DAILY_TABLES:
        add("%s_row_count" % table, expected_history, connection.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0])
    for table in FUTURE_DAILY_TABLES:
        add("%s_row_count" % table, expected_future, connection.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0])
    add("inventory_projection_row_count", expected_future * 3, connection.execute("SELECT COUNT(*) FROM fact_child_inventory_projection_daily").fetchone()[0])
    add("child_count", 342, connection.execute("SELECT COUNT(DISTINCT child_asin) FROM fact_child_sales_daily").fetchone()[0])
    add("golden_profile_count", 5, connection.execute("SELECT COUNT(*) FROM dim_demo_profile").fetchone()[0])
    add("route_count", 342, connection.execute("SELECT COUNT(*) FROM bridge_demo_child_route").fetchone()[0])
    add("forecast_evaluation_count", 342 * len(MODEL_NAMES), connection.execute("SELECT COUNT(*) FROM fact_child_forecast_evaluation").fetchone()[0])
    parent_diff = connection.execute("""
        SELECT COUNT(*) FROM (
          SELECT p.date, p.parent_asin, p.units_sold, SUM(c.units_sold) AS child_units
          FROM fact_parent_sales_daily p
          JOIN fact_child_sales_daily c ON c.date=p.date AND c.parent_asin=p.parent_asin
          WHERE p.date BETWEEN ? AND ?
          GROUP BY p.date,p.parent_asin,p.units_sold
          HAVING p.units_sold <> SUM(c.units_sold)
        )
    """, (HISTORY_START.isoformat(), AS_OF_DATE.isoformat())).fetchone()[0]
    add("parent_child_sales_reconciliation", 0, parent_diff)
    add("advertising_domain_rules", 0, connection.execute("""
        SELECT COUNT(*) FROM fact_child_advertising_daily
        WHERE clicks > impressions OR ad_orders < 0 OR ad_spend < 0 OR ad_sales < 0
    """).fetchone()[0])
    add("price_domain_rules", 0, connection.execute("""
        SELECT COUNT(*) FROM fact_child_price_daily
        WHERE selling_price > list_price + 0.01 OR selling_price <= 0 OR list_price <= 0
    """).fetchone()[0])
    add("historical_inventory_balance", 0, connection.execute("""
        SELECT COUNT(*) FROM fact_child_inventory_daily
        WHERE opening_fba_sellable + received_units + reserved_release_units + other_net_flow_units - units_sold <> closing_fba_sellable
           OR closing_fba_sellable < 0
    """).fetchone()[0])
    add("projection_inventory_balance", 0, connection.execute("""
        SELECT COUNT(*) FROM fact_child_inventory_projection_daily
        WHERE opening_sellable + considered_arrivals - fulfilled_units <> closing_sellable
           OR fulfilled_units + lost_sales_units <> forecast_demand
           OR closing_sellable < 0
    """).fetchone()[0])
    add("forecast_quantile_order", 0, connection.execute("""
        SELECT COUNT(*) FROM fact_child_forecast_daily WHERE p10_units > p50_units OR p50_units > p90_units
    """).fetchone()[0])
    add("future_plan_leakage", 0, connection.execute("""
        SELECT COUNT(*) FROM feature_child_demand_daily WHERE date > ?
    """, (AS_OF_DATE.isoformat(),)).fetchone()[0])
    golden_asins = [row["child_asin"] for row in golden.values()]
    placeholders = ",".join("?" for _ in golden_asins)
    worst_gold_wape = connection.execute(
        "SELECT MAX(wape) FROM fact_child_forecast_evaluation WHERE selected=1 AND child_asin IN (%s)" % placeholders,
        golden_asins,
    ).fetchone()[0]
    checks.append({
        "check": "golden_selected_model_wape",
        "expected": "<=0.20",
        "actual": round(float(worst_gold_wape), 6),
        "passed": float(worst_gold_wape) <= 0.20,
        "severity_if_failed": "high",
    })
    stable_status = connection.execute("""
        SELECT d.base_risk_status FROM dim_demo_profile p
        JOIN fact_child_inventory_decision d ON d.child_asin=p.golden_child_asin
        WHERE p.profile_id='stable_mature'
    """).fetchone()[0]
    add("golden_stable_inventory_healthy", "healthy", stable_status, "high")
    promotion_days = connection.execute("""
        SELECT COUNT(*) FROM dim_demo_profile p
        JOIN plan_child_promotion_daily x ON x.child_asin=p.golden_child_asin
        WHERE p.profile_id='promotion_spike' AND x.promotion_type='BD'
    """).fetchone()[0]
    checks.append({"check": "golden_promotion_future_bd_days", "expected": ">=5", "actual": promotion_days, "passed": promotion_days >= 5, "severity_if_failed": "high"})
    stockout_days = connection.execute("""
        SELECT COUNT(*) FROM dim_demo_profile p
        JOIN feature_child_demand_daily x ON x.child_asin=p.golden_child_asin
        WHERE p.profile_id='stockout_censored' AND x.demand_quality_flag='stockout_censored'
    """).fetchone()[0]
    checks.append({"check": "golden_stockout_history_days", "expected": ">=10", "actual": stockout_days, "passed": stockout_days >= 10, "severity_if_failed": "high"})
    decline_status = connection.execute("""
        SELECT d.base_risk_status FROM dim_demo_profile p
        JOIN fact_child_inventory_decision d ON d.child_asin=p.golden_child_asin
        WHERE p.profile_id='decline_overstock'
    """).fetchone()[0]
    checks.append({"check": "golden_decline_inventory_risk", "expected": "overstock_or_aged", "actual": decline_status, "passed": decline_status in ("overstock", "aged_inventory_risk"), "severity_if_failed": "high"})
    ad_growth = connection.execute("""
        SELECT MIN(expected_effect_ratio),MAX(expected_effect_ratio)
        FROM dim_demo_profile p JOIN plan_child_advertising_daily x ON x.child_asin=p.golden_child_asin
        WHERE p.profile_id='advertising_growth'
    """).fetchone()
    checks.append({"check": "golden_advertising_growth_effect", "expected": "max>min", "actual": [round(ad_growth[0], 4), round(ad_growth[1], 4)], "passed": ad_growth[1] > ad_growth[0], "severity_if_failed": "high"})
    for table in HISTORICAL_DAILY_TABLES + FUTURE_DAILY_TABLES:
        columns = [row[1] for row in connection.execute("PRAGMA table_info(%s)" % table) if row[3]]
        null_clause = " OR ".join("%s IS NULL" % column for column in columns)
        null_count = connection.execute("SELECT COUNT(*) FROM %s WHERE %s" % (table, null_clause)).fetchone()[0] if null_clause else 0
        add("%s_required_nulls" % table, 0, null_count)
    return {
        "dataset_version": DATASET_VERSION,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "checks": checks,
        "all_checks_passed": all(item["passed"] for item in checks),
    }


def _reconciliation(connection: sqlite3.Connection) -> List[Dict[str, Any]]:
    connection.row_factory = sqlite3.Row
    return [dict(row) for row in connection.execute("""
        SELECT p.parent_asin,
               COUNT(*) AS actual_parent_days,
               SUM(p.units_sold) AS parent_units,
               SUM(x.child_units) AS child_units,
               SUM(x.child_units) - SUM(p.units_sold) AS difference
        FROM fact_parent_sales_daily p
        JOIN (
          SELECT date,parent_asin,SUM(units_sold) AS child_units
          FROM fact_child_sales_daily GROUP BY date,parent_asin
        ) x ON x.date=p.date AND x.parent_asin=p.parent_asin
        WHERE p.date BETWEEN ? AND ?
        GROUP BY p.parent_asin ORDER BY p.parent_asin
    """, (HISTORY_START.isoformat(), AS_OF_DATE.isoformat()))]


def _golden_report(
    connection: sqlite3.Connection,
    golden: Mapping[str, Mapping[str, Any]],
    decisions: Mapping[str, Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    report: List[Dict[str, Any]] = []
    for profile in PROFILES:
        child = golden[profile["profile_id"]]
        child_asin = child["child_asin"]
        evaluation = connection.execute("""
            SELECT model_name,wape,bias,mae FROM fact_child_forecast_evaluation
            WHERE forecast_run_id=? AND child_asin=? AND selected=1
        """, (FORECAST_RUN_ID, child_asin)).fetchone()
        forecast_total = connection.execute("""
            SELECT SUM(p50_units),SUM(p10_units),SUM(p90_units)
            FROM fact_child_forecast_daily WHERE forecast_run_id=? AND child_asin=?
        """, (FORECAST_RUN_ID, child_asin)).fetchone()
        quality = dict(connection.execute("""
            SELECT SUM(demand_quality_flag='stockout_censored') AS stockout_days,
                   SUM(demand_quality_flag='promotion_event') AS promotion_days,
                   SUM(demand_quality_flag='ad_shock') AS ad_shock_days
            FROM feature_child_demand_daily WHERE child_asin=?
        """, (child_asin,)).fetchone())
        report.append({
            "profile_id": profile["profile_id"],
            "profile_name": profile["profile_name"],
            "child_asin": child_asin,
            "parent_asin": child["parent_asin"],
            "style_name": child["style_name"],
            "selected_model": evaluation["model_name"],
            "wape": evaluation["wape"],
            "bias": evaluation["bias"],
            "mae": evaluation["mae"],
            "forecast_p10_total": forecast_total[1],
            "forecast_p50_total": forecast_total[0],
            "forecast_p90_total": forecast_total[2],
            "history_flags": quality,
            "inventory_decision": decisions[child_asin],
        })
    return report


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _export_table(connection: sqlite3.Connection, table: str, output: Path) -> int:
    connection.row_factory = sqlite3.Row
    count = 0
    with output.open("w", encoding="utf-8") as handle:
        handle.write("[\n")
        first = True
        cursor = connection.execute("SELECT * FROM %s" % table)
        for row in cursor:
            if not first:
                handle.write(",\n")
            handle.write(json.dumps(dict(row), ensure_ascii=False, separators=(",", ":")))
            first = False
            count += 1
        handle.write("\n]\n")
    return count


def _write_readme(path: Path, quality: Mapping[str, Any], golden_report: Sequence[Mapping[str, Any]], specs: Mapping[str, Any]) -> None:
    lines = [
        "# 产品销售库存与 Agent 决策数据包 v0.3.0",
        "",
        "统一业务截止日：2026-08-03  ",
        "历史范围：%s 至 %s（%d 天）  " % (HISTORY_START.isoformat(), AS_OF_DATE.isoformat(), HISTORY_DAYS),
        "预测范围：2026-08-04 至 2026-11-01（90 天）",
        "",
        "## 数据范围",
        "",
        "- 子 ASIN：342 个；",
        "- 每张历史日表：249,660 行；",
        "- 每张未来计划与预测日表：30,780 行；",
        "- 三场景库存投影：92,340 行；",
        "- 黄金场景：5 个；",
        "- SQLite 表总数：%d。" % len(specs),
        "",
        "## 五个黄金场景",
        "",
        "| 场景 | 子 ASIN | 模型 | WAPE | P50 90天 | 库存判断 |",
        "| --- | --- | --- | ---: | ---: | --- |",
    ]
    for row in golden_report:
        lines.append(
            "| %s | `%s` | %s | %.2f%% | %s | %s |"
            % (
                row["profile_name"], row["child_asin"], row["selected_model"], row["wape"] * 100,
                f"{row['forecast_p50_total']:,}", row["inventory_decision"]["base_risk_status"],
            )
        )
    lines.extend([
        "",
        "## 来源边界",
        "",
        "- v0.2.2 产品、父级逐日销量、库存快照、库龄和供应事件保留为来源基线；",
        "- 子 ASIN 逐日历史包含父级事实分配与合成补充，必须查看 `value_origin`；",
        "- 预测、库存投影与补货建议均为 `model_derived`；",
        "- 本数据包用于 Demo，不应作为真实采购承诺。",
        "",
        "## 质量结果",
        "",
        "全部质量检查通过。" if quality["all_checks_passed"] else "存在未通过检查，禁止接入 Agent。",
    ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_dataset() -> Dict[str, Any]:
    if not SOURCE_DB.exists():
        raise FileNotFoundError("v0.2.2 source database not found: %s" % SOURCE_DB)
    if STAGING_ROOT.exists():
        shutil.rmtree(STAGING_ROOT)
    STAGING_ROOT.mkdir(parents=True)
    for source_file in SOURCE_ROOT.iterdir():
        if source_file.is_file() and source_file.name != SOURCE_DB.name:
            shutil.copy2(source_file, STAGING_ROOT / source_file.name)
    target_db = STAGING_ROOT / OUTPUT_DB_NAME
    shutil.copy2(SOURCE_DB, target_db)
    connection = sqlite3.connect(str(target_db))
    try:
        connection.execute("PRAGMA journal_mode=OFF")
        connection.execute("PRAGMA synchronous=OFF")
        connection.execute("PRAGMA temp_store=MEMORY")
        create_v030_tables(connection)
        context = _source_context(connection)
        children = context["children"]
        if len(children) != 342:
            raise RuntimeError("expected 342 child ASINs, got %d" % len(children))
        golden = _choose_golden(children)
        params = _parameters(children, golden)
        _build_lifecycle_and_routes(connection, params, golden)
        series = _build_history(connection, children, context["parent_daily"], params)
        final_inventory = _build_inventory(connection, children, params, series)
        _build_supply_bridge(connection, context["supply_events"], children, params)
        forecasts, model_summary = _build_future_and_forecast(connection, children, params, series)
        decisions = _build_policy_supply_and_projection(
            connection, children, params, series, forecasts, model_summary, final_inventory,
        )
        connection.execute("ANALYZE")
        connection.commit()
        quality = _quality_checks(connection, golden)
        reconciliation = _reconciliation(connection)
        golden_report = _golden_report(connection, golden, decisions)
        specs = _table_specs(connection)
        if not quality["all_checks_passed"]:
            failed = [item for item in quality["checks"] if not item["passed"]]
            raise RuntimeError("v0.3.0 quality gate failed: %s" % json_text(failed))
        generated_tables = list(TABLE_DDL)
        for table in generated_tables:
            _export_table(connection, table, STAGING_ROOT / (table + ".json"))
        _write_json(STAGING_ROOT / "schema_catalog.json", {"dataset_version": DATASET_VERSION, "tables": specs})
        _write_json(STAGING_ROOT / "quality_report.json", quality)
        _write_json(STAGING_ROOT / "parent_child_reconciliation.json", reconciliation)
        _write_json(STAGING_ROOT / "golden_scenario_report.json", golden_report)
        _write_json(STAGING_ROOT / "generation_config.json", {
            "dataset_version": DATASET_VERSION,
            "source_version": "0.2.2",
            "as_of_date": AS_OF_DATE.isoformat(),
            "history_start": HISTORY_START.isoformat(),
            "history_days": HISTORY_DAYS,
            "forecast_start": FORECAST_START.isoformat(),
            "forecast_end": FORECAST_END.isoformat(),
            "forecast_days": FORECAST_DAYS,
            "random_seed": RANDOM_SEED,
            "method_version": METHOD_VERSION,
            "golden_profiles": [dict(item) for item in PROFILES],
        })
        _write_json(STAGING_ROOT / "source_lineage.json", {
            "dataset_version": DATASET_VERSION,
            "source_dataset": str(SOURCE_ROOT),
            "c_to_b_contracts": {
                "orders_refunds_returns": "fact_child_sales_daily",
                "business_report": "fact_child_traffic_daily",
                "advertising_reports": "fact_child_advertising_daily",
                "price_and_coupon_history": "fact_child_price_daily",
                "promotion_system": "fact_child_promotion_daily",
                "inventory_ledger": "fact_child_inventory_daily",
                "purchase_and_logistics": ["bridge_supply_event_child", "plan_child_supply_event"],
            },
            "notes": "Demo 构建只实现 B 层；C 层接口保留为未来真实数据接入契约。",
        })
        _write_json(STAGING_ROOT / "dataset-manifest.json", {
            "dataset_name": "bamboocool-child-demand-forecast-agent-demo",
            "dataset_version": DATASET_VERSION,
            "generated_at": quality["generated_at"],
            "as_of_date": AS_OF_DATE.isoformat(),
            "source_version": "0.2.2",
            "child_count": len(children),
            "history_days": HISTORY_DAYS,
            "forecast_days": FORECAST_DAYS,
            "table_count": len(specs),
            "files": sorted(path.name for path in STAGING_ROOT.iterdir() if path.is_file()),
            "quality_checks_passed": True,
        })
        _write_readme(STAGING_ROOT / "README.md", quality, golden_report, specs)
    finally:
        connection.close()
    if OUTPUT_ROOT.exists():
        shutil.rmtree(OUTPUT_ROOT)
    STAGING_ROOT.rename(OUTPUT_ROOT)
    return {
        "output": str(OUTPUT_ROOT),
        "database": str(OUTPUT_ROOT / OUTPUT_DB_NAME),
        "child_count": 342,
        "history_days": HISTORY_DAYS,
        "forecast_days": FORECAST_DAYS,
        "quality_checks_passed": True,
    }
