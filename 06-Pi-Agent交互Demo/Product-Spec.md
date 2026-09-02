# Bamboocool 子 ASIN 销量预测 Agent Product Spec

本项目的已批准产品规格为：

- [子 ASIN 逐日销量预测与库存决策数据设计](docs/superpowers/specs/2026-08-30-child-asin-demand-forecast-data-design.md)
- [Pi Agent 交互 Demo 设计](docs/2026-08-29-Pi-Agent交互Demo设计.md)

实现优先级：

1. P0：恢复完整需求预测 Agent 职责，只读客观历史事实与未来运营计划，由 Agent 同一 run 产出 90 天逐日预测、五类影响判断和执行步骤。
2. P0：撤下“只解释预烤预测”的 `forecast-judgment` 错误链；数据包预测只作为无 Agent run 时的快照回落与并排对照。
3. P0：工作台继续确定性计算库存余额、覆盖、断货、缺口、补货和风险，不让需求 Agent 重算库存算术。
4. P0：完成禁读字段、原子落库、来源回落、自动化测试和真实 Pi 冒烟测试。
5. P1：更新 Organic Soft-Tech 前端以展示黄金场景、数据来源和丰富执行轨迹。

需求预测职责恢复的批准规格：[需求预测 Agent 职责恢复设计](docs/superpowers/specs/2026-08-31-demand-forecast-agent-responsibility-restoration-design.md)。

## 库存盘点结论 Agent P0 纵切

时间受限时，先以 `B0B3LM36WB` 跑通一条可交付给工作台前端的真实链路：

1. Pi Agent 从工作台 `compute.assess()` 同源读取需求、库存、在途、库龄和仓储费事实，不复制计算公式。
2. Agent 必须按顺序先读事实，再提交 `safety / in_transit / stockout / overstock / storage_fee` 五条结构化结论。
3. 提交门禁校验条数、状态词表、排序、引用和 `numbers` 与页面同口径计算的一致性；任一失败则整次不落库。
4. 校验通过后原子写入工作台 `verdict_agent.sqlite`，同时导出 `verdict_agent_latest.json` 给前端联调。
5. 在途采用 B 方案，只判断到货是否赶得上断货；当前数据没有实收和逾期证据，不输出“有逾期”。

## 广告分析 Agent v2 重建

批准规格以 [`09-广告Agent重建两侧分工.md`](../00-通用方法与规范/09-广告Agent重建两侧分工.md) 为准；旧的本地 Runner P0 设计作废。

1. 采用方案 A：一个广告 Agent、两条工作流。A1 按广告对象运行；页面二按子 ASIN 串行执行 B0b → B0cd → B0e → B1 → B2 → B3/B3b → B4。
2. Agent 侧只负责 Runner、提示词、干净输入桥和 sidecar 写入；不修改前端、读取层和枚举中文映射。
3. 两侧唯一接缝是 `ads_agent_state.sqlite` 的 `fact_ads_agent_run` 与 `fact_ads_agent_output`。运行表保留原 18 列并新增 `run_type`、`subject_kind`、`subject_id`；结论通过九值 `output_point` 词表区分。
4. 原广告包、产品包和竞品包只读；严禁读取 `ext_*` 结论行、预烤阶段契约、特定 ASIN 手工答案或用同一性比较作为门禁。
5. Pi 每轮只调用当前步骤的一个工具，后一步只能读取前一步已接受结果；模型只输出码值和契约要求的自由文本，`*_label` 中文译名由前端统一生成。
6. `diagnosis_coverage` 从运行表迁到 `output_point='B3b'` 的结论行，运行表旧列保留但留空。
7. A1 的 `rationale` 写入 A1 `payload`，不修改只读的 `fact_ad_label_version`；保持“两张表一个接缝”。
8. 子 ASIN 完整运行已经落地为八点状态机：每点校验后立即追加落表，禁止覆盖和跳步；八点齐全前保持 `running`，全部通过后才原子切为 `completed`。
9. 校验器检查字段、枚举、确定性数字、证据引用、非因果、精确值抑制和跨步引用闭环；同时拦截“已有任务却判 REQUIRED_TASK_MISSING”“无直接断货信号却把缺输入写成 INVENTORY_COVERAGE_RISK”等跨阶段语义矛盾，但不指定真实产品必须得到某个结论。
10. Runner 默认使用 Pi 的 `deepseek/deepseek-v4-flash`；本地联调可用 `BAMBOO_ADS_MODEL=provider/model-id` 临时选择已配置模型，不修改 Pi 全局默认。
11. 浏览器触发 Runner、`/decide` 持久化与生产 POST 接口后置；A1 与其余演示对象在子 ASIN 接缝稳定后继续。

