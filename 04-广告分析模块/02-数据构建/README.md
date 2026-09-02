# 04-广告分析模块 / 02-数据构建

广告模块四份数据产物是怎么来的、哪一份是权威、哪个脚本能重跑。
模块全景见 `/Users/linsen/BAM/04-广告分析模块/README.md`。

基准日 **2026-08-03**（来自 `/Users/linsen/BAM/09-工作台/core/paths.py:45`，
**不是**数据包声明的 —— 见模块 README「三个先看的地方」第 2 条）。
Amazon 事实窗 2026-07-01 ~ 2026-07-31，SP 按 7 天归因、SB/SD 按 14 天归因，不跨归因混加。

---

## 1. 构建链

**不是一条线。** 三份包各自从客户原始报表建，只有 `v0.2.0 → page2-ext` 是真链式；
而 `v0.2.0` 另外还要读 `v0.1.0` 复用 id。

```
客户原始报表（只读输入，31 个 xlsx/csv）
/Users/linsen/BAM/数据源/AI广告对接数据-总20260803/13.广告/
  │
  ├─ build_advertising_demo.py --mode slice     读其中 8 份 ──→ v0.1.0-slice     【废弃】
  │
  ├─ build_advertising_demo.py --mode release   读其中 8 份 ──→ v0.1.0           【仍被引用】
  │                                                              │
  │                                        （复用 733 个 ad_object_id）
  │                                                              ↓
  └─ build_v0_2_0.py  ＋ lib/{adsrc,build_facts,build_sides}.py
       读全部 31 份 ＋ 读 v0.1.0 ────────────────────────────→ v0.2.0           【权威·主库】
                                                                 │
                        产品包 v0.3.0 ─────────┐                  │
                        （342 脊椎、库存判定）  ↓                  ↓
                          build_page2_ext.py（读两个库，不读客户原始数据）
                                                        ──────→ page2-ext      【权威·第二库】
                                                                 │
                                      migrate_goal_to_operator_set.py（原地一次性迁移，已生效）
```

**`page2-ext` 不是从客户原始数据直接建的** —— 它的输入只有 v0.2.0 与产品包 v0.3.0
（`build_page2_ext.py:22-26`），所以它是派生件：重建它不需要碰客户报表，
但 v0.2.0 或产品包换版之后它必须跟着重建，否则五个演示对象的证据会指向旧事实。

`v0.2.0 → v0.1.0` 那条依赖是真的、有门禁守着：`build_v0_2_0.py:37` 把 v0.1.0 当输入读，
质量报告里 `Q-V010-ID-REUSE` 实测 `carried_ids=733 / v010_total=733`。
这是 `B088WF1PRW` 那条 v0.1.0 时代的页面二决策链在 v0.2.0 里还能解析的原因。

---

## 2. 每个脚本一行

| 脚本 | 行数 | 输入 | 输出 | 能不能重跑 |
| --- | ---: | --- | --- | --- |
| `build_advertising_demo.py` | 1,989 | 客户报表 31 份中的 8 份（xlsx 走 openpyxl） | `--mode slice` → `v0.1.0-slice/`；`--mode release` → `v0.1.0/`（各含 sqlite + `frontend/` 两个页面 JSON + `acceptance_export.json` + `schema.sql/json` + `lineage.json` + `quality_report.json` + `manifest.json`） | ⛔ **现在跑不了，而且跑之前会先删掉目标目录** —— 见第 5 节 |
| `build_v0_2_0.py` | 961 | 全部 31 份客户报表 ＋ `v0.1.0/advertising_demo.sqlite` | `v0.2.0/advertising_demo.sqlite` + `table_counts.json` + `quality_report.json` | ✅ 可重跑。`:552` 先删旧库再按 SCHEMA 重建，幂等（`seed=20260830` 固定） |
| `lib/adsrc.py` | 415 | —（被 `build_v0_2_0.py` import） | 源文件读取与取值解析：逐文件编码探测（部分 csv 是 GBK、部分 UTF-8-BOM）、Amazon 金额/百分比/日期格式、运营的广告活动命名约定解析 | — 客户源目录写死在 `:24` |
| `lib/build_facts.py` | 440 | 同上 | 事实层：`fact_ad_performance` / `fact_ad_daily` / 搜索词份额等。跨报表族的指标列名不同（7 天 vs 14 天归因、"花费" vs "广告主总成本"），全部走 `METRIC_COLS` 别名表 | — |
| `lib/build_sides.py` | 454 | 同上 | 侧翼事实（同比、预算、无效流量、品类基准、受众、素材、广告位）、归因桥、标签体系、异常规则、质量报告 | — |
| `build_page2_ext.py` | 831 | `v0.2.0/advertising_demo.sqlite` ＋ 产品包 `v0.3.0`（绝对路径写在 `:23`） | `page2-ext/page2_decision_ext.sqlite`（14 表） | ✅ 可重跑。`:235` 先删旧库、`:240` 重建 DDL |
| `migrate_goal_to_operator_set.py` | 95 | `page2-ext` 库（**原地改写**） | 把产品目标从「我们推断出来的」改成「运营填的输入」：`goal_status` → `confirmed`、`rationale` → 运营口径意图（不带推断数字）、`source_ref` → `operator_set`；证据侧 `evidence_nature` `inference` → `confirmed` | ✅ 已生效且已回灌构建器。**不需要再跑**（见下） |
| `diag_gates.py` | 67 | `v0.2.0` + `v0.1.0`（只读） | 诊断脚本，不产数据：查外键违规与桥表角色缺失。构建期用过，现在两项都已 PASS | ✅ 只读 |
| `selfcheck_adsrc.py` | 89 | 6 个 csv（只读） | 诊断脚本，不产数据：正式构建前自检取值解析器与 csv 编码探测 | ✅ 只读 |

