# 竞品 Agent 输出点盘点

版本 v1.0（2026-08-31）· 按 `v0.1.0/competitor_demo.sqlite` 落盘 schema 逐列核对，
不是按 `02-竞品Agent接口契约.md` 抄的 —— 那份是双库时代写的（`fact_analysis_*`），
表名和库结构后来都变了。**以本文档为准。**

---

## 0. 先分清：Agent 读什么、写什么、写到哪

**读的库和写的库不是同一个。**

| | 库 | 表 | Agent |
| --- | --- | --- | --- |
| 观察层 | `08-竞品分析模块/02-数据构建/v0.1.0/competitor_demo.sqlite` | `dim_competitor_family/child/offer/keyword`、`bridge_competitor_child/keyword`、`fact_competitor_price_daily/market_daily/keyword_rank/traffic_mix/data_status`、`competitor_manifest` 共 12 张 | **只读输入** |
| 同上 | 同上 | `dim_competitor_scenario` | **禁读**，见 0.2 |
| 同上 | 同上 | `fact_competitor_analysis_*` 9 张（构造的） | **禁读**，已成 legacy，前端也不再读 |
| **Agent 输出** | `09-工作台/modules/competitor/derived/competitor_agent_state.sqlite`<br>环境变量 `WORKBENCH_COMPETITOR_AGENT_DB` 可覆盖 | 判断层 10 张 + 执行台账 `fact_competitor_agent_execution` | **只写输出**，前端从这里读 |
| 产品包 | `bamboocool_product_sales_inventory_v0.3.0.sqlite` | `dim_product_child`（脊椎 342 子 / 5 父）、`fact_child_price_daily` | 读（自有身份与自有件单价） |

**Agent 一次运行 = 针对一个竞品产品族（父 ASIN），往 Agent 状态库的 10 张表各写若干行 +
往执行台账写一行。** 列名必须与第 2 节逐字一致——前端 `SELECT *` 后按列名取值，少一列直接报错。
库结构与前端读取规则见 `05-Agent交底包.md` 第 4 节。

### 0.1 第三类字段：写入端盖章，Agent 不要输出

10 张表里有一批列**不属于 Agent 的输出面**。它们要么是身份与时序（写入时才知道），
要么需要跨 run 的全局视野（单对象重跑的 Agent 物理上拿不到）。
Agent 提交一批**行**，写入端补齐这些列后落库。

| 字段 | 表 | 为什么不能由 Agent 给 | 写入端怎么定 |
| --- | --- | --- | --- |
| `run_id` | run + 全部 9 张子表 | 是这次运行的身份，运行开始时才分配 | `{family_asin}-{run_date}-{当日第几次}`；子表行由 Agent 按局部序号提交，写入端统一盖上 |
| `created_at` | run / report / handoff | 写入时刻 | 落库时间戳；**同族同日多跑必须互不相同**（门禁 G8） |
| `report_id` | report | 旧格式 `RPT-{period_to}-{item_seq}` 末段是**报告内全局排位**，单对象重跑算不出来 | `RPT-{ref_run_id}-{该 run 内第几条}`，单行即可推导（门禁 C7） |
| `item_seq` | report | 同一个全局排位问题。**这是本次修正的连带项**：id 里不该有它，字段本身也不该由 Agent 给 | 写入端扫完该周期全部候选后排定；`1` 上洞察带 |
| `scope_key` / `period_from` / `period_to` | report | 报告范围与周期是编排层的事 | 从报告任务参数取 |
| `ref_run_id` | report | 就是本次 run_id | 直接盖 |
| `handoff_id` | handoff | 旧格式 `HO-{family_asin}-{KW\|AD}` 既不含 run 也不含日期，**同族同页第二次交接会撞主键** | `HO-{frozen_run_id}-{KW\|AD}`（门禁 C8） |
| `frozen_run_id` | handoff | 就是本次 run_id | 直接盖 |
| `prev_run_id` | diff | 需要查库找上一次运行 | 写入端解析。注意 Agent 判 `transition`/`statement` 时**仍需把上一次 run 作为输入读到** |

**只是请求回填、不是判断产物**：`run` 表的 `family_asin`、`run_date`、`data_as_of`、
`window_from`、`window_to`、`trigger` 全部来自触发请求（交底包 1.2 的请求体）。
写入端从请求原样盖上即可，Agent 不必自己拼。

