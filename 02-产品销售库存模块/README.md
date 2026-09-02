# 产品销售库存模块

> 站在这个目录门口的第一张纸。项目全局索引在 `/Users/linsen/BAM/00-项目总入口.md`。

## 这个模块是什么

以**子 ASIN 为最小盘点单元**，回答「哪些货该补、什么时候断货、哪些压着不动」。
判断对象 342 个在售子 ASIN（5 个父 ASIN），基准日 `2026-08-03`。

**它是全树的根节点。** 关键词、竞品、广告三个模块都 ATTACH 这个模块的数据包去取产品身份
（子 ASIN ↔ 父 ASIN ↔ 款号的对应关系），不自建产品维度。改这个包会连带影响另三个模块。

## 目录里有什么

```
01-方案与数据需求/     5 份文档（需求基线、构建方案、实现方案、缺口登记、遗漏归因）
02-数据构建/           5 版数据包 + 4 个构建脚本 —— 构建说明见该目录下的 README.md
```

## 数据包现在用哪一版

**同时在用两版，这是最容易判错的地方。**

| 版本 | 表 | 行数 | 大小 | 状态 | 依据 |
|---|---|---|---|---|---|
| `v0.3.0` | 44 | 1,992,532 | 466MB | **权威主库** | `09-工作台/core/paths.py` 的 `PRODUCT_DB` 默认值 |
| `v0.2.2` | 22 | 21,098 | 11MB | **同时在用，不是旧版** | `09-工作台/modules/inventory/data.py:26` `SOURCE_ROOT = DATA_ROOT.parent / "v0.2.2"` |
| `v0.2.1` | 19 | 8,479 | 8MB | 过期（仅构建链输入） | `build_..._v022.py:39` 的 `V021_ROOT` |
| `v0.2.0` | 19 | 8,461 | 8MB | 废弃 | 仅被后续构建脚本按路径引用，无运行时读取 |
| `v0.1.0` | — | — | — | 废弃（**无 sqlite**，17 个文件全是 JSON） | 全树零运行时引用 |

**为什么 v0.2.2 不能删**：v0.3.0 把 `quality_report.json` 换成了扁平检查表，
页面要的四个质量汇总块只剩 v0.2.2 里有。`data.py:69-79` 同时读两处：

```python
manifest = json.loads((DATA_ROOT / "dataset-manifest.json").read_text(...))   # v0.3.0
quality  = json.loads((DATA_ROOT / "quality_report.json").read_text(...))     # v0.3.0
src_q    = SOURCE_ROOT / "quality_report.json"                                # v0.2.2
src_m    = SOURCE_ROOT / "dataset-manifest.json"                              # v0.2.2
```

删掉 v0.2.2 会打掉库存页的质量区块。

## 工作台哪几个文件读它

```
09-工作台/modules/inventory/
├── data.py            只读打开 v0.3.0（paths.PRODUCT_DB）+ v0.2.2（来源事实包）
├── compute.py         53KB，全部算术在这里：覆盖天数 / 断货日 / 缺口量 / 补货建议 / 五类风险
├── forecast.py        挂 Agent 预测库 + chart_cache
├── agent_forecast.py  读需求预测 Agent 的落表
├── verdict.py         读盘点结论 Agent 的落表
├── module.py          三个页面 inv-detail / inv-risk / inv-scope，四条路由
└── derived/           Agent 产出与缓存，见下

09-工作台/web/modules/inventory.{js,css} + inventory/{page-detail,page-risk,page-scope,daychart,util}.js
```

**工作台永不写库**（契约 6.1，`core/db.py` 加 `PRAGMA query_only`）。写库全在 Agent 侧。

## 这个模块的 Agent

两个，都落在 `09-工作台/modules/inventory/derived/`：

| Agent | 落表 | 状态 |
|---|---|---|
| 需求预测 | `forecast_agent.sqlite` | **已出 90 天逐日**（`fact_child_forecast_agent_daily` 900 行 = 10 次 × 90 天）。登记表里状态是「未接通」，**已过期** |
| 盘点结论 | `verdict_agent.sqlite` | 已接通，3 run。22 个数字与确定性层交叉核对过 |

`derived/` 下另有：

