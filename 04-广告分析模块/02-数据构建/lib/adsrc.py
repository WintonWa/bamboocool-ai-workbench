#!/usr/bin/env python3
"""Source readers and value parsers for the Bamboocool advertising demo build.

Read-only against the customer's report files. Handles:
  - per-file encoding detection (some csv are GBK, some UTF-8-BOM)
  - Amazon money / percent / date formats
  - the operator's campaign naming convention (real signal, not invented)
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import os
import re
import zipfile

from lxml import etree

M = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS = {"m": M, "r": R}

SRC_ROOT = "/Users/linsen/BAM/数据源/AI广告对接数据-总20260803"
AD_DIR = os.path.join(SRC_ROOT, "13.广告")

_EPOCH = dt.date(1899, 12, 30)
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}


# ---------------------------------------------------------------- value parsing

def parse_money(v) -> float | None:
    """'$2,365.78  ' -> 2365.78 ; '' -> None"""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "").replace("$", "").replace("\u00a0", "")
    if not s or s in {"-", "--", "N/A", "NA"}:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_pct(v) -> float | None:
    """'0.37%' -> 0.0037 ; 0.0037 -> 0.0037 ; '' -> None"""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "").replace("\u00a0", "")
    if not s or s in {"-", "--", "N/A", "NA"}:
        return None
    if s.endswith("%"):
        try:
            return float(s[:-1]) / 100.0
        except ValueError:
            return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_int(v) -> int | None:
    f = parse_money(v)
    return None if f is None else int(round(f))


def parse_date(v) -> str | None:
    """Normalise every date shape seen in these reports to ISO yyyy-mm-dd.

    Handles Excel serials, '1-Jul-26', 'Jul 1, 2026', '2026-07-01', '2026/07/01'.
    """
    if v is None:
        return None
    if isinstance(v, (int, float)):
        n = float(v)
        if 1 <= n <= 80000:
            return (_EPOCH + dt.timedelta(days=int(n))).isoformat()
        return None
    s = str(v).strip()
    if not s:
        return None
    # 2026-07-01 / 2026/07/01
    m = re.match(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})", s)
    if m:
        return "%04d-%02d-%02d" % tuple(int(g) for g in m.groups())
    # 1-Jul-26  /  1-Jul-2026
    m = re.match(r"^(\d{1,2})-([A-Za-z]{3})-(\d{2,4})$", s)
    if m:
        d, mon, y = int(m.group(1)), _MONTHS.get(m.group(2).title()), int(m.group(3))
        if mon:
            y = y + 2000 if y < 100 else y
            return "%04d-%02d-%02d" % (y, mon, d)
    # Jul 1, 2026
    m = re.match(r"^([A-Za-z]{3})[a-z]*\s+(\d{1,2}),\s*(\d{4})$", s)
    if m:
        mon = _MONTHS.get(m.group(1).title())
        if mon:
            return "%04d-%02d-%02d" % (int(m.group(3)), mon, int(m.group(2)))
    # bare serial as text
    try:
        n = float(s)
        if 1 <= n <= 80000:
            return (_EPOCH + dt.timedelta(days=int(n))).isoformat()
    except ValueError:
        pass
    return None


# ------------------------------------------------------------------ xlsx reader

def _shared_strings(zf: zipfile.ZipFile) -> list[str]:
    try:
        data = zf.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = etree.fromstring(data)
    return ["".join(t.text or "" for t in si.iter(f"{{{M}}}t"))
            for si in root.findall("m:si", NS)]


def _sheet_paths(zf: zipfile.ZipFile) -> list[str]:
    wb = etree.fromstring(zf.read("xl/workbook.xml"))
    rels = etree.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    rid = {rel.get("Id"): rel.get("Target") for rel in rels}
    out = []
    for sh in wb.find("m:sheets", NS):
        t = rid.get(sh.get(f"{{{R}}}id"), "")
        out.append(t[1:] if t.startswith("/xl/") else
                   (t if t.startswith("xl/") else "xl/" + t.lstrip("/")))
    return out


def _col(ref: str) -> int:
    n = 0
    for ch in ref:
        if ch.isalpha():
            n = n * 26 + (ord(ch.upper()) - 64)
        else:
            break
    return n


def xlsx_dicts(path: str, sheet: int = 0):
    """Yield each data row of an xlsx sheet as {header: raw_value}."""
    with zipfile.ZipFile(path) as zf:
        strings = _shared_strings(zf)
        paths = _sheet_paths(zf)
        if sheet >= len(paths):
            return
        header = None
        with zf.open(paths[sheet]) as fh:
            for _, elem in etree.iterparse(fh, events=("end",), tag=f"{{{M}}}row"):
                cells: dict[int, object] = {}
                for c in elem.findall(f"{{{M}}}c"):
                    ci = _col(c.get("r") or "A1")
                    t = c.get("t")
                    if t == "inlineStr":
                        el = c.find(f"{{{M}}}is")
                        val = "".join(x.text or "" for x in el.iter(f"{{{M}}}t")) \
                            if el is not None else None
                    else:
                        vv = c.find(f"{{{M}}}v")
                        val = vv.text if vv is not None else None
                        if t == "s" and val is not None:
                            i = int(val)
                            val = strings[i] if i < len(strings) else None
                        elif val is not None and t is None:
                            try:
                                val = float(val)
                            except ValueError:
                                pass
                    if val is not None:
                        cells[ci] = val
                width = max(cells) if cells else 0
                row = [cells.get(i) for i in range(1, width + 1)]
                elem.clear()
                while elem.getprevious() is not None:
                    del elem.getparent()[0]
                if header is None:
                    if any(v is not None for v in row):
                        header = [str(v).strip() if v is not None else ""
                                  for v in row]
                    continue
                yield {header[i]: row[i] if i < len(row) else None
                       for i in range(len(header))}


# ------------------------------------------------------------------- csv reader

_PROBE_TOKENS = ("开始日期", "广告活动名称", "日期", "品牌", "类别")


def csv_dicts(path: str):
    """Yield each data row of a csv as {header: str}. Detects encoding."""
    raw = open(path, "rb").read()
    best = None
    for enc in ("utf-8-sig", "gbk", "utf-8", "cp936", "latin-1"):
        try:
            text = raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
        head = text.split("\n", 1)[0]
        score = sum(1 for tok in _PROBE_TOKENS if tok in head)
        if best is None or score > best[0]:
            best = (score, enc, text)
        if score >= 2:
            break
    if best is None:
        return
    _, enc, text = best
    reader = csv.reader(io.StringIO(text, newline=""))
    rows = list(reader)
    if not rows:
        return
    header = [h.strip() for h in rows[0]]
    for r in rows[1:]:
        if not any(x.strip() for x in r):
            continue
        yield {header[i]: (r[i] if i < len(r) else None)
               for i in range(len(header))}, enc


def csv_encoding(path: str) -> str:
    for item in csv_dicts(path):
        return item[1]
    return "unknown"


def csv_rows(path: str):
    for row, _enc in csv_dicts(path):
        yield row


# ------------------------------------------------- campaign naming convention

# Derived from the customer's own 63 campaign names -- see 00-源表勘查/probe_names.py
NAME_TOKENS: dict[str, tuple[str, str]] = {
    # token          (dimension, human label)
    "SP": ("delivery", "手动投放"),
    "SPAU": ("delivery", "自动投放"),
    "SB": ("delivery", "品牌推广"),
    "SD": ("delivery", "展示型推广"),
    "KEYWORD": ("targeting", "关键词投放"),
    "KW": ("targeting", "关键词投放"),
    "ASIN": ("targeting", "商品投放"),
    "ALLASIN": ("targeting", "全商品投放"),
    "AT": ("targeting", "全商品投放"),
    "CATEGORY": ("targeting", "类目投放"),
    "BR": ("match", "广泛匹配"),
    "EX": ("match", "精准匹配"),
    "PH": ("match", "词组匹配"),
    "MIX": ("match", "混合匹配"),
    "CLOSE": ("match", "紧密匹配"),
    "LOOSE": ("match", "宽泛匹配"),
    "4A": ("style", "4条装A"),
    "4B": ("style", "4条装B"),
    "4C": ("style", "4条装C"),
    "7A": ("style", "7条装A"),
    "4LACK": ("style", "4条装黑"),
    "7PACK": ("style", "7条装"),
    "ZENG": ("owner", "曾向锋"),
    "ZENF": ("owner", "曾向锋(名称变体)"),
    "REGULAR": ("lifecycle", "主力组"),
    "TEST": ("lifecycle", "测试组"),
    "TOP": ("placement", "搜索结果顶部"),
    "TOPS": ("placement", "搜索结果顶部"),
    "LOW": ("placement", "其他位置"),
    "GJZ": ("audience", "高价值新客"),
    "XS": ("audience", "相似人群"),
    "LIKE": ("audience", "心愿单"),
    "LK": ("audience", "受众实验"),
    "KF": ("tactic", "捡漏"),
    "JM": ("tactic", "捡漏"),
    "TL": ("tactic", "捡漏"),
    "BD": ("tactic", "活动期"),
    "BRAND": ("theme", "品牌词"),
    "ABB": ("theme", "品牌变体词"),
    "GM": ("theme", "大词"),
    "MAIN": ("theme", "大词"),
    "FY": ("theme", "复购"),
    "COMPETITIVE": ("theme", "竞品词"),
    "人群": ("theme", "人群词"),
    "颜色": ("theme", "颜色词"),
    "尺码": ("theme", "尺码词"),
    "材质": ("theme", "材质词"),
    "功能": ("theme", "功能词"),
    "属性": ("theme", "属性词"),
    "场景": ("theme", "场景词"),
    "节日": ("theme", "节日词"),
    "季节": ("theme", "季节词"),
    "数量": ("theme", "数量词"),
    "文案": ("theme", "创意变体"),
}

# Chinese tokens that appear without a separator, matched as substrings.
NAME_SUBSTRINGS: dict[str, tuple[str, str]] = {
    "自动化": ("delivery", "自动投放"),
    "自动": ("delivery", "自动投放"),
    "捡漏": ("tactic", "捡漏"),
    "紧密": ("match", "紧密匹配"),
    "宽泛": ("match", "宽泛匹配"),
    "大词": ("theme", "大词"),
    "高价值新客": ("audience", "高价值新客"),
    "相似人群": ("audience", "相似人群"),
    "心愿单": ("audience", "心愿单"),
}

# The 12 需求属性 themes the operator opened dedicated test campaigns for --
# these map to the demand-attribute vocabulary in the product plan (§4.4).
_ATTRIBUTE_THEMES = {
    "人群词", "颜色词", "尺码词", "材质词", "功能词",
    "属性词", "场景词", "节日词", "季节词", "数量词",
}

_PURPOSE_RULES = [
    # (required dimensions/values, purpose label)  -- evaluated in order
    ({"theme": "品牌词"}, "品牌防守"),
    ({"theme": "品牌变体词"}, "品牌防守"),
    ({"theme": "竞品词"}, "竞品词拦截"),
    ({"theme": "大词"}, "大词抢位"),
    ({"theme": "创意变体"}, "创意测试"),
    ({"theme": "复购"}, "复购与关联"),
    ({"audience": "高价值新客"}, "受众再营销"),
    ({"audience": "相似人群"}, "受众再营销"),
    ({"audience": "心愿单"}, "受众再营销"),
    ({"audience": "受众实验"}, "受众再营销"),
    ({"targeting": "商品投放"}, "竞品与关联商品拦截"),
    ({"targeting": "全商品投放"}, "竞品与关联商品拦截"),
    ({"targeting": "类目投放"}, "类目流量拓展"),
    ({"tactic": "捡漏"}, "自动捡漏"),
    ({"delivery": "自动投放"}, "自动捡漏"),
    ({"targeting": "关键词投放"}, "关键词流量获取"),
]


def parse_campaign_name(name: str) -> dict:
    """Decode the operator's naming convention into labelled dimensions.

    Returns {'line':..., 'dims': {dimension: [labels]}, 'tokens': [...],
             'unknown_tokens': [...]}
    """
    if not name:
        return {"line": None, "dims": {}, "tokens": [], "unknown_tokens": []}
    text = str(name).strip()
    pieces = [p for p in re.split(r"[-_/\s]+", text) if p]
    dims: dict[str, list[str]] = {}
    known, unknown = [], []
    line = None

    def add(dim: str, label: str) -> None:
        dims.setdefault(dim, [])
        if label not in dims[dim]:
            dims[dim].append(label)

    for p in pieces:
        if re.fullmatch(r"\d{3}", p):
            line = p
            known.append(p)
            continue
        hit = NAME_TOKENS.get(p) or NAME_TOKENS.get(p.upper())
        if hit:
            add(hit[0], hit[1])
            known.append(p)
        else:
            unknown.append(p)

    # Chinese tokens are often glued to their neighbours (002自动化广告活动),
    # so also scan the raw string for them.
    for sub, (dim, label) in NAME_SUBSTRINGS.items():
        if sub in text:
            add(dim, label)
            if sub not in known:
                known.append(sub)
            unknown = [u for u in unknown if sub not in u]

    # A match type alone implies keyword targeting (002-SP-PH-7PACK-...).
    if "targeting" not in dims and dims.get("match"):
        if any(m in dims["match"] for m in
               ("广泛匹配", "精准匹配", "词组匹配", "混合匹配")):
            add("targeting", "关键词投放")

    if line is None and text.startswith("002"):
        line = "002"

    return {"line": line, "dims": dims, "tokens": known,
            "unknown_tokens": unknown}


def infer_purpose(dims: dict) -> tuple[str, str]:
    """Infer an ad purpose from decoded dimensions.

    Returns (purpose_label, basis). Purpose is a suggestion -- callers must
    store it with confirmation_status='pending'.
    """
    themes = dims.get("theme") or []
    for t in themes:
        if t in _ATTRIBUTE_THEMES:
            return "需求属性探索", "campaign_name:theme=" + t
    for need, purpose in _PURPOSE_RULES:
        if all(dims.get(k) and v in dims[k] for k, v in need.items()):
            basis = ",".join("%s=%s" % (k, v) for k, v in need.items())
            return purpose, "campaign_name:" + basis
    return "无法识别", "campaign_name:no_matching_token"


def ad_file(name: str) -> str:
    return os.path.join(AD_DIR, name)
