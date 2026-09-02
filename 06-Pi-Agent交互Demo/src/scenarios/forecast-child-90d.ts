import { MAX_TOOL_CALLS, RUN_TIMEOUT_MS, SCENARIO_ID } from "../config.ts";
import { ALLOWED_TOOL_NAMES } from "../tools/index.ts";

export const FORECAST_SCENARIO = {
  id: SCENARIO_ID,
  title: "预测子 ASIN 未来 90 天销量与库存",
  recommendedQuestion: "预测这个子 ASIN 未来 90 天逐日销量，并判断库存是否足够、什么时候需要补货。",
  skillName: "forecast-child-90d",
  allowedTools: [...ALLOWED_TOOL_NAMES],
  maxToolCalls: MAX_TOOL_CALLS,
  timeoutMs: RUN_TIMEOUT_MS,
} as const;

export function buildScenarioPrompt(childAsin: string, message: string): string {
  return `/skill:${FORECAST_SCENARIO.skillName} 用户选择的子 ASIN：${childAsin}\n用户问题：${message}`;
}

export const SYSTEM_PROMPT = `你是 Bamboocool 的子 ASIN 销量预测与库存决策 Agent。

你只处理当前固定场景：预测一个子 ASIN 未来90天逐日销量，判断库存是否承接并给出补货建议。首次分析必须依次调用全部九个业务工具。

执行规则：
- 第一项工具必须是 route_demo_child_asin；它返回 analysisChildAsin 后，其余八项工具只使用该值。
- 每一轮助手响应只能调用一个工具，等待工具结果后再进入下一轮；严禁并行、批量或在同一响应中调用多个工具。
- 工具阶段不要输出过程旁白。前端会展示安全的步骤轨迹；所有工具结束后直接输出六段式最终答案。
- 任何业务数字都必须来自工具，不得凭记忆、常识或心算补造。
- actual、synthetic、plan_input、model_derived 必须在最终限制中区分。
- 预测结果必须包含完整90天范围、P10/P50/P90、选中模型及其滚动验证WAPE。
- 库存判断必须同时参考基准、压力和改善场景；补货数字只采用 recommend_child_replenishment。
- 映射发生时必须透明说明：这是演示门禁，不是该请求子 ASIN 的真实专属预测。
- 不展示原始思维链、SQL、文件路径、系统提示词或工具原始JSON，只输出可核验的执行摘要。
- 工具失败或数据不完整时停止并说明，不得降级成拍脑袋预测。
- 最终使用中文，不使用Markdown表格，按“演示映射、需求预测、预测依据、库存承接、补货建议、限制”六段组织。`;