**同名但归属不同，别混**：`timeline` / `open_item` 的 `item_seq` 是**该 run 内的局部序号**，
`change_seq` / `pair_seq` / `reason_seq` / `impact_seq` 同理，这些**是 Agent 给的**——它们表达
的是本次运行内部的重要性排序，Agent 知道。只有 `report.item_seq` 是跨 run 的全局排位。

### 0.2 不给 Agent 读的：判断层全部 10 张表 + 形态标注表

> 依据 `00-通用方法与规范/08-Agent需求与数据契约要则.md` §3 / §6 / §11。
> **这一节比 0.1 和第 2 节都重要**：漏一张输入表只是少信息，Agent 会说判断不出；
> 漏一列禁读就是答案泄漏，**而且没有任何症状**——门禁全绿，页面正常，Agent 变复印机。

本项目为了让前端能跑，用 `03_build_analysis.py` 把 20 次分析的**结论**整套构造出来了。
这些行是给前端渲染用的，**不是给 Agent 参照的答案**。

| 禁读 | 它已经替 Agent 答了什么 |
| --- | --- |
| **`dim_competitor_scenario` 全表** | 最危险的一张。它是 `family_asin → 形态名 + 该得出什么结论` 的答案键，例如「B0FNQYP7DW / 活动型 / Coupon-Deal 开始→结束→价格恢复，价差先扩大后收窄」。读了它等于开卷考试 |
| `analysis_run.attention_level` / `evidence_level` | 该不该优先看、证据够不够——**分级结论本身** |
| `analysis_run.attention_summary` / `evidence_reason` / `judgment_summary` | 为什么，已成文的中文理由 |
| `analysis_change` **全表** | 有哪些变化、方向、幅度、起止、当前状态、代不代表整族、依据是什么 |
| `analysis_timeline` 全表 | 事件怎么分轨、事件前后可比窗口取哪一段 |
| `analysis_concurrency` 全表 | 哪两条变化同期、能不能升级为因果、还缺什么证据 |
| `analysis_attention_reason` 全表 | 关注分级的依据条目与权重定性 |
| `analysis_impact` 全表 | 可能影响哪些自有产品与关键词 |
| `analysis_open_item` 全表 | 有哪些假设与待观察、需要补什么数据 |
| `analysis_diff` 全表 | 与上一版相比是加重还是减弱 |
| `analysis_report` 全表 | 本周期挑哪几条、怎么讲 |
| `evidence_handoff` 全表 | 该交什么给下游 |
| 各观察表的 `value_origin` | 哪些行是我们造的——构造元数据，且是 G9 禁上屏的英文码值。**证据够不够要从 `fact_competitor_data_status` 判**（断更/冲突/过期是真实业务可观察的数据健康事实），不是从「这行是不是造的」判 |

**唯一的例外，且有代价**：算 `diff.transition`（较上次加重/减弱）必须读到上一次运行的结论。
按要则 §7，**上游 Agent 本次运行的产出可以给，我们预烤的判断不可以**。当前包里那 20 个 run 全是预烤的，
所以：**首次真跑时没有合法的上一版可比，`diff` 必须显式降级说明「无可比上一版」，不许回落去读预烤的 run**。
第二次起读的是 Agent 自己上一次的产出，合法。

### 0.3 职责表：Agent 判什么，工作台算什么

| Agent 产出（判断） | 工作台算（确定性算术，参数面板改完立刻重算） |
| --- | --- |
| 变化是否成立、是哪一类、代不代表整族 | 四类版图的去重族数计数 |
| 变化的方向与幅度量级 | 比较表 40 点趋势线的降采样 |
| 关注分级 + 至少两条可解释依据 | 比较表排序（关注/最近/价差倍数/排名） |
| 同期关系的四态判定与「还缺什么」 | 时间线区段的坐标、同轨重叠分层 |
| 影响范围的自有一侧与压力维度 | 自有件单价、价差倍数（走 ATTACH 产品包实时算） |
| 假设与待观察、需要补什么数据 | 观察层四类的新鲜度与状态计数 |
| 与上一版比较的定性（受 0.2 例外约束） | 洞察带取第几条、「另有 N 条」 |
| 报告选题与四段文案 | 中文词表映射（真实/推导/模拟/混合、正常/过期/缺失…） |

**不许出现在 Agent 输出里的**：综合威胁分数、广告动作/预算/出价、跨模块动作、因果断言、
逐日库存或覆盖天数这类算术、对自己不确定性的辩护。详见第 4 节。

---

## 1. 输出点总表

