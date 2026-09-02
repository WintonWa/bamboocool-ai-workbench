"""决定性检查：别的表里有没有 dim_ad_object 里不存在的广告组。
有 = 构建把广告组漏了；没有 = 54 就是报表能给的全部。
按 (campaign_name, ad_group_name) 配对比，不只比名字（有 3 个重名）。"""
import sqlite3

DB = ("/Users/linsen/BAM/04-广告分析模块/"
      "02-数据构建/v0.2.0/advertising_demo.sqlite")
cx = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
cx.row_factory = sqlite3.Row
q = lambda s, a=(): [dict(r) for r in cx.execute(s, a)]      # noqa: E731

known_pairs = {(r["c"], r["g"]) for r in q(
    "select campaign_name c, ad_group_name g from dim_ad_object"
    " where object_level='AD_GROUP'")}
known_names = {g for _, g in known_pairs}
print("dim_ad_object 广告组: %d 行 / %d 个唯一名" % (len(known_pairs),
                                              len(known_names)))

for t in ("fact_search_term_share", "fact_creative"):
    cols = [c["name"] for c in q("pragma table_info(%s)" % t)]
    has_c = "campaign_name" in cols
    sel = ("select distinct campaign_name c, ad_group_name g from %s"
           " where ad_group_name is not null" % t) if has_c else (
        "select distinct null c, ad_group_name g from %s"
        " where ad_group_name is not null" % t)
    got = {(r["c"], r["g"]) for r in q(sel)}
    names = {g for _, g in got}
    print("\n=== %s ===" % t)
    print("  出现 %d 个唯一名 / %d 个 (Campaign,组) 组合" % (len(names), len(got)))
    new_names = sorted(names - known_names)
    print("  名字不在 dim_ad_object 里的: %d 个 %s"
          % (len(new_names), new_names[:6]))
    if has_c:
        new_pairs = sorted(got - known_pairs)
        print("  (Campaign,组) 组合不在的: %d 个" % len(new_pairs))
        for c, g in new_pairs[:8]:
            print("     %-40s / %s" % (str(c)[:38], g))

print("\n=== 反向：54 个广告组里，有多少在各事实表出现过 ===")
for t in ("fact_ad_performance", "fact_ad_daily", "fact_search_term_share",
          "fact_budget", "fact_placement"):
    try:
        cols = [c["name"] for c in q("pragma table_info(%s)" % t)]
        if "ad_object_id" in cols:
            n = q("""select count(distinct o.ad_object_id) n from %s f
                     join dim_ad_object o on o.ad_object_id=f.ad_object_id
                     where o.object_level='AD_GROUP'""" % t)[0]["n"]
        else:
            n = q("""select count(distinct o.ad_object_id) n from %s f
                     join dim_ad_object o
                       on o.ad_group_name=f.ad_group_name
                      and o.campaign_name=f.campaign_name
                     where o.object_level='AD_GROUP'""" % t)[0]["n"]
        print("  %-26s %d / 54" % (t, n))
    except Exception as e:                                    # noqa: BLE001
        print("  %-26s 跳过（%s）" % (t, str(e)[:34]))

print("\n=== 广告组按广告类型 ===")
for r in q("select ad_type t, count(*) n from dim_ad_object"
           " where object_level='AD_GROUP' group by 1 order by 2 desc"):
    print("  %-4s %d" % (r["t"], r["n"]))
print("\n=== 投放对象按广告类型（对比）===")
for r in q("select ad_type t, count(*) n from dim_ad_object"
           " where object_level='TARGET' group by 1 order by 2 desc"):
    print("  %-4s %d" % (r["t"], r["n"]))
cx.close()
