# 广告 Agent 重建：两侧分工与接缝契约 v1.1

2026-08-31 · 方案 A（一个广告 Agent、两条工作流）

这份文档只解决一件事：**两边各自做完之后能对接上。**

2026-08-31 联调后把接缝定为一读一写：Runner 先从工作台接口只读三项
新鲜度元数据，完成判断后只写 sidecar 两张表。Agent 侧不碰前端和读取层，
前端侧不碰 Runner 和提示词。

```
工作台 /api/ads/context ──只读 context_hash/context_id/data_as_of──→ Runner
Runner 读原始事实 → Pi 逐步判断 → ads_agent_state.sqlite → 工作台读取 → 上屏
                                  fact_ads_agent_run
                                  fact_ads_agent_output
```

---

## 1. 接缝的确切结构

sidecar 路径不变：`09-工作台/modules/ads/derived/ads_agent_state.sqlite`
源数据包保持只读，Agent 只写这一个文件。

### 1.1 `fact_ads_agent_run` 一次运行一行

现有 18 列全部保留，只加 3 列。**加列不改列，这样我这侧的读取不会一次性全断。**

| 列 | 类型 | 现有 | 说明 |
|---|---|---|---|
| `run_id` | TEXT PK | ✓ | `<主体>-<基准日>-ads-agent-<时间戳>-<短哈希>` |
| `run_type` | TEXT | **新增** | `purpose_label`（A1）/ `child_decision`（B0b–B4）|
| `subject_kind` | TEXT | **新增** | `ad_object` / `child_asin` |
| `subject_id` | TEXT | **新增** | A1 填 `ad_object_id`；决策链填子 ASIN |
| `child_asin` | TEXT | ✓ | **保留**：决策链填子 ASIN，A1 填该对象推的主子 ASIN 或留空 |
| `data_as_of` | TEXT | ✓ | 数据截止，现在是 `2026-08-03` |
| `context_hash` | TEXT | ✓ | **工作台计算的页面新鲜度指纹**；Runner 从 `/api/ads/context` 原样存，不自行计算 |
| `context_id` | TEXT | ✓ | 同一接口原样存 |
| `trigger` | TEXT | ✓ | `manual` / `weekly` / `priority` |
| `model_version` | TEXT | ✓ | 现在是 `deepseek/deepseek-v4-flash` |
| `method_version` `schema_version` `dataset_version` `rule_version` | TEXT | ✓ | 四个版本号，追溯用 |
| `status` | TEXT | ✓ | `running` / `completed` / `failed`。**只有 completed 会被前端采纳** |
| `mode` | TEXT | ✓ | 中文档位：正式判断 / 条件性判断 / 暂时无法判断 |
| `condition` | TEXT | ✓ | 中文状态词表内取值 |
| `evidence_index` | TEXT | ✓ | JSON 数组，存本次模型实际看过的完整依据目录，结构见 §1.5 |
| `diagnosis_coverage` | TEXT | ✓ | **建议移走**：改成 `output_point='B3b'` 的行，这里留空 |
| `created_at` `completed_at` | TEXT | ✓ | |

### 1.2 `fact_ads_agent_output` 每条结论一行

取代现有的 `fact_ads_agent_stage` + `fact_ads_agent_item`。

| 列 | 类型 | 说明 |
|---|---|---|
| `run_id` | TEXT | 关联运行 |
| `output_point` | TEXT | 见 §1.3 词表，**九个值之一** |
| `point_ord` | INTEGER | 这个输出点在本次运行里的执行序号，从 1 起 |
| `item_ord` | INTEGER | 同一输出点内的排序，从 1 起 |
| `item_id` | TEXT | 这条结论的 id（`task_id` / `diagnosis_id` 等），内部用不上屏 |
| `payload` | TEXT | JSON，字段照 §2 |

主键 `(run_id, output_point, item_ord)`。

**不要再写 `label`。** 段落标题（「应有广告任务」这类）由前端按 `output_point` 给，
写在两边会不一致。

