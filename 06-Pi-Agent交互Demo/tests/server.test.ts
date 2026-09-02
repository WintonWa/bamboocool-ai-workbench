import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

process.env.BAMBOO_AGENT_FAKE = "1";
const { createDemoServer } = await import("../src/server.ts");

test("serves health, 342 child choices, UI and a nine-step fixture run", async (t) => {
  const server = createDemoServer();
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  t.after(() => new Promise<void>((resolve) => server.close(() => resolve())));
  const address = server.address();
  assert.ok(address && typeof address === "object");
  const base = `http://127.0.0.1:${address.port}`;

  const health = await fetch(`${base}/api/health`).then((response) => response.json());
  assert.equal(health.status, "ok");
  assert.equal(health.database, "ready");
  assert.equal(health.mode, "fixture");
  assert.equal(health.scenario, "forecast-child-sales-inventory-90d");

  const payload = await fetch(`${base}/api/children`).then((response) => response.json());
  assert.equal(payload.children.length, 342);
  const mapped = payload.children.find((item: any) => !item.isGoldenSample);

  const html = await fetch(`${base}/`).then((response) => response.text());
  assert.match(html, /预测子 ASIN/);

  const response = await fetch(`${base}/api/agent/run`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      sessionId: "session_12345678",
      scenarioId: "forecast-child-sales-inventory-90d",
      childAsin: mapped.childAsin,
      message: "预测未来90天销量，并判断什么时候补货",
    }),
  });
  assert.equal(response.headers.get("content-type"), "application/x-ndjson; charset=utf-8");
  const events = (await response.text()).trim().split("\n").map((line) => JSON.parse(line));
  assert.equal(events[0].type, "run.started");
  assert.equal(events.at(-1).type, "run.completed");
  assert.equal(events.filter((event) => event.type === "step.started").length, 9);
  const answer = events.find((event) => event.type === "answer.delta").delta;
  assert.match(answer, /演示映射/);
  assert.match(answer, /需求预测/);
  assert.match(answer, /补货建议/);
  assert.doesNotMatch(JSON.stringify(events), /SELECT|\/Users\//);
});

test("rejects invalid scenarios before opening a stream", async (t) => {
  const server = createDemoServer();
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  t.after(() => new Promise<void>((resolve) => server.close(() => resolve())));
  const address = server.address();
  assert.ok(address && typeof address === "object");
  const response = await fetch(`http://127.0.0.1:${address.port}/api/agent/run`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      sessionId: "session_12345678",
      scenarioId: "arbitrary-sql",
      childAsin: "B0CGLY2BPZ",
      message: "run",
    }),
  });
  assert.equal(response.status, 400);
  assert.equal((await response.json()).error, "INVALID_SCENARIO");
});

test("exposes an asynchronous keyword Loop task without publishing business results", async (t) => {
  const dir = mkdtempSync(join(tmpdir(), "bamboo-keyword-loop-http-"));
  process.env.BAMBOO_KEYWORD_LOOP_DB = join(dir, "loop.sqlite");
  const server = createDemoServer();
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  t.after(() => new Promise<void>((resolve) => server.close(() => {
    delete process.env.BAMBOO_KEYWORD_LOOP_DB;
    rmSync(dir, { recursive: true, force: true });
    resolve();
  })));
  const address = server.address();
  assert.ok(address && typeof address === "object");
  const base = `http://127.0.0.1:${address.port}`;
  const started = await fetch(`${base}/api/agent/keyword/loop-runs`, {
    method: "POST", headers: { "content-type": "application/json" }, body: "{}",
  });
  assert.equal(started.status, 202);
  const first = await started.json();
  assert.match(first.run.run_id, /^keyword-loop-/);
  let status: any;
  for (let i = 0; i < 100; i += 1) {
    status = await fetch(`${base}/api/agent/keyword/loop-runs/status`).then((response) => response.json());
    if (status.run?.status !== "running") break;
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
  assert.equal(status.run.status, "completed");
  assert.equal(status.run.accepted_count, 20);
  assert.match(status.run.message, /未发布业务结果/);
  assert.equal(status.steps.length, 6);
});
