# Agent 运行与落库口径（跨模块，v1.0）

适用：ads / competitor / keyword 三个模块的 Agent 产出落库。inventory 已按这套跑通，可直接参照
`02-产品销售库存模块/01-方案与数据需求/10-盘点结论Agent接口契约.md`。

**2026-08-31 王楠拍定：追加，不覆盖。页面读最新一次运行。**
理由是要保住页面上「较上次 加重／减弱／持续」和盘点表「与上次比」那两列 —— 覆盖会把被比较的那一份删掉。

附带的演示价值：追加让这两列**现场可演** —— 先跑一次，改一个门槛，再跑一次，页面上「较上次」真的会动。覆盖模式演不了这个。

---

## 一、语义（三个模块统一，不要各自发明）

1. **一次运行 = 一批行，追加写入。已写入的行永不修改、永不删除。**
   唯一例外是 run 头的 `status`（见第 5 条）。
2. **页面读「最新一次 completed run」**，不读「表里的全部行」。
3. **不设 `is_latest` 列。** 它要求写新行时回头改旧行，与第 1 条冲突，且两个进程同时写会双双为 1。
   最新是读取端排序算出来的，不是写入端标记出来的。

## 二、run_id 与 id 生成

统一格式：`<判断对象>-<run_date>-<seq>`，`seq` 从 1 起，同对象同日重跑 +1。

```sql
-- 写入前取 seq，同一事务内
SELECT COALESCE(MAX(CAST(substr(run_id, length(:obj) + length(:run_date) + 3) AS INTEGER)), 0) + 1
FROM <run 表> WHERE run_id LIKE :obj || '-' || :run_date || '-%';
```

- **子表的 id 必须包含 run 维度**，或以 `(run_id, seq)` 作唯一键。
- **id 不得依赖全局排位。** 竞品现在 `report_id = RPT-2026-08-03-04`，第三段是**报告内的 item_seq** —— 单对象重跑拿不到全局排位，必须改成含 `run_id` 或按 `scope_key` 重编。

## 三、时间戳（这条守的是已经复现过的静默错误）

- `created_at` **一律 ISO 8601 带偏移**：`2026-08-31T06:57:01+08:00`。
- 库存踩过：同一列里混着 `2026-08-30T22:56:12.869Z` 和 `2026-08-31T06:57:01` 两种格式，**按字符串比较会把带 Z 的判成前一天**，于是更新的结论被更旧的盖掉，而界面上没有任何症状。
- 读取端要宽容（两种格式都能解析），写入端必须严格（一律带偏移）。

## 四、读取端取最新的写法

```
SQL 只按 run_date 粗筛（纯日期，无歧义）
  → 同一天的多条在应用层按「解析后的时刻」选最晚（带 Z 的按 UTC 换算）
```

不要在 SQL 里对 `created_at` 做字符串 `MAX()` 或 `ORDER BY`。已验证实现见 `09-工作台/modules/inventory/verdict.py`。

## 五、半份结果不能上屏

写入顺序固定：**先写全部子表 → 最后写 run 头**（或 run 头先 `status='running'`，全部子表写完再改 `'completed'`）。
页面只读 `status='completed'` 的 run。

这样中途失败的那一批天然不可见，不需要回滚。**这是追加模式比覆盖模式干净的地方** —— 覆盖一旦写一半失败，表里就是半新半旧，页面上看不出来。

## 六、「较上次」必须真的能 JOIN 上

- run 头带 `prev_run_id`，指向同对象的上一个 completed run；**首次运行为 NULL**。
- `prev_run_id` 非空时**必须能 JOIN 到存在的那一行**。
- 首次运行时页面显示「首次分析」，不显示「较上次 持续」。
- 竞品现状：20 条 run 的 `prev_run_id` 全部悬空，页面照样显示「较上次 加重」。这条必须先修，否则那一列是假的。

## 七、三个模块各自要改什么

### competitor —— 最接近，交底 `05-Agent交底包.md:77` 已声明追加语义

