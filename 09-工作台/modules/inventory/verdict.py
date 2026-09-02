"""盘点结论：五条。

设计见 01-方案与数据需求/10-盘点结论Agent接口契约.md v0.2。

两条来源，**同一个形状**，所以页面代码不用分支：
  1. 结论库 verdict_agent.sqlite 的最新一次 run（Agent 跑出来的）
  2. 本文件的确定性规则（Agent 还没跑过这个对象时的兜底）

形状统一是有意的：接真 Agent 那天，页面一行都不用改。

**这里不重算任何数字。** 数字全部取自 compute.assess() 已经算好的结果，
本文件只做定性、排序、措辞。理由见契约 §3：数字要能追到表和字段才可核验，
而且阈值一调必须当场跟着变。

在途那一条走 B 方案（契约 §7）：只判「来不来得及」，
`有逾期` 那一档暂不启用 —— v0.3.0 的 684 笔 ETA 全晚于基准日，
逾期实例为零，且表里没有实收/缺损/延误任何字段，编不出来。
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

# 结论库。Agent 写、页面只读。产品包只读不动 —— 两库分开，
# 所以「v0.3.0 当静态快照不做回填」那条决定不受影响。
VERDICT_DB = Path(__file__).resolve().parent / "derived" / "verdict_agent.sqlite"

BLOCKS = ("safety", "stockout", "in_transit", "overstock", "storage_fee")

BLOCK_LABEL = {
    "safety": "库存是否安全",
    "stockout": "什么时候断货",
    "in_transit": "在途货件",
    "overstock": "库存积压",
    "storage_fee": "仓储费",
}

# state 只能取这些。不在词表内页面会落灰色兜底 ——
# 库存模块踩过一次（泳道颜色键大小写不符导致所有泳道同色）。
STATES = {
    "safety": ("安全", "偏紧", "不安全"),
    "stockout": ("窗口内不断货", "即将断货", "已断货"),
    "in_transit": ("正常", "来不及", "有逾期", "无在途"),
    "overstock": ("正常", "偏多", "积压"),
    "storage_fee": ("正常", "偏高"),
}

# 每个 state 的严重度，决定排序与颜色。数越大越靠前。
SEVERITY = {
    "不安全": 3, "已断货": 3, "有逾期": 3, "积压": 3,
    "偏紧": 2, "即将断货": 2, "来不及": 2, "偏多": 2, "偏高": 2,
    "安全": 0, "窗口内不断货": 0, "正常": 0, "无在途": 0,
}

TONE = {3: "alert", 2: "warn", 0: "good"}


def _d(iso: str | None) -> date | None:
    try:
        return date.fromisoformat(iso) if iso else None
    except (TypeError, ValueError):
        return None


def _stamp(raw: str | None) -> datetime:
    """把写入方给的 created_at 解析成可比较的时刻。

    **不能按字符串比。** 实测 Agent 两次运行给了两种格式：
    `2026-08-30T22:56:12.869Z`（UTC 带 Z）与 `2026-08-31T06:57:01`（本地无偏移），
    两者实际都是本地 08-31 06:56/06:57。字符串排序会把带 Z 的判成 08-30，
    于是更新的结果被更旧的盖掉，而这种错误在界面上没有任何症状。

    契约要求写入方给 ISO 8601 带偏移，但读取端保持宽容：
    写入方格式不齐是常态，读取端硬要求只会变成「数据没错但页面读不到」。
    """
    t = (raw or "").strip().replace("Z", "+00:00").replace(" ", "T")
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
    return dt.astimezone() if dt.tzinfo is None else dt


def _md(iso: str | None) -> str:
    """2026-08-28 -> 08-28。结论里说日期不必带年，基准日就在顶栏。"""
    return iso[5:] if iso and len(iso) == 10 else (iso or "—")


# ---------------------------------------------------------------------------
# 确定性五条
# ---------------------------------------------------------------------------

def _safety(a: dict, as_of: date) -> dict:
    pj = a.get("projection") or {}
    scopes = pj.get("scopes") or {}
    only = scopes.get("sellable_only") or {}
    plus = scopes.get("sellable_plus_confirmed") or {}
    safety_days = pj.get("safety_days")
    cover_only = only.get("cover_days")
    cover_plus = plus.get("cover_days")
    breach = plus.get("safety_breach_date") or only.get("safety_breach_date")
    stockout = plus.get("stockout_date") or only.get("stockout_date")

    nums = {"cover_days_sellable": cover_only, "cover_days_with_arrivals": cover_plus,
            "safety_days": safety_days, "safety_breach_date": breach, "stockout_date": stockout}

    if not pj.get("available"):
        return _item("safety", "偏紧", "缺库存快照，安全性无法判断。", None, ["inventory"], nums)

    if stockout:
        state = "不安全"
        verdict = (f"未来 90 天不够：可售只够 {_n(cover_only)} 天，"
                   f"{_md(stockout)} 见底。")
    elif breach:
        state = "偏紧"
        verdict = (f"够用但会跌破安全线：{_md(breach)} 低于 {safety_days} 天安全库存，"
                   f"窗口内不断货。")
    else:
        state = "安全"
        verdict = f"未来 90 天够用，覆盖 {_n(cover_plus or cover_only)} 天，未跌破安全线。"

    because = (f"可售口径覆盖 {_n(cover_only)} 天；把已确认到货算进来是 {_n(cover_plus)} 天。"
               f"安全库存 {safety_days} 天。")
    return _item("safety", state, verdict, because, ["inventory", "projection"], nums)


def _stockout(a: dict, as_of: date) -> dict:
    pj = a.get("projection") or {}
    scopes = pj.get("scopes") or {}
    plus = scopes.get("sellable_plus_confirmed") or {}
    only = scopes.get("sellable_only") or {}
    so = plus.get("stockout_date") or only.get("stockout_date")
    rng = plus.get("stockout_date_range") or only.get("stockout_date_range") or {}
    nums = {"stockout_date": so, "range_p10": rng.get("p10"), "range_p90": rng.get("p90")}

    if not so:
        return _item("stockout", "窗口内不断货", "90 天窗口内不会断货。", None,
                     ["projection"], nums)

    dd = _d(so)
    days = (dd - as_of).days if dd else None
    band = ""
    if rng.get("p10") and rng.get("p90") and rng["p10"] != rng["p90"]:
        band = f"需求走高到 p90 会提前到 {_md(rng['p10'])}，走低则推到 {_md(rng['p90'])}。"

    if days is not None and days <= 0:
        state, verdict = "已断货", f"已经断货（{_md(so)}）。"
    elif days is not None and days <= 14:
        state, verdict = "即将断货", f"{days} 天后断货（{_md(so)}）。"
    else:
        state, verdict = "即将断货", f"{_md(so)} 断货，还有 {days} 天。"

    return _item("stockout", state, verdict, band or None, ["projection"], nums)


def _in_transit(a: dict, as_of: date) -> dict:
    """B 方案：只判来不来得及。有逾期那一档不启用，理由见文件头。"""
    pj = a.get("projection") or {}
    arrivals = list(pj.get("arrivals") or [])
    scopes = pj.get("scopes") or {}
    so = ((scopes.get("sellable_plus_confirmed") or {}).get("stockout_date")
          or (scopes.get("sellable_only") or {}).get("stockout_date"))
    so_d = _d(so)

    nums = {"arrival_count": len(arrivals),
            "confirmed_qty": pj.get("confirmed_arrival_qty"),
            "planned_qty": pj.get("planned_arrival_qty"),
            "stockout_date": so}

    if not arrivals:
        return _item("in_transit", "无在途", "没有在途货件。", None, ["projection"], nums)

    first = min(arrivals, key=lambda x: x.get("eta") or "9999-12-31")
    nums["first_eta"] = first.get("eta")
    nums["first_units"] = first.get("units")

    gap = None
    if so_d:
        fe = _d(first.get("eta"))
        if fe:
            gap = (fe - so_d).days
            nums["gap_days"] = gap

    if gap is not None and gap > 0:
        # 这就是设计文档第 1 节那个矛盾：覆盖天数把在途算进来了，但货来得比断货晚。
        state = "来不及"
        verdict = (f"货在路上但来不及：{_md(so)} 断货，最近一批 {first.get('units')} 件 "
                   f"{_md(first.get('eta'))} 才到，中间空 {gap} 天。")
    else:
        state = "正常"
        verdict = (f"{len(arrivals)} 笔在途共 "
                   f"{_n0(_num(pj.get('confirmed_arrival_qty')) + _num(pj.get('planned_arrival_qty')))} 件，"
                   f"最近一批 {_md(first.get('eta'))} 到。")

    because = "；".join(
        f"{x.get('status_label')} {x.get('units')} 件 {x.get('mode_label')} 预计 {_md(x.get('eta'))}"
        f"{'（未计入覆盖）' if not x.get('counted') else ''}"
        for x in sorted(arrivals, key=lambda x: x.get("eta") or "")[:4]
    )
    return _item("in_transit", state, verdict, because or None, ["projection"], nums)


def _overstock(a: dict, as_of: date) -> dict:
    pj = a.get("projection") or {}
    ag = a.get("aging") or {}
    excess = _num(pj.get("excess_qty"))
    dep = pj.get("depletion_days")
    aged = _num(ag.get("aged_181_qty"))
    share = ag.get("aged_181_share")
    nums = {"excess_qty": excess, "depletion_days": dep,
            "reasonable_max_qty": pj.get("reasonable_max_qty"),
            "aged_181_qty": aged, "aged_181_share": share}

    if excess > 0 and aged > 0:
        state = "积压"
        verdict = (f"超量 {_n0(excess)} 件，其中 181 天以上 {_n0(aged)} 件"
                   f"（{_pc(share)}）。")
    elif excess > 0:
        state = "偏多"
        verdict = f"超量 {_n0(excess)} 件，消化约 {_n(dep)} 天。"
    elif aged > 0:
        state = "偏多"
        verdict = f"总量正常，但 181 天以上有 {_n0(aged)} 件（{_pc(share)}）。"
    else:
        state = "正常"
        verdict = f"没有超量，消化约 {_n(dep)} 天。"

    because = (f"合理上限 {_n0(_num(pj.get('reasonable_max_qty')))} 件，"
               f"按预估日均折算消化 {_n(dep)} 天。")
    return _item("overstock", state, verdict, because, ["aging", "projection"], nums)


def _storage_fee(a: dict, as_of: date) -> dict:
    fe = a.get("fee") or {}
    total = _num(fe.get("total_fee"))
    aged = _num(fe.get("aged_surcharge"))
    sr = fe.get("sales_ratio")
    gr = fe.get("gross_ratio")
    nums = {"total_fee": total, "aged_surcharge": aged, "sales_ratio": sr, "gross_ratio": gr}

    if not fe.get("available"):
        return _item("storage_fee", "正常", "缺体积或库龄数据，仓储费未估算。", None, ["fee"], nums)

    hits = []
    if aged > 0:
        hits.append(f"含超龄附加 ${aged:,.0f}")
    if gr is not None and gr > 0.10:
        hits.append(f"占毛利 {_pc(gr)}")
    if sr is not None and sr > 0.03:
        hits.append(f"占销售额 {_pc(sr)}")

    money = f"${total:,.2f}" if total < 100 else f"${total:,.0f}"
    if hits:
        state, verdict = "偏高", f"估算 {money}，{'、'.join(hits)}。"
    else:
        state, verdict = "正常", f"估算 {money}，占销售额 {_pc(sr)}。"

    return _item("storage_fee", state, verdict,
                 f"基础费 ${_num(fe.get('regular_fee')):,.2f}，超龄附加 ${aged:,.2f}。",
                 ["fee"], nums)


def _item(block: str, state: str, verdict: str, because: str | None,
          refs: list[str], numbers: dict) -> dict:
    assert state in STATES[block], f"{block} 的 state {state!r} 不在词表内"
    sev = SEVERITY[state]
    return {
        "block": block,
        "label": BLOCK_LABEL[block],
        "state": state,
        "tone": TONE[sev],
        "severity": sev,
        "verdict": verdict,
        "because": because,
        "refs": refs,
        "numbers": {k: v for k, v in numbers.items() if v is not None},
    }


BUILDERS = {"safety": _safety, "stockout": _stockout, "in_transit": _in_transit,
            "overstock": _overstock, "storage_fee": _storage_fee}


def deterministic(a: dict, as_of: date) -> list[dict]:
    """五条，全部由确定性规则给出。Agent 没跑过时用这个。"""
    return [BUILDERS[b](a, as_of) for b in BLOCKS]


# ---------------------------------------------------------------------------
# 结论库：读最新一次 run
# ---------------------------------------------------------------------------

_local = threading.local()


def available() -> bool:
    return VERDICT_DB.is_file()


def _con() -> sqlite3.Connection | None:
    """线程局部只读连接。不能用 @lru_cache 缓存成全局单例 ——
    ThreadingHTTPServer 下两个线程共用一个 SQLite 连接会偶发
    database disk image is malformed（外壳交接件点名的那条）。"""
    if not available():
        return None
    con = getattr(_local, "vd", None)
    if con is None:
        con = sqlite3.connect(f"file:{VERDICT_DB}?mode=ro", uri=True, check_same_thread=False)
        con.row_factory = sqlite3.Row
        _local.vd = con
    return con


def latest(child_asin: str) -> dict | None:
    """取该对象最新一次 run 及其五条。

    先按 run_date 取最新那天，再在同一天的记录里按**解析后的 created_at** 选最晚。
    **不读 is_latest 标记位** —— 中断的运行会留下两个 1，页面会静默读错
    且没有任何症状（07 契约 §2.1 的理由）。
    **也不按 created_at 的字符串比** —— 见 _stamp() 的注释，实测踩到过。
    """
    con = _con()
    if con is None:
        return None
    try:
        # SQL 只按 run_date 粗筛（纯日期，没有格式歧义），最新一条在 Python 里按
        # 解析后的时刻选 —— created_at 的格式由写入方决定，字符串比不可靠。
        cands = con.execute(
            "SELECT * FROM fact_child_verdict_run WHERE child_asin = ? "
            "ORDER BY run_date DESC LIMIT 20", (child_asin,)
        ).fetchall()
        if not cands:
            return None
        top_date = cands[0]["run_date"]
        same_day = [r for r in cands if r["run_date"] == top_date]
        run = max(same_day, key=lambda r: _stamp(r["created_at"]))
        rows = con.execute(
            "SELECT * FROM fact_child_verdict_item WHERE run_id = ? ORDER BY ord", (run["run_id"],)
        ).fetchall()
    except sqlite3.Error:
        return None            # 结论库坏了不该打掉整页，退回确定性规则
    if not rows:
        return None

    items = []
    for r in rows:
        block = r["block"]
        state = r["state"]
        if block not in STATES or state not in STATES[block]:
            return None        # 不合词表的输出整份丢弃，宁可退回规则也不上灰色兜底
        sev = SEVERITY[state]
        items.append({
            "ord": r["ord"],
            "block": block, "label": BLOCK_LABEL[block], "state": state,
            "tone": TONE[sev], "severity": sev,
            "verdict": r["verdict"], "because": r["because"],
            "refs": json.loads(r["refs"] or "[]"),
            "numbers": json.loads(r["numbers"] or "{}"),
        })
    if {i["block"] for i in items} != set(BLOCKS):
        return None            # 五条不齐也整份丢弃
    return {"run": dict(run), "items": items}


# ---------------------------------------------------------------------------
# 合并：Agent 有就用它，没有就用规则
# ---------------------------------------------------------------------------

def build(a: dict, as_of: date) -> dict:
    got = latest(a.get("child_asin") or "")
    if got:
        # Agent 已按契约给出优先级 ord；页面必须尊重这个顺序，不能再用
        # 本地严重度重排，否则“有契约的数字”到了前端仍会变序。
        items = sorted(got["items"], key=lambda x: x["ord"])
        run = got["run"]
        return {
            "origin": "agent",
            "run": {"run_id": run.get("run_id"), "run_date": run.get("run_date"),
                    "created_at": run.get("created_at"), "trigger": run.get("trigger"),
                    "trigger_label": {"manual": "手动", "weekly": "定时", "priority": "重点对象"}
                                     .get(run.get("trigger"), "—")},
            "items": items,
        }
    items = sorted(deterministic(a, as_of),
                   key=lambda x: (-x["severity"], BLOCKS.index(x["block"])))
    return {"origin": "rules", "run": None, "items": items}


# ---- 小工具 ----------------------------------------------------------------

def _num(v: Any) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _n(v: Any) -> str:
    return "—" if v is None else f"{float(v):,.1f}"


def _n0(v: Any) -> str:
    return "—" if v is None else f"{float(v):,.0f}"


def _pc(v: Any) -> str:
    return "—" if v is None else f"{float(v) * 100:.1f}%"
