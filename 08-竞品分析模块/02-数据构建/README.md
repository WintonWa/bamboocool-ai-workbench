# 竞品数据包怎么造出来的

一条线性三步链，**三步落在同一个 sqlite 文件上**——第三步不另建库，是在第二步的产物上
原地加表。这一点跟契约文档写的「两个库」不一样，看代码为准（见 §5 第 3 条）。

数据包只有一版 `v0.1.0`，就是权威版。判据是 `/Users/linsen/BAM/09-工作台/core/paths.py:62`
的 `COMPETITOR_DB` 字面量指向它，`/Users/linsen/BAM/09-工作台/modules/competitor/data.py:78`
以 `mode=ro` 打开它。没有旧版，所以没有「废弃还是仍被引用」的判定问题。

---

## 1. 构建链

```
客户原始数据
├─ /Users/linsen/BAM/数据源/AI广告对接数据-总20260803/9.竞品.xlsx            1,131,345 B  2026-08-11
├─ /Users/linsen/BAM/数据源/AI广告对接数据-总20260803/10.关键词/关键词3.xlsx  1,161,345 B  2026-08-11
└─ /Users/linsen/BAM/02-产品销售库存模块/02-数据构建/v0.3.0/
       bamboocool_product_sales_inventory_v0.3.0.sqlite        ← 自有一侧的产品脊椎
              │
              │  ① 01_extract_sources.py
              ▼
   /Users/linsen/BAM/08-竞品分析模块/02-数据构建/_sources.json   114,571 B
   38 族 / 209 子体 / 48 关键词
              │
              │  ② 02_build_demo.py   （先 os.remove 再重建）
              ▼
   /Users/linsen/BAM/08-竞品分析模块/02-数据构建/v0.1.0/competitor_demo.sqlite
   13 表 + 3 索引  ← 观察层
              │
              │  ③ 03_build_analysis.py  （同一个文件，原地 CREATE TABLE 追加）
              ▼
   同一个文件，23 表 / 47,166 行 / 8,712,192 B  ← 观察层 + v1 判断产物
```

**② 和 ③ 必须成对跑，顺序不能颠倒也不能只跑一个。**
② 开头 `os.remove(DB)` 重建干净库，所以 ③ 只能跟在 ② 后面；
③ 的 `SCHEMA` 里除 `competitor_manifest` 用了 `IF NOT EXISTS`，其余 10 张全是裸
`CREATE TABLE`，单独重跑 ③ 会撞已存在的表直接报错。

③ 还会用 `INSERT OR REPLACE` **改写 ② 写好的 manifest**：
`dataset_version` 从 `observation-v0.1.0` 改成 `agent-v0.1.0`，原值搬到
`observation_package_version`，再补 `agent_version` / `run_count` / `scope`，
并覆写 `generated_at` 和 `provenance`。所以库内 `competitor_manifest` 的 15 个键里，
时间戳和版号说的都是**第三步**跑完的时刻。

---

## 2. 每个脚本一行

| 脚本 | 大小 / mtime | 输入 | 输出 | 能不能重跑 |
| --- | --- | --- | --- | --- |
| `/Users/linsen/BAM/08-竞品分析模块/02-数据构建/01_extract_sources.py` | 9,677 B · 2026-08-31T16:22:26Z | `9.竞品.xlsx`（筛小类目 = `Men's Boxer Briefs`、子体 ≥ 4、价格中位落 $10~$40，按月销量取前 48，实得 38 族，每族取销量前 6 子体）；`关键词3.xlsx`（前三位命中竞品族且有月搜索量的词，取前 48）；产品包 v0.3.0（`read_own()` 读了但**没用**，见 §5 第 4 条） | `_sources.json` | 能。无随机数，幂等。只写 `_sources.json`，不写任何源目录 |
| `/Users/linsen/BAM/08-竞品分析模块/02-数据构建/02_build_demo.py` | 21,453 B · 2026-08-30T11:16:37Z | `_sources.json` + 产品包 v0.3.0（取 342 子 ASIN 脊椎与基准日售价，算件单价配 147 条竞争关系） | `v0.1.0/competitor_demo.sqlite` 的 13 表 + 3 索引 | 能，结果一致（`SEED=20260803` 固定）。**会先删库重建** |
| `/Users/linsen/BAM/08-竞品分析模块/02-数据构建/03_build_analysis.py` | 28,911 B · 2026-08-31T00:44:11Z | 同一个库的观察表 + `dim_competitor_scenario` | 同一个文件原地追加 10 张判断表，并改写 manifest | **不能单独重跑**（表已存在会报错）。`SEED=20260830` 固定，跟在 ② 后面跑结果一致 |
| `/Users/linsen/BAM/08-竞品分析模块/02-数据构建/lib/xlsxlite.py` | 4,972 B · 2026-08-30T10:43:59Z | — | 被 ① import，无第三方依赖地读 xlsx | 库文件，不单独跑 |

