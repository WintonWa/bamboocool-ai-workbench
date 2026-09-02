# 关键词 Agent 本地 Runner V2 设计

日期：2026-08-31  
状态：已批准  
范围：Bamboocool 关键词模块 P0 Demo

## 1. 权威契约

实现以关键词模块 `08-给Agent侧的完整交底.md`、`05-Agent输出面交底.md`、数据字典和接口样例为模块契约；冲突时以 `00-通用方法与规范` 下的 Agent 需求、运行落库和模块接入规范为准。

旧版把 `operator_role` 当成模型产出并读取五张旧判断表作为候选骨架，均属无效实现。V2 不继承这些判断、行数分布或文案。

## 2. 运行链

真实 Pi 严格顺序执行：

1. 冻结数据、参数、允许输入范围和 context hash；
2. C：从市场逐期快照生成候选，模型判断市场变化或返回 `null`；
3. D：从关键词×子 ASIN 的逐日自然位/广告位生成候选，模型判断覆盖变化或返回 `null`；
4. A：按 901 个关键词×子 ASIN 关系读取产品目标、词角色、库存承接、当前位置和本 run 事件，模型生成证据或返回 `null`；
5. B：根据流量事实、本 run 事件和证据生成日报契约；
6. E：工具从本 run 的证据和位置事实确定性汇总盘点记录；
7. 全局门禁通过后原子发布。

每轮只开放当前阶段工具。Agent 不输出隐藏思维链，只通过结构化工具参数提交判断与依据。

## 3. 输入边界

- `fact_keyword_evidence`、`fact_keyword_daily_report`、`fact_keyword_market_change_event`、`fact_keyword_coverage_event`、`fact_keyword_audit_record` 整表禁读，包括旧 ID、旧条数和旧引用。
- 事实桥按列白名单读取其余输入表；禁止读取 `value_origin`、构造 `rule_version`、建议出价、成文不可比原因和覆盖形态标签。
- 经批准的 Demo 例外输入包括产品目标、生命周期、库存承接，以及 `library_status` / `operator_role`。读取角色即意味着 J2b 不再是本 Agent 的判断点。
- J3 完整竞争结构解释和 J8 业务作用没有正式字段，本期不落库、不借用其他字段承载。

## 4. 输出与门禁

模型产出 A/B/C/D 契约字段；对象身份、日期、快照、数值、变化率、中文标签和版本由工具锁定或映射。`null` 是正式结果，不以固定行数或类型分布验收。

门禁检查：枚举、对象完整覆盖、引用只指向本 run、文案长度、中文上屏、数字不改写、变化方向、跨来源与周/月不混算、SQLite 完整性。E 的 `evidence_count` 与 `evidence_type_counts` 必须等于本 run A 的聚合结果。

## 5. 发布协议

业务结果写入 `keyword_agent_current.sqlite`：它是 24 张原表的完整副本，五张判断表内容替换为本 run 产出，并增加 manifest。运行账本写入 `keyword_agent_state.sqlite`。

只有以下条件同时成立页面才读取 Agent 结果：

- manifest completed；
- ledger 同 run completed；
- 两侧 context hash 相同；
- manifest 参数与当前页面六项判断参数一致。

写入顺序为：完成运行副本和 manifest → 保存不可变 completed 文件 → 账本 completed → 原子切换 current。失败或半份结果不改变旧 current。

run 头记录 `run_id`、`run_date`、`data_as_of`、数据/规则/模型版本、`prev_run_id`、带 `+08:00` 的时间戳、状态与错误。历史 run 只追加不覆盖。

## 6. 验收

- 契约泄漏审计零失败；
- 页面选库往返测试 16 条全过；
- 单元测试证明角色列不变、五张旧判断表没有被事实桥读取、`null` 可提交、引用和原子发布门禁有效；
- 当前 P0 Demo 只要求真实 Pi Agent Loop 能启动，并按严格顺序进入至少一个业务判断批次；
- 本阶段不要求 full-scope run 完成，不要求发布 `current`，也不以最终五表结果作为阻断验收项；
- 工作台六路由读取同一 run、两个演示对象下钻和完整结果发布改列后续增强；
- 无论 Loop 在何阶段停止，半份结果都不得被页面读取。
