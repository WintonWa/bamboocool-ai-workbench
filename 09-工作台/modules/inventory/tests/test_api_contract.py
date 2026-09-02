"""Structural check: every field the front-end reads must exist in the API payload.

This is not a substitute for looking at the rendered page, but it catches the
most likely failure -- a key name that does not exist -- without a browser.
"""
import json
import re
import sys
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:18820"
# app.js 拆成了入口 + 三个页面 + 共用件，拼起来一起查
_WEB = Path(__file__).resolve().parent.parent.parent.parent / "web"
JS = "\n".join(
    p.read_text()
    for p in [_WEB / "modules/inventory.js", *sorted((_WEB / "modules/inventory").glob("*.js"))]
)


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=20) as r:
        return json.loads(r.read())


meta = get("/api/inventory/meta")
children = get("/api/inventory/children?limit=5")
detail = get("/api/inventory/child/" + children["rows"][0]["child_asin"])

failures = []


def check(label, obj, dotted):
    cur = obj
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            failures.append(f"{label}: 缺 {dotted}")
            return
    return cur


# paths the detail renderer walks
for path in [
    "identity.child_asin", "identity.parent_asin", "identity.product_name", "identity.style_no",
    "identity.combination", "identity.colorway", "identity.size", "identity.operator",
    "identity.goods_status", "identity.product_lifecycle", "identity.category", "identity.sku",
    "identity.fnsku", "identity.store", "identity.category_rank", "identity.rating",
    "identity.attribute_quality",
    "windows.units_30d",
    "windows.daily_avg_30d",
    "demand.available",
    "demand.forecast_daily",
    "demand.forecast_90d",
    "demand.horizon_effective_days",
    "demand.run.as_of_date",
    "demand.run.model_label",
    "demand.run.model_wape",
    "demand.run.validation_days",
    "projection.arrivals",
    "projection.confirmed_arrival_qty",
    "projection.planned_arrival_qty",
    "demand.confidence_label",
    "demand.factors",
    "chart.available",
    "chart.dates",
    "chart.weekdays",
    "chart.actual",
    "chart.forecast",
    "chart.bands",
    "chart.lanes",
    "chart.lines",
    "chart.lane_axis_max",
    "chart.as_of_index",
    "chart.timezone_label",
    "projection.scopes.sellable_plus_confirmed.stockout_date_range.earliest",
    "projection.scopes.sellable_plus_confirmed.stockout_date_range.base",
    "projection.scopes.sellable_plus_confirmed.stockout_date_range.latest",
    "inventory.available", "inventory.sellable_qty", "inventory.restricted_qty",
    "inventory.availability_rate", "inventory.total_known_qty", "inventory.inbound_qty",
    "projection.available", "projection.safety_days", "projection.safety_days_origin",
    "projection.excess_qty", "projection.depletion_days", "projection.reasonable_max_qty",
    "projection.inbound_note",
    "projection.scopes.sellable_only.cover_days",
    "projection.scopes.sellable_plus_confirmed.cover_days",
    "projection.scopes.sellable_plus_confirmed.stockout_date",
    "projection.scopes.sellable_plus_confirmed.safety_breach_date",
    "projection.scopes.sellable_plus_confirmed.shortage_30d",
    "projection.scopes.sellable_plus_confirmed.shortage_90d",
    "projection.scopes.sellable_plus_confirmed.safety_stock_qty",
    "aging.aged_181_qty", "aging.aged_181_share", "aging.crossing_180_within_3d",
    "aging.crossing_180_within_7d", "aging.lot_count", "aging.assumption",
    "aging.rollforward.opening_qty_2026_06_30", "aging.rollforward.consumption_applied",
    "aging.rollforward.implied_arrival_qty", "aging.rollforward.closing_qty_2026_08_03",
    "aging.rollforward.balance_residual", "aging.rollforward.extra_depletion_to_match_snapshot",
    "fee.available", "capacity.level", "capacity.note",
    "customer_plan.expected_stockout_date", "customer_plan.suggested_purchase_qty",
    "customer_plan.suggested_purchase_date", "customer_plan.daily_sales_rate",
    "economics.unit_cost", "economics.unit_cost_origin", "economics.pack_size",
    "economics.unit_cost_currency_status",
    "monthly.units_sold", "monthly.net_sales", "monthly.order_gross_profit", "monthly.order_gross_margin",
    "rule_version", "as_of_date",
]:
    check("detail", detail, path)

for path in ["data.dataset_version", "data.as_of_date", "data.age_source_date",
             "data.age_rollforward.window_days", "data.depletion_sensitivity.applied_method",
             "data.depletion_sensitivity.aged_181_plus_fifo", "data.depletion_sensitivity.aged_181_plus_lifo",
             "data.depletion_sensitivity.spread_ratio", "data.known_limitations",
             "rule_version", "parameters", "filter_options", "risk_labels"]:
    check("meta", meta, path)

for path in ["total", "matched", "overview.risk_child_count", "overview.by_risk_type",
             "overview.severity", "overview.multi_risk_children", "overview.no_risk_children",
             "overview.capacity", "overview.confidence", "scope.child_count", "scope.availability_rate",
             "scope.aged_181_share", "scope.cover_days_median", "scope.cover_days_note",
             "scope.by_risk_type", "rows"]:
    check("children", children, path)

for key in ["child_asin", "style_no", "combination", "size", "cover_days", "units_30d",
            "sellable_qty", "primary_severity", "risk_count", "risk_types", "risk_qty",
            "capacity_level", "confidence", "aged_181_qty", "fee_total", "excess_qty"]:
    if key not in children["rows"][0]:
        failures.append(f"children row: 缺 {key}")

# every list row must be openable
opened = 0
for row in children["rows"]:
    d = get("/api/inventory/child/" + row["child_asin"])
    if "error" in d:
        failures.append(f"detail {row['child_asin']}: {d['error']}")
    else:
        opened += 1

# lot arrays must be present for the batch table
if not isinstance(detail["aging"].get("lots"), list):
    failures.append("detail: aging.lots 不是数组")
if not isinstance(detail.get("style_events"), list):
    failures.append("detail: style_events 不是数组")
if not isinstance(detail.get("parent_daily"), list):
    failures.append("detail: parent_daily 不是数组")

# params referenced by the panel
missing_group = [p["key"] for p in meta["parameters"] if "group" not in p]
if missing_group:
    failures.append(f"meta.parameters 缺 group: {missing_group}")

print(f"打开详情成功 {opened}/{len(children['rows'])}")
print(f"detail 字段路径检查 {len(failures)} 处问题")
for f in failures:
    print("  ✗", f)
print("PASS" if not failures else "FAIL")
sys.exit(1 if failures else 0)