### 1.3 `output_point` 词表（九个，写死）

| 值 | 中文（前端给，Agent 不用写）| 作用域 |
|---|---|---|
| `A1` | 广告目的标签建议 | 广告对象 |
| `B0b` | 目标约束分档 | 子 ASIN |
| `B0cd` | 词与竞品判断（**合并后的一步**）| 子 ASIN |
| `B0e` | 结构问题识别 | 子 ASIN |
| `B1` | 应有广告任务 | 子 ASIN |
| `B2` | 任务与结构对照 | 子 ASIN |
| `B3` | 广告诊断与优先级 | 子 ASIN |
| `B3b` | 诊断覆盖说明（十类逐类）| 子 ASIN |
| `B4` | 广告调整方案 | 子 ASIN |

`purpose_label` 类型的运行只出 `A1`。
`child_decision` 类型的运行必须八个点齐全（B0b → B4），缺一个前端判为不完整。

### 1.4 payload 里绝对不要写的两样

**`*_label` 中文译名不要写。** 现在实测 Agent 同时写了 `task_type` 和
`task_label`，等于翻译发生在两处——Agent 给一个词表外的码值时会自带一个它
自己编的中文摆到屏上，我这侧的兜底不会被调用。

**按要则「翻译只发生在一处」：Agent 只出码值，中文由前端翻。**
例外是契约点名的自由文本（`rationale` / `what_happened` / `uncertainty` /
`missing_input` / `check_direction` / `evaluation_direction` / `stop_condition`
/ `note` / `target_fit` / `detail` / `basis` 这些），它们本来就是中文句子。

**内部枚举也不要自己译。** 你新增任何码值，同步告我加映射；界面上出现
「未归类任务」就是提示有映射没补上。

### 1.5 `context_hash` 与依据目录（方案 1，已定）

`context_hash` 的语义是**页面上下文新鲜度指纹**，不是模型输入全文指纹。
唯一计算方是工作台。Runner 每次运行先 GET：

```
/api/ads/context?child_asin=<子ASIN>
```

只取并原样保存 `context_hash`、`context_id`、`data_as_of`；接口不可达、字段缺失、
主体不一致时直接失败，不用本地 hash 兜底。接口返回的其他板块数据不进入模型。

工作台 hash 只对判断对象、决策版本、运营目标、规则参数、数据包版本与有效上游
run_id 敏感；对 A1/B0b–B4、旧 `ext_*` 结论和中文展示字段不敏感。hash 不符时
结果一律不可用。联调期只能显式设置 `WORKBENCH_ADS_SEAM=1` 旁路，页面必须标红。

模型实际看过什么，由 Runner 写入 `evidence_index`。它不是字符串 id 数组，而是
完整对象数组；每一项字段固定为：

| 字段 | 说明 |
|---|---|
| `evidence_id` | 稳定、无中文、与 run 无关的原始事实 id |
| `evidence_type` | 九值词表，见下表 |
| `subject_kind` / `subject_id` | 事实所属对象与 id |
| `observed_at` / `valid_as_of` | 观察时间与有效截止 |
| `value_origin` | `direct` / `derived` / `constructed` |
| `source_ref` | 源表、上游 run 或确定性算子 |
| `payload` | 模型实际看到的原始事实；不得含禁读结论 |

九类 `evidence_type` 写死，中文只由前端映射：

| 码值 | 前端中文 |
|---|---|
| `PRODUCT_GOAL` | 产品目标 |
| `INVENTORY_CONTEXT` | 库存承接 |
| `SALES_HISTORY` | 历史销量 |
| `BUSINESS_EVENT` | 业务事件 |
| `AD_PERFORMANCE` | 广告表现 |
| `CAMPAIGN_CONTROL` | Campaign 控制 |
| `AD_STRUCTURE` | 广告结构 |
| `KEYWORD_POSITION` | 关键词位置 |
| `COMPETITOR_MARKET` | 竞品市场 |

