import {
  createAgentSession, DefaultResourceLoader, defineTool, getAgentDir,
  ModelRuntime, SessionManager, SettingsManager,
} from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import {
  ADS_CHILD_DECISION_POINTS, ADS_PROJECT_ROOT, appendAdsOutputPoint,
  beginAdsChildDecisionRun, completeAdsChildDecisionRun, failAdsChildDecisionRun,
  fetchWorkbenchAdsContext, loadAdsAgentFacts, validateAdsOutputPoint,
  type AdsAgentFacts, type AdsChildDecisionPoint, type JsonObject,
} from "../src/ads-agent.ts";

const childAsin = (process.argv[2] ?? "B0B3LWGP36").trim().toUpperCase();
let facts: AdsAgentFacts | undefined;
let runId: string | undefined;
let modelVersion = "pi-local-default";
let completed: ReturnType<typeof completeAdsChildDecisionRun> | undefined;
const accepted: Partial<Record<AdsChildDecisionPoint, JsonObject[]>> = {};

function success(details: JsonObject) {
  return { content: [{ type: "text" as const, text: JSON.stringify(details) }], details };
}
function failure(errors: string[]) {
  const details = { ok: false, errors };
  return { isError: true, content: [{ type: "text" as const, text: JSON.stringify(details) }], details };
}
function currentFacts(): AdsAgentFacts {
  if (!facts) throw new Error("请先读取广告判断事实");
  return facts;
}

const nullableString = Type.Union([Type.String(), Type.Null()]);
const stringArray = Type.Array(Type.String());
const evidenceIds = Type.Array(Type.String(), { minItems: 1 });
const judgmentMode = Type.Union([Type.Literal("formal"), Type.Literal("conditional"), Type.Literal("unable")]);

const constraintSchema = Type.Object({
  constraint_id: Type.String({ pattern: "^con_[A-Za-z0-9]+_[0-9]{2}$" }), goal_version: Type.String(),
  kind: Type.Union([Type.Literal("hard"), Type.Literal("observe")]),
  domain: Type.Union([Type.Literal("inventory"), Type.Literal("cost"), Type.Literal("traffic"), Type.Literal("event")]),
  label: Type.String({ minLength: 2, maxLength: 40 }), detail: Type.String({ minLength: 4, maxLength: 180 }),
  is_satisfied: Type.Union([Type.Literal(0), Type.Literal(1), Type.Null()]), evidence_ref: Type.String(),
}, { additionalProperties: false });

const b0cdSchema = Type.Union([
  Type.Object({
    item_kind: Type.Literal("keyword_match"), match_id: Type.String(), kw_id: Type.String(),
    match_level: Type.Union([Type.Literal("high"), Type.Literal("medium"), Type.Literal("low")]),
    demand_side: Type.String(), product_side: Type.String(), basis: Type.String(), evidence_ids: evidenceIds,
  }, { additionalProperties: false }),
  Type.Object({
    item_kind: Type.Literal("competitor_pressure"), pressure_id: Type.String(), competitor_asin: Type.String(), brand: Type.String(),
    pressure_type: Type.Union([Type.Literal("price"), Type.Literal("promotion"), Type.Literal("rank"), Type.Literal("sales"), Type.Literal("traffic"), Type.Literal("keyword_entry")]),
    detail: Type.String(), is_verified: Type.Union([Type.Literal(0), Type.Literal(1)]), observed_at: Type.String(), evidence_ids: evidenceIds,
  }, { additionalProperties: false }),
]);

