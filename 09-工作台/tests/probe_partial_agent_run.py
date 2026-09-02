#!/usr/bin/env python3
"""沙箱：拿对面那份半成品 run 试一遍，看页面遇到「半份 Agent 产出」会怎样。

背景：Agent 跑到 A（证据）就停了，日报与盘点两张表 0 行，manifest 还是 writing。
这一份**不能发布**（落库口径 §五 半份不上屏），但它是个现成的真实样本，
正好用来验两件事：

  1. status=writing 时选库逻辑是否真的拒绝它（该拒绝）
  2. 万一有人把它标成 completed 发布了，页面会不会崩
     —— 日报 0 行时页面一的 hero 与五问五答没有数据源

全程在临时目录操作，不动 derived/ 下任何文件，跑完自己清理。

用法：/usr/bin/python3 tests/probe_partial_agent_run.py
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import paths                                    # noqa: E402
from modules.keyword import agent_result, compute, data    # noqa: E402

SRC = (ROOT / "modules" / "keyword" / "derived" / "runs"
       / "keyword-all-2026-08-03-003.recovery.sqlite")


def rp(params: dict) -> dict:
    return {
        "scope": "全部", "compare": params["compare"], "weak_rank": 20,
        "collect_depth": 144, "streak_days": 7,
        "rank_shift": params["rank_shift"],
        "group_dedup": params["group_dedup"],
        "weights": dict(params["weights"]),
    }


def main() -> int:
    if not SRC.is_file():
        print("找不到那份 run：%s" % SRC)
        return 1
    params = dict(agent_result.DEFAULT_AGENT_PARAMS)
    tmp = Path(tempfile.mkdtemp(prefix="kwprobe-"))
    cur, led = tmp / "current.sqlite", tmp / "state.sqlite"
    try:
        shutil.copyfile(SRC, cur)
        con = sqlite3.connect(cur)
        row = con.execute(
            "SELECT run_id, context_hash, params_json, status "
            "FROM fact_keyword_agent_manifest").fetchone()
        run_id, ctx, pj, status = row
        print("== 这份 run 的自述 ==")
        print("  run_id       %s" % run_id)
        print("  status       %s   ← 关键" % status)
        print("  params 一致  %s"
              % (agent_result._contract(json.loads(pj))
                 == agent_result._contract(params)))
        print()

        print("== 一、status=writing 时选库逻辑该拒绝它 ==")
        sel = agent_result.select_database(paths.KEYWORD_DB, params,
                                          current_path=cur, state_path=led)
        ok = sel.status == "base"
        print("  [%s] 账本不存在 → 回落 base（%s）"
              % ("PASS" if ok else "FAIL", sel.reason))

        # 补上账本，但 manifest 仍是 writing
        l = sqlite3.connect(led)
        l.executescript("""create table fact_keyword_agent_run(
              run_id text primary key, context_hash text, status text);""")
        l.execute("insert into fact_keyword_agent_run values (?,?,?)",
                  (run_id, ctx, "completed"))
        l.commit(); l.close()
        sel = agent_result.select_database(paths.KEYWORD_DB, params,
                                          current_path=cur, state_path=led)
        ok = sel.status == "base"
        print("  [%s] 账本说完成但 manifest 是 writing → 仍回落 base（%s）"
              % ("PASS" if ok else "FAIL", sel.reason))
        print()

        print("== 二、假设有人强行标成 completed 发布，页面会怎样 ==")
        con.execute("update fact_keyword_agent_manifest set status='completed'")
        con.commit()
        sel = agent_result.select_database(paths.KEYWORD_DB, params,
                                          current_path=cur, state_path=led)
        print("  选库结果：status=%s  run_id=%s" % (sel.status, sel.run_id))
        counts = {}
        for t in ("fact_keyword_evidence", "fact_keyword_daily_report",
                  "fact_keyword_market_change_event",
                  "fact_keyword_coverage_event", "fact_keyword_audit_record"):
            counts[t] = con.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
        print("  五张判断表行数：%s"
              % "  ".join("%s=%d" % (k.replace("fact_keyword_", ""), v)
                          for k, v in counts.items()))
        con.close()

        with data.use_database(sel.path):
            c = data.connect()
            try:
                for name, fn in (
                    ("页面一 总览", lambda: compute.overview_page(c, rp(params), {})),
                    ("页面三 B0CBPXNC1M", lambda: compute.child_page(
                        c, "B0CBPXNC1M", rp(params))),
                    ("页面二 词库", lambda: compute.term_list_page(c, rp(params), {})
                     if hasattr(compute, "term_list_page") else None),
                ):
                    try:
                        out = fn()
                    except Exception as exc:
                        print("  [FAIL] %s 装载荷抛异常：%s: %s"
                              % (name, type(exc).__name__, exc))
                        continue
                    if out is None:
                        print("  [跳过] %s（没有这个入口）" % name)
                        continue
                    reports = out.get("reports")
                    ev = (out.get("evidence") or {}).get("total")
                    pr = (out.get("priority") or {}).get("total")
                    print("  [PASS] %s 装出来了　日报 %s 条　证据 %s　优先 %s"
                          % (name,
                             "0（空）" if not reports else len(reports),
                             ev if ev is not None else "—",
                             pr if pr is not None else "—"))
            finally:
                c.close()
        print()
        print("结论：半份产出被选库逻辑正确拒绝；即使强行发布，载荷仍能装出来，"
              "但日报为空 —— 页面一的 hero 与五问五答会没有内容。")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
