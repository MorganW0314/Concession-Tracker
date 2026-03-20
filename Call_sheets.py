import csv
from unittest import result
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from collections import defaultdict
from datetime import datetime
import re
import unicodedata
import requests


def get_sheet_id(service, spreadsheet_id, sheet_name):
    sheet_metadata = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    for sheet in sheet_metadata["sheets"]:
        if sheet["properties"]["title"] == sheet_name:
            return sheet["properties"]["sheetId"]
    raise ValueError(f"Sheet name '{sheet_name}' not found.")

def create_weekly_sheet(service, spreadsheet_id, stand_name):
    # 1. Generate the new tab name including stand name
    from datetime import datetime
    new_title = datetime.today().strftime(f"{stand_name} - Week of %m-%d-%Y")

    # 2. Create a new blank sheet tab
    requests = [{
        "addSheet": {
            "properties": {
                "title": new_title,
                "gridProperties": {"rowCount": 500, "columnCount": 11}
            }
        }
    }]

    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": requests}
    ).execute()

    # 3. Return the new sheet name
    return new_title


#For scoops in range(UNIT_CONVERSION)
    
UNIT_CONVERSION = {
    # Vanilla
    "Vanilla": 1,
    "Vanilla Double Scoop": 2,
    "Vanilla Triple Scoop": 3,

    # Chocolate
    "Chocolate": 1,
    "Chocolate Double Scoop": 2,
    "Chocolate Triple Scoop": 3,

    # Cookies N Cream
    "Cookies N Cream": 1,
    "Cookies N Cream Double Scoop": 2,
    "Cookies N Cream Triple Scoop": 3,

    # Cookie Dough
    "Cookie Dough": 1,
    "Cookie Dough Double Scoop": 2,
    "Cookie Dough Triple Scoop": 3,

    # Cotton Candy
    "Cotton Candy": 1,
    "Cotton Candy Double Scoop": 2,
    "Cotton Candy Triple Scoop": 3,

    # Cookie Monster
    "Cookie Monster": 1,
    "Cookie Monster Double Scoop": 2,
    "Cookie Monster Triple Scoop": 3,

    # Mint Chip
    "Mint Chip": 1,
    "Mint Chip Double Scoop": 2,
    "Mint Chip Triple Scoop": 3,

    # Peanut Butter Cup
    "Peanut Butter Cup": 1,
    "Peanut Butter Cup Double Scoop": 2,
    "Peanut Butter Cup Triple Scoop": 3,

    # Strawberry Cheesecake
    "Strawberry Cheesecake": 1,
    "Strawberry Cheesecake Double Scoop": 2,
    "Strawberry Cheesecake Triple Scoop": 3,

    # Super Duper Scoop
    "Super Duper Scoop": 1,
    "Super Duper Scoop Double Scoop": 2,
    "Super Duper Scoop Triple Scoop": 3,

    # Rainbow Sherbert
    "Rainbow Sherbert": 1,
    "Rainbow Sherbert Double Scoop": 2,
    "Rainbow Sherbert Triple Scoop": 3,

    # Brownie Bandit
    "Brownie Bandit": 1,
    "Brownie Bandit Double Scoop": 2,
    "Brownie Bandit Triple Scoop": 3,

    # Airheads (non-ice cream)
    "Airheads 2 for $1": 2,
}
def normalize_flavor(item):
    """Normalize only the flavor portion of an ice cream scoop item."""
    item = item.lower().strip()

    scoop_suffixes = [
        "single scoop",
        "double scoop",
        "triple scoop",
        "scoop"
    ]

    for suffix in scoop_suffixes:
        if item.endswith(suffix):
            item = item[: -len(suffix)].strip()

    return item

def normalize_item(item):
    """Normalize item names for matching sheet rows without collapsing categories."""
    item = item.lower()
    item = item.replace("’", "'")
    item = "".join(ch for ch in item if ch.isalnum() or ch.isspace())
    item = " ".join(item.split())
    return item


#

