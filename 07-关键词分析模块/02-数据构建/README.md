# 02-数据构建 · 关键词模块数据库构造说明

基准日（as_of）：**2026-08-03**　　随机种子：**20260803**（确定性，可重复重建）
规则版本：`keyword-demo-rules-v1`　　解释器：`/usr/bin/python3`（3.9.6，本机唯一带 lxml）

这个目录做一件事：把客户的 3 个关键词文件 + 产品包 v0.3.0，
变成工作台能读的 24 表关键词数据包。13 个脚本，其中 5 个的文件名带 `l3` / `l4` / `l56` / `l7` / `l89`
—— **那个 L 是「九层数据」的层号**，不是版本号、不是 level、不是 lib 编号。

---

## 一、先搞清 L 是什么：九层数据

九层是需求文档 `../01-方案与数据需求/02-关键词Demo数据需求.md` §3「必须构造的九层数据」
定的分层，从词本身一层层长到能上屏的日报。层号即依赖顺序：**L(n) 只能读 L(<n)**。

| 层 | 这一层是什么 | 落哪些表（`keyword_demo.sqlite` 里的名字） | 行数 | 谁建 |
| --- | --- | --- | ---: | --- |
| 元 | 本次范围与规则版本 | `dim_keyword_scope` | 1 | `build_keyword_dataset_v010.py` main() |
| **L1** | **共享市场词库** —— 词的四态（有效/待确认/噪声/监控）、运营角色、品牌角色、别名与拼写变体、品牌表 | `dim_keyword_term` 1,991<br>`dim_keyword_alias` 118<br>`dim_keyword_brand` 80 | 2,189 | `build_keyword_dataset_v010.py` → `build_l1()` |
| **L2** | **分类与需求词组** —— 一词多标签、需求词组、关键词1 的运营角色种子、组合词 ABA 档位、与客户「总览」sheet 的对账基线 | `bridge_keyword_attribute` 5,277<br>`dim_keyword_group` 59<br>`bridge_keyword_group` 2,318<br>`dim_keyword_attribute_seed` 162<br>`fact_keyword_attribute_combo` 324<br>`fact_keyword_category_rollup` 11 | 8,151 | `build_keyword_dataset_v010.py` → `build_l2()` |
| **L3** | **市场事实时间序列（★最大缺口）** —— 26 周 + 12 月双频率快照、头部 ASIN 结构 | `fact_keyword_market_snapshot` 77,400<br>`fact_keyword_head_asin` 42,378 | 119,778 | **`lib_l3.py`** |
| **L4** | **覆盖与位置关系（★第二大缺口）** —— 关键词 × 子ASIN × 日期 的自然位 / 广告位 / 五态 / 采集元数据 | `dim_keyword_child_pair` 901<br>`fact_keyword_child_position_daily` 163,982<br>`dim_keyword_state_label` 21 | 164,904 | **`lib_l4.py`** |
| **L5** | **付费侧词级证据** —— 词级自然 Sessions + 广告表现 + 展示量份额，以及归因残差对账 | `fact_keyword_child_traffic_daily` 121,031<br>`fact_keyword_traffic_attribution_daily` 4,938 | 125,969 | **`lib_l56.py`** → `build_traffic()` |
| **L6** | **产品目标与库存承接**（v0.3.0 没有，本模块新增/投影） | `dim_keyword_child_goal` 434<br>`fact_keyword_child_absorb` 342 | 776 | **`lib_l56.py`** → `build_product_context()` |
| **L7** | **变化事件** —— 市场变化与覆盖变化，带 from/to 可下钻复核 | `fact_keyword_market_change_event` 148<br>`fact_keyword_coverage_event` 973 | 1,121 | **`lib_l7.py`** |
| **L8** | **证据与盘点记录** —— 七类证据（结论与依据是中文成品文案）、30 子体 × 3 期盘点 | `fact_keyword_evidence` 562<br>`fact_keyword_audit_record` 90 | 652 | **`lib_l89.py`** |
| **L9** | **动态关键词日报** —— 五问五答 + 可解析的证据引用，14 天各不相同 | `fact_keyword_daily_report` | 14 | **`lib_l89.py`** |

合计 **24 表 / 423,555 行**。

`lib_l56.py` 一个文件管两层，因为 L6 的库存承接要给 L5 的流量上限提供子体口径；
`lib_l89.py` 一个文件管两层，因为 L9 日报直接引用 L8 的证据 id。

