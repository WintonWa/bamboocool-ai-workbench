# Pi Agent Liquid Glass 长页 QA

日期：2026-08-31  
范围：`web/index.html`、`web/app.css`、`web/app.js`

## 结果

- 自动化测试：通过，13/13；
- 数据质量测试：通过，3/3；
- JavaScript 语法检查：通过；
- HTTP 运行检查：`/`、`/app.css`、`/app.js` 均返回 200；
- Agent 健康检查：数据库 ready，Pi configured，场景为 `forecast-child-sales-inventory-90d`；
- 静态 DOM 契约：全部既有交互 ID 恰好保留一次；
- 文案边界检查：页面不含参考图中的 WebGL、GLSL 或 iOS Liquid Glass 示例文案；
- Git 空白检查：通过。

## 响应式与可访问性检查

源码检查确认：

- 760px 与 520px 两级窄屏规则存在；
- 390px 目标布局使用单列和 14px 页面边距；
- Live Agent 表单、选择器和发送按钮保持触控尺寸；
- `prefers-reduced-motion` 会关闭滚动和玻璃倾斜动效；
- 键盘焦点样式覆盖链接、按钮、选择器和输入框；
- Hero 与底部 CTA 均可滚动并聚焦到 Agent 输入框。

## 浏览器视觉验收限制

本次会话的应用内浏览器运行时未暴露任何可控制浏览器实例，因此未能生成桌面与 390px 的实际渲染截图，也未宣称完成截图对比。代码、HTTP、事件契约和响应式规则已完成验证。

建议人工打开 <http://127.0.0.1:18812/> 后重点查看：

1. 390px 下 Hero 标题是否保持 2–3 行且无裁切；
2. Liquid Glass 按钮的高光、色散边缘与指针跟随是否自然；
3. 九个内容段落的节奏是否避免重复卡片墙；
4. Live Agent 交互区在桌面和手机上是否无横向溢出；
5. 执行完整场景后，九步轨迹、答案、停止与重跑状态是否清晰。

