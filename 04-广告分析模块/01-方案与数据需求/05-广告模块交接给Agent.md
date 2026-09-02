# 广告模块交接给 Agent 侧 v1.0

2026-08-31 · 你要接的这两个页面长什么样、读了什么数据、要你回什么

配套三份材料，一起看：

| 材料 | 位置 | 作用 |
|---|---|---|
| 本文 | `04-广告分析模块/01-方案与数据需求/05-广告模块交接给Agent.md` | 页面结构 + 功能 + 读表清单 |
| 字段级契约 | 同目录 `04-广告模块Agent输出点清单.md` | 11 个输出点逐个的字段表与约束 |
| 真实 JSON 样例 | 同目录 `agent-samples/` | 从跑着的服务直接取的响应，不是手写的 |

服务：`http://127.0.0.1:18820`，模块前缀 `/api/ads/`。
基准日 2026-08-03（所有数字都是这个日期口径，不是今天）。

---

## 1. 两个页面各自回答什么问题

**页面一「广告分类与数据查看」** `/ads/ads-catalog`
只回答「数字长什么样」。把广告组或投放对象横向打散、贴标签、按标签筛、比数据、
标数值异常。

**这一页有红线**：不读产品目标、库存、关键词、竞品结论，不出诊断与建议。
禁的是动作措辞（建议调整 / 提高竞价 / 降低预算 / 否词 / 暂停）。
唯一的 Agent 介入点是「AI 建议了这个广告目的标签」，那是方案 3.4 的强制项。

**页面二「单一子 ASIN 广告决策」** `/ads/ads-decision/<子ASIN>`
一次只看一个子 ASIN，把「产品目标 → 应有广告任务 → 现有结构能不能承接 →
诊断 → 建议 → 运营拍板」这条判断链摊开，每一步都能点回它依据的那条事实。

深链是路径段不是查询串：`/ads/ads-decision/B0B3LWGP36`。

---

## 2. 页面一：八个板块与各自的数据来源

| 板块 | 界面上是什么 | 读哪些表 | 有 Agent 吗 |
|---|---|---|---|
| 1 当前范围与数据状态 | 顶部条：80 Campaign / 54 广告组 / 855 投放对象 / 31 份客户报表 + 状态 chip + 归因周期 + 范围口径 ⓘ | `dim_ad_object` `dim_campaign` `source_file` `fact_ad_daily` `fact_ad_performance` | 无 |
| 2 广告对象标签体系 | 侧栏五类标签分组，每个取值带来源与确认状态 | `fact_ad_label_version` join `dim_ad_object` | **A1 广告目的建议** |
| 3 标签组合与对象筛选 | 侧栏：搜索框 + 粒度锁 + 每族勾选行（带候选数）+ 已选条件 chip | 同上，分面计数在内存里算 | 无 |
| 4 筛选结果数据概览 | hero 花费 44px + 按归因周期分列的 ACoS/ROAS + 归因分块 + 类目基准阶梯 | `fact_ad_performance` `fact_category_benchmark` | 无 |
| 5 数值异常对象 | 四类计数 chip + 规则比例条（8 条）+ Campaign 级单列（13 条） | `dim_anomaly_rule` `fact_budget` `fact_invalid_traffic` | 无 |
| 6 横向对比 | 勾选 ≥2 行才出现，按 (粒度, 归因天数) 拆组，各组独立中位数 | 内存计算 | 无 |
| 7 广告对象数据清单 | 15 列定宽表，sticky 表头 | `dim_ad_object` `fact_ad_performance` `fact_ad_daily` | 无 |
| 8 详情与标签历史 | 抽屉八面板：本期数字 / 相对自身历史 / 预算与错失 / 无效流量 / 去年同期 / 广告位 / 标签与生效历史 / 数据状态 | 上面全部 + `fact_ad_yoy` `fact_placement` | **A1 的依据要显示在这里** |

### 筛选语义（你输出标签建议时要知道）

方案 3.5 的语义是**跨标签族 AND、族内 OR**：
「某个子 ASIN 下的全部 SP 广告组」是产品关系 AND 广告属性，
「投放某个关键词或某类关键词的全部 Target」是投放对象族内 OR。

两个粒度的分类轴不是同一套：

