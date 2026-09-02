import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { DatabaseSync } from "node:sqlite";
import {
  KeywordLoopTaskService, type KeywordLoopModelRunner,
} from "../src/keyword-loop-task.ts";

async function untilTerminal(service: KeywordLoopTaskService) {
  for (let i = 0; i < 100; i += 1) {
    const state = service.latest();
    if (state.run?.status !== "running") return state;
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
  throw new Error("关键词 Loop 测试超时");
}

test("Loop Smoke 真实走模型执行器，只写独立状态库并明确不发布", async () => {
  const dir = mkdtempSync(join(tmpdir(), "bamboo-keyword-loop-"));
  const dbPath = join(dir, "loop.sqlite");
  let resolveModel!: () => void;
  const gate = new Promise<void>((resolve) => { resolveModel = resolve; });
  let calls = 0;
  const modelRunner: KeywordLoopModelRunner = async (candidates, callbacks) => {
    calls += 1;
    callbacks.sessionReady("test/real-pi-shape");
    callbacks.promptStarted();
    await gate;
    return {
      modelVersion: "test/real-pi-shape",
      decisions: candidates.map((candidate) => ({
        candidate_id: String(candidate.candidate_id), event_type: null,
        continuity: null, label: null,
      })),
    };
  };
  const service = new KeywordLoopTaskService({ dbPath, modelRunner });
  try {
    const first = service.enqueue();
    const reused = service.enqueue();
    assert.equal(first.run.status, "running");
    assert.equal(reused.reused, true);
    assert.equal(reused.run.run_id, first.run.run_id);
    resolveModel();
    const done = await untilTerminal(service);
    assert.equal(calls, 1);
    assert.equal(done.run.status, "completed");
    assert.equal(done.run.accepted_count, 20);
    assert.equal(done.run.message, "Loop 演示完成，未发布业务结果");
    assert.deepEqual(done.steps.map((step: any) => step.status), Array(6).fill("completed"));
    const db = new DatabaseSync(dbPath, { readOnly: true });
    const tables = (db.prepare("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").all() as any[])
      .map((row) => row.name);
    db.close();
    assert.deepEqual(tables, ["fact_keyword_loop_run", "fact_keyword_loop_step"]);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("模型失败落安全终态并允许再次点击", async () => {
  const dir = mkdtempSync(join(tmpdir(), "bamboo-keyword-loop-fail-"));
  const dbPath = join(dir, "loop.sqlite");
  const service = new KeywordLoopTaskService({
    dbPath,
    modelRunner: async (_candidates, callbacks) => {
      callbacks.sessionReady("test/model");
      callbacks.promptStarted();
      throw new Error("HTTP 402 Insufficient Balance: secret provider detail");
    },
  });
  try {
    service.enqueue();
    const failed = await untilTerminal(service);
    assert.equal(failed.run.status, "failed");
    assert.equal(failed.run.error_code, "MODEL_BALANCE");
    assert.match(failed.run.message, /余额不足/);
    assert.doesNotMatch(JSON.stringify(failed), /secret provider detail/);
    const next = service.enqueue();
    assert.notEqual(next.run.run_id, failed.run.run_id);
    await untilTerminal(service);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
