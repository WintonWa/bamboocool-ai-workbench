#!/usr/bin/env python3
"""关键词模块 Demo 数据构建 — 源读取层与选样层（只读客户文件与 v0.3.0）。

三个客户关键词文件 + v0.3.0 产品包 → 标准化 Python 结构 + 确定性选样（300 词 / 30 子 ASIN）。
本模块从不写入任何源文件。
"""
from __future__ import annotations

import collections
import html.parser
import os
import re
import sqlite3
import sys
import unicodedata
import zipfile

# 复用广告模块已验证的 stdlib+lxml xlsx 读取器（/usr/bin/python3 是本机唯一带 lxml 的解释器）
AD_PROBE = "/Users/linsen/BAM/04-广告分析模块/00-源表勘查"
if AD_PROBE not in sys.path:
    sys.path.insert(0, AD_PROBE)
import xlsxlite as X  # noqa: E402

KW_DIR = "/Users/linsen/BAM/数据源/AI广告对接数据-总20260803/10.关键词"
V030_DB = ("/Users/linsen/BAM/02-产品销售库存模块/02-数据构建/"
           "v0.3.0/bamboocool_product_sales_inventory_v0.3.0.sqlite")

SITE = "US"
PRODUCT_LINE = "BAMBOO COOL 男士内衣"
OWN_BRAND = "BAMBOO COOL"
AS_OF = "2026-08-03"

ASIN_RE = re.compile(r"B0[A-Z0-9]{8}")
NUM_RE = re.compile(r"-?\d[\d,]*\.?\d*")

KW3 = "关键词3.xlsx"
KW2 = "关键词2.xlsx"
KW1 = "关键词1.html"


# --------------------------------------------------------------------------- 工具

def norm_keyword(text: str) -> str:
    """标准化关键词写法：NFKC、弯引号转直引号、小写、压空白。保留原写法由调用方负责。"""
    if text is None:
        return ""
    s = unicodedata.normalize("NFKC", str(text))
    s = s.replace("\u2019", "'").replace("\u2018", "'")
    s = s.replace("\u201c", '"').replace("\u201d", '"')
    s = s.lower()
    s = re.sub(r"\s+", " ", s).strip()
    return s


