#!/usr/bin/env python3
"""参数生效验证：每个 kw.* 参数必须真的改变数字，不能只回显。

为什么要剥回显字段再比：第一版直接对整个响应体做哈希，kw.compare 和
kw.collect_depth 都显示「生效」—— 因为它们的值被原样回显在
scope.compare_period / positions.collect_depth 里，哈希当然变。
剥掉回显后重比才暴露出这两个参数一个数字都没动，是死参数。

每个参数还必须打在真有那个特征的对象上：collect_depth 在 B0B3LWGP36 上
怎么调都不动（它 66 对末期位次全在前 10），换到 B0CBPXNC1M（17 个词位次
在 20 名之后）才看得出重分类。

用法：先 start.py start，然后 /usr/bin/python3 tests/test_keyword_params.py
"""
from __future__ import annotations

import hashlib
import json
import sys
import urllib.request

BASE = "http://127.0.0.1:18820/api/keyword/"

# 纯回显字段：参数值原样出现在这里，比哈希前必须剥掉
ECHO_PATHS = [
    ("scope",),
    ("positions", "collect_depth"),
    ("positions", "rank_shift_threshold"),
    ("coverage", "summary", "weak_rank_threshold"),
    ("coverage", "dedup_applied"),
    ("evidence", "weights"),
    ("priority", "weights"),
    ("group_changes", "dedup_applied"),
    ("dedup_applied",),
]
ECHO_IN_REPORTS = ("compare_period", "compare_lag_days")

# (参数键, 值A, 值B, 打在哪个路由, 为什么是这个路由)
CASES = [
    ("kw.compare", "day", "week", "overview",
     "日报环比的基期窗口"),
    ("kw.weak_rank", "20", "5", "child/B0CBPXNC1M",
     "该子体有 17 个词位次在 20 名之后，阈值一动分档就变"),
    ("kw.collect_depth", "144", "48", "child/B0CBPXNC1M",
     "该子体有深位次，压低深度会把「有排名」重分类成「超出采集深度」"),
    ("kw.streak_days", "7", "3", "child/B0B3LWGP36",
     "该子体有 6 条连续走弱轨迹，天数阈值一动条数就变"),
    ("kw.rank_shift", "3", "15", "overview",
     "核心词显著变化的名次门槛"),
    ("kw.group_dedup", "1", "0", "terms?limit=30",
     "一词多组的搜索量是否按 1/组数 分摊"),
    ("kw.w_demand", "0.30", "0.90", "overview",
     "优先列表按需求规模重排"),
    ("kw.w_change", "0.30", "0.90", "child/B0B3LWGP36",
     "证据列表按变化紧迫重排"),
    ("kw.w_push", "0.20", "0.90", "overview",
     "优先列表按主推加权重排"),
    ("kw.w_evidence", "0.20", "0.90", "overview",
     "优先列表按证据完整度重排"),
]

# 已声明的参数必须全部在上面被覆盖，新增参数不许悄悄没有验证
def declared_params() -> list[str]:
    with urllib.request.urlopen("http://127.0.0.1:18820/api/modules", timeout=20) as r:
        mods = json.load(r)["modules"]
    for m in mods:
        if m["id"] == "keyword":
            return [p["key"] for p in m.get("params", [])]
    return []


def fetch(path: str) -> dict:
    with urllib.request.urlopen(BASE + path, timeout=40) as r:
        return json.load(r)


def strip_echo(d: dict) -> dict:
    out = json.loads(json.dumps(d))
    for path in ECHO_PATHS:
        node = out
        for k in path[:-1]:
            node = node.get(k) if isinstance(node, dict) else None
            if node is None:
                break
        if isinstance(node, dict):
            node.pop(path[-1], None)
    for r in out.get("reports", []) or []:
        for k in ECHO_IN_REPORTS:
            r.pop(k, None)
    return out


def digest(path: str) -> str:
    blob = json.dumps(strip_echo(fetch(path)), sort_keys=True, ensure_ascii=False)
    return hashlib.md5(blob.encode("utf-8")).hexdigest()[:10]


def main() -> int:
    checks = []
    covered = {c[0] for c in CASES}
    declared = declared_params()
    missing = [p for p in declared if p not in covered]
    extra = [p for p in covered if p not in declared]

    print("== 参数生效验证（剥掉回显字段后比对）==")
    for key, a, b, route, why in CASES:
        sep = "&" if "?" in route else "?"
        try:
            changed = digest("%s%s%s=%s" % (route, sep, key, a)) \
                != digest("%s%s%s=%s" % (route, sep, key, b))
        except Exception as exc:
            checks.append((key, False, str(exc)))
            print("  [FAIL] %-18s 取数失败 %s" % (key, exc))
            continue
        checks.append((key, changed, why))
        print("  [%s] %-18s %-22s %s"
              % ("PASS" if changed else "FAIL", key, route.split("?")[0], why))

    print()
    ok_cover = not missing
    print("  [%s] 声明的 %d 个参数全部有验证 %s"
          % ("PASS" if ok_cover else "FAIL", len(declared),
             "" if ok_cover else "未覆盖：" + ", ".join(missing)))
    if extra:
        print("  [WARN] 验证里有已删除的参数：%s" % ", ".join(extra))

    nfail = sum(1 for _, ok, _ in checks if not ok) + (0 if ok_cover else 1)
    print("\n%d 条，失败 %d 条" % (len(checks) + 1, nfail))
    return 1 if nfail else 0


if __name__ == "__main__":
    sys.exit(main())
