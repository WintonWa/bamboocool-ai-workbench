#!/usr/bin/env python3
"""关键词模块只转接 Loop 运行态，不放宽正式结果选库门禁。"""

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.keyword import module  # noqa: E402


class KeywordLoopTaskContractTest(unittest.TestCase):
    def test_module_declares_polling_task_without_object_gate(self):
        task = module.MODULE["tasks"][0]
        self.assertEqual(task["label"], "运行关键词分析")
        self.assertEqual(task["run"], "run-agent-loop")
        self.assertEqual(task["poll"], "agent-loop-status")
        self.assertNotIn("needs", task)
        self.assertIn("run-agent-loop", module.MODULE["routes"])
        self.assertIn("agent-loop-status", module.MODULE["routes"])

    def test_internal_state_maps_to_shared_task_panel_contract(self):
        payload = module._loop_panel({
            "run": {
                "run_id": "keyword-loop-test",
                "status": "completed",
                "current_step": 6,
                "total_steps": 6,
                "model_version": "test/pi",
                "message": "Loop 演示完成，未发布业务结果",
            },
            "steps": [{
                "label": "在 Demo 边界收口",
                "detail": "Loop 演示已结束，未发布业务结果",
                "status": "completed",
                "sources": ["关键词 Agent 运行态"],
            }],
        })
        self.assertEqual(payload["run"]["status"], "完成")
        self.assertIsNone(payload["run"]["object_id"])
        self.assertIn("未发布业务结果", payload["run"]["message"])
        self.assertEqual(payload["steps"][0]["status"], "完成")
        self.assertNotIn("fact_", str(payload))


if __name__ == "__main__":
    unittest.main()
