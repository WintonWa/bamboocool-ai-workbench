"""广告分析模块载荷装配：把事实拼成页面要的形状，不产判断。

判断已经在离线层做完（现阶段由决策链回放，将来换真 Agent），
这里只做三件事：
  1. 组装 Agent 的输入（context）——板块 1/2/3/5 直接渲染它
  2. 组装 Agent 的输出（四段）——板块 4/6/7/8 渲染它
  3. 算 readiness 与 context_hash：够不够跑、依据变没变

G9 / G17：所有英文枚举在 data.py 的读取边界就换成中文，
这一层只负责拼装，不再出现库里的叫法。
"""
from __future__ import annotations

import hashlib
import json

from . import data
from . import rules as _rules
from core import db as dbx
from core import paths, ruleset

STAGES = ("task", "mapping", "diagnosis", "proposal")
STAGE_LABEL = {
    "task": "应有广告任务",
    "mapping": "目标—结构—表现对照",
    "diagnosis": "广告诊断与优先级",
    "proposal": "广告调整方案",
}

# 库里的枚举 → 成品中文。映射在这里集中，页面拿不到英文（契约 G9）
TASK_TYPE_CN = {
    "VERIFY_INBOUND_BEFORE_SCALE": "先核验入库再扩量",
    "PROTECT_CORE_QUERY_VISIBILITY": "守住核心词可见性",
    "CONTROL_EFFICIENCY_DRIFT": "控制效率漂移",
    "OBSERVE_EFFICIENCY": "观察效率",
    "CLEAR_AGED_INVENTORY": "处理高库龄库存",
    "ACCELERATE_SELL_THROUGH": "加速去库存",
    "COVER_MATCHED_QUERY_GAP": "补上匹配词的覆盖缺口",
    "CLARIFY_ATTRIBUTION_BOUNDARY": "厘清归因边界",
    "MAINTAIN_CURRENT_SETUP": "维持当前配置",
}
PROBLEM_CN = {
    "INVENTORY_COVERAGE_RISK": "库存承接不足",
    "CORE_QUERY_DEFENSE": "核心词守位存在缺口",
    "ACOS_UP_VS_SELF_HISTORY": "ACoS 高于自身历史",
    "EFFICIENCY_VARIATION": "效率波动",
    "KEYWORD_COVERAGE_GAP": "关键词机会存在但覆盖不足",
    "ATTRIBUTION_UNCLEAR": "广告对象与子 ASIN 关系不清",
    "GOAL_PURPOSE_MISMATCH": "产品目标与广告目的不一致",
    "MIXED_PURPOSE_GROUP": "一个广告组混合多个目的",
    "REQUIRED_TASK_MISSING": "必要广告任务缺失",
    "DUPLICATE_TASK_OWNERS": "多个广告组重复承担同一任务",
    "PERFORMANCE_NOT_SUPPORTING": "表现不支撑已确认的目的",
    "COMPETITOR_NO_TASK": "竞品压力存在但无对应任务",
    "INSUFFICIENT_EVIDENCE": "证据或规则不足暂时无法判断",
    # 真 Agent（deepseek-v4-flash）在健康对象上实测产出，「没问题」也是结论
    "NO_ADJUSTMENT_NEEDED": "本期无需调整",
}
DIRECTION_CN = {
    "KEEP": "保持", "OBSERVE": "继续观察", "ADJUST": "调整", "PAUSE": "暂停",
    "RESUME": "恢复", "SPLIT": "拆分", "MERGE": "合并", "BUILD": "补建",
    "TEST": "低成本测试", "DEFER": "暂缓", "REQUEST_INFO": "先补信息",
    "PREREQUISITE": "前置条件", "NEW_STRUCTURE": "补建结构",
}
GOAL_TYPE_CN = {    "scale_growth": "规模增长", "position_building": "位置建立",
    "stable_operation": "稳定经营", "profit_improvement": "利润改善",
    "inventory_clearance": "库存处理",
}
RISK_CN = {
    "replenishment_gap": "需要补货", "overstock": "超量备货",
    "aged_inventory_risk": "高库龄风险", "healthy": "健康",
    "stockout": "断货",
}
# 库里这批短语是英文，页面是中文，构建期推断值翻译不改变含义
PHRASE_CN = {
    "goal confirmation": "确认产品目标",
    "goal pending confirmation": "产品目标待确认",
    "inventory verification": "核验库存",
    "inventory prerequisite": "库存为前置条件",
    "inbound receipt not yet verified": "入库尚未核实",
    "immediate available coverage is limited": "立即可售覆盖有限",
    "confirm inbound receipt": "确认入库到仓",
    "collect change log": "补录同期变更日志",
    "no confirmed single-group ACoS cap": "没有客户确认的单组 ACoS 上限",
    "scenario only": "仅演示场景",
    "efficiency drift": "效率漂移", "false attribution": "错误归因",
    "stockout": "断货", "traffic loss": "流量流失",
    "core queries": "核心搜索词", "comparable SP groups": "可比 SP 广告组",
    "BR group": "广泛匹配组",
    "库龄成本随时间叠加": "库龄成本随时间叠加",
    "处理窗口有限": "处理窗口有限",
    "效率不能为清货无上限恶化": "效率不能为清货无上限恶化",
    "无客户确认 ACoS 上限": "无客户确认 ACoS 上限",
    "无现有对象承接": "无现有对象承接",
    "需低成本测试验证": "需低成本测试验证",
    "共享归因无法拆分": "共享归因无法拆分",
    "产品目标待确认": "产品目标待确认",
    "keyword_position": "关键词位置", "acos": "ACoS", "cvr": "CVR",
    "cpc": "CPC", "spend": "花费", "ad_sales": "广告销售额",
    "available_inventory": "可售库存", "daily_sales": "日销量",
    "sellable_days": "可售天数",
}
# 未确认状态在两条链里字符串不同，都要认
PENDING_GOAL = (None, "", "scenario_only",
                "conditional_pending_operator_confirmation",
                "pending_operator_confirmation")