const schemas: Record<AdsChildDecisionPoint, any> = {
  B0b: constraintSchema,
  B0cd: b0cdSchema,
  B0e: Type.Object({
    issue_id: Type.String(), issue_type: Type.Union([Type.Literal("shared"), Type.Literal("unexplained")]),
    ad_object_id: nullableString, label: Type.String(), detail: Type.String(), evidence_ids: evidenceIds,
  }, { additionalProperties: false }),
  B1: Type.Object({
    task_id: Type.String(), decision_id: Type.String(), goal_version: Type.String(),
    task_type: Type.Union([
      Type.Literal("VERIFY_INBOUND_BEFORE_SCALE"), Type.Literal("PROTECT_CORE_QUERY_VISIBILITY"), Type.Literal("CONTROL_EFFICIENCY_DRIFT"),
      Type.Literal("CLARIFY_ATTRIBUTION_BOUNDARY"), Type.Literal("ACCELERATE_SELL_THROUGH"), Type.Literal("CLEAR_AGED_INVENTORY"),
      Type.Literal("COVER_MATCHED_QUERY_GAP"),
    ]),
    task_direction: Type.Union([Type.Literal("ADJUST"), Type.Literal("BUILD"), Type.Literal("OBSERVE"), Type.Literal("PREREQUISITE"), Type.Literal("REQUEST_INFO")]),
    priority: Type.Union([Type.Literal("P0"), Type.Literal("P1"), Type.Literal("P2"), Type.Literal("P3")]),
    target_scope: Type.String(), constraints: stringArray, evaluation_direction: Type.String(), stop_condition: Type.String(),
    applies_from: Type.String(), applies_to: nullableString,
    rule_status: Type.Union([Type.Literal("confirmed"), Type.Literal("unconfirmed")]),
    exact_budget: Type.Union([Type.Number(), Type.Null()]), exact_bid: Type.Union([Type.Number(), Type.Null()]),
    exact_placement_adjustment: Type.Union([Type.Number(), Type.Null()]), exact_values_withheld: Type.Boolean(),
    evidence_ids: evidenceIds, inventory_constrained: Type.Union([Type.Literal(0), Type.Literal(1)]), judgment_mode: judgmentMode,
  }, { additionalProperties: false }),
  B2: Type.Object({
    mapping_id: Type.String(), task_id: Type.String(), ad_object_id: nullableString,
    coverage_status: Type.Union([Type.Literal("covered"), Type.Literal("mixed"), Type.Literal("missing"), Type.Literal("duplicate")]),
    attribution_limit: Type.Union([Type.Literal("exclusive"), Type.Literal("shared"), Type.Literal("unattributed")]),
    target_fit: Type.String(), result_supports_purpose: Type.String(),
    gap_source: Type.Union([Type.Literal("structure"), Type.Literal("evidence"), Type.Literal("none")]),
    basis_level: Type.Union([Type.Literal("self_history"), Type.Literal("conditional")]),
    is_automatic_error: Type.Union([Type.Literal(0), Type.Literal(1)]), note: Type.String(), evidence_ids: evidenceIds, judgment_mode: judgmentMode,
  }, { additionalProperties: false }),
  B3: Type.Object({
    diagnosis_id: Type.String(), task_id: nullableString,
    problem_type: Type.Union([Type.Literal("REQUIRED_TASK_MISSING"), Type.Literal("MIXED_PURPOSE_GROUP"), Type.Literal("GOAL_PURPOSE_MISMATCH"), Type.Literal("ATTRIBUTION_UNCLEAR"), Type.Literal("KEYWORD_COVERAGE_GAP"), Type.Literal("INVENTORY_COVERAGE_RISK")]),
    what_happened: Type.String(), impacted_goal: Type.String(), priority: Type.Union([Type.Literal("P0"), Type.Literal("P1"), Type.Literal("P2")]),
    confidence: Type.Union([Type.Literal("high"), Type.Literal("medium"), Type.Literal("low")]),
    basis_type: Type.Union([Type.Literal("confirmed_rule"), Type.Literal("self_history"), Type.Literal("peer"), Type.Literal("conditional")]),
    uncertainty: Type.String(), missing_input: Type.String(), check_direction: Type.String(), causal_claim: Type.Literal(0),
    evidence_ids: evidenceIds, judgment_mode: judgmentMode,
  }, { additionalProperties: false }),
  B3b: Type.Object({
    problem_type: Type.Union([Type.Literal("GOAL_PURPOSE_MISMATCH"), Type.Literal("MIXED_PURPOSE_GROUP"), Type.Literal("ATTRIBUTION_UNCLEAR"), Type.Literal("KEYWORD_COVERAGE_GAP"), Type.Literal("INVENTORY_COVERAGE_RISK"), Type.Literal("REQUIRED_TASK_MISSING"), Type.Literal("DUPLICATE_TASK_OWNERS"), Type.Literal("PERFORMANCE_NOT_SUPPORTING"), Type.Literal("COMPETITOR_NO_TASK"), Type.Literal("INSUFFICIENT_EVIDENCE")]),
    hit: Type.Union([Type.Literal(0), Type.Literal(1)]), why_not: Type.String(),
  }, { additionalProperties: false }),
  B4: Type.Object({
    recommendation_id: Type.String(), diagnosis_id: Type.String(), product_goal_version: Type.String(),
    ad_purpose: nullableString, ad_object_id: nullableString, structure_gap_id: nullableString,
    direction: Type.Union([Type.Literal("KEEP"), Type.Literal("OBSERVE"), Type.Literal("ADJUST"), Type.Literal("PAUSE"), Type.Literal("RESUME"), Type.Literal("SPLIT"), Type.Literal("MERGE"), Type.Literal("BUILD"), Type.Literal("TEST"), Type.Literal("DEFER"), Type.Literal("REQUEST_INFO"), Type.Literal("PREREQUISITE")]),
    rationale: Type.String(), preconditions: stringArray, risks: stringArray, uncertainty: Type.String(), observation_metrics: stringArray,
    review_windows: stringArray, d7_not_required: Type.Union([Type.Literal(0), Type.Literal(1)]),
    rule_status: Type.Union([Type.Literal("confirmed"), Type.Literal("unconfirmed")]), exact_value: nullableString,
    exact_values_withheld: Type.Boolean(), evidence_ids: evidenceIds, judgment_mode: judgmentMode,
  }, { additionalProperties: false }),
};

