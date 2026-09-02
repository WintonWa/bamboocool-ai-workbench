#!/usr/bin/env python3
"""并发回归探针：确认多线程读同一个数据包不会偶发 500。

背景（真踩过）：服务是 ThreadingHTTPServer，前端一个页面会并行发好几个请求
（侧栏取 meta、正文取对象详情，走 Promise.all）。第一版模块用
`@lru_cache` 缓存单个 SQLite 连接，两个线程同时 execute 同一连接，
偶发 `sqlite3.DatabaseError: database disk image is malformed` ——
文件其实没坏（quick_check 是 ok 的），是连接不能并发用。
`check_same_thread=False` 只解除检查，不做串行化。

修法是 core.db.pool() 按线程给连接。这个探针守着它别回退。

用法：/usr/bin/python3 tests/probe_concurrency.py
"""

from __future__ import annotations

import concurrent.futures as cf
import json
import sys
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import paths  # noqa: E402

BASE = f"http://127.0.0.1:{paths.PORT}"
ROUNDS = 30
WORKERS = 12


def get(path: str):
    try:
        with urllib.request.urlopen(f"{BASE}{path}", timeout=20) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception as e:  # 网络/超时
        return type(e).__name__


def modules() -> list[dict]:
    with urllib.request.urlopen(f"{BASE}/api/modules", timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))["modules"]


def main() -> int:
    try:
        mods = [m for m in modules() if not m["degraded"]]
    except Exception as exc:
        print(f"服务没起来：{exc}\n先跑 /usr/bin/python3 start.py start", file=sys.stderr)
        return 2

    # 每个可用模块都压：并发问题是共享层的，不是某一个模块的
    urls: list[str] = []
    for m in mods:
        urls += [f"/api/{m['id']}/meta"] * ROUNDS
    urls += [f"/api/sample/child/B0GKFMB38P"] * ROUNDS
    urls += [f"/api/sample/children"] * ROUNDS

    with cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        codes = list(ex.map(get, urls))

    dist = dict(Counter(codes))
    bad = {k: v for k, v in dist.items() if k != 200}
    print(f"压了 {len(urls)} 个请求，并发 {WORKERS}")
    print(f"状态码分布：{dist}")
    if bad:
        print(f"\n❌ 出现非 200：{bad}")
        print("   若是 500，看 server.log 的 traceback；"
              "若是 `database disk image is malformed`，说明连接又被跨线程共用了")
        return 1
    print("\n✅ 全部 200，无跨线程连接竞争")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
