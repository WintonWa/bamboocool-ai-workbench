#!/usr/bin/env python3
"""Fact-layer stages for the advertising demo v0.2.0 build.

Imported by build_v0_2_0.py. Every function takes the Build instance.

The metric column names differ across Amazon's report families (7-day vs 14-day
attribution, 花费 vs 广告主总成本), so all reads go through METRIC_COLS which
lists the accepted aliases per logical metric.
"""
from __future__ import annotations

import json
import os
from collections import defaultdict

import adsrc

WINDOW = ("2026-07-01", "2026-07-31")
ATTRIB = {"SP": 7, "SB": 14, "SD": 14}
MIN_DAYS_FOR_TREND = 20

METRIC_COLS = {
    "impressions": ["展示量", "总展示量"],
    "clicks": ["点击量", "总点击量"],
    "spend": ["花费", "广告主总成本"],
    "orders": ["7天总订单数(#)", "14天总订单数(#)", "订单量",
               "7 天内的总订单数 (#)"],
    "ad_sales": ["7天总销售额", "14天总销售额", "销售额",
                 "7 天内的总销售额 "],
    "units": ["7天总销售量(#)", "14天总销售量(#)", "已售商品数量"],
    "ctr": ["点击率 (CTR)", "点击率(CTR)"],
    "cpc": ["单次点击成本 (CPC)"],
    "cvr": ["7天的转化率", "14天的转化率", "7 天转化率"],
    "acos": ["广告投入产出比 (ACOS) 总计", "广告成本销售比(ACOS)"],
    "roas": ["总广告投资回报率 (ROAS)", "ROAS", "投入产出比(ROAS)"],
    "ad_sku_sales": ["7天内广告SKU销售额"],
    "other_sku_sales": ["7天内其他SKU销售额", "7天内其他SKU销售额 "],
    "top_is": ["搜索结果首页首位展示量份额"],
}

_PCT = {"ctr", "cvr", "acos"}


def pick(row: dict, metric: str):
    for col in METRIC_COLS[metric]:
        if col in row and row[col] is not None:
            v = row[col]
            if isinstance(v, str) and not v.strip():
                continue
            return adsrc.parse_pct(v) if metric in _PCT else adsrc.parse_money(v)
    return None


def metrics(row: dict) -> dict:
    m = {k: pick(row, k) for k in METRIC_COLS}
    # recompute the ratios from the raw numerator/denominator when possible so
    # the stored value is reproducible rather than copied from a rounded column
    if m["impressions"]:
        m["ctr"] = m["ctr"] if m["ctr"] is not None else \
            (m["clicks"] / m["impressions"] if m["clicks"] is not None else None)
    if m["clicks"]:
        m["cpc"] = m["cpc"] if m["cpc"] is not None else \
            (m["spend"] / m["clicks"] if m["spend"] is not None else None)
        if m["cvr"] is None and m["orders"] is not None:
            m["cvr"] = m["orders"] / m["clicks"]
    if m["ad_sales"]:
        if m["acos"] is None and m["spend"] is not None:
            m["acos"] = m["spend"] / m["ad_sales"]
        if m["roas"] is None and m["spend"]:
            m["roas"] = m["ad_sales"] / m["spend"]
    return m


def rows_of(filename: str):
    path = adsrc.ad_file(filename)
    if not os.path.exists(path):
        return
    it = (adsrc.csv_rows(path) if filename.endswith(".csv")
          else adsrc.xlsx_dicts(path))
    for r in it:
        yield r


def in_window(row) -> tuple[str | None, str | None]:
    s = adsrc.parse_date(row.get("开始日期") or row.get("日期"))
    e = adsrc.parse_date(row.get("结束日期")) or s
    return s, e


# ============================================================ 3. ad objects

