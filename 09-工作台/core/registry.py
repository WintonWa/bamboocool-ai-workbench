"""模块发现。

契约 8.1：扫 modules/*/module.py，import，读 MODULE，自动生成路由、导航、参数面板。
**这里不含任何模块清单。** 新增或删除一个模块，外壳一行代码都不用改。

契约 8.4：逐模块 try/except。import 失败的标 degraded 并在导航里降级显示，
其余模块照常服务。判据是把任意一个 module.py 改成语法错误，服务仍能启动。

契约 8.7：开发模式下按 mtime 只重载改动的那个模块的子树，其他模块不动。
"""

from __future__ import annotations

import importlib
import sys
import traceback
from pathlib import Path
from typing import Any, Callable

from . import paths, ruleset

API_VERSION = 1
_REQUIRED = ("id", "label", "api_version", "pages", "routes")


class Module:
    """一个已发现的模块。degraded=True 时 spec 为空，只有 error 可读。"""

    __slots__ = ("id", "spec", "error", "mtime", "params", "prefix")

    def __init__(self, mid: str) -> None:
        self.id = mid
        self.spec: dict[str, Any] = {}
        self.error: str = ""
        self.mtime: float = 0.0
        self.params: list[ruleset.Param] = []
        self.prefix: str = ""

    @property
    def degraded(self) -> bool:
        return bool(self.error) or not self.spec

    @property
    def label(self) -> str:
        return self.spec.get("label") or self.id

    def public(self) -> dict:
        """给 /api/modules 的载荷。错误只给一句人类可读的话，不给堆栈。"""
        if self.degraded:
            return {
                "id": self.id,
                "label": self.label,
                "degraded": True,
                "reason": self.error.strip().splitlines()[-1][:200] if self.error else "模块未能加载",
                "pages": [],
            }
        return {
            "id": self.id,
            "label": self.label,
            "degraded": False,
            "pages": self.spec.get("pages", []),
            "prefix": self.prefix,
            # 可运行任务（可选）。外壳的任务面板据此渲染，自己不含任何清单。
            # 形状：{id, label, needs?: "object", run: "<本模块路由名>", hint?}
            "tasks": self.spec.get("tasks", []),
            # 可选：本模块拥有的 Agent 声明。Agent 配置页读它。
            # 形状见契约 8.1。现在多数 Agent 还登记在 modules/agentcfg/registry_seed.py，
            # 模块认领后搬到自己这里，这个字段就有值了。
            "agents": self.spec.get("agents", []),
            "params": ruleset.describe(
                self.prefix, self.params, {p.name: p.default for p in self.params}
            ),
        }


_registry: dict[str, Module] = {}


def _module_dirs() -> list[Path]:
    if not paths.MODULES_DIR.is_dir():
        return []
    out = []
    for d in sorted(paths.MODULES_DIR.iterdir()):
        if not d.is_dir() or d.name.startswith((".", "_")):
            continue
        if not (d / "module.py").is_file():
            continue
        if paths.ENABLED_MODULES and d.name not in paths.ENABLED_MODULES:
            continue
        out.append(d)
    return out


def _tree_mtime(d: Path) -> float:
    return max((p.stat().st_mtime for p in d.rglob("*.py")), default=0.0)


def _validate(spec: dict, mid: str) -> None:
    missing = [k for k in _REQUIRED if k not in spec]
    if missing:
        raise ValueError(f"MODULE 缺少必填键：{', '.join(missing)}")
    if spec["id"] != mid:
        raise ValueError(f"MODULE['id']={spec['id']!r} 必须等于目录名 {mid!r}")
    if spec["api_version"] != API_VERSION:
        raise ValueError(
            f"api_version={spec['api_version']} 与外壳的 {API_VERSION} 不兼容"
        )
    if not isinstance(spec["routes"], dict) or not spec["routes"]:
        raise ValueError("routes 必须是非空字典：资源名 -> 处理函数")
    for name, fn in spec["routes"].items():
        if "/" in name:
            raise ValueError(f"路由资源名不要带斜杠：{name!r}")
        if not callable(fn):
            raise ValueError(f"路由 {name!r} 的处理函数不可调用")
    if not isinstance(spec["pages"], list) or not spec["pages"]:
        raise ValueError("pages 必须是非空列表")
    for pg in spec["pages"]:
        if not isinstance(pg, dict) or "id" not in pg or "label" not in pg:
            raise ValueError(f"pages 每项必须含 id 与 label：{pg!r}")


