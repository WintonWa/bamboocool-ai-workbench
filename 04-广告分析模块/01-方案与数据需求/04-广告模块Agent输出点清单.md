# 广告模块 Agent 输出点清单 v1.0

2026-08-31 · 给 Agent 实现方的字段级契约

这份清单的字段不是设计出来的，是**前端渲染逼出来的**：页面上每一处非事实的
文字都在这里有对应字段，页面渲染不出来的字段就是 Agent 必须补的字段。
当前 Demo 用已落盘的决策链回放（`page2_decision_ext.sqlite` 14 表），
**接口形状与真 Agent 就绪后完全一致**，届时只替换读取来源。

- 数据包：`04-广告分析模块/02-数据构建/v0.2.0/advertising_demo.sqlite`（35 表）
- 决策扩展库：`04-广告分析模块/02-数据构建/page2-ext/page2_decision_ext.sqlite`
- 前端消费方：`09-工作台/web/modules/ads.js`，服务端 `09-工作台/modules/ads/`
- 演示对象：B0B3LWGP36 / B0B3M8S4CQ / B0B6ZT7W64 / B0B3MBYGR5 / B0CJV56N43

---

## 0. 输出点总览

| # | 输出点 | 页面·板块 | 对应能力 | 触发 | 阻塞性 |
|---|---|---|---|---|---|
| A1 | 广告目的标签建议 | 一·板块2/7/8 | 能力三 | 数据构建时批量 | 不阻塞，可为「无法识别」 |
| ~~B0~~ | ~~产品目标判断~~ **已改为输入** | 二·板块2 | — | 运营在系统里填 | 见第 2 节 |
| B0b | 目标约束分档 | 二·板块2 | 能力五 | 进页面前已就绪 | 不阻塞 |
| B0c | 词与产品匹配度 | 二·板块3 | 能力五 | 进页面前已就绪 | 不阻塞 |
| B0d | 竞品压力分类 | 二·板块3 | 能力五 | 进页面前已就绪 | 不阻塞 |
| B0e | 结构问题识别 | 二·板块5 | 能力五 | 进页面前已就绪 | 不阻塞 |
| B1 | 应有广告任务 | 二·板块4 | 能力六 | 点「开始分析」第 1 段 | 后三段的输入 |
| B2 | 任务—结构对照 | 二·板块6 | 能力七 | 第 2 段 | 诊断的输入 |
| B3 | 广告诊断与优先级 | 二·板块7 | 能力八 | 第 3 段 | 建议的输入 |
| B3b | 诊断覆盖说明 | 二·板块7 | 能力八 | 随第 3 段 | 不阻塞 |
| B4 | 广告调整方案 | 二·板块8 | 能力九 | 第 4 段 | 板块9 的输入 |

**没有 Agent 的地方**（避免误接）：

- 能力一/二/四/十全是算子层。页面一除 A1 外**不出任何判断**——不读产品目标、
  库存、关键词、竞品，不出诊断建议。禁的是动作措辞（建议调整/提高竞价/降低预算/
  否词/暂停）。
- 能力十一是记录与交接，Agent 不产出内容，但要**接收** D+3/D+7 回流当后续证据。
- 板块1 范围与数据状态、板块5 数值异常、板块6 横向对比：全部算子，阈值由运营配置。
  没配规则时只出数值变化和排序，不标异常。

---

## 1. A1 — 广告目的标签建议（页面一）

### 界面呈现

- 侧栏「广告目的」标签族的可勾选项，每个取值带来源与确认状态
- 对象清单的目的列
- 详情抽屉「标签与生效历史」面板：来源、确认状态、生效区间

### Agent 必须输出

一个广告对象（广告组或投放对象）一条：

| 字段 | 类型 | 说明 |
|---|---|---|
| `ad_object_id` | text | 广告对象 id |
| `label_type` | text | 固定 `AD_PURPOSE` |
| `label_value` | text | **中文目的名**，见下方取值表 |
| `label_source` | text | 固定 `ai_suggested` |
| `confirmation_status` | text | `pending` 待运营确认 / `unrecognized` 无法识别 |
| `effective_from` | date | 生效起日 |
| `rationale` | text | **当前库里没有，必须补**：判断依据一句话 |
| `evidence` | json | **当前库里没有，建议补**：命名线索/投放内容/历史记录 |

