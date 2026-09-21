#!/usr/bin/env python3
"""Bamboocool 运营工作台 · 统一服务（V6）

一个端口承载全部模块。零第三方依赖：stdlib http.server + sqlite3 只读。
只绑 127.0.0.1，无鉴权 —— 本机演示用；若要开隧道给外部看，先加访问控制。

路由：
  /api/meta                     壳级：基准日、模块健康、脊椎规模
  /api/modules                  模块发现结果（导航与参数面板据此生成）
  /api/agent/*                  反代到独立的 Pi Agent 服务
  /api/<模块>/<资源>[/<段>...]   模块路由，由 core/registry 自动挂载
  /<任意非 /api 路径>            交给前端路由（深链刷新可用）

启停走 start.py，不要直接跑这个文件的后台进程。
"""

from __future__ import annotations

import json
import sys
import traceback
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))          # 让 core / modules 成为可导入的包

from core import db, paths, registry, ruleset          # noqa: E402
from core.ctx import Download, Ctx                               # noqa: E402

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".webp": "image/webp",
    ".woff2": "font/woff2",
    ".map": "application/json; charset=utf-8",
}

_spine_count: int | None = None


def spine_size() -> dict:
    """脊椎规模。只数一次，失败不致命——数据包缺失时页面要能显示缺失态。"""
    global _spine_count
    if _spine_count is None:
        try:
            con = db.connect(paths.PRODUCT_DB)
            try:
                _spine_count = db.scalar(con, "select count(*) from dim_product_child") or 0
                parents = db.scalar(con, "select count(*) from dim_product_parent") or 0
            finally:
                con.close()
            return {"children": _spine_count, "parents": parents, "condition": "正常"}
        except Exception:
            _spine_count = -1
    if _spine_count < 0:
        return {"children": None, "parents": None, "condition": "缺失"}
    return {"children": _spine_count, "parents": None, "condition": "正常"}


