"""P1 acceptance: every child opens, params bite, states covered, math recomputable."""
import json
import urllib.request
from collections import Counter

BASE = "http://127.0.0.1:18820"


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=30) as r:
        return json.loads(r.read())


fails = []

# --- 1. all 342 children open, seven boards resolve or explain -----------------
listing = get("/api/inventory/children?limit=500")
assert listing["total"] == 342, listing["total"]
state_seen = Counter()
board_empty = Counter()
errors = 0
for row in listing["rows"]:
    d = get("/api/inventory/child/" + row["child_asin"])
    if "error" in d:
        errors += 1
        fails.append(f"{row['child_asin']} 打不开: {d['error']}")
        continue
    for s in d["states"]:
        state_seen[s["state"]] += 1
    if not d["inventory"].get("available") and not d["inventory"].get("reason"):
        board_empty["库存盘点"] += 1
    if not d["fee"].get("available") and not d["fee"].get("reason"):
        board_empty["仓储费"] += 1
    if not d["projection"].get("available") and not d["projection"].get("reason"):
        board_empty["库存承接"] += 1
print(f"1) 342 个子体全部打开：错误 {errors} 个；空板块无说明 {dict(board_empty) or '无'}")

# --- 2. 13 states -------------------------------------------------------------
print("2) 出现过的状态：")
for s, n in state_seen.most_common():
    print(f"     {s:16s} {n:4d} 个对象")

# --- 3. parameter changes must move the numbers -------------------------------
base = get("/api/inventory/children?limit=1")
loose = get("/api/inventory/children?limit=1&inv.availability_min_rate=0.30&inv.aged_share_max=0.50&inv.max_cover_days=600")
tight = get("/api/inventory/children?limit=1&inv.availability_min_rate=0.95&inv.aged_share_max=0.05&inv.max_cover_days=120")
trio = [
    ("默认", base["overview"]),
    ("放宽阈值", loose["overview"]),
    ("收紧阈值", tight["overview"]),
]
print("3) 阈值改动对命中数的影响：")
for label, o in trio:
    counts = {k: v["child_count"] for k, v in o["by_risk_type"].items()}
    print(f"     {label:6s} 有风险 {o['risk_child_count']:3d} | " +
          " ".join(f"{k}={v}" for k, v in counts.items()))
if base["overview"]["risk_child_count"] == loose["overview"]["risk_child_count"] == tight["overview"]["risk_child_count"]:
    fails.append("阈值改动没有改变命中数")

# --- 4. demand now comes from the Agent, not from page parameters ------------
print("4) 需求预测已移出页面，改由 Agent 出（R1）：")
# 参数面板不再有需求预测参数，所以「改参数看预测变不变」失去了对象。
# 现在验相反的一件事：预测对参数免疫，下游对参数敏感。
probe = "B0CGLWJH26"
base = get(f"/api/inventory/child/{probe}")
tight = get(f"/api/inventory/child/{probe}?inv.safety_days_override=90&inv.max_cover_days=120")
bf = base["demand"]["forecast_daily"]
tf = tight["demand"]["forecast_daily"]
print(f"     预测日均 默认 {bf} / 改阈值后 {tf}"
      f" → {'不受参数影响（正确）' if bf == tf else '被参数改动了（错误）'}")
if bf != tf:
    fails.append("预测日均随阈值参数变化，说明还有页面公式残留")

b_safe = base["projection"]["safety_days"]
t_safe = tight["projection"]["safety_days"]
b_cov = base["projection"]["scopes"]["sellable_plus_confirmed"]["cover_days"]
print(f"     安全天数 {b_safe} → {t_safe}，覆盖天数 {b_cov}（覆盖天数只随库存与需求变）")
if b_safe == t_safe:
    fails.append("安全库存天数参数没有生效")

# 断货日必须是区间：Agent 给 lower/forecast/upper 三条需求线，投影各跑一遍。
rng = base["projection"]["scopes"]["sellable_plus_confirmed"]["stockout_date_range"]
print(f"     断货日区间 最早 {rng['earliest']} | 基准 {rng['base']} | 最晚 {rng['latest']}")
if rng["base"] and rng["earliest"] and rng["earliest"] > rng["base"]:
    fails.append("断货日区间方向错了：悲观需求应该比基准更早断货")
if rng["base"] and rng["latest"] and rng["latest"] < rng["base"]:
    fails.append("断货日区间方向错了：乐观需求应该比基准更晚断货")

# 不依赖需求的三类风险，在没有预测的对象上也必须照常判断。
# 这条守卫曾经漏过：一个早返回把五类风险全掐了，库龄 46→0、仓储费 21→0。
# v0.3.0 起 342 个对象全部有预测，所以「无预测对象」这个集合是空的。
# 门禁没有检查对象时必须说出来，不能既报绿又什么都没查 —— 但也不该报失败，
# 「全都有预测」正是这一版数据包解决掉的问题。
nof = [r for r in listing["rows"] if not r.get("forecast_available")]
if nof:
    kinds = {t for r in nof for t in r["risk_types"]}
    print(f"     无预测对象 {len(nof)} 个，其中仍命中的风险类型：{sorted(kinds) or '无'}")
    if not ({"availability", "aging", "storage_fee"} & kinds):
        fails.append("无预测的对象连可用性/库龄/仓储费风险都不判了，风险守卫拆分失效")
    if {"shortage", "overstock"} & kinds:
        fails.append("无预测的对象却判出了库存不足/超量，这两类必须以需求为输入")
