"""运营总览 · 外壳唯一读的入口文件。

这一版做的是「读四个模块已经产出的结论，把今天该看什么写在一屏里」。

**总览 Agent 没有接通，所以本页的结论句子是人写死的示例文案。**
但文案里没有一个写死的数字：COPY 里全是槽位，数值一律由四个模块自己的接口填。
那是本页唯一会变成假话的地方，所以规矩是硬的 ——
取不到的槽位不猜、不补、不算第二遍，整句降级成「暂无」。

跨模块取数走 core.registry（契约 8.5「经外壳传递」）：
本文件一行都不 import modules/inventory 等等，只按模块 id 向登记表要
对方**自己声明的对外接口**，再用对方**自己的默认参数**跑一次。
所以判断口径、阈值、中文词表（风险名、优先级类型名、下一步名）全部留在
各模块手里，总览只做摘取与排版。任一模块没加载、报错或换了内部结构，
这里降级，不影响其余三张卡（契约 8.4）。

实测四个上游接口合计约 0.35 秒，所以这里不做缓存 ——
缓存了反而会在上游热重载后读到旧值。
"""

from __future__ import annotations

from collections import Counter
from string import Formatter
from typing import Any

from core import ctx as ctx_mod
from core import paths, registry, ruleset

PREFIX = "ovw"

# 结论句里「事实 —— 该怎么办」的分界。COPY 的模板用的就是这个全角破折号；
# 改模板时这两处要一起改，否则尾巴那半句不会被标出来（不会报错，只是没高亮）。
PUNCH_SEP = " —— "

# 严重度 / 承接能力 / 置信度的中文词表。
# **这三份是从库存模块前端 web/modules/inventory/util.js 的
# SEV_LABEL / CAP_LABEL / CONF_LABEL 抄过来的，是有意重复。**
# 契约 G12 禁止读兄弟模块的代码，所以不能 import；抄过来的代价是它们改词
# 这里不会跟着改，收益是总览不新造一套词。库存那边改了词，这里要跟着改。
SEV_LABEL = {"high": "高", "medium": "中", "low": "低"}
CAP_LABEL = {
    "can_absorb": "可承接", "limited": "有限承接", "cannot_absorb": "不可承接",
    "unknown": "无法判断", "unavailable": "缺库存快照",
}
CONF_LABEL = {"high": "高", "medium": "中", "low": "低"}

# 状态词 → 色调。**一处映射，四个词，全站只有这一份。**
# 「空结果」刻意不给警示色：它是预期状态，不是出了错 —— 这个区分
# handle_meta 的注释里早就写了，配色不能把它抹掉。
COND_TONE = {"正常": "good", "缺失": "warn", "待确认": "calm", "空结果": "pale"}


# 竞品关注度的中文词 → 色调。词由竞品模块给（它自己的 data.py 词表），
# 这里只做「词 → 颜色」这一层薄映射。词表外的值给中性色，不猜。
ATTENTION_TONE = {
    "优先处理": "alert", "持续关注": "warn", "留观": "calm",
    "无需处理": "good", "尚未分析": "pale",
}


def _chip(label: Any, n: Any, tone: str) -> dict:
    """一个分类徽标。数量为空就不出这一个，不显示「暂无」占位。"""
    return {"label": str(label), "n": n, "tone": tone}


def _tone(condition: Any) -> str:
    """状态词的色调。词表外的值给中性色，不猜。"""
    return COND_TONE.get(str(condition or ""), "pale")


# 结论来源标注。页面上必须挂着它 —— 这几句是人写的，不是 Agent 跑的。
# 先例：库存页用「Agent 预测 · 跑于 …」与快照回落两种标注区分来源。
SOURCE_LABEL = "示例结论 · 总览 Agent 未接入"

