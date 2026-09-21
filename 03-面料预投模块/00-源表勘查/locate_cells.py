#!/usr/bin/env python3
"""给出三项数据在 Excel 里的**精确坐标**：文件 / sheet 第几张 / 列字母 / 真实行号。

为什么单独写：xlsxlite.iter_rows 按 <row> 元素顺序 yield，**不读 r 属性**。
xlsx 里允许跳行（缺失的 <row> 不占位），所以迭代序号不一定等于 Excel 行号。
这里直接读 <row r="N"> 和 <c r="J143">，报出来的坐标能在 Excel 里直接跳。

只读。
"""
from __future__ import annotations

import zipfile

from lxml import etree

M = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

MONTHLY = ("/Users/linsen/BAM/数据源/AI广告对接数据-总20260803/"
           "14.其他分析文件/2026年月报/6月/一组6月月报.xlsx")
STOCK = ("/Users/linsen/BAM/数据源/AI广告对接数据-总20260803/"
         "3.库存表-物流管理表.xlsx")
MINE = ("/Users/linsen/BAM/03-面料预投模块/00-源表勘查/"
        "原始预投表-一组6月预投下单-原样.xlsx")


def col_letter(n: int) -> str:
    """1 -> A, 27 -> AA"""
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def shared(zf):
    try:
        root = etree.fromstring(zf.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    out = []
    for si in root.findall(f"{{{M}}}si"):
        out.append("".join(t.text or "" for t in si.iter(f"{{{M}}}t")))
    return out


def sheet_paths(zf):
    """按 workbook 里声明的顺序返回 (tab序号, 名字, zip内路径)。"""
    wb = etree.fromstring(zf.read("xl/workbook.xml"))
    rels = etree.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    rmap = {r.get("Id"): r.get("Target") for r in rels}
    out = []
    for i, sh in enumerate(wb.find(f"{{{M}}}sheets"), start=1):
        t = rmap.get(sh.get(f"{{{R}}}id"), "")
        out.append((i, sh.get("name"), "xl/" + t.lstrip("/")))
    return out


def load(path, sheet_name):
    """回 (tab序号, {(行号, 列号): 值})。行列号都是 Excel 的 1-based 真实号。"""
    with zipfile.ZipFile(path) as zf:
        strs = shared(zf)
        tab = zp = None
        for i, name, p in sheet_paths(zf):
            if name == sheet_name:
                tab, zp = i, p
                break
        if zp is None:
            raise SystemExit(f"{path} 里没有名叫「{sheet_name}」的 sheet")
        cells = {}
        root = etree.fromstring(zf.read(zp))
        for row in root.iter(f"{{{M}}}row"):
            rn = int(row.get("r"))
            for c in row.findall(f"{{{M}}}c"):
                ref = c.get("r") or ""
                letters = "".join(ch for ch in ref if ch.isalpha())
                cn = 0
                for ch in letters:
                    cn = cn * 26 + (ord(ch) - 64)
                t = c.get("t")
                v = c.find(f"{{{M}}}v")
                val = v.text if v is not None else None
                if t == "s" and val is not None:
                    k = int(val)
                    val = strs[k] if k < len(strs) else None
                elif t == "inlineStr":
                    ise = c.find(f"{{{M}}}is")
                    val = "".join(x.text or "" for x in ise.iter(f"{{{M}}}t")) if ise is not None else None
                if val is not None:
                    cells[(rn, cn)] = val
        return tab, cells


def header_row(cells, want, maxrow=3):
    """在前几行里找表头，回 (行号, 列号)。"""
    for rn in range(1, maxrow + 1):
        for (r, c), v in cells.items():
            if r == rn and str(v).strip() == want:
                return r, c
    return None, None


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main() -> None:
    print("=" * 96)
    print("问题 3「追加数」和问题 5「运营」——都在同一张表")
    print("=" * 96)
    tab, cells = load(MONTHLY, "6月预投下单")
    print(f"文件：一组6月月报.xlsx")
    print(f"Sheet：「6月预投下单」= Excel 里从左往右第 {tab} 个标签页\n")

    for want in ("运营", "追加数", "预投数", "预投总数", "总下单数", "剩余数", "预投比"):
        r, c = header_row(cells, want)
        if r is None:
            print(f"  {want:<8} 没找到")
            continue
        print(f"  {want:<8} 表头在 {col_letter(c)}{r}  （第 {c} 列 = {col_letter(c)} 列）")

    # 追加数：哪些行真有值
    _, ac = header_row(cells, "追加数")
    rows_with = sorted(r for (r, c), v in cells.items()
                       if c == ac and r > 2 and num(v) not in (None, 0.0))
    print(f"\n  「追加数」有值的行：共 {len(rows_with)} 行")
    tot = 0.0
    for r in rows_with:
        kh = cells.get((r, 5), "")
        zh = cells.get((r, 6), "")
        pre = num(cells.get((r, 9))) or 0
        add = num(cells.get((r, ac))) or 0
        tt = num(cells.get((r, 11))) or 0
        tot += add if str(kh).strip() != "合计" else 0
        mark = "  ← 合计行" if str(kh).strip() == "合计" else ""
        print(f"    {col_letter(ac)}{r:<5} {str(kh):<12} {str(zh):<4} "
              f"预投数={pre:>9,.0f}  追加数={add:>8,.0f}  预投总数={tt:>9,.0f}{mark}")
    print(f"    明细行追加数合计 = {tot:,.0f}")

    # 运营列有哪些人
    _, oc = header_row(cells, "运营")
    people = {}
    for (r, c), v in cells.items():
        if c == oc and r > 2 and str(v).strip() and str(v).strip() != "运营":
            people.setdefault(str(v).strip(), []).append(r)
    print(f"\n  「运营」列（{col_letter(oc)} 列）里的人：")
    for name, rs in sorted(people.items(), key=lambda x: -len(x[1])):
        print(f"    {name:<8} {len(rs):>3} 行   例：{col_letter(oc)}{min(rs)}")

    # 合计行在哪
    trow = [r for (r, c), v in cells.items() if c == 5 and str(v).strip() == "合计"]
    if trow:
        r = trow[0]
        print(f"\n  「合计」那一行是 Excel 第 {r} 行（E{r} 写着「合计」）")
        print(f"    该行预投比在 {col_letter(18)}{r} = {cells.get((r, 18))}")

    print("\n" + "=" * 96)
    print("问题 4 那三列 —— 在另一个文件里，不在上面那张表")
    print("=" * 96)
    tab2, c2 = load(STOCK, "一组")
    print(f"文件：3.库存表-物流管理表.xlsx")
    print(f"Sheet：「一组」= Excel 里从左往右第 {tab2} 个标签页\n")
    for want in ("建议发货（2个月）", "建议备货（4个月）", "预投预计",
                 "翻单合计", "6月预投", "款号", "组合", "尺码"):
        r, c = header_row(c2, want, maxrow=2)
        if r is None:
            print(f"  {want:<18} 没找到")
            continue
        print(f"  {want:<18} 表头在 {col_letter(c)}{r}  （第 {c} 列 = {col_letter(c)} 列）")

    r0, c0 = header_row(c2, "预投预计", maxrow=2)
    if c0:
        datarows = sorted(r for (r, c), v in c2.items()
                          if c == c0 and r > r0 and num(v) is not None)[:5]
        print(f"\n  「预投预计」({col_letter(c0)} 列) 前几个有值的格：")
        for r in datarows:
            kh = c2.get((r, 11), "")     # K 列 款号
            zh = c2.get((r, 12), "")     # L 列 组合
            sz = c2.get((r, 14), "")     # N 列 尺码
            bc = c2.get((r, 55), "")     # BC 列 6月预投（对照：它是整数盒数）
            print(f"    {col_letter(c0)}{r:<5} {str(kh):<12} {str(zh):<4} {str(sz):<6} "
                  f"预投预计={c2.get((r, c0))!s:<20} 6月预投={bc!s}")

    print("\n" + "=" * 96)
    print("在我导给你那份文件里的位置（列少了、顺序一样）")
    print("=" * 96)
    tab3, c3 = load(MINE, "6月预投下单（原样）")
    print(f"文件：原始预投表-一组6月预投下单-原样.xlsx（第 {tab3} 个标签页）\n")
    for want in ("运营", "追加数", "预投数", "预投总数", "是否合计行"):
        r, c = header_row(c3, want)
        if r:
            print(f"  {want:<10} 表头在 {col_letter(c)}{r}")
    print("  ⚠️ 那三列（建议发货/建议备货/预投预计）不在这份文件里 ——")
    print("     它们属于 3.库存表-物流管理表.xlsx，是另一张表。")


if __name__ == "__main__":
    main()
