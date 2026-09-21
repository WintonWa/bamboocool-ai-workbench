"""广告页面二 · 示例调整方案（人写的演示脚本）

**这份不是 Agent 产出。** 王楠 2026-09-04 明确授权写死，用于当天汇报：
现有六个决策上下文的 `rule_status` 全是 `unconfirmed`，交底件（方案 5.5）规定
规则未确认不许输出精确值，于是真 Agent 只敢出「继续观察 / 先补信息 / 前置条件」，
三十八条历史建议里一条 ADJUST、一条 PAUSE 都没有 —— 讲不出「把某个广告组的
某项上调/下调/关掉」。

三条纪律，照 `modules/overview/module.py` 已有的做法（那页的结论句同样是人写的）：

1. **只准有槽位，不准有数字。** 文案里每个数字都是 `{slot}`，取自
   `/api/ads/context` 的真实载荷。写死数字会在数据换版后变成假话，
   而假话一旦上屏没有症状。
2. **绝不写进 `ads_agent_state.sqlite`。** 往权威结果库塞一条与真运行无法区分
   的记录，是 2026-08-31 竞品 FAKE=1 那次的错，后来要用户批准才清掉。
   这份只走一条独立路由，页面上另挂来源标注。
3. **默认不显示，点按钮才载入。** 页面不会在任何情况下自动把它当结论渲染。

槽位填不上就整条丢掉并说明原因 —— 宁可少一条，也不能把 `{kw}` 这种花括号
摆到客户面前。
"""
from __future__ import annotations

from . import proposal_schema as schema

# 页面上必须挂着它。这几句是人写的，不是 Agent 跑出来的。
SOURCE_LABEL = schema.ORIGIN_TEMPLATE
SOURCE_NOTE = (
    "这一屏的动作、原因与预期结果是人写的演示脚本，用来说明「规则确认之后」"
    "Agent 该给出什么形状的建议。句子里每个数字都取自本页上面那些真实事实接口，"
    "没有一个是编的。\n"
    "真 Agent 现在给不出这种带数值的动作，因为这个子 ASIN 的阈值状态是"
    "「未确认」——交底件规定规则未确认不输出预算、竞价与广告位数值，"
    "所以它只会停在「继续观察」。把阈值确认下来并重跑，这一屏就该由 Agent 自己写。"
)


