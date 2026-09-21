"""广告调整方案 · 标准化输出模板（单一真相来源）

字段全部来自 2026-09-03 会议原话，不是我发明的：

  00:36:32-42  「我这个词，我就是要把它上调 bid，或者说把它的 top placement
                的那个比例，从 40% 上调到 50%」
                → 调整对象 / 调整维度 / 调整方向 / 当前值 → 目标值
  00:36:42     「我把动作、原因、然后预期结果都列出来之后，给到人去做审批」
                → 卡面三栏的骨架
  00:38:45     「我有两个阈值，第一个就是时间阈值，第二个就是数据量阈值。
                那我就三天之后，或者数量达到之后，我就直接去看」
                → 时间阈值 / 数据量阈值 / 先到先算
  00:40:06-39  「我监控指标就是我在这个词下到底有没有这么多的份额有提升，
                或者说我词的数量有没有增加，那量化指标就是这个数字……
                这几个数指标都是要监控的指标」
                → 监控指标，每条带基准值与目标值
  00:38:45     「如果这个数据他达到了我们的一个目标的话，那我就判断这个策略
                是合理的」/ 00:40:39「如果没达到的话，那就是有问题的，
                那同时就会给我们自己的运营提这个推送」
                → 达标判据 / 不达标处置

**这份是模板，不是内容。** 两个来源都往它里面填：
  - Agent 的 B4 输出（现在只填得上一小半，缺的字段页面如实显示「未给出」）
  - 人写的示例脚本（demo_script.py，填满，用来说明规则确认后该长什么样）

两边**用同一个渲染器、同一个字段顺序**，所以形式上不可区分；
唯一的区别是最后那个「产出来源」字段自己写着它是哪来的 —— 那是一个字段，
不是一条横幅。要能审计，但不靠视觉上把它隔离出去。

模板的价值在于它同时是**给 Agent 的验收单**：哪一格是「未给出」，
就是 Agent 侧下一步要补的输出点。
"""
from __future__ import annotations

# 方向中文从 compute 取，不在这里抄第二份（抄一份就会漂）
from .compute import DIRECTION_CN

# 字段顺序 = 上屏顺序。改这里就改了两个来源的显示，不许在前端另排一次。
FIELDS = [
    ("target", "调整对象"),
    ("lever", "调整维度"),
    ("direction", "调整方向"),
    ("from_to", "当前值 → 目标值"),
    ("delta", "调整幅度"),
    ("goal", "调整目标"),
    ("time_threshold", "时间阈值"),
    ("volume_threshold", "数据量阈值"),
    ("trigger_rule", "到期取数方式"),
    ("pass_rule", "达标判据"),
    ("on_fail", "不达标处置"),
    ("guard", "护栏"),
    ("origin", "产出来源"),
]

# 可调的维度。**枚举写死在这里**，两边都从这取中文 —— 各自发明一套
# 就会出现「竞价」和「bid」并存，接得上但讲的不是同一件事。
LEVERS = {
    "bid": "关键词竞价",
    "placement_top": "搜索结果顶部广告位比例",
    "placement_rest": "商品页面广告位比例",
    "budget": "广告组日预算",
    "keyword_add": "关键词投放（新增）",
    "keyword_negative": "否定关键词",
    "object_state": "广告对象状态",
    "match_type": "匹配方式",
    "acos_cap": "效率上限（ACoS）",
    "scope": "本品盘点范围",
}

# 缺字段时的统一说法。**不留空白** —— 空白会把「Agent 没输出这一格」
# 藏起来，比显示出来更难查（这个坑在关键词模块付过学费）。
MISSING = "本次运行未给出"

ORIGIN_AGENT = "本次 Agent 运行"
ORIGIN_TEMPLATE = "标准模板示例 · 规则确认后由 Agent 产出"


def _t(v):
    """空值一律换成统一说法，不返回空串。"""
    if v is None or v == "" or v == []:
        return MISSING
    return v


def _pair(from_v, to_v, from_l, to_l, fallback):
    """从→到拆成两个值，给前端做大数字用。

    要则第一节：页面里最大的东西应该是数字。「$1.87 → $2.15」这一对才是
    「具体改什么」，必须能单独取出来放大；合成一个字符串就只能当一行文本。
    取不到就把 fallback 放在 to 位，from 位留空 —— 那时候卡面上没有数字，
    正是要让人看见的对比。
    """
    return {"from_value": from_v, "to_value": to_v,
            "from_label": from_l, "to_label": to_l,
            "pair_fallback": fallback}


