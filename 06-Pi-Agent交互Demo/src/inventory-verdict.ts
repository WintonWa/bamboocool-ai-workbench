import { execFileSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { DatabaseSync } from "node:sqlite";

const SRC_DIR = dirname(fileURLToPath(import.meta.url));
export const PROJECT_ROOT = resolve(SRC_DIR, "..");
export const WORKBENCH_ROOT = resolve(PROJECT_ROOT, "..", "09-工作台");
export const DEFAULT_VERDICT_DB = resolve(WORKBENCH_ROOT, "modules/inventory/derived/verdict_agent.sqlite");
export const DEFAULT_EXPORT_JSON = resolve(WORKBENCH_ROOT, "modules/inventory/derived/verdict_agent_latest.json");
const FACT_BRIDGE = resolve(PROJECT_ROOT, "scripts/inventory_verdict_facts.py");

export const BLOCKS = ["safety", "stockout", "in_transit", "overstock", "storage_fee"] as const;
export const DEMO_ORDER = ["safety", "in_transit", "stockout", "overstock", "storage_fee"] as const;
const ALLOWED_REFS = new Set(["inventory", "projection", "demand", "aging", "fee", "risks"]);
const STATES: Record<string, readonly string[]> = {
  safety: ["安全", "偏紧", "不安全"],
  stockout: ["窗口内不断货", "即将断货", "已断货"],
  in_transit: ["正常", "来不及", "有逾期", "无在途"],
  overstock: ["正常", "偏多", "积压"],
  storage_fee: ["正常", "偏高"],
};
const FORBIDDEN = ["不作为判断依据", "不代表客户经营事实", "阈值待确认", "仅供参考", "cannot_absorb", "demo_default", "synthetic_demo"];

export function shanghaiTimestamp(now = new Date(), withOffset = false): string {
  // 现有种子库 created_at 是上海本地无时区格式；继续使用同一可排序口径，
  // 避免 UTC 前一天字符串被错误判成更旧的 run。
  // withOffset=true 追加固定 +08:00（Asia/Shanghai 自 1991 年起无夏令时），
  // 供预测判断契约 §1.3 要求的「ISO 8601 带偏移」使用。
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit",
    hourCycle: "h23",
  }).formatToParts(now);
  const value = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  const stamp = `${value.year}-${value.month}-${value.day}T${value.hour}:${value.minute}:${value.second}`;
  return withOffset ? `${stamp}+08:00` : stamp;
}

export type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue };
export type ContractFact = {
  block: string;
  expected_state: string;
  refs: string[];
  numbers: Record<string, JsonValue>;
};
export type VerdictFacts = {
  ok: boolean;
  child_asin: string;
  data_as_of: string;
  forecast_run_id: string;
  decision_context: Record<string, JsonValue>;
  contract_facts: ContractFact[];
};
export type VerdictItem = {
  block: string;
  ord: number;
  state: string;
  verdict: string;
  because: string | null;
  refs: string[];
  numbers: Record<string, JsonValue>;
};
export type VerdictRun = {
  run_id: string;
  child_asin: string;
  run_date: string;
  data_as_of: string;
  trigger: "manual";
  model_version: string;
  method_version: "inv-verdict-v1";
  input_forecast_run_id: string;
  created_at: string;
};

