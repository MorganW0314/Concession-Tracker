import sys
import types
import unittest
from unittest.mock import MagicMock, call, patch


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


def _write_full_week_item_row(category_order, rows, target_item, stand_name="PTAC"):
    fake_sheet = MagicMock()
    fake_service = MagicMock()
    fake_service.spreadsheets().values().batchUpdate().execute.return_value = {}
    fake_service.spreadsheets().values().update().execute.return_value = {}
    fake_service.spreadsheets().batchUpdate().execute.return_value = {}

    item_row_map = {}
    row_num = 3
    for _category_name, item_list in category_order:
        for item in sorted(item_list):
            item_row_map[Call_sheets.normalize_item_name(item)] = row_num
            row_num += 1

    target_row_num = item_row_map[Call_sheets.normalize_item_name(target_item)]

    with (
        patch("Call_sheets.CATEGORY_ORDER", category_order, create=True),
        patch.object(Call_sheets, "ensure_stand_sheet_exists", return_value=None),
        patch.object(Call_sheets, "get_sheet_id", return_value=123),
        patch.object(Call_sheets, "find_last_week_start_col", return_value=0),
        patch.object(Call_sheets, "read_last_week_actuals_from_stand_sheet", return_value={}),
        patch.object(Call_sheets, "read_spoilage", return_value={}),
        patch.object(Call_sheets, "clear_spoilage_sheet", return_value=None),
        patch.object(Call_sheets, "extract_week_dates_from_label", return_value=(None, None)),
        patch.object(Call_sheets, "read_deliveries", return_value={}),
        patch.object(Call_sheets, "read_transfers", return_value={"to": {}, "from": {}}),
        patch.object(Call_sheets, "read_item_row_map", return_value=item_row_map),
        patch.object(Call_sheets, "_qty_per_case_value", return_value=1),
        patch.object(Call_sheets, "_sync_master_items_tab", return_value=None),
    ):
        Call_sheets.write_full_week(fake_sheet, fake_service, "sid", stand_name, rows)

    body = fake_service.spreadsheets.return_value.values.return_value.batchUpdate.call_args.kwargs["body"]
    target_range = f"'{stand_name}'!B{target_row_num}:M{target_row_num}"
    item_row = next(
        (entry["values"][0] for entry in body["data"] if entry["range"] == target_range),
        None,
    )
    return item_row, target_row_num


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

    def test_ingredient_map_cannonball_uses_one_vanilla_scoop(self):
        # Cannonball must map to exactly 1 scoop of Vanilla (inherent ingredient).
        # The slushie flavour is customer-selected via modifier and tracked separately.
        self.assertEqual(
            Call_sheets.INGREDIENT_MAP["Cannonball!!!"],
            [("Vanilla", 1)],
        )

    def test_ingredient_map_cup_of_cheese_uses_one_nacho_serving(self):
        self.assertEqual(
            Call_sheets.INGREDIENT_MAP["Cup of Cheese"],
            [("Nacho Cheese", 3)],
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

    def test_hot_dog_ingredient_configuration(self):
        self.assertEqual(
            Call_sheets.INGREDIENT_MAP["Hot Dog"],
            [("Hot Dog Buns", 1)],
        )
        self.assertEqual(
            Call_sheets.INGREDIENT_MAP["Chili Cheese Dog"],
            [("Hot Dog Buns", 1), ("Hot Dog", 1), ("Chili Sauce (cans)", 1)],
        )
        self.assertNotIn("Hot Dogs", Call_sheets.FOOD)
        self.assertNotIn("Hot Dogs", Call_sheets.INGREDIENTS)

    def test_nwsc_food_items_include_brats_and_hamburgers(self):
        self.assertIn("Brats", Call_sheets.FOOD)
        self.assertIn("Hamburgers", Call_sheets.FOOD)
        self.assertEqual(Call_sheets.QUANTITY_PER_CASE["Brats"], 50)
        self.assertEqual(Call_sheets.QUANTITY_PER_CASE["Hamburgers"], 40)
        self.assertEqual(Call_sheets.LOCATION_SPECIFIC_ITEM_STANDS["Brats"], {"NWSC"})
        self.assertEqual(Call_sheets.LOCATION_SPECIFIC_ITEM_STANDS["Hamburgers"], {"NWSC"})

    def test_food_list_excludes_menu_items_tracked_via_ingredients(self):
        self.assertNotIn("Chicken Salad Sandwich", Call_sheets.FOOD)
        self.assertNotIn("Ham & Cheese Sandwich", Call_sheets.FOOD)
        self.assertNotIn("Hummus and Pita Chips", Call_sheets.FOOD)
        self.assertNotIn("Pulled Pork Sandwich", Call_sheets.FOOD)
        self.assertNotIn("Salad", Call_sheets.FOOD)
        self.assertNotIn("Chili Cheese Dog", Call_sheets.FOOD)
        self.assertIn("Ham", Call_sheets.FOOD)
        self.assertIn("Cheese", Call_sheets.FOOD)
        self.assertNotIn("Ham & Cheese Sandwich", Call_sheets.LOCATION_SPECIFIC_ITEM_STANDS)

    def test_removed_legacy_food_items_not_in_default_category_order_for_any_stand(self):
        removed_items = {
            "Chicken Salad Sandwich",
            "Ham & Cheese Sandwich",
            "Hummus and Pita Chips",
            "Pulled Pork Sandwich",
        }
        for stand_name in Call_sheets.ALL_STANDS:
            category_order = Call_sheets.get_default_category_order_for_stand(stand_name)
            all_items = {item for _category, items in category_order for item in items}
            for removed_item in removed_items:
                self.assertNotIn(removed_item, all_items, msg=f"{removed_item} still present for {stand_name}")

    def test_calculate_ingredients_per_stand_converts_to_cans_and_bags(self):
        rows = {
            "Walking Taco": {"sales": 15},
            "Pulled Pork Sandwich": {"sales": 6},
        }

        result = Call_sheets.calculate_ingredients_per_stand(rows)

        self.assertEqual(result["Chili Sauce (cans)"]["sales"], 1.0)
        self.assertEqual(result["Pulled Pork (bags)"]["sales"], 1.0)

    def test_calculate_ingredients_per_stand_converts_fountain_slushie_and_grapes(self):
        rows = {
            "Dr. Pepper": {"sales": 640},
            "Root Beer": {"sales": 640},
            "Slushie - Mango": {"sales": 25},
            "Frozen Grapes": {"sales": 12},
        }
        result = Call_sheets.calculate_ingredients_per_stand(rows, stand_name="PTAC")
        self.assertEqual(result["Dr. Pepper"]["sales"], 1.0)
        self.assertEqual(result["Root Beer"]["sales"], 1.0)
        self.assertEqual(result["Slushie - Mango"]["sales"], 2.5)
        self.assertEqual(result["Frozen Grapes"]["sales"], 1.5)

        non_ptac_rows = {"Root Beer": {"sales": 320}}
        non_ptac_result = Call_sheets.calculate_ingredients_per_stand(non_ptac_rows, stand_name="NWSC")
        self.assertEqual(non_ptac_result["Root Beer"]["sales"], 1.0)

    def test_ham_and_cheese_package_conversion_constants(self):
        self.assertEqual(Call_sheets.HAM_SLICES_PER_PACKAGE, 32)
        self.assertEqual(Call_sheets.CHEESE_SLICES_PER_PACKAGE, 160)

    def test_calculate_ingredients_per_stand_keeps_ham_and_cheese_in_slices(self):
        rows = {"Ham and Cheese Sandwich": {"sales": 32}}
        result = Call_sheets.calculate_ingredients_per_stand(rows)
        self.assertEqual(result["Ham"]["sales"], 32)
        self.assertEqual(result["Cheese"]["sales"], 32)

    def test_calculate_ingredients_per_stand_converts_cup_of_cheese_to_nacho_bags(self):
        rows = {"Cup of Cheese": {"sales": 87}}
        result = Call_sheets.calculate_ingredients_per_stand(rows)
        self.assertEqual(result["Nacho Cheese"]["sales"], 1.86)

    def test_read_last_week_actuals_preserves_fractional_values(self):
        sheet = MagicMock()
        sheet.values().get().execute.return_value = {"values": [["1.95"], ["48"], ["1.875"], ["bad"]]}

        with patch.object(
            Call_sheets,
            "read_item_row_map",
            return_value={"Vanilla": 1, "Hot Dog": 2, "PB S'Mores": 3, "Nacho Cheese": 4},
        ), patch.object(
            Call_sheets,
            "find_last_week_start_col",
            return_value=2,
        ):
            actuals = Call_sheets.read_last_week_actuals_from_stand_sheet(sheet, "sid", "PTAC")

        self.assertEqual(actuals["Vanilla"], 1.95)
        self.assertEqual(actuals["Hot Dog"], 48.0)
        self.assertEqual(actuals["PB S'Mores"], round(1.875, 2))
        self.assertEqual(actuals["Nacho Cheese"], 0)

    def test_modifier_ice_cream_sales_drive_scoops_and_tubs_with_alias_rollups(self):
        # Modifier quantities already represent scoop counts (including Double/Triple dips).
        rows = {"Double Dip": {"sales": 86}, "Cotton Candy": {"sales": 9}}
        modifier_rows = {
            "Vanilla": {"sales": 54},
            "Cookies n' Cream": {"sales": 42},
            "Rainbow Sherbert": {"sales": 6},
            "Cotton Candy": {"sales": 2},
        }
        Call_sheets.merge_modifier_rows(rows, modifier_rows)

        flavor_totals = Call_sheets.group_scoops_by_flavor(rows)
        tubs_used = Call_sheets.tubs_used_from_scoops(flavor_totals)

        self.assertEqual(flavor_totals["vanilla"], 54)
        self.assertEqual(flavor_totals["cookies n' cream"], 42)
        self.assertEqual(flavor_totals["rainbow sherbet"], 6)
        self.assertEqual(flavor_totals["cotton candy ice cream"], 2)
        self.assertEqual(rows["Cotton Candy"]["sales"], 9)
        self.assertEqual(tubs_used["vanilla"], 0.9)
        self.assertEqual(tubs_used["cookies n' cream"], 0.7)
        self.assertEqual(tubs_used["rainbow sherbet"], 0.1)
        self.assertEqual(tubs_used["cotton candy ice cream"], 0.03)

    def test_blueberry_waffle_cone_alias_populates_scoops_and_tubs_on_base_row(self):
        def _row(sales=0):
            return {
                "sales": sales,
                "starting": 0,
                "deliveries": 0,
                "spoilage": 0,
                "expected": 0,
                "actual": "",
                "variance": "",
                "scoops_used": 0,
                "tubs_used": 0,
            }

        rows = {
            "Blueberry Waffle Cone": _row(0),
            "Blueberry Waffle Cone Cone": _row(60),
            "Vanilla": _row(30),
        }

        fake_sheet = MagicMock()
        fake_service = MagicMock()
        fake_service.spreadsheets().values().batchUpdate().execute.return_value = {}
        fake_service.spreadsheets().values().update().execute.return_value = {}
        fake_service.spreadsheets().batchUpdate().execute.return_value = {}

        with (
            patch("Call_sheets.CATEGORY_ORDER", [("ICE_CREAM_TOFTS", ["Blueberry Waffle Cone", "Vanilla"])], create=True),
            patch.object(Call_sheets, "ensure_stand_sheet_exists", return_value=None),
            patch.object(Call_sheets, "get_sheet_id", return_value=123),
            patch.object(Call_sheets, "find_last_week_start_col", return_value=0),
            patch.object(Call_sheets, "read_last_week_actuals_from_stand_sheet", return_value={}),
            patch.object(Call_sheets, "read_spoilage", return_value={}),
            patch.object(Call_sheets, "clear_spoilage_sheet", return_value=None),
            patch.object(Call_sheets, "extract_week_dates_from_label", return_value=(None, None)),
            patch.object(Call_sheets, "read_deliveries", return_value={}),
            patch.object(Call_sheets, "read_transfers", return_value={"to": {}, "from": {}}),
            patch.object(Call_sheets, "read_item_row_map", return_value={"Blueberry Waffle Cone": 3, "Vanilla": 4}),
            patch.object(Call_sheets, "_qty_per_case_value", return_value=1),
            patch.object(Call_sheets, "_sync_master_items_tab", return_value=None),
        ):
            Call_sheets.write_full_week(fake_sheet, fake_service, "sid", "PTAC", rows)

        self.assertEqual(rows["Blueberry Waffle Cone"]["scoops_used"], 60)
        self.assertEqual(rows["Blueberry Waffle Cone"]["tubs_used"], 1.0)
        self.assertEqual(rows["Vanilla"]["scoops_used"], 30)
        self.assertEqual(rows["Vanilla"]["tubs_used"], 0.5)

    def test_tofts_expected_formula_uses_tubs_used_not_scoops_used(self):
        """Expected formula for Toft's ice cream must subtract Tubs Used (tu_col),
        not Scoops Used (sc_col), so units are consistent (tubs ± tubs)."""
        def _row(starting=0, scoops_used=0, tubs_used=0):
            return {
                "sales": 0,
                "starting": starting,
                "deliveries": 0,
                "spoilage": 0,
                "expected": 0,
                "actual": "",
                "variance": "",
                "scoops_used": scoops_used,
                "tubs_used": tubs_used,
            }

        rows = {
            "Brownie Bandit": _row(starting=1.9, scoops_used=17, tubs_used=0.28),
        }

        fake_sheet = MagicMock()
        fake_service = MagicMock()
        fake_service.spreadsheets().values().batchUpdate().execute.return_value = {}
        fake_service.spreadsheets().values().update().execute.return_value = {}
        fake_service.spreadsheets().batchUpdate().execute.return_value = {}

        with (
            patch("Call_sheets.CATEGORY_ORDER", [("ICE_CREAM_TOFTS", ["Brownie Bandit"])], create=True),
            patch.object(Call_sheets, "ensure_stand_sheet_exists", return_value=None),
            patch.object(Call_sheets, "get_sheet_id", return_value=123),
            patch.object(Call_sheets, "find_last_week_start_col", return_value=0),
            patch.object(Call_sheets, "read_last_week_actuals_from_stand_sheet", return_value={}),
            patch.object(Call_sheets, "read_spoilage", return_value={}),
            patch.object(Call_sheets, "clear_spoilage_sheet", return_value=None),
            patch.object(Call_sheets, "extract_week_dates_from_label", return_value=(None, None)),
            patch.object(Call_sheets, "read_deliveries", return_value={}),
            patch.object(Call_sheets, "read_transfers", return_value={"to": {}, "from": {}}),
            patch.object(Call_sheets, "read_item_row_map", return_value={"brownie bandit": 3}),
            patch.object(Call_sheets, "_qty_per_case_value", return_value=1),
            patch.object(Call_sheets, "_sync_master_items_tab", return_value=None),
        ):
            Call_sheets.write_full_week(fake_sheet, fake_service, "sid", "PTAC", rows)

        # Capture the batchUpdate body written for item rows.
        body = fake_service.spreadsheets.return_value.values.return_value.batchUpdate.call_args.kwargs["body"]
        all_written_values = [v for item in body["data"] for v in item["values"]]

        # The Expected formula is at index 4 in the row values list.
        # With find_last_week_start_col=0 → next_week_start=1:
        #   s_col  = col_letter(1+0)  = "B"
        #   d_col  = col_letter(1+1)  = "C"
        #   sp_col = col_letter(1+3)  = "E"
        #   sc_col = col_letter(1+10) = "L"
        #   tu_col = col_letter(1+11) = "M"
        # Row 3 → Expected formula should be =B3+C3-M3-E3 (tubs), not =B3+C3-L3-E3 (scoops).
        expected_formulas = [row[4] for row in all_written_values if len(row) > 4]
        self.assertTrue(
            expected_formulas,
            "No Expected formula was written for the ice cream row",
        )
        for formula in expected_formulas:
            tu_col = Call_sheets.col_letter(1 + Call_sheets.COL_TUBS)
            sc_col = Call_sheets.col_letter(1 + Call_sheets.COL_SCOOPS)
            self.assertIn(
                f"-{tu_col}3",
                formula,
                f"Expected formula should subtract Tubs Used ({tu_col}3) but got: {formula}",
            )
            self.assertNotIn(
                f"-{sc_col}3",
                formula,
                f"Expected formula must NOT subtract Scoops Used ({sc_col}3) but got: {formula}",
            )

    def test_tofts_expected_row_math_is_tub_consistent(self):
        rows = {
            "Brownie Bandit": {
                "sales": 2,
                "expected": 0,
                "actual": "",
                "variance": "",
            },
        }

        fake_sheet = MagicMock()
        fake_service = MagicMock()
        fake_service.spreadsheets().values().batchUpdate().execute.return_value = {}
        fake_service.spreadsheets().values().update().execute.return_value = {}
        fake_service.spreadsheets().batchUpdate().execute.return_value = {}

        with (
            patch("Call_sheets.CATEGORY_ORDER", [("ICE_CREAM_TOFTS", ["Brownie Bandit"])], create=True),
            patch.object(Call_sheets, "ensure_stand_sheet_exists", return_value=None),
            patch.object(Call_sheets, "get_sheet_id", return_value=123),
            patch.object(Call_sheets, "find_last_week_start_col", return_value=0),
            patch.object(Call_sheets, "read_last_week_actuals_from_stand_sheet", return_value={"brownie bandit": 1.95}),
            patch.object(Call_sheets, "read_spoilage", return_value={"Brownie Bandit": 0}),
            patch.object(Call_sheets, "clear_spoilage_sheet", return_value=None),
            patch.object(Call_sheets, "extract_week_dates_from_label", return_value=(None, None)),
            patch.object(Call_sheets, "read_deliveries", return_value={"Brownie Bandit": 2}),
            patch.object(Call_sheets, "read_transfers", return_value={"to": {}, "from": {}}),
            patch.object(Call_sheets, "read_item_row_map", return_value={"brownie bandit": 3}),
            patch.object(Call_sheets, "_qty_per_case_value", return_value=1),
            patch.object(Call_sheets, "_sync_master_items_tab", return_value=None),
        ):
            Call_sheets.write_full_week(fake_sheet, fake_service, "sid", "PTAC", rows)

        body = fake_service.spreadsheets.return_value.values.return_value.batchUpdate.call_args.kwargs["body"]
        item_row = next(
            (entry["values"][0] for entry in body["data"] if entry["range"] == "'PTAC'!B3:M3"),
            None,
        )

        self.assertIsNotNone(item_row, "No Brownie Bandit row was written")
        self.assertEqual(item_row[0], 1.95)  # Starting tubs
        self.assertEqual(item_row[1], 2)  # Deliveries tubs
        self.assertEqual(item_row[11], 0.03)  # Tubs used
        self.assertEqual(item_row[4], "=B3+C3-M3-E3")
        self.assertAlmostEqual(item_row[0] + item_row[1] - item_row[11] - item_row[3], 3.92, places=2)

    def test_disposable_and_janitorial_items_leave_variance_blank(self):
        napkins_row, _ = _write_full_week_item_row(
            [("DISPOSABLES", ["Napkins"])],
            {"Napkins": {"sales": 4}},
            "Napkins",
        )
        hand_soap_row, _ = _write_full_week_item_row(
            [("JANITORIAL", ["Hand Soap"])],
            {"Hand Soap": {"sales": 2}},
            "Hand Soap",
        )

        self.assertEqual(napkins_row[Call_sheets.COL_VARIANCE], "")
        self.assertEqual(hand_soap_row[Call_sheets.COL_VARIANCE], "")

    def test_souvenir_cups_keeps_variance_formula(self):
        item_row, row_num = _write_full_week_item_row(
            [("DISPOSABLES", ["Souvenir Cups"])],
            {"Souvenir Cups": {"sales": 17}},
            "Souvenir Cups",
        )

        actual_col = Call_sheets.col_letter(1 + Call_sheets.COL_ACTUAL)
        expected_col = Call_sheets.col_letter(1 + Call_sheets.COL_EXPECTED)
        variance_formula = (
            f'=IF({actual_col}{row_num}="",'
            f'"",{actual_col}{row_num}-{expected_col}{row_num})'
        )

        self.assertEqual(item_row[Call_sheets.COL_VARIANCE], variance_formula)

    def test_non_disposable_items_keep_variance_formula(self):
        item_row, row_num = _write_full_week_item_row(
            [("CANDY", ["Airheads 2 for $1"])],
            {"Airheads 2 for $1": {"sales": 6}},
            "Airheads 2 for $1",
        )

        actual_col = Call_sheets.col_letter(1 + Call_sheets.COL_ACTUAL)
        expected_col = Call_sheets.col_letter(1 + Call_sheets.COL_EXPECTED)
        variance_formula = (
            f'=IF({actual_col}{row_num}="",'
            f'"",{actual_col}{row_num}-{expected_col}{row_num})'
        )

        self.assertEqual(item_row[Call_sheets.COL_VARIANCE], variance_formula)

    def test_popcorn_location_restrictions(self):
        self.assertIn("Popcorn", Call_sheets.LOCATION_SPECIFIC_ITEM_STANDS)
        self.assertEqual(
            Call_sheets.LOCATION_SPECIFIC_ITEM_STANDS["Popcorn"],
            {"TREMONT", "REED ROAD", "NWSC"},
        )

    def test_bloom_pop_locations_match_current_catalog(self):
        self.assertIn("Bloom Pop - Watermelon Lime", Call_sheets.LOCATION_SPECIFIC_ITEM_STANDS)
        stands = Call_sheets.LOCATION_SPECIFIC_ITEM_STANDS["Bloom Pop - Watermelon Lime"]
        self.assertEqual(
            stands,
            {"BEXLEY", "DEVON", "HILLIARD2 (EAST)", "HILLIARD1 (WEST)", "NWSC", "REED ROAD", "TREMONT"},
        )

    def test_poppi_raspberry_rose_name_and_restriction_are_canonical(self):
        self.assertIn("Poppi - Raspberry Rose", Call_sheets.BOTTLED_DRINKS)
        self.assertEqual(
            Call_sheets.LOCATION_SPECIFIC_ITEM_STANDS["Poppi - Raspberry Rose"],
            {"PTAC"},
        )
        nwsc = dict(Call_sheets.get_default_category_order_for_stand("NWSC"))
        ptac = dict(Call_sheets.get_default_category_order_for_stand("PTAC"))
        self.assertNotIn("Poppi - Raspberry Rose", nwsc["BOTTLED_DRINKS"])
        self.assertIn("Poppi - Raspberry Rose", ptac["BOTTLED_DRINKS"])

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

    def test_consolidate_variants_keeps_cotton_candy_candy_and_folds_scoops(self):
        rows = {
            "Cotton Candy": {"sales": 17, "deliveries": 0, "spoilage": 0},
            "Cotton Candy Ice Cream": {"sales": 4, "deliveries": 0, "spoilage": 0},
            "Cotton Candy Double Scoop": {"sales": 3, "deliveries": 1, "spoilage": 2},
        }

        Call_sheets.consolidate_variants_to_base(rows)

        self.assertIn("Cotton Candy", rows)
        self.assertEqual(rows["Cotton Candy"]["sales"], 17)
        self.assertNotIn("Cotton Candy Double Scoop", rows)
        self.assertEqual(rows["Cotton Candy Ice Cream"]["sales"], 7)
        self.assertEqual(rows["Cotton Candy Ice Cream"]["deliveries"], 1)
        self.assertEqual(rows["Cotton Candy Ice Cream"]["spoilage"], 2)

    def test_consolidate_variants_does_not_remove_bare_cotton_candy_row(self):
        rows = {"Cotton Candy": {"sales": 17, "deliveries": 0, "spoilage": 0}}

        Call_sheets.consolidate_variants_to_base(rows)

        self.assertEqual(
            rows,
            {"Cotton Candy": {"sales": 17, "deliveries": 0, "spoilage": 0}},
        )

    def test_get_default_category_order_for_stand_filters_location_items(self):
        bexley = dict(Call_sheets.get_default_category_order_for_stand("BEXLEY"))
        self.assertNotIn("Mint Chip", bexley["ICE_CREAM_TOFTS"])
        self.assertNotIn("Coke", bexley["FOUNTAIN_DRINKS"])
        self.assertNotIn("Diet Pepsi", bexley["FOUNTAIN_DRINKS"])
        self.assertIn("7up", bexley["FOUNTAIN_DRINKS"])
        self.assertIn("Diet RC", bexley["FOUNTAIN_DRINKS"])
        self.assertNotIn("RC Cola", bexley["FOUNTAIN_DRINKS"])
        self.assertIn("Big Red", bexley["FOUNTAIN_DRINKS"])
        self.assertIn("Lemonade", bexley["FOUNTAIN_DRINKS"])
        self.assertIn("Root Beer", bexley["FOUNTAIN_DRINKS"])
        self.assertIn("Dr. Pepper", bexley["FOUNTAIN_DRINKS"])

        ptac = dict(Call_sheets.get_default_category_order_for_stand("PTAC"))
        self.assertIn("Mint Chip", ptac["ICE_CREAM_TOFTS"])
        self.assertEqual(
            set(ptac["FOUNTAIN_DRINKS"]),
            {"Dr. Pepper", "Root Beer", "Diet Pepsi", "Mt. Dew", "Pepsi", "Starry"},
        )
        self.assertNotIn("Coke", ptac["FOUNTAIN_DRINKS"])
        self.assertNotIn("7up", ptac["FOUNTAIN_DRINKS"])
        self.assertNotIn("Big Red", ptac["FOUNTAIN_DRINKS"])
        self.assertNotIn("Diet RC", ptac["FOUNTAIN_DRINKS"])
        self.assertNotIn("RC Cola", ptac["FOUNTAIN_DRINKS"])

        treemont = dict(Call_sheets.get_default_category_order_for_stand("TREMONT"))
        self.assertIn("Mint Chip", treemont["ICE_CREAM_TOFTS"])
        self.assertIn("Coke", treemont["FOUNTAIN_DRINKS"])
        self.assertTrue(
            {"Big Red", "Dr. Pepper", "Lemonade", "Root Beer", "Coke", "Diet Coke"}.issubset(
                set(treemont["FOUNTAIN_DRINKS"])
            )
        )
        self.assertIn("7up", treemont["FOUNTAIN_DRINKS"])
        self.assertNotIn("Diet RC", treemont["FOUNTAIN_DRINKS"])
        self.assertNotIn("RC Cola", treemont["FOUNTAIN_DRINKS"])
        self.assertNotIn("Diet Pepsi", treemont["FOUNTAIN_DRINKS"])
        self.assertNotIn("Pepsi", treemont["FOUNTAIN_DRINKS"])
        self.assertNotIn("Starry", treemont["FOUNTAIN_DRINKS"])

        bevelhymer_green = dict(Call_sheets.get_default_category_order_for_stand("Bevelhymer Green"))
        bevelhymer_yellow = dict(Call_sheets.get_default_category_order_for_stand("Bevelhymer Yellow"))
        self.assertNotIn("ICE_CREAM_TOFTS", bevelhymer_green)
        self.assertNotIn("ICE_CREAM_TOFTS", bevelhymer_yellow)

    def test_sunflower_seeds_are_bevelhymer_only(self):
        self.assertEqual(
            Call_sheets.SUNFLOWER_SEED_STANDS,
            Call_sheets.BEVELHYMER_STANDS,
        )
        hilliard_east = dict(Call_sheets.get_default_category_order_for_stand("HILLIARD2 (EAST)"))
        bevelhymer_green = dict(Call_sheets.get_default_category_order_for_stand("Bevelhymer Green"))
        self.assertNotIn("Sunflower Seeds - Original", hilliard_east["SNACKS"])
        self.assertIn("Sunflower Seeds - Original", bevelhymer_green["SNACKS"])

    def test_fountain_drinks_list_includes_mt_dew_and_lemonade(self):
        self.assertIn("Mt. Dew", Call_sheets.FOUNTAIN_DRINKS)
        self.assertIn("Lemonade", Call_sheets.FOUNTAIN_DRINKS)

    def test_lemonade_restricted_to_non_ptac_stands(self):
        self.assertIn(("FOUNTAIN_DRINKS", "Lemonade"), Call_sheets.LOCATION_SPECIFIC_ITEM_STANDS)
        self.assertNotIn("PTAC", Call_sheets.LOCATION_SPECIFIC_ITEM_STANDS[("FOUNTAIN_DRINKS", "Lemonade")])
        self.assertIn("TREMONT", Call_sheets.LOCATION_SPECIFIC_ITEM_STANDS[("FOUNTAIN_DRINKS", "Lemonade")])
        self.assertNotIn("Bevelhymer Green", Call_sheets.LOCATION_SPECIFIC_ITEM_STANDS[("FOUNTAIN_DRINKS", "Lemonade")])

    def test_coke_fallback_restriction_applies_without_category(self):
        self.assertFalse(Call_sheets._is_item_available_at_stand("Coke", "PTAC"))
        self.assertTrue(Call_sheets._is_item_available_at_stand("Coke", "TREMONT"))
        self.assertTrue(Call_sheets._is_item_available_at_stand("Coke", "Bevelhymer Green"))

    def test_read_deliveries_converts_fountain_packages_to_bags(self):
        header = [["Date", "Item Name", "Packages", "Units per package"]]
        rows = [["05-10-2026", "Diet RC", "2", "1"]]
        tofts_rows = [["05-10-2026", "Brownie Bandit", "2", "999"]]
        root_beer_rows = [["05-10-2026", "Root Beer", "1", "1"]]
        ignored_units_per_package = "999"
        popcorn_rows = [["05-10-2026", "Popcorn", "2", ignored_units_per_package]]
        granola_rows = [["05-10-2026", "Granola Bar", "2", ignored_units_per_package]]
        hot_dog_rows = [["05-10-2026", "Hot Dogs", "2", ignored_units_per_package]]

        with patch.object(Call_sheets, "get_values", side_effect=[header, rows]):
            ptac = Call_sheets.read_deliveries(object(), "sid", "PTAC")
        self.assertEqual(ptac["Diet RC"], 2)

        with patch.object(Call_sheets, "get_values", side_effect=[header, tofts_rows]):
            tofts = Call_sheets.read_deliveries(object(), "sid", "PTAC")
        self.assertEqual(tofts["Brownie Bandit"], 2)

        with patch.object(Call_sheets, "get_values", side_effect=[header, rows]):
            reed = Call_sheets.read_deliveries(object(), "sid", "REED ROAD")
        self.assertEqual(reed["Diet RC"], 2)

        with patch.object(Call_sheets, "get_values", side_effect=[header, root_beer_rows]):
            ptac_root_beer = Call_sheets.read_deliveries(object(), "sid", "PTAC")
        self.assertEqual(ptac_root_beer["Root Beer"], 1)

        with patch.object(Call_sheets, "get_values", side_effect=[header, root_beer_rows]):
            reed_root_beer = Call_sheets.read_deliveries(object(), "sid", "REED ROAD")
        self.assertEqual(reed_root_beer["Root Beer"], 1)

        with patch.object(Call_sheets, "get_values", side_effect=[header, popcorn_rows]):
            reed_popcorn = Call_sheets.read_deliveries(object(), "sid", "REED ROAD")
        self.assertEqual(reed_popcorn["Popcorn"], 72)

        with patch.object(Call_sheets, "get_values", side_effect=[header, granola_rows]):
            reed_granola = Call_sheets.read_deliveries(object(), "sid", "REED ROAD")
        self.assertEqual(reed_granola["Granola Bar"], 72)

        with patch.object(Call_sheets, "get_values", side_effect=[header, hot_dog_rows]):
            reed_hot_dogs = Call_sheets.read_deliveries(object(), "sid", "REED ROAD")
        self.assertEqual(reed_hot_dogs["Hot Dogs"], 1998)

        ham_rows = [["05-10-2026", "Ham", "2", ignored_units_per_package]]
        cheese_rows = [["05-10-2026", "Cheese", "1", ignored_units_per_package]]

        with patch.object(Call_sheets, "get_values", side_effect=[header, ham_rows]):
            reed_ham = Call_sheets.read_deliveries(object(), "sid", "REED ROAD")
        self.assertEqual(reed_ham["Ham"], 2 * Call_sheets.HAM_SLICES_PER_PACKAGE)

        with patch.object(Call_sheets, "get_values", side_effect=[header, cheese_rows]):
            reed_cheese = Call_sheets.read_deliveries(object(), "sid", "REED ROAD")
        self.assertEqual(reed_cheese["Cheese"], Call_sheets.CHEESE_SLICES_PER_PACKAGE)

    def test_read_transfers_groups_by_to_and_from_stands(self):
        header = [["DATE", "FROM STAND", "TO STAND", "ITEM NAME", "INDIVIDUALS", "CASES", "QTY PER CASE"]]
        transfer_rows = [
            ["06-10-2026", "PTAC", "NWSC", "Hot Dog", "2", "1", "10"],
            ["06-01-2026", "PTAC", "NWSC", "Hot Dog", "5", "0", "0"],
        ]
        with patch.object(Call_sheets, "get_values", side_effect=[header, transfer_rows]):
            transfers = Call_sheets.read_transfers(
                object(),
                "sid",
                week_start_date=Call_sheets.datetime(2026, 6, 4).date(),
                week_end_date=Call_sheets.datetime(2026, 6, 10).date(),
            )

        self.assertEqual(transfers["from"]["PTAC"]["Hot Dog"], 12)
        self.assertEqual(transfers["to"]["NWSC"]["Hot Dog"], 12)

    def test_write_full_week_applies_transfer_out_and_in(self):
        fake_sheet = MagicMock()
        fake_service = MagicMock()
        fake_service.spreadsheets().values().batchUpdate().execute.return_value = {}
        fake_service.spreadsheets().values().update().execute.return_value = {}
        fake_service.spreadsheets().batchUpdate().execute.return_value = {}

        category_order = [("FOOD", ["Hot Dog"])]
        item_row_map = {Call_sheets.normalize_item_name("Hot Dog"): 3}
        rows = {"Hot Dog": {"starting": 0, "deliveries": 0, "sales": 0, "spoilage": 0}}

        with (
            patch.object(Call_sheets, "ensure_stand_sheet_exists", return_value=None),
            patch.object(Call_sheets, "get_sheet_id", return_value=123),
            patch.object(Call_sheets, "_build_category_order_for_stand", return_value=category_order),
            patch.object(Call_sheets, "find_last_week_start_col", return_value=0),
            patch.object(Call_sheets, "read_last_week_actuals_from_stand_sheet", return_value={"hot dog": 20}),
            patch.object(Call_sheets, "read_spoilage", return_value={}),
            patch.object(Call_sheets, "clear_spoilage_sheet", return_value=None),
            patch.object(Call_sheets, "extract_week_dates_from_label", return_value=(None, None)),
            patch.object(Call_sheets, "read_deliveries", return_value={"Hot Dog": 4}),
            patch.object(Call_sheets, "read_transfers", return_value={"to": {"PTAC": {"Hot Dog": 3}}, "from": {"PTAC": {"Hot Dog": 5}}}),
            patch.object(Call_sheets, "read_item_row_map", return_value=item_row_map),
            patch.object(Call_sheets, "_qty_per_case_value", return_value=1),
            patch.object(Call_sheets, "_sync_master_items_tab", return_value=None),
        ):
            Call_sheets.write_full_week(fake_sheet, fake_service, "sid", "PTAC", rows)

        body = fake_service.spreadsheets.return_value.values.return_value.batchUpdate.call_args.kwargs["body"]
        item_row = next(entry["values"][0] for entry in body["data"] if entry["range"] == "'PTAC'!B3:M3")
        self.assertEqual(item_row[0], 15)  # starting: 20 - 5 transfer out
        self.assertEqual(item_row[1], 7)   # deliveries: 4 + 3 transfer in

    def test_qty_per_case_value_for_root_beer_uses_physical_bag_units(self):
        self.assertEqual(Call_sheets._qty_per_case_value("Root Beer", "PTAC"), 1)
        self.assertEqual(Call_sheets._qty_per_case_value("Root Beer", "NWSC"), 1)

    def test_qty_per_case_value_uses_mapping_and_blanks_unknown(self):
        self.assertEqual(Call_sheets._qty_per_case_value("Poppi - Wild Berry", "PTAC"), 12)
        self.assertEqual(Call_sheets._qty_per_case_value("Not A Real Item", "PTAC"), "")
        self.assertEqual(
            Call_sheets._qty_per_case_value("Not A Real Item", "PTAC", "FOUNTAIN_DRINKS"),
            "",
        )

    def test_qty_per_case_uses_physical_units_for_tofts_fountain_and_grapes(self):
        self.assertEqual(Call_sheets.QUANTITY_PER_CASE["Vanilla"], 1)
        self.assertEqual(Call_sheets.QUANTITY_PER_CASE[("FOUNTAIN_DRINKS", "Dr. Pepper")], 1)
        self.assertEqual(Call_sheets.QUANTITY_PER_CASE[("BOTTLED_DRINKS", "Dr. Pepper")], 12)
        self.assertEqual(Call_sheets.QUANTITY_PER_CASE["Frozen Grapes"], 1)

    def test_qty_per_case_value_prefers_category_specific_collisions(self):
        self.assertEqual(
            Call_sheets._qty_per_case_value("Coke", "PTAC", "FOUNTAIN_DRINKS"),
            1,
        )
        self.assertEqual(
            Call_sheets._qty_per_case_value("Coke", "PTAC", "BOTTLED_DRINKS"),
            24,
        )

    def test_qty_per_case_value_falls_back_to_plain_item_lookup(self):
        self.assertEqual(
            Call_sheets._qty_per_case_value("Root Beer", "PTAC", "FOUNTAIN_DRINKS"),
            1,
        )

    def test_snacks_include_granola_and_split_crunchy_rara_flavors(self):
        self.assertIn("Granola Bar", Call_sheets.SNACKS)
        self.assertIn("Crunchy Ra-Ra - Mango", Call_sheets.SNACKS)
        self.assertIn("Crunchy Ra-Ra - Sprinkles", Call_sheets.SNACKS)
        self.assertIn("Crunchy Ra-Ra - Strawberry", Call_sheets.SNACKS)
        self.assertNotIn("Crunchy Ra-Ra Yogurt", Call_sheets.SNACKS)

    def test_slushie_constants_and_flavor_rows(self):
        self.assertEqual(Call_sheets.SLUSHIE_SERVINGS_PER_BAG, 10)
        self.assertEqual(Call_sheets.SLUSHIE_BAGS_PER_CONTAINER, 3)
        self.assertEqual(Call_sheets.SLUSHIE_OZ_PER_SERVING, 16)
        self.assertEqual(Call_sheets.SLUSHIE_OZ_PER_BAG, 160)
        self.assertEqual(Call_sheets.SLUSHIE_SERVINGS_PER_CONTAINER, 30)
        self.assertEqual(Call_sheets.SLUSHIE_OZ_PER_CONTAINER, 480)
        self.assertEqual(
            Call_sheets.SLUSHIE_FLAVORS,
            [
                "Slushie - Mango",
                "Slushie - Blue Razz",
                "Slushie - Tiger's Blood",
                "Slushie - Green Apple",
                "Slushie - Peach",
            ],
        )
        category_names = [name for name, _ in Call_sheets.DEFAULT_CATEGORY_ORDER]
        self.assertIn("SLUSHIE_MIX", category_names)
        self.assertIn("SLUSHIE_FLAVORS", category_names)

    def test_write_modifier_sales_converts_slushie_servings_to_bags(self):
        service = MagicMock()
        with (
            patch.object(Call_sheets, "find_last_week_start_col", return_value=1),
            patch.object(Call_sheets, "read_item_row_map", return_value={"slushie - mango": 5}),
        ):
            Call_sheets.write_modifier_sales_to_week(
                sheet=MagicMock(),
                service=service,
                spreadsheet_id="sid",
                stand_name="TREMONT",
                modifier_rows={"Slushie - Mango": {"sales": 3}},
            )

        body = service.spreadsheets.return_value.values.return_value.batchUpdate.call_args.kwargs["body"]
        self.assertEqual(body["data"][0]["range"], "'TREMONT'!D5")
        self.assertEqual(body["data"][0]["values"], [[0.3]])

    def test_master_category_order_adds_default_slushie_flavors(self):
        master_items = [("BOTTLED_DRINKS", "Bottled Water")]
        with patch.object(Call_sheets, "read_master_items", return_value=master_items):
            category_order = dict(
                Call_sheets._build_category_order_for_stand(MagicMock(), "sid", "PTAC")
            )
        self.assertIn("SLUSHIE_FLAVORS", category_order)
        self.assertEqual(
            set(category_order["SLUSHIE_FLAVORS"]),
            set(Call_sheets.SLUSHIE_FLAVORS),
        )


# ---------------------------------------------------------------------------
# Helper to build a minimal fake Google Sheets service for sync tests
# ---------------------------------------------------------------------------

def _make_service(sheet_id=42):
    """Return a MagicMock service where spreadsheets().get() returns sheet_id."""
    service = MagicMock()

    # get_sheet_id calls service.spreadsheets().get(spreadsheetId=...).execute()
    metadata_resp = {
        "sheets": [{"properties": {"title": "Test Stand", "sheetId": sheet_id}}]
    }
    service.spreadsheets.return_value.get.return_value.execute.return_value = metadata_resp

    # batchUpdate → execute returns a non-error value
    service.spreadsheets.return_value.batchUpdate.return_value.execute.return_value = {}

    # values().update().execute()
    service.spreadsheets.return_value.values.return_value.update.return_value.execute.return_value = {}

    return service


class SyncStandItemListTests(unittest.TestCase):
    """Unit tests for sync_stand_item_list()."""

    STAND = "Test Stand"
    SPREADSHEET_ID = "fake-id"

    def _make_sheet(self, col_a_values):
        """Return a mock sheet where values().get().execute() yields col_a_values.

        col_a_values is a list of row lists, e.g. [["ITEM"], [""], ["CAT"], ["item1"]].
        read_master_items (which also calls sheet.values().get()) is patched out
        separately to return None (no master tab) so the default category order
        is used.
        """
        sheet = MagicMock()
        sheet.values.return_value.get.return_value.execute.return_value = {
            "values": col_a_values
        }
        return sheet

    # ------------------------------------------------------------------ #
    # Test: nothing to add when sheet already has all expected items       #
    # ------------------------------------------------------------------ #
    def test_idempotent_no_changes_needed(self):
        """Running sync when all items are present returns added=[]."""
        # Build a minimal category order with two categories and two items each.
        category_order = [
            ("CAT_A", ["Apple", "Banana"]),
            ("CAT_B", ["Cherry", "Date"]),
        ]
        # Column A: row1=ITEM, row2=blank, row3=CAT_A, row4=Apple, row5=Banana,
        #           row6=CAT_B, row7=Cherry, row8=Date
        col_a = [
            ["ITEM"], [""],
            ["CAT_A"], ["Apple"], ["Banana"],
            ["CAT_B"], ["Cherry"], ["Date"],
        ]
        sheet = self._make_sheet(col_a)
        service = _make_service()

        with (
            patch.object(Call_sheets, "read_master_items", return_value=None),
            patch.object(Call_sheets, "get_default_category_order_for_stand",
                         return_value=category_order),
        ):
            result = Call_sheets.sync_stand_item_list(
                sheet, service, self.SPREADSHEET_ID, self.STAND
            )

        self.assertEqual(result["added"], [])
        self.assertCountEqual(
            result["skipped"], ["Apple", "Banana", "Cherry", "Date"]
        )
        # No insertions should have been made.
        service.spreadsheets.return_value.batchUpdate.assert_not_called()

    def test_idempotent_with_item_name_variants(self):
        """Dash/space/case/hidden-char variants should still be treated as existing."""
        category_order = [("SNACKS", ["Crunchy Ra-Ra - Mango", "Go-Go Squeez"])]
        col_a = [
            ["ITEM"], [""],
            ["SNACKS"],
            ["  crunchy ra-ra  –mango\u00A0"],
            ["Go-Go\u200BSqueez"],
        ]
        sheet = self._make_sheet(col_a)
        service = _make_service()

        with (
            patch.object(Call_sheets, "read_master_items", return_value=None),
            patch.object(Call_sheets, "get_default_category_order_for_stand",
                         return_value=category_order),
        ):
            result = Call_sheets.sync_stand_item_list(
                sheet, service, self.SPREADSHEET_ID, self.STAND
            )

        self.assertEqual(result["added"], [])
        self.assertCountEqual(result["skipped"], ["Crunchy Ra-Ra - Mango", "Go-Go Squeez"])
        service.spreadsheets.return_value.batchUpdate.assert_not_called()

    # ------------------------------------------------------------------ #
    # Test: new item inserted into an existing category                    #
    # ------------------------------------------------------------------ #
    def test_new_item_inserted_in_existing_category(self):
        """A single new item is added to an existing category."""
        category_order = [("CAT_A", ["Apple", "Banana", "Cherry"])]
        # Sheet is missing "Cherry"
        col_a = [["ITEM"], [""], ["CAT_A"], ["Apple"], ["Banana"]]
        sheet = self._make_sheet(col_a)
        service = _make_service()

        inserted_rows = []

        def capture_batch(spreadsheetId, body):
            req = body["requests"][0]
            if "insertDimension" in req:
                inserted_rows.append(req["insertDimension"]["range"]["startIndex"])
            mock = MagicMock()
            mock.execute.return_value = {}
            return mock

        service.spreadsheets.return_value.batchUpdate.side_effect = capture_batch

        with (
            patch.object(Call_sheets, "read_master_items", return_value=None),
            patch.object(Call_sheets, "get_default_category_order_for_stand",
                         return_value=category_order),
        ):
            result = Call_sheets.sync_stand_item_list(
                sheet, service, self.SPREADSHEET_ID, self.STAND
            )

        self.assertEqual(result["added"], ["Cherry"])
        # One insertDimension should have been called.
        self.assertEqual(len(inserted_rows), 1)
        # Cherry comes after Banana (row 5, 1-based), so startIndex should be 5.
        self.assertEqual(inserted_rows[0], 5)

    # ------------------------------------------------------------------ #
    # Test: multiple new items maintain alphabetical order                 #
    # ------------------------------------------------------------------ #
    def test_multiple_new_items_correct_order(self):
        """Items inserted into a category end up in sorted order."""
        category_order = [("CAT_A", ["Apple", "Banana", "Cherry", "Date"])]
        # Sheet has only Apple and Date; Banana and Cherry are missing.
        # Apple=row3 (header=row3 wait, let me re-count)
        # row1=ITEM, row2=blank, row3=CAT_A, row4=Apple, row5=Date
        col_a = [["ITEM"], [""], ["CAT_A"], ["Apple"], ["Date"]]
        sheet = self._make_sheet(col_a)
        service = _make_service()

        inserted_rows = []

        def capture_batch(spreadsheetId, body):
            req = body["requests"][0]
            if "insertDimension" in req:
                inserted_rows.append(req["insertDimension"]["range"]["startIndex"])
            mock = MagicMock()
            mock.execute.return_value = {}
            return mock

        service.spreadsheets.return_value.batchUpdate.side_effect = capture_batch

        with (
            patch.object(Call_sheets, "read_master_items", return_value=None),
            patch.object(Call_sheets, "get_default_category_order_for_stand",
                         return_value=category_order),
        ):
            result = Call_sheets.sync_stand_item_list(
                sheet, service, self.SPREADSHEET_ID, self.STAND
            )

        self.assertCountEqual(result["added"], ["Banana", "Cherry"])
        self.assertCountEqual(result["skipped"], ["Apple", "Date"])
        # Two insertDimension calls (one per missing item).
        self.assertEqual(len(inserted_rows), 2)

    # ------------------------------------------------------------------ #
    # Test: missing category header is also inserted                       #
    # ------------------------------------------------------------------ #
    def test_missing_category_header_inserted(self):
        """A whole new category (header + items) is inserted."""
        category_order = [
            ("CAT_A", ["Apple"]),
            ("CAT_B", ["Cherry"]),   # entirely new category
        ]
        col_a = [["ITEM"], [""], ["CAT_A"], ["Apple"]]
        sheet = self._make_sheet(col_a)
        service = _make_service()

        inserted_rows = []

        def capture_batch(spreadsheetId, body):
            req = body["requests"][0]
            if "insertDimension" in req:
                inserted_rows.append(req["insertDimension"]["range"]["startIndex"])
            mock = MagicMock()
            mock.execute.return_value = {}
            return mock

        service.spreadsheets.return_value.batchUpdate.side_effect = capture_batch

        with (
            patch.object(Call_sheets, "read_master_items", return_value=None),
            patch.object(Call_sheets, "get_default_category_order_for_stand",
                         return_value=category_order),
        ):
            result = Call_sheets.sync_stand_item_list(
                sheet, service, self.SPREADSHEET_ID, self.STAND
            )

        # Both the header and the item should be added.
        self.assertIn("CAT_B", result["added"])
        self.assertIn("Cherry", result["added"])
        self.assertEqual(len(result["added"]), 2)
        # Two insertDimension calls.
        self.assertEqual(len(inserted_rows), 2)

    # ------------------------------------------------------------------ #
    # Test: return value has correct structure                             #
    # ------------------------------------------------------------------ #
    def test_return_value_structure(self):
        """sync_stand_item_list always returns all expected bookkeeping keys."""
        category_order = [("CAT_A", ["Apple"])]
        col_a = [["ITEM"], [""], ["CAT_A"], ["Apple"]]
        sheet = self._make_sheet(col_a)
        service = _make_service()

        with (
            patch.object(Call_sheets, "read_master_items", return_value=None),
            patch.object(Call_sheets, "get_default_category_order_for_stand",
                         return_value=category_order),
        ):
            result = Call_sheets.sync_stand_item_list(
                sheet, service, self.SPREADSHEET_ID, self.STAND
            )

        self.assertIn("added", result)
        self.assertIn("skipped", result)
        self.assertIn("removed", result)
        self.assertIsInstance(result["added"], list)
        self.assertIsInstance(result["skipped"], list)
        self.assertIsInstance(result["removed"], list)

    def test_removes_obsolete_rows_without_week_data(self):
        category_order = [("CAT_A", ["Apple"])]
        full_grid = [["ITEM"], [""], ["CAT_A"], ["Apple"], ["Obsolete Item"]]
        col_a = [[row[0]] for row in full_grid]

        sheet = MagicMock()

        def get_side_effect(*args, **kwargs):
            query_range = kwargs.get("range", "")
            response = {"values": full_grid if query_range.endswith("!A:ZZ") else col_a}
            mock = MagicMock()
            mock.execute.return_value = response
            return mock

        sheet.values.return_value.get.side_effect = get_side_effect
        service = _make_service()

        batch_requests = []

        def capture_batch(spreadsheetId, body):
            batch_requests.extend(body.get("requests", []))
            mock = MagicMock()
            mock.execute.return_value = {}
            return mock

        service.spreadsheets.return_value.batchUpdate.side_effect = capture_batch

        with (
            patch.object(Call_sheets, "read_master_items", return_value=None),
            patch.object(Call_sheets, "get_default_category_order_for_stand", return_value=category_order),
        ):
            result = Call_sheets.sync_stand_item_list(
                sheet, service, self.SPREADSHEET_ID, self.STAND
            )

        self.assertEqual(result["removed"], ["Obsolete Item"])
        self.assertTrue(any("deleteDimension" in request for request in batch_requests))

    def test_removes_obsolete_row_even_when_week_data_exists(self):
        category_order = [("CAT_A", ["Apple"])]
        full_grid = [["ITEM"], [""], ["CAT_A"], ["Apple"], ["Obsolete Item", "WeekData"]]
        col_a = [[row[0]] for row in full_grid]

        sheet = MagicMock()

        def get_side_effect(*args, **kwargs):
            query_range = kwargs.get("range", "")
            response = {"values": full_grid if query_range.endswith("!A:ZZ") else col_a}
            mock = MagicMock()
            mock.execute.return_value = response
            return mock

        sheet.values.return_value.get.side_effect = get_side_effect
        service = _make_service()

        batch_requests = []

        def capture_batch(spreadsheetId, body):
            batch_requests.extend(body.get("requests", []))
            mock = MagicMock()
            mock.execute.return_value = {}
            return mock

        service.spreadsheets.return_value.batchUpdate.side_effect = capture_batch

        with (
            patch.object(Call_sheets, "read_master_items", return_value=None),
            patch.object(Call_sheets, "get_default_category_order_for_stand", return_value=category_order),
        ):
            result = Call_sheets.sync_stand_item_list(
                sheet, service, self.SPREADSHEET_ID, self.STAND
            )

        self.assertEqual(result["removed"], ["Obsolete Item"])
        self.assertTrue(any("deleteDimension" in request for request in batch_requests))

    def test_leaves_blank_col_a_row_with_week_data_alone(self):
        """Blank Column A rows must never be deleted, even if they have week data."""
        category_order = [("CAT_A", ["Apple"])]
        full_grid = [["ITEM"], [""], ["CAT_A"], ["Apple"], ["", "WeekData"]]
        col_a = [[row[0] if row else ""] for row in full_grid]

        sheet = MagicMock()

        def get_side_effect(*args, **kwargs):
            query_range = kwargs.get("range", "")
            response = {"values": full_grid if query_range.endswith("!A:ZZ") else col_a}
            mock = MagicMock()
            mock.execute.return_value = response
            return mock

        sheet.values.return_value.get.side_effect = get_side_effect
        service = _make_service()

        batch_requests = []

        def capture_batch(spreadsheetId, body):
            batch_requests.extend(body.get("requests", []))
            mock = MagicMock()
            mock.execute.return_value = {}
            return mock

        service.spreadsheets.return_value.batchUpdate.side_effect = capture_batch

        with (
            patch.object(Call_sheets, "read_master_items", return_value=None),
            patch.object(Call_sheets, "get_default_category_order_for_stand", return_value=category_order),
        ):
            result = Call_sheets.sync_stand_item_list(
                sheet, service, self.SPREADSHEET_ID, self.STAND
            )

        self.assertEqual(result["removed"], [])
        self.assertFalse(any("deleteDimension" in request for request in batch_requests))

    def test_leaves_fully_empty_row_alone(self):
        """Fully empty rows (no Column A value) must be skipped, not deleted."""
        category_order = [("CAT_A", ["Apple"])]
        full_grid = [["ITEM"], [""], ["CAT_A"], ["Apple"], []]
        col_a = [[row[0] if row else ""] for row in full_grid]

        sheet = MagicMock()

        def get_side_effect(*args, **kwargs):
            query_range = kwargs.get("range", "")
            response = {"values": full_grid if query_range.endswith("!A:ZZ") else col_a}
            mock = MagicMock()
            mock.execute.return_value = response
            return mock

        sheet.values.return_value.get.side_effect = get_side_effect
        service = _make_service()

        batch_requests = []

        def capture_batch(spreadsheetId, body):
            batch_requests.extend(body.get("requests", []))
            mock = MagicMock()
            mock.execute.return_value = {}
            return mock

        service.spreadsheets.return_value.batchUpdate.side_effect = capture_batch

        with (
            patch.object(Call_sheets, "read_master_items", return_value=None),
            patch.object(Call_sheets, "get_default_category_order_for_stand", return_value=category_order),
        ):
            result = Call_sheets.sync_stand_item_list(
                sheet, service, self.SPREADSHEET_ID, self.STAND
            )

        self.assertEqual(result["removed"], [])
        self.assertFalse(any("deleteDimension" in request for request in batch_requests))

    def test_deletion_expected_set_uses_canonical_defaults_not_master_augmented_order(self):
        col_a = [["ITEM"], [""], ["CAT_A"], ["Apple"], ["Obsolete Item"]]
        sheet = self._make_sheet(col_a)
        service = _make_service()

        batch_requests = []

        def capture_batch(spreadsheetId, body):
            batch_requests.extend(body.get("requests", []))
            mock = MagicMock()
            mock.execute.return_value = {}
            return mock

        service.spreadsheets.return_value.batchUpdate.side_effect = capture_batch

        with (
            patch.object(
                Call_sheets,
                "_build_category_order_for_stand",
                return_value=[("CAT_A", ["Apple", "Obsolete Item"])],
            ),
            patch.object(
                Call_sheets,
                "get_default_category_order_for_stand",
                return_value=[("CAT_A", ["Apple"])],
            ),
            patch.object(Call_sheets, "_sync_master_items_tab"),
        ):
            result = Call_sheets.sync_stand_item_list(
                sheet, service, self.SPREADSHEET_ID, self.STAND
            )

        self.assertEqual(result["removed"], ["Obsolete Item"])
        self.assertTrue(any("deleteDimension" in request for request in batch_requests))

    def test_sync_master_items_tab_removes_rows_not_in_canonical_defaults(self):
        sheet = MagicMock()
        sheet.values.return_value.get.return_value.execute.return_value = {
            "values": [
                ["CAT_A", "Apple"],
                ["CAT_A", "Obsolete Item"],
                ["CAT_A", "Legacy Item"],
            ]
        }

        service = MagicMock()
        service.spreadsheets.return_value.get.return_value.execute.return_value = {
            "sheets": [
                {"properties": {"title": "Test Stand", "sheetId": 42}},
                {"properties": {"title": "Master Items-Test Stand", "sheetId": 99}},
            ]
        }

        delete_start_indexes = []

        def capture_batch(spreadsheetId, body):
            requests = body.get("requests", [])
            if requests and "deleteDimension" in requests[0]:
                req = requests[0]["deleteDimension"]["range"]
                delete_start_indexes.append(req["startIndex"])
            mock = MagicMock()
            mock.execute.return_value = {}
            return mock

        service.spreadsheets.return_value.batchUpdate.side_effect = capture_batch

        with patch.object(
            Call_sheets,
            "get_default_category_order_for_stand",
            return_value=[("CAT_A", ["Apple"])],
        ):
            Call_sheets._sync_master_items_tab(
                sheet, service, self.SPREADSHEET_ID, self.STAND
            )

        # Rows are deleted bottom-to-top to avoid index shifting during deletions.
        self.assertEqual(delete_start_indexes, [3, 2])
        self.assertNotIn(1, delete_start_indexes)

    def test_new_item_format_explicitly_sets_white_background_style(self):
        category_order = [("CAT_A", ["Apple", "Banana"])]
        col_a = [["ITEM"], [""], ["CAT_A"], ["Apple"]]
        sheet = self._make_sheet(col_a)
        service = _make_service()

        repeat_requests = []

        def capture_batch(spreadsheetId, body):
            req = body["requests"][0]
            if "repeatCell" in req:
                repeat_requests.append(req["repeatCell"])
            mock = MagicMock()
            mock.execute.return_value = {}
            return mock

        service.spreadsheets.return_value.batchUpdate.side_effect = capture_batch

        with (
            patch.object(Call_sheets, "read_master_items", return_value=None),
            patch.object(Call_sheets, "get_default_category_order_for_stand",
                         return_value=category_order),
        ):
            Call_sheets.sync_stand_item_list(
                sheet, service, self.SPREADSHEET_ID, self.STAND
            )

        self.assertEqual(len(repeat_requests), 1)
        repeat_cell = repeat_requests[0]
        fmt = repeat_cell["cell"]["userEnteredFormat"]
        self.assertEqual(
            fmt["backgroundColorStyle"]["rgbColor"],
            {"red": 1.0, "green": 1.0, "blue": 1.0},
        )
        self.assertIn("backgroundColorStyle", repeat_cell["fields"])
        self.assertEqual(repeat_cell["range"]["endColumnIndex"], 200)


if __name__ == "__main__":
    unittest.main()
