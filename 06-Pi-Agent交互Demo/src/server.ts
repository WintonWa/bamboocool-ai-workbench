import { createServer as createHttpServer, type IncomingMessage, type ServerResponse } from "node:http";
import { existsSync, readFileSync } from "node:fs";
import { basename, extname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { getAgentDir } from "@earendil-works/pi-coding-agent";
import {
  HOST,
  MAX_MESSAGE_LENGTH,
  MAX_TOOL_CALLS,
  PORT,
  RUN_TIMEOUT_MS,
  SCENARIO_ID,
  WEB_DIR,
} from "./config.ts";
import { DemoRepository } from "./database.ts";
import { EventAdapter, publicError } from "./event-adapter.ts";
import { runDemandForecast } from "./demand-forecast-agent.ts";
import { readDemandForecastRunStatus, TRIGGERS, type ForecastTrigger } from "./demand-forecast.ts";
import { PiSessionStore } from "./pi-session.ts";
import { buildScenarioPrompt, FORECAST_SCENARIO } from "./scenarios/index.ts";
import { CompetitorTaskService } from "./competitor-task-service.ts";
import { KeywordLoopTaskService } from "./keyword-loop-task.ts";
import type { StreamEvent } from "./types.ts";

const CONTENT_TYPES: Record<string, string> = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "application/javascript; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
};

type RunRequest = { sessionId?: unknown; scenarioId?: unknown; childAsin?: unknown; message?: unknown };
type DemandForecastRequest = { childAsin?: unknown; trigger?: unknown };

function json(res: ServerResponse, status: number, payload: unknown): void {
  const body = Buffer.from(JSON.stringify(payload));
  res.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "content-length": body.length,
    "cache-control": "no-store",
  });
  res.end(body);
}

async function bodyJson<T>(req: IncomingMessage): Promise<T> {
  const chunks: Buffer[] = [];
  let size = 0;
  for await (const chunk of req) {
    const buffer = Buffer.from(chunk);
    size += buffer.length;
    if (size > 16_384) throw new Error("REQUEST_TOO_LARGE");
    chunks.push(buffer);
  }
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8")) as T;
  } catch {
    throw new Error("INVALID_JSON");
  }
}

function validateRun(input: RunRequest) {
  const sessionId = typeof input.sessionId === "string" ? input.sessionId : "";
  const scenarioId = typeof input.scenarioId === "string" ? input.scenarioId : "";
  const childAsin = typeof input.childAsin === "string" ? input.childAsin.trim().toUpperCase() : "";
  const message = typeof input.message === "string" ? input.message.trim() : "";
  if (!/^session_[a-zA-Z0-9-]{8,80}$/.test(sessionId)) throw new Error("INVALID_SESSION");
  if (scenarioId !== SCENARIO_ID) throw new Error("INVALID_SCENARIO");
  if (!/^[A-Z0-9]{10}$/.test(childAsin)) throw new Error("INVALID_CHILD_ASIN");
  if (!message || message.length > MAX_MESSAGE_LENGTH) throw new Error("INVALID_MESSAGE");
  return { sessionId, scenarioId, childAsin, message };
}

function validationError(error: unknown): { status: number; code: string; message: string } {
  const code = error instanceof Error ? error.message : "INVALID_REQUEST";
  const messages: Record<string, string> = {
    REQUEST_TOO_LARGE: "请求内容过大。",
    INVALID_JSON: "请求不是有效 JSON。",
    INVALID_SESSION: "会话标识无效。",
    INVALID_SCENARIO: "当前只支持子 ASIN 90 天销量与库存预测。",
    INVALID_CHILD_ASIN: "请选择有效的子 ASIN。",
    INVALID_MESSAGE: "请输入 1–2000 字的问题。",
  };
  return { status: code === "REQUEST_TOO_LARGE" ? 413 : 400, code, message: messages[code] ?? "请求无效。" };
}

function streamHeaders(res: ServerResponse): void {
  res.writeHead(200, {
    "content-type": "application/x-ndjson; charset=utf-8",
    "cache-control": "no-store, no-transform",
    connection: "keep-alive",
    "x-content-type-options": "nosniff",
  });
}

function writeEvent(res: ServerResponse, event: StreamEvent): void {
  if (!res.destroyed && !res.writableEnded) res.write(`${JSON.stringify(event)}\n`);
}

function zh(value: number): string {
  return value.toLocaleString("zh-CN");
}

