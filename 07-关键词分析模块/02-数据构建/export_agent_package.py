#!/usr/bin/env python3
"""导出给 Agent 侧看的两份机械产物：

1. `06-数据字典.md`  —— 24 张表逐张：行数、列数、每列类型与枚举全集、这张表干什么
2. `07-接口JSON样例.json` —— 六个路由的真实响应，长数组截断到前 2 项并标注原长度

产物是给另一侧的 Agent 读的，所以必须从落盘的库和在跑的服务里取。

用法：先 09-工作台/start.py start，然后
      /usr/bin/python3 export_agent_package.py
"""
from __future__ import annotations

import json
import pathlib
import sqlite3
import sys
import urllib.request

HERE = pathlib.Path(__file__).parent
DB = HERE / "v0.1.0" / "keyword_demo.sqlite"
OUT_DIR = HERE.parent / "01-方案与数据需求"
API = "http://127.0.0.1:18820/api/keyword/"

# 每张表一句话说明它在业务上是什么。九层结构见 02-关键词Demo数据需求.md
TABLE_PURPOSE = {
    "dim_keyword_scope": "L0 口径锚：站点、品线、基准日、各窗口边界",
    "dim_keyword_term": "L1 共享词库主表。一行一个唯一关键词，含库内状态与运营角色",
    "dim_keyword_alias": "L1 同词多写法归一（mens/men's/mens underware 三变体购买率差 13 倍）",
    "dim_keyword_brand": "L1 品牌维表，区分自有品牌词与竞品品牌词",
    "bridge_keyword_attribute": "L1 词×属性维度（材质/功能/场景/人群/款式/颜色/尺码…）",
    "dim_keyword_group": "L2 需求词组（按属性锚词聚成的需求单元）",
    "bridge_keyword_group": "L2 词×词组，带 dedup_weight（一词多组时按 1/组数 分摊，防重复计入）",
    "dim_keyword_attribute_seed": "L2 客户人工标注的属性词种子（S 必投 21/A 重要 55/B 补充 86，★ 59）",
    "fact_keyword_attribute_combo": "L2 属性词×核心大词的组合矩阵",
    "fact_keyword_category_rollup": "L2 客户总览 sheet 的分类基线，用来对账聚合口径",
    "fact_keyword_market_snapshot": "L3 市场事实逐期快照。周 26 期 + 月 12 期，两频率分开不折算",
    "fact_keyword_head_asin": "L3 每词每期的头部 ASIN 与前十名单（自有 ASIN 命中就是真实锚点）",
    "dim_keyword_child_pair": "L4 关键词×子 ASIN 关系对，覆盖位置监控的基本单位",
    "fact_keyword_child_position_daily": "L4 逐日自然位与广告位，五态可区分（有排名/确认未覆盖/超采集深度/当日采集失败/未纳入监控）",
    "dim_keyword_state_label": "L4 五态与各枚举的中文标签映射表（页面靠它把码值翻成中文）",
    "fact_keyword_child_traffic_daily": "L5 子体逐日流量（Sessions/转化），日报代理指标的来源",
    "fact_keyword_traffic_attribution_daily": "L5 流量归因残差（监控词能解释多少自然 Sessions，0–54.2%）",
    "dim_keyword_child_goal": "L6 子体的产品目标与主推关系（上游带入，不是关键词 Agent 判的）",
    "fact_keyword_child_absorb": "L6 库存承接结果（能不能承接扩量，上游带入）",
    "fact_keyword_market_change_event": "L7 市场变化事件【Agent 输出点 C】",
    "fact_keyword_coverage_event": "L7 覆盖与位置变化事件【Agent 输出点 D】",
    "fact_keyword_evidence": "L8 证据结论【Agent 输出点 A · 最重要】",
    "fact_keyword_audit_record": "L8 盘点快照【Agent 输出点 E】",
    "fact_keyword_daily_report": "L9 动态日报五问五答【Agent 输出点 B】",
}

ROUTES = [
    ("meta", "模块自描述：口径、窗口、各表计数、分布"),
    ("overview", "页面一 关键词动态与机会总览"),
    ("terms?limit=3", "页面二 列表态 市场关键词库"),
    ("term/kw_00001", "页面二 详情态 单词深研（mens underwear）"),
    ("children", "页面三 子体清单"),
    ("child/B0CBPXNC1M", "页面三 盘点（五态齐全的演示对象）"),
]

TRUNC_AT = 2  # 长数组只留前几项

