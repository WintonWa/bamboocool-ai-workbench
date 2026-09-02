# 竞品 Agent V2 任务服务设计

日期：2026-08-31  
状态：已确认并实现  
范围：Bamboocool 竞品分析模块真实 Pi Agent 重建

## 1. 背景与替代关系

本设计完全替代 `2026-08-31-competitor-agent-local-runner-design.md`。旧设计只证明本地 CLI
能够运行，不具备新版交底要求的页面异步触发、请求幂等、周期运行和可观察状态机，不能继续作为
竞品 Agent 验收基线。

当前 `competitor_agent_state.sqlite` 中的 5 次运行保留作审计，不迁移、不复制，也不参与 V2
页面读取。V2 使用独立数据库，首次上线时所有竞品显示“尚未分析”，直到新 Agent 产生第一条
`completed` 结果。

## 2. 目标

一次任务针对一个竞品产品族（父 ASIN），使用当前请求给定的观察窗和七个业务阈值，完成：

1. 数据可用性判断；
2. 变化性质识别；
3. 整族代表性判断；
4. 竞争关系和影响范围判断；
5. 同期关系判断；
6. 关注程度与依据；
7. 报告选题；
8. 时间线、待观察、版本差异和下游交接装配。

页面不等待模型同步返回。手动、周期、重点对象三类入口全部进入同一任务服务和同一判断链。

## 3. 冻结业务边界

- 判断对象是竞品产品族；子 ASIN、报价和关键词只作为观察对象。
- 观察库和产品包永久只读。
- Agent 只产出竞品判断，不采集数据，不写观察层。
- 不输出综合威胁分数、广告预算、出价、开关、竞品库存推断或执行动作。
- 流量占比不能反推竞品花费、预算或出价。
- 价差只按件单价；`pack_resolved=0` 的对象不能形成价差结论。
- 同期关系只能表述为“同期变化”或“可能相关”；V2 P0 的 `causal_ready` 恒为 0。
- `family_coverage_pct` 是参考证据，不是程序替 Agent 作答的硬门槛。少数主销变体也可能代表整族；
  大量非主销变体也可能不能代表整族。

## 4. 数据隔离

### 4.1 只读输入

- 观察库：`08-竞品分析模块/02-数据构建/v0.1.0/competitor_demo.sqlite`
- 产品包：`02-产品销售库存模块/02-数据构建/v0.3.0/bamboocool_product_sales_inventory_v0.3.0.sqlite`

### 4.2 V2 权威输出

- V2 sidecar：`09-工作台/modules/competitor/derived/competitor_agent_state_v2.sqlite`
- 联调镜像：`09-工作台/modules/competitor/derived/competitor_agent_latest_v2.json`

工作台以 V2 sidecar 为唯一权威来源；JSON 只用于联调与人工检查。

### 4.3 禁止进入模型上下文

以下内容既不能出现在 Prompt，也不能出现在任何工具结果：

- `dim_competitor_scenario`；
- 观察库中的 9 张 legacy `fact_competitor_analysis_*` 判断表；
- legacy `fact_competitor_evidence_handoff`；
- 观察表的 `value_origin`；
- V1 sidecar 的 5 次运行；
- 任何“这个族应该得出什么结论”的黄金答案或形态标签。

程序可以在提交阶段读取来源元数据并盖入 `change.value_origin`，但模型不得看到或生成该字段。
证据充分度只能依据断更、冲突、缺失、过期和观察连续性判断。

## 5. 运行权威与状态机

Pi 任务服务是唯一运行状态权威。工作台只负责发起、轮询以及完成后重取只读页面。

### 5.1 页面接口

```text
POST /api/agent/competitor/runs
GET  /api/agent/competitor/tasks/<task_id>
```

工作台现有 `/api/agent/*` 代理继续负责转发请求体和响应，不在竞品模块内直连模型。

POST 请求体严格采用交底包：

`trigger, family_asin, window_from, window_to, data_as_of, requested_by, request_key, thresholds`

- `manual` 必须有 `requested_by`；
- `scheduled` 和 `priority` 由调度入口发起；
- 七个阈值必须完整、夹紧并进入阈值指纹；
- `sort_by`、`quick_only` 只属于页面，不能进入任务请求。

### 5.2 幂等

`task_id` 由 `family_asin + SHA-256(request_key)` 确定性生成。执行台账以 `task_id` 唯一约束：

- 相同 `request_key` 重复提交返回同一任务；
- 运行中不新增任务；
- 已完成、跳过或失败时返回已保存的终态；
- 新请求必须使用新的 `request_key`。

不向 11 张正式表增加 `request_key` 列，以保持当前落盘 schema 不变。

### 5.3 内外状态映射

