# 关键词分析模块（keyword）

外壳零改动的业务模块。接入契约见 `../../00-通用方法与规范/02-模块接入契约.md`。
**动这个模块之前先读** `../../07-关键词分析模块/01-方案与数据需求/03-当前进度与下一步.md`
——那份是交接件，含 21 个修过的 bug、环境坑、两个演示对象的分工。

## 身份

| 项 | 值 |
| --- | --- |
| 模块 id / 路由前缀 | `keyword` → `/api/keyword/<资源>` |
| 参数前缀 | `kw.`（必须在 MODULE 里显式声明 `prefix`，外壳默认取 `mid[:3]`=`key`） |
| CSS 作用域 | `[data-module="keyword"]` |
| 数据包 | `core/paths.py` 的 `KEYWORD_DB` → `07-关键词分析模块/02-数据构建/v0.1.0/keyword_demo.sqlite` |
| 表名前缀 | `dim_keyword*` / `fact_keyword_*` / `bridge_keyword_*` |
| 页面 | `kw-overview` / `kw-market` / `kw-child` |
| 路由 | `meta` `children` `overview` `terms` `term` `child` |

## 文件

- `module.py` —— 外壳唯一读的文件。MODULE 自描述，处理函数收 `core.ctx.Ctx`，
  路径段走 `c.rest`（资源名不带斜杠）。
- `data.py` —— 只读事实。`connect()` 挂本包 + ATTACH 产品包读 342 子体脊椎，
  **不重建 `dim_product_child` / `dim_product_parent`**（契约 6.3）。
  只 select `_label` 列，码值不出 SQL —— 这是防枚举泄漏的主防线。
- `compute.py` —— 所有依赖参数的计算，每次请求重算。
  `_absorb_sentence()` 用已映射标签重拼库存说明，不上屏 v0.3.0 的 `decision_summary` 原文。
- `rules.py` —— 10 个参数，全带 `(lo, hi, step)`，由 `core/ruleset` 统一夹紧。

## 测试

```bash
/usr/bin/python3 tests/test_gates.py            # 17/17 接入契约
node tests/test_keyword_routes.mjs              # 15 深链往返（纯函数，不需服务）
node tests/test_keyword_render.mjs              # 24 渲染态禁词（需服务）
/usr/bin/python3 tests/test_keyword_params.py   # 11 参数真改数字（需服务）
/usr/bin/python3 tests/probe_code_fields.py     # 载荷里还剩哪些码值字段
```

两条自定测试都做过注入自检：把 `organic_state_label` 改成 `organic_state` 渲染态立刻红，
注掉 `_recompare` 参数测试立刻红。**改这两个测试时要重做注入自检**，否则可能变成假绿。

## 两个演示对象

`B0B3LWGP36`（66 对全真实锚点，演覆盖完整仍有缺口）+
`B0CBPXNC1M`（0 锚点但五态齐全，演「没覆盖」与「没采到」的区别）。
跟五态、偏弱、未覆盖有关的验证必须打在后者上。
