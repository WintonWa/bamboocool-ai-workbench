#!/usr/bin/env python3
"""Emit the inventory facts used by the workbench for one verdict run.

This is deliberately a thin bridge.  It imports the workbench calculation
module, so the Agent and the page never maintain two copies of the inventory
math.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
WORKBENCH = PROJECT.parent / "09-工作台"
sys.path.insert(0, str(WORKBENCH))

from modules.inventory import compute, verdict  # noqa: E402
from modules.inventory.rules import RuleSet  # noqa: E402


def main() -> int:
    asin = (sys.argv[1] if len(sys.argv) > 1 else "B0B3LM36WB").strip().upper()
    rules = RuleSet()
    assessment = compute.assess(asin, rules)
    if assessment is None:
        print(json.dumps({"ok": False, "error": "child_asin_not_found", "child_asin": asin}))
        return 2

    as_of = compute.AS_OF
    canonical = verdict.deterministic(assessment, as_of)
    projection = assessment.get("projection") or {}
    demand = assessment.get("demand") or {}
    inventory = assessment.get("inventory") or {}
    aging = assessment.get("aging") or {}
    fee = assessment.get("fee") or {}

    payload = {
        "ok": True,
        "child_asin": asin,
        "data_as_of": as_of.isoformat(),
        "forecast_run_id": ((demand.get("run") or {}).get("run_id")),
        "decision_context": {
            "forecast_daily": demand.get("forecast_daily"),
            "forecast_90d": demand.get("forecast_90d"),
            "forecast_confidence": demand.get("confidence_label"),
            "forecast_confidence_reason": demand.get("confidence_reason"),
            "sellable_qty": inventory.get("sellable_qty"),
            "safety_days": projection.get("safety_days"),
            "confirmed_arrival_qty": projection.get("confirmed_arrival_qty"),
            "planned_arrival_qty": projection.get("planned_arrival_qty"),
            "arrivals": projection.get("arrivals") or [],
            "aged_181_qty": aging.get("aged_181_qty"),
            "storage_fee": fee.get("total_fee"),
        },
        # These are the page-calculation outputs the contract gate cross-checks.
        # The Agent may improve the wording and prioritisation, but must not
        # silently invent a different number or state.
        "contract_facts": [
            {
                "block": item["block"],
                "expected_state": item["state"],
                "refs": item["refs"],
                "numbers": item["numbers"],
            }
            for item in canonical
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
