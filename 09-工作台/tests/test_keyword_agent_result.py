#!/usr/bin/env python3
"""Keyword Agent publication selection, cache isolation and stale-copy gates."""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from modules.keyword import agent_result, data, module  # noqa: E402


PARAMS = {
    "compare": "day",
    "rank_shift": 3,
    "group_dedup": True,
    "weights": {
        "w_demand": 0.3,
        "w_change": 0.3,
        "w_push": 0.2,
        "w_evidence": 0.2,
    },
}


def _published(current: Path, state: Path, run_id: str = "run-good") -> None:
    con = sqlite3.connect(current)
    con.execute("""CREATE TABLE fact_keyword_agent_manifest (
        run_id TEXT PRIMARY KEY, context_hash TEXT NOT NULL,
        params_json TEXT NOT NULL, status TEXT NOT NULL, completed_at TEXT)""")
    con.execute(
        "INSERT INTO fact_keyword_agent_manifest VALUES (?, 'ctx', ?, 'completed', 'now')",
        (run_id, json.dumps(PARAMS)),
    )
    con.commit()
    con.close()
    con = sqlite3.connect(state)
    con.execute("""CREATE TABLE fact_keyword_agent_run (
        run_id TEXT PRIMARY KEY, context_hash TEXT, status TEXT)""")
    con.execute("INSERT INTO fact_keyword_agent_run VALUES (?, 'ctx', 'completed')", (run_id,))
    con.commit()
    con.close()


def _scope_db(path: Path, scope_id: str) -> None:
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE dim_keyword_scope (scope_id TEXT, as_of_date TEXT)")
    con.execute("INSERT INTO dim_keyword_scope VALUES (?, '2026-08-03')", (scope_id,))
    con.commit()
    con.close()


class KeywordAgentResultTest(unittest.TestCase):
    def test_current_requires_completed_ledger_and_matching_params(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            base, current, state = root / "base.sqlite", root / "current.sqlite", root / "state.sqlite"
            base.touch()
            _published(current, state)

            matched = agent_result.select_database(base, PARAMS, current, state)
            self.assertEqual(matched.status, "current")
            self.assertEqual(matched.path, current)

            changed = json.loads(json.dumps(PARAMS))
            changed["compare"] = "week"
            stale = agent_result.select_database(base, changed, current, state)
            self.assertEqual(stale.status, "stale")
            self.assertEqual(stale.path, base)
            self.assertIn("不一致", stale.reason)

            changed = json.loads(json.dumps(PARAMS))
            changed["weights"]["w_demand"] = 0.5
            stale = agent_result.select_database(base, changed, current, state)
            self.assertEqual(stale.status, "stale")
            self.assertEqual(stale.path, base)

    def test_request_database_context_never_reuses_previous_scope(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            first, second = root / "first.sqlite", root / "second.sqlite"
            _scope_db(first, "first")
            _scope_db(second, "second")
            with data.use_database(first):
                self.assertEqual(data.scope()["scope_id"], "first")
            with data.use_database(second):
                self.assertEqual(data.scope()["scope_id"], "second")
            with data.use_database(first):
                self.assertEqual(data.scope()["scope_id"], "first")

    def test_stale_overview_hides_all_five_agent_answers_and_refs(self):
        payload = {
            "reports": [{
                "q1_traffic_result": "old1", "q2_main_movers": "old2",
                "q3_core_coverage_change": "old3", "q4_new_signals": "old4",
                "q5_priority_next": "old5",
                "priority_evidence_ids": ["ev_old"],
                "coverage_event_ids": ["ce_old"],
            }]
        }
        selection = agent_result.Selection(
            Path("base.sqlite"), "stale", "old-run", "参数不一致"
        )
        out = module._hide_stale_report(payload, selection)
        report = out["reports"][0]
        for key in (
            "q1_traffic_result", "q2_main_movers", "q3_core_coverage_change",
            "q4_new_signals", "q5_priority_next",
        ):
            self.assertEqual(report[key], module._STALE_REPORT)
        self.assertEqual(report["priority_evidence_ids"], [])
        self.assertEqual(report["coverage_event_ids"], [])
        self.assertEqual(out["agent_result"]["condition"], "过期")


if __name__ == "__main__":
    unittest.main()
