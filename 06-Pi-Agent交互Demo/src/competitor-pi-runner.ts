import {
  createAgentSession,
  DefaultResourceLoader,
  defineTool,
  getAgentDir,
  ModelRuntime,
  SessionManager,
  SettingsManager,
} from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import {
  COMPETITOR_V2_PROJECT_ROOT,
  COMPETITOR_V2_STAGES,
  CompetitorWorkflowV2,
  assertModelInputSafe,
  type AssembleDecision,
  type AttentionDecision,
  type ChangeDecision,
  type CompetitorModelFacts,
  type CompetitorRunRequest,
  type ConcurrencyDecision,
  type EvidenceDecision,
  type ImpactDecision,
  type JsonObject,
  type ReportSelectionDecision,
  type RepresentationDecision,
  type WorkflowSnapshot,
} from "./competitor-agent-v2.ts";

const nullableString = Type.Union([Type.String(), Type.Null()]);
const evidenceSchema = Type.Object({
  evidence_level: Type.Union([Type.Literal("sufficient"), Type.Literal("partial"), Type.Literal("insufficient")]),
  evidence_reason: Type.String(),
  judgment_summary: Type.String(),
});
const changeSchema = Type.Object({
  candidate_id: Type.String(),
  domain: Type.Union([Type.Literal("price_promo"), Type.Literal("market"), Type.Literal("keyword"), Type.Literal("traffic")]),
  direction: Type.Union([Type.Literal("up"), Type.Literal("down"), Type.Literal("neutral")]),
  current_state: Type.Union([Type.Literal("still_running"), Type.Literal("restored"), Type.Literal("ended"), Type.Literal("unconfirmed")]),
  label: Type.String(),
  basis: Type.String(),
  confidence: Type.Union([Type.Literal("high"), Type.Literal("medium"), Type.Literal("low")]),
});
const representationSchema = Type.Object({
  candidate_id: Type.String(), represents_family: Type.Boolean(), coverage_note: nullableString,
});
const impactSchema = Type.Object({
  candidate_id: Type.String(), relation_id: Type.String(), shared_keyword: nullableString,
  pressure_dimension: Type.Union([
    Type.Literal("price"), Type.Literal("promo"), Type.Literal("market"), Type.Literal("keyword"), Type.Literal("traffic"),
  ]),
  statement: Type.String(),
  confidence: Type.Union([Type.Literal("high"), Type.Literal("medium"), Type.Literal("low")]),
});
const concurrencySchema = Type.Object({
  change_a_id: Type.String(), change_b_id: Type.String(),
  relation: Type.Union([Type.Literal("concurrent"), Type.Literal("sequential"), Type.Literal("independent"), Type.Literal("insufficient")]),
  statement: Type.String(), missing_evidence: nullableString,
});
const attentionSchema = Type.Object({
  attention_level: Type.Union([Type.Literal("high"), Type.Literal("medium"), Type.Literal("low"), Type.Literal("none")]),
  attention_summary: Type.String(),
  reasons: Type.Array(Type.Object({ candidate_id: nullableString, label: Type.String(), weight_note: nullableString })),
});
const reportSchema = Type.Union([Type.Null(), Type.Object({
  headline: Type.String(), body: Type.String(), impact_note: nullableString, unconfirmed_note: nullableString,
})]);
const assembleSchema = Type.Object({
  open_items: Type.Array(Type.Object({
    item_kind: Type.Union([Type.Literal("hypothesis"), Type.Literal("unconfirmed"), Type.Literal("watch")]),
    statement: Type.String(), needed_data: nullableString,
  })),
  diff: Type.Object({
    transition: Type.Union([
      Type.Literal("new"), Type.Literal("sustained"), Type.Literal("escalated"),
      Type.Literal("eased"), Type.Literal("cleared"),
    ]),
    statement: Type.String(),
    changed_domains: Type.Array(Type.Union([
      Type.Literal("price_promo"), Type.Literal("market"), Type.Literal("keyword"), Type.Literal("traffic"),
    ])),
  }),
  handoffs: Type.Array(Type.Object({
    target_page: Type.Union([Type.Literal("keyword"), Type.Literal("advertising")]),
    candidate_id: Type.String(), relation_id: nullableString, shared_keyword: nullableString,
    pressure_dimension: Type.Union([
      Type.Literal("price"), Type.Literal("promo"), Type.Literal("market"), Type.Literal("keyword"), Type.Literal("traffic"),
    ]),
    observable_fact: Type.String(),
  })),
});

