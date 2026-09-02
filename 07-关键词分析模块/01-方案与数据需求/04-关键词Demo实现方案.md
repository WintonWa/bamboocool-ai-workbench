# 关键词分析模块 — Demo 实现方案

> 依据：方案 7.3（三页板块）/ 8.3（十项能力）；数据包 `02-数据构建/v0.1.0`（24 表 / 423,555 行 / 46 条门禁全绿）
> 编写日期：2026-08-30　　基准日：2026-08-03

---

## 1. 技术栈与目录

沿用产品库存模块已验证的形态，不引新框架：

| 项 | 选择 | 理由 |
| --- | --- | --- |
| 服务端 | stdlib `http.server.ThreadingHTTPServer` + `sqlite3` 只读 | 零依赖，与 18810 同构 |
| 端口 | **18813** | 18810 单品盘点 / 18811 UICraft 测试 / 18812 广告 已占用 |
| 绑定 | `127.0.0.1` 显式指定 | 回环，无鉴权，不对外 |
| 图表 | ECharts 5.5.1 静态文件（复制 `03-前端Demo/web/assets/echarts.min.js`） | 26 期趋势 + 182 天位置线 + 双 grid，手写 SVG 做不到 |
| 视觉 | 复用 `03-前端Demo/web/app.css` 无边框浅色系统 | 已定型四轮，不重新设计 |
| 进程 | `start.py` 双 fork + `os.setsid` | 防 KiroCrew 进程组回收 SIGTERM |

```text
06-关键词前端Demo/                        ← 与 07-关键词分析模块（数据）分开，沿用现有编号习惯
├── server.py            路由 + JSON 响应
├── start.py             双 fork 启动
├── lib/
│   ├── data.py          只读取事实，不做任何依赖参数的计算
│   ├── compute.py       所有依赖参数的计算，每次请求重算
│   └── rules.py         RuleSet 参数集
├── web/
│   ├── index.html       三页签
│   ├── app.js           板块渲染
│   ├── app.css          复制自 03-前端Demo 后增量
│   ├── kwchart.js       趋势图 / 位置图 / 覆盖结构图
│   └── assets/echarts.min.js
└── tests/
    ├── test_api_contract.py     每个端点的字段契约
    ├── test_page_acceptance.py  板块级验收（含禁词扫描）
    └── test_render.mjs          Node 里跑 ECharts 配置桩
```

`data.py` / `compute.py` 的分工必须照抄产品模块的纪律：**只要一个值依赖参数面板，它就不能出现在 `data.py`**。

---

## 2. 判断层边界（哪些读、哪些算）

沿用产品模块定下的 B 方案：**判断层只出判断，工作台自算全部下游算术**。

| 类别 | 归属 | 具体内容 |
| --- | --- | --- |
| 读判断层结果 | `fact_keyword_evidence`（562 条） | 七类证据的定性、结论文案、主要依据、证据完整度、下一步验证方向 |
| 读判断层结果 | `fact_keyword_market_change_event`（148） / `fact_keyword_coverage_event`（973） | 变化事件的类型、连续性、中文标签 |
| 页面自算 | 覆盖结构统计 | 按需求词组汇总自然/广告/双覆盖/未覆盖计数 |
| 页面自算 | 位置变化聚合 | 182 天内上涨/下降/新增/丢失的条数与幅度 |
| 页面自算 | 词组汇总 | 搜索量按 `bridge_keyword_group.dedup_weight` 分权求和 |
| 页面自算 | 优先级排序 | 按参数权重对证据重排（证据自带 `priority` 只作默认序） |
| 页面自算 | 日报数字 | 代理指标当日值与环比 |
| 页面自算 | 缺口清单 | 监控词集 − 已覆盖词集，按目标相关性过滤 |

**判断层现在是确定性规则产物，将来由离线 Agent 同构替换**——替换时页面代码不用改，因为读的是同一张表同一批字段。

---

## 3. 三页 → 板块 → 表字段映射

### 3.1 页面一 关键词动态与机会总览（端点 `/api/overview`）

| 板块（方案编号） | 主要表 | 关键字段 | 页面动作 |
| --- | --- | --- | --- |
| 3.3 数据范围与数据状态 | `dim_scope` / `dim_market_keyword` | `as_of_date` `library_status` 四态分布 `monitored_keyword_count` | 直接显示；口径说明进 ⓘ |
| 3.4 动态关键词日报 | `fact_keyword_daily_report` | `q1..q5` `traffic_proxy_metric/value/delta` `priority_evidence_ids` | 五问五答直出；每条答案挂下钻链接 |
| 3.5 市场需求与词组变化 | `fact_keyword_market_change_event` + `bridge_keyword_group` + `dim_keyword_group` | `event_type_label` `continuity_label` `change_ratio` `dedup_weight` | 按词组汇总变化；**搜索量必须按 dedup_weight 分权** |
| 3.6 自有核心词覆盖与位置变化 | `fact_keyword_coverage_event` + `dim_keyword_child_pair` | `event_type_label` `from_rank/to_rank` `is_core_keyword` `child_asin` | 只陈述事实，不给广告结论 |
| 3.7 机会与风险优先列表 | `fact_keyword_evidence` | `evidence_type_label` `priority` `conclusion` `main_basis` `evidence_completeness_label` `next_verification_label` | 按参数重排；每条带「影响谁 / 为什么 / 还缺什么」 |
| 3.8 下钻入口 | — | 携带 `site/product_line/as_of/compare/keyword_id/child_asin/goal` | 跳转不丢条件（方案 §6.5） |

