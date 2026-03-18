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

def create_weekly_sheet(service, spreadsheet_id):
    # 1. Generate the new tab name
    from datetime import datetime
    new_title = datetime.today().strftime("Week of %m-%d-%Y")

    # 2. Duplicate the TEMPLATE tab
    body = {
        "requests": [
            {
                "duplicateSheet": {
                    "sourceSheetId": get_sheet_id(service, spreadsheet_id, "TEST_FORMATTING"),
                    "insertSheetIndex": 0,
                    "newSheetName": new_title
                }
            }
        ]
    }

    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body=body
    ).execute()

    # 3. Return the new sheet ID
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

def read_deliveries(sheet, spreadsheet_id):
    """Read the Deliveries tab and return a dict of item -> quantity."""
    rows = get_values(sheet, spreadsheet_id, "Deliveries!A2:C200")
  # skip header row

    deliveries = {}

    for row in rows:
        if len(row) < 2:
            continue  # skip incomplete rows

        item = row[0].strip()
        packages = int(row[1])
        units_per_package = int(row[2]) 

        total_units = packages * units_per_package
        deliveries[item] = total_units

    return deliveries

def read_spoilage(sheet, spreadsheet_id):
    """Read the Spoilage tab and return item -> units spoiled."""
    rows = get_values(sheet, spreadsheet_id, "Spoilage!A2:B200")  # Item, Units Spoiled

    spoilage = {}

    for row in rows:
        if len(row) < 2:
            continue  # skip incomplete rows

        item = row[0].strip()
        units_spoiled = int(row[1])

        spoilage[item] = units_spoiled

    return spoilage

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

        # Only count ice cream scoops
        if "scoop" not in name_lower:
            continue

        # Extract sales from the row dict
        quantity = data.get("sales", 0)
        if not isinstance(quantity, (int, float)):
            continue

        flavor = normalize_flavor(item_name)

        if flavor not in flavor_totals:
            flavor_totals[flavor] = 0

        flavor_totals[flavor] += quantity

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

    return ending

def find_previous_week_sheet_name(service, spreadsheet_id, current_sheet_name):
    """Return the sheet name of the most recent weekly sheet before the current one."""
    # Get spreadsheet metadata
    metadata = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    sheets = metadata.get("sheets", [])

    weekly_sheets = []

    for s in sheets:
        title = s["properties"]["title"]

        # Only consider sheets that start with "Week of"
        if not title.startswith("Week of"):
            continue

        # Extract date portion
        try:
            date_str = title.replace("Week of", "").strip()
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


def write_full_week(sheet, service, spreadsheet_id, sheet_name, rows):

    """
    Writes a fully formatted weekly inventory sheet with:
    - Category grouping
    - Header formatting
    - Borders
    - Auto-size
    - Conditional formatting
    - Frozen header row
    """

  # ============================
# CATEGORY LISTS (MATCH CSV)
# ============================

    

    # ============================
    # CATEGORY ORDER
    # ============================

    CATEGORY_ORDER = [
        ("ICE CREAM (Toft's Scoops)", TOFTS_ICE_CREAM),
        ("NOVELTY ICE CREAM", NOVELTY_ICE_CREAM),
        ("CANDY", CANDY),
        ("DRINKS", DRINKS),
        ("MEALS", MEALS),
        ("SNACKS", SNACKS),
       ("SNOW CONES / SYRUPS", SNOW_CONE_AND_FOUNTAIN_SYRUPS),  # no CSV items yet
        ("JANITORIAL / CONSUMABLES", JANITORIAL)
    ] 
     # ====================================================================
    # NEW: ENSURE ALL ITEMS FROM CATEGORY_ORDER APPEAR, EVEN WITH 0 SALES
    # ====================================================================
    for category_name, item_list in CATEGORY_ORDER:
        for item in item_list:
            if item not in rows:
                # Add item with zero defaults if it's missing from CSV
                rows[item] = {
                    "starting": 0,
                    "deliveries": 0,
                    "sales": 0,
                    "spoilage": 0,
                    "scoops_used": 0,
                    "tubs_used": 0,
                    "expected": 0,
                    "actual": "",
                    "variance": ""
                }
                 # ADD THIS: Also add normalized flavor key
                normalized = normalize_flavor(item)
                if normalized not in rows:
                    rows[normalized] = rows[item]


    values = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f"{sheet_name}!A1:K300"
    ).execute().get("values", [])

    row_lookup = build_ice_cream_row_lookup(sheet, spreadsheet_id, sheet_name)


    # ------------------------------------------------------------
    # ICE CREAM SCOOP + TUBS LOGIC (NEW)
    # ------------------------------------------------------------
    flavor_totals = group_scoops_by_flavor(rows)
    # DEBUG: See what flavors were found and their totals
    print("\n" + "="*50)
    print("FLAVOR TOTALS FROM SCOOPS:")
    print("="*50)
    for flavor, scoops in flavor_totals.items():
         print(f"  {flavor}: {scoops} scoops")
    print("="*50 + "\n")
    tubs_used = tubs_used_from_scoops(flavor_totals)

    for flavor, scoops in flavor_totals.items():
        if flavor in rows:
            rows[flavor]["scoops_used"] = scoops
            rows[flavor]["tubs_used"] = tubs_used.get(flavor, 0)

