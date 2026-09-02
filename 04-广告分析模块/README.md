# 04-广告分析模块

站点 / 品线：US / BAMBOO COOL 男士内裤线　　数据基准日（as_of）：**2026-08-03**
工作台服务端口：**18820**（模块 id `ads`，路由前缀 `/api/ads/`，参数前缀 `ads.`）

## 这个模块是什么

两页两个判断对象：

- **页面一 `ads-catalog`「广告分类与数据查看」** —— 判断对象是**广告组 / 投放对象**。
  只回答「数字长什么样」：横向打散、贴标签、按标签筛、比数据、标数值异常。
  这一页有红线：不读产品目标、库存、关键词、竞品结论，**不出诊断与建议**，
  禁动作措辞（建议调整 / 提高竞价 / 降低预算 / 否词 / 暂停）。唯一的 Agent 介入点是
  「AI 建议了这个广告目的标签」（输出点 A1）。
- **页面二 `ads-decision`「单一子 ASIN 广告决策」** —— 判断对象是
  **一个子 ASIN 在当前运营目标与证据下的广告判断**。九个板块串起
  目标 → 证据 → 现有结构 → 应有任务 → 对照 → 诊断 → 方案 → 运营拍板。

规模（实测 `/api/ads/meta`，2026-09-02）：候选子 ASIN 343、有决策版本 6、
有完整证据链 5。广告对象 989（AD_GROUP 54 = SP40/SB5/SD9，CAMPAIGN 80，TARGET 855）。
Amazon 事实窗 2026-07-01 ~ 2026-07-31，SP 按 7 天归因、SB/SD 按 14 天归因，不跨归因混加。

---

## ⚠️ 三个先看的地方

### 1. 它打开的是**两个**库，`paths.py` 里只登记了一个

| 库 | 路径 | 登记在哪 |
| --- | --- | --- |
| 广告包 v0.2.0 | `/Users/linsen/BAM/04-广告分析模块/02-数据构建/v0.2.0/advertising_demo.sqlite` | `/Users/linsen/BAM/09-工作台/core/paths.py:54` 的 `ADS_DB` |
| **页面二决策扩展库** | `/Users/linsen/BAM/04-广告分析模块/02-数据构建/page2-ext/page2_decision_ext.sqlite` | **不在 `paths.py` 里**，路径写在 `/Users/linsen/BAM/09-工作台/modules/ads/data.py:30-32` |

原因写在 `data.py:29` 的注释里：**契约 §11 禁止模块改 `core/`**，模块自己不能往
`paths.py` 加一条，所以扩展库从 `paths.REBUILD_ROOT` 派生并留了
`WORKBENCH_ADS_EXT_DB` 环境变量口子，等外壳侧把它加进 `paths.py` 再切过去。

`data.py:56-62` 的 `connect()` 一次挂三个库，`ext` 与 `prod` 挂不上不致命，只是证据变薄：

```
ads   = ADS_DB                 广告包 v0.2.0（主库，月度事实、标签、推广关系、B088WF1PRW 那条老链）
ext   = page2_decision_ext     ATTACH 成 ext（五个演示对象的证据层与决策链）
prod  = paths.PRODUCT_DB       ATTACH 成 prod（342 脊椎、生命周期、销量窗口、库存判定）
```

**后果**：只看 `paths.py` 会以为这个模块只有一个数据包；只备份 `ADS_DB` 会把页面二
整条决策链丢掉（板块 2/3/4/5/6/7/8/9 的依据全在 `ext` 里）。

### 2. 数据包里没有声明 `as_of`，全靠 `paths.AS_OF` 兼着

`02-数据构建/v0.2.0/` 目录下**没有 `manifest.json`**（只有
`advertising_demo.sqlite` / `table_counts.json` / `quality_report.json`）。
库内那张 `dataset_manifest` 表有 1 行，声明的是构建时间与事实窗，**没有 as_of / 基准日列**：

```
dataset_version v0.2.0   dataset_stage release_candidate   built_at 2026-08-30T02:15:58
amazon_fact_window 2026-07-01 ~ 2026-07-31   attribution {"SP":7,"SB":14,"SD":14}
seed 20260830   source_file_count 31   currency USD
```

