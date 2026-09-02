"""关键词模块可调参数。

契约 5.2：键一律带 `kw.` 前缀，必须夹紧在声明的 (下限, 上限, 步长) 内。
一条 query string 会同时带全部模块的参数，本模块只解析 `kw.` 下的键并忽略其余。
参数名本身不带前缀 —— core/ruleset.parse 会拼，写了会变成 kw.kw.xxx。

这里没有「匹配度」「结论定性」类参数：那些是判断层的活，已移交离线 Agent。
本模块参数只决定「什么幅度算一条值得上屏的变化」和「优先级怎么排」，
它们全部属于待客户确认项，界面上以「待确认」状态呈现。
"""

from __future__ import annotations

from typing import Any

from core import ruleset
from core.ruleset import Param

PREFIX = "kw"

PARAMS: list[Param] = [
    Param("compare", "比较周期", "day", kind="enum",
          choices=[("day", "对比前一日"), ("week", "对比前一周"), ("4week", "对比前 4 周")],
          group="窗口", note="日报环比与变化聚合的窗口"),
    Param("weak_rank", "自然位偏弱阈值", 20, kind="num", lo=3, hi=100, step=1,
          group="位置", note="第几位之后算位置偏弱；只影响分档，不改变证据结论"),
    Param("collect_depth", "采集深度上限", 144, kind="num", lo=48, hi=288, step=48,
          group="位置", note="超过它记为超出采集深度，而不是确认未覆盖"),
    Param("streak_days", "连续下滑天数", 7, kind="num", lo=3, hi=30, step=1,
          group="位置", note="自然位连续下滑多少天才算连续趋势"),
    Param("rank_shift", "位置变动名次", 3, kind="num", lo=1, hi=30, step=1,
          group="位置", note="自然位变动超过这个名次才算一条位置变化"),
    Param("group_dedup", "词组汇总按权分摊", True, kind="bool",
          group="汇总", note="一个词属于多个词组时按 1/组数 分权，避免搜索量重复计入"),
    # 不设「过期天数」：整个数据包都在同一个基准日 2026-08-03，没有任何对象会过期，
    # 那个参数无论怎么调页面一字不变。留一个永远不会动的旋钮比不留更糟。
    Param("w_demand", "优先级·需求规模权重", 0.30, kind="num", lo=0, hi=1, step=0.05,
          group="优先级"),
    Param("w_change", "优先级·变化幅度权重", 0.30, kind="num", lo=0, hi=1, step=0.05,
          group="优先级"),
    Param("w_push", "优先级·主推加权", 0.20, kind="num", lo=0, hi=1, step=0.05,
          group="优先级"),
    Param("w_evidence", "优先级·证据完整度权重", 0.20, kind="num", lo=0, hi=1,
          step=0.05, group="优先级"),
]

ruleset.check_prefix(PREFIX, PARAMS)

# 不叫 w_completeness：G9 禁词表含 complete（产品模块曾把 complete 泄漏上屏）
_W = ("w_demand", "w_change", "w_push", "w_evidence")


def resolve(query: dict | None) -> dict[str, Any]:
    v = ruleset.parse(PREFIX, PARAMS, query or {})
    total = sum(v[k] for k in _W)
    v["weights"] = {k: (round(v[k] / total, 4) if total else 0.25) for k in _W}
    return v


def declare(query: dict | None = None) -> list[dict[str, Any]]:
    return ruleset.describe(PREFIX, PARAMS, ruleset.parse(PREFIX, PARAMS, query or {}))


def fingerprint(query: dict | None = None) -> str:
    return ruleset.fingerprint(PREFIX, ruleset.parse(PREFIX, PARAMS, query or {}))
