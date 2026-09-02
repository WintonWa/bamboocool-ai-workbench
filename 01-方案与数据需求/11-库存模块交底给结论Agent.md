# 库存模块交底 —— 给盘点结论 Agent

版本 v1.0 · 2026-08-31 · 用途：**Agent 侧读这一份就够**，不用翻代码

这份回答四个问题：我这个页面长什么样、我算什么、我读哪些表、你要写什么。
配套契约：`10-盘点结论Agent接口契约.md` v0.2（本文是它的实施态说明 + 样例）。

---

## 0. 一句话

我是 Bamboocool 工作台的**产品与库存模块**（`inventory`，跑在 18820）。
页面把库存判断算成确定性的数字，你把同一批数字**判断成五条中文结论**并写进结论库；
页面读你上次跑的结果，秒开，旁边有按钮让运营手动重跑。

**你不读我的页面，你读表。** 我们是同一批数据表的两个平行消费者。
数字应该一致 —— 不一致就是有一边算错了，门禁会比对。

---

## 1. 页面结构

三个页面，模块 id `inventory`，路由前缀 `/api/inventory/`：

| 页面 id | 名字 | 判断对象 | 板块 |
| --- | --- | --- | --- |
| `inv-detail` | 单品盘点 | 单个子 ASIN | 产品身份块 + 8 个板块 + 1 个折叠区 |
| `inv-risk` | 异常总览 | 全部 342 个子体 | 风险版图 |
| `inv-scope` | 库存全览 | 当前筛选范围 | 范围概览 |

**单品盘点页的板块顺序**（你的结论落在第 1 个板块里）：

1. **产品与盘点结果** ← **五条结论带在这里，在两个灰框上面**
   - 结论带（你写的五条，或页面的确定性兜底）
   - 承接 / 风险数 / 生命周期 三个标签
   - 灰框：市场表现（小类排名、评分、单位成本）
   - 灰框：2026-06 经营（销量、净销售额、毛利、毛利率）
2. 销量与需求 —— 820 天逐日柱状图（730 历史 + 90 预测），事件标注、缺货背景带、8 条可叠加折线
3. 库存盘点 —— 各库位数量与状态
4. 在途与到货 —— 逐笔在途、ETA、是否计入覆盖
5. 库存承接 —— 覆盖天数、安全线突破日、断货日、缺口、建议补货
6. 库龄 —— 八档库龄柱、181+ 占比、前滚审计
7. 仓储费 —— 基础费、超龄附加、占销售额/毛利
8. 风险点与形成原因 —— 五类风险逐条
9. （折叠）数据与口径

三个接口：`/api/inventory/meta`、`/api/inventory/children`、`/api/inventory/child/<子ASIN>`。

---

## 2. 我算什么、不算什么

这条边界是既定的（`07-预测Agent接口契约.md` §0）：

| 谁 | 做什么 |
| --- | --- |
| **需求预测 Agent**（已存在） | 未来 90 天逐日需求 p10/p50/p90 + 选用模型 + 回测偏差 + 调整项依据 |
| **我（页面）** | 逐日库存余额、覆盖天数（两个口径）、安全线突破日、预计断货日、缺口量、超量件数、消化天数、库龄八档、仓储费、五类风险、承接能力 |
| **你（盘点结论 Agent）** | 五条结论的**定性、先后、措辞、依据**。不产出数字，只引用 |

**我算的东西全部随参数面板即时变。** 运营一调安全库存天数或阈值，
覆盖天数、断货日、缺口量当场重算。所以数字不能来自你的上一次运行 —— 那样调参就是假的。

**11 个可调参数**（键带 `inv.` 前缀）：安全库存天数、目标覆盖天数、超量判定消化天数、
低销量保护、待调仓转可售天数、可用率下限、181+ 占比上限、仓储费占销售额上限、
仓储费占毛利上限、基础仓储费率、（批次消耗方式为 FIFO 且锁定，不在面板）。

---

## 3. 我读哪些表

### 3.1 产品包（只读，你也读它）

`02-产品销售库存模块/02-数据构建/v0.3.0/bamboocool_product_sales_inventory_v0.3.0.sqlite`
489 MB / 44 表 / 342 子体 / 基准日 **2026-08-03** / 历史 730 天 / 预测 90 天

**逐子体的事实表**（我一次全表读进内存，都 ≤342 行）：

