#!/usr/bin/env python3
"""构建 preinvest_demo.sqlite v0.1.0。

数据来源三处，全部只读：
  产品包 v0.3.0            57 个配色组的身份、单包条数、单盒成本、尺码销量
  一组6月月报.xlsx          真实预投/下单一轮（141 行，与脊椎交集 53 组）
  3.库存表-物流管理表.xlsx   逐月预投历史（15 个月，2025-05~2026-08）

七张表，全部带 preinvest 前缀（契约 §6.2）。不重建 dim_product_child（G7）。
构造成分一律标 value_origin，那列只对账不上屏（§6.4）。

用法：/usr/bin/python3 build_preinvest_v010.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, "/Users/linsen/BAM/04-广告分析模块/00-源表勘查")
import xlsxlite  # noqa: E402

SRC = Path("/Users/linsen/BAM/数据源/AI广告对接数据-总20260803")
MONTHLY = SRC / "14.其他分析文件/2026年月报/6月/一组6月月报.xlsx"
STOCK = SRC / "3.库存表-物流管理表.xlsx"
PRODUCT_DB = Path("/Users/linsen/BAM/02-产品销售库存模块/02-数据构建/v0.3.0/"
                  "bamboocool_product_sales_inventory_v0.3.0.sqlite")
OUT_DIR = Path("/Users/linsen/BAM/03-面料预投模块/02-数据构建/v0.1.0")
OUT = OUT_DIR / "preinvest_demo.sqlite"

AS_OF = "2026-08-03"
# 预投目标销售月：基准日 + 约两个半月（吴组长 00:56:51）
TARGET_MONTH = "2026-10"
ORDER_MONTH = "2026-09"
# 客户口述锚点（01:02:50）：30 万盒 ≈ 200 吨
FABRIC_G_PER_BOX = 200.0 * 1e6 / 300_000        # 666.666… g/盒

MONTH_COLS_SHEET = 0        # 3.库存表 的「一组」sheet
CYCLE_SHEET = 4             # 月报的「6月预投下单」sheet
BATCH_COL_RANGE = (11, 15)  # 四个无名列 = 分批下单日期


def f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def i(v):
    x = f(v)
    return None if x is None else int(round(x))


# --------------------------------------------------------------------------
# 1. 配色组身份（从产品包聚，不重建产品维度）
# --------------------------------------------------------------------------
def build_groups(pcon: sqlite3.Connection) -> list[dict]:
    rows = pcon.execute("""
        select c.style_no, c.combination,
               count(*)                                    as child_count,
               group_concat(distinct c.size)               as sizes,
               max(c.category)                             as category,
               max(c.operations_group)                     as operations_group,
               max(c.operator)                             as operator,
               max(c.colorway)                             as colorway,
               max(c.product_lifecycle)                    as lifecycle,
               max(e.pack_size)                            as pack_size,
               avg(e.unit_cost)                            as unit_cost_avg
          from dim_product_child c
          left join fact_unit_economics e on e.child_asin = c.child_asin
         where ifnull(c.style_no,'') <> '' and ifnull(c.combination,'') <> ''
         group by c.style_no, c.combination
         order by c.style_no, c.combination
    """).fetchall()
    out = []
    for r in rows:
        (style, comb, n, sizes, cat, og, op, colorway, life, pack, cost) = r
        # 单包条数：产品包已按「组合首位数字」派生。缺了就自己从组合取，
        # 两条路都取不到才留 NULL —— 不填默认值（那会让面料换算静默错）。
        if not pack:
            head = "".join(ch for ch in str(comb) if ch.isdigit())[:1]
            pack = int(head) if head else None
        out.append({
            "group_id": f"{style}|{comb}",
            "style_no": style, "combination": comb,
            "child_count": n,
            "sizes": ",".join(sorted((sizes or "").split(","))),
            "category": cat, "operations_group": og, "operator": op,
            "colorway": colorway, "lifecycle": life,
            "pack_size": i(pack),
            "unit_cost_avg": round(cost, 4) if cost else None,
            "value_origin": "direct",
        })
    return out


# --------------------------------------------------------------------------
# 2. 真实预投轮次 + 分批下单（月报）
# --------------------------------------------------------------------------
def build_cycles(spine: set[str]) -> tuple[list[dict], list[dict]]:
    rows = list(xlsxlite.iter_rows(str(MONTHLY), sheet_index=CYCLE_SHEET, limit=400))
    if len(rows) < 3:
        raise SystemExit("月报 sheet 读不到数据，构建中止")

    batch_dates = [xlsxlite.serial_to_date(v)
                   for v in rows[1][BATCH_COL_RANGE[0]:BATCH_COL_RANGE[1]]]
    batch_dates = [d for d in batch_dates if d]
    if len(batch_dates) != 4:
        raise SystemExit(f"分批下单日期还原失败，只得到 {batch_dates}")

    cycles, batches = [], []
    skipped: list[str] = []
    for n, r in enumerate(rows[2:]):
        if len(r) <= 19 or not str(r[4] or "").strip():
            continue
        style, comb = str(r[4]).strip(), str(r[5] or "").strip()

        # 汇总行必须挡掉。这张表最后一行是「合计」，预投 252,951 恰好等于
        # 上面所有真实行之和 —— 不挡就把整组数字翻一倍，而且比值（达成率）
        # 还是对的，所以没有任何症状。判据用两条：组合列为空、或款号是汇总词。
        # 挡掉的行打印出来，让构建过程可审。
        if not comb or style in ("合计", "小计", "总计", "汇总", "Total", "total"):
            skipped.append(f"{style}/{comb or '空组合'}")
            continue

        gid = f"{style}|{comb}"
        pre, add = i(r[8]) or 0, i(r[9]) or 0
        total, order = i(r[10]) or 0, i(r[15]) or 0
        remain, pack = i(r[16]), i(r[18])
        cid = f"C{n:04d}"
        cycles.append({
            "cycle_id": cid, "group_id": gid,
            "style_no": style, "combination": comb,
            # 不写「6 月一个月」—— 这轮覆盖多长销售期逐字稿里没答案（源表事实 §2.4）
            "period_label": "2026 年 6 月一轮",
            "order_month": "2026-06",
            "pre_invest_units": pre, "additional_units": add,
            "pre_invest_total": total, "order_total": order,
            "remaining_units": remain,
            # 达成率 = 下单÷预投（吴组长口径）。源表那列是它的补，不搬进来。
            "achieve_rate": round(order / total, 6) if total else None,
            "pack_size": pack,
            "total_tiao": i(r[19]),
            "operator": str(r[1] or "").strip(),
            "in_spine": 1 if gid in spine else 0,
            "value_origin": "direct",
        })
        for k, d in enumerate(batch_dates):
            q = i(r[BATCH_COL_RANGE[0] + k])
            if q:
                batches.append({"cycle_id": cid, "group_id": gid,
                                "batch_no": k + 1, "batch_date": d,
                                "order_units": q, "value_origin": "direct"})
    if skipped:
        print(f"  ↳ 挡掉汇总行 {len(skipped)} 行：{'、'.join(skipped)}")
    return cycles, batches


# --------------------------------------------------------------------------
# 3. 逐月预投历史（3.库存表「一组」）—— 逐子 ASIN，不是配色组
#
# ⚠️ v0.1 这里写错了：按配色组取 max，理由写的是「同一配色组的预投数在它每个
# 尺码的行上重复」。实测那个判断是**错的** —— 713 处各尺码的值不同，只有
# 101 处相同（`probe_size_level.py`）。看一眼就知道：
#     TH24AM-607 4A  S=空  M=400  L=500  XL=200  XXL=100  XXXL=空
# 这是逐尺码填的真实值。取 max 把运营真正在填的那一层压掉了。
#
# 所以预投的真实工作粒度是**子 ASIN（款号×组合×配色×尺码）**。
# 月报那张按配色组的表是考核汇总视图，不是运营的工作粒度。
# --------------------------------------------------------------------------
def build_months(children: set[str]) -> list[dict]:
    rows = list(xlsxlite.iter_rows(str(STOCK), sheet_index=MONTH_COLS_SHEET, limit=900))
    hdr = [str(h or "") for h in rows[0]]
    idx_asin = hdr.index("ASIN")
    idx_style = hdr.index("款号")
    idx_comb = hdr.index("组合")
    idx_size = hdr.index("尺码")

    # 「5月预投…12月预投」是 2025，之后「1月预投…8月预投」是 2026。
    # 靠出现顺序定年份，不靠列名 —— 列名里没有年份。补投单独一列，一起收。
    month_cols, year = [], 2025
    prev = 99
    for c, h in enumerate(hdr):
        if not (h.endswith("预投") or h.endswith("补投")) or h == "预投预计":
            continue
        m = int("".join(ch for ch in h if ch.isdigit()) or 0)
        if not m:
            continue
        if m < prev:
            year += 1 if month_cols else 0
        prev = m
        month_cols.append((c, f"{year}-{m:02d}", "补投" if "补投" in h else "预投"))

    out = []
    for r in rows[1:]:
        if len(r) <= idx_size:
            continue
        asin = str(r[idx_asin] or "").strip()
        style = str(r[idx_style] or "").strip()
        comb = str(r[idx_comb] or "").strip()
        size = str(r[idx_size] or "").strip()
        if not style or not comb:
            continue
        for c, ym, kind in month_cols:
            v = i(r[c]) if len(r) > c else None
            if not v:
                continue
            out.append({
                "child_asin": asin or None,
                "group_id": f"{style}|{comb}",
                "size": size or None,
                "month": ym, "kind": kind,
                "units": v,
                "in_spine": 1 if asin in children else 0,
                "value_origin": "direct",
            })
    return out


# --------------------------------------------------------------------------
# 4. 尺码历史销量占比（近 365 天，从产品包逐日销量聚）
# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# 5. 时间链条（吴组长口述，逐段带原话时间戳）
# --------------------------------------------------------------------------
LEADTIME = [
    {"stage": "fabric_prep", "stage_label": "备面料", "seq": 1,
     "days_min": 30, "days_max": 30,
     "note": "预投之后备面料约一个月", "quote_at": "00:56:21"},
    {"stage": "order", "stage_label": "下单", "seq": 2,
     "days_min": 0, "days_max": 0,
     "note": "面料备完通知运营，提前一个月下单", "quote_at": "01:01:33"},
    {"stage": "production", "stage_label": "生产", "seq": 3,
     "days_min": 10, "days_max": 25,
     "note": "生产周期十来天或二十几天，每个品类不一样", "quote_at": "00:56:21"},
    {"stage": "logistics", "stage_label": "物流", "seq": 4,
     "days_min": 15, "days_max": 20,
     "note": "越南生产运到美国", "quote_at": "00:59:59"},
]


# --------------------------------------------------------------------------
SCHEMA = """
create table dim_preinvest_group (
  group_id text primary key, style_no text, combination text,
  child_count integer, sizes text, category text,
  operations_group text, operator text, colorway text, lifecycle text,
  pack_size integer, unit_cost_avg real, value_origin text);
