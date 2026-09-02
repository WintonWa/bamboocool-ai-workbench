import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync, statSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import test from 'node:test';
import { DatabaseSync } from 'node:sqlite';
import {
  COMPETITOR_STAGES,
  COMPETITOR_WORKBENCH_ROOT,
  CompetitorWorkflow,
  loadCompetitorFacts,
  writeCompetitorAgentRun,
  type ChangeDecision,
  type CompetitorFacts,
  type OutputDecision,
} from '../src/competitor-agent.ts';

const SOURCE_DB = resolve(
  COMPETITOR_WORKBENCH_ROOT,
  '../08-竞品分析模块/02-数据构建/v0.1.0/competitor_demo.sqlite',
);

function buildWorkflow(facts: CompetitorFacts): CompetitorWorkflow {
  const flow = new CompetitorWorkflow(facts);
  const insufficient = facts.change_candidates.some((item) => item.evidence_gap);
  flow.submitEvidence(insufficient ? {
    evidence_level: 'insufficient',
    evidence_reason: '观察断更、来源冲突且关键词更新过期',
    judgment_summary: '观察缺口会把变化放大成假象，本次不给竞争结论',
  } : {
    evidence_level: 'sufficient',
    evidence_reason: '价格、市场与对象引用可在当前观察窗内核对',
    judgment_summary: '当前变化已达到值得进入竞争判断的程度',
  });

  const label: Record<string, [string, string]> = {
    'price-trend-1': ['常态价格带持续下移', '主销子体与已观察子体呈一致下行'],
    'market-rank-1': ['小类排名阶段变化', '小类排名变动已越过当前阈值'],
    'price-promo-1': ['单个非主销子体活动降价后恢复', '活动只落在一个非主销子体'],
    'traffic-1': ['广告流量占比阶段上行', '第三方估算流量结构呈连续上行'],
    'data-gap-1': ['观察缺口期间的价格变化无法确认', '缺口期没有连续观察记录'],
    'data-gap-keyword-1': ['关键词抢位无法确认', '当前族没有关键词位次和共同词关系记录'],
    'stable-1': ['未发现显著变化', '当前观察未达到变化阈值'],
  };
  const selectedCandidates = insufficient
    ? facts.change_candidates.filter((candidate) => candidate.evidence_gap)
    : facts.change_candidates;
  const changes = selectedCandidates.map((candidate) => ({
    candidate_id: candidate.candidate_id,
    domain: candidate.allowed_domains[0],
    direction: candidate.allowed_directions[0],
    current_state: candidate.allowed_current_states[0],
    label: label[candidate.candidate_id]?.[0] ?? '当前变化值得留意',
    basis: label[candidate.candidate_id]?.[1] ?? '观察序列支持该定性判断',
    confidence: insufficient ? 'low' : 'high',
  })) as ChangeDecision[];
  flow.submitChanges(changes);
  flow.submitRepresentation(changes.map((change) => {
    const candidate = facts.change_candidates.find((item) => item.candidate_id === change.candidate_id)!;
    const represents = Boolean(candidate.coverage.family_eligible) && !insufficient;
    return {
      candidate_id: change.candidate_id,
      represents_family: represents,
      coverage_note: represents ? null : (change.candidate_id === 'price-promo-1'
        ? '仅一个非主销子体发生变化' : '观察中断无法代表整族'),
    };
  }));

  const relation = facts.relation_candidates[0];
  const keyword = facts.shared_keyword_candidates[0]?.keyword ?? null;
  const primary = changes[0]!;
  const impacts = insufficient || !relation || facts.family_asin === 'B0D8V2L6JS' ? [] : [{
    candidate_id: primary.candidate_id, relation_id: relation.rel_id,
    shared_keyword: facts.family_asin === 'B0C81Q5KRW' ? keyword : null,
    pressure_dimension: facts.family_asin === 'B0C81Q5KRW' ? 'keyword' as const : 'price' as const,
    statement: facts.family_asin === 'B0C81Q5KRW'
      ? '共享核心词的获取难度已上升' : '常态价格带下移后与自有产品直接竞争',
    confidence: 'high' as const,
  }];
  flow.submitImpacts(impacts);

  flow.submitConcurrency(changes.length >= 2 && !insufficient ? [{
    change_a_id: changes[0]!.candidate_id, change_b_id: changes[1]!.candidate_id,
    relation: 'concurrent',
    statement: '两类变化在观察窗内同期出现，目前只判为可能相关',
    missing_evidence: '仍需转化表现与类目对照证据',
  }] : []);

  const level = insufficient ? 'none' : facts.family_asin === 'B0D8V2L6JS' ? 'low' : 'high';
  flow.submitAttention({
    attention_level: level,
    attention_summary: insufficient ? '证据不足，本次不给关注结论' : changes[0]!.label,
    reasons: level === 'none' ? [] : [
      { candidate_id: changes[0]!.candidate_id, label: '变化持续性已成立', weight_note: '持续性最强' },
      { candidate_id: changes[0]!.candidate_id, label: '变化已进入自有产品竞争范围', weight_note: '竞争关系可解析' },
    ],
  });

  const represents = changes.some((change) => facts.change_candidates
    .find((candidate) => candidate.candidate_id === change.candidate_id)?.coverage.family_eligible) && !insufficient;
  const eligibleReport = ['high', 'medium'].includes(level) && represents;
  const handoffs: OutputDecision['handoffs'] = insufficient || !relation || facts.family_asin === 'B0D8V2L6JS' ? [] : [{
    target_page: facts.family_asin === 'B0C81Q5KRW' ? 'keyword' : 'advertising',
    candidate_id: primary.candidate_id, relation_id: relation.rel_id,
    shared_keyword: facts.family_asin === 'B0C81Q5KRW' ? keyword : null,
    pressure_dimension: facts.family_asin === 'B0C81Q5KRW' ? 'keyword' : 'price',
    observable_fact: primary.label,
  }];
  flow.submitOutputs({
    open_items: [{
      item_kind: insufficient ? 'unconfirmed' : 'watch',
      statement: insufficient ? '观察中断期间是否发生过促销' : '当前变化是否会继续',
      needed_data: insufficient ? '补齐缺口期价格与活动观察' : '下一周期同口径观察',
    }],
    diff: {
      transition: facts.previous_run ? 'sustained' : 'new',
      statement: facts.previous_run ? '关注方向与上一版一致' : '本次为首次形成可追溯判断',
      changed_domains: [...new Set(changes.map((item) => item.domain))],
    },
    report: eligibleReport ? {
      headline: primary.label,
      body: '这条变化已经改变当前竞争位置，需要继续跟踪',
      impact_note: impacts[0]?.statement ?? null,
      unconfirmed_note: '变化是否会在下一观察周期延续',
    } : null,
    handoffs,
  });
  return flow;
}

