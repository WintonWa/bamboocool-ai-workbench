"""要则 §11-4 / §0 的决定性检查：真 Agent 的产出与预烤回放是不是同一份。

同 = 契约还在钉答案（复印机）。不同 = Agent 真在判断。
"""
import json
import sqlite3

AG = ("/Users/linsen/BAM/09-工作台/modules/ads/"
      "derived/ads_agent_state.sqlite")
EXT = ("/Users/linsen/BAM/04-广告分析模块/"
       "02-数据构建/page2-ext/page2_decision_ext.sqlite")


def ro(p):
    cx = sqlite3.connect("file:%s?mode=ro" % p, uri=True)
    cx.row_factory = sqlite3.Row
    return cx


a, e = ro(AG), ro(EXT)
q = lambda c, s, ar=(): [dict(r) for r in c.execute(s, ar)]   # noqa: E731

for run in q(a, "select run_id, child_asin from fact_ads_agent_run"
                " where status='completed' order by created_at"):
    asin, rid = run["child_asin"], run["run_id"]
    print("=" * 70)
    print("%s   run %s" % (asin, rid[-13:]))
    items = q(a, "select stage, item_ord, item_id, payload"
                 " from fact_ads_agent_item where run_id=?"
                 " order by stage, item_ord", (rid,))
    by = {}
    for r in items:
        by.setdefault(r["stage"], []).append(json.loads(r["payload"]))

    dec = "dec_%s_20260803" % asin
    ext = {
        "task": q(e, "select * from ext_required_ad_task where decision_id=?",
                  (dec,)),
        "mapping": q(e, "select * from ext_task_ad_object t join"
                        " ext_required_ad_task k on k.task_id=t.task_id"
                        " where k.decision_id=?", (dec,)),
        "diagnosis": q(e, "select * from ext_diagnosis where decision_id=?",
                       (dec,)),
        "proposal": q(e, "select * from ext_recommendation where decision_id=?",
                      (dec,)),
    }
    for st in ("task", "mapping", "diagnosis", "proposal"):
        ai = by.get(st, [])
        ex = ext.get(st, [])
        print("  %-10s Agent %d 条 / 回放 %d 条" % (st, len(ai), len(ex)))
        if not ai:
            continue
        # 比对自由文本与结论字段
        keys = {"task": ("task_type", "priority", "stop_condition"),
                "mapping": ("coverage_status", "note"),
                "diagnosis": ("problem_type", "priority", "what_happened"),
                "proposal": ("direction", "rationale")}[st]
        for k in keys:
            av = [str(x.get(k)) for x in ai if k in x]
            ev = [str(x.get(k)) for x in ex if k in x]
            if not av:
                print("     %-18s Agent 没这个字段" % k)
                continue
            same = sorted(av) == sorted(ev)
            print("     %-18s 逐值相同=%s" % (k, same))
            if not same:
                print("        Agent: %s" % " | ".join(x[:34] for x in av[:3]))
                print("        回放  : %s" % " | ".join(x[:34] for x in ev[:3]))
    print()

print("=== 同对象重跑过吗（§11-4）===")
for r in q(a, "select child_asin, count(*) n from fact_ads_agent_run"
              " where status='completed' group by 1"):
    print("  %s 跑了 %d 次" % (r["child_asin"], r["n"]))
a.close()
e.close()
