import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { DatabaseSync } from "node:sqlite";
import test from "node:test";
import {
  diagnoseDemandToolTrace,
  runDemandForecast,
  safeDemandModelError,
  safeDemandToolError,
} from "../src/demand-forecast-agent.ts";
import {
  FORBIDDEN_INPUT_KEYS,
  beginDemandForecastRun,
  expectedForecastDates,
  failDemandForecastRun,
  finishDemandForecastStep,
  forecastSegments,
  loadDemandForecastFacts,
  readDemandForecastRunStatus,
  startDemandForecastStep,
  validateDailyForecast,
  validateDailyForecastSegment,
} from "../src/demand-forecast.ts";

const SAMPLE = "B0B3LM36WB";

test("事实载荷只含职责修订允许的客观输入", () => {
  const facts = loadDemandForecastFacts(SAMPLE);
  const raw = JSON.stringify(facts);
  for (const key of FORBIDDEN_INPUT_KEYS) assert.doesNotMatch(raw, new RegExp(`"${key}"`));
  assert.equal((facts.future_plan.days as unknown[]).length, 90);
  assert.ok(Number(facts.observable_metrics.history_observed_days) >= 700);
});

test("逐日门禁拒绝缺行、错日期与分位倒挂", () => {
  const facts = loadDemandForecastFacts(SAMPLE);
  const dates = expectedForecastDates(facts.data_as_of);
  const valid = dates.map((forecast_date) => ({
    forecast_date, p10_units: 8, p50_units: 10, p90_units: 12, baseline_units: null,
  }));
  assert.deepEqual(validateDailyForecast(facts, valid), []);
  assert.match(validateDailyForecast(facts, valid.slice(1)).join("；"), /必须正好 90 行/);
  const reversed = valid.map((item, index) => index === 3 ? { ...item, p10_units: 14 } : item);
  assert.match(validateDailyForecast(facts, reversed).join("；"), /p10≤p50≤p90/);
  const firstSegment = valid.slice(0, 15);
  assert.equal(forecastSegments(facts.data_as_of).length, 6);
  assert.deepEqual(validateDailyForecastSegment(facts, 1, firstSegment), []);
  assert.match(validateDailyForecastSegment(facts, 2, firstSegment).join("；"), /日期应为/);
});

test("工具诊断区分未调用、工具拒绝和成功但未登记", () => {
  const tool = "load_sales_inventory_history";
  assert.equal(
    diagnoseDemandToolTrace(tool, { starts: 0, ends: 0, successfulEnds: 0, errors: [], modelErrors: [] }, false),
    `模型返回但没有发起工具调用：${tool}`,
  );
  const error = safeDemandToolError({
    isError: true,
    content: [{ type: "text", text: "参数不符合当前运行对象" }],
  });
  assert.equal(error, "参数不符合当前运行对象");
  assert.equal(
    diagnoseDemandToolTrace(tool, { starts: 1, ends: 1, successfulEnds: 0, errors: [error], modelErrors: [] }, false),
    "工具调用被拒绝：参数不符合当前运行对象",
  );
  assert.equal(
    diagnoseDemandToolTrace(tool, { starts: 1, ends: 1, successfulEnds: 1, errors: [], modelErrors: [] }, false),
    `工具调用成功但结果未登记：${tool}`,
  );
  assert.equal(
    diagnoseDemandToolTrace(tool, { starts: 1, ends: 1, successfulEnds: 1, errors: [], modelErrors: [] }, true),
    null,
  );
  const modelError = safeDemandModelError('402: {"message":"Insufficient Balance"}');
  assert.equal(modelError, "模型服务余额不足（402）");
  assert.equal(
    diagnoseDemandToolTrace(tool, { starts: 0, ends: 0, successfulEnds: 0, errors: [], modelErrors: [modelError] }, false),
    "模型请求失败：模型服务余额不足（402）",
  );
});

