import type { DemoRepository } from "../database.ts";
import { createChildForecastTools } from "./child-forecast.ts";

export const ALLOWED_TOOL_NAMES = [
  "route_demo_child_asin",
  "get_child_product_context",
  "audit_child_daily_history",
  "reconstruct_child_demand",
  "estimate_demand_drivers",
  "forecast_child_sales_daily",
  "get_child_inventory_supply",
  "project_child_inventory_daily",
  "recommend_child_replenishment",
] as const;

export function createBusinessTools(repository: DemoRepository) {
  return createChildForecastTools(repository);
}
