"""需求预测 Agent → 工作台 → 库存计算纵向门禁。

运行：``PYTHONPATH=. /usr/bin/python3 tests/probe_demand_forecast.py``
"""

from __future__ import annotations

from modules.inventory import agent_forecast, compute, rules

SUBJECT = "B0B3LM36WB"


def main() -> None:
    got = agent_forecast.latest(SUBJECT)
    assert got is not None, "工作台未读到完整 Agent run"
    assert len(got["daily"]) == 90
    assert len(got["factors"]) == 5
    assert len(got["steps"]) >= 7
    assert got["run"]["status"] == "completed"

    assessment = compute.assess(SUBJECT, rules.from_params({}))
    assert assessment is not None
    demand = assessment["demand"]
    assert demand["origin"] == "agent"
    assert demand["run"]["run_id"] == got["run"]["run_id"]
    assert demand["horizon_effective_days"] == 90
    assert demand["forecast_90d"] > 0
    assert assessment["projection"]["available"] is True

    print({
        "run_id": got["run"]["run_id"],
        "daily": len(got["daily"]),
        "factors": len(got["factors"]),
        "steps": len(got["steps"]),
        "forecast_90d": demand["forecast_90d"],
        "demand_origin": demand["origin"],
        "projection_available": assessment["projection"]["available"],
    })
    print("DEMAND FORECAST WORKBENCH PASS")


if __name__ == "__main__":
    main()
