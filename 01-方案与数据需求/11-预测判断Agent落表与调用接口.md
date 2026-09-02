# 预测判断 Agent · 落表与调用接口

版本 v0.2 · 2026-08-31 · 状态：**两侧已跑通，前端未接**
v0.2 改了什么：修正 §4 里把 `B0B3LM36WB` 当缺货扭曲样本的**事实错误**（实测它丢失销量 0 件），
换成 `B0CBPXNC1M` 并附实测数字与真模型结论；新增 §5 三张跨边界词表（v0.1 只钉了形状，
没钉词表，导致两侧各自发明了一套）；新增 §6 记下七条尚未解决的问题。
决策：王楠 2026-08-31 选 **B 方案** —— Agent 输出单独一张表，页面优先读它，读不到回落数据包。

配套必读：`07-预测Agent接口契约.md`（职责切法 §0、批次台账为什么不设 is_latest §2.1）、
`10-盘点结论Agent接口契约.md`（同一套 harness 校验后才写的模式、created_at 格式的坑）、
`../00-通用方法与规范/02-模块接入契约.md` v1.4（`MODULE["agents"]` 与 `MODULE["tasks"]`）。

---

## 0. 为什么这张表存的是判断，不是预测数字

**九工具链里的预测数字不是 Agent 算的。** 实测：`forecast_child_sales_daily`
读的是数据包里 `fact_child_forecast_daily` 的 P10/P50/P90，`fact_child_forecast_evaluation`
（1026 行 = 342 子体 × 3 候选模型）给出选中哪个模型和统计置信度。这些都是离线烤好的确定性结果。

所以「两份预测数字选哪份」这个问题不存在。真正缺的是 07 契约 §0 点名的那三类判断：
历史有没有被缺货扭曲、活动影响多大、生命周期在哪一段 —— 数据包给不出这些，
它只有统计指标（wape / bias / confidence_score），没有中文理由，也没有逐项调整的依据。

**这张表就存那部分，且只存那部分。** 90 天逐日序列继续由数据包提供，
Agent 不重算 —— 让 LLM 产出算术会同时丢掉可复算性和「改阈值立刻重算」这两件事。

---

## 1. 库与两张表

库：`09-工作台/modules/inventory/derived/forecast_agent.sqlite`
（与已经跑通的 `verdict_agent.sqlite` 同目录、同模式：Agent 项目写，工作台只读打开。）

### 1.1 `fact_child_forecast_judgment_run` —— 批次台账

```sql
CREATE TABLE fact_child_forecast_judgment_run (
  run_id                TEXT PRIMARY KEY,   -- {child_asin}-{run_date}-agent-{yyyymmddHHMMSS}
  child_asin            TEXT NOT NULL,
  run_date              TEXT NOT NULL,      -- YYYY-MM-DD
  data_as_of            TEXT NOT NULL,      -- 应等于产品包 as_of
  horizon_days          INTEGER NOT NULL,   -- 90
  trigger               TEXT NOT NULL,      -- weekly | manual | priority
  model_version         TEXT,               -- 真实模型名，例 deepseek/deepseek-v4-flash
  method_version        TEXT,               -- inv-forecast-judgment-v1
  input_forecast_run_id TEXT,               -- 用了包里哪一批预测，可追溯
  confidence            TEXT,               -- 高 | 中 | 低（中文，直接上界面）
  confidence_reason     TEXT,               -- 中文一句话，直接上界面
  judgment_summary      TEXT,               -- 中文一句话，结论先行用
  created_at            TEXT NOT NULL       -- ISO 8601 带偏移，见 §1.3
);
CREATE INDEX idx_fjudg_run ON fact_child_forecast_judgment_run(child_asin, run_date DESC, created_at DESC);
```

### 1.2 `fact_child_forecast_judgment_factor` —— 逐项调整与依据

```sql
CREATE TABLE fact_child_forecast_judgment_factor (
  run_id     TEXT NOT NULL,
  factor     TEXT NOT NULL,   -- 固定词表，见下
  ord        INTEGER NOT NULL,-- Agent 定的展示先后，最要紧的在前
  state      TEXT NOT NULL,   -- 中文固定词表，见下
  impact_pct REAL,            -- 对未来需求的影响幅度，-1.0 ~ 1.0；判断不出给 NULL
  because    TEXT,            -- 中文依据，点开才看
  numbers    TEXT,            -- JSON 对象：这条引用到的数字，供交叉核对门禁用
  PRIMARY KEY (run_id, factor)
);
```

**`factor` 固定五项**，缺一项就是输出不合契约：

