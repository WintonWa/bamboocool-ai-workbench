#!/usr/bin/env python3
"""盘点 Agent 输出面：判断层四张表的真实字段 + 取值分布 + 页面实读字段。

产出用于写 Agent 端契约，所以必须从落盘的库和渲染代码里取，不能凭记忆。

用法：/usr/bin/python3 probe_agent_surface.py
"""
from __future__ import annotations

import pathlib
import re
import sqlite3
import sys

DB = pathlib.Path(__file__).parent / "v0.1.0" / "keyword_demo.sqlite"
JS = (pathlib.Path(__file__).parents[2] / "09-工作台" / "web" / "modules"
      / "keyword.js")
DATA_PY = (pathlib.Path(__file__).parents[2] / "09-工作台" / "modules"
           / "keyword" / "data.py")

# 判断层四张表：不是算子算出来的，是「谁来判断」的产物
JUDGMENT_TABLES = [
    "fact_keyword_evidence",
    "fact_keyword_daily_report",
    "fact_keyword_market_change_event",
    "fact_keyword_coverage_event",
    "fact_keyword_audit_record",
]


def main() -> int:
    if not DB.exists():
        print("找不到库：%s" % DB)
        return 1
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row

    for t in JUDGMENT_TABLES:
        cols = con.execute(f"PRAGMA table_info({t})").fetchall()
        n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print("=" * 78)
        print("%s　%d 行　%d 列" % (t, n, len(cols)))
        print("=" * 78)
        for c in cols:
            name, typ = c["name"], c["type"]
            # 取非空样本与去重基数，判断这一列是枚举、自由文本还是数字
            row = con.execute(
                f"SELECT COUNT(DISTINCT {name}) d, COUNT({name}) nn FROM {t}"
            ).fetchone()
            d, nn = row["d"], row["nn"]
            sample = con.execute(
                f"SELECT {name} v FROM {t} WHERE {name} IS NOT NULL "
                f"AND {name} != '' LIMIT 1"
            ).fetchone()
            sv = "" if sample is None else str(sample["v"])
            # 枚举列（去重基数小）把全部取值列出来 —— Agent 必须照这份枚举出
            if 0 < d <= 12 and typ.upper() in ("TEXT", "VARCHAR", ""):
                vals = [str(r["v"]) for r in con.execute(
                    f"SELECT DISTINCT {name} v FROM {t} "
                    f"WHERE {name} IS NOT NULL ORDER BY 1")]
                kind = "枚举[%d]" % d
                shown = " | ".join(vals)[:150]
            elif len(sv) > 40:
                kind = "自由文本"
                shown = sv[:110].replace("\n", " ")
            else:
                kind = "值"
                shown = sv[:70]
            print("  %-34s %-9s 非空%-6d %-10s %s"
                  % (name, typ or "-", nn, kind, shown))
        print()

    # 页面实际读了哪些字段：从 keyword.js 里抓 e.xxx / r.xxx / t.xxx 形式
    print("=" * 78)
    print("页面（keyword.js）实际渲染的判断层字段")
    print("=" * 78)
    js = JS.read_text(encoding="utf-8")
    dp = DATA_PY.read_text(encoding="utf-8")
    all_cols = set()
    for t in JUDGMENT_TABLES:
        for c in con.execute(f"PRAGMA table_info({t})"):
            all_cols.add(c["name"])
    used, only_label, unused = [], [], []
    for col in sorted(all_cols):
        in_js = re.search(r"[.\[]\"?%s\b" % re.escape(col), js) is not None
        lbl = col + "_label"
        in_js_lbl = re.search(r"\b%s\b" % re.escape(lbl), js) is not None
        in_sql = re.search(r"\b%s\b" % re.escape(col), dp) is not None
        if in_js:
            used.append(col)
        elif in_js_lbl:
            only_label.append(col)
        elif in_sql:
            unused.append(col + "（进了 SQL 未上屏）")
    print("\n直接上屏（%d）：" % len(used))
    print("  " + "、".join(used))
    print("\n只上屏中文标签、码值不出 SQL（%d）：" % len(only_label))
    print("  " + "、".join(c + " → " + c + "_label" for c in only_label))
    print("\n取了但页面没渲染（%d）：" % len(unused))
    print("  " + "、".join(unused))
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
