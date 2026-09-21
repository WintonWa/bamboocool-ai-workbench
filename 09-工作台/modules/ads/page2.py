"""页面二（单一子 ASIN 广告决策）的派生展示块。

设计见 `04-广告分析模块/01-方案与数据需求/07-页面二屏幕决策设计.md`。

这一层**只做重排与分桶，不产判断**：把已经在 context / Agent 输出里的数字
整理成图表能直接吃的形状。任何"这个变化是好还是坏"的语义，只允许来自
本文件顶部那张写死的指标方向表——那是口径，不是对某一次运行的判断。

三条红线：
  1. 7 天与 14 天归因**分桶后不再合并**，绝不给跨桶合计（设计 §3②）
  2. 逐日两种 `metric_basis` 是两种推导，**不求和**，按参数选一种
  3. 没有复盘记录就如实说没有，不回落、不构造（设计 §3⑤）
"""
from __future__ import annotations

from core import db as dbx

# ---------------------------------------------------------------- 指标口径

# 效果对比用的指标表：中文名、格式、以及"往哪个方向走算好"。
#
# 方向必须逐指标定，不能统一：ACoS 下降是好、转化率上升是好，
# 而**花费上升本身没有好坏**——给花费涨了标红是在替运营做一个它没做的判断。
# neutral 的指标不着色，只显示数字与幅度。
#
# 顺序 = 上屏顺序：效率先行，规模在后。运营看复盘先看效率有没有改善。
REVIEW_METRICS = [
    ("acos", "ACoS", "pct", "down"),
    ("roas", "ROAS", "x", "up"),
    ("cvr", "转化率", "pct", "up"),
    ("ctr", "点击率", "pct", "up"),
    ("cpc", "单次点击成本", "usd2", "down"),
    ("spend", "花费", "usd", "neutral"),
    ("ad_sales", "广告销售额", "usd", "neutral"),
    ("orders", "订单", "int", "up"),
    ("clicks", "点击", "int", "neutral"),
    ("impressions", "曝光", "int", "neutral"),
]

# 销量趋势六窗口。嵌套累计：3 天那格是最近 3 天的日均，不是第 1–3 天。
# 短窗低于长窗即为走低（证据自带的 caveat）。
TREND_WINDOWS = [("daily_avg_3d", "近 3 天"), ("daily_avg_7d", "近 7 天"),
                 ("daily_avg_14d", "近 14 天"), ("daily_avg_30d", "近 30 天"),
                 ("daily_avg_60d", "近 60 天"), ("daily_avg_90d", "近 90 天")]

# 竞品压力类型的上屏顺序。矩阵的列就是这个顺序，缺的类型列照样在——
# "这一类没有压力"是信息，列消失了看的人分不清是没压力还是没查。
PRESSURE_COLS = [("price", "价格"), ("rank", "排名"),
                 ("keyword_entry", "核心词入口"), ("review", "评价"),
                 ("variant", "变体覆盖"), ("promotion", "活动"),
                 ("sales", "销量规模")]

# 约束四域，同理：四格常在，没有约束的格子写"本期无"。
CONSTRAINT_DOMAINS = [("cost", "成本"), ("traffic", "流量"),
                      ("inventory", "库存"), ("event", "事件")]


def _num(v):
    """None 与 0 是两件事，所以只把真的取不到的值变成 None。"""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------- ① 归因分桶（②板块）