⚠️ **`lib_l7.py` 的 docstring 已经过期**：它自称「L7 变化事件 / L8 证据与盘点记录 / L9 动态关键词日报」，
但 L8 / L9 的构建函数早已搬进 `lib_l89.py`。`lib_l7.py` 现在只剩 L7 的两个 `build_*`，
以及被 `lib_l89.py` import 回去复用的四个常量（`RULE_VERSION` / `AS_OF` / `AUDIT_RUNS` / `REPORT_DAYS`）。
按 docstring 去 `lib_l7.py` 里找日报代码会找不到。

---

## 二、构建链

**线性，一条链，没有分叉。** 只有一个版本目录 `v0.1.0/`，不存在库存模块那种多版本并存。

```
客户源文件（只读，从不写）
  /Users/linsen/BAM/数据源/AI广告对接数据-总20260803/10.关键词/
    ├── 关键词3.xlsx   1.1 MB / 15 sheet  ← 主底图
    ├── 关键词2.xlsx   945 KB / 15 sheet  ← 第二来源，与关键词3 真实冲突（840 词的广告竞品数不一致）
    └── 关键词1.html   108 KB / 12 表 / 174 行  ← 运营人工标注的构词矩阵
产品包 v0.3.0（只读，取 342 子体脊椎与当日真实上限）
  /Users/linsen/BAM/02-产品销售库存模块/02-数据构建/v0.3.0/bamboocool_product_sales_inventory_v0.3.0.sqlite
xlsx 读取器（只读复用广告模块的）
  /Users/linsen/BAM/04-广告分析模块/00-源表勘查/xlsxlite.py
        │
        │  ①  lib_kwsrc.py         读源 + 确定性选样（1,991 词库 → 300 监控词 / 342 子体 → 30 重点子体）
        ↓
        │  ②  build_keyword_dataset_v010.py   总装：自己建 L1+L2，逐层调 lib_l3/l4/l56/l7/l89，跑 46 条门禁，落库 + 导 JSON + 写 manifest
        ↓
  v0.1.0/bamboocool_keyword_v0.1.0.sqlite      108.9 MB / 24 表 / 423,555 行   ← 构建原产物，旧表名、旧 value_origin
  v0.1.0/<24 张表>.json + dataset-manifest.json                                ← 同一步导出，文件名用旧表名
        │
        │  ③  verify_v010.py       落盘独立复核 13 条（跑在落盘结果上，不是内存对象上）
        │  ④  migrate_to_contract.py  加表名前缀 + value_origin 归一 + 上屏文案清枚举码 + vacuum
        ↓
  v0.1.0/keyword_demo.sqlite                   107.5 MB / 24 表 / 423,555 行   ← ★权威，工作台唯一打开的库
        │
        └→  /Users/linsen/BAM/09-工作台/core/paths.py:58-60  KEYWORD_DB
```

第 ④ 步不是「改个名」，它改了三样东西：

| 改什么 | 从 | 到 | 为什么 |
| --- | --- | --- | --- |
| 7 张表的表名 | `dim_scope` `dim_brand` `dim_state_label` `dim_market_keyword` `dim_child_product_goal` `fact_child_inventory_absorb` `fact_child_traffic_attribution_daily` | `dim_keyword_scope` `dim_keyword_brand` `dim_keyword_state_label` `dim_keyword_term` `dim_keyword_child_goal` `fact_keyword_child_absorb` `fact_keyword_traffic_attribution_daily` | 接入契约 6.2 要求 `dim_keyword*` / `fact_keyword_*` / `bridge_keyword_*` 前缀。注意 `dim_market_keyword` 不匹配 —— `market` 挡在 `keyword` 前面，所以改叫 `dim_keyword_term` |
| `value_origin` 取值 | `customer_real` / `customer_real_anchor` / `derived` / `synthetic_demo` / `missing`（四值实测） | `direct` / `derived` / `constructed`（三值实测） | 契约 6.4 |
| 上屏自由文本里的英文枚举码 | `replenishment_gap` / `stockout` / `overstock` / `aged_inventory_risk` / `healthy` | 补货缺口 / 断货 / 超量备货 / 库龄风险 / 库存健康 | 构建期把 v0.3.0 的 `decision_summary` 原文拼进了 `main_basis`，直接显示就是枚举码泄漏，G9 会红。清的是 `fact_keyword_evidence.{conclusion,main_basis}`、两张事件表的 `label`、日报五个 `q*` 列 |

### 🚩 挑库的坑：两个 107 MB 库逐表行数完全相同

