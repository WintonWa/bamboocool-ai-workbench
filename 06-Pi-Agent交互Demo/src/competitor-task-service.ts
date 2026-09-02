import {
  DEFAULT_COMPETITOR_V2_DB,
  DEFAULT_COMPETITOR_V2_JSON,
  buildCompetitorTaskId,
  enqueueCompetitorExecution,
  failCompetitorExecution,
  getCompetitorTask,
  loadCompetitorFactsV2,
  markCompetitorExecutionRunning,
  readConfiguredPiModelVersion,
  recoverInterruptedCompetitorExecutions,
  shouldSkipCompetitorRun,
  skipCompetitorExecution,
  validateCompetitorRunRequest,
  writeCompetitorAgentRunV2,
  type CompetitorModelFacts,
  type CompetitorRunRequest,
  type CompetitorTaskPayload,
  type WorkflowSnapshot,
} from "./competitor-agent-v2.ts";

export type CompetitorRunner = (
  facts: CompetitorModelFacts,
  request: CompetitorRunRequest,
) => Promise<WorkflowSnapshot>;

export type CompetitorTaskServiceOptions = {
  runner?: CompetitorRunner;
  modelVersion?: string;
  dbPath?: string;
  exportPath?: string;
  now?: () => Date;
  maxConcurrency?: number;
};

function publicFailureReason(error: unknown, fallback: string): string {
  if (error && typeof error === "object" && "publicReason" in error) {
    const value = (error as { publicReason?: unknown }).publicReason;
    if (typeof value === "string" && value.trim()) return value;
  }
  return fallback;
}

function contractWriteFailure(error: unknown): Error & { publicReason: string } {
  const wrapped = new Error("竞品结果未通过写入前契约校验", { cause: error }) as Error & { publicReason: string };
  wrapped.publicReason = "失败步骤：写入前契约校验 · 结果未通过完整性门禁，请重新发起";
  return wrapped;
}

