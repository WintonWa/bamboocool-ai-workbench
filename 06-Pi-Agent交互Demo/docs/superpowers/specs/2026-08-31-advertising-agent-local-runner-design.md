# Bamboocool 广告 Agent 本地 Runner P0 设计

日期：2026-08-31  
状态：已完成方案确认，待书面规格复核

## 1. 目标

在不改造工作台请求体能力、不编写 POST 客户端的前提下，跑通广告分析真实 Pi Agent 的最小闭环：

1. 从工作台广告模块读取同口径事实；
2. Pi 按固定顺序生成 B1、B2、B3/B3b、B4；
3. 契约门禁校验对象、引用、归因窗口、枚举和确定性数字；
4. 全部通过后原子写入独立 sidecar SQLite；
5. 同时导出 latest JSON；
6. 现有广告页面继续使用 GET，读取最新完成的 Agent run。

P0 不是生产级任务系统，不处理外壳 JSON body、远程队列、多人审批或运营决定持久化。

## 2. 硬边界

- 不修改广告前端为 POST。
- 不依赖 HTTP request body。当前 `server.py` 创建 `Ctx` 时只有 query、params、fingerprint 和 as_of。
- 不把 HTTP 200 当成 body 已生效的证明。
- 原广告事实库保持只读。
- Pi 不直接执行 SQL；唯一写入口是契约提交工具。
- 页面一除 A1 广告目的建议外不增加 Agent 判断。
- 能力十继续由确定性算子负责。
- 能力十一的运营决定、执行交接和 D+3/D+7 回流不属于本轮 Agent 输出。
- 不合并不同归因窗口的销售额、ACoS 或 ROAS。
- 没问题也是结论；不得为了显得有用给健康对象虚构任务。

## 3. P0 黄金对象

### 3.1 B0B3LWGP36

用于验证多归因窗口隔离：

- SP 使用 7 天归因；
- SB/SD 使用 14 天归因；
- 花费可以汇总展示；
- 归因销售额、ACoS、ROAS 必须按 attribution block 分开；
- 只要同时存在 7 天和 14 天，顶层合计归因销售额、ACoS、ROAS 必须为空。

### 3.2 B0B3MBYGR5

用于验证健康对象短路：

- 只有 P2；
- 结论为 KEEP / 保持；
- 不追加模板化的 REQUEST_INFO 或 SPLIT；
- 不虚构异常、动作或缺口。

## 4. 架构

### 4.1 本地真实 Pi Runner

在现有 `06-Pi-Agent交互Demo` 项目增加广告专用命令：

```text
npm run demo:ads-agent -- <child_asin>
```

Runner 使用本机 Pi 配置和真实模型，不读取 fake 环境。每次运行只处理一个子 ASIN，并输出最终 run、items、数据库路径和 JSON 路径。

### 4.2 事实桥

事实桥直接复用工作台 `modules.ads.compute` 与 `modules.ads.data`，不复制广告计算公式。它负责：

- 构造当前对象的 context；
- 生成 B1–B4 所需候选事实；
- 给每个数值附带 metric basis、attribution days、evidence id 和 provenance；
- 删除或置空跨归因窗口伪合计；
- 生成稳定 context hash；
- 提供页面同口径的规范化 contract facts。

### 4.3 Agent sidecar

新增独立可写数据库：

```text
09-工作台/modules/ads/derived/ads_agent_state.sqlite
```

最小表：

- `fact_ads_agent_run`
- `fact_ads_agent_stage`
- `fact_ads_agent_item`

运行头至少包含：

- `run_id`
- `child_asin`
- `data_as_of`
- `context_hash`
- `trigger`
- `model_version`
- `method_version`
- `schema_version`
- `status`
- `created_at`
- `completed_at`

原始广告库不回填 Agent 结果。

### 4.4 JSON 联调镜像

每次成功运行导出：

```text
09-工作台/modules/ads/derived/ads_agent_latest.json
```

SQLite 是权威来源，JSON 只用于前端联调和人工检查。

## 5. 顺序执行

每轮模型响应只开放一个合法工具。Runner 在上一步结束并校验成功后，才发起下一轮模型调用。

1. `get_ad_decision_context`
   - 读取身份、产品目标、广告结构、分归因窗口表现和证据。
