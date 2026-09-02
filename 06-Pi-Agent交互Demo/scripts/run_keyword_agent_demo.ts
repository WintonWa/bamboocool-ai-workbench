import {
  createAgentSession, DefaultResourceLoader, defineTool, getAgentDir,
  ModelRuntime, SessionManager, SettingsManager,
} from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import {
  KEYWORD_PROJECT_ROOT, KeywordRunController, loadKeywordAgentFacts,
  type CoverageDecision, type DailyDecision, type EvidenceDecision,
  type JsonObject, type MarketDecision,
} from "../src/keyword-agent.ts";

function arg(name: string, fallback: string): string {
  const index = process.argv.indexOf(name);
  return index >= 0 ? process.argv[index + 1] ?? fallback : fallback;
}

const scope = arg("--scope", "all");
const resumePath = arg("--resume-db", "");
const resumeEvidenceOffset = Number(arg("--resume-evidence-offset", "0"));
const resumeFromRunId = arg("--resume-from-run", "");
const turnTimeoutMs = Number(arg("--turn-timeout-ms", "180000"));
const requestedProvider = arg("--model-provider", "");
const requestedModelId = arg("--model-id", "");
let modelVersion = "pi-local-default";
let controller: KeywordRunController | undefined;
let persisted: ReturnType<KeywordRunController["commit"]> | undefined;

type SignalTarget = {
  once: (signal: "SIGINT" | "SIGTERM", listener: () => void) => unknown;
  removeListener: (signal: "SIGINT" | "SIGTERM", listener: () => void) => unknown;
};

export function installKeywordSignalHandlers(
  getController: () => KeywordRunController | undefined,
  terminate: (code: number) => void = (code) => process.exit(code),
  target: SignalTarget = process,
): () => void {
  let handled = false;
  const handlers = { SIGINT: () => handle("SIGINT", 130), SIGTERM: () => handle("SIGTERM", 143) } as const;
  function cleanup() {
    target.removeListener("SIGINT", handlers.SIGINT);
    target.removeListener("SIGTERM", handlers.SIGTERM);
  }
  function handle(signal: "SIGINT" | "SIGTERM", code: number) {
    if (handled) return;
    handled = true;
    const run = getController();
    try {
      if (run && run.stage !== "completed" && run.stage !== "failed") run.fail(`收到 ${signal}，已终止当前关键词运行`);
    } finally { cleanup(); terminate(code); }
  }
  target.once("SIGINT", handlers.SIGINT); target.once("SIGTERM", handlers.SIGTERM);
  return cleanup;
}

function success(details: JsonObject) {
  return { content: [{ type: "text" as const, text: JSON.stringify(details) }], details };
}
function failure(error: unknown) {
  const message = error instanceof Error ? error.message : String(error);
  const details = { ok: false, error: message };
  return { isError: true, content: [{ type: "text" as const, text: JSON.stringify(details) }], details };
}
function current(): KeywordRunController {
  if (!controller) throw new Error("请先读取关键词运行上下文");
  return controller;
}

