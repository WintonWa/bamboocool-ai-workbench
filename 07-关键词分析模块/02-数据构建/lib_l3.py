#!/usr/bin/env python3
"""L3 市场事实时间序列：26 周 + 12 月双频率快照 + 头部 ASIN 结构。

核心手法：客户那一张截面钉在时间轴末端（末期 = customer_real，一字节不改），
往前 25 周 / 11 月为构造值（synthetic_demo），并让 7 种变化形态落在具体的词上。
"""
from __future__ import annotations

import collections
import datetime as dt
import hashlib
import random

WEEK_PERIODS = 26
MONTH_PERIODS = 12
WEEK_LAST_END = dt.date(2026, 8, 3)     # = as_of，与 v0.3.0 统一业务截止日一致
MONTH_LAST = (2026, 7)                  # 最后一个完整月

# 七种变化形态的配额（落在 300 个监控词上，其余词走 stable_light）
SHAPE_QUOTA = [
    ("demand_up", 45, "需求持续上涨"),
    ("demand_down", 35, "需求持续下滑"),
    ("stable", 120, "需求稳定"),
    ("competition_up", 40, "竞争加剧"),
    ("head_replaced", 25, "头部 ASIN 替换"),
    ("insufficient_history", 20, "历史样本不足"),
    ("not_comparable", 15, "口径变更不可比"),
]

# 形态优先分配给哪些选样桶（语义要对得上，不能乱配）
SHAPE_PREF = {
    "demand_up": ["gap_no_coverage", "longtail_high_cvr", "scene"],
    "demand_down": ["core_big", "own_brand", "size_color_qty"],
    "stable": ["fill", "attribute", "competitor_brand", "own_brand"],
    "competition_up": ["core_big", "competitor_brand", "attribute"],
    "head_replaced": ["core_big", "own_brand"],
    "insufficient_history": ["noise", "variant", "gap_no_coverage"],
    "not_comparable": ["noise", "variant", "size_color_qty"],
}

SHAPE_LABEL = {s: lab for s, _, lab in SHAPE_QUOTA}
SHAPE_LABEL["stable_light"] = "需求稳定"

MEASURE_WEEK_A = "第三方工具周度估算·口径A"
MEASURE_WEEK_B = "第三方工具周度估算·口径B（该期起来源变更）"
MEASURE_MONTH = "第三方工具月度估算 + ABA 月排名"
NOT_COMPARABLE_AT = 13          # 口径变更发生在第 14 期（0-based 13）
INSUFFICIENT_KEEP = 4           # 样本不足的词只有最后 4 期有数

WEEK_METRICS = ["aba_week_rank", "product_count", "demand_supply_ratio",
                "ad_competitor_count", "ppc_bid", "suggested_bid_low",
                "suggested_bid_high", "title_density", "spr",
                "click_share_top3", "conv_share_top3", "avg_price",
                "rating_count", "rating"]
MONTH_METRICS = ["monthly_search_volume", "monthly_purchase_volume",
                 "purchase_rate", "aba_month_rank", "impressions", "clicks"]
RANK_FIELDS = {"aba_week_rank", "aba_month_rank"}
INT_FIELDS = {"aba_week_rank", "aba_month_rank", "product_count",
              "ad_competitor_count", "title_density", "spr", "rating_count",
              "monthly_search_volume", "monthly_purchase_volume",
              "impressions", "clicks"}


def _rng(keyword: str, salt: str = "") -> random.Random:
    h = hashlib.md5(("%s|%s" % (keyword, salt)).encode("utf-8")).hexdigest()
    return random.Random(int(h[:12], 16))


def week_periods():
    out = []
    for i in range(WEEK_PERIODS):
        end = WEEK_LAST_END - dt.timedelta(days=7 * (WEEK_PERIODS - 1 - i))
        out.append((i, (end - dt.timedelta(days=6)).isoformat(), end.isoformat()))
    return out


