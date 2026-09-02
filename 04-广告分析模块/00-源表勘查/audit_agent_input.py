"""按 08-Agent需求与数据契约要则 §1/§3 审计广告 Agent 的输入侧。

对每条证据的 payload 逐 key 打印，供人工判定三问：
1 运营打开后台能直接看到它吗   2 它要算出来才有吗   3 构造脚本里写出来过吗
"""
import json
import sqlite3
from collections import OrderedDict

EXT = ("/Users/linsen/BAM/04-广告分析模块/"
       "02-数据构建/page2-ext/page2_decision_ext.sqlite")
cx = sqlite3.connect("file:%s?mode=ro" % EXT, uri=True)
cx.row_factory = sqlite3.Row
q = lambda s, a=(): [dict(r) for r in cx.execute(s, a)]      # noqa: E731

print("=== 十类证据的 payload 逐字段 ===\n")
seen = OrderedDict()
for r in q("select evidence_type t, evidence_title ti, evidence_payload p,"
           " evidence_nature n, value_origin vo"
           " from ext_decision_evidence order by evidence_type"):
    t = r["t"]
    if t in seen:
        continue
    try:
        pl = json.loads(r["p"] or "{}")
    except Exception:                                         # noqa: BLE001
        pl = {"<解析失败>": (r["p"] or "")[:60]}
    seen[t] = True
    print("── %s  「%s」  nature=%s  origin=%s"
          % (t, r["ti"], r["n"], r["vo"]))
    for k, v in (pl.items() if isinstance(pl, dict) else []):
        sv = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v
        print("     %-28s %s" % (k, str(sv)[:66]))
    print()

print("=== 产品目标同时出现在两处？（循环依赖检查）===")
print("  ext_product_goal 行数:", q("select count(*) n from ext_product_goal")[0]["n"])
g = q("select count(*) n from ext_decision_evidence"
      " where evidence_type='PRODUCT_GOAL'")[0]["n"]
print("  PRODUCT_GOAL 类证据行数:", g)
if g:
    p = json.loads(q("select evidence_payload p from ext_decision_evidence"
                     " where evidence_type='PRODUCT_GOAL' limit 1")[0]["p"])
    print("  该证据 payload 的 key:", list(p.keys()))

print("\n=== nature 与 value_origin 分布 ===")
for r in q("select evidence_nature n, value_origin vo, count(*) c"
           " from ext_decision_evidence group by 1,2 order by 3 desc"):
    print("  %-12s %-12s %d" % (r["n"], r["vo"], r["c"]))
cx.close()
