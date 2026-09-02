#!/usr/bin/env python3
"""Side facts, attribution bridges, label taxonomy, anomaly rules and the
quality report for the advertising demo v0.2.0 build.

Imported by build_v0_2_0.py.
"""
from __future__ import annotations

import json
from collections import defaultdict

import adsrc
from build_facts import ATTRIB, WINDOW, in_window, metrics, rows_of

RULE_VERSION = "demo-v0.2"


# =========================================================== 6. side facts

def build_yoy(b) -> int:
    n = 0
    for r in rows_of("商品推广_广告活动_报告.csv"):
        camp = (str(r.get("广告活动名称") or "")).strip()
        if not camp:
            continue
        cid = b.campaigns.get(("SP", camp))
        if cid is None:
            continue
        imp = adsrc.parse_money(r.get("展示量"))
        imp_ly = adsrc.parse_money(r.get("去年曝光量"))
        clk = adsrc.parse_money(r.get("点击量"))
        clk_ly = adsrc.parse_money(r.get("去年点击量"))
        sp = adsrc.parse_money(r.get("花费"))
        sp_ly = adsrc.parse_money(r.get("去年支出"))
        cpc = adsrc.parse_money(r.get("单次点击成本 (CPC)"))
        cpc_ly = adsrc.parse_money(r.get("去年每次点击成本(CPC)"))

        def chg(a, c):
            return ((a - c) / c) if (a is not None and c) else None

        b.db.execute(
            "INSERT OR REPLACE INTO fact_ad_yoy VALUES"
            " (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (b.sid("yoy", cid, WINDOW[0]), cid, "SP", WINDOW[0], WINDOW[1],
             imp, imp_ly, clk, clk_ly, sp, sp_ly, cpc, cpc_ly,
             chg(imp, imp_ly), chg(clk, clk_ly), chg(sp, sp_ly),
             chg(cpc, cpc_ly), "direct", "商品推广_广告活动_报告.csv"))
        n += 1
    b.db.commit()
    return n


def build_budget(b) -> int:
    n = 0
    for r in rows_of("商品推广_预算_报告.csv"):
        camp = (str(r.get("广告活动名称") or "")).strip()
        cid = b.campaigns.get(("SP", camp))
        if cid is None:
            continue
        b.db.execute(
            "INSERT OR REPLACE INTO fact_budget VALUES"
            " (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (b.sid("bud", cid, WINDOW[0]), cid, "SP", WINDOW[0], WINDOW[1],
             adsrc.parse_money(r.get("预算")),
             adsrc.parse_money(r.get("建议预算")),
             adsrc.parse_pct(r.get("预算范围内的平均时间")),
             adsrc.parse_money(r.get("预计错失的展示量范围（最小值）")),
             adsrc.parse_money(r.get("预计错失的展示量范围（最大值）")),
             adsrc.parse_money(r.get("预计错失的点击量范围（最小值）")),
             adsrc.parse_money(r.get("预计错失的点击量范围（最大）")),
             adsrc.parse_money(r.get("预计错失的销售额范围（最小值）")),
             adsrc.parse_money(r.get("预计错失的销售额范围（最大值）")),
             "direct", "商品推广_预算_报告.csv"))
        n += 1
    b.db.commit()
    return n


def build_invalid_traffic(b) -> int:
    n = 0
    for fname, atype in (("商品推广_总流量和无效流量_报告.xlsx", "SP"),
                         ("品牌推广_总流量和无效流量_报告.xlsx", "SB"),
                         ("展示型推广_总流量和无效流量_报告.xlsx", "SD")):
        for r in rows_of(fname):
            camp = (str(r.get("广告活动名称") or "")).strip()
            if not camp:
                continue
            cid = b.campaigns.get((atype, camp))
            s, e = in_window(r)
            b.db.execute(
                "INSERT OR REPLACE INTO fact_invalid_traffic VALUES"
                " (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (b.sid("inv", atype, camp, s), cid, atype, camp, s, e,
                 (str(r.get("状态") or "")).strip() or None,
                 adsrc.parse_money(r.get("总展示量")),
                 adsrc.parse_money(r.get("展示量")),
                 adsrc.parse_money(r.get("无效展示量")),
                 adsrc.parse_pct(r.get("无效展示率")),
                 adsrc.parse_money(r.get("总点击量")),
                 adsrc.parse_money(r.get("点击量")),
                 adsrc.parse_money(r.get("无效点击")),
                 adsrc.parse_pct(r.get("无效的点击率")),
                 "direct", fname))
            n += 1
    b.db.commit()
    return n