`v0.1.0/` 下两个 sqlite **24 表、423,555 行、同名表逐表行数全等**，
连行数多重集都一模一样，区别只有上表那 7 个表名（外加 `value_origin` 与文案）。
**按「哪个文件名像正式版本号」去挑必挑错**：
带 `bamboocool_keyword_v0.1.0` 这个正式版本号的是**改名前的源库**，
文件名平平无奇的 `keyword_demo.sqlite` 才是权威。

判据只有一个 —— **代码实际打开的路径**：

- `/Users/linsen/BAM/09-工作台/core/paths.py:58-60` → `keyword_demo.sqlite`（`KEYWORD_DB`）
- `/Users/linsen/BAM/09-工作台/modules/keyword/module.py:334`、`data.py:44` 都只走 `paths.KEYWORD_DB`
- `/Users/linsen/BAM/06-Pi-Agent交互Demo/src/keyword-agent.ts:13` 同样指 `keyword_demo.sqlite`
- **全仓没有任何运行时代码打开 `bamboocool_keyword_v0.1.0.sqlite`**，
  只有 `migrate_to_contract.py:21` 把它当输入

所以源库的状态是「**构建链上游，不是废弃件，不要删**」：
重跑第 ④ 步还要它。但它**不能上工作台**（表名不合契约、枚举码会泄漏上屏）。

---

## 三、13 个脚本逐个说

### 构建链上的（4 个，按跑的顺序）

| # | 脚本 | 输入 | 输出 | 能重跑？ |
| --- | --- | --- | --- | --- |
| ① | `lib_kwsrc.py` 29.6 KB | 客户 3 文件 + v0.3.0 | 不落盘。标准化 Python 结构 + 选样结果（`select_keywords()` 按 10 个配额桶确定性挑 300 词；`select_children()` 挑 30 子体 = 5 黄金场景 + 覆盖最富交集子体 + 零覆盖子体，覆盖全部 5 个父体） | 是（纯函数，只读源文件，从不写）。也可直接 `/usr/bin/python3 lib_kwsrc.py` 打印选样自检 |
| ② | `build_keyword_dataset_v010.py` 31.3 KB | ①的结果 | `v0.1.0/bamboocool_keyword_v0.1.0.sqlite` + 24 张表 JSON + `dataset-manifest.json` | 是，幂等（`drop table if exists` 后重建，seed 固定）。**会覆盖 v0.1.0/ 下的源库与 25 个 JSON** |
| ③ | `verify_v010.py` 7.2 KB | 落盘的库 | 13 条复核结果打屏 | 是，只读 |
| ④ | `migrate_to_contract.py` 6.3 KB | `bamboocool_keyword_v0.1.0.sqlite` | `keyword_demo.sqlite` | 是（`shutil.copy2` 后就地改，源库不动）。**会覆盖 `keyword_demo.sqlite`** |

②的九层被拆进 5 个 lib，全部由 ② 的 `main()` 顺序调用：

| 脚本 | 层 | 关键构建函数 | 内置门禁 |
| --- | --- | --- | --- |
| `lib_l3.py` 22.4 KB | L3 | `build_snapshots()` | `gate_g1()` 末期逐字段等于客户原值（53,756 个值）、`gate_shapes()` G3 指名到词的 9 条形态断言 |
| `lib_l4.py` 23.8 KB | L4 | `build_pairs()` → `build_positions()` | `gate_l4()` G4 共 12 条 |
| `lib_l56.py` 16.1 KB | L5 / L6 | `build_traffic()` / `build_product_context()` | `gate_l5()` 5 条、`gate_l6()` 6 条 |
| `lib_l7.py` 11.1 KB | L7 | `build_market_events()` / `build_coverage_events()` | 无（并入 `lib_l89.gate_l789()`） |
| `lib_l89.py` 20.3 KB | L8 / L9 | `build_evidence()` / `build_audit_records()` / `build_daily_reports()` | `gate_l789()` G7-G9 共 12 条，含 `_scan_forbidden()` 文案零枚举码扫描 |

G2（分类汇总与客户「总览」sheet 11 行三项全等）在 ② 的 `build_l2()` 里，
用客户原始 2,000 行现算 —— **必须用原始行，客户就是这样算的**，用去重后的 1,991 行对不上。

### 不在链上的（5 个探针 / 导出 / 审计，都只读）

