# 广告分析模块独立验收契约

版本：v1.0.0  
冻结日期：2026-08-29  
验收角色：能力验收 Agent  
当前状态：契约已冻结，等待数据构建 Agent 提交纵向切片

## 1. 验收立场

本目录只保存独立验收契约、检查器和验收结果，不保存或修改构建数据。

验收条件来自正式产品方案，不根据当前实现反向放宽。判断含义为：

- `PASS`：提交证据存在，且断言成立；
- `FAIL`：提交了可检查的证据，但内容与冻结契约矛盾；
- `BLOCKED`：必需产物、场景或来源证据尚未提交，当前无法判断；
- 缺少证据不是 `PASS`，构造数据也不会因为自洽自动被视为客户事实。

正式依据：

- `/Users/linsen/BAM/bamboocool 产品方案/Bamboocool-AI运营工作台方案.md`
- `/Users/linsen/BAM/bamboocool 产品方案/Bamboocool-广告分析模块两页架构方案.md`
- `/Users/linsen/BAM/bamboocool 产品方案/Bamboocool-广告分析模块必备逻辑与能力清单.md`
- `/Users/linsen/BAM/00-通用方法与规范/01-Demo数据构建方案制定方法.md`

机器契约见 [acceptance_contract.json](/Users/linsen/BAM/04-广告分析模块/03-验收/acceptance_contract.json)。

## 2. 冻结范围

父体范围严格为：

- `B0DDNK229S`：103 子；
- `B0GQXK2Q58`：92 子；
- `B0CJV3G988`：134 子；
- `B0D9FLMR6N`：96 子；
- `B0CCLWDJNV`：96 子。

release 数据包合计必须为 5 父、521 子。Amazon 后台广告事实窗为 `2026-07-01` 至 `2026-07-31`。

广告组采用 `(ad_type, campaign_name, ad_group_name)` 名称键，共 54 个：SP 40、SB 5、SD 9。源报表没有稳定 Campaign ID、广告组 ID 或 Target ID，因此构造出的确定性键必须标为 `source_name_key`，不能冒充 Amazon 平台 ID。

范围内明确推广 ASIN 为 115 个，属于 `B0DDNK229S`、`B0GQXK2Q58`、`B0CJV3G988` 三个父体。其他父体存在正广告花费不等于存在可证明的广告组关系。

## 3. 两页不可混淆的粒度

### 页面一：广告分类与数据查看

最小结果粒度是：

```text
广告组或 Target
× 当时有效的标签版本
× 统计时间范围
× 归因基础
```

同一个查询只能选择广告组或 Target 一种粒度。Campaign 只能限定范围，不能与广告组、Target 混进同一比较集合。

页面一允许输出标签、区间数据、自身历史变化、横向比较、数值异常和数据限制；不得输出产品目标判断、结构诊断、策略优先级、预算/竞价/否词/暂停/新建广告建议。

### 页面二：单一子 ASIN 广告决策

最小结果粒度是：

```text
子 ASIN × 产品目标版本 × 决策时刻
```

父体、Campaign 或广告组都不能代替子 ASIN 成为策略判断对象。每个决策版本必须使用当时有效的产品目标，并组装产品目标、库存、关键词、竞品和历史动作五类证据。

## 4. 来源角色边界

以下角色必须分别保存，不得用字符串相同或同表出现来互相升级：

| 角色 | 能证明什么 | 不能证明什么 |
|---|---|---|
| `promoted_asin` | 报表明确把该 ASIN 列为广告 ASIN/推广商品 | 不能由正花费、购买或投放 ASIN 猜测 |
| `positive_spend_asin` | 子体粒度存在正广告花费 | 没有广告 ASIN 关系时，不能证明具体 Campaign/广告组 |
| `purchased_asin` | 广告归因后实际购买了该商品 | 不代表它是本次推广商品 |
| `target_asin` | 该 ASIN 被用作商品投放目标 | 常为竞品，不代表客户在推广它 |
| `matched_asin` | 该 ASIN 出现在匹配目标或搜索上下文 | 不代表推广关系或购买结果 |

任何一个广告对象服务多个子 ASIN 时，关系必须保留为 `shared` 或 `unattributed`。没有客户支持的拆分规则时，不允许按均分或销售占比强制归给单一子 ASIN。

来源状态统一使用：

```text
direct / derived / supplemented / scenario_added / blocked
```

Amazon direct 事实只能在 2026 年 7 月窗口内。窗口外趋势可以补充构造，但必须使用 `supplemented` 或 `scenario_added`，并保留真实锚和构造规则。

## 5. AD-01～AD-11 验收主线