| factor | 含义 | 允许的 state |
| --- | --- | --- |
| `stockout_distortion` | 历史销量有没有被缺货压低 | `无扭曲` / `轻度扭曲` / `重度扭曲` |
| `promotion` | 站内活动对需求的影响 | `无活动` / `有活动且已回落` / `有活动仍在影响` |
| `lifecycle` | 生命周期在哪一段 | `爬坡` / `平稳` / `衰退` |
| `advertising` | 广告投放对需求的拉动 | `无投放` / `平稳` / `加大` / `减少` |
| `seasonality` | 季节性 | `不明显` / `旺季` / `淡季` |

**`state` 只能取表内值。** 不在表内页面会落到灰色兜底 —— 库存模块为这个付过学费
（泳道颜色键大小写不符，导致所有泳道同色，颜色唯一的作用被抹掉）。

**`numbers` 不是给人看的**，是给 §4 那条交叉核对门禁用的。

### 1.3 `created_at` 必须是 ISO 8601 **带偏移**

例 `2026-08-31T06:57:01+08:00`。这条是盘点结论那边实测踩出来的，不是洁癖：
同一个 Agent 两次运行给了 `2026-08-30T22:56:12.869Z` 和 `2026-08-31T06:57:01` 两种格式，
按字符串取最新会把带 Z 的判成前一天，**更新的结论被更旧的盖掉且界面上没有任何症状**。

**不设 `is_latest` 标记位**（07 §2.1 的理由：中断的运行会留下两个 1）。
读取端按 `run_date` 粗筛后，在同一天内按**解析后的时刻**取最晚，两种格式都要能排对。

---

## 2. 调用接口

### 2.1 Agent 侧新增端点

```
POST {AGENT_ORIGIN}/api/agent/forecast-judgment
Content-Type: application/json
{ "childAsin": "B0B3LM36WB", "trigger": "manual" }
```

同步返回（跑完才回，九工具链耗时以十秒计）：

```json
{
  "ok": true,
  "run_id": "B0B3LM36WB-2026-08-03-agent-20260831075500",
  "child_asin": "B0B3LM36WB",
  "model_version": "deepseek/deepseek-v4-flash",
  "steps": [
    { "tool": "route_demo_child_asin", "label": "路由到样本子 ASIN",
      "summary": "命中稳定成熟样本", "duration_ms": 812, "status": "完成" }
  ],
  "factors_written": 5,
  "errors": []
}
```

失败时 `ok:false` + `errors[]`（中文），并且**一行都不写库**。

### 2.2 LLM 不碰写路径

照盘点结论那条已经跑通的路：

1. harness 先独立读一份确定性事实（包里的选中模型、wape、P50 序列摘要、历史审计、事件日历）
2. Agent 通过 typebox schema 约束的工具提交判断，schema 挡住 factor/state 取值与字段缺失
3. `validateForecastJudgment(facts, judgment)` 返回错误清单 —— 逐项核 `numbers` 与确定性事实
4. **只在零错误时** `writeForecastJudgmentRun()` 写库

LLM 全程只提议，不写。这也是盘点结论那次 22 个数字能全部对上确定性层的原因。

### 2.3 工作台侧

- `MODULE["tasks"]` 声明一条：
  `{"id": "forecast-judgment", "label": "重跑需求判断", "needs": "object", "run": "run-forecast-judgment"}`
  任务面板读声明自动出现，外壳零改动。
- 路由 `run-forecast-judgment` **不跑 LLM**，转调 2.1 的端点，把返回的 steps 转成
  面板要的 `{run, steps}` 形状。`sources` 必须是**中文数据源名**，库内表名不上屏（G9）。
- 跑完页面**重新读表**取判断，不从 Agent 响应里取数字上屏 ——
  这样刷新、分享链接、别人打开看到的是同一份。

---

## 3. 页面优先读它，读不到回落

`forecast.py` 增一层：

| 情况 | 页面显示 |
| --- | --- |
| 有 Agent 判断 | 中文 `confidence` + `confidence_reason` + 五项调整及依据，标「跑于何时 · 触发方式」 |
| 没有 | 回落数据包的统计口径（选中模型 + `confidence_score`），并标明是统计口径不是判断 |

**回落必须看得出来。** 两种来源长得一样的话，运营会以为每个对象都被判断过了。

90 天逐日序列两种情况下都来自数据包，不受影响。

---

## 4. 门禁（写完一条一条跑）

| 门禁 | 断言 |
| --- | --- |
| 五项齐全 | 五个 `factor` 必须都有行，缺一个就是输出不合契约 |
| state 在词表内 | 逐条比对允许值，不许落到灰色兜底 |
| **交叉核对数字** | `numbers` 里每个值与确定性层同口径值比对，超容差判不一致 |
| 一句话 | `judgment_summary` / `confidence_reason` 长度上限，防止写成一段 |
| confidence 中文 | 只能是 高/中/低，不许出现 high/medium/low |
| 无枚举泄漏 | 扫 `stockout_distortion` 这类英文码值有没有上屏 |
| 取最新正确 | 同对象插两条同 `run_date` 不同 `created_at`，页面必须读到晚的那条 |
| **混格式时间戳仍取对** | 插一条「实际更晚但字符串更小」的（`…T23:05:00Z` 对 `…T06:57:01`），必须取到实际更晚的 |
| 回落可用 | 库整个移走，页面仍显示数据包统计口径且不报错，并标明是回落 |
| 回落看得出来 | 有判断与无判断两种情况在页面上必须可区分 |
| 打在真有特征的对象上 | 见 §4.1 —— **不要用 `B0B3LM36WB` 当缺货扭曲样本** |

