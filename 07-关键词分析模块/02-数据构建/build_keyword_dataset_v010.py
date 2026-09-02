#!/usr/bin/env python3
"""关键词模块 Demo 数据包 v0.1.0 构建器 —— L1 词库 / L2 分类与需求词组。

用法：/usr/bin/python3 build_keyword_dataset_v010.py [--stage l1l2]
输出：v0.1.0/bamboocool_keyword_v0.1.0.sqlite + 每表 JSON + manifest + quality_report
与 v0.3.0 物理隔离，只读客户源文件与 v0.3.0。
"""
from __future__ import annotations

import collections
import json
import os
import re
import sqlite3
import sys

import lib_kwsrc as L
import lib_l3 as L3
import lib_l4 as L4
import lib_l56 as L56
import lib_l7 as L7
import lib_l89 as L89

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "v0.1.0")
DB_PATH = os.path.join(OUT_DIR, "bamboocool_keyword_v0.1.0.sqlite")

VERSION = "0.1.0"
SEED = 20260803
RULE_VERSION = "keyword-demo-rules-v1"

# 词库状态目标分布（按相关度升序切，切点写进 manifest）
LIB_NOISE_N = 120
LIB_PENDING_N = 250
LIB_MONITOR_N = 30

DIM_ORDER = ["材质", "功能", "场景", "节日", "季节", "款式", "人群",
             "尺码", "颜色", "数量", "包装", "规格", "活动", "礼品",
             "品牌", "属性", "其他通用", "未分类"]

ROLE_BY_BUCKET = {
    "core_big": ("core", "核心词"),
    "own_brand": ("core", "核心词"),
    "competitor_brand": ("explore", "探索词"),
    "attribute": ("explore", "探索词"),
    "scene": ("explore", "探索词"),
    "size_color_qty": ("explore", "探索词"),
    "longtail_high_cvr": ("longtail", "长尾词"),
    "variant": ("longtail", "长尾词"),
    "gap_no_coverage": ("pending_validation", "待验证词"),
    "noise": ("unset", "未定角色"),
    "fill": ("unset", "未定角色"),
}

LIB_STATUS_LABEL = {
    "valid": "有效词",
    "pending": "待确认",
    "noise": "噪声词",
    "monitor": "监控词",
}


# --------------------------------------------------------------------- 落库工具

def ensure_out():
    os.makedirs(OUT_DIR, exist_ok=True)


def write_json(name: str, rows: list) -> None:
    path = os.path.join(OUT_DIR, "%s.json" % name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("[\n")
        for i, r in enumerate(rows):
            fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True))
            fh.write(",\n" if i < len(rows) - 1 else "\n")
        fh.write("]\n")


_SQL_TYPE = {int: "INTEGER", float: "REAL", str: "TEXT", bool: "INTEGER"}


def infer_cols(rows: list) -> list:
    cols, types = [], {}
    for r in rows:
        for k, v in r.items():
            if k not in types:
                cols.append(k)
                types[k] = None
            if types[k] is None and v is not None:
                types[k] = _SQL_TYPE.get(type(v), "TEXT")
    return [(c, types[c] or "TEXT") for c in cols]


def emit_table(con, name: str, rows: list, key: list[str] | None = None,
               indices: list[list[str]] | None = None) -> dict:
    if not rows:
        return {"table": name, "record_count": 0, "fields": [], "key": key or []}
    cols = infer_cols(rows)
    con.execute("drop table if exists %s" % name)
    ddl = ", ".join('"%s" %s' % (c, t) for c, t in cols)
    if key:
        ddl += ", primary key (%s)" % ", ".join('"%s"' % k for k in key)
    con.execute("create table %s (%s)" % (name, ddl))
    names = [c for c, _ in cols]
    ph = ",".join("?" * len(names))
    con.executemany("insert into %s (%s) values (%s)"
                    % (name, ",".join('"%s"' % n for n in names), ph),
                    [tuple(_scalar(r.get(n)) for n in names) for r in rows])
    for ix in (indices or []):
        con.execute("create index if not exists ix_%s_%s on %s (%s)"
                    % (name, "_".join(ix), name, ",".join('"%s"' % c for c in ix)))
    write_json(name, rows)
    return {"table": name, "record_count": len(rows), "fields": names, "key": key or []}


