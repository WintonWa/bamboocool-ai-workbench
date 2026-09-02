"""Read the forecast run and the per-day series the day-by-day board renders.

Run model (decided 2026-08-30)
------------------------------
The v0.3.0 package is treated as **one static snapshot -- the latest run's
output**. There is deliberately no multi-run handling, no latest-run derivation,
no staleness display and no write-back path: the package carries a single global
run row (``run_mode: golden_only``), so every child shares one ``as_of_date``
and a freshness field would be a constant. The contract's ``created_at``
tiebreaker and per-child run dates stay in ``07-预测Agent接口契约.md`` for when
a real Agent starts producing runs; none of that machinery is built here.

What the page still computes itself (R1 方案 B)
----------------------------------------------
Only the demand judgment is read: ``p10 / p50 / p90`` per day. The balance
projection, cover days, stockout date, shortage, replenishment quantity and the
five risk types are computed in ``compute.py`` so parameter changes still
recalculate, and so the projection can be run three times over the band to give
a stockout **range** instead of a single date.

The package also ships its own ``fact_child_inventory_projection_daily`` and
``fact_child_inventory_decision``. Those are NOT read as page output -- they are
exposed here as a comparison baseline so a gate can check the page's own
arithmetic against them.

Two sources
-----------
* the package -- forecast, model evaluation, projection/decision baseline
* ``derived/chart_cache.sqlite`` -- per-day history and event ranges, keyed
  ``(child_asin, date)``. See ``derived/build_cache.py`` for why it exists.
"""

from __future__ import annotations

import sqlite3
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any

from core import db as _db

from . import data
from . import agent_forecast as _agent

# 模块私有派生产物。搬进工作台后 forecast.py 与 derived/ 同级，
# 所以少一层 parent。路径就地算，不写死绝对路径（迁移指导第 6 节）。
CACHE_DB = Path(__file__).resolve().parent / "derived" / "chart_cache.sqlite"

# 固定整数泳道：同一类事件在不同子体上必须落在同一高度，否则运营得重新认一遍。
EVENT_LANE_MAX = 6

# 选用模型 -> 中文。内部模型名绝不上屏。
MODEL_LABEL = {
    "trend_seasonal": "趋势+季节",
    "seasonal_naive_4w": "四周同期",
    "lifecycle_damped": "生命周期衰减",
}


def cache_available() -> bool:
    return CACHE_DB.is_file()


def _cache() -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{CACHE_DB}?mode=ro", uri=True, check_same_thread=False)
    con.row_factory = sqlite3.Row
    # 一个字节读坏不该让整页 500。实测过一次：主机可用内存压到 350MB 时
    # demand_quality_flag 读成 'd_shock\ufffd'（ad_shock 偏了一字节），
    # 而文件本身 integrity_check ok、用 bytes 全扫零个非法值 —— 坏在内存不在磁盘。
    # 默认的严格解码会把 OperationalError 抛到路由层，342 个对象里一行坏值就打掉列表页。
    con.text_factory = lambda b: b.decode("utf-8", "replace")
    return con


# 连接按**线程**复用，不能用 @lru_cache 缓存成一个全局单例。
# 服务是 ThreadingHTTPServer，页面会并行取 meta 与对象详情，两个线程用同一个
# SQLite 连接会偶发 database disk image is malformed —— 文件是好的
# （quick_check ok），只是连接不给并发用，check_same_thread=False 只解除检查
# 不做串行化。这条是外壳交接件里点名「最严重、覆盖所有模块」的那个坑。
_local = threading.local()


def _con_cache() -> sqlite3.Connection:
    """派生缓存的线程局部连接。

    不走 core.db.pool()，因为这个连接要挂自定义 text_factory
    （见 _cache()：一个字节读坏不该让整页 500）。
    """
    con = getattr(_local, "cache_con", None)
    if con is None:
        con = _cache()
        _local.cache_con = con
    return con


def _con_pkg() -> sqlite3.Connection:
    """产品包的只读连接，直接用外壳的线程局部池。"""
    return _db.pool(data.DB_PATH)


