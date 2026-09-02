"""页面一 广告分类与数据查看 —— 运行时聚合与异常识别。

页面一的红线（方案 11.2）：只回答「数字长什么样」。
不读产品目标、库存、关键词、竞品，不出诊断和调整建议。
异常只说明对象、指标、时间、比较基准和偏离程度。

三条不能破的口径：
  1. 月度权威口径与日粒度口径物理隔离，永不同行相加。
     花费可加（真实支出与归因窗无关），归因销售额不可加
     （SP 7 天、SB/SD 14 天，加起来做分母会算出不存在的合计 ACoS）。
  2. Campaign 级规则（预算打满、无效流量）按 Campaign 计一次，
     不摊到它下面的每个对象——否则会被 Target 数量放大成几百条。
  3. 环比要求前后两个半月各自有点击样本，否则不给变化率。
"""
from __future__ import annotations

import statistics

from . import data

HALF = ("2026-07-01", "2026-07-15", "2026-07-16", "2026-07-31")
EXCLUDED_DAY = "2026-07-16"   # 不计入任何一侧，让两侧各 15 天等长


def _ratios(m: dict) -> dict:
    imp, clk = m.get("impressions") or 0, m.get("clicks") or 0
    sp, od = m.get("spend") or 0, m.get("orders") or 0
    sa = m.get("ad_sales") or 0
    return {
        "ctr": (clk / imp) if imp else None,
        "cpc": (sp / clk) if clk else None,
        "cvr": (od / clk) if clk else None,
        "acos": (sp / sa) if sa else None,
        "roas": (sa / sp) if sp else None,
    }


def _zero() -> dict:
    return {k: 0 for k in data.METRICS}


def _add(dst: dict, src: dict) -> None:
    for k in data.METRICS:
        dst[k] = (dst.get(k) or 0) + (src.get(k) or 0)


def half_change(daily: list[dict], min_per_half: int) -> dict:
    """相对自身历史的环比。变化率在原值与放大值上完全相同——
    放大系数按对象按指标恒定，做比值时约掉了。"""
    if not daily:
        return {"comparable": False, "why": "无日粒度序列"}
    a, b = _zero(), _zero()
    na = nb = 0
    for r in daily:
        d = r.get("stat_date") or ""
        if d == EXCLUDED_DAY:
            continue
        if HALF[0] <= d <= HALF[1]:
            _add(a, r); na += 1
        elif HALF[2] <= d <= HALF[3]:
            _add(b, r); nb += 1
    if a["clicks"] < min_per_half or b["clicks"] < min_per_half:
        return {"comparable": False, "why": "前后半窗点击样本不足",
                "days_prev": na, "days_curr": nb}
    ra, rb = _ratios(a), _ratios(b)
    def rate(k):
        x, y = ra.get(k), rb.get(k)
        if x in (None, 0) or y is None:
            return None
        return y / x - 1
    return {"comparable": True, "days_prev": na, "days_curr": nb,
            "prev": {**a, **ra}, "curr": {**b, **rb},
            "acos_change_rate": rate("acos"),
            "cvr_change_rate": rate("cvr"),
            "cpc_change_rate": rate("cpc")}


