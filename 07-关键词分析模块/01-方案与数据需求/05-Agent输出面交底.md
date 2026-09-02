# 关键词 Agent · 需求与数据契约（v2）

> 按 `00-通用方法与规范/08-Agent需求与数据契约要则.md` v1.1 的五节结构重写。
> **v1 有严重缺陷，已作废**：它把库里 562 条构造证据、14 行构造日报的成品句
> 当「现在的样子」示范给 Agent，等于钉答案；且完全没有第 4 节。
> 审计脚本 `02-数据构建/audit_agent_contract.py` 会把这类问题扫出来。
>
> 复核：2026-08-31 · 数据基准日 2026-08-03 · 库 `v0.1.0/keyword_demo.sqlite`

---

## 0. v1 犯了什么错，为什么要记在最前面

审计结果（`audit_agent_contract.py`）：

| 检查 | 结果 |
| --- | --- |
| 要则 §11-1 声明为「Agent 产出」的 25 个字段，库里有同名列吗 | **25 / 25 全部已有，且全部填满** |
| 要则 §3 库里有多少列命中禁读清单 | **36 列** |
| 要则 §11-2 契约文档里有完整中文结论句吗 | v1 有 3 处；`07-接口JSON样例.json` 有 23 处 |

跟广告那侧是同一个形态：**数据包为了让页面能渲染而构造了结论，契约又把这批结论
原样发给 Agent 当参照。** 实现越忠实，Agent 越只能复印。

**构造数据合法，构造结论不合法**（要则 §6）。本库里 L7/L8/L9 三层
（`fact_keyword_market_change_event` / `fact_keyword_coverage_event` /
`fact_keyword_evidence` / `fact_keyword_audit_record` / `fact_keyword_daily_report`）
全部是构造结论。它们**只为让页面在 Agent 接进来之前能跑**，
接进来之后必须被 Agent 的真产出替换，且 Agent 不得读它们。

---

## 1. 判断对象与触发

**判断对象是「关键词 × 子 ASIN」的关系对**（`dim_keyword_child_pair`，901 对）。

要则 §8 特别点名：关键词的对象是词，不是 ASIN。本模块更细一档——
同一个词在不同子体上的结论不同，所以对象是 pair。三个例外：

| 输出点 | 对象 | 理由 |
| --- | --- | --- |
| C 市场变化事件 | 关键词（`keyword_id`） | 市场需求变化与自有产品无关 |
| B 动态日报 | 站点 × 品线 × 日期 | 一天一行的汇总叙述 |
| E 盘点快照 | 子 ASIN × 盘点日 | 一次盘点一行 |

**触发**（沿用库存预测与竞品的三段式）：

| trigger | 何时 | 跑什么 |
| --- | --- | --- |
| `weekly` | 定时 | 全量监控词 × 有关系的子体 |
| `manual` | 运营在页面上点「重新分析」 | 单个子体或单个词 |
| `priority` | 确定性层发现该对象有变化 | 该对象 |

演示只需现场跑几个对象（不是全量 901 对），但这几个必须完整走真实流程。

---

## 2. 职责表

| Agent 产出 | 工作台算 |
| --- | --- |
| 七类证据成不成立、哪一类 | 覆盖结构统计（五态分区、组内覆盖率、缺口） |
| 结论句与依据句（中文，结论先行） | 位置聚合（当日平均自然位、最好/最差、连降天数） |
| 原始优先级意见 `priority` | 优先级重排（按 `kw.w_*` 四个权重参数） |
| 证据完整度、下一步验证方向 | 词组汇总（按 `dedup_weight` 分权） |
| 市场变化的类型与连续性 | 事件计数与构成条 |
| 覆盖变化的类型与连续性 | 日报每问上方的结构化数字 |
| 日报五个答句 | 环比基期与基期值（由 `kw.compare` 驱动） |
| 引用（`evidence_ids` / `event_ids`） | 表格排序、色阶、区间游标 |

**边界的实操判据**：阈值改完要立刻重算的，留在工作台（塞进 Agent 就得重跑才生效）。
`kw.weak_rank`、`kw.collect_depth`、`kw.streak_days`、`kw.rank_shift`、
`kw.group_dedup`、四个权重——这八个参数影响的全部是工作台侧。

