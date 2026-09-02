"""源表侧到底有多少广告组：把库里所有带广告组名列的表都数一遍，
和 dim_ad_object 的 54 对账，判断是构建漏了还是源数据本来就这么多。"""
import sqlite3

DB = ("/Users/linsen/BAM/04-广告分析模块/"
      "02-数据构建/v0.2.0/advertising_demo.sqlite")
cx = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
cx.row_factory = sqlite3.Row


def rows(sql, args=()):
    return [dict(r) for r in cx.execute(sql, args)]


tabs = [r["name"] for r in rows(
    "select name from sqlite_master where type='table' order by name")]
print("库里 %d 张表" % len(tabs))

print("\n=== 带广告组名/id 列的表，各自有多少不同广告组 ===")
hit = 0
for t in tabs:
    cols = [c["name"] for c in rows("pragma table_info(%s)" % t)]
    gcols = [c for c in cols
             if "ad_group" in c.lower() or "adgroup" in c.lower()]
    if not gcols:
        continue
    hit += 1
    n = rows("select count(*) n from %s" % t)[0]["n"]
    parts = []
    for c in gcols:
        d = rows("select count(distinct %s) d from %s where %s is not null"
                 % (c, t, c))[0]["d"]
        parts.append("%s=%d" % (c, d))
    print("  %-32s %6d 行   %s" % (t, n, "  ".join(parts)))
print("  （%d 张表带广告组列）" % hit)

print("\n=== 报表来源侧：dim_ad_object 的广告组按来源报表分布 ===")
cols = [c["name"] for c in rows("pragma table_info(dim_ad_object)")]
print("  dim_ad_object 列:", " ".join(cols))
for c in ("source_report", "source_file", "source_ref", "value_origin"):
    if c in cols:
        for r in rows("select %s v, count(*) n from dim_ad_object"
                      " where object_level='AD_GROUP' group by 1"
                      " order by 2 desc" % c):
            print("    %-40s %d" % (str(r["v"])[:38], r["n"]))
        break

print("\n=== 54 个广告组的名字与所属 Campaign ===")
for i, r in enumerate(rows(
        "select ad_group_name g, campaign_name c, ad_type t"
        " from dim_ad_object where object_level='AD_GROUP'"
        " order by campaign_name, ad_group_name"), 1):
    print("  %2d %-3s %-22s %s" % (i, r["t"], (r["g"] or "")[:20],
                                   (r["c"] or "")[:42]))
cx.close()
