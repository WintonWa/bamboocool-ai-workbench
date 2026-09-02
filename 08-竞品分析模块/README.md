# 08-竞品分析模块

判断对象是**竞品产品族（父 ASIN）**：把一个竞品父体在观察窗内的价格活动、市场表现、
关键词位置、流量结构四条轨看成一件事，判断它这段时间发生了什么变化、要不要关注、
对自有哪些子体有压力。范围是**美国站 · 男士内裤 · Men's Boxer Briefs**，
基准日 `2026-08-03`，观察窗 `2026-02-05 ~ 2026-08-03`，**没有未来区间**（竞品不做预测）。

模块 id `competitor`，参数前缀 `cmp`，两个页面：`cmp-overview`（竞品威胁总览）、
`cmp-rival`（单一竞品分析）。

---

## 1. 目录里有什么

| 路径 | 放什么 |
| --- | --- |
| `/Users/linsen/BAM/08-竞品分析模块/01-方案与数据需求/` | 5 份方案文档（4 md + 1 json 样例），逐份说明见 §5 |
| `/Users/linsen/BAM/08-竞品分析模块/02-数据构建/` | 三步构建脚本 + `_sources.json` 中间产物 + `lib/xlsxlite.py`（无依赖 xlsx 读取）。构造说明见 `/Users/linsen/BAM/08-竞品分析模块/02-数据构建/README.md` |
| `/Users/linsen/BAM/08-竞品分析模块/02-数据构建/v0.1.0/` | 数据包本体 `competitor_demo.sqlite` + `dataset-manifest.json` |
| `/Users/linsen/BAM/08-竞品分析模块/03-验收/` | `test_contract_gates.py`，22 条断言 + 2 条 INFO 覆盖提示 |

模块的工作台侧代码不在这里，在 `/Users/linsen/BAM/09-工作台/modules/competitor/`（见 §3）。

---

## 2. 数据包现在用哪一版

**只有一版，`v0.1.0`，它就是权威版。** 竞品模块没有历史版本，所以不存在库存/广告那种
「哪一版还在用」的判定问题。

```
/Users/linsen/BAM/08-竞品分析模块/02-数据构建/v0.1.0/competitor_demo.sqlite
```

| 项 | 实测 |
| --- | --- |
| 表数 | 23（观察 12 + 演示脚手架 1 + v1 判断产物 10，见 §6 第 1 条） |
| 总行数 | 47,166；最大三张：`fact_competitor_price_daily` 37,536、`fact_competitor_market_daily` 6,826、`fact_competitor_keyword_rank` 1,809，其余全在百行级以下 |
| 大小 / 索引 | 8,712,192 B（8.3 MB）/ 27 个索引（显式 4 个，其余为主键自动索引） |
| 基准日 | `2026-08-03`（库内 `competitor_manifest.as_of`） |
| 观察窗 | `2026-02-05 ~ 2026-08-03`，逐日 180 天；关键词位置周粒度 27 个观察日；流量结构月粒度 6 期 |
| 覆盖 | 38 个竞品族 / 209 个子体 / 48 个关键词；其中 20 族在分析范围内（`in_analysis_scope=1`）、8 族在快捷位 |
| 落盘时间 | 2026-08-31T00:45:19Z（文件 mtime）；库内 `generated_at` = 2026-08-31T00:44:19Z |

判它是权威版的证据是**代码实际打开的路径**：

- `/Users/linsen/BAM/09-工作台/core/paths.py:62` — `COMPETITOR_DB` 的字面量默认值就是上面这个路径，
  可用环境变量 `WORKBENCH_COMPETITOR_DB` 覆盖。这是唯一登记处。
- `/Users/linsen/BAM/09-工作台/modules/competitor/data.py:78` — `mode=ro` 打开它。
- `/Users/linsen/BAM/09-工作台/modules/competitor/module.py:342` — `MODULE["db"] = paths.COMPETITOR_DB`。

`v0.1.0/` 目录下除了这个库和本次新增的 manifest，没有别的文件。

---

## 3. 工作台哪几个文件读它

