# 广告分析模块 v0.1.0-slice 独立复验报告

验收日期：2026-08-29  
数据包：`/Users/linsen/BAM/04-广告分析模块/02-数据构建/v0.1.0-slice`  
契约：`bamboocool-advertising-acceptance-v1` / `1.0.0`  
验收模式：`vertical_slice`

## 总体结论：PASS

本次回修已关闭原有 3 个 P0 项：五类 ASIN 来源角色完整、manifest 最小声明完整、13/13 场景可按步骤独立复演。自动契约、原始报表回算、SQLite/JSON/前端同源、血缘和文件哈希均通过。

纵向切片门禁现可放行批量生成。该结论不等同于 release 验收；完整 521 子 ASIN、54 名称键广告组生成后，仍须以 `--mode release` 重新执行独立验收。

## 验收结果摘要

| 检查面 | 结果 | 独立证据 |
|---|---|---|
| 自动契约 | PASS | 58/58 断言通过；AD-01～AD-11、VS-00～VS-03 全部 PASS |
| 五类来源角色 | PASS | promoted 165、positive_spend 142、purchased 1、target 1、matched 1 |
| manifest | PASS | 顶层与逻辑 manifest 的 9 个冻结字段完整且一致 |
| 场景复演 | PASS | 13/13 含 steps 和 expected_results，13/13 独立复演通过 |
| source_lineage | PASS | 非 scenario_added 435/435 显式连接有效 source_file_id，连接率 100% |
| SQLite / JSON 同源 | PASS | 20/20 冻结逻辑产物逐行归一化一致 |
| 前端同源 | PASS | 页面一、页面二 63/63 个嵌套记录与逻辑表一致 |
| 交付文件哈希 | PASS | manifest 登记的 10/10 个文件 SHA-256 与字节数一致 |
| 原始报表回算 | PASS | 6 个 SP 精确日事实重新聚合，最大绝对差约 1.02e-11 |

## 自动契约结果

复验命令：

```bash
python3 "/Users/linsen/BAM/04-广告分析模块/03-验收/run_acceptance.py" \
  --dataset "/Users/linsen/BAM/04-广告分析模块/02-数据构建/v0.1.0-slice" \
  --mode vertical_slice \
  --output "/Users/linsen/BAM/04-广告分析模块/03-验收/latest_result.json"
```

结果为 58/58 `PASS`。机器输出见 [latest_result.json](/Users/linsen/BAM/04-广告分析模块/03-验收/latest_result.json)。以下复核均独立于构建器写入的 `assertion_status`。

## 三项回修复验

### 1. 五类来源角色与真实 target_asin：PASS

`bridge_ad_object_product` 当前包含：

| relation_role | 关系行数 | 角色边界 |
|---|---:|---|
| promoted_asin | 165 | 仅由 direct `advertising_asin` 证据建立 |
| positive_spend_asin | 142 | 由正花费产品角色建立，不反推推广关系 |
| purchased_asin | 1 | `unattributed`，来源角色为 `purchased_asin` |
| target_asin | 1 | `unattributed`，来源角色为 `targeting_asin` |
| matched_asin | 1 | `unattributed`，来源角色为 `matched_target_asin` |

新增目标 ASIN 关系为：

- 广告对象：`grp_37192cb0b75a711d`；
- 目标 ASIN：`B086L79Q6X`；
- 来源：`13.广告/商品推广_投放_报告.xlsx|target_asin|row=11`；
- 原表 Excel 第 11 行的 `asin`、广告活动和广告组与构建关系一致；
- `is_scope_product=0`，没有将外部投放对象冒充客户推广商品。

`SOURCE_ROLE_BOUNDARY` 场景现在链接五条不同角色样例；非 promoted 角色均未使用 `advertising_asin` 来源角色。AD-02 的五类边界已能完整演示。

### 2. manifest 顶层和逻辑字段：PASS

`manifest.json` 顶层和逻辑 `dataset_manifest` 均包含并对齐以下冻结字段：

```text
dataset_stage = vertical_slice
selected_parent_asins = 5 个冻结父 ASIN
expected_child_count = 521
expected_ad_group_name_key_count = 54
amazon_fact_window_start = 2026-07-01
amazon_fact_window_end = 2026-07-31
timezone = source-local
currency = USD
seed = 20260829
```

逻辑 manifest 采用 SQLite 的字符串化 JSON 表达数组，不改变字段含义，验收读取稳定。

### 3. 13 个场景逐步复演：PASS

13/13 场景均有非空 `steps` 和 `expected_results`，步骤序号连续，引用对象全部存在。逐场景独立复演结果：

