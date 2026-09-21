"""面料预投模块 · 只读取数层。

两个库：本模块的 preinvest_demo.sqlite（预投轮次、配色组、逐月历史、尺码占比）
和产品包（未来 90 天预测、逐日销量、未来活动计划）。产品包用 ATTACH 读，
**不在自己包里重建产品维度**（契约 §6.3 / G7）。

取连接一律走 core.db.pool（契约 §6.1b）—— 自己 lru_cache 单连接会在页面并行
请求时偶发 `database disk image is malformed`。
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from typing import Any

from core import db, paths

DB_PATH = paths.PREINVEST_DB

# 预投目标销售月：基准日 2026-08-03 + 约两个半月（逐字稿 00:56:51）
TARGET_MONTH = "2026-10"
TARGET_FROM, TARGET_TO = "2026-10-01", "2026-10-31"
ORDER_MONTH = "2026-09"


def target_window(lead_days: int = 75, months_ahead: int = 2) -> dict[str, Any]:
    """预投对应哪个销售月。

    **规则是 M+2**（用户 2026-09-04 拍定）：8 月做的预投对应 10 月的销量。
    依据是源表 —— `3.库存表` 的逐月预投列与月报的预投下单表**全都是 M+2**。

    为什么不是 M+3：吴组长口述前置期约 75 天，75 + 一个销售月 30 天 = 105 天，
    而需求预估只有 90 天。按 M+3 推（到货月的下一个整月）会落到 11 月，
    实测预估只覆盖 1/30 天，数字不可用。M+2 落在 10 月，覆盖 31/31 天。
    这个口径差异由用户在会上向客户解释。

    `arrive_earliest` 仍按前置期算，但它**不再决定销售月**，只作为图上的一条
    参考线：这批货最早 10-17 到，也就是说 10 月上半月卖的还是现有库存。
    """
    as_of = dt.date.fromisoformat(manifest().get("as_of") or "2026-08-03")
    y, m = as_of.year, as_of.month + int(months_ahead)
    while m > 12:
        y, m = y + 1, m - 12
    first = dt.date(y, m, 1)
    last = (dt.date(y + 1, 1, 1) if m == 12 else dt.date(y, m + 1, 1)) - dt.timedelta(days=1)
    total = (last - first).days + 1
    arrive = as_of + dt.timedelta(days=int(lead_days))

    lo, hi = db.one(con(), """
        select min(forecast_date) lo, max(forecast_date) hi
          from prod.fact_child_forecast_daily
    """).values()
    covered = db.scalar(con(), """
        select count(distinct forecast_date) from prod.fact_child_forecast_daily
         where forecast_date between ? and ?
    """, (first.isoformat(), last.isoformat())) or 0

    return {
        "month": f"{y}-{m:02d}",
        "from": first.isoformat(), "to": last.isoformat(),
        "total_days": total, "covered_days": int(covered),
        "coverage": round(covered / total, 4) if total else 0.0,
        "months_ahead": int(months_ahead),
        "arrive_earliest": arrive.isoformat(),
        "forecast_from": lo, "forecast_to": hi,
        "lead_days": int(lead_days),
        "need_horizon_days": (last - as_of).days,
    }

# 需求预测 Agent 的结果库。它归库存模块所有（modules/inventory/derived/），
# 这里**只读同一个数据源文件，不 import 那个模块**（契约 §8.5 禁模块间 import）。
#
# 为什么读它：用户 2026-09-04 的判断 ——「你只是需要把那个库存预估那给预投
# 做一个专属的前端就行」。预投不自己预估销量，直接用已有那份逐子体 90 天预估。
FORECAST_AGENT_DB = (paths.MODULES_DIR / "inventory" / "derived"
                     / "forecast_agent.sqlite")
FA_RUN = "fact_child_forecast_agent_run"
FA_DAILY = "fact_child_forecast_agent_daily"

def con() -> sqlite3.Connection:
    """本模块库的线程连接，产品包已 ATTACH 为 `prod`。

    「挂过没有」问 sqlite 自己（PRAGMA database_list），不在 Connection 上
    挂标记 —— sqlite3.Connection 不接受任意属性，那样会 AttributeError。
    连接是按线程复用的，所以每个线程第一次进来挂一次。
    """
    c = db.pool(DB_PATH)
    names = {r[1] for r in c.execute("PRAGMA database_list")}
    if "prod" not in names:
        db.attach(c, paths.PRODUCT_DB, "prod")
    return c


def clear_caches() -> None:
    """外壳热重载时调（契约 §8.7）。本模块无内存缓存，只有连接池，无需清理。"""
    return None


# ---------------------------------------------------------------------------
# 元信息
# ---------------------------------------------------------------------------

def manifest() -> dict[str, str]:
    return {r["key"]: r["value"]
            for r in db.rows(con(), "select key, value from dim_preinvest_manifest")}


def leadtime() -> list[dict]:
    return db.rows(con(), """
        select stage, stage_label, seq, days_min, days_max, note
          from dim_preinvest_leadtime order by seq
    """)


def meta() -> dict[str, Any]:
    m = manifest()
    return {
        "as_of": m.get("as_of"),
        "order_month": ORDER_MONTH,
        "dataset_version": m.get("version"),
        "group_count": db.scalar(con(), "select count(*) from dim_preinvest_group"),
        "assessment_rule": m.get("assessment_rule"),
        "fabric_anchor": m.get("fabric_anchor"),
        "leadtime": leadtime(),
    }


# ---------------------------------------------------------------------------
# 配色组
# ---------------------------------------------------------------------------

def groups() -> list[dict]:
    return db.rows(con(), """
        select group_id, style_no, combination, child_count, sizes, category,
               operations_group, operator, colorway, lifecycle,
               pack_size, unit_cost_avg
          from dim_preinvest_group
         order by style_no, combination
    """)


def group(group_id: str) -> dict | None:
    return db.one(con(), """
        select group_id, style_no, combination, child_count, sizes, category,
               operations_group, operator, colorway, lifecycle,
               pack_size, unit_cost_avg
          from dim_preinvest_group where group_id = ?
    """, (group_id,))


def group_children(group_id: str) -> list[dict]:
    """配色组下的子体清单。身份从产品包读，不从本模块库读。"""
    return db.rows(con(), """
        select c.child_asin, c.size, c.parent_asin, c.product_lifecycle
          from prod.dim_product_child c
         where c.style_no || '|' || c.combination = ?
         order by c.size
    """, (group_id,))


# ---------------------------------------------------------------------------
# 历史预投轮次（考核复盘页的数据源）
# ---------------------------------------------------------------------------

def cycles(in_spine_only: bool = False) -> list[dict]:
    """真实预投轮次。

    `in_spine_only=False` 返回一组全部 141 行（其中 107 行预投>0）——
    这是财务真看到的范围。`True` 只返回能在本 Demo 里下钻的 43 行。
    **两个范围的数字不一样，页面必须同时给出并标清区别**，
    藏掉任一个都会让人以为看到的是全貌。
    """
    where = "where in_spine = 1" if in_spine_only else ""
    return db.rows(con(), f"""
        select cycle_id, group_id, style_no, combination, period_label,
               order_month, pre_invest_units, additional_units, pre_invest_total,
               order_total, remaining_units, achieve_rate, pack_size,
               total_tiao, operator, in_spine
          from fact_preinvest_cycle {where}
         order by (pre_invest_total - order_total) desc
    """)


def cycle_of_group(group_id: str) -> dict | None:
    return db.one(con(), """
        select * from fact_preinvest_cycle where group_id = ?
         order by order_month desc limit 1
    """, (group_id,))


def order_batches(cycle_id: str | None = None) -> list[dict]:
    if cycle_id:
        return db.rows(con(), """
            select cycle_id, group_id, batch_no, batch_date, order_units
              from fact_preinvest_order_batch where cycle_id = ?
             order by batch_no
        """, (cycle_id,))
    return db.rows(con(), """
        select batch_no, batch_date, sum(order_units) as order_units,
               count(*) as group_count
          from fact_preinvest_order_batch
         group by batch_no, batch_date order by batch_no
    """)


def month_history(group_id: str | None = None) -> list[dict]:
    if group_id:
        return db.rows(con(), """
            select month, pre_invest_units from fact_preinvest_month
             where group_id = ? order by month
        """, (group_id,))
    return db.rows(con(), """
        select month, sum(pre_invest_units) as pre_invest_units,
               count(*) as group_count
          from fact_preinvest_month where in_spine = 1
         group by month order by month
    """)


# ---------------------------------------------------------------------------
# 上游：逐子体需求预估
#
# 预投**不自己预估销量**。它读已有的那份，只换两件事：时间窗口（预投对应的
# 销售月）和聚合层级（配色组，不是子体）。这就是「给库存预估做专属前端」。
#
# 两个来源，优先级固定，且必须让页面看出用的是哪一个：
#   Agent 真判断  modules/inventory/derived/forecast_agent.sqlite（跑过的子体）
#   数据包快照    产品包 fact_child_forecast_daily（构造的脚手架，全 342 子体）
#
# 绝不静默混用：每个配色组带 forecast_source 标出来。一个组内部分子体有 Agent
# 判断、部分没有时算「混合」—— 那种情况下这一行的数不该直接交出去。
# ---------------------------------------------------------------------------

def _agent_forecast_daily(month_from: str, month_to: str) -> dict[str, list[dict]]:
    """Agent 真跑出来的逐日预测，按子体。取每个子体最新一次成功 run。

    库不存在或表不齐就回空 dict —— 调用方据此整体回落到数据包快照。
    """
    if not FORECAST_AGENT_DB.is_file():
        return {}
    try:
        c = db.pool(FORECAST_AGENT_DB)
        names = db.table_names(c)
        if not {FA_RUN, FA_DAILY}.issubset(names):
            return {}
        # 每个子体取最新一次 completed。run_date 是纯日期无格式歧义，
        # 同一天多次运行按 run_id 尾号（Agent 侧自增）取大的。
        latest = db.rows(c, f"""
            select child_asin, run_id from {FA_RUN}
             where status in ('completed','完成','正常')
             order by run_date asc, rowid asc
        """)
        pick = {r["child_asin"]: r["run_id"] for r in latest}   # 后者覆盖前者
        if not pick:
            return {}
        ids = tuple(pick.values())
        marks = ",".join("?" * len(ids))
        rows = db.rows(c, f"""
            select child_asin, forecast_date, p10_units, p50_units, p90_units
              from {FA_DAILY}
             where run_id in ({marks})
               and forecast_date between ? and ?
             order by child_asin, forecast_date
        """, (*ids, month_from, month_to))
    except (sqlite3.Error, OSError):
        return {}
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(r["child_asin"], []).append(r)
    return out


def _snapshot_forecast_daily(month_from: str, month_to: str) -> dict[str, list[dict]]:
    """数据包快照的逐日预测，按子体。构造的脚手架，覆盖全部 342 子体。"""
    rows = db.rows(con(), """
        select child_asin, forecast_date, p10_units, p50_units, p90_units
          from prod.fact_child_forecast_daily
         where forecast_date between ? and ?
         order by child_asin, forecast_date
    """, (month_from, month_to))
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(r["child_asin"], []).append(r)
    return out


def child_to_group() -> dict[str, str]:
    return {r["child_asin"]: r["group_id"] for r in db.rows(con(), """
        select child_asin, style_no || '|' || combination as group_id
          from prod.dim_product_child
         where ifnull(style_no,'') <> '' and ifnull(combination,'') <> ''
    """)}


# ---------------------------------------------------------------------------
# 判断对象：子 ASIN（款号 × 组合 × 配色 × 尺码）
#
# ⚠️ v0.1~v0.3 做成配色组（57 个）是错的。实测 3.库存表 的逐月预投列
# **713 处各尺码值不同、仅 101 处相同** —— 运营是逐尺码填预投的，
# 一个尺码就是一个 ASIN。月报那张按配色组的表是考核汇总视图。
# 用户 2026-09-04：「你这个预投本来就是型号乘尺码的……你这个预估也是要以
# 这个尺码为维度去做预投啊，你不能把它合在一起的。」
# ---------------------------------------------------------------------------

def children() -> list[dict]:
    """342 个子 ASIN，带产品定位信息。身份从产品包读，不自建维表（G7）。"""
    return db.rows(con(), """
        select c.child_asin, c.parent_asin, c.product_name, c.style_no,
               c.combination, c.colorway, c.size, c.category,
               c.operations_group, c.operator, c.goods_status,
               c.product_lifecycle, c.category_rank, c.rating,
               c.style_no || '|' || c.combination as group_id,
               e.pack_size, e.unit_cost
          from prod.dim_product_child c
          left join prod.fact_unit_economics e on e.child_asin = c.child_asin
         order by c.style_no, c.combination, c.size
    """)


def child(child_asin: str) -> dict | None:
    rows = [r for r in children() if r["child_asin"] == child_asin]
    return rows[0] if rows else None


def forecast_by_child(month_from: str, month_to: str) -> dict[str, dict]:
    """目标销售月的预估销量，**按子 ASIN**（不聚合到配色组）。

    Agent 真判断优先，回落数据包快照，每个 ASIN 标出用的是哪一种。
    """
    agent = _agent_forecast_daily(month_from, month_to)
    snap = _snapshot_forecast_daily(month_from, month_to)
    out: dict[str, dict] = {}
    for ch in {*agent, *snap}:
        rows = agent.get(ch)
        src = "agent" if rows else "snapshot"
        if not rows:
            rows = snap.get(ch) or []
        if not rows:
            continue
        out[ch] = {
            "p10": round(sum(float(r["p10_units"] or 0) for r in rows)),
            "p50": round(sum(float(r["p50_units"] or 0) for r in rows)),
            "p90": round(sum(float(r["p90_units"] or 0) for r in rows)),
            "days": len(rows),
            "forecast_source": src,
        }
    return out


def agent_judgment(child_asin: str) -> dict | None:
    """这个 ASIN 的需求判断 —— 「为什么这么预估」。

    这是用户要的「Agent 的样子」：一句话总结 + 五项因子（各带状态、影响幅度、
    带真实数字的中文依据）+ 确定程度与理由。全部由需求预测 Agent 产出，
    预投这边只读、只渲染，一个字都不自己编。
    """
    if not FORECAST_AGENT_DB.is_file():
        return None
    try:
        c = db.pool(FORECAST_AGENT_DB)
        if not {FA_RUN, "fact_child_forecast_judgment_factor"}.issubset(db.table_names(c)):
            return None
        run = db.one(c, f"""
            select run_id, run_date, model_version, confidence, confidence_reason,
                   judgment_summary, horizon_days, trigger
              from {FA_RUN}
             where child_asin = ? and status in ('completed','完成','正常')
             order by run_date desc, rowid desc limit 1
        """, (child_asin,))
        if not run:
            return None
        factors = db.rows(c, """
            select factor, ord, state, impact_pct, because
              from fact_child_forecast_judgment_factor
             where run_id = ? order by ord
        """, (run["run_id"],))
    except (sqlite3.Error, OSError):
        return None
    for f in factors:
        f["factor_label"] = FACTOR_LABEL.get(str(f.get("factor")), "待确认")
    run["factors"] = factors
    return run


# 因子英文键 → 中文。内部键绝不上屏（G9），映射发生在这个读取边界。
FACTOR_LABEL = {
    "stockout_distortion": "缺货扭曲",
    "promotion": "站内活动",
    "lifecycle": "生命周期",
    "advertising": "广告投放",
    "seasonality": "季节性",
}


def month_history_child(child_asin: str) -> list[dict]:
    """这个 ASIN 过去各月实际投了多少 —— 逐尺码的真实历史。"""
    return db.rows(con(), """
        select month, kind, units from fact_preinvest_month
         where child_asin = ? order by month, kind
    """, (child_asin,))


def forecast_daily_child(child_asin: str, date_from: str, date_to: str) -> dict[str, Any]:
    """一个子 ASIN 的逐日预估。图上圈一段用的就是它。"""
    agent = _agent_forecast_daily(date_from, date_to)
    rows = agent.get(child_asin)
    src = "agent" if rows else "snapshot"
    if not rows:
        rows = (_snapshot_forecast_daily(date_from, date_to)).get(child_asin) or []
    return {
        "dates": [r["forecast_date"] for r in rows],
        "p10": [round(float(r["p10_units"] or 0), 2) for r in rows],
        "p50": [round(float(r["p50_units"] or 0), 2) for r in rows],
        "p90": [round(float(r["p90_units"] or 0), 2) for r in rows],
        "source": src,
    }


def history_daily_child(child_asin: str, days: int = 120) -> dict[str, Any]:
    as_of = manifest().get("as_of") or "2026-08-03"
    rows = db.rows(con(), """
        select date, units_sold as units from prod.fact_child_sales_daily
         where child_asin = ?
           and date > date(?, '-' || ? || ' day') and date <= ?
         order by date
    """, (child_asin, as_of, int(days), as_of))
    return {"dates": [r["date"] for r in rows],
            "units": [round(float(r["units"] or 0), 2) for r in rows]}


def forecast_by_group(month_from: str = TARGET_FROM,
                      month_to: str = TARGET_TO) -> dict[str, dict]:
    """目标销售月的预估销量，按配色组聚合。

    子体级 p10/p50/p90 求和到组级。求和而不是取分位数的分位数：组级区间因此
    偏宽（各子体不完全同向），这一点在页面上标明口径。

    `forecast_source` 三态：`agent`（该组全部子体都有 Agent 判断）/
    `mixed`（部分有）/ `snapshot`（一个都没有，全走数据包脚手架）。
    """
    c2g = child_to_group()
    agent = _agent_forecast_daily(month_from, month_to)
    snap = _snapshot_forecast_daily(month_from, month_to)

    acc: dict[str, dict] = {}
    for child, gid in c2g.items():
        rows = agent.get(child)
        src = "agent" if rows else "snapshot"
        if not rows:
            rows = snap.get(child) or []
        if not rows:
            continue
        a = acc.setdefault(gid, {"p10": 0.0, "p50": 0.0, "p90": 0.0,
                                 "child_count": 0, "agent_children": 0,
                                 "day_rows": 0})
        for r in rows:
            a["p10"] += float(r["p10_units"] or 0)
            a["p50"] += float(r["p50_units"] or 0)
            a["p90"] += float(r["p90_units"] or 0)
        a["child_count"] += 1
        a["day_rows"] += len(rows)
        if src == "agent":
            a["agent_children"] += 1

    for gid, a in acc.items():
        n, k = a["child_count"], a["agent_children"]
        a["forecast_source"] = "agent" if k and k == n else ("mixed" if k else "snapshot")
        for key in ("p10", "p50", "p90"):
            a[key] = round(a[key])
    return acc


def forecast_daily_group(group_id: str, date_from: str, date_to: str) -> dict[str, Any]:
    """一个配色组的逐日预估，把它下面所有尺码子体按天加起来。

    这是「预投是库存那张柱状图上的一段」那个视图的数据源：整段逐日给出来，
    页面自己把预投窗口那一段高亮并求和。
    """
    children = [r["child_asin"] for r in db.rows(con(), """
        select child_asin from prod.dim_product_child
         where style_no || '|' || combination = ?
    """, (group_id,))]
    if not children:
        return {"dates": [], "p50": [], "p10": [], "p90": [], "source": "缺失"}

    agent = _agent_forecast_daily(date_from, date_to)
    snap = _snapshot_forecast_daily(date_from, date_to)

    by_day: dict[str, dict[str, float]] = {}
    n_agent = 0
    for ch in children:
        rows = agent.get(ch)
        if rows:
            n_agent += 1
        else:
            rows = snap.get(ch) or []
        for r in rows:
            d = by_day.setdefault(r["forecast_date"], {"p10": 0.0, "p50": 0.0, "p90": 0.0})
            d["p10"] += float(r["p10_units"] or 0)
            d["p50"] += float(r["p50_units"] or 0)
            d["p90"] += float(r["p90_units"] or 0)

    dates = sorted(by_day)
    return {
        "dates": dates,
        "p10": [round(by_day[d]["p10"], 2) for d in dates],
        "p50": [round(by_day[d]["p50"], 2) for d in dates],
        "p90": [round(by_day[d]["p90"], 2) for d in dates],
        "child_count": len(children),
        "agent_children": n_agent,
        "source": ("agent" if n_agent == len(children)
                   else ("mixed" if n_agent else "snapshot")),
    }


def history_daily_group(group_id: str, days: int = 120) -> dict[str, Any]:
    """同一个配色组的历史逐日实销，接在预测段左边 —— 图上要有对照。"""
    as_of = manifest().get("as_of") or "2026-08-03"
    rows = db.rows(con(), """
        select s.date, sum(s.units_sold) as units
          from prod.fact_child_sales_daily s
          join prod.dim_product_child c on c.child_asin = s.child_asin
         where c.style_no || '|' || c.combination = ?
           and s.date > date(?, '-' || ? || ' day') and s.date <= ?
         group by s.date order by s.date
    """, (group_id, as_of, int(days), as_of))
    return {"dates": [r["date"] for r in rows],
            "units": [round(float(r["units"] or 0), 2) for r in rows]}


def window_daily_avg(group_id: str | None = None) -> dict[str, dict]:
    """现行 Excel 口径要的四个窗口日均（3/7/15/30 天），按配色组。

    吴组长口述是 15 天，领星系统实际列是 14 天 —— 这里按口述从逐日销量自算，
    差异记在 00-源表勘查/01-源表事实.md §8。
    """
    as_of = manifest().get("as_of") or "2026-08-03"
    clause = "and c.style_no || '|' || c.combination = ?" if group_id else ""
    # 占位符 8 个：四个窗口各 1、365 天 1、去年同期 2、末尾 where 1。
    args: list[Any] = [as_of] * 8
    sql = f"""
        select c.style_no || '|' || c.combination as group_id,
               sum(case when s.date > date(?, '-3 day')  then s.units_sold else 0 end) / 3.0  as d3,
               sum(case when s.date > date(?, '-7 day')  then s.units_sold else 0 end) / 7.0  as d7,
               sum(case when s.date > date(?, '-15 day') then s.units_sold else 0 end) / 15.0 as d15,
               sum(case when s.date > date(?, '-30 day') then s.units_sold else 0 end) / 30.0 as d30,
               sum(case when s.date > date(?, '-365 day') then s.units_sold else 0 end) as units_365d,
               sum(case when s.date > date(?, '-425 day')
                         and s.date <= date(?, '-395 day')
                        then s.units_sold else 0 end) as units_same_period_last_year
          from prod.fact_child_sales_daily s
          join prod.dim_product_child c on c.child_asin = s.child_asin
         where s.date <= ?
           and ifnull(c.style_no,'') <> '' and ifnull(c.combination,'') <> ''
           {clause}
         group by group_id
    """
    if group_id:
        args.append(group_id)
    return {r["group_id"]: r for r in db.rows(con(), sql, args)}


def planned_promotions(month_from: str = TARGET_FROM,
                       month_to: str = TARGET_TO) -> dict[str, list[dict]]:
    """目标销售月已排的活动，按配色组。

    这是吴组长第二个判断点的现成反例来源：「明明下个月是会安排一些 BD 或者 LD
    的情况，而他没有把这些事给他考虑进去」（01:05:31）。
    """
    rows = db.rows(con(), """
        select c.style_no || '|' || c.combination as group_id,
               p.promotion_type, min(p.date) as date_from, max(p.date) as date_to,
               count(distinct c.child_asin) as child_count,
               round(avg(p.planned_discount_rate), 4) as discount_rate
          from prod.plan_child_promotion_daily p
          join prod.dim_product_child c on c.child_asin = p.child_asin
         where p.date between ? and ?
           and ifnull(p.promotion_type,'') not in ('', 'none')
           and ifnull(c.style_no,'') <> '' and ifnull(c.combination,'') <> ''
         group by group_id, p.promotion_type
    """, (month_from, month_to))
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(r["group_id"], []).append(r)
    return out


def size_share(group_id: str | None = None) -> list[dict]:
    if group_id:
        return db.rows(con(), """
            select group_id, size, child_asin, units_365d, share
              from fact_preinvest_size_share where group_id = ?
             order by units_365d desc
        """, (group_id,))
    return db.rows(con(), """
        select group_id, size, child_asin, units_365d, share
          from fact_preinvest_size_share
    """)
