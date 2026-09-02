#!/usr/bin/env python3
"""步骤二：按契约第 2 节建观察库 competitor_demo.sqlite。

抓取层 + 观察层的产物。Agent 只读它，工作台的三个事实看板也读它。
逐日序列是构造的，锚点是真实快照：末日价格 == 快照价格，评论数单调收敛到快照值。
"""
from __future__ import annotations

import datetime as dt
import json
import os
import random
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "v0.1.0")
DB = os.path.join(OUT_DIR, "competitor_demo.sqlite")
PRODUCT_DB = os.path.join(
    os.path.dirname(os.path.dirname(HERE)),
    "02-产品销售库存模块", "02-数据构建", "v0.3.0",
    "bamboocool_product_sales_inventory_v0.3.0.sqlite",
)
SEED = 20260803
ANALYZED = 20
QUICK_SLOT = 8

SCENARIOS = [
    ("S1", "活动型", "Coupon/Deal 开始→结束→价格恢复，价差先扩大后收窄"),
    ("S2", "持续降价型", "非活动性阶梯降价，价格带整体下移"),
    ("S3", "市场上行型", "小类排名持续提升，销量量级上行，评论加速"),
    ("S4", "市场下行型", "小类排名下滑，评分下降"),
    ("S5", "关键词抢位型", "在共同核心词上挤进前三，点击共享上升"),
    ("S6", "关键词丢失型", "掉出前三，自有位置相对改善"),
    ("S7", "局部变化型", "变化只发生在一个非主销子体，不能代表产品族"),
    ("S8", "报价型", "BuyBox 换卖家导致价格变化，不是品牌自己降价"),
    ("S9", "证据不足型", "断更 14 天 + 来源冲突 + 更新过期"),
    ("S10", "同期非因果型", "价格下降与排名提升同期出现"),
    ("S10b", "同期对照型", "只有价格下降，排名无变化"),
    ("S11", "平稳对照型", "全期无显著变化"),
]

SCHEMA = """
CREATE TABLE dim_competitor_family (
  family_asin TEXT PRIMARY KEY, brand TEXT NOT NULL, title TEXT,
  category_path TEXT, sub_category TEXT, variant_count INTEGER,
  captured_children INTEGER, price_band_low REAL, price_band_high REAL,
  unit_price_median REAL, first_listed_date TEXT, seller_country TEXT,
  buybox_type TEXT, has_aplus INTEGER, has_video INTEGER,
  monitor_status TEXT NOT NULL, monitored_since TEXT,
  in_quick_slot INTEGER NOT NULL, in_analysis_scope INTEGER NOT NULL,
  source TEXT NOT NULL);
CREATE TABLE dim_competitor_child (
  child_asin TEXT PRIMARY KEY, family_asin TEXT NOT NULL, size_label TEXT,
  color_label TEXT, pack_count INTEGER, pack_resolved INTEGER NOT NULL,
  snapshot_price REAL, unit_price REAL, fba_fee REAL, gross_margin REAL,
  sales_rank_sub INTEGER, is_main_variant INTEGER NOT NULL);
CREATE TABLE dim_competitor_offer (
  offer_id TEXT PRIMARY KEY, child_asin TEXT NOT NULL, seller_name TEXT,
  seller_country TEXT, fulfillment TEXT, is_buybox INTEGER NOT NULL,
  observed_from TEXT, observed_to TEXT, value_origin TEXT NOT NULL);
CREATE TABLE dim_competitor_keyword (
  keyword TEXT PRIMARY KEY, keyword_cn TEXT, category_tags TEXT,
  aba_rank INTEGER, monthly_search INTEGER, monthly_purchase INTEGER,
  purchase_rate REAL, product_count INTEGER, supply_demand_ratio REAL,
  ad_competitor_count INTEGER, ppc_bid REAL, is_battleground INTEGER NOT NULL);
CREATE TABLE bridge_competitor_keyword (
  family_asin TEXT NOT NULL, keyword TEXT NOT NULL, first_observed TEXT,
  last_observed TEXT, entry_type TEXT, PRIMARY KEY (family_asin, keyword));
CREATE TABLE fact_competitor_price_daily (
  child_asin TEXT NOT NULL, date TEXT NOT NULL, list_price REAL,
  deal_price REAL, final_price REAL NOT NULL, unit_price REAL,
  coupon_pct REAL, promo_kind TEXT, value_origin TEXT NOT NULL,
  source TEXT NOT NULL, observed_at TEXT NOT NULL,
  PRIMARY KEY (child_asin, date));
CREATE TABLE fact_competitor_market_daily (
  family_asin TEXT NOT NULL, date TEXT NOT NULL, rank_sub INTEGER,
  rank_main INTEGER, units_rolling30 INTEGER, rating REAL,
  rating_count INTEGER, new_rating INTEGER, value_origin TEXT NOT NULL,
  source TEXT NOT NULL, PRIMARY KEY (family_asin, date));
CREATE TABLE fact_competitor_keyword_rank (
  family_asin TEXT NOT NULL, keyword TEXT NOT NULL, observed_date TEXT NOT NULL,
  organic_rank INTEGER, ad_slot TEXT, is_top3 INTEGER NOT NULL,
  click_share REAL, conversion_share REAL, value_origin TEXT NOT NULL,
  source TEXT NOT NULL, PRIMARY KEY (family_asin, keyword, observed_date));
CREATE TABLE fact_competitor_traffic_mix (
  family_asin TEXT NOT NULL, period_start TEXT NOT NULL, period_end TEXT NOT NULL,
  organic_share REAL, ad_share REAL, other_share REAL, top_entry_keyword TEXT,
  value_origin TEXT NOT NULL, PRIMARY KEY (family_asin, period_start));
CREATE TABLE fact_competitor_data_status (
  status_id TEXT PRIMARY KEY, object_level TEXT NOT NULL, object_id TEXT NOT NULL,
  date_from TEXT NOT NULL, date_to TEXT NOT NULL, status TEXT NOT NULL,
  label TEXT NOT NULL, source TEXT);
CREATE TABLE bridge_competitor_child (
  rel_id TEXT PRIMARY KEY, family_asin TEXT NOT NULL, child_asin TEXT NOT NULL,
  parent_asin TEXT NOT NULL, relation_basis TEXT NOT NULL, relation_note TEXT,
  confirm_status TEXT NOT NULL, since_date TEXT, value_origin TEXT NOT NULL);
CREATE TABLE dim_competitor_scenario (
  scenario_id TEXT PRIMARY KEY, family_asin TEXT NOT NULL, name TEXT NOT NULL,
  description TEXT NOT NULL);
CREATE TABLE competitor_manifest (key TEXT PRIMARY KEY, value TEXT);
CREATE INDEX idx_price_date ON fact_competitor_price_daily(date);
CREATE INDEX idx_market_date ON fact_competitor_market_daily(date);
CREATE INDEX idx_krank_kw ON fact_competitor_keyword_rank(keyword, observed_date);
"""


