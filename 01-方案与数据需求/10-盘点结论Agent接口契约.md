# 盘点结论 Agent 接口契约

版本 **v0.2** · 2026-08-31 · 状态：**设计待拍，未落代码**

v0.2 改了什么：v0.1 把架构写成「页面算好事实打包给 Agent」，那是错的。
正确形态是 **Agent 与页面各自读同一份数据表**，Agent 离线跑完落库，页面读上次结果。
差别不只是措辞 —— v0.1 那套里 Agent 只能在页面打开时才跑，页面也就无法「加载上次跑的静态数据」。

配套必读：`07-预测Agent接口契约.md`（需求预测 Agent，本文沿用它 §0 的职责切法与
§1 的两库 ATTACH 模式）、`09-外壳与Agent交互交接.md`（Agent 接入机制九条）、
`../00-通用方法与规范/02-模块接入契约.md` v1.3。

---

## 0. 要解决什么

单品盘点页现在**没有结论先行**。首屏只有一句「预计 2026-08-08 库存见底」，
其余四类判断散在下面八个板块里，运营得自己往下翻、自己汇总。

而且那一句不是判断，是模板：`compute.py` 的 `build_risks()` 里
第 567 / 594 / 632 / 660 / 692 行五个 f-string 拼出来的。
对 342 个对象说同一种结构，不会因为「这批货来不及」而改变说法。

三件事：

1. **删掉**板块标题旁的数据性质标注（`● 真实 身份属性 · ● 派生 盘点结论`）。
   它对运营没有决策价值，而且把盘点结论标成「派生」本身就不对 —— 结论该来自 Agent。
2. **在两个灰框上面**加结论先行带，五条。板块和灰框位置都不动。
3. **结论由 Agent 判断并落库**，页面读上次运行的结果，标明跑于何时，旁边可手动重跑。

「销量与需求」和「市场表现」两块不动 —— 已确认没问题。

---

## 1. 一个已经存在但没说出来的矛盾

这是设计这件事时抓到的最有说服力的例子，`B0B3LM36WB`：

| 字段 | 值 |
| --- | --- |
| `scopes.sellable_only.cover_days` | 4.6 天 |
| `scopes.sellable_plus_confirmed.cover_days` | **49.4 天** |
| 两个口径的 `stockout_date` | 都是 **2026-08-08** |
| 首笔已确认到货 `arrivals[0].eta` | **2026-08-28**，609 件 |

覆盖 49.4 天是把 609 件在途算进来的结果，但那批货 **08-28 才到，比断货晚 20 天**。
所以「覆盖 49.4 天」和「08-08 断货」同时为真，而页面把它们并排摆着不解释。

**结论带的第一个职责就是把这种事说成一句话**：
「货在路上，但来不及 —— 08-08 断货，最近一批 08-28 到，中间空 20 天。」

页面写不出这句：它只有两个数，没有「哪个更要紧」的取舍。
写死也不对：换个对象（到货在断货之前）逻辑就反了。这正是判断层该干的活。

---

## 2. 五条结论

顺序按**时间紧迫性**排，不按字母也不按数据表顺序。

| # | 这一条 | 回答哪个问题 | 读哪些表 |
| --- | --- | --- | --- |
| 1 | **库存是否安全** | 未来 90 天够不够，把到货算进来够不够 | `fact_inventory_snapshot`、`fact_child_forecast_daily`、`plan_child_supply_event`、`config_child_inventory_policy` |
| 2 | **什么时候断货** | 断在哪天，误差多大 | 同上（三档需求各投一遍出区间） |
| 3 | **在途货件** | 有没有缺损、有没有长时间未到、来不来得及 | `plan_child_supply_event`、`fact_child_inventory_daily.received_units` |
| 4 | **库存积压** | 是不是压太多、多久能消化 | `fact_inventory_age_bucket_asof`、`fact_inventory_lot`、`fact_child_forecast_daily` |
| 5 | **仓储费** | 花了多少、值不值得动 | `fact_inventory_age_bucket_asof`、`fact_unit_economics`、`fact_child_sales_monthly` |

第 3 条有数据缺口，见第 7 节。

---

## 3. 职责切法：两边读同一份表，各做自己擅长的

