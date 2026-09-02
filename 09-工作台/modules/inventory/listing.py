"""全量评估、筛选、范围汇总。

这三个函数原来在 18810 版的 server.py 里 —— 那个文件按迁移指导不带过来，
但函数本身是 `/api/inventory/children` 的全部逻辑，所以搬到这里。
**函数体逐字未改**，只把 `rules_mod` 换成 `rules`（模块内已无同名冲突）。
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import asdict
from functools import lru_cache
from typing import Any

from . import compute, data, rules


@lru_cache(maxsize=8)
def _assess_all(fingerprint: str, payload: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Assess all 342 children for one rule set. Cached by rule fingerprint."""
    rs = rules.RuleSet(**json.loads(payload))
    summaries = []
    for asin in data.all_children():
        assessment = compute.assess(asin, rs)
        if assessment:
            summaries.append(compute.summarize(assessment))

    risk_children: dict[str, set] = defaultdict(set)
    risk_qty: dict[str, int] = defaultdict(int)
    severity = Counter()
    for row in summaries:
        for risk_type in row["risk_types"]:
            risk_children[risk_type].add(row["child_asin"])
        if row["primary_severity"]:
            severity[row["primary_severity"]] += 1
    for row in summaries:
        for risk_type, qty in row.get("risk_qty", {}).items():
            risk_qty[risk_type] += qty

    overview = {
        "child_count": len(summaries),
        "risk_child_count": sum(1 for r in summaries if r["risk_count"]),
        "risk_record_count": sum(r["risk_count"] for r in summaries),
        "by_risk_type": {
            key: {
                "label": compute.RISK_LABELS[key],
                "child_count": len(risk_children.get(key, ())),
                "affected_qty": risk_qty.get(key, 0),
            }
            for key in compute.RISK_LABELS
        },
        "severity": dict(severity),
        "multi_risk_children": sum(1 for r in summaries if r["risk_count"] >= 2),
        "no_risk_children": sum(1 for r in summaries if r["risk_count"] == 0),
        "capacity": dict(Counter(r["capacity_level"] for r in summaries)),
        "confidence": dict(Counter(r["confidence"] for r in summaries)),
    }
    return summaries, overview


def assess_all(rs: rules.RuleSet):
    return _assess_all(rs.fingerprint(), json.dumps(asdict(rs), sort_keys=True))


def apply_filters(rowset: list[dict[str, Any]], query: dict[str, list[str]]) -> list[dict[str, Any]]:
    out = rowset
    for key in [
        "parent_asin",
        "style_no",
        "combination",
        "size",
        "operator",
        "goods_status",
        "product_lifecycle",
        "store",
    ]:
        if key in query and query[key][0]:
            wanted = set(query[key])
            out = [r for r in out if r.get(key) in wanted]
    if query.get("risk_type", [""])[0]:
        wanted = query["risk_type"][0]
        out = [r for r in out if wanted in r["risk_types"]]
    if query.get("severity", [""])[0]:
        out = [r for r in out if r["primary_severity"] == query["severity"][0]]
    search = query.get("q", [""])[0].strip().upper()
    if search:
        out = [
            r
            for r in out
            if search in r["child_asin"].upper()
            or search in (r["style_no"] or "").upper()
            or search in (r["parent_asin"] or "").upper()
        ]
    sort = query.get("sort", ["risk"])[0]
    keyfn = {
        "risk": lambda r: (-r["risk_score"], r["child_asin"]),
        "cover": lambda r: (r["cover_days"] if r["cover_days"] is not None else 10**9, r["child_asin"]),
        "sales": lambda r: (-(r["units_30d"] or 0), r["child_asin"]),
        "aged": lambda r: (-(r["aged_181_qty"] or 0), r["child_asin"]),
        "fee": lambda r: (-(r["fee_total"] or 0), r["child_asin"]),
        "excess": lambda r: (-(r["excess_qty"] or 0), r["child_asin"]),
        "asin": lambda r: r["child_asin"],
    }.get(sort, lambda r: (-r["risk_score"], r["child_asin"]))
    return sorted(out, key=keyfn)


def scope_aggregate(rowset: list[dict[str, Any]]) -> dict[str, Any]:
    """Range roll-up. Additive measures sum; ratios recompute from totals."""
    sellable = sum(r["sellable_qty"] or 0 for r in rowset)
    fba_total = sum(r["fba_total_qty"] or 0 for r in rowset)
    total_known = sum(r["total_known_qty"] or 0 for r in rowset)
    units_30d = sum(r["units_30d"] or 0 for r in rowset)
    aged = sum(r["aged_181_qty"] or 0 for r in rowset)
    fee = sum(r["fee_total"] or 0 for r in rowset)
    covers = sorted(r["cover_days"] for r in rowset if r["cover_days"] is not None)
    return {
        "child_count": len(rowset),
        "parent_count": len({r["parent_asin"] for r in rowset}),
        "style_count": len({r["style_no"] for r in rowset if r["style_no"]}),
        "sellable_qty": sellable,
        "fba_total_qty": fba_total,
        "total_known_qty": total_known,
        "units_30d": units_30d,
        "aged_181_qty": aged,
        "aged_181_share": round(aged / fba_total, 4) if fba_total else None,
        "availability_rate": round(sellable / fba_total, 4) if fba_total else None,
        "fee_total": round(fee, 2),
        "cover_days_median": covers[len(covers) // 2] if covers else None,
        "cover_days_note": "覆盖天数为中位数，不是平均值；可用率与库龄占比由范围内总量重算",
        "risk_child_count": sum(1 for r in rowset if r["risk_count"]),
        "risk_record_count": sum(r["risk_count"] for r in rowset),
        "by_risk_type": {
            key: sum(1 for r in rowset if key in r["risk_types"]) for key in compute.RISK_LABELS
        },
        "severity": dict(Counter(r["primary_severity"] for r in rowset if r["primary_severity"])),
    }


def clear_caches() -> None:
    """热重载钩子。全量评估缓存必须一起清，否则改了判断链看到的还是旧结果。"""
    _assess_all.cache_clear()
    data.clear_caches()
