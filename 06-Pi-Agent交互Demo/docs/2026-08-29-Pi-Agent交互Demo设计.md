# Bamboocool Pi Agent 交互 Demo 设计

日期：2026-08-29

状态：V1 已实现并完成自动测试、真实 Pi 冒烟测试与浏览器验收

目标目录：`06-Pi-Agent交互Demo/`

## 1. 目标

建立一个与现有 Bamboocool 前端 Demo 完全隔离的本地交互 Demo，验证一条真实 Agent 链路：

1. 用户选择父 ASIN，提出“预测未来 90 天销量”；
2. Pi 根据专用 Skill 自主调用受限业务工具；
3. 工具只读查询 `v0.2.2` SQLite，并执行透明的 Demo 预测；
4. 页面流式展示实际发生的工具步骤和最终回答；
5. 回答明确区分客户事实、派生结果和演示假设。

V1 的成功标准是交互链路真实、稳定、可解释，不是预测精度达到生产要求。

## 2. 术语

页面展示的过程称为：

- `Agent execution trace` / `Agent activity timeline`：Agent 执行轨迹；
- `Tool-call trace`：工具调用轨迹；
- `Reasoning summary`：面向用户的简短判断摘要。

页面不展示模型原始 `Chain of Thought`。用户看到的是可验证的工具动作、数据来源、简短结果摘要和最终答案。

## 3. 已确认的运行条件

- 本机 Pi 版本：`0.84.2`；
- 已安装包：`@earendil-works/pi-coding-agent@0.84.2`；
- 模型与认证已配置在本机 Pi Agent 目录；
- V1 只在演示者本机运行，不部署、不支持远程多用户；
- 模型供应商不写入场景业务逻辑，由 Pi 本机配置决定；
- 本机 Node.js 为 `v25.6.1`；Pi `0.84.2` 要求 Node.js `>=22.19.0`；
- 数据源固定为：
  `../02-产品销售库存模块/02-数据构建/v0.2.2/bamboocool_product_sales_inventory_v0.2.2.sqlite`；
- 数据库统一业务截止日为 `2026-08-03`，但工具必须按对象返回自己的实际最新日期；
- 第一条黄金场景只支持父 ASIN，不承诺子 ASIN 逐日预测。

## 4. 范围

### 4.1 V1 包含

- 一个独立的本地网页；
- 一个固定场景：父 ASIN 未来 90 天销量预测；
- 五个父 ASIN 的选择入口；
- 真实 Pi Agent 会话；
- 四个只读业务工具；
- 一个专用 Skill；
- 流式答案与执行轨迹；
- 当前会话内的简单追问；
- 停止、重新运行和清空对话；
- 数据来源与派生状态标记；
- 成功、缺数据、未知 ASIN、模型错误、工具错误、服务错误和用户取消状态。

### 4.2 V1 不包含

- 子 ASIN 的 90 天预测；
- 通用自然语言查库或任意 SQL；
- 生产级预测算法、自动调参和准确率评估；
- 促销、活动、季节、价格、广告变化等外生变量建模；
- 多场景编排器、多个 Agent 或子 Agent；
- 会话持久化、历史会话列表、用户账户和权限系统；
- 云部署、外网访问和远程共享；
- Agent 写库、修改业务数据或执行运营动作；
- 全局 Pi Extension、全局 Skill 或文件系统工具的自动加载；
- 原始思维链展示。

## 5. 总体架构

```text
浏览器页面
   │  同源 POST + NDJSON 流
   ▼
本地 Node 服务（127.0.0.1:18812）
   ├── 静态页面
   ├── 场景注册表
   ├── Pi 会话适配器
   ├── Pi 事件适配器
   └── 四个只读业务工具
              │
              ▼
        v0.2.2 SQLite（只读）
```

独立 Node 服务同时提供页面和 Agent API，因此无需 CORS、反向代理或第二个业务服务。现有 `03-前端Demo`、`04-UICraft测试` 和其他 Demo 不被引用或修改。