const nullable = <T>(schema: T) => Type.Union([Type.Null(), schema as any]);
const marketSchema = Type.Object({
  candidate_id: Type.String(),
  event_type: nullable(Type.Union([
    Type.Literal("demand_up"), Type.Literal("demand_down"), Type.Literal("competition_up"),
    Type.Literal("insufficient_history"), Type.Literal("not_comparable"),
  ])),
  continuity: nullable(Type.Union([
    Type.Literal("continuous"), Type.Literal("single_period"), Type.Literal("insufficient"),
  ])),
  label: nullable(Type.String()),
});
const coverageSchema = Type.Object({
  candidate_id: Type.String(),
  event_type: nullable(Type.Union([
    Type.Literal("organic_gained"), Type.Literal("organic_lost"), Type.Literal("organic_up"),
    Type.Literal("organic_down"), Type.Literal("ad_gained"), Type.Literal("ad_lost"),
    Type.Literal("beyond_depth"),
  ])),
  continuity: nullable(Type.Union([Type.Literal("continuous"), Type.Literal("single_period")])),
  label: nullable(Type.String()),
});
const evidenceSchema = Type.Object({
  candidate_id: Type.String(),
  evidence_type: nullable(Type.Union([
    Type.Literal("coverage_gap"), Type.Literal("scene_longtail_signal"),
    Type.Literal("insufficient_data"), Type.Literal("core_position_risk"),
    Type.Literal("inventory_limited"), Type.Literal("market_opportunity"),
    Type.Literal("pending_competitor_verification"),
  ])),
  priority: nullable(Type.Integer({ minimum: 1 })),
  conclusion: nullable(Type.String()), main_basis: nullable(Type.String()),
  evidence_completeness: nullable(Type.Union([
    Type.Literal("full"), Type.Literal("partial"), Type.Literal("insufficient"),
  ])),
  next_verification: nullable(Type.Union([
    Type.Literal("advertising"), Type.Literal("competitor"), Type.Literal("observe"),
  ])),
  competitor_verification_state: nullable(Type.Union([Type.Literal("na"), Type.Literal("pending")])),
  ref_market_event_ids: Type.Array(Type.String()),
  ref_coverage_event_ids: Type.Array(Type.String()),
});
const dailySchema = Type.Object({
  candidate_id: Type.String(), q1_traffic_result: Type.String(),
  q2_main_movers: Type.String(), q3_core_coverage_change: Type.String(),
  q4_new_signals: Type.String(), q5_priority_next: Type.String(),
  priority_evidence_ids: Type.Array(Type.String()),
});