def write_values (sheet, spreadsheet_id, range_string, values):
    """Write a 2D list of values to a range."""
    body = {"values": values}

    result = sheet.values().update(
    spreadsheetId=spreadsheet_id,
    range=range_string,
    valueInputOption="RAW",
        body=body
    ).execute()

    return result


def append_row(range_string, row, spreadsheet_id, sheet):
    """Append a single row to the bottom of a sheet."""
    body = {"values": [row]}

    result = sheet.values().update(
    spreadsheetId=spreadsheet_id,
        range=range_string,
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body=body
    ).execute()

    return result
def get_values(sheet, spreadsheet_id, range_string):
    """Read values from a range and return a 2D list."""
    result = sheet.values().get(
        spreadsheetId=spreadsheet_id,
        range=range_string
    ).execute()

    return result.get("values", [])

def read_deliveries(sheet, spreadsheet_id, stand_name):
    """Read the Deliveries - {stand} tab and accumulate deliveries per item.

    Tab format (row 1 = header, rows 2+ = data):
      A: DATE  (optional, for record-keeping)
      B: ITEM
      C: PACKAGES / QUANTITY
      D: UNITS PER PACKAGE  (optional, defaults to 1)

    Quantities are ACCUMULATED so multiple deliveries in one week are summed.
    """
    tab = f"Deliveries-{stand_name}"
    rows = get_values(sheet, spreadsheet_id, f"'{tab}'!A2:D200")

    deliveries = {}

    for row in rows:
        if len(row) < 3:
            continue  # need at least Date, Item, Quantity

        item = row[1].strip() if len(row) > 1 else ""
        if not item:
            continue

        try:
            packages = int(row[2].strip()) if row[2].strip() else 0
        except (ValueError, IndexError):
            packages = 0

        try:
            units_per = int(row[3].strip()) if len(row) > 3 and row[3].strip() else 1
        except (ValueError, IndexError):
            units_per = 1

        total_units = packages * units_per
        # ACCUMULATE so mid-week deliveries are summed, not overwritten
        deliveries[item] = deliveries.get(item, 0) + total_units

    return deliveries

def read_spoilage(sheet, spreadsheet_id, stand_name):
    """Read the Spoilage - {stand} tab and return accumulated spoilage per item.

    Tab format (row 1 = header, rows 2+ = data):
      A: DATE  (optional, for record-keeping)
      B: ITEM
      C: UNITS SPOILED

    Quantities are ACCUMULATED across all rows for the week.
    """
    tab = f"Spoilage-{stand_name}"
    try:
        rows = get_values(sheet, spreadsheet_id, f"'{tab}'!A2:C200")
    except Exception as e:
        print(f"Warning: Could not read spoilage sheet '{tab}'. Starting with no spoilage data.")
        return {}

    spoilage = {}

    for row in rows:
        if len(row) < 3:
            continue  # need at least Date, Item, Quantity

        item = row[1].strip() if len(row) > 1 else ""
        if not item:
            continue

        try:
            units_spoiled = int(row[2].strip()) if row[2].strip() else 0
        except (ValueError, IndexError):
            units_spoiled = 0

        # ACCUMULATE across all spoilage entries for the week
        spoilage[item] = spoilage.get(item, 0) + units_spoiled

    return spoilage


def clear_spoilage_sheet(sheet, spreadsheet_id, stand_name):
    """Clear all data rows from the Spoilage sheet after reading."""
    tab = f"Spoilage-{stand_name}"
    try:
        # Delete rows 2 onwards (keep header in row 1)
        sheet.values().clear(
            spreadsheetId=spreadsheet_id,
            range=f"'{tab}'!A2:C1000"
        ).execute()
        print(f"Cleared spoilage data from {tab}")
    except Exception as e:
        print(f"Could not clear spoilage sheet: {e}")

