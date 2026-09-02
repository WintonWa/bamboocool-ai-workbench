# 广告分析模块 Demo 实现方案

版本：v1.0（2026-08-29）
数据底座：`/Users/linsen/BAM/04-广告分析模块/02-数据构建/v0.1.0/`（release，独立验收 63/63 PASS）
需求原文：主方案 4.5 / 5.4 / 7.5（1978–2543 行）/ 8.5（4468–4860 行）
本轮范围：只做广告数据本身。库存、关键词、竞品不建模块，只渲染数据包里已落盘的证据卡。

---

## 1. 数据充分性核定

以下行数由逐键点数 `acceptance_export.json` 得到，不采用构建器自报。

| 逻辑表 | 行数 | 备注 |
| --- | ---: | --- |
| dim_product_parent | 5 | B0DDNK229S 103 / B0GQXK2Q58 92 / B0CJV3G988 134 / B0D9FLMR6N 96 / B0CCLWDJNV 96 |
| dim_product_child | 521 | |
| dim_ad_object | 733 | AD_GROUP 54（SP40/SB5/SD9）+ TARGET 679 |
| bridge_ad_object_product | 554 | 5 角色：promoted 331 / positive_spend 220 / purchased 1 / target 1 / matched 1 |
| fact_ad_performance | 739 | 733 整月 + 3 前窗 + 3 后窗 |
| fact_product_ad_spend | 526 | 431 正 / 89 零 / 1 blocked / 5 父体汇总，period=2026-06 |
| fact_ad_label_version | 897 | AD_PURPOSE 733 / PRODUCT_RELATION 54 / TARGET_OBJECT 54 / AD_ATTRIBUTE 54 / OPERATOR_CUSTOM 2 |
| dim_anomaly_rule | 2 | 均为 pending_customer_confirmation |
| fact_page1_result | 59 | 6 个 query 切片 |
| fact_page1_anomaly | 7 | 命中 4 个 result |
| fact_decision_context | 2 | 均属 B088WF1PRW |
| fact_decision_evidence | 9 | |
| fact_required_ad_task | 4 | |
| bridge_task_ad_object | 4 | |
| fact_ad_diagnosis | 4 | |
| fact_ad_recommendation | 4 | exact_value 全空 |
| fact_review_feedback | 2 | D+3 / D+7 各一 |
| scenario_registry | 13 | 全 PASS |
| source_lineage | 4089 | 非 scenario 3327 条 100% 连有效 source_file_id |

### 1.1 页面一：数据充分

- 733 个对象全部具备真实 7 月经营指标（impressions/clicks/spend/orders/ad_sales/ctr/cpc/cvr/acos/roas），验收独立回算差异 0/739。
- 五类标签齐备，且带 label_source、confirmation_status、effective_from/to、inherited_from_object_id，支持方案 3.4 要求的「不同来源不覆盖」。
- 标签版本变化有真实样本：`grp_b29d2a07cfeb3144` 的 OPERATOR_CUSTOM 有两版，截至 07-15 与自 07-16 起生效，不重叠。
- 共享广告对象有真实样本：同一广告组连 5 个 promoted 子体，全部保持 attribution_scope=shared。
- 218 条事实实际不足完整请求窗口，已标 partial_source_coverage，且 comparison_eligible=0、rank_by_acos=null。
- 2 条异常规则齐（绝对阈值 + 自身历史变化率），关闭规则的场景也已注册。

### 1.2 页面二：只有单点

全链只存在于 B088WF1PRW：2 个决策版本（07-10 历史场景 → 08-03 当前）、9 条证据、4 项应有任务、4 条结构对照、4 条诊断、4 条建议、accept/modify/reject/defer 四类决定、D+3 与 D+7 反馈各一条。其余 520 个子体只有广告花费事实与推广关系。

五类上游证据的底料均为真实客户文件，不需要另建模块：

| 证据 | 来源 | 关键值 |
| --- | --- | --- |
| PRODUCT_GOAL | 关键词3.xlsx + 产品跟进表-曾向锋.xlsx + 广告事实 | 稳定规模并保护核心流量位置（conditional，待运营确认） |
| INVENTORY | 产品跟进表-曾向锋.xlsx 领星补货建议 row=2 | 可售 3516 / 30 天日均 477.8 / 立即可售覆盖 7.36 天 / 含在途 58 天 / 断货日 2026-09-03 |
| KEYWORD | 关键词3.xlsx 全量关键词（含分类） | mens underwear 月搜 908485、mens boxer briefs 304295、athletic underwear men 13190 |
| COMPETITOR | 9.竞品.xlsx Competitor-US-Last-30-days row=2 | Hanes B086L4BXZC，BSR 1，月销 175973，月营收 $3797497，$21.58 |
| HISTORY_ACTION | 搜索词报告真实日行 + 场景动作 | baseline ACoS 0.575 → D+3 0.302 → D+7 0.357 |