| 粒度 | 对象数 | 分类轴 |
|---|---:|---|
| 广告组 | 54 | 产品关系 22 / 广告目的 8 / 广告属性 15 / 投放对象 9 / 运营自定义 6 / Campaign 52 |
| 投放对象 | 855 | 投放对象 13 / 匹配方式 6 / 广告属性 16 / 产品关系 22 / 广告目的 7 / 运营自定义 6 / Campaign 46 |

**广告组只有 54 个不是数据漏了**：报表里的广告组名与 (Campaign,组) 组合全部落在
`dim_ad_object` 里，差集为 0。少是因为 80 个 Campaign 里有 28 个在报表里既没有
广告组也没有投放对象。结构按类型：广告组 SP 40 / SD 9 / SB 5，
投放对象 SP 679 / SB 167 / SD 9——SB 是少数几个组堆大量关键词。

---

## 3. 页面二：九个板块与四段揭示

进页面立即渲染板块 1/2/3/5（这一步**永不触发 Agent**），
板块 4/6/7/8 是压低的空壳 + 一个「开始分析」按钮。

⚠️ **下表的「数据来源」是前端读哪张表，不是 Agent 的输入清单。**
带 ⛔ 的表是 Agent 自己该产出的东西，本项目为了让前端能渲染先烤了一份，
**不能当输入递给 Agent**。逐列判定见 `06-广告Agent契约审计.md`，
禁读清单见输出点清单第 12 节。

| 板块 | 界面上是什么 | 前端读哪些表 | Agent 点 |
|---|---|---|---|
| 1 决策上下文 | 子 ASIN / 父体 / 观察窗口 / 数据截止 / 判断档位 | `ext_decision_context` | 判断档位由 B0 决定 |
| 2 产品目标与约束 | 目标名 + 已确认徽章 + 硬性约束 / 观察项两组 | `ext_product_goal`（**运营设定的输入，可读**）⛔`ext_goal_constraint` | **B0b**（目标本身不判）|
| 3 判断依据 | 10 条证据卡，每条带性质、观察时点、局限、可跳转模块；含关键词位置表与竞品压力 | `ext_decision_evidence`（**含 14 个禁读字段**）`ext_keyword_position` ⛔`ext_keyword_match` ⛔`ext_competitor_pressure` | **B0c / B0d** |
| 4 应有广告任务 | 优先级徽章 + 任务名 + 五行说明 + 依据 chip | ⛔`ext_required_ad_task` | **B1（第 1 段）** |
| 5 现有广告结构与目的 | 该子 ASIN 名下真实广告对象树 + 结构问题 | `dim_ad_object` `bridge_ad_object_product` `fact_ad_label_version` ⛔`ext_structure_issue` | **B0e** |
| 6 目标—结构—表现对照 | 任务 → 对象 → 覆盖状态 → 归因限制 → 差距归类 | ⛔`ext_task_ad_object` | **B2（第 2 段）** |
| 7 广告诊断与优先级 | 一行一条诊断 + 十类覆盖说明 | ⛔`ext_diagnosis` ⛔`ext_diagnosis_coverage` | **B3 / B3b（第 3 段）** |
| 8 广告调整方案 | 方向徽章 + 理由 + 前置条件 + 风险 + 观察指标 + 复盘窗口 | ⛔`ext_recommendation` | **B4（第 4 段）** |
| 9 运营决定与交接 | 四种决定按钮，接受/修改出交接块，拒绝/暂缓不出 | 内存计算，Demo 不落库 | 无（接收 D+3/D+7 回流） |

八张 ⛔ 表的**列名与词表**要给你（形状与词表该钉），**行内容**不是参照答案。

`ext_decision_evidence` 是混的：十类证据里六类是干净输入（历史广告表现、
搜索词份额、归属缺口、销量趋势、采购单与促销排期、产品主数据），
另有 14 个字段是投影与结论——见输出点清单第 12 节。

四段现在是前端拿到全部后按 420ms 依次显示，让依赖链看得见。
真 Agent 就绪后可以改成 NDJSON 流式真串行。

---

## 4. 数据是怎么建的

### 主数据包 `v0.2.0/advertising_demo.sqlite`（35 表）

31 份客户报表全接。从 v0.1.0 到 v0.2.0 的变化：

| | v0.1.0 | v0.2.0 |
|---|---:|---:|
| 源文件 | 8 | **31** |
| 表 | 22 | **35** |
| 广告对象 | 733 | **989**（+Campaign 层 80）|
| 月度事实 | 739 | **984** |
| 有日线的对象 | **3** | **482** |
| 标签 | 897 | **9279** |
| 归因关系 | 554 | **5872**（五角色全齐）|
| 异常规则 | 2 | **10**（四类全齐）|

