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
import { ROOT_DIR } from "./config.ts";
import {
  DEFAULT_DEMAND_FORECAST_DB,
  DEFAULT_DEMAND_FORECAST_JSON,
  FACTORS,
  FACTOR_STATES,
  FORECAST_SEGMENT_COUNT,
  beginDemandForecastRun,
  expectedForecastDates,
  failDemandForecastRun,
  finishDemandForecastStep,
  forecastSegments,
  loadDemandForecastFacts,
  startDemandForecastStep,
  updateDemandForecastRunModel,
  validateDailyForecast,
  validateDailyForecastSegment,
  validateDemandAssessment,
  writeDemandForecastRun,
  type DailyForecast,
  type DemandAssessment,
  type DemandForecastFacts,
  type ForecastFactor,
  type ForecastStep,
  type ForecastTrigger,
  type WrittenDemandForecast,
} from "./demand-forecast.ts";

export const DEMAND_FORECAST_TOOLS = [
  "load_sales_inventory_history",
  "load_demand_driver_history",
  "load_future_operating_plan",
  "load_product_tenure_and_supply_context",
  "submit_demand_assessment",
  "submit_daily_forecast_segment",
  "validate_and_commit_forecast_run",
] as const;

const LABELS: Record<string, string> = {
  load_sales_inventory_history: "审计历史销量与缺货",
  load_demand_driver_history: "分析历史需求影响项",
  load_future_operating_plan: "读取未来运营计划",
  load_product_tenure_and_supply_context: "确认上架时长与承接背景",
  submit_demand_assessment: "形成五类需求判断",
  submit_daily_forecast_segment: "生成逐日需求预测",
  validate_and_commit_forecast_run: "校验并发布需求预测",
};

const SOURCES: Record<string, string[]> = {
  load_sales_inventory_history: ["历史逐日销量", "历史逐日可售库存"],
  load_demand_driver_history: ["历史广告表现", "历史活动记录", "历史价格", "历史流量"],
  load_future_operating_plan: ["未来广告计划", "未来活动排期", "未来价格计划"],
  load_product_tenure_and_supply_context: ["产品上架日期", "当前库存", "库存政策", "未来供给计划"],
  submit_demand_assessment: ["客观历史事实", "未来运营计划"],
  submit_daily_forecast_segment: ["需求判断", "未来运营计划"],
  validate_and_commit_forecast_run: ["需求预测契约"],
};

export type DemandForecastRunResponse = {
  ok: boolean;
  run_id: string | null;
  child_asin: string;
  model_version: string | null;
  steps: ForecastStep[];
  daily_written: number;
  factors_written: number;
  errors: string[];
  output?: WrittenDemandForecast;
};

export type DemandForecastRunOptions = {
  childAsin: string;
  trigger: ForecastTrigger;
  dbPath?: string;
  exportPath?: string;
  datasetPath?: string;
  fake?: boolean;
};

const factorSchema = Type.Union(FACTORS.map((factor) => Type.Object({
  factor: Type.Literal(factor),
  ord: Type.Integer({ minimum: 1, maximum: 5 }),
  state: Type.Union(FACTOR_STATES[factor].map((state) => Type.Literal(state))),
  impact_pct: Type.Union([Type.Number({ minimum: -1, maximum: 1 }), Type.Null()]),
  because: Type.String({ minLength: 1, maxLength: 180 }),
  numbers: Type.Record(Type.String(), Type.Number()),
})));

const assessmentSchema = Type.Object({
  confidence: Type.Union([Type.Literal("高"), Type.Literal("中"), Type.Literal("低")]),
  confidence_reason: Type.String({ minLength: 1, maxLength: 100 }),
  judgment_summary: Type.String({ minLength: 1, maxLength: 120 }),
  factors: Type.Array(factorSchema, { minItems: 5, maxItems: 5 }),
});

const dailyRowSchema = Type.Object({
  forecast_date: Type.String(),
  p10_units: Type.Number({ minimum: 0 }),
  p50_units: Type.Number({ minimum: 0 }),
  p90_units: Type.Number({ minimum: 0 }),
  baseline_units: Type.Union([Type.Number({ minimum: 0 }), Type.Null()]),
});

