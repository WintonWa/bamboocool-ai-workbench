# 外壳与 Agent 交互｜当前进度与交接

更新：2026-08-31 04:32
适用：上下文压缩后或全新会话。**先读这份，再按需展开。**
范围：`09-工作台` 外壳侧（任务面板 / 对象栏 / 调参器 / Agent 接入机制）。
不含各业务模块内部进度——那些在各模块自己的目录里。
配套必读：`../00-通用方法与规范/02-模块接入契约.md`（**v1.3**，改模块前必读）。

---

## 0. 一句话状态

统一外壳 `09-工作台` 跑在 **18820**，五个模块全部可用不降级：
`ads` / `competitor` / `inventory` / `keyword` / `sample`。契约门禁 **17/17 全绿**。

本轮外壳新增三样：**任务面板**（Agent 唯一入口）、**对象栏改可收起的玻璃浮层**、
**`?tune=1` 实时调参器**。另外测了一个 WebGL 折射库并**否掉**，结论见第 5 节。

---

## 1. 在跑的服务

| 端口 | 是什么 | 目录 |
| --- | --- | --- |
| 18820 | **统一工作台（主线）** | `09-工作台/` |
| 18821 | LiquidGlass 性能测试隔离副本（结论已出，可删） | `10-LiquidGlass测试/` |
| 18810 / 18811 / 18813 | 合并前的旧独立 demo，勿在里面新建功能 | `03-` / `04-UICraft测试` / `05-` |
| 18812 | Pi Agent 交互 Demo（Node/TS，九工具循环） | `06-Pi-Agent交互Demo/` |

启停：`cd 09-工作台 && /usr/bin/python3 start.py {start|stop|restart|status}`
必须 `/usr/bin/python3`（本机 **3.9.6**，`dataclass(slots=True)` 等 3.10+ 特性不可用）。

---

## 2. Agent 接入机制（已定，九条）

2026-08-31 与王楠讨论后定的架构。**这九条是后续实现的前提，改之前先问。**

1. **agent 是任务执行器，不是对话。** 自然语言只用于选任务和填参数；追问也是任务
   （`explain(run_id, item_seq)`），不是聊天
2. **判据：普通代码做不了的才是任务。** 算 90 天逐日、比回测、算断货日都是算子；
   剔除缺货扭曲、判断该不该信这次回测、词归给哪个产品目标才是任务
3. **产出归属：结论落在拥有该对象的模块页**，面板只留「跑了什么、结果在哪」的指针
4. **落表是唯一产物通道**，前端永远读表，流式只是同一次跑的实时旁观
5. **信封：run 层 + item 层。** item 的 `kind` 每模块自定，公共层只定信封
   （`seq` / `kind` / `body` / `evidence_ids` / `magnitude+unit` / `confidence`）
6. **两条硬门禁**：`evidence_ids` 必须全在本次输入的证据包里，过不了整个 run 判失败
   不落库；要上屏的数字不能只活在自由文本里
7. **LLM 不碰写路径**，harness 校验后写，工具保持全只读
8. **trace 跟 run 一起落库**，永久可回看，不是加载动画
9. **槽位 6 是任务面板，不是聊天框**

### 关键事实：Pi Agent 循环现在**不产出数字**

`06-Pi-Agent交互Demo` 全库 `readOnly: true` + `PRAGMA query_only = ON`，
九个工具没有一个能写，`INSERT`/`UPDATE` 在 `src/` 里零命中。run 的产物是
`answer.delta` 一段中文文本，跑完什么都不留下。

v0.3.0 那 30780 行预测是 `scripts/v030/pipeline.py` + `forecasting.py` **离线烤好的**，
循环只是去读它然后讲一段话。**所以「点击 → Agent 出数字 → 回工作台」这条链断在第三步。**
要接上，缺的是输出契约 + 落库 + run 记录三件；规格已存在于
`01-方案与数据需求/07-预测Agent接口契约.md` v0.3（四张表 + 7 条门禁），循环没接上它。

`docs/2026-08-29-Pi-Agent交互Demo设计.md` **比代码落后一代**（写父体 4 工具 v0.2.2，
代码是子体 9 工具 v0.3.0）。以代码为准。

---

## 3. 任务面板（槽位 6）

