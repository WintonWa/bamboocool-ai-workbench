"""产品目标改为「运营设定的输入」（王楠 2026-08-31 拍定）。

背景：原来产品目标是我们从销量趋势与库存判定推出来的，却同时
      (a) 当证据递给 Agent、(b) 被列为 Agent 的输出点 B0 —— 循环了。
决定：产品目标是运营在系统里填的，Agent 不判它，直接拿来用。

按 08-Agent需求与数据契约要则：
  §2「产品定位：运营设定的产品目标」→ 合法输入
  §6「构造输入合法」→ 构造一份运营填的目标可以
  6.6 nature 词表第三值 `confirmed` 运营已确认 → 正是这一档

所以要清掉三样「这是我们推断出来的」痕迹：
  1. goal_status  pending_operator_confirmation → confirmed
  2. rationale    推断链（近3日日均…库存判定…）→ 运营口径的意图，不带推断数字
  3. source_ref   derived from sales_window + inventory → operator_set
证据侧同步：evidence_nature inference → confirmed，caveat 里的「待运营确认」清掉。

幂等：重复跑不会二次改动。构建器 build_page2_ext.py 也要同步，见文末打印。
"""
import json
import sqlite3

DB = ("/Users/linsen/BAM/04-广告分析模块/"
      "02-数据构建/page2-ext/page2_decision_ext.sqlite")

# 运营口径的意图，只说想做什么，不含任何推断数字或判定结论
OPERATOR_NOTE = {
    "稳定经营并补齐库存承接": "保住现有规模，先把库存承接补齐",
    "加速去库存并保住效率": "优先清库存，效率不要恶化太多",
    "优先处理高库龄库存": "先处理高库龄那部分",
    "维持当前规模与效率": "维持现状，不做大动作",
}

cx = sqlite3.connect(DB)
cx.row_factory = sqlite3.Row


def rows(s, a=()):
    return [dict(r) for r in cx.execute(s, a)]


print("=== 改前 ===")
for r in rows("select child_asin, goal_status, rationale from ext_product_goal"):
    print("  %s  %s  %s" % (r["child_asin"], r["goal_status"],
                            (r["rationale"] or "")[:38]))

n1 = 0
for r in rows("select goal_version, goal_label from ext_product_goal"):
    note = OPERATOR_NOTE.get(r["goal_label"])
    if note is None:
        print("  ⚠ 没有对应的运营口径备注:", r["goal_label"])
        continue
    cx.execute("update ext_product_goal set goal_status='confirmed',"
               " rationale=?, source_ref='operator_set'"
               " where goal_version=?", (note, r["goal_version"]))
    n1 += cx.total_changes and 1 or 0
cx.execute("update ext_product_goal set goal_status='confirmed'")

# 证据侧：产品目标这条证据从「系统推导」改成「运营已确认」
n2 = cx.execute(
    "update ext_decision_evidence set evidence_nature='confirmed',"
    " caveat=null, source_ref='operator_set'"
    " where evidence_type='PRODUCT_GOAL'").rowcount

# payload 里的 status 也要跟上，否则界面读 payload 会显示旧状态
n3 = 0
for r in rows("select evidence_id, evidence_payload p from"
              " ext_decision_evidence where evidence_type='PRODUCT_GOAL'"):
    pl = json.loads(r["p"] or "{}")
    if pl.get("status") != "confirmed":
        pl["status"] = "confirmed"
        cx.execute("update ext_decision_evidence set evidence_payload=?"
                   " where evidence_id=?",
                   (json.dumps(pl, ensure_ascii=False), r["evidence_id"]))
        n3 += 1
cx.commit()

print("\n=== 改后 ===")
for r in rows("select child_asin, goal_status, rationale, source_ref"
              " from ext_product_goal"):
    print("  %s  %s  「%s」  %s" % (r["child_asin"], r["goal_status"],
                                  r["rationale"], r["source_ref"]))
print("\n证据侧改了 %d 条，payload 改了 %d 条" % (n2, n3))
for r in rows("select evidence_nature n, count(*) c from"
              " ext_decision_evidence group by 1 order by 2 desc"):
    print("  nature %-12s %d" % (r["n"], r["c"]))
cx.close()

print("""
下一步（本脚本不做，避免动别人正在跑的东西）：
  1. build_page2_ext.py 里生成 ext_product_goal 的那段要同步改，
     否则重建数据包会把这次迁移覆盖回去
  2. 输出点清单第 2 节 B0 作废，产品目标从输出点移到输入
  3. 第 12 节禁读清单里 PRODUCT_GOAL 那行删掉（它现在是合法输入）
""")
