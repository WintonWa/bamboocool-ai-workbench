# 广告 Agent 契约审计 v1.0

2026-08-31 · 按 `00-通用方法与规范/08-Agent需求与数据契约要则.md` 逐条自检

要则 §12 判定 ads「缺第 4 节 / 四阶段答案来自 constructed 决策行 / 门禁是同一性型 / 要重写契约」。
本文是逐字段核对的结果，比那句判定更严重：**产出侧的投影被标成了事实真值**。

审计对象：

- `04-广告分析模块/02-数据构建/page2-ext/page2_decision_ext.sqlite`（14 表）
- `01-方案与数据需求/04-广告模块Agent输出点清单.md`（我 08-31 写的）
- `01-方案与数据需求/05-广告模块交接给Agent.md`（同上）
- `01-方案与数据需求/agent-samples/`（10 个真实响应）

---

## 1. 输入侧：十类证据逐字段判定

判据是要则 §1 的三问。第 3 问「它在构造脚本里被写出来过吗」是我上一版全部漏掉的。

### 1.1 干净的（可以继续当输入）

| 证据 | 字段 | 为什么合法 |
|---|---|---|
| `AD_PERFORMANCE` | `spend` `ad_sales` `acos` `objects[]` | 历史广告花费与订单，后台导得出 |
| `AD_PLACEMENT` | `terms[]`（词 / 展示 / 份额 / 位次） | 历史搜索词报表 |
| `ATTRIBUTION_GAP` | `spend` `ad_sales` `objects` | 历史事实：17 个只出现在成交侧的对象 |
| `SALES_TREND` | `daily_avg_3d/7d/14d/30d/60d/90d` `units_30d` | 历史实销的嵌套窗口，纯算术 |
| `BUSINESS_EVENT` | `inbound[]`（采购单数量与 ETA）`planned[]`（促销排期） | 要则 §2「人排的计划」，人已排好 |
| `PRODUCT_STAGE` | `product_name` `style` `size` `colorway` `category` `parent` `operator` `rating` `category_rank` | 主数据与当前快照 |

六类、共 20 个字段可以原样保留。

### 1.2 必须摘出去的（产出侧被当输入喂了）

| 证据 | 字段 | 现标注 | 它已经替 Agent 答了 | 要则依据 |
|---|---|---|---|---|
| `INVENTORY` | `coverage_days` 41.79 | fact / direct | 还能卖几天 | §3 从预测派生的投影 |
| | `safety_breach_date` 2026-08-31 | fact / direct | 什么时候破安全线 | 同上 |
| | `stress_stockout_date` 2026-09-09 | fact / direct | 什么时候断货 | 同上 |
| | `base_stockout_date` | fact / direct | 同上 | 同上 |
| | `latest_order_date` 2026-06-13 | fact / direct | 最晚什么时候下单 | 同上 |
| | `suggested_replenishment_qty` 2531 | fact / direct | 该补多少 | 同上 |
| | `dynamic_safety_days` 21 | fact / direct | 安全线定在哪 | 依赖预测 |
| | `risk_status` `replenishment_gap` | fact / direct | 结论本身，且是英文码值 | §3 已分级的结论 |
| | `confidence_score` 0.8033 | fact / direct | 这个判断多可信 | §3 已给的置信度 |
| `PRODUCT_STAGE` | `lifecycle` 成熟期 | fact / direct | 生命周期在哪一段 | §3 正文点名的例子 |
| `PRODUCT_GOAL` | `goal_label` `goal_type` `status` | inference / constructed | 产品目标是什么 | §3 已分级的结论 |
| `KEYWORD` | `losing` 2 | fact / constructed | 哪些词在丢位置 | 位置趋势是判断 |
| | `absent_high_match` | fact / constructed | 哪些高匹配词没覆盖 | 匹配度是判断 |
| `COMPETITOR` | `types` `[price, rank, keyword_entry]` | fact / derived | 竞品压力属于哪几类 | §3 已分级的结论 |

