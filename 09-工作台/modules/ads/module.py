"""广告分析模块入口。契约 8.1：外壳只读这个文件。

两页：
  ads-catalog  广告分类与数据查看（页面一，本轮只出骨架与元信息）
  ads-decision 单一子 ASIN 广告决策（页面二，已实装九板块）

页面二的形态：Agent 不自动跑。
  GET  /api/ads/context?child_asin=…   进页面就调，渲染板块 1/2/3/5，永不触发 Agent
  GET  /api/ads/run?child_asin=…       只读本地 Pi Runner 最新完成结果，四段串行返回
  POST /api/ads/decide                 运营拍板，出交接字段
  GET  /api/ads/gate                   契约门禁：依据引用是否都能解析
"""
from __future__ import annotations

import dataclasses

from core import ctx as ctx_mod, xlsx
from core import paths

from . import agent_loop
from . import agent_result, compute, data, demo_script, page1, page2
from . import proposal_schema, rules

MODULE_ID = "ads"


def handle_meta(c: ctx_mod.Ctx) -> dict:
    con = data.connect()
    try:
        cands = data.candidates(con)
        rich = [x for x in cands if x["evidence_rich"]]
        full = [x for x in cands if x["decision_versions"]]
        spine = data.spine()
        off = [x["child_asin"] for x in cands if not x["in_spine"]]
        return {
            "id": MODULE_ID,
            "as_of": paths.AS_OF,
            "condition": data.STATUS_OK,
            "scope_label": "美国站 · 男士内裤线",
            "judgment_object": "页面一：广告组 / 投放对象；"
                               "页面二：一个子 ASIN 在当前目标与证据下的广告判断",
            "dataset_version": "0.2.0 + 页面二决策扩展",
            "product_spine": "%d 子 ASIN 脊椎，本模块候选 %d 个"
                             % (len(spine), len(cands)),
            "counts": {
                "候选子 ASIN": len(cands),
                "有完整证据链": len(rich),
                "有决策版本": len(full),
            },
            "vocab": {"nature": list(data.NATURE.values()),
                      "mode": [data.MODE_FORMAL, data.MODE_CONDITIONAL,
                               data.MODE_UNABLE]},
            "params": rules.declare(c.query),
            "spine_check": {"spine_size": len(spine),
                            "off_spine": off[:5],
                            "off_spine_n": len(off)},
            "missing_labels": compute.missing_labels(),
            "unconfirmed": [
                "正式广告目的体系及每类目的的定义",
                "产品目标如何拆成广告任务",
                "不同广告目的需要观察的指标、周期与阈值",
                "绝对阈值、自身历史变化与同组偏离对应的异常规则",
                "精确预算、竞价与广告位建议的生成边界",
                "共享广告与混合目的的可归因边界",
            ],
        }
    finally:
        con.close()


def handle_candidates(c: ctx_mod.Ctx) -> dict:
    """页面二的对象选择器，按库存处境分组。"""
    con = data.connect()
    try:
        groups = compute.candidate_groups(con)
        total = sum(len(g["rows"]) for g in groups)
        return {"as_of": paths.AS_OF,
                "condition": data.STATUS_OK if total else "空结果",
                "groups": groups}
    finally:
        con.close()