function fakeSnapshot(facts: CompetitorModelFacts): WorkflowSnapshot {
  const hasGap = facts.change_candidates.some((item) => item.evidence_gap);
  const previous = Boolean(facts.previous_run);
  if (hasGap) {
    return {
      evidence: {
        evidence_level: "insufficient",
        evidence_reason: "当前观察存在关键缺口，无法形成稳定判断",
        judgment_summary: "证据不足，本次不给关注结论",
      },
      changes: [],
      representation: [],
      impacts: [],
      concurrency: [],
      attention: { attention_level: "none", attention_summary: "证据不足，本次不给关注结论", reasons: [] },
      outputs: {
        open_items: [{ item_kind: "unconfirmed", statement: "等待缺失观察恢复后重新判断", needed_data: "补齐连续观察" }],
        diff: {
          transition: previous ? "sustained" : "new",
          statement: previous ? "证据状态与上一版保持一致" : "本次为首次形成可追溯判断",
          changed_domains: [],
        },
        report: null,
        handoffs: [],
      },
    };
  }
  const candidates = facts.change_candidates.slice(0, 2);
  const changes = candidates.map((candidate) => ({
    candidate_id: candidate.candidate_id,
    domain: candidate.allowed_domains[0],
    direction: candidate.allowed_directions[0],
    current_state: candidate.allowed_current_states[0],
    label: "当前变化已进入持续观察区间",
    basis: "连续观察和对象引用支持该定性判断",
    confidence: "high" as const,
  }));
  const priceChange = changes.find((item) => item.domain === "price_promo");
  const trafficChange = changes.find((item) => item.domain === "traffic");
  const sharedKeyword = facts.shared_keyword_candidates[0]?.keyword ?? null;
  const eligibleRelations = facts.relation_candidates.filter((item) =>
    item.confirm_status === "confirmed" && item.gap_shift_applicable === true && item.gap_shift_eligible === true);
  const impacts = priceChange ? eligibleRelations.map((relation) => ({
    candidate_id: priceChange.candidate_id,
    relation_id: relation.rel_id,
    shared_keyword: sharedKeyword,
    pressure_dimension: "price" as const,
    statement: "竞品件单价变化可能影响该自有产品的价格竞争位置",
    confidence: "high" as const,
  })) : [];
  const handoffs: WorkflowSnapshot["outputs"]["handoffs"] = [];
  if (impacts.length && sharedKeyword) handoffs.push({
    target_page: "keyword",
    candidate_id: impacts[0]!.candidate_id,
    relation_id: impacts[0]!.relation_id,
    shared_keyword: sharedKeyword,
    pressure_dimension: "keyword",
    observable_fact: "共同词与已确认竞争关系同时存在，可供关键词页继续核对",
  });
  if (trafficChange) handoffs.push({
    target_page: "advertising",
    candidate_id: trafficChange.candidate_id,
    relation_id: null,
    shared_keyword: null,
    pressure_dimension: "traffic",
    observable_fact: "广告流量占比持续变化，可供广告页继续核对流量结构",
  });
  return {
    evidence: {
      evidence_level: "sufficient",
      evidence_reason: "当前观察连续，对象引用和窗口边界可核对",
      judgment_summary: "当前变化可以进入竞争判断",
    },
    changes,
    representation: candidates.map((candidate) => ({
      candidate_id: candidate.candidate_id,
      represents_family: true,
      coverage_note: "结合主销对象与连续观察可以上卷整族",
    })),
    impacts,
    concurrency: candidates.length > 1 ? [{
      change_a_id: candidates[0]!.candidate_id,
      change_b_id: candidates[1]!.candidate_id,
      relation: "concurrent",
      statement: "两类变化在观察窗内同期变化，目前只判为可能相关",
      missing_evidence: "仍需后续窗口进一步核对",
    }] : [],
    attention: {
      attention_level: "high",
      attention_summary: "当前变化已影响竞争位置，需要持续跟踪",
      reasons: [
        { candidate_id: candidates[0]!.candidate_id, label: "变化具有持续性", weight_note: "持续性是主要依据" },
        { candidate_id: candidates[0]!.candidate_id, label: "变化进入竞争范围", weight_note: "竞争关系可以核对" },
      ],
    },
    outputs: {
      open_items: [{ item_kind: "watch", statement: "当前变化是否会在下一观察窗延续", needed_data: "下一周期的同口径连续观察" }],
      diff: {
        transition: previous ? "sustained" : "new",
        statement: previous ? "关注方向与上一版保持一致" : "本次为首次形成可追溯判断",
        changed_domains: [...new Set(changes.map((item) => item.domain))],
      },
      report: {
        headline: "当前竞争位置变化值得持续关注",
        body: "连续观察表明该变化已进入整族判断范围",
        impact_note: "后续需结合自有产品表现继续核对",
        unconfirmed_note: "变化是否会延续仍待下一观察窗确认",
      },
      handoffs,
    },
  } as WorkflowSnapshot;
}

async function defaultRunner(facts: CompetitorModelFacts, request: CompetitorRunRequest): Promise<WorkflowSnapshot> {
  if (process.env.BAMBOO_AGENT_FAKE === "1") return fakeSnapshot(facts);
  const module = await import("./competitor-pi-runner.ts");
  return module.runCompetitorPiAgent(facts, request);
}

export class CompetitorTaskService {
  readonly dbPath: string;
  readonly exportPath: string;
  readonly modelVersion: string;
  private readonly runner: CompetitorRunner;
  private readonly now: () => Date;
  private readonly maxConcurrency: number;
  private active = 0;
  private readonly permitWaiters: Array<() => void> = [];
  private readonly familyTails = new Map<string, Promise<void>>();
  private readonly scheduled = new Set<string>();
  private disposed = false;

