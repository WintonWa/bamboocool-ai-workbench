import { DatabaseSync } from "node:sqlite";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import {
  DEFAULT_COMPETITOR_THRESHOLDS,
  type CompetitorRunRequest,
} from "../src/competitor-agent-v2.ts";
import { CompetitorTaskService } from "../src/competitor-task-service.ts";

const root = resolve(fileURLToPath(new URL("..", import.meta.url)));
const observationDb = resolve(root, "../08-竞品分析模块/02-数据构建/v0.1.0/competitor_demo.sqlite");

function manifest(): Record<string, string> {
  const db = new DatabaseSync(observationDb, { readOnly: true });
  try {
    return Object.fromEntries((db.prepare("SELECT key, value FROM competitor_manifest").all() as Array<{ key: string; value: string }>)
      .map((row) => [row.key, row.value]));
  } finally { db.close(); }
}

async function main(): Promise<void> {
  const familyAsin = (process.argv[2] ?? "B0CJ9QLVPP").trim().toUpperCase();
  const values = manifest();
  const request: CompetitorRunRequest = {
    trigger: "manual",
    family_asin: familyAsin,
    window_from: values.window_from!,
    window_to: values.window_to!,
    data_as_of: values.as_of!,
    requested_by: "local-demo",
    request_key: `${familyAsin}-${values.as_of}-manual-${Date.now()}`,
    thresholds: { ...DEFAULT_COMPETITOR_THRESHOLDS },
  };
  const service = new CompetitorTaskService({ maxConcurrency: 1 });
  try {
    let task = await service.enqueue(request);
    process.stderr.write(`已入队 ${task.task_id}：${task.state}\n`);
    while (!["done", "skipped", "failed"].includes(task.state)) {
      await new Promise((resolveWait) => setTimeout(resolveWait, 500));
      task = (await service.get(task.task_id))!;
      process.stderr.write(`任务状态：${task.state}\n`);
    }
    process.stdout.write(`${JSON.stringify(task, null, 2)}\n`);
    if (task.state === "failed") process.exitCode = 1;
  } finally {
    await service.dispose();
  }
}

main().catch((error) => {
  process.stderr.write(`${error instanceof Error ? error.stack ?? error.message : String(error)}\n`);
  process.exitCode = 1;
});