# 人写的结论文案。**只准有槽位，不准有数字。**
COPY = {
    "inventory": (
        "{spine} 个子体里 {risk} 个至少命中一项库存风险，{high} 个的主风险判到高严重度，"
        "{multi} 个同时压着三项以上 —— 这 {multi} 个先看。"
    ),
    "keyword": (
        "关键词侧 {total} 项优先级事项里，{to_ads} 项要转进广告决策、{to_cmp} 项要转进竞品验证，"
        "其余 {watch} 项这一周期只需继续观察。"
    ),
    "thin": (
        "竞品 {cmp_monitored} 个产品族里只有 {cmp_run} 个跑出了分析结论，"
        "广告 {ads_cand} 个候选子体里只有 {ads_evi} 个证据链完整 —— 这两处的结论覆盖最薄。"
    ),
    "card_inventory": "{top_n} 个的主风险是{top_label}，{high} 个判到高严重度；另有 {none} 个当前无风险。",
    "card_keyword": "最大的两类是{first_label} {first_n} 项、{second_label} {second_n} 项；核心词事件 {core} 条，其中显著 {sig} 条。",
    "card_competitor": "{analyzed} 个进了分析范围，{run} 个已出结论，其余 {rest} 个尚未分析。",
    "card_ads": "{groups} 个广告组里 {hit} 个命中异常，共 {total} 条；已有决策版本的子体 {decided} 个。",
    "gap_overview": "本页的结论句子是人写的示例文案，数字取自四个模块的接口",
    "gap_competitor": "{rest} 个竞品产品族还没有分析结论",
    "gap_ads": "{rest} 个候选子体的证据链还不完整",
}

NO_RISK_LABEL = "无风险"          # 主风险构成里的补集桶，风险名本身一律从库存模块取
DASH = "暂无"


# ---- 跨模块读取：只经登记表，不 import 对方 ------------------------------
def _call(mid: str, resource: str) -> Any:
    """按模块 id 调对方声明的对外接口，参数用对方自己的默认值。

    契约 8.4：对方没加载、降级、没这个接口或处理时抛异常，一律回 None，
    由调用方降级成「暂无」。总览不该因为某一个模块坏了就整页打不开。
    """
    mod = registry.get(mid)
    if mod is None or mod.degraded:
        return None
    fn = registry.resolve(mid, resource)
    if fn is None:
        return None
    values = ruleset.parse(mod.prefix, mod.params, {})
    c = ctx_mod.Ctx(
        module=mid,
        resource=resource,
        params=values,
        fingerprint=ruleset.fingerprint(mod.prefix, values),
        as_of=paths.AS_OF,
    )
    try:
        return fn(c)
    except Exception:                                       # noqa: BLE001
        return None


def _label_of(mid: str, fallback: str) -> str:
    mod = registry.get(mid)
    return mod.label if mod is not None else fallback


def _g(node: Any, *path, default=None):
    """逐层取值，任何一层不是 dict 或缺键就回 default。

    上游换了结构时要的是「这一格暂无」，不是 500。
    """
    cur = node
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return default if cur is None else cur


def _named(items: Any, key: str = "name", val: str = "n") -> dict:
    """[{name, n}, ...] -> {name: n}。上游多处用这个形状。"""
    out: dict = {}
    if isinstance(items, list):
        for it in items:
            if isinstance(it, dict) and it.get(key) is not None:
                out[str(it[key])] = it.get(val)
    return out


