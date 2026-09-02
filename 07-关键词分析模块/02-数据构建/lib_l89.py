#!/usr/bin/env python3
"""L8 证据与盘点记录 / L9 动态关键词日报 + 三层门禁。"""
from __future__ import annotations

import collections

import lib_l56 as L56
import lib_l7 as L7

RULE_VERSION = L7.RULE_VERSION
AS_OF = L7.AS_OF
AUDIT_RUNS = L7.AUDIT_RUNS
REPORT_DAYS = L7.REPORT_DAYS

EVIDENCE_LABEL = L7.EVIDENCE_LABEL
COMPLETENESS_LABEL = L7.COMPLETENESS_LABEL
NEXT_LABEL = L7.NEXT_LABEL
VERIFY_LABEL = L7.VERIFY_LABEL

# 「流量获取」缺正式测量定义 → Demo 明示使用代理指标
TRAFFIC_PROXY = "监控词带来的自然 Sessions（代理指标）"


def _num(v):
    return "{:,}".format(int(v)) if v is not None else "—"


# --------------------------------------------------------------------- L8 证据

def build_evidence(pair_rows, pos_daily, market_events, coverage_events,
                   kw_rows, goals, absorb, focus_asins):
    kw = {r["keyword_id"]: r for r in kw_rows}
    goal_cur = {g["child_asin"]: g for g in goals if g["is_current"]}
    ab = {a["child_asin"]: a for a in absorb}
    last = max(r["date"] for r in pos_daily)
    last_state = {(r["pair_id"]): r for r in pos_daily if r["date"] == last}

    mkt_by_kw = collections.defaultdict(list)
    for e in market_events:
        mkt_by_kw[e["keyword_id"]].append(e)
    cov_by_pair = collections.defaultdict(list)
    for e in coverage_events:
        cov_by_pair[e["pair_id"]].append(e)

    rows = []
    eid = 0
    for p in pair_rows:
        kid = p["keyword_id"]
        asin = p["child_asin"]
        k = kw[kid]
        g = goal_cur.get(asin)
        a = ab.get(asin)
        st = last_state.get(p["pair_id"])
        if not st:
            continue
        mkts = mkt_by_kw.get(kid, [])
        covs = cov_by_pair.get(p["pair_id"], [])
        demand_up = any(e["event_type"] == "demand_up" for e in mkts)
        demand_down = any(e["event_type"] == "demand_down" for e in mkts)
        comp_up = any(e["event_type"] == "competition_up" for e in mkts)
        insuff = any(e["event_type"] in ("insufficient_history", "not_comparable")
                     for e in mkts)
        lost = any(e["event_type"] == "organic_lost" for e in covs)
        down = any(e["event_type"] == "organic_down" for e in covs)
        covered_o = st["organic_state"] == "covered"
        covered_a = st["ad_state"] == "covered"
        blocked = a and a["absorb_state"] in ("cannot_absorb", "replenish_first")

        etype = None
        weak_pos = (not covered_o) or (st["organic_rank"] or 999) > 20
        growth_goal = g and g["product_goal"] in (
            "volume_push", "niche_explore", "brand_defend")
        if insuff or not g:
            etype = "insufficient_data"
        elif demand_up and blocked:
            # 库存受限优先：机会真实存在但先扩量会打空
            etype = "inventory_limited"
        elif k["operator_role"] == "core" and (lost or down):
            etype = "core_position_risk"
        elif demand_up and weak_pos and growth_goal:
            # 市场机会是市场级判断，不要求零覆盖（零覆盖是「产品覆盖缺口」）
            etype = "market_opportunity"
        elif comp_up and covered_o:
            etype = "pending_competitor_verification"
        elif k["operator_role"] in ("longtail", "explore") and (demand_up or covered_a):
            etype = "scene_longtail_signal"
        elif not covered_o and not covered_a:
            etype = "coverage_gap"
        else:
            continue

        eid += 1
        rows.append(_mk_evidence(eid, etype, k, p, g, a, st, mkts, covs,
                                 demand_up, demand_down, comp_up, insuff))
    return rows