| 脚本 | 干什么 | 什么时候跑 |
| --- | --- | --- |
| `export_agent_package.py` 13.2 KB | 机械导出 `../01-方案与数据需求/06-数据字典.md`（24 表逐张：行数、列数、每列类型与枚举全集）与 `07-接口JSON样例.json`（六个路由真实响应，长数组截前 2 项并标原长度） | 库或接口变了就重跑。**需要工作台在 18820 跑着** |
| `audit_agent_contract.py` 9.2 KB | 按《08-Agent需求与数据契约要则》v1.1 做三项机械检查：A 产出侧字段在库里有没有同名列（答案泄漏）、B 库里哪些列命中禁读清单、C 交底文档里有没有出现完整的中文结论句（钉答案） | 改 Agent 交底文档后 |
| `probe_agent_surface.py` 4.1 KB | 盘点判断层四张表的真实字段 + 取值分布 + 页面实读字段，用来写 Agent 端契约 | 写/改 Agent 契约前 |
| `sweep_masked_sample.py` 2.8 KB | 把 JSON 样例里所有 ≥8 字的中文串按字段名聚合列出，人工过一遍决定该不该进 `MASK_FIELDS`。比正则猜结论句可靠 —— 正则抓得到「」句式，抓不到「需先补货再扩量」这种短结论 | 改抹值清单前 |
| `verify_v010.py` | 见上表 ③ | 每次重建后 |

另有 `../00-源表勘查/probe_kw_asin_overlap.py`（6.1 KB，只读）：
勘查头部 ASIN 与自有 342 子 ASIN 的交集，以及未勘查文件的字段级结构。

---

## 四、每一版数据包

只有一个版本目录 `v0.1.0/`，28 个文件，磁盘占用 **392 MiB（411 MB）**。

| 文件 | 大小 | 表 / 行 | 状态 | 判据 |
| --- | --- | --- | --- | --- |
| `keyword_demo.sqlite` | 107,511,808 B（107.5 MB） | 24 / 423,555 | **权威** | `09-工作台/core/paths.py:58-60` 的 `KEYWORD_DB` 就是它 |
| `bamboocool_keyword_v0.1.0.sqlite` | 108,904,448 B（108.9 MB） | 24 / 423,555 | **仍被引用的构建链上游**，非废弃、非过期 | `build_keyword_dataset_v010.py:22` 写它，`migrate_to_contract.py:21` 读它；零运行时代码打开它 |
| `dataset-manifest.json` | 23 KB | — | 有效 | 门禁逐条断言原文 + 通过与否 + 实测值都在 `gates` 里；另有 `selection_quotas` / `selection_cuts` / `library_status_cuts` 供复核 |
| 24 张表 `*.json` | 合计 ~195 MB | — | **有效但表名是旧的** | 与源库同一步导出，所以 7 个文件名（`dim_brand.json` / `dim_market_keyword.json` / `dim_scope.json` / `dim_state_label.json` / `dim_child_product_goal.json` / `fact_child_inventory_absorb.json` / `fact_child_traffic_attribution_daily.json`）在 `keyword_demo.sqlite` 里查不到同名表 |
| `README.md` | 5.7 KB | — | 有效 | 口径与表清单的原始版本，24 表逐行说明 + 三条来源口径 + 46 条门禁分组 |

**门禁：构建期 46 条（写进 manifest 的 `gates` 七组）+ 落盘复核 13 条，全绿。**
manifest 里 `stage` 字段写的是 `"L1+L2+L3+L4"` —— **这个字段过期了**，
实际九层全建完了（L5~L9 的表和行都在库里）。别按这个字段判进度。

---

## 五、表的分类：哪些是观察事实、哪些是构造、哪些是判断产物

这是这个包最要紧的一张表。**24 张表里没有一张是 v1 时代遗留的死表**，
但**有 3 张是判断产物**（现在由确定性规则生成，是给离线 Agent 预留的占位）。

先看每行自带的 `value_origin`（`keyword_demo.sqlite` 里的三值）：

| 取值 | 含义 | 迁移前叫什么 |
| --- | --- | --- |
| `direct` | 客户原文件原值，一字节未改 | `customer_real` |
| `derived` | 由本包其他表或客户字段推导（末期锚点位段、事件、证据、日报、词组） | `customer_real_anchor` / `derived` |
| `constructed` | 构造值 | `synthetic_demo` / `missing` |

### A. 客户原始派生的观察事实（有真实成分）

