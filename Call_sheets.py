import csv
import logging
from unittest import result
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build # type: ignore
from collections import defaultdict
from datetime import datetime, timedelta
import re
import unicodedata
import requests
from data_validation import AuditLogger, DataValidator, ItemMatcher, CategoryAwareItemMatcher
from item_name_utils import normalize_item_name


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
# Layout: Starting | Deliveries | Sales | Spoilage | Expected |
#         Individuals | Cases/Packs | Qty Per Case | Actual | Variance |
#         Scoops Used | Tubs Used
COLS_PER_WEEK = 12

# Number of scoops in one ice cream tub.  Used to convert "Tubs" deliveries
# to scoops when the Deliveries tab includes a TYPE column.
SCOOPS_PER_TUB = 60
PORK_SCOOPS_PER_BAG = 6
CHILI_SCOOPS_PER_CAN = 30
POPCORN_PACKETS_PER_BOX = 36
GRANOLA_BARS_PER_BOX = 36

# Nacho cheese conversion constants.
# Delivered in 140oz bags; each nacho serving uses 3oz.
NACHO_CHEESE_OZ_PER_BAG = 140
NACHO_CHEESE_OZ_PER_SERVING = 3

# Slushie conversion constants.
# Inventory is tracked by bag; each bag has 10 servings at 16oz each.
SLUSHIE_SERVINGS_PER_BAG = 10
SLUSHIE_BAGS_PER_CONTAINER = 3
SLUSHIE_OZ_PER_SERVING = 16
SLUSHIE_OZ_PER_BAG = SLUSHIE_SERVINGS_PER_BAG * SLUSHIE_OZ_PER_SERVING  # = 160oz
SLUSHIE_SERVINGS_PER_CONTAINER = SLUSHIE_SERVINGS_PER_BAG * SLUSHIE_BAGS_PER_CONTAINER  # = 30
SLUSHIE_OZ_PER_CONTAINER = SLUSHIE_SERVINGS_PER_CONTAINER * SLUSHIE_OZ_PER_SERVING  # = 480oz

# Chicken salad conversion constants.
# Delivered in 48oz tubs; each sandwich uses a 4oz scoop (12 scoops per tub).
CHICKEN_SALAD_OZ_PER_TUB = 48
CHICKEN_SALAD_OZ_PER_SCOOP = 4
CHICKEN_SALAD_SCOOPS_PER_TUB = CHICKEN_SALAD_OZ_PER_TUB // CHICKEN_SALAD_OZ_PER_SCOOP  # = 12

# Ham conversion constants.
# Delivered in ~32oz packages with approximately 32 slices per package.
HAM_SLICES_PER_PACKAGE = 32

# Cheese conversion constants.
# Delivered in packages of 160 slices.
CHEESE_SLICES_PER_PACKAGE = 160

# Fountain syrup conversion constants.
# 1 "package" on Deliveries-{stand} is converted to ounces automatically:
#   PTAC uses 640oz bags; all other known stands in this map use 320oz bags.
SYRUP_BAG_SIZES = {
    "PTAC": 640,
    "REED ROAD": 320,
    "TREMONT": 320,
    "DEVON": 320,
    "NWSC": 320,
    "HILLIARD2 (EAST)": 320,
    "HILLIARD1 (WEST)": 320,
    "BEXLEY": 320,
}

# Industry-standard 1:5 syrup:water ratio for a 16oz fountain drink.
# Kept as a shared constant so downstream usage/depletion math can use the
# same value everywhere (instead of hard-coded literals).
SYRUP_PER_16OZ_DRINK = 2.67

# Sub-header labels written in row 2 for every week block.
WEEK_COL_HEADERS = [
    "Starting", "Deliveries", "Sales", "Spoilage",
    "Expected", "Individuals", "Cases/Packs", "Qty Per Case",
    "Actual", "Variance", "Scoops Used", "Tubs Used",
]

# 0-based offsets within a week's column block.
COL_STARTING     = 0
COL_DELIVERIES   = 1
COL_SALES        = 2
COL_SPOILAGE     = 3
COL_EXPECTED     = 4
# IN PERSON COUNT helper columns (employees fill these in during manual counts)
COL_INDIVIDUALS  = 5
COL_CASES        = 6
COL_QTY_PER_CASE = 7
# Actual is now a formula: =Individuals + Cases/Packs * Qty Per Case
COL_ACTUAL       = 8
COL_VARIANCE     = 9
COL_SCOOPS       = 10
COL_TUBS         = 11

# Label written in row 1 over the three in-person count helper columns.
IN_PERSON_COUNT_LABEL = "IN PERSON COUNT"

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
        # Only treat cells that start with "Week of" as week-label columns.
        # This prevents the new "IN PERSON COUNT" label (written into the same
        # row for the helper columns) from being mistaken as a week start.
        if row[i] and str(row[i]).startswith("Week of"):
            last_week_start = i
    return last_week_start