def alias_key(text: str) -> str:
    """别名归并键：在标准化之上再去掉撇号与常见拼写差异，用于把变体聚到同一标准词。"""
    s = norm_keyword(text)
    s = s.replace("'", "")
    s = s.replace("underware", "underwear").replace("undewear", "underwear")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def to_num(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = NUM_RE.search(str(v).replace("$", ""))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def to_int(v):
    n = to_num(v)
    return None if n is None else int(round(n))


def money_range(v):
    """'$2.28-$3.43' / '$2.28 - $3.43' → (2.28, 3.43)"""
    if not v:
        return (None, None)
    nums = [float(x.replace(",", "")) for x in NUM_RE.findall(str(v))]
    if len(nums) >= 2:
        return (nums[0], nums[1])
    if len(nums) == 1:
        return (nums[0], nums[0])
    return (None, None)


def split_tags(v):
    if not v:
        return []
    parts = re.split(r"[,\u3001/|]", str(v))
    return [p.strip() for p in parts if p and p.strip()]


_EMOJI_RE = re.compile(
    "[" "\U0001F300-\U0001FAFF" "\U00002600-\U000027BF"
    "\U0000FE0F" "\U00002B00-\U00002BFF" "]+")


def clean_label(text: str) -> str:
    """去掉 emoji 与首尾符号，返回可直接上屏的中文短标签。"""
    if not text:
        return ""
    s = _EMOJI_RE.sub("", str(text))
    s = re.sub(r"\s+", " ", s).strip(" -—·|")
    return s.strip()


def _sheet_index(path: str, name: str):
    zf = zipfile.ZipFile(path)
    for i, (sname, _) in enumerate(X.sheets(zf)):
        if sname == name:
            return i
    return None


def read_sheet(path: str, name: str):
    """返回 (header:list[str], rows:list[dict])。"""
    idx = _sheet_index(path, name)
    if idx is None:
        return [], []
    raw = list(X.iter_rows(path, sheet_index=idx))
    if not raw:
        return [], []
    hdr = [str(c).strip() if c is not None else "" for c in raw[0]]
    out = []
    for r in raw[1:]:
        if not any(c not in (None, "") for c in r):
            continue
        d = {}
        for i, h in enumerate(hdr):
            d[h] = r[i] if i < len(r) else None
        out.append(d)
    return hdr, out


# --------------------------------------------------------------- 关键词3（主底图）

KW3_SHEET = "全量关键词(含分类)"


def read_kw3():
    path = os.path.join(KW_DIR, KW3)
    _, rows = read_sheet(path, KW3_SHEET)
    out = []
    for r in rows:
        kw_raw = r.get("关键词")
        if not kw_raw:
            continue
        heads = []
        for slot in (1, 2, 3):
            a = r.get("#%d 前三ASIN" % slot)
            cs = r.get("#%d 点击共享" % slot) if slot != 1 else r.get("#1 点击共享")
            vs = (r.get("#1转化共享") if slot == 1
                  else r.get("#%d 转化共享" % slot))
            if a:
                heads.append({"slot": slot, "asin": str(a).strip(),
                              "click_share": to_num(cs), "conv_share": to_num(vs)})
        top10 = ASIN_RE.findall(str(r.get("前十ASIN") or ""))
        lo, hi = money_range(r.get("建议竞价范围"))
        out.append({
            "keyword_raw": str(kw_raw).strip(),
            "keyword": norm_keyword(kw_raw),
            "alias_key": alias_key(kw_raw),
            "keyword_cn": (str(r.get("关键词翻译")).strip()
                           if r.get("关键词翻译") else None),
            "primary_category": (str(r.get("主要分类")).strip()
                                 if r.get("主要分类") else None),
            "all_category_tags": split_tags(r.get("所有分类标签")),
            "ac_recommended": 1 if str(r.get("AC推荐词") or "").strip().upper() == "Y" else 0,
            "relevance": to_num(r.get("相关度")),
            "aba_month_rank": to_int(r.get("ABA月排名")),
            "aba_week_rank": to_int(r.get("ABA周排名")),
            "monthly_search_volume": to_int(r.get("月搜索量")),
            "monthly_purchase_volume": to_int(r.get("月购买量")),
            "purchase_rate": to_num(r.get("购买率")),
            "impressions": to_int(r.get("展示量")),
            "clicks": to_int(r.get("点击量")),
            "spr": to_int(r.get("SPR")),
            "title_density": to_int(r.get("标题密度")),
            "product_count": to_int(r.get("商品数")),
            "demand_supply_ratio": to_num(r.get("需供比")),
            "ad_competitor_count": to_int(r.get("广告竞品数")),
            "click_share_top3": to_num(r.get("点击总占比")),
            "conv_share_top3": to_num(r.get("转化总占比")),
            "ppc_bid": to_num(r.get("PPC竞价")),
            "suggested_bid_low": lo,
            "suggested_bid_high": hi,
            "avg_price": to_num(r.get("均价")),
            "rating_count": to_int(r.get("评分数")),
            "rating": to_num(r.get("评分值")),
            "category_path": (str(r.get("所属类目")).strip()
                              if r.get("所属类目") else None),
            "heads": heads,
            "top10": top10,
        })
    return out


def read_kw3_overview():
    """总览 sheet 的 12 行分类汇总 —— G2 回归基线。"""
    path = os.path.join(KW_DIR, KW3)
    _, rows = read_sheet(path, "总览")
    out = []
    for r in rows:
        name = r.get("分类名称")
        if not name:
            continue
        out.append({
            "category_name": str(name).strip(),
            "keyword_count": to_int(r.get("关键词数量")),
            "share_text": (str(r.get("占比")).strip() if r.get("占比") else None),
            "monthly_search_sum": to_int(r.get("月搜索量合计")),
            "monthly_purchase_sum": to_int(r.get("月购买量合计")),
            "avg_purchase_rate_text": (str(r.get("平均购买率")).strip()
                                       if r.get("平均购买率") else None),
        })
    return out


# ----------------------------------------------------------- 关键词2（第二来源）

def read_kw2():
    path = os.path.join(KW_DIR, KW2)
    _, rows = read_sheet(path, "全量明细")
    out = []
    for r in rows:
        kw_raw = r.get("关键词")
        if not kw_raw:
            continue
        heads = []
        for slot in (1, 2, 3):
            a = r.get("#%d 前三ASIN" % slot)
            if a:
                heads.append({"slot": slot, "asin": str(a).strip(),
                              "click_share": to_num(r.get("#%d 点击共享" % slot)),
                              "conv_share": to_num(r.get("#%d 转化共享" % slot))})
        lo, hi = money_range(r.get("建议竞价范围"))
        out.append({
            "keyword_raw": str(kw_raw).strip(),
            "keyword": norm_keyword(kw_raw),
            "alias_key": alias_key(kw_raw),
            "keyword_cn": (str(r.get("关键词翻译")).strip()
                           if r.get("关键词翻译") else None),
            "traffic_share": to_num(r.get("流量占比")),
            "traffic_word_type": (str(r.get("流量词类型")).strip()
                                  if r.get("流量词类型") else None),
            "est_weekly_impressions": to_int(r.get("预估周曝光量")),
            "related_product_count": to_int(r.get("相关产品")),
            "related_asins": ASIN_RE.findall(str(r.get("相关ASIN") or "")),
            "aba_week_rank": to_int(r.get("ABA周排名")),
            "monthly_search_volume": to_int(r.get("月搜索量")),
            "monthly_purchase_volume": to_int(r.get("月购买量")),
            "purchase_rate": to_num(r.get("购买率")),
            "impressions": to_int(r.get("展示量")),
            "clicks": to_int(r.get("点击量")),
            "spr": to_int(r.get("SPR")),
            "title_density": to_int(r.get("标题密度")),
            "product_count": to_int(r.get("商品数")),
            "demand_supply_ratio": to_num(r.get("需供比")),
            "ad_competitor_count": to_int(r.get("广告竞品数")),
            "click_share_top3": to_num(r.get("点击总占比")),
            "conv_share_top3": to_num(r.get("转化总占比")),
            "ppc_bid": to_num(r.get("PPC竞价")),
            "suggested_bid_low": lo,
            "suggested_bid_high": hi,
            "category_tags_alt": split_tags(r.get("分类")),
            "matched_brand": (str(r.get("匹配品牌")).strip()
                              if r.get("匹配品牌") else None),
            "heads": heads,
            "top10": ASIN_RE.findall(str(r.get("前十ASIN") or "")),
        })
    return out


def read_kw2_brand_distribution():
    path = os.path.join(KW_DIR, KW2)
    _, rows = read_sheet(path, "品牌分布")
    out = []
    for r in rows:
        b = r.get("品牌")
        if not b:
            continue
        out.append({
            "brand": str(b).strip(),
            "keyword_count": to_int(r.get("关键词数")),
            "sample_keywords": str(r.get("代表关键词(前10)") or "").strip(),
        })
    return out


# --------------------------------------------- 关键词1（运营构词矩阵 + 角色种子）

class _TableGrab(html.parser.HTMLParser):
    """抓 <table> 及其前面最近的标题文本。"""

    HEADINGS = {"h1", "h2", "h3", "h4", "h5", "caption"}

    def __init__(self):
        super().__init__()
        self.tables = []
        self._cur = None
        self._row = None
        self._cell = None
        self._heading_buf = None
        self._last_heading = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._cur = []
        elif tag == "tr" and self._cur is not None:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []
        elif tag in self.HEADINGS:
            self._heading_buf = []

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data.strip())
        elif self._heading_buf is not None:
            self._heading_buf.append(data.strip())

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None:
            self._row.append(" ".join(x for x in self._cell if x))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if any(self._row):
                self._cur.append(self._row)
            self._row = None
        elif tag == "table" and self._cur is not None:
            self.tables.append((self._last_heading, self._cur))
            self._cur = None
        elif tag in self.HEADINGS and self._heading_buf is not None:
            txt = " ".join(x for x in self._heading_buf if x).strip()
            if txt:
                self._last_heading = txt
            self._heading_buf = None


