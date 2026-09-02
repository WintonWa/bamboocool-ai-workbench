# 竞品 Agent 与工作台接口契约

版本 v0.1（2026-08-30）· Agent 走 Pi，只返回结果 · 工作台只读

本文档同时是**承接数据的表结构规格**：Demo 里先由构建脚本按这份契约造出数据把壳子撑起来，
之后 Pi Agent 按同一份表和字段写真结果，前端一行不改。

---

## 0. 四层职责

| 层 | 谁做 | 是否用 LLM | 触发 |
| --- | --- | --- | --- |
| 抓取层 | 定时任务（第三方工具导出 / 接口） | 否 | 按周期（日或周） |
| 观察层 | 构建脚本：归一、去重、冲突保留、连接历史 | 否 | 抓完即跑 |
| 判断层 | **Pi Agent** | 是 | 算子发现变化时自动跑，或运营在快捷位点某个竞品重跑 |
| 呈现层 | 工作台前端：读最新一次分析、组织版图与顺序、跳转与冻结引用 | 否 | 打开即读，秒开 |

分界线：**Agent 只输出判断，不输出观察，也不输出动作。**

| 谁做 | 内容 |
| --- | --- |
| **Agent** | 变化结论及依据、同期关系是否成立、关注程度分级与理由、可能影响的自有产品与关键词、待确认事项、动态报告条目 |
| **工作台** | 四类变化版图的组织与计数去重、关注顺序排列、时间线渲染与前后开窗显示、跳转上下文、版本冻结、降级分支 |

不允许出现在 Agent 输出里的两样东西：**广告动作/预算/出价**（属广告模块），**综合威胁分数**（方案要求分级 + 可解释依据）。

---

## 1. 两个数据库

| 库 | 内容 | 谁写 | 工作台 |
| --- | --- | --- | --- |
| 观察库 `competitor_observation.sqlite` | 竞品身份、父子与报价、竞争关系、关键词、逐日价格活动、逐日市场表现、关键词位置、流量结构、数据状态、自有侧逐日价格 | 抓取层 + 观察层 | 只读 |
| Agent 库 `competitor_agent.sqlite` | 本文档第 3 节的九张表 | **Pi Agent** | 只读 |

工作台用 `ATTACH DATABASE` 挂两个库跨库 join，与库存模块同一套做法：

```sql
ATTACH DATABASE 'competitor_agent.sqlite' AS ag;
SELECT f.family_asin, f.brand, r.attention_level, r.attention_summary
FROM   dim_competitor_family f
JOIN   ag.fact_analysis_run r ON r.family_asin = f.family_asin;
```

**观察数据放观察库，不放 Agent 库。** 它们是市场事实，不随 Agent 每次运行变化；
时间线的三条轨、价格活动看板、市场表现看板都直接读观察库，Agent 只是它们的消费者之一。

---

## 2. 观察库（Agent 的输入，工作台的事实底座）

### 2.1 身份与关系

```sql
CREATE TABLE dim_competitor_family (
  family_asin      TEXT PRIMARY KEY,   -- 竞品父 ASIN
  brand            TEXT NOT NULL,
  title            TEXT,
  category_path    TEXT,
  sub_category     TEXT,
  variant_count    INTEGER,            -- 源表自报变体数
  captured_children INTEGER,           -- 导出实际抓到的子体数
  price_band_low   REAL,
  price_band_high  REAL,
  unit_price_median REAL,              -- 件单价中位，价差比较的口径
  first_listed_date TEXT,
  seller_country   TEXT,
  buybox_type      TEXT,
  has_aplus        INTEGER,
  has_video        INTEGER,
  monitor_status   TEXT NOT NULL,      -- monitoring | paused | removed
  monitored_since  TEXT,
  in_quick_slot    INTEGER NOT NULL,   -- 1 = 运营快捷位里的常看竞品
  source           TEXT NOT NULL
);
```

