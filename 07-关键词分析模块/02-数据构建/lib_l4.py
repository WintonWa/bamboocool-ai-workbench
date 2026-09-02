#!/usr/bin/env python3
"""L4 覆盖与位置关系：关键词 × 子ASIN × 日期 的自然位与广告位。

真实锚点：关键词3 头部/前十字段里出现的自有 ASIN → 末期（2026-08-03）必须落在
对应位段（前三 rank≤3、前十 4≤rank≤10）。往前 181 天为构造值。
广告位客户完全没有，全部构造并显式标注。
"""
from __future__ import annotations

import collections
import datetime as dt
import hashlib
import random

DAILY_END = dt.date(2026, 8, 3)
DAILY_DAYS = 182                      # = 26 周 × 7，周格能套住日格
COLLECT_DEPTH = 144                   # 自然位采集深度：前 3 页 × 48
AD_DEPTH = 20

# 每个重点子体的关系词数区间（真实覆盖是稀疏的，不做笛卡尔积）
PAIRS_MIN, PAIRS_MAX = 20, 60

# 全站采集失败日（做成整日条带，界面上是一根竖条而不是零散噪点）
GLOBAL_FAIL_DATES = ["2026-03-17", "2026-05-06", "2026-06-29"]

# 6 个子体是后来才纳入监控的 → 之前全部 not_monitored
LATE_MONITOR_FROM = "2026-05-01"
LATE_MONITOR_COUNT = 6

ORGANIC_STATES = ["covered", "not_covered", "beyond_depth", "collect_failed",
                  "not_monitored"]
STATE_LABEL = {
    "covered": "有排名",
    "not_covered": "确认未覆盖",
    "beyond_depth": "超出采集深度",
    "collect_failed": "当日采集失败",
    "not_monitored": "未纳入监控",
}
COVERAGE_LABEL = {
    "organic_only": "仅自然覆盖",
    "ad_only": "仅广告覆盖",
    "both": "自然与广告同时覆盖",
    "none": "未覆盖",
    "unconfirmed": "覆盖未确认",
}
PLACEMENT_LABEL = {
    "top_of_search": "搜索结果顶部",
    "rest_of_search": "搜索结果其余位置",
    "product_page": "商品页面",
}

# 位置形态配额（按对分配）
PAIR_SHAPES = [
    ("organic_up", 0.16, "自然位上涨"),
    ("organic_down", 0.16, "自然位下降"),
    ("organic_gained", 0.10, "新增自然覆盖"),
    ("organic_lost", 0.10, "丢失自然覆盖"),
    ("ad_only", 0.12, "仅广告覆盖"),
    ("organic_only", 0.12, "仅自然覆盖"),
    ("both_stable", 0.14, "双覆盖稳定"),
    ("beyond_depth", 0.10, "长期超出采集深度"),
]
PAIR_SHAPE_LABEL = {s: lab for s, _, lab in PAIR_SHAPES}


