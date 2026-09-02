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

from core import ctx as ctx_mod
from core import paths

from . import agent_loop
from . import agent_result, compute, data, page1, rules

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
    """Agent 的输入 = 板块 1/2/3/5 的渲染数据。这条永不触发 Agent。"""
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
        return ctx
    finally:
        con.close()


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
        return agent_result.latest(asin, ctx["context_hash"],
                                   c.q("context_hash") or None,
                                   objects=_display_objects(ctx))
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
        "catalog": handle_catalog,
        "compare": handle_compare,
        "object": handle_object,
    },
    "tasks": TASKS,
    "params": rules.PARAMS,
    "db": paths.ADS_DB,
    "invalidate": invalidate,
}
