import csv
import os
import sys
import tempfile
import types
import unittest


def _install_google_stubs():
    google_mod = types.ModuleType("google")
    oauth2_mod = types.ModuleType("google.oauth2")
    service_account_mod = types.ModuleType("google.oauth2.service_account")

    class _Credentials:
        @staticmethod
        def from_service_account_file(*args, **kwargs):
            return object()

    service_account_mod.Credentials = _Credentials

    googleapiclient_mod = types.ModuleType("googleapiclient")
    discovery_mod = types.ModuleType("googleapiclient.discovery")

    def _build(*args, **kwargs):
        return object()

    discovery_mod.build = _build

    sys.modules.setdefault("google", google_mod)
    sys.modules.setdefault("google.oauth2", oauth2_mod)
    sys.modules.setdefault("google.oauth2.service_account", service_account_mod)
    sys.modules.setdefault("googleapiclient", googleapiclient_mod)
    sys.modules.setdefault("googleapiclient.discovery", discovery_mod)


_install_google_stubs()

from Call_sheets import (
    BOTTLED_DRINKS,
    CANDY,
    FOOD,
    FOUNTAIN_DRINKS,
    LOCATION_SPECIFIC_ITEM_STANDS,
    NOVELTIES,
    RAINBOW_SHERBET_FLOAT_STANDS,
    SLUSHIE_FLAVORS,
    SNACKS,
    merge_modifier_rows,
)
from Take_items import (
    BLOOM_POP_FLAVOR_SET_PREFIX,
    COMBO_BREAKDOWN,
    CRUNCHY_RARA_MODIFIER_PREFIX,
    HAM_CHICKEN_MODIFIER_SET,
    ICE_CREAM_FLAVOR_SET_PREFIX,
    ICE_CREAM_TOPPINGS_PREFIX,
    MODIFIER_ITEMS,
    POPPI_FLAVOR_SET_PREFIX,
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
            ["Gatorade - Blue", "Gatorade - Red", "Gatorade - Yellow"],
        )
        self.assertNotIn("Gatorade - Orange", MODIFIER_ITEMS["Gatorade"])

    def test_slushie_and_crunchy_items_in_modifier_items(self):
        self.assertIn("Slushie", MODIFIER_ITEMS)
        self.assertIn("Flavor", MODIFIER_ITEMS)
        self.assertIn("Crunchy Ra-Ra", MODIFIER_ITEMS)
        self.assertIn("Crunchy Rara", MODIFIER_ITEMS)
        self.assertIn("Crunchy Ra-Ra Yogurt", MODIFIER_ITEMS)

    def test_new_modifier_items_added(self):
        for item in (
            "Ice Cream Toppings",
            "Fountain Drink Flavor",
            "Fountain Soda",
            HAM_CHICKEN_MODIFIER_SET,
            "Iced Coffee",
            "Chocolate Bar Flavor",
            "Chocolate Bars",
            "M&Ms Flavor",
            "M&Ms",
            "Soda Can",
            "Soda can",
            "Sunflower Seed Flavors",
            "Sunflower Seeds",
            "Bloom Pop",
            "Poppi",
            "Single-Dip",
        ):
            self.assertIn(item, MODIFIER_ITEMS)

    def test_ice_cream_flavor_prefix_constant(self):
        self.assertEqual(ICE_CREAM_FLAVOR_SET_PREFIX, "Ice Cream Flavor")

    def test_new_modifier_prefix_constants(self):
        self.assertEqual(SLUSHIE_FLAVOR_SET_PREFIX, "Slushie")
        self.assertEqual(CRUNCHY_RARA_MODIFIER_PREFIX, "Crunchy")
        self.assertEqual(BLOOM_POP_FLAVOR_SET_PREFIX, "Bloom Pop")
        self.assertEqual(POPPI_FLAVOR_SET_PREFIX, "Poppi")
        self.assertEqual(ICE_CREAM_TOPPINGS_PREFIX, "Ice Cream Toppings")
        self.assertEqual(HAM_CHICKEN_MODIFIER_SET, "Ham Sandwich OR Chicken Salad")

    def test_combo_breakdown_required_entries_exist(self):
        self.assertEqual(
            COMBO_BREAKDOWN["Chili Cheese Dog COMBO"],
            ["Chili Cheese Dog", "Assorted Chips"],
        )
        self.assertEqual(
            COMBO_BREAKDOWN["Chili Cheese Dog Combo Meal"],
            ["Chili Cheese Dog", "Assorted Chips"],
        )
        self.assertEqual(
            COMBO_BREAKDOWN["Pulled Pork COMBO"],
            ["Pulled Pork Sandwich", "Assorted Chips"],
        )
        self.assertEqual(
            COMBO_BREAKDOWN["Chicken Salad OR Ham Sandwich COMBO"],
            ["Assorted Chips"],
        )
        self.assertEqual(
            COMBO_BREAKDOWN["Hot Dog COMBO"],
            ["Hot Dog", "Assorted Chips"],
        )
        self.assertEqual(
            COMBO_BREAKDOWN["Pizza COMBO"],
            ["Pizza Slice", "Assorted Chips"],
        )

    def test_tofts_skip_items_includes_base_flavors(self):
        for flavor in ("Cookie Monster", "Blueberry Waffle Cone", "Vanilla", "Chocolate",
                       "Cookie Dough", "Brownie Bandit", "Birthday Cake", "Mint Chip",
                       "Rainbow Sherbet", "PB S'Mores", "Cookies n' Cream"):
            self.assertIn(flavor, _TOFTS_ICE_CREAM_SKIP_ITEMS)
        # Square/POS exports have used both Cotton Candy names; keep both skipped.
        self.assertIn("Cotton Candy", _TOFTS_ICE_CREAM_SKIP_ITEMS)
        self.assertIn("Cotton Candy Ice Cream", _TOFTS_ICE_CREAM_SKIP_ITEMS)

    def test_tofts_skip_items_includes_scoop_variants(self):
        for variant in (
            "Brownie Bandit Single Scoop", "Brownie Bandit Double Scoop", "Brownie Bandit Triple Scoop",
            "Cookie Monster Single Scoop", "Cookie Monster Double Scoop", "Cookie Monster Triple Scoop",
            "Vanilla Single Scoop", "Vanilla Double Scoop", "Vanilla Triple Scoop",
            "Blueberry Waffle Cone Cone",
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
            {"Item Name": "Single-Dip", "Item Variation": "Regular",
             "Units Sold": "2", "Units Refunded": "0"},
            {"Item Name": "Hot Dog", "Item Variation": "Regular",
             "Units Sold": "2", "Units Refunded": "0"},
        ])
        try:
            result = take_items(path)
            self.assertNotIn("Single Dip", result)
            self.assertNotIn("Single-Dip", result)
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

    def test_souvenir_cup_alias_maps_sales_to_souvenir_cups(self):
        path = _write_tmp_csv([
            {"Item Name": "Souvenir Cup", "Item Variation": "Regular",
             "Units Sold": "17", "Units Refunded": "0"},
        ])
        try:
            result = take_items(path)
            self.assertIn("Souvenir Cups", result)
            self.assertNotIn("Souvenir Cup", result)
            self.assertEqual(result["Souvenir Cups"]["sales"], 17)
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

    def test_new_modifier_base_items_are_skipped(self):
        path = _write_tmp_csv([
            {"Item Name": "Ice Cream Toppings", "Item Variation": "Regular", "Units Sold": "4", "Units Refunded": "0"},
            {"Item Name": "Fountain Soda", "Item Variation": "Regular", "Units Sold": "3", "Units Refunded": "0"},
            {"Item Name": "Ham Sandwich OR Chicken Salad", "Item Variation": "Regular", "Units Sold": "1", "Units Refunded": "0"},
            {"Item Name": "Iced Coffee", "Item Variation": "Regular", "Units Sold": "2", "Units Refunded": "0"},
            {"Item Name": "Chocolate Bars", "Item Variation": "Regular", "Units Sold": "1", "Units Refunded": "0"},
            {"Item Name": "M&Ms", "Item Variation": "Regular", "Units Sold": "1", "Units Refunded": "0"},
            {"Item Name": "Soda can", "Item Variation": "Regular", "Units Sold": "1", "Units Refunded": "0"},
            {"Item Name": "Sunflower Seeds", "Item Variation": "Regular", "Units Sold": "1", "Units Refunded": "0"},
            {"Item Name": "Hot Dog", "Item Variation": "Regular", "Units Sold": "2", "Units Refunded": "0"},
        ])
        try:
            result = take_items(path)
            self.assertNotIn("Ice Cream Toppings", result)
            self.assertNotIn("Fountain Soda", result)
            self.assertNotIn("Ham Sandwich OR Chicken Salad", result)
            self.assertNotIn("Iced Coffee", result)
            self.assertNotIn("Chocolate Bars", result)
            self.assertNotIn("M&Ms", result)
            self.assertNotIn("Soda can", result)
            self.assertNotIn("Sunflower Seeds", result)
            self.assertEqual(result["Hot Dog"]["sales"], 2)
        finally:
            os.unlink(path)

    def test_bloom_pop_and_poppi_base_items_are_skipped(self):
        """Base 'Bloom Pop' and 'Poppi' items must be skipped in take_items()."""
        path = _write_tmp_csv([
            {"Item Name": "Bloom Pop", "Item Variation": "Regular",
             "Units Sold": "5", "Units Refunded": "0"},
            {"Item Name": "Poppi", "Item Variation": "Regular",
             "Units Sold": "3", "Units Refunded": "0"},
            {"Item Name": "Hot Dog", "Item Variation": "Regular",
             "Units Sold": "2", "Units Refunded": "0"},
        ])
        try:
            result = take_items(path)
            self.assertNotIn("Bloom Pop", result)
            self.assertNotIn("Poppi", result)
            self.assertEqual(result["Hot Dog"]["sales"], 2)
        finally:
            os.unlink(path)

    def test_cotton_candy_candy_category_is_not_skipped_and_refund_applies(self):
        fieldnames = [
            "Item Name", "Item Variation", "SKU", "Category", "Items Sold",
            "Gross Sales", "Items Refunded", "Refunds", "Discounts & Comps",
            "Net Sales", "Tax", "Unit", "Units Sold", "Units Refunded",
        ]
        path = _write_tmp_csv([
            {
                "Item Name": "Cotton Candy",
                "Item Variation": "Regular",
                "SKU": ".965",
                "Category": "Candy",
                "Items Sold": "202",
                "Gross Sales": "$808.00",
                "Items Refunded": "-1",
                "Refunds": "-$4.00",
                "Discounts & Comps": "-$6.00",
                "Net Sales": "$798.00",
                "Tax": "$0.00",
                "Unit": "ea",
                "Units Sold": "202",
                "Units Refunded": "-1",
            },
        ], fieldnames=fieldnames)
        try:
            result = take_items(path)
            self.assertIn("Cotton Candy", result)
            self.assertEqual(result["Cotton Candy"]["sales"], 201)
        finally:
            os.unlink(path)

    def test_ice_cream_named_rows_still_skipped_without_candy_category(self):
        path = _write_tmp_csv([
            {"Item Name": "Cotton Candy", "Item Variation": "Regular", "Category": "", "Units Sold": "9", "Units Refunded": "0"},
            {"Item Name": "Cotton Candy", "Item Variation": "Regular", "Category": "Toft's Ice Cream", "Units Sold": "7", "Units Refunded": "0"},
            {"Item Name": "Vanilla", "Item Variation": "Regular", "Category": "", "Units Sold": "5", "Units Refunded": "0"},
            {"Item Name": "Hot Dog", "Item Variation": "Regular", "Category": "Food", "Units Sold": "2", "Units Refunded": "0"},
        ])
        try:
            result = take_items(path)
            self.assertNotIn("Cotton Candy", result)
            self.assertNotIn("Vanilla", result)
            self.assertEqual(result["Hot Dog"]["sales"], 2)
        finally:
            os.unlink(path)


    def test_new_combo_breakdown_items_are_expanded(self):
        path = _write_tmp_csv([
            {"Item Name": "Pizza COMBO", "Item Variation": "Regular", "Units Sold": "3", "Units Refunded": "1"},
            {"Item Name": "Pulled Pork COMBO", "Item Variation": "Regular", "Units Sold": "2", "Units Refunded": "0"},
            {"Item Name": "Chicken Salad OR Ham Sandwich COMBO", "Item Variation": "Regular", "Units Sold": "4", "Units Refunded": "1"},
        ])
        try:
            result = take_items(path)
            self.assertEqual(result["Pizza Slice"]["sales"], 2)
            self.assertEqual(result["Pulled Pork Sandwich"]["sales"], 2)
            self.assertEqual(result["Assorted Chips"]["sales"], 7)
            self.assertNotIn("Pizza COMBO", result)
            self.assertNotIn("Pulled Pork COMBO", result)
            self.assertNotIn("Chicken Salad OR Ham Sandwich COMBO", result)
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
            {"Modifier Set": "Slushie", "Modifier": "Mango", "Qty Sold": "3", "Gross Sales": "$0.00"},
            {"Modifier Set": "Flavor", "Modifier": "Mango", "Qty Sold": "2", "Gross Sales": "$0.00"},
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

    def test_new_modifier_set_name_construction(self):
        path = _write_tmp_csv([
            {"Modifier Set": "Ice Cream Toppings", "Modifier": "Rainbow Sprinkles", "Qty Sold": "3", "Gross Sales": "$0.00"},
            {"Modifier Set": "Fountain Drink Flavor", "Modifier": "RC", "Qty Sold": "4", "Gross Sales": "$0.00"},
            {"Modifier Set": "Fountain Drink Flavor", "Modifier": "Coke", "Qty Sold": "2", "Gross Sales": "$0.00"},
            {"Modifier Set": "Ham Sandwich OR Chicken Salad", "Modifier": "Ham Sandwich", "Qty Sold": "5", "Gross Sales": "$0.00"},
            {"Modifier Set": "Ham Sandwich OR Chicken Salad", "Modifier": "Chicken Salad Sandwich", "Qty Sold": "1", "Gross Sales": "$0.00"},
            {"Modifier Set": "Iced Coffee", "Modifier": "Mocha", "Qty Sold": "5", "Gross Sales": "$0.00"},
            {"Modifier Set": "Chocolate Bar Flavor", "Modifier": "Milky Way", "Qty Sold": "1", "Gross Sales": "$0.00"},
            {"Modifier Set": "M&Ms Flavor", "Modifier": "Peanut", "Qty Sold": "2", "Gross Sales": "$0.00"},
            {"Modifier Set": "Soda Can", "Modifier": "Sprite", "Qty Sold": "3", "Gross Sales": "$0.00"},
            {"Modifier Set": "Sunflower Seed Flavors", "Modifier": "Dill Pickle", "Qty Sold": "2", "Gross Sales": "$0.00"},
        ])
        try:
            result = take_modifiers(path)
            self.assertEqual(result["Rainbow Sprinkles"]["sales"], 3)
            self.assertEqual(result["RC Cola"]["sales"], 4)
            self.assertEqual(result["Coke"]["sales"], 2)
            self.assertEqual(result["Ham & Cheese Sandwich"]["sales"], 5)
            self.assertEqual(result["Chicken Salad Sandwich"]["sales"], 1)
            self.assertEqual(result["Iced Coffee - Mocha"]["sales"], 5)
            self.assertEqual(result["Milky Way"]["sales"], 1)
            self.assertEqual(result["M&M - Peanut"]["sales"], 2)
            self.assertEqual(result["Sprite"]["sales"], 3)
            self.assertEqual(result["Sunflower Seeds - Dill Pickle"]["sales"], 2)
        finally:
            os.unlink(path)

    def test_bloom_pop_flavor_modifier_uses_bloom_pop_dash_name(self):
        """Bloom Pop Flavor modifier set constructs 'Bloom Pop - {modifier}' names."""
        path = _write_tmp_csv([
            {"Modifier Set": "Bloom Pop", "Modifier": "Strawberry Cream",
             "Qty Sold": "2", "Gross Sales": "$0.00"},
            {"Modifier Set": "Bloom Pop", "Modifier": "Raspberry Lemonade",
             "Qty Sold": "3", "Gross Sales": "$0.00"},
            {"Modifier Set": "Bloom Pop", "Modifier": "Watermelon Lime",
             "Qty Sold": "1", "Gross Sales": "$0.00"},
        ])
        try:
            result = take_modifiers(path)
            self.assertEqual(result["Bloom Pop - Strawberry Cream"]["sales"], 2)
            self.assertEqual(result["Bloom Pop - Raspberry Lemonade"]["sales"], 3)
            self.assertEqual(result["Bloom Pop - Watermelon Lime"]["sales"], 1)
            self.assertNotIn("Strawberry Cream", result)
            self.assertNotIn("Raspberry Lemonade", result)
            self.assertNotIn("Watermelon Lime", result)
        finally:
            os.unlink(path)

    def test_iced_coffee_modifier_uses_current_item_prefix(self):
        path = _write_tmp_csv([
            {"Modifier Set": "Iced Coffee", "Modifier": "Vanilla", "Qty Sold": "4", "Gross Sales": "$0.00"},
        ])
        try:
            result = take_modifiers(path)
            self.assertEqual(result["Iced Coffee - Vanilla"]["sales"], 4)
            self.assertNotIn("La Colombe - Vanilla", result)
        finally:
            os.unlink(path)

    def test_poppi_flavor_modifier_uses_poppi_dash_name(self):
        """Poppi Flavor modifier set constructs 'Poppi - {modifier}' names."""
        path = _write_tmp_csv([
            {"Modifier Set": "Poppi", "Modifier": "Watermelon",
             "Qty Sold": "4", "Gross Sales": "$0.00"},
            {"Modifier Set": "Poppi", "Modifier": "Wild Berry",
             "Qty Sold": "2", "Gross Sales": "$0.00"},
            {"Modifier Set": "Poppi", "Modifier": "Raspberry Rose",
             "Qty Sold": "5", "Gross Sales": "$0.00"},
        ])
        try:
            result = take_modifiers(path)
            self.assertEqual(result["Poppi - Watermelon"]["sales"], 4)
            self.assertEqual(result["Poppi - Wild Berry"]["sales"], 2)
            self.assertEqual(result["Poppi - Raspberry Rose"]["sales"], 5)
            self.assertNotIn("Watermelon", result)
            self.assertNotIn("Wild Berry", result)
            self.assertNotIn("Raspberry Rose", result)
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


