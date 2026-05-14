import sys
import types
import unittest
from unittest.mock import patch


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

import Call_sheets  # noqa: E402


class InventoryRefactorTests(unittest.TestCase):
    def test_tofts_base_flavors_updated(self):
        self.assertIn("Birthday Cake", Call_sheets._TOFTS_BASE_FLAVORS)
        self.assertIn("PB S'Mores", Call_sheets._TOFTS_BASE_FLAVORS)
        self.assertIn("Blueberry Waffle Cone", Call_sheets._TOFTS_BASE_FLAVORS)
        self.assertIn("Rainbow Sherbet", Call_sheets._TOFTS_BASE_FLAVORS)

        self.assertNotIn("Peanut Butter Cup", Call_sheets._TOFTS_BASE_FLAVORS)
        self.assertNotIn("Strawberry Cheesecake", Call_sheets._TOFTS_BASE_FLAVORS)
        self.assertNotIn("Super Duper Scoop", Call_sheets._TOFTS_BASE_FLAVORS)

    def test_ingredient_map_removes_trays_and_straws(self):
        self.assertEqual(
            Call_sheets.INGREDIENT_MAP["Nachos & Cheese"],
            [("Nacho Chips", 1), ("Nacho Cheese", 1)],
        )
        self.assertEqual(
            Call_sheets.INGREDIENT_MAP["Slushie"],
            [("Slushie Mix", 1), ("Frazil Cups", 1)],
        )

    def test_ingredient_map_tracks_chili_and_pulled_pork_scoops(self):
        self.assertEqual(
            Call_sheets.INGREDIENT_MAP["Walking Taco"],
            [("Assorted Chips", 1), ("Chili Sauce (0.5oz scoop)", 2)],
        )
        self.assertEqual(
            Call_sheets.INGREDIENT_MAP["Pulled Pork Sandwich"],
            [("Hamburger Buns", 1), ("Pulled Pork (4oz scoop)", 1)],
        )
        self.assertEqual(
            Call_sheets.INGREDIENT_MAP["BBQ Pork Sandwich"],
            [("Hamburger Buns", 1), ("Pulled Pork (4oz scoop)", 1)],
        )
        self.assertEqual(
            Call_sheets.INGREDIENT_MAP["Pulled Pork Nachos"],
            [("Nacho Chips", 1), ("Nacho Cheese", 1), ("Pulled Pork (4oz scoop)", 1)],
        )
        self.assertIn("Pulled Pork (4oz scoop)", Call_sheets.INGREDIENTS)
        self.assertEqual(Call_sheets.PORK_SCOOPS_PER_BAG, 6)

    def test_consolidate_variants_initializes_full_base_row_shape(self):
        rows = {"Vanilla Double Scoop": {"sales": 2, "deliveries": 3, "spoilage": 1}}
        Call_sheets.consolidate_variants_to_base(rows, {"Vanilla Double Scoop": "Vanilla"})

        self.assertIn("Vanilla", rows)
        self.assertEqual(rows["Vanilla"]["starting"], 0)
        self.assertEqual(rows["Vanilla"]["deliveries"], 3)
        self.assertEqual(rows["Vanilla"]["sales"], 2)
        self.assertEqual(rows["Vanilla"]["spoilage"], 1)
        self.assertEqual(rows["Vanilla"]["scoops_used"], 0)
        self.assertEqual(rows["Vanilla"]["tubs_used"], 0)
        self.assertEqual(rows["Vanilla"]["expected"], 0)
        self.assertEqual(rows["Vanilla"]["actual"], "")

    def test_consolidate_variants_preserves_self_mapped_entries(self):
        rows = {"Chocolate": {"sales": 2, "deliveries": 3, "spoilage": 1}}
        Call_sheets.consolidate_variants_to_base(rows, {"Chocolate": "Chocolate"})

        self.assertEqual(
            rows,
            {"Chocolate": {"sales": 2, "deliveries": 3, "spoilage": 1}},
        )

    def test_get_default_category_order_for_stand_filters_location_items(self):
        bexley = dict(Call_sheets.get_default_category_order_for_stand("Bexley"))
        self.assertNotIn("Mint Chip", bexley["ICE_CREAM_TOFTS"])
        self.assertNotIn("Coca Cola", bexley["FOUNTAIN_DRINKS"])
        self.assertNotIn("Diet Pepsi", bexley["FOUNTAIN_DRINKS"])

        ptac = dict(Call_sheets.get_default_category_order_for_stand("PTAC"))
        self.assertIn("Mint Chip", ptac["ICE_CREAM_TOFTS"])
        self.assertIn("Diet Pepsi", ptac["FOUNTAIN_DRINKS"])
        self.assertNotIn("Coca Cola", ptac["FOUNTAIN_DRINKS"])

        treemont = dict(Call_sheets.get_default_category_order_for_stand("Treemont"))
        self.assertIn("Mint Chip", treemont["ICE_CREAM_TOFTS"])
        self.assertIn("Coca Cola", treemont["FOUNTAIN_DRINKS"])
        self.assertNotIn("Diet Pepsi", treemont["FOUNTAIN_DRINKS"])

    def test_read_deliveries_converts_fountain_packages_to_stand_oz(self):
        header = [["Date", "Item Name", "Packages", "Units per package"]]
        rows = [["05-10-2026", "Diet RC", "2", "1"]]

        with patch.object(Call_sheets, "get_values", side_effect=[header, rows]):
            ptac = Call_sheets.read_deliveries(object(), "sid", "PTAC")
        self.assertEqual(ptac["Diet RC"], 1280)

        with patch.object(Call_sheets, "get_values", side_effect=[header, rows]):
            reed = Call_sheets.read_deliveries(object(), "sid", "Reed Road")
        self.assertEqual(reed["Diet RC"], 640)


if __name__ == "__main__":
    unittest.main()
