#!/usr/bin/env python3
"""L7 变化事件 / L8 证据与盘点记录 / L9 动态关键词日报。

L8 的结论文案是「判断层占位」：现在用确定性规则生成，将来由离线 Agent 替换。
所有上屏文案必须是中文成品，枚举码一律不出现在文案里（禁词扫描当门禁）。
"""
from __future__ import annotations

import collections
import datetime as dt
import hashlib
import random

import lib_l4 as L4
import lib_l56 as L56

RULE_VERSION = "keyword-demo-rules-v1"
AS_OF = "2026-08-03"
AUDIT_RUNS = ["2026-06-15", "2026-07-13", "2026-08-03"]
REPORT_DAYS = 14

MARKET_EVENT_LABEL = {
    "demand_up": "搜索需求上涨",
    "demand_down": "搜索需求下滑",
    "competition_up": "竞争加剧",
    "head_asin_replaced": "头部 ASIN 发生替换",
    "insufficient_history": "历史样本不足",
    "not_comparable": "口径变更导致不可比",
}
COVERAGE_EVENT_LABEL = {
    "organic_up": "自然位上涨",
    "organic_down": "自然位下降",
    "organic_gained": "新增自然覆盖",
    "organic_lost": "丢失自然覆盖",
    "ad_gained": "新增广告覆盖",
    "ad_lost": "丢失广告覆盖",
    "beyond_depth": "跌出采集深度",
    "collect_failed": "当日采集失败",
}
EVIDENCE_LABEL = {
    "market_opportunity": "市场需求机会",
    "coverage_gap": "产品覆盖缺口",
    "core_position_risk": "核心位置风险",
    "scene_longtail_signal": "场景与长尾信号",
    "inventory_limited": "库存受限机会",
    "pending_competitor_verification": "待竞品验证信号",
    "insufficient_data": "数据不足",
}
COMPLETENESS_LABEL = {"full": "证据完整", "partial": "证据部分可用", "insufficient": "证据不足"}
NEXT_LABEL = {"competitor": "进入竞品分析验证", "advertising": "进入广告决策处理",
              "observe": "继续观察一个周期"}
VERIFY_LABEL = {"verified": "竞品已验证", "pending": "待竞品验证",
                "not_supported": "竞品验证不成立", "na": "无需竞品验证"}

# 禁词：这些内部枚举码绝不允许出现在上屏文案里
FORBIDDEN_IN_TEXT = sorted(set(
    list(MARKET_EVENT_LABEL) + list(COVERAGE_EVENT_LABEL) + list(EVIDENCE_LABEL)
    + list(L56.GOAL_LABEL) + list(L56.ABSORB_LABEL) + list(L56.PUSH_LABEL)
    + ["organic_only", "ad_only", "both_stable", "not_covered", "beyond_depth",
       "collect_failed", "not_monitored", "unconfirmed", "customer_real",
       "synthetic_demo", "derived", "kw2", "kw3"]))


