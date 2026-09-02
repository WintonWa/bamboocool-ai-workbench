# 产品销售库存模块 · 数据构建

> 这个包是怎么来的、五个版本什么关系、要重跑该怎么跑。模块总说明见上一层 `README.md`。

## 构建链（不是线性的）

```
/Users/linsen/BAM/数据源/AI广告对接数据-总20260803/        ← 客户原始，唯一真源
        │
        ├──→ build_product_inventory_dataset.py      → v0.1.0   （无 sqlite，17 个 JSON）
        ├──→ build_product_inventory_dataset_v020.py → v0.2.0   19 表 / 8,461 行
        ├──→ build_product_inventory_dataset_v021.py → v0.2.1   19 表 / 8,479 行
        └──→ build_product_inventory_dataset_v022.py → v0.2.2   22 表 / 21,098 行
                                                          │
                    ★ 唯一一段真链式，而且脚本不在本目录 ↓
              06-Pi-Agent交互Demo/scripts/v030/pipeline.py
                                                          │
                                                          ↓
                                                      v0.3.0   44 表 / 1,992,532 行 / 466MB
```

**两条容易搞错的：**

**一、前四版各自独立从客户原始数据重建，不是一版改一版。** 每个 `build_*.py` 都自己读
`数据源/AI广告对接数据-总20260803`。后面的脚本虽然声明了前面版本的路径常量
（`v022` 里同时有 `V010_ROOT` / `V020_ROOT` / `V021_ROOT`），但那是用来做对照与继承字段的，
主输入仍是客户原始数据。**只有 v0.2.2 → v0.3.0 是真正的链式**：
`scripts/v030/constants.py:20` 写死 `SOURCE_DB = v0.2.2/...sqlite`。

**二、v0.3.0 的构建脚本不在这个目录下。** 它在
`/Users/linsen/BAM/06-Pi-Agent交互Demo/scripts/v030/`（`constants.py` / `pipeline.py` / `schema.py`）。
在库存模块里找它必然找不到，容易误判成「手工生成、不可重建」。

## 每个脚本

| 脚本 | 输入 | 输出 | 能重跑吗 |
|---|---|---|---|
| `build_product_inventory_dataset.py` | `数据源/AI广告对接数据-总20260803` + `01-客户数据源索引` | `v0.1.0/`（17 个 JSON，无 sqlite） | 能。`DATASET_VERSION = "0.1.0"` |
| `build_product_inventory_dataset_v020.py` | 同上 + 引用 `V010_ROOT` | `v0.2.0/...v0.2.0.sqlite` | 能。`DATASET_VERSION = "0.2.0"` |
| `build_product_inventory_dataset_v021.py` | 同上 + 引用 `V010_ROOT` / `V020_ROOT` | `v0.2.1/...v0.2.1.sqlite` | 能。修了计量单位（件 vs 盒）和生命周期覆盖 108→342 |
| `build_product_inventory_dataset_v022.py` | 同上 + 引用 `V010/V020/V021_ROOT` | `v0.2.2/...v0.2.2.sqlite` | 能。把 6 月库龄前滚到统一基准日 2026-08-03，新增批次表 |
| `06-Pi-Agent交互Demo/scripts/v030/pipeline.py` | **只读 `v0.2.2` 的 sqlite** | `v0.3.0/`（sqlite + 51 个逐表 JSON 导出 + README） | 能。`RANDOM_SEED = 20260830`，可复现 |

## 五个版本

| 版本 | 表 | 行数 | 大小 | 基准日 | 状态 |
|---|---|---|---|---|---|
| `v0.3.0` | 44 | 1,992,532 | 466MB | 2026-08-03 | **权威主库**（`paths.PRODUCT_DB`） |
| `v0.2.2` | 22 | 21,098 | 11MB | 2026-08-03 | **同时在用**（`modules/inventory/data.py:26` 当来源事实包读） |
| `v0.2.1` | 19 | 8,479 | 8MB | 2026-08-03 | 过期，仅作 v0.2.2 的构建输入 |
| `v0.2.0` | 19 | 8,461 | 8MB | — | 废弃，无运行时引用 |
| `v0.1.0` | — | — | — | — | 废弃。**没有 sqlite**，17 个文件全是 JSON |

