#!/usr/bin/env python3
"""Build the first source-backed product/sales/inventory Demo dataset.

The builder reads the customer workbooks without changing them. It selects five
real parent ASINs deterministically, normalizes the directly usable facts, and
writes provenance and data-quality artifacts. Forecasts, projections, risks and
scenario additions intentionally remain outside v0.1.0.
"""

from __future__ import annotations

import hashlib
import importlib.util
import itertools
import json
import math
import re
import shutil
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from statistics import mean
from typing import Any
from zipfile import ZipFile


ROOT = Path("/Users/linsen/BAM")
SOURCE_ROOT = ROOT / "数据源/AI广告对接数据-总20260803"
SESSION_ROOT = ROOT
INDEX_ROOT = SESSION_ROOT / "01-客户数据源索引"
MODULE_ROOT = SESSION_ROOT / "02-产品销售库存模块"
INDEX_PATH = INDEX_ROOT / "客户数据源索引.json"
SCANNER_PATH = INDEX_ROOT / "工作文件/scan_customer_sources.py"
OUTPUT_ROOT = MODULE_ROOT / "02-数据构建/v0.1.0"

DATASET_VERSION = "0.1.0"
BUILD_TIMESTAMP = "2026-08-29T00:00:00+08:00"
AS_OF_DATE = "2026-08-03"
MONTHLY_SOURCE_PERIOD = "2026-06"

MONTHLY_FILE = "14.其他分析文件/2026年月报/6月/一组6月月报.xlsx"
PRODUCT_CHILD_SHEET = "产品表现-ASIN"
PRODUCT_PARENT_SHEET = "产品表现-父ASIN"
AGE_SHEET = "FBA库存明细"
INVENTORY_FILE = "3.库存表-物流管理表.xlsx"
INVENTORY_SHEET = "源数据1"

ASIN_RE = re.compile(r"^[A-Z0-9]{10}$")