def build_benchmark(b) -> int:
    n = 0
    for r in rows_of("品牌推广_品类基准_报告.csv"):
        brand = (str(r.get("品牌") or "")).strip()
        cat = (str(r.get("类别") or "")).strip()
        if not brand or not cat:
            continue
        s, e = in_window(r)
        b.db.execute(
            "INSERT OR REPLACE INTO fact_category_benchmark VALUES"
            " (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (b.sid("bmk", brand, cat, s), brand, cat, s, e,
             adsrc.parse_money(r.get("展示量")),
             adsrc.parse_money(r.get("对等商品曝光量 - 底部 25%")),
             adsrc.parse_money(r.get("对等商品曝光量 - 中位数")),
             adsrc.parse_money(r.get("对等商品曝光量 - 顶部 25%")),
             adsrc.parse_pct(r.get("点击率(CTR)")),
             adsrc.parse_pct(r.get("对等商品 CTR - 底部 25%")),
             adsrc.parse_pct(r.get("对等商品 CTR - 中位数")),
             adsrc.parse_pct(r.get("对等商品 CTR - 顶部 25%")),
             adsrc.parse_pct(r.get("广告成本销售比(ACOS)")),
             adsrc.parse_pct(r.get("对等商品 ACOS - 顶部 25%")),
             adsrc.parse_pct(r.get("对等商品 ACOS - 中位数")),
             adsrc.parse_pct(r.get("对等商品 ACOS - 底部 25%")),
             adsrc.parse_money(r.get("投入产出比(ROAS)")),
             adsrc.parse_money(r.get("对等商品 ROAS - 底部 25%")),
             adsrc.parse_money(r.get("对等商品 ROAS - 中位数")),
             adsrc.parse_money(r.get("对等商品 ROAS - 顶部 25%")),
             "direct", "品牌推广_品类基准_报告.csv"))
        n += 1
    b.db.commit()
    return n


def build_search_term_share(b) -> int:
    rows = []
    for fname, atype in (("商品推广_搜索词展示量份额_报告.csv", "SP"),
                         ("品牌推广_搜索词展示量份额_报告.csv", "SB")):
        for r in rows_of(fname):
            term = (str(r.get("客户搜索词") or "")).strip()
            if not term:
                continue
            s, e = in_window(r)
            m = metrics(r)
            rows.append((
                b.sid("shr", atype, term, r.get("广告活动名称"),
                      r.get("投放"), s),
                atype,
                (str(r.get("广告活动名称") or "")).strip() or None,
                (str(r.get("广告组名称") or "")).strip() or None,
                term,
                (str(r.get("投放") or "")).strip() or None,
                (str(r.get("匹配类型") or "")).strip() or None,
                s, e,
                adsrc.parse_money(r.get("搜索词展示量排名")),
                adsrc.parse_pct(r.get("搜索词展示量份额")),
                m["impressions"], m["clicks"], m["spend"], m["orders"],
                m["ad_sales"], "direct", fname))
    b.db.executemany(
        "INSERT OR REPLACE INTO fact_search_term_share VALUES"
        " (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    b.db.commit()
    return len(rows)


def build_creatives(b) -> int:
    n = 0
    for fname, atype, kind, detail_col in (
            ("商品推广_视频_报告.xlsx", "SP", "video", "视频详情"),
            ("商品推广_提示词_报告.xlsx", "SP", "prompt", "提示详细信息"),
            ("品牌推广_提示词_报告.xlsx", "SB", "prompt", "提示详细信息")):
        for r in rows_of(fname):
            camp = (str(r.get("广告活动名称") or "")).strip()
            detail = (str(r.get(detail_col) or "")).strip()
            if not camp or not detail:
                continue
            grp = (str(r.get("广告组名称") or "")).strip() or None
            oid = b.objects.get(("AD_GROUP", atype, camp, grp or "", "", ""))
            s, e = in_window(r)
            m = metrics(r)
            b.db.execute(
                "INSERT OR REPLACE INTO fact_creative VALUES"
                " (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (b.sid("crv", atype, camp, grp, kind, detail), oid, atype,
                 camp, grp, kind, detail,
                 (str(r.get("广告SKU") or "")).strip() or None,
                 (str(r.get("广告ASIN") or "")).strip() or None,
                 s, e, m["impressions"], m["clicks"], m["spend"], m["orders"],
                 m["ad_sales"], m["ctr"], m["cpc"], m["acos"], m["roas"],
                 adsrc.parse_money(r.get("5 秒观看次数")),
                 adsrc.parse_pct(r.get("5 秒观看率")),
                 "direct", fname))
            n += 1
    b.db.commit()
    return n