def _scalar(v):
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False, sort_keys=True)
    if isinstance(v, bool):
        return int(v)
    return v


# ------------------------------------------------------------------ L1 词库构建

def build_l1(S, monitored, buckets):
    """dim_market_keyword / dim_keyword_alias / dim_brand"""
    kw3_rows = S["kw3"]
    kw2_by_key = S["kw2_by_key"]
    seeds = {a["attribute_key"]: a for a in S["kw1_attrs"]}
    confirmed_seeds = {k for k, a in seeds.items() if a["priority"] in ("S", "A")}

    # 去重：同一标准写法多行，保留第一行为主，其余写法进别名表
    first = {}
    raw_variants = collections.defaultdict(list)
    for i, r in enumerate(kw3_rows):
        k = r["keyword"]
        raw_variants[k].append(r["keyword_raw"])
        if k not in first:
            first[k] = (i, r)

    uniq = [first[k][1] for k in sorted(first, key=lambda k: first[k][0])]

    # 词库状态：按相关度升序切
    by_rel = sorted(uniq, key=lambda r: ((r.get("relevance") or 0.0), r["keyword"]))
    status = {}
    for i, r in enumerate(by_rel):
        if i < LIB_NOISE_N:
            status[r["keyword"]] = "noise"
        elif i < LIB_NOISE_N + LIB_PENDING_N:
            status[r["keyword"]] = "pending"
        else:
            status[r["keyword"]] = "valid"
    cuts = {
        "noise_max_relevance": (by_rel[LIB_NOISE_N - 1].get("relevance")
                                if len(by_rel) >= LIB_NOISE_N else None),
        "pending_max_relevance": (by_rel[LIB_NOISE_N + LIB_PENDING_N - 1].get("relevance")
                                  if len(by_rel) >= LIB_NOISE_N + LIB_PENDING_N else None),
    }
    # 监控词：从监控集里取相关度最低的 30 个（运营临时加入、等待采集）
    mon_sorted = sorted((k for k in monitored if status.get(k) == "valid"),
                        key=lambda k: ((first[k][1].get("relevance") or 0.0), k))
    for k in mon_sorted[:LIB_MONITOR_N]:
        status[k] = "monitor"

    kw_ids = {}
    rows = []
    for n, r in enumerate(uniq, 1):
        k = r["keyword"]
        kid = "kw_%05d" % n
        kw_ids[k] = kid
        alt = kw2_by_key.get(k) or {}
        brand = (alt.get("matched_brand") or "").strip() or None
        if brand and brand.upper() == L.OWN_BRAND:
            brand_role, brand_label = "own_brand", "自有品牌词"
        elif brand:
            brand_role, brand_label = "competitor_brand", "竞品品牌词"
        else:
            brand_role, brand_label = "generic", "非品牌词"
        bucket = buckets.get(k)
        role, role_label = ROLE_BY_BUCKET.get(bucket, ("unset", "未定角色"))
        hit_seed = next((s for s in confirmed_seeds if s and s in k), None)
        st = status[k]
        rows.append({
            "keyword_id": kid,
            "keyword": k,
            "keyword_raw": r["keyword_raw"],
            "keyword_cn": r["keyword_cn"],
            "alias_key": r["alias_key"],
            "site": L.SITE,
            "product_line": L.PRODUCT_LINE,
            "library_status": st,
            "library_status_label": LIB_STATUS_LABEL[st],
            "is_monitored": 1 if k in monitored else 0,
            "selection_bucket": bucket,
            "primary_category": r["primary_category"],
            "all_category_tags": r["all_category_tags"],
            "category_tags_alt": alt.get("category_tags_alt") or [],
            "matched_brand": brand,
            "brand_role": brand_role,
            "brand_role_label": brand_label,
            "operator_role": role,
            "operator_role_label": role_label,
            "operator_role_confirmed": 1 if hit_seed else 0,
            "operator_role_seed_word": hit_seed,
            "ac_recommended": r["ac_recommended"],
            "relevance": r["relevance"],
            "category_path": r["category_path"],
            "traffic_word_type": alt.get("traffic_word_type"),
            "raw_variant_count": len(set(raw_variants[k])),
            "first_seen_date": "2026-02-02",
            "last_updated_date": L.AS_OF,
            "source_files": sorted({L.KW3} | ({L.KW2} if alt else set())),
            "value_origin": "customer_real",
        })

    # 别名表：同一标准写法的多种原始写法 + 同 alias_key 的跨写法家族
    aliases = []
    aid = 0
    for k, variants in raw_variants.items():
        for v in sorted(set(variants)):
            if L.norm_keyword(v) == k and v == first[k][1]["keyword_raw"]:
                continue
            aid += 1
            aliases.append({
                "alias_id": "al_%05d" % aid,
                "keyword_id": kw_ids[k],
                "alias_text": v,
                "alias_type": "raw_spelling",
                "alias_type_label": "原始写法",
                "normalization_rule": "NFKC+小写+压空白",
                "source_file": L.KW3,
                "value_origin": "customer_real",
            })
    fam = collections.defaultdict(list)
    for r in uniq:
        fam[r["alias_key"]].append(r["keyword"])
    for ak in sorted(fam):
        grp = sorted(fam[ak], key=lambda k: -(first[k][1].get("monthly_search_volume") or 0))
        if len(grp) < 2:
            continue
        std = grp[0]
        for other in grp[1:]:
            aid += 1
            aliases.append({
                "alias_id": "al_%05d" % aid,
                "keyword_id": kw_ids[std],
                "alias_text": other,
                "alias_type": "variant_family",
                "alias_type_label": "拼写变体",
                "normalization_rule": "去撇号+underware→underwear",
                "source_file": L.KW3,
                "value_origin": "derived",
            })

    brands = []
    for i, b in enumerate(sorted(S["kw2_brands"], key=lambda x: -(x["keyword_count"] or 0)), 1):
        is_own = (b["brand"] or "").strip().upper() == L.OWN_BRAND
        brands.append({
            "brand_id": "br_%03d" % i,
            "brand": b["brand"],
            "brand_role": "own_brand" if is_own else "competitor_brand",
            "brand_role_label": "自有品牌" if is_own else "竞品品牌",
            "keyword_count": b["keyword_count"],
            "sample_keywords": b["sample_keywords"],
            "source_file": L.KW2,
            "value_origin": "customer_real",
        })
    return rows, aliases, brands, kw_ids, cuts


