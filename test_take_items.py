import csv
import os
import tempfile
import unittest

from Take_items import take_items


class TakeItemsTests(unittest.TestCase):
    def test_take_items_skips_single_dip_modifier_item(self):
        with tempfile.NamedTemporaryFile("w", newline="", delete=False, encoding="utf-8") as tmp:
            writer = csv.DictWriter(
                tmp,
                fieldnames=["Item Name", "Units Sold", "Units Refunded"],
            )
            writer.writeheader()
            writer.writerow({"Item Name": "Single Dip", "Units Sold": "3", "Units Refunded": "0"})
            writer.writerow({"Item Name": "Hot Dog", "Units Sold": "2", "Units Refunded": "0"})
            csv_path = tmp.name

        try:
            rows = take_items(csv_path)
        finally:
            os.unlink(csv_path)

        self.assertNotIn("Single Dip", rows)
        self.assertEqual(rows["Hot Dog"]["sales"], 2)


if __name__ == "__main__":
    unittest.main()