# ------------------------------------------------------------
# FIND PREVIOUS WEEK'S SHEET
# ------------------------------------------------------------
    previous_sheet_name = find_previous_week_sheet_name(
    service,
    spreadsheet_id,
    sheet_name
)
    print("DEBUG previous sheet:", previous_sheet_name)

# ------------------------------------------------------------
# READ PREVIOUS WEEK'S ENDING INVENTORY
# ------------------------------------------------------------
    if previous_sheet_name:
        last_week_ending = read_last_week_inventory(
        service,
        spreadsheet_id,
        previous_sheet_name
    )
    else:
        last_week_ending = {}
    print("DEBUG last week ending:", last_week_ending)
# ------------------------------------------------------------
# MERGE INTO STARTING INVENTORY
# ------------------------------------------------------------
    for item in rows:
        rows[item]["starting"] = last_week_ending.get(item, 0)

    #--------------------
# SPOILAGE INTEGRATION
# ------------------------------------------------------------
    spoilage_totals = read_spoilage(sheet, spreadsheet_id)

    for item in rows:
        rows[item]["spoilage"] = spoilage_totals.get(item, 0)

    
# DELIVERIES INTEGRATION  ← ADD THIS BLOCK
# ------------------------------------------------------------
    delivery_totals = read_deliveries(sheet, spreadsheet_id)

    for item in rows:
        rows[item]["deliveries"] = delivery_totals.get(item, 0)
    
# ------------------------------------------------------------
# EXPECTED INVENTORY CALCULATION
# ------------------------------------------------------------
    expected_totals = calculate_expected_inventory(
    {item: rows[item].get("starting", 0) for item in rows},
    {item: rows[item].get("deliveries", 0) for item in rows},
    {item: rows[item].get("sales", 0) for item in rows},
    {item: rows[item].get("spoilage", 0) for item in rows},
)
    print("Items in rows dict:", list(rows.keys()))
    print("Expected items from CATEGORY_ORDER:", 
          
      [item for cat, items in CATEGORY_ORDER for item in items])
    for item in rows:
        rows[item]["expected"] = expected_totals.get(item, 0)

    output_rows = []
    print("DEBUG CATEGORY_ORDER:", CATEGORY_ORDER)

    # Header row
    header = [
        "CATEGORY", "ITEM", "STARTING", "DELIVERIES",
        "SALES", "SCOOPS USED", "TUBS USED", "SPOILAGE", "EXPECTED", "ACTUAL", "VARIANCE"
    ]
    output_rows.append(header)
    print("Loaded items:", list(rows.keys()))

    # Build grouped rows
    for category_name, item_list in CATEGORY_ORDER:
        output_rows.append([category_name] + [""] * 10)


        for item in sorted(item_list):
            if item in rows:
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
            rows[item].get("variance", "")
        ])
            else:
        # For manual items like janitorial, only fill ITEM and ACTUAL
                output_rows.append(
               ["", item, "", "", "", "", "", "", "", "", ""]

            )

    # ------------------------------------------------------------
    # 3. WRITE VALUES TO SHEET
    # ------------------------------------------------------------
    # Ensure all rows have the same number of columns
    expected_cols = len(header)
    for i, row in enumerate(output_rows):
        if len(row) < expected_cols:
            output_rows[i] = row + [""] * (expected_cols - len(row))
        elif len(row) > expected_cols:
            output_rows[i] = row[:expected_cols]

    body = {"values": output_rows}
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"{sheet_name}!A1:K",
        valueInputOption="USER_ENTERED",
        body=body
    ).execute()

    # ------------------------------------------------------------
    # 4. FORMATTING REQUESTS
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

    # Header formatting (FINAL, CORRECT BLOCK)
    # Set explicit column widths for header clarity

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
    
    # ------------------------------------------------------------
# HEADER FORMATTING (bold, background, alignment)
# ------------------------------------------------------------
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
                "backgroundColor": {"red": 0.9, "green": 0.9, "blue": 0.9},
                "textFormat": {"bold": True},
                "horizontalAlignment": "CENTER"
             }
            },
            "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)"
        }
    })

    # Color category rows  ← NO INDENT HERE
    category_names = [
        "ICE CREAM (Toft's Scoops)",
        "NOVELTY ICE CREAM",
        "CANDY",
        "DRINKS",
        "MEALS",
        "SNACKS",
        "SNOW CONES / SYRUPS",
        "JANITORIAL / CONSUMABLES",
    ]
   

    print("Category rows detected:")

    for i, row in enumerate(output_rows):
       if isinstance(row, list) and len(row) >= 2 and row[0] in category_names and row[1] == "":
            print(f"Row {i}: {row[0]}")
            requests.append({
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": i,
                        "endRowIndex": i + 1,
                        "startColumnIndex":0,
                        "endColumnIndex": 11
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": {"red": 1, "green": 1, "blue": 0},
                            "textFormat": {"bold": True}
                        }
                    },
                    "fields": "userEnteredFormat(backgroundColor,textFormat)"
                }
            })

     # ------------------------------------------------------------
    # APPLY FORMATTING
    # ------------------------------------------------------------
    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": requests}
    ).execute()

    # Calculate variance (only if ACTUAL is filled)
    calculate_variance(service.spreadsheets().values(), row_lookup)


   

   




def connect_to_sheets():
    creds = Credentials.from_service_account_file(
        r"C:\Users\willi\OneDrive\Desktop\inventory_Script\Credentials-personal.json",
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    service = build("sheets", "v4", credentials=creds)
    return service

