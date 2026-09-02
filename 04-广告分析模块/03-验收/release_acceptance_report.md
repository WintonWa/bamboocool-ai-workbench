# 广告分析模块 v0.1.0 release 独立最终复验报告

验收日期：2026-08-29  
数据包：`/Users/linsen/BAM/04-广告分析模块/02-数据构建/v0.1.0`  
契约：`bamboocool-advertising-acceptance-v1` / `1.0.0`  
验收模式：`release`

## 总体结论：PASS

原两项 P0 已全部关闭：

1. `fact_product_ad_spend` 已完整、独立承载 520 个有月报明细的范围子体广告花费，并将唯一无子体明细的 `B0CCTCLTYS` 标为 blocked；没有向广告对象关系表伪造映射。
2. 739 条广告事实的指标和实际覆盖日期均能从原始行精确回算；原 8 条广告组部分覆盖事实已修正，并明确排除比较和排名。

自动契约、完整范围、原表回算、SQLite/JSON/前端同源、schema、manifest/hash、血缘、外键、质量报告和 13 个场景全部通过。当前无 FAIL、BLOCKED 或遗留修复项，release 可交付前端。

## 1. 自动验收

复验命令：

```bash
python3 "/Users/linsen/BAM/04-广告分析模块/03-验收/run_acceptance.py" \
  --dataset "/Users/linsen/BAM/04-广告分析模块/02-数据构建/v0.1.0" \
  --mode release \
  --output "/Users/linsen/BAM/04-广告分析模块/03-验收/latest_release_result.json"
```

结果：63/63 `PASS`；AD-01～AD-11、VS-00～VS-03 全部 `PASS`。机器输出见 [latest_release_result.json](/Users/linsen/BAM/04-广告分析模块/03-验收/latest_release_result.json)。以下 P0 复验和原表回算均为独立检查，不采用构建器自报状态代替。

## 2. P0-1 复验：子 ASIN 正广告花费事实 PASS

### 2.1 粒度和数量

`fact_product_ad_spend` 当前共 526 条：

| 粒度/状态 | 数量 | 结果 |
|---|---:|---|
| CHILD_ASIN / observed_positive | 431 | 与月报正花费子体逐行一致 |
| CHILD_ASIN / observed_zero | 89 | 与月报零花费子体逐行一致 |
| CHILD_ASIN / blocked | 1 | `B0CCTCLTYS`，花费为空 |
| PARENT_ASIN / observed_positive | 5 | 五父均有正花费汇总 |

因此 direct 子体事实严格为 `520 = 431 正 + 89 零`；5 条父体汇总是独立 `PARENT_ASIN` 粒度，不是重复子体记录。

按父体回算：

| 父 ASIN | 正花费子体 | 零花费子体 | 子体花费合计（源值） | 父体汇总（源值） |
|---|---:|---:|---:|---:|
| B0DDNK229S | 101 | 2 | 424,263.54 | 424,463.54 |
| B0GQXK2Q58 | 92 | 0 | 313,347.91 | 313,233.76 |
| B0CJV3G988 | 95 | 39 | 340,092.56 | 340,202.18 |
| B0D9FLMR6N | 85 | 11 | 273,863.61 | 273,939.49 |
| B0CCLWDJNV | 58 | 37 | 127,946.25 | 127,982.85 |

子体合计与父体汇总分别原样保留两个来源工作表的客户事实；没有为追求相等而修改或均摊源值。

### 2.2 原表逐行一致性

独立读取：

```text
数据源/AI广告对接数据-总20260803/
14.其他分析文件/2026年月报/6月/一组6月月报.xlsx
├── 产品表现-ASIN
└── 产品表现-父ASIN
```

检查结果：

- 520/520 子体的 ASIN、父 ASIN、广告花费、正/零状态和原表行号完全一致；
- 5/5 父体汇总的父 ASIN、广告花费和原表行号完全一致；
- 子体事实主键唯一，无缺失、无额外 direct 子体；
- `period=2026-06`，窗口为 2026-06-01～2026-06-30；
- 唯一不在月报子体表中的范围商品为 `B0CCTCLTYS`，正确保存为 `no_child_spend_fact + blocked + spend=null`，来源回到石晖产品跟进表第 849 行。

### 2.3 不伪造广告组关系

- `fact_product_ad_spend` 没有 `ad_object_id` 字段；
- `bridge_ad_object_product` 仍为 554 条，月报来源关系为 0；
- `promoted_asin` 仍严格为 115 个独立子体，只覆盖 B0DD/B0GQ/B0CJV 三父；
- B0D9/B0CC 的正花费证据没有被升级为 Campaign、广告组或 promoted 关系；
- 526/526 产品花费事实均有 `source_lineage`，并连接有效 `source_file_id`。

结论：`positive spend` 与 `promoted relation` 已在模型中正确分离，AD-02 通过。