function stable(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stable).join(",")}]`;
  if (value && typeof value === "object") {
    const object = value as Record<string, unknown>;
    return `{${Object.keys(object).sort().map((key) => `${JSON.stringify(key)}:${stable(object[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

export function loadVerdictFacts(childAsin = "B0B3LM36WB"): VerdictFacts {
  const stdout = execFileSync("/usr/bin/python3", [FACT_BRIDGE, childAsin], {
    cwd: WORKBENCH_ROOT,
    encoding: "utf8",
    maxBuffer: 4 * 1024 * 1024,
  });
  const facts = JSON.parse(stdout) as VerdictFacts;
  if (!facts.ok) throw new Error(`没有可用于结论 Agent 的库存事实：${childAsin}`);
  return facts;
}

export function validateVerdictItems(facts: VerdictFacts, items: VerdictItem[]): string[] {
  const errors: string[] = [];
  if (items.length !== 5) errors.push(`必须正好提交 5 条，当前为 ${items.length} 条`);
  const seen = new Set<string>();
  const factByBlock = new Map(facts.contract_facts.map((fact) => [fact.block, fact]));
  for (const item of items) {
    if (!BLOCKS.includes(item.block as (typeof BLOCKS)[number])) {
      errors.push(`未知 block：${item.block}`);
      continue;
    }
    if (seen.has(item.block)) errors.push(`block 重复：${item.block}`);
    seen.add(item.block);
    const expectedOrd = DEMO_ORDER.indexOf(item.block as (typeof DEMO_ORDER)[number]) + 1;
    if (item.ord !== expectedOrd) errors.push(`${item.block}.ord 应为 ${expectedOrd}`);
    if (!STATES[item.block]?.includes(item.state)) errors.push(`${item.block}.state 不在词表内：${item.state}`);
    const contractFact = factByBlock.get(item.block);
    if (!contractFact) {
      errors.push(`${item.block} 没有页面同口径事实`);
      continue;
    }
    if (item.state !== contractFact.expected_state) {
      errors.push(`${item.block}.state 与页面计算不一致，应为 ${contractFact.expected_state}`);
    }
    if (item.block === "in_transit" && item.state === "有逾期") {
      errors.push("当前数据没有逾期事实，不得输出“有逾期”");
    }
    if (stable(item.numbers) !== stable(contractFact.numbers)) errors.push(`${item.block}.numbers 与页面数字不一致`);
    if (stable([...item.refs].sort()) !== stable([...contractFact.refs].sort())) errors.push(`${item.block}.refs 与契约事实不一致`);
    if (item.refs.some((ref) => !ALLOWED_REFS.has(ref))) errors.push(`${item.block}.refs 含未知引用`);
    const verdict = item.verdict.trim();
    if (!verdict || verdict.length > 160 || verdict.includes("\n")) errors.push(`${item.block}.verdict 必须是 160 字内的一句话`);
    const terminal = verdict.match(/[。！？]/g)?.length ?? 0;
    if (terminal !== 1 || !/[。！？]$/.test(verdict)) errors.push(`${item.block}.verdict 必须只有一个句末标点`);
    const text = `${item.verdict} ${item.because ?? ""}`;
    for (const phrase of FORBIDDEN) if (text.includes(phrase)) errors.push(`${item.block} 含禁用措辞：${phrase}`);
  }
  for (const block of BLOCKS) if (!seen.has(block)) errors.push(`缺少 block：${block}`);
  return [...new Set(errors)];
}

const SCHEMA = `
CREATE TABLE IF NOT EXISTS fact_child_verdict_run (
  run_id TEXT PRIMARY KEY, child_asin TEXT NOT NULL, run_date TEXT NOT NULL,
  data_as_of TEXT NOT NULL, trigger TEXT NOT NULL, model_version TEXT,
  method_version TEXT, input_forecast_run_id TEXT, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_verdict_run
  ON fact_child_verdict_run(child_asin, run_date DESC, created_at DESC);
CREATE TABLE IF NOT EXISTS fact_child_verdict_item (
  run_id TEXT NOT NULL, block TEXT NOT NULL, ord INTEGER NOT NULL,
  state TEXT NOT NULL, verdict TEXT NOT NULL, because TEXT, refs TEXT,
  numbers TEXT, PRIMARY KEY (run_id, block)
);`;

export function writeVerdictRun(
  facts: VerdictFacts,
  items: VerdictItem[],
  modelVersion: string,
  dbPath = DEFAULT_VERDICT_DB,
  exportPath = DEFAULT_EXPORT_JSON,
): { run: VerdictRun; items: VerdictItem[]; db_path: string; export_path: string } {
  const errors = validateVerdictItems(facts, items);
  if (errors.length) throw new Error(errors.join("；"));
  mkdirSync(dirname(dbPath), { recursive: true });
  const createdAt = shanghaiTimestamp();
  const compact = createdAt.replace(/[-:T]/g, "");
  const run: VerdictRun = {
    run_id: `${facts.child_asin}-${facts.data_as_of}-agent-${compact}`,
    child_asin: facts.child_asin,
    run_date: facts.data_as_of,
    data_as_of: facts.data_as_of,
    trigger: "manual",
    model_version: modelVersion,
    method_version: "inv-verdict-v1",
    input_forecast_run_id: facts.forecast_run_id,
    created_at: createdAt,
  };
  const db = new DatabaseSync(dbPath);
  try {
    db.exec(SCHEMA);
    db.exec("BEGIN IMMEDIATE");
    db.prepare(`INSERT INTO fact_child_verdict_run
      (run_id, child_asin, run_date, data_as_of, trigger, model_version, method_version, input_forecast_run_id, created_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`)
      .run(run.run_id, run.child_asin, run.run_date, run.data_as_of, run.trigger, run.model_version,
        run.method_version, run.input_forecast_run_id, run.created_at);
    const insert = db.prepare(`INSERT INTO fact_child_verdict_item
      (run_id, block, ord, state, verdict, because, refs, numbers)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?)`);
    for (const item of items) {
      insert.run(run.run_id, item.block, item.ord, item.state, item.verdict, item.because,
        JSON.stringify(item.refs), JSON.stringify(item.numbers));
    }
    db.exec("COMMIT");
  } catch (error) {
    try { db.exec("ROLLBACK"); } catch { /* transaction did not start */ }
    throw error;
  } finally {
    db.close();
  }
  const output = { contract_version: "inventory-verdict-v0.2", run, items: [...items].sort((a, b) => a.ord - b.ord) };
  mkdirSync(dirname(exportPath), { recursive: true });
  writeFileSync(exportPath, `${JSON.stringify(output, null, 2)}\n`, "utf8");
  return { run, items: output.items, db_path: dbPath, export_path: exportPath };
}
