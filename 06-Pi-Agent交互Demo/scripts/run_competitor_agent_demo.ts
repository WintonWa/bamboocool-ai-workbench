import {
  createAgentSession,
  DefaultResourceLoader,
  defineTool,
  getAgentDir,
  ModelRuntime,
  SessionManager,
  SettingsManager,
} from '@earendil-works/pi-coding-agent';
import { Type } from 'typebox';
import {
  COMPETITOR_PROJECT_ROOT,
  COMPETITOR_TOOL_NAMES,
  CompetitorWorkflow,
  loadCompetitorFacts,
  writeCompetitorAgentRun,
  type AttentionDecision,
  type ChangeDecision,
  type ConcurrencyDecision,
  type EvidenceDecision,
  type ImpactDecision,
  type JsonObject,
  type OutputDecision,
  type RepresentationDecision,
} from '../src/competitor-agent.ts';

const familyAsin = (process.argv[2] ?? 'B0CJ9QLVPP').trim().toUpperCase();
let workflow: CompetitorWorkflow | undefined;
let persisted: JsonObject | undefined;
let modelVersion = 'pi-local-default';

const nullableString = Type.Union([Type.String(), Type.Null()]);
const evidenceSchema = Type.Object({
  evidence_level: Type.Union([Type.Literal('sufficient'), Type.Literal('partial'), Type.Literal('insufficient')]),
  evidence_reason: Type.String(),
  judgment_summary: Type.String(),
});
const changeSchema = Type.Object({
  candidate_id: Type.String(),
  domain: Type.Union([Type.Literal('price_promo'), Type.Literal('market'), Type.Literal('keyword'), Type.Literal('traffic')]),
  direction: Type.Union([Type.Literal('up'), Type.Literal('down'), Type.Literal('neutral')]),
  current_state: Type.Union([Type.Literal('still_running'), Type.Literal('restored'), Type.Literal('ended'), Type.Literal('unconfirmed')]),
  label: Type.String(), basis: Type.String(),
  confidence: Type.Union([Type.Literal('high'), Type.Literal('medium'), Type.Literal('low')]),
});
const representationSchema = Type.Object({
  candidate_id: Type.String(), represents_family: Type.Boolean(), coverage_note: nullableString,
});
const impactSchema = Type.Object({
  candidate_id: Type.String(), relation_id: Type.String(), shared_keyword: nullableString,
  pressure_dimension: Type.Union([
    Type.Literal('price'), Type.Literal('promo'), Type.Literal('market'),
    Type.Literal('keyword'), Type.Literal('traffic'),
  ]),
  statement: Type.String(),
  confidence: Type.Union([Type.Literal('high'), Type.Literal('medium'), Type.Literal('low')]),
});
const concurrencySchema = Type.Object({
  change_a_id: Type.String(), change_b_id: Type.String(),
  relation: Type.Union([
    Type.Literal('concurrent'), Type.Literal('sequential'),
    Type.Literal('independent'), Type.Literal('insufficient'),
  ]),
  statement: Type.String(), missing_evidence: nullableString,
});
const attentionSchema = Type.Object({
  attention_level: Type.Union([
    Type.Literal('high'), Type.Literal('medium'), Type.Literal('low'), Type.Literal('none'),
  ]),
  attention_summary: Type.String(),
  reasons: Type.Array(Type.Object({
    candidate_id: nullableString, label: Type.String(), weight_note: nullableString,
  })),
});
const outputSchema = Type.Object({
  open_items: Type.Array(Type.Object({
    item_kind: Type.Union([Type.Literal('hypothesis'), Type.Literal('unconfirmed'), Type.Literal('watch')]),
    statement: Type.String(), needed_data: nullableString,
  })),
  diff: Type.Object({
    transition: Type.Union([
      Type.Literal('new'), Type.Literal('sustained'), Type.Literal('escalated'),
      Type.Literal('eased'), Type.Literal('cleared'),
    ]),
    statement: Type.String(),
    changed_domains: Type.Array(Type.Union([
      Type.Literal('price_promo'), Type.Literal('market'), Type.Literal('keyword'), Type.Literal('traffic'),
    ])),
  }),
  report: Type.Union([Type.Null(), Type.Object({
    headline: Type.String(), body: Type.String(), impact_note: nullableString, unconfirmed_note: nullableString,
  })]),
  handoffs: Type.Array(Type.Object({
    target_page: Type.Union([Type.Literal('keyword'), Type.Literal('advertising')]),
    candidate_id: Type.String(), relation_id: nullableString, shared_keyword: nullableString,
    pressure_dimension: Type.Union([
      Type.Literal('price'), Type.Literal('promo'), Type.Literal('market'),
      Type.Literal('keyword'), Type.Literal('traffic'),
    ]),
    observable_fact: Type.String(),
  })),
});

