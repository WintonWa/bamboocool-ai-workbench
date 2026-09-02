import type { AgentSessionEvent } from "@earendil-works/pi-coding-agent";
import type { StreamEvent } from "./types.ts";

const TOOL_LABELS: Record<string, string> = {
  route_demo_child_asin: "执行演示门禁",
  get_child_product_context: "确认子 ASIN 与生命周期",
  audit_child_daily_history: "审计 730 天历史",
  reconstruct_child_demand: "还原真实需求",
  estimate_demand_drivers: "评估需求影响项",
  forecast_child_sales_daily: "预测未来 90 天销量",
  get_child_inventory_supply: "读取库存与在途",
  project_child_inventory_daily: "推演三种库存场景",
  recommend_child_replenishment: "形成补货建议",
};

function number(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value) ? Math.round(value).toLocaleString("zh-CN") : "—";
}

function resultDetails(result: unknown): Record<string, any> {
  if (!result || typeof result !== "object") return {};
  const details = (result as { details?: unknown }).details;
  return details && typeof details === "object" ? details as Record<string, any> : {};
}

function completedSummary(toolName: string, result: unknown, isError: boolean): string {
  const details = resultDetails(result);
  if (isError) return typeof details.message === "string" ? details.message : "工具执行失败";
  if (toolName === "route_demo_child_asin" && details.route) {
    return details.route.wasMapped
      ? `已映射至 ${details.route.analysisChildAsin}（${details.route.profileName}）`
      : `直接使用黄金样本 ${details.route.analysisChildAsin}（${details.route.profileName}）`;
  }
  if (toolName === "get_child_product_context" && details.context) {
    return `已确认 ${details.context.styleName} / ${details.context.size}，生命周期 ${details.context.lifecycleStage}`;
  }
  if (toolName === "audit_child_daily_history" && details.audit) {
    return `已审计 ${details.audit.observedDays} 天，缺货 ${details.audit.stockoutDays} 天，异常 ${details.audit.abnormalDays} 天`;
  }
  if (toolName === "reconstruct_child_demand" && details.reconstruction) {
    return `还原需求 ${number(details.reconstruction.estimatedDemandUnits)} 件，校正 ${number(details.reconstruction.recoveredDemandUnits)} 件`;
  }
  if (toolName === "estimate_demand_drivers" && details.drivers) {
    return `未来广告系数 ${details.drivers.future.advertisingEffect}，促销排期 ${details.drivers.future.plannedPromotionDays} 天`;
  }
  if (toolName === "forecast_child_sales_daily" && details.forecast) {
    return `P50 ${number(details.forecast.p50Units)} 件，区间 ${number(details.forecast.p10Units)}–${number(details.forecast.p90Units)} 件`;
  }
  if (toolName === "get_child_inventory_supply" && details.supply) {
    return `截至 ${details.supply.asOfDate}，FBA可售 ${number(details.supply.fbaSellable)} 件，供给事件 ${details.supply.futureSupplyEvents.length} 个`;
  }
  if (toolName === "project_child_inventory_daily" && details.projection) {
    const base = details.projection.scenarios.find((item: any) => item.scenario === "base");
    return `基准场景风险 ${base?.riskStatus ?? "—"}，缺货日 ${base?.stockoutDate ?? "—"}`;
  }
  if (toolName === "recommend_child_replenishment" && details.decision) {
    return `建议补货 ${number(details.decision.suggestedReplenishmentQty)} 件，最晚下单日 ${details.decision.latestOrderDate}`;
  }
  return "执行完成";
}

export class EventAdapter {
  private readonly startedAt = new Map<string, number>();
  private readonly runId: string;

  constructor(runId: string) {
    this.runId = runId;
  }

  adapt(event: AgentSessionEvent): StreamEvent | null {
    if (event.type === "message_update" && event.assistantMessageEvent.type === "text_delta") {
      return { type: "answer.delta", runId: this.runId, delta: event.assistantMessageEvent.delta };
    }
    if (event.type === "tool_execution_start") {
      this.startedAt.set(event.toolCallId, Date.now());
      return {
        type: "step.started",
        runId: this.runId,
        stepId: event.toolCallId,
        tool: event.toolName,
        label: TOOL_LABELS[event.toolName] ?? "执行业务工具",
      };
    }
    if (event.type === "tool_execution_end") {
      const started = this.startedAt.get(event.toolCallId);
      this.startedAt.delete(event.toolCallId);
      return {
        type: event.isError ? "step.failed" : "step.completed",
        runId: this.runId,
        stepId: event.toolCallId,
        tool: event.toolName,
        label: TOOL_LABELS[event.toolName] ?? "执行业务工具",
        summary: completedSummary(event.toolName, event.result, event.isError),
        durationMs: started ? Date.now() - started : undefined,
      };
    }
    return null;
  }
}

export function publicError(error: unknown): { code: string; message: string } {
  const raw = error instanceof Error ? error.message : String(error);
  if (/auth|credential|api.?key|login/i.test(raw)) {
    return { code: "PI_AUTH_UNAVAILABLE", message: "Pi 模型认证不可用，请先在本机 Pi 中完成登录或密钥配置。" };
  }
  if (/model|provider/i.test(raw)) {
    return { code: "PI_MODEL_UNAVAILABLE", message: "Pi 当前模型不可用，请检查本机默认模型配置。" };
  }
  if (/timeout/i.test(raw)) return { code: "RUN_TIMEOUT", message: "Agent 运行超时，可以重新运行。" };
  return { code: "AGENT_RUN_FAILED", message: "Agent 运行失败，请检查本地服务日志后重试。" };
}
