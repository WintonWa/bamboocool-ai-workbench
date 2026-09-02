#!/usr/bin/env /usr/bin/python3
"""在独立端口起一个实例，供验证用，不碰 18820 那个共享进程。

为什么不用 start.py：它的 PIDFILE 是写死的单文件，看到 18820 的 pid
就判定「已在运行」，第二个实例起不来。

spawn 的写法照抄 start.py：KiroCrew 在命令结束时会清理整个进程组，
不双 fork + setsid 脱离会话，服务会被 SIGTERM 掉。
第一版我自己写的用 execve 传 env、父进程还 waitpid，起不来，
所以这版严格对齐 start.py：env 先写进 os.environ 让子进程继承，
父进程 fork 完直接返回，日志在孙进程里打开。

用法：
    ADS_PORT=18821 /usr/bin/python3 tests/start_ads_only.py start
    ADS_PORT=18821 /usr/bin/python3 tests/start_ads_only.py stop
"""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
SERVER = HERE / "server.py"
PYTHON = "/usr/bin/python3"
PORT = os.environ.get("ADS_PORT", "18821")
BASE = f"http://127.0.0.1:{PORT}"
LOGFILE = HERE / f"server-{PORT}.log"


def port_busy() -> bool:
    with socket.socket() as s:
        s.settimeout(0.4)
        return s.connect_ex(("127.0.0.1", int(PORT))) == 0


def spawn() -> None:
    # 环境先写进 os.environ，走 execv 整份继承（execve 传 dict 那版起不来）
    os.environ["WORKBENCH_PORT"] = PORT
    os.environ["WORKBENCH_MODULES"] = os.environ.get("ADS_ONLY", "")
    os.environ["WORKBENCH_DEV"] = "1"
    if os.fork() != 0:
        return                              # 父进程立刻返回，不 waitpid
    os.setsid()                             # 脱离会话，躲开进程组清理
    if os.fork() != 0:
        os._exit(0)                         # 中间层退出，孙进程被 init 收养
    with open(LOGFILE, "ab", buffering=0) as log:
        os.dup2(log.fileno(), 1)
        os.dup2(log.fileno(), 2)
    devnull = os.open(os.devnull, os.O_RDONLY)
    os.dup2(devnull, 0)
    os.chdir(str(HERE))
    os.execv(PYTHON, [PYTHON, str(SERVER)])


def do_start() -> int:
    if port_busy():
        print(f"端口 {PORT} 已被占用")
        return 1
    spawn()
    for _ in range(50):
        time.sleep(0.2)
        try:
            with urllib.request.urlopen(f"{BASE}/api/meta", timeout=3) as r:
                json.loads(r.read().decode("utf-8"))
            break
        except Exception:                                   # noqa: BLE001
            continue
    else:
        print(f"起不来，看 {LOGFILE.name}")
        return 1
    with urllib.request.urlopen(f"{BASE}/api/modules", timeout=4) as r:
        ms = json.loads(r.read().decode("utf-8"))["modules"]
    ids = ", ".join(m["id"] + ("（降级）" if m.get("degraded") else "")
                    for m in ms)
    print(f"已起 {BASE}/  加载模块：{ids or '无'}")
    return 0


def do_stop() -> int:
    out = subprocess.run(["lsof", "-nP", f"-iTCP:{PORT}", "-sTCP:LISTEN",
                          "-t"], capture_output=True, text=True, check=False)
    pids = [p for p in out.stdout.split() if p.strip()]
    for p in pids:
        subprocess.run(["kill", p], check=False)
    print(f"已停 {pids}" if pids else "没有在监听的进程")
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "start"
    sys.exit({"start": do_start, "stop": do_stop}.get(cmd, do_start)())