沿用 `07 §0` 已定的分界，不新造：

| 谁 | 做什么 | 为什么是它 |
| --- | --- | --- |
| **需求预测 Agent** | 未来 90 天逐日需求 + 区间 + 调整项依据 | 判断历史有没有被缺货扭曲、活动影响多大、生命周期在哪段 |
| **工作台页面** | 逐日余额、覆盖天数、安全线突破日、断货日、缺口、超量、承接、五类风险 | 这些是确定性算术，留在页面参数面板才能即时重算 |
| **盘点结论 Agent**（本文新增） | 五条结论的定性、先后、措辞、依据 | 综合多个维度取舍，这是 LLM 不可替代的部分 |

**关键一点：盘点结论 Agent 不读页面，它读表。**

它和页面是数据层的两个平行消费者，各自从同一批表算出同一批数字。
页面把数字按写好的规范显示；Agent 拿同一批数字做综合判断并写成中文。

这样切有三个实际好处：

1. **Agent 能离线跑。** 不依赖页面打开，可以定时批跑，也可以运营点一下跑单个对象。
   如果 Agent 要靠页面喂事实，页面不开它就跑不了。
2. **页面秒开。** 页面读上次运行的结论，不等 LLM。
3. **两边可以互相校验。** 同一份表算出来的数字应该一致，不一致就是有一边错了 ——
   这是第 8 节那条交叉核对门禁的由来，也是「算法底表可核验」在界面之外的形态。

> **和「v0.3.0 当静态快照、不做回填」那条决定不冲突。** 那条管的是**需求预测**：
> 预测不重跑、不取最新、不写回。本文新增的是**结论库**，它本来就要被写
> —— 运营点「进行产品分析」就是要产生一条新记录。两个库分开，互不影响。

---

## 4. 结论库：`verdict_agent.sqlite`

沿用 `07 §1` 的两库模式，页面用 `ATTACH DATABASE` 挂上跨库 join。
产品包只读、不动；结论库由 Agent 写、页面只读。

### 4.1 `fact_child_verdict_run` —— 批次台账

```sql
CREATE TABLE fact_child_verdict_run (
  run_id        TEXT PRIMARY KEY,   -- {child_asin}-{run_date}-{seq}
  child_asin    TEXT NOT NULL,
  run_date      TEXT NOT NULL,      -- YYYY-MM-DD
  data_as_of    TEXT NOT NULL,      -- 本次用的数据截止日（应等于产品包 as_of）
  trigger       TEXT NOT NULL,      -- weekly | manual | priority
  model_version TEXT,
  method_version TEXT,              -- inv-verdict-v1
  input_forecast_run_id TEXT,       -- 用了哪一次需求预测，可追溯
  created_at    TEXT NOT NULL       -- 同日多次运行的排序依据，必填
);
CREATE INDEX idx_verdict_run ON fact_child_verdict_run(child_asin, run_date DESC, created_at DESC);
```

**`created_at` 的格式：ISO 8601 **带偏移**，例如 `2026-08-31T06:57:01+08:00`。**

这条是实测踩出来的，不是洁癖。Agent 第一次注入给的是 `2026-08-30T22:56:12.869Z`（UTC 带 Z），
第二次给的是 `2026-08-31T06:57:01`（本地无偏移）—— 同一个 Agent 两种格式，
而两者实际都是本地 08-31 06:56 / 06:57。

如果页面按 `created_at` 的**字符串**取最新（原来就是这么写的），
带 Z 的那条会被判成 08-30，于是排在 06:22 的记录之前 ——
**更新的结论被更旧的盖掉，而界面上没有任何症状**。已用探针复现并修掉：
页面现在先按 `run_date` 取最新那天，再在同一天里按**解析后的时刻**选最晚，
带偏移的按偏移算、不带的按本地时区算。

读取端保持宽容（两种格式都能正确排序），但写入端请统一给带偏移的形式 ——
读取端硬要求只会变成「数据没错但页面读不到」。

`created_at` 必填、**不设 `is_latest` 标记位** —— 两条都照 `07 §2.1` 的理由：
运营点一下就重跑，一天内可能跑两次，`run_date` 分不出先后；
而标记位一旦因中断留下两个 1，页面会静默读错且没有任何症状。
页面按 `run_date DESC, created_at DESC` 自己取最新。