| 场景 | 结果 | 关键观察 |
|---|---|---|
| SOURCE_ROLE_BOUNDARY | PASS | 五类角色齐全且来源角色不互相升级 |
| SHARED_AD_OBJECT | PASS | 同一广告对象连接 5 个子体，保持 shared |
| PAGE1_FILTER_COMPARE_ANOMALY | PASS | 3 个广告组、7 天归因、同窗比较；异常均由启用规则产生 |
| LABEL_VERSION_CHANGE | PASS | 旧标签 07-15 结束，新标签 07-16 生效，无重叠 |
| NO_ANOMALY_RULE | PASS | 关闭异常规则后仍返回结果，异常数为 0 |
| PAGE2_END_TO_END | PASS | 五类证据及广告表现连接任务、结构对照、诊断、建议和决定 |
| INVENTORY_CONSTRAINT | PASS | 在库与在途分离，前置任务为 DEFER，未给精确值 |
| UNCONFIRMED_RULE_NO_PRECISE_VALUE | PASS | 4 条未确认规则建议 exact_value 均为空，含条件、风险、D+3/D+7 |
| DECISION_ACCEPT | PASS | 已接受并进入 handed_off |
| DECISION_MODIFY | PASS | 修改后进入 ready，并保留前序计划与 D+7 反馈链接 |
| DECISION_REJECT | PASS | 已拒绝，含原因且未执行 |
| DECISION_DEFER | PASS | 已暂缓，含原因且未执行 |
| REVIEW_FEEDBACK_LINK | PASS | D+3/D+7 反馈可解析，当前修改事件指向 D+7 反馈 |

## 血缘、同源和回算复核

### source_lineage

- 总血缘行：470；
- 非 `scenario_added`：435/435 通过 `source_file_id` 显式连接到有效 `source_file`，连接率 100%；
- 其中 direct：371/371，derived：64/64；
- 其余 35 行全部为 `scenario_added`，按契约使用场景引用，不要求伪造原始文件连接；
- 新增 target_asin 关系的血缘连接到 `src_617e27deda32cc1f`。

此前“主要依赖 source_ref、未连 source_file 主键”的风险已关闭。

### SQLite、验收 JSON 与前端 JSON

- SQLite 有 21 张表，包含 20 个冻结逻辑产物和额外的 `source_file`；
- 对 20 个冻结逻辑产物进行 JSON 字段解析、字段排序和记录排序后，SQLite 与 `acceptance_export.json` 的行数及逐行内容完全一致；
- 页面一、页面二前端 JSON 共比较 63 个嵌套记录，均与对应逻辑表记录一致；
- 页面一未出现产品目标、策略优先级、诊断、任务、预算/竞价/暂停建议等页面二策略字段；页面二保持“子 ASIN × 目标版本 × 决策时点”粒度，没有退化为广告组查数宽表。

### 哈希和原始报表回算

- manifest 登记的 10 个交付文件，SHA-256 和字节数 10/10 与实际文件一致；
- 从 `商品推广_搜索词_报告.xlsx` 独立筛选前窗 2026-07-01～07-15 与当前窗 2026-07-17～07-31，对 3 个 SP 广告组的 6 条精确日事实重新聚合展示、点击、花费、订单和广告销售；最大绝对差约 `1.02e-11`，属于浮点表示误差；
- CTR、CPC、CVR、ACoS、ROAS 均可从分子分母复算；SP 7 天、SB/SD 14 天归因边界保留。

## 门禁状态

| 门禁 | 状态 | 说明 |
|---|---|---|
| VS-00 契约与范围 | PASS | manifest、五类来源角色、血缘和切片范围均通过 |
| VS-01 页面一切片 | PASS | 筛选、比较、标签版本、异常规则和无异常场景可复演 |
| VS-02 页面二切片 | PASS | 证据、任务、结构、诊断、建议和库存约束链可复演 |
| VS-03 决定与反馈 | PASS | 接受、修改、拒绝、暂缓及 D+3/D+7 回流可复演 |

## 遗留边界（非失败项）

- 本次验收对象仍是纵向切片，实际覆盖 39 个子 ASIN、28 个广告组；521 子、54 名称键广告组是 release 目标，不应在切片阶段伪称已生成完成。
- `source_file` 是血缘支持表，不属于冻结的 20 个前端/验收逻辑产物，因此未在 `acceptance_export.json` 中重复导出不构成失败。

## 放行决定

最终状态：`PASS`。无阻塞批量生成的最小修复项；构建 Agent 可以继续批量生成 release。release 交付后必须重新执行全量数量、覆盖、唯一键、来源边界、同源、哈希、场景和原表回算验收，不能沿用本次切片结论。