function answerFromFixture(repository: DemoRepository, requestedChildAsin: string): string {
  const route = repository.routeDemoChildAsin(requestedChildAsin)!;
  const analysisAsin = route.analysisChildAsin;
  const context = repository.getChildProductContext(analysisAsin)!;
  const audit = repository.auditChildDailyHistory(analysisAsin)!;
  const reconstruction = repository.reconstructChildDemand(analysisAsin)!;
  const drivers = repository.estimateDemandDrivers(analysisAsin)!;
  const forecast = repository.forecastChildSalesDaily(analysisAsin)!;
  const supply = repository.getChildInventorySupply(analysisAsin)!;
  const projection = repository.projectChildInventoryDaily(analysisAsin)!;
  const decision = repository.recommendChildReplenishment(analysisAsin)!;
  const base = projection.scenarios.find((item) => item.scenario === "base")!;
  const stress = projection.scenarios.find((item) => item.scenario === "stress")!;
  const improvement = projection.scenarios.find((item) => item.scenario === "improvement")!;
  return `演示映射\n请求子 ASIN ${requestedChildAsin} ${route.wasMapped ? `已通过门禁映射到完整样本 ${analysisAsin}` : "直接使用完整样本"}，画像为“${route.profileName}”。\n\n需求预测\n${context.styleName}（${context.size}）在 ${forecast.startDate} 至 ${forecast.endDate} 的 P50 销量为 ${zh(forecast.p50Units)} 件，日均 ${forecast.p50DailyAverage} 件；P10–P90 为 ${zh(forecast.p10Units)}–${zh(forecast.p90Units)} 件。\n\n预测依据\n审计了 ${audit.observedDays} 天逐日历史，发现 ${audit.stockoutDays} 天缺货；由 ${zh(audit.totalObservedUnits)} 件观测销量还原为 ${zh(Math.round(reconstruction.estimatedDemandUnits))} 件需求。未来广告系数 ${drivers.future.advertisingEffect}、促销 ${drivers.future.plannedPromotionDays} 天。选中 ${forecast.selectedModel}，滚动验证 WAPE ${(forecast.modelWape * 100).toFixed(1)}%。\n\n库存承接\n截至 ${supply.asOfDate}，FBA 可售 ${zh(supply.fbaSellable)} 件。基准场景风险 ${base.riskStatus}、缺货日 ${base.stockoutDate}；压力场景缺货日 ${stress.stockoutDate}；改善场景缺货日 ${improvement.stockoutDate}。\n\n补货建议\n动态安全库存 ${decision.dynamicSafetyDays} 天 / ${zh(decision.dynamicSafetyUnits)} 件；最晚下单日 ${decision.latestOrderDate}；建议补货 ${zh(decision.suggestedReplenishmentQty)} 件（空运 ${zh(decision.suggestedAirQty)}、海运 ${zh(decision.suggestedSeaQty)}）。\n\n限制\n历史主体来自客户父体事实并按确定性方法下钻，未来计划含演示构造，预测与库存决策属于 model_derived；映射样本只用于演示流程，不代表请求子 ASIN 的真实专属结论。`;
}

async function runFixture(res: ServerResponse, repository: DemoRepository, runId: string, sessionId: string, childAsin: string): Promise<void> {
  const steps = [
    ["fixture-route", "route_demo_child_asin", "执行演示门禁", "已完成子 ASIN 路由"],
    ["fixture-context", "get_child_product_context", "确认子 ASIN 与生命周期", "已确认商品上下文"],
    ["fixture-audit", "audit_child_daily_history", "审计 730 天历史", "历史完整性与异常检查完成"],
    ["fixture-reconstruct", "reconstruct_child_demand", "还原真实需求", "已校正缺货与异常影响"],
    ["fixture-drivers", "estimate_demand_drivers", "评估需求影响项", "已读取未来经营计划"],
    ["fixture-forecast", "forecast_child_sales_daily", "预测未来 90 天销量", "已生成逐日 P10/P50/P90"],
    ["fixture-supply", "get_child_inventory_supply", "读取库存与在途", "已读取库存、策略和供给事件"],
    ["fixture-projection", "project_child_inventory_daily", "推演三种库存场景", "基准、压力、改善场景完成"],
    ["fixture-decision", "recommend_child_replenishment", "形成补货建议", "已生成补货量与最晚下单日"],
  ];
  for (const [stepId, tool, label, summary] of steps) {
    writeEvent(res, { type: "step.started", runId, stepId, tool, label });
    writeEvent(res, { type: "step.completed", runId, stepId, tool, label, summary, durationMs: 1 });
  }
  writeEvent(res, { type: "answer.delta", runId, delta: answerFromFixture(repository, childAsin) });
  writeEvent(res, { type: "run.completed", runId, sessionId });
}

