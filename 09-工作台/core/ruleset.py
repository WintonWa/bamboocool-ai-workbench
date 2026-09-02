"""参数声明、解析、夹紧、指纹。

契约 5.2：参数键一律带模块前缀，一条 query string 同时携带全部模块的参数，
各模块只解析自己前缀下的键并忽略其余。

模块只负责**声明**，解析和夹紧统一在这里做。这解决了两个旧 demo 的三处不一致：
一边 from_query 收 parse_qs 的 dict[str, list[str]]、一边收扁平 dict；
一边夹紧、一边不夹紧；一边指纹用 sha1、一边用明文拼接。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


class Param:
    """一个可调参数的声明。

    kind:
      "num"  数值，必须给 lo/hi/step，越界夹紧
      "bool" 布尔，接受 1/0/true/false/on/off
      "enum" 枚举，choices 是 [(值, 中文标签)]，非法值回落 default
    """

    __slots__ = ("name", "label", "default", "kind", "lo", "hi", "step", "choices", "group", "note")

    def __init__(
        self,
        name: str,
        label: str,
        default: Any,
        kind: str = "num",
        lo: float | None = None,
        hi: float | None = None,
        step: float | None = None,
        choices: list[tuple[str, str]] | None = None,
        group: str = "",
        note: str = "",
    ) -> None:
        if kind == "num" and (lo is None or hi is None or step is None):
            raise ValueError(f"数值参数 {name} 必须声明 lo / hi / step")
        if kind == "enum" and not choices:
            raise ValueError(f"枚举参数 {name} 必须声明 choices")
        self.name = name
        self.label = label
        self.default = default
        self.kind = kind
        self.lo = lo
        self.hi = hi
        self.step = step
        self.choices = choices or []
        self.group = group
        self.note = note


def _coerce_num(raw: str, p: Param) -> float | int:
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return p.default
    if v != v or v in (float("inf"), float("-inf")):      # NaN / inf
        return p.default
    v = max(float(p.lo), min(float(p.hi), v))             # 夹紧，不透传越界值
    return int(round(v)) if isinstance(p.default, int) else round(v, 6)


def _coerce_bool(raw: str, p: Param) -> bool:
    s = raw.strip().lower()
    if s in ("1", "true", "yes", "on"):
        return True
    if s in ("0", "false", "no", "off"):
        return False
    return bool(p.default)


def parse(prefix: str, params: list[Param], query: Mapping[str, Any]) -> dict[str, Any]:
    """从 query 里取出本模块的参数。

    query 同时接受 parse_qs 的 {k: [v]} 和扁平的 {k: v}，两种都行——
    旧代码两个模块签名不一致，这里一次吃掉。
    """
    out: dict[str, Any] = {}
    for p in params:
        key = f"{prefix}.{p.name}"
        raw = query.get(key)
        if isinstance(raw, (list, tuple)):
            raw = raw[0] if raw else None
        if raw is None or raw == "":
            out[p.name] = p.default
            continue
        raw = str(raw)
        if p.kind == "num":
            out[p.name] = _coerce_num(raw, p)
        elif p.kind == "bool":
            out[p.name] = _coerce_bool(raw, p)
        else:
            valid = {c[0] for c in p.choices}
            out[p.name] = raw if raw in valid else p.default
    return out


def fingerprint(prefix: str, values: Mapping[str, Any]) -> str:
    """稳定短指纹，用于缓存键。排序后 sha1，取前 12 位。"""
    blob = json.dumps({prefix: values}, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]


def describe(prefix: str, params: list[Param], values: Mapping[str, Any]) -> list[dict]:
    """给参数面板的 UI 提示。标签是中文成品文案，键名带前缀。"""
    out = []
    for p in params:
        item = {
            "key": f"{prefix}.{p.name}",
            "label": p.label,
            "kind": p.kind,
            "value": values.get(p.name, p.default),
            "default": p.default,
            "group": p.group,
        }
        if p.note:
            item["note"] = p.note
        if p.kind == "num":
            item.update(lo=p.lo, hi=p.hi, step=p.step)
        if p.kind == "enum":
            item["choices"] = [{"value": v, "label": lbl} for v, lbl in p.choices]
        out.append(item)
    return out


def check_prefix(prefix: str, params: list[Param]) -> None:
    """自检：参数名不许自带前缀（否则会变成 inv.inv.xxx），也不许重名。"""
    seen = set()
    for p in params:
        if "." in p.name:
            raise ValueError(f"参数名不要带前缀或点号：{p.name}")
        if p.name in seen:
            raise ValueError(f"参数重名：{prefix}.{p.name}")
        seen.add(p.name)