function success(details: JsonObject) {
  return { content: [{ type: "text" as const, text: JSON.stringify(details) }], details };
}
function failure(error: unknown) {
  const message = error instanceof Error ? error.message : String(error);
  const details = { ok: false, errors: message.split("；") };
  return { isError: true, content: [{ type: "text" as const, text: JSON.stringify(details) }], details };
}
function guarded(action: () => JsonObject, onError?: (error: unknown) => void) {
  try { return success(action()); } catch (error) { onError?.(error); return failure(error); }
}

const SYSTEM_PROMPT = `你是 Bamboocool 竞品分析 Agent。只基于工具与当前任务提供的净化观察事实完成八步判断。

严格规则：
- 每个回合只调用当前唯一开放的工具，成功后立即结束；不要输出思维链或工具外报告。
- 数字、日期、对象、ID 和来源由程序锁定；模型只选择候选并填写定性中文。
- 不生成综合威胁分数，不推断竞品库存、广告花费、预算、出价或开关。
- 流量占比不能反推花费、预算或出价；价差只按件单价。
- family_coverage_pct 只是参考证据，必须结合主销身份、观察覆盖和变体结构自行判断整族代表性。
- 同期只可写“同期变化”或“可能相关”，不得升级为因果。
- 证据不足时直接短路到装配步骤：关注等级为 none、零依据、零变化、零影响、零报告、零交接。
- 前序已接受的价格变化若存在已确认且价差变化达阈值的竞争关系，必须逐一产出影响范围；已接受影响存在共同词时必须交接关键词证据，前序已接受流量结构变化时必须交接广告证据。
- 上一版的影响范围与交接会作为合法历史上下文提供；若当前证据仍支持且 diff 为持续或加重，不得静默清空。只有证据减弱或结论解除时才能撤销，并在 diff 中说明。
- 工具拒绝时根据 errors 修正并重试当前唯一工具。`;

const STAGE_LABELS: Record<string, string> = {
  judge_competitor_evidence: "判断竞品证据",
  judge_competitor_changes: "判断竞品变化",
  judge_family_representation: "判断整族代表性",
  judge_competitive_scope: "判断竞争范围",
  judge_change_concurrency: "判断变化同期关系",
  judge_attention_and_impact: "判断关注与影响",
  judge_report_selection: "判断报告选题",
  assemble_competitor_run: "装配竞品运行契约",
};

export class CompetitorStageError extends Error {
  readonly stage: string;
  readonly publicReason: string;

  constructor(stage: string, kind: "model" | "contract", gateDetail?: string) {
    const label = STAGE_LABELS[stage] ?? stage;
    const detail = kind === "model" ? "模型调用未完成" : "未提交通过门禁的工具结果";
    super(`${label}：${detail}`);
    this.name = "CompetitorStageError";
    this.stage = stage;
    const suffix = gateDetail ? `：${gateDetail}` : "";
    this.publicReason = `失败步骤：${label} · ${detail}${suffix}，请重新发起`;
  }
}

function safeGateDetail(error: unknown): string {
  const value = error instanceof Error ? error.message : String(error ?? "");
  return value.replace(/[\r\n\t]+/g, " ").trim().slice(0, 140);
}

function compactChangeTiming(facts: CompetitorModelFacts): JsonObject[] {
  return facts.change_candidates.map((item) => ({
    candidate_id: item.candidate_id,
    domain: item.allowed_domains?.[0] ?? null,
    date_from: item.date_from,
    date_to: item.date_to,
    duration_days: item.duration_days,
    current_states: item.allowed_current_states,
  }));
}

/**
 * Disclose only the facts needed by the current judgment stage. The full
 * envelope remains program-private for hashing and final contract validation.
 */