class CallSheetsAlignmentTests(unittest.TestCase):
    """Verify Call_sheets item lists and stand restrictions match modifier outputs."""

    def test_slushie_and_snack_rows_use_current_names(self):
        self.assertEqual(
            SLUSHIE_FLAVORS,
            [
                "Slushie - Mango",
                "Slushie - Blue Razz",
                "Slushie - Tiger's Blood",
                "Slushie - Green Apple",
                "Slushie - Peach",
            ],
        )
        for snack in (
            "Rainbow Sprinkles",
            "Whipped Cream",
            "Sunflower Seeds - Original",
            "Sunflower Seeds - Dill Pickle",
            "Sunflower Seeds - Ranch",
            "Crunchy Ra-Ra - Sprinkles",
        ):
            self.assertIn(snack, SNACKS)
        self.assertNotIn("Sprinkles", SNACKS)

    def test_bottled_drinks_use_current_item_names(self):
        for item in (
            "Iced Coffee - Vanilla",
            "Iced Coffee - Mocha",
            "Iced Coffee - Caramel",
            "Bloom Pop - Watermelon Lime",
            "Poppi - Raspberry Rose",
            "Diet Mt. Dew",
            "7UP",
        ):
            self.assertIn(item, BOTTLED_DRINKS)
        self.assertNotIn("La Colombe - Vanilla", BOTTLED_DRINKS)
        self.assertNotIn("Gatorade - Orange", BOTTLED_DRINKS)

    def test_location_specific_item_stands_match_requested_restrictions(self):
        self.assertIn("Mt. Dew", FOUNTAIN_DRINKS)
        self.assertNotIn("Ham & Cheese Sandwich", FOOD)
        self.assertNotIn("Ham & Cheese Sandwich", LOCATION_SPECIFIC_ITEM_STANDS)
        self.assertEqual(
            LOCATION_SPECIFIC_ITEM_STANDS["Bloom Pop - Watermelon Lime"],
            {"BEXLEY", "DEVON", "HILLIARD2 (EAST)", "HILLIARD1 (WEST)", "NWSC", "REED ROAD", "TREMONT"},
        )
        self.assertEqual(LOCATION_SPECIFIC_ITEM_STANDS["Poppi - Wild Berry"], {"PTAC"})
        self.assertEqual(LOCATION_SPECIFIC_ITEM_STANDS["M&M - Peanut"], {"HILLIARD2 (EAST)", "Bevelhymer Yellow", "Bevelhymer Green"})
        # New candy items
        self.assertIn("Swedish Fish", CANDY)
        self.assertNotIn("Swedish Fish", LOCATION_SPECIFIC_ITEM_STANDS)
        self.assertIn("Big League Chew", CANDY)
        self.assertEqual(LOCATION_SPECIFIC_ITEM_STANDS["Big League Chew"], {"Bevelhymer Green", "Bevelhymer Yellow"})
        self.assertIn("Skittles", CANDY)
        self.assertEqual(LOCATION_SPECIFIC_ITEM_STANDS["Skittles"], {"Bevelhymer Green", "Bevelhymer Yellow"})
        # Peach Tea restricted to Bevelhymer
        self.assertIn("Peach Tea", BOTTLED_DRINKS)
        self.assertEqual(LOCATION_SPECIFIC_ITEM_STANDS["Peach Tea"], {"Bevelhymer Green", "Bevelhymer Yellow"})
        self.assertEqual(
            LOCATION_SPECIFIC_ITEM_STANDS[("FOUNTAIN_DRINKS", "Dr. Pepper")],
            {"BEXLEY", "DEVON", "HILLIARD2 (EAST)", "HILLIARD1 (WEST)", "NWSC", "PTAC", "REED ROAD", "TREMONT"},
        )
        self.assertEqual(
            LOCATION_SPECIFIC_ITEM_STANDS[("BOTTLED_DRINKS", "Dr. Pepper")],
            {"Bevelhymer Green", "Bevelhymer Yellow"},
        )
        self.assertEqual(
            LOCATION_SPECIFIC_ITEM_STANDS[("FOUNTAIN_DRINKS", "Mt. Dew")],
            {"PTAC"},
        )
        self.assertEqual(
            LOCATION_SPECIFIC_ITEM_STANDS[("BOTTLED_DRINKS", "Mt. Dew")],
            {"Bevelhymer Green", "Bevelhymer Yellow"},
        )


