#!/usr/bin/env python3
"""Build the Bamboocool advertising demo data layer v0.2.0.

v0.1.0 ingested 8 of the 31 ad reports. v0.2.0 ingests all 31, adds the
Campaign / placement / audience layers, a real daily fact table, year-over-year,
budget loss, invalid traffic, category benchmark and search-term share.

Design commitments
------------------
* v0.1.0 is never modified. Its ad_object_ids are REUSED so the page-2
  decision chain (B088WF1PRW) keeps resolving.
* Two number systems are stored side by side and never summed together:
    - month authoritative  (metric_basis='report_month_total',   direct)
    - daily comparable     (metric_basis='search_term_exact_day_sum', direct)
    - daily scaled         (metric_basis='daily_scaled_to_month',  derived)
* Every inference is labelled: source_status in
  direct / derived / supplemented / scenario_added / blocked.
* Labels derived from the operator's campaign naming convention are stored as
  label_source='auto_mapping' with confirmation_status='pending' -- never
  presented as operator-confirmed.

Usage: /usr/bin/python3 build_v0_2_0.py
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "lib"))
import adsrc  # noqa: E402

V010 = os.path.join(HERE, "v0.1.0", "advertising_demo.sqlite")
OUT_DIR = os.path.join(HERE, "v0.2.0")
OUT_DB = os.path.join(OUT_DIR, "advertising_demo.sqlite")

DATASET_VERSION = "v0.2.0"
WINDOW = ("2026-07-01", "2026-07-31")
ATTRIB = {"SP": 7, "SB": 14, "SD": 14}
SEED = 20260830
MIN_DAYS_FOR_TREND = 20

STATUS = ("direct", "derived", "supplemented", "scenario_added", "blocked")

# ---------------------------------------------------------------------- schema

SCHEMA = """
CREATE TABLE dataset_manifest (
    dataset_version TEXT PRIMARY KEY,
    dataset_stage TEXT NOT NULL,
    built_at TEXT NOT NULL,
    amazon_fact_window_start TEXT NOT NULL,
    amazon_fact_window_end TEXT NOT NULL,
    attribution_days_by_type TEXT NOT NULL,
    timezone TEXT NOT NULL,
    currency TEXT NOT NULL,
    seed INTEGER NOT NULL,
    source_file_count INTEGER NOT NULL,
    notes TEXT NOT NULL
);

CREATE TABLE source_file (
    source_file_id TEXT PRIMARY KEY,
    relative_path TEXT NOT NULL UNIQUE,
    sha256 TEXT NOT NULL,
    source_system TEXT NOT NULL,
    encoding TEXT NOT NULL,
    row_count INTEGER NOT NULL,
    used_for TEXT NOT NULL
);

CREATE TABLE dim_campaign (
    campaign_id TEXT PRIMARY KEY,
    ad_type TEXT NOT NULL,
    campaign_name TEXT NOT NULL,
    portfolio_name TEXT,
    state TEXT,
    budget REAL,
    recommended_budget REAL,
    time_in_budget REAL,
    targeting_type TEXT,
    bid_strategy TEXT,
    product_line TEXT,
    owner TEXT,
    lifecycle TEXT,
    name_dims TEXT NOT NULL,
    unknown_tokens TEXT NOT NULL,
    has_july_delivery INTEGER NOT NULL,
    source_status TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    UNIQUE(ad_type, campaign_name)
);

CREATE TABLE dim_ad_object (
    ad_object_id TEXT PRIMARY KEY,
    object_level TEXT NOT NULL CHECK(object_level IN ('CAMPAIGN','AD_GROUP','TARGET')),
    ad_type TEXT NOT NULL CHECK(ad_type IN ('SP','SB','SD')),
    campaign_id TEXT REFERENCES dim_campaign(campaign_id),
    campaign_name TEXT NOT NULL,
    ad_group_name TEXT,
    target_text TEXT,
    match_type TEXT,
    parent_ad_object_id TEXT REFERENCES dim_ad_object(ad_object_id),
    key_kind TEXT NOT NULL,
    is_system_named INTEGER NOT NULL,
    mapping_status TEXT NOT NULL,
    source_status TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    carried_from_v010 INTEGER NOT NULL
);

CREATE TABLE dim_placement (
    placement_id TEXT PRIMARY KEY,
    ad_type TEXT NOT NULL,
    campaign_id TEXT REFERENCES dim_campaign(campaign_id),
    campaign_name TEXT NOT NULL,
    placement TEXT NOT NULL,
    bid_strategy TEXT,
    source_status TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    UNIQUE(ad_type, campaign_name, placement)
);