现有取值（989 条，全部 `AD_PURPOSE`）：关键词流量获取 / 大词抢位 /
竞品与关联商品拦截 / 自动捡漏 / 品牌防守 / 无法识别 等 8 种（广告组层）。

### 约束

- 线索来自广告名称、投放对象内容、运营已有记录三处（能力三 5.2）
- **识别不出就给 `unrecognized`，不许猜**。现状 989 条里 127 条是 unrecognized，
  这是设计要演的状态，不是失败
- 不能静默覆盖 `system_attribute` / `auto_mapping` / `group_inherited` 三种来源
- 一个对象含多个目的时保留混合状态，不为分类强行选单一标签
- 目的标签只说明归入什么业务类别，**页面一不判断这个目的对不对**

### 缺口（要你补）

方案 3.4 明写「AI 可以建议…但必须展示依据和确认状态」。
`fact_ad_label_version` 现有列只有确认状态，**没有依据字段**。
Agent 侧要输出 `rationale`，我在表上加列并在详情抽屉里渲染。

---

## 2. ~~B0 产品目标判断~~ → **产品目标是输入，Agent 不判它**

**王楠 2026-08-31 拍定：产品目标是运营在系统里填的，Agent 直接拿来用。**

原因是它之前循环了：我们从销量趋势与库存判定推出目标，却同时把它当证据递给
Agent、又列为 Agent 的输出点。Agent 被要求判断的东西已经在它手里了。

要则 §2 把「运营设定的产品目标」列在「产品定位」这一类合法输入里，
所以这条路是通的。

### 现在它长什么样

| 字段 | 值 | 说明 |
|---|---|---|
| `goal_label` | 稳定经营并补齐库存承接 等四种 | 运营从词表里选的 |
| `goal_status` | `confirmed` | 运营填的就是确认过的 |
| `rationale` | 「保住现有规模，先把库存承接补齐」 | **运营口径的意图**，不含推断数字 |
| `source_ref` | `operator_set` | 不再是 `derived from sales_window + inventory` |
| `evidence_nature` | `confirmed` → 上屏「运营已确认」 | 词表第三值，之前一直空着 |

对应证据类型 `PRODUCT_GOAL`，标题「当前产品目标」（原来叫「当前产品目标判断」，
「判断」二字要去掉——它不是判断了）。

### 这对你的影响

- **不要输出产品目标。** 它是给你的输入。
- 它是你判断的**约束**：目标是「加速去库存」时，扩量类任务要让位给清货类。
- `goal_status` 不是 `confirmed` 时（真实业务里运营没填），
  整条链的判断档位降为 `conditional`，并在 `notes` 里写明缺什么。
  这条降级逻辑保留，因为真会遇到没填目标的对象。
- 阈值（`rule_status`）仍是 `unconfirmed`，所以当前五个演示对象的档位
  仍是「条件性判断」，不会因为目标确认了就升成「正式判断」。

---

## 3. B0b — 目标约束分档（页面二板块2）

### 界面呈现

板块2 目标下方分两组列出：硬性约束（必须先满足）与观察项（只看不拦）。

### Agent 必须输出

一个目标版本多条：

| 字段 | 类型 | 取值 / 说明 |
|---|---|---|
| `constraint_id` | text | |
| `goal_version` | text | 关联运营设定的目标版本（输入）|
| `kind` | text | **`hard` 硬性 / `observe` 观察** — 这个分档是判断 |
| `domain` | text | `inventory` / `cost` / `traffic` / `event` |
| `label` | text | 中文短标签，如「安全库存将在 2026-08-31 被击穿」 |
| `detail` | text | 展开说明，带数字 |
| `is_satisfied` | int | 0/1，未知留空 |
| `evidence_ref` | text | 指向 evidence_id |

### 约束

`hard` 与 `observe` 的分档直接决定建议能不能给：有未满足的 `hard` 约束时，
扩量类建议必须降为 `PREREQUISITE` 或 `DEFER`。

---

## 4. B0c — 词与产品匹配度（页面二板块3）

### 界面呈现

板块3 关键词表的「匹配度」列 + 点开看两侧理由。

### Agent 必须输出

