#!/usr/bin/env python3
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
            sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))


def main() -> None:
    handler = partial(Handler, directory=ROOT)
    with ThreadingHTTPServer((HOST, PORT), handler) as srv:
        print(f"静态快照 → http://{HOST}:{PORT}/   （Ctrl-C 停止）")
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            print("\n已停止")


if __name__ == "__main__":
    main()
