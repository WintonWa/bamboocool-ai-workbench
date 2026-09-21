#!/usr/bin/env python3
"""把原始预投表原样打印出来，一格不改。

只读。目的是让人核对源表长什么样，所以：
  不合并单元格、不改列名、不补空值、公式错误值（#DIV/0!）原样保留
"""
from __future__ import annotations

import sys

sys.path.insert(0, "/Users/linsen/BAM/04-广告分析模块/00-源表勘查")
import xlsxlite  # noqa: E402

MONTHLY = ("/Users/linsen/BAM/数据源/AI广告对接数据-总20260803/"
           "14.其他分析文件/2026年月报/6月/一组6月月报.xlsx")
STOCK = ("/Users/linsen/BAM/数据源/AI广告对接数据-总20260803/"
         "3.库存表-物流管理表.xlsx")


def cell(v, w=11):
    """一格。**必须带分隔符** —— 只靠 rjust 时，一个正好占满列宽的长小数
    会和左边那格连成一个数（0.0108695652 贴在 25 后面看起来像 250.01…），
    读的人会误判成数据错。"""
    if v is None:
        s = ""
    else:
        s = str(v)
        if isinstance(v, float) and v == int(v):
            s = f"{int(v):,}"
        elif isinstance(v, float):
            s = f"{v:.4f}".rstrip("0").rstrip(".")
    return " " + s[:w].rjust(w) + " |"


def main() -> None:
    print("=" * 118)
    print("① 一组6月月报.xlsx  →  sheet「6月预投下单」（第 5 张表）")
    print("=" * 118)
    rows = list(xlsxlite.iter_rows(MONTHLY, sheet_index=4, limit=400))

    print("\n【表头 20 列，原样】")
    for i, h in enumerate(rows[0]):
        tag = ""
        if i in (11, 12, 13, 14):
            tag = f"  ← 无表头，第 2 行是日期序列号 {rows[1][i]} = {xlsxlite.serial_to_date(rows[1][i])}"
        print(f"  第 {i + 1:>2} 列  {str(h or '（空）'):<12}{tag}")

    keep = [4, 5, 6, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19]
    names = ["款号", "组合", "条数", "预投数", "追加数", "预投总数",
             "06-02", "06-09", "06-16", "06-23", "总下单数", "剩余数",
             "预投比", "单包条数", "总条数"]

    print("\n【真实数据行，原样。列名按上面的表头对应】")
    print("  行号  |" + "".join(" " + n.rjust(12) + " |" for n in names))
    print("  " + "-" * 224)
    shown = 0
    for n, r in enumerate(rows[2:], start=3):
        if len(r) <= 19 or not str(r[4] or "").strip():
            continue
        shown += 1
        if shown > 12:
            continue
        print(f"  r{n:<4} |" + "".join(cell(r[i] if len(r) > i else None, 12) for i in keep))

    print("  ...")
    # 最后一行是合计
    for n, r in enumerate(rows[2:], start=3):
        if len(r) > 4 and str(r[4] or "").strip() in ("合计", "小计", "总计"):
            print(f"  r{n:<4} |" + "".join(cell(r[i] if len(r) > i else None, 12) for i in keep)
                  + "  ← 最后一行是「合计」")

    print(f"\n  款号非空的行共 {shown} 行（含最后那行合计）")

    print("\n" + "=" * 118)
    print("② 3.库存表-物流管理表.xlsx  →  sheet「一组」（第 1 张表）的预投相关列")
    print("=" * 118)
    srows = list(xlsxlite.iter_rows(STOCK, sheet_index=0, limit=12))
    hdr = [str(h or "") for h in srows[0]]
    idxs = [(i, h) for i, h in enumerate(hdr)
            if "预投" in h or "补投" in h or "建议" in h or "翻单" in h]
    print(f"\n【预投相关列共 {len(idxs)} 个，在第 53~73 列之间】")
    for i, h in idxs:
        print(f"  第 {i + 1:>2} 列  {h}")

    print("\n【真实数据行（前 6 行），只取款号/组合/配色/尺码 + 几个月度预投列】")
    base = [hdr.index("ASIN"), hdr.index("款号"), hdr.index("组合"), hdr.index("尺码")]
    want = ["6月预投", "7月预投", "8月预投", "翻单合计",
            "建议发货（2个月）", "建议备货（4个月）", "预投预计"]
    pick = base + [hdr.index(w) for w in want if w in hdr]
    head = ["ASIN", "款号", "组合", "尺码"] + [w for w in want if w in hdr]
    print("  " + "".join(" " + n.rjust(12) + " |" for n in head))
    print("  " + "-" * (15 * len(head)))
    shown2 = 0
    for r in srows[1:]:
        if len(r) <= pick[1] or not str(r[pick[1]] or "").strip():
            continue
        shown2 += 1
        if shown2 > 6:
            break
        print("  " + "".join(cell(r[i] if len(r) > i else None, 12) for i in pick))
    print("\n  ⚠️ 同一个配色组的预投数在它每个尺码的行上重复出现（看 4A 那几行），"
          "\n     所以这张表按行求和会重复计数 —— 汇总只能用 ① 那张月报表。")


if __name__ == "__main__":
    main()