class ComboBreakdownTests(unittest.TestCase):
    """Verify COMBO_BREAKDOWN constants and combo expansion logic in take_items()."""

    NON_BEVELHYMER = {
        "BEXLEY", "DEVON", "HILLIARD2 (EAST)", "HILLIARD1 (WEST)",
        "NWSC", "PTAC", "REED ROAD", "TREMONT",
    }

    def test_combo_breakdown_keys_present(self):
        self.assertIn("Cannonball!!!", COMBO_BREAKDOWN)
        self.assertIn("Root Beer Float", COMBO_BREAKDOWN)
        self.assertIn("Rainbow Sherbet Float", COMBO_BREAKDOWN)

    def test_root_beer_float_components(self):
        self.assertEqual(COMBO_BREAKDOWN["Root Beer Float"], ["Root Beer", "Vanilla"])

    def test_rainbow_sherbet_float_default_components(self):
        self.assertEqual(COMBO_BREAKDOWN["Rainbow Sherbet Float"], ["Rainbow Sherbet", "7up"])

    def test_root_beer_float_deducts_components(self):
        path = _write_tmp_csv([
            {"Item Name": "Root Beer Float", "Item Variation": "Regular",
             "Units Sold": "3", "Units Refunded": "1"},
        ])
        try:
            result = take_items(path)
            self.assertNotIn("Root Beer Float", result)
            self.assertIn("Root Beer", result)
            self.assertEqual(result["Root Beer"]["sales"], 2)
            self.assertIn("Vanilla", result)
            self.assertEqual(result["Vanilla"]["sales"], 2)
        finally:
            os.unlink(path)

    def test_rainbow_sherbet_float_deducts_7up_by_default(self):
        path = _write_tmp_csv([
            {"Item Name": "Rainbow Sherbet Float", "Item Variation": "Regular",
             "Units Sold": "2", "Units Refunded": "0"},
        ])
        try:
            result = take_items(path)
            self.assertNotIn("Rainbow Sherbet Float", result)
            self.assertIn("Rainbow Sherbet", result)
            self.assertEqual(result["Rainbow Sherbet"]["sales"], 2)
            self.assertIn("7up", result)
            self.assertEqual(result["7up"]["sales"], 2)
            self.assertNotIn("Starry", result)
        finally:
            os.unlink(path)

    def test_rainbow_sherbet_float_uses_starry_at_ptac(self):
        path = _write_tmp_csv([
            {"Item Name": "Rainbow Sherbet Float", "Item Variation": "Regular",
             "Units Sold": "2", "Units Refunded": "0"},
        ])
        try:
            result = take_items(path, stand_name="PTAC")
            self.assertNotIn("Rainbow Sherbet Float", result)
            self.assertIn("Rainbow Sherbet", result)
            self.assertIn("Starry", result)
            self.assertEqual(result["Starry"]["sales"], 2)
            self.assertNotIn("7up", result)
        finally:
            os.unlink(path)

    def test_rainbow_sherbet_float_uses_7up_at_nwsc(self):
        path = _write_tmp_csv([
            {"Item Name": "Rainbow Sherbet Float", "Item Variation": "Regular",
             "Units Sold": "1", "Units Refunded": "0"},
        ])
        try:
            result = take_items(path, stand_name="NWSC")
            self.assertNotIn("Rainbow Sherbet Float", result)
            self.assertIn("7up", result)
            self.assertEqual(result["7up"]["sales"], 1)
            self.assertNotIn("Starry", result)
        finally:
            os.unlink(path)

    def test_cannonball_deducts_vanilla(self):
        path = _write_tmp_csv([
            {"Item Name": "Cannonball!!!", "Item Variation": "Regular",
             "Units Sold": "2", "Units Refunded": "0"},
        ])
        try:
            result = take_items(path)
            self.assertNotIn("Cannonball!!!", result)
            self.assertIn("Vanilla", result)
            self.assertEqual(result["Vanilla"]["sales"], 2)
        finally:
            os.unlink(path)


