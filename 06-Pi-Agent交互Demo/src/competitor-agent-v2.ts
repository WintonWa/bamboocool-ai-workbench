import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { DatabaseSync } from "node:sqlite";
import type {
  AttentionDecision,
  ChangeDecision,
  ConcurrencyDecision,
  EvidenceDecision,
  ImpactDecision,
  JsonObject,
  OutputDecision,
  RepresentationDecision,
  WorkflowSnapshot,
} from "./competitor-agent.ts";

export type {
  AttentionDecision,
  ChangeDecision,
  ConcurrencyDecision,
  EvidenceDecision,
  ImpactDecision,
  JsonObject,
  OutputDecision,
  RepresentationDecision,
  WorkflowSnapshot,
};

const SRC_DIR = dirname(fileURLToPath(import.meta.url));
export const COMPETITOR_V2_PROJECT_ROOT = resolve(SRC_DIR, "..");
export const COMPETITOR_V2_WORKBENCH_ROOT = resolve(COMPETITOR_V2_PROJECT_ROOT, "..", "09-工作台");
export const DEFAULT_COMPETITOR_V2_DB = resolve(
  COMPETITOR_V2_WORKBENCH_ROOT,
  "modules/competitor/derived/competitor_agent_state_v2.sqlite",
);
export const DEFAULT_COMPETITOR_V2_JSON = resolve(
  COMPETITOR_V2_WORKBENCH_ROOT,
  "modules/competitor/derived/competitor_agent_latest_v2.json",
);
const FACT_BRIDGE = resolve(COMPETITOR_V2_PROJECT_ROOT, "scripts/competitor_agent_facts.py");
export const COMPETITOR_V2_METHOD_VERSION = "competitor-agent-v2.2" as const;

export const COMPETITOR_V2_STAGES = [
  "judge_competitor_evidence",
  "judge_competitor_changes",
  "judge_family_representation",
  "judge_competitive_scope",
  "judge_change_concurrency",
  "judge_attention_and_impact",
  "judge_report_selection",
  "assemble_competitor_run",
] as const;

export const COMPETITOR_V2_TABLES = [
  "fact_competitor_agent_execution",
  "fact_competitor_analysis_run",
  "fact_competitor_analysis_change",
  "fact_competitor_analysis_timeline",
  "fact_competitor_analysis_concurrency",
  "fact_competitor_analysis_attention_reason",
  "fact_competitor_analysis_impact",
  "fact_competitor_analysis_open_item",
  "fact_competitor_analysis_diff",
  "fact_competitor_analysis_report",
  "fact_competitor_evidence_handoff",
] as const;

export const DEFAULT_COMPETITOR_THRESHOLDS = {
  price_drop_pct: 5,
  gap_shift_pct: 10,
  rank_shift_pct: 15,
  kw_rank_shift: 3,
  min_duration_days: 7,
  family_coverage_pct: 30,
  stale_days: 14,
} as const;

const THRESHOLD_RANGES: Record<keyof typeof DEFAULT_COMPETITOR_THRESHOLDS, [number, number, boolean]> = {
  price_drop_pct: [1, 30, false],
  gap_shift_pct: [2, 50, false],
  rank_shift_pct: [5, 60, false],
  kw_rank_shift: [1, 20, true],
  min_duration_days: [1, 60, true],
  family_coverage_pct: [5, 100, false],
  stale_days: [3, 90, true],
};

export type CompetitorTrigger = "manual" | "scheduled" | "priority";
export type CompetitorTaskState = "queued" | "running" | "done" | "skipped" | "failed";
export type CompetitorRunRequest = {
  trigger: CompetitorTrigger;
  family_asin: string;
  window_from: string;
  window_to: string;
  data_as_of: string;
  requested_by?: string;
  request_key: string;
  thresholds: Record<keyof typeof DEFAULT_COMPETITOR_THRESHOLDS, number>;
};

export type CompetitorModelFacts = {
  ok: true;
  family_asin: string;
  data_as_of: string;
  run_date: string;
  window_from: string;
  window_to: string;
  dataset_version: string;
  schema_version: "competitor-agent-contract-v2";
  method_version: typeof COMPETITOR_V2_METHOD_VERSION;
  rule_version: string;
  source_context_hash: string;
  threshold_fingerprint: string;
  thresholds: JsonObject;
  stage_order: string[];
  family: JsonObject;
  status_events: JsonObject[];
  change_candidates: JsonObject[];
  relation_candidates: JsonObject[];
  shared_keyword_candidates: JsonObject[];
  observation_coverage: JsonObject;
  threshold_effects: JsonObject;
  previous_run: JsonObject | null;
  source_boundary: JsonObject;
};

export type CompetitorPrivateFacts = {
  origins: Record<string, string>;
};

export type CompetitorFactsEnvelope = {
  model: CompetitorModelFacts;
  private: CompetitorPrivateFacts;
};

export type CompetitorExecution = {
  task_id: string;
  run_id: string;
  family_asin: string;
  status: "queued" | "running" | "completed" | "skipped" | "failed";
  trigger: CompetitorTrigger;
  source_context_hash: string;
  threshold_fingerprint: string;
  model_version: string;
  method_version: string;
  schema_version: string;
  dataset_version: string;
  rule_version: string;
  prev_run_id: string | null;
  created_at: string;
  completed_at: string | null;
  reason: string | null;
};

export type CompetitorTaskPayload = {
  task_id: string;
  state: CompetitorTaskState;
  run_id?: string;
  reason?: string;
};