def build_universe(con, grain: str, basis: str) -> list[dict]:
    """一次装配某个粒度的全部对象：事实 + 标签 + 状态 + 环比。"""
    objs = data.objects(con, grain)
    facts = data.month_facts(con)
    labels = data.labels_by_object(con)
    daily = data.daily_by_object(con, basis)
    promoted = data.promoted_by_object(con)
    shared = {}
    for oid, kids in promoted.items():
        shared[oid] = len(set(kids))
    # SB 组无直接事实时用其下 Target 汇总
    child_facts: dict[str, dict] = {}
    if grain == "AD_GROUP":
        for t in data.objects(con, "TARGET"):
            p = t.get("parent_ad_object_id")
            f = facts.get(t["ad_object_id"])
            if not p or not f:
                continue
            agg = child_facts.setdefault(p, _zero())
            _add(agg, f)
            agg["attribution_days"] = f.get("attribution_days")
            agg["_n"] = agg.get("_n", 0) + 1

    out = []
    for o in objs:
        oid = o["ad_object_id"]
        f = facts.get(oid)
        states = []
        if f is None:
            f = child_facts.get(oid)
            if f:
                states.append("sb_from_targets")
        if f is None:
            f = _zero()
            states.append("no_data")
        m = {k: f.get(k) for k in data.METRICS}
        r = _ratios(m)
        ds = daily.get(oid) or []
        if not ds:
            states.append("no_daily")
        elif len({x.get("stat_date") for x in ds}) < 14:
            states.append("short_daily")
        cov = {x.get("stat_date") for x in ds}
        if ds and len(cov) < 31:
            states.append("partial_window")
        elif ds:
            states.append("full_window")
        n_kid = shared.get(oid, 0)
        if n_kid > 1:
            states.append("shared_children")
        elif n_kid == 0:
            states.append("no_promoted_asin")
        labs = labels.get(oid, [])
        kinds = {x["label_value"] for x in labs
                 if x["label_type"] == "TARGET_OBJECT"}
        if len(kinds) > 1:
            states.append("mixed_targeting")
        out.append({
            "ad_object_id": oid,
            "level": o["object_level"],
            "ad_type": o["ad_type"],
            "campaign_id": o.get("campaign_id"),
            "campaign": o.get("campaign_name"),
            "name": (o.get("ad_group_name") or o.get("target_text")
                     or o.get("campaign_name")),
            "match_type": o.get("match_type"),
            "attribution_days": f.get("attribution_days"),
            **m, **r,
            "labels": labs,
            "purpose": next((x["label_value"] for x in labs
                             if x["label_type"] == "AD_PURPOSE"), None),
            "states": states,
            "state_labels": [data.STATE_CN.get(s, s) for s in states],
            "shared_child_count": n_kid,
            "history": half_change(ds, 0) if ds else {"comparable": False,
                                                      "why": "无日粒度序列"},
            "nature": data.nature(f.get("source_status")),
        })
    out.sort(key=lambda x: -(x["spend"] or 0))
    return out


def parse_labels(raw: str) -> dict:
    """把 labels 串解析成 {标签族: {取值,…}}。

    方案 3.5 的六个例子全是「跨标签族 AND、族内 OR」：
    「某个子 ASIN 下的全部 SP 广告组」是产品关系 AND 广告属性，
    「投放某个关键词或某类关键词的全部 Target」是投放对象族内 OR。
    原来把所有 token 一律 AND，同族选两个值必然 0 结果——
    一个对象不可能既是精准匹配又是广泛匹配。
    """
    out: dict[str, set] = {}
    for token in (raw or "").split("\x01"):
        if ":" not in token:
            continue
        t, v = token.split(":", 1)
        if t and v:
            out.setdefault(t, set()).add(v)
    return out


def _has_label(r: dict, t: str, vals: set) -> bool:
    return any(x["label_type"] == t and x["label_value"] in vals
               for x in r["labels"])


def apply_filters(universe: list[dict], f: dict,
                  skip_family: str = None) -> list[dict]:
    """skip_family 供分面计数用：算某一族的候选数时要先摘掉它自己的选择，
    否则勾了一个值之后同族其他值全变 0，界面就成了单选。"""
    rows = universe
    if f.get("ad_type"):
        rows = [r for r in rows if r["ad_type"] == f["ad_type"]]
    if f.get("campaign"):
        rows = [r for r in rows if r["campaign"] == f["campaign"]]
    if f.get("match"):
        want_m = set(f["match"].split("\x01"))
        rows = [r for r in rows
                if data.match_cn(r.get("match_type")) in want_m]
    q = (f.get("q") or "").strip().lower()
    if q:
        rows = [r for r in rows
                if q in (r["name"] or "").lower()
                or q in (r["campaign"] or "").lower()
                or q in (r["purpose"] or "").lower()]
    for t, vals in parse_labels(f.get("labels")).items():
        if t == skip_family:
            continue
        rows = [r for r in rows if _has_label(r, t, vals)]
    st = [x for x in (f.get("states") or "").split(",") if x]
    for s in st:
        rows = [r for r in rows if s in r["states"]]
    return rows


# 侧栏标签族的呈现顺序：当前粒度最主要的分类轴排前面
FAMILY_ORDER = {
    "AD_GROUP": ["PRODUCT_RELATION", "AD_PURPOSE", "AD_ATTRIBUTE",
                 "TARGET_OBJECT", "OPERATOR_CUSTOM"],
    "TARGET": ["TARGET_OBJECT", "AD_ATTRIBUTE", "PRODUCT_RELATION",
               "AD_PURPOSE", "OPERATOR_CUSTOM"],
}