class Handler(BaseHTTPRequestHandler):
    server_version = "Workbench/0.1"
    protocol_version = "HTTP/1.1"
    max_body = 2 * 1024 * 1024                # 请求体上限 2 MB，超过回 413

    # ---- 请求体 ----------------------------------------------------------
    def _read_body(self) -> bytes:
        """把请求体一次读干净 —— **必须无条件读，哪怕这个路由用不上它**。

        protocol_version 是 HTTP/1.1，keep-alive 开着。未读的 body 会留在 socket 里，
        被当成下一个请求的起始行解析。实测：POST /api/ads/meta 带 body 之后，
        同一连接上的下一个 GET 回
            501 Unsupported method ('{"child_asin":"B0B3LWGP36"}GET')
        并断连。浏览器 fetch、requests.Session、urllib3 连接池都会踩到。
        """
        self._body_too_large = False
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return b""
        if length <= 0:
            return b""
        if length > self.max_body:
            remaining = length                # 超限也要读干净，否则残留照样污染连接
            while remaining > 0:
                chunk = self.rfile.read(min(65536, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
            self._body_too_large = True
            return b""
        return self.rfile.read(length)

    # ---- 输出 ------------------------------------------------------------
    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _download(self, d: "Download") -> None:
        """回一个附件。中文文件名两条都给：filename 退化成 ASCII 保底，
        filename* 按 RFC 5987 传 UTF-8 —— 只给前者中文会乱码，
        只给后者老浏览器拿不到名字。"""
        import urllib.parse

        ascii_name = d.filename.encode("ascii", "replace").decode("ascii").replace("?", "_")
        quoted = urllib.parse.quote(d.filename)
        self._send(
            200,
            d.data,
            d.content_type,
            extra={"Content-Disposition":
                   f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quoted}'},
        )

    def _json(self, payload, code: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self._send(code, body, CONTENT_TYPES[".json"])

    def _fail(self, code: int, message: str, module: str = "") -> None:
        """只给人类可读的一句话。不回堆栈——旧 demo 把 traceback 直接发给浏览器了。"""
        payload = {"error": message}
        if module:
            payload["module"] = module
        self._json(payload, code)

    def log_message(self, fmt: str, *args) -> None:      # 收敛访问日志噪音
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))

    # ---- 入口 ------------------------------------------------------------
    def do_GET(self) -> None:
        self._route()

    def do_HEAD(self) -> None:
        self._route()

    def do_POST(self) -> None:
        self._route()

    def do_DELETE(self) -> None:
        self._route()

    def _route(self) -> None:
        try:
            self._body = self._read_body()            # 先读干净，再决定谁来处理
            if self._body_too_large:
                self._fail(413, "请求体过大")
                return
            parsed = urllib.parse.urlsplit(self.path)
            segments = [s for s in urllib.parse.unquote(parsed.path).split("/") if s]
            query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)

            if segments and segments[0] == "api":
                self._api(segments[1:], query)
                return
            if self.command in ("POST", "DELETE"):
                self._fail(405, "该方法只用于 /api 路径")
                return
            self._static(segments)
        except BrokenPipeError:
            pass                                          # 浏览器提前断开，不是错误
        except Exception:
            traceback.print_exc()
            try:
                self._fail(500, "服务内部错误，详情见服务端日志")
            except Exception:
                pass

    # ---- API -------------------------------------------------------------
    def _api(self, seg: list[str], query: dict) -> None:
        registry.discover()                               # 开发模式下顺带热重载

        if not seg:
            self._fail(404, "未指定接口")
            return

        if seg[0] == "meta" and len(seg) == 1:
            self._json(
                {
                    "app": "Bamboocool 运营工作台",
                    "version": "V6",
                    "as_of": paths.AS_OF,
                    "spine": spine_size(),
                    "health": registry.health(),
                }
            )
            return

        if seg[0] == "modules" and len(seg) == 1:
            self._json({"modules": [m.public() for m in registry.modules()]})
            return

        if seg[0] == "agent":
            self._proxy_agent(seg[1:], query)
            return

        mid, resource = seg[0], (seg[1] if len(seg) > 1 else "meta")
        mod = registry.get(mid)
        if mod is None:
            self._fail(404, f"没有名为 {mid} 的模块")
            return
        if mod.degraded:
            self._fail(503, f"模块「{mod.label}」当前不可用", module=mid)
            return

        fn = registry.resolve(mid, resource)
        if fn is None:
            self._fail(404, f"模块「{mod.label}」没有 {resource} 这个接口", module=mid)
            return

        values = ruleset.parse(mod.prefix, mod.params, query)
        ctx = Ctx(
            module=mid,
            resource=resource,
            rest=tuple(seg[2:]),
            query=query,
            params=values,
            fingerprint=ruleset.fingerprint(mod.prefix, values),
            as_of=paths.AS_OF,
            body=self._body,
        )
        try:
            result = fn(ctx)
            # 导出类接口回的是文件，不是 JSON。判类型而不是判资源名 ——
            # 判资源名的话每加一个导出接口都要回来改这里。
            if isinstance(result, Download):
                self._download(result)
            else:
                self._json(result)
        except Exception:
            traceback.print_exc()
            # 契约 8.4：一个模块的接口炸了只回它自己的错误，不影响其他模块
            self._fail(500, f"模块「{mod.label}」处理 {resource} 时出错", module=mid)

    def _proxy_agent(self, seg: list[str], query: dict) -> None:
        """反代到独立 Agent 服务，让浏览器只见一个 origin（契约第 9 节）。

        Agent 服务的运行与会话接口挂在它自己的 /api/agent/ 下，健康与列表挂在 /api/ 下。
        这里做一次映射，让浏览器侧的 URL 统一是 /api/agent/<资源>：
          /api/agent/run          -> {AGENT}/api/agent/run
          /api/agent/session/<id> -> {AGENT}/api/agent/session/<id>
          /api/agent/health       -> {AGENT}/api/health
          /api/agent/children     -> {AGENT}/api/children
        """
        rest = list(seg)
        # health / children 是 Agent 服务的顶层只读接口；其余能力统一挂在
        # /api/agent/*。竞品异步任务因此会从
        # /api/agent/competitor/* 原样转到同一路径，不能丢掉 agent 段。
        if rest and rest[0] not in ("health", "children"):
            rest = ["agent"] + rest
        target = paths.AGENT_ORIGIN.rstrip("/") + "/api/" + "/".join(rest)
        if query:
            target += "?" + urllib.parse.urlencode(query, doseq=True)
        payload = self._body or None                  # _route 已经读干净，不要再读 rfile
        req = urllib.request.Request(target, data=payload, method=self.command)
        for h in ("Content-Type", "Accept"):
            if self.headers.get(h):
                req.add_header(h, self.headers[h])
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                ctype = resp.headers.get("Content-Type", "application/octet-stream")
                self.send_response(resp.status)
                self.send_header("Content-Type", ctype)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                while True:                                # 逐块转发，保住 NDJSON 流式
                    chunk = resp.read(4096)
                    if not chunk:
                        break
                    self.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk))
                    self.wfile.flush()
                self.wfile.write(b"0\r\n\r\n")
        except urllib.error.HTTPError as error:
            # 上游的 400/404 等业务状态必须原样传给浏览器，不能误报成服务离线。
            body = error.read()
            self._send(
                error.code,
                body,
                error.headers.get("Content-Type", "application/json; charset=utf-8"),
            )
        except urllib.error.URLError:
            self._fail(503, "AI 助手服务当前不可用")

    # ---- 静态文件与前端路由 ---------------------------------------------
    def _static(self, segments: list[str]) -> None:
        if segments == ["favicon.ico"]:
            self._send(204, b"", "image/x-icon")
            return

        rel = "/".join(segments)
        suffix = Path(rel).suffix

        # 没有扩展名 = 前端路由，交给 index.html（深链刷新可用）。
        # 有扩展名就必须真存在，否则 404 —— 不能拿 HTML 冒充缺失的 .js，
        # 那会让浏览器报一个完全看不懂的解析错误。
        if not suffix:
            self._file(paths.WEB_ROOT / "index.html")
            return

        target = (paths.WEB_ROOT / rel).resolve()
        try:
            target.relative_to(paths.WEB_ROOT.resolve())
        except ValueError:
            self._fail(403, "路径越界")
            return
        self._file(target)

    def _file(self, path: Path) -> None:
        if not path.is_file():
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        ctype = CONTENT_TYPES.get(path.suffix, "application/octet-stream")
        self._send(200, path.read_bytes(), ctype)


def main() -> None:
    registry.discover(force=True)
    h = registry.health()
    print(f"发现模块 {h['total']} 个：可用 {h['ok']}，降级 {h['degraded'] or '无'}")
    if h["enabled_filter"]:
        print(f"仅加载：{h['enabled_filter']}")
    srv = ThreadingHTTPServer((paths.HOST, paths.PORT), Handler)
    srv.daemon_threads = True
    print(f"工作台运行在 http://{paths.HOST}:{paths.PORT}/  基准日 {paths.AS_OF}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