| 字段 | 类型 | 说明 |
|---|---|---|
| `match_id` / `kw_id` | text | 关联词 |
| `match_level` | text | `high` / `medium` / `low` |
| `demand_side` | text | **这个词的需求面是什么**，如「明确要长平角这个款型」 |
| `product_side` | text | **本品是什么**，如「本品即长平角」 |
| `basis` | text | 为什么判成这个档 |

### 约束

三段式必须齐：判断匹配度不能只给一个档位，要能看出「词要什么 / 产品是什么 /
所以匹配度是多少」。这是方案 J7 判断点。
⚠️ **循环依赖待拍**：这一项的值现在同时出现在 `KEYWORD` 证据里（当输入递给 Agent）和本节（当 Agent 的输出）。二选一，见 `06-广告Agent契约审计.md` §1.3。


---

## 5. B0d — 竞品压力分类（页面二板块3）

### Agent 必须输出

| 字段 | 类型 | 说明 |
|---|---|---|
| `pressure_type` | text | `price` / `rank` / `keyword_entry` 等六分类 |
| `pressure_label` | text | 中文，如「核心词入口被占」 |
| `detail` | text | 带数字的具体情况 |
| `is_verified` | int | 0/1，是否经竞品模块核验 |
| `observed_at` | date | |

### 约束

**竞品数据不能用来证明广告效率的因果**。压力只作为诊断的背景条件出现，
不能写成「因为竞品降价所以我们 ACoS 上升」。
⚠️ **循环依赖待拍**：这一项的值现在同时出现在 `COMPETITOR` 证据里（当输入递给 Agent）和本节（当 Agent 的输出）。二选一，见 `06-广告Agent契约审计.md` §1.3。


---

## 6. B0e — 结构问题识别（页面二板块5）

### Agent 必须输出

| 字段 | 类型 | 说明 |
|---|---|---|
| `issue_type` | text | `shared` 共享 / `unexplained` 无法归因 |
| `ad_object_id` | text | 可空（整体性问题时空） |
| `label` | text | 中文，如「共享给 75 个子 ASIN」 |
| `detail` | text | 后果，如「结果不能全部归到当前子 ASIN」 |

结构问题由 Agent 从推广关系（`bridge_ad_object_product`）与标签自己看出来。
**不读 `ext_structure_issue`**——那是本项目为搭页面烤的同一份结论。
「共享给 75 个子 ASIN」这个数是算术，工作台算给你；
「所以结果不能全归到本品」这个判断才是你的。

---

## 7. B1 — 应有广告任务（第 1 段）

### 界面呈现

板块4 每条任务一块：优先级徽章 + 任务名 + 五行说明 + 依据 chip。

### Agent 必须输出

| 字段 | 类型 | 取值 / 说明 |
|---|---|---|
| `task_id` | text | 内部 id，**不上屏** |
| `decision_id` / `goal_version` | text | 关联 |
| `task_type` | text | 枚举，见下 |
| `task_direction` | text | `ADJUST` `BUILD` `OBSERVE` `PREREQUISITE` `REQUEST_INFO` |
| `priority` | text | `P0` / `P1` / `P2` / `P3` |
| `target_scope` | text | 作用范围：子 ASIN、具体词、或「可比广告组」 |
| `constraints` | json[] | 中文短语数组 |
| `evaluation_direction` | text | 用什么结果判断达成 |
| `stop_condition` | text | 什么时候停 |
| `applies_from` / `applies_to` | date | 适用时间 |
| `rule_status` | text | `confirmed` / `unconfirmed` |
| `exact_budget` / `exact_bid` / `exact_placement_adjustment` | real | 见第 13 节约束 3 |
| `evidence_ids` | json[] | **只能引用 context.evidence 里的 id** |
| `inventory_constrained` | int | 0/1 |

`task_type` 现有 7 种：`VERIFY_INBOUND_BEFORE_SCALE`
`PROTECT_CORE_QUERY_VISIBILITY` `CONTROL_EFFICIENCY_DRIFT`
`CLARIFY_ATTRIBUTION_BOUNDARY` `ACCELERATE_SELL_THROUGH`
`CLEAR_AGED_INVENTORY` `COVER_MATCHED_QUERY_GAP`。

### 约束

