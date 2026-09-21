#!/usr/bin/env python3
"""读「6月预投下单」的真实行，算预投比分布与 70% 达成率。

只读。不下判断，只把数字摆出来。
"""
from __future__ import annotations

import sys

sys.path.insert(0, "/Users/linsen/BAM/04-广告分析模块/00-源表勘查")
import xlsxlite  # noqa: E402

MONTHLY = ("/Users/linsen/BAM/数据源/AI广告对接数据-总20260803/"
           "14.其他分析文件/2026年月报/6月/一组6月月报.xlsx")
SHEET = 4   # 6月预投下单


def main() -> None:
    rows = list(xlsxlite.iter_rows(MONTHLY, sheet_index=SHEET, limit=400))
    print(f"读到 {len(rows)} 行（limit=400）")
    for n, row in enumerate(rows[:26]):
        cells = ["" if c is None else str(c)[:16] for c in row]
        while cells and cells[-1] == "":
            cells.pop()
        print(f"r{n:<3} ({len(cells):>2}) {cells}")

    # 找出真正有数据的行数：款号非空
    nonempty = [r for r in rows if len(r) > 4 and str(r[4] or "").strip()]
    print(f"\n款号非空的行：{len(nonempty)}")

    print("\n=== 预投数/预投总数/总下单数/剩余数/预投比 五列取值样本 ===")
    for n, r in enumerate(nonempty[:20]):
        def g(i):
            return r[i] if len(r) > i else None
        print(f"  {n:<3} 款号={g(4)!s:<14} 组合={g(5)!s:<8} 条数={g(6)!s:<5} "
              f"预投数={g(8)!s:<9} 追加={g(9)!s:<7} 预投总数={g(10)!s:<9} "
              f"总下单={g(15)!s:<9} 剩余={g(16)!s:<9} 预投比={g(17)!s:<20} "
              f"单包条数={g(18)!s:<5} 总条数={g(19)!s}")


if __name__ == "__main__":
    main()