def facets(universe: list[dict], f: dict, grain: str) -> list[dict]:
    """板块3 的可选条件，计数是「勾上它还剩几个对象」。

    每一族的计数都在「其他族的筛选已生效、本族自己的选择先摘掉」的集合上算，
    所以永远不会因为勾了一项就把同族其他项打成 0。计数为 0 的取值照样列出但
    置灰——让人看见「这个组合选不出东西」，而不是选项凭空消失。
    """
    picked = parse_labels(f.get("labels"))
    out = []

    order = FAMILY_ORDER.get(grain, FAMILY_ORDER["TARGET"])
    for t in order:
        # 本族在当前粒度下的全部取值，与筛选无关。
        # 只统计筛选后还存在的取值会让选不出的项直接消失，
        # 人就看不出「是这个组合选不出来」还是「本来就没这个分类」。
        allv = set()
        for r in universe:
            for x in r["labels"]:
                if x["label_type"] == t:
                    allv.add(x["label_value"])
        if not allv:
            continue
        base = apply_filters(universe, f, skip_family=t)
        counts: dict[str, int] = {v: 0 for v in allv}
        for r in base:
            for x in r["labels"]:
                if x["label_type"] == t and x["label_value"] in counts:
                    counts[x["label_value"]] += 1
        vals = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        out.append({
            "key": "labels", "type": t,
            "label": data.LABEL_FAMILY_CN.get(t, t),
            "values": [{"value": v, "n": n,
                        "on": v in picked.get(t, set())} for v, n in vals],
            "picked": sorted(picked.get(t, set())),
        })

    # 匹配方式只在投放对象粒度有意义：广告组层没有匹配方式这个属性
    if grain == "TARGET":
        allm = {data.match_cn(r.get("match_type")) for r in universe}
        base = apply_filters(universe, dict(f, match=""))
        mc: dict[str, int] = {k: 0 for k in allm}
        for r in base:
            k = data.match_cn(r.get("match_type"))
            mc[k] = mc.get(k, 0) + 1
        on = set((f.get("match") or "").split("\x01")) - {""}
        out.insert(1, {
            "key": "match", "type": "MATCH",
            "label": "匹配方式",
            "values": [{"value": k, "n": n, "on": k in on}
                       for k, n in sorted(mc.items(),
                                          key=lambda kv: (-kv[1], kv[0]))],
            "picked": sorted(on),
        })

    # Campaign 按方案 3.3 只作范围限定，不参与横向比较
    base = apply_filters(universe, dict(f, campaign=""))
    cc: dict[str, int] = {}
    for r in base:
        if r.get("campaign"):
            cc[r["campaign"]] = cc.get(r["campaign"], 0) + 1
    if cc:
        cur = f.get("campaign") or ""
        out.append({
            "key": "campaign", "type": "CAMPAIGN", "label": "Campaign",
            "single": True,
            "values": [{"value": k, "n": n, "on": k == cur}
                       for k, n in sorted(cc.items(),
                                          key=lambda kv: (-kv[1], kv[0]))],
            "picked": [cur] if cur else [],
        })
    return out


def aggregate(sel: list[dict]) -> dict:
    """按归因周期分块。花费可加，归因销售额不可加。"""
    blocks: dict[int, dict] = {}
    for r in sel:
        d = r.get("attribution_days") or 0
        b = blocks.setdefault(d, {"attribution_days": d, "ad_types": set(),
                                  "objects": 0, **_zero()})
        b["ad_types"].add(r["ad_type"])
        b["objects"] += 1
        _add(b, r)
    out = []
    for d in sorted(blocks, reverse=True):
        b = blocks[d]
        b["ad_types"] = sorted(b["ad_types"])
        b.update(_ratios(b))
        out.append(b)
    total_spend = sum(r.get("spend") or 0 for r in sel)
    total_clicks = sum(r.get("clicks") or 0 for r in sel)
    total_orders = sum(r.get("orders") or 0 for r in sel)
    total_imp = sum(r.get("impressions") or 0 for r in sel)
    return {
        "objects": len(sel),
        "with_data": len([r for r in sel if "no_data" not in r["states"]]),
        "spend": total_spend, "clicks": total_clicks,
        "orders": total_orders, "impressions": total_imp,
        "ctr": (total_clicks / total_imp) if total_imp else None,
        "blocks": out,
    }


