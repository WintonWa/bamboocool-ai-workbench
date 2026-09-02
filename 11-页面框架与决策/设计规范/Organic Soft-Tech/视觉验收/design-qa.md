# Design QA — Organic Soft-Tech preview

## Target and evidence

- Source visual truth: `.stitch/reference/01-full.png`
- Supporting Stitch screens: `.stitch/reference/02-full.png`, `.stitch/reference/03-full.png`, `.stitch/reference/04-full.png`
- Design system: `.stitch/DESIGN.md` (`Organic Soft-Tech`)
- Implementation capture: `qa/implementation-1280x1228-v3.png`
- Full-view comparison: `qa/comparison-v3.png` (source left, implementation right)
- Focused shell/KPI comparison: `qa/comparison-header-metrics-v3.png` (source left, implementation right)
- Responsive evidence: `qa/implementation-mobile-390x844.png`
- State: default overview dashboard
- Source viewport: 2560 × 2456 at 2×, normalized to 1280 × 1228
- Implementation viewport: 1280 × 1228 at 1×

## Fidelity review

| Surface | Result | Notes |
| --- | --- | --- |
| Typography | Pass | Plus Jakarta Sans for display text and Be Vietnam Pro for body text, with Chinese system fallbacks. Weight contrast follows the Stitch reference. |
| Layout and spacing | Pass | Warm off-white shell, light rail, deep-green pill navigation, airy 8 px rhythm, rounded content panels, four KPI cards, and two-column intelligence area. |
| Color | Pass | Deep bamboo green, pale mint, warm ivory, muted gray-green, and one dark KPI card reproduce the selected Organic Soft-Tech palette. |
| Shape language | Pass | 20–28 px card radii, circular icon orbs, pill controls, and restrained shadows match the selected style. |
| Imagery | Pass | The operator portrait is the exact avatar asset referenced by the Stitch screen. |
| Product copy and data | Pass | Existing Chinese BambooCool content, data provenance labels, eight navigation destinations, and demo interactions were preserved rather than replaced with generic dashboard copy. |
| Responsive behavior | Pass | At 390 px the document reports no horizontal overflow (`scrollWidth` equals `clientWidth`); desktop and narrow layouts both retain reachable controls. |

## Iteration history

- V1: priority cards compressed too aggressively at 1280 px. Fixed by increasing the sidebar to 244 px and adjusting priority-card breakpoints.
- V2: the anomaly/suggestion area collapsed to one column too early, pushing AI suggestions below the initial viewport. Fixed by retaining the two-column layout until 1040 px.
- V3: desktop composition now keeps KPI, anomaly, and AI suggestion content visible together while preserving the existing product hierarchy.

## Interaction and engineering checks

- Navigation: Overview → Products & Inventory → Overview passed.
- KPI detail drawer: open and close passed.
- Bamboo AI search demo toast: passed.
- Weekly report draft generation: passed.
- Browser console: no warnings or errors.
- `npm run lint`: passed.
- `npm test`: build passed; 9/9 tests passed.

## Accepted differences

- The implementation is intentionally denser than the generic Stitch reference because it retains the real demo's priority strip, four KPI cards, anomaly aggregation, execution suggestions, and eight product sections.
- Chinese business copy and existing data-source labels take precedence over the English placeholder copy in Stitch.

No unresolved P0, P1, or P2 visual issues remain. The remaining density difference is an intentional P3 product decision.

final result: passed

## V4 — 产品与库存判断视图

### 判断映射

| 运营问题 | 数据关系 | 页面表达 |
| --- | --- | --- |
| 哪些子 ASIN 需要优先关注？ | 库存风险 × 覆盖天数 × 销量趋势 | 风险分布、优先关注列表、风险排序表 |
| 是否会缺货或积压，何时发生？ | 90天累计需求 × 当前可售 × 在途 × BD | 需求供给曲线、覆盖时间轴、关键日期 |
| 运营接下来需要确认什么？ | 当前判断 × 关键依据 × 缺失输入 | 右侧固定 AI 运营助手 |

### 视觉与响应式检查

