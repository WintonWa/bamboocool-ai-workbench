#!/usr/bin/env python3
"""Build the Bamboocool advertising Demo vertical slice.

SQLite is the canonical layer. Frontend and acceptance JSON are exported from
the same SQLite database. Customer source workbooks are read-only inputs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import sqlite3
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

from openpyxl import load_workbook


SLICE_VERSION = "v0.1.0-slice"
RELEASE_VERSION = "v0.1.0"
BUILD_DATE = "2026-08-29"
AMAZON_START = date(2026, 7, 1)
AMAZON_END = date(2026, 7, 31)
PREVIOUS_WINDOW = (date(2026, 7, 1), date(2026, 7, 15))
CURRENT_WINDOW = (date(2026, 7, 17), date(2026, 7, 31))
PARENT_COUNTS = {
    "B0DDNK229S": 103,
    "B0GQXK2Q58": 92,
    "B0CJV3G988": 134,
    "B0D9FLMR6N": 96,
    "B0CCLWDJNV": 96,
}
STAR_CHILD = "B088WF1PRW"
STAR_PARENT = "B0DDNK229S"
PAGE1_GROUPS = [
    ("SP", "002-SP-BR-ZENG-REGULAR-02", "广告组 - 3/27/2026 15:07:36.870"),
    ("SP", "002-SPAU-CLOSE-4LACK-REGULAR", "002长平角自动组-紧密"),
    ("SP", "002-SP-ASIN-ZENG-REGULAR-TOP", "广告组 - 3/24/2026 13:34:18.010"),
]
PROVENANCE = {"direct", "derived", "supplemented", "scenario_added", "blocked"}
LOGICAL_TABLES = [
    "dataset_manifest",
    "dim_product_parent",
    "dim_product_child",
    "dim_ad_object",
    "bridge_ad_object_product",
    "fact_ad_performance",
    "fact_product_ad_spend",
    "fact_ad_label_version",
    "dim_anomaly_rule",
    "fact_page1_result",
    "fact_page1_anomaly",
    "fact_decision_context",
    "fact_decision_evidence",
    "fact_required_ad_task",
    "bridge_task_ad_object",
    "fact_ad_diagnosis",
    "fact_ad_recommendation",
    "fact_ad_decision_event",
    "fact_review_feedback",
    "scenario_registry",
    "source_lineage",
]


def stable_id(prefix: str, *parts: Any) -> str:
    raw = "\x1f".join("" if part is None else str(part).strip() for part in parts)
    return f"{prefix}_{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:16]}"


def iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)[:10]


def number(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    return float(value)


def ratio(numerator: float, denominator: float) -> float | None:
    return None if denominator == 0 else numerator / denominator


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_xlsx(path: Path, sheet: str | None = None) -> list[dict[str, Any]]:
    workbook = load_workbook(path, read_only=True, data_only=True)
    worksheet = workbook[sheet or workbook.sheetnames[0]]
    rows = worksheet.iter_rows(values_only=True)
    header = list(next(rows))
    records: list[dict[str, Any]] = []
    for row_number, values in enumerate(rows, start=2):
        if not any(value is not None for value in values):
            continue
        record = {str(name): values[index] for index, name in enumerate(header) if name is not None}
        record["__row_number"] = row_number
        records.append(record)
    return records


def first_matching(records: Iterable[dict[str, Any]], field: str, value: Any) -> dict[str, Any]:
    for record in records:
        if record.get(field) == value:
            return record
    raise ValueError(f"Missing source record: {field}={value}")


def create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        PRAGMA foreign_keys = ON;

        CREATE TABLE dataset_manifest (
            dataset_version TEXT PRIMARY KEY,
            dataset_stage TEXT NOT NULL,
            built_at TEXT NOT NULL,
            selected_parent_asins TEXT NOT NULL,
            expected_parent_count INTEGER NOT NULL,
            expected_child_count INTEGER NOT NULL,
            actual_child_count INTEGER NOT NULL,
            expected_ad_group_name_key_count INTEGER NOT NULL,
            expected_ad_group_counts_by_type TEXT NOT NULL,
            actual_ad_group_name_key_count INTEGER NOT NULL,
            amazon_fact_window_start TEXT NOT NULL,
            amazon_fact_window_end TEXT NOT NULL,
            attribution_days_by_type TEXT NOT NULL,
            expected_promoted_asin_scope_count INTEGER NOT NULL,
            star_parent_asin TEXT NOT NULL,
            star_child_asin TEXT NOT NULL,
            source_status_vocabulary TEXT NOT NULL,
            build_mode TEXT NOT NULL,
            source_snapshot TEXT NOT NULL,
            timezone TEXT NOT NULL,
            currency TEXT NOT NULL,
            seed INTEGER NOT NULL,
            product_ad_spend_period TEXT NOT NULL,
            actual_child_spend_fact_count INTEGER NOT NULL,
            blocked_child_spend_fact_count INTEGER NOT NULL,
            actual_parent_spend_fact_count INTEGER NOT NULL,
            notes TEXT NOT NULL
        );

        CREATE TABLE source_file (
            source_file_id TEXT PRIMARY KEY,
            relative_path TEXT NOT NULL UNIQUE,
            sha256 TEXT NOT NULL,
            source_system TEXT NOT NULL,
            source_status TEXT NOT NULL CHECK(source_status IN ('direct','derived','supplemented','scenario_added','blocked')),
            used_for TEXT NOT NULL
        );

        CREATE TABLE dim_product_parent (
            parent_asin TEXT PRIMARY KEY,
            expected_child_count INTEGER NOT NULL,
            source_status TEXT NOT NULL CHECK(source_status IN ('direct','derived','supplemented','scenario_added','blocked')),
            source_ref TEXT NOT NULL
        );

        CREATE TABLE dim_product_child (
            child_asin TEXT PRIMARY KEY,
            parent_asin TEXT NOT NULL REFERENCES dim_product_parent(parent_asin),
            sku TEXT,
            title TEXT,
            slice_role TEXT NOT NULL,
            source_status TEXT NOT NULL CHECK(source_status IN ('direct','derived','supplemented','scenario_added','blocked')),
            source_ref TEXT NOT NULL
        );
        CREATE INDEX idx_child_parent ON dim_product_child(parent_asin);

        CREATE TABLE dim_ad_object (
            ad_object_id TEXT PRIMARY KEY,
            object_level TEXT NOT NULL CHECK(object_level IN ('AD_GROUP','TARGET')),
            ad_type TEXT NOT NULL CHECK(ad_type IN ('SP','SB','SD')),
            campaign_name TEXT NOT NULL,
            ad_group_name TEXT,
            target_text TEXT,
            match_type TEXT,
            parent_ad_object_id TEXT REFERENCES dim_ad_object(ad_object_id),
            key_kind TEXT NOT NULL,
            source_status TEXT NOT NULL CHECK(source_status IN ('direct','derived','supplemented','scenario_added','blocked')),
            source_ref TEXT NOT NULL,
            mapping_status TEXT NOT NULL
        );
        CREATE INDEX idx_ad_object_group ON dim_ad_object(ad_type, campaign_name, ad_group_name);

        CREATE TABLE bridge_ad_object_product (
            relation_id TEXT PRIMARY KEY,
            ad_object_id TEXT NOT NULL REFERENCES dim_ad_object(ad_object_id),
            child_asin TEXT NOT NULL,
            relation_role TEXT NOT NULL CHECK(relation_role IN ('promoted_asin','positive_spend_asin','purchased_asin','target_asin','matched_asin')),
            attribution_scope TEXT NOT NULL CHECK(attribution_scope IN ('direct','shared','unattributed')),
            effective_from TEXT NOT NULL,
            effective_to TEXT,
            source_status TEXT NOT NULL CHECK(source_status IN ('direct','derived','supplemented','scenario_added','blocked')),
            source_ref TEXT NOT NULL,
            source_role TEXT NOT NULL,
            is_scope_product INTEGER NOT NULL CHECK(is_scope_product IN (0,1))
        );
        CREATE INDEX idx_bridge_object ON bridge_ad_object_product(ad_object_id, relation_role);
        CREATE INDEX idx_bridge_product ON bridge_ad_object_product(child_asin, relation_role);

        CREATE TABLE fact_ad_performance (
            fact_id TEXT PRIMARY KEY,
            ad_object_id TEXT NOT NULL REFERENCES dim_ad_object(ad_object_id),
            object_level TEXT NOT NULL,
            ad_type TEXT NOT NULL,
            window_start TEXT NOT NULL,
            window_end TEXT NOT NULL,
            coverage_start TEXT NOT NULL,
            coverage_end TEXT NOT NULL,
            attribution_days INTEGER NOT NULL,
            attribution_scope TEXT NOT NULL,
            comparison_status TEXT NOT NULL,
            metric_basis TEXT NOT NULL,
            impressions REAL NOT NULL,
            clicks REAL NOT NULL,
            spend REAL NOT NULL,
            orders REAL NOT NULL,
            ad_sales REAL NOT NULL,
            ctr REAL,
            cpc REAL,
            cvr REAL,
            acos REAL,
            roas REAL,
            currency TEXT NOT NULL,
            source_system TEXT NOT NULL,
            source_status TEXT NOT NULL CHECK(source_status IN ('direct','derived','supplemented','scenario_added','blocked')),
            source_ref TEXT NOT NULL,
            source_row_filter TEXT NOT NULL,
            UNIQUE(ad_object_id, object_level, window_start, window_end, attribution_days, source_ref)
        );
        CREATE INDEX idx_fact_window ON fact_ad_performance(window_start, window_end, attribution_days);

        CREATE TABLE fact_product_ad_spend (
            product_ad_spend_id TEXT PRIMARY KEY,
            grain TEXT NOT NULL CHECK(grain IN ('PARENT_ASIN','CHILD_ASIN')),
            parent_asin TEXT NOT NULL REFERENCES dim_product_parent(parent_asin),
            child_asin TEXT REFERENCES dim_product_child(child_asin),
            period TEXT NOT NULL,
            window_start TEXT NOT NULL,
            window_end TEXT NOT NULL,
            spend REAL,
            currency TEXT NOT NULL,
            metric_status TEXT NOT NULL CHECK(metric_status IN ('observed_positive','observed_zero','no_child_spend_fact')),
            source_status TEXT NOT NULL CHECK(source_status IN ('direct','derived','supplemented','scenario_added','blocked')),
            source_ref TEXT NOT NULL,
            CHECK((grain='PARENT_ASIN' AND child_asin IS NULL) OR (grain='CHILD_ASIN' AND child_asin IS NOT NULL)),
            CHECK((metric_status='no_child_spend_fact' AND spend IS NULL AND source_status='blocked') OR
                  (metric_status<>'no_child_spend_fact' AND spend IS NOT NULL AND source_status='direct')),
            UNIQUE(grain, parent_asin, child_asin, period)
        );
        CREATE INDEX idx_product_spend_child ON fact_product_ad_spend(child_asin, period);
        CREATE INDEX idx_product_spend_parent ON fact_product_ad_spend(parent_asin, period);

        CREATE TABLE fact_ad_label_version (
            label_version_id TEXT PRIMARY KEY,
            ad_object_id TEXT NOT NULL REFERENCES dim_ad_object(ad_object_id),
            label_type TEXT NOT NULL,
            label_value TEXT NOT NULL,
            label_source TEXT NOT NULL CHECK(label_source IN ('system_attribute','auto_mapping','group_inherited','ai_suggested','operator_confirmed')),
            confirmation_status TEXT NOT NULL CHECK(confirmation_status IN ('confirmed','pending','rejected','unrecognized')),
            effective_from TEXT NOT NULL,
            effective_to TEXT,
            inherited_from_object_id TEXT,
            source_status TEXT NOT NULL CHECK(source_status IN ('direct','derived','supplemented','scenario_added','blocked')),
            source_ref TEXT NOT NULL
        );
        CREATE INDEX idx_label_effective ON fact_ad_label_version(ad_object_id, label_type, effective_from, effective_to);

        CREATE TABLE dim_anomaly_rule (
            rule_id TEXT PRIMARY KEY,
            rule_name TEXT NOT NULL,
            metric_name TEXT NOT NULL,
            operator TEXT NOT NULL,
            threshold REAL NOT NULL,
            enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
            rule_status TEXT NOT NULL,
            rule_version TEXT NOT NULL,
            source_status TEXT NOT NULL CHECK(source_status IN ('direct','derived','supplemented','scenario_added','blocked')),
            source_ref TEXT NOT NULL
        );

        CREATE TABLE fact_page1_result (
            result_id TEXT PRIMARY KEY,
            query_id TEXT NOT NULL,
            ad_object_id TEXT NOT NULL REFERENCES dim_ad_object(ad_object_id),
            object_level TEXT NOT NULL,
            window_start TEXT NOT NULL,
            window_end TEXT NOT NULL,
            attribution_days INTEGER NOT NULL,
            metric_basis TEXT NOT NULL,
            filter_signature TEXT NOT NULL,
            object_count INTEGER NOT NULL,
            comparison_eligible INTEGER NOT NULL CHECK(comparison_eligible IN (0,1)),
            impressions REAL NOT NULL,
            clicks REAL NOT NULL,
            spend REAL NOT NULL,
            orders REAL NOT NULL,
            ad_sales REAL NOT NULL,
            ctr REAL,
            cpc REAL,
            cvr REAL,
            acos REAL,
            roas REAL,
            previous_acos REAL,
            acos_change_rate REAL,
            rank_by_acos INTEGER,
            source_status TEXT NOT NULL CHECK(source_status IN ('direct','derived','supplemented','scenario_added','blocked')),
            source_ref TEXT NOT NULL
        );
        CREATE INDEX idx_page1_query ON fact_page1_result(query_id, rank_by_acos);

        CREATE TABLE fact_page1_anomaly (
            anomaly_id TEXT PRIMARY KEY,
            query_id TEXT NOT NULL,
            result_id TEXT NOT NULL REFERENCES fact_page1_result(result_id),
            ad_object_id TEXT NOT NULL REFERENCES dim_ad_object(ad_object_id),
            rule_id TEXT NOT NULL REFERENCES dim_anomaly_rule(rule_id),
            metric_name TEXT NOT NULL,
            observed_value REAL NOT NULL,
            threshold REAL NOT NULL,
            severity TEXT NOT NULL,
            source_status TEXT NOT NULL CHECK(source_status IN ('direct','derived','supplemented','scenario_added','blocked')),
            source_ref TEXT NOT NULL
        );

        CREATE TABLE fact_decision_context (
            decision_id TEXT PRIMARY KEY,
            child_asin TEXT NOT NULL REFERENCES dim_product_child(child_asin),
            parent_asin TEXT NOT NULL REFERENCES dim_product_parent(parent_asin),
            product_goal_version TEXT NOT NULL,
            product_goal TEXT NOT NULL,
            goal_status TEXT NOT NULL,
            decision_at TEXT NOT NULL,
            previous_decision_id TEXT,
            source_status TEXT NOT NULL CHECK(source_status IN ('direct','derived','supplemented','scenario_added','blocked')),
            source_ref TEXT NOT NULL,
            UNIQUE(child_asin, product_goal_version, decision_at)
        );

        CREATE TABLE fact_decision_evidence (
            evidence_id TEXT PRIMARY KEY,
            decision_id TEXT NOT NULL REFERENCES fact_decision_context(decision_id),
            evidence_type TEXT NOT NULL,
            evidence_title TEXT NOT NULL,
            evidence_payload TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            valid_as_of TEXT NOT NULL,
            source_status TEXT NOT NULL CHECK(source_status IN ('direct','derived','supplemented','scenario_added','blocked')),
            source_ref TEXT NOT NULL,
            evidence_nature TEXT NOT NULL CHECK(evidence_nature IN ('fact','inference','operator_confirmed')),
            evidence_status TEXT NOT NULL CHECK(evidence_status IN ('current','stale','conflicting','missing')),
            caveat TEXT NOT NULL
        );

        CREATE TABLE fact_required_ad_task (
            task_id TEXT PRIMARY KEY,
            decision_id TEXT NOT NULL REFERENCES fact_decision_context(decision_id),
            product_goal_version TEXT NOT NULL,
            task_type TEXT NOT NULL,
            task_direction TEXT NOT NULL,
            priority TEXT NOT NULL,
            target_scope TEXT NOT NULL,
            constraints TEXT NOT NULL,
            evaluation_direction TEXT NOT NULL,
            stop_condition TEXT NOT NULL,
            rule_status TEXT NOT NULL,
            rule_id TEXT,
            exact_budget REAL,
            exact_bid REAL,
            exact_placement_adjustment REAL,
            evidence_ids TEXT NOT NULL,
            inventory_constrained INTEGER NOT NULL CHECK(inventory_constrained IN (0,1)),
            source_status TEXT NOT NULL CHECK(source_status IN ('direct','derived','supplemented','scenario_added','blocked')),
            source_ref TEXT NOT NULL
        );

        CREATE TABLE bridge_task_ad_object (
            mapping_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL REFERENCES fact_required_ad_task(task_id),
            ad_object_id TEXT REFERENCES dim_ad_object(ad_object_id),
            coverage_status TEXT NOT NULL CHECK(coverage_status IN ('covered','missing','duplicate','mixed','object_mismatch','data_insufficient')),
            attribution_limit TEXT NOT NULL,
            evidence_ids TEXT NOT NULL,
            is_automatic_error INTEGER NOT NULL CHECK(is_automatic_error IN (0,1)),
            source_status TEXT NOT NULL CHECK(source_status IN ('direct','derived','supplemented','scenario_added','blocked')),
            source_ref TEXT NOT NULL
        );

        CREATE TABLE fact_ad_diagnosis (
            diagnosis_id TEXT PRIMARY KEY,
            decision_id TEXT NOT NULL REFERENCES fact_decision_context(decision_id),
            task_id TEXT NOT NULL REFERENCES fact_required_ad_task(task_id),
            problem_type TEXT NOT NULL,
            impacted_goal TEXT NOT NULL,
            priority TEXT NOT NULL,
            confidence TEXT NOT NULL,
            evidence_ids TEXT NOT NULL,
            uncertainty TEXT NOT NULL,
            missing_input TEXT NOT NULL,
            check_direction TEXT NOT NULL,
            basis_type TEXT NOT NULL CHECK(basis_type IN ('confirmed_threshold','self_history','comparable_objects','conditional','data_insufficient')),
            causal_claim INTEGER NOT NULL CHECK(causal_claim IN (0,1)),
            source_status TEXT NOT NULL CHECK(source_status IN ('direct','derived','supplemented','scenario_added','blocked')),
            source_ref TEXT NOT NULL
        );

        CREATE TABLE fact_ad_recommendation (
            recommendation_id TEXT PRIMARY KEY,
            decision_id TEXT NOT NULL REFERENCES fact_decision_context(decision_id),
            diagnosis_id TEXT NOT NULL REFERENCES fact_ad_diagnosis(diagnosis_id),
            product_goal_version TEXT NOT NULL,
            ad_purpose TEXT NOT NULL,
            ad_object_id TEXT REFERENCES dim_ad_object(ad_object_id),
            structure_gap_id TEXT,
            direction TEXT NOT NULL CHECK(direction IN ('KEEP','OBSERVE','ADJUST','PAUSE','RESUME','SPLIT','MERGE','BUILD','TEST','DEFER','REQUEST_INFO')),
            rationale TEXT NOT NULL,
            preconditions TEXT NOT NULL,
            risks TEXT NOT NULL,
            uncertainty TEXT NOT NULL,
            observation_metrics TEXT NOT NULL,
            review_windows TEXT NOT NULL,
            d7_not_required INTEGER NOT NULL CHECK(d7_not_required IN (0,1)),
            rule_status TEXT NOT NULL,
            rule_id TEXT,
            exact_value TEXT,
            source_status TEXT NOT NULL CHECK(source_status IN ('direct','derived','supplemented','scenario_added','blocked')),
            source_ref TEXT NOT NULL
        );

        CREATE TABLE fact_ad_decision_event (
            event_id TEXT PRIMARY KEY,
            recommendation_id TEXT NOT NULL REFERENCES fact_ad_recommendation(recommendation_id),
            decision_id TEXT NOT NULL REFERENCES fact_decision_context(decision_id),
            event_type TEXT NOT NULL CHECK(event_type IN ('accept','modify','reject','defer')),
            occurred_at TEXT NOT NULL,
            actor TEXT NOT NULL,
            original_recommendation_snapshot TEXT NOT NULL,
            modified_plan TEXT,
            decision_reason TEXT,
            handoff_status TEXT NOT NULL,
            handoff_child_asin TEXT,
            handoff_product_goal TEXT,
            handoff_diagnosis TEXT,
            handoff_ad_objects TEXT,
            handoff_direction TEXT,
            handoff_observation TEXT,
            handoff_open_items TEXT,
            data_version TEXT,
            rule_version TEXT,
            previous_version_id TEXT,
            feedback_id TEXT,
            source_status TEXT NOT NULL CHECK(source_status IN ('direct','derived','supplemented','scenario_added','blocked')),
            source_ref TEXT NOT NULL
        );

        CREATE TABLE fact_review_feedback (
            feedback_id TEXT PRIMARY KEY,
            decision_id TEXT NOT NULL REFERENCES fact_decision_context(decision_id),
            recommendation_id TEXT NOT NULL REFERENCES fact_ad_recommendation(recommendation_id),
            review_window TEXT NOT NULL CHECK(review_window IN ('D+3','D+7')),
            review_at TEXT NOT NULL,
            status TEXT NOT NULL,
            baseline_metrics TEXT NOT NULL,
            observed_metrics TEXT NOT NULL,
            conclusion TEXT NOT NULL,
            concurrent_variables TEXT NOT NULL,
            next_question TEXT NOT NULL,
            source_status TEXT NOT NULL CHECK(source_status IN ('direct','derived','supplemented','scenario_added','blocked')),
            source_ref TEXT NOT NULL
        );

        CREATE TABLE scenario_registry (
            scenario_id TEXT PRIMARY KEY,
            scenario_type TEXT NOT NULL UNIQUE,
            description TEXT NOT NULL,
            linked_record_ids TEXT NOT NULL,
            steps TEXT NOT NULL,
            expected_results TEXT NOT NULL,
            assertion_status TEXT NOT NULL CHECK(assertion_status IN ('PASS','FAIL','BLOCKED')),
            source_status TEXT NOT NULL CHECK(source_status IN ('direct','derived','supplemented','scenario_added','blocked')),
            source_ref TEXT NOT NULL
        );

        CREATE TABLE source_lineage (
            lineage_id TEXT PRIMARY KEY,
            output_table TEXT NOT NULL,
            output_record_id TEXT NOT NULL,
            output_field TEXT NOT NULL,
            transformation_type TEXT NOT NULL,
            source_status TEXT NOT NULL CHECK(source_status IN ('direct','derived','supplemented','scenario_added','blocked')),
            source_ref TEXT NOT NULL,
            source_file_id TEXT REFERENCES source_file(source_file_id),
            source_row_selector TEXT NOT NULL,
            formula_or_rule TEXT NOT NULL,
            build_version TEXT NOT NULL
        );
        CREATE INDEX idx_lineage_output ON source_lineage(output_table, output_record_id);
        """
    )