_MISSING: set = set()

# 缺映射时上屏用的安全兜底：按字段给一句中性中文，不摆原值。
# 真 Agent 会持续产出词表外的值（实测 deepseek 出过 MAINTAIN_CURRENT_SETUP
# 与 NO_ADJUSTMENT_NEEDED），靠人工追映射永远追不上，所以兜底必须是安全的。
_FALLBACK_CN = {
    "task_type": "未归类任务",
    "problem_type": "未归类问题",
    "direction": "待确认方向",
    "task_direction": "待确认方向",
    "coverage_status": "覆盖情况待确认",
    "attribution_limit": "归因边界待确认",
    "basis_type": "依据档位待确认",
    "basis_level": "依据档位待确认",
    "issue_type": "未归类结构问题",
    "pressure_type": "未归类竞品压力",
    "match_level": "匹配度待确认",
    "goal_type": "未归类目标",
}


def cn(table: dict, v, what: str = ""):
    """缺映射时给安全兜底并记下来，由 module.py 的 meta 暴露出去。

    退回原值等于把 `MAINTAIN_CURRENT_SETUP` 摆到客户面前（前两个模块付过学费）。
    所以缺映射时上屏走 _FALLBACK_CN，原值只进 missing_labels() 这条对账通道。
    """
    if v in (None, ""):
        return v
    if v in table:
        return table[v]
    key = what or "?"
    _MISSING.add("%s:%s" % (key, v))
    fb = _FALLBACK_CN.get(key)
    if fb:
        return fb
    # 没有专门兜底的字段：只要看起来像内部枚举就不上屏
    s = str(v)
    if s.replace("_", "").replace("-", "").isascii() and s.upper() == s:
        return "待确认"
    return v


def missing_labels() -> list:
    return sorted(_MISSING)


def phrase(v):
    return PHRASE_CN.get(v, v)


def phrases(seq):
    return [phrase(x) for x in (seq or [])]


# ------------------------------------------------------------------ context

