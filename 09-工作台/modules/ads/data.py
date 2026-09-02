"""广告分析模块数据层：只读事实，不产判断。

契约要点落在这里：
  6.1 只读 URI 打开，路径从 core/paths.py 取，不写死绝对路径
  6.3 不重建 dim_product_child / dim_product_parent，要产品身份就 ATTACH 产品包
  6.4 value_origin 只内部对账，出口前映射成 6.6 的中文词表再上屏
  G8  引用的子体键 100% 命中 342 脊椎——所以候选池按脊椎过滤，
      广告包自建的 521 子体维度不当身份来源用

三个库：
  ads   广告包 v0.2.0（月度事实、标签、推广关系、B088WF1PRW 那条老链）
  ext   页面二决策扩展库（五个演示对象的证据层与决策链）
  prod  产品包 v0.3.0（342 脊椎、生命周期、销量窗口、库存判定、促销与到货）
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from core import db as dbx
from core import paths

DB_PATH = paths.ADS_DB

# 扩展库还没进 core/paths.py（契约 §11 禁止模块改 core/）。
# 从 REBUILD_ROOT 派生并留环境变量口子，等外壳侧把它加进 paths.py 再切过去。
_EXT_DEFAULT = (paths.REBUILD_ROOT
                / "04-广告分析模块/02-数据构建/page2-ext/page2_decision_ext.sqlite")
EXT_DB = Path(os.environ.get("WORKBENCH_ADS_EXT_DB") or _EXT_DEFAULT)

# 6.6 数据性质词表：value_origin 在读取边界就换成中文，页面拿不到英文枚举
NATURE = {"direct": "真实", "derived": "推导", "constructed": "模拟",
          "mixed": "混合"}
STATUS_OK = "正常"

# 判断档位（方案 4.3 的三态）
MODE_FORMAL, MODE_CONDITIONAL, MODE_UNABLE = "正式判断", "条件性判断", "暂时无法判断"

# 证据类型 → 落在哪个板块
EVIDENCE_BOARD = {
    "PRODUCT_GOAL": "goal", "PRODUCT_STAGE": "goal", "SALES_TREND": "goal",
    "INVENTORY": "goal", "BUSINESS_EVENT": "goal",
    "KEYWORD": "market", "COMPETITOR": "market",
    "AD_PERFORMANCE": "ads", "AD_PLACEMENT": "ads",
    "ATTRIBUTION_GAP": "ads", "CATEGORY_BENCHMARK": "ads",
    "HISTORY_ACTION": "history",
}

PROMO_ROLES = ("promoted_asin", "positive_spend_asin", "target_asin",
               "matched_asin")


def connect():
    """打开广告包并挂上扩展库与产品包。挂不上不致命，只是证据变薄。"""
    con = dbx.connect(DB_PATH)
    if EXT_DB.is_file():
        dbx.attach(con, EXT_DB, "ext")
    if Path(paths.PRODUCT_DB).is_file():
        dbx.attach(con, paths.PRODUCT_DB, "prod")
    return con


def _aliases(con) -> set:
    return {r[1] for r in con.execute("pragma database_list")}


def nature(origin: str | None) -> str:
    return NATURE.get(origin or "", NATURE["constructed"])


def jload(v: Any, fallback: Any = None) -> Any:
    if v is None:
        return fallback
    if isinstance(v, (list, dict)):
        return v
    try:
        return json.loads(v)
    except (TypeError, ValueError):
        return v


@lru_cache(maxsize=1)
def spine() -> frozenset:
    """342 子 ASIN 脊椎。G8 要求引用的子体键全部命中它。"""
    return frozenset(dbx.spine_children(paths.PRODUCT_DB))


def invalidate() -> None:
    spine.cache_clear()


# ------------------------------------------------------------ 决策版本

def decision_versions(con, child_asin: str | None = None) -> dict:
    """按子 ASIN 归集决策版本，新的在前。两个来源不重叠。"""
    out: dict[str, list[dict]] = {}
    al = _aliases(con)
    if "ext" in al:
        where = " where c.child_asin=?" if child_asin else ""
        args = (child_asin,) if child_asin else ()
        for r in dbx.rows(con,
                          "select c.decision_id, c.child_asin, c.parent_asin,"
                          " c.goal_version, c.decision_at,"
                          " c.previous_decision_id, c.observe_window_start,"
                          " c.observe_window_end, c.data_as_of, c.rule_status,"
                          " c.purpose_confirmed_n, c.purpose_pending_n,"
                          " c.scenario, c.value_origin,"
                          " g.goal_type, g.goal_label, g.goal_status,"
                          " g.rationale as goal_rationale, 1 as is_ext"
                          " from ext.ext_decision_context c"
                          " left join ext.ext_product_goal g"
                          "   on g.goal_version=c.goal_version"
                          + where + " order by c.decision_at desc", args):
            r["product_goal"] = r.pop("goal_label")
            r["nature"] = nature(r.pop("value_origin"))
            out.setdefault(r["child_asin"], []).append(r)
    where = " where child_asin=?" if child_asin else ""
    args = (child_asin,) if child_asin else ()
    for r in dbx.rows(con,
                      "select decision_id, child_asin, parent_asin,"
                      " product_goal_version as goal_version, product_goal,"
                      " goal_status, decision_at, previous_decision_id,"
                      " source_status, 0 as is_ext"
                      " from fact_decision_context" + where
                      + " order by decision_at desc", args):
        r["nature"] = nature(r.pop("source_status"))
        r["goal_type"] = None
        r["rule_status"] = "unconfirmed"
        out.setdefault(r["child_asin"], []).append(r)
    return out


def candidates(con) -> list[dict]:
    """页面二能选哪些子 ASIN。

    只出脊椎内的子体（G8）：广告包 521 子体里与 342 脊椎的交集，
    跨模块判断必须走同一套产品身份。
    """
    sp = spine()
    ver = decision_versions(con)
    spend = {r["child_asin"]: r["spend"] for r in dbx.rows(
        con, "select child_asin, sum(spend) spend from fact_product_ad_spend"
             " where child_asin is not null group by child_asin")}
    ident = {r["child_asin"]: r for r in dbx.rows(
        con, "select child_asin, parent_asin, product_lifecycle, style_name,"
             " category_rank from prod.dim_product_child")
        } if "prod" in _aliases(con) else {}
    risk = {r["child_asin"]: r for r in dbx.rows(
        con, "select child_asin, base_risk_status, safety_breach_date,"
             " stress_stockout_date from prod.fact_child_inventory_decision")
        } if "prod" in _aliases(con) else {}
    out = []
    for asin in sorted(sp | set(ver)):
        vs = ver.get(asin) or []
        cur = vs[0] if vs else {}
        pid = ident.get(asin) or {}
        rk = risk.get(asin) or {}
        in_spine = asin in sp
        out.append({
            "child_asin": asin,
            "parent_asin": cur.get("parent_asin") or pid.get("parent_asin"),
            "lifecycle": pid.get("product_lifecycle"),
            "style_no": pid.get("style_name"),
            "spend": spend.get(asin),
            "decision_versions": len(vs),
            "latest_decision_at": cur.get("decision_at"),
            "product_goal": cur.get("product_goal"),
            "inventory_risk": rk.get("base_risk_status"),
            "evidence_rich": bool(cur.get("is_ext")),
            "in_spine": in_spine,
            "condition": (STATUS_OK if vs else "待确认"),
            "mode": (MODE_CONDITIONAL if vs else MODE_UNABLE),
        })
    out.sort(key=lambda x: (not x["evidence_rich"],
                            -(x["decision_versions"] or 0),
                            -(x["spend"] or 0)))
    return out


# ------------------------------------------------------------ 证据与结构

def evidence(con, decision_id: str, is_ext: bool) -> list[dict]:
    if is_ext:
        rows = dbx.rows(con,
                        "select evidence_id, evidence_type, evidence_title,"
                        " evidence_payload, observed_at, valid_as_of,"
                        " evidence_nature, evidence_status, caveat, jump_to,"
                        " value_origin from ext.ext_decision_evidence"
                        " where decision_id=?"
                        " order by evidence_type, evidence_id", (decision_id,))
    else:
        rows = dbx.rows(con,
                        "select evidence_id, evidence_type, evidence_title,"
                        " evidence_payload, observed_at, valid_as_of,"
                        " evidence_nature, evidence_status, caveat,"
                        " source_status as value_origin, null as jump_to"
                        " from fact_decision_evidence where decision_id=?"
                        " order by evidence_type, evidence_id", (decision_id,))
    out = []
    for r in rows:
        r["payload"] = jload(r.pop("evidence_payload"), {})
        r["board"] = EVIDENCE_BOARD.get(r["evidence_type"], "other")
        r["nature"] = nature(r.pop("value_origin"))
        # 观察到的事实 / 系统推导 / 运营已确认（方案 6.2 要求三者分开）
        r["kind"] = {"fact": "观察到的事实", "inference": "系统推导",
                     "confirmed": "运营已确认"}.get(
                         r.pop("evidence_nature"), "观察到的事实")
        r["condition"] = ("过期" if r.pop("evidence_status") != "current"
                          else STATUS_OK)
        out.append(r)
    return out


def constraints(con, goal_version: str) -> list[dict]:
    if "ext" not in _aliases(con) or not goal_version:
        return []
    out = dbx.rows(con,
                   "select constraint_id, kind, domain, label, detail,"
                   " is_satisfied, evidence_ref, value_origin"
                   " from ext.ext_goal_constraint where goal_version=?"
                   " order by case kind when 'hard' then 0 else 1 end,"
                   " constraint_id", (goal_version,))
    for r in out:
        r["kind_label"] = "硬性条件" if r["kind"] == "hard" else "需要持续观察"
        r["nature"] = nature(r.pop("value_origin"))
    return out


def keywords(con, child_asin: str) -> list[dict]:
    if "ext" not in _aliases(con):
        return []
    out = dbx.rows(con,
                   "select p.kw_id, p.keyword, p.monthly_search,"
                   " p.organic_rank, p.organic_rank_prev, p.ad_rank,"
                   " p.ad_impression_share, p.covered_by_ad,"
                   " p.position_trend, p.limited_by, p.observed_at,"
                   " p.value_origin, m.match_level, m.demand_side,"
                   " m.product_side, m.basis from ext.ext_keyword_position p"
                   " left join ext.ext_keyword_match m on m.kw_id=p.kw_id"
                   " where p.child_asin=? order by p.monthly_search desc",
                   (child_asin,))
    TREND = {"holding": "位置持稳", "losing": "位置下滑",
             "gaining": "位置上升", "absent": "没有覆盖"}
    MATCH = {"high": "高度匹配", "medium": "部分匹配", "low": "匹配度低",
             "mismatch": "不匹配"}
    LIMIT = {"inventory": "受库存限制", "goal": "受目标限制", "none": ""}
    for r in out:
        r["covered_by_ad"] = bool(r["covered_by_ad"])
        r["trend_label"] = TREND.get(r["position_trend"], r["position_trend"])
        r["match_label"] = MATCH.get(r["match_level"], r["match_level"])
        r["limited_label"] = LIMIT.get(r["limited_by"] or "none", "")
        r["nature"] = nature(r.pop("value_origin"))
    return out


def competitor(con, child_asin: str) -> list[dict]:
    if "ext" not in _aliases(con):
        return []
    out = dbx.rows(con,
                   "select pressure_id, competitor_asin, brand,"
                   " pressure_type, pressure_label, detail, observed_at,"
                   " is_verified, value_origin"
                   " from ext.ext_competitor_pressure where child_asin=?"
                   " order by pressure_id", (child_asin,))
    TYPE = {"price": "价格", "promotion": "促销", "rank": "排名",
            "sales": "销量", "traffic": "流量", "keyword_entry": "关键词入口"}
    for r in out:
        r["type_label"] = TYPE.get(r["pressure_type"], r["pressure_type"])
        r["verify_label"] = ("已核实" if r["is_verified"]
                             else "同期变化待验证")
        r["is_verified"] = bool(r["is_verified"])
        r["nature"] = nature(r.pop("value_origin"))
    return out


def structure_issues(con, decision_id: str) -> list[dict]:
    if "ext" not in _aliases(con):
        return []
    out = dbx.rows(con,
                   "select issue_id, ad_object_id, issue_type, label, detail,"
                   " value_origin from ext.ext_structure_issue"
                   " where decision_id=? order by issue_id", (decision_id,))
    TYPE = {"shared": "共享", "duplicate": "重复承担", "overlap": "投放重叠",
            "unexplained": "无法解释", "missing": "缺失"}
    for r in out:
        r["type_label"] = TYPE.get(r["issue_type"], r["issue_type"])
        r["nature"] = nature(r.pop("value_origin"))
    return out


@lru_cache(maxsize=1)
def _purpose_map_key() -> str:
    return "v1"


def existing_structure(con, child_asin: str) -> list[dict]:
    """板块5：这个子 ASIN 名下真实的广告结构与月度表现。

    purchased_asin 不算「在推它」——方案 3.2 要求与推广角色分开，
    它单独进 structure_issues 的「无法解释」一档。
    """
    ph = ",".join("?" * len(PROMO_ROLES))
    rows = dbx.rows(con, """
        select o.ad_object_id, o.object_level, o.ad_type, o.campaign_name,
               o.ad_group_name, o.target_text, o.match_type,
               f.spend, f.ad_sales, f.acos, f.roas, f.clicks, f.orders,
               f.impressions, f.attribution_days, f.source_status,
               f.comparison_status,
               (select count(distinct b2.child_asin)
                  from bridge_ad_object_product b2
                 where b2.ad_object_id=o.ad_object_id
                   and b2.relation_role='promoted_asin') shared_n,
               (select group_concat(distinct l.label_value)
                  from fact_ad_label_version l
                 where l.ad_object_id=o.ad_object_id
                   and l.label_type='AD_PURPOSE') purpose,
               (select group_concat(distinct l.confirmation_status)
                  from fact_ad_label_version l
                 where l.ad_object_id=o.ad_object_id
                   and l.label_type='AD_PURPOSE') purpose_status
        from bridge_ad_object_product b
        join dim_ad_object o on o.ad_object_id=b.ad_object_id
        left join fact_ad_performance f on f.ad_object_id=o.ad_object_id
             and f.metric_basis='report_month_total'
        where b.child_asin=? and b.relation_role in (%s)
        group by o.ad_object_id
        order by f.spend desc""" % ph, (child_asin,) + PROMO_ROLES)
    CONF = {"confirmed": "已确认", "pending": "待确认",
            "unrecognized": "无法识别"}
    for r in rows:
        n = r.pop("shared_n") or 1
        r["shared_child_count"] = n
        r["is_shared"] = n > 1
        r["level_label"] = ("投放对象" if r["object_level"] == "TARGET"
                            else "广告组" if r["object_level"] == "AD_GROUP"
                            else "Campaign")
        r["name"] = (r["ad_group_name"] or r["target_text"]
                     or r["campaign_name"])
        r["purpose_status_label"] = CONF.get(
            (r.pop("purpose_status") or "").split(",")[0], "待确认")
        r["nature"] = nature(r.pop("source_status"))
        # 可比状态：样本不足或缺前窗时不给变化率（方案 5.2 的比较限制）
        r["comparable"] = (r.pop("comparison_status") or "") == "comparable"
    return rows


def history(con, decision_id: str, prev_id: str | None) -> dict:
    ids = [i for i in (decision_id, prev_id) if i]
    if not ids:
        return {"events": [], "reviews": []}
    ph = ",".join("?" * len(ids))
    ev = dbx.rows(con,
                  "select event_id, event_type, occurred_at, actor,"
                  " decision_reason, handoff_status, handoff_direction,"
                  " handoff_open_items, data_version, rule_version"
                  " from fact_ad_decision_event where decision_id in (%s)"
                  " order by occurred_at, event_id" % ph, tuple(ids))
    ACT = {"accept": "接受", "modify": "修改后接受", "reject": "拒绝",
           "defer": "暂缓"}
    HAND = {"ready": "待执行", "handed_off": "已交接", "rejected": "已拒绝",
            "deferred": "已暂缓"}
    for r in ev:
        r["handoff_open_items"] = jload(r["handoff_open_items"], [])
        r["event_label"] = ACT.get(r["event_type"], r["event_type"])
        r["handoff_label"] = HAND.get(r["handoff_status"],
                                      r["handoff_status"])
    rv = dbx.rows(con,
                  "select feedback_id, review_window, review_at, status,"
                  " baseline_metrics, observed_metrics, conclusion,"
                  " concurrent_variables, next_question"
                  " from fact_review_feedback where decision_id in (%s)"
                  " order by review_window" % ph, tuple(ids))
    for r in rv:
        r["baseline_metrics"] = jload(r["baseline_metrics"], {})
        r["observed_metrics"] = jload(r["observed_metrics"], {})
        r["concurrent_variables"] = jload(r["concurrent_variables"], [])
    return {"events": ev, "reviews": rv}


# --------------------------------------------------- Agent 四段输出

def tasks(con, decision_id: str, is_ext: bool) -> list[dict]:
    if is_ext:
        rows = dbx.rows(con,
                        "select task_id, task_type, task_direction, priority,"
                        " target_scope, constraints, evaluation_direction,"
                        " stop_condition, applies_from, applies_to,"
                        " rule_status, exact_budget, exact_bid,"
                        " exact_placement_adjustment, evidence_ids,"
                        " inventory_constrained, value_origin"
                        " from ext.ext_required_ad_task where decision_id=?"
                        " order by priority, task_id", (decision_id,))
    else:
        rows = dbx.rows(con,
                        "select task_id, task_type, task_direction, priority,"
                        " target_scope, constraints, evaluation_direction,"
                        " stop_condition, rule_status, exact_budget,"
                        " exact_bid, exact_placement_adjustment,"
                        " evidence_ids, inventory_constrained,"
                        " source_status as value_origin"
                        " from fact_required_ad_task where decision_id=?"
                        " order by priority, task_id", (decision_id,))
    for r in rows:
        r["constraints"] = jload(r["constraints"], [])
        r["evidence_ids"] = jload(r["evidence_ids"], [])
        r["inventory_constrained"] = bool(r["inventory_constrained"])
        # 规则未确认就不许出精确值——schema 级约束，不靠文案（方案 5.5）
        conf = r.pop("rule_status") == "confirmed"
        r["mode"] = MODE_FORMAL if conf else MODE_CONDITIONAL
        r["exact_values_withheld"] = not conf
        r["nature"] = nature(r.pop("value_origin"))
    return rows


def mappings(con, task_ids: list, is_ext: bool) -> list[dict]:
    if not task_ids:
        return []
    ph = ",".join("?" * len(task_ids))
    if is_ext:
        rows = dbx.rows(con,
                        "select mapping_id, task_id, ad_object_id,"
                        " coverage_status, attribution_limit, target_fit,"
                        " result_supports_purpose, gap_source, basis_level,"
                        " evidence_ids, is_automatic_error, note, value_origin"
                        " from ext.ext_task_ad_object where task_id in (%s)"
                        " order by task_id, mapping_id" % ph, tuple(task_ids))
    else:
        rows = dbx.rows(con,
                        "select mapping_id, task_id, ad_object_id,"
                        " coverage_status, attribution_limit, evidence_ids,"
                        " is_automatic_error, source_status as value_origin,"
                        " null as target_fit, null as result_supports_purpose,"
                        " null as gap_source, null as basis_level, null as note"
                        " from bridge_task_ad_object where task_id in (%s)"
                        " order by task_id, mapping_id" % ph, tuple(task_ids))
    COV = {"covered": "已被承担", "mixed": "混合了多个目的",
           "missing": "没有对象承担", "duplicate": "多个对象重复承担"}
    ATTR = {"exclusive": "独占归因", "shared": "共享归因：结果不能全归当前子 ASIN",
            "unattributed": "无法归因"}
    GAP = {"structure": "来自结构", "performance": "来自表现",
           "evidence": "证据尚未补齐", "none": ""}
    BASIS = {"confirmed_rule": "客户已确认阈值", "self_history": "自身历史",
             "peer": "可比对象", "conditional": "条件判断"}
    ids = [r["ad_object_id"] for r in rows if r["ad_object_id"]]
    facts = {}
    if ids:
        p2 = ",".join("?" * len(ids))
        facts = {r["ad_object_id"]: r for r in dbx.rows(con,
                 "select o.ad_object_id, o.ad_type, o.campaign_name,"
                 " o.ad_group_name, o.target_text, f.spend, f.ad_sales,"
                 " f.acos, f.roas, f.clicks, f.orders, f.attribution_days"
                 " from dim_ad_object o left join fact_ad_performance f"
                 "   on f.ad_object_id=o.ad_object_id"
                 "  and f.metric_basis='report_month_total'"
                 " where o.ad_object_id in (%s)" % p2, tuple(ids))}
    for r in rows:
        r["evidence_ids"] = jload(r["evidence_ids"], [])
        r["is_automatic_error"] = bool(r["is_automatic_error"])
        r["coverage_label"] = COV.get(r["coverage_status"],
                                      r["coverage_status"])
        r["attribution_label"] = ATTR.get(r["attribution_limit"],
                                          r["attribution_limit"])
        r["gap_label"] = GAP.get(r["gap_source"] or "none", "")
        r["basis_label"] = BASIS.get(r["basis_level"] or "", "")
        r.pop("gap_source", None)
        r.pop("basis_level", None)
        f = facts.get(r["ad_object_id"])
        r["ad_object"] = None if not f else {
            "ad_object_id": f["ad_object_id"],
            "name": f["ad_group_name"] or f["target_text"]
            or f["campaign_name"],
            "ad_type": f["ad_type"], "campaign": f["campaign_name"],
            "attribution_days": f["attribution_days"],
            "metrics": {k: f[k] for k in ("spend", "ad_sales", "acos",
                                          "roas", "clicks", "orders")},
        }
        r["nature"] = nature(r.pop("value_origin"))
    return rows


def diagnoses(con, decision_id: str, is_ext: bool) -> list[dict]:
    if is_ext:
        rows = dbx.rows(con,
                        "select diagnosis_id, task_id, problem_type,"
                        " impacted_goal, priority, confidence, evidence_ids,"
                        " uncertainty, missing_input, check_direction,"
                        " basis_type, causal_claim, what_happened,"
                        " value_origin from ext.ext_diagnosis"
                        " where decision_id=?", (decision_id,))
    else:
        rows = dbx.rows(con,
                        "select diagnosis_id, task_id, problem_type,"
                        " impacted_goal, priority, confidence, evidence_ids,"
                        " uncertainty, missing_input, check_direction,"
                        " basis_type, causal_claim,"
                        " null as what_happened,"
                        " source_status as value_origin"
                        " from fact_ad_diagnosis where decision_id=?",
                        (decision_id,))
    CONF = {"high": "高", "medium": "中", "low": "低"}
    BASIS = {"confirmed_rule": "客户已确认阈值", "self_history": "自身历史",
             "peer": "可比对象", "conditional": "条件判断"}
    order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    for r in rows:
        r["evidence_ids"] = jload(r["evidence_ids"], [])
        # 方案 9.2：不因两个指标同时变化就输出确定因果
        r["causal_claim"] = bool(r["causal_claim"])
        r["confidence_label"] = CONF.get(r["confidence"], r["confidence"])
        r["basis_label"] = BASIS.get(r["basis_type"], r["basis_type"])
        r["mode"] = (MODE_FORMAL if r["basis_type"] == "confirmed_rule"
                     else MODE_CONDITIONAL)
        r["nature"] = nature(r.pop("value_origin"))
    rows.sort(key=lambda x: (order.get(x["priority"], 9), x["diagnosis_id"]))
    return rows


def diagnosis_coverage(con, decision_id: str) -> list[dict]:
    """方案 4.9 列了十类诊断，未命中的也要说——那是「已检查过」的信息。"""
    if "ext" not in _aliases(con):
        return []
    out = dbx.rows(con,
                   "select problem_type, hit, why_not"
                   " from ext.ext_diagnosis_coverage where decision_id=?"
                   " order by hit desc, cov_id", (decision_id,))
    for r in out:
        r["hit"] = bool(r["hit"])
    return out


def proposals(con, decision_id: str, is_ext: bool) -> list[dict]:
    if is_ext:
        rows = dbx.rows(con,
                        "select recommendation_id, diagnosis_id, ad_purpose,"
                        " ad_object_id, structure_gap_id, direction,"
                        " rationale, preconditions, risks, uncertainty,"
                        " observation_metrics, review_windows,"
                        " d7_not_required, rule_status, exact_value,"
                        " value_origin from ext.ext_recommendation"
                        " where decision_id=? order by recommendation_id",
                        (decision_id,))
    else:
        rows = dbx.rows(con,
                        "select recommendation_id, diagnosis_id, ad_purpose,"
                        " ad_object_id, structure_gap_id, direction,"
                        " rationale, preconditions, risks, uncertainty,"
                        " observation_metrics, review_windows,"
                        " d7_not_required, rule_status, exact_value,"
                        " source_status as value_origin"
                        " from fact_ad_recommendation where decision_id=?"
                        " order by recommendation_id", (decision_id,))
    for r in rows:
        for k in ("preconditions", "risks", "observation_metrics",
                  "review_windows"):
            r[k] = jload(r[k], [])
        r["exact_value"] = jload(r["exact_value"])
        r["d7_not_required"] = bool(r["d7_not_required"])
        conf = r.pop("rule_status") == "confirmed"
        r["mode"] = MODE_FORMAL if conf else MODE_CONDITIONAL
        r["exact_values_withheld"] = not conf
        r["nature"] = nature(r.pop("value_origin"))
    return rows


# ================================================ 页面一：分类与数据查看

MONTH_BASIS = "report_month_total"
DAILY_RAW = "search_term_exact_day_sum"
DAILY_SCALED = "daily_scaled_to_month"
FULL_WINDOW = ("2026-07-01", "2026-07-31")
METRICS = ("impressions", "clicks", "spend", "orders", "ad_sales")

STATE_CN = {
    "full_window": "覆盖完整窗口",
    "partial_window": "实际覆盖不足完整窗口",
    "no_daily": "无日粒度序列",
    "short_daily": "日粒度样本不足",
    "no_data": "本期无投放数据",
    "shared_children": "共享多个子 ASIN",
    "mixed_targeting": "混合多类投放对象",
    "no_promoted_asin": "缺少广告 ASIN 映射",
    "sb_from_targets": "由投放对象汇总得出",
    "video_only": "仅出现在视频报表",
}
LABEL_FAMILY_CN = {
    "AD_PURPOSE": "广告目的", "TARGET_OBJECT": "投放对象",
    "PRODUCT_RELATION": "产品关系", "AD_ATTRIBUTE": "广告属性",
    "OPERATOR_CUSTOM": "运营自定义",
}
LABEL_SOURCE_CN = {
    "system_attribute": "报表属性", "auto_mapping": "命名映射",
    "ai_suggested": "AI 建议", "group_inherited": "组继承",
    "operator_confirmed": "运营确认",
}
CONFIRM_CN = {"confirmed": "已确认", "pending": "待确认",
              "unrecognized": "无法识别"}
# 匹配方式是报表原值，全大写单词（EXACT/BROAD）绕得过带下划线的枚举检测，
# 一旦进筛选面板就会直接摆到客户面前，所以在读取边界就映射掉。
# "-" 是 SB/SD 投放对象，本来就没有匹配方式这个概念。
MATCH_CN = {
    "EXACT": "精准匹配", "BROAD": "广泛匹配", "PHRASE": "词组匹配",
    "THEME": "主题投放", "-": "不适用",
}


def match_cn(v) -> str:
    if v is None or str(v).strip() == "":
        return "未标注"
    return MATCH_CN.get(v, str(v))


# 库里把匹配方式的报表原值直接当标签值存了（AD_ATTRIBUTE 族里 EXACT 363、
# BROAD 196、PHRASE 113、THEME 1），同时又有中文写法的同类值（精准匹配 92、
# 广泛匹配 196）。同一件事两种写法并存，上屏就是裸枚举，筛选里还会分裂成两项。
# 在读取边界统一成中文，两种写法自然合并。
# SP / SB / SD 不映射——那是亚马逊后台本身的叫法，运营就这么念。
LABEL_VALUE_CN = {
    "EXACT": "精准匹配", "BROAD": "广泛匹配",
    "PHRASE": "词组匹配", "THEME": "主题投放",
}


def label_value_cn(v) -> str:
    return LABEL_VALUE_CN.get(v, v)


def objects(con, level: str) -> list[dict]:
    return dbx.rows(con, """
        select o.*, c.state as campaign_state, c.budget as campaign_budget,
               c.bid_strategy, c.lifecycle, c.owner, c.has_july_delivery
        from dim_ad_object o
        left join dim_campaign c on c.campaign_id=o.campaign_id
        where o.object_level=?
        order by o.ad_type, o.campaign_name, o.ad_group_name, o.target_text""",
                    (level,))


def month_facts(con) -> dict:
    return {r["ad_object_id"]: r for r in dbx.rows(
        con, "select * from fact_ad_performance where metric_basis=?",
        (MONTH_BASIS,))}


def daily_by_object(con, basis: str) -> dict:
    out: dict[str, list[dict]] = {}
    for r in dbx.rows(con,
                      "select ad_object_id, stat_date, impressions, clicks,"
                      " spend, orders, ad_sales, scale_factor_spend,"
                      " day_coverage from fact_ad_daily where metric_basis=?"
                      " order by ad_object_id, stat_date", (basis,)):
        out.setdefault(r["ad_object_id"], []).append(r)
    return out


def labels_by_object(con) -> dict:
    out: dict[str, list[dict]] = {}
    for r in dbx.rows(con,
                      "select ad_object_id, label_type, label_value,"
                      " label_source, confirmation_status, effective_from,"
                      " effective_to, inherited_from_object_id"
                      " from fact_ad_label_version"
                      " order by ad_object_id, label_type, label_value"):
        r["family_label"] = LABEL_FAMILY_CN.get(r["label_type"],
                                               r["label_type"])
        r["label_value_raw"] = r["label_value"]
        r["label_value"] = label_value_cn(r["label_value"])
        r["source_label"] = LABEL_SOURCE_CN.get(r["label_source"],
                                                r["label_source"])
        r["confirm_label"] = CONFIRM_CN.get(r["confirmation_status"],
                                            r["confirmation_status"])
        out.setdefault(r["ad_object_id"], []).append(r)
    return out


def label_taxonomy(con, level: str = None) -> list[dict]:
    """板块2 标签体系：五类标签 × 取值 × 来源 × 确认状态。

    必须按粒度过滤，并且数的是「有多少个对象」而不是「有多少条标签行」。
    原来对整张标签表 group by 不 join 对象表，后果是两个粒度看到完全一样
    的选项、计数是标签版本行数，点下去还可能一个对象都选不出来。
    """
    where, args = "", []
    if level:
        where = " join dim_ad_object o on o.ad_object_id=l.ad_object_id" \
                " where o.object_level=?"
        args = [level]
    rows = dbx.rows(con,
                    "select l.label_type, l.label_value, l.label_source,"
                    " l.confirmation_status, l.ad_object_id"
                    " from fact_ad_label_version l" + where,
                    tuple(args))
    # 值映射后 EXACT 与「广泛匹配」会同名，必须按对象去重合并，
    # 否则同一个对象被两种写法各数一次。
    acc: dict[tuple, dict] = {}
    for r in rows:
        v = label_value_cn(r["label_value"])
        k = (r["label_type"], v)
        a = acc.setdefault(k, {"value": v, "objs": set(),
                               "sources": set(), "confirms": set()})
        a["objs"].add(r["ad_object_id"])
        a["sources"].add(LABEL_SOURCE_CN.get(r["label_source"],
                                             r["label_source"]))
        a["confirms"].add(CONFIRM_CN.get(r["confirmation_status"],
                                         r["confirmation_status"]))
    fam: dict[str, dict] = {}
    for (t, v), a in acc.items():
        f = fam.setdefault(t, {
            "type": t, "label": LABEL_FAMILY_CN.get(t, t),
            "values": [], "total": 0})
        f["values"].append({
            "value": v, "n": len(a["objs"]),
            "source_label": "、".join(sorted(a["sources"])),
            "confirm_label": "、".join(sorted(a["confirms"]))})
    for f in fam.values():
        f["values"].sort(key=lambda x: (-x["n"], x["value"]))
        f["total"] = sum(x["n"] for x in f["values"])
    order = ["PRODUCT_RELATION", "TARGET_OBJECT", "AD_PURPOSE",
             "AD_ATTRIBUTE", "OPERATOR_CUSTOM"]
    return sorted(fam.values(),
                  key=lambda f: order.index(f["type"])
                  if f["type"] in order else 99)


def promoted_by_object(con) -> dict:
    out: dict[str, list[str]] = {}
    for r in dbx.rows(con,
                      "select ad_object_id, child_asin"
                      " from bridge_ad_object_product"
                      " where relation_role='promoted_asin'"):
        out.setdefault(r["ad_object_id"], []).append(r["child_asin"])
    return out


def budget_by_campaign(con) -> dict:
    return {r["campaign_id"]: r for r in dbx.rows(
        con, "select * from fact_budget")}


def invalid_by_campaign(con) -> dict:
    return {r["campaign_id"]: r for r in dbx.rows(
        con, "select * from fact_invalid_traffic")}


def yoy_by_campaign(con) -> dict:
    return {r["campaign_id"]: r for r in dbx.rows(
        con, "select * from fact_ad_yoy")}


def placements_by_campaign(con) -> dict:
    out: dict[str, list[dict]] = {}
    for r in dbx.rows(con, "select * from fact_placement"):
        out.setdefault(r["campaign_id"], []).append(r)
    return out


def benchmark_ladder(con) -> list[dict]:
    """类目基准阶梯：6 行是 6 层嵌套类目，不是 6 个平行类目。"""
    return dbx.rows(con,
                    "select category, own_impressions, own_ctr,"
                    " peer_ctr_p25, peer_ctr_median, peer_ctr_p75,"
                    " own_acos, peer_acos_median, own_roas,"
                    " peer_roas_median from fact_category_benchmark"
                    " order by benchmark_id")


def anomaly_rules(con) -> list[dict]:
    CLS = {"absolute_threshold": "绝对阈值", "self_history": "相对自身历史",
           "peer_deviation": "相对同组对象偏离", "data_state": "数据状态"}
    out = dbx.rows(con,
                   "select rule_id, rule_name, rule_class, metric_name,"
                   " operator, threshold, applies_to, rule_version"
                   " from dim_anomaly_rule order by rule_class, rule_id")
    for r in out:
        r["class_label"] = CLS.get(r["rule_class"], r["rule_class"])
    return out


def scope_counts(con) -> dict:
    """板块1 当前范围与数据状态。"""
    q = lambda s, a=(): dbx.scalar(con, s, a)  # noqa: E731
    camp_total = q("select count(*) from dim_ad_object"
                   " where object_level='CAMPAIGN'")
    camp_live = q("select count(*) from dim_campaign"
                  " where has_july_delivery=1")
    return {
        "campaign_total": camp_total,
        "campaign_live": camp_live,
        "campaign_structure_only": (camp_total or 0) - (camp_live or 0),
        "ad_group_total": q("select count(*) from dim_ad_object"
                            " where object_level='AD_GROUP'"),
        "target_total": q("select count(*) from dim_ad_object"
                          " where object_level='TARGET'"),
        "source_files": q("select count(*) from source_file"),
        # 广告组只有 54 个不是构建漏了：报表里的广告组名与 (Campaign,组) 组合
        # 全部落在 dim_ad_object 里，差集为 0。少是因为 80 个 Campaign 里有
        # 28 个在报表里既没有广告组也没有投放对象，界面得把这件事说出来，
        # 否则看的人只会以为数字算错了。
        "campaign_no_structure": q(
            "select count(*) from dim_ad_object c"
            " where c.object_level='CAMPAIGN'"
            " and not exists (select 1 from dim_ad_object x"
            "   where x.campaign_id=c.campaign_id"
            "     and x.object_level in ('AD_GROUP','TARGET'))"),
        "ad_group_with_month": q(
            "select count(distinct f.ad_object_id) from fact_ad_performance f"
            " join dim_ad_object o on o.ad_object_id=f.ad_object_id"
            " where o.object_level='AD_GROUP' and f.metric_basis=?",
            (MONTH_BASIS,)),
        "by_type_group": {r["ad_type"]: r["n"] for r in dbx.rows(
            con, "select ad_type, count(*) n from dim_ad_object"
                 " where object_level='AD_GROUP' group by 1 order by 2 desc")},
        "by_type_target": {r["ad_type"]: r["n"] for r in dbx.rows(
            con, "select ad_type, count(*) n from dim_ad_object"
                 " where object_level='TARGET' group by 1 order by 2 desc")},
        "with_daily_group": q(
            "select count(distinct d.ad_object_id) from fact_ad_daily d"
            " join dim_ad_object o on o.ad_object_id=d.ad_object_id"
            " where o.object_level='AD_GROUP'"),
        "with_daily_target": q(
            "select count(distinct d.ad_object_id) from fact_ad_daily d"
            " join dim_ad_object o on o.ad_object_id=d.ad_object_id"
            " where o.object_level='TARGET'"),
        "attribution": {r["ad_type"]: r["attribution_days"] for r in dbx.rows(
            con, "select ad_type, max(attribution_days) attribution_days"
                 " from fact_ad_performance where metric_basis=?"
                 " group by ad_type", (MONTH_BASIS,))},
    }