## 关键词分析 Agent P0 纵切

批准规格见 [关键词 Agent 本地 Runner V2 设计](docs/superpowers/specs/2026-08-31-keyword-agent-local-runner-v2-design.md)。旧的 `keyword-agent-local-runner-design.md` 只保留为历史记录，不作为实现或验收依据。

1. 本地真实 Pi Runner 按上下文 → 市场事件 C → 覆盖事件 D → 证据 A → 日报 B → 盘点 E → 发布顺序运行，每轮只开放下一工具。
2. `library_status` 与 `operator_role` 是 Demo 例外输入，Agent 不得重新判断或修改 1991 词角色。
3. 五张旧判断表整表禁读；候选对象和锁定事实只能由其余 19 张输入表生成。
4. 模型判断 A/B/C/D；E 根据本 run 的 A 和位置事实确定性聚合。模型允许返回 `null`，不得被迫复刻旧构造分布。
5. 结果以原库完整副本承载，只替换五张判断表，并用 manifest + 独立 ledger 的双 completed 与 context hash/参数一致性发布。
6. 运行时间戳带 `+08:00`，台账保留版本、数据截止日和 `prev_run_id`；未完成、失败或过期结果不上屏。
7. J3 完整竞争结构解释和 J8 业务作用没有正式落库字段，本期不实现；浏览器触发 Agent 后置。
8. 当前 Demo 收口验收只要求真实 Pi Agent Loop 能启动，并按顺序进入至少一个业务判断批次；不要求 full-scope 运行完成或发布结果。完整五表生成、六路由联调和双对象下钻改列后续增强，半份结果仍禁止切换为 `current`。
9. 关键词页通过工作台右侧统一任务窗口触发独立 Loop Smoke：运行态只写 `keyword_agent_loop_state.sqlite`，每 1.5 秒轮询展示冻结范围、读取候选、创建 Pi 会话、模型判断与工具门禁；成功或失败都不触碰正式 manifest、结果账本和 `current`。

## 竞品分析 Agent V2

当前规格见 [竞品 Agent V2 任务服务设计](docs/superpowers/specs/2026-08-31-competitor-agent-v2-task-service-design.md)。
旧的 `competitor-agent-local-runner-design.md` 已被本节替代，只保留为历史记录，不作为实现或验收依据。

1. Pi 任务服务是唯一运行状态权威，提供手动、周期和重点对象三类触发。
2. 页面通过 POST 发起、GET 轮询；API 五态映射到内部 queued/running/completed/skipped/failed。
3. 相同 `request_key` 幂等复用任务；模型运行期间不持写事务。
4. 原观察库和产品包永久只读；V2 输出写 `competitor_agent_state_v2.sqlite`，旧 5 次运行不迁移、不参与读取。
5. 模型严禁读取 `value_origin`、`dim_competitor_scenario`、legacy 判断表和 V1 sidecar。
6. 八个业务步骤严格顺序执行；coverage 阈值只作参考，不能由程序提前决定整族代表性。
7. 写入端负责全部身份、时序、跨 run 和全局排位字段；11 张表通过门禁后原子发布。
8. 不生成综合威胁分数，不推断竞品库存，不用流量占比反推广告投入，价差只按可解析件单价。
9. 真实 Pi 验收必须覆盖幂等、跳过、阈值变化重跑、失败恢复、连续两版 diff 和 priority 周期批次。
10. 重跑不得静默清空仍受当前证据支持的影响范围或下游交接；`constructed` 变化仍单独展示，真实/推导事实为空时页面必须解释为来源为空，而不是“没有发现变化”。
11. 完整事实包只供程序计算指纹和最终校验；模型按八步逐段接收最小事实切片，后一步只能在前一步工具结果通过后开放。门禁拒绝后在当前步骤携带安全错误重试，仍失败才落失败台账，并记录安全的失败步骤与失败类别。

演示节奏规则：销量预测场景按九个工具逐项调用；竞品 V2 按八个业务判断步骤逐项调用。
所有场景每轮模型响应只能产生一个工具调用，前端按业务顺序展示步骤，并保证每一步有足够的最短可读时间。
展示节奏不改写工具返回的真实执行耗时。

技术栈保持现有方案：Python 标准库构建 SQLite 数据包；Node.js 25、TypeScript、`node:sqlite` 和本机 Pi Agent SDK 提供同源 Web 服务。