def handle_context(c: ctx_mod.Ctx) -> dict:
    """Agent 的输入 = 事实层板块的渲染数据。这条永不触发 Agent。

    2026-09-04 重构：除了原来的事实，另外返回 `view` —— 页面二图表要的
    派生形状（归因分桶 / 证据里的结构化事实 / 逐日 / 效果监控 / 决策沿革）。
    放在同一个响应里而不另开路由：这些块全部由 context 已有的数据推出来，
    分两次请求只会让页面出现"一半有图一半没有"的中间态。
    """
    asin = c.q("child_asin") or (c.rest[0] if c.rest else "")
    if not asin:
        return {"condition": "空结果", "message": "未指定子 ASIN"}
    con = data.connect()
    try:
        rs = rules.resolve(c.query)
        ctx = compute.build_context(con, asin, c.q("decision_id") or None, rs)
        if ctx is None:
            # 方案 4.3 的第三态：有事实没有决策版本
            cand = next((x for x in data.candidates(con)
                         if x["child_asin"] == asin), None)
            return {
                "child_asin": asin,
                "condition": "待确认",
                "readiness": {
                    "can_run": False, "mode": data.MODE_UNABLE,
                    "blockers": ["该子 ASIN 尚无决策版本"],
                    "notes": ["只有广告花费事实与推广关系，"
                              "没有可核验的产品目标与上游证据"],
                },
                "candidate": cand,
            }
        ctx["view"] = _view_blocks(con, ctx, rs)
        return ctx
    finally:
        con.close()


def _view_blocks(con, ctx: dict, rs: dict) -> dict:
    """页面二图表要的派生块。只重排不判断，见 page2.py 顶部。"""
    struct = ctx.get("existing_structure") or []
    # 复盘的时间阈值来自建议自带的复盘窗口。建议在 Agent 输出里，
    # 这里读一次已落库的最新运行拿 B4；读不到就给空窗口，
    # 不拿默认的 D+3/D+7 顶上——那会让页面显示一个没人定过的阈值。
    props = []
    try:
        res = agent_result.latest(ctx["context"]["child_asin"],
                                 ctx["context_hash"], None,
                                 objects=_display_objects(ctx))
        props = (res.get("points") or {}).get("B4") or []
    except Exception:                                         # noqa: BLE001
        props = []
    return {
        "attribution": page2.attribution_groups(struct),
        "facts": page2.fact_blocks(ctx.get("evidence") or []),
        "pressure": page2.pressure_matrix(ctx.get("competitor") or []),
        "constraint_domains":
            page2.constraint_domains(ctx.get("constraints") or []),
        "daily": page2.daily_series(con, struct,
                                    rs.get("daily_basis")
                                    or "daily_scaled_to_month"),
        "monitor": page2.monitor(ctx.get("history") or {}, props, rs),
        "lineage": page2.lineage(ctx.get("versions") or [],
                                ctx.get("history") or {}),
        # 只报有没有，不报内容 —— 内容要点按钮才取
        # 字段中文标签由后端给，前端不抄第二份（抄一份就会漂）
        "proposal_field_labels": dict(proposal_schema.FIELDS),
        "has_demo_script": demo_script.available(
            ctx["context"].get("child_asin")),
    }


def _display_objects(ctx: dict) -> dict:
    """Agent 只写 ad_object_id，展示用的对象数据由读取层补。

    形状按前端要的来：name / campaign / ad_type / purpose /
    attribution_days / metrics{}。page 和任务面板两处都用，抽出来免得抄两份。
    """
    return {
        s["ad_object_id"]: {
            "name": s.get("name"),
            "campaign": s.get("campaign_name"),
            "ad_type": s.get("ad_type"),
            "purpose": s.get("purpose"),
            "attribution_days": s.get("attribution_days"),
            "metrics": {k: s.get(k) for k in
                        ("spend", "ad_sales", "acos", "roas",
                         "clicks", "orders", "impressions")},
        }
        for s in ctx.get("existing_structure") or [] if s.get("ad_object_id")
    }


