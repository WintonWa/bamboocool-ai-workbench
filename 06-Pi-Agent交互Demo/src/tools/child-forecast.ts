import { defineTool } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import type { DemoRepository } from "../database.ts";
import { toolFailure, toolSuccess } from "./result.ts";

const childParameter = Type.Object({
  child_asin: Type.String({ description: "门禁返回的 analysis_child_asin" }),
});

function asin(value: string): string {
  return value.trim().toUpperCase();
}

export function createChildForecastTools(repository: DemoRepository) {
  return [
    defineTool({
      name: "route_demo_child_asin",
      label: "执行演示门禁",
      description: "将用户选中的任意子 ASIN 显式路由到五个完整黄金样本之一。后续工具必须使用返回的 analysisChildAsin。",
      promptSnippet: "先执行子 ASIN 演示路由，并向用户透明说明是否发生映射",
      executionMode: "sequential",
      parameters: Type.Object({
        requested_child_asin: Type.String({ description: "用户选择的 Amazon 子 ASIN" }),
      }),
      execute: async (_toolCallId, params) => {
        const route = repository.routeDemoChildAsin(asin(params.requested_child_asin));
        if (!route) {
          return toolFailure("not_found", "未找到该子 ASIN 的演示路由", {
            availableChildAsins: repository.listChildren().slice(0, 20).map((item) => item.childAsin),
          });
        }
        return toolSuccess({ ok: true, route });
      },
    }),
    defineTool({
      name: "get_child_product_context",
      label: "确认子 ASIN 与生命周期",
      description: "读取分析子 ASIN 的产品、父体、尺码、颜色、生命周期和演示画像。",
      promptSnippet: "确认分析对象的商品上下文",
      executionMode: "sequential",
      parameters: childParameter,
      execute: async (_toolCallId, params) => {
        const context = repository.getChildProductContext(asin(params.child_asin));
        return context ? toolSuccess({ ok: true, context }) : toolFailure("not_found", "分析子 ASIN 不属于黄金样本");
      },
    }),
    defineTool({
      name: "audit_child_daily_history",
      label: "审计 730 天历史",
      description: "检查分析子 ASIN 730 天逐日销量、缺失、缺货、促销、广告与异常标记。",
      promptSnippet: "先审计历史数据是否可以作为预测基础",
      executionMode: "sequential",
      parameters: childParameter,
      execute: async (_toolCallId, params) => {
        const audit = repository.auditChildDailyHistory(asin(params.child_asin));
        return audit ? toolSuccess({ ok: true, audit }) : toolFailure("not_found", "没有找到逐日历史");
      },
    }),
    defineTool({
      name: "reconstruct_child_demand",
      label: "还原真实需求",
      description: "根据缺货截断和异常标记，把观测销量还原为可用于预测的需求序列。",
      promptSnippet: "校正缺货和异常造成的需求低估",
      executionMode: "sequential",
      parameters: childParameter,
      execute: async (_toolCallId, params) => {
        const reconstruction = repository.reconstructChildDemand(asin(params.child_asin));
        return reconstruction ? toolSuccess({ ok: true, reconstruction }) : toolFailure("not_found", "没有找到需求特征");
      },
    }),
    defineTool({
      name: "estimate_demand_drivers",
      label: "评估需求影响项",
      description: "比较历史与未来的广告、价格、促销、季节性和生命周期影响。",
      promptSnippet: "把未来经营计划转成可解释的需求影响系数",
      executionMode: "sequential",
      parameters: childParameter,
      execute: async (_toolCallId, params) => {
        const drivers = repository.estimateDemandDrivers(asin(params.child_asin));
        return drivers ? toolSuccess({ ok: true, drivers }) : toolFailure("not_found", "没有找到需求影响项");
      },
    }),
    defineTool({
      name: "forecast_child_sales_daily",
      label: "预测未来 90 天销量",
      description: "读取三模型滚动验证后选出的逐日 P10/P50/P90 预测和模型误差。",
      promptSnippet: "生成并汇总子 ASIN 未来90天逐日概率预测",
      executionMode: "sequential",
      parameters: childParameter,
      execute: async (_toolCallId, params) => {
        const forecast = repository.forecastChildSalesDaily(asin(params.child_asin));
        return forecast ? toolSuccess({ ok: true, forecast }) : toolFailure("data_gate_failed", "该子 ASIN 没有完整90天预测");
      },
    }),
    defineTool({
      name: "get_child_inventory_supply",
      label: "读取库存与在途",
      description: "读取当前各仓库存、补货策略以及未来已计划的供给事件。",
      promptSnippet: "建立库存推演的起点和未来供给表",
      executionMode: "sequential",
      parameters: childParameter,
      execute: async (_toolCallId, params) => {
        const supply = repository.getChildInventorySupply(asin(params.child_asin));
        return supply ? toolSuccess({ ok: true, supply }) : toolFailure("not_found", "没有找到库存与供给数据");
      },
    }),
    defineTool({
      name: "project_child_inventory_daily",
      label: "推演三种库存场景",
      description: "基于逐日需求与供给，读取基准、压力、改善三种90天逐日库存投影。",
      promptSnippet: "判断何时跌破安全库存、何时缺货以及潜在损失",
      executionMode: "sequential",
      parameters: childParameter,
      execute: async (_toolCallId, params) => {
        const projection = repository.projectChildInventoryDaily(asin(params.child_asin));
        return projection ? toolSuccess({ ok: true, projection }) : toolFailure("data_gate_failed", "库存投影不完整");
      },
    }),
    defineTool({
      name: "recommend_child_replenishment",
      label: "形成补货建议",
      description: "读取动态安全库存、最晚下单日、建议补货量以及空海运拆分。",
      promptSnippet: "将预测与库存风险转成可执行的补货建议",
      executionMode: "sequential",
      parameters: childParameter,
      execute: async (_toolCallId, params) => {
        const decision = repository.recommendChildReplenishment(asin(params.child_asin));
        return decision ? toolSuccess({ ok: true, decision }) : toolFailure("not_found", "没有找到补货决策");
      },
    }),
  ];
}