def _purge(mid: str) -> None:
    dead = [k for k in sys.modules if k == f"modules.{mid}" or k.startswith(f"modules.{mid}.")]
    for k in dead:
        sys.modules.pop(k, None)


def _load(d: Path) -> Module:
    mid = d.name
    m = Module(mid)
    m.mtime = _tree_mtime(d)
    try:
        mod = importlib.import_module(f"modules.{mid}.module")
        spec = getattr(mod, "MODULE", None)
        if not isinstance(spec, dict):
            raise ValueError("module.py 必须定义一个名为 MODULE 的字典")
        _validate(spec, mid)
        m.spec = spec
        m.prefix = spec.get("prefix") or mid[:3]
        m.params = list(spec.get("params") or [])
        ruleset.check_prefix(m.prefix, m.params)
    except Exception:
        m.error = traceback.format_exc()
        m.spec = {}
    return m


def discover(force: bool = False) -> dict[str, Module]:
    """发现或刷新全部模块。开发模式下按 mtime 只重载改动的那个。"""
    global _registry
    dirs = _module_dirs()
    names = {d.name for d in dirs}

    for gone in set(_registry) - names:                    # 目录被删掉的
        _registry.pop(gone, None)
        _purge(gone)

    for d in dirs:
        mid = d.name
        cur = _registry.get(mid)
        if cur is None or force:
            _purge(mid)
            _registry[mid] = _load(d)
            continue
        if paths.DEV and _tree_mtime(d) > cur.mtime:
            inval = cur.spec.get("invalidate")
            if callable(inval):
                try:
                    inval()
                except Exception:
                    pass                                    # 清缓存失败不该拖住重载
            _purge(mid)
            _registry[mid] = _load(d)
    return _registry


# 导航顺序。按运营看数的先后排：先看总体，再看货，再看词与对手，最后看投放。
#
# 为什么这个清单在外壳而不在各模块里：顺序是**跨模块**的判断 ——
# 「库存排在关键词前面」这件事，在库存自己的文件里是决定不了的，
# 它不知道关键词的存在。写成各模块自己声明一个序号，等于把一个整体判断
# 拆成六处互不知情的局部声明，加一个模块就要去改别人的号。
#
# 这不违反"模块自注册、加模块外壳零改动"：**不在这个清单里的模块照常出现**，
# 只是排在已列模块之后、按 id 字母序。所以新模块不改这里也能跑，
# 只有想插到特定位置时才需要来加一行。
NAV_ORDER = [
    "overview",     # 总览（汇总其他模块的结论，目前是空页面）
    "inventory",    # 产品与库存
    "preinvest",    # 面料预投（库存那条链的下游：预测→预投→下单）
    "keyword",      # 关键词分析
    "competitor",   # 竞品分析
    "ads",          # 广告分析
    "agentcfg",     # Agent 配置（跨模块的设置面，排在业务模块之后）
    "sample",       # 接入范例（演示时用 WORKBENCH_MODULES 排除）
]


def _nav_key(mid: str) -> tuple:
    """已列模块按清单顺序，未列模块排在最后并按 id 字母序。"""
    try:
        return (0, NAV_ORDER.index(mid), mid)
    except ValueError:
        return (1, 0, mid)


def modules() -> list[Module]:
    return [_registry[k] for k in sorted(_registry, key=_nav_key)]


def get(mid: str) -> Module | None:
    return _registry.get(mid)


def resolve(mid: str, resource: str) -> Callable | None:
    m = _registry.get(mid)
    if m is None or m.degraded:
        return None
    return m.spec.get("routes", {}).get(resource)


def health() -> dict:
    ms = modules()
    return {
        "total": len(ms),
        "ok": [m.id for m in ms if not m.degraded],
        "degraded": [m.id for m in ms if m.degraded],
        "enabled_filter": list(paths.ENABLED_MODULES),
        "dev": paths.DEV,
    }
