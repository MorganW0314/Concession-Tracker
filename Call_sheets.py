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


# ---------------------------------------------------------------------------
# Horizontal-week layout constants
# ---------------------------------------------------------------------------
# Each week occupies this many columns to the right of Column A.
COLS_PER_WEEK = 9

# Sub-header labels written in row 2 for every week block.
WEEK_COL_HEADERS = [
    "Starting", "Deliveries", "Sales", "Spoilage",
    "Expected", "Actual", "Variance", "Scoops Used", "Tubs Used",
]

# 0-based offsets within a week's column block.
COL_STARTING   = 0
COL_DELIVERIES = 1
COL_SALES      = 2
COL_SPOILAGE   = 3
COL_EXPECTED   = 4
COL_ACTUAL     = 5
COL_VARIANCE   = 6
COL_SCOOPS     = 7
COL_TUBS       = 8

# Fixed row numbers (1-indexed) in every stand sheet.
HEADER_ROW    = 1   # Week-label row  (e.g. "Week of 03-23-2026")
SUBHEADER_ROW = 2   # Column-name row (Starting | Deliveries | …)
DATA_START_ROW = 3  # First category / item row


def col_letter(col_index):
    """Convert a 0-based column index to an A1-notation letter string.

    Examples: 0 → "A", 25 → "Z", 26 → "AA", 51 → "AZ", 52 → "BA".
    """
    result = ""
    n = col_index + 1
    while n > 0:
        n, remainder = divmod(n - 1, 26)
        result = chr(65 + remainder) + result
    return result


def find_last_week_start_col(sheet, spreadsheet_id, sheet_name):
    """Return the 0-based column index of the *last* week-label written in row 1.

    Week labels are placed in the first column of every week block (B, K, T, …).
    Column A ("ITEM") is always skipped.
    Returns 0 when no weeks have been appended yet.
    """
    result = sheet.values().get(
        spreadsheetId=spreadsheet_id,
        range=f"'{sheet_name}'!{HEADER_ROW}:{HEADER_ROW}",
    ).execute()

    row = (result.get("values") or [[]])[0]
    last_week_start = 0
    for i in range(1, len(row)):   # skip col A (index 0)
        if row[i]:
            last_week_start = i
    return last_week_start


def read_item_row_map(sheet, spreadsheet_id, sheet_name):
    """Read column A of a stand sheet and return {item_name: row_number}.

    Rows 1 and 2 are header rows and are always skipped.
    Row numbers are 1-indexed (matching Google Sheets notation).
    """
    result = sheet.values().get(
        spreadsheetId=spreadsheet_id,
        range=f"'{sheet_name}'!A:A",
    ).execute()

    col_a = result.get("values", [])
    item_row_map = {}
    for i, cell in enumerate(col_a):
        row_num = i + 1
        if row_num < DATA_START_ROW:
            continue
        if cell and cell[0].strip():
            item_row_map[cell[0].strip()] = row_num
    return item_row_map


def read_last_week_actuals_from_stand_sheet(sheet, spreadsheet_id, sheet_name):
    """Return the most recent week's Actual values as {item_name: quantity}.

    The Actual column is at offset COL_ACTUAL within its week's block.
    Returns an empty dict when no weeks have been written yet.
    """
    last_week_start = find_last_week_start_col(sheet, spreadsheet_id, sheet_name)
    if last_week_start == 0:
        return {}

    actual_col = col_letter(last_week_start + COL_ACTUAL)

    # Read both column A (names) and the Actual column in one pass via item_row_map.
    item_row_map = read_item_row_map(sheet, spreadsheet_id, sheet_name)

    result = sheet.values().get(
        spreadsheetId=spreadsheet_id,
        range=f"'{sheet_name}'!{actual_col}:{actual_col}",
    ).execute()
    actual_col_values = result.get("values", [])

    actuals = {}
    for item, row_num in item_row_map.items():
        idx = row_num - 1   # 0-based
        if idx < len(actual_col_values):
            cell = actual_col_values[idx]
            if cell and cell[0]:
                try:
                    actuals[item] = int(float(cell[0]))
                except (ValueError, TypeError):
                    actuals[item] = 0
    return actuals


