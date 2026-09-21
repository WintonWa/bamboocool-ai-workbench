# Agent 读写矩阵

审计日期：2026-09-02  
口径：这里记录的是代码与数据库的当前事实，以及按《01-统一数据边界总则》收敛后的目标边界。`允许` 只表示语义上可进入输入桥，不表示可以绕过 run、时点、完整性和 context 校验。

## 1. 需求预测 `demand-forecast`

- 判断对象：单个子 ASIN 在当前事实与已承诺计划下的未来 90 日真实需求。
- 触发范围：`weekly`、`manual`、`priority`；当前正式 HTTP 入口为 `/api/agent/demand-forecast`。
- 当前实现与目标差距：正式桥和 sidecar 已接通，但页面仍有基础包预测 fallback，旧 `/api/agent/run` 仍可读预烤答案。

| 检查项 | 当前事实与目标边界 |
|---|---|
| 1. 允许输入 | 子 ASIN 身份与关系；已发生的逐日销量、库存可售状态和价格；可观察的当前库存与在途；运营已承诺的活动、采购和事件日历；中立的历史聚合。当前 `loadDemandForecastFacts()` 已采用显式 allow-list，方向正确。 |
| 2. 禁止输入 | `fact_child_forecast_daily`、`feature_child_demand_daily`、库存投影、覆盖天数、生命周期判断、变化原因、置信度、预计效应、潜在/损失需求等预烤预测或同义答案；fixture expected answer；本 Agent 的 prior run，除非任务明确要求可比回顾。 |
| 3. 允许上游 Agent | 当前无必需上游 Agent。若以后读取异常识别结果，必须点名依赖并满足 completed、run_id、data_as_of/context、完整性、显式降级六项。 |
| 4. 禁止上游 Agent | 盘点结论、库存总体分析、广告、关键词和竞品 Agent 的判断，不得因页面上已经存在就自动并入预测输入。 |
| 5. 自己的输出 | 未来 90 天逐日需求预测及区间；影响调整项及依据；判断小结、确定程度与原因；run 元数据和 prior/comparison 引用。写入 `forecast_agent.sqlite` 的 run、daily、adjustment、comparison 四表。 |
| 6. 规则校验 | 校验 90 日完整性、日期连续性、区间关系、数值范围、证据引用和事实数字一致；不得校验为基础包的预制预测。库存余额、覆盖、断货与补货仍由确定性层计算。 |
| 7. 展示区域 | completed 且 context 匹配的预测进入 Agent 区；原始历史、库存与计划进入事实区；确定性库存测算进入规则/事实派生区并标明身份。 |
| 8. 无结果时 | Agent 区显示“尚未分析”或失败/过期状态；事实区继续可用。不得由页面 `forecast_daily()` 回落基础包 `fact_child_forecast_daily` 冒充当前 Agent 结果。 |
| 9. 运行状态 | 当前 sidecar 有 10 个 completed、10 个 failed；每个 completed run 均有 90 条 daily。正式读取只认完整 completed；failed 子表不读，stale 明示并引导重跑。 |
| 10. fixture 边界 | v0.3 包中的预测、特征需求和预期解释可以保留为 fixture/回归黄金样本，但要移出正式 observation read path，并以 `demo_seed` 或 fixture 身份隔离。旧 `/api/agent/run` 直接读预烤预测的兼容链不得作为正式入口。 |

证据：`06-Pi-Agent交互Demo/src/demand-forecast.ts:32-169`、`06-Pi-Agent交互Demo/src/demand-forecast-agent.ts`、`06-Pi-Agent交互Demo/src/server.ts:402-406`、`09-工作台/modules/inventory/forecast.py`、`09-工作台/modules/inventory/derived/forecast_agent.sqlite`。

## 2. 盘点结论 `stock-verdict`

- 判断对象：单个子 ASIN 当下是否要行动、行动方向及五条结论的轻重顺序。
- 触发范围：`weekly`、`manual`；实际服务以指定子 ASIN 和预测 run 为上下文运行。
- 当前实现与目标差距：真模型与原子落库已存在，但输入携带 `expected_state`、校验器锁定同一答案，run 表也缺正式状态语义。