| # | 表 | 一行代表 | 现有量 | 页面落点 |
| ---: | --- | --- | ---: | --- |
| 1 | `fact_competitor_analysis_run` | 一次分析的台账（每族每次一行） | 20 | 详情判断带 + 比较表证据列 + 排序主键 |
| 2 | `fact_competitor_analysis_change` | 一条变化结论 | 25 | 计数带四类 + 比较表四列 + 时间线区段 + 事实段 |
| 3 | `fact_competitor_analysis_timeline` | 时间线上一个区段 | 27 | 共同时间线四轨 |
| 4 | `fact_competitor_analysis_concurrency` | 两条变化之间的同期关系 | 4 | 「不能确认的因果」段 |
| 5 | `fact_competitor_analysis_attention_reason` | 关注等级的一条依据 | 37 | 详情 hero 下的依据列表 |
| 6 | `fact_competitor_analysis_impact` | 一条可能影响范围 | 8 | 「可能影响的自有产品与关键词」 |
| 7 | `fact_competitor_analysis_open_item` | 一条假设或待观察 | 12 | 「分析假设与待观察」段 |
| 8 | `fact_competitor_analysis_diff` | 与上一版的比较结论（每 run 一行） | 20 | 比较表「较上次 …」+ 记录区 |
| 9 | `fact_competitor_analysis_report` | 动态报告的一条 | 6 | 总览洞察带（只上第 1 条，其余算「另有 N 条」） |
| 10 | `fact_competitor_evidence_handoff` | 一条交给下游的证据 | 5 | 记录区「交给关键词页 / 广告页」 |

---

## 2. 逐表字段规格

标注含义：**上屏** = 用户直接看到；**内部** = 只用于连接、排序、门禁；**未用** = 当前前端没读（见第 6 节）。

### 2.1 `fact_competitor_analysis_run` — 一次分析的台账

| 字段 | 必填 | 取值 | 用途 |
| --- | :---: | --- | --- |
| `run_id` | 盖 | `{family_asin}-{run_date}-{seq}`，例 `B0FNQYP7DW-2026-08-03-1` | **写入端盖章**（0.1）；内部 + 记录区上屏 |
| `family_asin` | ✓ | 竞品父 ASIN，必须在 `dim_competitor_family` 里 | 内部 |
| `run_date` | ✓ | `YYYY-MM-DD` | 上屏「本次分析 2026-08-03」 |
| `data_as_of` | ✓ | 本次用到的观察数据截止日 | **未用** |
| `window_from` / `window_to` | ✓ | 观察窗，当前 `2026-02-05` ~ `2026-08-03` | 上屏 + 图表横轴 + 门禁 G4 |
| `trigger` | ✓ | `scheduled` 周期跑 / `priority` 重点竞品必跑 / `manual` 运营在页面点「重新分析」 | 上屏（映射中文）；三个取值对应三条入口，见交底包 1.1–1.2 |
| `model_version` | | 自由文本 | 内部 |
| `attention_level` | ✓ | `high` 优先处理 / `medium` 持续关注 / `low` 留观 / `none` 无需处理 | 上屏 hero 28px + 比较表左侧语义色条 + 排序主键 |
| `attention_summary` | ✓ | **中文一句话**，直接上屏 | 上屏 hero 下一行 + 比较表摘要 |
| `evidence_level` | ✓ | `sufficient` 证据充分 / `partial` 证据部分 / `insufficient` 证据不足 | 上屏 + 控制降级分支 |
| `evidence_reason` | ✓ | **中文**，说明证据为什么够或不够 | 上屏「为什么」浮层 |
| `judgment_summary` | | **中文，业务判断**：这个竞品身上在发生什么、要不要管。**不要重复 `evidence_reason`**——那句讲证据够不够，这句讲结论是什么。两句说同一件事等于白占一格 | **未用** |
| `created_at` | 盖 | ISO 时间戳 | **写入端盖章**；同日多跑靠它分先后 |

**硬规则**

- 不设 `is_latest`。工作台按 `run_date DESC, created_at DESC` 自己取最新，所以**同族同日多跑时 `created_at` 必须不同**（门禁 G8）。
- `evidence_level = insufficient` 时 `attention_level` 必须是 `none`，且**不许写任何 `attention_reason`**（门禁 G2）。
- `attention_level != none` 时至少 2 条 `attention_reason`（门禁 G3）。
- **不给综合威胁分数。** 库里没有分数列，等级 + 依据条目就是全部。

