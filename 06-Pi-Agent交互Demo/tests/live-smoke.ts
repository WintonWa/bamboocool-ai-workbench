import assert from "node:assert/strict";
import { createDemoServer } from "../src/server.ts";

delete process.env.BAMBOO_AGENT_FAKE;

const server = createDemoServer();
await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));

try {
  const address = server.address();
  assert.ok(address && typeof address === "object");
  const response = await fetch(`http://127.0.0.1:${address.port}/api/agent/run`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      sessionId: `session_${crypto.randomUUID()}`,
      scenarioId: "forecast-child-sales-inventory-90d",
      childAsin: "B0CGLY2BPZ",
      message: "预测这个子 ASIN 未来90天逐日销量，并判断库存是否足够、什么时候需要补货。",
    }),
  });
  assert.equal(response.status, 200);
  const events = (await response.text()).trim().split("\n").filter(Boolean).map((line) => JSON.parse(line));
  const tools = events.filter((event) => event.type === "step.started").map((event) => event.tool);
  const answer = events.filter((event) => event.type === "answer.delta").map((event) => event.delta).join("");
  assert.deepEqual(tools, [
    "route_demo_child_asin",
    "get_child_product_context",
    "audit_child_daily_history",
    "reconstruct_child_demand",
    "estimate_demand_drivers",
    "forecast_child_sales_daily",
    "get_child_inventory_supply",
    "project_child_inventory_daily",
    "recommend_child_replenishment",
  ]);
  assert.match(answer, /演示映射/);
  assert.match(answer, /P50/);
  assert.match(answer, /补货建议/);
  assert.doesNotMatch(answer, /并行调用|批量调用/);
  assert.equal(events.at(-1).type, "run.completed");
  console.log(JSON.stringify({ ok: true, tools, answerPreview: answer.slice(0, 260) }, null, 2));
} finally {
  await new Promise<void>((resolve) => server.close(() => resolve()));
}