def _rng(*parts):
    h = hashlib.md5("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()
    return random.Random(int(h[:12], 16))


def _num(v):
    return "{:,}".format(int(v)) if v is not None else "—"


# ------------------------------------------------------------------ L7 变化事件

def build_market_events(snaps, kw_rows):
    kw_name = {r["keyword_id"]: r["keyword"] for r in kw_rows}
    kw_role = {r["keyword_id"]: r["operator_role_label"] for r in kw_rows}
    monitored = {r["keyword_id"] for r in kw_rows if r["is_monitored"]}

    by = collections.defaultdict(list)
    for r in snaps:
        if r["source_code"] == "kw3" and r["keyword_id"] in monitored:
            by[(r["keyword_id"], r["period_type"])].append(r)

    events = []
    eid = 0
    for (kid, ptype), rows in by.items():
        rows.sort(key=lambda r: r["period_index"])
        shape = rows[-1]["change_shape"]
        vol_f = "monthly_search_volume" if ptype == "month" else "aba_week_rank"

        if shape == "insufficient_history":
            first_ok = next((r for r in rows if r["data_state"] == "covered"), None)
            eid += 1
            events.append(_mk_event(eid, kid, kw_name, kw_role, rows[-1], first_ok,
                                    "insufficient_history", None, None, "insufficient",
                                    ptype))
            continue
        if shape == "not_comparable" and ptype == "week":
            b = next((r for r in rows if not r["comparable_flag"]
                      and r["period_index"] > 0), None)
            if b:
                prev = rows[b["period_index"] - 1]
                eid += 1
                events.append(_mk_event(eid, kid, kw_name, kw_role, b, prev,
                                        "not_comparable", None, None,
                                        "single_period", ptype))

        cov = [r for r in rows if r["data_state"] == "covered" and r.get(vol_f)]
        if len(cov) < 4:
            continue
        first, last = cov[0], cov[-1]
        if ptype == "month":
            v0, v1 = first[vol_f], last[vol_f]
            ratio = v1 / v0 if v0 else 1.0
            if ratio >= 1.25 or ratio <= 0.8:
                streak = _streak(cov, vol_f, up=ratio >= 1.25)
                eid += 1
                events.append(_mk_event(
                    eid, kid, kw_name, kw_role, last, first,
                    "demand_up" if ratio >= 1.25 else "demand_down", v0, v1,
                    "continuous" if streak >= 4 else "single_period", ptype))
        else:
            p0 = first.get("product_count")
            p1 = last.get("product_count")
            if p0 and p1 and p1 / p0 >= 1.15:
                eid += 1
                events.append(_mk_event(eid, kid, kw_name, kw_role, last, first,
                                        "competition_up", p0, p1, "continuous", ptype))
    return events


def _streak(cov, field, up):
    n = 0
    for a, b in zip(cov, cov[1:]):
        if a.get(field) is None or b.get(field) is None:
            continue
        if (b[field] > a[field]) == up:
            n += 1
    return n


def _mk_event(eid, kid, kw_name, kw_role, to_row, from_row, etype, v0, v1,
              continuity, ptype):
    kw = kw_name[kid]
    if etype == "demand_up":
        label = "「%s」月搜索量从 %s 升到 %s" % (kw, _num(v0), _num(v1))
    elif etype == "demand_down":
        label = "「%s」月搜索量从 %s 降到 %s" % (kw, _num(v0), _num(v1))
    elif etype == "competition_up":
        label = "「%s」在售商品数从 %s 增到 %s" % (kw, _num(v0), _num(v1))
    elif etype == "insufficient_history":
        label = "「%s」只有最近少数几期有数据，暂不足以判断趋势" % kw
    elif etype == "not_comparable":
        label = "「%s」数据来源口径在本期变更，与上期不可直接比较" % kw
    else:
        label = "「%s」发生变化" % kw
    return {
        "event_id": "me_%05d" % eid,
        "keyword_id": kid,
        "keyword": kw,
        "period_type": ptype,
        "event_type": etype,
        "event_type_label": MARKET_EVENT_LABEL[etype],
        "from_snapshot_id": from_row["snapshot_id"] if from_row else None,
        "to_snapshot_id": to_row["snapshot_id"],
        "from_period_end": from_row["period_end"] if from_row else None,
        "to_period_end": to_row["period_end"],
        "from_value": v0,
        "to_value": v1,
        "change_ratio": round(v1 / v0, 4) if (v0 and v1) else None,
        "continuity": continuity,
        "continuity_label": {"continuous": "连续变化", "single_period": "单期波动",
                             "insufficient": "样本不足"}[continuity],
        "operator_role_label": kw_role.get(kid),
        "label": label,
        "rule_version": RULE_VERSION,
        "value_origin": "derived",
    }


def build_coverage_events(pos_daily, pair_rows, kw_rows):
    kw_name = {r["keyword_id"]: r["keyword"] for r in kw_rows}
    kw_core = {r["keyword_id"]: r["operator_role"] == "core" for r in kw_rows}
    by_pair = collections.defaultdict(list)
    for r in pos_daily:
        by_pair[r["pair_id"]].append(r)
    pair_of = {p["pair_id"]: p for p in pair_rows}

    events = []
    eid = 0
    for pid, rows in by_pair.items():
        rows.sort(key=lambda r: r["date"])
        p = pair_of[pid]
        kid = p["keyword_id"]
        prev = None
        for r in rows:
            if prev is None:
                prev = r
                continue
            for side, sfield, rfield in (("organic", "organic_state", "organic_rank"),
                                         ("ad", "ad_state", "ad_rank")):
                a, b = prev[sfield], r[sfield]
                if a == b:
                    continue
                if a == "not_covered" and b == "covered":
                    et = "%s_gained" % side
                elif a == "covered" and b == "not_covered":
                    et = "%s_lost" % side
                elif b == "beyond_depth" and a == "covered":
                    et = "beyond_depth"
                elif b == "collect_failed":
                    continue                     # 采集失败按日统计，不逐对发事件
                else:
                    continue
                eid += 1
                events.append(_mk_cov_event(eid, p, kw_name, kw_core, prev, r, et,
                                            prev[rfield], r[rfield]))
            prev = r
        # 位次连续上涨/下降各出一条汇总事件
        cov = [r for r in rows if r["organic_state"] == "covered" and r["organic_rank"]]
        if len(cov) >= 20 and p["pair_shape"] in ("organic_up", "organic_down"):
            eid += 1
            et = "organic_up" if p["pair_shape"] == "organic_up" else "organic_down"
            events.append(_mk_cov_event(eid, p, kw_name, kw_core, cov[0], cov[-1], et,
                                        cov[0]["organic_rank"], cov[-1]["organic_rank"]))
    return events


def _mk_cov_event(eid, p, kw_name, kw_core, from_row, to_row, et, r0, r1):
    kw = kw_name[p["keyword_id"]]
    asin = p["child_asin"]
    if et == "organic_up":
        label = "%s 在「%s」的自然位从第 %s 位升到第 %s 位" % (asin, kw, r0, r1)
    elif et == "organic_down":
        label = "%s 在「%s」的自然位从第 %s 位降到第 %s 位" % (asin, kw, r0, r1)
    elif et == "organic_gained":
        label = "%s 在「%s」新增自然覆盖，进入第 %s 位" % (asin, kw, r1)
    elif et == "organic_lost":
        label = "%s 在「%s」丢失自然覆盖，此前在第 %s 位" % (asin, kw, r0)
    elif et == "ad_gained":
        label = "%s 在「%s」新增广告覆盖" % (asin, kw)
    elif et == "ad_lost":
        label = "%s 在「%s」广告覆盖中断" % (asin, kw)
    else:
        label = "%s 在「%s」跌出采集深度，无法确认是否仍有排名" % (asin, kw)
    return {
        "event_id": "ce_%06d" % eid,
        "pair_id": p["pair_id"],
        "keyword_id": p["keyword_id"],
        "keyword": kw,
        "child_asin": asin,
        "event_type": et,
        "event_type_label": COVERAGE_EVENT_LABEL[et],
        "from_date": from_row["date"],
        "to_date": to_row["date"],
        "from_rank": r0,
        "to_rank": r1,
        "is_core_keyword": 1 if kw_core.get(p["keyword_id"]) else 0,
        "continuity": "continuous" if et in ("organic_up", "organic_down") else "single_period",
        "label": label,
        "rule_version": RULE_VERSION,
        "value_origin": "derived",
    }
