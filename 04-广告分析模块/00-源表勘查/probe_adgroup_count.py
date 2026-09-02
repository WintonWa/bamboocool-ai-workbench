"""广告组数量是否被构建漏掉：拿层级表、投放对象的父指针、各事实表交叉对账。"""
import sqlite3
from collections import Counter

DB = ("/Users/linsen/BAM/04-广告分析模块/"
      "02-数据构建/v0.2.0/advertising_demo.sqlite")
OLD = ("/Users/linsen/BAM/04-广告分析模块/"
       "02-数据构建/v0.1.0/advertising_demo.sqlite")


def open_ro(p):
    cx = sqlite3.connect("file:%s?mode=ro" % p, uri=True)
    cx.row_factory = sqlite3.Row
    return cx


def rows(cx, sql, args=()):
    return [dict(r) for r in cx.execute(sql, args)]


cx = open_ro(DB)
print("=== 层级计数（v0.2.0）===")
for r in rows(cx, "select object_level lv, count(*) n from dim_ad_object"
                  " group by 1 order by 2 desc"):
    print("  %-10s %d" % (r["lv"], r["n"]))

print("\n=== 各层覆盖的 Campaign 数 ===")
for lv in ("CAMPAIGN", "AD_GROUP", "TARGET"):
    r = rows(cx, "select count(distinct campaign_id) ci,"
                 " count(distinct campaign_name) cn from dim_ad_object"
                 " where object_level=?", (lv,))[0]
    print("  %-9s campaign_id %d / campaign_name %d" % (lv, r["ci"], r["cn"]))

print("\n=== 有 Campaign 行但没有广告组行的 Campaign ===")
miss = rows(cx, """
    select c.campaign_id, c.campaign_name,
           (select count(*) from dim_ad_object t
             where t.object_level='TARGET' and t.campaign_id=c.campaign_id) tn
    from dim_ad_object c
    where c.object_level='CAMPAIGN'
      and not exists (select 1 from dim_ad_object g
                      where g.object_level='AD_GROUP'
                        and g.campaign_id=c.campaign_id)
    order by tn desc""")
print("  共 %d 个" % len(miss))
for r in miss[:10]:
    print("    %-46s 其下投放对象 %d" % ((r["campaign_name"] or "")[:44],
                                    r["tn"]))
print("  其中「其下有投放对象却没有广告组」的:",
      len([r for r in miss if r["tn"] > 0]))

print("\n=== 投放对象的父指针指向什么 ===")
r = rows(cx, "select count(*) n, sum(parent_ad_object_id is null) nul"
             " from dim_ad_object where object_level='TARGET'")[0]
print("  投放对象 %d 个，父指针为空 %d 个" % (r["n"], r["nul"]))
orph = rows(cx, """
    select count(*) n from dim_ad_object t
    where t.object_level='TARGET' and t.parent_ad_object_id is not null
      and not exists (select 1 from dim_ad_object g
                      where g.ad_object_id=t.parent_ad_object_id)""")[0]["n"]
print("  父指针指向不存在的对象（孤儿）:", orph)
lv = rows(cx, """
    select g.object_level plv, count(*) n from dim_ad_object t
    join dim_ad_object g on g.ad_object_id=t.parent_ad_object_id
    where t.object_level='TARGET' group by 1 order by 2 desc""")
print("  父对象的层级分布:", {x["plv"]: x["n"] for x in lv})

print("\n=== 事实表里出现过多少广告组 ===")
for t, col in (("fact_ad_performance", "ad_object_id"),
               ("fact_ad_daily", "ad_object_id"),
               ("fact_ad_label_version", "ad_object_id")):
    try:
        n = rows(cx, """
            select count(distinct f.%s) n from %s f
            join dim_ad_object o on o.ad_object_id=f.%s
            where o.object_level='AD_GROUP'""" % (col, t, col))[0]["n"]
        print("  %-26s %d 个广告组" % (t, n))
    except Exception as e:                                    # noqa: BLE001
        print("  %-26s 读不到: %s" % (t, str(e)[:40]))

print("\n=== 广告组名字里有没有重复（同名不同 Campaign）===")
gn = Counter(r["ad_group_name"] for r in rows(
    cx, "select ad_group_name from dim_ad_object where object_level='AD_GROUP'"))
dup = {k: v for k, v in gn.items() if v > 1}
print("  唯一名字 %d 个，重名 %d 个: %s" % (len(gn), len(dup),
                                    list(dup.items())[:5]))

print("\n=== 和 v0.1.0 比 ===")
try:
    co = open_ro(OLD)
    for r in rows(co, "select object_level lv, count(*) n from dim_ad_object"
                      " group by 1 order by 2 desc"):
        print("  v0.1.0 %-10s %d" % (r["lv"], r["n"]))
    co.close()
except Exception as e:                                        # noqa: BLE001
    print("  读不到 v0.1.0:", str(e)[:60])
cx.close()