---

## 3. Agent 读哪些表

照要则 §2 的七类对照。**这些是「运营在 Agent 跑的那个时刻，打开后台就能拿到」的东西。**

### 3.1 已发生的事实

| 表 | 可读列 | 是什么 |
| --- | --- | --- |
| `fact_keyword_market_snapshot`（77,400） | `period_type` `period_start` `period_end` `search_volume` `purchase_volume` `purchase_rate` `products_on_sale` `ad_competitors` `click_share_total` `conversion_share_total` `aba_rank` `source_code` | 逐期市场事实。周 26 期 + 月 12 期，**两频率各自成线，绝不折算** |
| `fact_keyword_head_asin`（42,378） | `period_end` `rank_band` `asin` `is_own` | 每词每期的头部与前十名单 |
| `fact_keyword_child_position_daily`（163,982） | `date` `organic_rank` `ad_rank` `organic_state` `ad_state` | 逐日自然位与广告位，182 天 |
| `fact_keyword_child_traffic_daily`（121,031） | `date` `sessions` `orders` `conversion` | 子体逐日流量 |

### 3.2 此刻的状态

| 表 | 可读列 |
| --- | --- |
| `fact_keyword_child_position_daily` 末日切片 | 当前自然位、当前广告位、当前五态 |
| `dim_keyword_scope` | 站点、品线、基准日、各窗口边界 |

### 3.3 产品关系（ATTACH 产品包 v0.3.0）

父子体归属、装盒数、组合内容、尺码与颜色、FNSKU、款号。主数据，客观存在。

### 3.4 词库主数据与词表

| 表 | 可读列 | 备注 |
| --- | --- | --- |
| `dim_keyword_term`（1,991） | `keyword` `keyword_raw` `keyword_cn` `alias_key` `relevance` `primary_category` `all_category_tags` `matched_brand` `brand_role` `first_seen_date` `last_updated_date` `source_files` | 客户原值。**但 `library_status` / `operator_role` 禁读，见第 4 节** |
| `dim_keyword_alias`（118） | `alias_key` `variant` 各变体的搜索量与购买率 | 归一素材。`alias_type_label` 禁读 |
| `dim_keyword_brand`（80） | 品牌名、是否自有 | 客户原值 |
| `bridge_keyword_attribute`（5,277） | `attribute_dimension` `is_primary` | 词×属性维度 |
| `dim_keyword_attribute_seed`（162） | 属性词、维度、**运营人工标的 S/A/B 与 ★** | 客户已给的角色种子，是 J2b 的输入不是答案 |
| `dim_keyword_state_label`（21） | `code` `code_label` | **词表，必须给**（要则 §9 钉词表） |
| `dim_keyword_group`（59）/ `bridge_keyword_group`（2,318） | `group_name` `demand_dimension` `anchor_attribute_word` `dedup_weight` | 需求词组结构 |
| `dim_keyword_child_pair`（901） | `pair_id` `keyword_id` `child_asin` `monitor_from` `anchor_band` | 关系对与真实锚点 |

### 3.5 产品定位（**Demo 例外 · 可读**）

| 表 | 可读列 | 真业务里是什么 |
| --- | --- | --- |
| `dim_keyword_child_goal` | `product_goal` `product_goal_label` `push_role` `push_role_label` | 运营在后台填的产品目标与主推关系。要则 §2 把「运营设定的产品目标」列为可输入 |
| 同上 | `product_lifecycle` | 产品模块的判断。对关键词 Agent 是**上下文**，不是它自己的答案 |

本库这几列是构造的（运营没真填过），按第 3.8 节的例外放行。

### 3.6 外部可观察

关键词搜索量、在售商品数、广告竞品数、ABA 排名、头部 ASIN 与评分——
全在 3.1 的两张表里，抓得到。

### 3.7 上游 Agent 的产出（**Demo 例外 · 可读**）

`fact_keyword_child_absorb` 整张表可读：

| 列 | 是什么 |
| --- | --- |
| `absorb_state` / `absorb_state_label` / `absorb_detail` | 能不能承接扩量 |
| `inventory_limit_label` | 库存限制的类型 |
| `latest_order_date` | 最晚下单日 |
| `base_stockout_date` / `stress_stockout_date` | 基准与压力情景的断货日 |
| `days_to_base_stockout` / `dynamic_safety_days` | 还有几天、安全线在哪 |
| `suggested_replenishment_qty` / `projected_lost_sales_units` | 建议补多少、会少卖多少 |
| `confidence_score` | 库存侧对这个判断的置信度 |

