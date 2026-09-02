#!/usr/bin/env python3
"""步骤三：按契约第 3 节建 Agent 库 competitor_demo.sqlite。

这里生成的是"Pi Agent 之后会写的那些行"。前端只读这个库拿判断，
换成真 Agent 时表和字段一字不改。
"""
from __future__ import annotations

import datetime as dt
import os
import random
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "v0.1.0")
OBS = os.path.join(OUT_DIR, "competitor_demo.sqlite")
DB = os.path.join(OUT_DIR, "competitor_demo.sqlite")
SEED = 20260830
AGENT_VERSION = "competitor-agent-pi-v0.1"

SCHEMA = """
CREATE TABLE fact_competitor_analysis_run (
  run_id TEXT PRIMARY KEY, family_asin TEXT NOT NULL, run_date TEXT NOT NULL,
  data_as_of TEXT NOT NULL, window_from TEXT NOT NULL, window_to TEXT NOT NULL,
  trigger TEXT NOT NULL, model_version TEXT, attention_level TEXT NOT NULL,
  attention_summary TEXT NOT NULL, evidence_level TEXT NOT NULL,
  evidence_reason TEXT NOT NULL, judgment_summary TEXT, created_at TEXT NOT NULL);
CREATE INDEX idx_run_family ON fact_competitor_analysis_run(family_asin, run_date DESC, created_at DESC);
CREATE TABLE fact_competitor_analysis_change (
  run_id TEXT NOT NULL, change_seq INTEGER NOT NULL, domain TEXT NOT NULL,
  object_level TEXT NOT NULL, object_id TEXT NOT NULL, label TEXT NOT NULL,
  direction TEXT NOT NULL, magnitude_kind TEXT, magnitude_value REAL,
  date_from TEXT NOT NULL, date_to TEXT, current_state TEXT NOT NULL,
  represents_family INTEGER NOT NULL, coverage_note TEXT, value_origin TEXT NOT NULL,
  confidence TEXT NOT NULL, basis TEXT NOT NULL, PRIMARY KEY (run_id, change_seq));
CREATE TABLE fact_competitor_analysis_timeline (
  run_id TEXT NOT NULL, track TEXT NOT NULL, item_seq INTEGER NOT NULL,
  label TEXT NOT NULL, date_from TEXT NOT NULL, date_to TEXT, ref_change_seq INTEGER,
  window_before_from TEXT, window_before_to TEXT, window_after_from TEXT,
  window_after_to TEXT, note TEXT, PRIMARY KEY (run_id, track, item_seq));
CREATE TABLE fact_competitor_analysis_concurrency (
  run_id TEXT NOT NULL, pair_seq INTEGER NOT NULL, change_seq_a INTEGER NOT NULL,
  change_seq_b INTEGER NOT NULL, relation TEXT NOT NULL, overlap_from TEXT,
  overlap_to TEXT, statement TEXT NOT NULL, causal_ready INTEGER NOT NULL,
  missing_evidence TEXT, PRIMARY KEY (run_id, pair_seq));
CREATE TABLE fact_competitor_analysis_attention_reason (
  run_id TEXT NOT NULL, reason_seq INTEGER NOT NULL, label TEXT NOT NULL,
  ref_change_seq INTEGER, weight_note TEXT, PRIMARY KEY (run_id, reason_seq));
CREATE TABLE fact_competitor_analysis_impact (
  run_id TEXT NOT NULL, impact_seq INTEGER NOT NULL, own_parent_asin TEXT NOT NULL,
  own_child_asin TEXT, shared_keyword TEXT, pressure_dimension TEXT NOT NULL,
  statement TEXT NOT NULL, ref_change_seq INTEGER, confidence TEXT NOT NULL,
  PRIMARY KEY (run_id, impact_seq));
CREATE TABLE fact_competitor_analysis_open_item (
  run_id TEXT NOT NULL, item_seq INTEGER NOT NULL, item_kind TEXT NOT NULL,
  statement TEXT NOT NULL, needed_data TEXT, watch_until TEXT,
  PRIMARY KEY (run_id, item_seq));
CREATE TABLE fact_competitor_analysis_diff (
  run_id TEXT PRIMARY KEY, prev_run_id TEXT, transition TEXT NOT NULL,
  statement TEXT NOT NULL, changed_domains TEXT);
CREATE TABLE fact_competitor_analysis_report (
  report_id TEXT PRIMARY KEY, scope_key TEXT NOT NULL, period_from TEXT NOT NULL,
  period_to TEXT NOT NULL, item_seq INTEGER NOT NULL, family_asin TEXT NOT NULL,
  ref_run_id TEXT NOT NULL, headline TEXT NOT NULL, body TEXT NOT NULL,
  impact_note TEXT, unconfirmed_note TEXT, created_at TEXT NOT NULL);
CREATE TABLE fact_competitor_evidence_handoff (
  handoff_id TEXT PRIMARY KEY, frozen_run_id TEXT NOT NULL, target_page TEXT NOT NULL,
  family_asin TEXT NOT NULL, own_child_asin TEXT, shared_keyword TEXT,
  pressure_dimension TEXT, observable_fact TEXT NOT NULL, evidence_level TEXT NOT NULL,
  detail_entry TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS competitor_manifest (key TEXT PRIMARY KEY, value TEXT);
"""

