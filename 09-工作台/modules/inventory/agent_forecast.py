"""需求预测 Agent 结果库的只读边界。

只有一份完整、已完成并通过形状检查的 run 才会上屏：同一 run 必须同时拥有
90 行连续逐日预测、五项需求判断和执行步骤。任何一部分缺失都返回 ``None``，
由 ``forecast.py`` 明确回落到 v0.3.0 数据包快照。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from core import db as _db

FORECAST_DB = Path(__file__).resolve().parent / "derived" / "forecast_agent.sqlite"

RUN_TABLE = "fact_child_forecast_agent_run"
DAILY_TABLE = "fact_child_forecast_agent_daily"
FACTOR_TABLE = "fact_child_forecast_judgment_factor"
STEP_TABLE = "fact_child_forecast_agent_step"

FACTORS = ("stockout_distortion", "promotion", "lifecycle", "advertising", "seasonality")
FACTOR_LABEL = {
    "stockout_distortion": "缺货扭曲",
    "promotion": "站内活动",
    "lifecycle": "生命周期",
    "advertising": "广告投放",
    "seasonality": "季节性",
}
STATES = {
    "stockout_distortion": ("无扭曲", "轻度扭曲", "重度扭曲"),
    "promotion": ("无活动", "有活动且已回落", "有活动仍在影响"),
    "lifecycle": ("爬坡", "平稳", "衰退"),
    "advertising": ("无投放", "平稳", "加大", "减少"),
    "seasonality": ("不明显", "旺季", "淡季"),
}
TRIGGER_LABEL = {"manual": "手动", "weekly": "定时", "priority": "重点对象"}
_CAND_LIMIT = 50


def available() -> bool:
    return FORECAST_DB.is_file()


def _con() -> sqlite3.Connection | None:
    if not available():
        return None
    try:
        return _db.pool(FORECAST_DB)
    except (sqlite3.Error, OSError):
        return None


def _stamp(raw: str | None) -> datetime:
    value = (raw or "").strip().replace("Z", "+00:00").replace(" ", "T")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
    return parsed.astimezone() if parsed.tzinfo is None else parsed


def _json_object(raw: str | None) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _json_list(raw: str | None) -> list[Any]:
    try:
        value = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    return value if isinstance(value, list) else []


def _valid_daily(run: dict[str, Any], rows: list[sqlite3.Row]) -> bool:
    horizon = int(run.get("horizon_days") or 0)
    if horizon != 90 or len(rows) != horizon:
        return False
    try:
        expected = date.fromisoformat(str(run["data_as_of"])) + timedelta(days=1)
    except (KeyError, TypeError, ValueError):
        return False
    for offset, row in enumerate(rows):
        if row["forecast_date"] != (expected + timedelta(days=offset)).isoformat():
            return False
        try:
            p10, p50, p90 = float(row["p10_units"]), float(row["p50_units"]), float(row["p90_units"])
        except (TypeError, ValueError):
            return False
        if p10 < 0 or not p10 <= p50 <= p90:
            return False
    return True


def latest(child_asin: str) -> dict[str, Any] | None:
    """读取该对象最新的完整 completed run；不完整时整批拒绝。"""
    if not child_asin:
        return None
    con = _con()
    if con is None:
        return None
    try:
        candidates = con.execute(
            f"SELECT * FROM {RUN_TABLE} WHERE child_asin=? AND status='completed' "
            "ORDER BY run_date DESC, created_at DESC LIMIT ?",
            (child_asin, _CAND_LIMIT),
        ).fetchall()
    except sqlite3.Error:
        return None
    if not candidates:
        return None

    # 同一业务基准日内按真实时刻取最新，不能按带 Z / 带偏移的原字符串比较。
    top_date = candidates[0]["run_date"]
    run_row = max((r for r in candidates if r["run_date"] == top_date), key=lambda r: _stamp(r["created_at"]))
    run = dict(run_row)
    try:
        daily_rows = con.execute(
            f"SELECT * FROM {DAILY_TABLE} WHERE run_id=? ORDER BY forecast_date", (run["run_id"],)
        ).fetchall()
        factor_rows = con.execute(
            f"SELECT * FROM {FACTOR_TABLE} WHERE run_id=? ORDER BY ord", (run["run_id"],)
        ).fetchall()
        step_rows = con.execute(
            f"SELECT * FROM {STEP_TABLE} WHERE run_id=? ORDER BY step_seq", (run["run_id"],)
        ).fetchall()
    except sqlite3.Error:
        return None

    if not _valid_daily(run, daily_rows) or len(factor_rows) != 5 or not step_rows:
        return None

    factors: list[dict[str, Any]] = []
    seen: set[str] = set()
    ords: set[int] = set()
    for row in factor_rows:
        factor, state = row["factor"], row["state"]
        if factor not in STATES or state not in STATES[factor] or factor in seen:
            return None
        seen.add(factor)
        ords.add(int(row["ord"]))
        factors.append({
            "factor": factor,
            "label": FACTOR_LABEL[factor],
            "ord": row["ord"],
            "state": state,
            "impact_pct": float(row["impact_pct"]) if row["impact_pct"] is not None else None,
            "because": row["because"],
            "numbers": _json_object(row["numbers"]),
        })
    if seen != set(FACTORS) or ords != {1, 2, 3, 4, 5}:
        return None

    daily = [dict(row) for row in daily_rows]
    steps = []
    for row in step_rows:
        step = dict(row)
        step["sources"] = _json_list(step.get("sources"))
        steps.append(step)
    return {"run": run, "daily": daily, "factors": factors, "steps": steps}


def run_meta(run: dict[str, Any]) -> dict[str, Any]:
    trigger = run.get("trigger")
    return {
        "run_id": run.get("run_id"),
        "run_date": run.get("run_date"),
        "actual_run_date": run.get("actual_run_date"),
        "created_at": run.get("created_at"),
        "completed_at": run.get("completed_at"),
        "data_as_of": run.get("data_as_of"),
        "horizon_days": run.get("horizon_days"),
        "trigger": trigger,
        "trigger_label": TRIGGER_LABEL.get(trigger, "—"),
        "model_version": run.get("model_version"),
        "prompt_version": run.get("prompt_version"),
        "method_version": run.get("method_version"),
        "comparison_snapshot_run_id": run.get("comparison_snapshot_run_id"),
        "prev_run_id": run.get("prev_run_id"),
    }


def step_list(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把步骤行整成上屏形状。

    **`tool` 一个字都不出去** —— 它装的是 `load_sales_inventory_history`
    这类码值（G9 扫这个）。上屏靠 `label` / `detail` / `sources`，三样 Agent
    都给了中文。`run_id` 也剔掉：run 那一层已经有了，重复带只会让载荷变胖。

    `duration_ms` 带出去但页面现在不显示 —— 七步合计只有几毫秒，而一次运行
    实测 107 秒，模型耗时没被归到任何一步。把这种数字摆到屏幕上，读的人会
    以为这次运行只花了几毫秒。归因修好之前它只留给门禁用。
    见 01-方案与数据需求/13-需求预测Agent分段运行需求.md R5。
    """
    out: list[dict[str, Any]] = []
    for s in steps:
        out.append({
            "seq": s.get("step_seq"),
            "label": s.get("label"),
            "detail": s.get("detail"),
            "status": s.get("status"),
            "duration_ms": s.get("duration_ms"),
            "sources": s.get("sources") or [],
        })
    return out


def coverage() -> dict[str, Any]:
    out = {"available": available(), "children_with_forecast": 0, "runs": 0}
    con = _con()
    if con is None:
        return out
    try:
        row = con.execute(
            f"SELECT COUNT(*) n, COUNT(DISTINCT child_asin) kids FROM {RUN_TABLE} WHERE status='completed'"
        ).fetchone()
    except sqlite3.Error:
        return out
    out.update(runs=row["n"], children_with_forecast=row["kids"])
    return out