CREATE TABLE dim_audience (
    audience_id TEXT PRIMARY KEY,
    ad_type TEXT NOT NULL,
    campaign_id TEXT REFERENCES dim_campaign(campaign_id),
    campaign_name TEXT NOT NULL,
    audience_name TEXT NOT NULL,
    source_status TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    UNIQUE(ad_type, campaign_name, audience_name)
);

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
    comparison_status TEXT NOT NULL,
    metric_basis TEXT NOT NULL,
    impressions REAL,
    clicks REAL,
    spend REAL,
    orders REAL,
    ad_sales REAL,
    ctr REAL,
    cpc REAL,
    cvr REAL,
    acos REAL,
    roas REAL,
    ad_sku_sales REAL,
    other_sku_sales REAL,
    top_of_search_is REAL,
    currency TEXT NOT NULL,
    source_system TEXT NOT NULL,
    source_status TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    source_row_filter TEXT NOT NULL,
    UNIQUE(ad_object_id, window_start, window_end, metric_basis)
);

CREATE TABLE fact_ad_daily (
    daily_id TEXT PRIMARY KEY,
    ad_object_id TEXT NOT NULL REFERENCES dim_ad_object(ad_object_id),
    object_level TEXT NOT NULL,
    ad_type TEXT NOT NULL,
    stat_date TEXT NOT NULL,
    metric_basis TEXT NOT NULL,
    impressions REAL,
    clicks REAL,
    spend REAL,
    orders REAL,
    ad_sales REAL,
    ctr REAL,
    cpc REAL,
    cvr REAL,
    acos REAL,
    roas REAL,
    scale_factor_spend REAL,
    day_coverage INTEGER NOT NULL,
    daily_confidence TEXT NOT NULL,
    currency TEXT NOT NULL,
    source_status TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    UNIQUE(ad_object_id, stat_date, metric_basis)
);

CREATE TABLE fact_ad_yoy (
    yoy_id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL REFERENCES dim_campaign(campaign_id),
    ad_type TEXT NOT NULL,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    impressions REAL,
    impressions_ly REAL,
    clicks REAL,
    clicks_ly REAL,
    spend REAL,
    spend_ly REAL,
    cpc REAL,
    cpc_ly REAL,
    impressions_change REAL,
    clicks_change REAL,
    spend_change REAL,
    cpc_change REAL,
    source_status TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    UNIQUE(campaign_id, window_start, window_end)
);

CREATE TABLE fact_budget (
    budget_id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL REFERENCES dim_campaign(campaign_id),
    ad_type TEXT NOT NULL,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    budget REAL,
    recommended_budget REAL,
    time_in_budget REAL,
    lost_impressions_min REAL,
    lost_impressions_max REAL,
    lost_clicks_min REAL,
    lost_clicks_max REAL,
    lost_sales_min REAL,
    lost_sales_max REAL,
    source_status TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    UNIQUE(campaign_id, window_start, window_end)
);

CREATE TABLE fact_invalid_traffic (
    invalid_id TEXT PRIMARY KEY,
    campaign_id TEXT REFERENCES dim_campaign(campaign_id),
    ad_type TEXT NOT NULL,
    campaign_name TEXT NOT NULL,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    state TEXT,
    total_impressions REAL,
    valid_impressions REAL,
    invalid_impressions REAL,
    invalid_impression_rate REAL,
    total_clicks REAL,
    valid_clicks REAL,
    invalid_clicks REAL,
    invalid_click_rate REAL,
    source_status TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    UNIQUE(ad_type, campaign_name, window_start, window_end)
);

CREATE TABLE fact_category_benchmark (
    benchmark_id TEXT PRIMARY KEY,
    brand TEXT NOT NULL,
    category TEXT NOT NULL,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    own_impressions REAL,
    peer_impressions_p25 REAL,
    peer_impressions_median REAL,
    peer_impressions_p75 REAL,
    own_ctr REAL,
    peer_ctr_p25 REAL,
    peer_ctr_median REAL,
    peer_ctr_p75 REAL,
    own_acos REAL,
    peer_acos_p75 REAL,
    peer_acos_median REAL,
    peer_acos_p25 REAL,
    own_roas REAL,
    peer_roas_p25 REAL,
    peer_roas_median REAL,
    peer_roas_p75 REAL,
    source_status TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    UNIQUE(brand, category, window_start, window_end)
);

CREATE TABLE fact_search_term_share (
    share_id TEXT PRIMARY KEY,
    ad_type TEXT NOT NULL,
    campaign_name TEXT,
    ad_group_name TEXT,
    search_term TEXT NOT NULL,
    target_text TEXT,
    match_type TEXT,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    impression_rank REAL,
    impression_share REAL,
    impressions REAL,
    clicks REAL,
    spend REAL,
    orders REAL,
    ad_sales REAL,
    source_status TEXT NOT NULL,
    source_ref TEXT NOT NULL
);

