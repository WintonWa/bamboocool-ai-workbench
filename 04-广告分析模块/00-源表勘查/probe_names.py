#!/usr/bin/env python3
"""Decode the GBK csv reports and dump campaign / ad-group naming structure.

Needed before writing the v0.2.0 builder: the label taxonomy should be derived
from the operator's real naming convention, not invented.

Usage: /usr/bin/python3 probe_names.py
"""
from __future__ import annotations

import csv
import io
import os
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import xlsxlite  # noqa: E402

SRC = "/Users/linsen/BAM/数据源/AI广告对接数据-总20260803/13.广告"

GBK_CSVS = [
    "商品推广_广告活动_报告.csv",
    "商品推广_预算_报告.csv",
    "品牌推广_归因于广告的购买_报告.csv",
    "品牌推广_品类基准_报告.csv",
]


def read_gbk_csv(path: str):
    with io.open(path, encoding="gbk", errors="replace", newline="") as fh:
        return list(csv.reader(fh))


def main() -> int:
    print("########## GBK csv decode ##########")
    for name in GBK_CSVS:
        path = os.path.join(SRC, name)
        rows = read_gbk_csv(path)
        print("=" * 74)
        print("%s  rows=%d" % (name, len(rows) - 1))
        print("  header: %s" % " | ".join(rows[0]))
        for r in rows[1:3]:
            print("  row: %s" % " | ".join(str(x) for x in r))

    print()
    print("########## SP campaign inventory (from 广告活动_报告.csv) ##########")
    rows = read_gbk_csv(os.path.join(SRC, "商品推广_广告活动_报告.csv"))
    hdr = rows[0]
    ix = {h: i for i, h in enumerate(hdr)}
    i_name = next((ix[h] for h in hdr if "广告活动名称" in h), None)
    i_state = next((ix[h] for h in hdr if h.strip() == "状态"), None)
    i_budget = next((ix[h] for h in hdr if h.strip() == "预算"), None)
    i_bid = next((ix[h] for h in hdr if "竞价策略" in h), None)
    print("  cols -> name=%s state=%s budget=%s bid=%s" % (i_name, i_state, i_budget, i_bid))
    names = []
    for r in rows[1:]:
        if i_name is None or i_name >= len(r):
            continue
        nm = r[i_name].strip()
        if not nm:
            continue
        names.append(nm)
        if len(names) <= 63:
            print("  %-52s | %-8s | %-8s | %s" % (
                nm[:52],
                r[i_state] if i_state is not None and i_state < len(r) else "",
                r[i_budget] if i_budget is not None and i_budget < len(r) else "",
                r[i_bid] if i_bid is not None and i_bid < len(r) else "",
            ))
    print("  total campaigns = %d" % len(names))

    print()
    print("########## naming token frequency ##########")
    tok = Counter()
    for nm in names:
        for piece in re.split(r"[-_/\s]+", nm):
            p = piece.strip()
            if p:
                tok[p] += 1
    for t, c in tok.most_common(40):
        print("  %-14s %d" % (t, c))

    print()
    print("########## ad groups per campaign (from 投放_报告) ##########")
    path = os.path.join(SRC, "商品推广_投放_报告.xlsx")
    header = None
    pairs: dict[str, set] = defaultdict(set)
    for row in xlsxlite.iter_rows(path):
        if header is None:
            header = [str(v) if v is not None else "" for v in row]
            hh = {h: i for i, h in enumerate(header)}
            ic, ig = hh.get("广告活动名称"), hh.get("广告组名称")
            continue
        c = row[ic] if ic is not None and ic < len(row) else None
        g = row[ig] if ig is not None and ig < len(row) else None
        if c is not None:
            pairs[str(c)].add(str(g))
    for c in sorted(pairs):
        print("  %-50s -> %d group(s): %s" % (
            c[:50], len(pairs[c]),
            "; ".join(sorted(str(x)[:28] for x in pairs[c])[:3])))
    print("  campaigns in 投放 = %d, (campaign,group) pairs = %d" %
          (len(pairs), sum(len(v) for v in pairs.values())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