function success(details: JsonObject) {
  return { content: [{ type: 'text' as const, text: JSON.stringify(details) }], details };
}

function failure(error: unknown) {
  const message = error instanceof Error ? error.message : String(error);
  const details = { ok: false, errors: message.split('；') };
  return { isError: true, content: [{ type: 'text' as const, text: JSON.stringify(details) }], details };
}

function current(): CompetitorWorkflow {
  if (!workflow) throw new Error('请先读取竞品分析上下文');
  return workflow;
}

function guarded(action: () => JsonObject) {
  try { return success(action()); } catch (error) { return failure(error); }
}

const tools = [
  defineTool({
    name: COMPETITOR_TOOL_NAMES[0], label: '读取竞品分析上下文',
    description: '只读冻结观察窗、阈值、候选对象、数值和引用。', executionMode: 'sequential',
    parameters: Type.Object({ family_asin: Type.String() }),
    execute: async (_id, params) => guarded(() => {
      const facts = loadCompetitorFacts(params.family_asin);
      if (facts.family_asin !== familyAsin) throw new Error('family_asin 与当前 CLI 任务不一致');
      workflow = new CompetitorWorkflow(facts);
      process.stderr.write(`[1/9] 已冻结 ${facts.family_asin} 观察上下文 ${facts.source_context_hash.slice(0, 12)}\n`);
      return { ok: true, ...facts, next_stage: 'evidence' };
    }),
  }),
  defineTool({
    name: COMPETITOR_TOOL_NAMES[1], label: '评估竞品证据可用性',
    description: '根据断更、冲突、过期和缺失观察定证据档位。', executionMode: 'sequential',
    parameters: Type.Object({ family_asin: Type.String(), decision: evidenceSchema }),
    execute: async (_id, params) => guarded(() => {
      const flow = current();
      if (params.family_asin !== flow.facts.family_asin) throw new Error('family_asin 不一致');
      flow.submitEvidence(params.decision as EvidenceDecision);
      process.stderr.write('[2/9] 证据档位通过\n');
      return { ok: true, accepted_stage: 'evidence', next_stage: 'changes', candidates: flow.facts.change_candidates };
    }),
  }),
  defineTool({
    name: COMPETITOR_TOOL_NAMES[2], label: '分类竞品变化',
    description: '对锁定候选判断变化类型、方向、状态与中文表达。', executionMode: 'sequential',
    parameters: Type.Object({ family_asin: Type.String(), items: Type.Array(changeSchema) }),
    execute: async (_id, params) => guarded(() => {
      const flow = current(); flow.submitChanges(params.items as ChangeDecision[]);
      process.stderr.write('[3/9] 变化分类通过\n');
      return { ok: true, accepted_stage: 'changes', next_stage: 'representation',
        coverage: flow.facts.change_candidates.map((item) => ({ candidate_id: item.candidate_id, coverage: item.coverage })) };
    }),
  }),
  defineTool({
    name: COMPETITOR_TOOL_NAMES[3], label: '评估整族代表性',
    description: '逐条判断变化是否可上卷为竞品产品族结论。', executionMode: 'sequential',
    parameters: Type.Object({ family_asin: Type.String(), items: Type.Array(representationSchema) }),
    execute: async (_id, params) => guarded(() => {
      const flow = current(); flow.submitRepresentation(params.items as RepresentationDecision[]);
      process.stderr.write('[4/9] 整族代表性通过\n');
      return { ok: true, accepted_stage: 'representation', next_stage: 'impacts',
        relation_candidates: flow.facts.relation_candidates,
        shared_keyword_candidates: flow.facts.shared_keyword_candidates };
    }),
  }),
  defineTool({
    name: COMPETITOR_TOOL_NAMES[4], label: '映射竞争影响',
    description: '只能使用竞争关系桥和共同词候选映射影响。', executionMode: 'sequential',
    parameters: Type.Object({ family_asin: Type.String(), items: Type.Array(impactSchema) }),
    execute: async (_id, params) => guarded(() => {
      const flow = current(); flow.submitImpacts(params.items as ImpactDecision[]);
      process.stderr.write('[5/9] 竞争影响通过\n');
      return { ok: true, accepted_stage: 'impacts', next_stage: 'concurrency' };
    }),
  }),
  defineTool({
    name: COMPETITOR_TOOL_NAMES[5], label: '评估变化同期关系',
    description: '只表述同期、先后、独立或证据不足，因果锁定为否。', executionMode: 'sequential',
    parameters: Type.Object({ family_asin: Type.String(), items: Type.Array(concurrencySchema) }),
    execute: async (_id, params) => guarded(() => {
      const flow = current(); flow.submitConcurrency(params.items as ConcurrencyDecision[]);
      process.stderr.write('[6/9] 同期关系通过\n');
      return { ok: true, accepted_stage: 'concurrency', next_stage: 'attention' };
    }),
  }),
  defineTool({
    name: COMPETITOR_TOOL_NAMES[6], label: '分配关注等级',
    description: '给可解释分级、一句话摘要和定性依据，禁止综合分数。', executionMode: 'sequential',
    parameters: Type.Object({ family_asin: Type.String(), decision: attentionSchema }),
    execute: async (_id, params) => guarded(() => {
      const flow = current(); flow.submitAttention(params.decision as AttentionDecision);
      process.stderr.write('[7/9] 关注等级通过\n');
      return { ok: true, accepted_stage: 'attention', next_stage: 'outputs', previous_run: flow.facts.previous_run };
    }),
  }),
  defineTool({
    name: COMPETITOR_TOOL_NAMES[7], label: '装配竞品输出',
    description: '装配待观察项、版本差异、合格报告和冻结交接。', executionMode: 'sequential',
    parameters: Type.Object({ family_asin: Type.String(), decision: outputSchema }),
    execute: async (_id, params) => guarded(() => {
      const flow = current(); flow.submitOutputs(params.decision as OutputDecision);
      process.stderr.write('[8/9] 输出装配通过\n');
      return { ok: true, accepted_stage: 'outputs', ready_to_commit: true };
    }),
  }),
  defineTool({
    name: COMPETITOR_TOOL_NAMES[8], label: '提交竞品分析契约',
    description: '执行跨表门禁，在单事务写入 sidecar 并标记 completed。', executionMode: 'sequential',
    parameters: Type.Object({ family_asin: Type.String() }),
    execute: async (_id, params) => guarded(() => {
      const flow = current();
      if (params.family_asin !== flow.facts.family_asin) throw new Error('family_asin 不一致');
      persisted = writeCompetitorAgentRun(flow.facts, flow.snapshot(), modelVersion);
      flow.markCommitted();
      process.stderr.write(`[9/9] 已写入 ${persisted.run.run_id}\n`);
      return { ok: true, ...persisted };
    }),
  }),
];