def read_master_items(sheet, spreadsheet_id, stand_name):
    """Read the Master Items - {stand} tab and return a list of (category, item) tuples.

    Tab format (row 1 = header, rows 2+ = data):
      A: CATEGORY
      B: ITEM

    Returns a list of (category, item) tuples, or None if the tab is missing/empty.
    This list is used to build the CATEGORY_ORDER for write_full_week so items
    always appear even when not sold in a given week.
    """
    tab = f"Master Items-{stand_name}"
    try:
       rows = get_values(sheet, spreadsheet_id, f"'{tab}'!A2:B500")
    except Exception:
        return None  # Tab does not exist yet

    if not rows:
        return None

    items = []
    for row in rows:
        if len(row) < 2:
            continue
        category = row[0].strip()
        item = row[1].strip()
        if category and item:
            items.append((category, item))

    return items if items else None


def read_sales(sheet, spreadsheet_id, sheet_name):
    """
    Read the SALES column from the weekly sheet and return dict:
    normalized_item_name -> actual sales value.
    """
    range_string = f"{sheet_name}!A2:H200"
    rows = get_values(sheet, spreadsheet_id, range_string)

    sales = {}

    for row in rows:
        if len(row) < 8:
            continue

        item_name = row[0].strip()
        actual_sales = row[7]  # Column H

        if actual_sales == "":
            continue

        try:
            actual_sales = float(actual_sales)
        except:
            continue

        key = normalize_item(item_name)

        if key not in sales:
            sales[key] = 0

        sales[key] += actual_sales

    return sales

def build_ice_cream_row_lookup(sheet, spreadsheet_id, sheet_name):
    """
    Build a lookup: normalized flavor -> row number in the weekly sheet.
    """
    range_string = f"{sheet_name}!A2:A200"
    rows = get_values(sheet, spreadsheet_id, range_string)

    lookup = {}

    row_number = 2
    for row in rows:
        if not row:
            row_number += 1
            continue

        item_name = row[0].strip()

        # Only map ice cream rows
        if "ice cream" not in item_name.lower():
            row_number += 1
            continue

        # Normalize for matching scoops
        flavor = normalize_flavor(item_name)

        lookup[flavor] = row_number
        row_number += 1

    return lookup


SCOOPS_PER_TUB = 60

SCOOP_MAP = {
    "Single Scoop": 1,
    "Double Scoop": 2,
    "Triple Scoop": 3
}

def scoops_from_item(name):
    if "Triple" in name:
        return 3
    elif "Double" in name:
        return 2
    elif "Single" in name or "Scoop" in name:
        return 1
    else:
        return 1  # Base flavor = 1 scoop per sale



def group_scoops_by_flavor(rows):
    """
    Given parsed CSV rows, return dict: flavor -> total scoops.
    Uses flavor normalization that strips scoop descriptors only.
    """
    flavor_totals = {}

    for item_name, data in rows.items():
        name_lower = item_name.lower()

         # Check if this item is in TOFTS_ICE_CREAM (handles base + variants)
        is_tofts_ice_cream = False
        for tofts_flavor in TOFTS_ICE_CREAM:
            if normalize_flavor(item_name) == normalize_flavor(tofts_flavor):
                is_tofts_ice_cream = True
                break
        
        if not is_tofts_ice_cream:
            continue

        # Extract sales from the row dict
        quantity = data.get("sales", 0)
        if not isinstance(quantity, (int, float)):
            continue

        flavor = normalize_flavor(item_name)
        
        # Count scoops: determine multiplier based on scoop type
        if "triple scoop" in name_lower:
            scoops = quantity * 3
        elif "double scoop" in name_lower or "double" in name_lower:
            scoops = quantity * 2
        elif "single scoop" in name_lower:
            scoops = quantity * 1
        else:
            scoops = quantity * 1  # Base flavor defaults to 1 scoop

        if flavor not in flavor_totals:
            flavor_totals[flavor] = 0

        flavor_totals[flavor] += scoops

    return flavor_totals



def tubs_used_from_scoops(flavor_totals):
    tubs_used = {
        flavor: round(scoops / SCOOPS_PER_TUB, 2)
        for flavor, scoops in flavor_totals.items()
    }
    print("Tubs used:", tubs_used)
    return tubs_used