create index idx_pi_group_style on dim_preinvest_group(style_no);

create table fact_preinvest_cycle (
  cycle_id text primary key, group_id text, style_no text, combination text,
  period_label text, order_month text,
  pre_invest_units integer, additional_units integer, pre_invest_total integer,
  order_total integer, remaining_units integer, achieve_rate real,
  pack_size integer, total_tiao integer, operator text,
  in_spine integer, value_origin text);
create index idx_pi_cycle_group on fact_preinvest_cycle(group_id);

create table fact_preinvest_order_batch (
  cycle_id text, group_id text, batch_no integer, batch_date text,
  order_units integer, value_origin text,
  primary key (cycle_id, batch_no));

-- 逐子 ASIN 的历史预投/补投。**这是运营真正在填的粒度**（713 处各尺码值不同）。
create table fact_preinvest_month (
  child_asin text, group_id text, size text, month text, kind text,
  units integer, in_spine integer, value_origin text,
  primary key (child_asin, month, kind));
create index idx_pi_month_child on fact_preinvest_month(child_asin);
create index idx_pi_month_group on fact_preinvest_month(group_id, month);

create table dim_preinvest_leadtime (
  stage text primary key, stage_label text, seq integer,
  days_min integer, days_max integer, note text, quote_at text);

create table dim_preinvest_manifest (key text primary key, value text);
"""


def insert(con, table, rows):
    if not rows:
        print(f"  {table:<30} 0 行（跳过）")
        return
    cols = list(rows[0].keys())
    con.executemany(
        f"insert or replace into {table} ({','.join(cols)}) "
        f"values ({','.join('?' * len(cols))})",
        [[r[c] for c in cols] for r in rows])
    print(f"  {table:<30} {len(rows)} 行")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if OUT.exists():
        OUT.unlink()

    pcon = sqlite3.connect(f"file:{PRODUCT_DB}?mode=ro", uri=True)
    con = sqlite3.connect(OUT)
    con.executescript(SCHEMA)

    print("构建 preinvest_demo v0.1.0")
    groups = build_groups(pcon)
    spine = {g["group_id"] for g in groups}
    insert(con, "dim_preinvest_group", groups)

    cycles, batches = build_cycles(spine)
    insert(con, "fact_preinvest_cycle", cycles)
    insert(con, "fact_preinvest_order_batch", batches)
    # 逐子 ASIN 的历史预投。脊椎判据用子 ASIN，不是配色组。
    children = {r[0] for r in pcon.execute("select child_asin from dim_product_child")}
    insert(con, "fact_preinvest_month", build_months(children))
    insert(con, "dim_preinvest_leadtime", LEADTIME)

    hit = sum(1 for c in cycles if c["in_spine"])
    manifest = {
        "dataset": "preinvest_demo", "version": "v0.1.0",
        "as_of": AS_OF, "target_sales_month": TARGET_MONTH,
        "order_month": ORDER_MONTH,
        "fabric_g_per_box": round(FABRIC_G_PER_BOX, 4),
        "fabric_anchor": "客户口述 30 万盒≈200 吨（逐字稿 01:02:50）",
        "assessment_rule": "达成率 = 总下单数 ÷ 预投总数 ≥ 0.70（逐字稿 01:01:44）",
        "group_count": len(groups),
        "cycle_rows": len(cycles), "cycle_rows_in_spine": hit,
        "sources": json.dumps([
            str(PRODUCT_DB.name), str(MONTHLY.name), str(STOCK.name)],
            ensure_ascii=False),
        "caveat_cycle_period": "505,902 盒对应多长销售期客户未说明，"
                               "页面称「一轮预投周期」不写「一个月」",
        "grain_note": "预投的工作粒度是子 ASIN（款号x组合x配色x尺码）。"
                      "实测 3.库存表 逐月预投列 713 处各尺码值不同、仅 101 处相同，"
                      "所以不能按配色组聚合。月报那张按配色组的表是考核汇总视图。",
    }
    insert(con, "dim_preinvest_manifest",
           [{"key": k, "value": str(v)} for k, v in manifest.items()])

    con.commit()
    con.close()
    pcon.close()
    print(f"\n落盘 {OUT}  {OUT.stat().st_size / 1024:.1f} KB")
    print(f"配色组 {len(groups)} · 真实轮次 {len(cycles)} 行（命中脊椎 {hit}）")


if __name__ == "__main__":
    main()