**`migrate_goal_to_operator_set.py` 的状态要说清**，它容易被当成还没做的事：

- 已经跑过了 —— 实测 `ext_product_goal` 5 行全是 `goal_status=confirmed` /
  `source_ref=operator_set`，rationale 是「保住现有规模，先把库存承接补齐」这类运营口径。
- 而且**已经回灌进构建器** —— `build_page2_ext.py:327-332` 直接写 `'confirmed'` /
  `'operator_set'`。所以重跑 `build_page2_ext.py` **不会**把这次迁移覆盖回去
  （脚本尾部那条「下一步：构建器要同步改」的提示已经过期）。

---

## 3. 每一版数据包

| 版本 | 路径 | 表 | 行 | 大小 | 基准日 / 事实窗 | 判定 |
| --- | --- | ---: | ---: | ---: | --- | --- |
| **v0.2.0** | `/Users/linsen/BAM/04-广告分析模块/02-数据构建/v0.2.0/advertising_demo.sqlite` | 34 | 61,055 | 20 MB | 库内 `dataset_manifest`：`built_at 2026-08-30T02:15:58`、事实窗 `2026-07-01~07-31`、`source_file_count 31`、`seed 20260830`、`dataset_stage release_candidate`。**无 as_of 列** | **权威·主库**：`core/paths.py:54` 的 `ADS_DB` 指它 |
| **page2-ext** | `/Users/linsen/BAM/04-广告分析模块/02-数据构建/page2-ext/page2_decision_ext.sqlite` | 14 | 264 | 172 KB | `ext_meta`：`as_of=2026-08-03`、`built_at=2026-08-03`、`ads_source=v0.2.0`、`product_source=v0.3.0`、`demo_objects` 5 个 | **权威·第二库**：`modules/ads/data.py:30-32` 写路径、`:60` `ATTACH` 成 `ext`。**四份产物里唯一自带 as_of 的** |
| v0.1.0 | `…/v0.1.0/advertising_demo.sqlite` | 22 | 8,192 | 3.6 MB | `manifest.json`：`dataset_stage release`、事实窗 `2026-07-01~07-31`。无 as_of 字段 | **仍被引用，不是废弃**：`build_v0_2_0.py:37` 读它复用 id；`03-验收` 唯一验过的版本；`00-源表勘查/probe_adgroup_count.py:8` 与 `diag_gates.py` 也读它。没有任何工作台代码打开它 |
| v0.1.0-slice | `…/v0.1.0-slice/advertising_demo.sqlite` | 21 | 953 | 592 KB | 同上，无 as_of | **废弃**：验收前的最小纵向切片，被同脚本 `--mode release` 取代。全库 grep 只命中 `build_advertising_demo.py:25` 的版本号字面量，无人读 |

规模变化说明 v0.1.0 → v0.2.0 做了什么：v0.1.0 只吃了 31 份报表里的 8 份；
v0.2.0 吃全 31 份，补上 Campaign / 广告位 / 受众三层、真正的逐日事实表、同比、
预算损失、无效流量、品类基准与搜索词份额。`dim_ad_object` 733 → 989、
`fact_ad_performance` 739 → 984、`fact_search_term_share` 新增 34,109 行
（20 MB 里最大的一块）。

### 质量证据