| 文件 | 行数 | 干什么 |
| --- | --- | --- |
| `/Users/linsen/BAM/09-工作台/core/paths.py` | 69 | `:62` 登记 `COMPETITOR_DB` 路径；`:49` 登记产品包 `PRODUCT_DB` |
| `/Users/linsen/BAM/09-工作台/modules/competitor/data.py` | 562 | 只读数据层。`:78` 打开主库，`:79` `ATTACH` 产品包 v0.3.0 为 `pr`（契约 6.3：产品维度不在本包重建），`:44-47` + `:81` `ATTACH` Agent 状态库为 `agent` |
| `/Users/linsen/BAM/09-工作台/modules/competitor/compute.py` | 459 | 两页载荷装配 |
| `/Users/linsen/BAM/09-工作台/modules/competitor/module.py` | 344 | 自描述入口：路由 `meta` / `rivals` / `rival` / `analyze` / `analyze-status`，任务 `competitor-analysis` |
| `/Users/linsen/BAM/09-工作台/modules/competitor/rules.py` | 67 | `cmp.*` 参数声明与夹紧（七个阈值） |
| `/Users/linsen/BAM/09-工作台/web/modules/competitor.js` | 1,026 | ES module，自注册，走 `ctx.api("meta"/"rivals"/"rival/<asin>")` |
| `/Users/linsen/BAM/09-工作台/web/modules/competitor.css` | 714 | 作用域样式，全在 `[data-module="competitor"]` 之下 |
| `/Users/linsen/BAM/09-工作台/modules/agentcfg/registry_seed.py` | 492 | `:417` 登记 v1 Agent 状态库、`:434` 登记 v2，供「Agent 输出记录」页读运行台账 |
| `/Users/linsen/BAM/08-竞品分析模块/03-验收/test_contract_gates.py` | — | 门禁，同时读本包（`main`）、产品包（`pr`）、Agent 状态库（`agent`） |

**这个模块一次要挂三个库**：本包（观察）+ 产品包 v0.3.0（自有一侧的产品身份与价格）+
Agent 状态库（判断结论）。三个都是 `mode=ro`；模块自己一行都不写库。

---

## 4. 这个模块的 Agent 状态

有 Agent，跑通了，但只跑过一小部分族。

| 项 | 实测 |
| --- | --- |
| Agent id | `competitor-threat`；实现在 `/Users/linsen/BAM/06-Pi-Agent交互Demo/src/competitor-agent-v2.ts` |
| 落表在哪 | `/Users/linsen/BAM/09-工作台/modules/competitor/derived/competitor_agent_state_v2.sqlite`（11 表，147,456 B）。默认值写在 `data.py:44-47`，可用 `WORKBENCH_COMPETITOR_AGENT_DB` 覆盖 |
| 怎么发起 | 模块只读库，所以「重新分析这个竞品」是转调 Agent 侧任务服务：`POST {WORKBENCH_AGENT_ORIGIN}/api/agent/competitor/runs`（`module.py` 的 `AGENT_RUNS_PATH`，默认 origin `http://127.0.0.1:18812`），由 Agent 写库。页面轮 `analyze-status` 读执行台账 |
| 跑到哪一步 | 执行台账 25 条，覆盖 8 个族：completed 8 / skipped 8 / failed 9。判断 run 8 条，覆盖 5 个族；证据档位 sufficient 7 / insufficient 1；关注度 medium 7 / none 1。`model_version` 全部 `deepseek/deepseek-v4-flash`。台账时间 2026-08-31T03:01:15Z ~ 06:52:48Z |
| 9 条失败的原因 | 3 条「本地任务服务已重启，请重新发起分析」（并发跑第二个任务服务把在飞任务判死，不是 Agent 判断本身的问题）；5 条 Agent 侧自检门禁没过（装配契约 3 条 + 证据步 2 条）；1 条「运行或提交失败」 |
| 8 条 skipped | 「自 2026-08-31 起无新观察数据，沿用已有分析」——观察层没变时短路，是合法结果 |

**v1 状态库还在**：`/Users/linsen/BAM/09-工作台/modules/competitor/derived/competitor_agent_state.sqlite`
（11 表，106,496 B，5 条 completed 覆盖 4 个族，2026-08-31T01:43 ~ 01:49Z）。
竞品页已经不读它了，但**「Agent 输出记录」页还在读**（`registry_seed.py:417`，sid `cmp`）。
删它必须同时改那一处，否则那页会少一个来源。

`derived/quarantine-20260831-scenario-leak/` 里有三个 `.bak`（v1 库 114,688 B、
`competitor_agent_latest.json`、一个空占位），从目录名看是为 scenario 泄漏做的隔离，
但目录里没有说明文件，隔离原因只能靠名字推。

---

## 5. 文档在哪，哪些过期了

全在 `/Users/linsen/BAM/08-竞品分析模块/01-方案与数据需求/`。

| 文档 | 规模 | 回答什么问题 | 状态 |
| --- | --- | --- | --- |
| `01-能力清单与数据需求.md` | 287 行 | 方案九项能力怎么拆成字段级数据需求；真实源现场实测能给什么；哪些必须构造、构造锚是什么；哪些项 blocked | 未发现与落盘矛盾 |
| `02-竞品Agent接口契约.md` | 510 行 | 四层职责、两个库的分工、观察库与 Agent 库逐表 schema、工作台读取规则、门禁、词表纪律 | **已过期，见下** |
| `03-屏幕决策设计.md` | 180 行 | 两页的用户与核心问题、首屏阅读顺序、组件表达什么数据关系、状态、可验证验收标准、未确认的阈值与因果 | 未发现与落盘矛盾 |
| `04-Agent输出点盘点.md` | 421 行 | Agent 逐表字段规格、12 处中文文案槽、**禁读清单**、不许输出什么、工作台怎么消费 | **一处过期**：§0 把 Agent 输出库写成 v1 的 `competitor_agent_state.sqlite`，而 `data.py:46` 的默认值已经是 `_v2` |
| `05-Agent交底包.md` | 421 行 | 给 Agent 的总交底：模块干什么、两页结构、外壳与模块分工、读哪里写哪里、构造数据的真假边界、输出形状与自查 | 未发现与落盘矛盾 |
| `06-Agent输出样例.json` | 10,562 B | 输出形状样例（虚构族，只给 schema 与词表，不给答案） | — |