def _num(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _slots(ctx: dict, rs: dict) -> dict:
    """从真实载荷里取槽位值。取不到就不放键，让用它的条目自己落选。"""
    s: dict = {}
    kws = ctx.get("keywords") or []
    struct = ctx.get("existing_structure") or []
    view = ctx.get("view") or {}
    facts = view.get("facts") or {}

    # 掉位最多的词：自然位数字变大就是变差
    drops = [(k, _num(k.get("organic_rank")) - _num(k.get("organic_rank_prev")))
             for k in kws
             if _num(k.get("organic_rank")) is not None
             and _num(k.get("organic_rank_prev")) is not None]
    drops = [(k, d) for k, d in drops if d > 0]
    if drops:
        k, d = max(drops, key=lambda x: x[1])
        s["losing_kw"] = k.get("keyword")
        s["losing_prev"] = int(_num(k.get("organic_rank_prev")))
        s["losing_now"] = int(_num(k.get("organic_rank")))
        s["losing_drop"] = int(d)
        s["losing_vol"] = int(_num(k.get("monthly_search")) or 0)
        sh = _num(k.get("ad_impression_share"))
        if sh is not None:
            s["losing_share"] = "%.0f%%" % (sh * 100)

    # 完全没覆盖的词：广告位与自然位都没有
    unc = [k for k in kws if not k.get("covered_by_ad")
           and _num(k.get("organic_rank")) is None]
    if unc:
        k = max(unc, key=lambda x: _num(x.get("monthly_search")) or 0)
        s["gap_kw"] = k.get("keyword")
        s["gap_vol"] = int(_num(k.get("monthly_search")) or 0)
        s["gap_match"] = k.get("match_label") or ""

    # 主力 SP 广告组：有花费的那个，动作落在它身上
    sp = [o for o in struct if (o.get("ad_type") == "SP")
          and (_num(o.get("spend")) or 0) > 0]
    if sp:
        o = max(sp, key=lambda x: _num(x.get("spend")) or 0)
        s["sp_group"] = o.get("name")
        acos, clicks, spend = (_num(o.get("acos")), _num(o.get("clicks")),
                              _num(o.get("spend")))
        if acos is not None:
            s["sp_acos"] = "%.1f%%" % (acos * 100)
        if clicks and spend is not None:
            cpc = spend / clicks
            s["sp_cpc"] = "$%.2f" % cpc
            # 目标值必须算出来，不能只说「上调 15%」——会上原话是
            # 「从 40% 上调到 50%」，从→到两个数都要有
            s["bid_to"] = "$%.2f" % (cpc * 1.15)
            s["bid_to_20"] = "$%.2f" % (cpc * 1.20)
        roas = _num(o.get("roas"))
        if roas is not None:
            s["sp_roas"] = "%.2f" % roas

    # 本品广告对象数，移出一个之后是几个 —— 监控指标要基准与目标两列
    if struct:
        s["obj_n"] = len(struct)
        s["obj_n_after"] = max(len(struct) - 1, 0)

    # 零花费但仍占着盘点范围的对象
    dead = [o for o in struct if (_num(o.get("spend")) or 0) == 0
            and (_num(o.get("clicks")) or 0) == 0]
    if dead:
        o = max(dead, key=lambda x: x.get("shared_child_count") or 1)
        s["dead_group"] = o.get("name")
        s["dead_shared"] = o.get("shared_child_count") or 1
        s["dead_type"] = o.get("ad_type") or ""

    # 已确认的效率观察线（这两个是真参数，不是编的）
    if rs.get("acos_max") is not None:
        s["acos_line"] = "%.0f%%" % (float(rs["acos_max"]) * 100)
    if rs.get("min_clicks") is not None:
        s["min_clicks"] = int(rs["min_clicks"])

    # 库存侧：清货场景要用
    inv = facts.get("inventory") or {}
    if inv.get("coverage_days") is not None:
        s["cover_days"] = "%.0f" % inv["coverage_days"]
    if inv.get("safety_breach_date"):
        s["breach_date"] = inv["safety_breach_date"]
    if inv.get("latest_order_date"):
        s["order_date"] = inv["latest_order_date"]
    if inv.get("sellable") is not None:
        s["sellable"] = "%d" % inv["sellable"]

    # 归因桶里比率不成立的那一桶（订单数超过点击数）
    for b in view.get("attribution") or []:
        if b.get("ratio_impossible"):
            s["bad_bucket"] = b.get("label")
            s["bad_orders"] = "%d" % (b.get("orders") or 0)
            s["bad_clicks"] = "%d" % (b.get("clicks") or 0)
            break
    return s


# ---------------------------------------------------------------- 脚本正文
#
# direction 只用前端已有中文映射的词（web/modules/ads/util.js 的 LOCAL_CN），
# 不发明新枚举——发明一个前端就会渲染成「待确认方向」。

SCRIPTS = {
    # 核心词守位 + 需要补货
    "B0B3LWGP36": {
        "headline": "核心词在掉位、有一个大词完全没接，同时有一个组在空占范围",
        "items": [
            {
                "seq": 1, "direction": "ADJUST", "priority": "P1",
                "ad_purpose": "守住核心词位置",
                "target": "广告组「{sp_group}」· 关键词「{losing_kw}」",
                "lever": "bid",
                "from_to": "均 CPC {sp_cpc} → 上调后约 {bid_to}",
                "from_value": "{sp_cpc}", "to_value": "{bid_to}",
                "from_label": "当前均 CPC", "to_label": "上调后",
                "delta": "上调 15%",
                "goal": "把「{losing_kw}」的广告展示份额从 {losing_share} 抬起来，"
                        "止住自然位下滑",
                "time_threshold": "D+3 首次检查，D+7 定论",
                "volume_threshold": "该词累计 {min_clicks} 次点击",
                "trigger_rule": "时间与数据量两个阈值先到先算",
                "pass_rule": "广告展示份额高于 {losing_share} 且组 ACoS 未越过 "
                             "{acos_line}，两条同时成立才算达标",
                "on_fail": "回调竞价到原值，并给运营推送一条未达标记录",
                "guard": "组 ACoS 不得越过已确认观察线 {acos_line}",
                "watch": [
                    {"metric": "「{losing_kw}」广告展示份额",
                     "baseline": "{losing_share}", "target": "高于基准"},
                    {"metric": "「{losing_kw}」自然位",
                     "baseline": "第 {losing_now}", "target": "回到第 {losing_prev} 附近"},
                    {"metric": "广告组 ACoS",
                     "baseline": "{sp_acos}", "target": "不超过 {acos_line}"},
                ],
                "reason": "「{losing_kw}」自然位从第 {losing_prev} 掉到第 "
                          "{losing_now}（掉 {losing_drop} 位），月搜索量 "
                          "{losing_vol}，而广告展示份额只有 {losing_share}——"
                          "自然位在退、广告没顶上。该组当前 ACoS {sp_acos}，"
                          "离已确认观察线 {acos_line} 还有空间，所以有加价余地",
                "risk": "顶部广告位单价最贵，ACoS 会先升后降；越过护栏就要回调",
                "needs": ["losing_kw", "losing_prev", "losing_now", "losing_drop",
                          "losing_vol", "losing_share", "sp_group", "sp_cpc",
                          "bid_to", "sp_acos", "acos_line", "min_clicks"],
            },
            {
                "seq": 2, "direction": "BUILD", "priority": "P1",
                "ad_purpose": "补上未覆盖的需求词",
                "target": "新建关键词广告组（当前无对象承接）",
                "lever": "keyword_add",
                "from_to": "无投放 → 精准匹配投放，起始竞价 {sp_cpc}",
                "from_value": "无投放", "to_value": "{sp_cpc}",
                "from_label": "当前", "to_label": "精准匹配起始竞价",
                "delta": "新增 1 个关键词",
                "goal": "让「{gap_kw}」从零覆盖变成有广告展示与点击",
                "time_threshold": "D+7 首次检查",
                "volume_threshold": "该词累计 {min_clicks} 次点击",
                "trigger_rule": "以数据量阈值为准，不到样本不下效率结论",
                "pass_rule": "该词有广告展示份额记录，且累计点击达到 "
                             "{min_clicks} 次",
                "on_fail": "样本不足则延长观察，不判定效率；连续两个窗口无展示"
                           "则暂停该词",
                "guard": "新词爬坡期 ACoS 允许高于老组，但预算封顶",
                "watch": [
                    {"metric": "「{gap_kw}」广告展示份额",
                     "baseline": "无记录", "target": "出现记录"},
                    {"metric": "「{gap_kw}」累计点击",
                     "baseline": "0", "target": "{min_clicks} 次"},
                ],
                "reason": "「{gap_kw}」月搜索量 {gap_vol}（{gap_match}），"
                          "但广告位和自然位都没有记录——这是核心词里唯一完全"
                          "没有承接的一个，流量整份让给竞品",
                "risk": "新词没有历史，前期 ACoS 会明显高于老组，属正常爬坡",
                "needs": ["gap_kw", "gap_vol", "gap_match", "sp_cpc",
                          "min_clicks"],
            },
            {
                "seq": 3, "direction": "PAUSE", "priority": "P2",
                "ad_purpose": "清掉空占盘点范围的对象",
                "target": "{dead_type} 广告组「{dead_group}」",
                "lever": "scope",
                "from_to": "在本品盘点范围内 → 移出盘点范围",
                "from_value": "{obj_n} 个对象", "to_value": "{obj_n_after} 个对象",
                "from_label": "移出前", "to_label": "移出后",
                "delta": "移出 1 个对象",
                "goal": "让本品的广告对象清单只留真在推本品的对象",
                "time_threshold": "D+3 复核一次",
                "volume_threshold": "不适用（该对象零花费零点击）",
                "trigger_rule": "只按时间阈值，没有量可等",
                "pass_rule": "本品广告对象数下降，且没有任何量随之消失",
                "on_fail": "若移出后本品有量下降，说明归因判断有误，立刻还原",
                "guard": "只移出本品盘点范围，不暂停该组本体——它可能是别的"
                         "子 ASIN 的主力",
                "watch": [
                    {"metric": "本品广告对象数",
                     "baseline": "{obj_n} 个", "target": "{obj_n_after} 个"},
                    {"metric": "本品广告花费与销售额",
                     "baseline": "移出前口径", "target": "不发生变化"},
                ],
                "reason": "这个组零花费、零点击，却跨 {dead_shared} 个子 ASIN "
                          "共享，既不贡献本品的量，又让本品的广告对象数虚高——"
                          "运营每次盘点都要多看一行没有信息的东西",
                "risk": "若该组是别的子 ASIN 的主力，只做范围剔除不要真暂停",
                "needs": ["dead_group", "dead_shared", "dead_type",
                          "obj_n", "obj_n_after"],
            },
        ],
    },
    # 清货要流量
    "B0B3M8S4CQ": {
        "headline": "货压着要清，但最大的词在掉位、还有一个高匹配词没接",
        "items": [
            {
                "seq": 1, "direction": "ADJUST", "priority": "P1",
                "ad_purpose": "清货期用流量换周转",
                "target": "广告组「{sp_group}」· 关键词「{losing_kw}」",
                "lever": "bid",
                "from_to": "均 CPC {sp_cpc} → 上调后约 {bid_to_20}",
                "from_value": "{sp_cpc}", "to_value": "{bid_to_20}",
                "from_label": "当前均 CPC", "to_label": "上调后",
                "delta": "上调 20%",
                "goal": "把覆盖天数从 {cover_days} 天压下来，"
                        "「{losing_kw}」的展示与点击同步抬升",
                "time_threshold": "D+3 首次检查，D+7 定论",
                "volume_threshold": "该词累计 {min_clicks} 次点击",
                "trigger_rule": "时间与数据量两个阈值先到先算",
                "pass_rule": "覆盖天数低于 {cover_days} 天，且该词点击上升，"
                             "两条同时成立才算达标",
                "on_fail": "回调竞价并收回放宽的效率上限，给运营推送",
                "guard": "清货期 ACoS 允许高于 {acos_line}，但必须写明放宽额度"
                         "与收回时点，清货结束立即收回",
                "watch": [
                    {"metric": "库存覆盖天数",
                     "baseline": "{cover_days} 天", "target": "低于基准"},
                    {"metric": "「{losing_kw}」广告点击",
                     "baseline": "当前水平", "target": "上升"},
                    {"metric": "广告组 ACoS",
                     "baseline": "{sp_acos}", "target": "停在放宽后的上限内"},
                ],
                "reason": "覆盖天数 {cover_days} 天、安全线突破日 {breach_date}、"
                          "最晚下单日 {order_date} 已经过去——这不是缺货是压货，"
                          "目标是加速去库存。而「{losing_kw}」月搜索量 "
                          "{losing_vol} 是本品最大的需求词，自然位却从第 "
                          "{losing_prev} 掉到第 {losing_now}，正在丢最该拿的流量",
                "risk": "清货期主动牺牲效率，放宽额度不写明会一直留着",
                "needs": ["losing_kw", "losing_prev", "losing_now", "losing_vol",
                          "sp_group", "sp_cpc", "bid_to_20", "sp_acos",
                          "acos_line", "cover_days", "breach_date",
                          "order_date", "min_clicks"],
            },
            {
                "seq": 2, "direction": "BUILD", "priority": "P2",
                "ad_purpose": "补上高匹配却没投的词",
                "target": "广告组「{sp_group}」",
                "lever": "keyword_add",
                "from_to": "无投放 → 精准匹配投放，起始竞价 {sp_cpc}",
                "from_value": "无投放", "to_value": "{sp_cpc}",
                "from_label": "当前", "to_label": "精准匹配起始竞价",
                "delta": "新增 1 个关键词",
                "goal": "清货期多开一个入口，让「{gap_kw}」产生展示与点击",
                "time_threshold": "D+7 首次检查",
                "volume_threshold": "该词累计 {min_clicks} 次点击",
                "trigger_rule": "以数据量阈值为准，不到样本不下效率结论",
                "pass_rule": "该词有展示份额记录，且累计点击达到 {min_clicks} 次",
                "on_fail": "两个窗口都到不了样本线则撤下，不下效率结论",
                "guard": "小预算封顶，不与主力词抢预算",
                "watch": [
                    {"metric": "「{gap_kw}」广告展示",
                     "baseline": "无记录", "target": "出现记录"},
                    {"metric": "「{gap_kw}」累计点击",
                     "baseline": "0", "target": "{min_clicks} 次"},
                ],
                "reason": "「{gap_kw}」月搜索量 {gap_vol}（{gap_match}），"
                          "但既无广告位也无自然位。清货期本来就要多找入口，"
                          "这个词是现成的",
                "risk": "词量不大，可能跑很久才到样本线；到不了就不下结论",
                "needs": ["gap_kw", "gap_vol", "gap_match", "sp_group",
                          "sp_cpc", "min_clicks"],
            },
            {
                "seq": 3, "direction": "PAUSE", "priority": "P2",
                "ad_purpose": "清掉空占盘点范围的对象",
                "target": "{dead_type} 广告组「{dead_group}」",
                "lever": "scope",
                "from_to": "在本品盘点范围内 → 移出盘点范围",
                "from_value": "{obj_n} 个对象", "to_value": "{obj_n_after} 个对象",
                "from_label": "移出前", "to_label": "移出后",
                "delta": "移出 1 个对象",
                "goal": "本品广告对象清单只留真在推本品的对象",
                "time_threshold": "D+3 复核一次",
                "volume_threshold": "不适用（该对象零花费零点击）",
                "trigger_rule": "只按时间阈值，没有量可等",
                "pass_rule": "本品广告对象数下降，且没有任何量随之消失",
                "on_fail": "若移出后本品有量下降，说明归因判断有误，立刻还原",
                "guard": "只移出盘点范围，不暂停该组本体",
                "watch": [
                    {"metric": "本品广告对象数",
                     "baseline": "{obj_n} 个", "target": "{obj_n_after} 个"},
                    {"metric": "本品广告花费与销售额",
                     "baseline": "移出前口径", "target": "不发生变化"},
                ],
                "reason": "零花费零点击，却跨 {dead_shared} 个子 ASIN 共享，"
                          "对本品清货没有任何贡献",
                "risk": "别的子 ASIN 可能在用，只剔范围不暂停",
                "needs": ["dead_group", "dead_shared", "dead_type",
                          "obj_n", "obj_n_after"],
            },
        ],
    },
}


def available(child_asin: str) -> bool:
    return child_asin in SCRIPTS


def build(ctx: dict, rs: dict) -> dict:
    """把脚本套上真数字，输出**标准模板形状**（proposal_schema.FIELDS）。

    槽位缺一个那条就整条落选并说明缺什么 —— 宁可少一条，
    也不能把 `{kw}` 这种花括号摆到客户面前。
    """
    asin = (ctx.get("context") or {}).get("child_asin")
    spec = SCRIPTS.get(asin)
    if not spec:
        return {"condition": "待确认", "available": False,
                "message": "这个子 ASIN 没有标准模板示例。"
                           "示例只为汇报当天挑的两个对象写过。"}
    slots = _slots(ctx, rs)
    struct = {o.get("name"): o for o in (ctx.get("existing_structure") or [])}

    items, dropped = [], []
    for it in spec["items"]:
        missing = [k for k in it["needs"] if k not in slots]
        if missing:
            dropped.append({"seq": it["seq"],
                            "why": "缺槽位：" + "、".join(missing)})
            continue

        def f(v):
            return v.format(**slots) if isinstance(v, str) else v

        try:
            filled = {
                "recommendation_id": "demo_%s_%02d" % (asin, it["seq"]),
                "priority": it["priority"],
                "direction": it["direction"],
                "ad_purpose": it["ad_purpose"],
                "target": f(it["target"]),
                "lever": it["lever"],
                "from_to": f(it["from_to"]),
                "from_value": f(it.get("from_value")),
                "to_value": f(it.get("to_value")),
                "from_label": it.get("from_label"),
                "to_label": it.get("to_label"),
                "delta": f(it["delta"]),
                "goal": f(it["goal"]),
                "time_threshold": f(it["time_threshold"]),
                "volume_threshold": f(it["volume_threshold"]),
                "trigger_rule": f(it["trigger_rule"]),
                "pass_rule": f(it["pass_rule"]),
                "on_fail": f(it["on_fail"]),
                "guard": f(it["guard"]),
                "watch": [{"metric": f(w["metric"]),
                           "baseline": f(w["baseline"]),
                           "target": f(w["target"])} for w in it["watch"]],
                "reason": f(it["reason"]),
                "risks": [f(it["risk"])],
            }
        except KeyError as err:                               # noqa: PERF203
            dropped.append({"seq": it["seq"], "why": "槽位 %s 未定义" % err})
            continue

        # 广告对象 id：能对上就带上，用于「定位对象」高亮
        oname = filled["target"]
        for name, o in struct.items():
            if name and name in oname:
                filled["ad_object_id"] = o.get("ad_object_id")
                break
        items.append(schema.normalize_template(filled))

    return {
        "condition": "正常",
        "available": True,
        "child_asin": asin,
        "source_label": SOURCE_LABEL,
        "source_note": SOURCE_NOTE,
        "headline": spec["headline"],
        "items": items,
        "dropped": dropped,
        "rule_status": (ctx.get("context") or {}).get("rule_status"),
    }