@lru_cache(maxsize=1)
def run() -> dict[str, Any] | None:
    """The single run record. One row for the whole package by design."""
    con = _con_pkg()
    row = con.execute("SELECT * FROM fact_child_forecast_run LIMIT 1").fetchone()
    if row is None:
        return None
    out = dict(row)
    out["candidate_model_labels"] = [
        MODEL_LABEL.get(m, m)
        for m in (out.get("candidate_models") or "").strip("[]").replace('"', "").split(",")
        if m
    ]
    return out


def run_for(child_asin: str) -> dict[str, Any] | None:
    """优先返回该子体的 Agent run；没有完整 run 才回落数据包快照。"""
    got = _agent.latest(child_asin)
    if got:
        r = got["run"]
        return {
            "forecast_run_id": r["run_id"],
            "as_of_date": r["data_as_of"],
            "horizon_days": r["horizon_days"],
            "validation_days": None,
            "candidate_model_labels": ["Pi Agent"],
            "model_version": r.get("model_version"),
            "confidence": r.get("confidence"),
            "confidence_reason": r.get("confidence_reason"),
            "judgment_summary": r.get("judgment_summary"),
            "origin": "agent",
        }
    fallback = run()
    if fallback:
        fallback = dict(fallback)
        fallback["origin"] = "package"
    return fallback


@lru_cache(maxsize=1)
def _model_by_child() -> dict[str, dict[str, Any]]:
    """Per-child selected model and its backtest error. This IS per-child, unlike
    the run record, so it is what the board header shows."""
    out: dict[str, dict[str, Any]] = {}
    for r in _con_pkg().execute(
        "SELECT * FROM fact_child_forecast_evaluation WHERE selected=1"
    ):
        d = dict(r)
        d["model_label"] = MODEL_LABEL.get(d["model_name"], d["model_name"])
        out[d["child_asin"]] = d
    return out


def model_for(child_asin: str) -> dict[str, Any] | None:
    return _model_by_child().get(child_asin)


def forecast_daily(child_asin: str) -> list[dict[str, Any]]:
    """优先读 Agent 同一 run 的90天结果，否则读 v0.3.0 快照。"""
    got = _agent.latest(child_asin)
    if got:
        return [
            {
                "forecast_date": row["forecast_date"],
                "p10_units": row["p10_units"],
                "p50_units": row["p50_units"],
                "p90_units": row["p90_units"],
                "baseline_units": row.get("baseline_units"),
                "weekday_factor": None,
                "seasonality_factor": None,
                "lifecycle_factor": None,
                "advertising_effect_ratio": None,
                "price_effect_ratio": None,
                "promotion_effect_ratio": None,
                "selected_model": "Pi Agent",
                "model_wape": None,
                "confidence_score": None,
                "effect_source": "agent",
            }
            for row in got["daily"]
        ]
    rows = _con_pkg().execute(
        "SELECT forecast_date, p10_units, p50_units, p90_units, baseline_units,"
        " weekday_factor, seasonality_factor, lifecycle_factor,"
        " advertising_effect_ratio, price_effect_ratio, promotion_effect_ratio,"
        " selected_model, model_wape, confidence_score, effect_source"
        " FROM fact_child_forecast_daily WHERE child_asin=? ORDER BY forecast_date",
        (child_asin,),
    )
    return [dict(r) for r in rows]


def history_daily(child_asin: str) -> list[dict[str, Any]]:
    if not cache_available():
        return []
    rows = _con_cache().execute(
        "SELECT * FROM chart_daily WHERE child_asin=? ORDER BY date", (child_asin,)
    )
    return [dict(r) for r in rows]


def events(child_asin: str) -> list[dict[str, Any]]:
    if not cache_available():
        return []
    rows = _con_cache().execute(
        "SELECT * FROM chart_event WHERE child_asin=? ORDER BY date_from, lane DESC",
        (child_asin,),
    )
    return [dict(r) for r in rows]