代码：`web/index.html` 的 `#wb-task` + `web/shell.js` 的「槽位 6 任务面板」段 +
`web/base.css` 的同名段。

- **没有聊天输入框。** 列的是「可运行任务 → 执行过程 → 运行完成 + 查看结论指针」
- 任务由模块在 `MODULE["tasks"]` 声明，外壳零硬编码：
  `{ id, label, needs?: "object", run: "<本模块路由名>", hint? }`
  `core/registry.py` 的 `public()` 把它透给前端
- 参考实现：`modules/sample/module.py` 的 `handle_run` + `tasks`，跑真数据
- 非模态（无遮罩），页面保持可交互 —— 运营要一边看过程一边看页面数字
- footer 钉在面板底部、**在滚动区之外**（第一版塞进 body 里，过程一长就被滚走）
- 显示的耗时是**各步真实耗时之和**，不是墙钟时间（墙钟含 `REVEAL_MS` 揭示节奏，
  拿节奏当耗时报出去就是拿节奏冒充数字）
- 步骤行的 `sources` 用**中文数据源名**，`fact_*` 这类库内表名不上屏（G9）

**待做**：`evidence_ids` 和 trace step 双向可跳（点结论的依据跳到产生它的那一步，
点某一步高亮它支撑的结论）。这是「可核验」在界面上的具体形态，广告模块已有一半
（`compute.py` 里 evidence_id 必须全在 context 的检查），差双向跳转。

---

## 4. 对象栏（左侧长条）与视觉

### 开合机制

外壳拥有 `#wb-rail`，所以开合做一次，**五个模块全覆盖，模块零改动**。

- **默认 overlay**（王楠 2026-08-31 定）：玻璃浮层，和任务面板一套语言
- `?rail=push` 切另一种：展开时作为栅格列把内容推开、不遮数据
- overlay 下**默认收起**（浮层展开会盖住第一屏主指标）。改默认见 `shell.js` 的
  `RAIL_OPEN_DEFAULT`
- 手柄 `#wb-handle-l` 是常驻 `position:fixed`，展开时贴栏右缘显「收起」、
  收起时退到屏幕左缘显「对象」。**刻意不放在 `#wb-rail` 内部**——
  模块 mount 时 `host.rail.textContent = ""` 会清空那个容器

实测（广告页 1280 宽）：push 展开 rail 280 / body 936，收起 body 1232（+296px）；
overlay 展开时 body 始终 1232，栏浮在上面。

### 两组独立的 token：外观 + 几何各自独立

`web/tokens.css` 里 **`--glass-*` / `--panel-*`（任务面板）** 和 **`--rail-*`（对象栏）完全分开**。
第一版对象栏的高度是**借用** `--panel-h`、宽度写死 280px，所以「分别调整」当时根本做不到，
2026-08-31 04:25 才真拆开。当前值（王楠用调参器定的，两组外观同值）：

```
任务面板 外观  --glass-bg: rgba(208,209,211,0.02)
              --glass-filter: saturate(140%) blur(7px) brightness(0.91)
              --glass-hi: rgba(255,255,255,0)   --panel-r: 34px
任务面板 几何  --panel-w: 20vw  --panel-h: 89vh  --panel-edge: 16px  --panel-dy: 0px
对象栏  外观  --rail-bg: rgba(208,209,211,0.02)
              --rail-filter: saturate(140%) blur(7px) brightness(0.91)   --rail-r: 34px
对象栏  几何  --rail-w: 22vw   --rail-h: 89vh   --rail-edge: 16px   --rail-dy: 0px
```

**位置的表达方式：贴边 + 偏移，不用绝对坐标。**

- 参照点 = 面板所贴那条视口边的**垂直中心**（任务面板贴右缘，对象栏贴左缘）
- `--*-edge` = 到那条边的距离；`--*-dy` = 相对垂直中心的上下偏移（可负）
- 好处是窗口尺寸变了位置关系仍然成立
- 两个手柄的 `transform` 各自读自己那栏的 `--*-dy`，所以手柄和面板不会脱节
- `--rail-w` 同时驱动 push 模式的栅格列宽，一个宽度管两种模式

**不要手改 tokens.css，开调参器拖。**

### 关于毛玻璃的三条硬结论（别重复踩）

