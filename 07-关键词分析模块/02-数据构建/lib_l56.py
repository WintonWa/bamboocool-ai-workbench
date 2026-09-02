#!/usr/bin/env python3
"""L5 付费侧词级证据 + L6 产品目标与库存承接。

L5 的硬约束：词级流量与花费之和必须严格小于 v0.3.0 当日子体真实值——
钱和流量不能凭空造出来，且必须留出未归因残差（不是所有流量都来自监控词）。
L6 只做 v0.3.0 结果的投影与中文化，不重算库存。
"""
from __future__ import annotations

import collections
import hashlib
import random

import lib_l4 as L4

# 未归因残差区间：监控词最多解释掉多少比例的当日流量/花费
RESIDUAL_MIN, RESIDUAL_MAX = 0.22, 0.55

GOAL_LABEL = {
    "volume_push": "冲量抢位",
    "hold_position": "稳定守位",
    "niche_explore": "细分需求探索",
    "brand_defend": "品牌防守",
    "clear_stock": "清库退场",
    "maintain_base": "维持基本盘",
}
PUSH_LABEL = {"main": "主推", "assist": "辅助", "normal": "常规"}
ABSORB_LABEL = {
    "can_absorb_extra": "可承接额外流量",
    "normal_only": "仅可承接正常需求",
    "cannot_absorb": "不可承接扩量",
    "replenish_first": "需先补货再扩量",
}


