"""关键词模块数据层：只读取事实，不做任何依赖参数的计算。

契约 6.1 路径从 core/paths.py 取，只读 URI 打开
契约 6.3 产品身份 ATTACH 产品包读，本包不重建 dim_product_child / dim_product_parent
契约 6.6 value_origin（direct/derived/constructed）在读取边界映射成中文性质词，不上屏
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from core import paths

from . import agent_result

# 契约 6.6：上屏只用这两套固定词表，各模块不自造说法
NATURE = {"direct": "真实", "derived": "推导", "constructed": "模拟", "mixed": "混合"}
STATUS = ["正常", "加载中", "空结果", "过期", "缺失", "待确认", "失败"]

# 位置层五种自然位状态，页面必须能分别显示（方案 7.3 §5.5 红线）
ORGANIC_STATES = ("covered", "not_covered", "beyond_depth", "collect_failed",
                  "not_monitored")

_REQUEST_DATABASE: ContextVar[Path | None] = ContextVar(
    "keyword_request_database", default=None
)


@contextmanager
def use_database(path: Path):
    """Pin all reads in one request to the same resolved database."""
    token = _REQUEST_DATABASE.set(path)
    try:
        yield
    finally:
        _REQUEST_DATABASE.reset(token)


def connect() -> sqlite3.Connection:
    keyword_db = _REQUEST_DATABASE.get() or agent_result.database_path(paths.KEYWORD_DB)
    con = sqlite3.connect(f"file:{keyword_db}?mode=ro", uri=True,
                          check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute(f"attach database 'file:{paths.PRODUCT_DB}?mode=ro' as prod")
    return con


def rows(con: sqlite3.Connection, sql: str, args: tuple = ()) -> list[dict[str, Any]]:
    return [dict(r) for r in con.execute(sql, args)]


def one(con: sqlite3.Connection, sql: str, args: tuple = ()) -> Any:
    r = con.execute(sql, args).fetchone()
    if r is None:
        return None
    return dict(r) if len(r.keys()) > 1 else r[0]


def nature_of(origins) -> str:
    """一组 value_origin 折成一个中文性质词。混合来源报「混合」。"""
    s = {o for o in origins if o}
    if not s:
        return NATURE["constructed"]
    if len(s) > 1:
        return NATURE["mixed"]
    return NATURE.get(next(iter(s)), NATURE["constructed"])


# ------------------------------------------------------------------ 标签与词表

def labels() -> dict[str, dict[str, str]]:
    """枚举码 → 中文标签。映射在读取边界完成，页面只拿中文（契约 11 文案类）。"""
    con = connect()
    out: dict[str, dict[str, str]] = {}
    for r in rows(con, "select domain, code, label from dim_keyword_state_label"):
        out.setdefault(r["domain"], {})[r["code"]] = r["label"]
    con.close()
    return out


# ------------------------------------------------------------------------ 元信息

def scope() -> dict[str, Any]:
    con = connect()
    try:
        r = rows(con, "select * from dim_keyword_scope limit 1")
        return r[0] if r else {}
    finally:
        con.close()


def counts() -> dict[str, int]:
    con = connect()
    try:
        q = lambda t: one(con, "select count(*) from %s" % t)  # noqa: E731
        return {
            "term": q("dim_keyword_term"),
            "market_snapshot": q("fact_keyword_market_snapshot"),
            "head_asin": q("fact_keyword_head_asin"),
            "pair": q("dim_keyword_child_pair"),
            "position_daily": q("fact_keyword_child_position_daily"),
            "traffic_daily": q("fact_keyword_child_traffic_daily"),
            "market_event": q("fact_keyword_market_change_event"),
            "coverage_event": q("fact_keyword_coverage_event"),
            "evidence": q("fact_keyword_evidence"),
            "audit_record": q("fact_keyword_audit_record"),
            "daily_report": q("fact_keyword_daily_report"),
        }
    finally:
        con.close()


def window() -> dict[str, Any]:
    con = connect()
    try:
        return {
            "week_from": one(con, "select min(period_end) from fact_keyword_market_snapshot"
                                  " where period_type='week'"),
            "week_to": one(con, "select max(period_end) from fact_keyword_market_snapshot"
                                " where period_type='week'"),
            "month_from": one(con, "select min(period_end) from fact_keyword_market_snapshot"
                                   " where period_type='month'"),
            "month_to": one(con, "select max(period_end) from fact_keyword_market_snapshot"
                                 " where period_type='month'"),
            "position_from": one(con, "select min(date) from fact_keyword_child_position_daily"),
            "position_to": one(con, "select max(date) from fact_keyword_child_position_daily"),
            "collect_depth": one(con, "select collect_depth from"
                                      " fact_keyword_child_position_daily limit 1"),
        }
    finally:
        con.close()


def distributions() -> dict[str, Any]:
    """词库四态、运营角色、品牌角色、位置五态、覆盖四态 —— 全部带中文标签。"""
    con = connect()
    lab = labels()
    try:
        pos = rows(con, "select organic_state as code, count(*) as n"
                        " from fact_keyword_child_position_daily group by 1")
        for r in pos:
            r["label"] = lab.get("position_state", {}).get(r["code"], r["code"])
        cov = rows(con, "select coverage_state as code, count(*) as n"
                        " from fact_keyword_child_position_daily group by 1")
        for r in cov:
            r["label"] = lab.get("coverage_state", {}).get(r["code"], r["code"])
        return {
            "library_status": rows(con, """
                select library_status as code, library_status_label as label, count(*) as n
                from dim_keyword_term group by 1, 2 order by n desc"""),
            "monitored_role": rows(con, """
                select operator_role as code, operator_role_label as label, count(*) as n
                from dim_keyword_term where is_monitored = 1 group by 1, 2 order by n desc"""),
            "brand_role": rows(con, """
                select brand_role as code, brand_role_label as label, count(*) as n
                from dim_keyword_term group by 1, 2 order by n desc"""),
            "position_state": pos,
            "coverage_state": cov,
            "evidence_type": rows(con, """
                select evidence_type as code, evidence_type_label as label, count(*) as n
                from fact_keyword_evidence group by 1, 2 order by n desc"""),
            "not_comparable_rows": one(con, """
                select count(*) from fact_keyword_market_snapshot
                where comparable_flag = 0 and comparable_block_reason is not null"""),
        }
    finally:
        con.close()


def demand_dimensions() -> list[dict[str, Any]]:
    con = connect()
    try:
        return rows(con, """
            select demand_dimension as value, demand_dimension as label,
                   count(*) as group_count
            from dim_keyword_group group by 1 order by group_count desc""")
    finally:
        con.close()


def focus_children() -> list[dict[str, Any]]:
    """30 个重点子体：身份来自产品包脊椎，目标与承接来自本包。"""
    con = connect()
    try:
        return rows(con, """
            select p.child_asin, c.parent_asin, c.style_no, c.colorway, c.size,
                   c.combination, c.product_lifecycle, c.category_rank, c.rating,
                   count(*)                                                   as pair_count,
                   sum(case when p.anchor_band is not null then 1 else 0 end)  as anchor_count,
                   g.product_goal_label, g.push_role_label,
                   a.absorb_state_label
            from dim_keyword_child_pair p
            join prod.dim_product_child c on c.child_asin = p.child_asin
            left join dim_keyword_child_goal g
                   on g.child_asin = p.child_asin and g.is_current = 1
            left join fact_keyword_child_absorb a on a.child_asin = p.child_asin
            group by p.child_asin
            order by anchor_count desc, pair_count desc, p.child_asin""")
    finally:
        con.close()


def spine_check() -> dict[str, Any]:
    """契约 G8：模块引用的子体键必须 100% 命中 342 脊椎。"""
    con = connect()
    try:
        total = one(con, "select count(distinct child_asin) from dim_keyword_child_pair")
        miss = one(con, """
            select count(distinct p.child_asin) from dim_keyword_child_pair p
            left join prod.dim_product_child c on c.child_asin = p.child_asin
            where c.child_asin is null""")
        goal_total = one(con, "select count(distinct child_asin) from dim_keyword_child_goal")
        goal_miss = one(con, """
            select count(distinct g.child_asin) from dim_keyword_child_goal g
            left join prod.dim_product_child c on c.child_asin = g.child_asin
            where c.child_asin is null""")
        return {"pair_children": total, "pair_missing": miss,
                "goal_children": goal_total, "goal_missing": goal_miss,
                "spine_size": one(con, "select count(*) from prod.dim_product_child"),
                "passed": miss == 0 and goal_miss == 0}
    finally:
        con.close()


def invalidate() -> None:
    """Compatibility hook; request reads are uncached to prevent mixed runs."""
    return None


# =========================================================== 页面三：子体盘点
# 全部按 child_asin 取，不做任何依赖参数的判断——那些在 compute.py 里。

def child_identity(con, asin: str) -> dict[str, Any] | None:
    r = rows(con, """
        select c.child_asin, c.parent_asin, c.product_name, c.style_name, c.style_no,
               c.colorway, c.size, c.combination, c.category, c.category_rank, c.rating,
               c.operations_group, c.operator, c.goods_status, c.product_lifecycle
        from prod.dim_product_child c where c.child_asin = ?""", (asin,))
    return r[0] if r else None


def child_goal(con, asin: str) -> list[dict[str, Any]]:
    """当前目标 + 历史版本。历史用来演「目标改过」，不只给当前一条。"""
    return rows(con, """
        select product_goal_label, push_role_label, product_lifecycle,
               effective_from, effective_to, is_current
        from dim_keyword_child_goal where child_asin = ?
        order by effective_from""", (asin,))


def child_absorb(con, asin: str) -> dict[str, Any] | None:
    r = rows(con, """
        select absorb_state_label, days_to_latest_order, decision_summary,
               suggested_replenishment_qty, projected_lost_sales_units,
               dynamic_safety_days, confidence_score, base_stockout_date,
               stress_stockout_date, latest_order_date
        from fact_keyword_child_absorb where child_asin = ?""", (asin,))
    return r[0] if r else None


def child_pairs(con, asin: str) -> list[dict[str, Any]]:
    """该子体的全部关键词关系 + 末日位置状态 + 词的身份与词组。"""
    return rows(con, """
        select p.pair_id, p.keyword_id, p.keyword, p.anchor_band, p.anchor_band_label,
               p.pair_shape_label, p.monitor_from, p.value_origin,
               t.keyword_cn, t.operator_role, t.operator_role_label,
               t.brand_role_label, t.library_status_label, t.primary_category,
               d.organic_rank, d.organic_page, d.organic_state,
               d.ad_rank, d.ad_placement, d.ad_state, d.coverage_state,
               d.collect_depth,
               m.monthly_search_volume, m.purchase_rate, m.aba_month_rank
        from dim_keyword_child_pair p
        join dim_keyword_term t on t.keyword_id = p.keyword_id
        left join fact_keyword_child_position_daily d
               on d.pair_id = p.pair_id and d.date = (
                    select max(date) from fact_keyword_child_position_daily)
        left join fact_keyword_market_snapshot m
               on m.keyword_id = p.keyword_id and m.source_code = 'kw3'
              and m.period_type = 'month' and m.period_index = 11
        where p.child_asin = ?
        order by t.operator_role, p.keyword""", (asin,))


def child_groups(con, asin: str) -> list[dict[str, Any]]:
    """覆盖结构的分组底表：该子体每个需求词组的关系数与分权。"""
    return rows(con, """
        select g.group_id, g.group_name, g.demand_dimension,
               g.member_count as library_member_count,
               b.keyword_id, b.dedup_weight, p.pair_id
        from dim_keyword_child_pair p
        join bridge_keyword_group b on b.keyword_id = p.keyword_id
        join dim_keyword_group g on g.group_id = b.group_id
        where p.child_asin = ?""", (asin,))


def group_monitored_totals(con) -> list[dict[str, Any]]:
    """每个词组里有多少监控词 —— 缺口 = 组内监控词 − 该子体已覆盖。"""
    return rows(con, """
        select g.group_id, g.group_name, g.demand_dimension,
               count(distinct b.keyword_id) as monitored_count,
               sum(b.dedup_weight)          as weighted_count
        from dim_keyword_group g
        join bridge_keyword_group b on b.group_id = g.group_id
        join dim_keyword_term t on t.keyword_id = b.keyword_id
        where t.is_monitored = 1
        group by g.group_id order by monitored_count desc""")


def child_position_series(con, asin: str) -> list[dict[str, Any]]:
    """182 天逐日位置。行数约 pair_count × 182，单子体最多 66×182≈12000 行。"""
    return rows(con, """
        select d.pair_id, p.keyword, d.date, d.organic_rank, d.organic_state,
               d.ad_rank, d.ad_state, d.coverage_state
        from fact_keyword_child_position_daily d
        join dim_keyword_child_pair p on p.pair_id = d.pair_id
        where d.child_asin = ? order by d.date""", (asin,))


def child_coverage_events(con, asin: str) -> list[dict[str, Any]]:
    return rows(con, """
        select event_id, keyword, event_type_label, from_date, to_date,
               from_rank, to_rank, is_core_keyword, continuity, label
        from fact_keyword_coverage_event where child_asin = ?
        order by to_date desc, event_id""", (asin,))


def child_evidence(con, asin: str) -> list[dict[str, Any]]:
    """注意不取 evidence_completeness 码值：complete / partial 都在禁词表里，
    只取已经映射好的中文标签，避免码值进载荷。"""
    return rows(con, """
        select evidence_id, keyword, evidence_type_label, priority, conclusion,
               main_basis, product_goal_label, push_role_label,
               inventory_limit_label, evidence_completeness_label,
               next_verification_label, competitor_verification_label,
               ref_market_event_ids, ref_coverage_event_ids, ref_position_date
        from fact_keyword_evidence where child_asin = ?
        order by priority, evidence_id""", (asin,))


def child_audits(con, asin: str) -> list[dict[str, Any]]:
    return rows(con, """
        select record_id, run_date, is_latest, library_scope, pair_count,
               organic_covered_count, ad_covered_count, both_covered_count,
               unconfirmed_count, best_organic_rank, median_organic_rank,
               product_goal_label, push_role_label, absorb_state_label,
               evidence_count, evidence_type_counts, rule_version
        from fact_keyword_audit_record where child_asin = ?
        order by run_date""", (asin,))


def child_market_events(con, asin: str) -> list[dict[str, Any]]:
    """该子体覆盖的词上的市场变化，用来解释「位置变了市场是否也在变」。"""
    return rows(con, """
        select distinct e.event_id, e.keyword, e.event_type_label, e.label,
               e.continuity_label, e.to_period_end, e.change_ratio
        from fact_keyword_market_change_event e
        join dim_keyword_child_pair p on p.keyword_id = e.keyword_id
        where p.child_asin = ? order by e.event_id""", (asin,))


def collect_fail_dates(con) -> list[str]:
    """整日采集失败的日期 —— 位置图上画成背景带，不占事件泳道。"""
    return [r["date"] for r in rows(con, """
        select date, count(*) as n from fact_keyword_child_position_daily
        where organic_state = 'collect_failed' group by date
        having n >= 100 order by date""")]


# ======================================================= 页面二：词库与深研

def library_summary(con) -> dict[str, Any]:
    """共享词库的范围与质量（方案 7.3 §4.3）。"""
    return {
        "total": one(con, "select count(*) from dim_keyword_term"),
        "monitored": one(con, "select count(*) from dim_keyword_term where is_monitored=1"),
        "alias_groups": one(con, """
            select count(distinct keyword_id) from dim_keyword_alias"""),
        "alias_rows": one(con, "select count(*) from dim_keyword_alias"),
        "variant_families": one(con, """
            select count(*) from dim_keyword_alias where alias_type='variant_family'"""),
        "brands": one(con, "select count(*) from dim_keyword_brand"),
        "competitor_brands": one(con, """
            select count(*) from dim_keyword_brand where brand_role='competitor_brand'"""),
        "first_seen": one(con, "select min(first_seen_date) from dim_keyword_term"),
        "last_updated": one(con, "select max(last_updated_date) from dim_keyword_term"),
        "role_confirmed": one(con, """
            select count(*) from dim_keyword_term where operator_role_confirmed=1"""),
    }


def group_structure(con) -> list[dict[str, Any]]:
    """需求词组与市场结构（方案 7.3 §4.4）。

    搜索量给两个口径：按 dedup_weight 分权的和不分权的。
    不分权那一列存在的意义是让页面能演「一词多组重复计入会多算多少」。
    """
    return rows(con, """
        select g.group_id, g.group_name, g.demand_dimension, g.member_count,
               count(distinct b.keyword_id)                            as term_count,
               sum(case when t.is_monitored=1 then 1 else 0 end)        as monitored_count,
               sum(coalesce(m.monthly_search_volume,0) * b.dedup_weight) as search_weighted,
               sum(coalesce(m.monthly_search_volume,0))                  as search_raw,
               sum(coalesce(m.monthly_purchase_volume,0) * b.dedup_weight) as purchase_weighted
        from dim_keyword_group g
        join bridge_keyword_group b on b.group_id = g.group_id
        join dim_keyword_term t on t.keyword_id = b.keyword_id
        left join fact_keyword_market_snapshot m
               on m.keyword_id = b.keyword_id and m.source_code='kw3'
              and m.period_type='month' and m.period_index=11
        group by g.group_id
        order by search_weighted desc""")


_TERM_LIST_SQL = """
    select t.keyword_id, t.keyword, t.keyword_cn, t.library_status_label,
           t.is_monitored, t.operator_role, t.operator_role_label,
           t.brand_role_label, t.matched_brand, t.primary_category,
           t.relevance, t.raw_variant_count,
           m.monthly_search_volume, m.monthly_purchase_volume, m.purchase_rate,
           m.aba_month_rank,
           w.product_count, w.demand_supply_ratio, w.ad_competitor_count,
           w.ppc_bid, w.click_share_top3, w.avg_price, w.rating,
           w.change_shape_label, w.comparable_flag, w.comparable_block_reason,
           a.product_count as alt_product_count,
           a.ad_competitor_count as alt_ad_competitor_count,
           a.click_share_top3 as alt_click_share_top3
    from dim_keyword_term t
    left join fact_keyword_market_snapshot m
           on m.keyword_id = t.keyword_id and m.source_code='kw3'
          and m.period_type='month' and m.period_index=11
    left join fact_keyword_market_snapshot w
           on w.keyword_id = t.keyword_id and w.source_code='kw3'
          and w.period_type='week' and w.period_index=25
    left join fact_keyword_market_snapshot a
           on a.keyword_id = t.keyword_id and a.source_code='kw2'
          and a.period_type='week'