| 表 | 真的是哪一部分 |
| --- | --- |
| `dim_keyword_term` `dim_keyword_alias` `dim_keyword_brand` | 词、写法、品牌全部来自关键词3 原文（2,000 行归并 9 组重复写法 → 1,991 词） |
| `bridge_keyword_attribute` `dim_keyword_attribute_seed` `fact_keyword_attribute_combo` | 标签与运营角色种子来自关键词1 的人工标注矩阵（S必投 / A重要 / B补充 + ★） |
| `fact_keyword_category_rollup` | **全真**：与客户「总览」sheet 逐字段对账的 G2 回归基线，11 行三项全等 |
| `fact_keyword_market_snapshot` | **只有末期是真的**。每个词 × 每个来源 × 每个频率的最后一格 = 客户原值（G1 逐字段校验 53,756 个值），往前 25 周 / 11 月是构造 |
| `fact_keyword_head_asin` | 末期前十来自客户原文件；跨期替换是构造 |
| `fact_keyword_child_absorb` | **投影 v0.3.0，不重算**：库存承接态由 v0.3.0 字段唯一决定（G6 有断言） |

### B. 构造的（客户从来没提供过）

| 表 | 构造了什么 | 有真实约束吗 |
| --- | --- | --- |
| `dim_keyword_child_pair` `fact_keyword_child_position_daily` | **位置层客户从未提供**。真实信息只有「某个自有 ASIN 在这个词的前三或前十」这一档（186 对锚点）；精确位次、逐日 182 天轨迹、广告位全部构造 | 有：末期必须落回锚点位段（前三 rank≤3、前十 4≤rank≤10），G4 有断言 |
| `fact_keyword_child_traffic_daily` `fact_keyword_traffic_attribution_daily` | 词级自然 Sessions、广告表现、展示量份额 | 有硬顶：词级流量与花费之和必须**严格小于** v0.3.0 当日子体真实值，且必须留出未归因残差（归因比例不得 100%），G5 有断言 |
| `dim_keyword_child_goal` | 产品目标 + 主推关系（v0.3.0 没有，本模块新增） | 六种目标枚举是本模块自定的，**待客户确认**（口径 D2） |
| `dim_keyword_scope` `dim_keyword_state_label` | 范围元数据 / 枚举码→中文标签映射（映射在读取边界完成，码值不进事实表） | — |
| `dim_keyword_group` `bridge_keyword_group` | 需求词组。`bridge_keyword_group.dedup_weight` 一词多组按 1/n 分权，防搜索量重复计入 | — |

第二来源（关键词2）**只有当期一格，不伪造它的历史**。
它存在的意义是保留与关键词3 的真实冲突：840 个词的广告竞品数两来源不一致。

### C. 判断产物（现在是规则占位，将来由离线 Agent 同构替换）

| 表 | 行数 | 现在谁产出 | 上屏内容 |
| --- | --- | --- | --- |
| `fact_keyword_market_change_event` | 148 | `lib_l7.build_market_events()` | `label` 中文成品句，带 from/to snapshot_id 可下钻 |
| `fact_keyword_coverage_event` | 973 | `lib_l7.build_coverage_events()` | 同上，8 类覆盖与位置事件 |
| `fact_keyword_evidence` | 562 | `lib_l89.build_evidence()` | 七类证据，`conclusion` / `main_basis` 是中文成品文案 |
| `fact_keyword_audit_record` | 90 | `lib_l89.build_audit_records()` | 30 子体 × 3 期盘点 |
| `fact_keyword_daily_report` | 14 | `lib_l89.build_daily_reports()` | 五问五答，14 天各不相同且引用可解析 |

⚠️ **这 5 张表（尤其证据与日报）是给 Agent 的坑**：
`../01-方案与数据需求/05-Agent输出面交底.md` 顶部明写 v1 已作废，
原因就是它把这里的 562 条构造证据、14 行构造日报的成品句当「现在的样子」示范给 Agent
—— 等于钉答案，Agent 只会复述。跑 `audit_agent_contract.py` 能把这类问题扫出来。
真的 Agent 跑起来时，这 5 张表的内容必须由 Agent 自己产出，写进
`09-工作台/modules/keyword/derived/keyword_agent_current.sqlite`（详见模块根 `../README.md`）。

⚠️ **日报 Q3 现在有一句自相矛盾**：「当日新增覆盖 0 条、丢失覆盖 0 条，其中涉及核心词 114 条」。
前两个数按 `to_date == 当日` 过滤，而汇总型事件的 `to_date` 也是当日。
要回 `lib_l89.py` 改口径并重建那 14 行日报。

---

## 六、重跑要什么

### 前置