| 检查项 | 当前事实与目标边界 |
|---|---|
| 1. 允许输入 | 对象身份；当前库存、在途 ETA；明确指定的 completed 需求预测 run；工作台可复算的覆盖、断货日、到货时间轴、缺口天数等确定性数字；证据指针。 |
| 2. 禁止输入 | `expected_state`、预制五类风险、预制“该不该动”答案、预制排序和措辞；任何要求输出与 deterministic verdict 逐项相等的 expected answer。当前事实桥传入五个 `expected_state`，属于关键越界。 |
| 3. 允许上游 Agent | 需求预测仅可通过 completed `input_forecast_run_id` 接入，并核对当前对象、时点、90 日完整性和 context。 |
| 4. 禁止上游 Agent | 失败、seed、partial、旧 context 的需求预测；库存总体分析的下游汇总；其他模块结论。 |
| 5. 自己的输出 | 五条结论、每条 state/文案/排序/依据指针、run 时间与输入预测 run 引用，写入 `verdict_agent.sqlite` 的 run/item 表。 |
| 6. 规则校验 | 可以校验 state 在词表中、五条齐全、证据引用存在、引用数字与确定性层一致、结论不自相矛盾；不得要求 state 与 `expected_state` 相同。若 state 本质是确定性分类，则应移到 rule result，Agent 只负责解释——此归属待拍板。 |
| 7. 展示区域 | completed Agent 五条进入 Agent 区；覆盖、断货日和 ETA 进入事实/规则区；两者不能摊平为同一无来源卡片。 |
| 8. 无结果时 | 显示尚未分析；保留事实与规则数字。不得用 deterministic verdict 文案回填 Agent 五条。 |
| 9. 运行状态 | sidecar 有 3 个 run，其中 2 个真实模型、1 个 seed；schema 没有 `status/completed_at`，现状不能严格表达 completed。目标须补运行状态与完整性门禁，并默认排除 seed。 |
| 10. fixture 边界 | seed run、expected state 和零风险对照样本只供测试；不得参与最新正式 run 选择，不得进入 Agent payload。 |

证据：`06-Pi-Agent交互Demo/scripts/inventory_verdict_facts.py:32-68`、`src/inventory-verdict.ts:118-125`、`09-工作台/modules/inventory/derived/verdict_agent.sqlite`。

## 3. 库存总体分析 `stock-group-review`

- 判断对象：运营选定分组或全盘库存的总体状态、重点对象和子结论冲突。
- 触发范围：当前未定义；目标应在所需逐对象上游 run 完整后触发，而不是自造一个定时词。
- 当前实现与目标差距：只有 registry 登记，没有契约、代码、sidecar、触发和展示读取。

| 检查项 | 当前事实与目标边界 |
|---|---|
| 1. 允许输入 | 分组对象关系；负责人、款号、组合、生命周期、店铺、父 ASIN 等已存在筛选维度；分组确定性计数/合计/分布；完整的逐对象上游 Agent run 引用。 |
| 2. 禁止输入 | 基础包预制重点对象、预制总体结论、无 run 归属的五类风险文案；把规则排序结果伪装成 Agent 综合判断。 |
| 3. 允许上游 Agent | 需求预测与盘点结论；每个对象都须 completed、同一 data_as_of/context、结果完整。缺一个对象时应披露覆盖范围，不能静默补 fixture。 |
| 4. 禁止上游 Agent | seed/failed/partial/stale 且未明示的子 run；广告、关键词、竞品结论，除非未来契约明确扩为跨模块任务。 |
| 5. 自己的输出 | 分组总体结论；重点对象清单、入选理由与所引用子 run；冲突说明。当前尚无代码、契约和结果表。 |
| 6. 规则校验 | 校验分组成员、覆盖率、引用 run 完整性、重点对象属于当前分组；计数/合计/严重度分布由工作台复算。若只做 Top-N 排序和模板摘要，不应立为 Agent。 |
| 7. 展示区域 | completed 综合判断进入库存异常总览和库存全览的 Agent 区；分组统计留在事实/规则区。 |
| 8. 无结果时 | 两个页面保留分组统计，Agent 区显示未分析；不从逐对象文案拼一个伪总体结论。 |
| 9. 运行状态 | 当前仅登记为“待声明”，无触发、无 sidecar、无正式状态语义。目标触发应是依赖就绪后的编排事件，并记录输入子 run 集合。 |
| 10. fixture 边界 | 可用固定分组与冲突案例验证汇总契约；expected 排序和最终总结只能留在测试 fixture。 |