def _rng(*parts) -> random.Random:
    h = hashlib.md5("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()
    return random.Random(int(h[:12], 16))


def dates():
    start = DAILY_END - dt.timedelta(days=DAILY_DAYS - 1)
    return [(start + dt.timedelta(days=i)).isoformat() for i in range(DAILY_DAYS)]


def _attr_affinity(child, kw_row) -> float:
    """子体属性与关键词标签的粗匹配度，只用来决定「谁更可能覆盖这个词」。"""
    score = 0.0
    tags = set(kw_row.get("all_category_tags") or [])
    color = (child.get("colorway") or "").lower()
    size = (child.get("size") or "").lower()
    comb = (child.get("combination") or "").lower()
    k = kw_row["keyword"]
    if "颜色" in tags and color and any(w in k for w in color.split()):
        score += 1.5
    if "尺码" in tags and size and size in k:
        score += 1.5
    if "数量" in tags and comb and any(ch.isdigit() for ch in comb):
        score += 1.0
    if kw_row.get("brand_role") == "own_brand":
        score += 2.0
    if kw_row.get("operator_role") == "core":
        score += 1.2
    return score


def build_pairs(kw_rows, children, focus_asins, coverage_by_kw):
    """确定性地决定哪些 (关键词, 子ASIN) 存在关系，并给每对配一个位置形态。"""
    by_asin = {c["child_asin"]: c for c in children}
    monitored = [r for r in kw_rows if r["is_monitored"]]
    kw_by_key = {r["keyword"]: r for r in kw_rows}
    focus = list(focus_asins)

    # 1) 真实锚点：客户头部/前十字段里出现的重点子体
    anchors = collections.defaultdict(dict)      # asin -> {keyword: 'top3'|'top10'}
    for r in monitored:
        cov = coverage_by_kw.get(r["keyword"])
        if not cov:
            continue
        for a in cov.get("top3", []):
            if a in focus_asins:
                anchors[a][r["keyword"]] = "top3"
        for a in cov.get("top10", []):
            if a in focus_asins and r["keyword"] not in anchors[a]:
                anchors[a][r["keyword"]] = "top10"

    # ---- 阶段 0：真实锚点 + 各子体目标词数
    chosen = {a: {} for a in focus}
    target = {}
    for asin in focus:
        rng = _rng("pairs", asin)
        for kw, band in sorted(anchors.get(asin, {}).items()):
            chosen[asin][kw] = band
        # 关系词数与真实覆盖度正相关：真实一个词都没上榜的子体不该配到和主力一样多的词
        n_anchor = len(chosen[asin])
        if n_anchor >= 40:
            t = 55 + rng.randrange(11)
        elif n_anchor >= 15:
            t = 35 + rng.randrange(16)
        elif n_anchor >= 1:
            t = 24 + rng.randrange(12)
        else:
            t = PAIRS_MIN + rng.randrange(9)          # 零覆盖子体 20-28 对
        target[asin] = max(t, n_anchor)                # 真实锚点一个都不丢

    use = collections.Counter()
    for asin in focus:
        for kw in chosen[asin]:
            use[kw] += 1

    # ---- 阶段 1：每个监控词至少进一个产品关系
    # 不做这一步的话，affinity 里与子体无关的主导项会让 30 个子体挑到同一批词：
    # 实测 901 对只覆盖 123 个词，另外 177 个监控词永远没有产品关系，
    # 45 个需求上涨词里只有 3 个进得了 pair，页面一的机会类结论几乎没有对象。
    for r in monitored:
        kw = r["keyword"]
        if use[kw]:
            continue
        cands = [a for a in focus if len(chosen[a]) < target[a] and kw not in chosen[a]]
        if not cands:
            cands = [a for a in focus if kw not in chosen[a]]
        if not cands:
            continue
        best = max(cands, key=lambda a: (_attr_affinity(by_asin[a], r)
                                         + _rng("seed", a, kw).random(),
                                         -len(chosen[a]), a))
        chosen[best][kw] = None
        use[kw] += 1

    # ---- 阶段 2：按 affinity 减「已被几个子体选过」的惩罚补齐
    for asin in focus:
        child = by_asin[asin]
        cands = [r for r in monitored if r["keyword"] not in chosen[asin]]
        cands.sort(key=lambda r: (-(_attr_affinity(child, r)
                                    - 0.8 * use[r["keyword"]]
                                    + _rng("aff", asin, r["keyword"]).random()),
                                  r["keyword"]))
        for r in cands:
            if len(chosen[asin]) >= target[asin]:
                break
            chosen[asin][r["keyword"]] = None
            use[r["keyword"]] += 1

    pairs = []
    for asin in focus:
        for kw, band in sorted(chosen[asin].items()):
            pairs.append({"keyword_id": kw_by_key[kw]["keyword_id"], "keyword": kw,
                          "child_asin": asin, "anchor_band": band})

    # 3) 形态分配：有真实锚点的对不能给「丢失覆盖 / 仅广告 / 超深度」这类末期无自然位的形态
    anchored_ok = {"organic_up", "organic_down", "organic_only", "both_stable"}
    n = len(pairs)
    quota = {}
    acc = 0
    for i, (s, frac, _) in enumerate(PAIR_SHAPES):
        q = n - acc if i == len(PAIR_SHAPES) - 1 else int(round(n * frac))
        quota[s] = q
        acc += q
    order = sorted(pairs, key=lambda p: (p["child_asin"], p["keyword"]))
    left = dict(quota)
    for p in order:
        prefer = (sorted(anchored_ok, key=lambda s: -left.get(s, 0))
                  if p["anchor_band"] else
                  sorted(left, key=lambda s: -left.get(s, 0)))
        for s in prefer:
            if left.get(s, 0) > 0:
                p["pair_shape"] = s
                left[s] -= 1
                break
        else:
            p["pair_shape"] = "both_stable"
    return order


def pick_late_monitor(pair_rows_or_pairs, focus_asins) -> list[str]:
    """后纳入监控的子体：只从真实锚点最少的子体里挑。

    绝不能按字母序取前 N 个 —— 那会把覆盖最富的主演示对象（B0B3LWGP36）算进去，
    导致它前 87 天全是「未纳入监控」，页面三半个窗口是空的。
    """
    n_anchor = collections.Counter()
    for p in pair_rows_or_pairs:
        if p.get("anchor_band"):
            n_anchor[p["child_asin"]] += 1
    ranked = sorted(focus_asins, key=lambda a: (n_anchor.get(a, 0), a))
    return ranked[:LATE_MONITOR_COUNT]


def build_positions(pairs, children, focus_asins):
    """→ (pair_rows, daily_rows, state_labels)"""
    ds = dates()
    late = pick_late_monitor(pairs, focus_asins)
    late_set = set(late)
    fails = set(GLOBAL_FAIL_DATES)

    pair_rows = []
    daily = []
    pid = 0
    rid = 0
    for p in pairs:
        pid += 1
        pair_id = "kp_%05d" % pid
        shape = p["pair_shape"]
        band = p["anchor_band"]
        rng = _rng("pos", p["child_asin"], p["keyword"])
        monitor_from = LATE_MONITOR_FROM if p["child_asin"] in late_set else ds[0]

        # 末期自然位：有锚点就必须落在对应位段。
        # 锚点 + 下降形态有内在冲突（末期在前三又要比首期差）→ 末期取位段里最差的一位
        if band == "top3":
            end_rank = 3 if shape == "organic_down" else (
                1 if shape == "organic_up" else 1 + rng.randrange(3))
        elif band == "top10":
            end_rank = 10 if shape == "organic_down" else (
                4 if shape == "organic_up" else 4 + rng.randrange(7))
        elif shape in ("ad_only", "organic_lost"):
            end_rank = None
        elif shape == "beyond_depth":
            end_rank = None
        else:
            end_rank = 12 + rng.randrange(100)

        # 轨迹起点
        if end_rank is None:
            start_rank = 20 + rng.randrange(120)
        elif shape == "organic_up":
            start_rank = min(COLLECT_DEPTH, end_rank + 8 + rng.randrange(60))
        elif shape == "organic_down":
            start_rank = 1 if band else max(1, end_rank - (5 + rng.randrange(
                min(40, max(1, end_rank)))))
        else:
            start_rank = end_rank

        # 新增/丢失覆盖的时点必须落在该对的可观测窗口内，否则跳变发生在监控开始前，
        # 页面上只看到一条恒定的「未覆盖」，形态等于没造出来
        mon_idx = ds.index(monitor_from) if monitor_from in ds else 0
        span = DAILY_DAYS - mon_idx
        gain_at = (mon_idx + 15 + rng.randrange(max(1, span - 40))
                   if shape == "organic_gained" else None)
        lost_at = (mon_idx + 20 + rng.randrange(max(1, span - 45))
                   if shape == "organic_lost" else None)
        ad_active = shape in ("ad_only", "both_stable", "organic_up", "organic_gained")
        ad_start_at = rng.randrange(30) if ad_active else None
        # 约四分之一投过广告的对会中途停投 → 否则「丢失广告覆盖」这类事件永远为 0
        ad_stop_at = (mon_idx + 60 + rng.randrange(max(1, span - 70))
                      if ad_active and rng.random() < 0.25 else None)
        ad_end_rank = 1 + rng.randrange(AD_DEPTH) if ad_active else None

        for i, d in enumerate(ds):
            rid += 1
            row = {"pos_id": rid, "pair_id": pair_id,
                   "keyword_id": p["keyword_id"], "child_asin": p["child_asin"],
                   "date": d}
            last = i == DAILY_DAYS - 1

            if d < monitor_from:
                o_state, o_rank = "not_monitored", None
            elif d in fails and rng.random() < 0.7 and not last:
                o_state, o_rank = "collect_failed", None
            elif shape == "beyond_depth":
                o_state, o_rank = "beyond_depth", None
            elif gain_at is not None and i < gain_at:
                o_state, o_rank = "not_covered", None
            elif lost_at is not None and i >= lost_at and not last:
                o_state, o_rank = "not_covered", None
            elif shape in ("ad_only",) or (shape == "organic_lost" and last):
                o_state, o_rank = "not_covered", None
            else:
                t = i / (DAILY_DAYS - 1)
                base = start_rank + (end_rank - start_rank) * t if end_rank else start_rank
                jitter = (rng.random() - 0.5) * max(2.0, base * 0.08)
                r = int(round(base + (0 if last else jitter)))
                r = max(1, r)
                if last and end_rank is not None:
                    r = end_rank
                if r > COLLECT_DEPTH:
                    o_state, o_rank = "beyond_depth", None
                else:
                    o_state, o_rank = "covered", r

            if d < monitor_from:
                a_state, a_rank, placement = "not_monitored", None, None
            elif not ad_active or (ad_start_at is not None and i < ad_start_at):
                a_state, a_rank, placement = "not_covered", None, None
            elif ad_stop_at is not None and i >= ad_stop_at:
                a_state, a_rank, placement = "not_covered", None, None
            elif d in fails and rng.random() < 0.4 and not last:
                a_state, a_rank, placement = "collect_failed", None, None
            else:
                t = i / (DAILY_DAYS - 1)
                ar = int(round(ad_end_rank + (1 - t) * (rng.random() * 6)))
                ar = max(1, min(AD_DEPTH, ar))
                a_state, a_rank = "covered", (ad_end_rank if last else ar)
                placement = ("top_of_search" if ar <= 4 else
                             "rest_of_search" if ar <= 12 else "product_page")

            if o_state == "covered" and a_state == "covered":
                cov = "both"
            elif o_state == "covered":
                cov = "organic_only"
            elif a_state == "covered":
                cov = "ad_only"
            elif "collect_failed" in (o_state, a_state) or "beyond_depth" in (o_state, a_state):
                cov = "unconfirmed"
            elif o_state == "not_monitored":
                cov = "unconfirmed"
            else:
                cov = "none"

            row.update({
                "organic_rank": o_rank,
                "organic_page": (None if o_rank is None else (o_rank - 1) // 48 + 1),
                "organic_state": o_state,
                "ad_rank": a_rank,
                "ad_placement": placement,
                "ad_state": a_state,
                "coverage_state": cov,
                "collect_source": "自然位采集器 / 广告位采集器",
                "collect_depth": COLLECT_DEPTH,
                "site": "US",
                "value_origin": ("customer_real_anchor" if (last and band) else
                                 "synthetic_demo"),
            })
            daily.append(row)

        pair_rows.append({
            "pair_id": pair_id, "keyword_id": p["keyword_id"], "keyword": p["keyword"],
            "child_asin": p["child_asin"],
            "anchor_band": band, "anchor_band_label": ("客户头部前三" if band == "top3"
                                                      else "客户前十" if band == "top10"
                                                      else None),
            "pair_shape": shape, "pair_shape_label": PAIR_SHAPE_LABEL[shape],
            "monitor_from": monitor_from,
            "end_organic_rank": end_rank,
            "value_origin": "customer_real_anchor" if band else "synthetic_demo",
        })

    labels = []
    for code, lab in STATE_LABEL.items():
        labels.append({"label_id": "st_%s" % code, "domain": "position_state",
                       "code": code, "label": lab})
    for code, lab in COVERAGE_LABEL.items():
        labels.append({"label_id": "cv_%s" % code, "domain": "coverage_state",
                       "code": code, "label": lab})
    for code, lab in PLACEMENT_LABEL.items():
        labels.append({"label_id": "pl_%s" % code, "domain": "ad_placement",
                       "code": code, "label": lab})
    for code, lab in PAIR_SHAPE_LABEL.items():
        labels.append({"label_id": "ps_%s" % code, "domain": "pair_shape",
                       "code": code, "label": lab})
    return pair_rows, daily, labels


# ------------------------------------------------------------------------ 门禁

def gate_l4(pair_rows, daily, coverage_by_kw, focus_asins):
    out = []
    ds = dates()
    last = ds[-1]

    # G4-1 真实锚点必须落在对应位段
    by_pair = {p["pair_id"]: p for p in pair_rows}
    last_rows = {r["pair_id"]: r for r in daily if r["date"] == last}
    bad = []
    n_anchor = 0
    for pid, p in by_pair.items():
        if not p["anchor_band"]:
            continue
        n_anchor += 1
        r = last_rows.get(pid)
        rank = r["organic_rank"] if r else None
        if p["anchor_band"] == "top3" and not (rank and rank <= 3):
            bad.append((p["keyword"], p["child_asin"], "top3", rank))
        if p["anchor_band"] == "top10" and not (rank and 4 <= rank <= 10):
            bad.append((p["keyword"], p["child_asin"], "top10", rank))
    out.append(("G4-1 %d 个真实锚点末期落在对应位段" % n_anchor, not bad,
                "越界 %d 个 %s" % (len(bad), bad[:3])))

    # G4-2 五种自然位状态每种至少 5 个对
    st = collections.defaultdict(set)
    for r in daily:
        st[r["organic_state"]].add(r["pair_id"])
    missing = [s for s in ORGANIC_STATES if len(st.get(s, ())) < 5]
    out.append(("G4-2 五种自然位状态每种至少 5 个对出现", not missing,
                ", ".join("%s=%d" % (s, len(st.get(s, ()))) for s in ORGANIC_STATES)))

    # G4-3 四种覆盖态都要有
    cv = collections.Counter(r["coverage_state"] for r in daily)
    need = ["organic_only", "ad_only", "both", "none"]
    out.append(("G4-3 四种覆盖态都出现", all(cv.get(c, 0) > 0 for c in need),
                ", ".join("%s=%d" % (c, cv.get(c, 0)) for c in need + ["unconfirmed"])))

    # G4-4 采集失败必须是整日条带而非零散噪点
    per_date = collections.Counter(r["date"] for r in daily
                                  if r["organic_state"] == "collect_failed")
    stripes = [d for d, c in per_date.items() if c >= 100]
    out.append(("G4-4 采集失败日形成整日条带（≥100 对同日失败）",
                sorted(stripes) == sorted(GLOBAL_FAIL_DATES),
                "条带日=%s" % sorted(stripes)))

    # G4-5 后纳入监控的子体：早期必须是 not_monitored 而不是未覆盖
    late = pick_late_monitor(pair_rows, focus_asins)
    early = [r for r in daily if r["child_asin"] in set(late) and r["date"] < LATE_MONITOR_FROM]
    ok = early and all(r["organic_state"] == "not_monitored" for r in early)
    out.append(("G4-5 %d 个后纳入子体在 %s 之前全为未纳入监控"
                % (LATE_MONITOR_COUNT, LATE_MONITOR_FROM), bool(ok),
                "早期行 %d 条, 非 not_monitored %d 条; 子体=%s"
                % (len(early), sum(1 for r in early
                                   if r["organic_state"] != "not_monitored"),
                   ",".join(late))))

    # G4-5b 主演示对象绝不能落在后纳入集合里（否则半个窗口是空的）
    demo_objs = ["B0B3LWGP36", "B0CGLWQVWR", "B0CGLWJH26"]
    leaked = [a for a in demo_objs if a in set(late)]
    out.append(("G4-5b 主演示对象 %s 全窗口在监控内" % "/".join(demo_objs),
                not leaked, "落入后纳入集合的=%s" % (leaked or "无")))

    # G4-5c 关系词数必须与真实覆盖度正相关，零覆盖子体不得配到最多的词
    per_child = collections.Counter(p["child_asin"] for p in pair_rows)
    anch = collections.Counter(p["child_asin"] for p in pair_rows if p["anchor_band"])
    top_child = max(per_child, key=lambda a: (per_child[a], a))
    zero_max = max((per_child[a] for a in per_child if anch.get(a, 0) == 0), default=0)
    rich_min = min((per_child[a] for a in per_child if anch.get(a, 0) >= 15), default=0)
    out.append(("G4-5d 零覆盖子体关系词数 < 真实覆盖子体关系词数",
                zero_max < rich_min,
                "零覆盖最多=%d, 真实覆盖最少=%d, 词数最多的子体=%s(%d对/%d锚点)"
                % (zero_max, rich_min, top_child, per_child[top_child],
                   anch.get(top_child, 0))))

    # G4-6 新增覆盖与丢失覆盖必须真的各自存在
    # 注意：首行可能是 not_monitored（后纳入监控的子体），要从进入监控之后的第一行看起
    def first_monitored(pair_id):
        rows = sorted((r for r in daily if r["pair_id"] == pair_id),
                      key=lambda r: r["date"])
        eff = [r for r in rows if r["organic_state"] != "not_monitored"]
        return (eff[0], eff[-1]) if eff else (None, None)

    gained = [p for p in pair_rows if p["pair_shape"] == "organic_gained"]
    lost = [p for p in pair_rows if p["pair_shape"] == "organic_lost"]
    # 全量校验而不只看第一个，否则一个能过就掩盖了其余的
    g_bad = l_bad = 0
    for p in gained:
        a, b = first_monitored(p["pair_id"])
        if not (a and a["organic_state"] == "not_covered"
                and b["organic_state"] == "covered"):
            g_bad += 1
    for p in lost:
        a, b = first_monitored(p["pair_id"])
        if not (a and a["organic_state"] == "covered"
                and b["organic_state"] == "not_covered"):
            l_bad += 1
    out.append(("G4-6 全部 %d 个新增覆盖对与 %d 个丢失覆盖对的跳变都落在可观测窗口内"
                % (len(gained), len(lost)), g_bad == 0 and l_bad == 0,
                "新增不合格 %d 个, 丢失不合格 %d 个" % (g_bad, l_bad)))

    # G4-7 零覆盖黄金场景子体不得凭空出现真实锚点
    zero = ["B0CBPXNC1M", "B0BVM5PHFB"]
    leak = [p for p in pair_rows if p["child_asin"] in zero and p["anchor_band"]]
    out.append(("G4-7 零覆盖子体 B0CBPXNC1M / B0BVM5PHFB 无真实锚点", not leak,
                "锚点泄漏 %d 个" % len(leak)))

    # G4-8 超深度必须记为 beyond_depth 而不是 not_covered
    over = [r for r in daily if r["organic_rank"] and r["organic_rank"] > COLLECT_DEPTH]
    out.append(("G4-8 不存在超过采集深度 %d 却仍记为有排名的行" % COLLECT_DEPTH,
                not over, "越界行 %d 条" % len(over)))

    # G4-9 上涨/下降形态必须真的动了（锚点+下降曾经全程恒为 rank 1，看不出在降）
    by_pair_rows = collections.defaultdict(list)
    for r in daily:
        if r["organic_rank"]:
            by_pair_rows[r["pair_id"]].append((r["date"], r["organic_rank"]))
    flat = []
    for shape in ("organic_up", "organic_down"):
        for p in pair_rows:
            if p["pair_shape"] != shape:
                continue
            seq = sorted(by_pair_rows.get(p["pair_id"], []))
            if len(seq) < 10:
                continue
            if seq[0][1] == seq[-1][1]:
                flat.append((p["keyword"], p["child_asin"], shape, seq[0][1]))
    out.append(("G4-9 上涨/下降形态的对首末自然位不得相同", not flat,
                "恒定不动的对 %d 个 %s" % (len(flat), flat[:3])))

    # G4-10 全部 300 个监控词都必须进入至少一个产品关系
    kw_in_pairs = {p["keyword_id"] for p in pair_rows}
    out.append(("G4-10 监控词全部进入产品关系（覆盖面不得塌到少数词）",
                len(kw_in_pairs) >= 300,
                "关系覆盖 %d 个不同关键词 / %d 对" % (len(kw_in_pairs), len(pair_rows))))
    return out