| 项 | 要求 |
| --- | --- |
| 解释器 | **必须 `/usr/bin/python3`**（3.9.6）。它是本机唯一带 lxml 的解释器，无 openpyxl。3.9 的 f-string 里不能含反斜杠 |
| cwd | 就在 `/Users/linsen/BAM/07-关键词分析模块/02-数据构建/`（5 个 lib 靠同目录 import）。**绝不要在 `/Users/linsen/BAM/09-工作台/modules/` 下跑 python** —— 那里的 `keyword/` 包会遮蔽标准库 `keyword`，报错跟你的代码毫无关系 |
| 客户源 | `/Users/linsen/BAM/数据源/AI广告对接数据-总20260803/10.关键词/` 三个文件必须在（注意是带 `-总20260803` 的那个目录，同级还有一个残缺的同名前缀目录） |
| 产品包 | `/Users/linsen/BAM/02-产品销售库存模块/02-数据构建/v0.3.0/bamboocool_product_sales_inventory_v0.3.0.sqlite` |
| xlsx 读取器 | `/Users/linsen/BAM/04-广告分析模块/00-源表勘查/xlsxlite.py`（`lib_kwsrc.py:19-22` 把它塞进 `sys.path`） |
| 磁盘 | ~411 MB（两个 107 MB 库 + 195 MB JSON） |

### 顺序

```bash
cd /Users/linsen/BAM/07-关键词分析模块/02-数据构建

/usr/bin/python3 build_keyword_dataset_v010.py   # ② 重建源库 + 25 个 JSON（会覆盖）
/usr/bin/python3 verify_v010.py                  # ③ 落盘独立复核 13 条
/usr/bin/python3 migrate_to_contract.py          # ④ 产出 keyword_demo.sqlite（会覆盖）
```

② 打屏 46 条门禁逐条结果，③ 打屏 13 条，④ 末行打「契约 6.2 / 6.4 / G7 / G9 文案：全部通过」。
④ 的退出码非 0 就是有不合规项，别把库拿去用。
`migrate_to_contract.py` 最后跑 `vacuum`，这是两个库大小差 1.4 MB 的原因。

⚠️ **本次没有实测重跑耗时**（②④ 会覆盖 v0.1.0 下的既有文件，本次只读）。
② 要读 2 MB xlsx/html 并生成 42 万行，量级上是分钟级；确切耗时**判不出，需实测**。

⚠️ **重跑后必须重跑下游**：`keyword_demo.sqlite` 变了，
`../01-方案与数据需求/06-数据字典.md` 与 `07-接口JSON样例.json` 就过期了，
要跑 `export_agent_package.py`（**需先启动工作台 18820**）。

### 确定性

seed 固定 `20260803`，所有随机都走 `_rng(keyword, salt)` 这类**按对象名做哈希**的局部 RNG，
不是全局 `random`。所以同样的输入必然产出同样的库，可以拿两次构建的行数与 manifest 逐字段对比。
选样切点（`selection_cuts` / `library_status_cuts`）也写进 manifest 供门禁复核。

---

## 七、这一层的已知问题

1. **两个 107 MB 库逐表行数全等，按文件名挑必挑错** —— 见 §二。判据只能是 `paths.py` 打开的路径。
2. **`lib_l7.py` 的 docstring 过期**，自称含 L8/L9 但那两层在 `lib_l89.py`。
3. **`dataset-manifest.json` 的 `stage` 字段是 `"L1+L2+L3+L4"`**，与实际（九层全建完）不符。
4. **24 张表 JSON 的文件名是改名前的旧表名**，7 个与 `keyword_demo.sqlite` 的表名对不上。
5. **日报 Q3 一句文案自相矛盾** —— 见 §五 C。
6. **5 张判断产物表现在是规则占位**，内容必须在 Agent 跑通后由 Agent 自己产出；
   现在这些成品句**不能当示范喂给 Agent**（v1 交底就是这么废掉的）。
7. **内联 `python3 -c "..."` 与 heredoc 会被安全策略正则误拦**（撞过两次）：
   探针类脚本一律落成 `.py` 文件再跑。
8. **v0.3.0 的 `base_stockout_date` 对健康/超储/库龄子体存的是字面字符串 `"none"` 而非 NULL**，
   日期解析会静默失败。L6 投影时要处理。
9. **产品目标六种枚举与主推关系是本模块自定的**，正式口径**需王楠确认**（口径 D2）。
10. **「关键词流量获取」缺正式测量定义**，L9 日报用代理指标「监控词带来的自然 Sessions」，
    界面须在 ⓘ 里写明（口径 D1）。
