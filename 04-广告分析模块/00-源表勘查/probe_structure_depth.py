#!/usr/bin/env python3
"""核查交集子体的广告结构厚度。

$121k 花费却只挂 1 个广告对象很可疑：要么角色过滤太窄，
要么 fact_product_ad_spend 的花费和 bridge 的对象集不同源。
这个结论决定演示对象怎么选、要不要构造。
"""
import sqlite3

ADS = ('/Users/linsen/BAM/04-广告分析模块/'
       '02-数据构建/v0.2.0/advertising_demo.sqlite')
PROD = ('/Users/linsen/BAM/02-产品销售库存模块/'
        '02-数据构建/v0.3.0/bamboocool_product_sales_inventory_v0.3.0.sqlite')
TARGETS = ['B088WF1PRW', 'B0B3LWGP36', 'B0BVM5S1JR', 'B0B3MBYGR5',
           'B0B6ZT7W64']


def main() -> None:
    cx = sqlite3.connect('file:%s?mode=ro' % ADS, uri=True)
    cx.row_factory = sqlite3.Row

    print('=== 各子体按 relation_role 的广告对象数 ===')
    roles = [r[0] for r in cx.execute(
        "select distinct relation_role from bridge_ad_object_product"
        " order by 1")]
    print('%-13s %s' % ('child_asin', '  '.join('%-19s' % x for x in roles)))
    for a in TARGETS:
        cells = []
        for role in roles:
            n = cx.execute(
                "select count(distinct ad_object_id)"
                " from bridge_ad_object_product"
                " where child_asin=? and relation_role=?", (a, role)
            ).fetchone()[0]
            cells.append('%-19s' % n)
        print('%-13s %s' % (a, '  '.join(cells)))

    print('\n=== 有月度事实的对象数（全角色并集）与花费口径对照 ===')
    for a in TARGETS:
        oids = [r[0] for r in cx.execute(
            "select distinct ad_object_id from bridge_ad_object_product"
            " where child_asin=?", (a,))]
        if not oids:
            print('  %-13s 无任何关联对象' % a)
            continue
        ph = ','.join('?' * len(oids))
        f = cx.execute(
            "select count(*) n, sum(spend) sp, sum(ad_sales) sa,"
            " sum(clicks) ck from fact_ad_performance"
            " where ad_object_id in (%s)"
            " and metric_basis='report_month_total'" % ph,
            tuple(oids)).fetchone()
        by_level = cx.execute(
            "select o.object_level lv, count(distinct o.ad_object_id) n"
            " from dim_ad_object o where o.ad_object_id in (%s)"
            " group by lv" % ph, tuple(oids)).fetchall()
        pspend = cx.execute(
            "select sum(spend) s from fact_product_ad_spend"
            " where child_asin=?", (a,)).fetchone()['s']
        print('  %-13s 关联对象 %3d（%s）· 有月事实 %3d 行'
              ' · 事实花费 %10s · 推广商品报表花费 %10s'
              % (a, len(oids),
                 ' '.join('%s=%d' % (r['lv'], r['n']) for r in by_level),
                 f['n'] or 0,
                 '--' if f['sp'] is None else format(round(f['sp']), ','),
                 '--' if pspend is None else format(round(pspend), ',')))

    print('\n=== 用全角色并集重算：交集里结构最厚的 12 个 ===')
    cx.execute("attach database ? as prod", ("file:%s?mode=ro" % PROD,))
    rows = cx.execute("""
        select b.child_asin,
               count(distinct b.ad_object_id) objs,
               count(distinct case when o.object_level='AD_GROUP'
                     then b.ad_object_id end) groups_,
               count(distinct o.campaign_id) camps,
               count(distinct o.ad_type) types
        from bridge_ad_object_product b
        join dim_ad_object o on o.ad_object_id = b.ad_object_id
        join prod.dim_product_child pc on pc.child_asin = b.child_asin
        group by b.child_asin
        order by objs desc limit 12""").fetchall()
    print('%-13s %6s %8s %8s %6s %11s %-20s' % (
        'child_asin', '对象', '广告组', 'Campaign', '类型', '广告花费', '库存决策'))
    for r in rows:
        extra = cx.execute(
            "select round(sum(spend)) s from fact_product_ad_spend"
            " where child_asin=?", (r['child_asin'],)).fetchone()['s']
        risk = cx.execute(
            "select base_risk_status r from prod.fact_child_inventory_decision"
            " where child_asin=?", (r['child_asin'],)).fetchone()
        print('%-13s %6d %8d %8d %6d %11s %-20s' % (
            r['child_asin'], r['objs'], r['groups_'], r['camps'], r['types'],
            '--' if extra is None else format(int(extra), ','),
            (risk['r'] if risk else '--') or '--'))
    cx.close()


if __name__ == '__main__':
    main()
