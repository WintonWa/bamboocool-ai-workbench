# 需求预测：Agent 产出，工作台展示

> 定稿日期：2026-08-31
> 修订对象：`11-预测判断Agent落表与调用接口.md` §0
> 恢复依据：`07-预测Agent接口契约.md` §0
>
> 2026-08-31 修订：逐列审过 §4 给 Agent 的每一张表，把「已经构造好的答案」全部移进 §5 禁读。
> 共移出 5 组：销量表的 `lost_sales_units`/`potential_demand_units`；生命周期表的
> `lifecycle_stage`/`change_reason`/`confidence_score`（答案、理由、置信度三样都在表里）；
> 活动表的 `preset_uplift`/`performance_index`；库存表的 `coverage_days`（那是工作台的产出）；
> 以及所有表的 `value_origin`/`method_version`/`provenance`/`quality_status` 构造元数据。
> §4.1 同时改成「列出的列就是全部，没列的一律不给」。
> 同日又审了输出侧（§6.0）：Agent 已落库的 17 个数字依据里 **8 个引用的正是 §5 禁读的列**，
> 等于把构造好的答案换算成百分比报回来 —— 这也解释了 §2 那张对照表为什么「接近」。

---

## 0. 判断标准：真实业务里这条数据存在吗

这是全文唯一的分界线。

| 真实业务里 | 例子 | 在本项目里的角色 |
| --- | --- | --- |
| **客观存在** | 历史实销、历史库存、历史广告花费、运营自己排的未来广告预算、运营自己报的 deal 排期、未来定价计划 | **Agent 的输入** |
| **不存在，要算出来** | 未来 90 天逐日销量、每一项影响多少、影响的依据 | **Agent 的输出，页面展示这个** |

运营不会在后台看到一份"未来 90 天预测"然后请 AI 解释它。**预测就是 AI 要产出的东西。**

---

## 1. 现在反在哪

数据包 v0.3.0 为了先把页面搭起来，把**预测那一侧也烤好了**：

| 已烤好的 | 内容 |
| --- | --- |
| `fact_child_forecast_daily` | 30,780 行 = 342 子体 × 90 天，`p10/p50/p90` 齐全 |
| 同表的因子列 | `seasonality_factor / lifecycle_factor / advertising_effect_ratio / promotion_effect_ratio / price_effect_ratio` |
| `feature_child_demand_daily.clean_baseline_units` | 剥离干扰后的干净基线 |
| `feature_child_demand_daily.adjustment_reason` | **中文调整理由**：「已剥离Coupon活动提升」5,343 天、「已剥离广告投入突变影响」6,934 天、「已剥离LD活动提升」1,213 天 |
| `plan_child_*_daily.expected_effect_ratio` | 未来每天广告/活动/价格的预期效应 |
| `fact_child_forecast_evaluation` | 1,026 行，选中哪个模型、wape / bias / confidence |

**连"为什么"的中文文案都烤好了。** 于是 Agent 拿到的不是一道题，是一份答案。它能做的
只剩给这份答案配说法——这就是反了。

**数据包那份预测的正确定位是「上一次跑的快照」**，脚手架。不是 Agent 的输入。

---

## 2. 反过来的实测代价

`B0BVM5WCSQ`，Agent 跑于 2026-08-31 08:48，与快照的系数对照：

| Agent 判断 | 快照画柱子用的 | |
| --- | --- | --- |
| 季节性 −7.00% | `seasonality_factor` 0.9252 = −7.48% | 接近 |
| 广告投放 +5.00% | `advertising_effect_ratio` 1.0533 = +5.33% | 接近 |
| 站内活动 +3.00% | `promotion_effect_ratio` 1.019 = +1.90% | 差 1.1 点 |
| **生命周期 +0.00%（平稳）** | `lifecycle_factor` **1.0312 = +3.12%** | **字说平稳，柱子按涨 3% 画** |

页面上写着「生命周期 平稳」，图是按涨 3.12% 画的。**没有任何机制会发现**，因为字和
数字来自两次互不相干的计算。

这不是精度问题。只要数字和理由不同源，这类矛盾就持续产生，而且每次都无症状。

---

## 3. 职责表（恢复 `07` §0）