v0.3.0 与 v0.2.2 行数差 94 倍，因为 v0.3.0 才有 342 子体 × 730 天的逐日事实
（`fact_child_sales_daily` 等，各 249,660 行）。

**能删的**：`v0.2.0`、`v0.1.0`（合计约 8MB，全树零引用）。
**不能删的**：`v0.3.0`（主库）、`v0.2.2`（在用）、`v0.2.1`（删了 v0.2.2 就重建不出来）。

## 表的分类

v0.3.0 的 44 张表按性质分三类，**这个区分很要紧**——给 Agent 设计输入时判据就是它：

**一、客户原始派生的观察事实**（已发生，可作 Agent 输入）
`fact_child_sales_daily` / `fact_child_inventory_daily` / `fact_child_advertising_daily` /
`fact_child_price_daily` / `fact_child_traffic_daily` / `fact_child_promotion_daily`
各 249,660 行；`dim_product_child` / `dim_product_parent` 产品维度；
`plan_child_*` 未来计划（人排的活动排期，也算「已定义」故合法）。

**二、构造出来的答案**（未发生或已推断，**Agent 禁读**）
`fact_child_forecast_daily`（90 天预烤预测的 p10/p50/p90）、
`fact_child_sales_daily.lost_sales_units` 与 `potential_demand_units`、
`dim_child_lifecycle_history` 的 `lifecycle_stage` / `change_reason` / `confidence_score`、
`fact_child_promotion_daily.preset_uplift` / `performance_index`、
`fact_child_inventory_daily.coverage_days`。

逐列清单与禁读理由见
`/Users/linsen/BAM/01-方案与数据需求/12-需求预测Agent职责修订.md` §5。

**三、构造元数据**（每张表都有，**Agent 一律禁读**）
`value_origin`（取值 `synthetic_demo` / `derived_from_actual`——它直接告诉模型哪些数据是造的）、
`method_version`、`provenance`、`quality_status`。

## 包内自带的说明文件

`v0.3.0/` 是四个包里最齐的：

```
dataset-manifest.json     版本、基准日、表清单
quality_report.json       扁平检查表（注意：不是 v0.2.2 那种四块汇总，页面因此还要读 v0.2.2）
source_lineage.json       每张表追到哪个客户原始文件
README.md                 包自己的说明
（另有 51 个逐表 JSON 导出，其中 feature_child_demand_daily.json 单个 156MB）
```

`v0.2.2/` 有 `dataset-manifest.json` 与 `quality_report.json`（页面读的就是这两个）。

## 重跑

```bash
cd /Users/linsen/BAM
/usr/bin/python3 02-产品销售库存模块/02-数据构建/build_product_inventory_dataset_v022.py
/usr/bin/python3 06-Pi-Agent交互Demo/scripts/v030/pipeline.py
```

Python 必须 `/usr/bin/python3`（3.9.6）。v0.3.0 那步会写 466MB sqlite 加 51 个 JSON
（其中一个 156MB），跑之前确认磁盘有 2GB 余量。

`RANDOM_SEED = 20260830` 与 `FORECAST_RUN_ID = "forecast-v030-20260803-default"` 都写死在
`constants.py`，所以同一份 v0.2.2 重跑出来的 v0.3.0 是可复现的。

## 已知问题

1. **`quality_report.json` 两版格式不同**导致 v0.2.2 删不掉——这是格式变更没做兼容留下的债，
   要治就得让 v0.3.0 的质量报告补上那四个汇总块，然后页面只读一处。
2. **v0.1.0 目录名带版本号但里面没有 sqlite**，只有 JSON。按目录名会以为它是同类的一版。
3. **前四版都从客户原始数据重建**，意味着改了客户原始数据会同时影响四版，但没有任何脚本
   校验四版之间的一致性。
4. **`01-方案与数据需求/05-数据缺口登记.md` 的所有数字来自 v0.2.2 实测**，
   v0.3.0 换底座后没重测过。
