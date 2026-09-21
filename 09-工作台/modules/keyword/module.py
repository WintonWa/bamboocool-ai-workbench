"""关键词分析模块入口。契约 8.1：外壳只读这个文件，其余业务文件由它自己 import。

处理函数签名统一收一个 core.ctx.Ctx：参数已由外壳按声明夹紧放在 c.params，
额外路径段在 c.rest（/api/keyword/child/B0XX -> ("B0XX",)），资源名不带斜杠。

A1 骨架：meta 与 children 两个资源已实装，三页正文在 A2–A4 填。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from core import ctx as ctx_mod, xlsx
from core import paths

from . import agent_result, compute, data, rules

MODULE_ID = "keyword"
_STALE_REPORT = "当前参数与最近一次 Agent 运行不一致，本次不显示旧判断"
_LOOP_RUN_URL = paths.AGENT_ORIGIN.rstrip("/") + "/api/agent/keyword/loop-runs"
_LOOP_STATUS_URL = _LOOP_RUN_URL + "/status"
_LOOP_STATUS = {"running": "加载中", "completed": "完成", "failed": "失败"}


def _selection(c: ctx_mod.Ctx, resolved: dict | None = None):
    rp = resolved or rules.resolve(c.query)
    contract = {
        "compare": rp["compare"],
        "rank_shift": rp["rank_shift"],
        "group_dedup": rp["group_dedup"],
        "weights": rp["weights"],
    }
    return agent_result.select_database(paths.KEYWORD_DB, contract)


def _agent_status(selection) -> dict:
    condition = ("正常" if selection.status == "current"
                 else "过期" if selection.status == "stale" else "缺失")
    return {
        "condition": condition,
        "run_id": selection.run_id,
        "using_current": selection.status == "current",
        "message": selection.reason,
    }


def _hide_stale_report(out: dict, selection) -> dict:
    """Never pair request-time numbers with prose from another Agent context."""
    out["agent_result"] = _agent_status(selection)
    if selection.status == "stale":
        for report in out.get("reports") or []:
            for key in ("q1_traffic_result", "q2_main_movers",
                        "q3_core_coverage_change", "q4_new_signals",
                        "q5_priority_next"):
                report[key] = _STALE_REPORT
            report["priority_evidence_ids"] = []
            report["coverage_event_ids"] = []
    return out


def handle_meta(c: ctx_mod.Ctx) -> dict:
    """模块元信息。壳级 /api/meta 不占用，本模块的放这里（契约 5.1）。"""
    rp = rules.resolve(c.query)
    selection = _selection(c, rp)
    with data.use_database(selection.path):
        sc = data.scope()
        dist = data.distributions()
        win = data.window()
        spine = data.spine_check()
        counts = data.counts()
        dimensions = data.demand_dimensions()
    return {
        "id": MODULE_ID,
        "as_of": sc.get("as_of_date") or c.as_of,
        "condition": "正常",
        "scope_label": "%s · %s" % (sc.get("site"), sc.get("product_line")),
        "judgment_object": "市场关键词 / 关键词 × 子ASIN / 关键词 × 子ASIN × 当前目标",
        "dataset_version": "0.1.0",
        "product_spine": "%s 子 ASIN 脊椎，本模块命中 %s 个"
                         % (spine["spine_size"], spine["pair_children"]),
        "library_terms": sc.get("library_keyword_count"),
        "monitored_terms": sc.get("monitored_keyword_count"),
        "focus_children": sc.get("focus_child_count"),
        "counts": counts,
        "window": {
            "week": [win["week_from"], win["week_to"]],
            "month": [win["month_from"], win["month_to"]],
            "position": [win["position_from"], win["position_to"]],
            "collect_depth": win["collect_depth"],
        },
        "freshness": [
            {"name": "市场快照（周）", "updated": win["week_to"]},
            {"name": "市场快照（月）", "updated": win["month_to"]},
            {"name": "自然位与广告位", "updated": win["position_to"]},
        ],
        "distributions": dist,
        "demand_dimensions": dimensions,
        "not_comparable_rows": dist["not_comparable_rows"],
        "params": rules.declare(c.query),
        "agent_result": _agent_status(selection),
        "vocab": {"nature": list(data.NATURE.values()), "status": data.STATUS},
        "spine_check": spine,
        "unconfirmed": [
            "共享词库的纳入、移除与人工确认规则",
            "日报的默认比较周期",
            "「关键词流量获取」的正式测量定义与可用来源",
            "自然位与广告位的采集来源、采集深度与更新频率",
            "核心词、场景词、长尾词与待验证词的确认方式",
            "产品目标、产品阶段与主推关系的正式字段与规则",
            "关键词机会、风险与优先级的阈值或评价方式",
            "关键词证据交给竞品页与广告页的结构化格式",
        ],
    }


def handle_children(c: ctx_mod.Ctx) -> dict:
    """30 个重点子体清单，页面三的入口。身份来自产品包脊椎（契约 6.3）。"""
    selection = _selection(c)
    with data.use_database(selection.path):
        kids = data.focus_children()
        q = c.q("q").strip().lower()
        if q:
            kids = [k for k in kids
                    if q in k["child_asin"].lower()
                    or q in (k.get("style_no") or "").lower()]
        as_of = data.scope().get("as_of_date")
    return {
        "as_of": as_of,
        "condition": "正常" if kids else "空结果",
        "total": len(kids),
        "rows": kids,
        "judgment_object": "子 ASIN 是关键词盘点的最小判断对象",
        "agent_result": _agent_status(selection),
    }


def _pending(page_label: str, step: str) -> dict:
    return {"condition": "待确认", "page": page_label, "step": step,
            "message": "%s 在 %s 实装" % (page_label, step)}


FILTER_KEYS = ("q", "status", "dimension", "role", "evidence", "state", "limit")


def _flt(c: ctx_mod.Ctx) -> dict:
    out = {}
    for k in FILTER_KEYS:
        v = c.q(k).strip()
        if v:
            out[k] = v
    return out


def handle_terms(c: ctx_mod.Ctx) -> dict:
    """页面二总览：词库范围与质量 + 需求词组结构 + 市场关键词比较区。"""
    rp = rules.resolve(c.query)
    selection = _selection(c, rp)
    with data.use_database(selection.path):
        con = data.connect()
        try:
            out = compute.library_page(con, rp, _flt(c))
            out["agent_result"] = _agent_status(selection)
            return out
        finally:
            con.close()


def handle_term(c: ctx_mod.Ctx) -> dict:
    """页面二详情：单词市场事实深研。未绑定子体时只出市场事实。"""
    if not c.rest:
        return {"condition": "空结果", "message": "未指定关键词"}
    rp = rules.resolve(c.query)
    selection = _selection(c, rp)
    with data.use_database(selection.path):
        con = data.connect()
        try:
            out = compute.term_page(con, c.rest[0], rp)
            if out is None:
                return {"condition": "缺失", "message": "词库里没有这个关键词"}
            out["agent_result"] = _agent_status(selection)
            return out
        finally:
            con.close()


def handle_overview(c: ctx_mod.Ctx) -> dict:
    """页面一：关键词动态与机会总览。日报 + 词组变化 + 核心词变化 + 优先列表。"""
    rp = rules.resolve(c.query)
    selection = _selection(c, rp)
    with data.use_database(selection.path):
        con = data.connect()
        try:
            out = compute.overview_page(con, rp, _flt(c))
            return _hide_stale_report(out, selection)
        finally:
            con.close()


def handle_child(c: ctx_mod.Ctx) -> dict:
    """页面三：子 ASIN 关键词盘点。五个板块一次返回。"""
    if not c.rest:
        return {"condition": "空结果", "message": "未指定子 ASIN"}
    asin = c.rest[0]
    rp = rules.resolve(c.query)
    selection = _selection(c, rp)
    with data.use_database(selection.path):
        con = data.connect()
        try:
            out = compute.child_page(con, asin, rp)
            if out is None:
                return {"condition": "缺失",
                        "message": "该子体没有关键词关系数据，当前只覆盖 30 个重点子体"}
            out["agent_result"] = _agent_status(selection)
            return out
        finally:
            con.close()


def _loop_failed(message: str) -> dict:
    return {
        "run": {
            "run_id": None,
            "object_id": None,
            "status": "失败",
            "message": message,
        },
        "steps": [],
    }


def _loop_panel(payload: dict) -> dict:
    """把 Agent 内部状态转为外壳统一 `{run, steps}`，不转运业务结果。"""
    source = payload.get("run") if isinstance(payload, dict) else None
    if not isinstance(source, dict):
        return {"run": {"run_id": None, "object_id": None, "status": "待确认"}, "steps": []}
    steps = []
    for item in payload.get("steps") or []:
        if not isinstance(item, dict):
            continue
        steps.append({
            "label": str(item.get("label") or "关键词 Agent 步骤"),
            "detail": str(item.get("detail") or "—"),
            "status": _LOOP_STATUS.get(str(item.get("status")), "待确认"),
            "duration_ms": 0,
            "sources": [str(value) for value in (item.get("sources") or [])],
        })
    return {
        "run": {
            "run_id": source.get("run_id"),
            "object_id": None,
            "status": _LOOP_STATUS.get(str(source.get("status")), "待确认"),
            "current_step": source.get("current_step"),
            "total_steps": source.get("total_steps"),
            "model_version": source.get("model_version"),
            "created_at": source.get("created_at"),
            "message": source.get("message"),
        },
        "steps": steps,
    }


def handle_export(c: ctx_mod.Ctx):
    """关键词盘点导出。三页：待处理事项、词组变化、日报。

    「涉及核心词」这类计数在页面上是**整个窗口**的口径，而日报那句话讲的是**当日**——
    两个口径都对，但并排放会看起来自相矛盾。所以导出里把窗口口径写进表头，
    日报那页单独一张，不跟窗口计数摆在一起。
    """
    d = handle_overview(c)
    items = (d.get("priority") or {}).get("items") or []
    groups = (d.get("group_changes") or {}).get("groups") or []
    reports = d.get("reports") or []
    if not (items or groups or reports):
        return {"message": "当前没有可导出的关键词结果"}

    sheets = []
    if items:
        sheets.append(xlsx.from_records("待处理事项", items, [
            ("keyword", "关键词"),
            ("child_asin", "子体 ASIN"),
            ("evidence_type_label", "事项类型"),
            ("priority", "优先级"),
            ("conclusion", "结论"),
            ("main_basis", "主要依据"),
            ("product_goal_label", "当前目标"),
            ("push_role_label", "推广角色"),
            ("inventory_limit_label", "库存约束"),
            ("evidence_completeness_label", "证据完整度"),
            ("next_verification_label", "下一步验证"),
            ("monthly_search_volume", "月搜索量"),
            ("rank_score", "位次分"),
        ], [26, 14, 16, 8, 46, 40, 14, 12, 12, 12, 16, 12, 10]))
    if groups:
        sheets.append(xlsx.from_records("词组变化", groups, [
            ("group_name", "词组"),
            ("demand_dimension", "需求维度"),
            ("term_count", "词数"),
            ("up", "上涨"), ("down", "下滑"),
            ("competition", "竞争加剧"), ("unclear", "口径不清"),
            ("net", "净变化"),
            ("continuous", "连续"), ("single_period", "单期"),
            ("search_moved", "搜索量变动"),
        ], [26, 16, 8, 8, 8, 10, 10, 10, 8, 8, 14]))
    if reports:
        sheets.append(xlsx.from_records("日报", reports, [
            ("report_date", "日期"),
            ("traffic_proxy_metric", "流量代理指标"),
            ("traffic_proxy_value", "当期值"),
            ("traffic_proxy_delta", "较基期"),
            ("compare_base_date", "基期日"),
            ("compare_base_value", "基期值"),
            ("q1_traffic_result", "流量获取结果"),
            ("q2_main_movers", "主要增长与下降"),
            ("q3_core_coverage_change", "核心词覆盖与位置（当日口径）"),
            ("q4_new_signals", "新出现的信号"),
            ("q5_priority_next", "最值得继续看"),
            ("compare_note", "比较说明"),
        ], [12, 16, 10, 10, 12, 10, 46, 46, 46, 46, 46, 30]))

    sc = d.get("scope") or {}
    sheets.append({
        "name": "口径说明", "headers": ["项", "口径"], "widths": [18, 74],
        "rows": [
            ["站点", str(sc.get("site") or "")],
            ["产品线", str(sc.get("product_line") or "")],
            ["词库规模", f"{sc.get('library_terms')} 个词入库，"
                        f"其中 {sc.get('monitored_terms')} 个在监控"],
            ["覆盖子体", f"{sc.get('focus_children')} 个重点子体。"
                        "本模块只覆盖这些，不是产品脊椎那 342 个 —— "
                        "覆盖率这类指标的分母要按这个数看"],
            ["比较期", str(sc.get("compare_period") or "")],
            ["「待处理事项」口径", "整个观察窗口累计，不是当日"],
            ["日报里的覆盖计数", "当日口径。与页面上「窗口内新增/丢失覆盖」不是同一个口径，"
                             "两者都对，不要直接相减"],
            ["证据来源", "确定性规则算出来的，不是 LLM 判的"],
        ],
    })

    name = f"关键词盘点-{c.as_of}.xlsx"
    return ctx_mod.Download(filename=name, data=xlsx.build(sheets))


def handle_run_agent_loop(c: ctx_mod.Ctx) -> dict:
    """全量运行。模型在独立 Agent 服务后台跑。"""
    return _enqueue({"scope": "all"})


def handle_run_term_agent(c: ctx_mod.Ctx) -> dict:
    """只分析当前选中的那一个关键词。

    对象由外壳带来：任务面板发请求时会把当前 objectId 拼成 `?object=`
    （shell.js runTask）。没选对象就直说，不要退化成全量 —— 那正是
    8-31 会上要改掉的「点一下跑全量」。
    """
    obj = c.q("object").strip()
    if not obj:
        return _loop_failed("先在左侧对象栏选一个关键词，再运行这个分析")
    return _enqueue({"scope": "term", "keyword_id": obj}, obj)


def handle_run_child_agent(c: ctx_mod.Ctx) -> dict:
    """只分析当前选中的那一个子 ASIN。"""
    obj = c.q("object").strip()
    if not obj:
        return _loop_failed("先在左侧对象栏选一个子 ASIN，再运行这个分析")
    return _enqueue({"scope": "child", "child_asin": obj}, obj)


def _enqueue(payload: dict, object_id: str | None = None) -> dict:
    """向 Agent 侧入队一次运行。

    按对象跑（scope=term / child）目前 **Agent 侧不支持**：
    06-Pi-Agent交互Demo/src/keyword-agent.ts 把 scope 的类型写死成 "all"，
    并且「completed 运行必须覆盖 all」—— 那是「半份产出不上屏」机制的一部分
    （关键词是整库替换 keyword_agent_current.sqlite）。
    所以这里照实把 scope 发出去，Agent 侧拒绝就把它的原话显示出来，
    不在工作台这侧伪装成跑过了。
    """
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        _LOOP_RUN_URL, data=body, method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            out = _loop_panel(json.loads(response.read().decode("utf-8")))
            if object_id:
                out["run"]["object_id"] = object_id
            return out
    except urllib.error.HTTPError as error:
        if payload.get("scope") != "all":
            return _loop_failed(
                "Agent 侧目前只支持全量运行（scope=all），按单个对象跑要它先改落库形态"
                f"（HTTP {error.code}）")
        return _loop_failed(f"Agent 服务拒绝启动关键词分析（HTTP {error.code}）")
    except urllib.error.URLError:
        return _loop_failed("连不上 Agent 服务，关键词分析没有开跑")
    except (ValueError, OSError, TimeoutError):
        return _loop_failed("Agent 服务没有返回可读取的关键词运行状态")


def handle_agent_loop_status(c: ctx_mod.Ctx) -> dict:
    """右侧任务窗口轮询入口，只读独立 Loop 状态，不读取半份业务库。"""
    try:
        with urllib.request.urlopen(_LOOP_STATUS_URL, timeout=10) as response:
            return _loop_panel(json.loads(response.read().decode("utf-8")))
    except urllib.error.HTTPError as error:
        return _loop_failed(f"关键词运行状态接口异常（HTTP {error.code}）")
    except urllib.error.URLError:
        return _loop_failed("连不上 Agent 服务，暂时读不到关键词运行状态")
    except (ValueError, OSError, TimeoutError):
        return _loop_failed("关键词运行状态暂时无法读取")


def invalidate():
    """外壳热重载时调用：本模块的缓存必须能一次清干净（契约 8.7）。"""
    data.invalidate()


TASKS = [
    # 任务面板是模块级的，外壳不按页过滤，所以名字自带范围 —— 否则站在单对象页上
    # 看到一个叫「运行关键词分析」的按钮，分不清它是跑这一个还是跑全量。
    {
        "id": "keyword-term-agent",
        "label": "分析当前关键词",
        "run": "run-term-agent",
        "poll": "agent-loop-status",
        "hint": "只跑左侧选中的那一个关键词",
    },
    {
        "id": "keyword-child-agent",
        "label": "分析当前子 ASIN",
        "run": "run-child-agent",
        "poll": "agent-loop-status",
        "hint": "只跑左侧选中的那一个子 ASIN",
    },
    {
        "id": "keyword-agent-loop",
        "label": "运行关键词分析（全量）",
        "run": "run-agent-loop",
        "poll": "agent-loop-status",
        "hint": "覆盖整个词库跑一批，token 成本高，一般只在换数据包后跑",
    },
]


MODULE = {
    "id": MODULE_ID,
    "label": "关键词分析",
    # 外壳默认取 mid[:3]=key；契约 5.2 的示例是 kw.*，显式声明
    "prefix": "kw",
    "api_version": 1,
    # 三个汇总页 + 两个单对象分析页。原来单词深研与子体盘点是挂在
    # 列表页 objectId 下的子视图，页签上看不见，等于两个页面藏在里面。
    "pages": [
        {"id": "kw-overview", "label": "关键词动态与机会总览"},
        {"id": "kw-market", "label": "市场关键词库"},
        {"id": "kw-child", "label": "重点子体清单"},
        {"id": "kw-term", "label": "单一关键词分析"},
        {"id": "kw-asin", "label": "单一子 ASIN 盘点"},
    ],
    "routes": {
        "meta": handle_meta,
        "children": handle_children,
        "overview": handle_overview,
        "terms": handle_terms,
        "term": handle_term,
        "child": handle_child,
        "export": handle_export,
        "run-agent-loop": handle_run_agent_loop,
        "run-term-agent": handle_run_term_agent,
        "run-child-agent": handle_run_child_agent,
        "agent-loop-status": handle_agent_loop_status,
    },
    "tasks": TASKS,
    "params": rules.PARAMS,
    "db": paths.KEYWORD_DB,
    "invalidate": invalidate,
}