- `v0.2.0/quality_report.json`：**构建器自检** 13 项全 PASS。关键几条：
  `Q-ALL-SOURCES 31/31`、`Q-FK violations=0`、`Q-OBJECT-LEVELS AD_GROUP 54 / CAMPAIGN 80 / TARGET 855`、
  `Q-MONTH-BASIS-SINGLE 984`、`Q-DAILY-TWO-BASES`（月度 3,858 / 逐日精确 3,980 分开计）、
  `Q-DAILY-SCALE-CLOSES 0 个对象偏差 >0.05`、`Q-FIVE-ROLES`、`Q-LABEL-FIVE-TYPES`、
  `Q-INFERRED-NOT-CONFIRMED 0`、`Q-RULES-PENDING 0`。
- **v0.2.0 没有独立验收。** `/Users/linsen/BAM/04-广告分析模块/03-验收/latest_release_result.json`
  与 `latest_result.json` 的 `dataset` 字段都指向 `…/v0.1.0`，`mode=release`，
  `evaluated_at 2026-08-29`，PASS。v0.2.0 也没有 `manifest.json` / `schema.sql` / `lineage.json`
  （v0.1.0 与 slice 都有这三样）。
- `page2-ext` 既无独立验收也无质量报告，只有 `ext_meta` 五行元信息。

---

## 4. 表的分类

判据两条：一是表里 `source_status` / `value_origin` 的实测分布，
二是**有没有工作台代码打开它**（全文 grep `modules/ads/*.py`）。

### 4.1 v0.2.0 的 34 张表

**A. 客户原始派生的观察事实（`source_status=direct` 为主）—— 24 张里的主体**

| 表 | 行 | 来源分布 |
| --- | ---: | --- |
| `fact_search_term_share` | 34,109 | direct 全量 |
| `fact_ad_label_version` | 9,279 | derived 6,076 / direct 3,203（运营命名约定推出来的标签一律 `label_source=auto_mapping` + `confirmation_status=pending`，不冒充运营已确认） |
| `fact_ad_daily` | 7,838 | direct 3,980（`search_term_exact_day_sum`）/ derived 3,858（`daily_scaled_to_month`）—— **两套数系并存，永不相加** |
| `bridge_ad_object_product` | 5,872 | direct 全量（五种归因角色） |
| `dim_ad_object` | 989 | direct |
| `fact_ad_performance` | 984 | direct，单一 `metric_basis=report_month_total` |
| `fact_product_ad_spend` | 526 | direct 525 / blocked 1（唯一无子体明细的 `B0CCTCLTYS` 明确标 blocked，没有伪造映射） |
| `dim_product_child` | 521 | direct —— ⚠️ 见 4.3 |
| `dim_placement` / `fact_placement` | 157 / 157 | direct |
| `dim_campaign` 80、`fact_invalid_traffic` 74、`fact_ad_yoy` 63、`fact_budget` 36、`fact_creative` 31、`dim_audience` 7、`fact_audience` 7、`fact_category_benchmark` 6、`dim_product_parent` 5 | | direct |
| `source_file` 31、`source_lineage` 160、`dataset_manifest` 1 | | 血缘与元信息 |

**B. 构造的（`scenario_added`）**

| 表 | 行 | 说明 |
| --- | ---: | --- |
| `dim_anomaly_rule` | 10 | 异常阈值规则，全部 `pending_customer_confirmation` |
| `scenario_registry` | 13 | 演示场景登记 |
| `fact_ad_decision_event` | 4 | 运营历史动作 |
| `fact_review_feedback` | 2 | D+3 / D+7 回流 |

**C. 判断产物（`derived`，v0.1.0 时代的页面二链 + 页面一算子结果）**

| 表 | 行 | 还有没有人读 |
| --- | ---: | --- |
| `fact_decision_context` | 2 | ✅ 读（`data.py` 的 `is_ext=False` 分支，`B088WF1PRW` 那条老链） |
| `fact_decision_evidence` | 9 | ✅ 读，同上 |
| `fact_required_ad_task` 4 / `bridge_task_ad_object` 4 / `fact_ad_diagnosis` 4 / `fact_ad_recommendation` 4 | | ✅ 读，同上 |
| `fact_page1_result` | 59 | ❌ **没人读** —— 页面一现在由 `page1.py` 现算，不读预落的结果 |
| `fact_page1_anomaly` | 7 | ❌ **没人读**，同上 |

**D. 没有任何工作台代码打开的 10 张**

`dataset_manifest`、`dim_audience`、`fact_audience`、`dim_placement`、`fact_creative`、
`fact_page1_result`、`fact_page1_anomaly`、`fact_search_term_share`、`scenario_registry`、
`source_lineage`。

