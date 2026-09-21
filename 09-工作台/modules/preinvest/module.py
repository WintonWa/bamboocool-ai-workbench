"""面料预投模块 · 自描述文件。

外壳只读这一个文件（core/registry.py），其余业务文件由它自己 import。

三个页面：
  pre-audit  预投考核    真实历史一轮，回答「上一轮投准了吗」  ← 默认落地页
  pre-plan   预投计划    10 月这一轮，回答「该投多少」
  pre-group  配色组详情  单个组，回答「这个数怎么来的」

为什么默认落地页是考核而不是计划：汇报对象是供应链出身的老板，
先看「现在有多不准」（他自己的考核口径 + 真实历史），再看 AI 能收窄多少。
理由写在 01-方案与数据需求/01-屏幕决策设计.md §2.1。
"""

from __future__ import annotations

import time
from typing import Any

from core import xlsx
from core.ctx import Ctx, Download

from . import compute, data, rules

STATUS_OK = "完成"
STATUS_FAIL = "失败"


def _rules(c: Ctx) -> rules.RuleSet:
    return rules.from_params(c.params)


# ---------------------------------------------------------------------------
# 读接口
# ---------------------------------------------------------------------------

def handle_meta(c: Ctx) -> dict[str, Any]:
    rs = _rules(c)
    return {
        "data": data.meta(),
        "rule_version": rs.version_label(),
        "parameters": rules.describe(rs),
        "chain": compute.chain_dates(rs),
        "window": data.target_window(rs.lead_days_total, rs.target_month_offset),
    }


def handle_plan(c: Ctx) -> dict[str, Any]:
    """342 行全给，不筛选 —— 这是一次批量审批。"""
    rs = _rules(c)
    out = compute.plan(rs)
    out["rule_version"] = rs.version_label()
    return out


def handle_child(c: Ctx) -> dict[str, Any]:
    """单个子 ASIN 的依据页。

    主体两样：
      chart      库存那张逐日图，把销售月那一段圈出来
      judgment   需求预测 Agent 的判断 —— 「为什么这么预估」
                 一句话总结 + 五项因子（状态/影响幅度/带真实数字的中文依据）
                 + 确定程度与理由。**一个字都不由这个模块编。**

    用户 2026-09-04：「库存那个单品盘点那个柱状图，我觉得它会更全，它会把
    为什么这么预估都标记起来……它就是一个 Agent 的样子。这样你下面这个
    判断这个数该不该改就不需要了呀，因为你前面已经解释清楚了。」
    所以三张证据卡与尺码拆分都已删除。
    """
    ch = c.rest[0] if c.rest else ""
    if not ch:
        return {"message": "缺少子 ASIN"}
    rs = _rules(c)
    k = data.child(ch)
    if not k:
        return {"message": f"没有子 ASIN {ch} 的数据"}

    w = data.target_window(rs.lead_days_total, rs.target_month_offset)
    f = data.forecast_by_child(w["from"], w["to"]).get(ch) or {}
    cyc = data.cycle_of_group(k["group_id"])

    return {
        "child_asin": ch,
        "identity": k,
        "rule_version": rs.version_label(),
        "window": w,
        "buffer_hint": rs.safety_margin_rate,
        "fabric_g_per_box": rs.fabric_g_per_box,
        "achieve_rate_min": rs.achieve_rate_min,
        "forecast": {
            "p50": f.get("p50"), "p10": f.get("p10"), "p90": f.get("p90"),
            "source": f.get("forecast_source"),
            "days": f.get("days"),
        },
        # 「为什么这么预估」—— Agent 的判断，没跑过就是 None，页面据此不渲染那一块
        "judgment": data.agent_judgment(ch),
        "chart": {
            "history": data.history_daily_child(ch, 120),
            "forecast": data.forecast_daily_child(ch, w["forecast_from"], w["forecast_to"]),
            "highlight_from": w["from"], "highlight_to": w["to"],
            "arrive_earliest": w["arrive_earliest"],
            "as_of": data.manifest().get("as_of"),
        },
        # 这个 ASIN 过去各月实际投了多少（逐尺码真实历史）
        "month_history": data.month_history_child(ch),
        # 上一轮达成率是配色组级的（考核口径如此）
        "group_last_cycle": ({
            "period_label": cyc["period_label"],
            "preinvest_first": cyc["pre_invest_units"],
            "added": cyc["additional_units"],
            "preinvest": cyc["pre_invest_total"],
            "order": cyc["order_total"],
            "achieve_rate": cyc["achieve_rate"],
            "passed": (cyc["achieve_rate"] or 0) >= rs.achieve_rate_min,
        } if cyc else None),
    }