def read_item_row_map(sheet, spreadsheet_id, sheet_name):
    """Read column A of a stand sheet and return {normalized_item_name: row_number}.

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
        if not cell:
            continue
        normalized_name = normalize_item_name(cell[0])
        if not normalized_name:
            continue
        if normalized_name in item_row_map:
            logging.getLogger(__name__).warning(
                "Duplicate item variant in Column A for sheet %s: %r (row %d conflicts with row %d); using earliest row number.",
                sheet_name,
                normalized_name,
                row_num,
                item_row_map[normalized_name],
            )
            item_row_map[normalized_name] = min(item_row_map[normalized_name], row_num)
        else:
            item_row_map[normalized_name] = row_num
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

    # Cotton Candy Ice Cream (distinct from Cotton Candy candy)
    "Cotton Candy Ice Cream": 1,
    "Cotton Candy Ice Cream Double Scoop": 2,
    "Cotton Candy Ice Cream Triple Scoop": 3,

    # Cookie Monster
    "Cookie Monster": 1,
    "Cookie Monster Double Scoop": 2,
    "Cookie Monster Triple Scoop": 3,

    # Brownie Bandit
    "Brownie Bandit": 1,
    "Brownie Bandit Double Scoop": 2,
    "Brownie Bandit Triple Scoop": 3,

    # Birthday Cake
    "Birthday Cake": 1,
    "Birthday Cake Double Scoop": 2,
    "Birthday Cake Triple Scoop": 3,

    # Mint Chip
    "Mint Chip": 1,
    "Mint Chip Double Scoop": 2,
    "Mint Chip Triple Scoop": 3,

    # Rainbow Sherbet
    "Rainbow Sherbet": 1,
    "Rainbow Sherbet Double Scoop": 2,
    "Rainbow Sherbet Triple Scoop": 3,
    # Backward-compatible CSV spelling
    "Rainbow Sherbert": 1,
    "Rainbow Sherbert Double Scoop": 2,
    "Rainbow Sherbert Triple Scoop": 3,

    # PB S'Mores
    "PB S'Mores": 1,
    "PB S'Mores Double Scoop": 2,
    "PB S'Mores Triple Scoop": 3,

    # Blueberry Waffle Cone
    "Blueberry Waffle Cone": 1,
    "Blueberry Waffle Cone Double Scoop": 2,
    "Blueberry Waffle Cone Triple Scoop": 3,

    # Airheads (non-ice cream)
    "Airheads 2 for $1": 2,
    # Cuties — sold 2 for $1; each transaction counts as 2 units
    "Cuties (2/$1.00)": 2,
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

def extract_week_dates_from_label(week_label):
    """Parse a 'Week of MM-DD-YYYY' label into a (start_date, end_date) tuple.

    The date in the label is treated as the last day (end) of the week.
    The start date is computed as end_date minus 6 days so that exactly 7
    days are covered (start inclusive, end inclusive).

    Returns (start_date, end_date) as datetime.date objects, or (None, None)
    if the label cannot be parsed.
    """
    match = re.search(r"Week of\s+(\d{1,2})-(\d{1,2})-(\d{4})", week_label, re.IGNORECASE)
    if not match:
        return None, None
    try:
        end_date = datetime(int(match.group(3)), int(match.group(1)), int(match.group(2))).date()
        start_date = end_date - timedelta(days=6)
        return start_date, end_date
    except (ValueError, OverflowError):
        return None, None


def _parse_delivery_date(date_str):
    """Parse a delivery date string into a datetime.date, supporting multiple formats.

    Supports M-D-YYYY, MM-DD-YYYY, M/D/YYYY, MM/DD/YYYY, and YYYY-MM-DD.
    Returns a datetime.date on success, or None if the string cannot be parsed.
    """
    for fmt in ("%m-%d-%Y", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str.strip(), fmt).date()
        except ValueError:
            pass
    # Fallback: try splitting on common separators and constructing the date
    # (handles single-digit months/days: "4-1-2025", "4/1/2025", etc.)
    for sep in ("-", "/"):
        parts = date_str.strip().split(sep)
        if len(parts) == 3:
            try:
                month, day, year = int(parts[0]), int(parts[1]), int(parts[2])
                return datetime(year, month, day).date()
            except (ValueError, OverflowError):
                pass
    return None


def read_deliveries(sheet, spreadsheet_id, stand_name, week_start_date=None, week_end_date=None):
    """Read the Deliveries-{stand} tab and accumulate deliveries per item.

    Tab format (row 1 = header, rows 2+ = data):
      A: DATE              (optional, for record-keeping)
      B: ITEM NAME
      C: PACKAGES
      D: UNITS_PER_PACKAGE (optional, defaults to 1)

    Returns a dict: {item: qty}

    For Toft's ice cream items (auto-detected from TOFTS_ICE_CREAM):
      qty = packages × SCOOPS_PER_TUB  (already converted to scoops)

    For fountain drink items:
      qty = packages × stand-specific bag size in ounces
      (SYRUP_BAG_SIZES, defaults to 320oz if stand is not in the map)

    For all other items:
      qty = packages × units_per  (already in units)

    Column positions are resolved from the header row so the function is
    resilient to column re-ordering or renamed headers.

    When week_start_date and week_end_date are provided (as datetime.date
    objects), only rows whose Column-A date falls within that inclusive range
    are counted.  Rows with an unparseable date are skipped with a warning.
    If neither date is supplied the function reads all rows (backward-
    compatible behaviour).

    Quantities are ACCUMULATED so multiple deliveries in one week are summed.
    Duplicate (date, item) entries are logged as warnings.
    """
    tab = f"Deliveries-{stand_name}"

    # --- Resolve column positions from header row ---
    header_rows = get_values(sheet, spreadsheet_id, f"'{tab}'!A1:E1")
    headers = [h.strip().lower() for h in (header_rows[0] if header_rows else [])]

    def _col_idx(candidates, default):
        for i, h in enumerate(headers):
            if h in candidates:
                return i
        return default

    item_idx  = _col_idx({"item", "item name"}, 1)
    qty_idx   = _col_idx({"packages", "quantity", "qty", "packages / quantity", "packages/quantity"}, 2)
    units_idx = _col_idx({"units per package", "units per", "units_per_package", "units/pkg", "units/package"}, 3)

    # --- Read data rows ---
    range_str = f"'{tab}'!A2:E200"
    raw_rows = get_values(sheet, spreadsheet_id, range_str)

    # --- Duplicate detection ---
    _validator = DataValidator()
    _validator.detect_duplicate_deliveries(raw_rows, item_col=item_idx, date_col=0)

    filter_by_date = week_start_date is not None and week_end_date is not None
    if filter_by_date:
        print(f"  [Deliveries] Filtering to {week_start_date} – {week_end_date}")

    deliveries = {}

    for row in raw_rows:
        if len(row) <= item_idx:
            continue  # row too short to contain the item column

        # --- Date filtering ---
        if filter_by_date:
            date_str = row[0].strip() if row and row[0] else ""
            if not date_str:
                # No date in column A — skip when filtering is active
                continue
            delivery_date = _parse_delivery_date(date_str)
            if delivery_date is None:
                print(f"  [Deliveries] WARNING: unparseable date '{date_str}' — row skipped")
                continue
            if not (week_start_date <= delivery_date <= week_end_date):
                continue  # outside the current week's range

        item = row[item_idx].strip() if row[item_idx] else ""
        if not item:
            continue

        try:
            packages = int(row[qty_idx].strip()) if len(row) > qty_idx and row[qty_idx].strip() else 0
        except (ValueError, IndexError):
            packages = 0

        try:
            units_per = int(row[units_idx].strip()) if len(row) > units_idx and row[units_idx].strip() else 1
        except (ValueError, IndexError):
            units_per = 1

        # Auto-detect Toft's ice cream: convert tubs → scoops automatically.
        # All other items: multiply packages × units_per to get total units.
        is_tofts_ice_cream = any(
            item.lower() == tofts_item.lower()
            for tofts_item in TOFTS_ICE_CREAM
        )

        is_fountain_drink = any(
            item.lower() == fountain_item.lower()
            for fountain_item in FOUNTAIN_DRINKS
        )
        is_popcorn = item.lower() == "popcorn"
        is_granola_bar = item.lower() == "granola bar"
        is_nacho_cheese = item.lower() == "nacho cheese"
        is_chicken_salad = item.lower() == "chicken salad"

        if is_tofts_ice_cream:
            qty = packages * SCOOPS_PER_TUB
            print(
                f"  [Deliveries] '{item}': {packages} tub(s) → "
                f"{qty} scoops"
            )
        elif is_fountain_drink:
            bag_size_oz = SYRUP_BAG_SIZES.get(stand_name, 320)
            qty = packages * bag_size_oz
            print(
                f"  [Deliveries] '{item}': {packages} bag(s) at "
                f"{stand_name} → {qty} oz syrup"
            )
        elif is_popcorn:
            qty = packages * POPCORN_PACKETS_PER_BOX
            print(f"  [Deliveries] '{item}': {packages} box(es) → {qty} packets")
        elif is_granola_bar:
            qty = packages * GRANOLA_BARS_PER_BOX
            print(f"  [Deliveries] '{item}': {packages} box(es) → {qty} bars")
        elif is_nacho_cheese:
            qty = packages * NACHO_CHEESE_OZ_PER_BAG
            print(f"  [Deliveries] '{item}': {packages} bag(s) → {qty} oz nacho cheese")
        elif is_chicken_salad:
            qty = packages * CHICKEN_SALAD_SCOOPS_PER_TUB
            print(f"  [Deliveries] '{item}': {packages} tub(s) → {qty} scoops chicken salad")
        else:
            qty = packages * units_per

        # ACCUMULATE so mid-week deliveries are summed, not overwritten
        deliveries[item] = deliveries.get(item, 0) + qty

    return deliveries

def read_spoilage(sheet, spreadsheet_id, stand_name):
    """Read the Spoilage-{stand} tab and return accumulated spoilage per item.

    Tab format (row 1 = header, rows 2+ = data):
      A: DATE         (optional, for record-keeping)
      B: ITEM
      C: UNITS SPOILED

    Column positions are resolved from the header row so the function is
    resilient to column re-ordering or renamed headers.  Positional defaults
    (B=item, C=units_spoiled) are used as fallback when no header row exists.

    Quantities are ACCUMULATED across all rows for the week.
    """
    tab = f"Spoilage-{stand_name}"

    # --- Resolve column positions from header row ---
    header_rows = get_values(sheet, spreadsheet_id, f"'{tab}'!A1:C1")
    headers = [h.strip().lower() for h in (header_rows[0] if header_rows else [])]

    def _col_idx(candidates, default):
        for i, h in enumerate(headers):
            if h in candidates:
                return i
        return default

    item_idx   = _col_idx({"item", "item name"}, 1)
    units_idx  = _col_idx({"units spoiled", "units", "quantity", "qty", "spoilage"}, 2)

    # --- Read data rows ---
    range_str = f"'{tab}'!A2:C200"
    raw_rows = get_values(sheet, spreadsheet_id, range_str)
    spoilage = {}

    for row in raw_rows:
        if len(row) <= item_idx:
            continue  # row too short to contain the item column

        item = row[item_idx].strip() if row[item_idx] else ""
        if not item:
            continue

        try:
            units_spoiled = int(row[units_idx].strip()) if len(row) > units_idx and row[units_idx].strip() else 0
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


def _canonical_item_name(item_name):
    """Normalize item names for matching/filtering across spacing variants."""
    if not item_name:
        return ""
    normalized = " ".join(item_name.strip().split())
    return re.sub(r"\s*-\s*", " - ", normalized)


def _row_for_item_name(item_row_map, item_name):
    return item_row_map.get(normalize_item_name(item_name))


def _build_category_order_for_stand(sheet, spreadsheet_id, stand_name):
    """Build stand-aware category order from master tab with safe fallbacks."""
    master_items = read_master_items(sheet, spreadsheet_id, stand_name)
    if not master_items:
        return get_default_category_order_for_stand(stand_name)

    category_map = {}
    for category, item in master_items:
        canonical_item = _canonical_item_name(item)
        if not canonical_item:
            continue
        if not _is_item_available_at_stand(canonical_item, stand_name, category):
            continue
        category_map.setdefault(category, [])
        if canonical_item not in category_map[category]:
            category_map[category].append(canonical_item)

    default_order = get_default_category_order_for_stand(stand_name)
    for category, default_items in default_order:
        category_map.setdefault(category, [])
        existing_items = {_canonical_item_name(x) for x in category_map[category]}
        for item in default_items:
            canonical_item = _canonical_item_name(item)
            if canonical_item not in existing_items:
                category_map[category].append(canonical_item)
                existing_items.add(canonical_item)

    return [(category, items) for category, items in category_map.items() if items]


# ---------------------------------------------------------------------------
# Master Items lookup (global "Master Items" tab, not per-stand)
# ---------------------------------------------------------------------------

def load_master_items(sheet, spreadsheet_id):
    """Read the global 'Master Items' tab and return a lookup dictionary.

    Tab format (row 1 = header, rows 2+ = data):
      A: CATEGORY
      B: ITEM NAME
      C: INGREDIENT / COMPONENT MAP  (human-readable text, e.g. "1 Bun, 1 Hot Dog")

    Returns a dict keyed by exact item name:
      { item_name: {"category": str, "ingredients": str} }

    Returns an empty dict if the tab is absent or empty.
    """
    try:
        rows = get_values(sheet, spreadsheet_id, "'Master Items'!A2:C500")
    except Exception:
        return {}

    master = {}
    for row in rows:
        if len(row) < 2:
            continue
        category      = row[0].strip() if row[0] else ""
        item_name     = row[1].strip() if row[1] else ""
        ingredient_txt = row[2].strip() if len(row) > 2 and row[2] else ""
        if item_name:
            master[item_name] = {"category": category, "ingredients": ingredient_txt}
    return master


def map_item_to_ingredients(item_name, quantity, ingredient_map=None):
    """Convert a sold item + quantity to a dict of ingredient components.

    Uses INGREDIENT_MAP by default.  Returns {ingredient_name: total_qty}.
    Items not present in the ingredient_map are returned as-is
    ({item_name: quantity}).
    """
    if ingredient_map is None:
        ingredient_map = INGREDIENT_MAP

    if item_name not in ingredient_map:
        return {item_name: quantity}

    result = {}
    for ing_name, qty_per_sale in ingredient_map[item_name]:
        result[ing_name] = result.get(ing_name, 0) + quantity * qty_per_sale
    return result


def calculate_ingredients_per_stand(rows, ingredient_map=None):
    """Expand CSV sales into ingredient-level usage for a single stand.

    For each item that has an entry in INGREDIENT_MAP, the additional
    ingredient items it consumes are computed from the item's sales count
    and added (accumulated) into *rows*.

    The original item's own row is left untouched – it continues to show
    the raw number of that item sold.  Only the derived ingredient rows
    (e.g. "Bun", "Chili (1oz scoop)") are created/updated here.

    This function modifies *rows* in-place and also returns it.
    """
    if ingredient_map is None:
        ingredient_map = INGREDIENT_MAP

    for sold_item, ingredient_list in ingredient_map.items():
        qty_sold = rows.get(sold_item, {}).get("sales", 0)
        if qty_sold <= 0:
            continue

        for ingredient_name, qty_per_sale in ingredient_list:
            if ingredient_name not in rows:
                rows[ingredient_name] = {
                    "starting": 0, "deliveries": 0, "sales": 0,
                    "spoilage": 0, "scoops_used": 0, "tubs_used": 0,
                    "expected": 0, "actual": "",
                }
            rows[ingredient_name]["sales"] += qty_sold * qty_per_sale

    if "Chili Sauce (cans)" in rows:
        rows["Chili Sauce (cans)"]["sales"] = round(rows["Chili Sauce (cans)"]["sales"] / CHILI_SCOOPS_PER_CAN, 2)
    if "Pulled Pork (bags)" in rows:
        rows["Pulled Pork (bags)"]["sales"] = round(rows["Pulled Pork (bags)"]["sales"] / PORK_SCOOPS_PER_BAG, 2)
    if "Nacho Cheese" in rows:
        oz_used = rows["Nacho Cheese"].get("sales", 0)
        if oz_used > 0:
            rows["Nacho Cheese"]["sales"] = round(oz_used / NACHO_CHEESE_OZ_PER_BAG, 2)
    if "Chicken Salad" in rows:
        scoops_used = rows["Chicken Salad"].get("sales", 0)
        if scoops_used > 0:
            rows["Chicken Salad"]["sales"] = round(scoops_used / CHICKEN_SALAD_SCOOPS_PER_TUB, 2)
    if "Ham" in rows:
        slices_used = rows["Ham"].get("sales", 0)
        if slices_used > 0:
            rows["Ham"]["sales"] = round(slices_used / HAM_SLICES_PER_PACKAGE, 2)
    if "Cheese" in rows:
        slices_used = rows["Cheese"].get("sales", 0)
        if slices_used > 0:
            rows["Cheese"]["sales"] = round(slices_used / CHEESE_SLICES_PER_PACKAGE, 2)

    return rows


def create_master_items_tab(service, spreadsheet_id):
    """Create and populate the global 'Master Items' tab if it does not exist.

    The tab is created with three columns:
      A: CATEGORY | B: ITEM NAME | C: INGREDIENT / COMPONENT MAP

    All items from DEFAULT_CATEGORY_ORDER are written in.  Items that appear
    in INGREDIENT_MAP have their ingredient text auto-generated.

    Returns the integer sheetId (existing or newly created).
    """
    tab_name = "Master Items"

    # Return early if the tab already exists.
    metadata = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    for s in metadata.get("sheets", []):
        if s["properties"]["title"] == tab_name:
            return s["properties"]["sheetId"]

    # Create the tab.
    response = service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": [{
            "addSheet": {
                "properties": {
                    "title": tab_name,
                    "gridProperties": {"rowCount": 500, "columnCount": 5},
                }
            }
        }]},
    ).execute()
    new_sheet_id = response["replies"][0]["addSheet"]["properties"]["sheetId"]

    # Build row data: header + one row per item.
    tab_rows = [["CATEGORY", "ITEM NAME", "INGREDIENT / COMPONENT MAP"]]

    for category_name, item_list in DEFAULT_CATEGORY_ORDER:
        for item in sorted(item_list):
            ingredient_text = ""
            if item in INGREDIENT_MAP:
                parts = [f"{qty} {ing}" for ing, qty in INGREDIENT_MAP[item]]
                ingredient_text = ", ".join(parts)
            tab_rows.append([category_name, item, ingredient_text])

    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"'{tab_name}'!A1",
        valueInputOption="RAW",
        body={"values": tab_rows},
    ).execute()

    # Bold the header row.
    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": [{
            "repeatCell": {
                "range": {
                    "sheetId": new_sheet_id,
                    "startRowIndex": 0, "endRowIndex": 1,
                    "startColumnIndex": 0, "endColumnIndex": 3,
                },
                "cell": {
                    "userEnteredFormat": {
                        "textFormat": {"bold": True},
                        "backgroundColor": {"red": 0.267, "green": 0.447, "blue": 0.769},
                    }
                },
                "fields": "userEnteredFormat(textFormat,backgroundColor)",
            }
        }]},
    ).execute()

    return new_sheet_id


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

    Some CSV item names (e.g. "Cotton Candy Double Scoop") don't normalize to
    the same string as their base flavor ("Cotton Candy Ice Cream").
    SCOOP_VARIANT_TO_BASE provides an explicit mapping for those cases so that
    all scoop variants accumulate into the correct base-flavor bucket.
    """
    flavor_totals = {}

    for item_name, data in rows.items():
        name_lower = item_name.lower()

        # Direct case-insensitive membership check against TOFTS_ICE_CREAM,
        # which now includes all scoop variants explicitly.  Using a direct name
        # check (rather than normalize-based) avoids false positives such as
        # "Cotton Candy" (candy item) matching "Cotton Candy Double Scoop" after
        # both normalize to "cotton candy".
        is_tofts_ice_cream = any(item_name.lower() == t.lower() for t in TOFTS_ICE_CREAM)

        if not is_tofts_ice_cream:
            continue

        # Extract sales from the row dict
        quantity = data.get("sales", 0)
        if not isinstance(quantity, (int, float)):
            continue

        # Resolve any variant whose CSV name doesn't auto-normalize to its base,
        # then use the canonical base-flavor name as the accumulation key so that
        # e.g. "Cotton Candy Double Scoop" rolls up into "cotton candy ice cream".
        canonical_name = SCOOP_VARIANT_TO_BASE.get(item_name, item_name)
        flavor = normalize_flavor(canonical_name)

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