# ========================================================== 7. attribution

BRIDGE_SOURCES = [
    # (filename, ad_type, level, group_col, asin_col, role, scope_note)
    ("商品推广_推广的商品_报告.xlsx", "SP", "AD_GROUP", "广告组名称",
     "广告ASIN", "promoted_asin"),
    ("展示型推广_推广的商品_报告.xlsx", "SD", "AD_GROUP", "广告组名称",
     "广告ASIN", "promoted_asin"),
    ("商品推广_已购买商品_报告.xlsx", "SP", "AD_GROUP", "广告组名称",
     "已购买的ASIN", "purchased_asin"),
    ("展示型推广_已购买商品_报告.xlsx", "SD", "AD_GROUP", "广告组名称",
     "已购买的ASIN", "purchased_asin"),
    ("品牌推广_归因于广告的购买_报告.csv", "SB", "CAMPAIGN", None,
     "已购买的ASIN", "purchased_asin"),
]


def build_bridges(b) -> dict:
    scope = {row[0] for row in b.db.execute(
        "SELECT child_asin FROM dim_product_child")}
    seen: set[tuple] = set()
    stats = defaultdict(int)
    rows = []

    def add(oid, asin, role, scope_flag, src, source_role):
        key = (oid, asin, role)
        if key in seen:
            return
        seen.add(key)
        n_children = 0
        rows.append((b.sid("rel", oid, asin, role), oid, asin, role,
                     "shared", WINDOW[0], None, "direct", src, source_role,
                     1 if scope_flag else 0))
        stats[role] += 1
        return n_children

    for fname, atype, level, gcol, acol, role in BRIDGE_SOURCES:
        for r in rows_of(fname):
            camp = (str(r.get("广告活动名称") or "")).strip()
            asin = (str(r.get(acol) or "")).strip().upper()
            if not camp or not asin:
                continue
            grp = (str(r.get(gcol) or "")).strip() if gcol else None
            if level == "CAMPAIGN":
                oid = b.objects.get(("CAMPAIGN", atype, camp, "", "", ""))
            else:
                oid = b.objects.get(("AD_GROUP", atype, camp, grp or "", "", ""))
                if oid is None:
                    oid = b.ensure_object("AD_GROUP", atype, camp, grp,
                                          src=fname)
            if oid is None:
                continue
            add(oid, asin, role, asin in scope, fname, acol)
            # A promoted ASIN that actually spent money in the window is a
            # separate, stronger fact than merely being listed as 广告ASIN.
            if role == "promoted_asin":
                spend = adsrc.parse_money(r.get("花费"))
                if spend and spend > 0:
                    add(oid, asin, "positive_spend_asin", asin in scope,
                        fname, "广告ASIN+花费>0")

    # 商品投放的目标 ASIN (competitor targets) and SD matched targets
    for r in rows_of("商品推广_投放_报告.xlsx"):
        tgt = (str(r.get("投放") or "")).strip()
        if not tgt.lower().startswith("asin="):
            continue
        asin = tgt.split("=", 1)[1].strip().strip('"').upper()
        camp = (str(r.get("广告活动名称") or "")).strip()
        grp = (str(r.get("广告组名称") or "")).strip() or None
        oid = b.objects.get(("AD_GROUP", "SP", camp, grp or "", "", ""))
        if oid and asin:
            add(oid, asin, "target_asin", asin in scope,
                "商品推广_投放_报告.xlsx", "投放")

    for r in rows_of("展示型推广_匹配的目标_报告.xlsx"):
        matched = (str(r.get("匹配的目标") or "")).strip().upper()
        camp = (str(r.get("广告活动名称") or "")).strip()
        oid = b.objects.get(("CAMPAIGN", "SD", camp, "", "", ""))
        if oid and len(matched) == 10 and matched.startswith("B0"):
            add(oid, matched, "matched_asin", matched in scope,
                "展示型推广_匹配的目标_报告.xlsx", "匹配的目标")

    b.db.executemany(
        "INSERT OR IGNORE INTO bridge_ad_object_product VALUES"
        " (?,?,?,?,?,?,?,?,?,?,?)", rows)
    b.db.commit()
    in_scope = b.db.execute(
        "SELECT COUNT(*) FROM bridge_ad_object_product WHERE is_scope_product=1"
    ).fetchone()[0]
    stats["_total"] = len(rows)
    stats["_in_scope"] = in_scope
    return dict(stats)


