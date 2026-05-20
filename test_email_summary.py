import unittest
import sys
import types


if "google.oauth2.service_account" not in sys.modules:
    google_module = types.ModuleType("google")
    oauth2_module = types.ModuleType("google.oauth2")
    service_account_module = types.ModuleType("google.oauth2.service_account")

    class _Credentials:
        @staticmethod
        def from_service_account_file(*args, **kwargs):
            return None

    service_account_module.Credentials = _Credentials
    oauth2_module.service_account = service_account_module
    google_module.oauth2 = oauth2_module
    sys.modules["google"] = google_module
    sys.modules["google.oauth2"] = oauth2_module
    sys.modules["google.oauth2.service_account"] = service_account_module

if "googleapiclient.discovery" not in sys.modules:
    googleapiclient_module = types.ModuleType("googleapiclient")
    discovery_module = types.ModuleType("googleapiclient.discovery")

    def _build(*args, **kwargs):
        return None

    discovery_module.build = _build
    googleapiclient_module.discovery = discovery_module
    sys.modules["googleapiclient"] = googleapiclient_module
    sys.modules["googleapiclient.discovery"] = discovery_module

from email_summary import generate_email_body, get_stands_with_discrepancies, _get_category_for_item


class EmailSummaryTests(unittest.TestCase):
    def test_get_stands_with_discrepancies(self):
        stand_names = ["Stand A", "Stand B", "Stand C"]
        negative_items = {
            "Stand A": [{"item": "Hot Dog", "expected": 10, "actual": 8, "variance": -2}],
            "Stand C": [{"item": "Nacho Chips", "expected": 12, "actual": 9, "variance": -3}],
        }
        status = get_stands_with_discrepancies(stand_names, negative_items)
        self.assertEqual(status["Stand A"], "❌ 1 items flagged")
        self.assertEqual(status["Stand B"], "✅ All clear")
        self.assertEqual(status["Stand C"], "❌ 1 items flagged")

    def test_generate_email_body_sections(self):
        stand_names = ["Stand A", "Stand B"]
        negative_items = {
            "Stand A": [
                {"item": "Hot Dog", "expected": 10.0, "actual": 8.0, "variance": -2.0},
                {"item": "Nacho Chips", "expected": 20.0, "actual": 18.0, "variance": -2.0},
            ]
        }
        stand_rows = {
            "Stand A": [
                {"item": "Vanilla", "sales": 2.0, "expected": 2.0, "actual": 0.5, "variance": -1.5},
                {"item": "Pepsi", "sales": 64.0, "expected": 1280.0, "actual": 1280.0, "variance": 0.0},
                {"item": "Hot Dog", "sales": 12.0, "expected": 24.0, "actual": 21.0, "variance": -3.0},
            ],
            "Stand B": [
                {"item": "Unknown Item", "sales": 1.0, "expected": 5.0, "actual": 5.0, "variance": 0.0},
                {"item": "Airheads", "sales": 0.0, "expected": 0.0, "actual": 0.0, "variance": 0.0},
            ],
        }
        body = generate_email_body(stand_names, negative_items, stand_rows=stand_rows, week_label="Week of 05-20-2026")
        self.assertIn("Weekly Inventory Summary — Week of 05-20-2026", body)
        self.assertIn("Quick Overview", body)
        self.assertIn("- Total Stands: 2", body)
        self.assertIn("- Stands with Discrepancies: 1", body)
        self.assertIn("- Items with Negative Variance: 2", body)
        self.assertIn("Stand A", body)
        self.assertIn("ICE CREAM", body)
        self.assertIn("Vanilla................. 2.00 tubs expected  ⚠️  Variance: -1.50", body)
        self.assertIn("FOUNTAIN DRINKS", body)
        self.assertIn("Pepsi................... 1280 oz expected", body)
        self.assertIn("FOOD", body)
        self.assertIn("Hot Dog................. 24 expected  ⚠️  Variance: -3.00", body)
        self.assertIn("Stand B", body)
        self.assertIn("✅ All clear", body)

    def test_get_category_for_item(self):
        self.assertEqual(_get_category_for_item("Vanilla"), "ICE_CREAM_TOFTS")
        self.assertEqual(_get_category_for_item("Pepsi"), "FOUNTAIN_DRINKS")
        self.assertEqual(_get_category_for_item("Hot Dog"), "FOOD")
        self.assertIsNone(_get_category_for_item("Unknown Item"))


if __name__ == "__main__":
    unittest.main()