证据：`09-工作台/modules/agentcfg/registry_seed.py:96-151`。

## 4. 关键词机会与风险 `keyword-opportunity`

- 判断对象：市场关键词，以及关键词 × 子 ASIN 层的机会、风险、覆盖变化和验证去向。
- 触发范围：registry 登记为 `weekly`；正式 Runner 强制 `scope='all'`，Smoke 则仅把前 20 个市场候选送入模型。
- 当前实现与目标差距：正式代码形状存在但正式库不存在；Smoke 全失败；页面靠五张基础包预烤表继续给答案。

| 检查项 | 当前事实与目标边界 |
|---|---|
| 1. 允许输入 | 关键词实体与自有核心词关系；历史搜索量、自然位、广告位和同期可观察变化；明确来源的当前外部快照；中立变化量、连续观测数与证据目录。 |
| 2. 禁止输入 | 五张基础判断表 `fact_keyword_market_opportunity`、`fact_keyword_coverage_event`、`fact_keyword_child_goal_check`、`fact_keyword_action_handoff`、`fact_keyword_agent_decision`；以及 `fact_keyword_child_absorb` 中断货日、动态安全量、补货量、损失量、承接状态和置信度；预制 lifecycle/优先级/机会/风险/去向。 |
| 3. 允许上游 Agent | 若机会判断确实依赖库存，应读取点名的 completed 库存 run，并保留 run_id；当前契约没有合法化这种依赖。竞品验证可以作为后续 handoff，而不是未经声明的输入答案。 |
| 4. 禁止上游 Agent | 基础包里的库存判断同义字段；广告/竞品/预测的无 run 结论；当前 Agent 自己上一次输出，除非明确做“较上次”。 |
| 5. 自己的输出 | 市场候选机会/风险、覆盖事件、优先级与证据完整度、下一验证去向、运行及 handoff 记录。正式 Runner 计划替换上述五张表；Smoke 只写 loop 运行态。 |
| 6. 规则校验 | 校验来源事件存在、词 ID 与位置序列一致、枚举/引用/去向闭环；确定性分数可作为可解释特征，但不能与预制结论做同一性校验。 |
| 7. 展示区域 | completed 正式 run 进入关键词 Agent 区；搜索量与位置曲线进入事实区；确定性变化量进入特征区。 |
| 8. 无结果时 | 当前六个 GET 会回落基础包五表；目标必须改为 Agent 区“尚未分析”，事实曲线照常显示，不允许 fallback。 |
| 9. 运行状态 | 正式 current/state 路径存在于代码但文件不存在；Smoke loop state 有 3 个 failed，均为 `MODEL_TIMEOUT`。二者不是同一运行账本，不得互相代表完成。 |
| 10. fixture 边界 | 基础包五张输出表可保留为 Demo expected fixture，但必须移出正式 observation DB 或被正式查询硬隔离；Smoke 输出只用于链路测试，不能发布为正式判断。 |

证据：`07-关键词分析模块/02-数据构建/export_agent_package.py:46-50,543-554`、`06-Pi-Agent交互Demo/src/keyword-agent.ts`、`06-Pi-Agent交互Demo/src/keyword-loop-task.ts:294-323`、`09-工作台/modules/keyword/agent_result.py`。

## 5. 子体关键词布局 `keyword-child-goal`

- 判断对象：关键词 × 子 ASIN × 当前推广目标下的布局充分性，以及该推、守、放弃的词。
- 触发范围：当前未定义；目标应在目标版本确认且上游词级 completed run 就绪后按子 ASIN 或目标版本触发。
- 当前实现与目标差距：registry 已登记但没有独立契约、runner 或 sidecar，相关结果混在正式关键词五表设计中。