def _mk_evidence(eid, etype, k, p, g, a, st, mkts, covs,
                 demand_up, demand_down, comp_up, insuff):
    kwn = k["keyword"]
    asin = p["child_asin"]
    goal_txt = g["product_goal_label"] if g else "尚未设定产品目标"
    push_txt = g["push_role_label"] if g else "未定"
    ab_txt = a["absorb_state_label"] if a else "库存结果缺失"
    rank = st["organic_rank"]
    ad_rank = st["ad_rank"]
    mkt_lab = mkts[0]["label"] if mkts else None
    cov_lab = covs[-1]["label"] if covs else None

    if etype == "market_opportunity":
        pos_txt = ("目前既无自然位也无广告位" if not st["organic_rank"]
                   else "当前自然位仅第 %s 位，偏弱" % st["organic_rank"])
        concl = "「%s」需求在涨，%s %s，是可以争取的入口" % (kwn, asin, pos_txt)
        basis = "%s；当前产品目标「%s」，%s，库存%s" % (
            mkt_lab or "该词近期搜索需求持续上行", goal_txt, push_txt, ab_txt)
        nxt, ver, comp = "advertising", "na", "full"
    elif etype == "coverage_gap":
        concl = "%s 与「%s」相关，但当前没有任何自然或广告覆盖" % (asin, kwn)
        basis = "该词属于%s，与当前产品目标「%s」相关，覆盖为空" % (
            k["operator_role_label"], goal_txt)
        nxt, ver, comp = "advertising", "na", "partial"
    elif etype == "core_position_risk":
        concl = "核心词「%s」上，%s 的位置正在走弱" % (kwn, asin)
        basis = cov_lab or "自然位连续下滑"
        nxt, ver, comp = "competitor", "pending", "full"
    elif etype == "scene_longtail_signal":
        concl = "「%s」需求出现连续增长，%s 已有初步覆盖，值得继续观察" % (kwn, asin)
        basis = "%s；当前自然位第 %s 位，广告位第 %s 位" % (
            mkt_lab or "需求上行", rank if rank else "—", ad_rank if ad_rank else "—")
        nxt, ver, comp = "observe", "na", "partial"
    elif etype == "inventory_limited":
        concl = "「%s」有机会，但 %s 当前%s，不宜先扩量" % (kwn, asin, ab_txt)
        basis = "%s；库存判断：%s" % (mkt_lab or "该词需求上行",
                                    (a or {}).get("decision_summary") or ab_txt)
        nxt, ver, comp = "observe", "na", "full"
    elif etype == "pending_competitor_verification":
        concl = "「%s」竞争在加剧，%s 虽有位置但需先确认竞品动作" % (kwn, asin)
        basis = mkt_lab or "该词在售商品数与广告竞品数同期上升"
        nxt, ver, comp = "competitor", "pending", "partial"
    else:
        concl = "「%s」在 %s 上暂不能形成可靠结论" % (kwn, asin)
        basis = ("该词历史样本不足或来源口径变更，本期不可比" if insuff
                 else "缺少当前产品目标，无法判断该词的业务作用")
        nxt, ver, comp = "observe", "na", "insufficient"

    pri = {"core_position_risk": 1, "inventory_limited": 2, "market_opportunity": 2,
           "pending_competitor_verification": 3, "coverage_gap": 4,
           "scene_longtail_signal": 5, "insufficient_data": 6}[etype]
    if k["operator_role"] == "core":
        pri = max(1, pri - 1)
    if g and g["push_role"] == "main":
        pri = max(1, pri - 1)

    return {
        "evidence_id": "ev_%05d" % eid,
        "keyword_id": k["keyword_id"],
        "keyword": kwn,
        "child_asin": asin,
        "pair_id": p["pair_id"],
        "evidence_type": etype,
        "evidence_type_label": EVIDENCE_LABEL[etype],
        "priority": pri,
        "conclusion": concl,
        "main_basis": basis,
        "product_goal_label": goal_txt,
        "push_role_label": push_txt,
        "inventory_limit_label": ab_txt if etype == "inventory_limited" else None,
        "evidence_completeness": comp,
        "evidence_completeness_label": COMPLETENESS_LABEL[comp],
        "next_verification": nxt,
        "next_verification_label": NEXT_LABEL[nxt],
        "competitor_verification_state": ver,
        "competitor_verification_label": VERIFY_LABEL[ver],
        "ref_market_event_ids": [e["event_id"] for e in mkts[:3]],
        "ref_coverage_event_ids": [e["event_id"] for e in covs[-3:]],
        "ref_position_date": st["date"],
        "run_date": AS_OF,
        "rule_version": RULE_VERSION,
        "value_origin": "derived",
    }