def attribution_groups(structure: list[dict]) -> list[dict]:
    """按归因窗口把广告对象分桶。

    为什么必须分：`ev_*_adperf` 的 payload 自己把 SP 的 7 天和 SD 的 14 天
    加成了 `spend 18792.73 / acos 0.0755`，而同一条证据的 caveat 明写
    "SP 与 SD/SB 归因窗口不同不可相加"——数据自己打自己。
    页面按窗口分桶，**不给跨桶合计**。

    桶内的 ACoS / ROAS / CTR / CVR 由桶内合计重算，不平均对象级比率：
    平均比率会让一个零花费对象和一个一万五花费对象等权。
    """
    buckets: dict[int, list[dict]] = {}
    for r in structure:
        d = r.get("attribution_days")
        buckets.setdefault(int(d) if d else 0, []).append(r)

    out = []
    for days in sorted(buckets):
        rows = buckets[days]
        agg = {}
        for k in ("spend", "ad_sales", "clicks", "orders", "impressions"):
            vals = [_num(r.get(k)) for r in rows]
            got = [v for v in vals if v is not None]
            agg[k] = sum(got) if got else None
        sp, sales = agg["spend"], agg["ad_sales"]
        clicks, imps, orders = agg["clicks"], agg["impressions"], agg["orders"]
        cvr = (orders / clicks) if orders is not None and clicks else None
        out.append({
            "attribution_days": days or None,
            "label": ("%d 天归因" % days) if days else "归因窗口未标注",
            "object_count": len(rows),
            "ad_types": sorted({r.get("ad_type") for r in rows if r.get("ad_type")}),
            "object_ids": [r.get("ad_object_id") for r in rows],
            **agg,
            # 合计重算，不平均对象级比率
            "acos": (sp / sales) if sp is not None and sales else None,
            "roas": (sales / sp) if sales is not None and sp else None,
            "ctr": (clicks / imps) if clicks is not None and imps else None,
            "cvr": cvr,
            "cpc": (sp / clicks) if sp is not None and clicks else None,
            # 桶里最大的共享数——归因稀释条画这个
            "max_shared": max((r.get("shared_child_count") or 1)
                              for r in rows) if rows else 1,
            # 转化率大于 100% 在算术上不可能（订单数超过点击数），
            # 说明这一桶的分子分母不是同一批流量。这是算术不是判断，
            # 但页面必须说出来——否则"转化率 162%"看着像前端算错了。
            # 实测 14 天桶就是这样：orders 6373 / clicks 3932 = 1.62，
            # 与 Agent 的 B0e「共享桶被整体计为单品归因」是同一件事。
            "ratio_impossible": bool(cvr is not None and cvr > 1),
        })
    return out


# --------------------------------------------------- ② 从证据里抽结构化事实