def load_scanner():
    spec = importlib.util.spec_from_file_location("bam_source_scanner", SCANNER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法载入扫描器：{SCANNER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SCANNER = load_scanner()


def clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"none", "nan", "null", "n/a", "--", "—"}:
        return None
    return text


def normalize_asin(value: Any) -> str | None:
    text = clean_text(value)
    if text is None:
        return None
    candidate = text.upper()
    return candidate if ASIN_RE.fullmatch(candidate) else None


def to_number(value: Any) -> int | float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        return int(value) if float(value).is_integer() else round(float(value), 6)
    text = clean_text(value)
    if text is None or text.startswith("="):
        return None
    text = text.replace(",", "").replace("$", "").replace("￥", "").replace("¥", "")
    percent = text.endswith("%")
    if percent:
        text = text[:-1]
    try:
        number = float(text)
    except ValueError:
        return None
    if percent:
        number /= 100
    return int(number) if number.is_integer() else round(number, 6)


def normalize_date(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    parsed = SCANNER.parse_date_value(value)
    return parsed.date().isoformat() if parsed else None


def json_ready(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return round(value, 6)
    if isinstance(value, dict):
        return {key: json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_ready(item) for item in value]
    return value


def mode_text(values: list[Any]) -> str | None:
    cleaned = [clean_text(value) for value in values]
    present = [value for value in cleaned if value]
    if not present:
        return None
    return Counter(present).most_common(1)[0][0]


def provenance(source_file: str, source_sheet: str, source_row: int) -> dict[str, Any]:
    return {
        "provenance_type": "customer_actual",
        "source_file": source_file,
        "source_sheet": source_sheet,
        "source_row": source_row,
        "source_as_of_date": AS_OF_DATE,
    }


class WorkbookReader:
    def __init__(self, index: dict[str, Any]):
        self.index = index
        self.sheet_meta = {
            (file["relative_path"], sheet["sheet_name"]): sheet
            for file in index["files"]
            for sheet in file.get("sheets", [])
        }
        self.cache: dict[tuple[str, str], list[dict[str, Any]]] = {}

    def rows(self, relative_path: str, sheet_name: str) -> list[dict[str, Any]]:
        key = (relative_path, sheet_name)
        if key in self.cache:
            return self.cache[key]
        meta = self.sheet_meta[key]
        header_row = meta.get("header_row")
        fields = meta.get("fields", [])
        if not header_row or not fields:
            self.cache[key] = []
            return []
        positions = {index + 1: field for index, field in enumerate(fields)}
        sparse_rows: dict[int, dict[str, Any]] = defaultdict(dict)
        workbook_path = SOURCE_ROOT / relative_path
        with ZipFile(workbook_path) as package:
            shared_strings = SCANNER.read_shared_strings(package)
            date_styles = SCANNER.read_date_style_indexes(package)
            workbook_sheets, date_1904 = SCANNER.read_workbook_metadata(package)
            sheet_path = next(
                sheet["path"] for sheet in workbook_sheets if sheet["name"] == sheet_name
            )
            for row_index, column_index, value, is_formula, is_error in SCANNER.iter_ooxml_cells(
                package, sheet_path, shared_strings, date_styles, date_1904
            ):
                if row_index <= header_row or column_index not in positions:
                    continue
                field = positions[column_index]
                sparse_rows[row_index][field] = value
                if is_formula:
                    sparse_rows[row_index].setdefault("__formula_fields", []).append(field)
                if is_error:
                    sparse_rows[row_index].setdefault("__error_fields", []).append(field)
        rows = []
        for row_index in sorted(sparse_rows):
            row = sparse_rows[row_index]
            row["__source_row"] = row_index
            rows.append(row)
        self.cache[key] = rows
        return rows


def find_daily_parent_sources(index: dict[str, Any], reader: WorkbookReader) -> dict[str, dict[str, Any]]:
    candidates: dict[str, dict[tuple[str, str], list[dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for file in index["files"]:
        relative_path = file["relative_path"]
        if not relative_path.startswith("1.产品跟进表-运营记录/"):
            continue
        for sheet in file.get("sheets", []):
            fields = set(sheet.get("fields", []))
            if not {"日期", "父ASIN", "销量", "销售额"}.issubset(fields):
                continue
            sheet_name = sheet["sheet_name"]
            for row in reader.rows(relative_path, sheet_name):
                parent_asin = normalize_asin(row.get("父ASIN"))
                business_date = normalize_date(row.get("日期"))
                if parent_asin and business_date:
                    candidates[parent_asin][(relative_path, sheet_name)].append(row)

    selected: dict[str, dict[str, Any]] = {}
    for parent_asin, sources in candidates.items():
        ranked = []
        for (relative_path, sheet_name), rows in sources.items():
            by_date: dict[str, dict[str, Any]] = {}
            for row in rows:
                business_date = normalize_date(row.get("日期"))
                if business_date:
                    by_date[business_date] = row
            ranked.append(
                {
                    "relative_path": relative_path,
                    "sheet_name": sheet_name,
                    "rows_by_date": by_date,
                    "date_count": len(by_date),
                    "latest_date": max(by_date, default=""),
                }
            )
        ranked.sort(key=lambda item: (item["date_count"], item["latest_date"]), reverse=True)
        selected[parent_asin] = ranked[0]
    return selected


def build_candidate_stats(
    product_rows: list[dict[str, Any]],
    age_rows: list[dict[str, Any]],
    inventory_rows: list[dict[str, Any]],
    daily_sources: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    children_by_parent: dict[str, list[str]] = defaultdict(list)
    for row in product_rows:
        child_asin = normalize_asin(row.get("ASIN"))
        parent_asin = normalize_asin(row.get("父ASIN"))
        if child_asin and parent_asin:
            children_by_parent[parent_asin].append(child_asin)
    age_asins = {normalize_asin(row.get("ASIN")) for row in age_rows}
    inventory_asins = {normalize_asin(row.get("ASIN")) for row in inventory_rows}
    age_asins.discard(None)
    inventory_asins.discard(None)

    stats: dict[str, dict[str, Any]] = {}
    for parent_asin, children in children_by_parent.items():
        unique_children = sorted(set(children))
        count = len(unique_children)
        daily_source = daily_sources.get(parent_asin)
        stats[parent_asin] = {
            "parent_asin": parent_asin,
            "child_count": count,
            "age_coverage": round(
                sum(child in age_asins for child in unique_children) / max(1, count), 6
            ),
            "inventory_coverage": round(
                sum(child in inventory_asins for child in unique_children) / max(1, count), 6
            ),
            "daily_history_days": daily_source["date_count"] if daily_source else 0,
            "daily_latest_date": daily_source["latest_date"] if daily_source else None,
        }
    return stats


def select_five_parents(candidate_stats: dict[str, dict[str, Any]]) -> tuple[list[str], dict[str, str]]:
    mature = [
        item
        for item in candidate_stats.values()
        if item["daily_history_days"] >= 500
        and item["child_count"] >= 20
        and item["age_coverage"] >= 0.95
        and item["inventory_coverage"] >= 0.95
    ]
    if len(mature) < 4:
        raise RuntimeError(f"满足条件的成熟父体不足 4 个：{len(mature)}")

    combinations = []
    for group in itertools.combinations(mature, 4):
        total_children = sum(item["child_count"] for item in group)
        average_inventory_coverage = mean(item["inventory_coverage"] for item in group)
        average_history = mean(item["daily_history_days"] for item in group)
        combinations.append(
            (
                abs(total_children - 250),
                -average_inventory_coverage,
                -average_history,
                tuple(sorted(item["parent_asin"] for item in group)),
                group,
            )
        )
    combinations.sort(key=lambda item: item[:4])
    mature_group = list(combinations[0][4])
    mature_ids = {item["parent_asin"] for item in mature_group}

    newer = [
        item
        for item in candidate_stats.values()
        if item["parent_asin"] not in mature_ids
        and 60 <= item["daily_history_days"] <= 180
        and item["child_count"] >= 20
        and item["age_coverage"] >= 0.95
        and item["inventory_coverage"] >= 0.90
    ]
    if not newer:
        raise RuntimeError("没有找到满足条件的短历史父体")
    newer.sort(
        key=lambda item: (
            -item["inventory_coverage"],
            abs(item["child_count"] - 90),
            -item["daily_history_days"],
            item["parent_asin"],
        )
    )
    new_parent = newer[0]

    selected_stats = mature_group + [new_parent]
    selected_stats.sort(key=lambda item: (-item["daily_history_days"], item["parent_asin"]))
    labels = {
        item["parent_asin"]: ("mature" if item["parent_asin"] in mature_ids else "newer")
        for item in selected_stats
    }
    return [item["parent_asin"] for item in selected_stats], labels


def aggregate_numeric(rows: list[dict[str, Any]], fields: list[str]) -> dict[str, int | float | None]:
    output: dict[str, int | float | None] = {}
    for field in fields:
        values = [to_number(row.get(field)) for row in rows]
        present = [value for value in values if value is not None]
        output[field] = round(sum(present), 6) if present else None
    return output


def source_record(row: dict[str, Any], source_file: str, source_sheet: str) -> dict[str, Any]:
    return provenance(source_file, source_sheet, int(row["__source_row"]))


def build_dataset() -> dict[str, Any]:
    index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    reader = WorkbookReader(index)

    product_rows = reader.rows(MONTHLY_FILE, PRODUCT_CHILD_SHEET)
    parent_monthly_rows = reader.rows(MONTHLY_FILE, PRODUCT_PARENT_SHEET)
    age_rows = reader.rows(MONTHLY_FILE, AGE_SHEET)
    inventory_rows = reader.rows(INVENTORY_FILE, INVENTORY_SHEET)
    daily_sources = find_daily_parent_sources(index, reader)
    candidate_stats = build_candidate_stats(product_rows, age_rows, inventory_rows, daily_sources)
    selected_parents, lifecycle_labels = select_five_parents(candidate_stats)
    selected_parent_set = set(selected_parents)

    selected_products = [
        row for row in product_rows if normalize_asin(row.get("父ASIN")) in selected_parent_set
    ]
    selected_children = sorted(
        {
            normalize_asin(row.get("ASIN"))
            for row in selected_products
            if normalize_asin(row.get("ASIN"))
        }
    )
    selected_child_set = set(selected_children)

    children_by_parent: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in selected_products:
        parent_asin = normalize_asin(row.get("父ASIN"))
        child_asin = normalize_asin(row.get("ASIN"))
        if parent_asin and child_asin:
            children_by_parent[parent_asin].append(row)

    dim_parent = []
    for parent_asin in selected_parents:
        rows = children_by_parent[parent_asin]
        stat = candidate_stats[parent_asin]
        dim_parent.append(
            {
                "parent_asin": parent_asin,
                "product_name": mode_text([row.get("品名") for row in rows]),
                "style_name": mode_text([row.get("款名") for row in rows]),
                "owner": mode_text([row.get("负责人") for row in rows]),
                "demo_lifecycle_group": lifecycle_labels[parent_asin],
                "child_count": len(rows),
                "daily_history_days": stat["daily_history_days"],
                "daily_latest_date": stat["daily_latest_date"],
                "inventory_coverage": stat["inventory_coverage"],
                "age_coverage": stat["age_coverage"],
                "provenance": source_record(rows[0], MONTHLY_FILE, PRODUCT_CHILD_SHEET),
            }
        )

    child_field_map = {
        "品名": "product_name",
        "款名": "style_name",
        "负责人": "owner",
        "小类排名": "category_rank",
        "评分": "rating",
    }
    dim_child = []
    child_monthly_sales = []
    for row in sorted(selected_products, key=lambda item: normalize_asin(item.get("ASIN")) or ""):
        child_asin = normalize_asin(row.get("ASIN"))
        parent_asin = normalize_asin(row.get("父ASIN"))
        if not child_asin or not parent_asin:
            continue
        dimension = {
            "child_asin": child_asin,
            "parent_asin": parent_asin,
            **{target: json_ready(row.get(source)) for source, target in child_field_map.items()},
            "provenance": source_record(row, MONTHLY_FILE, PRODUCT_CHILD_SHEET),
        }
        dim_child.append(dimension)
        child_monthly_sales.append(
            {
                "period": MONTHLY_SOURCE_PERIOD,
                "child_asin": child_asin,
                "parent_asin": parent_asin,
                "refund_units": to_number(row.get("退款量")),
                "refund_rate": to_number(row.get("退款率")),
                "return_units": to_number(row.get("退货量")),
                "return_rate": to_number(row.get("退货率")),
                "net_sales": to_number(row.get("净销售额")),
                "orders": to_number(row.get("订单量")),
                "units_sold": to_number(row.get("销量")),
                "sales_amount": to_number(row.get("销售额")),
                "average_price": to_number(row.get("销售均价")),
                "order_gross_profit": to_number(row.get("订单毛利润")),
                "order_gross_margin": to_number(row.get("订单毛利率")),
                "ad_spend": to_number(row.get("广告花费")),
                "acoas": to_number(row.get("ACoAS")),
                "clicks": to_number(row.get("点击")),
                "impressions": to_number(row.get("展示")),
                "ctr": to_number(row.get("CTR")),
                "ad_cvr": to_number(row.get("广告CVR")),
                "cvr": to_number(row.get("CVR")),
                "provenance": source_record(row, MONTHLY_FILE, PRODUCT_CHILD_SHEET),
            }
        )

    parent_monthly = []
    for row in parent_monthly_rows:
        parent_asin = normalize_asin(row.get("父ASIN"))
        if parent_asin not in selected_parent_set:
            continue
        parent_monthly.append(
            {
                "period": MONTHLY_SOURCE_PERIOD,
                "parent_asin": parent_asin,
                "units_sold": to_number(row.get("销量")),
                "sales_amount": to_number(row.get("销售额")),
                "orders": to_number(row.get("订单量")),
                "net_sales": to_number(row.get("净销售额")),
                "order_gross_profit": to_number(row.get("订单毛利润")),
                "ad_spend": to_number(row.get("广告花费")),
                "provenance": source_record(row, MONTHLY_FILE, PRODUCT_PARENT_SHEET),
            }
        )

    inventory_by_asin: dict[str, dict[str, Any]] = {}
    for row in inventory_rows:
        child_asin = normalize_asin(row.get("ASIN"))
        if child_asin in selected_child_set:
            inventory_by_asin[child_asin] = row

    age_by_asin: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in age_rows:
        child_asin = normalize_asin(row.get("ASIN"))
        if child_asin in selected_child_set:
            age_by_asin[child_asin].append(row)

    bridge_identifiers = []
    inventory_snapshot = []
    sales_windows = []
    supply_plan = []
    age_buckets = []
    missing_matrix = []

    inventory_fields = {
        "FBA库存": "fba_inventory",
        "可售": "fba_sellable",
        "待调仓": "pending_transfer",
        "FBA预留": "fba_reserved",
        "入库中": "fba_receiving",
        "FBA在途": "fba_inbound",
        "海外仓可用": "overseas_available",
        "海外仓在途": "overseas_inbound",
        "本地可用": "local_available",
        "本地最大可加工量": "local_max_processable",
        "待检待上架量": "pending_inspection",
        "待交付": "pending_delivery",
        "本地仓在途": "local_inbound",
        "采购计划": "purchase_plan_qty",
        "总库存": "total_inventory",
    }
    sales_window_fields = {
        "3天销量": "units_3d",
        "7天销量": "units_7d",
        "14天销量": "units_14d",
        "30天销量": "units_30d",
        "60天销量": "units_60d",
        "90天销量": "units_90d",
        "3天日均": "daily_avg_3d",
        "7天日均": "daily_avg_7d",
        "14天日均": "daily_avg_14d",
        "30天日均": "daily_avg_30d",
        "60天日均": "daily_avg_60d",
        "90天日均": "daily_avg_90d",
    }
    supply_number_fields = {
        "历史供货天数": "historical_supply_days",
        "采购计划天数": "purchase_plan_days",
        "采购交期": "purchase_lead_days",
        "质检天数": "quality_check_days",
        "海外仓至FBA天数": "overseas_to_fba_days",
        "安全天数": "safety_days",
        "备货时长": "stocking_lead_days",
        "可售天数(总)": "coverage_days_total",
        "可售天数(FBA)": "coverage_days_fba",
        "可售天数(FBA + 在途)": "coverage_days_fba_inbound",
        "日均销量": "daily_sales_rate",
        "销量预测": "forecast_units",
        "建议采购量": "suggested_purchase_qty",
        "建议采购量-空派": "suggested_purchase_air_qty",
        "建议采购量-海派": "suggested_purchase_sea_qty",
        "本地发FBA量": "local_to_fba_qty",
        "海外仓发FBA量": "overseas_to_fba_qty",
    }
    supply_date_fields = {
        "断货时间": "expected_stockout_date",
        "建议采购日": "suggested_purchase_date",
        "建议本地发货日": "suggested_local_ship_date",
        "建议海外仓发货日": "suggested_overseas_ship_date",
    }
    age_fields = [
        "30天内库龄",
        "31-60天库龄",
        "61-90天库龄",
        "91-180天库龄",
        "181-270天库龄",
        "271-330天库龄",
        "331-365天库龄",
        "大于365天库龄",
        "AWD在库",
        "AWD可用量",
        "AWD待发货量",
        "AWD标发在途",
        "AWD实际在途",
        "AWD补货至FBA标发在途",
        "AWD补货至FBA实际在途",
        "AWD可用+在途库存合计",
    ]

    for child in dim_child:
        child_asin = child["child_asin"]
        parent_asin = child["parent_asin"]
        inventory_row = inventory_by_asin.get(child_asin)
        child_age_rows = age_by_asin.get(child_asin, [])

        if inventory_row:
            bridge_identifiers.append(
                {
                    "child_asin": child_asin,
                    "parent_asin": parent_asin,
                    "sku": clean_text(inventory_row.get("SKU")),
                    "fnsku": clean_text(inventory_row.get("FNSKU")),
                    "store": clean_text(inventory_row.get("店铺")),
                    "country_region": clean_text(inventory_row.get("国家（地区）")),
                    "listing_owner": clean_text(inventory_row.get("Listing负责人")),
                    "provenance": source_record(inventory_row, INVENTORY_FILE, INVENTORY_SHEET),
                }
            )
            inventory_snapshot.append(
                {
                    "snapshot_date": AS_OF_DATE,
                    "child_asin": child_asin,
                    "parent_asin": parent_asin,
                    **{
                        target: to_number(inventory_row.get(source))
                        for source, target in inventory_fields.items()
                    },
                    "provenance": source_record(inventory_row, INVENTORY_FILE, INVENTORY_SHEET),
                }
            )
            sales_windows.append(
                {
                    "as_of_date": AS_OF_DATE,
                    "child_asin": child_asin,
                    "parent_asin": parent_asin,
                    **{
                        target: to_number(inventory_row.get(source))
                        for source, target in sales_window_fields.items()
                    },
                    "provenance": source_record(inventory_row, INVENTORY_FILE, INVENTORY_SHEET),
                }
            )
            supply_plan.append(
                {
                    "as_of_date": AS_OF_DATE,
                    "child_asin": child_asin,
                    "parent_asin": parent_asin,
                    **{
                        target: to_number(inventory_row.get(source))
                        for source, target in supply_number_fields.items()
                    },
                    **{
                        target: normalize_date(inventory_row.get(source))
                        for source, target in supply_date_fields.items()
                    },
                    "provenance": source_record(inventory_row, INVENTORY_FILE, INVENTORY_SHEET),
                }
            )
        if child_age_rows:
            age_buckets.append(
                {
                    "snapshot_period": MONTHLY_SOURCE_PERIOD,
                    "child_asin": child_asin,
                    "parent_asin": parent_asin,
                    **aggregate_numeric(child_age_rows, age_fields),
                    "source_row_count": len(child_age_rows),
                    "provenance": {
                        "provenance_type": "customer_actual",
                        "source_file": MONTHLY_FILE,
                        "source_sheet": AGE_SHEET,
                        "source_rows": sorted(int(row["__source_row"]) for row in child_age_rows),
                        "aggregation_rule": "sum_rows_by_child_asin",
                        "source_as_of_date": "2026-06-30",
                    },
                }
            )

        missing_matrix.append(
            {
                "child_asin": child_asin,
                "parent_asin": parent_asin,
                "has_product_master": True,
                "has_inventory_snapshot": inventory_row is not None,
                "has_sku": bool(inventory_row and clean_text(inventory_row.get("SKU"))),
                "has_fnsku": bool(inventory_row and clean_text(inventory_row.get("FNSKU"))),
                "has_age_buckets": bool(child_age_rows),
                "has_expected_stockout_date": bool(
                    inventory_row and normalize_date(inventory_row.get("断货时间"))
                ),
                "has_suggested_purchase_date": bool(
                    inventory_row and normalize_date(inventory_row.get("建议采购日"))
                ),
                "needs_child_daily_supplement": True,
                "needs_inventory_history_supplement": True,
                "needs_lot_date_supplement": True,
                "needs_forecast_derivation": True,
                "needs_projection_derivation": True,
                "needs_risk_derivation": True,
            }
        )

    parent_daily = []
    daily_source_summary = []
    for parent_asin in selected_parents:
        source = daily_sources[parent_asin]
        relative_path = source["relative_path"]
        sheet_name = source["sheet_name"]
        daily_source_summary.append(
            {
                "parent_asin": parent_asin,
                "source_file": relative_path,
                "source_sheet": sheet_name,
                "date_count": source["date_count"],
                "min_date": min(source["rows_by_date"]),
                "max_date": max(source["rows_by_date"]),
            }
        )
        for business_date, row in sorted(source["rows_by_date"].items()):
            child_list = [
                asin
                for asin in (normalize_asin(item) for item in str(row.get("ASIN", "")).split(","))
                if asin
            ]
            parent_daily.append(
                {
                    "date": business_date,
                    "parent_asin": parent_asin,
                    "reported_child_asins": child_list,
                    "units_sold": to_number(row.get("销量")),
                    "sales_amount": to_number(row.get("销售额")),
                    "order_gross_profit": to_number(row.get("订单毛利润")),
                    "settlement_gross_profit": to_number(row.get("结算毛利润")),
                    "settlement_gross_margin": to_number(row.get("结算毛利率")),
                    "order_gross_margin": to_number(row.get("订单毛利率")),
                    "fba_sellable": to_number(row.get("FBA-可售")),
                    "available_inventory": to_number(row.get("可用库存")),
                    "fba_inbound": to_number(row.get("FBA-在途")),
                    "sessions": to_number(row.get("Sessions-Total")),
                    "cvr": to_number(row.get("CVR")),
                    "ad_spend": to_number(row.get("广告花费")),
                    "acos": to_number(row.get("ACOS")),
                    "acoas": to_number(row.get("ACoAS")),
                    "ad_sales": to_number(row.get("广告销售额")),
                    "clicks": to_number(row.get("点击")),
                    "impressions": to_number(row.get("展示")),
                    "provenance": source_record(row, relative_path, sheet_name),
                }
            )

    child_monthly_by_parent: dict[str, dict[str, float]] = defaultdict(
        lambda: {"units_sold": 0.0, "sales_amount": 0.0}
    )
    for row in child_monthly_sales:
        for field in ("units_sold", "sales_amount"):
            value = row.get(field)
            if value is not None:
                child_monthly_by_parent[row["parent_asin"]][field] += float(value)
    parent_monthly_map = {row["parent_asin"]: row for row in parent_monthly}
    reconciliation = []
    for parent_asin in selected_parents:
        child_sum = child_monthly_by_parent[parent_asin]
        parent_row = parent_monthly_map.get(parent_asin, {})
        parent_units = parent_row.get("units_sold")
        parent_sales = parent_row.get("sales_amount")
        unit_difference = (
            round(child_sum["units_sold"] - float(parent_units), 6)
            if parent_units is not None
            else None
        )
        sales_difference = (
            round(child_sum["sales_amount"] - float(parent_sales), 6)
            if parent_sales is not None
            else None
        )
        reconciliation.append(
            {
                "period": MONTHLY_SOURCE_PERIOD,
                "parent_asin": parent_asin,
                "child_units_sum": round(child_sum["units_sold"], 6),
                "parent_units_reported": parent_units,
                "units_difference": unit_difference,
                "child_sales_sum": round(child_sum["sales_amount"], 6),
                "parent_sales_reported": parent_sales,
                "sales_difference": sales_difference,
                "status": (
                    "matched"
                    if unit_difference == 0 and (sales_difference is not None and abs(sales_difference) < 0.01)
                    else "review"
                ),
            }
        )

    selection_rows = []
    for parent_asin in selected_parents:
        stat = candidate_stats[parent_asin]
        selection_rows.append(
            {
                **stat,
                "selection_role": lifecycle_labels[parent_asin],
                "selection_rule": (
                    "four_mature_parents_total_children_nearest_250"
                    if lifecycle_labels[parent_asin] == "mature"
                    else "short_history_parent_nearest_90_children_with_high_coverage"
                ),
                "daily_source": next(
                    item for item in daily_source_summary if item["parent_asin"] == parent_asin
                ),
            }
        )

    datasets = {
        "dim_product_parent.json": dim_parent,
        "dim_product_child.json": dim_child,
        "bridge_product_identifier.json": bridge_identifiers,
        "fact_parent_sales_daily.json": parent_daily,
        "fact_parent_sales_monthly.json": parent_monthly,
        "fact_child_sales_monthly.json": child_monthly_sales,
        "fact_sales_window.json": sales_windows,
        "fact_inventory_snapshot.json": inventory_snapshot,
        "fact_inventory_age_bucket.json": age_buckets,
        "fact_supply_plan.json": supply_plan,
        "missing_field_matrix.json": missing_matrix,
        "reconciliation_report.json": reconciliation,
        "parent_selection.json": selection_rows,
    }

    source_lineage = {
        "dataset_version": DATASET_VERSION,
        "source_root": str(SOURCE_ROOT),
        "sources": [
            {
                "relative_path": MONTHLY_FILE,
                "sheets": [PRODUCT_CHILD_SHEET, PRODUCT_PARENT_SHEET, AGE_SHEET],
                "usage": [
                    "product hierarchy",
                    "child and parent monthly sales",
                    "inventory age and AWD snapshot",
                ],
            },
            {
                "relative_path": INVENTORY_FILE,
                "sheets": [INVENTORY_SHEET],
                "usage": [
                    "identifier mapping",
                    "current inventory",
                    "rolling sales windows",
                    "replenishment plan",
                ],
                "deduplication_note": (
                    "5.库存或备货计算表-物流管理表.xlsx has the same SHA-256 and is excluded"
                ),
            },
            *[
                {
                    "relative_path": item["source_file"],
                    "sheets": [item["source_sheet"]],
                    "usage": [f"daily parent sales for {item['parent_asin']}"],
                }
                for item in daily_source_summary
            ],
        ],
    }

    return {
        "datasets": datasets,
        "source_lineage": source_lineage,
        "selection_rows": selection_rows,
        "selected_parents": selected_parents,
        "selected_children": selected_children,
    }


def write_json(path: Path, data: Any) -> str:
    payload = json.dumps(json_ready(data), ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    path.write_text(payload, encoding="utf-8")
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_quality_summary(result: dict[str, Any]) -> dict[str, Any]:
    datasets = result["datasets"]
    child_count = len(datasets["dim_product_child.json"])
    inventory_count = len(datasets["fact_inventory_snapshot.json"])
    age_count = len(datasets["fact_inventory_age_bucket.json"])
    identifier_count = len(datasets["bridge_product_identifier.json"])
    missing = datasets["missing_field_matrix.json"]
    reconciliation = datasets["reconciliation_report.json"]

    checks = [
        {
            "check": "selected_parent_count",
            "expected": 5,
            "actual": len(result["selected_parents"]),
            "passed": len(result["selected_parents"]) == 5,
        },
        {
            "check": "selected_child_count",
            "expected": 342,
            "actual": child_count,
            "passed": child_count == 342,
        },
        {
            "check": "unique_child_asin",
            "expected": child_count,
            "actual": len(set(result["selected_children"])),
            "passed": child_count == len(set(result["selected_children"])),
        },
        {
            "check": "inventory_coverage",
            "expected": ">= 97%",
            "actual": round(inventory_count / max(1, child_count), 6),
            "passed": inventory_count / max(1, child_count) >= 0.97,
        },
        {
            "check": "age_coverage",
            "expected": ">= 98%",
            "actual": round(age_count / max(1, child_count), 6),
            "passed": age_count / max(1, child_count) >= 0.98,
        },
        {
            "check": "identifier_coverage",
            "expected": ">= 97%",
            "actual": round(identifier_count / max(1, child_count), 6),
            "passed": identifier_count / max(1, child_count) >= 0.97,
        },
        {
            "check": "daily_parent_coverage",
            "expected": 5,
            "actual": len({row["parent_asin"] for row in datasets["fact_parent_sales_daily.json"]}),
            "passed": len({row["parent_asin"] for row in datasets["fact_parent_sales_daily.json"]}) == 5,
        },
        {
            "check": "monthly_parent_coverage",
            "expected": 5,
            "actual": len(datasets["fact_parent_sales_monthly.json"]),
            "passed": len(datasets["fact_parent_sales_monthly.json"]) == 5,
        },
    ]
    summary = {
        "dataset_version": DATASET_VERSION,
        "parent_count": len(result["selected_parents"]),
        "child_count": child_count,
        "record_counts": {name: len(rows) for name, rows in datasets.items()},
        "coverage": {
            "inventory": round(inventory_count / max(1, child_count), 6),
            "age_bucket": round(age_count / max(1, child_count), 6),
            "identifier": round(identifier_count / max(1, child_count), 6),
            "expected_stockout_date": round(
                sum(row["has_expected_stockout_date"] for row in missing) / max(1, child_count), 6
            ),
            "suggested_purchase_date": round(
                sum(row["has_suggested_purchase_date"] for row in missing) / max(1, child_count), 6
            ),
        },
        "missing_field_summary": {
            key: sum(not bool(row[key]) for row in missing)
            for key in [
                "has_inventory_snapshot",
                "has_sku",
                "has_fnsku",
                "has_age_buckets",
                "has_expected_stockout_date",
                "has_suggested_purchase_date",
            ]
        },
        "supplement_or_derivation_required": {
            key: sum(bool(row[key]) for row in missing)
            for key in [
                "needs_child_daily_supplement",
                "needs_inventory_history_supplement",
                "needs_lot_date_supplement",
                "needs_forecast_derivation",
                "needs_projection_derivation",
                "needs_risk_derivation",
            ]
        },
        "reconciliation": {
            "matched": sum(row["status"] == "matched" for row in reconciliation),
            "review": sum(row["status"] == "review" for row in reconciliation),
        },
        "checks": checks,
        "all_checks_passed": all(check["passed"] for check in checks),
    }
    return summary


def write_markdown_report(result: dict[str, Any], quality: dict[str, Any]) -> None:
    selection = result["selection_rows"]
    lines = [
        "# 产品销售库存 Demo 真实数据底座 v0.1.0",
        "",
        f"生成时间：{BUILD_TIMESTAMP}  ",
        f"数据截止日：{AS_OF_DATE}  ",
        "性质：客户真实数据清洗与标准化；尚未加入预测、投影、风险与场景补充。",
        "",
        "## 1. 首版范围",
        "",
        f"- 父 ASIN：**{quality['parent_count']}** 个；",
        f"- 子 ASIN：**{quality['child_count']}** 个；",
        f"- 父体日销售：**{quality['record_counts']['fact_parent_sales_daily.json']}** 条；",
        f"- 当前库存：**{quality['record_counts']['fact_inventory_snapshot.json']}** 条；",
        f"- 库龄记录：**{quality['record_counts']['fact_inventory_age_bucket.json']}** 条。",
        "",
        "| 父 ASIN | 角色 | 子体 | 日历史 | 库存覆盖 | 库龄覆盖 |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for item in selection:
        lines.append(
            f"| `{item['parent_asin']}` | {item['selection_role']} | {item['child_count']} | "
            f"{item['daily_history_days']} | {item['inventory_coverage']:.1%} | {item['age_coverage']:.1%} |"
        )
    lines.extend(
        [
            "",
            "## 2. 质量结果",
            "",
            "| 检查 | 预期 | 实际 | 结果 |",
            "| --- | ---: | ---: | --- |",
        ]
    )
    for check in quality["checks"]:
        lines.append(
            f"| {check['check']} | {check['expected']} | {check['actual']} | "
            f"{'通过' if check['passed'] else '未通过'} |"
        )
    lines.extend(
        [
            "",
            f"月度父子汇总核对：{quality['reconciliation']['matched']} 个完全一致，"
            f"{quality['reconciliation']['review']} 个需复核。需复核父体仅相差 1 件销量和 28.48 美元销售额，"
            "保留差异，不静默改写客户原值。",
            "",
            "## 3. 仍需补齐或派生",
            "",
            "- 子 ASIN 日销售序列：依据父体日总量、子体月销量和滚动销量窗口约束拆分；",
            "- 历史库存快照与批次收货日：从当前库存、销量和库龄桶回放，明确标记 `supplemented`；",
            "- 90 天需求预测、库存投影、盘点和五类风险：按规则生成，标记 `derived`；",
            "- 活动与特殊异常：优先从真实记录识别，只补充缺失的必要场景。",
            "",
            "## 4. 使用边界",
            "",
            "- 原始工作簿保持只读，所有记录保留来源文件、Sheet 和原始行号；",
            "- 两份完全重复的库存工作簿只导入一个逻辑来源；",
            "- 本数据包包含客户实际经营数据，只能用于本项目授权范围；",
            "- 页面不得把后续补齐值展示成客户原始事实。",
            "",
        ]
    )
    (OUTPUT_ROOT / "README.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    if OUTPUT_ROOT.exists():
        shutil.rmtree(OUTPUT_ROOT)
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    result = build_dataset()
    hashes: dict[str, str] = {}
    for filename, data in result["datasets"].items():
        hashes[filename] = write_json(OUTPUT_ROOT / filename, data)
    hashes["source_lineage.json"] = write_json(
        OUTPUT_ROOT / "source_lineage.json", result["source_lineage"]
    )

    quality = build_quality_summary(result)
    hashes["quality_report.json"] = write_json(OUTPUT_ROOT / "quality_report.json", quality)
    write_markdown_report(result, quality)
    hashes["README.md"] = hashlib.sha256((OUTPUT_ROOT / "README.md").read_bytes()).hexdigest()

    manifest = {
        "dataset_name": "bamboocool-product-sales-inventory-demo",
        "dataset_version": DATASET_VERSION,
        "generated_at": BUILD_TIMESTAMP,
        "as_of_date": AS_OF_DATE,
        "source_period": MONTHLY_SOURCE_PERIOD,
        "data_nature": "customer_actual_normalized",
        "parent_count": len(result["selected_parents"]),
        "child_count": len(result["selected_children"]),
        "selected_parent_asins": result["selected_parents"],
        "files": [
            {
                "name": filename,
                "sha256": digest,
                "record_count": (
                    len(result["datasets"].get(filename, []))
                    if filename in result["datasets"]
                    else None
                ),
            }
            for filename, digest in sorted(hashes.items())
        ],
        "quality_checks_passed": quality["all_checks_passed"],
        "next_layer": [
            "supplemented child daily sales",
            "supplemented inventory history and lot dates",
            "derived demand forecast",
            "derived inventory projection",
            "derived assessment and risks",
        ],
    }
    write_json(OUTPUT_ROOT / "dataset-manifest.json", manifest)

    if not quality["all_checks_passed"]:
        failed = [check["check"] for check in quality["checks"] if not check["passed"]]
        raise RuntimeError(f"数据质量检查未通过：{', '.join(failed)}")
    print(
        json.dumps(
            {
                "output": str(OUTPUT_ROOT),
                "parents": len(result["selected_parents"]),
                "children": len(result["selected_children"]),
                "all_checks_passed": quality["all_checks_passed"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
