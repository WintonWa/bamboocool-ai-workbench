#!/usr/bin/env python3
"""勘查预投链条的真实源表。

只读。目的是回答三个问题：
  1. 「6月预投下单」这张 sheet 到底有哪些列、几行有数据、预投与下单两列都在不在
  2. 3.库存表「一组」的逐月预投列填充到什么程度
  3. 预投 ÷ 下单 的真实比例分布，以及 70% 考核的实际达成率

结论写进 01-源表事实.md，不在这里下判断。
"""
from __future__ import annotations

import sys

sys.path.insert(0, "/Users/linsen/BAM/04-广告分析模块/00-源表勘查")
import xlsxlite  # noqa: E402

MONTHLY = ("/Users/linsen/BAM/数据源/AI广告对接数据-总20260803/"
           "14.其他分析文件/2026年月报/6月/一组6月月报.xlsx")
STOCK = ("/Users/linsen/BAM/数据源/AI广告对接数据-总20260803/"
         "3.库存表-物流管理表.xlsx")


def dump_sheets(path: str, tag: str) -> list[dict]:
    print(f"\n{'=' * 70}\n{tag}\n{path}\n{'=' * 70}")
    info = xlsxlite.sheet_summary(path)
    for i, s in enumerate(info):
        print(f"  [{i}] {s}")
    return info


def dump_sheet_rows(path: str, idx: int, name: str, nrows: int = 12) -> None:
    print(f"\n--- {name} (sheet_index={idx}) 前 {nrows} 行 ---")
    for n, row in enumerate(xlsxlite.iter_rows(path, sheet_index=idx, limit=nrows)):
        cells = ["" if c is None else str(c)[:22] for c in row]
        # 去掉尾部空列，免得刷屏
        while cells and cells[-1] == "":
            cells.pop()
        print(f"  r{n:<3} ({len(cells):>3}col) {cells}")


if __name__ == "__main__":
    m = dump_sheets(MONTHLY, "① 一组6月月报")
    for i, s in enumerate(m):
        nm = str(s.get("name", ""))
        if "预投" in nm or "下单" in nm:
            dump_sheet_rows(MONTHLY, i, nm, 14)

    s3 = dump_sheets(STOCK, "② 3.库存表-物流管理表")