方案 7.2 要求每项任务说明六件事，字段逐一对应：服务哪个目标（诊断段的
`impacted_goal`）/ 争取或保护什么流量（`target_scope`）/ 作用于哪些对象
（mapping 段）/ 优先级与适用时间（`priority` + `applies_from`）/ 成本库存风险
条件（`constraints` + `inventory_constrained`）/ 用什么判断达成
（`evaluation_direction` + `stop_condition`）。

**任务是从目标推出来的，不是从现有广告结构反推的**。现有结构没有对应对象时，
任务照样要出，由 mapping 段报「没有对象承接」。

---

## 8. B2 — 任务与现有结构对照（第 2 段）

### 界面呈现

板块6 一行一个对照：任务名 → 对象名 → 覆盖状态 → 归因限制 → 差距归类。

### Agent 必须输出

| 字段 | 类型 | 取值 / 说明 |
|---|---|---|
| `mapping_id` / `task_id` | text | `task_id` 必须 ⊂ 第 1 段 |
| `ad_object_id` | text | **可空 = 结构缺口** |
| `coverage_status` | text | `covered` / `mixed` / `missing` / `duplicate` |
| `attribution_limit` | text | `exclusive` / `shared` / `unattributed` |
| `target_fit` | text | 中文，如「该对象推的不是本品」 |
| `result_supports_purpose` | text | 中文，如「支撑」 |
| `gap_source` | text | `structure` 结构没建 / `evidence` 证据不足 / `none` |
| `basis_level` | text | `self_history` / `conditional` |
| `is_automatic_error` | int | 0/1 自动投放误配 |
| `note` | text | 中文，如「该对象同时推 75 个子 ASIN」 |
| `evidence_ids` | json[] | 同第 13 节约束 1 |

### 约束

`ad_object_id` 为空时页面必须显式说「当前没有广告对象承接这项任务」——
**空缺是结论，不是渲染失败**。`gap_source` 区分「结构没建」和「证据不足」，
两者的后续动作完全不同。

---

## 9. B3 — 广告诊断与优先级（第 3 段）

### 界面呈现

板块7 一行一条诊断：优先级 + 发生了什么 + 影响哪个目标 + 可靠度 + 还缺什么
+ 依据 chip。

### Agent 必须输出

| 字段 | 类型 | 取值 / 说明 |
|---|---|---|
| `diagnosis_id` / `task_id` | text | `task_id` 可空（非任务驱动的诊断） |
| `problem_type` | text | 枚举，见下 |
| `what_happened` | text | **中文一句话，说事实不说结论** |
| `impacted_goal` | text | 中文目标名，必须等于输入里运营设定的 `goal_label` |
| `priority` | text | `P0` / `P1` / `P2` |
| `confidence` | text | `high` / `medium` / `low` |
| `basis_type` | text | 见下方优先顺序 |
| `uncertainty` | text | 这条判断哪里不确定 |
| `missing_input` | text | 还缺什么输入 |
| `check_direction` | text | 接下来往哪个方向核 |
| `causal_claim` | int | **必须 0**，除非真有因果证据 |
| `evidence_ids` | json[] | 同第 13 节约束 1 |

`problem_type` 现有 6 种（覆盖表里定义了 10 类）：
`REQUIRED_TASK_MISSING` `MIXED_PURPOSE_GROUP` `GOAL_PURPOSE_MISMATCH`
`ATTRIBUTION_UNCLEAR` `KEYWORD_COVERAGE_GAP` `INVENTORY_COVERAGE_RISK`。

`basis_type` 的优先顺序（方案 4.8，高到低）：
`confirmed_rule` 客户已确认阈值 → `self_history` 自身历史 →
`peer` 可比对象 → `conditional` 条件判断。
**只能用当前拿得到的最高档，并把档位写进字段**，不能用低档冒充高档。

### 约束

**`causal_claim` 恒为 false 是硬约束**。两个指标同时变化不等于因果。
`uncertainty` 里要写清没控制住什么变量（现成写法：「未控制竞价、自然位、
促销和流量结构变化」）。

---

## 10. B3b — 诊断覆盖说明（随第 3 段）

十类问题**逐类**给命中与否，没命中要说为什么没命中——这是「算法可核验」的一半：
运营能看出 Agent 查过但没发现，而不是漏查了。

| 字段 | 类型 | 说明 |
|---|---|---|
| `problem_type` | text | 十类之一，**必须十类全给** |
| `hit` | int | 0/1 |
| `why_not` | text | `hit=0` 时必填，说明为什么没命中 |