_ABA_CELL = re.compile(r"#(\d+)\s*(Top 5K|[\d.]+K-[\d.]+K|[\d.]+K\+)?\s*([\d,]+)?")

PRIORITY_MAP = {"S必投": "S", "A重要": "A", "B补充": "B"}


def read_kw1():
    """→ (attr_rows, dimensions)。attr_rows 每行一个属性词，含运营优先级与两个核心词的组合词。"""
    path = os.path.join(KW_DIR, KW1)
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        raw = fh.read()
    p = _TableGrab()
    p.feed(raw)

    attr_rows = []
    dims = []
    for t_no, (heading, table) in enumerate(p.tables, 1):
        if not table or len(table[0]) < 6:
            continue
        hdr = table[0]
        core_a = re.sub(r"^[^\w]*搭配\s*", "", clean_label(hdr[2])).strip()
        core_b = re.sub(r"^[^\w]*搭配\s*", "", clean_label(hdr[4])).strip()
        dim_full = clean_label(heading) or ("属性维度%d" % t_no)
        # "材质词 Material" → 中文标签 + 英文代码
        m = re.match(r"^(.*?)\s*([A-Za-z][A-Za-z /]*)$", dim_full)
        dim_name = (m.group(1).strip() if m else dim_full)
        dim_code = (m.group(2).strip().lower().replace(" / ", "_").replace(" ", "_")
                    if m else "dim%d" % t_no)
        dims.append({"table_no": t_no, "dimension": dim_name, "dimension_code": dim_code,
                     "core_a": core_a, "core_b": core_b, "row_count": len(table) - 1})
        for r in table[1:]:
            if len(r) < 6 or not r[0]:
                continue
            word = r[0].strip()
            starred = 1 if "★" in word else 0
            word = word.replace("★", "").strip()
            pri_raw = r[1].strip()
            combos = []
            for combo_cell, aba_cell, core in ((r[2], r[3], core_a), (r[4], r[5], core_b)):
                combo = re.sub(r"^组合词\s*", "", combo_cell or "").strip()
                slot = bucket = imps = None
                if aba_cell and "无数据" not in aba_cell:
                    m = _ABA_CELL.search(aba_cell)
                    if m:
                        slot = int(m.group(1))
                        bucket = m.group(2)
                        imps = to_int(m.group(3))
                combos.append({"core_keyword": core, "combo_keyword": combo,
                               "aba_slot": slot, "volume_bucket": bucket,
                               "impressions": imps,
                               "has_data": 0 if slot is None else 1})
            attr_rows.append({
                "table_no": t_no,
                "dimension": dim_name,
                "dimension_code": dim_code,
                "attribute_word": word,
                "attribute_key": norm_keyword(word),
                "is_starred": starred,
                "priority_raw": pri_raw,
                "priority": PRIORITY_MAP.get(pri_raw, None),
                "combos": combos,
            })
    return attr_rows, dims