最后一条是这个项目反复付过学费的：门禁跑在没有该特征的对象上，全绿等于没测。

### 4.1 缺货扭曲那条通路的检查对象（实测定的，别改回去）

**本文 v0.1 写错过一次**：原文说「至少一个缺货扭曲明显的（`B0B3LM36WB` 现成）」。
实测 `B0B3LM36WB` 丢失销量 **0 件、有丢失的天数 0 天**，真模型判的是「无扭曲」。
照那句写出来的门禁会验着一个错的预期还打勾 —— 比没有门禁更坏。

正确的对象是 **`B0CBPXNC1M`**，它是全包**唯一**有丢失销量的子体：

| 指标 | 值 | 注意 |
| --- | --- | --- |
| 缺货天数 | 113 / 730 天，近 90 天 **1 天** | 与下一行不是同一个指标 |
| 有丢失销量的天数 | 14 天，近 90 天 **0 天** | `lost_sales_units > 0` 的天数 |
| 丢失销量合计 | 27 件（占潜在需求 2528 的 1.07%） | 全包合计也是 27 件 |

**两个指标要分清**：「缺货」是没货可卖，「丢失销量」是因此真的少卖了多少。
`fact_child_sales_daily` 里**没有** `stockout_censored` 列，别照那个名字写查询。

2026-08-31 08:17 真模型（`deepseek/deepseek-v4-flash`）在它身上判的是：

```
缺货扭曲  轻度扭曲  +3.00%
依据：历史730天缺货113天但近90天仅1天，丢失销量仅27件，历史扭曲已基本修复。
```

所以门禁的正确断言是「**能判出 `轻度扭曲` 且 impact_pct 为正**」，
不是「判出 `重度扭曲`」—— 数据支撑不到重度。

**`重度扭曲` 这一档在本数据包里没有检查对象。** 要么由数据侧造一个近 90 天有实质缺货的
对象，要么门禁用合成行覆盖这一档并在注释里写明它测的是读取端不是真实数据。
两条都行，但**不许因为它没对象就当它测过了**。

零特征对照对象：`B0B3LNKTMC`（从未跑过判断，用来验回落分支）。

---

## 5. 三张跨边界词表（v0.1 缺的就是这三张）

v0.1 把数据的**形状**钉死了，两侧一次就对接成功。但凡是要跨过接口、
最终显示给人的东西，光钉形状不够 —— 两个实现方各自发明了一套：
Agent 侧自建了 metric key 表，工作台侧自建了 step 数据源映射表和中文兜底。
接得上，但讲的不是同一件事。这一节补上。

### 5.1 语气沿用结论带已有的 `tone`，方向由 `impact_pct` 的符号自己说

**页面上已经有一套语气词表了。** `verdict.py` 每条结论带 `tone`，取值
`alert` / `warn` / `good`，`inventory.css` 的 `[data-tone="…"]` 已经按它上色。
需求判断**必须复用同一套取值**，否则同一个页面上两套语气机制，颜色含义就不统一了。

关键是分清两件被混在一起的事：

**方向不用 tone 表达。** 屏幕上已经显示 `-5%` / `+3%` 了，符号本身就是方向。
再给「淡季 −5%」标个警示色是错的 —— 淡季不是问题，是季节。
手写一张「哪个 state 什么颜色」的表，迟早和数字打架，出现「标红的 +3%」。

| `impact_pct` | 显示 | tone |
| --- | --- | --- |
| > 0 | `+3.00%` | 无 |
| < 0 | `−5.00%` | 无 |
| = 0 | `0.00%` | 无 |
| NULL | `—`（要和 `0.00%` 视觉可区分） | 无 |

**tone 只留给「这一项本身需要注意」**，与需求涨跌无关：

| state | tone | 为什么 |
| --- | --- | --- |
| `重度扭曲` | `alert` | 喂给模型的历史被缺货压过，预测的输入本身不干净 |
| `轻度扭曲` | `warn` | 同上，程度轻 |
| `衰退` | `warn` | 生命周期在往下，与单期涨跌不是一回事 |
| 其余全部 | 无 | 旺季/淡季/加大/减少都不评好坏 |

