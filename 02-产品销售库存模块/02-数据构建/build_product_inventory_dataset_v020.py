#!/usr/bin/env python3
"""Build the corrected v0.2.0 source-fact package without touching v0.1.0.

This builder deliberately keeps directly supplied values, calculations based on
customer cells, downstream derivations, estimates, and unknowns distinguishable.
It uses the existing source index and reads cached OOXML formula results when
they are present in the workbook.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import math
import re
import shutil
import sqlite3
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Any
from zipfile import ZipFile


ROOT = Path("/Users/linsen/BAM")
MODULE_ROOT = ROOT / "02-产品销售库存模块"
BUILD_ROOT = MODULE_ROOT / "02-数据构建"
BASE_BUILDER_PATH = BUILD_ROOT / "build_product_inventory_dataset.py"
V010_ROOT = BUILD_ROOT / "v0.1.0"
OUTPUT_ROOT = BUILD_ROOT / "v0.2.0"
STAGING_ROOT = BUILD_ROOT / ".v0.2.0-building"

DATASET_VERSION = "0.2.0"
AS_OF_DATE = "2026-08-03"
AS_OF = date.fromisoformat(AS_OF_DATE)
MONTHLY_SOURCE_PERIOD = "2026-06"
BUILD_TIMESTAMP = datetime.now().astimezone().isoformat(timespec="seconds")

ATTRIBUTE_FILE = "3.库存表-物流管理表.xlsx"
ATTRIBUTE_SHEET = "一组"
SHIPMENT_FILE = "4.物流或补货清单-运营出货表.xlsx"
SHIPMENT_SHEET = "出货表"
MONTHLY_FILE = "14.其他分析文件/2026年月报/6月/一组6月月报.xlsx"
STYLE_MONTHLY_SHEET = "月报"
COST_SOURCES = [
    (
        "1.产品跟进表-运营记录/产品跟进表-曾向锋.xlsx",
        "冗余库存-领星库存管理",
    ),
    (
        "1.产品跟进表-运营记录/产品跟进表-王倩倩.（1）xlsx.xlsx",
        "冗余库存-领星库存管理",
    ),
]

DAILY_CANONICAL_FIELDS = {
    "units_sold": ["销量"],
    "sales_amount": ["销售额"],
    "order_gross_profit": ["订单毛利润"],
    "settlement_gross_profit": ["结算毛利润"],
    "settlement_gross_margin": ["结算毛利率"],
    "order_gross_margin": ["订单毛利率"],
    "fba_sellable": ["FBA-可售", "可售庫存", "可售库存"],
    "available_inventory": ["可用库存"],
    "fba_inbound": ["FBA-在途"],
    "sessions": ["Sessions-Total", "session"],
    "cvr": ["CVR", "综合转化率"],
    "ad_spend": ["广告花费", "total spend"],
    "acos": ["ACOS", "Acos"],
    "acoas": ["ACoAS"],
    "ad_sales": ["广告销售额"],
    "clicks": ["点击", "clicks"],
    "impressions": ["展示", "Impressions"],
}

PARENT_INVENTORY_FIELDS = {
    "fba_sellable": DAILY_CANONICAL_FIELDS["fba_sellable"],
    "available_inventory": DAILY_CANONICAL_FIELDS["available_inventory"],
    "fba_inbound": DAILY_CANONICAL_FIELDS["fba_inbound"],
    "sessions": DAILY_CANONICAL_FIELDS["sessions"],
    "order_gross_profit": DAILY_CANONICAL_FIELDS["order_gross_profit"],
}


def load_base_builder():
    spec = importlib.util.spec_from_file_location("bamboocool_v010_builder", BASE_BUILDER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法载入 v0.1.0 构建器：{BASE_BUILDER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BASE = load_base_builder()
SCANNER = BASE.SCANNER
SOURCE_ROOT = BASE.SOURCE_ROOT
INDEX_PATH = BASE.INDEX_PATH


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def directory_hashes(path: Path) -> dict[str, str]:
    return {
        item.relative_to(path).as_posix(): sha256_file(item)
        for item in sorted(path.rglob("*"))
        if item.is_file()
    }


def json_ready(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return round(value, 8)
    if isinstance(value, dict):
        return {key: json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_ready(item) for item in value]
    return value


def decode_cached_cell(
    cell,
    shared_strings: list[str],
    date_style_indexes: set[int],
    date_1904: bool,
) -> tuple[Any, str | None, bool]:
    """Return cached/display value, formula text, and error status."""
    formula_text = SCANNER._first_local_text(cell, "f")
    cell_type = cell.get("t", "n")
    value_text = SCANNER._first_local_text(cell, "v")

    if cell_type == "inlineStr":
        parts = cell.xpath("./*[local-name()='is']//*[local-name()='t']/text()")
        return "".join(parts), formula_text, False
    if value_text is None:
        return None, formula_text, False
    if cell_type == "s":
        try:
            index = int(value_text)
            value = shared_strings[index] if 0 <= index < len(shared_strings) else value_text
            return value, formula_text, False
        except (TypeError, ValueError):
            return value_text, formula_text, False
    if cell_type == "b":
        return value_text == "1", formula_text, False
    if cell_type == "e":
        return value_text, formula_text, True
    if cell_type == "d":
        try:
            return datetime.fromisoformat(value_text.replace("Z", "+00:00")), formula_text, False
        except ValueError:
            return value_text, formula_text, False
    if cell_type in {"str", "inlineStr"}:
        return value_text, formula_text, False

    try:
        number = float(value_text)
        numeric_value: int | float = int(number) if number.is_integer() else number
        try:
            style_index = int(cell.get("s", "0"))
        except ValueError:
            style_index = 0
        if style_index in date_style_indexes:
            try:
                return SCANNER._excel_serial_to_datetime(number, date_1904), formula_text, False
            except (OverflowError, ValueError):
                pass
        return numeric_value, formula_text, False
    except (TypeError, ValueError):
        return value_text, formula_text, False


class CachedFormulaWorkbookReader:
    """Indexed XLSX reader that uses saved formula values and keeps formula lineage."""

    def __init__(self, index: dict[str, Any]):
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
        with ZipFile(SOURCE_ROOT / relative_path) as package:
            shared_strings = SCANNER.read_shared_strings(package)
            date_styles = SCANNER.read_date_style_indexes(package)
            workbook_sheets, date_1904 = SCANNER.read_workbook_metadata(package)
            sheet_path = next(
                sheet["path"] for sheet in workbook_sheets if sheet["name"] == sheet_name
            )
            with package.open(sheet_path) as stream:
                for _, element in SCANNER.etree.iterparse(stream, events=("end",)):
                    local_name = SCANNER.etree.QName(element).localname
                    if local_name != "c":
                        if local_name == "row":
                            element.clear()
                            parent = element.getparent()
                            if parent is not None:
                                while element.getprevious() is not None:
                                    del parent[0]
                        continue
                    reference = element.get("r", "")
                    row_match = re.search(r"(\d+)$", reference)
                    column_index = SCANNER.column_index_from_ref(reference)
                    if row_match and column_index in positions:
                        row_index = int(row_match.group(1))
                        if row_index > header_row:
                            value, formula_text, is_error = decode_cached_cell(
                                element, shared_strings, date_styles, date_1904
                            )
                            field = positions[column_index]
                            sparse_rows[row_index][field] = value
                            if formula_text is not None:
                                sparse_rows[row_index].setdefault("__formula_fields", []).append(field)
                                sparse_rows[row_index].setdefault("__formulas", {})[field] = formula_text
                                sparse_rows[row_index].setdefault("__formula_cache_present", {})[
                                    field
                                ] = value is not None
                            if is_error:
                                sparse_rows[row_index].setdefault("__error_fields", []).append(field)
                    element.clear()
                    parent = element.getparent()
                    if parent is not None:
                        while element.getprevious() is not None:
                            del parent[0]
        rows = []
        for row_index in sorted(sparse_rows):
            row = sparse_rows[row_index]
            row["__source_row"] = row_index
            rows.append(row)
        self.cache[key] = rows
        return rows


def clean_text(value: Any) -> str | None:
    return BASE.clean_text(value)


def normalize_asin(value: Any) -> str | None:
    return BASE.normalize_asin(value)


def to_number(value: Any) -> int | float | None:
    return BASE.to_number(value)


def normalize_date(value: Any) -> str | None:
    return BASE.normalize_date(value)


def normalize_datetime(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time()).isoformat()
    parsed = SCANNER.parse_date_value(value)
    return parsed.isoformat() if parsed else None


def source_record(
    row: dict[str, Any], source_file: str, source_sheet: str, source_field: str | None = None
) -> dict[str, Any]:
    record = {
        "provenance_type": "customer_actual",
        "source_file": source_file,
        "source_sheet": source_sheet,
        "source_row": int(row["__source_row"]),
        "source_as_of_date": AS_OF_DATE,
    }
    if source_field:
        record["source_field"] = source_field
        formula = row.get("__formulas", {}).get(source_field)
        if formula is not None:
            record["source_formula"] = formula
            record["formula_cache_used"] = bool(
                row.get("__formula_cache_present", {}).get(source_field)
            )
            record["provenance_type"] = "customer_actual_formula_cache"
    return record


def value_for_aliases(
    row: dict[str, Any], aliases: list[str]
) -> tuple[int | float | None, str | None, bool]:
    for field in aliases:
        value = to_number(row.get(field))
        if value is not None:
            return value, field, field in row.get("__formula_fields", [])
    return None, None, False


def load_v010_datasets() -> dict[str, list[dict[str, Any]]]:
    datasets = {}
    for path in sorted(V010_ROOT.glob("*.json")):
        if path.name in {"dataset-manifest.json", "quality_report.json", "source_lineage.json"}:
            continue
        value = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(value, list):
            datasets[path.name] = value
    return datasets


def collect_daily_candidates(
    index: dict[str, Any],
    reader: CachedFormulaWorkbookReader,
    selected_parents: set[str],
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, dict[tuple[str, str], list[dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for file in index["files"]:
        relative_path = file["relative_path"]
        if not relative_path.startswith("1.产品跟进表-运营记录/"):
            continue
        for sheet in file.get("sheets", []):
            if not {"日期", "父ASIN", "销量", "销售额"}.issubset(set(sheet.get("fields", []))):
                continue
            sheet_name = sheet["sheet_name"]
            for row in reader.rows(relative_path, sheet_name):
                parent_asin = normalize_asin(row.get("父ASIN"))
                business_date = normalize_date(row.get("日期"))
                if parent_asin not in selected_parents or not business_date:
                    continue
                if date.fromisoformat(business_date) <= AS_OF:
                    grouped[parent_asin][(relative_path, sheet_name)].append(row)

    output: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for parent_asin, sources in grouped.items():
        for (relative_path, sheet_name), rows in sources.items():
            rows_by_date = {}
            for row in rows:
                business_date = normalize_date(row.get("日期"))
                if business_date:
                    rows_by_date[business_date] = row
            units_nonnull = sales_nonnull = both_nonnull = direct_both = formula_both = 0
            for row in rows_by_date.values():
                units, _, units_formula = value_for_aliases(row, ["销量"])
                sales, _, sales_formula = value_for_aliases(row, ["销售额"])
                units_nonnull += units is not None
                sales_nonnull += sales is not None
                if units is not None and sales is not None:
                    both_nonnull += 1
                    direct_both += not units_formula and not sales_formula
                    formula_both += units_formula or sales_formula
            output[parent_asin].append(
                {
                    "parent_asin": parent_asin,
                    "relative_path": relative_path,
                    "sheet_name": sheet_name,
                    "rows_by_date": rows_by_date,
                    "date_count": len(rows_by_date),
                    "min_date": min(rows_by_date, default=None),
                    "max_date": max(rows_by_date, default=None),
                    "units_nonnull_days": units_nonnull,
                    "sales_nonnull_days": sales_nonnull,
                    "both_nonnull_days": both_nonnull,
                    "direct_both_days": direct_both,
                    "formula_cache_both_days": formula_both,
                }
            )
    return output


def candidate_rank(candidate: dict[str, Any]) -> tuple[Any, ...]:
    return (
        candidate["direct_both_days"],
        candidate["both_nonnull_days"],
        candidate["max_date"] or "",
        candidate["date_count"],
        candidate["sheet_name"] != "跟进表",
    )


def select_daily_sources(
    candidates: dict[str, list[dict[str, Any]]]
) -> dict[str, dict[str, Any]]:
    return {parent: max(items, key=candidate_rank) for parent, items in candidates.items()}


def metric_source_rank(candidate: dict[str, Any], aliases: list[str]) -> tuple[Any, ...]:
    nonnull = direct = formula = 0
    for row in candidate["rows_by_date"].values():
        value, _, is_formula = value_for_aliases(row, aliases)
        if value is not None:
            nonnull += 1
            direct += not is_formula
            formula += is_formula
    return direct, nonnull, candidate["max_date"] or "", -formula


def select_metric_sources(
    candidates: dict[str, list[dict[str, Any]]]
) -> dict[str, dict[str, dict[str, Any]]]:
    selected: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for parent, items in candidates.items():
        for metric, aliases in PARENT_INVENTORY_FIELDS.items():
            usable = [item for item in items if metric_source_rank(item, aliases)[1] > 0]
            if usable:
                selected[parent][metric] = max(
                    usable, key=lambda item: metric_source_rank(item, aliases)
                )
    return selected


def build_parent_daily_sales(
    selected_parents: list[str], selected_sources: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    rows = []
    for parent in selected_parents:
        source = selected_sources[parent]
        for business_date, row in sorted(source["rows_by_date"].items()):
            record: dict[str, Any] = {
                "date": business_date,
                "parent_asin": parent,
                "reported_child_asins": [
                    asin
                    for asin in (
                        normalize_asin(item) for item in str(row.get("ASIN", "")).split(",")
                    )
                    if asin
                ],
            }
            formula_fields = []
            for target, aliases in DAILY_CANONICAL_FIELDS.items():
                value, source_field, is_formula = value_for_aliases(row, aliases)
                record[target] = value
                if value is not None and is_formula:
                    formula_fields.append(target)
            record["value_origin"] = (
                "customer_actual_formula_cache" if formula_fields else "customer_actual"
            )
            record["formula_fields_used"] = formula_fields
            record["provenance"] = source_record(
                row, source["relative_path"], source["sheet_name"]
            )
            rows.append(record)
    return rows


def build_parent_inventory_daily(
    selected_parents: list[str],
    daily_sources: dict[str, dict[str, Any]],
    metric_sources: dict[str, dict[str, dict[str, Any]]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = []
    coverage = []
    for parent in selected_parents:
        dates = sorted(daily_sources[parent]["rows_by_date"])
        for business_date in dates:
            record: dict[str, Any] = {"date": business_date, "parent_asin": parent}
            field_provenance = {}
            missing = []
            for metric, aliases in PARENT_INVENTORY_FIELDS.items():
                source = metric_sources.get(parent, {}).get(metric)
                source_row = source["rows_by_date"].get(business_date) if source else None
                if source_row:
                    value, source_field, _ = value_for_aliases(source_row, aliases)
                else:
                    value, source_field = None, None
                record[metric] = value
                if value is None:
                    missing.append(metric)
                elif source and source_field:
                    field_provenance[metric] = source_record(
                        source_row,
                        source["relative_path"],
                        source["sheet_name"],
                        source_field,
                    )
            inventory_core = [
                record.get("fba_sellable"),
                record.get("available_inventory"),
                record.get("fba_inbound"),
            ]
            record["quality_status"] = (
                "complete" if all(value is not None for value in inventory_core) else "partial"
            )
            record["missing_metrics"] = missing
            record["field_provenance"] = field_provenance
            rows.append(record)

        for metric, aliases in PARENT_INVENTORY_FIELDS.items():
            source = metric_sources.get(parent, {}).get(metric)
            populated_dates = []
            formula_days = 0
            if source:
                for business_date in dates:
                    source_row = source["rows_by_date"].get(business_date)
                    if not source_row:
                        continue
                    value, _, is_formula = value_for_aliases(source_row, aliases)
                    if value is not None:
                        populated_dates.append(business_date)
                        formula_days += is_formula
            coverage.append(
                {
                    "parent_asin": parent,
                    "metric": metric,
                    "nonnull_days": len(populated_dates),
                    "expected_days": len(dates),
                    "nonnull_rate": round(len(populated_dates) / max(1, len(dates)), 6),
                    "coverage_start": min(populated_dates, default=None),
                    "coverage_end": max(populated_dates, default=None),
                    "formula_cache_days": formula_days,
                    "source_file": source["relative_path"] if source else None,
                    "source_sheet": source["sheet_name"] if source else None,
                }
            )
    return rows, coverage


def build_product_attributes(
    datasets: dict[str, list[dict[str, Any]]], reader: CachedFormulaWorkbookReader
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, str]]:
    dim_child = copy.deepcopy(datasets["dim_product_child.json"])
    selected = {row["child_asin"] for row in dim_child}
    attr_by_child = {}
    for row in reader.rows(ATTRIBUTE_FILE, ATTRIBUTE_SHEET):
        child = normalize_asin(row.get("ASIN"))
        if child in selected:
            attr_by_child[child] = row

    attributes = []
    style_by_child = {}
    parent_by_child = {row["child_asin"]: row["parent_asin"] for row in dim_child}
    attr_map = {
        "category": "品类",
        "operations_group": "运营组",
        "operator": "运营",
        "goods_status": "货物状态",
        "style_no": "款号",
        "combination": "组合",
        "colorway": "配色",
        "size": "尺码",
    }
    for child_row in dim_child:
        child = child_row["child_asin"]
        source_row = attr_by_child.get(child)
        values = {
            target: clean_text(source_row.get(source)) if source_row else None
            for target, source in attr_map.items()
        }
        style = values["style_no"] or clean_text(child_row.get("style_name"))
        style_by_child[child] = style
        quality_flags = [target for target, value in values.items() if value is None]
        status = "missing" if source_row is None else ("complete" if not quality_flags else "partial")
        child_row.update(values)
        child_row["style_no"] = style
        child_row["attribute_quality_status"] = status
        child_row["attribute_quality_flags"] = quality_flags
        if source_row:
            child_row["attribute_provenance"] = source_record(
                source_row, ATTRIBUTE_FILE, ATTRIBUTE_SHEET
            )
        else:
            child_row["attribute_provenance"] = None
        attributes.append(
            {
                "child_asin": child,
                "parent_asin": child_row["parent_asin"],
                **values,
                "style_no": style,
                "quality_status": status,
                "quality_flags": quality_flags,
                "provenance": (
                    source_record(source_row, ATTRIBUTE_FILE, ATTRIBUTE_SHEET)
                    if source_row
                    else None
                ),
            }
        )

    edges: dict[tuple[str, str], list[str]] = defaultdict(list)
    for row in attributes:
        if row["provenance"] and row["style_no"]:
            edges[(row["parent_asin"], row["style_no"])].append(row["child_asin"])
    bridge = [
        {
            "parent_asin": parent,
            "style_no": style,
            "child_count": len(children),
            "child_asins": sorted(children),
            "relationship_type": "cross_dimension",
            "value_origin": "customer_actual",
        }
        for (parent, style), children in sorted(edges.items())
    ]
    return dim_child, attributes, bridge, style_by_child


def build_style_monthly_attributes(
    reader: CachedFormulaWorkbookReader,
    selected_styles: set[str],
    selected_parents: set[str],
) -> list[dict[str, Any]]:
    rows = []
    for source_row in reader.rows(MONTHLY_FILE, STYLE_MONTHLY_SHEET):
        style = clean_text(source_row.get("款号"))
        if style not in selected_styles:
            continue
        parent = normalize_asin(source_row.get("父asin"))
        if parent not in selected_parents:
            continue
        record_id = hashlib.sha1(
            f"{MONTHLY_FILE}|{STYLE_MONTHLY_SHEET}|{source_row['__source_row']}".encode()
        ).hexdigest()[:16]
        rows.append(
            {
                "record_id": f"STYLEMONTH-{record_id}",
                "period": MONTHLY_SOURCE_PERIOD,
                "style_no": style,
                "parent_asin": parent,
                "owner": clean_text(source_row.get("负责人")),
                "secondary_category": clean_text(source_row.get("二级类目")),
                "product_lifecycle": clean_text(source_row.get("产品生命周期")),
                "list_price": to_number(source_row.get("定价")),
                "average_selling_price": to_number(source_row.get("平均售价")),
                "bd_days": to_number(source_row.get("BD天数")),
                "bd_performance": to_number(source_row.get("BD表现（售卖库存）")),
                "value_origin": "customer_actual",
                "provenance": source_record(source_row, MONTHLY_FILE, STYLE_MONTHLY_SHEET),
            }
        )
    return rows


def choose_style(row: dict[str, Any]) -> tuple[str | None, str | None]:
    for field in ["款号，最终", "款号2025", "款号"]:
        value = clean_text(row.get(field))
        if value:
            return value, field
    return None, None


def parse_lead_range(value: Any) -> tuple[int, int] | None:
    text = clean_text(value)
    if not text:
        return None
    numbers = [int(item) for item in re.findall(r"\d+", text)]
    if not numbers:
        return None
    return (numbers[0], numbers[1] if len(numbers) > 1 else numbers[0])


def build_supply_events(
    reader: CachedFormulaWorkbookReader,
    selected_styles: set[str],
    bridge_parent_style: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    parents_by_style: dict[str, list[str]] = defaultdict(list)
    children_by_style: dict[str, list[str]] = defaultdict(list)
    for edge in bridge_parent_style:
        parents_by_style[edge["style_no"]].append(edge["parent_asin"])
        children_by_style[edge["style_no"]].extend(edge["child_asins"])

    events = []
    for row in reader.rows(SHIPMENT_FILE, SHIPMENT_SHEET):
        style, style_field = choose_style(row)
        if style not in selected_styles:
            continue
        created_at = normalize_datetime(row.get("创建时间"))
        created_date = date.fromisoformat(created_at[:10]) if created_at else None
        eta_start_actual = normalize_date(row.get("最早到货日期"))
        eta_end_actual = normalize_date(row.get("最晚到货日期"))
        lead_range = parse_lead_range(row.get("时效需求"))
        if eta_start_actual or eta_end_actual:
            eta_origin = "customer_actual"
            eta_start = eta_start_actual or eta_end_actual
            eta_end = eta_end_actual or eta_start_actual
        elif created_date and lead_range:
            eta_origin = "estimated"
            eta_start = (created_date + timedelta(days=lead_range[0])).isoformat()
            eta_end = (created_date + timedelta(days=lead_range[1])).isoformat()
        else:
            eta_origin = "unknown"
            eta_start = eta_end = None

        actual_delivery = normalize_date(row.get("实际交期"))
        if actual_delivery and date.fromisoformat(actual_delivery) <= AS_OF:
            status = "received"
        elif eta_end and date.fromisoformat(eta_end) < AS_OF:
            status = "overdue_or_unconfirmed"
        elif eta_end:
            status = "scheduled_or_in_transit"
        else:
            status = "unknown"

        quantity = to_number(row.get("件数"))
        volume = to_number(row.get("体积"))
        unit_volume = (
            round(float(volume) / float(quantity), 10)
            if volume is not None and quantity not in {None, 0}
            else None
        )
        digest = hashlib.sha1(
            f"{SHIPMENT_FILE}|{SHIPMENT_SHEET}|{row['__source_row']}".encode()
        ).hexdigest()[:16]
        events.append(
            {
                "supply_event_id": f"SHIP-{digest}",
                "event_grain": "source_shipment_row_x_style",
                "style_no": style,
                "matched_parent_asins": sorted(set(parents_by_style.get(style, []))),
                "matched_child_count": len(set(children_by_style.get(style, []))),
                "created_at": created_at,
                "shipment_id": clean_text(row.get("货件编号")),
                "tracking_number": clean_text(row.get("追踪编号")),
                "contract_number": clean_text(row.get("合同号")),
                "store": clean_text(row.get("店铺")),
                "operator": clean_text(row.get("运营")),
                "quantity_units": quantity,
                "package_count": to_number(row.get("盒数")),
                "carton_count": to_number(row.get("箱数")),
                "carton_dimensions": clean_text(row.get("箱规")),
                "volume_m3": volume,
                "unit_volume_m3": unit_volume,
                "specification": clean_text(row.get("规格")),
                "transit_requirement": clean_text(row.get("时效需求")),
                "eta_earliest_actual": eta_start_actual,
                "eta_latest_actual": eta_end_actual,
                "eta_earliest_effective": eta_start,
                "eta_latest_effective": eta_end,
                "eta_origin": eta_origin,
                "actual_delivery_date": actual_delivery,
                "event_status_as_of": status,
                "channel": clean_text(row.get("渠道")),
                "value_origin": "customer_actual" if eta_origin == "customer_actual" else eta_origin,
                "provenance": source_record(row, SHIPMENT_FILE, SHIPMENT_SHEET, style_field),
            }
        )
    return events


def build_unit_economics(
    reader: CachedFormulaWorkbookReader,
    dim_child: list[dict[str, Any]],
    style_by_child: dict[str, str | None],
    supply_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    selected = {row["child_asin"] for row in dim_child}
    direct_candidates: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for source_file, source_sheet in COST_SOURCES:
        for row in reader.rows(source_file, source_sheet):
            child = normalize_asin(row.get("ASIN"))
            quantity = to_number(row.get("FBA可售"))
            total_cost = to_number(row.get("FBA可售(成本)"))
            if child not in selected or quantity in {None, 0} or total_cost is None:
                continue
            unit_cost = float(total_cost) / float(quantity)
            direct_candidates[child].append(
                {
                    "unit_cost": unit_cost,
                    "quantity": quantity,
                    "total_cost": total_cost,
                    "provenance": source_record(
                        row, source_file, source_sheet, "FBA可售(成本)"
                    ),
                }
            )

    direct_cost = {
        child: max(items, key=lambda item: float(item["quantity"]))
        for child, items in direct_candidates.items()
    }
    costs_by_style: dict[str, list[float]] = defaultdict(list)
    for child, item in direct_cost.items():
        style = style_by_child.get(child)
        if style:
            costs_by_style[style].append(float(item["unit_cost"]))

    volumes_by_style: dict[str, list[float]] = defaultdict(list)
    for event in supply_events:
        if event["unit_volume_m3"] is not None:
            volumes_by_style[event["style_no"]].append(float(event["unit_volume_m3"]))

    output = []
    for child_row in dim_child:
        child = child_row["child_asin"]
        style = style_by_child.get(child)
        direct = direct_cost.get(child)
        if direct:
            unit_cost = round(float(direct["unit_cost"]), 6)
            cost_origin = "customer_actual_derived"
            cost_method = "FBA可售(成本) / FBA可售"
            cost_source = direct["provenance"]
            cost_sample_count = 1
        elif style and costs_by_style.get(style):
            unit_cost = round(median(costs_by_style[style]), 6)
            cost_origin = "derived"
            cost_method = "same_style_direct_unit_cost_median"
            cost_source = {
                "source_styles": [style],
                "direct_child_sample_count": len(costs_by_style[style]),
            }
            cost_sample_count = len(costs_by_style[style])
        else:
            unit_cost = None
            cost_origin = "unknown"
            cost_method = None
            cost_source = None
            cost_sample_count = 0

        if style and volumes_by_style.get(style):
            unit_volume = round(median(volumes_by_style[style]), 10)
            volume_origin = "derived"
            volume_method = "median(shipment_volume_m3 / shipment_quantity_units) by style"
            volume_sample_count = len(volumes_by_style[style])
        else:
            unit_volume = None
            volume_origin = "unknown"
            volume_method = None
            volume_sample_count = 0

        flags = []
        if unit_cost is None:
            flags.append("unit_cost_unknown")
        if unit_volume is None:
            flags.append("unit_volume_unknown")
        flags.append("cost_currency_unconfirmed")
        output.append(
            {
                "as_of_date": AS_OF_DATE,
                "child_asin": child,
                "parent_asin": child_row["parent_asin"],
                "style_no": style,
                "unit_cost": unit_cost,
                "unit_cost_currency": None,
                "unit_cost_currency_status": "unconfirmed",
                "unit_cost_origin": cost_origin,
                "unit_cost_method": cost_method,
                "unit_cost_sample_count": cost_sample_count,
                "unit_cost_provenance": cost_source,
                "unit_volume_m3": unit_volume,
                "unit_volume_origin": volume_origin,
                "unit_volume_method": volume_method,
                "unit_volume_source_event_count": volume_sample_count,
                "quality_status": "complete" if not flags[:-1] else "partial",
                "quality_flags": flags,
            }
        )
    return output


def build_missing_matrix(
    base_rows: list[dict[str, Any]],
    attributes: list[dict[str, Any]],
    economics: list[dict[str, Any]],
    supply_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    attr = {row["child_asin"]: row for row in attributes}
    econ = {row["child_asin"]: row for row in economics}
    supply_styles = {row["style_no"] for row in supply_events}
    output = []
    for base_row in base_rows:
        row = copy.deepcopy(base_row)
        child = row["child_asin"]
        a = attr[child]
        e = econ[child]
        row.update(
            {
                "has_product_attribute_source": a["provenance"] is not None,
                "has_goods_status": bool(a["goods_status"]),
                "has_size": bool(a["size"]),
                "has_colorway": bool(a["colorway"]),
                "has_direct_unit_cost": e["unit_cost_origin"] == "customer_actual_derived",
                "has_any_unit_cost": e["unit_cost"] is not None,
                "has_unit_volume": e["unit_volume_m3"] is not None,
                "has_style_supply_event": bool(e["style_no"] in supply_styles),
                "unit_cost_origin": e["unit_cost_origin"],
                "unit_volume_origin": e["unit_volume_origin"],
            }
        )
        output.append(row)
    return output


def update_parent_metadata(
    datasets: dict[str, list[dict[str, Any]]], selected_sources: dict[str, dict[str, Any]]
) -> None:
    for name in ["dim_product_parent.json", "parent_selection.json"]:
        for row in datasets[name]:
            parent = row["parent_asin"]
            source = selected_sources[parent]
            row["daily_history_days"] = source["both_nonnull_days"]
            row["daily_latest_date"] = source["max_date"]
            if name == "parent_selection.json":
                row["daily_source"] = {
                    "parent_asin": parent,
                    "source_file": source["relative_path"],
                    "source_sheet": source["sheet_name"],
                    "date_count": source["date_count"],
                    "nonnull_sales_days": source["both_nonnull_days"],
                    "min_date": source["min_date"],
                    "max_date": source["max_date"],
                    "selection_policy": "direct_nonnull_required_measures_then_coverage_and_freshness",
                }


def public_source_audit(
    candidates: dict[str, list[dict[str, Any]]],
    selected: dict[str, dict[str, Any]],
    inventory_coverage: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "dataset_version": DATASET_VERSION,
        "sales_source_policy": (
            "required measure direct-value coverage, then total non-null coverage, freshness, "
            "date count, and non-follow-up preference"
        ),
        "parents": [
            {
                "parent_asin": parent,
                "selected_source_file": selected[parent]["relative_path"],
                "selected_source_sheet": selected[parent]["sheet_name"],
                "candidates": [
                    {
                        key: value
                        for key, value in candidate.items()
                        if key != "rows_by_date"
                    }
                    | {"selected": candidate is selected[parent]}
                    for candidate in sorted(items, key=candidate_rank, reverse=True)
                ],
            }
            for parent, items in sorted(candidates.items())
        ],
        "parent_inventory_metric_coverage": inventory_coverage,
    }


def dataset_specs() -> dict[str, dict[str, Any]]:
    return {
        "dim_product_parent": {"grain": "one row per parent ASIN", "key": ["parent_asin"]},
        "dim_product_child": {"grain": "one row per child ASIN", "key": ["child_asin"]},
        "dim_product_attribute": {"grain": "one row per child ASIN", "key": ["child_asin"]},
        "bridge_parent_style": {
            "grain": "one row per parent ASIN x style",
            "key": ["parent_asin", "style_no"],
        },
        "bridge_product_identifier": {"grain": "one row per child ASIN", "key": ["child_asin"]},
        "fact_parent_sales_daily": {
            "grain": "one row per date x parent ASIN",
            "key": ["date", "parent_asin"],
        },
        "fact_parent_inventory_daily": {
            "grain": "one row per date x parent ASIN",
            "key": ["date", "parent_asin"],
        },
        "fact_parent_sales_monthly": {
            "grain": "one row per period x parent ASIN",
            "key": ["period", "parent_asin"],
        },
        "fact_child_sales_monthly": {
            "grain": "one row per period x child ASIN",
            "key": ["period", "child_asin"],
        },
        "fact_style_monthly_attribute": {
            "grain": "one source monthly row per style x parent",
            "key": ["record_id"],
        },
        "fact_sales_window": {"grain": "one row per as-of x child ASIN", "key": ["as_of_date", "child_asin"]},
        "fact_inventory_snapshot": {"grain": "one row per snapshot x child ASIN", "key": ["snapshot_date", "child_asin"]},
        "fact_inventory_age_bucket": {"grain": "one row per period x child ASIN", "key": ["snapshot_period", "child_asin"]},
        "fact_supply_plan": {"grain": "one row per as-of x child ASIN", "key": ["as_of_date", "child_asin"]},
        "fact_supply_event": {"grain": "one source shipment row x matched style", "key": ["supply_event_id"]},
        "fact_unit_economics": {"grain": "one row per as-of x child ASIN", "key": ["as_of_date", "child_asin"]},
        "missing_field_matrix": {"grain": "one row per child ASIN", "key": ["child_asin"]},
        "reconciliation_report": {"grain": "one row per period x parent ASIN", "key": ["period", "parent_asin"]},
        "parent_selection": {"grain": "one row per selected parent ASIN", "key": ["parent_asin"]},
    }


def sql_type(values: list[Any]) -> str:
    present = [value for value in values if value is not None]
    if not present:
        return "TEXT"
    if all(isinstance(value, bool) for value in present):
        return "INTEGER"
    if all(isinstance(value, int) and not isinstance(value, bool) for value in present):
        return "INTEGER"
    if all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in present):
        return "REAL"
    return "TEXT"


def sqlite_value(value: Any) -> Any:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (dict, list, tuple, set)):
        return json.dumps(json_ready(value), ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def create_sqlite(
    path: Path, datasets: dict[str, list[dict[str, Any]]], specs: dict[str, dict[str, Any]]
) -> dict[str, int]:
    if path.exists():
        path.unlink()
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute("PRAGMA foreign_keys=ON")
        for filename, rows in sorted(datasets.items()):
            table = filename.removesuffix(".json")
            columns = []
            for row in rows:
                for column in row:
                    if column not in columns:
                        columns.append(column)
            column_defs = [
                f'"{column}" {sql_type([row.get(column) for row in rows])}'
                for column in columns
            ]
            key = specs.get(table, {}).get("key", [])
            if key and all(column in columns for column in key):
                column_defs.append("PRIMARY KEY (" + ", ".join(f'"{item}"' for item in key) + ")")
            connection.execute(f'CREATE TABLE "{table}" ({", ".join(column_defs)})')
            if rows:
                placeholders = ", ".join("?" for _ in columns)
                column_sql = ", ".join(f'"{column}"' for column in columns)
                connection.executemany(
                    f'INSERT INTO "{table}" ({column_sql}) VALUES ({placeholders})',
                    [[sqlite_value(row.get(column)) for column in columns] for row in rows],
                )
            for index_column in ["parent_asin", "child_asin", "style_no", "date"]:
                if index_column in columns and index_column not in key:
                    connection.execute(
                        f'CREATE INDEX "idx_{table}_{index_column}" '
                        f'ON "{table}" ("{index_column}")'
                    )
        connection.commit()
        counts = {
            filename.removesuffix(".json"): connection.execute(
                f'SELECT COUNT(*) FROM "{filename.removesuffix(".json")}"'
            ).fetchone()[0]
            for filename in datasets
        }
        result = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise RuntimeError(f"SQLite integrity_check failed: {result}")
        return counts
    finally:
        connection.close()


def unique_count(rows: list[dict[str, Any]], fields: list[str]) -> int:
    return len({tuple(json.dumps(row.get(field), ensure_ascii=False, sort_keys=True) for field in fields) for row in rows})


def build_quality_report(
    datasets: dict[str, list[dict[str, Any]]],
    source_audit: dict[str, Any],
    sqlite_counts: dict[str, int],
    v010_before: dict[str, str],
    v010_after: dict[str, str],
) -> dict[str, Any]:
    parents = {row["parent_asin"] for row in datasets["dim_product_parent.json"]}
    children = {row["child_asin"] for row in datasets["dim_product_child.json"]}
    daily = datasets["fact_parent_sales_daily.json"]
    attributes = datasets["dim_product_attribute.json"]
    bridge = datasets["bridge_parent_style.json"]
    economics = datasets["fact_unit_economics.json"]
    events = datasets["fact_supply_event.json"]
    inventory_daily = datasets["fact_parent_inventory_daily.json"]

    daily_by_parent: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in daily:
        daily_by_parent[row["parent_asin"]].append(row)
    daily_profile = [
        {
            "parent_asin": parent,
            "row_count": len(rows),
            "unique_dates": len({row["date"] for row in rows}),
            "units_nonnull": sum(row["units_sold"] is not None for row in rows),
            "sales_nonnull": sum(row["sales_amount"] is not None for row in rows),
            "min_date": min(row["date"] for row in rows),
            "max_date": max(row["date"] for row in rows),
        }
        for parent, rows in sorted(daily_by_parent.items())
    ]
    attr_coverage = {
        field: {
            "nonnull": sum(bool(row.get(field)) for row in attributes),
            "rate": round(sum(bool(row.get(field)) for row in attributes) / len(attributes), 6),
            "distinct": len({row[field] for row in attributes if row.get(field)}),
        }
        for field in [
            "category",
            "operations_group",
            "operator",
            "goods_status",
            "style_no",
            "combination",
            "colorway",
            "size",
        ]
    }
    cost_profile = Counter(row["unit_cost_origin"] for row in economics)
    volume_profile = Counter(row["unit_volume_origin"] for row in economics)
    eta_profile = Counter(row["eta_origin"] for row in events)
    actual_eta_latest = [row["eta_latest_actual"] for row in events if row["eta_latest_actual"]]
    styles_to_parents: dict[str, set[str]] = defaultdict(set)
    for row in bridge:
        styles_to_parents[row["style_no"]].add(row["parent_asin"])
    shared_styles = {style: sorted(items) for style, items in styles_to_parents.items() if len(items) > 1}

    all_child_fks = []
    all_parent_fks = []
    for rows in datasets.values():
        for row in rows:
            if "child_asin" in row:
                all_child_fks.append(row["child_asin"])
            if "parent_asin" in row and row["parent_asin"] is not None:
                all_parent_fks.append(row["parent_asin"])

    formula_cache_candidates = sum(
        candidate["formula_cache_both_days"] > 0
        for parent in source_audit["parents"]
        for candidate in parent["candidates"]
    )
    checks = []

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

    add_check("v0_1_0_preserved", "all file hashes unchanged", v010_before == v010_after, v010_before == v010_after, "critical")
    add_check("parent_count", 5, len(parents), len(parents) == 5, "critical")
    add_check("child_count", 342, len(children), len(children) == 342, "critical")
    add_check("daily_parent_count", 5, len(daily_by_parent), len(daily_by_parent) == 5, "critical")
    add_check("daily_sales_nonnull_rate", 1.0, round(sum(row["units_sold"] is not None and row["sales_amount"] is not None for row in daily) / len(daily), 6), all(row["units_sold"] is not None and row["sales_amount"] is not None for row in daily), "critical")
    add_check("daily_parent_date_key_unique", len(daily), unique_count(daily, ["date", "parent_asin"]), unique_count(daily, ["date", "parent_asin"]) == len(daily), "critical")
    add_check("daily_no_dates_after_as_of", 0, sum(row["date"] > AS_OF_DATE for row in daily), all(row["date"] <= AS_OF_DATE for row in daily), "high")
    add_check("formula_cache_candidates_detected", ">= 3", formula_cache_candidates, formula_cache_candidates >= 3, "high")
    add_check("goods_status_coverage", 341, attr_coverage["goods_status"]["nonnull"], attr_coverage["goods_status"]["nonnull"] == 341, "high")
    add_check("size_coverage", 341, attr_coverage["size"]["nonnull"], attr_coverage["size"]["nonnull"] == 341, "high")
    add_check("category_distinct", 1, attr_coverage["category"]["distinct"], attr_coverage["category"]["distinct"] == 1, "medium")
    add_check("parent_style_edges", 17, len(bridge), len(bridge) == 17, "high")
    add_check("shared_parent_styles", 2, len(shared_styles), len(shared_styles) == 2, "high")
    add_check("direct_unit_cost_coverage", 144, cost_profile["customer_actual_derived"], cost_profile["customer_actual_derived"] == 144, "medium")
    add_check("shipment_event_count", 194, len(events), len(events) == 194, "high")
    add_check("actual_eta_event_count", 54, eta_profile["customer_actual"], eta_profile["customer_actual"] == 54, "medium")
    add_check("latest_actual_eta", "2026-09-19", max(actual_eta_latest, default=None), max(actual_eta_latest, default=None) == "2026-09-19", "medium")
    add_check("parent_inventory_daily_key_unique", len(inventory_daily), unique_count(inventory_daily, ["date", "parent_asin"]), unique_count(inventory_daily, ["date", "parent_asin"]) == len(inventory_daily), "critical")
    add_check("child_foreign_keys", 0, len(set(all_child_fks) - children), not (set(all_child_fks) - children), "critical")
    add_check("parent_foreign_keys", 0, len(set(all_parent_fks) - parents), not (set(all_parent_fks) - parents), "critical")
    sqlite_mismatches = {
        filename: {"json": len(rows), "sqlite": sqlite_counts.get(filename.removesuffix(".json"))}
        for filename, rows in datasets.items()
        if len(rows) != sqlite_counts.get(filename.removesuffix(".json"))
    }
    add_check("sqlite_json_row_count_match", 0, len(sqlite_mismatches), not sqlite_mismatches, "critical")

    return {
        "dataset_version": DATASET_VERSION,
        "generated_at": BUILD_TIMESTAMP,
        "intended_use": "source-fact layer for product, sales and inventory Demo pages",
        "dataset_grains": {
            name.removesuffix(".json"): spec["grain"] for name, spec in [(f"{key}.json", value) for key, value in dataset_specs().items()]
        },
        "record_counts": {name: len(rows) for name, rows in datasets.items()},
        "daily_sales_profile": daily_profile,
        "product_attribute_coverage": attr_coverage,
        "unit_cost_origin_counts": dict(cost_profile),
        "unit_volume_origin_counts": dict(volume_profile),
        "supply_eta_origin_counts": dict(eta_profile),
        "shared_parent_styles": shared_styles,
        "parent_inventory_metric_coverage": source_audit["parent_inventory_metric_coverage"],
        "known_limitations": [
            "one selected child ASIN has no matching current inventory/product-attribute row",
            "unit cost currency is not confirmed",
            "unit cost beyond direct coverage is a same-style median derivation",
            "unit volume is derived from shipment volume divided by shipment quantity and then summarized by style",
            "supply events remain at shipment-row x style grain and are not allocated to child ASINs in v0.2.0",
            "inventory age source is a 2026-06 monthly extract; exact snapshot date remains unconfirmed",
            "child daily sales, forecasts, projections, assessments and risks remain outside v0.2.0",
        ],
        "checks": checks,
        "all_checks_passed": all(check["passed"] for check in checks),
    }


def write_json(path: Path, value: Any) -> str:
    payload = json.dumps(json_ready(value), ensure_ascii=False, indent=2) + "\n"
    path.write_text(payload, encoding="utf-8")
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def write_readme(
    path: Path,
    datasets: dict[str, list[dict[str, Any]]],
    quality: dict[str, Any],
) -> None:
    lines = [
        "# 产品销售库存 Demo 来源事实数据包 v0.2.0",
        "",
        f"生成时间：{BUILD_TIMESTAMP}  ",
        f"统一业务截止日：{AS_OF_DATE}  ",
        "上一版本：`../v0.1.0`（完整保留，未覆盖、未删除）",
        "",
        "## 1. 本版修复",
        "",
        "- 日销售选源改为按必需指标的直接非空覆盖、总非空覆盖、截止日和日期数量排序；",
        "- XLSX 公式单元格同时保留公式文本并读取工作簿缓存数值；",
        "- 5 个父 ASIN 的真实日销量/销售额在各自历史区间内 100% 有值；",
        "- 新增产品属性、父体逐日库存、父体—款号桥、款号月度属性、单位经济性和在途事件；",
        "- 所有数值明确区分客户直接值、客户单元格计算值、派生值、估算值和未知值；",
        "- 质量门禁使用非空率、唯一键、外键、时效、覆盖区间和 JSON/SQLite 对账。",
        "",
        "## 2. 交付格式",
        "",
        "- JSON：每张事实表或维表一个文件，适合静态前端和调试；",
        "- SQLite：`bamboocool_product_sales_inventory_v0.2.0.sqlite`，表名与 JSON 文件名一致；",
        "- `schema_catalog.json`：表粒度、主键与字段清单；",
        "- `source_selection_audit.json`：父体日销售候选源、最终选择及逐日库存字段覆盖；",
        "- `quality_report.json`：机械门禁、覆盖率和已知限制；",
        "- `source_lineage.json`：来源文件、Sheet 与使用方式。",
        "",
        "## 3. 数据表",
        "",
        "| 表 | 记录数 | 粒度 |",
        "| --- | ---: | --- |",
    ]
    specs = dataset_specs()
    for filename, rows in sorted(datasets.items()):
        table = filename.removesuffix(".json")
        lines.append(f"| `{table}` | {len(rows):,} | {specs[table]['grain']} |")
    lines.extend(
        [
            "",
            "## 4. 来源性质",
            "",
            "| 标记 | 含义 |",
            "| --- | --- |",
            "| `customer_actual` | 客户原表直接值 |",
            "| `customer_actual_formula_cache` | 客户工作簿公式已保存的缓存结果，同时保留公式血缘 |",
            "| `customer_actual_derived` | 仅使用同一客户记录中的字段计算，例如成本 ÷ 数量 |",
            "| `derived` | 跨记录、跨款号或按规则计算 |",
            "| `estimated` | 由创建时间和时效范围估算 |",
            "| `unknown` | 信息不足，不进入正式余额或正式结论 |",
            "",
            "## 5. 质量结论",
            "",
            f"- 机械检查：{sum(check['passed'] for check in quality['checks'])}/{len(quality['checks'])} 通过；",
            f"- 父体日销售：{len(datasets['fact_parent_sales_daily.json']):,} 行；",
            f"- 产品属性：货物状态 {quality['product_attribute_coverage']['goods_status']['nonnull']}/342，尺码 {quality['product_attribute_coverage']['size']['nonnull']}/342；",
            f"- 单位成本直接反算：{quality['unit_cost_origin_counts'].get('customer_actual_derived', 0)} 个子 ASIN；",
            f"- 在途事件：{len(datasets['fact_supply_event.json'])} 条，其中原表 ETA {quality['supply_eta_origin_counts'].get('customer_actual', 0)} 条；",
            "- SQLite 已通过 `PRAGMA integrity_check`，且所有表与 JSON 行数一致。",
            "",
            "## 6. 使用边界",
            "",
            "- v0.2.0 是来源事实层，不包含子 ASIN 逐日销量、预测、库存投影、盘点结果和五类风险结果；",
            "- 出货事件保持款号粒度，尚未向子 ASIN 分摊；",
            "- 单位成本币种待客户确认，确认前不得形成正式货值结论；",
            "- 库龄仍保留 2026-06 期间口径，不与 2026-08-03 库存快照直接做守恒对账；",
            "- 页面不得把 `derived`、`estimated` 或 `unknown` 展示为客户原始事实。",
            "",
            "## 7. SQLite 示例",
            "",
            "```sql",
            "SELECT parent_asin, COUNT(*) AS days,",
            "       SUM(units_sold IS NOT NULL) AS units_nonnull_days",
            "FROM fact_parent_sales_daily",
            "GROUP BY parent_asin;",
            "```",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def build_source_lineage(
    selected_sources: dict[str, dict[str, Any]], inventory_coverage: list[dict[str, Any]]
) -> dict[str, Any]:
    daily_sources = sorted(
        {
            (source["relative_path"], source["sheet_name"])
            for source in selected_sources.values()
        }
    )
    return {
        "dataset_version": DATASET_VERSION,
        "source_root": str(SOURCE_ROOT),
        "sources": [
            {
                "relative_path": MONTHLY_FILE,
                "sheets": ["产品表现-ASIN", "产品表现-父ASIN", "FBA库存明细", STYLE_MONTHLY_SHEET],
                "usage": ["product hierarchy", "monthly sales", "inventory age", "style monthly attributes"],
            },
            {
                "relative_path": ATTRIBUTE_FILE,
                "sheets": [ATTRIBUTE_SHEET, "源数据1"],
                "usage": ["product attributes", "current inventory", "sales windows", "supply plan"],
            },
            {
                "relative_path": SHIPMENT_FILE,
                "sheets": [SHIPMENT_SHEET],
                "usage": ["shipment-level supply events", "actual or estimated ETA", "style volume anchor"],
            },
            *[
                {
                    "relative_path": source_file,
                    "sheets": [source_sheet],
                    "usage": ["direct unit cost anchor"],
                }
                for source_file, source_sheet in COST_SOURCES
            ],
            *[
                {
                    "relative_path": source_file,
                    "sheets": [source_sheet],
                    "usage": ["selected daily parent sales source"],
                }
                for source_file, source_sheet in daily_sources
            ],
        ],
        "daily_source_selection": {
            parent: {
                "relative_path": source["relative_path"],
                "sheet_name": source["sheet_name"],
                "min_date": source["min_date"],
                "max_date": source["max_date"],
                "nonnull_days": source["both_nonnull_days"],
            }
            for parent, source in selected_sources.items()
        },
        "parent_inventory_metric_coverage": inventory_coverage,
        "origin_rules": {
            "customer_actual": "direct source cell",
            "customer_actual_formula_cache": "saved workbook formula result with formula retained",
            "customer_actual_derived": "calculation within the same customer source record",
            "derived": "cross-record or cross-grain calculation",
            "estimated": "date or measure estimated from customer inputs",
            "unknown": "insufficient evidence",
        },
    }


def main() -> int:
    if not V010_ROOT.exists():
        raise RuntimeError(f"v0.1.0 不存在：{V010_ROOT}")
    v010_before = directory_hashes(V010_ROOT)
    index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    reader = CachedFormulaWorkbookReader(index)
    datasets = load_v010_datasets()

    selected_parents = [row["parent_asin"] for row in datasets["parent_selection.json"]]
    selected_parent_set = set(selected_parents)
    candidates = collect_daily_candidates(index, reader, selected_parent_set)
    if set(candidates) != selected_parent_set:
        raise RuntimeError("日销售候选源未覆盖全部选中父 ASIN")
    selected_sources = select_daily_sources(candidates)
    metric_sources = select_metric_sources(candidates)

    datasets["fact_parent_sales_daily.json"] = build_parent_daily_sales(
        selected_parents, selected_sources
    )
    inventory_daily, inventory_coverage = build_parent_inventory_daily(
        selected_parents, selected_sources, metric_sources
    )
    datasets["fact_parent_inventory_daily.json"] = inventory_daily
    update_parent_metadata(datasets, selected_sources)

    dim_child, attributes, bridge_parent_style, style_by_child = build_product_attributes(
        datasets, reader
    )
    datasets["dim_product_child.json"] = dim_child
    datasets["dim_product_attribute.json"] = attributes
    datasets["bridge_parent_style.json"] = bridge_parent_style
    selected_styles = {row["style_no"] for row in attributes if row.get("style_no")}
    datasets["fact_style_monthly_attribute.json"] = build_style_monthly_attributes(
        reader, selected_styles, selected_parent_set
    )
    supply_events = build_supply_events(reader, selected_styles, bridge_parent_style)
    datasets["fact_supply_event.json"] = supply_events
    economics = build_unit_economics(reader, dim_child, style_by_child, supply_events)
    datasets["fact_unit_economics.json"] = economics
    datasets["missing_field_matrix.json"] = build_missing_matrix(
        datasets["missing_field_matrix.json"], attributes, economics, supply_events
    )

    source_audit = public_source_audit(candidates, selected_sources, inventory_coverage)
    source_lineage = build_source_lineage(selected_sources, inventory_coverage)
    specs = dataset_specs()
    schema_catalog = {
        "dataset_version": DATASET_VERSION,
        "tables": {
            filename.removesuffix(".json"): {
                **specs[filename.removesuffix(".json")],
                "record_count": len(rows),
                "fields": list(rows[0]) if rows else [],
            }
            for filename, rows in sorted(datasets.items())
        },
    }

    if STAGING_ROOT.exists():
        shutil.rmtree(STAGING_ROOT)
    STAGING_ROOT.mkdir(parents=True)
    sqlite_path = STAGING_ROOT / "bamboocool_product_sales_inventory_v0.2.0.sqlite"
    sqlite_counts = create_sqlite(sqlite_path, datasets, specs)
    v010_after = directory_hashes(V010_ROOT)
    quality = build_quality_report(
        datasets, source_audit, sqlite_counts, v010_before, v010_after
    )
    if not quality["all_checks_passed"]:
        failed = [check["check"] for check in quality["checks"] if not check["passed"]]
        raise RuntimeError("v0.2.0 质量门禁未通过：" + ", ".join(failed))

    hashes = {}
    for filename, rows in sorted(datasets.items()):
        hashes[filename] = write_json(STAGING_ROOT / filename, rows)
    hashes["schema_catalog.json"] = write_json(STAGING_ROOT / "schema_catalog.json", schema_catalog)
    hashes["source_selection_audit.json"] = write_json(
        STAGING_ROOT / "source_selection_audit.json", source_audit
    )
    hashes["source_lineage.json"] = write_json(
        STAGING_ROOT / "source_lineage.json", source_lineage
    )
    hashes["quality_report.json"] = write_json(
        STAGING_ROOT / "quality_report.json", quality
    )
    write_readme(STAGING_ROOT / "README.md", datasets, quality)
    hashes["README.md"] = sha256_file(STAGING_ROOT / "README.md")
    hashes[sqlite_path.name] = sha256_file(sqlite_path)

    manifest = {
        "dataset_name": "bamboocool-product-sales-inventory-demo",
        "dataset_version": DATASET_VERSION,
        "generated_at": BUILD_TIMESTAMP,
        "as_of_date": AS_OF_DATE,
        "source_period": MONTHLY_SOURCE_PERIOD,
        "previous_version": "../v0.1.0",
        "previous_version_preserved": v010_before == v010_after,
        "data_nature": "mixed_source_fact_with_explicit_origin",
        "parent_count": len(selected_parents),
        "child_count": len(datasets["dim_product_child.json"]),
        "selected_parent_asins": selected_parents,
        "files": [
            {
                "name": filename,
                "sha256": digest,
                "record_count": len(datasets.get(filename, [])) if filename in datasets else None,
            }
            for filename, digest in sorted(hashes.items())
        ],
        "quality_checks_passed": True,
        "next_layer": [
            "supplemented child daily sales",
            "derived demand forecast",
            "derived inventory projection",
            "derived assessment history and five risk types",
        ],
    }
    write_json(STAGING_ROOT / "dataset-manifest.json", manifest)

    if OUTPUT_ROOT.exists():
        shutil.rmtree(OUTPUT_ROOT)
    STAGING_ROOT.rename(OUTPUT_ROOT)
    print(
        json.dumps(
            {
                "output": str(OUTPUT_ROOT),
                "parents": len(selected_parents),
                "children": len(datasets["dim_product_child.json"]),
                "daily_sales_rows": len(datasets["fact_parent_sales_daily.json"]),
                "supply_events": len(supply_events),
                "quality_checks": len(quality["checks"]),
                "all_checks_passed": quality["all_checks_passed"],
                "v0_1_0_preserved": v010_before == v010_after,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