# The 12 canonical Toft's base flavors — one entry per physical tub.
# This list is used for:
#   1. Sheet display — DEFAULT_CATEGORY_ORDER uses this list so the sheet shows
#      ONLY these 12 rows, not individual scoop-variant rows.
#   2. Scoop accumulation — write_full_week assigns scoops_used / tubs_used
#      only to rows whose normalize_flavor() matches a flavor in this list.
#   3. Negative-inventory consolidation — flag_negative_expected folds variant
#      expected values into their base-flavor entry before checking for negatives.
#
# "Cotton Candy Ice Cream" (not "Cotton Candy") is intentional: the CANDY
# category has a separate "Cotton Candy" item and sharing the key would cause
# row-map collisions in the sheet.
_TOFTS_BASE_FLAVORS = [
    "Brownie Bandit",
    "Birthday Cake",
    "Chocolate",
    "Cookie Dough",
    "Cookie Monster",
    "Cookies n' Cream",
    "Vanilla",
    # Kept distinct from candy row name to avoid duplicate row-key collisions.
    "Cotton Candy Ice Cream",
    "Mint Chip",
    "Rainbow Sherbet",
    "PB S'Mores",
    "Blueberry Waffle Cone",
]

# Comprehensive mapping of every CSV scoop-variant name → canonical base flavor.
#
# ⚠️  KEEP THIS MAPPING COMPLETE.
# When a new scoop variant appears in the POS CSV, add it here so that
# consolidate_variants_to_base() (called at the start of write_full_week)
# folds it into the correct base-flavor bucket.  Omitting a variant here
# causes its sales/deliveries/spoilage to be silently dropped.
#
# This dict serves two purposes:
#   1. group_scoops_by_flavor() – resolves variant name → base before counting
#      scoops (handles names that don't auto-normalize, e.g. "Cotton Candy
#      Double Scoop" → "cotton candy" ≠ "cotton candy ice cream").
#   2. consolidate_variants_to_base() – merges ALL numeric row data
#      (sales, deliveries, spoilage) from variant keys into base-flavor keys
#      so the sheet's Sales column is populated correctly.
SCOOP_VARIANT_TO_BASE: dict[str, str] = {
    # Brownie Bandit
    "Brownie Bandit":                     "Brownie Bandit",
    "Brownie Bandit Single Scoop":        "Brownie Bandit",
    "Brownie Bandit Double Scoop":        "Brownie Bandit",
    "Brownie Bandit Triple Scoop":        "Brownie Bandit",
    # Birthday Cake
    "Birthday Cake":                      "Birthday Cake",
    "Birthday Cake Single Scoop":         "Birthday Cake",
    "Birthday Cake Double Scoop":         "Birthday Cake",
    "Birthday Cake Triple Scoop":         "Birthday Cake",
    # Chocolate
    "Chocolate":                          "Chocolate",
    "Chocolate Single Scoop":             "Chocolate",
    "Chocolate Double Scoop":             "Chocolate",
    "Chocolate Triple Scoop":             "Chocolate",
    # Cookie Dough
    "Cookie Dough":                       "Cookie Dough",
    "Cookie Dough Single Scoop":          "Cookie Dough",
    "Cookie Dough Double Scoop":          "Cookie Dough",
    "Cookie Dough Triple Scoop":          "Cookie Dough",
    # Cookie Monster
    "Cookie Monster":                     "Cookie Monster",
    "Cookie Monster Single Scoop":        "Cookie Monster",
    "Cookie Monster Double Scoop":        "Cookie Monster",
    "Cookie Monster Triple Scoop":        "Cookie Monster",
    # Cookies n' Cream (include common CSV spelling variants)
    "Cookies n' Cream":                   "Cookies n' Cream",
    "Cookies n' Cream Single Scoop":      "Cookies n' Cream",
    "Cookies n' Cream Double Scoop":      "Cookies n' Cream",
    "Cookies n' Cream Triple Scoop":      "Cookies n' Cream",
    "Cookies N Cream":                    "Cookies n' Cream",
    "Cookies N Cream Single Scoop":       "Cookies n' Cream",
    "Cookies N Cream Double Scoop":       "Cookies n' Cream",
    "Cookies N Cream Triple Scoop":       "Cookies n' Cream",
    "Cookies & Cream":                    "Cookies n' Cream",
    "Cookies & Cream Single Scoop":       "Cookies n' Cream",
    "Cookies & Cream Double Scoop":       "Cookies n' Cream",
    "Cookies & Cream Triple Scoop":       "Cookies n' Cream",
    # Cotton Candy (base name differs: "Cotton Candy Ice Cream")
    "Cotton Candy Ice Cream":             "Cotton Candy Ice Cream",
    "Cotton Candy Single Scoop":          "Cotton Candy Ice Cream",
    "Cotton Candy Double Scoop":          "Cotton Candy Ice Cream",
    "Cotton Candy Triple Scoop":          "Cotton Candy Ice Cream",
    "Cotton Candy Ice Cream Single Scoop":"Cotton Candy Ice Cream",
    "Cotton Candy Ice Cream Double Scoop":"Cotton Candy Ice Cream",
    "Cotton Candy Ice Cream Triple Scoop":"Cotton Candy Ice Cream",
    # Mint Chip (variant names differ from base)
    "Mint Chip":                          "Mint Chip",
    "Mint Chip Single Scoop":             "Mint Chip",
    "Mint Chip Double":                   "Mint Chip",
    "Mint Chip Double Scoop":             "Mint Chip",
    "Mint Chip Triple Scoop":             "Mint Chip",
    # Rainbow Sherbet
    "Rainbow Sherbet":                    "Rainbow Sherbet",
    "Rainbow Sherbet Single Scoop":       "Rainbow Sherbet",
    "Rainbow Sherbet Double Scoop":       "Rainbow Sherbet",
    "Rainbow Sherbet Triple Scoop":       "Rainbow Sherbet",
    # Backward-compatible CSV spelling
    "Rainbow Sherbert":                   "Rainbow Sherbet",
    "Rainbow Sherbert Single Scoop":      "Rainbow Sherbet",
    "Rainbow Sherbert Double Scoop":      "Rainbow Sherbet",
    "Rainbow Sherbert Triple Scoop":      "Rainbow Sherbet",
    # PB S'Mores
    "PB S'Mores":                         "PB S'Mores",
    "PB S'Mores Single Scoop":            "PB S'Mores",
    "PB S'Mores Double Scoop":            "PB S'Mores",
    "PB S'Mores Triple Scoop":            "PB S'Mores",
    # Blueberry Waffle Cone
    "Blueberry Waffle Cone":              "Blueberry Waffle Cone",
    "Blueberry Waffle Cone Single Scoop": "Blueberry Waffle Cone",
    "Blueberry Waffle Cone Double Scoop": "Blueberry Waffle Cone",
    "Blueberry Waffle Cone Triple Scoop": "Blueberry Waffle Cone",
    # Vanilla
    "Vanilla":                            "Vanilla",
    "Vanilla Single Scoop":               "Vanilla",
    "Vanilla Double Scoop":               "Vanilla",
    "Vanilla Triple Scoop":               "Vanilla",
}


