#!/usr/bin/env python3
"""B0B3LWGP36 的广告结构树 + 真实指标，作为构造决策链的事实底座。

按角色分开看：
  推广角色（promoted / positive_spend / target / matched）→ 板块5 的结构树
  purchased_asin → 「成交归属但非推广」，方案 3.2 要求单独识别
"""
import sqlite3

ADS = ('/Users/linsen/BAM/04-广告分析模块/'
       '02-数据构建/v0.2.0/advertising_demo.sqlite')
A = 'B0B3LWGP36'
PROMO = ('promoted_asin', 'positive_spend_asin', 'target_asin', 'matched_asin')


def main() -> None:
    cx = sqlite3.connect('file:%s?mode=ro' % ADS, uri=True)
    cx.row_factory = sqlite3.Row

    ph = ','.join('?' * len(PROMO))
    rows = cx.execute("""
        select distinct b.relation_role, b.attribution_scope,
               o.ad_object_id, o.object_level, o.ad_type, o.campaign_id,
               o.campaign_name, o.ad_group_name, o.target_text, o.match_type,
               o.parent_ad_object_id,
               f.spend, f.ad_sales, f.acos, f.roas, f.clicks, f.orders,
               f.impressions, f.attribution_days
        from bridge_ad_object_product b
        join dim_ad_object o on o.ad_object_id = b.ad_object_id
        left join fact_ad_performance f on f.ad_object_id = o.ad_object_id
             and f.metric_basis='report_month_total'
        where b.child_asin=? and b.relation_role in (%s)
        order by f.spend desc""" % ph, (A,) + PROMO).fetchall()
    print('=== 推广角色的对象 %d 个 ===' % len(rows))
    for r in rows:
        print('  %-9s %-13s %-4s %-9s spend=%-10s acos=%-7s 组=%s'
              % (r['object_level'], r['relation_role'][:13], r['ad_type'],
                 (r['campaign_name'] or '')[:9],
                 '--' if r['spend'] is None else round(r['spend'], 2),
                 '--' if r['acos'] is None else '%.1f%%' % (r['acos'] * 100),
                 (r['ad_group_name'] or r['target_text'] or '')[:34]))

    # 这些组下面挂的 Target
    gids = [r['ad_object_id'] for r in rows if r['object_level'] == 'AD_GROUP']
    if gids:
        gp = ','.join('?' * len(gids))
        tg = cx.execute("""
            select o.ad_object_id, o.parent_ad_object_id, o.target_text,
                   o.match_type, o.key_kind, f.spend, f.acos, f.clicks,
                   f.orders
            from dim_ad_object o
            left join fact_ad_performance f on f.ad_object_id=o.ad_object_id
                 and f.metric_basis='report_month_total'
            where o.parent_ad_object_id in (%s)
            order by f.spend desc""" % gp, tuple(gids)).fetchall()
        print('\n=== 这些组下挂的投放对象 %d 个 ===' % len(tg))
        for t in tg[:14]:
            print('  %-30s %-8s %-10s spend=%-9s acos=%s'
                  % ((t['target_text'] or '')[:30], t['match_type'] or '--',
                     t['key_kind'] or '--',
                     '--' if t['spend'] is None else round(t['spend'], 2),
                     '--' if t['acos'] is None else '%.1f%%' % (t['acos']*100)))
        if len(tg) > 14:
            print('  …共 %d 个' % len(tg))

    pur = cx.execute("""
        select count(distinct b.ad_object_id) n, sum(f.spend) sp,
               sum(f.ad_sales) sa
        from bridge_ad_object_product b
        left join fact_ad_performance f on f.ad_object_id=b.ad_object_id
             and f.metric_basis='report_month_total'
        where b.child_asin=? and b.relation_role='purchased_asin'
          and b.ad_object_id not in (
            select ad_object_id from bridge_ad_object_product
            where child_asin=? and relation_role in (%s))""" % ph,
        (A, A) + PROMO).fetchone()
    print('\n=== 成交归属但非推广（方案 3.2）===')
    print('  %d 个广告对象带来了这个子体的成交，但它们推的不是它'
          % (pur['n'] or 0))
    print('  这些对象合计花费 %s，广告销售额 %s（含推别的 ASIN 的部分，'
          '不能全归当前子体）'
          % ('--' if pur['sp'] is None else format(round(pur['sp']), ','),
             '--' if pur['sa'] is None else format(round(pur['sa']), ',')))

    # 搜索词份额里这些 Campaign 的词
    cnames = sorted({r['campaign_name'] for r in rows if r['campaign_name']})
    if cnames:
        cp = ','.join('?' * len(cnames))
        st = cx.execute("""
            select search_term, target_text, match_type, impression_rank,
                   impression_share, impressions, clicks, spend, ad_sales
            from fact_search_term_share where campaign_name in (%s)
            order by impressions desc limit 8""" % cp, tuple(cnames)).fetchall()
        print('\n=== 这些 Campaign 的搜索词份额（真实，页面二还没用）===')
        for s in st:
            print('  %-26s rank=%-4s share=%-8s imp=%-7s clicks=%-5s'
                  % ((s['search_term'] or '')[:26], s['impression_rank'],
                     '--' if s['impression_share'] is None
                     else '%.2f%%' % (s['impression_share'] * 100),
                     s['impressions'], s['clicks']))
    cx.close()


if __name__ == '__main__':
    main()
