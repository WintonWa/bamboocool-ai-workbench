"""盘点 Agent 输出点：扩展库 13 张表的真实列 + 每列的取值样本。
输出直接用于写「Agent 输出点清单」，所以要列名、类型、非空率、取值枚举。"""
import json
import sqlite3

EXT = ("/Users/linsen/BAM/04-广告分析模块/"
       "02-数据构建/page2-ext/page2_decision_ext.sqlite")
cx = sqlite3.connect("file:%s?mode=ro" % EXT, uri=True)
cx.row_factory = sqlite3.Row
q = lambda s, a=(): [dict(r) for r in cx.execute(s, a)]      # noqa: E731

tabs = [r["name"] for r in q(
    "select name from sqlite_master where type='table' order by name")]
print("扩展库 %d 张表\n" % len(tabs))

for t in tabs:
    n = q("select count(*) n from %s" % t)[0]["n"]
    cols = q("pragma table_info(%s)" % t)
    print("=" * 72)
    print("%s   %d 行   %d 列" % (t, n, len(cols)))
    for c in cols:
        name = c["name"]
        nn = q("select count(*) n from %s where %s is not null"
               % (t, name))[0]["n"]
        # 取值枚举：不同值少于 9 个就全列出，否则给两个样本
        d = q("select count(distinct %s) d from %s" % (name, t))[0]["d"]
        if d and d <= 8:
            vs = [str(r["v"])[:34] for r in q(
                "select distinct %s v from %s where %s is not null"
                " order by 1" % (name, t, name))]
            sample = "取值: " + " | ".join(vs)
        else:
            vs = [str(r["v"])[:44] for r in q(
                "select %s v from %s where %s is not null limit 2"
                % (name, t, name))]
            sample = "%d 种，例: %s" % (d, "  ／  ".join(vs))
        flag = "" if nn == n else "  非空 %d/%d" % (nn, n)
        print("   %-30s %-7s %s%s" % (name, c["type"], sample, flag))
print("=" * 72)

print("\n\n=== 五个演示对象各自的链条规模 ===")
try:
    for r in q("""select child_asin,
                  (select count(*) from ext_decision_evidence e
                    where e.child_asin=c.child_asin) ev,
                  (select count(*) from ext_required_ad_task t
                    where t.child_asin=c.child_asin) tk,
                  (select count(*) from ext_diagnosis d
                    where d.child_asin=c.child_asin) dg,
                  (select count(*) from ext_recommendation p
                    where p.child_asin=c.child_asin) pr
                  from ext_decision_context c order by child_asin"""):
        print("  %s  证据 %2d  任务 %d  诊断 %d  建议 %d"
              % (r["child_asin"], r["ev"], r["tk"], r["dg"], r["pr"]))
except Exception as e:                                        # noqa: BLE001
    print("  查不到:", str(e)[:80])
cx.close()
