import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { DatabaseSync } from 'node:sqlite';
import {
  COMPETITOR_V2_STAGES,
  COMPETITOR_V2_TABLES,
  CompetitorWorkflowV2,
  assertModelInputSafe,
  buildCompetitorTaskId,
  enqueueCompetitorExecution,
  getCompetitorTask,
  loadCompetitorFactsV2,
  markCompetitorExecutionRunning,
  skipCompetitorExecution,
  validateCompetitorRunRequest,
} from '../src/competitor-agent-v2.ts';
import { CompetitorTaskService } from '../src/competitor-task-service.ts';
import {
  CompetitorStageError,
  competitorStageContext,
  promptCompetitorStage,
} from '../src/competitor-pi-runner.ts';

const BUSINESS_TABLES = [
  'fact_competitor_analysis_run',
  'fact_competitor_analysis_change',
  'fact_competitor_analysis_timeline',
  'fact_competitor_analysis_concurrency',
  'fact_competitor_analysis_attention_reason',
  'fact_competitor_analysis_impact',
  'fact_competitor_analysis_open_item',
  'fact_competitor_analysis_diff',
  'fact_competitor_analysis_report',
  'fact_competitor_evidence_handoff',
] as const;

const EXPECTED_STAGES = [
  'judge_competitor_evidence',
  'judge_competitor_changes',
  'judge_family_representation',
  'judge_competitive_scope',
  'judge_change_concurrency',
  'judge_attention_and_impact',
  'judge_report_selection',
  'assemble_competitor_run',
] as const;

const DEFAULT_THRESHOLDS = {
  price_drop_pct: 5,
  gap_shift_pct: 10,
  rank_shift_pct: 15,
  kw_rank_shift: 3,
  min_duration_days: 7,
  family_coverage_pct: 30,
  stale_days: 14,
};

function request(requestKey: string, overrides: Record<string, unknown> = {}) {
  return {
    trigger: 'manual',
    family_asin: 'B0CJ9QLVPP',
    window_from: '2026-02-05',
    window_to: '2026-08-03',
    data_as_of: '2026-08-03',
    requested_by: 'contract-test',
    request_key: requestKey,
    thresholds: { ...DEFAULT_THRESHOLDS },
    ...overrides,
  };
}

function createDeferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((ok, fail) => {
    resolve = ok;
    reject = fail;
  });
  return { promise, resolve, reject };
}