SCOPE = "美国站 · 男士内裤 · Men's Boxer Briefs"


def main():
    rng = random.Random(SEED)
    # 观察层已建好同一个库，这里只追加分析表。重跑请先跑 02（它会重建干净库）。
    con = sqlite3.connect(DB)
    con.executescript(SCHEMA)
    obs = con
    man = dict(obs.execute("SELECT key, value FROM competitor_manifest"))
    as_of, win_from = man["as_of"], man["window_from"]
    scen = {r[1]: r[0] for r in obs.execute("SELECT scenario_id, family_asin FROM dim_competitor_scenario")}
    fams = obs.execute(
        "SELECT family_asin, brand, unit_price_median, captured_children, variant_count"
        " FROM dim_competitor_family WHERE in_analysis_scope = 1"
        " ORDER BY in_quick_slot DESC, family_asin"
    ).fetchall()
    rel = {}
    for r in obs.execute(
        "SELECT family_asin, child_asin, parent_asin FROM bridge_competitor_child"
    ):
        rel.setdefault(r[0], []).append((r[1], r[2]))
    kws = {}
    for r in obs.execute(
        "SELECT family_asin, keyword FROM bridge_competitor_keyword"
    ):
        kws.setdefault(r[0], []).append(r[1])
    main_child = {}
    non_main = {}
    any_child = {}
    for r in obs.execute(
        "SELECT family_asin, child_asin, is_main_variant, pack_resolved"
        " FROM dim_competitor_child ORDER BY is_main_variant DESC, pack_resolved DESC"
    ):
        any_child.setdefault(r[0], r[1])
        if r[3] != 1:
            continue
        if r[2] == 1:
            main_child.setdefault(r[0], r[1])
        else:
            non_main.setdefault(r[0], r[1])
    # 装盒数未解析的族没有可用于价差结论的子体，退到任意子体（其变化不会进价差类结论）
    for fa, cid in any_child.items():
        main_child.setdefault(fa, cid)
        non_main.setdefault(fa, main_child[fa])
    fallback_kw = obs.execute(
        "SELECT keyword FROM dim_competitor_keyword WHERE is_battleground = 1"
        " ORDER BY monthly_search DESC LIMIT 1"
    ).fetchone()[0]

    def ins(table, row):
        con.execute(
            f"INSERT INTO {table} VALUES ({','.join('?' * len(row))})", row
        )

    reports = []
    handoffs = []
    run_i = 0
    for fam_asin, brand, unit_med, captured, variants in fams:
        sid = scen.get(fam_asin)
        run_i += 1
        run_id = f"{fam_asin}-{as_of}-1"
        changes = []          # (seq, domain, level, obj, label, dir, kind, val, d0, d1, state, repr, cover, nature, conf, basis)
        pairs = []
        reasons = []
        impacts = []
        opens = []
        mc = main_child.get(fam_asin)
        nm = non_main.get(fam_asin, mc)
        kw = (kws.get(fam_asin) or [fallback_kw])[0] or fallback_kw
        own = (rel.get(fam_asin) or [(None, "B0D9FLMR6N")])[0]
        attention, ev_level = "medium", "sufficient"
        summary = f"{brand} 近期出现值得关注的变化"
        ev_reason = "价格、市场与关键词三条轨都有连续观察，覆盖完整"
        judgment = ""

        if sid == "S1":
            changes.append((1, "price_promo", "child", mc, "活动期降价 20% 后已恢复原价", "down",
                            "pct", -20.0, "2026-05-16", "2026-06-07", "已恢复", 1,
                            f"活动覆盖 {captured} 个在售子体中的主销变体", "direct", "high",
                            "成交价在活动段稳定低于日常价，活动结束后回到原区间"))
            changes.append((2, "price_promo", "family", fam_asin, "与自有的件单价差活动期扩大后收窄", "down",
                            "pct", -18.0, "2026-05-16", "2026-06-07", "已恢复", 1,
                            "按件单价同口径比较", "derived", "medium",
                            "活动期件单价差从 1.5 倍扩到 1.9 倍，结束后回到 1.5 倍"))
            reasons = [(1, "曾出现 20% 幅度的活动降价，价差一度扩到 1.9 倍", 1, "幅度最大且落在主销变体上"),
                       (2, "活动已结束且价格完全恢复，压力当前不持续", 1, "决定等级不上调")]
            attention = "medium"
            judgment = "活动期造成过一段真实价格压力，目前已恢复，属于需要记住节奏而非当下应对的对象。"
            impacts = [(1, own[1], own[0], kw, "price", "活动期该竞品件单价低于自有约 35%，同期共享核心词曝光被压", 1, "medium")]
            opens = [(1, "watch", "下一次活动是否在同一档期重复出现", "活动日历与历史活动记录", "2026-09-15")]

        elif sid == "S2":
            changes.append((1, "price_promo", "family", fam_asin, "非活动性阶梯降价，价格带整体下移 18%", "down",
                            "pct", -18.0, "2026-03-01", None, "仍在进行", 1,
                            f"{captured} 个在售子体同步下移", "direct", "high",
                            "价格分三段下移且无活动标识，属常态价调整"))
            changes.append((2, "market", "family", fam_asin, "小类排名同期小幅走强", "up",
                            "rank", -6.0, "2026-04-10", None, "仍在进行", 1, None,
                            "constructed", "medium", "排名估算在降价后稳定上移"))
            pairs = [(1, 1, 2, "concurrent", "2026-04-10", as_of,
                      "价格带下移与排名走强同期出现，目前只能表述为可能相关", 0,
                      "需要转化率或流量结构数据才能判断排名是否由降价带来")]
            reasons = [(1, "常态价下移 18% 且仍在持续，不是短期活动", 1, "持续性最强"),
                       (2, "价格带下移已把该族拉进自有的件单价区间", 1, "直接改变竞争位置"),
                       (3, "同期排名走强，压力方向一致", 2, "作为旁证不单独成立")]
            attention = "high"
            judgment = "这是本周期最值得处理的一个：不是活动，是价格带真的下来了，且已经压到自有所在区间。"
            impacts = [(1, own[1], own[0], kw, "price", "自有件单价相对溢价从 1.4 倍升到 1.7 倍", 1, "high")]
            opens = [(1, "hypothesis", "降价可能是为清理旧款库存", "该族历史上下架与新品上架记录", None)]

        elif sid == "S3":
            changes.append((1, "market", "family", fam_asin, "小类排名持续提升，销量量级上行", "up",
                            "rank", -34.0, "2026-03-20", None, "仍在进行", 1, None,
                            "constructed", "medium", "排名与销量量级估算连续 4 个月同向走强"))
            changes.append((2, "market", "family", fam_asin, "评论增速加快", "up", "units", 1.6,
                            "2026-04-01", None, "仍在进行", 1, None, "constructed",
                            "medium", "月新增评分数较窗口前段提升约 60%"))
            reasons = [(1, "排名连续 4 个月提升且未回落", 1, "持续性与幅度都成立"),
                       (2, "评论增速同向加快，说明成交在放量", 2, "支撑排名变化不是估算噪声")]
            attention = "high"
            judgment = "市场份额在被这个对象持续拿走，价格没动，压力来自产品端。"
            impacts = [(1, own[1], own[0], kw, "market", "共享核心词上该竞品可见度提升，自有自然位承压", 1, "medium")]
            opens = [(1, "unconfirmed", "排名提升是否来自站外或新增变体尚不能确认", "变体上架记录与站外流量", None)]

        elif sid == "S4":
            changes.append((1, "market", "family", fam_asin, "小类排名下滑，评分走低", "down",
                            "rank", 28.0, "2026-04-05", None, "仍在进行", 1, None,
                            "constructed", "medium", "排名估算连续下行，评分同期下降 0.2"))
            reasons = [(1, "排名连续下行且评分同步走低", 1, "两条独立信号方向一致"),
                       (2, "该族仍在自有的件单价区间内，位置腾出可被承接", 1, "构成机会而非威胁")]
            attention = "low"
            judgment = "这是一个机会型对象：它在退，自有在同一批词上有承接空间。"
            impacts = [(1, own[1], own[0], kw, "market", "该竞品退位，自有在共享词上有承接空间", 1, "medium")]
            opens = [(1, "watch", "评分下滑是否由某一批次质量问题引起", "评论内容抽样", "2026-09-30")]

        elif sid == "S5":
            changes.append((1, "keyword", "keyword", kw, "在共享核心词上挤进前三，点击共享上升", "up",
                            "position", -9.0, "2026-05-01", None, "仍在进行", 1,
                            "该词为与自有共同竞争的重点词", "direct", "high",
                            "自然位从第 10 名区间进入前三，且当期点击共享有真实记录"))
            changes.append((2, "traffic", "family", fam_asin, "广告流量占比上升", "up", "pct", 6.0,
                            "2026-05-01", None, "仍在进行", 1, None, "constructed",
                            "low", "第三方估算的广告流量占比连续两月上行"))
            pairs = [(1, 1, 2, "concurrent", "2026-05-01", as_of,
                      "位置提升与广告占比上升同期出现，可能相关", 0,
                      "竞品广告花费与出价无可靠来源，不能据占比反推")]
            reasons = [(1, "在与自有共同竞争的重点词上进入前三", 1, "直接改变自有获取该词流量的难度"),
                       (2, "位置提升已持续 3 个月，不是单次波动", 1, "持续性成立")]
            attention = "high"
            judgment = "位置被实打实拿走，这条要交给关键词页继续核对。"
            impacts = [(1, own[1], own[0], kw, "keyword", "自有在该词自然位被挤到前三之外", 1, "high")]
            opens = [(1, "unconfirmed", "对方是否在该词上加投广告无法确认", "竞品广告数据（当前无可靠来源）", None)]
            handoffs.append((f"HO-{run_id}-KW", run_id, "keyword", fam_asin, own[0], kw,
                             "keyword", "该竞品在此词当期位居前三且点击共享有真实记录",
                             "sufficient", f"{fam_asin} · 2026-05-01 至 {as_of} · 关键词位置"))

        elif sid == "S6":
            changes.append((1, "keyword", "keyword", kw, "掉出前三，覆盖收缩", "down",
                            "position", 7.0, "2026-06-10", None, "仍在进行", 1,
                            "该词为与自有共同竞争的重点词", "direct", "medium",
                            "自然位从前三退到第 8 名区间"))
            reasons = [(1, "在共享重点词上退出前三", 1, "自有可承接的位置出现"),
                       (2, "退位已持续 6 周，不是单周波动", 1, "持续性成立")]
            attention = "low"
            judgment = "对方退位，是自有在这个词上加位的窗口。"
            impacts = [(1, own[1], own[0], kw, "keyword", "该词前三腾出一位，自有有加位窗口", 1, "medium")]
            opens = [(1, "watch", "退位是否会在下一个周期反弹", "关键词位置继续观察 4 周", "2026-09-27")]

        elif sid == "S7":
            changes.append((1, "price_promo", "child", nm, "单个非主销子体降价 15%", "down",
                            "pct", -15.0, "2026-06-24", None, "仍在进行", 0,
                            f"仅 1 个子体，且不是主销变体；该族共 {captured} 个在售子体、自报 {variants} 个变体",
                            "direct", "high",
                            "只有该子体成交价下移，其余子体价格未动"))
            reasons = [(1, "变化只落在一个非主销子体上", 1, "不构成产品族层面的价格压力"),
                       (2, "该族其余子体价格全期未动", 1, "排除整族调价")]
            attention = "low"
            judgment = "看起来像降价，其实只是一个尺码在清货，不要按整族降价处理。"
            impacts = []
            opens = [(1, "watch", "是否会扩散到其他子体", "逐子体价格继续观察", "2026-09-20")]

        elif sid == "S8":
            changes.append((1, "price_promo", "offer", f"{mc}-OF2", "BuyBox 换到第三方卖家，成交价下移 9%", "down",
                            "pct", -9.0, "2026-05-05", "2026-07-04", "已结束", 0,
                            "变化发生在报价层，不是品牌自己调价", "direct", "medium",
                            "同期 BuyBox 卖家发生变化，品牌自营报价未动"))
            reasons = [(1, "价格下移来自第三方跟卖占据 BuyBox", 1, "归因对象是报价不是品牌"),
                       (2, "品牌自营报价全期未变", 1, "排除品牌调价")]
            attention = "low"
            judgment = "这是跟卖造成的价格变化，不代表品牌策略变了。"
            impacts = []
            opens = [(1, "unconfirmed", "第三方卖家是否为授权渠道无法确认", "卖家资质信息", None)]

        elif sid == "S9":
            attention, ev_level = "none", "insufficient"
            summary = "证据不足，本次不给关注结论"
            ev_reason = "6 月有 14 天完全没有观察记录，7 月起两个来源的成交价互相冲突，关键词位置最近更新于 4 周前"
            judgment = "这个对象的数据本身有问题，任何变化结论都可能是观察缺口造成的假象。"
            changes.append((1, "price_promo", "family", fam_asin, "观察缺口期间的价格变化无法确认", "neutral",
                            None, None, "2026-06-05", "2026-06-18", "无法确认", 0,
                            "断更 14 天，缺口两端价格不可直接相减", "constructed", "low",
                            "该区间无任何价格观察记录"))
            pairs = [(1, 1, 1, "insufficient", "2026-06-05", "2026-06-18",
                      "缺口期内是否发生过活动无法判断，不构成任何同期证据", 0,
                      "需要补齐断更期间的价格与活动观察")]
            opens = [(1, "unconfirmed", "断更期间是否发生过活动", "补齐 6 月 5 日至 18 日的价格监控", "2026-09-10"),
                     (2, "unconfirmed", "两个来源哪一个的成交价可用", "确认两个来源的采集口径", "2026-09-10")]

        elif sid == "S10":
            changes.append((1, "price_promo", "family", fam_asin, "常态价下移 9%", "down", "pct", -9.0,
                            "2026-06-04", None, "仍在进行", 1, None, "direct", "high",
                            "成交价自 6 月起稳定低于前段区间"))
            changes.append((2, "market", "family", fam_asin, "小类排名同期提升", "up", "rank", -22.0,
                            "2026-06-04", None, "仍在进行", 1, None, "constructed",
                            "medium", "排名估算在同一时点开始上移"))
            pairs = [(1, 1, 2, "concurrent", "2026-06-04", as_of,
                      "降价与排名提升在同一时点开始，属同期变化，暂不能判断因果", 0,
                      "需要该族转化率或同类目其他对象的对照，才能排除类目整体走强")]
            reasons = [(1, "常态价下移 9% 且持续", 1, "价格压力成立"),
                       (2, "同期排名提升，但因果未确认", 2, "作为同期证据不单独定级")]
            attention = "high"
            judgment = "价格和排名一起动了，但两件事的因果没有证据，先当同期变化处理。"
            impacts = [(1, own[1], own[0], kw, "price", "件单价差收窄，自有溢价空间被压缩", 1, "medium")]
            opens = [(1, "hypothesis", "排名提升可能来自降价，也可能是类目整体走强", "同类目对照组表现", None)]

        elif sid == "S10b":
            changes.append((1, "price_promo", "family", fam_asin, "常态价下移 9%", "down", "pct", -9.0,
                            "2026-06-04", None, "仍在进行", 1, None, "direct", "high",
                            "成交价自 6 月起稳定低于前段区间"))
            reasons = [(1, "常态价下移 9% 且持续", 1, "价格压力成立"),
                       (2, "同期排名没有变化，说明降价未换来位置", 1, "降低紧迫度")]
            attention = "medium"
            judgment = "同样幅度的降价，这个对象的排名没动——正好说明降价与排名不能默认当因果。"
            impacts = [(1, own[1], own[0], None, "price", "件单价差收窄但未转化为对方位置提升", 1, "low")]
            opens = [(1, "watch", "降价是否会在下一周期开始换来位置", "排名与价格继续同步观察", "2026-10-04")]

        elif sid == "S11":
            attention = "none"
            summary = "本周期无显著变化"
            ev_reason = "三条轨观察完整，未识别出达到关注门槛的变化"
            judgment = "平稳对照对象，本周期不需要处理。"
            changes.append((1, "market", "family", fam_asin, "排名与价格全期平稳", "neutral", None, None,
                            win_from, as_of, "仍在进行", 1, None, "constructed", "high",
                            "窗口内排名波动未超过正常区间，价格未变"))

        else:
            # 其余分析范围内的对象：给较轻的变化，保证四类版图都有足够对象
            pick = run_i % 4
            if pick == 0:
                changes.append((1, "price_promo", "family", fam_asin, "短期 Coupon 上线后撤下", "down",
                                "pct", -8.0, "2026-06-12", "2026-06-26", "已结束", 1, None,
                                "direct", "medium", "成交价在两周内低于日常价后恢复"))
            elif pick == 1:
                changes.append((1, "market", "family", fam_asin, "小类排名小幅走弱", "down", "rank",
                                9.0, "2026-05-20", None, "仍在进行", 1, None,
                                "constructed", "low", "排名估算连续两月轻微下行"))
            elif pick == 2:
                changes.append((1, "keyword", "keyword", kw or "mens underwear",
                                "关键词覆盖新增，位置进入前十", "up", "position", -5.0,
                                "2026-06-01", None, "仍在进行", 1, None, "derived", "low",
                                "该词位置序列自 6 月起进入前十区间"))
            else:
                changes.append((1, "traffic", "family", fam_asin, "广告流量占比上升", "up", "pct",
                                4.0, "2026-05-01", None, "仍在进行", 1, None,
                                "constructed", "low",
                                "第三方估算的广告流量占比连续两月上行"))
            attention = "low"
            summary = f"{brand} 有轻度变化，暂不需优先处理"
            reasons = [(1, "变化幅度有限且未持续扩大", 1, "不足以上调等级"),
                       (2, "尚未影响与自有共同竞争的重点词", 1, "影响范围有限")]
            judgment = "轻度变化，记录在案。"

        # 概要句用最重要那条变化本身，不用"某某近期出现值得关注的变化"这种模板句
        if changes and summary.endswith("近期出现值得关注的变化"):
            summary = changes[0][4]

        # 写 run
        created = f"{as_of}T0{(run_i % 8) + 1}:15:00Z"
        trig = "priority" if run_i <= 8 else "scheduled"
        ins("fact_competitor_analysis_run", (run_id, fam_asin, as_of, as_of, win_from, as_of, trig,
                                 AGENT_VERSION, attention, summary, ev_level, ev_reason,
                                 judgment, created))
        for c in changes:
            ins("fact_competitor_analysis_change", (run_id,) + c)
        for p in pairs:
            ins("fact_competitor_analysis_concurrency", (run_id,) + p)
        if attention != "none":
            for r in reasons:
                ins("fact_competitor_analysis_attention_reason", (run_id,) + r)
        for i in impacts:
            ins("fact_competitor_analysis_impact", (run_id,) + i)
        for o in opens:
            ins("fact_competitor_analysis_open_item", (run_id,) + o)

        # 时间线：把变化落到对应轨，并给事件前后可比窗口
        track_of = {"price_promo": "price_promo", "market": "market",
                    "keyword": "keyword", "traffic": "keyword"}
        seq_by_track = {}
        for c in changes:
            tr = track_of[c[1]]
            seq_by_track[tr] = seq_by_track.get(tr, 0) + 1
            d0 = c[8]
            bf = (dt.date.fromisoformat(d0) - dt.timedelta(days=28)).isoformat()
            bt = (dt.date.fromisoformat(d0) - dt.timedelta(days=1)).isoformat()
            af = d0
            at_ = (dt.date.fromisoformat(d0) + dt.timedelta(days=28)).isoformat()
            ins("fact_competitor_analysis_timeline",
                (run_id, tr, seq_by_track[tr], c[4], d0, c[9], c[0], bf, bt, af,
                 min(at_, as_of), None))
        if sid == "S9":
            ins("fact_competitor_analysis_timeline",
                (run_id, "data_status", 1, "观察中断 14 天", "2026-06-05", "2026-06-18",
                 None, None, None, None, None, "缺口两端不可直接相减"))
            ins("fact_competitor_analysis_timeline",
                (run_id, "data_status", 2, "两个来源成交价冲突", "2026-07-20", as_of,
                 None, None, None, None, None, "差异保留，未抹平"))

        # 与上一版比较
        prev_id = f"{fam_asin}-2026-07-27-1"
        trans = {"high": "escalated", "medium": "sustained", "low": "eased",
                 "none": "cleared"}[attention]
        stmt = {"escalated": "关注程度较上一次分析加重",
                "sustained": "关注程度与上一次分析持平",
                "eased": "关注程度较上一次分析减弱",
                "cleared": "上一次的关注已解除"}[trans]
        ins("fact_competitor_analysis_diff", (run_id, prev_id, trans, stmt,
                                   ",".join(sorted({c[1] for c in changes}))))

        if attention in ("high", "medium") and ev_level == "sufficient":
            fam_changes = [c for c in changes if c[11] == 1]
            if fam_changes:
                reports.append((fam_asin, run_id, fam_changes[0][4],
                                judgment or ev_reason,
                                impacts[0][5] if impacts else None,
                                opens[0][2] if opens else None))
            if attention == "high":
                handoffs.append((f"HO-{run_id}-AD", run_id, "advertising", fam_asin,
                                 own[0], kw, "price" if changes[0][1] == "price_promo" else "market",
                                 changes[0][4], ev_level,
                                 f"{fam_asin} · {changes[0][8]} 至 {as_of} · {changes[0][4]}"))

    # 动态报告
    now = dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"
    for i, (fa, rid, head, body, impact, unconf) in enumerate(reports[:10], start=1):
        ins("fact_competitor_analysis_report",
            (f"RPT-{rid}-01", SCOPE, "2026-07-07", as_of, i, fa, rid,
             head, body, impact, unconf, now))
    for h in handoffs:
        ins("fact_competitor_evidence_handoff", (h[0],) + h[1:] + (now,))

    for k, v in dict(
        dataset_version="agent-v0.1.0", generated_at=now, agent_version=AGENT_VERSION,
        run_count=str(len(fams)), observation_package_version=man["dataset_version"],
        scope=SCOPE,
        provenance="本包为按契约构造的承接数据；换成 Pi Agent 真实输出时表结构不变",
    ).items():
        con.execute("INSERT OR REPLACE INTO competitor_manifest VALUES (?,?)", (k, v))

    con.commit()
    for t in ["fact_competitor_analysis_run", "fact_competitor_analysis_change", "fact_competitor_analysis_timeline",
              "fact_competitor_analysis_concurrency", "fact_competitor_analysis_attention_reason",
              "fact_competitor_analysis_impact", "fact_competitor_analysis_open_item", "fact_competitor_analysis_diff",
              "fact_competitor_analysis_report", "fact_competitor_evidence_handoff"]:
        print(f"{t:36s} {con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]:>6d}")
    con.close()
    print(f"DB {DB} ({os.path.getsize(DB)/1024:.0f} KB)")


if __name__ == "__main__":
    main()
