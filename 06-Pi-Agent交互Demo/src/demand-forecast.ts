import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { DatabaseSync } from "node:sqlite";
import { DATASET_PATH } from "./config.ts";

const SRC_DIR = dirname(fileURLToPath(import.meta.url));
export const PROJECT_ROOT = resolve(SRC_DIR, "..");
export const WORKBENCH_ROOT = resolve(PROJECT_ROOT, "..", "09-工作台");
export const DEFAULT_DEMAND_FORECAST_DB = resolve(WORKBENCH_ROOT, "modules/inventory/derived/forecast_agent.sqlite");
export const DEFAULT_DEMAND_FORECAST_JSON = resolve(WORKBENCH_ROOT, "modules/inventory/derived/forecast_agent_latest.json");

export const DATA_AS_OF = "2026-08-03";
export const HORIZON_DAYS = 90;
export const FORECAST_SEGMENT_DAYS = 15;
export const FORECAST_SEGMENT_COUNT = HORIZON_DAYS / FORECAST_SEGMENT_DAYS;
export const FORECAST_TOTAL_STEPS = 4 + 1 + FORECAST_SEGMENT_COUNT + 1;
export const METHOD_VERSION = "demand-forecast-agent-segmented-v1";
export const PROMPT_VERSION = "demand-forecast-segmented-15d-v1";
export const CONTRACT_VERSION = "demand-forecast-agent-v1";
export const TRIGGERS = ["manual", "weekly", "priority"] as const;
export const FACTORS = ["stockout_distortion", "promotion", "lifecycle", "advertising", "seasonality"] as const;

export const FACTOR_STATES: Record<(typeof FACTORS)[number], readonly string[]> = {
  stockout_distortion: ["无扭曲", "轻度扭曲", "重度扭曲"],
  promotion: ["无活动", "有活动且已回落", "有活动仍在影响"],
  lifecycle: ["爬坡", "平稳", "衰退"],
  advertising: ["无投放", "平稳", "加大", "减少"],
  seasonality: ["不明显", "旺季", "淡季"],
};

export const FORBIDDEN_INPUT_KEYS = [
  "fact_child_forecast_daily", "feature_child_demand_daily", "fact_child_forecast_evaluation",
  "potential_demand_units", "lost_sales_units", "coverage_days", "lifecycle_stage", "change_reason",
  "confidence_score", "preset_uplift", "performance_index", "expected_effect_ratio", "quality_status",
  "value_origin", "method_version", "provenance", "demand_quality_flag",
] as const;

export type JsonScalar = string | number | boolean | null;
export type ForecastTrigger = (typeof TRIGGERS)[number];
export type ForecastFactor = (typeof FACTORS)[number];
export type ForecastFactorInput = {
  factor: ForecastFactor;
  ord: number;
  state: string;
  impact_pct: number | null;
  because: string;
  numbers: Record<string, number>;
};
export type DemandAssessment = {
  child_asin: string;
  confidence: "高" | "中" | "低";
  confidence_reason: string;
  judgment_summary: string;
  factors: ForecastFactorInput[];
};
export type DailyForecast = {
  forecast_date: string;
  p10_units: number;
  p50_units: number;
  p90_units: number;
  baseline_units: number | null;
};
export type ForecastStep = {
  step_seq: number;
  tool: string;
  label: string;
  detail: string;
  status: "加载中" | "完成" | "失败";
  duration_ms: number | null;
  sources: string[];
  started_at: string | null;
  completed_at: string | null;
};
export type ForecastRunHandle = {
  run_id: string;
  reused: boolean;
  db_path: string;
};
export type DemandForecastRunStatus = {
  ok: boolean;
  run: null | {
    run_id: string;
    child_asin: string;
    status: "加载中" | "完成" | "失败";
    created_at: string;
    completed_at: string | null;
    model_version: string | null;
    current_step: number;
    total_steps: number;
    error: string | null;
  };
  steps: Array<Omit<ForecastStep, "tool" | "step_seq"> & { seq: number }>;
  error: string | null;
};
export type DemandForecastFacts = {
  child_asin: string;
  data_as_of: string;
  product: Record<string, JsonScalar>;
  sales_inventory: Record<string, unknown>;
  demand_drivers: Record<string, unknown>;
  future_plan: Record<string, unknown>;
  tenure_supply: Record<string, unknown>;
  observable_metrics: Record<string, number>;
  factor_evidence: Array<{ factor: ForecastFactor; required_number_keys: string[] }>;
};
export type WrittenDemandForecast = {
  contract_version: string;
  run: Record<string, JsonScalar>;
  daily: DailyForecast[];
  assessment: DemandAssessment;
  steps: ForecastStep[];
  db_path: string;
  export_path: string;
};

type Row = Record<string, string | number | null>;

function n(value: unknown): number {
  const parsed = Number(value ?? 0);
  return Number.isFinite(parsed) ? parsed : 0;
}

function round(value: number, digits = 3): number {
  const scale = 10 ** digits;
  return Math.round(value * scale) / scale;
}