# ------------------------------------------------------------------ v0.3.0 产品侧

def read_v030_children():
    con = sqlite3.connect("file:%s?mode=ro" % V030_DB, uri=True)
    rows = con.execute(
        "select child_asin, parent_asin, product_name, style_name, style_no, "
        "       colorway, size, combination, category, category_rank, rating, "
        "       operations_group, operator, goods_status, product_lifecycle "
        "from dim_product_child").fetchall()
    cols = ["child_asin", "parent_asin", "product_name", "style_name", "style_no",
            "colorway", "size", "combination", "category", "category_rank", "rating",
            "operations_group", "operator", "goods_status", "product_lifecycle"]
    out = [dict(zip(cols, r)) for r in rows]
    con.close()
    return out


def read_v030_golden():
    con = sqlite3.connect("file:%s?mode=ro" % V030_DB, uri=True)
    rows = con.execute(
        "select profile_id, profile_name, description, lifecycle, "
        "       golden_child_asin, parent_asin from dim_demo_profile").fetchall()
    con.close()
    return [dict(zip(["profile_id", "profile_name", "description", "lifecycle",
                      "golden_child_asin", "parent_asin"], r)) for r in rows]


def read_v030_inventory_decision():
    con = sqlite3.connect("file:%s?mode=ro" % V030_DB, uri=True)
    rows = con.execute(
        "select child_asin, base_risk_status, safety_breach_date, base_stockout_date, "
        "       stress_stockout_date, latest_order_date, suggested_replenishment_qty, "
        "       projected_lost_sales_units, dynamic_safety_days, decision_summary, "
        "       confidence_score from fact_child_inventory_decision").fetchall()
    cols = ["child_asin", "base_risk_status", "safety_breach_date", "base_stockout_date",
            "stress_stockout_date", "latest_order_date", "suggested_replenishment_qty",
            "projected_lost_sales_units", "dynamic_safety_days", "decision_summary",
            "confidence_score"]
    con.close()
    return {r[0]: dict(zip(cols, r)) for r in rows}


