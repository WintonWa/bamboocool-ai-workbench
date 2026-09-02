import { createHash } from "node:crypto";
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

async function main(): Promise<void> {
  const db = new DatabaseSync(observationDb, { readOnly: true });
  let manifest: Record<string, string>;
  let families: Array<{ family_asin: string; in_quick_slot: number }>;
  try {
    manifest = Object.fromEntries((db.prepare("SELECT key, value FROM competitor_manifest").all() as Array<{ key: string; value: string }>)
      .map((row) => [row.key, row.value]));
    families = db.prepare(`SELECT family_asin, in_quick_slot FROM dim_competitor_family
      WHERE in_analysis_scope=1 ORDER BY in_quick_slot DESC, family_asin`).all() as typeof families;
  } finally { db.close(); }
  const thresholdKey = createHash("sha256").update(JSON.stringify(DEFAULT_COMPETITOR_THRESHOLDS)).digest("hex").slice(0, 12);
  const service = new CompetitorTaskService({ maxConcurrency: 3 });
  const tasks: Array<{ family_asin: string; task_id: string }> = [];
  try {
    for (const family of families) {
      const trigger = family.in_quick_slot ? "priority" : "scheduled";
      const request: CompetitorRunRequest = {
        trigger,
        family_asin: family.family_asin,
        window_from: manifest.window_from!,
        window_to: manifest.window_to!,
        data_as_of: manifest.as_of!,
        request_key: `cycle-${manifest.as_of}-${trigger}-${family.family_asin}-${thresholdKey}`,
        thresholds: { ...DEFAULT_COMPETITOR_THRESHOLDS },
      };
      const task = await service.enqueue(request);
      tasks.push({ family_asin: family.family_asin, task_id: task.task_id });
    }
    const results = [];
    for (const task of tasks) {
      let state = await service.get(task.task_id);
      while (state && !["done", "skipped", "failed"].includes(state.state)) {
        await new Promise((resolveWait) => setTimeout(resolveWait, 500));
        state = await service.get(task.task_id);
      }
      results.push({ family_asin: task.family_asin, ...state });
    }
    const counts = Object.fromEntries(["done", "skipped", "failed"].map((state) => [
      state, results.filter((item) => item.state === state).length,
    ]));
    process.stdout.write(`${JSON.stringify({ total: results.length, counts, results }, null, 2)}\n`);
    if (counts.failed) process.exitCode = 1;
  } finally {
    await service.dispose();
  }
}

main().catch((error) => {
  process.stderr.write(`${error instanceof Error ? error.stack ?? error.message : String(error)}\n`);
  process.exitCode = 1;
});
