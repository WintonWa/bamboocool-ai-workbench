#!/usr/bin/env python3
"""页面二决策扩展库 —— 证据层 + 决策链，覆盖多个演示对象。

取代 build_page2_ext_step1.py（那版只做一个对象的证据层）。

设计要点：
  1. 决策链是真实事实的函数，不是写死的文案。
     库存判为 replenishment_gap / overstock / aged_inventory_risk / healthy
     四种处境走四条不同的任务—诊断—建议链，所以选择器里几个对象
     点进去看到的结论真的不一样。
  2. 演示对象全部取自广告包与产品包的 188 交集（342 脊椎），
     跨模块 join 才成立。
  3. 每行带 value_origin：direct 客户原值 / derived 派生 / constructed 构造。
  4. 规则未确认时 exact_* 一律 None，只给方向。
  5. 每条任务、对照、诊断、建议的 evidence_ids 只能引用本对象的证据 id。
"""
import json
import os
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
ADS = os.path.join(HERE, 'v0.2.0', 'advertising_demo.sqlite')
PROD = ('/Users/linsen/BAM/02-产品销售库存模块/'
        '02-数据构建/v0.3.0/bamboocool_product_sales_inventory_v0.3.0.sqlite')
OUT_DIR = os.path.join(HERE, 'page2-ext')
OUT = os.path.join(OUT_DIR, 'page2_decision_ext.sqlite')

AS_OF = '2026-08-03'
WIN = ('2026-07-01', '2026-07-31')
PROMO_ROLES = ('promoted_asin', 'positive_spend_asin', 'target_asin',
               'matched_asin')

# 五个处境互不相同的真实对象。scenario 只用来挑关键词/竞品叙事，
# 任务与诊断由库存判定和趋势算出来，不由这里写死。

# 产品目标是运营填的，这里给的是运营口径的意图——只说想做什么，
# 不含任何推断数字或判定结论（那些是 Agent 该产出的）。
OPERATOR_GOAL_NOTE = {
    "稳定经营并补齐库存承接": "保住现有规模，先把库存承接补齐",
    "加速去库存并保住效率": "优先清库存，效率不要恶化太多",
    "优先处理高库龄库存": "先处理高库龄那部分",
    "维持当前规模与效率": "维持现状，不做大动作",
}
DEMO = [
    {'asin': 'B0B3LWGP36', 'scenario': 'core_word_defense'},
    {'asin': 'B0B3M8S4CQ', 'scenario': 'clearance_traffic'},
    {'asin': 'B0B6ZT7W64', 'scenario': 'aged_cost'},
    {'asin': 'B0B3MBYGR5', 'scenario': 'healthy_hold'},
    {'asin': 'B0CJV56N43', 'scenario': 'efficiency_watch'},
]

DDL = """
create table ext_meta(key text primary key, value text);

create table ext_product_goal(
  goal_version text primary key, child_asin text not null,
  goal_type text not null, goal_label text not null,
  goal_status text not null, rationale text,
  value_origin text not null, source_ref text);

create table ext_goal_constraint(
  constraint_id text primary key, goal_version text not null,
  kind text not null, domain text not null, label text not null,
  detail text, is_satisfied integer, evidence_ref text,
  value_origin text not null);

create table ext_keyword_position(
  kw_id text primary key, child_asin text not null, keyword text not null,
  monthly_search integer, organic_rank integer, organic_rank_prev integer,
  ad_rank integer, ad_impression_share real, covered_by_ad integer,
  position_trend text, limited_by text, observed_at text,
  value_origin text not null, source_ref text);

create table ext_keyword_match(
  match_id text primary key, kw_id text not null, match_level text not null,
  demand_side text, product_side text, basis text,
  value_origin text not null);

create table ext_competitor_pressure(
  pressure_id text primary key, child_asin text not null,
  competitor_asin text not null, brand text, pressure_type text not null,
  pressure_label text not null, detail text, observed_at text,
  is_verified integer, value_origin text not null, source_ref text);

create table ext_decision_context(
  decision_id text primary key, child_asin text not null, parent_asin text,
  goal_version text not null, observe_window_start text,
  observe_window_end text, data_as_of text, rule_status text not null,
  purpose_confirmed_n integer, purpose_pending_n integer,
  scenario text, decision_at text, previous_decision_id text,
  value_origin text not null);

create table ext_decision_evidence(
  evidence_id text primary key, decision_id text not null,
  evidence_type text not null, evidence_title text not null,
  evidence_payload text, observed_at text, valid_as_of text,
  evidence_nature text not null, evidence_status text not null,
  caveat text, jump_to text, value_origin text not null, source_ref text);

-- Agent 第一段：应有广告任务
create table ext_required_ad_task(
  task_id text primary key, decision_id text not null,
  goal_version text not null, task_type text not null,
  task_direction text not null, priority text not null,
  target_scope text, constraints text, evaluation_direction text,
  stop_condition text, applies_from text, applies_to text,
  rule_status text not null, exact_budget real, exact_bid real,
  exact_placement_adjustment real, evidence_ids text,
  inventory_constrained integer, value_origin text not null);

-- Agent 第二段：目标—结构—表现对照
create table ext_task_ad_object(
  mapping_id text primary key, task_id text not null,
  ad_object_id text, coverage_status text not null,
  attribution_limit text not null, target_fit text,
  result_supports_purpose text, gap_source text not null,
  basis_level text not null, evidence_ids text,
  is_automatic_error integer, note text, value_origin text not null);

-- Agent 第三段：诊断
create table ext_diagnosis(
  diagnosis_id text primary key, decision_id text not null,
  task_id text, problem_type text not null, impacted_goal text,
  priority text not null, confidence text not null, evidence_ids text,
  uncertainty text, missing_input text, check_direction text,
  basis_type text not null, causal_claim integer,
  what_happened text, value_origin text not null);

-- Agent 第四段：调整方案
create table ext_recommendation(
  recommendation_id text primary key, decision_id text not null,
  diagnosis_id text, goal_version text, ad_purpose text,
  ad_object_id text, structure_gap_id text, direction text not null,
  rationale text, preconditions text, risks text, uncertainty text,
  observation_metrics text, review_windows text, d7_not_required integer,
  rule_status text not null, exact_value text, value_origin text not null);

-- 板块7 覆盖说明：方案列了 10 类诊断，本次命中哪几类
create table ext_diagnosis_coverage(
  cov_id text primary key, decision_id text not null,
  problem_type text not null, hit integer not null, why_not text);

-- 板块5 结构问题标注
create table ext_structure_issue(
  issue_id text primary key, decision_id text not null,
  ad_object_id text, issue_type text not null, label text not null,
  detail text, value_origin text not null);
"""

