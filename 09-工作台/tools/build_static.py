#!/usr/bin/env python3
"""把运行中的工作台打成一个静态快照包。

产物是一个可以整体拷走的文件夹：所有页面照常浏览，但不需要 Python 服务、
不需要 SQLite、不连 Agent。做法是把每个 GET 接口在**默认参数**下的响应
固化成 JSON 文件，前端侧用一个 shim 把 fetch('/api/...') 改指那些文件。

用法（服务必须先在跑）：
    /usr/bin/python3 tools/build_static.py            # 全量
    /usr/bin/python3 tools/build_static.py --dry-run  # 只统计不下载

**这个包做不到的事**（脚本会把它们写进包里的 README 与页内提示）：
  · 调参数面板 —— 快照只有默认参数那一份，改了数字不会重算
  · 跑 Agent —— 触发按钮全部禁用（用户明确要求不含 Agent 能力）
  · 现场生成导出 —— 改为预生成几个 xlsx 放进 exports/，按钮直接下载
不把这三件说清楚，看的人会以为是坏了。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:18820"
APP = Path(__file__).resolve().parent.parent          # 09-工作台/
WEB = APP / "web"
OUT = APP / "dist-static"

# 静态资源：整棵 web/ 拷过去，但排除这些（无用或体积大且不被引用）
SKIP_DIRS = {"__pycache__"}

# ---------------------------------------------------------------------------
# 抓取清单
#
# plain   直接抓，落 api/<module>/<resource>.json
# detail  (路由名, 取 id 的列表端点, 列表在响应里的键, id 字段名)
#         落 api/<module>/<路由名>/<id>.json
#
# **只抓 GET 读取类。** 写入与 Agent 触发类（run-* / analyze / decide / loop /
# scheme-save / *-status）一概不抓 —— 它们在静态包里没有意义，
# shim 会让这些请求回一个「静态快照不含此能力」的正常响应。
# ---------------------------------------------------------------------------
SPEC: dict[str, dict] = {
    "overview": {"plain": ["meta", "digest"], "detail": []},
    "inventory": {
        "plain": ["meta", "children"],
        "detail": [("child", "children", "rows", "child_asin")],
    },
    "preinvest": {
        "plain": ["meta", "plan"],
        "detail": [("child", "plan", "rows", "child_asin")],
    },
    "keyword": {
        "plain": ["meta", "overview", "terms", "children"],
        "detail": [
            ("term", "terms", "terms", "keyword_id"),
            ("child", "children", "rows", "child_asin"),
        ],
    },
    "competitor": {
        "plain": ["meta", "rivals"],
        "detail": [("rival", "rivals", "table", "family_asin")],
    },
    "ads": {
        "plain": ["meta", "candidates", "context", "catalog", "compare",
                  "demo-script", "gate"],
        "detail": [("object", "catalog", "rows", "ad_object_id")],
    },
    "agentcfg": {"plain": ["meta", "agents", "runs", "schemes"], "detail": []},
    "sample": {
        "plain": ["meta", "children"],
        "detail": [("child", "children", "items", "child_asin")],
    },
}

# 预生成的导出文件：(模块, 路由, 路径参数或None, POST body 或 None, 文件名)
EXPORTS = [
    ("inventory", "export-daily", "B0B3LM36WB", None,
     "库存-B0B3LM36WB-逐日销量与需求.xlsx"),
    ("preinvest", "export-child", "B0B3LM36WB", None,
     "预投-B0B3LM36WB-逐日预估与预投窗口.xlsx"),
    ("preinvest", "export-plan", None, {"buffer": 0.10, "overrides": {}},
     "预投-2026-10预投表.xlsx"),
]


def get(path: str, timeout: int = 90) -> bytes:
    req = urllib.request.Request(BASE + path, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def post(path: str, body: dict, timeout: int = 90) -> bytes:
    req = urllib.request.Request(
        BASE + path, data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def safe_name(s: str, used: set[str]) -> str:
    """id 转文件名，并保证不撞名。

    **不要指望前端能算出同一个名字。** Python 的 str.isalnum() 认中文
    （'男'.isalnum() 是 True），JS 的 [0-9A-Za-z] 不认 —— 两侧各写一份规则
    必然在某个 id 上分叉，而那种错没有症状（只是某个对象点开是 404）。
    所以这里只管生成，映射关系写进 api/_index.json 交给 shim 查表。
    """
    base = "".join(c if (c.isascii() and (c.isalnum() or c in "-_.")) else "_"
                   for c in str(s)).lstrip(".") or "obj"
    name = base
    k = 2
    while name in used:
        name = f"{base}~{k}"
        k += 1
    used.add(name)
    return name


def write_json(rel: str, raw: bytes) -> int:
    p = OUT / "api" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(raw)
    return len(raw)


def copy_web() -> int:
    """拷 web/ 整棵树。dist-static 自己在 APP 下、不在 web 下，不会递归。"""
    n = 0
    for src in WEB.rglob("*"):
        if any(part in SKIP_DIRS for part in src.parts):
            continue
        rel = src.relative_to(WEB)
        dst = OUT / rel
        if src.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            n += 1
    return n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只统计不下载")
    ap.add_argument("--limit", type=int, default=0,
                    help="每个详情端点最多抓几个（0=全抓）")
    args = ap.parse_args()

    try:
        mods_raw = get("/api/modules", timeout=20)
    except (urllib.error.URLError, TimeoutError) as e:
        sys.exit(f"连不上工作台 {BASE} —— 先启动它：/usr/bin/python3 start.py restart\n{e}")
    mods = json.loads(mods_raw)
    live = {m["id"] for m in mods.get("modules", []) if not m.get("degraded")}
    print(f"运行中的模块：{sorted(live)}")

    if not args.dry_run:
        if OUT.exists():
            shutil.rmtree(OUT)
        OUT.mkdir(parents=True)

    total = 0
    files = 0
    t0 = time.time()
    # id -> 文件名 的总索引。shim 查它，不自己算文件名（见 safe_name 的注释）。
    index: dict[str, dict[str, str]] = {}

    if not args.dry_run:
        total += write_json("modules.json", mods_raw)
        files += 1
        try:
            total += write_json("meta.json", get("/api/meta", timeout=20))
            files += 1
        except Exception as e:                                    # noqa: BLE001
            print(f"  /api/meta 抓不到：{e}")

    # ---- 逐模块 ----
    for mid, spec in SPEC.items():
        if mid not in live:
            print(f"[{mid}] 未运行或已降级，跳过")
            continue
        cache: dict[str, dict] = {}
        for res in spec["plain"]:
            try:
                raw = get(f"/api/{mid}/{res}")
            except Exception as e:                                # noqa: BLE001
                print(f"  [{mid}/{res}] 抓不到：{e}")
                continue
            try:
                cache[res] = json.loads(raw)
            except ValueError:
                cache[res] = {}
            if not args.dry_run:
                total += write_json(f"{mid}/{res}.json", raw)
            else:
                total += len(raw)
            files += 1
            print(f"  [{mid}/{res}] {len(raw)/1024:,.0f} KB")

        for route, list_res, list_key, id_field in spec["detail"]:
            src = cache.get(list_res) or {}
            rows = src.get(list_key) or []
            ids = []
            for r in rows:
                v = r.get(id_field) if isinstance(r, dict) else None
                if v:
                    ids.append(str(v))
            # 去重保序
            seen, uniq = set(), []
            for v in ids:
                if v not in seen:
                    seen.add(v)
                    uniq.append(v)
            if args.limit:
                uniq = uniq[:args.limit]
            if not uniq:
                print(f"  [{mid}/{route}] 列表里没找到 {id_field}，跳过")
                continue

            sub = 0
            bad = 0
            used: set[str] = set()
            imap: dict[str, str] = {}
            for k, oid in enumerate(uniq, 1):
                try:
                    raw = get(f"/api/{mid}/{route}/{urllib.parse.quote(oid, safe='')}")
                except Exception:                                 # noqa: BLE001
                    bad += 1
                    continue
                fn = safe_name(oid, used)
                imap[oid] = f"{fn}.json"
                if not args.dry_run:
                    sub += write_json(f"{mid}/{route}/{fn}.json", raw)
                else:
                    sub += len(raw)
                files += 1
                if k % 50 == 0 or k == len(uniq):
                    print(f"  [{mid}/{route}] {k}/{len(uniq)}  累计 {sub/1048576:,.1f} MB"
                          + (f"  失败 {bad}" if bad else ""))
            index[f"{mid}/{route}"] = imap
            total += sub

    if not args.dry_run:
        (OUT / "api" / "_index.json").write_text(
            json.dumps(index, ensure_ascii=False), encoding="utf-8")
        n_ids = sum(len(v) for v in index.values())
        print(f"  索引 api/_index.json：{len(index)} 个端点 / {n_ids} 个对象")

    print(f"\nAPI 快照：{files} 个文件 · {total/1048576:,.1f} MB · {time.time()-t0:,.0f} 秒")

    if args.dry_run:
        print("（dry-run，未写盘）")
        return

    # ---- 预生成导出 ----
    exp_dir = OUT / "exports"
    exp_dir.mkdir(exist_ok=True)
    manifest_exports = []
    for mid, route, arg, body, fname in EXPORTS:
        if mid not in live:
            continue
        path = f"/api/{mid}/{route}" + (f"/{arg}" if arg else "")
        try:
            raw = post(path, body) if body is not None else get(path)
        except Exception as e:                                     # noqa: BLE001
            print(f"  导出 {fname} 失败：{e}")
            continue
        (exp_dir / fname).write_bytes(raw)
        manifest_exports.append({"module": mid, "route": route, "arg": arg,
                                 "file": f"exports/{fname}",
                                 "size": len(raw)})
        print(f"  导出 {fname}  {len(raw)/1024:,.0f} KB")

    (OUT / "api" / "static-exports.json").write_text(
        json.dumps(manifest_exports, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---- 拷前端 ----
    n = copy_web()
    print(f"前端静态资源：{n} 个文件")

    # ---- 注入 shim 并改 index.html ----
    shim = Path(__file__).resolve().parent / "static-shim.js"

    # 打包前先给 shim 做一次语法检查。它是整个包的命门：一旦有语法错误，
    # fetch 不会被劫持、页面所有取数落到静态服务上，报错还是一句
    # "Invalid or unexpected token" —— 跟真实原因（某处注释误闭合）
    # 毫无关系。踩过一次：注释里写了 run- 加星号加斜杠，把块注释提前关掉了。
    if shutil.which("node"):
        import subprocess
        r = subprocess.run(["node", "--check", str(shim)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit(f"static-shim.js 语法错误，打包中止：\n{r.stderr.strip()}")
        print("static-shim.js 语法检查通过")
    else:
        print("没有 node，跳过 shim 语法检查 —— 建议装上，这一步挡的是整个包失效")

    shutil.copy2(shim, OUT / "static-shim.js")
    idx = OUT / "index.html"
    html = idx.read_text(encoding="utf-8")
    if "static-shim.js" not in html:
        # 必须排在所有脚本之前 —— shell.js 一起来就 fetch。
        #
        # **src 用绝对路径 /static-shim.js，不能用 ./static-shim.js。**
        # 这个前端的 URL 是 /preinvest/pre-detail/B0B3LM36WB 这种深链，
        # 相对路径会解析成 /preinvest/pre-detail/static-shim.js —— 不存在，
        # 被 SPA 回退成 index.html，浏览器把 HTML 当 JS 解析，
        # 报一句跟真实原因毫无关系的 "Unexpected token '<'"。
        # index.html 里原有的 /tune.js /tokens.css 也都是绝对路径，照它。
        html = html.replace("</head>", '  <script src="/static-shim.js"></script>\n</head>')
        idx.write_text(html, encoding="utf-8")
        print("index.html 已注入 static-shim.js")
    else:
        print("index.html 已有 shim，跳过")

    # ---- 包内自带一个会做 SPA 回退的小服务 ----
    # 不能用 python -m http.server：这个项目是「URL 即状态」（契约 8.8），
    # /preinvest/pre-detail/B0B3LM36WB 这种深链在磁盘上没有对应文件，
    # http.server 会直接 404，于是刷新页面和分享链接全坏 —— 而深链可直达
    # 本来是门禁 G16 守着的一条。真服务端 server.py 是回落到 index.html 的，
    # 这里照做。
    (OUT / "serve.py").write_text(SERVE_PY, encoding="utf-8")

    # ---- 双击就能看 ----
    # file:// 下 fetch 本地文件会被 CORS 挡，所以必须走 http。
    opener = OUT / "打开工作台.command"
    opener.write_text(
        "#!/bin/bash\n"
        '# 双击这个文件即可查看。静态包必须走 http 打开 ——\n'
        '# file:// 协议下浏览器会以跨域为由拒绝读取 api/ 下的 JSON。\n'
        'cd "$(dirname "$0")" || exit 1\n'
        'echo "工作台静态快照 → http://127.0.0.1:18899/"\n'
        'echo "（关掉这个终端窗口就停止）"\n'
        'sleep 1 && open "http://127.0.0.1:18899/" &\n'
        '/usr/bin/python3 serve.py\n',
        encoding="utf-8")
    opener.chmod(0o755)

    (OUT / "README.md").write_text(README, encoding="utf-8")

    size = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file())
    cnt = sum(1 for f in OUT.rglob("*") if f.is_file())
    print(f"\n包总大小：{size/1048576:,.1f} MB · {cnt} 个文件")
    print(f"输出：{OUT}")
    print(f"查看：双击 {opener.name}，或在包目录下跑 /usr/bin/python3 serve.py")


SERVE_PY = '''#!/usr/bin/env python3
"""静态快照的本地查看服务。只绑回环，零依赖。