def consolidate_variants_to_base(
    rows: dict,
    variant_map: dict[str, str] | None = None,
) -> dict:
    """Merge ice cream scoop variant entries into their canonical base flavors.

    POS CSV exports list scoop variants as separate line items, e.g.:
        "Brownie Bandit Double Scoop"  (35 units)
        "Brownie Bandit Single Scoop"  (85 units)

    The sheet tracks only the canonical base flavor ("Brownie Bandit"), so
    variant keys must be folded into the base-flavor key *before* any sheet-
    writing logic runs — otherwise the Sales column stays empty for every
    base flavor that was only sold as Single/Double Scoop variants.

    This function performs SIMPLE consolidation — quantities are summed as-is
    with NO scoop multipliers applied:
        "Brownie Bandit Double Scoop": sales=35
        "Brownie Bandit Single Scoop": sales=85
        "Brownie Bandit" total:        35 + 85 = 120 items sold ✅

    Scoop multipliers (Double=2, Triple=3) belong ONLY in group_scoops_by_flavor(),
    which calculates scoops used for inventory tracking.

    ⚠️  ALWAYS call this on any ``rows`` dict that originates from CSV reading
    before passing it to write_full_week or any other sheet-writing function.
    Skipping this step causes the Sales column to show 0 for affected flavors.

    ⚠️  Only Toft's ice cream scoop variants (all entries in SCOOP_VARIANT_TO_BASE)
    go through this path.  CANDY, DRINKS, MEALS, SNACKS, NOVELTY ICE CREAM, and
    all other categories are never in variant_map and are never modified here.

    Args:
        rows:        Dict mapping item_name -> data_dict (mutated in-place).
                     Each data_dict may contain "sales", "deliveries",
                     "spoilage", "starting", and other numeric fields.
        variant_map: Mapping of variant_name -> base_name.  Defaults to
                     SCOOP_VARIANT_TO_BASE.  Override only in tests.

    Returns:
        The same ``rows`` dict (mutated in-place) for convenient chaining.
    """
    if variant_map is None:
        variant_map = SCOOP_VARIANT_TO_BASE

    for variant, base in variant_map.items():
        if variant not in rows:
            continue

        if variant == base:
            continue

        # Ensure the base-flavor key exists before merging.
        if base not in rows:
            rows[base] = {
                "starting": 0, "deliveries": 0, "sales": 0,
                "spoilage": 0, "scoops_used": 0, "tubs_used": 0,
                "expected": 0, "actual": "",
            }

        variant_data = rows.pop(variant)
        base_data = rows[base]

        # Simple accumulation: sum raw quantities with no multipliers.
        # Scoop multipliers are applied only in group_scoops_by_flavor()
        # for inventory (scoops used) calculations.
        for field in ("sales", "deliveries", "spoilage"):
            base_data[field] = base_data.get(field, 0) + variant_data.get(field, 0)

    return rows

# Full list: base flavors + all scoop variants found in the CSV.
# Used ONLY for CSV-item recognition (group_scoops_by_flavor, read_deliveries,
# is_tofts checks).  The sheet display uses _TOFTS_BASE_FLAVORS (the 12 bases)
# so that scoop-variant rows do NOT appear as separate lines on the sheet.
TOFTS_ICE_CREAM = [
    # Base flavors
    *_TOFTS_BASE_FLAVORS,
    # Variant aliases
    "Brownie Bandit Single Scoop",
    "Brownie Bandit Double Scoop",
    "Brownie Bandit Triple Scoop",
    "Birthday Cake Single Scoop",
    "Birthday Cake Double Scoop",
    "Birthday Cake Triple Scoop",
    "Chocolate Single Scoop",
    "Chocolate Double Scoop",
    "Chocolate Triple Scoop",
    "Cookie Dough Single Scoop",
    "Cookie Dough Double Scoop",
    "Cookie Dough Triple Scoop",
    "Cookie Monster Single Scoop",
    "Cookie Monster Double Scoop",
    "Cookie Monster Triple Scoop",
    "Cookies n' Cream Single Scoop",
    "Cookies n' Cream Double Scoop",
    "Cookies n' Cream Triple Scoop",
    "Cookies N Cream",
    "Cookies N Cream Single Scoop",
    "Cookies N Cream Double Scoop",
    "Cookies N Cream Triple Scoop",
    "Cookies & Cream",
    "Cookies & Cream Single Scoop",
    "Cookies & Cream Double Scoop",
    "Cookies & Cream Triple Scoop",
    "Cotton Candy Single Scoop",
    "Cotton Candy Double Scoop",
    "Cotton Candy Triple Scoop",
    "Cotton Candy Ice Cream Single Scoop",
    "Cotton Candy Ice Cream Double Scoop",
    "Cotton Candy Ice Cream Triple Scoop",
    "Mint Chip Single Scoop",
    "Mint Chip Double",
    "Mint Chip Double Scoop",
    "Mint Chip Triple Scoop",
    "Rainbow Sherbet",
    "Rainbow Sherbet Single Scoop",
    "Rainbow Sherbet Double Scoop",
    "Rainbow Sherbet Triple Scoop",
    # Backward-compatible CSV spelling
    "Rainbow Sherbert",
    "Rainbow Sherbert Single Scoop",
    "Rainbow Sherbert Double Scoop",
    "Rainbow Sherbert Triple Scoop",
    "PB S'Mores Single Scoop",
    "PB S'Mores Double Scoop",
    "PB S'Mores Triple Scoop",
    "Blueberry Waffle Cone Single Scoop",
    "Blueberry Waffle Cone Double Scoop",
    "Blueberry Waffle Cone Triple Scoop",
    "Vanilla Single Scoop",
    "Vanilla Double Scoop",
    "Vanilla Triple Scoop",
]


NOVELTIES = [
    "Bomb Pop",
    "Cannonball!!!",
    "Cookie Sandwich",
    "Nerd Bomb Pop",
    "Power Puff Girl",
    "Rainbow Sherbet Float",
    "Reese's Ice Cream",
    "Root Beer Float",
    "Snickers Ice Cream Bar",
    "Sonic The Hedgehog",
    "Spiderman Ice Cream",
    "Spongebob Ice Cream",
    "Strawberry Shortcake Bar",
    "Sundae Cone",
    "Twix Ice Cream Bar",
]

CANDY = [
    "Airheads 2 for $1",
    "Sour Patch Kids",
    "Ring Pop",
    "Slime Lickers",
    "Xtremes",
    "Starburst",
    "Nerd's Clusters",
    "Cotton Candy",
    "Cow Tail",
    "Milky Way",
    "Snickers",
    "M&M - Peanut",
    "M&M - Regular",
    "Swedish Fish",
    "Big League Chew",
    "Skittles",
]

FOUNTAIN_DRINKS = [
    "7up",
    "Big Red",
    "Diet RC",
    "Dr. Pepper",
    "Lemonade",
    "Root Beer",
    "RC Cola",
    "Coke",
    "Diet Coke",
    "Diet Pepsi",
    "Mt. Dew",
    "Pepsi",
    "Starry",
]

BOTTLED_DRINKS = [
    "Bottled Water",
    "Gatorade - Red",
    "Gatorade - Blue",
    "Gatorade - Yellow",
    "Bloom Pop - Strawberry Cream",
    "Bloom Pop - Raspberry Lemonade",
    "Bloom Pop - Watermelon Lime",
    "Poppi - Watermelon",
    "Poppi - Wild Berry",
    "Poppi - Raspberry Rose",
    "Fairlife",
    "Peach Tea",
    "Iced Coffee - Vanilla",
    "Iced Coffee - Mocha",
    "Iced Coffee - Caramel",
    "Diet Mt. Dew",
    "Mt. Dew",
    "Squirt",
    "Dr. Pepper",
    "Bubly - Green",
    "Bubly - Red",
    "Coke",
    "Zero Sugar RC",
    "RC",
    "Sprite",
    "7UP",
    "Sunkist - Orange",
    "AW Root Beer",
]