def fact_blocks(evidence: list[dict]) -> dict:
    """把证据卡的 payload 抽成图表能吃的形状。

    只认 payload 里**已经是数字**的字段。绝不从中文 detail / label 句子里
    正则抽数字：那些句子是 Agent 或构建期写的判断产物，
    把它当数据源等于让判断反过来定义事实（设计 §3① 末尾）。

    **两条决策链的同名证据 payload 形状不同**，实测：
      ext 链（5 个对象）INVENTORY 给 `closing_fba_sellable / coverage_days`
      base 链（B088WF1PRW）INVENTORY 给 `available / fba_inventory / receiving`
    所以每个字段按候选键列表取，取不到就是 None，不猜也不换算。
    """
    by_type = {}
    for e in evidence:
        by_type.setdefault(e.get("evidence_type"), []).append(e)

    def payload(*types):
        """取第一条该类型且 payload 是非空 dict 的证据。

        base 链的 KEYWORD payload 是 list，这里跳过——关键词本来就走
        context.keywords，不从证据里抽第二份。
        """
        for t in types:
            for e in by_type.get(t) or []:
                p = e.get("payload")
                if isinstance(p, dict) and p:
                    return p, e
        return None, None

    def pick(p: dict, *keys):
        for k in keys:
            if k in p:
                v = _num(p.get(k))
                if v is not None:
                    return v
        return None

    out = {}

    # 销量趋势六窗口（只有 ext 链有）
    p, e = payload("SALES_TREND", "PRODUCT_TREND")
    if p:
        bars = [{"key": k, "label": lab, "value": _num(p.get(k))}
                for k, lab in TREND_WINDOWS]
        got = [b for b in bars if b["value"] is not None]
        first = got[0]["value"] if got else None
        last = got[-1]["value"] if got else None
        out["trend"] = {
            "evidence_id": e.get("evidence_id"), "caveat": e.get("caveat"),
            "nature": e.get("nature"), "observed_at": e.get("observed_at"),
            "bars": bars,
            "units_30d": _num(p.get("units_30d")),
            # 最短窗对最长窗：负值就是在走低。名字叫 ratio 不叫 verdict——
            # 这是算术，不是判断。
            "short_vs_long": ((first - last) / last)
            if first is not None and last else None,
        }

    # 库存承接：时间轴的四个点 + 两个量。两条链的键名不同，逐字段给候选。
    p, e = payload("INVENTORY")
    if p:
        out["inventory"] = {
            "evidence_id": e.get("evidence_id"), "caveat": e.get("caveat"),
            "nature": e.get("nature"), "observed_at": e.get("observed_at"),
            "sellable": pick(p, "closing_fba_sellable", "available"),
            "on_hand": pick(p, "fba_inventory"),
            "inbound": pick(p, "fba_inbound"),
            "receiving": pick(p, "receiving"),
            "coverage_days": pick(p, "coverage_days",
                                  "immediate_available_days"),
            "safety_days": pick(p, "dynamic_safety_days"),
            "daily_avg_30d": pick(p, "daily_avg_30d"),
            "sales_30d": pick(p, "sales_30d"),
            "safety_breach_date": p.get("safety_breach_date"),
            # 库里用字符串 "none" 表示"窗口内不断货"，不是缺数据
            "base_stockout_date": (None if p.get("base_stockout_date") in
                                   (None, "none", "")
                                   else p.get("base_stockout_date")),
            "stress_stockout_date": (None if p.get("stress_stockout_date") in
                                     (None, "none", "")
                                     else p.get("stress_stockout_date")),
            "latest_order_date": p.get("latest_order_date"),
            "suggested_qty": pick(p, "suggested_replenishment_qty"),
        }

    # 搜索词展示份额（证据类型实测是 AD_PLACEMENT，不是 SEARCH_TERM_SHARE）
    p, e = payload("AD_PLACEMENT", "SEARCH_TERM_SHARE")
    if p and isinstance(p.get("terms"), list):
        terms = [{"term": t.get("term"), "rank": _num(t.get("rank")),
                  "share": _num(t.get("share")),
                  "impressions": _num(t.get("impressions"))}
                 for t in p["terms"] if isinstance(t, dict)]
        out["share"] = {
            "evidence_id": e.get("evidence_id"), "caveat": e.get("caveat"),
            "nature": e.get("nature"),
            "terms": sorted(terms, key=lambda x: -(x["impressions"] or 0)),
        }

    # 成交归属但非推广：归因边界的量级
    p, e = payload("ATTRIBUTION_GAP", "PURCHASE_GAP")
    if p:
        out["purchase_gap"] = {
            "evidence_id": e.get("evidence_id"), "caveat": e.get("caveat"),
            "nature": e.get("nature"),
            "objects": _num(p.get("objects")),
            "spend": _num(p.get("spend")),
            "ad_sales": _num(p.get("ad_sales")),
        }

    # 临近事件：到货批次与计划促销
    p, e = payload("BUSINESS_EVENT", "EVENT")
    if p:
        out["events"] = {
            "evidence_id": e.get("evidence_id"), "caveat": e.get("caveat"),
            "nature": e.get("nature"),
            "inbound": [x for x in (p.get("inbound") or [])
                        if isinstance(x, dict)],
            "planned": [x for x in (p.get("planned") or [])
                        if isinstance(x, dict)],
        }

    return out


def pressure_matrix(competitor: list[dict]) -> dict:
    """竞品压力矩阵：品牌×压力类型。列固定，缺的类型列照样在。"""
    brands: dict[str, dict] = {}
    for p in competitor or []:
        b = p.get("brand") or p.get("competitor_asin") or "未标注品牌"
        row = brands.setdefault(b, {"brand": b, "asins": [], "cells": {}})
        a = p.get("competitor_asin")
        if a and a not in row["asins"]:
            row["asins"].append(a)
        cell = row["cells"].setdefault(p.get("pressure_type") or "", [])
        cell.append({"label": p.get("pressure_label") or p.get("type_label"),
                     "detail": p.get("detail"),
                     "verified": bool(p.get("is_verified")),
                     "verify_label": p.get("verify_label"),
                     "observed_at": p.get("observed_at")})
    cols = [{"key": k, "label": lab} for k, lab in PRESSURE_COLS]
    return {"cols": cols, "rows": list(brands.values()),
            "hit_types": sorted({p.get("pressure_type")
                                 for p in competitor or [] if p.get("pressure_type")})}


def constraint_domains(constraints: list[dict]) -> list[dict]:
    """约束按四域摊开。空域保留并写明本期无，不让格子消失。"""
    out = []
    for key, label in CONSTRAINT_DOMAINS:
        rows = [c for c in (constraints or []) if (c.get("domain") or "") == key]
        out.append({
            "key": key, "label": label, "rows": rows,
            "hard_n": sum(1 for c in rows if c.get("kind") == "hard"),
            "observe_n": sum(1 for c in rows if c.get("kind") != "hard"),
        })
    other = [c for c in (constraints or [])
             if (c.get("domain") or "") not in dict(CONSTRAINT_DOMAINS)]
    if other:
        out.append({"key": "other", "label": "其他", "rows": other,
                    "hard_n": sum(1 for c in other if c.get("kind") == "hard"),
                    "observe_n": sum(1 for c in other if c.get("kind") != "hard")})
    return out


