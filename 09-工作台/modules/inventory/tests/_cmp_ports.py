"""并排比对 18810 与 18820 的完整载荷。

不手挑字段 —— 手挑会挑错，挑错了两边都返回 None，比对 None == None 报"一致"，
那是假绿。这里递归比对整份 JSON，把所有不一致的路径打出来。

用法：/usr/bin/python3 _cmp_ports.py [asin ...]
"""
import json
import sys
import urllib.request

# 按特征挑的靶子，不是随手取前几个：
#   B0F4R834YP  2 类事件 12 段 + 59 缺货日   （事件与缺货都密）
#   B0CGLWQVWR  BD+Coupon 15 段 + 43 缺货日  （两类活动叠加）
#   B0B3LM36WB  设计图复现用的那个           （趋势+季节，置信度中）
#   B0GKFMB38P  零风险                        （对照组，别只测有问题的）
#   B0B3LWGP36  closing_fba_sellable 中段失真的那个
DEFAULT = ["B0F4R834YP", "B0CGLWQVWR", "B0B3LM36WB", "B0GKFMB38P", "B0B3LWGP36"]

# 允许不同的路径：迁移本身带来的、已知且有理由的差异
ALLOWED = set()


def get(port, asin):
    prefix = "inventory/" if port == 18820 else ""
    url = f"http://127.0.0.1:{port}/api/{prefix}child/{asin}"
    with urllib.request.urlopen(url, timeout=120) as r:
        return json.load(r)


def walk(a, b, path=""):
    """递归比对，返回不一致的路径列表。"""
    out = []
    if type(a) is not type(b) and not (isinstance(a, (int, float)) and isinstance(b, (int, float))):
        return [(path, f"类型 {type(a).__name__} vs {type(b).__name__}")]
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            p = f"{path}.{k}" if path else k
            if k not in a:
                out.append((p, "只有 18820 有"))
            elif k not in b:
                out.append((p, "只有 18810 有"))
            else:
                out += walk(a[k], b[k], p)
    elif isinstance(a, list):
        if len(a) != len(b):
            out.append((path, f"长度 {len(a)} vs {len(b)}"))
        else:
            for i, (x, y) in enumerate(zip(a, b)):
                out += walk(x, y, f"{path}[{i}]")
    elif isinstance(a, float) or isinstance(b, float):
        if a is None or b is None:
            if a is not b:
                out.append((path, f"{a!r} vs {b!r}"))
        elif abs(float(a) - float(b)) > 1e-9:
            out.append((path, f"{a!r} vs {b!r}"))
    elif a != b:
        out.append((path, f"{a!r} vs {b!r}"))
    return out


def main():
    asins = sys.argv[1:] or DEFAULT
    total_bad = 0
    for asin in asins:
        try:
            old, new = get(18810, asin), get(18820, asin)
        except Exception as exc:
            print(f"  {asin}  取数失败：{exc}")
            total_bad += 1
            continue

        diffs = [(p, d) for p, d in walk(old, new) if p not in ALLOWED]
        # 报一下实际比了多少东西，避免"0 项检查"的假绿
        leaves = _count_leaves(old)
        if not diffs:
            print(f"  {asin}  一致（比对了 {leaves} 个叶子值）")
        else:
            total_bad += 1
            print(f"  {asin}  {len(diffs)} 处不一致（共 {leaves} 个叶子值）")
            for p, d in diffs[:25]:
                print(f"      {p}: {d}")
            if len(diffs) > 25:
                print(f"      …… 另有 {len(diffs)-25} 处")

    print()
    print("全部一致" if not total_bad else f"{total_bad}/{len(asins)} 个对象有差异")
    return 1 if total_bad else 0


def _count_leaves(x):
    if isinstance(x, dict):
        return sum(_count_leaves(v) for v in x.values())
    if isinstance(x, list):
        return sum(_count_leaves(v) for v in x)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