const SCHEMA = `
CREATE TABLE IF NOT EXISTS fact_competitor_agent_execution (
  task_id TEXT NOT NULL UNIQUE, run_id TEXT PRIMARY KEY, family_asin TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('queued','running','completed','skipped','failed')),
  trigger TEXT NOT NULL CHECK(trigger IN ('manual','scheduled','priority')),
  source_context_hash TEXT NOT NULL, threshold_fingerprint TEXT NOT NULL,
  model_version TEXT NOT NULL, method_version TEXT NOT NULL, schema_version TEXT NOT NULL,
  dataset_version TEXT NOT NULL, rule_version TEXT NOT NULL, prev_run_id TEXT,
  created_at TEXT NOT NULL, completed_at TEXT, reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_competitor_agent_latest_v2
  ON fact_competitor_agent_execution(family_asin, status, created_at DESC);
CREATE TABLE IF NOT EXISTS fact_competitor_analysis_run (
  run_id TEXT PRIMARY KEY, family_asin TEXT NOT NULL, run_date TEXT NOT NULL,
  data_as_of TEXT NOT NULL, window_from TEXT NOT NULL, window_to TEXT NOT NULL,
  trigger TEXT NOT NULL, model_version TEXT, attention_level TEXT NOT NULL,
  attention_summary TEXT NOT NULL, evidence_level TEXT NOT NULL,
  evidence_reason TEXT NOT NULL, judgment_summary TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS fact_competitor_analysis_change (
  run_id TEXT NOT NULL, change_seq INTEGER NOT NULL, domain TEXT NOT NULL,
  object_level TEXT NOT NULL, object_id TEXT NOT NULL, label TEXT NOT NULL,
  direction TEXT NOT NULL, magnitude_kind TEXT, magnitude_value REAL,
  date_from TEXT NOT NULL, date_to TEXT, current_state TEXT NOT NULL,
  represents_family INTEGER NOT NULL, coverage_note TEXT, value_origin TEXT NOT NULL,
  confidence TEXT NOT NULL, basis TEXT NOT NULL, PRIMARY KEY (run_id, change_seq)
);
CREATE TABLE IF NOT EXISTS fact_competitor_analysis_timeline (
  run_id TEXT NOT NULL, track TEXT NOT NULL, item_seq INTEGER NOT NULL,
  label TEXT NOT NULL, date_from TEXT NOT NULL, date_to TEXT, ref_change_seq INTEGER,
  window_before_from TEXT, window_before_to TEXT, window_after_from TEXT,
  window_after_to TEXT, note TEXT, PRIMARY KEY (run_id, track, item_seq)
);
CREATE TABLE IF NOT EXISTS fact_competitor_analysis_concurrency (
  run_id TEXT NOT NULL, pair_seq INTEGER NOT NULL, change_seq_a INTEGER NOT NULL,
  change_seq_b INTEGER NOT NULL, relation TEXT NOT NULL, overlap_from TEXT,
  overlap_to TEXT, statement TEXT NOT NULL, causal_ready INTEGER NOT NULL,
  missing_evidence TEXT, PRIMARY KEY (run_id, pair_seq)
);
CREATE TABLE IF NOT EXISTS fact_competitor_analysis_attention_reason (
  run_id TEXT NOT NULL, reason_seq INTEGER NOT NULL, label TEXT NOT NULL,
  ref_change_seq INTEGER, weight_note TEXT, PRIMARY KEY (run_id, reason_seq)
);
CREATE TABLE IF NOT EXISTS fact_competitor_analysis_impact (
  run_id TEXT NOT NULL, impact_seq INTEGER NOT NULL, own_parent_asin TEXT NOT NULL,
  own_child_asin TEXT, shared_keyword TEXT, pressure_dimension TEXT NOT NULL,
  statement TEXT NOT NULL, ref_change_seq INTEGER, confidence TEXT NOT NULL,
  PRIMARY KEY (run_id, impact_seq)
);
CREATE TABLE IF NOT EXISTS fact_competitor_analysis_open_item (
  run_id TEXT NOT NULL, item_seq INTEGER NOT NULL, item_kind TEXT NOT NULL,
  statement TEXT NOT NULL, needed_data TEXT, watch_until TEXT,
  PRIMARY KEY (run_id, item_seq)
);
CREATE TABLE IF NOT EXISTS fact_competitor_analysis_diff (
  run_id TEXT PRIMARY KEY, prev_run_id TEXT, transition TEXT NOT NULL,
  statement TEXT NOT NULL, changed_domains TEXT
);
CREATE TABLE IF NOT EXISTS fact_competitor_analysis_report (
  report_id TEXT PRIMARY KEY, scope_key TEXT NOT NULL, period_from TEXT NOT NULL,
  period_to TEXT NOT NULL, item_seq INTEGER NOT NULL, family_asin TEXT NOT NULL,
  ref_run_id TEXT NOT NULL, headline TEXT NOT NULL, body TEXT NOT NULL,
  impact_note TEXT, unconfirmed_note TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS fact_competitor_evidence_handoff (
  handoff_id TEXT PRIMARY KEY, frozen_run_id TEXT NOT NULL, target_page TEXT NOT NULL,
  family_asin TEXT NOT NULL, own_child_asin TEXT, shared_keyword TEXT,
  pressure_dimension TEXT, observable_fact TEXT NOT NULL, evidence_level TEXT NOT NULL,
  detail_entry TEXT NOT NULL, created_at TEXT NOT NULL
);`;

const INTERNAL_STATUS_TO_API: Record<CompetitorExecution["status"], CompetitorTaskState> = {
  queued: "queued",
  running: "running",
  completed: "done",
  skipped: "skipped",
  failed: "failed",
};

const STATE_CN: Record<ChangeDecision["current_state"], string> = {
  still_running: "仍在进行",
  restored: "已恢复",
  ended: "已结束",
  unconfirmed: "无法确认",
};

const INTERNAL_ENUMS = [
  "price_promo", "third_party_estimate", "constructed", "insufficient", "sufficient",
  "partial", "sustained", "escalated", "hypothesis", "concurrent", "family_asin",
];
const FORBIDDEN_TEXT = [
  "综合威胁分数", "竞品库存", "广告预算", "提高出价", "降低出价", "黄金链", "黄金对象",
  "当前场景", "构造场景", "场景标注", "场景判定", "导致", "造成", "因此", "驱动",
];
const FORBIDDEN_MODEL_KEYS = new Set(["value_origin", "scenario", "scenario_id", "golden", "golden_answer"]);
const FORBIDDEN_MODEL_TOKENS = [
  "dim_competitor_scenario",
  "fact_competitor_analysis_",
  "fact_competitor_evidence_handoff",
  "competitor_agent_state.sqlite",
  "competitor_agent_latest.json",
];