真业务里这些是**库存 Agent 跑出来的**，关键词 Agent 用它是正常的上游接力
（要则 §7 允许）。本库这份不是库存 Agent 跑的、是预烤的，按第 3.8 节的例外放行。

### 3.8 词库定性（**Demo 例外 · 可读，但有代价**）

| 表 | 可读列 | 本该是谁的判断 |
| --- | --- | --- |
| `dim_keyword_term` | `library_status` `library_status_label` | J1 词是否属于本品线 |
| 同上 | `operator_role` `operator_role_label` `operator_role_confirmed` `operator_role_seed_word` | J2b 运营角色定性 |
| `dim_keyword_alias` | `alias_type_label` | 变体归类 |

**放开的代价：J2b「运营角色定性」由判断点降为输入。**
Agent 读得到「这个词是核心词」，就不能再声称它在判断运营角色——
第 2 节的职责表已相应调整，`01-关键词模块能力盘点.md` 的十二个判断点里
J2b 要改标成「输入（Demo 例外）」。

`dim_keyword_attribute_seed` 的 S/A/B 与 ★ 是客户运营人工标的 162 个种子，
本来就是输入，不受本条影响。

### 3.9 这三组例外的来龙去脉

**王楠 2026-08-31 拍定：「这 3 个都可以给 Agent 看。即使前面没输出，
在我们 Demo 这一块可以给 Agent 看。」**

照要则 §7 广告那条口子的格式记在这里——**它是例外，不是规则。**

三组的共同点：**它们都是别的判断点的答案，不是关键词 Agent 自己的产出。**
产品定位来自运营与产品模块，库存承接来自库存 Agent，词库定性是 J1/J2b。
真业务里 Agent 跑的那个时刻它们都存在（有人填、有上游 Agent 产），
只是本库这份是构造的。

**这一条不动第 4 节的核心：关键词 Agent 自己那五张判断层表仍然整表禁读。**
那才是广告那侧翻车的地方，也是本文档 v1 最严重的问题。

---

## 4. 不给 Agent 读的（**比第 3 节重要**）

要则 §8：「第 3 节漏一张表只是少信息，第 4 节漏一列就是答案泄漏，而且没有症状。」

审计扫出 **36 列**命中禁读清单。逐列写明它已经替 Agent 答了什么：

### 4.1 本 Agent 自己的产出（L7/L8/L9 五张表整表禁读）

| 表 | 列 | 已经替 Agent 答了 |
| --- | --- | --- |
| `fact_keyword_evidence` | `evidence_id` `evidence_type` `priority` `conclusion` `main_basis` `evidence_completeness` `next_verification` `competitor_verification_state` `ref_market_event_ids` `ref_coverage_event_ids` | 哪一类证据成立、多要紧、结论是什么、依据是什么、够不够、下一步给谁 |
| `fact_keyword_daily_report` | `q1_traffic_result` `q2_main_movers` `q3_core_coverage_change` `q4_new_signals` `q5_priority_next` `traffic_proxy_value` `traffic_proxy_delta` `priority_evidence_ids` `coverage_event_ids` | 五个答案全文；每一句都是成品结论，读一眼就不用判断了 |
| `fact_keyword_market_change_event` | `event_type` `continuity` `label` `change_ratio` `change_shape_label` | 市场变化是哪一类、连不连续、怎么说 |
| `fact_keyword_coverage_event` | `event_type` `continuity` `label` `is_core_keyword` | 覆盖变化是哪一类、怎么说 |
| `fact_keyword_audit_record` | `evidence_count` `evidence_type_counts` | 这次盘点有几条什么证据 |

**这五张表在 Agent 接进来之后是写入目标，不是读取源。**

### 4.2 跨模块动作与构造元数据

