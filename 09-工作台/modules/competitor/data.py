"""竞品模块数据层。

契约 6.1：只读打开，路径来自 core/paths.py，不在业务文件里写死绝对路径。
契约 6.3：产品身份靠 ATTACH 产品包读，本模块的包里没有 dim_product_child。
契约 6.6：`value_origin` 只在库里用；上屏一律映射成固定中文词表。
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from core import paths

# ---- 上屏词表（契约 6.6，全站统一，模块不自造说法）--------------------------
NATURE = {"direct": "真实", "derived": "推导", "constructed": "模拟", "mixed": "混合"}
STATUS = {
    "normal": "正常", "interrupted": "缺失", "stale": "过期",
    "conflict": "待确认", "missing": "缺失",
}
# 数据状态轨上要说清"发生了什么"，用独立标签列承载，不靠状态词表达细节
ATTENTION = {"high": "优先处理", "medium": "持续关注", "low": "留观", "none": "无需处理"}
ATTENTION_ORDER = {"high": 0, "medium": 1, "low": 2, "none": 3}
EVIDENCE = {"sufficient": "证据充分", "partial": "证据部分", "insufficient": "证据不足"}
DOMAIN = {
    "price_promo": "活动与价格", "market": "市场表现",
    "keyword": "关键词位置", "traffic": "流量结构",
}
TRACK = {
    "market": "市场结果", "price_promo": "价格促销",
    "keyword": "流量与位置", "data_status": "证据事件",
}
TRACK_GRAIN = {"market": "日", "price_promo": "日", "keyword": "周 / 月", "data_status": "区间"}
TRIGGER = {"scheduled": "周跑", "manual": "手动", "priority": "重点跑"}
TRANSITION = {
    "new": "新增", "sustained": "持续", "escalated": "加重",
    "eased": "减弱", "cleared": "已解除",
}

AGENT_DB = Path(os.environ.get(
    "WORKBENCH_COMPETITOR_AGENT_DB",
    Path(__file__).resolve().parent / "derived/competitor_agent_state_v2.sqlite",
)).expanduser().resolve()


def term(table: dict, v: str | None) -> str | None:
    """码值 → 中文。

    Agent 输出的码值可能落在词表外（词表是契约钉死的，见要则 §9）。三种回落都错：
    回落成原值 = 英文码值上屏（G9 禁）；回落成空白 = 把 Agent 的契约违规静默藏起来。
    所以词表外的非空值一律显示成「待确认」——它是合法的状态词，且看得见。
    NULL 是 Agent 的合法输出（要则 §4「判断不出就给 NULL」），照实返回 None，由调用处决定不渲染该行。
    """
    if v is None or v == "":
        return None
    return table.get(v) or "待确认"


def nature(v: str | None) -> str:
    return NATURE.get(v or "", "混合")


def mix_nature(values) -> str:
    """一个对象同时含多种来源时返回「混合」（契约 6.6）。"""
    s = {v for v in values if v}
    if not s:
        return "混合"
    if len(s) == 1:
        return NATURE.get(next(iter(s)), "混合")
    return "混合"


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{paths.COMPETITOR_DB}?mode=ro", uri=True)
    con.execute(f"ATTACH DATABASE 'file:{paths.PRODUCT_DB}?mode=ro' AS pr")
    if AGENT_DB.exists():
        con.execute(f"ATTACH DATABASE 'file:{AGENT_DB}?mode=ro' AS agent")
    con.row_factory = sqlite3.Row
    return con


def rows(con, sql: str, args: tuple = ()) -> list[dict[str, Any]]:
    return [dict(r) for r in con.execute(sql, args)]


def one(con, sql: str, args: tuple = ()) -> dict[str, Any] | None:
    r = con.execute(sql, args).fetchone()
    return dict(r) if r else None


def manifest(con) -> dict[str, str]:
    return {r["key"]: r["value"] for r in con.execute(
        "SELECT key, value FROM competitor_manifest")}


# ---- Agent sidecar：只读 latest completed，原库判断表永不再读 ----
def has_agent(con) -> bool:
    if not any(r[1] == "agent" for r in con.execute("PRAGMA database_list")):
        return False
    required = {
        "fact_competitor_agent_execution",
        "fact_competitor_analysis_run",
        "fact_competitor_analysis_change",
        "fact_competitor_analysis_timeline",
        "fact_competitor_analysis_concurrency",
        "fact_competitor_analysis_attention_reason",
        "fact_competitor_analysis_impact",
        "fact_competitor_analysis_open_item",
        "fact_competitor_analysis_diff",
        "fact_competitor_analysis_report",
        "fact_competitor_evidence_handoff",
    }
    present = {r[0] for r in con.execute(
        "SELECT name FROM agent.sqlite_master WHERE type='table'"
    )}
    return required.issubset(present)


LATEST = """
WITH ranked AS (
  SELECT r.*, e.source_context_hash, e.threshold_fingerprint, e.completed_at,
         ROW_NUMBER() OVER (
           PARTITION BY r.family_asin
           ORDER BY julianday(e.created_at) DESC, e.created_at DESC, e.run_id DESC
         ) AS rn
  FROM agent.fact_competitor_analysis_run r
  JOIN agent.fact_competitor_agent_execution e USING(run_id)
  WHERE e.status='completed'
)
SELECT * FROM ranked WHERE rn=1
"""


def latest_runs(con) -> dict[str, dict]:
    if not has_agent(con):
        return {}
    return {r["family_asin"]: r for r in rows(con, LATEST)}


def latest_run(con, family_asin: str) -> dict | None:
    if not has_agent(con):
        return None
    return one(con, f"SELECT * FROM ({LATEST}) WHERE family_asin=?", (family_asin,))


def latest_execution(con, family_asin: str) -> dict | None:
    if not has_agent(con):
        return None
    return one(con, """
        SELECT * FROM agent.fact_competitor_agent_execution
        WHERE family_asin=?
        ORDER BY julianday(created_at) DESC, created_at DESC, run_id DESC LIMIT 1
    """, (family_asin,))


def analysis_state(con, family_asin: str, current_context_hash: str) -> str:
    """Separate observation availability from Agent result state."""
    newest = latest_execution(con, family_asin)
    run = latest_run(con, family_asin)
    if run is None:
        # failed/skipped 是任务状态，不是业务结论。只有真正在等待或运行的
        # 任务才表示“未完成”；失败/跳过且无 completed run 时仍是尚未分析。
        return "incomplete" if newest and newest["status"] in ("queued", "running") else "not_run"
    integrity = one(con, """
        SELECT
          (SELECT COUNT(*) FROM agent.fact_competitor_analysis_change WHERE run_id=?) changes,
          (SELECT COUNT(*) FROM agent.fact_competitor_analysis_diff WHERE run_id=?) diffs
    """, (run["run_id"], run["run_id"]))
    # insufficient 按 V2 契约可以在证据步后短路，没有 change 是合法结果；
    # 其他证据档位若没有任何变化行，才是结果不完整。
    if (not integrity or integrity["diffs"] != 1
            or (run["evidence_level"] != "insufficient" and not integrity["changes"])):
        return "damaged"
    if (newest and newest["run_id"] != run["run_id"]
            and newest["status"] in ("queued", "running")):
        return "incomplete"
    if run["evidence_level"] == "insufficient":
        return "insufficient"
    if run["source_context_hash"] != current_context_hash:
        return "stale"
    return "current"


def source_context_hash(con, family_asin: str, thresholds: dict) -> str:
    """Canonical observation fingerprint shared by Runner and GET freshness checks."""
    # JSON 会区分 Python 的 5 与 5.0，但页面/Node 传输不会保留这个类型差异。
    # 先按契约字段类型归一，避免相同业务阈值产生不同 context hash。
    canonical_thresholds = {
        "price_drop_pct": float(thresholds["price_drop_pct"]),
        "gap_shift_pct": float(thresholds["gap_shift_pct"]),
        "rank_shift_pct": float(thresholds["rank_shift_pct"]),
        "kw_rank_shift": int(thresholds["kw_rank_shift"]),
        "min_duration_days": int(thresholds["min_duration_days"]),
        "family_coverage_pct": float(thresholds["family_coverage_pct"]),
        "stale_days": int(thresholds["stale_days"]),
    }
    payload = {
        "family": one(con, "SELECT * FROM dim_competitor_family WHERE family_asin=?", (family_asin,)),
        "children": rows(con, "SELECT * FROM dim_competitor_child WHERE family_asin=? ORDER BY child_asin", (family_asin,)),
        "offers": rows(con, """SELECT o.* FROM dim_competitor_offer o JOIN dim_competitor_child c
            USING(child_asin) WHERE c.family_asin=? ORDER BY offer_id""", (family_asin,)),
        "price": rows(con, """
            SELECT c.child_asin, MIN(p.date) date_from, MAX(p.date) date_to,
                   MIN(p.unit_price) min_unit, MAX(p.unit_price) max_unit,
                   SUM(CASE WHEN p.promo_kind NOT IN ('none','') AND p.promo_kind IS NOT NULL THEN 1 ELSE 0 END) promo_days,
                   (SELECT unit_price FROM fact_competitor_price_daily p0 WHERE p0.child_asin=c.child_asin ORDER BY date LIMIT 1) first_unit,
                   (SELECT unit_price FROM fact_competitor_price_daily p1 WHERE p1.child_asin=c.child_asin ORDER BY date DESC LIMIT 1) last_unit
            FROM dim_competitor_child c JOIN fact_competitor_price_daily p USING(child_asin)
            WHERE c.family_asin=? GROUP BY c.child_asin ORDER BY c.child_asin
        """, (family_asin,)),
        "market": rows(con, "SELECT * FROM fact_competitor_market_daily WHERE family_asin=? ORDER BY date", (family_asin,)),
        "keywords": rows(con, "SELECT * FROM fact_competitor_keyword_rank WHERE family_asin=? ORDER BY keyword, observed_date", (family_asin,)),
        "traffic": rows(con, "SELECT * FROM fact_competitor_traffic_mix WHERE family_asin=? ORDER BY period_start", (family_asin,)),
        "status": data_status(con, family_asin),
        "relations": rows(con, "SELECT * FROM bridge_competitor_child WHERE family_asin=? ORDER BY rel_id", (family_asin,)),
        "keyword_relations": rows(con, "SELECT * FROM bridge_competitor_keyword WHERE family_asin=? ORDER BY keyword", (family_asin,)),
        "thresholds": canonical_thresholds,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


# ---- 观察层读取 ------------------------------------------------------------
def families(con) -> list[dict]:
    return rows(con, "SELECT * FROM dim_competitor_family ORDER BY family_asin")


def children(con, family_asin: str) -> list[dict]:
    return rows(
        con,
        "SELECT * FROM dim_competitor_child WHERE family_asin = ?"
        " ORDER BY is_main_variant DESC, snapshot_price",
        (family_asin,),
    )


def offers(con, family_asin: str) -> list[dict]:
    return rows(
        con,
        "SELECT o.* FROM dim_competitor_offer o JOIN dim_competitor_child c"
        " USING(child_asin) WHERE c.family_asin = ? ORDER BY o.is_buybox DESC",
        (family_asin,),
    )


def price_series(con, child_asin: str) -> list[dict]:
    return rows(
        con,
        "SELECT date, list_price, deal_price, final_price, unit_price, coupon_pct,"
        " promo_kind, value_origin FROM fact_competitor_price_daily"
        " WHERE child_asin = ? ORDER BY date",
        (child_asin,),
    )


def market_series(con, family_asin: str) -> list[dict]:
    return rows(
        con,
        "SELECT date, rank_sub, rank_main, units_rolling30, rating, rating_count,"
        " new_rating, value_origin FROM fact_competitor_market_daily"
        " WHERE family_asin = ? ORDER BY date",
        (family_asin,),
    )


def keyword_series(con, family_asin: str) -> list[dict]:
    return rows(
        con,
        "SELECT k.keyword, m.keyword_cn, m.monthly_search, m.is_battleground,"
        " k.observed_date, k.organic_rank, k.ad_slot, k.is_top3, k.click_share,"
        " k.conversion_share, k.value_origin"
        " FROM fact_competitor_keyword_rank k JOIN dim_competitor_keyword m"
        " USING(keyword) WHERE k.family_asin = ?"
        " ORDER BY m.is_battleground DESC, k.keyword, k.observed_date",
        (family_asin,),
    )


def traffic_series(con, family_asin: str) -> list[dict]:
    return rows(
        con,
        "SELECT period_start, period_end, organic_share, ad_share, other_share,"
        " top_entry_keyword, value_origin FROM fact_competitor_traffic_mix"
        " WHERE family_asin = ? ORDER BY period_start",
        (family_asin,),
    )


def data_status(con, family_asin: str) -> list[dict]:
    return rows(
        con,
        "SELECT * FROM fact_competitor_data_status WHERE object_id = ?"
        " OR object_id IN (SELECT child_asin FROM dim_competitor_child"
        "                  WHERE family_asin = ?) ORDER BY date_from",
        (family_asin, family_asin),
    )


# ---- 自有一侧：ATTACH 产品包读，不在本包重建（契约 6.3）--------------------
def own_relations(con, family_asin: str) -> list[dict]:
    return rows(
        con,
        "SELECT b.rel_id, b.child_asin, b.parent_asin, b.relation_basis,"
        " b.relation_note, b.confirm_status, b.since_date, b.value_origin,"
        " c.product_name, c.size, c.combination, c.product_lifecycle"
        " FROM bridge_competitor_child b"
        " LEFT JOIN pr.dim_product_child c ON c.child_asin = b.child_asin"
        " WHERE b.family_asin = ?",
        (family_asin,),
    )


PACK_EXPR = (
    "CAST(NULLIF(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE("
    "c.combination,'A',''),'B',''),'C',''),'D',''),'F',''),'G',''),'H','') , '')"
    " AS INTEGER)"
)


def own_unit_price_all(con, as_of: str) -> dict[str, float]:
    """每个竞品族对应的自有件单价均值，一次查完，供比较表排序与价差列用。"""
    sql = (
        "SELECT b.family_asin AS fa,"
        "       AVG(p.selling_price * 1.0 / NULLIF(k.pack, 0)) AS unit_price"
        " FROM bridge_competitor_child b"
        " JOIN (SELECT c.child_asin, " + PACK_EXPR + " AS pack"
        "         FROM pr.dim_product_child c) k ON k.child_asin = b.child_asin"
        " JOIN pr.fact_child_price_daily p"
        "   ON p.child_asin = b.child_asin AND p.date = ?"
        " GROUP BY 1"
    )
    return {r["fa"]: r["unit_price"] for r in rows(con, sql, (as_of,))}


def competitor_unit_price_all(con, as_of: str) -> dict[str, float]:
    return {r["family_asin"]: r["unit_price"] for r in rows(
        con,
        "SELECT c.family_asin, AVG(p.unit_price) AS unit_price"
        " FROM fact_competitor_price_daily p"
        " JOIN dim_competitor_child c USING(child_asin)"
        " WHERE p.date = ? GROUP BY 1", (as_of,))}


def spark_series(con, table: str, key: str, value: str, ids: list[str],
                 points: int = 40) -> dict[str, list]:
    """给比较表用的迷你趋势：每个对象降采样到 points 个点，一次查完。

    表格里一行只有几个数字时，读起来就是文字陈述；给一条 40 点的轨，
    「在涨还是在退」不用读数字就能看出来。
    """
    if not ids:
        return {}
    ph = ",".join("?" * len(ids))
    raw: dict[str, list] = {}
    for r in con.execute(
        f"SELECT {key} AS k, {value} AS v FROM {table}"
        f" WHERE {key} IN ({ph}) ORDER BY {key}, date", ids
    ):
        raw.setdefault(r["k"], []).append(r["v"])
    out = {}
    for k, vals in raw.items():
        vals = [v for v in vals if v is not None]
        if len(vals) <= points:
            out[k] = vals
            continue
        step = len(vals) / points
        out[k] = [vals[min(int(i * step), len(vals) - 1)] for i in range(points)]
    return out


def child_spark_price(con, ids: list[str], points: int = 40) -> dict[str, list]:
    """价格轨按族取主销子体，避免同族多子体混在一条线上。"""
    if not ids:
        return {}
    ph = ",".join("?" * len(ids))
    mains = {r["family_asin"]: r["child_asin"] for r in rows(
        con,
        f"SELECT family_asin, child_asin FROM dim_competitor_child"
        f" WHERE family_asin IN ({ph})"
        f" ORDER BY is_main_variant DESC, snapshot_price", ids)}
    by_child = spark_series(con, "fact_competitor_price_daily", "child_asin",
                            "unit_price", list(mains.values()), points)
    return {fa: by_child.get(cid, []) for fa, cid in mains.items()}


def promo_bands(con, child_asin: str) -> list[dict]:
    """把逐日 promo_kind 压成活动区间，供图上画阴影带。"""
    out: list[dict] = []
    cur = None
    for r in con.execute(
        "SELECT date, promo_kind, coupon_pct FROM fact_competitor_price_daily"
        " WHERE child_asin = ? ORDER BY date", (child_asin,)
    ):
        kind = r["promo_kind"] if r["promo_kind"] not in (None, "none") else None
        if kind:
            if cur and cur["kind"] == kind:
                cur["date_to"] = r["date"]
            else:
                if cur:
                    out.append(cur)
                cur = {"kind": kind, "date_from": r["date"], "date_to": r["date"],
                       "coupon_pct": r["coupon_pct"]}
        elif cur:
            out.append(cur)
            cur = None
    if cur:
        out.append(cur)
    label = {"deal": "活动价", "coupon": "Coupon", "lightning": "秒杀"}
    for b in out:
        b["label"] = label.get(b["kind"], "活动")
    return out


def market_snapshot(con, as_of: str) -> dict[str, dict]:
    return {r["family_asin"]: r for r in rows(
        con,
        "SELECT family_asin, rank_sub, units_rolling30, rating, rating_count"
        " FROM fact_competitor_market_daily WHERE date = ?", (as_of,))}


def own_unit_price(con, family_asin: str, as_of: str) -> dict | None:
    """自有一侧在基准日的件单价均值，用于件单价同口径比较。"""
    r = con.execute(
        "SELECT AVG(p.selling_price * 1.0 / NULLIF(b.pack, 0)) AS unit_price,"
        "       COUNT(*) AS n"
        " FROM bridge_competitor_child b0"
        " JOIN (SELECT c.child_asin,"
        "              CAST(NULLIF(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE("
        "                   REPLACE(REPLACE(c.combination,'A',''),'B',''),'C',''),"
        "                   'D',''),'F',''),'G',''),'H','') , '') AS INTEGER) AS pack"
        "         FROM pr.dim_product_child c) b"
        "   ON b.child_asin = b0.child_asin"
        " JOIN pr.fact_child_price_daily p"
        "   ON p.child_asin = b0.child_asin AND p.date = ?"
        " WHERE b0.family_asin = ?",
        (as_of, family_asin),
    ).fetchone()
    if not r or not r["n"]:
        return None
    return {"unit_price": r["unit_price"], "child_count": r["n"]}


# ---- 分析层读取 ------------------------------------------------------------
def changes(con, run_id: str) -> list[dict]:
    if not has_agent(con):
        return []
    return rows(
        con,
        "SELECT * FROM agent.fact_competitor_analysis_change WHERE run_id = ?"
        " ORDER BY change_seq",
        (run_id,),
    )


def all_changes(con) -> dict[str, list[dict]]:
    if not has_agent(con):
        return {}
    out: dict[str, list[dict]] = {}
    for c in rows(con, "SELECT * FROM agent.fact_competitor_analysis_change"
                       " ORDER BY run_id, change_seq"):
        out.setdefault(c["run_id"], []).append(c)
    return out


def timeline(con, run_id: str) -> list[dict]:
    if not has_agent(con):
        return []
    return rows(
        con,
        "SELECT * FROM agent.fact_competitor_analysis_timeline WHERE run_id = ?"
        " ORDER BY track, item_seq",
        (run_id,),
    )


def concurrency(con, run_id: str) -> list[dict]:
    if not has_agent(con):
        return []
    return rows(
        con,
        "SELECT * FROM agent.fact_competitor_analysis_concurrency WHERE run_id = ?"
        " ORDER BY pair_seq",
        (run_id,),
    )


def attention_reasons(con, run_id: str) -> list[dict]:
    if not has_agent(con):
        return []
    return rows(
        con,
        "SELECT * FROM agent.fact_competitor_analysis_attention_reason WHERE run_id = ?"
        " ORDER BY reason_seq",
        (run_id,),
    )


def impacts(con, run_id: str) -> list[dict]:
    if not has_agent(con):
        return []
    return rows(
        con,
        "SELECT * FROM agent.fact_competitor_analysis_impact WHERE run_id = ?"
        " ORDER BY impact_seq",
        (run_id,),
    )


def open_items(con, run_id: str) -> list[dict]:
    if not has_agent(con):
        return []
    return rows(
        con,
        "SELECT * FROM agent.fact_competitor_analysis_open_item WHERE run_id = ?"
        " ORDER BY item_seq",
        (run_id,),
    )


def diff(con, run_id: str) -> dict | None:
    if not has_agent(con):
        return None
    return one(con, "SELECT * FROM agent.fact_competitor_analysis_diff WHERE run_id = ?",
               (run_id,))


def handoffs(con, run_id: str) -> list[dict]:
    if not has_agent(con):
        return []
    return rows(
        con,
        "SELECT * FROM agent.fact_competitor_evidence_handoff WHERE frozen_run_id = ?",
        (run_id,),
    )


def report(con) -> list[dict]:
    if not has_agent(con):
        return []
    return rows(
        con,
        """WITH latest AS (
             SELECT e.run_id, e.family_asin,
                    ROW_NUMBER() OVER (PARTITION BY e.family_asin
                      ORDER BY julianday(e.created_at) DESC, e.created_at DESC, e.run_id DESC) rn
             FROM agent.fact_competitor_agent_execution e
             WHERE e.status='completed'
           )
           SELECT p.*, f.brand FROM agent.fact_competitor_analysis_report p
           JOIN latest l ON l.run_id=p.ref_run_id AND l.rn=1
           JOIN agent.fact_competitor_analysis_run r ON r.run_id=p.ref_run_id
           JOIN dim_competitor_family f USING(family_asin)
           WHERE r.evidence_level='sufficient' AND r.attention_level IN ('high','medium')
             AND EXISTS (SELECT 1 FROM agent.fact_competitor_analysis_change c
                         WHERE c.run_id=p.ref_run_id AND c.represents_family=1)
           ORDER BY CASE r.attention_level WHEN 'high' THEN 0 ELSE 1 END,
                    julianday(p.created_at) DESC, p.item_seq""",
    )