def month_periods():
    out = []
    y, m = MONTH_LAST
    seq = []
    for _ in range(MONTH_PERIODS):
        seq.append((y, m))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    for i, (yy, mm) in enumerate(reversed(seq)):
        start = dt.date(yy, mm, 1)
        end = (dt.date(yy + (mm == 12), (mm % 12) + 1, 1) - dt.timedelta(days=1))
        out.append((i, start.isoformat(), end.isoformat()))
    return out


def assign_shapes(monitored_buckets: dict) -> dict:
    """确定性地把 7 种形态分给 300 个监控词，优先满足语义匹配的桶。"""
    order = sorted(monitored_buckets, key=lambda k: (monitored_buckets[k], k))
    by_bucket = collections.defaultdict(list)
    for k in order:
        by_bucket[monitored_buckets[k]].append(k)
    cursor = {b: 0 for b in by_bucket}
    taken = set()
    shapes = {}

    def pull(bucket):
        lst = by_bucket.get(bucket, [])
        i = cursor.get(bucket, 0)
        while i < len(lst) and lst[i] in taken:
            i += 1
        cursor[bucket] = i
        if i < len(lst):
            return lst[i]
        return None

    for shape, n, _ in SHAPE_QUOTA:
        got = 0
        for bucket in SHAPE_PREF.get(shape, []):
            while got < n:
                k = pull(bucket)
                if k is None:
                    break
                shapes[k] = shape
                taken.add(k)
                got += 1
        for k in order:                     # 优先桶不够就任取
            if got >= n:
                break
            if k not in taken:
                shapes[k] = shape
                taken.add(k)
                got += 1
    for k in order:
        shapes.setdefault(k, "stable")
    return shapes


def _demand_multipliers(shape: str, n: int, rng: random.Random) -> list[float]:
    """返回长度 n 的需求乘子，最后一格恒为 1.0（末期锚客户原值）。"""
    if shape == "demand_up":
        g = 0.040 + rng.random() * 0.020
        m = [1.0 / ((1.0 + g) ** (n - 1 - i)) for i in range(n)]
    elif shape == "demand_down":
        d = 0.030 + rng.random() * 0.020
        m = [(1.0 + d) ** (n - 1 - i) for i in range(n)]
    else:
        m = [1.0 for _ in range(n)]
    out = []
    for i, v in enumerate(m):
        noise = 1.0 + (rng.random() - 0.5) * (0.03 if shape == "stable_light" else 0.06)
        out.append(v * noise)
    out[-1] = 1.0
    return out


def _competition_multipliers(shape: str, n: int, rng: random.Random) -> list[float]:
    """竞争侧乘子（商品数/广告竞品数/竞价），最后一格恒为 1.0。"""
    if shape == "competition_up":
        g = 0.018 + rng.random() * 0.012
        m = [1.0 / ((1.0 + g) ** (n - 1 - i)) for i in range(n)]
    else:
        m = [1.0 + (rng.random() - 0.5) * 0.04 for _ in range(n)]
    m[-1] = 1.0
    return m


def _purchase_divergence(shape: str, n: int, rng: random.Random) -> list[float]:
    """购买量相对搜索量的偏离乘子，最后一格恒为 1.0。

    没有它，购买量与搜索量同比例缩放 → 购买率恒定不动，页面「搜索需求变化与购买
    表现变化是否一致」这一问就永远只能答「一致」。
    """
    if shape == "demand_up":
        # 流量抓得住、成交跟不上：越靠近末期购买率越低
        k = 0.010 + rng.random() * 0.010
        m = [(1.0 + k) ** (n - 1 - i) for i in range(n)]
    elif shape == "demand_down":
        # 需求在退但转化守住：末期购买率反而更高
        k = 0.008 + rng.random() * 0.008
        m = [1.0 / ((1.0 + k) ** (n - 1 - i)) for i in range(n)]
    else:
        m = [1.0 + (rng.random() - 0.5) * 0.10 for _ in range(n)]
    m[-1] = 1.0
    return m


