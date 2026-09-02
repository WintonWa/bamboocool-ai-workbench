"""Rule parameters for the Demo.

Every number here is a **Demo preset**, not a customer standard, except where
marked ``customer_actual``. Defaults were chosen against the measured
distribution of the 342 selected child ASINs so that a threshold identifies an
exception rather than describing the norm. The measured hit count for each
default is recorded next to it and is also surfaced in the UI.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

from core.ruleset import Param

RULE_SET_ID = "demo-product-inventory"
RULE_VERSION = "2026-08-29.1"


@dataclass
class RuleSet:
    # --- 需求预测 ---
    # 这里原来有 10 个参数（5 个窗口权重、趋势强度/上下限、预测天数、活动系数与天数）。
    # R1 把需求预测整段移出页面：预测由独立的预测 Agent 离线产出，工作台只读结果。
    # 因此这些参数已删除 —— 留着会让人以为还能在页面上调预测，实际调不动。
    # 页面仍然自己算所有下游（余额、覆盖、断货日、缺口、风险、承接），
    # 所以下面的阈值类与承接类参数全部保留且依然即时生效。

    # --- 库存承接 ---
    # 安全库存天数：默认用客户自己填的 safety_days（14 或 60），customer_actual
    safety_days_override: int | None = None
    target_cover_days: int = 120
    # 超量判定：已知库存消化天数上限。实测消化天数中位数 174 天（该业务采购交期 30 天
    # + 备货前置 79 天，压半年货是常态），因此 180 天会命中 47%；365 天命中 51 个（15%），
    # 且与 365 天超龄收费节点一致。
    max_cover_days: int = 365
    # 销量过低时消化天数与覆盖天数没有意义，低于此日均只给区间不给精确值
    low_velocity_daily_units: float = 0.5
    # 已在 FBA 网络内但未可售的库存（待调仓 + 入库中）假设多少天后转可售
    internal_release_lag_days: int = 7

    # --- 风险阈值 ---
    # 可用率 = fba_sellable / fba_inventory。中位数 0.896，<0.60 命中 ~72 个
    availability_min_rate: float = 0.60
    # 181+ 占比。中位数 0，p90 0.366，>0.20 命中 46 个
    aged_share_max: float = 0.20
    # 仓储费压力
    fee_sales_ratio_max: float = 0.03
    fee_gross_ratio_max: float = 0.10

    # --- 仓储费费率（Demo 预设，不是 Amazon 公布费率）---
    fee_rate_per_m3_month: float = 27.50
    fee_aged_surcharge_per_m3_month: dict = field(
        default_factory=lambda: {
            "181-270天库龄": 17.50,
            "271-330天库龄": 35.00,
            "331-365天库龄": 52.50,
            "大于365天库龄": 52.50,
        }
    )

    # --- 批次消耗方式 ---
    # 库龄批次是数据层产物（v0.2.2 已按 FIFO 前滚），运行时不可切换。
    # 改成 LIFO 需要重建数据层，敏感性已知：181+ 相差 2.65 倍。
    depletion_method: str = "FIFO"
    depletion_method_locked: bool = True

    # --- 严重度分级 ---
    # 每类风险的 (medium, high) 比值门槛。比值 = 偏离程度，各风险自己定义。
    # 分开设是因为共用一套门槛会让"高"占到一半以上，失去排序意义。
    severity_cuts: dict = field(
        default_factory=lambda: {
            "shortage": [1.5, 3.0],
            "overstock": [1.6, 3.0],
            "availability": [1.5, 2.5],
            "aging": [1.5, 2.5],
            "storage_fee": [1.5, 2.5],
        }
    )

    def fingerprint(self) -> str:
        payload = json.dumps(asdict(self), sort_keys=True, ensure_ascii=False)
        return hashlib.sha1(payload.encode()).hexdigest()[:12]

    def version_label(self) -> str:
        return f"{RULE_SET_ID}@{RULE_VERSION}+{self.fingerprint()}"


NUMERIC_FIELDS = {
    "safety_days_override": int,
    "target_cover_days": int,
    "max_cover_days": int,
    "low_velocity_daily_units": float,
    "internal_release_lag_days": int,
    "availability_min_rate": float,
    "aged_share_max": float,
    "fee_sales_ratio_max": float,
    "fee_gross_ratio_max": float,
    "fee_rate_per_m3_month": float,
}


def from_query(query: dict[str, list[str]]) -> RuleSet:
    """Build a RuleSet from URL query params, ignoring anything unrecognised."""
    rules = RuleSet()
    for key, caster in NUMERIC_FIELDS.items():
        if key not in query:
            continue
        raw = query[key][0].strip()
        if raw == "":
            continue
        try:
            setattr(rules, key, caster(float(raw)) if caster is int else caster(raw))
        except (TypeError, ValueError):
            continue
    return rules


def describe(rules: RuleSet) -> list[dict[str, Any]]:
    """Parameter panel metadata: label, value, origin, note."""
    return [
        {"group": "库存承接", "key": "safety_days_override", "label": "安全库存天数", "value": rules.safety_days_override, "origin": "customer_actual",
         "note": "留空则使用客户自填值（326 个为 14 天，15 个为 60 天）"},
        {"group": "库存承接", "key": "target_cover_days", "label": "目标覆盖天数", "value": rules.target_cover_days, "origin": "demo_default", "step": 10},
        {"group": "库存承接", "key": "max_cover_days", "label": "超量判定消化天数", "value": rules.max_cover_days, "origin": "demo_default", "step": 30,
         "note": "超出此天数的库存计入超量。消化天数中位数 174 天；180 天命中 47%，365 天命中 51 个"},
        {"group": "库存承接", "key": "low_velocity_daily_units", "label": "低销量保护（日均件）", "value": rules.low_velocity_daily_units, "origin": "demo_default", "step": 0.1,
         "note": "日均低于此值时，覆盖天数与消化天数只给区间不给精确值"},
        {"group": "库存承接", "key": "internal_release_lag_days", "label": "待调仓/入库中转可售天数", "value": rules.internal_release_lag_days, "origin": "demo_default", "step": 1},
        {"group": "风险阈值", "key": "availability_min_rate", "label": "可用率下限", "value": rules.availability_min_rate, "origin": "demo_default", "step": 0.05,
         "note": "可用率 = 可售 ÷ FBA 总库存，中位数 0.896"},
        {"group": "风险阈值", "key": "aged_share_max", "label": "181+ 占比上限", "value": rules.aged_share_max, "origin": "demo_default", "step": 0.05,
         "note": "181 天以上占比，中位数 0，p90 0.366"},
        {"group": "风险阈值", "key": "fee_sales_ratio_max", "label": "仓储费占销售额上限", "value": rules.fee_sales_ratio_max, "origin": "demo_default", "step": 0.01},
        {"group": "风险阈值", "key": "fee_gross_ratio_max", "label": "仓储费占毛利上限", "value": rules.fee_gross_ratio_max, "origin": "demo_default", "step": 0.01},
        {"group": "风险阈值", "key": "fee_rate_per_m3_month", "label": "基础仓储费率 /m³/月", "value": rules.fee_rate_per_m3_month, "origin": "demo_default", "step": 2.5,
         "note": "每 m³ 月费率"},
        {"group": "批次消耗", "key": "depletion_method", "label": "批次消耗方式", "value": rules.depletion_method, "origin": "data_layer", "locked": True,
         "note": "库龄批次由数据层按 FIFO 前滚生成，切换需重建数据层"},
    ]


# ---------------------------------------------------------------------------
# 工作台参数声明层
#
# 外壳负责解析与夹紧（core/ruleset.py），模块只负责声明。上面的 RuleSet 是
# compute.py 消费的形状，保持原样不动；这里只是把"可调的那些"暴露给外壳面板。
#
# 两处与 18810 版的差异，都是外壳参数模型的约束，不是判断逻辑变化：
#
# 1. safety_days_override 原本是 int | None，None = 用客户自填值。外壳的 Param
#    没有"留空"这个概念（kind="num" 必须有 lo/hi/step 且默认值参与类型判断），
#    所以这里用 0 表示"用客户自填值"，from_params 再映射回 None。
#
# 2. depletion_method 不在这里声明。它 locked=True、恒为 FIFO，切换要重建数据层。
#    把一个调不动的东西放进"可调参数"面板会让人以为能调 —— 那是误导。
#    它作为事实由 /api/inventory/meta 带出去，在库龄板块处说明。
PARAMS = [
    Param("safety_days_override", "安全库存天数", 0, kind="num", lo=0, hi=180, step=1,
          group="库存承接",
          note="0 = 用客户自填值（326 个为 14 天，15 个为 60 天）；填了就整体覆盖"),
    Param("target_cover_days", "目标覆盖天数", 120, kind="num", lo=7, hi=365, step=10,
          group="库存承接"),
    Param("max_cover_days", "超量判定消化天数", 365, kind="num", lo=30, hi=730, step=30,
          group="库存承接",
          note="超出此天数的库存计入超量。消化天数中位数 174 天；180 天命中 47%，365 天命中 51 个"),
    Param("low_velocity_daily_units", "低销量保护（日均件）", 0.5, kind="num", lo=0.0, hi=10.0, step=0.1,
          group="库存承接",
          note="日均低于此值时，覆盖天数与消化天数只给区间不给精确值"),
    Param("internal_release_lag_days", "待调仓/入库中转可售天数", 7, kind="num", lo=0, hi=60, step=1,
          group="库存承接"),
    Param("availability_min_rate", "可用率下限", 0.60, kind="num", lo=0.0, hi=1.0, step=0.05,
          group="风险阈值",
          note="可用率 = 可售 ÷ FBA 总库存，中位数 0.896"),
    Param("aged_share_max", "181+ 占比上限", 0.20, kind="num", lo=0.0, hi=1.0, step=0.05,
          group="风险阈值",
          note="181 天以上占比，中位数 0，p90 0.366"),
    Param("fee_sales_ratio_max", "仓储费占销售额上限", 0.03, kind="num", lo=0.0, hi=1.0, step=0.01,
          group="风险阈值"),
    Param("fee_gross_ratio_max", "仓储费占毛利上限", 0.10, kind="num", lo=0.0, hi=1.0, step=0.01,
          group="风险阈值"),
    Param("fee_rate_per_m3_month", "基础仓储费率 /m³/月", 27.50, kind="num", lo=0.0, hi=200.0, step=2.5,
          group="风险阈值", note="每 m³ 月费率，Demo 预设，不是 Amazon 公布费率"),
]


def from_params(values: dict[str, Any]) -> RuleSet:
    """把外壳已夹紧的参数字典变成 RuleSet。

    收到的键不带模块前缀（外壳已剥掉），值已按 lo/hi 夹紧过，
    所以这里不再做范围检查 —— 重复夹紧会掩盖外壳侧的问题。
    """
    rules = RuleSet()
    for p in PARAMS:
        if p.name not in values:
            continue
        raw = values[p.name]
        if raw is None:
            continue
        caster = NUMERIC_FIELDS.get(p.name, float)
        try:
            setattr(rules, p.name, caster(float(raw)) if caster is int else caster(raw))
        except (TypeError, ValueError):
            continue
    # 0 是"留空"的表达，映射回 None 交给 compute 走客户自填值那条路
    if rules.safety_days_override in (0, 0.0):
        rules.safety_days_override = None
    return rules