const pointDescriptions: Record<AdsChildDecisionPoint, string> = {
  B0b: "目标约束分档。规则未确认时成本/流量只能 observe；库存上游缺失时不许编未来投影。domain 与证据类型必须对应：inventory=库存、cost=广告表现/控制、traffic=广告表现/销量/关键词、event=业务事件；产品目标不是 event。",
  B0cd: "同时输出关键词匹配与竞品压力两类行；item_kind 决定字段。压力只是背景，不能写成广告效率的因果。detail 中每个数字必须存在于 evidence_ids 所引证据；若拿竞品30天销量与本品28天销量对比，必须同时引用竞品证据和本品销量证据。",
  B0e: "从广告对象与产品关系判断共享或无法归因的结构问题。",
  B1: "从运营目标推出应有任务，不从现有广告结构反推。规则未确认时三个精确值必须 null。",
  B2: "逐项把 B1 任务与现有结构对照；没有承接对象时 ad_object_id=null、coverage_status=missing。",
  B3: "基于前序任务与映射形成诊断。causal_claim 必须为 0；impacted_goal 必须原样使用运营目标名。REQUIRED_TASK_MISSING 只表示 B1 根本没建立所需任务，此时 task_id 必须 null；已有任务但缺上游输入不是任务缺失。上游库存 Agent 缺失且 stockout_flag=0 时，不得把无法判断写成 INVENTORY_COVERAGE_RISK。",
  B3b: "十类问题必须各一行；未命中必须解释 why_not。前六类 hit 必须与 B3 实际 problem_type 完全一致。",
  B4: "仅针对 B3 诊断给建议；允许保持/观察。规则未确认时 exact_value=null。",
};