`captured_children < variant_count` 是常态（真实源里 291 个族有 271 个如此），
所以「变化能不能代表整个产品族」必须由 Agent 判断，工作台不用覆盖比例自动裁决。

```sql
CREATE TABLE dim_competitor_child (
  child_asin     TEXT PRIMARY KEY,
  family_asin    TEXT NOT NULL,
  size_label     TEXT,
  color_label    TEXT,
  pack_count     INTEGER,            -- 装盒数；解析不出时为 NULL
  pack_resolved  INTEGER NOT NULL,   -- 0 = 装盒数未解析，不参与价差结论
  snapshot_price REAL,
  unit_price     REAL,               -- snapshot_price / pack_count
  fba_fee        REAL,
  gross_margin   REAL,
  sales_rank_sub INTEGER,
  is_main_variant INTEGER            -- 是否主销变体，影响能否代表产品族
);

CREATE TABLE dim_competitor_offer (
  offer_id      TEXT PRIMARY KEY,
  child_asin    TEXT NOT NULL,
  seller_name   TEXT,
  seller_country TEXT,
  fulfillment   TEXT,                -- AMZ | FBA | FBM
  is_buybox     INTEGER NOT NULL,
  observed_from TEXT,
  observed_to   TEXT,
  data_nature   TEXT NOT NULL        -- observed | third_party_estimate | derived
);

CREATE TABLE bridge_competitor_own (
  rel_id         TEXT PRIMARY KEY,
  family_asin    TEXT NOT NULL,
  own_child_asin TEXT,
  own_parent_asin TEXT NOT NULL,
  relation_basis TEXT NOT NULL,      -- 中文：同子类目 / 同价格带 / 同材质定位 / 同装盒数 / 同人群
  relation_note  TEXT,
  confirm_status TEXT NOT NULL,      -- confirmed | pending_review
  since_date     TEXT
);
```

竞品表与自有 ASIN 交集为 0，这张表**必须显式构造**，是整个模块的接缝。

### 2.2 关键词

```sql
CREATE TABLE dim_market_keyword (
  keyword         TEXT PRIMARY KEY,
  keyword_cn      TEXT,
  category_tags   TEXT,              -- 品类 / 材质 / 功能 / 场景 / 品牌 / 竞品
  aba_rank        INTEGER,
  monthly_search  INTEGER,
  monthly_purchase INTEGER,
  product_count   INTEGER,
  supply_demand_ratio REAL,
  ad_competitor_count INTEGER,
  ppc_bid         REAL,
  is_battleground INTEGER NOT NULL   -- 1 = 与自有共同竞争的重点词
);

CREATE TABLE bridge_competitor_keyword (
  family_asin   TEXT NOT NULL,
  keyword       TEXT NOT NULL,
  first_observed TEXT,
  last_observed  TEXT,
  entry_type    TEXT,                -- top3 | ac_keyword | brand_term | observed
  PRIMARY KEY (family_asin, keyword)
);
```

### 2.3 观察序列（模块地基）