## 3. P0-2 复验：事实实际覆盖日期 PASS

独立从六份 Amazon 原报表重新筛选和聚合全部 739 条 `fact_ad_performance`：

| 检查 | 结果 |
|---|---:|
| 展示、点击、花费、订单、广告销售差异 | 0/739 |
| CTR、CPC、CVR、ACoS、ROAS 差异 | 0/739 |
| coverage_start/end 差异 | 0/739 |
| 实际部分覆盖事实 | 218 |
| 部分覆盖状态标记错误 | 0 |

每条 coverage 均为实际参与聚合原始行的 `min(开始日期)` 和 `max(结束日期)`。218 条实际不足完整请求窗口的事实全部标为 `partial_source_coverage`。

原问题单中的 8 条广告组事实全部修正：

| fact_id | 修正后的实际 coverage |
|---|---|
| fact_2fdae9830d605ac3 | 07-01～07-05 |
| fact_6e621eec7f6391b8 | 07-01～07-23 |
| fact_48cf6b92d2018239 | 07-03～07-31 |
| fact_7f7d8c3af920315a | 07-01～07-23 |
| fact_6fbb1dea735aca64 | 07-01～07-24 |
| fact_671507fa23547773 | 07-01～07-18 |
| fact_201a39bf02174e80 | 07-18～07-18 |
| fact_b8c5e7217527da96 | 07-01～07-26 |

这 8 条在页面一全量广告组查询中均为 `comparison_eligible=0` 且 `rank_by_acos=null`，没有进入可比排名。AD-04-C 通过。

## 4. 完整 release 回归

### 4.1 范围、对象和角色

| 项目 | 复验结果 |
|---|---|
| 父/子范围 | 5 父、521 子；103/92/134/96/96，子体唯一归属 |
| 广告组名称键 | 54；SP40、SB5、SD9 |
| SP Target | 679 个 |
| 广告事实 | 739；Target 679、广告组 60 |
| 明确推广 ASIN | 115；B0DD 38、B0GQ 51、B0CJV 26，仅三父 |
| SB 映射 | 5/5 `pending_mapping` |
| 五类角色 | promoted / positive_spend / purchased / target / matched 均存在且不互相升级 |
| direct 事实窗 | 739/739 位于 2026-07-01～07-31 |
| 归因 | SP=7 天，SB/SD=14 天；739/739 正确 |

所有 promoted 关系均为 `direct + advertising_asin`；非 promoted 角色使用 `advertising_asin` 的数量为 0。共享广告对象保持 shared，没有均分或销售占比强拆。

### 4.2 SQLite、schema、JSON 与前端同源

- `acceptance_export.json` 的 21 个逻辑表与 SQLite 逐行归一化一致：21/21；
- `schema.json` 的 22 张表与 SQLite 列定义一致：22/22；
- `schema.sql` 包含 SQLite 的全部 22 张表和 10 个显式索引；
- 页面一、页面二共核对 744 个嵌套记录，与 SQLite 一致：744/744；
- 页面二 `product_ad_spend` 的明星子体和父体两条记录均来自新事实表；
- 页面一无产品目标、诊断、任务、预算/竞价/暂停建议等页面二字段污染。

### 4.3 manifest、质量、血缘和外键

- manifest 顶层 9 个最小字段完整；
- manifest 登记的 10 个交付文件 SHA-256 与字节数 10/10 一致；
- `quality_report.json` 为 PASS，16/16 检查通过；
- `source_lineage` 共 4,089 行；非 `scenario_added` 的 3,327/3,327 行均显式连接有效 `source_file_id`，连接率 100%；
- SQLite `PRAGMA foreign_key_check` 返回 0 条违规。

## 5. 13 个场景复演

13/13 场景均包含非空 `steps` 和 `expected_results`，步骤序号完整，引用记录全部存在。独立回归覆盖：

- 五类来源角色边界；
- 共享广告对象；
- 页面一筛选、比较、异常、标签版本和无规则场景；
- 页面二证据、任务、结构对照、诊断与建议；
- 库存限制、未确认规则不得给精确值；
- accept、modify、reject、defer；
- D+3/D+7 反馈回流。

明星共享对象 `grp_b29d2a07cfeb3144` 仍连接 5 个 promoted 子体并全部保持 shared。13/13 场景复演通过。

## 6. 最终能力与门禁

| 能力/门禁 | 状态 |
|---|---|
| AD-01～AD-11 | 全部 PASS |
| VS-00～VS-03 | 全部 PASS |
| 原 P0：子体正花费完整性 | PASS，已关闭 |
| 原 P0：实际 coverage | PASS，已关闭 |
| release 最终门禁 | **PASS** |

最终状态：`PASS`。没有需要构建 Agent 继续修复的阻塞项，数据包可进入前端交付。
