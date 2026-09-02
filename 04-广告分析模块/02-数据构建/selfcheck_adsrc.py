#!/usr/bin/env python3
"""Self-check the source reader/parser layer before the real build."""
from __future__ import annotations

import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import adsrc  # noqa: E402

CSVS = [
    "商品推广_广告活动_报告.csv",
    "商品推广_预算_报告.csv",
    "商品推广_搜索词展示量份额_报告.csv",
    "品牌推广_归因于广告的购买_报告.csv",
    "品牌推广_品类基准_报告.csv",
    "品牌推广_搜索词展示量份额_报告.csv",
]


def main() -> int:
    print("=== value parsers ===")
    for v in ["$2,365.78  ", "$0.00 ", "", "377368", 1405.0, "-"]:
        print("  money %-14r -> %r" % (v, adsrc.parse_money(v)))
    for v in ["0.37%", "32.15%", "", 0.0037]:
        print("  pct   %-14r -> %r" % (v, adsrc.parse_pct(v)))
    for v in ["1-Jul-26", "Jul 1, 2026", "2026-07-01", 46204.0, "31-Jul-26", ""]:
        print("  date  %-14r -> %r" % (v, adsrc.parse_date(v)))

    print()
    print("=== csv encoding detection ===")
    for name in CSVS:
        p = adsrc.ad_file(name)
        enc = adsrc.csv_encoding(p)
        first = None
        for row in adsrc.csv_rows(p):
            first = row
            break
        keys = list(first.keys())[:5] if first else []
        print("  %-42s enc=%-10s cols=%d  head=%s"
              % (name, enc, len(first or {}), keys))

    print()
    print("=== campaign name decoding (all 63) ===")
    dim_hits = Counter()
    purposes = Counter()
    unknown = Counter()
    n = 0
    for row in adsrc.csv_rows(adsrc.ad_file("商品推广_广告活动_报告.csv")):
        name = (row.get("广告活动名称") or "").strip()
        if not name:
            continue
        n += 1
        info = adsrc.parse_campaign_name(name)
        for d in info["dims"]:
            dim_hits[d] += 1
        for t in info["unknown_tokens"]:
            unknown[t] += 1
        purpose, basis = adsrc.infer_purpose(info["dims"])
        purposes[purpose] += 1
        if n <= 10:
            print("  %-46s" % name[:46])
            print("      dims=%s" % info["dims"])
            print("      purpose=%s  (%s)" % (purpose, basis))
    print("  campaigns decoded = %d" % n)
    print("  dimension coverage: %s" % dict(dim_hits))
    print("  purpose distribution: %s" % dict(purposes))
    print("  unknown tokens: %s" % dict(unknown.most_common(20)))

    print()
    print("=== xlsx dict reader spot check ===")
    p = adsrc.ad_file("商品推广_投放_报告.xlsx")
    k = 0
    for row in adsrc.xlsx_dicts(p):
        k += 1
        if k <= 2:
            print("  start=%s end=%s camp=%r grp=%r target=%r match=%r spend=%r" % (
                adsrc.parse_date(row.get("开始日期")),
                adsrc.parse_date(row.get("结束日期")),
                row.get("广告活动名称"), row.get("广告组名称"),
                row.get("投放"), row.get("匹配类型"),
                adsrc.parse_money(row.get("花费"))))
    print("  rows read = %d" % k)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
