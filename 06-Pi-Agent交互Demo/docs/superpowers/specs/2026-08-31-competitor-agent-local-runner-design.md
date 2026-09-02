# 竞品 Agent 本地 Runner 设计

日期：2026-08-31  
状态：已废止，由 `2026-08-31-competitor-agent-v2-task-service-design.md` 替代
范围：Bamboocool 竞品模块 P0 Demo

## 1. 目标

构建一个使用本机 Pi 配置的真实竞品 Agent。一次运行针对一个竞品父 ASIN，按业务依赖顺序完成证据可用性、变化性质、整族代表性、竞争影响、同期关系、关注等级和报告交接判断，并将通过契约门禁的结果提供给现有竞品页面。

P0 重点证明：

- Agent 逐步判断，不并行回放固定九个工具；
- 模型负责分类、边界和中文表达，确定性程序负责数值和引用；
- 原始观察数据不被 Agent 改写；
- 证据不足、局部变化和平稳对象都有正确降级结果；
- 页面只读取 completed 结果，失败运行不可见。

## 2. 冻结边界

- 判断对象是竞品产品族，即父 ASIN。
- 13 张观察层表和 ATTACH 的自有产品包永久只读。
- Agent 只产出 10 张判断层表对应的内容。
- 不输出广告预算、出价、开关或库存推断。
- 不使用综合威胁分数；只输出关注等级和可解释依据。
- 流量占比不能反推竞品花费、预算或出价。
- 价差只按件单价；`pack_resolved=0` 的对象不能进入价差结论。
- 同期变化只表述为“同期变化”或“可能相关”，P0 的 `causal_ready` 保持 0。

## 3. P0 运行与读取方式

P0 延续广告 Demo 已确认的本地方式：

- 本地 CLI 启动真实 Pi Runner；
- 浏览器和工作台 GET 只读取结果，不触发写操作；
- 页面“重新分析”在 P0 只刷新或提示本地运行方式，不创建任务；
- 浏览器点击即启动、幂等队列和轮询属于后续生产接入。

CLI：

```text
npm run demo:competitor-agent -- B0CJ9QLVPP
```

## 4. 数据架构

原始观察库保持只读：

`08-竞品分析模块/02-数据构建/v0.1.0/competitor_demo.sqlite`

Agent sidecar：

`09-工作台/modules/competitor/derived/competitor_agent_state.sqlite`

sidecar 包含：

- `fact_competitor_agent_execution` 执行台账；
- 与现有 schema 同形的 10 张竞品判断表。

执行台账至少保存：

`task_id`、`run_id`、`family_asin`、`status`、`trigger`、`source_context_hash`、`threshold_fingerprint`、`model_version`、`method_version`、`schema_version`、`dataset_version`、`rule_version`、`prev_run_id`、`created_at`、`completed_at`、`reason`。

Pi Runner 是唯一写者。工作台以只读模式 ATTACH sidecar，只选择 `status=completed` 的结果。latest JSON 仅用于联调，不作为页面权威来源。

## 5. 顺序工具链

每轮只开放当前阶段工具：

1. `get_competitor_analysis_context`
   - 冻结父 ASIN、观察窗、七个阈值、数据版本和 context hash。
2. `assess_competitor_evidence`
   - 判断 `sufficient / partial / insufficient`。
3. `classify_competitor_changes`
   - 判断四类变化及时间、幅度和状态。
4. `assess_family_representation`
   - 判断变化能否代表整族并生成覆盖说明。
5. `map_competitive_impacts`
   - 将可成立的变化映射到自有产品和共同词。
6. `assess_change_concurrency`
   - 判断同期、先后、独立或证据不足。
7. `assign_attention_level`
   - 输出关注等级、摘要和至少两条可解释依据。
8. `assemble_competitor_outputs`
   - 生成时间线、待观察项、diff、报告和冻结交接。
9. `submit_competitor_contract`
   - 执行跨表门禁并在单事务内写入 sidecar，最后标记 completed。

## 6. 判断与确定性字段边界

模型负责：

