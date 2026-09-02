import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { DatabaseSync } from "node:sqlite";

const SRC_DIR = dirname(fileURLToPath(import.meta.url));
export const ADS_PROJECT_ROOT = resolve(SRC_DIR, "..");
export const ADS_WORKBENCH_ROOT = resolve(ADS_PROJECT_ROOT, "..", "09-工作台");
export const DEFAULT_ADS_AGENT_DB = resolve(
  ADS_WORKBENCH_ROOT,
  "modules/ads/derived/ads_agent_state.sqlite",
);
const FACT_BRIDGE = resolve(ADS_PROJECT_ROOT, "scripts/ads_agent_facts.py");

export const ADS_OUTPUT_POINTS = ["A1", "B0b", "B0cd", "B0e", "B1", "B2", "B3", "B3b", "B4"] as const;
export type AdsOutputPoint = (typeof ADS_OUTPUT_POINTS)[number];
export const ADS_EVIDENCE_TYPES = [
  "PRODUCT_GOAL", "INVENTORY_CONTEXT", "SALES_HISTORY", "BUSINESS_EVENT",
  "AD_PERFORMANCE", "CAMPAIGN_CONTROL", "AD_STRUCTURE",
  "KEYWORD_POSITION", "COMPETITOR_MARKET",
] as const;
export type AdsEvidenceType = (typeof ADS_EVIDENCE_TYPES)[number];
export type JsonObject = Record<string, any>;

export type AdsEvidence = {
  evidence_id: string;
  evidence_type: AdsEvidenceType;
  subject_kind: string;
  subject_id: string;
  observed_at: string;
  valid_as_of: string;
  payload: JsonObject;
  value_origin: "direct" | "derived" | "constructed";
  source_ref: string;
};

export type WorkbenchAdsContextMeta = {
  child_asin: string;
  context_hash: string;
  context_id: string;
  data_as_of: string;
};

export type AdsB0bConstraint = {
  constraint_id: string;
  goal_version: string;
  kind: "hard" | "observe";
  domain: "inventory" | "cost" | "traffic" | "event";
  label: string;
  detail: string;
  is_satisfied: 0 | 1 | null;
  evidence_ref: string;
};

export type AdsAgentRawFacts = {
  ok: boolean;
  run_type: "child_decision";
  subject_kind: "child_asin";
  subject_id: string;
  child_asin: string;
  source_data_as_of: string;
  source_context_id: string;
  input_digest: string;
  dataset_version: string;
  rule_version: string;
  mode: "正式判断" | "条件性判断" | "暂时无法判断";
  condition: string;
  goal_version: string;
  operator_goal: JsonObject;
  identity: JsonObject;
  upstream_inventory_agent: JsonObject;
  input_limits: string[];
  evidence: AdsEvidence[];
  evidence_index: AdsEvidence[];
  open_output_point: "B0b";
  output_contract: JsonObject;
};

export type AdsAgentFacts = Omit<
  AdsAgentRawFacts,
  "source_data_as_of" | "source_context_id"
> & WorkbenchAdsContextMeta;

export type AdsAgentRun = {
  run_id: string;
  run_type: "child_decision";
  subject_kind: "child_asin";
  subject_id: string;
  child_asin: string;
  data_as_of: string;
  context_hash: string;
  context_id: string;
  trigger: "manual";
  model_version: string;
  method_version: "ads-agent-v2-b0b-seam" | "ads-agent-v2-child-decision";
  schema_version: "ads-agent-contract-v2";
  dataset_version: string;
  rule_version: string;
  status: "running" | "completed" | "failed";
  mode: AdsAgentFacts["mode"];
  condition: string;
  created_at: string;
  completed_at: string | null;
};

export const ADS_CHILD_DECISION_POINTS = ["B0b", "B0cd", "B0e", "B1", "B2", "B3", "B3b", "B4"] as const;
export type AdsChildDecisionPoint = (typeof ADS_CHILD_DECISION_POINTS)[number];

const JUDGMENT_MODES = ["formal", "conditional", "unable"] as const;
const TASK_TYPES = [
  "VERIFY_INBOUND_BEFORE_SCALE", "PROTECT_CORE_QUERY_VISIBILITY",
  "CONTROL_EFFICIENCY_DRIFT", "CLARIFY_ATTRIBUTION_BOUNDARY",
  "ACCELERATE_SELL_THROUGH", "CLEAR_AGED_INVENTORY",
  "COVER_MATCHED_QUERY_GAP",
] as const;
const TASK_DIRECTIONS = ["ADJUST", "BUILD", "OBSERVE", "PREREQUISITE", "REQUEST_INFO"] as const;
const DIAGNOSIS_TYPES = [
  "REQUIRED_TASK_MISSING", "MIXED_PURPOSE_GROUP", "GOAL_PURPOSE_MISMATCH",
  "ATTRIBUTION_UNCLEAR", "KEYWORD_COVERAGE_GAP", "INVENTORY_COVERAGE_RISK",
] as const;
export const DIAGNOSIS_COVERAGE_TYPES = [
  "GOAL_PURPOSE_MISMATCH", "MIXED_PURPOSE_GROUP", "ATTRIBUTION_UNCLEAR",
  "KEYWORD_COVERAGE_GAP", "INVENTORY_COVERAGE_RISK", "REQUIRED_TASK_MISSING",
  "DUPLICATE_TASK_OWNERS", "PERFORMANCE_NOT_SUPPORTING", "COMPETITOR_NO_TASK",
  "INSUFFICIENT_EVIDENCE",
] as const;
const RECOMMENDATION_DIRECTIONS = [
  "KEEP", "OBSERVE", "ADJUST", "PAUSE", "RESUME", "SPLIT", "MERGE",
  "BUILD", "TEST", "DEFER", "REQUEST_INFO", "PREREQUISITE",
] as const;