def windows(child_asin: str) -> dict[str, Any]:
    """Rolling-window totals computed from the SAME per-day rows the chart draws.

    The package's own ``fact_sales_window`` is the customer's per-child figure,
    but it disagrees with the per-day series by a median of 20% at child level:
    the customer's two sources contradict each other (their per-child windows do
    not sum to their own parent daily), and the package anchored the allocation
    on the parent, which reconciles exactly.

    Screen consistency wins here. Every sales number the page shows -- sidebar
    column, monthly box, chart bars -- is derived from one series, so bars always
    add up to the headline. Parent-level totals still match customer truth
    exactly; only the child-level split is an allocation.
    """
    if not cache_available():
        return {}
    as_of = data.meta()["as_of_date"]
    con = _con_cache()
    out: dict[str, Any] = {"origin": "allocated_from_parent_actual", "as_of": as_of}
    for days in (3, 7, 14, 30, 60, 90):
        r = con.execute(
            "SELECT COALESCE(SUM(units_sold),0) u, COALESCE(SUM(net_sales),0) s,"
            " COUNT(*) n FROM chart_daily"
            " WHERE child_asin=? AND date > date(?, ?)",
            (child_asin, as_of, f"-{days} day"),
        ).fetchone()
        out[f"units_{days}d"] = r["u"]
        out[f"net_sales_{days}d"] = round(r["s"], 2)
        out[f"daily_avg_{days}d"] = round(r["u"] / days, 3) if days else None
        out[f"observed_days_{days}d"] = r["n"]
    return out


def month_actuals(child_asin: str, period: str) -> dict[str, Any]:
    """Month totals from the same per-day series, for the 经营 box."""
    if not cache_available():
        return {}
    r = _con_cache().execute(
        "SELECT COALESCE(SUM(units_sold),0) units, COALESCE(SUM(net_sales),0) net,"
        " COALESCE(SUM(ad_spend),0) ad, COUNT(*) days FROM chart_daily"
        " WHERE child_asin=? AND substr(date,1,7)=?",
        (child_asin, period),
    ).fetchone()
    return {
        "period": period,
        "units_sold": r["units"],
        "net_sales": round(r["net"], 2),
        "ad_spend": round(r["ad"], 2),
        "days": r["days"],
    }


def supply_plan(child_asin: str) -> list[dict[str, Any]]:
    """Planned inbound shipments with per-child ETAs.

    v0.2.2 only knew shipment dates at style level, so in-transit stock could not
    enter the balance projection. This table attributes them to the child, which
    is why the projection can now count them.

    Arrival day is ``eta_earliest``: that is the convention the package's own
    projection uses (342 of 342 confirmed events land there, none on the late
    edge), so the page matches it instead of inventing a second convention.
    """
    rows = _con_pkg().execute(
        "SELECT plan_event_id, planned_units, eta_earliest, eta_latest, transport_mode,"
        " event_status, confidence_level FROM plan_child_supply_event"
        " WHERE child_asin=? ORDER BY eta_earliest",
        (child_asin,),
    )
    out = []
    for r in rows:
        d = dict(r)
        d["is_confirmed"] = d["event_status"] == "confirmed"
        d["mode_label"] = {"air": "空运", "sea": "海运"}.get(d["transport_mode"], d["transport_mode"])
        d["status_label"] = {"confirmed": "已确认", "planned": "计划中"}.get(
            d["event_status"], d["event_status"]
        )
        out.append(d)
    return out


def decision_baseline(child_asin: str) -> dict[str, Any] | None:
    """The package's own replenishment conclusion.

    Not page output: the page computes its own downstream so parameters stay
    live. Kept as a comparison baseline for the gate.
    """
    r = _con_pkg().execute(
        "SELECT * FROM fact_child_inventory_decision WHERE child_asin=?", (child_asin,)
    ).fetchone()
    return dict(r) if r else None


def projection_baseline(child_asin: str, scenario: str = "base") -> list[dict[str, Any]]:
    rows = _con_pkg().execute(
        "SELECT projection_date, opening_sellable, confirmed_arrivals, forecast_demand,"
        " closing_sellable, safety_stock_units, coverage_days, risk_status"
        " FROM fact_child_inventory_projection_daily"
        " WHERE child_asin=? AND scenario=? ORDER BY projection_date",
        (child_asin, scenario),
    )
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# 需求判断：Agent 的数字与判断同 run；没有完整 run 才回落统计口径
# ---------------------------------------------------------------------------