现状每个对象命中 3–5 类，其余给「本次未命中」。

---

## 11. B4 — 广告调整方案（第 4 段）

### 界面呈现

板块8 一行一条建议：方向徽章 + 理由 + 前置条件 + 风险 + 不确定项 + 观察指标
+ 复盘窗口 + 依据 chip。

### Agent 必须输出

| 字段 | 类型 | 取值 / 说明 |
|---|---|---|
| `recommendation_id` / `diagnosis_id` | text | `diagnosis_id` 必须 ⊂ 第 3 段 |
| `product_goal_version` | text | 关联运营设定的目标版本，用于追溯 |
| `ad_purpose` / `ad_object_id` / `structure_gap_id` | text | 作用对象，可空 |
| `direction` | text | 12 种，见下 |
| `rationale` | text | 中文理由，引用具体数字 |
| `preconditions` | json[] | 中文数组，如 `["确认产品目标","核验库存"]` |
| `risks` | json[] | 中文数组，如 `["断货","流量流失"]` |
| `uncertainty` | text | |
| `observation_metrics` | json[] | 中文指标名数组 |
| `review_windows` | json[] | 如 `["D+3","D+7"]` |
| `d7_not_required` | int | 0/1 |
| `rule_status` | text | `confirmed` / `unconfirmed` |
| `exact_value` | text | 见第 13 节约束 3 |

`direction` 12 种：`KEEP` `OBSERVE` `ADJUST` `PAUSE` `RESUME` `SPLIT`
`MERGE` `BUILD` `TEST` `DEFER` `REQUEST_INFO` `PREREQUISITE`。

### 约束

- 一条诊断可以出 0 条建议（诊断成立但暂时不动也是结论）
- 有未满足的 `hard` 约束时不许给扩量方向，降为 `PREREQUISITE` / `DEFER`
- **建议不含精确数值**除非 `rule_status='confirmed'`，见第 13 节约束 3

---

## 12. 不给 Agent 读的（要则 §8 第 4 节）

**这一节比「读哪些表」重要。** 漏一张表只是少信息，Agent 会说判断不出；
漏一列就是答案泄漏，而且没有症状——它会写出看起来像真判断的话。

判据是要则 §1 的三问，第 3 问最容易漏：**它在我们的构造脚本里被写出来过吗。**

### 12.1 从预测派生的投影（`INVENTORY` 证据里）

| 字段 | 现值举例 | 它已经替你答了 |
|---|---|---|
| `coverage_days` | 41.79 | 还能卖几天 |
| `safety_breach_date` | 2026-08-31 | 什么时候破安全线 |
| `stress_stockout_date` | 2026-09-09 | 什么时候断货 |
| `base_stockout_date` | — | 同上 |
| `latest_order_date` | 2026-06-13 | 最晚什么时候下单 |
| `suggested_replenishment_qty` | 2531 | 该补多少 |
| `dynamic_safety_days` | 21 | 安全线定在哪 |
| `risk_status` | `replenishment_gap` | 结论本身，且是英文码值 |
| `confidence_score` | 0.8033 | 这个判断多可信 |

**本轮例外（要则 §7，王楠拍定）**：广告暂时把这些当作**库存 Agent 本次产出**使用，
不换源。用例外的前提是——它们必须被声明成上游产出，不是事实真值；
上游没跑过时下游降级说明，不能悄悄回落。

当前数据里它们标着 `nature=fact origin=direct`，这是**在宣称客户报表原值**，
比标 `constructed` 危险。这个标注要改（见审计文档 §4.2）。

同一条证据里这两个可以留作输入：`closing_fba_sellable` 5897（当前可售）、
`fba_inbound` 10228（在途）——它们是此刻的状态，运营后台查得到。

### 12.2 已成结论的（不在例外范围内，必须摘）

| 出处 | 字段 | 它已经替你答了 |
|---|---|---|
| `PRODUCT_STAGE` | `lifecycle` = 成熟期 | 生命周期在哪一段。中文、可直接上屏，念出来就答完了 |
| ~~`PRODUCT_GOAL`~~ | — | **已解除**：产品目标改为运营设定的输入，可以读。见第 2 节 |
| `KEYWORD` | `losing` = 2 | 哪些词在丢位置（与 B0c 循环）|
| `KEYWORD` | `absent_high_match` | 哪些高匹配词没覆盖（匹配度是判断）|
| `COMPETITOR` | `types` = `[price, rank, keyword_entry]` | 竞品压力属于哪几类（与 B0d 循环）|