- 1440 × 900：最高风险 `B088WF1PRW` 位于首屏第一优先级；断货窗口 `08/28`、BD、可售库存、在途和90天预测在同一阅读路径内。
- 1440 × 900：AI 助手固定在右侧，宽 304 px；页面无横向溢出，文档宽度 1425 px。
- 390 × 844：文档宽度 375 px，无页面级横向溢出；明细表在自身容器内横向滚动。
- 390 × 844：左侧导航转换为底部横向模块导航，八个模块保持可达；AI 助手移动到内容流下方。
- 风险颜色仅使用绿 / 黄 / 橙 / 红；面板使用小圆角、细边框和弱阴影。
- 已删除页面中的产品设计、能力验证和实现状态说明；保留数据来源、口径和业务不确定项。

### 交互与工程检查

- 优先关注列表切换子 ASIN：通过；关系图、关键日期和 AI 判断同步更新。
- 库存风险筛选：通过；选择“库龄风险”后显示 2 / 2 个子 ASIN。
- 筛选重置：通过；恢复 10 个子 ASIN。
- “查看依据”抽屉：通过；显示选中 ASIN 的连续判断链与库存组成。
- 窄屏模块导航：通过；可从总览进入产品与库存。
- 浏览器控制台：0 warning / 0 error。
- `npm test`：构建通过，9 / 9 测试通过。

### Impeccable 检测

- 检测脚本执行一次，报告 3 项 warning：两处既有旧页面侧边强调线，以及基础 CSS 的 Arial 回退声明。
- 这些警告均不属于本次 V4 产品与库存布局；Organic Soft-Tech 已在后置主题层使用项目指定的 Plus Jakarta Sans / Be Vietnam Pro，未为消除检测提示而覆盖项目设计系统。

V4 产品与库存页面：passed。

## V4.1 — 运营文案收口

- 全局复查八个页面、页面头、设置区、周报、数据来源抽屉及业务详情抽屉。
- 将“试点、边界、能力、Demo 目的、只建议、不做什么”等方案解释改为业务范围、判断状态、数据依据和下一步动作。
- 保留真实不确定项与数据来源标记，包括待确认阈值、到仓时间、安全库存、真实 / 推导 / 模拟口径。
- 新增界面文案回归测试，防止旧防御性句子重新进入前端。
- 1440 × 900：产品与库存、设置、广告分类和子 ASIN 广告分析检查通过；页面无横向溢出。
- 390 × 844：产品与库存页面无页面级横向溢出；明细表在自身容器内横向滚动。
- 主要交互：库存风险筛选、筛选重置、库存依据抽屉、模块导航、广告分析页签均通过。
- 浏览器控制台：0 warning / 0 error。
- `npm run lint`：通过；`npm test`：构建通过，10 / 10 测试通过。

V4.1：passed。

## V4.1.1 — 页面说明改为运营结论

- 八个页面标题下方不再解释页面用途，统一改为当前异常、风险、数据结果或待确认状态。
- 总览四个区块的说明同步改为当前指标与动作数量，不再描述聚合、展示或共创逻辑。
- 关键词日报、竞品日报、广告诊断、复盘、数据中心和设置区的结构说明同步收口为业务事实。
- 自动回归检查新增 8 类页面定位说明，防止“收拢到入口”“从子 ASIN 出发”“先看清广告组”等句子再次进入前端。
- 浏览器逐页核对八个页头，旧说明残留 0 项；控制台 0 warning / 0 error。
- `npm run lint`：通过；`npm test`：构建通过，10 / 10 测试通过。

V4.1.1：passed。

## V4.1.2 — 固定副标题改为业务字段

- 删除页面标题、模块标题和左侧导航下方的固定解释层；八个页面逐页检查均为 0 项残留。
- 关键词类型由关键词名称下方的附属文字改为独立“关键词分类”列，首行明确显示 `mens underwear / 品类大词`。
- 产品阶段、推广目标、库存组成、预测范围、数据来源、执行人和执行时间等重要信息均改为字段、状态或数据关系，不再使用弱化副标题承载。
- 删除“样例、规则补全、Demo 说明”等面向方案设计的可见文案；原始数据、第三方估算、系统计算和待确认项继续明确标记。
- 1440 × 900：产品与库存、关键词分析检查通过；页面无横向溢出。
- 680 × 900：产品、关键词、广告、数据中心和设置无页面级横向溢出；模块标题保持正常横排。
- `npm run lint`：通过；`npm test`：构建通过，11 / 11 测试通过。

V4.1.2：passed。
