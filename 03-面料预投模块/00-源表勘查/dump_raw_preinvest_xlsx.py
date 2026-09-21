#!/usr/bin/env python3
"""把原始「6月预投下单」sheet 原样另存成一个单 sheet 文件，方便直接打开核对。

**原样**的意思：
  一格不改、不补空值、不改列名、不删合计行、公式错误值 #DIV/0! 原样保留
  只做两件事：把四个无表头的日期列补上中文表头（源表那四列表头是空的，
  日期写在第二行），以及在最后加一列标出哪一行是合计。

只读源文件。输出到 03-面料预投模块/00-源表勘查/。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, "/Users/linsen/BAM/04-广告分析模块/00-源表勘查")
sys.path.insert(0, "/Users/linsen/BAM/09-工作台")
import xlsxlite  # noqa: E402
from core import xlsx  # noqa: E402   工作台自己手写的 xlsx 写入器，零第三方依赖

SRC = ("/Users/linsen/BAM/数据源/AI广告对接数据-总20260803/"
       "14.其他分析文件/2026年月报/6月/一组6月月报.xlsx")
OUT = Path("/Users/linsen/BAM/03-面料预投模块/00-源表勘查/"
           "原始预投表-一组6月预投下单-原样.xlsx")


def main() -> None:
    rows = list(xlsxlite.iter_rows(SRC, sheet_index=4, limit=400))
    hdr = [str(h or "").strip() for h in rows[0]]

    # 四个无表头列：日期在第 2 行，是 Excel 序列号。补成中文表头。
    for i in range(11, 15):
        d = xlsxlite.serial_to_date(rows[1][i]) if len(rows[1]) > i else None
        hdr[i] = f"{d} 下单" if d else f"第{i+1}列（源表无表头）"
    hdr.append("是否合计行")

    body = []
    for r in rows[2:]:
        if len(r) <= 4 or not str(r[4] or "").strip():
            continue
        cells = [r[i] if len(r) > i else None for i in range(20)]
        is_total = str(cells[4] or "").strip() in ("合计", "小计", "总计", "汇总")
        body.append(cells + ["合计行" if is_total else ""])

    sheets = [{
        "name": "6月预投下单（原样）",
        "headers": hdr,
        "rows": body,
        "widths": [8, 8, 11, 11, 13, 7, 7, 26, 11, 9, 11,
                   13, 13, 13, 13, 11, 10, 20, 9, 12, 10],
    }]
    OUT.write_bytes(xlsx.build(sheets))
    n_total = sum(1 for r in body if r[-1])
    print(f"落盘 {OUT}")
    print(f"  {len(body)} 行 x {len(hdr)} 列（其中合计行 {n_total} 行）")
    print(f"  {OUT.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    main()