### 4.2 `fact_child_verdict_item` —— 五条结论

```sql
CREATE TABLE fact_child_verdict_item (
  run_id      TEXT NOT NULL,
  block       TEXT NOT NULL,   -- safety | stockout | in_transit | overstock | storage_fee
  ord         INTEGER NOT NULL,-- Agent 定的展示先后（最要紧的在前）
  state       TEXT NOT NULL,   -- 中文，固定词表，见下
  verdict     TEXT NOT NULL,   -- 一句话结论，直接上屏
  because     TEXT,            -- 依据，点 ⓘ 才展开
  refs        TEXT,            -- JSON 数组，指向页面哪些板块，供下钻
  numbers     TEXT,            -- JSON 对象：这条引用到的数字，供交叉核对
  PRIMARY KEY (run_id, block)
);
```

**`state` 只能取固定词表。** 不在词表内的值页面会落到灰色兜底 ——
库存模块踩过一次（泳道颜色键大小写不符，导致所有泳道同色，颜色唯一的作用被抹掉）。

| 这一条 | 允许的 state |
| --- | --- |
| safety | `安全` / `偏紧` / `不安全` |
| stockout | `窗口内不断货` / `即将断货` / `已断货` |
| in_transit | `正常` / `来不及` / `有逾期` / `无在途` |
| overstock | `正常` / `偏多` / `积压` |
| storage_fee | `正常` / `偏高` |

**`numbers` 存的是这条结论引用到的数字**，例如
`{"stockout_date":"2026-08-08","first_eta":"2026-08-28","gap_days":20}`。
它不是给人看的，是给第 8 节那条交叉核对门禁用的。

**三条硬约束**

1. `verdict` / `because` 里不许出现英文枚举（`cannot_absorb` 这类）。契约 G9，泄漏过一次。
2. 不许出现免责或口径辩护句。被删的口径限制进数据缺口文档，不上屏。
3. `verdict` 是**一句话**。它要在首屏一行里读完，写成一段就失去「结论先行」的意义。

---

## 5. 页面怎么读

```sql
ATTACH DATABASE 'verdict_agent.sqlite' AS vd;

SELECT i.*, r.run_date, r.created_at, r.trigger
FROM   vd.fact_child_verdict_item i
JOIN   vd.fact_child_verdict_run  r USING (run_id)
WHERE  r.child_asin = ?
  AND  r.run_id = (
         SELECT run_id FROM vd.fact_child_verdict_run
         WHERE child_asin = ?
         ORDER BY run_date DESC, created_at DESC LIMIT 1)
ORDER BY i.ord;
```

**没有结论时**（Agent 还没跑过这个对象、或结论库不存在）：
页面用现有确定性规则填这五条，数据性质标「派生」。
**界面上不写「未经 Agent 复核」这类话** —— 那是防御性表述，徽标已经把话说完了。

---

## 6. 前端呈现

**位置**：「产品与盘点结果」板块**保留**，两个灰框（市场表现 / 经营）位置**不动**。
结论带插在板块标题与灰框之间 —— 也就是现在那一句「预计 2026-08-08 库存见底」的位置，
把一句换成五条。标题旁的数据性质 chip 行删除。

**形态**：五行，每行 = 状态圆点 + 这一条的名字 + 一句话 + 右侧关键数字 + ⓘ。
点 ⓘ 出 `because`；点整行滚到 `refs` 指的板块。
**不做卡片网格** —— 五个等权卡片会让眯眼测试失败，视线落不到最紧急的那条。

**排序**：按 `ord`（Agent 定），最要紧的在最上面。

**跑于何时 + 手动重跑**：结论带右上角一行小字「跑于 2026-08-31 05:12 · 手动」，
紧邻一个「进行产品分析」按钮。按钮走外壳的 `MODULE["tasks"]` 声明，
外壳零硬编码（`09-外壳与Agent交互交接.md` §3）：

```python
"tasks": [
    {"id": "inv-verdict", "label": "进行产品分析", "needs": "object",
     "run": "verdict", "hint": "读同一份数据表，重新给出五条盘点结论"},
]
```