# ---- 四个模块各摘一份事实 -------------------------------------------------
def _inventory() -> dict:
    meta = _call("inventory", "meta")
    kids = _call("inventory", "children")
    f: dict = {"ok": False, "label": _label_of("inventory", "产品与库存")}
    if not isinstance(kids, dict) or not isinstance(kids.get("rows"), list):
        return f

    rows = kids["rows"]
    ov = kids.get("overview") or {}
    labels = _g(meta, "risk_labels", default={}) or {}

    primary = Counter(r.get("primary_risk") for r in rows)
    # 每种主风险内部的严重度分布。**这是库存模块自己的判断（primary_severity），
    # 总览只是把它原样搬过来上色，不另立一套严重度。** 逐类相加等于该类的子体数。
    sev_by = {}
    for r in rows:
        code = r.get("primary_risk")
        if code is None:
            continue
        sev_by.setdefault(code, Counter())[str(r.get("primary_severity"))] += 1

    by_type = _g(kids, "overview", "by_risk_type", default={}) or {}
    mix = []
    for code, n in primary.most_common():
        if code is None:
            continue
        c = sev_by.get(code) or Counter()
        mix.append({
            "label": labels.get(code, code),
            "n": n,
            # 高=警报、中=提示、低=中性。库存详情页对单个风险徽标用的是二分
            # （high → alert，其余 → warn）；这里是分布，低严重度染成橙色会
            # 夸大问题，所以取三分，且与下面「严重度分布」那一格用同一套。
            "parts": [
                {"label": SEV_LABEL[k], "n": c[k],
                 "tone": "alert" if k == "high" else ("warn" if k == "medium" else "pale")}
                for k in ("high", "medium", "low") if c.get(k)
            ],
            "qty": _g(by_type, code, "affected_qty"),
        })
    if primary.get(None):
        mix.append({"label": NO_RISK_LABEL, "n": primary[None], "rest": True, "parts": [], "qty": None})

    f.update(
        ok=True,
        condition=_g(kids, "condition", default="正常") if rows else "空结果",
        dataset_version=_g(meta, "data", "dataset_version", default=""),
        spine=_g(ov, "child_count", default=len(rows)),
        risk_children=_g(ov, "risk_child_count"),
        no_risk=_g(ov, "no_risk_children"),
        risk_records=_g(ov, "risk_record_count"),
        high=_g(ov, "severity", "high"),
        multi3=sum(1 for r in rows if (r.get("risk_count") or 0) >= 3),
        multi_any=_g(ov, "multi_risk_children"),
        crossing_7d=_g(meta, "data", "aging_profile", "children_crossing_180_within_7d"),
        # 三个此前没上屏的分布。中文词照库存模块自己的词表（util.js 的
        # SEV_LABEL / CAP_LABEL / CONF_LABEL），总览不新造词。
        severity=[
            {"label": SEV_LABEL[k], "n": _g(ov, "severity", k, default=0),
             "tone": "alert" if k == "high" else ("warn" if k == "medium" else "pale")}
            for k in ("high", "medium", "low")
        ],
        capacity=[
            {"label": CAP_LABEL.get(k, k), "n": v,
             "tone": "alert" if k == "cannot_absorb" else ("good" if k == "can_absorb" else "pale")}
            for k, v in (_g(ov, "capacity", default={}) or {}).items()
        ],
        confidence=[
            {"label": CONF_LABEL.get(k, k), "n": v,
             "tone": "pale" if k == "low" else "calm"}
            for k, v in (_g(ov, "confidence", default={}) or {}).items()
        ],
        mix=mix,
        # 库存是单日快照，不声明历史窗口，所以这一格放它自己的快照日期。
        window=str(_g(meta, "data", "as_of_date", default="") or DASH),
    )
    return f