# ============================================================== 8. labels

DIM_TO_LABEL = {
    "delivery": "AD_ATTRIBUTE",
    "match": "AD_ATTRIBUTE",
    "placement": "AD_ATTRIBUTE",
    "targeting": "TARGET_OBJECT",
    "audience": "TARGET_OBJECT",
    "theme": "TARGET_OBJECT",
    "style": "PRODUCT_RELATION",
    "owner": "OPERATOR_CUSTOM",
    "lifecycle": "OPERATOR_CUSTOM",
    "tactic": "OPERATOR_CUSTOM",
}


def _target_object_from_text(target_text: str, match_type: str) -> str | None:
    t = (target_text or "").strip()
    m = (match_type or "").strip().upper()
    if not t:
        return None
    low = t.lower()
    if low.startswith("asin="):
        return "竞品/关联商品"
    if low.startswith("category="):
        return "类目"
    if low in {"*", "-"} or m in {"", "-"}:
        return "自动匹配对象"
    if m in {"BROAD", "PHRASE", "EXACT"}:
        return "关键词"
    return "其他投放对象"


def build_labels(b) -> dict:
    rows = []
    stats = defaultdict(int)
    camp_dims: dict[str, dict] = {}
    for cid, name, dims_json in b.db.execute(
            "SELECT campaign_id, campaign_name, name_dims FROM dim_campaign"):
        camp_dims[cid] = json.loads(dims_json)

    objects = list(b.db.execute(
        "SELECT ad_object_id, object_level, ad_type, campaign_id, campaign_name,"
        " ad_group_name, target_text, match_type FROM dim_ad_object"))

    # product relation from the promoted-ASIN bridge
    promoted: dict[str, set] = defaultdict(set)
    for oid, asin in b.db.execute(
            "SELECT ad_object_id, child_asin FROM bridge_ad_object_product"
            " WHERE relation_role='promoted_asin'"):
        promoted[oid].add(asin)

    parent_of = {r[0]: r[1] for r in b.db.execute(
        "SELECT ad_object_id, parent_ad_object_id FROM dim_ad_object")}

    def emit(oid, ltype, lvalue, lsource, status, basis, inherited=None):
        if not lvalue:
            return
        rows.append((
            b.sid("lbl", oid, ltype, lvalue), oid, ltype, lvalue, lsource,
            status, WINDOW[0], None, inherited, basis,
            "derived" if lsource in ("auto_mapping", "ai_suggested")
            else "direct",
            "dim_campaign.name_dims" if lsource == "auto_mapping"
            else "dim_ad_object"))
        stats[ltype] += 1

    for oid, level, atype, cid, camp, grp, tgt, mt in objects:
        dims = camp_dims.get(cid) or adsrc.parse_campaign_name(camp)["dims"]

        # 1. AD_ATTRIBUTE -- ad type is a hard system attribute
        emit(oid, "AD_ATTRIBUTE", atype, "system_attribute", "confirmed",
             "report column 广告活动类型")
        if mt and mt not in {"-", ""}:
            emit(oid, "AD_ATTRIBUTE", mt, "system_attribute", "confirmed",
                 "report column 匹配类型")

        # 2. from the naming convention
        for dim, labels in dims.items():
            ltype = DIM_TO_LABEL.get(dim)
            if not ltype:
                continue
            for lv in labels:
                emit(oid, ltype, lv, "auto_mapping", "pending",
                     "campaign name token (%s)" % dim)

        # 3. TARGET_OBJECT from the actual target text
        if level == "TARGET":
            to = _target_object_from_text(tgt, mt)
            emit(oid, "TARGET_OBJECT", to, "system_attribute", "confirmed",
                 "投放/匹配类型 content")

        # 4. AD_PURPOSE -- suggestion, always pending
        purpose, basis = adsrc.infer_purpose(dims)
        emit(oid, "AD_PURPOSE", purpose, "ai_suggested",
             "pending" if purpose != "无法识别" else "unrecognized", basis)

        # 5. PRODUCT_RELATION from promoted ASINs, inherited down the tree
        asins = promoted.get(oid) or set()
        inherited_from = None
        if not asins:
            p = parent_of.get(oid)
            if p and promoted.get(p):
                asins = promoted[p]
                inherited_from = p
        if asins:
            emit(oid, "PRODUCT_RELATION",
                 "%d 个推广子ASIN" % len(asins),
                 "group_inherited" if inherited_from else "auto_mapping",
                 "pending", "bridge promoted_asin", inherited_from)

    b.db.executemany(
        "INSERT OR IGNORE INTO fact_ad_label_version VALUES"
        " (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    b.db.commit()
    stats["_total"] = len(rows)
    return dict(stats)


# =============================================================== 9. rules

RULES = [
    ("rule_acos_gt_050", "ACoS 高于演示观察线", "absolute_threshold",
     "acos", ">", 0.5, "AD_GROUP,TARGET"),
    ("rule_cpc_gt_300", "CPC 高于演示观察线", "absolute_threshold",
     "cpc", ">", 3.0, "AD_GROUP,TARGET"),
    ("rule_acos_increase_gt_030", "ACoS 较自身历史上升超过 30%", "self_history",
     "acos_change_rate", ">", 0.3, "AD_GROUP,TARGET"),
    ("rule_cvr_drop_gt_030", "转化率较自身历史下降超过 30%", "self_history",
     "cvr_change_rate", "<", -0.3, "AD_GROUP,TARGET"),
    ("rule_acos_peer_dev", "ACoS 显著高于同口径对象中位数", "peer_deviation",
     "acos_vs_peer_median", ">", 0.5, "AD_GROUP,TARGET"),
    ("rule_budget_capped", "预算几乎打满且有明确错失", "data_state",
     "time_in_budget", ">", 0.95, "CAMPAIGN"),
    ("rule_invalid_click_high", "无效点击率偏高", "absolute_threshold",
     "invalid_click_rate", ">", 0.1, "CAMPAIGN"),
    ("rule_partial_coverage", "实际覆盖不足完整窗口", "data_state",
     "coverage_days", "<", 31.0, "AD_GROUP,TARGET"),
    ("rule_mapping_missing", "缺少广告 ASIN 映射", "data_state",
     "promoted_asin_count", "<", 1.0, "AD_GROUP"),
    ("rule_low_daily_coverage", "日粒度样本不足无法看趋势", "data_state",
     "day_coverage", "<", 20.0, "AD_GROUP,TARGET"),
]


def build_rules(b) -> int:
    for rid, name, cls, metric, op, thr, applies in RULES:
        b.db.execute(
            "INSERT OR REPLACE INTO dim_anomaly_rule VALUES"
            " (?,?,?,?,?,?,?,?,?,?,?,?)",
            (rid, name, cls, metric, op, thr, 1,
             "pending_customer_confirmation", RULE_VERSION, applies,
             "scenario_added", "scenario://anomaly-rule/%s" % RULE_VERSION))
    b.db.commit()
    return len(RULES)