  constructor(options: CompetitorTaskServiceOptions = {}) {
    this.dbPath = options.dbPath ?? process.env.BAMBOO_COMPETITOR_V2_DB ?? DEFAULT_COMPETITOR_V2_DB;
    this.exportPath = options.exportPath ?? process.env.BAMBOO_COMPETITOR_V2_JSON ?? DEFAULT_COMPETITOR_V2_JSON;
    this.modelVersion = options.modelVersion ?? readConfiguredPiModelVersion();
    this.runner = options.runner ?? defaultRunner;
    this.now = options.now ?? (() => new Date());
    this.maxConcurrency = Math.max(1, Math.floor(options.maxConcurrency ?? 3));
    recoverInterruptedCompetitorExecutions(this.dbPath, this.now());
  }

  async enqueue(input: unknown): Promise<CompetitorTaskPayload> {
    if (this.disposed) throw new Error("竞品任务服务已关闭");
    const request = validateCompetitorRunRequest(input);
    const envelope = loadCompetitorFactsV2(request, this.dbPath);
    const execution = enqueueCompetitorExecution(request, envelope.model, this.modelVersion, this.dbPath, this.now());
    if (execution.status === "queued") this.schedule(request);
    return getCompetitorTask(execution.task_id, this.dbPath)!;
  }

  async get(taskId: string): Promise<CompetitorTaskPayload | null> {
    return getCompetitorTask(taskId, this.dbPath);
  }

  private schedule(request: CompetitorRunRequest): void {
    const taskId = buildCompetitorTaskId(request.family_asin, request.request_key);
    if (this.scheduled.has(taskId)) return;
    this.scheduled.add(taskId);
    const prior = this.familyTails.get(request.family_asin) ?? Promise.resolve();
    const current = prior.catch(() => undefined).then(() => this.process(taskId, request));
    this.familyTails.set(request.family_asin, current);
    void current.finally(() => {
      this.scheduled.delete(taskId);
      if (this.familyTails.get(request.family_asin) === current) this.familyTails.delete(request.family_asin);
    });
  }

  private async process(taskId: string, request: CompetitorRunRequest): Promise<void> {
    await this.acquirePermit();
    try {
      await this.processWithPermit(taskId, request);
    } finally {
      this.releasePermit();
    }
  }

  private async processWithPermit(taskId: string, request: CompetitorRunRequest): Promise<void> {
    const current = await this.get(taskId);
    if (!current || current.state !== "queued") return;
    try {
      const skip = shouldSkipCompetitorRun(taskId, this.dbPath);
      if (skip.skip) {
        skipCompetitorExecution(taskId, skip.reason ?? "观察上下文与上一版相同，沿用已有分析", this.dbPath, this.now());
        return;
      }
      const envelope = loadCompetitorFactsV2(request, this.dbPath);
      markCompetitorExecutionRunning(taskId, this.dbPath, this.now());
      const snapshot = await this.runner(envelope.model, request);
      try {
        writeCompetitorAgentRunV2(
          taskId,
          envelope.model,
          envelope.private,
          snapshot,
          request,
          this.dbPath,
          this.exportPath,
          this.now(),
        );
      } catch (error) {
        throw contractWriteFailure(error);
      }
    } catch (error) {
      const latest = await this.get(taskId);
      if (latest && (latest.state === "queued" || latest.state === "running")) {
        const fallback = latest.state === "running" ? "竞品分析运行或提交失败，请重新发起" : "竞品分析入队失败，请重新发起";
        const category = publicFailureReason(error, fallback);
        try { failCompetitorExecution(taskId, category, this.dbPath, this.now()); } catch { /* already terminal */ }
      }
    }
  }

  private async acquirePermit(): Promise<void> {
    if (this.active < this.maxConcurrency) {
      this.active += 1;
      return;
    }
    await new Promise<void>((resolve) => this.permitWaiters.push(resolve));
    this.active += 1;
  }

  private releasePermit(): void {
    this.active = Math.max(0, this.active - 1);
    this.permitWaiters.shift()?.();
  }

  async dispose(): Promise<void> {
    this.disposed = true;
    await Promise.allSettled([...this.familyTails.values()]);
  }
}
