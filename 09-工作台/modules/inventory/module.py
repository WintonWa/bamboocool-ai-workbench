"""产品与库存模块 · 自描述文件。

外壳只读这一个文件（core/registry.py）。_REQUIRED 是
id / label / api_version / pages / routes，缺一个整个模块降级。

三个接口沿用 18810 版的载荷形状，只把前缀换成 /api/inventory/：
  meta      基准信息、参数面板、筛选选项、风险词表
  children  全量评估 + 筛选 + 范围汇总（异常总览与库存全览共用）
  child     单个子体的完整盘点（单品盘点页）
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from typing import Any

from core import paths, xlsx
from core.ctx import Ctx, Download

from . import compute, data, forecast, listing, rules, verdict
from . import agent_forecast as af

# 每页默认最多回多少行。18810 版是 400，保持一致。
DEFAULT_LIMIT = 400

# 需求预测 Agent 的端点。工作台**不跑 LLM**，只触发并回读落库结果。
FORECAST_PATH = "/api/agent/demand-forecast"

# 九工具链耗时以十秒计（契约 11 §2.1），但一个挂住的 Agent 不该长期占着
# 一个服务线程。外壳自己的反代是 300s，这里收到 180s。
AGENT_TIMEOUT_S = 180

# 面板认的成功值。外壳 shell.js 把 status 不是「完成」也不是「正常」的标成失败，
# 而 6.6 状态词表里并没有「完成」这个词 —— 这处不一致已登记在交付报告里。
# 这里跟范例模块与面板保持一致，用「完成」/「失败」。
STATUS_OK = "完成"
STATUS_FAIL = "失败"
_STATUS_WORDS = {"完成", "正常", "加载中", "空结果", "过期", "缺失", "待确认", "失败"}

# 步骤的 sources 必须是**中文数据源名**，库内表名与工具码值不上屏（G9）。
# 九工具链的工具名在工作台侧任何文档里都没有登记，只有契约 §2.1 的例子给了一个，
# 所以这张表现在只有一项 + 一个中文兜底 —— 宁可粗，也不让 route_demo_child_asin
# 这类码值漏到屏幕上。真正该修的是让 Agent 自己在 step 里带 sources，见交付报告。
_TOOL_SOURCE = {
    "route_demo_child_asin": "产品主数据",
}
_DEFAULT_SOURCE = "需求预测 Agent"

_CJK = re.compile(r"[\u3400-\u9fff\u3000-\u303f\uff00-\uffef]")


def _rules(c: Ctx) -> rules.RuleSet:
    """外壳已按 lo/hi 夹紧并剥掉前缀，这里只做形状转换。"""
    return rules.from_params(c.params)


def handle_meta(c: Ctx) -> dict[str, Any]:
    rs = _rules(c)
    return {
        "data": data.meta(),
        "rule_version": rs.version_label(),
        "parameters": rules.describe(rs),
        "filter_options": data.filter_options(),
        "risk_labels": compute.RISK_LABELS,
        # 批次消耗方式不是可调参数（locked，切换要重建数据层），所以不在参数面板里，
        # 而是作为事实带出来，由库龄板块就地说明。
        "depletion": {
            "method": rs.depletion_method,
            "locked": rs.depletion_method_locked,
            "note": "库龄批次由数据层按 FIFO 前滚生成，切换需重建数据层",
        },
    }


def handle_children(c: Ctx) -> dict[str, Any]:
    rs = _rules(c)
    summaries, overview = listing.assess_all(rs)
    filtered = listing.apply_filters(summaries, c.query)
    limit = c.q_int("limit", DEFAULT_LIMIT)
    return {
        "rule_version": rs.version_label(),
        "total": len(summaries),
        "matched": len(filtered),
        "overview": overview,
        "scope": listing.scope_aggregate(filtered),
        "rows": filtered[:limit],
    }


def handle_child(c: Ctx) -> dict[str, Any]:
    """路径段走 c.rest —— 路由名不能带斜杠，_validate() 会直接拒。"""
    asin = c.rest[0] if c.rest else ""
    if not asin:
        return {"message": "缺少子 ASIN"}
    rs = _rules(c)
    assessment = compute.assess(asin, rs)
    if not assessment:
        # 外壳把处理函数的异常统一包成 500，没有让处理函数指定状态码的通路。
        # 所以按 sample 已建立的约定：回一个带 message 的载荷，前端识别后出占位。
        return {"message": f"没有子 ASIN {asin} 的数据"}
    parent = assessment["identity"]["parent_asin"]
    assessment["parent_daily"] = data.parent_daily_series(parent, 180)
    assessment["parent_inventory_daily"] = data.parent_inventory_series(parent, 180)
    assessment["parameters"] = rules.describe(rs)
    # 盘点结论五条。Agent 跑过就读结论库的最新一次，否则用确定性规则兜底 ——
    # 两条来源同一个形状，所以前端不分支。见 verdict.py 与
    # 01-方案与数据需求/10-盘点结论Agent接口契约.md v0.2。
    assessment["verdict"] = verdict.build(assessment, compute.AS_OF)
    # 需求判断。Agent 跑过就读结论库，没跑过回落数据包的统计口径 ——
    # origin / origin_label 让页面能看出是哪一种（契约 11 §3：回落必须看得出来）。
    assessment["forecast_judgment"] = forecast.judgment(asin)
    return assessment


# ---------------------------------------------------------------------------
# 可运行任务：重跑需求判断
# ---------------------------------------------------------------------------

def _cn(text: Any, fallback: str) -> str:
    """没有中文字符的一律当码值处理，换成中文兜底。

    Agent 的 step 只保证 `tool` 这一项存在，`label` 缺了或写成
    `route_demo_child_asin` 时，直接上屏就是 G9 说的枚举泄漏。
    判据是「含不含 CJK」而不是「含不含 ASCII」—— 中文标签里带
    ASIN、P50 这类 ASCII 是正常的。
    """
    s = str(text or "").strip()
    return s if s and _CJK.search(s) else fallback


def _sources(step: dict) -> list[str]:
    """中文数据源名。Agent 自己给了就用它，没给就按工具名查表。"""
    raw = step.get("sources")
    if isinstance(raw, list):
        cn = [str(x).strip() for x in raw if _CJK.search(str(x or ""))]
        if cn:
            return cn
    return [_TOOL_SOURCE.get(str(step.get("tool") or ""), _DEFAULT_SOURCE)]


def _step(label: str, detail: str, status: str = STATUS_OK,
          duration_ms: float = 0.0, sources: list[str] | None = None) -> dict:
    return {
        "label": label,
        "detail": detail,
        "status": status,
        "duration_ms": round(float(duration_ms or 0), 1),
        "sources": sources or [_DEFAULT_SOURCE],
    }


def _failed(obj: str, why: str, steps: list[dict] | None = None,
            label: str = "调用需求判断 Agent",
            sources: list[str] | None = None) -> dict:
    """Agent 不可达、超时、报错都走这里。

    **回 200 + 状态词表里的「失败」，不回 500。** 外壳把处理函数的异常统一包成
    500，而面板遇到非 2xx 只能显示「接口返回 500」—— 运营看不出是 Agent 没起来
    还是工作台自己炸了。所以失败也要是一个结构完整、原因是中文的正常响应。
    """
    steps = list(steps or [])
    steps.append(_step(label, why, STATUS_FAIL, sources=sources))
    return {
        "run": {
            "run_id": None,
            "object_id": obj or None,
            "data_as_of": compute.AS_OF.isoformat(),
            "status": STATUS_FAIL,
            "model_version": None,
        },
        "steps": steps,
        "message": why,
    }


def _call_agent(child_asin: str, trigger: str) -> dict[str, Any]:
    """POST 契约 §2.1 的端点。同步返回，跑完才回。

    这里**不跑 LLM**，也不解释判断内容 —— 工作台只负责触发与把过程转成面板形状。
    """
    target = paths.AGENT_ORIGIN.rstrip("/") + FORECAST_PATH
    body = json.dumps({"childAsin": child_asin, "trigger": trigger}).encode("utf-8")
    req = urllib.request.Request(
        target, data=body, method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=AGENT_TIMEOUT_S) as resp:
        return json.loads(resp.read().decode("utf-8"))


def handle_export_daily(c: Ctx):
    """逐日销量与需求导出成 xlsx。

    2026-08-31 会上王楠提的第二条：那张柱状图「不方便做工作……好多工作其实我们是
    拿表格来的」，落脚理由是「他给其他部门下单也是用文件下单」。
    所以导的是**能直接拿去下单的粒度**：一天一行，图上看得见的都给出来。

    刻意分成三页而不是挤在一页：
      逐日数据  —— 主表，按天
      事件      —— 图上那些活动带，本来只在悬停时能看到
      叠加指标  —— 价格 / 访问量 / 转化率那几条可切换的线，与主表同一批日期

    「实际 / 预测」不并进一列。并了以后拿到文件的人分不清哪天是已发生哪天是预测，
    而这正是这张图最要紧的一条区分（深色已发生、浅色未发生）。
    """
    asin = c.rest[0] if c.rest else ""
    if not asin:
        return {"message": "缺少子 ASIN"}
    rs = _rules(c)
    assessment = compute.assess(asin, rs)
    if not assessment:
        return {"message": f"没有子 ASIN {asin} 的数据"}

    chart = assessment.get("chart") or {}
    if not chart.get("available"):
        return {"message": "这个对象没有逐日数据可导"}

    ident = assessment.get("identity") or {}
    dates = chart.get("dates") or []
    actual = chart.get("actual") or []
    forecast = chart.get("forecast") or []
    as_of = chart.get("as_of") or c.as_of

    import datetime as dt

    def d(s):
        try:
            return dt.date.fromisoformat(s)
        except Exception:                                       # noqa: BLE001
            return s

    rows = []
    for i, ds in enumerate(dates):
        a = actual[i] if i < len(actual) else None
        f = forecast[i] if i < len(forecast) else None
        fv = f.get("value") if isinstance(f, dict) else f
        lo = f.get("lower") if isinstance(f, dict) else None
        hi = f.get("upper") if isinstance(f, dict) else None
        a = a or {}
        rows.append([
            d(ds),
            chart.get("weekdays", [None] * len(dates))[i] if i < len(chart.get("weekdays") or []) else None,
            "已发生" if ds <= as_of else "预测",
            a.get("value"),
            fv, lo, hi,
            "是" if a.get("is_stockout") else "",
            "是" if a.get("is_anomaly") else "",
            a.get("quality_label"),
            a.get("trust_note") or a.get("adjustment_reason"),
        ])

    sheets = [{
        "name": "逐日数据",
        "headers": ["日期", "星期", "数据性质", "实际销量（件）",
                    "预测销量（件）", "预测下界", "预测上界",
                    "当天缺货", "当天异常", "数据质量", "口径说明"],
        "rows": rows,
        "widths": [12, 8, 10, 14, 14, 11, 11, 10, 10, 12, 40],
    }]

    bands = list(chart.get("bands") or []) + list(chart.get("points") or [])
    if bands:
        sheets.append({
            "name": "事件",
            "headers": ["类型", "名称", "开始", "结束", "天数", "是否未来"],
            "rows": [[b.get("type_label"), b.get("label"), d(b.get("from")),
                      d(b.get("to")), b.get("days"),
                      "是" if b.get("is_future") else ""] for b in bands],
            "widths": [14, 28, 12, 12, 8, 10],
        })

    lines = [ln for ln in (chart.get("lines") or []) if not ln.get("is_constant")]
    if lines:
        head = ["日期"] + [f"{ln.get('label')}（{ln.get('unit')}）" if ln.get("unit")
                          else str(ln.get("label")) for ln in lines]
        lrows = []
        for i, ds in enumerate(dates):
            vals = [(ln.get("values") or [None] * len(dates))[i]
                    if i < len(ln.get("values") or []) else None for ln in lines]
            if any(v is not None for v in vals):
                lrows.append([d(ds)] + vals)
        if lrows:
            sheets.append({"name": "叠加指标", "headers": head, "rows": lrows,
                           "widths": [12] + [14] * len(lines)})

    name = f"{asin}-逐日销量与需求-{as_of}.xlsx"
    return Download(filename=name, data=xlsx.build(sheets))


def handle_forecast_status(c: Ctx) -> dict[str, Any]:
    """轮询用：把 Agent 的状态接口转成面板要的 `{run, steps}`。

    **页面不再 await 那次触发调用。** 实测一次运行 87~107 秒，而触发那侧是
    跑完才回；await 它等于让面板整段时间只显示一个不动的字。改成发出去就轮
    这个接口，逐步显示真实进度 —— 步骤是 Agent 分步落库的，不是按节奏播的。
    需求与实测见 01-方案与数据需求/13-需求预测Agent分段运行需求.md R1/R2。

    这里只做转形状，不判断内容：`加载中 / 完成 / 失败` 三个词由 Agent 给，
    都在契约 02 §6.6 的词表里，外壳的 `_STATUS_WORDS` 认得。
    """
    obj = (c.rest[0] if c.rest else c.q("object")).strip()
    if not obj:
        return {"run": {"object_id": None, "status": "空结果"}, "steps": []}

    target = paths.AGENT_ORIGIN.rstrip("/") + FORECAST_PATH + "/status?childAsin=" + obj
    try:
        with urllib.request.urlopen(target, timeout=10) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"run": {"object_id": obj, "status": "失败",
                        "message": f"状态接口返回异常（HTTP {e.code}）"}, "steps": []}
    except urllib.error.URLError:
        return {"run": {"object_id": obj, "status": "失败",
                        "message": "连不上 Agent 服务"}, "steps": []}
    except (ValueError, OSError, TimeoutError):
        return {"run": {"object_id": obj, "status": "失败",
                        "message": "状态接口的响应读不了"}, "steps": []}

    src = payload.get("run") or {}
    steps = []
    for s in payload.get("steps") or []:
        if not isinstance(s, dict):
            continue
        status = str(s.get("status") or STATUS_OK)
        steps.append(
            _step(
                _cn(s.get("label"), "Agent 步骤"),
                # 还在跑的那一步没有结论可报，留「—」不替它编。
                _cn(s.get("detail"), "—"),
                status if status in _STATUS_WORDS else STATUS_OK,
                s.get("duration_ms") or 0,
                _sources(s),
            )
        )
    return {
        "run": {
            "run_id": src.get("run_id"),
            "object_id": src.get("child_asin") or obj,
            "status": str(src.get("status") or "待确认"),
            "current_step": src.get("current_step"),
            "total_steps": src.get("total_steps"),
            "data_as_of": compute.AS_OF.isoformat(),
            "message": src.get("error"),
        },
        "steps": steps,
    }


def handle_run_demand_forecast(c: Ctx) -> dict[str, Any]:
    """重跑需求预测。转调 Agent，把返回的 steps 转成面板要的 {run, steps}。

    面板是 GET 调用（`shell.js` 的 `runTask` 带 `?object=<子 ASIN>`），
    对象也允许走路径段。**跑完不从 Agent 响应里取数字上屏** ——
    页面重新读表取判断（契约 §2.3），这样刷新、分享链接、别人打开看到的是同一份。
    所以这里最后一步是**回读结论库**：Agent 说写好了、工作台却读不到，
    是这条链上唯一一种在界面上没有症状的错误。
    """
    obj = (c.rest[0] if c.rest else c.q("object")).strip()
    trigger = c.q("trigger", "manual") or "manual"
    if trigger not in ("manual", "weekly", "priority"):
        trigger = "manual"

    if not obj:
        return {
            "run": {"object_id": None, "status": "空结果",
                    "data_as_of": compute.AS_OF.isoformat()},
            "steps": [_step("确认分析对象", "未指定对象，先在页面上选一个子 ASIN",
                            STATUS_FAIL, sources=["产品主数据"])],
        }

    t0 = time.perf_counter()
    if obj not in data.all_children():
        return _failed(obj, f"子 ASIN {obj} 不在 342 个产品脊椎里",
                       label="确认对象在脊椎内", sources=["产品主数据"])
    pre = [_step("确认对象在脊椎内",
                 f"命中 · 触发方式 {af.TRIGGER_LABEL.get(trigger, '手动')}",
                 STATUS_OK, (time.perf_counter() - t0) * 1000, ["产品主数据"])]

    try:
        payload = _call_agent(obj, trigger)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return _failed(obj, "Agent 服务上还没有需求判断这个接口", pre)
        return _failed(obj, f"Agent 服务返回异常（HTTP {e.code}）", pre)
    except urllib.error.URLError:
        return _failed(obj, "连不上 Agent 服务，判断没有开跑", pre)
    except TimeoutError:
        return _failed(obj, f"Agent 超过 {AGENT_TIMEOUT_S} 秒没有回应", pre)
    except (ValueError, OSError):
        return _failed(obj, "Agent 的响应不是合法 JSON，无法判定是否写库", pre)

    if not isinstance(payload, dict) or not payload.get("ok"):
        errs = payload.get("errors") if isinstance(payload, dict) else None
        why = "；".join(str(x) for x in errs) if errs else "Agent 报告本次判断未完成"
        return _failed(obj, why, pre)

    steps = pre
    for s in payload.get("steps") or []:
        if not isinstance(s, dict):
            continue
        status = str(s.get("status") or STATUS_OK)
        steps.append(
            _step(
                _cn(s.get("label"), "Agent 步骤"),
                # 没给中文说明就留「—」。不替它编一句「已完成」——
                # 那是拿一句话冒充这一步真说了什么。
                _cn(s.get("summary") or s.get("detail"), "—"),
                status if status in _STATUS_WORDS else STATUS_OK,
                s.get("duration_ms") or 0,
                _sources(s),
            )
        )

    # 回读完整 run。Agent 报 ok 但工作台读不到（90日/五因子/步骤任一不齐）
    # 必须判失败，不能让页面静默混用 Agent 判断与数据包预测。
    t1 = time.perf_counter()
    got = af.latest(obj)
    ms = (time.perf_counter() - t1) * 1000
    if got:
        run = got["run"]
        steps.append(_step(
            "回读预测结果库",
            f"读到 {len(got['daily'])} 天预测、{len(got['factors'])} 项判断和 "
            f"{len(got['steps'])} 个步骤",
            STATUS_OK, ms, ["需求预测结果"]))
        status, run_id, model = STATUS_OK, run.get("run_id"), run.get("model_version")
    else:
        steps.append(_step(
            "回读预测结果库",
            "Agent 报告已写入，但90天预测、五项判断或步骤不完整，页面继续使用数据包快照",
            STATUS_FAIL, ms, ["需求预测结果"]))
        status, run_id, model = STATUS_FAIL, payload.get("run_id"), payload.get("model_version")

    return {
        "run": {
            "run_id": run_id,
            "object_id": obj,
            "data_as_of": compute.AS_OF.isoformat(),
            "status": status,
            "model_version": model,
        },
        "steps": steps,
    }


TASKS = [
    {
        "id": "demand-forecast",
        "label": "重跑需求预测",
        "needs": "object",
        "run": "run-demand-forecast",
        # 有 `poll` 时外壳不 await 触发那次调用，改成边跑边轮这个路由。
        # 一次运行 87~107 秒，await 的话面板整段时间只有一个不动的字。
        "poll": "forecast-status",
        "hint": "顺序读取事实，重新产出未来90天逐日P10/P50/P90和五项需求判断",
    },
]


MODULE = {
    "id": "inventory",
    "label": "产品与库存",
    "api_version": 1,
    # 显式写。不写外壳默认取 mid[:3]，对 inventory 恰好也是 inv，
    # 但关键词模块就是因为默认取到 key 而不是 kw 才出的问题，别赌这个。
    "prefix": "inv",
    "pages": [
        {"id": "inv-detail", "label": "单品盘点"},
        {"id": "inv-risk", "label": "异常总览"},
        {"id": "inv-scope", "label": "库存全览"},
    ],
    "routes": {
        "meta": handle_meta,
        "children": handle_children,
        "child": handle_child,
        # 路由名不带斜杠 —— registry._validate() 会直接拒，竞品模块曾因此整块降级。
        "run-demand-forecast": handle_run_demand_forecast,
        # 轮询进度。任务声明里的 `poll` 指向它。
        "forecast-status": handle_forecast_status,
        # 导出。回 Download，服务端认类型走文件通道而不是 JSON。
        "export-daily": handle_export_daily,
    },
    # 可运行任务。外壳的任务面板读这个，模块自己不做任务入口（契约第 9 节）。
    "tasks": TASKS,
    "params": rules.PARAMS,
    "db": None,  # 读产品包，没有自己的库
    "invalidate": listing.clear_caches,
}