```sql
CREATE TABLE fact_competitor_price_daily (
  child_asin  TEXT NOT NULL,
  date        TEXT NOT NULL,
  list_price  REAL,                  -- 划线价
  deal_price  REAL,                  -- 活动价，无活动为空
  final_price REAL NOT NULL,         -- 运营实际看到的成交价
  unit_price  REAL,                  -- 件单价
  coupon_pct  REAL,
  promo_kind  TEXT,                  -- deal | coupon | lightning | none
  data_nature TEXT NOT NULL,
  source      TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  PRIMARY KEY (child_asin, date)
);

CREATE TABLE fact_competitor_market_daily (
  family_asin  TEXT NOT NULL,
  date         TEXT NOT NULL,
  rank_sub     INTEGER,
  rank_main    INTEGER,
  units_rolling30 INTEGER,           -- 滚动 30 天销量量级（第三方估算）
  rating       REAL,
  rating_count INTEGER,
  new_rating   INTEGER,
  data_nature  TEXT NOT NULL,
  source       TEXT NOT NULL,
  PRIMARY KEY (family_asin, date)
);

CREATE TABLE fact_competitor_keyword_rank (
  family_asin   TEXT NOT NULL,
  keyword       TEXT NOT NULL,
  observed_date TEXT NOT NULL,
  organic_rank  INTEGER,
  ad_slot       TEXT,                -- 可观察广告位，未观察到为空
  is_top3       INTEGER NOT NULL,
  click_share   REAL,
  conversion_share REAL,
  data_nature   TEXT NOT NULL,
  source        TEXT NOT NULL,
  PRIMARY KEY (family_asin, keyword, observed_date)
);

CREATE TABLE fact_competitor_traffic_mix (
  family_asin  TEXT NOT NULL,
  period_start TEXT NOT NULL,
  period_end   TEXT NOT NULL,
  organic_share REAL,
  ad_share      REAL,
  other_share   REAL,
  top_entry_keyword TEXT,
  data_nature  TEXT NOT NULL,        -- 恒为 third_party_estimate
  PRIMARY KEY (family_asin, period_start)
);

CREATE TABLE fact_data_status (
  status_id   TEXT PRIMARY KEY,
  object_level TEXT NOT NULL,        -- family | child | offer | keyword
  object_id   TEXT NOT NULL,
  date_from   TEXT NOT NULL,
  date_to     TEXT NOT NULL,
  status      TEXT NOT NULL,         -- normal | interrupted | stale | conflict | missing
  label       TEXT NOT NULL,         -- 中文成品文案，直接上时间线数据状态轨
  source      TEXT
);

CREATE TABLE fact_own_price_daily (
  child_asin  TEXT NOT NULL,
  parent_asin TEXT NOT NULL,
  date        TEXT NOT NULL,
  final_price REAL NOT NULL,
  pack_count  INTEGER,
  unit_price  REAL NOT NULL,
  PRIMARY KEY (child_asin, date)
);

CREATE TABLE observation_manifest (key TEXT PRIMARY KEY, value TEXT);
-- 至少：dataset_version / generated_at / as_of / window_from / window_to
--       family_count / analyzed_family_count / own_parent_asins / source_package
```

**价差必须同口径。** 自有是 3/4/7 件装、件单价约 $6.7–7.0；Hanes 六件装 $26.08 折合件单价约 $4.35。
直接比整包价会得出「自有贵 2.5 倍」的假结论。所以：**价差一律用 `unit_price` 比较**，
`pack_resolved = 0` 的对象不进任何价差结论。

---

## 3. Agent 库（Pi Agent 的输出契约）

### 3.1 `fact_analysis_run` —— 一次分析的台账

```sql
CREATE TABLE fact_analysis_run (
  run_id          TEXT PRIMARY KEY,  -- 建议 {family_asin}-{run_date}-{seq}
  family_asin     TEXT NOT NULL,
  run_date        TEXT NOT NULL,
  data_as_of      TEXT NOT NULL,     -- 本次用到的观察数据截止日
  window_from     TEXT NOT NULL,     -- 本次分析的观察窗
  window_to       TEXT NOT NULL,
  trigger         TEXT NOT NULL,     -- scheduled | manual | priority
  model_version   TEXT,
  attention_level TEXT NOT NULL,     -- high | medium | low | none
  attention_summary TEXT NOT NULL,   -- 中文一句话，直接上屏
  evidence_level  TEXT NOT NULL,     -- sufficient | partial | insufficient
  evidence_reason TEXT NOT NULL,     -- 中文，说明证据为什么够或不够
  judgment_summary TEXT,             -- 中文，报告正文用
  created_at      TEXT NOT NULL      -- 同日多次运行的排序依据，必填
);
CREATE INDEX idx_run_family ON fact_analysis_run(family_asin, run_date DESC, created_at DESC);
```

与预测 Agent 同规矩：**不设 `is_latest`**，工作台按 `run_date DESC, created_at DESC` 自己取最新。
`evidence_level = insufficient` 时 `attention_level` 必须是 `none`——证据不足不给关注等级。