v0.1.0 一字节未动，733 个 `ad_object_id` 全部复用，所以页面二的决策链没断。

### 决策扩展库 `page2-ext/page2_decision_ext.sqlite`（14 表）

这是你要替换的部分——现在是回放，将来是你的实时输出。

| 表 | 行数 | 对应输出点 |
|---|---:|---|
| `ext_product_goal` | 5 | 输入（运营设定的目标）|
| `ext_goal_constraint` | 19 | B0b |
| `ext_keyword_position` | 14 | 事实为主，`position_trend`/`limited_by` 是判断 |
| `ext_keyword_match` | 14 | B0c |
| `ext_competitor_pressure` | 15 | B0d |
| `ext_structure_issue` | 13 | B0e |
| `ext_decision_context` | 5 | 决策版本 |
| `ext_decision_evidence` | 50 | 每对象 10 条 |
| `ext_required_ad_task` | 16 | B1 |
| `ext_task_ad_object` | 16 | B2 |
| `ext_diagnosis` | 21 | B3 |
| `ext_diagnosis_coverage` | 50 | B3b（十类逐类，命中 3–5 类）|
| `ext_recommendation` | 21 | B4 |
| `ext_meta` | 5 | 版本与演示对象清单 |

### 跨模块读取

产品身份和库存事实**不重建**，`ATTACH` 产品包 v0.3.0 只读：
`prod.dim_product_child`（`product_name` `style_name` `colorway` `size`
`category` `category_rank` `rating` `operator` `product_lifecycle`）、
`prod.fact_child_inventory_decision`。

跨模块 join 只走 342 子体脊椎。**演示对象必须在脊椎内**——早期用的
B088WF1PRW 不在产品包里，两包交集只有 188，所以换成了现在这五个。

---

## 5. 三条不能破的数据不变量

你输出的东西如果违反这三条，页面会算出不存在的数字。

**5.1 两套数字物理隔离，永不同行相加**

- 月度权威 `metric_basis='report_month_total'`（984 行，花费完整但无时间维度）
- 日粒度原值 `search_term_exact_day_sum`（只是搜索词可见部分）
- 日粒度放大值 `daily_scaled_to_month`（按对象按指标恒定系数放大）

环比变化率在原值和放大值上完全相同（系数做比值时约掉），只有水平值受口径影响。

**5.2 花费可加，归因销售额不可加**

花费是真实支出，与归因窗无关。但 SP 是 7 天归因、SB/SD 是 14 天归因，
把销售额加起来做分母会算出一个不存在的合计 ACoS。
所以 ACoS 和 ROAS 一律按归因周期分开给。

**5.3 Campaign 级规则按 Campaign 计一次**

预算打满、无效流量是 `applies_to='CAMPAIGN'` 的规则，曾被 Target 数量放大成
202 条。你出诊断时同理：Campaign 级的问题不要按 Target 条数重复报。

---

## 6. 九个路由与真实响应样例

| 路由 | 用途 | 样例文件 |
|---|---|---|
| `GET /api/ads/meta` | 模块自描述（页、路由、参数） | — |
| `GET /api/ads/candidates` | 选子 ASIN，带处境与证据完整度 | `candidates.json` |
| `GET /api/ads/context?child_asin=` | **Agent 的输入**，永不触发 Agent | `context.json` |
| `GET /api/ads/run?child_asin=` | **Agent 的输出四段** | `run.json` |
| `GET /api/ads/decide?child_asin=&recommendation_id=&decision=` | 板块9 交接 | `decide-accept.json` `decide-reject.json` `decide-bad-param.json` |
| `GET /api/ads/gate` | 契约门禁：依据 id 零悬空 | `gate.json` |
| `GET /api/ads/catalog` | 页面一八板块 | `catalog-adgroup.json` `catalog-target-filtered.json` |
| `GET /api/ads/compare` | 页面一横向对比 | — |
| `GET /api/ads/object/<id>` | 页面一详情抽屉 | `object.json` |

`decision` 收 `accept` / `modify` / `reject` / `defer`，也接受中文写法。

