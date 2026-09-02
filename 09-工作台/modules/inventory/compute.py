"""Runtime calculation: forecast -> projection -> coverage -> fee -> risks.

Nothing here is persisted. Every number is recomputed on each request so the
parameter panel can change a threshold and the page updates. Anything that
cannot be computed returns an explicit reason instead of a fabricated value.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from . import data
from . import forecast
from .rules import RuleSet

AS_OF = date.fromisoformat("2026-08-03")
AGED_BUCKETS = ["181-270天库龄", "271-330天库龄", "331-365天库龄", "大于365天库龄"]

RISK_SHORTAGE = "shortage"
RISK_OVERSTOCK = "overstock"
RISK_AVAILABILITY = "availability"
RISK_AGING = "aging"
RISK_FEE = "storage_fee"

RISK_LABELS = {
    RISK_SHORTAGE: "库存不足",
    RISK_OVERSTOCK: "超量备货",
    RISK_AVAILABILITY: "库存可用性异常",
    RISK_AGING: "库龄风险",
    RISK_FEE: "仓储费风险",
}


MONTH_PERIOD = "2026-06"
WEEKDAY_CN = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


def _num(value: Any, default: float = 0.0) -> float:
    return float(value) if isinstance(value, (int, float)) else default


# --------------------------------------------------------------------------- #
# 销量与需求
# --------------------------------------------------------------------------- #
def _weekday_cn(iso: str) -> str:
    return WEEKDAY_CN[date.fromisoformat(iso).weekday()]


def build_demand(asin: str, facts: dict[str, Any], rules: RuleSet) -> dict[str, Any]:
    """Demand comes from the forecast package. The page does not compute it.

    R1 deleted the six-window weighted average and the trend coefficient: a
    formula cannot know that a sales spike came from a BD that will not repeat.
    The package decides which history to trust; the workbench does the arithmetic
    downstream of that judgment (R1 方案 B).

    The package is one static snapshot of the latest run. Multi-run handling,
    per-child run dates and a freshness display are deliberately not built -- the
    run table carries a single global row, so freshness would be a constant.
    """
    run = forecast.run_for(asin)
    is_agent = bool(run and run.get("origin") == "agent")
    model = None if is_agent else forecast.model_for(asin)
    rows = forecast.forecast_daily(asin)
    history = forecast.history_daily(asin)

    if run is None or not rows:
        return {
            "available": False,
            "reason": "尚无预测结果",
            "detail": (
                "该子 ASIN 没有预测记录。覆盖天数、断货日、缺口量都以需求为输入，"
                "因此这些结论暂不给出。"
            ),
            "history_rows": len(history),
            "forecast_daily": 0.0,
            "forecast_90d": 0.0,
            "daily": [],
            "daily_lower": [],
            "daily_upper": [],
            "confidence": "unavailable",
            "confidence_label": "不可用",
            "confidence_reason": "尚无预测记录",
            "factors": [],
            "stale_days": None,
        }

    as_of_iso = AS_OF.isoformat()
    future = [r for r in rows if r["forecast_date"] > as_of_iso]
    elapsed = len(rows) - len(future)

    def series(key: str) -> list[dict[str, Any]]:
        return [
            {"date": r["forecast_date"], "forecast_units": float(r[key] or 0)}
            for r in future
        ]

    base = series("p50_units")
    lower = series("p10_units")
    upper = series("p90_units")
    horizon = len(base)
    total = sum(d["forecast_units"] for d in base)
    daily_mean = (total / horizon) if horizon else 0.0

    # 近 7 天实际（剔除缺货日）。替代原来的趋势系数，作为「需求上行」的信号，
    # 用的是真实数字而不是两个平滑窗口的比值。
    recent = [r for r in history if r["date"] > (AS_OF - timedelta(days=7)).isoformat()]
    ok = [float(r["units_sold"]) for r in recent if not r["stockout_flag"]]
    recent_daily = (sum(ok) / len(ok)) if ok else None
    vs_recent = (daily_mean / recent_daily) if recent_daily and recent_daily > 0 else None

    if is_agent:
        conf_label = str(run.get("confidence") or "不可用")
        conf = {"高": "high", "中": "medium", "低": "low"}.get(conf_label, "unavailable")
        conf_reason = run.get("confidence_reason")
        wape = None
        judgment = forecast.judgment(asin)
        factors = [
            {
                "label": item["label"],
                "basis": item.get("because") or "—",
                "state": item.get("state"),
                "impact_pct": item.get("impact_pct"),
            }
            for item in judgment.get("factors") or []
        ]
    else:
        # 快照回落：置信度来自包内回测分数，且明确标记为统计口径。
        score = (model or {}).get("confidence_score")
        wape = (model or {}).get("wape")
        if score is None:
            conf, conf_label = "unavailable", "不可用"
        elif score >= 0.85:
            conf, conf_label = "high", "高"
        elif score >= 0.70:
            conf, conf_label = "medium", "中"
        else:
            conf, conf_label = "low", "低"
        conf_reason = None
        if wape is not None:
            conf_reason = f"{run['validation_days']} 天回测平均偏差 {wape * 100:.1f}%"
        factors = []

    return {
        "available": True,
        "run": {
            "run_id": run["forecast_run_id"],
            "as_of_date": run["as_of_date"],
            "horizon_days": run["horizon_days"],
            "validation_days": run["validation_days"],
            "candidate_model_labels": run["candidate_model_labels"],
            "model_label": "Pi Agent" if is_agent else (model or {}).get("model_label"),
            "model_version": run.get("model_version"),
            "model_wape": wape,
            "model_bias": (model or {}).get("bias"),
            "model_mae": (model or {}).get("mae"),
            "origin": "agent" if is_agent else "package",
        },
        "confidence": conf,
        "confidence_label": conf_label,
        "confidence_reason": conf_reason,
        "factors": factors,
        "daily": base,
        "daily_lower": lower,
        "daily_upper": upper,
        "forecast_daily": round(daily_mean, 3),
        "forecast_90d": round(total, 1),
        "horizon_effective_days": horizon,
        "horizon_elapsed_days": elapsed,
        "horizon_note": None,
        "recent_actual_daily": round(recent_daily, 3) if recent_daily is not None else None,
        "vs_recent_actual": round(vs_recent, 3) if vs_recent is not None else None,
        "history_rows": len(history),
        "stale_days": None,
        "origin": "agent" if is_agent else "forecast_package",
    }


# --------------------------------------------------------------------------- #
# 库存构成与逐日投影
# --------------------------------------------------------------------------- #
def build_inventory(facts: dict[str, Any]) -> dict[str, Any]:
    inv = facts.get("inv") or {}
    if not inv:
        return {"available": False, "reason": "该子 ASIN 无当前库存快照记录"}

    sellable = int(_num(inv.get("fba_sellable")))
    reserved = int(_num(inv.get("fba_reserved")))
    transfer = int(_num(inv.get("pending_transfer")))
    receiving = int(_num(inv.get("fba_receiving")))
    fba_total = int(_num(inv.get("fba_inventory")))
    inbound = int(_num(inv.get("fba_inbound")))
    overseas = int(_num(inv.get("overseas_available")))
    local = int(_num(inv.get("local_available")))
    pending_delivery = int(_num(inv.get("pending_delivery")))
    total_known = int(_num(inv.get("total_inventory")))

    identity_gap = fba_total - (sellable + reserved + transfer + receiving)
    restricted = reserved + transfer + receiving

    return {
        "available": True,
        "locations": [
            {"location": "FBA", "sellable": sellable, "restricted": restricted, "total": fba_total},
            {"location": "AWD / 海外仓", "sellable": overseas, "restricted": 0, "total": overseas},
            {"location": "国内仓", "sellable": local, "restricted": pending_delivery, "total": local + pending_delivery},
        ],
        "states": [
            {"state": "可售", "qty": sellable, "immediate": True},
            {"state": "预留", "qty": reserved, "immediate": False},
            {"state": "待调仓", "qty": transfer, "immediate": False},
            {"state": "入库中", "qty": receiving, "immediate": False},
            {"state": "FBA 在途", "qty": inbound, "immediate": False},
            {"state": "海外仓可用", "qty": overseas, "immediate": False},
            {"state": "国内可用", "qty": local, "immediate": False},
            {"state": "待交付", "qty": pending_delivery, "immediate": False},
        ],
        "sellable_qty": sellable,
        "restricted_qty": restricted,
        "fba_total_qty": fba_total,
        "inbound_qty": inbound,
        "total_known_qty": total_known,
        "availability_rate": round(sellable / fba_total, 4) if fba_total else None,
        "identity_gap": identity_gap,
        "identity_note": (
            None
            if identity_gap == 0
            else f"客户表的 FBA 总库存比可售+预留+待调仓+入库中少 {abs(identity_gap)} 件，保留原值不强行配平"
        ),
        "origin": "customer_actual",
    }


def build_projection(
    facts: dict[str, Any], demand: dict[str, Any], inventory: dict[str, Any], rules: RuleSet
) -> dict[str, Any]:
    if not inventory.get("available"):
        return {"available": False, "reason": inventory.get("reason")}
    if not demand.get("available"):
        return {
            "available": False,
            "reason": demand.get("reason") or "尚无预测结果",
            "detail": demand.get("detail"),
        }

    plan = facts.get("plan") or {}
    safety_days = (
        int(rules.safety_days_override)
        if rules.safety_days_override is not None
        else int(_num(plan.get("safety_days"), 0))
    )
    safety_origin = "demo_override" if rules.safety_days_override is not None else "customer_actual"

    sellable = inventory["sellable_qty"]
    internal_release = inventory["restricted_qty"]
    lag = max(0, int(rules.internal_release_lag_days))

    # 计划到货：v0.3.0 起 ETA 到子体级，所以在途终于可以进余额曲线了。
    # 到货日取 eta_earliest（342/342 笔 confirmed 都落在这一端，与数据包投影一致），
    # 只计 event_status=confirmed；计划中的单独列出不计入。
    asin = (facts.get("child") or {}).get("child_asin")
    date_index = {d["date"]: i for i, d in enumerate(demand["daily"])}
    confirmed_arrivals: dict[int, float] = {lag: float(internal_release)}
    planned_pending = 0.0
    arrival_rows: list[dict[str, Any]] = []
    for ev in (forecast.supply_plan(asin) if asin else []):
        idx = date_index.get(ev["eta_earliest"])
        arrival_rows.append({
            "plan_event_id": ev["plan_event_id"],
            "units": ev["planned_units"],
            "eta": ev["eta_earliest"],
            "eta_latest": ev["eta_latest"],
            "mode_label": ev["mode_label"],
            "status_label": ev["status_label"],
            "in_window": idx is not None,
            "counted": bool(ev["is_confirmed"] and idx is not None),
        })
        if idx is None:
            continue
        if ev["is_confirmed"]:
            confirmed_arrivals[idx] = confirmed_arrivals.get(idx, 0.0) + float(ev["planned_units"])
        else:
            planned_pending += float(ev["planned_units"])

    def _walk(demand_days: list[dict[str, Any]], arrivals: dict[int, float],
              safety_qty: float) -> dict[str, Any]:
        """Walk the balance forward one day at a time. Pure arithmetic."""
        balance = float(sellable)
        series = []
        stockout_date = None
        safety_breach_date = None
        for index, day in enumerate(demand_days):
            arrival = arrivals.get(index, 0)
            opening = balance
            balance = balance + arrival - day["forecast_units"]
            series.append(
                {
                    "date": day["date"],
                    "opening": round(opening, 2),
                    "demand": day["forecast_units"],
                    "arrival": arrival,
                    "closing": round(balance, 2),
                }
            )
            if stockout_date is None and balance <= 0:
                stockout_date = day["date"]
            if safety_breach_date is None and balance <= safety_qty:
                safety_breach_date = day["date"]
        return {
            "series": series,
            "stockout_date": stockout_date,
            "safety_breach_date": safety_breach_date,
        }

    scopes: dict[str, dict[str, Any]] = {}
    for scope, arrivals in (
        ("sellable_only", {}),
        ("sellable_plus_confirmed", confirmed_arrivals),
    ):
        safety_qty = demand["forecast_daily"] * safety_days
        walked = _walk(demand["daily"], arrivals, safety_qty)
        series = walked["series"]
        stockout_date = walked["stockout_date"]
        safety_breach_date = walked["safety_breach_date"]

        # The Agent gives a band, not a line. Running the same projection over
        # the pessimistic and optimistic demand lines turns the stockout date
        # into a range — which is the whole reason the projection stayed on the
        # page instead of moving into the Agent.
        hi_demand = _walk(demand["daily_upper"], arrivals, safety_qty)
        lo_demand = _walk(demand["daily_lower"], arrivals, safety_qty)
        stockout_range = {
            "earliest": hi_demand["stockout_date"],
            "base": stockout_date,
            "latest": lo_demand["stockout_date"],
        }
        safety_breach_range = {
            "earliest": hi_demand["safety_breach_date"],
            "base": safety_breach_date,
            "latest": lo_demand["safety_breach_date"],
        }

        daily_demand = demand["forecast_daily"]
        opening_total = sellable + sum(arrivals.values())
        cover_days = (opening_total / daily_demand) if daily_demand > 0 else None
        horizon_demand = demand["forecast_90d"]
        scopes[scope] = {
            "series": series,
            "cover_days": round(cover_days, 1) if cover_days is not None else None,
            "cover_days_unavailable_reason": None if daily_demand > 0 else "预测日均为 0，覆盖天数不可计算",
            "stockout_date": stockout_date,
            "stockout_date_range": stockout_range,
            "safety_breach_date": safety_breach_date,
            "safety_breach_date_range": safety_breach_range,
            "safety_stock_qty": round(safety_qty, 1),
            "shortage_30d": round(max(0.0, sum(d["demand"] for d in series[:30]) + safety_qty - opening_total), 1),
            "shortage_90d": round(max(0.0, horizon_demand + safety_qty - opening_total), 1),
            "closing_at_horizon": series[-1]["closing"] if series else None,
        }

    daily_demand = demand["forecast_daily"]
    low_velocity = 0 < daily_demand < rules.low_velocity_daily_units
    reasonable_max = daily_demand * rules.max_cover_days
    excess_qty = max(0.0, inventory["total_known_qty"] - reasonable_max) if daily_demand > 0 else None
    depletion_days = (inventory["total_known_qty"] / daily_demand) if daily_demand > 0 else None
    depletion_reason = None
    if daily_demand <= 0:
        depletion_reason = "预测日均为 0，消化天数不可计算"
    elif low_velocity:
        depletion_reason = (
            f"预测日均仅 {daily_demand:.2f} 件，消化天数只能判断为「远超一年」，精确值无意义"
        )

    return {
        "available": True,
        "safety_days": safety_days,
        "safety_days_origin": safety_origin,
        "scopes": scopes,
        "low_velocity": low_velocity,
        "reasonable_max_qty": round(reasonable_max, 1) if daily_demand > 0 else None,
        "excess_qty": round(excess_qty, 1) if excess_qty is not None else None,
        "depletion_days": (
            None if depletion_days is None else (round(min(depletion_days, 999), 1) if not low_velocity else None)
        ),
        "depletion_unavailable_reason": depletion_reason,
        "unallocated_inbound_qty": inventory["inbound_qty"],
        "arrivals": arrival_rows,
        "confirmed_arrival_qty": round(sum(confirmed_arrivals.values()) - internal_release, 1),
        "planned_arrival_qty": round(planned_pending, 1),
        "internal_release_qty": internal_release,
        "inbound_note": (
            "FBA 在途数量是客户真实值。计划货件现在带子 ASIN 级预计到货日，"
            "已确认的那部分按最早到货日进入余额曲线"
        ),
        "origin": "derived",
    }


# --------------------------------------------------------------------------- #
# 库龄与仓储费
# --------------------------------------------------------------------------- #
def build_aging(facts: dict[str, Any]) -> dict[str, Any]:
    age = facts.get("age") or {}
    june = facts.get("age_june") or {}
    lots = facts.get("lots") or []
    roll = facts.get("roll") or {}

    buckets = [
        {"bucket": col, "qty": int(_num(age.get(col)))}
        for col in data.AGE_BUCKET_COLUMNS
    ]
    june_buckets = [
        {"bucket": col, "qty": int(_num(june.get(col)))}
        for col in data.AGE_BUCKET_COLUMNS
    ]
    crossing_3d = sum(l["quantity"] for l in lots if l["crosses_180_within_3d"])
    crossing_7d = sum(l["quantity"] for l in lots if l["crosses_180_within_7d"])
    aged_value = sum(_num(l["inventory_value"]) for l in lots if l["already_over_180"])
    has_cost = any(l["inventory_value"] is not None for l in lots)

    return {
        "as_of_buckets": buckets,
        "june_buckets": june_buckets,
        "total_qty": int(_num(age.get("total_qty"))),
        "aged_181_qty": int(_num(age.get("aged_181_plus_qty"))),
        "aged_181_share": age.get("aged_181_plus_share"),
        "aged_181_value": round(aged_value, 2) if has_cost else None,
        "aged_value_unavailable_reason": None if has_cost else "缺单位成本，货值不可计算",
        "crossing_180_within_3d": crossing_3d,
        "crossing_180_within_7d": crossing_7d,
        "lot_count": len(lots),
        "lots": lots,
        "rollforward": roll,
        "origin": "derived",
        "assumption": (
            "收货日由 2026-06-30 库龄档按 1 天均匀切片反推，按 FIFO 扣减真实 34 天销量后，"
            "对齐到 2026-08-03 的 FBA 总库存"
        ),
    }


def build_fee(facts: dict[str, Any], aging: dict[str, Any], rules: RuleSet) -> dict[str, Any]:
    econ = facts.get("econ") or {}
    month = facts.get("month") or {}
    unit_volume = econ.get("unit_volume_m3")
    if unit_volume is None:
        return {
            "available": False,
            "reason": f"缺单件体积（款号 {econ.get('style_no')} 在出货表中无记录）",
        }

    regular = 0.0
    aged = 0.0
    for row in aging["as_of_buckets"]:
        volume = row["qty"] * float(unit_volume)
        regular += volume * rules.fee_rate_per_m3_month
        if row["bucket"] in AGED_BUCKETS:
            aged += volume * rules.fee_aged_surcharge_per_m3_month.get(row["bucket"], 0.0)
    total = regular + aged

    net_sales = month.get("net_sales")
    gross = month.get("order_gross_profit")
    sales_ratio = (total / net_sales) if isinstance(net_sales, (int, float)) and net_sales > 0 else None
    gross_ratio = (total / gross) if isinstance(gross, (int, float)) and gross > 0 else None

    return {
        "available": True,
        "total_fee": round(total, 2),
        "regular_fee": round(regular, 2),
        "aged_surcharge": round(aged, 2),
        "billed_volume_m3": round(aging["total_qty"] * float(unit_volume), 4),
        "unit_volume_m3": unit_volume,
        "sales_ratio": round(sales_ratio, 4) if sales_ratio is not None else None,
        "gross_ratio": round(gross_ratio, 4) if gross_ratio is not None else None,
        "gross_ratio_unavailable_reason": (
            None if gross_ratio is not None else "月度毛利 ≤ 0 或缺失，费毛利比不可计算"
        ),
        "currency_status": econ.get("unit_cost_currency_status"),
        "origin": "estimated",
        "note": (
            "费率是 Demo 预设，不是 Amazon 公布费率；金额未与客户月度仓储费总额对账"
            "（客户源表粒度是负责人×月，无 ASIN）"
        ),
    }


# --------------------------------------------------------------------------- #
# 风险评价
# --------------------------------------------------------------------------- #
def _severity(ratio: float, risk_type: str, rules: RuleSet) -> str:
    medium, high = rules.severity_cuts.get(risk_type, [1.5, 2.5])
    if ratio >= high:
        return "high"
    if ratio >= medium:
        return "medium"
    return "low"


def build_risks(
    facts: dict[str, Any],
    demand: dict[str, Any],
    inventory: dict[str, Any],
    projection: dict[str, Any],
    aging: dict[str, Any],
    fee: dict[str, Any],
    rules: RuleSet,
) -> list[dict[str, Any]]:
    risks: list[dict[str, Any]] = []
    if not inventory.get("available"):
        return risks

    # 库存不足与超量备货都以需求为输入，没有预测就给不出来。
    # 可用性、库龄、仓储费不依赖需求，必须照常判断 —— 否则一个没有预测的对象
    # 会显示成「无明显风险」，而它可能正压着一堆超龄库存。
    if projection.get("available"):
        confirmed = projection["scopes"]["sellable_plus_confirmed"]
        sellable_scope = projection["scopes"]["sellable_only"]
        safety_days = projection["safety_days"]

        # 库存不足：按逐日投影判，不按覆盖天数比值判。
        #
        # 覆盖天数 =（可售 + 窗口内已确认到货）÷ 预估日均，分子里的到货没有时间概念 ——
        # 一批 2026-09-12 才到的货会被当成今天就在手上。v0.2.2 时「已确认到货」只是
        # 那点待调仓/入库中，影响不大；v0.3.0 接入子体级计划货件后分子被抬高，覆盖天数
        # 中位数变成 118 天，几乎没有对象低于 14/60 天的安全线，这条判据只命中 5 个，
        # 等于失效。
        #
        # 投影尊重时间：走一遍逐日余额，看它到底哪天见底、哪天破安全线。改成这个判据后
        # 命中 171 个，与数据包自己判定需要补货的 168 个基本一致。
        # 覆盖天数保留为展示指标，不再作为判据。
        cover = confirmed["cover_days"]
        breach = confirmed["stockout_date"] or confirmed["safety_breach_date"]
        if breach:
            # 严重度按「多快出事」：越早见底越严重
            days_to = max((date.fromisoformat(breach) - AS_OF).days, 1)
            ratio = max(1.0, (max(safety_days, 7) * 2.0) / days_to)
            reasons = []
            if inventory["availability_rate"] is not None and inventory["availability_rate"] < 0.9:
                reasons.append("可售占比偏低，部分库存被预留/待调仓/入库中占用")
            if demand.get("vs_recent_actual") and demand["vs_recent_actual"] > 1.1:
                reasons.append(
                    f"预估日均 {demand['forecast_daily']} 件高于近 7 天实际 "
                    f"{demand['recent_actual_daily']} 件，需求上行"
                )
            if inventory["inbound_qty"] > 0:
                reasons.append(f"有 {inventory['inbound_qty']} 件在途但到货日期未分摊到子体，未计入余额")
            if not reasons:
                reasons.append("库存总量相对当前销速不足")
            risks.append(
                {
                    "risk_type": RISK_SHORTAGE,
                    "label": RISK_LABELS[RISK_SHORTAGE],
                    "severity": _severity(ratio, RISK_SHORTAGE, rules),
                    "risk_score": round(min(ratio, 5.0) * 20, 1),
                    "headline": (
                        f"预计 {confirmed['stockout_date']} 库存见底"
                        if confirmed["stockout_date"]
                        else f"预计 {confirmed['safety_breach_date']} 跌破安全库存 {safety_days} 天"
                    ),
                    "affected_qty": int(confirmed["shortage_30d"]),
                    "reasons": reasons,
                    "evidence": {
                        "cover_days_confirmed": cover,
                        "cover_days_sellable": sellable_scope["cover_days"],
                        "safety_days": safety_days,
                        "safety_days_origin": projection["safety_days_origin"],
                        "stockout_date": confirmed["stockout_date"],
                        "shortage_30d": confirmed["shortage_30d"],
                    },
                }
            )

        # 超量备货：总已知库存超过合理上限
        if projection["excess_qty"] and projection["excess_qty"] > 0:
            ratio = inventory["total_known_qty"] / max(projection["reasonable_max_qty"], 1.0)
            risks.append(
                {
                    "risk_type": RISK_OVERSTOCK,
                    "label": RISK_LABELS[RISK_OVERSTOCK],
                    "severity": _severity(ratio, RISK_OVERSTOCK, rules),
                    "risk_score": round(min(ratio, 5.0) * 18, 1),
                    "headline": (
                        f"已知库存 {inventory['total_known_qty']} 件，"
                        f"超过 {rules.max_cover_days} 天合理上限 {projection['excess_qty']} 件"
                    ),
                    "affected_qty": int(projection["excess_qty"]),
                    "reasons": [
                        (
                            f"预计消化需 {projection['depletion_days']} 天"
                            if projection["depletion_days"] is not None
                            else projection["depletion_unavailable_reason"]
                        ),
                        "国内仓/海外仓集中" if inventory["total_known_qty"] > inventory["fba_total_qty"] * 1.5 else "库存集中在 FBA",
                    ],
                    "evidence": {
                        "total_known_qty": inventory["total_known_qty"],
                        "reasonable_max_qty": projection["reasonable_max_qty"],
                        "depletion_days": projection["depletion_days"],
                        "max_cover_days": rules.max_cover_days,
                    },
                }
            )


    # 库存可用性异常
    rate = inventory["availability_rate"]
    if rate is not None and rate < rules.availability_min_rate:
        ratio = rules.availability_min_rate / max(rate, 0.01)
        top_state = max(
            [s for s in inventory["states"] if not s["immediate"] and s["state"] in {"预留", "待调仓", "入库中"}],
            key=lambda s: s["qty"],
            default=None,
        )
        risks.append(
            {
                "risk_type": RISK_AVAILABILITY,
                "label": RISK_LABELS[RISK_AVAILABILITY],
                "severity": _severity(ratio, RISK_AVAILABILITY, rules),
                "risk_score": round(min(ratio, 5.0) * 16, 1),
                "headline": f"FBA 可用率 {rate:.0%}，低于阈值 {rules.availability_min_rate:.0%}",
                "affected_qty": inventory["restricted_qty"],
                "reasons": [
                    f"主要受限状态：{top_state['state']} {top_state['qty']} 件" if top_state else "受限库存分布分散",
                ],
                "evidence": {
                    "availability_rate": rate,
                    "sellable_qty": inventory["sellable_qty"],
                    "fba_total_qty": inventory["fba_total_qty"],
                    "restricted_qty": inventory["restricted_qty"],
                    "threshold": rules.availability_min_rate,
                },
            }
        )

    # 库龄风险
    share = aging["aged_181_share"]
    if share is not None and share > rules.aged_share_max:
        ratio = share / max(rules.aged_share_max, 0.01)
        reasons = [f"181 天以上 {aging['aged_181_qty']} 件，占 {share:.0%}"]
        if aging["crossing_180_within_7d"]:
            reasons.append(f"未来 7 天内还有 {aging['crossing_180_within_7d']} 件跨过 180 天")
        risks.append(
            {
                "risk_type": RISK_AGING,
                "label": RISK_LABELS[RISK_AGING],
                "severity": _severity(ratio, RISK_AGING, rules),
                "risk_score": round(min(ratio, 5.0) * 15, 1),
                "headline": f"181 天以上库存占比 {share:.0%}，高于阈值 {rules.aged_share_max:.0%}",
                "affected_qty": aging["aged_181_qty"],
                "reasons": reasons,
                "evidence": {
                    "aged_181_qty": aging["aged_181_qty"],
                    "aged_181_share": share,
                    "crossing_3d": aging["crossing_180_within_3d"],
                    "crossing_7d": aging["crossing_180_within_7d"],
                    "threshold": rules.aged_share_max,
                    "assumption": aging["assumption"],
                },
            }
        )

    # 仓储费风险
    if fee.get("available"):
        hits = []
        ratio_parts = []
        if fee["sales_ratio"] is not None and fee["sales_ratio"] > rules.fee_sales_ratio_max:
            hits.append(f"占销售额 {fee['sales_ratio']:.1%}")
            ratio_parts.append(fee["sales_ratio"] / rules.fee_sales_ratio_max)
        if fee["gross_ratio"] is not None and fee["gross_ratio"] > rules.fee_gross_ratio_max:
            hits.append(f"占毛利 {fee['gross_ratio']:.1%}")
            ratio_parts.append(fee["gross_ratio"] / rules.fee_gross_ratio_max)
        if hits:
            ratio = max(ratio_parts)
            risks.append(
                {
                    "risk_type": RISK_FEE,
                    "label": RISK_LABELS[RISK_FEE],
                    "severity": _severity(ratio, RISK_FEE, rules),
                    "risk_score": round(min(ratio, 5.0) * 12, 1),
                    "headline": f"估算仓储费 {fee['total_fee']:.0f}（{'、'.join(hits)}）",
                    "affected_qty": aging["total_qty"],
                    "reasons": [
                        f"超龄附加费 {fee['aged_surcharge']:.0f}，占总费用 "
                        f"{(fee['aged_surcharge'] / fee['total_fee']):.0%}" if fee["total_fee"] else "费用构成不可拆",
                        "金额为估算值，费率是 Demo 预设",
                    ],
                    "evidence": {
                        "total_fee": fee["total_fee"],
                        "regular_fee": fee["regular_fee"],
                        "aged_surcharge": fee["aged_surcharge"],
                        "sales_ratio": fee["sales_ratio"],
                        "gross_ratio": fee["gross_ratio"],
                        "origin": "estimated",
                    },
                }
            )

    risks.sort(key=lambda r: -r["risk_score"])
    return risks


def build_capacity(
    demand: dict[str, Any], projection: dict[str, Any], risks: list[dict[str, Any]]
) -> dict[str, Any]:
    if not projection.get("available"):
        return {"level": "unavailable", "reason": "无库存快照，无法判断承接能力"}
    confirmed = projection["scopes"]["sellable_plus_confirmed"]
    cover = confirmed["cover_days"]
    safety = projection["safety_days"]
    has_shortage = any(r["risk_type"] == RISK_SHORTAGE for r in risks)
    if cover is None:
        level, note = "unknown", "预测日均为 0，无法给出承接结论"
    elif has_shortage:
        level, note = "cannot_absorb", f"覆盖 {cover} 天已低于安全线 {safety} 天，不宜再加新增流量"
    elif cover < safety * 2:
        level, note = "limited", f"覆盖 {cover} 天，安全线 {safety} 天，只能承接有限新增"
    else:
        level, note = "can_absorb", f"覆盖 {cover} 天，高于安全线 {safety} 天两倍以上"
    extra = None
    if cover is not None and demand["forecast_daily"] > 0 and level == "can_absorb":
        spare_days = cover - safety * 2
        extra = round(spare_days * demand["forecast_daily"] / 30, 1)
    return {"level": level, "note": note, "extra_daily_units_30d": extra}


# --------------------------------------------------------------------------- #
# 逐日柱状图的数据装配
# --------------------------------------------------------------------------- #
# 折线类指标的显示定义。标签与单位都在这里定死，页面不做映射。
LINE_METRICS = [
    {"key": "price", "label": "售价", "unit": "$", "decimals": 2},
    {"key": "list_price", "label": "标价", "unit": "$", "decimals": 2},
    {"key": "net_sales", "label": "销售额", "unit": "$", "decimals": 2},
    {"key": "ad_spend", "label": "广告花费", "unit": "$", "decimals": 2},
    {"key": "ad_sales", "label": "广告销售额", "unit": "$", "decimals": 2},
    {"key": "sessions", "label": "访问量", "unit": "", "decimals": 0},
    {"key": "conversion_rate", "label": "转化率", "unit": "%", "decimals": 4},
    {"key": "acos", "label": "ACoS", "unit": "%", "decimals": 4},
]

# 泳道标签与固定高度。派生缓存已带 type_label/lane，这里只是给 lanes 列表用。
_LANE_LABEL = {"BD": "BD 活动", "LD": "Limited Deal", "Coupon": "Coupon", "PriceDiscount": "价格调整"}
_LANE_OF = {"BD": 5, "LD": 5, "Coupon": 4, "PriceDiscount": 2}


def _band(actual: list, dates: list[str], i: int, j: int) -> dict[str, Any]:
    return {
        "from_index": i,
        "to_index": j,
        "from": dates[i],
        "to": dates[j],
        "days": j - i + 1,
        "units_in_span": sum((actual[k]["value"] or 0) for k in range(i, j + 1) if actual[k]),
    }


def build_chart(asin: str, demand: dict[str, Any]) -> dict[str, Any]:
    """Assemble the day-by-day chart. Read and align only, no judgment.

    Layer taxonomy (06-界面优化点登记.md R2.1):
      量           柱        逐日销量（实际 / 预测）
      柱不可信     改柱样式  缺货日、需求被扭曲的日子（不进泳道）
      缺货区间     背景色带  柱高为 0 时柱子样式什么都表达不了
      有起止的状态 横条泳道  BD / Coupon / 价格调整，各占固定整数高度
      连续指标     折线      价格 / 金额 / 流量 / 转化 / 广告
    """
    history = forecast.history_daily(asin)
    events = forecast.events(asin)
    rows = forecast.forecast_daily(asin)

    if not history and not rows:
        return {
            "available": False,
            "reason": "该子 ASIN 既没有逐日销量历史，也没有预测结果",
            "detail": "逐日数据以子 ASIN 为维度构建，尚未覆盖此对象",
        }

    hist_by_date = {r["date"]: r for r in history}
    fc_by_date = {r["forecast_date"]: r for r in rows}
    dates = sorted(set(hist_by_date) | set(fc_by_date))
    index_of = {d: i for i, d in enumerate(dates)}
    as_of_iso = AS_OF.isoformat()

    # --- 柱：实际 ---------------------------------------------------------- #
    # data 用对象而不是裸数字，tooltip 直接读，不回查第二份结构。
    actual = []
    for d in dates:
        r = hist_by_date.get(d)
        if r is None:
            actual.append(None)
            continue
        stockout = bool(r["stockout_flag"])
        # 需求被扭曲：包里 demand_quality_flag 已给中文标签，页面不做映射。
        distorted = r["quality_label"] if r["demand_quality_flag"] != "normal" else None
        actual.append(
            {
                "value": r["units_sold"],
                "date": d,
                "weekday": _weekday_cn(d),
                "is_stockout": stockout,
                "is_anomaly": bool(distorted) and not stockout,
                "quality_label": distorted,
                "adjustment_reason": r.get("adjustment_reason"),
                # 缺货日的销量不是需求。数据语义直接变成视觉编码。
                "trust_note": (
                    "当天缺货，这个销量不代表需求" if stockout
                    else (f"当天{distorted}，基线已按口径还原" if distorted else None)
                ),
                "potential_demand": r.get("potential_demand_units"),
                "lost_sales": r.get("lost_sales_units"),
                "price": r.get("selling_price"),
                "list_price": r.get("list_price"),
                "net_sales": r.get("net_sales"),
                "ad_spend": r.get("ad_spend"),
                "ad_sales": r.get("ad_sales"),
                "acos": r.get("acos"),
                "sessions": r.get("sessions"),
                "conversion_rate": r.get("cvr"),
            }
        )

    # --- 柱：预测 + 区间 ---------------------------------------------------- #
    fc = []
    for d in dates:
        r = fc_by_date.get(d)
        if r is None:
            fc.append(None)
            continue
        fc.append(
            {
                "value": round(float(r["p50_units"] or 0), 2),
                "lower": round(float(r["p10_units"] or 0), 2),
                "upper": round(float(r["p90_units"] or 0), 2),
                "date": d,
                "weekday": _weekday_cn(d),
                "already_elapsed": d <= as_of_iso,
                # 因子分解：点开某一天可以看出这个数是怎么拆出来的。
                # **不写 `or 0`** —— Agent 那条路现在不给基线，空值套成 0 会让
                # 日详情写出「基线 0.0 件」并紧挨着「17 件」，那是错数不是缺数。
                # 留 None，daychart 的 `baseline != null` 守卫才拦得住整行不显示。
                "baseline": (
                    round(float(r["baseline_units"]), 2)
                    if r["baseline_units"] is not None else None
                ),
                "weekday_factor": r.get("weekday_factor"),
                "seasonality_factor": r.get("seasonality_factor"),
                "lifecycle_factor": r.get("lifecycle_factor"),
                "ad_ratio": r.get("advertising_effect_ratio"),
                "price_ratio": r.get("price_effect_ratio"),
                "promotion_ratio": r.get("promotion_effect_ratio"),
            }
        )

    # --- 缺货区间：连续段单独给出来 ---------------------------------------- #
    # 缺货日销量通常是 0，高度为 0 的柱子画不出任何东西 —— 那一段会成为空白，
    # 读起来像「没有数据」，比读成需求下降更糟。
    stockout_bands = []
    run_start = None
    for i, a in enumerate(actual):
        flag = bool(a and a["is_stockout"])
        if flag and run_start is None:
            run_start = i
        elif not flag and run_start is not None:
            stockout_bands.append(_band(actual, dates, run_start, i - 1))
            run_start = None
    if run_start is not None:
        stockout_bands.append(_band(actual, dates, run_start, len(actual) - 1))

    # --- 状态区间与点事件 -------------------------------------------------- #
    bands, points = [], []
    for e in events:
        if e["date_from"] not in index_of and e["date_to"] not in index_of:
            continue
        fi = index_of.get(e["date_from"], 0)
        ti = index_of.get(e["date_to"], len(dates) - 1)
        item = {
            "event_type": e["event_type"],
            "type_label": e["type_label"],
            "label": e["label"],
            "lane": e["lane"],
            "from": e["date_from"],
            "to": e["date_to"],
            "from_index": fi,
            "to_index": ti,
            "days": e["days"],
            "horizon": e["horizon"],
            "is_future": e["horizon"] == "future",
        }
        (points if e["days"] <= 1 else bands).append(item)

    present = sorted({b["event_type"] for b in bands} | {q["event_type"] for q in points},
                     key=lambda t: -_LANE_OF.get(t, 0))
    lanes = [
        {"event_type": t, "label": _LANE_LABEL.get(t, t), "lane": _LANE_OF.get(t, 0)}
        for t in present
    ]

    # --- 折线指标：只保留真的有值的 ---------------------------------------- #
    lines = []
    for m in LINE_METRICS:
        vals = [(a[m["key"]] if a else None) for a in actual]
        if not any(v is not None for v in vals):
            continue
        distinct = {round(float(v), 6) for v in vals if v is not None}
        lines.append(
            {
                **m,
                "values": [round(float(v), m["decimals"]) if v is not None else None for v in vals],
                "is_constant": len(distinct) <= 1,
            }
        )

    return {
        "available": True,
        "dates": dates,
        "weekdays": [_weekday_cn(d) for d in dates],
        "as_of": as_of_iso,
        "as_of_index": index_of.get(as_of_iso),
        "forecast_start": rows[0]["forecast_date"] if rows else None,
        "forecast_start_index": index_of.get(rows[0]["forecast_date"]) if rows else None,
        "actual": actual,
        "forecast": fc,
        "has_forecast": bool(rows),
        "no_forecast_note": None if rows else "该对象尚无预测结果，图上只有已发生的部分",
        "bands": bands,
        "points": points,
        "lanes": lanes,
        "lane_axis_max": forecast.EVENT_LANE_MAX,
        "dropped_bands": [],
        "stockout_bands": stockout_bands,
        "lines": lines,
        "history_days": len(history),
        "history_first": history[0]["date"] if history else None,
        "history_last": history[-1]["date"] if history else None,
        "stockout_days": sum(1 for a in actual if a and a["is_stockout"]),
        "anomaly_days": sum(1 for a in actual if a and a["is_anomaly"]),
        "timezone_label": "美国时间",
        "default_on": ["actual", "forecast", "band", "stockout"] + [l["event_type"] for l in lanes],
        "hint": "悬停看当天数据，点击看当天为什么是这个数",
    }


# --------------------------------------------------------------------------- #
# 组装
# --------------------------------------------------------------------------- #
def parse_pack_manifest(colorway: str | None, pack_size: int | None) -> dict[str, Any]:
    """The customer's 配色 column is a pack manifest, not a single colour.

    Three delimiter conventions appear in the source, all meaning 色号#颜色 × 件数:
      A  ``156#豆沙红X灰色腰带-1,110#烟灰蓝X灰色腰带-1``   entries by ``,``  qty after ``-``
      B  ``073#黑色*1+114#深灰蓝*1``                        entries by ``+``  qty after ``*``
      C  ``7G:200#黑色``                                    combination prefix, no qty
    Reported quantities sum to the pack size for 323 of 342 children; the rest are
    surfaced as a mismatch rather than being forced to balance.
    """
    raw = (colorway or "").strip()
    if not raw:
        return {"items": [], "total_units": None, "matches_pack_size": None, "raw": None}
    body = raw.split(":", 1)[1] if re.match(r"^\w{1,4}:", raw) else raw
    items: list[dict[str, Any]] = []
    for seg in (s.strip() for s in re.split(r"[,，+]", body)):
        if not seg:
            continue
        qty_match = re.search(r"[-*](\d+)\s*$", seg)
        qty = int(qty_match.group(1)) if qty_match else None
        label = (seg[: qty_match.start()] if qty_match else seg).strip()
        code_match = re.match(r"^(\d{2,4})#\s*(.*)$", label)
        code = code_match.group(1) if code_match else None
        name = (code_match.group(2) if code_match else label).strip()
        body_colour, _, waistband = name.partition("X")
        items.append(
            {
                "color_code": code,
                "color_name": name,
                "body_color": body_colour.strip() or None,
                "waistband_color": waistband.strip() or None,
                "quantity": qty,
                "quantity_stated": qty is not None,
            }
        )
    total = sum(i["quantity"] or 0 for i in items) or None
    stated_all = all(i["quantity_stated"] for i in items)
    return {
        "items": items,
        "total_units": total if stated_all else None,
        "matches_pack_size": (total == pack_size) if (stated_all and pack_size) else None,
        "raw": raw,
    }


def assess(asin: str, rules: RuleSet) -> dict[str, Any] | None:
    facts = data.child_facts(asin)
    if not facts:
        return None

    demand = build_demand(asin, facts, rules)
    inventory = build_inventory(facts)
    projection = build_projection(facts, demand, inventory, rules)
    aging = build_aging(facts)
    fee = build_fee(facts, aging, rules)
    risks = build_risks(facts, demand, inventory, projection, aging, fee, rules)
    capacity = build_capacity(demand, projection, risks)
    chart = build_chart(asin, demand)

    unavailable = []
    if not inventory.get("available"):
        unavailable.append({"item": "库存盘点", "reason": inventory.get("reason")})
    if not fee.get("available"):
        unavailable.append({"item": "仓储费", "reason": fee.get("reason")})
    if projection.get("available") and projection["scopes"]["sellable_only"]["cover_days"] is None:
        unavailable.append({"item": "覆盖天数", "reason": "预测日均为 0"})
    if fee.get("available") and fee.get("gross_ratio") is None:
        unavailable.append({"item": "费毛利比", "reason": fee.get("gross_ratio_unavailable_reason")})
    if (facts.get("econ") or {}).get("unit_cost") is None:
        unavailable.append({"item": "库存货值", "reason": "缺单位成本"})

    states = []
    if not demand.get("available"):
        states.append({"state": "尚无预测", "detail": demand.get("detail") or demand.get("reason")})
    elif demand["confidence"] == "low":
        states.append(
            {"state": "预测置信度低", "detail": demand.get("confidence_reason")}
        )
    # 新鲜度不作状态：数据包是一次全盘运行的静态快照，每个对象的运行日相同，
    # 「预估更新于 X 天前」对 342 个对象是同一个常量，放上去只是噪音。
    # 真实 Agent 按对象各自节奏跑起来之后再恢复（契约见 07，运行模型未变）。
    # 原来这里有「在途 ETA 未分摊」，v0.3.0 起计划货件带子 ASIN 级 ETA，不再成立。
    # 换成「有计划中货件未计入」之后实测 341/341 命中 —— 每个子体都恰好有一笔
    # sea/planned/medium 的计划货件，恒定值作为状态没有信息量。
    # 件数改在「在途与到货」板块里作为数字显示（projection.planned_arrival_qty）。
    if (
        inventory.get("available")
        and inventory["sellable_qty"] == 0
        and inventory["total_known_qty"] > 0
    ):
        states.append(
            {
                "state": "有货但不可售",
                "detail": f"可售 0 件，已知库存仍有 {inventory['total_known_qty']} 件",
            }
        )
    if not fee.get("available"):
        states.append({"state": "仓储费不可计算", "detail": fee.get("reason")})
    if unavailable:
        states.append(
            {
                "state": "存在不可计算输出",
                "detail": "、".join(u["item"] for u in unavailable),
            }
        )
    if (facts.get("attr") or {}).get("quality_status") != "complete":
        states.append({"state": "产品属性缺失", "detail": str((facts.get("attr") or {}).get("quality_flags"))})
    if not risks:
        states.append({"state": "无明显风险", "detail": "五类风险在当前阈值下均未命中"})

    return {
        "child_asin": asin,
        "identity": {
            "child_asin": asin,
            "parent_asin": (facts.get("child") or {}).get("parent_asin"),
            "product_name": (facts.get("child") or {}).get("product_name"),
            "style_no": (facts.get("attr") or {}).get("style_no"),
            "combination": (facts.get("attr") or {}).get("combination"),
            "colorway": (facts.get("attr") or {}).get("colorway"),
            "pack_manifest": parse_pack_manifest(
                (facts.get("attr") or {}).get("colorway"),
                (facts.get("econ") or {}).get("pack_size"),
            ),
            "size": (facts.get("attr") or {}).get("size"),
            "operator": (facts.get("attr") or {}).get("operator"),
            "goods_status": (facts.get("attr") or {}).get("goods_status"),
            "product_lifecycle": (facts.get("attr") or {}).get("product_lifecycle"),
            "category": (facts.get("attr") or {}).get("category"),
            "sku": (facts.get("ident") or {}).get("sku"),
            "fnsku": (facts.get("ident") or {}).get("fnsku"),
            "store": (facts.get("ident") or {}).get("store"),
            "category_rank": (facts.get("child") or {}).get("category_rank"),
            "rating": (facts.get("child") or {}).get("rating"),
            "attribute_quality": (facts.get("attr") or {}).get("quality_status"),
        },
        "customer_plan": facts.get("plan") or {},
        "economics": facts.get("econ") or {},
        "monthly": {
            **(facts.get("month") or {}),
            **forecast.month_actuals(asin, MONTH_PERIOD),
        },
        # 侧栏那列 30 天销量、经营框、图上的柱子必须同源，否则同屏两个数对不上。
        # 客户自己的 fact_sales_window 与他自己的父体逐日互相矛盾（子体级中位差 20%），
        # 数据包把分配锚在父体上（父体级精确对齐），所以页面统一读逐日。
        "windows": forecast.windows(asin) or {
            "units_30d": None, "daily_avg_30d": None, "origin": "unavailable",
        },
        "demand": demand,
        "chart": chart,
        "inventory": inventory,
        "projection": projection,
        "aging": aging,
        "fee": fee,
        "risks": risks,
        "capacity": capacity,
        "unavailable_outputs": unavailable,
        "states": states,
        "style_events": facts.get("style_events") or [],
        "rule_version": rules.version_label(),
        "as_of_date": AS_OF.isoformat(),
    }


def summarize(assessment: dict[str, Any]) -> dict[str, Any]:
    """Compact row for the list pages."""
    inv = assessment["inventory"]
    proj = assessment["projection"]
    confirmed = proj["scopes"]["sellable_plus_confirmed"] if proj.get("available") else {}
    primary = assessment["risks"][0] if assessment["risks"] else None
    return {
        "child_asin": assessment["child_asin"],
        "parent_asin": assessment["identity"]["parent_asin"],
        "style_no": assessment["identity"]["style_no"],
        "combination": assessment["identity"]["combination"],
        "size": assessment["identity"]["size"],
        "operator": assessment["identity"]["operator"],
        "goods_status": assessment["identity"]["goods_status"],
        "product_lifecycle": assessment["identity"]["product_lifecycle"],
        "store": assessment["identity"]["store"],
        "sellable_qty": inv.get("sellable_qty"),
        "fba_total_qty": inv.get("fba_total_qty"),
        "total_known_qty": inv.get("total_known_qty"),
        "availability_rate": inv.get("availability_rate"),
        "units_30d": assessment["windows"]["units_30d"],
        "daily_avg_30d": assessment["windows"]["daily_avg_30d"],
        "forecast_daily": assessment["demand"].get("forecast_daily"),
        "forecast_available": assessment["demand"].get("available", False),
        "forecast_run_date": (assessment["demand"].get("run") or {}).get("run_date"),
        "forecast_model": (assessment["demand"].get("run") or {}).get("model_label"),
        "forecast_wape": (assessment["demand"].get("run") or {}).get("model_wape"),
        "cover_days": confirmed.get("cover_days"),
        "stockout_date": confirmed.get("stockout_date"),
        "excess_qty": proj.get("excess_qty"),
        "aged_181_qty": assessment["aging"]["aged_181_qty"],
        "aged_181_share": assessment["aging"]["aged_181_share"],
        "crossing_7d": assessment["aging"]["crossing_180_within_7d"],
        "fee_total": assessment["fee"].get("total_fee"),
        "risk_count": len(assessment["risks"]),
        "risk_types": [r["risk_type"] for r in assessment["risks"]],
        "risk_qty": {r["risk_type"]: int(r["affected_qty"] or 0) for r in assessment["risks"]},
        "primary_risk": primary["risk_type"] if primary else None,
        "primary_severity": primary["severity"] if primary else None,
        "primary_headline": primary["headline"] if primary else None,
        "risk_score": primary["risk_score"] if primary else 0,
        "capacity_level": assessment["capacity"]["level"],
        "confidence": assessment["demand"].get("confidence"),
    }