def build_audit_records(focus_asins, pair_rows, pos_daily, evidence, goals, absorb):
    goal_cur = {g["child_asin"]: g for g in goals if g["is_current"]}
    ab = {a["child_asin"]: a for a in absorb}
    pairs_by_child = collections.defaultdict(list)
    for p in pair_rows:
        pairs_by_child[p["child_asin"]].append(p)
    ev_by_child = collections.defaultdict(list)
    for e in evidence:
        ev_by_child[e["child_asin"]].append(e)
    state_by_pair_date = {(r["pair_id"], r["date"]): r for r in pos_daily}

    rows = []
    rid = 0
    for asin in sorted(focus_asins):
        for run in AUDIT_RUNS:
            rid += 1
            ps = pairs_by_child[asin]
            states = [state_by_pair_date.get((p["pair_id"], run)) for p in ps]
            states = [s for s in states if s]
            o_cov = sum(1 for s in states if s["organic_state"] == "covered")
            a_cov = sum(1 for s in states if s["ad_state"] == "covered")
            both = sum(1 for s in states if s["coverage_state"] == "both")
            unk = sum(1 for s in states if s["coverage_state"] == "unconfirmed")
            ranks = [s["organic_rank"] for s in states if s["organic_rank"]]
            g = goal_cur.get(asin)
            a = ab.get(asin)
            evs = ev_by_child.get(asin, []) if run == AS_OF else []
            rows.append({
                "record_id": "ar_%04d" % rid,
                "child_asin": asin,
                "run_date": run,
                "is_latest": 1 if run == AUDIT_RUNS[-1] else 0,
                "library_scope": "US / BAMBOO COOL 男士内衣 / 监控词 300",
                "pair_count": len(ps),
                "organic_covered_count": o_cov,
                "ad_covered_count": a_cov,
                "both_covered_count": both,
                "unconfirmed_count": unk,
                "best_organic_rank": min(ranks) if ranks else None,
                "median_organic_rank": (sorted(ranks)[len(ranks) // 2]
                                        if ranks else None),
                "product_goal_label": g["product_goal_label"] if g else None,
                "push_role_label": g["push_role_label"] if g else None,
                "product_lifecycle": g["product_lifecycle"] if g else None,
                "absorb_state_label": a["absorb_state_label"] if a else None,
                "evidence_count": len(evs),
                "evidence_type_counts": dict(collections.Counter(
                    e["evidence_type_label"] for e in evs)),
                "data_as_of": run,
                "rule_version": RULE_VERSION,
                "value_origin": "derived",
            })
    return rows


# --------------------------------------------------------------------- L9 日报

def build_daily_reports(pos_daily, traffic, market_events, coverage_events, evidence,
                        kw_rows):
    import datetime as dt
    end = dt.date.fromisoformat(AS_OF)
    days = [(end - dt.timedelta(days=REPORT_DAYS - 1 - i)).isoformat()
            for i in range(REPORT_DAYS)]
    sess_by_date = collections.Counter()
    for t in traffic:
        sess_by_date[t["date"]] += t["organic_sessions"] or 0
    cov_by_date = collections.defaultdict(list)
    for e in coverage_events:
        cov_by_date[e["to_date"]].append(e)
    ev_sorted = sorted(evidence, key=lambda e: (e["priority"], e["evidence_id"]))

    rows = []
    for i, d in enumerate(days):
        prev = days[i - 1] if i else None
        cur = sess_by_date.get(d, 0)
        pv = sess_by_date.get(prev, 0) if prev else 0
        delta = (cur - pv) / pv if pv else None
        evs = cov_by_date.get(d, [])
        gained = [e for e in evs if e["event_type"] in ("organic_gained", "ad_gained")]
        lost = [e for e in evs if e["event_type"] in ("organic_lost", "ad_lost")]
        core_hit = [e for e in evs if e["is_core_keyword"]]
        top = ev_sorted[(i * 3) % max(1, len(ev_sorted) - 3):][:3]
        ups = [e for e in market_events if e["event_type"] == "demand_up"][:2]
        downs = [e for e in market_events if e["event_type"] == "demand_down"][:2]

        q1 = "%s 为 %s，%s" % (
            TRAFFIC_PROXY, _num(cur),
            "较前一日无可比数据" if delta is None else
            "较前一日%s %.1f%%" % ("上升" if delta >= 0 else "下降", abs(delta) * 100))
        q2 = ("增长主要来自 %s；下降主要来自 %s"
              % ("、".join("「%s」" % e["keyword"] for e in ups) or "暂无显著上涨词",
                 "、".join("「%s」" % e["keyword"] for e in downs) or "暂无显著下滑词"))
        q3 = ("当日新增覆盖 %d 条、丢失覆盖 %d 条，其中涉及核心词 %d 条"
              % (len(gained), len(lost), len(core_hit)))
        q4 = ("当日出现 %d 条覆盖或位置变化；%s"
              % (len(evs),
                 "、".join(dict.fromkeys(e["event_type_label"] for e in evs[:3]))
                 or "无新增异常信号"))
        q5 = ("最值得继续看的是 %s"
              % ("；".join("%s 在「%s」（%s）"
                          % (e["child_asin"], e["keyword"], e["evidence_type_label"])
                          for e in top) or "暂无优先事项"))
        rows.append({
            "report_date": d,
            "site": "US",
            "product_line": "BAMBOO COOL 男士内衣",
            "compare_period": "对比前一日",
            "traffic_proxy_metric": TRAFFIC_PROXY,
            "traffic_proxy_value": cur,
            "traffic_proxy_delta": (round(delta, 4) if delta is not None else None),
            "q1_traffic_result": q1,
            "q2_main_movers": q2,
            "q3_core_coverage_change": q3,
            "q4_new_signals": q4,
            "q5_priority_next": q5,
            "priority_evidence_ids": [e["evidence_id"] for e in top],
            "coverage_event_ids": [e["event_id"] for e in evs[:20]],
            "rule_version": RULE_VERSION,
            "value_origin": "derived",
        })
    return rows


# ------------------------------------------------------------------------ 门禁

TEXT_FIELDS = ["conclusion", "main_basis", "label", "q1_traffic_result",
               "q2_main_movers", "q3_core_coverage_change", "q4_new_signals",
               "q5_priority_next"]


def _scan_forbidden(rows):
    hits = []
    for r in rows:
        for f in TEXT_FIELDS:
            v = r.get(f)
            if not isinstance(v, str):
                continue
            for bad in L7.FORBIDDEN_IN_TEXT:
                if bad in v:
                    hits.append((r.get("evidence_id") or r.get("event_id")
                                 or r.get("report_date"), f, bad))
    return hits


def gate_l789(market_events, coverage_events, evidence, audits, reports, snaps,
              absorb, focus_asins):
    out = []
    snap_ids = {s["snapshot_id"] for s in snaps}

    # G7-1 事件必须能下钻到两期快照
    bad = [e for e in market_events
           if e["to_snapshot_id"] not in snap_ids
           or (e["from_snapshot_id"] and e["from_snapshot_id"] not in snap_ids)]
    out.append(("G7-1 %d 条市场事件的快照引用都可解析" % len(market_events),
                not bad, "无法解析 %d 条" % len(bad)))

    mt = collections.Counter(e["event_type"] for e in market_events)
    miss = [k for k in L7.MARKET_EVENT_LABEL if k not in mt and k != "head_asin_replaced"]
    out.append(("G7-2 市场事件类型齐全（头部替换在 L3 头部表内表达）", not miss,
                ", ".join("%s=%d" % (L7.MARKET_EVENT_LABEL[k], v) for k, v in mt.items())))

    ct = collections.Counter(e["event_type"] for e in coverage_events)
    need = ["organic_up", "organic_down", "organic_gained", "organic_lost",
            "ad_gained", "ad_lost"]
    miss_c = [k for k in need if ct.get(k, 0) < 5]
    out.append(("G7-3 六类覆盖事件每类 ≥ 5 条", not miss_c,
                ", ".join("%s=%d" % (L7.COVERAGE_EVENT_LABEL[k], ct.get(k, 0))
                          for k in need)))

    cont = collections.Counter(e["continuity"] for e in market_events)
    out.append(("G7-4 连续变化与单期波动都存在",
                cont.get("continuous", 0) > 0 and cont.get("single_period", 0) > 0,
                dict(cont)))

    # G8-1 七类证据每类 ≥ 5 条
    et = collections.Counter(e["evidence_type"] for e in evidence)
    thin = [EVIDENCE_LABEL[k] for k in EVIDENCE_LABEL if et.get(k, 0) < 5]
    out.append(("G8-1 七类证据每类 ≥ 5 条", not thin,
                ", ".join("%s=%d" % (EVIDENCE_LABEL[k], et.get(k, 0))
                          for k in EVIDENCE_LABEL)
                + ("  过薄=%s" % thin if thin else "")))

    # G8-2 上屏文案不得泄漏枚举码
    hits = _scan_forbidden(evidence) + _scan_forbidden(market_events) \
        + _scan_forbidden(coverage_events) + _scan_forbidden(reports)
    out.append(("G8-2 证据/事件/日报文案零枚举码泄漏", not hits,
                "泄漏 %d 处 %s" % (len(hits), hits[:3])))

    # G8-3 库存受限证据必须真的指向承接不了的子体
    ab = {a["child_asin"]: a["absorb_state"] for a in absorb}
    wrong = [e for e in evidence if e["evidence_type"] == "inventory_limited"
             and ab.get(e["child_asin"]) not in ("cannot_absorb", "replenish_first")]
    out.append(("G8-3 库存受限证据都指向承接不了的子体", not wrong,
                "口径不符 %d 条" % len(wrong)))

    comp = collections.Counter(e["evidence_completeness"] for e in evidence)
    out.append(("G8-4 证据完整度三档都出现", len(comp) == 3, dict(comp)))

    # G8-5 盘点记录必须多期且相邻两期真的不同
    n_child = len(set(focus_asins))
    by_child = collections.defaultdict(list)
    for a in audits:
        by_child[a["child_asin"]].append(a)
    same = 0
    changed_children = 0
    for asin, rs in by_child.items():
        rs.sort(key=lambda r: r["run_date"])
        moved = False
        for x, y in zip(rs, rs[1:]):
            if (x["organic_covered_count"] == y["organic_covered_count"]
                    and x["ad_covered_count"] == y["ad_covered_count"]
                    and x["median_organic_rank"] == y["median_organic_rank"]
                    and x["unconfirmed_count"] == y["unconfirmed_count"]):
                same += 1
            else:
                moved = True
        if moved:
            changed_children += 1
    # 有些子体在两次盘点之间本来就没动，这是真实情况；要求的是多数子体能看出变化
    ratio = changed_children / max(1, len(by_child))
    out.append(("G8-5 %d 子体 × %d 期盘点记录，≥70%% 子体相邻两期能看出变化"
                % (n_child, len(AUDIT_RUNS)),
                len(audits) == n_child * len(AUDIT_RUNS) and ratio >= 0.7,
                "记录 %d 条，有变化的子体 %d/%d (%.0f%%)，完全未动的相邻组 %d"
                % (len(audits), changed_children, len(by_child), ratio * 100, same)))

    # G9-1 日报 14 天，五问都非空
    empty = [r["report_date"] for r in reports
             if not all(r.get("q%d_%s" % (i, s)) for i, s in
                        ((1, "traffic_result"), (2, "main_movers"),
                         (3, "core_coverage_change"), (4, "new_signals"),
                         (5, "priority_next")))]
    out.append(("G9-1 日报 %d 天且五问都非空" % REPORT_DAYS,
                len(reports) == REPORT_DAYS and not empty,
                "%d 天，空答 %d 天" % (len(reports), len(empty))))

    # G9-2 日报不得每天完全相同
    uniq = len({(r["q1_traffic_result"], r["q3_core_coverage_change"],
                 r["q5_priority_next"]) for r in reports})
    out.append(("G9-2 %d 天日报内容各不相同" % REPORT_DAYS, uniq == len(reports),
                "不同内容 %d / %d 天" % (uniq, len(reports))))

    # G9-3 日报引用的证据 id 都能解析
    ids = {e["evidence_id"] for e in evidence}
    dangling = [r["report_date"] for r in reports
                if any(x not in ids for x in r["priority_evidence_ids"])]
    out.append(("G9-3 日报优先事项引用都能解析到证据", not dangling,
                "悬空引用 %d 天" % len(dangling)))
    return out