其中 `fact_search_term_share`（34,109 行）是这个 20 MB 库里最大的一块，
但页面一的搜索词面板并不读它 —— **判不出**这是留给后续页面的、还是构建时顺手落的，
**需王楠确认**。其余几张（受众、广告位维度、素材）性质相同：数据在，页面没用上。

### 4.2 page2-ext 的 14 张表

分两半，这一半的区分很要紧 —— **上半是 Agent 的合法输入，下半是 Agent 已经能自己产出的结论。**

**证据层与元信息（Agent 的输入侧）**

| 表 | 行 | value_origin |
| --- | ---: | --- |
| `ext_decision_context` | 5 | constructed 5（决策版本头：观察窗、data_as_of、场景） |
| `ext_decision_evidence` | 50 | direct 35 / constructed 10 / derived 5 —— 10 类证据 × 5 个对象，`evidence_nature` 除 `PRODUCT_GOAL=confirmed` 外都是 `fact` |
| `ext_product_goal` | 5 | constructed 5，但 `goal_status=confirmed` / `source_ref=operator_set` —— **运营填的输入，不是 Agent 判的**（原输出点 B0 已作废） |
| `ext_keyword_match` / `ext_keyword_position` | 14 / 14 | constructed |
| `ext_competitor_pressure` | 15 | derived 10 / constructed 5 |
| `ext_meta` | 5 | 元信息（as_of / 两个源包版本 / 五个演示对象） |

**构造的结论链（产出侧，与真 Agent 的输出点重叠）**

| 表 | 行 | value_origin | 对应的 Agent 输出点 |
| --- | ---: | --- | --- |
| `ext_goal_constraint` | 19 | derived 9 / direct 5 / constructed 5 | B0b |
| `ext_structure_issue` | 13 | derived 8 / direct 5 | B0e |
| `ext_required_ad_task` | 16 | constructed 16 | B1 |
| `ext_task_ad_object` | 16 | derived 14 / constructed 2 | B2 |
| `ext_diagnosis` | 21 | constructed 21 | B3 |
| `ext_diagnosis_coverage` | 50 | （无来源列） | B3b |
| `ext_recommendation` | 21 | constructed 21 | B4 |

这七张现在**还在被读**，但读它们的只剩两条路由：`/api/ads/decide`（板块9 拍板）和
`/api/ads/gate`（依据引用门禁），两条都走 `compute.py:329` 的 `agent_stages`。
页面上四段揭示（板块 4/6/7/8）读的已经是真 Agent 的
`fact_ads_agent_output`，不是这七张。由此产生的断裂见模块 README「已知问题」第 1、2 条。

`06-广告Agent契约审计.md` §4.2 对这一半提了四条未完项（`INVENTORY` 证据拆两半、
`PRODUCT_STAGE.lifecycle` 摘掉、`KEYWORD.losing` / `COMPETITOR.types` 二选一、
11 个 `nature=fact` 的错标注改对），标注为「要你拍口径再动」，至今未动。

### 4.3 那张 521 行的 `dim_product_child`

`v0.2.0` 自建了 `dim_product_child`（521 行 / 7 列）与 `dim_product_parent`（5 行）。
实测与产品包 v0.3.0 的 342 脊椎交集 **188**。

**没有任何工作台代码打开这两张表** —— 全模块只在 `modules/ads/data.py:149` 读
`prod.dim_product_child`（ATTACH 进来的产品包），`data.py:1-14` 的文件头也写明
「广告包自建的 521 子体维度不当身份来源用」。

但表还在包里，`01-方案与数据需求/01-广告Demo数据构建范围.md` 也还写着「完整 521 个子 ASIN」，
而接入契约 §2 点名这是「目前唯一需要返工的地方」。
**口径冲突未裁决，本文档不裁决**，详见模块 README「三个先看的地方」第 3 条。

### 4.4 Agent 的产出不在这个目录

真 Agent 的落表在工作台侧的 sidecar，源数据包保持只读：

```
/Users/linsen/BAM/09-工作台/modules/ads/derived/ads_agent_state.sqlite
  fact_ads_agent_run      22 行   一次运行一行（17 completed + 2 failed + 3 v1 遗留）
  fact_ads_agent_output  707 行   按 output_point 分组的逐条产出（现行）
  fact_ads_agent_stage    12 行   v1 遗留，已不读
  fact_ads_agent_item     40 行   v1 遗留，已不读
```

---

## 5. 重跑要什么