def handle_run(c: ctx_mod.Ctx) -> dict:
    """读取本地真实 Pi Runner 的最新 completed run。

    P0 刻意不从浏览器触发 Agent：外壳当前拿不到 request body。页面仍用 GET，
    但这里只读 sidecar，不再把离线构造的决策链回放冒充成 Agent。
    """
    asin = c.q("child_asin") or (c.rest[0] if c.rest else "")
    if not asin:
        return {"condition": "空结果", "message": "未指定子 ASIN"}
    con = data.connect()
    try:
        rs = rules.resolve(c.query)
        ctx = compute.build_context(con, asin, c.q("decision_id") or None, rs)
        if ctx is None:
            return {"condition": "待确认", "message": "该子 ASIN 尚无决策版本"}
        if not ctx["readiness"]["can_run"]:
            return {"condition": "待确认",
                    "readiness": ctx["readiness"],
                    "message": "；".join(ctx["readiness"]["blockers"])}
        res = agent_result.latest(asin, ctx["context_hash"],
                                  c.q("context_hash") or None,
                                  objects=_display_objects(ctx))
        # B4 过一遍标准模板：Agent 与示例走同一个字段顺序、同一个渲染器，
        # Agent 没输出的格子显示「本次运行未给出」——缺口自己露出来，
        # 这一份同时就是给 Agent 侧的验收单。
        names = {o["ad_object_id"]: (o.get("name") or "")
                 for o in (ctx.get("existing_structure") or [])
                 if o.get("ad_object_id")}
        rows = [proposal_schema.normalize_agent(
                    it, names.get(it.get("ad_object_id")), rs)
                for it in (res.get("points") or {}).get("B4") or []]
        res["proposals"] = rows
        res["field_coverage"] = proposal_schema.field_coverage(rows)
        return res
    finally:
        con.close()


def handle_loop(c: ctx_mod.Ctx) -> dict:
    """外壳任务面板：把已落库的一次运行还原成十回合过程。

    外壳传对象用 `object`（见 shell.js 的 runTask），不是 `child_asin`，
    两个都收——面板和页面用同一个路由时不该因为参数名不同而失败。
    """
    asin = (c.q("object") or c.q("child_asin")
            or (c.rest[0] if c.rest else ""))
    if not asin:
        return {"steps": [], "run": {"status": "失败",
                                     "message": "先在页面上选一个子 ASIN"}}
    trigger = c.q("trigger") != "0"      # 状态路由会显式传 0
    con = data.connect()
    try:
        rs = rules.resolve(c.query)
        ctx = compute.build_context(con, asin, c.q("decision_id") or None, rs)
        if ctx is None:
            return {"steps": [], "run": {
                "status": "失败", "object_id": asin,
                "message": "该子 ASIN 尚无决策版本，Agent 跑不了"}}
        objects = _display_objects(ctx)
        # run 路由触发真实 Runner；poll 路由只读状态不触发
        return agent_loop.task_run(asin, ctx["context_hash"], objects,
                                   do_trigger=trigger)
    finally:
        con.close()


def handle_loop_status(c: ctx_mod.Ctx) -> dict:
    """外壳轮这个路由看进度。只读，绝不触发——不然每 1.5 秒起一个 Runner。"""
    q = dict(c.query or {})
    q["trigger"] = ["0"]
    return handle_loop(dataclasses.replace(c, query=q))


def handle_loop_a1(c: ctx_mod.Ctx) -> dict:
    """外壳任务面板：A1 广告目的标签判断的批量结果。

    A1 按广告对象跑，不按子 ASIN，所以不需要选对象。
    没跑过时步骤全「待确认」并说明要在本地执行 Runner——
    这比面板上根本没有这个入口好：运营看得见这一步存在、只是还没跑。
    """
    return agent_loop.task_run_a1()