def read_v030_daily_caps(child_asins, date_from, date_to):
    """G3/G4 的分母：逐日 sessions 与广告 clicks / spend。"""
    if not child_asins:
        return {}
    ph = ",".join("?" * len(child_asins))
    args = list(child_asins) + [date_from, date_to]
    con = sqlite3.connect("file:%s?mode=ro" % V030_DB, uri=True)
    caps = collections.defaultdict(dict)
    for asin, d, sess, pv in con.execute(
            "select child_asin, date, sessions, page_views from fact_child_traffic_daily "
            "where child_asin in (%s) and date between ? and ?" % ph, args):
        caps[(asin, d)]["sessions"] = sess or 0
        caps[(asin, d)]["page_views"] = pv or 0
    for asin, d, clicks, spend, imps in con.execute(
            "select child_asin, date, clicks, ad_spend, impressions "
            "from fact_child_advertising_daily "
            "where child_asin in (%s) and date between ? and ?" % ph, args):
        caps[(asin, d)]["clicks"] = clicks or 0
        caps[(asin, d)]["ad_spend"] = spend or 0.0
        caps[(asin, d)]["ad_impressions"] = imps or 0
    con.close()
    return dict(caps)


# ------------------------------------------------------------------------ 选样层

MONITOR_TARGET = 300
CHILD_TARGET = 30

# 300 词的配额（确定性，写死在这里，便于门禁复核）
QUOTAS = [
    ("core_big", 40, "核心大词：自有 ASIN 在前三且月搜索量最高"),
    ("gap_no_coverage", 40, "零覆盖缺口词：相关度高但自有 ASIN 完全不在榜"),
    ("own_brand", 25, "自有品牌词：匹配品牌 = BAMBOO COOL"),
    ("competitor_brand", 30, "竞品品牌词：匹配品牌非空且不等于自有品牌"),
    ("attribute", 45, "属性/功能/材质词：来自关键词1 的 S必投 / A重要 种子"),
    ("scene", 30, "场景/节日/季节词"),
    ("size_color_qty", 20, "尺码/颜色/数量词"),
    ("longtail_high_cvr", 35, "长尾高转化：购买率高且月搜索量小"),
    ("noise", 20, "噪声/跨类目词：相关度低"),
    ("variant", 15, "拼写变体族：同一 alias_key 下的多种写法"),
]

DIM_SCENE = {"场景", "节日", "季节"}
DIM_SIZE = {"尺码", "颜色", "数量"}
DIM_ATTR = {"材质", "功能", "属性", "款式"}

# 选样时实际用到的分位数切点，构建后写进 manifest 供门禁复核
SELECTION_CUTS: dict = {}


def select_children(children, coverage_counts, golden):
    """30 个子 ASIN：5 个黄金场景 + 覆盖最富的交集子体 + 零覆盖子体（覆盖全部父体）。"""
    by_asin = {c["child_asin"]: c for c in children}
    golden_asins = [g["golden_child_asin"] for g in golden
                    if g["golden_child_asin"] in by_asin]

    picked = list(golden_asins)
    # 覆盖最富的交集子体
    ranked = sorted((a for a in coverage_counts if a in by_asin),
                    key=lambda a: (-coverage_counts[a], a))
    for a in ranked:
        if len(picked) >= 22:
            break
        if a not in picked:
            picked.append(a)

    # 零覆盖子体，按父体轮转补齐，保证 5 个父体都在
    parents_present = {by_asin[a]["parent_asin"] for a in picked}
    zero = [c["child_asin"] for c in sorted(children, key=lambda c: c["child_asin"])
            if coverage_counts.get(c["child_asin"], 0) == 0 and c["child_asin"] not in picked]
    all_parents = sorted({c["parent_asin"] for c in children})
    for p in all_parents:
        if p in parents_present:
            continue
        for a in zero:
            if by_asin[a]["parent_asin"] == p:
                picked.append(a)
                parents_present.add(p)
                break
    by_parent = collections.defaultdict(list)
    for a in zero:
        by_parent[by_asin[a]["parent_asin"]].append(a)
    cursor = {p: 0 for p in all_parents}
    while len(picked) < CHILD_TARGET:
        progressed = False
        for p in all_parents:
            if len(picked) >= CHILD_TARGET:
                break
            lst = by_parent.get(p, [])
            i = cursor[p]
            while i < len(lst) and lst[i] in picked:
                i += 1
            if i < len(lst):
                picked.append(lst[i])
                cursor[p] = i + 1
                progressed = True
        if not progressed:
            break
    return picked[:CHILD_TARGET]


