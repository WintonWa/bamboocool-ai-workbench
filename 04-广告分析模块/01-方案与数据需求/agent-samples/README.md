# 接口真实响应样例

从跑着的工作台（`http://127.0.0.1:18820`）直接取的真实响应。

**这是形状参照，不是标准答案。** 按 `00-通用方法与规范/08-Agent需求与数据契约要则.md` §9「钉形状钉词表，不钉答案」：

- 字段名、类型、嵌套结构、数组形状：**照着对接**
- 产出侧的自由文本与结论取值：已替换成占位符，由 Agent 自己判断
- 输入侧的禁读字段（覆盖天数 / 断货日 / 建议补货量 / 生命周期 / 置信度）：已替换成禁读标记
- 长数组只留前 3 项并在原位注明原始长度

演示子 ASIN：`B0B3LWGP36`

| 文件 | 请求 | 内容 | 样例/原始字符数 |
|---|---|---|---|
| `candidates.json` | `GET /api/ads/candidates` | 选子 ASIN，带处境与证据完整度 | 5481 / 15034 |
| `context.json` | `GET /api/ads/context` | Agent 的输入（板块1/2/3/5） | 11310 / 13077 |
| `run.json` | `GET /api/ads/run` | Agent 的输出四段（板块4/6/7/8） | 16674 / 14832 |
| `decide-accept.json` | `GET /api/ads/decide` | 板块9 交接（运营接受 → 出交接块） | 516 / 394 |
| `decide-reject.json` | `GET /api/ads/decide` | 板块9（拒绝 → 不出交接块） | 210 / 182 |
| `decide-bad-param.json` | `GET /api/ads/decide` | 参数校验：缺 decision 时的失败形状 | 94 / 88 |
| `gate.json` | `GET /api/ads/gate` | 契约门禁自检：依据 id 零悬空 | 618 / 436 |
| `catalog-adgroup.json` | `GET /api/ads/catalog` | 页面一八板块（广告组粒度） | 12559 / 61101 |
| `catalog-target-filtered.json` | `GET /api/ads/catalog` | 页面一 + 组合筛选（族内 OR、跨族 AND） | 14187 / 268887 |
| `object.json` | `GET /api/ads/object/grp_03d043c7031eebf6` | 页面一详情抽屉八面板 | 1984 / 1607 |