def _keyword() -> dict:
    meta = _call("keyword", "meta")
    ovw = _call("keyword", "overview")
    f: dict = {"ok": False, "label": _label_of("keyword", "关键词分析")}
    if not isinstance(ovw, dict) or not isinstance(ovw.get("priority"), dict):
        return f

    pri = ovw["priority"]
    nxt = _named(pri.get("next_counts"))
    types = [
        {"label": str(it.get("name")), "n": it.get("n")}
        for it in (pri.get("type_counts") or [])
        if isinstance(it, dict) and it.get("name")
    ]
    win = _g(meta, "window", "position", default=[]) or []

    f.update(
        ok=True,
        condition=_g(ovw, "condition", default="正常"),
        dataset_version=_g(meta, "dataset_version", default=""),
        library=_g(ovw, "scope", "library_terms"),
        monitored=_g(ovw, "scope", "monitored_terms"),
        total=pri.get("total"),
        types=types,
        next_counts=[
            {"label": str(it.get("name")), "n": it.get("n")}
            for it in (pri.get("next_counts") or [])
            if isinstance(it, dict) and it.get("name")
        ],
        to_ads=nxt.get("进入广告决策处理"),
        to_cmp=nxt.get("进入竞品分析验证"),
        watch=nxt.get("继续观察一个周期"),
        core_events=_g(ovw, "core_changes", "core_events"),
        all_events=_g(ovw, "core_changes", "all_events"),
        significant=_g(ovw, "core_changes", "significant"),
        blocked=[str(x) for x in (ovw.get("blocked_reasons") or [])],
        agent_condition=_g(ovw, "agent_result", "condition", default="缺失"),
        agent_message=_g(ovw, "agent_result", "message", default=""),
        window=" ~ ".join(str(x) for x in win) if len(win) == 2 else DASH,
    )
    return f


def _competitor() -> dict:
    meta = _call("competitor", "meta")
    riv = _call("competitor", "rivals")
    f: dict = {"ok": False, "label": _label_of("competitor", "竞品分析")}
    if not isinstance(riv, dict) or not isinstance(riv.get("totals"), dict):
        return f

    t = riv["totals"]
    table = riv.get("table") or []
    # 关注程度的中文词由竞品模块给（它自己的 ATTENTION 映射），这里只统计
    attention = Counter(
        r.get("attention") for r in table if isinstance(r, dict) and r.get("attention")
    )
    win = riv.get("window") or []

    f.update(
        ok=True,
        condition=_g(riv, "condition", default="正常"),
        dataset_version=_g(meta, "dataset_version", default=""),
        monitored=t.get("monitored"),
        analyzed=t.get("analyzed"),
        with_run=t.get("with_run"),
        attention=[{"label": k, "n": v} for k, v in attention.most_common()],
        bands=[
            {"label": str(b.get("label")), "n": b.get("family_count")}
            for b in (riv.get("count_band") or [])
            if isinstance(b, dict) and b.get("label")
        ],
        headline=_g(riv, "insight", "headline", default=""),
        headline_brand=_g(riv, "insight", "brand", default=""),
        window=" ~ ".join(str(x) for x in win) if len(win) == 2 else DASH,
    )
    return f


def _ads() -> dict:
    meta = _call("ads", "meta")
    cat = _call("ads", "catalog")
    f: dict = {"ok": False, "label": _label_of("ads", "广告分析")}
    if not isinstance(meta, dict) or not isinstance(meta.get("counts"), dict):
        return f

    # 广告模块的 counts 键本身就是中文成品文案，按键取值。
    # 它改了叫法这里会取到 None -> 上屏「暂无」，不会静默填零。
    counts = meta["counts"]
    by_rule = _g(cat, "anomalies", "by_rule", default={}) or {}
    top_rules = sorted(
        ({"label": str(k), "n": v} for k, v in by_rule.items() if v),
        key=lambda x: -(x["n"] or 0),
    )[:3]

    f.update(
        ok=True,
        condition=_g(cat, "condition", default=_g(meta, "condition", default="正常")),
        dataset_version=_g(meta, "dataset_version", default=""),
        candidates=counts.get("候选子 ASIN"),
        with_evidence=counts.get("有完整证据链"),
        with_decision=counts.get("有决策版本"),
        objects=_g(cat, "aggregate", "objects"),
        grain_label=_g(cat, "grain_label", default=""),
        anomaly_objects=_g(cat, "anomalies", "objects_hit"),
        anomaly_total=_g(cat, "anomalies", "total"),
        top_rules=top_rules,
        window=DASH,
    )
    return f


