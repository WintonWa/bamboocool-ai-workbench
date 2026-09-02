#!/usr/bin/env python3
"""往返验证：Agent 写出来的东西，页面到底读不读得出来。

这是「输出格式定好了」的唯一硬证据。光写文档不算 —— 必须真造一份 Agent 输出，
让选库逻辑认它、让页面载荷带上它、让前端渲染出它的原话。

做法（全程不碰真库）：
  1. 把真库复制成一份「Agent 业务库」到 derived/keyword_agent_current.sqlite
  2. 在里面建 fact_keyword_agent_manifest，把五张判断层表的内容改成合成结论
  3. 另建旁挂账本 derived/keyword_agent_state.sqlite，写 fact_keyword_agent_run
  4. 逐条验证 agent_result.select_database() 的判定
  5. 验证 compute 装出来的载荷带上 agent_result 且拿到的是合成结论
  6. 跑完把两份文件删掉，不留痕

合成结论用一句明显不是构造脚本口气的话，这样「页面显示的是不是 Agent 那一份」
一眼可辨（要则 §11 配套边界：依赖具体判断值的门禁要用合成行，不指定活对象）。

用法：/usr/bin/python3 tests/test_keyword_agent_roundtrip.py
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import paths                      # noqa: E402
from modules.keyword import agent_result, compute, data   # noqa: E402

DERIVED = ROOT / "modules" / "keyword" / "derived"
CUR = agent_result.CURRENT_DB
LEDGER = agent_result.STATE_DB

# 一眼能认出是合成的：构造脚本不会这么说话
MARK = "【合成验证】本条由往返测试写入，用于证明前端读得到 Agent 的原话"
RUN_ID = "kwtest-2026-08-03-1"
CTX_HASH = "roundtrip-ctx-0001"

fails: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print("  [%s] %s%s" % ("PASS" if ok else "FAIL", name,
                           "" if ok else "  (" + str(detail)[:110] + ")"))
    if not ok:
        fails.append(name)


def build_agent_db(params: dict) -> None:
    """造一份 Agent 业务库 + 旁挂账本。"""
    DERIVED.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(paths.KEYWORD_DB, CUR)
    con = sqlite3.connect(CUR)
    # manifest：agent_result.select_database() 认的就是这张表
    con.executescript("""
        drop table if exists fact_keyword_agent_manifest;
        create table fact_keyword_agent_manifest (
            run_id       text primary key,
            context_hash text not null,
            params_json  text not null,
            status       text not null
        );
    """)
    con.execute(
        "insert into fact_keyword_agent_manifest values (?,?,?,?)",
        (RUN_ID, CTX_HASH, json.dumps(params, ensure_ascii=False), "completed"))
    # 把五张判断层表的上屏文案换成合成结论 —— 页面若显示旧文案就说明没读到 Agent 库
    con.execute("update fact_keyword_evidence set conclusion = ?", (MARK,))
    con.execute("update fact_keyword_daily_report set q1_traffic_result = ?", (MARK,))
    con.execute("update fact_keyword_market_change_event set label = ?", (MARK,))
    con.execute("update fact_keyword_coverage_event set label = ?", (MARK,))
    con.commit()
    con.close()

    led = sqlite3.connect(LEDGER)
    led.executescript("""
        drop table if exists fact_keyword_agent_run;
        create table fact_keyword_agent_run (
            run_id       text primary key,
            context_hash text not null,
            status       text not null
        );
    """)
    led.execute("insert into fact_keyword_agent_run values (?,?,?)",
                (RUN_ID, CTX_HASH, "completed"))
    led.commit()
    led.close()


def set_ledger(status: str, ctx: str = CTX_HASH) -> None:
    led = sqlite3.connect(LEDGER)
    led.execute("update fact_keyword_agent_run set status = ?, context_hash = ?",
                (status, ctx))
    led.commit()
    led.close()


def cleanup() -> None:
    for f in (CUR, LEDGER):
        if f.is_file():
            f.unlink()


def main() -> int:
    params = dict(agent_result.DEFAULT_AGENT_PARAMS)

    print("== 一、没有 Agent 结果时必须回落到 base ==")
    cleanup()
    sel = agent_result.select_database(paths.KEYWORD_DB, params)
    check("没有已发布结果 → status=base", sel.status == "base", sel.status)
    check("回落到的就是原库", sel.path == paths.KEYWORD_DB, sel.path)

    print("\n== 二、双方都 completed 且参数一致 → 用 Agent 那一份 ==")
    build_agent_db(params)
    sel = agent_result.select_database(paths.KEYWORD_DB, params)
    check("status=current", sel.status == "current", sel.reason)
    check("run_id 认出来了", sel.run_id == RUN_ID, sel.run_id)
    check("选中的是 Agent 库", sel.path == CUR, sel.path)

    print("\n== 三、载荷与前端能拿到 Agent 的原话 ==")
    with data.use_database(sel.path):
        con = data.connect()
        try:
            child = compute.child_page(con, "B0CBPXNC1M", _rp(params))
            ov = compute.overview_page(con, _rp(params), {})
        finally:
            con.close()
    got_ev = [e.get("conclusion") for e in (child or {}).get("evidence", {}).get("items", [])]
    check("页面三的证据结论是 Agent 写的那句",
          bool(got_ev) and all(c == MARK for c in got_ev),
          (got_ev or ["无证据"])[0])
    q1 = ((ov.get("reports") or [{}])[0]).get("q1_traffic_result")
    check("页面一日报 Q1 是 Agent 写的那句", q1 == MARK, q1)

    print("\n== 四、账本没说完成 → 不许上屏（半份结果） ==")
    set_ledger("running")
    sel = agent_result.select_database(paths.KEYWORD_DB, params)
    check("账本 running → 回落 base", sel.status == "base", sel.status)

    print("\n== 五、账本与 manifest 的 context_hash 不一致 → 不许上屏 ==")
    set_ledger("completed", ctx="another-ctx")
    sel = agent_result.select_database(paths.KEYWORD_DB, params)
    check("context_hash 不一致 → 回落 base", sel.status == "base", sel.reason)

    print("\n== 六、参数被改过 → stale，不许把当期数字配旧结论 ==")
    set_ledger("completed")
    moved = dict(params, compare="week")
    sel = agent_result.select_database(paths.KEYWORD_DB, moved)
    check("换了比较周期 → status=stale", sel.status == "stale", sel.status)
    check("stale 仍报出是哪个 run 过期了", sel.run_id == RUN_ID, sel.run_id)
    check("stale 时读的是原库不是 Agent 库", sel.path == paths.KEYWORD_DB, sel.path)

    print("\n== 七、权重改一档也要 stale ==")
    w = json.loads(json.dumps(params))
    w["weights"]["w_demand"] = 0.35
    sel = agent_result.select_database(paths.KEYWORD_DB, w)
    check("换了优先级权重 → status=stale", sel.status == "stale", sel.status)

    cleanup()
    print("\n== 八、清理后必须回到 base ==")
    sel = agent_result.select_database(paths.KEYWORD_DB, params)
    check("临时文件已删、回到 base", sel.status == "base", sel.status)
    check("Agent 库文件确实不在了", not CUR.is_file(), str(CUR))

    print("\n%d 条，失败 %d 条" % (16, len(fails)))
    if fails:
        print("失败项：" + "、".join(fails))
    return 1 if fails else 0


def _rp(params: dict) -> dict:
    """把 Agent 参数契约摊成 compute 要的 rp 形状。"""
    w = params["weights"]
    return {
        "scope": "全部",
        "compare": params["compare"],
        "weak_rank": 20,
        "collect_depth": 144,
        "streak_days": 7,
        "rank_shift": params["rank_shift"],
        "group_dedup": params["group_dedup"],
        "weights": dict(w),
    }


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        cleanup()
        raise
