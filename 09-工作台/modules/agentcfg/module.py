"""Agent 配置 · 外壳唯一读的入口文件。

这个页面回答客户那个需求：**Agent 的分析方式和数据门槛边界能不能自定义。**

它有一条刻意的设计约束：**不新建一份阈值存储。**
工作台已经有 52 个门槛参数（各模块 `MODULE["params"]`，带 lo/hi 夹紧、
中文标签、分组）。这个页面只是把它们按 Agent 归拢起来一处可见可改，
值仍然走原来那一套。再存一份的后果是阈值有两个真相来源 ——
那正是这个项目在消除的碎片化。

所以本模块后端只做一件事：给出 Agent 登记表。阈值的当前值、范围、标签
由前端从外壳已有的 `/api/modules` 拿，本模块不读兄弟模块的代码（契约 G12）。

第二个页面「Agent 输出记录」回答另一个需求：**过去跑过的 Agent 有没有存档。**
它按真实时刻倒序列出六张 run 表里已经跑出来的运行，只读、不写、不补、不造。
那六张表归各业务模块所有（落点声明在 `registry_seed.RUN_SOURCES`），
本模块按路径只读打开它们 —— 是数据依赖，不是代码依赖。
"""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone

from core import ctx as ctx_mod
from core import db as db_mod
from core import paths

from . import registry_seed, schemes
from .registry_seed import (
    DONE_COL,
    ERROR_COLS,
    RUN_SOURCES,
    SEED,
    STATUS_COL,
    TIME_COL,
    TRIGGERS,
    VOCAB,
)

PREFIX = "agc"


def handle_meta(c: ctx_mod.Ctx) -> dict:
    claimed = [a for a in SEED if a.get("status") not in ("待声明",)]
    return {
        "as_of": c.as_of,
        "fingerprint": c.fingerprint,
        "total": len(SEED),
        "declared": len(claimed),
        "pending": len(SEED) - len(claimed),
        "condition": "正常",
    }


def _module_agents() -> list[dict]:
    """各业务模块在自己的 MODULE["agents"] 里声明的 Agent。

    契约 §8.1：Agent 最终由所属模块声明，登记表只是过渡落点。
    但这一页原来只读 SEED —— 于是一个模块「认领」之后，它的 Agent 就从
    Agent 配置页消失了，而页面上的 AI 徽标还标着。那正是 G26 要防的那种
    当场露馅（客户点开配置页查不到页面上标着的 Agent）。

    走 core.registry 而不是 import 那些模块：registry 是外壳的一部分，
    不违反「模块之间禁止互相 import」（§8.5）—— 本文件是模块，
    直接 import modules/preinvest/ 才是违规。
    """
    from core import registry                     # 局部 import，避免循环

    out = []
    for m in registry.modules():
        if m.degraded or m.id == "agentcfg":
            continue
        for a in (m.spec.get("agents") or []):
            if isinstance(a, dict) and a.get("id"):
                out.append(dict(a, declared_in="模块 " + m.id))
    return out


def handle_agents(c: ctx_mod.Ctx) -> dict:
    """Agent 登记表。

    thresholds 只回参数键，不回它们的当前值和范围 —— 那份数据外壳已经
    在 /api/modules 里给过了，这里再回一遍就是第二个真相来源。
    """
    return {
        "as_of": c.as_of,
        "triggers": TRIGGERS,
        "agents": [
            {
                "id": a["id"],
                "label": a["label"],
                "desc": a.get("desc", ""),
                "owner": a["owner"],
                "status": a["status"],
                "model_version": a.get("model_version"),
                "trigger": a.get("trigger", []),
                "judges": a.get("judges", []),
                "computed": a.get("computed", []),
                "needs": a.get("needs", []),
                "outputs": a.get("outputs", []),
                "thresholds": a.get("thresholds", []),
                "contract": a.get("contract"),
                "note": a.get("note", ""),
                # 声明位置：现在全部还在登记表里，等模块认领后由模块自己给
                "declared_in": "登记表",
            }
            for a in SEED
        ] + _module_agents(),
    }