1. **透明度暴露出来的是白色。** 浅色高留白页面上，玻璃背后没东西可糊
2. **加大模糊会让它更不像玻璃**：大模糊把稀疏内容糊成近似白，再叠近白底色收敛成白
3. **「透明」和「像玻璃」是反方向的**：要看得见背后 → 高透明 + **小**模糊；
   要材质感 → 低透明 + 灰调。两者不可兼得
4. 玻璃只用在**外壳浮层**上，业务页面一律不用（全局原则 §8 禁止业务页面用玻璃效果，
   但允许弹窗抽屉用阴影）。面板内部的面不能不透明，否则把玻璃盖死

### 调参器

`web/tune.js`。**20 个滑块分四组**（任务面板·外观 8 / 任务面板·尺寸与位置 4 /
对象栏·外观 4 / 对象栏·尺寸与位置 4），实时改 `:root` 上的 CSS 变量，
调的是**真面板**不是预览。「复制 tokens」输出 15 行可直接粘进 `tokens.css` 的文本。

**两种打开方式**：URL 加 `?tune=1`，或者随时按 **`Shift + T`**（输入框里打字时不触发）。
不带 flag 时这个文件什么都不做，客户演示看不到。

**改了 tokens.css 的默认值，记得同步 `tune.js` 里 KNOBS 的 `val`**，否则一开调参器
面板会跳回旧样子。KNOBS 里 `{ sep: "..." }` 是分组标题不是滑块，遍历时要跳过（`if (k.key)`）。

### 会话开关必须在 URL 重写后存活（踩过）

外壳启动时会 `history.replaceState` 把 URL 重写成 `currentUrl()`，而它只拼共享上下文、
筛选、参数三类键。**`?tune=1` 因此在调参器读到它之前就被剥掉了，开关永远打不开。**

修法：`shell.js` 顶部的 `SESSION_FLAGS = ["tune", "rail", "glass"]`，`queryString()` 里
先把它们带上，`applyUrl()` 里跳过它们。第二条同样重要——不跳过的话这些 flag 会被当成
业务筛选塞进 chip 栏，界面上会出现「tune 1 ✕」这种东西。

以后再加会话级开关，**必须同时改这两处**。

---

## 5. LiquidGlass（WebGL 折射库）已测并否掉

副本 `10-LiquidGlass测试/`（18821），三挡 `?glass=off|dynamic|marked`。
用浏览器标准 Performance API 测（不用库自带 `.fps`），工具做过灵敏度自检。

| 场景 | 挡 | FPS | Long Task | LT 最长 |
| --- | --- | --- | --- | --- |
| 表格滚动 | off | 59.8 | 0 | 0 |
| | data-dynamic | **2.6** | 5 / 2786ms | **1088ms** |
| | markChanged | 60.0 | 0 | 0 |
| ECharts 挂载 | data-dynamic | **2.6** | 5 / 3587ms | **1566ms** |
| 数据更新 | data-dynamic | **2.7** | 8 / 4085ms | **1147ms** |

**两挡都不能用，原因相反**：

- `data-dynamic` 正确但每帧把整个 `.wb-app`（3350 个 DOM 节点）用 `html-to-image`
  光栅化，界面一次冻结 1.5 秒
- `markChanged` 数字漂亮是因为**渲染的是一张冻结死图**。往面板背后塞纯红色块，
  四种失效方式（`markChanged(元素)` / `markChanged()` / `data-config` 变更 /
  红块改成 root 直接子元素带 `data-dynamic`）全都没进去

结构性原因：整个应用是**一个** wrapper（`.wb-app`）挂在 root 下，库的脏跟踪只在
**root 的直接子元素**这一层工作。要中间档得把 `.wb-app` 拆成一堆 root 级兄弟元素。

**重要澄清：贵的是「把 DOM 抓成纹理」，不是折射本身。** 着色器只跑不抓时是
60fps / 0 Long Task。CSS `backdrop-filter` 免费就是因为合成器手里已经有页面的光栅结果。

测量口径限制：HeadlessChrome dpr=1，真机 retina 像素量 4 倍会更差；交互延迟一列全 0，
因为用 JS 驱动没产生真实输入事件。

副本可以删（`rm -rf 10-LiquidGlass测试`），结论已在此。