export function competitorStageContext(facts: CompetitorModelFacts, stage: string): JsonObject {
  const task = {
    family_asin: facts.family_asin,
    data_as_of: facts.data_as_of,
    window_from: facts.window_from,
    window_to: facts.window_to,
  };
  let context: JsonObject;
  switch (stage) {
    case "judge_competitor_evidence":
      const domainHealth = Object.values(facts.change_candidates.reduce((acc, item) => {
        const domain = String(item.allowed_domains?.[0] ?? "unknown");
        const current = acc[domain] ?? { domain, candidate_count: 0, evidence_gap_count: 0 };
        current.candidate_count += 1;
        if (item.evidence_gap) current.evidence_gap_count += 1;
        acc[domain] = current;
        return acc;
      }, {} as Record<string, { domain: string; candidate_count: number; evidence_gap_count: number }>));
      context = {
        stage, task,
        evidence_health: {
          status_events: facts.status_events,
          optional_channel_coverage: facts.observation_coverage,
          domain_health: domainHealth,
          candidate_count: facts.change_candidates.length,
          evidence_gap_count: facts.change_candidates.filter((item) => item.evidence_gap).length,
          stale_rule: facts.threshold_effects.stale_days,
        },
      };
      break;
    case "judge_competitor_changes":
      context = {
        stage, task,
        thresholds: {
          price_drop_pct: facts.thresholds.price_drop_pct,
          rank_shift_pct: facts.thresholds.rank_shift_pct,
          kw_rank_shift: facts.thresholds.kw_rank_shift,
          min_duration_days: facts.thresholds.min_duration_days,
        },
        threshold_effects: {
          price_drop_pct: facts.threshold_effects.price_drop_pct,
          rank_shift_pct: facts.threshold_effects.rank_shift_pct,
          kw_rank_shift: facts.threshold_effects.kw_rank_shift,
          min_duration_days: facts.threshold_effects.min_duration_days,
          traffic_series: facts.threshold_effects.traffic_series,
        },
        change_candidates: facts.change_candidates,
      };
      break;
    case "judge_family_representation":
      context = {
        stage, task,
        family: facts.family,
        family_coverage_reference_pct: facts.thresholds.family_coverage_pct,
        candidate_coverage: facts.change_candidates.map((item) => ({
          candidate_id: item.candidate_id,
          coverage: item.coverage,
        })),
      };
      break;
    case "judge_competitive_scope":
      context = {
        stage, task,
        gap_shift_reference_pct: facts.thresholds.gap_shift_pct,
        relation_candidates: facts.relation_candidates,
        shared_keyword_candidates: facts.shared_keyword_candidates,
      };
      break;
    case "judge_change_concurrency":
      context = {
        stage, task,
        change_timing: compactChangeTiming(facts),
        causal_ready: false,
      };
      break;
    case "judge_attention_and_impact":
      context = {
        stage, task,
        decision_rules: {
          minimum_reasons_when_attention_exists: 2,
          numeric_weight_allowed: false,
          composite_threat_score_allowed: false,
        },
      };
      break;
    case "judge_report_selection":
      context = {
        stage, task,
        report_eligibility: {
          evidence_level: "sufficient",
          attention_levels: ["high", "medium"],
          requires_family_level_change: true,
        },
      };
      break;
    case "assemble_competitor_run":
      context = {
        stage, task,
        previous_run: facts.previous_run,
        handoff_candidates: {
          relations: facts.relation_candidates,
          shared_keywords: facts.shared_keyword_candidates,
        },
        source_boundary: facts.source_boundary,
      };
      break;
    default:
      throw new Error(`未知竞品判断步骤：${stage}`);
  }
  assertModelInputSafe(context);
  return context;
}

function stagePrompt(stage: string, facts: CompetitorModelFacts, instruction: string): string {
  const context = competitorStageContext(facts, stage);
  return `进入步骤：${STAGE_LABELS[stage] ?? stage}。以下 JSON 仅包含本步骤新开放的只读事实；\n`
    + `前序已接受的判断保留在当前会话中。\n${JSON.stringify(context)}\n\n${instruction}`;
}

export async function promptCompetitorStage(
  session: { prompt: (value: string) => Promise<unknown> },
  workflow: { readonly expectedStage: string },
  stage: string,
  prompt: string,
  gateErrors: Map<string, string>,
): Promise<void> {
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const previousError = gateErrors.get(stage);
    gateErrors.delete(stage);
    const currentPrompt = attempt === 0 ? prompt
      : `上次 ${STAGE_LABELS[stage] ?? stage} 提交未通过门禁：${previousError ?? "未提交合法工具结果"}。`
        + `请修正后只调用 ${stage}，成功后立即结束。`;
    try {
      await session.prompt(currentPrompt);
    } catch {
      throw new CompetitorStageError(stage, "model");
    }
    if (workflow.expectedStage !== stage) return;
  }
  throw new CompetitorStageError(stage, "contract", gateErrors.get(stage));
}

