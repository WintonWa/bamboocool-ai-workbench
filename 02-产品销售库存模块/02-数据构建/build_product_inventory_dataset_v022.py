#!/usr/bin/env python3
"""Roll the 2026-06-30 inventory age buckets forward to the 2026-08-03 as-of date.

v0.2.2 adds a lot-level aging layer so every table in the package sits on one
business date. The customer's original June buckets are copied through
untouched; the rolled-forward view is a separate, explicitly derived table.

Method, in order:
  1. Each June bucket becomes uniform SLICE_DAYS-wide slices inside its own age
     range (1 day, so the 3-day and 7-day 180-crossing bands are not aliased).
     A bucket only states a range, so intra-bucket placement is an assumption,
     not customer data. Every slice is marked ``supplemented``.
  2. Sales between 2026-06-30 and 2026-08-03 deplete lots oldest-first (FIFO,
     recorded as a visible preset). The 34-day figure uses the real rolling
     windows: units_30d + 4 x daily rate implied by (units_60d - units_30d).
  3. Whatever is still missing against the 2026-08-03 FBA total becomes an
     implied arrival lot dated at the window midpoint; whatever is left over is
     depleted further. Both adjustments are reported per child, never smoothed.
  4. Buckets at 2026-08-03 are recomputed FROM the lots, so the lot table and
     the bucket table cannot disagree.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import shutil
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path("/Users/linsen/BAM")
BUILD_ROOT = ROOT / "02-产品销售库存模块/02-数据构建"
V021_BUILDER = BUILD_ROOT / "build_product_inventory_dataset_v021.py"
V010_ROOT = BUILD_ROOT / "v0.1.0"
V020_ROOT = BUILD_ROOT / "v0.2.0"
V021_ROOT = BUILD_ROOT / "v0.2.1"
OUTPUT_ROOT = BUILD_ROOT / "v0.2.2"
STAGING_ROOT = BUILD_ROOT / ".v0.2.2-building"

DATASET_VERSION = "0.2.2"
AS_OF_DATE = "2026-08-03"
AS_OF = date.fromisoformat(AS_OF_DATE)
AGE_SOURCE_DATE = "2026-06-30"
AGE_SOURCE = date.fromisoformat(AGE_SOURCE_DATE)
WINDOW_DAYS = (AS_OF - AGE_SOURCE).days
WINDOW_MIDPOINT = AGE_SOURCE + timedelta(days=WINDOW_DAYS // 2)
SLICE_DAYS = 1
DEPLETION_METHOD = "FIFO"
OPEN_BUCKET_ASSUMED_MAX_AGE = 420

# June bucket label -> inclusive age range at AGE_SOURCE_DATE
AGE_BUCKETS: list[tuple[str, int, int]] = [
    ("30天内库龄", 0, 30),
    ("31-60天库龄", 31, 60),
    ("61-90天库龄", 61, 90),
    ("91-180天库龄", 91, 180),
    ("181-270天库龄", 181, 270),
    ("271-330天库龄", 271, 330),
    ("331-365天库龄", 331, 365),
    ("大于365天库龄", 366, OPEN_BUCKET_ASSUMED_MAX_AGE),
]
BUCKET_LABELS = [label for label, _, _ in AGE_BUCKETS]


def load_v021():
    spec = importlib.util.spec_from_file_location("bam_v021", V021_BUILDER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法载入 v0.2.1 构建器：{V021_BUILDER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V021 = load_v021()
BUILD_TIMESTAMP = datetime.now().astimezone().isoformat(timespec="seconds")


def bucket_for_age(age_days: int) -> str:
    for label, low, high in AGE_BUCKETS[:-1]:
        if low <= age_days <= high:
            return label
    return BUCKET_LABELS[-1]


def load_v021_datasets() -> dict[str, list[dict[str, Any]]]:
    datasets: dict[str, list[dict[str, Any]]] = {}
    skip = {
        "dataset-manifest.json",
        "quality_report.json",
        "schema_catalog.json",
        "source_lineage.json",
        "source_selection_audit.json",
    }
    for path in sorted(V021_ROOT.glob("*.json")):
        if path.name in skip:
            continue
        datasets[path.name] = json.loads(path.read_text(encoding="utf-8"))
    return datasets


def window_consumption(window_row: dict[str, Any] | None) -> tuple[int, str]:
    """Real 34-day sell-through estimate from the customer's rolling windows."""
    if not window_row:
        return 0, "unknown"
    units_30 = window_row.get("units_30d") or 0
    units_60 = window_row.get("units_60d") or 0
    extra_days = WINDOW_DAYS - 30
    daily_31_60 = max(units_60 - units_30, 0) / 30
    return round(units_30 + extra_days * daily_31_60), "derived_from_real_rolling_windows"


