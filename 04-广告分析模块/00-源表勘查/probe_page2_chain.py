#!/usr/bin/env python3
"""勘查广告 v0.2.0 里页面二决策链相关的表：结构、行数、实际取值。
只读，不写库。目的是把 Agent 输入/输出契约建立在真列真值上，不靠记忆。"""
import sqlite3
import sys

DB = ('/Users/linsen/BAM/04-广告分析模块/'
      '02-数据构建/v0.2.0/advertising_demo.sqlite')

# 页面二这条链相关的表（名字里带这些词的都捞出来）
KEYS = ('decision', 'evidence', 'task', 'diagnos', 'recommend', 'proposal',
        'structure', 'review', 'followup', 'action', 'context', 'lineage')


def main() -> None:
    cx = sqlite3.connect('file:%s?mode=ro' % DB, uri=True)
    cx.row_factory = sqlite3.Row
    names = [r[0] for r in cx.execute(
        "select name from sqlite_master where type='table' order by name")]
    print('=== 全部 %d 张表 ===' % len(names))
    print('  ' + ' · '.join(names))

    hit = [n for n in names if any(k in n.lower() for k in KEYS)]
    print('\n=== 决策链相关 %d 张 ===' % len(hit))
    for t in hit:
        n = cx.execute('select count(*) from "%s"' % t).fetchone()[0]
        cols = [(r['name'], r['type']) for r in
                cx.execute('pragma table_info("%s")' % t)]
        print('\n--- %s  (%d 行, %d 列) ---' % (t, n, len(cols)))
        print('    列: ' + ', '.join('%s:%s' % (c, ty or '?') for c, ty in cols))
        if n:
            row = cx.execute('select * from "%s" limit 1' % t).fetchone()
            for c, _ in cols:
                v = row[c]
                s = '' if v is None else str(v)
                if len(s) > 88:
                    s = s[:88] + '…(%d字)' % len(str(v))
                print('      %-30s = %s' % (c, 'NULL' if v is None else s))
    cx.close()


if __name__ == '__main__':
    sys.exit(main())
