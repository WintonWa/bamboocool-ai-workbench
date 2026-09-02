import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { DatabaseSync } from "node:sqlite";
import {
  ADS_CHILD_DECISION_POINTS,
  ADS_EVIDENCE_TYPES,
  appendAdsOutputPoint,
  beginAdsChildDecisionRun,
  bindWorkbenchContext,
  completeAdsChildDecisionRun,
  DIAGNOSIS_COVERAGE_TYPES,
  loadAdsAgentRawFacts,
  validateAdsOutputPoint,
  validateAdsFacts,
  validateB0bConstraints,
  writeB0bSeamRun,
  type AdsAgentFacts,
  type AdsB0bConstraint,
} from "../src/ads-agent.ts";

function loadedFacts(childAsin = "B0B3LWGP36"): AdsAgentFacts {
  const raw = loadAdsAgentRawFacts(childAsin);
  const contextHash = "a".repeat(64);
  return bindWorkbenchContext(raw, {
    child_asin: raw.child_asin,
    context_hash: contextHash,
    context_id: `${raw.source_context_id}@${contextHash.slice(0, 12)}`,
    data_as_of: raw.source_data_as_of,
  });
}

function validItems(facts: AdsAgentFacts): AdsB0bConstraint[] {
  const inventory = facts.evidence.find((item) => item.evidence_type === "INVENTORY_CONTEXT")!;
  const performance = facts.evidence.find((item) => item.evidence_type === "AD_PERFORMANCE")!;
  return [
    {
      constraint_id: `con_${facts.child_asin}_01`,
      goal_version: facts.goal_version,
      kind: "hard",
      domain: "inventory",
      label: "当前库存承接待确认",
      detail: `当前可售${inventory.payload.closing_fba_sellable}件、在途${inventory.payload.fba_inbound}件；上游库存Agent未运行，是否满足目标暂不能确认`,
      is_satisfied: null,
      evidence_ref: inventory.evidence_id,
    },
    {
      constraint_id: `con_${facts.child_asin}_02`,
      goal_version: facts.goal_version,
      kind: "observe",
      domain: "cost",
      label: "7天归因效率待观察",
      detail: "7天ACoS约30.1%，客户效率阈值尚未确认",
      is_satisfied: null,
      evidence_ref: performance.evidence_id,
    },
  ];
}

test("B0b 输入桥只返回干净事实且跨归因窗口不合并", () => {
  const facts = loadedFacts();
  assert.deepEqual(validateAdsFacts(facts), []);
  assert.equal(facts.open_output_point, "B0b");
  assert.equal(facts.operator_goal.source_ref, "operator_set");
  assert.equal(facts.upstream_inventory_agent.available, false);
  assert.deepEqual(facts.evidence_index, facts.evidence);
  assert.ok(facts.evidence_index.every((item) => ADS_EVIDENCE_TYPES.includes(item.evidence_type)));
  assert.ok(facts.evidence_index.every((item) => item.subject_id && item.valid_as_of && item.source_ref));
  const serialized = JSON.stringify(facts);
  for (const forbidden of [
    '"stage_contracts"', '"next_stage_contract"', '"product_lifecycle"',
    '"coverage_days"', '"risk_status"', '"suggested_replenishment_qty"',
    '"match_level"', '"pressure_type"',
  ]) assert.doesNotMatch(serialized, new RegExp(forbidden));
  const performance = facts.evidence.find((item) => item.evidence_type === "AD_PERFORMANCE")!.payload;
  assert.equal(performance.aggregate_ad_sales, null);
  assert.equal(performance.aggregate_acos, null);
  assert.equal(performance.aggregate_roas, null);
});

test("B0b 门禁检查字段、证据、数字和未确认规则", () => {
  const facts = loadedFacts();
  const items = validItems(facts);
  assert.deepEqual(validateB0bConstraints(facts, items), []);

  const badEvidence = structuredClone(items);
  badEvidence[0]!.evidence_ref = "missing:evidence";
  assert.match(validateB0bConstraints(facts, badEvidence).join("；"), /evidence_ref 悬空/);

  const badNumber = structuredClone(items);
  badNumber[0]!.detail = "当前可售999999件，库存状态待确认";
  assert.match(validateB0bConstraints(facts, badNumber).join("；"), /引用数字不在证据/);

  const hardCost = structuredClone(items);
  hardCost[1]!.kind = "hard";
  assert.match(validateB0bConstraints(facts, hardCost).join("；"), /成本\/流量不得升级为 hard/);
});

test("上游库存 Agent 缺失时拒绝模型编造未来库存投影", () => {
  const facts = loadedFacts();
  const items = validItems(facts);
  items[0]!.label = "库存将在未来断货";
  items[0]!.detail = "当前库存不足，预计很快断货";
  assert.match(validateB0bConstraints(facts, items).join("；"), /不能输出库存投影结论/);
});