**14 个字段。其中 11 个标注为 `nature=fact`，10 个标注为 `origin=direct`。**

投影标成 `direct` 比标成 `constructed` 危险得多：`constructed` 至少在对账时能被认出来，`direct` 是在宣称「这是客户报表原值」。

### 1.3 循环依赖：产品目标同时在两端

`ext_product_goal` 5 行 ＋ `PRODUCT_GOAL` 类证据 5 行，同一份 `goal_label`。

我上一版文档把 B0「产品目标判断」列为 Agent 的**阻塞级输出点**，同时把 `PRODUCT_GOAL`
证据列为 Agent 的**输入**。Agent 被要求输出的东西已经递到它手里了。

这不是标注问题，是得二选一：

- **选 A**：产品目标是运营设定的（要则 §2「产品定位」允许当输入）。
  那就没有 `rationale`、没有 `pending_operator_confirmation`、Agent 不判它。
- **选 B**：产品目标是 Agent 的判断。
  那就从证据里整条摘掉，Agent 只拿销量趋势 ＋ 库存状态 ＋ 产品定位去自己判。

**已拍定（王楠 2026-08-31）：选 A，产品目标是运营填的，Agent 不判它。**

已执行：`goal_status` 改 `confirmed`、`rationale` 从推断链换成运营口径的意图
（「保住现有规模，先把库存承接补齐」）、`source_ref` 改 `operator_set`、
证据 `evidence_nature` 改 `confirmed`（上屏「运营已确认」）、标题去掉「判断」二字。
迁移脚本 `02-数据构建/migrate_goal_to_operator_set.py`，构建器已同步。

档位未受影响：`rule_status` 仍 `unconfirmed`，五个对象仍停在「条件性判断」。

同类二选一还有三处：`KEYWORD.losing` 对 B0c、`COMPETITOR.types` 对 B0d、
`PRODUCT_STAGE.lifecycle` 对（没有对应输出点，但它是结论）。

### 1.4 §7 本轮例外的适用边界

要则 §7 允许「广告暂时把数据包的库存投影当作库存 Agent 的产出使用，不换源」。

**这条救的是 1.2 表里前 9 行的存在，不救它们的标注。** 用例外的前提是把它们声明成
「上游 Agent 本次产出」，并写明下游依赖上游先跑、上游没跑时必须降级。
现在它们伪装成 `fact/direct`，等于绕过了例外的前提。

`lifecycle` / `goal_label` / `losing` / `types` 四项不在例外范围内——
它们不是库存 Agent 的产出，是我们为搭页面烤的。

---

## 2. 我那两份文档的违规

### 2.1 `04-广告模块Agent输出点清单.md`

| # | 违规 | 要则依据 |
|---|---|---|
| 1 | **没有「不给 Agent 读的」一节** | §8 第 4 节，缺一节退回；且「比第 3 节重要」 |
| 2 | 给了完整中文结论句当模板：「近 3 日日均 90 件对 90 日均 142 件为 −37%，库存判定需要补货，安全库存 2026-08-31 被击穿」并写「照这个格式」 | §11-2 契约里出现完整中文结论句 = 钉了答案 |
| 3 | 第 15 节列出五个对象的完整任务链（P0 先核验入库再扩量 → 暂缓 …）并写「照着这个规模出」 | §6 构造产出不合法；§11-2 |
| 4 | 把 B0 产品目标列为输出点，同时在第 2 节把 `PRODUCT_GOAL` 证据列为输入 | §3 答案泄漏 |
| 5 | B0c 匹配度 / B0d 竞品压力 / B0e 结构问题同样两端都在 | 同上 |
| 6 | 「现有取值 X 种」逐个列出中文结论取值 | 这条**不算违规**：§9 要求钉词表。保留 |

### 2.2 `05-广告模块交接给Agent.md`