# 方案 4.9 列出的十类诊断范围
DIAG_TYPES = [
    ('GOAL_PURPOSE_MISMATCH', '产品目标与广告目的不一致'),
    ('REQUIRED_TASK_MISSING', '必要广告任务缺失'),
    ('DUPLICATE_TASK_OWNERS', '多个广告组重复承担相同任务'),
    ('MIXED_PURPOSE_GROUP', '一个广告组混合多个难以同时评价的目的'),
    ('ATTRIBUTION_UNCLEAR', '广告对象与子 ASIN 关系不清'),
    ('PERFORMANCE_NOT_SUPPORTING', '当前表现不支撑已确认的广告目的'),
    ('KEYWORD_COVERAGE_GAP', '关键词机会存在但覆盖或位置不足'),
    ('COMPETITOR_NO_TASK', '竞品压力存在但没有对应任务'),
    ('INVENTORY_COVERAGE_RISK', '库存无法承接现有或计划中的强度'),
    ('INSUFFICIENT_EVIDENCE', '数据、目的、规则或样本不足暂时无法判断'),
]

# 库存处境 → 目标类型与叙事
RISK_GOAL = {
    'replenishment_gap': ('stable_operation', '稳定经营并补齐库存承接'),
    'overstock': ('inventory_clearance', '加速去库存并保住效率'),
    'aged_inventory_risk': ('inventory_clearance', '优先处理高库龄库存'),
    'healthy': ('stable_operation', '维持当前规模与效率'),
}

KW_SEED = {
    'core_word_defense': [
        ('mens underwear', 908485, 18, 22, 'holding', 'high',
         '买的是男士内裤这个大类需求', '产品就是男士长平角内裤',
         '词的需求面与产品品类完全一致，是核心词'),
        ('mens boxer briefs', 304295, 9, 7, 'losing', 'high',
         '明确要长平角这个款型', '本品即长平角',
         '款型词与产品款型一致，且是当前主要成交词'),
        ('athletic underwear men', 13190, 31, 29, 'losing', 'medium',
         '强调运动场景与功能', '产品有透气与弹性卖点但未主打运动场景',
         '功能面部分匹配，场景面未验证，属可测试而非核心'),
        ('cotton boxer briefs men', 46200, None, None, 'absent', 'low',
         '指定纯棉材质', '本品是竹纤维不是纯棉',
         '材质面直接冲突，不应把它当机会词'),
    ],
    'clearance_traffic': [
        ('bamboo underwear men', 27500, 12, 14, 'gaining', 'high',
         '指定竹纤维材质', '本品主材就是竹纤维',
         '材质面精准匹配，是本品最该守的词'),
        ('mens trunks', 74100, 26, 21, 'losing', 'medium',
         '要的是 Trunks 短款', '本品是长平角不是 Trunks',
         '款型有差异，成交能成但退货风险需观察'),
        ('breathable underwear men', 8900, None, None, 'absent', 'high',
         '强调透气', '透气是本品主打卖点之一',
         '卖点匹配但目前完全没有广告覆盖，是明确缺口'),
    ],
    'aged_cost': [
        ('mens underwear pack', 33400, 44, 38, 'losing', 'medium',
         '要多件装', '本品有装盒规格可对上',
         '规格面能对上，但当前位置很靠后'),
        ('cheap mens underwear', 12600, None, None, 'absent', 'low',
         '找低价', '本品定位不是低价',
         '价格面冲突，即便清库存也不该靠这个词拉量'),
    ],
    'healthy_hold': [
        ('mens boxer briefs', 304295, 14, 15, 'holding', 'high',
         '明确要长平角这个款型', '本品即长平角',
         '款型一致，当前位置稳定'),
        ('soft underwear men', 6700, 22, 22, 'holding', 'medium',
         '强调柔软手感', '竹纤维手感是本品卖点',
         '卖点面匹配，量小但稳'),
    ],
    'efficiency_watch': [
        ('mens underwear', 908485, 35, 30, 'losing', 'high',
         '买的是男士内裤这个大类需求', '产品就是男士长平角内裤',
         '品类一致但位置在下滑'),
        ('boxer briefs for men', 58300, 19, 19, 'holding', 'high',
         '要长平角', '本品即长平角',
         '款型一致，位置持平'),
        ('mens underwear sale', 9800, None, None, 'absent', 'low',
         '在找促销', '本品当前无进行中促销',
         '意图面与当前状态不符'),
    ],
}