| 表 | 我用它干什么 |
| --- | --- |
| `dim_product_child` | 子体身份、父体归属 |
| `dim_product_attribute` | 款号、组合、颜色、尺码、运营、货品状态、生命周期、品类 |
| `bridge_product_identifier` | FNSKU、店铺 |
| `fact_inventory_snapshot` | 可售、受限、FBA 合计、在库、待调仓、入库中 → 库存盘点板块 |
| `fact_sales_window` | 客户自己的 3/7/14/30/60/90 天窗口销量（**只作对照，不作页面口径**） |
| `fact_supply_plan` | 客户自填的安全库存天数、补货计划 |
| `fact_child_sales_monthly` | 2026-06 经营：销量、净销售额、毛利、毛利率 |
| `fact_unit_economics` | 单位成本、单位体积 → 仓储费 |
| `fact_inventory_age_bucket_asof` | 八档库龄（已前滚到基准日）→ 库龄板块、仓储费超龄附加 |
| `fact_inventory_age_bucket` | 客户 6 月原值，界面上作对照细线 |
| `age_rollforward_audit` | 前滚审计，折叠区 |
| `missing_field_matrix` | 缺字段矩阵，折叠区 |

**逐日表**（249,660 行级）：

| 表 | 我用它干什么 |
| --- | --- |
| `fact_child_sales_daily` | 历史实际销量 → 柱状图左半边、窗口与月度重算 |
| `fact_child_inventory_daily` | `stockout_flag` 缺货日 → 柱状图缺货背景带；`received_units` 逐日实收 |
| `feature_child_demand_daily` | `demand_quality_flag` 异常日、`adjustment_reason` 中文调整原因 |
| `fact_child_price_daily` / `fact_child_traffic_daily` / `fact_child_advertising_daily` | 8 条可叠加折线：售价、标价、销售额、广告花费、广告销售额、访问量、转化率、ACoS |
| `fact_child_promotion_daily` / `plan_child_promotion_daily` | 事件区间（BD / LD / Coupon / 价格调整），按同子体+同类型+相邻日期合并 |
| `fact_parent_sales_daily` / `fact_parent_inventory_daily` | 父体对照曲线 |

**预测与在途**：

| 表 | 我用它干什么 |
| --- | --- |
| `fact_child_forecast_daily` | `p10/p50/p90_units` → 需求，三档各投影一遍得断货日区间 |
| `fact_child_forecast_run` / `fact_child_forecast_evaluation` | 选用模型、回测偏差、置信度 |
| `plan_child_supply_event` | **在途逐笔**：`planned_units / eta_earliest / eta_latest / transport_mode / event_status / confidence_level`。342 个子体共 684 笔 |
| `fact_child_inventory_decision` / `fact_child_inventory_projection_daily` | 数据包自带的决策与投影，**只作对照基线，不作页面输出**。断货日一致率 80% |

**不用的表**：`bridge_demo_child_route`（它把 337/342 改指 5 个黄金对象，但每个子体确有各自预测，用了就是挂错数字）。

### 3.2 我建的派生缓存（模块私有）

`modules/inventory/derived/chart_cache.sqlite`，36 MB，`chart_daily` 249,660 行 + `chart_event` 2,649 段。

**为什么存在**：产品包逐日表主键是 `(date, child_asin)`，按子体查退化成跳扫
65–128 ms/表，一个板块 700 ms，全量 342 个要四分钟。缓存按 `(child_asin, date)` 建，
单子体查询 **0.8 ms**，全盘 3.4 s。重建：`/usr/bin/python3 modules/inventory/derived/build_cache.py`（2.5 s）。

**你不需要这个缓存** —— 直接读产品包即可，你是离线跑的，不在乎单次延迟。

---

## 4. 你要写什么：结论库

`modules/inventory/derived/verdict_agent.sqlite` —— **你写，我只读**。
产品包只读不动，两库分开。页面用 `ATTACH DATABASE` 挂上。

### 4.1 两张表

```sql
CREATE TABLE fact_child_verdict_run (
  run_id        TEXT PRIMARY KEY,   -- {child_asin}-{run_date}-{seq}
  child_asin    TEXT NOT NULL,
  run_date      TEXT NOT NULL,      -- YYYY-MM-DD
  data_as_of    TEXT NOT NULL,      -- 应等于产品包 as_of，即 2026-08-03
  trigger       TEXT NOT NULL,      -- weekly | manual | priority
  model_version TEXT,
  method_version TEXT,              -- inv-verdict-v1（真 Agent）/ inv-verdict-rules-v1（规则兜底）
  input_forecast_run_id TEXT,       -- 用了哪一次需求预测，可追溯
  created_at    TEXT NOT NULL       -- 必填！同日可能跑两次，run_date 分不出先后
);
CREATE INDEX idx_verdict_run ON fact_child_verdict_run(child_asin, run_date DESC, created_at DESC);

CREATE TABLE fact_child_verdict_item (
  run_id   TEXT NOT NULL,
  block    TEXT NOT NULL,   -- safety | stockout | in_transit | overstock | storage_fee
  ord      INTEGER NOT NULL,-- 展示先后，最要紧的给 1
  state    TEXT NOT NULL,   -- 中文，固定词表，见 4.2
  verdict  TEXT NOT NULL,   -- 一句话，直接上屏
  because  TEXT,            -- 依据，点 ⓘ 才展开，可以长
  refs     TEXT,            -- JSON 数组，指向页面板块，供下钻
  numbers  TEXT,            -- JSON 对象，这条引用到的数字，供交叉核对
  PRIMARY KEY (run_id, block)
);
```

