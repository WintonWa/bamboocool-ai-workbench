#!/usr/bin/env python3
"""How far can a daily series be rebuilt from the search-term report?

Q1: per ad group, how many of the 31 July days have exact-day rows?
Q2: aggregating search-term exact-day rows up to (campaign, group, 投放, 匹配类型)
    -- i.e. Target grain -- how many of the 679 targets in 投放_报告 are covered?
Q3: does summing exact-day search-term rows for a whole group reproduce the
    month total that 投放_报告 reports? (coverage sanity check, spend only)

Usage: /usr/bin/python3 probe_daily_coverage.py
"""
from __future__ import annotations

import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import xlsxlite  # noqa: E402
from probe_dates import norm_date  # noqa: E402

SRC = "/Users/linsen/BAM/数据源/AI广告对接数据-总20260803/13.广告"
ST = os.path.join(SRC, "商品推广_搜索词_报告.xlsx")
TG = os.path.join(SRC, "商品推广_投放_报告.xlsx")


def load(path):
    """Return (header_index_map, list_of_rows)."""
    header = None
    out = []
    for row in xlsxlite.iter_rows(path):
        if header is None:
            if any(v is not None for v in row):
                header = [str(v) if v is not None else "" for v in row]
            continue
        out.append(row)
    return {h: i for i, h in enumerate(header or [])}, out


def get(row, i):
    return row[i] if i is not None and i < len(row) else None


def fnum(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def main() -> int:
    hi, st_rows = load(ST)
    i_s, i_e = hi.get("开始日期"), hi.get("结束日期")
    i_c, i_g = hi.get("广告活动名称"), hi.get("广告组名称")
    i_t, i_m = hi.get("投放"), hi.get("匹配类型")
    i_spend = hi.get("花费")

    days_per_group: dict[tuple, set] = defaultdict(set)
    st_targets_exact: set[tuple] = set()
    st_spend_exact: dict[tuple, float] = defaultdict(float)
    st_spend_all: dict[tuple, float] = defaultdict(float)
    match_types: dict[str, int] = defaultdict(int)

    for row in st_rows:
        s, e = norm_date(get(row, i_s)), norm_date(get(row, i_e))
        if not s or not e:
            continue
        camp, grp = str(get(row, i_c)), str(get(row, i_g))
        tgt, mt = get(row, i_t), get(row, i_m)
        gkey = (camp, grp)
        tkey = (camp, grp, str(tgt), str(mt))
        spend = fnum(get(row, i_spend))
        st_spend_all[gkey] += spend
        if s == e:
            days_per_group[gkey].add(s)
            st_targets_exact.add(tkey)
            st_spend_exact[gkey] += spend
            match_types[str(mt)] += 1

    print("=== Q1  per-group day coverage (exact-day rows, July 2026) ===")
    buckets = defaultdict(int)
    for gkey, days in days_per_group.items():
        buckets[len(days)] += 1
    for n in sorted(buckets, reverse=True):
        print("  %2d days covered : %d groups" % (n, buckets[n]))
    full = sum(1 for d in days_per_group.values() if len(d) == 31)
    print("  groups with all 31 days = %d / %d" % (full, len(days_per_group)))

    print()
    print("=== Q2  Target grain reachable from exact-day search-term rows ===")
    ti, tg_rows = load(TG)
    j_c, j_g = ti.get("广告活动名称"), ti.get("广告组名称")
    j_t, j_m = ti.get("投放"), ti.get("匹配类型")
    j_spend = ti.get("花费")
    tg_targets: set[tuple] = set()
    tg_spend: dict[tuple, float] = defaultdict(float)
    tg_group_spend: dict[tuple, float] = defaultdict(float)
    for row in tg_rows:
        key = (str(get(row, j_c)), str(get(row, j_g)),
               str(get(row, j_t)), str(get(row, j_m)))
        tg_targets.add(key)
        tg_spend[key] += fnum(get(row, j_spend))
        tg_group_spend[(key[0], key[1])] += fnum(get(row, j_spend))
    inter = tg_targets & st_targets_exact
    print("  targets in 投放_报告            = %d" % len(tg_targets))
    print("  targets w/ exact-day ST rows   = %d" % len(st_targets_exact))
    print("  intersection (daily-rebuildable) = %d  (%.1f%% of 投放)" %
          (len(inter), 100.0 * len(inter) / len(tg_targets) if tg_targets else 0))
    only_st = len(st_targets_exact - tg_targets)
    only_tg = len(tg_targets - st_targets_exact)
    print("  only in ST = %d    only in 投放 = %d" % (only_st, only_tg))
    print("  ST exact-day rows by match type: %s" %
          ", ".join("%s:%d" % kv for kv in sorted(match_types.items(),
                                                  key=lambda kv: -kv[1])))

    print()
    print("=== Q3  group spend: exact-day ST sum vs 投放_报告 month total ===")
    print("  %-46s %12s %12s %7s" % ("group", "ST exact", "投放 month", "ratio"))
    shown = 0
    ratios = []
    for gkey in sorted(tg_group_spend, key=lambda k: -tg_group_spend[k]):
        a = st_spend_exact.get(gkey, 0.0)
        b = tg_group_spend[gkey]
        if b <= 0:
            continue
        ratios.append(a / b)
        if shown < 12:
            label = ("%s / %s" % gkey)[:46]
            print("  %-46s %12.2f %12.2f %7.3f" % (label, a, b, a / b))
            shown += 1
    if ratios:
        ratios.sort()
        mid = ratios[len(ratios) // 2]
        print("  ratio: min=%.3f median=%.3f max=%.3f  over %d groups" %
              (ratios[0], mid, ratios[-1], len(ratios)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