const SYSTEM_PROMPT = `你是 Bamboocool 竞品分析 Agent。确定性数字、日期、对象和引用由工具锁定，你只负责定性判断和成品中文。

严格规则：
- 每个回合只调用当前唯一开放的工具，成功后立即结束。
- 不在中文槽里自行写阿拉伯数字，不泄漏英文内部枚举。
- 不生成综合威胁分数，不推断竞品库存，不用流量占比反推花费、预算或出价。
- 同期关系只说“同期变化”或“可能相关”，不得写导致、驱动或造成。
- 证据不足时必须给 none、零条依据、零影响、零报告、零交接。
- 只有事实包存在 evidence_gap 候选时才判 insufficient；未参与当前变化的其他域缺行不等于全局证据不足。
- 局部变化不得写整族报告。工具拒绝时根据 errors 修正并重试当前工具。`;

const PROMPTS = [
  `只调用上下文工具读取 ${familyAsin}，然后结束本轮。`,
  '只调用证据工具。根据上轮状态事件和缺失观察判断证据档位；中文不写数字。',
  '只调用变化分类工具。逐条使用 candidate_id 和允许枚举，不改日期数字。',
  '只调用整族代表性工具。覆盖每条已选候选，局部变化明确写不代表整族。',
  '只调用竞争影响工具。证据不足则提交空数组；否则只用候选关系。',
  '只调用同期关系工具。没有可比的两条变化可提交空数组；不判因果。',
  '只调用关注等级工具。有等级必须至少两条定性依据，证据不足必须无等级且零依据。',
  '只调用输出装配工具。首次运行差异为 new；报告和交接必须满足门禁。',
  `只调用最终提交工具，family_asin=${familyAsin}。`,
] as const;