### 3.2 `fact_analysis_change` —— 变化结论（四类版图的唯一来源）

```sql
CREATE TABLE fact_analysis_change (
  run_id       TEXT NOT NULL,
  change_seq   INTEGER NOT NULL,     -- 展示顺序，越小越重要
  domain       TEXT NOT NULL,        -- price_promo | market | keyword | traffic
  object_level TEXT NOT NULL,        -- family | child | offer | keyword
  object_id    TEXT NOT NULL,
  label        TEXT NOT NULL,        -- 中文短标签，直接上版图
  direction    TEXT NOT NULL,        -- up | down | neutral
  magnitude_kind TEXT,               -- pct | rank | units | position
  magnitude_value REAL,
  date_from    TEXT NOT NULL,
  date_to      TEXT,                 -- 空 = 仍在持续
  current_state TEXT NOT NULL,       -- 中文：仍在进行 / 已结束 / 已恢复
  represents_family INTEGER NOT NULL,-- 1 = 可代表产品族；0 = 只保留在局部对象
  coverage_note TEXT,                -- 中文：涉及几个子体、是否主销变体
  data_nature  TEXT NOT NULL,        -- observed | third_party_estimate | derived | hypothesis
  confidence   TEXT NOT NULL,        -- high | medium | low
  basis        TEXT NOT NULL,        -- 中文一句话依据
  PRIMARY KEY (run_id, change_seq)
);
```

`domain` 的四个值正好是总览四类版图。`represents_family = 0` 的变化**不得进入整族结论**，
但仍要在详情的产品族与报价关系板块显示。

### 3.3 `fact_analysis_timeline` —— 共同时间线

```sql
CREATE TABLE fact_analysis_timeline (
  run_id      TEXT NOT NULL,
  track       TEXT NOT NULL,         -- market | price_promo | keyword | data_status
  item_seq    INTEGER NOT NULL,
  label       TEXT NOT NULL,         -- 中文
  date_from   TEXT NOT NULL,
  date_to     TEXT,
  ref_change_seq INTEGER,            -- 指回 fact_analysis_change
  window_before_from TEXT,           -- 事件前可比窗口
  window_before_to   TEXT,
  window_after_from  TEXT,
  window_after_to    TEXT,
  note        TEXT,
  PRIMARY KEY (run_id, track, item_seq)
);
```

### 3.4 `fact_analysis_concurrency` —— 同期关系（把因果边界写成数据）

```sql
CREATE TABLE fact_analysis_concurrency (
  run_id        TEXT NOT NULL,
  pair_seq      INTEGER NOT NULL,
  change_seq_a  INTEGER NOT NULL,
  change_seq_b  INTEGER NOT NULL,
  relation      TEXT NOT NULL,       -- concurrent | sequential | independent | insufficient
  overlap_from  TEXT,
  overlap_to    TEXT,
  statement     TEXT NOT NULL,       -- 中文，只能表达同期或可能相关
  causal_ready  INTEGER NOT NULL,    -- 0 = 不得升级为因果
  missing_evidence TEXT,             -- 中文：还缺什么才能升级
  PRIMARY KEY (run_id, pair_seq)
);
```

方案的因果红线在这张表上是可门禁的：`causal_ready = 1` 必须同时给出支撑证据说明，否则门禁失败。

### 3.5 `fact_analysis_attention_reason` —— 关注等级的依据条目

```sql
CREATE TABLE fact_analysis_attention_reason (
  run_id     TEXT NOT NULL,
  reason_seq INTEGER NOT NULL,
  label      TEXT NOT NULL,          -- 中文依据条目
  ref_change_seq INTEGER,
  weight_note TEXT,                  -- 中文：为什么这条最重要（不给数字权重）
  PRIMARY KEY (run_id, reason_seq)
);
```

**没有分数列，只有依据条目。** 这是方案「不产生无法解释的精确威胁分数」的落地方式。

