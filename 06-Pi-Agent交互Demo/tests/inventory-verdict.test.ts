import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import {
  DEMO_ORDER,
  loadVerdictFacts,
  validateVerdictItems,
  writeVerdictRun,
  type VerdictItem,
} from "../src/inventory-verdict.ts";

function validItems(): { facts: ReturnType<typeof loadVerdictFacts>; items: VerdictItem[] } {
  const facts = loadVerdictFacts("B0B3LM36WB");
  const byBlock = new Map(facts.contract_facts.map((fact) => [fact.block, fact]));
  const items = DEMO_ORDER.map((block, index) => {
    const fact = byBlock.get(block)!;
    return {
      block,
      ord: index + 1,
      state: fact.expected_state,
      verdict: `${block} 的结论已按页面事实确认。`,
      because: "数字来自工作台同口径计算。",
      refs: fact.refs,
      numbers: fact.numbers,
    };
  });
  return { facts, items };
}

test("库存结论门禁接受五条同口径契约", () => {
  const { facts, items } = validItems();
  assert.deepEqual(validateVerdictItems(facts, items), []);
});

test("库存结论门禁拒绝被 Agent 改写的页面数字", () => {
  const { facts, items } = validItems();
  items[0] = { ...items[0], numbers: { ...items[0].numbers, cover_days_sellable: 99 } };
  assert.match(validateVerdictItems(facts, items).join("；"), /numbers 与页面数字不一致/);
});

test("通过门禁后原子写库并导出前端 JSON", () => {
  const { facts, items } = validItems();
  const dir = mkdtempSync(join(tmpdir(), "bamboo-verdict-"));
  try {
    const db = join(dir, "verdict.sqlite");
    const json = join(dir, "latest.json");
    const result = writeVerdictRun(facts, items, "test/model", db, json);
    assert.equal(result.items.length, 5);
    assert.equal(result.items[1]?.block, "in_transit");
    assert.equal(JSON.parse(readFileSync(json, "utf8")).run.model_version, "test/model");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
