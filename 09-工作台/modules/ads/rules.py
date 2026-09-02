"""广告分析模块可调参数。

契约 5.2：键一律带 `ads.` 前缀，必须夹紧在声明的 (下限, 上限, 步长) 内。
参数名本身不带前缀——core/ruleset.parse 会拼，写了会变成 ads.ads.xxx。

页面二（单一子 ASIN 广告决策）的参数只有两类：
  1. 判断窗口与样本守卫——决定「什么幅度算一条值得上屏的变化」
  2. 数值异常阈值——页面一用，页面二只借它标注效率是否偏离

这里没有「预算」「竞价」「广告位调整」类参数：方案 5.5 明确规定
规则未确认前不输出精确值，那些参数出现在界面上本身就是伪精确。
"""
from __future__ import annotations

from typing import Any

from core import ruleset
from core.ruleset import Param

PREFIX = "ads"

PARAMS: list[Param] = [
    Param("grain", "对象粒度", "AD_GROUP", kind="enum",
          choices=[("AD_GROUP", "广告组"), ("TARGET", "投放对象")],
          group="范围", note="一次只看一种粒度，两种不进同一张比较表"),
    Param("acos_max", "ACoS 观察线", 0.45, kind="num", lo=0.05, hi=2.0,
          step=0.05, group="效率",
          note="超过它标注为效率偏离；客户未确认前只做观察线不做判定"),
    Param("acos_rise", "ACoS 较自身历史上升", 0.30, kind="num", lo=0.05,
          hi=2.0, step=0.05, group="效率",
          note="相对自身前窗上升超过这个比例才算一条变化"),
    Param("cvr_drop", "转化率较自身历史下降", 0.40, kind="num", lo=0.05,
          hi=1.0, step=0.05, group="效率",
          note="相对自身前窗下降超过这个比例才算一条变化"),
    Param("cpc_max", "CPC 观察线", 3.0, kind="num", lo=0.5, hi=20.0,
          step=0.5, group="效率"),
    Param("min_clicks", "最小点击样本", 30, kind="num", lo=5, hi=500,
          step=5, group="样本",
          note="点击少于它的对象不参与效率判断，避免小样本噪声"),
    Param("min_clicks_per_half", "前后半窗各自最小点击", 8, kind="num",
          lo=2, hi=100, step=2, group="样本",
          note="环比要求前后两个半月各自有点击样本，否则不给变化率"),
    Param("stale_days", "证据过期天数", 14, kind="num", lo=3, hi=90, step=1,
          group="证据",
          note="证据比基准日旧过这个天数就标「过期」并降低判断确定程度"),
    Param("coverage_warn_days", "库存覆盖预警天数", 21, kind="num", lo=7,
          hi=120, step=7, group="约束",
          note="立即可售覆盖低于它时，扩量类任务标为受库存约束"),

    # ---- 页面一的数值异常规则 ----------------------------------------
    # 阈值按实测分布校准过：无效点击率中位就是 10.7%，默认 0.10 会打中
    # 65% 的 Campaign；预算范围内时间中位 79%、p75 97.7%，0.95 打中 41.7%。
    # 一条抓走大半总体的「异常阈值」没有区分度。
    Param("invalid_click_rate_max", "无效点击率上限", 0.15, kind="num",
          lo=0.0, hi=1.0, step=0.01, group="异常·绝对阈值"),
    Param("budget_capped_at", "预算打满判定线", 0.98, kind="num", lo=0.0,
          hi=1.0, step=0.01, group="异常·绝对阈值",
          note="预算范围内时间达到它就算打满"),
    Param("acos_rise_max", "ACoS 环比涨幅上限", 0.30, kind="num", lo=0.0,
          hi=5.0, step=0.05, group="异常·自身历史"),
    Param("cvr_drop_max", "转化率环比跌幅下限", -0.40, kind="num", lo=-1.0,
          hi=0.0, step=0.05, group="异常·自身历史"),
    Param("acos_peer_dev_max", "ACoS 相对同组中位偏离上限", 0.50,
          kind="num", lo=0.0, hi=5.0, step=0.05, group="异常·同组偏离"),
    Param("min_day_coverage", "可看趋势的最少天数", 14, kind="num", lo=0,
          hi=31, step=1, group="异常·样本"),
    Param("min_clicks_for_ratio", "比率类判定最少点击", 30, kind="num",
          lo=0, hi=500, step=5, group="异常·样本"),
    Param("min_impressions_for_ctr", "CTR 判定最少展示", 1000, kind="num",
          lo=0, hi=20000, step=100, group="异常·样本"),
    Param("min_spend_for_acos", "ACoS 判定最少花费", 50.0, kind="num",
          lo=0.0, hi=2000.0, step=10.0, group="异常·样本"),
    Param("min_clicks_for_invalid", "无效流量判定最少点击", 100,
          kind="num", lo=0, hi=5000, step=10, group="异常·样本"),
    Param("classes", "启用的异常类别", "all", kind="enum",
          choices=[("all", "全部四类"), ("absolute", "只看绝对阈值"),
                   ("self", "只看自身历史"), ("peer", "只看同组偏离"),
                   ("state", "只看数据状态")],
          group="异常·范围"),
    Param("daily_basis", "日粒度口径", "daily_scaled_to_month", kind="enum",
          choices=[("daily_scaled_to_month", "放大到月度总额"),
                   ("search_term_exact_day_sum", "搜索词原值")],
          group="口径",
          note="日线只能从搜索词报表拿到，两种口径算出的环比变化率相同，"
               "只有水平值不同"),
]

ruleset.check_prefix(PREFIX, PARAMS)


def resolve(query: dict | None = None) -> dict[str, Any]:
    return ruleset.parse(PREFIX, PARAMS, query or {})


def declare(query: dict | None = None) -> list[dict[str, Any]]:
    return ruleset.describe(PREFIX, PARAMS,
                            ruleset.parse(PREFIX, PARAMS, query or {}))


def fingerprint(query: dict | None = None) -> str:
    return ruleset.fingerprint(PREFIX,
                               ruleset.parse(PREFIX, PARAMS, query or {}))