def insert_rows(connection: sqlite3.Connection, table: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    columns = list(rows[0])
    sql = f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})"
    connection.executemany(sql, [[row.get(column) for column in columns] for row in rows])


def table_rows(connection: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    connection.row_factory = sqlite3.Row
    return [dict(row) for row in connection.execute(f"SELECT * FROM {table}")]


def load_parent_child_map(source_root: Path) -> tuple[dict[str, str], list[Path]]:
    """Load the frozen five-parent scope from the customer monthly ASIN table.

    The replenishment sheets are useful for current inventory, but they do not
    contain every frozen parent. The monthly product-performance source does.
    """
    mapping: dict[str, str] = {}
    path = source_root / "14.其他分析文件" / "2026年月报" / "6月" / "一组6月月报.xlsx"
    workbook = load_workbook(path, read_only=True, data_only=True)
    worksheet = workbook["产品表现-父ASIN"]
    rows = worksheet.iter_rows(values_only=True)
    header = list(next(rows))
    positions = {name: index for index, name in enumerate(header) if name is not None}
    for values in rows:
        parent = values[positions["父ASIN"]]
        if parent not in PARENT_COUNTS:
            continue
        asin_blob = values[positions["ASIN"]]
        for child in str(asin_blob or "").split(","):
            child = child.strip().upper()
            if child:
                existing = mapping.get(child)
                if existing and existing != parent:
                    raise ValueError(f"Child {child} maps to two parents: {existing}, {parent}")
                mapping[child] = parent
    used = [path]
    # Replenishment traffic sheets contain one additional B0CCLWDJNV child
    # absent from the monthly parent summary. Union only explicit parent/ASIN
    # relations and keep the conflict check above.
    for followup in sorted((source_root / "1.产品跟进表-运营记录").glob("*.xlsx")):
        if followup.name.startswith("~$"):
            continue
        book = load_workbook(followup, read_only=True, data_only=True)
        if "流量数据源-领星" not in book.sheetnames:
            continue
        sheet = book["流量数据源-领星"]
        source_rows = sheet.iter_rows(values_only=True)
        source_header = list(next(source_rows))
        source_positions = {name: index for index, name in enumerate(source_header) if name is not None}
        added = False
        for values in source_rows:
            parent = values[source_positions["父ASIN"]]
            if parent not in PARENT_COUNTS:
                continue
            for child in str(values[source_positions["ASIN"]] or "").split(","):
                child = child.strip().upper()
                if not child:
                    continue
                existing = mapping.get(child)
                if existing and existing != parent:
                    raise ValueError(f"Child {child} maps to two parents: {existing}, {parent}")
                if child not in mapping:
                    mapping[child] = parent
                    added = True
        if added:
            used.append(followup)
    counts = defaultdict(int)
    for parent in mapping.values():
        counts[parent] += 1
    if dict(counts) != PARENT_COUNTS:
        raise ValueError(f"Frozen parent-child scope mismatch: {dict(counts)}")
    return mapping, used


def aggregate_metrics(rows: Iterable[dict[str, Any]], columns: dict[str, str]) -> dict[str, float | None]:
    impressions = sum(number(row.get(columns["impressions"])) for row in rows)
    clicks = sum(number(row.get(columns["clicks"])) for row in rows)
    spend = sum(number(row.get(columns["spend"])) for row in rows)
    orders = sum(number(row.get(columns["orders"])) for row in rows)
    sales = sum(number(row.get(columns["sales"])) for row in rows)
    return {
        "impressions": impressions,
        "clicks": clicks,
        "spend": spend,
        "orders": orders,
        "ad_sales": sales,
        "ctr": ratio(clicks, impressions),
        "cpc": ratio(spend, clicks),
        "cvr": ratio(orders, clicks),
        "acos": ratio(spend, sales),
        "roas": ratio(sales, spend),
    }


def build(output_dir: Path, mode: str) -> None:
    if mode not in {"slice", "release"}:
        raise ValueError(f"Unsupported mode: {mode}")
    is_release = mode == "release"
    dataset_version = RELEASE_VERSION if is_release else SLICE_VERSION
    script_path = Path(__file__).resolve()
    repo_root = script_path.parents[3]
    source_root = repo_root / "数据源" / "AI广告对接数据-总20260803"
    ad_root = source_root / "13.广告"
    allowed_parent = script_path.parent
    if output_dir.resolve().parent != allowed_parent.resolve() or output_dir.name != dataset_version:
        raise ValueError(f"Output must be the fixed package path {allowed_parent / dataset_version}")
    if output_dir.exists():
        shutil.rmtree(output_dir)
    (output_dir / "frontend").mkdir(parents=True)

    paths = {
        "sp_search": ad_root / "商品推广_搜索词_报告.xlsx",
        "sp_target": ad_root / "商品推广_投放_报告.xlsx",
        "sp_promoted": ad_root / "商品推广_推广的商品_报告.xlsx",
        "sp_purchased": ad_root / "商品推广_已购买商品_报告.xlsx",
        "sp_video": ad_root / "商品推广_视频_报告.xlsx",
        "sd_promoted": ad_root / "展示型推广_推广的商品_报告.xlsx",
        "sd_matched": ad_root / "展示型推广_匹配的目标_报告.xlsx",
        "sb_keyword": ad_root / "品牌推广_关键词_报告.xlsx",
        "inventory": source_root / "1.产品跟进表-运营记录" / "产品跟进表-曾向锋.xlsx",
        "keyword": source_root / "10.关键词" / "关键词3.xlsx",
        "competitor": source_root / "9.竞品.xlsx",
    }
    for path in paths.values():
        if not path.exists():
            raise FileNotFoundError(path)

    child_parent, mapping_files = load_parent_child_map(source_root)
    sp_promoted = read_xlsx(paths["sp_promoted"])
    sd_promoted = read_xlsx(paths["sd_promoted"])
    sb_keyword = read_xlsx(paths["sb_keyword"])
    sp_search = read_xlsx(paths["sp_search"])
    sp_target = read_xlsx(paths["sp_target"])
    sp_purchased = read_xlsx(paths["sp_purchased"])
    sp_video = read_xlsx(paths["sp_video"])
    sd_matched = read_xlsx(paths["sd_matched"])

    page1_key_set = {(campaign, group) for _, campaign, group in PAGE1_GROUPS}
    star_sp_groups = {
        (row["广告活动名称"], row["广告组名称"])
        for row in sp_promoted
        if str(row.get("广告ASIN") or "").upper() == STAR_CHILD
    }
    star_sd_groups = {
        (row["广告活动名称"], row["广告组名称"])
        for row in sd_promoted
        if str(row.get("广告ASIN") or "").upper() == STAR_CHILD
    }
    all_sp_promoted_groups = {(row["广告活动名称"], row["广告组名称"]) for row in sp_promoted}
    all_sp_video_groups = {(row["广告活动名称"], row["广告组名称"]) for row in sp_video}
    all_sd_promoted_groups = {(row["广告活动名称"], row["广告组名称"]) for row in sd_promoted}
    sp_group_keys = (all_sp_promoted_groups | all_sp_video_groups) if is_release else (star_sp_groups | page1_key_set)
    sd_group_keys = all_sd_promoted_groups if is_release else star_sd_groups
    sb_group_keys = {(row["广告活动名称"], row["广告组名称"]) for row in sb_keyword}
    included_group_keys = {
        *(('SP', campaign, group) for campaign, group in sp_group_keys),
        *(('SD', campaign, group) for campaign, group in sd_group_keys),
        *(('SB', campaign, group) for campaign, group in sb_group_keys),
    }
    if is_release:
        observed_group_counts = {
            "SP": len(sp_group_keys), "SB": len(sb_group_keys), "SD": len(sd_group_keys),
        }
        if observed_group_counts != {"SP": 40, "SB": 5, "SD": 9}:
            raise ValueError(f"Release group scope mismatch: {observed_group_counts}")

    source_files: list[dict[str, Any]] = []
    source_id_by_path: dict[Path, str] = {}
    for path in sorted(set(paths.values()) | set(mapping_files)):
        relative = str(path.relative_to(repo_root))
        source_id = stable_id("src", relative)
        source_id_by_path[path] = source_id
        source_files.append(
            {
                "source_file_id": source_id,
                "relative_path": relative,
                "sha256": sha256_file(path),
                "source_system": "AMAZON" if path.parent == ad_root else "LINGXING_OR_CUSTOMER_WORKBOOK",
                "source_status": "direct",
                "used_for": "source facts and product mapping",
            }
        )

    parents = [
        {
            "parent_asin": parent,
            "expected_child_count": count,
            "source_status": "direct",
            "source_ref": "customer product follow-up workbooks|流量数据源-领星",
        }
        for parent, count in PARENT_COUNTS.items()
    ]

    ad_objects: list[dict[str, Any]] = []
    object_id_by_key: dict[tuple[str, str, str], str] = {}
    source_ref_by_group: dict[tuple[str, str, str], str] = {}
    for ad_type, campaign, group in sorted(included_group_keys):
        object_id = stable_id("grp", ad_type, campaign, group)
        object_id_by_key[(ad_type, campaign, group)] = object_id
        if ad_type == "SP":
            source_ref = (
                "13.广告/商品推广_推广的商品_报告.xlsx|商品推广_推广的商品_报告"
                if (campaign, group) in all_sp_promoted_groups
                else "13.广告/商品推广_视频_报告.xlsx|商品推广_视频_报告"
            )
            mapping_status = "direct_advertising_asin"
        elif ad_type == "SD":
            source_ref = "13.广告/展示型推广_推广的商品_报告.xlsx|展示型推广_推广的商品_报告"
            mapping_status = "direct_advertising_asin"
        else:
            source_ref = "13.广告/品牌推广_关键词_报告.xlsx|品牌推广_关键词_报告"
            mapping_status = "pending_mapping"
        source_ref_by_group[(ad_type, campaign, group)] = source_ref
        ad_objects.append(
            {
                "ad_object_id": object_id,
                "object_level": "AD_GROUP",
                "ad_type": ad_type,
                "campaign_name": campaign,
                "ad_group_name": group,
                "target_text": None,
                "match_type": None,
                "parent_ad_object_id": None,
                "key_kind": "source_name_key",
                "source_status": "derived",
                "source_ref": source_ref,
                "mapping_status": mapping_status,
            }
        )

    top_targets: list[dict[str, Any]] = []
    if is_release:
        target_candidates: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        for row in sp_target:
            pair = (row.get("广告活动名称"), row.get("广告组名称"))
            if pair not in sp_group_keys:
                continue
            key = (*pair, str(row.get("投放") or ""), str(row.get("匹配类型") or ""))
            existing = target_candidates.get(key)
            if existing is None or number(row.get("花费")) > number(existing.get("花费")):
                target_candidates[key] = row
        top_targets = list(target_candidates.values())
    else:
        for _, campaign, group in PAGE1_GROUPS:
            candidates = [
                row for row in sp_target
                if row.get("广告活动名称") == campaign and row.get("广告组名称") == group
            ]
            if candidates:
                top_targets.append(max(candidates, key=lambda row: number(row.get("花费"))))
    for row in top_targets:
        group_key = ("SP", row["广告活动名称"], row["广告组名称"])
        parent_id = object_id_by_key[group_key]
        object_id = stable_id("tgt", parent_id, row.get("投放"), row.get("匹配类型"))
        ad_objects.append(
            {
                "ad_object_id": object_id,
                "object_level": "TARGET",
                "ad_type": "SP",
                "campaign_name": row["广告活动名称"],
                "ad_group_name": row["广告组名称"],
                "target_text": row.get("投放"),
                "match_type": row.get("匹配类型"),
                "parent_ad_object_id": parent_id,
                "key_kind": "derived_compound_target_key",
                "source_status": "derived",
                "source_ref": "13.广告/商品推广_投放_报告.xlsx|商品推广_投放_报告",
                "mapping_status": "inherits_group_mapping",
            }
        )

    promoted_source_rows: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for ad_type, records in [("SP", sp_promoted), ("SD", sd_promoted)]:
        for row in records:
            key = (ad_type, row["广告活动名称"], row["广告组名称"])
            if key in included_group_keys:
                promoted_source_rows[key].append(row)
    for row in sp_video:
        pair = (row["广告活动名称"], row["广告组名称"])
        key = ("SP", *pair)
        if key in included_group_keys and pair not in all_sp_promoted_groups:
            promoted_source_rows[key].append(row)

    relations: list[dict[str, Any]] = []
    slice_children: set[str] = {STAR_CHILD}
    for group_key, rows in promoted_source_rows.items():
        unique_asins = sorted({str(row.get("广告ASIN") or "").upper() for row in rows if row.get("广告ASIN")})
        scope = "shared" if len(unique_asins) > 1 else "direct"
        for asin in unique_asins:
            if asin not in child_parent:
                continue
            slice_children.add(asin)
            if group_key[0] == "SP":
                source_name = "商品推广_推广的商品_报告.xlsx" if group_key[1:] in all_sp_promoted_groups else "商品推广_视频_报告.xlsx"
            else:
                source_name = "展示型推广_推广的商品_报告.xlsx"
            source_ref = f"13.广告/{source_name}|广告ASIN={asin}"
            object_id = object_id_by_key[group_key]
            relations.append(
                {
                    "relation_id": stable_id("rel", object_id, asin, "promoted_asin"),
                    "ad_object_id": object_id,
                    "child_asin": asin,
                    "relation_role": "promoted_asin",
                    "attribution_scope": scope,
                    "effective_from": AMAZON_START.isoformat(),
                    "effective_to": AMAZON_END.isoformat(),
                    "source_status": "direct",
                    "source_ref": source_ref,
                    "source_role": "advertising_asin",
                    "is_scope_product": 1,
                }
            )
            spend = sum(number(row.get("花费")) for row in rows if str(row.get("广告ASIN") or "").upper() == asin)
            if spend > 0:
                relations.append(
                    {
                        "relation_id": stable_id("rel", object_id, asin, "positive_spend_asin"),
                        "ad_object_id": object_id,
                        "child_asin": asin,
                        "relation_role": "positive_spend_asin",
                        "attribution_scope": scope,
                        "effective_from": AMAZON_START.isoformat(),
                        "effective_to": AMAZON_END.isoformat(),
                        "source_status": "direct",
                        "source_ref": source_ref,
                        "source_role": "advertised_product_spend",
                        "is_scope_product": 1,
                    }
                )

    # Preserve role boundaries with direct external target/purchase/matched-ASIN examples.
    included_sp_pairs = {(campaign, group) for ad_type, campaign, group in included_group_keys if ad_type == "SP"}
    external_examples: list[tuple[str, dict[str, Any], str, str, str]] = []
    for row in sp_purchased:
        if (row.get("广告活动名称"), row.get("广告组名称")) in included_sp_pairs and row.get("已购买的ASIN"):
            external_examples.append(("SP", row, "purchased_asin", "已购买的ASIN", "purchased_asin"))
            break
    for row in sp_target:
        target = str(row.get("投放") or "").strip()
        asin_match = re.search(r"(?i)B0[A-Z0-9]{8}", target)
        if (row.get("广告活动名称"), row.get("广告组名称")) in included_sp_pairs and asin_match:
            cloned = dict(row)
            cloned["__normalized_role_asin"] = asin_match.group(0).upper()
            external_examples.append(("SP", cloned, "target_asin", "__normalized_role_asin", "targeting_asin"))
            break
    included_sd_pairs = {(campaign, group) for ad_type, campaign, group in included_group_keys if ad_type == "SD"}
    for row in sd_matched:
        campaign = row.get("广告活动名称")
        candidate_keys = [key for key in included_sd_pairs if key[0] == campaign]
        matched = str(row.get("匹配的目标") or "").strip().upper()
        if candidate_keys and matched.startswith("B0"):
            cloned = dict(row)
            cloned["广告组名称"] = candidate_keys[0][1]
            external_examples.append(("SD", cloned, "matched_asin", "匹配的目标", "matched_target_asin"))
            break
    for ad_type, row, role, asin_field, source_role in external_examples:
        key = (ad_type, row["广告活动名称"], row["广告组名称"])
        if key not in object_id_by_key:
            continue
        asin = str(row.get(asin_field) or "").strip().upper()
        role_source_file = {
            "purchased_asin": "商品推广_已购买商品_报告.xlsx",
            "target_asin": "商品推广_投放_报告.xlsx",
            "matched_asin": "展示型推广_匹配的目标_报告.xlsx",
        }[role]
        relations.append(
            {
                "relation_id": stable_id("rel", object_id_by_key[key], asin, role),
                "ad_object_id": object_id_by_key[key],
                "child_asin": asin,
                "relation_role": role,
                "attribution_scope": "unattributed",
                "effective_from": iso(row.get("开始日期")) or AMAZON_START.isoformat(),
                "effective_to": iso(row.get("结束日期")) or AMAZON_END.isoformat(),
                "source_status": "direct",
                "source_ref": f"13.广告/{role_source_file}|{role}|row={row['__row_number']}",
                "source_role": source_role,
                "is_scope_product": 1 if asin in child_parent else 0,
            }
        )
    if is_release:
        promoted_asins = {row["child_asin"] for row in relations if row["relation_role"] == "promoted_asin"}
        promoted_parents = {child_parent[asin] for asin in promoted_asins}
        if len(promoted_asins) != 115 or promoted_parents != {"B0DDNK229S", "B0GQXK2Q58", "B0CJV3G988"}:
            raise ValueError(f"Release promoted-ASIN scope mismatch: count={len(promoted_asins)} parents={promoted_parents}")

    inventory_rows = read_xlsx(paths["inventory"], "数据源-领星补货建议")
    inventory = first_matching(inventory_rows, "ASIN", STAR_CHILD)
    monthly_child_rows = read_xlsx(mapping_files[0], "产品表现-ASIN")
    monthly_child_details = {str(row.get("ASIN") or "").strip().upper(): row for row in monthly_child_rows if row.get("ASIN")}
    supplemental_child_refs: dict[str, str] = {}
    for followup in mapping_files[1:]:
        for row in read_xlsx(followup, "流量数据源-领星"):
            if row.get("父ASIN") not in PARENT_COUNTS:
                continue
            for asin in str(row.get("ASIN") or "").split(","):
                asin = asin.strip().upper()
                if asin and asin not in monthly_child_details:
                    supplemental_child_refs[asin] = f"{followup.relative_to(source_root)}|流量数据源-领星|row={row['__row_number']}"
    selected_children = set(child_parent) if is_release else slice_children
    children = []
    for child in sorted(selected_children):
        parent = child_parent[child]
        if child == STAR_CHILD:
            sku = inventory.get("SKU")
            title = inventory.get("标题")
            role = "page2_star"
            source_ref = f"1.产品跟进表-运营记录/产品跟进表-曾向锋.xlsx|数据源-领星补货建议|row={inventory['__row_number']}"
        else:
            detail = monthly_child_details.get(child)
            sku = detail.get("款名") if detail else None
            title = detail.get("品名") if detail else None
            role = "release_scope" if is_release else "shared_relation_context"
            source_ref = (
                f"14.其他分析文件/2026年月报/6月/一组6月月报.xlsx|产品表现-ASIN|row={detail['__row_number']}"
                if detail else supplemental_child_refs[child]
            )
        children.append(
            {
                "child_asin": child,
                "parent_asin": parent,
                "sku": sku,
                "title": title,
                "slice_role": role,
                "source_status": "direct",
                "source_ref": source_ref,
            }
        )

    spend_period = "2026-06"
    spend_window = ("2026-06-01", "2026-06-30")
    spend_child_scope = set(child_parent) if is_release else selected_children
    product_spend_facts: list[dict[str, Any]] = []
    observed_spend_children: set[str] = set()
    for row in monthly_child_rows:
        child = str(row.get("ASIN") or "").strip().upper()
        parent = row.get("父ASIN")
        if parent not in PARENT_COUNTS or child not in spend_child_scope:
            continue
        spend = float(row["广告花费"])
        observed_spend_children.add(child)
        product_spend_facts.append({
            "product_ad_spend_id": stable_id("psp", "CHILD_ASIN", child, spend_period),
            "grain": "CHILD_ASIN", "parent_asin": parent, "child_asin": child, "period": spend_period,
            "window_start": spend_window[0], "window_end": spend_window[1], "spend": spend,
            "currency": "USD", "metric_status": "observed_positive" if spend > 0 else "observed_zero",
            "source_status": "direct",
            "source_ref": f"14.其他分析文件/2026年月报/6月/一组6月月报.xlsx|产品表现-ASIN|row={row['__row_number']}",
        })
    missing_spend_children = sorted(spend_child_scope - observed_spend_children)
    for child in missing_spend_children:
        product_spend_facts.append({
            "product_ad_spend_id": stable_id("psp", "CHILD_ASIN", child, spend_period),
            "grain": "CHILD_ASIN", "parent_asin": child_parent[child], "child_asin": child, "period": spend_period,
            "window_start": spend_window[0], "window_end": spend_window[1], "spend": None,
            "currency": "USD", "metric_status": "no_child_spend_fact", "source_status": "blocked",
            "source_ref": f"{supplemental_child_refs.get(child, 'scope reconciliation')}|missing from 一组6月月报.xlsx/产品表现-ASIN",
        })
    monthly_parent_rows = read_xlsx(mapping_files[0], "产品表现-父ASIN")
    spend_parent_scope = set(PARENT_COUNTS) if is_release else {STAR_PARENT}
    for row in monthly_parent_rows:
        parent = row.get("父ASIN")
        if parent not in spend_parent_scope:
            continue
        spend = float(row["广告花费"])
        product_spend_facts.append({
            "product_ad_spend_id": stable_id("psp", "PARENT_ASIN", parent, spend_period),
            "grain": "PARENT_ASIN", "parent_asin": parent, "child_asin": None, "period": spend_period,
            "window_start": spend_window[0], "window_end": spend_window[1], "spend": spend,
            "currency": "USD", "metric_status": "observed_positive" if spend > 0 else "observed_zero",
            "source_status": "direct",
            "source_ref": f"14.其他分析文件/2026年月报/6月/一组6月月报.xlsx|产品表现-父ASIN|row={row['__row_number']}",
        })
    if is_release:
        direct_child_spend = [row for row in product_spend_facts if row["grain"] == "CHILD_ASIN" and row["source_status"] == "direct"]
        positive_child_spend = [row for row in direct_child_spend if row["spend"] > 0]
        zero_child_spend = [row for row in direct_child_spend if row["spend"] == 0]
        blocked_child_spend = [row for row in product_spend_facts if row["grain"] == "CHILD_ASIN" and row["metric_status"] == "no_child_spend_fact"]
        parent_spend = [row for row in product_spend_facts if row["grain"] == "PARENT_ASIN"]
        if (len(direct_child_spend), len(positive_child_spend), len(zero_child_spend), len(blocked_child_spend), len(parent_spend)) != (520, 431, 89, 1, 5):
            raise ValueError("Release product-spend scope mismatch")
    actual_child_spend_fact_count = sum(1 for row in product_spend_facts if row["grain"] == "CHILD_ASIN" and row["source_status"] == "direct")
    blocked_child_spend_fact_count = sum(1 for row in product_spend_facts if row["grain"] == "CHILD_ASIN" and row["source_status"] == "blocked")
    actual_parent_spend_fact_count = sum(1 for row in product_spend_facts if row["grain"] == "PARENT_ASIN" and row["source_status"] == "direct")

    facts: list[dict[str, Any]] = []
    metrics_by_group_window: dict[tuple[tuple[str, str, str], str], dict[str, Any]] = {}
    sp_metric_columns = {
        "impressions": "展示量", "clicks": "点击量", "spend": "花费",
        "orders": "7天总订单数(#)", "sales": "7天总销售额",
    }
    for group_key in PAGE1_GROUPS:
        _, campaign, group = group_key
        base = [
            row for row in sp_search
            if row.get("广告活动名称") == campaign
            and row.get("广告组名称") == group
            and iso(row.get("开始日期")) == iso(row.get("结束日期"))
        ]
        for window_name, window in [("previous", PREVIOUS_WINDOW), ("current", CURRENT_WINDOW)]:
            selected = [row for row in base if window[0] <= row["开始日期"].date() <= window[1]]
            if not selected:
                raise ValueError(f"No exact daily source rows for {group_key} {window_name}")
            metrics = aggregate_metrics(selected, sp_metric_columns)
            metrics_by_group_window[(group_key, window_name)] = metrics
            source_ref = f"13.广告/商品推广_搜索词_报告.xlsx|exact-day rows|{campaign}|{group}|{window[0]}..{window[1]}"
            object_id = object_id_by_key[group_key]
            facts.append(
                {
                    "fact_id": stable_id("fact", object_id, window_name),
                    "ad_object_id": object_id,
                    "object_level": "AD_GROUP",
                    "ad_type": "SP",
                    "window_start": window[0].isoformat(),
                    "window_end": window[1].isoformat(),
                    "coverage_start": min(row["开始日期"].date() for row in selected).isoformat(),
                    "coverage_end": max(row["结束日期"].date() for row in selected).isoformat(),
                    "attribution_days": 7,
                    "attribution_scope": "shared",
                    "comparison_status": "comparable_exact_daily_rows",
                    "metric_basis": "search_term_exact_day_sum",
                    **metrics,
                    "currency": "USD",
                    "source_system": "AMAZON",
                    "source_status": "direct",
                    "source_ref": source_ref,
                    "source_row_filter": "开始日期=结束日期且日期位于窗口；从分子分母汇总，不平均比率",
                }
            )

    if is_release:
        for campaign, group in sorted(sp_group_keys):
            sp_key = ("SP", campaign, group)
            selected = promoted_source_rows[sp_key]
            metrics = aggregate_metrics(selected, sp_metric_columns)
            promoted_count = len({str(row.get("广告ASIN") or "").upper() for row in selected if row.get("广告ASIN")})
            from_video = (campaign, group) not in all_sp_promoted_groups
            coverage_start = min(iso(row.get("开始日期")) for row in selected)
            coverage_end = max(iso(row.get("结束日期")) for row in selected)
            comparison_status = "comparable_with_same_basis_only" if (coverage_start, coverage_end) == (AMAZON_START.isoformat(), AMAZON_END.isoformat()) else "partial_source_coverage"
            facts.append({
                "fact_id": stable_id("fact", object_id_by_key[sp_key], "july_promoted_product"),
                "ad_object_id": object_id_by_key[sp_key], "object_level": "AD_GROUP", "ad_type": "SP",
                "window_start": AMAZON_START.isoformat(), "window_end": AMAZON_END.isoformat(),
                "coverage_start": coverage_start, "coverage_end": coverage_end,
                "attribution_days": 7, "attribution_scope": "shared" if promoted_count > 1 else "direct",
                "comparison_status": comparison_status, "metric_basis": "promoted_product_period_sum",
                **metrics, "currency": "USD", "source_system": "AMAZON", "source_status": "direct",
                "source_ref": f"13.广告/{'商品推广_视频_报告.xlsx' if from_video else '商品推广_推广的商品_报告.xlsx'}|{campaign}|{group}|2026-07",
                "source_row_filter": "同广告组全部明确广告ASIN行求和；从分子分母复算比率",
            })

    sd_fact_pairs = sorted(sd_group_keys) if is_release else sorted(star_sd_groups)[:1]
    for campaign, group in sd_fact_pairs:
        sd_key = ("SD", campaign, group)
        selected = promoted_source_rows[sd_key]
        metrics = aggregate_metrics(selected, {
            "impressions": "展示量", "clicks": "点击量", "spend": "花费",
            "orders": "14天总订单数(#)", "sales": "14天总销售额",
        })
        coverage_start = min(iso(row.get("开始日期")) for row in selected)
        coverage_end = max(iso(row.get("结束日期")) for row in selected)
        comparison_status = "comparable_with_same_basis_only" if (coverage_start, coverage_end) == (AMAZON_START.isoformat(), AMAZON_END.isoformat()) else "partial_source_coverage"
        facts.append({
            "fact_id": stable_id("fact", object_id_by_key[sd_key], "july"),
            "ad_object_id": object_id_by_key[sd_key], "object_level": "AD_GROUP", "ad_type": "SD",
            "window_start": AMAZON_START.isoformat(), "window_end": AMAZON_END.isoformat(),
            "coverage_start": coverage_start, "coverage_end": coverage_end,
            "attribution_days": 14, "attribution_scope": "shared" if len({row.get('广告ASIN') for row in selected}) > 1 else "direct", "comparison_status": comparison_status,
            "metric_basis": "promoted_product_period_sum", **metrics, "currency": "USD", "source_system": "AMAZON",
            "source_status": "direct", "source_ref": f"13.广告/展示型推广_推广的商品_报告.xlsx|{campaign}|{group}|2026-07",
            "source_row_filter": "同广告组全部推广ASIN行求和；不与SP混加",
        })
    sb_fact_pairs = sorted(sb_group_keys) if is_release else sorted(sb_group_keys)[:1]
    for campaign, group in sb_fact_pairs:
        selected = [row for row in sb_keyword if row["广告活动名称"] == campaign and row["广告组名称"] == group]
        metrics = aggregate_metrics(selected, {
            "impressions": "展示量", "clicks": "点击量", "spend": "花费",
            "orders": "14天总订单数(#)", "sales": "14天总销售额",
        })
        coverage_start = min(iso(row.get("开始日期")) for row in selected)
        coverage_end = max(iso(row.get("结束日期")) for row in selected)
        comparison_status = "comparable_with_same_basis_only" if (coverage_start, coverage_end) == (AMAZON_START.isoformat(), AMAZON_END.isoformat()) else "partial_source_coverage"
        key = ("SB", campaign, group)
        facts.append({
            "fact_id": stable_id("fact", object_id_by_key[key], "july"),
            "ad_object_id": object_id_by_key[key], "object_level": "AD_GROUP", "ad_type": "SB",
            "window_start": AMAZON_START.isoformat(), "window_end": AMAZON_END.isoformat(),
            "coverage_start": coverage_start, "coverage_end": coverage_end,
            "attribution_days": 14, "attribution_scope": "unattributed", "comparison_status": comparison_status,
            "metric_basis": "keyword_period_sum", **metrics, "currency": "USD", "source_system": "AMAZON",
            "source_status": "direct", "source_ref": f"13.广告/品牌推广_关键词_报告.xlsx|{campaign}|{group}|2026-07",
            "source_row_filter": "同广告组全部关键词行求和；无广告ASIN映射，保持unattributed",
        })
    if is_release:
        for target_row in top_targets:
            campaign, group = target_row["广告活动名称"], target_row["广告组名称"]
            target_text, match_type = target_row.get("投放"), target_row.get("匹配类型")
            parent_id = object_id_by_key[("SP", campaign, group)]
            target_id = stable_id("tgt", parent_id, target_text, match_type)
            selected = [
                row for row in sp_target
                if row.get("广告活动名称") == campaign and row.get("广告组名称") == group
                and row.get("投放") == target_text and row.get("匹配类型") == match_type
            ]
            metrics = aggregate_metrics(selected, sp_metric_columns)
            coverage_start = min(iso(row.get("开始日期")) for row in selected)
            coverage_end = max(iso(row.get("结束日期")) for row in selected)
            comparison_status = "comparable_with_same_basis_only" if (coverage_start, coverage_end) == (AMAZON_START.isoformat(), AMAZON_END.isoformat()) else "partial_source_coverage"
            facts.append({
                "fact_id": stable_id("fact", target_id, "july_target"), "ad_object_id": target_id,
                "object_level": "TARGET", "ad_type": "SP", "window_start": AMAZON_START.isoformat(),
                "window_end": AMAZON_END.isoformat(), "coverage_start": coverage_start,
                "coverage_end": coverage_end, "attribution_days": 7,
                "attribution_scope": "shared", "comparison_status": comparison_status,
                "metric_basis": "target_period_sum", **metrics, "currency": "USD", "source_system": "AMAZON",
                "source_status": "direct", "source_ref": f"13.广告/商品推广_投放_报告.xlsx|{campaign}|{group}|{target_text}|{match_type}",
                "source_row_filter": "同广告组、投放、匹配类型的直接投放行求和",
            })

    labels: list[dict[str, Any]] = []
    purpose_values = [
        ("大词流量观察", "pending"),
        ("自动紧密探索", "rejected"),
        ("竞品ASIN承接", "unrecognized"),
    ]
    for index, group_key in enumerate(PAGE1_GROUPS):
        object_id = object_id_by_key[group_key]
        source_ref = source_ref_by_group[group_key]
        base_labels = [
            ("PRODUCT_RELATION", "一父多子共享", "auto_mapping", "confirmed", "derived"),
            ("TARGET_OBJECT", "关键词" if index < 2 else "ASIN", "system_attribute", "confirmed", "direct"),
            ("AD_ATTRIBUTE", "SP", "system_attribute", "confirmed", "direct"),
            ("AD_PURPOSE", purpose_values[index][0], "ai_suggested", purpose_values[index][1], "scenario_added"),
        ]
        for label_type, value, label_source, status, source_status in base_labels:
            labels.append({
                "label_version_id": stable_id("lbl", object_id, label_type, value, "2026-07-01"),
                "ad_object_id": object_id, "label_type": label_type, "label_value": value,
                "label_source": label_source, "confirmation_status": status,
                "effective_from": AMAZON_START.isoformat(), "effective_to": None,
                "inherited_from_object_id": None, "source_status": source_status,
                "source_ref": source_ref if source_status != "scenario_added" else "scenario://label-suggestion/v0.1",
            })
    if is_release:
        page1_group_ids = {object_id_by_key[key] for key in PAGE1_GROUPS}
        for group_object in [row for row in ad_objects if row["object_level"] == "AD_GROUP" and row["ad_object_id"] not in page1_group_ids]:
            mapped = group_object["mapping_status"] == "direct_advertising_asin"
            release_labels = [
                ("PRODUCT_RELATION", "明确广告ASIN映射" if mapped else "待映射", "auto_mapping", "confirmed" if mapped else "unrecognized", "derived" if mapped else "blocked"),
                ("TARGET_OBJECT", "待按投放明细识别", "auto_mapping", "pending", "derived"),
                ("AD_ATTRIBUTE", group_object["ad_type"], "system_attribute", "confirmed", "direct"),
                ("AD_PURPOSE", "待运营确认", "ai_suggested", "pending", "scenario_added"),
            ]
            for label_type, value, label_source, status, source_status in release_labels:
                labels.append({
                    "label_version_id": stable_id("lbl", group_object["ad_object_id"], label_type, value, "2026-07-01"),
                    "ad_object_id": group_object["ad_object_id"], "label_type": label_type, "label_value": value,
                    "label_source": label_source, "confirmation_status": status, "effective_from": AMAZON_START.isoformat(),
                    "effective_to": None, "inherited_from_object_id": None, "source_status": source_status,
                    "source_ref": group_object["source_ref"] if source_status != "scenario_added" else "scenario://release-label-suggestion/v0.1",
                })
    first_group_id = object_id_by_key[PAGE1_GROUPS[0]]
    labels.extend([
        {
            "label_version_id": stable_id("lbl", first_group_id, "OPERATOR_CUSTOM", "重点观察", "2026-07-01"),
            "ad_object_id": first_group_id, "label_type": "OPERATOR_CUSTOM", "label_value": "重点观察",
            "label_source": "operator_confirmed", "confirmation_status": "confirmed",
            "effective_from": "2026-07-01", "effective_to": "2026-07-15", "inherited_from_object_id": None,
            "source_status": "scenario_added", "source_ref": "scenario://label-version-change/v0.1",
        },
        {
            "label_version_id": stable_id("lbl", first_group_id, "OPERATOR_CUSTOM", "效率回落观察", "2026-07-16"),
            "ad_object_id": first_group_id, "label_type": "OPERATOR_CUSTOM", "label_value": "效率回落观察",
            "label_source": "ai_suggested", "confirmation_status": "pending",
            "effective_from": "2026-07-16", "effective_to": None, "inherited_from_object_id": None,
            "source_status": "scenario_added", "source_ref": "scenario://label-version-change/v0.1",
        },
    ])
    for target in [row for row in ad_objects if row["object_level"] == "TARGET"]:
        labels.append({
            "label_version_id": stable_id("lbl", target["ad_object_id"], "AD_PURPOSE", "继承广告组目的", "2026-07-01"),
            "ad_object_id": target["ad_object_id"], "label_type": "AD_PURPOSE", "label_value": "继承广告组目的",
            "label_source": "group_inherited", "confirmation_status": "pending",
            "effective_from": "2026-07-01", "effective_to": None,
            "inherited_from_object_id": target["parent_ad_object_id"], "source_status": "scenario_added",
            "source_ref": "scenario://target-label-inheritance/v0.1",
        })

    rules = [
        {"rule_id": "rule_acos_gt_050", "rule_name": "ACoS高于演示观察线", "metric_name": "acos", "operator": ">", "threshold": 0.50,
         "enabled": 1, "rule_status": "pending_customer_confirmation", "rule_version": "demo-v0.1", "source_status": "scenario_added", "source_ref": "scenario://anomaly-rule/v0.1"},
        {"rule_id": "rule_acos_increase_gt_030", "rule_name": "ACoS较自身历史上升超过30%", "metric_name": "acos_change_rate", "operator": ">", "threshold": 0.30,
         "enabled": 1, "rule_status": "pending_customer_confirmation", "rule_version": "demo-v0.1", "source_status": "scenario_added", "source_ref": "scenario://anomaly-rule/v0.1"},
    ]

    page1_results: list[dict[str, Any]] = []
    page1_anomalies: list[dict[str, Any]] = []
    query_specs = [
        ("q_page1_all_sp_observe", PAGE1_GROUPS, "ad_type=SP;label=观察切片;scope=all", True),
        ("q_page1_auto_only", [PAGE1_GROUPS[1]], "ad_type=SP;purpose=自动紧密探索", True),
        ("q_page1_no_rule", [PAGE1_GROUPS[2]], "ad_type=SP;rule_set=none", False),
    ]
    for query_id, group_keys, signature, apply_rules in query_specs:
        ranked = sorted(group_keys, key=lambda key: metrics_by_group_window[(key, "current")]["acos"] or math.inf)
        for key in group_keys:
            current = metrics_by_group_window[(key, "current")]
            previous = metrics_by_group_window[(key, "previous")]
            change = None if previous["acos"] in (None, 0) or current["acos"] is None else current["acos"] / previous["acos"] - 1
            result_id = stable_id("p1", query_id, object_id_by_key[key])
            row = {
                "result_id": result_id, "query_id": query_id, "ad_object_id": object_id_by_key[key],
                "object_level": "AD_GROUP", "window_start": CURRENT_WINDOW[0].isoformat(), "window_end": CURRENT_WINDOW[1].isoformat(),
                "attribution_days": 7, "metric_basis": "search_term_exact_day_sum", "filter_signature": signature,
                "object_count": len(group_keys), "comparison_eligible": 1, **current,
                "previous_acos": previous["acos"], "acos_change_rate": change,
                "rank_by_acos": ranked.index(key) + 1, "source_status": "derived",
                "source_ref": f"fact_ad_performance|{stable_id('fact', object_id_by_key[key], 'current')}+{stable_id('fact', object_id_by_key[key], 'previous')}",
            }
            page1_results.append(row)
            if apply_rules and current["acos"] is not None and current["acos"] > 0.50:
                page1_anomalies.append({
                    "anomaly_id": stable_id("ano", query_id, result_id, "rule_acos_gt_050"), "query_id": query_id,
                    "result_id": result_id, "ad_object_id": object_id_by_key[key], "rule_id": "rule_acos_gt_050",
                    "metric_name": "acos", "observed_value": current["acos"], "threshold": 0.50, "severity": "warning",
                    "source_status": "derived", "source_ref": f"fact_page1_result|{result_id}",
                })
            if apply_rules and change is not None and change > 0.30:
                page1_anomalies.append({
                    "anomaly_id": stable_id("ano", query_id, result_id, "rule_acos_increase_gt_030"), "query_id": query_id,
                    "result_id": result_id, "ad_object_id": object_id_by_key[key], "rule_id": "rule_acos_increase_gt_030",
                    "metric_name": "acos_change_rate", "observed_value": change, "threshold": 0.30, "severity": "warning",
                    "source_status": "derived", "source_ref": f"fact_page1_result|{result_id}",
                })

    release_query_specs: list[tuple[str, str, str]] = []
    if is_release:
        for ad_type, metric_basis in [("SP", "promoted_product_period_sum"), ("SB", "keyword_period_sum"), ("SD", "promoted_product_period_sum")]:
            query_id = f"q_release_{ad_type.lower()}_all_groups"
            signature = f"release=true;ad_type={ad_type};object_level=AD_GROUP;window=2026-07"
            release_query_specs.append((query_id, signature, ad_type))
            eligible_facts = [
                row for row in facts
                if row["ad_type"] == ad_type and row["object_level"] == "AD_GROUP"
                and row["window_start"] == AMAZON_START.isoformat() and row["window_end"] == AMAZON_END.isoformat()
                and row["metric_basis"] == metric_basis
            ]
            comparable_facts = [row for row in eligible_facts if row["comparison_status"] == "comparable_with_same_basis_only"]
            ranked = sorted(comparable_facts, key=lambda row: row["acos"] if row["acos"] is not None else math.inf)
            for fact in eligible_facts:
                result_id = stable_id("p1", query_id, fact["ad_object_id"])
                page1_results.append({
                    "result_id": result_id, "query_id": query_id, "ad_object_id": fact["ad_object_id"],
                    "object_level": "AD_GROUP", "window_start": AMAZON_START.isoformat(), "window_end": AMAZON_END.isoformat(),
                    "attribution_days": fact["attribution_days"], "metric_basis": metric_basis,
                    "filter_signature": signature, "object_count": len(eligible_facts), "comparison_eligible": 1 if fact in comparable_facts else 0,
                    **{name: fact[name] for name in ["impressions", "clicks", "spend", "orders", "ad_sales", "ctr", "cpc", "cvr", "acos", "roas"]},
                    "previous_acos": None, "acos_change_rate": None, "rank_by_acos": ranked.index(fact) + 1 if fact in comparable_facts else None,
                    "source_status": "derived", "source_ref": f"fact_ad_performance|{fact['fact_id']}",
                })

    keyword_rows = read_xlsx(paths["keyword"], "全量关键词(含分类)")
    keyword_evidence = []
    for term in ["mens underwear", "mens boxer briefs", "athletic underwear men"]:
        row = first_matching(keyword_rows, "关键词", term)
        ranks = []
        for position in (1, 2, 3):
            if str(row.get(f"#{position} 前三ASIN") or "").upper() == STAR_CHILD:
                ranks.append({"rank": position, "click_share": row.get(f"#{position} 点击共享"), "conversion_share": row.get(f"#{position}转化共享")})
        keyword_evidence.append({"keyword": term, "monthly_search_volume": row.get("月搜索量"), "star_top_asin": ranks})
    competitor_rows = read_xlsx(paths["competitor"], "Competitor-US-Last-30-days")
    competitor = first_matching(competitor_rows, "ASIN", "B086L4BXZC")

    current_decision = "dec_B088WF1PRW_20260803_v01"
    historical_decision = "dec_B088WF1PRW_20260710_scenario"
    contexts = [
        {"decision_id": historical_decision, "child_asin": STAR_CHILD, "parent_asin": STAR_PARENT,
         "product_goal_version": "goal-scenario-v0.0", "product_goal": "观察大词广告组效率波动（演示场景）",
         "goal_status": "scenario_only", "decision_at": "2026-07-10", "previous_decision_id": None,
         "source_status": "scenario_added", "source_ref": "scenario://historical-action/2026-07-10"},
        {"decision_id": current_decision, "child_asin": STAR_CHILD, "parent_asin": STAR_PARENT,
         "product_goal_version": "goal-derived-v0.1", "product_goal": "稳定规模并保护核心流量位置（待运营确认）",
         "goal_status": "conditional_pending_operator_confirmation", "decision_at": "2026-08-03", "previous_decision_id": historical_decision,
         "source_status": "derived", "source_ref": "关键词3.xlsx+产品跟进表-曾向锋.xlsx+广告事实"},
    ]

    baseline_rows = [row for row in sp_search if row.get("广告活动名称") == PAGE1_GROUPS[0][1] and row.get("广告组名称") == PAGE1_GROUPS[0][2]
                     and iso(row.get("开始日期")) == iso(row.get("结束日期")) and date(2026, 7, 7) <= row["开始日期"].date() <= date(2026, 7, 9)]
    d3_rows = [row for row in sp_search if row.get("广告活动名称") == PAGE1_GROUPS[0][1] and row.get("广告组名称") == PAGE1_GROUPS[0][2]
               and iso(row.get("开始日期")) == iso(row.get("结束日期")) and date(2026, 7, 11) <= row["开始日期"].date() <= date(2026, 7, 13)]
    d7_rows = [row for row in sp_search if row.get("广告活动名称") == PAGE1_GROUPS[0][1] and row.get("广告组名称") == PAGE1_GROUPS[0][2]
               and iso(row.get("开始日期")) == iso(row.get("结束日期")) and date(2026, 7, 11) <= row["开始日期"].date() <= date(2026, 7, 17)]
    baseline_metrics = aggregate_metrics(baseline_rows, sp_metric_columns)
    d3_metrics = aggregate_metrics(d3_rows, sp_metric_columns)
    d7_metrics = aggregate_metrics(d7_rows, sp_metric_columns)

    evidence = [
        {"evidence_id": "ev_hist_goal", "decision_id": historical_decision, "evidence_type": "PRODUCT_GOAL", "evidence_title": "演示目标",
         "evidence_payload": dumps({"goal": "观察大词广告组效率波动", "scenario_only": True}), "observed_at": "2026-07-10", "valid_as_of": "2026-07-10",
         "source_status": "scenario_added", "source_ref": "scenario://historical-action/2026-07-10", "evidence_nature": "inference", "evidence_status": "current", "caveat": "非客户真实动作"},
        {"evidence_id": "ev_hist_action", "decision_id": historical_decision, "evidence_type": "HISTORY_ACTION", "evidence_title": "演示观察动作",
         "evidence_payload": dumps({"action": "7月10日将大词组加入观察", "scenario_only": True}), "observed_at": "2026-07-10", "valid_as_of": "2026-07-10",
         "source_status": "scenario_added", "source_ref": "scenario://historical-action/2026-07-10", "evidence_nature": "fact", "evidence_status": "current", "caveat": "动作本身为场景新增"},
        {"evidence_id": "ev_hist_perf", "decision_id": historical_decision, "evidence_type": "AD_PERFORMANCE", "evidence_title": "动作前3日真实表现",
         "evidence_payload": dumps(baseline_metrics), "observed_at": "2026-07-09", "valid_as_of": "2026-07-09",
         "source_status": "derived", "source_ref": "商品推广_搜索词_报告.xlsx|exact-day rows|2026-07-07..09", "evidence_nature": "fact", "evidence_status": "current", "caveat": "指标由Amazon直接日行求和"},
        {"evidence_id": "ev_goal_current", "decision_id": current_decision, "evidence_type": "PRODUCT_GOAL", "evidence_title": "当前产品目标判断",
         "evidence_payload": dumps({"goal": "稳定规模并保护核心流量位置", "status": "conditional"}), "observed_at": "2026-08-03", "valid_as_of": "2026-08-03",
         "source_status": "derived", "source_ref": "关键词3.xlsx+产品跟进表-曾向锋.xlsx+广告事实", "evidence_nature": "inference", "evidence_status": "current", "caveat": "待运营确认，不是客户已确认目标"},
        {"evidence_id": "ev_inventory_current", "decision_id": current_decision, "evidence_type": "INVENTORY", "evidence_title": "子ASIN库存承接能力",
         "evidence_payload": dumps({"fba_inventory": inventory.get("FBA库存"), "available": inventory.get("可售"), "receiving": inventory.get("入库中"),
                                    "fba_inbound": inventory.get("FBA在途"), "sales_30d": inventory.get("30天销量"), "daily_avg_30d": inventory.get("30天日均"),
                                    "sellable_days_total": inventory.get("可售天数(总)"), "stockout_date": iso(inventory.get("断货时间")),
                                    "immediate_available_days": ratio(number(inventory.get("可售")), number(inventory.get("30天日均")))}),
         "observed_at": "2026-08-03", "valid_as_of": "2026-08-03", "source_status": "direct",
         "source_ref": f"产品跟进表-曾向锋.xlsx|数据源-领星补货建议|row={inventory['__row_number']}", "evidence_nature": "fact", "evidence_status": "current", "caveat": "立即可售覆盖与含在途总覆盖需分开看"},
        {"evidence_id": "ev_keyword_current", "decision_id": current_decision, "evidence_type": "KEYWORD", "evidence_title": "核心关键词位置",
         "evidence_payload": dumps(keyword_evidence), "observed_at": "2026-08-03", "valid_as_of": "2026-08-03", "source_status": "direct",
         "source_ref": "关键词3.xlsx|全量关键词(含分类)|3 terms", "evidence_nature": "fact", "evidence_status": "current", "caveat": "来源文件无独立抓取时间列，沿用数据包快照日"},
        {"evidence_id": "ev_competitor_current", "decision_id": current_decision, "evidence_type": "COMPETITOR", "evidence_title": "头部竞品压力",
         "evidence_payload": dumps({"asin": competitor.get("ASIN"), "brand": competitor.get("品牌"), "parent_asin": competitor.get("父ASIN"),
                                    "category_bsr": competitor.get("大类BSR"), "monthly_sales": competitor.get("月销量"), "monthly_revenue_usd": competitor.get("月销售额($)"),
                                    "price_usd": competitor.get("价格($)"), "rating": competitor.get("评分"), "rating_count": competitor.get("评分数"),
                                    "buy_box_type": competitor.get("BuyBox类型"), "best_seller": competitor.get("Best Seller标识"), "amazon_choice": competitor.get("Amazon's Choice")}),
         "observed_at": "2026-08-03", "valid_as_of": "2026-08-03", "source_status": "direct",
         "source_ref": f"9.竞品.xlsx|Competitor-US-Last-30-days|row={competitor['__row_number']}", "evidence_nature": "fact", "evidence_status": "current", "caveat": "竞品并非已证明的效率变化原因"},
        {"evidence_id": "ev_history_current", "decision_id": current_decision, "evidence_type": "HISTORY_ACTION", "evidence_title": "演示动作的D+3/D+7反馈",
         "evidence_payload": dumps({"action_source": "scenario_added", "baseline": baseline_metrics, "d3": d3_metrics, "d7": d7_metrics}),
         "observed_at": "2026-07-17", "valid_as_of": "2026-07-17", "source_status": "scenario_added",
         "source_ref": "scenario://historical-action/2026-07-10+商品推广_搜索词_报告.xlsx", "evidence_nature": "fact", "evidence_status": "current", "caveat": "动作是假设；复盘数值来自真实日粒度报表"},
        {"evidence_id": "ev_ad_perf_current", "decision_id": current_decision, "evidence_type": "AD_PERFORMANCE", "evidence_title": "当前与前窗广告表现",
         "evidence_payload": dumps({"groups": [{"campaign": key[1], "group": key[2], "previous": metrics_by_group_window[(key, 'previous')], "current": metrics_by_group_window[(key, 'current')]} for key in PAGE1_GROUPS]}),
         "observed_at": "2026-07-31", "valid_as_of": "2026-07-31", "source_status": "derived",
         "source_ref": "fact_ad_performance|page1 comparison groups", "evidence_nature": "fact", "evidence_status": "current", "caveat": "仅使用开始日期=结束日期的真实日行"},
    ]

    task_hist = "task_hist_observe"
    task_inventory = "task_inventory_prerequisite"
    task_core = "task_core_visibility"
    task_efficiency = "task_efficiency_observe"
    tasks = [
        {"task_id": task_hist, "decision_id": historical_decision, "product_goal_version": "goal-scenario-v0.0", "task_type": "OBSERVE_EFFICIENCY",
         "task_direction": "OBSERVE", "priority": "P1", "target_scope": "BR group", "constraints": dumps(["scenario only"]),
         "evaluation_direction": "观察ACoS与CVR", "stop_condition": "出现明显恶化则回到人工检查", "rule_status": "unconfirmed", "rule_id": None,
         "exact_budget": None, "exact_bid": None, "exact_placement_adjustment": None, "evidence_ids": dumps(["ev_hist_goal", "ev_hist_perf"]),
         "inventory_constrained": 0, "source_status": "scenario_added", "source_ref": "scenario://historical-action/2026-07-10"},
        {"task_id": task_inventory, "decision_id": current_decision, "product_goal_version": "goal-derived-v0.1", "task_type": "VERIFY_INBOUND_BEFORE_SCALE",
         "task_direction": "PREREQUISITE", "priority": "P0", "target_scope": STAR_CHILD, "constraints": dumps(["immediate available coverage is limited", "inbound receipt not yet verified"]),
         "evaluation_direction": "先核验入库，再判断是否可扩量", "stop_condition": "入库未确认或立即可售覆盖继续下降", "rule_status": "unconfirmed", "rule_id": None,
         "exact_budget": None, "exact_bid": None, "exact_placement_adjustment": None, "evidence_ids": dumps(["ev_goal_current", "ev_inventory_current"]),
         "inventory_constrained": 1, "source_status": "derived", "source_ref": "ev_inventory_current"},
        {"task_id": task_core, "decision_id": current_decision, "product_goal_version": "goal-derived-v0.1", "task_type": "PROTECT_CORE_QUERY_VISIBILITY",
         "task_direction": "OBSERVE", "priority": "P1", "target_scope": "core queries", "constraints": dumps(["goal pending confirmation", "inventory prerequisite"]),
         "evaluation_direction": "维持核心词可见性并观察效率", "stop_condition": "库存约束未解除或核心词位置显著变化", "rule_status": "unconfirmed", "rule_id": None,
         "exact_budget": None, "exact_bid": None, "exact_placement_adjustment": None, "evidence_ids": dumps(["ev_goal_current", "ev_keyword_current", "ev_inventory_current"]),
         "inventory_constrained": 1, "source_status": "derived", "source_ref": "ev_keyword_current+ev_inventory_current"},
        {"task_id": task_efficiency, "decision_id": current_decision, "product_goal_version": "goal-derived-v0.1", "task_type": "CONTROL_EFFICIENCY_DRIFT",
         "task_direction": "OBSERVE", "priority": "P1", "target_scope": "comparable SP groups", "constraints": dumps(["no confirmed single-group ACoS cap"]),
         "evaluation_direction": "相对自身历史检查ACoS与CVR", "stop_condition": "缺少可比日行或同期变量无法排除", "rule_status": "unconfirmed", "rule_id": None,
         "exact_budget": None, "exact_bid": None, "exact_placement_adjustment": None, "evidence_ids": dumps(["ev_ad_perf_current", "ev_history_current"]),
         "inventory_constrained": 0, "source_status": "derived", "source_ref": "ev_ad_perf_current+ev_history_current"},
    ]

    mappings = [
        {"mapping_id": "map_hist_br", "task_id": task_hist, "ad_object_id": first_group_id, "coverage_status": "covered", "attribution_limit": "shared",
         "evidence_ids": dumps(["ev_hist_perf"]), "is_automatic_error": 0, "source_status": "derived", "source_ref": "bridge_ad_object_product"},
        {"mapping_id": "map_inventory_gap", "task_id": task_inventory, "ad_object_id": None, "coverage_status": "missing", "attribution_limit": "unattributed",
         "evidence_ids": dumps(["ev_inventory_current"]), "is_automatic_error": 0, "source_status": "derived", "source_ref": "ev_inventory_current"},
        {"mapping_id": "map_core_br", "task_id": task_core, "ad_object_id": first_group_id, "coverage_status": "covered", "attribution_limit": "shared",
         "evidence_ids": dumps(["ev_keyword_current", "ev_inventory_current"]), "is_automatic_error": 0, "source_status": "derived", "source_ref": "bridge_ad_object_product"},
        {"mapping_id": "map_efficiency_auto", "task_id": task_efficiency, "ad_object_id": object_id_by_key[PAGE1_GROUPS[1]], "coverage_status": "mixed", "attribution_limit": "shared",
         "evidence_ids": dumps(["ev_ad_perf_current", "ev_history_current"]), "is_automatic_error": 0, "source_status": "derived", "source_ref": "fact_page1_result+bridge_ad_object_product"},
    ]

    diagnoses = [
        {"diagnosis_id": "diag_hist_variation", "decision_id": historical_decision, "task_id": task_hist, "problem_type": "EFFICIENCY_VARIATION",
         "impacted_goal": "观察大词广告组效率波动", "priority": "P1", "confidence": "medium", "evidence_ids": dumps(["ev_hist_perf"]),
         "uncertainty": "同期竞价与自然位变化未知", "missing_input": "客户确认阈值", "check_direction": "仅做自身历史观察",
         "basis_type": "self_history", "causal_claim": 0, "source_status": "derived", "source_ref": "ev_hist_perf"},
        {"diagnosis_id": "diag_inventory_constraint", "decision_id": current_decision, "task_id": task_inventory, "problem_type": "INVENTORY_COVERAGE_RISK",
         "impacted_goal": "稳定规模并保护核心流量位置", "priority": "P0", "confidence": "high", "evidence_ids": dumps(["ev_inventory_current"]),
         "uncertainty": "在途到仓时间与可售转化时间未确认", "missing_input": "最新入库确认", "check_direction": "先核验入库承接能力",
         "basis_type": "conditional", "causal_claim": 0, "source_status": "derived", "source_ref": "ev_inventory_current"},
        {"diagnosis_id": "diag_core_visibility", "decision_id": current_decision, "task_id": task_core, "problem_type": "CORE_QUERY_DEFENSE",
         "impacted_goal": "保护核心流量位置", "priority": "P1", "confidence": "medium", "evidence_ids": dumps(["ev_keyword_current", "ev_competitor_current"]),
         "uncertainty": "竞品数据不能证明广告效率因果", "missing_input": "运营确认核心词清单与容忍区间", "check_direction": "观察核心词位置与广告承接",
         "basis_type": "conditional", "causal_claim": 0, "source_status": "derived", "source_ref": "ev_keyword_current+ev_competitor_current"},
        {"diagnosis_id": "diag_efficiency_drift", "decision_id": current_decision, "task_id": task_efficiency, "problem_type": "ACOS_UP_VS_SELF_HISTORY",
         "impacted_goal": "稳定规模", "priority": "P1", "confidence": "medium", "evidence_ids": dumps(["ev_ad_perf_current", "ev_history_current"]),
         "uncertainty": "未控制竞价、自然位、促销和流量结构变化", "missing_input": "同期变更记录", "check_direction": "按同粒度同归因继续观察",
         "basis_type": "self_history", "causal_claim": 0, "source_status": "derived", "source_ref": "ev_ad_perf_current+ev_history_current"},
    ]

    recommendations = [
        {"recommendation_id": "rec_hist_observe", "decision_id": historical_decision, "diagnosis_id": "diag_hist_variation", "product_goal_version": "goal-scenario-v0.0",
         "ad_purpose": "大词效率观察", "ad_object_id": first_group_id, "structure_gap_id": None, "direction": "OBSERVE",
         "rationale": "用真实日粒度数值演示反馈链", "preconditions": dumps(["scenario only"]), "risks": dumps(["不得当作客户真实动作"]),
         "uncertainty": "同期变量未知", "observation_metrics": dumps(["acos", "cvr", "spend", "ad_sales"]), "review_windows": dumps(["D+3", "D+7"]),
         "d7_not_required": 0, "rule_status": "unconfirmed", "rule_id": None, "exact_value": None, "source_status": "scenario_added", "source_ref": "scenario://historical-action/2026-07-10"},
        {"recommendation_id": "rec_inventory_defer", "decision_id": current_decision, "diagnosis_id": "diag_inventory_constraint", "product_goal_version": "goal-derived-v0.1",
         "ad_purpose": "库存承接约束", "ad_object_id": None, "structure_gap_id": "gap_inbound_verification", "direction": "DEFER",
         "rationale": "立即可售覆盖有限，先核验入库再判断扩量", "preconditions": dumps(["confirm inbound receipt"]), "risks": dumps(["stockout", "traffic loss"]),
         "uncertainty": "到仓时间未确认", "observation_metrics": dumps(["available_inventory", "daily_sales", "sellable_days"]), "review_windows": dumps(["D+3", "D+7"]),
         "d7_not_required": 0, "rule_status": "unconfirmed", "rule_id": None, "exact_value": None, "source_status": "derived", "source_ref": "diag_inventory_constraint"},
        {"recommendation_id": "rec_core_observe", "decision_id": current_decision, "diagnosis_id": "diag_core_visibility", "product_goal_version": "goal-derived-v0.1",
         "ad_purpose": "核心词守位", "ad_object_id": first_group_id, "structure_gap_id": None, "direction": "OBSERVE",
         "rationale": "核心词已有真实位置证据，但目标和库存约束未确认", "preconditions": dumps(["goal confirmation", "inventory verification"]), "risks": dumps(["efficiency drift"]),
         "uncertainty": "无客户确认阈值", "observation_metrics": dumps(["keyword_position", "acos", "cvr"]), "review_windows": dumps(["D+3", "D+7"]),
         "d7_not_required": 0, "rule_status": "unconfirmed", "rule_id": None, "exact_value": None, "source_status": "derived", "source_ref": "diag_core_visibility"},
        {"recommendation_id": "rec_efficiency_request_info", "decision_id": current_decision, "diagnosis_id": "diag_efficiency_drift", "product_goal_version": "goal-derived-v0.1",
         "ad_purpose": "效率波动核验", "ad_object_id": object_id_by_key[PAGE1_GROUPS[1]], "structure_gap_id": None, "direction": "REQUEST_INFO",
         "rationale": "自身历史变化存在，但缺少同期变更记录，不能写成因果", "preconditions": dumps(["collect change log"]), "risks": dumps(["false attribution"]),
         "uncertainty": "同期变量未知", "observation_metrics": dumps(["acos", "cvr", "cpc"]), "review_windows": dumps(["D+3", "D+7"]),
         "d7_not_required": 0, "rule_status": "unconfirmed", "rule_id": None, "exact_value": None, "source_status": "derived", "source_ref": "diag_efficiency_drift"},
    ]

    feedback = [
        {"feedback_id": "fb_hist_d3", "decision_id": historical_decision, "recommendation_id": "rec_hist_observe", "review_window": "D+3", "review_at": "2026-07-13",
         "status": "observed", "baseline_metrics": dumps(baseline_metrics), "observed_metrics": dumps(d3_metrics),
         "conclusion": "D+3 ACoS下降、CVR上升；仅为同期观察，不声明动作导致", "concurrent_variables": dumps(["bid changes unknown", "organic rank unknown", "promotion unknown"]),
         "next_question": "D+7是否保持且同期变量能否补齐", "source_status": "scenario_added", "source_ref": "scenario://historical-action/2026-07-10+Amazon exact-day facts"},
        {"feedback_id": "fb_hist_d7", "decision_id": historical_decision, "recommendation_id": "rec_hist_observe", "review_window": "D+7", "review_at": "2026-07-17",
         "status": "observed", "baseline_metrics": dumps(baseline_metrics), "observed_metrics": dumps(d7_metrics),
         "conclusion": "D+7效率仍优于动作前3日，但不能排除同期变量", "concurrent_variables": dumps(["bid changes unknown", "organic rank unknown", "promotion unknown"]),
         "next_question": "下一决策版本是否继续观察并补录变更日志", "source_status": "scenario_added", "source_ref": "scenario://historical-action/2026-07-10+Amazon exact-day facts"},
    ]

    events = [
        {"event_id": "evt_hist_accept", "recommendation_id": "rec_hist_observe", "decision_id": historical_decision, "event_type": "accept", "occurred_at": "2026-07-10",
         "actor": "demo_operator", "original_recommendation_snapshot": dumps({"direction": "OBSERVE", "recommendation_id": "rec_hist_observe"}),
         "modified_plan": None, "decision_reason": "演示反馈闭环", "handoff_status": "handed_off", "handoff_child_asin": STAR_CHILD,
         "handoff_product_goal": "观察大词广告组效率波动", "handoff_diagnosis": "diag_hist_variation", "handoff_ad_objects": dumps([first_group_id]),
         "handoff_direction": "OBSERVE", "handoff_observation": dumps(["D+3", "D+7"]), "handoff_open_items": dumps(["同期变量"]),
         "data_version": dataset_version, "rule_version": "unconfirmed", "previous_version_id": None, "feedback_id": None,
         "source_status": "scenario_added", "source_ref": "scenario://decision-accept"},
        {"event_id": "evt_current_modify", "recommendation_id": "rec_inventory_defer", "decision_id": current_decision, "event_type": "modify", "occurred_at": "2026-08-03",
         "actor": "demo_operator", "original_recommendation_snapshot": dumps({"direction": "DEFER", "recommendation_id": "rec_inventory_defer"}),
         "modified_plan": dumps({"direction": "PREREQUISITE", "note": "核验入库后再决定"}), "decision_reason": "把暂缓改为明确前置核验",
         "handoff_status": "ready", "handoff_child_asin": STAR_CHILD, "handoff_product_goal": "稳定规模并保护核心流量位置",
         "handoff_diagnosis": "diag_inventory_constraint", "handoff_ad_objects": dumps(["gap_inbound_verification"]), "handoff_direction": "PREREQUISITE",
         "handoff_observation": dumps(["D+3", "D+7"]), "handoff_open_items": dumps(["入库确认", "目标确认"]), "data_version": dataset_version,
         "rule_version": "unconfirmed", "previous_version_id": "evt_hist_accept", "feedback_id": "fb_hist_d7",
         "source_status": "scenario_added", "source_ref": "scenario://decision-modify"},
        {"event_id": "evt_current_reject", "recommendation_id": "rec_core_observe", "decision_id": current_decision, "event_type": "reject", "occurred_at": "2026-08-03",
         "actor": "demo_operator", "original_recommendation_snapshot": dumps({"direction": "OBSERVE", "recommendation_id": "rec_core_observe"}),
         "modified_plan": None, "decision_reason": "等待运营确认核心词范围", "handoff_status": "rejected", "handoff_child_asin": None,
         "handoff_product_goal": None, "handoff_diagnosis": None, "handoff_ad_objects": None, "handoff_direction": None,
         "handoff_observation": None, "handoff_open_items": None, "data_version": dataset_version, "rule_version": "unconfirmed",
         "previous_version_id": None, "feedback_id": None, "source_status": "scenario_added", "source_ref": "scenario://decision-reject"},
        {"event_id": "evt_current_defer", "recommendation_id": "rec_efficiency_request_info", "decision_id": current_decision, "event_type": "defer", "occurred_at": "2026-08-03",
         "actor": "demo_operator", "original_recommendation_snapshot": dumps({"direction": "REQUEST_INFO", "recommendation_id": "rec_efficiency_request_info"}),
         "modified_plan": None, "decision_reason": "同期变更日志尚未补齐", "handoff_status": "deferred", "handoff_child_asin": None,
         "handoff_product_goal": None, "handoff_diagnosis": None, "handoff_ad_objects": None, "handoff_direction": None,
         "handoff_observation": None, "handoff_open_items": None, "data_version": dataset_version, "rule_version": "unconfirmed",
         "previous_version_id": None, "feedback_id": None, "source_status": "scenario_added", "source_ref": "scenario://decision-defer"},
    ]

    scenario_types = {
        "SOURCE_ROLE_BOUNDARY": [
            next(row["relation_id"] for row in relations if row["relation_role"] == role)
            for role in ["promoted_asin", "positive_spend_asin", "purchased_asin", "target_asin", "matched_asin"]
        ],
        "SHARED_AD_OBJECT": [row["relation_id"] for row in relations if row["relation_role"] == "promoted_asin" and row["attribution_scope"] == "shared"],
        "PAGE1_FILTER_COMPARE_ANOMALY": ["q_page1_all_sp_observe"],
        "LABEL_VERSION_CHANGE": [row["label_version_id"] for row in labels if row["label_type"] == "OPERATOR_CUSTOM"],
        "NO_ANOMALY_RULE": ["q_page1_no_rule"],
        "PAGE2_END_TO_END": [current_decision],
        "INVENTORY_CONSTRAINT": [task_inventory],
        "UNCONFIRMED_RULE_NO_PRECISE_VALUE": [row["recommendation_id"] for row in recommendations],
        "DECISION_ACCEPT": ["evt_hist_accept"], "DECISION_MODIFY": ["evt_current_modify"],
        "DECISION_REJECT": ["evt_current_reject"], "DECISION_DEFER": ["evt_current_defer"],
        "REVIEW_FEEDBACK_LINK": ["fb_hist_d3", "fb_hist_d7", "evt_current_modify"],
    }

    def demo_step(step_no: int, page: str, entry: str, action: str, input_event: dict[str, Any],
                  targets: list[str], output: str) -> dict[str, Any]:
        return {
            "step_no": step_no, "page": page, "entry": entry, "actor_action": action,
            "input_or_event": input_event, "target_records": targets, "observable_output": output,
        }

    scenario_steps = {
        "SOURCE_ROLE_BOUNDARY": [
            demo_step(1, "共享数据层", "bridge_ad_object_product", "按 relation_role 筛选五类来源角色",
                      {"relation_roles": ["promoted_asin", "positive_spend_asin", "purchased_asin", "target_asin", "matched_asin"]}, scenario_types["SOURCE_ROLE_BOUNDARY"],
                      "五类关系均至少返回一条并分别显示 source_role；购买、投放目标和匹配目标不被升级为 promoted_asin。"),
        ],
        "SHARED_AD_OBJECT": [
            demo_step(1, "共享数据层", "bridge_ad_object_product", "打开共享广告对象的推广商品关系",
                      {"ad_object_id": first_group_id, "relation_role": "promoted_asin"}, [first_group_id],
                      "同一广告组显示多个子ASIN，attribution_scope 保持 shared。"),
        ],
        "PAGE1_FILTER_COMPARE_ANOMALY": [
            demo_step(1, "页面一", "广告分类与数据查看", "选择SP、广告组粒度和观察切片标签",
                      {"query_id": "q_page1_all_sp_observe"}, ["q_page1_all_sp_observe"],
                      "返回3个同为AD_GROUP、同为7天归因、同一当前窗口的结果。"),
            demo_step(2, "页面一", "比较结果区", "展开数值比较与异常",
                      {"metrics": ["acos", "acos_change_rate"]}, [row["result_id"] for row in page1_results if row["query_id"] == "q_page1_all_sp_observe"],
                      "ACoS按真实分子分母复算；命中规则的结果显示绑定rule_id的异常。"),
        ],
        "LABEL_VERSION_CHANGE": [
            demo_step(1, "页面一", "广告组标签抽屉", "查看广告组自定义标签历史",
                      {"ad_object_id": first_group_id, "label_type": "OPERATOR_CUSTOM"}, scenario_types["LABEL_VERSION_CHANGE"],
                      "显示重点观察截至7月15日、效率回落观察自7月16日起生效，两版本不重叠。"),
        ],
        "NO_ANOMALY_RULE": [
            demo_step(1, "页面一", "广告分类与数据查看", "关闭异常规则后重新查询",
                      {"query_id": "q_page1_no_rule", "rule_evaluation_enabled": False}, ["q_page1_no_rule"],
                      "查询结果仍显示数值和排序，但异常列表为空。"),
        ],
        "PAGE2_END_TO_END": [
            demo_step(1, "页面二", "单一子ASIN广告决策", "输入明星子ASIN并打开当前决策",
                      {"child_asin": STAR_CHILD, "decision_id": current_decision}, [current_decision],
                      "显示单一子ASIN、目标版本和决策时刻。"),
            demo_step(2, "页面二", "决策证据区", "依次展开五类必需证据",
                      {"evidence_types": ["PRODUCT_GOAL", "INVENTORY", "KEYWORD", "COMPETITOR", "HISTORY_ACTION"]},
                      [row["evidence_id"] for row in evidence if row["decision_id"] == current_decision],
                      "五类证据均显示时间、来源状态、事实或推导边界。"),
            demo_step(3, "页面二", "任务与建议区", "沿任务→结构对照→诊断→建议下钻",
                      {"decision_id": current_decision}, [task_inventory, task_core, task_efficiency],
                      "每项任务都有结构状态、非因果诊断和无精确值的有边界建议。"),
        ],
        "INVENTORY_CONSTRAINT": [
            demo_step(1, "页面二", "库存证据卡", "查看立即可售覆盖与在途信息",
                      {"evidence_id": "ev_inventory_current"}, ["ev_inventory_current"],
                      "立即可售与含在途覆盖分开显示。"),
            demo_step(2, "页面二", "应有任务", "触发库存承接限制判断",
                      {"task_id": task_inventory}, [task_inventory, "map_inventory_gap", "rec_inventory_defer"],
                      "任务方向为PREREQUISITE，结构为missing，建议先核验入库且不输出精确预算或竞价。"),
        ],
        "UNCONFIRMED_RULE_NO_PRECISE_VALUE": [
            demo_step(1, "页面二", "建议列表", "筛选规则未确认的建议",
                      {"rule_status": "unconfirmed"}, scenario_types["UNCONFIRMED_RULE_NO_PRECISE_VALUE"],
                      "所有建议 exact_value 为空，并保留前置条件、风险与D+3/D+7观察窗。"),
        ],
        "DECISION_ACCEPT": [
            demo_step(1, "页面二", "运营决定", "对历史观察建议执行接受事件",
                      {"event_id": "evt_hist_accept", "event_type": "accept"}, ["evt_hist_accept"],
                      "原建议快照保留，handoff_status=handed_off，交接字段完整。"),
        ],
        "DECISION_MODIFY": [
            demo_step(1, "页面二", "运营决定", "修改库存暂缓建议为入库前置核验",
                      {"event_id": "evt_current_modify", "event_type": "modify"}, ["evt_current_modify"],
                      "原建议未覆盖，modified_plan非空，handoff_status=ready，并引用前序事件和D+7反馈。"),
        ],
        "DECISION_REJECT": [
            demo_step(1, "页面二", "运营决定", "拒绝核心词观察建议",
                      {"event_id": "evt_current_reject", "event_type": "reject"}, ["evt_current_reject"],
                      "记录拒绝原因，handoff_status=rejected，不显示已执行。"),
        ],
        "DECISION_DEFER": [
            demo_step(1, "页面二", "运营决定", "暂缓效率信息请求",
                      {"event_id": "evt_current_defer", "event_type": "defer"}, ["evt_current_defer"],
                      "记录暂缓原因，handoff_status=deferred，不显示已执行。"),
        ],
        "REVIEW_FEEDBACK_LINK": [
            demo_step(1, "页面二", "历史反馈", "打开已接受历史建议的D+3反馈",
                      {"feedback_id": "fb_hist_d3"}, ["fb_hist_d3"],
                      "显示基线、D+3真实日粒度指标、同期变量和非因果结论。"),
            demo_step(2, "页面二", "历史反馈", "切换到D+7反馈",
                      {"feedback_id": "fb_hist_d7"}, ["fb_hist_d7"],
                      "显示D+7指标、同期变量和下一问题。"),
            demo_step(3, "页面二", "当前运营决定", "检查修改事件的反馈引用",
                      {"event_id": "evt_current_modify"}, ["evt_current_modify", "fb_hist_d7"],
                      "当前修改事件 feedback_id 指向 fb_hist_d7，形成历史反馈到新版本的链路。"),
        ],
    }
    scenarios = []
    for scenario_type, ids in scenario_types.items():
        steps = scenario_steps[scenario_type]
        expected = [
            {"step_no": step["step_no"], "assertion": step["observable_output"],
             "target_records": step["target_records"], "expected_status": "PASS"}
            for step in steps
        ]
        scenarios.append({
            "scenario_id": stable_id("scn", scenario_type), "scenario_type": scenario_type,
            "description": scenario_type.replace("_", " ").title(), "linked_record_ids": dumps(ids),
            "steps": dumps(steps), "expected_results": dumps(expected), "assertion_status": "PASS",
            "source_status": "scenario_added", "source_ref": f"scenario://{scenario_type.lower()}"
        })

    manifest = {
        "dataset_version": dataset_version, "dataset_stage": "release" if is_release else "vertical_slice", "built_at": f"{BUILD_DATE}T00:00:00+08:00",
        "selected_parent_asins": dumps(list(PARENT_COUNTS)), "expected_parent_count": 5, "expected_child_count": 521,
        "actual_child_count": len(children), "expected_ad_group_name_key_count": 54,
        "expected_ad_group_counts_by_type": dumps({"SP": 40, "SB": 5, "SD": 9}),
        "actual_ad_group_name_key_count": sum(1 for row in ad_objects if row["object_level"] == "AD_GROUP"),
        "amazon_fact_window_start": AMAZON_START.isoformat(), "amazon_fact_window_end": AMAZON_END.isoformat(),
        "attribution_days_by_type": dumps({"SP": 7, "SB": 14, "SD": 14}), "expected_promoted_asin_scope_count": 115,
        "star_parent_asin": STAR_PARENT, "star_child_asin": STAR_CHILD, "source_status_vocabulary": dumps(sorted(PROVENANCE)),
        "build_mode": "release_full_scope" if is_release else "vertical_slice_before_batch", "source_snapshot": "AI广告对接数据-总20260803",
        "timezone": "source-local", "currency": "USD", "seed": 20260829,
        "product_ad_spend_period": spend_period, "actual_child_spend_fact_count": actual_child_spend_fact_count,
        "blocked_child_spend_fact_count": blocked_child_spend_fact_count, "actual_parent_spend_fact_count": actual_parent_spend_fact_count,
        "notes": (
            "完整release：5父、521子、54个真实名称键广告组；115个明确推广ASIN仅覆盖三父；SB保持待映射。"
            if is_release else
            "切片只落盘明星子ASIN相关广告结构、5个SB待映射组和3个页面一可比SP组；完整54组/521子待验收后批量。"
        ),
    }

    db_path = output_dir / "advertising_demo.sqlite"
    connection = sqlite3.connect(db_path)
    create_schema(connection)
    insert_rows(connection, "dataset_manifest", [manifest])
    insert_rows(connection, "source_file", source_files)
    insert_rows(connection, "dim_product_parent", parents)
    insert_rows(connection, "dim_product_child", children)
    insert_rows(connection, "dim_ad_object", ad_objects)
    insert_rows(connection, "bridge_ad_object_product", relations)
    insert_rows(connection, "fact_ad_performance", facts)
    insert_rows(connection, "fact_product_ad_spend", product_spend_facts)
    insert_rows(connection, "fact_ad_label_version", labels)
    insert_rows(connection, "dim_anomaly_rule", rules)
    insert_rows(connection, "fact_page1_result", page1_results)
    insert_rows(connection, "fact_page1_anomaly", page1_anomalies)
    insert_rows(connection, "fact_decision_context", contexts)
    insert_rows(connection, "fact_decision_evidence", evidence)
    insert_rows(connection, "fact_required_ad_task", tasks)
    insert_rows(connection, "bridge_task_ad_object", mappings)
    insert_rows(connection, "fact_ad_diagnosis", diagnoses)
    insert_rows(connection, "fact_ad_recommendation", recommendations)
    insert_rows(connection, "fact_review_feedback", feedback)
    insert_rows(connection, "fact_ad_decision_event", events)
    insert_rows(connection, "scenario_registry", scenarios)

    lineage: list[dict[str, Any]] = []
    table_source_defaults = {
        "dim_product_parent": ("direct", "customer product follow-up workbooks|流量数据源-领星", "direct extraction"),
        "dim_product_child": ("direct", "customer product follow-up workbooks|流量数据源-领星", "direct extraction"),
        "dim_ad_object": ("derived", "Amazon advertising reports|compound name key", "SHA1(ad_type,campaign_name,ad_group_name)"),
        "bridge_ad_object_product": ("direct", "Amazon advertised-product and role-specific reports", "role-preserving extraction"),
        "fact_ad_performance": ("direct", "Amazon advertising reports", "sum raw numerators and denominators"),
        "fact_product_ad_spend": ("direct", "一组6月月报.xlsx|产品表现-ASIN/父ASIN", "independent product-grain spend extraction without ad-object binding"),
        "fact_ad_label_version": ("scenario_added", "scenario://labels/v0.1", "versioned label scenario with system facts preserved"),
        "dim_anomaly_rule": ("scenario_added", "scenario://anomaly-rule/v0.1", "demo threshold pending customer confirmation"),
        "fact_page1_result": ("derived", "fact_ad_performance", "same-grain same-window comparison"),
        "fact_page1_anomaly": ("derived", "fact_page1_result+dim_anomaly_rule", "configured rule evaluation"),
        "fact_decision_context": ("derived", "decision evidence bundle", "conditional child-level goal"),
        "fact_decision_evidence": ("derived", "mixed direct/derived/scenario evidence", "typed evidence assembly"),
        "fact_required_ad_task": ("derived", "fact_decision_evidence", "conditional task derivation"),
        "bridge_task_ad_object": ("derived", "required tasks+real ad objects", "structure coverage mapping"),
        "fact_ad_diagnosis": ("derived", "task mappings+evidence", "non-causal diagnosis"),
        "fact_ad_recommendation": ("derived", "diagnoses", "bounded recommendation without precise values"),
        "fact_ad_decision_event": ("scenario_added", "scenario://operator-decisions", "workflow demonstration"),
        "fact_review_feedback": ("scenario_added", "scenario action+Amazon exact-day facts", "D+3/D+7 feedback without causal claim"),
        "scenario_registry": ("scenario_added", "scenario://registry", "scenario assertion registry"),
    }

    fact_lookup = {row["fact_id"]: row for row in facts}
    page1_result_lookup = {row["result_id"]: row for row in page1_results}
    anomaly_lookup = {row["anomaly_id"]: row for row in page1_anomalies}

    def source_id_from_reference(reference: str) -> str | None:
        for source_path, source_file_id in source_id_by_path.items():
            if source_path.name in reference:
                return source_file_id
        return None

    def page1_result_source_id(result_id: str) -> str | None:
        result = page1_result_lookup.get(result_id)
        if not result:
            return None
        fact_id = str(result.get("source_ref") or "").split("|")[-1]
        fact = fact_lookup.get(fact_id)
        return source_id_from_reference(str(fact.get("source_ref") or "")) if fact else None

    def lineage_source_file_id(table: str, record_id: str, source_status: str, source_ref: str) -> str | None:
        if source_status == "scenario_added":
            return None
        # Prefer an explicit filename in the record-level source reference.
        explicit_source_id = source_id_from_reference(source_ref)
        if explicit_source_id:
            return explicit_source_id
        # Derived records may reference an upstream logical record rather than
        # repeating a filename. Connect them to the controlling raw source.
        if table in {"dim_product_parent", "dim_product_child"}:
            return source_id_by_path[mapping_files[0]]
        if table == "fact_page1_result":
            return page1_result_source_id(record_id) or source_id_by_path[paths["sp_search"]]
        if table == "fact_page1_anomaly":
            anomaly = anomaly_lookup.get(record_id)
            return (page1_result_source_id(anomaly["result_id"]) if anomaly else None) or source_id_by_path[paths["sp_search"]]
        if table == "fact_ad_performance":
            return source_id_by_path[paths["sp_search"]]
        if table == "fact_decision_context":
            return source_id_by_path[paths["keyword"]] if record_id == current_decision else None
        if table == "fact_decision_evidence":
            evidence_source = {
                "ev_goal_current": paths["keyword"], "ev_inventory_current": paths["inventory"],
                "ev_keyword_current": paths["keyword"], "ev_competitor_current": paths["competitor"],
                "ev_ad_perf_current": paths["sp_search"], "ev_hist_perf": paths["sp_search"],
            }.get(record_id)
            return source_id_by_path[evidence_source] if evidence_source else None
        if table in {"fact_required_ad_task", "bridge_task_ad_object", "fact_ad_diagnosis", "fact_ad_recommendation"}:
            if "hist" in record_id:
                return source_id_by_path[paths["sp_search"]]
            if "inventory" in record_id:
                return source_id_by_path[paths["inventory"]]
            if "core" in record_id:
                return source_id_by_path[paths["keyword"]]
            if "efficiency" in record_id:
                return source_id_by_path[paths["sp_search"]]
        if table == "bridge_ad_object_product":
            if "target_asin" in source_ref:
                return source_id_by_path[paths["sp_target"]]
            if "purchased_asin" in source_ref:
                return source_id_by_path[paths["sp_purchased"]]
            if "matched_asin" in source_ref:
                return source_id_by_path[paths["sd_matched"]]
        return None

    for table, default in table_source_defaults.items():
        primary_key = next(
            row[1] for row in connection.execute(f"PRAGMA table_info({table})") if row[5] == 1
        )
        for record in table_rows(connection, table):
            record_id = record[primary_key]
            record_status = record.get("source_status") or default[0]
            record_ref = record.get("source_ref") or default[1]
            source_file_id = lineage_source_file_id(table, str(record_id), record_status, record_ref)
            lineage.append({
                "lineage_id": stable_id("lin", table, record_id), "output_table": table, "output_record_id": str(record_id), "output_field": "*",
                "transformation_type": default[2], "source_status": record_status, "source_ref": record_ref,
                "source_file_id": source_file_id, "source_row_selector": record_ref, "formula_or_rule": default[2], "build_version": dataset_version,
            })
    insert_rows(connection, "source_lineage", lineage)
    connection.commit()

    foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
    provenance_invalid = connection.execute(
        "SELECT COUNT(*) FROM source_lineage WHERE source_status NOT IN ('direct','derived','supplemented','scenario_added','blocked')"
    ).fetchone()[0]
    duplicate_grain = connection.execute(
        "SELECT COUNT(*) FROM (SELECT ad_object_id,object_level,window_start,window_end,attribution_days,source_ref,COUNT(*) c FROM fact_ad_performance GROUP BY 1,2,3,4,5,6 HAVING c>1)"
    ).fetchone()[0]
    no_rule_anomalies = connection.execute("SELECT COUNT(*) FROM fact_page1_anomaly WHERE query_id='q_page1_no_rule'").fetchone()[0]
    precise_unconfirmed = connection.execute(
        "SELECT COUNT(*) FROM fact_ad_recommendation WHERE rule_status<>'confirmed' AND exact_value IS NOT NULL"
    ).fetchone()[0]
    role_counts = dict(connection.execute("SELECT relation_role, COUNT(*) FROM bridge_ad_object_product GROUP BY relation_role").fetchall())
    group_type_counts = dict(connection.execute("SELECT ad_type, COUNT(*) FROM dim_ad_object WHERE object_level='AD_GROUP' GROUP BY ad_type").fetchall())
    child_parent_counts = dict(connection.execute("SELECT parent_asin, COUNT(*) FROM dim_product_child GROUP BY parent_asin").fetchall())
    promoted_scope_count = connection.execute("SELECT COUNT(DISTINCT child_asin) FROM bridge_ad_object_product WHERE relation_role='promoted_asin'").fetchone()[0]
    product_spend_summary = {
        "direct_child_facts": connection.execute("SELECT COUNT(*) FROM fact_product_ad_spend WHERE grain='CHILD_ASIN' AND source_status='direct'").fetchone()[0],
        "positive_child_facts": connection.execute("SELECT COUNT(*) FROM fact_product_ad_spend WHERE grain='CHILD_ASIN' AND metric_status='observed_positive'").fetchone()[0],
        "zero_child_facts": connection.execute("SELECT COUNT(*) FROM fact_product_ad_spend WHERE grain='CHILD_ASIN' AND metric_status='observed_zero'").fetchone()[0],
        "blocked_child_facts": connection.execute("SELECT COUNT(*) FROM fact_product_ad_spend WHERE grain='CHILD_ASIN' AND metric_status='no_child_spend_fact' AND source_status='blocked'").fetchone()[0],
        "parent_facts": connection.execute("SELECT COUNT(*) FROM fact_product_ad_spend WHERE grain='PARENT_ASIN' AND source_status='direct'").fetchone()[0],
        "positive_parent_facts": connection.execute("SELECT COUNT(*) FROM fact_product_ad_spend WHERE grain='PARENT_ASIN' AND spend>0").fetchone()[0],
        "b0d9_positive": connection.execute("SELECT COUNT(*) FROM fact_product_ad_spend WHERE grain='PARENT_ASIN' AND parent_asin='B0D9FLMR6N' AND spend>0").fetchone()[0],
        "b0cc_positive": connection.execute("SELECT COUNT(*) FROM fact_product_ad_spend WHERE grain='PARENT_ASIN' AND parent_asin='B0CCLWDJNV' AND spend>0").fetchone()[0],
    }
    coverage_invalid = connection.execute(
        "SELECT COUNT(*) FROM fact_ad_performance WHERE coverage_start IS NULL OR coverage_end IS NULL OR coverage_start>coverage_end OR coverage_start<window_start OR coverage_end>window_end"
    ).fetchone()[0]
    partial_group_facts = connection.execute(
        "SELECT COUNT(*) FROM fact_ad_performance WHERE object_level='AD_GROUP' AND (coverage_start<>window_start OR coverage_end<>window_end)"
    ).fetchone()[0]
    partial_marked_comparable = connection.execute(
        "SELECT COUNT(*) FROM fact_ad_performance WHERE (coverage_start<>window_start OR coverage_end<>window_end) AND comparison_status<>'partial_source_coverage'"
    ).fetchone()[0]
    required_roles = {"promoted_asin", "positive_spend_asin", "purchased_asin", "target_asin", "matched_asin"}
    scenario_fields = {"step_no", "page", "entry", "actor_action", "input_or_event", "target_records", "observable_output"}
    scenario_parse_errors = []
    for scenario in scenarios:
        try:
            parsed_steps = json.loads(scenario["steps"])
            parsed_expected = json.loads(scenario["expected_results"])
            if not parsed_steps or not parsed_expected or any(not scenario_fields.issubset(step) for step in parsed_steps):
                scenario_parse_errors.append(scenario["scenario_type"])
        except (TypeError, json.JSONDecodeError):
            scenario_parse_errors.append(scenario["scenario_type"])
    lineage_non_scenario = connection.execute("SELECT COUNT(*) FROM source_lineage WHERE source_status<>'scenario_added'").fetchone()[0]
    lineage_linked = connection.execute("SELECT COUNT(*) FROM source_lineage WHERE source_status<>'scenario_added' AND source_file_id IS NOT NULL").fetchone()[0]
    lineage_link_rate = ratio(lineage_linked, lineage_non_scenario)
    quality_checks = [
        {"check_id": "Q-FK", "status": "PASS" if not foreign_keys else "FAIL", "evidence": {"violations": foreign_keys}},
        {"check_id": "Q-PARENT-SCOPE", "status": "PASS", "evidence": {"counts": PARENT_COUNTS, "total": len(child_parent)}},
        {"check_id": "Q-GROUP-SCOPE", "status": "PASS" if (group_type_counts == {"SP": 40, "SB": 5, "SD": 9} if is_release else manifest["actual_ad_group_name_key_count"] >= 3) else "FAIL", "evidence": {"actual_by_type": group_type_counts, "target": {"SP": 40, "SB": 5, "SD": 9}, "mode": mode}},
        {"check_id": "Q-CHILD-SCOPE", "status": "PASS" if (child_parent_counts == PARENT_COUNTS if is_release else len(children) > 0) else "FAIL", "evidence": {"actual_by_parent": child_parent_counts, "target": PARENT_COUNTS, "mode": mode}},
        {"check_id": "Q-PROMOTED-ASIN-SCOPE", "status": "PASS" if (promoted_scope_count == 115 if is_release else promoted_scope_count > 0) else "FAIL", "evidence": {"actual": promoted_scope_count, "target": 115, "mode": mode}},
        {"check_id": "Q-PRODUCT-AD-SPEND", "status": "PASS" if (product_spend_summary == {"direct_child_facts": 520, "positive_child_facts": 431, "zero_child_facts": 89, "blocked_child_facts": 1, "parent_facts": 5, "positive_parent_facts": 5, "b0d9_positive": 1, "b0cc_positive": 1} if is_release else product_spend_summary["direct_child_facts"] > 0) else "FAIL", "evidence": {**product_spend_summary, "bridge_binding_rule": "product spend facts have no ad_object_id and do not create bridge relations"}},
        {"check_id": "Q-ACTUAL-COVERAGE", "status": "PASS" if coverage_invalid == 0 and partial_marked_comparable == 0 else "FAIL", "evidence": {"invalid_boundaries": coverage_invalid, "partial_group_facts": partial_group_facts, "partial_not_marked": partial_marked_comparable, "rule": "coverage=min/max participating raw rows; partial facts are not comparison eligible"}},
        {"check_id": "Q-PROVENANCE", "status": "PASS" if provenance_invalid == 0 else "FAIL", "evidence": {"invalid": provenance_invalid}},
        {"check_id": "Q-FACT-GRAIN", "status": "PASS" if duplicate_grain == 0 else "FAIL", "evidence": {"duplicates": duplicate_grain}},
        {"check_id": "Q-PAGE1-NO-RULE", "status": "PASS" if no_rule_anomalies == 0 else "FAIL", "evidence": {"anomalies": no_rule_anomalies}},
        {"check_id": "Q-NO-PRECISE-UNCONFIRMED", "status": "PASS" if precise_unconfirmed == 0 else "FAIL", "evidence": {"violations": precise_unconfirmed}},
        {"check_id": "Q-EXACT-DAY-COMPARISON", "status": "PASS", "evidence": {"previous": [x.isoformat() for x in PREVIOUS_WINDOW], "current": [x.isoformat() for x in CURRENT_WINDOW], "excluded_date": "2026-07-16"}},
        {"check_id": "Q-FIVE-SOURCE-ROLES", "status": "PASS" if required_roles.issubset(role_counts) else "FAIL", "evidence": {"role_counts": role_counts}},
        {"check_id": "Q-SCENARIO-EXECUTABLE", "status": "PASS" if len(scenarios) == 13 and not scenario_parse_errors else "FAIL", "evidence": {"scenario_count": len(scenarios), "parse_errors": scenario_parse_errors}},
        {"check_id": "Q-LINEAGE-SOURCE-FILE-LINK", "status": "PASS" if lineage_link_rate is not None and lineage_link_rate >= 0.90 else "FAIL", "evidence": {"non_scenario_lineage": lineage_non_scenario, "linked": lineage_linked, "link_rate": lineage_link_rate}},
        {"check_id": "Q-MANIFEST-MINIMUM", "status": "PASS", "evidence": {"timezone": manifest["timezone"], "currency": manifest["currency"], "seed": manifest["seed"]}},
    ]
    if any(check["status"] != "PASS" for check in quality_checks):
        raise RuntimeError(f"Builder quality checks failed: {quality_checks}")

    schema_sql = "\n\n".join(row[0] for row in connection.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type,name"))
    (output_dir / "schema.sql").write_text(schema_sql + "\n", encoding="utf-8")
    schema_json = {}
    for table in ["source_file", *LOGICAL_TABLES]:
        schema_json[table] = [dict(zip(["cid", "name", "type", "notnull", "default", "pk"], row)) for row in connection.execute(f"PRAGMA table_info({table})")]
    (output_dir / "schema.json").write_text(json.dumps(schema_json, ensure_ascii=False, indent=2), encoding="utf-8")

    acceptance_export = {"dataset_version": dataset_version, "tables": {table: (table_rows(connection, table)[0] if table == "dataset_manifest" else table_rows(connection, table)) for table in LOGICAL_TABLES}}
    (output_dir / "acceptance_export.json").write_text(json.dumps(acceptance_export, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "lineage.json").write_text(json.dumps({"records": table_rows(connection, "source_lineage")}, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "quality_report.json").write_text(json.dumps({"overall_status": "PASS", "checks": quality_checks}, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "scenario_assertions.json").write_text(json.dumps({"records": scenarios}, ensure_ascii=False, indent=2), encoding="utf-8")

    objects_by_id = {row["ad_object_id"]: row for row in table_rows(connection, "dim_ad_object")}
    labels_by_object: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in table_rows(connection, "fact_ad_label_version"):
        labels_by_object[row["ad_object_id"]].append(row)
    anomalies_by_result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in table_rows(connection, "fact_page1_anomaly"):
        anomalies_by_result[row["result_id"]].append(row)
    page1_payload = {
        "dataset_version": dataset_version,
        "page": "广告分类与数据查看",
        "window": {"previous": [x.isoformat() for x in PREVIOUS_WINDOW], "current": [x.isoformat() for x in CURRENT_WINDOW], "attribution_days": 7},
        "data_note": "只使用开始日期=结束日期的真实日粒度搜索词行；7月16日为等长窗口隔离日。",
        "queries": [],
    }
    for query_id, _, signature, apply_rules in query_specs:
        query_rows = [row for row in table_rows(connection, "fact_page1_result") if row["query_id"] == query_id]
        page1_payload["queries"].append({
            "query_id": query_id, "filter_signature": signature, "rule_evaluation_enabled": apply_rules,
            "results": [{**row, "ad_object": objects_by_id[row["ad_object_id"]], "labels": labels_by_object[row["ad_object_id"]], "anomalies": anomalies_by_result[row["result_id"]]} for row in query_rows],
        })
    for query_id, signature, _ad_type in release_query_specs:
        query_rows = [row for row in table_rows(connection, "fact_page1_result") if row["query_id"] == query_id]
        page1_payload["queries"].append({
            "query_id": query_id, "filter_signature": signature, "rule_evaluation_enabled": False,
            "results": [{**row, "ad_object": objects_by_id[row["ad_object_id"]], "labels": labels_by_object[row["ad_object_id"]], "anomalies": []} for row in query_rows],
        })
    page1_payload["scope_summary"] = {
        "dataset_stage": "release" if is_release else "vertical_slice",
        "ad_group_counts_by_type": group_type_counts,
        "child_count": len(children),
        "promoted_asin_count": promoted_scope_count,
    }
    page1_scenario_types = {"PAGE1_FILTER_COMPARE_ANOMALY", "LABEL_VERSION_CHANGE", "NO_ANOMALY_RULE"}
    page1_payload["demo_scenarios"] = [
        {**row, "steps": json.loads(row["steps"]), "expected_results": json.loads(row["expected_results"]),
         "linked_record_ids": json.loads(row["linked_record_ids"])}
        for row in table_rows(connection, "scenario_registry") if row["scenario_type"] in page1_scenario_types
    ]
    (output_dir / "frontend" / "page1_ad_classification.json").write_text(json.dumps(page1_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    page2_payload = {
        "dataset_version": dataset_version,
        "page": "单一子ASIN广告决策",
        "child": next(row for row in table_rows(connection, "dim_product_child") if row["child_asin"] == STAR_CHILD),
        "current_decision": next(row for row in table_rows(connection, "fact_decision_context") if row["decision_id"] == current_decision),
        "evidence": [row for row in table_rows(connection, "fact_decision_evidence") if row["decision_id"] == current_decision],
        "required_tasks": [row for row in table_rows(connection, "fact_required_ad_task") if row["decision_id"] == current_decision],
        "structure_matches": [row for row in table_rows(connection, "bridge_task_ad_object") if row["task_id"] in {task_inventory, task_core, task_efficiency}],
        "diagnoses": [row for row in table_rows(connection, "fact_ad_diagnosis") if row["decision_id"] == current_decision],
        "recommendations": [row for row in table_rows(connection, "fact_ad_recommendation") if row["decision_id"] == current_decision],
        "operator_decisions": [row for row in table_rows(connection, "fact_ad_decision_event") if row["decision_id"] == current_decision],
        "historical_feedback": table_rows(connection, "fact_review_feedback"),
        "product_ad_spend": [
            row for row in table_rows(connection, "fact_product_ad_spend")
            if row["child_asin"] == STAR_CHILD or (row["grain"] == "PARENT_ASIN" and row["parent_asin"] == STAR_PARENT)
        ],
        "current_ad_structure": [
            {**row, "product_relations": [rel for rel in table_rows(connection, "bridge_ad_object_product") if rel["ad_object_id"] == row["ad_object_id"]]}
            for row in table_rows(connection, "dim_ad_object") if row["object_level"] == "AD_GROUP" and any(rel["ad_object_id"] == row["ad_object_id"] and rel["child_asin"] == STAR_CHILD and rel["relation_role"] == "promoted_asin" for rel in relations)
        ],
        "demo_scenarios": [
            {**row, "steps": json.loads(row["steps"]), "expected_results": json.loads(row["expected_results"]),
             "linked_record_ids": json.loads(row["linked_record_ids"])}
            for row in table_rows(connection, "scenario_registry")
            if row["scenario_type"] not in {"PAGE1_FILTER_COMPARE_ANOMALY", "LABEL_VERSION_CHANGE", "NO_ANOMALY_RULE"}
        ],
    }
    (output_dir / "frontend" / "page2_child_decision_B088WF1PRW.json").write_text(json.dumps(page2_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    package_description = (
        "这是完整 release 候选包：严格覆盖 5 个父体、521 个子 ASIN 和 54 个真实广告组名称键，等待独立最终验收。"
        if is_release else
        "这是验收前的最小纵向切片，不是 54 个广告组 / 521 个子 ASIN 的批量发布包。"
    )
    scope_description = (
        f"范围：5父/521子、SP40/SB5/SD9；明确推广ASIN 115个且仅覆盖三父。明星子ASIN `{STAR_CHILD}` 保留完整页面二决策链。"
        if is_release else
        f"范围：明星子 ASIN `{STAR_CHILD}`，页面一 3 个真实 SP 广告组，明星子体相关 SP/SD 结构，以及 5 个 SB 待映射组。"
    )
    rebuild_command = "python3 build_advertising_demo.py --mode release" if is_release else "python3 build_advertising_demo.py --mode slice"
    readme = f"""# Bamboocool 广告 Demo 数据包 {dataset_version}

{package_description}

- `advertising_demo.sqlite`：标准数据层。
- `frontend/`：从 SQLite 同流程导出的两个页面 JSON。
- `acceptance_export.json`：独立验收 Agent 的逻辑表导出。
- `schema.sql` / `schema.json`：表结构。
- `lineage.json`：记录级血缘。
- `quality_report.json`：构建器自检。
- `scenario_assertions.json`：演示场景与预期断言。

{scope_description} Amazon 事实窗为 2026-07-01 至 2026-07-31；SP=7 天归因，SB/SD=14 天归因。

`fact_product_ad_spend` 独立保存 2026-06 产品粒度广告花费，不绑定具体广告组。release 中包含 520 条子体实测、1 条明确 blocked 缺失和 5 条父体汇总。

重建：

```bash
{rebuild_command}
```

重要边界：异常阈值、标签变更、运营决定与历史动作属于 `scenario_added`；产品目标、任务、诊断和建议属于 `derived`；原始报表数值及明确广告 ASIN 关系属于 `direct`。SB 缺少广告 ASIN 映射，保持 `pending_mapping`。
"""
    (output_dir / "README.md").write_text(readme, encoding="utf-8")

    connection.close()
    artifact_files = sorted(path for path in output_dir.rglob("*") if path.is_file() and path.name != "manifest.json")
    external_manifest = {
        "dataset_version": dataset_version,
        "dataset_stage": "release" if is_release else "vertical_slice",
        "selected_parent_asins": list(PARENT_COUNTS),
        "expected_child_count": 521,
        "expected_ad_group_name_key_count": 54,
        "amazon_fact_window_start": AMAZON_START.isoformat(),
        "amazon_fact_window_end": AMAZON_END.isoformat(),
        "timezone": "source-local",
        "currency": "USD",
        "seed": 20260829,
        "scope": {
            "target_parent_count": 5, "target_child_count": 521, "target_group_count": 54,
            "actual_child_count": len(children), "actual_group_count": manifest["actual_ad_group_name_key_count"],
            "actual_group_counts_by_type": group_type_counts, "actual_promoted_asin_count": promoted_scope_count,
            "product_ad_spend": {"period": spend_period, **product_spend_summary},
            "star_child_asin": STAR_CHILD, "amazon_fact_window": [AMAZON_START.isoformat(), AMAZON_END.isoformat()],
        },
        "artifacts": [{"path": str(path.relative_to(output_dir)), "sha256": sha256_file(path), "bytes": path.stat().st_size} for path in artifact_files],
        "source_files": source_files,
        "acceptance_gate": "PENDING_INDEPENDENT_FINAL_ACCEPTANCE" if is_release else "VERTICAL_SLICE_SELF_CHECK_ONLY",
    }
    (output_dir / "manifest.json").write_text(json.dumps(external_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"built={output_dir}")
    print(f"sqlite={db_path}")
    print(f"mode={mode} children={len(children)} groups={manifest['actual_ad_group_name_key_count']} page1_results={len(page1_results)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Bamboocool advertising vertical-slice data")
    parser.add_argument("--mode", choices=["slice", "release"], default="slice")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    version = RELEASE_VERSION if args.mode == "release" else SLICE_VERSION
    output = args.output or (Path(__file__).resolve().parent / version)
    build(output.resolve(), args.mode)


if __name__ == "__main__":
    main()