const dailySegmentSchema = Type.Object({
  segment_index: Type.Integer({ minimum: 1, maximum: FORECAST_SEGMENT_COUNT }),
  start_date: Type.String(),
  end_date: Type.String(),
  daily: Type.Array(dailyRowSchema, { minItems: 15, maxItems: 15 }),
});

function systemPrompt(): string {
  const states = FACTORS.map((factor) => `${factor}：${FACTOR_STATES[factor].join(" / ")}`).join("\n");
  return `你是 Bamboocool 需求预测 Agent。预测数字和判断都由你本次运行产出，不能读取或复述数据包里预烤的预测答案。

工作方式：当前运行已经绑定唯一子 ASIN，工具不要求你重复提交 child_asin。用户每轮只要求一个工具，你只调用当前唯一开放的工具，工具返回后结束本轮。不要尝试调用未开放工具。

业务边界：
- 只依据历史实销、历史可售库存、历史广告/活动/价格/流量、上架日期和未来运营计划。
- 绝不索要或假设 clean_baseline、lost_sales、potential_demand、lifecycle_stage、expected_effect、预烤 p10/p50/p90 或模型评估。
- 五类判断与90天逐日预测必须来自同一套事实、同一次运行。
- 不输出覆盖天数、断货日、缺口、补货量或库存风险，这些由工作台计算。

五项 state 词表：
${states}

提交判断时：numbers 必须逐字复制事实的 observable_metrics，并包含 factor_evidence 规定的全部键；impact_pct 在 -1 到 1，判断不出给 null；ord 是1到5的不重复排列；全部中文。

提交逐日预测时：严格按当前要求的15天时间窗，逐日直接给出真实 p10/p50/p90 数字；不能只给形状参数再让代码展开。每天满足 0≤p10≤p50≤p90，baseline_units 可以为 null。相邻分段必须首尾连续，最终共同组成 data_as_of 次日起连续90天。

禁止免责声明、内部英文枚举和思维过程。工具返回校验错误时按错误修正并重试。`;
}

function metricSubset(facts: DemandForecastFacts, prefixes: string[]): Record<string, number> {
  return Object.fromEntries(Object.entries(facts.observable_metrics).filter(([key]) => prefixes.some((prefix) => key.startsWith(prefix))));
}

function fixtureAssessment(facts: DemandForecastFacts): DemandAssessment {
  const m = facts.observable_metrics;
  const factor = (name: ForecastFactor, ord: number, state: string, impact: number | null, because: string) => {
    const required = facts.factor_evidence.find((item) => item.factor === name)!.required_number_keys;
    return { factor: name, ord, state, impact_pct: impact, because, numbers: Object.fromEntries(required.map((key) => [key, m[key]])) };
  };
  const stockState = m.history_stockout_days_90d > 7 ? "重度扭曲" : (m.history_stockout_days_90d > 0 ? "轻度扭曲" : "无扭曲");
  const promoState = m.future_promotion_days > 0 ? "有活动仍在影响" : "无活动";
  const trend = m.history_instock_daily_avg_30d / Math.max(m.history_instock_daily_avg_180d, 0.01) - 1;
  const lifecycleState = trend > 0.08 ? "爬坡" : (trend < -0.08 ? "衰退" : "平稳");
  const adRatio = m.future_ad_spend_daily_30d / Math.max(m.history_ad_spend_daily_30d, 0.01) - 1;
  const adState = m.future_ad_spend_daily_30d === 0 ? "无投放" : (adRatio > 0.05 ? "加大" : (adRatio < -0.05 ? "减少" : "平稳"));
  const seasonRatio = m.matching_last_year_daily_avg / Math.max(m.history_instock_daily_avg_90d, 0.01) - 1;
  const seasonState = seasonRatio > 0.08 ? "旺季" : (seasonRatio < -0.08 ? "淡季" : "不明显");
  return {
    child_asin: facts.child_asin,
    confidence: "中",
    confidence_reason: "历史覆盖两年且未来计划完整，但逐日结果仍受运营计划执行偏差影响。",
    judgment_summary: "近期需求、同期季节性和未来运营计划共同决定本次90天预测。",
    factors: [
      factor("stockout_distortion", 1, stockState, stockState === "无扭曲" ? 0 : 0.03, `近90天缺货${m.history_stockout_days_90d}天，基线按有货日销量评估。`),
      factor("promotion", 2, promoState, promoState === "无活动" ? 0 : 0.05, `未来排期活动${m.future_promotion_days}天，历史活动日与非活动日销量可对照。`),
      factor("lifecycle", 3, lifecycleState, Math.max(-0.2, Math.min(0.2, trend)), `上架${m.days_since_launch}天，近30天与近180天有货日均用于判断阶段。`),
      factor("advertising", 4, adState, Math.max(-0.2, Math.min(0.2, adRatio)), "未来30天计划日均广告花费与历史近30天实际花费对照。"),
      factor("seasonality", 5, seasonState, Math.max(-0.2, Math.min(0.2, seasonRatio)), "去年同期日均与最近90天有货日均用于判断季节变化。"),
    ],
  };
}