**两条硬规则**

- **`created_at` 必填，且要 ISO 8601 带偏移**（`2026-08-31T06:57:01+08:00`）。
  运营点一下就重跑，一天内可能两次，`run_date` 分不出先后。

  **这一条你已经踩过一次**：第一次注入给的是 `2026-08-30T22:56:12.869Z`，
  第二次给的是 `2026-08-31T06:57:01` —— 同一个 Agent 两种格式，
  而两者实际都是本地 08-31 06:56 / 06:57。页面原来按字符串比，
  带 Z 的那条会被判成 08-30 从而排到更旧的记录之前，
  **更新的结论被更旧的盖掉且界面上没有任何症状**。
  页面已改成按解析后的时刻排序（两种格式都能正确处理），但请统一给带偏移的形式。
- **不要设 `is_latest` 标记位。** 页面按 `run_date DESC, created_at DESC` 自己取最新。
  标记位一旦因中断的运行留下两个 1，页面会静默读错一个对象的结论，而这种错误没有任何症状。

### 4.2 五个 block 与允许的 state

**`state` 只能取词表内的值。** 越界的话页面整份丢弃这次 run、退回确定性规则
—— 不是落灰色兜底。这一条是踩过的：库存模块曾因泳道颜色键大小写不符，
导致所有泳道同色，颜色唯一的作用被抹掉。

| block | 中文名 | 回答什么 | 允许的 state |
| --- | --- | --- | --- |
| `safety` | 库存是否安全 | 未来 90 天够不够，把到货算进来够不够 | `安全` / `偏紧` / `不安全` |
| `stockout` | 什么时候断货 | 断在哪天，误差多大 | `窗口内不断货` / `即将断货` / `已断货` |
| `in_transit` | 在途货件 | 来不来得及（**本期只判这个**） | `正常` / `来不及` / `有逾期` / `无在途` |
| `overstock` | 库存积压 | 是不是压太多、多久消化 | `正常` / `偏多` / `积压` |
| `storage_fee` | 仓储费 | 花了多少、值不值得动 | `正常` / `偏高` |

**`in_transit` 的 `有逾期` 本期不要用。** v0.3.0 的 684 笔 ETA 全部晚于基准日，
逾期实例为零；且表里没有实收/缺损/延误任何字段（全库扫过
`received/shortage/damag/discrep/actual_units/lost/delay/overdue`，
只有 `fact_child_inventory_daily.received_units` 是逐日实收，
但它与 `plan_event_id` 之间没有关联列，接不上）。所以本期只判「来不来得及」，
不要编造缺损结论。

### 4.3 三条文案硬约束

1. **`verdict` 是一句话**，要在首屏一行读完。写成一段就失去「结论先行」的意义。
2. **不许出现英文枚举**（`cannot_absorb` / `demo_default` / `direct` / `derived` 这类）。
   这是契约 G9，泄漏过一次。
3. **不许出现免责或口径辩护句**（「不作为判断依据」「不代表客户经营事实」「阈值待确认」
   这类）。口径限制进数据缺口文档，不上屏。

---

## 5. 你判断时该抓的那件事

这是我设计这个结论带的起因，`B0B3LM36WB`：

| 字段 | 值 |
| --- | --- |
| 可售口径覆盖天数 | 4.6 天 |
| **含已确认到货的覆盖天数** | **49.4 天** |
| 两个口径的断货日 | 都是 **2026-08-08** |
| 首笔已确认到货 | **2026-08-28**，609 件，空运 |

覆盖 49.4 天把 609 件在途算进来了，但那批货**比断货晚 20 天到**。
所以「覆盖 49.4 天」和「08-08 断货」同时为真，页面把它们并排摆着不解释。