| 谁做 | 内容 |
| --- | --- |
| **Agent** | 未来 90 天逐日 `p10 / p50 / p90` + 每一项影响的幅度与中文依据 |
| **工作台** | 逐日库存余额、覆盖天数、安全线突破日、预计断货日、缺口量、超量件数、最晚补货日、建议补货量、承接能力、五类风险 |

**这样切的理由**（`07` §0 原话）：Agent 不可替代的是**判断需求**——历史有没有被缺货扭曲、
活动影响多大、生命周期在哪一段；拿需求算库存够不够是**确定性算术**。算术留在工作台，
安全库存天数、入库延迟这些阈值就仍然能在参数面板上改并立刻重算。

**一次 run 同时产出数字和理由，共用一个 `run_id`** —— 第 2 节那类矛盾唯一的根治办法。

---

## 4. Agent 读哪些表（真实业务里客观存在的）

### 4.1 历史事实：两年，342 子体 × 730 天

| 表 | 行数 | 有用的列 | 判断什么 |
| --- | --- | --- | --- |
| `fact_child_sales_daily` | 249,660 | `units_sold` 实销、`orders`、`average_selling_price` | 基线 |
| `fact_child_inventory_daily` | 249,660 | `opening_fba_sellable` / `closing_fba_sellable` 可售量、`received_units` 入库、`stockout_flag` 当天有没有货 | 哪些天没货 → 那些天的销量不算需求，真实需求要 Agent 自己估 |
| `fact_child_advertising_daily` | 249,660 | `ad_budget / ad_spend / impressions / clicks / cpc / ad_orders / ad_sales / ctr / ad_cvr / acos / acoas` | 投放与销量的实际关系 |
| `fact_child_promotion_daily` | 249,660 | `promotion_id / promotion_type / promotion_status / discount_rate / is_planned` | 每类活动实际抬升多少（自己从销量对比里算） |
| `fact_child_price_daily` | 249,660 | `list_price / selling_price / coupon_amount / discount_rate / price_event` | 价格弹性 |
| `fact_child_traffic_daily` | 249,660 | `sessions / page_views / buyers / cvr` | 区分「没流量」和「没转化」 |
| `dim_child_lifecycle_history` | 344 | **只取上架日**（最早的 `effective_start`） | 上架多久了 —— 在哪一段要 Agent 从销量轨迹自己判断 |

范围 2024-08-04 ~ 2026-08-03（as_of）。

**上表列出的列就是全部，没列的一律不给。** 逐表的排除项与理由见 §5。
判断一列该不该给，用 §0 那把尺子：**运营的后台里有没有这一列。**

三个容易误伤的例子（这些**是**合法输入）：`acos` / `ctr` / `ad_cvr` / `cvr` 都是算出来的比率，
但亚马逊广告后台和业务报告里确实有这几列，运营天天看 —— 所以给。
反过来 `coverage_days`（覆盖天数）也是算出来的，但它在 §3 里明确是**工作台的产出**，
所以不给。区别不在「算没算过」，在**真实业务里存不存在这一列**。

**`potential_demand_units` 与 `lost_sales_units` 已从本表划掉**，理由见 §5 末。
一句话：那两列就是「历史被缺货压低了多少」的答案，递给 Agent 就等于替它答了这道题。
它该拿到的是实销 + 可售量，自己推出「这几天没货，所以那几天的销量不是需求」。

### 4.2 未来计划：每个 ASIN、每一天，90 天

这些是**运营自己排的**，真实业务里确实存在：

| 表 | 行数 | 有用的列 |
| --- | --- | --- |
| `plan_child_advertising_daily` | 30,780 | `planned_budget / planned_spend / planned_impressions / planned_clicks` |
| `plan_child_promotion_daily` | 30,780 | `promotion_id / promotion_type / promotion_status / planned_discount_rate` |
| `plan_child_price_daily` | 30,780 | `planned_list_price / planned_selling_price / planned_coupon_amount / planned_discount_rate` |

范围 2026-08-04 ~ 2026-11-01。

### 4.3 库存与政策（算承接能力要用，Agent 判断需求时可参考）

