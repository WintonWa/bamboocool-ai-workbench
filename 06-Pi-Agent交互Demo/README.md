# Bamboocool 子 ASIN 预测 Agent Demo

独立本地 Demo：使用 Pi Agent SDK 和九个只读业务工具，完成“子 ASIN 未来 90 天逐日销量预测 → 库存三场景推演 → 补货建议”的完整演示。

首页采用移动优先的 Organic Soft-Tech / Liquid Glass 长页，先解释九步业务链路，再嵌入真实 Pi Agent 流式交互。详细视觉设计见 [Liquid Glass 长页设计](docs/2026-08-31-Pi-Agent-Liquid-Glass长页设计.md)，验收记录见 [长页 QA](docs/2026-08-31-Pi-Agent-Liquid-Glass长页-QA.md)。

## 当前能力

- 数据底座：`v0.3.0` SQLite；
- 全量商品：342 个子 ASIN；
- 历史颗粒度：每个子 ASIN 每天一行，共 730 天；
- 未来颗粒度：每个子 ASIN 每天一行，共 90 天；
- 完整场景：稳定成熟、广告增长、促销爆发、缺货失真、衰退积压；
- 预测方法：三个候选模型滚动验证，输出 P10/P50/P90；
- 库存方法：基准、压力、改善三种场景，输出风险日期与补货建议；
- Demo 门禁：任意子 ASIN 都会透明路由到五个完整样本之一。

Agent 严格按以下九个工具执行：

1. `route_demo_child_asin`
2. `get_child_product_context`
3. `audit_child_daily_history`
4. `reconstruct_child_demand`
5. `estimate_demand_drivers`
6. `forecast_child_sales_daily`
7. `get_child_inventory_supply`
8. `project_child_inventory_daily`
9. `recommend_child_replenishment`

前端只展示安全的执行摘要，不展示模型内部思维链、SQL、文件路径或工具原始 JSON。

## 工作台需求预测 Agent

工作台接入使用独立的十二步顺序链，不读取数据包里的预烤预测答案：

1. 审计历史逐日销量与缺货；
2. 读取历史广告、活动、价格和流量；
3. 读取未来 90 天广告、活动和价格计划；
4. 读取上架时长与供给背景；
5. 提交五类需求影响判断；
6. 由模型直接提交第 1–15 天逐日 P10/P50/P90；
7. 由模型直接提交第 16–30 天逐日 P10/P50/P90；
8. 由模型直接提交第 31–45 天逐日 P10/P50/P90；
9. 由模型直接提交第 46–60 天逐日 P10/P50/P90；
10. 由模型直接提交第 61–75 天逐日 P10/P50/P90；
11. 由模型直接提交第 76–90 天逐日 P10/P50/P90；
12. 校验并原子发布同一 `run_id`。

真实 Pi 运行：

```bash
npm run demo:demand-forecast -- B0B3LM36WB
```

HTTP 触发入口为 `POST /api/agent/demand-forecast`。同步入口保持兼容；页面可以不等待响应，改为轮询：

```text
GET /api/agent/demand-forecast/status?childAsin=B0B3LM36WB
GET /api/agent/demand-forecast/status?runId=<run_id>
```

状态接口的 run 和步骤统一输出 `加载中 / 完成 / 失败`，失败原因在 `run.error`；步骤只返回安全摘要，不暴露内部工具码。结果写入工作台
`modules/inventory/derived/forecast_agent.sqlite`；工作台只有在 90 天、五因子和步骤全部齐全时才使用 Agent run，否则明确回落到 v0.3.0 快照。库存余额、覆盖天数、断货、缺口和补货仍由工作台确定性计算。

## 工作台竞品 Agent V2

竞品 Agent 使用异步八步顺序链。模型只读取净化后的观察事实，不能读取预制场景、旧判断表、
V1 sidecar 或 `value_origin`；来源字段只由非模型写入器在提交时盖章。

页面接口：

```text
POST /api/agent/competitor/runs
GET  /api/agent/competitor/tasks/<task_id>
```

内部状态为 `queued → running → completed | skipped | failed`，页面把 `completed` 映射为
`done`。相同 `request_key` 复用同一任务；同一父 ASIN 严格串行，跨父 ASIN 默认最多并行三个。
最终十张业务表和 `completed` 状态在同一个 SQLite 事务内提交。

真实 Pi 单对象运行：

```bash
npm run demo:competitor-agent -- B0CJ9QLVPP
```

手动执行一次 priority/scheduled 周期：

```bash
npm run cycle:competitor-agent
```

V2 权威结果位于工作台：

- `modules/competitor/derived/competitor_agent_state_v2.sqlite`
- `modules/competitor/derived/competitor_agent_latest_v2.json`

旧 V1 文件只保留审计，不迁移、不读取、不回退。详细设计见
[竞品 Agent V2 任务服务设计](docs/superpowers/specs/2026-08-31-competitor-agent-v2-task-service-design.md)。

## 环境与启动

- Node.js `>=22.19.0`
- Python 3.10+
- 本机 Pi `0.84.2` 已完成模型与认证配置

```bash
npm install
npm start
```

打开 <http://127.0.0.1:18812/>。服务只绑定 `127.0.0.1`。

## 数据构建

源数据 `v0.2.2` 只读保留，构建脚本会在相邻目录生成完整的 `v0.3.0` 数据包：

```bash
npm run build:data
```

构建采用固定随机种子，先写入临时目录，通过全部质量门禁后再替换 `v0.3.0`。用户已明确不要求哈希校验，因此测试采用只读连接和结构/业务约束校验。

## 测试

```bash
npm test
```

默认测试覆盖数据契约、九个工具、Demo 路由、HTTP 流式事件和前端脚本，不调用模型。

真实 Pi 冒烟测试会调用本机默认模型：

```bash
npm run smoke
```

## 数据边界

- 父级历史事实来源于 `v0.2.2`；子级日数据包含确定性分配与演示构造，需以 `value_origin` 区分；
- 未来广告、价格、促销与供给计划为 Demo 输入；
- 预测、库存投影和补货建议为 `model_derived`；
- Demo 映射会明确告知，不能视为任意子 ASIN 的真实专属预测；
- 本项目不应直接用于真实采购承诺。

详细设计见 [子 ASIN 数据设计](docs/superpowers/specs/2026-08-30-child-asin-demand-forecast-data-design.md) 和 [实现计划](docs/superpowers/plans/2026-08-30-child-asin-agent-implementation-plan.md)。
