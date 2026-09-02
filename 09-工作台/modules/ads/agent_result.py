"""Read validated advertising Agent runs from the writable sidecar.

The advertising source package remains read-only.  This reader never falls
back to the old deterministic replay: an absent, stale, incomplete or damaged
run is surfaced as ``待确认`` so the page cannot mistake a fixture for Pi.

2026-08-31 v2：读取层从 ``fact_ads_agent_stage`` + ``fact_ads_agent_item``
切到 ``fact_ads_agent_output``，按 ``output_point`` 分组。分工见
``00-通用方法与规范/09-广告Agent重建两侧分工.md``。

重建期间八个输出点会分批到位，所以这里区分两种不完整：

* 一个输出点都没有 → ``待确认``，页面什么都不显示
* 有一部分 → 正常返回已到位的那些，并在 ``pending_points`` 里报出还缺哪些

第二种是重建期间的常态，不能当失败——否则第一步验接缝时页面永远是空的。
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parent / "derived" / "ads_agent_state.sqlite"

# 九个输出点与上屏用的段落标题。标题由前端给，Agent 不写 label，
# 写两边必然不一致（分工文档 §1.2）。
POINT_LABEL = {
    "A1": "广告目的标签建议",
    "B0b": "目标约束分档",
    "B0cd": "词与竞品判断",
    "B0e": "结构问题识别",
    "B1": "应有广告任务",
    "B2": "任务与结构对照",
    "B3": "广告诊断与优先级",
    "B3b": "诊断覆盖说明",
    "B4": "广告调整方案",
}
# 一条完整的子 ASIN 决策链要齐的八个点
DECISION_POINTS = ("B0b", "B0cd", "B0e", "B1", "B2", "B3", "B3b", "B4")
# 页面二四段揭示读的是这四个；B0b/B0cd/B0e 落在板块 2/3/5
STAGE_POINTS = ("B1", "B2", "B3", "B4")
STAGE_ALIAS = {"B1": "task", "B2": "mapping", "B3": "diagnosis",
               "B4": "proposal"}


def _pending(subject: str, message: str, **extra) -> dict:
    return {
        "condition": "待确认",
        "source": "Pi Agent",
        "child_asin": subject,
        "message": message,
        "stages": [],
        "points": {},
        "pending_points": list(DECISION_POINTS),
        "diagnosis_coverage": [],
        **extra,
    }


def _open():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def latest(child_asin: str, current_hash: str,
           requested_hash: str | None = None,
           objects: dict | None = None) -> dict:
    """子 ASIN 决策链：读最新一次 completed 的 child_decision 运行。

    ``objects`` 是 ``{ad_object_id: {name, campaign, ad_type, purpose,
    attribution_days, metrics}}``，由调用方（module.py）从事实层取好传进来。
    Agent 只写 ``ad_object_id``（它不该输出展示字段），对象名、Campaign、
    月度指标这些由读取层补全——两边职责分开，也避免 Agent 输出中文。
    """
    if requested_hash and requested_hash != current_hash:
        return _pending(
            child_asin,
            "页面依据已经变化，请刷新页面后再读取 Agent 结果",
            context_hash_matched=False,
            current_context_hash=current_hash,
        )
    if not DB.is_file():
        return _pending(child_asin,
                        "该对象尚未运行，请先执行本地广告 Agent Runner")
    try:
        con = _open()
        run = con.execute(
            "SELECT * FROM fact_ads_agent_run"
            " WHERE (subject_id=? OR child_asin=?)"
            "   AND (run_type IS NULL OR run_type='child_decision')"
            "   AND status='completed'"
            " ORDER BY created_at DESC, completed_at DESC LIMIT 1",
            (child_asin, child_asin),
        ).fetchone()
        if run is None:
            con.close()
            return _pending(child_asin, "该对象尚未完成真实 Agent 运行")
        rows = con.execute(
            "SELECT output_point, point_ord, item_ord, item_id, payload"
            " FROM fact_ads_agent_output WHERE run_id=?"
            " ORDER BY point_ord, item_ord", (run["run_id"],)).fetchall()
        con.close()

        # hash 不同就是不能用，不再猜是「口径不一致」还是「依据变了」。
        # 原来拿「依据 id 里有没有冒号」当判据是启发式，不可靠——
        # id 换成点号命名就失效，而且它本来就不该由 id 形态来推断。
        # 方案 1 定了 hash 只由工作台算、Runner 原样存，所以正常情况下
        # 两者必然相等；不等只有两种原因，处理方式都是重跑：
        #   数据包版本 / 规则参数 / 运营目标变了
        #   Runner 没按约定原样取走 hash
        # 另外校验口径版本：hash 算法本身改过就直接判不兼容。
        hash_ok = run["context_hash"] == current_hash

        points: dict[str, list] = {}
        order: dict[str, int] = {}
        for r in rows:
            p = r["output_point"]
            if p not in POINT_LABEL:
                raise ValueError("unknown output_point %s" % p)
            item = json.loads(r["payload"])
            # B2/B4 只给 ad_object_id，展示用的对象数据由读取层补。
            # 补不到就置 None，前端据此显示「当前没有广告对象承接」——
            # 那是结论不是渲染失败，所以不能兜个空对象糊过去。
            if p in ("B2", "B4") and objects is not None:
                oid = item.get("ad_object_id")
                item["ad_object"] = objects.get(oid) if oid else None
            points.setdefault(p, []).append(item)
            order.setdefault(p, r["point_ord"] or 99)
        if not points:
            return _pending(child_asin, "本次运行没有落下任何结果")

        # hash 不符一律不能当有效结果用。
        # 唯一例外是接缝联调期：显式开 WORKBENCH_ADS_SEAM=1 才旁路，
        # 且页面上必须标出来（前端读 seam_bypass 画红 chip）。
        # 默认关，所以不会有人不知不觉看着一份对不上的结果做演示。
        seam = os.environ.get("WORKBENCH_ADS_SEAM") == "1"
        if not hash_ok and not seam:
            return _pending(
                child_asin,
                "Agent 结果与当前页面依据不一致，需要在本地重新运行",
                run_id=run["run_id"], context_hash=run["context_hash"],
                current_context_hash=current_hash,
                context_hash_matched=False)

        missing = [p for p in DECISION_POINTS if p not in points]
        stages = [
            {"stage": STAGE_ALIAS[p], "point": p, "label": POINT_LABEL[p],
             "items": points[p]}
            for p in STAGE_POINTS if p in points
        ]
        notes = []
        if not hash_ok:
            notes.append("接缝联调旁路已开：这份结果的依据指纹与页面不一致，"
                         "只用于验证字段能否上屏，不是有效结论")
        if missing:
            notes.append("本次运行已产出 %s，还缺 %s"
                         % ("、".join(POINT_LABEL[p] for p in points),
                            "、".join(POINT_LABEL[p] for p in missing)))
        return {
            # 八个点齐且 hash 相符才算「正常」
            "condition": "正常" if (not missing and hash_ok) else "待确认",
            "message": "；".join(notes),
            "seam_bypass": (not hash_ok) or None,
            "source": "Pi Agent",
            "context_hash_matched": hash_ok,
            "current_context_hash": current_hash,
            "run_id": run["run_id"],
            "run_type": run["run_type"] or "child_decision",
            "child_asin": run["subject_id"] or run["child_asin"],
            "data_as_of": run["data_as_of"],
            "context_id": run["context_id"],
            "context_hash": run["context_hash"],
            "model_version": run["model_version"],
            "method_version": run["method_version"],
            "schema_version": run["schema_version"],
            "dataset_version": run["dataset_version"],
            "rule_version": run["rule_version"],
            "created_at": run["created_at"],
            "completed_at": run["completed_at"],
            "mode": run["mode"],
            # 四段揭示只认已到位的，前端按这个数组渲染
            "stage_order": [s["stage"] for s in stages],
            "stages": stages,
            # 板块 2/3/5 用的三个点单独给，不混进四段
            "points": {p: points[p] for p in points},
            "point_order": order,
            "pending_points": missing,
            "diagnosis_coverage": points.get("B3b")
            or _jload(run["diagnosis_coverage"]),
            "evidence_index": _jload(run["evidence_index"]) or [],
        }
    except (sqlite3.Error, ValueError, TypeError,
            json.JSONDecodeError) as err:
        return _pending(child_asin,
                        "Agent 结果库不完整或不可读，请重新运行（%s）"
                        % type(err).__name__)


def latest_purpose_labels() -> dict:
    """A1：广告目的标签建议，按广告对象取最新一次 completed 运行。"""
    if not DB.is_file():
        return {"condition": "待确认", "by_object": {}, "runs": 0,
                "message": "尚未运行 A1"}
    try:
        con = _open()
        runs = con.execute(
            "SELECT run_id, subject_id, created_at, model_version"
            " FROM fact_ads_agent_run"
            " WHERE run_type='purpose_label' AND status='completed'"
            " ORDER BY created_at DESC").fetchall()
        if not runs:
            con.close()
            return {"condition": "待确认", "by_object": {}, "runs": 0,
                    "message": "尚未完成 A1 运行"}
        seen, out = set(), {}
        for r in runs:
            oid = r["subject_id"]
            if oid in seen:          # 同一对象只取最新那次
                continue
            seen.add(oid)
            items = con.execute(
                "SELECT payload FROM fact_ads_agent_output"
                " WHERE run_id=? AND output_point='A1'"
                " ORDER BY item_ord", (r["run_id"],)).fetchall()
            if items:
                out[oid] = {
                    "run_id": r["run_id"],
                    "created_at": r["created_at"],
                    "model_version": r["model_version"],
                    "items": [json.loads(x["payload"]) for x in items],
                }
        con.close()
        return {"condition": "正常" if out else "待确认",
                "by_object": out, "runs": len(out)}
    except (sqlite3.Error, ValueError, TypeError,
            json.JSONDecodeError) as err:
        return {"condition": "失败", "by_object": {}, "runs": 0,
                "message": "A1 结果不可读（%s）" % type(err).__name__}


def _jload(v):
    if not v:
        return None
    try:
        return json.loads(v)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