class NewItemsInventoryTests(unittest.TestCase):
    """Verify new items are present in the correct Call_sheets inventory lists."""

    NON_BEVELHYMER = {
        "BEXLEY", "DEVON", "HILLIARD2 (EAST)", "HILLIARD1 (WEST)",
        "NWSC", "PTAC", "REED ROAD", "TREMONT",
    }
    BEVELHYMER = {"Bevelhymer Green", "Bevelhymer Yellow"}

    def test_novelties_correct_square_names(self):
        for item in (
            "Bomb Pop",
            "Cookie Sandwich",
            "Nerd Bomb Pop",
            "Power Puff Girl",
            "Reese's Ice Cream",
            "Snickers Ice Cream Bar",
            "Sonic The Hedgehog",
            "Spiderman Ice Cream",
            "Spongebob Ice Cream",
            "Strawberry Shortcake Bar",
            "Sundae Cone",
            "Twix Ice Cream Bar",
        ):
            self.assertIn(item, NOVELTIES, f"{item!r} missing from NOVELTIES")

    def test_food_has_new_items(self):
        self.assertIn("Chicken Caesar Salad", FOOD)
        self.assertNotIn("Hummus and Pita Chips", FOOD)

    def test_snacks_has_new_items(self):
        for item in (
            "Cuties (2/$1.00)",
            "Peanuts Shelled",
            "Kars",
            "Clif Bar",
            "Fig Bars",
            "Doughnut Packs",
        ):
            self.assertIn(item, SNACKS, f"{item!r} missing from SNACKS")

    def test_oranges_removed_from_snacks(self):
        self.assertNotIn("Oranges", SNACKS)

    def test_cannonball_restricted_to_non_bevelhymer(self):
        self.assertIn("Cannonball!!!", LOCATION_SPECIFIC_ITEM_STANDS)
        self.assertEqual(LOCATION_SPECIFIC_ITEM_STANDS["Cannonball!!!"], self.NON_BEVELHYMER)

    def test_root_beer_float_restricted_to_non_bevelhymer(self):
        self.assertIn("Root Beer Float", LOCATION_SPECIFIC_ITEM_STANDS)
        self.assertEqual(LOCATION_SPECIFIC_ITEM_STANDS["Root Beer Float"], self.NON_BEVELHYMER)

    def test_rainbow_sherbet_float_restricted_to_four_stands(self):
        self.assertIn("Rainbow Sherbet Float", LOCATION_SPECIFIC_ITEM_STANDS)
        self.assertEqual(
            LOCATION_SPECIFIC_ITEM_STANDS["Rainbow Sherbet Float"],
            RAINBOW_SHERBET_FLOAT_STANDS,
        )

    def test_bevelhymer_snacks_restricted_correctly(self):
        for item in ("Peanuts Shelled", "Kars", "Clif Bar", "Fig Bars", "Doughnut Packs"):
            self.assertIn(item, LOCATION_SPECIFIC_ITEM_STANDS, f"{item!r} missing from LOCATION_SPECIFIC_ITEM_STANDS")
            self.assertEqual(
                LOCATION_SPECIFIC_ITEM_STANDS[item],
                self.BEVELHYMER,
                f"{item!r} should be restricted to Bevelhymer stands only",
            )