SLUSHIE_FLAVORS = [
    "Slushie - Mango",
    "Slushie - Blue Razz",
    "Slushie - Tiger's Blood",
    "Slushie - Green Apple",
    "Slushie - Peach",
]

FOOD = [
    "Pizza Slice",
    "Chicken Caesar Salad",
    "Hot Dog",
    "Chili Cheese Dog",
    "Chili Sauce (cans)",
    "Pulled Pork (bags)",
    "Uncrustable",
    "Nacho Chips",
    "Nacho Cheese",
    "Hamburger Buns",
    "Hot Dog Buns",
    "Soft Pretzel",
    "Ham",
    "Cheese",
]

SNACKS = [
    "Hummus",
    "Pita Chips",
    "Assorted Chips",
    "Goldfish",
    # Legacy "Crunchy Ra-Ra Yogurt" standalone row was replaced by flavor rows;
    # backward compatibility is maintained by keeping "Crunchy Ra-Ra Yogurt" in
    # Take_items.MODIFIER_ITEMS so take_items() skips that legacy base item.
    "Crunchy Ra-Ra - Mango",
    "Crunchy Ra-Ra - Sprinkles",
    "Crunchy Ra-Ra - Strawberry",
    "Rainbow Sprinkles",
    "Whipped Cream",
    "Sunflower Seeds - Original",
    "Sunflower Seeds - Dill Pickle",
    "Sunflower Seeds - Ranch",
    "String Cheese",
    "Frozen Grapes",
    "Pickles",
    "Go-Go Squeez",
    "Cuties (2/$1.00)",
    "Oranges",
    "Granola Bar",
    "Popcorn",
    "Peanuts Shelled",
    "Kars",
    "Fig Bars",
    "Doughnut Packs",
]

DISPOSABLES = [
    "Steam Pan Liners",
    "Nacho Trays",
    "Pretzel Sleeves",
    "Sandwich Trays",
    "Napkins",
    "Spoons",
    "Forks",
    "Knives",
    "Paper Cups",
    "Souvenir Cups",
    "Frazil Cups",
    "Ice Cream Cones",
    "Ketchup",
    "Mustard",
    "CO2 Tanks",
]






JANITORIAL = [
    "Dish Soap",
    "Floor Cleaner",
    "Sanitizer Tablets",
    "Gloves",
    "Hand Soap",
    "Paper Towels",
    "Trash Bags",
]

# ---------------------------------------------------------------------------
# Ingredient / component items
# These are physical inventory items derived from meal sales via INGREDIENT_MAP.
# They do not appear in the POS CSV; their "sales" values are computed by
# calculate_ingredients_per_stand().
# ---------------------------------------------------------------------------
INGREDIENTS = [
    "Hamburger Buns",
    "Hot Dog Buns",
    "Chicken Salad",
    "Pulled Pork (bags)",
    "Chili Sauce (cans)",
    "Ham",
    "Cheese",
    "Nacho Chips",
    "Nacho Cheese",
    "Hummus",
    "Pita Chips",
    "Frazil Cups",
    "Slushie Mix",
]

# ---------------------------------------------------------------------------
# Ingredient map
# Maps each sold menu item (CSV "Item Name") to a list of
# (ingredient_name, qty_per_sale) tuples.
#
# The sold item's own row is left unchanged; only the listed ingredients
# are added to (accumulated in) the rows dict.
#
# Ice cream scoop items are handled separately via group_scoops_by_flavor /
# UNIT_CONVERSION and do NOT need entries here.
# ---------------------------------------------------------------------------
INGREDIENT_MAP = {
    # Sandwiches and proteins
    "Chicken Salad Sandwich": [("Hamburger Buns", 1), ("Chicken Salad", 1)],
    "Pulled Pork Sandwich": [("Hamburger Buns", 1), ("Pulled Pork (bags)", 1)],
    "BBQ Pork Sandwich": [("Hamburger Buns", 1), ("Pulled Pork (bags)", 1)],
    "Ham and Cheese Sandwich": [("Hamburger Buns", 1), ("Ham", 1), ("Cheese", 1)],
    "Ham & Cheese Sandwich": [("Hamburger Buns", 1), ("Ham", 1), ("Cheese", 1)],

    # Hot dogs / chili use
    "Hot Dog": [("Hot Dog Buns", 1)],
    "Chili Cheese Dog": [("Hot Dog Buns", 1), ("Hot Dog", 1), ("Chili Sauce (cans)", 1)],

    # Nacho items (nacho cheese quantities are ounces per sale; 3oz each)
    "Nachos & Cheese": [("Nacho Chips", 1), ("Nacho Cheese", 3)],
    "Chili Cheese Nachos": [("Nacho Chips", 1), ("Nacho Cheese", 3), ("Chili Sauce (cans)", 3)],
    "Pulled Pork Nachos": [("Nacho Chips", 1), ("Nacho Cheese", 3), ("Pulled Pork (bags)", 1)],
    "Walking Taco": [("Assorted Chips", 1), ("Chili Sauce (cans)", 2)],

    # Snacks and frozen drinks
    "Hummus and Pita Chips": [("Hummus", 1), ("Pita Chips", 1)],
    "Slushie": [("Slushie Mix", 1), ("Frazil Cups", 1)],
}

PREMIUM_ICE_CREAM_ITEMS = {
    "Mint Chip",
    "Rainbow Sherbet",
    "PB S'Mores",
    "Blueberry Waffle Cone",
}

PREMIUM_ICE_CREAM_STANDS = {"PTAC", "NWSC", "TREMONT", "HILLIARD1 (WEST)"}
ALL_STANDS = {
    "BEXLEY",
    "DEVON",
    "HILLIARD2 (EAST)",
    "HILLIARD1 (WEST)",
    "NWSC",
    "PTAC",
    "REED ROAD",
    "TREMONT",
    "Bevelhymer Green",
    "Bevelhymer Yellow",
}
BEVELHYMER_STANDS = {"Bevelhymer Green", "Bevelhymer Yellow"}
NON_BEVELHYMER_STANDS = ALL_STANDS - BEVELHYMER_STANDS
UA_AND_NWSC_FOUNTAIN_STANDS = {"HILLIARD2 (EAST)", "HILLIARD1 (WEST)", "NWSC"}
UA_FOUNTAIN_STANDS = {"DEVON", "REED ROAD", "TREMONT"}
RAINBOW_SHERBET_FLOAT_STANDS = {"HILLIARD1 (WEST)", "TREMONT", "PTAC", "NWSC"}
BLOOM_POP_STANDS = {
    "BEXLEY",
    "DEVON",
    "HILLIARD2 (EAST)",
    "HILLIARD1 (WEST)",
    "NWSC",
    "REED ROAD",
    "TREMONT",
}
PTAC_ONLY = {"PTAC"}
HAM_SANDWICH_STANDS = NON_BEVELHYMER_STANDS
MMS_STANDS = {"HILLIARD2 (EAST)", "Bevelhymer Yellow", "Bevelhymer Green"}
CHOCOLATE_BAR_STANDS = BEVELHYMER_STANDS
SODA_CAN_STANDS = {"Bevelhymer Green", "Bevelhymer Yellow"}
SUNFLOWER_SEED_STANDS = {"HILLIARD2 (EAST)", "Bevelhymer Yellow"}
LOCATION_SPECIFIC_ITEM_STANDS = {
    ("FOUNTAIN_DRINKS", "7up"): UA_AND_NWSC_FOUNTAIN_STANDS | UA_FOUNTAIN_STANDS,
    ("FOUNTAIN_DRINKS", "Big Red"): UA_AND_NWSC_FOUNTAIN_STANDS | UA_FOUNTAIN_STANDS | {"BEXLEY"},
    ("FOUNTAIN_DRINKS", "Diet RC"): UA_AND_NWSC_FOUNTAIN_STANDS | {"BEXLEY"},
    ("FOUNTAIN_DRINKS", "Dr. Pepper"): NON_BEVELHYMER_STANDS,
    ("FOUNTAIN_DRINKS", "Lemonade"): UA_AND_NWSC_FOUNTAIN_STANDS | UA_FOUNTAIN_STANDS | {"BEXLEY"},
    ("FOUNTAIN_DRINKS", "Root Beer"): NON_BEVELHYMER_STANDS,
    ("FOUNTAIN_DRINKS", "RC Cola"): UA_AND_NWSC_FOUNTAIN_STANDS,
    ("FOUNTAIN_DRINKS", "Coke"): UA_FOUNTAIN_STANDS,
    ("FOUNTAIN_DRINKS", "Diet Coke"): UA_FOUNTAIN_STANDS,
    ("FOUNTAIN_DRINKS", "Diet Pepsi"): PTAC_ONLY,
    ("FOUNTAIN_DRINKS", "Mt. Dew"): PTAC_ONLY,
    ("FOUNTAIN_DRINKS", "Pepsi"): PTAC_ONLY,
    ("FOUNTAIN_DRINKS", "Starry"): PTAC_ONLY,
    "Poppi - Watermelon": PTAC_ONLY,
    "Poppi - Wild Berry": PTAC_ONLY,
    "Poppi - Raspberry Rose": PTAC_ONLY,
    "Popcorn": {"TREMONT", "REED ROAD", "NWSC"},
    "Milky Way": CHOCOLATE_BAR_STANDS,
    "Snickers": CHOCOLATE_BAR_STANDS,
    "Big League Chew": BEVELHYMER_STANDS,
    "Skittles": BEVELHYMER_STANDS,
    "M&M - Peanut": MMS_STANDS,
    "M&M - Regular": MMS_STANDS,
    "Bloom Pop - Strawberry Cream": BLOOM_POP_STANDS,
    "Bloom Pop - Raspberry Lemonade": BLOOM_POP_STANDS,
    "Bloom Pop - Watermelon Lime": BLOOM_POP_STANDS,
    "Iced Coffee - Vanilla": BLOOM_POP_STANDS,
    "Iced Coffee - Mocha": BLOOM_POP_STANDS,
    "Iced Coffee - Caramel": BLOOM_POP_STANDS,
    ("BOTTLED_DRINKS", "Diet Mt. Dew"): SODA_CAN_STANDS,
    ("BOTTLED_DRINKS", "Mt. Dew"): SODA_CAN_STANDS,
    ("BOTTLED_DRINKS", "Squirt"): SODA_CAN_STANDS,
    ("BOTTLED_DRINKS", "Dr. Pepper"): SODA_CAN_STANDS,
    ("BOTTLED_DRINKS", "Bubly - Green"): SODA_CAN_STANDS,
    ("BOTTLED_DRINKS", "Bubly - Red"): SODA_CAN_STANDS,
    ("BOTTLED_DRINKS", "Coke"): SODA_CAN_STANDS,
    ("BOTTLED_DRINKS", "Zero Sugar RC"): SODA_CAN_STANDS,
    ("BOTTLED_DRINKS", "RC"): SODA_CAN_STANDS,
    ("BOTTLED_DRINKS", "Sprite"): SODA_CAN_STANDS,
    ("BOTTLED_DRINKS", "7UP"): SODA_CAN_STANDS,
    ("BOTTLED_DRINKS", "Sunkist - Orange"): SODA_CAN_STANDS,
    ("BOTTLED_DRINKS", "AW Root Beer"): SODA_CAN_STANDS,
    "Coke": UA_FOUNTAIN_STANDS | SODA_CAN_STANDS,
    "Sunflower Seeds - Original": SUNFLOWER_SEED_STANDS,
    "Sunflower Seeds - Dill Pickle": SUNFLOWER_SEED_STANDS,
    "Sunflower Seeds - Ranch": SUNFLOWER_SEED_STANDS,
    # Novelties — location-restricted items
    "Cannonball!!!": NON_BEVELHYMER_STANDS,
    "Root Beer Float": NON_BEVELHYMER_STANDS,
    "Rainbow Sherbet Float": RAINBOW_SHERBET_FLOAT_STANDS,
    # Snacks — Bevelhymer only
    "Peanuts Shelled": BEVELHYMER_STANDS,
    "Kars": BEVELHYMER_STANDS,
    "Fig Bars": BEVELHYMER_STANDS,
    "Doughnut Packs": BEVELHYMER_STANDS,
    # Bottled drinks — Bevelhymer restrictions
    "Fairlife": NON_BEVELHYMER_STANDS,
    "Peach Tea": BEVELHYMER_STANDS,
}


