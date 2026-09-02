"""只读 SQLite 访问。

两个旧 demo 各写了一份 connect / rows / one，函数体几乎一致，差别只在路径来源和
是否显式传 con。这里合成一份并统一成显式传 con（模块自己持有连接，互不干扰）。

注意：旧代码里 App A 的 _num() 是"取值强转 float"、App B 的 _num() 是"格式化成显示字符串"，
同名反向。这里一个都不收，避免把这对 false friend 带进公共层。
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable, Sequence


def connect(path: str | Path) -> sqlite3.Connection:
    """以只读 URI 打开。不存在就直接报错，不静默返回空连接。

    每次调用返回**新连接**。不要把返回值缓存起来跨线程复用 —— 用 pool() 代替。
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"数据包不存在：{p}")
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only = ON")
    return con


_local = threading.local()


def pool(path: str | Path) -> sqlite3.Connection:
    """按线程复用只读连接。**模块取连接一律用这个，不要自己 lru_cache。**

    服务是 ThreadingHTTPServer，前端经常并行发好几个请求（页面同时取 meta 和
    对象详情）。一个 SQLite 连接被两个线程同时 execute 会偶发
    `database disk image is malformed` —— 文件其实没坏，quick_check 是 ok 的，
    只是连接不是给并发用的。`check_same_thread=False` 只是解除了检查，
    并不会替你串行化。

    这个坑第一版就踩到了：范例模块用 @lru_cache 缓存单连接，页面一并行请求就 500。
    """
    key = f"con:{Path(path).resolve()}"
    con = getattr(_local, key, None)
    if con is None:
        con = connect(path)
        setattr(_local, key, con)
    return con


def rows(con: sqlite3.Connection, sql: str, args: Sequence[Any] = ()) -> list[dict]:
    cur = con.execute(sql, args)
    try:
        return [dict(r) for r in cur.fetchall()]
    finally:
        cur.close()


def one(con: sqlite3.Connection, sql: str, args: Sequence[Any] = ()) -> dict | None:
    cur = con.execute(sql, args)
    try:
        r = cur.fetchone()
        return dict(r) if r else None
    finally:
        cur.close()


def scalar(con: sqlite3.Connection, sql: str, args: Sequence[Any] = ()) -> Any:
    cur = con.execute(sql, args)
    try:
        r = cur.fetchone()
        return r[0] if r else None
    finally:
        cur.close()


def table_names(con: sqlite3.Connection) -> set[str]:
    return {
        r["name"]
        for r in rows(con, "select name from sqlite_master where type='table'")
    }


def attach(con: sqlite3.Connection, path: str | Path, alias: str) -> None:
    """跨库只读 ATTACH。需要产品身份时用它读产品包，不要在自己的包里重建维度表。"""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"要挂载的数据包不存在：{p}")
    con.execute("ATTACH DATABASE ? AS " + _safe_alias(alias), (f"file:{p}?mode=ro",))


def _safe_alias(alias: str) -> str:
    if not alias.isidentifier():
        raise ValueError(f"非法的库别名：{alias!r}")
    return alias


def spine_children(product_db: str | Path) -> set[str]:
    """产品对象脊椎的全部子 ASIN。模块自检用（契约 G8）。"""
    con = connect(product_db)
    try:
        return {r["child_asin"] for r in rows(con, "select child_asin from dim_product_child")}
    finally:
        con.close()