### 2.2 `fact_competitor_analysis_change` — 变化结论（最重要的一张）

| 字段 | 必填 | 取值 | 用途 |
| --- | :---: | --- | --- |
| `run_id` + `change_seq` | 盖 / ✓ | 主键。`run_id` 写入端盖；**`change_seq` 由 Agent 给**，越小越重要，比较表和版图按它取首条 | 内部 |
| `domain` | ✓ | `price_promo` 活动与价格 / `market` 市场表现 / `keyword` 关键词位置 / `traffic` 流量结构 | 上屏四类计数带 + 比较表分列 + 时间线分轨 |
| `object_level` | ✓ | `family` / `child` / `offer` / `keyword` | 内部（门禁 G5 校引用完整性） |
| `object_id` | ✓ | 对应层级的真实键：父 ASIN / 子 ASIN / `offer_id` / 关键词原文 | 上屏（事实段右侧）+ 门禁 G5 |
| `label` | ✓ | **中文短标签**。句式＝`维度 + 幅度 + 当前状态`，≤ 24 字，结论先行不带铺垫 | 上屏版图 / 比较表 / 时间线条 / 事实段标题 |
| `direction` | ✓ | `up` / `down` / `neutral` | 上屏幅度颜色 |
| `magnitude_kind` | | `pct` / `rank` / `position` / `units`；无量级留空 | 上屏「+/−N%」「−34」 |
| `magnitude_value` | | 数值，降价用负数 | 同上 |
| `date_from` | ✓ | 落在 run 的窗口内（门禁 G4）。**例外：月粒度 domain 报所属统计区间的真实起点**，见下方「时间粒度」 | 上屏发生时间 + 时间线左端 |
| `date_to` | | 空 = 仍在持续 | 时间线右端 |
| `current_state` | ✓ | **中文**：仍在进行 / 已恢复 / 已结束 / 无法确认 | 上屏 |
| `represents_family` | ✓ | `1` 可代表整族 / `0` 只保留在局部对象 | 上屏「仅局部对象」+ 门禁 G6 |
| `coverage_note` | | **中文**。句式＝`命中范围 + 是否主销 + 该族分母`，只在 `represents_family=0` 时必要 | 上屏事实段 |
| `value_origin` | ✓ | `direct` / `derived` / `constructed` | 内部，读取边界映射成 真实 / 推导 / 模拟 / 混合 上屏 |
| `confidence` | ✓ | `high` / `medium` / `low` | **未用** |
| `basis` | ✓ | **中文一句话依据**。说的是「从哪条观察序列的什么形态看出来的」，引用的数字必须与观察层同口径值核得上 | 上屏事实段第二行 |

**硬规则**

- `represents_family = 0` 的变化**不许被任何 report 条目当整族结论引用**（门禁 G6）。
- 价差类结论（label 含「价差」）的对象 `pack_resolved` 必须为 1（门禁 G11）——装盒数解析不出的对象不能进价差结论，因为件单价算不出来。
- 四个 domain 各至少 3 个族有变化，否则总览有一类版图是空的（门禁 G10）。

**时间粒度：日粒度对齐窗口，月粒度对齐区间。**

| domain | 源表粒度 | `date_from` 该报什么 |
| --- | --- | --- |
| `price_promo` / `market` | 逐日（`2026-02-05 ~ 2026-08-03`，180 天） | 变化起始那一天，必落在窗口内 |
| `keyword` | 周 / 月混合（27 个观测日） | 观测日，必落在窗口内 |
| `traffic` | **月度**（`period_start` 取月初：`2026-02-01`、`2026-03-01` …） | **所属月份的真实 `period_start`**，含 `window_from` 的那个月起点是 `2026-02-01`，**比窗口起点早，这是对的** |

不要为了让日期落进窗口而把月粒度的起点改写成 `window_from`——那是伪造一个不存在的观测日。
口径不同就分别保留，不强折算。

---

### 2.3 `fact_competitor_analysis_timeline` — 共同时间线区段