`fact_inventory_snapshot`、`config_child_inventory_policy`、`plan_child_supply_event`（684 笔在途）。

---

## 5. 不给 Agent 读的（真实业务里不存在这份数据）

不是"禁止"，是**这些东西在真实业务里根本没有**——它们是本项目为了搭页面烤出来的答案：

| 字段 | 它已经替 Agent 回答了 |
| --- | --- |
| `fact_child_forecast_daily.p10/p50/p90` | 未来 90 天卖多少 |
| 同表 `seasonality_factor / lifecycle_factor / advertising_effect_ratio / promotion_effect_ratio / price_effect_ratio` | 每一项影响多少 |
| `feature_child_demand_daily.clean_baseline_units` | 剥离干扰后的干净基线 |
| `feature_child_demand_daily.estimated_demand_units` | 缺货日的真实需求是多少 |
| `feature_child_demand_daily.*_factor` / `*_effect_ratio` | 五项因子的分解 |
| `feature_child_demand_daily.adjustment_reason` | **为什么**（中文成品文案） |
| `feature_child_demand_daily.demand_quality_flag` | 这天算不算正常销售日 |
| `plan_child_*_daily.expected_effect_ratio`、`preset_uplift` | 未来这天的计划会带来多少提升 |
| `fact_child_forecast_evaluation` | 选哪个模型、置信度多少 |
| `fact_child_sales_daily.lost_sales_units` | 因为没货少卖了多少 —— **就是「历史被压低了多少」这道题的答案** |
| `fact_child_sales_daily.potential_demand_units` | 要是有货本来能卖多少 —— 同上，而且是纯派生 |
| `dim_child_lifecycle_history.lifecycle_stage` | **「生命周期在哪一段」的答案本身** —— 取值就是 `成熟期` / `成长期` / `新品期` / `衰退期`，中文、可直接上屏 |
| `dim_child_lifecycle_history.change_reason` | 阶段为什么变 —— 连「为什么」都烤好了（如 `当前属性延展`） |
| `dim_child_lifecycle_history.confidence_score` | 这个判断的置信度（如 `0.78`）—— 置信度是 Agent 该给的 |
| `fact_child_promotion_daily.preset_uplift` | 这场活动预设会抬升多少 —— **「活动影响多大」的答案** |
| `fact_child_promotion_daily.performance_index` | 活动表现指数 —— 构造出来的合成指标，业务后台没有这一列 |
| `fact_child_inventory_daily.coverage_days` | 覆盖天数 —— §3 里明确是**工作台的产出**，不该回流成 Agent 的输入 |
| `*.quality_status` / `*.demand_quality_flag` | 这条数据算不算正常 —— 数据质量判断，且取值是英文码值（`complete` / `supplemented`） |
| `*.value_origin` / `*.method_version` / `*.provenance` | **构造元数据，所有表一律不给**。`value_origin` 取值是 `synthetic_demo` / `derived_from_actual` —— 一是英文码值（G9），二是它直接告诉模型哪些数据是造的 |

**`lost_sales_units` / `potential_demand_units` 是 2026-08-31 补划的**（原先误列在 §4.1 的输入里）。实测依据：
`potential_demand_units = units_sold + lost_sales_units` 在 **249,660 行里 100% 成立**，
所以它不是一次独立测量，就是「实销 + 那个答案」，零新信息。

而 `lost_sales_units` 本身是**估出来的**：运营后台里只能看到「这 14 天可售是 0、卖了 0 件」，
少卖多少必须自己推。递给 Agent 就等于替它答了缺货扭曲这道题 ——
和 §1 那个错完全同形，只是换了一张表。

**同日一并补划的还有生命周期那三列与活动那两列。** 逐条实测确认过：
`dim_child_lifecycle_history` 一张表里同时装着答案（`成熟期`）、理由（`当前属性延展`）
和置信度（`0.78`）—— 而 §4.1 原本正是把这张表列为「判断生命周期在哪一段」的依据。
这是本文档 §1 那个错在 342 行的小表上重演了一次。

**判断标准**：运营的后台里不会有一列叫「本来能卖多少」，也不会有一列直接写着
「这个产品处于成熟期，因为当前属性延展，置信度 0.78」。