async function waitForState(
  service: CompetitorTaskService,
  taskId: string,
  expected: string | string[],
  timeoutMs = 5_000,
) {
  const wanted = new Set(Array.isArray(expected) ? expected : [expected]);
  const deadline = Date.now() + timeoutMs;
  let latest: any = null;
  while (Date.now() < deadline) {
    latest = await service.get(taskId);
    if (latest && wanted.has(latest.state)) return latest;
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
  assert.fail(`task ${taskId} did not enter ${[...wanted].join('/')} (latest=${JSON.stringify(latest)})`);
}

function modelTextIsClean(value: unknown): void {
  const raw = JSON.stringify(value);
  assert.doesNotMatch(raw, /"scenario"\s*:/i);
  assert.doesNotMatch(raw, /"value_origin"\s*:/i);
  assert.doesNotMatch(raw, /dim_competitor_scenario/i);
  assert.doesNotMatch(raw, /fact_competitor_analysis_(?:run|change|timeline|concurrency|attention_reason|impact|open_item|diff|report)/i);
  assert.doesNotMatch(raw, /competitor_agent_state\.sqlite/i, 'V1 sidecar path/name must never enter model context');
}

/**
 * Build a complete model decision using only candidate identifiers. Numbers,
 * object ownership, IDs, timestamps and provenance remain writer-owned.
 */
function validSnapshot(facts: any, options: { forceRepresents?: boolean } = {}) {
  modelTextIsClean(facts);
  assertModelInputSafe(facts);
  const candidates = facts.change_candidates as any[];
  assert.ok(candidates.length > 0, 'the sanitized fact bridge must provide at least one candidate');
  const selected = candidates.slice(0, 2);
  const changes = selected.map((candidate) => ({
    candidate_id: candidate.candidate_id,
    domain: candidate.allowed_domains[0],
    direction: candidate.allowed_directions[0],
    current_state: candidate.allowed_current_states[0],
    label: '当前变化已进入持续观察区间',
    basis: '连续观察和对象引用支持该定性判断',
    confidence: 'high',
  }));
  const represents = options.forceRepresents ?? true;
  const representation = selected.map((candidate) => ({
    candidate_id: candidate.candidate_id,
    represents_family: represents,
    coverage_note: represents ? '结合主销对象与连续观察可以上卷整族' : '当前只能说明局部变体变化',
  }));
  const priceChange = changes.find((item) => item.domain === 'price_promo');
  const trafficChange = changes.find((item) => item.domain === 'traffic');
  const sharedKeyword = facts.shared_keyword_candidates[0]?.keyword ?? null;
  const eligibleRelations = (facts.relation_candidates as any[]).filter((item) =>
    item.confirm_status === 'confirmed' && item.gap_shift_applicable === true && item.gap_shift_eligible === true);
  const impacts = priceChange ? eligibleRelations.map((relation) => ({
    candidate_id: priceChange.candidate_id,
    relation_id: relation.rel_id,
    shared_keyword: sharedKeyword,
    pressure_dimension: 'price',
    statement: '竞品件单价变化可能影响该自有产品的价格竞争位置',
    confidence: 'high',
  })) : [];
  const handoffs: any[] = [];
  if (impacts.length && sharedKeyword) handoffs.push({
    target_page: 'keyword',
    candidate_id: impacts[0].candidate_id,
    relation_id: impacts[0].relation_id,
    shared_keyword: sharedKeyword,
    pressure_dimension: 'keyword',
    observable_fact: '共同词与已确认竞争关系同时存在，可供关键词页继续核对',
  });
  if (trafficChange) handoffs.push({
    target_page: 'advertising',
    candidate_id: trafficChange.candidate_id,
    relation_id: null,
    shared_keyword: null,
    pressure_dimension: 'traffic',
    observable_fact: '广告流量占比持续变化，可供广告页继续核对流量结构',
  });
  const previousRun = facts.previous_run?.run_id ?? null;
  return {
    evidence: {
      evidence_level: 'sufficient',
      evidence_reason: '当前观察连续，对象引用和窗口边界可核对',
      judgment_summary: '当前变化可以进入竞争判断',
    },
    changes,
    representation,
    impacts,
    concurrency: selected.length > 1 ? [{
      change_a_id: selected[0].candidate_id,
      change_b_id: selected[1].candidate_id,
      relation: 'concurrent',
      statement: '两类变化在观察窗内同期变化，目前只判为可能相关',
      missing_evidence: '仍需后续窗口和转化表现进一步核对',
    }] : [],
    attention: {
      attention_level: 'high',
      attention_summary: '当前变化已影响竞争位置，需要持续跟踪',
      reasons: [
        { candidate_id: selected[0].candidate_id, label: '变化具有持续性', weight_note: '持续性是主要依据' },
        { candidate_id: selected[0].candidate_id, label: '变化进入竞争范围', weight_note: '竞争关系可以核对' },
      ],
    },
    outputs: {
      open_items: [{
        item_kind: 'watch',
        statement: '当前变化是否会在下一观察窗延续',
        needed_data: '下一周期的同口径连续观察',
      }],
      diff: {
        transition: previousRun ? 'sustained' : 'new',
        statement: previousRun ? '关注方向与上一版保持一致' : '本次为首次形成可追溯判断',
        changed_domains: [...new Set(changes.map((item) => item.domain))],
      },
      report: represents ? {
        headline: '当前竞争位置变化值得持续关注',
        body: '连续观察表明该变化已进入整族判断范围',
        impact_note: '后续需结合自有产品表现继续核对',
        unconfirmed_note: '变化是否会延续仍待下一观察窗确认',
      } : null,
      handoffs,
    },
  };
}

function withTempState(prefix: string) {
  const dir = mkdtempSync(join(tmpdir(), prefix));
  const oldDb = process.env.BAMBOO_COMPETITOR_V2_DB;
  const oldJson = process.env.BAMBOO_COMPETITOR_V2_JSON;
  process.env.BAMBOO_COMPETITOR_V2_DB = join(dir, 'competitor_agent_state_v2.sqlite');
  process.env.BAMBOO_COMPETITOR_V2_JSON = join(dir, 'competitor_agent_latest_v2.json');
  return {
    dir,
    dbPath: process.env.BAMBOO_COMPETITOR_V2_DB,
    restore() {
      if (oldDb === undefined) delete process.env.BAMBOO_COMPETITOR_V2_DB;
      else process.env.BAMBOO_COMPETITOR_V2_DB = oldDb;
      if (oldJson === undefined) delete process.env.BAMBOO_COMPETITOR_V2_JSON;
      else process.env.BAMBOO_COMPETITOR_V2_JSON = oldJson;
      rmSync(dir, { recursive: true, force: true });
    },
  };
}

test('V2 冻结为八个业务步骤、十张业务表和一张执行台账', () => {
  assert.deepEqual(COMPETITOR_V2_STAGES, EXPECTED_STAGES);
  assert.deepEqual(new Set(COMPETITOR_V2_TABLES), new Set([
    'fact_competitor_agent_execution',
    ...BUSINESS_TABLES,
  ]));
  assert.equal(COMPETITOR_V2_TABLES.length, 11);
});

test('请求严格验证七个阈值，手动触发必须有 requested_by', () => {
  const normalized = validateCompetitorRunRequest(request('request-normalize', {
    thresholds: {
      price_drop_pct: -1,
      gap_shift_pct: 999,
      rank_shift_pct: 1,
      kw_rank_shift: 99,
      min_duration_days: 0,
      family_coverage_pct: 999,
      stale_days: 1,
    },
  }));
  assert.deepEqual(normalized.thresholds, {
    price_drop_pct: 1,
    gap_shift_pct: 50,
    rank_shift_pct: 5,
    kw_rank_shift: 20,
    min_duration_days: 1,
    family_coverage_pct: 100,
    stale_days: 3,
  });
  assert.throws(
    () => validateCompetitorRunRequest(request('missing-operator', { requested_by: null })),
    /requested_by/i,
  );
  assert.throws(
    () => validateCompetitorRunRequest({ ...request('page-only-field'), sort_by: 'attention' }),
    /sort_by|unknown|不允许/i,
  );
  const incomplete = request('missing-threshold') as any;
  delete incomplete.thresholds.stale_days;
  assert.throws(() => validateCompetitorRunRequest(incomplete), /stale_days/i);
});

test('task_id 由家族和 request_key 确定生成，不泄漏原始键', () => {
  const first = buildCompetitorTaskId('B0CJ9QLVPP', 'ops-secret-request-key');
  const repeated = buildCompetitorTaskId('b0cj9qlvpp', 'ops-secret-request-key');
  assert.equal(first, repeated);
  assert.notEqual(first, buildCompetitorTaskId('B0CJ9QLVPP', 'another-request-key'));
  assert.notEqual(first, buildCompetitorTaskId('B0D8V2L6JS', 'ops-secret-request-key'));
  assert.match(first, /^T-B0CJ9QLVPP-[a-f0-9]+$/i);
  assert.doesNotMatch(first, /ops-secret-request-key/);
});

test('模型输入扫描禁止 scenario、value_origin、legacy 判断表和 V1 sidecar', () => {
  assert.doesNotThrow(() => assertModelInputSafe({
    family_asin: 'B0CJ9QLVPP',
    coverage: { observed: 3, selling: 71, threshold_reference_pct: 30, main_seller_observed: true },
    previous_run: { run_id: 'B0CJ9QLVPP-2026-08-03-1', transition: 'sustained' },
  }));
  for (const forbidden of [
    { nested: { scenario: 'price-pressure' } },
    { candidate: { value_origin: 'constructed' } },
    { source: 'dim_competitor_scenario' },
    { source: 'fact_competitor_analysis_change' },
    { path: '/tmp/competitor_agent_state.sqlite' },
  ]) {
    assert.throws(() => assertModelInputSafe(forbidden), /scenario|value_origin|legacy|V1|禁止|禁读/i);
  }
});

test('完整事实不再一次性发给模型，八步只披露当前阶段最小事实', () => {
  const state = withTempState('bamboo-competitor-v2-stage-context-');
  try {
    const facts = loadCompetitorFactsV2(request('stage-context') as any, state.dbPath).model;
    const contexts = Object.fromEntries(COMPETITOR_V2_STAGES.map((stage) => [stage, competitorStageContext(facts, stage)]));
    for (const context of Object.values(contexts)) {
      assertModelInputSafe(context);
      modelTextIsClean(context);
    }

    const evidence = JSON.stringify(contexts.judge_competitor_evidence);
    assert.match(evidence, /evidence_health|domain_health/);
    assert.doesNotMatch(evidence, /change_candidates|locked_fact|relation_candidates|previous_run/);

    const changes = JSON.stringify(contexts.judge_competitor_changes);
    assert.match(changes, /change_candidates|locked_fact/);
    assert.doesNotMatch(changes, /relation_candidates|shared_keyword_candidates|previous_run/);

    const representation = JSON.stringify(contexts.judge_family_representation);
    assert.match(representation, /candidate_coverage|family_coverage_reference_pct/);
    assert.doesNotMatch(representation, /relation_candidates|previous_run/);

    const scope = JSON.stringify(contexts.judge_competitive_scope);
    assert.match(scope, /relation_candidates|shared_keyword_candidates/);
    assert.doesNotMatch(scope, /previous_run|locked_fact/);

    const concurrency = JSON.stringify(contexts.judge_change_concurrency);
    assert.match(concurrency, /change_timing|causal_ready/);
    assert.doesNotMatch(concurrency, /relation_candidates|previous_run|locked_fact/);

    assert.doesNotMatch(JSON.stringify(contexts.judge_attention_and_impact), /change_candidates|relation_candidates|previous_run/);
    assert.doesNotMatch(JSON.stringify(contexts.judge_report_selection), /change_candidates|relation_candidates|previous_run/);

    const assemble = JSON.stringify(contexts.assemble_competitor_run);
    assert.match(assemble, /previous_run|handoff_candidates/);
  } finally {
    state.restore();
  }
});

test('证据阶段把可选通道缺行与现有可分析通道分开，不提前披露变化明细', () => {
  const state = withTempState('bamboo-competitor-v2-channel-health-');
  try {
    const facts = loadCompetitorFactsV2(request('channel-health', { family_asin: 'B08FTYHMC7' }) as any, state.dbPath).model;
    const context: any = competitorStageContext(facts, 'judge_competitor_evidence');
    assert.deepEqual(context.evidence_health.status_events, []);
    assert.equal(context.evidence_health.evidence_gap_count, 0);
    assert.ok(context.evidence_health.domain_health.some((item: any) => item.domain === 'market' && item.candidate_count > 0));
    assert.ok(context.evidence_health.domain_health.some((item: any) => item.domain === 'traffic' && item.candidate_count > 0));
    assert.equal(context.evidence_health.optional_channel_coverage.keyword_rank_rows, 0);
    assert.doesNotMatch(JSON.stringify(context), /locked_fact|change_candidates|relation_candidates/);
  } finally {
    state.restore();
  }
});

test('Agent 阶段失败会在台账保留安全步骤，不泄漏底层异常', async () => {
  const state = withTempState('bamboo-competitor-v2-stage-failure-');
  const service = new CompetitorTaskService({
    modelVersion: 'test/model',
    runner: async () => { throw new CompetitorStageError('judge_competitive_scope', 'contract'); },
  });
  try {
    const task = await service.enqueue(request('stage-failure'));
    const failed = await waitForState(service, task.task_id, 'failed');
    assert.match(failed.reason, /失败步骤：判断竞争范围/);
    assert.match(failed.reason, /未提交通过门禁的工具结果/);
    assert.doesNotMatch(failed.reason, /stack|prompt|token|secret/i);
  } finally {
    await service.dispose();
    state.restore();
  }
});

test('当前步骤门禁拒绝后会携带安全错误原地重试，不会跳到下一步', async () => {
  const stage = 'assemble_competitor_run';
  const workflow: any = { expectedStage: stage };
  const gateErrors = new Map<string, string>();
  const prompts: string[] = [];
  const session = {
    async prompt(value: string) {
      prompts.push(value);
      if (prompts.length === 1) gateErrors.set(stage, '存在流量结构变化时必须产出广告证据交接');
      else workflow.expectedStage = 'completed';
    },
  };
  await promptCompetitorStage(session, workflow, stage, '首次装配', gateErrors);
  assert.equal(prompts.length, 2);
  assert.equal(prompts[0], '首次装配');
  assert.match(prompts[1], /存在流量结构变化时必须产出广告证据交接/);
  assert.match(prompts[1], /只调用 assemble_competitor_run/);
});

test('执行台账只允许法定状态转换，终态不得复活', () => {
  const state = withTempState('bamboo-competitor-v2-transitions-');
  try {
    const rawRequest = request('legal-state-transition');
    const facts = loadCompetitorFactsV2(rawRequest as any, state.dbPath).model;
    const execution = enqueueCompetitorExecution(rawRequest as any, facts, 'test/model', state.dbPath);
    assert.equal(getCompetitorTask(execution.task_id, state.dbPath)?.state, 'queued');
    markCompetitorExecutionRunning(execution.task_id, state.dbPath);
    assert.equal(getCompetitorTask(execution.task_id, state.dbPath)?.state, 'running');
    assert.throws(
      () => skipCompetitorExecution(execution.task_id, '运行中不得跳转跳过', state.dbPath),
      /非法状态转换|running.*skipped/i,
    );
  } finally {
    state.restore();
  }
});

test('request_key 并发幂等，且 queued 与 running 对轮询可观察', async () => {
  const state = withTempState('bamboo-competitor-v2-idempotent-');
  const release = createDeferred<void>();
  let calls = 0;
  const service = new CompetitorTaskService({
    modelVersion: 'test/model',
    runner: async (facts: any) => {
      calls += 1;
      await release.promise;
      return validSnapshot(facts);
    },
  });
  try {
    const submissions = await Promise.all(Array.from({ length: 8 }, () => service.enqueue(request('same-request-key'))));
    assert.equal(new Set(submissions.map((item: any) => item.task_id)).size, 1);
    const taskId = submissions[0]!.task_id;
    assert.ok(submissions.every((item: any) => ['queued', 'running'].includes(item.state)));
    await waitForState(service, taskId, 'running');
    assert.equal(calls, 1);
    release.resolve();
    const done = await waitForState(service, taskId, 'done');
    assert.ok(done.run_id);
    assert.equal(calls, 1);

    const db = new DatabaseSync(state.dbPath, { readOnly: true });
    try {
      const count = db.prepare('SELECT COUNT(*) n FROM fact_competitor_agent_execution').get() as { n: number };
      assert.equal(Number(count.n), 1);
      const tables = new Set((db.prepare("SELECT name FROM sqlite_master WHERE type='table'").all() as Array<{ name: string }>)
        .map((item) => item.name));
      for (const table of COMPETITOR_V2_TABLES) assert.equal(tables.has(table), true, `${table} was not published`);
      for (const table of BUSINESS_TABLES) {
        const key = table === 'fact_competitor_analysis_report' ? 'ref_run_id'
          : table === 'fact_competitor_evidence_handoff' ? 'frozen_run_id' : 'run_id';
        const foreign = db.prepare(`SELECT COUNT(*) n FROM ${table} WHERE ${key}<>?`).get(done.run_id) as { n: number };
        assert.equal(Number(foreign.n), 0, `${table} contains a row owned by another run`);
      }
      assert.equal(Number((db.prepare('SELECT COUNT(*) n FROM fact_competitor_analysis_run WHERE run_id=?')
        .get(done.run_id) as { n: number }).n), 1);
      assert.ok(Number((db.prepare('SELECT COUNT(*) n FROM fact_competitor_analysis_change WHERE run_id=?')
        .get(done.run_id) as { n: number }).n) > 0);
      assert.equal(Number((db.prepare('SELECT COUNT(*) n FROM fact_competitor_analysis_diff WHERE run_id=?')
        .get(done.run_id) as { n: number }).n), 1);
    } finally {
      db.close();
    }
  } finally {
    await service.dispose();
    state.restore();
  }
});

test('同家族不同任务严格串行', async () => {
  const state = withTempState('bamboo-competitor-v2-serial-');
  let familyActive = 0;
  let maxFamilyActive = 0;
  const releases = [createDeferred<void>(), createDeferred<void>()];
  let call = 0;
  const service = new CompetitorTaskService({
    modelVersion: 'test/model',
    runner: async (facts: any) => {
      const current = call++;
      familyActive += 1;
      maxFamilyActive = Math.max(maxFamilyActive, familyActive);
      await releases[current]!.promise;
      familyActive -= 1;
      return validSnapshot(facts);
    },
  });
  try {
    const first = await service.enqueue(request('serial-one'));
    const second = await service.enqueue(request('serial-two', {
      thresholds: { ...DEFAULT_THRESHOLDS, price_drop_pct: 6 },
    }));
    await waitForState(service, first.task_id, 'running');
    assert.equal((await service.get(second.task_id)).state, 'queued');
    assert.equal(call, 1);
    releases[0].resolve();
    await waitForState(service, first.task_id, 'done');
    await waitForState(service, second.task_id, 'running');
    assert.equal(call, 2);
    releases[1].resolve();
    await waitForState(service, second.task_id, 'done');
    assert.equal(maxFamilyActive, 1);
  } finally {
    await service.dispose();
    state.restore();
  }
});

test('首轮只读 V2 completed 前序且 diff=new；同上下文新请求 skipped，阈值变化必须重跑', async () => {
  const state = withTempState('bamboo-competitor-v2-prev-skip-');
  const observedPrevious: Array<string | null> = [];
  const service = new CompetitorTaskService({
    modelVersion: 'test/model',
    runner: async (facts: any) => {
      observedPrevious.push(facts.previous_run?.run_id ?? null);
      return validSnapshot(facts);
    },
  });
  try {
    const first = await service.enqueue(request('first-v2-run'));
    const firstDone = await waitForState(service, first.task_id, 'done');
    assert.deepEqual(observedPrevious, [null], 'V1 and observation-layer legacy runs must not become previous_run');

    const skipped = await service.enqueue(request('same-context-new-request'));
    const skippedDone = await waitForState(service, skipped.task_id, 'skipped');
    assert.match(skippedDone.reason, /没有新|相同|沿用|未变/);
    assert.equal(observedPrevious.length, 1, 'skip must happen before opening the model runner');

    const rerun = await service.enqueue(request('changed-threshold', {
      thresholds: { ...DEFAULT_THRESHOLDS, family_coverage_pct: 100 },
    }));
    const rerunDone = await waitForState(service, rerun.task_id, 'done');
    assert.equal(observedPrevious[1], firstDone.run_id);

    const db = new DatabaseSync(state.dbPath, { readOnly: true });
    try {
      const firstDiff = db.prepare('SELECT transition, prev_run_id FROM fact_competitor_analysis_diff WHERE run_id=?')
        .get(firstDone.run_id) as any;
      const secondDiff = db.prepare('SELECT transition, prev_run_id FROM fact_competitor_analysis_diff WHERE run_id=?')
        .get(rerunDone.run_id) as any;
      assert.equal(firstDiff.transition, 'new');
      assert.equal(firstDiff.prev_run_id, null);
      assert.equal(secondDiff.prev_run_id, firstDone.run_id);
      assert.notEqual(secondDiff.transition, 'new');
      const skippedExecution = db.prepare('SELECT run_id FROM fact_competitor_agent_execution WHERE task_id=?')
        .get(skipped.task_id) as { run_id: string };
      const skippedRows = BUSINESS_TABLES.reduce((sum, table) => {
        const key = table === 'fact_competitor_analysis_report' ? 'ref_run_id'
          : table === 'fact_competitor_evidence_handoff' ? 'frozen_run_id' : 'run_id';
        const row = db.prepare(`SELECT COUNT(*) n FROM ${table} WHERE ${key}=?`).get(skippedExecution.run_id) as { n: number };
        return sum + Number(row.n);
      }, 0);
      assert.equal(skippedRows, 0, 'skipped task must publish zero judgment rows');
    } finally {
      db.close();
    }
  } finally {
    await service.dispose();
    state.restore();
  }
});

test('重跑上下文包含上一版影响与交接，持续结论不得静默清空', async () => {
  const state = withTempState('bamboo-competitor-v2-continuity-');
  let call = 0;
  let previousSeen: any = null;
  const service = new CompetitorTaskService({
    modelVersion: 'test/model',
    runner: async (facts: any) => {
      call += 1;
      const snapshot = validSnapshot(facts);
      if (call === 1) return snapshot;
      previousSeen = facts.previous_run;
      snapshot.impacts = [];
      snapshot.outputs.handoffs = [];
      snapshot.outputs.diff.transition = 'sustained';
      return snapshot;
    },
  });
  try {
    const first = await service.enqueue(request('continuity-first'));
    const firstDone = await waitForState(service, first.task_id, 'done');
    const rerun = await service.enqueue(request('continuity-cleared', {
      thresholds: { ...DEFAULT_THRESHOLDS, price_drop_pct: 6 },
    }));
    await waitForState(service, rerun.task_id, 'failed');
    assert.ok(previousSeen);
    assert.ok(previousSeen.impacts.length > 0, 'previous impacts must be visible to the model');
    assert.ok(previousSeen.handoffs.length > 0, 'previous handoffs must be visible to the model');

    const db = new DatabaseSync(state.dbPath, { readOnly: true });
    try {
      const completed = db.prepare(`SELECT run_id FROM fact_competitor_agent_execution
        WHERE family_asin=? AND status='completed' ORDER BY created_at DESC`).all('B0CJ9QLVPP') as Array<{ run_id: string }>;
      assert.deepEqual(completed.map((item) => item.run_id), [firstDone.run_id]);
    } finally {
      db.close();
    }
  } finally {
    await service.dispose();
    state.restore();
  }
});

test('当前事实有已确认价差关系和流量变化时，工作流拒绝空影响与空交接', () => {
  const state = withTempState('bamboo-competitor-v2-required-outputs-');
  try {
    const facts = loadCompetitorFactsV2(request('required-output-gate') as any, state.dbPath).model;
    const snapshot = validSnapshot(facts);
    const scope = new CompetitorWorkflowV2(facts);
    scope.submitEvidence(snapshot.evidence);
    scope.submitChanges(snapshot.changes);
    scope.submitRepresentation(snapshot.representation);
    assert.throws(() => scope.submitScope([]), /必须产出影响范围/);

    const assemble = new CompetitorWorkflowV2(facts);
    assemble.submitEvidence(snapshot.evidence);
    assemble.submitChanges(snapshot.changes);
    assemble.submitRepresentation(snapshot.representation);
    assemble.submitScope(snapshot.impacts);
    assemble.submitConcurrency(snapshot.concurrency);
    assemble.submitAttention(snapshot.attention);
    assemble.submitReport({ report: snapshot.outputs.report });
    assert.throws(() => assemble.submitAssemble({
      open_items: snapshot.outputs.open_items,
      diff: snapshot.outputs.diff,
      handoffs: [],
    }), /关键词证据交接|广告证据交接/);
  } finally {
    state.restore();
  }
});

test('family_coverage_pct 只是模型参考，写入端不能依阈值硬锁整族代表性', async () => {
  const state = withTempState('bamboo-competitor-v2-coverage-');
  let sawBelowThreshold = false;
  const service = new CompetitorTaskService({
    modelVersion: 'test/model',
    runner: async (facts: any) => {
      const candidate = facts.change_candidates[0];
      const coverage = candidate.coverage ?? {};
      const observedPct = Number(coverage.observed_pct ?? coverage.coverage_pct ?? 0);
      sawBelowThreshold = observedPct < 100;
      return validSnapshot(facts, { forceRepresents: true });
    },
  });
  try {
    const task = await service.enqueue(request('coverage-is-reference', {
      family_asin: 'B0D8V2L6JS',
      thresholds: { ...DEFAULT_THRESHOLDS, family_coverage_pct: 100 },
    }));
    const done = await waitForState(service, task.task_id, 'done');
    assert.equal(sawBelowThreshold, true, 'fixture must exercise coverage below the requested reference threshold');
    const db = new DatabaseSync(state.dbPath, { readOnly: true });
    try {
      const represented = db.prepare(`SELECT COUNT(*) n FROM fact_competitor_analysis_change
        WHERE run_id=? AND represents_family=1`).get(done.run_id) as { n: number };
      assert.ok(Number(represented.n) > 0);
    } finally {
      db.close();
    }
  } finally {
    await service.dispose();
    state.restore();
  }
});

test('完成任务原子发布十张业务表，提交中途失败则全部回滚并转 failed', async () => {
  const state = withTempState('bamboo-competitor-v2-atomic-');
  const release = createDeferred<void>();
  const service = new CompetitorTaskService({
    modelVersion: 'test/model',
    runner: async (facts: any) => {
      await release.promise;
      return validSnapshot(facts);
    },
  });
  try {
    const task = await service.enqueue(request('forced-mid-commit-failure'));
    await waitForState(service, task.task_id, 'running');
    const db = new DatabaseSync(state.dbPath);
    try {
      db.exec(`CREATE TRIGGER force_diff_failure
        BEFORE INSERT ON fact_competitor_analysis_diff
        BEGIN SELECT RAISE(FAIL, 'forced contract failure'); END`);
    } finally {
      db.close();
    }
    release.resolve();
    const failed = await waitForState(service, task.task_id, 'failed');
    assert.match(failed.reason, /失败步骤：写入前契约校验/);

    const read = new DatabaseSync(state.dbPath, { readOnly: true });
    try {
      const executionRow = read.prepare(`SELECT run_id, status, completed_at
        FROM fact_competitor_agent_execution WHERE task_id=?`).get(task.task_id) as any;
      for (const table of BUSINESS_TABLES) {
        const key = table === 'fact_competitor_analysis_report' ? 'ref_run_id'
          : table === 'fact_competitor_evidence_handoff' ? 'frozen_run_id' : 'run_id';
        const count = read.prepare(`SELECT COUNT(*) n FROM ${table} WHERE ${key}=?`).get(executionRow.run_id) as { n: number };
        assert.equal(Number(count.n), 0, `${table} left a partial row after rollback`);
      }
      assert.equal(executionRow.status, 'failed');
    } finally {
      read.close();
    }
  } finally {
    await service.dispose();
    state.restore();
  }
});

test('模型异常得到 failed 且零判断行，新 request_key 可恢复成功', async () => {
  const state = withTempState('bamboo-competitor-v2-recovery-');
  let shouldFail = true;
  const service = new CompetitorTaskService({
    modelVersion: 'test/model',
    runner: async (facts: any) => {
      if (shouldFail) throw new Error('provider unavailable with secret-token-redacted');
      return validSnapshot(facts);
    },
  });
  try {
    const first = await service.enqueue(request('provider-fails'));
    const failed = await waitForState(service, first.task_id, 'failed');
    assert.doesNotMatch(failed.reason, /secret-token-redacted/, 'status API must expose a safe reason');
    shouldFail = false;
    const retry = await service.enqueue(request('new-key-recovers'));
    const done = await waitForState(service, retry.task_id, 'done');
    assert.ok(done.run_id);
  } finally {
    await service.dispose();
    state.restore();
  }
});

test('HTTP POST 立即返回任务，GET 轮询五态契约，相同 request_key 复用 task_id', async () => {
  const state = withTempState('bamboo-competitor-v2-api-');
  const oldFake = process.env.BAMBOO_AGENT_FAKE;
  process.env.BAMBOO_AGENT_FAKE = '1';
  const { createDemoServer } = await import('../src/server.ts');
  const server = createDemoServer();
  try {
    await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
    const address = server.address();
    assert.ok(address && typeof address === 'object');
    const base = `http://127.0.0.1:${address.port}`;
    const body = request('api-idempotent');
    const [first, second] = await Promise.all([1, 2].map(async () => {
      const response = await fetch(`${base}/api/agent/competitor/runs`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body),
      });
      assert.equal(response.status, 202);
      return response.json() as Promise<any>;
    }));
    assert.equal(first.task_id, second.task_id);
    assert.ok(['queued', 'running', 'done'].includes(first.state));

    let terminal: any = null;
    const deadline = Date.now() + 5_000;
    while (Date.now() < deadline) {
      const response = await fetch(`${base}/api/agent/competitor/tasks/${first.task_id}`);
      assert.equal(response.status, 200);
      terminal = await response.json();
      if (['done', 'skipped', 'failed'].includes(terminal.state)) break;
      await new Promise((resolve) => setTimeout(resolve, 10));
    }
    assert.equal(terminal.state, 'done');
    assert.ok(terminal.run_id);

    const unknown = await fetch(`${base}/api/agent/competitor/tasks/T-UNKNOWN-deadbeef`);
    assert.equal(unknown.status, 404);
    const invalid = await fetch(`${base}/api/agent/competitor/runs`, {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: '{}',
    });
    assert.equal(invalid.status, 400);
  } finally {
    await new Promise<void>((resolve) => server.close(() => resolve()));
    if (oldFake === undefined) delete process.env.BAMBOO_AGENT_FAKE;
    else process.env.BAMBOO_AGENT_FAKE = oldFake;
    state.restore();
  }
});
