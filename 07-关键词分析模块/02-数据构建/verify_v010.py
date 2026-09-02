#!/usr/bin/env python3
"""独立复核 v0.1.0 数据包：只读 SQLite，不依赖构建脚本的中间态。

用法：/usr/bin/python3 verify_v010.py
构建脚本里的门禁跑在内存对象上；这一份跑在落盘结果上，两者互为对照——
落盘环节（类型推断、JSON 序列化、主键约束）自己也会出错。
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "v0.1.0", "bamboocool_keyword_v0.1.0.sqlite")
MANIFEST = os.path.join(HERE, "v0.1.0", "dataset-manifest.json")
AS_OF = "2026-08-03"

FORBIDDEN = ["organic_only", "ad_only", "not_covered", "beyond_depth",
             "collect_failed", "not_monitored", "unconfirmed", "can_absorb_extra",
             "cannot_absorb", "replenish_first", "normal_only", "volume_push",
             "hold_position", "niche_explore", "brand_defend", "clear_stock",
             "maintain_base", "demand_up", "demand_down", "competition_up",
             "head_asin_replaced", "insufficient_history", "not_comparable",
             "market_opportunity", "coverage_gap", "core_position_risk",
             "scene_longtail_signal", "inventory_limited", "insufficient_data",
             "pending_competitor_verification", "synthetic_demo", "customer_real"]

TEXT_COLS = {
    "fact_keyword_evidence": ["conclusion", "main_basis"],
    "fact_keyword_market_change_event": ["label"],
    "fact_keyword_coverage_event": ["label"],
    "fact_keyword_daily_report": ["q1_traffic_result", "q2_main_movers",
                                  "q3_core_coverage_change", "q4_new_signals",
                                  "q5_priority_next"],
}

checks = []


def ck(name, ok, detail=""):
    checks.append((name, bool(ok), str(detail)))


def main():
    if not os.path.exists(DB):
        print("未找到数据库：%s" % DB)
        return 1
    con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    q = lambda s, a=(): con.execute(s, a).fetchall()      # noqa: E731
    one = lambda s, a=(): con.execute(s, a).fetchone()[0]  # noqa: E731

    man = json.load(open(MANIFEST, encoding="utf-8"))

    # V1 表数与行数必须与 manifest 一致（落盘环节没丢行）
    bad = []
    for t in man["tables"]:
        n = one("select count(*) from %s" % t["table"])
        if n != t["record_count"]:
            bad.append((t["table"], t["record_count"], n))
    ck("V1 %d 张表行数与 manifest 一致" % len(man["tables"]), not bad, bad[:3])

    # V2 主键无重复（emit 时 primary key 生效）
    ck("V2 主键约束生效（PRAGMA integrity_check）",
       one("pragma integrity_check") == "ok", one("pragma integrity_check"))

    # V3 引用完整性：位置层的 keyword_id / pair_id 都能解析
    ck("V3 位置层 keyword_id 全部可解析",
       one("""select count(*) from fact_keyword_child_position_daily d
              left join dim_market_keyword k using(keyword_id)
              where k.keyword_id is null""") == 0)
    ck("V3b 证据层 pair_id 全部可解析",
       one("""select count(*) from fact_keyword_evidence e
              left join dim_keyword_child_pair p using(pair_id)
              where p.pair_id is null""") == 0)
    ck("V3c 事件层 snapshot 引用全部可解析",
       one("""select count(*) from fact_keyword_market_change_event e
              left join fact_keyword_market_snapshot s
                on s.snapshot_id = e.to_snapshot_id
              where s.snapshot_id is null""") == 0)

    # V4 as_of 对齐：三处锚点都是 2026-08-03
    ck("V4 快照末期 / 位置末日 / 盘点末期都等于 %s" % AS_OF,
       one("select max(period_end) from fact_keyword_market_snapshot where period_type='week'") == AS_OF
       and one("select max(date) from fact_keyword_child_position_daily") == AS_OF
       and one("select max(run_date) from fact_keyword_audit_record") == AS_OF)

    # V5 G1 落盘复核：抽 mens underwear 末期与客户原值比对（值写死在这里，独立于构建脚本）
    r = one("""select aba_week_rank from fact_keyword_market_snapshot
               where keyword='mens underwear' and period_type='week'
                 and source_code='kw3' and period_end=?""", (AS_OF,))
    p = one("""select product_count from fact_keyword_market_snapshot
               where keyword='mens underwear' and period_type='week'
                 and source_code='kw3' and period_end=?""", (AS_OF,))
    sv = one("""select monthly_search_volume from fact_keyword_market_snapshot
                where keyword='mens underwear' and period_type='month'
                  and source_code='kw3' and period_index=11""")
    ck("V5 mens underwear 末期 = 客户原值 (ABA周217 / 商品数27426 / 月搜索908485)",
       (r, p, sv) == (217, 27426, 908485), (r, p, sv))

    # V6 词级流量与花费不得超过 v0.3.0（用本包残差表自证，残差不得为负）
    neg = one("""select count(*) from fact_child_traffic_attribution_daily
                 where sessions_unattributed < 0 or ad_spend_unattributed < -0.001""")
    ck("V6 归因残差不得为负（词级加总未反超产品级）", neg == 0, "为负 %d 行" % neg)

    # V7 上屏文案零枚举码泄漏（落盘后再扫一遍）
    hits = []
    for tbl, cols in TEXT_COLS.items():
        for c in cols:
            for bad_word in FORBIDDEN:
                n = one("select count(*) from %s where %s like ?" % (tbl, c),
                        ("%" + bad_word + "%",))
                if n:
                    hits.append((tbl, c, bad_word, n))
    ck("V7 落盘文案零枚举码泄漏", not hits, hits[:3])

    # V8 覆盖面：300 监控词全部进入产品关系，五种自然位状态齐全
    ck("V8 300 个监控词全部进入产品关系",
       one("select count(distinct keyword_id) from dim_keyword_child_pair") >= 300,
       one("select count(distinct keyword_id) from dim_keyword_child_pair"))
    states = {r[0] for r in q("select distinct organic_state from fact_keyword_child_position_daily")}
    need = {"covered", "not_covered", "beyond_depth", "collect_failed", "not_monitored"}
    ck("V8b 五种自然位状态齐全", need <= states, sorted(states))

    # V9 七类证据齐全，每类 ≥ 5
    rows = q("""select evidence_type, count(*) from fact_keyword_evidence group by 1""")
    thin = [t for t, n in rows if n < 5]
    ck("V9 七类证据每类 ≥ 5 条", len(rows) == 7 and not thin,
       dict(rows))

    # V10 零覆盖黄金场景子体不得有真实锚点
    leak = one("""select count(*) from dim_keyword_child_pair
                  where child_asin in ('B0CBPXNC1M','B0BVM5PHFB')
                    and anchor_band is not null""")
    ck("V10 零覆盖子体无真实锚点", leak == 0, leak)

    con.close()

    print("== v0.1.0 落盘复核 ==")
    for n, ok, d in checks:
        print("  [%s] %s%s" % ("PASS" if ok else "FAIL", n,
                               ("  (%s)" % d if d and not ok else "")))
    nfail = sum(1 for _, ok, _ in checks if not ok)
    print("\n%d 条，失败 %d 条" % (len(checks), nfail))
    return 1 if nfail else 0


if __name__ == "__main__":
    sys.exit(main())
