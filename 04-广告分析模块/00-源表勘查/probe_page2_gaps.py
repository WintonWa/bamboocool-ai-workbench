#!/usr/bin/env python3
"""核实页面二各板块缺的字段，到底是数据里没有，还是我没接。

不能把「我没做」混进「数据没有」——所以逐个字段去两个数据包里找。
"""
import os
import sqlite3

ADS = ('/Users/linsen/BAM/04-广告分析模块/'
       '02-数据构建/v0.2.0/advertising_demo.sqlite')
PROD = ('/Users/linsen/BAM/02-产品销售库存模块/'
        '02-数据构建/v0.3.0')


def tables(db: str) -> dict:
    cx = sqlite3.connect('file:%s?mode=ro' % db, uri=True)
    out = {}
    for (t,) in cx.execute(
            "select name from sqlite_master where type='table'"):
        cols = [r[1] for r in cx.execute('pragma table_info("%s")' % t)]
        n = cx.execute('select count(*) from "%s"' % t).fetchone()[0]
        out[t] = (n, cols)
    cx.close()
    return out


def find(db_tables: dict, *keys) -> list:
    """在所有表的列名里找关键词"""
    hits = []
    for t, (n, cols) in sorted(db_tables.items()):
        for c in cols:
            if any(k in c.lower() for k in keys):
                hits.append('%s.%s (%d行)' % (t, c, n))
    return hits


def main() -> None:
    ads = tables(ADS)
    print('=== 广告包 v0.2.0：%d 张表 ===' % len(ads))

    probes = [
        ('产品阶段 / 生命周期', ('lifecycle', 'stage', 'phase')),
        ('产品定位', ('position', 'role', 'tier')),
        ('销量趋势', ('trend', 'growth')),
        ('关键业务事件 BD/促销/库龄', ('promotion', 'deal', 'coupon',
                                'event', 'age_')),
        ('自然位置', ('organic', 'natural')),
        ('广告位置', ('placement', 'top_of_search', 'rank')),
        ('关键词与产品匹配度', ('match', 'relevan')),
        ('搜索词份额', ('share',)),
        ('结构问题标注', ('gap', 'duplicate', 'overlap', 'conflict')),
        ('成本/流量/库存边界配置', ('threshold', 'limit', 'cap', 'target_')),
    ]
    for label, keys in probes:
        h = find(ads, *keys)
        print('\n%-26s %s' % (label, ('无' if not h else '')))
        for x in h[:8]:
            print('    %s' % x)

    print('\n\n=== 产品包 v0.3.0 ===')
    if not os.path.isdir(PROD):
        print('目录不存在: %s' % PROD)
        return
    dbs = [f for f in os.listdir(PROD) if f.endswith('.sqlite')]
    if not dbs:
        print('无 sqlite: %s' % os.listdir(PROD)[:8])
        return
    p = os.path.join(PROD, dbs[0])
    prod = tables(p)
    print('%s：%d 张表' % (dbs[0], len(prod)))
    for label, keys in [
            ('产品阶段 / 生命周期', ('lifecycle', 'stage', 'phase')),
            ('销量趋势', ('trend', 'growth', 'daily_avg')),
            ('BD / 促销 / Coupon', ('promotion', 'deal', 'coupon')),
            ('库龄', ('age_', 'aged')),
            ('产品目标', ('goal', 'objective')),
            ('预计缺货 / 到货', ('stockout', 'eta', 'inbound', 'supply')),
    ]:
        h = find(prod, *keys)
        print('\n%-26s %s' % (label, ('无' if not h else '')))
        for x in h[:8]:
            print('    %s' % x)


if __name__ == '__main__':
    main()
