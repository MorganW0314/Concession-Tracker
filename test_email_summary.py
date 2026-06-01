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

from email_summary import generate_email_body, get_stands_with_discrepancies, _get_category_for_item, _negative_from_rows


class EmailSummaryTests(unittest.TestCase):
    def test_negative_from_rows_flags_negative_expected_without_actual(self):
        rows = [
            {"item": "Short Item", "expected": 10.0, "actual": 8.0, "variance": -2.0},
            {"item": "Negative Expected", "expected": -5.0, "actual": None, "variance": None},
            {"item": "Fine Item", "expected": 12.0, "actual": 12.0, "variance": 0.0},
        ]
        flagged = _negative_from_rows(rows)
        self.assertEqual([row["item"] for row in flagged], ["Short Item", "Negative Expected"])

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
                {"item": "Pepsi", "sales": 4.0, "expected": 4.0, "actual": 4.0, "variance": 0.0},
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
        self.assertIn("Vanilla................. 2.00 tubs expected  ⚠️  Variance: -1.50 tubs", body)
        self.assertIn("FOUNTAIN DRINKS", body)
        self.assertIn("Pepsi................... 4 bags expected", body)
        self.assertIn("FOOD", body)
        self.assertIn("Hot Dog................. 24 expected  ⚠️  Variance: -3.00", body)
        self.assertIn("Stand B", body)
        self.assertIn("✅ All clear", body)

    def test_generate_email_body_flags_negative_expected_without_actual(self):
        stand_names = ["Stand A", "Stand B"]
        stand_a_rows = [
            {"item": "Hot Dog", "sales": 5.0, "expected": -5.0, "actual": None, "variance": None},
        ]
        negative_items = {"Stand A": _negative_from_rows(stand_a_rows)}
        stand_rows = {"Stand A": stand_a_rows}

        body = generate_email_body(stand_names, negative_items, stand_rows=stand_rows, week_label="Week of 05-20-2026")

        self.assertIn("- Stands with Discrepancies: 1", body)
        self.assertIn("- Items with Negative Variance: 1", body)
        self.assertIn("Hot Dog................. -5 expected  ⚠️  Variance: -5.00", body)

    def test_get_category_for_item(self):
        self.assertEqual(_get_category_for_item("Vanilla"), "ICE_CREAM_TOFTS")
        self.assertEqual(_get_category_for_item("Pepsi"), "FOUNTAIN_DRINKS")
        self.assertEqual(_get_category_for_item("Hot Dog"), "FOOD")
        self.assertIsNone(_get_category_for_item("Unknown Item"))

    def test_souvenir_cups_appears_in_email_with_variance(self):
        stand_names = ["Stand A"]
        stand_a_rows = [
            {"item": "Souvenir Cups", "sales": 5.0, "expected": 10.0, "actual": 7.0,
             "variance": -3.0, "counted": True},
        ]
        negative_items = {"Stand A": _negative_from_rows(stand_a_rows)}
        stand_rows = {"Stand A": stand_a_rows}

        body = generate_email_body(stand_names, negative_items, stand_rows=stand_rows,
                                   week_label="Week of 05-20-2026")

        self.assertIn("SNACKS", body)
        self.assertIn("Souvenir Cups", body)
        self.assertIn("Souvenir Cups........... 10 expected  ⚠️  Variance: -3.00", body)
        self.assertIn("- Items with Negative Variance: 1", body)

    def test_other_disposables_excluded_from_email(self):
        stand_names = ["Stand A"]
        stand_a_rows = [
            {"item": "Napkins", "sales": 0.0, "expected": 50.0, "actual": 45.0,
             "variance": -5.0, "counted": True},
        ]
        negative_items = {"Stand A": _negative_from_rows(stand_a_rows)}
        stand_rows = {"Stand A": stand_a_rows}

        body = generate_email_body(stand_names, negative_items, stand_rows=stand_rows,
                                   week_label="Week of 05-20-2026")

        self.assertNotIn("Napkins", body)
        self.assertIn("✅ All clear", body)

    def test_not_counted_item_shows_marker_and_excluded_from_discrepancy(self):
        stand_names = ["Stand A"]
        stand_a_rows = [
            {"item": "Hot Dog", "sales": 5.0, "expected": 10.0, "actual": 10.0,
             "variance": 0.0, "counted": False},
        ]
        raw_negative = {"Stand A": _negative_from_rows(stand_a_rows)}
        negative_items = {k: v for k, v in raw_negative.items() if v}
        stand_rows = {"Stand A": stand_a_rows}

        body = generate_email_body(stand_names, negative_items, stand_rows=stand_rows,
                                   week_label="Week of 05-20-2026")

        self.assertIn("🔲 no count entered", body)
        self.assertNotIn("⚠️", body)
        self.assertIn("- Stands with Discrepancies: 0", body)
        self.assertIn("- Items with Negative Variance: 0", body)

    def test_counted_short_item_flagged_as_discrepancy(self):
        stand_names = ["Stand A"]
        stand_a_rows = [
            {"item": "Hot Dog", "sales": 5.0, "expected": 10.0, "actual": 7.0,
             "variance": -3.0, "counted": True},
        ]
        negative_items = {"Stand A": _negative_from_rows(stand_a_rows)}
        stand_rows = {"Stand A": stand_a_rows}

        body = generate_email_body(stand_names, negative_items, stand_rows=stand_rows,
                                   week_label="Week of 05-20-2026")

        self.assertIn("⚠️", body)
        self.assertIn("Variance: -3.00", body)
        self.assertIn("- Stands with Discrepancies: 1", body)
        self.assertIn("- Items with Negative Variance: 1", body)
        self.assertNotIn("🔲", body)


if __name__ == "__main__":
    unittest.main()