内部执行台账：

`queued → running → completed | skipped | failed`

页面 API：

- `queued → queued`
- `running → running`
- `completed → done`，附 `run_id`
- `skipped → skipped`，附 `reason`
- `failed → failed`，附安全的人类可读 `reason`

`failed.reason` 必须至少包含失败步骤和安全类别，例如“判断竞争范围 · 未提交通过门禁的工具结果”或
“写入前契约校验 · 结果未通过完整性门禁”；不得保存供应商密钥、完整 Prompt 或原始异常堆栈。

任务入队时先在短事务内分配 `task_id/run_id/created_at` 并提交 `queued`。模型运行期间不持有写事务。
最终 10 张判断表与 `completed` 状态在一个事务内提交。

### 5.4 跳过规则

最新 completed 运行同时满足下列条件时可以跳过：

- `source_context_hash` 相同；
- `threshold_fingerprint` 相同；
- `model_version/method_version/schema_version/rule_version` 相同。

阈值或任一版本变化时，即使观察数据没变也必须重跑。

## 6. 八步顺序 Agent

编排器先在模型外组装并净化完整只读 context，用于指纹、幂等和最终校验，但不得一次性发送给模型。
模型按下列八步逐段接收当前步骤的最小事实切片；同一个会话保留前序已接受判断，每轮只开放一个合法工具，
前一步没有通过门禁时不得披露或执行后一步：

1. `judge_competitor_evidence`
   - 输出 `sufficient / partial / insufficient` 和成品中文原因。
   - `insufficient` 立即短路到第 8 步。
2. `judge_competitor_changes`
   - 从程序给出的候选和锁定数字中选择成立变化，判断性质、状态和中文表达。
3. `judge_family_representation`
   - 综合命中比例、主销身份、在售数和自报变体数判断能否代表整族。
4. `judge_competitive_scope`
   - 只从已确认竞争关系桥和共同词候选中选择自有影响范围。
5. `judge_change_concurrency`
   - 判断同期、先后、独立或证据不足，不升级因果。
6. `judge_attention_and_impact`
   - 给关注等级、摘要、至少两条不重复依据和可能影响。
7. `judge_report_selection`
   - 只有 `high/medium + sufficient + 至少一条整族变化` 才可进入报告候选。
8. `assemble_competitor_run`
   - 产出时间线局部序号、待观察、diff 定性、报告文案和下游交接候选。
   - 当前证据仍支持且 diff 为 `sustained / escalated` 时，不得静默删除上一版影响范围或下游交接。
   - 已确认且价差变化达阈值的关系必须进入影响范围；有共同词的影响必须交接关键词页，流量结构变化必须交接广告页。

八步全部完成后，编排器调用非模型写入器执行契约校验和原子提交。写入器不是第九个判断步骤。

阶段披露边界：证据步只见数据健康摘要；变化步才见变化候选与对应阈值；代表性步才见产品族结构与覆盖；
竞争范围步才见关系桥与共同词；同期步见变化时序；装配步才见上一版及交接候选。工具成功结果只返回下一步骤，
不得把后续事实夹带在前一步工具结果中。当前工具被门禁拒绝时，编排器把安全错误反馈给同一会话并在原步骤
重试，最多三次；未通过前不开放下一工具，三次均未通过才将步骤和最后一条安全门禁原因写入失败台账。

## 7. 模型与确定性程序的字段边界

### 7.1 模型负责

- 证据档位与理由；
- 哪些候选变化成立、变化标签、依据和当前状态；
- 是否代表整族及覆盖说明；
- 竞争关系、影响范围和非因果表述；
- 关注等级、摘要、依据和定性排序理由；
- 报告选题、假设、待观察和下游可观察事实；
- 与合法上一版相比的定性变化。

### 7.2 程序锁定或盖章

- 请求回填字段；
- `task_id/run_id/created_at/completed_at`；
- `report_id/report.item_seq/ref_run_id`；
- `handoff_id/frozen_run_id`；
- `prev_run_id`；
- 所有观察数字、日期、对象候选和引用；
- 幅度数值、窗口边界、件单价和价差倍数；
- `value_origin`；
- context、阈值和版本指纹；
- 页面词表、统计、筛选、排序和趋势降采样。

模型通过候选 ID 选择事实，不重抄数字。中文依据里的数字由写入器从锁定事实模板注入或交叉核验。

## 8. 写入与最新结果

V2 sidecar 保持 11 张表：10 张判断表 + `fact_competitor_agent_execution`。

流程：