`evidence_id` 使用点号分段，按来源主键和观察时点命名，例如：

```
ads.operator_goal.<goal_version>
product.inventory_snapshot.<child_asin>.<as_of>
product.sales_history.<child_asin>.<start>.<end>
product.promotion_plan.<child_asin>.<start>.<end>
ads.performance.<ad_object_id>.<window_end>.<attribution_days>d
ads.campaign_budget.<campaign_id>.<window_end>
ads.invalid_traffic.<campaign_id>.<window_end>
ads.structure.<child_asin>.<ad_object_id>
keyword.position.<child_asin>.<kw_id>.<observed_at>
competitor.market.<child_asin>.<competitor_asin>.<observed_at>
inventory.agent.<run_id>.<block>
```

输出里的 `evidence_ref` / `evidence_ids` 只能引用这份目录。前端按 id 解析 chip，
按 `evidence_type` 翻中文，按目录里的 payload 展示依据详情。

---

## 2. 每个输出点的字段

字段表在 `01-方案与数据需求/04-广告模块Agent输出点清单.md` 第 1–11 节，
逐点列了字段名、类型、取值枚举。**这份不重复抄，抄两份必然对不上。**

只强调三处与那份文档的差异（这次重建改的）：

1. **B0 产品目标判断作废**——产品目标改成运营设定的输入，Agent 不判它。
2. **B0c 与 B0d 合并成 B0cd**——同一类外部事实、同一层分类判断，一步出完。
   payload 里两组字段都给：词的 `match_level`/`demand_side`/`product_side`/`basis`，
   竞品的 `pressure_type`/`detail`/`is_verified`。
3. **B3b 从 run 行搬到 output 行**——十类逐类，`hit` 与 `why_not`。

---

## 3. 他那边做什么

| # | 事 | 判据 |
|---|---|---|
| 1 | 建两张新表，写 Runner 落库 | `run_type` / `output_point` 两个词表严格按 §1.2/§1.3 |
| 2 | 重建输入桥：A1 / B0b / B0cd / B0e 各读自己那部分原始事实 | 禁读清单照输出点清单第 12 节，**尤其九个库存投影字段与生命周期** |
| 3 | 七步串行：B0b → B0cd → B0e → B1 → B2 → B3(+B3b) → B4 | 后一步只读前一步已落库的结果，不预先并行 |
| 4 | 删掉旧逻辑 | 读 `ext_*` 结论表 / 把答案放进下一步契约 / 提示词要求逐字复制 / 「等于预烤结果」当门禁 / 按 ASIN 手工覆盖 |
| 5 | 校验器换成约束型七条 | 见 §5 |
| 6 | 跑一遍：5 个子 ASIN 全链 + A1 按 §4 的范围 | `status='completed'` 且八个点齐 |
| 7 | 每次改了 payload 字段，告我一声 | 否则我这侧显示不出来 |

**A1 不改主数据包**：`rationale` 写进 `output_point='A1'` 的 payload；
`fact_ad_label_version` 保持只读，不增加依据列。这样写入接缝仍然只有两张 sidecar 表。

## 4. 我这边做什么

| # | 事 | 完成判据 |
|---|---|---|
| 1 | 读取层从 stage+item 改成 output，按 `output_point` 分组 | 九个点都能读出来 |
| 2 | 段落标题、枚举中文、缺映射兜底全在我这侧 | 界面零英文码值 |
| 3 | 页面一读 A1 最新结果，接到侧栏标签体系与详情抽屉 | 每条建议点开能看到依据 |
| 4 | 页面二按 `point_ord` 逐步显示，四态：没结果 / 失败 / 过期 / 正常 | 「执行中」不做，见 §6 |
| 5 | 「开始分析」改名「查看分析结果」，旁边显示上次运行时间与模型 | 没跑过就置灰写「尚未运行」 |
| 6 | 三层字段对账脚本跟着改表名 | `09-工作台/tests/check_agent_field_contract.py` 报 0 / 0 / 0 |
| 7 | 删掉旧的同一性自检 | `05-广告前端Demo/tests/selfcheck_decision.py` |
| 8 | `gate` 路由扩成约束型七条 | 见 §5 |

