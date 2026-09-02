#!/usr/bin/env python3
"""扫载荷里还带码值的字段 —— 渲染态门禁的补充信息。

渲染态扫描（tests/test_keyword_render.mjs）只能抓「码值被渲染出来」这一种失误。
如果载荷里根本没有码值字段，那条门禁就永远不会红 —— 真正的防线在 SQL 只选
_label 列这一步。这个脚本把「载荷里还剩哪些码值字段」列出来，
让人知道渲染态门禁实际在保护哪几个字段。

用法：先 start.py start，然后 /usr/bin/python3 tests/probe_code_fields.py
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request

BASE = "http://127.0.0.1:18820/api/keyword/"
ROUTES = ["child/B0CBPXNC1M", "child/B0B3LWGP36", "overview",
          "terms?limit=5", "term/kw_00001", "children", "meta"]

CODE = re.compile(
    r"^(covered|not_covered|beyond_depth|collect_failed|not_monitored"
    r"|organic_only|ad_only|both|none|unconfirmed"
    r"|direct|derived|constructed|synthetic_demo|customer_real\w*"
    r"|top3|top10|day|week|4week"
    r"|organic_up|organic_down|both_stable|\w+_gained|\w+_lost"
    r"|demand_up|demand_down|competition_up|insufficient_history|not_comparable"
    r"|single_period|continuous|insufficient"
    r"|market_opportunity|coverage_gap|core_position_risk|scene_longtail_signal"
    r"|inventory_limited|insufficient_data|pending_competitor_verification"
    r"|volume_push|hold_position|niche_explore|brand_defend|clear_stock"
    r"|maintain_base|main|assist|normal"
    r"|can_absorb_extra|cannot_absorb|replenish_first|normal_only"
    r"|healthy|stockout|overstock|replenishment_gap|aged_inventory_risk"
    r"|valid|pending|noise|monitor|core|explore|longtail|pending_validation|unset"
    r"|own_brand|competitor_brand|generic|kw2|kw3)$")


def get(path: str):
    with urllib.request.urlopen(BASE + path, timeout=30) as r:
        return json.load(r)


def main() -> int:
    found: dict[str, set] = {}
    for route in ROUTES:
        try:
            payload = get(route)
        except Exception as exc:
            print("  %-24s 取不到：%s" % (route, exc))
            continue
        root = route.split("?")[0]

        def walk(o, path):
            if isinstance(o, dict):
                for k, v in o.items():
                    walk(v, path + "." + k)
            elif isinstance(o, list):
                for v in o[:5]:
                    walk(v, path + "[]")
            elif isinstance(o, str) and CODE.match(o):
                found.setdefault(path.lstrip("."), set()).add(o)

        walk(payload, root)

    print("== 载荷里仍带码值的字段 ==")
    if not found:
        print("  无。渲染态门禁当前没有可保护的对象 ——")
        print("  真正的防线是 data.py 只 select _label 列，改 SQL 时要盯住这一点。")
        return 0
    for k in sorted(found):
        print("  %-56s %s" % (k, sorted(found[k])[:4]))
    print("\n共 %d 个字段。渲染态门禁保护的就是这些字段不被直接渲染成文本；" % len(found))
    print("其余字段的防线在 SQL 层（只选 _label 列），改 data.py 时要盯住。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
