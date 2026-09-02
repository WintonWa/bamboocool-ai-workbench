export type ValueOrigin = "customer_actual" | "synthetic" | "model_derived" | "plan_input" | string;

export type ChildChoice = {
  childAsin: string;
  parentAsin: string;
  productName: string;
  styleName: string;
  size: string;
  colorway: string;
  lifecycleStage: string;
  profileId: string;
  profileName: string;
  analysisChildAsin: string;
  isGoldenSample: boolean;
};

export type DemoRoute = {
  requestedChildAsin: string;
  analysisChildAsin: string;
  profileId: string;
  profileName: string;
  routingMethod: string;
  routingReason: string;
  wasMapped: boolean;
  valueOrigin: ValueOrigin;
};

export type ChildProductContext = {
  childAsin: string;
  parentAsin: string;
  productName: string;
  styleName: string;
  size: string;
  colorway: string;
  lifecycleStage: string;
  profileId: string;
  profileName: string;
  profileDescription: string;
  isGoldenSample: boolean;
  valueOrigin: ValueOrigin;
};

export type HistoryAudit = {
  childAsin: string;
  startDate: string;
  endDate: string;
  observedDays: number;
  expectedDays: number;
  missingDays: number;
  totalObservedUnits: number;
  totalPotentialDemandUnits: number;
  lostSalesUnits: number;
  stockoutDays: number;
  promotionDays: number;
  advertisingActiveDays: number;
  abnormalDays: number;
  recent30dUnits: number;
  previous30dUnits: number;
  rawTrendRatio: number | null;
  auditFlags: string[];
  valueOrigins: string[];
};

export type DemandReconstruction = {
  childAsin: string;
  startDate: string;
  endDate: string;
  observedUnits: number;
  estimatedDemandUnits: number;
  recoveredDemandUnits: number;
  censoredDays: number;
  cleanBaselineDaily: number;
  confidenceScore: number;
  adjustmentReasons: string[];
  valueOrigin: ValueOrigin;
};

export type DriverEffects = {
  childAsin: string;
  historical: {
    advertisingEffect: number;
    priceEffect: number;
    promotionEffect: number;
    seasonalityEffect: number;
    lifecycleEffect: number;
  };
  future: {
    advertisingEffect: number;
    priceEffect: number;
    promotionEffect: number;
    seasonalityEffect: number;
    lifecycleEffect: number;
    plannedPromotionDays: number;
    plannedAdvertisingDays: number;
  };
  interpretation: string[];
  valueOrigin: ValueOrigin;
};

export type ForecastSummary = {
  childAsin: string;
  forecastRunId: string;
  startDate: string;
  endDate: string;
  horizonDays: number;
  p10Units: number;
  p50Units: number;
  p90Units: number;
  p50DailyAverage: number;
  selectedModel: string;
  modelWape: number;
  modelBias: number;
  confidenceScore: number;
  modelCandidates: Array<{ modelName: string; wape: number; bias: number; selected: boolean }>;
  daily: Array<{ date: string; p10: number; p50: number; p90: number }>;
  valueOrigin: ValueOrigin;
};

export type InventorySupply = {
  childAsin: string;
  asOfDate: string;
  fbaSellable: number;
  fbaReserved: number;
  fbaReceiving: number;
  fbaInbound: number;
  overseasAvailable: number;
  overseasInbound: number;
  localAvailable: number;
  baseSafetyDays: number;
  targetCoverageDays: number;
  purchaseLeadDays: number;
  preferredTransportMode: string;
  futureSupplyEvents: Array<{
    eventId: string;
    units: number;
    etaEarliest: string;
    etaLatest: string;
    status: string;
    confidence: string;
  }>;
  valueOrigin: ValueOrigin;
};

export type ProjectionScenario = {
  scenario: "base" | "stress" | "improvement" | string;
  safetyBreachDate: string;
  stockoutDate: string;
  endingInventoryUnits: number;
  lostSalesUnits: number;
  minimumCoverageDays: number;
  riskStatus: string;
};

export type InventoryProjectionSummary = {
  childAsin: string;
  forecastRunId: string;
  startDate: string;
  endDate: string;
  scenarios: ProjectionScenario[];
  dailyBase: Array<{
    date: string;
    opening: number;
    arrivals: number;
    demand: number;
    closing: number;
    coverageDays: number;
    riskStatus: string;
  }>;
  valueOrigin: ValueOrigin;
};

export type ReplenishmentDecision = {
  childAsin: string;
  forecastRunId: string;
  baseRiskStatus: string;
  safetyBreachDate: string;
  baseStockoutDate: string;
  stressStockoutDate: string;
  latestOrderDate: string;
  suggestedReplenishmentQty: number;
  suggestedAirQty: number;
  suggestedSeaQty: number;
  projectedLostSalesUnits: number;
  endingInventoryUnits: number;
  dynamicSafetyDays: number;
  dynamicSafetyUnits: number;
  decisionSummary: string;
  confidenceScore: number;
  valueOrigin: ValueOrigin;
};

export type StreamEvent = {
  type: string;
  runId: string;
  sessionId?: string;
  [key: string]: unknown;
};