### 1.3 判定

可以做出一个可发版的小型 Demo，形态锁为**页面一全量可摆弄 + 页面二单点走通全链**。不做「521 个子体都能出诊断」的承诺。

---

## 2. 实现形态与技术栈

沿用产品库存模块 Demo 的既有约定（`/Users/linsen/BAM/03-前端Demo/`）：

- Python 标准库 `http.server` + `sqlite3` 只读，零第三方依赖；host 内存紧，不整包加载 JSON。
- `HOST=127.0.0.1`，`PORT=18812`（18810 库存原版、18811 UICraft 测试均不动）。仅绑回环、无鉴权，外部访问走 SSH 隧道。
- `start.py` 双 fork + setsid 防进程组回收，`--stop` 按 server.py 路径匹配 pkill。
- 视觉沿用中性白主题与 ui-craft-dense-dashboard 规则（hero 独大 + 2–4 support、4/8 间距网格、语义色只上文字与描边、mono 数字 tabular-nums、每数据区三态）。
- 目录：`/Users/linsen/BAM/05-广告前端Demo/`

```
05-广告前端Demo/
├── server.py            路由 + 按规则指纹缓存
├── start.py             双 fork + setsid，--stop
├── lib/
│   ├── data.py          sqlite3 只读 + lru_cache
│   ├── rules.py         RuleSet（异常规则、比较窗口、粒度锁）
│   └── compute.py       运行时聚合与判断链
├── web/                 index.html + app.css + app.js
└── tests/               API 契约 / 页面验收 / 无浏览器渲染
```

---

## 3. 六条实现纪律

1. **不拿 59 行预计算当筛选后端。** `fact_page1_result` 只覆盖 6 个固定 query，无法支撑任意标签组合。改为运行时从 `fact_ad_performance`(739) + `fact_ad_label_version`(897) + `bridge_ad_object_product`(554) + `dim_ad_object`(733) 现算聚合，本地毫秒级。59 行预计算改作**回归基线**：同条件算出的 impressions/clicks/spend/orders/ad_sales/ctr/cpc/cvr/acos/roas/previous_acos/acos_change_rate/rank_by_acos 必须与之逐字段相等，作为免费的正确性门禁写进 tests。

2. **粒度锁。** 一次查询只能选 AD_GROUP 或 TARGET，不混入同一汇总或比较集合。Campaign 仅做范围限定与归属展示。

3. **归因不混加。** SP 7 天与 SB/SD 14 天分开汇总、分开排名。跨类型只做并列呈现。

4. **规则缺失即不标异常。** 参数面板可关规则；关掉后只出数值、变化和排序，异常列表为空（对应方案 3.7 与 `scn_493550fe863b58f8`）。

5. **页面一零策略字段。** 不读产品目标、库存、关键词、竞品，不产出预算/竞价/否词/启停/新建建议。异常只说对象、指标、时间、比较基准、偏离程度。

6. **规则未确认不给精确值。** 页面二建议的 exact_value 保持为空，只出方向、对象、前置条件、风险与 D+3/D+7 观察要求。

---

## 4. 页面一：广告分类与数据查看（8 板块 → 数据映射）

| # | 板块 | 数据来源 | 本轮做到 |
| ---: | --- | --- | --- |
| 1 | 当前范围、粒度与数据状态 | dataset_manifest + dim_ad_object + fact_ad_performance | 5 父/521 子/733 对象/事实窗/归因口径/218 条部分覆盖/**可比较对象 3 of 54**/SB 5 个 pending_mapping |
| 2 | 广告对象标签体系 | fact_ad_label_version 897 | 五类分区，标注来源与确认状态；Target 仅 AD_PURPOSE 如实说明 |
| 3 | 标签组合与对象筛选 | 运行时 | 多标签 AND 组合 + 粒度切换 + 时间范围，回显对象数量 |
| 4 | 筛选结果数据概览 | 运行时聚合 | 按归因周期分块汇总，共享/缺失/不可比单列标注 |
| 5 | 数值异常对象 | dim_anomaly_rule 2 + 运行时 | 绝对阈值全量可跑；变化率规则仅 3 个对象有前窗，其余显示「无可比前窗」 |
| 6 | 横向对比 | comparison_eligible 门禁 | 同粒度同归因同窗口才进排名，不可比对象排除 |
| 7 | 广告对象数据清单 | 733 行 | 对象 + Campaign/广告组归属 + 标签 + 指标 + 变化 + 异常 + 共享态 |
| 8 | 对象详情与标签历史 | dim_ad_object + bridge + label_version | 层级位置、关联子 ASIN 与共享范围、标签版本时间轴 |

