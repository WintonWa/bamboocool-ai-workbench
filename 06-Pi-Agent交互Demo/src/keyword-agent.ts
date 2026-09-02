import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { copyFileSync, existsSync, mkdirSync, renameSync, rmSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { DatabaseSync } from "node:sqlite";

const SRC_DIR = dirname(fileURLToPath(import.meta.url));
export const KEYWORD_PROJECT_ROOT = resolve(SRC_DIR, "..");
export const KEYWORD_REBUILD_ROOT = resolve(KEYWORD_PROJECT_ROOT, "..");
export const KEYWORD_WORKBENCH_ROOT = resolve(KEYWORD_REBUILD_ROOT, "09-工作台");
export const DEFAULT_KEYWORD_BASE_DB = resolve(
  KEYWORD_REBUILD_ROOT, "07-关键词分析模块/02-数据构建/v0.1.0/keyword_demo.sqlite",
);
export const DEFAULT_KEYWORD_CURRENT_DB = resolve(
  KEYWORD_WORKBENCH_ROOT, "modules/keyword/derived/keyword_agent_current.sqlite",
);
export const DEFAULT_KEYWORD_STATE_DB = resolve(
  KEYWORD_WORKBENCH_ROOT, "modules/keyword/derived/keyword_agent_state.sqlite",
);
const FACT_BRIDGE = resolve(KEYWORD_PROJECT_ROOT, "scripts/keyword_agent_facts.py");

export const KEYWORD_STAGES = [
  "context", "market", "coverage", "evidence", "daily", "audit", "commit",
] as const;
export type KeywordStage = (typeof KEYWORD_STAGES)[number] | "completed" | "failed";
export type JsonObject = Record<string, any>;

const MARKET_TYPE_LABELS = {
  demand_up: "搜索需求上涨", demand_down: "搜索需求下滑",
  competition_up: "竞争加剧", insufficient_history: "历史样本不足",
  not_comparable: "口径变更导致不可比",
} as const;
const CONTINUITY_LABELS = {
  continuous: "连续变化", single_period: "单期波动", insufficient: "样本不足",
} as const;
const COVERAGE_TYPE_LABELS = {
  organic_gained: "新增自然覆盖", organic_lost: "丢失自然覆盖",
  organic_up: "自然位上涨", organic_down: "自然位下降",
  ad_gained: "新增广告覆盖", ad_lost: "丢失广告覆盖",
  beyond_depth: "跌出采集深度",
} as const;
const EVIDENCE_TYPE_LABELS = {
  coverage_gap: "产品覆盖缺口", scene_longtail_signal: "场景与长尾信号",
  insufficient_data: "数据不足", core_position_risk: "核心位置风险",
  inventory_limited: "库存受限机会", market_opportunity: "市场需求机会",
  pending_competitor_verification: "待竞品验证信号",
} as const;
const COMPLETENESS_LABELS = {
  full: "证据完整", partial: "证据部分可用", insufficient: "证据不足",
} as const;
const NEXT_LABELS = {
  advertising: "进入广告决策处理", competitor: "进入竞品分析验证",
  observe: "继续观察一个周期",
} as const;
const COMPETITOR_LABELS = { na: "无需竞品验证", pending: "待竞品验证" } as const;

type MarketType = keyof typeof MARKET_TYPE_LABELS;
type Continuity = keyof typeof CONTINUITY_LABELS;
type CoverageType = keyof typeof COVERAGE_TYPE_LABELS;
type EvidenceType = keyof typeof EVIDENCE_TYPE_LABELS;

export type KeywordAgentFacts = {
  ok: boolean;
  database: string;
  dataset_version: string;
  rule_version: string;
  scope: "all";
  as_of_date: string;
  site: string;
  product_line: string;
  context_hash: string;
  params: JsonObject;
  counts: {
    terms: number; market_candidates: number; coverage_candidates: number;
    evidence_candidates: number; pairs: number; children: number;
  };
  terms: JsonObject[];
  market_candidates: JsonObject[];
  coverage_candidates: JsonObject[];
  evidence_candidates: JsonObject[];
  golden: JsonObject;
};

export type MarketDecision = {
  candidate_id: string;
  event_type: MarketType | null;
  continuity: Continuity | null;
  label: string | null;
};
export type CoverageDecision = {
  candidate_id: string;
  event_type: CoverageType | null;
  continuity: "continuous" | "single_period" | null;
  label: string | null;
};
export type EvidenceDecision = {
  candidate_id: string;
  evidence_type: EvidenceType | null;
  priority: number | null;
  conclusion: string | null;
  main_basis: string | null;
  evidence_completeness: keyof typeof COMPLETENESS_LABELS | null;
  next_verification: keyof typeof NEXT_LABELS | null;
  competitor_verification_state: keyof typeof COMPETITOR_LABELS | null;
  ref_market_event_ids: string[];
  ref_coverage_event_ids: string[];
};
export type DailyDecision = {
  candidate_id: string;
  q1_traffic_result: string;
  q2_main_movers: string;
  q3_core_coverage_change: string;
  q4_new_signals: string;
  q5_priority_next: string;
  priority_evidence_ids: string[];
};

const SIDECAR_SCHEMA = `
CREATE TABLE IF NOT EXISTS fact_keyword_agent_run (
  run_id TEXT PRIMARY KEY, context_hash TEXT NOT NULL, scope TEXT NOT NULL,
  run_date TEXT, data_as_of TEXT, source_path TEXT NOT NULL,
  staging_path TEXT NOT NULL, current_path TEXT NOT NULL,
  dataset_version TEXT NOT NULL, rule_version TEXT NOT NULL,
  model_version TEXT NOT NULL, prev_run_id TEXT, resume_source_run_id TEXT,
  status TEXT NOT NULL, current_stage TEXT NOT NULL, error TEXT,
  created_at TEXT NOT NULL, completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_keyword_agent_latest
  ON fact_keyword_agent_run(status, completed_at DESC, created_at DESC);
CREATE TABLE IF NOT EXISTS fact_keyword_agent_stage (
  run_id TEXT NOT NULL, stage TEXT NOT NULL, status TEXT NOT NULL,
  accepted_count INTEGER NOT NULL DEFAULT 0,
  expected_count INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL, error TEXT, PRIMARY KEY(run_id, stage)
);`;

function ensureSidecar(db: DatabaseSync): void {
  db.exec(SIDECAR_SCHEMA);
  const existing = new Set((db.prepare("PRAGMA table_info(fact_keyword_agent_run)").all() as JsonObject[])
    .map((row) => row.name));
  for (const [name, type] of [["run_date", "TEXT"], ["data_as_of", "TEXT"], ["prev_run_id", "TEXT"], ["resume_source_run_id", "TEXT"]]) {
    if (!existing.has(name)) db.exec(`ALTER TABLE fact_keyword_agent_run ADD COLUMN ${name} ${type}`);
  }
}

export function shanghaiTimestamp(now = new Date()): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23",
  }).formatToParts(now);
  const value = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${value.year}-${value.month}-${value.day}T${value.hour}:${value.minute}:${value.second}+08:00`;
}

export function stable(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stable).join(",")}]`;
  if (value && typeof value === "object") {
    const object = value as Record<string, unknown>;
    return `{${Object.keys(object).sort().map((key) => `${JSON.stringify(key)}:${stable(object[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

export function resolveKeywordSource(
  currentPath = DEFAULT_KEYWORD_CURRENT_DB,
  statePath = DEFAULT_KEYWORD_STATE_DB,
  basePath = DEFAULT_KEYWORD_BASE_DB,
): string {
  if (!existsSync(currentPath) || !existsSync(statePath)) return basePath;
  let current: DatabaseSync | undefined;
  let state: DatabaseSync | undefined;
  try {
    current = new DatabaseSync(currentPath, { readOnly: true });
    state = new DatabaseSync(statePath, { readOnly: true });
    const manifest = current.prepare(
      "SELECT run_id, context_hash, status FROM fact_keyword_agent_manifest LIMIT 1",
    ).get() as JsonObject | undefined;
    const run = manifest && state.prepare(
      "SELECT run_id, context_hash, status FROM fact_keyword_agent_run WHERE run_id=?",
    ).get(manifest.run_id) as JsonObject | undefined;
    if (manifest?.status === "completed" && run?.status === "completed"
      && run.context_hash === manifest.context_hash) return currentPath;
  } catch {
    return basePath;
  } finally {
    current?.close(); state?.close();
  }
  return basePath;
}

export function loadKeywordAgentFacts(
  scope = "all", database = DEFAULT_KEYWORD_BASE_DB,
): KeywordAgentFacts {
  const stdout = execFileSync("/usr/bin/python3", [
    FACT_BRIDGE, "--database", database, "--scope", scope,
  ], { cwd: KEYWORD_PROJECT_ROOT, encoding: "utf8", maxBuffer: 128 * 1024 * 1024 });
  const facts = JSON.parse(stdout) as KeywordAgentFacts;
  if (!facts.ok) throw new Error(`关键词事实读取失败：${(facts as any).error ?? "unknown"}`);
  const errors = validateKeywordFacts(facts);
  if (errors.length) throw new Error(`关键词事实门禁失败：${errors.join("；")}`);
  return facts;
}

export function validateKeywordFacts(facts: KeywordAgentFacts): string[] {
  const errors: string[] = [];
  if (facts.scope !== "all") errors.push("completed 运行必须覆盖 all");
  if (facts.terms.length !== 1991 || facts.counts.terms !== 1991) errors.push("词库必须正好 1991 词");
  if (facts.counts.pairs !== 901 || facts.evidence_candidates.length !== facts.counts.pairs)
    errors.push("证据判断对象必须覆盖 901 个关键词×子体关系");
  for (const [name, items] of [
    ["market", facts.market_candidates], ["coverage", facts.coverage_candidates],
    ["evidence", facts.evidence_candidates],
  ] as const) {
    const ids = items.map((item) => item.candidate_id);
    if (ids.some((id) => !id) || new Set(ids).size !== ids.length) errors.push(`${name} candidate_id 缺失或重复`);
  }
  if (facts.counts.market_candidates !== facts.market_candidates.length) errors.push("市场候选计数不一致");
  if (facts.counts.coverage_candidates !== facts.coverage_candidates.length) errors.push("覆盖候选计数不一致");
  if (facts.counts.evidence_candidates !== facts.evidence_candidates.length) errors.push("证据候选计数不一致");
  if (facts.market_candidates.some((item) => item.source_code !== "kw3")) errors.push("市场候选混入第二来源");
  return [...new Set(errors)];
}

function batchIds(candidates: JsonObject[], decisions: JsonObject[]): string[] {
  const expected = candidates.map((item) => item.candidate_id).sort();
  const actual = decisions.map((item) => item.candidate_id).sort();
  const errors: string[] = [];
  if (actual.length !== expected.length) errors.push(`本批应提交 ${expected.length} 条，实际 ${actual.length} 条`);
  if (new Set(actual).size !== actual.length) errors.push("本批 candidate_id 重复");
  if (stable(actual) !== stable(expected)) errors.push("本批 candidate_id 与当前候选集不一致");
  return errors;
}

const INTERNAL_CODE = /\b(?:coverage_gap|scene_longtail_signal|insufficient_data|core_position_risk|inventory_limited|market_opportunity|pending_competitor_verification|organic_gained|organic_lost|organic_up|organic_down|ad_gained|ad_lost|beyond_depth|demand_up|demand_down|competition_up|insufficient_history|not_comparable|full|partial)\b/i;
const DEFENSIVE = /仅供参考|不构成建议|作为参考|免责声明/;

function numbers(value: unknown): Set<string> {
  const output = new Set<string>();
  const text = typeof value === "string" ? value : stable(value);
  for (const match of text.matchAll(/\d[\d,]*(?:\.\d+)?%?/g)) {
    output.add(match[0].replaceAll(",", "").replace(/%$/, ""));
  }
  return output;
}

function validateText(text: unknown, locked: unknown, literals: string[] = [], range?: [number, number]): string[] {
  if (typeof text !== "string" || text.trim().length < 4) return ["中文文案过短或缺失"];
  let scanned = text;
  for (const literal of literals) scanned = scanned.replaceAll(String(literal ?? ""), "");
  const errors: string[] = [];
  if (INTERNAL_CODE.test(scanned)) errors.push("上屏文案包含内部枚举码");
  if (DEFENSIVE.test(scanned)) errors.push("上屏文案包含防御性表述");
  if (range) {
    const length = [...text.trim()].length;
    if (length < range[0] || length > range[1]) errors.push(`文案长度必须为 ${range[0]}–${range[1]} 字`);
  }
  const allowed = numbers(locked);
  for (const value of numbers(scanned)) if (!allowed.has(value)) errors.push(`文案改写了确定性数字 ${value}`);
  return errors;
}

function enumOk(value: string | null, values: object, field: string): string[] {
  return value !== null && Object.hasOwn(values, value) ? [] : [`${field} 枚举非法：${value}`];
}

function nullShape(item: JsonObject, fields: string[]): string[] {
  return fields.some((field) => item[field] !== null && !(Array.isArray(item[field]) && item[field].length === 0))
    ? ["返回 null 判断时，其余判断字段也必须为空"] : [];
}

export function validateMarketBatch(candidates: JsonObject[], decisions: MarketDecision[]): string[] {
  const errors = batchIds(candidates, decisions);
  const byId = new Map(candidates.map((item) => [item.candidate_id, item]));
  for (const decision of decisions) {
    const source = byId.get(decision.candidate_id);
    if (decision.event_type === null) {
      errors.push(...nullShape(decision, ["continuity", "label"]));
      continue;
    }
    errors.push(...enumOk(decision.event_type, MARKET_TYPE_LABELS, "event_type"));
    errors.push(...enumOk(decision.continuity, CONTINUITY_LABELS, "continuity"));
    if (!source) continue;
    errors.push(...validateText(decision.label, source, [source.keyword]));
    if (decision.event_type === "demand_up" && !(source.to_value > source.from_value)) errors.push(`${decision.candidate_id} 需求上涨与数值方向相反`);
    if (decision.event_type === "demand_down" && !(source.to_value < source.from_value)) errors.push(`${decision.candidate_id} 需求下滑与数值方向相反`);
    if (decision.event_type === "competition_up" && !(
      source.to_product_count > source.from_product_count
      || source.to_ad_competitor_count > source.from_ad_competitor_count
    )) errors.push(`${decision.candidate_id} 没有竞争指标上涨`);
    if (decision.event_type === "insufficient_history" && decision.continuity !== "insufficient") errors.push("历史样本不足必须使用 insufficient");
    if (decision.event_type === "not_comparable" && source.from_comparable !== 0 && source.to_comparable !== 0) errors.push(`${decision.candidate_id} 两期均可比`);
  }
  return [...new Set(errors)];
}

export function validateCoverageBatch(candidates: JsonObject[], decisions: CoverageDecision[], rankShift = 3): string[] {
  const errors = batchIds(candidates, decisions);
  const byId = new Map(candidates.map((item) => [item.candidate_id, item]));
  for (const decision of decisions) {
    const source = byId.get(decision.candidate_id);
    if (decision.event_type === null) {
      errors.push(...nullShape(decision, ["continuity", "label"]));
      continue;
    }
    errors.push(...enumOk(decision.event_type, COVERAGE_TYPE_LABELS, "event_type"));
    if (!(decision.continuity === "continuous" || decision.continuity === "single_period")) errors.push("coverage continuity 枚举非法");
    if (!source) continue;
    errors.push(...validateText(decision.label, source, [source.keyword, source.child_asin]));
    const organic = decision.event_type.startsWith("organic_") || decision.event_type === "beyond_depth";
    const ad = decision.event_type.startsWith("ad_");
    if ((organic && source.channel !== "organic") || (ad && source.channel !== "ad")) errors.push(`${decision.candidate_id} 事件与自然/广告通道不一致`);
    if (decision.event_type.endsWith("_up") && !(source.to_rank < source.from_rank && source.from_rank - source.to_rank >= rankShift)) errors.push(`${decision.candidate_id} 位次上涨不满足方向或阈值`);
    if (decision.event_type.endsWith("_down") && !(source.to_rank > source.from_rank && source.to_rank - source.from_rank >= rankShift)) errors.push(`${decision.candidate_id} 位次下降不满足方向或阈值`);
    if (decision.event_type.endsWith("_gained") && !(source.from_rank == null && source.to_rank != null)) errors.push(`${decision.candidate_id} 新增覆盖与位次相反`);
    if (decision.event_type.endsWith("_lost") && !(source.from_rank != null && source.to_rank == null)) errors.push(`${decision.candidate_id} 丢失覆盖与位次相反`);
    if (decision.event_type === "beyond_depth" && source.from_state !== "beyond_depth" && source.to_state !== "beyond_depth") errors.push(`${decision.candidate_id} 没有超出采集深度状态`);
  }
  return [...new Set(errors)];
}

function outputEventId(prefix: "me" | "ce", candidateId: string, asOf: string): string {
  return `${prefix}_${candidateId.replace(/^(mc|cc)_/, "")}_${asOf.replaceAll("-", "")}`;
}

function allowedRefs(run: KeywordRunController, candidate: JsonObject) {
  return {
    market: new Set(run.marketEventRows.filter((item) => item.keyword_id === candidate.keyword_id).map((item) => item.event_id)),
    coverage: new Set(run.coverageEventRows.filter((item) => item.pair_id === candidate.pair_id).map((item) => item.event_id)),
  };
}

export function validateEvidenceBatch(
  run: KeywordRunController, candidates: JsonObject[], decisions: EvidenceDecision[],
): string[] {
  const errors = batchIds(candidates, decisions);
  const byId = new Map(candidates.map((item) => [item.candidate_id, item]));
  for (const decision of decisions) {
    const source = byId.get(decision.candidate_id);
    if (decision.evidence_type === null) {
      errors.push(...nullShape(decision, ["priority", "conclusion", "main_basis", "evidence_completeness", "next_verification", "competitor_verification_state", "ref_market_event_ids", "ref_coverage_event_ids"]));
      continue;
    }
    errors.push(...enumOk(decision.evidence_type, EVIDENCE_TYPE_LABELS, "evidence_type"));
    errors.push(...enumOk(decision.evidence_completeness, COMPLETENESS_LABELS, "evidence_completeness"));
    errors.push(...enumOk(decision.next_verification, NEXT_LABELS, "next_verification"));
    errors.push(...enumOk(decision.competitor_verification_state, COMPETITOR_LABELS, "competitor_verification_state"));
    if (!Number.isInteger(decision.priority) || Number(decision.priority) < 1) errors.push(`${decision.candidate_id} priority 必须为 ≥1 的整数`);
    if (!source) continue;
    errors.push(...validateText(decision.conclusion, source, [source.keyword, source.child_asin], [40, 70]));
    errors.push(...validateText(decision.main_basis, source, [source.keyword, source.child_asin]));
    const refs = allowedRefs(run, source);
    for (const id of decision.ref_market_event_ids ?? []) if (!refs.market.has(id)) errors.push(`${decision.candidate_id} 市场事件引用悬空：${id}`);
    for (const id of decision.ref_coverage_event_ids ?? []) if (!refs.coverage.has(id)) errors.push(`${decision.candidate_id} 覆盖事件引用悬空：${id}`);
    if (decision.competitor_verification_state === "pending" && decision.next_verification !== "competitor") errors.push(`${decision.candidate_id} 待竞品验证必须交给竞品分析`);
  }
  return [...new Set(errors)];
}

type KeywordRunOptions = {
  modelVersion: string;
  sourcePath?: string;
  currentPath?: string;
  statePath?: string;
  stagingPath?: string;
  batchSize?: number;
  evidenceBatchSize?: number;
  resumePath?: string;
  resumeEvidenceOffset?: number;
  resumeFromRunId?: string;
  publishCurrent?: (publishTemp: string, currentPath: string) => void;
};

export class KeywordRunController {
  readonly facts: KeywordAgentFacts;
  readonly runId: string;
  readonly prevRunId: string | null;
  readonly sourcePath: string;
  readonly currentPath: string;
  readonly statePath: string;
  readonly stagingPath: string;
  readonly completedPath: string;
  readonly batchSize: number;
  readonly evidenceBatchSize: number;
  readonly resumeFromRunId: string | null;
  readonly marketEventRows: JsonObject[] = [];
  readonly coverageEventRows: JsonObject[] = [];
  readonly evidenceRows: JsonObject[] = [];
  private readonly publishCurrent: (publishTemp: string, currentPath: string) => void;
  private offsets = { market: 0, coverage: 0, evidence: 0 };
  stage: KeywordStage = "context";

  constructor(facts: KeywordAgentFacts, options: KeywordRunOptions) {
    const errors = validateKeywordFacts(facts);
    if (errors.length) throw new Error(errors.join("；"));
    this.facts = facts;
    this.sourcePath = options.sourcePath ?? DEFAULT_KEYWORD_BASE_DB;
    this.currentPath = options.currentPath ?? DEFAULT_KEYWORD_CURRENT_DB;
    this.statePath = options.statePath ?? DEFAULT_KEYWORD_STATE_DB;
    this.batchSize = Math.min(100, Math.max(50, options.batchSize ?? 80));
    this.evidenceBatchSize = Math.min(50, Math.max(10, options.evidenceBatchSize ?? this.batchSize));
    this.resumeFromRunId = options.resumeFromRunId ?? null;
    this.publishCurrent = options.publishCurrent ?? renameSync;
    mkdirSync(dirname(this.statePath), { recursive: true });
    const state = new DatabaseSync(this.statePath);
    let seq = 1;
    let previous: JsonObject | undefined;
    try {
      ensureSidecar(state);
      previous = state.prepare(`SELECT run_id FROM fact_keyword_agent_run
        WHERE status='completed' ORDER BY completed_at DESC, created_at DESC LIMIT 1`).get() as JsonObject | undefined;
      seq = Number((state.prepare("SELECT COUNT(*) n FROM fact_keyword_agent_run WHERE run_date=?").get(facts.as_of_date) as JsonObject).n) + 1;
    } finally { state.close(); }
    this.prevRunId = previous?.run_id ?? null;
    this.runId = `keyword-all-${facts.as_of_date}-${String(seq).padStart(3, "0")}`;
    this.stagingPath = options.stagingPath ?? resolve(dirname(this.currentPath), "runs", `.${this.runId}.writing.sqlite`);
    this.completedPath = resolve(dirname(this.stagingPath), `${this.runId}.completed.sqlite`);
    mkdirSync(dirname(this.stagingPath), { recursive: true });
    copyFileSync(options.resumePath ?? this.sourcePath, this.stagingPath);
    const createdAt = shanghaiTimestamp();
    const business = new DatabaseSync(this.stagingPath);
    try {
      business.exec("BEGIN IMMEDIATE");
      if (!options.resumePath) {
        for (const table of ["fact_keyword_evidence", "fact_keyword_daily_report", "fact_keyword_market_change_event", "fact_keyword_coverage_event", "fact_keyword_audit_record"]) {
          business.exec(`DELETE FROM ${table}`);
        }
      } else {
        business.exec("DELETE FROM fact_keyword_daily_report; DELETE FROM fact_keyword_audit_record");
      }
      business.exec("DROP TABLE IF EXISTS fact_keyword_agent_manifest");
      business.exec(`CREATE TABLE fact_keyword_agent_manifest (
        run_id TEXT PRIMARY KEY, context_hash TEXT NOT NULL,
        params_json TEXT NOT NULL, status TEXT NOT NULL, completed_at TEXT)`);
      business.prepare("INSERT INTO fact_keyword_agent_manifest VALUES (?, ?, ?, 'writing', NULL)")
        .run(this.runId, facts.context_hash, JSON.stringify(facts.params));
      business.exec("COMMIT");
    } catch (error) {
      try { business.exec("ROLLBACK"); } catch { /* no transaction */ }
      throw error;
    } finally { business.close(); }
    const ledger = new DatabaseSync(this.statePath);
    try {
      ensureSidecar(ledger);
      ledger.prepare(`INSERT INTO fact_keyword_agent_run
        (run_id,context_hash,scope,run_date,data_as_of,source_path,staging_path,current_path,
         dataset_version,rule_version,model_version,prev_run_id,resume_source_run_id,
         status,current_stage,error,created_at,completed_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?, 'writing','context',NULL,?,NULL)`)
        .run(this.runId, facts.context_hash, "all", facts.as_of_date, facts.as_of_date,
          this.sourcePath, this.stagingPath, this.currentPath, facts.dataset_version,
          facts.rule_version, options.modelVersion, this.prevRunId, this.resumeFromRunId, createdAt);
      for (const name of KEYWORD_STAGES) ledger.prepare(
        "INSERT INTO fact_keyword_agent_stage VALUES (?, ?, 'pending', 0, ?, ?, NULL)",
      ).run(this.runId, name, this.expected(name), createdAt);
      if (options.resumePath) {
        const offset = Math.max(0, Math.min(facts.evidence_candidates.length, options.resumeEvidenceOffset ?? 0));
        this.offsets.market = facts.market_candidates.length;
        this.offsets.coverage = facts.coverage_candidates.length;
        this.offsets.evidence = offset;
        this.stage = "evidence";
        ledger.prepare("UPDATE fact_keyword_agent_run SET current_stage='evidence' WHERE run_id=?").run(this.runId);
        for (const [stage, accepted] of [["context", 1], ["market", this.offsets.market], ["coverage", this.offsets.coverage]] as const) {
          ledger.prepare("UPDATE fact_keyword_agent_stage SET status='completed',accepted_count=?,updated_at=? WHERE run_id=? AND stage=?")
            .run(accepted, createdAt, this.runId, stage);
        }
        ledger.prepare("UPDATE fact_keyword_agent_stage SET status='writing',accepted_count=?,updated_at=? WHERE run_id=? AND stage='evidence'")
          .run(offset, createdAt, this.runId);
      }
    } finally { ledger.close(); }
    if (options.resumePath) {
      const resumed = new DatabaseSync(this.stagingPath, { readOnly: true });
      try {
        this.marketEventRows.push(...resumed.prepare("SELECT * FROM fact_keyword_market_change_event ORDER BY event_id").all() as JsonObject[]);
        this.coverageEventRows.push(...resumed.prepare("SELECT * FROM fact_keyword_coverage_event ORDER BY event_id").all() as JsonObject[]);
        this.evidenceRows.push(...resumed.prepare("SELECT * FROM fact_keyword_evidence ORDER BY evidence_id").all() as JsonObject[]);
      } finally { resumed.close(); }
    }
  }

  private expected(stage: (typeof KEYWORD_STAGES)[number]): number {
    if (stage === "market") return this.facts.market_candidates.length;
    if (stage === "coverage") return this.facts.coverage_candidates.length;
    if (stage === "evidence") return this.facts.evidence_candidates.length;
    if (stage === "daily") return 14;
    if (stage === "audit") return this.facts.counts.children;
    return 1;
  }

  private mark(stage: KeywordStage, status: string, accepted = 0, error?: string): void {
    this.stage = stage;
    const db = new DatabaseSync(this.statePath);
    try {
      db.prepare("UPDATE fact_keyword_agent_run SET current_stage=?, error=? WHERE run_id=?")
        .run(stage, error ?? null, this.runId);
      if (KEYWORD_STAGES.includes(stage as any)) db.prepare(
        "UPDATE fact_keyword_agent_stage SET status=?, accepted_count=?, updated_at=?, error=? WHERE run_id=? AND stage=?",
      ).run(status, accepted, shanghaiTimestamp(), error ?? null, this.runId, stage);
    } finally { db.close(); }
  }

  acceptContext(contextHash: string): void {
    if (this.stage !== "context") throw new Error("当前不允许提交 context");
    if (contextHash !== this.facts.context_hash) throw new Error("context hash 不一致");
    this.mark("context", "completed", 1);
    this.mark("market", "writing", 0);
  }

  private slice(kind: keyof typeof this.offsets, items: JsonObject[]): JsonObject[] {
    const size = kind === "evidence" ? this.evidenceBatchSize : this.batchSize;
    return items.slice(this.offsets[kind], this.offsets[kind] + size);
  }

  progressToken(): string {
    return `${this.stage}:${this.offsets.market}:${this.offsets.coverage}:${this.offsets.evidence}`;
  }

  nextMarketBatch(): JsonObject[] { return this.slice("market", this.facts.market_candidates); }
  nextCoverageBatch(): JsonObject[] { return this.slice("coverage", this.facts.coverage_candidates); }
  nextEvidenceBatch(): JsonObject[] {
    return this.slice("evidence", this.facts.evidence_candidates).map((candidate) => {
      const refs = allowedRefs(this, candidate);
      return { ...candidate, allowed_market_event_ids: [...refs.market], allowed_coverage_event_ids: [...refs.coverage] };
    });
  }

  submitMarket(decisions: MarketDecision[]): void {
    if (this.stage !== "market") throw new Error("当前不允许提交市场事件");
    const candidates = this.nextMarketBatch();
    const errors = validateMarketBatch(candidates, decisions);
    if (errors.length) throw new Error(errors.join("；"));
    const byId = new Map(candidates.map((item) => [item.candidate_id, item]));
    this.write((db) => {
      const insert = db.prepare(`INSERT INTO fact_keyword_market_change_event VALUES
        (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`);
      for (const decision of decisions) {
        if (decision.event_type === null) continue;
        const source = byId.get(decision.candidate_id)!;
        let fromValue = source.from_value, toValue = source.to_value;
        if (decision.event_type === "competition_up") {
          const productDelta = Number(source.to_product_count ?? 0) - Number(source.from_product_count ?? 0);
          const adDelta = Number(source.to_ad_competitor_count ?? 0) - Number(source.from_ad_competitor_count ?? 0);
          if (productDelta >= adDelta) { fromValue = source.from_product_count; toValue = source.to_product_count; }
          else { fromValue = source.from_ad_competitor_count; toValue = source.to_ad_competitor_count; }
        }
        const ratio = fromValue == null || Number(fromValue) === 0 || toValue == null
          ? null : (Number(toValue) - Number(fromValue)) / Number(fromValue);
        const eventId = outputEventId("me", decision.candidate_id, this.facts.as_of_date);
        const row = { ...source, event_id: eventId, from_value: fromValue, to_value: toValue,
          change_ratio: ratio, ...decision };
        this.marketEventRows.push(row);
        insert.run(eventId, source.keyword_id, source.keyword, source.period_type,
          decision.event_type, MARKET_TYPE_LABELS[decision.event_type], source.from_snapshot_id,
          source.to_snapshot_id, source.from_period_end, source.to_period_end, fromValue, toValue,
          ratio, decision.continuity, CONTINUITY_LABELS[decision.continuity!],
          this.term(source.keyword_id)?.operator_role_label ?? null, decision.label,
          this.facts.rule_version, "agent");
      }
    });
    this.offsets.market += decisions.length;
    if (this.offsets.market === this.facts.market_candidates.length) {
      this.mark("market", "completed", this.offsets.market); this.mark("coverage", "writing", 0);
    } else this.mark("market", "writing", this.offsets.market);
  }

  submitCoverage(decisions: CoverageDecision[]): void {
    if (this.stage !== "coverage") throw new Error("当前不允许提交覆盖事件");
    const candidates = this.nextCoverageBatch();
    const errors = validateCoverageBatch(candidates, decisions, Number(this.facts.params.rank_shift));
    if (errors.length) throw new Error(errors.join("；"));
    const byId = new Map(candidates.map((item) => [item.candidate_id, item]));
    this.write((db) => {
      const insert = db.prepare("INSERT INTO fact_keyword_coverage_event VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)");
      for (const decision of decisions) {
        if (decision.event_type === null) continue;
        const source = byId.get(decision.candidate_id)!;
        const eventId = outputEventId("ce", decision.candidate_id, this.facts.as_of_date);
        const row = { ...source, event_id: eventId, ...decision };
        this.coverageEventRows.push(row);
        insert.run(eventId, source.pair_id, source.keyword_id, source.keyword, source.child_asin,
          decision.event_type, COVERAGE_TYPE_LABELS[decision.event_type], source.from_date,
          source.to_date, source.from_rank, source.to_rank,
          source.operator_role === "core" ? 1 : 0, decision.continuity,
          decision.label, this.facts.rule_version, "agent");
      }
    });
    this.offsets.coverage += decisions.length;
    if (this.offsets.coverage === this.facts.coverage_candidates.length) {
      this.mark("coverage", "completed", this.offsets.coverage); this.mark("evidence", "writing", 0);
    } else this.mark("coverage", "writing", this.offsets.coverage);
  }

  submitEvidence(decisions: EvidenceDecision[]): void {
    if (this.stage !== "evidence") throw new Error("当前不允许提交证据");
    const candidates = this.nextEvidenceBatch();
    const errors = validateEvidenceBatch(this, candidates, decisions);
    if (errors.length) throw new Error(errors.join("；"));
    const byId = new Map(candidates.map((item) => [item.candidate_id, item]));
    this.write((db) => {
      const insert = db.prepare(`INSERT INTO fact_keyword_evidence VALUES
        (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`);
      for (const decision of decisions) {
        if (decision.evidence_type === null) continue;
        const source = byId.get(decision.candidate_id)!;
        const evidenceId = `ev_${source.pair_id}_${this.facts.as_of_date.replaceAll("-", "")}`;
        const row = { ...source, evidence_id: evidenceId, ...decision };
        this.evidenceRows.push(row);
        insert.run(evidenceId, source.keyword_id, source.keyword, source.child_asin, source.pair_id,
          decision.evidence_type, EVIDENCE_TYPE_LABELS[decision.evidence_type], decision.priority,
          decision.conclusion, decision.main_basis, source.product_goal_label,
          source.push_role_label, source.absorb_state_label,
          decision.evidence_completeness, COMPLETENESS_LABELS[decision.evidence_completeness!],
          decision.next_verification, NEXT_LABELS[decision.next_verification!],
          decision.competitor_verification_state,
          COMPETITOR_LABELS[decision.competitor_verification_state!],
          JSON.stringify(decision.ref_market_event_ids ?? []),
          JSON.stringify(decision.ref_coverage_event_ids ?? []), source.ref_position_date,
          this.facts.as_of_date, this.facts.rule_version, "agent");
      }
    });
    this.offsets.evidence += decisions.length;
    if (this.offsets.evidence === this.facts.evidence_candidates.length) {
      this.mark("evidence", "completed", this.offsets.evidence); this.mark("daily", "writing", 0);
    } else this.mark("evidence", "writing", this.offsets.evidence);
  }

  dailyContexts(): JsonObject[] {
    if (this.stage !== "daily") throw new Error("当前不允许读取日报契约");
    const db = new DatabaseSync(this.stagingPath, { readOnly: true });
    try {
      const traffic = db.prepare(`SELECT date,
        SUM(COALESCE(organic_sessions,0)+COALESCE(ad_clicks,0)) value
        FROM fact_keyword_child_traffic_daily GROUP BY date ORDER BY date`).all() as JsonObject[];
      const last = traffic.slice(-14);
      const byDate = new Map(traffic.map((row) => [row.date, Number(row.value)]));
      const allDates = traffic.map((row) => row.date);
      const offset = this.facts.params.compare === "week" ? 7 : this.facts.params.compare === "4week" ? 28 : 1;
      return last.map((row) => {
        const index = allDates.indexOf(row.date);
        const baseDate = allDates[index - offset] ?? null;
        const baseValue = baseDate ? byDate.get(baseDate) ?? null : null;
        const value = Number(row.value);
        const delta = baseValue == null || baseValue === 0 ? null : (value - baseValue) / baseValue;
        const market = this.marketEventRows.filter((item) => item.to_period_end === row.date);
        const coverage = this.coverageEventRows.filter((item) => item.to_date === row.date);
        const current = row.date === this.facts.as_of_date;
        const evidence = current ? [...this.evidenceRows].sort((a, b) => a.priority - b.priority).slice(0, 3) : [];
        return {
          candidate_id: `dr_${row.date}`, report_date: row.date,
          compare_period: this.facts.params.compare,
          traffic_proxy_metric: "自然会话与广告点击合计",
          traffic_proxy_value: value, traffic_proxy_delta: delta,
          traffic_proxy_delta_pct: delta == null ? null : Number((delta * 100).toFixed(2)),
          base_date: baseDate, base_value: baseValue,
          market: {
            demand_up: market.filter((x) => x.event_type === "demand_up").length,
            demand_down: market.filter((x) => x.event_type === "demand_down").length,
            competition_up: market.filter((x) => x.event_type === "competition_up").length,
          },
          coverage: {
            gained: coverage.filter((x) => x.event_type.endsWith("_gained")).length,
            lost: coverage.filter((x) => x.event_type.endsWith("_lost")).length,
            core_events: coverage.filter((x) => x.operator_role === "core" || x.is_core_keyword === 1).length,
            all_events: coverage.length,
            significant: coverage.filter((x) => x.from_rank != null && x.to_rank != null
              && Math.abs(x.to_rank - x.from_rank) >= Number(this.facts.params.rank_shift)).length,
            children_touched: new Set(coverage.map((x) => x.child_asin)).size,
          },
          pending_evidence_count: current ? this.evidenceRows.length : 0,
          sample_children: current ? new Set(this.evidenceRows.map((x) => x.child_asin)).size : 0,
          priority_top3: evidence.map((x) => ({ evidence_id: x.evidence_id, keyword: x.keyword,
            child_asin: x.child_asin, priority: x.priority })),
          priority_evidence_ids: evidence.map((x) => x.evidence_id),
          coverage_event_ids: coverage.map((x) => x.event_id),
        };
      });
    } finally { db.close(); }
  }

  submitDaily(decisions: DailyDecision[]): void {
    if (this.stage !== "daily") throw new Error("当前不允许提交日报");
    const contexts = this.dailyContexts();
    const errors = batchIds(contexts, decisions);
    const byId = new Map(contexts.map((item) => [item.candidate_id, item]));
    const allowedEvidence = new Set(this.evidenceRows.map((item) => item.evidence_id));
    for (const decision of decisions) {
      const context = byId.get(decision.candidate_id);
      if (!context) continue;
      for (const field of ["q1_traffic_result", "q2_main_movers", "q3_core_coverage_change", "q4_new_signals", "q5_priority_next"] as const) {
        errors.push(...validateText(decision[field], context));
      }
      for (const id of decision.priority_evidence_ids) if (!allowedEvidence.has(id)) errors.push(`${decision.candidate_id} 日报证据引用悬空：${id}`);
    }
    if (errors.length) throw new Error([...new Set(errors)].join("；"));
    this.write((db) => {
      const insert = db.prepare("INSERT INTO fact_keyword_daily_report VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)");
      for (const decision of decisions) {
        const context = byId.get(decision.candidate_id)!;
        insert.run(context.report_date, this.facts.site, this.facts.product_line,
          context.compare_period, context.traffic_proxy_metric, context.traffic_proxy_value,
          context.traffic_proxy_delta, decision.q1_traffic_result, decision.q2_main_movers,
          decision.q3_core_coverage_change, decision.q4_new_signals, decision.q5_priority_next,
          JSON.stringify(decision.priority_evidence_ids), JSON.stringify(context.coverage_event_ids),
          this.facts.rule_version, "agent");
      }
    });
    this.mark("daily", "completed", decisions.length); this.mark("audit", "writing", 0);
  }

  buildAuditRecords(): void {
    if (this.stage !== "audit") throw new Error("当前不允许构建盘点记录");
    this.write((db) => {
      const children = db.prepare("SELECT DISTINCT child_asin FROM dim_keyword_child_pair ORDER BY child_asin").all() as JsonObject[];
      const insert = db.prepare("INSERT INTO fact_keyword_audit_record VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)");
      for (const { child_asin } of children) {
        const pairs = db.prepare(`SELECT p.pair_id, t.operator_role_confirmed,
          d.organic_rank, d.ad_rank FROM dim_keyword_child_pair p
          JOIN dim_keyword_term t ON t.keyword_id=p.keyword_id
          LEFT JOIN fact_keyword_child_position_daily d ON d.pair_id=p.pair_id AND d.date=?
          WHERE p.child_asin=?`).all(this.facts.as_of_date, child_asin) as JsonObject[];
        const goal = db.prepare(`SELECT product_goal_label,push_role_label,product_lifecycle
          FROM dim_keyword_child_goal WHERE child_asin=? AND is_current=1 LIMIT 1`).get(child_asin) as JsonObject | undefined;
        const absorb = db.prepare("SELECT absorb_state_label FROM fact_keyword_child_absorb WHERE child_asin=? LIMIT 1").get(child_asin) as JsonObject | undefined;
        const evidence = this.evidenceRows.filter((item) => item.child_asin === child_asin);
        const typeCounts: Record<string, number> = {};
        for (const item of evidence) typeCounts[item.evidence_type] = (typeCounts[item.evidence_type] ?? 0) + 1;
        const organic = pairs.map((x) => x.organic_rank).filter((x) => x != null).map(Number).sort((a, b) => a - b);
        const median = organic.length ? organic[Math.floor((organic.length - 1) / 2)] : null;
        insert.run(`ka_${child_asin}_${this.facts.as_of_date.replaceAll("-", "")}`, child_asin,
          this.facts.as_of_date, 1, "全部关系词", pairs.length,
          pairs.filter((x) => x.organic_rank != null).length,
          pairs.filter((x) => x.ad_rank != null).length,
          pairs.filter((x) => x.organic_rank != null && x.ad_rank != null).length,
          pairs.filter((x) => x.operator_role_confirmed !== 1).length,
          organic[0] ?? null, median, goal?.product_goal_label ?? null,
          goal?.push_role_label ?? null, goal?.product_lifecycle ?? null,
          absorb?.absorb_state_label ?? null, evidence.length, JSON.stringify(typeCounts),
          this.facts.as_of_date, this.facts.rule_version, "agent");
      }
    });
    this.mark("audit", "completed", this.facts.counts.children); this.mark("commit", "writing", 0);
  }

  validateForCommit(): string[] {
    const errors: string[] = [];
    const db = new DatabaseSync(this.stagingPath, { readOnly: true });
    try {
      const terms = db.prepare(`SELECT keyword_id,library_status,operator_role,
        operator_role_label,operator_role_confirmed,operator_role_seed_word
        FROM dim_keyword_term ORDER BY keyword_id`).all() as JsonObject[];
      const expected = this.facts.terms.map((x) => ({ keyword_id: x.keyword_id,
        library_status: x.library_status, operator_role: x.operator_role,
        operator_role_label: x.operator_role_label,
        operator_role_confirmed: x.operator_role_confirmed,
        operator_role_seed_word: x.operator_role_seed_word }));
      if (stable(terms) !== stable(expected)) errors.push("V2 禁止修改词库状态或运营角色");
      const daily = Number((db.prepare("SELECT COUNT(*) n FROM fact_keyword_daily_report").get() as JsonObject).n);
      const audits = Number((db.prepare("SELECT COUNT(*) n FROM fact_keyword_audit_record").get() as JsonObject).n);
      if (daily !== 14) errors.push("动态日报必须覆盖最近 14 日");
      if (audits !== this.facts.counts.children) errors.push("盘点记录必须覆盖全部演示子体");
      const marketIds = new Set((db.prepare("SELECT event_id FROM fact_keyword_market_change_event").all() as JsonObject[]).map((x) => x.event_id));
      const coverageIds = new Set((db.prepare("SELECT event_id FROM fact_keyword_coverage_event").all() as JsonObject[]).map((x) => x.event_id));
      const evidenceIds = new Set((db.prepare("SELECT evidence_id FROM fact_keyword_evidence").all() as JsonObject[]).map((x) => x.evidence_id));
      for (const row of db.prepare("SELECT evidence_id,ref_market_event_ids,ref_coverage_event_ids FROM fact_keyword_evidence").all() as JsonObject[]) {
        try {
          for (const id of JSON.parse(row.ref_market_event_ids)) if (!marketIds.has(id)) errors.push(`${row.evidence_id} 市场引用悬空`);
          for (const id of JSON.parse(row.ref_coverage_event_ids)) if (!coverageIds.has(id)) errors.push(`${row.evidence_id} 覆盖引用悬空`);
        } catch { errors.push(`${row.evidence_id} 引用不是 JSON 数组`); }
      }
      for (const row of db.prepare("SELECT report_date,priority_evidence_ids FROM fact_keyword_daily_report").all() as JsonObject[]) {
        try { for (const id of JSON.parse(row.priority_evidence_ids)) if (!evidenceIds.has(id)) errors.push(`${row.report_date} 日报引用悬空`); }
        catch { errors.push(`${row.report_date} 日报引用不是 JSON 数组`); }
      }
      for (const row of db.prepare("SELECT child_asin,evidence_count,evidence_type_counts FROM fact_keyword_audit_record").all() as JsonObject[]) {
        const actual = db.prepare("SELECT evidence_type,COUNT(*) n FROM fact_keyword_evidence WHERE child_asin=? GROUP BY evidence_type").all(row.child_asin) as JsonObject[];
        const counts = Object.fromEntries(actual.map((x) => [x.evidence_type, Number(x.n)]));
        const total = actual.reduce((sum, x) => sum + Number(x.n), 0);
        if (Number(row.evidence_count) !== total || stable(JSON.parse(row.evidence_type_counts)) !== stable(counts)) errors.push(`${row.child_asin} 盘点证据聚合不一致`);
      }
      const integrity = (db.prepare("PRAGMA integrity_check").get() as JsonObject).integrity_check;
      if (integrity !== "ok") errors.push(`SQLite integrity_check: ${integrity}`);
    } finally { db.close(); }
    return [...new Set(errors)];
  }

  commit(): { run_id: string; context_hash: string; completed_path: string; current_path: string; state_path: string; status: "completed" } {
    if (this.stage !== "commit") throw new Error("当前不允许发布");
    const errors = this.validateForCommit();
    if (errors.length) throw new Error(errors.join("；"));
    const completedAt = shanghaiTimestamp();
    mkdirSync(dirname(this.currentPath), { recursive: true });
    mkdirSync(dirname(this.completedPath), { recursive: true });
    const completedTemp = `${this.completedPath}.tmp`;
    const publishTemp = `${this.currentPath}.${this.runId}.tmp`;
    try {
      this.write((db) => db.prepare(
        "UPDATE fact_keyword_agent_manifest SET status='completed',completed_at=? WHERE run_id=?",
      ).run(completedAt, this.runId));
      copyFileSync(this.stagingPath, completedTemp);
      renameSync(completedTemp, this.completedPath);
      copyFileSync(this.completedPath, publishTemp);
      rmSync(this.stagingPath, { force: true });
      const state = new DatabaseSync(this.statePath);
      try {
        state.exec("BEGIN IMMEDIATE");
        state.prepare("UPDATE fact_keyword_agent_stage SET status='completed',accepted_count=1,updated_at=? WHERE run_id=? AND stage='commit'").run(completedAt, this.runId);
        state.prepare("UPDATE fact_keyword_agent_run SET status='completed',current_stage='completed',completed_at=?,error=NULL WHERE run_id=?").run(completedAt, this.runId);
        state.exec("COMMIT");
      } catch (error) {
        try { state.exec("ROLLBACK"); } catch { /* no transaction */ }
        throw error;
      } finally { state.close(); }
      this.publishCurrent(publishTemp, this.currentPath);
    } catch (error) {
      rmSync(completedTemp, { force: true }); rmSync(publishTemp, { force: true });
      try { this.fail(error); } catch { this.stage = "failed"; }
      throw error;
    }
    this.stage = "completed";
    return { run_id: this.runId, context_hash: this.facts.context_hash,
      completed_path: this.completedPath, current_path: this.currentPath,
      state_path: this.statePath, status: "completed" };
  }

  fail(error: unknown): void {
    const message = error instanceof Error ? error.message : String(error);
    const db = new DatabaseSync(this.statePath);
    try {
      db.prepare("UPDATE fact_keyword_agent_run SET status='failed',current_stage='failed',error=?,completed_at=NULL WHERE run_id=?").run(message, this.runId);
      db.prepare("UPDATE fact_keyword_agent_stage SET status='failed',error=?,updated_at=? WHERE run_id=? AND stage=?").run(message, shanghaiTimestamp(), this.runId, this.stage);
    } finally { db.close(); }
    rmSync(this.stagingPath, { force: true }); this.stage = "failed";
  }

  private term(keywordId: string): JsonObject | undefined {
    return this.facts.terms.find((item) => item.keyword_id === keywordId);
  }

  private write(action: (db: DatabaseSync) => unknown): void {
    const db = new DatabaseSync(this.stagingPath);
    try { db.exec("BEGIN IMMEDIATE"); action(db); db.exec("COMMIT"); }
    catch (error) { try { db.exec("ROLLBACK"); } catch { /* no transaction */ } throw error; }
    finally { db.close(); }
  }
}

export function contextDigest(facts: KeywordAgentFacts): string {
  return createHash("sha256").update(stable({
    context_hash: facts.context_hash, counts: facts.counts, params: facts.params,
  })).digest("hex");
}
