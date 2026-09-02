# 预测 Agent 与工作台接口契约

版本 v0.3（2026-08-30）· 对应决策：**B 方案** · 日期范围已对齐真实 Agent 输出

---

## 0. 职责划分

Agent 有两类交付物：

1. **当下的判断** —— 给人看的，不进工作台
2. **写入表的预测** —— 工作台只读这一类

工作台**读预测，自己算下游**。分界线：

| 谁做 | 内容 |
| --- | --- |
| **Agent** | 未来 90 天逐日销量预测 + 预测区间 + 每个调整项的影响和依据 |
| **工作台** | 逐日库存余额、覆盖天数、安全线突破日、预计断货日、缺口量、超量件数、最晚补货日、建议补货量、承接能力、五类风险 |

这样切的理由：Agent 不可替代的是**判断需求**（历史有没有被缺货扭曲、活动影响多大、生命周期在哪一段）；拿需求算库存够不够是**确定性算术**。算术留在工作台，安全库存天数、入库延迟、各类阈值就仍然能在参数面板上改并立刻重算。

**一个连带红利**：因为投影在工作台算，Agent 给的 `lower / forecast / upper` 三条需求线可以各跑一遍，于是断货日不是一个日期而是一个**区间**（悲观最早哪天断、基准哪天断）。如果投影也放在 Agent 里离线跑，就只能给一个数。

---

## 1. 两个数据库

| 库 | 内容 | 打开方式 |
| --- | --- | --- |
| 产品库存包 `bamboocool_product_sales_inventory_v0.2.x.sqlite` | 产品身份、库存快照、在途、库龄批次、成本体积、**历史逐日销量**、**事件日历** | 只读 |
| 预测库 `forecast_agent.sqlite` | 本文档定义的四张表 | 只读 |

工作台用 `ATTACH DATABASE` 把两个库挂在同一连接上，从而能跨库 join：

```sql
ATTACH DATABASE 'forecast_agent.sqlite' AS fc;
SELECT c.child_asin, f.date, f.forecast_units
FROM   dim_product_child c
JOIN   fc.fact_forecast_daily f ON f.child_asin = c.child_asin;
```

**历史逐日和事件日历建议放产品包，不放预测库。** 它们是产品事实，不随 Agent 每次运行变化，而且工作台画柱状图左半边（历史实际）要直接用，Agent 只是它们的消费者之一。如果你打算放预测库，告诉我，读取端换个前缀即可。

---

## 2. 预测库四张表

### 2.1 `fact_forecast_run` —— 批次台账

```sql
CREATE TABLE fact_forecast_run (
  run_id            TEXT PRIMARY KEY,   -- 建议 {child_asin}-{run_date}-{seq}
  child_asin        TEXT NOT NULL,
  run_date          TEXT NOT NULL,      -- YYYY-MM-DD，预测起算日
  data_as_of        TEXT NOT NULL,      -- 本次用的历史数据截止日
  horizon_days      INTEGER NOT NULL,   -- 90
  trigger           TEXT NOT NULL,      -- weekly | manual | priority
  model_version     TEXT,
  confidence        TEXT,               -- high | medium | low
  confidence_reason TEXT,               -- 中文，直接上界面
  judgment_summary  TEXT,               -- 可选：Agent 那句人读的判断
  created_at        TEXT NOT NULL       -- 同日多次运行的排序依据，必填
);
CREATE INDEX idx_run_asin_date ON fact_forecast_run(child_asin, run_date DESC, created_at DESC);
```

**`created_at` 必填**，因为「重点 ASIN 天跑」和「运营点一下就重跑」都可能一天内跑两次，`run_date` 分不出先后。

**不设 `is_latest` 标记位。** 工作台按 `run_date DESC, created_at DESC` 自己取最新——标记位一旦因为中断的运行留下两个 1，页面会静默读错一个对象的预测，而这种错误没有任何症状。派生一次的代价在 342 个对象上是微秒级。

### 2.2 `fact_forecast_daily` —— 逐日预测（工作台主输入）