const tools = [
  defineTool({
    name: "get_keyword_run_context", label: "冻结关键词运行上下文",
    description: "冻结允许输入、参数和 context hash；旧五张判断表未读取。",
    executionMode: "sequential", parameters: Type.Object({ scope: Type.Literal("all") }),
    execute: async (_id, params) => {
      try {
        const facts = loadKeywordAgentFacts(params.scope);
        controller = new KeywordRunController(facts, {
          modelVersion, batchSize: 50, evidenceBatchSize: 20,
          ...(resumePath ? {
            resumePath, resumeEvidenceOffset,
            resumeFromRunId: resumeFromRunId || undefined,
          } : {}),
        });
        if (controller.stage === "context") controller.acceptContext(facts.context_hash);
        process.stderr.write(`[1/7] context ${facts.context_hash.slice(0, 12)}；市场候选 ${facts.counts.market_candidates}\n`);
        return success({ ok: true, run_id: controller.runId, context_hash: facts.context_hash,
          counts: facts.counts, null_policy: "没有足够信号时 event_type=null，其余判断字段也为 null",
          resumed: Boolean(resumePath), stage: controller.stage,
          candidates: controller.stage === "market" ? controller.nextMarketBatch()
            : controller.stage === "evidence" ? controller.nextEvidenceBatch() : [] });
      } catch (error) { return failure(error); }
    },
  }),
  defineTool({
    name: "submit_market_event_batch", label: "判断市场变化事件",
    description: "只根据同来源、同频率原始快照判断 C；允许无事件。",
    executionMode: "sequential", parameters: Type.Object({ decisions: Type.Array(marketSchema) }),
    execute: async (_id, params) => {
      try {
        const run = current(); run.submitMarket(params.decisions as MarketDecision[]);
        return success({ ok: true, accepted: params.decisions.length, stage: run.stage,
          candidates: run.stage === "market" ? run.nextMarketBatch() : run.nextCoverageBatch() });
      } catch (error) { return failure(error); }
    },
  }),
  defineTool({
    name: "submit_coverage_event_batch", label: "判断覆盖变化事件",
    description: "按自然位/广告位通道判断 D；阈值不足或没有事件可返回 null。",
    executionMode: "sequential", parameters: Type.Object({ decisions: Type.Array(coverageSchema) }),
    execute: async (_id, params) => {
      try {
        const run = current(); run.submitCoverage(params.decisions as CoverageDecision[]);
        return success({ ok: true, accepted: params.decisions.length, stage: run.stage,
          candidates: run.stage === "coverage" ? run.nextCoverageBatch() : run.nextEvidenceBatch() });
      } catch (error) { return failure(error); }
    },
  }),
  defineTool({
    name: "submit_keyword_evidence_batch", label: "判断关键词证据",
    description: "按关键词×子 ASIN 判断 A；角色、目标与库存承接均为输入，不重判。",
    executionMode: "sequential", parameters: Type.Object({
      decisions: Type.Array(evidenceSchema),
      no_signal_candidate_ids: Type.Array(Type.String()),
    }),
    execute: async (_id, params) => {
      try {
        const run = current();
        const candidates = run.nextEvidenceBatch();
        const expected = new Set(candidates.map((item) => item.candidate_id));
        const decided = new Set(params.decisions.map((item) => item.candidate_id));
        const noSignal = new Set(params.no_signal_candidate_ids);
        if (params.decisions.some((item) => item.evidence_type === null)) {
          throw new Error("decisions 只放实际证据；无信号对象放 no_signal_candidate_ids");
        }
        if (decided.size !== params.decisions.length || noSignal.size !== params.no_signal_candidate_ids.length) {
          throw new Error("证据批次 ID 重复");
        }
        for (const id of decided) if (noSignal.has(id)) throw new Error(`证据与无信号列表重复：${id}`);
        const covered = new Set([...decided, ...noSignal]);
        if (covered.size !== expected.size || [...expected].some((id) => !covered.has(id))) {
          throw new Error("实际证据与无信号列表必须合计覆盖本批全部 candidate_id");
        }
        const expanded = [
          ...(params.decisions as EvidenceDecision[]),
          ...params.no_signal_candidate_ids.map((candidate_id) => ({
            candidate_id, evidence_type: null, priority: null, conclusion: null,
            main_basis: null, evidence_completeness: null, next_verification: null,
            competitor_verification_state: null, ref_market_event_ids: [],
            ref_coverage_event_ids: [],
          } satisfies EvidenceDecision)),
        ];
        run.submitEvidence(expanded);
        return success({ ok: true, accepted: candidates.length,
          actual_evidence: params.decisions.length,
          no_signal: params.no_signal_candidate_ids.length, stage: run.stage,
          ...(run.stage === "evidence" ? { candidates: run.nextEvidenceBatch() }
            : { candidates: run.dailyContexts() }) });
      } catch (error) { return failure(error); }
    },
  }),
  defineTool({
    name: "submit_keyword_daily_reports", label: "生成关键词动态日报",
    description: "为最近 14 日逐日提交 B 的五个答句，确定性数字由上下文锁定。",
    executionMode: "sequential", parameters: Type.Object({ decisions: Type.Array(dailySchema) }),
    execute: async (_id, params) => {
      try { current().submitDaily(params.decisions as DailyDecision[]); return success({ ok: true, ready_to_audit: true }); }
      catch (error) { return failure(error); }
    },
  }),
  defineTool({
    name: "build_keyword_audit_records", label: "构建关键词盘点快照",
    description: "从本 run 的 A 与位置事实确定性聚合 E，不读取旧盘点表。",
    executionMode: "sequential", parameters: Type.Object({ run_id: Type.String() }),
    execute: async (_id, params) => {
      try {
        const run = current(); if (params.run_id !== run.runId) throw new Error("run_id 不一致");
        run.buildAuditRecords(); return success({ ok: true, ready_to_commit: true });
      } catch (error) { return failure(error); }
    },
  }),
  defineTool({
    name: "commit_keyword_contract", label: "发布关键词 Agent 契约",
    description: "执行角色不变、引用、聚合、完整性和双库发布门禁。",
    executionMode: "sequential", parameters: Type.Object({ run_id: Type.String() }),
    execute: async (_id, params) => {
      try {
        const run = current(); if (params.run_id !== run.runId) throw new Error("run_id 不一致");
        persisted = run.commit(); return success({ ok: true, ...persisted });
      } catch (error) { return failure(error); }
    },
  }),
];