function stable(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stable).join(",")}]`;
  if (value && typeof value === "object") {
    const object = value as Record<string, unknown>;
    return `{${Object.keys(object).sort().map((key) => `${JSON.stringify(key)}:${stable(object[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

function sha(value: string): string {
  return createHash("sha256").update(value).digest("hex");
}

function isoDate(value: unknown, field: string): string {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)
      || Number.isNaN(Date.parse(`${value}T00:00:00Z`))) throw new Error(`${field} 必须是 YYYY-MM-DD`);
  return value;
}

function clamp(value: number, low: number, high: number): number {
  return Math.min(high, Math.max(low, value));
}

export function validateCompetitorRunRequest(input: unknown): CompetitorRunRequest {
  if (!input || typeof input !== "object" || Array.isArray(input)) throw new Error("请求体必须是对象");
  const raw = input as Record<string, unknown>;
  const allowedFields = new Set([
    "trigger", "family_asin", "window_from", "window_to", "data_as_of",
    "requested_by", "request_key", "thresholds",
  ]);
  const unknownFields = Object.keys(raw).filter((key) => !allowedFields.has(key));
  if (unknownFields.length) throw new Error(`不允许的请求字段：${unknownFields.join(", ")}`);
  const trigger = raw.trigger;
  if (!(trigger === "manual" || trigger === "scheduled" || trigger === "priority")) {
    throw new Error("trigger 只能是 manual / scheduled / priority");
  }
  const familyAsin = typeof raw.family_asin === "string" ? raw.family_asin.trim().toUpperCase() : "";
  if (!/^[A-Z0-9]{10}$/.test(familyAsin)) throw new Error("family_asin 必须是 10 位父 ASIN");
  const windowFrom = isoDate(raw.window_from, "window_from");
  const windowTo = isoDate(raw.window_to, "window_to");
  const dataAsOf = isoDate(raw.data_as_of, "data_as_of");
  if (windowFrom > windowTo) throw new Error("window_from 不能晚于 window_to");
  if (dataAsOf < windowFrom || dataAsOf > windowTo) throw new Error("data_as_of 必须位于观察窗内");
  const requestKey = typeof raw.request_key === "string" ? raw.request_key.trim() : "";
  if (!requestKey || requestKey.length > 240) throw new Error("request_key 必须为 1–240 字符");
  const requestedBy = typeof raw.requested_by === "string" ? raw.requested_by.trim() : undefined;
  if (trigger === "manual" && !requestedBy) throw new Error("manual 请求必须提供 requested_by");
  if (!raw.thresholds || typeof raw.thresholds !== "object" || Array.isArray(raw.thresholds)) {
    throw new Error("thresholds 必须完整提供七个阈值");
  }
  const rawThresholds = raw.thresholds as Record<string, unknown>;
  const expected = Object.keys(THRESHOLD_RANGES);
  const actual = Object.keys(rawThresholds);
  const missing = expected.filter((key) => !(key in rawThresholds));
  const extra = actual.filter((key) => !expected.includes(key));
  if (missing.length || extra.length) {
    throw new Error(`thresholds 字段不完整：缺少 ${missing.join(", ") || "无"}；多余 ${extra.join(", ") || "无"}`);
  }
  const thresholds = {} as CompetitorRunRequest["thresholds"];
  for (const key of expected as Array<keyof typeof THRESHOLD_RANGES>) {
    const number = Number(rawThresholds[key]);
    if (!Number.isFinite(number)) throw new Error(`${key} 必须是数字`);
    const [low, high, integer] = THRESHOLD_RANGES[key];
    const value = clamp(number, low, high);
    thresholds[key] = integer ? Math.round(value) : Math.round(value * 10) / 10;
  }
  return {
    trigger,
    family_asin: familyAsin,
    window_from: windowFrom,
    window_to: windowTo,
    data_as_of: dataAsOf,
    ...(requestedBy ? { requested_by: requestedBy } : {}),
    request_key: requestKey,
    thresholds,
  };
}

export function buildCompetitorTaskId(familyAsin: string, requestKey: string): string {
  const family = familyAsin.trim().toUpperCase();
  if (!/^[A-Z0-9]{10}$/.test(family)) throw new Error("family_asin 无效");
  if (!requestKey.trim()) throw new Error("request_key 不能为空");
  return `T-${family}-${sha(requestKey).slice(0, 20)}`;
}

function sanitize(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sanitize);
  if (!value || typeof value !== "object") return value;
  const output: Record<string, unknown> = {};
  for (const [key, item] of Object.entries(value as Record<string, unknown>)) {
    if (FORBIDDEN_MODEL_KEYS.has(key)) continue;
    output[key] = sanitize(item);
  }
  return output;
}

export function assertModelInputSafe(value: unknown): void {
  const violations: string[] = [];
  function walk(item: unknown, path: string): void {
    if (Array.isArray(item)) return item.forEach((child, index) => walk(child, `${path}[${index}]`));
    if (item && typeof item === "object") {
      for (const [key, child] of Object.entries(item as Record<string, unknown>)) {
        if (FORBIDDEN_MODEL_KEYS.has(key)) violations.push(`${path}.${key}`);
        walk(child, `${path}.${key}`);
      }
      return;
    }
    if (typeof item === "string") {
      for (const token of FORBIDDEN_MODEL_TOKENS) if (item.includes(token)) violations.push(`${path}:${token}`);
    }
  }
  walk(value, "$model");
  if (violations.length) throw new Error(`模型上下文包含禁读内容：${[...new Set(violations)].join("；")}`);
}

function latestCompleted(db: DatabaseSync, familyAsin: string): CompetitorExecution | undefined {
  return db.prepare(`SELECT * FROM fact_competitor_agent_execution
    WHERE family_asin=? AND status='completed'
    ORDER BY julianday(created_at) DESC, created_at DESC, run_id DESC LIMIT 1`)
    .get(familyAsin) as CompetitorExecution | undefined;
}

function previousForModel(dbPath: string, familyAsin: string): JsonObject | null {
  try {
    const db = new DatabaseSync(dbPath, { readOnly: true });
    try {
      const execution = latestCompleted(db, familyAsin);
      if (!execution) return null;
      const run = db.prepare("SELECT * FROM fact_competitor_analysis_run WHERE run_id=?").get(execution.run_id) as JsonObject | undefined;
      const changes = db.prepare(`SELECT domain, label, direction, current_state, represents_family, confidence
        FROM fact_competitor_analysis_change WHERE run_id=? ORDER BY change_seq`).all(execution.run_id) as JsonObject[];
      const diff = db.prepare("SELECT transition, statement, changed_domains FROM fact_competitor_analysis_diff WHERE run_id=?")
        .get(execution.run_id) as JsonObject | undefined;
      const impacts = db.prepare(`SELECT own_parent_asin, own_child_asin, shared_keyword,
          pressure_dimension, statement, confidence
        FROM fact_competitor_analysis_impact WHERE run_id=? ORDER BY impact_seq`)
        .all(execution.run_id) as JsonObject[];
      const handoffs = db.prepare(`SELECT target_page, family_asin, own_child_asin,
          shared_keyword, pressure_dimension, observable_fact, detail_entry
        FROM fact_competitor_evidence_handoff WHERE frozen_run_id=? ORDER BY target_page`)
        .all(execution.run_id) as JsonObject[];
      return run ? {
        run_id: execution.run_id,
        created_at: execution.created_at,
        attention_level: run.attention_level,
        evidence_level: run.evidence_level,
        judgment_summary: run.judgment_summary,
        changes,
        impacts,
        handoffs,
        diff: diff ?? null,
      } : null;
    } finally {
      db.close();
    }
  } catch {
    return null;
  }
}

export function loadCompetitorFactsV2(
  requestInput: CompetitorRunRequest,
  dbPath = process.env.BAMBOO_COMPETITOR_V2_DB ?? DEFAULT_COMPETITOR_V2_DB,
): CompetitorFactsEnvelope {
  const request = validateCompetitorRunRequest(requestInput);
  const stdout = execFileSync("/usr/bin/python3", [
    FACT_BRIDGE,
    request.family_asin,
    JSON.stringify(request.thresholds),
  ], {
    cwd: COMPETITOR_V2_WORKBENCH_ROOT,
    encoding: "utf8",
    maxBuffer: 32 * 1024 * 1024,
    env: { ...process.env, WORKBENCH_COMPETITOR_AGENT_DB: dbPath },
  });
  const raw = JSON.parse(stdout) as JsonObject;
  if (!raw.ok) throw new Error(`没有可用的竞品观察事实：${request.family_asin}`);
  const origins = Object.fromEntries((raw.change_candidates ?? []).map((item: JsonObject) => [
    item.candidate_id,
    typeof item.value_origin === "string" ? item.value_origin : "derived",
  ]));
  const thresholdFingerprint = sha(stable(request.thresholds));
  // Must remain byte-for-byte identical to the workbench read model's hash;
  // otherwise a just-completed run would immediately be rendered as stale.
  const sourceContextHash = String(raw.source_context_hash);
  const clean = sanitize(raw) as JsonObject;
  const model: CompetitorModelFacts = {
    ...clean,
    ok: true,
    family_asin: request.family_asin,
    data_as_of: request.data_as_of,
    run_date: request.data_as_of,
    window_from: request.window_from,
    window_to: request.window_to,
    dataset_version: String(raw.dataset_version ?? "competitor-v0.1.0"),
    schema_version: "competitor-agent-contract-v2",
    method_version: COMPETITOR_V2_METHOD_VERSION,
    rule_version: "competitor-thresholds-v2",
    source_context_hash: sourceContextHash,
    threshold_fingerprint: thresholdFingerprint,
    thresholds: structuredClone(request.thresholds),
    stage_order: [...COMPETITOR_V2_STAGES],
    family: clean.family as JsonObject,
    status_events: clean.status_events as JsonObject[],
    change_candidates: clean.change_candidates as JsonObject[],
    relation_candidates: clean.relation_candidates as JsonObject[],
    shared_keyword_candidates: clean.shared_keyword_candidates as JsonObject[],
    observation_coverage: clean.observation_coverage as JsonObject,
    threshold_effects: clean.threshold_effects as JsonObject,
    previous_run: previousForModel(dbPath, request.family_asin),
    source_boundary: {
      observation_tables_read_only: true,
      prior_v2_completed_only: true,
      traffic_budget_inference_allowed: false,
      causal_ready: 0,
    },
  };
  if (!model.change_candidates.length) throw new Error("至少需要一个可审核变化候选");
  assertModelInputSafe(model);
  return { model, private: { origins } };
}

function ensureSchema(db: DatabaseSync): void {
  db.exec(SCHEMA);
}

function nextCreatedAt(db: DatabaseSync, familyAsin: string, now: Date): string {
  let value = now.toISOString();
  while (db.prepare("SELECT 1 FROM fact_competitor_agent_execution WHERE family_asin=? AND created_at=?")
    .get(familyAsin, value)) value = new Date(Date.parse(value) + 1).toISOString();
  return value;
}

function nextRunId(db: DatabaseSync, familyAsin: string, runDate: string): string {
  const prefix = `${familyAsin}-${runDate}-`;
  const rows = db.prepare("SELECT run_id FROM fact_competitor_agent_execution WHERE run_id LIKE ?")
    .all(`${prefix}%`) as Array<{ run_id: string }>;
  const max = rows.reduce((value, row) => {
    const suffix = Number(row.run_id.slice(prefix.length));
    return Number.isInteger(suffix) ? Math.max(value, suffix) : value;
  }, 0);
  return `${prefix}${max + 1}`;
}

export function enqueueCompetitorExecution(
  requestInput: CompetitorRunRequest,
  facts: CompetitorModelFacts,
  modelVersion: string,
  dbPath = process.env.BAMBOO_COMPETITOR_V2_DB ?? DEFAULT_COMPETITOR_V2_DB,
  now = new Date(),
): CompetitorExecution {
  const request = validateCompetitorRunRequest(requestInput);
  const taskId = buildCompetitorTaskId(request.family_asin, request.request_key);
  mkdirSync(dirname(dbPath), { recursive: true });
  const db = new DatabaseSync(dbPath);
  try {
    ensureSchema(db);
    db.exec("BEGIN IMMEDIATE");
    const existing = db.prepare("SELECT * FROM fact_competitor_agent_execution WHERE task_id=?").get(taskId) as CompetitorExecution | undefined;
    if (existing) {
      db.exec("COMMIT");
      return existing;
    }
    const createdAt = nextCreatedAt(db, request.family_asin, now);
    const previous = latestCompleted(db, request.family_asin);
    const execution: CompetitorExecution = {
      task_id: taskId,
      run_id: nextRunId(db, request.family_asin, request.data_as_of),
      family_asin: request.family_asin,
      status: "queued",
      trigger: request.trigger,
      source_context_hash: facts.source_context_hash,
      threshold_fingerprint: facts.threshold_fingerprint,
      model_version: modelVersion,
      method_version: facts.method_version,
      schema_version: facts.schema_version,
      dataset_version: facts.dataset_version,
      rule_version: facts.rule_version,
      prev_run_id: previous?.run_id ?? null,
      created_at: createdAt,
      completed_at: null,
      reason: null,
    };
    const keys = Object.keys(execution);
    db.prepare(`INSERT INTO fact_competitor_agent_execution (${keys.join(",")}) VALUES (${keys.map(() => "?").join(",")})`)
      .run(...keys.map((key) => (execution as JsonObject)[key]));
    db.exec("COMMIT");
    return execution;
  } catch (error) {
    try { db.exec("ROLLBACK"); } catch { /* no active transaction */ }
    throw error;
  } finally {
    db.close();
  }
}

const LEGAL_TRANSITIONS: Record<CompetitorExecution["status"], CompetitorExecution["status"][]> = {
  queued: ["running", "skipped", "failed"],
  running: ["completed", "failed"],
  completed: [],
  skipped: [],
  failed: [],
};

function transitionExecution(
  taskId: string,
  next: CompetitorExecution["status"],
  reason: string | null,
  dbPath: string,
  now = new Date(),
): CompetitorExecution {
  const db = new DatabaseSync(dbPath);
  try {
    ensureSchema(db);
    db.exec("BEGIN IMMEDIATE");
    const row = db.prepare("SELECT * FROM fact_competitor_agent_execution WHERE task_id=?").get(taskId) as CompetitorExecution | undefined;
    if (!row) throw new Error("任务不存在");
    if (!LEGAL_TRANSITIONS[row.status].includes(next)) throw new Error(`非法状态转换：${row.status} → ${next}`);
    db.prepare("UPDATE fact_competitor_agent_execution SET status=?, reason=?, completed_at=? WHERE task_id=?")
      .run(next, reason, next === "completed" ? now.toISOString() : null, taskId);
    const updated = db.prepare("SELECT * FROM fact_competitor_agent_execution WHERE task_id=?").get(taskId) as CompetitorExecution;
    db.exec("COMMIT");
    return updated;
  } catch (error) {
    try { db.exec("ROLLBACK"); } catch { /* no active transaction */ }
    throw error;
  } finally {
    db.close();
  }
}

export function markCompetitorExecutionRunning(taskId: string, dbPath = process.env.BAMBOO_COMPETITOR_V2_DB ?? DEFAULT_COMPETITOR_V2_DB, now = new Date()): CompetitorExecution {
  return transitionExecution(taskId, "running", null, dbPath, now);
}

export function failCompetitorExecution(taskId: string, reason: string, dbPath = process.env.BAMBOO_COMPETITOR_V2_DB ?? DEFAULT_COMPETITOR_V2_DB, now = new Date()): CompetitorExecution {
  return transitionExecution(taskId, "failed", safeReason(reason), dbPath, now);
}

export function skipCompetitorExecution(taskId: string, reason: string, dbPath = process.env.BAMBOO_COMPETITOR_V2_DB ?? DEFAULT_COMPETITOR_V2_DB, now = new Date()): CompetitorExecution {
  return transitionExecution(taskId, "skipped", safeReason(reason), dbPath, now);
}

export function getCompetitorTask(taskId: string, dbPath = process.env.BAMBOO_COMPETITOR_V2_DB ?? DEFAULT_COMPETITOR_V2_DB): CompetitorTaskPayload | null {
  try {
    const db = new DatabaseSync(dbPath, { readOnly: true });
    try {
      const row = db.prepare("SELECT * FROM fact_competitor_agent_execution WHERE task_id=?").get(taskId) as CompetitorExecution | undefined;
      if (!row) return null;
      const state = INTERNAL_STATUS_TO_API[row.status];
      return {
        task_id: row.task_id,
        state,
        ...(["done", "skipped", "failed"].includes(state) ? { run_id: row.run_id } : {}),
        ...((state === "failed" || state === "skipped") && row.reason ? { reason: row.reason } : {}),
      };
    } finally {
      db.close();
    }
  } catch {
    return null;
  }
}

export function recoverInterruptedCompetitorExecutions(
  dbPath = process.env.BAMBOO_COMPETITOR_V2_DB ?? DEFAULT_COMPETITOR_V2_DB,
  now = new Date(),
): number {
  if (!readableDatabase(dbPath)) return 0;
  const db = new DatabaseSync(dbPath);
  try {
    ensureSchema(db);
    const result = db.prepare(`UPDATE fact_competitor_agent_execution
      SET status='failed', completed_at=?, reason='本地任务服务已重启，请重新发起分析'
      WHERE status IN ('queued','running')`).run(now.toISOString());
    return Number(result.changes);
  } finally {
    db.close();
  }
}

function readableDatabase(path: string): boolean {
  try { readFileSync(path, { encoding: null, flag: "r" }); return true; } catch { return false; }
}

function safeReason(value: string): string {
  const text = String(value || "竞品分析任务失败").replace(/[\r\n\t]+/g, " ").trim();
  return text.slice(0, 240) || "竞品分析任务失败";
}

export function shouldSkipCompetitorRun(
  taskId: string,
  dbPath = process.env.BAMBOO_COMPETITOR_V2_DB ?? DEFAULT_COMPETITOR_V2_DB,
): { skip: boolean; reason?: string } {
  const db = new DatabaseSync(dbPath, { readOnly: true });
  try {
    const current = db.prepare("SELECT * FROM fact_competitor_agent_execution WHERE task_id=?").get(taskId) as CompetitorExecution | undefined;
    if (!current) throw new Error("任务不存在");
    const previous = db.prepare(`SELECT * FROM fact_competitor_agent_execution
      WHERE family_asin=? AND status='completed' AND run_id<>?
      ORDER BY julianday(created_at) DESC, created_at DESC, run_id DESC LIMIT 1`)
      .get(current.family_asin, current.run_id) as CompetitorExecution | undefined;
    if (!previous) return { skip: false };
    const keys: Array<keyof CompetitorExecution> = [
      "source_context_hash", "threshold_fingerprint", "model_version", "method_version",
      "schema_version", "rule_version",
    ];
    if (keys.every((key) => current[key] === previous[key])) {
      return { skip: true, reason: `自 ${previous.completed_at?.slice(0, 10) ?? previous.created_at.slice(0, 10)} 起无新观察数据，沿用已有分析` };
    }
    return { skip: false };
  } finally {
    db.close();
  }
}

function textErrors(label: string, value: string | null | undefined): string[] {
  if (value == null) return [];
  const text = value.trim();
  const errors: string[] = [];
  if (!text) errors.push(`${label} 不得为空`);
  if (/\d/.test(text)) errors.push(`${label} 不得自行填写数字；数值由程序锁定`);
  for (const token of [...INTERNAL_ENUMS, ...FORBIDDEN_TEXT]) if (text.includes(token)) errors.push(`${label} 含禁用措辞：${token}`);
  return errors;
}

function unique<T>(values: T[]): T[] { return [...new Set(values)]; }
function failIf(errors: string[]): void {
  const values = unique(errors);
  if (values.length) throw new Error(values.join("；"));
}

export type ReportSelectionDecision = { report: OutputDecision["report"] };
export type AssembleDecision = Omit<OutputDecision, "report">;

export class CompetitorWorkflowV2 {
  readonly facts: CompetitorModelFacts;
  private expected = 0;
  private evidence?: EvidenceDecision;
  private changes: ChangeDecision[] = [];
  private representation: RepresentationDecision[] = [];
  private impacts: ImpactDecision[] = [];
  private concurrency: ConcurrencyDecision[] = [];
  private attention?: AttentionDecision;
  private report: OutputDecision["report"] = null;
  private outputs?: OutputDecision;

  constructor(facts: CompetitorModelFacts) { assertModelInputSafe(facts); this.facts = facts; }
  get expectedStage(): string { return COMPETITOR_V2_STAGES[this.expected] ?? "completed"; }
  private require(index: number): void {
    if (this.expected !== index) throw new Error(`当前只能执行 ${this.expectedStage}`);
  }

  submitEvidence(value: EvidenceDecision): void {
    this.require(0);
    const errors = [...textErrors("证据原因", value.evidence_reason), ...textErrors("判断摘要", value.judgment_summary)];
    const statuses = new Set(this.facts.status_events.map((item) => item.status));
    const hasGap = this.facts.change_candidates.some((item) => item.evidence_gap);
    if (hasGap && value.evidence_level !== "insufficient") errors.push("原始观察缺失时必须判为证据不足");
    if (!hasGap && statuses.has("interrupted") && statuses.has("conflict") && statuses.has("stale")
      && value.evidence_level !== "insufficient") errors.push("断更、冲突和过期同时存在时必须判为证据不足");
    failIf(errors);
    this.evidence = structuredClone(value);
    this.expected = value.evidence_level === "insufficient" ? 7 : 1;
  }

  submitChanges(values: ChangeDecision[]): void {
    this.require(1);
    const errors: string[] = [];
    if (!values.length) errors.push("每个有效 run 至少提交一条变化或稳定结论");
    const candidates = new Map(this.facts.change_candidates.map((item) => [item.candidate_id, item]));
    const seen = new Set<string>();
    for (const value of values) {
      const candidate = candidates.get(value.candidate_id);
      if (!candidate) { errors.push(`未知 candidate_id：${value.candidate_id}`); continue; }
      if (seen.has(value.candidate_id)) errors.push(`candidate_id 重复：${value.candidate_id}`);
      seen.add(value.candidate_id);
      if (!candidate.allowed_domains.includes(value.domain)) errors.push(`${value.candidate_id}.domain 与候选事实不一致`);
      if (!candidate.allowed_directions.includes(value.direction)) errors.push(`${value.candidate_id}.direction 与锁定幅度不一致`);
      if (!candidate.allowed_current_states.includes(value.current_state)) errors.push(`${value.candidate_id}.current_state 与日期区间不一致`);
      errors.push(...textErrors("变化标签", value.label), ...textErrors("变化依据", value.basis));
    }
    failIf(errors); this.changes = structuredClone(values); this.expected = 2;
  }

  submitRepresentation(values: RepresentationDecision[]): void {
    this.require(2);
    const errors: string[] = [];
    const selected = new Set(this.changes.map((item) => item.candidate_id));
    if (values.length !== selected.size) errors.push("整族代表性必须逐条覆盖已选变化");
    const seen = new Set<string>();
    for (const value of values) {
      if (!selected.has(value.candidate_id)) errors.push(`代表性引用了未选变化：${value.candidate_id}`);
      if (seen.has(value.candidate_id)) errors.push(`代表性重复：${value.candidate_id}`);
      seen.add(value.candidate_id);
      // family_coverage_pct 只作为模型证据，不能成为程序硬锁。
      if (!value.represents_family && !value.coverage_note?.trim()) errors.push(`${value.candidate_id} 不代表整族时必须说明覆盖范围`);
      errors.push(...textErrors("覆盖说明", value.coverage_note));
    }
    failIf(errors); this.representation = structuredClone(values); this.expected = 3;
  }

  submitScope(values: ImpactDecision[]): void {
    this.require(3);
    const errors: string[] = [];
    const selected = new Set(this.changes.map((item) => item.candidate_id));
    const relations = new Map(this.facts.relation_candidates.map((item) => [item.rel_id, item]));
    const keywords = new Set(this.facts.shared_keyword_candidates.map((item) => item.keyword));
    const seen = new Set<string>();
    for (const value of values) {
      if (!selected.has(value.candidate_id)) errors.push("影响引用了未选变化");
      const relation = relations.get(value.relation_id);
      if (!relation) errors.push(`自有对象不属于当前竞品族：${value.relation_id}`);
      if (["price", "promo"].includes(value.pressure_dimension)
          && relation?.gap_shift_applicable && !relation.gap_shift_eligible) errors.push("件单价差变化未达当前阈值");
      if (value.shared_keyword && !keywords.has(value.shared_keyword)) errors.push("共同词不属于当前竞品族");
      const key = `${value.candidate_id}:${value.relation_id}:${value.pressure_dimension}`;
      if (seen.has(key)) errors.push(`影响重复：${key}`);
      seen.add(key); errors.push(...textErrors("影响说明", value.statement));
    }
    const selectedPriceCandidates = this.changes
      .filter((item) => item.domain === "price_promo")
      .map((item) => item.candidate_id);
    if (selectedPriceCandidates.length) {
      const eligibleRelations = this.facts.relation_candidates.filter((item) =>
        item.confirm_status === "confirmed" && item.gap_shift_applicable === true && item.gap_shift_eligible === true);
      for (const relation of eligibleRelations) {
        const covered = values.some((item) => selectedPriceCandidates.includes(item.candidate_id)
          && item.relation_id === relation.rel_id && ["price", "promo"].includes(item.pressure_dimension));
        if (!covered) errors.push(`已确认且价差变化达阈值的关系必须产出影响范围：${relation.rel_id}`);
      }
    }
    failIf(errors); this.impacts = structuredClone(values); this.expected = 4;
  }

  submitConcurrency(values: ConcurrencyDecision[]): void {
    this.require(4);
    const errors: string[] = [];
    const selected = new Set(this.changes.map((item) => item.candidate_id));
    const pairs = new Set<string>();
    for (const value of values) {
      if (value.change_a_id === value.change_b_id) errors.push("同期关系必须引用两条不同变化");
      if (!selected.has(value.change_a_id) || !selected.has(value.change_b_id)) errors.push("同期关系存在悬空变化引用");
      const pair = [value.change_a_id, value.change_b_id].sort().join(":");
      if (pairs.has(pair)) errors.push("同期关系重复");
      pairs.add(pair);
      if (value.relation === "concurrent" && !/同期|可能相关/.test(value.statement)) errors.push("同期关系只能表述为同期变化或可能相关");
      errors.push(...textErrors("同期关系", value.statement), ...textErrors("缺失证据", value.missing_evidence));
    }
    failIf(errors); this.concurrency = structuredClone(values); this.expected = 5;
  }

  submitAttention(value: AttentionDecision): void {
    this.require(5);
    const errors = [
      ...textErrors("关注摘要", value.attention_summary),
      ...value.reasons.flatMap((item) => [...textErrors("关注依据", item.label), ...textErrors("权重说明", item.weight_note)]),
    ];
    const selected = new Set(this.changes.map((item) => item.candidate_id));
    for (const reason of value.reasons) {
      if (reason.candidate_id && !selected.has(reason.candidate_id)) errors.push("关注依据存在悬空引用");
      if (reason.weight_note && /\d|%/.test(reason.weight_note)) errors.push("权重说明只能定性表达");
    }
    if (value.attention_level !== "none" && value.reasons.length < 2) errors.push("有关注等级时至少需要两条依据");
    failIf(errors); this.attention = structuredClone(value); this.expected = 6;
  }

  submitReport(value: ReportSelectionDecision): void {
    this.require(6);
    const errors: string[] = [];
    const eligible = this.evidence?.evidence_level === "sufficient"
      && ["high", "medium"].includes(this.attention!.attention_level)
      && this.representation.some((item) => item.represents_family);
    if (Boolean(value.report) !== eligible) errors.push("报告只允许证据充分、高中关注且存在整族变化的 run");
    if (value.report) errors.push(
      ...textErrors("报告标题", value.report.headline), ...textErrors("报告正文", value.report.body),
      ...textErrors("报告影响", value.report.impact_note), ...textErrors("报告未确认项", value.report.unconfirmed_note),
    );
    failIf(errors); this.report = structuredClone(value.report); this.expected = 7;
  }

  submitAssemble(value: AssembleDecision): void {
    this.require(7);
    const errors: string[] = [];
    for (const item of value.open_items) errors.push(...textErrors("待观察项", item.statement), ...textErrors("待补数据", item.needed_data));
    errors.push(...textErrors("版本差异", value.diff.statement));
    const isFirst = !this.facts.previous_run;
    if (isFirst && value.diff.transition !== "new") errors.push("首次 V2 运行的 diff 必须为 new");
    if (!isFirst && value.diff.transition === "new") errors.push("已有 V2 上一版时 diff 不得为 new");
    const selected = new Set(this.changes.map((item) => item.candidate_id));
    const selectedDomains = new Set(this.changes.map((item) => item.domain));
    if (value.diff.changed_domains.some((item) => !selectedDomains.has(item))) errors.push("diff 引用了未提交变化类型");
    const relations = new Set(this.facts.relation_candidates.map((item) => item.rel_id));
    const keywords = new Set(this.facts.shared_keyword_candidates.map((item) => item.keyword));
    const targets = new Set<string>();
    for (const handoff of value.handoffs) {
      if (targets.has(handoff.target_page)) errors.push("每个 run 每个目标页最多一条交接");
      targets.add(handoff.target_page);
      if (!selected.has(handoff.candidate_id)) errors.push("交接存在悬空变化引用");
      if (handoff.relation_id && !relations.has(handoff.relation_id)) errors.push("交接自有对象不属于当前族关系桥");
      if (handoff.shared_keyword && !keywords.has(handoff.shared_keyword)) errors.push("交接共同词不属于当前族");
      errors.push(...textErrors("交接事实", handoff.observable_fact));
    }
    const hasKeywordEvidence = this.impacts.length > 0 && this.facts.shared_keyword_candidates.length > 0;
    const hasTrafficChange = this.changes.some((item) => item.domain === "traffic");
    if (this.evidence!.evidence_level !== "insufficient") {
      if (hasKeywordEvidence && !targets.has("keyword")) errors.push("存在影响范围和共同词时必须产出关键词证据交接");
      if (hasTrafficChange && !targets.has("advertising")) errors.push("存在流量结构变化时必须产出广告证据交接");
      const previous = this.facts.previous_run as JsonObject | null;
      const previousImpacts = Array.isArray(previous?.impacts) ? previous.impacts : [];
      const previousHandoffs = Array.isArray(previous?.handoffs) ? previous.handoffs : [];
      if (["sustained", "escalated"].includes(value.diff.transition)) {
        if (previousImpacts.length > 0 && this.impacts.length === 0) {
          errors.push("持续或加重的重跑不得静默清空上一版影响范围");
        }
        for (const prior of previousHandoffs) {
          if (typeof prior?.target_page === "string" && !targets.has(prior.target_page)) {
            errors.push(`持续或加重的重跑不得静默清空上一版${prior.target_page}交接`);
          }
        }
      }
    }
    if (this.evidence!.evidence_level === "insufficient") {
      if (this.changes.length || this.representation.length || this.impacts.length || this.concurrency.length
          || this.attention || this.report || value.handoffs.length) errors.push("证据不足必须短路且不产出关注、报告或交接");
      this.attention = { attention_level: "none", attention_summary: "证据不足，本次不给关注结论", reasons: [] };
    }
    failIf(errors);
    this.outputs = { ...structuredClone(value), report: structuredClone(this.report) };
    this.expected = 8;
  }

  snapshot(): WorkflowSnapshot {
    if (this.expected !== 8 || !this.evidence || !this.attention || !this.outputs) throw new Error("竞品八步判断尚未完成");
    return structuredClone({
      evidence: this.evidence,
      changes: this.changes,
      representation: this.representation,
      impacts: this.impacts,
      concurrency: this.concurrency,
      attention: this.attention,
      outputs: this.outputs,
    });
  }
}

function addDays(value: string, days: number): string {
  const date = new Date(`${value}T00:00:00Z`); date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}
function clampDate(value: string, low: string, high: string): string { return value < low ? low : value > high ? high : value; }

function insertRows(db: DatabaseSync, table: string, values: JsonObject[]): void {
  if (!values.length) return;
  const keys = Object.keys(values[0]!);
  const statement = db.prepare(`INSERT INTO ${table} (${keys.join(",")}) VALUES (${keys.map(() => "?").join(",")})`);
  for (const value of values) statement.run(...keys.map((key) => value[key] ?? null));
}

function derivedRows(
  facts: CompetitorModelFacts,
  privateFacts: CompetitorPrivateFacts,
  snapshot: WorkflowSnapshot,
  execution: CompetitorExecution,
): JsonObject {
  const candidates = new Map(facts.change_candidates.map((item) => [item.candidate_id, item]));
  const reps = new Map(snapshot.representation.map((item) => [item.candidate_id, item]));
  const seq = new Map(snapshot.changes.map((item, index) => [item.candidate_id, index + 1]));
  const changes = snapshot.changes.map((item, index) => {
    const candidate = candidates.get(item.candidate_id)!;
    const representation = reps.get(item.candidate_id)!;
    if (!candidate || !representation) throw new Error("变化或代表性引用缺失");
    return {
      run_id: execution.run_id, change_seq: index + 1, domain: item.domain,
      object_level: candidate.object_level, object_id: candidate.object_id, label: item.label,
      direction: item.direction, magnitude_kind: candidate.magnitude_kind, magnitude_value: candidate.magnitude_value,
      date_from: candidate.date_from, date_to: candidate.date_to, current_state: STATE_CN[item.current_state],
      represents_family: representation.represents_family ? 1 : 0, coverage_note: representation.coverage_note,
      value_origin: privateFacts.origins[item.candidate_id] ?? "derived", confidence: item.confidence, basis: item.basis,
    };
  });
  const trackSeq = new Map<string, number>();
  const timelines = changes.map((change: JsonObject) => {
    const track = change.domain === "traffic" ? "keyword" : change.domain;
    const itemSeq = (trackSeq.get(track) ?? 0) + 1; trackSeq.set(track, itemSeq);
    return {
      run_id: execution.run_id, track, item_seq: itemSeq, label: change.label,
      date_from: change.date_from, date_to: change.date_to, ref_change_seq: change.change_seq,
      window_before_from: clampDate(addDays(change.date_from, -28), facts.window_from, facts.window_to),
      window_before_to: clampDate(addDays(change.date_from, -1), facts.window_from, facts.window_to),
      window_after_from: change.date_from,
      window_after_to: clampDate(addDays(change.date_from, 28), facts.window_from, facts.window_to), note: null,
    };
  });
  for (const status of facts.status_events) {
    const itemSeq = (trackSeq.get("data_status") ?? 0) + 1; trackSeq.set("data_status", itemSeq);
    timelines.push({
      run_id: execution.run_id, track: "data_status", item_seq: itemSeq, label: status.label,
      date_from: clampDate(status.date_from, facts.window_from, facts.window_to),
      date_to: status.date_to ? clampDate(status.date_to, facts.window_from, facts.window_to) : null,
      ref_change_seq: null, window_before_from: null, window_before_to: null,
      window_after_from: null, window_after_to: null, note: status.source ?? null,
    });
  }
  const concurrency = snapshot.concurrency.map((item, index) => {
    const a = candidates.get(item.change_a_id)!; const b = candidates.get(item.change_b_id)!;
    if (!a || !b || item.change_a_id === item.change_b_id) throw new Error("同期关系引用非法");
    const overlapFrom = a.date_from > b.date_from ? a.date_from : b.date_from;
    const aTo = a.date_to ?? facts.window_to; const bTo = b.date_to ?? facts.window_to;
    const overlapTo = aTo < bTo ? aTo : bTo;
    return {
      run_id: execution.run_id, pair_seq: index + 1,
      change_seq_a: seq.get(item.change_a_id), change_seq_b: seq.get(item.change_b_id), relation: item.relation,
      overlap_from: overlapFrom <= overlapTo ? overlapFrom : null, overlap_to: overlapFrom <= overlapTo ? overlapTo : null,
      statement: item.statement, causal_ready: 0, missing_evidence: item.missing_evidence,
    };
  });
  const reasons = snapshot.attention.reasons.map((item, index) => ({
    run_id: execution.run_id, reason_seq: index + 1, label: item.label,
    ref_change_seq: item.candidate_id ? seq.get(item.candidate_id) ?? null : null, weight_note: item.weight_note,
  }));
  const relations = new Map(facts.relation_candidates.map((item) => [item.rel_id, item]));
  const impacts = snapshot.impacts.map((item, index) => {
    const relation = relations.get(item.relation_id);
    if (!relation) throw new Error("竞争影响自有对象不属于当前族");
    return {
      run_id: execution.run_id, impact_seq: index + 1, own_parent_asin: relation.parent_asin,
      own_child_asin: relation.child_asin, shared_keyword: item.shared_keyword,
      pressure_dimension: item.pressure_dimension, statement: item.statement,
      ref_change_seq: seq.get(item.candidate_id), confidence: item.confidence,
    };
  });
  const openItems = snapshot.outputs.open_items.map((item, index) => ({
    run_id: execution.run_id, item_seq: index + 1, item_kind: item.item_kind,
    statement: item.statement, needed_data: item.needed_data, watch_until: null,
  }));
  const diff = {
    run_id: execution.run_id, prev_run_id: execution.prev_run_id,
    transition: snapshot.outputs.diff.transition, statement: snapshot.outputs.diff.statement,
    changed_domains: unique(snapshot.outputs.diff.changed_domains).sort().join(","),
  };
  const handoffs = snapshot.outputs.handoffs.map((item) => {
    const relation = item.relation_id ? relations.get(item.relation_id) : undefined;
    const candidate = candidates.get(item.candidate_id);
    if (!candidate) throw new Error("交接变化引用非法");
    const suffix = item.target_page === "keyword" ? "KW" : "AD";
    return {
      handoff_id: `HO-${execution.run_id}-${suffix}`, frozen_run_id: execution.run_id,
      target_page: item.target_page, family_asin: facts.family_asin,
      own_child_asin: relation?.child_asin ?? null, shared_keyword: item.shared_keyword,
      pressure_dimension: item.pressure_dimension, observable_fact: item.observable_fact,
      evidence_level: snapshot.evidence.evidence_level,
      detail_entry: `${facts.family_asin} · ${candidate.date_from} 至 ${candidate.date_to ?? facts.window_to} · ${item.observable_fact}`,
      created_at: execution.created_at,
    };
  });
  return { changes, timelines, concurrency, reasons, impacts, openItems, diff, handoffs };
}

function validateSnapshot(facts: CompetitorModelFacts, snapshot: WorkflowSnapshot): void {
  const errors: string[] = [];
  try {
    // The writer replays the complete business workflow instead of trusting the
    // in-process runner. This keeps the atomic commit boundary authoritative.
    const replay = new CompetitorWorkflowV2(facts);
    replay.submitEvidence(snapshot.evidence);
    if (snapshot.evidence.evidence_level !== "insufficient") {
      replay.submitChanges(snapshot.changes);
      replay.submitRepresentation(snapshot.representation);
      replay.submitScope(snapshot.impacts);
      replay.submitConcurrency(snapshot.concurrency);
      replay.submitAttention(snapshot.attention);
      replay.submitReport({ report: snapshot.outputs.report });
    }
    const { report: _report, ...assemble } = snapshot.outputs;
    replay.submitAssemble(assemble);
    if (stable(replay.snapshot()) !== stable(snapshot)) errors.push("写入 payload 与八步工作流重放结果不一致");
  } catch (error) {
    errors.push(error instanceof Error ? error.message : "八步工作流重放失败");
  }
  const candidateIds = new Set(facts.change_candidates.map((item) => item.candidate_id));
  const relationIds = new Set(facts.relation_candidates.map((item) => item.rel_id));
  const keywordIds = new Set(facts.shared_keyword_candidates.map((item) => item.keyword));
  const changeIds = new Set(snapshot.changes.map((item) => item.candidate_id));
  if (changeIds.size !== snapshot.changes.length) errors.push("变化候选重复");
  if ([...changeIds].some((id) => !candidateIds.has(id))) errors.push("变化引用不属于当前族候选");
  if (snapshot.representation.length !== snapshot.changes.length) errors.push("代表性必须覆盖每条变化");
  for (const item of snapshot.impacts) {
    if (!changeIds.has(item.candidate_id) || !relationIds.has(item.relation_id)) errors.push("影响存在悬空或跨族引用");
    if (item.shared_keyword && !keywordIds.has(item.shared_keyword)) errors.push("影响共同词不属于当前族");
  }
  for (const item of snapshot.concurrency) {
    if (item.change_a_id === item.change_b_id || !changeIds.has(item.change_a_id) || !changeIds.has(item.change_b_id)) errors.push("同期关系引用非法");
  }
  if (snapshot.evidence.evidence_level === "insufficient") {
    if (snapshot.attention.attention_level !== "none" || snapshot.attention.reasons.length || snapshot.outputs.report) errors.push("证据不足门禁失败");
  } else if (snapshot.attention.attention_level !== "none" && snapshot.attention.reasons.length < 2) errors.push("关注依据不足两条");
  const reportEligible = snapshot.evidence.evidence_level === "sufficient"
    && ["high", "medium"].includes(snapshot.attention.attention_level)
    && snapshot.representation.some((item) => item.represents_family);
  if (Boolean(snapshot.outputs.report) !== reportEligible) errors.push("报告资格门禁失败");
  failIf(errors);
}

function rerankReports(db: DatabaseSync, periodTo: string): void {
  const rows = db.prepare(`SELECT r.report_id, r.family_asin, r.created_at, a.attention_level
    FROM fact_competitor_analysis_report r
    JOIN fact_competitor_analysis_run a ON a.run_id=r.ref_run_id
    JOIN fact_competitor_agent_execution e ON e.run_id=r.ref_run_id AND e.status='completed'
    WHERE r.period_to=? AND e.run_id=(
      SELECT e2.run_id FROM fact_competitor_agent_execution e2
      WHERE e2.family_asin=e.family_asin AND e2.status='completed'
      ORDER BY julianday(e2.created_at) DESC, e2.created_at DESC, e2.run_id DESC LIMIT 1
    )`).all(periodTo) as Array<{ report_id: string; family_asin: string; created_at: string; attention_level: string }>;
  rows.sort((a, b) => {
    const level = (value: string) => value === "high" ? 0 : value === "medium" ? 1 : 2;
    return level(a.attention_level) - level(b.attention_level)
      || b.created_at.localeCompare(a.created_at)
      || a.family_asin.localeCompare(b.family_asin);
  });
  const update = db.prepare("UPDATE fact_competitor_analysis_report SET item_seq=? WHERE report_id=?");
  rows.forEach((row, index) => update.run(index + 1, row.report_id));
}

export function writeCompetitorAgentRunV2(
  taskId: string,
  facts: CompetitorModelFacts,
  privateFacts: CompetitorPrivateFacts,
  snapshot: WorkflowSnapshot,
  requestInput: CompetitorRunRequest,
  dbPath = process.env.BAMBOO_COMPETITOR_V2_DB ?? DEFAULT_COMPETITOR_V2_DB,
  exportPath = process.env.BAMBOO_COMPETITOR_V2_JSON ?? DEFAULT_COMPETITOR_V2_JSON,
  now = new Date(),
): JsonObject {
  const request = validateCompetitorRunRequest(requestInput);
  assertModelInputSafe(facts);
  validateSnapshot(facts, snapshot);
  const db = new DatabaseSync(dbPath);
  let output: JsonObject;
  try {
    ensureSchema(db);
    db.exec("BEGIN IMMEDIATE");
    const execution = db.prepare("SELECT * FROM fact_competitor_agent_execution WHERE task_id=?").get(taskId) as CompetitorExecution | undefined;
    if (!execution) throw new Error("任务不存在");
    if (execution.status !== "running") throw new Error(`只有 running 任务可以提交，当前为 ${execution.status}`);
    const previous = db.prepare(`SELECT * FROM fact_competitor_agent_execution
      WHERE family_asin=? AND status='completed' AND run_id<>?
      ORDER BY julianday(created_at) DESC, created_at DESC, run_id DESC LIMIT 1`)
      .get(execution.family_asin, execution.run_id) as CompetitorExecution | undefined;
    execution.prev_run_id = previous?.run_id ?? null;
    const isFirst = !execution.prev_run_id;
    if (isFirst && snapshot.outputs.diff.transition !== "new") throw new Error("首次 V2 运行的 diff 必须为 new");
    if (!isFirst && snapshot.outputs.diff.transition === "new") throw new Error("已有 V2 上一版时 diff 不得为 new");
    const rows = derivedRows(facts, privateFacts, snapshot, execution);
    const completedAt = now.toISOString();
    const run = {
      run_id: execution.run_id, family_asin: request.family_asin, run_date: request.data_as_of,
      data_as_of: request.data_as_of, window_from: request.window_from, window_to: request.window_to,
      trigger: request.trigger, model_version: execution.model_version,
      attention_level: snapshot.attention.attention_level, attention_summary: snapshot.attention.attention_summary,
      evidence_level: snapshot.evidence.evidence_level, evidence_reason: snapshot.evidence.evidence_reason,
      judgment_summary: snapshot.evidence.judgment_summary, created_at: execution.created_at,
    };
    const report = snapshot.outputs.report ? [{
      report_id: `RPT-${execution.run_id}-01`, scope_key: `美国站 · ${facts.family.sub_category}`,
      period_from: clampDate(addDays(request.window_to, -27), request.window_from, request.window_to),
      period_to: request.window_to, item_seq: 999999, family_asin: request.family_asin,
      ref_run_id: execution.run_id, ...snapshot.outputs.report, created_at: execution.created_at,
    }] : [];
    insertRows(db, "fact_competitor_analysis_run", [run]);
    insertRows(db, "fact_competitor_analysis_change", rows.changes);
    insertRows(db, "fact_competitor_analysis_timeline", rows.timelines);
    insertRows(db, "fact_competitor_analysis_concurrency", rows.concurrency);
    insertRows(db, "fact_competitor_analysis_attention_reason", rows.reasons);
    insertRows(db, "fact_competitor_analysis_impact", rows.impacts);
    insertRows(db, "fact_competitor_analysis_open_item", rows.openItems);
    insertRows(db, "fact_competitor_analysis_diff", [{ ...rows.diff, prev_run_id: execution.prev_run_id }]);
    insertRows(db, "fact_competitor_analysis_report", report);
    insertRows(db, "fact_competitor_evidence_handoff", rows.handoffs);
    db.prepare(`UPDATE fact_competitor_agent_execution SET status='completed', prev_run_id=?, completed_at=?, reason=NULL
      WHERE task_id=? AND status='running'`).run(execution.prev_run_id, completedAt, taskId);
    rerankReports(db, request.window_to);
    db.exec("COMMIT");
    output = {
      contract_version: facts.schema_version,
      task_id: taskId,
      run: { ...run, status: "completed", completed_at: completedAt, prev_run_id: execution.prev_run_id },
      analysis_state: snapshot.evidence.evidence_level === "insufficient" ? "insufficient" : "current",
      counts: {
        changes: rows.changes.length, timelines: rows.timelines.length, concurrency: rows.concurrency.length,
        reasons: rows.reasons.length, impacts: rows.impacts.length, open_items: rows.openItems.length,
        reports: report.length, handoffs: rows.handoffs.length,
      },
    };
  } catch (error) {
    try { db.exec("ROLLBACK"); } catch { /* no active transaction */ }
    throw error;
  } finally {
    db.close();
  }
  mkdirSync(dirname(exportPath), { recursive: true });
  const temp = `${exportPath}.${taskId}.tmp`;
  writeFileSync(temp, `${JSON.stringify(output, null, 2)}\n`, "utf8");
  renameSync(temp, exportPath);
  return { ...output, db_path: dbPath, export_path: exportPath };
}

export function readConfiguredPiModelVersion(): string {
  try {
    const settings = JSON.parse(readFileSync(resolve(process.env.HOME ?? "", ".pi/agent/settings.json"), "utf8"));
    if (settings.defaultProvider && settings.defaultModel) return `${settings.defaultProvider}/${settings.defaultModel}`;
  } catch { /* fall through */ }
  return "pi-local-default";
}
