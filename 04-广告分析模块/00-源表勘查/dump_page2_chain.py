#!/usr/bin/env python3
"""把页面二决策链的全部行完整打出来（每张表只有 2-9 行）。
这是前端要渲染的真数据，也是 Agent 输出契约的实际形状。"""
import json
import sqlite3
import sys

DB = ('/Users/linsen/BAM/04-广告分析模块/'
      '02-数据构建/v0.2.0/advertising_demo.sqlite')

CHAIN = [
    ('fact_decision_context', 'decision_at'),
    ('fact_decision_evidence', 'evidence_id'),
    ('fact_required_ad_task', 'task_id'),
    ('bridge_task_ad_object', 'mapping_id'),
    ('fact_ad_diagnosis', 'priority'),
    ('fact_ad_recommendation', 'recommendation_id'),
    ('fact_ad_decision_event', 'occurred_at'),
    ('fact_review_feedback', 'review_window'),
]
# 太长的 JSON 列只看键，不铺全文
TRIM = {'baseline_metrics', 'observed_metrics', 'evidence_payload',
        'original_recommendation_snapshot'}


def fmt(col: str, v: object) -> str:
    if v is None:
        return 'NULL'
    s = str(v)
    if col in TRIM and s.startswith('{'):
        try:
            d = json.loads(s)
            return '{%s}' % ', '.join(
                '%s=%s' % (k, round(x, 4) if isinstance(x, float) else x)
                for k, x in d.items())
        except Exception:
            pass
    return s


def main() -> None:
    cx = sqlite3.connect('file:%s?mode=ro' % DB, uri=True)
    cx.row_factory = sqlite3.Row
    for t, order in CHAIN:
        cols = [r['name'] for r in cx.execute('pragma table_info("%s")' % t)]
        rows = list(cx.execute('select * from "%s" order by "%s"' % (t, order)))
        print('\n' + '=' * 74)
        print('%s   %d 行' % (t, len(rows)))
        print('=' * 74)
        for i, r in enumerate(rows, 1):
            print('  [%d]' % i)
            for c in cols:
                if c in ('source_status', 'source_ref'):
                    continue
                print('    %-30s %s' % (c, fmt(c, r[c])))
    cx.close()


if __name__ == '__main__':
    sys.exit(main())
