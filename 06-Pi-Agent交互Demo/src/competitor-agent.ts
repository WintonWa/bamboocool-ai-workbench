import { execFileSync } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { mkdirSync, renameSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

const SRC_DIR = dirname(fileURLToPath(import.meta.url));
export const COMPETITOR_PROJECT_ROOT = resolve(SRC_DIR, '..');
export const COMPETITOR_WORKBENCH_ROOT = resolve(COMPETITOR_PROJECT_ROOT, '..', '09-工作台');
export const DEFAULT_COMPETITOR_AGENT_DB = resolve(
  COMPETITOR_WORKBENCH_ROOT, 'modules/competitor/derived/competitor_agent_state.sqlite',
);
export const DEFAULT_COMPETITOR_AGENT_JSON = resolve(
  COMPETITOR_WORKBENCH_ROOT, 'modules/competitor/derived/competitor_agent_latest.json',
);
const FACT_BRIDGE = resolve(COMPETITOR_PROJECT_ROOT, 'scripts/competitor_agent_facts.py');

export const COMPETITOR_STAGES = [
  'context', 'evidence', 'changes', 'representation', 'impacts',
  'concurrency', 'attention', 'outputs', 'contract',
] as const;
export const COMPETITOR_TOOL_NAMES = [
  'get_competitor_analysis_context',
  'assess_competitor_evidence',
  'classify_competitor_changes',
  'assess_family_representation',
  'map_competitive_impacts',
  'assess_change_concurrency',
  'assign_attention_level',
  'assemble_competitor_outputs',
  'submit_competitor_contract',
] as const;

export type JsonObject = Record<string, any>;
export type CompetitorFacts = {
  ok: boolean;
  family_asin: string;
  data_as_of: string;
  run_date: string;
  window_from: string;
  window_to: string;
  dataset_version: string;
  schema_version: 'competitor-agent-contract-v1';
  method_version: 'competitor-agent-v1';
  rule_version: string;
  source_context_hash: string;
  threshold_fingerprint: string;
  thresholds: JsonObject;
  stage_order: string[];
  family: JsonObject;
  status_events: JsonObject[];
  change_candidates: ChangeCandidate[];
  relation_candidates: JsonObject[];
  shared_keyword_candidates: JsonObject[];
  observation_coverage: JsonObject;
  threshold_effects: JsonObject;
  previous_run: JsonObject | null;
  source_boundary: JsonObject;
};
export type ChangeCandidate = {
  candidate_id: string;
  allowed_domains: string[];
  allowed_directions: string[];
  allowed_current_states: string[];
  object_level: string;
  object_id: string;
  date_from: string;
  date_to: string | null;
  magnitude_kind: string | null;
  magnitude_value: number | null;
  value_origin: string;
  evidence_gap?: boolean;
  evidence_ids: string[];
  coverage: JsonObject;
  locked_fact: string;
};
export type EvidenceDecision = {
  evidence_level: 'sufficient' | 'partial' | 'insufficient';
  evidence_reason: string;
  judgment_summary: string;
};
export type ChangeDecision = {
  candidate_id: string;
  domain: 'price_promo' | 'market' | 'keyword' | 'traffic';
  direction: 'up' | 'down' | 'neutral';
  current_state: 'still_running' | 'restored' | 'ended' | 'unconfirmed';
  label: string;
  basis: string;
  confidence: 'high' | 'medium' | 'low';
};
export type RepresentationDecision = {
  candidate_id: string;
  represents_family: boolean;
  coverage_note: string | null;
};
export type ImpactDecision = {
  candidate_id: string;
  relation_id: string;
  shared_keyword: string | null;
  pressure_dimension: 'price' | 'promo' | 'market' | 'keyword' | 'traffic';
  statement: string;
  confidence: 'high' | 'medium' | 'low';
};
export type ConcurrencyDecision = {
  change_a_id: string;
  change_b_id: string;
  relation: 'concurrent' | 'sequential' | 'independent' | 'insufficient';
  statement: string;
  missing_evidence: string | null;
};
export type AttentionDecision = {
  attention_level: 'high' | 'medium' | 'low' | 'none';
  attention_summary: string;
  reasons: Array<{ candidate_id: string | null; label: string; weight_note: string | null }>;
};
export type OutputDecision = {
  open_items: Array<{
    item_kind: 'hypothesis' | 'unconfirmed' | 'watch';
    statement: string;
    needed_data: string | null;
  }>;
  diff: {
    transition: 'new' | 'sustained' | 'escalated' | 'eased' | 'cleared';
    statement: string;
    changed_domains: Array<'price_promo' | 'market' | 'keyword' | 'traffic'>;
  };
  report: null | {
    headline: string;
    body: string;
    impact_note: string | null;
    unconfirmed_note: string | null;
  };
  handoffs: Array<{
    target_page: 'keyword' | 'advertising';
    candidate_id: string;
    relation_id: string | null;
    shared_keyword: string | null;
    pressure_dimension: 'price' | 'promo' | 'market' | 'keyword' | 'traffic';
    observable_fact: string;
  }>;
};
export type WorkflowSnapshot = {
  evidence: EvidenceDecision;
  changes: ChangeDecision[];
  representation: RepresentationDecision[];
  impacts: ImpactDecision[];
  concurrency: ConcurrencyDecision[];
  attention: AttentionDecision;
  outputs: OutputDecision;
};

const INTERNAL_ENUMS = [
  'price_promo', 'third_party_estimate', 'constructed', 'insufficient', 'sufficient',
  'partial', 'sustained', 'escalated', 'hypothesis', 'concurrent', 'family_asin',
];
const FORBIDDEN = [
  '综合威胁分数', '竞品库存', '广告预算', '提高出价', '降低出价',
  '不作为判断依据', '阈值待客户确认', '仅供参考', '黄金链', '黄金对象', '已批准', '工具拒绝',
  '工具校验', '依据工具', '当前场景', '构造场景', '场景标注', '场景判定',
];
const STATE_CN: Record<ChangeDecision['current_state'], string> = {
  still_running: '仍在进行', restored: '已恢复', ended: '已结束', unconfirmed: '无法确认',
};

function stable(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stable).join(',')}]`;
  if (value && typeof value === 'object') {
    const object = value as Record<string, unknown>;
    return `{${Object.keys(object).sort().map((key) => `${JSON.stringify(key)}:${stable(object[key])}`).join(',')}}`;
  }
  return JSON.stringify(value);
}

function textErrors(label: string, value: string | null | undefined): string[] {
  if (value == null) return [];
  const text = value.trim();
  const errors: string[] = [];
  if (!text) errors.push(`${label} 不得为空`);
  if (/\d/.test(text)) errors.push(`${label} 不得自行填写数字；数值由程序锁定`);
  for (const token of [...INTERNAL_ENUMS, ...FORBIDDEN]) {
    if (text.includes(token)) errors.push(`${label} 含禁用措辞：${token}`);
  }
  return errors;
}

function unique<T>(values: T[]): T[] {
  return [...new Set(values)];
}

function failIf(errors: string[]): void {
  const deduped = unique(errors);
  if (deduped.length) throw new Error(deduped.join('；'));
}

export function loadCompetitorFacts(
  familyAsin: string,
  thresholds?: JsonObject,
): CompetitorFacts {
  const args = [FACT_BRIDGE, familyAsin.trim().toUpperCase()];
  if (thresholds) args.push(JSON.stringify(thresholds));
  const stdout = execFileSync('/usr/bin/python3', args, {
    cwd: COMPETITOR_WORKBENCH_ROOT,
    encoding: 'utf8',
    maxBuffer: 32 * 1024 * 1024,
  });
  const facts = JSON.parse(stdout) as CompetitorFacts;
  if (!facts.ok) throw new Error(`没有可用的竞品观察事实：${familyAsin}`);
  const errors: string[] = [];
  if (stable(facts.stage_order) !== stable(COMPETITOR_STAGES)) errors.push('九步顺序不正确');
  if (!facts.source_boundary?.observation_tables_read_only) errors.push('观察库必须只读');
  if (facts.source_boundary?.historical_judgment_tables_read) errors.push('不得读取历史判断层当作答案');
  if (Object.prototype.hasOwnProperty.call(facts, 'scenario')) errors.push('事实包不得携带预制场景结论');
  if (facts.change_candidates.some((item) => item.evidence_ids.some((id) => id.startsWith('scenario:')))) {
    errors.push('变化候选不得引用预制场景结论');
  }
  if (!facts.change_candidates.length) errors.push('至少需要一个可审核变化候选');
  failIf(errors);
  return facts;
}

export class CompetitorWorkflow {
  readonly facts: CompetitorFacts;
  private expected = 1;
  private evidence?: EvidenceDecision;
  private changes?: ChangeDecision[];
  private representation?: RepresentationDecision[];
  private impacts?: ImpactDecision[];
  private concurrency?: ConcurrencyDecision[];
  private attention?: AttentionDecision;
  private outputs?: OutputDecision;

  constructor(facts: CompetitorFacts) {
    this.facts = facts;
  }

  get expectedStage(): string {
    return COMPETITOR_STAGES[this.expected]!;
  }

  private require(stage: number): void {
    if (this.expected !== stage) {
      throw new Error(`当前只能执行 ${COMPETITOR_STAGES[this.expected]}，不能跳到 ${COMPETITOR_STAGES[stage]}`);
    }
  }

  submitEvidence(value: EvidenceDecision): void {
    this.require(1);
    const errors = [
      ...textErrors('evidence_reason', value.evidence_reason),
      ...textErrors('judgment_summary', value.judgment_summary),
    ];
    const statuses = new Set(this.facts.status_events.map((item) => item.status));
    if (statuses.has('interrupted') && statuses.has('conflict') && statuses.has('stale')
        && value.evidence_level !== 'insufficient') {
      errors.push('断更、来源冲突和过期同时存在时必须判为证据不足');
    }
    const hasEvidenceGap = this.facts.change_candidates.some((item) => item.evidence_gap);
    if (hasEvidenceGap && value.evidence_level !== 'insufficient') {
      errors.push('原始观察缺失时必须判为证据不足');
    }
    if (!hasEvidenceGap && value.evidence_level === 'insufficient') {
      errors.push('当前没有可引用的观察缺口候选，不得将未参与当前判断的单个数据域缺行升级为全局证据不足');
    }
    failIf(errors);
    this.evidence = structuredClone(value);
    this.expected = 2;
  }

  submitChanges(values: ChangeDecision[]): void {
    this.require(2);
    const errors: string[] = [];
    if (!values.length) errors.push('每个 run 至少提交一条变化或稳定结论');
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
      errors.push(...textErrors(`${value.candidate_id}.label`, value.label));
      errors.push(...textErrors(`${value.candidate_id}.basis`, value.basis));
    }
    if (this.evidence?.evidence_level === 'insufficient'
        && values.some((item) => !candidates.get(item.candidate_id)?.evidence_gap)) {
      errors.push('证据不足时只能保留观察缺口结论');
    }
    failIf(errors);
    this.changes = structuredClone(values);
    this.expected = 3;
  }

  submitRepresentation(values: RepresentationDecision[]): void {
    this.require(3);
    const errors: string[] = [];
    const selected = new Set(this.changes!.map((item) => item.candidate_id));
    if (values.length !== selected.size) errors.push('整族代表性必须逐条覆盖已选变化');
    const candidates = new Map(this.facts.change_candidates.map((item) => [item.candidate_id, item]));
    const seen = new Set<string>();
    for (const value of values) {
      if (!selected.has(value.candidate_id)) errors.push(`代表性引用了未选变化：${value.candidate_id}`);
      if (seen.has(value.candidate_id)) errors.push(`代表性重复：${value.candidate_id}`);
      seen.add(value.candidate_id);
      const candidate = candidates.get(value.candidate_id);
      if (value.represents_family && !candidate?.coverage.family_eligible) errors.push(`${value.candidate_id} 的观察覆盖不允许上卷整族`);
      if (!value.represents_family && !value.coverage_note?.trim()) errors.push(`${value.candidate_id} 不代表整族时必须说明覆盖范围`);
      errors.push(...textErrors(`${value.candidate_id}.coverage_note`, value.coverage_note));
    }
    failIf(errors);
    this.representation = structuredClone(values);
    this.expected = 4;
  }

  submitImpacts(values: ImpactDecision[]): void {
    this.require(4);
    const errors: string[] = [];
    const selected = new Set(this.changes!.map((item) => item.candidate_id));
    const relations = new Map(this.facts.relation_candidates.map((item) => [item.rel_id, item]));
    const keywords = new Set(this.facts.shared_keyword_candidates.map((item) => item.keyword));
    const seen = new Set<string>();
    for (const value of values) {
      if (!selected.has(value.candidate_id)) errors.push(`影响引用了未选变化：${value.candidate_id}`);
      if (!relations.has(value.relation_id)) errors.push(`自有对象不在 bridge_competitor_child：${value.relation_id}`);
      const relation = relations.get(value.relation_id);
      if (['price', 'promo'].includes(value.pressure_dimension)
          && relation?.gap_shift_applicable && !relation.gap_shift_eligible) {
        errors.push(`${value.relation_id} 件单价倍数变动未达当前阈值`);
      }
      if (value.shared_keyword && !keywords.has(value.shared_keyword)) errors.push(`共同词不在当前候选：${value.shared_keyword}`);
      const key = `${value.candidate_id}:${value.relation_id}:${value.pressure_dimension}`;
      if (seen.has(key)) errors.push(`影响重复：${key}`);
      seen.add(key);
      errors.push(...textErrors('影响说明', value.statement));
    }
    if (this.evidence!.evidence_level === 'insufficient' && values.length) errors.push('证据不足时不得写竞争影响');
    failIf(errors);
    this.impacts = structuredClone(values);
    this.expected = 5;
  }

  submitConcurrency(values: ConcurrencyDecision[]): void {
    this.require(5);
    const errors: string[] = [];
    const selected = new Set(this.changes!.map((item) => item.candidate_id));
    for (const value of values) {
      if (!selected.has(value.change_a_id) || !selected.has(value.change_b_id)) errors.push('同期关系存在悬空变化引用');
      if (value.relation === 'concurrent' && !/\u540c\u671f|\u53ef\u80fd\u76f8\u5173/.test(value.statement)) errors.push('同期关系只能表述为“同期变化”或“可能相关”');
      if (/\u5bfc\u81f4|\u9020\u6210|\u56e0\u6b64|\u9a71\u52a8/.test(value.statement)) errors.push('禁止将同期关系升级为因果');
      errors.push(...textErrors('同期关系', value.statement));
      errors.push(...textErrors('缺失证据', value.missing_evidence));
    }
    failIf(errors);
    this.concurrency = structuredClone(values);
    this.expected = 6;
  }

  submitAttention(value: AttentionDecision): void {
    this.require(6);
    const errors = [
      ...textErrors('attention_summary', value.attention_summary),
      ...value.reasons.flatMap((item) => [
        ...textErrors('关注依据', item.label), ...textErrors('依据权重说明', item.weight_note),
      ]),
    ];
    const selected = new Set(this.changes!.map((item) => item.candidate_id));
    for (const reason of value.reasons) {
      if (reason.candidate_id && !selected.has(reason.candidate_id)) errors.push(`关注依据存在悬空引用：${reason.candidate_id}`);
      if (reason.weight_note && /\d|%/.test(reason.weight_note)) errors.push('weight_note 只允许定性说明');
    }
    if (this.evidence!.evidence_level === 'insufficient') {
      if (value.attention_level !== 'none' || value.reasons.length) errors.push('证据不足必须为 none 且零条关注依据');
    } else if (value.attention_level !== 'none' && value.reasons.length < 2) {
      errors.push('有关注等级时至少需要两条依据');
    }
    failIf(errors);
    this.attention = structuredClone(value);
    this.expected = 7;
  }

  submitOutputs(value: OutputDecision): void {
    this.require(7);
    const errors: string[] = [];
    for (const item of value.open_items) {
      errors.push(...textErrors('待观察项', item.statement));
      errors.push(...textErrors('待补数据', item.needed_data));
    }
    errors.push(...textErrors('diff.statement', value.diff.statement));
    if (!this.facts.previous_run && value.diff.transition !== 'new') {
      errors.push('首次运行的 diff.transition 必须为 new');
    }
    if (this.facts.previous_run && value.diff.transition === 'new') {
      errors.push('已有上一版时 diff.transition 不得为 new');
    }
    const selectedDomains = new Set(this.changes!.map((item) => item.domain));
    if (value.diff.changed_domains.some((domain) => !selectedDomains.has(domain))) errors.push('diff.changed_domains 含未提交的变化类型');
    const hasFamilyChange = this.representation!.some((item) => item.represents_family);
    const eligibleReport = this.evidence!.evidence_level === 'sufficient'
      && ['high', 'medium'].includes(this.attention!.attention_level) && hasFamilyChange;
    if (Boolean(value.report) !== eligibleReport) errors.push('报告只允许证据充分、高中关注且存在整族变化的 run');
    if (value.report) {
      errors.push(...textErrors('报告标题', value.report.headline));
      errors.push(...textErrors('报告正文', value.report.body));
      errors.push(...textErrors('报告影响', value.report.impact_note));
      errors.push(...textErrors('报告未确认项', value.report.unconfirmed_note));
    }
    const selected = new Set(this.changes!.map((item) => item.candidate_id));
    const relations = new Set(this.facts.relation_candidates.map((item) => item.rel_id));
    const keywords = new Set(this.facts.shared_keyword_candidates.map((item) => item.keyword));
    const targets = new Set<string>();
    for (const handoff of value.handoffs) {
      if (targets.has(handoff.target_page)) errors.push(`每个 run 每个目标页最多一条交接：${handoff.target_page}`);
      targets.add(handoff.target_page);
      if (!selected.has(handoff.candidate_id)) errors.push('交接存在悬空变化引用');
      if (handoff.relation_id && !relations.has(handoff.relation_id)) errors.push('交接存在悬空自有对象引用');
      if (handoff.shared_keyword && !keywords.has(handoff.shared_keyword)) errors.push('交接存在悬空关键词引用');
      errors.push(...textErrors('交接事实', handoff.observable_fact));
    }
    if (this.evidence!.evidence_level === 'insufficient' && value.handoffs.length) errors.push('证据不足时不得交接竞争结论');
    failIf(errors);
    this.outputs = structuredClone(value);
    this.expected = 8;
  }

  snapshot(): WorkflowSnapshot {
    this.require(8);
    return structuredClone({
      evidence: this.evidence!, changes: this.changes!, representation: this.representation!,
      impacts: this.impacts!, concurrency: this.concurrency!, attention: this.attention!, outputs: this.outputs!,
    });
  }

  markCommitted(): void {
    this.require(8);
    this.expected = 9;
  }
}

const SCHEMA = `
CREATE TABLE IF NOT EXISTS fact_competitor_agent_execution (
  task_id TEXT NOT NULL, run_id TEXT PRIMARY KEY, family_asin TEXT NOT NULL,
  status TEXT NOT NULL, trigger TEXT NOT NULL, source_context_hash TEXT NOT NULL,
  threshold_fingerprint TEXT NOT NULL, model_version TEXT NOT NULL,
  method_version TEXT NOT NULL, schema_version TEXT NOT NULL,
  dataset_version TEXT NOT NULL, rule_version TEXT NOT NULL, prev_run_id TEXT,
  created_at TEXT NOT NULL, completed_at TEXT, reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_competitor_agent_latest
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

function addDays(value: string, days: number): string {
  const date = new Date(`${value}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

function clampDate(value: string, low: string, high: string): string {
  return value < low ? low : value > high ? high : value;
}

function nextCreatedAt(db: DatabaseSync, familyAsin: string, now: Date): string {
  let value = now.toISOString();
  while (db.prepare('SELECT 1 FROM fact_competitor_agent_execution WHERE family_asin=? AND created_at=?')
    .get(familyAsin, value)) {
    value = new Date(Date.parse(value) + 1).toISOString();
  }
  return value;
}

function latestCompleted(db: DatabaseSync, familyAsin: string): JsonObject | undefined {
  return db.prepare(`SELECT * FROM fact_competitor_agent_execution
    WHERE family_asin=? AND status='completed'
    ORDER BY julianday(created_at) DESC, created_at DESC, run_id DESC LIMIT 1`)
    .get(familyAsin) as JsonObject | undefined;
}

function runSequence(db: DatabaseSync, familyAsin: string, runDate: string): number {
  const row = db.prepare(`SELECT COUNT(*) n FROM fact_competitor_agent_execution
    WHERE family_asin=? AND substr(run_id, length(?) + 2, 10)=?`)
    .get(familyAsin, familyAsin, runDate) as { n: number };
  return Number(row.n) + 1;
}

function rowsForRun(facts: CompetitorFacts, snapshot: WorkflowSnapshot, runId: string, createdAt: string, prevRunId: string | null) {
  const candidates = new Map(facts.change_candidates.map((item) => [item.candidate_id, item]));
  const rep = new Map(snapshot.representation.map((item) => [item.candidate_id, item]));
  const seq = new Map(snapshot.changes.map((item, index) => [item.candidate_id, index + 1]));
  const changes = snapshot.changes.map((item, index) => {
    const candidate = candidates.get(item.candidate_id)!;
    const representation = rep.get(item.candidate_id)!;
    return {
      run_id: runId, change_seq: index + 1, domain: item.domain,
      object_level: candidate.object_level, object_id: candidate.object_id,
      label: item.label, direction: item.direction,
      magnitude_kind: candidate.magnitude_kind, magnitude_value: candidate.magnitude_value,
      date_from: candidate.date_from, date_to: candidate.date_to,
      current_state: STATE_CN[item.current_state],
      represents_family: representation.represents_family ? 1 : 0,
      coverage_note: representation.coverage_note, value_origin: candidate.value_origin,
      confidence: item.confidence, basis: item.basis,
    };
  });
  const trackSeq = new Map<string, number>();
  const timelines: JsonObject[] = changes.map((change) => {
    const track = change.domain === 'traffic' ? 'keyword' : change.domain;
    const itemSeq = (trackSeq.get(track) ?? 0) + 1;
    trackSeq.set(track, itemSeq);
    return {
      run_id: runId, track, item_seq: itemSeq, label: change.label,
      date_from: change.date_from, date_to: change.date_to,
      ref_change_seq: change.change_seq,
      window_before_from: clampDate(addDays(change.date_from, -28), facts.window_from, facts.window_to),
      window_before_to: clampDate(addDays(change.date_from, -1), facts.window_from, facts.window_to),
      window_after_from: change.date_from,
      window_after_to: clampDate(addDays(change.date_from, 28), facts.window_from, facts.window_to),
      note: null,
    };
  });
  for (const status of facts.status_events) {
    const itemSeq = (trackSeq.get('data_status') ?? 0) + 1;
    trackSeq.set('data_status', itemSeq);
    timelines.push({
      run_id: runId, track: 'data_status', item_seq: itemSeq, label: status.label,
      date_from: status.date_from, date_to: status.date_to, ref_change_seq: null,
      window_before_from: null, window_before_to: null,
      window_after_from: null, window_after_to: null, note: status.source ?? null,
    });
  }
  const concurrency = snapshot.concurrency.map((item, index) => {
    const a = candidates.get(item.change_a_id)!;
    const b = candidates.get(item.change_b_id)!;
    const overlapFrom = a.date_from > b.date_from ? a.date_from : b.date_from;
    const aTo = a.date_to ?? facts.window_to;
    const bTo = b.date_to ?? facts.window_to;
    const overlapTo = aTo < bTo ? aTo : bTo;
    return {
      run_id: runId, pair_seq: index + 1,
      change_seq_a: seq.get(item.change_a_id)!, change_seq_b: seq.get(item.change_b_id)!,
      relation: item.relation,
      overlap_from: overlapFrom <= overlapTo ? overlapFrom : null,
      overlap_to: overlapFrom <= overlapTo ? overlapTo : null,
      statement: item.statement, causal_ready: 0, missing_evidence: item.missing_evidence,
    };
  });
  const reasons = snapshot.attention.reasons.map((item, index) => ({
    run_id: runId, reason_seq: index + 1, label: item.label,
    ref_change_seq: item.candidate_id ? seq.get(item.candidate_id) ?? null : null,
    weight_note: item.weight_note,
  }));
  const relations = new Map(facts.relation_candidates.map((item) => [item.rel_id, item]));
  const impacts = snapshot.impacts.map((item, index) => {
    const relation = relations.get(item.relation_id)!;
    return {
      run_id: runId, impact_seq: index + 1,
      own_parent_asin: relation.parent_asin, own_child_asin: relation.child_asin,
      shared_keyword: item.shared_keyword, pressure_dimension: item.pressure_dimension,
      statement: item.statement, ref_change_seq: seq.get(item.candidate_id)!, confidence: item.confidence,
    };
  });
  const openItems = snapshot.outputs.open_items.map((item, index) => ({
    run_id: runId, item_seq: index + 1, item_kind: item.item_kind,
    statement: item.statement, needed_data: item.needed_data, watch_until: null,
  }));
  const diff = {
    run_id: runId, prev_run_id: prevRunId, transition: snapshot.outputs.diff.transition,
    statement: snapshot.outputs.diff.statement,
    changed_domains: unique(snapshot.outputs.diff.changed_domains).sort().join(','),
  };
  const handoffs = snapshot.outputs.handoffs.map((item) => {
    const relation = item.relation_id ? relations.get(item.relation_id) : undefined;
    const candidate = candidates.get(item.candidate_id)!;
    const suffix = item.target_page === 'keyword' ? 'KW' : 'AD';
    return {
      handoff_id: `HO-${runId}-${suffix}`, frozen_run_id: runId,
      target_page: item.target_page, family_asin: facts.family_asin,
      own_child_asin: relation?.child_asin ?? null, shared_keyword: item.shared_keyword,
      pressure_dimension: item.pressure_dimension, observable_fact: item.observable_fact,
      evidence_level: snapshot.evidence.evidence_level,
      detail_entry: `${facts.family_asin} · ${candidate.date_from} 至 ${candidate.date_to ?? facts.window_to} · ${item.observable_fact}`,
      created_at: createdAt,
    };
  });
  return { changes, timelines, concurrency, reasons, impacts, openItems, diff, handoffs };
}

function insertRows(db: DatabaseSync, table: string, values: JsonObject[]): void {
  if (!values.length) return;
  const keys = Object.keys(values[0]!);
  const sql = `INSERT INTO ${table} (${keys.join(',')}) VALUES (${keys.map(() => '?').join(',')})`;
  const statement = db.prepare(sql);
  for (const value of values) statement.run(...keys.map((key) => value[key] ?? null));
}

export function writeCompetitorAgentRun(
  facts: CompetitorFacts,
  snapshot: WorkflowSnapshot,
  modelVersion: string,
  dbPath = DEFAULT_COMPETITOR_AGENT_DB,
  exportPath = DEFAULT_COMPETITOR_AGENT_JSON,
  now = new Date(),
): JsonObject {
  mkdirSync(dirname(dbPath), { recursive: true });
  const db = new DatabaseSync(dbPath);
  db.exec(SCHEMA);
  const createdAt = nextCreatedAt(db, facts.family_asin, now);
  const previous = latestCompleted(db, facts.family_asin);
  if (!previous && snapshot.outputs.diff.transition !== 'new') throw new Error('首次运行的 diff.transition 必须为 new');
  if (previous && snapshot.outputs.diff.transition === 'new') throw new Error('已有上一版时 diff.transition 不得为 new');
  const seqNo = runSequence(db, facts.family_asin, facts.run_date);
  const runId = `${facts.family_asin}-${facts.run_date}-${seqNo}`;
  const completedAt = createdAt;
  const taskId = `T-${facts.family_asin}-${randomUUID().slice(0, 8)}`;
  const prevRunId = previous?.run_id ?? null;
  const derived = rowsForRun(facts, snapshot, runId, createdAt, prevRunId);
  const reportCount = (db.prepare('SELECT COUNT(*) n FROM fact_competitor_analysis_report WHERE period_to=?')
    .get(facts.window_to) as { n: number }).n;
  const report = snapshot.outputs.report ? [{
    report_id: `RPT-${runId}-01`,
    scope_key: `美国站 · ${facts.family.sub_category}`,
    period_from: clampDate(addDays(facts.window_to, -27), facts.window_from, facts.window_to),
    period_to: facts.window_to, item_seq: reportCount + 1,
    family_asin: facts.family_asin, ref_run_id: runId,
    ...snapshot.outputs.report, created_at: createdAt,
  }] : [];
  const run = {
    run_id: runId, family_asin: facts.family_asin, run_date: facts.run_date,
    data_as_of: facts.data_as_of, window_from: facts.window_from, window_to: facts.window_to,
    trigger: 'manual', model_version: modelVersion,
    attention_level: snapshot.attention.attention_level,
    attention_summary: snapshot.attention.attention_summary,
    evidence_level: snapshot.evidence.evidence_level,
    evidence_reason: snapshot.evidence.evidence_reason,
    judgment_summary: snapshot.evidence.judgment_summary, created_at: createdAt,
  };
  const execution = {
    task_id: taskId, run_id: runId, family_asin: facts.family_asin, status: 'writing',
    trigger: 'manual', source_context_hash: facts.source_context_hash,
    threshold_fingerprint: facts.threshold_fingerprint, model_version: modelVersion,
    method_version: facts.method_version, schema_version: facts.schema_version,
    dataset_version: facts.dataset_version, rule_version: facts.rule_version,
    prev_run_id: prevRunId, created_at: createdAt, completed_at: null, reason: null,
  };
  try {
    db.exec('BEGIN IMMEDIATE');
    insertRows(db, 'fact_competitor_agent_execution', [execution]);
    insertRows(db, 'fact_competitor_analysis_run', [run]);
    insertRows(db, 'fact_competitor_analysis_change', derived.changes);
    insertRows(db, 'fact_competitor_analysis_timeline', derived.timelines);
    insertRows(db, 'fact_competitor_analysis_concurrency', derived.concurrency);
    insertRows(db, 'fact_competitor_analysis_attention_reason', derived.reasons);
    insertRows(db, 'fact_competitor_analysis_impact', derived.impacts);
    insertRows(db, 'fact_competitor_analysis_open_item', derived.openItems);
    insertRows(db, 'fact_competitor_analysis_diff', [derived.diff]);
    insertRows(db, 'fact_competitor_analysis_report', report);
    insertRows(db, 'fact_competitor_evidence_handoff', derived.handoffs);
    db.prepare(`UPDATE fact_competitor_agent_execution
      SET status='completed', completed_at=? WHERE run_id=?`).run(completedAt, runId);
    db.exec('COMMIT');
  } catch (error) {
    try { db.exec('ROLLBACK'); } catch { /* no active transaction */ }
    throw error;
  } finally {
    db.close();
  }
  const output = {
    contract_version: facts.schema_version,
    run: { ...run, status: 'completed', completed_at: completedAt, prev_run_id: prevRunId },
    analysis_state: snapshot.evidence.evidence_level === 'insufficient' ? 'insufficient' : 'current',
    change_count: derived.changes.length, report_count: report.length,
    handoff_count: derived.handoffs.length, db_path: dbPath, export_path: exportPath,
  };
  mkdirSync(dirname(exportPath), { recursive: true });
  const temp = `${exportPath}.${runId}.tmp`;
  writeFileSync(temp, `${JSON.stringify(output, null, 2)}\n`, 'utf8');
  renameSync(temp, exportPath);
  return output;
}