`02-竞品Agent接口契约.md` 的过期点（都在 §1 与 §2.1，逐条对过落盘 schema）：

1. 库名对不上：契约写 `competitor_observation.sqlite` / `competitor_agent.sqlite`，
   落盘是 `competitor_demo.sqlite` / `competitor_agent_state_v2.sqlite`。
2. `ATTACH` 别名与表名对不上：契约 §1 的 SQL 例子用 `AS ag` 和 `ag.fact_analysis_run`，
   实际是 `AS agent` 和 `agent.fact_competitor_analysis_run`（`data.py:81` 与 `LATEST` 常量）。
3. 表数对不上：契约说「第 3 节的九张表」，Agent 状态库实际是 10 张判断表 +
   1 张执行台账 `fact_competitor_agent_execution`（V2 任务服务加的）。
4. 少一列：契约 §2.1 的 `dim_competitor_family` 没有 `in_analysis_scope`，落盘有，
   而且它是「哪 20 族在分析范围内」的唯一依据。

另外 `04` 说观察层 12 张、`05` 说观察 13 表，差的是 `dim_competitor_scenario`——
`04` 把它单列为禁读所以不计入，两处不矛盾，只是口径不同。

---

## 6. 已知问题

1. **观察包里混着 10 张 v1 时代的 Agent 判断产物表**（9 张 `fact_competitor_analysis_*`
   加 `fact_competitor_evidence_handoff`，共 164 行），是 `03_build_analysis.py` 原地加在
   观察库上的。**现在没有任何东西读它们**：`data.py` 里所有判断层查询都带 `agent.` 前缀
   （指向外部 sidecar），门禁脚本头部第 9 行明写这 9 张 legacy 表禁读、不参与门禁。
   后果是包看起来像「依赖 Agent 输出」，实际方向相反——Agent 读这个包，不写它。
   分类见 `/Users/linsen/BAM/08-竞品分析模块/02-数据构建/README.md` 的「表的分类」。

2. **门禁当前 1 条 FAIL：G1。** G1 要求每个 run 至少有一条变化行，但
   `data.py` 的 `analysis_state()` 明确允许 `evidence_level='insufficient'` 的 run 零变化
   （V2 契约允许在证据步短路），sidecar 里正好有 1 个 insufficient run。
   G1 没跟上这条短路，两边口径打架。读本包的 A1–A3、C1–C8 全绿。

3. **步骤一改过之后没重跑全链。** `01_extract_sources.py` 的 mtime 是 2026-08-31T16:22:26Z，
   晚于它的产物 `_sources.json`（2026-08-30T11:14:10Z）和数据包（2026-08-31T00:45:19Z）。
   改了什么**判不出**：这些构建脚本没纳入 git（`git ls-files` 报未匹配），没有 diff 可看。
   **需王楠确认**这次改动要不要重跑，重跑后现有分析会全部变「过期」（见下一条）。

4. **重跑数据包会让 sidecar 里已有的分析变「过期」。** `data.py` 的 `source_context_hash()`
   把观察层整段打成指纹，`analysis_state()` 一旦发现 run 的 hash 和当前不一致就返回 `stale`。
   `02_build_demo.py` 里逐日序列带 `rng` 抖动，重跑必然换 hash。

5. **v1 状态库删不掉**：`registry_seed.py:417` 还登记它。要删就同时改那一处。

6. `01_extract_sources.py` 的 `read_own()` 会打开产品包读自有子体和逐日价格，但 `main()`
   根本没用它的返回值（脚本自己打印「自有侧不落盘」）。是死代码，白读一遍产品库。

7. `03_build_analysis.py` 第 17–18 行的 `OBS` 和 `DB` 两个常量指向**同一个文件**，
   是「两个库」时代的残留。它的 docstring 也还写着「建 Agent 库」，实际是在观察库上原地加表。

8. `/Users/linsen/BAM/09-工作台/modules/competitor/README.md` 里写「20 条门禁」，
   实际现在是 22 条断言（G1–G9、G11、G12、A1–A3、C1–C8，没有 G10）。

9. `derived/quarantine-20260831-scenario-leak/` 没有说明文件，为什么隔离只能从目录名推。

10. 关键词位置只覆盖 11 个族（38 个族里）——只有在真实 ABA 前三里命中过的族才有位置行。
    38 族都有市场表现和价格序列，但按关键词看总览时有 27 个族是空的。
    这是**构造边界的自然结果**（不编不存在的位置），不是缺数据，但页面上要说清楚。