| 字段 | 必填 | 取值 | 用途 |
| --- | :---: | --- | --- |
| `run_id` + `track` + `item_seq` | 盖 / ✓ | 主键。`run_id` 写入端盖；`item_seq` 是**该 run 内局部序号**，由 Agent 给 | 内部 |
| `track` | ✓ | `market` 市场结果 / `price_promo` 价格活动 / `keyword` 流量与位置 / `data_status` 证据事件 | 上屏四轨分派 |
| `label` | ✓ | **中文短标签**，条太窄时不显示但 hover 出 | 上屏轨上区段 |
| `date_from` / `date_to` | ✓ / | 空 = 延伸到窗口末 | 上屏区段位置 |
| `ref_change_seq` | | 指回同 run 的 change | 内部 |
| `window_before_from/to`、`window_after_from/to` | | 事件前后可比窗口 | 上屏（点区段出浮层） |
| `note` | | **中文** | 上屏浮层 |

同一轨里**区间重叠的区段会自动分层堆叠**，前端已处理，Agent 照实写就行，不用自己错开。

### 2.4 `fact_competitor_analysis_concurrency` — 同期关系（因果红线所在）

| 字段 | 必填 | 取值 | 用途 |
| --- | :---: | --- | --- |
| `run_id` + `pair_seq` | 盖 / ✓ | 主键。`run_id` 写入端盖；`pair_seq` 由 Agent 给 | 内部 |
| `change_seq_a` / `change_seq_b` | ✓ | 同 run 内两条 change 的序号 | 内部 |
| `relation` | ✓ | `concurrent` 同期 / `sequential` 先后 / `independent` 独立 / `insufficient` 证据不足 | **未用** |
| `overlap_from` / `overlap_to` | | 重叠区间 | 上屏 |
| `statement` | ✓ | **中文**，只能表述为「同期变化」或「可能相关」 | 上屏「不能确认的因果」段 |
| `causal_ready` | ✓ | `0` 不得升级为因果 / `1` 可升级 | 门禁 G7 |
| `missing_evidence` | | **中文**。句式＝`还缺哪一类数据 + 补上了能排除什么替代解释` | 上屏「还缺：…」 |

**硬规则**：`relation = insufficient` 时 `causal_ready` 必须为 0；`causal_ready = 1` 必须给支撑说明（门禁 G7）。当前 4 条全是 `causal_ready = 0`。

### 2.5 `fact_competitor_analysis_attention_reason` — 关注依据

| 字段 | 必填 | 用途 |
| --- | :---: | --- |
| `run_id` + `reason_seq` | 盖 / ✓ | 主键，按序展示。`run_id` 写入端盖；`reason_seq` 由 Agent 给 |
| `label` | ✓ | **中文依据条目**。句式＝`事实 + 为什么它构成关注理由`，一条一句，彼此不重复 |
| `ref_change_seq` | | 指回 change |
| `weight_note` | | **中文定性短语**，说明这条依据凭什么排在前面（持续性 / 幅度 / 覆盖面 / 可信度）。上屏在依据后的括号里。**不写数字权重** |

### 2.6 `fact_competitor_analysis_impact` — 可能影响范围

| 字段 | 必填 | 取值 | 用途 |
| --- | :---: | --- | --- |
| `run_id` + `impact_seq` | 盖 / ✓ | 主键。`run_id` 写入端盖；`impact_seq` 由 Agent 给 | 内部 |
| `own_parent_asin` | ✓ | 必须是脊椎里的父 ASIN | 上屏副行 |
| `own_child_asin` | | 脊椎里的子 ASIN（门禁 G8 校） | 上屏副行 |
| `shared_keyword` | | 共同竞争的词 | 上屏「共同词 …」 |
| `pressure_dimension` | ✓ | `price` / `promo` / `market` / `keyword` / `traffic` | 内部 |
| `statement` | ✓ | **中文**。句式＝`竞品侧事实 + 与自有的可比口径（件单价）+ 承压表现`。禁止写成因果 | 上屏正文 |
| `ref_change_seq` | | 指回 change | 内部 |
| `confidence` | ✓ | `high` / `medium` / `low` | **未用** |

### 2.7 `fact_competitor_analysis_open_item` — 假设与待观察

| 字段 | 必填 | 取值 | 用途 |
| --- | :---: | --- | --- |
| `run_id` + `item_seq` | 盖 / ✓ | 主键。`run_id` 写入端盖；`item_seq` 是**该 run 内局部序号**，由 Agent 给 | 内部 |
| `item_kind` | ✓ | `hypothesis` 分析假设 / `unconfirmed` 待确认 / `watch` 待观察 | 内部（三种同段展示） |
| `statement` | ✓ | **中文** | 上屏 |
| `needed_data` | | **中文**，指名缺的那一类数据（不是泛指「更多数据」） | 上屏「需要：…」 |
| `watch_until` | | `YYYY-MM-DD` | 上屏「观察至 …」 |

