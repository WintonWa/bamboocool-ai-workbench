"""关键词模块计算层：依赖参数的计算全在这里，每次请求重算。

判断层边界（沿用产品模块 B 方案）：
  读判断层结果 —— fact_keyword_evidence 的定性与文案、两张事件表的类型与连续性
  页面自算     —— 覆盖结构统计、位置变化聚合、词组汇总（按 dedup_weight）、
                  优先级重排、缺口清单（监控词集 − 已覆盖）

载荷纪律：内部码值不出现在返回值里。complete / partial / missing / value_origin
这些词在门禁禁词表内，所以只传已映射好的中文标签与 6.6 的性质/状态词。
"""

from __future__ import annotations

import collections
import json
from typing import Any

from . import data

# 6.6 数据性质：库里的 direct/derived/constructed 在读取边界换成中文
_NATURE = {"direct": "真实", "derived": "推导", "constructed": "模拟"}


def _nature(origins) -> str:
    s = {o for o in origins if o}
    if not s:
        return "模拟"
    if len(s) > 1:
        return "混合"
    return _NATURE.get(next(iter(s)), "模拟")


def _absorb_sentence(absorb) -> str | None:
    """库存承接的一句话说明，用已映射的中文标签 + 数字重拼。

    绝不上屏 v0.3.0 的 decision_summary 原文：它是产品模块的内部话，里面混着英文
    枚举（「基准场景出现replenishment_gap；建议补货2531件…」），直接显示就是
    枚举码泄漏，G9 / G17 都会红。
    """
    if not absorb:
        return None
    parts = [absorb.get("absorb_state_label") or ""]
    qty = absorb.get("suggested_replenishment_qty")
    if qty:
        parts.append("建议补货 %s 件" % "{:,}".format(int(qty)))
    lo = absorb.get("latest_order_date")
    days = absorb.get("days_to_latest_order")
    if lo:
        if days is not None and days < 0:
            parts.append("最晚下单日 %s 已过 %d 天" % (lo, -days))
        elif days is not None:
            parts.append("最晚下单日 %s，还有 %d 天" % (lo, days))
        else:
            parts.append("最晚下单日 %s" % lo)
    lost = absorb.get("projected_lost_sales_units")
    if lost:
        parts.append("按当前节奏预计少卖 %s 件" % "{:,}".format(int(lost)))
    return "；".join(p for p in parts if p) or None


def _pct(a: float, b: float) -> float | None:
    return round(a / b, 4) if b else None


# ------------------------------------------------- 板块一：子体与当前产品上下文

def _context(con, asin: str, pairs: list[dict]) -> dict[str, Any]:
    ident = data.child_identity(con, asin)
    goals = data.child_goal(con, asin)
    absorb = data.child_absorb(con, asin)
    cur = next((g for g in goals if g["is_current"]), None)
    prev = [g for g in goals if not g["is_current"]]

    anchored = sum(1 for p in pairs if p["anchor_band"])
    nature = _nature(p["value_origin"] for p in pairs)

    # 目标或库存缺失时仍出事实，但要明说停在哪里（方案 7.3 §5.3）
    blocked = []
    if not cur:
        blocked.append("当前产品目标未设定，暂不形成产品级机会结论")
    if not absorb:
        blocked.append("库存承接结果缺失，暂不判断能否扩量")

    return {
        "child_asin": asin,
        "parent_asin": ident["parent_asin"] if ident else None,
        "product_name": ident["product_name"] if ident else None,
        "style_no": ident["style_no"] if ident else None,
        "colorway": ident["colorway"] if ident else None,
        "size": ident["size"] if ident else None,
        "combination": ident["combination"] if ident else None,
        "category_rank": ident["category_rank"] if ident else None,
        "rating": ident["rating"] if ident else None,
        "lifecycle": (cur or {}).get("product_lifecycle")
                     or (ident or {}).get("product_lifecycle"),
        "product_goal_label": (cur or {}).get("product_goal_label"),
        "push_role_label": (cur or {}).get("push_role_label"),
        "goal_effective_from": (cur or {}).get("effective_from"),
        "goal_history": [
            {"product_goal_label": g["product_goal_label"],
             "from": g["effective_from"], "to": g["effective_to"]}
            for g in prev],
        "absorb_state_label": (absorb or {}).get("absorb_state_label"),
        "absorb_detail": _absorb_sentence(absorb),
        "latest_order_date": (absorb or {}).get("latest_order_date"),
        "days_to_latest_order": (absorb or {}).get("days_to_latest_order"),
        "pair_count": len(pairs),
        "anchored_count": anchored,
        "nature": nature,
        "condition": "正常" if not blocked else "待确认",
        "blocked_reasons": blocked,
    }