def handle_decide(c: ctx_mod.Ctx) -> dict:
    """板块9：运营对某条建议拍板，算全交接字段。Demo 不落库。"""
    asin = c.q("child_asin")
    rec_id = c.q("recommendation_id")
    act = c.q("decision")
    ACT = {"accept": "接受", "modify": "修改后接受", "reject": "拒绝",
           "defer": "暂缓"}
    # 报错文案原来写「决定必须是接受、修改、拒绝或暂缓」，实际只收英文键，
    # 调用方照着报错传中文会一直失败。两种都收。
    if act not in ACT:
        back = {v: k for k, v in ACT.items()}
        back["修改"] = "modify"
        act = back.get(act, act)
    if act not in ACT:
        return {"condition": "失败",
                "message": "决定必须是 accept / modify / reject / defer"
                           "（也接受接受、修改、拒绝、暂缓）"}
    con = data.connect()
    try:
        rs = rules.resolve(c.query)
        res = compute.agent_stages(con, asin, c.q("decision_id") or None, rs)
        if res is None:
            return {"condition": "待确认", "message": "该子 ASIN 尚无决策版本"}
        props = {p["recommendation_id"]: p
                 for p in res["stages"][3]["items"]}
        rec = props.get(rec_id)
        if rec is None:
            return {"condition": "缺失", "message": "找不到这条建议"}
        handoff = None
        if act in ("accept", "modify"):
            handoff = {
                "子 ASIN": asin,
                "广告目的": rec["ad_purpose"],
                "原诊断": rec["diagnosis_label"],
                "广告对象": [x for x in (rec["ad_object_id"],
                                     rec["structure_gap_id"]) if x],
                "方向": rec["direction_label"],
                "观察窗口": rec["review_windows"],
                "未确认项": rec["preconditions"] + (
                    [rec["uncertainty"]] if rec["uncertainty"] else []),
                "规则版本": "未确认" if rec["exact_values_withheld"] else "已确认",
                "数据版本": "0.2.0",
            }
        return {
            "condition": data.STATUS_OK,
            "persisted": False,
            "recommendation_id": rec_id,
            "decision_label": ACT[act],
            "original": {"方向": rec["direction_label"],
                         "广告目的": rec["ad_purpose"]},
            "handoff_label": {"accept": "待执行", "modify": "待执行",
                              "reject": "已拒绝", "defer": "已暂缓"}[act],
            "handoff": handoff,
        }
    finally:
        con.close()


def handle_demo_script(c: ctx_mod.Ctx) -> dict:
    """示例调整方案（人写的演示脚本）。**只有点了按钮才会请求这条。**

    为什么有这条路由：六个决策上下文的 rule_status 全是 unconfirmed，
    交底件规定规则未确认不输出精确值，所以真 Agent 只出「继续观察 / 先补信息」，
    讲不出「把某个广告组的某项上调」。王楠 2026-09-04 授权写死用于汇报。

    它**不碰** ads_agent_state.sqlite，也不混进 run 载荷 —— 页面另挂来源标注。
    """
    asin = c.q("child_asin") or (c.rest[0] if c.rest else "")
    if not asin:
        return {"condition": "空结果", "available": False,
                "message": "未指定子 ASIN"}
    con = data.connect()
    try:
        rs = rules.resolve(c.query)
        ctx = compute.build_context(con, asin, c.q("decision_id") or None, rs)
        if ctx is None:
            return {"condition": "待确认", "available": False,
                    "message": "该子 ASIN 尚无决策版本"}
        ctx["view"] = _view_blocks(con, ctx, rs)
        return demo_script.build(ctx, rs)
    finally:
        con.close()


def handle_gate(c: ctx_mod.Ctx) -> dict:
    """依据引用可解析门禁。可以对全部有链对象跑一遍。"""
    con = data.connect()
    try:
        rs = rules.resolve(c.query)
        asin = c.q("child_asin")
        targets = ([asin] if asin else
                   [x["child_asin"] for x in data.candidates(con)
                    if x["decision_versions"]])
        out = {}
        for a in targets:
            out[a] = compute.validate_evidence_refs(con, a, None, rs)
        bad = [a for a, v in out.items() if v["status"] == "FAIL"]
        return {"condition": data.STATUS_OK if not bad else "失败",
                "checked": len(out), "failed": bad, "detail": out}
    finally:
        con.close()


FILTER_KEYS = ("ad_type", "campaign", "labels", "states", "q", "match")