def daterange(a: str, b: str):
    d0 = dt.date.fromisoformat(a)
    d1 = dt.date.fromisoformat(b)
    out = []
    while d0 <= d1:
        out.append(d0.isoformat())
        d0 += dt.timedelta(days=1)
    return out


def main():
    rng = random.Random(SEED)
    with open(os.path.join(HERE, "_sources.json"), encoding="utf-8") as fh:
        src = json.load(fh)

    as_of, win_from = src["as_of"], src["window_from"]
    dates = daterange(win_from, as_of)
    n = len(dates)
    fams = src["families"]
    os.makedirs(OUT_DIR, exist_ok=True)
    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB)
    con.executescript(SCHEMA)

    # ---- 场景分配：按真实月销量排序前 12 位分给 12 个形态 ----
    scen_by_fam = {}
    for i, (sid, name, desc) in enumerate(SCENARIOS):
        if i >= len(fams):
            break
        fa = fams[i]["family_asin"]
        scen_by_fam[fa] = sid
        con.execute(
            "INSERT INTO dim_competitor_scenario VALUES (?,?,?,?)", (sid, fa, name, desc)
        )

    # ---- 身份层 ----
    for idx, f in enumerate(fams):
        in_scope = 1 if idx < ANALYZED else 0
        con.execute(
            "INSERT INTO dim_competitor_family VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                f["family_asin"], f["brand"], f["title"], f["category_path"],
                f["sub_category"], f["variant_count"], f["captured_children"],
                f["price_band_low"], f["price_band_high"], f["unit_price_median"],
                f["first_listed_date"], f["seller_country"], f["buybox_type"],
                f["has_aplus"], f["has_video"], "monitoring", "2026-02-05",
                1 if idx < QUICK_SLOT else 0, in_scope, "卖家精灵导出 2026-08-03",
            ),
        )
        for ci, c in enumerate(f["children"]):
            size = color = None
            if c["sku"]:
                parts = [p.strip() for p in str(c["sku"]).split("|")]
                for p in parts:
                    if p.lower().startswith("size"):
                        size = p.split(":", 1)[-1].strip()
                    elif p.lower().startswith("color"):
                        color = p.split(":", 1)[-1].strip()
            con.execute(
                "INSERT INTO dim_competitor_child VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    c["child_asin"], f["family_asin"], size, color, c["pack_count"],
                    1 if c["pack_count"] else 0, c["snapshot_price"], c["unit_price"],
                    c["fba_fee"], c["gross_margin"], c["sales_rank_sub"],
                    1 if ci == 0 else 0,
                ),
            )
        # 报价层：BuyBox 卖家真实，其余按卖家数补
        head_child = f["children"][0]["child_asin"]
        con.execute(
            "INSERT INTO dim_competitor_offer VALUES (?,?,?,?,?,?,?,?,?)",
            (
                f"{head_child}-OF1", head_child, f["buybox_seller"],
                f["seller_country"], f["fulfillment"], 1, win_from, as_of, "direct",
            ),
        )
        for k in range(2, min((f["seller_count"] or 1), 4) + 1):
            con.execute(
                "INSERT INTO dim_competitor_offer VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    f"{head_child}-OF{k}", head_child, f"第三方卖家 {k-1}",
                    f["seller_country"], "FBM", 0, win_from, as_of, "derived",
                ),
            )

    # ---- 自有侧：只读产品包取脊椎，不在本包重建产品维度（契约 6.3）----
    pcon = sqlite3.connect(f"file:{PRODUCT_DB}?mode=ro", uri=True)
    own_units = {}
    q = (
        "SELECT c.child_asin, c.parent_asin, c.combination, p.selling_price"
        " FROM dim_product_child c JOIN fact_child_price_daily p"
        "   ON p.child_asin = c.child_asin AND p.date = ?"
    )
    for cid, pid, comb, price in pcon.execute(q, (as_of,)):
        digits = "".join(ch for ch in str(comb or "") if ch.isdigit())
        pack = int(digits) if digits else 1
        own_units[cid] = (pid, round(price / pack, 3), pack)
    spine = pcon.execute("SELECT COUNT(*) FROM dim_product_child").fetchone()[0]
    parents = pcon.execute("SELECT COUNT(*) FROM dim_product_parent").fetchone()[0]
    pcon.close()
    print(f"脊椎：产品包 {spine} 子 ASIN / {parents} 父 ASIN，其中 {len(own_units)} 个有基准日价格")

    # ---- 竞争关系：同子类目 + 件单价同带 ----
    rel_i = 0
    for f in fams:
        if not f["unit_price_median"]:
            continue
        picks = []
        for oc, (op, ou, opk) in own_units.items():
            if abs(ou - f["unit_price_median"]) / f["unit_price_median"] <= 0.75:
                picks.append((oc, op, ou, opk))
        picks.sort(key=lambda t: abs(t[2] - f["unit_price_median"]))
        for oc, op, ou, opk in picks[:4]:
            rel_i += 1
            con.execute(
                "INSERT INTO bridge_competitor_child VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    f"REL{rel_i:04d}", f["family_asin"], oc, op,
                    "同子类目 · 件单价同带 · 同装盒数区间",
                    f"竞品件单价 ${f['unit_price_median']:.2f} 对自有 ${ou:.2f}（{opk} 件装）",
                    "confirmed" if rel_i % 7 else "pending_review", "2026-02-05",
                    "constructed",
                ),
            )

    # ---- 关键词 ----
    fam_ids = [f["family_asin"] for f in fams]
    for kw in src["keywords"]:
        tags = kw["category_tags"] or ""
        battle = 1 if kw["own_family_hits"] >= 1 and (kw["monthly_search"] or 0) > 20000 else 0
        con.execute(
            "INSERT INTO dim_competitor_keyword VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                kw["keyword"], kw["keyword_cn"], tags, kw["aba_rank"],
                kw["monthly_search"], kw["monthly_purchase"], kw["purchase_rate"],
                kw["product_count"], kw["supply_demand_ratio"],
                kw["ad_competitor_count"], kw["ppc_bid"], battle,
            ),
        )
        for t in kw["top3"]:
            if t["family_asin"]:
                con.execute(
                    "INSERT OR IGNORE INTO bridge_competitor_keyword VALUES (?,?,?,?,?)",
                    (t["family_asin"], kw["keyword"], win_from, as_of, "top3"),
                )

    # ---- 逐日价格 ----
    price_rows = []
    for f in fams:
        sid = scen_by_fam.get(f["family_asin"])
        for ci, c in enumerate(f["children"]):
            p_end = c["snapshot_price"]
            if not p_end:
                continue
            pack = c["pack_count"]
            for di, d in enumerate(dates):
                frac = di / max(n - 1, 1)
                list_price = round(p_end * 1.18, 2)
                final = p_end
                deal = None
                coupon = None
                kind = "none"
                if sid == "S1":
                    if 100 <= di <= 122:
                        deal = round(p_end * 0.80, 2)
                        final = deal
                        coupon = 0.15
                        kind = "deal"
                    elif 123 <= di <= 130:
                        final = round(p_end * 0.94, 2)
                        kind = "coupon"
                        coupon = 0.06
                elif sid == "S2":
                    step = round(p_end * (1.22 - 0.22 * min(frac / 0.9, 1.0)), 2)
                    final = step
                elif sid == "S7":
                    if ci == 2 and di >= 140:
                        final = round(p_end * 0.85, 2)
                        kind = "coupon"
                        coupon = 0.15
                elif sid == "S8":
                    if 90 <= di <= 150 and ci == 0:
                        final = round(p_end * 0.91, 2)
                elif sid in ("S10", "S10b"):
                    if di >= 120:
                        final = round(p_end * (1.0 + 0.09 * (150 - di) / 30), 2) if di < 150 else p_end
                elif sid == "S9":
                    if 120 <= di <= 133:
                        continue  # 断更 14 天：这些天没有观察
                if di == n - 1:
                    final = p_end
                    deal = None
                    coupon = None
                    kind = "none"
                final = round(final * (1 + rng.uniform(-0.004, 0.004)), 2) if di < n - 1 else final
                price_rows.append(
                    (
                        c["child_asin"], d, list_price, deal, final,
                        round(final / pack, 3) if pack else None, coupon, kind,
                        "direct" if di == n - 1 else "constructed",
                        "卖家精灵快照" if di == n - 1 else "价格监控（构造序列）",
                        f"{d}T09:00:00Z",
                    )
                )
    con.executemany(
        "INSERT INTO fact_competitor_price_daily VALUES (?,?,?,?,?,?,?,?,?,?,?)", price_rows
    )

    # ---- 逐日市场表现 ----
    mkt_rows = []
    for f in fams:
        sid = scen_by_fam.get(f["family_asin"])
        r_end = f["rank_sub"] or 60
        rc_end = f["rating_count"] or 1000
        u_end = int(f["monthly_units"] or 500)
        rating_end = f["rating"] or 4.5
        new_r = f["new_rating"] or max(int(rc_end * 0.02), 5)
        for di, d in enumerate(dates):
            frac = di / max(n - 1, 1)
            if sid == "S3":
                rank = int(round(r_end * (2.4 - 1.4 * frac)))
                units = int(u_end * (0.55 + 0.45 * frac))
                rating = rating_end
            elif sid == "S4":
                rank = int(round(r_end * (0.55 + 0.45 * frac)))
                units = int(u_end * (1.35 - 0.35 * frac))
                rating = round(rating_end + 0.2 * (1 - frac), 1)
            elif sid == "S10":
                rank = int(round(r_end * (1.6 - 0.6 * min(frac / 0.75, 1.0))))
                units = int(u_end * (0.8 + 0.2 * frac))
                rating = rating_end
            elif sid == "S11":
                rank = r_end
                units = u_end
                rating = rating_end
            else:
                wob = 1 + 0.10 * (rng.random() - 0.5)
                rank = max(1, int(round(r_end * wob)))
                units = int(u_end * (0.92 + 0.16 * rng.random()))
                rating = rating_end
            if di == n - 1:
                rank, units, rating = r_end, u_end, rating_end
            rc = int(rc_end - new_r * (n - 1 - di) / 30.0)
            if sid == "S9" and 120 <= di <= 133:
                continue
            mkt_rows.append(
                (
                    f["family_asin"], d, rank, f["rank_main"], units, rating,
                    max(rc, 1), new_r,
                    "direct" if di == n - 1 else "constructed",
                    "卖家精灵快照" if di == n - 1 else "卖家精灵（构造序列）",
                )
            )
    con.executemany(
        "INSERT INTO fact_competitor_market_daily VALUES (?,?,?,?,?,?,?,?,?,?)", mkt_rows
    )

    # ---- 关键词位置（周粒度，末次观察对齐真实前三） ----
    weeks = [d for i, d in enumerate(dates) if i % 7 == 0]
    if weeks[-1] != as_of:
        weeks.append(as_of)
    kr_rows = []
    real_top = {}
    for kw in src["keywords"]:
        for pos, t in enumerate(kw["top3"], start=1):
            if t["family_asin"]:
                real_top[(t["family_asin"], kw["keyword"])] = (
                    pos, t["click_share"], t["conversion_share"]
                )
    for (fa, kwd), (pos, clk, cvr) in real_top.items():
        sid = scen_by_fam.get(fa)
        for wi, d in enumerate(weeks):
            wf = wi / max(len(weeks) - 1, 1)
            if sid == "S5":
                rank = max(pos, int(round(pos + 9 * (1 - wf))))
            elif sid == "S6":
                rank = pos if wf < 0.55 else pos + int(round(7 * (wf - 0.55) / 0.45))
            else:
                rank = max(1, pos + (1 if rng.random() < 0.25 else 0))
            if d == as_of:
                rank = pos
            share = clk if (clk and rank <= 3) else None
            kr_rows.append(
                (
                    fa, kwd, d, rank, "搜索结果顶部" if rank <= 3 and rng.random() < 0.4 else None,
                    1 if rank <= 3 else 0, share,
                    cvr if (cvr and rank <= 3) else None,
                    "direct" if d == as_of else "derived",
                    "ABA 前三（真实）" if d == as_of else "位置序列（构造）",
                )
            )
    con.executemany(
        "INSERT INTO fact_competitor_keyword_rank VALUES (?,?,?,?,?,?,?,?,?,?)", kr_rows
    )

    # ---- 流量结构（月度，全部第三方估算） ----
    tm_rows = []
    months = ["2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07"]
    for f in fams:
        for mi, m in enumerate(months):
            org = round(0.62 - 0.03 * mi + rng.uniform(-0.04, 0.04), 3)
            ad = round(0.26 + 0.025 * mi + rng.uniform(-0.03, 0.03), 3)
            other = round(1 - org - ad, 3)
            start = f"{m}-01"
            end = f"{m}-28"
            tm_rows.append(
                (f["family_asin"], start, end, org, ad, other, None, "constructed")
            )
    con.executemany(
        "INSERT INTO fact_competitor_traffic_mix VALUES (?,?,?,?,?,?,?,?)", tm_rows
    )

    # ---- 数据状态 ----
    st = []
    for fa, sid in scen_by_fam.items():
        if sid == "S9":
            st.append((f"ST-{fa}-1", "family", fa, "2026-06-05", "2026-06-18",
                       "interrupted", "观察中断 14 天，期间无价格与排名记录", "价格监控"))
            st.append((f"ST-{fa}-2", "family", fa, "2026-07-20", as_of,
                       "conflict", "两个来源的成交价不一致，差异未抹平", "价格监控 / 卖家精灵"))
            st.append((f"ST-{fa}-3", "family", fa, "2026-07-06", as_of,
                       "stale", "关键词位置最近更新于 4 周前", "关键词监控"))
    for f in fams[ANALYZED:ANALYZED + 3]:
        st.append((f"ST-{f['family_asin']}-1", "family", f["family_asin"],
                   "2026-05-01", as_of, "missing",
                   "未纳入持续监控，只有当期快照", "卖家精灵"))
    con.executemany("INSERT INTO fact_competitor_data_status VALUES (?,?,?,?,?,?,?,?)", st)

    counts = {}
    for t in [
        "dim_competitor_family", "dim_competitor_child", "dim_competitor_offer",
        "bridge_competitor_child", "dim_competitor_keyword", "bridge_competitor_keyword",
        "fact_competitor_price_daily", "fact_competitor_market_daily",
        "fact_competitor_keyword_rank", "fact_competitor_traffic_mix",
        "fact_competitor_data_status", "dim_competitor_scenario",
    ]:
        counts[t] = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]

    man = dict(
        dataset_version="observation-v0.1.0",
        generated_at=dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        as_of=as_of, window_from=win_from, window_to=as_of,
        family_count=str(len(fams)), analyzed_family_count=str(min(ANALYZED, len(fams))),
        quick_slot_count=str(min(QUICK_SLOT, len(fams))),
        product_spine="342 子 ASIN / 5 父 ASIN（ATTACH 产品包读，本包不重建）",
        source_package="9.竞品.xlsx / 关键词3.xlsx / v0.3.0",
        provenance="身份与前三位置为客户事实；逐日序列为构造，锚定快照值",
    )
    for k, v in man.items():
        con.execute("INSERT INTO competitor_manifest VALUES (?,?)", (k, str(v)))
    con.commit()
    con.close()
    for k, v in counts.items():
        print(f"{k:36s} {v:>7d}")
    print(f"DB {DB} ({os.path.getsize(DB)/1024/1024:.1f} MB)")


if __name__ == "__main__":
    main()