# ---------------------------------------------------- L2 分类、需求词组、基线对账

def build_l2(S, kw_rows, kw_ids):
    """bridge_keyword_attribute / dim_keyword_group / bridge_keyword_group
    / dim_keyword_attribute_seed / fact_keyword_attribute_combo
    / fact_keyword_category_rollup"""
    by_key = {r["keyword"]: r for r in kw_rows}

    # 属性标签桥表（一词多标签，两来源各自留痕）
    attrs = []
    n = 0
    for r in kw_rows:
        tags3 = r["all_category_tags"] or []
        tags2 = r["category_tags_alt"] or []
        for t in tags3:
            n += 1
            attrs.append({"attr_row_id": "ka_%06d" % n, "keyword_id": r["keyword_id"],
                          "attribute_dimension": t, "source_file": L.KW3,
                          "is_primary": 1 if t == r["primary_category"] else 0,
                          "value_origin": "customer_real"})
        for t in tags2:
            n += 1
            attrs.append({"attr_row_id": "ka_%06d" % n, "keyword_id": r["keyword_id"],
                          "attribute_dimension": t, "source_file": L.KW2,
                          "is_primary": 0, "value_origin": "customer_real"})

    # 属性词种子（关键词1）
    seeds = []
    combos = []
    for i, a in enumerate(S["kw1_attrs"], 1):
        sid = "as_%03d" % i
        seeds.append({
            "seed_id": sid,
            "attribute_word": a["attribute_word"],
            "attribute_key": a["attribute_key"],
            "dimension": a["dimension"],
            "dimension_code": a["dimension_code"],
            "priority_code": a["priority"],
            "priority_label": a["priority_raw"],
            "is_starred": a["is_starred"],
            "source_file": L.KW1,
            "value_origin": "customer_real",
        })
        for j, c in enumerate(a["combos"], 1):
            combos.append({
                "combo_id": "%s_%d" % (sid, j),
                "seed_id": sid,
                "core_keyword": c["core_keyword"],
                "combo_keyword": c["combo_keyword"],
                "aba_slot": c["aba_slot"],
                "volume_bucket": c["volume_bucket"],
                "impressions": c["impressions"],
                "data_state": "covered" if c["has_data"] else "insufficient_data",
                "data_state_label": "有排名数据" if c["has_data"] else "暂无数据",
                "source_file": L.KW1,
                "value_origin": "customer_real",
            })

    # 需求词组：优先用关键词1 的属性词种子命中，否则落到主要分类
    seed_by_key = {a["attribute_key"]: a for a in S["kw1_attrs"]}
    seed_keys = sorted(seed_by_key, key=lambda s: (-len(s), s))
    dim_rank = {d: i for i, d in enumerate(DIM_ORDER)}

    members = collections.defaultdict(list)
    for r in kw_rows:
        k = r["keyword"]
        # 方案明写「一个关键词可以同时属于多个需求属性标签」→ 收集全部命中的种子，不只取第一个
        hits = []
        for s in seed_keys:
            if s and re.search(r"(?:^|\s)%s(?:\s|$)" % re.escape(s), k):
                hits.append(seed_by_key[s])
        if hits:
            # 同一维度内只保留最长（最具体）的那个种子，跨维度全部保留
            best_per_dim = {}
            for h in hits:
                cur = best_per_dim.get(h["dimension"])
                if cur is None or len(h["attribute_key"]) > len(cur["attribute_key"]):
                    best_per_dim[h["dimension"]] = h
            for h in best_per_dim.values():
                members[(h["dimension"], h["attribute_word"])].append(k)
        else:
            tags = r["all_category_tags"] or ([r["primary_category"]]
                                              if r["primary_category"] else [])
            tag = min(tags, key=lambda t: dim_rank.get(t, 99)) if tags else "未分类"
            members[(tag, None)].append(k)

    # 成员数 < 5 的种子组折回其维度级组
    folded = collections.defaultdict(list)
    for gkey, ks in members.items():
        dim, word = gkey
        if word is not None and len(ks) < 5:
            folded[(dim, None)].extend(ks)
        else:
            folded[gkey].extend(ks)

    groups = []
    bridges = []
    gid_of = {}
    for i, gkey in enumerate(sorted(folded, key=lambda g: (dim_rank.get(g[0], 99),
                                                           g[1] or "", g[0])), 1):
        dim, word = gkey
        gid = "kg_%03d" % i
        gid_of[gkey] = gid
        name = "%s·%s" % (dim, word) if word else dim
        groups.append({
            "group_id": gid,
            "group_name": name,
            "demand_dimension": dim,
            "anchor_attribute_word": word,
            "member_count": len(folded[gkey]),
            "value_origin": "derived",
        })

    # 一词多组时按 1/n 分权，词组汇总不重复计入
    kw_groups = collections.defaultdict(list)
    for gkey, ks in folded.items():
        for k in ks:
            kw_groups[k].append(gid_of[gkey])
    b = 0
    for k in sorted(kw_groups):
        gids = sorted(set(kw_groups[k]))
        w = round(1.0 / len(gids), 6)
        for g in gids:
            b += 1
            bridges.append({"bridge_id": "kgb_%06d" % b, "keyword_id": by_key[k]["keyword_id"],
                            "group_id": g, "dedup_weight": w, "value_origin": "derived"})

    # G2 基线：客户总览 11 行 vs 从 2000 原始行现算（必须用原始行，客户就是这样算的）
    raw = S["kw3"]
    agg = collections.defaultdict(lambda: {"n": 0, "sv": 0, "pv": 0})
    for r in raw:
        c = r["primary_category"] or "未分类"
        agg[c]["n"] += 1
        agg[c]["sv"] += r["monthly_search_volume"] or 0
        agg[c]["pv"] += r["monthly_purchase_volume"] or 0
    rollup = []
    for i, o in enumerate(S["kw3_overview"], 1):
        c = o["category_name"]
        a = agg.get(c, {"n": 0, "sv": 0, "pv": 0})
        rollup.append({
            "rollup_id": "cr_%02d" % i,
            "category_name": c,
            "customer_keyword_count": o["keyword_count"],
            "computed_keyword_count": a["n"],
            "customer_monthly_search_sum": o["monthly_search_sum"],
            "computed_monthly_search_sum": a["sv"],
            "customer_monthly_purchase_sum": o["monthly_purchase_sum"],
            "computed_monthly_purchase_sum": a["pv"],
            "match_keyword_count": 1 if o["keyword_count"] == a["n"] else 0,
            "match_search_sum": 1 if o["monthly_search_sum"] == a["sv"] else 0,
            "match_purchase_sum": 1 if o["monthly_purchase_sum"] == a["pv"] else 0,
            "source_file": L.KW3,
            "value_origin": "customer_real",
        })
    return attrs, groups, bridges, seeds, combos, rollup


