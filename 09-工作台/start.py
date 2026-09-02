#!/usr/bin/env python3
"""工作台服务启停。

必须用 /usr/bin/python3（本机唯一装了数据链要用的 lxml 的解释器；服务端本身零依赖）。

用法：/usr/bin/python3 start.py {start|stop|restart|status}

两个踩过的坑，别改回去：
1. 双 fork + os.setsid()。不脱离进程组的话，KiroCrew 清理进程组时会把服务一起 SIGTERM 掉。
2. pkill 必须匹配 server.py 的**路径**，不能用 sys.executable —— 运行中的进程显示的是
   解析后的框架路径，匹配不上会杀不掉旧进程还谎报成功。
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
SERVER = HERE / "server.py"
PIDFILE = HERE / ".server.pid"
LOGFILE = HERE / "server.log"
PYTHON = "/usr/bin/python3"

PORT = int(os.environ.get("WORKBENCH_PORT", "18820"))
BASE = f"http://127.0.0.1:{PORT}"


def port_busy() -> bool:
    with socket.socket() as s:
        s.settimeout(0.4)
        return s.connect_ex(("127.0.0.1", PORT)) == 0


def probe() -> dict | None:
    try:
        with urllib.request.urlopen(f"{BASE}/api/meta", timeout=4) as r:
            return json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


def running_pids() -> list[int]:
    out = subprocess.run(
        ["pgrep", "-f", str(SERVER)], capture_output=True, text=True
    ).stdout
    me = os.getpid()
    return [int(x) for x in out.split() if x.isdigit() and int(x) != me]


def spawn() -> None:
    """双 fork 脱离进程组，stdout/stderr 落 server.log。"""
    if os.fork() != 0:
        return
    os.setsid()
    if os.fork() != 0:
        os._exit(0)
    with open(LOGFILE, "ab", buffering=0) as log:
        os.dup2(log.fileno(), 1)
        os.dup2(log.fileno(), 2)
    devnull = os.open(os.devnull, os.O_RDONLY)
    os.dup2(devnull, 0)
    os.chdir(str(HERE))
    os.execv(PYTHON, [PYTHON, str(SERVER)])


def do_stop() -> None:
    pids = running_pids()
    if not pids:
        print("没有在跑的工作台进程")
    else:
        subprocess.run(["pkill", "-f", str(SERVER)])
        for _ in range(20):
            if not running_pids():
                break
            time.sleep(0.2)
        left = running_pids()
        print(f"已停止 {pids}" if not left else f"仍有残留进程：{left}")
    PIDFILE.unlink(missing_ok=True)


def do_start() -> int:
    if running_pids():
        print(f"已在运行 pid {running_pids()} -> {BASE}/")
        return 0
    if port_busy():
        print(f"端口 {PORT} 被其他进程占用，先释放再启动", file=sys.stderr)
        return 1
    spawn()
    for _ in range(50):
        time.sleep(0.2)
        meta = probe()
        if meta:
            h = meta.get("health", {})
            print(f"已启动 -> {BASE}/")
            print(f"  基准日 {meta.get('as_of')}  模块可用 {h.get('ok')}  降级 {h.get('degraded') or '无'}")
            return 0
    print(f"启动超时，看 {LOGFILE}", file=sys.stderr)
    return 1


def do_status() -> int:
    pids = running_pids()
    meta = probe()
    if not pids and not meta:
        print("未运行")
        return 1
    print(f"pid {pids or '未知'} -> {BASE}/")
    if meta:
        h = meta.get("health", {})
        print(f"  基准日 {meta.get('as_of')}  脊椎 {meta.get('spine')}")
        print(f"  模块可用 {h.get('ok')}  降级 {h.get('degraded') or '无'}  dev={h.get('dev')}")
    else:
        print("  进程在但 /api/meta 无响应")
    return 0


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "start":
        return do_start()
    if cmd == "stop":
        do_stop()
        return 0
    if cmd == "restart":
        do_stop()
        time.sleep(0.4)
        return do_start()
    if cmd == "status":
        return do_status()
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