`v0.1.0/manifest.json` 同样只有 `amazon_fact_window_start/end`，没有基准日字段。
所以整站显示的 **2026-08-03 只有一个来源**：`/Users/linsen/BAM/09-工作台/core/paths.py:45`
的 `AS_OF`（`WORKBENCH_AS_OF` 可覆盖）。

唯一自带 as_of 的是扩展库 —— `page2_decision_ext.sqlite` 的 `ext_meta` 里
`as_of=2026-08-03`、`ads_source=v0.2.0`、`product_source=v0.3.0`。

**后果**：改 `WORKBENCH_AS_OF` 不会让广告包里的数字跟着变（事实窗仍是 7 月），
但顶栏、`/api/ads/meta`、页面上所有「基准日」字样会变，而扩展库里写死的
`data_as_of=2026-08-03` 不变 —— 两者会当场不一致，且没有任何门禁拦它。
需王楠确认：基准日该不该写进数据包 manifest（写进去谁跟谁对齐）。

### 3. 脉络口径冲突：342 脊椎 vs 521 子体宇宙（**未裁决，不要自己拍**）

两侧都有明文，且都还生效：

| 立场 | 出处 | 原话 / 实测 |
| --- | --- | --- |
| 应当返工到 342 | `/Users/linsen/BAM/00-通用方法与规范/02-模块接入契约.md:55-59` | 「产品对象脊椎固定为 342 个子 ASIN / 5 个父 ASIN……不要引入第三套产品宇宙——**广告包当初自建了一套 521 个子体的维度，与脊椎交集只有 188，父体只对上 2/5，这是目前唯一需要返工的地方**」；同文 §6.3（第 127 行）、门禁 G8（第 449 行）同向 |
| 仍按 521 | `/Users/linsen/BAM/04-广告分析模块/01-方案与数据需求/01-广告Demo数据构建范围.md` | 「产品范围：5 个父 ASIN、**完整 521 个子 ASIN**」（该文档至今未改） |
| 数据包已按 521 建成 | `v0.2.0` 实测 | `dim_product_child` 521 行 / `dim_product_parent` 5 行；与产品包 v0.3.0 的 342 脊椎交集 **188** |

现状的实际情况，两条都要知道：

- **读取层已经绕开了那张表。** 全模块只在 `data.py:149` 读 `prod.dim_product_child`
  取产品身份，广告包自建的 `dim_product_child` / `dim_product_parent`
  **没有任何工作台代码打开**（全文 grep 只命中 `data.py:5` 的注释）。
  `data.py:1-14` 的文件头写明「广告包自建的 521 子体维度不当身份来源用」。
- **但表还在包里，文档还写着 521，G8 也还没全绿。** `/api/ads/meta` 的
  `spine_check` 实测 `off_spine_n=1`、`off_spine=["B088WF1PRW"]` ——
  那是 v0.1.0 时代的明星子 ASIN，不在 342 脊椎里，却仍在候选池
  （候选 343 = 342 脊椎 + 它），并且它是 6 个「有决策版本」里的第 6 个。

**这一条列为已知问题，本文档不裁决。** 要不要重建 `dim_product_child`、
`01-广告Demo数据构建范围.md` 要不要改口径、`B088WF1PRW` 那条老链留不留 ——
需王楠确认。

---

## 目录里有什么

| 子目录 | 放什么 |
| --- | --- |
| `00-源表勘查/` | 19 个只读脚本（`probe_*` / `audit_*` / `dump_*` / `export_agent_samples.py` / `xlsxlite.py`）加一份产物 `page2_candidates.json`。摸源表列名、日期覆盖、广告组口径、跨包交集、Agent 输入合法性用的，不产数据包 |
| `01-方案与数据需求/` | 6 份方案与契约文档 + `agent-samples/`（10 个从跑着的服务取的真实响应）。逐份说明见下面「文档在哪」 |
| `02-数据构建/` | 构建脚本 6 个 + `lib/` 3 个 + 4 份数据产物（`v0.1.0-slice` / `v0.1.0` / `v0.2.0` / `page2-ext`）。**构造说明见 `/Users/linsen/BAM/04-广告分析模块/02-数据构建/README.md`** |
| `03-验收/` | 独立验收契约 `acceptance_contract.json`、检查器 `run_acceptance.py`、验收结果与报告。只验到 v0.1.0，见下 |