def peer_medians(sel: list[dict]) -> dict:
    """同组中位数：同 (粒度, 广告类型, 归因天数) 才算一组。"""
    groups: dict[tuple, list] = {}
    for r in sel:
        if r.get("acos") is None:
            continue
        groups.setdefault((r["level"], r["ad_type"],
                           r.get("attribution_days")), []).append(r["acos"])
    return {k: {"median_acos": statistics.median(v), "n": len(v)}
            for k, v in groups.items() if len(v) >= 3}


def detect_anomalies(con, sel: list[dict], rs: dict) -> dict:
    """四类异常。Campaign 级的按 Campaign 计一次，单列。"""
    want = rs.get("classes") or "all"
    def on(cls):
        return want == "all" or want == cls
    med = peer_medians(sel)
    rules = {r["rule_id"]: r for r in data.anomaly_rules(con)}
    hits = []
    for r in sel:
        found = []
        def hit(rid, observed, threshold, basis):
            ru = rules.get(rid) or {}
            found.append({
                "rule_id": rid,
                "rule_name": ru.get("rule_name", rid),
                "class_label": ru.get("class_label", ""),
                "observed": observed, "threshold": threshold,
                "basis": basis})
        # 绝对阈值
        if on("absolute"):
            if (r.get("acos") is not None
                    and (r.get("spend") or 0) >= rs["min_spend_for_acos"]
                    and r["acos"] > rs["acos_max"]):
                hit("rule_acos_gt_050", r["acos"], rs["acos_max"],
                    "月度权威口径 ACoS 高于观察线")
            if (r.get("cpc") is not None
                    and (r.get("clicks") or 0) >= rs["min_clicks_for_ratio"]
                    and r["cpc"] > rs["cpc_max"]):
                hit("rule_cpc_gt_300", r["cpc"], rs["cpc_max"],
                    "月度权威口径 CPC 高于观察线")
        # 相对自身历史
        if on("self"):
            h = r["history"]
            if h.get("comparable"):
                ok_half = (h["prev"]["clicks"] >= rs["min_clicks_per_half"]
                           and h["curr"]["clicks"] >= rs["min_clicks_per_half"])
                ar = h.get("acos_change_rate")
                if ok_half and ar is not None and ar > rs["acos_rise_max"]:
                    hit("rule_acos_increase_gt_030", ar, rs["acos_rise_max"],
                        "后半月对前半月，两侧各 15 天等长")
                cr = h.get("cvr_change_rate")
                if ok_half and cr is not None and cr < rs["cvr_drop_max"]:
                    hit("rule_cvr_drop_gt_030", cr, rs["cvr_drop_max"],
                        "后半月对前半月，两侧各 15 天等长")
        # 相对同组偏离
        if on("peer"):
            key = (r["level"], r["ad_type"], r.get("attribution_days"))
            g = med.get(key)
            if (g and r.get("acos") is not None
                    and (r.get("spend") or 0) >= rs["min_spend_for_acos"]):
                dev = r["acos"] / g["median_acos"] - 1
                if dev > rs["acos_peer_dev_max"]:
                    hit("rule_acos_peer_dev", dev, rs["acos_peer_dev_max"],
                        "同粒度同类型同归因 %d 个对象的中位 ACoS %.1f%%"
                        % (g["n"], g["median_acos"] * 100))
        # 数据状态
        if on("state"):
            # 库里的规则 id 与状态一一对应，不自造 id
            STATE_RULE = {
                "no_data": "rule_partial_coverage",
                "short_daily": "rule_low_daily_coverage",
                "partial_window": "rule_partial_coverage",
                "no_promoted_asin": "rule_mapping_missing",
            }
            for s, rid in STATE_RULE.items():
                if s in r["states"]:
                    hit(rid, None, None, data.STATE_CN.get(s, s))
        if found:
            hits.append({"ad_object_id": r["ad_object_id"],
                         "name": r["name"], "anomalies": found})

    by_rule: dict[str, int] = {}
    for h in hits:
        for a in h["anomalies"]:
            by_rule[a["rule_name"]] = by_rule.get(a["rule_name"], 0) + 1

    # Campaign 级：按 Campaign 计一次，不摊到对象
    camp = []
    if on("absolute"):
        cids = {r["campaign_id"] for r in sel if r.get("campaign_id")}
        bud = data.budget_by_campaign(con)
        inv = data.invalid_by_campaign(con)
        names = {r["campaign_id"]: r["campaign_name"] for r in data.objects(
            con, "CAMPAIGN")}
        for cid in sorted(cids):
            b = bud.get(cid)
            if b and (b.get("time_in_budget") or 0) >= rs["budget_capped_at"]:
                camp.append({
                    "campaign_id": cid, "campaign": names.get(cid, cid),
                    "rule_id": "rule_budget_capped",
                    "rule_name": (rules.get("rule_budget_capped") or {})
                    .get("rule_name", "预算几乎打满"),
                    "class_label": "数据状态",
                    "observed": b["time_in_budget"],
                    "threshold": rs["budget_capped_at"],
                    "basis": "预算 %s，预计错失展示 %s—%s"
                             % (b.get("budget"),
                                b.get("lost_impressions_min"),
                                b.get("lost_impressions_max"))})
            v = inv.get(cid)
            if (v and (v.get("invalid_click_rate") or 0)
                    >= rs["invalid_click_rate_max"]
                    and (v.get("total_clicks") or 0)
                    >= rs["min_clicks_for_invalid"]):
                camp.append({
                    "campaign_id": cid, "campaign": names.get(cid, cid),
                    "rule_id": "rule_invalid_click_high",
                    "rule_name": (rules.get("rule_invalid_click_high") or {})
                    .get("rule_name", "无效点击率偏高"),
                    "class_label": "绝对阈值",
                    "observed": v["invalid_click_rate"],
                    "threshold": rs["invalid_click_rate_max"],
                    "basis": "无效点击占总点击"})
    return {
        "objects_hit": len(hits),
        "total": sum(len(h["anomalies"]) for h in hits),
        "by_rule": by_rule,
        "rows": hits,
        "campaign_total": len(camp),
        "campaign_rows": camp,
        "campaigns_hit": len({c["campaign_id"] for c in camp}),
        "campaigns_in_scope": len({r["campaign_id"] for r in sel
                                   if r.get("campaign_id")}),
    }