# ---- 组装 ---------------------------------------------------------------
def _fill(template: str, **slots) -> str:
    """槽位缺一个就整句作废。半句真话比暂无更坏。"""
    if any(v is None or v == "" for v in slots.values()):
        return ""
    return template.format(**slots)


def _fill_parts(template: str, **slots) -> list:
    """把填好的句子拆成「文字 / 数字」两种段落，让前端能只强调数字。

    **用 string.Formatter 按真实槽位拆，不用正则找数字。**
    正则会把模板里本来就有的数字也认成填进去的值 ——
    「同时压着三项以上」的「三」、「7 天内跨 180 天库龄」的 7 和 180
    都不是数据，强调它们等于指错重点。

    「—— 」之后是这一句的结论（「这 12 个先看」），单独标出来，
    因为那半句才是要人动手的部分。第二句没有这个尾巴，就都不标。
    """
    if any(v is None or v == "" for v in slots.values()):
        return []

    parts: list = []
    for text, field, _spec, _conv in Formatter().parse(template):
        if text:
            parts.append({"t": "s", "v": text})
        if field is not None:
            v = slots[field]
            num = isinstance(v, (int, float)) and not isinstance(v, bool)
            parts.append({"t": "n" if num else "s", "v": v})

    out: list = []
    hit = False
    for p in parts:
        if not hit and p["t"] == "s" and PUNCH_SEP in str(p["v"]):
            head, tail = str(p["v"]).split(PUNCH_SEP, 1)
            if head:
                out.append({"t": "s", "v": head})
            out.append({"t": "s", "v": PUNCH_SEP, "sep": True})
            if tail:
                out.append({"t": "s", "v": tail, "punch": True})
            hit = True
            continue
        if hit:
            p = dict(p, punch=True)
        out.append(p)
    return out


def _headline(inv: dict, kw: dict, cmp_: dict, ads: dict) -> list:
    lines = []

    if inv.get("ok"):
        text = _fill(
            COPY["inventory"],
            spine=inv.get("spine"),
            risk=inv.get("risk_children"),
            high=inv.get("high"),
            multi=inv.get("multi3"),
        )
        parts = _fill_parts(
            COPY["inventory"],
            spine=inv.get("spine"),
            risk=inv.get("risk_children"),
            high=inv.get("high"),
            multi=inv.get("multi3"),
        )
        if text:
            lines.append({"text": text, "parts": parts, "module": "inventory", "module_label": inv["label"]})

    if kw.get("ok"):
        text = _fill(
            COPY["keyword"],
            total=kw.get("total"),
            to_ads=kw.get("to_ads"),
            to_cmp=kw.get("to_cmp"),
            watch=kw.get("watch"),
        )
        parts = _fill_parts(
            COPY["keyword"],
            total=kw.get("total"),
            to_ads=kw.get("to_ads"),
            to_cmp=kw.get("to_cmp"),
            watch=kw.get("watch"),
        )
        if text:
            lines.append({"text": text, "parts": parts, "module": "keyword", "module_label": kw["label"]})

    if cmp_.get("ok") and ads.get("ok"):
        text = _fill(
            COPY["thin"],
            cmp_monitored=cmp_.get("monitored"),
            cmp_run=cmp_.get("with_run"),
            ads_cand=ads.get("candidates"),
            ads_evi=ads.get("with_evidence"),
        )
        parts = _fill_parts(
            COPY["thin"],
            cmp_monitored=cmp_.get("monitored"),
            cmp_run=cmp_.get("with_run"),
            ads_cand=ads.get("candidates"),
            ads_evi=ads.get("with_evidence"),
        )
        if text:
            lines.append({"text": text, "parts": parts, "module": "competitor", "module_label": cmp_["label"]})

    return lines