function workbenchState(dbPath: string, familyAsin: string): Record<string, any> {
  const code = `
import json
from modules.competitor import compute, data
con=data.connect()
try:
 print(json.dumps(compute.detail(con, ${JSON.stringify(familyAsin)}, {
  'price_drop_pct':5.0,'gap_shift_pct':10.0,'rank_shift_pct':15.0,'kw_rank_shift':3,
  'min_duration_days':7,'family_coverage_pct':30.0,'stale_days':14,
  'sort_by':'attention','quick_only':False
 }), ensure_ascii=False))
finally: con.close()
`;
  return JSON.parse(execFileSync('/usr/bin/python3', ['-c', code], {
    cwd: COMPETITOR_WORKBENCH_ROOT, encoding: 'utf8',
    env: { ...process.env, WORKBENCH_COMPETITOR_AGENT_DB: dbPath },
  }));
}

test('事实桥只读观察层，不携带预制结论', () => {
  const expected = new Map([
    ['B0CJ9QLVPP', 'price-trend-1'], ['B0D8V2L6JS', 'price-promo-1'],
    ['B0C81Q5KRW', 'data-gap-keyword-1'], ['B0D7D246LV', 'data-gap-1'],
  ]);
  for (const [asin, candidate] of expected) {
    const facts = loadCompetitorFacts(asin);
    assert.deepEqual(facts.stage_order, COMPETITOR_STAGES);
    assert.equal(facts.source_boundary.observation_tables_read_only, true);
    assert.equal(facts.source_boundary.historical_judgment_tables_read, false);
    assert.equal(Object.prototype.hasOwnProperty.call(facts, 'scenario'), false);
    assert.equal(/dim_competitor_scenario|scenario_only|构造场景标注/.test(JSON.stringify(facts)), false);
    assert.equal(facts.change_candidates.some((item) =>
      item.evidence_ids.some((id) => id.startsWith('scenario:'))), false);
    assert.ok(facts.change_candidates.some((item) => item.candidate_id === candidate));
  }
  for (const asin of ['B0CJ9QLVPP', 'B0D8V2L6JS', 'B0C81Q5KRW']) {
    const facts = loadCompetitorFacts(asin);
    const traffic = facts.change_candidates.find((item) => item.candidate_id === 'traffic-1');
    assert.ok(traffic);
    assert.ok(traffic.evidence_ids.every((id) => id.startsWith('traffic:')));
    assert.ok(facts.threshold_effects.traffic_series.input_rows >= 2);
  }
});

