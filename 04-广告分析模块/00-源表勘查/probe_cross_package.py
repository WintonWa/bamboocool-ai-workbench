#!/usr/bin/env python3
"""跨包勘查：确认页面二要接的字段能不能真接上。

三件事：
  1. B088WF1PRW（页面二演示对象）在不在产品包里 → 决定第一类是接还是造
  2. 要接的每张表的真实列名与该子体的真实取值
  3. 广告包里 placement / search_term_share 对该子体的覆盖情况
"""
import os
import sqlite3

ADS = ('/Users/linsen/BAM/04-广告分析模块/'
       '02-数据构建/v0.2.0/advertising_demo.sqlite')
PROD = ('/Users/linsen/BAM/02-产品销售库存模块/'
        '02-数据构建/v0.3.0/bamboocool_product_sales_inventory_v0.3.0.sqlite')
ASIN = 'B088WF1PRW'


def cx_ro(path: str) -> sqlite3.Connection:
    c = sqlite3.connect('file:%s?mode=ro' % path, uri=True)
    c.row_factory = sqlite3.Row
    return c


def show(cx, sql, params=(), limit=6, title=''):
    if title:
        print('  ' + title)
    try:
        rows = list(cx.execute(sql, params))
    except sqlite3.Error as e:
        print('    查询失败: %s' % e)
        return []
    if not rows:
        print('    （无行）')
        return []
    for r in rows[:limit]:
        print('    ' + ' | '.join(
            '%s=%s' % (k, r[k]) for k in r.keys()
            if r[k] is not None))
    if len(rows) > limit:
        print('    …共 %d 行' % len(rows))
    return rows


def main() -> None:
    print('=== 0. ATTACH 可行性 ===')
    if not os.path.isfile(PROD):
        print('产品包不存在: %s' % PROD)
        return
    a = cx_ro(ADS)
    a.execute("attach database ? as prod", ("file:%s?mode=ro" % PROD,))
    print('  ATTACH 成功（只读跨包 join 可行）')

    print('\n=== 1. 演示对象在不在产品包 ===')
    n = a.execute("select count(*) from prod.dim_product_child"
                  " where child_asin=?", (ASIN,)).fetchone()[0]
    print('  %s 在产品包: %s' % (ASIN, '是' if n else '否'))
    both = a.execute(
        "select count(*) from dim_product_child ac"
        " join prod.dim_product_child pc using(child_asin)").fetchone()[0]
    print('  两包子体交集: %d 个（广告 %d / 产品 %d）' % (
        both,
        a.execute("select count(*) from dim_product_child").fetchone()[0],
        a.execute("select count(*) from prod.dim_product_child").fetchone()[0]))
    if not n:
        print('\n  交集里花费最高的候选（可换演示对象）:')
        show(a, "select s.child_asin, round(sum(s.spend)) spend"
                " from fact_product_ad_spend s"
                " join prod.dim_product_child pc using(child_asin)"
                " where s.child_asin is not null"
                " group by s.child_asin order by spend desc", limit=8)

    print('\n=== 2. 产品包各表对该子体（或交集样本）的取值 ===')
    tgt = ASIN if n else (a.execute(
        "select s.child_asin from fact_product_ad_spend s"
        " join prod.dim_product_child pc using(child_asin)"
        " where s.child_asin is not null group by s.child_asin"
        " order by sum(s.spend) desc limit 1").fetchone() or [None])[0]
    print('  取样对象: %s' % tgt)
    if tgt:
        show(a, "select child_asin, parent_asin, product_lifecycle, sku"
                " from prod.dim_product_child where child_asin=?", (tgt,),
             title='dim_product_child 生命周期')
        show(a, "select * from prod.fact_sales_window where child_asin=?",
             (tgt,), title='fact_sales_window 六窗口销量趋势')
        show(a, "select * from prod.fact_child_inventory_decision"
                " where child_asin=?", (tgt,),
             title='fact_child_inventory_decision 断货日与建议')
        show(a, "select date, closing_fba_sellable, coverage_days,"
                " stockout_flag from prod.fact_child_inventory_daily"
                " where child_asin=? order by date desc limit 3", (tgt,),
             title='fact_child_inventory_daily 最近三天')
        show(a, "select date, promotion_type, promotion_status, promotion_id"
                " from prod.fact_child_promotion_daily"
                " where child_asin=? and promotion_type<>'none'"
                " order by date desc limit 4", (tgt,),
             title='fact_child_promotion_daily 历史促销')
        show(a, "select date, promotion_type, promotion_id"
                " from prod.plan_child_promotion_daily"
                " where child_asin=? and promotion_type<>'none'"
                " order by date limit 4", (tgt,),
             title='plan_child_promotion_daily 未来计划促销')
        show(a, "select supply_event_id, eta_earliest, eta_latest,"
                " transport_mode, quantity from prod.bridge_supply_event_child"
                " where child_asin=? order by eta_earliest limit 4", (tgt,),
             title='bridge_supply_event_child 在途到货')

    print('\n=== 3. 广告包里页面二还没用的两张表 ===')
    oids = [r[0] for r in a.execute(
        "select distinct ad_object_id from bridge_ad_object_product"
        " where child_asin=? and relation_role in"
        " ('promoted_asin','positive_spend_asin')", (ASIN,))]
    print('  该子体广告对象 %d 个' % len(oids))
    ph = ','.join('?' * len(oids)) if oids else "''"
    show(a, "select placement, bid_strategy, impressions, clicks, spend,"
            " acos, roas from fact_placement limit 5",
         title='fact_placement 结构（Campaign 级）')
    if oids:
        show(a, "select count(*) n, count(distinct search_term) terms,"
                " count(distinct campaign_name) camps"
                " from fact_search_term_share", title='fact_search_term_share 总量')
        cols = [r[1] for r in a.execute(
            "pragma table_info(fact_search_term_share)")]
        print('    列: %s' % ', '.join(cols))
    a.close()


if __name__ == '__main__':
    main()