def _scale(field, base, mult):
    if base is None:
        return None
    if field in RANK_FIELDS:
        v = base / max(mult, 1e-6)          # 需求涨 → 排名变好（数值变小）
        v = max(1.0, v)
    else:
        v = base * mult
    if field in INT_FIELDS:
        return int(round(v))
    return round(v, 4)


def build_snapshots(kw_rows, kw3_by_key, kw2_by_key, monitored_buckets):
    """→ (snapshots, head_asins, shape_map, gate_facts)"""
    weeks = week_periods()
    months = month_periods()
    shape_map = assign_shapes(monitored_buckets)

    snaps = []
    heads = []
    sid = hid = 0

    for r in kw_rows:
        k = r["keyword"]
        kid = r["keyword_id"]
        src3 = kw3_by_key[k]
        shape = shape_map.get(k, "stable_light")
        rng = _rng(k, shape)
        dm_w = _demand_multipliers(shape, WEEK_PERIODS, rng)
        dm_m = _demand_multipliers(shape, MONTH_PERIODS, _rng(k, shape + "m"))
        pdiv = _purchase_divergence(shape, MONTH_PERIODS, _rng(k, shape + "p"))
        cm_w = _competition_multipliers(shape, WEEK_PERIODS, _rng(k, shape + "c"))

        insufficient = shape == "insufficient_history"
        notcmp = shape == "not_comparable"

        # ---- 周频
        for i, pstart, pend in weeks:
            last = i == WEEK_PERIODS - 1
            has_data = 1 if (last or not insufficient or
                             i >= WEEK_PERIODS - INSUFFICIENT_KEEP) else 0
            measure = MEASURE_WEEK_A if (not notcmp or i < NOT_COMPARABLE_AT) else MEASURE_WEEK_B
            cmp_ok = 1
            reason = None
            if i == 0:
                cmp_ok, reason = 0, "首期无上期可比"
            elif notcmp and i == NOT_COMPARABLE_AT:
                cmp_ok, reason = 0, "数据来源口径于本期变更，与上期不可直接比较"
            elif not has_data:
                cmp_ok, reason = 0, "本期暂无数据"
            sid += 1
            row = {
                "snapshot_id": "ks_%07d" % sid,
                "keyword_id": kid,
                "keyword": k,
                "source_file": "关键词3.xlsx",
                "source_code": "kw3",
                "period_type": "week",
                "period_index": i,
                "period_start": pstart,
                "period_end": pend,
                "measure_definition": measure,
                "data_state": "covered" if has_data else "no_data",
                "data_state_label": "有数据" if has_data else "暂无数据",
                "comparable_flag": cmp_ok,
                "comparable_block_reason": reason,
                "change_shape": shape,
                "change_shape_label": SHAPE_LABEL.get(shape, "需求稳定"),
                "value_origin": "customer_real" if last else "synthetic_demo",
            }
            for f in WEEK_METRICS:
                base = src3.get(f)
                if not has_data:
                    row[f] = None
                elif last:
                    row[f] = base
                else:
                    mult = cm_w[i] if f in ("product_count", "ad_competitor_count",
                                            "ppc_bid", "suggested_bid_low",
                                            "suggested_bid_high") else dm_w[i]
                    row[f] = _scale(f, base, mult)
            if has_data and not last and row.get("product_count"):
                sv = src3.get("monthly_search_volume") or 0
                pc = row["product_count"] or 1
                row["demand_supply_ratio"] = round(sv * dm_w[i] / pc, 2)
            snaps.append(row)

        # ---- 月频
        for i, pstart, pend in months:
            last = i == MONTH_PERIODS - 1
            has_data = 1 if (last or not insufficient or
                             i >= MONTH_PERIODS - 3) else 0
            cmp_ok = 1
            reason = None
            if i == 0:
                cmp_ok, reason = 0, "首期无上期可比"
            elif not has_data:
                cmp_ok, reason = 0, "本期暂无数据"
            sid += 1
            row = {
                "snapshot_id": "ks_%07d" % sid,
                "keyword_id": kid,
                "keyword": k,
                "source_file": "关键词3.xlsx",
                "source_code": "kw3",
                "period_type": "month",
                "period_index": i,
                "period_start": pstart,
                "period_end": pend,
                "measure_definition": MEASURE_MONTH,
                "data_state": "covered" if has_data else "no_data",
                "data_state_label": "有数据" if has_data else "暂无数据",
                "comparable_flag": cmp_ok,
                "comparable_block_reason": reason,
                "change_shape": shape,
                "change_shape_label": SHAPE_LABEL.get(shape, "需求稳定"),
                "value_origin": "customer_real" if last else "synthetic_demo",
            }
            for f in MONTH_METRICS:
                base = src3.get(f)
                if last:
                    row[f] = base
                elif not has_data:
                    row[f] = None
                elif f in ("monthly_purchase_volume", "clicks"):
                    row[f] = _scale(f, base, dm_m[i] * pdiv[i])
                else:
                    row[f] = _scale(f, base, dm_m[i])
            if has_data and not last:
                sv, pv = row.get("monthly_search_volume"), row.get("monthly_purchase_volume")
                row["purchase_rate"] = round(pv / sv, 4) if sv else None
            snaps.append(row)

        # ---- 第二来源（关键词2）：只造末期一格，不伪造它的历史
        alt = kw2_by_key.get(k)
        if alt:
            for ptype, pstart, pend, metrics in (
                    ("week", weeks[-1][1], weeks[-1][2], WEEK_METRICS),
                    ("month", months[-1][1], months[-1][2], MONTH_METRICS)):
                sid += 1
                row = {
                    "snapshot_id": "ks_%07d" % sid,
                    "keyword_id": kid, "keyword": k,
                    "source_file": "关键词2.xlsx", "source_code": "kw2",
                    "period_type": ptype,
                    "period_index": (WEEK_PERIODS if ptype == "week" else MONTH_PERIODS) - 1,
                    "period_start": pstart, "period_end": pend,
                    "measure_definition": "第二来源工具估算（字段与口径均与关键词3 不同）",
                    "data_state": "covered", "data_state_label": "有数据",
                    "comparable_flag": 0,
                    "comparable_block_reason": "第二来源仅有当期一格，且与关键词3 口径不同，不做跨来源比较",
                    "change_shape": "single_snapshot",
                    "change_shape_label": "仅当期一格",
                    "value_origin": "customer_real",
                }
                for f in metrics:
                    row[f] = alt.get(f)
                row["traffic_share"] = alt.get("traffic_share")
                row["est_weekly_impressions"] = alt.get("est_weekly_impressions")
                snaps.append(row)

        # ---- 头部 ASIN：末期取客户原值（含前十），监控词往前造 25 期前三
        for h in src3["heads"]:
            hid += 1
            heads.append({
                "head_id": "kh_%07d" % hid, "keyword_id": kid, "keyword": k,
                "period_end": weeks[-1][2], "rank_slot": h["slot"], "asin": h["asin"],
                "click_share": h["click_share"], "conversion_share": h["conv_share"],
                "is_own_asin": 1 if h["asin"] in OWN_ASINS else 0,
                "source_code": "kw3", "value_origin": "customer_real",
            })
        seen = {h["asin"] for h in src3["heads"]}
        for j, a in enumerate([x for x in src3["top10"] if x not in seen], 4):
            if j > 10:
                break
            hid += 1
            heads.append({
                "head_id": "kh_%07d" % hid, "keyword_id": kid, "keyword": k,
                "period_end": weeks[-1][2], "rank_slot": j, "asin": a,
                "click_share": None, "conversion_share": None,
                "is_own_asin": 1 if a in OWN_ASINS else 0,
                "source_code": "kw3", "value_origin": "customer_real",
            })

        if k in monitored_buckets and src3["heads"]:
            hr = _rng(k, "head")
            swap_at = 14
            pool = [x for x in src3["top10"] if x not in seen] or [src3["heads"][-1]["asin"]]
            challenger = pool[hr.randrange(len(pool))]
            for i, _ps, pend in weeks[:-1]:
                for h in src3["heads"]:
                    asin = h["asin"]
                    slot = h["slot"]
                    if shape == "head_replaced" and h["slot"] == 1 and i < swap_at:
                        asin = challenger          # 换人发生在第 15 期
                    drift = 1.0 + (hr.random() - 0.5) * 0.25
                    hid += 1
                    heads.append({
                        "head_id": "kh_%07d" % hid, "keyword_id": kid, "keyword": k,
                        "period_end": pend, "rank_slot": slot, "asin": asin,
                        "click_share": (round(h["click_share"] * drift, 4)
                                        if h["click_share"] is not None else None),
                        "conversion_share": (round(h["conv_share"] * drift, 4)
                                             if h["conv_share"] is not None else None),
                        "is_own_asin": 1 if asin in OWN_ASINS else 0,
                        "source_code": "kw3", "value_origin": "synthetic_demo",
                    })
    return snaps, heads, shape_map