def _is_item_available_at_stand(item_name, stand_name, category_name=None):
    """Return whether an item should appear for a stand.

    When category_name is provided, category-specific location overrides stored
    as (category_name, item_name) tuple keys take precedence over plain item
    name keys. This allows the same display name to be restricted differently
    across categories (for example fountain vs bottled soda rows).
    """
    if not stand_name:
        return True

    if category_name == "ICE_CREAM_TOFTS" and stand_name in BEVELHYMER_STANDS:
        return False

    if item_name in PREMIUM_ICE_CREAM_ITEMS:
        return stand_name in PREMIUM_ICE_CREAM_STANDS

    canonical_item = _canonical_item_name(item_name)
    if category_name:
        allowed_stands = LOCATION_SPECIFIC_ITEM_STANDS.get((category_name, canonical_item))
        if allowed_stands is not None:
            return stand_name in allowed_stands
    allowed_stands = LOCATION_SPECIFIC_ITEM_STANDS.get(canonical_item)
    if allowed_stands is not None:
        return stand_name in allowed_stands

    return True


def get_default_category_order_for_stand(stand_name):
    stand_category_order = []
    for category_name, item_list in DEFAULT_CATEGORY_ORDER:
        filtered_items = [
            item for item in item_list
            if _is_item_available_at_stand(item, stand_name, category_name)
        ]
        if filtered_items:
            stand_category_order.append((category_name, filtered_items))
    return stand_category_order

# ---------------------------------------------------------------------------
# Default category order (used when no stand-specific Master Items tab exists)
# ---------------------------------------------------------------------------
DEFAULT_CATEGORY_ORDER = [
    ("CANDY", CANDY),
    ("NOVELTIES", NOVELTIES),
    ("ICE_CREAM_TOFTS", _TOFTS_BASE_FLAVORS),
    ("FOUNTAIN_DRINKS", FOUNTAIN_DRINKS),
    ("BOTTLED_DRINKS", BOTTLED_DRINKS),
    ("SLUSHIE_FLAVORS", SLUSHIE_FLAVORS),
    ("FOOD", FOOD),
    ("SNACKS", SNACKS),
    ("DISPOSABLES", DISPOSABLES),
    ("JANITORIAL", JANITORIAL),
]