```sql
CREATE TABLE fact_forecast_daily (
  run_id         TEXT NOT NULL,
  child_asin     TEXT NOT NULL,
  date           TEXT NOT NULL,
  forecast_units REAL NOT NULL,
  lower_units    REAL,
  upper_units    REAL,
  PRIMARY KEY (run_id, date)
);
CREATE INDEX idx_fd_asin_date ON fact_forecast_daily(child_asin, date);
```

**日期约定：第一个预测日 = `run_date + 1`**，共 `horizon_days` 行。
理由是 `run_date` 当天的实际销量还没结算完，属于历史侧。

**已与真实 Agent 输出对齐**（2026-08-30 确认）：

| | 范围 |
| --- | --- |
| Agent 历史 | 2024-08-05 ~ 2026-08-03（约 2 年） |
| Agent 未来 | 2026-08-04 ~ 2026-11-01（90 天） |

未来窗口的起点 2026-08-04 正好等于 `run_date(2026-08-03) + 1`，与上述约定吻合，
读取端无需调整。产品包基准日也是 2026-08-03，三者同一个锚点。

历史两年意味着柱状图必须自带时间范围切换与缩放，不能一次画满。

### 2.3 `fact_forecast_factor` —— 调整项与依据

```sql
CREATE TABLE fact_forecast_factor (
  run_id       TEXT NOT NULL,
  child_asin   TEXT NOT NULL,
  factor_seq   INTEGER NOT NULL,   -- 展示顺序
  factor_type  TEXT NOT NULL,      -- 见下
  label        TEXT NOT NULL,      -- 中文短标签，直接上界面
  effect_kind  TEXT NOT NULL,      -- pct | units | multiplier
  effect_value REAL NOT NULL,
  direction    TEXT NOT NULL,      -- up | down | neutral
  applies_from TEXT,               -- 空 = 作用于整个窗口
  applies_to   TEXT,
  basis        TEXT NOT NULL,      -- 一句话依据，给人读
  PRIMARY KEY (run_id, factor_seq)
);
```

**这张表只放最关键的影响因素，不做全量审计轨。** 它的用途是给人解释「为什么是这个数」，
所以每次运行**写 2~5 条**就够，按 `factor_seq` 排在前面的是影响最大的。
Agent 内部那些更深的取数与中间量（引用到源文件哪一行的定位串等）本轮不进表，
需要时再加一列 `evidence_ref`，不影响已建结构。

`factor_type` 至少覆盖：`trend` 趋势 / `weekday` 星期规律 / `lifecycle` 生命周期 / `ad` 广告 / `bd` BD 促销 / `coupon` Coupon / `price` 价格变化 / `stockout_repair` 缺货修正 / `market` 市场变动 / `other`。

**`label` 和 `basis` 必须是中文成品文案，工作台直接渲染不做映射。** `factor_type` 只用于逻辑分组和图标，绝不上屏——这个项目的规矩是内部枚举值一律不出现在界面上。

这张表是整个板块最值钱的一张：它让「为什么预测是这个数」可点开、可追溯，同时是柱状图**未来侧**标注的来源（哪几天因为什么被调高调低）。

### 2.4 `forecast_manifest` —— 包级说明

```sql
CREATE TABLE forecast_manifest (
  key   TEXT PRIMARY KEY,
  value TEXT
);
-- 至少：dataset_version / generated_at / agent_version / asin_count / run_count
--       product_package_version（本预测针对哪个产品包版本跑的）
```

`product_package_version` 是为了防止预测库和产品包错配（比如预测是对着 v0.2.2 的库存跑的，工作台却挂了 v0.2.3）。

---

## 3. 工作台的读取规则

**取最新一次运行**（决策 2：按每个 ASIN 最新的汇总）：

```sql
SELECT r.* FROM fc.fact_forecast_run r
JOIN (SELECT child_asin, MAX(run_date || 'T' || created_at) AS mx
      FROM fc.fact_forecast_run GROUP BY child_asin) t
  ON t.child_asin = r.child_asin
 AND t.mx = r.run_date || 'T' || r.created_at;
```

**新鲜度不作为告警状态。** 你的理由我接受并按它设计：运营不去分析的对象，本身就说明它不重要或量小。所以页面只客观显示「预估更新于 X 日 · 周跑」，不涂红、不排进异常。