function makeSubmitTool(point: AdsChildDecisionPoint) {
  return defineTool({
    name: `submit_${point.toLowerCase()}_output`, label: `提交 ${point} 判断`,
    description: `${pointDescriptions[point]} 只校验契约、证据与跨阶段引用，不与预烤答案比较。`,
    executionMode: "sequential",
    parameters: Type.Object({
      child_asin: Type.String(),
      items: Type.Array(schemas[point], point === "B3b" ? { minItems: 10, maxItems: 10 } : { minItems: 1, maxItems: 20 }),
    }, { additionalProperties: false }),
    execute: async (_id: string, params: JsonObject) => {
      const current = currentFacts();
      if (String(params.child_asin).trim().toUpperCase() !== current.child_asin) return failure(["child_asin 与当前事实不一致"]);
      if (accepted[point]) return failure([`${point} 已提交，禁止覆盖`]);
      const items = params.items as JsonObject[];
      const errors = validateAdsOutputPoint(current, point, items, accepted);
      if (errors.length) return failure(errors);
      if (point === "B0b") {
        const started = beginAdsChildDecisionRun(current, modelVersion);
        runId = started.run.run_id;
      }
      if (!runId) return failure(["完整运行尚未建立"]);
      appendAdsOutputPoint(current, runId, point, items, accepted);
      accepted[point] = items;
      const index = ADS_CHILD_DECISION_POINTS.indexOf(point);
      const next = ADS_CHILD_DECISION_POINTS[index + 1] ?? "commit";
      process.stderr.write(`[${index + 2}/10] ${point} 已通过门禁并落表，共 ${items.length} 条；下一步 ${next}\n`);
      return success({ ok: true, run_id: runId, accepted_output_point: point, accepted_items: items, next_output_point: next });
    },
  });
}

const contextTool = defineTool({
  name: "get_ads_child_decision_context", label: "读取广告判断事实",
  description: "从工作台读取 freshness 元数据并绑定只含原始事实/可复核算术的证据目录，不返回 ext_* 预烤答案。",
  executionMode: "sequential",
  parameters: Type.Object({ child_asin: Type.String() }, { additionalProperties: false }),
  execute: async (_id, params) => {
    const workbenchContext = await fetchWorkbenchAdsContext(params.child_asin);
    facts = loadAdsAgentFacts(params.child_asin, workbenchContext);
    process.stderr.write(`[1/10] 已绑定 ${facts.child_asin} freshness ${facts.context_hash.slice(0, 12)}，读取 ${facts.evidence.length} 条干净证据\n`);
    return success({
      ok: true, child_asin: facts.child_asin, data_as_of: facts.data_as_of, context_id: facts.context_id,
      context_hash: facts.context_hash, mode: facts.mode, operator_goal: facts.operator_goal, identity: facts.identity,
      upstream_inventory_agent: facts.upstream_inventory_agent, input_limits: facts.input_limits,
      evidence: facts.evidence, evidence_types: [...new Set(facts.evidence.map((item) => item.evidence_type))], first_output_point: "B0b",
    });
  },
});

const commitTool = defineTool({
  name: "commit_ads_child_decision_run", label: "完成广告判断运行",
  description: "确认八个输出点都已逐步落表后，把 running 原子切换为 completed。", executionMode: "sequential",
  parameters: Type.Object({ child_asin: Type.String() }, { additionalProperties: false }),
  execute: async (_id, params) => {
    const current = currentFacts();
    if (params.child_asin.trim().toUpperCase() !== current.child_asin) return failure(["child_asin 与当前事实不一致"]);
    if (!runId) return failure(["尚无 running 运行"]);
    const missing = ADS_CHILD_DECISION_POINTS.filter((point) => !accepted[point]);
    if (missing.length) return failure([`仍缺少输出点：${missing.join(", ")}`]);
    completed = completeAdsChildDecisionRun(runId);
    process.stderr.write(`[10/10] 完整运行 ${runId} 已切换 completed\n`);
    return success({ ok: true, ...completed });
  },
});

const tools = [contextTool, ...ADS_CHILD_DECISION_POINTS.map(makeSubmitTool), commitTool];