# ------------------------------------------------------- 板块二：关键词覆盖结构

def _coverage(con, asin: str, pairs: list[dict], rp: dict) -> dict[str, Any]:
    """按需求词组分组统计覆盖与缺口。搜索量按 dedup_weight 分权（可关）。"""
    grows = data.child_groups(con, asin)
    totals = {g["group_id"]: g for g in data.group_monitored_totals(con)}
    by_pair = {p["pair_id"]: p for p in pairs}
    dedup = bool(rp["group_dedup"])
    depth = int(rp["collect_depth"])

    # 采集深度同样作用在末日截面上，否则覆盖结构和位置板块会各说一套
    for p in pairs:
        if p["organic_state"] == "covered" and p["organic_rank"] \
                and p["organic_rank"] > depth:
            p["organic_state"] = "beyond_depth"
            p["organic_rank"] = None
            p["coverage_state"] = ("ad_only" if p["ad_state"] == "covered"
                                   else "unconfirmed")

    agg: dict[str, dict] = {}
    for r in grows:
        p = by_pair.get(r["pair_id"])
        if not p:
            continue
        g = agg.setdefault(r["group_id"], {
            "group_id": r["group_id"], "group_name": r["group_name"],
            "demand_dimension": r["demand_dimension"],
            "covered_organic": 0.0, "covered_ad": 0.0, "covered_both": 0.0,
            "unconfirmed": 0.0, "related": 0.0, "search_volume": 0.0,
        })
        w = r["dedup_weight"] if dedup else 1.0
        g["related"] += w
        g["search_volume"] += (p["monthly_search_volume"] or 0) * w
        if p["organic_state"] == "covered":
            g["covered_organic"] += w
        if p["ad_state"] == "covered":
            g["covered_ad"] += w
        if p["coverage_state"] == "both":
            g["covered_both"] += w
        if p["coverage_state"] == "unconfirmed":
            g["unconfirmed"] += w

    out = []
    for gid, g in agg.items():
        t = totals.get(gid, {})
        monitored = (t.get("weighted_count") if dedup else t.get("monitored_count")) or 0
        gap = max(0.0, monitored - g["related"])
        out.append({
            "group_name": g["group_name"],
            "demand_dimension": g["demand_dimension"],
            "monitored_in_group": round(monitored, 2),
            "related_here": round(g["related"], 2),
            "organic_covered": round(g["covered_organic"], 2),
            "ad_covered": round(g["covered_ad"], 2),
            "both_covered": round(g["covered_both"], 2),
            "unconfirmed": round(g["unconfirmed"], 2),
            "gap": round(gap, 2),
            # 组内覆盖率 = 本子体相关 ÷ 组内监控词。
            # 不用「自然覆盖 ÷ 本子体相关」：那个在锚点齐全的子体上恒为 100%，整列没信息量。
            "group_reach": _pct(g["related"], monitored),
            "organic_rate": _pct(g["covered_organic"], g["related"]),
            "search_volume": int(g["search_volume"]),
        })
    out.sort(key=lambda x: (-x["gap"], -x["search_volume"]))

    # 自然与广告分别判断：只有广告流量不代表已形成自然覆盖（方案 7.3 §5.4）
    n_o = sum(1 for p in pairs if p["organic_state"] == "covered")
    n_a = sum(1 for p in pairs if p["ad_state"] == "covered")
    n_b = sum(1 for p in pairs if p["coverage_state"] == "both")
    ad_only = sum(1 for p in pairs if p["coverage_state"] == "ad_only")
    organic_only = sum(1 for p in pairs if p["coverage_state"] == "organic_only")
    none = sum(1 for p in pairs if p["coverage_state"] == "none")
    weak = sum(1 for p in pairs
               if p["organic_state"] == "covered"
               and (p["organic_rank"] or 999) > rp["weak_rank"])

    return {
        "summary": {
            "related": len(pairs),
            "organic_covered": n_o,
            "ad_covered": n_a,
            "both_covered": n_b,
            "ad_only": ad_only,
            "organic_only": organic_only,
            "not_covered": none,
            "weak_position": weak,
            "weak_rank_threshold": rp["weak_rank"],
        },
        "dedup_applied": dedup,
        "groups": out,
        "condition": "正常" if pairs else "空结果",
    }