**层级**（走 `06-视觉基准要则.md` 的七级，不新增档位）：

| 元素 | 档位 |
| --- | --- |
| 「盘点结论」小标题 | `--fs-meta` 13 |
| 每条的 `verdict` | `--fs-sub` 16（整句陈述归 16，22 留给指标值） |
| 这一条的名字 + state 徽标 | `--fs-meta` 13 |
| 右侧关键数字 | `--fs-value` 22（日期与复合值）/ `--fs-num` 30（单个数字） |
| 「跑于 …」与 `because` 正文 | `--fs-anno` 12 / `--fs-body` 14 |

---

## 7. 数据缺口：第 3 条的「缺损」与「长时间未到」

实测 v0.3.0 的 `plan_child_supply_event`（684 笔）：

- 字段只有 `planned_units / eta_earliest / eta_latest / event_status / confidence_level`。
  **没有实收数量、没有缺损、没有延误标记。** 全库扫过
  `received / shortage / damag / discrep / actual_units / lost / delay / overdue`，
  只有 `fact_child_inventory_daily.received_units` 是逐日实收，
  但它与 `plan_event_id` 之间没有关联列，接不上。
- **ETA 全部晚于基准日**：本月内到 278 笔（80,057 件，全 confirmed），更晚 406 笔。
  **逾期实例为零** —— 「长时间未到」在这份数据里演不出来。

两条路：

**A. 下一版数据包补三列** —— `plan_child_supply_event` 加
`received_units`（实收）、`received_at`（实收日）、`discrepancy_reason`（差异原因，中文成品文案），
并让一部分事件 ETA 落在基准日之前形成逾期实例。这样第 3 条才有内容可判。

**B. 本期只判「来不来得及」** —— 用已有的 `eta` 对比断货日，
state 取 `正常 / 来不及 / 无在途`，`有逾期` 这一档暂不启用。不编造缺损数据。

倾向 **B 先上、A 排进下一版数据包**：B 用真实数据就能演出第 1 节那个强场景，
已经比现在好很多；A 需要数据方配合，不该卡住页面。

---

## 8. 门禁

| 门禁 | 断言 |
| --- | --- |
| 五条齐全 | 五个 `block` 必须都有 item，缺一个就是输出不合契约 |
| state 在词表内 | 逐条比对允许值，不许落到灰色兜底 |
| **交叉核对数字** | Agent 落在 `numbers` 里的每个值，与页面按同口径算出的值比对，超出容差判不一致。**两边读同一份表就该得到同一批数字，这条是那句话的可验证形式** |
| 一句话 | `verdict` 长度上限，防止写成一段 |
| 无枚举泄漏 | 扫 `cannot_absorb` 这类英文码值 |
| 无免责表述 | 沿用现有禁词表 |
| 取最新正确 | 同一对象插两条同 `run_date` 不同 `created_at` 的记录，页面必须读到晚的那条 |
| **混格式时间戳仍取对** | 插一条「实际更晚但字符串更小」的记录（如 `…T23:05:00Z` 对 `…T06:57:01`），页面必须取到实际更晚的那条。**这是已复现过的静默错误** |
| 降级可用 | 结论库整个移走，五条仍能由确定性规则填满且页面不报错 |
| 打在真有特征的对象上 | 至少一个「有在途但来不及」的对象（`B0B3LM36WB` 现成）+ 一个零风险对象作对照 |

最后一条是这个项目反复付过学费的：门禁跑在没有该特征的对象上，全绿等于没测。

---

## 9. 状态

**已定**（本轮）

- 两个灰框位置不动，结论带插在它们上面，板块保留
- 页面读上次运行的静态结论 + 标明跑于何时 + 旁边可手动重跑
- Agent 与页面各自读同一份表，Agent 不读页面

**待拍**

- 第 3 条（在途货件）走 A 还是 B。倾向 B 先上、A 排下一版数据包。

**实现顺序**（拍完之后）

1. 删 chip 行 + 结论带占位（先用确定性规则填五条，形态先立起来）
2. 结论库 schema + 页面读取与取最新
3. `MODULE["tasks"]` 声明 + 手动重跑通路
4. 九条门禁
5. 接真 Agent
