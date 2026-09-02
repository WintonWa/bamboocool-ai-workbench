import { randomUUID } from "node:crypto";
import { mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { DatabaseSync } from "node:sqlite";
import {
  createAgentSession, DefaultResourceLoader, defineTool, getAgentDir,
  ModelRuntime, SessionManager, SettingsManager,
} from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import {
  KEYWORD_PROJECT_ROOT, KEYWORD_WORKBENCH_ROOT, loadKeywordAgentFacts,
  shanghaiTimestamp, validateMarketBatch,
  type JsonObject, type MarketDecision,
} from "./keyword-agent.ts";

export const DEFAULT_KEYWORD_LOOP_STATE_DB = resolve(
  KEYWORD_WORKBENCH_ROOT, "modules/keyword/derived/keyword_agent_loop_state.sqlite",
);

const LOOP_STEPS = [
  [1, "冻结关键词分析范围", "关键词范围与判断参数"],
  [2, "读取首批市场候选", "关键词市场快照"],
  [3, "创建真实 Pi 会话", "本机 Pi 模型配置"],
  [4, "调用 Pi 判断首批市场候选", "关键词市场快照"],
  [5, "接受结构化工具结果", "关键词判断门禁"],
  [6, "在 Demo 边界收口", "关键词 Agent 运行态"],
] as const;

const SCHEMA = `
CREATE TABLE IF NOT EXISTS fact_keyword_loop_run (
  task_id TEXT PRIMARY KEY, status TEXT NOT NULL,
  current_step INTEGER NOT NULL, total_steps INTEGER NOT NULL,
  model_version TEXT, accepted_count INTEGER NOT NULL DEFAULT 0,
  result_count INTEGER NOT NULL DEFAULT 0, message TEXT, error_code TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_keyword_loop_latest
  ON fact_keyword_loop_run(created_at DESC, task_id DESC);
CREATE TABLE IF NOT EXISTS fact_keyword_loop_step (
  task_id TEXT NOT NULL, step_seq INTEGER NOT NULL, label TEXT NOT NULL,
  detail TEXT NOT NULL, status TEXT NOT NULL, sources_json TEXT NOT NULL,
  updated_at TEXT NOT NULL, PRIMARY KEY(task_id, step_seq)
);`;

export type KeywordLoopCallbacks = {
  sessionReady: (modelVersion: string) => void;
  promptStarted: () => void;
};

export type KeywordLoopModelResult = {
  modelVersion: string;
  decisions: MarketDecision[];
};

export type KeywordLoopModelRunner = (
  candidates: JsonObject[], callbacks: KeywordLoopCallbacks,
) => Promise<KeywordLoopModelResult>;

export type KeywordLoopTaskOptions = {
  dbPath?: string;
  modelRunner?: KeywordLoopModelRunner;
};

async function runFixtureKeywordLoopModel(
  candidates: JsonObject[], callbacks: KeywordLoopCallbacks,
): Promise<KeywordLoopModelResult> {
  callbacks.sessionReady("fixture/keyword-loop");
  callbacks.promptStarted();
  return {
    modelVersion: "fixture/keyword-loop",
    decisions: candidates.map((candidate) => ({
      candidate_id: String(candidate.candidate_id), event_type: null,
      continuity: null, label: null,
    })),
  };
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

const LOOP_SYSTEM_PROMPT = `你是 Bamboocool 关键词分析 Agent 的 Loop 演示执行器。
本轮只判断工具提供的 20 个市场候选。周线与月线不得合并；只有明显的需求方向、竞争上升、样本不足或口径不可比才形成事件，否则三个判断字段都返回 null。
你必须覆盖每个 candidate_id，不增删、不重复，只调用一次 submit_keyword_loop_market_batch。工具调用后立即结束，不输出报告、Markdown 或隐藏思维链。`;

function toolSuccess(details: JsonObject) {
  return { content: [{ type: "text" as const, text: JSON.stringify(details) }], details };
}

function configuredModel(): { provider: string; id: string } | null {
  const value = (process.env.BAMBOO_KEYWORD_MODEL ?? "").trim();
  const slash = value.indexOf("/");
  if (slash < 1 || slash === value.length - 1) return null;
  return { provider: value.slice(0, slash), id: value.slice(slash + 1) };
}

function safeFailure(error: unknown): { code: string; message: string } {
  const raw = error instanceof Error ? error.message : String(error);
  if (/402|insufficient balance|余额不足/i.test(raw)) {
    return { code: "MODEL_BALANCE", message: "模型账户余额不足，Pi Loop 已启动，但本批判断未完成" };
  }
  if (/超时|timeout/i.test(raw)) {
    return { code: "MODEL_TIMEOUT", message: "Pi 模型超过 60 秒没有完成本批判断" };
  }
  if (/未调用|未推进|tool/i.test(raw)) {
    return { code: "TOOL_NOT_CALLED", message: "Pi 已响应，但没有按契约调用市场判断工具" };
  }
  if (/找不到指定模型/i.test(raw)) {
    return { code: "MODEL_NOT_FOUND", message: "Pi 找不到当前指定的关键词演示模型" };
  }
  return { code: "LOOP_FAILED", message: "关键词 Pi Loop 本次未完成，可以重新运行" };
}

export async function runRealKeywordLoopModel(
  candidates: JsonObject[], callbacks: KeywordLoopCallbacks,
): Promise<KeywordLoopModelResult> {
  const agentDir = getAgentDir();
  const settingsManager = SettingsManager.create(KEYWORD_PROJECT_ROOT, agentDir);
  const loader = new DefaultResourceLoader({
    cwd: KEYWORD_PROJECT_ROOT, agentDir, settingsManager,
    noExtensions: true, noPromptTemplates: true, noThemes: true, noContextFiles: true,
    systemPromptOverride: () => LOOP_SYSTEM_PROMPT,
    appendSystemPromptOverride: () => [],
  });
  await loader.reload();
  const modelRuntime = await ModelRuntime.create();
  const requested = configuredModel();
  // Pi 全局默认目前可能指向余额不足的供应商。Loop Smoke 在没有显式环境变量时，
  // 优先选本机已经配置的轻量演示模型；本机没有它才真正回落 Pi 默认。
  const localDemo = { provider: "xiaoyao", id: "gpt-5.6-luna" };
  const selected = requested
    ? modelRuntime.getModel(requested.provider, requested.id)
    : modelRuntime.getModel(localDemo.provider, localDemo.id) ?? undefined;
  if (requested && !selected) throw new Error(`Pi 找不到指定模型 ${requested.provider}/${requested.id}`);

  let accepted: MarketDecision[] | null = null;
  const tool = defineTool({
    name: "submit_keyword_loop_market_batch",
    label: "提交首批市场变化判断",
    description: "覆盖本批全部 candidate_id，提交市场事件或正式 null。",
    executionMode: "sequential",
    parameters: Type.Object({ decisions: Type.Array(marketSchema) }),
    execute: async (_id, params) => {
      const decisions = params.decisions as MarketDecision[];
      const errors = validateMarketBatch(candidates, decisions);
      if (errors.length) throw new Error(errors.join("；"));
      accepted = decisions;
      return toolSuccess({ ok: true, accepted: decisions.length });
    },
  });

  const { session } = await createAgentSession({
    cwd: KEYWORD_PROJECT_ROOT, agentDir, modelRuntime,
    ...(selected ? { model: selected } : {}),
    thinkingLevel: "medium", tools: [tool.name], customTools: [tool],
    resourceLoader: loader, sessionManager: SessionManager.inMemory(KEYWORD_PROJECT_ROOT), settingsManager,
  });
  const modelVersion = session.model
    ? `${session.model.provider}/${session.model.id}`
    : requested ? `${requested.provider}/${requested.id}`
      : selected ? `${localDemo.provider}/${localDemo.id}` : "pi-local-default";
  callbacks.sessionReady(modelVersion);
  session.setActiveToolsByName([tool.name]);
  let assistantError = "";
  const unsubscribe = session.subscribe((event: any) => {
    if (event.type === "message_end" && event.message?.role === "assistant") {
      assistantError = String(event.message.errorMessage ?? "");
    }
  });
  let timer: NodeJS.Timeout | undefined;
  try {
    callbacks.promptStarted();
    const prompt = `只调用 submit_keyword_loop_market_batch。以下是本批唯一 candidates：\n${JSON.stringify(candidates)}`;
    await Promise.race([
      session.prompt(prompt),
      new Promise<never>((_, reject) => {
        timer = setTimeout(() => reject(new Error("Pi 单批超时 60000ms")), 60_000);
      }),
    ]);
    if (!accepted) throw new Error(assistantError || "Pi 本轮未调用指定工具");
    return { modelVersion, decisions: accepted };
  } catch (error) {
    await session.abort().catch(() => {});
    throw error;
  } finally {
    if (timer) clearTimeout(timer);
    unsubscribe();
    session.dispose();
  }
}

export class KeywordLoopTaskService {
  readonly dbPath: string;
  private readonly modelRunner: KeywordLoopModelRunner;
  private readonly active = new Map<string, Promise<void>>();

  constructor(options: KeywordLoopTaskOptions = {}) {
    this.dbPath = options.dbPath ?? process.env.BAMBOO_KEYWORD_LOOP_DB ?? DEFAULT_KEYWORD_LOOP_STATE_DB;
    this.modelRunner = options.modelRunner
      ?? (process.env.BAMBOO_AGENT_FAKE === "1" ? runFixtureKeywordLoopModel : runRealKeywordLoopModel);
    mkdirSync(dirname(this.dbPath), { recursive: true });
    const db = new DatabaseSync(this.dbPath);
    try { db.exec(SCHEMA); } finally { db.close(); }
  }

  enqueue(): JsonObject {
    const running = this.row("SELECT * FROM fact_keyword_loop_run WHERE status='running' ORDER BY created_at DESC LIMIT 1");
    if (running) return { ...this.publicTask(String(running.task_id)), reused: true };
    const taskId = `keyword-loop-${shanghaiTimestamp().replace(/\D/g, "").slice(0, 14)}-${randomUUID().slice(0, 6)}`;
    const now = shanghaiTimestamp();
    const db = new DatabaseSync(this.dbPath);
    try {
      db.exec("BEGIN IMMEDIATE");
      db.prepare(`INSERT INTO fact_keyword_loop_run
        (task_id,status,current_step,total_steps,created_at,updated_at,message)
        VALUES (?, 'running', 1, ?, ?, ?, ?)`)
        .run(taskId, LOOP_STEPS.length, now, now, "真实 Pi Loop 正在运行；业务结果尚未发布");
      const insert = db.prepare(`INSERT INTO fact_keyword_loop_step
        (task_id,step_seq,label,detail,status,sources_json,updated_at)
        VALUES (?,?,?,?,?,?,?)`);
      for (const [seq, label, source] of LOOP_STEPS) {
        insert.run(taskId, seq, label, seq === 1 ? "正在锁定数据截止日和判断参数" : "等待前一步完成",
          seq === 1 ? "running" : "pending", JSON.stringify([source]), now);
      }
      db.exec("COMMIT");
    } catch (error) {
      try { db.exec("ROLLBACK"); } catch { /* no transaction */ }
      throw error;
    } finally { db.close(); }
    const promise = this.execute(taskId).finally(() => this.active.delete(taskId));
    this.active.set(taskId, promise);
    return { ...this.publicTask(taskId), reused: false };
  }

  latest(): JsonObject {
    const latest = this.row("SELECT * FROM fact_keyword_loop_run ORDER BY created_at DESC, task_id DESC LIMIT 1");
    if (!latest) return { ok: true, run: null, steps: [] };
    if (latest.status === "running" && !this.active.has(String(latest.task_id))) {
      this.fail(String(latest.task_id), "PROCESS_ENDED", "上次关键词 Loop 的运行进程已经结束");
    }
    return this.publicTask(String(latest.task_id));
  }

  private row(sql: string, ...params: any[]): JsonObject | undefined {
    const db = new DatabaseSync(this.dbPath, { readOnly: true });
    try { return db.prepare(sql).get(...params) as JsonObject | undefined; }
    finally { db.close(); }
  }

  private publicTask(taskId: string): JsonObject {
    const db = new DatabaseSync(this.dbPath, { readOnly: true });
    try {
      const run = db.prepare("SELECT * FROM fact_keyword_loop_run WHERE task_id=?").get(taskId) as JsonObject;
      const steps = db.prepare(`SELECT step_seq,label,detail,status,sources_json,updated_at
        FROM fact_keyword_loop_step WHERE task_id=? AND status<>'pending' ORDER BY step_seq`).all(taskId) as JsonObject[];
      return {
        ok: true,
        run: {
          run_id: run.task_id, status: run.status, current_step: run.current_step,
          total_steps: run.total_steps, model_version: run.model_version,
          accepted_count: run.accepted_count, result_count: run.result_count,
          message: run.message, error_code: run.error_code,
          created_at: run.created_at, completed_at: run.completed_at,
        },
        steps: steps.map((step) => ({
          seq: step.step_seq, label: step.label, detail: step.detail,
          status: step.status, sources: JSON.parse(String(step.sources_json)),
          updated_at: step.updated_at,
        })),
      };
    } finally { db.close(); }
  }

  private step(taskId: string, seq: number, status: "running" | "completed", detail: string): void {
    const now = shanghaiTimestamp();
    const db = new DatabaseSync(this.dbPath);
    try {
      db.prepare("UPDATE fact_keyword_loop_step SET status=?,detail=?,updated_at=? WHERE task_id=? AND step_seq=?")
        .run(status, detail, now, taskId, seq);
      db.prepare("UPDATE fact_keyword_loop_run SET current_step=?,updated_at=? WHERE task_id=?")
        .run(seq, now, taskId);
    } finally { db.close(); }
  }

  private async execute(taskId: string): Promise<void> {
    try {
      const facts = loadKeywordAgentFacts("all");
      this.step(taskId, 1, "completed", `已锁定 ${facts.as_of_date} 数据和六项判断参数`);
      this.step(taskId, 2, "running", "正在从允许输入表生成首批候选");
      const candidates = facts.market_candidates.slice(0, 20);
      if (candidates.length !== 20) throw new Error("首批市场候选不足 20 个");
      this.step(taskId, 2, "completed", `已读取 ${candidates.length} 个市场候选`);
      this.step(taskId, 3, "running", "正在读取本机 Pi 模型配置");
      const result = await this.modelRunner(candidates, {
        sessionReady: (modelVersion) => {
          const db = new DatabaseSync(this.dbPath);
          try {
            db.prepare("UPDATE fact_keyword_loop_run SET model_version=?,updated_at=? WHERE task_id=?")
              .run(modelVersion, shanghaiTimestamp(), taskId);
          } finally { db.close(); }
          this.step(taskId, 3, "completed", `已创建 ${modelVersion} 会话`);
          this.step(taskId, 4, "running", `正在分析 ${candidates.length} 个市场候选`);
        },
        promptStarted: () => {},
      });
      this.step(taskId, 4, "completed", "Pi 已完成本批判断并调用结构化工具");
      this.step(taskId, 5, "running", "正在校验候选覆盖、枚举和变化方向");
      const errors = validateMarketBatch(candidates, result.decisions);
      if (errors.length) throw new Error(errors.join("；"));
      const resultCount = result.decisions.filter((item) => item.event_type !== null).length;
      this.step(taskId, 5, "completed", `门禁接受 ${result.decisions.length} 个判断，其中 ${resultCount} 个形成事件`);
      this.step(taskId, 6, "running", "正在结束本次小批次演示");
      this.step(taskId, 6, "completed", "Loop 演示已结束，未发布业务结果");
      const now = shanghaiTimestamp();
      const db = new DatabaseSync(this.dbPath);
      try {
        db.prepare(`UPDATE fact_keyword_loop_run SET status='completed',current_step=?,model_version=?,
          accepted_count=?,result_count=?,message=?,updated_at=?,completed_at=? WHERE task_id=?`)
          .run(LOOP_STEPS.length, result.modelVersion, result.decisions.length, resultCount,
            "Loop 演示完成，未发布业务结果", now, now, taskId);
      } finally { db.close(); }
    } catch (error) {
      const failure = safeFailure(error);
      this.fail(taskId, failure.code, failure.message);
    }
  }

  private fail(taskId: string, code: string, message: string): void {
    const now = shanghaiTimestamp();
    const db = new DatabaseSync(this.dbPath);
    try {
      const run = db.prepare("SELECT current_step FROM fact_keyword_loop_run WHERE task_id=?").get(taskId) as JsonObject | undefined;
      const seq = Number(run?.current_step ?? 1);
      db.prepare("UPDATE fact_keyword_loop_step SET status='failed',detail=?,updated_at=? WHERE task_id=? AND step_seq=?")
        .run(message, now, taskId, seq);
      db.prepare(`UPDATE fact_keyword_loop_run SET status='failed',message=?,error_code=?,
        updated_at=?,completed_at=? WHERE task_id=?`).run(message, code, now, now, taskId);
    } finally { db.close(); }
  }
}
