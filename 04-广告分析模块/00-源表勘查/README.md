# 广告分析模块 · 源表勘查

> 这里是 20 个一次性探查脚本 + 1 个工具库。**不是产线代码，是当初摸清客户原始数据用的。**
> 想知道数据长什么样，先读 `../01-方案与数据需求/README.md` 指的文档；
> 只有那些文档答不了、要现场量一遍时才回到这里。

## 这些脚本都读什么

绝大多数直接读客户原始目录
`/Users/linsen/BAM/数据源/AI广告对接数据-总20260803/13.广告`，
**不读数据包**——所以它们的结论是「客户给的原始数据长什么样」，
不是「我们构建出来的包长什么样」。

`xlsxlite.py` 是零依赖的 xlsx 读取器（手写的，因为工作台不引第三方库），其余脚本都用它。

## 按用途分四组

**一、摸客户原始数据的形状**（最早那批，08-29）

```
probe_names.py            13.广告 目录下有哪些文件、表头长什么样
probe_dates.py            日期字段的范围与格式
probe_daily_coverage.py   日粒度数据覆盖到哪一天、有多少空洞
probe_inventory.py        广告数据与库存数据的 ASIN 交集（结论：交集 0，时间也不对齐）
probe_page1_shapes.py     页面一要的那些形状够不够
```

**二、摸广告结构的层级**（08-30）

```
probe_structure_depth.py   Campaign / 广告组 / 投放对象 三层的实际深度
probe_adgroup_count.py     广告组到底有多少个
probe_adgroup_source.py    广告组这个概念从哪张表来
probe_adgroup_diff.py      两个来源的广告组对不对得上
probe_cross_package.py     跨数据包（广告 × 产品）能不能 join
```

**三、摸页面二那条决策链**（08-30）

```
probe_page2_chain.py       决策链每一环有没有数据
dump_page2_chain.py        把整条链倒出来看
probe_page2_gaps.py        链上哪一环是断的
probe_page2_scenarios.py   能凑出几种演示情景
probe_demo_object.py       挑演示对象
page2_candidates.json      ← 上面这些的产物：候选对象清单
```

**四、审 Agent 的输入输出**（08-31，这组最要紧）

```
audit_agent_input.py       审 Agent 的输入里有没有产出侧字段被当事实喂了
audit_agent_vs_replay.py   Agent 真实产出 vs 重放对照
probe_agent_schema.py      Agent 落表的 schema
export_agent_samples.py    ← 产出 ../01-方案与数据需求/agent-samples/ 那 11 个文件
```

**第四组里 `audit_agent_input.py` 的结论写进了
`../01-方案与数据需求/06-广告Agent契约审计.md`**：`safety_breach_date` /
`stress_stockout_date` / `latest_order_date` 三个是产出侧被当输入喂了，
且实测确认进了 Agent 的 rationale 并会上屏。**这条结论至今未落地修复。**

## 怎么跑

```bash
cd /Users/linsen/BAM/04-广告分析模块/00-源表勘查
/usr/bin/python3 probe_names.py
```

Python 必须 `/usr/bin/python3`（3.9.6）。所有脚本都只读，跑多少次都不会改数据。
但注意它们大多硬编码了客户原始目录的绝对路径，**换机器要改路径**。

## 已知问题

1. **没有一个脚本有自己的说明**，脚本名是唯一的线索。上面这份分组是按代码内容归的。
2. **`probe_inventory.py` 的结论（广告与库存 ASIN 交集 0）已经过时**——那是拿客户原始数据比的；
   现在构建出来的包已按脊椎对齐，广告包是 521 子体、脊椎是 342，交集不为 0。
   见 `../01-方案与数据需求/README.md` 里 342/521 那条未裁决的冲突。
3. `export_agent_samples.py` 是这组里唯一还会被再用的（重新生成 `agent-samples/`），
   其余都是一次性的。