# ---------------------------------------------------------------------------
# Agent 输出记录
# ---------------------------------------------------------------------------
# 客户要的是「过去跑过的 Agent 的时间、信息、结果有一个存档」。
# 数据全是已经跑出来的真实 run，六张表分散在四个模块自己的 derived 库里
# （落点声明见 registry_seed.RUN_SOURCES），本模块只读、不写、不补、不造。


def _stamp(raw: str | None) -> datetime | None:
    """把写入方给的时间戳解析成可比较的时刻；解析不出来回 None。

    **不能按字符串比。** 这六张表里三种格式同时存在，同一条时间线上写成：
      `2026-08-30T22:56:12.869Z`（UTC 带 Z）、`2026-08-31T10:13:56+08:00`（带偏移）、
      `2026-08-31T06:22:29`（无偏移，实际是本地）。
    带 Z 的那条字符串排序会被判成 08-30 的记录排到最后，于是"更晚发生的运行"
    在按时间倒序的列表里出现在更早的运行下面 —— 而这种错在界面上没有任何症状。
    库存模块已经踩过并修了（modules/inventory/verdict.py 的 _stamp），这里照抄它的做法：
    G12 禁止 import 兄弟模块的代码，所以这六行是有意重复的，不是漏抽公共层。

    读取端保持宽容：带偏移按偏移读，无偏移按本机时区读，解析不了照实说不知道。
    """
    t = (raw or "").strip().replace("Z", "+00:00").replace(" ", "T")
    if not t:
        return None
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    return dt.astimezone() if dt.tzinfo is None else dt


_FLOOR = datetime(1, 1, 1, tzinfo=timezone.utc)     # 解析不出来的排最后，但不丢掉
_OFFSET = re.compile(r"[+-]\d{2}:?\d{2}$")
_WEEKDAY = "一二三四五六日"


def _shape(raw: str | None) -> str | None:
    """这条时间戳在库里长什么样。详情里如实显示，因为三种形态确实同时存在。"""
    t = (raw or "").strip()
    if not t:
        return None
    if t.endswith("Z"):
        return "带 Z，按 UTC 读"
    if _OFFSET.search(t):
        return "带偏移，按偏移读"
    return "没写偏移，按本机时区读"


def _term(col: str, value) -> str | None:
    """码值 → 中文。词表外的非空值一律「待确认」，不让英文码值上屏、也不静默变空白。"""
    if value is None or value == "":
        return None
    table = VOCAB.get(col)
    if table is None:
        return str(value)
    return table.get(str(value)) or "待确认"