比 `python -m http.server` 多做一件事：**磁盘上不存在的路径回落到 index.html**。
这个前端把状态放在 URL 路径里（/preinvest/pre-detail/B0B3LM36WB），
那种路径在磁盘上没有对应文件；不回落的话刷新页面和分享链接都会 404。
"""

from __future__ import annotations

import os
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

HOST = "127.0.0.1"
PORT = int(os.environ.get("SNAPSHOT_PORT", "18899"))
ROOT = os.path.dirname(os.path.abspath(__file__))


class Handler(SimpleHTTPRequestHandler):
    def send_head(self):
        path = self.translate_path(self.path)
        if os.path.isdir(path) or os.path.exists(path):
            return super().send_head()
        # /api/ 与静态资源后缀：缺了就老实回 404。
        # 回退成 index.html 的话，取数那侧会拿到一段 HTML 去 res.json()，
        # 报错跟真实原因毫无关系（"Unexpected token '<'"），最难查的那种。
        p = self.path.split("?")[0]
        if p.startswith("/api/") or p.endswith((".js", ".css", ".json", ".png",
                                                ".jpg", ".svg", ".xlsx", ".map")):
            self.send_error(404, "File not found")
            return None
        # 其余当作前端路由（URL 即状态），回落到 index.html
        self.path = "/index.html"
        return super().send_head()

    def end_headers(self):
        # 快照是给人当场看的，别让浏览器缓存住旧的一次打包
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):        # 静音，只留报错
        if str(args[1] if len(args) > 1 else "").startswith(("4", "5")):
            sys.stderr.write("%s %s\\n" % (self.address_string(), fmt % args))


def main() -> None:
    handler = partial(Handler, directory=ROOT)
    with ThreadingHTTPServer((HOST, PORT), handler) as srv:
        print(f"静态快照 → http://{HOST}:{PORT}/   （Ctrl-C 停止）")
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            print("\\n已停止")


if __name__ == "__main__":
    main()
'''


README = """# Bamboocool 运营工作台 · 静态快照