def write_ice_cream_inventory(sheet, flavor_totals, tubs_used, row_lookup):
    for flavor, scoops in flavor_totals.items():
        row = row_lookup.get(flavor)
        if not row:
            continue

        # Column indices (adjust if needed)
        SALES_COL = 5
        SPOILAGE_COL = 6
        EXPECTED_COL = 7
        STARTING_COL = 3
        DELIVERIES_COL = 4

        # Write scoops sold
        sheet.update_cell(row, SALES_COL, scoops)

        # Read starting + deliveries + spoilage
        starting = float(sheet.cell(row, STARTING_COL).value or 0)
        delivered = float(sheet.cell(row, DELIVERIES_COL).value or 0)
        spoilage = float(sheet.cell(row, SPOILAGE_COL).value or 0)

        expected = starting + delivered - tubs_used[flavor] - spoilage

        sheet.update_cell(row, EXPECTED_COL, round(expected, 2))

def calculate_variance(sheet, row_lookup):
    for flavor, row in row_lookup.items():
        expected = sheet.cell(row, 7).value
        actual = sheet.cell(row, 8).value

        if actual:
            variance = float(actual) - float(expected)
            sheet.update_cell(row, 9, round(variance, 2))




def calculate_expected_inventory(starting, deliveries, sales, spoilage):
    """
    Calculate expected inventory for each item:
    expected = starting + deliveries - sales - spoilage
    Missing values default to 0.
    """
    expected = {}

    # Get a unified set of all item names
    all_items = set(starting.keys()) | set(deliveries.keys()) | set(sales.keys()) | set(spoilage.keys())

    for item in all_items:
        start = starting.get(item, 0)
        delivered = deliveries.get(item, 0)
        sold = sales.get(item, 0)
        spoiled = spoilage.get(item, 0)

        expected[item] = start + delivered - sold - spoiled

    return expected

def ensure_tab_exists(service, SPREADSHEET_ID, range_string, values, tab_name):
    """Create the tab if it does not exist and return its sheetId."""
    metadata = service.spreadsheets().get(
        spreadsheetId=SPREADSHEET_ID
    ).execute()

    sheets = metadata.get("sheets", [])
    
    # Check if tab already exists
    for s in sheets:
        if s["properties"]["title"] == tab_name:
            return s["properties"]["sheetId"]

    # If not found, create it
    requests = [{
        "addSheet": {
            "properties": {
                "title": tab_name,
                "gridProperties": {"rowCount": 500, "columnCount": 10}
            }
        }
    }]

    response = service.spreadsheets().batchUpdate(
        spreadsheetId=SPREADSHEET_ID,
        body={"requests": requests}
    ).execute()

    return response["replies"][0]["addSheet"]["properties"]["sheetId"]

TOFTS_ICE_CREAM = [
    "Vanilla",
    "Mint Chip",
    "Chocolate",
    "Cookie Dough",
    "Cookies & Cream",
    "Cotton Candy",
    "Cookie Monster",
    "Peanut Butter Cup",
    "Strawberry Cheesecake",
    "Super Duper Scoop",
    "Rainbow Sherbert",
    "Brownie Bandit"
]


NOVELTY_ICE_CREAM = [
        "Bomb Pop",
        "Cannonball!!!",
        "Cookie Sandwich",
        "Hawaiian Shaved Ice Ball",
        "Nerd Bomb Pop",
        "Ninja Turtles Ice Cream",
        "Rainbow Sherbet Float",
        "Root Beer Float",
        "Snickers Ice Cream Bar",
        "Sonic The Hedgehog",
        "Spiderman Ice Cream",
        "Spongebob Ice Cream",
        "Strawberry Shortcake Bar",
        "Twix Ice Cream Bar"
    ]

CANDY = [
        "Airheads 2 for $1",
        "Cotton Candy",
        "Cow Tail",
        "Nerds Clusters",
        "Ring Pop",
        "Slime Lickers",
        "Sour Patch Kids",
        "Starburst",
        "Swedish Fish",
        "Xtremes"
    ]