def _readiness(ctx: dict, rs: dict) -> dict:
    ev = ctx["evidence"]
    have = {e["evidence_type"] for e in ev}
    stale = [e["evidence_id"] for e in ev if e["condition"] == "过期"]
    need = ["PRODUCT_GOAL", "AD_PERFORMANCE", "INVENTORY", "KEYWORD",
            "COMPETITOR"]
    missing = [e for e in need if e not in have]
    c = ctx["context"]
    goal_ok = c.get("goal_status") not in PENDING_GOAL
    rule_ok = c.get("rule_status") in (None, "confirmed")
    blockers = []
    if not ctx["existing_structure"]:
        blockers.append("该子 ASIN 没有可归因的广告对象")
    if "AD_PERFORMANCE" not in have:
        blockers.append("缺广告表现证据")
    if blockers:
        mode, can_run = data.MODE_UNABLE, False
    elif goal_ok and rule_ok and not missing:
        mode, can_run = data.MODE_FORMAL, True
    else:
        mode, can_run = data.MODE_CONDITIONAL, True
    notes = []
    if not goal_ok:
        notes.append("产品目标尚未由运营确认，结论只能停在条件性判断")
    if not rule_ok:
        notes.append("阈值与调整边界尚未确认，不给预算、竞价与广告位数值")
    if missing:
        notes.append("缺少部分上游证据，相关任务与诊断会标注证据不足")
    if stale:
        notes.append("有 %d 条证据已过期，判断确定程度相应降低" % len(stale))
    return {"can_run": can_run, "mode": mode, "goal_confirmed": goal_ok,
            "rule_confirmed": rule_ok, "missing_evidence_n": len(missing),
            "stale_evidence": stale, "blockers": blockers, "notes": notes,
            "stale_days_threshold": rs.get("stale_days")}


def rules_fingerprint(rs: dict | None = None) -> str:
    """规则参数指纹。阈值改了判断就该重跑，所以进 hash。

    必须拿**已解析的这一次**的参数值算，不能不带参数重算——
    那样永远是默认值的指纹，改阈值 hash 不动，页面就不知道该重跑。
    """
    try:
        if rs:
            return ruleset.fingerprint(_rules.PREFIX,
                                       {k: v for k, v in rs.items()
                                        if not k.startswith("_")})
        return _rules.fingerprint()
    except Exception:                                         # noqa: BLE001
        return "?"


def _dataset_versions() -> dict:
    """四个数据包的版本，从库路径里取版本目录名，不硬编码。

    版本级粒度足够：这些包是静态快照，同一版本内事实不会变。
    换版本必须让 hash 变，否则页面会拿旧结果配新数据。
    """
    def ver(p):
        parts = [x for x in str(p).split("/") if x]
        for x in reversed(parts):
            if x.startswith("v") and any(ch.isdigit() for ch in x):
                return x
        return parts[-2] if len(parts) > 1 else "?"
    return {
        "ads": ver(paths.ADS_DB),
        "product": ver(paths.PRODUCT_DB),
        "keyword": ver(getattr(paths, "KEYWORD_DB", "")),
        "competitor": ver(getattr(paths, "COMPETITOR_DB", "")),
        "ads_ext": _ext_version(),
    }


def _ext_version() -> str:
    try:
        con = data.connect()
        try:
            rows = dbx.rows(con, "select key, value from ext.ext_meta")
            m = {r["key"]: r["value"] for r in rows}
            return "%s+%s" % (m.get("ads_source", "?"),
                              m.get("product_source", "?"))
        finally:
            con.close()
    except Exception:                                         # noqa: BLE001
        return "?"