**解释器：`/usr/bin/python3`（3.9.6）。** 这是本机唯一装了数据链依赖的解释器 ——
实测 `openpyxl 3.1.5`（`build_advertising_demo.py` 读 xlsx 用）与 `lxml`
（`lib/adsrc.py` 解析 xlsx 用）都在它下面。3.9 的 f-string 里不能含反斜杠。

**别 `cd` 进 `/Users/linsen/BAM/09-工作台/modules/` 跑任何 python** ——
那里的 `keyword/` 包会遮蔽标准库的 `keyword`，报错跟你的代码毫无关系。
本目录的脚本不受影响（都从 `02-数据构建/` 下跑）。

### ✅ v0.2.0 —— 可以重跑

```bash
cd /Users/linsen/BAM/04-广告分析模块/02-数据构建
/usr/bin/python3 build_v0_2_0.py
```

要什么：① 客户报表 31 份在 `/Users/linsen/BAM/数据源/AI广告对接数据-总20260803/13.广告/`
（绝对路径写死在 `lib/adsrc.py:24`，重构后仍正确）；② `v0.1.0/advertising_demo.sqlite`
必须在原位（`:37` 要读它复用 733 个 id，删了它 `Q-V010-ID-REUSE` 会挂、
`B088WF1PRW` 老链在 v0.2.0 里会断）。`:552` 先删旧库再重建，`seed=20260830` 固定，幂等。
耗时未实测（要读 31 份报表、落 61,055 行，量级在分钟级）。

**重跑后必须跟着重建 `page2-ext`** —— 它的证据引用挂在 v0.2.0 的行上。

### ✅ page2-ext —— 可以重跑

```bash
cd /Users/linsen/BAM/04-广告分析模块/02-数据构建
/usr/bin/python3 build_page2_ext.py
```

要什么：v0.2.0 库 + 产品包
`/Users/linsen/BAM/02-产品销售库存模块/02-数据构建/v0.3.0/bamboocool_product_sales_inventory_v0.3.0.sqlite`
（绝对路径写死在 `:23`）。**不需要客户原始报表**。
`:235` 先删旧库、`:240` 重建 DDL，幂等。264 行，秒级。
运营目标那段已含迁移后的口径，**不需要再跑 `migrate_goal_to_operator_set.py`**。

重跑之后 Agent 的历史结果会作废：`context_hash` 由工作台按新数据算出来会变，
`agent_result.py` 会把旧运行判成「Agent 结果与当前页面依据不一致，需要在本地重新运行」。
五个演示对象要各跑一次 Runner
（`/Users/linsen/BAM/06-Pi-Agent交互Demo/scripts/run_ads_agent_demo.ts`）。

### ⛔ v0.1.0 / v0.1.0-slice —— 现在跑不了，而且会先删掉目标目录

`build_advertising_demo.py:628-636` 按 `Path(__file__).resolve().parents[3]` 推项目根。
2026-09-01 重构之后这个下标算错了一层：

```
script  /Users/linsen/BAM/04-广告分析模块/02-数据构建/build_advertising_demo.py
parents[3] → /Users/linsen                （重构前是项目根）
source_root → /Users/linsen/数据源/AI广告对接数据-总20260803   不存在
实际位置    → /Users/linsen/BAM/数据源/AI广告对接数据-总20260803  存在
```

更要紧的是执行顺序：**`:635-636` 的 `shutil.rmtree(output_dir)` 发生在读源文件之前，
而且它删的是整个版本目录。** 所以现在跑 `--mode release` 的结果是：
先把 `v0.1.0/`（含唯一一份独立验收产物 `self_acceptance_result.json`、
`manifest.json`、`lineage.json`、`acceptance_export.json`、`frontend/` 两个页面 JSON）
删干净，然后因为找不到客户报表失败 —— **v0.1.0 那一版就没了，且 v0.2.0 也会跟着不可重建**
（它要读 v0.1.0 复用 id）。

要重建 v0.1.0，必须先把那个路径推法修对（改 `parents[3]` 或改成绝对路径）。
**本文档只登记，没有改这个脚本。** 修之前请先备份 `v0.1.0/`。

### 只读诊断脚本（随时可跑）

```bash
cd /Users/linsen/BAM/04-广告分析模块/02-数据构建
/usr/bin/python3 selfcheck_adsrc.py    # 取值解析器与 csv 编码探测
/usr/bin/python3 diag_gates.py         # 外键违规与桥表角色（读 v0.2.0 + v0.1.0，只读）
```

`/Users/linsen/BAM/04-广告分析模块/00-源表勘查/` 下 19 个脚本同样只读，
但 `probe_adgroup_count.py:8` 读的是 v0.1.0，不是现行主库。