**这三行是判断，不是推导出来的 —— 要否就否掉。** 理由：旺季对备货是压力、
对销售是机会，在这一层给它定好坏只会误导；而「历史不干净」和「在衰退」
是无论怎么解读都该让人看一眼的。

`good` 这一档需求判断用不上（没有哪一项调整是「好消息」），留空即可。

### 5.2 每个 step 的 `sources` 由 Agent 自己给中文

v0.1 的 step 例子里没有 `sources`，而 §2.3 又硬要求它是中文数据源名。
唯一能推出数据源的是 `tool`，偏偏它是英文码值、G9 禁止上屏。
结果工作台侧只能建一张映射表加中文兜底 —— 工具一多就要么猜错（码值上屏），
要么九步全显示同一个兜底源。

**改为写入方负责**：`/api/agent/forecast-judgment` 返回的每个 step 必须带
`sources: string[]`，中文数据源名，例如 `["产品主数据", "历史逐日销量"]`。
工作台侧照抄不加工，并**删掉那张映射表**。

Agent 侧给不出中文名的 step，就给空数组 —— 空数组页面不显示数据源，
比显示一个猜错的源好。

### 5.3 `numbers` 的可引用口径由 Agent 侧发布，本文不抄一份

`numbers` 是交叉核对门禁的输入。没有可引用口径表，Agent 交 `{"foo":1}` 也能过。
Agent 侧已经定了一套 metric key 与「每个 factor 必填/可选哪些 key」。

**本文不复制那份清单。** 抄进来就是第二个真相来源，改一处忘一处，
而这正是这个项目在消除的东西。

要求 Agent 侧把它作为**机器可读产物**发布（与 `forecast_agent_latest.json`
同目录的一个 `forecast_facts_schema.json`，或在事实产物里带上
`metrics` 与 `factor_evidence` 两段）。工作台侧要显示或核对时读它，不硬编码。

判据是：**离开 Agent 侧的源码，也能知道 `numbers` 里允许出现哪些键。**
现在做不到，所以这条算未完成。

---

## 6. 还没解决的（两侧实现时发现，记下来免得丢）

| # | 问题 | 影响 |
| --- | --- | --- |
| 1 | `run_id` 里有两个日期：`{child_asin}-{run_date}-agent-{yyyymmddHHMMSS}`，`run_date` 是包 as_of（2026-08-03），后面那串是墙上时钟（20260831…） | 想按 `run_date` 查「今天重跑过没有」永远查不到。要么再加一列真实运行日，要么改 id 规则 |
| 2 | `重度扭曲` / `无活动` / `无投放` 三个 state 在本数据包里没有检查对象 | 342 个子体全部有活动排期与投放计划；缺货也没有近期实质扭曲的对象。这三档的门禁只能用合成行，且必须在注释里写明它测的是读取端不是真实数据 |
| 3 | `stockout_distortion.impact_pct` 的量级喂不动 | 全包丢失销量合计 27 件。除 `B0CBPXNC1M`，其余对象这一项只能是 0 或 NULL |
| 4 | `core.db.pool` 缓存的连接绑 inode | Agent 若改成「删旧库、建新文件」而不是原地写，工作台的只读连接会一直读老 inode，**且界面上没有症状**。现在是原地写所以不触发。`verdict.py` 有同样性质 |
| 5 | 盘点结论库的 `created_at` 仍是无偏移格式 | §1.3 要求带偏移，但 `verdict_agent.sqlite` 是既有数据。读取端两种格式都能排对，是否统一由盘点结论那边决定 |
| 6 | 契约 02 的 `status` 词表自相矛盾 | 8.1 说用 6.6 的词表且「`完成` 之外的值标成失败」，但 6.6 词表里没有「完成」。`shell.js` 实际放过「完成」和「正常」两个。该在契约 02 里定一个 |
| 7 | 置信度阈值有两份 | `forecast.CONFIDENCE_CUTS` 与 `compute.build_demand()` 里的三行是同一套档位，重复而非共享 |
| 8 | **产出方不确定，按特征挑的检查对象会失效** | 实测 `B0B3LM36WB` 的生命周期 08:05 与 08:11 两次跑都给 `null`，08:13 那次给 `0.0` —— 两者都合契约。所以「某对象的某项是 null」这类断言今天成立、重跑就不成立，且失败起来**看起来像代码坏了**。凡是依赖具体判断值的门禁，要用合成行，不要指定活对象 |

第 4 条最值得警惕：它和「按 `created_at` 字符串取最新」是同一类 —— **修了也没有症状，
坏了也没有症状**，只能靠写下来提醒。

第 8 条改变了「打在真有特征的对象上」这条老规矩的适用范围：**该规矩仍然成立于
确定性特征**（有没有在途、有没有缺货日、跑过没跑过判断 —— 这些不会因重跑而变），
**但不适用于 Agent 判断出来的值**。两类要分开挑靶子。
