"""模块路由处理函数收到的上下文。

模块通过它拿到 query、已夹紧的本模块参数、参数指纹和剩余路径段，
不需要 import server，也拿不到 socket 或 handler 本身。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


# 本机 /usr/bin/python3 是 3.9.6：dataclass(slots=True) 要 3.10+，
# 而手写 __slots__ 会与 dataclass 生成的默认值类变量冲突，所以这里不用 slots。
# Ctx 每个请求只造一个，省这点内存没意义。
@dataclass
class Download:
    """要当文件下载的响应。模块的路由函数返回它，服务端就不走 JSON。

    2026-08-31 会上王楠要的导出：「他给其他部门下单也是用文件下单」。
    所以下载通道做成通用的 —— 四个模块都要出导出，不给广告或库存单开后门。

    filename 直接进 Content-Disposition。中文文件名靠 RFC 5987 的 filename*
    传，服务端负责编码，这里原样给中文就行。
    """

    filename: str
    data: bytes
    content_type: str = ("application/vnd.openxmlformats-officedocument"
                         ".spreadsheetml.sheet")


@dataclass
class Ctx:
    module: str
    resource: str
    rest: tuple = ()                           # /api/inventory/child/B0XX -> ("B0XX",)
    query: dict = field(default_factory=dict)
    params: dict = field(default_factory=dict)
    fingerprint: str = ""
    as_of: str = ""
    body: bytes = b""                          # POST/DELETE 的原始请求体；GET 时是 b""
    _json_cache: Any = field(default=None, repr=False)

    def q(self, key: str, default: str = "") -> str:
        """取单值 query 参数。注意业务筛选用裸键，可调参数用带前缀的键。"""
        v = self.query.get(key)
        if isinstance(v, (list, tuple)):
            return v[0] if v else default
        return default if v is None else str(v)

    def q_all(self, key: str) -> list[str]:
        v = self.query.get(key)
        if isinstance(v, (list, tuple)):
            return [str(x) for x in v]
        return [] if v is None else [str(v)]

    def q_int(self, key: str, default: int) -> int:
        try:
            return int(self.q(key, str(default)))
        except (TypeError, ValueError):
            return default

    def json(self) -> dict:
        """请求体解析成 dict。不是合法 JSON、或不是对象时回空 dict，不抛。"""
        if self._json_cache is None:
            try:
                parsed = json.loads(self.body.decode("utf-8")) if self.body else {}
            except (ValueError, UnicodeDecodeError):
                parsed = {}
            self._json_cache = parsed if isinstance(parsed, dict) else {}
        return self._json_cache

    def arg(self, key: str, default: str = "") -> str:
        """query 优先，其次 JSON 请求体。

        一个取值点同时支持 GET ?k=v 和 POST {"k": "v"}，所以模块从 GET 切到 POST
        不用改每一处取值。**只有取值口兼容，语义仍然是：读用 GET，写用 POST。**
        """
        if self.query.get(key) is not None:
            return self.q(key, default)
        v = self.json().get(key)
        return default if v is None else str(v)