# 产出侧字段：值必须抹掉，只留类型示意。
# 要则 §11-2「契约文档里有没有出现完整的中文结论句？有 → 钉了答案」。
# 这份样例的用途是让 Agent 看清信封形状，不是让它照着写答案 ——
# 广告那侧就是把 constructed 行原样发给 LLM 当 items，把模型压成了复印机。
MASK_FIELDS = {
    # A 证据结论
    "evidence_type", "evidence_type_label", "priority", "conclusion",
    "main_basis", "evidence_completeness", "evidence_completeness_label",
    "next_verification", "next_verification_label",
    "competitor_verification_state", "competitor_verification_label",
    "ref_market_event_ids", "ref_coverage_event_ids",
    # B 动态日报
    "traffic_proxy_value", "traffic_proxy_delta",
    "q1_traffic_result", "q2_main_movers", "q3_core_coverage_change",
    "q4_new_signals", "q5_priority_next",
    "priority_evidence_ids", "coverage_event_ids",
    # C/D 两张事件表
    "event_type", "event_type_label", "continuity", "continuity_label",
    "label", "change_ratio", "change_shape_label",
    # E 盘点快照
    "evidence_count", "evidence_type_counts",
    # 建议出价属于广告模块（要则 §5 跨模块动作）
    "suggested_bid_low", "suggested_bid_high",
    # 中文理由
    "comparable_block_reason",
    # 覆盖形态定性（不在王楠放开的三组里，保持抹值）
    "pair_shape_label",
    # 构造元数据（要则 §3 最后一类，且 G9 禁上屏）
    "value_origin", "rule_version",
}

# ---- Demo 例外：以下三组不抹 -------------------------------------------
# 王楠 2026-08-31 拍定：「这 3 个都可以给 Agent 看。即使前面没输出，
# 在我们 Demo 这一块可以给 Agent 看。」照要则 §7 广告那条口子的格式记在这里，
# 是例外不是先例。三组都是**别的判断点的答案**，不是关键词 Agent 自己的产出：
#
#   一 产品定位   product_goal / push_role / product_lifecycle
#                 真业务里前两个是运营在后台填的，本就可输入；
#                 product_lifecycle 是产品模块的判断，对关键词 Agent 是上下文
#   二 库存承接   absorb_* / latest_order_date / *_stockout_date /
#                 suggested_replenishment_qty / projected_lost_sales_units /
#                 confidence_score —— 库存 Agent 的产出，真业务里是上游接力
#   三 词库定性   library_status / operator_role / alias_type_label
#                 ⚠️ 放开的代价：J2b「运营角色定性」由判断点降为输入，
#                 Agent 不再声称它在判断运营角色
#
# 这三组一律不加进 MASK_FIELDS —— 列在这里只为让下一个人知道是刻意的。
DEMO_READABLE = {
    "product_goal", "product_goal_label", "push_role", "push_role_label",
    "product_lifecycle", "lifecycle",
    "absorb_state", "absorb_state_label", "absorb_detail",
    "inventory_limit_label", "latest_order_date", "base_stockout_date",
    "stress_stockout_date", "days_to_base_stockout", "dynamic_safety_days",
    "suggested_replenishment_qty", "projected_lost_sales_units",
    "confidence_score",
    "library_status", "library_status_label", "operator_role",
    "operator_role_label", "alias_type_label",
}
assert not (MASK_FIELDS & DEMO_READABLE), "放开的字段不能同时在抹值表里"

TYPE_HINT = {
    str: "<字符串·由 Agent 判断>",
    int: "<整数·由 Agent 判断>",
    float: "<小数·由 Agent 判断>",
    bool: "<布尔·由 Agent 判断>",
    list: "<数组·由 Agent 判断>",
    dict: "<对象·由 Agent 判断>",
}


def mask(v):
    """把产出侧的值换成类型示意，保留 null（null 本身是合法产出，见要则 §4）。"""
    if v is None:
        return None
    return TYPE_HINT.get(type(v), "<值·由 Agent 判断>")


def truncate(o, path=""):
    """长数组截断到前 TRUNC_AT 项；产出侧字段的值抹成类型示意。"""
    if isinstance(o, dict):
        out = {}
        for k, v in o.items():
            out[k] = mask(v) if k in MASK_FIELDS else truncate(v, f"{path}.{k}")
        return out
    if isinstance(o, list):
        if len(o) <= TRUNC_AT:
            return [truncate(v, path + "[]") for v in o]
        kept = [truncate(v, path + "[]") for v in o[:TRUNC_AT]]
        kept.append(f"…… 此数组原有 {len(o)} 项，样例只留前 {TRUNC_AT} 项")
        return kept
    return o