DRINKS = [
        "Bottled Water",
        "Coca-Cola",
        "Dr. Pepper",
        "Gatorade Blue",
        "Gatorade Orange",
        "Gatorade Red",
        "Gatorade White",
        "Ice + Water",
        "Razzberry Tea",
        "Root Beer",
        "Souvenir Cup",
        "Soda Refill $1"
    ]

MEALS = [
        "BBQ Pork Sandwich",
        "Chicken Salad Sandwich",
        "Chili Cheese Dog",
        "Chili Cheese Nachos",
        "Hot Dog",
        "Pizza Slice",
        "Pulled Pork Nachos",
        "Uncrustable",
        "Walking Taco",
        "Cup of Cheese",
        "Whole Jet's Pizza"
    ]

SNACKS = [
        "Assorted Chips",
        "Frozen Grapes",
        "Hummus and Pita Chips",
        "Smoothies",
        "String Cheese",
        "Jumbo Pickle",
        "Nachos & Cheese",
        "Soft Pretzel"
    ]

    # Manual category (not in CSV)
SYRUPS = [
    "Blue Raspberry Syrup (decimal estimate)",
    "Cherry Syrup (decimal estimate)",
    "Grape Syrup (decimal estimate)",
    "Orange Syrup (decimal estimate)",
    "Root Beer Syrup (decimal estimate)",
    "Cotton Candy Syrup (decimal estimate)"
]

BIB_SYRUPS = [
    "Dr. Pepper (decimal estimate)",
    "Rootbeer (decimal estimate)",
    "Pepsi (decimal estimate)",
    "Diet Pepsi (decimal estimate)",
    "Mt Dew (decimal estimate)",
    "Starry (decimal estimate)",
    "Slushi Mix (count in bag; 10 per box)"
]






JANITORIAL = [
        "Paper Towels (count rolls)",
        "Trash Bags (count rolls)",
        "Gloves (estimate)",
        "Soap (estimate)",
        "Sanitizer (estimate)",
        "Napkins (estimate)",
        "Cups (estimate)",
        "CO2 Tanks (eye track)",
        "Syrup Bags (eye track)"
    
    ]

SNOW_CONE_AND_FOUNTAIN_SYRUPS = SYRUPS + BIB_SYRUPS 
# Combine all category lists
all_categories = {
    "TOFTS_ICE_CREAM": TOFTS_ICE_CREAM,
    "NOVELTY_ICE_CREAM": NOVELTY_ICE_CREAM,
    "CANDY": CANDY,
    "DRINKS": DRINKS,
    "MEALS": MEALS,
    "SNACKS": SNACKS,
    "JANITORIAL": JANITORIAL,
    "SNOW_CONE_AND_FOUNTAIN_SYRUPS": SNOW_CONE_AND_FOUNTAIN_SYRUPS
}

def read_last_week_inventory(service, spreadsheet_id, previous_sheet_name):
    values = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f"{previous_sheet_name}!A2:K300"
    ).execute().get("values", [])

    ending = {}

    for row in values:
        if len(row) < 2:
            continue

        item = row[1].strip()  # Column B
        if not item:
            continue

        expected = row[8] if len(row) > 8 and row[8] != "" else None
        actual = row[9] if len(row) > 9 and row[9] != "" else None

        try:
            expected = int(float(expected)) if expected is not None else None
        except:
            expected = None

        try:
            actual = int(float(actual)) if actual is not None else None
        except:
            actual = None

        if actual is not None:
            ending[item] = actual
        elif expected is not None:
            ending[item] = expected
        else:
            ending[item] = 0
        
        # ADD THIS: Also add normalized key for matching
        normalized = normalize_flavor(item)
        if normalized != item:
            ending[normalized] = ending[item]

    return ending