def _card(mid: str, route: str, f: dict, **kw) -> dict:
    """一张结论卡。取不到数就只剩状态词与「暂无」，不填默认值。"""
    card = {
        "module": mid,
        "label": f.get("label") or mid,
        "route": route,
        "condition": f.get("condition") if f.get("ok") else "缺失",
        "dataset_version": f.get("dataset_version") or "",
        "tone": _tone(f.get("condition") if f.get("ok") else "缺失"),
        "value": None,
        "value_suffix": "",
        "value_label": "",
        "line": "",
        "detail": [],
    }
    card.update({k: v for k, v in kw.items() if v is not None})
    return card


def _kv(label: str, value: Any, unit: str = "") -> dict:
    """一条 k/v 明细。

    数字走 n + unit 让前端用 ctx.fmt.int 加千分位 —— 服务端拼成字符串的话
    「1991」永远没有千分位，而同一页别处的数字有，看上去像两套数据。
    """
    if value is None or value == "":
        return {"k": label, "v": DASH}
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return {"k": label, "n": value, "unit": unit}
    return {"k": label, "v": str(value)}


def _cards(inv: dict, kw: dict, cmp_: dict, ads: dict) -> list:
    out = []

    top = (inv.get("mix") or [{}])[0] if inv.get("ok") else {}
    out.append(_card(
        "inventory", "/inventory", inv,
        value=inv.get("risk_children"),
        value_suffix="/ {}".format(inv.get("spine")) if inv.get("spine") else "",
        value_label="至少命中一项风险的子体",
        line=_fill(
            COPY["card_inventory"],
            top_n=top.get("n"),
            top_label=top.get("label"),
            high=inv.get("high"),
            none=inv.get("no_risk"),
        ),
        chips=[c for c in (
            _chip("高严重度", inv.get("high"), "alert"),
            _chip("多风险叠加", inv.get("multi_any"), "warn"),
            _chip(NO_RISK_LABEL, inv.get("no_risk"), "good"),
        ) if c["n"] is not None],
        detail=[
            _kv("风险条数", inv.get("risk_records"), " 条"),
            _kv("命中三项以上", inv.get("multi3"), " 个"),
            _kv("7 天内跨 180 天库龄", inv.get("crossing_7d"), " 个"),
        ],
    ))

    types = kw.get("types") or []
    first = types[0] if len(types) > 0 else {}
    second = types[1] if len(types) > 1 else {}
    out.append(_card(
        "keyword", "/keyword", kw,
        value=kw.get("total"),
        value_label="待处理的优先级事项",
        line=_fill(
            COPY["card_keyword"],
            first_label=first.get("label"), first_n=first.get("n"),
            second_label=second.get("label"), second_n=second.get("n"),
            core=kw.get("core_events"), sig=kw.get("significant"),
        ),
        chips=[
            _chip(x["label"], x["n"], "pale" if str(x["label"]).startswith("继续观察") else "warn")
            for x in (kw.get("next_counts") or []) if x.get("n") is not None
        ],
        detail=[
            _kv("市场词库", kw.get("library"), " 个"),
            _kv("监控词", kw.get("monitored"), " 个"),
            _kv("覆盖与位置变化", kw.get("all_events"), " 条"),
            _kv("关键词 Agent 结果", kw.get("agent_condition")),
        ],
    ))

    rest = None
    if cmp_.get("monitored") is not None and cmp_.get("with_run") is not None:
        rest = cmp_["monitored"] - cmp_["with_run"]
    out.append(_card(
        "competitor", "/competitor", cmp_,
        value=cmp_.get("with_run"),
        value_suffix="/ {}".format(cmp_.get("monitored")) if cmp_.get("monitored") else "",
        value_label="已跑出分析结论的竞品产品族",
        line=_fill(
            COPY["card_competitor"],
            analyzed=cmp_.get("analyzed"), run=cmp_.get("with_run"), rest=rest,
        ),
        quote=cmp_.get("headline") or None,
        quote_from=cmp_.get("label") if cmp_.get("headline") else None,
        chips=[
            _chip(x.get("label"), x.get("n"), ATTENTION_TONE.get(str(x.get("label")), "pale"))
            for x in (cmp_.get("attention") or []) if x.get("n")
        ],
        detail=[_kv(b["label"], b["n"], " 族") for b in (cmp_.get("bands") or [])],
    ))

    out.append(_card(
        "ads", "/ads", ads,
        value=ads.get("with_evidence"),
        value_suffix="/ {}".format(ads.get("candidates")) if ads.get("candidates") else "",
        value_label="证据链完整的候选子体",
        line=_fill(
            COPY["card_ads"],
            groups=ads.get("objects"), hit=ads.get("anomaly_objects"),
            total=ads.get("anomaly_total"), decided=ads.get("with_decision"),
        ),
        chips=[c for c in (
            _chip("命中异常的广告组", ads.get("anomaly_objects"), "warn"),
            _chip("异常条数", ads.get("anomaly_total"), "calm"),
            _chip("已有决策版本", ads.get("with_decision"), "good"),
        ) if c["n"] is not None],
        detail=[_kv(r["label"], r["n"], " 个") for r in (ads.get("top_rules") or [])],
    ))
    return out