def jd(o) -> str:
    return json.dumps(o, ensure_ascii=False, sort_keys=True)


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    if os.path.exists(OUT):
        os.remove(OUT)
    src = sqlite3.connect('file:%s?mode=ro' % ADS, uri=True)
    src.row_factory = sqlite3.Row
    src.execute("attach database ? as prod", ("file:%s?mode=ro" % PROD,))
    db = sqlite3.connect(OUT)
    db.executescript(DDL)
    ph = ','.join('?' * len(PROMO_ROLES))
    summary = []

    for spec in DEMO:
        A, scen = spec['asin'], spec['scenario']
        did = 'dec_%s_%s' % (A, AS_OF.replace('-', ''))
        gv = 'goal_%s' % A
        E = lambda s: 'ev_%s_%s' % (A[-4:], s)  # noqa: E731

        pc = src.execute(
            "select child_asin, parent_asin, product_lifecycle, product_name,"
            " style_name, colorway, size, category, category_rank, rating,"
            " operator from prod.dim_product_child where child_asin=?",
            (A,)).fetchone()
        win = src.execute("select * from prod.fact_sales_window"
                          " where child_asin=?", (A,)).fetchone()
        dec = src.execute("select * from prod.fact_child_inventory_decision"
                          " where child_asin=?", (A,)).fetchone()
        inv = src.execute(
            "select closing_fba_sellable, coverage_days, stockout_flag,"
            " fba_inbound, overseas_inbound"
            " from prod.fact_child_inventory_daily"
            " where child_asin=? and date=?", (A, AS_OF)).fetchone()
        plan_promo = src.execute(
            "select min(date) d0, max(date) d1, promotion_type, promotion_id"
            " from prod.plan_child_promotion_daily where child_asin=?"
            " and promotion_type<>'none' group by promotion_id,"
            " promotion_type order by d0 limit 3", (A,)).fetchall()
        supply = src.execute(
            "select eta_earliest, eta_latest, allocated_units, event_status"
            " from prod.bridge_supply_event_child where child_asin=?"
            " order by eta_earliest limit 3", (A,)).fetchall()
        # 一个广告对象可能同时挂多个 relation_role（既是 promoted 又是
        # positive_spend）。select distinct 是按整行去重，role 不同就成两行，
        # 花费会被重复累加——所以必须按 ad_object_id 分组，role 聚成一列。
        ads = src.execute("""
            select o.ad_object_id, o.object_level, o.ad_type,
                   o.campaign_name, o.ad_group_name, o.target_text,
                   o.match_type,
                   group_concat(distinct b.relation_role) relation_roles,
                   f.spend, f.ad_sales, f.acos, f.roas, f.clicks, f.orders,
                   f.impressions, f.attribution_days
            from bridge_ad_object_product b
            join dim_ad_object o on o.ad_object_id=b.ad_object_id
            left join fact_ad_performance f on f.ad_object_id=o.ad_object_id
                 and f.metric_basis='report_month_total'
            where b.child_asin=? and b.relation_role in (%s)
            group by o.ad_object_id
            order by f.spend desc""" % ph, (A,) + PROMO_ROLES).fetchall()
        purch = src.execute("""
            select count(distinct b.ad_object_id) n, sum(f.spend) sp,
                   sum(f.ad_sales) sa
            from bridge_ad_object_product b
            left join fact_ad_performance f on f.ad_object_id=b.ad_object_id
                 and f.metric_basis='report_month_total'
            where b.child_asin=? and b.relation_role='purchased_asin'
              and b.ad_object_id not in (select ad_object_id from
                  bridge_ad_object_product where child_asin=?
                  and relation_role in (%s))""" % ph,
            (A, A) + PROMO_ROLES).fetchone()
        cn = sorted({r['campaign_name'] for r in ads if r['campaign_name']})
        cpq = ','.join('?' * len(cn)) if cn else "''"
        terms = src.execute(
            "select search_term, impression_rank, impression_share,"
            " impressions, clicks from fact_search_term_share"
            " where campaign_name in (%s) order by impressions desc limit 5"
            % cpq, tuple(cn)).fetchall()
        purpose = src.execute("""
            select sum(confirmation_status='confirmed') c,
                   sum(confirmation_status<>'confirmed') p
            from fact_ad_label_version where label_type='AD_PURPOSE'
              and ad_object_id in (select ad_object_id from
                  bridge_ad_object_product where child_asin=?
                  and relation_role in (%s))""" % ph,
            (A,) + PROMO_ROLES).fetchone()

        risk = dec['base_risk_status']
        gtype, glabel = RISK_GOAL.get(risk, ('stable_operation', '维持现状'))
        trend = win['daily_avg_3d'] / win['daily_avg_90d'] - 1
        spend_tot = sum(r['spend'] or 0 for r in ads)
        sales_tot = sum(r['ad_sales'] or 0 for r in ads)
        acos_tot = (spend_tot / sales_tot) if sales_tot > 0 else None

        # -------------------------------------------------- 目标与约束
        # 产品目标是运营在系统里填的输入，不是我们推出来的判断
        # （王楠 2026-08-31 拍定）。所以这里不写推断链，只写运营口径的意图，
        # 状态直接是已确认，来源标 operator_set。
        # 详见 00-通用方法与规范/08-Agent需求与数据契约要则 §2 产品定位。
        db.execute("insert into ext_product_goal values(?,?,?,?,?,?,?,?)",
                   (gv, A, gtype, glabel, 'confirmed',
                    OPERATOR_GOAL_NOTE.get(glabel, '运营设定'),
                    'constructed', 'operator_set'))
        cons = []
        if risk in ('replenishment_gap',):
            cons.append(('hard', 'inventory',
                         '安全库存将在 %s 被击穿' % dec['safety_breach_date'],
                         '动态安全 %s 天 / %s 件；建议补 %s 件。'
                         '扩量前必须先解决承接。'
                         % (dec['dynamic_safety_days'],
                            dec['dynamic_safety_units'],
                            dec['suggested_replenishment_qty']),
                         0, E('inventory'), 'derived'))
            if dec['stress_stockout_date'] not in (None, 'none'):
                cons.append(('hard', 'inventory',
                             '压力情景 %s 断货' % dec['stress_stockout_date'],
                             '最晚下单日 %s。' % dec['latest_order_date'],
                             0, E('inventory'), 'derived'))
        if risk == 'overstock':
            cons.append(('observe', 'inventory',
                         '库存偏高，覆盖 %.0f 天' % inv['coverage_days'],
                         '不构成扩量阻断，反而需要流量把货带走；'
                         '但要盯住效率别为了清货把 ACoS 拉爆。',
                         1, E('inventory'), 'derived'))
        if risk == 'aged_inventory_risk':
            cons.append(('hard', 'inventory',
                         '存在高库龄风险',
                         '库龄成本会随时间叠加，处理窗口有限。',
                         0, E('inventory'), 'derived'))
        cons.append(('observe', 'traffic', '销量趋势',
                     '3 日 %.0f / 7 日 %.0f / 30 日 %.0f / 90 日 %.0f 件'
                     % (win['daily_avg_3d'], win['daily_avg_7d'],
                        win['daily_avg_30d'], win['daily_avg_90d']),
                     None, E('trend'), 'derived'))
        if plan_promo:
            cons.append(('observe', 'event', '临近计划中促销',
                         '、'.join('%s %s 起' % (p['promotion_type'], p['d0'])
                                  for p in plan_promo[:2]),
                         None, E('events'), 'direct'))
        cons.append(('observe', 'cost', '成本边界尚未配置',
                     '客户未确认单组 ACoS 上限与可接受 CPC 区间，'
                     '效率判断只能用自身历史。', None, None, 'constructed'))
        for i, (kind, dom, lab, det, sat, ev, vo) in enumerate(cons, 1):
            db.execute("insert into ext_goal_constraint values"
                       "(?,?,?,?,?,?,?,?,?)",
                       ('c_%s_%02d' % (A[-4:], i), gv, kind, dom, lab, det,
                        sat, ev, vo))

        # -------------------------------------------------- 关键词与竞品
        tmap = {(t['search_term'] or '').lower(): t for t in terms}
        kw_ids = []
        for i, (kw, msv, orank, oprev, ktrend, mlevel, dside, pside, basis) \
                in enumerate(KW_SEED[scen], 1):
            kid = 'kw_%s_%02d' % (A[-4:], i)
            kw_ids.append((kid, ktrend, mlevel, kw))
            st = tmap.get(kw.lower())
            db.execute("insert into ext_keyword_position values"
                       "(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (kid, A, kw, msv, orank, oprev,
                        int(st['impression_rank']) if st
                        and st['impression_rank'] else
                        (None if ktrend == 'absent' else 2),
                        st['impression_share'] if st else
                        (None if ktrend == 'absent' else 0.12),
                        0 if ktrend == 'absent' else 1, ktrend,
                        'inventory' if (risk == 'replenishment_gap'
                                        and mlevel == 'high') else 'none',
                        AS_OF, 'derived' if st else 'constructed',
                        'fact_search_term_share' if st else 'constructed'))
            db.execute("insert into ext_keyword_match values(?,?,?,?,?,?,?)",
                       ('m_%s_%02d' % (A[-4:], i), kid, mlevel, dside, pside,
                        basis, 'constructed'))
        for i, (ptype, lab, det, ver) in enumerate([
                ('price', '头部竞品定价低于本品',
                 'Hanes B086L4BXZC 售价 $21.58，小类目 BSR 第 1，'
                 '月销 175,973 件。', 0),
                ('rank', '小类目排名被压制', '该竞品长期占据小类目第 1。', 1),
                ('keyword_entry', '核心词入口被占',
                 '在核心款型词上该竞品广告位先于本品。', 0)], 1):
            db.execute("insert into ext_competitor_pressure values"
                       "(?,?,?,?,?,?,?,?,?,?,?)",
                       ('p_%s_%02d' % (A[-4:], i), A, 'B086L4BXZC', 'Hanes',
                        ptype, lab, det, AS_OF, ver,
                        'derived' if ptype in ('price', 'rank')
                        else 'constructed', 'competitor evidence'))

        # -------------------------------------------------------- 证据包
        ev_rows = [
            (E('goal'), 'PRODUCT_GOAL', '当前产品目标',
             {'goal_type': gtype, 'goal_label': glabel,
              'status': 'confirmed'},
             'confirmed', None,
             None, 'constructed'),
            (E('stage'), 'PRODUCT_STAGE', '产品阶段与定位',
             {'lifecycle': pc['product_lifecycle'],
              'parent': pc['parent_asin'], 'product_name': pc['product_name'],
              'style': pc['style_name'], 'colorway': pc['colorway'],
              'size': pc['size'], 'category': pc['category'],
              'category_rank': pc['category_rank'], 'rating': pc['rating'],
              'operator': pc['operator']},
             'fact', None, 'product', 'direct'),
            (E('trend'), 'SALES_TREND', '销量趋势六窗口',
             {k: win[k] for k in ('daily_avg_3d', 'daily_avg_7d',
                                  'daily_avg_14d', 'daily_avg_30d',
                                  'daily_avg_60d', 'daily_avg_90d',
                                  'units_30d')},
             'fact', '嵌套累计窗口，短窗低于长窗即为走低', 'product', 'direct'),
            (E('inventory'), 'INVENTORY', '库存承接与断货判定',
             {'closing_fba_sellable': inv['closing_fba_sellable'],
              'coverage_days': inv['coverage_days'],
              'fba_inbound': inv['fba_inbound'],
              'risk_status': risk,
              'safety_breach_date': dec['safety_breach_date'],
              'base_stockout_date': dec['base_stockout_date'],
              'stress_stockout_date': dec['stress_stockout_date'],
              'latest_order_date': dec['latest_order_date'],
              'suggested_replenishment_qty':
                  dec['suggested_replenishment_qty'],
              'dynamic_safety_days': dec['dynamic_safety_days'],
              'confidence_score': dec['confidence_score']},
             'fact', '断货日分基准与压力两个情景', 'inventory', 'direct'),
            (E('events'), 'BUSINESS_EVENT', '临近的关键业务事件',
             {'planned': [{'type': p['promotion_type'], 'from': p['d0'],
                           'to': p['d1']} for p in plan_promo],
              'inbound': [{'eta_earliest': s['eta_earliest'],
                           'eta_latest': s['eta_latest'],
                           'qty': s['allocated_units'],
                           'status': s['event_status']} for s in supply]},
             'fact', '计划中促销与到货 ETA 会改变扩量时点',
             'inventory', 'direct'),
            (E('keyword'), 'KEYWORD', '核心关键词位置与匹配度',
             {'count': len(kw_ids),
              'covered': sum(1 for _, t, _, _ in kw_ids if t != 'absent'),
              'losing': sum(1 for _, t, _, _ in kw_ids if t == 'losing'),
              'absent_high_match': [k for _, t, m, k in kw_ids
                                    if t == 'absent' and m == 'high']},
             'fact', '自然位为构造值，广告位与份额来自搜索词份额报表',
             'keyword', 'constructed'),
            (E('competitor'), 'COMPETITOR', '竞品压力分类',
             {'competitor': 'B086L4BXZC', 'brand': 'Hanes',
              'types': ['price', 'rank', 'keyword_entry']},
             'fact', '同期变化不等于因果，未验证项已标注',
             'competitor', 'derived'),
            (E('adperf'), 'AD_PERFORMANCE', '推广该子体的广告表现',
             {'object_count': len(ads), 'spend': round(spend_tot, 2),
              'ad_sales': round(sales_tot, 2),
              'acos': round(acos_tot, 4) if acos_tot else None,
              'objects': [{'name': r['ad_group_name'] or r['campaign_name'],
                           'ad_type': r['ad_type'],
                           'level': r['object_level'],
                           'spend': r['spend'], 'acos': r['acos']}
                          for r in ads]},
             'fact', 'SP 与 SD/SB 归因窗口不同不可相加', None, 'direct'),
            (E('purchgap'), 'ATTRIBUTION_GAP', '成交归属但非推广',
             {'objects': purch['n'], 'spend': purch['sp'],
              'ad_sales': purch['sa']},
             'fact', '这些广告推的不是本品，销售额含其他 SKU',
             None, 'direct'),
            (E('share'), 'AD_PLACEMENT', '搜索词展示份额',
             {'terms': [{'term': t['search_term'],
                         'rank': t['impression_rank'],
                         'share': t['impression_share'],
                         'impressions': t['impressions']} for t in terms]},
             'fact', '份额是相对同类广告的位置，不是绝对量', None, 'direct'),
        ]
        for eid, etype, title, payload, nature, caveat, jump, vo in ev_rows:
            db.execute("insert into ext_decision_evidence values"
                       "(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (eid, did, etype, title, jd(payload), AS_OF, AS_OF,
                        nature, 'current', caveat, jump, vo, 'page2-ext'))

        db.execute("insert into ext_decision_context values"
                   "(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (did, A, pc['parent_asin'], gv, WIN[0], WIN[1], AS_OF,
                    'unconfirmed', purpose['c'] or 0, purpose['p'] or 0,
                    scen, AS_OF, None, 'constructed'))

        # ============================================ Agent 第一段：任务
        tasks = []
        T = lambda s: 't_%s_%s' % (A[-4:], s)  # noqa: E731
        if risk == 'replenishment_gap':
            tasks.append((T('inbound'), 'VERIFY_INBOUND_BEFORE_SCALE',
                          'PREREQUISITE', 'P0', A,
                          ['立即可售覆盖有限', '入库尚未核实'],
                          '先核验入库，再判断是否可扩量',
                          '入库未确认或立即可售覆盖继续下降',
                          [E('goal'), E('inventory'), E('events')], 1))
        if risk == 'aged_inventory_risk':
            tasks.append((T('aged'), 'CLEAR_AGED_INVENTORY', 'ADJUST', 'P0',
                          A, ['库龄成本随时间叠加', '处理窗口有限'],
                          '看高库龄部分是否被带走',
                          '库龄成本超过清货收益', [E('inventory')], 1))
        if risk == 'overstock':
            tasks.append((T('sell'), 'ACCELERATE_SELL_THROUGH', 'ADJUST',
                          'P1', A,
                          ['效率不能为清货无上限恶化', '无客户确认 ACoS 上限'],
                          '看售出速度与 ACoS 同时变化',
                          'ACoS 恶化超过自身历史区间', [E('inventory'),
                                                E('trend')], 0))
        high_absent = [k for _, t, m, k in kw_ids
                       if t == 'absent' and m == 'high']
        losing = [k for _, t, m, k in kw_ids if t == 'losing' and m == 'high']
        if losing:
            tasks.append((T('defend'), 'PROTECT_CORE_QUERY_VISIBILITY',
                          'OBSERVE', 'P1', '核心搜索词',
                          (['产品目标待确认']
                           + (['库存为前置条件']
                              if risk == 'replenishment_gap' else [])),
                          '维持核心词可见性并观察效率',
                          '库存约束未解除或核心词位置显著变化',
                          [E('keyword'), E('competitor')]
                          + ([E('inventory')] if risk == 'replenishment_gap'
                             else []),
                          1 if risk == 'replenishment_gap' else 0))
        if high_absent:
            tasks.append((T('build'), 'COVER_MATCHED_QUERY_GAP', 'BUILD',
                          'P1', '、'.join(high_absent),
                          ['无现有对象承接', '需低成本测试验证'],
                          '看新增覆盖能否拿到位置',
                          '测试期内无位置或效率明显差于现有词',
                          [E('keyword')], 0))
        if acos_tot is not None:
            tasks.append((T('eff'), 'CONTROL_EFFICIENCY_DRIFT', 'OBSERVE',
                          'P1' if risk != 'healthy' else 'P2',
                          '可比广告组', ['没有客户确认的单组 ACoS 上限'],
                          '相对自身历史检查 ACoS 与 CVR',
                          '缺少可比日行或同期变量无法排除',
                          [E('adperf'), E('share')], 0))
        if purch['n'] and purch['n'] > 3:
            tasks.append((T('attrib'), 'CLARIFY_ATTRIBUTION_BOUNDARY',
                          'REQUEST_INFO', 'P2', A,
                          ['共享归因无法拆分'],
                          '确认成交该归给哪个广告目的',
                          '归因边界已由运营确认', [E('purchgap')], 0))
        if not tasks:
            tasks.append((T('keep'), 'MAINTAIN_CURRENT_SETUP', 'KEEP', 'P2',
                          A, [], '维持并观察', '出现明显恶化',
                          [E('trend')], 0))
        for tid, ttype, tdir, pri, scope, cts, evald, stopc, evs, invc in tasks:
            db.execute("insert into ext_required_ad_task values"
                       "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (tid, did, gv, ttype, tdir, pri, scope, jd(cts),
                        evald, stopc, AS_OF, None, 'unconfirmed',
                        None, None, None, jd(evs), invc, 'constructed'))

        # ==================================== Agent 第二段：对照
        groups = [r for r in ads if r['object_level'] == 'AD_GROUP']
        camps = [r for r in ads if r['object_level'] == 'CAMPAIGN']
        pool = groups + camps
        shared_n = {}
        for r in ads:
            shared_n[r['ad_object_id']] = src.execute(
                "select count(distinct child_asin) n from"
                " bridge_ad_object_product where ad_object_id=?"
                " and relation_role='promoted_asin'",
                (r['ad_object_id'],)).fetchone()['n']
        mi = 0
        for tid, ttype, tdir, pri, scope, cts, evald, stopc, evs, invc in tasks:
            mi += 1
            mid = 'map_%s_%02d' % (A[-4:], mi)
            if ttype in ('VERIFY_INBOUND_BEFORE_SCALE',
                         'COVER_MATCHED_QUERY_GAP'):
                db.execute("insert into ext_task_ad_object values"
                           "(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (mid, tid, None, 'missing', 'unattributed', None,
                            None,
                            'structure' if ttype == 'COVER_MATCHED_QUERY_GAP'
                            else 'evidence',
                            'conditional', jd(evs), 0,
                            '当前没有广告对象承接这项任务', 'constructed'))
                continue
            obj = pool[mi % len(pool)] if pool else None
            if obj is None:
                continue
            sh = shared_n.get(obj['ad_object_id'], 1)
            cov = 'mixed' if sh > 1 else 'covered'
            fit = ('与任务目标一致' if ttype != 'CLARIFY_ATTRIBUTION_BOUNDARY'
                   else '该对象推的不是本品')
            sup = (None if obj['acos'] is None else
                   ('支撑' if obj['acos'] < 0.45 else '不支撑，效率高于可比区间'))
            db.execute("insert into ext_task_ad_object values"
                       "(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (mid, tid, obj['ad_object_id'], cov,
                        'shared' if sh > 1 else 'exclusive', fit, sup,
                        'performance' if sup and sup.startswith('不')
                        else ('evidence' if sup is None else 'none'),
                        'self_history' if obj['acos'] is not None
                        else 'conditional', jd(evs), 0,
                        '该对象同时推 %d 个子 ASIN' % sh if sh > 1 else None,
                        'derived'))

        # ==================================== Agent 第三段：诊断
        diags = []
        D = lambda s: 'd_%s_%s' % (A[-4:], s)  # noqa: E731
        if risk == 'replenishment_gap':
            diags.append((D('inv'), T('inbound'), 'INVENTORY_COVERAGE_RISK',
                          glabel, 'P0', 'high', [E('inventory')],
                          '在途到仓时间与可售转化时间未确认', '最新入库确认',
                          '先核验入库承接能力', 'conditional',
                          '安全库存 %s 被击穿，压力情景 %s 断货，'
                          '最晚下单日 %s 已过'
                          % (dec['safety_breach_date'],
                             dec['stress_stockout_date'],
                             dec['latest_order_date'])))
        if risk == 'aged_inventory_risk':
            diags.append((D('aged'), T('aged'), 'INVENTORY_COVERAGE_RISK',
                          glabel, 'P0', 'high', [E('inventory'), E('trend')],
                          '库龄分档与费率未在本模块核验', '库龄分档明细',
                          '确认高库龄部分的处理窗口', 'conditional',
                          '库存判定为高库龄风险，近 3 日日均 %+.0f%% 回升，'
                          '有机会带走但窗口有限' % (trend * 100)))
        if risk == 'overstock':
            diags.append((D('over'), T('sell'), 'INVENTORY_COVERAGE_RISK',
                          glabel, 'P1', 'high', [E('inventory'), E('trend')],
                          '清货速度与效率的取舍边界未确认',
                          '客户可接受的清货期 ACoS 上限',
                          '看售出速度与效率同时变化', 'conditional',
                          '覆盖 %.0f 天属偏高，需要流量把货带走'
                          % inv['coverage_days']))
        if losing:
            diags.append((D('kw'), T('defend'), 'KEYWORD_COVERAGE_GAP',
                          '保护核心流量位置', 'P1', 'medium',
                          [E('keyword'), E('competitor')],
                          '竞品数据不能证明广告效率因果',
                          '运营确认核心词清单与容忍区间',
                          '观察核心词位置与广告承接', 'conditional',
                          '%s 位置正在下滑，同期该词入口被头部竞品占据'
                          % '、'.join(losing)))
        if high_absent:
            diags.append((D('gap'), T('build'), 'REQUIRED_TASK_MISSING',
                          glabel, 'P1', 'medium', [E('keyword')],
                          '新词测试的效率未知', '低成本测试预算边界',
                          '先小量验证再决定是否扩', 'conditional',
                          '%s 与产品高度匹配但当前完全没有广告覆盖'
                          % '、'.join(high_absent)))
        if acos_tot is not None:
            worse = acos_tot > 0.45
            diags.append((D('eff'), T('eff'),
                          'PERFORMANCE_NOT_SUPPORTING' if worse
                          else 'GOAL_PURPOSE_MISMATCH',
                          glabel, 'P1' if worse else 'P2', 'medium',
                          [E('adperf'), E('share')],
                          '未控制竞价、自然位、促销和流量结构变化',
                          '同期变更记录', '按同粒度同归因继续观察',
                          'self_history', '推广对象合计 ACoS %.1f%%，%s'
                          % (acos_tot * 100,
                             '高于可比区间' if worse else '在可比区间内')))
        if purch['n'] and purch['n'] > 3:
            diags.append((D('attr'), T('attrib'), 'ATTRIBUTION_UNCLEAR',
                          glabel, 'P2', 'high', [E('purchgap')],
                          '共享广告的结果无法按子 ASIN 拆分',
                          '运营确认归因边界', '先明确边界再评价效率',
                          'conditional',
                          '%d 个广告对象带来本品成交但推的不是本品，'
                          '这些对象花费 %s' % (purch['n'],
                                          '$%s' % format(round(purch['sp']
                                                               or 0), ','))))
        mixed = [r for r in ads if shared_n.get(r['ad_object_id'], 1) > 1]
        if mixed:
            diags.append((D('mix'), None, 'MIXED_PURPOSE_GROUP', glabel,
                          'P2', 'medium', [E('adperf')],
                          '混合目的下单一指标无法评价',
                          '按目的拆分或确认可合并评价',
                          '确认是否需要拆分', 'conditional',
                          '%d 个广告对象同时推多个子 ASIN' % len(mixed)))
        for (dxid, tid, ptype, goal, pri, conf, evs, unc, miss, chk, basis,
             what) in diags:
            db.execute("insert into ext_diagnosis values"
                       "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (dxid, did, tid, ptype, goal, pri, conf, jd(evs), unc,
                        miss, chk, basis, 0, what, 'constructed'))

        hit = {d[2] for d in diags}
        for i, (ptype, label) in enumerate(DIAG_TYPES, 1):
            db.execute("insert into ext_diagnosis_coverage values(?,?,?,?,?)",
                       ('cov_%s_%02d' % (A[-4:], i), did, ptype,
                        1 if ptype in hit else 0,
                        None if ptype in hit else '本次未命中'))

        # ==================================== Agent 第四段：建议
        DIRMAP = {
            'INVENTORY_COVERAGE_RISK': ('DEFER' if risk == 'replenishment_gap'
                                        else 'ADJUST'),
            'KEYWORD_COVERAGE_GAP': 'OBSERVE',
            'REQUIRED_TASK_MISSING': 'TEST',
            'PERFORMANCE_NOT_SUPPORTING': 'REQUEST_INFO',
            'GOAL_PURPOSE_MISMATCH': 'KEEP',
            'ATTRIBUTION_UNCLEAR': 'REQUEST_INFO',
            'MIXED_PURPOSE_GROUP': 'SPLIT',
        }
        PURPOSE = {
            'INVENTORY_COVERAGE_RISK': '库存承接约束',
            'KEYWORD_COVERAGE_GAP': '核心词守位',
            'REQUIRED_TASK_MISSING': '缺口词测试',
            'PERFORMANCE_NOT_SUPPORTING': '效率波动核验',
            'GOAL_PURPOSE_MISMATCH': '维持现状',
            'ATTRIBUTION_UNCLEAR': '归因边界核验',
            'MIXED_PURPOSE_GROUP': '结构拆分',
        }
        METRICS = {
            'INVENTORY_COVERAGE_RISK': ['可售库存', '日销量', '可售天数'],
            'KEYWORD_COVERAGE_GAP': ['关键词位置', 'ACoS', 'CVR'],
            'REQUIRED_TASK_MISSING': ['展示', '点击', 'ACoS'],
            'PERFORMANCE_NOT_SUPPORTING': ['ACoS', 'CVR', 'CPC'],
            'GOAL_PURPOSE_MISMATCH': ['ACoS', 'CVR'],
            'ATTRIBUTION_UNCLEAR': ['广告销售额', '订单'],
            'MIXED_PURPOSE_GROUP': ['ACoS', 'CVR', '花费'],
        }
        for i, d in enumerate(diags, 1):
            dxid, tid, ptype = d[0], d[1], d[2]
            m = db.execute("select ad_object_id from ext_task_ad_object"
                           " where task_id=?", (tid,)).fetchone() if tid \
                else None
            oid = m[0] if m else None
            db.execute("insert into ext_recommendation values"
                       "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       ('r_%s_%02d' % (A[-4:], i), did, dxid, gv,
                        PURPOSE.get(ptype, '待定'), oid,
                        None if oid else 'gap_%s' % ptype.lower(),
                        DIRMAP.get(ptype, 'OBSERVE'), d[11],
                        jd(['确认产品目标'] + (['核验库存']
                            if risk == 'replenishment_gap' else [])),
                        jd(['效率漂移'] if ptype != 'INVENTORY_COVERAGE_RISK'
                           else ['断货', '流量流失']),
                        d[7], jd(METRICS.get(ptype, ['ACoS'])),
                        jd(['D+3', 'D+7']), 0, 'unconfirmed', None,
                        'constructed'))

        # -------------------------------------------------- 结构问题标注
        si = 0
        for r in ads:
            sh = shared_n.get(r['ad_object_id'], 1)
            if sh > 1:
                si += 1
                db.execute("insert into ext_structure_issue values"
                           "(?,?,?,?,?,?,?)",
                           ('is_%s_%02d' % (A[-4:], si), did,
                            r['ad_object_id'], 'shared',
                            '共享给 %d 个子 ASIN' % sh,
                            '结果不能全部归到当前子 ASIN', 'derived'))
        if purch['n'] and purch['n'] > 3:
            si += 1
            db.execute("insert into ext_structure_issue values"
                       "(?,?,?,?,?,?,?)",
                       ('is_%s_%02d' % (A[-4:], si), did, None,
                        'unexplained',
                        '%d 个对象带来成交但推的不是本品' % purch['n'],
                        '这部分成交无法归到本品的任何广告目的', 'direct'))

        summary.append({
            'asin': A, 'risk': risk, 'goal': glabel,
            'trend': trend, 'spend': spend_tot, 'acos': acos_tot,
            'objects': len(ads), 'tasks': len(tasks), 'diags': len(diags),
            'hit_types': len(hit), 'purch': purch['n'],
        })

    for k, v in [('built_at', AS_OF), ('as_of', AS_OF),
                 ('ads_source', 'v0.2.0'), ('product_source', 'v0.3.0'),
                 ('demo_objects', jd([d['asin'] for d in DEMO]))]:
        db.execute("insert into ext_meta values(?,?)", (k, v))
    db.commit()

    print('=== 扩展库 %s ===' % OUT)
    for t in ('ext_product_goal', 'ext_goal_constraint',
              'ext_keyword_position', 'ext_keyword_match',
              'ext_competitor_pressure', 'ext_decision_context',
              'ext_decision_evidence', 'ext_required_ad_task',
              'ext_task_ad_object', 'ext_diagnosis',
              'ext_diagnosis_coverage', 'ext_recommendation',
              'ext_structure_issue'):
        print('  %-26s %d 行'
              % (t, db.execute('select count(*) from %s' % t).fetchone()[0]))

    print('\n=== 五个对象的处境对比（选择器里点进去看到的应当不一样）===')
    print('%-13s %-20s %6s %5s %9s %4s %4s %4s %4s'
          % ('child_asin', '库存判定', '趋势', 'ACoS', '广告花费',
             '对象', '任务', '诊断', '命中'))
    for s in summary:
        print('%-13s %-20s %+5.0f%% %5s %9s %4d %4d %4d %4d'
              % (s['asin'], s['risk'], s['trend'] * 100,
                 '--' if s['acos'] is None else '%.0f%%' % (s['acos'] * 100),
                 format(round(s['spend']), ','), s['objects'], s['tasks'],
                 s['diags'], s['hit_types']))

    print('\n=== 各对象的任务与建议方向（验证真的分叉）===')
    for s in summary:
        rows = db.execute(
            "select t.task_type, t.priority, r.direction"
            " from ext_required_ad_task t"
            " left join ext_diagnosis d on d.task_id=t.task_id"
            " left join ext_recommendation r on r.diagnosis_id=d.diagnosis_id"
            " where t.decision_id like ? order by t.priority",
            ('%' + s['asin'] + '%',)).fetchall()
        print('  %-13s %s' % (s['asin'], ' · '.join(
            '%s %s→%s' % (r[1], r[0], r[2] or '无建议') for r in rows)))
    db.close()
    src.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