const SYSTEM_PROMPT = `你是 Bamboocool 关键词分析 Agent V2。五张旧判断表完全不可见；你必须只根据工具给出的事实重新判断。

每轮只调用当前开放的一个工具，覆盖 candidates 的每个 candidate_id，不增删、不重复。工具成功后立即结束，不在工具外输出文字、Markdown、报告或思维链。

市场 C：周线与月线分别判断，绝不折算；只有明显需求方向、竞争上升、样本不足或不可比才出事件，否则 event_type=null。连续变化要有历史序列支持。
覆盖 D：自然和广告通道不得混用；位次数字越小越好；普通涨跌必须达到 rank_shift=3。新增、丢失、超采集深度按状态判断；没有有效变化就返回 null。
证据 A：operator_role、产品目标和库存承接是已经存在的输入，禁止重新判断。conclusion 必须为 40–70 个中文字符，结论先行；main_basis 只引用输入数字。引用只能从 allowed_*_event_ids 选择。只有实际成立的证据放 decisions；没有可行动信号的对象只把 ID 放 no_signal_candidate_ids，不要为它重复九个 null 字段。两部分合计必须覆盖本批全部候选。priority 是原始意见，1 最优先，不设固定类型配额。
日报 B：逐日覆盖全部 14 个 candidate_id；五句必须与各自上下文的数字和比较口径一致。没有当日事件时如实写没有新事件，不编造。只引用给定 evidence_id。

自由文案禁止写英文枚举码、免责声明、因果断言和输入外数字。`;