class MultiByItemTests(unittest.TestCase):
    """Verify that "2 for $1" multi-buy items deduct 2 physical pieces per unit sold."""

    def test_airheads_doubles_units_sold(self):
        path = _write_tmp_csv([
            {"Item Name": "Airheads 2 for $1", "Item Variation": "Regular",
             "Units Sold": "5", "Units Refunded": "0"},
        ])
        try:
            result = take_items(path)
            self.assertIn("Airheads 2 for $1", result)
            self.assertEqual(result["Airheads 2 for $1"]["sales"], 10)
        finally:
            os.unlink(path)

    def test_cuties_doubles_units_sold(self):
        path = _write_tmp_csv([
            {"Item Name": "Cuties (2/$1.00)", "Item Variation": "Regular",
             "Units Sold": "3", "Units Refunded": "0"},
        ])
        try:
            result = take_items(path)
            self.assertIn("Cuties (2/$1.00)", result)
            self.assertEqual(result["Cuties (2/$1.00)"]["sales"], 6)
        finally:
            os.unlink(path)

    def test_airheads_refund_scales_with_multiplier(self):
        path = _write_tmp_csv([
            {"Item Name": "Airheads 2 for $1", "Item Variation": "Regular",
             "Units Sold": "5", "Units Refunded": "1"},
        ])
        try:
            result = take_items(path)
            # net = (5 - 1) * 2 = 8
            self.assertIn("Airheads 2 for $1", result)
            self.assertEqual(result["Airheads 2 for $1"]["sales"], 8)
        finally:
            os.unlink(path)

    def test_refund_sign_is_agnostic_for_regular_items(self):
        for refunded in ("-2", "2"):
            with self.subTest(refunded=refunded):
                path = _write_tmp_csv([
                    {"Item Name": "Hot Dog", "Item Variation": "Regular",
                     "Units Sold": "10", "Units Refunded": refunded},
                ])
                try:
                    result = take_items(path)
                    self.assertEqual(result["Hot Dog"]["sales"], 8)
                finally:
                    os.unlink(path)

    def test_cuties_refund_scales_with_multiplier_for_negative_refunds(self):
        path = _write_tmp_csv([
            {"Item Name": "Cuties (2/$1.00)", "Item Variation": "Regular",
             "Units Sold": "5", "Units Refunded": "-1"},
        ])
        try:
            result = take_items(path)
            self.assertEqual(result["Cuties (2/$1.00)"]["sales"], 8)
        finally:
            os.unlink(path)

    def test_cotton_candy_candy_and_ice_cream_modifier_stay_separate(self):
        item_fieldnames = [
            "Item Name", "Item Variation", "SKU", "Category", "Items Sold",
            "Gross Sales", "Items Refunded", "Refunds", "Discounts & Comps",
            "Net Sales", "Tax", "Unit", "Units Sold", "Units Refunded",
        ]
        items_path = _write_tmp_csv([
            {
                "Item Name": "Cotton Candy",
                "Item Variation": "Regular",
                "SKU": ".965",
                "Category": "Candy",
                "Items Sold": "202",
                "Gross Sales": "$808.00",
                "Items Refunded": "-1",
                "Refunds": "-$4.00",
                "Discounts & Comps": "-$6.00",
                "Net Sales": "$798.00",
                "Tax": "$0.00",
                "Unit": "ea",
                "Units Sold": "202",
                "Units Refunded": "-1",
            },
        ], fieldnames=item_fieldnames)
        modifiers_path = _write_tmp_csv([
            {
                "Modifier Set": "Ice Cream Flavor",
                "Modifier": "Cotton Candy",
                "Qty Sold": "572",
                "Gross Sales": "$0.00",
            },
        ], fieldnames=["Modifier Set", "Modifier", "Qty Sold", "Gross Sales"])
        try:
            rows = take_items(items_path)
            modifier_rows = take_modifiers(modifiers_path)
            merge_modifier_rows(rows, modifier_rows)
            self.assertEqual(rows["Cotton Candy"]["sales"], 201)
            self.assertEqual(rows["Cotton Candy Ice Cream"]["sales"], 572)
        finally:
            os.unlink(items_path)
            os.unlink(modifiers_path)

    def test_control_item_not_doubled(self):
        path = _write_tmp_csv([
            {"Item Name": "Sour Patch Kids", "Item Variation": "Regular",
             "Units Sold": "7", "Units Refunded": "0"},
        ])
        try:
            result = take_items(path)
            self.assertIn("Sour Patch Kids", result)
            self.assertEqual(result["Sour Patch Kids"]["sales"], 7)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