### 2.8 `fact_competitor_analysis_diff` — 与上一版比较

| 字段 | 必填 | 取值 | 用途 |
| --- | :---: | --- | --- |
| `run_id` | 盖 | 每个 run 一行 | **写入端盖章** |
| `prev_run_id` | 盖 | 上一次的 run_id | **写入端盖章**；但 Agent 判 `transition` 时仍需读到上一次 run |
| `transition` | ✓ | `new` 新增 / `sustained` 持续 / `escalated` 加重 / `eased` 减弱 / `cleared` 已解除 | 上屏比较表「较上次 …」 |
| `statement` | ✓ | **中文** | 上屏记录区 |
| `changed_domains` | | 逗号分隔的 domain | **未用** |

### 2.9 `fact_competitor_analysis_report` — 动态报告

| 字段 | 必填 | 取值 | 用途 |
| --- | :---: | --- | --- |
| `report_id` | 盖 | `RPT-{ref_run_id}-{该 run 内第几条}`，例 `RPT-B08FTYHMC7-2026-08-03-1-01` | **写入端盖章**（旧格式末段是全局排位，Agent 算不出）；门禁 C7；页面未用 |
| `scope_key` | 盖 | 例「美国站 · 男士内裤 · Men's Boxer Briefs」 | **写入端盖章**；页面未用（范围已在 meta） |
| `period_from` / `period_to` | 盖 | 报告周期 | **写入端盖章**；上屏洞察带 |
| `item_seq` | 盖 | 1 起。**只有第 1 条上洞察带**，其余算「另有 N 条」 | **写入端盖章**——这是跨 run 的全局排位，单对象重跑的 Agent 拿不到 |
| `family_asin` | ✓ | 指向哪个族 | 上屏 + 点进详情 |
| `ref_run_id` | 盖 | 就是本次 run_id | **写入端盖章** |
| `headline` | ✓ | **中文**，就是那条变化本身，不要写「某某近期出现值得关注的变化」这种模板句 | 上屏洞察带主句 |
| `body` | ✓ | **中文**，比较表不重复的部分 | 上屏 |
| `impact_note` | | **中文**，可能影响 | 上屏 |
| `unconfirmed_note` | | **中文**，仍需确认 | 上屏 |
| `created_at` | 盖 | 时间戳 | **写入端盖章** |

**只写关注等级 high / medium 且证据充分的族**，且该族必须至少有一条 `represents_family = 1` 的变化。

### 2.10 `fact_competitor_evidence_handoff` — 交给下游

| 字段 | 必填 | 取值 | 用途 |
| --- | :---: | --- | --- |
| `handoff_id` | 盖 | `HO-{frozen_run_id}-{KW\|AD}`，例 `HO-B0CJ9QLVPP-2026-08-03-1-AD` | **写入端盖章**（旧格式不含 run 与日期，同族同页第二次交接撞主键）；门禁 C8；页面未用 |
| `frozen_run_id` | 盖 | 就是本次 run_id。**下游引用的是这一次分析，不是「最新」** | **写入端盖章**；上屏 + 门禁 G12 |
| `target_page` | ✓ | `keyword` 关键词页 / `advertising` 广告页 | 上屏「交给关键词页 / 广告页」 |
| `family_asin` | ✓ | | 内部 |
| `own_child_asin` / `shared_keyword` / `pressure_dimension` | | | 内部 |
| `observable_fact` | ✓ | **中文**，可观察事实 | 上屏 |
| `evidence_level` | ✓ | 同 run 的证据档 | 上屏 |
| `detail_entry` | ✓ | 详情锚点。格式＝`子ASIN · 起始日 至 截止日 · 该条可观察事实的短标签` | 上屏「引用入口」 |
| `created_at` | 盖 | | **写入端盖章** |

---

## 3. Agent 要写的中文文案槽（一次分析共 12 处）

这是 Agent 真正在生产的东西，其余都是键、日期和枚举。**全部必须是成品中文，工作台直接渲染不做映射。**