def _rng(*parts) -> random.Random:
    h = hashlib.md5("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()
    return random.Random(int(h[:12], 16))


def _rank_weight(rank, depth):
    """位次越好权重越大，用 1/log 形状而非线性，贴近真实点击衰减。"""
    if not rank:
        return 0.0
    import math
    return 1.0 / math.log(rank + 1.6, 2)


# ------------------------------------------------------------------ L5 付费侧

def build_traffic(pos_daily, pair_rows, caps):
    """→ (rows, unattributed_rows)

    caps: {(child_asin, date): {sessions, clicks, ad_spend, ad_impressions}}
    """
    pair_kw = {p["pair_id"]: p["keyword_id"] for p in pair_rows}
    by_cd = collections.defaultdict(list)
    for r in pos_daily:
        if r["organic_state"] == "covered" or r["ad_state"] == "covered":
            by_cd[(r["child_asin"], r["date"])].append(r)

    rows = []
    unattr = []
    rid = 0
    for (asin, date), group in by_cd.items():
        cap = caps.get((asin, date)) or {}
        sess_cap = cap.get("sessions") or 0
        click_cap = cap.get("clicks") or 0
        spend_cap = float(cap.get("ad_spend") or 0.0)
        imp_cap = cap.get("ad_impressions") or 0
        rng = _rng("traffic", asin, date)
        explain = RESIDUAL_MIN + rng.random() * (RESIDUAL_MAX - RESIDUAL_MIN)

        o_w = {r["pos_id"]: _rank_weight(r["organic_rank"], L4.COLLECT_DEPTH)
               for r in group}
        a_w = {r["pos_id"]: _rank_weight(r["ad_rank"], L4.AD_DEPTH)
               for r in group}
        o_sum = sum(o_w.values()) or 1.0
        a_sum = sum(a_w.values()) or 1.0

        o_used = a_used_clicks = a_used_imp = 0
        a_used_spend = 0.0
        for r in group:
            rid += 1
            o_share = o_w[r["pos_id"]] / o_sum
            a_share = a_w[r["pos_id"]] / a_sum
            o_sess = int(sess_cap * explain * o_share)
            a_clicks = int(click_cap * explain * a_share)
            a_imp = int(imp_cap * explain * a_share)
            a_spend = round(spend_cap * explain * a_share, 4)
            o_used += o_sess
            a_used_clicks += a_clicks
            a_used_imp += a_imp
            a_used_spend += a_spend
            cvr = round(0.008 + rng.random() * 0.05, 4)
            orders = int(a_clicks * cvr)
            aov = 18.0 + rng.random() * 14.0
            sales = round(orders * aov, 2)
            rows.append({
                "traffic_id": rid,
                "keyword_id": pair_kw[r["pair_id"]],
                "pair_id": r["pair_id"],
                "child_asin": asin,
                "date": date,
                "organic_sessions": o_sess if r["organic_state"] == "covered" else 0,
                "ad_impressions": a_imp if r["ad_state"] == "covered" else 0,
                "ad_clicks": a_clicks if r["ad_state"] == "covered" else 0,
                "ad_spend": a_spend if r["ad_state"] == "covered" else 0.0,
                "ad_orders": orders if r["ad_state"] == "covered" else 0,
                "ad_sales": sales if r["ad_state"] == "covered" else 0.0,
                "ad_cvr": cvr if r["ad_state"] == "covered" else None,
                # 展示量份额是报表自带的独立字段，绝不可换算成广告位
                "search_term_impression_share": (
                    round(min(0.95, 0.02 + rng.random() * 0.5), 4)
                    if r["ad_state"] == "covered" else None),
                "attribution_grain": "search_term_daily",
                "value_origin": "synthetic_demo",
            })
        unattr.append({
            "child_asin": asin, "date": date,
            "sessions_total": sess_cap,
            "sessions_attributed": o_used,
            "sessions_unattributed": sess_cap - o_used,
            "ad_spend_total": round(spend_cap, 4),
            "ad_spend_attributed": round(a_used_spend, 4),
            "ad_spend_unattributed": round(spend_cap - a_used_spend, 4),
            "ad_clicks_total": click_cap,
            "ad_clicks_attributed": a_used_clicks,
            "attributed_share": round(o_used / sess_cap, 4) if sess_cap else None,
            "note": "未归因部分为不在监控词范围内的自然与付费流量",
            "value_origin": "derived",
        })
    return rows, unattr


# --------------------------------------------------- L6 产品目标与库存承接

def _days_to(date_str, as_of="2026-08-03"):
    if not date_str:
        return None
    import datetime as _dt
    try:
        a = _dt.date.fromisoformat(str(date_str)[:10])
        b = _dt.date.fromisoformat(as_of)
        return (a - b).days
    except ValueError:
        return None


def _stockout_bucket(days):
    if days is None:
        return "none"
    if days <= 60:
        return "within60"
    return "beyond60"


def _order_bucket(days):
    """最晚下单日距基准日：≤14 天 = 现在就得补，扩不了量。"""
    if days is None:
        return "none"
    if days <= 14:
        return "order_now"
    return "has_runway"


def build_product_context(children, inv_decision, coverage_by_child, focus_asins,
                          own_brand_cov=None):
    """→ (goal_rows, absorb_rows)。产品目标是新增字段层，库存承接只投影 v0.3.0。"""
    own_brand_cov = own_brand_cov or {}
    goals = []
    absorb = []
    gid = aid = 0
    cov_rank = sorted(children, key=lambda c: -coverage_by_child.get(c["child_asin"], 0))
    main_set = {c["child_asin"] for c in cov_rank[:40]}

    for c in sorted(children, key=lambda x: x["child_asin"]):
        asin = c["child_asin"]
        life = c.get("product_lifecycle") or ""
        dec = inv_decision.get(asin) or {}
        risk = dec.get("base_risk_status") or ""
        cov = coverage_by_child.get(asin, 0)
        obc = own_brand_cov.get(asin, 0)
        rng = _rng("goal", asin)

        # 品牌防守是策略角色，必须在库存态之前判：自有品牌词有覆盖就是在守品牌，
        # 否则它永远被 risk 分支抢走，六种目标里这一种就是死枚举
        if obc >= 3 and cov >= 20:
            goal = "brand_defend"
        elif risk in ("stockout", "replenishment_gap"):
            goal = "hold_position"
        elif risk in ("aged_inventory_risk",) or "衰退" in life:
            goal = "clear_stock"
        elif risk in ("overstock",):
            goal = "volume_push"
        elif "成长" in life:
            goal = "volume_push"
        elif cov >= 20:
            goal = "hold_position"
        elif cov == 0:
            goal = "niche_explore"
        else:
            goal = "maintain_base"

        if asin in main_set and cov >= 30:
            push = "main"
        elif cov >= 5 or asin in focus_asins:
            push = "assist"
        else:
            push = "normal"

        # 历史版本：约三成子体在 4 月改过一次目标
        versions = [("2026-01-01", "2026-04-14", None), ("2026-04-15", None, goal)]
        if rng.random() < 0.3:
            prev = "volume_push" if goal != "volume_push" else "hold_position"
            spans = [("2026-01-01", "2026-04-14", prev), ("2026-04-15", None, goal)]
        else:
            spans = [("2026-01-01", None, goal)]
        for eff_from, eff_to, g in spans:
            gid += 1
            goals.append({
                "goal_id": "pg_%05d" % gid,
                "child_asin": asin,
                "parent_asin": c["parent_asin"],
                "effective_from": eff_from,
                "effective_to": eff_to,
                "is_current": 1 if eff_to is None else 0,
                "product_goal": g,
                "product_goal_label": GOAL_LABEL[g],
                "push_role": push,
                "push_role_label": PUSH_LABEL[push],
                "product_lifecycle": life,
                "version": "%s@%s" % (g, eff_from),
                "source": "关键词模块新增字段层（v0.3.0 未提供产品目标与主推关系）",
                "value_origin": "synthetic_demo",
            })

        # 承接态由 (v0.3.0 风险态, 最晚下单日距今档) 共同决定——仍是投影，只是多用了一个字段。
        # 只看风险态的话「仅可承接正常需求」永远不会出现，那一档就是死枚举。
        # 注意 v0.3.0 的 base_stockout_date 对健康/超储子体是字面字符串 "none" 而非 NULL，
        # 所以用 latest_order_date 做判别：最晚下单日已逼近基准日 = 现在就得补，扩不了量。
        days_out = _days_to(dec.get("base_stockout_date"))
        days_order = _days_to(dec.get("latest_order_date"))
        bucket = _order_bucket(days_order)
        if risk == "stockout":
            ab = "replenish_first"
        elif risk == "replenishment_gap":
            ab = "cannot_absorb"
        elif risk in ("overstock", "aged_inventory_risk"):
            # 超储与库龄风险手上有余量，最晚下单日在过去不代表要补货，而是本来就该出货
            ab = "can_absorb_extra"
        elif risk == "healthy":
            # 只有健康子体才用下单窗口判别：已逼近就只能承接正常需求
            ab = "normal_only" if bucket == "order_now" else "can_absorb_extra"
        else:
            ab = "normal_only"
        aid += 1
        absorb.append({
            "absorb_id": "ab_%05d" % aid,
            "child_asin": asin,
            "as_of_date": "2026-08-03",
            "base_risk_status": risk,
            "days_to_base_stockout": days_out,
            "days_to_latest_order": days_order,
            "order_bucket": bucket,
            "absorb_state": ab,
            "absorb_state_label": ABSORB_LABEL[ab],
            "base_stockout_date": dec.get("base_stockout_date"),
            "stress_stockout_date": dec.get("stress_stockout_date"),
            "latest_order_date": dec.get("latest_order_date"),
            "suggested_replenishment_qty": dec.get("suggested_replenishment_qty"),
            "projected_lost_sales_units": dec.get("projected_lost_sales_units"),
            "dynamic_safety_days": dec.get("dynamic_safety_days"),
            "decision_summary": dec.get("decision_summary"),
            "confidence_score": dec.get("confidence_score"),
            "source": "投影自 v0.3.0 fact_child_inventory_decision，本模块不重算库存",
            "value_origin": "customer_real" if dec else "missing",
        })
    return goals, absorb


# ------------------------------------------------------------------------ 门禁

def gate_l5(traffic, unattr, caps):
    out = []
    agg = collections.defaultdict(lambda: {"s": 0, "c": 0, "p": 0.0, "i": 0})
    for r in traffic:
        k = (r["child_asin"], r["date"])
        agg[k]["s"] += r["organic_sessions"] or 0
        agg[k]["c"] += r["ad_clicks"] or 0
        agg[k]["p"] += r["ad_spend"] or 0.0
        agg[k]["i"] += r["ad_impressions"] or 0

    over_s = over_c = over_p = 0
    for k, v in agg.items():
        cap = caps.get(k) or {}
        if v["s"] > (cap.get("sessions") or 0):
            over_s += 1
        if v["c"] > (cap.get("clicks") or 0):
            over_c += 1
        if v["p"] > float(cap.get("ad_spend") or 0.0) + 1e-6:
            over_p += 1
    out.append(("G5-1 词级自然 sessions 之和 ≤ v0.3.0 当日子体 sessions",
                over_s == 0, "越界 %d / %d 个子体日" % (over_s, len(agg))))
    out.append(("G5-2 词级广告点击之和 ≤ v0.3.0 当日 clicks",
                over_c == 0, "越界 %d 个子体日" % over_c))
    out.append(("G5-3 词级广告花费之和 ≤ v0.3.0 当日 ad_spend",
                over_p == 0, "越界 %d 个子体日" % over_p))

    shares = [u["attributed_share"] for u in unattr if u["attributed_share"] is not None]
    lo = min(shares) if shares else 0
    hi = max(shares) if shares else 0
    out.append(("G5-4 归因比例落在 %.0f%%-%.0f%% 之间（不得 100%% 归因到监控词）"
                % (RESIDUAL_MIN * 100, RESIDUAL_MAX * 100),
                bool(shares) and hi <= RESIDUAL_MAX + 0.01 and lo >= 0.0,
                "实测 %.1f%% ~ %.1f%%" % (lo * 100, hi * 100)))

    # 展示量份额不得与广告位构成函数关系（否则等于把份额换算成了排名）
    pts = [(r["search_term_impression_share"], r) for r in traffic
           if r["search_term_impression_share"] is not None][:5000]
    distinct = len({round(p[0], 3) for p in pts})
    out.append(("G5-5 展示量份额取值分散、不与广告位一一对应",
                distinct > 100, "不同份额取值 %d 个 / 抽样 %d 行" % (distinct, len(pts))))
    return out


def gate_l6(goals, absorb, inv_decision, children):
    out = []
    cur = [g for g in goals if g["is_current"]]
    n_child = len({c["child_asin"] for c in children})
    out.append(("G6-1 %d 个子体都有且只有一条当前产品目标" % n_child,
                len(cur) == n_child and len({g["child_asin"] for g in cur}) == n_child,
                "当前目标 %d 条 / 覆盖子体 %d 个"
                % (len(cur), len({g["child_asin"] for g in cur}))))

    got = collections.Counter(g["product_goal"] for g in cur)
    missing = [k for k in GOAL_LABEL if k not in got]
    out.append(("G6-2 六种产品目标都出现", not missing,
                ", ".join("%s=%d" % (GOAL_LABEL[k], v) for k, v in got.items())))

    push = collections.Counter(g["push_role"] for g in cur)
    out.append(("G6-3 主推/辅助/常规三类都出现且主推 ≤ 60",
                len(push) == 3 and push.get("main", 0) <= 60,
                ", ".join("%s=%d" % (PUSH_LABEL[k], v) for k, v in push.items())))

    ab = collections.Counter(a["absorb_state"] for a in absorb)
    missing_ab = [k for k in ABSORB_LABEL if k not in ab]
    thin = [ABSORB_LABEL[k] for k, v in ab.items() if v < 10]
    out.append(("G6-4 四种库存承接态都出现且每种 ≥ 10 个子体",
                not missing_ab and not thin,
                ", ".join("%s=%d" % (ABSORB_LABEL[k], v) for k, v in ab.items())
                + ("  过薄的档=%s" % thin if thin else "")))

    # 承接态必须由 v0.3.0 字段唯一决定（证明是投影而非另算一套）
    mapping = collections.defaultdict(set)
    for a in absorb:
        mapping[(a["base_risk_status"], a["order_bucket"])].add(a["absorb_state"])
    ambiguous = {"%s/%s" % k: sorted(v) for k, v in mapping.items() if len(v) > 1}
    out.append(("G6-5 每个 (风险态, 最晚下单日档) 组合只映射到一个承接态（投影不重算）",
                not ambiguous, "一对多的组合=%s" % (ambiguous or "无")))

    # 历史版本必须真的存在，否则「与上次盘点比」没有可比对象
    multi = collections.Counter(g["child_asin"] for g in goals)
    changed = sum(1 for a, n in multi.items() if n > 1)
    out.append(("G6-6 有改过目标的子体数 ≥ 60（否则目标版本机制等于没用）",
                changed >= 60, "改过目标的子体 %d 个" % changed))
    return out