| 列 | 为什么禁 |
| --- | --- |
| `fact_keyword_market_snapshot.suggested_bid_low` / `suggested_bid_high` | 出价是广告模块的活（要则 §5 跨模块动作） |
| `fact_keyword_market_snapshot.comparable_block_reason` | 已成文的中文理由 |
| `dim_keyword_child_pair.pair_shape_label` | 覆盖形态定性（双覆盖稳定/…），是判断，且不在放开的三组里 |
| 所有表的 `value_origin` | 哪些是造的（且 G9 禁上屏） |
| 所有表的 `rule_version` | 构造元数据 |

### 4.3 已经放开的三组（Demo 例外，见第 3.5 / 3.7 / 3.8 节）

原 v2 初稿把下面三组也列进禁读，**王楠 2026-08-31 拍定放开**，已移到第 3 节：

| 组 | 列 | 放开理由 |
| --- | --- | --- |
| 产品定位 | `product_goal` `push_role` `product_lifecycle` 及各 `_label` | 真业务里是运营填的 / 产品模块判的，不是关键词 Agent 的答案 |
| 库存承接 | `fact_keyword_child_absorb` 整表 + `inventory_limit_label` | 真业务里是库存 Agent 的产出，上游接力（要则 §7） |
| 词库定性 | `library_status` `operator_role` `alias_type_label` 及各 `_label` | J1/J2b 的答案；放开的代价是 J2b 由判断点降为输入 |

**放开的边界**：这三组是**别人**的答案。关键词 Agent 自己那五张表（第 4.1 节）
仍然整表禁读——那是广告那侧翻车的地方。

---

## 5. 输出与上屏

### 5.1 输出什么

照要则 §4 四类。**每个字段只给形状、词表、约束，不给成品句。**

#### A 证据结论 → `fact_keyword_evidence`

| 字段 | 形状 | 约束 |
| --- | --- | --- |
| `evidence_type` | 码值 | 必须在下面七类词表内 |
| `priority` | 整数 ≥1 | 原始意见。**页面会按 `kw.w_*` 四个权重重排**，这不是最终顺序 |
| `conclusion` | 中文一句话 | 结论先行；40–70 字；不含英文码值；不含防御性表述 |
| `main_basis` | 中文一句话 | 引用的每个数字必须能与确定性层同口径核对上；可用分号分段 |
| `evidence_completeness` | 码值 | `full` / `partial` / `insufficient` |
| `next_verification` | 码值 | `advertising` / `competitor` / `observe` |
| `competitor_verification_state` | 码值 | `na` / `pending` |
| `ref_market_event_ids` | JSON 数组 | 必须能解析到本次产出的市场事件，不许悬空 |
| `ref_coverage_event_ids` | JSON 数组 | 同上 |

**七类证据词表**（要则 §9：词表要钉，中文与码值的归属逐字段写死）：

```
coverage_gap                    → 产品覆盖缺口
scene_longtail_signal           → 场景与长尾信号
insufficient_data               → 数据不足
core_position_risk              → 核心位置风险
inventory_limited               → 库存受限机会
market_opportunity              → 市场需求机会
pending_competitor_verification → 待竞品验证信号
```

**Agent 一律输出码值**，中文标签由工作台在读取边界翻译（翻译只发生在一处）。
`conclusion` / `main_basis` 是契约逐字段点名的自由文本，例外。

**七类的条数分布不钉。** 本库现有 127/135/103/88/59/26/24 是构造结果，
不是目标——照着凑就是复印机。

#### B 动态日报 → `fact_keyword_daily_report`

| 字段 | 形状 | 约束 |
| --- | --- | --- |
| `traffic_proxy_value` | 整数 | 代理指标当期值 |
| `traffic_proxy_delta` | 小数比率 | 判断不出给 `null` |
| `q1_traffic_result` | 中文一句 | 流量获取结果 |
| `q2_main_movers` | 中文一句 | 主要增长与下降 |
| `q3_core_coverage_change` | 中文一句 | 核心词覆盖与位置 |
| `q4_new_signals` | 中文一句 | 新出现的信号 |
| `q5_priority_next` | 中文一句 | 最值得继续看 |
| `priority_evidence_ids` | JSON 数组 | 指向本次产出的证据 |

**五个答句每一句上方都有页面自算的数字**，Agent 写的句子必须与之口径一致：