def write_dictionary(con: sqlite3.Connection) -> int:
    lines = [
        "# 关键词模块 · 数据字典",
        "",
        "> 机械导出，不要手改。重新生成："
        "`/usr/bin/python3 02-数据构建/export_agent_package.py`",
        "",
        "库文件 `02-数据构建/v0.1.0/keyword_demo.sqlite`。"
        "产品身份走 `ATTACH` 读产品包 v0.3.0，本库不重建 "
        "`dim_product_child` / `dim_product_parent`（接入契约 G7）。",
        "",
    ]
    tables = [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    total = 0
    lines.append("## 表清单")
    lines.append("")
    lines.append("| 表 | 行数 | 列 | 作用 |")
    lines.append("| --- | ---: | ---: | --- |")
    for t in tables:
        n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        c = len(con.execute(f"PRAGMA table_info({t})").fetchall())
        total += n
        lines.append("| `%s` | %s | %d | %s |"
                     % (t, f"{n:,}", c, TABLE_PURPOSE.get(t, "—")))
    lines.append("")
    lines.append("共 %d 张表 / %s 行。" % (len(tables), f"{total:,}"))
    lines.append("")

    lines.append("## 逐表字段")
    lines.append("")
    for t in tables:
        n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        lines.append("### `%s`　%s 行" % (t, f"{n:,}"))
        lines.append("")
        lines.append(TABLE_PURPOSE.get(t, ""))
        lines.append("")
        lines.append("| 列 | 类型 | 非空 | 取值 |")
        lines.append("| --- | --- | ---: | --- |")
        for c in con.execute(f"PRAGMA table_info({t})"):
            name, typ = c[1], c[2] or "-"
            nn = con.execute(
                f"SELECT COUNT({name}) FROM {t}").fetchone()[0]
            d = con.execute(
                f"SELECT COUNT(DISTINCT {name}) FROM {t}").fetchone()[0]
            if 0 < d <= 12 and typ.upper() in ("TEXT", "VARCHAR", "-"):
                vals = [str(r[0]) for r in con.execute(
                    f"SELECT DISTINCT {name} FROM {t} "
                    f"WHERE {name} IS NOT NULL ORDER BY 1")]
                shown = "枚举 %d：" % d + " · ".join(vals)
                if len(shown) > 170:
                    shown = shown[:167] + "…"
            else:
                s = con.execute(
                    f"SELECT {name} FROM {t} WHERE {name} IS NOT NULL "
                    f"AND {name} != '' LIMIT 1").fetchone()
                sv = "" if s is None else str(s[0]).replace("\n", " ")
                shown = ("样例 `%s`" % sv[:88]) if sv else "全空"
            lines.append("| `%s` | %s | %s | %s |"
                         % (name, typ, f"{nn:,}", shown.replace("|", "\\|")))
        lines.append("")
    p = OUT_DIR / "06-数据字典.md"
    p.write_text("\n".join(lines), encoding="utf-8")
    print("写出 %s（%d 行）" % (p.name, len(lines)))
    return len(tables)


def write_samples() -> int:
    out = {
        "_说明": "六个路由的真实响应**信封形状**。长数组截断到前 %d 项。"
                 "重新生成：/usr/bin/python3 02-数据构建/export_agent_package.py" % TRUNC_AT,
        "_产出侧已抹值": "凡是 Agent 该判断的字段，值一律换成 <…由 Agent 判断>。"
                    "这是刻意的：按《08-Agent需求与数据契约要则》§11-2，"
                    "契约文档里出现完整的中文结论句就等于钉了答案。"
                    "看形状用这份，看该输出什么看 05-Agent输出面交底.md 第 2 节。",
        "_抹掉的字段数": len(MASK_FIELDS),
        "_基址": "http://127.0.0.1:18820/api/keyword/",
        "_参数": "全部 kw.* 参数以 query 传，由外壳夹紧后放进 c.params",
        "路由": {},
    }
    ok = 0
    for route, desc in ROUTES:
        try:
            with urllib.request.urlopen(API + route, timeout=40) as r:
                payload = json.load(r)
            out["路由"][route] = {"_呈现": desc, "响应": truncate(payload, route)}
            ok += 1
        except Exception as exc:
            out["路由"][route] = {"_呈现": desc, "_取数失败": str(exc)}
    p = OUT_DIR / "07-接口JSON样例.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    kb = p.stat().st_size / 1024
    print("写出 %s（%d/%d 路由，%.1f KB）" % (p.name, ok, len(ROUTES), kb))
    return ok


def main() -> int:
    if not DB.exists():
        print("找不到库：%s" % DB)
        return 1
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    write_dictionary(con)
    con.close()
    write_samples()
    return 0


if __name__ == "__main__":
    sys.exit(main())