async function handleRun(
  req: IncomingMessage,
  res: ServerResponse,
  repository: DemoRepository,
  sessions: PiSessionStore,
): Promise<void> {
  let input;
  try {
    input = validateRun(await bodyJson<RunRequest>(req));
  } catch (error) {
    const failure = validationError(error);
    json(res, failure.status, { error: failure.code, message: failure.message });
    return;
  }
  if (!repository.routeDemoChildAsin(input.childAsin)) {
    json(res, 404, { error: "CHILD_NOT_FOUND", message: "没有找到这个子 ASIN。" });
    return;
  }

  const runId = `run_${crypto.randomUUID()}`;
  streamHeaders(res);
  writeEvent(res, { type: "run.started", runId, sessionId: input.sessionId, scenarioId: input.scenarioId });

  if (process.env.BAMBOO_AGENT_FAKE === "1") {
    await runFixture(res, repository, runId, input.sessionId, input.childAsin);
    res.end();
    return;
  }

  let stored;
  try {
    stored = await sessions.getOrCreate(input.sessionId);
  } catch (error) {
    const failure = publicError(error);
    writeEvent(res, { type: "run.failed", runId, ...failure });
    res.end();
    return;
  }
  if (stored.busy || stored.session.isStreaming) {
    writeEvent(res, { type: "run.failed", runId, code: "SESSION_BUSY", message: "当前会话仍在运行，请先停止或等待完成。" });
    res.end();
    return;
  }

  stored.workflow.reset();
  stored.busy = true;
  stored.lastUsedAt = Date.now();
  const adapter = new EventAdapter(runId);
  let toolCalls = 0;
  let finished = false;
  let cancelled = false;
  let timedOut = false;
  const unsubscribe = stored.session.subscribe((event) => {
    if (event.type === "tool_execution_start") {
      toolCalls += 1;
      if (toolCalls > MAX_TOOL_CALLS) {
        writeEvent(res, { type: "run.warning", runId, code: "TOOL_BUDGET_EXCEEDED", message: "工具调用次数超过演示上限，已停止。" });
        void stored.session.abort();
      }
    }
    const adapted = adapter.adapt(event);
    if (adapted) writeEvent(res, adapted);
  });
  const abortForDisconnect = () => {
    if (!finished) {
      cancelled = true;
      void stored.session.abort();
    }
  };
  res.on("close", abortForDisconnect);
  const timeout = setTimeout(() => {
    timedOut = true;
    void stored.session.abort();
  }, RUN_TIMEOUT_MS);

  try {
    await stored.session.prompt(buildScenarioPrompt(input.childAsin, input.message));
    if (timedOut) throw new Error("timeout");
    if (toolCalls < 9) {
      writeEvent(res, { type: "run.warning", runId, code: "INCOMPLETE_TOOL_TRACE", message: "本次 Agent 未完成全部必要工具步骤。" });
    }
    if (!cancelled) writeEvent(res, { type: "run.completed", runId, sessionId: input.sessionId });
  } catch (error) {
    if (cancelled) {
      writeEvent(res, { type: "run.cancelled", runId, sessionId: input.sessionId });
    } else {
      const failure = publicError(error);
      writeEvent(res, { type: "run.failed", runId, ...failure });
    }
  } finally {
    finished = true;
    clearTimeout(timeout);
    unsubscribe();
    res.off("close", abortForDisconnect);
    stored.busy = false;
    stored.lastUsedAt = Date.now();
    if (!res.writableEnded) res.end();
  }
}

/**
 * 同步 POST 保持兼容；运行开始即写 run/step，失败时保留进度与中文原因供状态接口读取。
 * 落表路径可用 BAMBOO_FORECAST_DB / BAMBOO_FORECAST_JSON 改写（测试用），默认写工作台 derived 目录。
 */
