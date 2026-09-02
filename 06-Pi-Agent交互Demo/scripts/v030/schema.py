import sqlite3


TABLE_DDL = {
    "dim_demo_profile": """
        CREATE TABLE dim_demo_profile (
          profile_id TEXT PRIMARY KEY, profile_name TEXT NOT NULL, description TEXT NOT NULL,
          lifecycle TEXT NOT NULL, golden_child_asin TEXT NOT NULL, parent_asin TEXT NOT NULL,
          parameters_json TEXT NOT NULL, value_origin TEXT NOT NULL, method_version TEXT NOT NULL
        )
    """,
    "bridge_demo_child_route": """
        CREATE TABLE bridge_demo_child_route (
          requested_child_asin TEXT PRIMARY KEY, analysis_child_asin TEXT NOT NULL,
          demo_profile_id TEXT NOT NULL, routing_method TEXT NOT NULL, routing_reason TEXT NOT NULL,
          value_origin TEXT NOT NULL, method_version TEXT NOT NULL
        )
    """,
    "dim_child_lifecycle_history": """
        CREATE TABLE dim_child_lifecycle_history (
          child_asin TEXT NOT NULL, parent_asin TEXT NOT NULL, effective_start TEXT NOT NULL,
          effective_end TEXT NOT NULL, lifecycle_stage TEXT NOT NULL, change_reason TEXT NOT NULL,
          confidence_score REAL NOT NULL, value_origin TEXT NOT NULL, method_version TEXT NOT NULL,
          provenance TEXT NOT NULL, PRIMARY KEY (child_asin, effective_start)
        )
    """,
    "bridge_supply_event_child": """
        CREATE TABLE bridge_supply_event_child (
          supply_event_id TEXT NOT NULL, child_asin TEXT NOT NULL, parent_asin TEXT NOT NULL,
          allocated_units INTEGER NOT NULL, allocation_ratio REAL NOT NULL,
          eta_earliest TEXT NOT NULL, eta_latest TEXT NOT NULL, event_status TEXT NOT NULL,
          allocation_method TEXT NOT NULL, confidence_score REAL NOT NULL,
          value_origin TEXT NOT NULL, method_version TEXT NOT NULL, provenance TEXT NOT NULL,
          PRIMARY KEY (supply_event_id, child_asin)
        )
    """,
    "fact_child_sales_daily": """
        CREATE TABLE fact_child_sales_daily (
          date TEXT NOT NULL, child_asin TEXT NOT NULL, parent_asin TEXT NOT NULL,
          units_sold INTEGER NOT NULL, potential_demand_units INTEGER NOT NULL,
          lost_sales_units INTEGER NOT NULL, orders INTEGER NOT NULL,
          sales_amount REAL NOT NULL, net_sales REAL NOT NULL,
          refund_units INTEGER NOT NULL, return_units INTEGER NOT NULL,
          average_selling_price REAL NOT NULL, value_origin TEXT NOT NULL,
          method_version TEXT NOT NULL, provenance TEXT NOT NULL,
          PRIMARY KEY (date, child_asin)
        )
    """,
    "fact_child_traffic_daily": """
        CREATE TABLE fact_child_traffic_daily (
          date TEXT NOT NULL, child_asin TEXT NOT NULL, parent_asin TEXT NOT NULL,
          sessions INTEGER NOT NULL, page_views INTEGER NOT NULL, buyers INTEGER NOT NULL,
          cvr REAL NOT NULL, quality_status TEXT NOT NULL, value_origin TEXT NOT NULL,
          method_version TEXT NOT NULL, provenance TEXT NOT NULL,
          PRIMARY KEY (date, child_asin)
        )
    """,
    "fact_child_advertising_daily": """
        CREATE TABLE fact_child_advertising_daily (
          date TEXT NOT NULL, child_asin TEXT NOT NULL, parent_asin TEXT NOT NULL,
          ad_budget REAL NOT NULL, ad_spend REAL NOT NULL, impressions INTEGER NOT NULL,
          clicks INTEGER NOT NULL, cpc REAL NOT NULL, ad_orders INTEGER NOT NULL,
          ad_sales REAL NOT NULL, ctr REAL NOT NULL, ad_cvr REAL NOT NULL,
          acos REAL NOT NULL, acoas REAL NOT NULL, value_origin TEXT NOT NULL,
          method_version TEXT NOT NULL, provenance TEXT NOT NULL,
          PRIMARY KEY (date, child_asin)
        )
    """,
    "fact_child_price_daily": """
        CREATE TABLE fact_child_price_daily (
          date TEXT NOT NULL, child_asin TEXT NOT NULL, parent_asin TEXT NOT NULL,
          list_price REAL NOT NULL, selling_price REAL NOT NULL, coupon_amount REAL NOT NULL,
          discount_rate REAL NOT NULL, price_change_rate REAL NOT NULL,
          price_event TEXT NOT NULL, value_origin TEXT NOT NULL,
          method_version TEXT NOT NULL, provenance TEXT NOT NULL,
          PRIMARY KEY (date, child_asin)
        )
    """,
    "fact_child_promotion_daily": """
        CREATE TABLE fact_child_promotion_daily (
          date TEXT NOT NULL, child_asin TEXT NOT NULL, parent_asin TEXT NOT NULL,
          promotion_id TEXT NOT NULL, promotion_type TEXT NOT NULL, promotion_status TEXT NOT NULL,
          discount_rate REAL NOT NULL, is_planned INTEGER NOT NULL,
          performance_index REAL NOT NULL, preset_uplift REAL NOT NULL,
          value_origin TEXT NOT NULL, method_version TEXT NOT NULL, provenance TEXT NOT NULL,
          PRIMARY KEY (date, child_asin)
        )
    """,
    "fact_child_inventory_daily": """
        CREATE TABLE fact_child_inventory_daily (
          date TEXT NOT NULL, child_asin TEXT NOT NULL, parent_asin TEXT NOT NULL,
          opening_fba_sellable INTEGER NOT NULL, received_units INTEGER NOT NULL,
          reserved_release_units INTEGER NOT NULL, other_net_flow_units INTEGER NOT NULL,
          units_sold INTEGER NOT NULL, closing_fba_sellable INTEGER NOT NULL,
          fba_reserved INTEGER NOT NULL, fba_receiving INTEGER NOT NULL, fba_inbound INTEGER NOT NULL,
          overseas_available INTEGER NOT NULL, overseas_inbound INTEGER NOT NULL,
          local_available INTEGER NOT NULL, stockout_flag INTEGER NOT NULL,
          coverage_days REAL NOT NULL, quality_status TEXT NOT NULL,
          value_origin TEXT NOT NULL, method_version TEXT NOT NULL, provenance TEXT NOT NULL,
          PRIMARY KEY (date, child_asin)
        )
    """,
    "plan_child_advertising_daily": """
        CREATE TABLE plan_child_advertising_daily (
          date TEXT NOT NULL, child_asin TEXT NOT NULL, parent_asin TEXT NOT NULL,
          planned_budget REAL NOT NULL, planned_spend REAL NOT NULL,
          planned_impressions INTEGER NOT NULL, planned_clicks INTEGER NOT NULL,
          expected_effect_ratio REAL NOT NULL, effect_source TEXT NOT NULL,
          plan_status TEXT NOT NULL, value_origin TEXT NOT NULL,
          method_version TEXT NOT NULL, provenance TEXT NOT NULL,
          PRIMARY KEY (date, child_asin)
        )
    """,
    "plan_child_price_daily": """
        CREATE TABLE plan_child_price_daily (
          date TEXT NOT NULL, child_asin TEXT NOT NULL, parent_asin TEXT NOT NULL,
          planned_list_price REAL NOT NULL, planned_selling_price REAL NOT NULL,
          planned_coupon_amount REAL NOT NULL, planned_discount_rate REAL NOT NULL,
          expected_effect_ratio REAL NOT NULL, effect_source TEXT NOT NULL,
          plan_status TEXT NOT NULL, value_origin TEXT NOT NULL,
          method_version TEXT NOT NULL, provenance TEXT NOT NULL,
          PRIMARY KEY (date, child_asin)
        )
    """,
    "plan_child_promotion_daily": """
        CREATE TABLE plan_child_promotion_daily (
          date TEXT NOT NULL, child_asin TEXT NOT NULL, parent_asin TEXT NOT NULL,
          promotion_id TEXT NOT NULL, promotion_type TEXT NOT NULL,
          promotion_status TEXT NOT NULL, planned_discount_rate REAL NOT NULL,
          preset_uplift REAL NOT NULL, expected_effect_ratio REAL NOT NULL,
          effect_source TEXT NOT NULL, value_origin TEXT NOT NULL,
          method_version TEXT NOT NULL, provenance TEXT NOT NULL,
          PRIMARY KEY (date, child_asin)
        )
    """,
    "plan_child_supply_event": """
        CREATE TABLE plan_child_supply_event (
          plan_event_id TEXT PRIMARY KEY, child_asin TEXT NOT NULL, parent_asin TEXT NOT NULL,
          planned_units INTEGER NOT NULL, source_location TEXT NOT NULL,
          destination_location TEXT NOT NULL, transport_mode TEXT NOT NULL,
          eta_earliest TEXT NOT NULL, eta_latest TEXT NOT NULL,
          event_status TEXT NOT NULL, confidence_level TEXT NOT NULL,
          value_origin TEXT NOT NULL, method_version TEXT NOT NULL, provenance TEXT NOT NULL
        )
    """,
    "config_child_inventory_policy": """
        CREATE TABLE config_child_inventory_policy (
          child_asin TEXT NOT NULL, parent_asin TEXT NOT NULL, effective_start TEXT NOT NULL,
          effective_end TEXT NOT NULL, service_level REAL NOT NULL,
          base_safety_days INTEGER NOT NULL, purchase_lead_days INTEGER NOT NULL,
          quality_check_days INTEGER NOT NULL, transport_days INTEGER NOT NULL,
          fba_receiving_days INTEGER NOT NULL, target_coverage_days INTEGER NOT NULL,
          preferred_transport_mode TEXT NOT NULL, value_origin TEXT NOT NULL,
          method_version TEXT NOT NULL, provenance TEXT NOT NULL,
          PRIMARY KEY (child_asin, effective_start)
        )
    """,
    "feature_child_demand_daily": """
        CREATE TABLE feature_child_demand_daily (
          date TEXT NOT NULL, child_asin TEXT NOT NULL, parent_asin TEXT NOT NULL,
          observed_units INTEGER NOT NULL, estimated_demand_units REAL NOT NULL,
          clean_baseline_units REAL NOT NULL, weekday_factor REAL NOT NULL,
          seasonality_factor REAL NOT NULL, lifecycle_factor REAL NOT NULL,
          advertising_effect_ratio REAL NOT NULL, price_effect_ratio REAL NOT NULL,
          promotion_effect_ratio REAL NOT NULL, demand_quality_flag TEXT NOT NULL,
          adjustment_reason TEXT NOT NULL, confidence_score REAL NOT NULL,
          is_golden_sample INTEGER NOT NULL, demo_profile_id TEXT NOT NULL,
          value_origin TEXT NOT NULL, method_version TEXT NOT NULL, provenance TEXT NOT NULL,
          PRIMARY KEY (date, child_asin)
        )
    """,
    "fact_child_forecast_run": """
        CREATE TABLE fact_child_forecast_run (
          forecast_run_id TEXT PRIMARY KEY, as_of_date TEXT NOT NULL,
          horizon_days INTEGER NOT NULL, run_mode TEXT NOT NULL,
          dataset_version TEXT NOT NULL, candidate_models TEXT NOT NULL,
          validation_days INTEGER NOT NULL, status TEXT NOT NULL,
          method_version TEXT NOT NULL, created_at TEXT NOT NULL
        )
    """,
    "fact_child_forecast_evaluation": """
        CREATE TABLE fact_child_forecast_evaluation (
          forecast_run_id TEXT NOT NULL, child_asin TEXT NOT NULL,
          model_name TEXT NOT NULL, wape REAL NOT NULL, bias REAL NOT NULL,
          mae REAL NOT NULL, validation_days INTEGER NOT NULL,
          selected INTEGER NOT NULL, confidence_score REAL NOT NULL,
          method_version TEXT NOT NULL,
          PRIMARY KEY (forecast_run_id, child_asin, model_name)
        )
    """,
    "fact_child_forecast_daily": """
        CREATE TABLE fact_child_forecast_daily (
          forecast_run_id TEXT NOT NULL, forecast_date TEXT NOT NULL,
          child_asin TEXT NOT NULL, parent_asin TEXT NOT NULL,
          baseline_units REAL NOT NULL, weekday_factor REAL NOT NULL,
          seasonality_factor REAL NOT NULL, lifecycle_factor REAL NOT NULL,
          advertising_effect_ratio REAL NOT NULL, price_effect_ratio REAL NOT NULL,
          promotion_effect_ratio REAL NOT NULL, p10_units INTEGER NOT NULL,
          p50_units INTEGER NOT NULL, p90_units INTEGER NOT NULL,
          selected_model TEXT NOT NULL, model_wape REAL NOT NULL,
          effect_source TEXT NOT NULL, confidence_score REAL NOT NULL,
          value_origin TEXT NOT NULL, method_version TEXT NOT NULL, provenance TEXT NOT NULL,
          PRIMARY KEY (forecast_run_id, forecast_date, child_asin)
        )
    """,
    "fact_child_inventory_projection_daily": """
        CREATE TABLE fact_child_inventory_projection_daily (
          forecast_run_id TEXT NOT NULL, scenario TEXT NOT NULL,
          projection_date TEXT NOT NULL, child_asin TEXT NOT NULL, parent_asin TEXT NOT NULL,
          opening_sellable INTEGER NOT NULL, confirmed_arrivals INTEGER NOT NULL,
          considered_arrivals INTEGER NOT NULL, forecast_demand INTEGER NOT NULL,
          fulfilled_units INTEGER NOT NULL, lost_sales_units INTEGER NOT NULL,
          closing_sellable INTEGER NOT NULL, safety_stock_units INTEGER NOT NULL,
          coverage_days REAL NOT NULL, risk_status TEXT NOT NULL,
          value_origin TEXT NOT NULL, method_version TEXT NOT NULL, provenance TEXT NOT NULL,
          PRIMARY KEY (forecast_run_id, scenario, projection_date, child_asin)
        )
    """,
    "fact_child_inventory_decision": """
        CREATE TABLE fact_child_inventory_decision (
          forecast_run_id TEXT NOT NULL, child_asin TEXT NOT NULL, parent_asin TEXT NOT NULL,
          base_risk_status TEXT NOT NULL, safety_breach_date TEXT NOT NULL,
          base_stockout_date TEXT NOT NULL, stress_stockout_date TEXT NOT NULL,
          latest_order_date TEXT NOT NULL, suggested_replenishment_qty INTEGER NOT NULL,
          suggested_air_qty INTEGER NOT NULL, suggested_sea_qty INTEGER NOT NULL,
          projected_lost_sales_units INTEGER NOT NULL, ending_inventory_units INTEGER NOT NULL,
          dynamic_safety_days INTEGER NOT NULL, dynamic_safety_units INTEGER NOT NULL,
          decision_summary TEXT NOT NULL, confidence_score REAL NOT NULL,
          value_origin TEXT NOT NULL, method_version TEXT NOT NULL, provenance TEXT NOT NULL,
          PRIMARY KEY (forecast_run_id, child_asin)
        )
    """,
}


INDEX_DDL = (
    "CREATE INDEX idx_child_sales_parent_date ON fact_child_sales_daily(parent_asin, date)",
    "CREATE INDEX idx_child_feature_asin_date ON feature_child_demand_daily(child_asin, date)",
    "CREATE INDEX idx_forecast_asin_date ON fact_child_forecast_daily(child_asin, forecast_date)",
    "CREATE INDEX idx_projection_asin_scenario_date ON fact_child_inventory_projection_daily(child_asin, scenario, projection_date)",
    "CREATE INDEX idx_supply_plan_asin_eta ON plan_child_supply_event(child_asin, eta_earliest)",
)


def create_v030_tables(connection: sqlite3.Connection) -> None:
    for table in TABLE_DDL:
        connection.execute("DROP TABLE IF EXISTS %s" % table)
    for ddl in TABLE_DDL.values():
        connection.execute(ddl)
    for ddl in INDEX_DDL:
        connection.execute(ddl)
    connection.commit()