**必须能演出的状态**：至少 1 条「暂不可比较」（来自 `comparable_flag=0` + `comparable_block_reason`）、七类证据里 ≥5 类同屏。

### 3.2 页面二 市场关键词库与单词深研（端点 `/api/library`、`/api/keyword/{id}`）

| 板块 | 主要表 | 关键字段 | 备注 |
| --- | --- | --- | --- |
| 4.3 词库范围与质量 | `dim_market_keyword` / `dim_keyword_alias` | `library_status_label` `raw_variant_count` `first_seen_date` `last_updated_date` | 四态可筛；别名两类（原始写法 / 拼写变体）分开显示 |
| 4.4 需求词组与市场结构 | `dim_keyword_group` / `bridge_keyword_group` / `bridge_keyword_attribute` | `group_name` `demand_dimension` `member_count` `dedup_weight` | 一词多标签不重复计入；59 组 |
| 4.5 市场关键词比较区 | `fact_keyword_market_snapshot`（末期） | 需求 / 购买 / 供给 / 竞价 / 集中度 + `measure_definition` `comparable_flag` | **两来源并列成列**，冲突不合并（840 词广告竞品数不一致） |
| 4.6 单词市场事实深研 | `fact_keyword_market_snapshot`（26 周 + 12 月） | 全字段时间序列 + `change_shape_label` `value_origin` | 双频率画两条线，绝不合并；末期标「客户原值」，历史段标构造 |
| 4.7 关键词与产品关系区 | `dim_keyword_child_pair` + `fact_keyword_child_position_daily` + `dim_child_product_goal` + `fact_child_inventory_absorb` | `anchor_band_label` `organic_rank` `ad_rank` `coverage_state` `product_goal_label` `absorb_state_label` | **未绑定子体时只出市场事实**（方案 §6.2） |
| 4.8 头部 ASIN 与竞品入口 | `fact_keyword_head_asin` | `rank_slot` `asin` `click_share` `conversion_share` `is_own_asin` | 跨期替换可见；头部 ASIN ≠ 已确认竞品 |

**图表**：单词深研主图 = 双 y 轴（左搜索量、右 ABA 排名 `inverse:true`），下方 26 期柱 + 头部份额堆叠条。

### 3.3 页面三 子 ASIN 关键词盘点（端点 `/api/child/{asin}`，**先做这一页**）

| 板块 | 主要表 | 关键字段 | 备注 |
| --- | --- | --- | --- |
| 5.3 产品上下文 | `dim_child_product_goal` + `fact_child_inventory_absorb` + v0.3.0 `dim_product_child` | `product_goal_label` `push_role_label` `product_lifecycle` `absorb_state_label` `decision_summary` | 目标或库存缺失时明示，仍出事实 |
| 5.4 关键词覆盖结构 | `dim_keyword_child_pair` + `bridge_keyword_group` + 末日 `fact_keyword_child_position_daily` | 按 `demand_dimension` 分组的 覆盖/未覆盖 计数 + `anchor_band_label` | 自然与广告**分别**判断；缺口 = 该组监控词 − 已覆盖 |
| 5.5 自然位与广告位变化 | `fact_keyword_child_position_daily`（182 天） + `fact_keyword_coverage_event` | `organic_rank` `ad_rank` `organic_state` `collect_depth` | **五态必须可区分**：有排名 / 确认未覆盖 / 超采集深度 / 当日采集失败 / 未纳入监控 |
| 5.6 缺口·机会·风险 | `fact_keyword_evidence`（该子体） | 七类 + `priority` + `inventory_limit_label` + `competitor_verification_label` | 每条说明依据、影响的目标、库存限制、下一步 |
| 5.7 盘点记录 | `fact_keyword_audit_record`（3 期） | 覆盖计数 / 最好位次 / 中位位次 / 证据计数 / `rule_version` | 「与上次比」的差值由页面算，实测 29/30 子体有变化 |

**主演示对象 `B0B3LWGP36`**：66 个关系对全部带真实锚点，5 个父体里覆盖最富。

