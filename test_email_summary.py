import unittest

from email_summary import generate_email_body, get_stands_with_discrepancies


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
        body = generate_email_body(stand_names, negative_items)
        self.assertIn("Section 1: Quick Overview", body)
        self.assertIn("- Total Stands: 2", body)
        self.assertIn("- Stands with Discrepancies: 1", body)
        self.assertIn("- Items with Negative Variance: 2", body)
        self.assertIn("Section 2: Stands Status", body)
        self.assertIn("Stand B: ✅ All clear", body)
        self.assertIn("Section 3: Items Flagged as Negative (Discrepancies)", body)
        self.assertIn("Hot Dog: Expected 10.00, Actual 8.00, Variance -2.00", body)


if __name__ == "__main__":
    unittest.main()