| 问 | 页面自算并显示在句子上方 |
| --- | --- |
| Q1 | 较前一日 %、基期日期与值 |
| Q2 | 上涨/下滑/竞争加剧词组数 |
| Q3 | 新增覆盖、丢失覆盖、涉及核心词 |
| Q4 | 覆盖或位置变化总数、其中显著、涉及子体 |
| Q5 | 待处理事项总数、取样子体数 |

这是交叉核对不是钉答案（要则 §10）：钉「你引用的数字不许编」对，
钉「你的结论必须是这一个」错。

**现存 Q3 就是这条的反例**：库里写「新增覆盖 0 条、丢失覆盖 0 条，
其中涉及核心词 114 条」，页面自算是 162 / 68 / 352，并排显示直接矛盾。
根因在 `lib_l89.py` 的 `build_daily_reports()` 按 `to_date == 当日` 过滤，
而汇总型事件的 `to_date` 也是当日。**Agent 接进来时这句重新生成，不要沿用。**

#### C / D 两张事件表

```
市场变化 event_type:
  demand_up → 搜索需求上涨 | demand_down → 搜索需求下滑
  competition_up → 竞争加剧 | insufficient_history → 历史样本不足
  not_comparable → 口径变更导致不可比
覆盖变化 event_type:
  organic_gained → 新增自然覆盖 | organic_lost → 丢失自然覆盖
  organic_up → 自然位上涨 | organic_down → 自然位下降
  ad_gained → 新增广告覆盖 | ad_lost → 丢失广告覆盖
  beyond_depth → 跌出采集深度
continuity: continuous → 连续变化 | single_period → 单期波动 | insufficient → 样本不足
```

`label` 是中文一句话；`from_rank` / `to_rank` 允许为空
（新增覆盖没有 from、丢失覆盖没有 to）。

#### E 盘点快照

Agent 只出 `evidence_count` 与 `evidence_type_counts`；
统计数（`pair_count` / 各 covered 计数 / `best_organic_rank` / `median_organic_rank`）由工作台填。

### 5.2 不输出什么（要则 §5）

| 不输出 | 为什么 |
| --- | --- |
| 覆盖结构统计、位置聚合、词组汇总、优先级最终顺序 | 确定性算术，阈值要能在参数面板改完立刻重算 |
| 加词、否词、出价、预算 | 跨模块动作（广告模块的活） |
| 综合评分 / 单一机会分数 | 要分级加可解释依据 |
| 因果断言 | 只给相关与条件判断 |
| 英文码值出现在 `conclusion` / `main_basis` / `label` / 五个答句里 | 翻译只发生在一处；G9/G17 会拦 |
| 「本结论仅供参考」这类 | 不上屏 |

### 5.3 判断不出给 NULL

要则 §4：**这是契约的正式选项。** 判断不出就给 `null`，不许凑一个数。
需求预测实测走过这条路——生命周期那一项真模型给了 `null`。

### 5.4 同对象重跑允许结论不同

要则 §11-4：一个真在判断的 Agent，同对象重跑结果**可以**不同。
本契约明确允许。任何要求「两次必须一致」的门禁都是同一性门禁，退回。

### 5.5 上屏

页面展示的就是 Agent 那一份。三条：

1. **五张表接进来之后，页面读 Agent 的 run，不读预烤行。**
2. **Agent 没跑过的对象必须降级说明**，页面直说「尚未生成关键词判断」，
   不能悄悄回落到预烤值（要则 §7）。
3. 上屏文案纪律见 `00-通用方法与规范/07-需求判断上屏交底.md` 与
   `06-视觉基准要则.md`；机械门禁是 `09-工作台/tests/test_keyword_render.mjs`
   扫渲染后的 `innerText`，禁词零命中。

---

## 5A. 数据接口：Agent 写什么、页面怎么读

**这一节已用往返测试闭环验证过，16 条全过：**

```bash
/usr/bin/python3 09-工作台/tests/test_keyword_agent_roundtrip.py
```

它真造一份 Agent 输出、让选库逻辑认它、让载荷带上它、断言页面拿到的是
Agent 写的那句原话，跑完删除临时文件。**光看文档不算确认，跑这个才算。**

### 5A.1 落库形态：整库替换，不是往现有表插行

Agent 不修改现有的 `keyword_demo.sqlite`。它产出**两个文件**：