async function main() {
  const agentDir = getAgentDir();
  const settingsManager = SettingsManager.create(COMPETITOR_PROJECT_ROOT, agentDir);
  const loader = new DefaultResourceLoader({
    cwd: COMPETITOR_PROJECT_ROOT, agentDir, settingsManager,
    noExtensions: true, noPromptTemplates: true, noThemes: true, noContextFiles: true,
    systemPromptOverride: () => SYSTEM_PROMPT, appendSystemPromptOverride: () => [],
  });
  await loader.reload();
  const { session } = await createAgentSession({
    cwd: COMPETITOR_PROJECT_ROOT, agentDir,
    modelRuntime: await ModelRuntime.create(), thinkingLevel: 'low',
    tools: [...COMPETITOR_TOOL_NAMES], customTools: tools,
    resourceLoader: loader, sessionManager: SessionManager.inMemory(COMPETITOR_PROJECT_ROOT), settingsManager,
  });
  if (session.model) modelVersion = `${session.model.provider}/${session.model.id}`;
  const unsubscribe = session.subscribe((event) => {
    if (event.type === 'message_update' && event.assistantMessageEvent.type === 'text_delta') {
      process.stderr.write(event.assistantMessageEvent.delta);
    }
  });
  try {
    process.stderr.write(`Pi 竞品 Agent 开始运行 ${familyAsin}（${modelVersion}）\n`);
    for (let index = 0; index < COMPETITOR_TOOL_NAMES.length; index += 1) {
      session.setActiveToolsByName([COMPETITOR_TOOL_NAMES[index]!]);
      await session.prompt(PROMPTS[index]!);
      if (index === 0 && !workflow) throw new Error('Pi 未读取竞品上下文');
      if (index === 8 && !persisted) throw new Error('Pi 未完成竞品契约提交');
    }
    process.stdout.write(`${JSON.stringify(persisted, null, 2)}\n`);
  } finally {
    unsubscribe(); session.dispose();
  }
}

main().catch((error) => {
  process.stderr.write(`${error instanceof Error ? error.stack ?? error.message : String(error)}\n`);
  process.exitCode = 1;
});