def _flt(c: ctx_mod.Ctx) -> dict:
    out = {}
    for k in FILTER_KEYS:
        v = c.q(k).strip()
        if v:
            out[k] = v
    return out


def handle_catalog(c: ctx_mod.Ctx) -> dict:
    """页面一八板块一次返回。只回答数字长什么样，不出诊断与建议。"""
    con = data.connect()
    try:
        return page1.catalog_page(con, rules.resolve(c.query), _flt(c))
    finally:
        con.close()


def handle_export(c: ctx_mod.Ctx):
    """广告对象数据清单导出。粒度是广告组，不是投放对象也不是 Campaign。

    ACoS 这类比率列按小数存（0.25 而不是 "25%"）—— 存成百分号字符串
    Excel 里就没法再算了，而拿去下单的人是要接着算的。
    归因窗口按类型分（SP 7 天 / SB 与 SD 各 14 天），所以另起一页写清楚，
    否则不同类型的 ACoS 会被当成同一口径横向比较。
    """
    d = handle_catalog(c)
    rows = d.get("rows") or []
    if not rows:
        return {"message": "当前筛选没有广告对象"}

    sheets = [xlsx.from_records("广告对象数据清单", rows, [
        ("name", "广告组"),
        ("campaign", "广告活动"),
        ("ad_type", "广告类型"),
        ("purpose", "投放目的"),
        ("state_labels", "状态"),
        ("impressions", "曝光"),
        ("clicks", "点击"),
        ("orders", "订单"),
        ("spend", "花费（$）"),
        ("ad_sales", "广告销售额（$）"),
        ("ctr", "点击率"),
        ("cpc", "单次点击成本（$）"),
        ("cvr", "转化率"),
        ("acos", "ACoS"),
        ("roas", "ROAS"),
        ("acos_change_rate", "ACoS 变化率"),
        ("shared_child_count", "关联子体数"),
        ("comparable", "可比"),
        ("nature", "数据性质"),
    ], [26, 30, 10, 16, 16, 10, 8, 8, 12, 16, 9, 16, 9, 9, 9, 13, 12, 8, 10])]

    an = (d.get("anomalies") or {}).get("rows") or []
    if an:
        sheets.append(xlsx.from_records("异常对象", an, [
            ("name", "广告组"),
            ("anomalies", "命中的异常", lambda v, r: "；".join(
                (a.get("rule_name") or "") + (
                    "（" + str(a.get("detail")) + "）" if a.get("detail") else "")
                for a in (v or []))),
        ], [26, 70]))

    rules = d.get("rules") or []
    if rules:
        sheets.append(xlsx.from_records("异常判据", rules, [
            ("rule_name", "规则"), ("rule_class", "类别"),
            ("metric_name", "指标"), ("operator", "比较"),
            ("threshold", "阈值"), ("applies_to", "适用范围"),
        ], [24, 14, 18, 8, 12, 20]))

    bm = d.get("benchmark") or []
    if bm:
        sheets.append(xlsx.from_records("类目对标", bm, [
            ("category", "类目"), ("own_impressions", "自有曝光"),
            ("own_ctr", "自有点击率"), ("peer_ctr_p25", "同行 CTR P25"),
            ("peer_ctr_median", "同行 CTR 中位"), ("peer_ctr_p75", "同行 CTR P75"),
            ("own_acos", "自有 ACoS"),
        ], [20, 12, 12, 14, 14, 14, 12]))

    sheets.append({
        "name": "口径说明", "headers": ["项", "口径"], "widths": [18, 74],
        "rows": [
            ["粒度", "广告组。投放对象层已汇总到广告组，Campaign 层另算"],
            ["归因窗口", "按广告类型分：SP 7 天，SB 14 天，SD 14 天。"
                        "不同类型的 ACoS 不是同一口径，横向比较前先看这一列"],
            ["比率列", "按小数存（0.25 = 25%），不是百分号字符串，可直接参与计算"],
            ["基准日", str(c.as_of)],
            ["投放目的", "由数据包在构建期烤好，不是 Agent 现场判的；"
                        "有一部分是「无法识别」"],
        ],
    })

    name = f"广告对象数据清单-{c.as_of}.xlsx"
    return ctx_mod.Download(filename=name, data=xlsx.build(sheets))