Pi 通过 `@earendil-works/pi-coding-agent` SDK 嵌入。模型运行时读取本机认证与模型配置；资源加载器只加载本 Demo 明确指定的场景 Skill 和工具。每个浏览器会话使用一个内存 Agent Session，前端用随机 `sessionId` 关联追问。会话空闲 30 分钟后过期，服务最多保留 10 个会话；超过上限时淘汰最久未使用的会话。刷新或清空对话时允许创建新会话并释放旧会话。

## 6. 建议目录

```text
06-Pi-Agent交互Demo/
├── README.md
├── package.json
├── docs/
│   └── 2026-08-29-Pi-Agent交互Demo设计.md
├── src/
│   ├── server.ts
│   ├── config.ts
│   ├── database.ts
│   ├── pi-session.ts
│   ├── event-adapter.ts
│   ├── scenarios/
│   │   ├── index.ts
│   │   └── forecast-parent-90d.ts
│   └── tools/
│       ├── product.ts
│       ├── sales.ts
│       ├── inventory.ts
│       └── forecast.ts
├── skills/
│   └── forecast-parent-90d/
│       └── SKILL.md
├── web/
│   ├── index.html
│   ├── app.js
│   └── app.css
└── tests/
    ├── tools.test.ts
    ├── event-contract.test.ts
    ├── server.test.ts
    └── fixtures/
```

运行时代码、页面、测试和说明全部留在此目录。唯一的外部依赖是对 `v0.2.2` SQLite 的只读访问，以及本机 Pi 配置。

## 7. 场景注册表与 Skill

场景注册表是固定场景的机器可读入口。V1 只有：

```text
scenario_id: forecast-parent-sales-90d
title: 预测父 ASIN 未来 90 天销量
allowed_tools:
  - get_parent_product
  - get_parent_sales_history
  - get_parent_inventory_snapshot
  - forecast_parent_sales_90d
max_tool_calls: 6
run_timeout_ms: 120000
```

场景同时定义：

- 推荐问题；
- 必填上下文 `parent_asin`；
- 专用 Skill 路径；
- 允许工具白名单；
- 工具调用预算与运行超时；
- 前端展示名称；
- 最终回答结构。

专用 Skill 约束 Agent 的分析顺序和回答边界：

1. 先确认父 ASIN 与数据覆盖；
2. 再读取历史销量；
3. 调用确定性预测工具；
4. 读取库存承接信息；
5. 输出结论、依据、库存承接与限制；
6. 不得把派生结果表述为客户原始事实；
7. 数据不足时停止预测，不补造数字。

该顺序是 Agent 的受控工作指南，不是前端预录动画。执行轨迹必须来自真实 Pi 工具事件。

后续可把场景注册表替换为用户维护的提示词表或流程配置，工具接口和前端事件协议保持不变。

## 8. 工具设计

所有工具只接受结构化参数，只返回有大小上限的结构化结果。Agent 不获得通用 SQL、Shell、文件读取、文件写入或编辑工具。

### 8.1 `get_parent_product`

输入：

```json
{"parent_asin":"B0CGLP3WVY"}
```

读取 `dim_product_parent`，返回：

- `parent_asin`；
- `product_name`；
- `style_name`；
- `demo_lifecycle_group`；
- `child_count`；
- `daily_history_days`；
- `daily_latest_date`；
- 来源状态与数据覆盖提示。

未知父 ASIN 返回结构化 `not_found`，并附可用父 ASIN 列表，不抛出包含本地路径的错误。

### 8.2 `get_parent_sales_history`

输入：

```json
{"parent_asin":"B0CGLP3WVY","lookback_days":180}
```

读取 `fact_parent_sales_daily`，返回：

- 实际起止日期；
- 可用天数与缺失天数；
- 近 30、60、90 天销量与日均；
- 前 30 天日均；
- 最近 30 个逐日观测值；
- `value_origin` 汇总；
- 来源和质量提示。