export async function runCompetitorPiAgent(
  facts: CompetitorModelFacts,
  request: CompetitorRunRequest,
): Promise<WorkflowSnapshot> {
  assertModelInputSafe(facts);
  const workflow = new CompetitorWorkflowV2(facts);
  const gateErrors = new Map<string, string>();
  const stageGuard = (stage: string, action: () => JsonObject) => guarded(action, (error) => {
    gateErrors.set(stage, safeGateDetail(error));
  });
  const tools = [
    defineTool({
      name: COMPETITOR_V2_STAGES[0], label: "判断竞品证据",
      description: "根据观察连续性、断更、冲突、缺失和过期判断证据档位。",
      executionMode: "sequential", parameters: Type.Object({ decision: evidenceSchema }),
      execute: async (_id, params) => stageGuard(COMPETITOR_V2_STAGES[0], () => {
        workflow.submitEvidence(params.decision as EvidenceDecision);
        return { ok: true, next_stage: workflow.expectedStage };
      }),
    }),
    defineTool({
      name: COMPETITOR_V2_STAGES[1], label: "判断竞品变化",
      description: "从锁定候选中选择成立变化并判断性质、方向和状态。",
      executionMode: "sequential", parameters: Type.Object({ items: Type.Array(changeSchema) }),
      execute: async (_id, params) => stageGuard(COMPETITOR_V2_STAGES[1], () => {
        workflow.submitChanges(params.items as ChangeDecision[]);
        return { ok: true, next_stage: workflow.expectedStage };
      }),
    }),
    defineTool({
      name: COMPETITOR_V2_STAGES[2], label: "判断整族代表性",
      description: "综合覆盖、主销身份、在售子体和自报变体判断能否代表整族。",
      executionMode: "sequential", parameters: Type.Object({ items: Type.Array(representationSchema) }),
      execute: async (_id, params) => stageGuard(COMPETITOR_V2_STAGES[2], () => {
        workflow.submitRepresentation(params.items as RepresentationDecision[]);
        return { ok: true, next_stage: workflow.expectedStage };
      }),
    }),
    defineTool({
      name: COMPETITOR_V2_STAGES[3], label: "判断竞争范围",
      description: "只从当前竞品族的竞争关系桥和共同词候选中选择自有影响范围；已确认且价差变化达阈值的关系必须逐一覆盖。",
      executionMode: "sequential", parameters: Type.Object({ items: Type.Array(impactSchema) }),
      execute: async (_id, params) => stageGuard(COMPETITOR_V2_STAGES[3], () => {
        workflow.submitScope(params.items as ImpactDecision[]);
        return { ok: true, next_stage: workflow.expectedStage };
      }),
    }),
    defineTool({
      name: COMPETITOR_V2_STAGES[4], label: "判断变化同期关系",
      description: "判断同期、先后、独立或证据不足，因果恒为否。",
      executionMode: "sequential", parameters: Type.Object({ items: Type.Array(concurrencySchema) }),
      execute: async (_id, params) => stageGuard(COMPETITOR_V2_STAGES[4], () => {
        workflow.submitConcurrency(params.items as ConcurrencyDecision[]);
        return { ok: true, next_stage: workflow.expectedStage };
      }),
    }),
    defineTool({
      name: COMPETITOR_V2_STAGES[5], label: "判断关注与影响",
      description: "给出关注等级、摘要和至少两条不重复定性依据。",
      executionMode: "sequential", parameters: Type.Object({ decision: attentionSchema }),
      execute: async (_id, params) => stageGuard(COMPETITOR_V2_STAGES[5], () => {
        workflow.submitAttention(params.decision as AttentionDecision);
        return { ok: true, next_stage: workflow.expectedStage };
      }),
    }),
    defineTool({
      name: COMPETITOR_V2_STAGES[6], label: "判断报告选题",
      description: "仅为证据充分、高中关注且有整族变化的任务选择报告。",
      executionMode: "sequential", parameters: Type.Object({ report: reportSchema }),
      execute: async (_id, params) => stageGuard(COMPETITOR_V2_STAGES[6], () => {
        workflow.submitReport(params as ReportSelectionDecision);
        return { ok: true, next_stage: workflow.expectedStage };
      }),
    }),
    defineTool({
      name: COMPETITOR_V2_STAGES[7], label: "装配竞品运行契约",
      description: "装配待观察项、版本差异与下游冻结交接；仍被证据支持的上一版结果不得静默消失。",
      executionMode: "sequential", parameters: assembleSchema,
      execute: async (_id, params) => stageGuard(COMPETITOR_V2_STAGES[7], () => {
        workflow.submitAssemble(params as AssembleDecision);
        return { ok: true, ready_to_commit: true };
      }),
    }),
  ];

  const agentDir = getAgentDir();
  const settingsManager = SettingsManager.create(COMPETITOR_V2_PROJECT_ROOT, agentDir);
  const loader = new DefaultResourceLoader({
    cwd: COMPETITOR_V2_PROJECT_ROOT,
    agentDir,
    settingsManager,
    noExtensions: true,
    noPromptTemplates: true,
    noThemes: true,
    noContextFiles: true,
    systemPromptOverride: () => SYSTEM_PROMPT,
    appendSystemPromptOverride: () => [],
  });
  await loader.reload();
  const { session } = await createAgentSession({
    cwd: COMPETITOR_V2_PROJECT_ROOT,
    agentDir,
    modelRuntime: await ModelRuntime.create(),
    thinkingLevel: "low",
    tools: [...COMPETITOR_V2_STAGES],
    customTools: tools,
    resourceLoader: loader,
    sessionManager: SessionManager.inMemory(COMPETITOR_V2_PROJECT_ROOT),
    settingsManager,
  });
  const instructions: Record<string, string> = {
    [COMPETITOR_V2_STAGES[0]]: `只调用 ${COMPETITOR_V2_STAGES[0]}，判断证据档位并结束。某个可选观察通道没有行，不等于整个 run 证据不足；结合 domain_health、缺口和状态事件判断现有变化通道能否支持分析。`,
    [COMPETITOR_V2_STAGES[1]]: `只调用 ${COMPETITOR_V2_STAGES[1]}。从候选中选择成立变化，不改写锁定数字。`,
    [COMPETITOR_V2_STAGES[2]]: `只调用 ${COMPETITOR_V2_STAGES[2]}。逐条覆盖已选变化；覆盖阈值只是参考，不是硬锁。`,
    [COMPETITOR_V2_STAGES[3]]: `只调用 ${COMPETITOR_V2_STAGES[3]}。逐一覆盖已确认且价差变化达阈值的关系；确实没有合法自有影响对象时才提交空数组。`,
    [COMPETITOR_V2_STAGES[4]]: `只调用 ${COMPETITOR_V2_STAGES[4]}。不足两条变化时提交空数组，不判因果。`,
    [COMPETITOR_V2_STAGES[5]]: `只调用 ${COMPETITOR_V2_STAGES[5]}。有关注等级时给至少两条不重复定性依据。`,
    [COMPETITOR_V2_STAGES[6]]: `只调用 ${COMPETITOR_V2_STAGES[6]}。严格遵守报告资格门禁。`,
    [COMPETITOR_V2_STAGES[7]]: `只调用 ${COMPETITOR_V2_STAGES[7]}。首次 V2 diff 为 new；证据不足短路时必须零变化、零影响、零交接。只有前序已接受的影响范围存在共同词时才交接关键词证据；只有前序已接受流量结构变化时才交接广告证据。持续或加重时不得静默删除上一版仍受支持的交接。`,
  };
  try {
    const firstStage = COMPETITOR_V2_STAGES[0];
    session.setActiveToolsByName([firstStage]);
    await promptCompetitorStage(session, workflow, firstStage, stagePrompt(firstStage, facts, instructions[firstStage]!), gateErrors);
    if (workflow.expectedStage === COMPETITOR_V2_STAGES[7]) {
      const finalStage = COMPETITOR_V2_STAGES[7];
      session.setActiveToolsByName([finalStage]);
      await promptCompetitorStage(session, workflow, finalStage, stagePrompt(finalStage, facts, instructions[finalStage]!), gateErrors);
      return workflow.snapshot();
    }
    for (let index = 1; index < COMPETITOR_V2_STAGES.length; index += 1) {
      const stage = COMPETITOR_V2_STAGES[index]!;
      if (workflow.expectedStage !== stage) throw new Error(`Pi 未完成上一步，当前应为 ${workflow.expectedStage}`);
      session.setActiveToolsByName([stage]);
      await promptCompetitorStage(session, workflow, stage, stagePrompt(stage, facts, instructions[stage]!), gateErrors);
    }
    return workflow.snapshot();
  } finally {
    session.dispose();
  }
}