test('九步状态机拒绝跳步', () => {
  const flow = new CompetitorWorkflow(loadCompetitorFacts('B0CJ9QLVPP'));
  assert.throws(() => flow.submitChanges([]), /只能执行 evidence/);
  assert.throws(() => flow.submitEvidence({
    evidence_level: 'sufficient',
    evidence_reason: '依据工具校验可以继续',
    judgment_summary: '当前证据可以进入后续判断',
  }), /工具校验/);
  assert.throws(() => flow.submitEvidence({
    evidence_level: 'insufficient',
    evidence_reason: '关键词域当前没有观察行',
    judgment_summary: '因此将整个对象判为证据不足',
  }), /没有可引用的观察缺口候选/);
});

test('局部变化无整族报告，证据不足为零依据零报告', () => {
  const local = buildWorkflow(loadCompetitorFacts('B0D8V2L6JS')).snapshot();
  assert.equal(local.representation.find((item) => item.candidate_id === 'price-promo-1')?.represents_family, false);
  assert.equal(local.outputs.report, null);
  const insufficient = buildWorkflow(loadCompetitorFacts('B0D7D246LV')).snapshot();
  assert.equal(insufficient.attention.attention_level, 'none');
  assert.equal(insufficient.attention.reasons.length, 0);
  assert.equal(insufficient.outputs.report, null);
  assert.equal(insufficient.outputs.handoffs.length, 0);
  const missingKeyword = buildWorkflow(loadCompetitorFacts('B0C81Q5KRW')).snapshot();
  assert.equal(missingKeyword.evidence.evidence_level, 'insufficient');
  assert.equal(missingKeyword.attention.attention_level, 'none');
  assert.equal(missingKeyword.outputs.report, null);
  assert.equal(missingKeyword.outputs.handoffs.length, 0);
});

test('七个业务阈值逐个进入候选、关系、资格或证据计算', () => {
  const ids = (facts: CompetitorFacts) => new Set(facts.change_candidates.map((item) => item.candidate_id));

  assert.equal(ids(loadCompetitorFacts('B0CJ9QLVPP')).has('price-trend-1'), true);
  assert.equal(ids(loadCompetitorFacts('B0CJ9QLVPP', { price_drop_pct: 30 })).has('price-trend-1'), false);

  const gapDefault = loadCompetitorFacts('B0CJ9QLVPP').relation_candidates[0]!;
  const gapStrict = loadCompetitorFacts('B0CJ9QLVPP', { gap_shift_pct: 30 }).relation_candidates[0]!;
  assert.equal(gapDefault.gap_shift_eligible, true);
  assert.equal(gapStrict.gap_shift_eligible, false);

  const standaloneMarket = loadCompetitorFacts('B08FTYHMC7');
  assert.equal(ids(standaloneMarket).has('market-rank-1'), true);
  assert.equal([...ids(standaloneMarket)].some((id) => id.startsWith('price-')), false);
  assert.equal(ids(loadCompetitorFacts('B08FTYHMC7', { rank_shift_pct: 60 })).has('market-rank-1'), false);

  const keywordLoose = loadCompetitorFacts('B0FNQYP7DW', { kw_rank_shift: 1, min_duration_days: 1 });
  const keywordStrict = loadCompetitorFacts('B0FNQYP7DW', { kw_rank_shift: 2, min_duration_days: 1 });
  assert.equal([...ids(keywordLoose)].some((id) => id.startsWith('keyword-')), true);
  assert.equal([...ids(keywordStrict)].some((id) => id.startsWith('keyword-')), false);

  assert.equal(ids(loadCompetitorFacts('B0D8V2L6JS')).has('price-promo-1'), true);
  assert.equal(ids(loadCompetitorFacts('B0D8V2L6JS', { min_duration_days: 60 })).has('price-promo-1'), false);

  const coverageDefault = loadCompetitorFacts('B0D8V2L6JS').change_candidates
    .find((item) => item.candidate_id === 'price-promo-1')!.coverage;
  const coverageLoose = loadCompetitorFacts('B0D8V2L6JS', { family_coverage_pct: 5 }).change_candidates
    .find((item) => item.candidate_id === 'price-promo-1')!.coverage;
  assert.equal(coverageDefault.coverage_threshold_met, false);
  assert.equal(coverageLoose.coverage_threshold_met, true);
  assert.equal(coverageLoose.family_eligible, false, '非主销子体仍不得上卷整族');

  const staleDefault = loadCompetitorFacts('B0D7D246LV').status_events;
  const staleRelaxed = loadCompetitorFacts('B0D7D246LV', { stale_days: 30 }).status_events;
  assert.equal(staleDefault.some((item) => item.status === 'stale'), true);
  assert.equal(staleRelaxed.some((item) => item.status === 'stale'), false);
});

