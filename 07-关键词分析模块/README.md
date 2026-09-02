# 07-关键词分析模块

站点 / 品线：US / BAMBOO COOL 男士内衣　　数据基准日（as_of）：**2026-08-03**
工作台服务端口：**18820**（模块 id `keyword`，路由前缀 `/api/keyword/`，参数前缀 `kw.`）

## 这个模块是什么

判断对象是**关键词**，以及**关键词 × 子 ASIN 的覆盖关系对**。
回答三个问题：市场上这个词在涨还是在退、自有子体在这个词上排到第几位、下一步该投哪个词。
三个页面：`kw-overview`（关键词动态与机会总览）/ `kw-market`（市场关键词库与单词深研）/
`kw-child`（子 ASIN 关键词盘点）。

规模：共享词库 1,991 词，其中监控词 300 个；重点子 ASIN 30 个（覆盖全部 5 个父体）；
关系对 901 对；逐日窗口 182 天（2026-02-03 ~ 2026-08-03）。

---

## ⚠️ 三个先看的坑

### 坑 1：`modules/keyword/` 会遮蔽 Python 标准库的 `keyword`

**别 `cd` 进 `/Users/linsen/BAM/09-工作台/modules/` 跑任何 python。**
那个目录里有 `keyword/__init__.py`，cwd 会被塞进 `sys.path[0]`，
于是标准库的 `keyword` 模块被这个包顶掉。实测（只读复现）：

```
$ cd /Users/linsen/BAM/09-工作台/modules && /usr/bin/python3 -c "from keyword import iskeyword"
ImportError: cannot import name 'iskeyword' from 'keyword'
  (/Users/linsen/BAM/09-工作台/modules/keyword/__init__.py)
```

`iskeyword` 被 `dataclasses`、`collections.namedtuple`、`sqlite3` 的一些路径间接用到，
所以**报错信息跟你写的代码毫无关系**，看上去像解释器坏了。
脚本一律从 `/Users/linsen/BAM/09-工作台/` 或更上层跑，不要在 `modules/` 里跑。

### 坑 2：两个 107 MB 的库，按文件名挑必挑错

`02-数据构建/v0.1.0/` 下两个库**逐表行数完全相同**（都是 24 表 / 423,555 行），
区别只在 7 张表的表名前缀。名字里带正式版本号的那个**不是**工作台读的那个：

| 文件 | 大小 | 角色 | 证据 |
| --- | --- | --- | --- |
| `keyword_demo.sqlite` | 107.5 MB | **权威**，工作台唯一打开的库 | `/Users/linsen/BAM/09-工作台/core/paths.py:58-60` 的 `KEYWORD_DB` 指它 |
| `bamboocool_keyword_v0.1.0.sqlite` | 108.9 MB | 构建脚本的原始产物，是 `migrate_to_contract.py` 改名前的**源库** | `build_keyword_dataset_v010.py:22` 写它；`migrate_to_contract.py:21` 读它。**没有任何工作台代码打开它** |

源库不是废弃件——重跑迁移还要它当输入。但它不能上工作台：表名不合接入契约 6.2，
`value_origin` 是旧的四值（`customer_real` / `customer_real_anchor` / `derived` / `synthetic_demo`），
上屏文案里还留着 v0.3.0 的英文枚举码。三样都在迁移那一步才被改掉。
详见 `02-数据构建/README.md`。

### 坑 3：关键词 Agent 一次都没成功落过正式表

3 次 Loop Smoke 全部失败在第 4 步，错误码 `MODEL_TIMEOUT`；
两个正式落点在磁盘上**根本不存在**。细节见下面「Agent 状态」一节。

---

## 目录里有什么

```
/Users/linsen/BAM/07-关键词分析模块/
├── README.md                    ← 本文件
├── 00-源表勘查/                 只读勘查客户三个源文件的结构与 ASIN 交集
│   └── probe_kw_asin_overlap.py
├── 01-方案与数据需求/           方案、需求、进度、Agent 契约、机械导出的字典与样例
└── 02-数据构建/                 13 个构建脚本 + v0.1.0 数据包（见该目录 README）
```

工作台侧代码不在这里，在 `/Users/linsen/BAM/09-工作台/`。