"""


def term_list(con, statuses=None, dimension=None, role=None, q=None,
              limit: int = 200) -> tuple[list[dict[str, Any]], int]:
    where, args = [], []
    if statuses:
        where.append("t.library_status in (%s)" % ",".join("?" * len(statuses)))
        args += list(statuses)
    if role:
        where.append("t.operator_role = ?")
        args.append(role)
    if q:
        where.append("(t.keyword like ? or t.keyword_cn like ?)")
        args += ["%" + q + "%"] * 2
    if dimension:
        where.append("""t.keyword_id in (
            select b.keyword_id from bridge_keyword_group b
            join dim_keyword_group g on g.group_id=b.group_id
            where g.demand_dimension = ?)""")
        args.append(dimension)
    clause = (" where " + " and ".join(where)) if where else ""
    total = one(con, "select count(*) from dim_keyword_term t" + clause, tuple(args))
    sql = (_TERM_LIST_SQL + clause
           + " order by coalesce(m.monthly_search_volume,0) desc, t.keyword limit ?")
    return rows(con, sql, tuple(args) + (limit,)), total


def term_identity(con, keyword_id: str) -> dict[str, Any] | None:
    r = rows(con, """
        select keyword_id, keyword, keyword_raw, keyword_cn, alias_key, site,
               product_line, library_status_label, is_monitored, selection_bucket,
               primary_category, all_category_tags, category_tags_alt,
               matched_brand, brand_role_label, operator_role, operator_role_label,
               operator_role_confirmed, operator_role_seed_word, ac_recommended,
               relevance, category_path, traffic_word_type, raw_variant_count,
               first_seen_date, last_updated_date, source_files, value_origin
        from dim_keyword_term where keyword_id = ?""", (keyword_id,))
    return r[0] if r else None


def term_aliases(con, keyword_id: str) -> list[dict[str, Any]]:
    return rows(con, """
        select alias_text, alias_type_label, normalization_rule
        from dim_keyword_alias where keyword_id = ? order by alias_type, alias_text""",
                (keyword_id,))


def term_snapshots(con, keyword_id: str) -> list[dict[str, Any]]:
    """双频率全序列 + 第二来源末期一格。绝不把月搜索量折算成周。"""
    return rows(con, """
        select source_code, source_file, period_type, period_index,
               period_start, period_end, measure_definition, data_state_label,
               comparable_flag, comparable_block_reason, change_shape_label,
               value_origin,
               monthly_search_volume, monthly_purchase_volume, purchase_rate,
               aba_month_rank, impressions, clicks,
               aba_week_rank, product_count, demand_supply_ratio,
               ad_competitor_count, ppc_bid, suggested_bid_low, suggested_bid_high,
               title_density, spr, click_share_top3, conv_share_top3,
               avg_price, rating_count, rating
        from fact_keyword_market_snapshot where keyword_id = ?
        order by period_type, source_code, period_index""", (keyword_id,))


def term_head_asins(con, keyword_id: str) -> list[dict[str, Any]]:
    return rows(con, """
        select period_end, rank_slot, asin, click_share, conversion_share,
               is_own_asin, value_origin
        from fact_keyword_head_asin where keyword_id = ?
        order by period_end, rank_slot""", (keyword_id,))


def term_market_events(con, keyword_id: str) -> list[dict[str, Any]]:
    return rows(con, """
        select event_type_label, period_type, from_period_end, to_period_end,
               from_value, to_value, change_ratio, continuity_label, label
        from fact_keyword_market_change_event where keyword_id = ?
        order by period_type, event_id""", (keyword_id,))


def term_groups(con, keyword_id: str) -> list[dict[str, Any]]:
    return rows(con, """
        select g.group_name, g.demand_dimension, b.dedup_weight, g.member_count
        from bridge_keyword_group b join dim_keyword_group g on g.group_id=b.group_id
        where b.keyword_id = ? order by g.demand_dimension""", (keyword_id,))


def term_attributes(con, keyword_id: str) -> list[dict[str, Any]]:
    return rows(con, """
        select attribute_dimension, source_file, is_primary
        from bridge_keyword_attribute where keyword_id = ?
        order by is_primary desc, source_file, attribute_dimension""", (keyword_id,))


def term_child_relations(con, keyword_id: str) -> list[dict[str, Any]]:
    """关键词 × 子ASIN 关系区（方案 7.3 §4.7）。绑定子体后才出产品判断。"""
    return rows(con, """
        select p.pair_id, p.child_asin, p.anchor_band_label, p.pair_shape_label,
               p.monitor_from,
               c.parent_asin, c.style_no, c.colorway, c.size,
               g.product_goal_label, g.push_role_label,
               ab.absorb_state_label,
               d.organic_rank, d.organic_state, d.ad_rank, d.ad_state,
               d.coverage_state
        from dim_keyword_child_pair p
        join prod.dim_product_child c on c.child_asin = p.child_asin
        left join dim_keyword_child_goal g
               on g.child_asin = p.child_asin and g.is_current = 1
        left join fact_keyword_child_absorb ab on ab.child_asin = p.child_asin
        left join fact_keyword_child_position_daily d
               on d.pair_id = p.pair_id and d.date = (
                    select max(date) from fact_keyword_child_position_daily)
        where p.keyword_id = ? order by p.child_asin""", (keyword_id,))


def term_evidence(con, keyword_id: str) -> list[dict[str, Any]]:
    return rows(con, """
        select child_asin, evidence_type_label, priority, conclusion, main_basis,
               product_goal_label, inventory_limit_label,
               evidence_completeness_label, next_verification_label,
               competitor_verification_label
        from fact_keyword_evidence where keyword_id = ?
        order by priority""", (keyword_id,))


# ========================================================== 页面一：动态与总览

def daily_reports(con, limit: int = 14) -> list[dict[str, Any]]:
    """动态关键词日报（方案 7.3 §3.4）。五问五答 + 可下钻的引用。"""
    return rows(con, """
        select report_date, site, product_line, compare_period,
               traffic_proxy_metric, traffic_proxy_value, traffic_proxy_delta,
               q1_traffic_result, q2_main_movers, q3_core_coverage_change,
               q4_new_signals, q5_priority_next,
               priority_evidence_ids, coverage_event_ids
        from fact_keyword_daily_report order by report_date desc limit ?""", (limit,))


def market_events_by_group(con) -> list[dict[str, Any]]:
    """市场变化按需求词组汇总（方案 7.3 §3.5）。

    带 dedup_weight，让页面能按权分摊，避免一词多组重复计入。
    """
    return rows(con, """
        select g.group_id, g.group_name, g.demand_dimension,
               e.event_type, e.event_type_label, e.continuity, e.continuity_label,
               e.keyword, e.keyword_id, e.period_type, e.change_ratio,
               e.from_value, e.to_value, e.label, e.to_period_end,
               b.dedup_weight,
               m.monthly_search_volume
        from fact_keyword_market_change_event e
        join bridge_keyword_group b on b.keyword_id = e.keyword_id
        join dim_keyword_group g on g.group_id = b.group_id
        left join fact_keyword_market_snapshot m
               on m.keyword_id = e.keyword_id and m.source_code='kw3'
              and m.period_type='month' and m.period_index=11
        order by g.demand_dimension, e.event_id""")


def core_coverage_events(con) -> list[dict[str, Any]]:
    """自有核心词的覆盖与位置变化（方案 7.3 §3.6）。只陈述事实，不给广告结论。"""
    return rows(con, """
        select e.event_id, e.keyword, e.keyword_id, e.child_asin,
               e.event_type, e.event_type_label, e.from_date, e.to_date,
               e.from_rank, e.to_rank, e.is_core_keyword, e.continuity, e.label,
               t.operator_role_label,
               g.push_role_label, g.product_goal_label,
               m.monthly_search_volume
        from fact_keyword_coverage_event e
        join dim_keyword_term t on t.keyword_id = e.keyword_id
        left join dim_keyword_child_goal g
               on g.child_asin = e.child_asin and g.is_current = 1
        left join fact_keyword_market_snapshot m
               on m.keyword_id = e.keyword_id and m.source_code='kw3'
              and m.period_type='month' and m.period_index=11
        order by e.to_date desc, e.event_id""")


def evidence_all(con) -> list[dict[str, Any]]:
    """全范围证据，供优先列表跨子体排序（方案 7.3 §3.7）。"""
    return rows(con, """
        select e.evidence_id, e.keyword, e.keyword_id, e.child_asin,
               e.evidence_type, e.evidence_type_label, e.priority,
               e.conclusion, e.main_basis, e.product_goal_label, e.push_role_label,
               e.inventory_limit_label, e.evidence_completeness_label,
               e.next_verification_label, e.competitor_verification_label,
               m.monthly_search_volume
        from fact_keyword_evidence e
        left join fact_keyword_market_snapshot m
               on m.keyword_id = e.keyword_id and m.source_code='kw3'
              and m.period_type='month' and m.period_index=11""")


def scope_status(con) -> dict[str, Any]:
    """数据范围与数据状态（方案 7.3 §3.3）。缺失时要明确指出受影响范围。"""
    return {
        "children_with_relations": one(con, """
            select count(distinct child_asin) from dim_keyword_child_pair"""),
        "children_with_goal": one(con, """
            select count(distinct child_asin) from dim_keyword_child_goal
            where is_current = 1"""),
        "children_with_absorb": one(con, """
            select count(*) from fact_keyword_child_absorb"""),
        "children_with_evidence": one(con, """
            select count(distinct child_asin) from fact_keyword_evidence"""),
        "terms_with_relations": one(con, """
            select count(distinct keyword_id) from dim_keyword_child_pair"""),
        # 只数主来源 kw3 的不可比行。第二来源 kw2 天然 comparable_flag=0
        # （它只有当期一格、且与 kw3 口径不同），把它算进来会把「口径变更的词」
        # 从 15 个虚报成 880 个 —— 那是「有第二来源的词数」，完全另一回事。
        "not_comparable_terms": one(con, """
            select count(distinct keyword_id) from fact_keyword_market_snapshot
            where source_code = 'kw3' and comparable_flag = 0
              and comparable_block_reason is not null and period_index > 0"""),
        "second_source_terms": one(con, """
            select count(distinct keyword_id) from fact_keyword_market_snapshot
            where source_code = 'kw2'"""),
        "insufficient_terms": one(con, """
            select count(distinct keyword_id) from fact_keyword_market_snapshot
            where source_code = 'kw3' and data_state = 'no_data'"""),
    }