const POINT_KEYS: Record<Exclude<AdsChildDecisionPoint, "B0b" | "B0cd">, string[]> = {
  B0e: ["issue_id", "issue_type", "ad_object_id", "label", "detail", "evidence_ids"],
  B1: [
    "task_id", "decision_id", "goal_version", "task_type", "task_direction", "priority",
    "target_scope", "constraints", "evaluation_direction", "stop_condition", "applies_from",
    "applies_to", "rule_status", "exact_budget", "exact_bid", "exact_placement_adjustment",
    "exact_values_withheld", "evidence_ids", "inventory_constrained", "judgment_mode",
  ],
  B2: [
    "mapping_id", "task_id", "ad_object_id", "coverage_status", "attribution_limit",
    "target_fit", "result_supports_purpose", "gap_source", "basis_level",
    "is_automatic_error", "note", "evidence_ids", "judgment_mode",
  ],
  B3: [
    "diagnosis_id", "task_id", "problem_type", "what_happened", "impacted_goal", "priority",
    "confidence", "basis_type", "uncertainty", "missing_input", "check_direction",
    "causal_claim", "evidence_ids", "judgment_mode",
  ],
  B3b: ["problem_type", "hit", "why_not"],
  B4: [
    "recommendation_id", "diagnosis_id", "product_goal_version", "ad_purpose", "ad_object_id",
    "structure_gap_id", "direction", "rationale", "preconditions", "risks", "uncertainty",
    "observation_metrics", "review_windows", "d7_not_required", "rule_status", "exact_value",
    "exact_values_withheld", "evidence_ids", "judgment_mode",
  ],
};

function isOneOf(value: unknown, choices: readonly string[]): boolean {
  return typeof value === "string" && choices.includes(value);
}

function strictKeys(item: JsonObject, keys: string[], prefix: string, errors: string[]): void {
  if (stable(Object.keys(item).sort()) !== stable([...keys].sort())) errors.push(`${prefix} 字段集合不符合契约`);
  for (const key of Object.keys(item)) if (key.endsWith("_label")) errors.push(`${prefix} 不得输出译名字段 ${key}`);
}

function validateEvidenceIds(
  facts: AdsAgentFacts,
  value: unknown,
  prefix: string,
  errors: string[],
): string[] {
  if (!Array.isArray(value) || value.length < 1 || !value.every((id) => typeof id === "string")) {
    errors.push(`${prefix} evidence_ids 必须是非空字符串数组`);
    return [];
  }
  const known = new Set(facts.evidence_index.map((item) => item.evidence_id));
  const ids = value as string[];
  for (const id of ids) if (!known.has(id)) errors.push(`${prefix} evidence_id 悬空：${id}`);
  if (new Set(ids).size !== ids.length) errors.push(`${prefix} evidence_ids 重复`);
  return ids;
}

function validateCommonJudgment(item: JsonObject, prefix: string, errors: string[]): void {
  if (!isOneOf(item.judgment_mode, JUDGMENT_MODES)) errors.push(`${prefix} judgment_mode 不在词表`);
}