```
09-工作台/modules/keyword/derived/
  keyword_agent_current.sqlite    ← 业务库：原库的全部表 + 一张 manifest
  keyword_agent_state.sqlite      ← 旁挂账本：只有 run 头
```

业务库 = 原库结构照搬（24 张表），其中五张判断层表的内容换成 Agent 的产出，
**再加一张 manifest**：

```sql
CREATE TABLE fact_keyword_agent_manifest (
    run_id       TEXT PRIMARY KEY,   -- 本次运行的身份
    context_hash TEXT NOT NULL,      -- 与账本核对用，两边必须相同
    params_json  TEXT NOT NULL,      -- 本次判断用的参数契约，见 5A.3
    status       TEXT NOT NULL       -- running | completed
);
```

旁挂账本只有一张表：

```sql
CREATE TABLE fact_keyword_agent_run (
    run_id       TEXT PRIMARY KEY,
    context_hash TEXT NOT NULL,
    status       TEXT NOT NULL       -- running | completed
);
```

### 5A.2 页面认这一份的四个条件（缺一条就回落到原库）

`modules/keyword/agent_result.py` 的 `select_database()` 逐条查：

| # | 条件 | 不满足时 |
| --- | --- | --- |
| 1 | 两个文件都存在 | `base` · 没有已发布的关键词 Agent 结果 |
| 2 | manifest 的 `status = 'completed'` | `base` · current manifest 未完成 |
| 3 | 账本里同 `run_id` 的行也 `completed`，**且 `context_hash` 与 manifest 相同** | `base` · current 与 completed 台账不一致 |
| 4 | manifest 的 `params_json` 与**当前请求的参数**一致 | `stale` · 当前比较周期或优先级权重与最近 Agent 运行不一致 |

第 3 条是「半份结果不上屏」的实现：**写入顺序必须是先写业务库、最后改账本状态**。
中途失败的那一批 `context_hash` 对不上或状态还是 `running`，天然不可见。

第 4 条是这套设计比按行 `run_id` 强的地方：运营在参数面板把比较周期从「前一日」
改成「前一周」，Agent 那份是按前一日判的——**当期数字配旧结论就是自相矛盾**，
所以整份判为 `stale`，页面回落到原库，并且日报五答会被替换成占位。

### 5A.3 参数契约（`params_json` 的形状）

只有这六项参与比对，其余参数不影响判断层：

```json
{
  "compare": "day",            // day | week | 4week
  "rank_shift": 3,
  "group_dedup": true,
  "weights": {
    "w_demand": 0.30, "w_change": 0.30,
    "w_push": 0.20,   "w_evidence": 0.20
  }
}
```

比对前会归一：`rank_shift` 转 int、`group_dedup` 转 bool、四个权重 round 到 4 位。
**Agent 必须把它这次实际用的参数原样写进 `params_json`**——写错会被判 `stale`，
Agent 白跑。

### 5A.4 Agent 要写的五张表

业务库里这五张表的内容替换成 Agent 的产出，**列结构不变**（页面按现有列名读）：

| 表 | Agent 填的列 | 页面从哪读 |
| --- | --- | --- |
| `fact_keyword_evidence` | 见第 5.1 节 A | 页面一优先列表、页面三缺口板块、决策摘要首条 |
| `fact_keyword_daily_report` | 见 5.1 节 B | 页面一 hero + 五问五答 |
| `fact_keyword_market_change_event` | 见 5.1 节 C | 页面一词组变化样例、页面二单词深研 |
| `fact_keyword_coverage_event` | 见 5.1 节 D | 页面一核心词表、页面三事件构成条 |
| `fact_keyword_audit_record` | 见 5.1 节 E | 页面三盘点记录 |

其余 19 张表**原样复制**，不要改——页面会从同一个库里读事实层。

### 5A.5 页面侧已经就绪的部分

| 文件 | 干什么 |
| --- | --- |
| `modules/keyword/agent_result.py` | 选库：四条件判定，返回 `base` / `current` / `stale` |
| `modules/keyword/module.py` | 六个路由都在载荷里带 `agent_result`；`stale` 时把日报五答换成占位 |
| `web/modules/keyword.js` 的 `sourceBand()` | 三态的判断来源条，四个页面各挂一条 |
| `tests/test_keyword_agent_roundtrip.py` | 16 条往返验证 |