- 变化类型、定性方向、是否能代表整族；
- 竞争关系与可能影响范围；
- 同期关系的非因果表述；
- 关注等级、摘要、依据和中文成品文案；
- 报告选题、待观察项和下游证据交接。

程序锁定或生成：

- run、change、report、handoff 等 ID；
- 所有观察数值、日期、幅度和对象候选；
- 自有与竞品件单价及倍数；
- 数据状态、断更区间、过期天数和来源档位；
- `created_at`、版本、context hash；
- 最新 completed run 的选择与 `prev_run_id`；
- 词表翻译、趋势降采样、筛选、排序和图表布局。

模型提交只需满足 schema、枚举、引用和事实一致性，不要求与预制判断全文相等。

## 7. 关键业务门禁

- `evidence_level=insufficient` 时强制 `attention_level=none`、零条关注依据、零报告。
- `attention_level!=none` 时至少两条关注依据，`weight_note` 只能是定性说明。
- 断更两端的数值不能直接相减形成变化。
- 变化日期必须在观察窗内，对象 ID 必须能在观察层解析。
- `represents_family=0` 必须有覆盖说明，且不能被报告当作整族结论。
- 影响中的自有对象必须来自 `bridge_competitor_child`。
- 价差结论的对象必须完成装盒数解析，并能复算件单价。
- concurrency 引用必须存在；P0 禁止升级为因果。
- 报告只允许 `high/medium + sufficient + 至少一条整族变化`。
- handoff 冻结具体 completed run，不引用“最新”。每个 run 每个目标页 P0 最多一条。
- 同族同日重复运行的 `created_at` 必须不同，按解析后的绝对时间选最新。
- 任一子表失败都不能留下 completed 运行。

## 8. GET 与前端兼容

现有业务路由保持：

- `GET /api/competitor/rivals`
- `GET /api/competitor/rival/<family_asin>`

读取层将 sidecar 的最新 completed 结果与观察事实装配。可以增加纯读取端点：

- `GET /api/competitor/agent-result?family_asin=...`
- `GET /api/competitor/agent-status?family_asin=...`

响应拆分两个状态：

- `condition`：观察资源是否存在；
- `analysis_state`：`current / not_run / stale / insufficient / incomplete / damaged`。

已有竞品族无论有没有 Agent run 都继续显示观察事实。旧结果过期时保留旧内容和分析日期，不涂红；证据不足显示“本次不给关注结论”，不能误写成“无需处理”。

P0 同时修正：

- 后端 `keyword` 与前端 `shared_keyword` 的字段错位；
- 总览报告只读取各族最新 completed run 的合格报告；
- `prev_run_id` 必须真实可解析；
- 最新运行按解析后的时间选择，而不是字符串 `MAX`。

## 9. 黄金对象

- `B0CJ9QLVPP`：持续降价、整族成立、排名同期走强但不判因果、high、报告与广告交接。
- `B0D8V2L6JS`：单个非主销子体局部变化，验证不能进入整族报告。
- `B0C81Q5KRW`：关键词抢位，验证关键词与广告证据交接。
- `B0D7D246LV`：断更、来源冲突和过期，验证 insufficient 短路。

`B0FNQYP7DW` 作为 P0.5 活动开始—结束—恢复对象。

## 10. 验收

- 现有竞品契约门禁全部通过；以脚本实际 23 条为准，不沿用文档旧写法 20 条。
- 四个黄金对象真实 Pi 运行成功且结论形态不同。
- 局部变化不进入整族报告。
- 证据不足对象为 none、零依据、零报告。
- 同期变化不出现因果断言。
- 所有数值、日期、对象和引用可从当前 context 复算。
- 中文文案不泄漏内部枚举，不出现综合威胁分数或广告动作。
- 同族同日连续运行可正确形成 `prev_run_id` 和 diff。
- 中断、损坏、incomplete 和 stale 运行不会冒充 current。
- SQLite、GET 和 latest JSON 的 run_id 一致；页面权威只认 SQLite。
- 工作台通用门禁与竞品渲染测试继续通过。

## 11. P0 非目标

- 浏览器点击启动或排队；
- 周期调度与“下次运行时间”；
- 确认因果关系；
- 生成广告执行动作；
- 重做竞品页面视觉。