### 12.3 整表禁读

| 表 | 为什么 |
|---|---|
| `ext_diagnosis` | 就是 B3 的答案 |
| `ext_recommendation` | 就是 B4 的答案 |
| `ext_required_ad_task` | 就是 B1 的答案 |
| `ext_task_ad_object` | 就是 B2 的答案 |
| `ext_diagnosis_coverage` | 就是 B3b 的答案 |
| `ext_structure_issue` | 就是 B0e 的答案 |
| `ext_keyword_match` | 就是 B0c 的答案 |
| `ext_competitor_pressure` | 就是 B0d 的答案 |
| ~~`ext_product_goal`~~ | **已解除**：改为运营设定的输入，可以读 |

这九张表的**列名与词表**要给你（那是形状与词表，要则 §9 要求钉）；
**行内容**不能给你当参照。样例文件里这些表的自由文本已替换成占位符。

### 12.4 通用问法

把这一列的值念出来，是不是就把你该说的话说完了。是 → 禁读。

---

## 13. 五条硬约束（机制，不是文案）

### 12.1 `evidence_ids` 只能引用 context.evidence 里的 id

这是「点依据能高亮页面元素」的物理保证。Agent 引用了 context 之外的 id，
运营点过去是空的，「算法可核验」当场变成假的。

`GET /api/ads/gate` 把这条做成门禁，悬空就 FAIL。前端找不到时 `console.warn`
报悬空，不静默失败。**建议服务端收到 Agent 响应后再校验一遍，不信任模型自觉。**

### 12.2 context 冻结并带 hash

`context_hash` 只哈希会影响判断的输入（决策版本、目标版本与状态、每条证据的
id / valid_as_of / status / payload、结构的目的与关键指标、数据包版本），
不含渲染顺序。`run` 请求带上打开页面时的 hash，回执给 `context_hash_matched`。
不匹配时页面提示「依据在你打开页面后变过」。

### 12.3 规则未确认时不许出精确值

`rule_status != 'confirmed'` 时 `exact_budget` / `exact_bid` /
`exact_placement_adjustment` / `exact_value` **必须是 null**，并置
`exact_values_withheld = true`。这是 schema 级约束，不靠 prompt 里写
「记得别编数」。现状 16 条任务、21 条建议的精确值字段**全部为空**。

### 12.4 `judgment_mode` 是一等字段

三态：`formal` 正式判断（客户已确认目标与阈值）/ `conditional` 条件性判断
（靠自身历史或可比对象）/ `unable` 暂时无法判断。前端按这个字段决定渲不渲染
数值，不靠文案暗示。

现状五个演示对象的 `goal_status` 全是 `pending_operator_confirmation`、
`rule_status` 全是 `unconfirmed`，所以全部落在 `conditional`。

### 12.5 `readiness` 在按钮之前算出来

不够跑就把「开始分析」置灰并写明缺哪一项，不能让用户点了等半天换回一句
「无法判断」。字段：`can_run` / `judgment_mode` / `goal_confirmed` /
`missing_evidence[]` / `stale_evidence[]` / `blockers[]` / `notes[]`。

---

## 14. 枚举一律不上屏

Agent 输出枚举，**前端负责翻译**，映射表在 `ads.js` 顶部。
`cn()` 缺映射时退回原值并 `console.warn`——这样新增枚举会被发现，
而不是静默把 `ACOS_UP_VS_SELF_HISTORY` 摆给客户看。

**你新增任何枚举值，同步告诉我加映射**，否则它会原样出现在界面上。

`task_id` / `diagnosis_id` / `ad_object_id` 这类内部 id 也不上屏：
引用任务用任务人话名，引用诊断用诊断人话名，引用对象用对象名。

另外注意一类隐蔽泄漏：**全大写单词（`EXACT` `BROAD` `PHRASE` `THEME`）
绕得过带下划线的枚举检测**。这次就在标签值里抓到过，已在读取边界映射。

---

## 15. 数据接口：Agent 读什么、写什么，前端怎么读

三段各自的边界必须写死，否则两侧会各自发明一套。

