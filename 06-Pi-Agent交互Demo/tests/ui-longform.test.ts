import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const html = readFileSync(new URL("../web/index.html", import.meta.url), "utf8");
const css = readFileSync(new URL("../web/app.css", import.meta.url), "utf8");
const script = readFileSync(new URL("../web/app.js", import.meta.url), "utf8");

test("renders the approved Pi Agent longform structure without reference-image filler copy", () => {
  assert.match(html, /让 Pi Agent 真正进入运营工作流/);
  for (const heading of [
    "角色与目标",
    "确认业务对象",
    "审计逐日历史",
    "还原真实需求",
    "评估经营驱动",
    "形成逐日预测",
    "推演库存三场景",
    "给出补货建议",
    "让执行过程可见",
  ]) {
    assert.match(html, new RegExp(heading));
  }
  assert.match(html, /LIVE AGENT DEMO/);
  assert.doesNotMatch(html, /WebGL|GLSL|iOS Liquid Glass/);
});

test("preserves every DOM contract used by the Agent runtime exactly once", () => {
  for (const id of [
    "serviceState",
    "childSelect",
    "productMeta",
    "quickPrompt",
    "conversation",
    "emptyState",
    "composer",
    "messageInput",
    "sendButton",
    "stopButton",
    "retryButton",
    "clearButton",
  ]) {
    assert.equal((html.match(new RegExp(`id=["']${id}["']`, "g")) || []).length, 1, id);
  }
});

test("includes responsive, reduced-motion and glass interaction rules", () => {
  assert.match(css, /@media \(max-width: 520px\)/);
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(css, /backdrop-filter:/);
  assert.match(script, /function setupPageEffects/);
  assert.match(script, /scrollIntoView/);
});