function fixtureDaily(facts: DemandForecastFacts, assessment: DemandAssessment): DailyForecast[] {
  const weekdayRows = (facts.sales_inventory.weekday ?? []) as Array<Record<string, number>>;
  const byWeekday = new Map(weekdayRows.map((item) => [Number(item.weekday), Number(item.daily_avg)]));
  const plan = (facts.future_plan.days ?? []) as Array<Record<string, string | number | null>>;
  const impacts = assessment.factors.reduce((sum, item) => sum + (item.impact_pct ?? 0), 0);
  return expectedForecastDates(facts.data_as_of).map((date, index) => {
    const weekday = new Date(`${date}T00:00:00Z`).getUTCDay();
    const baseline = byWeekday.get(weekday) ?? facts.observable_metrics.history_instock_daily_avg_90d;
    const item = plan[index] ?? {};
    const promo = item.promotion_id !== null && item.promotion_id !== undefined && String(item.promotion_status) !== "none" ? 0.05 : 0;
    const p50 = Math.max(0, Math.round((baseline * (1 + impacts + promo)) * 10) / 10);
    return { forecast_date: date, baseline_units: Math.round(baseline * 10) / 10, p10_units: Math.round(p50 * 0.8 * 10) / 10, p50_units: p50, p90_units: Math.round(p50 * 1.2 * 10) / 10 };
  });
}

export type DemandToolTrace = {
  starts: number;
  ends: number;
  successfulEnds: number;
  errors: string[];
  modelErrors: string[];
};

export function safeDemandToolError(result: unknown): string {
  if (!result || typeof result !== "object") return "工具返回失败，但没有错误内容";
  const value = result as { details?: unknown; content?: unknown };
  const details = value.details && typeof value.details === "object"
    ? value.details as { message?: unknown; errors?: unknown }
    : undefined;
  let message = "";
  if (Array.isArray(details?.errors)) message = details.errors.map(String).join("；");
  else if (typeof details?.message === "string") message = details.message;
  if (!message && Array.isArray(value.content)) {
    const text = value.content.find((item) => item && typeof item === "object" && (item as { type?: unknown }).type === "text") as { text?: unknown } | undefined;
    if (typeof text?.text === "string") message = text.text;
  }
  return (message || "工具返回失败，但没有错误内容").replace(/\s+/g, " ").trim().slice(0, 500);
}

export function diagnoseDemandToolTrace(tool: string, trace: DemandToolTrace, registered: boolean): string | null {
  if (trace.successfulEnds > 0) {
    return registered ? null : `工具调用成功但结果未登记：${tool}`;
  }
  if (trace.modelErrors.length > 0) return `模型请求失败：${trace.modelErrors.at(-1)}`;
  if (trace.starts === 0) return `模型返回但没有发起工具调用：${tool}`;
  if (trace.errors.length > 0) return `工具调用被拒绝：${trace.errors.at(-1)}`;
  if (trace.ends === 0) return `工具调用已发起但没有结束：${tool}`;
  return `工具调用结束但没有产生可接受结果：${tool}`;
}