CREATE TABLE fact_placement (
    placement_fact_id TEXT PRIMARY KEY,
    placement_id TEXT NOT NULL REFERENCES dim_placement(placement_id),
    campaign_id TEXT REFERENCES dim_campaign(campaign_id),
    ad_type TEXT NOT NULL,
    placement TEXT NOT NULL,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    attribution_days INTEGER NOT NULL,
    impressions REAL,
    clicks REAL,
    spend REAL,
    orders REAL,
    ad_sales REAL,
    ctr REAL,
    cpc REAL,
    acos REAL,
    roas REAL,
    source_status TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    UNIQUE(placement_id, window_start, window_end)
);

CREATE TABLE fact_audience (
    audience_fact_id TEXT PRIMARY KEY,
    audience_id TEXT NOT NULL REFERENCES dim_audience(audience_id),
    campaign_id TEXT REFERENCES dim_campaign(campaign_id),
    ad_type TEXT NOT NULL,
    audience_name TEXT NOT NULL,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    impressions REAL,
    clicks REAL,
    spend REAL,
    orders REAL,
    ad_sales REAL,
    ctr REAL,
    cpc REAL,
    roas REAL,
    source_status TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    UNIQUE(audience_id, window_start, window_end)
);

CREATE TABLE fact_creative (
    creative_id TEXT PRIMARY KEY,
    ad_object_id TEXT REFERENCES dim_ad_object(ad_object_id),
    ad_type TEXT NOT NULL,
    campaign_name TEXT NOT NULL,
    ad_group_name TEXT,
    creative_kind TEXT NOT NULL CHECK(creative_kind IN ('video','prompt')),
    creative_detail TEXT NOT NULL,
    ad_sku TEXT,
    ad_asin TEXT,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    impressions REAL,
    clicks REAL,
    spend REAL,
    orders REAL,
    ad_sales REAL,
    ctr REAL,
    cpc REAL,
    acos REAL,
    roas REAL,
    view_5s REAL,
    view_5s_rate REAL,
    source_status TEXT NOT NULL,
    source_ref TEXT NOT NULL
);

CREATE TABLE bridge_ad_object_product (
    relation_id TEXT PRIMARY KEY,
    ad_object_id TEXT NOT NULL REFERENCES dim_ad_object(ad_object_id),
    child_asin TEXT NOT NULL,
    relation_role TEXT NOT NULL CHECK(relation_role IN
        ('promoted_asin','positive_spend_asin','purchased_asin',
         'target_asin','matched_asin')),
    attribution_scope TEXT NOT NULL CHECK(attribution_scope IN
        ('direct','shared','unattributed')),
    effective_from TEXT NOT NULL,
    effective_to TEXT,
    source_status TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    source_role TEXT NOT NULL,
    is_scope_product INTEGER NOT NULL,
    UNIQUE(ad_object_id, child_asin, relation_role)
);

CREATE TABLE fact_ad_label_version (
    label_version_id TEXT PRIMARY KEY,
    ad_object_id TEXT NOT NULL REFERENCES dim_ad_object(ad_object_id),
    label_type TEXT NOT NULL,
    label_value TEXT NOT NULL,
    label_source TEXT NOT NULL CHECK(label_source IN
        ('system_attribute','auto_mapping','group_inherited',
         'ai_suggested','operator_confirmed')),
    confirmation_status TEXT NOT NULL CHECK(confirmation_status IN
        ('confirmed','pending','rejected','unrecognized')),
    effective_from TEXT NOT NULL,
    effective_to TEXT,
    inherited_from_object_id TEXT,
    basis TEXT NOT NULL,
    source_status TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    UNIQUE(ad_object_id, label_type, label_value, effective_from)
);

CREATE TABLE dim_anomaly_rule (
    rule_id TEXT PRIMARY KEY,
    rule_name TEXT NOT NULL,
    rule_class TEXT NOT NULL CHECK(rule_class IN
        ('absolute_threshold','self_history','peer_deviation','data_state')),
    metric_name TEXT NOT NULL,
    operator TEXT NOT NULL,
    threshold REAL,
    enabled INTEGER NOT NULL,
    rule_status TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    applies_to TEXT NOT NULL,
    source_status TEXT NOT NULL,
    source_ref TEXT NOT NULL
);

CREATE TABLE source_lineage (
    lineage_id TEXT PRIMARY KEY,
    output_table TEXT NOT NULL,
    output_record_id TEXT NOT NULL,
    output_field TEXT NOT NULL,
    transformation_type TEXT NOT NULL,
    source_status TEXT NOT NULL,
    source_file_id TEXT REFERENCES source_file(source_file_id),
    source_row_selector TEXT NOT NULL,
    formula_or_rule TEXT NOT NULL,
    build_version TEXT NOT NULL
);