# ------------------------------------------------------------------------- main

def main():
    ensure_out()
    S = L.load_all()
    seed_keys = {a["attribute_key"] for a in S["kw1_attrs"] if a["priority"] in ("S", "A")}
    buckets = L.select_keywords(S["kw3"], S["kw2_by_key"], seed_keys,
                                S["own_asins"], S["coverage_by_kw"])
    monitored = set(buckets)
    children = L.select_children(S["children"], S["coverage_by_child"], S["golden"])

    kw_rows, aliases, brands, kw_ids, cuts = build_l1(S, monitored, buckets)
    attrs, groups, bridges, seeds, combos, rollup = build_l2(S, kw_rows, kw_ids)

    # ---- L3 市场事实时间序列
    kw3_by_key = {r["keyword"]: r for r in S["kw3"]}
    L3.set_own_asins(S["own_asins"])
    snaps, heads, shape_map = L3.build_snapshots(kw_rows, kw3_by_key, S["kw2_by_key"],
                                                buckets)
    g1_checked, g1_fails = L3.gate_g1(snaps, kw3_by_key, S["kw2_by_key"])
    shape_gates = L3.gate_shapes(snaps, heads, shape_map)

    # ---- L4 覆盖与位置关系
    focus = set(children)
    pairs = L4.build_pairs(kw_rows, S["children"], focus, S["coverage_by_kw"])
    pair_rows, pos_daily, state_labels = L4.build_positions(pairs, S["children"], focus)
    l4_gates = L4.gate_l4(pair_rows, pos_daily, S["coverage_by_kw"], focus)

    # ---- L5 付费侧词级证据（受 v0.3.0 当日真实值封顶）
    ds = L4.dates()
    caps = L.read_v030_daily_caps(sorted(focus), ds[0], ds[-1])
    traffic, unattr = L56.build_traffic(pos_daily, pair_rows, caps)
    l5_gates = L56.gate_l5(traffic, unattr, caps)

    # ---- L6 产品目标与库存承接
    kw_brand = {r["keyword_id"]: r["brand_role"] for r in kw_rows}
    own_brand_cov = collections.Counter(
        p["child_asin"] for p in pair_rows
        if kw_brand.get(p["keyword_id"]) == "own_brand")
    goals, absorb = L56.build_product_context(S["children"], S["inv_decision"],
                                              S["coverage_by_child"], focus,
                                              own_brand_cov)
    l6_gates = L56.gate_l6(goals, absorb, S["inv_decision"], S["children"])

    # ---- L7 变化事件
    mkt_events = L7.build_market_events(snaps, kw_rows)
    cov_events = L7.build_coverage_events(pos_daily, pair_rows, kw_rows)

    # ---- L8 证据与盘点记录
    evidence = L89.build_evidence(pair_rows, pos_daily, mkt_events, cov_events,
                                  kw_rows, goals, absorb, focus)
    audits = L89.build_audit_records(focus, pair_rows, pos_daily, evidence,
                                     goals, absorb)

    # ---- L9 动态日报
    reports = L89.build_daily_reports(pos_daily, traffic, mkt_events, cov_events,
                                      evidence, kw_rows)
    l789_gates = L89.gate_l789(mkt_events, cov_events, evidence, audits, reports,
                               snaps, absorb, focus)

    scope = [{"scope_id": "sc_001", "site": L.SITE, "product_line": L.PRODUCT_LINE,
              "as_of_date": L.AS_OF, "monitored_keyword_count": len(monitored),
              "focus_child_count": len(children),
              "focus_child_asins": sorted(children),
              "library_keyword_count": len(kw_rows),
              "rule_version": RULE_VERSION, "value_origin": "derived"}]

    con = sqlite3.connect(DB_PATH)
    con.execute("pragma journal_mode=delete")
    cat = []
    cat.append(emit_table(con, "dim_scope", scope, ["scope_id"]))
    cat.append(emit_table(con, "dim_market_keyword", kw_rows, ["keyword_id"],
                          [["keyword"], ["library_status"], ["is_monitored"],
                           ["primary_category"], ["alias_key"]]))
    cat.append(emit_table(con, "dim_keyword_alias", aliases, ["alias_id"], [["keyword_id"]]))
    cat.append(emit_table(con, "dim_brand", brands, ["brand_id"], [["brand_role"]]))
    cat.append(emit_table(con, "bridge_keyword_attribute", attrs, ["attr_row_id"],
                          [["keyword_id"], ["attribute_dimension"]]))
    cat.append(emit_table(con, "dim_keyword_group", groups, ["group_id"],
                          [["demand_dimension"]]))
    cat.append(emit_table(con, "bridge_keyword_group", bridges, ["bridge_id"],
                          [["keyword_id"], ["group_id"]]))
    cat.append(emit_table(con, "dim_keyword_attribute_seed", seeds, ["seed_id"],
                          [["dimension_code"], ["priority_code"]]))
    cat.append(emit_table(con, "fact_keyword_attribute_combo", combos, ["combo_id"],
                          [["seed_id"]]))
    cat.append(emit_table(con, "fact_keyword_category_rollup", rollup, ["rollup_id"]))
    cat.append(emit_table(con, "fact_keyword_market_snapshot", snaps, ["snapshot_id"],
                          [["keyword_id", "period_type", "period_index"],
                           ["period_end"], ["change_shape"], ["source_code"],
                           ["comparable_flag"]]))
    cat.append(emit_table(con, "fact_keyword_head_asin", heads, ["head_id"],
                          [["keyword_id", "period_end"], ["asin"], ["is_own_asin"]]))
    cat.append(emit_table(con, "dim_keyword_child_pair", pair_rows, ["pair_id"],
                          [["child_asin"], ["keyword_id"], ["pair_shape"],
                           ["anchor_band"]]))
    cat.append(emit_table(con, "fact_keyword_child_position_daily", pos_daily,
                          ["pos_id"],
                          [["pair_id", "date"], ["child_asin", "date"],
                           ["keyword_id", "date"], ["organic_state"],
                           ["coverage_state"]]))
    cat.append(emit_table(con, "dim_state_label", state_labels, ["label_id"],
                          [["domain"]]))
    cat.append(emit_table(con, "fact_keyword_child_traffic_daily", traffic,
                          ["traffic_id"],
                          [["keyword_id", "date"], ["child_asin", "date"],
                           ["pair_id"]]))
    cat.append(emit_table(con, "fact_child_traffic_attribution_daily", unattr,
                          ["child_asin", "date"]))
    cat.append(emit_table(con, "dim_child_product_goal", goals, ["goal_id"],
                          [["child_asin"], ["is_current"], ["product_goal"],
                           ["push_role"]]))
    cat.append(emit_table(con, "fact_child_inventory_absorb", absorb, ["absorb_id"],
                          [["child_asin"], ["absorb_state"]]))
    cat.append(emit_table(con, "fact_keyword_market_change_event", mkt_events,
                          ["event_id"], [["keyword_id"], ["event_type"],
                                         ["to_period_end"]]))
    cat.append(emit_table(con, "fact_keyword_coverage_event", cov_events,
                          ["event_id"], [["child_asin"], ["keyword_id"],
                                         ["event_type"], ["to_date"]]))
    cat.append(emit_table(con, "fact_keyword_evidence", evidence, ["evidence_id"],
                          [["child_asin"], ["keyword_id"], ["evidence_type"],
                           ["priority"]]))
    cat.append(emit_table(con, "fact_keyword_audit_record", audits, ["record_id"],
                          [["child_asin", "run_date"], ["is_latest"]]))
    cat.append(emit_table(con, "fact_keyword_daily_report", reports, ["report_date"]))
    con.commit()
    con.execute("vacuum")
    con.close()

    status_dist = collections.Counter(r["library_status"] for r in kw_rows)
    role_dist = collections.Counter(r["operator_role"] for r in kw_rows if r["is_monitored"])
    brand_dist = collections.Counter(r["brand_role"] for r in kw_rows)
    g2_fail = [r for r in rollup if not (r["match_keyword_count"] and r["match_search_sum"]
                                        and r["match_purchase_sum"])]

    manifest = {
        "dataset_name": "bamboocool-keyword-analysis-demo",
        "dataset_version": VERSION,
        "stage": "L1+L2+L3+L4",
        "as_of_date": L.AS_OF,
        "site": L.SITE,
        "product_line": L.PRODUCT_LINE,
        "seed": SEED,
        "rule_version": RULE_VERSION,
        "source_files": [L.KW3, L.KW2, L.KW1,
                         "v0.3.0/bamboocool_product_sales_inventory_v0.3.0.sqlite"],
        "library_keyword_count": len(kw_rows),
        "monitored_keyword_count": len(monitored),
        "focus_child_count": len(children),
        "selection_quotas": {b: sum(1 for v in buckets.values() if v == b)
                             for b, _, _ in L.QUOTAS},
        "selection_cuts": dict(L.SELECTION_CUTS),
        "library_status_cuts": cuts,
        "library_status_distribution": dict(status_dist),
        "monitored_role_distribution": dict(role_dist),
        "brand_role_distribution": dict(brand_dist),
        "week_periods": L3.WEEK_PERIODS,
        "month_periods": L3.MONTH_PERIODS,
        "week_last_period_end": L3.WEEK_LAST_END.isoformat(),
        "change_shape_distribution": dict(collections.Counter(shape_map.values())),
        "gates": {
            "G1_last_period_equals_customer": {
                "fields_checked": g1_checked, "failures": len(g1_fails),
                "passed": not g1_fails,
                "sample_failures": g1_fails[:5],
            },
            "G2_category_rollup": {"rows": len(rollup), "failures": len(g2_fail),
                                   "passed": not g2_fail},
            "G3_named_shape_assertions": [
                {"assertion": a, "passed": bool(ok), "detail": d}
                for a, ok, d in shape_gates],
            "G4_position_assertions": [
                {"assertion": a, "passed": bool(ok), "detail": d}
                for a, ok, d in l4_gates],
            "G5_paid_evidence_assertions": [
                {"assertion": a, "passed": bool(ok), "detail": d}
                for a, ok, d in l5_gates],
            "G6_product_context_assertions": [
                {"assertion": a, "passed": bool(ok), "detail": d}
                for a, ok, d in l6_gates],
            "G7_G8_G9_assertions": [
                {"assertion": a, "passed": bool(ok), "detail": str(d)}
                for a, ok, d in l789_gates],
        },
        "position_layer": {
            "daily_days": L4.DAILY_DAYS,
            "date_from": L4.dates()[0],
            "date_to": L4.dates()[-1],
            "collect_depth": L4.COLLECT_DEPTH,
            "pair_count": len(pair_rows),
            "anchored_pair_count": sum(1 for p in pair_rows if p["anchor_band"]),
            "pair_shape_distribution": dict(collections.Counter(
                p["pair_shape"] for p in pair_rows)),
            "global_collect_fail_dates": L4.GLOBAL_FAIL_DATES,
            "late_monitor_from": L4.LATE_MONITOR_FROM,
        },
        "tables": cat,
    }
    with open(os.path.join(OUT_DIR, "dataset-manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2, sort_keys=True)

    print("== v%s  L1+L2 ==" % VERSION)
    for t in cat:
        print("  %-34s %7d 行" % (t["table"], t["record_count"]))
    print("\n词库状态分布: %s" % dict(status_dist))
    print("  切点: 噪声≤相关度%s  待确认≤%s"
          % (cuts["noise_max_relevance"], cuts["pending_max_relevance"]))
    print("监控词角色分布: %s" % dict(role_dist))
    print("品牌角色分布: %s" % dict(brand_dist))
    per_kw = collections.Counter(b["keyword_id"] for b in bridges)
    multi = collections.Counter(per_kw.values())
    print("需求词组: %d 组  (成员数 top5: %s)"
          % (len(groups), ", ".join("%s=%d" % (g["group_name"], g["member_count"])
                                    for g in sorted(groups, key=lambda x: -x["member_count"])[:5])))
    print("  一词多组分布(组数→词数): %s   多组词占比 %.1f%%"
          % (dict(sorted(multi.items())),
             100.0 * sum(v for k, v in multi.items() if k > 1) / max(1, sum(multi.values()))))
    print("\nG2 分类基线对账: %d/%d 行三项全等  %s"
          % (len(rollup) - len(g2_fail), len(rollup),
             "全绿" if not g2_fail else "不一致: " + ", ".join(r["category_name"] for r in g2_fail)))
    print("\n变化形态分布: %s" % dict(collections.Counter(shape_map.values())))
    print("G1 末期锚客户原值: 校验 %d 个字段值, 不等 %d 个  %s"
          % (g1_checked, len(g1_fails), "全绿" if not g1_fails else "红"))
    for f in g1_fails[:5]:
        print("    %s / %s / %s / %s: 造=%s 客户=%s" % f)
    print("G3 指名到词的形态门禁:")
    for a, ok, d in shape_gates:
        print("  [%s] %s  (%s)" % ("PASS" if ok else "FAIL", a, d))
    print("\nL4 位置层: %d 对 (%d 对带真实锚点)  %d 天  形态分布 %s"
          % (len(pair_rows), sum(1 for p in pair_rows if p["anchor_band"]),
             L4.DAILY_DAYS,
             dict(collections.Counter(p["pair_shape"] for p in pair_rows))))
    print("G4 位置层门禁:")
    for a, ok, d in l4_gates:
        print("  [%s] %s  (%s)" % ("PASS" if ok else "FAIL", a, d))
    print("\nL5 付费侧: %d 行词级流量  %d 行归因残差" % (len(traffic), len(unattr)))
    for a, ok, d in l5_gates:
        print("  [%s] %s  (%s)" % ("PASS" if ok else "FAIL", a, d))
    print("\nL6 产品上下文: %d 条产品目标（当前 %d 条）  %d 条库存承接"
          % (len(goals), sum(1 for g in goals if g["is_current"]), len(absorb)))
    for a, ok, d in l6_gates:
        print("  [%s] %s  (%s)" % ("PASS" if ok else "FAIL", a, d))
    print("\nL7-L9: %d 条市场事件  %d 条覆盖事件  %d 条证据  %d 条盘点记录  %d 天日报"
          % (len(mkt_events), len(cov_events), len(evidence), len(audits),
             len(reports)))
    for a, ok, d in l789_gates:
        print("  [%s] %s  (%s)" % ("PASS" if ok else "FAIL", a, d))
    allg = shape_gates + l4_gates + l5_gates + l6_gates + l789_gates
    nfail = sum(1 for _, ok, _ in allg if not ok) + (1 if g1_fails else 0) \
        + (1 if g2_fail else 0)
    print("\n门禁总计: %d 条，失败 %d 条" % (len(allg) + 2, nfail))
    print("DB: %s (%.1f MB)" % (DB_PATH, os.path.getsize(DB_PATH) / 1e6))


if __name__ == "__main__":
    sys.exit(main())
