# 需求预测 Agent 职责恢复设计

日期：2026-08-31  
状态：待用户书面确认  
依据：`01-方案与数据需求/12-需求预测Agent职责修订.md`、`00-通用方法与规范/07-Agent运行与落库口径.md`、`01-方案与数据需求/11-预测判断Agent落表与调用接口.md`

## 1. 目标与非目标

目标是撤下当前错误的“只解释数据包预烤预测”的 `forecast-judgment` 链，恢复完整需求预测 Agent：它从真实业务中客观存在的历史事实和未来运营计划出发，一次运行同时产出未来 90 天逐日 `p10 / p50 / p90`、五类影响判断及真实执行步骤。工作台使用同一 run 的预测数字和理由继续计算库存余额、覆盖天数、断货日、缺口量、补货建议与风险。

以下内容不在本次回退范围：

- 已跑通的库存盘点结论 Agent、`verdict_agent.sqlite` 及五条结论契约；
- 产品销售库存 v0.3.0 数据包本身；
- 广告、关键词和竞品 Agent；
- “影响项乘回基线必须逐日重建 p50”的门禁，本轮按职责修订明确不做。

## 2. 回退边界

当前错误链包括 Pi 服务的 `/api/agent/forecast-judgment`、`forecast-judgment-agent.ts`、`forecast-judgment.ts`，以及工作台的 `forecast_judgment.py`、`run-forecast-judgment` 任务和“90 天序列始终来自数据包”的读取优先级。

实施时不直接删除已有错误运行数据。现有 `forecast_agent.sqlite` 与 `forecast_agent_latest.json` 先改名归档为 legacy 产物，工作台停止读取它们。新链确认成功前，页面回落到 v0.3.0 快照，不能出现半份新预测。

这不是把代码简单恢复到 Git 中的九工具版本。旧九工具链的 `forecast_child_sales_daily` 仍直接读取 `fact_child_forecast_daily`，同样违反新职责。可复用它的交互壳、顺序工作流和库存下游工具，但需求预测输入与预测提交必须重写。

## 3. 职责边界

### 3.1 Agent 输入

事实加载器必须使用显式列清单，不得 `SELECT *`。允许读取：

- `fact_child_sales_daily`：`units_sold / orders / average_selling_price`；
- `fact_child_inventory_daily`：期初/期末可售、入库和 `stockout_flag`；
- `fact_child_advertising_daily`：预算、花费、展示、点击、订单、销售额及业务后台已有比率；
- `fact_child_promotion_daily`：活动身份、类型、状态、折扣和是否计划；
- `fact_child_price_daily`：标价、售价、Coupon、折扣和价格事件；
- `fact_child_traffic_daily`：sessions、page views、buyers、cvr；
- `dim_child_lifecycle_history`：只取最早 `effective_start` 作为上架日；
- 三张未来计划表：只取计划预算/花费/流量、活动排期/折扣、未来价格计划；
- 库存快照、库存政策和未来供给事件，仅作为需求承接上下文。

事实工具可以做中性的窗口聚合、同比/环比和事件窗口切片，以控制上下文长度；不得预先给出“干净基线”“生命周期阶段”“活动抬升”“缺货损失”或模型选择等判断答案。每个摘要值必须能回溯到允许列。

### 3.2 Agent 禁读

禁读清单以职责修订 §5 为准，至少包括：

- `fact_child_forecast_daily` 全部预测及因子列；
- `feature_child_demand_daily`；
- `fact_child_forecast_evaluation`；
- `lost_sales_units / potential_demand_units / coverage_days`；
- 生命周期阶段、变化理由和置信度；
- `preset_uplift / performance_index / expected_effect_ratio`；
- 所有 `quality_status / value_origin / method_version / provenance` 构造元数据。

代码门禁扫描事实查询和返回载荷中的禁读字段；命中即使模型未使用也判运行失败。

### 3.3 Agent 输出

同一个 `run_id` 原子产出：

1. 连续 90 天的 `p10_units / p50_units / p90_units`，可选 `baseline_units`；
2. `stockout_distortion / promotion / lifecycle / advertising / seasonality` 五项判断，包含 Agent 排序、固定中文状态、影响幅度、中文依据和原始事实数字引用；
3. 真实工具执行步骤，包含中文 `label / detail / status / duration_ms / sources[]`。

Agent 不输出库存余额、覆盖天数、安全线突破日、断货日、缺口、超量、最晚补货日、补货量、承接能力或库存风险。

## 4. Agent 顺序工作流

同一模型会话每轮只开放下一项合法工具。推荐流程：

1. `route_forecast_child`：确认或演示路由分析对象；
2. `load_sales_inventory_history`：读取实销与可售历史；
3. `load_demand_driver_history`：读取广告、活动、价格和流量历史；
4. `load_future_operating_plan`：读取未来广告、活动和价格计划；
5. `load_product_tenure_and_supply_context`：读取上架日、库存政策和供给上下文；
6. `submit_demand_assessment`：提交五类判断的阶段性草案，仅保存在运行内存；
7. `submit_daily_forecast`：提交 90 天逐日区间；
8. `validate_and_commit_forecast_run`：执行全量门禁，零错误时单事务落库。

任何工具失败或门禁不通过时不写 completed run。模型可在当前提交工具上根据错误重试，但不能跳步或回写前一步事实。

## 5. 落库设计

权威 sidecar 仍使用工作台 `modules/inventory/derived/forecast_agent.sqlite`，但采用新 schema。旧同名库先归档，不能混用两代语义。