| 项 | 现状 | 要改 |
|---|---|---|
| run 头 | `fact_competitor_analysis_run.run_id` 是 PRIMARY KEY ✓ | 补 `seq` 生成规则（现有 20 行 seq 全是 1，从没被验证过）；补 `prev_run_id`、`status` |
| 子表 run 引用 | `_change` / `_timeline` / `_open_item` 首列即 `run_id` ✓；`_report.ref_run_id` ✓；`_handoff.frozen_run_id` ✓ | 不用加列 |
| 唯一约束 | 三张子表**无 PRIMARY KEY 也无 UNIQUE** | 加 `UNIQUE(run_id, change_seq)` / `(run_id, track, item_seq)` / `(run_id, item_seq)`，防同一 run 内重复插 |
| report_id | 第三段是报告内 item_seq | 含 `run_id`，或按 `scope_key` 整份重编 |
| 落库路径 | 全仓 `INSERT INTO fact_competitor_analysis*` **0 命中**，只有离线 `03_build_analysis.py` | **补运行时写入接口** —— 这是三个模块里唯一缺整段链路的 |

### keyword —— 选了追加就必须加 run 维度（覆盖才不用）

| 项 | 现状 | 要改 |
|---|---|---|
| run 头 | **没有 run 表** | 建 `fact_keyword_agent_run`：`run_id` PK、`run_date`、`data_as_of`、`model_version`、`rule_version`、`prev_run_id`、`status`、`created_at` |
| 五张判断层表 | 单列 PK（`evidence_id` / `event_id` / `event_id` / `record_id` / **`report_date`**），只有 `run_date`，无 `run_id`、无 `created_at` | 各加 `run_id` 列 + 外键；`fact_keyword_daily_report` 的 PK 从 `report_date` 改为 `run_id`（否则同日第二次直接撞） |
| `is_latest` | `fact_keyword_audit_record` 现有此列 | **删掉**，改由读取端排序（见第 1 条第 3 款） |

### ads

| 项 | 现状 | 要改 |
|---|---|---|
| run 头 | `run.json` 顶层无 `run_id` / `model_version` / `created_at` / `data_as_of` / `rule_version` | 全部补上，并落成 run 表 |
| 三张主表 | `ext_diagnosis` / `ext_recommendation` / `ext_required_ad_task` 无 `run_id` 列；`decision_id = dec_<asin>_20260803` | 加 `run_id` 列；`decision_id` 含 run 维度 |
| `ext_meta.built_at` | 填的是 `as_of`（2026-08-03）不是构建时刻 | 填真实构建时刻，或改名避免误用 |

## 八、门禁（三个模块各自实现，判据一致）

1. **同对象同日连跑两次**：两次都成功，表里两条 run 并存，页面显示第二次的结论，`prev_run_id` 指向第一次。
2. **`prev_run_id` 非空必须 JOIN 得上**，且首次运行必须为 NULL。
3. **中途失败不上屏**：人为让第 N 条子表写入失败，页面必须仍显示上一次的完整结论，不显示半份。

门禁必须打在**真有该特征的对象**上（例：竞品要挑一个 `prev_run_id` 该非空的族），否则全绿只是零覆盖。

## 九、不归模块、由外壳侧修（王楠已知，Kiro 负责）

- `server.py` / `core/ctx.py`：POST body 进不到模块，且未读 body 会污染 keep-alive 连接（下一个请求 501 并断连）。**外壳补完之前不要写 POST 客户端** —— 现在 POST 不报错、回 200、参数静静丢掉，`context_hash` 还反过来报「已匹配」。
- 外壳 role 筛选硬编码 4 个取值，漏了 `unset`（占关键词 1711 词 / 86%）。

## 十、另一条与本文档无关但必须一起定的

**枚举翻译归属逐字段写死。** 三个模块现状各不相同（ads 服务端已译、competitor 后端 `data.py:18-24` 译、keyword 写库时码值 + `_label` 成对），照错的后果统一是**静默出空、不报错**：竞品实测把 `attention_level` 写成中文，判断带那一位空白且排序垫底。

规则：**翻译只发生在一处**，Agent 一律输出码值，除文档逐字段点名的自由文本（`headline` / `body` / `basis` / `statement` 这类）。