---

## 数据包现在用哪一版

判据是**工作台代码实际打开的路径**，不是版本号最大的那个。

| 版本 | 完整路径 | 表 / 行 / 大小 | 判定 | 证据 |
| --- | --- | --- | --- | --- |
| **v0.2.0** | `/Users/linsen/BAM/04-广告分析模块/02-数据构建/v0.2.0/advertising_demo.sqlite` | 34 表 / 61,055 行 / 20 MB | **权威**（主库） | `core/paths.py:54` 的 `ADS_DB` 指它；`modules/ads/data.py:26` `DB_PATH = paths.ADS_DB`；`module.py` 的 `MODULE["db"]` 也是它 |
| **page2-ext** | `/Users/linsen/BAM/04-广告分析模块/02-数据构建/page2-ext/page2_decision_ext.sqlite` | 14 表 / 264 行 / 172 KB | **权威**（第二库，与 v0.2.0 同时在用） | `modules/ads/data.py:30-32` 写路径、`:60` `ATTACH` 成 `ext`；14 张表有 13 张被 `data.py` 读、`ext_meta` 被 `compute.py` 读 |
| v0.1.0 | `/Users/linsen/BAM/04-广告分析模块/02-数据构建/v0.1.0/advertising_demo.sqlite` | 22 表 / 8,192 行 / 3.6 MB | **仍被引用，不是废弃** | ① `02-数据构建/build_v0_2_0.py:37` 把它当 id 复用来源读（质量门禁 `Q-V010-ID-REUSE` 733/733 全数沿用，这是 `B088WF1PRW` 老链在 v0.2.0 里还能解析的原因）；② 它是**唯一做过独立验收的版本**（`03-验收/latest_release_result.json` 的 `dataset` 就是它，`release` 模式 PASS）；③ `00-源表勘查/probe_adgroup_count.py:8`、`02-数据构建/diag_gates.py` 也读它。**没有任何工作台代码打开它** |
| v0.1.0-slice | `/Users/linsen/BAM/04-广告分析模块/02-数据构建/v0.1.0-slice/advertising_demo.sqlite` | 21 表 / 953 行 / 592 KB | **废弃** | 验收前的最小纵向切片，已被同脚本的 `--mode release`（即 v0.1.0）取代。全库 grep：只有 `build_advertising_demo.py:25` 把 `v0.1.0-slice` 当输出版本号字面量，**没有任何代码读它** |

`v0.2.0` 的自检结果在 `v0.2.0/quality_report.json`：13 项全 PASS（含
`Q-ALL-SOURCES 31/31`、`Q-FK 0 violations`、`Q-DAILY-TWO-BASES`、`Q-FIVE-ROLES`）。
**这是构建器自检，不是独立验收** —— v0.2.0 没有走过 `03-验收/run_acceptance.py`。

---

## 工作台哪几个文件读它

服务端 `/Users/linsen/BAM/09-工作台/modules/ads/`：

| 文件 | 行数 | 干什么 |
| --- | ---: | --- |
| `module.py` | 392 | 模块自描述与 12 条路由（契约 8.1，外壳只读这个文件） |
| `data.py` | 829 | 数据层：三库打开与只读取数，`value_origin → 中文性质词` 映射在这里做 |
| `compute.py` | 448 | 算 readiness、`context_hash`、页面二上下文与四段 |
| `page1.py` | 609 | 页面一八板块（对象宇宙、筛选、横向对比、详情抽屉） |
| `rules.py` | 102 | 21 个 `ads.*` 可调参数（观察线、样本门槛、异常四类、日粒度口径） |
| `agent_result.py` | 251 | 读 Agent sidecar 的最新 completed 运行 |
| `agent_loop.py` | 394 | 起本地 Pi Runner、把已落库的一次运行还原成十回合给外壳任务面板 |

**实际打开数据文件的就三处**：