中间产物 `_sources.json`（114,571 B · 2026-08-30T11:14:10Z）只有五个顶层键：
`as_of` / `window_from` / `sub_category` / `families` / `keywords`。自有一侧不在里面
（契约 6.3 要求 `ATTACH` 产品包读，不在本包重建产品维度）。

---

## 3. 每一版数据包

只有一版。

| 项 | v0.1.0 |
| --- | --- |
| 路径 | `/Users/linsen/BAM/08-竞品分析模块/02-数据构建/v0.1.0/competitor_demo.sqlite` |
| 表数 / 行数 | 23 表 / 47,166 行 |
| 大小 / 索引 | 8,712,192 B（8.3 MB）/ 27 个索引（显式建的 4 个：② 的 3 个 + ③ 的 `idx_run_family`，其余 23 个是主键自动索引） |
| 基准日 | `2026-08-03` |
| 观察窗 | `2026-02-05 ~ 2026-08-03`；逐日 180 天、关键词位置 27 个观察日（周粒度）、流量结构 6 期（月粒度） |
| 落盘 | 文件 mtime 2026-08-31T00:45:19Z；库内 `generated_at` 2026-08-31T00:44:19Z |
| 定性 | **权威**（`paths.py:62` 指向它） |
| 附件 | `dataset-manifest.json`（本次新增，23 张表逐表字段/主键/行数 + 门禁实测结果） |

逐表行数：

| 表 | 行数 | | 表 | 行数 |
| --- | --- | --- | --- | --- |
| `fact_competitor_price_daily` | 37,536 | | `fact_competitor_analysis_attention_reason` | 37 |
| `fact_competitor_market_daily` | 6,826 | | `fact_competitor_analysis_timeline` | 27 |
| `fact_competitor_keyword_rank` | 1,809 | | `fact_competitor_analysis_change` | 25 |
| `fact_competitor_traffic_mix` | 228 | | `fact_competitor_analysis_run` | 20 |
| `dim_competitor_child` | 209 | | `fact_competitor_analysis_diff` | 20 |
| `bridge_competitor_child` | 147 | | `competitor_manifest` | 15 |
| `bridge_competitor_keyword` | 67 | | `dim_competitor_scenario` | 12 |
| `dim_competitor_offer` | 61 | | `fact_competitor_analysis_open_item` | 12 |
| `dim_competitor_keyword` | 48 | | `fact_competitor_analysis_impact` | 8 |
| `dim_competitor_family` | 38 | | `fact_competitor_analysis_report` | 6 |
| `fact_competitor_data_status` | 6 | | `fact_competitor_evidence_handoff` | 5 |
| | | | `fact_competitor_analysis_concurrency` | 4 |

---

## 4. 表的分类

这一节是这个包最容易被误读的地方：**23 张表里有 10 张是 Agent 判断产物，
但现在没有任何东西读它们。** 看到它们就以为「这个包依赖 Agent 输出」是反的——
Agent 读这个包，不写它。

### A. 客户原始导出派生的观察事实（5 张）

身份、报价、关键词库与前三命中，来自 `9.竞品.xlsx` / `关键词3.xlsx` 的真实导出。

| 表 | 行数 | 说明 |
| --- | --- | --- |
| `dim_competitor_family` | 38 | 竞品父体身份。`monitor_status` 全 `monitoring`；`in_analysis_scope=1` 的 20 族、`in_quick_slot=1` 的 8 族 |
| `dim_competitor_child` | 209 | 子体身份、装盒数、快照价与件单价 |
| `dim_competitor_offer` | 61 | 报价层。BuyBox 那 38 条 `direct`（真实卖家），补齐的 23 条 `derived` |
| `dim_competitor_keyword` | 48 | 关键词市场指标（ABA 排名、月搜索、需供比、PPC 竞价）；`is_battleground=1` 的 5 个 |
| `bridge_competitor_keyword` | 67 | 族 × 关键词的前三命中关系，全部来自真实 ABA 前三 |

### B. 构造的逐日 / 逐周序列，锚定真实快照（6 张）