def find_previous_week_sheet_name(service, spreadsheet_id, current_sheet_name, stand_name):
    """Return the sheet name of the most recent weekly sheet before the current one for a stand."""
    # Get spreadsheet metadata
    metadata = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    sheets = metadata.get("sheets", [])

    prefix = f"{stand_name} - Week of "
    weekly_sheets = []

    for s in sheets:
        title = s["properties"]["title"]

        # Only consider weekly sheets for this stand
        if not title.startswith(prefix):
            continue

        # Extract date portion
        try:
            date_str = title[len(prefix):].strip()
            date_obj = datetime.strptime(date_str, "%m-%d-%Y")
            weekly_sheets.append((title, date_obj))
        except:
            continue  # Skip sheets with unexpected names

    # Sort by date
    weekly_sheets.sort(key=lambda x: x[1])

    # Find the sheet immediately before the current one
    for i, (title, date_obj) in enumerate(weekly_sheets):
        if title == current_sheet_name and i > 0:
            return weekly_sheets[i - 1][0]

    return None  # No previous sheet found


def write_full_week(sheet, service, spreadsheet_id, sheet_name, rows, stand_name):

    """
    Writes a fully formatted weekly inventory sheet for a given stand with:
    - Category grouping (from Master Items tab or hardcoded fallback)
    - Blue header row, light-blue category rows matching 2025 sheet design
    - Green/red conditional formatting on Variance column
    - Variance written as a formula so it auto-calculates when Actual is filled
    - Frozen header row
    """

    # ============================
    # CATEGORY ORDER
    # Try to read from "Master Items - {stand}" tab first; fall back to hardcoded lists.
    # ============================

    master_items = read_master_items(sheet, spreadsheet_id, stand_name)

    if master_items:
        from collections import OrderedDict
        category_map = OrderedDict()
        for category, item in master_items:
            if category not in category_map:
                category_map[category] = []
            category_map[category].append(item)
        CATEGORY_ORDER = list(category_map.items())
    else:
        CATEGORY_ORDER = [
            ("ICE CREAM (Toft's Scoops)", TOFTS_ICE_CREAM),
            ("NOVELTY ICE CREAM", NOVELTY_ICE_CREAM),
            ("CANDY", CANDY),
            ("DRINKS", DRINKS),
            ("MEALS", MEALS),
            ("SNACKS", SNACKS),
            ("SNOW CONES / SYRUPS", SNOW_CONE_AND_FOUNTAIN_SYRUPS),
            ("JANITORIAL / CONSUMABLES", JANITORIAL),
        ]

    # ====================================================================
    # ENSURE ALL ITEMS FROM CATEGORY_ORDER APPEAR, EVEN WITH 0 SALES
    # ====================================================================
    for category_name, item_list in CATEGORY_ORDER:
        for item in item_list:
            if item not in rows:
                rows[item] = {
                    "starting": 0,
                    "deliveries": 0,
                    "sales": 0,
                    "spoilage": 0,
                    "scoops_used": 0,
                    "tubs_used": 0,
                    "expected": 0,
                    "actual": "",
                }
                normalized = normalize_flavor(item)
                if normalized not in rows:
                    rows[normalized] = rows[item]

    # ------------------------------------------------------------
    # ICE CREAM SCOOP + TUBS LOGIC
    # ------------------------------------------------------------
    flavor_totals = group_scoops_by_flavor(rows)
    tubs_used = tubs_used_from_scoops(flavor_totals)

    for flavor, scoops in flavor_totals.items():
        found = False
        for tofts_flavor in TOFTS_ICE_CREAM:
            if normalize_flavor(tofts_flavor) == flavor:
                rows[tofts_flavor]["scoops_used"] = scoops
                rows[tofts_flavor]["tubs_used"] = tubs_used.get(flavor, 0)
                found = True
                break
        if not found:
            for item_name in list(rows.keys()):
                if normalize_flavor(item_name) == flavor:
                    rows[item_name]["scoops_used"] = scoops
                    rows[item_name]["tubs_used"] = tubs_used.get(flavor, 0)
                    break

    # Consolidate variant sales to base Toft's flavors
    for tofts_flavor in TOFTS_ICE_CREAM:
        normalized = normalize_flavor(tofts_flavor)
        total_sales = sum(
            rows[item_name].get("sales", 0)
            for item_name in list(rows.keys())
            if normalize_flavor(item_name) == normalized
        )
        rows[tofts_flavor]["sales"] = total_sales

    # ------------------------------------------------------------
    # FIND PREVIOUS WEEK'S SHEET (per stand)
    # ------------------------------------------------------------
    previous_sheet_name = find_previous_week_sheet_name(
        service, spreadsheet_id, sheet_name, stand_name
    )

    # ------------------------------------------------------------
    # READ PREVIOUS WEEK'S ENDING INVENTORY
    # ------------------------------------------------------------
    if previous_sheet_name:
        last_week_ending = read_last_week_inventory(
            service, spreadsheet_id, previous_sheet_name
        )
    else:
        last_week_ending = {}

    # ------------------------------------------------------------
    # MERGE INTO STARTING INVENTORY
    # ------------------------------------------------------------
    for item in rows:
        rows[item]["starting"] = last_week_ending.get(item, 0)

    # ------------------------------------------------------------
    # SPOILAGE INTEGRATION
    # ------------------------------------------------------------
    spoilage_totals = read_spoilage(sheet, spreadsheet_id, stand_name)
    for item in rows:
        rows[item]["spoilage"] = spoilage_totals.get(item, 0)
    clear_spoilage_sheet(sheet, spreadsheet_id, stand_name)
    # ------------------------------------------------------------
    # DELIVERIES INTEGRATION (accumulated)
    # ------------------------------------------------------------
    delivery_totals = read_deliveries(sheet, spreadsheet_id, stand_name)
    for delivery_item, qty in delivery_totals.items():
        found = False
        for tofts_flavor in TOFTS_ICE_CREAM:
            if tofts_flavor == delivery_item:
                rows[tofts_flavor]["deliveries"] = qty
                found = True
                break
        if not found:
            for item_name in list(rows.keys()):
                if item_name == delivery_item:
                    rows[item_name]["deliveries"] = qty
                    break

    # ------------------------------------------------------------
    # EXPECTED INVENTORY CALCULATION
    # ------------------------------------------------------------
    expected_totals = calculate_expected_inventory(
        {item: rows[item].get("starting", 0) for item in rows},
        {item: rows[item].get("deliveries", 0) for item in rows},
        {item: rows[item].get("sales", 0) for item in rows},
        {item: rows[item].get("spoilage", 0) for item in rows},
    )
    for item in rows:
        rows[item]["expected"] = expected_totals.get(item, 0)

    # ------------------------------------------------------------
    # BUILD OUTPUT ROWS
    # Track sheet row numbers so variance formulas reference correct cells.
    # Row 1 = header, rows 2+ = data/category rows.
    # ------------------------------------------------------------
    header = [
        "CATEGORY", "ITEM", "STARTING", "DELIVERIES",
        "SALES", "SCOOPS USED", "TUBS USED", "SPOILAGE", "EXPECTED", "ACTUAL", "VARIANCE"
    ]
    # Derive column letters from header positions (0-indexed → A, B, C ...)
    COL_EXPECTED = chr(ord("A") + header.index("EXPECTED"))   # I
    COL_ACTUAL   = chr(ord("A") + header.index("ACTUAL"))     # J

    output_rows = [header]
    sheet_row = 2  # first data row in the sheet (1-indexed)

    for category_name, item_list in CATEGORY_ORDER:
        output_rows.append([category_name] + [""] * 10)
        sheet_row += 1

        for item in sorted(item_list):
            if item in rows:
                variance_formula = (
                    f'=IF({COL_ACTUAL}{sheet_row}="",'
                    f'"",{COL_ACTUAL}{sheet_row}-{COL_EXPECTED}{sheet_row})'
                )
                output_rows.append([
                    "", item,
                    rows[item].get("starting", 0),
                    rows[item].get("deliveries", 0),
                    rows[item].get("sales", 0),
                    rows[item].get("scoops_used", 0),
                    rows[item].get("tubs_used", 0),
                    rows[item].get("spoilage", 0),
                    rows[item].get("expected", 0),
                    rows[item].get("actual", ""),
                    variance_formula,
                ])
            else:
                output_rows.append(["", item, "", "", "", "", "", "", "", "", ""])
            sheet_row += 1

    # ------------------------------------------------------------
    # WRITE VALUES TO SHEET
    # ------------------------------------------------------------
    expected_cols = len(header)
    for i, row in enumerate(output_rows):
        if len(row) < expected_cols:
            output_rows[i] = row + [""] * (expected_cols - len(row))
        elif len(row) > expected_cols:
            output_rows[i] = row[:expected_cols]

    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"{sheet_name}!A1:K",
        valueInputOption="USER_ENTERED",
        body={"values": output_rows}
    ).execute()

    # ------------------------------------------------------------
    # FORMATTING REQUESTS
    # ------------------------------------------------------------
    requests = []
    sheet_id = get_sheet_id(service, spreadsheet_id, sheet_name)

    # Freeze header row
    requests.append({
        "updateSheetProperties": {
            "properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 1}},
            "fields": "gridProperties.frozenRowCount"
        }
    })

    # Set column widths
    requests.append({
        "updateDimensionProperties": {
            "range": {
                "sheetId": sheet_id,
                "dimension": "COLUMNS",
                "startIndex": 0,
                "endIndex": 11
            },
            "properties": {"pixelSize": 140},
            "fields": "pixelSize"
        }
    })

    # Header row: blue background, white bold text, centered
    requests.append({
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 0,
                "endRowIndex": 1,
                "startColumnIndex": 0,
                "endColumnIndex": 11
            },
            "cell": {
                "userEnteredFormat": {
                    "backgroundColor": {"red": 0.267, "green": 0.447, "blue": 0.769},
                    "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
                    "horizontalAlignment": "CENTER"
                }
            },
            "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)"
        }
    })

    # Category rows: light blue background, bold text
    category_names_set = {cat for cat, _ in CATEGORY_ORDER}
    for i, row in enumerate(output_rows):
        if isinstance(row, list) and len(row) >= 2 and row[0] in category_names_set and row[1] == "":
            requests.append({
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": i,
                        "endRowIndex": i + 1,
                        "startColumnIndex": 0,
                        "endColumnIndex": 11
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": {"red": 0.647, "green": 0.761, "blue": 0.902},
                            "textFormat": {"bold": True}
                        }
                    },
                    "fields": "userEnteredFormat(backgroundColor,textFormat)"
                }
            })

    # Conditional formatting: green for positive variance, red for negative
    variance_col_idx = header.index("VARIANCE")
    variance_range = [{
        "sheetId": sheet_id,
        "startRowIndex": 1,
        "endRowIndex": len(output_rows),
        "startColumnIndex": variance_col_idx,
        "endColumnIndex": variance_col_idx + 1
    }]
    requests.append({
        "addConditionalFormatRule": {
            "rule": {
                "ranges": variance_range,
                "booleanRule": {
                    "condition": {"type": "NUMBER_GREATER", "values": [{"userEnteredValue": "0"}]},
                    "format": {"backgroundColor": {"red": 0.576, "green": 0.769, "blue": 0.490}}
                }
            },
            "index": 0
        }
    })
    # Conditional formatting: red for negative variance
    requests.append({
        "addConditionalFormatRule": {
            "rule": {
                "ranges": variance_range,
                "booleanRule": {
                    "condition": {"type": "NUMBER_LESS", "values": [{"userEnteredValue": "0"}]},
                    "format": {"backgroundColor": {"red": 0.918, "green": 0.267, "blue": 0.208}}
                }
            },
            "index": 1
        }
    })

    # ------------------------------------------------------------
    # APPLY FORMATTING
    # ------------------------------------------------------------
    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": requests}
    ).execute()






def connect_to_sheets():
    creds = Credentials.from_service_account_file(
        r"C:\Users\willi\OneDrive\Desktop\inventory_Script\Credentials-personal.json",
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    service = build("sheets", "v4", credentials=creds)
    return service