```
core/paths.py:54                ADS_DB      = …/v0.2.0/advertising_demo.sqlite
modules/ads/data.py:30-32       EXT_DB      = …/page2-ext/page2_decision_ext.sqlite
modules/ads/agent_result.py:26  DB          = modules/ads/derived/ads_agent_state.sqlite
                                （agent_loop.py:35 同一个文件）
```

前端：`/Users/linsen/BAM/09-工作台/web/modules/ads.js`（76 KB）、
`/Users/linsen/BAM/09-工作台/web/modules/ads.css`（28 KB）。

12 条路由：`meta` `candidates` `context` `run` `loop` `loop-status` `loop-a1`
`decide` `gate` `catalog` `compare` `object`。

相关检查脚本（在 `/Users/linsen/BAM/09-工作台/tests/`）：
`start_ads_only.py`（独立端口起实例，不碰 18820）、
`check_context_hash_scope.py`（反证 hash 该敏感的敏感、该不敏感的不敏感）、
`check_agent_field_contract.py`（落表 ↔ 接口 ↔ 前端三层字段对账）。

---

## 这个模块的 Agent 状态

**有真 Agent，页面二的四段已经是真跑出来的，不是回放。**

| 项 | 现状 |
| --- | --- |
| Runner | `/Users/linsen/BAM/06-Pi-Agent交互Demo/scripts/run_ads_agent_demo.ts`，本地 `node` 跑，工作台起子进程触发（`agent_loop.py:32-33`） |
| 落表 | `/Users/linsen/BAM/09-工作台/modules/ads/derived/ads_agent_state.sqlite`（源数据包保持只读，Agent 只写这一个文件） |
| 表 | `fact_ads_agent_run`（22 行）+ `fact_ads_agent_output`（707 行）；`fact_ads_agent_stage`（12）/ `fact_ads_agent_item`（40）是 v1 遗留，`agent_result.py:7-8` 已于 2026-08-31 切到 `fact_ads_agent_output` |
| 接缝 | 一读一写：Runner 先从 `/api/ads/context` 只读 `context_hash / context_id / data_as_of`（`06-Pi-Agent交互Demo/src/ads-agent.ts:361-384`，默认 origin `http://127.0.0.1:18820`），判断完只写 sidecar。hash 由工作台算、Runner 原样存，所以两侧天然一致 |
| 模型 | `deepseek/deepseek-v4-flash`（`BAMBOO_ADS_MODEL` 可覆盖） |
| 跑通没跑通 | **跑通了。** 五个演示对象各有一次 completed 运行、八个输出点齐、hash 全部相符：实测 `/api/ads/run` 对 `B0B3LWGP36` `B0B3M8S4CQ` `B0B6ZT7W64` `B0B3MBYGR5` `B0CJV56N43` 全部 `condition=正常`、`pending_points=[]`、`stages=4` |
| 失败记录 | `fact_ads_agent_run` 里有 2 行 `status=failed`（都是 `B0B3LWGP36`，2026-08-31 13:12 / 13:14）。只有 `completed` 会被前端采纳 |

九个输出点：`A1` 广告目的标签建议、`B0b` 目标约束分档、`B0cd` 词与竞品判断、
`B0e` 结构问题识别、`B1` 应有广告任务、`B2` 任务与结构对照、`B3` 广告诊断与优先级、
`B3b` 诊断覆盖说明、`B4` 广告调整方案。其中 `B1/B2/B3/B4` 是页面二的四段揭示，
`B0b/B0cd/B0e` 落在板块 2/3/5。

**A1 还没有 Runner。** `loop-a1` 路由在（`module.py:handle_loop_a1`），但外壳任务面板里
那条任务被刻意注释掉了（`module.py:TASKS` 下的注释：「Agent 侧还没有驱动 A1 的 Runner，
摆在『可运行』里点下去只会挂红失败」）。`latest_purpose_labels()` 现在一律返回「尚未运行 A1」。

**产品目标不是 Agent 判的。** 原输出点 `B0` 已于 2026-08-31 改成**运营在系统里填的输入**
（王楠拍定），`ext_product_goal` 五行实测 `goal_status=confirmed` / `source_ref=operator_set`、
rationale 是运营口径的意图（「保住现有规模，先把库存承接补齐」），不含推断数字。

