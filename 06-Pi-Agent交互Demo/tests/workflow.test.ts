import assert from "node:assert/strict";
import test from "node:test";
import { attachSequentialToolWorkflow } from "../src/pi-session.ts";
import { ALLOWED_TOOL_NAMES } from "../src/tools/index.ts";

test("exposes only the next tool and advances after a successful result", () => {
  let activeTools: string[] = [];
  let listener: (event: any) => void = () => {};
  const workflow = attachSequentialToolWorkflow({
    setActiveToolsByName(names: string[]) {
      activeTools = [...names];
    },
    subscribe(nextListener: (event: any) => void) {
      listener = nextListener;
      return () => { listener = () => {}; };
    },
  } as any);

  assert.deepEqual(activeTools, [ALLOWED_TOOL_NAMES[0]]);
  listener({ type: "tool_execution_end", toolName: ALLOWED_TOOL_NAMES[0], isError: true });
  assert.deepEqual(activeTools, [ALLOWED_TOOL_NAMES[0]]);
  listener({ type: "tool_execution_end", toolName: ALLOWED_TOOL_NAMES[2], isError: false });
  assert.deepEqual(activeTools, [ALLOWED_TOOL_NAMES[0]]);

  for (let index = 0; index < ALLOWED_TOOL_NAMES.length; index += 1) {
    listener({ type: "tool_execution_end", toolName: ALLOWED_TOOL_NAMES[index], isError: false });
    assert.deepEqual(activeTools, index + 1 < ALLOWED_TOOL_NAMES.length ? [ALLOWED_TOOL_NAMES[index + 1]] : []);
  }
  assert.equal(workflow.expectedTool(), null);

  workflow.reset();
  assert.deepEqual(activeTools, [ALLOWED_TOOL_NAMES[0]]);
  workflow.dispose();
});
