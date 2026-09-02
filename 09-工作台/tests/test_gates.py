#!/usr/bin/env python3
"""接入契约门禁 G1–G24。

用法：先 start.py start，然后 /usr/bin/python3 tests/test_gates.py

契约第 12 节说"逐条机械检查，任一条不过就退回"。这个文件就是那个检查。
G10（每个板块能说出它回答哪个经营问题）与 G11（视觉验证）无法机械化，
这里只打印成待人工项 —— 前两个模块的多个真 bug 都是看屏幕才发现的，测试当时全绿。

G19–G24 是视觉基准（00-通用方法与规范/06-视觉基准要则.md）的机械部分，
按模块逐个查，新模块加进来自动纳入，不需要各写一份。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import paths  # noqa: E402

BASE = f"http://127.0.0.1:{paths.PORT}"
MODULES_DIR = ROOT / "modules"
WEB_MODULES = ROOT / "web" / "modules"

# 绝不允许出现在返回给前端的载荷里的内部叫法
LEAK_WORDS = [
    "value_origin", "source_status", "source_ref", "provenance",
    "can_absorb", "cannot_absorb", "report_month_total",
    "complete", "partial", "missing",
]
NATURES = {"真实", "推导", "模拟", "混合"}
CONDITIONS = {"正常", "过期", "缺失", "待确认", "失败", "加载中", "空结果"}

results: list[tuple[str, bool, str]] = []


def gate(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))


def get(path: str):
    with urllib.request.urlopen(f"{BASE}{path}", timeout=20) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


def status_of(path: str) -> int:
    try:
        with urllib.request.urlopen(f"{BASE}{path}", timeout=20) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def raw(path: str) -> str:
    with urllib.request.urlopen(f"{BASE}{path}", timeout=20) as r:
        return r.read().decode("utf-8", "replace")


def module_ids() -> list[str]:
    _, payload = get("/api/modules")
    return [m["id"] for m in payload["modules"]], payload["modules"]


# ---- G1 无自建外壳 --------------------------------------------------------
def g1():
    banned = {"index.html", "app.css", "server.py", "start.py"}
    bad = []
    for d in MODULES_DIR.iterdir():
        if not d.is_dir() or d.name.startswith((".", "_")):
            continue
        for f in d.rglob("*"):
            if f.name in banned:
                bad.append(str(f.relative_to(ROOT)))
    gate("G1 无自建外壳", not bad, "；".join(bad))


# ---- G2 CSS 作用域 / G3 无新增 token -------------------------------------
_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_BARE_ELEMENT = re.compile(
    r"(?:^|[},])\s*(html|body|section|table|thead|tbody|tr|th|td|div|span|p|h[1-6]|a|button|input|ul|li|dl|dt|dd)\b"
    r"[^{}]*\{",
    re.M,
)


def g2_g3():
    bad_scope, bad_id, bad_token, bad_bare = [], [], [], []
    for f in sorted(WEB_MODULES.glob("*.css")):
        src = _COMMENT.sub("", f.read_text(encoding="utf-8"))
        mid = f.stem
        for rule in re.finditer(r"([^{}]+)\{", src):
            sel = rule.group(1).strip()
            if not sel or sel.startswith("@") or sel.startswith("%"):
                continue
            if "#" in sel:
                bad_id.append(f"{f.name}: {sel[:60]}")
            if f'[data-module="{mid}"]' not in sel:
                bad_scope.append(f"{f.name}: {sel[:60]}")
        if _BARE_ELEMENT.search(src):
            bad_bare.append(f.name)
        if re.search(r"(^|[;{\s])--[a-z0-9-]+\s*:", src, re.M):
            bad_token.append(f.name)
    gate("G2 CSS 作用域（全部规则在 [data-module] 下）", not bad_scope, "；".join(bad_scope[:5]))
    gate("G2 CSS 无 #id 选择器", not bad_id, "；".join(bad_id[:5]))
    gate("G2 CSS 无作用域外裸元素选择器", not bad_bare, "；".join(bad_bare))
    gate("G3 模块 CSS 不新增 token", not bad_token, "；".join(bad_token))


# ---- G4 必须是 ES module 且不往全局挂东西 --------------------------------
def g4():
    # ES module 的顶层作用域天然不是全局，所以 `let host = null` 不会和任何人冲突。
    # 真正要禁的是两件事：文件根本不是 module（那顶层就是全局，旧两个 demo 就这样
    # 撞了 $ / el / S / pc / load / renderList / renderScope 七个名字），
    # 以及显式往 window / globalThis 上挂东西绕过模块边界。
    bad = []
    for f in sorted(WEB_MODULES.glob("*.js")):
        src = f.read_text(encoding="utf-8")
        if not re.search(r"^\s*export\s", src, re.M):
            bad.append(f"{f.name} 不是 ES module（没有任何 export）")
        for i, line in enumerate(src.splitlines(), 1):
            if re.search(r"\b(window|globalThis|self)\s*(\.\w+|\[[^\]]+\])\s*=", line):
                bad.append(f"{f.name}:{i} 往全局挂了东西")
    gate("G4 模块是 ES module 且不污染全局", not bad, "；".join(bad[:5]))


# ---- G18 筛选项声明了中文标签 --------------------------------------------
def _filters_block(src: str) -> str:
    """取出 export const filters = [ ... ] 这一段。按方括号配平找结尾，
    不用正则贪婪匹配 —— 数组里有嵌套的 options 数组。"""
    m = re.search(r"export\s+const\s+filters\s*=\s*\[", src)
    if not m:
        return ""
    i = m.end() - 1
    depth = 0
    for j in range(i, len(src)):
        if src[j] == "[":
            depth += 1
        elif src[j] == "]":
            depth -= 1
            if depth == 0:
                return src[i : j + 1]
    return src[i:]


def g18(mods):
    # 外壳的 chip 拿不到声明就退化成写 query 键名，那是内部叫法上屏。
    # 判据是"每个用到的筛选键都有 label"，不是"key 和 label 必须写在同一行" ——
    # 第一版正则要求两者相邻，把 { key:"domain", kind:"select", label:"变化类型" }
    # 这种完全合规的多行写法误报成缺 label。
    bad = []
    for f in sorted(WEB_MODULES.glob("*.js")):
        src = f.read_text(encoding="utf-8")
        block = _filters_block(src)
        declared = set()
        if block:
            # 按 key: "x" 切段，每段内必须出现 label:
            parts = re.split(r"""key\s*:\s*["'](\w+)["']""", block)
            # parts = [前缀, key1, 段1, key2, 段2, ...]
            for k, seg in zip(parts[1::2], parts[2::2]):
                if re.search(r"\blabel\s*:", seg):
                    declared.add(k)
        used = set(re.findall(r"""setFilters\(\s*\{\s*(\w+)\s*:""", src))
        for k in sorted(used - declared):
            bad.append(f"{f.name}: 筛选 {k} 未声明 label")
    gate("G18 筛选项都声明了中文标签", not bad, "；".join(bad[:5]))


# ---- G5 路由前缀 ---------------------------------------------------------
def g5(mods):
    bad = []
    for m in mods:
        if m["degraded"]:
            continue
        if status_of(f"/api/{m['id']}/meta") != 200:
            bad.append(f"{m['id']}/meta 不可达")
    # 无前缀的裸路径不该命中模块
    if status_of("/api/children") == 200:
        bad.append("/api/children 未加模块前缀却可达")
    gate("G5 接口全部在 /api/<模块>/ 下", not bad, "；".join(bad))


# ---- G6 参数前缀与夹紧 ---------------------------------------------------
def g6(mods):
    bad = []
    for m in mods:
        if m["degraded"]:
            continue
        prefix = m.get("prefix")
        for p in m.get("params", []):
            if not p["key"].startswith(f"{prefix}."):
                bad.append(f"{m['id']}: {p['key']} 缺前缀")
            if p["kind"] == "num" and ("lo" not in p or "hi" not in p or "step" not in p):
                bad.append(f"{m['id']}: {p['key']} 未声明 lo/hi/step")
    # 夹紧：给一个远超上限的值，返回的展示条数不得超过上限
    _, payload = get("/api/sample/children?smp.page_size=99999")
    if payload["shown"] > 342:
        bad.append(f"page_size 越界未夹紧：shown={payload['shown']}")
    _, low = get("/api/sample/children?smp.page_size=1")
    if low["shown"] < 10 and low["total"] >= 10:
        bad.append(f"page_size 低于下限未夹紧：shown={low['shown']}")
    gate("G6 参数带前缀且越界被夹紧", not bad, "；".join(bad))


# ---- G7 不重建产品维度 ---------------------------------------------------
def g7():
    bad = []
    for d in MODULES_DIR.iterdir():
        if not d.is_dir() or d.name.startswith((".", "_")):
            continue
        for dbf in d.rglob("*.sqlite"):
            con = sqlite3.connect(f"file:{dbf}?mode=ro", uri=True)
            try:
                names = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
            finally:
                con.close()
            for t in ("dim_product_child", "dim_product_parent"):
                if t in names:
                    bad.append(f"{dbf.name} 重建了 {t}")
    gate("G7 模块自有库未重建产品维度", not bad, "；".join(bad))


# ---- G8 脊椎命中 ---------------------------------------------------------
def g8():
    con = sqlite3.connect(f"file:{paths.PRODUCT_DB}?mode=ro", uri=True)
    try:
        spine = {r[0] for r in con.execute("select child_asin from dim_product_child")}
    finally:
        con.close()
    _, payload = get("/api/sample/children?smp.page_size=342")
    keys = {i["child_asin"] for i in payload["items"]}
    off = keys - spine
    gate(
        f"G8 子体键全部命中脊椎（{len(spine)} 个）",
        not off and len(keys) == len(spine),
        f"越界 {len(off)} 个；返回 {len(keys)} / 脊椎 {len(spine)}" if (off or len(keys) != len(spine)) else "",
    )


# ---- G9 / G17 载荷不泄漏内部叫法，性质词只来自词表 -----------------------
def g9_g17():
    probes = [
        "/api/meta",
        "/api/modules",
        "/api/sample/meta",
        "/api/sample/children?smp.page_size=20",
        "/api/sample/child/B0GKFMB38P",
    ]
    leaks, bad_words = [], []
    for p in probes:
        text = raw(p)
        for w in LEAK_WORDS:
            if re.search(rf'"[^"]*{re.escape(w)}[^"]*"', text):
                # 只关心出现在会上屏的字段里；params 的 key 本身带前缀是合法的
                leaks.append(f"{p} 含 {w}")
        payload = json.loads(text)
        for v in _walk(payload, "nature"):
            if v not in NATURES:
                bad_words.append(f"{p} nature={v!r}")
        for v in _walk(payload, "condition"):
            if v not in CONDITIONS:
                bad_words.append(f"{p} condition={v!r}")
    gate("G9 API 载荷不含内部枚举与列名", not leaks, "；".join(sorted(set(leaks))[:6]))
    gate("G17 性质与状态只用词表内的词", not bad_words, "；".join(sorted(set(bad_words))[:6]))


def _walk(node, key):
    out = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k == key and isinstance(v, str):
                out.append(v)
            else:
                out.extend(_walk(v, key))
    elif isinstance(node, list):
        for v in node:
            out.extend(_walk(v, key))
    return out


# ---- G12 模块间零代码依赖 ------------------------------------------------
def g12():
    bad = []
    for d in MODULES_DIR.iterdir():
        if not d.is_dir() or d.name.startswith((".", "_")):
            continue
        for f in d.rglob("*.py"):
            for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                m = re.match(r"\s*(?:from|import)\s+(?:\.\.|modules\.)(\w+)", line)
                if m and m.group(1) != d.name:
                    bad.append(f"{f.relative_to(ROOT)}:{i} 引用了 {m.group(1)}")
    for f in sorted(WEB_MODULES.glob("*.js")):
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            m = re.search(r"""from\s+["']\./(\w+)\.js["']""", line)
            if m and m.group(1) != f.stem:
                bad.append(f"{f.name}:{i} 引用了 {m.group(1)}.js")
    gate("G12 模块之间零代码依赖", not bad, "；".join(bad[:5]))


# ---- G13 单模块可独立加载 ------------------------------------------------
def g13():
    env = dict(os.environ, WORKBENCH_MODULES="sample")
    code = (
        "import sys; sys.path.insert(0,'.');"
        "from core import registry; registry.discover(force=True);"
        "import json; print(json.dumps(registry.health()))"
    )
    out = subprocess.run(
        ["/usr/bin/python3", "-c", code], cwd=str(ROOT), env=env, capture_output=True, text=True
    )
    ok, detail = False, out.stderr.strip()[-200:]
    if out.returncode == 0:
        h = json.loads(out.stdout.strip().splitlines()[-1])
        ok = h["ok"] == ["sample"] and h["enabled_filter"] == ["sample"]
        detail = "" if ok else json.dumps(h, ensure_ascii=False)
    gate("G13 WORKBENCH_MODULES 只加载指定模块", ok, detail)


# ---- G14 故障隔离 --------------------------------------------------------
def g14():
    broken = MODULES_DIR / "gatebroken"
    broken.mkdir(exist_ok=True)
    (broken / "__init__.py").write_text("", encoding="utf-8")
    (broken / "module.py").write_text("def oops(:\n", encoding="utf-8")   # 故意语法错
    code = (
        "import sys; sys.path.insert(0,'.');"
        "from core import registry; registry.discover(force=True);"
        "import json; print(json.dumps(registry.health()))"
    )
    try:
        out = subprocess.run(
            ["/usr/bin/python3", "-c", code], cwd=str(ROOT), capture_output=True, text=True
        )
        ok, detail = False, out.stderr.strip()[-200:]
        if out.returncode == 0:
            h = json.loads(out.stdout.strip().splitlines()[-1])
            ok = "gatebroken" in h["degraded"] and "sample" in h["ok"]
            detail = "" if ok else json.dumps(h, ensure_ascii=False)
    finally:
        shutil.rmtree(broken, ignore_errors=True)
    gate("G14 坏模块被标降级且其余模块照常", ok, detail)


# ---- G19–G23 视觉基准：字号阶梯与字族 -------------------------------------
# 依据 00-通用方法与规范/06-视觉基准要则.md 第一、二、七节。
# 阶梯的档位与值都从 tokens.css 反查，不在这里抄第二份 —— 抄一份就会漂。

# tokens.css 里应有且只应有这些档位。要则第一节："不新增档位。"
# 值也一起钉住，否则有人把 --fs-value 从 22 悄悄改成 20，门禁照样全绿。
# 这八档是从设计图逐像素量出来的，不许动。
EXPECTED_LADDER = {
    "axis": 11, "anno": 12, "meta": 13, "body": 14,
    "sub": 16, "value": 22, "title": 24, "num": 30,
}

# 第九档 --fs-page（页面标题），2026-08-31 王楠批准新增 —— 设计图是单板块特写，
# 没有页面标题这一层，所以量不出来。
# 它的值不钉：由 ?tune=1 拖定，钉了就会跟调参器打架。
# 钉的是它存在的理由：必须严格大于板块标题，否则页面标题比它包含的板块标题还小，
# 层级读反 —— 那正是加这一档要解决的问题。
TUNABLE_STEPS = {"page": ("title", "必须大于板块标题")}

# 列对齐声明的回归下限 —— 不是拍出来的阈值。
# 每个模块迁移前有 N 处靠等宽字体让数字列对齐；换成比例字体后，
# 必须至少还有 N 处显式 font-variant-numeric: tabular-nums，否则那些列就散了。
# N 是 2026-08-31 迁移时点数出来的等宽站点数。
TABULAR_FLOOR = {"ads": 17, "competitor": 4, "keyword": 8, "sample": 0, "inventory": 10}


def _strip_css_comments(text: str) -> str:
    """剥注释。要则第七节：注释里会写"原来是 font-size:17px"，那是文档不是规则。"""
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def _module_web_files(mid: str, suffix: str) -> list[Path]:
    """模块前端文件：<id>.<suffix> 加上 <id>/ 子目录下的同类文件。"""
    out = []
    top = WEB_MODULES / f"{mid}.{suffix}"
    if top.exists():
        out.append(top)
    sub = WEB_MODULES / mid
    if sub.is_dir():
        out.extend(sorted(sub.glob(f"*.{suffix}")))
    return out


def _ladder_from_tokens() -> tuple[dict, str]:
    tok = (ROOT / "web" / "tokens.css").read_text(encoding="utf-8")
    body = _strip_css_comments(tok)
    found = {m[1]: int(m[2]) for m in re.finditer(r"--fs-([a-z]+):\s*(\d+)px", body)}
    return found, tok


def g19_g23(mods):
    found, _ = _ladder_from_tokens()
    # 和 g5/g18 一致：mods 是模块字典列表，这里只要 id
    ids = [m["id"] for m in mods]

    # G19 阶梯本身：量出来的八档值不许漂，可调的第九档只查它的层级约束
    known = set(EXPECTED_LADDER) | set(TUNABLE_STEPS)
    extra = {k: v for k, v in found.items() if k not in known}
    missing = [k for k in known if k not in found]
    drift = {k: (found[k], EXPECTED_LADDER[k]) for k in EXPECTED_LADDER
             if k in found and found[k] != EXPECTED_LADDER[k]}
    broken = []
    for step, (against, why) in TUNABLE_STEPS.items():
        if step in found and against in found and not found[step] > found[against]:
            broken.append(f"--fs-{step}={found[step]}px {why}（--fs-{against}={found[against]}px）")
    d = []
    if extra:
        d.append("多出档位 " + " ".join(f"--fs-{k}={v}px" for k, v in extra.items()))
    if missing:
        d.append("缺档位 " + " ".join(missing))
    if drift:
        d.append("值被改 " + " ".join(f"--fs-{k} {a}!={b}" for k, (a, b) in drift.items()))
    if broken:
        d.append("层级反了 " + "; ".join(broken))
    gate("G19 阶梯档位齐全、量出的值未漂、可调档不反层级",
         not (extra or missing or drift or broken),
         "; ".join(d) or f"{len(found)} 档（钉住 {len(EXPECTED_LADDER)} + 可调 "
                          f"{len(TUNABLE_STEPS)}），--fs-page={found.get('page')}px > "
                          f"--fs-title={found.get('title')}px")

    ladder_names = known
    lit_bad, off_bad, inline_bad, mono_bad, tab_bad = [], [], [], [], []

    for mid in ids:
        css_files = _module_web_files(mid, "css")
        css = "".join(_strip_css_comments(p.read_text(encoding="utf-8")) for p in css_files)

        # G20 CSS 无字号字面量
        lits = re.findall(r"font-size:\s*[\d.]+px", css)
        if lits:
            lit_bad.append(f"{mid} {len(lits)} 处（{' '.join(sorted(set(lits))[:4])}）")

        # G21 只用这八档，不出现档外变量名
        used = {m[1] for m in re.finditer(r"font-size:\s*var\(--fs-([a-z]+)\)", css)}
        off = used - ladder_names
        if off:
            off_bad.append(f"{mid} " + " ".join(sorted(off)))

        # G22 不用等宽 + 列对齐声明不低于下限
        mono = len(re.findall(r"var\(--mono\)|monospace|Menlo|Consolas|Courier", css))
        if mono:
            mono_bad.append(f"{mid} {mono} 处")
        tab = len(re.findall(r"font-variant-numeric:\s*tabular-nums", css))
        floor = TABULAR_FLOOR.get(mid, 0)
        if tab < floor:
            tab_bad.append(f"{mid} {tab}<{floor}")

        # G23 JS 无内联字号 —— 内联的在 CSS 层扫不到，必须单独查
        for p in _module_web_files(mid, "js"):
            src = re.sub(r"/\*.*?\*/", "", p.read_text(encoding="utf-8"), flags=re.S)
            src = re.sub(r"^\s*//.*$", "", src, flags=re.M)
            hits = re.findall(r"font-size:\s*[\d.]+px|fontSize:\s*\d+", src)
            if hits:
                inline_bad.append(f"{p.name} {len(hits)} 处")

    gate("G20 模块 CSS 无字号字面量", not lit_bad, "; ".join(lit_bad) or f"{len(ids)} 个模块全干净")
    gate("G21 只用阶梯档位", not off_bad, "; ".join(off_bad) or "无档外档位")
    gate("G22 不用等宽字族且列对齐未丢", not (mono_bad or tab_bad),
         "; ".join(mono_bad + tab_bad) or "等宽 0 处，列对齐声明均达下限")
    gate("G23 JS 无内联字号", not inline_bad, "; ".join(inline_bad) or "前端 JS 无内联字号")

    # G24 canvas 侧。要则第七节："没有检查对象的门禁比没有门禁更糟。"
    # 这四个模块目前一张图都没有，照抄 inventory 那两条会打出"0 项全在档 ✓"的假绿。
    # 所以先探有没有图表代码：没有就报不适用，有了自动开始查。
    tok_sans = re.search(r"--sans:\s*([^;]+);", (ROOT / "web" / "tokens.css").read_text(encoding="utf-8"))
    sans_first = tok_sans.group(1).split(",")[0].strip() if tok_sans else ""
    charted, chart_bad, no_chart = [], [], []
    for mid in ids:
        js = [(p, re.sub(r"/\*.*?\*/", "", p.read_text(encoding="utf-8"), flags=re.S))
              for p in _module_web_files(mid, "js")]
        # 图表证据只认 echarts 与 canvas 取上下文。
        # 曾经把 createElementNS 也算进来 —— 结果 Agent 配置页那个 SVG 头像
        # 被报成"有图表的模块"。判据不准的门禁迟早被人不信，宁可窄一点。
        has_chart = [p for p, s in js if re.search(r"echarts|getContext\(", s)]
        if not has_chart:
            no_chart.append(mid)
            continue
        charted.append(mid)
        for p, s in js:
            # 字体栈必须与 --sans 首项一致：两处重复，只改一边页面与图表就是两种字形
            for m in re.finditer(r"fontFamily:\s*['\"]([^'\"]+)['\"]|const FONT\s*=\s*'([^']+)'", s):
                stack = (m.group(1) or m.group(2)).split(",")[0].strip()
                if stack != sans_first:
                    chart_bad.append(f"{p.name} 字体栈 {stack}!={sans_first}")
            # 字号镜像必须全落在档上（CSS 变量进不了 canvas，所以那边重复了一份）
            # 用 tokens.css 里实际的值比，包含可调的 --fs-page，不另抄一份常量
            for m in re.finditer(r"fontSize:\s*(\d+)", s):
                if int(m.group(1)) not in set(found.values()):
                    chart_bad.append(f"{p.name} 档外字号 {m.group(1)}")
    gate("G24 图表侧字体栈与字号镜像", not chart_bad,
         "; ".join(chart_bad) if chart_bad else
         (f"有图表的模块 {' '.join(charted)} 全对；无图表故不适用：{' '.join(no_chart)}"
          if charted else f"本轮无一个模块有图表代码，本条无检查对象（不适用）：{' '.join(no_chart)}"))


# ---- G25 Agent 声明与门槛交叉引用 ----------------------------------------
def g25(mods):
    """Agent 声明必须指向真实存在的东西。

    最要紧的一条是 thresholds：它写的是别的模块的参数键。写错一个字母，
    页面上那一项就静默消失 —— 不报错、不留痕，客户以为这个门槛不能调。
    所以必须逐键对着模块声明核。
    """
    param_keys = {}
    for m in mods:
        for p in m.get("params", []) or []:
            param_keys[p["key"]] = m["id"]
    ids = {m["id"] for m in mods}

    agents = []
    # 模块自己声明的（认领后在这里）
    for m in mods:
        for a in m.get("agents", []) or []:
            agents.append(("模块 " + m["id"], a))
    # 还登记在 Agent 配置模块里的（待认领）
    if "agentcfg" in ids:
        try:
            _, payload = get("/api/agentcfg/agents")
            for a in payload.get("agents", []):
                agents.append(("登记表", a))
        except Exception as e:                                  # noqa: BLE001
            gate("G25 Agent 声明交叉引用", False, f"读不到登记表：{e}")
            return

    if not agents:
        gate("G25 Agent 声明交叉引用", False, "一个 Agent 声明都没有，本条无检查对象")
        return

    bad, seen = [], {}
    for where, a in agents:
        aid = a.get("id")
        if not aid:
            bad.append(f"{where} 有 Agent 缺 id")
            continue
        if aid in seen:
            bad.append(f"Agent id 重复 {aid}（{seen[aid]} 与 {where}）")
        seen[aid] = where
        if a.get("owner") not in ids:
            bad.append(f"{aid} 的 owner={a.get('owner')!r} 不是已发现的模块")
        for k in a.get("thresholds", []) or []:
            if k not in param_keys:
                bad.append(f"{aid} 的门槛键 {k} 在任何模块里都不存在")
        # 产出与判断可以为空（未拍定），但不能是字符串——那说明写成了一句话而不是清单
        for field in ("judges", "computed", "needs", "outputs", "thresholds"):
            if not isinstance(a.get(field, []), list):
                bad.append(f"{aid} 的 {field} 不是清单")

    pending = [a["id"] for _, a in agents if a.get("status") == "待声明"]
    unclaimed = [a["id"] for where, a in agents if where == "登记表"]
    gate(
        "G25 Agent 声明交叉引用",
        not bad,
        "；".join(bad) if bad else
        f"{len(agents)} 个 Agent，门槛键全部命中模块声明（共 {len(param_keys)} 个可调门槛）"
        f"；待模块认领 {len(unclaimed)} 个，分析方式待拍定 {len(pending)} 个",
    )


# ---- G16 深链往返 -------------------------------------------------------
def g16(mods):
    bad = []
    # 无扩展名路径交给前端路由，必须回 index.html
    for p in ["/", "/sample", "/sample/detail", "/sample/detail/B0GKFMB38P"]:
        body = raw(p)
        if "<title>Bamboocool 运营工作台</title>" not in body:
            bad.append(f"{p} 未回 index.html")
    # 有扩展名但不存在的必须 404，不能拿 HTML 冒充 .js
    if status_of("/modules/nope.js") != 404:
        bad.append("/modules/nope.js 未回 404")
    # 未知模块与未知接口
    if status_of("/api/nosuch/meta") != 404:
        bad.append("未知模块未回 404")
    if status_of("/api/sample/nosuch") != 404:
        bad.append("未知接口未回 404")
    # 每个页面都能构造出一个可访问的 URL
    for m in mods:
        if m["degraded"]:
            continue
        for pg in m["pages"]:
            if "<title>" not in raw(f"/{m['id']}/{pg['id']}"):
                bad.append(f"/{m['id']}/{pg['id']} 不可达")
    gate("G16 深链可直接访问且缺失静态文件回 404", not bad, "；".join(bad[:5]))


def main() -> int:
    try:
        get("/api/meta")
    except Exception as exc:
        print(f"服务没起来：{exc}\n先跑 /usr/bin/python3 start.py start", file=sys.stderr)
        return 2

    ids, mods = module_ids()
    print(f"发现模块：{ids}\n")

    g1()
    g2_g3()
    g4()
    g18(mods)
    g5(mods)
    g6(mods)
    g7()
    g8()
    g9_g17()
    g12()
    g13()
    g14()
    g16(mods)
    g19_g23(mods)
    g25(mods)

    width = max(len(n) for n, _, _ in results)
    failed = 0
    for name, ok, detail in results:
        mark = "✅" if ok else "❌"
        print(f"{mark} {name.ljust(width)}  {detail}")
        if not ok:
            failed += 1

    print("\n以下两条无法机械化，必须人工做：")
    print("  G10 每个板块能说出它回答运营的哪个经营问题（对屏幕决策设计逐条核）")
    print("  G11 视觉验证 —— 真看页面截图。柱子塌成 0×0、数字挤在一起这类 bug 测试全绿也抓不到")

    print(f"\n{len(results) - failed}/{len(results)} 通过")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