const SYSTEM_PROMPT = `你是 Bamboocool 广告分析 Agent。你要按工具开放顺序，对一个子 ASIN 完成八个有契约的判断点。

总规则：
1. 只根据 get_ads_child_decision_context 返回的干净事实自主判断，禁止寻找、猜测或复述 ext_* 预烤答案。
2. 每个用户回合只调用当前开放的一个工具；工具成功后立即结束本轮。报错时按错误修正并重试同一工具。
3. 只输出工具 schema 中的字段，不增加 *_label、nature、mode、翻译字段，也不输出思考链。
4. evidence_ids/evidence_ref 必须来自工具返回的 evidence_id。7 天与 14 天归因保持隔离；Campaign 级事实每个 Campaign 只算一次。
5. 竞品只作为背景，两个指标同时变化不是因果；causal_claim 固定为 0。
6. 当前 rule_status 未确认时，exact_budget/exact_bid/exact_placement_adjustment/exact_value 必须 null，exact_values_withheld=true。
7. 上游库存 Agent 不可用时，不得编造断货日、安全线、最晚下单日或补货量。
8. judgment_mode 当前使用 conditional。允许输出 KEEP/OBSERVE，也允许指出没有问题；不要为了显得有用而强行制造问题。
9. id 必须稳定易读：con_<ASIN>_NN、match_<ASIN>_NN、pressure_<ASIN>_NN、issue_<ASIN>_NN、task_<ASIN>_NN、map_<ASIN>_NN、diag_<ASIN>_NN、rec_<ASIN>_NN。
10. B0cd 要覆盖上下文中的全部关键词位置证据，并对有可验证证据的竞品给压力判断；B3b 必须十类各一条。

不要描述你准备调用工具，直接调用当前工具。`;

const STEP_DEFS: Array<{ name: string; point?: AdsChildDecisionPoint }> = [
  { name: "get_ads_child_decision_context" },
  ...ADS_CHILD_DECISION_POINTS.map((point) => ({ name: `submit_${point.toLowerCase()}_output`, point })),
  { name: "commit_ads_child_decision_run" },
];

function promptForStep(step: { name: string; point?: AdsChildDecisionPoint }, retry: boolean): string {
  if (step.name === "get_ads_child_decision_context") return `唯一合法响应是调用 ${step.name}，child_asin=${childAsin}。不要输出解释或 JSON 文本。`;
  if (step.name === "commit_ads_child_decision_run") return `唯一合法响应是调用 ${step.name}，child_asin=${childAsin}。不要输出解释或 JSON 文本。`;
  const point = step.point!;
  const packet = {
    child_asin: facts?.child_asin,
    data_as_of: facts?.data_as_of,
    context_id: facts?.context_id,
    mode: facts?.mode,
    operator_goal: facts?.operator_goal,
    identity: facts?.identity,
    upstream_inventory_agent: facts?.upstream_inventory_agent,
    input_limits: facts?.input_limits,
    evidence: facts?.evidence,
    accepted_outputs: accepted,
  };
  return `${retry ? "上一次没有成功调用工具；这次" : "现在"}唯一合法响应是调用 ${step.name}。不要输出解释、Markdown 或 JSON 文本；必须把判断放进工具参数 items。\n输出点=${point}；child_asin=${childAsin}。${pointDescriptions[point]}\n本轮冻结输入：\n${JSON.stringify(packet)}`;
}