def slice_bucket(quantity: int, low: int, high: int) -> list[tuple[int, int]]:
    """Split a bucket into SLICE_DAYS-wide slices. Returns [(age_days, quantity), ...]."""
    if quantity <= 0:
        return []
    edges = list(range(low, high + 1, SLICE_DAYS))
    spans = []
    for index, start in enumerate(edges):
        end = min(start + SLICE_DAYS - 1, high)
        spans.append((start, end))
        if end >= high:
            break
    total_days = sum(end - start + 1 for start, end in spans)
    out = []
    assigned = 0
    for index, (start, end) in enumerate(spans):
        if index == len(spans) - 1:
            qty = quantity - assigned
        else:
            qty = int(quantity * (end - start + 1) / total_days)
        assigned += qty
        if qty > 0:
            midpoint = start + (end - start) // 2
            out.append((midpoint, qty))
    return out


def build_lots(
    age_rows: list[dict[str, Any]],
    inventory_rows: list[dict[str, Any]],
    window_rows: list[dict[str, Any]],
    economics_rows: list[dict[str, Any]],
    method: str = DEPLETION_METHOD,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    inventory = {row["child_asin"]: row for row in inventory_rows}
    windows = {row["child_asin"]: row for row in window_rows}
    economics = {row["child_asin"]: row for row in economics_rows}
    oldest_first = method == "FIFO"

    lots: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []

    for age_row in age_rows:
        child = age_row["child_asin"]
        parent = age_row["parent_asin"]
        econ = economics.get(child, {})
        unit_cost = econ.get("unit_cost")
        unit_volume = econ.get("unit_volume_m3")

        # step 1: June buckets -> dated slices
        opening: list[dict[str, Any]] = []
        for label, low, high in AGE_BUCKETS:
            quantity = age_row.get(label) or 0
            for age_at_source, qty in slice_bucket(int(quantity), low, high):
                opening.append(
                    {
                        "source_bucket": label,
                        "received_at": (AGE_SOURCE - timedelta(days=age_at_source)).isoformat(),
                        "age_days_at_source": age_at_source,
                        "quantity": qty,
                        "origin": "supplemented",
                        "date_method": f"uniform {SLICE_DAYS}-day slice inside the June bucket range",
                        "date_confidence": "estimated",
                    }
                )
        opening.sort(key=lambda item: item["received_at"], reverse=not oldest_first)
        opening_total = sum(item["quantity"] for item in opening)

        # step 2: FIFO depletion by real window sales
        consumption_target, consumption_method = window_consumption(windows.get(child))
        remaining = copy.deepcopy(opening)
        consumed = 0
        to_consume = min(consumption_target, opening_total)
        for item in remaining:
            if to_consume <= 0:
                break
            take = min(item["quantity"], to_consume)
            item["quantity"] -= take
            consumed += take
            to_consume -= take
        consumption_clamped = max(consumption_target - opening_total, 0)

        # step 3: close against the 2026-08-03 FBA total
        snapshot = inventory.get(child)
        closing_target = snapshot["fba_inventory"] if snapshot else None
        arrival_qty = 0
        extra_depletion = 0
        if closing_target is None:
            closing_target = sum(item["quantity"] for item in remaining)
            close_note = "no_inventory_snapshot_row"
        else:
            current = sum(item["quantity"] for item in remaining)
            if closing_target > current:
                arrival_qty = closing_target - current
            elif closing_target < current:
                extra_depletion = current - closing_target
                to_drop = extra_depletion
                for item in remaining:
                    if to_drop <= 0:
                        break
                    take = min(item["quantity"], to_drop)
                    item["quantity"] -= take
                    to_drop -= take
            close_note = "closed_on_fba_inventory"

        kept = [item for item in remaining if item["quantity"] > 0]
        if arrival_qty > 0:
            kept.append(
                {
                    "source_bucket": None,
                    "received_at": WINDOW_MIDPOINT.isoformat(),
                    "age_days_at_source": None,
                    "quantity": arrival_qty,
                    "origin": "derived",
                    "date_method": (
                        "implied by balance: 2026-08-03 FBA total minus rolled-forward "
                        "June stock; dated at the window midpoint because the source "
                        "gives no child-level receipt date"
                    ),
                    "date_confidence": "estimated",
                }
            )

        for index, item in enumerate(sorted(kept, key=lambda row: row["received_at"])):
            received = date.fromisoformat(item["received_at"])
            age_days = (AS_OF - received).days
            quantity = item["quantity"]
            lots.append(
                {
                    "lot_id": f"LOT-{child}-{index + 1:02d}",
                    "as_of_date": AS_OF_DATE,
                    "child_asin": child,
                    "parent_asin": parent,
                    "location_type": "FBA",
                    "received_at": item["received_at"],
                    "age_days": age_days,
                    "age_bucket": bucket_for_age(age_days),
                    "days_to_180": 180 - age_days,
                    "crosses_180_within_3d": 0 < 180 - age_days <= 3,
                    "crosses_180_within_7d": 0 < 180 - age_days <= 7,
                    "already_over_180": age_days > 180,
                    "quantity": quantity,
                    "source_bucket_at_2026_06_30": item["source_bucket"],
                    "age_days_at_2026_06_30": item["age_days_at_source"],
                    "unit_cost": unit_cost,
                    "inventory_value": (
                        round(unit_cost * quantity, 2) if unit_cost is not None else None
                    ),
                    "unit_volume_m3": unit_volume,
                    "lot_volume_m3": (
                        round(unit_volume * quantity, 6) if unit_volume is not None else None
                    ),
                    "value_origin": item["origin"],
                    "date_method": item["date_method"],
                    "date_confidence": item["date_confidence"],
                    "depletion_method": method,
                }
            )

        closing_actual = sum(item["quantity"] for item in kept)
        audit.append(
            {
                "child_asin": child,
                "parent_asin": parent,
                "age_source_date": AGE_SOURCE_DATE,
                "as_of_date": AS_OF_DATE,
                "window_days": WINDOW_DAYS,
                "opening_qty_2026_06_30": opening_total,
                "consumption_target": consumption_target,
                "consumption_method": consumption_method,
                "consumption_applied": consumed,
                "consumption_unmet_by_opening": consumption_clamped,
                "implied_arrival_qty": arrival_qty,
                "extra_depletion_to_match_snapshot": extra_depletion,
                "closing_qty_2026_08_03": closing_actual,
                "closing_target_fba_inventory": closing_target,
                "balance_residual": closing_actual - closing_target,
                "close_note": close_note,
                "lot_count": sum(1 for lot in lots if lot["child_asin"] == child),
            }
        )
    return lots, audit


def build_rolled_buckets(
    lots: list[dict[str, Any]], age_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    by_child: dict[str, dict[str, int]] = defaultdict(lambda: {label: 0 for label in BUCKET_LABELS})
    for lot in lots:
        by_child[lot["child_asin"]][lot["age_bucket"]] += lot["quantity"]
    parents = {row["child_asin"]: row["parent_asin"] for row in age_rows}
    output = []
    for row in age_rows:
        child = row["child_asin"]
        buckets = by_child.get(child, {label: 0 for label in BUCKET_LABELS})
        aged = sum(buckets[label] for label in BUCKET_LABELS[4:])
        total = sum(buckets.values())
        output.append(
            {
                "as_of_date": AS_OF_DATE,
                "child_asin": child,
                "parent_asin": parents.get(child),
                **buckets,
                "total_qty": total,
                "aged_181_plus_qty": aged,
                "aged_181_plus_share": round(aged / total, 6) if total else None,
                "value_origin": "derived",
                "derivation": (
                    f"June buckets sliced uniformly, depleted {DEPLETION_METHOD} by real "
                    f"{WINDOW_DAYS}-day sell-through, then closed on the 2026-08-03 FBA total"
                ),
                "source_table": "fact_inventory_age_bucket (2026-06-30, unchanged)",
            }
        )
    return output


def counterfactual_aged_share(
    lots: list[dict[str, Any]],
    age_rows: list[dict[str, Any]],
    inventory_rows: list[dict[str, Any]],
    window_rows: list[dict[str, Any]],
    economics_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Run the identical pipeline with LIFO so the two numbers are comparable."""
    lifo_lots, _ = build_lots(
        age_rows, inventory_rows, window_rows, economics_rows, method="LIFO"
    )
    applied = sum(lot["quantity"] for lot in lots if lot["already_over_180"])
    lifo = sum(lot["quantity"] for lot in lifo_lots if lot["already_over_180"])
    return {
        "note": (
            "units older than 180 days at the as-of date, same pipeline and same "
            "closing step, only the depletion order changed"
        ),
        "applied_method": DEPLETION_METHOD,
        "aged_181_plus_fifo": applied if DEPLETION_METHOD == "FIFO" else None,
        "aged_181_plus_lifo": lifo,
        "spread_ratio": round(lifo / applied, 3) if applied else None,
        "crossing_180_within_7d_lifo": sum(
            lot["quantity"] for lot in lifo_lots if lot["crosses_180_within_7d"]
        ),
    }


def dataset_specs() -> dict[str, dict[str, Any]]:
    specs = dict(V021.dataset_specs())
    specs["fact_inventory_lot"] = {
        "grain": "one row per child ASIN x receipt slice at the as-of date",
        "key": ["lot_id"],
    }
    specs["fact_inventory_age_bucket_asof"] = {
        "grain": "one row per child ASIN at the as-of date",
        "key": ["as_of_date", "child_asin"],
    }
    specs["age_rollforward_audit"] = {
        "grain": "one row per child ASIN",
        "key": ["child_asin"],
    }
    return specs


def build_quality_report(
    datasets: dict[str, list[dict[str, Any]]],
    sqlite_counts: dict[str, int],
    preserved: dict[str, bool],
    sensitivity: dict[str, Any],
) -> dict[str, Any]:
    lots = datasets["fact_inventory_lot.json"]
    rolled = datasets["fact_inventory_age_bucket_asof.json"]
    june = datasets["fact_inventory_age_bucket.json"]
    audit = datasets["age_rollforward_audit.json"]
    inventory = {row["child_asin"]: row for row in datasets["fact_inventory_snapshot.json"]}

    lot_qty_by_child: dict[str, int] = defaultdict(int)
    for lot in lots:
        lot_qty_by_child[lot["child_asin"]] += lot["quantity"]

    tie_failures = [
        row["child_asin"]
        for row in audit
        if row["closing_target_fba_inventory"] is not None
        and lot_qty_by_child[row["child_asin"]] != row["closing_target_fba_inventory"]
    ]
    bucket_failures = [
        row["child_asin"]
        for row in rolled
        if row["total_qty"] != lot_qty_by_child[row["child_asin"]]
    ]
    balance_failures = [
        row["child_asin"]
        for row in audit
        if row["opening_qty_2026_06_30"]
        - row["consumption_applied"]
        + row["implied_arrival_qty"]
        - row["extra_depletion_to_match_snapshot"]
        != row["closing_qty_2026_08_03"]
    ]
    future_lots = [lot["lot_id"] for lot in lots if lot["received_at"] > AS_OF_DATE]
    age_math = [
        lot["lot_id"]
        for lot in lots
        if lot["days_to_180"] != 180 - lot["age_days"]
        or lot["age_bucket"] != bucket_for_age(lot["age_days"])
    ]
    june_total = sum(sum(row[label] for label in BUCKET_LABELS) for row in june)
    rolled_total = sum(row["total_qty"] for row in rolled)
    snapshot_total = sum(row["fba_inventory"] for row in inventory.values())

    crossing_3d = sum(lot["quantity"] for lot in lots if lot["crosses_180_within_3d"])
    crossing_7d = sum(lot["quantity"] for lot in lots if lot["crosses_180_within_7d"])
    children_3d = len({lot["child_asin"] for lot in lots if lot["crosses_180_within_3d"]})
    children_7d = len({lot["child_asin"] for lot in lots if lot["crosses_180_within_7d"]})
    over_180 = sum(lot["quantity"] for lot in lots if lot["already_over_180"])

    checks: list[dict[str, Any]] = []

    def add_check(name: str, expected: Any, actual: Any, passed: bool, severity: str) -> None:
        checks.append(
            {
                "check": name,
                "expected": expected,
                "actual": actual,
                "passed": bool(passed),
                "severity_if_failed": severity,
            }
        )

    for version, ok in preserved.items():
        add_check(f"{version}_preserved", "all file hashes unchanged", ok, ok, "critical")
    add_check("lots_tie_to_fba_inventory", 0, len(tie_failures), not tie_failures, "critical")
    add_check("rolled_buckets_tie_to_lots", 0, len(bucket_failures), not bucket_failures, "critical")
    add_check("rollforward_balance_closes", 0, len(balance_failures), not balance_failures, "critical")
    add_check("no_lot_received_after_as_of", 0, len(future_lots), not future_lots, "critical")
    add_check("lot_age_arithmetic", 0, len(age_math), not age_math, "critical")
    add_check(
        "june_original_unchanged",
        "same field values as v0.2.1",
        june == json.loads((V021_ROOT / "fact_inventory_age_bucket.json").read_text(encoding="utf-8")),
        june == json.loads((V021_ROOT / "fact_inventory_age_bucket.json").read_text(encoding="utf-8")),
        "critical",
    )
    add_check("rolled_total_equals_snapshot_total", snapshot_total, rolled_total, rolled_total == snapshot_total, "high")
    add_check("child_coverage", len(june), len(rolled), len(rolled) == len(june), "high")
    sqlite_mismatches = [
        name
        for name, rows in datasets.items()
        if len(rows) != sqlite_counts.get(name.removesuffix(".json"))
    ]
    add_check("sqlite_json_row_count_match", 0, len(sqlite_mismatches), not sqlite_mismatches, "critical")

    return {
        "dataset_version": DATASET_VERSION,
        "generated_at": BUILD_TIMESTAMP,
        "intended_use": "single-as-of source-fact layer for the product, sales and inventory Demo pages",
        "as_of_date": AS_OF_DATE,
        "age_rollforward": {
            "age_source_date": AGE_SOURCE_DATE,
            "window_days": WINDOW_DAYS,
            "slice_days": SLICE_DAYS,
            "depletion_method": DEPLETION_METHOD,
            "arrival_dating": f"window midpoint {WINDOW_MIDPOINT.isoformat()}",
            "open_bucket_assumed_max_age_days": OPEN_BUCKET_ASSUMED_MAX_AGE,
            "june_units": june_total,
            "rolled_units": rolled_total,
            "snapshot_fba_units": snapshot_total,
            "consumption_applied": sum(row["consumption_applied"] for row in audit),
            "implied_arrivals": sum(row["implied_arrival_qty"] for row in audit),
            "extra_depletion": sum(row["extra_depletion_to_match_snapshot"] for row in audit),
            "consumption_unmet_by_opening": sum(row["consumption_unmet_by_opening"] for row in audit),
            "children_needing_arrivals": sum(1 for row in audit if row["implied_arrival_qty"] > 0),
            "children_needing_extra_depletion": sum(
                1 for row in audit if row["extra_depletion_to_match_snapshot"] > 0
            ),
        },
        "aging_profile_at_as_of": {
            "lot_count": len(lots),
            "units_over_180": over_180,
            "units_crossing_180_within_3d": crossing_3d,
            "units_crossing_180_within_7d": crossing_7d,
            "children_crossing_180_within_3d": children_3d,
            "children_crossing_180_within_7d": children_7d,
            "bucket_totals": {
                label: sum(row[label] for row in rolled) for label in BUCKET_LABELS
            },
        },
        "depletion_sensitivity": sensitivity,
        "record_counts": {name: len(rows) for name, rows in datasets.items()},
        "known_limitations": [
            "lot receipt dates are an assumption: the source states only an age bucket, so quantities are spread uniformly in "
            f"{SLICE_DAYS}-day slices inside each bucket range",
            f"depletion uses {DEPLETION_METHOD} as a visible Demo preset; the depletion_sensitivity block shows the LIFO counterfactual",
            "implied arrival lots are dated at the window midpoint because the source has no child-level receipt date, so the 30天内 bucket at the as-of date is composed entirely of derived arrivals and carries no customer aging fact",
            "the >365 day bucket has no upper bound; date derivation assumes at most "
            f"{OPEN_BUCKET_ASSUMED_MAX_AGE} days and flags the assumption",
            "the June original bucket table is copied through unchanged and must stay the only customer_actual aging figure on screen",
            "child daily sales, forecasts, projections, assessments and risks remain outside the source-fact layer",
        ],
        "checks": checks,
        "all_checks_passed": all(check["passed"] for check in checks),
    }


def write_readme(path: Path, datasets: dict[str, list[dict[str, Any]]], quality: dict[str, Any]) -> None:
    roll = quality["age_rollforward"]
    aging = quality["aging_profile_at_as_of"]
    specs = dataset_specs()
    lines = [
        "# 产品销售库存 Demo 来源事实数据包 v0.2.2",
        "",
        f"生成时间：{BUILD_TIMESTAMP}  ",
        f"统一业务截止日：{AS_OF_DATE}（本版起全部表同一基准日）  ",
        "上一版本：`../v0.2.1`（与 v0.1.0、v0.2.0 一并完整保留）",
        "",
        "## 1. 本版做了什么",
        "",
        f"把 {AGE_SOURCE_DATE} 的库龄档前滚 {roll['window_days']} 天到 {AS_OF_DATE}，"
        "让库龄、库存快照、销量窗口、补货计划、在途事件坐在同一个日子上。",
        "",
        f"- 6 月原表 {roll['june_units']:,} 件 → 前滚后 {roll['rolled_units']:,} 件，"
        f"与 {AS_OF_DATE} 的 FBA 库存合计 {roll['snapshot_fba_units']:,} 件完全一致；",
        f"- 期间按真实滚动窗口消耗 {roll['consumption_applied']:,} 件（{DEPLETION_METHOD}，先耗最老）；",
        f"- 差额补 {roll['implied_arrivals']:,} 件推定到货（{roll['children_needing_arrivals']} 个子体），"
        f"多出的 {roll['extra_depletion']:,} 件继续扣减（{roll['children_needing_extra_depletion']} 个子体）；",
        "- 6 月原值表 `fact_inventory_age_bucket` 原样保留，未被覆盖。",
        "",
        "## 2. 新增表",
        "",
        "| 表 | 记录数 | 粒度 |",
        "| --- | ---: | --- |",
        f"| `fact_inventory_lot` | {len(datasets['fact_inventory_lot.json']):,} | {specs['fact_inventory_lot']['grain']} |",
        f"| `fact_inventory_age_bucket_asof` | {len(datasets['fact_inventory_age_bucket_asof.json']):,} | {specs['fact_inventory_age_bucket_asof']['grain']} |",
        f"| `age_rollforward_audit` | {len(datasets['age_rollforward_audit.json']):,} | {specs['age_rollforward_audit']['grain']} |",
        "",
        "## 3. 前滚后的库龄结果",
        "",
        f"- 超过 180 天：{aging['units_over_180']:,} 件；",
        f"- 未来 3 天内跨 180 天：{aging['units_crossing_180_within_3d']:,} 件，"
        f"涉及 {aging['children_crossing_180_within_3d']} 个子 ASIN；",
        f"- 未来 7 天内跨 180 天：{aging['units_crossing_180_within_7d']:,} 件，"
        f"涉及 {aging['children_crossing_180_within_7d']} 个子 ASIN；",
        f"- 批次行数：{aging['lot_count']:,}。",
        "",
        "各档分布：",
        "",
        "| 库龄档 | 件数 |",
        "| --- | ---: |",
    ]
    for label, value in aging["bucket_totals"].items():
        lines.append(f"| {label} | {value:,} |")
    lines.extend(
        [
            "",
            "## 4. 方法与假设",
            "",
            f"1. 库龄档只给区间不给批次日，所以桶内按 {SLICE_DAYS} 天均匀切片定位收货日，"
            "全部标 `supplemented` / `date_confidence=estimated`；",
            f"2. 消耗量 = 真实 30 天销量 + {roll['window_days'] - 30} 天 ×（31–60 天窗口推出的日均），"
            f"按 {DEPLETION_METHOD} 先耗最老批次；",
            f"3. 与 {AS_OF_DATE} 的 FBA 合计对不上的差额，按推定到货补在窗口中点 "
            f"{WINDOW_MIDPOINT.isoformat()}，或继续扣减，逐个子体在 `age_rollforward_audit` 里记录，不抹平；",
            f"4. `大于365天库龄` 没有上界，定位日期时假设最多 {OPEN_BUCKET_ASSUMED_MAX_AGE} 天并显式标注；",
            "5. 前滚后的库龄档由批次表反算，两张表不可能互相矛盾。",
            "",
            "## 5. 消耗假设的敏感性",
            "",
            f"- {DEPLETION_METHOD}（本版采用，先耗最老）：181+ 剩 {quality['depletion_sensitivity']['aged_181_plus_fifo']:,} 件；",
            f"- LIFO 反事实（先耗最新，同一管道同一收口步骤）：181+ 剩 {quality['depletion_sensitivity']['aged_181_plus_lifo']:,} 件，"
            f"是前者的 {quality['depletion_sensitivity']['spread_ratio']} 倍。",
            "",
            "两者差距就是这条假设对库龄风险结论的影响幅度，页面依据区应当写明当前用的是哪一条。",
            "",
            "## 6. 使用边界",
            "",
            f"- `fact_inventory_age_bucket` 是客户 {AGE_SOURCE_DATE} 原值，是屏幕上唯一可以标成客户事实的库龄数字；",
            "- `fact_inventory_age_bucket_asof` 与 `fact_inventory_lot` 都是派生值，必须标注；",
            "- 到货量仍用 `fact_supply_event.sellable_units`（盒），且该表仍是款号粒度；",
            "- 单位成本币种仍未确认，货值结论暂不成立；",
            "- 子体逐日销量、预测、库存投影、盘点结果和五类风险仍在本层之外。",
            "",
            "## 7. SQLite 示例",
            "",
            "```sql",
            "SELECT child_asin, SUM(quantity) AS qty_crossing_180_in_7d",
            "FROM fact_inventory_lot",
            "WHERE crosses_180_within_7d = 1",
            "GROUP BY child_asin ORDER BY qty_crossing_180_in_7d DESC;",
            "```",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    for label, root in (("v0.1.0", V010_ROOT), ("v0.2.0", V020_ROOT), ("v0.2.1", V021_ROOT)):
        if not root.exists():
            raise RuntimeError(f"{label} 不存在：{root}")
    before = {
        "v0_1_0": V021.directory_hashes(V010_ROOT),
        "v0_2_0": V021.directory_hashes(V020_ROOT),
        "v0_2_1": V021.directory_hashes(V021_ROOT),
    }

    datasets = load_v021_datasets()
    lots, audit = build_lots(
        datasets["fact_inventory_age_bucket.json"],
        datasets["fact_inventory_snapshot.json"],
        datasets["fact_sales_window.json"],
        datasets["fact_unit_economics.json"],
    )
    datasets["fact_inventory_lot.json"] = lots
    datasets["fact_inventory_age_bucket_asof.json"] = build_rolled_buckets(
        lots, datasets["fact_inventory_age_bucket.json"]
    )
    datasets["age_rollforward_audit.json"] = audit
    sensitivity = counterfactual_aged_share(
        lots,
        datasets["fact_inventory_age_bucket.json"],
        datasets["fact_inventory_snapshot.json"],
        datasets["fact_sales_window.json"],
        datasets["fact_unit_economics.json"],
    )

    specs = dataset_specs()
    schema_catalog = {
        "dataset_version": DATASET_VERSION,
        "tables": {
            name.removesuffix(".json"): {
                **specs[name.removesuffix(".json")],
                "record_count": len(rows),
                "fields": list(rows[0]) if rows else [],
            }
            for name, rows in sorted(datasets.items())
        },
    }

    if STAGING_ROOT.exists():
        shutil.rmtree(STAGING_ROOT)
    STAGING_ROOT.mkdir(parents=True)
    sqlite_path = STAGING_ROOT / f"bamboocool_product_sales_inventory_v{DATASET_VERSION}.sqlite"
    sqlite_counts = V021.create_sqlite(sqlite_path, datasets, specs)

    after = {
        "v0_1_0": V021.directory_hashes(V010_ROOT),
        "v0_2_0": V021.directory_hashes(V020_ROOT),
        "v0_2_1": V021.directory_hashes(V021_ROOT),
    }
    preserved = {key: before[key] == after[key] for key in before}
    quality = build_quality_report(datasets, sqlite_counts, preserved, sensitivity)
    if not quality["all_checks_passed"]:
        failed = [check["check"] for check in quality["checks"] if not check["passed"]]
        raise RuntimeError(f"v{DATASET_VERSION} 质量门禁未通过：" + ", ".join(failed))

    hashes: dict[str, str] = {}
    for name, rows in sorted(datasets.items()):
        hashes[name] = V021.write_json(STAGING_ROOT / name, rows)
    hashes["schema_catalog.json"] = V021.write_json(
        STAGING_ROOT / "schema_catalog.json", schema_catalog
    )
    hashes["quality_report.json"] = V021.write_json(
        STAGING_ROOT / "quality_report.json", quality
    )
    for carried in ("source_lineage.json", "source_selection_audit.json"):
        shutil.copy2(V021_ROOT / carried, STAGING_ROOT / carried)
        hashes[carried] = V021.sha256_file(STAGING_ROOT / carried)
    write_readme(STAGING_ROOT / "README.md", datasets, quality)
    hashes["README.md"] = V021.sha256_file(STAGING_ROOT / "README.md")
    hashes[sqlite_path.name] = V021.sha256_file(sqlite_path)

    manifest = {
        "dataset_name": "bamboocool-product-sales-inventory-demo",
        "dataset_version": DATASET_VERSION,
        "generated_at": BUILD_TIMESTAMP,
        "as_of_date": AS_OF_DATE,
        "age_source_date": AGE_SOURCE_DATE,
        "single_as_of": True,
        "previous_version": "../v0.2.1",
        "previous_versions_preserved": preserved,
        "data_nature": "mixed_source_fact_with_explicit_origin",
        "parent_count": len(datasets["dim_product_parent.json"]),
        "child_count": len(datasets["dim_product_child.json"]),
        "files": [
            {
                "name": name,
                "sha256": digest,
                "record_count": len(datasets[name]) if name in datasets else None,
            }
            for name, digest in sorted(hashes.items())
        ],
        "quality_checks_passed": True,
        "next_layer": [
            "supplemented child daily sales",
            "derived demand forecast",
            "derived inventory projection",
            "derived assessment history and five risk types",
        ],
    }
    V021.write_json(STAGING_ROOT / "dataset-manifest.json", manifest)

    if OUTPUT_ROOT.exists():
        shutil.rmtree(OUTPUT_ROOT)
    STAGING_ROOT.rename(OUTPUT_ROOT)
    print(
        json.dumps(
            {
                "output": str(OUTPUT_ROOT),
                "lots": len(lots),
                "june_units": quality["age_rollforward"]["june_units"],
                "rolled_units": quality["age_rollforward"]["rolled_units"],
                "snapshot_fba_units": quality["age_rollforward"]["snapshot_fba_units"],
                "units_over_180": quality["aging_profile_at_as_of"]["units_over_180"],
                "units_crossing_180_within_7d": quality["aging_profile_at_as_of"][
                    "units_crossing_180_within_7d"
                ],
                "quality_checks": len(quality["checks"]),
                "all_checks_passed": quality["all_checks_passed"],
                "previous_versions_preserved": preserved,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
