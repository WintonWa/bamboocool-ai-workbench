#!/usr/bin/env python3
"""关键词源表勘查：头部 ASIN 与自有 342 子 ASIN 的交集，以及未勘查文件的字段级结构。

只读。需要 /usr/bin/python3（本机唯一带 lxml 的解释器）。
用法：/usr/bin/python3 probe_kw_asin_overlap.py
"""
from __future__ import annotations

import collections
import html.parser
import os
import re
import sqlite3
import sys
import zipfile

AD_PROBE = "/Users/linsen/BAM/04-广告分析模块/00-源表勘查"
sys.path.insert(0, AD_PROBE)
import xlsxlite as X  # noqa: E402

KW_DIR = "/Users/linsen/BAM/数据源/AI广告对接数据-总20260803/10.关键词"
DB = ("/Users/linsen/BAM/02-产品销售库存模块/02-数据构建/"
      "v0.3.0/bamboocool_product_sales_inventory_v0.3.0.sqlite")

ASIN_RE = re.compile(r"B0[A-Z0-9]{8}")
HEAD_COLS = ["#1 前三ASIN", "#2 前三ASIN", "#3 前三ASIN"]
TOP10_COL = "前十ASIN"


def own_asins() -> tuple[set[str], dict[str, tuple]]:
    con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    rows = con.execute(
        "select child_asin, parent_asin, style_name, product_lifecycle "
        "from dim_product_child").fetchall()
    con.close()
    return {r[0] for r in rows}, {r[0]: r[1:] for r in rows}


def sheet_rows(path: str, name: str):
    zf = zipfile.ZipFile(path)
    sheets = X.sheets(zf)
    for i, (sname, _) in enumerate(sheets):
        if sname == name:
            return list(X.iter_rows(path, sheet_index=i))
    return []


def probe_overlap(own: set[str], meta: dict) -> None:
    path = os.path.join(KW_DIR, "关键词3.xlsx")
    rows = sheet_rows(path, "全量关键词(含分类)")
    hdr, body = rows[0], rows[1:]
    ci = {h: i for i, h in enumerate(hdr)}
    print("== 关键词3.xlsx / 全量关键词(含分类) ==")
    print("rows=%d cols=%d" % (len(body), len(hdr)))

    counter = collections.Counter()
    kw_top3 = kw_top10 = 0
    per_own_kw = collections.defaultdict(list)
    for r in body:
        kw = r[ci["关键词"]]

        def grab(cols):
            found = set()
            for c in cols:
                j = ci[c]
                if j < len(r) and r[j]:
                    found |= set(ASIN_RE.findall(str(r[j])))
            return found

        top3 = grab(HEAD_COLS)
        top10 = grab(HEAD_COLS + [TOP10_COL])
        for a in top10:
            counter[a] += 1
        hit3, hit10 = top3 & own, top10 & own
        if hit3:
            kw_top3 += 1
        if hit10:
            kw_top10 += 1
        for a in hit10:
            per_own_kw[a].append(kw)

    inter = set(counter) & own
    print("头部/前十字段出现的唯一 ASIN 数: %d" % len(counter))
    print("自有子 ASIN 总数: %d" % len(own))
    print("交集(自有且出现在头部/前十): %d" % len(inter))
    print("含自有 ASIN 的关键词数: 前三=%d  前十=%d  (占 %d 词的 %.1f%% / %.1f%%)"
          % (kw_top3, kw_top10, len(body),
             100.0 * kw_top3 / len(body), 100.0 * kw_top10 / len(body)))
    print("\n-- 交集明细(按覆盖词数降序, 取前 25) --")
    print("%-12s %-12s %-16s %-8s %s" % ("child_asin", "parent", "style", "lifecycle", "覆盖词数"))
    for a, n in sorted(((a, counter[a]) for a in inter), key=lambda t: -t[1])[:25]:
        p, style, life = meta[a]
        print("%-12s %-12s %-16s %-8s %d"
              % (a, p, (style or "")[:16], (life or "")[:8], n))

    golden = ["B0CGLY2BPZ", "B0C3V65DHZ", "B0CGLWQVWR", "B0CBPXNC1M", "B0BVM5PHFB"]
    print("\n-- v0.3.0 五个黄金场景子体的关键词覆盖 --")
    for g in golden:
        kws = per_own_kw.get(g, [])
        print("%-12s 覆盖词数=%-4d 样例=%s" % (g, len(kws), ", ".join(map(str, kws[:5])) or "—"))


def probe_kw2() -> None:
    path = os.path.join(KW_DIR, "关键词2.xlsx")
    print("\n== 关键词2.xlsx 字段级 ==")
    zf = zipfile.ZipFile(path)
    for name, _ in X.sheets(zf):
        rows = list(X.iter_rows(path,
                                sheet_index=[i for i, (n, _) in enumerate(X.sheets(zf))
                                             if n == name][0],
                                limit=2))
        if not rows:
            print("  [%s] 空表" % name)
            continue
        print("  [%s] cols=%d" % (name, len(rows[0])))
        print("      表头: %s" % " | ".join(str(c) for c in rows[0]))
        if len(rows) > 1:
            print("      样例: %s" % " | ".join(str(c)[:18] for c in rows[1]))


class TableGrab(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables, self.cur, self.row, self.cell = [], None, None, None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.cur = []
        elif tag == "tr" and self.cur is not None:
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data.strip())

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None:
            self.row.append(" ".join(x for x in self.cell if x))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            if any(self.row):
                self.cur.append(self.row)
            self.row = None
        elif tag == "table" and self.cur is not None:
            self.tables.append(self.cur)
            self.cur = None


def probe_kw1() -> None:
    path = os.path.join(KW_DIR, "关键词1.html")
    print("\n== 关键词1.html 结构 ==")
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        raw = fh.read()
    p = TableGrab()
    p.feed(raw)
    for i, t in enumerate(p.tables, 1):
        widths = collections.Counter(len(r) for r in t)
        print("  表%-3d 行=%-4d 列宽分布=%s" % (i, len(t), dict(widths)))
        for r in t[:3]:
            print("       %s" % " | ".join(c[:20] for c in r))


if __name__ == "__main__":
    own, meta = own_asins()
    probe_overlap(own, meta)
    probe_kw2()
    probe_kw1()
