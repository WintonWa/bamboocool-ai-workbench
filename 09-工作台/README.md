# Bamboocool 运营工作台（V6）

一个端口承载全部业务模块的统一工作台。**V6 = V5 前端成品的信息架构 + 零依赖运行时。**

外壳负责导航、路由、URL 状态、筛选快照、返回态恢复、AI 槽位、浮层抽屉和给模块的 ctx 工具；
业务表达全部由模块渲染。接入规则见
`../00-通用方法与规范/02-模块接入契约.md`（**改模块前必读**）。

## 启停

```bash
/usr/bin/python3 start.py {start|stop|restart|status}
```

必须用 `/usr/bin/python3`（本机 3.9.6，也是唯一装了数据链要用的 lxml 的解释器）。
服务端零第三方依赖：stdlib `http.server` + `sqlite3` 只读。
只绑 `127.0.0.1:18820`，**无鉴权** —— 本机演示用；要开隧道给外部看，先加访问控制。

## 环境变量

| 变量 | 默认 | 作用 |
| --- | --- | --- |
| `WORKBENCH_PORT` | `18820` | 端口 |
| `WORKBENCH_MODULES` | 空 = 全部 | 只加载指定模块，逗号分隔。开发单个模块时用 |
| `WORKBENCH_DEV` | `1` | 模块 `.py` 改动后按 mtime 热重载 |
| `WORKBENCH_AS_OF` | `2026-08-03` | 统一基准日，顶栏显示它而不是今天 |
| `WORKBENCH_PRODUCT_DB` / `_ADS_DB` / `_KEYWORD_DB` / `_COMPETITOR_DB` | 见 `core/paths.py` | 数据包路径 |
| `WORKBENCH_AGENT_ORIGIN` | `http://127.0.0.1:18812` | 独立 Agent 服务，`/api/agent/*` 反代到它 |

其他端口（都不是这个服务）：18810 旧库存 demo、18811 UICraft 对照副本、18812 Pi-Agent、18813 旧广告 demo。

## 结构

```text
09-工作台/
├─ server.py        单一路由器：/api/meta、/api/modules、/api/agent/*、/api/<模块>/<资源>
├─ start.py         双 fork + setsid 防进程组回收
├─ core/
│   ├─ paths.py     全部路径与端口，环境变量可覆盖
│   ├─ db.py        只读 SQLite：connect / rows / one / scalar / attach / spine_children
│   ├─ ruleset.py   参数声明 Param + 解析 + 夹紧 + 指纹 + 面板描述
│   ├─ registry.py  扫 modules/*/module.py 发现模块，逐模块 try/except，mtime 热重载
│   └─ ctx.py       给模块处理函数的请求上下文
├─ modules/<模块名>/{module,data,compute,rules}.py
├─ web/
│   ├─ index.html   八槽位骨架    shell.js  外壳运行时
│   ├─ tokens.css   设计令牌唯一来源   base.css  骨架样式
│   └─ modules/<模块名>.{js,css}
└─ tests/test_gates.py   契约门禁 G1–G18
```

## 新增一个模块

写两处文件，**外壳零改动**：

1. `modules/<id>/module.py` 定义 `MODULE` 字典（照抄 `modules/sample/module.py`）
2. `web/modules/<id>.js` + `.css`（照抄 `web/modules/sample.js` / `.css`）

目录名、路由前缀、`data-module` 属性值、前端文件名四处必须完全一致 —— 发现机制靠这个，
没有任何手工维护的清单。删一个模块就是删掉这些文件。

`modules/sample/` 是**参考实现兼外壳自检**，它真读 489MB 产品包。
给客户演示前用 `WORKBENCH_MODULES` 排除它，或直接删掉那个目录。

## 门禁

```bash
/usr/bin/python3 start.py start
/usr/bin/python3 tests/test_gates.py
```

18 条机械检查（作用域、无 token 新增、ES module、路由前缀、参数夹紧、不重建产品维度、
脊椎命中、载荷不泄漏内部叫法、模块零互相依赖、单模块可加载、故障隔离、深链往返、筛选标签）。

**G10 与 G11 无法机械化，必须人工做**：每个板块能说出它回答哪个经营问题；以及真看页面截图。
前两个模块的多个真 bug（柱子塌成 0×0、枚举值泄漏、数字挤在一起）测试当时全绿。

## 踩过的坑

- **`/usr/bin/python3` 是 3.9.6**：`dataclass(slots=True)`、`match` 都不能用。
  `X | Y` 注解靠每个文件顶部的 `from __future__ import annotations` 才合法。
- **改了 `core/` 必须重启**；改 `modules/` 下的 `.py` 靠 mtime 热重载（尽力而为，
  行为可疑时以 `restart` 为准）；改 `web/` 下的静态文件刷新页面即生效。
- **模块内的缓存必须能从 `MODULE["invalidate"]` 一次清干净**，否则热重载会读到旧值。
- **`[hidden]` 必须配 `display:none!important`**：它属于 UA 来源，任何作者样式写了
  `display` 都会盖掉它，hidden 的元素照样有实体几何、糊在页面上吃掉全部点击。
- **有扩展名的路径不存在就回 404**，不能拿 `index.html` 冒充缺失的 `.js` ——
  那会让浏览器报一个完全看不懂的解析错误。无扩展名的路径才交给前端路由。
- **`start.py` 的 pkill 匹配 `server.py` 路径**，不能用 `sys.executable`：
  运行中的进程显示的是解析后的框架路径，匹配不上会杀不掉旧进程还谎报成功。
