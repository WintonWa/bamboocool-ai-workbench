#!/usr/bin/env python3
"""核实两件事，决定预投模块能不能挂真实数据：

  1. 月报「6月预投下单」的 141 个「款号×组合」与产品包 57 个配色组的交集
  2. 预投的上游 —— 未来销量预测（fact_child_forecast_daily）覆盖到哪一层

只读。
"""
from __future__ import annotations

import sqlite3
import sys

sys.path.insert(0, "/Users/linsen/BAM/04-广告分析模块/00-源表勘查")
import xlsxlite  # noqa: E402

MONTHLY = ("/Users/linsen/BAM/数据源/AI广告对接数据-总20260803/"
           "14.其他分析文件/2026年月报/6月/一组6月月报.xlsx")
DB = ("/Users/linsen/BAM/02-产品销售库存模块/02-数据构建/v0.3.0/"
      "bamboocool_product_sales_inventory_v0.3.0.sqlite")


def main() -> None:
    rows = list(xlsxlite.iter_rows(MONTHLY, sheet_index=4, limit=400))
    sheet_groups = {}
    for r in rows[2:]:
        if len(r) <= 17 or not str(r[4] or "").strip():
            continue
        key = (str(r[4]).strip(), str(r[5] or "").strip())
        sheet_groups[key] = r

    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    spine = {(a or "", b or "") for a, b in con.execute(
        "select style_no, combination from dim_product_child "
        "where style_no<>'' and combination<>''")}

    inter = set(sheet_groups) & spine
    print(f"月报配色组 {len(sheet_groups)}  产品包配色组 {len(spine)}  "
          f"交集 {len(inter)}")
    print(f"月报有、脊椎无：{len(set(sheet_groups) - spine)}")
    print(f"脊椎有、月报无：{len(spine - set(sheet_groups))}")
    print("\n交集样本（前 12）：")
    for k in sorted(inter)[:12]:
        r = sheet_groups[k]
        print(f"  {k[0]}-{k[1]:<3} 预投 {r[10]!s:>10}  下单 {r[15]!s:>10}")
    print("\n脊椎有、月报无（前 10）：")
    for k in sorted(spine - set(sheet_groups))[:10]:
        print(f"  {k[0]}-{k[1]}")

    print("\n=== 预投上游：未来销量预测覆盖 ===")
    for sql, tag in [
        ("select count(*), count(distinct child_asin), min(date), max(date) "
         "from fact_child_forecast_daily", "fact_child_forecast_daily"),
        ("select count(*), count(distinct child_asin), min(run_date), max(run_date) "
         "from fact_child_forecast_run", "fact_child_forecast_run"),
        ("select count(*), count(distinct child_asin), min(date), max(date) "
         "from fact_child_sales_daily", "fact_child_sales_daily"),
        ("select count(*), count(distinct child_asin), min(month), max(month) "
         "from fact_child_sales_monthly", "fact_child_sales_monthly"),
    ]:
        try:
            print(f"  {tag:<34} {con.execute(sql).fetchone()}")
        except sqlite3.Error as e:                                # noqa: PERF203
            print(f"  {tag:<34} ERR {e}")

    print("\n=== 配色组能覆盖多少子体的预测 ===")
    q = ("select count(distinct c.child_asin) from dim_product_child c "
         "join fact_child_forecast_daily f on f.child_asin=c.child_asin "
         "where c.style_no<>'' and c.combination<>''")
    print(f"  有预测且有配色组的子体：{con.execute(q).fetchone()[0]}")
    q2 = ("select count(distinct c.style_no||'|'||c.combination) "
          "from dim_product_child c "
          "join fact_child_forecast_daily f on f.child_asin=c.child_asin")
    print(f"  被预测覆盖到的配色组：{con.execute(q2).fetchone()[0]} / 57")

    print("\n=== fact_child_sales_monthly 列 ===")
    print("  ", [d[1] for d in con.execute(
        "pragma table_info(fact_child_sales_monthly)")])
    print("=== fact_supply_plan 列 ===")
    print("  ", [d[1] for d in con.execute(
        "pragma table_info(fact_supply_plan)")])
    con.close()


if __name__ == "__main__":
    main()