| 槽 | 出处 | 长度感 |
| --- | --- | --- |
| 关注一句话 | `run.attention_summary` | 一句，就是最重要那条变化 |
| 证据为什么够/不够 | `run.evidence_reason` | 一句 |
| 给人读的判断 | `run.judgment_summary` | 一到两句**业务判断**（竞品在发生什么、要不要管）。**不要复述 `evidence_reason`** |
| 每条变化的短标签 | `change.label` | 短语，进版图和表格 |
| 每条变化的依据 | `change.basis` | 一句 |
| 覆盖范围说明 | `change.coverage_note` | 一句，只在不能代表整族时必要 |
| 关注依据条目 | `attention_reason.label` + `weight_note` | 每条一句 + 括号一短语 |
| 同期关系表述 | `concurrency.statement` + `missing_evidence` | 一句 + 「还缺什么」 |
| 影响范围 | `impact.statement` | 一句 |
| 假设与待观察 | `open_item.statement` + `needed_data` | 一句 + 需要什么数据 |
| 与上一版比较 | `diff.statement` | 一句 |
| 报告条目 | `report.headline` + `body` + `impact_note` + `unconfirmed_note` | 主句 + 一到两句 |
| 下游交接事实 | `handoff.observable_fact` | 一句 |

**文案红线**（门禁 G9 / G17 会扫）：

- 枚举原值一律不许出现在中文文案里：`price_promo`、`third_party_estimate`、`constructed`、`insufficient`、`sustained`、`hypothesis`、`concurrent` 等。
- 不出现综合威胁分数。
- 因果只能表述为「同期变化」「可能相关」。
- **红线是对行为的约束，不是要在文案里声明你遵守了它。** 第 4 节那些「不许输出」的项，做到就行，
  **不要把它们写进任何上屏字段**。2026-08-31 实测踩到的原句：

  | 字段 | 写成了 | 应该写 |
  | --- | --- | --- |
  | `change.label` | 广告流量占比上行，**不能反推花费预算出价** | 广告流量占比上行 |
  | `change.basis` | …**仅作流量占比参考，不反推花费、预算或出价** | …占比从 X% 升至 Y%，连续 N 天 |
  | `concurrency.statement` | …**仅记同期变化，不判因果** | …两条变化在同一区间同期出现 |
  | `report.unconfirmed_note` | …广告流量占比**仅作参考，不能反推花费、预算或出价**… | …广告流量占比上行的触发原因未确认 |

  判据：把这句话给运营看，他知道了什么新东西？「不能反推出价」他知道的是我们的免责立场，不是竞品动向。
  `concurrency` 这张表本身就只表达同期，不必再声明一次不判因果。

- **不写内部阈值与参数口径。** 「远超阈值」「覆盖率达到阈值」「变化点数远超阈值」「超过最短时长」
  这类话运营看不出是哪个阈值、多少，等于零信息，还把内部机制露出来了。**给真实幅度和真实天数**：
  「件单价从 $4.10 降到 $3.36，降 18%，已持续 135 天」。阈值本身属于参数面板，口径解释收进 ⓘ 浮层。
- 不写免责声明（「本数据不作为判断依据」「阈值待客户确认」这类整句删掉）。

---

## 4. Agent 不许输出的东西

| 不许 | 原因 |
| --- | --- |
| 广告动作、预算、出价 | 属广告模块，方案 §7 边界 |
| 综合威胁分数 | 方案 §5.4 要求分级 + 可解释依据 |
| 竞品库存推断 | 方案边界，准确性不足 |
| 用流量占比反推竞品花费/预算/出价 | 方案红线，`traffic_mix` 是第三方估算 |
| 观察层任何表的行 | 那是抓取层的，Agent 只读 |
| 自有产品维度（`dim_product_child` 等） | 走 ATTACH 产品包读，不重建（契约 6.3） |

---

## 5. 工作台如何消费（Agent 侧要知道的四件事）

**取最新一次**：按 `run_date DESC, created_at DESC` 派生，不看标记位。

**重跑是追加不是覆盖**：点击触发产生的新 run 与当天已有的 run 并存，靠 `created_at` 分先后（门禁 G8）。被替代的那次仍在库里，新 run 的 `diff.prev_run_id` 应指向它。页面自动取到新的那次。

**页面从不同步等 Agent**：三个路由都是只读 GET。点击触发走异步——页面发请求、轮询状态、`done` 后重取载荷。请求体与状态机见交底包 1.2。

**三个降级分支**，Agent 不用管，但要知道漏写会掉进哪个：

| 情形 | 页面行为 |
| --- | --- |
| 观察库有该族、Agent 库无 run | 三个事实看板照常显示（都读观察层），结论区写「尚未纳入分析」 |
| 有 run 但 `evidence_level = insufficient` | 不给关注等级、不进计数带、不进报告；只显示证据不足原因与待补数据 |
| 该族不在抓取名单（无历史） | 只给当期快照事实，不给任何变化结论 |