export function validateAdsOutputPoint(
  facts: AdsAgentFacts,
  point: AdsChildDecisionPoint,
  items: JsonObject[],
  accepted: Partial<Record<AdsChildDecisionPoint, JsonObject[]>> = {},
): string[] {
  if (point === "B0b") return validateB0bConstraints(facts, items as AdsB0bConstraint[]);
  const errors: string[] = [];
  if (!Array.isArray(items)) return [`${point} 必须是数组`];
  if (point !== "B3b" && (items.length < 1 || items.length > 20)) return [`${point} 必须输出 1–20 条`];
  const ids = new Set<string>();
  const taskIds = new Set((accepted.B1 ?? []).map((item) => item.task_id));
  const diagnosisIds = new Set((accepted.B3 ?? []).map((item) => item.diagnosis_id));
  const goalLabel = String(facts.operator_goal.goal_label ?? facts.operator_goal.product_goal_label ?? "");

  for (const [index, item] of items.entries()) {
    const prefix = `${point}[${index + 1}]`;
    if (!item || typeof item !== "object" || Array.isArray(item)) {
      errors.push(`${prefix} 不是对象`);
      continue;
    }
    if (point === "B0cd") {
      if (item.item_kind === "keyword_match") {
        strictKeys(item, ["item_kind", "match_id", "kw_id", "match_level", "demand_side", "product_side", "basis", "evidence_ids"], prefix, errors);
        if (!isOneOf(item.match_level, ["high", "medium", "low"])) errors.push(`${prefix} match_level 不在词表`);
        if (!String(item.match_id ?? "").startsWith("match_")) errors.push(`${prefix} match_id 格式无效`);
        const refs = validateEvidenceIds(facts, item.evidence_ids, prefix, errors);
        if (!refs.some((id) => id.startsWith(`keyword.position.${facts.child_asin}.`))) errors.push(`${prefix} 必须引用当前子 ASIN 的关键词位置证据`);
      } else if (item.item_kind === "competitor_pressure") {
        strictKeys(item, ["item_kind", "pressure_id", "competitor_asin", "brand", "pressure_type", "detail", "is_verified", "observed_at", "evidence_ids"], prefix, errors);
        if (!isOneOf(item.pressure_type, ["price", "promotion", "rank", "sales", "traffic", "keyword_entry"])) errors.push(`${prefix} pressure_type 不在词表`);
        if (![0, 1].includes(item.is_verified)) errors.push(`${prefix} is_verified 只能为 0/1`);
        const refs = validateEvidenceIds(facts, item.evidence_ids, prefix, errors);
        if (!refs.some((id) => id.includes(`.${item.competitor_asin}.`))) errors.push(`${prefix} 竞品主体与依据不一致`);
        errors.push(...validateTextNumbersAcrossEvidence(facts, String(item.detail ?? ""), refs).map((error) => `${prefix} ${error}`));
      } else errors.push(`${prefix} item_kind 只能是 keyword_match/competitor_pressure`);
      continue;
    }

    strictKeys(item, POINT_KEYS[point], prefix, errors);
    if ((["B1", "B2", "B3", "B4"] as string[]).includes(point)) validateCommonJudgment(item, prefix, errors);
    if (point === "B0e") {
      if (!isOneOf(item.issue_type, ["shared", "unexplained"])) errors.push(`${prefix} issue_type 不在词表`);
      validateEvidenceIds(facts, item.evidence_ids, prefix, errors);
    } else if (point === "B1") {
      if (!isOneOf(item.task_type, TASK_TYPES)) errors.push(`${prefix} task_type 不在词表`);
      if (!isOneOf(item.task_direction, TASK_DIRECTIONS)) errors.push(`${prefix} task_direction 不在词表`);
      if (!isOneOf(item.priority, ["P0", "P1", "P2", "P3"])) errors.push(`${prefix} priority 不在词表`);
      if (item.goal_version !== facts.goal_version) errors.push(`${prefix} goal_version 不一致`);
      if (!Array.isArray(item.constraints)) errors.push(`${prefix} constraints 必须是数组`);
      if (!isOneOf(item.rule_status, ["confirmed", "unconfirmed"])) errors.push(`${prefix} rule_status 不在词表`);
      if (item.rule_status !== "confirmed" && (item.exact_budget !== null || item.exact_bid !== null || item.exact_placement_adjustment !== null || item.exact_values_withheld !== true)) errors.push(`${prefix} 未确认规则必须隐藏精确值`);
      if (![0, 1].includes(item.inventory_constrained)) errors.push(`${prefix} inventory_constrained 只能为 0/1`);
      validateEvidenceIds(facts, item.evidence_ids, prefix, errors);
    } else if (point === "B2") {
      if (!taskIds.has(item.task_id)) errors.push(`${prefix} task_id 不属于 B1`);
      if (!isOneOf(item.coverage_status, ["covered", "mixed", "missing", "duplicate"])) errors.push(`${prefix} coverage_status 不在词表`);
      if (!isOneOf(item.attribution_limit, ["exclusive", "shared", "unattributed"])) errors.push(`${prefix} attribution_limit 不在词表`);
      if (!isOneOf(item.gap_source, ["structure", "evidence", "none"])) errors.push(`${prefix} gap_source 不在词表`);
      if (!isOneOf(item.basis_level, ["self_history", "conditional"])) errors.push(`${prefix} basis_level 不在词表`);
      if (![0, 1].includes(item.is_automatic_error)) errors.push(`${prefix} is_automatic_error 只能为 0/1`);
      if (item.coverage_status === "missing" && item.ad_object_id !== null) errors.push(`${prefix} missing 时 ad_object_id 必须为空`);
      validateEvidenceIds(facts, item.evidence_ids, prefix, errors);
    } else if (point === "B3") {
      if (item.task_id !== null && !taskIds.has(item.task_id)) errors.push(`${prefix} task_id 不属于 B1`);
      if (!isOneOf(item.problem_type, DIAGNOSIS_TYPES)) errors.push(`${prefix} problem_type 不在词表`);
      if (goalLabel && item.impacted_goal !== goalLabel) errors.push(`${prefix} impacted_goal 必须等于运营目标名`);
      if (!isOneOf(item.priority, ["P0", "P1", "P2"])) errors.push(`${prefix} priority 不在词表`);
      if (!isOneOf(item.confidence, ["high", "medium", "low"])) errors.push(`${prefix} confidence 不在词表`);
      if (!isOneOf(item.basis_type, ["confirmed_rule", "self_history", "peer", "conditional"])) errors.push(`${prefix} basis_type 不在词表`);
      if (item.causal_claim !== 0) errors.push(`${prefix} causal_claim 必须为 0`);
      if (item.problem_type === "REQUIRED_TASK_MISSING" && item.task_id !== null) errors.push(`${prefix} REQUIRED_TASK_MISSING 表示任务未建立，task_id 必须为空`);
      if (item.problem_type === "INVENTORY_COVERAGE_RISK" && !facts.upstream_inventory_agent.available) {
        const inventory = facts.evidence.find((entry) => entry.evidence_type === "INVENTORY_CONTEXT");
        if (inventory?.payload.stockout_flag !== 1) errors.push(`${prefix} 上游库存 Agent 缺失且当前无直接断货信号，不能把“无法判断”写成库存覆盖风险`);
      }
      validateEvidenceIds(facts, item.evidence_ids, prefix, errors);
    } else if (point === "B3b") {
      if (!isOneOf(item.problem_type, DIAGNOSIS_COVERAGE_TYPES)) errors.push(`${prefix} problem_type 不在十类词表`);
      if (![0, 1].includes(item.hit)) errors.push(`${prefix} hit 只能为 0/1`);
      if (item.hit === 0 && !String(item.why_not ?? "").trim()) errors.push(`${prefix} 未命中时 why_not 必填`);
    } else if (point === "B4") {
      if (!diagnosisIds.has(item.diagnosis_id)) errors.push(`${prefix} diagnosis_id 不属于 B3`);
      if (item.product_goal_version !== facts.goal_version) errors.push(`${prefix} product_goal_version 不一致`);
      if (!isOneOf(item.direction, RECOMMENDATION_DIRECTIONS)) errors.push(`${prefix} direction 不在词表`);
      for (const key of ["preconditions", "risks", "observation_metrics", "review_windows"]) if (!Array.isArray(item[key])) errors.push(`${prefix} ${key} 必须是数组`);
      if (![0, 1].includes(item.d7_not_required)) errors.push(`${prefix} d7_not_required 只能为 0/1`);
      if (!isOneOf(item.rule_status, ["confirmed", "unconfirmed"])) errors.push(`${prefix} rule_status 不在词表`);
      if (item.rule_status !== "confirmed" && (item.exact_value !== null || item.exact_values_withheld !== true)) errors.push(`${prefix} 未确认规则必须隐藏精确值`);
      validateEvidenceIds(facts, item.evidence_ids, prefix, errors);
    }
    const identity = String(item.issue_id ?? item.task_id ?? item.mapping_id ?? item.diagnosis_id ?? item.recommendation_id ?? item.problem_type ?? "");
    if (identity && ids.has(identity)) errors.push(`${prefix} 主键重复：${identity}`);
    ids.add(identity);
  }
  if (point === "B3b") {
    const types = items.map((item) => item.problem_type);
    if (items.length !== DIAGNOSIS_COVERAGE_TYPES.length || new Set(types).size !== DIAGNOSIS_COVERAGE_TYPES.length || DIAGNOSIS_COVERAGE_TYPES.some((type) => !types.includes(type))) errors.push("B3b 必须十类各输出一条");
    const diagnosed = new Set((accepted.B3 ?? []).map((item) => item.problem_type));
    for (const type of DIAGNOSIS_TYPES) {
      const coverage = items.find((item) => item.problem_type === type);
      if (coverage && Boolean(coverage.hit) !== diagnosed.has(type)) errors.push(`B3b ${type} 的 hit 必须与 B3 诊断一致`);
    }
  }
  return [...new Set(errors)];
}