# 置信度档位。**与 compute.build_demand() 里那三行是同一套阈值**
# （score >= 0.85 高 / >= 0.70 中 / 其余 低）—— 一屏之内不能有两套口径。
# 两处目前各写一份，是有意不动 compute.py 的结果；重复已登记，见交付报告。
CONFIDENCE_CUTS = (0.85, 0.70)


def grade_confidence(score: float | None) -> str | None:
    """0-1 的统计分数 -> 中文档位。给不出分数就给 None，不编一个「中」。"""
    if score is None:
        return None
    try:
        s = float(score)
    except (TypeError, ValueError):
        return None
    hi, mid = CONFIDENCE_CUTS
    return "高" if s >= hi else ("中" if s >= mid else "低")


def judgment(child_asin: str) -> dict[str, Any]:
    """需求判断一层。Agent 跑过就读结论库，没跑过回落数据包的统计口径。

    **`origin` 是这个函数存在的理由**（契约 §3：回落必须看得出来，
    否则运营会以为每个对象都被判断过了）。所以两条来源**不做成同一形状** ——
    这一点与盘点结论那边故意相反：`verdict.build()` 把两条来源做成同形是为了让
    页面不分支，而这里两条来源的信息量根本不同（判断有中文依据、有逐项调整与影响
    幅度；统计口径只有一个回测分数），硬对齐就是拿分数冒充判断。

    90 天逐日 P10/P50/P90 跟着同一条来源走：Agent 跑过就是它那次 run 的，
    没跑过才是数据包快照。见 `forecast_daily()` 与
    01-方案与数据需求/12-需求预测Agent职责修订.md 第 3 节。
    """
    got = _agent.latest(child_asin)
    if got:
        run_row = got["run"]
        return {
            "origin": "agent",
            "origin_label": "Agent 判断",
            "is_agent": True,
            "confidence": run_row.get("confidence"),
            "confidence_reason": run_row.get("confidence_reason"),
            "summary": run_row.get("judgment_summary"),
            "factors": got["factors"],
            # 执行过程。落库的步骤原样带出（剔掉码值列），让「跑于 …」那个戳
            # 能点开回看这一次是怎么跑的 —— 在这之前过程只在跑的那一刻存在过。
            "steps": _agent.step_list(got["steps"]),
            "run": _agent.run_meta(run_row),
        }

    # 回落：包里 fact_child_forecast_evaluation 的选中模型 + confidence_score。
    # 这是统计口径，不是判断 —— 没有中文依据，也没有逐项调整，factors 就该是空的，
    # 不用逐日因子分解去填满它冒充「五项都判过了」。
    model = model_for(child_asin) or {}
    r = run() or {}
    score = model.get("confidence_score")
    wape = model.get("wape")
    reason = None
    if wape is not None and r.get("validation_days"):
        reason = f"{r['validation_days']} 天回测平均偏差 {wape * 100:.1f}%"
    elif wape is not None:
        reason = f"回测平均偏差 {wape * 100:.1f}%"
    return {
        "origin": "package",
        "origin_label": "统计口径",
        "is_agent": False,
        "confidence": grade_confidence(score),
        "confidence_reason": reason,
        "summary": None,
        "factors": [],
        "steps": [],
        "run": None,
        # 回落侧的两个事实，页面要能说出「这个档位是怎么来的」
        "model_label": model.get("model_label"),
        "confidence_score": score,
    }


def coverage() -> dict[str, Any]:
    con = _con_pkg()
    r = run()
    kids = con.execute(
        "SELECT COUNT(DISTINCT child_asin) n FROM fact_child_forecast_daily"
    ).fetchone()["n"]
    cache_rows = 0
    if cache_available():
        cache_rows = _con_cache().execute("SELECT COUNT(*) n FROM chart_daily").fetchone()["n"]
    return {
        "run_id": (r or {}).get("forecast_run_id"),
        "as_of_date": (r or {}).get("as_of_date"),
        "horizon_days": (r or {}).get("horizon_days"),
        "children_with_forecast": kids,
        "cache_available": cache_available(),
        "cache_daily_rows": cache_rows,
        "agent": _agent.coverage(),
    }