async function handleDemandForecast(
  req: IncomingMessage,
  res: ServerResponse,
  repository: DemoRepository,
): Promise<void> {
  let childAsin = "";
  let trigger: ForecastTrigger = "manual";
  try {
    const input = await bodyJson<DemandForecastRequest>(req);
    childAsin = typeof input.childAsin === "string" ? input.childAsin.trim().toUpperCase() : "";
    if (!/^[A-Z0-9]{10}$/.test(childAsin)) throw new Error("请提供有效的子 ASIN。");
    if (input.trigger !== undefined) {
      if (!TRIGGERS.includes(input.trigger as ForecastTrigger)) {
        throw new Error(`trigger 只能是 ${TRIGGERS.join(" / ")}。`);
      }
      trigger = input.trigger as ForecastTrigger;
    }
  } catch (error) {
    const message = error instanceof Error && error.message === "INVALID_JSON"
      ? "请求不是有效 JSON。"
      : (error instanceof Error && error.message === "REQUEST_TOO_LARGE" ? "请求内容过大。" : String((error as Error).message));
    json(res, 400, { ok: false, run_id: null, child_asin: childAsin, model_version: null, steps: [], daily_written: 0, factors_written: 0, errors: [message] });
    return;
  }
  if (!repository.routeDemoChildAsin(childAsin)) {
    json(res, 404, { ok: false, run_id: null, child_asin: childAsin, model_version: null, steps: [], daily_written: 0, factors_written: 0, errors: ["没有找到这个子 ASIN。"] });
    return;
  }
  try {
    const result = await runDemandForecast({
      childAsin,
      trigger,
      fake: process.env.BAMBOO_AGENT_FAKE === "1",
      dbPath: process.env.BAMBOO_FORECAST_DB,
      exportPath: process.env.BAMBOO_FORECAST_JSON,
    });
    json(res, 200, result);
  } catch (error) {
    const message = error instanceof Error ? error.message : "需求预测运行失败。";
    json(res, 200, { ok: false, run_id: null, child_asin: childAsin, model_version: null, steps: [], daily_written: 0, factors_written: 0, errors: [message] });
  }
}

function handleDemandForecastStatus(res: ServerResponse, url: URL): void {
  const runId = url.searchParams.get("runId")?.trim() || undefined;
  const childAsin = url.searchParams.get("childAsin")?.trim().toUpperCase() || undefined;
  if (!runId && !childAsin) {
    json(res, 400, { ok: false, run: null, steps: [], error: "缺少 runId 或 childAsin" });
    return;
  }
  if (childAsin && !/^[A-Z0-9]{10}$/.test(childAsin)) {
    json(res, 400, { ok: false, run: null, steps: [], error: "请提供有效的子 ASIN" });
    return;
  }
  const result = readDemandForecastRunStatus({
    runId,
    childAsin: runId ? undefined : childAsin,
    dbPath: process.env.BAMBOO_FORECAST_DB,
  });
  json(res, result.ok ? 200 : 404, result);
}

async function handleCompetitorEnqueue(
  req: IncomingMessage,
  res: ServerResponse,
  service: CompetitorTaskService,
): Promise<void> {
  try {
    const task = await service.enqueue(await bodyJson<unknown>(req));
    json(res, 202, task);
  } catch (error) {
    const code = error instanceof Error ? error.message : "INVALID_REQUEST";
    if (code === "REQUEST_TOO_LARGE" || code === "INVALID_JSON") {
      const failure = validationError(error);
      json(res, failure.status, { error: failure.code, message: failure.message });
      return;
    }
    json(res, 400, { error: "INVALID_COMPETITOR_RUN", message: code });
  }
}

async function handleCompetitorTask(
  res: ServerResponse,
  service: CompetitorTaskService,
  taskId: string,
): Promise<void> {
  const task = await service.get(taskId);
  if (!task) {
    json(res, 404, { error: "TASK_NOT_FOUND", message: "竞品分析任务不存在。" });
    return;
  }
  json(res, 200, task);
}

async function handleKeywordLoopEnqueue(
  req: IncomingMessage, res: ServerResponse, service: KeywordLoopTaskService,
): Promise<void> {
  try {
    await bodyJson<unknown>(req);
    json(res, 202, service.enqueue());
  } catch (error) {
    if (error instanceof Error && ["INVALID_JSON", "REQUEST_TOO_LARGE"].includes(error.message)) {
      const failure = validationError(error);
      json(res, failure.status, { error: failure.code, message: failure.message });
      return;
    }
    json(res, 500, { error: "KEYWORD_LOOP_START_FAILED", message: "关键词 Pi Loop 没有成功创建运行记录。" });
  }
}

function handleKeywordLoopStatus(res: ServerResponse, service: KeywordLoopTaskService): void {
  try {
    json(res, 200, service.latest());
  } catch {
    json(res, 500, { error: "KEYWORD_LOOP_STATUS_FAILED", message: "关键词 Pi Loop 状态暂时无法读取。" });
  }
}

