#!/usr/bin/env python3
"""扫抹值后的 JSON 样例里还有哪些「长中文串」漏网。

判据：产出侧的东西通常是长句或结论词。这个脚本把样例里所有 ≥8 字的中文串
按字段名聚合列出来，人工过一遍决定该不该进 MASK_FIELDS。

比正则猜结论句可靠 —— 正则只抓得到「」句式，抓不到「需先补货再扩量」这种短结论。

用法：/usr/bin/python3 sweep_masked_sample.py
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

SAMPLE = (pathlib.Path(__file__).parents[1] / "01-方案与数据需求"
          / "07-接口JSON样例.json")

# 已知安全：口径名、窗口、产品主数据、页面自算的统计与标签
SAFE = {
    "site", "product_line", "traffic_proxy_metric", "compare_period",
    "scope_label", "judgment_object", "dataset_version", "as_of",
    "keyword", "keyword_cn", "keyword_raw", "alias_key", "child_asin",
    "parent_asin", "style_no", "colorway", "size", "combination",
    "product_name", "group_name", "demand_dimension", "anchor_attribute_word",
    "primary_category", "category_path", "matched_brand", "brand",
    "_呈现", "_说明", "_产出侧已抹值", "_基址", "_参数",
    "condition", "nature", "library_scope", "period_type",
    "current_state_label", "state", "name", "label_cn",
    "brand_role_label", "anchor_band_label", "attribute_dimension",
    "source_file", "source_code", "selection_bucket", "traffic_word_type",
}
CJK = re.compile(r"[\u4e00-\u9fff]")


def main() -> int:
    if not SAMPLE.exists():
        print("找不到样例：%s" % SAMPLE)
        return 1
    data = json.loads(SAMPLE.read_text(encoding="utf-8"))
    found: dict[str, set] = {}

    def walk(o, key=""):
        if isinstance(o, dict):
            for k, v in o.items():
                walk(v, k)
        elif isinstance(o, list):
            for v in o:
                walk(v, key)
        elif isinstance(o, str):
            if o.startswith("<") or o.startswith("……"):
                return
            n = len(CJK.findall(o))
            if n >= 4 and key not in SAFE:
                found.setdefault(key, set()).add(o[:70])

    walk(data)
    if not found:
        print("没有漏网的长中文串。")
        return 0
    print("== 抹值后仍有中文内容的字段（人工判断该不该抹）==")
    for k in sorted(found):
        vals = sorted(found[k])
        print("  %-30s %d 种" % (k, len(vals)))
        for v in vals[:3]:
            print("      " + v)
    print()
    print("共 %d 个字段。凡是「念出来就把 Agent 该说的话说完了」的，加进 "
          "export_agent_package.py 的 MASK_FIELDS。" % len(found))
    return 0


if __name__ == "__main__":
    sys.exit(main())
