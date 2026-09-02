#!/usr/bin/env python3
"""Probe the v0.2.0 layer for the shapes page 1 depends on."""
from __future__ import annotations

import os
import sqlite3

DB = ("/Users/linsen/BAM/04-广告分析模块/"
      "02-数据构建/v0.2.0/advertising_demo.sqlite")


def q(db, sql, *a):
    return list(db.execute(sql, a))


def main() -> int:
    db = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)

    print("=== objects by level x type ===")
    for r in q(db, "SELECT object_level, ad_type, COUNT(*) FROM dim_ad_object"
                   " GROUP BY 1,2 ORDER BY 1,2"):
        print("  %s" % (r,))

    print()
    print("=== month facts by level x type ===")
    for r in q(db, "SELECT object_level, ad_type, COUNT(*) FROM"
                   " fact_ad_performance WHERE metric_basis='report_month_total'"
                   " GROUP BY 1,2 ORDER BY 1,2"):
        print("  %s" % (r,))

    print()
    print("=== ad groups WITHOUT a direct month fact ===")
    rows = q(db, """
        SELECT o.ad_type, o.campaign_name, o.ad_group_name,
               (SELECT COUNT(*) FROM dim_ad_object t
                 WHERE t.parent_ad_object_id = o.ad_object_id) AS n_targets
        FROM dim_ad_object o
        WHERE o.object_level='AD_GROUP'
          AND o.ad_object_id NOT IN (
              SELECT ad_object_id FROM fact_ad_performance
              WHERE metric_basis='report_month_total')
        ORDER BY o.ad_type, o.campaign_name""")
    print("  count=%d" % len(rows))
    for r in rows[:12]:
        print("  %s | %s | %s | targets=%s" % r)

    print()
    print("=== target parent linkage ===")
    print("  targets with parent set   : %s" % q(
        db, "SELECT COUNT(*) FROM dim_ad_object WHERE object_level='TARGET'"
            " AND parent_ad_object_id IS NOT NULL")[0][0])
    print("  targets without parent    : %s" % q(
        db, "SELECT COUNT(*) FROM dim_ad_object WHERE object_level='TARGET'"
            " AND parent_ad_object_id IS NULL")[0][0])
    for r in q(db, "SELECT ad_type, COUNT(*) FROM dim_ad_object"
                   " WHERE object_level='TARGET' AND parent_ad_object_id IS NULL"
                   " GROUP BY 1"):
        print("    orphan by type %s" % (r,))

    print()
    print("=== group rollup vs direct group fact (SP, spend) ===")
    for r in q(db, """
        SELECT o.ad_group_name,
               ROUND(g.spend,2) AS direct_group,
               ROUND((SELECT SUM(f.spend) FROM dim_ad_object t
                        JOIN fact_ad_performance f
                          ON f.ad_object_id=t.ad_object_id
                         AND f.metric_basis='report_month_total'
                       WHERE t.parent_ad_object_id=o.ad_object_id),2) AS rollup
        FROM dim_ad_object o
        JOIN fact_ad_performance g ON g.ad_object_id=o.ad_object_id
                                  AND g.metric_basis='report_month_total'
        WHERE o.object_level='AD_GROUP' AND o.ad_type='SP'
        ORDER BY g.spend DESC LIMIT 10"""):
        print("  %-38s direct=%-11s rollup=%s" % r)

    print()
    print("=== daily coverage by level ===")
    for r in q(db, "SELECT object_level, metric_basis, COUNT(DISTINCT ad_object_id),"
                   " COUNT(*) FROM fact_ad_daily GROUP BY 1,2"):
        print("  %s" % (r,))

    print()
    print("=== label vocabulary (top values per type) ===")
    for (lt,) in q(db, "SELECT DISTINCT label_type FROM fact_ad_label_version"
                       " ORDER BY 1"):
        vals = q(db, "SELECT label_value, COUNT(*) FROM fact_ad_label_version"
                     " WHERE label_type=? GROUP BY 1 ORDER BY 2 DESC LIMIT 8", lt)
        print("  %-18s %s" % (lt, ", ".join("%s(%d)" % v for v in vals)))

    print()
    print("=== confirmation status mix ===")
    for r in q(db, "SELECT label_source, confirmation_status, COUNT(*)"
                   " FROM fact_ad_label_version GROUP BY 1,2 ORDER BY 3 DESC"):
        print("  %s" % (r,))

    print()
    print("=== category benchmark rows ===")
    for r in q(db, "SELECT category, own_ctr, peer_ctr_median, peer_ctr_p75,"
                   " own_acos, peer_acos_median, own_roas, peer_roas_median"
                   " FROM fact_category_benchmark"):
        print("  %s" % (r,))

    print()
    print("=== budget capped campaigns ===")
    for r in q(db, "SELECT c.campaign_name, b.budget, b.time_in_budget,"
                   " b.lost_impressions_min, b.lost_sales_max"
                   " FROM fact_budget b JOIN dim_campaign c USING(campaign_id)"
                   " WHERE b.time_in_budget > 0.95 ORDER BY b.lost_sales_max DESC"
                   " LIMIT 6"):
        print("  %s" % (r,))

    print()
    print("=== invalid traffic worst ===")
    for r in q(db, "SELECT campaign_name, invalid_click_rate, invalid_clicks,"
                   " total_clicks FROM fact_invalid_traffic"
                   " WHERE invalid_click_rate IS NOT NULL"
                   " ORDER BY invalid_click_rate DESC LIMIT 6"):
        print("  %s" % (r,))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