test("B0b completed 运行只写约定的两表接缝", () => {
  const facts = loadedFacts();
  const items = validItems(facts);
  const dir = mkdtempSync(join(tmpdir(), "bamboo-ads-b0b-"));
  try {
    const dbPath = join(dir, "ads.sqlite");
    const output = writeB0bSeamRun(facts, items, "test/model", dbPath);
    const db = new DatabaseSync(dbPath, { readOnly: true });
    const run = db.prepare(`SELECT run_type, subject_kind, subject_id, child_asin,
      status, diagnosis_coverage, model_version FROM fact_ads_agent_run WHERE run_id=?`)
      .get(output.run.run_id) as Record<string, string>;
    const rows = db.prepare("SELECT * FROM fact_ads_agent_output WHERE run_id=? ORDER BY item_ord")
      .all(output.run.run_id) as Array<Record<string, any>>;
    const runColumns = new Set(
      (db.prepare("PRAGMA table_info(fact_ads_agent_run)").all() as Array<{ name: string }>).map((row) => row.name),
    );
    db.close();
    assert.equal(run.run_type, "child_decision");
    assert.equal(run.subject_kind, "child_asin");
    assert.equal(run.subject_id, facts.child_asin);
    assert.equal(run.status, "completed");
    assert.equal(run.diagnosis_coverage, "");
    assert.equal(run.model_version, "test/model");
    assert.ok(runColumns.has("run_type") && runColumns.has("subject_kind") && runColumns.has("subject_id"));
    assert.equal(rows.length, items.length);
    assert.ok(rows.every((row) => row.output_point === "B0b" && row.point_ord === 1));
    assert.deepEqual(rows.map((row) => JSON.parse(row.payload)), items);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

function fullOutputs(facts: AdsAgentFacts): Record<string, Record<string, any>[]> {
  const keyword = facts.evidence.find((item) => item.evidence_type === "KEYWORD_POSITION")!;
  const competitor = facts.evidence.find((item) => item.evidence_type === "COMPETITOR_MARKET")!;
  const structure = facts.evidence.find((item) => item.evidence_type === "AD_STRUCTURE")!;
  const performance = facts.evidence.find((item) => item.evidence_type === "AD_PERFORMANCE")!;
  const competitorAsin = competitor.evidence_id.split(".")[3]!;
  const kwId = keyword.evidence_id.split(".")[3]!;
  const taskId = `task_${facts.child_asin}_01`;
  const diagnosisId = `diag_${facts.child_asin}_01`;
  return {
    B0b: validItems(facts),
    B0cd: [
      { item_kind: "keyword_match", match_id: `match_${facts.child_asin}_01`, kw_id: kwId, match_level: "high", demand_side: "核心品类需求", product_side: "本品属性与需求一致", basis: "关键词位置事实与产品身份一致", evidence_ids: [keyword.evidence_id] },
      { item_kind: "competitor_pressure", pressure_id: `pressure_${facts.child_asin}_01`, competitor_asin: competitorAsin, brand: String(competitor.payload.brand ?? "unknown"), pressure_type: "price", detail: "存在可比竞品价格背景", is_verified: 1, observed_at: competitor.observed_at, evidence_ids: [competitor.evidence_id] },
    ],
    B0e: [{ issue_id: `issue_${facts.child_asin}_01`, issue_type: "shared", ad_object_id: null, label: "结构共享", detail: "广告对象与多个产品存在推广关系，归因需要隔离解释", evidence_ids: [structure.evidence_id] }],
    B1: [{
      task_id: taskId, decision_id: facts.context_id.split("@")[0], goal_version: facts.goal_version,
      task_type: "CLARIFY_ATTRIBUTION_BOUNDARY", task_direction: "OBSERVE", priority: "P1",
      target_scope: facts.child_asin, constraints: ["保持归因窗口隔离"], evaluation_direction: "核验对象与产品映射",
      stop_condition: "归因边界可以明确解释", applies_from: facts.data_as_of, applies_to: null,
      rule_status: "unconfirmed", exact_budget: null, exact_bid: null, exact_placement_adjustment: null,
      exact_values_withheld: true, evidence_ids: [structure.evidence_id, performance.evidence_id],
      inventory_constrained: 0, judgment_mode: "conditional",
    }],
    B2: [{
      mapping_id: `map_${facts.child_asin}_01`, task_id: taskId, ad_object_id: null,
      coverage_status: "missing", attribution_limit: "unattributed", target_fit: "当前没有单独对象承接",
      result_supports_purpose: "尚不能确认", gap_source: "structure", basis_level: "conditional",
      is_automatic_error: 0, note: "结构缺口需要运营确认", evidence_ids: [structure.evidence_id], judgment_mode: "conditional",
    }],
    B3: [{
      diagnosis_id: diagnosisId, task_id: taskId, problem_type: "ATTRIBUTION_UNCLEAR",
      what_happened: "当前结构没有独立对象承接该任务", impacted_goal: facts.operator_goal.goal_label,
      priority: "P1", confidence: "medium", basis_type: "conditional", uncertainty: "对象共享关系仍需运营核验",
      missing_input: "缺少运营确认的对象归属", check_direction: "核对广告对象与子 ASIN 的实际承接关系",
      causal_claim: 0, evidence_ids: [structure.evidence_id], judgment_mode: "conditional",
    }],
    B3b: DIAGNOSIS_COVERAGE_TYPES.map((problemType) => ({
      problem_type: problemType, hit: problemType === "ATTRIBUTION_UNCLEAR" ? 1 : 0,
      why_not: problemType === "ATTRIBUTION_UNCLEAR" ? "" : "本次证据未命中该类问题",
    })),
    B4: [{
      recommendation_id: `rec_${facts.child_asin}_01`, diagnosis_id: diagnosisId,
      product_goal_version: facts.goal_version, ad_purpose: null, ad_object_id: null,
      structure_gap_id: `issue_${facts.child_asin}_01`, direction: "REQUEST_INFO",
      rationale: "先核验广告对象归属，再决定是否调整", preconditions: ["确认对象归属"], risks: ["归因误判"],
      uncertainty: "缺少运营确认", observation_metrics: ["对象覆盖状态"], review_windows: ["D+3"],
      d7_not_required: 1, rule_status: "unconfirmed", exact_value: null, exact_values_withheld: true,
      evidence_ids: [structure.evidence_id], judgment_mode: "conditional",
    }],
  };
}

test("完整子 ASIN 运行逐点落表，缺点时不能 completed", () => {
  const facts = loadedFacts();
  const outputs = fullOutputs(facts);
  const dir = mkdtempSync(join(tmpdir(), "bamboo-ads-full-"));
  try {
    const dbPath = join(dir, "ads.sqlite");
    const started = beginAdsChildDecisionRun(facts, "test/model", dbPath);
    const accepted: Record<string, Record<string, any>[]> = {};
    assert.throws(() => appendAdsOutputPoint(facts, started.run.run_id, "B1", outputs.B1!, accepted, dbPath), /之前必须先完成 B0b/);
    appendAdsOutputPoint(facts, started.run.run_id, "B0b", outputs.B0b!, accepted, dbPath); accepted.B0b = outputs.B0b!;
    assert.throws(() => completeAdsChildDecisionRun(started.run.run_id, dbPath), /缺少 B0cd/);
    for (const point of ADS_CHILD_DECISION_POINTS.slice(1)) {
      assert.deepEqual(validateAdsOutputPoint(facts, point, outputs[point]!, accepted), []);
      appendAdsOutputPoint(facts, started.run.run_id, point, outputs[point]!, accepted, dbPath);
      accepted[point] = outputs[point]!;
    }
    const done = completeAdsChildDecisionRun(started.run.run_id, dbPath);
    assert.equal(done.status, "completed");
    const db = new DatabaseSync(dbPath, { readOnly: true });
    const run = db.prepare("SELECT status, context_hash, context_id, data_as_of FROM fact_ads_agent_run WHERE run_id=?").get(started.run.run_id) as Record<string, string>;
    const points = db.prepare("SELECT output_point, COUNT(*) n FROM fact_ads_agent_output WHERE run_id=? GROUP BY output_point ORDER BY MIN(point_ord)").all(started.run.run_id) as Array<Record<string, any>>;
    db.close();
    assert.equal(run.status, "completed");
    assert.equal(run.context_hash, facts.context_hash);
    assert.equal(run.context_id, facts.context_id);
    assert.equal(run.data_as_of, facts.data_as_of);
    assert.deepEqual(points.map((row) => row.output_point), ADS_CHILD_DECISION_POINTS);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

test("跨阶段语义门禁拒绝把缺输入误写成缺任务或库存风险", () => {
  const facts = loadedFacts();
  const outputs = fullOutputs(facts);
  const accepted = { B1: outputs.B1!, B3: outputs.B3! };

  const missingTask = structuredClone(outputs.B3![0]!);
  missingTask.problem_type = "REQUIRED_TASK_MISSING";
  assert.match(validateAdsOutputPoint(facts, "B3", [missingTask], accepted).join("；"), /task_id 必须为空/);

  const inventoryRisk = structuredClone(outputs.B3![0]!);
  inventoryRisk.problem_type = "INVENTORY_COVERAGE_RISK";
  assert.match(validateAdsOutputPoint(facts, "B3", [inventoryRisk], accepted).join("；"), /不能把“无法判断”写成库存覆盖风险/);

  const badCoverage = structuredClone(outputs.B3b!);
  badCoverage.find((item) => item.problem_type === "ATTRIBUTION_UNCLEAR")!.hit = 0;
  badCoverage.find((item) => item.problem_type === "ATTRIBUTION_UNCLEAR")!.why_not = "错误地标成未命中";
  assert.match(validateAdsOutputPoint(facts, "B3b", badCoverage, accepted).join("；"), /必须与 B3 诊断一致/);

  const badPressure = structuredClone(outputs.B0cd!.find((item) => item.item_kind === "competitor_pressure")!);
  badPressure.detail = "竞品销量为99999999";
  assert.match(validateAdsOutputPoint(facts, "B0cd", [badPressure], {}).join("；"), /引用数字不在所引证据/);
});