### 3.6 `fact_analysis_impact` —— 可能影响范围

```sql
CREATE TABLE fact_analysis_impact (
  run_id       TEXT NOT NULL,
  impact_seq   INTEGER NOT NULL,
  own_parent_asin TEXT NOT NULL,
  own_child_asin  TEXT,
  shared_keyword  TEXT,
  pressure_dimension TEXT NOT NULL,  -- price | promo | market | keyword | traffic
  statement    TEXT NOT NULL,        -- 中文
  ref_change_seq INTEGER,
  confidence   TEXT NOT NULL,
  PRIMARY KEY (run_id, impact_seq)
);
```

### 3.7 `fact_analysis_open_item` —— 待确认与待观察

```sql
CREATE TABLE fact_analysis_open_item (
  run_id     TEXT NOT NULL,
  item_seq   INTEGER NOT NULL,
  item_kind  TEXT NOT NULL,          -- hypothesis | unconfirmed | watch
  statement  TEXT NOT NULL,          -- 中文
  needed_data TEXT,                  -- 中文：需要什么数据才能确认
  watch_until TEXT,
  PRIMARY KEY (run_id, item_seq)
);
```

### 3.8 `fact_analysis_diff` —— 与上一版比较

```sql
CREATE TABLE fact_analysis_diff (
  run_id       TEXT PRIMARY KEY,
  prev_run_id  TEXT,
  transition   TEXT NOT NULL,        -- new | sustained | escalated | eased | cleared
  statement    TEXT NOT NULL,        -- 中文
  changed_domains TEXT               -- 逗号分隔的 domain
);
```

`transition` 五个值正好对应方案要求的「新增 / 持续 / 加重 / 减弱 / 解除」。

### 3.9 `fact_analysis_report` —— 动态报告条目（总览用）

```sql
CREATE TABLE fact_analysis_report (
  report_id    TEXT PRIMARY KEY,
  scope_key    TEXT NOT NULL,        -- 站点+品线+子类目
  period_from  TEXT NOT NULL,
  period_to    TEXT NOT NULL,
  item_seq     INTEGER NOT NULL,
  family_asin  TEXT NOT NULL,
  ref_run_id   TEXT NOT NULL,        -- 冻结引用
  headline     TEXT NOT NULL,        -- 中文
  body         TEXT NOT NULL,        -- 中文，可多句
  impact_note  TEXT,
  unconfirmed_note TEXT,
  created_at   TEXT NOT NULL
);
```

### 3.10 `fact_evidence_handoff` —— 交给下游

```sql
CREATE TABLE fact_evidence_handoff (
  handoff_id   TEXT PRIMARY KEY,
  frozen_run_id TEXT NOT NULL,       -- 冻结的 run，不随后续重跑改变
  target_page  TEXT NOT NULL,        -- keyword | advertising
  family_asin  TEXT NOT NULL,
  own_child_asin TEXT,
  shared_keyword TEXT,
  pressure_dimension TEXT,
  observable_fact TEXT NOT NULL,     -- 中文
  evidence_level TEXT NOT NULL,
  detail_entry TEXT NOT NULL,        -- 详情页锚点：family + 时间范围 + 变化类型
  created_at   TEXT NOT NULL
);

CREATE TABLE agent_manifest (key TEXT PRIMARY KEY, value TEXT);
-- 至少：dataset_version / generated_at / agent_version / run_count
--       observation_package_version（本次分析针对哪个观察包跑的）
```

---

## 4. 工作台读取规则

**取最新一次分析**：

```sql
SELECT r.* FROM ag.fact_analysis_run r
JOIN (SELECT family_asin, MAX(run_date || 'T' || created_at) AS mx
      FROM ag.fact_analysis_run GROUP BY family_asin) t
  ON t.family_asin = r.family_asin
 AND t.mx = r.run_date || 'T' || r.created_at;
```

**三个必须支持的分支**：