# ------------------------------------------------------------- ③ 逐日趋势

def daily_series(con, structure: list[dict], basis: str,
                 max_objects: int = 4) -> dict:
    """按对象取逐日。**两种 metric_basis 不求和**，按参数选一种。

    实测同一对象两种口径各一行/天（48 行 / 27 天），加起来是把两种推导
    混成一个数。口径由 `ads.daily_basis` 参数选，两种算出的环比变化率相同、
    只有水平值不同（rules.py 的注释）。

    没有逐日的对象如实报出来——`camp_*` 与暂停的 `grp_*` 实测零行，
    画一张空图比说"无记录"更糟。
    """
    ids = [r.get("ad_object_id") for r in structure if r.get("ad_object_id")]
    if not ids:
        return {"basis": basis, "objects": [], "no_daily": [], "dates": []}
    ph = ",".join("?" * len(ids))
    rows = dbx.rows(con, """
        select ad_object_id, stat_date, impressions, clicks, spend,
               orders, ad_sales, day_coverage
          from fact_ad_daily
         where metric_basis=? and ad_object_id in (%s)
         order by ad_object_id, stat_date""" % ph, (basis,) + tuple(ids))

    grouped: dict[str, list[dict]] = {}
    for r in rows:
        grouped.setdefault(r["ad_object_id"], []).append(r)

    name = {r.get("ad_object_id"): r.get("name") for r in structure}
    atype = {r.get("ad_object_id"): r.get("ad_type") for r in structure}
    adays = {r.get("ad_object_id"): r.get("attribution_days")
             for r in structure}

    objs = []
    for oid, series in sorted(grouped.items(),
                              key=lambda kv: -sum(_num(x["spend"]) or 0
                                                  for x in kv[1])):
        if len(objs) >= max_objects:
            break
        pts = []
        for r in series:
            sp, sales = _num(r["spend"]), _num(r["ad_sales"])
            pts.append({
                "date": r["stat_date"],
                "spend": sp, "ad_sales": sales,
                "clicks": _num(r["clicks"]), "orders": _num(r["orders"]),
                "impressions": _num(r["impressions"]),
                # 逐日 ACoS 由当天两个量算，不取月度值摊平
                "acos": (sp / sales) if sp is not None and sales else None,
                "day_coverage": r["day_coverage"],
            })
        objs.append({"ad_object_id": oid, "name": name.get(oid) or oid,
                     "ad_type": atype.get(oid),
                     "attribution_days": adays.get(oid),
                     "days": len(pts), "points": pts})

    dates = sorted({p["date"] for o in objs for p in o["points"]})
    return {
        "basis": basis,
        "basis_label": ("放大到月度总额" if basis == "daily_scaled_to_month"
                        else "搜索词原值"),
        "objects": objs,
        "no_daily": [{"ad_object_id": i, "name": name.get(i) or i}
                     for i in ids if i not in grouped],
        "dates": dates,
        "window": [dates[0], dates[-1]] if dates else None,
    }


# --------------------------------------------------- ④ 执行后效果监控（⑤板块）