这是工作台前端的**离线快照**：所有页面照常浏览，不需要 Python 服务、
不需要数据库、不连 Agent。

## 怎么打开

双击 `打开工作台.command`，浏览器会自动开到 http://127.0.0.1:18899/

或者在这个目录下手动跑：

```
/usr/bin/python3 serve.py
```

两件事说明一下：

- **不能直接双击 index.html。** `file://` 协议下浏览器会以跨域为由拒绝读取
  `api/` 下的 JSON，页面会是空的。这不是包坏了。
- **也不要用 `python -m http.server`。** 这个前端把状态放在 URL 路径里
  （比如 `/preinvest/pre-detail/B0B3LM36WB`），那种路径磁盘上没有对应文件，
  `http.server` 会直接 404，刷新和分享链接都会坏。包里的 `serve.py`
  多做了一件事：找不到的路径回落到 index.html。

## 这个包能看什么

八个模块的全部页面与全部对象，数据是打包那一刻的样子：

- 总览、产品与库存（342 个子 ASIN）、面料预投（342 个子 ASIN）
- 关键词分析（200 个词）、竞品分析（20 个族）、广告分析（54 个对象）
- Agent 配置（含运行记录）、接入范例

图表、逐日柱状图、点击看当天依据、深链（把地址栏 URL 发给别人能直达同一页）
都能用。

## 这个包做不到的三件事

1. **参数面板改了不会重算。** 快照只固化了默认参数下那一份数据。
   面板仍然打得开（那本身是要展示的能力：门槛可见可调），但改了数字页面不动。
2. **Agent 不在包内。** 所有「运行/重跑/分析」按钮点了会明确回一句
   「静态快照不含 Agent 能力」，不是坏了。
3. **导出不是现场生成的。** `exports/` 目录里预生成了几份示例 xlsx，
   页面上的导出按钮会给这几份。别的对象的导出需要连着服务的那一版。

## 怎么重新打包

在工作台目录下（服务要先在跑）：

```
/usr/bin/python3 tools/build_static.py            # 全量
/usr/bin/python3 tools/build_static.py --dry-run  # 只统计不写盘
/usr/bin/python3 tools/build_static.py --limit 20 # 每类对象只抓 20 个（小包）
```
"""


if __name__ == "__main__":
    main()
