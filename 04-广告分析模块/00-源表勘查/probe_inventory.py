#!/usr/bin/env python3
"""Inventory every ad report under 13.广告: sheets, row counts, column headers.

Pure registration -- records what is there, makes no judgement about gaps.
Usage: /usr/bin/python3 probe_inventory.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import xlsxlite  # noqa: E402

SRC = "/Users/linsen/BAM/数据源/AI广告对接数据-总20260803/13.广告"

# Ad-group / campaign / date column names we care about for the 环比 question.
KEY_HINTS = ("开始日期", "结束日期", "广告活动名称", "广告组名称", "投放", "广告位", "预算")


def main() -> int:
    names = sorted(n for n in os.listdir(SRC) if not n.startswith("."))
    for name in names:
        path = os.path.join(SRC, name)
        size = os.path.getsize(path)
        print("=" * 78)
        print("FILE %s  (%d bytes)" % (name, size))
        if name.lower().endswith(".csv"):
            try:
                header, _, total = xlsxlite.read_csv_head(path, limit=0)
            except Exception as exc:  # noqa: BLE001
                print("  CSV read error: %r" % (exc,))
                continue
            print("  rows=%d cols=%d" % (total, len(header)))
            print("  header: %s" % (" | ".join(header),))
            continue
        try:
            summary = xlsxlite.sheet_summary(path)
        except Exception as exc:  # noqa: BLE001
            print("  XLSX read error: %r" % (exc,))
            continue
        for s in summary:
            print("  sheet=%r rows=%d cols=%d" % (s["sheet"], s["rows"], len(s["header"])))
            print("    header: %s" % (" | ".join(s["header"]),))
            hits = [h for h in s["header"] if any(k in h for k in KEY_HINTS)]
            if hits:
                print("    key cols: %s" % (", ".join(hits),))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