载荷里的 `agent_result` 块：

```json
"agent_result": {
  "condition": "正常 | 过期 | 缺失",
  "run_id": "kw-2026-08-03-1",
  "using_current": true,
  "message": "回落原因，正常时为 null"
}
```

页面对应三种呈现：

| `condition` | 判断来源条 | 判断层内容 |
| --- | --- | --- |
| 缺失 | 橙色·「尚未接入关键词 Agent」 | 构造脚手架 |
| 过期 | 紫色·「Agent 结果已过期，本页回落到构造内容」 | 构造脚手架，日报五答换占位 |
| 正常 | 绿色·「本次 Agent 判断」+ run_id | Agent 那一份 |

**页面侧不需要再改**——两个文件出现且四条件满足，页面自动切过去。

### 5A.6 Agent 侧接进来的检查单

1. 业务库是原库的完整副本（24 张表），只替换五张判断层表的内容
2. 加 `fact_keyword_agent_manifest`，`params_json` 写这次实际用的六项参数
3. 建旁挂账本，`context_hash` 与 manifest 完全相同
4. **写入顺序：业务库全写完 → 最后把账本改成 `completed`**
5. 跑 `test_keyword_agent_roundtrip.py`，16 条必须全过

---

## 6. 门禁必须是约束型（要则 §10）

现有四套测试都是约束型，没有一条拿 Agent 结论去比对确定性层：

```
tests/test_gates.py              接入契约 23 条
tests/test_keyword_render.mjs    渲染态禁词 36 条，扫 innerText
tests/test_keyword_routes.mjs    深链往返 15 条
tests/test_keyword_params.py     参数真改数字 11 条
```

**Agent 接进来还缺这几条约束门禁**（尚未实现，需要先拍第 4.6 节三个问题）：

| 断言 | 类型 |
| --- | --- |
| `evidence_type` / `continuity` / `next_verification` 等取值必须在词表内 | 约束 |
| `main_basis` 里引用的数字必须等于确定性层同口径值 | 交叉核对 |
| `ref_*_ids` 必须能解析到本次 run 的事件，不许悬空 | 约束 |
| `causal_claim` 必须为 false | 约束 |
| `conclusion` 字数上限、无英文码值、无防御性表述 | 约束 |
| 符号方向与结论一致（说「在退」就不能配正的 `change_ratio`） | 约束 |

**依赖具体判断值的门禁要用合成行，不要指定活对象**（要则 §11 配套边界）——
LLM 重跑会变，指定活对象的门禁会今天绿明天红。
确定性特征（有没有真实锚点、跑过没跑过）不受此限，
那两个演示对象 `B0B3LWGP36`（66 对全锚点）与 `B0CBPXNC1M`（五态齐全）仍要显式打上。

---

## 7. 落库

不在本文管辖范围，见 `00-通用方法与规范/07-Agent运行与落库口径.md`。

本模块现状：五张判断层表只有 `run_date` 与 `rule_version`，
**没有 run 头表、没有 `created_at`**。库存预测 Agent 已有成熟形态
（`fact_child_forecast_run`），建议照它加，但表结构由你定，我不自己发明。

---

## 8. 写完自检（要则 §11 六条）

| # | 条目 | 本文状态 |
| --- | --- | --- |
| 1 | 产出侧字段在数据包里有同名列吗 | **有，25/25**。已在第 4.1 节整表禁读 |
| 2 | 契约文档里有完整中文结论句吗 | 无。v1 有 3 处已删；JSON 样例已抹 51 个字段的值 |
| 3 | 门禁里有「等于确定性层结论」的判据吗 | 无。第 6 节列的全是约束型 |
| 4 | 同对象连跑两次允许结论不同吗 | 允许，第 5.4 节明写 |
| 5 | 换特征不同的对象结论会变吗 | 两个演示对象特征互补，第 6 节要求显式打上 |
| 6 | 输入够不够做这个判断 | 第 3 节七类齐；但 4.6 三问未拍前，库存受限与产品目标两类证据的输入待定 |

重跑审计：

```bash
/usr/bin/python3 02-数据构建/audit_agent_contract.py
/usr/bin/python3 02-数据构建/sweep_masked_sample.py
```