def _f30(win: dict) -> float:
    """近 30 天实销。参照用 —— 吴组长举例时用的就是这个数。"""
    try:
        return float(win.get("d30") or 0) * 30
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# 导出（沿用外壳的通用下载通道，不给预投单开后门）
# ---------------------------------------------------------------------------

def handle_export_child(c: Ctx):
    """导出单个子 ASIN 的逐日预估 —— 对应库存「销量与需求」那个导出按钮。

    位置和粒度都跟库存那个一致：站在一个对象上，导它的逐日数据。
    区别只在多两列：这一天是否落在预投窗口内、以及窗口段的合计写进第二页。
    走 GET + Content-Disposition（跟库存同一条路），文件名由后端定。
    """
    ch = c.rest[0] if c.rest else ""
    if not ch:
        return {"message": "缺少子 ASIN"}
    rs = _rules(c)
    k = data.child(ch)
    if not k:
        return {"message": f"没有子 ASIN {ch} 的数据"}

    w = data.target_window(rs.lead_days_total, rs.target_month_offset)
    hist = data.history_daily_child(ch, 120)
    fdaily = data.forecast_daily_child(ch, w["forecast_from"], w["forecast_to"])

    rows = []
    for d, u in zip(hist["dates"], hist["units"]):
        rows.append([_d(d), "已发生", u, None, None, None, ""])
    for i2, d in enumerate(fdaily["dates"]):
        inwin = w["from"] <= d <= w["to"]
        rows.append([
            _d(d), "预估", None,
            fdaily["p50"][i2] if i2 < len(fdaily["p50"]) else None,
            fdaily["p10"][i2] if i2 < len(fdaily["p10"]) else None,
            fdaily["p90"][i2] if i2 < len(fdaily["p90"]) else None,
            "是" if inwin else "",
        ])

    sheets = [{
        "name": "逐日",
        "headers": ["日期", "数据性质", "实际销量（盒）", "预估 P50",
                    "预估 P10", "预估 P90", "在预投窗口内"],
        "rows": rows,
        "widths": [12, 10, 14, 11, 11, 11, 13],
    }]

    # 第二页：这个对象的预投口径与判断依据。导出的人要能脱离页面看懂那个数。
    f = data.forecast_by_child(w["from"], w["to"]).get(ch) or {}
    j = data.agent_judgment(ch)
    info_rows = [
        ["子 ASIN", ch], ["尺码", k["size"]],
        ["款号 · 组合", f'{k["style_no"]} · {k["combination"]}'],
        ["配色", k["colorway"]], ["品类", k["category"]],
        ["运营", k["operator"]], ["生命周期", k["product_lifecycle"]],
        ["单包条数", k["pack_size"]],
        ["预投对应销售月", f'{w["month"]}（M+{w["months_ahead"]}）'],
        ["销售月区间", f'{w["from"]} ~ {w["to"]}'],
        ["这批最早到货", w["arrive_earliest"]],
        ["销售月预估销量（盒）", f.get("p50")],
        ["预估区间", f'{f.get("p10")} ~ {f.get("p90")}'],
        ["预估来源", "需求预测 Agent 判断" if f.get("forecast_source") == "agent"
                     else "数据包脚手架"],
    ]
    if j:
        info_rows += [["", ""], ["判断总结", j.get("judgment_summary")],
                      ["确定程度", j.get("confidence")],
                      ["确定程度理由", j.get("confidence_reason")],
                      ["模型", j.get("model_version")], ["", ""]]
        for fac in (j.get("factors") or []):
            info_rows.append([fac["factor_label"],
                              f'{fac.get("state") or ""}　'
                              f'{"" if fac.get("impact_pct") in (None, "") else fac["impact_pct"]}　'
                              f'{fac.get("because") or ""}'])
    sheets.append({"name": "预投口径与判断依据",
                   "headers": ["项", "值"], "rows": info_rows, "widths": [22, 96]})

    name = f"{ch}-逐日预估与预投窗口-{data.manifest().get('as_of')}.xlsx"
    return Download(filename=name, data=xlsx.build(sheets))


