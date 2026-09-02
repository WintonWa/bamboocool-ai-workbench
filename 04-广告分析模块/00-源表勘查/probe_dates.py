#!/usr/bin/env python3
"""Measure date-window shape per ad report: exact-day rows vs multi-day spans,
and how many distinct ad groups / campaigns the exact-day rows cover.

This answers: can a period-over-period (环比) comparison be built from real
customer rows, and for how many objects?

Usage: /usr/bin/python3 probe_dates.py
"""
from __future__ import annotations

import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import xlsxlite  # noqa: E402

SRC = "/Users/linsen/BAM/数据源/AI广告对接数据-总20260803/13.广告"

TARGETS = [
    "商品推广_搜索词_报告.xlsx",
    "商品推广_投放_报告.xlsx",
    "商品推广_推广的商品_报告.xlsx",
    "商品推广_已购买商品_报告.xlsx",
    "商品推广_视频_报告.xlsx",
    "商品推广_广告位_报告.xlsx",
    "商品推广_总流量和无效流量_报告.xlsx",
    "商品推广_受众_报告.xlsx",
    "品牌推广_关键词_报告.xlsx",
    "品牌推广_搜索词_报告.xlsx",
    "品牌推广_广告活动_报告.xlsx",
    "品牌推广_广告活动广告位_报告.xlsx",
    "展示型推广_匹配的目标_报告.xlsx",
    "展示型推广_推广的商品_报告.xlsx",
    "展示型推广_投放_报告.xlsx",
    "展示型推广_已购买商品_报告.xlsx",
    "展示型推广_广告活动_报告.xlsx",
]


def norm_date(v):
    """Normalise a cell to an ISO date string."""
    if v is None:
        return None
    if isinstance(v, float):
        return xlsxlite.serial_to_date(v)
    s = str(v).strip()
    if not s:
        return None
    # already looks like a date
    if len(s) >= 8 and (s[4:5] in "-/" or s[2:3] in "-/"):
        return s.replace("/", "-")[:10]
    return xlsxlite.serial_to_date(s) or s


def probe(name: str) -> None:
    path = os.path.join(SRC, name)
    rows = xlsxlite.iter_rows(path)
    header = None
    for row in rows:
        if any(v is not None for v in row):
            header = [str(v) if v is not None else "" for v in row]
            break
    if not header:
        print("  %s: empty" % name)
        return
    idx = {h: i for i, h in enumerate(header)}
    i_start = idx.get("开始日期")
    i_end = idx.get("结束日期")
    i_camp = idx.get("广告活动名称")
    i_grp = idx.get("广告组名称")
    if i_start is None or i_end is None:
        print("  %s: no date columns" % name)
        return

    total = 0
    exact = 0
    span = 0
    exact_days: set[str] = set()
    exact_groups: set[tuple] = set()
    exact_camps: set[str] = set()
    all_groups: set[tuple] = set()
    span_len: dict[int, int] = defaultdict(int)
    min_d, max_d = None, None

    def cell(row, i):
        return row[i] if i is not None and i < len(row) else None

    for row in xlsxlite.iter_rows(path):
        s = norm_date(cell(row, i_start))
        e = norm_date(cell(row, i_end))
        if not s or not e or s == "开始日期":
            continue
        total += 1
        min_d = s if min_d is None or s < min_d else min_d
        max_d = e if max_d is None or e > max_d else max_d
        camp = cell(row, i_camp)
        grp = cell(row, i_grp)
        key = (str(camp), str(grp)) if i_grp is not None else (str(camp),)
        all_groups.add(key)
        if s == e:
            exact += 1
            exact_days.add(s)
            exact_groups.add(key)
            if camp is not None:
                exact_camps.add(str(camp))
        else:
            span += 1
            try:
                import datetime as dt
                d1 = dt.date.fromisoformat(s)
                d2 = dt.date.fromisoformat(e)
                span_len[(d2 - d1).days + 1] += 1
            except Exception:  # noqa: BLE001
                span_len[-1] += 1

    print("-" * 74)
    print("%s" % name)
    print("  rows=%d  window=%s..%s" % (total, min_d, max_d))
    print("  exact-day rows=%d (%.1f%%)   multi-day rows=%d" %
          (exact, 100.0 * exact / total if total else 0, span))
    print("  distinct objects overall = %d" % len(all_groups))
    print("  distinct objects with exact-day rows = %d" % len(exact_groups))
    if i_grp is not None:
        print("  distinct campaigns with exact-day rows = %d" % len(exact_camps))
    if exact_days:
        ds = sorted(exact_days)
        print("  exact-day dates: %d distinct, %s .. %s" % (len(ds), ds[0], ds[-1]))
    if span_len:
        top = sorted(span_len.items(), key=lambda kv: -kv[1])[:6]
        print("  span lengths (days:count): %s" %
              ", ".join("%s:%d" % (k, v) for k, v in top))


def main() -> int:
    for name in TARGETS:
        try:
            probe(name)
        except Exception as exc:  # noqa: BLE001
            print("  %s: ERROR %r" % (name, exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