### 15.1 Agent 读什么（输入侧）

只读、不写。主数据包与产品包都是 `mode=ro`。

| 来源 | 表 | 给什么 |
|---|---|---|
| `advertising_demo.sqlite` | `dim_ad_object` `dim_campaign` | 广告结构与 Campaign 属性 |
| | `fact_ad_performance` | 月度权威口径的花费与归因销售额 |
| | `fact_ad_daily` | 日粒度序列（两种口径，见第 5 节不变量）|
| | `fact_ad_label_version` | 标签与来源、确认状态 |
| | `bridge_ad_object_product` | 广告对象与子 ASIN 的关系与角色 |
| | `fact_search_term_share` | 搜索词展示份额 |
| | `fact_budget` `fact_invalid_traffic` `fact_placement` `fact_ad_yoy` | 预算打满、无效流量、广告位、去年同期 |
| `ATTACH` 产品包 v0.3.0 | `prod.dim_product_child` | 产品身份（**不含 `lifecycle`**，见第 12 节）|
| | `prod.fact_child_inventory_decision` | 当前可售与在途（**只这两项**）|
| 扩展库 | `ext_decision_context` `ext_keyword_position` | 决策版本、关键词位置观测 |

**禁读清单见第 12 节**，那一节比这一节重要。

### 15.2 Agent 写什么（产出侧落库）

写到**独立可写 sidecar**，源包永不被写：

```
09-工作台/modules/ads/derived/ads_agent_state.sqlite
```

三张表，列名照现有实现（`modules/ads/agent_result.py`）：

**`fact_ads_agent_run`** 一次运行一行

| 列 | 说明 |
|---|---|
| `run_id` | `<子ASIN>-<基准日>-ads-agent-<时间戳>-<短哈希>` |
| `child_asin` `data_as_of` | 判断对象与数据截止 |
| `context_hash` `context_id` | 冻结的输入指纹，前端据此判过期 |
| `trigger` | 谁触发的 |
| `model_version` `method_version` `schema_version` `dataset_version` `rule_version` | 五个版本号，追溯用 |
| `status` | `completed` 才被前端采纳 |
| `mode` | 判断档位（正式判断 / 条件性判断 / 暂时无法判断）|
| `condition` | 数据状态词表内取值 |
| `evidence_index` | JSON，依据 id → 标题，供前端解析 chip |
| `diagnosis_coverage` | JSON，十类逐类命中与未命中说明 |
| `created_at` `completed_at` | 时间戳 |

**`fact_ads_agent_stage`** 一次运行四行：`run_id` `stage` `ord` `label`

**`fact_ads_agent_item`** 每条结论一行：`run_id` `stage` `item_ord` `item_id` `payload`

`payload` 是 JSON，字段照第 1–11 节各输出点的字段表。

**落库语义**（详见 `00-通用方法与规范/07-Agent运行与落库口径.md`）：
追加不覆盖，半份不上屏，同一 `context_hash` 可以有多次运行、前端取最新。

### 15.3 前端怎么读（适配逻辑）

`agent_result.latest(child_asin, current_hash, requested_hash)` 一个入口，
按这个顺序判：

| 顺序 | 条件 | 结果 |
|---|---|---|
| 1 | 请求带的 hash ≠ 当前 hash | `待确认`「页面依据已经变化，请刷新」 |
| 2 | sidecar 文件不存在 | `待确认`「该对象尚未运行」 |
| 3 | 没有 `status='completed'` 的 run | `待确认`「尚未完成真实运行」 |
| 4 | run 的 `context_hash` ≠ 当前 hash | `待确认`「结果已过期，需重新运行」 |
| 5 | 四段不齐 / 有空段 / 出现未知 stage | `待确认`「结果库不完整」 |
| 6 | 全通过 | `正常`，`source='Pi Agent'` |

**绝不回落到 `ext_*` 回放。** 这是要则 §8-5 的硬要求：页面展示的必须是 Agent
那一份，回落必须看得出来。这里比"看得出来"更严格——干脆不回落，
因为一旦允许回落，就会有人在演示时看到回放数据以为是 Agent 跑的。

### 15.4 枚举翻译的适配

Agent 输出码值，前端翻中文，映射表在 `compute.py` 顶部。