**判断依据**：运营的后台里不会有一列叫「已剥离Coupon活动提升」。缺货日的真实需求要**估**，
干净基线要**算**，季节系数要**判断**。这些全是产出。

**它们的正确用途是对照**：Agent 跑完之后，与快照并排比 —— 上一次说日均 21.9、
生命周期 +3.12%，这一次 Agent 说多少、为什么不同。这是演示里最有说服力的一屏，
前提是两份来自互相独立的计算。

---

## 6. 输出：页面展示的就是这个

一次 run 产出三样，共用 `run_id`：

| # | 内容 | 页面用在哪 |
| --- | --- | --- |
| 1 | 未来每一天的 `p10 / p50 / p90` | 图上的柱子与区间；算下游（余额、覆盖、断货日、缺口、补货建议） |
| 2 | 每一项判断：名称、状态、影响幅度、中文依据、可引用的数字 | 需求判断带 |
| 3 | 这一次的执行环节 | 任务面板的过程；「跑于 …」点开回看 |

第 1 和第 2 必须同源。第 3 见第 8 节。

### 6.0 输出侧审查：现在的「依据」有一半是把构造好的答案吐回来

2026-08-31 逐键审过 Agent 已落库的 `numbers`（判断的数字依据）。**17 个键里 8 个
引用的正是 §5 禁读的列**——也就是说 Agent 的「判断依据」相当一部分是读了包里烤好的因子、
换算成百分比再报一遍。

| factor | 必须换掉的键 | 它其实就是 |
| --- | --- | --- |
| `seasonality` | `history_seasonality_factor_90d`、`future_seasonality_factor_90d` | `fact_child_forecast_daily.seasonality_factor` |
| `lifecycle` | `history_lifecycle_factor_90d`、`future_lifecycle_factor_90d` | 同表 `lifecycle_factor` |
| `advertising` | `future_advertising_effect_ratio` | 同表 / `plan_*` 的 `expected_effect_ratio` |
| `promotion` | `future_promotion_effect_ratio`、`future_promotion_max_effect_ratio` | 同上、以及 `preset_uplift` |
| `stockout_distortion` | `history_lost_sales_units` | `fact_child_sales_daily.lost_sales_units` |

**这解释了 §2 那张对照表为什么「接近」**：Agent 报 季节性 −7.00% / 包里 −7.48%，
Agent 报 广告 +5.00% / 包里 +5.33% —— 那不是两次独立判断恰好吻合，
是 **Agent 读了包里的因子、四舍五入报了一遍**。而逐日 `p50` 来自别处，
所以生命周期那一项才会「字说平稳、柱子涨 3.12%」。

**换成什么**：依据必须是**可观测的原始事实**，Agent 自己算的。举例——

| 不要 | 改成 |
| --- | --- |
| `seasonality_factor` = 0.9252 | 去年同期（未来 90 天对应的历史窗口）日均 vs 最近 90 天日均，两个实销数字 |
| `lifecycle_factor` = 1.0312 | 近 30 天日均 vs 前 30 天日均 vs 上架至今的轨迹，实销数字 |
| `expected_effect_ratio` = 1.019 | 历史同类活动期间日均 vs 相邻非活动期日均，实销数字；未来只给排期天数与折扣率 |
| `lost_sales_units` = 27 | 可售量为 0 的天数、那些天的实销、相邻正常日的日均 |

判据和输入侧同一把尺子：**这个数字是观测到的，还是别人替它算好的。**

### 6.0.1 另外三条输出侧规则

**一、不许输出工作台算的东西。** §3 划给工作台的十项（逐日库存余额、覆盖天数、
安全线突破日、预计断货日、缺口量、超量件数、最晚补货日、建议补货量、承接能力、五类风险）
不进需求预测 Agent 的输出。理由是 §3 原话：算术留在工作台，阈值才能在参数面板改并立刻重算。

注意和盘点结论 Agent 的区别：那个 Agent 的判断**就是关于**断货日与覆盖天数的，
所以它在 `numbers` 里**引用**这些值是对的。区别是「引用工作台的产出当依据」
与「自己重算一份」。前者可以，后者不行。

