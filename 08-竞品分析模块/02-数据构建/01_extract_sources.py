#!/usr/bin/env python3
"""步骤一：从真实源表抽取竞品族/子体/关键词/自有侧，落 _sources.json。

只读源文件，不写任何源目录。用 /usr/bin/python3 运行（本机唯一带 lxml 的解释器）。
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import statistics
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "lib"))
import xlsxlite  # noqa: E402

SRC = "/Users/linsen/BAM/数据源/AI广告对接数据-总20260803"
COMP = f"{SRC}/9.竞品.xlsx"
KW3 = f"{SRC}/10.关键词/关键词3.xlsx"
OWN_DB = (
    "/Users/linsen/BAM/02-产品销售库存模块/02-数据构建/"
    "v0.3.0/bamboocool_product_sales_inventory_v0.3.0.sqlite"
)
OWN_PARENTS = ("B0D9FLMR6N", "B0GQXK2Q58")
AS_OF = "2026-08-03"
WINDOW_FROM = "2026-02-05"
SUB_CATEGORY = "Men's Boxer Briefs"
CRAWL_FAMILIES = 48

PACK_A = re.compile(r"(\d+)\s*[- ]?(?:pack|pk|pairs?|count|ct)\b", re.I)
PACK_B = re.compile(r"pack of\s*(\d+)", re.I)


def parse_pack(*texts):
    for t in texts:
        if not t:
            continue
        s = str(t)
        m = PACK_A.search(s) or PACK_B.search(s)
        if m:
            n = int(m.group(1))
            if 1 <= n <= 24:
                return n
    return None


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def read_competitors():
    rows = list(xlsxlite.iter_rows(COMP, 0))
    hdr = rows[0]
    ix = {h: i for i, h in enumerate(hdr) if isinstance(h, str)}

    def g(r, k):
        i = ix.get(k)
        return r[i] if i is not None and i < len(r) else None

    fam = defaultdict(list)
    for r in rows[1:]:
        if g(r, "小类目") != SUB_CATEGORY:
            continue
        fam[g(r, "父ASIN")].append(r)

    families, children = [], []
    for pa, rs in fam.items():
        if len(rs) < 4:
            continue
        head = rs[0]
        prices = [num(g(r, "价格($)")) for r in rs]
        prices = [p for p in prices if p]
        if not prices:
            continue
        med = statistics.median(prices)
        if not (10.0 <= med <= 40.0):
            continue
        kids, unit_prices = [], []
        for r in rs:
            price = num(g(r, "价格($)"))
            pack = parse_pack(g(r, "SKU"), g(r, "商品标题"))
            unit = round(price / pack, 3) if (price and pack) else None
            if unit:
                unit_prices.append(unit)
            kids.append(
                dict(
                    child_asin=g(r, "ASIN"),
                    family_asin=pa,
                    sku=g(r, "SKU"),
                    pack_count=pack,
                    snapshot_price=price,
                    unit_price=unit,
                    fba_fee=num(g(r, "FBA($)")),
                    gross_margin=num(g(r, "毛利率")),
                    sales_rank_sub=int(num(g(r, "小类BSR")) or 0) or None,
                    child_units=num(g(r, "子体销量")),
                )
            )
        if not unit_prices:
            continue
        families.append(
            dict(
                family_asin=pa,
                brand=g(r, "品牌") or g(head, "品牌"),
                title=g(head, "商品标题"),
                category_path=g(head, "类目路径"),
                sub_category=SUB_CATEGORY,
                variant_count=int(num(g(head, "变体数")) or 0) or None,
                captured_children=len(rs),
                price_band_low=min(prices),
                price_band_high=max(prices),
                unit_price_median=round(statistics.median(unit_prices), 3),
                first_listed_date=str(g(head, "上架时间") or "")[:10] or None,
                seller_country=g(head, "卖家所属地"),
                buybox_type=g(head, "BuyBox类型"),
                buybox_seller=g(head, "BuyBox卖家"),
                seller_count=int(num(g(head, "卖家数")) or 0) or None,
                fulfillment=g(head, "配送方式"),
                has_aplus=1 if g(head, "A+页面") == "Y" else 0,
                has_video=1 if g(head, "视频介绍") == "Y" else 0,
                monthly_units=num(g(head, "月销量")),
                rank_sub=int(num(g(head, "小类BSR")) or 0) or None,
                rank_main=int(num(g(head, "大类BSR")) or 0) or None,
                rating=num(g(head, "评分")),
                rating_count=int(num(g(head, "评分数")) or 0) or None,
                new_rating=int(num(g(head, "月新增评分数")) or 0) or None,
                ac_keyword=g(head, "AC关键词"),
                children=kids,
            )
        )

    families.sort(key=lambda d: -(d["monthly_units"] or 0))
    families = families[:CRAWL_FAMILIES]
    keep = {f["family_asin"] for f in families}
    for f in families:
        f["children"] = sorted(
            f["children"], key=lambda k: -(k["child_units"] or 0)
        )[:6]
        children.extend(f["children"])
    return families, children, keep


def read_keywords(comp_child_to_family):
    rows = list(xlsxlite.iter_rows(KW3, 1))
    hdr = [h if isinstance(h, str) else "" for h in rows[0]]
    ix = {h: i for i, h in enumerate(hdr)}

    def g(r, k):
        i = ix.get(k)
        return r[i] if i is not None and i < len(r) else None

    top_cols = []
    for n in (1, 2, 3):
        asin_col = next((h for h in hdr if h.startswith(f"#{n}") and "ASIN" in h), None)
        clk = next((h for h in hdr if h.startswith(f"#{n}") and "点击共享" in h), None)
        cvr = next((h for h in hdr if h.startswith(f"#{n}") and "转化共享" in h), None)
        top_cols.append((asin_col, clk, cvr))

    out = []
    for r in rows[1:]:
        kw = g(r, "关键词")
        if not kw:
            continue
        top3 = []
        for asin_col, clk, cvr in top_cols:
            a = g(r, asin_col) if asin_col else None
            if not a:
                continue
            top3.append(
                dict(
                    asin=str(a).strip(),
                    click_share=num(g(r, clk)) if clk else None,
                    conversion_share=num(g(r, cvr)) if cvr else None,
                    family_asin=comp_child_to_family.get(str(a).strip()),
                )
            )
        hit = [t for t in top3 if t["family_asin"]]
        tags = str(g(r, "所有分类标签") or "")
        out.append(
            dict(
                keyword=kw,
                keyword_cn=g(r, "关键词翻译"),
                category_tags=tags,
                aba_rank=int(num(g(r, "ABA月排名")) or 0) or None,
                monthly_search=int(num(g(r, "月搜索量")) or 0) or None,
                monthly_purchase=int(num(g(r, "月购买量")) or 0) or None,
                purchase_rate=num(g(r, "购买率")),
                product_count=int(num(g(r, "商品数")) or 0) or None,
                supply_demand_ratio=num(g(r, "需供比")),
                ad_competitor_count=int(num(g(r, "广告竞品数")) or 0) or None,
                ppc_bid=num(str(g(r, "PPC竞价") or "").replace("$", "")),
                top3=top3,
                own_family_hits=len(hit),
            )
        )
    scored = [k for k in out if k["own_family_hits"] > 0 and k["monthly_search"]]
    scored.sort(key=lambda k: (-k["own_family_hits"], -(k["monthly_search"] or 0)))
    return scored[:48]


def read_own():
    con = sqlite3.connect(f"file:{OWN_DB}?mode=ro", uri=True)
    q = (
        "SELECT c.child_asin, c.parent_asin, c.product_name, c.size, c.combination,"
        " c.category, c.product_lifecycle"
        " FROM dim_product_child c WHERE c.parent_asin IN (?,?)"
    )
    kids = []
    for row in con.execute(q, OWN_PARENTS):
        pack = None
        digits = "".join(ch for ch in str(row[4] or "") if ch.isdigit())
        if digits:
            pack = int(digits)
        kids.append(
            dict(
                child_asin=row[0],
                parent_asin=row[1],
                product_name=row[2],
                size=row[3],
                combination=row[4],
                pack_count=pack,
                category=row[5],
                lifecycle=row[6],
            )
        )
    price = []
    q2 = (
        "SELECT p.child_asin, p.parent_asin, p.date, p.selling_price"
        " FROM fact_child_price_daily p"
        " WHERE p.parent_asin IN (?,?) AND p.date BETWEEN ? AND ?"
    )
    for row in con.execute(q2, (*OWN_PARENTS, WINDOW_FROM, AS_OF)):
        price.append(dict(child_asin=row[0], parent_asin=row[1], date=row[2], price=row[3]))
    con.close()
    return kids, price


def main():
    families, children, _ = read_competitors()
    c2f = {c["child_asin"]: c["family_asin"] for c in children}
    all_c2f = {}
    for f in families:
        for c in f["children"]:
            all_c2f[c["child_asin"]] = f["family_asin"]
    keywords = read_keywords(all_c2f)

    payload = dict(
        as_of=AS_OF,
        window_from=WINDOW_FROM,
        sub_category=SUB_CATEGORY,
        families=families,
        keywords=keywords,
    )
    out = os.path.join(HERE, "_sources.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)
    packs = sum(1 for c in children if c["pack_count"])
    print(f"families={len(families)} children={len(children)} pack_resolved={packs}/{len(children)}")
    print(f"keywords={len(keywords)}")
    print("自有侧不落盘：契约 6.3 要求 ATTACH 产品包读，不在本包重建产品维度")
    print(f"wrote {out} ({os.path.getsize(out)/1024:.0f} KB)")


if __name__ == "__main__":
    main()