| 情形 | 页面行为 |
| --- | --- |
| 观察库有、Agent 库无 run | 照常显示身份、价格活动、市场表现三个看板（都读观察库），只在结论区写「尚未纳入分析」，给一个「立即分析」入口 |
| 有 run 但 `evidence_level = insufficient` | 不显示关注等级、不进关注顺序、不进版图；显示证据不足原因与待补数据 |
| 有 run 但对象不在抓取名单内（无历史） | 只给当期快照事实，不给任何变化结论 |

**新鲜度不作为告警。** 与库存模块同口径：客观显示「分析于 X 日 · 周跑」，不涂红、不排异常。

---

## 5. 门禁

| ID | 断言 |
| --- | --- |
| G1 | 每个 run 至少 1 条 `fact_analysis_change`，且 `label` / `basis` 非空 |
| G2 | `evidence_level = insufficient` 的 run，`attention_level` 必须为 `none`，且无 attention_reason |
| G3 | `attention_level != none` 的 run，至少 2 条 `fact_analysis_attention_reason` |
| G4 | `fact_analysis_change.date_from` 必须落在 run 的 `window_from ~ window_to` 内 |
| G5 | 每条 change 的 `object_id` 必须能在观察库对应层级找到（引用完整性） |
| G6 | `represents_family = 0` 的 change 不得被任何 report 条目引用为整族结论 |
| G7 | `causal_ready = 1` 必须有非空支撑说明；`relation = insufficient` 时 `causal_ready` 必须为 0 |
| G8 | 同一 family 同一 run_date 的多个 run，`created_at` 互不相同 |
| G9 | 全库任意中文文案字段不得包含枚举原值（`price_promo`、`third_party_estimate`、`insufficient` 等） |
| G10 | 四个 domain 各至少 3 个 family 有变化；`fact_data_status` 里有 interrupted / stale / conflict 三种状态各至少 1 条 |
| G11 | 价差类 change 的对象 `pack_resolved` 必须为 1 |
| G12 | `fact_evidence_handoff.frozen_run_id` 指向的 run 存在，且不是该 family 的最新 run 也允许（冻结语义） |

门禁必须打在真有该特征的对象上：证据不足的门禁跑在一个证据充分的族上会全绿，等于没测。

---

## 6. 口径与文案纪律

1. 每条结果都带 `data_nature` + 来源 + 观察时间 + 分析时间；月度估算不得渲染成每日事实。
2. 所有 `label` / `basis` / `statement` / `summary` 必须是**中文成品文案**，前端直接渲染不做映射。
3. 枚举原值（`domain`、`data_nature`、`trigger`、`transition` 等）只用于逻辑分组和图标，绝不上屏。
4. 价差一律用件单价；装盒数未解析的对象不进价差结论。
5. 同期只能表述为「同期变化」或「可能相关」，升级为因果需 `causal_ready = 1` 且有支撑说明。
6. 界面上不写防御性自述与免责声明；口径解释收进 ⓘ 浮层。

---

## 7. 本轮采用的默认口径

| 项 | 取值 |
| --- | --- |
| 基准日 `as_of` | 2026-08-03（与库存 v0.3.0、广告模块、竞品快照目录 20260803 同一天） |
| 观察窗 | 180 天：2026-02-05 ~ 2026-08-03 |
| 自有侧 | 库存∩广告的 188 个子体 / 2 个父体 `B0D9FLMR6N`、`B0GQXK2Q58` |
| 抓取范围 | 48 个竞品族（Men's Boxer Briefs，件单价可比，子体 ≥ 4） |
| 分析范围 | 20 个族（其中 8 个在运营快捷位） |
| 未来区间 | 无。竞品模块不做预测 |

## 8. 仍然开放

- **A** 抓取周期定日还是周。日粒度让价格活动看板更真，但第三方工具配额是硬约束。
- **B** 快捷位名单谁维护：策略设置里配，还是运营在页面上直接加。
- **C** 关键词位置是否补完整自然位排名（真实源只给前三名）。当前默认补，并标注为构造。
