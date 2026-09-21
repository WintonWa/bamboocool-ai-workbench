# 22 · 广告标准决策单视觉优化

生成方式：内置 Image 2 图片编辑模式。

参考图：用户提供的现有「广告策略建议与审批」页面截图。

## 主提示词

```text
Use case: ui-mockup
Asset type: high-fidelity desktop web UI redesign reference for an existing Chinese Amazon advertising operations workbench.

Redesign only the “广告策略建议与审批” module into a clearer, repeatable standard decision proposal card driven by a fixed Agent data contract. The same component must plausibly support bid changes, budget changes, negative keywords, pausing objects, creating objects, match type changes, or observation-only recommendations.

Show one fully expanded pending proposal card and the top of a second compact proposal row below it. The expanded card has a compact summary header, a strong “当前值 → 目标值” focal point, and structured “动作 / 原因 / 预期结果” areas. Preserve the contract's semantic order and fields; do not invent new business information.

Make “$1.87 → $2.15” the single strongest element, with a restrained neutral “上调 15%” annotation. Preserve the long advertising object name, adjustment goal, Agent rationale, guardrail, three-column monitoring table, time threshold, volume threshold, trigger rule, pass rule, failure handling, source, and approval actions.

Use a pristine light-mode B2B decision workbench: Swiss rational system sans, precise grid, neutral white panels, light gray separators, near-black text, restrained metadata, small radii, hairline borders, and semantic colors only for real states. No gradients, glassmorphism, glowing backgrounds, decorative shadows, fake charts, illustrations, or stock imagery. Do not use three equal columns. Avoid dead empty space. Keep missing contract values visible as muted “本次运行未给出”, never blank.

Keep all Chinese text Simplified Chinese and retain “mens boxer briefs” exactly. Preserve business meaning, field completeness, approval workflow, and standardized Agent-contract nature. Change information hierarchy, spacing, card structure, and visual emphasis only.
```

## 最终校正提示词

```text
Make only two targeted corrections: replace “行动建议” with the exact contract label “动作”; change the green “↑ 上调 15%” annotation to neutral near-black/dark gray because adjustment direction is not a positive-result state. Preserve everything else exactly.
```
