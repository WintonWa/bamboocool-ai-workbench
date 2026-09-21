#!/usr/bin/env python3
"""核实「建议发货（2个月）」「建议备货（4个月）」「预投预计」这三列的真实口径。

起因：它们的值是 3~10 的小数，不可能是预投盒数，但 01-源表事实.md 把
「预投预计」写成了「Excel 算出的预投建议值」。用恒等式反证，不靠列名猜。

只读。
"""
from __future__ import annotations

import statistics
import sys

sys.path.insert(0, "/Users/linsen/BAM/04-广告分析模块/00-源表勘查")
import xlsxlite  # noqa: E402

STOCK = ("/Users/linsen/BAM/数据源/AI广告对接数据-总20260803/"
         "3.库存表-物流管理表.xlsx")


def f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main() -> None:
    rows = list(xlsxlite.iter_rows(STOCK, sheet_index=0, limit=900))
    hdr = [str(h or "") for h in rows[0]]

    def ix(name):
        return hdr.index(name) if name in hdr else None

    cols = {n: ix(n) for n in
            ("建议发货（2个月）", "建议备货（4个月）", "预投预计",
             "翻单合计", "装箱数量", "箱数", "ASIN", "款号", "组合", "尺码")}
    print("列位置:", {k: (v + 1 if v is not None else None) for k, v in cols.items()})

    body = [r for r in rows[1:]
            if len(r) > (cols["款号"] or 0) and str(r[cols["款号"]] or "").strip()]
    print(f"数据行 {len(body)}")

    print("\n=== 三列的取值分布（判断它们是不是盒数）===")
    for name in ("建议发货（2个月）", "建议备货（4个月）", "预投预计", "翻单合计"):
        i = cols[name]
        vals = [f(r[i]) for r in body if len(r) > i and f(r[i]) is not None]
        nz = [v for v in vals if v != 0]
        if not nz:
            print(f"  {name:<18} 全零")
            continue
        ints = sum(1 for v in nz if v == int(v))
        print(f"  {name:<18} 非零 {len(nz):>4}  "
              f"最小 {min(nz):>10.4f}  中位 {statistics.median(nz):>10.4f}  "
              f"最大 {max(nz):>10.2f}  整数占比 {ints/len(nz):>5.0%}")

    print("\n=== 反证：三列之间与销量列的关系 ===")
    # 源数据1 sheet 有 30天日均/可售天数，但「一组」sheet 自己也有销量管理区
    print("「一组」sheet 第 15~24 列的表头（销量与库存管理区）：")
    for i in range(14, 24):
        print(f"  第 {i+1:>2} 列  {hdr[i] or '（空，属上一合并表头）'}")

    print("\n=== 第 2 行（子表头行）在这些列上的内容 ===")
    sub = rows[1] if len(rows) > 1 else []
    for i in list(range(14, 24)) + [cols["建议发货（2个月）"],
                                    cols["建议备货（4个月）"], cols["预投预计"]]:
        if i is None or len(sub) <= i:
            continue
        print(f"  第 {i+1:>2} 列  表头={hdr[i] or '—':<14} 子表头={sub[i]}")

    print("\n=== 恒等式试探：预投预计 = 建议发货 + 建议备货？×倍数？ ===")
    a, b, c = cols["建议发货（2个月）"], cols["建议备货（4个月）"], cols["预投预计"]
    hits = {"c=a+b": 0, "c=b*1.5": 0, "c=a*2": 0, "c=b+a/2": 0}
    n = 0
    for r in body:
        if len(r) <= max(a, b, c):
            continue
        va, vb, vc = f(r[a]), f(r[b]), f(r[c])
        if None in (va, vb, vc) or vc == 0:
            continue
        n += 1
        if abs(vc - (va + vb)) < 0.01:
            hits["c=a+b"] += 1
        if abs(vc - vb * 1.5) < 0.01:
            hits["c=b*1.5"] += 1
        if abs(vc - va * 2) < 0.01:
            hits["c=a*2"] += 1
        if abs(vc - (vb + va / 2)) < 0.01:
            hits["c=b+a/2"] += 1
    print(f"  可比行 {n}：{hits}")

    print("\n=== 样本逐行看（同一配色组的不同尺码）===")
    shown = 0
    for r in body:
        if str(r[cols["款号"]]).strip() != "TH24AM-607":
            continue
        shown += 1
        if shown > 8:
            break
        g = lambda k: (f(r[cols[k]]) if len(r) > cols[k] else None)
        print(f"  {str(r[cols['组合']]):<4} {str(r[cols['尺码']]):<5} "
              f"发货2月={g('建议发货（2个月）')!s:<9} 备货4月={g('建议备货（4个月）')!s:<9} "
              f"预投预计={g('预投预计')!s:<9} 翻单={g('翻单合计')!s}")


if __name__ == "__main__":
    main()