def compare(sel: list[dict], ids: list[str]) -> dict:
    """横向对比。跨归因周期不进同一张排名——方案 3.8。"""
    picked = [r for r in sel if r["ad_object_id"] in ids]
    if len(picked) < 2:
        return {"groups": [], "blockers": ["至少勾选两行才能比较"]}
    groups: dict[tuple, list] = {}
    for r in picked:
        groups.setdefault((r["level"], r.get("attribution_days")),
                          []).append(r)
    out, blockers = [], []
    if len(groups) > 1:
        blockers.append("勾选的对象跨了不同粒度或归因周期，已拆成多组"
                        "分别排名，不合并成一张表")
    for (lv, days), rows in sorted(groups.items(),
                                   key=lambda x: -(x[0][1] or 0)):
        acos = [r["acos"] for r in rows if r.get("acos") is not None]
        rows2 = sorted(rows, key=lambda r: -(r.get("spend") or 0))
        out.append({
            "level": lv, "attribution_days": days, "n": len(rows),
            "median_acos": statistics.median(acos) if len(acos) >= 1 else None,
            "rows": [{"ad_object_id": r["ad_object_id"], "name": r["name"],
                      "ad_type": r["ad_type"], "campaign": r["campaign"],
                      **{k: r.get(k) for k in data.METRICS},
                      **{k: r.get(k) for k in ("ctr", "cpc", "cvr", "acos",
                                               "roas")},
                      "acos_change_rate":
                          r["history"].get("acos_change_rate")}
                     for r in rows2],
        })
    return {"groups": out, "blockers": blockers,
            "excluded": [i for i in ids
                         if i not in {r["ad_object_id"] for r in picked}]}


def object_detail(con, universe: list[dict], oid: str, rs: dict) -> dict | None:
    r = next((x for x in universe if x["ad_object_id"] == oid), None)
    if r is None:
        return None
    cid = r.get("campaign_id")
    return {
        "ad_object_id": oid, "name": r["name"], "level": r["level"],
        "ad_type": r["ad_type"], "campaign": r["campaign"],
        "attribution_days": r["attribution_days"],
        "metrics": {k: r.get(k) for k in data.METRICS},
        "ratios": {k: r.get(k) for k in ("ctr", "cpc", "cvr", "acos", "roas")},
        "labels": r["labels"],
        "state_labels": r["state_labels"],
        "shared_child_count": r["shared_child_count"],
        "history": r["history"],
        "nature": r["nature"],
        "budget": data.budget_by_campaign(con).get(cid),
        "invalid": data.invalid_by_campaign(con).get(cid),
        "yoy": data.yoy_by_campaign(con).get(cid),
        "placements": data.placements_by_campaign(con).get(cid, []),
    }