export function stable(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stable).join(",")}]`;
  if (value && typeof value === "object") {
    const object = value as Record<string, unknown>;
    return `{${Object.keys(object).sort().map((key) => `${JSON.stringify(key)}:${stable(object[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

function shanghaiTimestamp(now = new Date()): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  }).formatToParts(now);
  const value = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${value.year}-${value.month}-${value.day}T${value.hour}:${value.minute}:${value.second}+08:00`;
}

export function loadAdsAgentRawFacts(childAsin: string): AdsAgentRawFacts {
  const normalized = childAsin.trim().toUpperCase();
  const stdout = execFileSync("/usr/bin/python3", [FACT_BRIDGE, normalized], {
    cwd: ADS_PROJECT_ROOT,
    encoding: "utf8",
    maxBuffer: 16 * 1024 * 1024,
  });
  const facts = JSON.parse(stdout) as AdsAgentRawFacts;
  if (!facts.ok) throw new Error(`没有可用于广告 Agent 的干净事实：${normalized}`);
  return facts;
}

export function bindWorkbenchContext(
  raw: AdsAgentRawFacts,
  meta: WorkbenchAdsContextMeta,
): AdsAgentFacts {
  const errors: string[] = [];
  if (meta.child_asin !== raw.child_asin) errors.push("工作台主体与事实主体不一致");
  if (meta.data_as_of !== raw.source_data_as_of) errors.push("工作台 data_as_of 与事实截止日不一致");
  if (!meta.context_id.startsWith(`${raw.source_context_id}@`)) errors.push("工作台 context_id 与决策版本不一致");
  if (!/^[a-f0-9]{64}$/.test(meta.context_hash)) errors.push("工作台 context_hash 格式无效");
  if (errors.length) throw new Error(`工作台上下文绑定失败：${errors.join("；")}`);
  const { source_data_as_of: _sourceDataAsOf, source_context_id: _sourceContextId, ...cleanRaw } = raw;
  const facts = {
    ...cleanRaw,
    child_asin: raw.child_asin,
    data_as_of: meta.data_as_of,
    context_id: meta.context_id,
    context_hash: meta.context_hash,
  } as AdsAgentFacts;
  const validationErrors = validateAdsFacts(facts);
  if (validationErrors.length) throw new Error(`广告事实门禁失败：${validationErrors.join("；")}`);
  return facts;
}

export function loadAdsAgentFacts(childAsin: string, meta: WorkbenchAdsContextMeta): AdsAgentFacts {
  return bindWorkbenchContext(loadAdsAgentRawFacts(childAsin), meta);
}

export async function fetchWorkbenchAdsContext(
  childAsin: string,
  origin = process.env.BAMBOO_WORKBENCH_ORIGIN ?? "http://127.0.0.1:18820",
): Promise<WorkbenchAdsContextMeta> {
  const normalized = childAsin.trim().toUpperCase();
  const url = new URL("/api/ads/context", origin);
  url.searchParams.set("child_asin", normalized);
  let response: Response;
  try {
    response = await fetch(url, { signal: AbortSignal.timeout(10_000) });
  } catch (error) {
    throw new Error(`无法读取工作台广告上下文：${error instanceof Error ? error.message : String(error)}`);
  }
  if (!response.ok) throw new Error(`工作台广告上下文返回 HTTP ${response.status}`);
  const body = await response.json() as JsonObject;
  const meta: WorkbenchAdsContextMeta = {
    child_asin: String(body.context?.child_asin ?? "").trim().toUpperCase(),
    context_hash: String(body.context_hash ?? ""),
    context_id: String(body.context_id ?? ""),
    data_as_of: String(body.context?.data_as_of ?? ""),
  };
  if (meta.child_asin !== normalized) throw new Error("工作台广告上下文返回了错误主体");
  if (!/^[a-f0-9]{64}$/.test(meta.context_hash) || !meta.context_id || !meta.data_as_of)
    throw new Error("工作台广告上下文缺少 context_hash/context_id/data_as_of");
  return meta;
}

function walk(value: unknown, visit: (key: string | null, value: unknown) => void, key: string | null = null): void {
  visit(key, value);
  if (Array.isArray(value)) {
    for (const item of value) walk(item, visit, null);
  } else if (value && typeof value === "object") {
    for (const [childKey, item] of Object.entries(value)) walk(item, visit, childKey);
  }
}

export function validateAdsFacts(facts: AdsAgentFacts): string[] {
  const errors: string[] = [];
  if (facts.run_type !== "child_decision") errors.push("B0b 必须属于 child_decision 运行");
  if (facts.subject_kind !== "child_asin" || facts.subject_id !== facts.child_asin)
    errors.push("B0b 主体必须是当前 child_asin");
  if (facts.open_output_point !== "B0b") errors.push("第一阶段只能开放 B0b");
  if (!facts.context_hash || facts.context_hash.length !== 64) errors.push("干净输入 context_hash 无效");
  if (!facts.goal_version || facts.operator_goal.goal_version !== facts.goal_version)
    errors.push("运营目标版本缺失或不一致");
  if (facts.operator_goal.source_ref !== "operator_set") errors.push("产品目标必须来自 operator_set");
  const indexedIds = facts.evidence_index.map((item) => item.evidence_id);
  if (new Set(indexedIds).size !== indexedIds.length) errors.push("evidence_index 存在重复 id");
  const actualIds = facts.evidence.map((item) => item.evidence_id);
  if (stable(facts.evidence) !== stable(facts.evidence_index)) errors.push("evidence_index 与干净证据不一致");
  const forbiddenKeys = new Set([
    "product_lifecycle", "lifecycle", "coverage_days", "safety_breach_date",
    "stress_stockout_date", "base_stockout_date", "latest_order_date",
    "suggested_replenishment_qty", "dynamic_safety_days", "risk_status",
    "confidence_score", "position_trend", "limited_by", "match_level",
    "pressure_type", "stage_contracts", "next_stage_contract",
  ]);
  walk(facts, (key) => {
    if (key && forbiddenKeys.has(key)) errors.push(`干净输入包含禁读字段：${key}`);
  });
  for (const item of facts.evidence) {
    if (!item.evidence_id || !item.evidence_type || !item.source_ref ||
        !item.subject_kind || !item.subject_id || !item.observed_at || !item.valid_as_of)
      errors.push("证据缺少身份、时点或来源");
    if (!ADS_EVIDENCE_TYPES.includes(item.evidence_type)) errors.push(`未知 evidence_type：${item.evidence_type}`);
    if (!/^[A-Za-z0-9_.-]+$/.test(item.evidence_id)) errors.push(`evidence_id 命名无效：${item.evidence_id}`);
    if (!( ["direct", "derived", "constructed"] as const).includes(item.value_origin))
      errors.push(`value_origin 不在词表：${item.evidence_id}`);
    if (item.evidence_type === "AD_PERFORMANCE") {
      const payload = item.payload;
      const blocks = payload.attribution_blocks ?? [];
      if (new Set(blocks.map((block: JsonObject) => block.attribution_days)).size > 1) {
        for (const key of ["aggregate_ad_sales", "aggregate_acos", "aggregate_roas"])
          if (payload[key] != null) errors.push(`跨归因窗口时 ${key} 必须为空`);
      }
    }
  }
  return [...new Set(errors)];
}

function flattenedScalars(value: unknown): Array<string | number> {
  const out: Array<string | number> = [];
  walk(value, (_key, item) => {
    if (typeof item === "number" || typeof item === "string") out.push(item);
  });
  return out;
}

function numberMatches(value: number, allowed: number[]): boolean {
  return allowed.some((candidate) => {
    const tolerances = [candidate, candidate * 100];
    return tolerances.some((expected) => {
      const decimals = (String(value).split(".")[1] ?? "").length;
      const tolerance = Math.max(1e-6, 0.51 * 10 ** -decimals);
      return Math.abs(value - expected) <= tolerance;
    });
  });
}

function validateTextNumbers(text: string, referencedEvidence: AdsEvidence): string[] {
  const errors: string[] = [];
  const scalars = flattenedScalars(referencedEvidence);
  const strings = scalars.filter((item): item is string => typeof item === "string");
  const numbers = scalars.filter((item): item is number => typeof item === "number" && Number.isFinite(item));
  const dates = text.match(/\b20\d{2}-\d{2}-\d{2}\b/g) ?? [];
  for (const found of dates) if (!strings.includes(found)) errors.push(`引用日期不在证据中：${found}`);
  const withoutDates = text.replace(/\b20\d{2}-\d{2}-\d{2}\b/g, "");
  const foundNumbers = withoutDates.match(/(?<![A-Za-z])\d+(?:\.\d+)?/g) ?? [];
  for (const raw of foundNumbers) {
    const value = Number(raw);
    if (!numberMatches(value, numbers)) errors.push(`引用数字不在证据同口径值中：${raw}`);
  }
  return errors;
}

function validateTextNumbersAcrossEvidence(facts: AdsAgentFacts, text: string, evidenceIds: string[]): string[] {
  const byId = new Map(facts.evidence_index.map((item) => [item.evidence_id, item]));
  const evidence = evidenceIds.map((id) => byId.get(id)).filter((item): item is AdsEvidence => Boolean(item));
  const scalars = flattenedScalars(evidence);
  const strings = scalars.filter((item): item is string => typeof item === "string");
  const numbers = scalars.filter((item): item is number => typeof item === "number" && Number.isFinite(item));
  const errors: string[] = [];
  const dates = text.match(/\b20\d{2}-\d{2}-\d{2}\b/g) ?? [];
  for (const found of dates) if (!strings.includes(found)) errors.push(`引用日期不在所引证据中：${found}`);
  const withoutCodes = text
    .replace(/\b20\d{2}-\d{2}-\d{2}\b/g, "")
    .replace(/[A-Za-z_][A-Za-z0-9_.-]*/g, "");
  const foundNumbers = withoutCodes.match(/\d+(?:\.\d+)?/g) ?? [];
  for (const raw of foundNumbers) if (!numberMatches(Number(raw), numbers)) errors.push(`引用数字不在所引证据同口径值中：${raw}`);
  return errors;
}

const B0B_KEYS = [
  "constraint_id", "goal_version", "kind", "domain", "label", "detail",
  "is_satisfied", "evidence_ref",
].sort();

export function validateB0bConstraints(facts: AdsAgentFacts, items: AdsB0bConstraint[]): string[] {
  const errors: string[] = [];
  if (!Array.isArray(items) || items.length < 1 || items.length > 8) return ["B0b 必须输出 1–8 条约束"];
  const ids = new Set<string>();
  const evidenceById = new Map(facts.evidence_index.map((item) => [item.evidence_id, item]));
  for (const [index, item] of items.entries()) {
    const prefix = `B0b[${index + 1}]`;
    if (!item || typeof item !== "object") {
      errors.push(`${prefix} 不是对象`);
      continue;
    }
    if (stable(Object.keys(item).sort()) !== stable(B0B_KEYS)) errors.push(`${prefix} 字段集合不符合契约`);
    if (!/^con_[A-Za-z0-9]+_\d{2}$/.test(item.constraint_id)) errors.push(`${prefix} constraint_id 格式无效`);
    if (ids.has(item.constraint_id)) errors.push(`${prefix} constraint_id 重复`);
    ids.add(item.constraint_id);
    if (item.goal_version !== facts.goal_version) errors.push(`${prefix} goal_version 不等于运营输入版本`);
    if (!(["hard", "observe"] as const).includes(item.kind)) errors.push(`${prefix} kind 不在词表`);
    if (!(["inventory", "cost", "traffic", "event"] as const).includes(item.domain)) errors.push(`${prefix} domain 不在词表`);
    if (![0, 1, null].includes(item.is_satisfied)) errors.push(`${prefix} is_satisfied 只能为 0/1/null`);
    if (typeof item.label !== "string" || item.label.length < 2 || item.label.length > 40) errors.push(`${prefix} label 长度应为 2–40 字`);
    if (typeof item.detail !== "string" || item.detail.length < 4 || item.detail.length > 180) errors.push(`${prefix} detail 长度应为 4–180 字`);
    for (const key of Object.keys(item)) if (key.endsWith("_label")) errors.push(`${prefix} 不得输出中文译名字段 ${key}`);
    const referenced = evidenceById.get(item.evidence_ref);
    if (!referenced) {
      errors.push(`${prefix} evidence_ref 悬空：${item.evidence_ref}`);
    } else {
      errors.push(...validateTextNumbers(`${item.label} ${item.detail}`, referenced).map((error) => `${prefix} ${error}`));
      const allowedTypes: Record<AdsB0bConstraint["domain"], AdsEvidenceType[]> = {
        inventory: ["INVENTORY_CONTEXT"],
        cost: ["AD_PERFORMANCE", "CAMPAIGN_CONTROL"],
        traffic: ["AD_PERFORMANCE", "SALES_HISTORY", "KEYWORD_POSITION"],
        event: ["BUSINESS_EVENT"],
      };
      if (!allowedTypes[item.domain]?.includes(referenced.evidence_type)) errors.push(`${prefix} domain=${item.domain} 与证据类型 ${referenced.evidence_type} 不匹配`);
    }
    if (facts.rule_version.includes("b0b") && facts.operator_goal && facts.mode === "条件性判断") {
      if ((item.domain === "cost" || item.domain === "traffic") && item.kind === "hard")
        errors.push(`${prefix} 客户阈值未确认，成本/流量不得升级为 hard`);
    }
    if (!facts.upstream_inventory_agent.available && item.domain === "inventory") {
      const claimsFuture = /断货|安全线|补货量|最晚下单|覆盖\s*\d/.test(`${item.label}${item.detail}`);
      if (claimsFuture) errors.push(`${prefix} 上游库存 Agent 缺失，不能输出库存投影结论`);
    }
  }
  return [...new Set(errors)];
}

const RUN_TABLE_SQL = `
CREATE TABLE IF NOT EXISTS fact_ads_agent_run (
  run_id TEXT PRIMARY KEY,
  child_asin TEXT NOT NULL,
  data_as_of TEXT NOT NULL,
  context_hash TEXT NOT NULL,
  context_id TEXT NOT NULL,
  trigger TEXT NOT NULL,
  model_version TEXT NOT NULL,
  method_version TEXT NOT NULL,
  schema_version TEXT NOT NULL,
  dataset_version TEXT NOT NULL,
  rule_version TEXT NOT NULL,
  status TEXT NOT NULL,
  mode TEXT NOT NULL,
  condition TEXT NOT NULL,
  evidence_index TEXT NOT NULL,
  diagnosis_coverage TEXT NOT NULL,
  created_at TEXT NOT NULL,
  completed_at TEXT
);`;

const OUTPUT_TABLE_SQL = `
CREATE TABLE IF NOT EXISTS fact_ads_agent_output (
  run_id TEXT NOT NULL,
  output_point TEXT NOT NULL,
  point_ord INTEGER NOT NULL,
  item_ord INTEGER NOT NULL,
  item_id TEXT NOT NULL,
  payload TEXT NOT NULL,
  PRIMARY KEY (run_id, output_point, item_ord)
);`;

export function ensureAdsAgentSchema(db: DatabaseSync): void {
  db.exec(RUN_TABLE_SQL);
  const columns = new Set(
    (db.prepare("PRAGMA table_info(fact_ads_agent_run)").all() as Array<{ name: string }>).map((row) => row.name),
  );
  if (!columns.has("run_type")) db.exec("ALTER TABLE fact_ads_agent_run ADD COLUMN run_type TEXT");
  if (!columns.has("subject_kind")) db.exec("ALTER TABLE fact_ads_agent_run ADD COLUMN subject_kind TEXT");
  if (!columns.has("subject_id")) db.exec("ALTER TABLE fact_ads_agent_run ADD COLUMN subject_id TEXT");
  db.exec(OUTPUT_TABLE_SQL);
  db.exec("CREATE INDEX IF NOT EXISTS idx_ads_agent_latest_subject ON fact_ads_agent_run(run_type, subject_kind, subject_id, status, created_at DESC)");
  db.exec("CREATE INDEX IF NOT EXISTS idx_ads_agent_output_point ON fact_ads_agent_output(run_id, output_point, point_ord, item_ord)");
}

function createRunId(facts: AdsAgentFacts, createdAt: string): string {
  const compact = createdAt.replace(/[-:T+]/g, "").replace("0800", "");
  return `${facts.subject_id}-${facts.data_as_of}-ads-agent-${compact}-${randomUUID().slice(0, 6)}`;
}

function outputItemId(point: AdsChildDecisionPoint, item: JsonObject): string {
  if (point === "B0b") return String(item.constraint_id);
  if (point === "B0cd") return String(item.match_id ?? item.pressure_id);
  if (point === "B0e") return String(item.issue_id);
  if (point === "B1") return String(item.task_id);
  if (point === "B2") return String(item.mapping_id);
  if (point === "B3") return String(item.diagnosis_id);
  if (point === "B3b") return String(item.problem_type);
  return String(item.recommendation_id);
}

export function beginAdsChildDecisionRun(
  facts: AdsAgentFacts,
  modelVersion: string,
  dbPath = DEFAULT_ADS_AGENT_DB,
): { run: AdsAgentRun; db_path: string } {
  const errors = validateAdsFacts(facts);
  if (errors.length) throw new Error(errors.join("；"));
  const createdAt = shanghaiTimestamp();
  const run: AdsAgentRun = {
    run_id: createRunId(facts, createdAt), run_type: "child_decision",
    subject_kind: "child_asin", subject_id: facts.subject_id, child_asin: facts.child_asin,
    data_as_of: facts.data_as_of, context_hash: facts.context_hash, context_id: facts.context_id,
    trigger: "manual", model_version: modelVersion, method_version: "ads-agent-v2-child-decision",
    schema_version: "ads-agent-contract-v2", dataset_version: facts.dataset_version,
    rule_version: facts.rule_version, status: "running", mode: facts.mode,
    condition: facts.condition, created_at: createdAt, completed_at: null,
  };
  mkdirSync(dirname(dbPath), { recursive: true });
  const db = new DatabaseSync(dbPath);
  try {
    ensureAdsAgentSchema(db);
    db.prepare(`INSERT INTO fact_ads_agent_run
      (run_id, run_type, subject_kind, subject_id, child_asin, data_as_of,
       context_hash, context_id, trigger, model_version, method_version,
       schema_version, dataset_version, rule_version, status, mode, condition,
       evidence_index, diagnosis_coverage, created_at, completed_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'running', ?, ?, ?, '', ?, NULL)`)
      .run(
        run.run_id, run.run_type, run.subject_kind, run.subject_id, run.child_asin,
        run.data_as_of, run.context_hash, run.context_id, run.trigger, run.model_version,
        run.method_version, run.schema_version, run.dataset_version, run.rule_version,
        run.mode, run.condition, JSON.stringify(facts.evidence_index), run.created_at,
      );
  } finally { db.close(); }
  return { run, db_path: dbPath };
}

export function appendAdsOutputPoint(
  facts: AdsAgentFacts,
  runId: string,
  point: AdsChildDecisionPoint,
  items: JsonObject[],
  accepted: Partial<Record<AdsChildDecisionPoint, JsonObject[]>>,
  dbPath = DEFAULT_ADS_AGENT_DB,
): { run_id: string; output_point: AdsChildDecisionPoint; item_count: number } {
  const errors = validateAdsOutputPoint(facts, point, items, accepted);
  if (errors.length) throw new Error(errors.join("；"));
  const pointOrd = ADS_CHILD_DECISION_POINTS.indexOf(point) + 1;
  const db = new DatabaseSync(dbPath);
  try {
    ensureAdsAgentSchema(db);
    db.exec("BEGIN IMMEDIATE");
    const run = db.prepare("SELECT status, context_hash, subject_id FROM fact_ads_agent_run WHERE run_id=?").get(runId) as JsonObject | undefined;
    if (!run || run.status !== "running") throw new Error("只能向当前 running 运行追加输出");
    if (run.context_hash !== facts.context_hash || run.subject_id !== facts.subject_id) throw new Error("运行主体或 context_hash 已变化");
    const existing = db.prepare("SELECT output_point FROM fact_ads_agent_output WHERE run_id=? GROUP BY output_point").all(runId) as Array<{ output_point: string }>;
    const existingPoints = new Set(existing.map((row) => row.output_point));
    if (existingPoints.has(point)) throw new Error(`${point} 已写入，禁止覆盖`);
    for (const required of ADS_CHILD_DECISION_POINTS.slice(0, pointOrd - 1)) if (!existingPoints.has(required)) throw new Error(`${point} 之前必须先完成 ${required}`);
    const insert = db.prepare(`INSERT INTO fact_ads_agent_output
      (run_id, output_point, point_ord, item_ord, item_id, payload) VALUES (?, ?, ?, ?, ?, ?)`);
    items.forEach((item, index) => insert.run(runId, point, pointOrd, index + 1, outputItemId(point, item), JSON.stringify(item)));
    db.exec("COMMIT");
  } catch (error) {
    try { db.exec("ROLLBACK"); } catch { /* transaction never opened */ }
    throw error;
  } finally { db.close(); }
  return { run_id: runId, output_point: point, item_count: items.length };
}

export function completeAdsChildDecisionRun(
  runId: string,
  dbPath = DEFAULT_ADS_AGENT_DB,
): { run_id: string; status: "completed"; completed_at: string; output_points: readonly AdsChildDecisionPoint[]; db_path: string } {
  const db = new DatabaseSync(dbPath);
  const completedAt = shanghaiTimestamp();
  try {
    ensureAdsAgentSchema(db);
    db.exec("BEGIN IMMEDIATE");
    const run = db.prepare("SELECT status FROM fact_ads_agent_run WHERE run_id=?").get(runId) as JsonObject | undefined;
    if (!run || run.status !== "running") throw new Error("运行不存在或不处于 running");
    const rows = db.prepare("SELECT output_point, COUNT(*) AS n FROM fact_ads_agent_output WHERE run_id=? GROUP BY output_point").all(runId) as Array<{ output_point: string; n: number }>;
    const counts = new Map(rows.map((row) => [row.output_point, Number(row.n)]));
    for (const point of ADS_CHILD_DECISION_POINTS) if (!counts.has(point) || Number(counts.get(point)) < 1) throw new Error(`运行不完整：缺少 ${point}`);
    db.prepare("UPDATE fact_ads_agent_run SET status='completed', completed_at=? WHERE run_id=?").run(completedAt, runId);
    db.exec("COMMIT");
  } catch (error) {
    try { db.exec("ROLLBACK"); } catch { /* transaction never opened */ }
    throw error;
  } finally { db.close(); }
  return { run_id: runId, status: "completed", completed_at: completedAt, output_points: ADS_CHILD_DECISION_POINTS, db_path: dbPath };
}

export function failAdsChildDecisionRun(runId: string, dbPath = DEFAULT_ADS_AGENT_DB): void {
  const db = new DatabaseSync(dbPath);
  try {
    ensureAdsAgentSchema(db);
    db.prepare("UPDATE fact_ads_agent_run SET status='failed', completed_at=? WHERE run_id=? AND status='running'").run(shanghaiTimestamp(), runId);
  } finally { db.close(); }
}

export function writeB0bSeamRun(
  facts: AdsAgentFacts,
  items: AdsB0bConstraint[],
  modelVersion: string,
  dbPath = DEFAULT_ADS_AGENT_DB,
): { run: AdsAgentRun; output_point: "B0b"; items: AdsB0bConstraint[]; db_path: string } {
  const errors = [...validateAdsFacts(facts), ...validateB0bConstraints(facts, items)];
  if (errors.length) throw new Error([...new Set(errors)].join("；"));

  const createdAt = shanghaiTimestamp();
  const compact = createdAt.replace(/[-:T+]/g, "").replace("0800", "");
  const run: AdsAgentRun = {
    run_id: `${facts.subject_id}-${facts.data_as_of}-ads-agent-${compact}-${randomUUID().slice(0, 6)}`,
    run_type: "child_decision",
    subject_kind: "child_asin",
    subject_id: facts.subject_id,
    child_asin: facts.child_asin,
    data_as_of: facts.data_as_of,
    context_hash: facts.context_hash,
    context_id: facts.context_id,
    trigger: "manual",
    model_version: modelVersion,
    method_version: "ads-agent-v2-b0b-seam",
    schema_version: "ads-agent-contract-v2",
    dataset_version: facts.dataset_version,
    rule_version: facts.rule_version,
    status: "completed",
    mode: facts.mode,
    condition: facts.condition,
    created_at: createdAt,
    completed_at: createdAt,
  };

  mkdirSync(dirname(dbPath), { recursive: true });
  const db = new DatabaseSync(dbPath);
  try {
    ensureAdsAgentSchema(db);
    db.exec("BEGIN IMMEDIATE");
    db.prepare(`INSERT INTO fact_ads_agent_run
      (run_id, run_type, subject_kind, subject_id, child_asin, data_as_of,
       context_hash, context_id, trigger, model_version, method_version,
       schema_version, dataset_version, rule_version, status, mode, condition,
       evidence_index, diagnosis_coverage, created_at, completed_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'running', ?, ?, ?, '', ?, NULL)`)
      .run(
        run.run_id, run.run_type, run.subject_kind, run.subject_id,
        run.child_asin, run.data_as_of, run.context_hash, run.context_id,
        run.trigger, run.model_version, run.method_version, run.schema_version,
        run.dataset_version, run.rule_version, run.mode, run.condition,
        JSON.stringify(facts.evidence_index), run.created_at,
      );
    const insert = db.prepare(`INSERT INTO fact_ads_agent_output
      (run_id, output_point, point_ord, item_ord, item_id, payload)
      VALUES (?, 'B0b', 1, ?, ?, ?)`);
    items.forEach((item, index) => insert.run(
      run.run_id, index + 1, item.constraint_id, JSON.stringify(item),
    ));
    db.prepare("UPDATE fact_ads_agent_run SET status='completed', completed_at=? WHERE run_id=?")
      .run(run.completed_at, run.run_id);
    db.exec("COMMIT");
  } catch (error) {
    try { db.exec("ROLLBACK"); } catch { /* transaction never opened */ }
    throw error;
  } finally {
    db.close();
  }
  return { run, output_point: "B0b", items, db_path: dbPath };
}