---

## 数据包现在用哪一版

**权威：** `/Users/linsen/BAM/07-关键词分析模块/02-数据构建/v0.1.0/keyword_demo.sqlite`

| 项 | 值 |
| --- | --- |
| 表数 / 行数 | 24 表 / 423,555 行 |
| 大小 | 107,511,808 字节（107.5 MB） |
| 基准日 | 2026-08-03（与产品包 v0.3.0 三锚点一致） |
| 表名前缀 | `dim_keyword*` / `fact_keyword_*` / `bridge_keyword_*` |
| `value_origin` 取值 | `direct` / `derived` / `constructed`（契约 6.4 三值） |
| 门禁 | 构建期 46 条 + 落盘复核 13 条，全绿；逐条断言在 `v0.1.0/dataset-manifest.json` 的 `gates` |

只有这一个版本目录（`v0.1.0`），没有多版本并存问题。目录里另外两类文件：

- `bamboocool_keyword_v0.1.0.sqlite` —— 改名前源库，见坑 2，**仍是构建链的一环，不要删**
- 24 个逐表 `*.json` + `dataset-manifest.json` —— 构建脚本的导出件，
  **文件名用的是改名前的旧表名**（`dim_brand.json` / `dim_market_keyword.json` /
  `dim_scope.json` / `dim_state_label.json` / `dim_child_product_goal.json` /
  `fact_child_inventory_absorb.json` / `fact_child_traffic_attribution_daily.json`），
  跟 `keyword_demo.sqlite` 里的表名对不上。按 JSON 文件名去库里找表会找不到。

---

## 工作台哪几个文件读它

代码在 `/Users/linsen/BAM/09-工作台/`：

| 文件 | 作用 | 打开数据包的那一行 |
| --- | --- | --- |
| `core/paths.py` | 登记 `KEYWORD_DB` | `:58-60` → `07-关键词分析模块/02-数据构建/v0.1.0/keyword_demo.sqlite`（可用环境变量 `WORKBENCH_KEYWORD_DB` 覆盖） |
| `modules/keyword/module.py` | 外壳唯一读的文件。MODULE 自描述：3 页 / 8 路由 / `prefix=kw` / 1 个 task | `:334` `"db": paths.KEYWORD_DB`；`:35` 走 `agent_result.select_database()` 选库 |
| `modules/keyword/data.py` | 只读事实层 | `:44-48` `connect()`：`sqlite3.connect(f"file:{keyword_db}?mode=ro", uri=True)`，再 `attach` 产品包 `paths.PRODUCT_DB` 读 342 子体身份（契约 6.3，本包不重建 `dim_product_child` / `dim_product_parent`） |
| `modules/keyword/agent_result.py` | 双库切换：有已发布的 Agent 结果就读它，否则回落基准包 | `:17-18` `CURRENT_DB` / `STATE_DB`（见下节，磁盘上不存在）；`:66-67` 两库都 `mode=ro` 打开 |
| `modules/keyword/compute.py` | 所有依赖参数的计算，每次请求重算 | 不直接开库 |
| `modules/keyword/rules.py` | 10 个 `kw.*` 参数，全带 (下限, 上限, 步长) | 不开库 |
| `web/modules/keyword.js` / `keyword.css` | 前端，ES module + `[data-module="keyword"]` 作用域 | 不开库 |

`data.py` **只 select `_label` 列**，码值不出 SQL —— 这是防枚举码上屏的主防线，
渲染态禁词扫描只是二道闸。改 SQL 时多选一个码值列就多一个泄漏点
（跑 `09-工作台/tests/probe_code_fields.py` 看载荷里还剩哪 29 个码值字段）。

`data.py` 的路径来源有两层：请求级覆盖 `_REQUEST_DATABASE`，
否则 `agent_result.database_path(paths.KEYWORD_DB)`。

---

## 这个模块的 Agent 状态

**结论：没跑通过。正式落点在磁盘上不存在，页面现在读的一直是基准包。**

### 说好的落点

`modules/keyword/agent_result.py:17-18` 定义两个文件，都在
`/Users/linsen/BAM/09-工作台/modules/keyword/derived/` 下：