| # | 违规 | 要则依据 |
|---|---|---|
| 1 | 第 3 节表格把 `ext_product_goal` `ext_decision_evidence` `ext_keyword_match` `ext_competitor_pressure` `ext_structure_issue` 列为「板块 2/3 的数据来源」，读起来就是 Agent 的输入 | §3 |
| 2 | 第 8 节整张「换个对象结论要真的变」对照表，把五个对象的库存判定、趋势、任务链、建议方向全列出来 | §11-2；本意是给判据，写法却是给答案 |
| 3 | 第 5 节三条数据不变量、第 7 节枚举不上屏、第 2 节筛选语义 | **不算违规**，是口径与形状，保留 |

### 2.3 `agent-samples/`

`run.json` 是四段的真实响应，包含 21 条诊断与建议的完整中文文本。
把它当「样例」交出去，对方照着对齐就是复印机。

`context.json` 里含 1.2 表的全部 14 个字段。

**形状要给，答案不能给。** 修法是保留结构、把自由文本与结论枚举替换成占位符。

---

## 3. 门禁是同一性型（要则 §10）

现在 `GET /api/ads/gate` 只查一件事：`evidence_ids` 有没有悬空。
那是约束型的一条，方向对但太少。

真正的问题在数据层自检 `tests/selfcheck_decision.py`：它比对四段与四张表的一致性——
回放实现下必然全绿，换成真 Agent 后**任何真判断都会让它变红**。

按 §10 该有的约束型判据（现在一条都没有）：

| 判据 | 现状 |
|---|---|
| 取值必须在词表内 | 无 |
| `numbers` 引用的数字必须等于确定性层同口径值 | 无 |
| 不得与事实矛盾（说位置在丢，位置数据必须真在降） | 无 |
| 符号须与结论一致 | 无 |
| `evidence_ids` 必须能解析 | **有** |
| 禁止因果断言 `causal_claim=false` | 数据层查了，接口层没查 |
| 一句话字数上限 | 无 |

§11-4 那条一句话判据现在必然不通过：**同一个对象连跑两次，结论逐字节相同**，
因为四段是从表里读的。

---

## 4. 要改什么

### 4.1 文档（我这轮就改）

1. `04` 号文档补第 4 节「不给 Agent 读的」，逐列写明它替 Agent 答了什么
2. 删掉完整中文结论句模板与五对象结论链表，换成「必须满足的判据」
3. B0 / B0c / B0d / B0e 四处二选一先标成待你拍，不再两端都写
4. `05` 号文档第 3 节表格把「Agent 产出，不得当输入」的行显式标出
5. 第 8 节改成判据（同对象重跑可以不同、换对象必须变），不给答案
6. 样例的自由文本与结论枚举替换成占位符，README 写明「形状参照，不是标准答案」

### 4.2 数据（要你拍口径再动）

1. `INVENTORY` 证据拆两半：当前可售与在途留作输入；9 个投影字段改标注为
   「上游库存 Agent 本次产出」，并按 §7 写明降级路径
2. `PRODUCT_STAGE.lifecycle` 从证据里摘掉（它没有对应的输出点，摘掉即可）
3. `PRODUCT_GOAL` / `KEYWORD.losing` / `COMPETITOR.types` 按 1.3 的二选一处理
4. 把 11 个 `nature=fact` 的错标注改对——这一条与上面三条独立，无论怎么选都要改

### 4.3 门禁（数据口径定了再写）

把同一性自检换成约束型七条，其中「凡依赖具体判断值的门禁用合成行、不指定活对象」
是要则 §11 的配套边界，现在的自检正好违反它（打在 B0B3LWGP36 这个活对象上）。

---

## 5. 一句话

我上一版把「页面渲染逼出来的字段」当成了「Agent 该输出的字段」，这一步是对的；
错在没有反过来问一遍——**这些字段的值现在已经在库里了，那 Agent 还判断什么。**