**`run` 和 `decide` 现在是 GET**：外壳给模块的前端接口只有 GET，回放实现下纯读
所以能跑。真 Agent 落地时 `run` 要 POST（带 `context_hash` 和请求体），
`decide` 更需要（要写运营决定）。这是我要向外壳提的能力请求，不占你的工。

样例说明：长数组只留前 3 项并在原位注明原始长度，**字段一个没删**。
`catalog-target-filtered.json` 原始 268887 字符，裁到 14015。

---

## 7. 你输出的东西怎么上屏

**枚举一律不上屏。** 你输出枚举，前端负责翻译，映射表在 `ads.js` 顶部。
缺映射时退回原值并 `console.warn`——这样新增枚举会被发现，
而不是静默把 `ACOS_UP_VS_SELF_HISTORY` 摆给客户看。

**你新增任何枚举值，同步告诉我加映射。**

有一类隐蔽泄漏值得你也留意：**全大写单词（`EXACT` `BROAD` `PHRASE` `THEME`）
绕得过带下划线的枚举检测**。这次就在标签值里抓到过——库里同时存着
`EXACT 363` 和中文的 `精准匹配 92`，同一件事两种写法并存。

**内部 id 不上屏**：`task_id` / `diagnosis_id` / `ad_object_id` 都要经过
人话名映射。引用任务用任务名，引用诊断用诊断名，引用对象用对象名。

**界面文案分三层**：数字和数字的名字直接显示；栏目、算法、口径的解释收进 ⓘ
点开；「我为什么这么设计」的防御型自述一律不写进界面。
所以你不用输出免责表述，输出了我也不会渲染。

---

## 8. 换个对象结论要真的变

这是判断链和公式套壳的分界线。判据（照要则 §11，一句话就能判）：

| # | 判据 | 怎么验 |
|---|---|---|
| 1 | 同一个对象连跑两次，结论**允许**不同 | 跑两次逐字节相同 = 复印机 |
| 2 | 换一个库存处境不同的对象，任务链**必须**变 | 两个对象的任务不能同构 |
| 3 | 有对象应当「没问题」 | 只出 P2、方向保持，也是结论 |
| 4 | 判断不出给 null | 不许凑数凑话 |

判据 3 的意思是：**不要为了显得有用而给每个对象都编出问题。**
哪个对象是「没问题」由你判，本文档不指定。

现有回放数据里五个对象覆盖了四种库存处境（需要补货 / 超量备货 / 高库龄风险 /
健康），趋势有涨有跌。**具体哪个对象是哪种处境、该出什么任务，不在这份文档里给**——
那是答案，给了你就只能对齐。你从输入侧的销量趋势与库存状态自己判。

### 输入侧的来源分档

干净输入（历史事实与人排的计划）：历史广告花费与订单、搜索词份额、归属缺口、
销量六窗口、采购单数量与 ETA、促销排期、产品主数据、当前可售与在途。

**不给你读的**（投影与结论）：见输出点清单第 12 节，共 14 个字段 + 9 张整表。
其中库存投影那 9 个字段按要则 §7 走本轮例外——当作**上游库存 Agent 本次产出**
使用，不是事实真值；上游没跑过时必须降级说明，不能悄悄回落到预烤值。

你输出时同样要标 `value_origin`（`direct` / `derived` / `constructed`），
**这个字段只内部对账，不上屏。**

---

## 9. 现在就能拿的东西

```
04-广告分析模块/01-方案与数据需求/
├─ 03-页面二Agent接口契约.md          形态与五条硬约束（18813 时期，路由已变）
├─ 04-广告模块Agent输出点清单.md       11 个输出点的字段级契约 ← 主要看这份
├─ 05-广告模块交接给Agent.md          本文
└─ agent-samples/                    真实 JSON 响应
   ├─ README.md
   ├─ candidates.json    context.json    run.json
   ├─ decide-accept.json decide-reject.json decide-bad-param.json
   ├─ gate.json          object.json
   └─ catalog-adgroup.json  catalog-target-filtered.json
```

落地顺序建议见输出点清单第 16 节：先 B0（阻塞项）→ B1（后三段都依赖）→
B2/B3/B4 按依赖走 → A1 完全并行 → 四个附属点最后补。

我这边不用改：三个接口的形状、`context` 的组装、`context_hash` 的算法、门禁、
前端全部代码。你保证输出点清单第 12 节那五条即可，
其中「依据 id 不许悬空」和「规则未确认不许出精确值」我会在服务端再校验一遍。
