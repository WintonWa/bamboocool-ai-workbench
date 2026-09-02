"""Read-only access to the v0.2.2 source-fact package.

This module does no business calculation. It only fetches customer facts and the
data-layer derivations that already carry their own provenance. Everything that
depends on a rule parameter lives in ``compute.py`` so it can be recalculated on
every request.
"""

from __future__ import annotations

import json
import sqlite3
from functools import lru_cache
from typing import Any

from core import db as _db
from core import paths

# 路径由外壳集中声明并支持环境变量覆盖（契约 6.1），模块不写死绝对路径。
DB_PATH = paths.PRODUCT_DB
DATA_ROOT = DB_PATH.parent

# v0.3.0 声明 source_version 0.2.2，库龄批次与前滚审计是原样继承的。
# 它自己的 quality_report 换成了扁平检查表，不再带页面要渲染的四个汇总块，
# 所以那几块从它声明的来源包读 —— 事实没变，只是位置变了。
SOURCE_ROOT = DATA_ROOT.parent / "v0.2.2"

AGE_BUCKET_COLUMNS = [
    "30天内库龄",
    "31-60天库龄",
    "61-90天库龄",
    "91-180天库龄",
    "181-270天库龄",
    "271-330天库龄",
    "331-365天库龄",
    "大于365天库龄",
]


# connect / rows / one 转调外壳的公共只读访问层。签名保持原样（不显式传 con 的
# connect、显式传 con 的 rows/one），这样 compute.py 与 forecast.py 一个字都不用改。
# 外壳版额外加了 PRAGMA query_only，比原来更严，不影响只读用法。
def connect() -> sqlite3.Connection:
    return _db.connect(DB_PATH)


def rows(con: sqlite3.Connection, sql: str, args: tuple = ()) -> list[dict[str, Any]]:
    return _db.rows(con, sql, args)


def one(con: sqlite3.Connection, sql: str, args: tuple = ()) -> dict[str, Any] | None:
    return _db.one(con, sql, args)


def clear_caches() -> None:
    """热重载时清掉进程内缓存（module.py 的 invalidate 钩子）。

    不清的话改了 .py 之后新代码读的还是旧快照，看起来像"改了没生效"。
    """
    for fn in (meta, _facts_cache, filter_options):
        try:
            fn.cache_clear()
        except AttributeError:
            pass


@lru_cache(maxsize=1)
def meta() -> dict[str, Any]:
    manifest = json.loads((DATA_ROOT / "dataset-manifest.json").read_text(encoding="utf-8"))
    quality = json.loads((DATA_ROOT / "quality_report.json").read_text(encoding="utf-8"))
    inherited: dict[str, Any] = {}
    src_q = SOURCE_ROOT / "quality_report.json"
    if src_q.is_file():
        inherited = json.loads(src_q.read_text(encoding="utf-8"))
    for key in ("age_rollforward", "aging_profile_at_as_of", "depletion_sensitivity",
                "known_limitations"):
        if key not in quality and key in inherited:
            quality[key] = inherited[key]
    src_m = SOURCE_ROOT / "dataset-manifest.json"
    if src_m.is_file():
        src_manifest = json.loads(src_m.read_text(encoding="utf-8"))
        for key in ("age_source_date", "single_as_of", "parent_count"):
            manifest.setdefault(key, src_manifest.get(key))
    return {
        "dataset_version": manifest["dataset_version"],
        "as_of_date": manifest["as_of_date"],
        "age_source_date": manifest.get("age_source_date"),
        "single_as_of": manifest.get("single_as_of", False),
        "parent_count": manifest.get("parent_count"),
        "child_count": manifest.get("child_count"),
        "generated_at": manifest["generated_at"],
        "age_rollforward": quality["age_rollforward"],
        "depletion_sensitivity": quality["depletion_sensitivity"],
        "known_limitations": quality["known_limitations"],
        "aging_profile": quality["aging_profile_at_as_of"],
    }