def ensure_stand_sheet_exists(service, spreadsheet_id, stand_name, sheet, category_order):
    """Create a stand sheet and populate Column A if it does not already exist.

    The sheet is named after the stand (e.g. "Bevelhymer Green").
    Row 1 gets "ITEM" in A1.
    Rows starting at DATA_START_ROW contain category headers and sorted item names.
    Returns the integer sheetId.
    """
    metadata = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    for s in metadata.get("sheets", []):
        if s["properties"]["title"] == stand_name:
            return s["properties"]["sheetId"]

    # Create the sheet tab.
    response = service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": [{
            "addSheet": {
                "properties": {
                    "title": stand_name,
                    "gridProperties": {"rowCount": 500, "columnCount": 200},
                }
            }
        }]},
    ).execute()
    new_sheet_id = response["replies"][0]["addSheet"]["properties"]["sheetId"]

    # Build column A content: [ITEM label, blank sub-header row, then categories/items].
    col_a_data = [["ITEM"], [""]]
    for category_name, item_list in category_order:
        col_a_data.append([category_name])
        for item in sorted(item_list):
            col_a_data.append([item])

    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"'{stand_name}'!A1",
        valueInputOption="RAW",
        body={"values": col_a_data},
    ).execute()

    # --- Formatting for column A ---
    fmt_requests = []

    # Freeze top 2 rows and the first column so they stay visible while scrolling.
    fmt_requests.append({
        "updateSheetProperties": {
            "properties": {
                "sheetId": new_sheet_id,
                "gridProperties": {"frozenRowCount": 2, "frozenColumnCount": 1},
            },
            "fields": "gridProperties.frozenRowCount,gridProperties.frozenColumnCount",
        }
    })

    # A1 header: blue background, white bold centred text.
    fmt_requests.append({
        "repeatCell": {
            "range": {
                "sheetId": new_sheet_id,
                "startRowIndex": 0, "endRowIndex": 1,
                "startColumnIndex": 0, "endColumnIndex": 1,
            },
            "cell": {
                "userEnteredFormat": {
                    "backgroundColor": {"red": 0.267, "green": 0.447, "blue": 0.769},
                    "textFormat": {
                        "bold": True,
                        "foregroundColor": {"red": 1, "green": 1, "blue": 1},
                    },
                    "horizontalAlignment": "CENTER",
                }
            },
            "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)",
        }
    })

    # Category rows in column A: light-blue background, bold text.
    row_idx = DATA_START_ROW - 1   # 0-based
    for category_name, item_list in category_order:
        fmt_requests.append({
            "repeatCell": {
                "range": {
                    "sheetId": new_sheet_id,
                    "startRowIndex": row_idx, "endRowIndex": row_idx + 1,
                    "startColumnIndex": 0, "endColumnIndex": 1,
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": {"red": 0.647, "green": 0.761, "blue": 0.902},
                        "textFormat": {"bold": True},
                    }
                },
                "fields": "userEnteredFormat(backgroundColor,textFormat)",
            }
        })
        row_idx += 1 + len(item_list)  # skip category row + all its items

    # Set column A width to 200 px so item names are fully visible.
    fmt_requests.append({
        "updateDimensionProperties": {
            "range": {
                "sheetId": new_sheet_id,
                "dimension": "COLUMNS",
                "startIndex": 0,
                "endIndex": 1,
            },
            "properties": {"pixelSize": 200},
            "fields": "pixelSize",
        }
    })

    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": fmt_requests},
    ).execute()

    return new_sheet_id


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
    range_str = f"'{tab}'!A2:D200"
    print(f"Stand name: '{stand_name}'")
    print(f"Tab name: '{tab}'")
    print(f"Range: '{range_str}'")
    rows = get_values(sheet, spreadsheet_id, range_str)

    
    tab = f"Deliveries-{stand_name}"
    range_str = f"'{tab}'!A2:D200"
    rows = get_values(sheet, spreadsheet_id, range_str)

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
    range_str = f"{tab}!A2:C200"
    rows = get_values(sheet, spreadsheet_id, range_str)
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
    range_str = f"{tab}!A2:C1000"
    sheet.values().clear(
        spreadsheetId=spreadsheet_id,
        range=range_str
    ).execute()

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


