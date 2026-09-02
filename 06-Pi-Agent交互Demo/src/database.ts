import { DatabaseSync } from "node:sqlite";
import { DATASET_PATH } from "./config.ts";
import type {
  ChildChoice,
  ChildProductContext,
  DemandReconstruction,
  DemoRoute,
  DriverEffects,
  ForecastSummary,
  HistoryAudit,
  InventoryProjectionSummary,
  InventorySupply,
  ProjectionScenario,
  ReplenishmentDecision,
} from "./types.ts";

const FORECAST_RUN_ID = "forecast-v030-20260803-default";

function round(value: number, digits = 2): number {
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
}

function number(value: unknown): number {
  return Number(value ?? 0);
}

function splitDistinct(value: unknown): string[] {
  return String(value ?? "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean)
    .filter((item, index, list) => list.indexOf(item) === index);
}

type AnyRow = Record<string, string | number | null>;

export class DemoRepository {
  readonly db: DatabaseSync;

  constructor(path = DATASET_PATH) {
    this.db = new DatabaseSync(path, { readOnly: true });
    this.db.exec("PRAGMA query_only = ON");
  }

  close(): void {
    this.db.close();
  }

  ping(): boolean {
    const row = this.db.prepare(`
      SELECT COUNT(*) AS row_count,
             COUNT(DISTINCT child_asin) AS child_count,
             COUNT(DISTINCT forecast_date) AS forecast_days
      FROM fact_child_forecast_daily
      WHERE forecast_run_id = ?
    `).get(FORECAST_RUN_ID) as AnyRow;
    return number(row.row_count) === 30_780 && number(row.child_count) === 342 && number(row.forecast_days) === 90;
  }

  listChildren(): ChildChoice[] {
    const rows = this.db.prepare(`
      SELECT c.child_asin, c.parent_asin, c.product_name, c.style_name,
             COALESCE(c.size, '未标注') AS size,
             COALESCE(c.colorway, '未标注') AS colorway,
             l.lifecycle_stage, r.analysis_child_asin, r.demo_profile_id,
             p.profile_name,
             CASE WHEN c.child_asin = p.golden_child_asin THEN 1 ELSE 0 END AS is_golden
      FROM dim_product_child c
      JOIN bridge_demo_child_route r ON r.requested_child_asin = c.child_asin
      JOIN dim_demo_profile p ON p.profile_id = r.demo_profile_id
      JOIN dim_child_lifecycle_history l
        ON l.child_asin = c.child_asin
       AND l.effective_start <= '2026-08-03' AND l.effective_end >= '2026-08-03'
      ORDER BY is_golden DESC, p.profile_id, c.parent_asin, c.child_asin
    `).all() as AnyRow[];
    return rows.map((row) => ({
      childAsin: String(row.child_asin),
      parentAsin: String(row.parent_asin),
      productName: String(row.product_name),
      styleName: String(row.style_name),
      size: String(row.size),
      colorway: String(row.colorway),
      lifecycleStage: String(row.lifecycle_stage),
      profileId: String(row.demo_profile_id),
      profileName: String(row.profile_name),
      analysisChildAsin: String(row.analysis_child_asin),
      isGoldenSample: number(row.is_golden) === 1,
    }));
  }

  routeDemoChildAsin(requestedChildAsin: string): DemoRoute | null {
    const row = this.db.prepare(`
      SELECT r.requested_child_asin, r.analysis_child_asin, r.demo_profile_id,
             r.routing_method, r.routing_reason, r.value_origin, p.profile_name
      FROM bridge_demo_child_route r
      JOIN dim_demo_profile p ON p.profile_id = r.demo_profile_id
      WHERE r.requested_child_asin = ?
    `).get(requestedChildAsin) as AnyRow | undefined;
    if (!row) return null;
    return {
      requestedChildAsin: String(row.requested_child_asin),
      analysisChildAsin: String(row.analysis_child_asin),
      profileId: String(row.demo_profile_id),
      profileName: String(row.profile_name),
      routingMethod: String(row.routing_method),
      routingReason: String(row.routing_reason),
      wasMapped: row.requested_child_asin !== row.analysis_child_asin,
      valueOrigin: String(row.value_origin),
    };
  }

  getChildProductContext(childAsin: string): ChildProductContext | null {
    const row = this.db.prepare(`
      SELECT c.child_asin, c.parent_asin, c.product_name, c.style_name,
             COALESCE(c.size, '未标注') AS size,
             COALESCE(c.colorway, '未标注') AS colorway,
             l.lifecycle_stage, p.profile_id, p.profile_name,
             p.description AS profile_description, p.value_origin,
             CASE WHEN c.child_asin = p.golden_child_asin THEN 1 ELSE 0 END AS is_golden
      FROM dim_product_child c
      JOIN dim_demo_profile p ON p.golden_child_asin = c.child_asin
      JOIN dim_child_lifecycle_history l
        ON l.child_asin = c.child_asin
       AND l.effective_start <= '2026-08-03' AND l.effective_end >= '2026-08-03'
      WHERE c.child_asin = ?
    `).get(childAsin) as AnyRow | undefined;
    if (!row) return null;
    return {
      childAsin: String(row.child_asin),
      parentAsin: String(row.parent_asin),
      productName: String(row.product_name),
      styleName: String(row.style_name),
      size: String(row.size),
      colorway: String(row.colorway),
      lifecycleStage: String(row.lifecycle_stage),
      profileId: String(row.profile_id),
      profileName: String(row.profile_name),
      profileDescription: String(row.profile_description),
      isGoldenSample: number(row.is_golden) === 1,
      valueOrigin: String(row.value_origin),
    };
  }

  auditChildDailyHistory(childAsin: string): HistoryAudit | null {
    const rows = this.db.prepare(`
      SELECT s.date, s.units_sold, s.potential_demand_units, s.lost_sales_units,
             i.stockout_flag, pr.promotion_type, a.ad_spend,
             f.demand_quality_flag, s.value_origin
      FROM fact_child_sales_daily s
      JOIN fact_child_inventory_daily i USING (date, child_asin)
      JOIN fact_child_promotion_daily pr USING (date, child_asin)
      JOIN fact_child_advertising_daily a USING (date, child_asin)
      JOIN feature_child_demand_daily f USING (date, child_asin)
      WHERE s.child_asin = ?
      ORDER BY s.date
    `).all(childAsin) as AnyRow[];
    if (!rows.length) return null;
    const recent = rows.slice(-30);
    const previous = rows.slice(-60, -30);
    const recent30dUnits = recent.reduce((sum, row) => sum + number(row.units_sold), 0);
    const previous30dUnits = previous.reduce((sum, row) => sum + number(row.units_sold), 0);
    const rawTrendRatio = previous30dUnits > 0 ? round(recent30dUnits / previous30dUnits, 4) : null;
    const stockoutDays = rows.filter((row) => number(row.stockout_flag) === 1).length;
    const abnormalDays = rows.filter((row) => String(row.demand_quality_flag) !== "normal").length;
    const flags: string[] = [];
    if (stockoutDays > 0) flags.push(`检测到${stockoutDays}天缺货，直接销量低估真实需求`);
    if (abnormalDays > 0) flags.push(`检测到${abnormalDays}天需求需校正`);
    if (rawTrendRatio !== null && rawTrendRatio >= 1.15) flags.push("近30天销量明显增长");
    if (rawTrendRatio !== null && rawTrendRatio <= 0.85) flags.push("近30天销量明显下滑");
    if (!flags.length) flags.push("历史日序列完整，未发现显著异常");
    return {
      childAsin,
      startDate: String(rows[0].date),
      endDate: String(rows.at(-1)?.date),
      observedDays: rows.length,
      expectedDays: 730,
      missingDays: Math.max(0, 730 - rows.length),
      totalObservedUnits: rows.reduce((sum, row) => sum + number(row.units_sold), 0),
      totalPotentialDemandUnits: rows.reduce((sum, row) => sum + number(row.potential_demand_units), 0),
      lostSalesUnits: rows.reduce((sum, row) => sum + number(row.lost_sales_units), 0),
      stockoutDays,
      promotionDays: rows.filter((row) => String(row.promotion_type) !== "none").length,
      advertisingActiveDays: rows.filter((row) => number(row.ad_spend) > 0).length,
      abnormalDays,
      recent30dUnits,
      previous30dUnits,
      rawTrendRatio,
      auditFlags: flags,
      valueOrigins: splitDistinct(rows.map((row) => row.value_origin).join(",")),
    };
  }

  reconstructChildDemand(childAsin: string): DemandReconstruction | null {
    const row = this.db.prepare(`
      SELECT MIN(date) AS start_date, MAX(date) AS end_date,
             SUM(observed_units) AS observed_units,
             ROUND(SUM(estimated_demand_units), 2) AS estimated_demand_units,
             ROUND(SUM(estimated_demand_units - observed_units), 2) AS recovered_units,
             SUM(CASE WHEN demand_quality_flag <> 'normal' THEN 1 ELSE 0 END) AS censored_days,
             ROUND(AVG(clean_baseline_units), 2) AS clean_baseline_daily,
             ROUND(AVG(confidence_score), 4) AS confidence_score,
             GROUP_CONCAT(DISTINCT adjustment_reason) AS adjustment_reasons,
             MAX(value_origin) AS value_origin
      FROM feature_child_demand_daily
      WHERE child_asin = ?
    `).get(childAsin) as AnyRow;
    if (!row.start_date) return null;
    return {
      childAsin,
      startDate: String(row.start_date),
      endDate: String(row.end_date),
      observedUnits: number(row.observed_units),
      estimatedDemandUnits: number(row.estimated_demand_units),
      recoveredDemandUnits: number(row.recovered_units),
      censoredDays: number(row.censored_days),
      cleanBaselineDaily: number(row.clean_baseline_daily),
      confidenceScore: number(row.confidence_score),
      adjustmentReasons: splitDistinct(row.adjustment_reasons),
      valueOrigin: String(row.value_origin),
    };
  }

  estimateDemandDrivers(childAsin: string): DriverEffects | null {
    const historical = this.db.prepare(`
      SELECT ROUND(AVG(advertising_effect_ratio), 4) AS ad,
             ROUND(AVG(price_effect_ratio), 4) AS price,
             ROUND(AVG(promotion_effect_ratio), 4) AS promo,
             ROUND(AVG(seasonality_factor), 4) AS seasonality,
             ROUND(AVG(lifecycle_factor), 4) AS lifecycle
      FROM feature_child_demand_daily
      WHERE child_asin = ? AND date >= '2026-05-06'
    `).get(childAsin) as AnyRow;
    const future = this.db.prepare(`
      SELECT ROUND(AVG(f.advertising_effect_ratio), 4) AS ad,
             ROUND(AVG(f.price_effect_ratio), 4) AS price,
             ROUND(AVG(f.promotion_effect_ratio), 4) AS promo,
             ROUND(AVG(f.seasonality_factor), 4) AS seasonality,
             ROUND(AVG(f.lifecycle_factor), 4) AS lifecycle,
             SUM(CASE WHEN pp.promotion_type <> 'none' THEN 1 ELSE 0 END) AS promo_days,
             SUM(CASE WHEN pa.planned_spend > 0 THEN 1 ELSE 0 END) AS ad_days,
             MAX(f.value_origin) AS value_origin
      FROM fact_child_forecast_daily f
      JOIN plan_child_promotion_daily pp
        ON pp.date = f.forecast_date AND pp.child_asin = f.child_asin
      JOIN plan_child_advertising_daily pa
        ON pa.date = f.forecast_date AND pa.child_asin = f.child_asin
      WHERE f.child_asin = ? AND f.forecast_run_id = ?
    `).get(childAsin, FORECAST_RUN_ID) as AnyRow;
    if (!future.value_origin) return null;
    const interpretations: string[] = [];
    if (number(future.promo_days) > 0) interpretations.push(`未来排期包含${number(future.promo_days)}天促销`);
    if (number(future.ad) > number(historical.ad) + 0.02) interpretations.push("未来广告计划对需求有正向拉动");
    if (number(future.lifecycle) < 0.95) interpretations.push("生命周期下行压低基准需求");
    if (number(future.price) < 0.99) interpretations.push("价格计划对需求形成负向压力");
    if (!interpretations.length) interpretations.push("主要驱动项总体稳定");
    return {
      childAsin,
      historical: {
        advertisingEffect: number(historical.ad),
        priceEffect: number(historical.price),
        promotionEffect: number(historical.promo),
        seasonalityEffect: number(historical.seasonality),
        lifecycleEffect: number(historical.lifecycle),
      },
      future: {
        advertisingEffect: number(future.ad),
        priceEffect: number(future.price),
        promotionEffect: number(future.promo),
        seasonalityEffect: number(future.seasonality),
        lifecycleEffect: number(future.lifecycle),
        plannedPromotionDays: number(future.promo_days),
        plannedAdvertisingDays: number(future.ad_days),
      },
      interpretation: interpretations,
      valueOrigin: String(future.value_origin),
    };
  }

  forecastChildSalesDaily(childAsin: string): ForecastSummary | null {
    const rows = this.db.prepare(`
      SELECT forecast_date, p10_units, p50_units, p90_units,
             selected_model, model_wape, confidence_score, value_origin
      FROM fact_child_forecast_daily
      WHERE forecast_run_id = ? AND child_asin = ?
      ORDER BY forecast_date
    `).all(FORECAST_RUN_ID, childAsin) as AnyRow[];
    if (rows.length !== 90) return null;
    const evaluations = this.db.prepare(`
      SELECT model_name, wape, bias, selected
      FROM fact_child_forecast_evaluation
      WHERE forecast_run_id = ? AND child_asin = ?
      ORDER BY selected DESC, wape
    `).all(FORECAST_RUN_ID, childAsin) as AnyRow[];
    const selected = evaluations.find((row) => number(row.selected) === 1);
    const p50Units = rows.reduce((sum, row) => sum + number(row.p50_units), 0);
    return {
      childAsin,
      forecastRunId: FORECAST_RUN_ID,
      startDate: String(rows[0].forecast_date),
      endDate: String(rows.at(-1)?.forecast_date),
      horizonDays: rows.length,
      p10Units: rows.reduce((sum, row) => sum + number(row.p10_units), 0),
      p50Units,
      p90Units: rows.reduce((sum, row) => sum + number(row.p90_units), 0),
      p50DailyAverage: round(p50Units / rows.length),
      selectedModel: String(rows[0].selected_model),
      modelWape: number(rows[0].model_wape),
      modelBias: number(selected?.bias),
      confidenceScore: round(rows.reduce((sum, row) => sum + number(row.confidence_score), 0) / rows.length, 4),
      modelCandidates: evaluations.map((row) => ({
        modelName: String(row.model_name),
        wape: number(row.wape),
        bias: number(row.bias),
        selected: number(row.selected) === 1,
      })),
      daily: rows.map((row) => ({
        date: String(row.forecast_date),
        p10: number(row.p10_units),
        p50: number(row.p50_units),
        p90: number(row.p90_units),
      })),
      valueOrigin: String(rows[0].value_origin),
    };
  }

  getChildInventorySupply(childAsin: string): InventorySupply | null {
    const snapshot = this.db.prepare(`
      SELECT date, closing_fba_sellable, fba_reserved, fba_receiving, fba_inbound,
             overseas_available, overseas_inbound, local_available, value_origin
      FROM fact_child_inventory_daily
      WHERE child_asin = ? ORDER BY date DESC LIMIT 1
    `).get(childAsin) as AnyRow | undefined;
    const policy = this.db.prepare(`
      SELECT base_safety_days, target_coverage_days, purchase_lead_days,
             preferred_transport_mode
      FROM config_child_inventory_policy
      WHERE child_asin = ?
        AND effective_start <= '2026-08-04' AND effective_end >= '2026-08-04'
    `).get(childAsin) as AnyRow | undefined;
    if (!snapshot || !policy) return null;
    const events = this.db.prepare(`
      SELECT plan_event_id, planned_units, eta_earliest, eta_latest,
             event_status, confidence_level
      FROM plan_child_supply_event
      WHERE child_asin = ? ORDER BY eta_earliest
    `).all(childAsin) as AnyRow[];
    return {
      childAsin,
      asOfDate: String(snapshot.date),
      fbaSellable: number(snapshot.closing_fba_sellable),
      fbaReserved: number(snapshot.fba_reserved),
      fbaReceiving: number(snapshot.fba_receiving),
      fbaInbound: number(snapshot.fba_inbound),
      overseasAvailable: number(snapshot.overseas_available),
      overseasInbound: number(snapshot.overseas_inbound),
      localAvailable: number(snapshot.local_available),
      baseSafetyDays: number(policy.base_safety_days),
      targetCoverageDays: number(policy.target_coverage_days),
      purchaseLeadDays: number(policy.purchase_lead_days),
      preferredTransportMode: String(policy.preferred_transport_mode),
      futureSupplyEvents: events.map((row) => ({
        eventId: String(row.plan_event_id),
        units: number(row.planned_units),
        etaEarliest: String(row.eta_earliest),
        etaLatest: String(row.eta_latest),
        status: String(row.event_status),
        confidence: String(row.confidence_level),
      })),
      valueOrigin: String(snapshot.value_origin),
    };
  }

  projectChildInventoryDaily(childAsin: string): InventoryProjectionSummary | null {
    const rows = this.db.prepare(`
      SELECT scenario, projection_date, opening_sellable, considered_arrivals,
             forecast_demand, closing_sellable, lost_sales_units,
             coverage_days, risk_status, value_origin
      FROM fact_child_inventory_projection_daily
      WHERE forecast_run_id = ? AND child_asin = ?
      ORDER BY CASE scenario WHEN 'base' THEN 1 WHEN 'stress' THEN 2 ELSE 3 END,
               projection_date
    `).all(FORECAST_RUN_ID, childAsin) as AnyRow[];
    if (rows.length !== 270) return null;
    const riskPriority = ["stockout", "replenishment_gap", "safety_stock_breach", "overstock", "aged_inventory_risk", "healthy"];
    const scenarios: ProjectionScenario[] = ["base", "stress", "improvement"].map((scenario) => {
      const subset = rows.filter((row) => row.scenario === scenario);
      const safety = subset.find((row) => ["safety_stock_breach", "replenishment_gap", "stockout"].includes(String(row.risk_status)));
      const stockout = subset.find((row) => number(row.closing_sellable) === 0 && number(row.forecast_demand) > 0);
      const ending = subset.at(-1)!;
      const riskStatus = riskPriority.find((status) => subset.some((row) => row.risk_status === status)) ?? String(ending.risk_status);
      return {
        scenario,
        safetyBreachDate: safety ? String(safety.projection_date) : "none",
        stockoutDate: stockout ? String(stockout.projection_date) : "none",
        endingInventoryUnits: number(ending.closing_sellable),
        lostSalesUnits: subset.reduce((sum, row) => sum + number(row.lost_sales_units), 0),
        minimumCoverageDays: round(Math.min(...subset.map((row) => number(row.coverage_days))), 2),
        riskStatus,
      };
    });
    const base = rows.filter((row) => row.scenario === "base");
    return {
      childAsin,
      forecastRunId: FORECAST_RUN_ID,
      startDate: String(base[0].projection_date),
      endDate: String(base.at(-1)?.projection_date),
      scenarios,
      dailyBase: base.map((row) => ({
        date: String(row.projection_date),
        opening: number(row.opening_sellable),
        arrivals: number(row.considered_arrivals),
        demand: number(row.forecast_demand),
        closing: number(row.closing_sellable),
        coverageDays: number(row.coverage_days),
        riskStatus: String(row.risk_status),
      })),
      valueOrigin: String(rows[0].value_origin),
    };
  }

  recommendChildReplenishment(childAsin: string): ReplenishmentDecision | null {
    const row = this.db.prepare(`
      SELECT * FROM fact_child_inventory_decision
      WHERE forecast_run_id = ? AND child_asin = ?
    `).get(FORECAST_RUN_ID, childAsin) as AnyRow | undefined;
    if (!row) return null;
    return {
      childAsin,
      forecastRunId: String(row.forecast_run_id),
      baseRiskStatus: String(row.base_risk_status),
      safetyBreachDate: String(row.safety_breach_date),
      baseStockoutDate: String(row.base_stockout_date),
      stressStockoutDate: String(row.stress_stockout_date),
      latestOrderDate: String(row.latest_order_date),
      suggestedReplenishmentQty: number(row.suggested_replenishment_qty),
      suggestedAirQty: number(row.suggested_air_qty),
      suggestedSeaQty: number(row.suggested_sea_qty),
      projectedLostSalesUnits: number(row.projected_lost_sales_units),
      endingInventoryUnits: number(row.ending_inventory_units),
      dynamicSafetyDays: number(row.dynamic_safety_days),
      dynamicSafetyUnits: number(row.dynamic_safety_units),
      decisionSummary: String(row.decision_summary),
      confidenceScore: number(row.confidence_score),
      valueOrigin: String(row.value_origin),
    };
  }
}
