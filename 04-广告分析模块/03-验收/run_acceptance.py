#!/usr/bin/env python3
"""Independent acceptance runner for the Bamboocool advertising Demo.

The runner consumes logical tables from one of three delivery shapes:

1. ``acceptance_export.json`` containing ``{"tables": {name: records}}``;
2. individual ``<logical_artifact>.json`` files;
3. a SQLite file containing tables named after the logical artifacts.

Exit codes: 0=PASS, 1=FAIL, 2=BLOCKED.
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Iterable


HERE = Path(__file__).resolve().parent
DEFAULT_CONTRACT = HERE / "acceptance_contract.json"
PROVENANCE = {"direct", "derived", "supplemented", "scenario_added", "blocked"}
ROLE_VALUES = {
    "promoted_asin",
    "positive_spend_asin",
    "purchased_asin",
    "target_asin",
    "matched_asin",
}


@dataclass
class Check:
    check_id: str
    capability_id: str
    status: str
    message: str
    evidence: dict[str, Any]


def iso_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    text = str(value).strip()[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def num(value: Any) -> float | None:
    if value in (None, "", "null"):
        return None
    try:
        return float(str(value).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return None


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                parsed = json.loads(text)
                return parsed if isinstance(parsed, list) else [parsed]
            except json.JSONDecodeError:
                pass
        return [part.strip() for part in text.split(",") if part.strip()]
    return [value]


def truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def nonempty(record: dict[str, Any], fields: Iterable[str]) -> bool:
    return all(record.get(field) not in (None, "", [], {}) for field in fields)


def unique(records: list[dict[str, Any]], fields: list[str]) -> tuple[bool, list[tuple[Any, ...]]]:
    keys = [tuple(row.get(field) for field in fields) for row in records]
    duplicates = [key for key, count in Counter(keys).items() if count > 1]
    return not duplicates, duplicates[:10]


class Store:
    def __init__(self, root: Path, contract: dict[str, Any]):
        self.root = root
        self.contract = contract
        self._tables: dict[str, Any] = {}
        self._load()

    def _load_json_file(self, path: Path) -> Any:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if isinstance(payload, dict):
            for key in ("records", "data", "rows"):
                if isinstance(payload.get(key), list):
                    return payload[key]
        return payload

    def _load(self) -> None:
        if not self.root.exists():
            return
        if self.root.is_file() and self.root.suffix.lower() in {".sqlite", ".db"}:
            self._load_sqlite(self.root)
            return
        bundle = self.root if self.root.is_file() and self.root.suffix == ".json" else self.root / "acceptance_export.json"
        if bundle.exists():
            payload = self._load_json_file(bundle)
            if isinstance(payload, dict) and isinstance(payload.get("tables"), dict):
                self._tables.update(payload["tables"])
            elif isinstance(payload, dict):
                self._tables.update(payload)

        if self.root.is_dir():
            for name in self.contract["logical_artifacts"]:
                if name in self._tables:
                    continue
                candidates = [self.root / f"{name}.json"]
                if name == "dataset_manifest":
                    candidates += [self.root / "dataset-manifest.json", self.root / "manifest.json"]
                for candidate in candidates:
                    if candidate.exists():
                        self._tables[name] = self._load_json_file(candidate)
                        break

            sqlite_files = sorted(self.root.glob("*.sqlite")) + sorted(self.root.glob("*.db"))
            if sqlite_files:
                self._load_sqlite(sqlite_files[0])

    def _load_sqlite(self, path: Path) -> None:
        with sqlite3.connect(path) as connection:
            names = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")
            }
            for name in self.contract["logical_artifacts"]:
                if name in self._tables or name not in names:
                    continue
                cursor = connection.execute(f'SELECT * FROM "{name}"')
                columns = [column[0] for column in cursor.description]
                records = [dict(zip(columns, row)) for row in cursor.fetchall()]
                if name == "dataset_manifest" and len(records) == 1:
                    self._tables[name] = records[0]
                else:
                    self._tables[name] = records

    def has(self, name: str) -> bool:
        return name in self._tables

    def rows(self, name: str) -> list[dict[str, Any]]:
        value = self._tables.get(name, [])
        if isinstance(value, dict):
            for key in ("records", "rows", "data"):
                if isinstance(value.get(key), list):
                    return value[key]
            return [value]
        return value if isinstance(value, list) else []

    def obj(self, name: str) -> dict[str, Any]:
        value = self._tables.get(name, {})
        if isinstance(value, list) and len(value) == 1 and isinstance(value[0], dict):
            return value[0]
        return value if isinstance(value, dict) else {}


class Validator:
    def __init__(self, store: Store, contract: dict[str, Any], mode: str):
        self.store = store
        self.contract = contract
        self.scope = contract["scope"]
        manifest = store.obj("dataset_manifest")
        inferred = str(manifest.get("dataset_stage", "vertical_slice")).lower()
        self.mode = inferred if mode == "auto" else mode
        if self.mode not in {"vertical_slice", "release"}:
            self.mode = "vertical_slice"
        self.checks: list[Check] = []

    def add(self, check_id: str, capability: str, passed: bool, message: str, **evidence: Any) -> None:
        self.checks.append(Check(check_id, capability, "PASS" if passed else "FAIL", message, evidence))

    def block(self, check_id: str, capability: str, message: str, **evidence: Any) -> None:
        self.checks.append(Check(check_id, capability, "BLOCKED", message, evidence))

    def require(self, capability: str) -> bool:
        spec = next(item for item in self.contract["capabilities"] if item["capability_id"] == capability)
        missing = [name for name in spec["required_artifacts"] if not self.store.has(name)]
        if missing:
            self.block(f"{capability}-INPUT", capability, "缺少必需逻辑产物，无法验收该能力。", missing_artifacts=missing)
            return False
        return True

    def run(self) -> list[Check]:
        for capability in [f"AD-{index:02d}" for index in range(1, 12)]:
            method: Callable[[], None] = getattr(self, f"check_{capability.replace('-', '_').lower()}")
            if self.require(capability):
                method()
        self.check_vertical_gates()
        return self.checks

    def check_ad_01(self) -> None:
        cap = "AD-01"
        manifest = self.store.obj("dataset_manifest")
        objects = self.store.rows("dim_ad_object")
        facts = self.store.rows("fact_ad_performance")
        groups = [row for row in objects if row.get("object_level") == "AD_GROUP"]
        types = {row.get("ad_type") for row in objects}
        self.add("AD-01-A1", cap, {"SP", "SB", "SD"}.issubset(types), "SP、SB、SD 对象覆盖。", observed_types=sorted(x for x in types if x))
        invalid_keys = [row.get("ad_object_id") for row in groups if row.get("key_kind") != "source_name_key"]
        self.add("AD-01-A2", cap, not invalid_keys, "广告组必须声明为名称键，不得冒充平台稳定 ID。", invalid_ids=invalid_keys[:10])

        planned = manifest.get("expected_ad_group_name_key_count")
        self.add("AD-01-B0", cap, int(planned or -1) == 54, "manifest 冻结完整 54 个广告组名称键。", observed=planned)
        if self.mode == "release":
            counts = Counter(row.get("ad_type") for row in groups)
            self.add("AD-01-B1", cap, len(groups) == 54, "release 广告组名称键数量必须为 54。", observed=len(groups))
            self.add("AD-01-B2", cap, counts == Counter(self.scope["ad_group_counts_by_type"]), "release 广告组类型分布必须为 SP40/SB5/SD9。", observed=dict(counts))
        else:
            self.add("AD-01-B1", cap, len(groups) >= 3, "纵向切片至少提供 3 个广告组用于比较。", observed=len(groups))

        start = date.fromisoformat(self.scope["amazon_fact_window"]["start"])
        end = date.fromisoformat(self.scope["amazon_fact_window"]["end"])
        bad_window = []
        bad_attr = []
        bad_fact_fields = []
        for row in facts:
            if not nonempty(row, ["fact_id", "ad_object_id", "object_level", "window_start", "window_end", "ad_type", "attribution_days", "source_status", "source_ref"]):
                bad_fact_fields.append(row.get("fact_id"))
            if row.get("source_system") == "AMAZON" and row.get("source_status") == "direct":
                left, right = iso_date(row.get("window_start")), iso_date(row.get("window_end"))
                if left is None or right is None or left < start or right > end or left > right:
                    bad_window.append(row.get("fact_id"))
            expected = self.scope["attribution_days"].get(row.get("ad_type"))
            try:
                actual = int(row.get("attribution_days"))
            except (TypeError, ValueError):
                actual = -1
            if expected is not None and actual != expected:
                bad_attr.append(row.get("fact_id"))
        self.add("AD-01-C", cap, not bad_window, "Amazon direct 事实必须落在冻结的 2026-07 窗口。", invalid_fact_ids=bad_window[:10])
        self.add("AD-01-D", cap, not bad_attr, "广告归因天数必须为 SP=7、SB/SD=14。", invalid_fact_ids=bad_attr[:10])
        ok, duplicates = unique(facts, ["fact_id"])
        self.add("AD-01-E1", cap, ok and not bad_fact_fields, "广告事实主键唯一且来源/粒度/时间字段齐全。", duplicates=duplicates, incomplete=bad_fact_fields[:10])
        bad_prov = [row.get("fact_id") for row in facts if row.get("source_status") not in PROVENANCE]
        self.add("AD-01-E2", cap, not bad_prov, "广告事实来源状态使用冻结五分类。", invalid_fact_ids=bad_prov[:10])

    def check_ad_02(self) -> None:
        cap = "AD-02"
        manifest = self.store.obj("dataset_manifest")
        parents = self.store.rows("dim_product_parent")
        children = self.store.rows("dim_product_child")
        relations = self.store.rows("bridge_ad_object_product")
        expected_parents = set(self.scope["parent_asins"])
        planned_parents = set(as_list(manifest.get("selected_parent_asins")))
        self.add("AD-02-A0", cap, planned_parents == expected_parents and int(manifest.get("expected_child_count", -1)) == 521, "manifest 冻结 5 父和完整 521 子目标。", observed_parents=sorted(planned_parents), observed_child_target=manifest.get("expected_child_count"))
        if self.mode == "release":
            observed_parents = {row.get("parent_asin") for row in parents}
            self.add("AD-02-A1", cap, observed_parents == expected_parents, "release 父体集合必须与冻结范围完全一致。", observed=sorted(x for x in observed_parents if x))
            self.add("AD-02-A2", cap, len(children) == 521, "release 必须保留完整 521 个子 ASIN。", observed=len(children))
            counts = Counter(row.get("parent_asin") for row in children)
            self.add("AD-02-A3", cap, counts == Counter(self.scope["parent_child_counts"]), "每个父体的完整子体数量必须符合冻结范围。", observed=dict(counts))
        else:
            self.add("AD-02-A1", cap, bool(children), "纵向切片至少包含一个范围内子 ASIN。", observed=len(children))
        ok, duplicate_children = unique(children, ["child_asin"])
        self.add("AD-02-A4", cap, ok and all(row.get("parent_asin") in expected_parents for row in children), "子 ASIN 唯一归属一个冻结父体。", duplicates=duplicate_children)

        bad_roles = [row.get("relation_id") for row in relations if row.get("relation_role") not in ROLE_VALUES]
        self.add("AD-02-B", cap, not bad_roles, "关系角色必须显式区分推广、正花费、购买、目标和匹配。", invalid_relation_ids=bad_roles[:10])
        promoted = [row for row in relations if row.get("relation_role") == "promoted_asin"]
        if self.mode == "release":
            promoted_children = {row.get("child_asin") for row in promoted}
            child_to_parent = {row.get("child_asin"): row.get("parent_asin") for row in children}
            promoted_parents = {child_to_parent.get(child) for child in promoted_children}
            self.add("AD-02-C1", cap, len(promoted_children) == 115, "release 范围内推广 ASIN 必须为 115 个。", observed=len(promoted_children))
            self.add("AD-02-C2", cap, promoted_parents == set(self.scope["promoted_parent_asins"]), "推广 ASIN 只覆盖三个有明确广告关系的父体。", observed=sorted(x for x in promoted_parents if x))
        bad_promoted = [row.get("relation_id") for row in promoted if row.get("source_status") != "direct" or row.get("source_role") != "advertising_asin"]
        self.add("AD-02-C3", cap, not bad_promoted and bool(promoted), "推广关系必须来自直接 advertising_asin 证据。", invalid_relation_ids=bad_promoted[:10], promoted_rows=len(promoted))
        bad_boundaries = [row.get("relation_id") for row in relations if row.get("relation_role") in {"purchased_asin", "target_asin", "matched_asin"} and row.get("source_role") == "advertising_asin"]
        self.add("AD-02-C4", cap, not bad_boundaries, "购买/目标/匹配 ASIN 不得被升级为广告 ASIN。", invalid_relation_ids=bad_boundaries[:10])
        shared_by_object: dict[Any, set[Any]] = defaultdict(set)
        for row in promoted:
            shared_by_object[row.get("ad_object_id")].add(row.get("child_asin"))
        shared_objects = {key for key, values in shared_by_object.items() if len(values) > 1}
        bad_shared = [row.get("relation_id") for row in promoted if row.get("ad_object_id") in shared_objects and row.get("attribution_scope") not in {"shared", "unattributed"}]
        self.add("AD-02-D", cap, bool(shared_objects) and not bad_shared, "共享广告对象保留 shared/unattributed 归因边界。", shared_object_count=len(shared_objects), invalid_relation_ids=bad_shared[:10])
        incomplete = [row.get("relation_id") for row in relations if not nonempty(row, ["relation_id", "ad_object_id", "child_asin", "relation_role", "attribution_scope", "effective_from", "source_status", "source_ref", "source_role"])]
        self.add("AD-02-E", cap, not incomplete, "广告产品关系包含生效时间、来源与归因边界。", incomplete_relation_ids=incomplete[:10])

    def check_ad_03(self) -> None:
        cap = "AD-03"
        labels = self.store.rows("fact_ad_label_version")
        required_types = {"PRODUCT_RELATION", "TARGET_OBJECT", "AD_PURPOSE", "AD_ATTRIBUTE", "OPERATOR_CUSTOM"}
        observed_types = {row.get("label_type") for row in labels}
        self.add("AD-03-A", cap, required_types.issubset(observed_types), "标签切片覆盖五类标签体系。", observed_types=sorted(x for x in observed_types if x))
        sources = {"system_attribute", "auto_mapping", "group_inherited", "ai_suggested", "operator_confirmed"}
        bad_sources = [row.get("label_version_id") for row in labels if row.get("label_source") not in sources]
        self.add("AD-03-B", cap, not bad_sources, "标签来源使用冻结枚举。", invalid_versions=bad_sources[:10])
        required_states = {"confirmed", "pending", "rejected", "unrecognized"}
        observed_states = {row.get("confirmation_status") for row in labels}
        self.add("AD-03-C", cap, required_states.issubset(observed_states), "切片包含确认、待确认、拒绝和无法识别状态。", observed_states=sorted(x for x in observed_states if x))
        bad_dates = []
        intervals: dict[tuple[Any, Any, Any], list[tuple[date, date | None, Any]]] = defaultdict(list)
        for row in labels:
            left, right = iso_date(row.get("effective_from")), iso_date(row.get("effective_to"))
            if left is None or (right is not None and right < left):
                bad_dates.append(row.get("label_version_id"))
                continue
            intervals[(row.get("ad_object_id"), row.get("label_type"), row.get("label_value"))].append((left, right, row.get("label_version_id")))
        overlaps = []
        for key, values in intervals.items():
            values.sort(key=lambda item: item[0])
            for previous, current in zip(values, values[1:]):
                if previous[1] is None or previous[1] >= current[0]:
                    overlaps.append((key, previous[2], current[2]))
        versions_by_object_type: dict[tuple[Any, Any], list[dict[str, Any]]] = defaultdict(list)
        for row in labels:
            versions_by_object_type[(row.get("ad_object_id"), row.get("label_type"))].append(row)
        history = any(
            len(values) > 1
            and len({row.get("label_value") for row in values}) > 1
            and any(row.get("effective_to") not in (None, "") for row in values)
            for values in versions_by_object_type.values()
        )
        self.add("AD-03-D", cap, not bad_dates and not overlaps and history, "标签版本区间有效、不重叠，且切片含历史变化。", invalid_dates=bad_dates[:10], overlaps=overlaps[:5], has_history=history)
        inherited = [row for row in labels if row.get("label_source") == "group_inherited"]
        self.add("AD-03-E", cap, bool(inherited) and all(row.get("inherited_from_object_id") not in (None, "") for row in inherited), "继承标签保留来源广告组。", inherited_count=len(inherited))

    def _metric_checks(self, rows: list[dict[str, Any]], prefix: str, cap: str) -> None:
        negative = []
        mismatch = []
        metrics = ["impressions", "clicks", "spend", "orders", "ad_sales"]
        for row in rows:
            rid = row.get("fact_id") or row.get("result_id")
            values = {field: num(row.get(field)) for field in metrics}
            if any(value is not None and value < 0 for value in values.values()):
                negative.append(rid)
            expectations = {
                "ctr": None if not values["impressions"] else values["clicks"] / values["impressions"],
                "cpc": None if not values["clicks"] else values["spend"] / values["clicks"],
                "cvr": None if not values["clicks"] else values["orders"] / values["clicks"],
                "acos": None if not values["ad_sales"] else values["spend"] / values["ad_sales"],
                "roas": None if not values["spend"] else values["ad_sales"] / values["spend"],
            }
            for field, expected in expectations.items():
                actual = num(row.get(field))
                if expected is None:
                    if actual not in (None, 0.0):
                        mismatch.append((rid, field, actual, None))
                elif actual is None or not math.isclose(actual, expected, rel_tol=1e-4, abs_tol=1e-6):
                    mismatch.append((rid, field, actual, expected))
        self.add(f"{prefix}-A", cap, not negative, "基础经营量不得为负。", invalid_ids=negative[:10])
        self.add(f"{prefix}-B", cap, not mismatch, "CTR/CPC/CVR/ACoS/ROAS 必须可由分子分母复算。", mismatches=mismatch[:10])

    def check_ad_04(self) -> None:
        cap = "AD-04"
        facts = self.store.rows("fact_ad_performance")
        self._metric_checks(facts, "AD-04", cap)
        grain_fields = ["ad_object_id", "object_level", "window_start", "window_end", "attribution_days", "source_ref"]
        ok, duplicates = unique(facts, grain_fields)
        self.add("AD-04-C1", cap, ok, "广告经营事实目标粒度唯一。", duplicate_grains=duplicates)
        incomplete = [row.get("fact_id") for row in facts if not nonempty(row, ["coverage_start", "coverage_end", "attribution_days", "attribution_scope", "comparison_status"])]
        self.add("AD-04-C2", cap, not incomplete, "区间结果保留覆盖、归因、共享和可比状态。", incomplete_fact_ids=incomplete[:10])
        forbidden = {"product_goal_judgement", "strategy_priority", "diagnosis", "recommendation", "recommended_bid", "recommended_budget"}
        polluted = [row.get("fact_id") for row in facts if forbidden.intersection(row.keys())]
        self.add("AD-04-E", cap, not polluted, "经营事实不携带产品诊断或建议字段。", polluted_fact_ids=polluted[:10])

    def check_ad_05(self) -> None:
        cap = "AD-05"
        contexts = self.store.rows("fact_decision_context")
        evidence = self.store.rows("fact_decision_evidence")
        ok, duplicates = unique(contexts, ["child_asin", "product_goal_version", "decision_at"])
        self.add("AD-05-A", cap, bool(contexts) and ok and all(nonempty(row, ["decision_id", "child_asin", "product_goal_version", "decision_at"]) for row in contexts), "决策上下文使用子 ASIN × 目标版本 × 决策时刻唯一粒度。", duplicate_grains=duplicates)
        by_decision: dict[Any, set[Any]] = defaultdict(set)
        for row in evidence:
            by_decision[row.get("decision_id")].add(row.get("evidence_type"))
        required = set(self.contract["page_grains"]["page_2"]["required_evidence_types"])
        complete_decisions = [decision_id for decision_id, types in by_decision.items() if required.issubset(types)]
        self.add("AD-05-B", cap, bool(complete_decisions), "至少一个明星决策包含五类必需证据。", complete_decisions=complete_decisions[:10])
        incomplete = [row.get("evidence_id") for row in evidence if not nonempty(row, ["evidence_id", "decision_id", "evidence_type", "observed_at", "valid_as_of", "source_status", "source_ref", "evidence_nature"])]
        bad_nature = [row.get("evidence_id") for row in evidence if row.get("evidence_nature") not in {"fact", "inference", "operator_confirmed"}]
        self.add("AD-05-C", cap, not incomplete and not bad_nature, "证据保留时间、来源和事实/推导/确认边界。", incomplete=incomplete[:10], invalid_nature=bad_nature[:10])
        decision_time = {row.get("decision_id"): iso_date(row.get("decision_at")) for row in contexts}
        future = []
        for row in evidence:
            cutoff = decision_time.get(row.get("decision_id"))
            observed = iso_date(row.get("observed_at"))
            valid = iso_date(row.get("valid_as_of"))
            if cutoff is None or observed is None or valid is None or observed > cutoff or valid > cutoff:
                future.append(row.get("evidence_id"))
        self.add("AD-05-D", cap, not future and all(row.get("evidence_status") in {"current", "stale", "conflicting", "missing"} for row in evidence), "决策不使用未来证据，证据质量状态显式。", invalid_evidence_ids=future[:10])

    def check_ad_06(self) -> None:
        cap = "AD-06"
        tasks = self.store.rows("fact_required_ad_task")
        evidence_ids = {row.get("evidence_id") for row in self.store.rows("fact_decision_evidence")}
        incomplete = []
        broken_evidence = []
        precision_without_rule = []
        for row in tasks:
            if not nonempty(row, ["task_id", "decision_id", "product_goal_version", "task_type", "priority", "target_scope", "constraints", "evaluation_direction", "stop_condition", "rule_status", "evidence_ids"]):
                incomplete.append(row.get("task_id"))
            if not set(as_list(row.get("evidence_ids"))).issubset(evidence_ids):
                broken_evidence.append(row.get("task_id"))
            if row.get("rule_status") != "confirmed" and any(num(row.get(field)) is not None for field in ["exact_budget", "exact_bid", "exact_placement_adjustment"]):
                precision_without_rule.append(row.get("task_id"))
        self.add("AD-06-A", cap, bool(tasks) and not incomplete and not broken_evidence, "每项任务绑定决策、目标、证据和完整任务边界。", incomplete=incomplete[:10], broken_evidence=broken_evidence[:10])
        self.add("AD-06-C", cap, not precision_without_rule, "规则未确认时不得输出精确预算、竞价或广告位幅度。", invalid_task_ids=precision_without_rule[:10])
        inventory_constrained = [row for row in tasks if truthy(row.get("inventory_constrained"))]
        allowed = {"DEFER", "LIMIT", "PREREQUISITE", "OBSERVE"}
        self.add("AD-06-D", cap, bool(inventory_constrained) and all(row.get("task_direction") in allowed for row in inventory_constrained), "库存不可承接场景生成限制、暂缓或前置任务。", constrained_tasks=len(inventory_constrained))

    def check_ad_07(self) -> None:
        cap = "AD-07"
        tasks = self.store.rows("fact_required_ad_task")
        mappings = self.store.rows("bridge_task_ad_object")
        objects = {row.get("ad_object_id") for row in self.store.rows("dim_ad_object")}
        allowed = {"covered", "missing", "duplicate", "mixed", "object_mismatch", "data_insufficient"}
        bad_status = [row.get("mapping_id") for row in mappings if row.get("coverage_status") not in allowed]
        mapped_tasks = {row.get("task_id") for row in mappings}
        missing_tasks = [row.get("task_id") for row in tasks if row.get("task_id") not in mapped_tasks]
        self.add("AD-07-A", cap, bool(mappings) and not bad_status and not missing_tasks, "每项应有任务都有冻结的结构对照状态。", invalid_status=bad_status[:10], unmapped_tasks=missing_tasks[:10])
        broken = []
        false_missing = []
        for row in mappings:
            status = row.get("coverage_status")
            object_id = row.get("ad_object_id")
            if status in {"covered", "duplicate", "mixed", "object_mismatch"} and object_id not in objects:
                broken.append(row.get("mapping_id"))
            if status == "missing" and object_id not in (None, ""):
                false_missing.append(row.get("mapping_id"))
        self.add("AD-07-B", cap, not broken and not false_missing, "已承接状态连接真实对象；缺失状态不伪造承担者。", broken_links=broken[:10], false_missing=false_missing[:10])
        incomplete = [row.get("mapping_id") for row in mappings if not nonempty(row, ["mapping_id", "task_id", "coverage_status", "attribution_limit", "evidence_ids"])]
        self.add("AD-07-C", cap, not incomplete and any(row.get("attribution_limit") in {"shared", "unattributed"} for row in mappings), "结构对照保留共享、重叠或不可归因限制。", incomplete=incomplete[:10])
        auto_error = [row.get("mapping_id") for row in mappings if row.get("coverage_status") == "mixed" and truthy(row.get("is_automatic_error"))]
        self.add("AD-07-D", cap, not auto_error, "共享或混合结构不会被自动等同为错误。", invalid_mapping_ids=auto_error[:10])

    def check_ad_08(self) -> None:
        cap = "AD-08"
        diagnoses = self.store.rows("fact_ad_diagnosis")
        evidence_ids = {row.get("evidence_id") for row in self.store.rows("fact_decision_evidence")}
        required = ["diagnosis_id", "decision_id", "task_id", "problem_type", "impacted_goal", "priority", "confidence", "evidence_ids", "uncertainty", "missing_input", "check_direction", "basis_type"]
        incomplete = [row.get("diagnosis_id") for row in diagnoses if not nonempty(row, required)]
        broken = [row.get("diagnosis_id") for row in diagnoses if not set(as_list(row.get("evidence_ids"))).issubset(evidence_ids)]
        self.add("AD-08-A", cap, bool(diagnoses) and not incomplete and not broken, "诊断包含目标、优先级、可信度、证据、不确定项和检查方向。", incomplete=incomplete[:10], broken_evidence=broken[:10])
        bad_basis = [row.get("diagnosis_id") for row in diagnoses if row.get("basis_type") not in {"confirmed_threshold", "self_history", "comparable_objects", "conditional", "data_insufficient"}]
        self.add("AD-08-C", cap, not bad_basis, "诊断只使用已确认阈值、自身历史、严格可比对象或条件/不足判断。", invalid_diagnoses=bad_basis[:10])
        causal = [row.get("diagnosis_id") for row in diagnoses if truthy(row.get("causal_claim"))]
        self.add("AD-08-D", cap, not causal, "同期变化不得被声明为确定因果。", causal_diagnoses=causal[:10])

    def check_ad_09(self) -> None:
        cap = "AD-09"
        recommendations = self.store.rows("fact_ad_recommendation")
        diagnoses = {row.get("diagnosis_id") for row in self.store.rows("fact_ad_diagnosis")}
        objects = {row.get("ad_object_id") for row in self.store.rows("dim_ad_object")}
        allowed = {"KEEP", "OBSERVE", "ADJUST", "PAUSE", "RESUME", "SPLIT", "MERGE", "BUILD", "TEST", "DEFER", "REQUEST_INFO"}
        incomplete = []
        broken = []
        bad_direction = []
        bad_precision = []
        for row in recommendations:
            required = ["recommendation_id", "decision_id", "diagnosis_id", "product_goal_version", "ad_purpose", "direction", "rationale", "preconditions", "risks", "uncertainty", "observation_metrics", "review_windows", "rule_status"]
            if not nonempty(row, required):
                incomplete.append(row.get("recommendation_id"))
            if row.get("diagnosis_id") not in diagnoses:
                broken.append(row.get("recommendation_id"))
            if row.get("ad_object_id") not in objects and row.get("structure_gap_id") in (None, ""):
                broken.append(row.get("recommendation_id"))
            if row.get("direction") not in allowed:
                bad_direction.append(row.get("recommendation_id"))
            if row.get("exact_value") not in (None, "") and (row.get("rule_status") != "confirmed" or row.get("rule_id") in (None, "")):
                bad_precision.append(row.get("recommendation_id"))
        self.add("AD-09-A", cap, bool(recommendations) and not incomplete and not broken, "建议绑定决策、目标、诊断和真实对象或明确结构缺口。", incomplete=incomplete[:10], broken_links=broken[:10])
        self.add("AD-09-B", cap, not bad_direction, "建议方向使用冻结动作方向。", invalid_recommendations=bad_direction[:10])
        windows_ok = all("D+3" in as_list(row.get("review_windows")) and ("D+7" in as_list(row.get("review_windows")) or truthy(row.get("d7_not_required"))) for row in recommendations)
        self.add("AD-09-C", cap, windows_ok, "建议包含 D+3 和必要时 D+7 观察要求。")
        self.add("AD-09-D", cap, not bad_precision, "精确建议值只在规则已确认且 rule_id 存在时允许。", invalid_recommendations=bad_precision[:10])

    def check_ad_10(self) -> None:
        cap = "AD-10"
        results = self.store.rows("fact_page1_result")
        anomalies = self.store.rows("fact_page1_anomaly")
        rules = {row.get("rule_id") for row in self.store.rows("dim_anomaly_rule") if truthy(row.get("enabled"))}
        by_query: dict[Any, list[dict[str, Any]]] = defaultdict(list)
        for row in results:
            by_query[row.get("query_id")].append(row)
        mixed = []
        sparse = []
        for query_id, rows in by_query.items():
            if len({row.get("object_level") for row in rows}) != 1:
                mixed.append(query_id)
            if len(rows) < 1 or any(row.get("filter_signature") in (None, "") or row.get("object_count") in (None, "") for row in rows):
                sparse.append(query_id)
        self.add("AD-10-A", cap, bool(by_query) and not mixed and not sparse, "每次第一页查询只含一种对象粒度，并声明范围、筛选签名和对象数。", mixed_queries=mixed[:10], incomplete_queries=sparse[:10])
        bad_compare = []
        for query_id, rows in by_query.items():
            eligible = [row for row in rows if truthy(row.get("comparison_eligible"))]
            keys = {(row.get("object_level"), row.get("window_start"), row.get("window_end"), row.get("attribution_days"), row.get("metric_basis")) for row in eligible}
            if len(keys) > 1:
                bad_compare.append(query_id)
        self.add("AD-10-B", cap, not bad_compare, "可比较对象必须同粒度、同时间、同归因和同指标基础。", invalid_queries=bad_compare[:10])
        bad_anomalies = [row.get("anomaly_id") for row in anomalies if row.get("rule_id") not in rules]
        self.add("AD-10-C", cap, not bad_anomalies, "数值异常必须绑定已启用规则；无规则不标异常。", invalid_anomalies=bad_anomalies[:10])
        forbidden = set(self.contract["page_grains"]["page_1"]["forbidden_outputs"])
        polluted = [row.get("result_id") for row in results if forbidden.intersection(row.keys())]
        self.add("AD-10-D", cap, not polluted, "第一页结果不包含产品策略诊断或动作建议字段。", polluted_results=polluted[:10])
        signatures: dict[Any, set[Any]] = defaultdict(set)
        for query_id, rows in by_query.items():
            if rows:
                signatures[rows[0].get("filter_signature")].add(query_id)
        scenario_ids = {row.get("scenario_type") for row in self.store.rows("scenario_registry")}
        self.add("AD-10-E", cap, "PAGE1_FILTER_COMPARE_ANOMALY" in scenario_ids and "NO_ANOMALY_RULE" in scenario_ids and len(by_query) >= 2, "切片包含范围变化重算和无规则不报异常场景。", query_count=len(by_query), scenarios=sorted(x for x in scenario_ids if x))

    def check_ad_11(self) -> None:
        cap = "AD-11"
        events = self.store.rows("fact_ad_decision_event")
        feedback = self.store.rows("fact_review_feedback")
        recommendations = {row.get("recommendation_id") for row in self.store.rows("fact_ad_recommendation")}
        event_types = {row.get("event_type") for row in events}
        required_types = {"accept", "modify", "reject", "defer"}
        incomplete = [row.get("event_id") for row in events if row.get("recommendation_id") not in recommendations or not nonempty(row, ["event_id", "recommendation_id", "decision_id", "event_type", "occurred_at", "actor", "original_recommendation_snapshot"])]
        self.add("AD-11-A", cap, required_types.issubset(event_types) and not incomplete, "四类运营决定均存在且保存原建议快照。", observed_types=sorted(x for x in event_types if x), incomplete=incomplete[:10])
        invalid_flow = []
        for row in events:
            kind = row.get("event_type")
            if kind == "modify" and row.get("modified_plan") in (None, "", {}):
                invalid_flow.append(row.get("event_id"))
            if kind in {"reject", "defer"} and (row.get("decision_reason") in (None, "") or row.get("handoff_status") in {"handed_off", "executed"}):
                invalid_flow.append(row.get("event_id"))
            if kind in {"accept", "modify"} and row.get("handoff_status") not in {"ready", "handed_off"}:
                invalid_flow.append(row.get("event_id"))
        self.add("AD-11-B", cap, not invalid_flow, "接受/修改才可交接；拒绝/暂缓记录原因且不伪装执行。", invalid_event_ids=invalid_flow[:10])
        handoff_fields = ["handoff_child_asin", "handoff_product_goal", "handoff_diagnosis", "handoff_ad_objects", "handoff_direction", "handoff_observation", "handoff_open_items", "data_version", "rule_version"]
        incomplete_handoff = [row.get("event_id") for row in events if row.get("event_type") in {"accept", "modify"} and not nonempty(row, handoff_fields)]
        self.add("AD-11-C", cap, not incomplete_handoff, "交接包含产品、诊断、对象、方向、观察、未确认项和版本。", incomplete_event_ids=incomplete_handoff[:10])
        feedback_ids = {row.get("feedback_id") for row in feedback}
        feedback_windows = {row.get("review_window") for row in feedback}
        feedback_incomplete = [row.get("feedback_id") for row in feedback if not nonempty(row, ["feedback_id", "decision_id", "recommendation_id", "review_window", "status", "conclusion", "concurrent_variables", "next_question", "source_status", "source_ref"])]
        self.add("AD-11-D", cap, {"D+3", "D+7"}.issubset(feedback_windows) and not feedback_incomplete, "D+3/D+7 反馈通过执行复盘来源回流并保留同期变量。", windows=sorted(x for x in feedback_windows if x), incomplete=feedback_incomplete[:10])
        version_links = [row for row in events if row.get("previous_version_id") not in (None, "")]
        self.add("AD-11-E", cap, bool(version_links) and any(row.get("feedback_id") in feedback_ids for row in events), "新版本引用前序版本和历史反馈，不覆盖旧记录。", linked_versions=len(version_links))

    def check_vertical_gates(self) -> None:
        scenarios = {row.get("scenario_type") for row in self.store.rows("scenario_registry")} if self.store.has("scenario_registry") else set()
        by_cap: dict[str, list[Check]] = defaultdict(list)
        for check in self.checks:
            by_cap[check.capability_id].append(check)
        for gate in self.contract["vertical_slice_gates"]:
            relevant = [check for cap in gate["capability_ids"] for check in by_cap.get(cap, [])]
            missing_scenarios = sorted(set(gate["required_scenarios"]) - scenarios)
            if any(check.status == "FAIL" for check in relevant):
                status = "FAIL"
                message = "门禁包含失败断言。"
            elif any(check.status == "BLOCKED" for check in relevant) or missing_scenarios:
                status = "BLOCKED"
                message = "门禁缺少能力证据或必需场景。"
            else:
                status = "PASS"
                message = "门禁能力断言和场景均通过。"
            self.checks.append(Check(gate["gate_id"], gate["gate_id"], status, message, {"missing_scenarios": missing_scenarios, "capability_ids": gate["capability_ids"]}))


def summarize(checks: list[Check]) -> dict[str, Any]:
    counts = Counter(check.status for check in checks)
    if counts["FAIL"]:
        overall = "FAIL"
    elif counts["BLOCKED"]:
        overall = "BLOCKED"
    else:
        overall = "PASS"
    by_capability: dict[str, str] = {}
    for capability in [f"AD-{index:02d}" for index in range(1, 12)] + [f"VS-{index:02d}" for index in range(4)]:
        statuses = [check.status for check in checks if check.capability_id == capability or check.check_id == capability]
        if "FAIL" in statuses:
            by_capability[capability] = "FAIL"
        elif "BLOCKED" in statuses or not statuses:
            by_capability[capability] = "BLOCKED"
        else:
            by_capability[capability] = "PASS"
    return {"overall_status": overall, "counts": dict(counts), "capability_status": by_capability}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the frozen Bamboocool advertising acceptance contract.")
    parser.add_argument("--dataset", type=Path, required=True, help="Dataset directory, SQLite file, or acceptance_export.json")
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--mode", choices=["auto", "vertical_slice", "release"], default="auto")
    parser.add_argument("--output", type=Path, default=HERE / "latest_result.json")
    args = parser.parse_args()

    with args.contract.open("r", encoding="utf-8") as handle:
        contract = json.load(handle)
    store = Store(args.dataset.resolve(), contract)
    validator = Validator(store, contract, args.mode)
    checks = validator.run()
    summary = summarize(checks)
    payload = {
        "contract_id": contract["contract_id"],
        "contract_version": contract["contract_version"],
        "dataset": str(args.dataset.resolve()),
        "mode": validator.mode,
        "evaluated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        **summary,
        "checks": [asdict(check) for check in checks],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)

    print(f"overall={summary['overall_status']} mode={validator.mode} dataset={args.dataset}")
    for capability, status in summary["capability_status"].items():
        print(f"{capability}: {status}")
    print(f"result={args.output}")
    return 0 if summary["overall_status"] == "PASS" else 1 if summary["overall_status"] == "FAIL" else 2


if __name__ == "__main__":
    sys.exit(main())
