#!/usr/bin/env python3
"""Diagnose the two failing gates: FK violations and the missing bridge roles."""
from __future__ import annotations

import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "lib"))
import adsrc  # noqa: E402

NEW = os.path.join(HERE, "v0.2.0", "advertising_demo.sqlite")
OLD = os.path.join(HERE, "v0.1.0", "advertising_demo.sqlite")


def main() -> int:
    db = sqlite3.connect("file:%s?mode=ro" % NEW, uri=True)
    print("=== foreign_key_check ===")
    for row in db.execute("PRAGMA foreign_key_check"):
        print("  %s" % (row,))
        table, rowid, parent, fkid = row
        cols = [r[1] for r in db.execute("PRAGMA table_info(%s)" % table)]
        rec = db.execute("SELECT * FROM %s WHERE rowid=?" % table,
                         (rowid,)).fetchone()
        if rec:
            print("      %s" % dict(zip(cols, rec)))

    print()
    print("=== v0.1.0 positive_spend_asin relations point at what? ===")
    old = sqlite3.connect("file:%s?mode=ro" % OLD, uri=True)
    for row in old.execute("""
        SELECT b.relation_role, b.source_role, b.source_ref, o.object_level,
               o.ad_type, o.campaign_name, COUNT(*)
        FROM bridge_ad_object_product b
        LEFT JOIN dim_ad_object o ON o.ad_object_id = b.ad_object_id
        GROUP BY b.relation_role, b.source_role, o.object_level
        ORDER BY b.relation_role"""):
        print("  %s" % (row,))

    print()
    print("=== SD 匹配的目标 sample values ===")
    seen = set()
    for r in adsrc.xlsx_dicts(adsrc.ad_file("展示型推广_匹配的目标_报告.xlsx")):
        v = str(r.get("匹配的目标") or "").strip()
        t = str(r.get("投放") or "").strip()
        if v and (v, t) not in seen and len(seen) < 12:
            seen.add((v, t))
            print("  投放=%-34r 匹配的目标=%r" % (t[:34], v))
    print()
    print("=== SP 投放 value shapes ===")
    shapes = {}
    for r in adsrc.xlsx_dicts(adsrc.ad_file("商品推广_投放_报告.xlsx")):
        t = str(r.get("投放") or "").strip()
        m = str(r.get("匹配类型") or "").strip()
        key = ("asin=" if t.lower().startswith("asin=") else
               "category=" if t.lower().startswith("category=") else
               "star" if t in {"*", "-"} else "text")
        shapes.setdefault((key, m), 0)
        shapes[(key, m)] += 1
    for k in sorted(shapes, key=lambda x: -shapes[x]):
        print("  %-24s %d" % (str(k), shapes[k]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
