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
            [("Assorted Chips", 1), ("Chili Sauce (cans)", 2)],
        )
        self.assertEqual(
            Call_sheets.INGREDIENT_MAP["Pulled Pork Sandwich"],
            [("Hamburger Buns", 1), ("Pulled Pork (bags)", 1)],
        )
        self.assertEqual(
            Call_sheets.INGREDIENT_MAP["BBQ Pork Sandwich"],
            [("Hamburger Buns", 1), ("Pulled Pork (bags)", 1)],
        )
        self.assertEqual(
            Call_sheets.INGREDIENT_MAP["Pulled Pork Nachos"],
            [("Nacho Chips", 1), ("Nacho Cheese", 1), ("Pulled Pork (bags)", 1)],
        )
        self.assertIn("Pulled Pork (bags)", Call_sheets.INGREDIENTS)
        self.assertIn("Chili Sauce (cans)", Call_sheets.INGREDIENTS)
        self.assertEqual(Call_sheets.CHILI_SCOOPS_PER_CAN, 30)
        self.assertEqual(Call_sheets.PORK_SCOOPS_PER_BAG, 6)
        self.assertEqual(Call_sheets.POPCORN_PACKETS_PER_BOX, 36)

    def test_hot_dog_frank_tracking_configuration(self):
        self.assertEqual(Call_sheets.HOT_DOG_FRANKS_PER_BAG, 50)
        self.assertEqual(
            Call_sheets.INGREDIENT_MAP["Hot Dog"],
            [("Hot Dog Buns", 1), ("Hot Dogs", 1)],
        )
        self.assertEqual(
            Call_sheets.INGREDIENT_MAP["Chili Cheese Dog"],
            [("Hot Dog Buns", 1), ("Hot Dogs", 1), ("Chili Sauce (cans)", 1)],
        )
        self.assertIn("Hot Dogs", Call_sheets.FOOD)
        self.assertIn("Hot Dogs", Call_sheets.INGREDIENTS)

    def test_calculate_ingredients_per_stand_converts_to_cans_and_bags(self):
        rows = {
            "Walking Taco": {"sales": 15},
            "Pulled Pork Sandwich": {"sales": 6},
        }

        result = Call_sheets.calculate_ingredients_per_stand(rows)

        self.assertEqual(result["Chili Sauce (cans)"]["sales"], 1.0)
        self.assertEqual(result["Pulled Pork (bags)"]["sales"], 1.0)

    def test_popcorn_location_restrictions(self):
        self.assertIn("Popcorn", Call_sheets.LOCATION_SPECIFIC_ITEM_STANDS)
        self.assertEqual(
            Call_sheets.LOCATION_SPECIFIC_ITEM_STANDS["Popcorn"],
            {"TREMONT", "REED ROAD", "NWSC"},
        )

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
        bexley = dict(Call_sheets.get_default_category_order_for_stand("BEXLEY"))
        self.assertNotIn("Mint Chip", bexley["ICE_CREAM_TOFTS"])
        self.assertNotIn("Coca Cola", bexley["FOUNTAIN_DRINKS"])
        self.assertNotIn("Diet Pepsi", bexley["FOUNTAIN_DRINKS"])
        self.assertIn("7up", bexley["FOUNTAIN_DRINKS"])
        self.assertIn("Diet RC", bexley["FOUNTAIN_DRINKS"])
        self.assertIn("RC Cola", bexley["FOUNTAIN_DRINKS"])

        ptac = dict(Call_sheets.get_default_category_order_for_stand("PTAC"))
        self.assertIn("Mint Chip", ptac["ICE_CREAM_TOFTS"])
        self.assertEqual(
            set(ptac["FOUNTAIN_DRINKS"]),
            {"Dr. Pepper", "Root Beer", "Diet Pepsi", "Pepsi", "Starry"},
        )
        self.assertNotIn("Coca Cola", ptac["FOUNTAIN_DRINKS"])
        self.assertNotIn("7up", ptac["FOUNTAIN_DRINKS"])
        self.assertNotIn("Big Red", ptac["FOUNTAIN_DRINKS"])
        self.assertNotIn("Diet RC", ptac["FOUNTAIN_DRINKS"])
        self.assertNotIn("RC Cola", ptac["FOUNTAIN_DRINKS"])

        treemont = dict(Call_sheets.get_default_category_order_for_stand("TREMONT"))
        self.assertIn("Mint Chip", treemont["ICE_CREAM_TOFTS"])
        self.assertIn("Coca Cola", treemont["FOUNTAIN_DRINKS"])
        self.assertTrue(
            {"7up", "Big Red", "Diet RC", "Dr. Pepper", "Root Beer", "RC Cola", "Coca Cola"}.issubset(
                set(treemont["FOUNTAIN_DRINKS"])
            )
        )
        self.assertNotIn("Diet Pepsi", treemont["FOUNTAIN_DRINKS"])
        self.assertNotIn("Pepsi", treemont["FOUNTAIN_DRINKS"])
        self.assertNotIn("Starry", treemont["FOUNTAIN_DRINKS"])

    def test_fountain_drinks_list_excludes_mt_dew_and_lemonade(self):
        self.assertNotIn("Mt. Dew", Call_sheets.FOUNTAIN_DRINKS)
        self.assertNotIn("Lemonade", Call_sheets.FOUNTAIN_DRINKS)

    def test_read_deliveries_converts_fountain_packages_to_stand_oz(self):
        header = [["Date", "Item Name", "Packages", "Units per package"]]
        rows = [["05-10-2026", "Diet RC", "2", "1"]]
        root_beer_rows = [["05-10-2026", "Root Beer", "1", "1"]]
        ignored_units_per_package = "999"
        popcorn_rows = [["05-10-2026", "Popcorn", "2", ignored_units_per_package]]
        hot_dog_rows = [["05-10-2026", "Hot Dogs", "2", ignored_units_per_package]]

        with patch.object(Call_sheets, "get_values", side_effect=[header, rows]):
            ptac = Call_sheets.read_deliveries(object(), "sid", "PTAC")
        self.assertEqual(ptac["Diet RC"], 1280)

        with patch.object(Call_sheets, "get_values", side_effect=[header, rows]):
            reed = Call_sheets.read_deliveries(object(), "sid", "REED ROAD")
        self.assertEqual(reed["Diet RC"], 640)

        with patch.object(Call_sheets, "get_values", side_effect=[header, root_beer_rows]):
            ptac_root_beer = Call_sheets.read_deliveries(object(), "sid", "PTAC")
        self.assertEqual(ptac_root_beer["Root Beer"], 640)

        with patch.object(Call_sheets, "get_values", side_effect=[header, root_beer_rows]):
            reed_root_beer = Call_sheets.read_deliveries(object(), "sid", "REED ROAD")
        self.assertEqual(reed_root_beer["Root Beer"], 320)

        with patch.object(Call_sheets, "get_values", side_effect=[header, popcorn_rows]):
            reed_popcorn = Call_sheets.read_deliveries(object(), "sid", "REED ROAD")
        self.assertEqual(reed_popcorn["Popcorn"], 72)

        with patch.object(Call_sheets, "get_values", side_effect=[header, hot_dog_rows]):
            reed_hot_dogs = Call_sheets.read_deliveries(object(), "sid", "REED ROAD")
        self.assertEqual(reed_hot_dogs["Hot Dogs"], 100)


if __name__ == "__main__":
    unittest.main()