1. `queued` 行已存在；
2. Worker 更新为 `running`；
3. 内存中组装完整 10 表 payload；
4. 运行 schema、枚举、引用、对象归属、数字和中文门禁；
5. `BEGIN IMMEDIATE`；
6. 重新解析同族上一条 completed run；
7. 盖入 `prev_run_id` 和可追加 ID；
8. 插入 10 张判断表；
9. 更新执行状态为 `completed`；
10. 提交后原子导出 latest JSON。

若第 5–9 步任意失败，事务回滚，再用独立短事务把执行状态更新为 `failed`。失败任务不能留下
可见的 analysis run。

首次 V2 运行的 `diff` 必须是 `new`，不得读取 V1 或观察库 legacy 判断。第二次起只能比较 V2
同族上一条 completed 运行。

报告全局 `item_seq` 由写入器按当前周期内各族最新合格报告重排：关注等级 high 优先于 medium，
同档按完成时间倒序、父 ASIN 稳定排序。该排序仅用于页面选第 1 条，不生成综合威胁分数。

## 9. 周期入口

周期命令调用与页面相同的 enqueue 服务：

- 快捷位 8 个族使用 `trigger=priority`；
- 其余本周期分析对象使用 `trigger=scheduled`；
- 每个对象生成确定性周期 `request_key`；
- 并发度受限，单对象仍严格执行八步顺序链；
- 单个族失败不阻断其他族。

P0 提供一次可手动执行的周期命令和结果汇总；常驻 cron 的部署配置不在本地 Demo 内创建。

## 10. 工作台行为

- 新增“重新分析”按钮，POST 后保存 `task_id`；
- 每 3 秒轮询状态，上限 2 分钟；
- queued/running 时旧结果继续可读；
- done 后重取 `/api/competitor/rival/<family_asin>`；
- skipped/failed 保留旧结果，不把失败渲染成业务告警；
- 页面不直接读取 SQLite，也不把 execution 台账当成浏览器接口；
- 页面只认 V2 sidecar 的最新 completed 结果；
- insufficient 显示“证据不足，本次不给关注结论”，不能显示“无需处理”。

## 11. 契约门禁

除当前观察层门禁外，V2 必须新增：

- 模型上下文禁读表和禁读字段扫描；
- 11 张表列名与枚举校验；
- 相同 request_key 幂等；
- 状态只允许合法转换；
- incomplete payload 不得 completed；
- 所有子表共享同一 run；
- change 对象必须属于当前族对应层级；
- impact 和 handoff 的自有对象、共同词必须属于当前族关系桥；
- timeline 和比较窗口不能越 run 窗口；
- concurrency 必须引用两条不同且存在的 change；
- `represents_family=0` 不能进入整族报告；
- insufficient 必须 none、零依据、零报告；
- attention 非 none 至少两条依据；
- P0 `causal_ready=0`；
- 报告和交接 ID 可跨重跑唯一；
- 中文不泄漏英文枚举、答案键、综合分数或广告动作；
- 失败/跳过任务零判断表可见；
- DB、latest JSON 和工作台 GET 的最新 run_id 一致。

当前 `test_contract_gates.py` 的演示覆盖 D1/D2 不作为真 Agent 正确性门禁。真 Agent 不需要为了铺满
枚举而强行制造某类结论。

## 12. 测试矩阵

### 12.1 单元与契约测试

- 请求 schema、阈值夹紧、指纹和 task_id；
- 五态转换与非法转换；
- 同 request_key 串行和并发幂等；
- 禁读字段扫描；
- coverage 参考证据不会硬锁结果；
- 写入端盖章和 ID 唯一；
- 首次 diff 为 new，第二次串联合法 prev；
- 原子回滚与 failed 修复；
- skipped 条件；
- report 全局排序；
- 工作台 current/not_run/stale/insufficient/incomplete/damaged。

### 12.2 真实 Pi 验收

至少运行：

- `B0CJ9QLVPP`：同族连续两次，验证合法 prev 和 diff；
- `B0D8V2L6JS`：验证局部变化不进入整族报告；
- `B0C81Q5KRW`：验证关键词变化和下游交接；
- `B0D7D246LV`：验证 insufficient 短路。

额外运行：

- 相同 request_key 双并发，只产生一个任务；
- 同数据同阈值同版本，得到 skipped；
- 同数据但改变阈值，必须重跑；
- 模型中断、提交中途故障和状态接口重启恢复；
- 一次 priority 周期批次，快捷位对象全部入队。

验收必须核对工具顺序、执行台账、10 张判断表、latest JSON 和工作台 GET，不能只检查模型最终文本。

## 13. P0 非目标

- 常驻生产调度器和外部消息队列；
- 多机 Worker 和分布式锁；
- 因果确认；
- 广告或关键词执行动作；
- 重做竞品页面视觉；
- 删除 V1 审计文件。