def write_full_week(sheet, service, spreadsheet_id, stand_name, rows):
    """Append one week's inventory data as 9 new columns to the stand's sheet.

    Sheet layout
    ------------
    * Column A  – static item list (category headers + sorted item names).
    * Row 1     – week-label row: "Week of MM-DD-YYYY" in the first column of
                  each week's block; Column A always contains "ITEM".
    * Row 2     – sub-header row: Starting | Deliveries | Sales | Spoilage |
                  Expected | Actual | Variance | Scoops Used | Tubs Used
                  repeated for every week block; Column A is blank.
    * Row 3+    – data rows: one row per category header or item.

    On the first run the stand sheet is created automatically.  Subsequent
    runs detect the last week via the week labels in row 1 and append 9 more
    columns to the right — no new sheet tabs are created.
    """

    # ============================
    # CATEGORY ORDER
    # Try to read from "Master Items-{stand}" tab first; fall back to hardcoded
    # lists.
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

    # ============================
    # ENSURE STAND SHEET EXISTS (creates it with items in col A if absent)
    # ============================
    ensure_stand_sheet_exists(service, spreadsheet_id, stand_name, sheet, CATEGORY_ORDER)
    sheet_id = get_sheet_id(service, spreadsheet_id, stand_name)

    # ============================
    # ENSURE ALL ITEMS APPEAR, EVEN WITH 0 SALES
    # ============================
    for category_name, item_list in CATEGORY_ORDER:
        for item in item_list:
            if item not in rows:
                rows[item] = {
                    "starting": 0, "deliveries": 0, "sales": 0,
                    "spoilage": 0, "scoops_used": 0, "tubs_used": 0,
                    "expected": 0, "actual": "",
                }

    # ============================
    # ICE CREAM SCOOP + TUBS LOGIC
    # ============================
    flavor_totals = group_scoops_by_flavor(rows)
    tubs_used_map = tubs_used_from_scoops(flavor_totals)

    for flavor, scoops in flavor_totals.items():
        for tofts_flavor in TOFTS_ICE_CREAM:
            if normalize_flavor(tofts_flavor) == flavor:
                rows[tofts_flavor]["scoops_used"] = scoops
                rows[tofts_flavor]["tubs_used"] = tubs_used_map.get(flavor, 0)

    # ============================
    # FIND WHERE THE NEXT WEEK'S COLUMNS START
    # ============================
    last_week_start = find_last_week_start_col(sheet, spreadsheet_id, stand_name)
    if last_week_start == 0:
        next_week_start = 1             # No weeks yet → start at column B
    else:
        next_week_start = last_week_start + COLS_PER_WEEK

    # ============================
    # READ LAST WEEK'S ACTUALS → THIS WEEK'S STARTING INVENTORY
    # ============================
    last_week_actuals = read_last_week_actuals_from_stand_sheet(
        sheet, spreadsheet_id, stand_name
    )
    for item in rows:
        rows[item]["starting"] = last_week_actuals.get(item, 0)

    # ============================
    # SPOILAGE INTEGRATION
    # ============================
    spoilage_totals = read_spoilage(sheet, spreadsheet_id, stand_name)
    for item in rows:
        rows[item]["spoilage"] = spoilage_totals.get(item, 0)
    clear_spoilage_sheet(sheet, spreadsheet_id, stand_name)

    # ============================
    # DELIVERIES INTEGRATION (accumulated)
    # ============================
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

    # ============================
    # EXPECTED INVENTORY CALCULATION
    # ============================
    expected_totals = calculate_expected_inventory(
        {item: rows[item].get("starting", 0) for item in rows},
        {item: rows[item].get("deliveries", 0) for item in rows},
        {item: rows[item].get("sales", 0) for item in rows},
        {item: rows[item].get("spoilage", 0) for item in rows},
    )
    for item in rows:
        rows[item]["expected"] = expected_totals.get(item, 0)

    # ============================
    # BUILD ITEM → ROW-NUMBER LOOKUP (reads column A of the stand sheet)
    # ============================
    item_row_map = read_item_row_map(sheet, spreadsheet_id, stand_name)

    # ============================
    # WRITE WEEK LABEL (row 1) AND COLUMN SUB-HEADERS (row 2)
    # ============================
    week_label = datetime.today().strftime("Week of %m-%d-%Y")
    week_start_letter = col_letter(next_week_start)
    week_end_letter   = col_letter(next_week_start + COLS_PER_WEEK - 1)

    # Row 1: week label in first column of this week's block only.
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"'{stand_name}'!{week_start_letter}{HEADER_ROW}",
        valueInputOption="RAW",
        body={"values": [[week_label]]},
    ).execute()

    # Row 2: all nine sub-headers.
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"'{stand_name}'!{week_start_letter}{SUBHEADER_ROW}",
        valueInputOption="RAW",
        body={"values": [WEEK_COL_HEADERS]},
    ).execute()

    # ============================
    # WRITE ITEM DATA ROW BY ROW
    # ============================
    # Pre-compute column letters for this week block (same for every row).
    s_col  = col_letter(next_week_start + COL_STARTING)
    d_col  = col_letter(next_week_start + COL_DELIVERIES)
    sa_col = col_letter(next_week_start + COL_SALES)
    sp_col = col_letter(next_week_start + COL_SPOILAGE)
    ex_col = col_letter(next_week_start + COL_EXPECTED)
    ac_col = col_letter(next_week_start + COL_ACTUAL)
    va_col = col_letter(next_week_start + COL_VARIANCE)
    sc_col = col_letter(next_week_start + COL_SCOOPS)
    tu_col = col_letter(next_week_start + COL_TUBS)

    batch_data = []

    for category_name, item_list in CATEGORY_ORDER:
        for item in sorted(item_list):
            row_num = item_row_map.get(item)
            if not row_num:
                continue

            is_tofts = item in TOFTS_ICE_CREAM
            item_data = rows.get(item, {})

            # Spreadsheet formulas (use USER_ENTERED so Sheets evaluates them).
            expected_formula = (
                f"={s_col}{row_num}+{d_col}{row_num}"
                f"-{sa_col}{row_num}-{sp_col}{row_num}"
            )
            variance_formula = (
                f'=IF({ac_col}{row_num}="",'
                f'"",{ac_col}{row_num}-{ex_col}{row_num})'
            )

            row_values = [
                item_data.get("starting", 0),
                item_data.get("deliveries", 0),
                item_data.get("sales", 0),
                item_data.get("spoilage", 0),
                expected_formula,
                "",                                            # Actual (user fills in)
                variance_formula,
                item_data.get("scoops_used", 0) if is_tofts else "",
                item_data.get("tubs_used", 0)   if is_tofts else "",
            ]

            batch_data.append({
                "range": f"'{stand_name}'!{s_col}{row_num}:{tu_col}{row_num}",
                "values": [row_values],
            })

    if batch_data:
        service.spreadsheets().values().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"valueInputOption": "USER_ENTERED", "data": batch_data},
        ).execute()

    # ============================
    # FORMATTING FOR THIS WEEK'S COLUMNS
    # ============================
    fmt_requests = []

    week_start_idx = next_week_start          # 0-based
    week_end_idx   = next_week_start + COLS_PER_WEEK  # exclusive

    # Merge week label across all 9 columns in row 1.
    fmt_requests.append({
        "mergeCells": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 0, "endRowIndex": 1,
                "startColumnIndex": week_start_idx, "endColumnIndex": week_end_idx,
            },
            "mergeType": "MERGE_ALL",
        }
    })

    # Row 1 (week label): blue background, white bold centred text.
    fmt_requests.append({
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 0, "endRowIndex": 1,
                "startColumnIndex": week_start_idx, "endColumnIndex": week_end_idx,
            },
            "cell": {
                "userEnteredFormat": {
                    "backgroundColor": {"red": 0.267, "green": 0.447, "blue": 0.769},
                    "textFormat": {
                        "bold": True,
                        "foregroundColor": {"red": 1, "green": 1, "blue": 1},
                    },
                    "horizontalAlignment": "CENTER",
                }
            },
            "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)",
        }
    })

    # Row 2 (sub-headers): same blue style.
    fmt_requests.append({
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 1, "endRowIndex": 2,
                "startColumnIndex": week_start_idx, "endColumnIndex": week_end_idx,
            },
            "cell": {
                "userEnteredFormat": {
                    "backgroundColor": {"red": 0.267, "green": 0.447, "blue": 0.769},
                    "textFormat": {
                        "bold": True,
                        "foregroundColor": {"red": 1, "green": 1, "blue": 1},
                    },
                    "horizontalAlignment": "CENTER",
                }
            },
            "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)",
        }
    })

    # Category rows: light-blue background for this week's new columns.
    for category_name, item_list in CATEGORY_ORDER:
        cat_row = item_row_map.get(category_name)
        if cat_row:
            fmt_requests.append({
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": cat_row - 1, "endRowIndex": cat_row,
                        "startColumnIndex": week_start_idx, "endColumnIndex": week_end_idx,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": {"red": 0.647, "green": 0.761, "blue": 0.902},
                            "textFormat": {"bold": True},
                        }
                    },
                    "fields": "userEnteredFormat(backgroundColor,textFormat)",
                }
            })

    # Conditional formatting: green/red on Variance column.
    total_data_rows = DATA_START_ROW - 1
    for _, item_list in CATEGORY_ORDER:
        total_data_rows += 1 + len(item_list)

    variance_col_idx = next_week_start + COL_VARIANCE
    variance_range = [{
        "sheetId": sheet_id,
        "startRowIndex": DATA_START_ROW - 1,
        "endRowIndex": total_data_rows,
        "startColumnIndex": variance_col_idx,
        "endColumnIndex": variance_col_idx + 1,
    }]

    fmt_requests.append({
        "addConditionalFormatRule": {
            "rule": {
                "ranges": variance_range,
                "booleanRule": {
                    "condition": {
                        "type": "NUMBER_GREATER",
                        "values": [{"userEnteredValue": "0"}],
                    },
                    "format": {
                        "backgroundColor": {"red": 0.576, "green": 0.769, "blue": 0.490}
                    },
                }
            },
            "index": 0,
        }
    })
    fmt_requests.append({
        "addConditionalFormatRule": {
            "rule": {
                "ranges": variance_range,
                "booleanRule": {
                    "condition": {
                        "type": "NUMBER_LESS",
                        "values": [{"userEnteredValue": "0"}],
                    },
                    "format": {
                        "backgroundColor": {"red": 0.918, "green": 0.267, "blue": 0.208}
                    },
                }
            },
            "index": 1,
        }
    })

    # Set column widths for the new week's block.
    fmt_requests.append({
        "updateDimensionProperties": {
            "range": {
                "sheetId": sheet_id,
                "dimension": "COLUMNS",
                "startIndex": week_start_idx,
                "endIndex": week_end_idx,
            },
            "properties": {"pixelSize": 120},
            "fields": "pixelSize",
        }
    })

    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": fmt_requests},
    ).execute()

    print(f"✅ Week '{week_label}' written to '{stand_name}' "
          f"(columns {week_start_letter}–{week_end_letter}).")






def connect_to_sheets():
    creds = Credentials.from_service_account_file(
        r"C:\Users\willi\OneDrive\Desktop\inventory_Script\Credentials-personal.json",
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    service = build("sheets", "v4", credentials=creds)
    return service

