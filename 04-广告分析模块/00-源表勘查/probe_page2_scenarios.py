#!/usr/bin/env python3
"""从 188 个交集子体里挑演示对象，要求场景互不相同。

页面二要能演出不同处境（库存受限 / 效率下滑 / 位置丢失 / 结构缺口 / 健康），
不能只有一种。所以按真实数据给每个候选打上场景标记再挑。
"""
import json
import sqlite3

ADS = ('/Users/linsen/BAM/04-广告分析模块/'
       '02-数据构建/v0.2.0/advertising_demo.sqlite')
PROD = ('/Users/linsen/BAM/02-产品销售库存模块/'
        '02-数据构建/v0.3.0/bamboocool_product_sales_inventory_v0.3.0.sqlite')


def main() -> None:
    cx = sqlite3.connect('file:%s?mode=ro' % ADS, uri=True)
    cx.row_factory = sqlite3.Row
    cx.execute("attach database ? as prod", ("file:%s?mode=ro" % PROD,))

    rows = list(cx.execute("""
        select s.child_asin,
               round(sum(s.spend)) ad_spend,
               pc.parent_asin, pc.product_lifecycle,
               w.daily_avg_3d, w.daily_avg_7d, w.daily_avg_30d,
               w.daily_avg_90d, w.units_30d,
               d.base_risk_status, d.safety_breach_date,
               d.base_stockout_date, d.stress_stockout_date,
               d.suggested_replenishment_qty, d.dynamic_safety_days,
               d.confidence_score
        from fact_product_ad_spend s
        join prod.dim_product_child pc using(child_asin)
        left join prod.fact_sales_window w on w.child_asin = s.child_asin
        left join prod.fact_child_inventory_decision d
               on d.child_asin = s.child_asin
        where s.child_asin is not null
        group by s.child_asin
        order by ad_spend desc
        limit 40"""))

    # 每个候选：广告对象数、是否有共享、当月 ACoS、环比方向
    print('%-13s %9s %4s %6s %7s %-22s %8s %6s  %s' % (
        'child_asin', '广告花费', '对象', '趋势', 'ACoS', '库存决策',
        '断货日', '置信', '生命周期'))
    print('-' * 128)
    picks = []
    for r in rows:
        oids = [x[0] for x in cx.execute(
            "select distinct ad_object_id from bridge_ad_object_product"
            " where child_asin=? and relation_role in"
            " ('promoted_asin','positive_spend_asin')", (r['child_asin'],))]
        if not oids:
            continue
        ph = ','.join('?' * len(oids))
        f = cx.execute(
            "select sum(spend) sp, sum(ad_sales) sa, sum(clicks) ck,"
            " sum(orders) od from fact_ad_performance"
            " where ad_object_id in (%s)"
            " and metric_basis='report_month_total'" % ph,
            tuple(oids)).fetchone()
        acos = (f['sp'] / f['sa']) if (f['sa'] or 0) > 0 else None
        a3, a90 = r['daily_avg_3d'], r['daily_avg_90d']
        trend = None if not (a3 and a90) else (a3 / a90 - 1)
        picks.append({
            'child_asin': r['child_asin'],
            'ad_spend': r['ad_spend'],
            'objects': len(oids),
            'trend_3d_vs_90d': trend,
            'acos': acos,
            'risk': r['base_risk_status'],
            'stockout': r['stress_stockout_date'] or r['base_stockout_date'],
            'safety_breach': r['safety_breach_date'],
            'confidence': r['confidence_score'],
            'lifecycle': r['product_lifecycle'],
            'units_30d': r['units_30d'],
            'suggest_qty': r['suggested_replenishment_qty'],
            'safety_days': r['dynamic_safety_days'],
            'parent': r['parent_asin'],
        })
        print('%-13s %9s %4d %6s %7s %-22s %8s %6s  %s' % (
            r['child_asin'], format(int(r['ad_spend']), ','), len(oids),
            '--' if trend is None else '%+.0f%%' % (trend * 100),
            '--' if acos is None else '%.1f%%' % (acos * 100),
            r['base_risk_status'] or '--',
            (r['stress_stockout_date'] or r['base_stockout_date'] or '--')[:10],
            '--' if r['confidence_score'] is None
            else '%.2f' % r['confidence_score'],
            r['product_lifecycle'] or '--'))

    # 促销与关键词覆盖情况
    print('\n=== 前 8 名的促销与关键词证据可用性 ===')
    for p in picks[:8]:
        a = p['child_asin']
        hist = cx.execute(
            "select count(distinct promotion_id) n from"
            " prod.fact_child_promotion_daily where child_asin=?"
            " and promotion_type<>'none'", (a,)).fetchone()[0]
        plan = cx.execute(
            "select count(distinct promotion_id) n from"
            " prod.plan_child_promotion_daily where child_asin=?"
            " and promotion_type<>'none'", (a,)).fetchone()[0]
        sup = cx.execute(
            "select count(*) n from prod.bridge_supply_event_child"
            " where child_asin=?", (a,)).fetchone()[0]
        # 该子体的广告对象里有多少是共享的
        sh = cx.execute(
            "select count(*) n from (select ad_object_id from"
            " bridge_ad_object_product where child_asin=?"
            " and relation_role='promoted_asin') t"
            " where (select count(distinct child_asin) from"
            " bridge_ad_object_product b where b.ad_object_id=t.ad_object_id"
            " and b.relation_role='promoted_asin') > 1", (a,)).fetchone()[0]
        print('  %-13s 历史促销 %2d 个 · 计划促销 %2d 个 · 到货批次 %2d'
              ' · 共享对象 %2d / %2d'
              % (a, hist, plan, sup, sh, p['objects']))

    out = ('/Users/linsen/BAM/04-广告分析模块/'
           '00-源表勘查/page2_candidates.json')
    with open(out, 'w', encoding='utf-8') as fh:
        json.dump(picks, fh, ensure_ascii=False, indent=1)
    print('\n候选明细已写 %s（%d 个）' % (out, len(picks)))
    cx.close()


if __name__ == '__main__':
    main()