**缺映射时不上屏原值。** 真 Agent 会持续产出词表外的值（实测
deepseek-v4-flash 产出过 `MAINTAIN_CURRENT_SETUP` 与 `NO_ADJUSTMENT_NEEDED`），
靠人工追映射追不上，所以 `cn()` 的兜底按字段给中性中文
（`task_type` → 「未归类任务」、`problem_type` → 「未归类问题」…），
原值只进 `missing_labels()` 这条对账通道，由 `meta` 路由暴露。

**你新增枚举时同步告诉我加映射**——兜底是保险，不是常态。
界面上出现「未归类任务」就说明有映射没补上。

---

## 16. 接口现状（工作台版）

九个路由，全在 `/api/ads/` 下：

| 路由 | 用途 | 方法 |
|---|---|---|
| `meta` | 模块自描述 | GET |
| `candidates` | 选子 ASIN，带处境与证据完整度 | GET |
| `context` | Agent 输入，**永不触发 Agent** | GET `?child_asin=` |
| `run` | 四段串行输出 | GET（见下） |
| `decide` | 板块9 交接 | GET（见下） |
| `gate` | 契约门禁 | GET |
| `catalog` | 页面一八板块 | GET |
| `compare` | 页面一横向对比 | GET |
| `object` | 页面一详情抽屉 | GET `/<id>` |

**`run` 和 `decide` 现在是 GET**：外壳给模块的 `ctx.api` 只有 GET，
回放实现下本就是纯读所以能跑。真 Agent 落地时 `run` 需要 POST（要带
`context_hash` 和请求体），`decide` 更需要（要写运营决定）。
**这是要向外壳提的能力请求，不是你那边的事**，我会去提。

深链是路径段不是查询串：`/ads/ads-decision/<子ASIN>`。

分段揭示：前端拿到四段后按 420ms 依次显示，让依赖链看得见。
真 Agent 就绪后可以改成 NDJSON 流式真串行。

---

## 17. 当前回放数据的规模（只给量，不给结论）

`page2_decision_ext.sqlite` 14 表，五个演示对象：

| 表 | 行数 | 对应输出点 |
|---|---:|---|
| `ext_required_ad_task` | 16 | B1 |
| `ext_task_ad_object` | 16 | B2 |
| `ext_diagnosis` | 21 | B3 |
| `ext_diagnosis_coverage` | 50 | B3b（每对象十类全给，命中 3–5 类）|
| `ext_recommendation` | 21 | B4 |
| `ext_decision_evidence` | 50 | 每对象 10 条 |

**这些行的内容不是标准答案。** 它们是 `value_origin='constructed'` 的回放数据，
存在的唯一目的是让前端能渲染。你出的链不需要与它们一致，也不应该与它们一致。

### 你的输出必须满足的判据（照要则 §11）

| # | 判据 | 怎么验 |
|---|---|---|
| 1 | 同一个对象连跑两次，结论**允许**不同 | 跑两次比对，逐字节相同 = 复印机 |
| 2 | 换一个特征不同的对象，结论**必须**变 | 库存处境不同的两个对象，任务链不能同构 |
| 3 | 判断不出就给 null | 不许为了填满字段凑一个数或一句话 |
| 4 | 没问题也是结论 | 五个对象里有一个应当只出 P2、方向为保持 |
| 5 | 引用的数字能与确定性层核对上 | `numbers` 逐个比对同口径值 |
| 6 | 不引用「不给 Agent 读的」清单里的值 | 出现覆盖天数 / 断货日 / 建议补货量 = 泄漏 |

判据 4 的意思是：**不要为了显得有用而给每个对象都编出问题。**
哪个对象该是「没问题」由你判，不由这份文档指定。

---

## 18. 落地顺序建议

1. **先做 B1 任务段**——后三段都依赖它。（产品目标已改为输入，不用做）
3. B2/B3/B4 按依赖顺序
4. B3b 覆盖说明与 B1 同期做（同一次推理的副产物）
5. A1 广告目的标签建议可以并行，它跟页面二完全独立
6. B0b/B0c/B0d/B0e 四个附属点最后补，缺了页面能降级显示

我这边不用改的东西：三个接口的形状、`context` 的组装、`context_hash` 的算法、
门禁、前端全部代码。你保证第 12 节那五条即可，其中 12.1 和 12.3 我会在服务端
收到响应后再校验一遍。