| 文件 | 该装什么 | 磁盘上 |
| --- | --- | --- |
| `keyword_agent_current.sqlite` | Agent 判断后的完整业务库 + `fact_keyword_agent_manifest`（`run_id` / `context_hash` / `params_json` / `status`） | **不存在** |
| `keyword_agent_state.sqlite` | 旁挂台账 `fact_keyword_agent_run`（`run_id` / `context_hash` / `status`） | **不存在** |

三处代码引用这两个名字，全都还在等它们出现：

- `/Users/linsen/BAM/09-工作台/modules/keyword/agent_result.py:17-18`
- `/Users/linsen/BAM/09-工作台/modules/agentcfg/registry_seed.py:403`
  （注册 `agent_id=keyword-opportunity`，`db=keyword/derived/keyword_agent_state.sqlite`）
- `/Users/linsen/BAM/09-工作台/tests/test_keyword_agent_roundtrip.py:8-10`
  （自己造这两个库跑往返测试，跑完清理）

Agent 侧的写入方是 `/Users/linsen/BAM/06-Pi-Agent交互Demo/src/keyword-agent.ts:16,19`，
默认路径和上面逐字一致。

选库逻辑是**双向确认**：`current` 的 manifest 与旁挂台账必须同时 `completed`
且 `run_id` / `context_hash` 一致，参数契约（`compare` / `rank_shift` / `group_dedup` +
四个权重）也必须与本次请求相同，否则降级 `base` 或 `stale`。
两个文件缺一个就直接 `base`，理由「没有已发布的关键词 Agent 结果」。
**半份产出永远不会上屏——这是设计如此，不是 bug。**

### 3 次 Loop Smoke 的实际结果

`/Users/linsen/BAM/09-工作台/modules/keyword/derived/keyword_agent_loop_state.sqlite`（24 KB）
里 `fact_keyword_loop_run` 3 行，全部 `failed`：

| task_id | 停在第几步 | 模型 | error_code | message |
| --- | --- | --- | --- | --- |
| `keyword-loop-20260831131455-230637` | 4 / 6 | `xiaoyao/gpt-5.6-luna` | `MODEL_TIMEOUT` | Pi 模型超过 60 秒没有完成本批判断 |
| `keyword-loop-20260831131738-0e6d5d` | 4 / 6 | 同上 | `MODEL_TIMEOUT` | 同上 |
| `keyword-loop-20260831141843-6acf65` | 4 / 6 | 同上 | `MODEL_TIMEOUT` | 同上 |

六步是：① 冻结范围 → ② 读取首批市场候选（20 个）→ ③ 创建真实 Pi 会话 →
④ **调用 Pi 判断首批候选（三次都死在这里，60 秒超时）** → ⑤ 接受结构化工具结果 →
⑥ 在 Demo 边界收口。前三步三次都 `completed`，后两步一直 `pending`。
`accepted_count` / `result_count` 全 0。

前端入口：`module.py` 的 `TASKS[0]`「运行关键词分析」，
`run` → `/api/keyword/run-agent-loop`，`poll` → `/api/keyword/agent-loop-status`，
两个都转发给 Agent 服务 `paths.AGENT_ORIGIN`（默认 `http://127.0.0.1:18812`）
的 `/api/agent/keyword/loop-runs`。

### `derived/` 下那 308 MB 是什么

```
/Users/linsen/BAM/09-工作台/modules/keyword/derived/
├── keyword_agent_loop_state.sqlite                     24 KB   Loop Smoke 运行态，3 run / 18 step（上表）
├── agent_run_state.sqlite                               0 字节  空文件，全仓零引用 —— 判不出，需王楠确认
├── runs/                                              103 MB   Agent 运行的暂存目录
│   └── keyword-all-2026-08-03-003.recovery.sqlite     107.5 MB
└── quarantine-20260831-pre-atomic-fix/                206 MB   原子发布修复前的两份隔离快照
    ├── keyword-2026-08-03-20260831091855-bf9b2e.writing.sqlite.bak   107.5 MB
    └── keyword-2026-08-03-20260831092302-4a8781.writing.sqlite.bak   107.5 MB
```