def select_keywords(kw3_rows, kw2_by_key, attr_seed_keys, own_asins, coverage_by_kw):
    """确定性挑 300 个监控词，返回 {keyword_key: bucket_name}。"""
    picked = {}
    order = {r["keyword"]: i for i, r in enumerate(kw3_rows)}

    def take(bucket, candidates, n):
        cnt = 0
        for k in candidates:
            if cnt >= n:
                break
            if k in picked:
                continue
            picked[k] = bucket
            cnt += 1
        return cnt

    def sv(k):
        return kw3_by_key[k].get("monthly_search_volume") or 0

    kw3_by_key = {r["keyword"]: r for r in kw3_rows}

    def sort_key(k, desc_field="monthly_search_volume"):
        return (-(kw3_by_key[k].get(desc_field) or 0), order[k])

    keys = list(kw3_by_key)

    # 1 核心大词
    core = [k for k in keys if coverage_by_kw.get(k, {}).get("top3")]
    core.sort(key=lambda k: sort_key(k))
    take("core_big", core, 40)

    # 2 零覆盖缺口词（必须早于属性/场景桶，否则会被抢空）
    # 相关度实测中位数仅 11.7、最大 100，不是均匀分布 → 用分位数而非固定阈值
    rel_vals = sorted((kw3_by_key[k].get("relevance") or 0.0) for k in keys)
    rel_hi = rel_vals[int(len(rel_vals) * 0.75)]   # 相关度上四分位
    rel_lo = rel_vals[int(len(rel_vals) * 0.10)]   # 相关度最低一成
    SELECTION_CUTS["relevance_p75"] = rel_hi
    SELECTION_CUTS["relevance_p10"] = rel_lo
    gap = [k for k in keys
           if not coverage_by_kw.get(k, {}).get("top10")
           and (kw3_by_key[k].get("relevance") or 0) >= rel_hi]
    gap.sort(key=lambda k: (-(kw3_by_key[k].get("relevance") or 0),
                            -(kw3_by_key[k].get("monthly_search_volume") or 0), order[k]))
    take("gap_no_coverage", gap, 40)

    # 3/4 品牌词
    own_b, comp_b = [], []
    for k in keys:
        brand = (kw2_by_key.get(k) or {}).get("matched_brand")
        if not brand:
            continue
        if brand.strip().upper() == OWN_BRAND:
            own_b.append(k)
        else:
            comp_b.append(k)
    own_b.sort(key=lambda k: sort_key(k))
    comp_b.sort(key=lambda k: sort_key(k))
    take("own_brand", own_b, 25)
    take("competitor_brand", comp_b, 30)

    # 4 属性词（关键词1 种子命中）
    attr = [k for k in keys
            if any(a and a in k for a in attr_seed_keys)
            or (set(kw3_by_key[k]["all_category_tags"]) & DIM_ATTR)]
    attr.sort(key=lambda k: sort_key(k))
    take("attribute", attr, 45)

    # 5 场景/节日/季节
    scene = [k for k in keys if set(kw3_by_key[k]["all_category_tags"]) & DIM_SCENE]
    scene.sort(key=lambda k: sort_key(k))
    take("scene", scene, 30)

    # 6 尺码/颜色/数量
    scq = [k for k in keys if set(kw3_by_key[k]["all_category_tags"]) & DIM_SIZE]
    scq.sort(key=lambda k: sort_key(k))
    take("size_color_qty", scq, 20)

    # 7 长尾高转化
    lt = [k for k in keys
          if (kw3_by_key[k].get("purchase_rate") or 0) >= 0.08
          and 0 < (kw3_by_key[k].get("monthly_search_volume") or 0) < 20000]
    lt.sort(key=lambda k: (-(kw3_by_key[k].get("purchase_rate") or 0), order[k]))
    take("longtail_high_cvr", lt, 35)

    # 8 零覆盖缺口词 —— 已在第 2 步取过

    # 9 噪声词：相关度最低一成
    noise = [k for k in keys if (kw3_by_key[k].get("relevance") or 0) <= rel_lo]
    noise.sort(key=lambda k: ((kw3_by_key[k].get("relevance") or 0), order[k]))
    take("noise", noise, 20)

    # 10 拼写变体族
    fam = collections.defaultdict(list)
    for k in keys:
        fam[kw3_by_key[k]["alias_key"]].append(k)
    var = []
    for ak in sorted(fam):
        grp = sorted(fam[ak], key=lambda k: sort_key(k))
        if len(grp) > 1:
            var.extend(grp)
    take("variant", var, 15)

    # 补齐到 300：按月搜索量降序补，桶名标 fill
    if len(picked) < MONITOR_TARGET:
        rest = [k for k in keys if k not in picked]
        rest.sort(key=lambda k: sort_key(k))
        take("fill", rest, MONITOR_TARGET - len(picked))
    return picked