| 检查项 | 当前事实与目标边界 |
|---|---|
| 1. 允许输入 | 子体—关键词关系与位置/表现；运营已确认的推广目标及历史版本；completed 的词级机会 run；中立覆盖数与位置分布。 |
| 2. 禁止输入 | `dim_keyword_child_goal.product_lifecycle` 若它是预测判断；`fact_keyword_child_absorb.absorb_state` 及断货/补货/损失/置信度；基础包 `fact_keyword_child_goal_check` 的预制一致性结论、该推/该守/该放弃答案。`library_status/operator_role` 仅在确认属于运营输入后才允许。 |
| 3. 允许上游 Agent | `keyword-opportunity` 的 completed 正式 run；若目标依赖库存承接，还须显式引用 completed 库存 run，而不是基础包派生字段。 |
| 4. 禁止上游 Agent | Smoke 候选；同 scope 的 partial/failed 关键词 run；无 run_id 的库存/竞品判断。 |
| 5. 自己的输出 | 子体词布局结论；该推、该守、该放弃的词及理由；目标与现有布局的不一致；结果须独立于词级机会结果落库。当前无独立实现。 |
| 6. 规则校验 | 校验目标版本存在、词属于子体、上游优先级引用有效；覆盖数和位置分布由工作台复算。不得用 `fact_keyword_child_goal_check` 校验 Agent 答案。 |
| 7. 展示区域 | completed 布局结论进入“子 ASIN 关键词盘点”的 Agent 区；目标进入计划/人设区；表现进入事实区。 |
| 8. 无结果时 | 保留目标和词表现，Agent 区显示未分析；不得回落预烤 goal check。 |
| 9. 运行状态 | 登记为“待声明”，无独立触发、sidecar 或正式 run；当前正式关键词链把相关结果混在同一批五表中。目标需明确独立 Agent 还是同 Agent 第二阶段。 |
| 10. fixture 边界 | 30 个重点子体与预制 goal check 可作为覆盖测试；预制布局结论不得进入正式页面或正式输入。 |

证据：`09-工作台/modules/agentcfg/registry_seed.py:175-219`、`06-Pi-Agent交互Demo/scripts/keyword_agent_facts.py:167-226`。

## 6. 竞品威胁判定 `competitor-threat`

- 判断对象：单个产品族下竞品价格、排名、关键词位置等变化是否构成真实威胁及证据充分度。
- 触发范围：registry 登记为 `weekly`；V2 实际按产品族创建任务，可产生 completed、failed、skipped。
- 当前实现与目标差距：V2 边界已接近目标，但 registry 仍写“未拍定”，基础观察库仍混放 V1 判断表，V1 sidecar 仍被运行档案读取。

| 检查项 | 当前事实与目标边界 |
|---|---|
| 1. 允许输入 | 竞品与自有对象关系；可观察的价格、排名、关键词位置和页面变化历史；产品族归属；中立的变化量、持续天数与 freshness；清洗后的证据目录。 |
| 2. 禁止输入 | 基础观察库的 10 张 `fact_competitor_analysis_*` 判断表和 `fact_competitor_evidence_handoff`；场景 expected answer；V1 sidecar 输出；`value_origin` 等可能暗示标准答案的内部字段。V2 模型输入目前已显式清除这些内容。 |
| 3. 允许上游 Agent | 默认无必需上游。prior V2 completed run 只可用于明确的“较上次”任务，并通过 `prev_run_id` 接入。 |
| 4. 禁止上游 Agent | V1 run、failed/skipped/writing V2 run、不同产品族或不可比较 context 的 prior；其他模块结论。 |
| 5. 自己的输出 | 证据档位、变化、时间线、并发关系、关注理由、影响、待补问题、与上次差异、报告和 handoff，原子写入 V2 sidecar 11 张表。 |
| 6. 规则校验 | 校验所有证据/主体引用、V2 schema、context hash、输出完整性与 completed 后可见；确定性变化幅度可复算。威胁档位是 Agent 还是阈值规则仍属产品拍板，但不能两套结论混读。 |
| 7. 展示区域 | 仅当前 context 的 completed V2 run 进入 Agent 区；观察序列与差值进入事实/特征区；V1/基础包判断不渲染。 |
| 8. 无结果时 | 事实区仍展示价格、排名与关键词位置；Agent 区尚未分析，不回落基础包 11 张旧判断表。 |
| 9. 运行状态 | V2 sidecar 当前 8 completed、9 failed、8 skipped；页面查询显式 JOIN `status='completed'` 并校验 context，方向最接近目标。首次 run 的 prior 为空；现有 diff 未发现悬空 prev。 |
| 10. fixture 边界 | 基础包旧 V1 判断表可暂留 fixture/quarantine 供回归；V1 sidecar 只作历史存档，不参与主页面“最新”。模拟观察可留 observation store，但必须与预制分析分开。 |