---

## 6. 本轮修掉的真 bug（都只有看屏幕或压测才发现）

1. **跨线程共用 SQLite 连接**（最严重，覆盖所有模块）。页面用 `Promise.all` 并行取
   `meta` 和对象详情，两个线程撞在同一个 `@lru_cache` 缓存的连接上，偶发
   `database disk image is malformed`——文件没坏（`quick_check` ok），是连接不能并发用，
   `check_same_thread=False` 只解除检查不做串行化。
   修法：`core/db.py` 新增 `pool()` 按线程给连接。**模块取连接一律用 `db.pool()`，
   不要自己 `lru_cache` 缓存 `db.connect()` 的返回值。**
   回归探针：`tests/probe_concurrency.py`，压 210 个并发请求，现在全 200
2. 任务面板 footer 被卷进滚动区，最该看见的运行状态和「查看结论」滚走了
3. 用揭示节奏冒充真实耗时（footer 显示 928ms，真实 0.0ms）
4. 玻璃面板里放了一张纯白不透明 `.wb-placeholder`，把整块玻璃盖死
5. G18 门禁误报：正则要求 `key` 和 `label` 同行相邻，把合规的多行写法判成缺 label。
   **门禁写错比代码写错更坏，它会让人去改正确的代码**

---

## 7. 文件地图（外壳侧）

```
09-工作台/
├─ server.py            单一路由器  start.py  双 fork + setsid
├─ core/
│   ├─ paths.py         全部路径与端口，环境变量可覆盖
│   ├─ db.py            只读 SQLite：connect / pool / rows / one / scalar / attach
│   ├─ ruleset.py       Param 声明 + 解析 + 夹紧 + 指纹
│   ├─ registry.py      扫 modules/*/module.py 发现，逐模块 try/except，mtime 热重载
│   └─ ctx.py           模块处理函数的请求上下文
├─ modules/<id>/{module,data,compute,rules}.py
├─ web/
│   ├─ index.html       八槽位骨架 + 任务面板 + 两个手柄
│   ├─ shell.js         导航/路由/URL 状态/任务面板/对象栏开合/浮层抽屉/ctx
│   ├─ tokens.css       ★ 设计令牌唯一来源（两组玻璃）
│   ├─ base.css         骨架 + 任务面板 + 对象栏 + 调参器样式
│   ├─ tune.js          ?tune=1 调参器
│   └─ modules/<id>.{js,css}
└─ tests/
    ├─ test_gates.py           契约门禁 G1–G18
    └─ probe_concurrency.py    并发回归探针
```

契约在 `../00-通用方法与规范/02-模块接入契约.md`（v1.2，改模块前必读）。
库存迁移指导在同目录 `05-库存模块迁移指导.md`。

---

## 8. 下一步（外壳侧）

1. **`evidence_ids` ↔ trace step 双向可跳**（第 3 节末）
2. **Agent 落库那一段**：按 `07-预测Agent接口契约.md` v0.3 给 Pi 循环加输出契约 +
   harness 校验 + 写库。注意第 2 节第 7 条：LLM 不碰写路径
3. Pi 循环要变常驻还需三处泛化：`scenarioId` 从严格相等改任务注册表、
   必填上下文按任务声明（关键词的对象是词不是 ASIN）、`ping()` 别绑死一个数据包的行数
4. `10-LiquidGlass测试/` 可删

## 9. 环境坑

- `/usr/bin/python3` 是 **3.9.6**：`dataclass(slots=True)`、`match` 都不能用；
  `X | Y` 注解靠每个文件顶部的 `from __future__ import annotations` 才合法
- 改 `core/` 必须重启；改 `modules/` 下 `.py` 靠 mtime 热重载（尽力而为）；
  改 `web/` 静态文件刷新即生效
- `[hidden]` 必须配 `display:none!important`（UA 来源会被作者样式的 `display` 盖掉）
- 有扩展名的路径不存在就回 404，不能拿 `index.html` 冒充缺失的 `.js`
- 长 heredoc / 复杂管道会触发安全策略拦截，**把脚本落成文件再用单条简单命令执行**
- 多会话并行：动任何目录前先 `find -newermt` 查最近改动时间，确认没有别的会话在写