def normalize_agent(item: dict, obj_name: str | None, rs: dict) -> dict:
    """把 Agent 的 B4 原样映射进模板。

    映射只做「搬」，不做「补」：Agent 没输出的格子就是 MISSING。
    往里填一个我推算出来的值，会让页面看起来像 Agent 已经能给数值了 ——
    那是把缺口藏起来，也是这次重构最不该犯的错。
    """
    withheld = bool(item.get("exact_values_withheld"))
    wins = item.get("review_windows") or []
    metrics = item.get("observation_metrics") or []
    return {
        "recommendation_id": item.get("recommendation_id"),
        "priority": item.get("priority") or "",
        "direction_code": item.get("direction"),
        "ad_purpose": item.get("ad_purpose"),
        "ad_object_id": item.get("ad_object_id"),
        "fields": {
            "target": _t(obj_name or (
                "新建对象（当前无对象承接）"
                if item.get("structure_gap_id") else None)),
            # Agent 现在不输出「调 什么」这一维，所以这里必然是 MISSING。
            # 这一格空着正是要让人看见的东西。
            "lever": MISSING,
            "direction": _t(DIRECTION_CN.get(item.get("direction"))),
            "from_to": (
                "规则未确认，不给数值" if withheld
                else _t(item.get("exact_value"))),
            "delta": "规则未确认，不给数值" if withheld else MISSING,
            "goal": _t(item.get("ad_purpose")),
            "time_threshold": _t("、".join(wins) if wins else None),
            "volume_threshold": _t(
                "%d 次点击" % rs["min_clicks"]
                if rs.get("min_clicks") is not None else None),
            "trigger_rule": "两个阈值先到先算" if wins else MISSING,
            "pass_rule": MISSING,
            "on_fail": MISSING,
            "guard": _t("；".join(item.get("preconditions") or []) or None),
            "origin": ORIGIN_AGENT,
        },
        # 监控指标：Agent 给的是一串句子，没有基准值与目标值两列。
        # 原样搬进来并标出缺的两列 —— 不替它拆，拆就是我在替它判断。
        # Agent 不给数值，所以 from/to 两格是空的，只留一句说明 ——
        # 卡面上那两个大数字的位置空着，比在字段表里写一行更说明问题
        "pair": _pair(None, None, "当前值", "目标值",
                      "规则未确认，不给数值" if withheld else MISSING),
        "watch": [{"metric": m, "baseline": MISSING, "target": MISSING}
                  for m in metrics],
        "reason": item.get("rationale"),
        "risks": item.get("risks") or [],
        "uncertainty": item.get("uncertainty"),
        "diagnosis_id": item.get("diagnosis_id"),
        "is_template": False,
    }


def normalize_template(item: dict) -> dict:
    """把示例脚本映射进同一个模板。字段名与上面逐字一致。"""
    return {
        "recommendation_id": item["recommendation_id"],
        "priority": item.get("priority") or "",
        "direction_code": item.get("direction"),
        "ad_purpose": item.get("ad_purpose"),
        "ad_object_id": item.get("ad_object_id"),
        "fields": {
            "target": _t(item.get("target")),
            "lever": _t(LEVERS.get(item.get("lever"), item.get("lever"))),
            "direction": _t(DIRECTION_CN.get(item.get("direction"))),
            "from_to": _t(item.get("from_to")),
            "delta": _t(item.get("delta")),
            "goal": _t(item.get("goal")),
            "time_threshold": _t(item.get("time_threshold")),
            "volume_threshold": _t(item.get("volume_threshold")),
            "trigger_rule": _t(item.get("trigger_rule")),
            "pass_rule": _t(item.get("pass_rule")),
            "on_fail": _t(item.get("on_fail")),
            "guard": _t(item.get("guard")),
            "origin": ORIGIN_TEMPLATE,
        },
        "pair": _pair(item.get("from_value"), item.get("to_value"),
                      item.get("from_label") or "当前值",
                      item.get("to_label") or "目标值", None),
        "watch": item.get("watch") or [],
        "reason": item.get("reason"),
        "risks": item.get("risks") or [],
        "uncertainty": item.get("uncertainty"),
        "diagnosis_id": item.get("diagnosis_id"),
        "is_template": True,
    }


def field_coverage(rows: list[dict]) -> dict:
    """模板覆盖率：这一批建议里，每个字段有几条真填上了。

    这是给 Agent 侧的验收单 —— 哪一格覆盖率是 0，就是下一步要补的输出点。
    """
    out = []
    for key, label in FIELDS:
        filled = sum(1 for r in rows
                     if (r["fields"].get(key) or MISSING) != MISSING
                     and not str(r["fields"].get(key) or "").startswith("规则未确认"))
        out.append({"key": key, "label": label,
                    "filled": filled, "total": len(rows)})
    return {"fields": out, "total": len(rows)}