# --------------------------------------------- 板块三：自然位与广告位变化

def _positions(con, asin: str, pairs: list[dict], rp: dict) -> dict[str, Any]:
    series = data.child_position_series(con, asin)
    fails = set(data.collect_fail_dates(con))
    lab = data.labels()
    state_lab = lab.get("position_state", {})

    # 采集深度是页面口径而不是库里的定值：数据层按 144 落的库，运营把它压到 48 时
    # 超过 48 的位次就该读成「超出采集深度」而不是「有排名」。原来这个参数只回显
    # 不参与计算，调它整页一字不变，等于一个不会动的旋钮。
    depth = int(rp["collect_depth"])
    for r in series:
        if r["organic_state"] == "covered" and r["organic_rank"] \
                and r["organic_rank"] > depth:
            r["organic_state"] = "beyond_depth"
            r["organic_rank"] = None
            if r["coverage_state"] == "both":
                r["coverage_state"] = "ad_only"
            elif r["coverage_state"] == "organic_only":
                r["coverage_state"] = "unconfirmed"

    dates = sorted({r["date"] for r in series})
    by_pair: dict[str, list[dict]] = collections.defaultdict(list)
    for r in series:
        by_pair[r["pair_id"]].append(r)

    # 每日五态计数 —— 位置图的背景带靠它画，不逐对画点
    daily = []
    per_date = collections.defaultdict(collections.Counter)
    rank_sum = collections.Counter()
    rank_n = collections.Counter()
    for r in series:
        per_date[r["date"]][r["organic_state"]] += 1
        if r["organic_rank"]:
            rank_sum[r["date"]] += r["organic_rank"]
            rank_n[r["date"]] += 1
    for d in dates:
        c = per_date[d]
        daily.append({
            "date": d,
            "covered": c.get("covered", 0),
            "not_covered": c.get("not_covered", 0),
            "beyond_depth": c.get("beyond_depth", 0),
            "collect_failed": c.get("collect_failed", 0),
            "not_monitored": c.get("not_monitored", 0),
            "avg_organic_rank": (round(rank_sum[d] / rank_n[d], 1)
                                 if rank_n[d] else None),
            "is_collect_fail_day": d in fails,
        })

    # 逐词轨迹：只给有排名的点，缺口段前端按 date 对齐留空
    tracks = []
    name_of = {p["pair_id"]: p for p in pairs}
    for pid, rs in by_pair.items():
        p = name_of.get(pid)
        if not p:
            continue
        pts = [{"date": r["date"], "organic": r["organic_rank"], "ad": r["ad_rank"],
                "state": r["organic_state"]} for r in rs]
        ranks = [x["organic"] for x in pts if x["organic"]]
        streak = _down_streak([x["organic"] for x in pts])
        tracks.append({
            "pair_id": pid,
            "keyword": p["keyword"],
            "operator_role_label": p["operator_role_label"],
            "is_core": p["operator_role"] == "core",
            "anchor_band_label": p["anchor_band_label"],
            "monitor_from": p["monitor_from"],
            "current_organic": p["organic_rank"],
            "current_ad": p["ad_rank"],
            "current_state_label": state_lab.get(p["organic_state"], p["organic_state"]),
            "best_rank": min(ranks) if ranks else None,
            "worst_rank": max(ranks) if ranks else None,
            "down_streak_days": streak,
            "is_continuous_decline": streak >= rp["streak_days"],
            "points": _thin(pts),
        })
    tracks.sort(key=lambda t: (not t["is_core"], -(t["down_streak_days"] or 0),
                               t["keyword"]))

    events = data.child_coverage_events(con, asin)
    ev_counts = collections.Counter(e["event_type_label"] for e in events)
    big = [e for e in events
           if e["from_rank"] and e["to_rank"]
           and abs(e["to_rank"] - e["from_rank"]) >= rp["rank_shift"]]

    return {
        "date_from": dates[0] if dates else None,
        "date_to": dates[-1] if dates else None,
        "collect_depth": rp["collect_depth"],
        "collect_fail_days": sorted(d for d in fails if d in set(dates)),
        "daily": daily,
        "tracks": tracks,
        "state_legend": [{"code_label": v} for v in state_lab.values()],
        "event_counts": [{"name": k, "n": v} for k, v in ev_counts.most_common()],
        "events": events[:60],
        "significant_events": len(big),
        "rank_shift_threshold": rp["rank_shift"],
        "market_events": data.child_market_events(con, asin)[:20],
        "condition": "正常" if dates else "空结果",
    }


