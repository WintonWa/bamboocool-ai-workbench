"""落表 ↔ 接口 ↔ 前端 三层字段对账。

Agent 写进表的每个字段，要能一路走到屏幕上；前端要读的每个字段，
要能一路追回到表里。三层各自可能丢东西：

  第一层  Agent 落表        fact_ads_agent_item.payload
  第二层  服务端读取与加工   agent_result.latest() → 码值翻中文加 _label
  第三层  前端渲染          ads.js 的 rowTask / rowMapping / rowDiagnosis / rowProposal

判定：
  落表有、接口没有         → 服务端把它吃掉了
  接口有、前端没读         → 白写，页面上看不到
  前端读、接口没有         → 页面会空或显示 undefined

用法：/usr/bin/python3 tests/check_agent_field_contract.py
"""
import json
import re
import sqlite3
import sys
from pathlib import Path

WB = Path("/Users/linsen/BAM/09-工作台")
SIDE = WB / "modules" / "ads" / "derived" / "ads_agent_state.sqlite"
JS = WB / "web" / "modules" / "ads.js"
sys.path.insert(0, str(WB))

RENDER = {
    # 这几个点不走四段渲染，各自有专用的行渲染函数
    "B0b": ("constraintRow", "x"),
    "B0cd": ("b0cdRow", "x"),
    "B0e": ("structIssueRow", "x"),
    "B3b": ("coverageRow", "x"),
    "task": ("rowTask", "t"),
    "mapping": ("rowMapping", "m"),
    "diagnosis": ("rowDiagnosis", "d"),
    "proposal": ("rowProposal", "p"),
}
# 前端不必读的：内部 id 与内部标记，契约明写不上屏
NOT_FOR_SCREEN = {
    "task_id", "mapping_id", "diagnosis_id", "recommendation_id",
    "decision_id", "goal_version", "product_goal_version", "item_id",
    "child_asin", "run_id", "value_origin",
    "constraint_id", "issue_id", "goal_version", "evidence_ref",
    "match_id", "pressure_id", "item_kind",
}
# 服务端把码值翻成中文时的真实命名（从 compute.py 的 cn() 调用提取，
# 不是 <字段>_label 这种规律命名，所以必须写死）。
# 前端读了译名就等于读了原字段，不算白写。
TRANSLATED = {
    "confidence": "confidence_label",
    "task_type": "task_label",
    "task_direction": "direction_label",
    "direction": "direction_label",
    "problem_type": "problem_label",
}
# 已经在别处显示、不在这一行渲染函数里的（外层卡片或板块级）
SHOWN_ELSEWHERE = {
    "ad_object_id",        # 经 objName() 翻成对象名再显示
    "judgment_mode",       # 板块级标着判断档位
    "nature",              # 证据卡上的数据性质
    "rule_status",         # 前端用 exact_values_withheld 表达
}


def js_fn_body(src: str, name: str) -> str:
    i = src.find("function %s(" % name)
    if i < 0:
        return ""
    j = src.find("{", i)
    depth, k = 0, j
    while k < len(src):
        if src[k] == "{":
            depth += 1
        elif src[k] == "}":
            depth -= 1
            if depth == 0:
                return src[j:k + 1]
        k += 1
    return src[j:]


def layer1() -> dict:
    """Agent 落表的字段。"""
    if not SIDE.is_file():
        return {}
    cx = sqlite3.connect("file:%s?mode=ro" % SIDE, uri=True)
    cx.row_factory = sqlite3.Row
    out: dict = {}
    # 新表：按 output_point 分组。B1-B4 映射成四段名字，其余点单独列。
    alias = {"B1": "task", "B2": "mapping", "B3": "diagnosis",
             "B4": "proposal"}
    for r in cx.execute("select output_point, payload"
                        " from fact_ads_agent_output"):
        key = alias.get(r["output_point"], r["output_point"])
        for k in json.loads(r["payload"]):
            out.setdefault(key, set()).add(k)
    cx.close()
    return out


def layer2():
    """服务端读出来给前端的字段。用落表里记的 hash 当当前 hash，
    绕过「页面依据已变化」那道闸，专测字段是否齐。"""
    from modules.ads import agent_result
    cx = sqlite3.connect("file:%s?mode=ro" % SIDE, uri=True)
    cx.row_factory = sqlite3.Row
    run = cx.execute("select child_asin, context_hash from fact_ads_agent_run"
                     " where status='completed'"
                     " order by created_at desc limit 1").fetchone()
    cx.close()
    if run is None:
        return {}, None
    res = agent_result.latest(run["child_asin"], run["context_hash"])
    if not (res.get("points") or res.get("stages")):
        return {}, res
    out = {}
    alias = {"B1": "task", "B2": "mapping", "B3": "diagnosis",
             "B4": "proposal"}
    for pt, items in (res.get("points") or {}).items():
        key = alias.get(pt, pt)
        for it in items:
            out.setdefault(key, set()).update(it.keys())
    return out, res