**二、`confidence` 必须是 Agent 自己的判断。** 包里有两处现成的置信度都已列入 §5 禁读
（`fact_child_forecast_evaluation.confidence_score`、`dim_child_lifecycle_history.confidence_score`）。
不许读，自然也不许换算成三档报回来。

**三、`input_forecast_run_id` 的含义要重定。** 现在它指向包里那批预烤预测
（`forecast-v030-20260803-default`），那是「Agent 读了哪一批预测」的意思 ——
本修订之后 Agent 不再读它。这一列要么去掉，要么改成「本次并排对照用的快照批次」，
不能继续暗示预测是从那里来的。

### 6.1 重建检查：**本轮不做**（王楠 2026-08-31 决定）

原第 3 条要求「各项影响乘回基线应能重建 `p50`，容差写进门禁」。**这一轮先不做，
先看到 Agent 真的出预测。**

留档两件事，免得以后重新想一遍：

**它防的是什么**：页面上的字和图自相矛盾。§2 那个实测就是——写着「生命周期 平稳」，
柱子按涨 3.12% 画。两者来自两次互不相干的计算，**现在没有任何东西会发现**。

**为什么不能靠反推校准**：2026-08-31 实测过，这个恒等式在数据包里**根本不成立**——
`p50 = baseline × 六因子` 的逐日残差中位 10.5%、最大 62%，按 ASIN 合计最大到 2.6e12%。
原因是 `baseline_units` 已经把星期效应烤进去了（它逐日变化且与 `weekday_factor` 反向），
再乘一次就是重复计算；剔掉星期还差 3~4%，剩下是 `p50` 取整。
**包里那些因子列是注解，不是 p50 的构成方式。** 所以门禁只能由契约定义、Agent 按定义产出，
不能从包里量。

**以后要做时的两个档位**：逐日验（Agent 每天给基线+五个乘数，任何一天矛盾都抓得到，
但模型容易验不过要重试）／只验 90 天合计（快、容易过，但矛盾集中在活动那几天时会被平均掉）。

**为此本轮的让步**：逐日表里保留 `baseline_units` 一列，可为空。
现在不填也不校验，以后要加这条门禁时不用改表结构。

---

## 6.2 逐日预测表（本轮要落的）

库沿用 `modules/inventory/derived/forecast_agent.sqlite`，与判断**共用 `run_id`**
（§3 的「一次 run 同时产出数字和理由」就是靠这个成立的）。

```sql
CREATE TABLE fact_child_forecast_agent_daily (
  run_id         TEXT NOT NULL,
  child_asin     TEXT NOT NULL,
  forecast_date  TEXT NOT NULL,   -- YYYY-MM-DD，从 as_of 次日起连续
  p10_units      REAL NOT NULL,
  p50_units      REAL NOT NULL,
  p90_units      REAL NOT NULL,
  baseline_units REAL,            -- 可为空，见 6.1 末
  PRIMARY KEY (run_id, forecast_date)
);
CREATE INDEX idx_fagent_daily ON fact_child_forecast_agent_daily(child_asin, forecast_date);
```

工作台这一侧只提三个要求（原 §6 的 1、2 保留，3 撤下）：

1. 行数 = `horizon_days`，日期连续无缺；缺天视为 run 失败，不半截上屏
2. `p10 ≤ p50 ≤ p90` 逐日成立
3. ~~各项影响乘回基线能重建 p50~~ —— 本轮不做，见 6.1

### 6.3 事实里不能再带那两列

§4.1 已划掉 `potential_demand_units` 与 `lost_sales_units`。
**Agent 侧的事实加载器要跟着改**：判断缺货扭曲的原料是
`fact_child_inventory_daily` 的可售量（哪些天没货），不是「少卖了多少」。

**事实怎么摘要由 Agent 侧定。** 730 天原始逐日行显然不能整段塞给模型，
但摘要成什么形状（按周聚合？分段统计？只给关键窗口？）是 Agent 侧的判断，
本文不规定 —— 规定了反而会限制它把预测做对。

**工作台写读取端**（现在 `forecast_judgment.py` 就是这样，只读 `forecast_agent.sqlite`）。

逐日表的结构与验收要求见 §6.2，本节不重复。