test("运行中步骤可读，状态词固定为加载中、完成、失败", () => {
  const dir = mkdtempSync(join(tmpdir(), "bamboo-demand-status-"));
  try {
    const dbPath = join(dir, "forecast_agent.sqlite");
    const facts = loadDemandForecastFacts(SAMPLE);
    const handle = beginDemandForecastRun({ facts, trigger: "manual", dbPath });
    let status = readDemandForecastRunStatus({ runId: handle.run_id, dbPath });
    assert.equal(status.run?.status, "加载中");
    assert.equal(status.run?.current_step, 0);
    const loading = startDemandForecastStep({
      runId: handle.run_id, stepSeq: 1, tool: "test", label: "测试步骤",
      detail: "真实运行中", sources: ["测试事实"], dbPath,
    });
    status = readDemandForecastRunStatus({ runId: handle.run_id, dbPath });
    assert.equal(status.steps[0]?.status, "加载中");
    assert.equal(status.steps[0]?.duration_ms, null);
    finishDemandForecastStep({ runId: handle.run_id, step: loading, status: "完成", detail: "测试完成", durationMs: 37, dbPath });
    status = readDemandForecastRunStatus({ runId: handle.run_id, dbPath });
    assert.equal(status.steps[0]?.status, "完成");
    assert.equal(status.steps[0]?.duration_ms, 37);
    failDemandForecastRun(handle.run_id, "测试失败原因", dbPath);
    status = readDemandForecastRunStatus({ runId: handle.run_id, dbPath });
    assert.equal(status.run?.status, "失败");
    assert.equal(status.run?.error, "测试失败原因");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("同一 run 原子写入90天、五因子、十二步骤并保留前序链", async () => {
  const dir = mkdtempSync(join(tmpdir(), "bamboo-demand-agent-"));
  try {
    const dbPath = join(dir, "forecast_agent.sqlite");
    const exportPath = join(dir, "forecast_agent_latest.json");
    const first = await runDemandForecast({ childAsin: SAMPLE, trigger: "manual", fake: true, dbPath, exportPath });
    assert.equal(first.ok, true);
    assert.equal(first.daily_written, 90);
    assert.equal(first.factors_written, 5);
    assert.equal(first.steps.length, 12);

    const db = new DatabaseSync(dbPath, { readOnly: true });
    try {
      const runId = first.run_id!;
      const count = (table: string) => Number((db.prepare(`SELECT COUNT(*) n FROM ${table} WHERE run_id=?`).get(runId) as { n: number }).n);
      assert.equal(count("fact_child_forecast_agent_daily"), 90);
      assert.equal(count("fact_child_forecast_judgment_factor"), 5);
      assert.equal(count("fact_child_forecast_agent_step"), 12);
      const run = db.prepare("SELECT * FROM fact_child_forecast_agent_run WHERE run_id=?").get(runId) as Record<string, unknown>;
      assert.equal(run.status, "completed");
      assert.equal(run.horizon_days, 90);
      assert.match(String(run.created_at), /\+08:00$/);
    } finally {
      db.close();
    }

    const second = await runDemandForecast({ childAsin: SAMPLE, trigger: "weekly", fake: true, dbPath, exportPath });
    assert.notEqual(second.run_id, first.run_id);
    assert.equal(second.output!.run.prev_run_id, first.run_id);
    const exported = JSON.parse(readFileSync(exportPath, "utf8"));
    assert.equal(exported.run.run_id, second.run_id);
    assert.equal(exported.daily.length, 90);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("HTTP 契约返回90天、五因子与顺序执行步骤摘要", async () => {
  const dir = mkdtempSync(join(tmpdir(), "bamboo-demand-api-"));
  try {
    process.env.BAMBOO_AGENT_FAKE = "1";
    process.env.BAMBOO_FORECAST_DB = join(dir, "forecast_agent.sqlite");
    process.env.BAMBOO_FORECAST_JSON = join(dir, "latest.json");
    const { createDemoServer } = await import("../src/server.ts");
    const server = createDemoServer();
    try {
      await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
      const port = (server.address() as { port: number }).port;
      const response = await fetch(`http://127.0.0.1:${port}/api/agent/demand-forecast`, {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ childAsin: SAMPLE, trigger: "manual" }),
      });
      const payload = await response.json();
      assert.equal(response.status, 200);
      assert.equal(payload.ok, true);
      assert.equal(payload.daily_written, 90);
      assert.equal(payload.factors_written, 5);
      assert.deepEqual(payload.steps.map((step: { step_seq: number }) => step.step_seq), [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]);

      const statusResponse = await fetch(`http://127.0.0.1:${port}/api/agent/demand-forecast/status?runId=${payload.run_id}`);
      const statusPayload = await statusResponse.json();
      assert.equal(statusResponse.status, 200);
      assert.equal(statusPayload.run.status, "完成");
      assert.equal(statusPayload.run.total_steps, 12);
      assert.equal(statusPayload.steps.length, 12);
      assert.equal("tool" in statusPayload.steps[0], false);

      const bad = await fetch(`http://127.0.0.1:${port}/api/agent/demand-forecast`, {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ childAsin: SAMPLE, trigger: "hourly" }),
      });
      const badPayload = await bad.json();
      assert.equal(bad.status, 400);
      assert.equal(badPayload.daily_written, 0);
    } finally {
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  } finally {
    delete process.env.BAMBOO_AGENT_FAKE;
    delete process.env.BAMBOO_FORECAST_DB;
    delete process.env.BAMBOO_FORECAST_JSON;
    rmSync(dir, { recursive: true, force: true });
  }
});