序列是造的，但**末日一定等于真实快照**，`value_origin` 逐行标注真假边界。

| 表 | 行数 | `value_origin` 实测 |
| --- | --- | --- |
| `fact_competitor_price_daily` | 37,536 | `direct` 209（基准日 = 卖家精灵快照价）+ `constructed` 37,327。活动日：`deal` 138 / `coupon` 87 / `none` 37,311 |
| `fact_competitor_market_daily` | 6,826 | `direct` 38（基准日快照）+ `constructed` 6,788 |
| `fact_competitor_keyword_rank` | 1,809 | `direct` 67（基准日 = 真实 ABA 前三）+ `derived` 1,742。只覆盖 11 个族——只有真实命中过前三的族才有位置行 |
| `fact_competitor_traffic_mix` | 228 | 全 `constructed`（第三方估算）。**月粒度**，`period_start` 取月初，最早一期 `2026-02-01` 比窗口起点 `2026-02-05` 早 4 天，这是月粒度的正常口径，门禁 G4 有专门说明 |
| `fact_competitor_data_status` | 6 | 观察质量标注：`missing` 3 / `interrupted` 1 / `conflict` 1 / `stale` 1 |
| `bridge_competitor_child` | 147 | 竞品族 ↔ 自有子体的竞争关系，全 `constructed`（按同子类目 + 件单价同带配的）。`confirmed` 126 / `pending_review` 21；自家一侧 42 个子 ASIN、4 个父体，全部落在 342 个脊椎内 |

### C. 演示脚手架，Agent 禁读（1 张）

| 表 | 行数 | 说明 |
| --- | --- | --- |
| `dim_competitor_scenario` | 12 | `family_asin → 形态名 + 该得出什么结论` 的映射。**这是答案键**，`01-方案与数据需求/04-Agent输出点盘点.md` 的 0.2 明确列为禁读，前端也不上屏。构建脚本 `03_build_analysis.py:85` 和门禁 `test_contract_gates.py:71` 读它是合法的（构建侧和验收侧读，不是 Agent 读） |

### D. v1 时代的 Agent 判断产物，已无人读（10 张，共 164 行）

`03_build_analysis.py` 原地加在观察库上的，当时前端从这里拿判断。

| 表 | 行数 | | 表 | 行数 |
| --- | --- | --- | --- | --- |
| `fact_competitor_analysis_run` | 20 | | `fact_competitor_analysis_attention_reason` | 37 |
| `fact_competitor_analysis_change` | 25 | | `fact_competitor_analysis_impact` | 8 |
| `fact_competitor_analysis_timeline` | 27 | | `fact_competitor_analysis_open_item` | 12 |
| `fact_competitor_analysis_concurrency` | 4 | | `fact_competitor_analysis_report` | 6 |
| `fact_competitor_analysis_diff` | 20 | | `fact_competitor_evidence_handoff` | 5 |

**判「已无人读」用的证据（两条，都在代码里）：**

1. `/Users/linsen/BAM/09-工作台/modules/competitor/data.py` 里所有判断层查询——`LATEST`
   常量、`changes()`、`all_changes()`、`timeline()`、`concurrency()`、`attention_reasons()`、
   `impacts()`、`open_items()`、`diff()`、`handoffs()`、`report()`——**每一条都带 `agent.` 前缀**，
   指向 `:81` `ATTACH` 进来的外部 sidecar。主库里的同名表一次都没被 `SELECT`。
2. `/Users/linsen/BAM/08-竞品分析模块/03-验收/test_contract_gates.py` 头部第 9 行原话：
   「观察库里那 9 张 legacy `fact_competitor_analysis_*` 是禁读的，不参与门禁」。
   门禁的判断层断言全部走 `agent.` 前缀。

**现在真正被读的判断库**是
`/Users/linsen/BAM/09-工作台/modules/competitor/derived/competitor_agent_state_v2.sqlite`
（11 表 = 这 10 张 + 执行台账 `fact_competitor_agent_execution`）。

同名不同库很容易读错：`fact_competitor_analysis_run` 在本包里 20 行（构造的，死表），
在 v2 sidecar 里 8 行（Agent 真跑出来的）。**看到这个表名先确认是哪个库。**

### E. 元数据（1 张）

`competitor_manifest` 15 行，库内自述（基准日、窗口、族数、版号、来源、provenance）。

---

## 5. 重跑要什么

**输入**（三个都实测存在）