---

## 文档在哪

| 文件 | 回答什么问题 | 状态 |
| --- | --- | --- |
| `01-方案与数据需求/01-广告Demo数据构建范围.md` | 两页各做什么、产品/广告/时间范围、数据边界档位 | ⚠️ **口径过期**：写「完整 521 个子 ASIN」，与接入契约 §2 的 342 脊椎冲突（见上「三个先看的地方」第 3 条）。未裁决 |
| `01-方案与数据需求/02-广告Demo实现方案.md` | 数据充分性逐表核定、页面一/二的实现方案 | ⚠️ **数字过期**：底座写 `v0.1.0`，表内数字是 v0.1.0 的（`dim_ad_object 733`、`fact_ad_performance 739`）。现行 v0.2.0 是 989 / 984 |
| `01-方案与数据需求/03-页面二Agent接口契约.md` | 页面二的调用形态、四段 NDJSON、板块字段 | ⚠️ **三处已脱节**：① 路由写 `/api/ads2/*`，实际是 `/api/ads/*`；② 写 `POST` + NDJSON 流式，实际是 `GET` 一次返回；③ 写「用已落盘的决策链回放，届时只替换 `lib/decision.py::agent_stages` 的数据来源」——`lib/decision.py` 不存在（现为 `modules/ads/compute.py:329`），且回放已被真 Agent 取代 |
| `01-方案与数据需求/04-广告模块Agent输出点清单.md` | 11 个输出点逐个的字段级契约（给 Agent 实现方） | ⚠️ **部分过期**：开头仍写「当前 Demo 用已落盘的决策链回放…届时只替换读取来源」，真 Agent 已就绪；「v0.2.0（35 表）」实测是 34 表。输出点粒度也与实现不同：文档拆 `B0c`/`B0d`，落表合成 `B0cd` |
| `01-方案与数据需求/05-广告模块交接给Agent.md` | 两个页面长什么样、读了什么表、要 Agent 回什么 | 现行有效（服务 18820、基准日 2026-08-03 与实测一致） |
| `01-方案与数据需求/06-广告Agent契约审计.md` | 按 `08-Agent需求与数据契约要则.md` 逐条自检的结果：输入侧十类证据哪些干净、哪些是「产出侧被当输入喂了」 | 现行有效，且是**未完项清单**：§4.2「数据（要你拍口径再动）」四条、§4.3「门禁」一条仍未动 |
| `01-方案与数据需求/agent-samples/` | 10 个真实接口响应（形状参照，结论已替换成占位符） | 现行有效 |
| `03-验收/README.md` | 独立验收契约的立场、PASS/FAIL/BLOCKED 判定口径 | ⚠️ **路径过期**：正式依据指向 `/Users/linsen/BAM/bamboocool 产品方案/…`，该目录已不存在（2026-09-01 重构后是 `/Users/linsen/BAM/10-产品方案/`） |
| `03-验收/release_acceptance_report.md` | v0.1.0 release 独立复验报告（PASS） | 有效，但**只覆盖 v0.1.0** |

跨模块必读：`/Users/linsen/BAM/00-通用方法与规范/02-模块接入契约.md`（改模块前必读）、
`/Users/linsen/BAM/00-通用方法与规范/09-广告Agent重建两侧分工.md`（接缝契约，sidecar 列定义）、
`/Users/linsen/BAM/00-通用方法与规范/08-Agent需求与数据契约要则.md`（输入/产出边界）。

---

## 已知问题

按严重程度排。**只登记，没改任何文件。**

### 1. 板块9 拍板对 Agent 产出的建议是断的（实测可复现）

页面上四段来自真 Agent（`ads_agent_state.sqlite`），但 `/api/ads/decide` 走的是
`compute.agent_stages`（`compute.py:329`），它读的是 **page2-ext 里预先构造的那条链**。
两条链的建议 id 不是同一套：

