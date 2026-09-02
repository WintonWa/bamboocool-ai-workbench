# 竞品分析模块（competitor）交接说明

按 `00-通用方法与规范/02-模块接入契约.md` 交付，外壳零改动。

## 交了什么

```text
09-工作台/modules/competitor/module.py    外壳唯一读的自描述入口
09-工作台/modules/competitor/data.py      只读数据层（挂本包 + ATTACH 产品包）
09-工作台/modules/competitor/compute.py   两页载荷装配
09-工作台/modules/competitor/rules.py     cmp.* 参数声明与夹紧
09-工作台/web/modules/competitor.js       ES module，自注册
09-工作台/web/modules/competitor.css      作用域样式
08-竞品分析模块/02-数据构建/v0.1.0/competitor_demo.sqlite   数据包（23 表）
```

没交（契约 §3 明确不要）：`server.py`、端口、`index.html`、`app.css`、token 定义、浮层抽屉导航实现、AI 对话 UI。

## 接口

| 路由 | 说明 |
| --- | --- |
| `/api/competitor/rivals` | 总览：洞察带 + 变化计数带 + 威胁比较表 |
| `/api/competitor/rival/<family_asin>` | 详情：一个竞品产品族的完整分析 |
| `/api/competitor/meta` | 模块元信息、数据新鲜度、参数声明、待确认清单 |

页面 id：`cmp-overview`、`cmp-rival`。判断对象：竞品产品族（父 ASIN）。

## 外壳需要提供的 `ctx` 能力

前端一个都没自己实现，全部从 `ctx` 取：

| 名称 | 用途 |
| --- | --- |
| `ctx.api(resource)` | 请求 `/api/competitor/<resource>`，自动带上当前筛选与参数 |
| `ctx.el(tag, attrs, children)` | 建元素（`onclick` 直接传函数） |
| `ctx.money(v)` / `ctx.num(v)` / `ctx.pct(v)` | 金额、整数、百分比格式化 |
| `ctx.popover(anchor, text)` | 单例浮层，用于口径与「为什么」 |
| `ctx.setShared(patch)` | 改跨模块上下文（计数带点击写 `domain`） |
| `ctx.setModuleState(patch)` | 改本模块 state 子树（下钻写 `page` / `familyAsin`） |
| `ctx.spark({class,viewBox,points,invert})` | 画 sparkline。外壳未提供时模块退化成一行文字趋势（起点 → 当前 · 区间 · 观察点数），不静默留白，也不直接操作 document |

筛选项由模块声明、外壳渲染：竞品或 ASIN 搜索、时间范围、子类目（取 `meta.sub_categories`）、变化类型、证据状态。

## 需要的 token

`competitor.css` 头部列了完整清单。若 `tokens.css` 还没有，请按那份补齐——模块不就地定义色值（已核：0 个 hex / rgb 字面量）。

## 数据口径

- 基准日 2026-08-03，观察窗 2026-02-05 ~ 2026-08-03，无未来区间（竞品不做预测）；
- 产品脊椎 342 子 ASIN / 5 父 ASIN，`ATTACH` 产品包读，本包不含 `dim_product_child`；
- `bridge_competitor_child` 147 条关系，自家一侧全部落在脊椎内；
- `value_origin` 只在库里用：209 条基准日锚点与 67 条真实 ABA 前三是 `direct`，180 天序列是 `constructed`；上屏一律映射成 真实 / 推导 / 模拟 / 混合；
- **价差一律按件单价**：竞品多为 6 件装、自有为 3/4/7 件装，比整包价会得出假价差。

## 验收

`08-竞品分析模块/03-验收/test_contract_gates.py` — 20 条门禁（G1–G12 契约、A1–A3 构造锚、C1–C5 接入契约），全绿。

```bash
/usr/bin/python3 08-竞品分析模块/03-验收/test_contract_gates.py
```

## 契约自查（机械核对结果）

| 检查 | 结果 |
| --- | --- |
| CSS 选择器总数 | 47，全部在 `[data-module="competitor"]` 之下 |
| `#id` 选择器 | 0 |
| 裸元素 / 后代元素选择器 | 0（单元格改用 `.cmp-th` / `.cmp-td` 类） |
| 自定义色值字面量（hex / rgb） | 0，只用 token |
| 前端直接操作 `document` | 0，画图能力走 `ctx.spark` |
| ES module 导出 | `id` / `apiVersion` / `filters` / `mount` / `render` / `unmount` 齐全 |
| 门禁 | 20 条全绿 |