**但有一个例外要处理**：一个尾部对象的预估是 7 天前的，而它现在触了「库存不足」——这时旧预估会低报问题。这种组合页面标一个可点的「建议重跑」，不是错误态，是一个动作入口。这条要不要做你定。

**缺预测的对象**：产品包里有、预测库里没有的 ASIN，页面照常显示库存/库龄/仓储费（这些不依赖预测），只在需求和承接两块写明「尚无预测」。不猜、不退回旧公式。

---

## 4. 现有实现的增删

**删掉**（`lib/compute.py` / `lib/rules.py`）：

- `build_demand` 的整条公式链：六窗口加权 → 基线日均 → 趋势系数（原始 → 限幅 → 折减）→ 预测日均 → 乘天数
- 参数面板里 10 个需求预测参数：7/14/30/60/90 天权重、趋势强度、预测天数、活动系数、活动天数、活动起始偏移

**保留**（只把需求输入换源）：

- `build_projection` 逐日投影、覆盖天数、断货日、缺口、超量
- `build_aging` 库龄、`build_fee` 仓储费、`build_risks` 五类风险、`build_capacity` 承接能力
- 参数面板里的阈值类和承接类：安全库存天数、目标覆盖、消化上限、入库延迟、可用率下限、181+ 占比、费销比、费毛利比、费率

**新增**：

- `lib/forecast.py`：挂载预测库、取最新运行、读逐日与调整项
- 投影跑三遍（`lower / forecast / upper`），断货日给区间
- 历史逐日 + 事件日历的读取，供柱状图左半边

---

## 5. 门禁（构建完跑一遍）

1. 每个 `run_id` 的 `fact_forecast_daily` 行数 == 该 run 的 `horizon_days`
2. 每个 run 的日期连续无空洞，且第一天 == `run_date + 1`
3. `lower_units <= forecast_units <= upper_units`（有值时）
4. 预测库里的 ASIN 必须全部能在产品包里找到（引用完整性）。
   **不要求每个对象都有 run**——「有历史但无预测」是页面必须支持的分支，
   门禁只把这类对象的数量单独报出，不判失败。
5. 同一 `child_asin` 同一 `run_date` 的多个 run，`created_at` 互不相同
6. 每个 run 至少一条 `fact_forecast_factor`，且 `label` / `basis` 非空
7. 历史逐日的最后一天 与 最早的 `run_date` 之间无缺口（见下）

---

## 6. 已确认

**① 日期轴** —— 由数据构建方保证历史与预测在同一条轴上无空洞。门禁 7 仍然跑，只作机械核对。

**② 调整项进表**，但只写最关键的影响因素（每次 2~5 条），不做全量审计轨；
Agent 内部更深的取数链路本轮不进表。

**③ 事件粒度 = 子 ASIN**。`fact_product_event` 直接以 `child_asin` 为键，不需要款号级展开桥表。

```sql
CREATE TABLE fact_product_event (
  child_asin TEXT NOT NULL,
  date_from  TEXT NOT NULL,
  date_to    TEXT NOT NULL,
  event_type TEXT NOT NULL,   -- bd | coupon | price | ad | market | other
  label      TEXT NOT NULL,   -- 中文短标签，直接上柱状图标注
  magnitude  REAL,            -- 折扣幅度 / 预算变化，可空
  note       TEXT,
  source     TEXT
);
CREATE INDEX idx_ev_asin_date ON fact_product_event(child_asin, date_from);
```

同一天可以有多个事件（BD 叠 Coupon），柱状图上并排叠标记，不合并。

---

## 7. 仍然开放

**A. 旧预估撞上库存不足时给不给「建议重跑」入口。** 尾部对象预估 7 天前、现在触了库存不足，
旧预估会低报严重度。倾向做成一个可点的动作入口而非错误态。未定。

**B. 历史逐日与事件日历放哪个库。** 建议放产品包（它们是产品事实，不随 Agent 每次运行变化，
工作台画柱状图左半边直接用，Agent 只是消费者之一）。放预测库也能读，读取端换前缀即可。未定。