def _charts(inv: dict, kw: dict) -> list:
    """两张图。总览层面没有可比的历史序列，所以只画构成，不画趋势。

    深浅只用来分开相邻段落，不表达严重度 —— 严重度是库存模块的判断，
    在这里换成颜色会变成第二套说法。
    """
    out = []

    mix = inv.get("mix") or []
    if mix:
        risk_n = sum(x["n"] for x in mix if not x.get("rest") and x.get("n"))
        rest_n = sum(x["n"] for x in mix if x.get("rest") and x.get("n"))
        out.append({
            "id": "risk-mix",
            "title": "{} · {} 个子体的主风险构成".format(inv.get("label"), inv.get("spine")),
            "note": "每个子体只计它的主风险，所以各段相加等于子体总数",
            "total": inv.get("spine"),
            "unit": "个",
            "strip": {
                "label": "有风险 / 无风险",
                "segments": [
                    {"label": "至少一项风险", "n": risk_n, "tone": "ink"},
                    {"label": NO_RISK_LABEL, "n": rest_n, "tone": "pale"},
                ],
            },
            "rows": [
                {
                    "label": x["label"], "n": x["n"], "rest": bool(x.get("rest")),
                    # 段落来自库存模块的 primary_severity，逐类相加等于该类子体数
                    "parts": x.get("parts") or [], "qty": x.get("qty"),
                }
                for x in mix
            ],
            # 图例说明这几段颜色是谁的判断 —— 不写清楚就会被当成总览自己的分级
            "parts_legend": "分段是库存模块判的主风险严重度",
            "dists": [
                {"title": "严重度分布", "items": inv.get("severity") or []},
                {"title": "承接能力分布", "items": inv.get("capacity") or []},
                {"title": "预测置信度分布", "items": inv.get("confidence") or []},
            ],
        })

    types = kw.get("types") or []
    if types:
        # 「继续观察」排到最后并做浅色：深色段落 = 这一周期要转出去处理的量。
        # 这是唯一一处让深浅带含义的地方，且含义就写在图例上。
        nxt = list(kw.get("next_counts") or [])
        nxt.sort(key=lambda x: str(x["label"]).startswith("继续观察"))
        segs = []
        for i, item in enumerate(nxt):
            if str(item["label"]).startswith("继续观察"):
                tone = "pale"
            else:
                tone = "ink" if i == 0 else "mid"
            segs.append({"label": item["label"], "n": item["n"], "tone": tone})
        out.append({
            "id": "priority-mix",
            "title": "{} · {} 项优先级事项的类型构成".format(kw.get("label"), kw.get("total")),
            "note": "一项事项只属于一个类型，所以各段相加等于事项总数",
            "total": kw.get("total"),
            "unit": "项",
            "strip": {"label": "按下一步去向", "segments": segs} if segs else None,
            "rows": [{"label": x["label"], "n": x["n"], "rest": False} for x in types],
        })

    return out