test('sidecar 单事务写入、GET 只读 completed 且真实串联 prev_run_id', () => {
  const dir = mkdtempSync(join(tmpdir(), 'bamboo-competitor-agent-'));
  const dbPath = join(dir, 'competitor.sqlite');
  const jsonPath = join(dir, 'latest.json');
  const sourceBefore = statSync(SOURCE_DB).mtimeMs;
  try {
    const facts = { ...loadCompetitorFacts('B0CJ9QLVPP'), previous_run: null };
    const first = writeCompetitorAgentRun(
      facts, buildWorkflow(facts).snapshot(), 'test/model', dbPath, jsonPath,
      new Date('2026-08-31T01:00:00.000Z'),
    );
    assert.equal(workbenchState(dbPath, facts.family_asin).analysis_state, 'current');
    const secondFacts = { ...facts, previous_run: { run_id: first.run.run_id } };
    const second = writeCompetitorAgentRun(
      secondFacts, buildWorkflow(secondFacts).snapshot(), 'test/model', dbPath, jsonPath,
      new Date('2026-08-31T01:00:00.000Z'),
    );
    const db = new DatabaseSync(dbPath, { readOnly: true });
    const executions = db.prepare(`SELECT run_id, status, prev_run_id, created_at
      FROM fact_competitor_agent_execution ORDER BY julianday(created_at)`).all() as any[];
    const tables = db.prepare("SELECT name FROM sqlite_master WHERE type='table'").all() as Array<{ name: string }>;
    db.close();
    assert.equal(executions.length, 2);
    assert.equal(executions[1]!.prev_run_id, executions[0]!.run_id);
    assert.notEqual(executions[0]!.created_at, executions[1]!.created_at);
    assert.ok(executions.every((item) => item.status === 'completed'));
    assert.equal(tables.filter((item) => item.name.startsWith('fact_competitor_analysis_')).length, 9);
    assert.equal(JSON.parse(readFileSync(jsonPath, 'utf8')).run.run_id, second.run.run_id);
    assert.equal(workbenchState(dbPath, facts.family_asin).record.run_id, second.run.run_id);
    assert.equal(statSync(SOURCE_DB).mtimeMs, sourceBefore);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('GET 正确区分 not_run、stale 和 insufficient', () => {
  const dir = mkdtempSync(join(tmpdir(), 'bamboo-competitor-states-'));
  try {
    const missing = join(dir, 'missing.sqlite');
    assert.equal(workbenchState(missing, 'B0CJ9QLVPP').analysis_state, 'not_run');

    const staleDb = join(dir, 'stale.sqlite');
    const staleJson = join(dir, 'stale.json');
    const facts = { ...loadCompetitorFacts('B0CJ9QLVPP'), previous_run: null };
    writeCompetitorAgentRun(facts, buildWorkflow(facts).snapshot(), 'test/model', staleDb, staleJson);
    const writable = new DatabaseSync(staleDb);
    writable.prepare("UPDATE fact_competitor_agent_execution SET source_context_hash='outdated'").run();
    writable.close();
    assert.equal(workbenchState(staleDb, facts.family_asin).analysis_state, 'stale');

    const insufficientDb = join(dir, 'insufficient.sqlite');
    const insufficientJson = join(dir, 'insufficient.json');
    const weak = { ...loadCompetitorFacts('B0D7D246LV'), previous_run: null };
    writeCompetitorAgentRun(weak, buildWorkflow(weak).snapshot(), 'test/model', insufficientDb, insufficientJson);
    const payload = workbenchState(insufficientDb, weak.family_asin);
    assert.equal(payload.condition, '正常');
    assert.equal(payload.analysis_state, 'insufficient');
    assert.equal(payload.band.attention, '本次不给关注结论');
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