```
Agent 的 B4 建议 id （/api/ads/run 返回、ads.js:1806 原样回传）  rec_B0B3LWGP36_01 / _02
构造链的建议 id   （ext_recommendation 里）                      r_GP36_01 … r_GP36_05

实测：
  GET /api/ads/decide?child_asin=B0B3LWGP36&decision=accept&recommendation_id=rec_B0B3LWGP36_01
    → {"condition":"缺失","message":"找不到这条建议"}
  GET /api/ads/decide?child_asin=B0B3LWGP36&decision=accept&recommendation_id=r_GP36_01
    → {"condition":"正常", …交接块…}
```

前端 `ads.js:1806` 传的是 `p.recommendation_id`，即 Agent 那一套。
**所以运营在页面上点任何一条 Agent 建议的「接受/修改/拒绝/暂缓」，后端必然报「找不到这条建议」。**

### 2. `/api/ads/gate` 门禁校的不是 Agent 的输出

`validate_evidence_refs`（`compute.py:391-405`）内部调 `agent_stages`，
校的是**构造链**的 `evidence_ids`，不是 Agent 落在 `fact_ads_agent_output` 里的引用。
实测 `condition=正常 / checked=6 / failed=[]` —— 这个绿灯不能证明 Agent 的依据引用没有悬空。

### 3. page2-ext 里的构造结论链仍与 Agent 产出并存

`ext_required_ad_task` / `ext_task_ad_object` / `ext_diagnosis` / `ext_recommendation` /
`ext_diagnosis_coverage` / `ext_goal_constraint` / `ext_structure_issue`
这七张是**产出侧**的构造结论，Agent 已经能自己产出对应的 `B0b/B0e/B1/B2/B3/B3b/B4`。
它们现在的唯一去处是上面第 1、2 条那两条路由。
`06-广告Agent契约审计.md` §4.2 已列为「要你拍口径再动」，未动。

### 4. `B088WF1PRW` 这条 v0.1.0 老链还在候选池里

它不在 342 脊椎内（`/api/ads/meta` 的 `spine_check.off_spine`），
证据与决策链落在 v0.2.0 包自己的 `fact_decision_context` / `fact_decision_evidence` /
`fact_required_ad_task` / `fact_ad_diagnosis` / `fact_ad_recommendation` 等表里，
`data.py` 走 `is_ext=False` 分支读。留着它 = G8 永远差一个；去掉它 = v0.1.0 时代的
纵向切片验收证据在页面上就没有对应对象了。**需王楠确认取舍。**

### 5. v0.2.0 没有独立验收，也没有 manifest 文件

`03-验收/` 的两份 result JSON 的 `dataset` 都指向 v0.1.0。v0.2.0 只有构建器自检
（`quality_report.json` 13 项 PASS）。同时 v0.2.0 目录下没有 `manifest.json`
（v0.1.0 / v0.1.0-slice 都有），也没有 `schema.sql` / `lineage.json`。

### 6. v0.2.0 里有 10 张表没有任何工作台代码读

`dataset_manifest`、`dim_audience`、`fact_audience`、`dim_placement`、`fact_creative`、
`fact_page1_result`、`fact_page1_anomaly`、`fact_search_term_share`、`scenario_registry`、
`source_lineage`。其中 `fact_search_term_share` 有 34,109 行，是 20 MB 库里最大的一块，
但页面一的搜索词面板并不读它。判不出这是「留给后续页面的」还是「构建时顺手落的」——
**需王楠确认**。分类见 `/Users/linsen/BAM/04-广告分析模块/02-数据构建/README.md`。

### 7. 小项

- `check_agent_field_contract.py` 文件头第 6 行仍写「第一层 Agent 落表
  `fact_ads_agent_item.payload`」，脚本正文（第 94 行）读的已经是 `fact_ads_agent_output`。
- `modules/ads/derived/runner-*.log` 里的 `db_path` 写着
  `/Users/linsen/BAM/06-Bamboocool-Demo重建/09-工作台/…` —— 那是 2026-09-01 重构前的路径。
  日志是 08-31 的历史产物，Runner 本身按相对路径解析（`ads_agent_facts.py:21-22`
  `PROJECT.parents[1]`），重构后不受影响。
- `agent_result.py` 留了 `WORKBENCH_ADS_SEAM=1` 旁路：hash 不符时也把结果放上屏，
  前端画红 chip。默认关，但环境变量一旦被谁设上，页面会显示对不上的结论。
