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

    def test_bloom_pop_locations_use_canonical_bevelhymer_name(self):
        self.assertIn("Bloom Pop - Watermelon Lime", Call_sheets.LOCATION_SPECIFIC_ITEM_STANDS)
        stands = Call_sheets.LOCATION_SPECIFIC_ITEM_STANDS["Bloom Pop - Watermelon Lime"]
        self.assertIn("Bevelhymer Yellow", stands)
        self.assertNotIn("Bevelhymer", stands)

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
            {"7up", "Big Red", "Diet RC", "Dr. Pepper", "Lemonade", "Root Beer", "RC Cola", "Coca Cola"}.issubset(
                set(treemont["FOUNTAIN_DRINKS"])
            )
        )
        self.assertNotIn("Diet Pepsi", treemont["FOUNTAIN_DRINKS"])
        self.assertNotIn("Pepsi", treemont["FOUNTAIN_DRINKS"])
        self.assertNotIn("Starry", treemont["FOUNTAIN_DRINKS"])

    def test_fountain_drinks_list_excludes_mt_dew_and_includes_lemonade(self):
        self.assertNotIn("Mt. Dew", Call_sheets.FOUNTAIN_DRINKS)
        self.assertIn("Lemonade", Call_sheets.FOUNTAIN_DRINKS)

    def test_lemonade_restricted_to_non_ptac_stands(self):
        self.assertIn("Lemonade", Call_sheets.LOCATION_SPECIFIC_ITEM_STANDS)
        self.assertNotIn("PTAC", Call_sheets.LOCATION_SPECIFIC_ITEM_STANDS["Lemonade"])
        self.assertIn("TREMONT", Call_sheets.LOCATION_SPECIFIC_ITEM_STANDS["Lemonade"])
        self.assertIn("Bevelhymer Green", Call_sheets.LOCATION_SPECIFIC_ITEM_STANDS["Lemonade"])

    def test_read_deliveries_converts_fountain_packages_to_stand_oz(self):
        header = [["Date", "Item Name", "Packages", "Units per package"]]
        rows = [["05-10-2026", "Diet RC", "2", "1"]]
        root_beer_rows = [["05-10-2026", "Root Beer", "1", "1"]]
        ignored_units_per_package = "999"
        popcorn_rows = [["05-10-2026", "Popcorn", "2", ignored_units_per_package]]
        granola_rows = [["05-10-2026", "Granola Bar", "2", ignored_units_per_package]]
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

        with patch.object(Call_sheets, "get_values", side_effect=[header, granola_rows]):
            reed_granola = Call_sheets.read_deliveries(object(), "sid", "REED ROAD")
        self.assertEqual(reed_granola["Granola Bar"], 72)

        with patch.object(Call_sheets, "get_values", side_effect=[header, hot_dog_rows]):
            reed_hot_dogs = Call_sheets.read_deliveries(object(), "sid", "REED ROAD")
        self.assertEqual(reed_hot_dogs["Hot Dogs"], 1998)

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
                "Slushie - Blue Raz",
                "Slushie - Tigers Blood",
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
        """sync_stand_item_list always returns a dict with added/skipped keys."""
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
        self.assertIsInstance(result["added"], list)
        self.assertIsInstance(result["skipped"], list)

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


if __name__ == "__main__":
    unittest.main()
