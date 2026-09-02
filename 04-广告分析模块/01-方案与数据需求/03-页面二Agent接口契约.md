# 页面二 Agent 接口契约 v1.0

2026-08-30 · 广告分析模块 · 单一子 ASIN 广告决策

这份契约由前端逼出来的，不是拍的：前端渲染不出来的字段就是 Agent 必须补的字段。
现阶段 Agent 那一段用已落盘的真实决策链回放（v0.2.0 四张表），
**接口形状与真 Agent 就绪后完全一致**，届时只替换 `lib/decision.py::agent_stages`
的数据来源。

---

## 1. 形态：Agent 不自动跑

```
进页面
  GET /api/ads2/context?child_asin=…
  → 立即渲染板块 1/2/3/5（判断依据 + 现有结构）
  → 返回 context_id / context_hash / readiness
  → 板块 4/6/7/8 是压低的空壳 + 一个「开始分析」按钮

用户点「开始分析」
  POST /api/ads2/run  { child_asin, decision_id?, context_hash? }
  → NDJSON 串行四段：task → mapping → diagnosis → proposal
  → 前端逐段填板块 4/6/7/8

运营拍板
  POST /api/ads2/decide { child_asin, recommendation_id, decision, edits?, reason? }
  → 板块 9 交接给执行与复盘模块
```

配套：`GET /api/ads2/candidates` 选子 ASIN，`GET /api/ads2/gate` 契约门禁。

---

## 2. Agent 的输入（context）

方案 8.5 能力五「组装单一子 ASIN 广告决策证据」的标准输出就是这个 payload，
不用另外设计。

```
context        决策版本：decision_id / child_asin / parent_asin /
               product_goal / product_goal_version / goal_status /
               decision_at / previous_decision_id
versions[]     该子 ASIN 的全部决策版本，可切历史版本重看
evidence[]     evidence_id · evidence_type · evidence_title · payload ·
               observed_at · valid_as_of · evidence_nature · evidence_status ·
               caveat · board
existing_structure[]
               该子 ASIN 名下真实广告对象：层级 / 类型 / Campaign /
               广告目的与确认状态 / 标签 / 共享子 ASIN 数 / 归因天数 /
               月度指标 / 数字来源
history        events[] 历史动作与交接字段 · reviews[] D+3 / D+7 复盘
readiness      can_run · judgment_mode · goal_confirmed ·
               missing_evidence[] · stale_evidence[] · blockers[] · notes[]
context_hash   只哈希会影响判断的输入
context_id     decision_id@hash 前 12 位
```

**`evidence_nature` 三分类**（方案 6.2 要求把三者分开保存）：
`fact` 观察到的事实 · `inference` 系统推导的结论 · `confirmed` 运营已确认的目标。

**`board` 决定落在哪个板块**：`goal`→板块2，`market`→板块3，
`ads`/`history`→广告表现与历史复盘列。

---

## 3. Agent 的输出（四段）

四段是真依赖链，必须串行：前一段的输出是后一段的输入。

### stage=task → 板块4 应有广告任务（能力六）

```
task_id · task_type · task_direction · priority(P0/P1/P2/P3) ·
target_scope · constraints[] · evaluation_direction · stop_condition ·
rule_status · rule_id · exact_budget · exact_bid ·
exact_placement_adjustment · evidence_ids[] · inventory_constrained ·
judgment_mode · exact_values_withheld
```

方案 7.2 要求每项任务说明六件事，逐一对应：服务哪个目标（`impacted_goal`
在诊断段给）/ 争取或保护什么流量（`target_scope`）/ 作用于哪些对象
（`target_scope` + mapping 段）/ 优先级与适用时间（`priority`）/
成本库存风险条件（`constraints` + `inventory_constrained`）/
用什么结果判断达成（`evaluation_direction` + `stop_condition`）。

### stage=mapping → 板块6 目标—结构—表现对照（能力七）

```
mapping_id · task_id · ad_object_id · coverage_status ·
attribution_limit · evidence_ids[] · is_automatic_error ·
ad_object{ name, campaign, ad_type, purpose, attribution_days, metrics{} }
```

`coverage_status`：`covered` 已被承担 · `mixed` 混合了多个目的 ·
`missing` 没有对象承担 · `duplicate` 多个对象重复承担。
`attribution_limit`：`exclusive` / `shared` / `unattributed`。
`ad_object` 为 `null` 就是结构缺口，页面必须显式说「当前没有广告对象承接」。

### stage=diagnosis → 板块7 广告诊断与优先级（能力八）

```
diagnosis_id · task_id · problem_type · impacted_goal · priority ·
confidence(high/medium/low) · evidence_ids[] · uncertainty ·
missing_input · check_direction · basis_type · causal_claim ·
judgment_mode
```

方案 9.2 要求每条诊断必含六项，逐一对应：发生了什么（`problem_type`）/
影响哪个目标（`impacted_goal`）/ 依据哪些事实（`evidence_ids`）/
多可靠（`confidence` + `basis_type`）/ 还缺什么（`missing_input`）/
为什么排这个优先级（`priority`）。

`basis_type` 是判断依据的优先顺序（方案 4.8）：
`confirmed_rule` 客户已确认阈值 > `self_history` 自身历史 >
`peer` 可比对象 > `conditional` 条件判断。

**`causal_claim` 必须为 false**，除非真有因果证据。方案 9.2：
不因两个指标同时变化就输出确定因果。

### stage=proposal → 板块8 广告调整方案（能力九）

```
recommendation_id · diagnosis_id · product_goal_version · ad_purpose ·
ad_object_id · structure_gap_id · direction · rationale ·
preconditions[] · risks[] · uncertainty · observation_metrics[] ·
review_windows[] · d7_not_required · rule_status · rule_id ·
exact_value · judgment_mode · exact_values_withheld
```