2. `derive_required_ad_tasks`
   - 生成 B1 应有广告任务。
3. `map_tasks_to_ad_structure`
   - 生成 B2 任务与现有 Campaign/广告组/投放对象的结构对照。
4. `diagnose_advertising`
   - 生成 B3 诊断、优先级和 B3b 十类覆盖说明。
5. `propose_ad_adjustments`
   - 生成 B4 调整方案；规则未确认时禁止精确预算、竞价和广告位数值。
6. `submit_advertising_contract`
   - 完整校验并单事务落库、导出 JSON。

任何步骤失败均不得创建 completed run。

## 6. 契约门禁

### 6.1 通用门禁

- child_asin 与事实快照一致；
- context hash、数据版本、规则版本一致；
- B1→B2→B3/B3b→B4 的 ID 引用完整；
- evidence ids 必须属于当前 context；
- state、direction、priority、judgment mode 使用冻结枚举；
- Agent 不能修改确定性数字；
- verdict 与 because 不得出现免责声明、内部枚举或执行完成假话；
- 五阶段必须属于同一个 run。

### 6.2 归因门禁

- 同一 attribution block 内才允许计算销售额、ACoS 和 ROAS；
- 花费可以跨 block 汇总，但必须保留组成；
- 同时出现 7 天和 14 天归因时，顶层合计销售额、ACoS、ROAS 必须为空；
- Agent 不得在文案中引用不存在的“合计 ACoS”。

### 6.3 健康对象门禁

对 `B0B3MBYGR5`：

- 只允许 P2；
- 顶层方向必须 KEEP；
- 不允许 REQUEST_INFO、SPLIT、ADJUST 或虚构异常；
- 无问题必须明确作为正式结论落库。

### 6.4 Campaign 门禁

Campaign 级规则按 `(run_id, campaign_id, rule_id)` 唯一，只判断一次，不能按 Target 数量放大。

## 7. 工作台读取

广告前端请求方法不变。

`GET /api/ads/run?child_asin=...` 的职责调整为：

1. 读取该对象最新 `completed` Agent run；
2. context hash 匹配时返回真实 Agent stages；
3. 没有 run 时返回“尚未运行”，不得返回预制回放并标成 Agent；
4. hash 不匹配时返回“结果已过期，需要在本地重新运行”；
5. 返回 `source=Pi Agent`、run id、model version、created at 和 schema version。

P0 不通过浏览器触发 Agent。演示者先运行本地命令，再在页面点击“开始分析”读取结果。

## 8. 错误处理

- Pi 未配置：运行失败，不写 run。
- Pi 中途结束：保留审计日志，不写 completed 结果。
- Schema 或引用失败：提交工具返回明确错误，Agent可在同一步修正后重提。
- context hash 变化：旧结果仍保留但不作为当前结果返回。
- 数据库写失败：事务回滚，JSON 不更新。
- JSON 导出失败：run 不标 completed，避免数据库和 JSON 不一致。

## 9. 测试与验收

### 9.1 自动测试

- 事实桥输出稳定且不包含跨归因窗口伪合计；
- Agent 修改确定性数字会被拒绝；
- evidence 引用悬空会被拒绝；
- Campaign 规则不会按 Target 重复；
- incomplete run 对前端不可见；
- GET 没有 run 时明确返回尚未运行；
- GET hash 不匹配时返回过期；
- 现有广告页面无需 POST 仍能渲染真实 run。

### 9.2 真实 Pi 验收

- 清除 fake 模式；
- `B0B3LWGP36` 完整跑通一次，7/14 天输出保持隔离；
- `B0B3MBYGR5` 完整跑通一次，只产生 P2→保持；
- 精确记录工具顺序、模型版本、run id 和门禁重试；
- 数据库、latest JSON 和工作台 GET 返回相同 run id；
- 全量现有测试与新增广告测试全部通过。

## 10. 明确后置

- 外壳 JSON body 与正式 POST API；
- 浏览器触发的异步队列与跨刷新轮询；
- `/decide` 持久化；
- 执行交接；
- D+3/D+7 回流；
- A1 批量广告目的标签生成；
- 生产鉴权、多人审批、审计权限和调度系统。