CREATE INDEX idx_obj_level ON dim_ad_object(object_level, ad_type);
CREATE INDEX idx_obj_campaign ON dim_ad_object(campaign_id);
CREATE INDEX idx_perf_obj ON fact_ad_performance(ad_object_id, metric_basis);
CREATE INDEX idx_daily_obj ON fact_ad_daily(ad_object_id, metric_basis, stat_date);
CREATE INDEX idx_daily_date ON fact_ad_daily(stat_date, ad_type);
CREATE INDEX idx_bridge_obj ON bridge_ad_object_product(ad_object_id, relation_role);
CREATE INDEX idx_bridge_child ON bridge_ad_object_product(child_asin, relation_role);
CREATE INDEX idx_label_obj ON fact_ad_label_version(ad_object_id, label_type);
CREATE INDEX idx_share_term ON fact_search_term_share(search_term);
CREATE INDEX idx_lineage_out ON source_lineage(output_table, output_record_id);
"""

# Tables copied verbatim from v0.1.0 (product scope + the page-2 decision chain
# + the 59-row page1 regression baseline).
CARRY_TABLES = [
    "dim_product_parent",
    "dim_product_child",
    "fact_product_ad_spend",
    "fact_decision_context",
    "fact_decision_evidence",
    "fact_required_ad_task",
    "bridge_task_ad_object",
    "fact_ad_diagnosis",
    "fact_ad_recommendation",
    "fact_ad_decision_event",
    "fact_review_feedback",
    "fact_page1_result",
    "fact_page1_anomaly",
    "scenario_registry",
]

# Every ad report, with the role it plays in v0.2.0.
REPORTS = {
    "商品推广_广告活动_报告.csv": "SP campaign dimension + yoy",
    "商品推广_预算_报告.csv": "SP budget and budget-loss",
    "商品推广_广告位_报告.xlsx": "SP placement dimension and month facts",
    "商品推广_受众_报告.xlsx": "SP audience dimension and month facts",
    "商品推广_投放_报告.xlsx": "SP target month facts (authoritative)",
    "商品推广_推广的商品_报告.xlsx": "SP promoted ASIN relations + ad-group month facts",
    "商品推广_搜索词_报告.xlsx": "SP daily comparable series + search terms",
    "商品推广_搜索词展示量份额_报告.csv": "SP search-term impression share",
    "商品推广_已购买商品_报告.xlsx": "SP purchased ASIN relations",
    "商品推广_视频_报告.xlsx": "SP video creative facts",
    "商品推广_提示词_报告.xlsx": "SP prompt facts",
    "商品推广_总流量和无效流量_报告.xlsx": "SP invalid traffic",
    "商品推广_按时间查看效果_报告.xlsx": "SP account-level month total (sanity only)",
    "品牌推广_广告活动_报告.xlsx": "SB campaign dimension",
    "品牌推广_广告活动广告位_报告.xlsx": "SB placement dimension",
    "品牌推广_关键词_报告.xlsx": "SB target month facts",
    "品牌推广_关键词广告位_报告.xlsx": "SB keyword placement (empty in this pull)",
    "品牌推广_搜索词_报告.xlsx": "SB daily comparable series",
    "品牌推广_搜索词展示量份额_报告.csv": "SB search-term impression share",
    "品牌推广_归因于广告的购买_报告.csv": "SB purchased ASIN relations",
    "品牌推广_提示词_报告.xlsx": "SB creative prompt facts",
    "品牌推广_总流量和无效流量_报告.xlsx": "SB invalid traffic",
    "品牌推广_品类基准_报告.csv": "category benchmark (external reference)",
    "展示型推广_广告活动_报告.xlsx": "SD campaign dimension",
    "展示型推广_投放_报告.xlsx": "SD target month facts",
    "展示型推广_推广的商品_报告.xlsx": "SD promoted ASIN relations + ad-group facts",
    "展示型推广_匹配的目标_报告.xlsx": "SD matched target facts",
    "展示型推广_已购买商品_报告.xlsx": "SD purchased ASIN relations",
    "展示型推广_总流量和无效流量_报告.xlsx": "SD invalid traffic",
    "展示型推广_定价透明度_报告.xlsx": "SD pricing transparency (header only)",
    "Sponsored_TV_定价透明度_报告.xlsx": "Sponsored TV (out of scope, header only)",
}


# --------------------------------------------------------------------- helpers

def sid(prefix: str, *parts) -> str:
    h = hashlib.sha1("\x1f".join("" if p is None else str(p)
                                 for p in parts).encode("utf-8"))
    return "%s_%s" % (prefix, h.hexdigest()[:16])


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_div(a, b):
    try:
        if a is None or b in (None, 0):
            return None
        return a / b
    except ZeroDivisionError:
        return None


def norm_type(value: str) -> str:
    v = (value or "").strip()
    if "品牌" in v or v.upper() == "SB":
        return "SB"
    if "展示" in v or v.upper() == "SD":
        return "SD"
    return "SP"


class Build:
    def __init__(self) -> None:
        os.makedirs(OUT_DIR, exist_ok=True)
        if os.path.exists(OUT_DB):
            os.remove(OUT_DB)
        self.db = sqlite3.connect(OUT_DB)
        self.db.executescript(SCHEMA)
        self.files: dict[str, str] = {}      # filename -> source_file_id
        self.campaigns: dict[tuple, str] = {}   # (ad_type, name) -> campaign_id
        self.objects: dict[tuple, str] = {}     # object key -> ad_object_id
        self.v010_ids: dict[tuple, str] = {}
        self.lineage: list[tuple] = []
        self.notes: list[str] = []

    # -------------------------------------------------------- v0.1.0 carry-over
    def carry_over(self) -> dict:
        """Copy the product scope, page-2 decision chain and the 59-row page1
        regression baseline out of v0.1.0, DDL and all."""
        if not os.path.exists(V010):
            self.notes.append("v0.1.0 not found -- carry-over skipped")
            return {}
        old = sqlite3.connect("file:%s?mode=ro" % V010, uri=True)
        ddl = {name: sql for name, sql in old.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='table'")}
        counts = {}
        for table in CARRY_TABLES:
            if table not in ddl or not ddl[table]:
                self.notes.append("carry table absent in v0.1.0: %s" % table)
                continue
            self.db.executescript(ddl[table])
            cols = [r[1] for r in old.execute("PRAGMA table_info(%s)" % table)]
            rows = list(old.execute("SELECT %s FROM %s" %
                                    (",".join('"%s"' % c for c in cols), table)))
            self.db.executemany(
                "INSERT OR REPLACE INTO %s VALUES (%s)"
                % (table, ",".join("?" * len(cols))), rows)
            counts[table] = len(rows)
        old.close()
        self.db.commit()
        return counts

    # ------------------------------------------------------------- acceptance
    def quality_report(self) -> dict:
        q = self.db.execute
        checks = []

        def add(cid, ok, evidence):
            checks.append({"check_id": cid,
                           "status": "PASS" if ok else "FAIL",
                           "evidence": evidence})

        n_files = q("SELECT COUNT(*) FROM source_file").fetchone()[0]
        add("Q-ALL-SOURCES", n_files == len(REPORTS),
            {"registered": n_files, "expected": len(REPORTS)})

        fk = list(q("PRAGMA foreign_key_check"))
        add("Q-FK", not fk, {"violations": len(fk)})

        levels = dict(q("SELECT object_level, COUNT(*) FROM dim_ad_object"
                        " GROUP BY object_level").fetchall())
        add("Q-OBJECT-LEVELS", set(levels) == {"CAMPAIGN", "AD_GROUP", "TARGET"},
            levels)

        carried = q("SELECT COUNT(*) FROM dim_ad_object WHERE carried_from_v010=1"
                    ).fetchone()[0]
        add("Q-V010-ID-REUSE", carried >= 700,
            {"carried_ids": carried, "v010_total": len(self.v010_ids)})

        # the page-2 chain must still resolve against the new object table
        orphan = q(
            "SELECT COUNT(*) FROM fact_ad_recommendation r"
            " WHERE r.ad_object_id IS NOT NULL AND r.ad_object_id NOT IN"
            " (SELECT ad_object_id FROM dim_ad_object)").fetchone()[0]
        add("Q-PAGE2-CHAIN-INTACT", orphan == 0, {"orphan_recommendations": orphan})

        bases = dict(q("SELECT metric_basis, COUNT(*) FROM fact_ad_performance"
                       " GROUP BY metric_basis").fetchall())
        add("Q-MONTH-BASIS-SINGLE", set(bases) == {"report_month_total"}, bases)

        dbases = dict(q("SELECT metric_basis, COUNT(*) FROM fact_ad_daily"
                        " GROUP BY metric_basis").fetchall())
        add("Q-DAILY-TWO-BASES",
            set(dbases) == {"search_term_exact_day_sum", "daily_scaled_to_month"},
            dbases)

        # scaled daily must sum back to the authoritative month total
        bad = list(q("""
            SELECT d.ad_object_id, ROUND(SUM(d.spend),2), ROUND(p.spend,2)
            FROM fact_ad_daily d
            JOIN fact_ad_performance p
              ON p.ad_object_id = d.ad_object_id
             AND p.metric_basis = 'report_month_total'
            WHERE d.metric_basis = 'daily_scaled_to_month' AND d.spend IS NOT NULL
            GROUP BY d.ad_object_id
            HAVING ABS(SUM(d.spend) - p.spend) > 0.05
        """))
        add("Q-DAILY-SCALE-CLOSES", not bad,
            {"objects_off_by_more_than_0.05": len(bad),
             "sample": bad[:3]})

        roles = dict(q("SELECT relation_role, COUNT(*) FROM"
                       " bridge_ad_object_product GROUP BY relation_role"
                       ).fetchall())
        add("Q-FIVE-ROLES", len(roles) == 5, roles)

        ltypes = dict(q("SELECT label_type, COUNT(*) FROM fact_ad_label_version"
                        " GROUP BY label_type").fetchall())
        add("Q-LABEL-FIVE-TYPES", len(ltypes) == 5, ltypes)

        unconfirmed = q("SELECT COUNT(*) FROM fact_ad_label_version"
                        " WHERE label_source IN ('auto_mapping','ai_suggested')"
                        " AND confirmation_status='confirmed'").fetchone()[0]
        add("Q-INFERRED-NOT-CONFIRMED", unconfirmed == 0,
            {"inferred_but_marked_confirmed": unconfirmed})

        rclasses = dict(q("SELECT rule_class, COUNT(*) FROM dim_anomaly_rule"
                          " GROUP BY rule_class").fetchall())
        add("Q-RULE-FOUR-CLASSES", len(rclasses) == 4, rclasses)

        confirmed_rules = q("SELECT COUNT(*) FROM dim_anomaly_rule"
                            " WHERE rule_status!='pending_customer_confirmation'"
                            ).fetchone()[0]
        add("Q-RULES-PENDING", confirmed_rules == 0,
            {"rules_claiming_confirmed": confirmed_rules})

        overall = "PASS" if all(c["status"] == "PASS" for c in checks) else "FAIL"
        return {"overall_status": overall, "checks": checks,
                "notes": self.notes}

    def write_manifest(self, table_counts: dict) -> None:
        import datetime as _d
        self.db.execute(
            "INSERT OR REPLACE INTO dataset_manifest VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (DATASET_VERSION, "release_candidate",
             _d.datetime.now().replace(microsecond=0).isoformat(),
             WINDOW[0], WINDOW[1], json.dumps(ATTRIB),
             "source-local", "USD", SEED, len(self.files),
             "all 31 ad reports ingested; month authoritative and daily "
             "comparable kept as separate metric_basis and never summed"))
        self.db.commit()
        with open(os.path.join(OUT_DIR, "table_counts.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(table_counts, fh, ensure_ascii=False, indent=2)

    # ------------------------------------------------------------ id helpers
    @staticmethod
    def sid(prefix: str, *parts) -> str:
        return sid(prefix, *parts)

    def sid_placement(self, ad_type: str, campaign: str, placement: str) -> str:
        return sid("plc", ad_type, campaign, placement)

    # ------------------------------------------------------------ source files
    def register_files(self) -> None:
        for name, used_for in sorted(REPORTS.items()):
            path = adsrc.ad_file(name)
            if not os.path.exists(path):
                self.notes.append("missing source file: %s" % name)
                continue
            enc = "xlsx"
            rows = 0
            if name.lower().endswith(".csv"):
                enc = adsrc.csv_encoding(path)
                rows = sum(1 for _ in adsrc.csv_rows(path))
            else:
                rows = sum(1 for _ in adsrc.xlsx_dicts(path))
            fid = sid("src", name)
            self.files[name] = fid
            system = "AMAZON"
            self.db.execute(
                "INSERT INTO source_file VALUES (?,?,?,?,?,?,?)",
                (fid, "数据源/AI广告对接数据-总20260803/13.广告/" + name,
                 sha256_file(path), system, enc, rows, used_for))
        self.db.commit()

    def lin(self, table, rec, field, ttype, status, filename, selector, rule):
        self.lineage.append((
            sid("lin", table, rec, field), table, rec, field, ttype, status,
            self.files.get(filename or "", None), selector, rule,
            DATASET_VERSION))

    def flush_lineage(self) -> None:
        self.db.executemany(
            "INSERT OR REPLACE INTO source_lineage VALUES (?,?,?,?,?,?,?,?,?,?)",
            self.lineage)
        self.lineage.clear()
        self.db.commit()

    # ---------------------------------------------------------- v0.1.0 id reuse
    def load_v010_ids(self) -> None:
        if not os.path.exists(V010):
            self.notes.append("v0.1.0 db not found -- no id reuse")
            return
        old = sqlite3.connect("file:%s?mode=ro" % V010, uri=True)
        for row in old.execute(
                "SELECT ad_object_id, object_level, ad_type, campaign_name,"
                " ad_group_name, target_text, match_type FROM dim_ad_object"):
            oid, level, atype, camp, grp, tgt, mt = row
            key = (level, atype, camp or "", grp or "", tgt or "", mt or "")
            self.v010_ids[key] = oid
        old.close()

    def object_id(self, level, atype, camp, grp=None, tgt=None, mt=None):
        key = (level, atype, camp or "", grp or "", tgt or "", mt or "")
        if key in self.v010_ids:
            return self.v010_ids[key], 1
        prefix = {"CAMPAIGN": "camp", "AD_GROUP": "grp", "TARGET": "tgt"}[level]
        return sid(prefix, *key), 0

    # -------------------------------------------------------------- dimensions
    def build_campaigns(self) -> None:
        rows: dict[tuple, dict] = {}

        def take(filename, ad_type_hint, name_key="广告活动名称"):
            path = adsrc.ad_file(filename)
            if not os.path.exists(path):
                return
            it = (adsrc.csv_rows(path) if filename.endswith(".csv")
                  else adsrc.xlsx_dicts(path))
            for r in it:
                name = (str(r.get(name_key) or "")).strip()
                if not name:
                    continue
                atype = norm_type(r.get("广告活动类型") or ad_type_hint)
                key = (atype, name)
                cur = rows.setdefault(key, {"src": filename})
                for col, fld, conv in (
                        ("广告组合名称", "portfolio_name", str),
                        ("状态", "state", str),
                        ("预算", "budget", adsrc.parse_money),
                        ("建议预算", "recommended_budget", adsrc.parse_money),
                        ("预算范围内的平均时间", "time_in_budget", adsrc.parse_pct),
                        ("定位类型", "targeting_type", str),
                        ("竞价策略", "bid_strategy", str)):
                    v = r.get(col)
                    if v is None or (isinstance(v, str) and not v.strip()):
                        continue
                    val = conv(v) if conv is not str else str(v).strip()
                    if val is not None and cur.get(fld) in (None, ""):
                        cur[fld] = val

        take("商品推广_广告活动_报告.csv", "SP")
        take("商品推广_预算_报告.csv", "SP")
        take("品牌推广_广告活动_报告.xlsx", "SB")
        take("展示型推广_广告活动_报告.xlsx", "SD")

        for (atype, name), cur in sorted(rows.items()):
            info = adsrc.parse_campaign_name(name)
            dims = info["dims"]
            cid = sid("camp", atype, name)
            self.campaigns[(atype, name)] = cid
            self.db.execute(
                "INSERT INTO dim_campaign VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (cid, atype, name, cur.get("portfolio_name"), cur.get("state"),
                 cur.get("budget"), cur.get("recommended_budget"),
                 cur.get("time_in_budget"), cur.get("targeting_type"),
                 cur.get("bid_strategy"), info["line"],
                 (dims.get("owner") or [None])[0],
                 (dims.get("lifecycle") or [None])[0],
                 json.dumps(dims, ensure_ascii=False),
                 json.dumps(info["unknown_tokens"], ensure_ascii=False),
                 0, "direct", cur["src"]))
            self.lin("dim_campaign", cid, "campaign_name", "direct_copy",
                     "direct", cur["src"], "广告活动名称=%s" % name, "as reported")
            self.lin("dim_campaign", cid, "name_dims", "rule_decode", "derived",
                     cur["src"], "广告活动名称=%s" % name,
                     "adsrc.parse_campaign_name (operator naming convention)")
            # the campaign is also an addressable ad object
            oid, carried = self.object_id("CAMPAIGN", atype, name)
            self.objects[("CAMPAIGN", atype, name, "", "", "")] = oid
            self.db.execute(
                "INSERT OR IGNORE INTO dim_ad_object VALUES"
                " (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (oid, "CAMPAIGN", atype, cid, name, None, None, None, None,
                 "source_name_key", 0, "direct_campaign_report", "direct",
                 cur["src"], carried))
        self.db.commit()

    def ensure_object(self, level, atype, camp, grp=None, tgt=None, mt=None,
                      src="", mapping="derived_from_report"):
        key = (level, atype, camp or "", grp or "", tgt or "", mt or "")
        if key in self.objects:
            return self.objects[key]
        oid, carried = self.object_id(level, atype, camp, grp, tgt, mt)
        cid = self.campaigns.get((atype, camp))
        parent = None
        if level == "TARGET":
            parent = self.objects.get(
                ("AD_GROUP", atype, camp or "", grp or "", "", ""))
        elif level == "AD_GROUP":
            parent = self.objects.get(("CAMPAIGN", atype, camp or "", "", "", ""))
        is_sys = 1 if (grp or "").startswith("广告组 - ") else 0
        self.db.execute(
            "INSERT OR IGNORE INTO dim_ad_object VALUES"
            " (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (oid, level, atype, cid, camp, grp, tgt, mt, parent,
             "source_name_key", is_sys, mapping, "direct", src, carried))
        self.objects[key] = oid
        return oid


def main() -> int:
    import build_facts as bf
    import build_sides as bs

    b = Build()
    print("[1/9] registering source files ...")
    b.register_files()
    b.load_v010_ids()
    print("      files=%d   v0.1.0 ids for reuse=%d"
          % (len(b.files), len(b.v010_ids)))

    print("[2/9] carrying product scope + page-2 chain from v0.1.0 ...")
    carried = b.carry_over()
    print("      %s" % carried)

    print("[3/9] campaign dimension ...")
    b.build_campaigns()
    byt = dict(b.db.execute("SELECT ad_type, COUNT(*) FROM dim_campaign"
                            " GROUP BY ad_type").fetchall())
    print("      campaigns=%d %s"
          % (sum(byt.values()), byt))

    print("[4/9] ad group / target objects, placements, audiences ...")
    obj_stats = bf.build_objects(b)
    npl = bf.build_placements(b)
    nau = bf.build_audiences(b)
    levels = dict(b.db.execute("SELECT object_level, COUNT(*) FROM dim_ad_object"
                               " GROUP BY object_level").fetchall())
    print("      objects=%s  (rows scanned %s)" % (levels, obj_stats))
    print("      placement facts=%d  audience facts=%d" % (npl, nau))

    print("[5/9] month authoritative facts ...")
    mstats = bf.build_month_facts(b)
    ncamp = bf.build_campaign_rollup(b)
    # A campaign exists in the account but may have had no July delivery at all;
    # page 1 has to be able to say which ones those are.
    b.db.execute("""
        UPDATE dim_campaign SET has_july_delivery = (
            SELECT CASE WHEN EXISTS (
                SELECT 1 FROM dim_ad_object o
                JOIN fact_ad_performance f ON f.ad_object_id = o.ad_object_id
                WHERE o.campaign_id = dim_campaign.campaign_id
                  AND o.object_level IN ('AD_GROUP','TARGET')
                  AND f.metric_basis = 'report_month_total'
                  AND COALESCE(f.impressions,0) + COALESCE(f.spend,0) > 0
            ) THEN 1 ELSE 0 END)
    """)
    b.db.commit()
    live = dict(b.db.execute("SELECT has_july_delivery, COUNT(*) FROM dim_campaign"
                             " GROUP BY has_july_delivery").fetchall())
    print("      by level=%s  campaign rows=%d" % (mstats, ncamp))
    print("      campaigns with July delivery=%s" % live)

    print("[6/9] daily comparable + scaled series ...")
    dstats = bf.build_daily_facts(b)
    print("      %s" % dstats)

    print("[7/9] side facts (yoy / budget / invalid / benchmark / share / creative) ...")
    side = {
        "yoy": bs.build_yoy(b),
        "budget": bs.build_budget(b),
        "invalid_traffic": bs.build_invalid_traffic(b),
        "category_benchmark": bs.build_benchmark(b),
        "search_term_share": bs.build_search_term_share(b),
        "creative": bs.build_creatives(b),
    }
    print("      %s" % side)

    print("[8/9] attribution bridges + label taxonomy + anomaly rules ...")
    br = bs.build_bridges(b)
    lb = bs.build_labels(b)
    nr = bs.build_rules(b)
    print("      bridges=%s" % br)
    print("      labels=%s" % lb)
    print("      rules=%d" % nr)

    print("[9/9] lineage, manifest, quality report ...")
    b.flush_lineage()
    b.write_manifest({})
    counts = {}
    for (name,) in b.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        counts[name] = b.db.execute("SELECT COUNT(*) FROM %s" % name).fetchone()[0]
    with open(os.path.join(OUT_DIR, "table_counts.json"), "w",
              encoding="utf-8") as fh:
        json.dump(counts, fh, ensure_ascii=False, indent=2)
    report = b.quality_report()
    with open(os.path.join(OUT_DIR, "quality_report.json"), "w",
              encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)

    b.db.execute("PRAGMA optimize")
    b.db.commit()
    b.db.close()

    print()
    print("=== table counts ===")
    for k, v in counts.items():
        print("  %-32s %8d" % (k, v))
    print()
    print("=== quality: %s ===" % report["overall_status"])
    for c in report["checks"]:
        print("  %-26s %s  %s" % (c["check_id"], c["status"],
                                  json.dumps(c["evidence"], ensure_ascii=False)[:150]))
    if report["notes"]:
        print("  notes: %s" % report["notes"])
    print()
    print("db: %s" % OUT_DB)
    return 0 if report["overall_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
