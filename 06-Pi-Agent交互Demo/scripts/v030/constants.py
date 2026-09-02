from datetime import date, timedelta
from pathlib import Path


DATASET_VERSION = "0.3.0"
AS_OF_DATE = date(2026, 8, 3)
HISTORY_DAYS = 730
FORECAST_DAYS = 90
HISTORY_START = AS_OF_DATE - timedelta(days=HISTORY_DAYS - 1)
FORECAST_START = AS_OF_DATE + timedelta(days=1)
FORECAST_END = FORECAST_START + timedelta(days=FORECAST_DAYS - 1)
RANDOM_SEED = 20260830
METHOD_VERSION = "child-demand-causal-v1"
FORECAST_RUN_ID = "forecast-v030-20260803-default"

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEMO_REBUILD_ROOT = PROJECT_ROOT.parent
DATA_BUILD_ROOT = DEMO_REBUILD_ROOT / "02-产品销售库存模块" / "02-数据构建"
SOURCE_ROOT = DATA_BUILD_ROOT / "v0.2.2"
SOURCE_DB = SOURCE_ROOT / "bamboocool_product_sales_inventory_v0.2.2.sqlite"
OUTPUT_ROOT = DATA_BUILD_ROOT / "v0.3.0"
STAGING_ROOT = DATA_BUILD_ROOT / ".v0.3.0-building"
OUTPUT_DB_NAME = "bamboocool_product_sales_inventory_v0.3.0.sqlite"

PROFILES = (
    {
        "profile_id": "stable_mature",
        "profile_name": "稳定成熟",
        "description": "周周期稳定、波动较低、库存健康",
        "lifecycle": "成熟期",
        "trend_annual": 0.01,
        "ad_elasticity": 0.16,
        "price_elasticity": -1.25,
        "promo_uplift": 0.18,
        "volatility": 0.08,
    },
    {
        "profile_id": "advertising_growth",
        "profile_name": "广告增长",
        "description": "广告投入提升并带动需求增长",
        "lifecycle": "成长期",
        "trend_annual": 0.28,
        "ad_elasticity": 0.32,
        "price_elasticity": -1.05,
        "promo_uplift": 0.22,
        "volatility": 0.11,
    },
    {
        "profile_id": "promotion_spike",
        "profile_name": "促销爆发",
        "description": "BD活动显著放量且预测区间扩大",
        "lifecycle": "成熟期",
        "trend_annual": 0.04,
        "ad_elasticity": 0.20,
        "price_elasticity": -1.45,
        "promo_uplift": 0.52,
        "volatility": 0.14,
    },
    {
        "profile_id": "stockout_censored",
        "profile_name": "缺货失真",
        "description": "历史销量被库存压制，需要还原潜在需求",
        "lifecycle": "成长期",
        "trend_annual": 0.20,
        "ad_elasticity": 0.24,
        "price_elasticity": -1.15,
        "promo_uplift": 0.24,
        "volatility": 0.12,
    },
    {
        "profile_id": "decline_overstock",
        "profile_name": "衰退积压",
        "description": "需求下滑并形成超储与库龄风险",
        "lifecycle": "衰退期",
        "trend_annual": -0.25,
        "ad_elasticity": 0.10,
        "price_elasticity": -1.60,
        "promo_uplift": 0.14,
        "volatility": 0.10,
    },
)

PROFILE_BY_ID = {item["profile_id"]: item for item in PROFILES}

WEEKDAY_FACTORS = (0.91, 0.94, 0.98, 1.00, 1.06, 1.11, 1.08)

HISTORICAL_DAILY_TABLES = (
    "fact_child_sales_daily",
    "fact_child_traffic_daily",
    "fact_child_advertising_daily",
    "fact_child_price_daily",
    "fact_child_promotion_daily",
    "fact_child_inventory_daily",
    "feature_child_demand_daily",
)

FUTURE_DAILY_TABLES = (
    "plan_child_advertising_daily",
    "plan_child_price_daily",
    "plan_child_promotion_daily",
    "fact_child_forecast_daily",
)
