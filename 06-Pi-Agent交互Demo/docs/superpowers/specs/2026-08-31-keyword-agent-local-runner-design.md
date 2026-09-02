# 关键词 Agent 本地 Runner 设计

日期：2026-08-31  
状态：已批准  
范围：Bamboocool 关键词模块 P0 Demo

## 1. 目标

构建一个使用本机 Pi 配置的真实关键词 Agent。Agent 针对现有关键词数据完成运营角色、市场事件、覆盖事件、证据结论和日报文案判断，经过逐阶段契约门禁后发布给现有工作台读取。

P0 不追求预测或判断绝对准确，重点验证：

- Pi 按真实业务顺序工作，而不是并行调用固定工具；
- 模型只判断定性字段，不改写确定性数字和对象引用；
- 1991 个关键词均有逐词角色判断；
- 现有三个页面可以直接读取发布结果；
- 失败或未完成运行不会污染当前可见结果。

## 2. 冻结决策

### 2.1 角色直接写现有列

关键词角色不新建业务表。运行结果直接写入 `dim_keyword_term`：

- `operator_role`
- `operator_role_label`
- `operator_role_seed_word`
- `operator_role_confirmed`

页面和现有六个 GET 路由已经消费这些列，因此无需增加新的前端载荷形状。

### 2.2 `operator_role_confirmed` 的语义

`operator_role_confirmed` 只表示人工确认：

- Agent 自动判断的角色默认写 `0`；
- 命中客户角色种子只写入 `operator_role_seed_word`，不自动代表人工确认；
- `operator_role_confirmed=1` 时，`operator_role` 不得为 `unset`；
- 页面不得显示“未定角色（已确认）”。

一次完整运行后，`unset` 只表示尚未处理或运行失败。证据不足但已经完成判断的词写为 `pending_validation / 待验证词`。

### 2.3 本期边界

- J2b 运营角色属于 P0，不后置。
- J3 只处理现有页面已消费的 `second_source_note`；两来源必须并列，不能合并数值。
- J3 的完整竞争结构解释没有页面槽位，后置。
- J8“该词承担的业务作用”没有页面槽位，后置。
- 覆盖结构统计、位置聚合、词组分权、最终优先级排序和日报卡片数字继续由页面或确定性程序计算。

## 3. 数据与发布架构

归档基库保持不变：

`07-关键词分析模块/02-数据构建/v0.1.0/keyword_demo.sqlite`

Runner 每次从归档基库或当前 completed 版本建立同结构运行副本，在副本内更新现有角色列和 A–E 业务表。全部阶段通过后，原子发布为：

`09-工作台/modules/keyword/derived/keyword_agent_current.sqlite`

独立运行 sidecar：

`09-工作台/modules/keyword/derived/keyword_agent_state.sqlite`

sidecar 只保存运行台账、阶段状态、context hash、模型版本、数据版本、错误和完成时间，不复制关键词业务结果。工作台优先只读 current；current 不存在时回退归档基库。

latest JSON 仅用于联调观察，不作为页面权威来源。

## 4. Agent 与工具顺序

CLI：

```text
npm run demo:keyword-agent -- --scope all
```

每轮只开放当前阶段工具：

1. `get_keyword_run_context`
   - 冻结数据版本、规则版本、参数、词范围、子 ASIN 范围和 context hash。
2. `submit_operator_role_batch`
   - 每批 50–100 词，直到 1991 词全部覆盖。
3. `submit_market_event_batch`
   - 生成 C 市场变化事件的定性字段。
4. `submit_coverage_event_batch`
   - 生成 D 覆盖变化事件的定性字段。
5. `submit_evidence_batch`
   - 按子 ASIN 分批生成 A 证据判断。
6. `submit_daily_report_contract`
   - 生成 B 五个答句并选择可解析的证据引用。
7. `build_audit_records`
   - 确定性聚合 A 的结果生成 E，不调用模型判断。
8. `commit_keyword_contract`
   - 完成全局引用、文案、数字和发布门禁，原子切换 current。

## 5. 模型可判断与不可修改字段

### 5.1 角色

模型输出：`operator_role`。Runner 映射中文标签并设置 `operator_role_confirmed=0`。`operator_role_seed_word` 来自输入事实，模型不可改写。

允许角色：

- `core / 核心词`
- `explore / 探索词`
- `longtail / 长尾词`
- `pending_validation / 待验证词`

completed 运行不允许 `unset`。

### 5.2 A 证据结论

模型判断：`evidence_type`、原始 `priority`、`conclusion`、`main_basis`、`evidence_completeness`、`next_verification`、`competitor_verification_state`、市场事件引用、覆盖事件引用。

Runner 分配 ID、映射标签并锁定关键词、子 ASIN、pair、产品目标、库存限制、日期和规则版本。

### 5.3 B 日报

模型输出 Q1–Q5 中文答句并选择引用。流量代理值、环比、比较基期、事件计数和优先级重排由程序锁定。

答句必须与当前参数口径和页面结构化数字一致：

- Q3 与 `fact_keyword_coverage_event` 当前统计一致；
- Q4 明确使用当日或全窗口口径，不混写；
- Q1 随 `kw.compare` 改变比较周期措辞；
- Q5 使用页面当前权重重排后的前三项。

### 5.4 C/D 事件

模型只输出 `event_type`、`continuity` 和中文 `label`。快照 ID、日期、数值、变化率、位次、采集状态和对象引用全部由工具锁定。

周线与月线不能互折；关键词2和关键词3不能跨来源合并；`collect_failed`、`beyond_depth` 和 `not_covered` 必须保持不同语义。

### 5.5 E 盘点

E 的统计字段全部由 Runner 从当前 A 和位置事实确定性汇总。模型不参与。

## 6. 错误处理与一致性

- 运行开始先写 `status=writing`；只有所有阶段和发布成功后改为 `completed`。
- 任一批次失败，current 保持旧版本，运行标记 failed。
- 角色四列在同一事务更新，不允许半行发布。
- context hash 覆盖数据版本、规则版本、角色种子、判断输入和影响判断的 `kw.*` 参数。
- 输入变化后旧运行保留，但不能冒充当前结果。
- 页面只认 current 业务库和 completed 台账，不读半成品。

## 7. 验收对象与门禁

黄金对象：

- `kw_00001 / mens underwear`：验证双来源冲突和 `second_source_note`。
- `kw_00087 / boxer briefs for men pack cotton`：验证旧的 unset + seed + confirmed 怪值被消除。
- `kw_00085 / men hanes underwear`：验证无 seed 的角色判断。
- `B0CBPXNC1M`：验证未覆盖、超采集深度和采集失败不混淆。
- `B0B3LWGP36`：验证真实锚点与词组缺口可以同时成立。

必须通过：

- 1991 词一词一行、ID 唯一、码值与标签一致；
- completed 运行无 `unset`；
- `confirmed=1` 只来自已有人工确认且角色非 unset；Agent 新判断默认 confirmed=0；
- A 对 C/D、B 对 A/D 的引用全部可解析；
- 模型不能修改确定性数字、日期、对象和来源；
- 周/月和两来源不混算；
- Q1–Q5 与页面当前参数和结构化数字一致；
- 渲染结果不出现内部枚举与“未定角色（已确认）”；
- 未完成运行不发布；发布失败不改变旧 current；
- 现有关键词接入、渲染、路由和参数测试全部通过。

## 8. P0 非目标

- 浏览器点击启动 Agent；
- J8 业务作用判断；
- J3 完整竞争结构文案；
- 自动把 Agent 判断标成人工确认；
- 重做关键词页面视觉或新增业务板块。