function isoDateOffset(iso: string, days: number): string {
  const date = new Date(`${iso}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

function shanghaiNow(now = new Date()): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23",
  }).formatToParts(now);
  const p = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}:${p.second}+08:00`;
}

function rows(db: DatabaseSync, sql: string, ...params: (string | number)[]): Row[] {
  return db.prepare(sql).all(...params) as Row[];
}

function row(db: DatabaseSync, sql: string, ...params: (string | number)[]): Row | undefined {
  return db.prepare(sql).get(...params) as Row | undefined;
}

function windowMetric(history: Row[], fromExclusive: string) {
  const selected = history.filter((item) => String(item.date) > fromExclusive);
  const inStock = selected.filter((item) => n(item.stockout_flag) === 0);
  return {
    days: selected.length,
    units: selected.reduce((sum, item) => sum + n(item.units_sold), 0),
    stockout_days: selected.length - inStock.length,
    in_stock_daily_avg: round(inStock.reduce((sum, item) => sum + n(item.units_sold), 0) / Math.max(inStock.length, 1)),
  };
}

function assertNoForbidden(value: unknown): void {
  const text = JSON.stringify(value);
  const found = FORBIDDEN_INPUT_KEYS.filter((key) => text.includes(`"${key}"`));
  if (found.length) throw new Error(`事实载荷包含禁读字段：${found.join("、")}`);
}

export function loadDemandForecastFacts(childAsin: string, datasetPath = DATASET_PATH): DemandForecastFacts {
  const asin = childAsin.trim().toUpperCase();
  const db = new DatabaseSync(datasetPath, { readOnly: true });
  db.exec("PRAGMA query_only = ON");
  try {
    const product = row(db, `SELECT child_asin, parent_asin, product_name, style_name, category,
      style_no, colorway, size FROM dim_product_child WHERE child_asin = ?`, asin);
    if (!product) throw new Error(`子 ASIN ${asin} 不在产品脊椎中`);

    const history = rows(db, `SELECT s.date, s.units_sold, s.orders, s.average_selling_price,
      i.opening_fba_sellable, i.closing_fba_sellable, i.received_units, i.stockout_flag
      FROM fact_child_sales_daily s
      JOIN fact_child_inventory_daily i ON i.child_asin=s.child_asin AND i.date=s.date
      WHERE s.child_asin=? ORDER BY s.date`, asin);
    const monthly = rows(db, `SELECT substr(s.date,1,7) AS month,
      SUM(s.units_sold) AS units_sold, SUM(s.orders) AS orders,
      ROUND(AVG(s.average_selling_price),2) AS average_selling_price,
      SUM(CASE WHEN i.stockout_flag=1 THEN 1 ELSE 0 END) AS stockout_days,
      COUNT(*) AS observed_days
      FROM fact_child_sales_daily s
      JOIN fact_child_inventory_daily i ON i.child_asin=s.child_asin AND i.date=s.date
      WHERE s.child_asin=? GROUP BY substr(s.date,1,7) ORDER BY month`, asin);
    const weekday = rows(db, `SELECT CAST(strftime('%w',s.date) AS INTEGER) AS weekday,
      COUNT(*) AS in_stock_days, SUM(s.units_sold) AS units_sold,
      ROUND(AVG(s.units_sold),3) AS daily_avg
      FROM fact_child_sales_daily s
      JOIN fact_child_inventory_daily i ON i.child_asin=s.child_asin AND i.date=s.date
      WHERE s.child_asin=? AND i.stockout_flag=0 GROUP BY weekday ORDER BY weekday`, asin);
    const windows = {
      d30: windowMetric(history, isoDateOffset(DATA_AS_OF, -30)),
      d60: windowMetric(history, isoDateOffset(DATA_AS_OF, -60)),
      d90: windowMetric(history, isoDateOffset(DATA_AS_OF, -90)),
      d180: windowMetric(history, isoDateOffset(DATA_AS_OF, -180)),
    };
    const priorMatch = history.filter((item) => String(item.date) >= "2025-08-04" && String(item.date) <= "2025-11-01" && n(item.stockout_flag) === 0);

    const driverMonthly = rows(db, `SELECT substr(s.date,1,7) AS month,
      SUM(s.units_sold) AS units_sold, ROUND(SUM(a.ad_spend),2) AS ad_spend,
      SUM(a.impressions) AS impressions, SUM(a.clicks) AS clicks, SUM(a.ad_orders) AS ad_orders,
      ROUND(SUM(a.ad_sales),2) AS ad_sales, SUM(t.sessions) AS sessions, SUM(t.buyers) AS buyers,
      ROUND(AVG(p.selling_price),2) AS average_selling_price,
      SUM(CASE WHEN pr.promotion_id IS NOT NULL AND pr.promotion_status <> 'none' THEN 1 ELSE 0 END) AS promotion_days
      FROM fact_child_sales_daily s
      JOIN fact_child_advertising_daily a ON a.child_asin=s.child_asin AND a.date=s.date
      JOIN fact_child_traffic_daily t ON t.child_asin=s.child_asin AND t.date=s.date
      JOIN fact_child_price_daily p ON p.child_asin=s.child_asin AND p.date=s.date
      JOIN fact_child_promotion_daily pr ON pr.child_asin=s.child_asin AND pr.date=s.date
      WHERE s.child_asin=? GROUP BY substr(s.date,1,7) ORDER BY month`, asin);
    const driverDaily = rows(db, `SELECT s.date, s.units_sold,
      a.ad_budget, a.ad_spend, a.impressions, a.clicks, a.cpc, a.ad_orders, a.ad_sales,
      a.ctr, a.ad_cvr, a.acos, a.acoas,
      pr.promotion_id, pr.promotion_type, pr.promotion_status, pr.discount_rate, pr.is_planned,
      p.list_price, p.selling_price, p.coupon_amount, p.discount_rate AS price_discount_rate, p.price_event,
      t.sessions, t.page_views, t.buyers, t.cvr
      FROM fact_child_sales_daily s
      JOIN fact_child_advertising_daily a ON a.child_asin=s.child_asin AND a.date=s.date
      JOIN fact_child_promotion_daily pr ON pr.child_asin=s.child_asin AND pr.date=s.date
      JOIN fact_child_price_daily p ON p.child_asin=s.child_asin AND p.date=s.date
      JOIN fact_child_traffic_daily t ON t.child_asin=s.child_asin AND t.date=s.date
      WHERE s.child_asin=? AND s.date>? ORDER BY s.date`, asin, isoDateOffset(DATA_AS_OF, -180));

    const futurePlan = rows(db, `SELECT a.date,
      a.planned_budget, a.planned_spend, a.planned_impressions, a.planned_clicks,
      pr.promotion_id, pr.promotion_type, pr.promotion_status, pr.planned_discount_rate,
      p.planned_list_price, p.planned_selling_price, p.planned_coupon_amount, p.planned_discount_rate AS price_discount_rate
      FROM plan_child_advertising_daily a
      JOIN plan_child_promotion_daily pr ON pr.child_asin=a.child_asin AND pr.date=a.date
      JOIN plan_child_price_daily p ON p.child_asin=a.child_asin AND p.date=a.date
      WHERE a.child_asin=? ORDER BY a.date`, asin);
    if (futurePlan.length !== HORIZON_DAYS) throw new Error(`未来运营计划不是 ${HORIZON_DAYS} 天`);

    const launch = row(db, `SELECT MIN(effective_start) AS launch_date
      FROM dim_child_lifecycle_history WHERE child_asin=?`, asin);
    const inventory = row(db, `SELECT snapshot_date, fba_inventory, fba_sellable, fba_reserved,
      fba_receiving, fba_inbound, overseas_available, overseas_inbound, local_available,
      purchase_plan_qty, total_inventory FROM fact_inventory_snapshot WHERE child_asin=?`, asin) ?? {};
    const policy = row(db, `SELECT effective_start, effective_end, service_level, base_safety_days,
      purchase_lead_days, quality_check_days, transport_days, fba_receiving_days,
      target_coverage_days, preferred_transport_mode
      FROM config_child_inventory_policy WHERE child_asin=?`, asin) ?? {};
    const supply = rows(db, `SELECT plan_event_id, planned_units, source_location, destination_location,
      transport_mode, eta_earliest, eta_latest, event_status
      FROM plan_child_supply_event WHERE child_asin=? ORDER BY eta_earliest`, asin);

    const recent30Drivers = driverDaily.filter((item) => String(item.date) > isoDateOffset(DATA_AS_OF, -30));
    const promoHistory = driverDaily.filter((item) => item.promotion_id !== null && String(item.promotion_status) !== "none");
    const noPromoHistory = driverDaily.filter((item) => item.promotion_id === null || String(item.promotion_status) === "none");
    const future30 = futurePlan.slice(0, 30);
    const futurePromo = futurePlan.filter((item) => item.promotion_id !== null && String(item.promotion_status) !== "none");
    const metrics: Record<string, number> = {
      history_observed_days: history.length,
      history_stockout_days: history.filter((item) => n(item.stockout_flag) === 1).length,
      history_stockout_days_90d: windows.d90.stockout_days,
      history_instock_daily_avg_30d: windows.d30.in_stock_daily_avg,
      history_instock_daily_avg_90d: windows.d90.in_stock_daily_avg,
      history_instock_daily_avg_180d: windows.d180.in_stock_daily_avg,
      matching_last_year_daily_avg: round(priorMatch.reduce((sum, item) => sum + n(item.units_sold), 0) / Math.max(priorMatch.length, 1)),
      days_since_launch: Math.max(0, Math.round((Date.parse(`${DATA_AS_OF}T00:00:00Z`) - Date.parse(`${launch?.launch_date ?? DATA_AS_OF}T00:00:00Z`)) / 86_400_000)),
      history_ad_spend_daily_30d: round(recent30Drivers.reduce((sum, item) => sum + n(item.ad_spend), 0) / Math.max(recent30Drivers.length, 1)),
      history_ad_sales_daily_30d: round(recent30Drivers.reduce((sum, item) => sum + n(item.ad_sales), 0) / Math.max(recent30Drivers.length, 1)),
      future_ad_spend_daily_30d: round(future30.reduce((sum, item) => sum + n(item.planned_spend), 0) / Math.max(future30.length, 1)),
      history_promotion_days_180d: promoHistory.length,
      history_promotion_daily_avg_180d: round(promoHistory.reduce((sum, item) => sum + n(item.units_sold), 0) / Math.max(promoHistory.length, 1)),
      history_nonpromotion_daily_avg_180d: round(noPromoHistory.reduce((sum, item) => sum + n(item.units_sold), 0) / Math.max(noPromoHistory.length, 1)),
      future_promotion_days: futurePromo.length,
      future_promotion_days_30d: future30.filter((item) => item.promotion_id !== null && String(item.promotion_status) !== "none").length,
    };

    const facts: DemandForecastFacts = {
      child_asin: asin,
      data_as_of: DATA_AS_OF,
      product,
      sales_inventory: { monthly, weekday, windows, recent_daily: history.slice(-120), prior_year_matching_window_days: priorMatch.length },
      demand_drivers: { monthly: driverMonthly, recent_daily: driverDaily },
      future_plan: { days: futurePlan },
      tenure_supply: { launch_date: launch?.launch_date ?? null, inventory, policy, supply },
      observable_metrics: metrics,
      factor_evidence: [
        { factor: "stockout_distortion", required_number_keys: ["history_observed_days", "history_stockout_days", "history_stockout_days_90d", "history_instock_daily_avg_90d"] },
        { factor: "promotion", required_number_keys: ["history_promotion_days_180d", "history_promotion_daily_avg_180d", "history_nonpromotion_daily_avg_180d", "future_promotion_days"] },
        { factor: "lifecycle", required_number_keys: ["days_since_launch", "history_instock_daily_avg_30d", "history_instock_daily_avg_90d", "history_instock_daily_avg_180d"] },
        { factor: "advertising", required_number_keys: ["history_ad_spend_daily_30d", "history_ad_sales_daily_30d", "future_ad_spend_daily_30d"] },
        { factor: "seasonality", required_number_keys: ["matching_last_year_daily_avg", "history_instock_daily_avg_90d"] },
      ],
    };
    assertNoForbidden(facts);
    return facts;
  } finally {
    db.close();
  }
}

function oneSentence(value: string, max: number): boolean {
  const text = value.trim();
  return Boolean(text) && text.length <= max && !text.includes("\n") && (text.match(/[。！？]/g)?.length ?? 0) <= 1;
}

export function validateDemandAssessment(facts: DemandForecastFacts, assessment: DemandAssessment): string[] {
  const errors: string[] = [];
  if (assessment.child_asin !== facts.child_asin) errors.push("child_asin 与事实不一致");
  if (!["高", "中", "低"].includes(assessment.confidence)) errors.push("confidence 必须是高/中/低");
  if (!oneSentence(assessment.confidence_reason, 100)) errors.push("confidence_reason 必须是100字内的一句话");
  if (!oneSentence(assessment.judgment_summary, 120)) errors.push("judgment_summary 必须是120字内的一句话");
  if (assessment.factors.length !== FACTORS.length) errors.push("必须正好提交五项影响判断");
  const seen = new Set<string>();
  const evidence = new Map(facts.factor_evidence.map((item) => [item.factor, item]));
  for (const factor of assessment.factors) {
    if (!FACTORS.includes(factor.factor)) { errors.push(`未知 factor：${factor.factor}`); continue; }
    if (seen.has(factor.factor)) errors.push(`factor 重复：${factor.factor}`);
    seen.add(factor.factor);
    if (!FACTOR_STATES[factor.factor].includes(factor.state)) errors.push(`${factor.factor}.state 不在词表内`);
    if (!Number.isInteger(factor.ord) || factor.ord < 1 || factor.ord > 5) errors.push(`${factor.factor}.ord 非法`);
    if (factor.impact_pct !== null && (!Number.isFinite(factor.impact_pct) || factor.impact_pct < -1 || factor.impact_pct > 1)) errors.push(`${factor.factor}.impact_pct 超范围`);
    if (!oneSentence(factor.because, 180)) errors.push(`${factor.factor}.because 必须是180字内的一句话`);
    for (const key of evidence.get(factor.factor)?.required_number_keys ?? []) {
      if (!(key in factor.numbers)) errors.push(`${factor.factor}.numbers 缺少 ${key}`);
      else if (factor.numbers[key] !== facts.observable_metrics[key]) errors.push(`${factor.factor}.${key} 与客观事实不一致`);
    }
    for (const [key, value] of Object.entries(factor.numbers)) {
      if (!(key in facts.observable_metrics)) errors.push(`${factor.factor}.numbers 含未知口径 ${key}`);
      else if (value !== facts.observable_metrics[key]) errors.push(`${factor.factor}.${key} 与客观事实不一致`);
    }
  }
  if (new Set(assessment.factors.map((item) => item.ord)).size !== 5) errors.push("五项 ord 必须是1..5的不重复排列");
  for (const factor of FACTORS) if (!seen.has(factor)) errors.push(`缺少 factor：${factor}`);
  const copy = JSON.stringify(assessment);
  for (const key of FORBIDDEN_INPUT_KEYS) if (copy.includes(key)) errors.push(`输出泄漏禁读字段名：${key}`);
  return [...new Set(errors)];
}

export function expectedForecastDates(dataAsOf = DATA_AS_OF): string[] {
  return Array.from({ length: HORIZON_DAYS }, (_, index) => isoDateOffset(dataAsOf, index + 1));
}

export function validateDailyForecast(facts: DemandForecastFacts, daily: DailyForecast[]): string[] {
  const errors: string[] = [];
  if (daily.length !== HORIZON_DAYS) errors.push(`逐日预测必须正好 ${HORIZON_DAYS} 行，当前 ${daily.length} 行`);
  const expected = expectedForecastDates(facts.data_as_of);
  const seen = new Set<string>();
  for (let index = 0; index < daily.length; index += 1) {
    const item = daily[index]!;
    if (seen.has(item.forecast_date)) errors.push(`日期重复：${item.forecast_date}`);
    seen.add(item.forecast_date);
    if (item.forecast_date !== expected[index]) errors.push(`第${index + 1}行日期应为 ${expected[index]}`);
    const values = [item.p10_units, item.p50_units, item.p90_units];
    if (values.some((value) => !Number.isFinite(value) || value < 0)) errors.push(`${item.forecast_date} 分位值必须是非负数字`);
    if (!(item.p10_units <= item.p50_units && item.p50_units <= item.p90_units)) errors.push(`${item.forecast_date} 必须满足 p10≤p50≤p90`);
    if (item.baseline_units !== null && (!Number.isFinite(item.baseline_units) || item.baseline_units < 0)) errors.push(`${item.forecast_date}.baseline_units 非法`);
  }
  return [...new Set(errors)];
}

export function forecastSegments(dataAsOf = DATA_AS_OF, segmentDays = FORECAST_SEGMENT_DAYS) {
  if (HORIZON_DAYS % segmentDays !== 0) throw new Error("预测窗口必须整除90天");
  const dates = expectedForecastDates(dataAsOf);
  return Array.from({ length: HORIZON_DAYS / segmentDays }, (_, index) => {
    const startIndex = index * segmentDays;
    const segmentDates = dates.slice(startIndex, startIndex + segmentDays);
    return {
      segment_index: index + 1,
      start_day: startIndex + 1,
      end_day: startIndex + segmentDays,
      start_date: segmentDates[0]!,
      end_date: segmentDates.at(-1)!,
      dates: segmentDates,
    };
  });
}

export function validateDailyForecastSegment(
  facts: DemandForecastFacts,
  segmentIndex: number,
  daily: DailyForecast[],
  segmentDays = FORECAST_SEGMENT_DAYS,
): string[] {
  const segment = forecastSegments(facts.data_as_of, segmentDays)[segmentIndex - 1];
  if (!segment) return [`预测分段序号非法：${segmentIndex}`];
  const errors: string[] = [];
  if (daily.length !== segmentDays) errors.push(`第${segmentIndex}段必须正好 ${segmentDays} 行，当前 ${daily.length} 行`);
  for (let index = 0; index < daily.length; index += 1) {
    const item = daily[index]!;
    if (item.forecast_date !== segment.dates[index]) errors.push(`第${segmentIndex}段第${index + 1}行日期应为 ${segment.dates[index]}`);
    const values = [item.p10_units, item.p50_units, item.p90_units];
    if (values.some((value) => !Number.isFinite(value) || value < 0)) errors.push(`${item.forecast_date} 分位值必须是非负数字`);
    if (!(item.p10_units <= item.p50_units && item.p50_units <= item.p90_units)) errors.push(`${item.forecast_date} 必须满足 p10≤p50≤p90`);
    if (item.baseline_units !== null && (!Number.isFinite(item.baseline_units) || item.baseline_units < 0)) errors.push(`${item.forecast_date}.baseline_units 非法`);
  }
  return [...new Set(errors)];
}

const SCHEMA = `
CREATE TABLE IF NOT EXISTS fact_child_forecast_agent_run (
  run_id TEXT PRIMARY KEY, child_asin TEXT NOT NULL, run_date TEXT NOT NULL,
  actual_run_date TEXT NOT NULL, data_as_of TEXT NOT NULL, horizon_days INTEGER NOT NULL,
  trigger TEXT NOT NULL, model_version TEXT, prompt_version TEXT, method_version TEXT,
  comparison_snapshot_run_id TEXT, prev_run_id TEXT, confidence TEXT NOT NULL,
  confidence_reason TEXT NOT NULL, judgment_summary TEXT NOT NULL, status TEXT NOT NULL,
  created_at TEXT NOT NULL, completed_at TEXT NOT NULL, error_message TEXT
);
CREATE INDEX IF NOT EXISTS idx_dfagent_run
  ON fact_child_forecast_agent_run(child_asin, run_date DESC, created_at DESC);
CREATE TABLE IF NOT EXISTS fact_child_forecast_agent_daily (
  run_id TEXT NOT NULL, child_asin TEXT NOT NULL, forecast_date TEXT NOT NULL,
  p10_units REAL NOT NULL, p50_units REAL NOT NULL, p90_units REAL NOT NULL,
  baseline_units REAL, PRIMARY KEY (run_id, forecast_date)
);
CREATE TABLE IF NOT EXISTS fact_child_forecast_judgment_factor (
  run_id TEXT NOT NULL, factor TEXT NOT NULL, ord INTEGER NOT NULL, state TEXT NOT NULL,
  impact_pct REAL, because TEXT NOT NULL, numbers TEXT NOT NULL,
  PRIMARY KEY (run_id, factor)
);
CREATE TABLE IF NOT EXISTS fact_child_forecast_agent_step (
  run_id TEXT NOT NULL, step_seq INTEGER NOT NULL, tool TEXT NOT NULL, label TEXT NOT NULL,
  detail TEXT NOT NULL, status TEXT NOT NULL, duration_ms REAL NOT NULL, sources TEXT NOT NULL,
  started_at TEXT, completed_at TEXT,
  PRIMARY KEY (run_id, step_seq)
);`;

function ensureColumn(db: DatabaseSync, table: string, column: string, definition: string): void {
  const columns = db.prepare(`PRAGMA table_info(${table})`).all() as Array<{ name: string }>;
  if (!columns.some((item) => item.name === column)) db.exec(`ALTER TABLE ${table} ADD COLUMN ${column} ${definition}`);
}

function ensureDemandForecastSchema(db: DatabaseSync): void {
  db.exec(SCHEMA);
  ensureColumn(db, "fact_child_forecast_agent_run", "error_message", "TEXT");
  ensureColumn(db, "fact_child_forecast_agent_step", "started_at", "TEXT");
  ensureColumn(db, "fact_child_forecast_agent_step", "completed_at", "TEXT");
}

function openDemandForecastDb(dbPath: string): DatabaseSync {
  mkdirSync(dirname(dbPath), { recursive: true });
  const db = new DatabaseSync(dbPath);
  ensureDemandForecastSchema(db);
  return db;
}

export function beginDemandForecastRun(args: {
  facts: DemandForecastFacts;
  trigger: ForecastTrigger;
  modelVersion?: string | null;
  comparisonSnapshotRunId?: string;
  dbPath?: string;
}): ForecastRunHandle {
  const dbPath = args.dbPath ?? DEFAULT_DEMAND_FORECAST_DB;
  const db = openDemandForecastDb(dbPath);
  try {
    db.exec("BEGIN IMMEDIATE");
    const active = db.prepare(`SELECT run_id FROM fact_child_forecast_agent_run
      WHERE child_asin=? AND status='running' ORDER BY created_at DESC LIMIT 1`)
      .get(args.facts.child_asin) as { run_id?: string } | undefined;
    if (active?.run_id) {
      db.exec("COMMIT");
      return { run_id: active.run_id, reused: true, db_path: dbPath };
    }
    const seqRow = db.prepare(`SELECT COUNT(*) AS n FROM fact_child_forecast_agent_run
      WHERE child_asin=? AND run_date=?`).get(args.facts.child_asin, args.facts.data_as_of) as { n: number };
    const runId = `${args.facts.child_asin}-${args.facts.data_as_of}-${Number(seqRow.n) + 1}`;
    const prev = db.prepare(`SELECT run_id FROM fact_child_forecast_agent_run
      WHERE child_asin=? AND status='completed' ORDER BY run_date DESC, created_at DESC LIMIT 1`)
      .get(args.facts.child_asin) as { run_id?: string } | undefined;
    const timestamp = shanghaiNow();
    db.prepare(`INSERT INTO fact_child_forecast_agent_run
      (run_id,child_asin,run_date,actual_run_date,data_as_of,horizon_days,trigger,model_version,
       prompt_version,method_version,comparison_snapshot_run_id,prev_run_id,confidence,
       confidence_reason,judgment_summary,status,created_at,completed_at,error_message)
      VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`).run(
      runId, args.facts.child_asin, args.facts.data_as_of, timestamp.slice(0, 10),
      args.facts.data_as_of, HORIZON_DAYS, args.trigger, args.modelVersion ?? null,
      PROMPT_VERSION, METHOD_VERSION,
      args.comparisonSnapshotRunId ?? "forecast-v030-20260803-default", prev?.run_id ?? null,
      "", "", "", "running", timestamp, "", null,
    );
    db.exec("COMMIT");
    return { run_id: runId, reused: false, db_path: dbPath };
  } catch (error) {
    try { db.exec("ROLLBACK"); } catch { /* no active transaction */ }
    throw error;
  } finally {
    db.close();
  }
}

export function updateDemandForecastRunModel(runId: string, modelVersion: string, dbPath = DEFAULT_DEMAND_FORECAST_DB): void {
  const db = openDemandForecastDb(dbPath);
  try {
    db.prepare("UPDATE fact_child_forecast_agent_run SET model_version=? WHERE run_id=? AND status='running'").run(modelVersion, runId);
  } finally {
    db.close();
  }
}

export function startDemandForecastStep(args: {
  runId: string;
  stepSeq: number;
  tool: string;
  label: string;
  detail: string;
  sources: string[];
  dbPath?: string;
}): ForecastStep {
  const dbPath = args.dbPath ?? DEFAULT_DEMAND_FORECAST_DB;
  const startedAt = shanghaiNow();
  const db = openDemandForecastDb(dbPath);
  try {
    db.prepare(`INSERT INTO fact_child_forecast_agent_step
      (run_id,step_seq,tool,label,detail,status,duration_ms,sources,started_at,completed_at)
      VALUES (?,?,?,?,?,'加载中',0,?,?,NULL)
      ON CONFLICT(run_id,step_seq) DO UPDATE SET tool=excluded.tool,label=excluded.label,
      detail=excluded.detail,status='加载中',duration_ms=0,sources=excluded.sources,
      started_at=excluded.started_at,completed_at=NULL`).run(
      args.runId, args.stepSeq, args.tool, args.label, args.detail, JSON.stringify(args.sources), startedAt,
    );
  } finally {
    db.close();
  }
  return {
    step_seq: args.stepSeq, tool: args.tool, label: args.label, detail: args.detail,
    status: "加载中", duration_ms: null, sources: args.sources,
    started_at: startedAt, completed_at: null,
  };
}

export function finishDemandForecastStep(args: {
  runId: string;
  step: ForecastStep;
  status: "完成" | "失败";
  detail: string;
  durationMs: number;
  dbPath?: string;
}): ForecastStep {
  const dbPath = args.dbPath ?? DEFAULT_DEMAND_FORECAST_DB;
  const completedAt = shanghaiNow();
  const db = openDemandForecastDb(dbPath);
  try {
    db.prepare(`UPDATE fact_child_forecast_agent_step SET detail=?,status=?,duration_ms=?,completed_at=?
      WHERE run_id=? AND step_seq=?`).run(
      args.detail, args.status, args.durationMs, completedAt,
      args.runId, args.step.step_seq,
    );
  } finally {
    db.close();
  }
  return { ...args.step, detail: args.detail, status: args.status, duration_ms: args.durationMs, completed_at: completedAt };
}

export function failDemandForecastRun(runId: string, message: string, dbPath = DEFAULT_DEMAND_FORECAST_DB): void {
  const db = openDemandForecastDb(dbPath);
  try {
    db.prepare(`UPDATE fact_child_forecast_agent_run SET status='failed',completed_at=?,error_message=?
      WHERE run_id=? AND status='running'`).run(shanghaiNow(), message.slice(0, 500), runId);
  } finally {
    db.close();
  }
}

const PUBLIC_RUN_STATUS = { running: "加载中", completed: "完成", failed: "失败" } as const;

export function readDemandForecastRunStatus(args: {
  runId?: string;
  childAsin?: string;
  dbPath?: string;
}): DemandForecastRunStatus {
  const dbPath = args.dbPath ?? DEFAULT_DEMAND_FORECAST_DB;
  if (!args.runId && !args.childAsin) return { ok: false, run: null, steps: [], error: "缺少 runId 或 childAsin" };
  try {
    // Open through the schema gate so status polling also works against a
    // pre-segmentation sidecar before the first new run is triggered.
    const db = openDemandForecastDb(dbPath);
    try {
      const run = (args.runId
        ? db.prepare("SELECT * FROM fact_child_forecast_agent_run WHERE run_id=?").get(args.runId)
        : db.prepare(`SELECT * FROM fact_child_forecast_agent_run WHERE child_asin=?
            ORDER BY CASE status WHEN 'running' THEN 0 ELSE 1 END, run_date DESC, created_at DESC LIMIT 1`)
          .get(args.childAsin!.trim().toUpperCase())) as Row | undefined;
      if (!run) return { ok: false, run: null, steps: [], error: "没有找到这次需求预测运行" };
      const rows = db.prepare(`SELECT step_seq,label,detail,status,duration_ms,sources,started_at,completed_at
        FROM fact_child_forecast_agent_step WHERE run_id=? ORDER BY step_seq`).all(String(run.run_id)) as Row[];
      const steps = rows.map((item) => ({
        seq: Number(item.step_seq), label: String(item.label), detail: String(item.detail),
        status: item.status as "加载中" | "完成" | "失败",
        duration_ms: item.status === "加载中" ? null : Number(item.duration_ms),
        sources: JSON.parse(String(item.sources || "[]")) as string[],
        started_at: item.started_at ? String(item.started_at) : null,
        completed_at: item.completed_at ? String(item.completed_at) : null,
      }));
      const loading = steps.find((item) => item.status === "加载中");
      const currentStep = loading?.seq ?? Math.max(0, ...steps.map((item) => item.seq));
      const internalStatus = String(run.status) as keyof typeof PUBLIC_RUN_STATUS;
      const totalSteps = run.method_version === METHOD_VERSION ? FORECAST_TOTAL_STEPS : steps.length;
      return {
        ok: true,
        run: {
          run_id: String(run.run_id), child_asin: String(run.child_asin),
          status: PUBLIC_RUN_STATUS[internalStatus] ?? "失败",
          created_at: String(run.created_at),
          completed_at: run.completed_at ? String(run.completed_at) : null,
          model_version: run.model_version ? String(run.model_version) : null,
          current_step: currentStep, total_steps: totalSteps,
          error: run.error_message ? String(run.error_message) : null,
        },
        steps,
        error: null,
      };
    } finally {
      db.close();
    }
  } catch {
    return { ok: false, run: null, steps: [], error: "没有找到这次需求预测运行" };
  }
}

export function writeDemandForecastRun(args: {
  facts: DemandForecastFacts;
  assessment: DemandAssessment;
  daily: DailyForecast[];
  steps: ForecastStep[];
  trigger: ForecastTrigger;
  modelVersion: string;
  comparisonSnapshotRunId?: string;
  runId?: string;
  finalStepStartedMs?: number;
  finalStepCompletedDetail?: string;
  dbPath?: string;
  exportPath?: string;
}): WrittenDemandForecast {
  const errors = [...validateDemandAssessment(args.facts, args.assessment), ...validateDailyForecast(args.facts, args.daily)];
  if (errors.length) throw new Error(errors.join("；"));
  const dbPath = args.dbPath ?? DEFAULT_DEMAND_FORECAST_DB;
  const exportPath = args.exportPath ?? DEFAULT_DEMAND_FORECAST_JSON;
  let runId = args.runId;
  if (!runId) {
    const handle = beginDemandForecastRun({ facts: args.facts, trigger: args.trigger, modelVersion: args.modelVersion, comparisonSnapshotRunId: args.comparisonSnapshotRunId, dbPath });
    if (handle.reused) throw new Error(`该对象已有运行中的需求预测：${handle.run_id}`);
    runId = handle.run_id;
  }
  const db = openDemandForecastDb(dbPath);
  let run: Record<string, JsonScalar>;
  let persistedSteps = args.steps;
  try {
    db.exec("BEGIN IMMEDIATE");
    const existing = db.prepare("SELECT * FROM fact_child_forecast_agent_run WHERE run_id=? AND status='running'").get(runId) as Row | undefined;
    if (!existing) throw new Error(`运行 ${runId} 不存在或已经结束`);
    db.prepare("DELETE FROM fact_child_forecast_agent_daily WHERE run_id=?").run(runId);
    db.prepare("DELETE FROM fact_child_forecast_judgment_factor WHERE run_id=?").run(runId);
    const dailyInsert = db.prepare(`INSERT INTO fact_child_forecast_agent_daily
      (run_id,child_asin,forecast_date,p10_units,p50_units,p90_units,baseline_units) VALUES (?,?,?,?,?,?,?)`);
    for (const item of args.daily) dailyInsert.run(runId, args.facts.child_asin, item.forecast_date, item.p10_units, item.p50_units, item.p90_units, item.baseline_units);
    const factorInsert = db.prepare(`INSERT INTO fact_child_forecast_judgment_factor
      (run_id,factor,ord,state,impact_pct,because,numbers) VALUES (?,?,?,?,?,?,?)`);
    for (const item of args.assessment.factors) factorInsert.run(runId, item.factor, item.ord, item.state, item.impact_pct, item.because, JSON.stringify(item.numbers));
    const timestamp = shanghaiNow();
    if (args.finalStepStartedMs !== undefined) {
      persistedSteps = args.steps.map((step) => step.step_seq === FORECAST_TOTAL_STEPS ? {
        ...step,
        detail: args.finalStepCompletedDetail ?? step.detail,
        status: "完成" as const,
        duration_ms: Date.now() - args.finalStepStartedMs,
        completed_at: timestamp,
      } : step);
    }
    run = {
      run_id: runId, child_asin: args.facts.child_asin, run_date: String(existing.run_date),
      actual_run_date: String(existing.actual_run_date), data_as_of: args.facts.data_as_of,
      horizon_days: HORIZON_DAYS, trigger: args.trigger, model_version: args.modelVersion,
      prompt_version: PROMPT_VERSION, method_version: METHOD_VERSION,
      comparison_snapshot_run_id: args.comparisonSnapshotRunId
        ?? (existing.comparison_snapshot_run_id === null ? null : String(existing.comparison_snapshot_run_id)),
      prev_run_id: existing.prev_run_id ?? null, confidence: args.assessment.confidence,
      confidence_reason: args.assessment.confidence_reason, judgment_summary: args.assessment.judgment_summary,
      status: "completed", created_at: String(existing.created_at), completed_at: timestamp,
    };
    const stepUpsert = db.prepare(`INSERT INTO fact_child_forecast_agent_step
      (run_id,step_seq,tool,label,detail,status,duration_ms,sources,started_at,completed_at)
      VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(run_id,step_seq) DO UPDATE SET
      tool=excluded.tool,label=excluded.label,detail=excluded.detail,status=excluded.status,
      duration_ms=excluded.duration_ms,sources=excluded.sources,started_at=excluded.started_at,
      completed_at=excluded.completed_at`);
    for (const step of persistedSteps) stepUpsert.run(runId, step.step_seq, step.tool, step.label, step.detail, step.status, step.duration_ms ?? 0, JSON.stringify(step.sources), step.started_at, step.completed_at);
    db.prepare(`UPDATE fact_child_forecast_agent_run SET model_version=?,confidence=?,confidence_reason=?,
      judgment_summary=?,status='completed',completed_at=?,error_message=NULL WHERE run_id=? AND status='running'`).run(
      args.modelVersion, args.assessment.confidence, args.assessment.confidence_reason,
      args.assessment.judgment_summary, timestamp, runId,
    );
    db.exec("COMMIT");
  } catch (error) {
    try { db.exec("ROLLBACK"); } catch { /* no active transaction */ }
    throw error;
  } finally {
    db.close();
  }
  const output: WrittenDemandForecast = {
    contract_version: CONTRACT_VERSION,
    run: run!, daily: args.daily, assessment: args.assessment,
    steps: persistedSteps, db_path: dbPath, export_path: exportPath,
  };
  mkdirSync(dirname(exportPath), { recursive: true });
  writeFileSync(exportPath, `${JSON.stringify(output, null, 2)}\n`, "utf8");
  return output;
}