`direction` 取值（方案 10.2）：`KEEP` `OBSERVE` `ADJUST` `PAUSE` `RESUME`
`SPLIT` `MERGE` `BUILD` `TEST` `DEFER` `REQUEST_INFO` `PREREQUISITE`。

---

## 4. 五条不能破的约束

### 4.1 `evidence_ids` 只能引用 context.evidence 里的 id

这是「点依据能高亮页面元素」的物理保证，不是文案承诺。
Agent 引用了 context 之外的 id，运营点过去就是空的，
「算法可核验」当场变成假的。

`GET /api/ads2/gate` 把这条做成门禁，悬空就 FAIL。**必须进回归。**
前端 `flashEvidence()` 在找不到时 `console.warn` 报悬空，不静默失败。

### 4.2 context 冻结并带 hash

`context_hash` 只哈希会影响判断的输入（决策版本、目标版本与状态、
每条证据的 id / valid_as_of / status / payload、结构的目的与关键指标、
数据包版本），不含渲染顺序。

`run` 请求带上打开页面时拿到的 hash；服务端在第一行回执里给
`context_hash_matched`。不匹配时页面提示「依据在你打开页面后变过」。
方案 4.3 要求上游变化时提示原判断可能过期，5.6 要求生成新版本不覆盖旧结论。

### 4.3 规则未确认时不许出精确值

`rule_status != 'confirmed'` 时 `exact_budget` / `exact_bid` /
`exact_placement_adjustment` / `exact_value` 必须是 `null`，
并置 `exact_values_withheld = true`。
这是 schema 级约束，不靠 prompt 里写「记得别编数」。方案 5.5。

### 4.4 判断档位是一等字段

`judgment_mode` 三态（方案 4.3）：
`formal` 正式判断（客户已确认目标与阈值）·
`conditional` 条件性判断（靠自身历史或可比对象）·
`unable` 暂时无法判断（证据或规则不足）。

前端按这个字段决定渲不渲染数值，不靠文案暗示。

### 4.5 `readiness` 在按钮之前算出来

不够跑就把「开始分析」置灰并写明缺哪一项，
不能让用户点了等半天换回一句「无法判断」。

---

## 5. 界面不摆内部枚举

`task_type` / `problem_type` / `direction` / `coverage_status` /
`attribution_limit` / `handoff_status` 以及库里那批英文短语
（`goal confirmation` / `stockout` / `bid changes unknown` …）
一律经 `page2.js` 顶部的映射层转成人话再上屏。
`cn()` 缺映射时退回原值并 `console.warn`，这样新增枚举会被发现，
而不是静默把 `ACOS_UP_VS_SELF_HISTORY` 摆给客户看。

`task_id` / `diagnosis_id` / `ad_object_id` 这类内部 id 也不上屏：
对照段引用任务时用任务的人话名（`S.taskName`），
方案段引用诊断时用诊断的人话名（`S.diagName`），
引用广告对象时用对象名（`S.objName`）。

---

## 6. Demo 的三态

`GET /api/ads2/candidates` 返回 521 个子 ASIN，分三档：

| 档 | 数量 | 含义 |
|---|---:|---|
| `full` | 1 | 有决策版本（B088WF1PRW，2 个版本），可完整跑四段 |
| `facts_only` | 520 | 有广告花费与推广关系，无产品目标与上游证据 → `unable` |
| `none` | 0 | 连推广关系都没有 |

**降级不是缺陷，是方案 4.3 明写要演的东西。** 演示时主打 B088WF1PRW 走全链，
随手点别的子 ASIN 展示「暂时无法判断」+ 缺什么。

B088WF1PRW 当前版本（2026-08-03）：6 条证据 / 3 任务 / 3 结构对照 /
3 诊断 / 3 建议；历史版本（2026-07-10）：完整闭环含 D+3 与 D+7 真实回流数值。
四种运营决定 accept / modify / reject / defer 都有真实样本。

---

## 7. 回归判据

数据层 `tests/selfcheck_decision.py`：
- 候选三态分布 · context 四板块非空 · readiness 判对
- 四段都非空 · 段间 id 能串上（mapping/diagnosis 的 task_id ⊂ task，
  proposal 的 diagnosis_id ⊂ diagnosis）
- 精确值零泄漏 · `causal_claim` 全为假
- `evidence_ids` 零悬空 · 两个决策版本的 hash 必须不同

接口层 `tests/check_agent_stream.py`：
- NDJSON 段序严格 `task → mapping → diagnosis → proposal`
- 传错 hash 时 `context_hash_matched` 必须为 `false`

前端层（浏览器断言，待落成文件）：
- 顶栏页面名只出现 1 次
- 34 项内部枚举与英文短语零命中
- 依据 chip 全中文、零悬空、点了能高亮唯一一条证据
- 覆盖三态（已被承担 / 混合 / 没有对象承担）都出现
- 接受与修改出交接块，拒绝与暂缓不出

---

## 8. 换成真 Agent 时改哪里

只改 `lib/decision.py::agent_stages()` 的数据来源：
现在读 `fact_required_ad_task` / `bridge_task_ad_object` /
`fact_ad_diagnosis` / `fact_ad_recommendation` 四张表，
改成调 Agent 进程（Node 18812，外壳反代 `/api/agent/*`）。

不用改：三个接口的形状、`context` 的组装、`context_hash` 的算法、
门禁、前端全部代码。

Agent 那边要保证的就是第 4 节那五条。其中 4.1 和 4.3 建议在服务端
收到 Agent 响应后再校验一遍，不信任模型自觉。