async function main() {
  const agentDir = getAgentDir();
  const settingsManager = SettingsManager.create(ADS_PROJECT_ROOT, agentDir);
  const loader = new DefaultResourceLoader({
    cwd: ADS_PROJECT_ROOT, agentDir, settingsManager, noExtensions: true, noPromptTemplates: true,
    noThemes: true, noContextFiles: true, systemPromptOverride: () => SYSTEM_PROMPT, appendSystemPromptOverride: () => [],
  });
  await loader.reload();
  const modelRuntime = await ModelRuntime.create();
  const modelSpec = process.env.BAMBOO_ADS_MODEL ?? "deepseek/deepseek-v4-flash";
  const separator = modelSpec.indexOf("/");
  if (separator < 1) throw new Error("BAMBOO_ADS_MODEL 必须是 provider/model-id");
  const providerId = modelSpec.slice(0, separator);
  const modelId = modelSpec.slice(separator + 1);
  const selectedModel = modelRuntime.getModel(providerId, modelId);
  if (!selectedModel) throw new Error(`Pi 中未找到已配置的 ${modelSpec}`);
  modelVersion = `${selectedModel.provider}/${selectedModel.id}`;
  // 思考档与单回合超时可用环境变量覆盖。
  // 默认从 high/90 秒改成 medium/240 秒：high + 90 秒实测跑不完——
  // 撞的是 B2（要产十几条，本来就是最费时的一步），而不是模型不可用
  // （同一个 deepseek-v4-flash 库存跑了 18 次、竞对 12 次都成功）。
  // medium 对齐关键词 Agent，超时留够余量；实测三次连跑八点齐全。
  const thinking = (process.env.BAMBOO_ADS_THINKING ?? "medium") as
    "off" | "low" | "medium" | "high";
  const turnTimeoutMs = Number(process.env.BAMBOO_ADS_TURN_TIMEOUT_MS ?? 240_000);
  async function runTurn(step: { name: string; point?: AdsChildDecisionPoint }, retry: boolean): Promise<void> {
    // 每个判断点使用独立短会话。业务状态和逐点落库由本进程保持，模型只看
    // 当前冻结事实与已接受输出，避免十轮工具载荷累积和某一轮挂住后污染后续。
    const { session } = await createAgentSession({
      cwd: ADS_PROJECT_ROOT, agentDir, modelRuntime, model: selectedModel, thinkingLevel: thinking,
      tools: tools.map((item) => item.name), customTools: tools, resourceLoader: loader,
      sessionManager: SessionManager.inMemory(ADS_PROJECT_ROOT), settingsManager,
    });
    if (session.model) modelVersion = `${session.model.provider}/${session.model.id}`;
    const unsubscribe = session.subscribe((event) => {
      if (event.type === "message_update" && event.assistantMessageEvent.type === "text_delta") process.stderr.write(event.assistantMessageEvent.delta);
      if (event.type === "agent_end" && !event.willRetry) {
        const last = event.messages.at(-1) as JsonObject | undefined;
        if (last?.role === "assistant" && last.stopReason && last.stopReason !== "stop" && last.stopReason !== "toolUse")
          process.stderr.write(`[Pi stopReason=${last.stopReason}${last.errorMessage ? `: ${last.errorMessage}` : ""}]\n`);
      }
    });
    try {
      session.setActiveToolsByName([step.name]);
      let timeout: ReturnType<typeof setTimeout> | undefined;
      try {
        await Promise.race([
          session.prompt(promptForStep(step, retry)),
          new Promise<never>((_resolve, reject) => {
            timeout = setTimeout(() => reject(new Error(
              `${step.name} 模型回合超过 ${Math.round(turnTimeoutMs / 1000)} 秒`)), turnTimeoutMs);
          }),
        ]);
      } catch (error) {
        if (session.isStreaming) await session.abort();
        throw error;
      } finally { if (timeout) clearTimeout(timeout); }
    } finally { unsubscribe(); session.dispose(); }
  }
  try {
    process.stderr.write(`Pi 广告 Agent 完整子 ASIN 判断 ${childAsin}（${modelVersion}）\n`);
    for (const step of STEP_DEFS) {
      const succeeded = () => step.name === "get_ads_child_decision_context" ? Boolean(facts)
        : step.name === "commit_ads_child_decision_run" ? Boolean(completed)
        : Boolean(accepted[step.point!]);
      for (let attempt = 0; attempt < 3 && !succeeded(); attempt += 1) await runTurn(step, attempt > 0);
      if (!succeeded()) throw new Error(`${step.point ?? step.name} 连续三次未完成工具调用`);
    }
    process.stdout.write(`${JSON.stringify({ completed, outputs: accepted }, null, 2)}\n`);
  } catch (error) {
    if (runId && !completed) failAdsChildDecisionRun(runId);
    throw error;
  }
}

main().catch((error) => {
  process.stderr.write(`${error instanceof Error ? error.stack ?? error.message : String(error)}\n`);
  process.exitCode = 1;
});