**这就是你不可替代的地方**：把这件事说成一句话，并且判断它比「仓储费只有 $13」更要紧。
页面写不出来（它只有两个数，没有取舍），写死也不对（换个对象到货在断货之前，逻辑就反了）。

判断时建议的取舍顺序：**时间紧迫性 > 金额大小**。断货 5 天后发生，
比一年 $13 的仓储费重要几个数量级，`ord` 要体现这个。

---

## 6. JSON 样例

### 6.1 我给出的载荷（`GET /api/inventory/child/B0B3LM36WB` 的相关片段）

你不需要调这个接口（你读表），这里给出来是让你知道**页面手里有哪些数**，
以便你的数字和它对得上。

```jsonc
{
  "child_asin": "B0B3LM36WB",
  "as_of_date": "2026-08-03",
  "rule_version": "demo-product-inventory@2026-08-29.1+9f89dd95cf6a",

  "demand": {
    "available": true,
    "forecast_daily": 14.7,          // 预估日均
    "forecast_90d": 1324,            // 90 天累计
    "recent_actual_daily": 16.6,     // 近 7 天实际日均
    "confidence": "medium",
    "run": { "model_label": "趋势+季节", "model_wape": 0.19, "validation_days": 56 }
  },

  "inventory": { "sellable_qty": 67, "fba_total_qty": 117, "availability_rate": 0.57 },

  "projection": {
    "available": true,
    "safety_days": 14,
    "scopes": {
      "sellable_only":           { "cover_days": 4.6,  "stockout_date": "2026-08-08",
                                   "safety_breach_date": "2026-08-04" },
      "sellable_plus_confirmed": { "cover_days": 49.4, "stockout_date": "2026-08-08",
                                   "safety_breach_date": "2026-08-04" }
    },
    "arrivals": [
      { "plan_event_id": "PLAN-B0B3LM36WB-A", "units": 609, "eta": "2026-08-28",
        "eta_latest": "2026-08-31", "mode_label": "空运", "status_label": "已确认",
        "in_window": true, "counted": true },
      { "plan_event_id": "PLAN-B0B3LM36WB-B", "units": 305, "eta": "2026-09-28",
        "eta_latest": "2026-10-06", "mode_label": "海运", "status_label": "计划中",
        "in_window": true, "counted": false }
    ],
    "confirmed_arrival_qty": 609, "planned_arrival_qty": 305,
    "excess_qty": 0, "depletion_days": 150.7, "reasonable_max_qty": 5369.5
  },

  "aging": { "total_qty": 117, "aged_181_qty": 0, "aged_181_share": 0.0 },
  "fee":   { "available": true, "total_fee": 12.97, "regular_fee": 12.97,
             "aged_surcharge": 0.0, "sales_ratio": 0.0005, "gross_ratio": 0.0031 },

  "risks": [
    { "risk_type": "shortage",     "severity": "high", "headline": "预计 2026-08-08 库存见底" },
    { "risk_type": "availability", "severity": "low",  "headline": "FBA 可用率 57%，低于阈值 60%" }
  ],
  "capacity": { "level": "cannot_absorb", "note": "覆盖 49.4 天已低于安全线 14 天，不宜再加新增流量" },

  "verdict": { "origin": "agent", "run": {...}, "items": [ /* 见 6.2 */ ] }
}
```

### 6.2 你要写的五条（这是真实种子数据，页面已在渲染它）