def _coverage(inv: dict, kw: dict, cmp_: dict, ads: dict) -> dict:
    mods = []
    for f in (inv, kw, cmp_, ads):
        mods.append({
            "label": f.get("label") or "",
            "dataset_version": f.get("dataset_version") or DASH,
            "condition": f.get("condition") if f.get("ok") else "缺失",
            "tone": _tone(f.get("condition") if f.get("ok") else "缺失"),
            "window": f.get("window") or DASH,
        })

    gaps = [{
        "label": "总览结论",
        "condition": "缺失",
        "note": COPY["gap_overview"],
    }]

    if kw.get("ok") and kw.get("agent_condition") != "正常":
        gaps.append({
            "label": "关键词 Agent 结果",
            "condition": kw.get("agent_condition") or "缺失",
            "note": kw.get("agent_message") or "",
        })
    if cmp_.get("ok") and cmp_.get("monitored") is not None and cmp_.get("with_run") is not None:
        gaps.append({
            "label": "竞品分析结论",
            "condition": "缺失",
            "note": COPY["gap_competitor"].format(rest=cmp_["monitored"] - cmp_["with_run"]),
        })
    if ads.get("ok") and ads.get("candidates") is not None and ads.get("with_evidence") is not None:
        gaps.append({
            "label": "广告证据链",
            "condition": "缺失",
            "note": COPY["gap_ads"].format(rest=ads["candidates"] - ads["with_evidence"]),
        })
    # 受阻说明合成一条 —— 两条各占一行会在同一张表里出现两个同名标签，
    # 看的人会以为是两个不同的口径问题。
    if kw.get("blocked"):
        gaps.append({
            "label": "关键词比较口径",
            "condition": "待确认",
            "note": "；".join(kw["blocked"]),
        })

    # 缺口的色调在这里集中补，不在上面五处各写一遍 —— 少一处就会有一行没颜色
    for g in gaps:
        g["tone"] = _tone(g.get("condition"))

    return {"as_of": paths.AS_OF, "modules": mods, "gaps": gaps}


# ---- 路由 ---------------------------------------------------------------
def handle_meta(c: ctx_mod.Ctx) -> dict:
    """基准日、结论来源、上游模块是否可读。不在这里取数，取数在 digest。"""
    upstream = []
    for mid, fallback in (("inventory", "产品与库存"), ("keyword", "关键词分析"),
                          ("competitor", "竞品分析"), ("ads", "广告分析")):
        mod = registry.get(mid)
        upstream.append({
            "module": mid,
            "label": _label_of(mid, fallback),
            "condition": "正常" if (mod is not None and not mod.degraded) else "缺失",
        })
    return {
        "as_of": c.as_of,
        "fingerprint": c.fingerprint,
        "condition": "正常",
        "source_label": SOURCE_LABEL,
        "upstream": upstream,
    }


def handle_digest(c: ctx_mod.Ctx) -> dict:
    inv, kw, cmp_, ads = _inventory(), _keyword(), _competitor(), _ads()
    lines = _headline(inv, kw, cmp_, ads)
    return {
        "as_of": c.as_of,
        "condition": "正常" if lines else "空结果",
        "source_label": SOURCE_LABEL,
        "headline": {"lines": lines},
        "cards": _cards(inv, kw, cmp_, ads),
        "charts": _charts(inv, kw),
        "coverage": _coverage(inv, kw, cmp_, ads),
    }


MODULE = {
    "id": "overview",
    "label": "总览",
    "api_version": 1,
    "prefix": PREFIX,
    "pages": [{"id": "home", "label": "运营总览"}],
    "routes": {"meta": handle_meta, "digest": handle_digest},
    "db": None,                      # 自己没有库，读的全是别人已经产出的结论
}