证据：`06-Pi-Agent交互Demo/src/competitor-agent-v2.ts:258-265,352-476,1073-1077`、`scripts/competitor_agent_facts.py`、`09-工作台/modules/competitor/derived/competitor_agent_state_v2.sqlite`。

## 7. 广告异常与决策 `ads-anomaly`

- 判断对象：单个子 ASIN 下广告约束、关键词/竞品关系、结构问题、任务映射、诊断与建议。
- 触发范围：registry 登记为 `weekly`、`manual`；当前 V2 child decision 实际只接受 `manual`。
- 当前实现与目标差距：新 Runner 已有分点输出和 sidecar，但输入仍含未来推断/预算建议，上游库存 run 校验不全，工作台还读旧 `ext_*` 判断与 partial 结果。

| 检查项 | 当前事实与目标边界 |
|---|---|
| 1. 允许输入 | 广告对象结构与命名；历史展示、点击、花费、订单、预算与竞价事实；运营确认的产品目标、活动和控制计划；关键词位置与竞品市场的原始观察；合法的 completed 库存 run；中立聚合与 evidence index。 |
| 2. 禁止输入 | `ext_keyword_match`、`ext_competitor_pressure`、`ext_structure_issue`、`ext_diagnosis`、`ext_recommendation`、`ext_required_ad_task`、`ext_task_ad_object` 等预制判断；活动 `preset_uplift`；`fact_budget.recommended_budget`、预制流量损失估计；无 run 的库存结论。新桥已避开多数 `ext_*`，但后三类仍需清理。 |
| 3. 允许上游 Agent | 需求明确时可读 completed 库存/预测 run，并核对 child_asin、data_as_of/context、结果完整性；关键词/竞品若作为 Agent 上游，也必须以 completed run 明确接入。 |
| 4. 禁止上游 Agent | seed、failed、partial、过期库存 run；基础包里的关键词匹配和竞品压力预烤结论；本 Agent 旧输出，除非显式比较。当前桥只排除 `model_version='seed'`，不足。 |
| 5. 自己的输出 | B0b 约束、B0cd 匹配/竞品压力、B0e 结构问题、B1 任务、B2 映射、B3 诊断、B3b 覆盖、B4 建议，以及 run/evidence/恢复记录，写入 `ads_agent_state.sqlite`。 |
| 6. 规则校验 | 校验九个输出点完整、枚举、证据引用、主体一致、跨 B1/B2/B3/B4 引用闭环和禁止精确金额越权；ACOS/CVR/CPC 等确定性命中可作规则层。不得以 `ext_*` 表做答案同一性校验。 |
| 7. 展示区域 | completed 完整 run 的判断进入 Agent 区；广告表现与已确认计划进入事实区；阈值命中单列规则区。当前 `build_context()` 与 `handle_decide()` 仍把旧判断层带入工作台交接，需切断。 |
| 8. 无结果时 | Agent 区尚未分析，事实和规则异常照常展示；不得用 `agent_stages()` 从扩展库恢复预烤任务、诊断和建议。 |
| 9. 运行状态 | sidecar 有 22 个 run：20 completed、2 failed；其中 5 个 completed child decision 少于 8 个业务输出点，读取层仍可返回 partial points。目标应在完整性门禁通过后才置 completed，阶段产物只用于进度/恢复。 |
| 10. fixture 边界 | 广告扩展库的旧 B0–B4 判断表可作为 fixture/黄金样本隔离保留；正式工作台和 Agent 输入均不得 fallback。构造的历史广告事实可保留，但 future inferred uplift 只能进 fixture。 |