- `/Users/linsen/BAM/数据源/AI广告对接数据-总20260803/9.竞品.xlsx`
- `/Users/linsen/BAM/数据源/AI广告对接数据-总20260803/10.关键词/关键词3.xlsx`
- `/Users/linsen/BAM/02-产品销售库存模块/02-数据构建/v0.3.0/bamboocool_product_sales_inventory_v0.3.0.sqlite`

**解释器**：必须 `/usr/bin/python3`（3.9.6）。`lib/xlsxlite.py` 解 xlsx 依赖 `lxml`，
本机只有这个解释器带。3.9 的 f-string 里不能含反斜杠。

**顺序**

```bash
cd /Users/linsen/BAM/08-竞品分析模块/02-数据构建
/usr/bin/python3 01_extract_sources.py      # → _sources.json
/usr/bin/python3 02_build_demo.py           # → v0.1.0/competitor_demo.sqlite（先删后建）
/usr/bin/python3 03_build_analysis.py       # → 同一个文件原地加 10 表
/usr/bin/python3 ../03-验收/test_contract_gates.py
```

**耗时：未实测。** 本次交付是只读的，跑 ② 会删库重建，没跑。
规模参考：最大的写入是 37,536 行价格 + 6,826 行市场 + 1,809 行关键词位置，成品 8.3 MB。

**五个坑**

1. **别 `cd` 进 `/Users/linsen/BAM/09-工作台/modules/` 跑任何 python**——`modules/keyword/`
   会遮蔽标准库的 `keyword`，报错信息（`from keyword import iskeyword`）跟你的代码毫无关系。
2. **重跑会让 sidecar 里已有的分析全部变「过期」。** `data.py` 的 `source_context_hash()`
   把观察层整段打成指纹，`analysis_state()` 发现 run 的 hash 与当前不一致就返回 `stale`。
   `02_build_demo.py` 的逐日序列带 `rng` 抖动，重跑必然换指纹。页面会把 5 个族的现有分析
   显示成过期，要重新发起才恢复。
3. **③ 不能单独跑**（见 §1）。要重建判断表只能 ② + ③ 一起。
4. `01_extract_sources.py` 的 `read_own()` 会打开产品包读自有子体和逐日价格，但 `main()`
   **没用它的返回值**（脚本自己打印「自有侧不落盘」）。死代码，白读一遍产品库，可以删但没删。
5. **步骤一改过之后没重跑过全链**：`01_extract_sources.py` 的 mtime（2026-08-31T16:22:26Z）
   晚于 `_sources.json`（2026-08-30T11:14:10Z）和数据包（2026-08-31T00:45:19Z）。
   改了什么**判不出**——这些脚本没纳入 git（`git ls-files` 报未匹配），没有 diff 可看。
   **需王楠确认**要不要按新版脚本重跑。

**另外两处代码痕迹**（不影响跑，但会误导读代码的人）

- `03_build_analysis.py` 第 17–18 行 `OBS` 和 `DB` 指向同一个文件，是「两个库」时代的残留；
  它的 docstring 也还写着「建 Agent 库」，实际是在观察库上原地加表。
- `01-方案与数据需求/02-竞品Agent接口契约.md` §1 写的是两个独立库
  （`competitor_observation.sqlite` / `competitor_agent.sqlite`），和落盘对不上。
  文档过期清单见 `/Users/linsen/BAM/08-竞品分析模块/README.md` §5。

---

## 6. 验收

```bash
/usr/bin/python3 /Users/linsen/BAM/08-竞品分析模块/03-验收/test_contract_gates.py
```

22 条断言（G1–G9、G11、G12、A1–A3、C1–C8，没有 G10）+ 2 条 INFO 覆盖提示。
脚本把 INFO 计进 passed，所以末行显示的是 `23 passed, 1 failed`。

**实测（2026-09-02）：21 条 PASS，1 条 FAIL。**

- 读本包的 A1–A3（末日价格 = 快照价、评论数单调不减、断更区间内无观察）和
  C1–C8（表名前缀、未重建产品维度、`value_origin` 取值、脊椎 342 内、数据状态取值、
  `item_kind` 取值、`report_id` 可推导、`handoff_id` 可推导）**全绿**。
- FAIL 的是 G1：它要求每个 run 至少一条变化行，但 `data.py` 的 `analysis_state()` 明确允许
  `evidence_level='insufficient'` 的 run 零变化（V2 契约允许在证据步短路），
  v2 sidecar 里正好有 1 个 insufficient run。**门禁没跟上这条短路，不是本包的观察数据有问题。**
- G 系列全部读外部 sidecar，结论随那个库的内容变，不由本包决定。