> 2026-08-31 删除：本节原有一份重复的「工作台只提三个要求」，其中第 3 条
> （各项影响乘回基线应能重建 `p50`，容差写进门禁）与 §6.2 明确撤下的那一条**相反**，
> 且它说「表结构由 Agent 侧发布」，而 §6.2 已经把 `CREATE TABLE` 给全了。
> 两处相反的要求发出去，实现方会照其中一半做。删掉重复块，只留 §6.2 一处。

---

## 7. 页面怎么读

| 情形 | 图上的柱子 | 来源标 |
| --- | --- | --- |
| 该子体有 Agent run | Agent 的 `p50`，区间用 `p10/p90` | 「Agent 预测 · 跑于 08-31 08:48」 |
| 没有 | 数据包快照 | 「上一次快照 · as_of 2026-08-03」 |

两种来源的柱子在视觉上要可分辨，否则演示时说不清现在看的是哪一份。

工作台这一侧的保证：读到就用，不改写、不重算、不重排序（哪一项排第一是判断的一部分：
实测 `B0CBPXNC1M` 首位是站内活动，`B0B3LM36WB` 是季节性）、不映射枚举值（中文由 Agent 给，
G9 扫这个）、`null` 显示 `—` 而 `0` 显示 `0.00%`、库内表名不上屏。

---

## 8. 执行过程的颗粒度

### 8.1 现状：五个领域塞进一个 3 毫秒的步骤

九工具链第 6 个 `forecast_child_sales_daily` 被刻意跳过，理由正是「预测数字不归 Agent」
那条错前提。链砍短后，判断被压成一步「读取预测判断事实」，里面装了 **17 个键、5 个领域**：
缺货扭曲 4、季节性 2、广告投放 4、站内活动 4、生命周期 3。

运营看到一行字，看不出它查了五件事。任务面板显示过程的目的是让人判断「这次跑得靠不靠谱」，
一个不透明的「读取事实」说服力远低于「查了历史缺货 → 查了季节系数 → 查了投放变化 → …」。

第 2 步的 `sources` 显示成「需求判断 Agent」——那是执行者名字，不是数据源。它标错、
和它只有一步，同一个原因：**没人描述过这一步做了什么**。补 `sources` 是把标签改对，
补颗粒度才是把过程说清。

职责改回来之后，过程本身就是分领域的，不用人为拆。**分几步、每步叫什么，由 Agent 侧
按真实环节定，工作台照显示。**

### 8.2 步骤不落库，跑完就没了

判断库只有 `fact_child_forecast_judgment_run`（6 行）和 `_factor`（30 行），**没有步骤表**。
步骤是 run 处理函数临时返回的（契约 02 §220：每步 `label / detail / status / duration_ms /
sources[]`），外壳 `renderTrace` 显示完即弃。

后果：「跑于 08-31 08:48」那个戳**点不开过程**。演示时观众进来看到的是已跑好的结果，
最能说明「AI 在干活」的那段恰好不可见。Agent 侧把步骤落库，工作台就能让戳点开。

---

## 9. 待定

| 项 | 说明 |
| --- | --- |
| 一次 run 多久 | 现有 16 秒是「只出五个因子」的量；出 90 天逐日数字是另一个量级。先实测一个子体 |
| 演示跑多少 | 全量 342 个（30,780 行输出），还是只跑要现场点的几个，其余显示快照并标明 |
| 快照怎么摆 | 倾向留作对照基线并排显示（第 5 节末） |
| `run_id` 里两个日期 | `11 §6` 第 1 条已记：`run_date` 是包 as_of（2026-08-03），后缀是墙上时钟。逐日表要按 `date` 查，这个歧义会放大 |
| ~~`11 §6` 第 3 条要重算~~ **已答** | 2026-08-31 实测：原始面 `fact_child_sales_daily` 与 `feature_child_demand_daily` 重统结果**完全一致** —— 都是 27 件、1 个子体、14 个子体-日。所以不论从哪张表统，缺货扭曲在本数据包里就是几乎没有信号，`11 §6` 第 3 条成立，不用改。**注意这一列现已列入 §5 禁读**，Agent 判断缺货扭曲要从可售量自己推 |
