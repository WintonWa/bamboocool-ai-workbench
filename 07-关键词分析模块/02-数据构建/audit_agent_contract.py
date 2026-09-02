#!/usr/bin/env python3
"""按《08-Agent需求与数据契约要则》v1.1 审计关键词模块的交底文档与数据包。

三项机械检查，对应要则 §11 自检六条里能机械化的那几条：

  A. §11-1 答案泄漏：产出侧字段在数据包里有没有同名列
  B. §3    禁读清单：库里哪些列命中「不给 Agent 读的」类别
  C. §11-2 钉答案：交底文档里有没有出现完整的中文结论句

用法：/usr/bin/python3 audit_agent_contract.py
"""
from __future__ import annotations

import json
import pathlib
import re
import sqlite3
import sys

HERE = pathlib.Path(__file__).parent
DB = HERE / "v0.1.0" / "keyword_demo.sqlite"
DOCS_DIR = HERE.parent / "01-方案与数据需求"
DOCS = ["05-Agent输出面交底.md", "08-给Agent侧的完整交底.md"]
JSON_SAMPLE = DOCS_DIR / "07-接口JSON样例.json"

# 我在 05 号文档里声明「Agent 必须输出」的字段
DECLARED_OUTPUT = [
    "evidence_id", "evidence_type", "priority", "conclusion", "main_basis",
    "evidence_completeness", "next_verification", "competitor_verification_state",
    "ref_market_event_ids", "ref_coverage_event_ids",
    "traffic_proxy_value", "traffic_proxy_delta",
    "q1_traffic_result", "q2_main_movers", "q3_core_coverage_change",
    "q4_new_signals", "q5_priority_next",
    "priority_evidence_ids", "coverage_event_ids",
    "event_type", "continuity", "label", "change_ratio",
    "evidence_count", "evidence_type_counts",
]

# 王楠 2026-08-31 拍定放开的三组（Demo 例外）：产品定位 / 库存承接 / 词库定性。
# 它们是**别的判断点的答案**，不是关键词 Agent 自己的产出，所以不进禁读校验。
# 记在这里是为了让「为什么这几列没被拦」有据可查 —— 不是漏了。
DEMO_READABLE = {
    "product_goal", "product_goal_label", "push_role", "push_role_label",
    "product_lifecycle", "lifecycle",
    "absorb_state", "absorb_state_label", "absorb_detail",
    "inventory_limit_label", "latest_order_date", "base_stockout_date",
    "stress_stockout_date", "days_to_base_stockout", "dynamic_safety_days",
    "suggested_replenishment_qty", "projected_lost_sales_units",
    "confidence_score",
    "library_status", "library_status_label", "operator_role",
    "operator_role_label", "operator_role_confirmed", "operator_role_seed_word",
    "alias_type_label",
}

# 要则 §3 的禁读类别 → 命中该类别的列名模式
FORBIDDEN = {
    "对未来的预测": [r"forecast", r"p10_|p50_|p90_", r"predicted", r"_units$"],
    "从预测派生的投影": [r"latest_order_date", r"stockout", r"coverage_days",
                    r"safety_", r"replenish", r"suggest"],
    "已分解的因子": [r"_factor$", r"_effect_rati", r"uplift"],
    "已剥离的干净基线": [r"clean_baseline", r"estimated_demand", r"lost_sales",
                   r"potential_demand"],
    "已成文的中文理由": [r"_reason$", r"rationale", r"what_happened",
                   r"^conclusion$", r"^main_basis$", r"^label$", r"^detail$",
                   r"_detail$", r"^q[1-5]_"],
    "已分级的结论": [r"^risk_status$", r"^priority$", r"attention_level",
                 r"lifecycle_stage", r"^product_lifecycle$", r"^direction$",
                 r"target_fit", r"^operator_role$", r"^library_status$",
                 r"^event_type$", r"^continuity$", r"^evidence_type$",
                 r"^absorb_state", r"^product_goal", r"^push_role"],
    "已给的置信度": [r"confidence", r"^wape$", r"^bias$", r"selected_model",
                 r"_completeness$"],
    "预计效应": [r"preset_uplift", r"expected_effect", r"performance_index"],
    "数据质量与构造元数据": [r"quality_status", r"quality_flag", r"^value_origin$",
                     r"method_version", r"^rule_version$"],
}

# 完整中文结论句的特征：带书名号词条 + 判断动词/量词的长句
CONCLUSION_PAT = re.compile(
    r"「[^」]{3,60}」[^\n|]{0,40}"
    r"(有机会|不宜|正在走弱|已恢复|中断|需先|不可承接|从第|降到|升到|"
    r"上升|下降|丢失|新增|值得继续|暂不能|尚未|已有初步)")


def sec(title: str) -> None:
    print()
    print("=" * 76)
    print(title)
    print("=" * 76)