### 5.1 `fact_child_forecast_agent_run`

关键字段：

`run_id, child_asin, run_date, actual_run_date, data_as_of, horizon_days, trigger, model_version, prompt_version, method_version, comparison_snapshot_run_id, prev_run_id, confidence, confidence_reason, judgment_summary, status, created_at, completed_at`

- `run_id` 使用 `<child_asin>-<run_date>-<seq>`；同对象同日递增；
- `run_date` 是业务基准日，`actual_run_date` 是墙上运行日，消除旧格式中两个日期含义混杂；
- `created_at / completed_at` 一律 ISO 8601 带 `+08:00` 偏移；
- 页面只读 `status='completed'`；
- `prev_run_id` 必须指向同对象上一条 completed run，首次为 null；
- `comparison_snapshot_run_id` 仅表示并排对照的数据包快照，不暗示 Agent 读取了预烤预测。

### 5.2 `fact_child_forecast_agent_daily`

采用职责修订 §6.2 的字段：`run_id / child_asin / forecast_date / p10_units / p50_units / p90_units / baseline_units`，主键为 `(run_id, forecast_date)`。

### 5.3 `fact_child_forecast_judgment_factor`

保留五项固定 `factor` 和中文状态词表，但 `numbers` 只能引用允许输入中的可观测事实。禁止继续使用预烤季节因子、生命周期因子、未来预期效应或丢失销量。

### 5.4 `fact_child_forecast_agent_step`

字段为 `run_id / step_seq / tool / label / detail / status / duration_ms / sources`，主键 `(run_id, step_seq)`。步骤与预测结果同事务发布，使“跑于……”可回看真实过程。

写入顺序为 daily、factor、step 子表，最后插入 completed run 头；或先写 running run 头，提交前更新为 completed。任一方式都必须保证失败运行对页面不可见。

## 6. 工作台读取与库存下游

`forecast.py` 按以下顺序取数：

1. 找该子 ASIN 最新 completed Agent run；同一 `run_date` 内在应用层解析带偏移时间选择最新；
2. 校验 run 有 90 个连续日期且逐日 `0 ≤ p10 ≤ p50 ≤ p90`；
3. 合格时图表与需求序列使用 Agent daily，同一 run 的 factor 用于需求判断带；
4. 不合格、无 run 或 sidecar 不可读时，完整回落 v0.3.0 快照，并明确标“上一次快照”；
5. `compute.build_projection()` 及库存下游继续消费统一 demand 形状，不复制预测公式。

页面不得把 Agent 数字与快照因子混用。来源标必须区分“Agent 预测 · 跑于……”和“上一次快照 · as_of……”。Agent 因子保持 `ord`，工作台不重排。

库存盘点结论 Agent 可以继续引用工作台计算后的覆盖、断货和费用数字，但新的盘点 run 应记录它消费的需求预测 run_id；已有盘点结果不删除。

## 7. 错误处理与兼容

- Pi 不可用、超时、工具失败、90 天缺行或契约不合：不发布新 run，页面保留上一条 completed 或快照；
- 输入对象不在产品脊椎：运行前失败，不创建 run；
- 模型提交负数或 `p10 > p50 > p90`：提交工具返回逐日错误，允许重试；
- 禁读字段泄漏：整次运行失败，错误必须指出表和字段；
- 旧 legacy DB 只保留审计，不参与最新选择；
- sidecar 原地写，不采用“删库重建”，避免工作台连接池继续读取旧 inode；
- API 和页面只显示中文来源与状态，内部表名、factor 码值及构造元数据不上屏。

## 8. 验收与测试

### 8.1 静态与单元门禁

- 允许列清单逐表测试；禁读表/字段扫描零命中；
- 90 行、连续日期、非负和分位顺序门禁；
- 五项齐全、状态词表、ord 唯一、数字引用可回溯；
- 时间戳带偏移，混合旧格式读取仍能正确选择最新；
- 同对象同日连跑两次，seq 递增、两条并存、prev_run_id 可 JOIN；
- 模拟第 N 条写入失败，页面仍读取上一次 completed；
- Agent 与快照两种来源可区分；
- 修改库存参数只重算库存下游，不重跑需求 Agent；
- 库存盘点结论 Agent 现有测试保持通过。

### 8.2 真实 Pi P0

先跑一个黄金子体，再扩到五个黄金子体：

- 真实 Pi，禁用 fake mode；
- 精确断言八步调用顺序；
- 输出 90 天 daily、五项 factor 和步骤表；
- 数据库、latest JSON、工作台 API 三方 run_id 一致；
- 工作台图表使用 Agent p50，库存断货和覆盖由工作台重新计算；
- 暂时移走 sidecar 后页面回落快照且不报错；
- 运行日志证明事实载荷不含职责修订 §5 的任何禁读字段。

本轮不以“与预烤快照接近”作为正确性门禁。快照仅供演示对照；预测不同必须由同 run 的可观测事实依据解释。

## 9. 实施顺序

1. 固定当前错误链和旧 DB 的 legacy 清单；
2. 撤下旧端点、工作台任务和读取优先级，确认页面回落快照；
3. 建新 schema、允许列事实加载器和静态禁读门禁；
4. 实现八步 Pi workflow、提交验证和原子 writer；
5. 接入工作台 Agent daily/factor/step 读取与来源标；
6. 跑自动测试、真实 Pi 单对象 smoke 和前端 API 验收；
7. 验收通过后再决定是否扩到五个或 342 个子体。

