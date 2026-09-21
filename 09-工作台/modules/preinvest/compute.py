"""面料预投模块 · 确定性计算层。

这里只放**算术**，一个判断都不做。分界照契约 §0 那把尺子：
真实业务里 Agent 跑之前这条数据存在吗 —— 存在的是输入，要判出来的归 Agent。

所以下面有的是：聚合、单位换算、比值、达标判定、与现行口径的差额。
没有的是：这个组下月市场会怎么走、活动能推高多少、尺码该怎么拆。
那三件由预投判断 Agent 出，本文件只负责把它的产出接进来算下游（见 agent_result.py）。
"""

from __future__ import annotations

import datetime as dt
from collections import Counter
from typing import Any

from . import data, rules


# 一条复核判据命中超过这个比例，就说明它没有区分性 —— 从逐行标记撤掉，
# 升级成页面级提示。不设这道自检，判据会悄悄退化成「整张表都标红」。
REASON_CAP = 0.70


def _f(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# 现行 Excel 口径复刻 —— 对拍基线，必须可复现
# ---------------------------------------------------------------------------

def suggest_units(forecast_p50: float | None, rs: rules.RuleSet) -> int | None:
    """预投建议量 = 目标销售月预估销量 × (1 + 安全余量)。

    **不再复刻运营那套「3/7/15/30 天加权平均」。** 用户 2026-09-04：
      「他们现在的这个预估方式是比较草率的……既然用上 AI 了，就不需要这么草率的
        拉个公式了……我们直接用我们的预估销量模型做就行了呀。」
    所以这里只做一件事：把已有的逐子体预估按销售月聚合后，加一层安全余量。

    余量来自吴组长举例「预计卖 100 盒，我可能就会投到 110 盒」= 10%，可调。
    """
    if forecast_p50 is None:
        return None
    return int(round(float(forecast_p50) * (1 + rs.safety_margin_rate)))


# ---------------------------------------------------------------------------
# 单位换算：盒 → 条 → 吨 → 钱
# ---------------------------------------------------------------------------

def to_fabric(boxes: float, pack_size: int | None, rs: rules.RuleSet,
              unit_cost: float | None = None) -> dict[str, Any]:
    """一个盒数折成条数、吨数与资金占用。

    吨数由客户口述锚点「30 万盒≈200 吨」反推，是 customer_derived。
    **金额是估算**：锚点只给了盒与吨，没给面料单价；unit_cost 是成品成本
    不是面料成本，所以要乘一个「面料占成品成本比例」，而那个比例客户没给。
    因此 money 一栏必须带 estimated=True，页面标「待确认」。
    """
    boxes = _f(boxes)
    tiao = boxes * pack_size if pack_size else None
    tons = boxes * rs.fabric_g_per_box / 1e6
    money = None
    if unit_cost:
        money = boxes * _f(unit_cost) * rs.fabric_cost_share
    return {
        "boxes": int(round(boxes)),
        "tiao": int(round(tiao)) if tiao is not None else None,
        "tons": round(tons, 3),
        "money": round(money, 2) if money is not None else None,
        "money_estimated": True,
    }


# ---------------------------------------------------------------------------
# 考核：历史轮次的达成率与闲置
# ---------------------------------------------------------------------------

def plan(rs: rules.RuleSet, judgments: dict[str, dict] | None = None) -> dict[str, Any]:
    """本轮预投表 —— **一行一个子 ASIN**，342 行全给，不分堆不筛选。

    用户 2026-09-04：「你这个不要做筛选，你就把所有的都给列出来就行，
    因为它这个相当于是一个批量的审批的一个东西。」

    **后端不乘 buffer。** 只给 Agent 估出来的销量，buffer 由运营在页面上填：
      「你不需要有一个你自己算的 buffer，你就直接有一个 Agent 估的销量就行了，
        然后你把 buffer 给到运营。」
    所以这里返回 forecast_p50，建议预投由前端按运营填的 buffer 现算。
    """
    win = data.target_window(rs.lead_days_total, rs.target_month_offset)
    kids = data.children()
    fc = data.forecast_by_child(win["from"], win["to"])
    cycles = {c["group_id"]: c for c in data.cycles()}
    SRC = {"agent": "AI 判断", "snapshot": "预估快照"}

    rows: list[dict] = []
    for k in kids:
        ch = k["child_asin"]
        f = fc.get(ch) or {}
        p50 = f.get("p50")
        cyc = cycles.get(k["group_id"])
        rows.append({
            "child_asin": ch,
            "parent_asin": k["parent_asin"],
            "product_name": k["product_name"],
            "style_no": k["style_no"], "combination": k["combination"],
            "colorway": k["colorway"], "size": k["size"],
            "category": k["category"], "operator": k["operator"],
            "goods_status": k["goods_status"],
            "lifecycle": k["product_lifecycle"],
            "category_rank": k["category_rank"], "rating": k["rating"],
            "pack_size": k["pack_size"], "unit_cost": k["unit_cost"],
            "group_id": k["group_id"],
            "forecast_p50": p50, "forecast_p10": f.get("p10"),
            "forecast_p90": f.get("p90"),
            "forecast_source": f.get("forecast_source") or "缺失",
            "forecast_source_label": SRC.get(f.get("forecast_source"), "缺失"),
            # 上一轮达成率是配色组级的（考核口径如此），这里作为参考带上
            "group_last_achieve": cyc["achieve_rate"] if cyc else None,
        })

    total_p50 = sum(r["forecast_p50"] or 0 for r in rows)
    n_agent = sum(1 for r in rows if r["forecast_source"] == "agent")
    return {
        "window": win,
        "target_sales_month": win["month"],
        "child_count": len(rows),
        "forecast_p50_total": total_p50,
        "agent_judged_children": n_agent,
        "rows": rows,
        "achieve_rate_min": rs.achieve_rate_min,
        "fabric_g_per_box": rs.fabric_g_per_box,
        # buffer 的建议起点（客户举例 100→110），但由运营决定，后端不乘
        "buffer_hint": rs.safety_margin_rate,
    }

def chain_dates(rs: rules.RuleSet) -> list[dict]:
    """时间链条各环节的起止日期。

    甘特图要的是每段的 from/to，所以**最早与最晚两条游标分别累计**：
    生产 10~25 天、物流 15~20 天，两段的不确定性会叠起来，
    只推一条游标的话画出来的是「全部取最长」那一种极端，不是区间。

    起点是基准日（这一轮预投必须在此定下），逐段用客户口述的天数
    （dim_preinvest_leadtime，每条带逐字稿时间戳）。
    """
    as_of = dt.date.fromisoformat(data.manifest().get("as_of") or "2026-08-03")
    out: list[dict] = [{
        "stage": "preinvest", "stage_label": "预投",
        "from": as_of.isoformat(), "to": as_of.isoformat(),
        "days_min": 0, "days_max": 0, "is_milestone": True,
        "note": "本轮预投必须在此定下",
    }]
    lo = hi = as_of
    for st in data.leadtime():
        f_lo, f_hi = lo, hi
        lo = lo + dt.timedelta(days=st["days_min"])
        hi = hi + dt.timedelta(days=st["days_max"])
        out.append({
            "stage": st["stage"], "stage_label": st["stage_label"],
            # from = 这段最早开始，to = 这段最晚结束
            "from": f_lo.isoformat(), "to": hi.isoformat(),
            "ends_earliest": lo.isoformat(), "ends_latest": hi.isoformat(),
            "days_min": st["days_min"], "days_max": st["days_max"],
            # 里程碑的判据是「起止同一天」，不是「天数为 0」。
            # 开卖那段 days_max 是 0 但起止差 20 天（最早 09-27、最晚 10-17），
            # 当成里程碑会画成一条 20 天长的黑条，那是在说一件不成立的事。
            "is_milestone": f_lo == hi,
            "note": st["note"],
        })
    out.append({
        "stage": "onsale", "stage_label": "开卖",
        "from": lo.isoformat(), "to": hi.isoformat(),
        "days_min": 0, "days_max": 0, "is_milestone": lo == hi,
        "note": f"最早 {lo.isoformat()}、最晚 {hi.isoformat()} 上架，"
                f"落在 {data.TARGET_MONTH} 销售月",
    })
    return out
