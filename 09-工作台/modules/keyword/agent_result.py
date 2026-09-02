"""Resolve the latest fully published keyword Agent business database.

Both the business manifest and the sidecar ledger must say completed with the
same run/context.  A writing/failed run can therefore never become visible to
the six existing GET routes.
"""

from __future__ import annotations

import sqlite3
import json
from dataclasses import dataclass
from pathlib import Path


DERIVED = Path(__file__).resolve().parent / "derived"
CURRENT_DB = DERIVED / "keyword_agent_current.sqlite"
STATE_DB = DERIVED / "keyword_agent_state.sqlite"

DEFAULT_AGENT_PARAMS = {
    "compare": "day",
    "rank_shift": 3,
    "group_dedup": True,
    "weights": {
        "w_demand": 0.30,
        "w_change": 0.30,
        "w_push": 0.20,
        "w_evidence": 0.20,
    },
}


@dataclass(frozen=True)
class Selection:
    path: Path
    status: str
    run_id: str | None = None
    reason: str | None = None


def _contract(params: dict | None) -> dict:
    source = params or DEFAULT_AGENT_PARAMS
    weights = source.get("weights") or {}
    return {
        "compare": source.get("compare", "day"),
        "rank_shift": int(source.get("rank_shift", 3)),
        "group_dedup": bool(source.get("group_dedup", True)),
        "weights": {
            key: round(float(weights.get(key, DEFAULT_AGENT_PARAMS["weights"][key])), 4)
            for key in DEFAULT_AGENT_PARAMS["weights"]
        },
    }


def select_database(
    base: Path,
    request_params: dict | None = None,
    current_path: Path = CURRENT_DB,
    state_path: Path = STATE_DB,
) -> Selection:
    """Select current only when publication and judgment parameters both match."""
    if not current_path.is_file() or not state_path.is_file():
        return Selection(base, "base", reason="没有已发布的关键词 Agent 结果")
    business = state = None
    try:
        business = sqlite3.connect(f"file:{current_path}?mode=ro", uri=True)
        state = sqlite3.connect(f"file:{state_path}?mode=ro", uri=True)
        manifest = business.execute(
            "SELECT run_id, context_hash, params_json, status "
            "FROM fact_keyword_agent_manifest LIMIT 1"
        ).fetchone()
        if not manifest or manifest[3] != "completed":
            return Selection(base, "base", reason="current manifest 未完成")
        run = state.execute(
            "SELECT context_hash, status FROM fact_keyword_agent_run WHERE run_id=?",
            (manifest[0],),
        ).fetchone()
        if not run or run[1] != "completed" or run[0] != manifest[1]:
            return Selection(base, "base", reason="current 与 completed 台账不一致")
        try:
            published_params = _contract(json.loads(manifest[2]))
        except (TypeError, ValueError, json.JSONDecodeError):
            return Selection(base, "base", reason="current 参数契约不可解析")
        if _contract(request_params) != published_params:
            return Selection(
                base,
                "stale",
                run_id=manifest[0],
                reason="当前比较周期或优先级权重与最近 Agent 运行不一致",
            )
        return Selection(current_path, "current", run_id=manifest[0])
    except (sqlite3.Error, OSError):
        return Selection(base, "base", reason="current 或台账不可读")
    finally:
        if business is not None:
            business.close()
        if state is not None:
            state.close()


def database_path(base: Path, request_params: dict | None = None) -> Path:
    """Backward-compatible path-only resolver using the default Agent contract."""
    return select_database(base, request_params).path
