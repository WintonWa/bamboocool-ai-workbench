"""导出真实接口响应作为 Agent 侧的参照样例。
不裁字段（Agent 要看全形状），只裁数组长度：长列表留前 2-3 条，
并在文件里注明原始长度，避免样例大到没人读。
"""
import json
import os
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:18820/api/ads/"
OUT = ("/Users/linsen/BAM/04-广告分析模块/"
       "01-方案与数据需求/agent-samples")
ASIN = "B0B3LWGP36"
KEEP = 3          # 长数组留几条
# 这些键的数组绝不裁：裁了会砍掉第四段 proposal，而四段本身就是要展示的形状。
NEVER_TRIM = {"stages", "stage_order", "diagnosis_coverage", "groups"}

# 按 08-Agent需求与数据契约要则 §9「钉形状钉词表，不钉答案」：
# 产出侧的自由文本与结论取值一律遮蔽，只留形状与类型。
# 不遮蔽枚举字段本身（那是词表，该钉），遮蔽的是「这个对象取哪个值」。
MASK_TEXT = {
    "rationale", "what_happened", "uncertainty", "missing_input",
    "check_direction", "evaluation_direction", "stop_condition",
    "target_fit", "result_supports_purpose", "note", "detail",
    "goal_label", "impacted_goal", "label", "why_not", "basis",
    "demand_side", "product_side", "pressure_label", "diagnosis_label",
    "direction_label", "task_label", "why",
    # 候选池与 context 里的同义字段，第一版漏了
    "product_goal", "goal_rationale",
}
MASK_ENUM = {
    "task_type", "task_direction", "problem_type", "direction",
    "priority", "confidence", "coverage_status", "attribution_limit",
    "gap_source", "basis_type", "basis_level", "issue_type",
    "pressure_type", "match_level", "goal_type", "position_trend",
    "risk_status", "scenario", "kind",
    # 候选池按库存处境分组，组 key 就是结论
    "inventory_risk", "base_risk_status",
}
# 输入侧的禁读字段：样例里也不该出现，否则对方照着用
MASK_FORBIDDEN = {
    "coverage_days", "safety_breach_date", "stress_stockout_date",
    "base_stockout_date", "latest_order_date",
    "suggested_replenishment_qty", "dynamic_safety_days",
    "confidence_score", "lifecycle",
}


def mask(o, key=""):
    """遮蔽产出侧的值，保留形状。"""
    if isinstance(o, dict):
        return {k: mask(v, k) for k, v in o.items()}
    if isinstance(o, list):
        return [mask(x, key) for x in o]
    if key in MASK_FORBIDDEN:
        return "<禁读·见输出点清单第 12 节>"
    if o is None or isinstance(o, bool):
        return o
    if key in MASK_TEXT and isinstance(o, str) and o.strip():
        return "<中文一句话，结论先行，由 Agent 产出>"
    if key in MASK_ENUM and isinstance(o, str) and o.strip():
        return "<词表内取值，由 Agent 判断>"
    return o


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def trim(o, key=""):
    """裁数组长度，并在被裁处插一条说明。key 是这个值所在的字段名。"""
    if isinstance(o, dict):
        return {k: trim(v, k) for k, v in o.items()}
    if isinstance(o, list):
        if key in NEVER_TRIM or len(o) <= KEEP:
            return [trim(x, key) for x in o]
        head = [trim(x, key) for x in o[:KEEP]]
        head.append("…… 本数组原有 %d 项，样例只留前 %d 项 ……"
                    % (len(o), KEEP))
        return head
    return o


os.makedirs(OUT, exist_ok=True)

# decide 需要一个真实的 recommendation_id，先从 run 里取
try:
    _run = get("run?child_asin=" + ASIN)
    REC = _run["stages"][3]["items"][0]["recommendation_id"]
    print("取到建议 id:", REC)
except Exception as e:                                        # noqa: BLE001
    REC = ""
    print("取不到建议 id:", str(e)[:60])

jobs = [
    ("candidates", "candidates", "选子 ASIN，带处境与证据完整度"),
    ("context", "context?child_asin=" + ASIN, "Agent 的输入（板块1/2/3/5）"),
    ("run", "run?child_asin=" + ASIN, "Agent 的输出四段（板块4/6/7/8）"),
    ("decide-accept", "decide?child_asin=%s&recommendation_id=%s"
     "&decision=accept" % (ASIN, urllib.parse.quote(REC)),
     "板块9 交接（运营接受 → 出交接块）"),
    ("decide-reject", "decide?child_asin=%s&recommendation_id=%s"
     "&decision=reject" % (ASIN, urllib.parse.quote(REC)),
     "板块9（拒绝 → 不出交接块）"),
    ("decide-bad-param", "decide?child_asin=" + ASIN,
     "参数校验：缺 decision 时的失败形状"),
    ("gate", "gate", "契约门禁自检：依据 id 零悬空"),
    ("catalog-adgroup", "catalog?ads.grain=AD_GROUP", "页面一八板块（广告组粒度）"),
    ("catalog-target-filtered",
     "catalog?ads.grain=TARGET&labels="
     + urllib.parse.quote("TARGET_OBJECT:关键词\x01AD_ATTRIBUTE:SP")
     + "&match=" + urllib.parse.quote("精准匹配"),
     "页面一 + 组合筛选（族内 OR、跨族 AND）"),
    ("object", "object/" + "grp_03d043c7031eebf6", "页面一详情抽屉八面板"),
]

idx = []
for name, path, desc in jobs:
    try:
        raw = get(path)
    except Exception as e:                                    # noqa: BLE001
        print("  %-26s 取不到: %s" % (name, str(e)[:50]))
        continue
    small = mask(trim(raw))
    body = json.dumps(small, ensure_ascii=False, indent=2)
    fp = os.path.join(OUT, name + ".json")
    with open(fp, "w", encoding="utf-8") as f:
        f.write(body)
    full = len(json.dumps(raw, ensure_ascii=False))
    print("  %-26s %6d 字符（原始 %d）  %s"
          % (name + ".json", len(body), full, desc))
    idx.append((name, path, desc, len(body), full))

with open(os.path.join(OUT, "README.md"), "w", encoding="utf-8") as f:
    f.write("# 接口真实响应样例\n\n")
    f.write("从跑着的工作台（`http://127.0.0.1:18820`）直接取的真实响应。\n\n"
            "**这是形状参照，不是标准答案。** 按 "
            "`00-通用方法与规范/08-Agent需求与数据契约要则.md` §9"
            "「钉形状钉词表，不钉答案」：\n\n"
            "- 字段名、类型、嵌套结构、数组形状：**照着对接**\n"
            "- 产出侧的自由文本与结论取值：已替换成占位符，"
            "由 Agent 自己判断\n"
            "- 输入侧的禁读字段（覆盖天数 / 断货日 / 建议补货量 / "
            "生命周期 / 置信度）：已替换成禁读标记\n"
            "- 长数组只留前 %d 项并在原位注明原始长度\n\n" % KEEP)
    f.write("演示子 ASIN：`%s`\n\n" % ASIN)
    f.write("| 文件 | 请求 | 内容 | 样例/原始字符数 |\n|---|---|---|---|\n")
    for name, path, desc, s, full in idx:
        f.write("| `%s.json` | `GET /api/ads/%s` | %s | %d / %d |\n"
                % (name, path.split("?")[0], desc, s, full))
print("\n索引写到", os.path.join(OUT, "README.md"))