def context_hash(ctx: dict, rs: dict | None = None) -> str:
    """页面上下文**新鲜度**指纹，不是模型输入全文指纹。

    2026-08-31 按方案 1 重写（`00-通用方法与规范/09-广告Agent重建两侧分工.md`）：
    hash 由工作台算，Runner 从 `/api/ads/context` 原样取走、绝不自行重算；
    模型真看了什么由 Runner 写进 `evidence_index`，跟这个 hash 无关。

    **只包含**：判断对象、决策版本、运营设定的目标、数据截止、
    规则参数指纹、四个数据包版本、上游 Agent 的有效 run_id。

    **绝不包含**（否则循环依赖：Agent 的产出会改变它自己输入的指纹）：
    A1 与 B0b–B4 的任何输出、`ext_*` 预烤结论（约束 / 匹配度 / 竞品压力 /
    结构问题 / 任务 / 诊断 / 建议）、AI 建议的广告目的标签、中文展示字段。

    旧版把整套证据卡的 payload 和结构里的 purpose 都哈希进来了，
    那批 payload 里正装着预烤的投影与分级结论——等于让产出侧决定输入指纹。
    """
    c = ctx["context"]
    basis = {
        "v": 2,                       # 口径版本，改了这个函数就要加
        "child_asin": c.get("child_asin"),
        "decision_id": c.get("decision_id"),
        "goal_version": c.get("goal_version"),
        "goal_status": c.get("goal_status"),
        "data_as_of": paths.AS_OF,
        "rules": rules_fingerprint(rs),
        "datasets": _dataset_versions(),
        # 上游库存 Agent 的有效 run_id。现在按要则 §7 的本轮例外用数据包
        # 投影顶着，所以是 null；接上真上游后这里会变，hash 跟着变。
        "upstream_inventory_run_id": c.get("upstream_inventory_run_id"),
    }
    blob = json.dumps(basis, sort_keys=True, ensure_ascii=False,
                      default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def build_context(con, child_asin: str, decision_id: str | None,
                  rs: dict) -> dict | None:
    vs = data.decision_versions(con, child_asin).get(child_asin) or []
    if not vs:
        return None
    cur = next((v for v in vs if v["decision_id"] == decision_id), vs[0])
    is_ext = bool(cur.get("is_ext"))
    gv = cur.get("goal_version")
    cur = dict(cur)
    cur["goal_type_label"] = cn(GOAL_TYPE_CN, cur.get("goal_type"),
                                "goal_type")
    cur["goal_confirmed_label"] = ("已确认"
                                   if cur.get("goal_status")
                                   not in PENDING_GOAL else "待运营确认")
    ctx = {
        "context": cur,
        "versions": [{"decision_id": v["decision_id"],
                      "decision_at": v["decision_at"],
                      "product_goal": v.get("product_goal"),
                      "is_current": v["decision_id"] == cur["decision_id"]}
                     for v in vs],
        "evidence": data.evidence(con, cur["decision_id"], is_ext),
        "constraints": data.constraints(con, gv),
        "keywords": data.keywords(con, child_asin),
        "competitor": data.competitor(con, child_asin),
        "existing_structure": data.existing_structure(con, child_asin),
        "structure_issues": data.structure_issues(con, cur["decision_id"]),
        "history": data.history(con, cur["decision_id"],
                               cur.get("previous_decision_id")),
    }
    ctx["readiness"] = _readiness(ctx, rs)
    ctx["context_hash"] = context_hash(ctx, rs)
    ctx["context_id"] = "%s@%s" % (cur["decision_id"],
                                   ctx["context_hash"][:12])
    ctx["condition"] = data.STATUS_OK
    ctx["is_ext"] = is_ext
    return ctx


# -------------------------------------------------------------- agent 四段

def agent_stages(con, child_asin: str, decision_id: str | None,
                 rs: dict) -> dict | None:
    ctx = build_context(con, child_asin, decision_id, rs)
    if ctx is None:
        return None
    did = ctx["context"]["decision_id"]
    is_ext = ctx["is_ext"]

    ts = data.tasks(con, did, is_ext)
    for t in ts:
        t["task_label"] = cn(TASK_TYPE_CN, t["task_type"], "task_type")
        t["direction_label"] = cn(DIRECTION_CN, t["task_direction"],
                                  "direction")
        t["target_scope"] = phrase(t.get("target_scope"))
        t["constraints"] = phrases(t.get("constraints"))
    name = {t["task_id"]: t["task_label"] for t in ts}

    ms = data.mappings(con, [t["task_id"] for t in ts], is_ext)
    for m in ms:
        m["task_label"] = name.get(m["task_id"], m["task_id"])

    ds = data.diagnoses(con, did, is_ext)
    for d in ds:
        d["problem_label"] = cn(PROBLEM_CN, d["problem_type"],
                                "problem_type")
        d["task_label"] = name.get(d.get("task_id"), "")
    dname = {d["diagnosis_id"]: d["problem_label"] for d in ds}

    ps = data.proposals(con, did, is_ext)
    for p in ps:
        p["direction_label"] = cn(DIRECTION_CN, p["direction"], "direction")
        p["diagnosis_label"] = dname.get(p.get("diagnosis_id"), "")
        p["preconditions"] = phrases(p.get("preconditions"))
        p["risks"] = phrases(p.get("risks"))
        p["observation_metrics"] = phrases(p.get("observation_metrics"))

    cov = data.diagnosis_coverage(con, did)
    for c in cov:
        c["problem_label"] = cn(PROBLEM_CN, c["problem_type"],
                                "problem_type")

    return {
        "context_id": ctx["context_id"],
        "context_hash": ctx["context_hash"],
        "decision_id": did,
        "mode": ctx["readiness"]["mode"],
        "condition": data.STATUS_OK,
        "stage_order": list(STAGES),
        "stages": [
            {"stage": "task", "label": STAGE_LABEL["task"], "items": ts},
            {"stage": "mapping", "label": STAGE_LABEL["mapping"],
             "items": ms},
            {"stage": "diagnosis", "label": STAGE_LABEL["diagnosis"],
             "items": ds},
            {"stage": "proposal", "label": STAGE_LABEL["proposal"],
             "items": ps},
        ],
        "diagnosis_coverage": cov,
        "evidence_index": [e["evidence_id"] for e in ctx["evidence"]],
    }


def validate_evidence_refs(con, child_asin: str, decision_id: str | None,
                           rs: dict) -> dict:
    """契约门禁：Agent 输出引用的 evidence_id 必须全在 context 里。

    引用了 context 之外的 id，「点依据高亮」就会点到空，
    整个「可核验」就是假的。
    """
    ctx = build_context(con, child_asin, decision_id, rs)
    res = agent_stages(con, child_asin, decision_id, rs)
    if ctx is None or res is None:
        return {"status": "SKIP", "why": "无决策版本"}
    known = {e["evidence_id"] for e in ctx["evidence"]}
    bad = []
    for st in res["stages"]:
        for it in st["items"]:
            for eid in (it.get("evidence_ids") or []):
                if eid not in known:
                    bad.append({"stage": st["stage"], "ref": eid})
    return {"status": "PASS" if not bad else "FAIL",
            "known": len(known), "dangling": bad}


def candidate_groups(con) -> list[dict]:
    """选择器按库存处境分组——点进去看到的结论不一样，这是重点。"""
    cands = data.candidates(con)
    order = ["replenishment_gap", "aged_inventory_risk", "overstock",
             "healthy"]
    note = {
        "replenishment_gap": "库存挡在扩量前面，会出 P0 前置任务",
        "aged_inventory_risk": "库龄成本随时间叠加，处理窗口有限",
        "overstock": "货压着需要流量带走，但要盯住效率",
        "healthy": "没有高优先问题，方案只出保持",
    }
    rich = [c for c in cands if c["evidence_rich"]]
    thin = [c for c in cands if not c["evidence_rich"]
            and c["decision_versions"]]
    facts = [c for c in cands if not c["decision_versions"]]
    groups = []
    for k in order:
        rows = [c for c in rich if c["inventory_risk"] == k]
        if rows:
            groups.append({"key": k, "label": cn(RISK_CN, k, "risk"),
                           "note": note.get(k, ""), "rows": rows})
    other = [c for c in rich if c["inventory_risk"] not in order]
    if other:
        groups.append({"key": "other", "label": "其他处境", "note": "",
                       "rows": other})
    if thin:
        groups.append({"key": "thin", "label": "证据较少", "rows": thin,
                       "note": "有决策版本但缺产品阶段、销量趋势、"
                               "关键词与竞品证据，任务与诊断会更薄"})
    if facts:
        groups.append({"key": "facts", "label": "只有广告事实",
                       "rows": facts[:40],
                       "note": "有花费与推广关系，但没有产品目标与上游证据，"
                               "结论只能停在暂时无法判断",
                       "truncated": len(facts) > 40, "total": len(facts)})
    return groups
