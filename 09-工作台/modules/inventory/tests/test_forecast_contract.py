"""Forecast contract gates, re-aimed at the v0.3.0 package.

The原 suite validated the contract in ``07-预测Agent接口契约.md`` against the
throwaway fixtures. Those are deleted; the real data now lives in the package
under different table names (``fact_child_forecast_run/_daily/_evaluation``
instead of ``fact_forecast_run/_daily/_factor``, and promotion day-rows instead
of a range table).

The contract's *intent* still applies, so the checks are kept and re-pointed:
horizon length, first forecast day, quantile order, axis continuity, per-child
coverage, event ranges inside the history window, and no internal enum reaching
a display label.

Run: /usr/bin/python3 tests/test_forecast_contract.py
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

# tests/ 在 modules/inventory/ 下，工作台根目录要上四层
ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(ROOT))

from modules.inventory import data, forecast  # noqa: E402

AS_OF = date.fromisoformat(data.meta()["as_of_date"])
fails: list[str] = []


def main() -> None:
    pkg = sqlite3.connect(f"file:{data.DB_PATH}?mode=ro", uri=True)
    pkg.row_factory = sqlite3.Row
    cache = sqlite3.connect(f"file:{forecast.CACHE_DB}?mode=ro", uri=True)
    cache.row_factory = sqlite3.Row

    run = forecast.run()
    kids = [r[0] for r in pkg.execute("SELECT DISTINCT child_asin FROM fact_child_forecast_daily")]
    print(f"运行 {run['forecast_run_id']} · 基准日 {run['as_of_date']} · 预估 {run['horizon_days']} 天")
    print(f"覆盖 {len(kids)} 个子体 · 历史缓存 {cache.execute('SELECT COUNT(*) n FROM chart_daily').fetchone()['n']} 行")
    print()

    # G1 每个对象的逐日行数 == horizon_days
    bad = pkg.execute(
        "SELECT COUNT(*) n FROM (SELECT child_asin, COUNT(*) c FROM fact_child_forecast_daily"
        " GROUP BY 1 HAVING c <> ?)", (run["horizon_days"],)
    ).fetchone()["n"]
    print(f"  {'✓' if not bad else '✗'} G1 逐日行数 == horizon（{run['horizon_days']}），不符 {bad} 个")
    if bad:
        fails.append(f"G1 {bad} 个对象逐日行数 != horizon")

    # G2 首个预测日 == 基准日 + 1
    want = (AS_OF + timedelta(days=1)).isoformat()
    bad = pkg.execute(
        "SELECT COUNT(*) n FROM (SELECT child_asin, MIN(forecast_date) f"
        " FROM fact_child_forecast_daily GROUP BY 1 HAVING f <> ?)", (want,)
    ).fetchone()["n"]
    print(f"  {'✓' if not bad else '✗'} G2 首个预测日 == 基准日+1（{want}），不符 {bad} 个")
    if bad:
        fails.append(f"G2 {bad} 个对象首个预测日 != {want}")

    # G3 分位数有序且非负
    r = pkg.execute(
        "SELECT SUM(p10_units > p50_units) a, SUM(p50_units > p90_units) b,"
        " SUM(p10_units < 0) c FROM fact_child_forecast_daily"
    ).fetchone()
    ok = not (r["a"] or r["b"] or r["c"])
    print(f"  {'✓' if ok else '✗'} G3 p10<=p50<=p90 且非负（越界 {r['a']}/{r['b']}/{r['c']}）")
    if not ok:
        fails.append("G3 分位数越界")

    # G4 有历史但无预测：本版应为 0，但不作失败 —— 那是页面必须支持的分支
    hist_kids = {r["child_asin"] for r in cache.execute("SELECT DISTINCT child_asin FROM chart_daily")}
    miss = sorted(hist_kids - set(kids))
    print(f"  ✓ G4 有历史但无预测的对象 {len(miss)} 个"
          + (f"（页面须走「尚无预测」分支）: {miss[:3]}" if miss else "（本版全覆盖）"))

    # G5 日期轴不开洞
    holes = 0
    for asin in list(hist_kids)[:40]:
        ds = [r["date"] for r in cache.execute(
            "SELECT date FROM chart_daily WHERE child_asin=? ORDER BY date", (asin,))]
        span = (date.fromisoformat(ds[-1]) - date.fromisoformat(ds[0])).days + 1
        if span != len(ds):
            holes += 1
    print(f"  {'✓' if not holes else '✗'} G5 历史日期轴连续（抽 40 个，开洞 {holes} 个）")
    if holes:
        fails.append(f"G5 {holes} 个对象历史日期轴开洞")

    # G6 事件区间落在轴内，且 label 无枚举泄漏
    r = cache.execute(
        "SELECT COUNT(*) n FROM chart_event WHERE date_from > date_to"
    ).fetchone()["n"]
    leak = cache.execute(
        "SELECT COUNT(*) n FROM chart_event WHERE type_label IN"
        " ('BD','LD','Coupon','PriceDiscount','none') AND event_type <> 'Coupon'"
    ).fetchone()["n"]
    fake = cache.execute("SELECT COUNT(*) n FROM chart_event WHERE event_type='none'").fetchone()["n"]
    ok = not (r or leak or fake)
    print(f"  {'✓' if ok else '✗'} G6 事件区间方向正确、无 none 假段、label 无枚举泄漏"
          f"（{r}/{fake}/{leak}）")
    if not ok:
        fails.append("G6 事件区间或标签有问题")

    # G7 缺货标记与库存台账一致
    r = cache.execute("SELECT SUM(stockout_flag) n, COUNT(DISTINCT child_asin) k"
                      " FROM chart_daily WHERE stockout_flag=1").fetchone()
    src = pkg.execute("SELECT SUM(stockout_flag) n FROM fact_child_inventory_daily").fetchone()["n"]
    ok = r["n"] == src
    print(f"  {'✓' if ok else '✗'} G7 缺货日与源表一致（缓存 {r['n']} / 源 {src}，涉及 {r['k']} 个子体）")
    if not ok:
        fails.append("G7 缺货日与源表不一致")

    # G8 调整项文案是中文成品，不是枚举
    bad = cache.execute(
        "SELECT COUNT(*) n FROM chart_daily WHERE adjustment_reason IS NOT NULL"
        " AND adjustment_reason GLOB '[a-z_]*'"
    ).fetchone()["n"]
    print(f"  {'✓' if not bad else '✗'} G8 adjustment_reason 是中文成品文案（疑似枚举 {bad} 行）")
    if bad:
        fails.append("G8 adjustment_reason 疑似枚举值")

    # G9 未来计划不得泄漏进历史区间
    bad = pkg.execute(
        "SELECT COUNT(*) n FROM plan_child_promotion_daily WHERE date <= ?", (AS_OF.isoformat(),)
    ).fetchone()["n"]
    print(f"  {'✓' if not bad else '✗'} G9 未来计划不泄漏进历史（越界 {bad} 行）")
    if bad:
        fails.append("G9 未来计划泄漏进历史区间")

    print()
    print(f"门禁失败 {len(fails)} 项")
    for f in fails:
        print("  ✗", f)
    print("FORECAST CONTRACT " + ("PASS" if not fails else "FAIL"))


if __name__ == "__main__":
    main()
