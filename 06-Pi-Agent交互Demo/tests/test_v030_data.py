import json
import sqlite3
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT.parent / "02-产品销售库存模块" / "02-数据构建" / "v0.3.0"
DATABASE = DATA_DIR / "bamboocool_product_sales_inventory_v0.3.0.sqlite"


class V030DataContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.connection = sqlite3.connect("file:%s?mode=ro" % DATABASE, uri=True)

    @classmethod
    def tearDownClass(cls):
        cls.connection.close()

    def scalar(self, sql):
        return self.connection.execute(sql).fetchone()[0]

    def test_quality_report_passes_every_gate(self):
        report = json.loads((DATA_DIR / "quality_report.json").read_text(encoding="utf-8"))
        self.assertTrue(report["all_checks_passed"])
        self.assertEqual([item for item in report["checks"] if not item["passed"]], [])

    def test_complete_child_daily_grain(self):
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM dim_product_child"), 342)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM fact_child_sales_daily"), 342 * 730)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM fact_child_forecast_daily"), 342 * 90)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM fact_child_inventory_projection_daily"), 342 * 90 * 3)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM dim_demo_profile"), 5)

    def test_dates_and_quantiles(self):
        self.assertEqual(self.scalar("SELECT MIN(date) FROM fact_child_sales_daily"), "2024-08-04")
        self.assertEqual(self.scalar("SELECT MAX(date) FROM fact_child_sales_daily"), "2026-08-03")
        self.assertEqual(self.scalar("SELECT MIN(forecast_date) FROM fact_child_forecast_daily"), "2026-08-04")
        self.assertEqual(self.scalar("SELECT MAX(forecast_date) FROM fact_child_forecast_daily"), "2026-11-01")
        violations = self.scalar("SELECT COUNT(*) FROM fact_child_forecast_daily WHERE p10_units > p50_units OR p50_units > p90_units")
        self.assertEqual(violations, 0)


if __name__ == "__main__":
    unittest.main()