OBJECT_SOURCES = [
    # (filename, ad_type, level, group_col, target_col, match_col)
    ("商品推广_投放_报告.xlsx", "SP", "TARGET", "广告组名称", "投放", "匹配类型"),
    ("商品推广_推广的商品_报告.xlsx", "SP", "AD_GROUP", "广告组名称", None, None),
    ("商品推广_搜索词_报告.xlsx", "SP", "AD_GROUP", "广告组名称", None, None),
    ("商品推广_已购买商品_报告.xlsx", "SP", "AD_GROUP", "广告组名称", None, None),
    ("商品推广_视频_报告.xlsx", "SP", "AD_GROUP", "广告组名称", None, None),
    ("商品推广_提示词_报告.xlsx", "SP", "AD_GROUP", "广告组名称", None, None),
    ("品牌推广_关键词_报告.xlsx", "SB", "TARGET", "广告组名称", "投放", "匹配类型"),
    ("品牌推广_搜索词_报告.xlsx", "SB", "AD_GROUP", "广告组名称", None, None),
    ("品牌推广_提示词_报告.xlsx", "SB", "AD_GROUP", "广告组名称", None, None),
    ("展示型推广_投放_报告.xlsx", "SD", "TARGET", "广告组名称", "投放", None),
    ("展示型推广_推广的商品_报告.xlsx", "SD", "AD_GROUP", "广告组名称", None, None),
    ("展示型推广_已购买商品_报告.xlsx", "SD", "AD_GROUP", "广告组名称", None, None),
    ("展示型推广_匹配的目标_报告.xlsx", "SD", "TARGET", None, "投放", None),
]


def build_objects(b) -> dict:
    """Create every AD_GROUP / TARGET object seen in any report."""
    stats = defaultdict(int)
    for fname, atype, level, gcol, tcol, mcol in OBJECT_SOURCES:
        for r in rows_of(fname):
            camp = (str(r.get("广告活动名称") or "")).strip()
            if not camp:
                continue
            grp = (str(r.get(gcol) or "")).strip() if gcol else None
            tgt = (str(r.get(tcol) or "")).strip() if tcol else None
            mt = (str(r.get(mcol) or "")).strip() if mcol else None
            if grp:
                b.ensure_object("AD_GROUP", atype, camp, grp, src=fname)
                stats["AD_GROUP"] += 1
            if level == "TARGET" and tgt:
                b.ensure_object("TARGET", atype, camp, grp, tgt, mt, src=fname)
                stats["TARGET"] += 1
    b.db.commit()
    return dict(stats)


def build_placements(b) -> int:
    n = 0
    for fname, atype in (("商品推广_广告位_报告.xlsx", "SP"),
                         ("品牌推广_广告活动广告位_报告.xlsx", "SB"),
                         ("品牌推广_关键词广告位_报告.xlsx", "SB")):
        for r in rows_of(fname):
            camp = (str(r.get("广告活动名称") or "")).strip()
            place = (str(r.get("放置") or r.get("投放类型") or "")).strip()
            if not camp or not place:
                continue
            cid = b.campaigns.get((atype, camp))
            pid = b.sid_placement(atype, camp, place)
            b.db.execute(
                "INSERT OR IGNORE INTO dim_placement VALUES (?,?,?,?,?,?,?,?)",
                (pid, atype, cid, camp, place,
                 (str(r.get("竞价策略") or "")).strip() or None,
                 "direct", fname))
            s, e = in_window(r)
            m = metrics(r)
            b.db.execute(
                "INSERT OR IGNORE INTO fact_placement VALUES"
                " (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (b.sid("plf", pid, s, e), pid, cid, atype, place, s, e,
                 ATTRIB[atype], m["impressions"], m["clicks"], m["spend"],
                 m["orders"], m["ad_sales"], m["ctr"], m["cpc"], m["acos"],
                 m["roas"], "direct", fname))
            n += 1
    b.db.commit()
    return n