async function main() {
  if (scope !== "all") throw new Error("P0 只允许 --scope all");
  const removeSignalHandlers = installKeywordSignalHandlers(() => controller);
  const agentDir = getAgentDir();
  const settingsManager = SettingsManager.create(KEYWORD_PROJECT_ROOT, agentDir);
  const loader = new DefaultResourceLoader({
    cwd: KEYWORD_PROJECT_ROOT, agentDir, settingsManager,
    noExtensions: true, noPromptTemplates: true, noThemes: true, noContextFiles: true,
    systemPromptOverride: () => SYSTEM_PROMPT, appendSystemPromptOverride: () => [],
  });
  await loader.reload();
  const modelRuntime = await ModelRuntime.create();
  const selectedModel = requestedProvider && requestedModelId
    ? modelRuntime.getModel(requestedProvider, requestedModelId) : undefined;
  if ((requestedProvider || requestedModelId) && !selectedModel) {
    throw new Error(`Pi 找不到指定模型 ${requestedProvider}/${requestedModelId}`);
  }
  async function runTurn(tool: string, prompt: string) {
    // 每批使用独立短会话。业务顺序与 Controller 状态保持连续，但模型
    // 上下文只携带当前候选，避免数十轮工具载荷累积后拖慢或溢出。
    for (let attempt = 1; attempt <= 3; attempt += 1) {
      const before = controller?.progressToken() ?? "none";
      const { session } = await createAgentSession({
        cwd: KEYWORD_PROJECT_ROOT, agentDir, modelRuntime,
        ...(selectedModel ? { model: selectedModel } : {}),
        thinkingLevel: "medium", tools: tools.map((item) => item.name), customTools: tools,
        resourceLoader: loader, sessionManager: SessionManager.inMemory(KEYWORD_PROJECT_ROOT), settingsManager,
      });
      if (session.model) modelVersion = `${session.model.provider}/${session.model.id}`;
      const unsubscribe = session.subscribe((event: any) => {
        if (event.type === "message_update" && event.assistantMessageEvent.type === "text_delta") process.stderr.write(event.assistantMessageEvent.delta);
        if (event.type === "message_end" && event.message?.role === "assistant") {
          const kinds = Array.isArray(event.message.content)
            ? event.message.content.map((item: any) => item.type).join(",") : "none";
          if (event.message.errorMessage || !kinds.includes("toolCall")) {
            process.stderr.write(`\n[Pi assistant end] stop=${event.message.stopReason ?? "unknown"} content=${kinds} error=${event.message.errorMessage ?? "none"}\n`);
          }
        }
        if (event.type === "tool_execution_end" && event.isError) {
          process.stderr.write(`\n[Pi tool error] ${event.toolName}\n`);
        }
      });
      let timer: NodeJS.Timeout | undefined;
      try {
        session.setActiveToolsByName([tool]);
        await Promise.race([
          session.prompt(prompt),
          new Promise<never>((_, reject) => {
            timer = setTimeout(() => reject(new Error(`Pi 单批超时 ${turnTimeoutMs}ms`)), turnTimeoutMs);
          }),
        ]);
        const after = controller?.progressToken() ?? "none";
        if (after === before) throw new Error(`Pi 本轮未推进工具状态：${tool}`);
        return;
      } catch (error) {
        const progressed = (controller?.progressToken() ?? "none") !== before;
        if (progressed) return;
        if (attempt === 3) throw error;
        process.stderr.write(`\n${error instanceof Error ? error.message : String(error)}；重试当前批 ${attempt + 1}/3\n`);
      } finally {
        if (timer) clearTimeout(timer);
        unsubscribe(); session.dispose();
      }
    }
  }
  const withCandidates = (instruction: string, candidates: JsonObject[]) =>
    `${instruction}\n以下是本批唯一 candidates：\n${JSON.stringify(candidates)}`;
  try {
    // 上下文冻结是框架确定性步骤，不要求模型复述。先探测本机 Pi 模型，
    // 再直接创建 run；C/D/A/B 的业务判断仍全部由后续模型工具提交。
    const probe = await createAgentSession({
      cwd: KEYWORD_PROJECT_ROOT, agentDir, modelRuntime,
      ...(selectedModel ? { model: selectedModel } : {}),
      thinkingLevel: "medium", tools: tools.map((item) => item.name), customTools: tools,
      resourceLoader: loader, sessionManager: SessionManager.inMemory(KEYWORD_PROJECT_ROOT), settingsManager,
    });
    if (probe.session.model) modelVersion = `${probe.session.model.provider}/${probe.session.model.id}`;
    probe.session.dispose();
    const facts = loadKeywordAgentFacts(scope);
    controller = new KeywordRunController(facts, {
      modelVersion, batchSize: 50, evidenceBatchSize: 20,
      ...(resumePath ? {
        resumePath, resumeEvidenceOffset,
        resumeFromRunId: resumeFromRunId || undefined,
      } : {}),
    });
    if (controller.stage === "context") controller.acceptContext(facts.context_hash);
    process.stderr.write(`[1/7] context ${facts.context_hash.slice(0, 12)}；stage=${controller.stage}\n`);
    process.stderr.write(`Pi 关键词 Agent V2 开始运行 scope=${scope}（${modelVersion}）\n`);
    while (controller.stage === "market") await runTurn("submit_market_event_batch",
      withCandidates("只提交本批市场 candidates 的判断；无事件用 null。", controller.nextMarketBatch()));
    process.stderr.write(`[2/7] 市场变化 C 完成，产出 ${controller.marketEventRows.length} 条\n`);
    while (controller.stage === "coverage") await runTurn("submit_coverage_event_batch",
      withCandidates("只提交本批覆盖 candidates 的判断；无有效变化用 null。", controller.nextCoverageBatch()));
    process.stderr.write(`[3/7] 覆盖变化 D 完成，产出 ${controller.coverageEventRows.length} 条\n`);
    while (controller.stage === "evidence") await runTurn("submit_keyword_evidence_batch",
      withCandidates("提交本批证据：成立的放 decisions，无信号的只放 no_signal_candidate_ids。", controller.nextEvidenceBatch()));
    process.stderr.write(`[4/7] 证据 A 完成，产出 ${controller.evidenceRows.length} 条\n`);
    await runTurn("submit_keyword_daily_reports",
      withCandidates("逐日提交本批 14 个日报 candidates 的五答与引用。", controller.dailyContexts()));
    process.stderr.write("[5/7] 动态日报 B 完成\n");
    await runTurn("build_keyword_audit_records", `只调用盘点聚合工具，run_id=${controller.runId}。`);
    process.stderr.write("[6/7] 盘点 E 完成\n");
    await runTurn("commit_keyword_contract", `只调用发布工具，run_id=${controller.runId}。`);
    if (!persisted) throw new Error("关键词契约未发布");
    process.stderr.write("[7/7] 双库发布完成\n");
    process.stdout.write(`${JSON.stringify(persisted, null, 2)}\n`);
  } catch (error) {
    if (controller && controller.stage !== "completed" && controller.stage !== "failed") controller.fail(error);
    throw error;
  } finally { removeSignalHandlers(); }
}

const invokedPath = process.argv[1] ? pathToFileURL(resolve(process.argv[1])).href : "";
if (import.meta.url === invokedPath) {
  main().catch((error) => {
    process.stderr.write(`${error instanceof Error ? error.stack ?? error.message : String(error)}\n`);
    process.exitCode = 1;
  });
}
