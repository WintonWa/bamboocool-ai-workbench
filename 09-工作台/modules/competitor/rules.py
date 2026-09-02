"""竞品模块可调参数。

契约 5.2：只声明，解析与夹紧统一由 core/ruleset.py 做。参数名不带前缀，
外壳按 MODULE["prefix"]="cmp" 拼成 cmp.xxx。

这里没有"威胁分数"类参数：方案 §5.4 与 V5 §3.2 都要求关注程度用可解释分级 +
依据条目，不生成综合分数。下面的参数只决定"什么幅度才算一条值得上屏的变化"，
它们全部属于决策记录 §9 的待客户确认项。
"""

from __future__ import annotations

from core import ruleset

PARAMS: list[ruleset.Param] = [
    ruleset.Param(
        "price_drop_pct", "降价入选幅度", 5.0, "num", 1.0, 30.0, 0.5,
        group="价格",
        note="件单价相对前一段基线下降超过这个百分比，才算一条价格变化",
    ),
    ruleset.Param(
        "gap_shift_pct", "价差变动幅度", 10.0, "num", 2.0, 50.0, 1.0,
        group="价格",
        note="自有与竞品的件单价倍数变动超过这个百分比才上屏",
    ),
    ruleset.Param(
        "rank_shift_pct", "排名变动幅度", 15.0, "num", 5.0, 60.0, 1.0,
        group="市场",
        note="小类排名相对窗口起点变动超过这个百分比才算市场表现变化",
    ),
    ruleset.Param(
        "kw_rank_shift", "关键词位置变动名次", 3, "num", 1, 20, 1,
        group="关键词",
        note="自然位变动超过这个名次才算一条关键词位置变化",
    ),
    ruleset.Param(
        "min_duration_days", "最短持续天数", 7, "num", 1, 60, 1,
        group="口径",
        note="变化至少持续这么多天才上屏，用来滤掉单日跳变",
    ),
    ruleset.Param(
        "family_coverage_pct", "产品族代表比例", 30.0, "num", 5.0, 100.0, 5.0,
        group="口径",
        note="发生变化的子体占在售子体的比例达到这个值，才考虑上卷为整族事件",
    ),
    ruleset.Param(
        "stale_days", "过期天数", 14, "num", 3, 90, 1,
        group="口径",
        note="某类观察比基准日旧过这么多天，标为过期并降低结论强度",
    ),
    ruleset.Param(
        "sort_by", "比较表排序", "attention", "enum",
        choices=[
            ("attention", "按关注程度"),
            ("recent", "按最近变化时间"),
            ("gap", "按自有价差倍数"),
            ("rank", "按小类排名"),
        ],
        group="排序",
        note="威胁比较表的排序口径；不生成综合威胁分数",
    ),
    ruleset.Param(
        "quick_only", "只看快捷位", False, "bool",
        group="排序",
        note="只显示运营常看的那批竞品",
    ),
]