def build_audiences(b) -> int:
    n = 0
    for r in rows_of("商品推广_受众_报告.xlsx"):
        camp = (str(r.get("广告活动名称") or "")).strip()
        aud = (str(r.get("受众名称") or "")).strip()
        if not camp or not aud:
            continue
        cid = b.campaigns.get(("SP", camp))
        aid = b.sid("aud", "SP", camp, aud)
        b.db.execute("INSERT OR IGNORE INTO dim_audience VALUES (?,?,?,?,?,?,?)",
                     (aid, "SP", cid, camp, aud, "direct", "商品推广_受众_报告.xlsx"))
        s, e = in_window(r)
        m = metrics(r)
        b.db.execute(
            "INSERT OR IGNORE INTO fact_audience VALUES"
            " (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (b.sid("audf", aid, s, e), aid, cid, "SP", aud, s, e,
             m["impressions"], m["clicks"], m["spend"], m["orders"],
             m["ad_sales"], m["ctr"], m["cpc"], m["roas"],
             "direct", "商品推广_受众_报告.xlsx"))
        n += 1
    b.db.commit()
    return n


# ==================================================== 4. month-level facts

MONTH_FACT_SOURCES = [
    # (filename, ad_type, level, group_col, target_col, match_col)
    ("商品推广_投放_报告.xlsx", "SP", "TARGET", "广告组名称", "投放", "匹配类型"),
    ("商品推广_推广的商品_报告.xlsx", "SP", "AD_GROUP", "广告组名称", None, None),
    ("品牌推广_关键词_报告.xlsx", "SB", "TARGET", "广告组名称", "投放", "匹配类型"),
    ("展示型推广_投放_报告.xlsx", "SD", "TARGET", "广告组名称", "投放", None),
    ("展示型推广_推广的商品_报告.xlsx", "SD", "AD_GROUP", "广告组名称", None, None),
    ("展示型推广_匹配的目标_报告.xlsx", "SD", "TARGET", None, "投放", None),
]

# Some ad groups run video creatives only and never appear in 推广的商品; the
# video report is their sole month-level source. Used as a FALLBACK so groups
# present in both are not counted twice.
MONTH_FALLBACK_SOURCES = [
    ("商品推广_视频_报告.xlsx", "SP", "AD_GROUP", "广告组名称", None, None),
    ("商品推广_提示词_报告.xlsx", "SP", "AD_GROUP", "广告组名称", None, None),
]