三个大文件都是 25 表（= 基准包 24 表 + `fact_keyword_agent_manifest`），
manifest 里 `status` 全是 `writing`，`completed_at` 全 `NULL`。**都是半成品，都不该发布。**

- **`runs/`** 是 Agent 的暂存位。`keyword-agent.ts:416` 把运行中的库写成
  `derived/runs/.<runId>.writing.sqlite`，跑完才原子改名发布成 `keyword_agent_current.sqlite`。
  目录里现在这一份 `keyword-all-2026-08-03-003.recovery.sqlite` 是**上一次完整链路没跑完时留下的恢复证据**，
  被刻意保留：Agent 侧设计文档
  `/Users/linsen/BAM/06-Pi-Agent交互Demo/docs/superpowers/specs/2026-08-31-keyword-agent-loop-smoke-design.md:19`
  明写「保留为上次完整链路未完成时的恢复证据，本功能不修改它」。
  它半在哪儿看得见：`fact_keyword_evidence` 只有 58 行（完整应 562）、
  `fact_keyword_coverage_event` 45 行（应 973）、`fact_keyword_market_change_event` 85 行（应 148）、
  `fact_keyword_daily_report` 和 `fact_keyword_audit_record` **0 行**。
  也就是 Agent 跑到证据那一层就停了，日报和盘点整块没有。
  `/Users/linsen/BAM/09-工作台/tests/probe_partial_agent_run.py` 拿它当现成样本，
  在临时目录验两件事：`writing` 时选库逻辑是否真的拒绝（该拒绝）、
  万一被误标 `completed` 页面会不会崩（日报 0 行时页面一的 hero 与五问五答没有数据源）。

- **`quarantine-20260831-pre-atomic-fix/`** 是 2026-08-31 修「原子发布」之前的两份 `.writing` 库快照。
  目录名就是它的用途（pre-atomic-fix = 修复前）。**全仓没有任何代码引用这两个 `.bak`。**
  它们的 manifest 比 `runs/` 那份还少一列：只有
  `run_id` / `context_hash` / `status` / `completed_at`，**没有 `params_json`**。
  而 `agent_result.py:76-78` 的 SELECT 要读 `params_json` ——
  即便有人把它们放成 `current`，也会抛 `sqlite3.Error` 被兜到「current 或台账不可读」。
  两份的 `context_hash` 相同（`df2e84c4…`），是同一个上下文相隔 4 分钟的两次尝试。
  **能不能清理判不出，需王楠确认**（占 206 MB，但可能是留作复现原子发布 bug 的证据）。

---

## 文档在哪

全在 `/Users/linsen/BAM/07-关键词分析模块/01-方案与数据需求/`：

| 文档 | 回答什么问题 | 状态 |
| --- | --- | --- |
| `08-给Agent侧的完整交底.md` | 模块定位、三页结构、数据来源总览 —— **自包含入口，先读这份** | 2026-08-31 核对 |
| `01-关键词模块能力盘点.md` | 方案 4.3/5.2/7.3/8.3 拆成 10 能力 / 12 判断点 / 6 横切 / 5 红线 | 有效 |
| `02-关键词Demo数据需求.md` | 客户三个源文件里有什么、必须构造的九层数据是哪九层、构造硬约束 | 有效（顶部已回填实现状态） |
| `03-当前进度与下一步.md` | **交接件**：怎么跑起来、文件地图、21 个修过的 bug、环境坑、还没做完的、待用户拍的 6 条口径 | 2026-08-31，压缩上下文后先读这份 |
| `04-关键词Demo实现方案.md` | 三页 17 板块 → 表字段映射 | 有效 |
| `05-Agent输出面交底.md` | 关键词 Agent 的需求与数据契约 **v2** | 有效。**v1 已作废**（把库里 562 条构造证据、14 行构造日报的成品句当「现在的样子」示范给 Agent，等于钉答案，且缺第 4 节） |
| `06-数据字典.md` | 24 张表逐张：行数、列数、每列类型与枚举全集 | **机械导出，不要手改**；重新生成跑 `02-数据构建/export_agent_package.py` |
| `07-接口JSON样例.json` | 六个 GET 路由的真实响应，长数组截到前 2 项并标原长度 | 同上，机械导出 |