def _down_streak(ranks: list) -> int:
    """最长连续变差天数，先做 7 天移动均值再判单调。

    直接对逐日位次判严格单调是取不到的：位次每天有抖动，连续 7 天不回头几乎不可能，
    实测主演示对象 66 条轨迹里「连续下滑」恒为 0，而事件表同期有 24 条自然位下降 ——
    参数 streak_days 就成了永远取不到的那一档。平滑掉抖动、保留趋势才判得出来。
    """
    vals = [r for r in ranks if r is not None]
    if len(vals) < 14:
        return 0
    win = 7
    ma = [sum(vals[i:i + win]) / win for i in range(len(vals) - win + 1)]
    best = cur = 0
    for a, b in zip(ma, ma[1:]):
        if b > a:                      # 位次数字变大 = 位置变差
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def _thin(points: list, keep: int = 46) -> list:
    """轨迹降采样：保留首末、状态变化点、以及等距抽样点。

    不裁的话单子体载荷 66 轨迹 × 182 天 ≈ 946 KB，前端图上根本画不了那么密。
    """
    if len(points) <= keep:
        return points
    idx = {0, len(points) - 1}
    prev = None
    for i, p in enumerate(points):
        if p["state"] != prev:
            idx.add(i)
            prev = p["state"]
    step = max(1, len(points) // keep)
    idx.update(range(0, len(points), step))
    return [points[i] for i in sorted(idx)]


# ------------------------------------------- 板块四：缺口、机会与风险（读判断层）

_PRIORITY_BUMP = {"主推": 1.0, "辅助": 0.5, "常规": 0.0}


def _evidence(con, asin: str, rp: dict) -> dict[str, Any]:
    rows = data.child_evidence(con, asin)
    w = rp["weights"]
    comp_score = {"证据完整": 1.0, "证据部分可用": 0.5, "证据不足": 0.0}

    for r in rows:
        for k in ("ref_market_event_ids", "ref_coverage_event_ids"):
            if isinstance(r.get(k), str):
                try:
                    r[k] = json.loads(r[k])
                except (TypeError, ValueError):
                    r[k] = []
        # 优先级重排：证据自带 priority 只作默认序，权重由参数面板给
        base = (7 - (r["priority"] or 6)) / 6.0
        r["rank_score"] = round(
            w["w_demand"] * base
            + w["w_change"] * base
            + w["w_push"] * _PRIORITY_BUMP.get(r.get("push_role_label") or "", 0.0)
            + w["w_evidence"] * comp_score.get(
                r.get("evidence_completeness_label") or "", 0.0), 4)
    rows.sort(key=lambda r: (-r["rank_score"], r["priority"], r["evidence_id"]))

    counts = collections.Counter(r["evidence_type_label"] for r in rows)
    return {
        "total": len(rows),
        "type_counts": [{"name": k, "n": v} for k, v in counts.most_common()],
        "weights": w,
        "items": rows,
        "condition": "正常" if rows else "空结果",
    }


# ----------------------------------------------------- 板块五：盘点记录

def _audits(con, asin: str) -> dict[str, Any]:
    rows = data.child_audits(con, asin)
    for r in rows:
        if isinstance(r.get("evidence_type_counts"), str):
            try:
                r["evidence_type_counts"] = json.loads(r["evidence_type_counts"])
            except (TypeError, ValueError):
                r["evidence_type_counts"] = {}
    # 「与上次比」的差值由页面算，不落库
    for prev, cur in zip(rows, rows[1:]):
        cur["delta"] = {
            "organic_covered": cur["organic_covered_count"] - prev["organic_covered_count"],
            "ad_covered": cur["ad_covered_count"] - prev["ad_covered_count"],
            "median_organic_rank": (
                (cur["median_organic_rank"] - prev["median_organic_rank"])
                if (cur["median_organic_rank"] and prev["median_organic_rank"]) else None),
            "unconfirmed": cur["unconfirmed_count"] - prev["unconfirmed_count"],
        }
    return {"runs": rows, "condition": "正常" if rows else "空结果"}


# ------------------------------------------------------------------ 装配入口

def child_page(con, asin: str, rp: dict) -> dict[str, Any] | None:
    pairs = data.child_pairs(con, asin)
    if not pairs:
        return None
    return {
        "child_asin": asin,
        "as_of": data.scope().get("as_of_date"),
        "judgment_object": "关键词 × 子ASIN × 当前产品目标",
        "context": _context(con, asin, pairs),
        "coverage": _coverage(con, asin, pairs, rp),
        "positions": _positions(con, asin, pairs, rp),
        "evidence": _evidence(con, asin, rp),
        "audits": _audits(con, asin),
        "condition": "正常",
    }


# ========================================================== 页面二：词库与深研

def library_page(con, rp: dict, flt: dict) -> dict[str, Any]:
    """词库范围与质量 + 需求词组结构 + 市场关键词比较区。"""
    statuses = flt.get("status") and [flt["status"]] or rp.get("library_status")
    terms, total = data.term_list(
        con, statuses=statuses, dimension=flt.get("dimension"),
        role=flt.get("role"), q=flt.get("q"), limit=int(flt.get("limit") or 200))

    # 两来源冲突：同一个词、同一期，两份文件的数不一样。冲突保留不合并（能力三）
    for t in terms:
        conflicts = []
        for label, a, b in (("在售商品数", t["product_count"], t["alt_product_count"]),
                            ("广告竞品数", t["ad_competitor_count"],
                             t["alt_ad_competitor_count"]),
                            ("头部点击占比", t["click_share_top3"],
                             t["alt_click_share_top3"])):
            if a is not None and b is not None and a != b:
                conflicts.append(label)
        t["conflict_fields"] = conflicts
        t["has_conflict"] = bool(conflicts)

    groups = data.group_structure(con)
    dedup = bool(rp["group_dedup"])
    for g in groups:
        g["search_volume"] = int(g["search_weighted"] if dedup else g["search_raw"])
        g["double_count"] = int((g["search_raw"] or 0) - (g["search_weighted"] or 0))
    summary = data.library_summary(con)
    dist = data.distributions()
    return {
        "as_of": data.scope().get("as_of_date"),
        "judgment_object": "市场关键词（未绑定子体时只出市场事实）",
        "summary": summary,
        "library_status": dist["library_status"],
        "monitored_role": dist["monitored_role"],
        "brand_role": dist["brand_role"],
        "groups": groups,
        "dedup_applied": dedup,
        "total_matched": total,
        "shown": len(terms),
        "terms": terms,
        "conflict_terms": sum(1 for t in terms if t["has_conflict"]),
        "condition": "正常" if terms else "空结果",
    }


def _series(snaps: list[dict], ptype: str, source: str) -> list[dict]:
    return [s for s in snaps
            if s["period_type"] == ptype and s["source_code"] == source]


def term_page(con, keyword_id: str, rp: dict) -> dict[str, Any] | None:
    ident = data.term_identity(con, keyword_id)
    if not ident:
        return None
    snaps = data.term_snapshots(con, keyword_id)
    week = _series(snaps, "week", "kw3")
    month = _series(snaps, "month", "kw3")
    alt_week = _series(snaps, "week", "kw2")
    alt_month = _series(snaps, "month", "kw2")

    # 两来源末期并列。绝不合并成一个数，也绝不把月搜索量折算成周（方案 §6.3）
    cur_w = week[-1] if week else {}
    cur_m = month[-1] if month else {}
    alt_w = alt_week[-1] if alt_week else {}
    alt_m = alt_month[-1] if alt_month else {}
    compare = []
    for label, key, src in (
            ("月搜索量", "monthly_search_volume", (cur_m, alt_m)),
            ("月购买量", "monthly_purchase_volume", (cur_m, alt_m)),
            ("购买率", "purchase_rate", (cur_m, alt_m)),
            ("ABA 周排名", "aba_week_rank", (cur_w, alt_w)),
            ("在售商品数", "product_count", (cur_w, alt_w)),
            ("需供比", "demand_supply_ratio", (cur_w, alt_w)),
            ("广告竞品数", "ad_competitor_count", (cur_w, alt_w)),
            ("头部三名点击占比", "click_share_top3", (cur_w, alt_w)),
            ("PPC 竞价", "ppc_bid", (cur_w, alt_w)),
    ):
        a, b = src[0].get(key), src[1].get(key)
        compare.append({"metric": label, "primary": a, "second": b,
                        "conflict": (a is not None and b is not None and a != b)})

    heads = data.term_head_asins(con, keyword_id)
    last_end = max((h["period_end"] for h in heads), default=None)
    head_now = [h for h in heads if h["period_end"] == last_end]
    slot1 = [(h["period_end"], h["asin"]) for h in heads if h["rank_slot"] == 1]
    replaced = len({a for _, a in slot1}) > 1

    rels = data.term_child_relations(con, keyword_id)
    lab = data.labels().get("position_state", {})
    for r in rels:
        r["organic_state_label"] = lab.get(r["organic_state"], r["organic_state"])
        r["weak"] = bool(r["organic_rank"] and r["organic_rank"] > rp["weak_rank"])

    ev = data.term_evidence(con, keyword_id)
    unclear = [s for s in week if not s["comparable_flag"] and s["period_index"] > 0]

    return {
        "keyword_id": keyword_id,
        "as_of": data.scope().get("as_of_date"),
        "judgment_object": "关键词 × 子ASIN × 当前产品目标"
                           if rels else "市场关键词（尚未绑定子体）",
        "identity": ident,
        "nature": _nature([ident.get("value_origin")]),
        "aliases": data.term_aliases(con, keyword_id),
        "groups": data.term_groups(con, keyword_id),
        "attributes": data.term_attributes(con, keyword_id),
        "series": {
            "week": [_slim_week(s) for s in week],
            "month": [_slim_month(s) for s in month],
            "week_measure": cur_w.get("measure_definition"),
            "month_measure": cur_m.get("measure_definition"),
            "not_comparable": [{"period_end": s["period_end"],
                                "reason": s["comparable_block_reason"]}
                               for s in unclear],
        },
        "compare": compare,
        "second_source_note": (alt_w.get("comparable_block_reason")
                               or alt_m.get("comparable_block_reason")),
        "conflict_count": sum(1 for c in compare if c["conflict"]),
        "head_asins": head_now,
        "head_replaced": replaced,
        "head_slot1_history": slot1,
        "own_in_head": sum(1 for h in head_now if h["is_own_asin"]),
        "market_events": data.term_market_events(con, keyword_id),
        "relations": rels,
        "evidence": ev,
        "condition": "正常",
    }


def _slim_week(s: dict) -> dict:
    return {"period_end": s["period_end"], "aba_week_rank": s["aba_week_rank"],
            "product_count": s["product_count"],
            "ad_competitor_count": s["ad_competitor_count"],
            "demand_supply_ratio": s["demand_supply_ratio"],
            "ppc_bid": s["ppc_bid"], "click_share_top3": s["click_share_top3"],
            "state": s["data_state_label"], "comparable": s["comparable_flag"],
            "nature": _NATURE.get(s["value_origin"], "模拟")}


def _slim_month(s: dict) -> dict:
    return {"period_end": s["period_end"],
            "monthly_search_volume": s["monthly_search_volume"],
            "monthly_purchase_volume": s["monthly_purchase_volume"],
            "purchase_rate": s["purchase_rate"],
            "aba_month_rank": s["aba_month_rank"],
            "state": s["data_state_label"], "comparable": s["comparable_flag"],
            "nature": _NATURE.get(s["value_origin"], "模拟")}


# ========================================================== 页面一：动态与总览

_UP = {"demand_up"}
_DOWN = {"demand_down"}


def _group_changes(con, rp: dict) -> dict[str, Any]:
    """市场需求与词组变化：把单词变化重新组织到需求词组里。

    搜索量按 dedup_weight 分权，否则属于多组的词在每个组里各算一次。
    """
    rows_ = data.market_events_by_group(con)
    dedup = bool(rp["group_dedup"])
    agg: dict[str, dict] = {}
    for r in rows_:
        g = agg.setdefault(r["group_id"], {
            "group_name": r["group_name"], "demand_dimension": r["demand_dimension"],
            "up": 0, "down": 0, "competition": 0, "unclear": 0,
            "continuous": 0, "single": 0,
            "search_moved": 0.0, "terms": set(), "samples": [],
        })
        w = r["dedup_weight"] if dedup else 1.0
        et = r["event_type"]
        if et in _UP:
            g["up"] += 1
        elif et in _DOWN:
            g["down"] += 1
        elif et == "competition_up":
            g["competition"] += 1
        else:
            g["unclear"] += 1
        if r["continuity"] == "continuous":
            g["continuous"] += 1
        elif r["continuity"] == "single_period":
            g["single"] += 1
        g["terms"].add(r["keyword"])
        g["search_moved"] += (r["monthly_search_volume"] or 0) * w
        if len(g["samples"]) < 3 and et in (_UP | _DOWN | {"competition_up"}):
            g["samples"].append({"keyword": r["keyword"], "label": r["label"],
                                 "event_type_label": r["event_type_label"],
                                 "continuity_label": r["continuity_label"]})

    out = []
    for g in agg.values():
        out.append({
            "group_name": g["group_name"], "demand_dimension": g["demand_dimension"],
            "term_count": len(g["terms"]),
            "up": g["up"], "down": g["down"], "competition": g["competition"],
            "unclear": g["unclear"],
            "continuous": g["continuous"], "single_period": g["single"],
            "net": g["up"] - g["down"],
            "search_moved": int(g["search_moved"]),
            "samples": g["samples"],
        })
    out.sort(key=lambda x: -x["search_moved"])
    total = {
        "up": sum(x["up"] for x in out), "down": sum(x["down"] for x in out),
        "competition": sum(x["competition"] for x in out),
        "unclear": sum(x["unclear"] for x in out),
        "continuous": sum(x["continuous"] for x in out),
        "single_period": sum(x["single_period"] for x in out),
        "groups_moved": len(out),
    }
    # 变化集中在少数词组还是散在各处 —— 这是「市场结构变了」和「单词波动」的分界
    top3 = sum(x["search_moved"] for x in out[:3])
    allv = sum(x["search_moved"] for x in out) or 1
    return {"groups": out, "totals": total, "dedup_applied": dedup,
            "top3_share": round(top3 / allv, 4)}


def _core_changes(con, rp: dict) -> dict[str, Any]:
    """自有核心词覆盖与位置变化。只陈述事实，位置涨跌不等于广告策略对错。"""
    evs = data.core_coverage_events(con)
    core = [e for e in evs if e["is_core_keyword"]]
    big = [e for e in core
           if e["from_rank"] and e["to_rank"]
           and abs(e["to_rank"] - e["from_rank"]) >= rp["rank_shift"]]
    by_type = collections.Counter(e["event_type_label"] for e in core)
    by_push = collections.Counter(e["push_role_label"] or "未定" for e in core)
    gained = [e for e in core if e["event_type"].endswith("_gained")]
    lost = [e for e in core if e["event_type"].endswith("_lost")]
    down = [e for e in core
            if e["event_type"] == "organic_down"
            and e["from_rank"] and e["to_rank"]]
    down.sort(key=lambda e: -((e["to_rank"] or 0) - (e["from_rank"] or 0)))
    # 按子体去重取样：organic_up/down 的汇总事件 to_date 全是末日，直接按日期倒排
    # 会让贡献最多关系对的那个子体（B0B3LWGP36，66 对）霸占整屏，
    # 看起来像「只有它在动」。这一屏要回答的是「变化涉及谁」，所以每子体最多两条。
    per_child = collections.Counter()
    sampled = []
    for e in core:
        if per_child[e["child_asin"]] >= 2:
            continue
        per_child[e["child_asin"]] += 1
        sampled.append(e)
        if len(sampled) >= 16:
            break
    return {
        "core_events": len(core),
        "all_events": len(evs),
        "significant": len(big),
        "rank_shift_threshold": rp["rank_shift"],
        "by_type": [{"name": k, "n": v} for k, v in by_type.most_common()],
        "by_push_role": [{"name": k, "n": v} for k, v in by_push.most_common()],
        "gained": len(gained), "lost": len(lost),
        "children_touched": len({e["child_asin"] for e in core}),
        "top_declines": down[:10],
        "recent": sampled,
        "sampled_children": len(per_child),
        "condition": "正常" if core else "空结果",
    }


def _priority_list(con, rp: dict) -> dict[str, Any]:
    """机会与风险优先列表：跨子体重排，只说先分析什么，不给广告动作。"""
    evs = data.evidence_all(con)
    w = rp["weights"]
    comp = {"证据完整": 1.0, "证据部分可用": 0.5, "证据不足": 0.0}
    push = {"主推": 1.0, "辅助": 0.5, "常规": 0.0}
    vols = [e["monthly_search_volume"] or 0 for e in evs]
    vmax = max(vols) if vols else 1
    for e in evs:
        base = (7 - (e["priority"] or 6)) / 6.0
        demand = (e["monthly_search_volume"] or 0) / (vmax or 1)
        e["rank_score"] = round(
            w["w_demand"] * demand
            + w["w_change"] * base
            + w["w_push"] * push.get(e["push_role_label"] or "", 0.0)
            + w["w_evidence"] * comp.get(e["evidence_completeness_label"] or "", 0.0), 4)
    evs.sort(key=lambda e: (-e["rank_score"], e["priority"], e["evidence_id"]))
    counts = collections.Counter(e["evidence_type_label"] for e in evs)
    nxt = collections.Counter(e["next_verification_label"] for e in evs)
    return {
        "total": len(evs),
        "type_counts": [{"name": k, "n": v} for k, v in counts.most_common()],
        "next_counts": [{"name": k, "n": v} for k, v in nxt.most_common()],
        "weights": w,
        "items": evs[:30],
        "condition": "正常" if evs else "空结果",
    }


_COMPARE_LAG = {"day": 1, "week": 7, "4week": 28}
_COMPARE_LABEL = {"day": "对比前一日", "week": "对比前一周", "4week": "对比前 4 周"}


def _recompare(reports: list[dict], compare: str) -> None:
    """按参数重算日报的环比，而不是用库里烘死的 traffic_proxy_delta。

    库里那一列是按前一日算的。原来这个参数只回显不参与计算，切到「对比前 4 周」
    整页一字不变 —— 一个不会动的旋钮比没有旋钮更糟。
    """
    lag = _COMPARE_LAG.get(compare, 1)
    by_date = {r["report_date"]: (r.get("traffic_proxy_value") or 0) for r in reports}
    ordered = sorted(by_date)
    idx = {d: i for i, d in enumerate(ordered)}
    for r in reports:
        i = idx.get(r["report_date"], 0)
        j = i - lag
        base = by_date[ordered[j]] if j >= 0 else None
        cur = r.get("traffic_proxy_value") or 0
        r["compare_period"] = _COMPARE_LABEL.get(compare, "对比前一日")
        r["compare_lag_days"] = lag
        r["compare_base_date"] = ordered[j] if j >= 0 else None
        r["compare_base_value"] = base
        r["traffic_proxy_delta"] = (round((cur - base) / base, 4)
                                    if base else None)
        # 窗口不够长时说清是「窗口内没有可比基期」，不是「没变化」
        r["compare_note"] = (None if base else
                            "本页只保留最近 %d 天，%d 天前不在窗口内" % (len(ordered), lag))


def overview_page(con, rp: dict, flt: dict) -> dict[str, Any]:
    reports = data.daily_reports(con, 14)
    for r in reports:
        for k in ("priority_evidence_ids", "coverage_event_ids"):
            if isinstance(r.get(k), str):
                try:
                    r[k] = json.loads(r[k])
                except (TypeError, ValueError):
                    r[k] = []
    _recompare(reports, rp["compare"])
    sc = data.scope()
    st = data.scope_status(con)
    win = data.window()
    blocked = []
    if st["children_with_relations"] < sc.get("focus_child_count", 0):
        blocked.append("关键词关系只覆盖 %d 个子体，其余子体本页不出结论"
                       % st["children_with_relations"])
    if st["not_comparable_terms"]:
        blocked.append("%d 个词本期口径变更，涨跌不计入比较"
                       % st["not_comparable_terms"])
    if st["insufficient_terms"]:
        blocked.append("%d 个词历史样本不足，只报当期事实"
                       % st["insufficient_terms"])
    return {
        "as_of": sc.get("as_of_date"),
        "judgment_object": "需求词组 / 自有核心词 / 关键词 × 子ASIN",
        "scope": {
            "site": sc.get("site"), "product_line": sc.get("product_line"),
            "library_terms": sc.get("library_keyword_count"),
            "monitored_terms": sc.get("monitored_keyword_count"),
            "focus_children": sc.get("focus_child_count"),
            "compare_period": rp["compare"],
            "week_window": [win["week_from"], win["week_to"]],
            "position_window": [win["position_from"], win["position_to"]],
            **st,
        },
        "blocked_reasons": blocked,
        "reports": reports,
        "group_changes": _group_changes(con, rp),
        "core_changes": _core_changes(con, rp),
        "priority": _priority_list(con, rp),
        "condition": "正常",
    }