function serveStatic(res: ServerResponse, pathname: string): void {
  const requested = pathname === "/" ? "index.html" : pathname.slice(1);
  const fullPath = resolve(WEB_DIR, requested);
  if (!fullPath.startsWith(`${WEB_DIR}/`) || !existsSync(fullPath)) {
    json(res, 404, { error: "NOT_FOUND", message: "页面不存在。" });
    return;
  }
  const body = readFileSync(fullPath);
  res.writeHead(200, {
    "content-type": CONTENT_TYPES[extname(fullPath)] ?? "application/octet-stream",
    "content-length": body.length,
    "cache-control": "no-store",
    "x-content-type-options": "nosniff",
  });
  res.end(body);
}

export function createDemoServer(repository = new DemoRepository()) {
  const sessions = new PiSessionStore(repository);
  // Lazy creation keeps unrelated forecast/server tests from touching the
  // competitor state DB merely by constructing an HTTP server.
  let competitorTasks: CompetitorTaskService | undefined;
  const getCompetitorTasks = () => competitorTasks ??= new CompetitorTaskService();
  let keywordLoopTasks: KeywordLoopTaskService | undefined;
  const getKeywordLoopTasks = () => keywordLoopTasks ??= new KeywordLoopTaskService();
  const server = createHttpServer(async (req, res) => {
    const url = new URL(req.url ?? "/", `http://${HOST}`);
    try {
      if (req.method === "GET" && url.pathname === "/api/health") {
        const agentDir = getAgentDir();
        json(res, 200, {
          status: "ok",
          database: repository.ping() ? "ready" : "unavailable",
          piConfigured: existsSync(join(agentDir, "auth.json")) && existsSync(join(agentDir, "settings.json")),
          mode: process.env.BAMBOO_AGENT_FAKE === "1" ? "fixture" : "pi",
          scenario: FORECAST_SCENARIO.id,
        });
      } else if (req.method === "GET" && url.pathname === "/api/children") {
        json(res, 200, { children: repository.listChildren() });
      } else if (req.method === "POST" && url.pathname === "/api/agent/run") {
        await handleRun(req, res, repository, sessions);
      } else if (req.method === "POST" && url.pathname === "/api/agent/demand-forecast") {
        await handleDemandForecast(req, res, repository);
      } else if (req.method === "GET" && url.pathname === "/api/agent/demand-forecast/status") {
        handleDemandForecastStatus(res, url);
      } else if (req.method === "POST" && url.pathname === "/api/agent/keyword/loop-runs") {
        await handleKeywordLoopEnqueue(req, res, getKeywordLoopTasks());
      } else if (req.method === "GET" && url.pathname === "/api/agent/keyword/loop-runs/status") {
        handleKeywordLoopStatus(res, getKeywordLoopTasks());
      } else if (req.method === "POST" && url.pathname === "/api/agent/competitor/runs") {
        await handleCompetitorEnqueue(req, res, getCompetitorTasks());
      } else if (req.method === "GET" && url.pathname.startsWith("/api/agent/competitor/tasks/")) {
        const taskId = decodeURIComponent(basename(url.pathname));
        await handleCompetitorTask(res, getCompetitorTasks(), taskId);
      } else if (req.method === "DELETE" && url.pathname.startsWith("/api/agent/session/")) {
        const sessionId = basename(url.pathname);
        if (!/^session_[a-zA-Z0-9-]{8,80}$/.test(sessionId)) {
          json(res, 400, { error: "INVALID_SESSION", message: "会话标识无效。" });
        } else {
          sessions.delete(sessionId);
          json(res, 200, { ok: true });
        }
      } else if (req.method === "GET" && !url.pathname.startsWith("/api/")) {
        serveStatic(res, url.pathname);
      } else {
        json(res, 404, { error: "NOT_FOUND", message: "接口不存在。" });
      }
    } catch {
      if (!res.headersSent) json(res, 500, { error: "SERVER_ERROR", message: "本地服务发生错误。" });
      else if (!res.writableEnded) res.end();
    }
  });
  server.on("close", () => {
    sessions.disposeAll();
    if (competitorTasks) void competitorTasks.dispose();
    repository.close();
  });
  return server;
}

const isMain = process.argv[1] && fileURLToPath(import.meta.url) === resolve(process.argv[1]);
if (isMain) {
  const server = createDemoServer();
  server.listen(PORT, HOST, () => console.log(`Bamboocool Pi Agent Demo: http://${HOST}:${PORT}/`));
  const shutdown = () => server.close(() => process.exit(0));
  process.on("SIGINT", shutdown);
  process.on("SIGTERM", shutdown);
}