证据：`06-Pi-Agent交互Demo/scripts/ads_agent_facts.py:149-165,247-271,569-598`、`src/ads-agent.ts`、`09-工作台/modules/ads/compute.py:288-388`、`modules/ads/derived/ads_agent_state.sqlite`。

## 8. 广告目的标签 `ads-purpose-label`

- 判断对象：单个广告对象在命名、结构和投放行为下的实际用途及证据充分度。
- 触发范围：registry 为 `manual`；设计 run type 为 `purpose_label`、输出点为 A1。
- 当前实现与目标差距：代码和读取函数存在，但库内没有成功 purpose-label run；页面现有 54 个标签来自数据包而非 Agent。

| 检查项 | 当前事实与目标边界 |
|---|---|
| 1. 允许输入 | Campaign/广告组/投放对象的命名和层级；匹配类型、投放对象构成、历史投放行为；产品身份映射；最小样本量与 freshness 等规则参数。 |
| 2. 禁止输入 | 数据包已有 purpose 标签、`ext_task_ad_object` 的用途映射、预制结构诊断、预制“无法识别”原因；本 Agent 旧 purpose 输出。 |
| 3. 允许上游 Agent | 默认不需要。若未来使用产品目标，只能读运营确认的 committed plan，而不是广告异常 Agent 的建议。 |
| 4. 禁止上游 Agent | `ads-anomaly` 的同批 B2/B3/B4 判断不得反向成为目的标签输入；其他模块结论默认禁读。 |
| 5. 自己的输出 | 每个广告对象的 purpose 标签建议、依据、证据是否充分、无法识别对象及原因；按登记设计写 `fact_ads_agent_run.run_type='purpose_label'` 与 A1 输出。 |
| 6. 规则校验 | 校验对象存在、证据引用、允许标签词表、证据不足时允许无法识别；展示/点击/花费/订单计数由确定性层复算。不得校验等于数据包的 54 个旧标签。 |
| 7. 展示区域 | completed A1 进入广告对象目的的 Agent 区；对象结构与表现留事实区；运营确认标签应另写 human action。 |
| 8. 无结果时 | 显示“尚未完成目的标签分析”；不得继续把旧 54 个数据包标签说成 Agent 结论。若业务必须展示，可明确标为 fixture/历史人工标签。 |
| 9. 运行状态 | 登记为“未接通”；代码与读取函数存在，但现有 run_type 只有 `child_decision` 与空值，未发现成功 `purpose_label` run。正式状态须沿用 running/completed/failed 与输出完整性。 |
| 10. fixture 边界 | 54 个旧标签（含 11 个无法识别）适合作测试覆盖与对照，不得默认作为正式 A1 最新结果。 |

证据：`09-工作台/modules/agentcfg/registry_seed.py:269-311`、`06-Pi-Agent交互Demo/src/ads-agent.ts`、`09-工作台/modules/ads/derived/ads_agent_state.sqlite`。

## 9. 运营总览 `overview-digest`

- 判断对象：同一时点四个业务模块已完成结论之间的总体优先级、冲突与综合行动含义。
- 触发范围：当前未定义；目标只能在声明的上游 run 集合就绪后由依赖编排触发。
- 当前实现与目标差距：只有 registry 占位，无职责契约、代码、结果库和页面正式读取；且尚未决定它是确定性排序还是跨模块 Agent 判断。