| 能力 | 验收结果主线 | 所属页面 |
|---|---|---|
| AD-01 | SP/SB/SD 对象、层级、时间、归因和来源统一，但不混加 | 共用 |
| AD-02 | 广告对象到子 ASIN 的服务关系、共享范围和归因边界可追溯 | 共用 |
| AD-03 | 标签有类型、来源、确认状态、生效时间和历史版本 | 页面一 |
| AD-04 | 区间经营事实可复算，比较条件和不可比限制明确 | 共用 |
| AD-05 | 单一子 ASIN 决策证据包同时包含五类上游证据 | 页面二 |
| AD-06 | 从目标和证据推出应有任务、优先级、约束和停止条件 | 页面二 |
| AD-07 | 应有任务与真实广告对象形成覆盖/缺失/重复/混合等对照 | 页面二 |
| AD-08 | 诊断含证据、可信度、不确定项和检查方向，不伪造因果 | 页面二 |
| AD-09 | 建议有对象、依据、边界、风险和 D+3/D+7 观察要求 | 页面二 |
| AD-10 | 标签筛选、范围重算、同口径比较和有规则依据的数值异常 | 页面一 |
| AD-11 | 原建议、运营决定、执行交接和复盘回流形成版本链 | 页面二 |

每项详细断言和 Definition of Done 以 `acceptance_contract.json` 为准。

## 6. 纵向切片门禁

批量生成前必须依次通过：

### VS-00：契约与范围

- manifest 声明 5 父、521 子、54 名称键广告组和 2026 年 7 月 Amazon 事实窗；
- 提交至少一个明确推广关系和一个共享广告对象；
- 角色、来源、归因与生效时间完整；
- AD-01、AD-02 为 `PASS`。

### VS-01：页面一纵向切片

- 至少 3 个同粒度、同时间、同归因可比较广告对象；
- 有标签版本变化和继承来源；
- 能按标签筛选、重新计算范围、横向比较；
- 有规则时产生数值异常，无规则时不产生异常；
- 页面一结果没有策略字段；
- AD-03、AD-04、AD-10 为 `PASS`。

### VS-02：页面二纵向切片

- 优先使用 `B088WF1PRW`；若更换明星子体，必须仍是具有 direct 推广关系的范围内子 ASIN，并在场景注册表说明原因；
- 五类证据进入同一个子 ASIN 决策版本；
- 应有任务 → 结构对照 → 诊断 → 建议链路全部可回溯；
- 至少包含库存不可承接和规则未确认不得给精确值两个边界场景；
- AD-05～AD-09 为 `PASS`。

### VS-03：运营决定与反馈

- accept、modify、reject、defer 四种决定可重复触发；
- modify 保存 AI 原建议与修改计划；
- reject/defer 不进入已执行状态；
- 接受或修改后的建议可交接；
- 至少一条 D+3 和 D+7 反馈可关联回下一决策版本；
- AD-11 为 `PASS`。

任一门禁为 `FAIL` 或 `BLOCKED`，不得进入批量生成或前端交付。

## 7. 构建 Agent 提交格式

验收器检查逻辑产物，不强制底层只能使用 JSON 或 SQLite。支持：

1. 目录内逐表 `<logical_artifact>.json`；
2. `acceptance_export.json`，结构为 `{"tables": {"table_name": [...]}}`；
3. SQLite/DB 中使用契约规定的逻辑表名。

必需逻辑产物名称由 `acceptance_contract.json.logical_artifacts` 冻结。JSON 表可以直接是记录数组，也可以包装为 `records`、`rows` 或 `data`。

manifest 至少声明：

```json
{
  "dataset_stage": "vertical_slice",
  "selected_parent_asins": ["B0DDNK229S", "B0GQXK2Q58", "B0CJV3G988", "B0D9FLMR6N", "B0CCLWDJNV"],
  "expected_child_count": 521,
  "expected_ad_group_name_key_count": 54,
  "amazon_fact_window_start": "2026-07-01",
  "amazon_fact_window_end": "2026-07-31",
  "timezone": "source-local",
  "currency": "USD",
  "seed": 20260829
}
```

`dataset_stage=vertical_slice` 时允许只提交明星对象的记录，但完整范围目标仍须冻结在 manifest 中。`dataset_stage=release` 时自动启用 521 子、54 广告组和类型分布的精确数量检查。

## 8. 运行方式

```bash
python3 "/Users/linsen/BAM/04-广告分析模块/03-验收/run_acceptance.py" \
  --dataset "/absolute/path/to/submitted-slice"
```

强制以纵向切片或 release 模式运行：

```bash
python3 run_acceptance.py --dataset "/absolute/path" --mode vertical_slice
python3 run_acceptance.py --dataset "/absolute/path" --mode release
```

检查结果写入本目录的 `latest_result.json`。进程退出码：

- `0`：整体 `PASS`；
- `1`：至少一个 `FAIL`；
- `2`：无 `FAIL`，但存在 `BLOCKED`。

切片提交后，能力验收 Agent 还会按 `scenario_registry.steps` 做人工演示核验。自动检查通过不能替代页面任务验收。

## 9. 发布原则

只有以下条件同时成立才能交给前端：

- AD-01～AD-11 全部 `PASS`；
- VS-00～VS-03 全部 `PASS`；
- release 模式通过；
- Critical 缺口为 0；
- 客户事实、派生、补造和场景数据清楚区分；
- 关键结果能够从上游明细按 Demo 规则复算；
- 固定规则和固定种子下明星场景可重复；
- 不需要前端硬编码关键诊断或建议。