def handle_compare(c: ctx_mod.Ctx) -> dict:
    """板块6 横向对比。跨归因周期拆多组分别排名，不合并成一张表。"""
    ids = [x for x in c.q("ids").split(",") if x]
    con = data.connect()
    try:
        rs = rules.resolve(c.query)
        uni = page1.build_universe(con, rs.get("grain") or "AD_GROUP",
                                   rs.get("daily_basis"))
        return {"condition": data.STATUS_OK, **page1.compare(uni, ids)}
    finally:
        con.close()


def handle_object(c: ctx_mod.Ctx) -> dict:
    """板块8 广告对象详情与标签历史。"""
    if not c.rest:
        return {"condition": "空结果", "message": "未指定广告对象"}
    con = data.connect()
    try:
        rs = rules.resolve(c.query)
        uni = page1.build_universe(con, rs.get("grain") or "AD_GROUP",
                                   rs.get("daily_basis"))
        d = page1.object_detail(con, uni, c.rest[0], rs)
        if d is None:
            # 换粒度再找一次：详情不该因为当前粒度不对就说找不到
            other = "TARGET" if (rs.get("grain") or "AD_GROUP") == "AD_GROUP" \
                else "AD_GROUP"
            uni2 = page1.build_universe(con, other, rs.get("daily_basis"))
            d = page1.object_detail(con, uni2, c.rest[0], rs)
        if d is None:
            return {"condition": "缺失", "message": "找不到这个广告对象"}
        return {"condition": data.STATUS_OK, **d}
    finally:
        con.close()


def invalidate():
    data.invalidate()


TASKS = [
    {
        "id": "ads-decision-loop",
        "label": "查看广告决策十回合",
        "needs": "object",
        "run": "loop",
        # 有 poll 时外壳不 await 触发那次调用，改成边跑边轮这个路由。
        # 十回合下来好几分钟，await 的话面板整段时间不动。
        "poll": "loop-status",
        "hint": "起一次真实 Pi 运行：输入桥 → 八个输出点 → 全链校验",
    },
    # A1（广告目的标签）暂不放进任务面板：Agent 侧还没有驱动 A1 的 Runner，
    # 摆在「可运行」里点下去只会挂红失败——面板里的按钮应当都是真能跑的。
    # loop-a1 路由留着，A1 的 Runner 一到位把这段解注释即可。
    # {
    #     "id": "ads-purpose-label",
    #     "label": "查看广告目的标签判断",
    #     "run": "loop-a1",
    #     "hint": "AI 建议的广告目的标签，覆盖了多少广告对象、还有多少无法识别",
    # },
]


MODULE = {
    "id": MODULE_ID,
    "label": "广告分析",
    "prefix": "ads",
    "api_version": 1,
    "pages": [
        {"id": "ads-catalog", "label": "广告分类与数据查看"},
        {"id": "ads-decision", "label": "单一子 ASIN 广告决策"},
    ],
    "routes": {
        "meta": handle_meta,
        "candidates": handle_candidates,
        "context": handle_context,
        "run": handle_run,
        "loop": handle_loop,
        "loop-status": handle_loop_status,
        "loop-a1": handle_loop_a1,
        "decide": handle_decide,
        "gate": handle_gate,
        "demo-script": handle_demo_script,
        "catalog": handle_catalog,
        "compare": handle_compare,
        "export": handle_export,
        "object": handle_object,
    },
    "tasks": TASKS,
    "params": rules.PARAMS,
    "db": paths.ADS_DB,
    "invalidate": invalidate,
}