| 检查项 | 当前事实与目标边界 |
|---|---|
| 1. 允许输入 | 四模块各自完整 completed run 的小结、证据引用和明确的运行时点；必要的跨模块实体映射；工作台可复算的模块级计数。 |
| 2. 禁止输入 | 基础包预烤摘要、页面现成卡片文案、partial/failed/stale 上游结果、把规则排序包装成 AI 总结。 |
| 3. 允许上游 Agent | 需求预测、盘点结论、库存总体分析、关键词机会/布局、竞品 V2、广告异常/目的标签；仅限契约点名且满足六项上游条件的结果。 |
| 4. 禁止上游 Agent | 任何 seed、V1、Smoke、fixture 或没有 run_id/context 的模块结论；缺失模块不能用旧答案补齐。 |
| 5. 自己的输出 | 只有在职责定为“跨模块冲突消解与综合判断”时，才输出总体结论、优先事项、冲突与引用链。当前无实现、无契约、无输出表。 |
| 6. 规则校验 | 校验上游覆盖率、时点一致、引用闭环和冲突披露；纯排序、计数、Top-N 应由工作台完成。不得校验为预制总览。 |
| 7. 展示区域 | completed 总览进入首页 Agent 区；四模块事实计数与规则告警仍各自展示，不能被一段 AI 文案替代。 |
| 8. 无结果时 | 首页事实与模块入口照常成立，总览 Agent 区显示尚未分析并指出哪些合法上游尚缺；不生成占位结论。 |
| 9. 运行状态 | 当前“待声明”，总览页是占位，无代码、触发、sidecar。目标应由依赖编排触发，并冻结本次使用的全部 upstream run_id。 |
| 10. fixture 边界 | 可用四模块冲突样本测试综合契约；预制总览、预定优先顺序仅留 fixture。若最终只是确定性排序，应取消 Agent 身份。 |

证据：`09-工作台/modules/agentcfg/registry_seed.py:312-354`。

## 10. 当前真实表与关键字段索引

| Agent | 当前事实/输入读表 | 当前或目标结果表 | 工作台正式读取边界 |
|---|---|---|---|
| `demand-forecast` | `dim_product_child(child_asin,parent_asin,category)`；`fact_child_sales_daily(date,units_sold,orders,average_selling_price)`；`fact_child_inventory_daily(closing_fba_sellable,received_units,stockout_flag)`；`fact_child_advertising_daily`、`fact_child_traffic_daily`、`fact_child_price_daily`、`fact_child_promotion_daily`；`plan_child_advertising_daily`、`plan_child_promotion_daily`、`plan_child_price_daily`、`plan_child_supply_event`；`fact_inventory_snapshot`、`config_child_inventory_policy` | `forecast_agent.sqlite`: `fact_child_forecast_agent_run`、`fact_child_forecast_agent_daily`、`fact_child_forecast_judgment_factor`、`fact_child_forecast_agent_step` | `modules/inventory/agent_forecast.py` 与 `forecast.py` 只应选择完整 completed run；基础包 `fact_child_forecast_daily` 禁止 fallback |
| `stock-verdict` | 通过 `modules.inventory.compute/verdict` 间接读取产品事实、预测 run 和确定性 projection；桥中关键越界字段为 `contract_facts[].expected_state` | `verdict_agent.sqlite`: `fact_child_verdict_run(run_id,child_asin,input_forecast_run_id,model_version)`、`fact_child_verdict_item(block,ord,state,verdict,because,refs,numbers)` | 只读非 seed、完整 completed run；当前 schema 还没有 status/completed_at |
| `stock-group-review` | 目标读取 forecast/verdict 的 run 与 item/daily/factor，以及产品实体分组字段；当前没有实际 Reader | 尚无结果库；目标至少需要 group run、member/run reference、summary/priority/conflict 表 | 当前无正式读取；将来只从自己的 completed group run 读取，不临时拼接 fixture |
| `keyword-opportunity` | `dim_keyword_scope`、`dim_keyword_term`、`dim_keyword_child_pair`、`fact_keyword_market_snapshot`、`fact_keyword_child_position_daily`；当前桥另读 `dim_keyword_child_goal` 和 `fact_keyword_child_absorb` 的争议字段 | Smoke: `keyword_agent_loop_state.sqlite` 的 `fact_keyword_loop_run/step`；正式代码目标为 current/state 库及五类结果表 | `modules/keyword/agent_result.py` 当前会回落基础包；目标只读正式 completed current/state，不读 Smoke |
| `keyword-child-goal` | `dim_keyword_child_goal(product_goal,push_role,product_lifecycle,is_current)`、`dim_keyword_child_pair`、`fact_keyword_child_position_daily`，以及 completed 词级 run | 当前未独立落库；目标应有独立 child-goal run、layout item 和 upstream run reference | 当前 `fact_keyword_child_goal_check` 是基础包预烤结果，不能作为无 run 答案 |
| `competitor-threat` | `dim_competitor_family`、`dim_competitor_child`、`dim_competitor_keyword`、`bridge_competitor_keyword`、`fact_competitor_price_daily`、`fact_competitor_market_daily`、`fact_competitor_keyword_rank`，以及自有产品价格映射 | V2 sidecar 的 `fact_competitor_agent_execution` 和 10 张 `fact_competitor_analysis_*`/handoff 结果表 | `modules/competitor/data.py` 只读 context 匹配的 V2 completed；基础库与 V1 sidecar 判断禁读 |
| `ads-anomaly` | `ext_decision_context`、`ext_product_goal`；产品事实表；广告库 `dim_ad_object`、`bridge_ad_object_product`、`fact_ad_performance`、`fact_budget`、`fact_invalid_traffic`、`fact_ad_label_version`；`ext_keyword_position`；竞品观察表；库存 verdict run/item | `ads_agent_state.sqlite`: `fact_ads_agent_run`、`fact_ads_agent_stage`、`fact_ads_agent_output`、`fact_ads_agent_item`，输出点 B0b/B0cd/B0e/B1/B2/B3/B3b/B4 | 只读完整 completed child_decision；`compute.agent_stages()` 对 `ext_diagnosis/ext_recommendation` 等 fallback 应退出正式链 |
| `ads-purpose-label` | `dim_ad_object(object_level,ad_type,campaign_id,object_name)`、`bridge_ad_object_product`、`fact_ad_performance`、匹配/投放结构事实 | 设计复用 ads sidecar：`fact_ads_agent_run.run_type='purpose_label'` 与 `fact_ads_agent_output.output_point='A1'` | `latest_purpose_labels()` 只应读取 completed A1；当前库无成功 run，数据包 purpose 标签不得冒充 |
| `overview-digest` | 目标读取各 Agent 的 completed run 头、摘要、证据引用和 frozen upstream run_id 集合；当前没有实际表读取 | 尚无结果库；目标需 overview run、upstream reference、digest/conflict/action item | 当前无正式读取；不得从模块页面 read model 或基础包摊平 payload 取答案 |