export function safeDemandModelError(raw: unknown): string {
  const message = String(raw ?? "");
  if (/insufficient balance|余额不足|\b402\b/i.test(message)) return "模型服务余额不足（402）";
  if (/rate.?limit|too many requests|\b429\b/i.test(message)) return "模型服务请求过于频繁（429）";
  if (/auth|credential|api.?key|unauthorized|\b401\b|\b403\b/i.test(message)) return "模型服务认证失败";
  if (/timeout|timed out/i.test(message)) return "模型服务响应超时";
  return "模型服务返回错误";
}

export async function runDemandForecast(options: DemandForecastRunOptions): Promise<DemandForecastRunResponse> {
  const facts = loadDemandForecastFacts(options.childAsin, options.datasetPath);
  const dbPath = options.dbPath ?? DEFAULT_DEMAND_FORECAST_DB;
  const exportPath = options.exportPath ?? DEFAULT_DEMAND_FORECAST_JSON;
  const modelDefault = options.fake ? "fixture/deterministic" : "pi-local-default";
  const handle = beginDemandForecastRun({ facts, trigger: options.trigger, modelVersion: modelDefault, dbPath });
  if (handle.reused) {
    return {
      ok: false, run_id: handle.run_id, child_asin: facts.child_asin, model_version: modelDefault,
      steps: [], daily_written: 0, factors_written: 0,
      errors: [`该对象已有运行中的需求预测：${handle.run_id}`],
    };
  }

  const runId = handle.run_id;
  const steps: ForecastStep[] = [];
  let assessment: DemandAssessment | undefined;
  let written: WrittenDemandForecast | undefined;
  let modelVersion = modelDefault;

  const persistImmediateStep = (seq: number, tool: string, label: string, detail: string): ForecastStep => {
    const started = Date.now();
    const step = startDemandForecastStep({ runId, stepSeq: seq, tool, label, detail, sources: SOURCES[tool]!, dbPath });
    const completed = finishDemandForecastStep({ runId, step, status: "完成", detail, durationMs: Date.now() - started, dbPath });
    steps.push(completed);
    return completed;
  };

  const publish = (daily: DailyForecast[]): WrittenDemandForecast => {
    const errors = validateDailyForecast(facts, daily);
    if (errors.length) throw new Error(errors.join("；"));
    const started = Date.now();
    const step = startDemandForecastStep({
      runId, stepSeq: 12, tool: DEMAND_FORECAST_TOOLS[6], label: LABELS[DEMAND_FORECAST_TOOLS[6]]!,
      detail: "正在校验90天连续性并发布", sources: SOURCES[DEMAND_FORECAST_TOOLS[6]]!, dbPath,
    });
    steps.push(step);
    try {
      const output = writeDemandForecastRun({
        facts, assessment: assessment!, daily, steps, trigger: options.trigger, modelVersion,
        runId, finalStepStartedMs: started,
        finalStepCompletedDetail: "90天、六个窗口及五类判断全部通过门禁，已发布",
        dbPath, exportPath,
      });
      steps[steps.length - 1] = output.steps.at(-1)!;
      return output;
    } catch (error) {
      const message = error instanceof Error ? error.message : "需求预测发布失败";
      const failed = finishDemandForecastStep({ runId, step, status: "失败", detail: message, durationMs: Date.now() - started, dbPath });
      steps[steps.length - 1] = failed;
      throw error;
    }
  };

  if (options.fake) {
    try {
      persistImmediateStep(1, DEMAND_FORECAST_TOOLS[0], LABELS[DEMAND_FORECAST_TOOLS[0]]!, `已审计${facts.observable_metrics.history_observed_days}天历史`);
      persistImmediateStep(2, DEMAND_FORECAST_TOOLS[1], LABELS[DEMAND_FORECAST_TOOLS[1]]!, "历史需求影响数据读取完成");
      persistImmediateStep(3, DEMAND_FORECAST_TOOLS[2], LABELS[DEMAND_FORECAST_TOOLS[2]]!, "未来90天运营计划读取完成");
      persistImmediateStep(4, DEMAND_FORECAST_TOOLS[3], LABELS[DEMAND_FORECAST_TOOLS[3]]!, `上架${facts.observable_metrics.days_since_launch}天`);
      assessment = fixtureAssessment(facts);
      persistImmediateStep(5, DEMAND_FORECAST_TOOLS[4], LABELS[DEMAND_FORECAST_TOOLS[4]]!, "五类判断通过契约校验");
      const daily = fixtureDaily(facts, assessment);
      for (const segment of forecastSegments(facts.data_as_of)) {
        persistImmediateStep(
          5 + segment.segment_index,
          DEMAND_FORECAST_TOOLS[5],
          `生成第${segment.segment_index}段逐日预测`,
          `${segment.start_date} 至 ${segment.end_date} 的15天预测通过门禁`,
        );
      }
      written = publish(daily);
      return {
        ok: true, run_id: runId, child_asin: facts.child_asin, model_version: modelVersion,
        steps, daily_written: daily.length, factors_written: assessment.factors.length, errors: [], output: written,
      };
    } catch (error) {
      const message = error instanceof Error ? error.message : "需求预测运行失败";
      failDemandForecastRun(runId, message, dbPath);
      throw error;
    }
  }

  const segments = new Map<number, DailyForecast[]>();
  let requestedSegment = 0;
  const tools = [
    defineTool({
      name: DEMAND_FORECAST_TOOLS[0], label: LABELS[DEMAND_FORECAST_TOOLS[0]]!, description: "读取两年实销与可售库存，只包含客观允许字段。", executionMode: "sequential",
      parameters: Type.Object({}),
      execute: async () => {
        const payload = { child_asin: facts.child_asin, data_as_of: facts.data_as_of, sales_inventory: facts.sales_inventory, observable_metrics: metricSubset(facts, ["history_", "matching_"]) };
        return { content: [{ type: "text" as const, text: JSON.stringify(payload) }], details: payload };
      },
    }),
    defineTool({
      name: DEMAND_FORECAST_TOOLS[1], label: LABELS[DEMAND_FORECAST_TOOLS[1]]!, description: "读取广告、活动、价格与流量历史客观值。", executionMode: "sequential",
      parameters: Type.Object({}),
      execute: async () => {
        const payload = { demand_drivers: facts.demand_drivers, observable_metrics: facts.observable_metrics, factor_evidence: facts.factor_evidence };
        return { content: [{ type: "text" as const, text: JSON.stringify(payload) }], details: payload };
      },
    }),
    defineTool({
      name: DEMAND_FORECAST_TOOLS[2], label: LABELS[DEMAND_FORECAST_TOOLS[2]]!, description: "读取未来90天广告、活动和价格计划，不含预期效果答案。", executionMode: "sequential",
      parameters: Type.Object({}),
      execute: async () => {
        return { content: [{ type: "text" as const, text: JSON.stringify(facts.future_plan) }], details: facts.future_plan };
      },
    }),
    defineTool({
      name: DEMAND_FORECAST_TOOLS[3], label: LABELS[DEMAND_FORECAST_TOOLS[3]]!, description: "读取产品上架日、库存与供给背景，不读取生命周期答案。", executionMode: "sequential",
      parameters: Type.Object({}),
      execute: async () => {
        const payload = { product: facts.product, tenure_supply: facts.tenure_supply, days_since_launch: facts.observable_metrics.days_since_launch };
        return { content: [{ type: "text" as const, text: JSON.stringify(payload) }], details: payload };
      },
    }),
    defineTool({
      name: DEMAND_FORECAST_TOOLS[4], label: LABELS[DEMAND_FORECAST_TOOLS[4]]!, description: "提交五类需求影响判断，数字必须引用客观事实。", executionMode: "sequential",
      parameters: assessmentSchema,
      execute: async (_id, params) => {
        const candidate = { ...params, child_asin: facts.child_asin } as DemandAssessment;
        const errors = validateDemandAssessment(facts, candidate);
        if (errors.length) return { isError: true, content: [{ type: "text" as const, text: JSON.stringify({ ok: false, errors }) }], details: { ok: false, errors } };
        assessment = candidate;
        return { content: [{ type: "text" as const, text: JSON.stringify({ ok: true }) }], details: { ok: true } };
      },
    }),
    defineTool({
      name: DEMAND_FORECAST_TOOLS[5], label: LABELS[DEMAND_FORECAST_TOOLS[5]]!, description: "提交当前15天窗口的逐日P10/P50/P90预测。", executionMode: "sequential",
      parameters: dailySegmentSchema,
      execute: async (_id, params) => {
        if (!assessment) return { isError: true, content: [{ type: "text" as const, text: "请先提交五类需求判断" }] };
        const expected = forecastSegments(facts.data_as_of)[requestedSegment - 1];
        const candidate = params.daily as DailyForecast[];
        const errors = [
          ...(params.segment_index === requestedSegment ? [] : [`当前必须提交第${requestedSegment}段`]),
          ...(expected && params.start_date === expected.start_date && params.end_date === expected.end_date ? [] : ["分段起止日期与当前窗口不一致"]),
          ...validateDailyForecastSegment(facts, requestedSegment, candidate),
        ];
        if (errors.length) return { isError: true, content: [{ type: "text" as const, text: JSON.stringify({ ok: false, errors: errors.slice(0, 20) }) }], details: { ok: false, errors } };
        segments.set(requestedSegment, candidate);
        return { content: [{ type: "text" as const, text: JSON.stringify({ ok: true, segment_index: requestedSegment, rows: candidate.length }) }], details: { ok: true, rows: candidate.length } };
      },
    }),
    defineTool({
      name: DEMAND_FORECAST_TOOLS[6], label: LABELS[DEMAND_FORECAST_TOOLS[6]]!, description: "发布由运行器执行，无需模型调用。", executionMode: "sequential",
      parameters: Type.Object({}),
      execute: async () => ({ isError: true, content: [{ type: "text" as const, text: "发布步骤由运行器执行" }] }),
    }),
  ];

  let session: Awaited<ReturnType<typeof createAgentSession>>["session"] | undefined;
  const runModelStep = async (args: {
    seq: number;
    tool: string;
    label: string;
    loadingDetail: string;
    completedDetail: string;
    prompt: string;
    registered: () => boolean;
  }) => {
    const started = Date.now();
    const trace: DemandToolTrace = { starts: 0, ends: 0, successfulEnds: 0, errors: [], modelErrors: [] };
    const step = startDemandForecastStep({
      runId, stepSeq: args.seq, tool: args.tool, label: args.label,
      detail: args.loadingDetail, sources: SOURCES[args.tool]!, dbPath,
    });
    const unsubscribe = session!.subscribe((event) => {
      if (event.type === "tool_execution_start" && event.toolName === args.tool) trace.starts += 1;
      if (event.type === "tool_execution_end" && event.toolName === args.tool) {
        trace.ends += 1;
        if (event.isError) trace.errors.push(safeDemandToolError(event.result));
        else trace.successfulEnds += 1;
      }
      if (event.type === "message_end" && event.message.role === "assistant") {
        const message = event.message as typeof event.message & { stopReason?: unknown; errorMessage?: unknown };
        if (message.stopReason === "error") trace.modelErrors.push(safeDemandModelError(message.errorMessage));
      }
    });
    try {
      session!.setActiveToolsByName([args.tool]);
      if (!session!.getActiveToolNames().includes(args.tool)) {
        throw new Error(`运行器没有成功开放工具：${args.tool}`);
      }
      await session!.prompt(args.prompt);
      let diagnostic = diagnoseDemandToolTrace(args.tool, trace, args.registered());
      if (diagnostic && trace.modelErrors.length === 0 && trace.successfulEnds === 0 && (trace.starts === 0 || trace.errors.length > 0)) {
        await session!.prompt(
          `上一轮没有完成当前工具步骤：${diagnostic}。现在必须直接调用唯一开放的 ${args.tool} 工具，参数中不要填写 child_asin；不要输出解释文字。`,
        );
        diagnostic = diagnoseDemandToolTrace(args.tool, trace, args.registered());
      }
      if (diagnostic) throw new Error(diagnostic);
      const completed = finishDemandForecastStep({
        runId, step, status: "完成", detail: args.completedDetail,
        durationMs: Date.now() - started, dbPath,
      });
      steps.push(completed);
    } catch (error) {
      const message = error instanceof Error ? error.message : `${args.label}失败`;
      const failed = finishDemandForecastStep({
        runId, step, status: "失败", detail: message,
        durationMs: Date.now() - started, dbPath,
      });
      steps.push(failed);
      failDemandForecastRun(runId, message, dbPath);
      throw error;
    } finally {
      unsubscribe();
    }
  };

  try {
    const agentDir = getAgentDir();
    const settingsManager = SettingsManager.create(ROOT_DIR, agentDir);
    const loader = new DefaultResourceLoader({
      cwd: ROOT_DIR, agentDir, settingsManager, noExtensions: true, noPromptTemplates: true,
      noThemes: true, noContextFiles: true, systemPromptOverride: systemPrompt,
      appendSystemPromptOverride: () => [],
    });
    await loader.reload();
    const created = await createAgentSession({
      cwd: ROOT_DIR, agentDir, modelRuntime: await ModelRuntime.create(), thinkingLevel: "low",
      tools: [...DEMAND_FORECAST_TOOLS], customTools: tools, resourceLoader: loader,
      sessionManager: SessionManager.inMemory(ROOT_DIR), settingsManager,
    });
    session = created.session;
    if (session.model) modelVersion = `${session.model.provider}/${session.model.id}`;
    updateDemandForecastRunModel(runId, modelVersion, dbPath);

    const factPrompts = [
      `调用当前工具读取 ${facts.child_asin} 的历史销量与缺货事实，工具返回后结束本轮。`,
      "调用当前工具读取历史广告、活动、价格与流量事实，工具返回后结束本轮。",
      "调用当前工具读取未来90天运营计划，工具返回后结束本轮。",
      "调用当前工具读取上架时长与供给背景，工具返回后结束本轮。",
    ];
    const factDetails = [
      `已审计${facts.observable_metrics.history_observed_days}天历史`,
      "历史需求影响数据读取完成",
      "未来90天运营计划读取完成",
      `上架${facts.observable_metrics.days_since_launch}天`,
    ];
    for (let index = 0; index < 4; index += 1) {
      const tool = DEMAND_FORECAST_TOOLS[index]!;
      await runModelStep({
        seq: index + 1, tool, label: LABELS[tool]!, loadingDetail: `${LABELS[tool]}中`,
        completedDetail: factDetails[index]!, prompt: factPrompts[index]!,
        registered: () => true,
      });
    }

    await runModelStep({
      seq: 5, tool: DEMAND_FORECAST_TOOLS[4], label: LABELS[DEMAND_FORECAST_TOOLS[4]]!,
      loadingDetail: "正在依据四组事实形成五类判断", completedDetail: "五类判断通过契约校验",
      prompt: "根据前四轮事实调用当前工具提交五类需求判断；不要输出解释文字。",
      registered: () => Boolean(assessment),
    });

    const plan = (facts.future_plan.days ?? []) as Array<Record<string, unknown>>;
    for (const segment of forecastSegments(facts.data_as_of)) {
      requestedSegment = segment.segment_index;
      const planSlice = plan.slice(segment.start_day - 1, segment.end_day);
      await runModelStep({
        seq: 5 + segment.segment_index,
        tool: DEMAND_FORECAST_TOOLS[5],
        label: `生成第${segment.segment_index}段逐日预测`,
        loadingDetail: `正在预测 ${segment.start_date} 至 ${segment.end_date}`,
        completedDetail: `${segment.start_date} 至 ${segment.end_date} 的15天预测通过门禁`,
        prompt: `调用当前工具直接提交第${segment.segment_index}段真实逐日预测：${segment.start_date} 至 ${segment.end_date}，必须正好15行。当前窗口未来计划如下：${JSON.stringify(planSlice)}。不要给形状参数，不要输出解释文字。`,
        registered: () => segments.has(segment.segment_index),
      });
    }

    const daily = Array.from({ length: FORECAST_SEGMENT_COUNT }, (_, index) => segments.get(index + 1) ?? []).flat();
    written = publish(daily);
    return {
      ok: true, run_id: runId, child_asin: facts.child_asin, model_version: modelVersion,
      steps, daily_written: daily.length, factors_written: assessment!.factors.length, errors: [], output: written,
    };
  } catch (error) {
    const message = error instanceof Error ? error.message : "需求预测运行失败";
    failDemandForecastRun(runId, message, dbPath);
    throw error;
  } finally {
    session?.dispose();
  }
}
