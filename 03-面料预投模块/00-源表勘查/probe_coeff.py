#!/usr/bin/env python3
"""算齐建库要用的换算系数与汇总数，供设计文档引用。

只读。每个数都能追到来源，没有一个是估的（估的那一项显式标出来）。
"""
from __future__ import annotations

import sqlite3
import statistics
import sys

sys.path.insert(0, "/Users/linsen/BAM/04-广告分析模块/00-源表勘查")
import xlsxlite  # noqa: E402

MONTHLY = ("/Users/linsen/BAM/数据源/AI广告对接数据-总20260803/"
           "14.其他分析文件/2026年月报/6月/一组6月月报.xlsx")
DB = ("/Users/linsen/BAM/02-产品销售库存模块/02-数据构建/v0.3.0/"
      "bamboocool_product_sales_inventory_v0.3.0.sqlite")

# 客户口述锚点（逐字稿 01:02:50）：「我要销售30万盒，对于面料来说，它可能是200吨」
ANCHOR_BOX, ANCHOR_TON = 300_000, 200.0


def f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main() -> None:
    rows = list(xlsxlite.iter_rows(MONTHLY, sheet_index=4, limit=400))
    live = []
    for r in rows[2:]:
        if len(r) <= 19 or not str(r[4] or "").strip():
            continue
        pre, order, pack, tiao = f(r[10]), f(r[15]), f(r[18]), f(r[19])
        if not pre or pre <= 0:
            continue
        live.append((str(r[4]), str(r[5] or ""), pre, order or 0.0, pack or 0.0, tiao or 0.0))

    tot_pre = sum(x[2] for x in live)
    tot_ord = sum(x[3] for x in live)
    tot_tiao = sum(x[5] for x in live)
    avg_pack = tot_tiao / tot_pre if tot_pre else 0
    print(f"一组 6 月 · 预投>0 的配色组 {len(live)}")
    print(f"  预投合计 {tot_pre:,.0f} 盒   下单合计 {tot_ord:,.0f} 盒")
    print(f"  闲置     {tot_pre - tot_ord:,.0f} 盒   整组达成率 {tot_ord/tot_pre:.2%}")
    print(f"  总条数   {tot_tiao:,.0f} 条   加权平均单包条数 {avg_pack:.3f}")

    # 面料换算：用客户锚点 30 万盒≈200 吨，按锚点隐含的平均条数折成「每条克重」
    # 锚点没说那 30 万盒是几条装，所以两种口径都算出来，文档里说清用哪一个。
    g_per_box = ANCHOR_TON * 1e6 / ANCHOR_BOX
    g_per_tiao = g_per_box / avg_pack
    print(f"\n面料换算（锚点 {ANCHOR_BOX:,} 盒 = {ANCHOR_TON} 吨）")
    print(f"  按盒：{g_per_box:,.1f} g/盒")
    print(f"  按条：{g_per_tiao:,.1f} g/条（用一组加权平均 {avg_pack:.3f} 条/盒折算）")
    print(f"  闲置 {tot_pre-tot_ord:,.0f} 盒 -> "
          f"{(tot_pre-tot_ord)*g_per_box/1e6:,.1f} 吨面料")

    rates = [x[3] / x[2] for x in live]
    print(f"\n达成率 中位 {statistics.median(rates):.1%} 均值 {statistics.mean(rates):.1%}")
    for lo, hi in [(0, .3), (.3, .5), (.5, .7), (.7, .9), (.9, 1.01), (1.01, 9)]:
        c = sum(1 for x in rates if lo <= x < hi)
        print(f"  [{lo:.0%},{hi:.0%}) {c:>4}  {'█' * c}")

    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    print("\n=== 产品包：配色组 x 单包条数 x 单盒成本 ===")
    q = ("select c.style_no, c.combination, count(*) n, "
         "       max(e.pack_size) pack, round(avg(e.unit_cost),2) cost "
         "from dim_product_child c "
         "left join fact_unit_economics e on e.child_asin=c.child_asin "
         "where c.style_no<>'' and c.combination<>'' "
         "group by c.style_no, c.combination order by 1,2")
    got = con.execute(q).fetchall()
    print(f"  配色组 {len(got)}；pack_size 缺失 {sum(1 for g in got if not g[3])}；"
          f"unit_cost 缺失 {sum(1 for g in got if not g[4])}")
    costs = [g[4] for g in got if g[4]]
    print(f"  单盒成本 中位 {statistics.median(costs):.2f} 最低 {min(costs):.2f} "
          f"最高 {max(costs):.2f}（币种客户未确认）")
    for g in got[:6]:
        print(f"    {g[0]}-{g[1]:<3} 子体{g[2]} 单包{g[3]}条 单盒成本 {g[4]}")

    print("\n=== 10 月（预投目标月）预测销量按配色组 · 前 8 ===")
    q2 = ("select c.style_no||'-'||c.combination g, "
          "       round(sum(f.p50_units)) p50, round(sum(f.p10_units)) p10, "
          "       round(sum(f.p90_units)) p90, count(distinct c.child_asin) n "
          "from fact_child_forecast_daily f "
          "join dim_product_child c on c.child_asin=f.child_asin "
          "where f.forecast_date between '2026-10-01' and '2026-10-31' "
          "  and c.style_no<>'' and c.combination<>'' "
          "group by 1 order by p50 desc limit 8")
    for g in con.execute(q2):
        print(f"  {g[0]:<16} p50 {g[1]:>8,.0f}  区间 {g[2]:>7,.0f}~{g[3]:>8,.0f}  子体 {g[4]}")
    tot = con.execute(
        "select round(sum(p50_units)) from fact_child_forecast_daily "
        "where forecast_date between '2026-10-01' and '2026-10-31'").fetchone()[0]
    print(f"  57 组 10 月 p50 合计 {tot:,.0f} 盒")
    con.close()


if __name__ == "__main__":
    main()