```jsonc
// fact_child_verdict_run
{
  "run_id": "B0B3LM36WB-2026-08-03-1",
  "child_asin": "B0B3LM36WB",
  "run_date": "2026-08-03",
  "data_as_of": "2026-08-03",
  "trigger": "manual",
  "model_version": "<你的模型>",
  "method_version": "inv-verdict-v1",
  "input_forecast_run_id": "forecast-v030-20260803-default",
  "created_at": "2026-08-31T06:22:29"
}

// fact_child_verdict_item ×5，ord 按紧迫性
[
  { "block": "safety", "ord": 1, "state": "不安全",
    "verdict": "这个对象撑不到下批货：可售 67 件按日均 14.7 件只够 4.6 天，8 月 8 日见底，而最近一批要到 8 月 28 日。",
    "because": "覆盖天数有两个口径：只看可售是 4.6 天，把已确认到货算进来是 49.4 天。后者容易误读成安全 —— 那 609 件 8 月 28 日才到，落在断货之后 20 天。安全库存 14 天在 8 月 4 日就已跌破。",
    "refs": ["inventory", "projection"],
    "numbers": { "cover_days_sellable": 4.6, "cover_days_with_arrivals": 49.4,
                 "safety_days": 14, "stockout_date": "2026-08-08" } },

  { "block": "in_transit", "ord": 2, "state": "来不及",
    "verdict": "在途 914 件分两批，都赶不上这次断货：空运 609 件 8 月 28 日，海运 305 件 9 月 28 日。",
    "because": "空运那批已确认，海运那批还是计划中、未计入覆盖天数。若要补上 8 月 8 日到 8 月 28 日这 20 天的缺口，得走本地调仓或加急，现有两批都改不了到期。",
    "refs": ["projection"],
    "numbers": { "first_eta": "2026-08-28", "first_units": 609, "gap_days": 20,
                 "confirmed_qty": 609, "planned_qty": 305 } },

  { "block": "stockout", "ord": 3, "state": "即将断货",
    "verdict": "5 天后断货（8 月 8 日）。需求走高会更早，走低也推不过 8 月中。",
    "because": "按预估日均 14.7 件、可售 67 件推算。这个对象 56 天回测偏差 19%，属中等置信度，断货日误差按 ±2 天看。",
    "refs": ["projection", "demand"],
    "numbers": { "stockout_date": "2026-08-08" } },

  { "block": "overstock", "ord": 4, "state": "正常",
    "verdict": "没有积压：总量在合理上限内，181 天以上为零。",
    "because": "合理上限 5,369 件，当前未超。按预估日均折算消化约 150.7 天，这个天数偏长是因为断货期间销量被压制，不是备货过量。",
    "refs": ["aging", "projection"],
    "numbers": { "excess_qty": 0, "depletion_days": 150.7, "aged_181_qty": 0 } },

  { "block": "storage_fee", "ord": 5, "state": "正常",
    "verdict": "仓储费 $12.97，占销售额 0.1%，不值得为它动库存。",
    "because": "基础费 $12.97，无超龄附加。占毛利 0.3%。这个量级下，清库存省下的仓储费远不及断货损失。",
    "refs": ["fee"],
    "numbers": { "total_fee": 12.97, "aged_surcharge": 0.0, "sales_ratio": 0.0005 } }
]
```

`refs` 的可用值：`inventory` / `projection` / `demand` / `aging` / `fee` / `risks`
—— 对应单品盘点页的板块，页面用它做点击下钻。

---

## 7. 页面怎么读你的结果

```sql
ATTACH DATABASE 'verdict_agent.sqlite' AS vd;

SELECT i.*, r.run_date, r.created_at, r.trigger
FROM   vd.fact_child_verdict_item i
JOIN   vd.fact_child_verdict_run  r USING (run_id)
WHERE  r.child_asin = ?
  AND  r.run_id = (SELECT run_id FROM vd.fact_child_verdict_run
                   WHERE child_asin = ?
                   ORDER BY run_date DESC, created_at DESC LIMIT 1)
ORDER BY i.ord;
```

**整份丢弃的三种情况**（页面退回确定性规则，不会半残渲染）：
`state` 不在词表内 / 五条不齐 / 结论库读取报错。

**你没跑过的对象**：页面用确定性规则填五条，右上角显示「规则判定」而不是「跑于 …」。
现在 342 个对象里只有 `B0B3LM36WB` 有种子数据，其余全走规则兜底。

---

## 8. 你的输出会被怎么检查

| 门禁 | 断言 |
| --- | --- |
| 五条齐全 | 五个 block 都要有，缺一个整份丢弃 |
| state 在词表内 | 逐 block 比对 |
| **交叉核对数字** | `numbers` 里每个值与页面按同口径算出的值比对，超容差判不一致。**「两边读同一份表就该得到同一批数字」这句话的可验证形式就是这条** |
| 一句话 | `verdict` 长度上限 |
| 无枚举泄漏 | 扫 `cannot_absorb` 这类英文码值 |
| 无免责表述 | 现有禁词表 |
| 取最新正确 | 同对象插两条同 `run_date` 不同 `created_at`，必须读到晚的那条 |
| 降级可用 | 结论库整个移走，页面仍能渲染 |

---

## 9. 现在的状态

**已经能跑**：结论带在页面上，五条渲染正常；结论库两表已建并种了一条真实 run；
读取路径与规则兜底路径都实测走通过。

**还没做**：手动重跑按钮只有外观，还没接通路（要加 `MODULE["tasks"]` 声明和
`/api/inventory/verdict` 路由）；上面八条门禁还没落成测试；真 Agent 未接。

**给你的最小起步**：读产品包算出五条判断，按 4.1 的两张表写进
`verdict_agent.sqlite`，`method_version` 填 `inv-verdict-v1`，
`created_at` 必填。写完刷新页面就能看到，不需要我改代码。