```
chart_cache.sqlite                      36MB  工作台自建的图表读缓存（非 Agent），由同目录 build_cache.py 从 v0.3.0 生成
forecast_judgment_legacy_20260831.*           被 forecast_agent 取代前的旧判断表，全树零引用
_B0BVM5WCSQ_judgment.bak.json                 单对象手工备份，零引用
seed_verdict.py                               盘点结论的播种脚本
```

**两个 Agent 都没有页面上的触发入口**：`06-Pi-Agent交互Demo/src/inventory-verdict.ts` 没接进
`server.ts`，只能手工 `npm run demo:inventory-verdict`。需求预测有路由
（`POST /api/inventory/run-demand-forecast`）。

## 文档在哪（`01-方案与数据需求/`）

| 文件 | 回答什么问题 | 状态 |
|---|---|---|
| `01-产品销售库存模块-Demo数据需求.md` | 三页反推出来的完整数据需求（五层数据、规模、场景覆盖） | 基线有效。**文内建议的「8 父 / 72 子」已被推翻**，现为 5 父 / 342 子 |
| `03-产品销售库存Demo数据构建方案.md` | 客户数据怎么继承 / 派生 / 补造，为什么不能把 Excel 原样接进页面 | 权威。342 脊椎的出处 |
| `04-产品销售库存Demo实现方案.md` | 三页怎么实现、计算放哪 | **部分过期**：底座写 v0.2.2，现用 v0.3.0 |
| `05-数据缺口登记.md` | 缺什么、缺口挡住哪个结论 | 持续追加的台账。**对应 v0.2.2 实测**，未按 v0.3.0 重测 |
| `06-数据构建遗漏归因与后续门禁.md` | 上次为什么「检查全绿但页面跑不了」 | 权威。它那套「假绿」归因是 `00-通用方法与规范/08-Agent需求与数据契约要则.md` §0 的先声 |

跨模块的上位规范在 `/Users/linsen/BAM/00-通用方法与规范/`，Agent 契约在
`/Users/linsen/BAM/01-方案与数据需求/`（`07` 预测 Agent 职责切法、`10`+`11` 盘点结论、
`12`+`13` 需求预测职责修订与分段运行）。

## 已知问题

1. **两条不同的 Agent 链共用同一个页面**，文件名里没有区分词：
   `01-方案与数据需求/` 下 `10`+`11-库存模块交底给结论Agent` 是**盘点结论** Agent，
   `07`+`11-预测判断Agent落表与调用接口`+`12`+`13` 是**需求预测** Agent。只有配套必读列表能分开。
2. **`00-通用方法与规范/07-需求判断上屏交底.md` 已过期**：它点名的
   `forecast_judgment.py` 和 `probe_forecast_judgment.py` 都不存在了（现为 `agent_forecast.py` /
   `probe_demand_forecast.py`），而它把这些写成「已经做好的，不要重做」——照它去找会扑空。
3. **`01-方案与数据需求/11-预测判断Agent落表与调用接口.md` 的表名与落盘 schema 脱节**：
   `fact_child_forecast_judgment_run` 库里已不存在（现为 `fact_child_forecast_agent_run`）。
   只有 `fact_child_forecast_judgment_factor` 名字还活着。
4. **需求预测的 20 次运行里 10 次失败**，全部是「模型服务余额不足（402）」。
5. **`05-数据缺口登记.md` 的所有数字来自 v0.2.2 实测**，v0.3.0 换了底座后没重测过。
6. **`13-需求预测Agent分段运行需求.md` 的 R2「单步 ≤25 秒」有一步稳定超标**：
   第 5 步 `submit_demand_assessment` 实测 28.6 秒，其余 11 步全部合规。

## 踩过的坑

**不要 `cd` 进 `09-工作台/modules/` 跑 python。** 兄弟目录 `modules/keyword/` 会遮蔽 Python
标准库的 `keyword`，任何脚本都会炸在 `from keyword import iskeyword`，报错信息跟你的代码
毫无关系。从 `09-工作台/` 跑。

**取 Agent 最新一次运行不能 `ORDER BY created_at DESC`。** 库里三种时间戳格式并存
（`+08:00` / `.Z` / 无偏移），字符串排序会把带 `Z` 的判成前一天，**更新的记录被更旧的盖掉
且界面上完全看不出异常**。正确写法见 `09-工作台/modules/agentcfg/module.py` 的 `_stamp()`。
