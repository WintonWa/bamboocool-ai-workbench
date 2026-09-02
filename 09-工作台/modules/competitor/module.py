"""竞品分析模块入口。契约 8.1：外壳只读这个文件，其余业务文件由它自己 import。

处理函数签名统一收一个 core.ctx.Ctx：参数已由外壳按声明夹紧放在 c.params，
额外路径段在 c.rest（/api/competitor/rival/B0XX -> ("B0XX",)），资源名不带斜杠。
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from core import ctx as ctx_mod
from core import paths

from . import compute, data, rules

MODULE_ID = "competitor"
FILTER_KEYS = ("q", "sub", "domain", "evidence")

# ---- Agent 任务服务 --------------------------------------------------------
# 契约 6.1 强制本模块只读打开库，所以「发起分析」只能转调 Agent 侧的任务服务，
# 由它写库；本模块只发起、只读状态。端点见 competitor-agent-v2 设计 §5.1。
AGENT_RUNS_PATH = "/api/agent/competitor/runs"
# 只是发起，Agent 立即返回 queued 不等跑完（实测入队 → running 约 0.8 秒），
# 所以这里给短超时。真正的等待由面板轮 analyze-status 完成。
AGENT_TIMEOUT_S = 15

# 面板认的状态词。外壳把不是「完成」也不是「正常」的判成失败，
# 其余取契约 6.6 词表，`_STATUS_WORDS` 认得。
STATUS_OK = "完成"
STATUS_FAIL = "失败"
STATUS_RUNNING = "加载中"
STATUS_EMPTY = "空结果"

_LEDGER_TO_PANEL = {
    "queued": STATUS_RUNNING,
    "running": STATUS_RUNNING,
    "completed": STATUS_OK,
    "skipped": STATUS_OK,
    "failed": STATUS_FAIL,
}

# 八步顺序判断的中文名。**Agent 侧当前不分步落库**（10 张判断表在最后一个事务里
# 一起提交），所以面板只能把这八步当一整段显示，不能逐步点亮 —— 编一个进度条
# 就是拿节奏冒充数字。等 Agent 把步骤分段回报后，这里展开成八行。
STAGE_CHAIN = "证据 → 变化 → 整族代表性 → 竞争范围 → 同期关系 → 关注与影响 → 报告选题 → 装配"

TASKS = [
    {
        "id": "competitor-analysis",
        "label": "重新分析这个竞品",
        "needs": "object",
        "run": "analyze",
        # 有 poll，外壳就不 await 触发那次调用，改成边跑边轮这个路由。
        # 实测一次运行 63~106 秒，await 的话面板整段时间只有一个不动的字。
        "poll": "analyze-status",
        "hint": "按当前观察窗与七个阈值重跑八步判断，跑完页面换成新的一次分析",
    },
]


def _step(label: str, detail: str, status: str, sources: list[str]) -> dict:
    return {"label": label, "detail": detail, "status": status, "sources": sources}


def _elapsed_note(created_at: str | None) -> str:
    """把已耗时说出来。

    面板在跑的时候只有一个不动的脉冲，没有秒数（外壳的决定：Agent 不分步回报，
    任何进度条都是猜的）。但**已耗时是真值**，算得出来就该显示 —— 实测撞到过一次
    卡在 running 超过 3 分钟且永不终结的运行（Agent 侧没有超时判定），
    那种情况下一个不动的「加载中」就是「卡死」。
    """
    if not created_at:
        return ""
    try:
        started = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
    except ValueError:
        return ""
    sec = int((datetime.now(timezone.utc) - started).total_seconds())
    if sec < 0:
        return ""
    span = f"{sec // 60} 分 {sec % 60} 秒" if sec >= 60 else f"{sec} 秒"
    # 不宣称失败（页面无权判定，见交底包 1.2.1），只把「比平常久」说出来。
    tail = "，比平常久" if sec > 150 else ""
    return f"已 {span}{tail}（平常 1 到 2 分钟）"


def _object(c: ctx_mod.Ctx) -> str:
    return (c.rest[0] if c.rest else c.q("object") or "").strip().upper()


def _flt(c: ctx_mod.Ctx) -> dict:
    return {k: c.q(k) for k in FILTER_KEYS if c.q(k)}


def handle_analyze(c: ctx_mod.Ctx) -> dict:
    """发起一次分析。转调 Agent 任务服务，不等它跑完。

    请求体严格按交底包 1.2：七个阈值随请求传过去，Agent 必须用请求里的值判断，
    不能用自己写死的 —— 否则运营在参数面板调完阈值再重跑，页面筛选口径与
    Agent 判断口径会各说各话。`request_key` 每次点击都不同，用于幂等。
    """
    family = _object(c)
    if not family:
        return {"run": {"object_id": None, "status": STATUS_EMPTY,
                        "message": "先在页面上选一个竞品"}, "steps": []}

    con = data.connect()
    try:
        man = data.manifest(con)
    finally:
        con.close()

    body = json.dumps({
        "trigger": "manual",
        "family_asin": family,
        "window_from": man.get("window_from"),
        "window_to": man.get("window_to"),
        "data_as_of": man.get("as_of"),
        "requested_by": "workbench-ui",
        "request_key": f"{family}-{man.get('as_of')}-manual-{time.time_ns()}",
        "thresholds": compute._thresholds(c.params),
    }).encode("utf-8")

    req = urllib.request.Request(
        paths.AGENT_ORIGIN.rstrip("/") + AGENT_RUNS_PATH,
        data=body, method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=AGENT_TIMEOUT_S) as resp:
            got = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"run": {"object_id": family, "status": STATUS_FAIL,
                        "message": f"分析服务返回异常（HTTP {e.code}）"}, "steps": []}
    except urllib.error.URLError:
        return {"run": {"object_id": family, "status": STATUS_FAIL,
                        "message": "连不上分析服务"}, "steps": []}
    except (ValueError, OSError, TimeoutError):
        return {"run": {"object_id": family, "status": STATUS_FAIL,
                        "message": "分析服务的响应读不了"}, "steps": []}

    return {
        "run": {
            # run_id 不在这里给：Agent 的 POST 只回 task_id 与 state，
            # run_id 由 analyze-status 从执行台账读（入队时就分配了）。
            "object_id": family,
            "status": STATUS_RUNNING,
            "data_as_of": man.get("as_of"),
            "message": f"已受理，任务 {got.get('state') or 'queued'}",
        },
        "steps": [_step("已受理", "分析已排队", STATUS_OK, ["竞品分析 Agent"])],
    }


def handle_analyze_status(c: ctx_mod.Ctx) -> dict:
    """轮询用：把执行台账转成面板要的 `{run, steps}`。

    读台账而不是读 run 表，因为 `run_id` 是**入队时**就分配的。外壳的 pollTask
    要看到一个新的 `run_id` 才认为「开跑了」，宽限只有 25 秒；而判断结果要跑完
    63~106 秒才落 run 表 —— 读 run 表会让每次点击都被判成「没有开跑」。
    """
    family = _object(c)
    if not family:
        return {"run": {"object_id": None, "status": STATUS_EMPTY}, "steps": []}

    con = data.connect()
    try:
        ex = data.latest_execution(con, family)
    finally:
        con.close()

    if not ex:
        return {"run": {"object_id": family, "status": STATUS_EMPTY,
                        "message": "这个竞品还没有分析记录"}, "steps": []}

    raw = str(ex["status"] or "")
    panel = _LEDGER_TO_PANEL.get(raw, "待确认")
    reason = ex["reason"] or None
    # 两种失败要分开说，运营该做的事不一样：被别人的运行挤掉 ≠ 这次分析本身有问题。
    if raw == "failed" and reason and "已重启" in reason:
        message = "这次分析被另一次运行打断，可以直接重新发起"
    else:
        message = reason

    steps = [_step("已受理", "分析已排队", STATUS_OK, ["竞品分析 Agent"])]
    if raw in ("queued", "running"):
        note = _elapsed_note(ex["created_at"])
        steps.append(_step("八步顺序判断",
                           f"{STAGE_CHAIN}　·　{note}" if note else STAGE_CHAIN,
                           STATUS_RUNNING, ["竞品观察数据"]))
    elif raw == "completed":
        steps.append(_step("八步顺序判断", STAGE_CHAIN, STATUS_OK, ["竞品观察数据"]))
        steps.append(_step("写入判断结果", "变化、关注依据、影响范围、报告与交接已入库",
                           STATUS_OK, ["竞品分析 Agent"]))
    elif raw == "skipped":
        steps.append(_step("跳过本次分析", reason or "观察数据与上一次相同，沿用已有分析",
                           STATUS_OK, ["竞品观察数据"]))
    elif raw == "failed":
        steps.append(_step("八步顺序判断", message or "本次运行未完成",
                           STATUS_FAIL, ["竞品观察数据"]))

    return {
        "run": {
            "run_id": ex["run_id"],
            "object_id": family,
            "status": panel,
            "data_as_of": ex["created_at"],
            "message": message,
        },
        "steps": steps,
    }


def handle_rivals(c: ctx_mod.Ctx) -> dict:
    """总览：洞察带 + 变化计数带 + 威胁比较表。"""
    con = data.connect()
    try:
        return compute.overview(con, c.params, _flt(c))
    finally:
        con.close()


def handle_rival(c: ctx_mod.Ctx) -> dict:
    """详情：一个竞品产品族。父 ASIN 走路径段，不进资源名。"""
    if not c.rest:
        return {"condition": "空结果", "message": "未指定竞品产品族"}
    con = data.connect()
    try:
        out = compute.detail(con, c.rest[0], c.params)
        if out is None:
            return {"condition": "缺失",
                    "message": "该父 ASIN 不在当前监控范围内，只覆盖 38 个竞品产品族"}
        return out
    finally:
        con.close()


def handle_meta(c: ctx_mod.Ctx) -> dict:
    """模块元信息。壳级 /api/meta 不占用，本模块的放这里（契约 5.1）。"""
    con = data.connect()
    try:
        man = data.manifest(con)
        fams = data.families(con)
        runs = data.latest_runs(con)
        subs = sorted({f["sub_category"] for f in fams if f["sub_category"]})
        freshness = data.rows(con, """
            SELECT '价格与活动' AS name, MAX(date) AS updated
              FROM fact_competitor_price_daily
            UNION ALL SELECT '市场表现', MAX(date) FROM fact_competitor_market_daily
            UNION ALL SELECT '关键词位置', MAX(observed_date)
              FROM fact_competitor_keyword_rank
            UNION ALL SELECT '流量结构', MAX(period_end)
              FROM fact_competitor_traffic_mix
        """)
        rel = data.one(con, "SELECT COUNT(*) n, SUM(confirm_status='confirmed') c"
                            " FROM bridge_competitor_child")
        kw = data.one(con, "SELECT COUNT(*) total, SUM(is_battleground) battleground"
                           " FROM dim_competitor_keyword")
        st = data.rows(con, "SELECT status, COUNT(*) n FROM fact_competitor_data_status"
                            " GROUP BY status")
        # 多个内部状态会映射到同一个上屏词（观察中断与未纳入监控都叫「缺失」），
        # 合并后再上屏，否则界面上出现两个同名 chip。
        merged: dict[str, int] = {}
        for r in st:
            merged[data.STATUS.get(r["status"], r["status"])] = (
                merged.get(data.STATUS.get(r["status"], r["status"]), 0) + r["n"])
        runs_by_fam = runs
        return {
            "id": MODULE_ID,
            "as_of": man["as_of"],
            "condition": "正常",
            "scope_label": man.get("scope", ""),
            "judgment_object": "竞品产品族（父 ASIN）",
            "dataset_version": man.get("dataset_version", ""),
            "product_spine": man.get("product_spine", ""),
            "window": [man["window_from"], man["window_to"]],
            "freshness": freshness,
            "sub_categories": subs,
            "monitored": len(fams),
            "analyzed": sum(1 for f in fams if f["in_analysis_scope"]),
            "with_run": len(runs),
            "quick_slot": [
                {
                    "family_asin": f["family_asin"],
                    "brand": f["brand"],
                    "attention": data.ATTENTION.get(
                        (runs_by_fam.get(f["family_asin"]) or {}).get("attention_level", ""),
                        "尚未分析"),
                    "attention_key": (runs_by_fam.get(f["family_asin"]) or {})
                    .get("attention_level", "unanalyzed"),
                    "unit_price": f["unit_price_median"],
                }
                for f in fams if f["in_quick_slot"]
            ],
            "relations": {"total": rel["n"], "confirmed": rel["c"]},
            "keywords": {"total": kw["total"], "battleground": kw["battleground"]},
            "data_status": [{"label": k, "n": v} for k, v in sorted(
                merged.items(), key=lambda kv: -kv[1])],
            "unconfirmed": [
                "威胁优先级的计算方式（当前用可解释分级与依据条目，不给分数）",
                "洞察带的刷新频率与固定结构",
                "筛选项、变化类型与子类目的口径",
                "价格、销量、排名、流量、关键词与流量结构的可用字段",
                "各指标的时间粒度、历史范围与更新时间",
                "第三方接口的实际可接入能力",
                "来源标识、证据记录与下游交接格式",
            ],
        }
    finally:
        con.close()


def invalidate():
    """外壳热重载时调用。每次请求都新开只读连接，无常驻缓存。"""
    return None


MODULE = {
    "id": MODULE_ID,
    "label": "竞品分析",
    # 外壳默认取 mid[:3]=com；契约 5.2 的示例是 cmp.*，显式声明
    "prefix": "cmp",
    "api_version": 1,
    "pages": [
        {"id": "cmp-overview", "label": "竞品威胁总览"},
        {"id": "cmp-rival", "label": "单一竞品分析"},
    ],
    "routes": {
        "meta": handle_meta,
        "rivals": handle_rivals,
        "rival": handle_rival,
        "analyze": handle_analyze,
        "analyze-status": handle_analyze_status,
    },
    "tasks": TASKS,
    "params": rules.PARAMS,
    "db": paths.COMPETITOR_DB,
    "invalidate": invalidate,
}