@lru_cache(maxsize=1)
def _facts_cache() -> dict[str, Any]:
    """Load the per-child fact tables once. All of them are <= 342 rows."""
    con = connect()
    try:
        by_child: dict[str, dict[str, Any]] = {}

        def merge(table: str, key: str, prefix: str) -> None:
            for row in rows(con, f"SELECT * FROM {table}"):
                child = row[key]
                by_child.setdefault(child, {})[prefix] = row

        merge("dim_product_child", "child_asin", "child")
        merge("dim_product_attribute", "child_asin", "attr")
        merge("bridge_product_identifier", "child_asin", "ident")
        merge("fact_inventory_snapshot", "child_asin", "inv")
        merge("fact_sales_window", "child_asin", "win")
        merge("fact_supply_plan", "child_asin", "plan")
        merge("fact_child_sales_monthly", "child_asin", "month")
        merge("fact_unit_economics", "child_asin", "econ")
        merge("fact_inventory_age_bucket_asof", "child_asin", "age")
        merge("fact_inventory_age_bucket", "child_asin", "age_june")
        merge("age_rollforward_audit", "child_asin", "roll")
        merge("missing_field_matrix", "child_asin", "missing")

        parents = {r["parent_asin"]: r for r in rows(con, "SELECT * FROM dim_product_parent")}

        lots_by_child: dict[str, list[dict[str, Any]]] = {}
        for row in rows(
            con,
            "SELECT * FROM fact_inventory_lot ORDER BY child_asin, received_at",
        ):
            lots_by_child.setdefault(row["child_asin"], []).append(row)

        events_by_style: dict[str, list[dict[str, Any]]] = {}
        for row in rows(con, "SELECT * FROM fact_supply_event ORDER BY style_no, created_at"):
            row["matched_parent_asins"] = json.loads(row["matched_parent_asins"] or "[]")
            events_by_style.setdefault(row["style_no"], []).append(row)

        parent_daily_days: dict[str, int] = {}
        for row in rows(
            con,
            "SELECT parent_asin, COUNT(*) AS days, MIN(date) AS first_date, MAX(date) AS last_date "
            "FROM fact_parent_sales_daily WHERE units_sold IS NOT NULL GROUP BY parent_asin",
        ):
            parent_daily_days[row["parent_asin"]] = row

        style_monthly: dict[str, list[dict[str, Any]]] = {}
        for row in rows(con, "SELECT * FROM fact_style_monthly_attribute ORDER BY style_no, period"):
            style_monthly.setdefault(row["style_no"], []).append(row)

        return {
            "by_child": by_child,
            "parents": parents,
            "lots": lots_by_child,
            "events": events_by_style,
            "parent_daily": parent_daily_days,
            "style_monthly": style_monthly,
        }
    finally:
        con.close()


def all_children() -> list[str]:
    return sorted(_facts_cache()["by_child"])


def child_facts(asin: str) -> dict[str, Any] | None:
    cache = _facts_cache()
    facts = cache["by_child"].get(asin)
    if not facts:
        return None
    style = (facts.get("attr") or {}).get("style_no")
    parent = (facts.get("child") or {}).get("parent_asin")
    out = dict(facts)
    out["parent"] = cache["parents"].get(parent)
    out["lots"] = cache["lots"].get(asin, [])
    out["style_events"] = cache["events"].get(style, [])
    out["parent_daily_span"] = cache["parent_daily"].get(parent)
    out["style_monthly"] = cache["style_monthly"].get(style, [])
    return out


def parent_daily_series(parent_asin: str, days: int = 180) -> list[dict[str, Any]]:
    con = connect()
    try:
        series = rows(
            con,
            "SELECT date, units_sold, sales_amount FROM fact_parent_sales_daily "
            "WHERE parent_asin = ? AND units_sold IS NOT NULL ORDER BY date DESC LIMIT ?",
            (parent_asin, days),
        )
        return list(reversed(series))
    finally:
        con.close()


def parent_inventory_series(parent_asin: str, days: int = 180) -> list[dict[str, Any]]:
    con = connect()
    try:
        series = rows(
            con,
            "SELECT date, fba_sellable, available_inventory, fba_inbound "
            "FROM fact_parent_inventory_daily WHERE parent_asin = ? "
            "ORDER BY date DESC LIMIT ?",
            (parent_asin, days),
        )
        return list(reversed(series))
    finally:
        con.close()


@lru_cache(maxsize=1)
def filter_options() -> dict[str, list[str]]:
    """Distinct values for the 库存全览 filters. All real, no invented dimensions."""
    con = connect()
    try:
        out: dict[str, list[str]] = {}
        pairs = [
            ("style_no", "dim_product_attribute"),
            ("combination", "dim_product_attribute"),
            ("colorway", "dim_product_attribute"),
            ("size", "dim_product_attribute"),
            ("operator", "dim_product_attribute"),
            ("goods_status", "dim_product_attribute"),
            ("category", "dim_product_attribute"),
            ("product_lifecycle", "dim_product_attribute"),
        ]
        for column, table in pairs:
            values = [
                r[column]
                for r in rows(
                    con,
                    f"SELECT DISTINCT {column} FROM {table} "
                    f"WHERE {column} IS NOT NULL AND {column} != '' ORDER BY {column}",
                )
            ]
            out[column] = values
        out["store"] = [
            r["store"]
            for r in rows(
                con,
                "SELECT DISTINCT store FROM bridge_product_identifier "
                "WHERE store IS NOT NULL ORDER BY store",
            )
        ]
        out["parent_asin"] = [
            r["parent_asin"]
            for r in rows(con, "SELECT parent_asin FROM dim_product_parent ORDER BY parent_asin")
        ]
        return out
    finally:
        con.close()
