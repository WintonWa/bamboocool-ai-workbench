# 竞品分析模块 · 验收

> 只有一个文件：契约门禁。

## `test_contract_gates.py`

竞品 Agent 的契约门禁，逐条核对 Agent 真实落表是否符合
`../01-方案与数据需求/04-Agent输出点盘点.md` 的字段级规格。

**这是竞品这条线唯一的机械验收手段。** 工作台侧那 24 条门禁
（`/Users/linsen/BAM/09-工作台/tests/test_gates.py`）管的是模块接入契约与视觉基准，
不管 Agent 输出的字段是否合规 —— 那部分由这个文件管。

## 怎么跑

```bash
cd /Users/linsen/BAM/08-竞品分析模块/03-验收
/usr/bin/python3 test_contract_gates.py
```

Python 必须 `/usr/bin/python3`（3.9.6）。

## 它检查的是什么

ATTACH 三个库，各查一层：

```
competitor_demo.sqlite                观察层（价格 / 市场 / 排名 / 流量）
...v0.3.0.sqlite                      产品包，查 342 脊椎命中
competitor_agent_state_v2.sqlite      ★ Agent 状态库，V2 那个
    环境变量 WORKBENCH_COMPETITOR_AGENT_DB 可覆盖
```

**Agent 那部分指的是 V2 库，不是观察库里那九张 v1 死表。** 门禁是活的、有效的。

## 实跑现状（2026-09-02）

```
23 passed, 1 failed
FAIL G1  每个 run 至少一条变化且文案非空（无变化 run=1，空文案=0）
```

G1 这一条红：有 1 个 run 没有产出任何变化记录。文案没有空的，所以不是文案病，
是那次运行本身没给出变化——可能是跳过的 run，也可能是真漏了。
需要对着 `fact_competitor_agent_execution` 台账看那个 run 的 status 才能定性。