def coverage_from_kw3(kw3_rows, own_asins):
    """从头部/前十字段反推「当期覆盖截面」。"""
    cov_by_kw = {}
    cnt_by_child = collections.Counter()
    for r in kw3_rows:
        top3 = {h["asin"] for h in r["heads"]} & own_asins
        top10 = (set(r["top10"]) | {h["asin"] for h in r["heads"]}) & own_asins
        if top3 or top10:
            cov_by_kw[r["keyword"]] = {"top3": sorted(top3), "top10": sorted(top10)}
        for a in top10:
            cnt_by_child[a] += 1
    return cov_by_kw, cnt_by_child


def load_all():
    """一次性加载全部源，返回一个 dict。"""
    kw3 = read_kw3()
    kw2 = read_kw2()
    attr_rows, dims = read_kw1()
    children = read_v030_children()
    own = {c["child_asin"] for c in children}
    cov_by_kw, cov_by_child = coverage_from_kw3(kw3, own)
    dup = collections.Counter(r["keyword"] for r in kw3)
    dup_keys = sorted(k for k, n in dup.items() if n > 1)
    return {
        "kw3": kw3,
        "kw3_dup_keys": dup_keys,
        "kw3_overview": read_kw3_overview(),
        "kw2": kw2,
        "kw2_by_key": {r["keyword"]: r for r in kw2},
        "kw2_brands": read_kw2_brand_distribution(),
        "kw1_attrs": attr_rows,
        "kw1_dims": dims,
        "children": children,
        "own_asins": own,
        "golden": read_v030_golden(),
        "inv_decision": read_v030_inventory_decision(),
        "coverage_by_kw": cov_by_kw,
        "coverage_by_child": cov_by_child,
    }


if __name__ == "__main__":
    S = load_all()
    print("关键词3: %d 行 / %d 唯一词（重复写法 %d 组: %s）"
          % (len(S["kw3"]), len({r["keyword"] for r in S["kw3"]}),
             len(S["kw3_dup_keys"]), ", ".join(S["kw3_dup_keys"][:5]) or "无"))
    print("关键词3 总览基线: %d 行" % len(S["kw3_overview"]))
    print("关键词2: %d 词  品牌分布: %d 品牌" % (len(S["kw2"]), len(S["kw2_brands"])))
    print("关键词1: %d 属性词 / %d 维度" % (len(S["kw1_attrs"]), len(S["kw1_dims"])))
    print("  维度: %s" % ", ".join("%s(%d)" % (d["dimension"], d["row_count"])
                                   for d in S["kw1_dims"]))
    prio = collections.Counter(a["priority_raw"] for a in S["kw1_attrs"])
    print("  优先级分布: %s  ★=%d"
          % (dict(prio), sum(a["is_starred"] for a in S["kw1_attrs"])))
    print("v0.3.0 子体: %d  交集子体: %d  含自有ASIN的词: %d"
          % (len(S["children"]), len(S["coverage_by_child"]), len(S["coverage_by_kw"])))

    kids = select_children(S["children"], S["coverage_by_child"], S["golden"])
    print("\n== 选中 30 个子 ASIN ==")
    meta = {c["child_asin"]: c for c in S["children"]}
    for a in kids:
        print("  %-12s %-12s %-14s cov=%-4d %s"
              % (a, meta[a]["parent_asin"], meta[a]["style_no"] or "",
                 S["coverage_by_child"].get(a, 0), meta[a]["product_lifecycle"] or ""))
    par = collections.Counter(meta[a]["parent_asin"] for a in kids)
    print("  父体分布: %s" % dict(par))

    seeds = {a["attribute_key"] for a in S["kw1_attrs"]
             if a["priority"] in ("S", "A")}
    picked = select_keywords(S["kw3"], S["kw2_by_key"], seeds, S["own_asins"],
                             S["coverage_by_kw"])
    print("\n== 选中 %d 个监控词 ==" % len(picked))
    for b, n, desc in QUOTAS + [("fill", 0, "补齐")]:
        got = sum(1 for v in picked.values() if v == b)
        if got:
            print("  %-18s %3d/%-3d  %s" % (b, got, n, desc))
