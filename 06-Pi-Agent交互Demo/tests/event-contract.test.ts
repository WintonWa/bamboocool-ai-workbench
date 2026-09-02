import assert from "node:assert/strict";
import test from "node:test";
import { EventAdapter, publicError } from "../src/event-adapter.ts";

test("maps Pi tool events to a safe paired execution trace", () => {
  const adapter = new EventAdapter("run_test");
  const started = adapter.adapt({
    type: "tool_execution_start",
    toolCallId: "tool_1",
    toolName: "forecast_child_sales_daily",
    args: { child_asin: "B0CGLY2BPZ" },
  } as any);
  const completed = adapter.adapt({
    type: "tool_execution_end",
    toolCallId: "tool_1",
    toolName: "forecast_child_sales_daily",
    result: { details: { forecast: { p50Units: 4933, p10Units: 4193, p90Units: 5673 } } },
    isError: false,
  } as any);
  assert.equal(started?.type, "step.started");
  assert.equal(completed?.type, "step.completed");
  assert.equal(started?.stepId, completed?.stepId);
  const serialized = JSON.stringify([started, completed]);
  assert.doesNotMatch(serialized, /SELECT|\/Users\//);
  assert.match(serialized, /4,933/);
});

test("maps text deltas without exposing cumulative Pi messages", () => {
  const adapter = new EventAdapter("run_test");
  const event = adapter.adapt({
    type: "message_update",
    assistantMessageEvent: { type: "text_delta", delta: "结论" },
    message: { role: "assistant", content: [] },
  } as any);
  assert.deepEqual(event, { type: "answer.delta", runId: "run_test", delta: "结论" });
});

test("returns stable public errors", () => {
  assert.equal(publicError(new Error("missing API key")).code, "PI_AUTH_UNAVAILABLE");
  assert.equal(publicError(new Error("provider model missing")).code, "PI_MODEL_UNAVAILABLE");
  assert.equal(publicError(new Error("/Users/private/path failed")).message, "Agent 运行失败，请检查本地服务日志后重试。");
});
