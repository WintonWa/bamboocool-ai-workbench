import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { existsSync, mkdtempSync, readFileSync, rmSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import test from "node:test";
import { DatabaseSync } from "node:sqlite";
import {
  DEFAULT_KEYWORD_BASE_DB, KEYWORD_PROJECT_ROOT, KeywordRunController,
  loadKeywordAgentFacts, resolveKeywordSource, validateCoverageBatch,
  validateKeywordFacts, validateMarketBatch,
  type CoverageDecision, type DailyDecision, type EvidenceDecision,
  type MarketDecision,
} from "../src/keyword-agent.ts";
import { installKeywordSignalHandlers } from "../scripts/run_keyword_agent_demo.ts";

const facts = loadKeywordAgentFacts("all", DEFAULT_KEYWORD_BASE_DB);

function marketDecision(item: Record<string, any>): MarketDecision {
  if (item.from_comparable === 0 || item.to_comparable === 0) return {
    candidate_id: item.candidate_id, event_type: "not_comparable",
    continuity: "single_period", label: `${item.keyword}当前两期市场口径不可直接比较`,
  };
  if (item.from_value == null || item.to_value == null
    || item.from_data_state === "no_data" || item.to_data_state === "no_data") return {
    candidate_id: item.candidate_id, event_type: "insufficient_history",
    continuity: "insufficient", label: `${item.keyword}当前同频率历史样本不足`,
  };
  if (item.to_value === item.from_value) return {
    candidate_id: item.candidate_id, event_type: null, continuity: null, label: null,
  };
  return {
    candidate_id: item.candidate_id,
    event_type: item.to_value > item.from_value ? "demand_up" : "demand_down",
    continuity: "single_period", label: `${item.keyword}当前同频率搜索需求出现单期变化`,
  };
}

function coverageDecision(item: Record<string, any>): CoverageDecision {
  const none: CoverageDecision = {
    candidate_id: item.candidate_id, event_type: null, continuity: null, label: null,
  };
  if (item.channel === "organic" && (item.from_state === "beyond_depth" || item.to_state === "beyond_depth")) return {
    candidate_id: item.candidate_id, event_type: "beyond_depth", continuity: "single_period",
    label: `${item.child_asin}在${item.keyword}的自然位超出当前采集深度`,
  };
  if (item.from_rank == null && item.to_rank != null) return {
    candidate_id: item.candidate_id,
    event_type: item.channel === "organic" ? "organic_gained" : "ad_gained",
    continuity: "single_period", label: `${item.child_asin}在${item.keyword}新增当前通道覆盖`,
  };
  if (item.from_rank != null && item.to_rank == null) return {
    candidate_id: item.candidate_id,
    event_type: item.channel === "organic" ? "organic_lost" : "ad_lost",
    continuity: "single_period", label: `${item.child_asin}在${item.keyword}丢失当前通道覆盖`,
  };
  if (item.from_rank == null || item.to_rank == null || Math.abs(item.to_rank - item.from_rank) < 3) return none;
  return {
    candidate_id: item.candidate_id,
    event_type: item.channel === "organic"
      ? (item.to_rank < item.from_rank ? "organic_up" : "organic_down")
      : null,
    continuity: item.channel === "organic" ? "single_period" : null,
    label: item.channel === "organic" ? `${item.child_asin}在${item.keyword}的自然位出现有效变化` : null,
  };
}

function conclusion(item: Record<string, any>): string {
  let value = `${item.child_asin}在“${item.keyword}”的当前覆盖和市场证据尚不足以形成扩量判断，建议结合既定产品目标保持观察`;
  while ([...value].length < 40) value += "并跟踪后续变化";
  return `${value.slice(0, 69)}。`;
}

function evidenceDecision(item: Record<string, any>): EvidenceDecision {
  return {
    candidate_id: item.candidate_id, evidence_type: "insufficient_data", priority: 6,
    conclusion: conclusion(item), main_basis: "当前位置、市场快照与既定产品目标尚未形成相互印证的完整信号",
    evidence_completeness: "insufficient", next_verification: "observe",
    competitor_verification_state: "na", ref_market_event_ids: [], ref_coverage_event_ids: [],
  };
}

function dailyDecision(item: Record<string, any>): DailyDecision {
  return {
    candidate_id: item.candidate_id,
    q1_traffic_result: "当日流量代理指标已按相同比较口径完成核对，结果已进入本次日报",
    q2_main_movers: "当日市场变化已按周线与月线分别核对，没有跨频率合并判断",
    q3_core_coverage_change: "核心词覆盖变化已按自然位和广告位分别核对，未混用两类通道",
    q4_new_signals: "当日新增覆盖与位置变化已完成筛选，仅保留达到参数门槛的信号",
    q5_priority_next: "当前优先事项按本次证据原始意见记录，最终顺序交由页面权重重排",
    priority_evidence_ids: item.priority_evidence_ids,
  };
}

function advanceToCommit(run: KeywordRunController): void {
  run.acceptContext(facts.context_hash);
  while (run.stage === "market") run.submitMarket(run.nextMarketBatch().map(marketDecision));
  while (run.stage === "coverage") run.submitCoverage(run.nextCoverageBatch().map(coverageDecision));
  while (run.stage === "evidence") run.submitEvidence(run.nextEvidenceBatch().map(evidenceDecision));
  run.submitDaily(run.dailyContexts().map(dailyDecision));
  run.buildAuditRecords();
}

test("V2 事实桥从允许输入生成对象，完全不查询五张旧判断表", () => {
  assert.deepEqual(validateKeywordFacts(facts), []);
  assert.equal(facts.counts.terms, 1991);
  assert.equal(facts.counts.pairs, 901);
  assert.equal(facts.counts.evidence_candidates, 901);
  assert.equal(facts.counts.coverage_candidates, 1802);
  assert.equal(facts.golden.second_source_observation.sources.kw3.ad_competitor_count, 548);
  assert.equal(facts.golden.second_source_observation.sources.kw2.ad_competitor_count, 495);
  const bridge = readFileSync(resolve(KEYWORD_PROJECT_ROOT, "scripts/keyword_agent_facts.py"), "utf8");
  for (const table of ["fact_keyword_evidence", "fact_keyword_daily_report", "fact_keyword_market_change_event", "fact_keyword_coverage_event", "fact_keyword_audit_record"]) {
    assert.equal(bridge.includes(table), false, `事实桥不得出现旧判断表 ${table}`);
  }
});

test("null 是事件契约的正式结果，方向与通道仍受门禁约束", () => {
  const market = facts.market_candidates[0]!;
  assert.deepEqual(validateMarketBatch([market], [{ candidate_id: market.candidate_id,
    event_type: null, continuity: null, label: null }]), []);
  const badMarket = marketDecision(market);
  if (badMarket.event_type === "demand_down") {
    assert.match(validateMarketBatch([market], [{ ...badMarket, event_type: "demand_up" }]).join("；"), /方向相反/);
  }
  const organic = facts.coverage_candidates.find((x) => x.channel === "organic"
    && x.from_rank != null && x.to_rank != null && x.to_rank - x.from_rank >= 3)!;
  const bad: CoverageDecision = { candidate_id: organic.candidate_id, event_type: "organic_up",
    continuity: "single_period", label: `${organic.child_asin}在${organic.keyword}的自然位上涨` };
  assert.match(validateCoverageBatch([organic], [bad], 3).join("；"), /方向或阈值/);
});

test("A–E 完成后才发布；运营角色原样保留，时间戳与 run 头符合规范", { timeout: 180_000 }, () => {
  const dir = mkdtempSync(join(tmpdir(), "bamboo-keyword-v2-"));
  const currentPath = join(dir, "current.sqlite");
  const statePath = join(dir, "state.sqlite");
  const run = new KeywordRunController(facts, { modelVersion: "test/v2",
    sourcePath: DEFAULT_KEYWORD_BASE_DB, currentPath, statePath, batchSize: 100 });
  try {
    advanceToCommit(run);
    assert.deepEqual(run.validateForCommit(), []);
    const output = run.commit();
    assert.equal(resolveKeywordSource(currentPath, statePath, DEFAULT_KEYWORD_BASE_DB), currentPath);
    const base = new DatabaseSync(DEFAULT_KEYWORD_BASE_DB, { readOnly: true });
    const current = new DatabaseSync(currentPath, { readOnly: true });
    const roleSql = "SELECT keyword_id,library_status,operator_role,operator_role_label,operator_role_confirmed,operator_role_seed_word FROM dim_keyword_term ORDER BY keyword_id";
    assert.deepEqual(current.prepare(roleSql).all(), base.prepare(roleSql).all());
    assert.equal((current.prepare("SELECT COUNT(*) n FROM fact_keyword_daily_report").get() as any).n, 14);
    assert.equal((current.prepare("SELECT COUNT(*) n FROM fact_keyword_audit_record").get() as any).n, 30);
    base.close(); current.close();
    const state = new DatabaseSync(statePath, { readOnly: true });
    const row = state.prepare("SELECT run_id,run_date,data_as_of,prev_run_id,status,created_at,completed_at FROM fact_keyword_agent_run WHERE run_id=?").get(output.run_id) as any;
    state.close();
    assert.equal(row.status, "completed"); assert.equal(row.run_date, facts.as_of_date);
    assert.equal(row.data_as_of, facts.as_of_date); assert.equal(row.prev_run_id, null);
    assert.match(row.created_at, /\+08:00$/); assert.match(row.completed_at, /\+08:00$/);
  } catch (error) {
    if (run.stage !== "completed" && run.stage !== "failed") run.fail(error);
    throw error;
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

test("原子发布最后一步失败时旧 current 保持可见", { timeout: 240_000 }, () => {
  const dir = mkdtempSync(join(tmpdir(), "bamboo-keyword-v2-rollback-"));
  const currentPath = join(dir, "current.sqlite"), statePath = join(dir, "state.sqlite");
  const first = new KeywordRunController(facts, { modelVersion: "test/first",
    sourcePath: DEFAULT_KEYWORD_BASE_DB, currentPath, statePath, batchSize: 100 });
  let second: KeywordRunController | undefined;
  try {
    advanceToCommit(first); const firstOutput = first.commit(); const before = statSync(currentPath);
    second = new KeywordRunController(facts, { modelVersion: "test/second",
      sourcePath: DEFAULT_KEYWORD_BASE_DB, currentPath, statePath, batchSize: 100,
      publishCurrent: () => { throw new Error("注入的原子发布失败"); } });
    advanceToCommit(second); assert.throws(() => second!.commit(), /原子发布失败/);
    const after = statSync(currentPath); assert.equal(after.ino, before.ino); assert.equal(after.size, before.size);
    const db = new DatabaseSync(currentPath, { readOnly: true });
    assert.equal((db.prepare("SELECT run_id FROM fact_keyword_agent_manifest").get() as any).run_id, firstOutput.run_id);
    db.close(); assert.equal(second.stage, "failed"); assert.equal(existsSync(second.stagingPath), false);
  } finally {
    if (second && second.stage !== "completed" && second.stage !== "failed") second.fail("测试清理");
    if (first.stage !== "completed" && first.stage !== "failed") first.fail("测试清理");
    rmSync(dir, { recursive: true, force: true });
  }
});

test("SIGTERM 只标记当前 run 失败并保留其他运行", () => {
  const dir = mkdtempSync(join(tmpdir(), "bamboo-keyword-v2-signal-"));
  const currentPath = join(dir, "current.sqlite"), statePath = join(dir, "state.sqlite");
  const run = new KeywordRunController(facts, { modelVersion: "test/signal",
    sourcePath: DEFAULT_KEYWORD_BASE_DB, currentPath, statePath, batchSize: 100 });
  const other = new KeywordRunController(facts, { modelVersion: "test/other",
    sourcePath: DEFAULT_KEYWORD_BASE_DB, currentPath, statePath, batchSize: 100 });
  const target = new EventEmitter(); let exitCode: number | undefined;
  const cleanup = installKeywordSignalHandlers(() => run, (code) => { exitCode = code; }, target as any);
  try {
    run.acceptContext(facts.context_hash); other.acceptContext(facts.context_hash); target.emit("SIGTERM");
    assert.equal(exitCode, 143); assert.equal(run.stage, "failed"); assert.equal(other.stage, "market");
    assert.equal(existsSync(other.stagingPath), true);
  } finally {
    cleanup(); if (other.stage !== "completed" && other.stage !== "failed") other.fail("测试清理");
    rmSync(dir, { recursive: true, force: true });
  }
});