def build_month_facts(b) -> dict:
    """Authoritative month totals, summed per object across report rows."""
    acc: dict[tuple, dict] = {}
    covered: set[str] = set()

    def scan(sources, fallback=False):
        for fname, atype, level, gcol, tcol, mcol in sources:
            for r in rows_of(fname):
                camp = (str(r.get("广告活动名称") or "")).strip()
                if not camp:
                    continue
                grp = (str(r.get(gcol) or "")).strip() if gcol else None
                tgt = (str(r.get(tcol) or "")).strip() if tcol else None
                mt = (str(r.get(mcol) or "")).strip() if mcol else None
                oid = b.ensure_object(level, atype, camp, grp, tgt, mt,
                                      src=fname)
                if fallback and oid in covered:
                    continue
                s, e = in_window(r)
                key = (oid, level, atype)
                cur = acc.setdefault(key, {
                    "cov_s": s, "cov_e": e, "n": 0, "src": fname,
                    "impressions": 0.0, "clicks": 0.0, "spend": 0.0,
                    "orders": 0.0, "ad_sales": 0.0,
                    "ad_sku_sales": 0.0, "other_sku_sales": 0.0,
                    "top_is_sum": 0.0, "top_is_n": 0})
                m = metrics(r)
                for k in ("impressions", "clicks", "spend", "orders",
                          "ad_sales", "ad_sku_sales", "other_sku_sales"):
                    if m[k] is not None:
                        cur[k] += m[k]
                if m["top_is"] is not None:
                    cur["top_is_sum"] += m["top_is"]
                    cur["top_is_n"] += 1
                if s and (cur["cov_s"] is None or s < cur["cov_s"]):
                    cur["cov_s"] = s
                if e and (cur["cov_e"] is None or e > cur["cov_e"]):
                    cur["cov_e"] = e
                cur["n"] += 1
                if not fallback:
                    covered.add(oid)

    scan(MONTH_FACT_SOURCES)
    scan(MONTH_FALLBACK_SOURCES, fallback=True)

    rows = []
    for (oid, level, atype), c in acc.items():
        full = (c["cov_s"] == WINDOW[0] and c["cov_e"] == WINDOW[1])
        rows.append((
            b.sid("fact", oid, WINDOW[0], WINDOW[1], "report_month_total"),
            oid, level, atype, WINDOW[0], WINDOW[1], c["cov_s"], c["cov_e"],
            ATTRIB[atype],
            "comparable" if full else "partial_source_coverage",
            "report_month_total",
            c["impressions"], c["clicks"], c["spend"], c["orders"], c["ad_sales"],
            (c["clicks"] / c["impressions"]) if c["impressions"] else None,
            (c["spend"] / c["clicks"]) if c["clicks"] else None,
            (c["orders"] / c["clicks"]) if c["clicks"] else None,
            (c["spend"] / c["ad_sales"]) if c["ad_sales"] else None,
            (c["ad_sales"] / c["spend"]) if c["spend"] else None,
            c["ad_sku_sales"] or None, c["other_sku_sales"] or None,
            (c["top_is_sum"] / c["top_is_n"]) if c["top_is_n"] else None,
            "USD", "AMAZON", "direct", c["src"],
            "sum of %d report row(s)" % c["n"]))
    b.db.executemany(
        "INSERT OR REPLACE INTO fact_ad_performance VALUES"
        " (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    b.db.commit()
    out = defaultdict(int)
    for r in rows:
        out[r[2]] += 1
    return dict(out)


def build_campaign_rollup(b) -> int:
    """Campaign-level month facts, from the campaign reports themselves."""
    rows = []
    for fname, atype in (("商品推广_广告活动_报告.csv", "SP"),
                         ("品牌推广_广告活动_报告.xlsx", "SB"),
                         ("展示型推广_广告活动_报告.xlsx", "SD")):
        for r in rows_of(fname):
            camp = (str(r.get("广告活动名称") or "")).strip()
            if not camp:
                continue
            atype2 = adsrc_norm(r, atype)
            oid = b.objects.get(("CAMPAIGN", atype2, camp, "", "", ""))
            if oid is None:
                continue
            s, e = in_window(r)
            m = metrics(r)
            rows.append((
                b.sid("fact", oid, WINDOW[0], WINDOW[1], "report_month_total"),
                oid, "CAMPAIGN", atype2, WINDOW[0], WINDOW[1],
                s or WINDOW[0], e or WINDOW[1], ATTRIB[atype2],
                "comparable", "report_month_total",
                m["impressions"], m["clicks"], m["spend"], m["orders"],
                m["ad_sales"], m["ctr"], m["cpc"], m["cvr"], m["acos"],
                m["roas"], None, None, None,
                "USD", "AMAZON", "direct", fname, "campaign report row"))
    b.db.executemany(
        "INSERT OR REPLACE INTO fact_ad_performance VALUES"
        " (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    b.db.commit()
    return len(rows)


def adsrc_norm(row, fallback):
    v = (str(row.get("广告活动类型") or "")).strip()
    if "品牌" in v:
        return "SB"
    if "展示" in v:
        return "SD"
    if "商品" in v:
        return "SP"
    return fallback


# ============================================================ 5. daily facts

DAILY_SOURCES = [
    ("商品推广_搜索词_报告.xlsx", "SP"),
    ("品牌推广_搜索词_报告.xlsx", "SB"),
    ("商品推广_已购买商品_报告.xlsx", "SP"),
    ("展示型推广_已购买商品_报告.xlsx", "SD"),
    ("展示型推广_匹配的目标_报告.xlsx", "SD"),
]

_DAILY_METRIC_FILES = {"商品推广_搜索词_报告.xlsx", "品牌推广_搜索词_报告.xlsx",
                       "展示型推广_匹配的目标_报告.xlsx"}


def build_daily_facts(b) -> dict:
    """Daily series from exact-day rows, at AD_GROUP and TARGET grain.

    Stored twice per object/day:
      search_term_exact_day_sum  -- direct, what the report literally says
      daily_scaled_to_month      -- derived, rescaled so the month sums to the
                                    authoritative month total
    """
    # (oid, level, atype, date) -> metric accumulator
    acc: dict[tuple, dict] = {}
    src_of: dict[str, str] = {}

    for fname, atype in DAILY_SOURCES:
        if fname not in _DAILY_METRIC_FILES:
            continue
        for r in rows_of(fname):
            s, e = in_window(r)
            if not s or s != e:
                continue
            camp = (str(r.get("广告活动名称") or "")).strip()
            if not camp:
                continue
            grp = (str(r.get("广告组名称") or "")).strip() or None
            tgt = (str(r.get("投放") or "")).strip() or None
            mt = (str(r.get("匹配类型") or "")).strip() or None
            m = metrics(r)
            targets = []
            if grp:
                targets.append(("AD_GROUP", b.ensure_object(
                    "AD_GROUP", atype, camp, grp, src=fname)))
            if tgt:
                targets.append(("TARGET", b.ensure_object(
                    "TARGET", atype, camp, grp, tgt, mt, src=fname)))
            for level, oid in targets:
                key = (oid, level, atype, s)
                cur = acc.setdefault(key, dict.fromkeys(
                    ("impressions", "clicks", "spend", "orders", "ad_sales"), 0.0))
                for k in cur:
                    if m[k] is not None:
                        cur[k] += m[k]
                src_of[oid] = fname

    # day coverage per object
    days: dict[str, set] = defaultdict(set)
    raw_tot: dict[str, dict] = defaultdict(
        lambda: dict.fromkeys(("impressions", "clicks", "spend", "orders",
                               "ad_sales"), 0.0))
    for (oid, _lvl, _at, d), c in acc.items():
        days[oid].add(d)
        for k, v in c.items():
            raw_tot[oid][k] += v

    month = {}
    for oid, imp, clk, sp, orl, sal in b.db.execute(
            "SELECT ad_object_id, impressions, clicks, spend, orders, ad_sales"
            " FROM fact_ad_performance WHERE metric_basis='report_month_total'"):
        month[oid] = {"impressions": imp, "clicks": clk, "spend": sp,
                      "orders": orl, "ad_sales": sal}

    rows = []
    for (oid, level, atype, d), c in sorted(acc.items()):
        cov = len(days[oid])
        conf = "normal" if cov >= MIN_DAYS_FOR_TREND else "low"
        rows.append(_daily_row(b, oid, level, atype, d, c,
                               "search_term_exact_day_sum", cov, conf,
                               None, "direct", src_of.get(oid, "")))
        mt_ = month.get(oid) or {}
        factors = {}
        for k in ("impressions", "clicks", "spend", "orders", "ad_sales"):
            base = raw_tot[oid][k]
            tgt_total = mt_.get(k)
            factors[k] = (tgt_total / base) if (base and tgt_total) else None
        scaled = {k: (c[k] * factors[k]) if factors[k] else None
                  for k in c}
        if any(v is not None for v in scaled.values()):
            rows.append(_daily_row(b, oid, level, atype, d, scaled,
                                   "daily_scaled_to_month", cov, conf,
                                   factors["spend"], "derived",
                                   src_of.get(oid, "") +
                                   "+fact_ad_performance"))
    b.db.executemany(
        "INSERT OR REPLACE INTO fact_ad_daily VALUES"
        " (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    b.db.commit()
    return {"objects_with_daily": len(days),
            "daily_rows": len(rows),
            "full_31_day_objects": sum(1 for v in days.values() if len(v) == 31)}


def _daily_row(b, oid, level, atype, d, c, basis, cov, conf, factor,
               status, src):
    imp, clk = c.get("impressions"), c.get("clicks")
    sp, orl, sal = c.get("spend"), c.get("orders"), c.get("ad_sales")

    def div(a, bb):
        return (a / bb) if (a is not None and bb) else None

    return (b.sid("day", oid, d, basis), oid, level, atype, d, basis,
            imp, clk, sp, orl, sal,
            div(clk, imp), div(sp, clk), div(orl, clk),
            div(sp, sal), div(sal, sp),
            factor, cov, conf, "USD", status, src)
