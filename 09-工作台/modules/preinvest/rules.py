"""面料预投模块 · 可调参数声明。

契约 §5.2：键一律带 `pre.` 前缀，外壳负责解析与夹紧，这里只声明。

**v0.3 删掉了四个窗口权重参数（w_3d/w_7d/w_15d/w_30d）。**
它们是用来复刻运营现在那套「最近 3/7/15/30 天加权平均」的。用户 2026-09-04 的判断：

  「本身吴组长他也说了，他们现在的这个预估方式是比较草率的，只考虑了 3 天销量、
    7 天销量、14 天销量这种平均。那我觉得既然用上 AI 了，就不需要这么草率的
    拉个公式了……我们直接用我们的预估销量模型做就行了呀。」

所以预投量的来源改成**已有的逐子体 90 天需求预估**（需求预测 Agent 的产出，
没跑过则回落数据包快照），不再自己算一套加权平均。参照列换成一个纯事实：
近 30 天实销 —— 吴组长举例时用的就是它（「我最近 30 天卖了 1000 件」→ 投 110%）。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

from core.ruleset import Param

RULE_SET_ID = "demo-preinvest"
RULE_VERSION = "2026-09-04.3"


@dataclass
class RuleSet:
    # --- 预投量 ---
    # 安全余量：吴组长举例「预计卖 100 盒，我可能就会投到 110 盒」= 10%
    safety_margin_rate: float = 0.10

    # 预投对应的销售月 = 基准日月份 + 这个偏移。源表全是 M+2，所以默认 2。
    # 调成 3 会落到 11 月，而需求预估只有 90 天（到 11-01）、覆盖 1/30 天 ——
    # 那条路要先把预估延长到 119 天。
    target_month_offset: int = 2

    # --- 考核 ---
    # 达成率 = 总下单数 ÷ 预投总数。客户明确给的 70%，是 customer_actual。
    achieve_rate_min: float = 0.70

    # --- 需要人复核的判据 ---
    # 这一页的产物是运营要交给生产端的那份预投表。57 行全平铺等于把分类工作
    # 推回给人，所以按几条确定性判据挑出「需要你看」的行，其余默认折叠。
    #
    # 判据一：预测区间太宽 = 这个组下个月本身不好判。p90/p50 超过这个倍数就挑出来。
    review_band_ratio: float = 1.40
    # 判据二：上一轮达成率低于考核线（用 achieve_rate_min）
    # 判据三：目标销售月排了 BD/LD 且覆盖面够大
    review_promo_coverage: float = 0.30
    # 判据四：销量预测还没经过 AI 真判断（走的是数据包快照）—— 无阈值
    # 判据五：成长期，本身不好判 —— 无阈值

    # --- 面料换算（客户说这不是真值，只需搭起来）---
    # 由客户口述锚点「30 万盒≈200 吨」反推，666.67 g/盒
    fabric_g_per_box: float = 666.67
    # 面料成本占成品成本的比例。客户未提供，Demo 预设。
    fabric_cost_share: float = 0.35

    # --- 时间链条 ---
    # 预投→开卖合计天数。吴组长：「按两个半月比较平均一点」= 75 天。
    # 它决定「这批货最早能卖的那天」，从而决定目标销售月。
    lead_days_total: int = 75

    def fingerprint(self) -> str:
        payload = json.dumps(asdict(self), sort_keys=True, ensure_ascii=False)
        return hashlib.sha1(payload.encode()).hexdigest()[:12]

    def version_label(self) -> str:
        return f"{RULE_SET_ID}@{RULE_VERSION}+{self.fingerprint()}"


NUMERIC_FIELDS: dict[str, Any] = {
    "safety_margin_rate": float,
    "target_month_offset": int,
    "achieve_rate_min": float,
    "review_band_ratio": float,
    "review_promo_coverage": float,
    "fabric_g_per_box": float,
    "fabric_cost_share": float,
    "lead_days_total": int,
}


PARAMS = [
    Param("safety_margin_rate", "安全余量", 0.10, kind="num", lo=0.0, hi=0.5, step=0.01,
          group="预投量",
          note="预投比预估销量多投多少。客户举例「预计卖 100 盒投到 110 盒」，反推约 10%"),
    Param("target_month_offset", "预投对应几个月后", 2, kind="num", lo=1, hi=6, step=1,
          group="预投量",
          note="8 月预投对应 10 月销量（M+2）。源表的逐月预投列与月报预投下单表全是 M+2。"
               "改成 3 会落到 11 月，但需求预估只有 90 天、覆盖 1/30 天，要先延长到 119 天"),
    Param("achieve_rate_min", "达成率考核线", 0.70, kind="num", lo=0.0, hi=1.0, step=0.05,
          group="考核",
          note="客户明确的考核口径：预投 100 万至少用掉 70 万"),
    Param("review_band_ratio", "预测区间过宽线", 1.40, kind="num", lo=1.0, hi=3.0, step=0.05,
          group="复核范围",
          note="乐观预测 ÷ 基准预测 超过这个倍数，说明这个组下月本身不好判，挑出来让人看"),
    Param("review_promo_coverage", "活动覆盖面下限", 0.30, kind="num",
          lo=0.0, hi=1.0, step=0.05, group="复核范围",
          note="下月活动要覆盖这个组多大比例的尺码才挑出来；"
               "实测覆盖比例中位 17%，不设门槛会把 47/57 行都标成需复核"),
    Param("fabric_g_per_box", "每盒折面料（克）", 666.67, kind="num",
          lo=0.0, hi=5000.0, step=10.0, group="面料换算",
          note="由客户口述「30 万盒≈200 吨」反推。客户说过面料这块不是真值，只需搭起来"),
    Param("fabric_cost_share", "面料占成品成本比例", 0.35, kind="num",
          lo=0.0, hi=1.0, step=0.05, group="面料换算",
          note="客户未提供，Demo 预设 · 金额一栏因此是估算，主指标用盒与吨"),
    Param("lead_days_total", "预投到开卖天数", 75, kind="num", lo=30, hi=180, step=5,
          group="时间链条",
          note="客户口述「预投加生产加物流约两个半月」。它决定这批货最早能卖的那天，"
               "从而决定预投对应哪个销售月"),
]


def from_params(values: dict[str, Any]) -> RuleSet:
    """外壳已剥前缀并按 lo/hi 夹紧，这里只做类型转换，不重复夹紧。"""
    rs = RuleSet()
    for p in PARAMS:
        if p.name not in values:
            continue
        raw = values[p.name]
        if raw is None or raw == "":
            continue
        caster = NUMERIC_FIELDS.get(p.name, float)
        try:
            setattr(rs, p.name, caster(float(raw)) if caster is int else caster(raw))
        except (TypeError, ValueError):
            continue
    return rs


def describe(rs: RuleSet) -> list[dict[str, Any]]:
    """参数面板元信息。`origin` 分三档，页面据此区分哪些数是客户给的。

    customer_actual  客户明确给过的数字
    customer_derived 由客户口述反推的
    demo_default     客户没给、Demo 预设，必须标「待确认」
    """
    return [
        {"group": "预投量", "key": "safety_margin_rate", "label": "安全余量",
         "value": rs.safety_margin_rate, "origin": "customer_derived",
         "note": "客户举例「预计卖 100 盒投到 110 盒」"},
        {"group": "预投量", "key": "target_month_offset", "label": "预投对应几个月后",
         "value": rs.target_month_offset, "origin": "customer_actual",
         "note": "源表的逐月预投列与月报预投下单表全是 M+2"},
        {"group": "考核", "key": "achieve_rate_min", "label": "达成率考核线",
         "value": rs.achieve_rate_min, "origin": "customer_actual",
         "note": "预投 100 万至少用掉 70 万"},
        {"group": "复核范围", "key": "review_band_ratio", "label": "预测区间过宽线",
         "value": rs.review_band_ratio, "origin": "demo_default",
         "note": "乐观 ÷ 基准 超过这个倍数就挑出来让人看"},
        {"group": "复核范围", "key": "review_promo_coverage", "label": "活动覆盖面下限",
         "value": rs.review_promo_coverage, "origin": "demo_default",
         "note": "实测活动覆盖尺码比例中位 17%，不设门槛会把 47/57 行标成需复核"},
        {"group": "面料换算", "key": "fabric_g_per_box", "label": "每盒折面料（克）",
         "value": rs.fabric_g_per_box, "origin": "customer_derived",
         "note": "由「30 万盒≈200 吨」反推；客户说面料这块不是真值"},
        {"group": "面料换算", "key": "fabric_cost_share", "label": "面料占成品成本比例",
         "value": rs.fabric_cost_share, "origin": "demo_default",
         "note": "客户未提供 · 金额一栏是估算，主指标用盒与吨"},
        {"group": "时间链条", "key": "lead_days_total", "label": "预投到开卖天数",
         "value": rs.lead_days_total, "origin": "customer_derived",
         "note": "客户口述约两个半月，决定预投对应哪个销售月"},
    ]