def main() -> int:
    if not DB.exists():
        print("找不到库：%s" % DB)
        return 1
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    tables = [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    col_owner: dict[str, list[str]] = {}
    for t in tables:
        for c in con.execute(f"PRAGMA table_info({t})"):
            col_owner.setdefault(c[1], []).append(t)

    fail = 0

    # ---- A. §11-1 答案泄漏：声明为产出的字段，库里已有同名列 ----
    # 库里有这些列本身不是错 —— 那是让页面在 Agent 接进来之前能渲染的脚手架
    # （要则 §6：构造数据合法）。真正要验的是：每一列都在需求文档第 4 节
    # 被点名禁读。要则 §8：「第 4 节漏一列就是答案泄漏，而且没有症状。」
    doc4 = ""
    p05 = DOCS_DIR / "05-Agent输出面交底.md"
    if p05.exists():
        t = p05.read_text(encoding="utf-8")
        m = re.search(r"\n## 4\..*?(?=\n## 5)", t, re.S)
        doc4 = m.group(0) if m else ""
    sec("A · 要则 §11-1 + §8　产出字段在库里有同名列，是否已在第 4 节点名禁读")
    leaked = [(f, col_owner[f]) for f in DECLARED_OUTPUT if f in col_owner]
    undocumented = []
    for f, ts in leaked:
        named = re.search(r"`[^`]*\b%s\b[^`]*`" % re.escape(f), doc4) is not None
        if not named:
            undocumented.append(f)
        print("  %s  %-32s 已存在于 %s"
              % ("已禁读" if named else "未写明", f, "、".join(ts)))
    print()
    print("  产出字段 %d 个，库里已有同名列 %d 个，第 4 节未点名 %d 个。"
          % (len(DECLARED_OUTPUT), len(leaked), len(undocumented)))
    if undocumented:
        fail += 1
        print("  → 判定：答案泄漏。这几列没写进第 4 节：%s"
              % "、".join(undocumented))
    else:
        print("  → 判定：通过。库里的构造行是脚手架，且每一列都已点名禁读。")

    # ---- B. §3 禁读清单 ----
    sec("B · 要则 §3 + §8　命中禁读清单的列，是否已在第 4 节点名")
    hits: dict[str, list[str]] = {}
    hit_cols: set[str] = set()
    freed: set[str] = set()
    for cat, pats in FORBIDDEN.items():
        for col, ts in col_owner.items():
            if not any(re.search(p, col) for p in pats):
                continue
            if col in DEMO_READABLE:
                freed.add(col)
                continue
            hits.setdefault(cat, []).append("%s（%s）" % (col, ts[0]))
            hit_cols.add(col)
    miss = sorted(c for c in hit_cols
                  if not re.search(r"`[^`]*\b%s\b[^`]*`" % re.escape(c), doc4))
    for cat in FORBIDDEN:
        got = sorted(set(hits.get(cat, [])))
        if got:
            print("  【%s】%d 列" % (cat, len(got)))
            for g in got:
                col = g.split("（")[0]
                print("      %s %s" % ("已禁读" if col not in miss else "未写明", g))
    print()
    if freed:
        print("  Demo 例外放开 %d 列（王楠 2026-08-31 拍定，不计入禁读）：" % len(freed))
        print("      " + "、".join(sorted(freed)))
        print()
    print("  仍须禁读 %d 列，第 4 节未点名 %d 列。" % (len(hit_cols), len(miss)))
    if miss:
        fail += 1
        print("  → 判定：漏列。这几列没写进第 4 节：%s" % "、".join(miss))
    else:
        print("  → 判定：通过。每一列都已在第 4 节写明它替 Agent 答了什么。")

    # ---- C. §11-2 契约文档里有没有完整中文结论句 ----
    sec("C · 要则 §11-2　交底文档里有没有出现完整的中文结论句")
    for name in DOCS:
        p = DOCS_DIR / name
        if not p.exists():
            print("  %s  不存在" % name)
            continue
        text = p.read_text(encoding="utf-8")
        found = CONCLUSION_PAT.findall(text)
        sents = [m.group(0) for m in CONCLUSION_PAT.finditer(text)]
        print("  %-30s 命中 %d 处" % (name, len(sents)))
        for s in sents[:8]:
            print("      " + s.replace("\n", " ")[:96])
        if sents:
            fail += 1
    if JSON_SAMPLE.exists():
        raw = JSON_SAMPLE.read_text(encoding="utf-8")
        sents = [m.group(0) for m in CONCLUSION_PAT.finditer(raw)]
        print("  %-30s 命中 %d 处（整份就是构造载荷）"
              % (JSON_SAMPLE.name, len(sents)))
        for s in sents[:5]:
            print("      " + s[:96])
        if sents:
            fail += 1

    sec("结论")
    print("  三项检查失败 %d 项。" % fail)
    print("  要则 §8 要求需求文档五节齐全，其中第 4 节「不给 Agent 读的」")
    print("  比第 3 节更重要 —— 漏一列就是答案泄漏，而且没有症状。")
    con.close()
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
