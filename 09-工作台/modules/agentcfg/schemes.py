"""Agent 配置方案（方案一 / 方案二 / 方案三…）

由来：2026-08-31 会上王楠要的第三条。原话是「你在这个板块，就是你右上角只需要加一个
方案一。默认方案，或者方案一、方案二、方案三」，而动机在后面那句：
「我卖给其他家，其他家他会在这过程中做他自己的方案……他做那方案就是很宝贵的东西，
我能拿来卖钱的」。

所以方案是**要留下来的资产**，不能只存在浏览器的 localStorage 里 ——
换台机器就没了的东西没法收集也没法卖。落在这里的 JSON 文件。

一个方案 = 某个 Agent 的一套阈值取值。它只覆盖那个 Agent 在登记表里声明的
thresholds 那几个键，不碰别的 —— 否则「换个方案」会顺手改掉隔壁板块的口径。

「默认方案」不入库，每次按各模块 Param 的 default 现算。这样改了代码里的默认值，
默认方案跟着变；存下来就会变成一份悄悄过期的副本。
"""

from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any

STORE = Path(__file__).resolve().parent / "derived" / "schemes.json"

BUILTIN_ID = "default"
BUILTIN_NAME = "方案一（默认）"

# 方案名允许的长度。太长的名字会把板块标题行挤掉，下拉也读不出来。
NAME_MAX = 24


def _load() -> dict:
    if not STORE.exists():
        return {}
    try:
        raw = json.loads(STORE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # 文件坏了不能让整个模块跟着降级 —— 方案是增强项，读不到就当没有自定义方案。
        return {}
    return raw if isinstance(raw, dict) else {}


def _save(data: dict) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STORE)                       # 原子替换，避免写一半被读到


def _clean_name(raw: Any) -> str:
    name = re.sub(r"\s+", " ", str(raw or "")).strip()
    return name[:NAME_MAX]


def for_agent(agent: dict, params_by_key: dict) -> list[dict]:
    """某个 Agent 的方案清单，第一项永远是默认方案。

    params_by_key 是全站参数声明 {键: 声明}，用来算默认值并过滤掉
    登记表里写错的键 —— 写错的键静默丢掉而不是报错，因为 G25 已经在管这件事，
    这里再报一次会让同一个错出现两遍。
    """
    keys = [k for k in (agent.get("thresholds") or []) if k in params_by_key]
    out = [{
        "id": BUILTIN_ID,
        "name": BUILTIN_NAME,
        "builtin": True,
        "values": {k: params_by_key[k].get("default") for k in keys},
    }]
    for s in _load().get(agent.get("id"), []):
        vals = {k: v for k, v in (s.get("values") or {}).items() if k in keys}
        out.append({
            "id": s.get("id"),
            "name": s.get("name") or "未命名",
            "builtin": False,
            "values": vals,
            "note": s.get("note") or "",
            "saved_at": s.get("saved_at") or "",
        })
    return out


def save(agent_id: str, name: str, values: dict, allowed: list,
         scheme_id: str | None = None, note: str = "") -> dict:
    """新建或改名/改值。allowed 是这个 Agent 允许的阈值键。

    返回落库后的那一条。改的是内置方案则直接拒 —— 默认方案是代码里的默认值，
    允许改它等于让「默认」这个词失去意义。
    """
    if scheme_id == BUILTIN_ID:
        raise ValueError("默认方案不能改，另存一个新方案")
    name = _clean_name(name)
    if not name:
        raise ValueError("方案要有名字")
    if name == BUILTIN_NAME:
        raise ValueError("这个名字留给默认方案")

    picked = {k: v for k, v in (values or {}).items() if k in set(allowed)}
    if not picked:
        raise ValueError("这个方案没有任何属于该 Agent 的阈值")

    data = _load()
    lst = data.setdefault(agent_id, [])
    row = {
        "id": scheme_id or uuid.uuid4().hex[:12],
        "name": name,
        "values": picked,
        "note": _clean_name(note)[:80],
        "saved_at": time.strftime("%Y-%m-%d %H:%M"),
    }
    for i, s in enumerate(lst):
        if s.get("id") == row["id"]:
            lst[i] = row
            break
        if s.get("name") == name:            # 同名视为改同一个，不建重名
            row["id"] = s.get("id") or row["id"]
            lst[i] = row
            break
    else:
        lst.append(row)
    _save(data)
    return row


def delete(agent_id: str, scheme_id: str) -> bool:
    if scheme_id == BUILTIN_ID:
        raise ValueError("默认方案不能删")
    data = _load()
    lst = data.get(agent_id) or []
    left = [s for s in lst if s.get("id") != scheme_id]
    if len(left) == len(lst):
        return False
    data[agent_id] = left
    _save(data)
    return True
