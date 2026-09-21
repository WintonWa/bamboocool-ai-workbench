#!/usr/bin/env python3
"""把预投链条的真实数字算出来。

三件事：
  1. 「预投比」这列到底是什么口径 —— 用恒等式反证，不靠列名猜
  2. 70% 考核的真实达成率分布（142 行 · 一组 6 月）
  3. 4 个无名列的日期序列号还原 + 3.库存表「一组」逐月预投列的填充率

只读。
"""
from __future__ import annotations

import statistics
import sys

sys.path.insert(0, "/Users/linsen/BAM/04-广告分析模块/00-源表勘查")
import xlsxlite  # noqa: E402

MONTHLY = ("/Users/linsen/BAM/数据源/AI广告对接数据-总20260803/"
           "14.其他分析文件/2026年月报/6月/一组6月月报.xlsx")
STOCK = ("/Users/linsen/BAM/数据源/AI广告对接数据-总20260803/"
         "3.库存表-物流管理表.xlsx")


def f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main() -> None:
    rows = list(xlsxlite.iter_rows(MONTHLY, sheet_index=4, limit=400))

    print("=== 4 个无名列的日期序列号 ===")
    for v in (rows[1][11:15] if len(rows) > 1 else []):
        print(f"  {v} -> {xlsxlite.serial_to_date(v)}")

    data = [r for r in rows[2:] if len(r) > 17 and str(r[4] or "").strip()]
    print(f"\n=== 有效行 {len(data)} ===")

    # 口径反证：表里的「预投比」是 剩余÷预投总数 还是 下单÷预投总数？
    hit_remain = hit_order = 0
    for r in data:
        pre, order, remain, ratio = f(r[10]), f(r[15]), f(r[16]), f(r[17])
        if not pre or ratio is None:
            continue
        if remain is not None and abs(ratio - remain / pre) < 1e-9:
            hit_remain += 1
        if order is not None and abs(ratio - order / pre) < 1e-9:
            hit_order += 1
    print(f"预投比 == 剩余数÷预投总数 : {hit_remain} 行命中")
    print(f"预投比 == 总下单数÷预投总数: {hit_order} 行命中")

    # 恒等式：预投总数 = 预投数 + 追加数 ? 剩余 = 预投总数 - 总下单 ?
    ok_total = sum(1 for r in data
                   if f(r[10]) is not None
                   and abs((f(r[10]) or 0) - ((f(r[8]) or 0) + (f(r[9]) or 0))) < 1e-6)
    ok_remain = sum(1 for r in data
                    if f(r[16]) is not None
                    and abs((f(r[16]) or 0) - ((f(r[10]) or 0) - (f(r[15]) or 0))) < 1e-6)
    ok_tiao = sum(1 for r in data
                  if f(r[19]) is not None
                  and abs((f(r[19]) or 0) - (f(r[10]) or 0) * (f(r[18]) or 0)) < 1e-6)
    print(f"预投总数 = 预投数+追加数 : {ok_total}/{len(data)}")
    print(f"剩余数   = 预投总数-总下单数: {ok_remain}/{len(data)}")
    print(f"总条数   = 预投总数x单包条数: {ok_tiao}/{len(data)}")

    # 70% 考核达成率 = 总下单数 ÷ 预投总数
    live = [(str(r[4]), str(r[5]), f(r[10]) or 0.0, f(r[15]) or 0.0)
            for r in data if (f(r[10]) or 0) > 0]
    print(f"\n=== 预投总数 > 0 的行：{len(live)}（其余 {len(data) - len(live)} 行"
          f"预投=0，表里预投比是 #DIV/0!）===")
    rates = [o / p for _, _, p, o in live]
    pass70 = [x for x in rates if x >= 0.70]
    print(f"达成率(总下单÷预投总数)  中位 {statistics.median(rates):.1%}  "
          f"均值 {statistics.mean(rates):.1%}  最低 {min(rates):.1%}  最高 {max(rates):.1%}")
    print(f"达标(>=70%)：{len(pass70)}/{len(rates)} = {len(pass70)/len(rates):.1%}")
    tot_p = sum(p for _, _, p, _ in live)
    tot_o = sum(o for _, _, _, o in live)
    print(f"组级汇总：预投 {tot_p:,.0f} 盒  下单 {tot_o:,.0f} 盒  "
          f"整组达成率 {tot_o/tot_p:.1%}  面料闲置 {tot_p - tot_o:,.0f} 盒")

    print("\n--- 达成率最低的 10 个配色组（最浪费的）---")
    for kh, zh, p, o in sorted(live, key=lambda x: x[3] / x[2])[:10]:
        print(f"  {kh}-{zh:<3} 预投 {p:>9,.0f}  下单 {o:>9,.0f}  "
              f"达成 {o/p:>6.1%}  闲置 {p-o:>9,.0f} 盒")

    # 3.库存表「一组」逐月预投列
    print("\n=== 3.库存表「一组」逐月预投列填充率 ===")
    srows = list(xlsxlite.iter_rows(STOCK, sheet_index=0, limit=900))
    hdr = srows[0]
    idxs = [(i, str(h)) for i, h in enumerate(hdr)
            if h and ("预投" in str(h) or "建议" in str(h) or "翻单" in str(h))]
    body = [r for r in srows[1:] if len(r) > 10 and str(r[1] or "").strip()]
    print(f"数据行 {len(body)}")
    for i, name in idxs:
        vals = [f(r[i]) for r in body if len(r) > i]
        nz = [v for v in vals if v not in (None, 0.0)]
        print(f"  col{i:<3} {name:<16} 非零 {len(nz):>4}/{len(body)} "
              f"({len(nz)/len(body):>5.1%})  合计 {sum(nz):>12,.0f}")


if __name__ == "__main__":
    main()