**图表**：位置图 = 上 grid 画自然位（`inverse:true`，1 在顶），下 grid 画广告位；采集失败日画灰色背景带，未纳入监控段整段置灰——**沿用产品模块柱状图的教训：状态区间画成背景，不占事件泳道**。

---

## 4. API 端点

| 方法 | 路径 | 返回 |
| --- | --- | --- |
| GET | `/api/meta` | 范围、基准日、词库四态分布、数据状态九态计数、规则版本 |
| GET | `/api/overview?compare=day\|week\|4week` | 页面一五个板块 |
| GET | `/api/library?status=&dimension=&group=&role=&q=` | 词库列表 + 词组结构（分页） |
| GET | `/api/keyword/{keyword_id}?child_asin=` | 单词深研；带 `child_asin` 时追加产品关系区 |
| GET | `/api/child/{child_asin}` | 页面三全部板块 |
| GET | `/api/child/{child_asin}/audit` | 3 期盘点记录 |
| GET | `/api/rules` | 参数面板当前值与取值域 |
| GET | `/api/labels` | `dim_state_label` 全量，前端映射用 |

所有响应带 `as_of` 与 `rule_version`，便于「总览的数字能在详情复核」。

---

## 5. 参数面板（留在页面的参数）

| 参数 | 默认 | 影响 |
| --- | --- | --- |
| 比较周期 | 对比前一日 | 日报环比、变化聚合窗口 |
| 自然位「偏弱」阈值 | 第 20 位 | 机会/风险的分档，不改变证据定性 |
| 采集深度上限 | 144（前 3 页） | 超深度的解释口径 |
| 词组汇总是否按权分摊 | 开 | 关掉时可演示重复计入的后果 |
| 优先级权重 | 需求规模 0.3 / 变化幅度 0.3 / 主推加权 0.2 / 证据完整度 0.2 | 只重排，不改结论 |
| 词库状态筛选 | 有效 + 监控 | 噪声与待确认默认收起 |
| 核心词位置连续天数 | 7 天 | 「连续下滑」的判定 |

**已移交判断层、不在页面**：词是否属于本品线、分类纠错、竞争结构解释、词与产品匹配度、证据定性、日报文案。

---

## 6. 界面纪律（照抄已生效的教训）

1. 三层文案：数字与数字的名字直接显示 → 栏目与口径解释收进 ⓘ 点开 → **「我为什么这么设计」的防御性自述一律不写**。判据：`innerText` 扫禁词表零命中。
2. 枚举码不上屏，全部走 `/api/labels`（`dim_state_label`）映射。
3. 顶栏日期用 `as_of=2026-08-03`，不用今天。
4. `flex/grid` 子项显式给 `min-width:0` / `min-height:0`；`grid-template-columns` 用 `minmax(0,1fr)`。
5. 全局加 `[hidden]{display:none!important}`，可见性断言查 `getComputedStyle().display` + `getBoundingClientRect()` + `elementFromPoint()` 三者。
6. 构造数据要能看出来：`value_origin` 决定角标（客户原值 / 末期锚点 / 构造），但**不写整句免责声明**。

---

## 7. 分步实施

| 步 | 内容 | 完成判据 |
| --- | --- | --- |
| A1 | 骨架：`server.py` + `data.py` + `rules.py` + `/api/meta` + `/api/labels` + 三页签空壳 | 两端点 200，页面能切换 |
| A2 | **页面三**（子 ASIN 盘点）五板块 + 位置图 | `B0B3LWGP36` 五态同屏可见，3 期盘点可比 |
| A3 | 页面二（词库 + 单词深研）六板块 + 趋势图 | 双频率两条线，两来源冲突并列，未绑定子体只出市场事实 |
| A4 | 页面一（总览）五板块 | 优先列表 ≥10 条覆盖 ≥5 类，至少 1 条「暂不可比较」 |
| A5 | 参数面板 + 三套测试 + 真实视觉验证 | 三套测试绿 + 截图逐块看过 |

---

## 8. 测试与验收门禁

| 组 | 内容 |
| --- | --- |
| 契约 | 每个端点的必需字段、类型、`as_of` 一致性 |
| 板块验收 | 每个板块至少一条**指名到对象**的断言（如「`B0B3LWGP36` 覆盖结构必须出现超采集深度与采集失败两态」） |
| 禁词 | `innerText` 扫 40 个枚举码 + 防御性表述词表，零命中 |
| 布局 | 子元素右边界不得超出容器；有内容的元素尺寸不得为 0 |
| 图表 | Node 里跑 ECharts 配置桩，校验双 grid、`inverse:true`、背景带落在真有该特征的对象上 |

**门禁必须打在真有该特征的对象上**——这一条在数据层已经吃过一次亏（详见 `03-当前进度与下一步.md` 第 4 节九个 bug），前端同样适用：不要在一个既无采集失败也无超深度的子体上断言「五态齐全」还打勾。