def _d(s: str):
    """日期字符串转 date，转不了就原样 —— xlsx 写入器按类型决定格式。"""
    import datetime as _dt
    try:
        return _dt.date.fromisoformat(s)
    except (TypeError, ValueError):
        return s


def handle_export_plan(c: Ctx):
    """导出运营要交给生产端的那份预投表 —— 一行一个子 ASIN。

    buffer 与运营改后的量都由请求带进来（POST body）：页面上 buffer 是运营填的，
    后端不自己乘。「系统建议」与「运营最终」分两列不并 —— 并了拿文件的人分不清
    哪个数是人定的。
    """
    rs = _rules(c)
    p = compute.plan(rs)
    body_json = c.json() if c.body else {}
    buf = body_json.get("buffer")
    try:
        buf = float(buf)
    except (TypeError, ValueError):
        buf = rs.safety_margin_rate
    raw = body_json.get("overrides")
    overrides: dict[str, int] = {}
    if isinstance(raw, dict):
        for k2, v in raw.items():
            try:
                n = int(round(float(v)))
            except (TypeError, ValueError):
                continue
            if n >= 0:
                overrides[str(k2)] = n

    w = p["window"]
    hdr = ["子ASIN", "父ASIN", "款号", "组合", "尺码", "配色", "品类", "运营",
           "生命周期", "货品状态", "单包条数",
           f"{w['month']} 预估销量（盒）", "预估下界", "预估上界", "预估来源",
           f"Buffer（{buf:.0%}）", "系统建议预投（盒）", "运营最终（盒）", "人工调整（盒）",
           "折条数", "折面料（吨）", "所属配色组上轮达成率"]
    body = []
    for r in p["rows"]:
        p50 = r["forecast_p50"]
        sug = None if p50 is None else int(round(p50 * (1 + buf)))
        ov = overrides.get(r["child_asin"])
        final = ov if ov is not None else sug
        fab = compute.to_fabric(final or 0, r["pack_size"], rs)
        body.append([
            r["child_asin"], r["parent_asin"], r["style_no"], r["combination"],
            r["size"], r["colorway"], r["category"], r["operator"],
            r["lifecycle"], r["goods_status"], r["pack_size"],
            p50, r["forecast_p10"], r["forecast_p90"], r["forecast_source_label"],
            round(buf, 4), sug, final,
            (final - sug) if (ov is not None and sug is not None) else None,
            fab["tiao"], fab["tons"],
            (round(r["group_last_achieve"], 4)
             if r["group_last_achieve"] is not None else None),
        ])
    tot_sug = sum(x[16] or 0 for x in body)
    tot_fin = sum(x[17] or 0 for x in body)
    body.append(["合计", "", "", "", "", "", "", "", "", "", "",
                 p["forecast_p50_total"], "", "", "", "", tot_sug, tot_fin,
                 tot_fin - tot_sug, "", "", ""])

    sheets = [{
        "name": f"{w['month']} 预投表",
        "headers": hdr, "rows": body,
        "widths": [13, 13, 13, 7, 7, 26, 12, 9, 10, 10, 9,
                   18, 10, 10, 12, 12, 17, 15, 14, 10, 12, 20],
    }]
    name = f"面料预投表-{w['month']}-{data.manifest().get('as_of')}.xlsx"
    return Download(filename=name, data=xlsx.build(sheets))


MODULE = {
    "id": "preinvest",
    "label": "面料预投",
    "api_version": 1,
    # 显式写。不写外壳默认取 mid[:3] = "pre"，恰好也对，但关键词模块
    # 就是因为默认取到 key 而不是 kw 才出的问题，别赌这个。
    "prefix": "pre",
    "pages": [
        {"id": "pre-plan", "label": "预投表"},
        {"id": "pre-detail", "label": "单品依据"},
    ],
    "routes": {
        "meta": handle_meta,
        "plan": handle_plan,
        "child": handle_child,
        "export-plan": handle_export_plan,
        "export-child": handle_export_child,
    },
    "params": rules.PARAMS,
    "db": data.DB_PATH,
    "invalidate": data.clear_caches,
}