**我不做的**：Runner、提示词、Pi 调用、输入桥。那四样全在他那侧。

## 5. 校验器七条（两边都要认，我在服务端再校一遍）

1. 每个枚举字段的取值必须在词表内
2. `payload` 里引用的数字必须等于确定性层同口径值（这是交叉核对，不是钉答案）
3. 不得与事实矛盾：说位置在丢，排名数据必须真在降
4. `evidence_ids` 每个都能在本次 `evidence_index` 里查到，零悬空
5. `causal_claim` 必须为 false
6. `rule_status != 'confirmed'` 时 `exact_budget` / `exact_bid` /
   `exact_placement_adjustment` / `exact_value` 必须为 null，
   并置 `exact_values_withheld = true`
7. 自由文本一句话有字数上限

**跨步闭环另算三条**：B2 的 `task_id` ⊂ B1、B3 的 `task_id` ⊂ B1、
B4 的 `diagnosis_id` ⊂ B3。

**这批检查打在造的假数据上，不指定真产品。** Agent 重跑结果会变，
打在真产品上会今天绿明天红，看起来像代码坏了。

## 6. 已经定了的，不要再改

| 事 | 定论 |
|---|---|
| 产品目标 | 运营设定的输入，Agent 不判。已改完：状态已确认、依据是运营口径、来源标 `operator_set` |
| 生命周期、词位置升降 | 当输入给。前者是产品模块的判断，后者是两点相减的算术 |
| 匹配度、竞品压力分类 | Agent 判（B0cd）。这两个是分级结论，念出来就把话说完了 |
| 页面绝不回落到回放 | 缺失 / 过期 / 不完整一律「待确认」，不拿 `ext_*` 顶上 |
| 浏览器不触发 Agent | 外壳拿不到请求体，Runner 是本地脚本。所以没有页面可见的「执行中」 |
| 三条数据不变量 | 月度数与日粒度不混算、归因销售额不相加、Campaign 级规则每 Campaign 计一次 |

## 7. A1 的演示范围

- **54 个广告组全跑**。就这么点，全跑了演示时点任何一行都有依据，不会点到空。
- **855 个投放对象抽 20–30 个**，按特征抽不要随机抽：四种匹配方式（精准 363 /
  广泛 196 / 词组 113 / 自动）各要有，有花费和无花费各要有。

随机抽会漏掉特征——检查打在一个没有该特征的对象上，全绿等于没查。

## 8. 顺序：谁先谁后

```
第一步（他）   建两张新表 + 落库，先只跑 B0b 一个点，status=completed
第二步（我）   读取层改到新表，验证 B0b 能上屏          ← 接缝在这里就验通了
第三步（他）   补齐 B0cd/B0e/B1-B4 七步串行
第三步（我，并行）  页面一接 A1、按钮改名、字段对账脚本跟着改
第四步（两边） 一起跑：5 个子 ASIN 全链 + A1 按 §7 范围
第五步（两边） 换校验器，删旧自检
```

**关键是第一步和第二步**：只用一个输出点把接缝验通，再堆剩下八个。
先做完九个点再来对接，对不上就得整体返工。

## 9. 怎么确认真的对接上了

一条命令，两边都能跑：

```
cd 09-工作台 && /usr/bin/python3 tests/check_agent_field_contract.py
```

它报三个数：

- **服务端吃掉几个字段** —— Agent 写了但读取层没传出来
- **白写几个** —— 传出来了但页面不读，等于白写
- **会空几个** —— 页面要读但没人写，页面上是空白或 undefined

**三个都为 0 才算接上。** 现在（旧表结构下）是 0 / 0 / 0。

它是静态分析加真实落库数据对照，不依赖 Agent 跑出什么结论，所以
Agent 重跑不会让它变红——只有字段对不上才红。
