import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

export const ROOT_DIR = resolve(dirname(fileURLToPath(import.meta.url)), "..");
export const WEB_DIR = resolve(ROOT_DIR, "web");
export const SKILL_DIR = resolve(ROOT_DIR, "skills", "forecast-child-90d");
export const DATASET_PATH = resolve(
  ROOT_DIR,
  "..",
  "02-产品销售库存模块",
  "02-数据构建",
  "v0.3.0",
  "bamboocool_product_sales_inventory_v0.3.0.sqlite",
);

export const HOST = "127.0.0.1";
export const PORT = Number(process.env.BAMBOO_AGENT_PORT || 18812);
export const SCENARIO_ID = "forecast-child-sales-inventory-90d";
export const SESSION_TTL_MS = 30 * 60 * 1000;
export const MAX_SESSIONS = 10;
export const MAX_TOOL_CALLS = 12;
export const RUN_TIMEOUT_MS = 180_000;
export const MAX_MESSAGE_LENGTH = 2_000;