def _lasted(started: datetime | None, ended: datetime | None) -> str | None:
    if started is None or ended is None:
        return None
    secs = int((ended - started).total_seconds())
    if secs < 0:
        return None
    if secs < 60:
        return "%d 秒" % secs
    return "%d 分 %d 秒" % (secs // 60, secs % 60)


def _pairs(row: dict, cols: list, present: set) -> list:
    """(列, 中文名) 声明 → 详情键值对。空值与库里没有的列都跳过。"""
    out = []
    for col, label in cols or []:
        if col not in present:
            continue
        v = _term(col, row.get(col))
        if v is None or v == "":
            continue
        out.append({"k": label, "v": str(v)})
    return out


def _collect(spec: dict) -> tuple:
    """读一个来源的全部 run。返回 (记录, 来源状态)。

    每一种读不到都如实报出来，绝不静默当成"没有运行过"：
    库文件不在 / 表不在库里 / 库读不动 / 声明的列不存在，都写进来源状态给页面显示。
    """
    path = paths.MODULES_DIR / spec["db"]
    state = {
        "sid": spec["sid"],
        "agent_id": spec["agent_id"],
        "source": spec["source"],
        "rows": 0,
        "condition": "正常",
        "reason": None,
        "missing_cols": [],
    }
    if not spec["table"].isidentifier():             # 表名来自本文件的声明，不来自请求
        state.update(condition="失败", reason="表名不合法")
        return [], state
    if not path.exists():
        state.update(condition="缺失", reason="库文件还不在：" + spec["db"])
        return [], state
    try:
        con = db_mod.connect(path)
    except (sqlite3.Error, OSError) as exc:
        state.update(condition="失败", reason=str(exc))
        return [], state
    try:
        if spec["table"] not in db_mod.table_names(con):
            state.update(condition="缺失", reason="库里没有这张表：" + spec["table"])
            return [], state
        present = {r["name"] for r in db_mod.rows(con, "PRAGMA table_info(%s)" % spec["table"])}
        raw_rows = db_mod.rows(con, "SELECT * FROM %s" % spec["table"])
    except sqlite3.Error as exc:
        state.update(condition="失败", reason=str(exc))
        return [], state
    finally:
        con.close()

    declared = [spec.get("subject_col"), spec.get("summary_col"), TIME_COL]
    declared += [c for c, _ in spec.get("tags") or []]
    declared += [c for c, _ in spec.get("extra") or []]
    state["missing_cols"] = sorted({c for c in declared if c and c not in present})

    records = []
    for row in raw_rows:
        started = _stamp(row.get(TIME_COL))
        # 显示统一换算到本机时区。**不这么做的后果肉眼可见**：带 Z 的那几条会用
        # UTC 的钟面上屏（04:06），排在 12:06 与 12:11 之间，列表看起来是乱序的 ——
        # 排序其实是对的，错的是三种格式各用各的钟面。
        shown = started.astimezone() if started else None
        ended = _stamp(row.get(DONE_COL)) if DONE_COL in present else None
        err = None
        for col in ERROR_COLS:
            if col in present and row.get(col):
                err = str(row[col])
                break
        records.append({
            # run_id 跨库会重名（两个竞品库里都有 B0CJ9QLVPP-2026-08-03-1），
            # 所以存档键带上来源前缀
            "key": spec["sid"] + ":" + str(row.get("run_id") or len(records)),
            "agent_id": spec["agent_id"],
            "source": spec["source"],
            "run_id": row.get("run_id"),
            "subject": _term(spec.get("subject_col"), row.get(spec.get("subject_col"))),
            "subject_kind": spec.get("subject_kind"),
            "ran_at": shown.strftime("%Y-%m-%d %H:%M:%S") if shown else None,
            "day": shown.strftime("%Y-%m-%d") if shown else None,
            "weekday": ("星期" + _WEEKDAY[shown.weekday()]) if shown else None,
            "clock": shown.strftime("%H:%M:%S") if shown else None,
            "raw_stamp": row.get(TIME_COL),
            "stamp_shape": _shape(row.get(TIME_COL)),
            "lasted": _lasted(started, ended),
            "data_as_of": row.get("data_as_of"),
            "trigger": _term("trigger", row.get("trigger")) if "trigger" in present else None,
            "model_version": row.get("model_version") or None,
            "status": _term(STATUS_COL, row.get(STATUS_COL)) if STATUS_COL in present else None,
            "error": err,
            "summary": (row.get(spec["summary_col"]) or None) if spec.get("summary_col") else None,
            "tags": _pairs(row, spec.get("tags"), present),
            "extra": _pairs(row, spec.get("extra"), present),
            "_sort": started or _FLOOR,
        })
    return records, state


def _params_by_key() -> dict:
    """全站参数声明 {带前缀的键: 声明}。方案要拿默认值，也要拿它挡掉登记表里写错的键。

    用 ruleset.describe() 拼，不自己拼 f"{prefix}.{name}" —— 前缀规则只该有一处，
    自己拼一遍就等于多一个真相来源，前缀规则一改这里就静默错位。
    """
    from core import registry, ruleset

    out = {}
    for m in registry.modules():
        ps = m.spec.get("params") or []
        if not ps:
            continue
        for d in ruleset.describe(m.prefix, ps, {}):
            out[d["key"]] = d
    return out


def handle_schemes(c: ctx_mod.Ctx) -> dict:
    """每个 Agent 的配置方案清单。第一项永远是默认方案（现算，不入库）。"""
    pbk = _params_by_key()
    return {
        "as_of": c.as_of,
        "agents": [
            {
                "id": a["id"],
                "label": a["label"],
                "owner": a["owner"],
                "thresholds": [k for k in (a.get("thresholds") or []) if k in pbk],
                "schemes": schemes.for_agent(a, pbk),
            }
            for a in registry_seed.SEED
        ],
        "params": pbk,
    }


def handle_scheme_save(c: ctx_mod.Ctx) -> dict:
    """存一个方案。POST 体：{agent_id, name, values, id?, note?}"""
    body = c.json()
    aid = body.get("agent_id")
    agent = next((a for a in registry_seed.SEED if a["id"] == aid), None)
    if not agent:
        return {"ok": False, "message": f"没有名为 {aid} 的 Agent"}
    pbk = _params_by_key()
    allowed = [k for k in (agent.get("thresholds") or []) if k in pbk]
    try:
        row = schemes.save(aid, body.get("name"), body.get("values") or {},
                           allowed, body.get("id"), body.get("note") or "")
    except ValueError as e:
        return {"ok": False, "message": str(e)}
    return {"ok": True, "scheme": row}


def handle_scheme_delete(c: ctx_mod.Ctx) -> dict:
    body = c.json()
    try:
        gone = schemes.delete(body.get("agent_id"), body.get("id"))
    except ValueError as e:
        return {"ok": False, "message": str(e)}
    return {"ok": gone, "message": "" if gone else "没找到这个方案"}


def handle_runs(c: ctx_mod.Ctx) -> dict:
    """按真实时刻倒序的运行存档。

    排序在这里做完，前端只保序渲染 —— JS 里同样有这个坑
    （`new Date("…Z")` 与 `new Date("…")` 是两种时区解释），
    所以整条链上一个 JS 时间对象都不出现。
    """
    labels = {a["id"]: a["label"] for a in SEED}
    records, sources = [], []
    for spec in RUN_SOURCES:
        recs, state = _collect(spec)
        state["rows"] = len(recs)
        sources.append(state)
        records.extend(recs)

    # **按解析后的时刻倒序，不按 created_at 字符串。** 理由见 _stamp()。
    records.sort(key=lambda r: r["_sort"], reverse=True)
    for r in records:
        r.pop("_sort", None)
        r["agent_label"] = labels.get(r["agent_id"], "待确认")

    unreadable = [s for s in sources if s["condition"] != "正常"]
    return {
        "as_of": c.as_of,
        "fingerprint": c.fingerprint,
        "total": len(records),
        "sources": sources,
        "unreadable": len(unreadable),
        "condition": "正常" if records else ("失败" if unreadable else "空结果"),
        "agents": [{"id": a["id"], "label": a["label"]} for a in SEED],
        "runs": records,
    }


MODULE = {
    "id": "agentcfg",
    "label": "Agent 配置",
    "api_version": 1,
    "prefix": PREFIX,
    "pages": [
        {"id": "list", "label": "Agent 与门槛"},
        {"id": "runs", "label": "Agent 输出记录"},
    ],
    "routes": {
        "meta": handle_meta,
        "agents": handle_agents,
        "runs": handle_runs,
        # 配置方案。方案一/二/三那套 —— 每个 Agent 各自一份清单。
        "schemes": handle_schemes,
        "scheme-save": handle_scheme_save,
        "scheme-delete": handle_scheme_delete,
    },
    "db": None,                      # 不取业务数，只给声明与运行台账
}
