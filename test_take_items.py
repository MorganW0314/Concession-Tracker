import csv
import os
import tempfile
import unittest

from Take_items import (
    CRUNCHY_RARA_MODIFIER_PREFIX,
    ICE_CREAM_FLAVOR_SET_PREFIX,
    MODIFIER_ITEMS,
    SLUSHIE_FLAVOR_SET_PREFIX,
    _TOFTS_ICE_CREAM_SKIP_ITEMS,
    take_items,
    take_modifiers,
)


def _write_tmp_csv(rows, fieldnames=None):
    """Write rows to a temporary CSV file and return the path."""
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, newline="", encoding="utf-8"
    )
    if fieldnames is None and rows:
        fieldnames = list(rows[0].keys())
    writer = csv.DictWriter(tmp, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    tmp.close()
    return tmp.name


class ModifierItemsConstantTests(unittest.TestCase):
    """Verify MODIFIER_ITEMS and related constants are configured correctly."""

    def test_double_dip_in_modifier_items(self):
        self.assertIn("Double Dip", MODIFIER_ITEMS)

    def test_triple_dip_in_modifier_items(self):
        self.assertIn("Triple Dip", MODIFIER_ITEMS)

    def test_ice_cream_flavor_in_modifier_items(self):
        self.assertIn(ICE_CREAM_FLAVOR_SET_PREFIX, MODIFIER_ITEMS)

    def test_gatorade_still_in_modifier_items(self):
        self.assertIn("Gatorade", MODIFIER_ITEMS)
        self.assertEqual(
            MODIFIER_ITEMS["Gatorade"],
            ["Gatorade - Blue", "Gatorade - Red", "Gatorade - Yellow", "Gatorade - Orange"],
        )

    def test_slushie_and_crunchy_items_in_modifier_items(self):
        self.assertIn("Slushie", MODIFIER_ITEMS)
        self.assertIn("Crunchy Ra-Ra", MODIFIER_ITEMS)
        self.assertIn("Crunchy Rara", MODIFIER_ITEMS)
        self.assertIn("Crunchy Ra-Ra Yogurt", MODIFIER_ITEMS)

    def test_ice_cream_flavor_prefix_constant(self):
        self.assertEqual(ICE_CREAM_FLAVOR_SET_PREFIX, "Ice Cream Flavor")

    def test_new_modifier_prefix_constants(self):
        self.assertEqual(SLUSHIE_FLAVOR_SET_PREFIX, "Slushie Flavor")
        self.assertEqual(CRUNCHY_RARA_MODIFIER_PREFIX, "Crunchy")

    def test_tofts_skip_items_includes_base_flavors(self):
        for flavor in ("Cookie Monster", "Blueberry Waffle Cone", "Vanilla", "Chocolate",
                       "Cookie Dough", "Brownie Bandit", "Birthday Cake", "Mint Chip",
                       "Rainbow Sherbet", "PB S'Mores", "Cotton Candy Ice Cream",
                       "Cookies n' Cream"):
            self.assertIn(flavor, _TOFTS_ICE_CREAM_SKIP_ITEMS)

    def test_tofts_skip_items_includes_scoop_variants(self):
        for variant in (
            "Brownie Bandit Single Scoop", "Brownie Bandit Double Scoop", "Brownie Bandit Triple Scoop",
            "Cookie Monster Single Scoop", "Cookie Monster Double Scoop", "Cookie Monster Triple Scoop",
            "Vanilla Single Scoop", "Vanilla Double Scoop", "Vanilla Triple Scoop",
            # Backward-compatible CSV misspelling ("Sherbert" not "Sherbet") from POS exports
            "Rainbow Sherbert",
        ):
            self.assertIn(variant, _TOFTS_ICE_CREAM_SKIP_ITEMS)


class TakeItemsSkipTests(unittest.TestCase):
    """Verify take_items() skips ice cream items correctly."""

    def test_double_dip_skipped(self):
        path = _write_tmp_csv([
            {"Item Name": "Double Dip", "Item Variation": "Regular",
             "Units Sold": "3", "Units Refunded": "0"},
            {"Item Name": "Hot Dog", "Item Variation": "Regular",
             "Units Sold": "5", "Units Refunded": "0"},
        ])
        try:
            result = take_items(path)
            self.assertNotIn("Double Dip", result)
            self.assertIn("Hot Dog", result)
            self.assertEqual(result["Hot Dog"]["sales"], 5)
        finally:
            os.unlink(path)

    def test_single_dip_skipped(self):
        path = _write_tmp_csv([
            {"Item Name": "Single Dip", "Item Variation": "Regular",
             "Units Sold": "3", "Units Refunded": "0"},
            {"Item Name": "Hot Dog", "Item Variation": "Regular",
             "Units Sold": "2", "Units Refunded": "0"},
        ])
        try:
            result = take_items(path)
            self.assertNotIn("Single Dip", result)
            self.assertIn("Hot Dog", result)
            self.assertEqual(result["Hot Dog"]["sales"], 2)
        finally:
            os.unlink(path)

    def test_triple_dip_skipped(self):
        path = _write_tmp_csv([
            {"Item Name": "Triple Dip", "Item Variation": "Regular",
             "Units Sold": "2", "Units Refunded": "0"},
        ])
        try:
            result = take_items(path)
            self.assertNotIn("Triple Dip", result)
        finally:
            os.unlink(path)

    def test_legacy_scoop_variants_skipped(self):
        legacy_items = [
            "Cookie Monster Single Scoop",
            "Cookie Monster Double Scoop",
            "Cookie Monster Triple Scoop",
            "Blueberry Waffle Cone Double Scoop",
            "Vanilla",
            "Rainbow Sherbert",
        ]
        rows = [
            {"Item Name": item, "Item Variation": "Regular",
             "Units Sold": "2", "Units Refunded": "0"}
            for item in legacy_items
        ]
        rows.append({
            "Item Name": "Soft Pretzel", "Item Variation": "Regular",
            "Units Sold": "10", "Units Refunded": "0",
        })
        path = _write_tmp_csv(rows)
        try:
            result = take_items(path)
            for item in legacy_items:
                self.assertNotIn(item, result, f"Expected {item!r} to be skipped")
            self.assertIn("Soft Pretzel", result)
        finally:
            os.unlink(path)

    def test_non_ice_cream_items_still_processed(self):
        path = _write_tmp_csv([
            {"Item Name": "Nachos & Cheese", "Item Variation": "Regular",
             "Units Sold": "4", "Units Refunded": "1"},
            {"Item Name": "Gatorade", "Item Variation": "Regular",
             "Units Sold": "6", "Units Refunded": "0"},
        ])
        try:
            result = take_items(path)
            # Nachos & Cheese is not a modifier item or ice cream, so it should appear.
            self.assertIn("Nachos & Cheese", result)
            self.assertEqual(result["Nachos & Cheese"]["sales"], 3)
            # Gatorade is still in MODIFIER_ITEMS and should be skipped.
            self.assertNotIn("Gatorade", result)
        finally:
            os.unlink(path)

    def test_slushie_and_crunchy_base_items_are_skipped(self):
        path = _write_tmp_csv([
            {"Item Name": "Slushie", "Item Variation": "Regular", "Units Sold": "4", "Units Refunded": "0"},
            {"Item Name": "Crunchy Ra-Ra", "Item Variation": "Regular", "Units Sold": "2", "Units Refunded": "0"},
            {"Item Name": "Crunchy Ra-Ra Yogurt", "Item Variation": "Regular", "Units Sold": "3", "Units Refunded": "0"},
            {"Item Name": "Hot Dog", "Item Variation": "Regular", "Units Sold": "1", "Units Refunded": "0"},
        ])
        try:
            result = take_items(path)
            self.assertNotIn("Slushie", result)
            self.assertNotIn("Crunchy Ra-Ra", result)
            self.assertNotIn("Crunchy Ra-Ra Yogurt", result)
            self.assertEqual(result["Hot Dog"]["sales"], 1)
        finally:
            os.unlink(path)


class TakeModifiersIceCreamTests(unittest.TestCase):
    """Verify take_modifiers() correctly parses ice cream flavor modifier CSVs."""

    def _make_ice_cream_csv(self, rows):
        """Write a modifier CSV with Ice Cream Flavor N format."""
        return _write_tmp_csv(rows, fieldnames=["Modifier Set", "Modifier", "Qty Sold", "Gross Sales"])

    def test_single_flavor_set_basic(self):
        path = self._make_ice_cream_csv([
            {"Modifier Set": "Ice Cream Flavor 1", "Modifier": "Cookie Monster",
             "Qty Sold": "2", "Gross Sales": "$0.00"},
        ])
        try:
            result = take_modifiers(path)
            self.assertIn("Cookie Monster", result)
            self.assertEqual(result["Cookie Monster"]["sales"], 2)
            # Should NOT include the prefixed form
            self.assertNotIn("Ice Cream Flavor Cookie Monster", result)
        finally:
            os.unlink(path)

    def test_flavor_accumulated_across_all_flavor_sets(self):
        """Cookie Monster appearing in Flavor 1, 2, and 3 should be summed."""
        path = self._make_ice_cream_csv([
            {"Modifier Set": "Ice Cream Flavor 1", "Modifier": "Blueberry Waffle Cone",
             "Qty Sold": "1", "Gross Sales": "$0.00"},
            {"Modifier Set": "Ice Cream Flavor 1", "Modifier": "Cookie Monster",
             "Qty Sold": "2", "Gross Sales": "$0.00"},
            {"Modifier Set": "Ice Cream Flavor 2", "Modifier": "Cookie Dough",
             "Qty Sold": "1", "Gross Sales": "$0.00"},
            {"Modifier Set": "Ice Cream Flavor 2", "Modifier": "Cookie Monster",
             "Qty Sold": "1", "Gross Sales": "$0.00"},
            {"Modifier Set": "Ice Cream Flavor 2", "Modifier": "Cookies n' Cream",
             "Qty Sold": "1", "Gross Sales": "$0.00"},
            {"Modifier Set": "Ice Cream Flavor 3", "Modifier": "Blueberry Waffle Cone",
             "Qty Sold": "1", "Gross Sales": "$0.00"},
            {"Modifier Set": "Ice Cream Flavor 3", "Modifier": "Cookie Monster",
             "Qty Sold": "1", "Gross Sales": "$0.00"},
        ])
        try:
            result = take_modifiers(path)
            # Cookie Monster: 2 + 1 + 1 = 4
            self.assertEqual(result["Cookie Monster"]["sales"], 4)
            # Blueberry Waffle Cone: 1 + 1 = 2
            self.assertEqual(result["Blueberry Waffle Cone"]["sales"], 2)
            # Cookie Dough: 1
            self.assertEqual(result["Cookie Dough"]["sales"], 1)
            # Cookies n' Cream: 1
            self.assertEqual(result["Cookies n' Cream"]["sales"], 1)
        finally:
            os.unlink(path)

    def test_gross_sales_dollar_values_do_not_corrupt_qty(self):
        """$0.00 in Gross Sales column must not add to quantity."""
        path = self._make_ice_cream_csv([
            {"Modifier Set": "Ice Cream Flavor 1", "Modifier": "Vanilla",
             "Qty Sold": "3", "Gross Sales": "$0.00"},
        ])
        try:
            result = take_modifiers(path)
            # Only the 3 from Qty Sold should be counted; $0.00 → 0
            self.assertEqual(result["Vanilla"]["sales"], 3)
        finally:
            os.unlink(path)

    def test_row_shape_is_correct(self):
        """Each flavor entry has all required inventory fields."""
        path = self._make_ice_cream_csv([
            {"Modifier Set": "Ice Cream Flavor 1", "Modifier": "Chocolate",
             "Qty Sold": "5", "Gross Sales": "$0.00"},
        ])
        try:
            result = take_modifiers(path)
            self.assertIn("Chocolate", result)
            entry = result["Chocolate"]
            self.assertEqual(entry["starting"], 0)
            self.assertEqual(entry["deliveries"], 0)
            self.assertEqual(entry["sales"], 5)
            self.assertEqual(entry["spoilage"], 0)
        finally:
            os.unlink(path)

    def test_gatorade_modifier_still_uses_prefixed_name(self):
        """Gatorade modifiers must NOT be affected by the ice cream path."""
        path = _write_tmp_csv([
            {"Modifier Set": "Gatorade Flavor", "Modifier": "Blue", "04/01-04/07": "4"},
        ])
        try:
            result = take_modifiers(path)
            self.assertIn("Gatorade - Blue", result)
            self.assertEqual(result["Gatorade - Blue"]["sales"], 4)
            self.assertNotIn("Blue", result)
        finally:
            os.unlink(path)

    def test_slushie_flavor_modifier_uses_slushie_dash_name(self):
        path = _write_tmp_csv([
            {"Modifier Set": "Slushie Flavor", "Modifier": "Mango", "Qty Sold": "3", "Gross Sales": "$0.00"},
            {"Modifier Set": "Slushie Flavor", "Modifier": "Mango", "Qty Sold": "2", "Gross Sales": "$0.00"},
        ])
        try:
            result = take_modifiers(path)
            self.assertEqual(result["Slushie - Mango"]["sales"], 5)
        finally:
            os.unlink(path)

    def test_crunchy_rara_modifier_uses_crunchy_dash_name(self):
        path = _write_tmp_csv([
            {"Modifier Set": "Crunchy Ra-Ra Flavor", "Modifier": "Strawberry", "Qty Sold": "1", "Gross Sales": "$0.00"},
            {"Modifier Set": "Crunchy Rara Flavor", "Modifier": "Strawberry", "Qty Sold": "2", "Gross Sales": "$0.00"},
        ])
        try:
            result = take_modifiers(path)
            self.assertEqual(result["Crunchy Ra-Ra - Strawberry"]["sales"], 3)
        finally:
            os.unlink(path)

    def test_empty_modifier_csv_returns_empty_dict(self):
        """A modifier CSV with no data rows returns {}."""
        path = _write_tmp_csv(
            [],
            fieldnames=["Modifier Set", "Modifier", "Qty Sold", "Gross Sales"],
        )
        try:
            result = take_modifiers(path)
            self.assertEqual(result, {})
        finally:
            os.unlink(path)

    def test_missing_file_returns_empty_dict(self):
        missing_path = os.path.join(
            tempfile.gettempdir(), "nonexistent_modifier_file_xyz.csv"
        )
        result = take_modifiers(missing_path)
        self.assertEqual(result, {})


if __name__ == "__main__":
    unittest.main()