def grain_note(con, grain: str, basis: str, sel: list[dict]) -> dict:
    """换粒度时合计会跳，先把差额算出来并说清为什么。

    广告组合计 $313,663、投放对象合计 $314,617，差 $954。这不是算错：
    两个粒度覆盖的对象集本身不同——有花费但没有对应广告组行的投放对象，
    只会出现在投放对象粒度里。界面上不说，看的人只会以为数字有问题。
    """
    other = "TARGET" if grain == "AD_GROUP" else "AD_GROUP"
    other_uni = build_universe(con, other, basis)
    here = sum(r.get("spend") or 0 for r in sel)
    there = sum(r.get("spend") or 0 for r in other_uni)
    lab = {"AD_GROUP": "广告组", "TARGET": "投放对象"}
    return {
        "other_grain_label": lab[other],
        "other_spend": there,
        "delta": here - there,
        "other_objects": len(other_uni),
        "why": f"两种粒度的合计差 {abs(here - there):,.0f} 美元。"
               f"这是对象集不同造成的：{lab[other]}粒度有 {len(other_uni)} 个对象，"
               f"{lab[grain]}粒度有 {len(sel)} 个，"
               "有花费但对不上另一层结构的对象只会出现在其中一边。"
               "两边的花费各自都是完整的，不该相加。",
    }


def active_filters(f: dict, grain: str) -> list[dict]:
    """当前生效的条件，供界面做可单独摘掉的 chip。

    方案 3.5 要求筛选结果始终说明粒度、标签条件、时间范围和对象数量，
    条件本身看不见就没法说明。chip 只带中文族名和取值，不带 query 键名。
    """
    out = []
    if f.get("q"):
        out.append({"key": "q", "family": "搜索", "value": f["q"],
                    "token": ""})
    if f.get("ad_type"):
        out.append({"key": "ad_type", "family": "广告类型",
                    "value": f["ad_type"], "token": ""})
    if f.get("campaign"):
        out.append({"key": "campaign", "family": "Campaign",
                    "value": f["campaign"], "token": ""})
    for m in (f.get("match") or "").split("\x01"):
        if m:
            out.append({"key": "match", "family": "匹配方式",
                        "value": m, "token": m})
    for t, vals in parse_labels(f.get("labels")).items():
        for v in sorted(vals):
            out.append({"key": "labels",
                        "family": data.LABEL_FAMILY_CN.get(t, t),
                        "value": v, "token": f"{t}:{v}"})
    return out


def catalog_page(con, rs: dict, flt: dict) -> dict:
    """页面一一次返回八板块要的全部载荷。"""
    grain = rs.get("grain") or "AD_GROUP"
    basis = rs.get("daily_basis") or data.DAILY_SCALED
    uni = build_universe(con, grain, basis)
    sel = apply_filters(uni, flt)
    return {
        "condition": data.STATUS_OK if sel else "空结果",
        "grain": grain,
        "grain_label": "广告组" if grain == "AD_GROUP" else "投放对象",
        "grain_note": grain_note(con, grain, basis, sel),
        "scope": data.scope_counts(con),
        "taxonomy": data.label_taxonomy(con, grain),
        "facets": facets(uni, flt, grain),
        "active": active_filters(flt, grain),
        "state_vocab": [{"key": k, "label": v}
                        for k, v in data.STATE_CN.items()],
        "aggregate": aggregate(sel),
        "benchmark": data.benchmark_ladder(con),
        "anomalies": detect_anomalies(con, sel, rs),
        "rules": data.anomaly_rules(con),
        "total": len(uni),
        "returned": len(sel),
        "rows": [{"ad_object_id": r["ad_object_id"], "name": r["name"],
                  "campaign": r["campaign"], "ad_type": r["ad_type"],
                  "purpose": r["purpose"],
                  "state_labels": r["state_labels"],
                  "shared_child_count": r["shared_child_count"],
                  "nature": r["nature"],
                  **{k: r.get(k) for k in data.METRICS},
                  **{k: r.get(k) for k in ("ctr", "cpc", "cvr", "acos",
                                           "roas")},
                  "acos_change_rate": r["history"].get("acos_change_rate"),
                  "comparable": r["history"].get("comparable")}
                 for r in sel],
    }