⚠️ `03-当前进度与下一步.md` 的「文件地图」一节列的是 4 份 `.md`，
现在实际有 6 份 `.md` + 1 份 `.json`（05 / 06 / 07 / 08 是后加的），
且那一节把 `keyword_demo.sqlite` 的表名写成旧名。读文件地图时以本文件为准。

---

## 测试

从 `/Users/linsen/BAM/09-工作台/` 跑（**不要 cd 进 `modules/`**，见坑 1）：

```bash
/usr/bin/python3 tests/test_gates.py                  # 17/17 模块接入契约
node tests/test_keyword_routes.mjs                    # 15 深链往返（纯函数，不需服务）
node tests/test_keyword_render.mjs                    # 24 渲染态禁词（需服务）
/usr/bin/python3 tests/test_keyword_params.py         # 11 参数真改数字（需服务）
/usr/bin/python3 tests/test_keyword_agent_result.py   # 选库逻辑
/usr/bin/python3 tests/test_keyword_agent_roundtrip.py# 自造两个 Agent 库跑往返
/usr/bin/python3 tests/test_keyword_loop_task.py      # Loop task 面板
/usr/bin/python3 tests/probe_code_fields.py           # 载荷里还剩哪些码值字段
/usr/bin/python3 tests/probe_partial_agent_run.py     # 拿半成品 recovery 库试页面
```

`test_keyword_render.mjs` 和 `test_keyword_params.py` 都做过注入自检
（把 `organic_state_label` 改成 `organic_state` 渲染态立刻红；注掉 `_recompare` 参数测试立刻红）。
**改这两个测试要重做注入自检**，否则可能变成假绿。

---

## 已知问题

1. **`modules/keyword/` 遮蔽标准库 `keyword`** —— 坑 1，报错信息与你的代码无关。
2. **两个同行数的 107 MB 库** —— 坑 2，按「哪个像正式版本号」挑会挑错。
3. **Agent 从未成功落表** —— 坑 3，3 次 `MODEL_TIMEOUT`，正式落点两个文件不存在。
4. **`derived/` 下 308 MB 全是半成品** —— 一份刻意保留的恢复证据 + 两份无人引用的隔离快照。
5. **`derived/agent_run_state.sqlite` 是 0 字节空文件，全仓零引用** —— 判不出，需王楠确认。
6. **`v0.1.0/*.json` 的文件名是改名前的旧表名**，与 `keyword_demo.sqlite` 里的表名对不上（7 张）。
7. **日报 Q3 一句文案自相矛盾** ——「当日新增覆盖 0 条、丢失覆盖 0 条，其中涉及核心词 114 条」。
   前两个数按 `to_date == 当日` 过滤，而汇总型事件的 `to_date` 也是当日。
   要回 `02-数据构建/lib_l89.py` 改口径并重建那 14 行日报。见 `03-当前进度与下一步.md` §9。
8. **剩 7 条验收断言没补** —— 恒定列 / 全破折号列 / 同类折叠 / 0 值渲染 / 子体去重 /
   不可比词上限 / 连续下滑非零。
9. **竞品验证回写只有三态占位** —— 竞品模块的真实验证结果还没接。
10. **载荷里仍有 29 个字段带码值** —— 跑 `probe_code_fields.py` 看清单。
11. **外壳的参数面板把 `bool`/`enum` 参数渲染成文本框**（只认 `num` 的 min/max/step）。
    契约禁改外壳，接受现状。
12. **6 条口径待王楠拍** —— 「关键词流量获取」的正式测量定义（现用代理指标「监控词带来的自然
    Sessions」）、产品目标六种枚举、覆盖监控范围是否铺满 342、`mens underwear` 的形态、
    页面三主演示对象、双来源冲突展示方式。逐条见 `03-当前进度与下一步.md` §10。

---

## 两个演示对象必须一起用

`B0B3LWGP36`（66 对全真实锚点，演「覆盖完整但仍有缺口」）
+ `B0CBPXNC1M`（0 锚点但五态齐全，演「没覆盖」与「没采到」的区别）。
**跟五态、偏弱、未覆盖有关的验证必须打在后者上**，打在前者上是假绿。