else:
    print("     无预测对象 0 个（本版数据包全覆盖），这条守卫本轮无检查对象")
    # 换一个等价的检查：不依赖需求的三类风险数量必须与产品包基线一致。
    # 它们只看批次库龄、体积和可售占比，接线出错会立刻掉到 0。
    kinds_all = {}
    for r in listing["rows"]:
        for t in r["risk_types"]:
            kinds_all[t] = kinds_all.get(t, 0) + 1
    for t, expect in (("availability", 73), ("aging", 46), ("storage_fee", 21)):
        got = kinds_all.get(t, 0)
        print(f"     不依赖需求的 {t}: {got} 个（基线 {expect}）")
        if got != expect:
            fails.append(f"{t} 命中 {got} 个，基线是 {expect} —— 这三类不该随预测源变化")

# 逐日图的载荷完整性
ch = base["chart"]
print(f"     逐日图 轴 {len(ch['dates'])} 天 | 实际 {sum(1 for x in ch['actual'] if x)}"
      f" | 预估 {sum(1 for x in ch['forecast'] if x)} | 泳道 {len(ch['lanes'])}")
if len(ch["dates"]) != len(ch["weekdays"]) or len(ch["dates"]) != len(ch["actual"]) \
   or len(ch["dates"]) != len(ch["forecast"]):
    fails.append("逐日图各数组长度与日期轴不齐，图上会错位一天")
for ln in ch["lines"]:
    if len(ln["values"]) != len(ch["dates"]):
        fails.append(f"折线 {ln['label']} 长度与日期轴不齐")

print("5) 抽 10 个子体手工复算：")
checked = 0
# 只抽有预测的对象：没有预测就没有投影，复算无从下手。
# 按 forecast_available 挑，而不是取前 10 行 —— 否则 fixtures 覆盖一变，
# 这一节可能一个都没检查还照样报 PASS。
with_forecast = [r for r in listing["rows"] if r.get("forecast_available")][:10]
for row in with_forecast:
    d = get("/api/inventory/child/" + row["child_asin"])
    if not d["projection"].get("available"):
        continue
    conf = d["projection"]["scopes"]["sellable_plus_confirmed"]
    inv, dem = d["inventory"], d["demand"]
    # cover =（可售 + 受限 + 窗口内已确认到货）/ 预估日均
    # 已确认到货这一项 v0.3.0 才有：计划货件带子 ASIN 级 ETA 之后在途才进得来。
    if dem["forecast_daily"] > 0:
        arrivals = d["projection"].get("confirmed_arrival_qty") or 0
        expect = round(
            (inv["sellable_qty"] + inv["restricted_qty"] + arrivals) / dem["forecast_daily"], 1
        )
        if abs(expect - (conf["cover_days"] or 0)) > 0.15:
            fails.append(f"{row['child_asin']} 覆盖天数 {conf['cover_days']} != 手算 {expect}")
    # 余额曲线首日 = 可售 - 首日需求（到货在第 7 天）
    s0 = conf["series"][0]
    if abs(s0["closing"] - (inv["sellable_qty"] - s0["demand"])) > 0.05:
        fails.append(f"{row['child_asin']} 首日余额不符")
    # 断货日必须是首个 closing <= 0
    first_zero = next((x["date"] for x in conf["series"] if x["closing"] <= 0), None)
    if first_zero != conf["stockout_date"]:
        fails.append(f"{row['child_asin']} 断货日 {conf['stockout_date']} != 首个零点 {first_zero}")
    # 3/7 天跨线量必须能从批次复算
    lots = d["aging"]["lots"]
    c3 = sum(l["quantity"] for l in lots if 0 < l["days_to_180"] <= 3)
    c7 = sum(l["quantity"] for l in lots if 0 < l["days_to_180"] <= 7)
    if c3 != d["aging"]["crossing_180_within_3d"] or c7 != d["aging"]["crossing_180_within_7d"]:
        fails.append(f"{row['child_asin']} 跨线量与批次不符")
    # 批次件数合计 = FBA 总库存
    if sum(l["quantity"] for l in lots) != inv["fba_total_qty"]:
        fails.append(f"{row['child_asin']} 批次合计 != FBA 总库存")
    checked += 1
print(f"     复算通过 {checked} 个（有预测的对象共 {len(with_forecast)} 个）")
if checked < 3:
    fails.append(f"只复算了 {checked} 个对象，覆盖太薄，这一节等于没检查")

# --- 6. filters ---------------------------------------------------------------
f1 = get("/api/inventory/children?risk_type=aging&limit=500")
f2 = get("/api/inventory/children?size=XXXL&limit=500")
f3 = get("/api/inventory/children?q=TH23AM-125&limit=500")
print(f"6) 筛选：库龄风险 {f1['matched']} 个 | 尺码 XXXL {f2['matched']} 个 | 搜 TH23AM-125 {f3['matched']} 个")
if not all(("aging" in r["risk_types"]) for r in f1["rows"]):
    fails.append("风险筛选返回了不含该风险的行")
if not all(r["size"] == "XXXL" for r in f2["rows"]):
    fails.append("尺码筛选不准")

print()
print(f"失败项 {len(fails)}")
for f in fails[:20]:
    print("  ✗", f)
print("P1 ACCEPTANCE PASS" if not fails else "P1 ACCEPTANCE FAIL")