def layer3(src: str) -> dict:
    out = {}
    for stage, (fn, var) in RENDER.items():
        body = js_fn_body(src, fn)
        if not body:
            out[stage] = None
            continue
        keys = set(re.findall(r"\b%s\.([A-Za-z_][A-Za-z0-9_]*)" % var, body))
        keys |= set(re.findall(r"\b%s\[[\"']([^\"']+)[\"']\]" % var, body))
        # 字段名以字符串参数传给适配函数的也算读了：
        #   labelOf(t, "task_type", "task_label")
        #   labelOf(m, "gap_source", "gap_label", "gap_source")
        for m in re.finditer(
                r"labelOf\(\s*%s\s*,\s*\"([^\"]+)\"\s*,\s*\"?([^\",)]*)\"?"
                % var, body):
            keys.add(m.group(1))
            if m.group(2):
                keys.add(m.group(2))
        # 分派函数（b0cdRow 这种只按 item_kind 转发的）本身不读字段，
        # 要把它转发到的下游函数体也算进来，否则会误报整片白写。
        import re as _re
        for m2 in _re.finditer(r"\b(\w+)\(c,\s*%s\)" % var, body):
            sub = js_fn_body(src, m2.group(1))
            if not sub:
                continue
            for v2 in ("x", "t", "m", "d", "p"):
                keys |= set(_re.findall(
                    r"\b%s\.([A-Za-z_][A-Za-z0-9_]*)" % v2, sub))
                for m3 in _re.finditer(
                        r"labelOf\(\s*%s\s*,\s*\"([^\"]+)\"" % v2, sub):
                    keys.add(m3.group(1))
        keys -= {"length", "map", "filter", "forEach", "join", "slice",
                 "push", "some", "every", "includes", "concat"}
        out[stage] = keys
    return out


src = JS.read_text()
L1 = layer1()
L2, res = layer2()
L3 = layer3(src)

if not L1:
    print("sidecar 里还没有 Agent 结果，无法对账。先让 Runner 跑一次。")
    raise SystemExit(1)
if not L2:
    print("服务端读不出这次运行：", (res or {}).get("message", "未知"))
    raise SystemExit(1)

print("对账样本：%s   run %s\n"
      % (res["child_asin"], res["run_id"][-13:]))

eaten, unread, empty = [], [], []
for stage in sorted(set(L1) | set(L2)):
    a, b, c = L1.get(stage, set()), L2.get(stage, set()), L3.get(stage)
    print("=" * 68)
    print("%-10s 落表 %d 字段 → 接口 %d 字段 → 前端读 %s"
          % (stage, len(a), len(b), len(c) if c is not None else "函数没找到"))
    if c is None:
        continue
    e = sorted(a - b)
    if e:
        print("   ✗ 服务端吃掉了: %s" % "  ".join(e))
        eaten += [(stage, k) for k in e]
    u = sorted((b - c) - NOT_FOR_SCREEN - SHOWN_ELSEWHERE)
    # 有译名且前端读了译名的，不算白写
    u = [k for k in u if TRANSLATED.get(k) not in c]
    if u:
        print("   ✗ 接口给了但前端没读: %s" % "  ".join(u))
        unread += [(stage, k) for k in u]
    # labelOf(x, 码值键, 回放label键, 映射名)：第三参只在回放路径存在，
    # Agent 路径没有不算缺。ad_object 是读取层补的，也不来自落表。
    OPTIONAL = {"mode", "ad_object", "kind_label", "coverage_label",
                "task_label", "diagnosis_label"}
    m = sorted(k for k in (c - b)
               if not k.endswith("_label") and k not in OPTIONAL)
    if m:
        print("   ✗ 前端读但接口没给: %s" % "  ".join(m))
        empty += [(stage, k) for k in m]
    if not e and not u and not m:
        print("   ✓ 三层对齐")

print("=" * 68)
print("服务端吃掉 %d · 白写 %d · 会空 %d" % (len(eaten), len(unread), len(empty)))
raise SystemExit(1 if (eaten or unread or empty) else 0)