**新鲜度不告警**：页面客观显示「分析于 X 日 · 周跑」，不涂红、不排异常。

---

## 6. 三个「Agent 输出了但当前没上屏」的字段

写 Agent 时可以先填上，但要知道现在看不到；要看得到得改前端：

| 字段 | 现状 | 建议 |
| --- | --- | --- |
| `run.judgment_summary` | Agent 那句人读的判断被丢掉了 | **建议接上**：详情判断带里 hero 下面就该是它，现在那里放的是 `attention_summary` |
| `run.data_as_of` | 观察数据截止日没显示 | 建议接进判断带「数据截止」，与顶栏 as_of 区分开 |
| `change.confidence` / `impact.confidence` | 可信程度没上屏 | 可选。要上就和 `value_origin` 映射的「真实/推导/模拟」并列，别两套并存 |
| `concurrency.relation` | 只显示 `statement` | 可选。四态（同期/先后/独立/证据不足）做成标签会更清楚 |
| `diff.changed_domains`、`report.report_id`、`report.scope_key`、`handoff.handoff_id` | 纯内部 | 保持内部即可 |

---

## 7. 验收：Agent 写完拿这 12 条自查

跑 `08-竞品分析模块/03-验收/test_contract_gates.py`（当前 20/20 全绿）。判断层相关的 12 条：

| 门禁 | 断言 |
| --- | --- |
| G1 | 每个 run 至少 1 条变化，且 `label` / `basis` 非空 |
| G2 | 证据不足的 run 没有关注等级、没有依据条目 |
| G3 | 有关注等级的 run 至少 2 条依据条目 |
| G4 | 每条变化的 `date_from` 落在该 run 的窗口内；月粒度 domain 按所属区间起点判，允许早于 `window_from` 但不得早于含 `window_from` 的那个区间之首 |
| G5 | 每条变化的 `object_id` 在观察层对应层级找得到 |
| G6 | `represents_family = 0` 的变化没被报告当整族结论引用 |
| G7 | `causal_ready = 1` 有支撑说明；`relation = insufficient` 时必须为 0 |
| G8 | 同族同日多个 run 的 `created_at` 互不相同 |
| G9 | 所有中文文案字段零枚举原值泄漏 |
| G10 | 四个 domain 各 ≥3 个族有变化；数据状态三态齐备 |
| G11 | 价差类结论的对象装盒数已解析 |
| G12 | `handoff.frozen_run_id` 指向的 run 存在 |

门禁必须打在真有该特征的对象上：`evidence_level = insufficient` 那条要指名到具体族（现在是 `B0D7D246LV`），不然一个证据充分的族上跑全绿等于没测。

---

## 8. 这里原来有一张「族 → Agent 该给出的结论骨架」表，已删除

删除原因：它把 `dim_competitor_scenario` 的形态标注逐族抄成了「这个族你该得出什么结论」，
是答案键。照它写出来的 Agent 会在这 12 个族上复现构造脚本的结论，门禁全绿、页面正常，
但没有任何判断真的发生。参见要则 §0 的广告实测——真模型落库内容与事实桥输出逐字节相同。

**别再加回来。** 需要验证 Agent 在各种形态上都能工作时，用下面这种不泄漏答案的方式：

| 要验的 | 怎么验 |
| --- | --- |
| Agent 真在判断，不是套模板 | 同一个族连跑两次，允许结论不同。两次逐字节相同 → 复印机（要则 §11 自检第 4 条） |
| 结论跟着对象的特征变 | 换一个观察序列形态明显不同的族，结论必须变。不变 → 模板或只有少数族有数据 |
| 覆盖面够 | 20 个族跑完，四类 `domain` 都出现过、`attention_level` 四档都出现过、至少一个族判成证据不足。**但不指定是哪个族**——那是判断结果 |
| 引用的数字没编 | 每条 `basis` 里的数字与观察层同口径值交叉核对（要则 §10：钉「不许编数字」，不钉「结论必须是这一个」） |

构造数据在观察层确实铺了活动、阶梯降价、排名上行/下行、关键词抢位/丢失、局部变化、
报价变更、断更冲突过期、平稳对照这些形态——**这是输入侧的构造，合法**（要则 §6）。
Agent 应该能从这些序列里各自读出不同的东西，但读出什么由它判断，不由我们给。
