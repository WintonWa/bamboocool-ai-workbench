#!/usr/bin/env python3
"""按接入契约 6.2 / 4 规整数据包：表名加模块前缀 + 产出 keyword_demo.sqlite。

契约要求：
  6.2 表名带模块前缀 fact_keyword_* / dim_keyword* / bridge_keyword_*
  4   数据库文件名 07-关键词分析模块/02-数据构建/v0.1.0/keyword_demo.sqlite
      （core/paths.py 的 KEYWORD_DB 就指这个名字）
  6.4 value_origin 取值统一为 direct / derived / constructed

只读源库、写新库，源库 bamboocool_keyword_v0.1.0.sqlite 不动。
用法：/usr/bin/python3 migrate_to_contract.py
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "v0.1.0", "bamboocool_keyword_v0.1.0.sqlite")
DST = os.path.join(HERE, "v0.1.0", "keyword_demo.sqlite")

# 不合规的表名 → 契约要求的名字
RENAME = {
    "dim_scope": "dim_keyword_scope",
    "dim_brand": "dim_keyword_brand",
    "dim_state_label": "dim_keyword_state_label",
    "dim_child_product_goal": "dim_keyword_child_goal",
    "fact_child_inventory_absorb": "fact_keyword_child_absorb",
    "fact_child_traffic_attribution_daily": "fact_keyword_traffic_attribution_daily",
    # 共享市场词库本体。契约 6.2 要求 dim_keyword* 前缀，
    # dim_market_keyword 不匹配（market 挡在 keyword 前面）
    "dim_market_keyword": "dim_keyword_term",
}

# 契约 6.4：value_origin 只允许 direct / derived / constructed
ORIGIN_MAP = {
    "customer_real": "direct",
    "customer_real_anchor": "derived",   # 由客户「在前三/前十」推导出的位段
    "derived": "derived",
    "synthetic_demo": "constructed",
    "missing": "constructed",
}

PREFIX_OK = ("dim_keyword", "fact_keyword", "bridge_keyword")

# 会上屏的自由文本列。构建期把 v0.3.0 的 decision_summary 原文拼进了 main_basis，
# 那句话里混着英文枚举（「基准场景出现replenishment_gap；建议补货…」），
# 直接显示就是枚举码泄漏，G9 / G17 都会红。在这里按契约在读取边界之前清掉。
TEXT_COLUMNS = {
    "fact_keyword_evidence": ["conclusion", "main_basis"],
    "fact_keyword_market_change_event": ["label"],
    "fact_keyword_coverage_event": ["label"],
    "fact_keyword_daily_report": ["q1_traffic_result", "q2_main_movers",
                                  "q3_core_coverage_change", "q4_new_signals",
                                  "q5_priority_next"],
}

# v0.3.0 的库存风险枚举 → 中文成品文案
RISK_TEXT = {
    "replenishment_gap": "补货缺口",
    "stockout": "断货",
    "overstock": "超量备货",
    "aged_inventory_risk": "库龄风险",
    "healthy": "库存健康",
}


def _sanitize_text(con) -> tuple[int, list[str]]:
    changed = 0
    for table, cols in TEXT_COLUMNS.items():
        n = con.execute("select count(*) from sqlite_master where type='table' and name=?",
                        (table,)).fetchone()[0]
        if not n:
            continue
        for col in cols:
            for code, cn in RISK_TEXT.items():
                cur = con.execute(
                    "update %s set %s = replace(%s, ?, ?) where %s like ?"
                    % (table, col, col, col),
                    (code, cn, "%" + code + "%"))
                changed += cur.rowcount
    con.commit()
    left = []
    for table, cols in TEXT_COLUMNS.items():
        for col in cols:
            for code in RISK_TEXT:
                try:
                    n = con.execute("select count(*) from %s where %s like ?"
                                    % (table, col), ("%" + code + "%",)).fetchone()[0]
                except sqlite3.OperationalError:
                    continue
                if n:
                    left.append("%s.%s:%s=%d" % (table, col, code, n))
    return changed, left


def main() -> int:
    if not os.path.exists(SRC):
        print("源库不存在：%s" % SRC, file=sys.stderr)
        return 1
    shutil.copy2(SRC, DST)
    con = sqlite3.connect(DST)

    for old, new in RENAME.items():
        n = con.execute("select count(*) from sqlite_master where type='table' and name=?",
                        (old,)).fetchone()[0]
        if n:
            con.execute("alter table %s rename to %s" % (old, new))
            print("  重命名 %-40s → %s" % (old, new))

    tables = [r[0] for r in con.execute(
        "select name from sqlite_master where type='table' and name not like 'sqlite_%'")]
    bad = [t for t in tables if not t.startswith(PREFIX_OK)]
    print("\n表前缀检查：%d 张表，不合规 %d 张 %s" % (len(tables), len(bad), bad or ""))

    # value_origin 收敛到三值
    total = 0
    for t in tables:
        cols = [r[1] for r in con.execute("pragma table_info(%s)" % t)]
        if "value_origin" not in cols:
            continue
        for old, new in ORIGIN_MAP.items():
            cur = con.execute("update %s set value_origin=? where value_origin=?" % t,
                              (new, old))
            total += cur.rowcount
    con.commit()
    left = set()
    for t in tables:
        cols = [r[1] for r in con.execute("pragma table_info(%s)" % t)]
        if "value_origin" in cols:
            left |= {r[0] for r in con.execute(
                "select distinct value_origin from %s" % t)}
    print("value_origin 归一：改写 %d 行，现有取值 %s" % (total, sorted(left)))

    # 上屏文本里的枚举码
    n_text, text_left = _sanitize_text(con)
    print("上屏文本清理：改写 %d 处，残留 %s" % (n_text, text_left or "无"))

    # 产品维度不得重建（契约 G7）
    leak = [r[0] for r in con.execute(
        "select name from sqlite_master where name in "
        "('dim_product_child','dim_product_parent')")]
    print("G7 产品维度未重建：%s" % ("通过" if not leak else "泄漏 %s" % leak))

    con.execute("vacuum")
    con.close()
    print("\n输出 %s (%.1f MB)" % (DST, os.path.getsize(DST) / 1e6))
    ok = (not bad and left <= {"direct", "derived", "constructed"} and not leak
          and not text_left)
    print("契约 6.2 / 6.4 / G7 / G9 文案：%s" % ("全部通过" if ok else "有不合规项"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