完整 180 天序列留在工具内部供计算使用，不全部放入模型上下文。

### 8.3 `get_parent_inventory_snapshot`

输入：

```json
{"parent_asin":"B0CGLP3WVY"}
```

从 `fact_parent_inventory_daily` 按该父 ASIN 自己的最大日期读取，返回：

- `as_of_date`；
- `fba_sellable`；
- `available_inventory`；
- `fba_inbound`；
- `quality_status`；
- `missing_metrics`；
- 字段来源摘要。

不得使用全表最大日期过滤所有父体，因为新品与成熟款的数据截止日期可能不同。

### 8.4 `forecast_parent_sales_90d`

输入：

```json
{"parent_asin":"B0CGLP3WVY","horizon_days":90}
```

工具自己从数据库读取计算所需的完整历史序列，执行确定性 V1 算法，并返回：

- `forecast_units`；
- `forecast_daily_average`；
- `demo_range_low`；
- `demo_range_high`；
- `avg_30d`、`avg_60d`、`avg_90d`、`avg_previous_30d`；
- 原始趋势比、受限趋势系数；
- 方法版本、公式和假设；
- 数据截止日；
- `value_origin: demo_derived`。

历史数据少于 30 个有效日时返回 `insufficient_data`，不生成预测。

## 9. V1 预测公式

```text
基础日均 = 近30天日均 × 0.50
         + 近60天日均 × 0.30
         + 近90天日均 × 0.20

原始趋势比 = 近30天日均 ÷ 前30天日均
趋势系数 = clamp(原始趋势比, 0.85, 1.15)

90天预测 = round(基础日均 × 趋势系数 × 90)
演示下界 = round(90天预测 × 0.85)
演示上界 = round(90天预测 × 1.15)
```

当“前 30 天日均”为零时，趋势系数固定为 `1.0` 并返回警告。演示上下界只称为“演示区间”，不得称为统计学置信区间。

公式版本固定为 `demo-wma-trend-v1`。以后替换算法时新增方法版本，不改变工具名、主要返回字段或前端事件协议。

## 10. 黄金流程

```text
用户选择父 ASIN 并发送问题
  → Gateway 校验 scenario_id 与 parent_asin
  → 创建内存 Pi Session
  → Pi 调用 get_parent_product
  → Pi 调用 get_parent_sales_history
  → Pi 调用 forecast_parent_sales_90d
  → Pi 调用 get_parent_inventory_snapshot
  → Pi 输出四段式回答
```

Agent 可在白名单内根据工具结果调整调用，但不得跳过产品确认、历史销量和预测工具后直接给出数字。库存工具失败时允许输出销量预测，但必须把库存承接标为不可判断。

最终回答固定为：

1. 结论：90 天预测总量与演示区间；
2. 依据：数据截止日、历史窗口和趋势；
3. 库存承接：库存与在途是否足以支持预测；
4. 限制：未纳入的业务变量与 Demo 算法声明。

## 11. HTTP 接口

### 11.1 `GET /api/health`

返回服务、数据库和 Pi 模型运行时是否可用。不得返回供应商密钥、认证内容或本地绝对路径。

### 11.2 `GET /api/parents`

从 `dim_product_parent` 返回父 ASIN 选择列表及简短元数据。该接口不经过模型，不产生费用。

### 11.3 `POST /api/agent/run`

请求：

```json
{
  "sessionId":"session_abc",
  "scenarioId":"forecast-parent-sales-90d",
  "parentAsin":"B0CGLP3WVY",
  "message":"预测这个父 ASIN 未来 90 天的销量"
}
```

响应类型：`application/x-ndjson; charset=utf-8`。每行一个完整 JSON 事件。浏览器使用流式 `fetch` 读取；用户点击停止时通过 `AbortController` 关闭请求，Gateway 随即中止当前 Pi 运行。