# Combine all category lists (for reference / legacy use)
all_categories = {
    "TOFTS_ICE_CREAM": TOFTS_ICE_CREAM,
    "CANDY": CANDY,
    "NOVELTIES": NOVELTIES,
    "ICE_CREAM_TOFTS": _TOFTS_BASE_FLAVORS,
    "FOUNTAIN_DRINKS": FOUNTAIN_DRINKS,
    "BOTTLED_DRINKS": BOTTLED_DRINKS,
    "SLUSHIE_FLAVORS": SLUSHIE_FLAVORS,
    "FOOD": FOOD,
    "SNACKS": SNACKS,
    "DISPOSABLES": DISPOSABLES,
    "JANITORIAL": JANITORIAL,
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
    """Append one week's inventory data as 12 new columns to the stand's sheet.

    Sheet layout
    ------------
    * Column A  – static item list (category headers + sorted item names).
    * Row 1     – week-label row:
                    • "Week of MM-DD-YYYY" merged over the first 5 columns
                      (Starting → Expected) of each week's block.
                    • "IN PERSON COUNT" merged over the 3 helper columns
                      (Individuals, Cases/Packs, Qty Per Case).
                    • Remaining columns (Actual → Tubs) are visually grouped
                      with the week label background but left blank.
                    • Column A always contains "ITEM".
    * Row 2     – sub-header row: Starting | Deliveries | Sales | Spoilage |
                  Expected | Individuals | Cases/Packs | Qty Per Case |
                  Actual | Variance | Scoops Used | Tubs Used
                  repeated for every week block; Column A is blank.
    * Row 3+    – data rows: one row per category header or item.

    On the first run the stand sheet is created automatically.  Subsequent
    runs detect the last week via the week labels in row 1 and append 12 more
    columns to the right — no new sheet tabs are created.
    """

    # ============================
    # CATEGORY ORDER
    # Try to read from "Master Items-{stand}" tab first; fall back to
    # DEFAULT_CATEGORY_ORDER (which includes INGREDIENTS / COMPONENTS).
    # ============================
    CATEGORY_ORDER = _build_category_order_for_stand(sheet, spreadsheet_id, stand_name)

    # ============================
    # ICE CREAM SCOOP TOTALS — compute BEFORE consolidation
    # group_scoops_by_flavor must see the individual variant rows
    # (e.g. "Brownie Bandit Double Scoop", "Brownie Bandit Single Scoop") so
    # it can apply per-variant multipliers (Double=2, Triple=3).  After
    # consolidate_variants_to_base() those variant rows are removed, so we
    # must capture flavor_totals first.
    # ============================
    flavor_totals = group_scoops_by_flavor(rows)
    tubs_used_map = tubs_used_from_scoops(flavor_totals)

    # ============================
    # SCOOP VARIANT CONSOLIDATION
    # Merges variant rows into base-flavor rows using simple addition (no
    # multipliers).  Sales = raw items sold (e.g. 120 for Brownie Bandit).
    # Multipliers are applied only in group_scoops_by_flavor() above.
    # ============================
    consolidate_variants_to_base(rows)

    # ============================
    # INGREDIENT-BASED SALES EXPANSION (per-stand, not consolidated)
    # Must run BEFORE the "ensure all items appear" loop so that computed
    # ingredient rows (Bun, Chili scoop, etc.) are in `rows` when that
    # loop checks them.
    # ============================
    calculate_ingredients_per_stand(rows)

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
    # AUDIT / VALIDATION SETUP
    # Build the ItemMatcher and helpers now that rows has all canonical items.
    # ============================
    week_label = datetime.today().strftime("Week of %m-%d-%Y")
    audit_logger = AuditLogger(stand_name)
    validator    = DataValidator()
    category_map = CategoryAwareItemMatcher.build_category_map(CATEGORY_ORDER)
    item_matcher = CategoryAwareItemMatcher(list(rows.keys()), category_map, threshold=0.65)

    # ============================
    # ICE CREAM SCOOP + TUBS LOGIC — assign computed values to base rows
    # ============================
    for flavor, scoops in flavor_totals.items():
        for tofts_flavor in TOFTS_ICE_CREAM:
            # Only assign scoops_used / tubs_used to the canonical BASE flavor
            # row.  Variant rows (Single Scoop, Double Scoop, etc.) inherit the
            # Toft's expected formula but intentionally show scoops_used = 0 so
            # they don't double-count against the base row's expected inventory.
            if normalize_flavor(tofts_flavor) == flavor and tofts_flavor in _TOFTS_BASE_FLAVORS:
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
    # Uses ItemMatcher so ALL categories carry forward correctly even if item
    # names have slight variations between runs.
    # ============================
    last_week_actuals = read_last_week_actuals_from_stand_sheet(
        sheet, spreadsheet_id, stand_name
    )
    unmatched_starting = []
    for item in rows:
        normalized_item = normalize_item_name(item)
        if normalized_item in last_week_actuals:
            rows[item]["starting"] = last_week_actuals[normalized_item]
        else:
            matched = item_matcher.find_match(item)
            if matched:
                normalized_match = normalize_item_name(matched)
                if normalized_match in last_week_actuals:
                    rows[item]["starting"] = last_week_actuals[normalized_match]
                    continue
            rows[item]["starting"] = 0
            # Only report as unmatched when a previous week exists
            if last_week_actuals:
                unmatched_starting.append(item)
    audit_logger.log_starting_inventory(last_week_actuals, unmatched_starting)

    # ============================
    # SPOILAGE INTEGRATION
    # Backup is logged BEFORE clearing so data is never silently lost on crash.
    # Fuzzy matching prevents silent data loss when staff misspells item names.
    # ============================
    spoilage_totals = read_spoilage(sheet, spreadsheet_id, stand_name)
    audit_logger.log_spoilage_backup(spoilage_totals)  # crash-safe backup

    # Reset all spoilage to 0, then apply matched entries
    for item in rows:
        rows[item]["spoilage"] = 0
    unmatched_spoilage = []
    for spoilage_item, qty in spoilage_totals.items():
        matched = item_matcher.find_match(spoilage_item)
        if matched and matched in rows:
            rows[matched]["spoilage"] = rows[matched].get("spoilage", 0) + qty
        else:
            unmatched_spoilage.append(spoilage_item)
    audit_logger.log_spoilage_read(spoilage_totals, unmatched_spoilage)
    clear_spoilage_sheet(sheet, spreadsheet_id, stand_name)

    # ============================
    # DELIVERIES INTEGRATION (date-filtered, accumulated)
    # Fuzzy matching prevents silent data loss when staff misspells item names.
    # ============================
    week_start_date, week_end_date = extract_week_dates_from_label(week_label)
    delivery_totals = read_deliveries(
        sheet, spreadsheet_id, stand_name,
        week_start_date=week_start_date,
        week_end_date=week_end_date,
    )
    unmatched_deliveries = []
    for delivery_item, qty in delivery_totals.items():
        matched = item_matcher.find_match(delivery_item)
        if matched and matched in rows:
            rows[matched]["deliveries"] = rows[matched].get("deliveries", 0) + qty
        else:
            unmatched_deliveries.append(delivery_item)
    audit_logger.log_deliveries_read(delivery_totals, unmatched_deliveries)

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
    # DATA INTEGRITY VALIDATION
    # Flag items with negative expected inventory before writing to the sheet.
    # ============================
    negative_items = validator.flag_negative_expected(expected_totals)
    audit_logger.log_inventory_write(week_label, negative_items)

    # ============================
    # BUILD ITEM → ROW-NUMBER LOOKUP (reads column A of the stand sheet)
    # ============================
    item_row_map = read_item_row_map(sheet, spreadsheet_id, stand_name)

    # ============================
    # WRITE WEEK LABEL (row 1) AND COLUMN SUB-HEADERS (row 2)
    # week_label was already computed at the top of the data pipeline above.
    # ============================
    week_start_letter = col_letter(next_week_start)
    week_end_letter   = col_letter(next_week_start + COLS_PER_WEEK - 1)

    # Row 1 – write the week label into the first column of this week's block
    # and write "IN PERSON COUNT" into the first helper column so Google Sheets
    # has the values for the two merged regions (see formatting below).
    in_person_start_letter = col_letter(next_week_start + COL_INDIVIDUALS)
    service.spreadsheets().values().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={
            "valueInputOption": "RAW",
            "data": [
                {
                    "range": f"'{stand_name}'!{week_start_letter}{HEADER_ROW}",
                    "values": [[week_label]],
                },
                {
                    "range": f"'{stand_name}'!{in_person_start_letter}{HEADER_ROW}",
                    "values": [[IN_PERSON_COUNT_LABEL]],
                },
            ],
        },
    ).execute()

    # Row 2: all twelve sub-headers.
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
    s_col   = col_letter(next_week_start + COL_STARTING)
    d_col   = col_letter(next_week_start + COL_DELIVERIES)
    sa_col  = col_letter(next_week_start + COL_SALES)
    sp_col  = col_letter(next_week_start + COL_SPOILAGE)
    ex_col  = col_letter(next_week_start + COL_EXPECTED)
    ind_col = col_letter(next_week_start + COL_INDIVIDUALS)
    cas_col = col_letter(next_week_start + COL_CASES)
    qty_col = col_letter(next_week_start + COL_QTY_PER_CASE)
    ac_col  = col_letter(next_week_start + COL_ACTUAL)
    va_col  = col_letter(next_week_start + COL_VARIANCE)
    sc_col  = col_letter(next_week_start + COL_SCOOPS)
    tu_col  = col_letter(next_week_start + COL_TUBS)

    batch_data = []

    for category_name, item_list in CATEGORY_ORDER:
        for item in sorted(item_list):
            row_num = _row_for_item_name(item_row_map, item)
            if not row_num:
                continue

            is_tofts = item in TOFTS_ICE_CREAM
            item_data = rows.get(item, {})

            # Spreadsheet formulas (use USER_ENTERED so Sheets evaluates them).
            # Deliveries are already converted to the correct unit:
            #   Toft's ice cream → scoops (packages × 60 done in read_deliveries)
            #   All other items  → units  (packages × units_per)
            # So Expected uses the same structure for every item:
            #   Toft's:    Starting + Deliveries - ScoopsUsed - Spoilage
            #   Non-Toft's: Starting + Deliveries - Sales - Spoilage
            if is_tofts:
                expected_formula = (
                    f"={s_col}{row_num}+{d_col}{row_num}"
                    f"-{sc_col}{row_num}-{sp_col}{row_num}"
                )
            else:
                expected_formula = (
                    f"={s_col}{row_num}+{d_col}{row_num}"
                    f"-{sa_col}{row_num}-{sp_col}{row_num}"
                )
            # Actual = Individuals + Cases/Packs × Qty Per Case.
            # Returns blank until at least one helper column is filled in.
            # NEW (CORRECT):
            actual_formula = (
                f'=IF(AND({ind_col}{row_num}="",'
                f'{cas_col}{row_num}=""),'
                f'IF({ex_col}{row_num}="",'
                f'"",'
                f'{ex_col}{row_num}),'
                f'IFERROR({ind_col}{row_num}+{cas_col}{row_num}*{qty_col}{row_num},""))'
            )
            variance_formula = (
                f'=IF({ac_col}{row_num}="",'
                f'"",{ac_col}{row_num}-{ex_col}{row_num})'
            )

            row_values = [
                item_data.get("starting", 0),        # Starting
                item_data.get("deliveries", 0),      # Deliveries (scoops for ice cream, units otherwise)
                item_data.get("sales", 0),               # Sales
                item_data.get("spoilage", 0),            # Spoilage
                expected_formula,                    # Expected (formula)
                "",                                  # Individuals   (employee fills in)
                "",                                  # Cases/Packs   (employee fills in)
                "",                                  # Qty Per Case  (employee fills in)
                actual_formula,                      # Actual = Ind + Cases×Qty
                variance_formula,                    # Variance = Actual − Expected
                item_data.get("scoops_used", 0) if is_tofts else "",  # Scoops Used
                item_data.get("tubs_used", 0)   if is_tofts else "",  # Tubs Used
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

    week_start_idx = next_week_start                      # 0-based
    week_end_idx   = next_week_start + COLS_PER_WEEK      # exclusive
    inpc_start_idx = next_week_start + COL_INDIVIDUALS    # first helper col
    inpc_end_idx   = next_week_start + COL_INDIVIDUALS + 3  # exclusive (3 helper cols)
    rest_start_idx = inpc_end_idx                         # Actual … Tubs

    # --- Row 1 merges ---
    # Merge 1: week label over cols 0-4 (Starting through Expected).
    fmt_requests.append({
        "mergeCells": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 0, "endRowIndex": 1,
                "startColumnIndex": week_start_idx,
                "endColumnIndex": inpc_start_idx,
            },
            "mergeType": "MERGE_ALL",
        }
    })
    # Merge 2: "IN PERSON COUNT" label over the 3 helper columns.
    fmt_requests.append({
        "mergeCells": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 0, "endRowIndex": 1,
                "startColumnIndex": inpc_start_idx,
                "endColumnIndex": inpc_end_idx,
            },
            "mergeType": "MERGE_ALL",
        }
    })
    # Merge 3: remaining columns (Actual → Tubs) blank merged region.
    fmt_requests.append({
        "mergeCells": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 0, "endRowIndex": 1,
                "startColumnIndex": rest_start_idx,
                "endColumnIndex": week_end_idx,
            },
            "mergeType": "MERGE_ALL",
        }
    })

    # --- Row 1 background colours ---
    # Week label section: blue
    fmt_requests.append({
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 0, "endRowIndex": 1,
                "startColumnIndex": week_start_idx, "endColumnIndex": inpc_start_idx,
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
    # IN PERSON COUNT section: orange
    fmt_requests.append({
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 0, "endRowIndex": 1,
                "startColumnIndex": inpc_start_idx, "endColumnIndex": inpc_end_idx,
            },
            "cell": {
                "userEnteredFormat": {
                    "backgroundColor": {"red": 0.949, "green": 0.580, "blue": 0.118},
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
    # Remaining section (Actual → Tubs): blue, matching week label
    fmt_requests.append({
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 0, "endRowIndex": 1,
                "startColumnIndex": rest_start_idx, "endColumnIndex": week_end_idx,
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

    # --- Row 2 (sub-headers) ---
    # Columns 0-4 and 8-11: standard blue.
    for col_range in [
        (week_start_idx, inpc_start_idx),
        (rest_start_idx, week_end_idx),
    ]:
        fmt_requests.append({
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 1, "endRowIndex": 2,
                    "startColumnIndex": col_range[0], "endColumnIndex": col_range[1],
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
    # Columns 5-7 (helper columns): orange to match IN PERSON COUNT header.
    fmt_requests.append({
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 1, "endRowIndex": 2,
                "startColumnIndex": inpc_start_idx, "endColumnIndex": inpc_end_idx,
            },
            "cell": {
                "userEnteredFormat": {
                    "backgroundColor": {"red": 0.949, "green": 0.580, "blue": 0.118},
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
        cat_row = _row_for_item_name(item_row_map, category_name)
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


_modifier_logger = logging.getLogger(__name__)


def write_modifier_sales_to_week(sheet, service, spreadsheet_id, stand_name, modifier_rows):
    """Overwrite the Sales cells in the most-recent week block for modifier items.

    Instead of creating a new week, this function finds the last week already
    written to the stand sheet and updates only the Sales column for each item
    found in *modifier_rows*.

    Args:
        sheet:           Google Sheets API resource (service.spreadsheets()).
        service:         Full Google Sheets API service object.
        spreadsheet_id:  ID of the target spreadsheet.
        stand_name:      Name of the stand tab within the spreadsheet.
        modifier_rows:   dict mapping item_name -> {"sales": int, ...}
                         as returned by take_modifiers().
    """
    last_week_start = find_last_week_start_col(sheet, spreadsheet_id, stand_name)
    if last_week_start == 0:
        _modifier_logger.warning(
            "write_modifier_sales_to_week: no weeks found in '%s' — "
            "run item-sales first to create the week block.",
            stand_name,
        )
        return

    sales_col = col_letter(last_week_start + COL_SALES)
    item_row_map = read_item_row_map(sheet, spreadsheet_id, stand_name)

    batch_data = []
    for item_name, mod_data in modifier_rows.items():
        row_num = _row_for_item_name(item_row_map, item_name)
        if row_num is None:
            _modifier_logger.warning(
                "Modifier item %r not found in sheet '%s' — skipping.",
                item_name,
                stand_name,
            )
            continue
        qty = mod_data.get("sales", 0)
        if item_name in SLUSHIE_FLAVORS:
            qty = round(qty / SLUSHIE_SERVINGS_PER_BAG, 2)
        batch_data.append({
            "range": f"'{stand_name}'!{sales_col}{row_num}",
            "values": [[qty]],
        })
        _modifier_logger.debug("Updated %r sales to %d", item_name, qty)

    if batch_data:
        service.spreadsheets().values().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"valueInputOption": "USER_ENTERED", "data": batch_data},
        ).execute()
        _modifier_logger.info(
            "Modifier sales written to column %s of '%s' (%d items).",
            sales_col,
            stand_name,
            len(batch_data),
        )
    else:
        _modifier_logger.warning(
            "No modifier items were matched in sheet '%s'.", stand_name
        )




def _sync_master_items_tab(sheet, service, spreadsheet_id, stand_name):
    """Remove stale non-canonical items from the per-stand Master Items tab."""
    tab_name = f"Master Items-{stand_name}"
    try:
        rows = get_values(sheet, spreadsheet_id, f"'{tab_name}'!A2:B500")
        tab_sheet_id = get_sheet_id(service, spreadsheet_id, tab_name)
    except Exception:
        return

    canonical_items_normalized = set()
    for _category_name, item_list in get_default_category_order_for_stand(stand_name):
        for item in item_list:
            normalized_item = normalize_item_name(item)
            if normalized_item:
                canonical_items_normalized.add(normalized_item)

    for row_num in range(len(rows) + 1, 1, -1):
        row = rows[row_num - 2] if row_num - 2 < len(rows) else []
        item_name = str(row[1] if len(row) > 1 else "").strip()
        normalized_item = normalize_item_name(item_name)
        if not normalized_item or normalized_item in canonical_items_normalized:
            continue

        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{
                "deleteDimension": {
                    "range": {
                        "sheetId": tab_sheet_id,
                        "dimension": "ROWS",
                        "startIndex": row_num - 1,
                        "endIndex": row_num,
                    }
                }
            }]},
        ).execute()


def sync_stand_item_list(sheet, service, spreadsheet_id, stand_name):
    """Sync the expected item list into Column A of an existing stand sheet.

    Reads the current Column A, compares it against the expected category/item
    order, removes obsolete rows, and inserts any missing items or category
    headers in the correct alphabetically-sorted position within their category.

    Rules
    -----
    * Only Column A is modified — week-data columns (B onward) are untouched.
    * Rows 1 and 2 are never deleted.
    * Obsolete rows are deleted unconditionally, including rows with week data.
    * The operation is idempotent: running it twice adds 0 items the second time.
    * New category headers get the same light-blue bold formatting as existing ones.
    * New item rows get plain white formatting.

    Returns
    -------
    dict with keys:
        "added"            – list of item/header names that were inserted
        "skipped"          – list of item names that already existed in Column A
        "removed"          – list of obsolete row names that were deleted
    """
    # -- Build expected category order (same logic as write_full_week) --
    category_order = _build_category_order_for_stand(sheet, spreadsheet_id, stand_name)

    # -- Get integer sheet ID for batchUpdate calls --
    sheet_id = get_sheet_id(service, spreadsheet_id, stand_name)

    # -- Build normalized expected names set from the CANONICAL code-defined list only. --
    # Do NOT use _build_category_order_for_stand here — that reads the Master Items
    # tab which may be stale and still contain old removed items.
    expected_names_normalized = set()
    canonical_order = get_default_category_order_for_stand(stand_name)
    for category_name, item_list in canonical_order:
        normalized_category = normalize_item_name(category_name)
        if normalized_category:
            expected_names_normalized.add(normalized_category)
        for item in item_list:
            normalized_item = normalize_item_name(item)
            if normalized_item:
                expected_names_normalized.add(normalized_item)

    removed = []
    sheet_values = sheet.values().get(
        spreadsheetId=spreadsheet_id,
        range=f"'{stand_name}'!A:ZZ",
    ).execute().get("values", [])

    def delete_row(row_num_1based):
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{
                "deleteDimension": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": "ROWS",
                        "startIndex": row_num_1based - 1,
                        "endIndex": row_num_1based,
                    }
                }
            }]},
        ).execute()

    def remove_dead_row(row_num_1based):
        delete_row(row_num_1based)
        logging.getLogger(__name__).info(
            "sync: removed blank/dead row %d from '%s'",
            row_num_1based,
            stand_name,
        )
        removed.append("<blank>")

    # -- Deletions first (bottom-to-top) --
    for row_num in range(len(sheet_values), DATA_START_ROW - 1, -1):
        row_values = sheet_values[row_num - 1] if row_num - 1 < len(sheet_values) else []
        if not row_values:
            remove_dead_row(row_num)
            continue
        item_name = str(row_values[0] if len(row_values) > 0 else "").strip()
        if not item_name:
            remove_dead_row(row_num)
            continue
        normalized_item = normalize_item_name(item_name)
        if not normalized_item or normalized_item in expected_names_normalized:
            continue

        delete_row(row_num)
        logging.getLogger(__name__).info(
            "sync: removed obsolete row %d ('%s') from '%s'",
            row_num,
            item_name,
            stand_name,
        )
        removed.append(item_name)

    # -- Read current Column A after deletions --
    existing_map = read_item_row_map(sheet, spreadsheet_id, stand_name)

    # -- Build the list of rows that need to be inserted --
    # Each entry: (anchor_row_1based, sort_key_tuple, item_name, is_header)
    # "anchor_row" is the 1-based row after which the new row will be inserted.
    insertions = []
    added = []
    skipped = []

    # Walk the expected structure top-to-bottom, tracking the last row we've
    # seen in the *existing* sheet so we know where to anchor insertions.
    last_known_row = SUBHEADER_ROW  # row 2; data starts at row 3

    for cat_idx, (category_name, item_list) in enumerate(category_order):
        sorted_items = sorted(item_list)

        normalized_category_name = normalize_item_name(category_name)
        if normalized_category_name in existing_map:
            last_known_row = existing_map[normalized_category_name]
            item_anchor = existing_map[normalized_category_name]
        else:
            # Category header is missing.  Anchor it (and its items) after the
            # last row we've seen so far.  When processed bottom-to-top the
            # header will be inserted last within its group, ending up directly
            # after last_known_row with all its items following.
            cat_anchor = last_known_row
            insertions.append((cat_anchor, (cat_idx, -1), category_name, True))
            added.append(category_name)
            item_anchor = last_known_row

        for item_idx, item in enumerate(sorted_items):
            normalized_item = normalize_item_name(item)
            if normalized_item in existing_map:
                skipped.append(item)
                last_known_row = existing_map[normalized_item]
                item_anchor = existing_map[normalized_item]
            else:
                # Insert this item after the nearest predecessor that exists.
                insertions.append((item_anchor, (cat_idx, item_idx), item, False))
                added.append(item)
                # item_anchor is intentionally NOT updated for missing items so
                # that subsequent missing items in this category also anchor off
                # the same row.  When sorted descending and processed one by one
                # they naturally accumulate in the correct sorted order.

    if not insertions:
        _sync_master_items_tab(sheet, service, spreadsheet_id, stand_name)
        return {"added": [], "skipped": skipped, "removed": removed}

    # -- Sort insertions bottom-to-top so earlier inserts don't shift later ones --
    # Primary sort: anchor_row descending (process lowest row last).
    # Secondary sort: sort_key descending (within equal anchors, process later
    # expected items first so the header ends up on top after all inserts).
    insertions.sort(key=lambda x: (x[0], x[1][0], x[1][1]), reverse=True)

    # -- Execute each insertion --
    for anchor_row, _sort_key, item_name, is_header in insertions:
        # Insert one blank row immediately after anchor_row.
        # insertDimension.startIndex is 0-based; startIndex=anchor_row inserts
        # before 0-based row anchor_row (= 1-based row anchor_row+1), which is
        # directly after 1-based row anchor_row.
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{
                "insertDimension": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": "ROWS",
                        "startIndex": anchor_row,
                        "endIndex": anchor_row + 1,
                    },
                    "inheritFromBefore": False,
                }
            }]},
        ).execute()

        new_row_1based = anchor_row + 1

        # Write the item/header name into Column A of the new row.
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"'{stand_name}'!A{new_row_1based}",
            valueInputOption="RAW",
            body={"values": [[item_name]]},
        ).execute()

        # Apply formatting: light-blue bold for category headers, plain for items.
        if is_header:
            cell_format = {
                "backgroundColor": {"red": 0.647, "green": 0.761, "blue": 0.902},
                "textFormat": {"bold": True},
            }
            end_column_index = 1
        else:
            cell_format = {
                "backgroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0},
                "backgroundColorStyle": {
                    "rgbColor": {"red": 1.0, "green": 1.0, "blue": 1.0}
                },
                "textFormat": {"bold": False},
            }
            end_column_index = 200

        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": new_row_1based - 1,
                        "endRowIndex": new_row_1based,
                        "startColumnIndex": 0,
                        "endColumnIndex": end_column_index,
                    },
                    "cell": {"userEnteredFormat": cell_format},
                    "fields": "userEnteredFormat(backgroundColor,backgroundColorStyle,textFormat)",
                }
            }]},
        ).execute()

    _sync_master_items_tab(sheet, service, spreadsheet_id, stand_name)
    return {"added": added, "skipped": skipped, "removed": removed}


def connect_to_sheets():
    creds = Credentials.from_service_account_file(
        r"C:\Users\willi\OneDrive\Desktop\inventory_Script\Credentials-personal.json",
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    service = build("sheets", "v4", credentials=creds)
    return service
