"""接入范例模块 · 外壳唯一读的入口文件。

这个模块的用途有三个：
1. 契约第 8 节的参考实现 —— 新模块照抄这个文件的形状；
2. 外壳的自检 —— 它真读 489MB 产品包，跑通说明发现、路由、参数、取数全链路是活的；
3. 门禁的落点 —— G1–G17 都能打在它身上。

给客户演示前用 WORKBENCH_MODULES 把它排除掉，或者直接删掉这个目录（外壳零改动）。
"""

from __future__ import annotations

from core import ctx as ctx_mod
from core.ruleset import Param

from . import data

PREFIX = "smp"

PARAMS = [
    Param(
        "page_size",
        "每页对象数",
        default=50,
        kind="num",
        lo=10,
        hi=342,
        step=10,
        group="清单",
        note="只影响清单页展示条数，不影响筛选结果总数",
    ),
    Param(
        "sort",
        "排序",
        default="asin",
        kind="enum",
        choices=[("asin", "按子 ASIN"), ("parent", "按父体"), ("name", "按品名")],
        group="清单",
    ),
]

_SORT_SQL = {"asin": "child_asin", "parent": "parent_asin", "name": "product_name"}


def _filtered(c: ctx_mod.Ctx) -> list[dict]:
    rows = data.spine()
    parent = c.q("parent")
    keyword = c.q("q").strip().lower()
    if parent:
        rows = [r for r in rows if r.get("parent_asin") == parent]
    if keyword:
        rows = [
            r
            for r in rows
            if keyword in (r.get("child_asin") or "").lower()
            or keyword in (r.get("product_name") or "").lower()
        ]
    key = _SORT_SQL.get(c.params.get("sort"), "child_asin")
    return sorted(rows, key=lambda r: (r.get(key) or "", r.get("child_asin") or ""))


def handle_meta(c: ctx_mod.Ctx) -> dict:
    return {
        "as_of": c.as_of,
        "fingerprint": c.fingerprint,
        "total": len(data.spine()),
        "parents": data.parents(),
        # 数据性质与状态用词表里的中文词，不回枚举名
        "nature": "真实",
        "condition": "正常",
    }


def handle_children(c: ctx_mod.Ctx) -> dict:
    rows = _filtered(c)
    limit = int(c.params.get("page_size") or 50)
    return {
        "total": len(rows),
        "shown": min(limit, len(rows)),
        "items": [
            {
                "child_asin": r["child_asin"],
                "parent_asin": r.get("parent_asin"),
                "name": r.get("product_name"),
                "colorway": r.get("colorway"),
                "size": r.get("size"),
                "nature": data.nature_of("direct"),
            }
            for r in rows[:limit]
        ],
    }


def handle_child(c: ctx_mod.Ctx) -> dict:
    if not c.rest:
        return {"condition": "空结果", "message": "未指定对象"}
    row = data.child(c.rest[0])
    if row is None:
        return {"condition": "缺失", "message": "该对象不在脊椎里"}

    # 显式白名单，不是黑名单。黑名单会漏 —— 第一版用黑名单就把库里的列名当标签
    # 上了屏，还带出一整段 provenance JSON。数据包加一列，黑名单就又漏一次。
    fields = []
    for col, label in data.FIELD_LABELS.items():
        v = row.get(col)
        if v in (None, ""):
            continue
        fields.append({"label": label, "value": data.display(col, v)})

    return {
        "child_asin": row["child_asin"],
        "parent_asin": row.get("parent_asin"),
        "parent_name": row.get("parent_name"),
        "nature": data.nature_of(row.get("value_origin")),
        "condition": data.condition_of(row.get("attribute_quality_status")),
        "fields": fields,
    }


def handle_run(c: ctx_mod.Ctx) -> dict:
    """参考实现：一个可运行任务，产出 run + steps。

    这个任务是纯算子（没有 LLM），因为范例模块的用途是验证外壳链路。
    真实模块的任务应该只放"普通代码做不了的"判断，算术留在算子层。

    steps 的 sources 用**中文数据源名**，库里的表名不上屏（G9）。
    """
    import time

    obj = c.rest[0] if c.rest else c.q("object")
    steps = []

    def step(label: str, fn):
        t0 = time.perf_counter()
        detail, sources = fn()
        steps.append(
            {
                "label": label,
                "detail": detail,
                "sources": sources,
                "status": "完成",
                "duration_ms": round((time.perf_counter() - t0) * 1000, 1),
            }
        )

    if not obj:
        return {
            "run": {"status": "空结果"},
            "steps": [{"label": "确认分析对象", "detail": "未指定对象", "status": "失败"}],
        }

    spine = {r["child_asin"] for r in data.spine()}
    step("确认对象在脊椎内", lambda: (
        f"命中 · 脊椎共 {len(spine)} 个子 ASIN" if obj in spine else "未命中脊椎",
        ["产品主数据"],
    ))
    if obj not in spine:
        steps[-1]["status"] = "失败"
        return {"run": {"status": "缺失", "object_id": obj}, "steps": steps}

    row = data.child(obj) or {}
    step("读取身份字段", lambda: (
        f"{row.get('product_name') or '—'} · {row.get('size') or '—'}",
        ["产品主数据"],
    ))
    step("核对属性完整度", lambda: (
        f"属性完整度 {data.display('attribute_quality_status', row.get('attribute_quality_status'))}",
        ["产品主数据"],
    ))
    step("确认父体归属", lambda: (
        f"父体 {row.get('parent_asin') or '—'} · {row.get('parent_name') or '—'}",
        ["产品主数据"],
    ))

    return {
        "run": {
            "run_id": f"{obj}-{c.as_of}-1",
            "object_id": obj,
            "data_as_of": c.as_of,
            "status": "完成",
            "model_version": "sample-operator-v1",
        },
        "steps": steps,
    }


MODULE = {
    "id": "sample",
    "label": "接入范例",
    "api_version": 1,
    "prefix": PREFIX,
    "pages": [
        {"id": "list", "label": "对象清单"},
        {"id": "detail", "label": "单对象"},
    ],
    "routes": {
        "meta": handle_meta,
        "children": handle_children,
        "child": handle_child,
        "run": handle_run,
    },
    # 可运行任务。外壳的任务面板读这个，模块自己不做任务入口（契约第 9 节）。
    "tasks": [
        {
            "id": "verify-identity",
            "label": "核对对象身份",
            "needs": "object",
            "run": "run",
            "hint": "确认对象在脊椎内并核对身份字段",
        },
    ],
    "params": PARAMS,
    "db": None,                      # 本模块读产品包，没有自己的库
    "invalidate": data.clear_caches,
}