同一个 `sessionId` 的后续请求复用内存 Pi Session，因此可以基于上一轮结果追问。服务拒绝同一会话上的并发运行。

### 11.4 `DELETE /api/agent/session/:sessionId`

释放指定内存会话，用于“清空对话”。不存在的会话按幂等成功处理。

## 12. 稳定事件协议

前端只消费以下事件，不直接消费 Pi 原始事件：

```text
run.started
step.started
step.completed
step.failed
run.warning
answer.delta
run.completed
run.failed
run.cancelled
```

示例：

```jsonl
{"type":"run.started","runId":"run_123","sessionId":"session_abc","scenarioId":"forecast-parent-sales-90d"}
{"type":"step.started","runId":"run_123","stepId":"s1","tool":"get_parent_product","label":"读取父 ASIN 信息"}
{"type":"step.completed","runId":"run_123","stepId":"s1","summary":"找到 TH24AM-074，历史数据 579 天","durationMs":18}
{"type":"step.started","runId":"run_123","stepId":"s2","tool":"get_parent_sales_history","label":"查询历史销量"}
{"type":"answer.delta","runId":"run_123","delta":"根据截至 2026-08-03 的数据，"}
{"type":"run.completed","runId":"run_123"}
```

事件适配器负责：

- 把 Pi `tool_execution_start/end` 映射为步骤状态；
- 把 Pi 文本增量映射为 `answer.delta`；
- 用工具元数据生成用户友好的标签和摘要；
- 删除原始工具 JSON、SQL、本地路径、调试堆栈和认证信息；
- 保证同一 `stepId` 的开始与结束可配对；
- 连接中止时终止 Pi 会话，不让模型继续后台运行。

## 13. 页面设计

V1 是独立单页，不追求正式工作台的最终信息架构。默认使用 Organic Soft-Tech 的深绿、暖白、薄荷色、圆角和轻量层次，但界面只承担验证任务。

桌面布局：

- 左侧：场景说明、父 ASIN 选择、推荐问题和数据状态；
- 右侧：用户消息、可折叠执行轨迹、流式答案和输入框。

窄屏按内容顺序改为单列。必须存在：

- 发送；
- 停止；
- 重新运行；
- 清空对话；
- 展开或收起执行过程。

页面显示工具动作、简短结果、数据期间和来源状态；不显示模型原始思维链、SQL、完整工具 JSON、凭证或文件路径。

## 14. 错误与降级

| 情况 | 行为 |
| --- | --- |
| Agent 服务未启动 | 页面显示本地服务不可用与启动提示 |
| Pi 模型或认证不可用 | 运行前失败，不进入工具步骤 |
| 数据库不存在或不可读 | 健康检查失败，不启动预测 |
| 未知父 ASIN | 返回 `not_found` 和可用父 ASIN，不生成数字 |
| 有效历史少于 30 天 | 返回 `insufficient_data`，说明实际覆盖 |
| 前 30 天日均为零 | 趋势系数使用 1.0，并发出警告 |
| 销量工具失败 | 停止预测并标记失败步骤 |
| 库存工具失败 | 允许保留销量预测，但库存承接标为不可判断 |
| 模型超时 | 中止运行，允许使用相同输入重新运行 |
| 用户取消 | 关闭流并中止 Pi，状态显示“已停止” |
| 浏览器断开 | Gateway 中止对应运行并释放内存会话 |

错误事件使用稳定错误码和用户文案；详细堆栈只写服务端日志，日志不得包含认证值。

## 15. 安全边界

- 服务只绑定 `127.0.0.1`；
- 不提供修改绑定地址的页面入口；
- SQLite 以只读模式打开；
- 不复制、不迁移、不写回数据包；
- Pi 工具白名单只有四个业务工具；
- 禁止 `bash`、`read`、`write`、`edit`、任意 SQL 和任意网络工具；
- 只加载本 Demo 的 Skill，不自动加载全局 Extension 或全局 Skill；
- 场景 ID 必须命中注册表，不能从请求传入任意 Skill 路径；
- 输入长度、工具返回记录数、工具调用次数和运行时间均设上限；
- 静态文件服务防止目录穿越；
- 任何返回浏览器的错误均去除绝对路径和堆栈；
- 认证文件只由 Pi 模型运行时在服务端读取，不进入日志和响应。