环比样本只有 3 个这件事不藏进脚注：板块 1 直接给出「具备可比较数据的对象 3 / 54」，这本就是方案 3.3 要求页面说明的内容。

---

## 5. 页面二：单一子 ASIN 广告决策（9 板块 → 数据映射）

| # | 板块 | 数据来源 |
| ---: | --- | --- |
| 1 | 子 ASIN 决策上下文 | fact_decision_context 2 版本 + goal_status + previous_decision_id |
| 2 | 产品目标与经营约束 | ev_goal_current + ev_inventory_current（立即可售与含在途分开显示） |
| 3 | 关键词与竞品证据 | ev_keyword_current + ev_competitor_current |
| 4 | 应有广告任务 | fact_required_ad_task 4 条（含 PREREQUISITE 与 inventory_constrained=1） |
| 5 | 现有广告结构与目的 | dim_ad_object + bridge + AD_PURPOSE 标签 |
| 6 | 目标—结构—表现对照 | bridge_task_ad_object 的 coverage_status（covered/missing/duplicate/mixed/object_mismatch/data_insufficient） |
| 7 | 广告诊断与优先级 | fact_ad_diagnosis 4 条（basis_type + causal_claim=0 + uncertainty + check_direction） |
| 8 | 广告调整方案 | fact_ad_recommendation 4 条（direction + preconditions + risks + review_windows，exact_value 空） |
| 9 | 运营决定与执行交接 | fact_ad_decision_event 四类 + fact_review_feedback D+3/D+7 |

**子体选择器**：521 个都可点开。B088WF1PRW 走完整九板块；其余 520 个显示广告花费事实与推广关系，并明确「本子体无决策版本」。这不是缺陷，是方案 4.3 要求的第三态（正式判断 / 条件性判断 / 暂时无法判断）的真实样本。

---

## 6. 分步计划

**A1 服务端骨架**
sqlite3 只读接入 v0.1.0；三接口 `/api/meta`（版本、事实窗、归因、范围、数据状态）、`/api/objects?grain&labels&window&ruleparams`、`/api/child/<asin>`；733 对象列表能出、B088WF1PRW 能打开。

**A2 页面一八板块**
运行时聚合层 + 标签筛选 + 归因分块 + 横向对比门禁 + 两条规则；跑 59 行预计算基线比对。

**A3 页面二九板块**
证据卡渲染 + 任务→结构对照→诊断→建议链路下钻 + 四类决定 + D+3/D+7 反馈；520 个无决策链子体的第三态。

**A4 参数面板与场景验收**
异常阈值可改立刻重算并显示命中数；13 个注册场景逐条按 `scenario_registry.steps` 走通；三套测试（API 契约 / 页面验收 / 无浏览器 node 渲染）。

---

## 7. 数据缺口登记

| 编号 | 缺口 | 影响 | 处理 |
| --- | --- | --- | --- |
| A1 | 环比样本仅 3 个广告组 | 变化率规则与自身历史对比覆盖面窄 | 板块 1 显式声明可比对象数；其余显示「无可比前窗」 |
| A2 | 页面二决策链仅 B088WF1PRW | 只能单点演示 | 子体选择器保留全部 521，其余走第三态 |
| A3 | SB 5 个广告组无广告 ASIN 映射 | SB 无法归到子 ASIN | 保持 pending_mapping，不强归 |
| A4 | 679 个 Target 只有 AD_PURPOSE 标签 | Target 粒度多维筛选受限 | 投放对象与属性改用 dim_ad_object 的 target_text/match_type/ad_type 直接筛 |
| A5 | B0D9FLMR6N、B0CCLWDJNV 有正花费但零推广关系 | 两父体在页面一无广告对象 | 只在花费视图出现，不伪造广告组关系 |
| A6 | 花费事实是 2026-06，表现事实是 2026-07 | 两者不同期 | 不相除、不合成 TACOS 类指标 |
| A7 | 源报表无稳定 Amazon ID | 键为 source_name_key | 界面不冒充平台 ID |
| A8 | 无含自然单销售额 | TACOS 算不出 | 本轮不做 TACOS |
| A9 | 2 条异常阈值未经客户确认 | 阈值为演示观察线 | 参数面板可改，规则版本 demo-v0.1 |

---

## 8. 验收条件

1. 733 个对象在页面一可筛、可比、可展开，指标与源表回算一致。
2. 同条件下算出的结果与 59 行预计算逐字段相等。
3. 关闭规则后异常列表为空，数值与排序仍在。
4. 页面一不出现任何策略字段。
5. B088WF1PRW 九板块全出，链路可从建议回溯到证据与源文件。
6. 建议 exact_value 全空，D+3/D+7 观察要求在位。
7. 13 个注册场景逐条走通。
8. 三套测试零失败。