OWN_ASINS: set = set()


def set_own_asins(s):
    global OWN_ASINS
    OWN_ASINS = set(s)


# ------------------------------------------------------------------------ 门禁

def gate_g1(snaps, kw3_by_key, kw2_by_key):
    """末期逐字段等于客户原值，按来源与频率分别校验。"""
    fails = []
    checked = 0
    for r in snaps:
        if r["value_origin"] != "customer_real":
            continue
        src = kw3_by_key if r["source_code"] == "kw3" else kw2_by_key
        base = src.get(r["keyword"])
        if not base:
            continue
        fields = WEEK_METRICS if r["period_type"] == "week" else MONTH_METRICS
        for f in fields:
            if f not in base:
                continue
            if r.get(f) != base.get(f):
                fails.append((r["keyword"], r["source_code"], r["period_type"],
                              f, r.get(f), base.get(f)))
            checked += 1
    return checked, fails


def gate_shapes(snaps, heads, shape_map):
    """形态门禁必须指名到词，不能只报「7 种都有」。"""
    out = []
    by_kw = collections.defaultdict(list)
    for r in snaps:
        if r["source_code"] == "kw3":
            by_kw[(r["keyword"], r["period_type"])].append(r)

    def pick(shape):
        return next((k for k in sorted(shape_map) if shape_map[k] == shape), None)

    # 1 mens underwear 必须 26 格且末期锚真值
    k = "mens underwear"
    rows = sorted(by_kw.get((k, "week"), []), key=lambda r: r["period_index"])
    out.append(("G3-1 mens underwear 周格数=26 且末期为客户原值",
                len(rows) == WEEK_PERIODS and rows and rows[-1]["value_origin"] == "customer_real"
                and rows[-1]["period_end"] == WEEK_LAST_END.isoformat(),
                "%d 格, 末期 %s" % (len(rows), rows[-1]["period_end"] if rows else "-")))

    # 2 口径变更词：恰好一期 comparable_flag=0（除首期）
    k = pick("not_comparable")
    rows = sorted(by_kw.get((k, "week"), []), key=lambda r: r["period_index"])
    blocked = [r["period_index"] for r in rows
               if not r["comparable_flag"] and r["period_index"] != 0]
    out.append(("G3-2 口径变更词 %s 第 %d 期起口径变更且该期不可比" % (k, NOT_COMPARABLE_AT + 1),
                blocked == [NOT_COMPARABLE_AT], "不可比期=%s" % blocked))

    # 3 样本不足词：周频只有 4 期有数
    k = pick("insufficient_history")
    rows = by_kw.get((k, "week"), [])
    got = sum(1 for r in rows if r["data_state"] == "covered")
    out.append(("G3-3 样本不足词 %s 周频只有 %d 期有数" % (k, INSUFFICIENT_KEEP),
                got == INSUFFICIENT_KEEP, "有数期=%d/%d" % (got, len(rows))))

    # 4 头部替换词：首期与末期 slot1 不同
    k = pick("head_replaced")
    hr = [h for h in heads if h["keyword"] == k and h["rank_slot"] == 1]
    ends = sorted({h["period_end"] for h in hr})
    a0 = next((h["asin"] for h in hr if h["period_end"] == ends[0]), None)
    a1 = next((h["asin"] for h in hr if h["period_end"] == ends[-1]), None)
    out.append(("G3-4 头部替换词 %s 首末期 #1 ASIN 不同" % k,
                bool(a0 and a1 and a0 != a1), "%s → %s" % (a0, a1)))

    # 5 需求上涨词：末期显著高于首期
    k = pick("demand_up")
    rows = sorted(by_kw.get((k, "month"), []), key=lambda r: r["period_index"])
    v0 = rows[0].get("monthly_search_volume") if rows else None
    v1 = rows[-1].get("monthly_search_volume") if rows else None
    out.append(("G3-5 需求上涨词 %s 末期月搜索量 > 首期 1.5 倍" % k,
                bool(v0 and v1 and v1 > v0 * 1.5), "%s → %s" % (v0, v1)))

    # 6 需求下滑词：末期显著低于首期
    k = pick("demand_down")
    rows = sorted(by_kw.get((k, "month"), []), key=lambda r: r["period_index"])
    v0 = rows[0].get("monthly_search_volume") if rows else None
    v1 = rows[-1].get("monthly_search_volume") if rows else None
    out.append(("G3-6 需求下滑词 %s 末期月搜索量 < 首期 0.8 倍" % k,
                bool(v0 and v1 and v1 < v0 * 0.8), "%s → %s" % (v0, v1)))

    # 7 竞争加剧词：末期商品数 > 首期
    k = pick("competition_up")
    rows = sorted(by_kw.get((k, "week"), []), key=lambda r: r["period_index"])
    v0 = rows[0].get("product_count") if rows else None
    v1 = rows[-1].get("product_count") if rows else None
    out.append(("G3-7 竞争加剧词 %s 末期商品数 > 首期" % k,
                bool(v0 and v1 and v1 > v0), "%s → %s" % (v0, v1)))

    # 8 购买率必须真的会动（否则「搜索变化与购买表现是否一致」永远只能答一致）
    k = pick("demand_up")
    rows = sorted(by_kw.get((k, "month"), []), key=lambda r: r["period_index"])
    rates = [r.get("purchase_rate") for r in rows if r.get("purchase_rate")]
    spread = (max(rates) - min(rates)) / max(rates) if rates else 0
    out.append(("G3-8 需求上涨词 %s 购买率 12 期极差 > 5%%（搜索涨而成交跟不上）" % k,
                spread > 0.05, "购买率 %.4f→%.4f 极差 %.1f%%"
                % (rates[0], rates[-1], spread * 100) if rates else "无数据"))

    # 9 双来源冲突必须真的存在
    src2 = [r for r in snaps if r["source_code"] == "kw2" and r["period_type"] == "week"]
    conflict = 0
    for r in src2:
        m = next((x for x in by_kw.get((r["keyword"], "week"), [])
                  if x["period_index"] == WEEK_PERIODS - 1), None)
        if m and r.get("ad_competitor_count") != m.get("ad_competitor_count"):
            conflict += 1
    out.append(("G3-9 双来源广告竞品数存在真实冲突的词数 ≥ 100",
                conflict >= 100, "冲突词数=%d" % conflict))
    return out