## 16. 启动方式

目标启动方式：

```bash
npm install
npm run dev
```

打开 `http://127.0.0.1:18812/`。另外提供：

```bash
npm test
npm run start
```

`npm test` 必须默认使用假模型或事件夹具，不产生模型费用。真实 Pi 冒烟测试作为显式命令或人工验收步骤运行，不并入默认测试。

## 17. 测试策略

### 17.1 工具单元测试

- 五个父 ASIN 均能读取产品资料；
- 各父体分别使用自己的最新库存日期；
- 30/60/90 天汇总可由 SQLite 明细复算；
- 预测公式与边界钳制正确；
- 前 30 天为零与历史不足分支正确；
- 所有工具返回来源状态；
- 未知 ASIN 不生成预测。

### 17.2 事件契约测试

- 每个步骤开始与结束可配对；
- 文本增量顺序不乱；
- 工具失败映射为 `step.failed`；
- 取消映射为 `run.cancelled`；
- 事件中不出现 SQL、绝对路径、堆栈或认证字段；
- 最终事件只能是完成、失败或取消之一。

### 17.3 服务测试

- 健康检查、父体列表、静态页面和流式接口可访问；
- 非法场景、非法 JSON、空 ASIN 和超长输入被拒绝；
- 同一会话的并发运行被拒绝，会话过期、上限淘汰和主动清理有效；
- 只允许注册工具；
- 客户端断开后运行被中止；
- 静态路径不能逃出 `web/`。

### 17.4 浏览器与真实 Pi 验收

- 桌面与窄屏均能完成一次预测；
- 浏览器控制台无运行时错误；
- 真实 Pi 至少调用产品、销量和预测工具；
- 库存可用时展示库存承接；
- 答案包含四段固定结构；
- 停止和重新运行有效；
- Agent 未启动、未知 ASIN和模型错误均有可见状态。

### 17.5 只读证明

真实冒烟测试前后计算 SQLite SHA-256，必须一致。测试同时确认没有在数据包目录创建新文件。

## 18. 完成定义

以下条件全部满足才算 V1 完成：

1. 所有运行文件均位于 `06-Pi-Agent交互Demo`；
2. 现有 Demo 代码和数据包没有被修改；
3. 一条命令可以启动本地页面与 Agent；
4. 父 ASIN 90 天预测黄金场景可重复完成；
5. Pi 真实调用白名单工具，而非前端播放预设步骤；
6. 执行轨迹与真实工具事件一致；
7. 最终答案包含预测、依据、库存承接和限制；
8. 客户事实与 `demo_derived` 结果明确区分；
9. 失败、超时和取消路径可演示；
10. 默认自动测试不调用付费模型；
11. SQLite 运行前后哈希一致；
12. 浏览器不接收凭证、本地路径、SQL、调试堆栈或原始思维链。

## 19. 后续扩展边界

未来扩展遵循以下顺序：

1. 替换或升级数据包；
2. 在预测工具内部替换算法，并增加方法版本；
3. 增加新的场景配置与专用 Skill；
4. 复用现有工具或增加新的窄工具；
5. 保持稳定事件协议，按需替换前端；
6. 真正部署时再设计独立凭证、鉴权、沙箱、多用户会话和持久化。

不得因为增加新场景而开放任意 SQL、Shell 或全局 Pi 工具。

## 20. 参考

- Pi SDK：<https://pi.dev/docs/latest/sdk>
- Pi Agent Harness：<https://github.com/earendil-works/pi>
- 数据包说明：`../02-产品销售库存模块/02-数据构建/v0.2.2/README.md`