def monitor(history: dict, proposals: list[dict], rs: dict) -> dict:
    """效果监控：双阈值 + 基准对观察 + 同期变量 + 决策事件。

    双阈值都用现成的东西，不新造参数（设计 §3⑤）：
      时间阈值 = 建议自带的复盘窗口 `review_windows`
      数据量阈值 = `ads.min_clicks`（本就是"点击少于它不参与效率判断"）

    没有复盘记录时返回 `has_data=False` 并说明缺什么，
    前端据此显示"未接入"而不是空板块。
    """
    reviews = list((history or {}).get("reviews") or [])
    events = list((history or {}).get("events") or [])

    min_clicks = rs.get("min_clicks")
    windows = []
    for p in proposals or []:
        for w in (p.get("review_windows") or []):
            if w not in windows:
                windows.append(w)
    # 已经写下来的复盘记录本身就带窗口。只从 B4 取会出现这种错：
    # 对象有 D+3/D+7 两份真实复盘记录，而它没跑过 Agent 所以没有 B4，
    # 于是"时间阈值"显示成 —— 而下面明明列着两个窗口。
    # 实际用过的窗口是事实，比建议里写的更硬。
    for rv in reviews:
        w = rv.get("review_window")
        if w and w not in windows:
            windows.append(w)

    cards = []
    for rv in reviews:
        base = rv.get("baseline_metrics") or {}
        obs = rv.get("observed_metrics") or {}
        rowsm = []
        for key, label, kind, better in REVIEW_METRICS:
            b, o = _num(base.get(key)), _num(obs.get(key))
            if b is None and o is None:
                continue
            change = ((o - b) / abs(b)) if (b not in (None, 0)
                                            and o is not None) else None
            # 方向语义只从上面那张写死的表来。neutral 一律不着色。
            tone = ""
            if change is not None and better != "neutral":
                improved = (change < 0) if better == "down" else (change > 0)
                tone = "good" if improved else "warn"
            rowsm.append({
                "key": key, "label": label, "kind": kind, "better": better,
                "baseline": b, "observed": o, "change": change, "tone": tone,
                # 比率类另给百分点差，相对变化容易把 57%→30% 说成 -48%
                "points": ((o - b) * 100) if kind == "pct"
                and b is not None and o is not None else None,
            })
        got_clicks = _num(obs.get("clicks"))
        cards.append({
            "feedback_id": rv.get("feedback_id"),
            "window": rv.get("review_window"),
            "review_at": rv.get("review_at"),
            "status": rv.get("status"),
            "conclusion": rv.get("conclusion"),
            "concurrent_variables": rv.get("concurrent_variables") or [],
            "next_question": rv.get("next_question"),
            "metrics": rowsm,
            # 数据量阈值到没到：够不够做效率判断
            "clicks": got_clicks,
            "min_clicks": min_clicks,
            "sample_ok": (got_clicks is not None and min_clicks is not None
                          and got_clicks >= min_clicks),
        })

    return {
        "has_data": bool(cards),
        "thresholds": {"time_windows": windows, "min_clicks": min_clicks},
        "cards": cards,
        "events": events,
        # 没数据时说清缺什么，不说"暂无"
        "why_empty": None if cards else
        "这个子 ASIN 还没有被采纳并执行的建议，所以没有复盘记录。"
        "复盘记录由执行侧在到达复盘窗口后写入。",
    }


def lineage(versions: list[dict], history: dict) -> dict:
    """决策沿革：版本时间轴 + 每版挂到的事件与复盘。

    这是"上一次的建议后来怎么样了"，会上说的回测的第一种含义。
    第二种（把策略带回历史某日重跑）没有数据也没有 Agent 能力，
    在 `backtest` 里如实标未接入并写清前置条件——不造结论。
    """
    events = (history or {}).get("events") or []
    reviews = (history or {}).get("reviews") or []
    by_ver = {}
    for e in events:
        by_ver.setdefault(e.get("decision_id"), {"events": [], "reviews": []})["events"].append(e)
    for r in reviews:
        by_ver.setdefault(r.get("decision_id"), {"events": [], "reviews": []})["reviews"].append(r)

    items = []
    for v in versions or []:
        did = v.get("decision_id")
        bag = by_ver.get(did) or {"events": [], "reviews": []}
        items.append({
            "decision_id": did,
            "decision_at": v.get("decision_at"),
            "product_goal": v.get("product_goal"),
            "is_current": bool(v.get("is_current")),
            "event_n": len(bag["events"]),
            "review_n": len(bag["reviews"]),
            "events": bag["events"],
        })

    return {
        "versions": items,
        "has_history": len(items) > 1,
        "backtest": {
            "available": False,
            "label": "策略回测",
            # 会上原话的四个前置条件。写清缺哪一样，比一句"未接入"有用。
            "needs": [
                "选一个历史基准日（例如该子 ASIN 上线当月）",
                "屏蔽该日之后的全部事实，只把当日已存在的证据递给 Agent",
                "用同一套门槛参数跑同一个广告 Agent",
                "把它当时的建议与该日之后真实发生的结果逐指标对比",
            ],
            "missing": "当前数据包只有单一基准日 2026-08-03 的快照，"
                       "没有按历史日期切片的事实，Agent 侧也没有回测入口。",
        },
    }