## 11. 关键词双层对象与双运行链专项说明

### 11.1 市场词与子体词不是同一个判断对象

| 层级 | 合法事实输入 | 应由本层产生 | 禁止串用 |
|---|---|---|---|
| 市场关键词 | 市场搜索量、排名/位置历史、需求变化、核心词关系 | 机会/风险、优先级、证据完整度、后续验证去向 | 子体库存答案、布局 goal check、预制优先级 |
| 关键词 × 子体 | 自然/广告位置、展示点击转化、覆盖和中立变化量 | 覆盖事件、该词对该子体的角色判断 | 市场词结论直接复制为子体结论 |
| 关键词 × 子体 × 目标 | 运营确认目标及版本、词表现、completed 上游词级 run | 该推/守/放弃、目标—布局不一致 | 预制 lifecycle、absorb state、goal check |

### 11.2 Smoke 与正式 Full Runner 的边界

| 项目 | Smoke loop | 正式 Full Runner |
|---|---|---|
| 目的 | 验证六步模型调用、工具闭环与状态恢复 | 产生可发布的全量关键词判断 |
| 范围 | 调用 `loadKeywordAgentFacts('all')`，但送入模型的市场候选仅前 20 条 | 强制 `scope='all'`，按 C、D、A、B、E 阶段处理完整范围 |
| 落点 | `keyword_agent_loop_state.sqlite`，只有 loop/task/step 状态 | 代码声明 `keyword_agent_current.sqlite` 与 `keyword_agent_state.sqlite`，当前文件均不存在 |
| 当前结果 | 3 次均 failed，错误为 `MODEL_TIMEOUT` | 没有可审计的正式 published run |
| 工作台资格 | 无；不能当正式 run，也不能触发基础包答案发布 | 仅 completed、完整、context 匹配后可进入 Agent 区 |

结论：Smoke 成功也不等于正式结果可用；正式结果缺失也不授权回落基础包五张预烤输出表。
