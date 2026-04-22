import csv
import logging
import os
import re
from datetime import datetime as _dt

from data_validation import AuditLogger, _make_logger

# Items that are tracked by modifier variant in the sheet.
# Key: base item name as it appears in the Square item-sales CSV (must be skipped
#      by take_items so the base row is never written to the sheet).
# Value: list of sheet item names for each modifier variant.
MODIFIER_ITEMS = {
    "Gatorade": ["Gatorade Blue", "Gatorade Red", "Gatorade Orange"],
}

COMBO_BREAKDOWN = {
    "Chili Cheese Dog Combo Meal": ["Chili Cheese Dog", "Assorted Chips", "Fountain Drink"],
    "Uncrustable Combo Meal": ["Uncrustable", "Assorted Chips", "Fountain Drink"],
    "Chicken Salad Combo Meal": ["Chicken Salad Sandwich", "Assorted Chips", "Fountain Drink"],
    "Hot Dog Combo Meal": ["Hot Dog", "Assorted Chips", "Fountain Drink"],
    "pizza Combo Meal": ["Pizza slice", "Assorted Chips", "Fountain Drink"],
    "Pulled Pork Combo": ["Chicken Tenders", "Fries", "Fountain Drink"],
}

_logger = _make_logger("concession.Take_items")


def _validate_combo_breakdown():
    """Warn at import time if any combo component is listed only in COMBO_BREAKDOWN
    and not as a standalone item (informational, not an error)."""
    all_components = {comp for comps in COMBO_BREAKDOWN.values() for comp in comps}
    all_keys = set(COMBO_BREAKDOWN.keys())
    orphan_components = all_components - all_keys
    if orphan_components:
        _logger.debug(
            "Combo components (expected to exist as standalone inventory items): %s",
            sorted(orphan_components),
        )


_validate_combo_breakdown()


def take_items(csv_file_path, stand_name=None):
    """Parse a Square POS CSV export and return a dict of item sales.

    Args:
        csv_file_path: Absolute path to the CSV file.
        stand_name:    Optional stand name used for audit logging.

    Returns:
        dict mapping item_name -> {"starting": 0, "deliveries": 0,
                                   "sales": int, "spoilage": 0}
    """
    csv_path = csv_file_path
    rows = {}
    raw_row_count = 0
    skipped_rows = 0
    malformed_rows = 0

    _logger.info("Reading CSV: %s", csv_path)

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        # ------------------------------------------------------------
        # PERMANENT FIX: Normalize header names
        # ------------------------------------------------------------
        reader.fieldnames = [
            fn.replace("\u00A0", " ")   # non-breaking space
              .replace("\u200B", "")    # zero-width space
              .replace("\u202F", " ")   # narrow no-break space
              .strip()
            for fn in reader.fieldnames
        ]

        for line in reader:
            raw_row_count += 1
            item = (line.get("Item Name") or "").strip()

            sold_raw = (line.get("Units Sold") or "").strip()
            refunded_raw = (line.get("Units Refunded") or "").strip()

            try:
                sold = int(sold_raw) if sold_raw else 0
                refunded = int(refunded_raw) if refunded_raw else 0
            except ValueError:
                malformed_rows += 1
                _logger.warning(
                    "Row %d: could not parse Units Sold=%r or Units Refunded=%r "
                    "for item %r — defaulting to 0",
                    raw_row_count, sold_raw, refunded_raw, item,
                )
                sold = refunded = 0

            net_sales = sold - refunded

            if item == "":
                skipped_rows += 1
                continue

            if item in MODIFIER_ITEMS:
                skipped_rows += 1
                _logger.debug(
                    "Skipping modifier base item %r (tracked via take_modifiers)",
                    item,
                )
                continue

            if item in COMBO_BREAKDOWN:
                for comp in COMBO_BREAKDOWN[item]:
                    if comp not in rows:
                        rows[comp] = {
                            "starting": 0,
                            "deliveries": 0,
                            "sales": 0,
                            "spoilage": 0,
                        }
                    rows[comp]["sales"] += net_sales
                _logger.debug(
                    "Combo %r expanded to %s (qty=%d)",
                    item, COMBO_BREAKDOWN[item], net_sales,
                )
                continue  # skip adding the combo itself

            if item not in rows:
                rows[item] = {
                    "starting": 0,
                    "deliveries": 0,
                    "sales": 0,
                    "spoilage": 0,
                }

            rows[item]["sales"] += net_sales

    _logger.info(
        "CSV read complete: %d raw rows, %d items loaded, "
        "%d skipped (blank), %d malformed",
        raw_row_count, len(rows), skipped_rows, malformed_rows,
    )

    # Audit log (only when stand_name provided)
    if stand_name:
        audit = AuditLogger(stand_name)
        audit.log_csv_read(
            csv_path=csv_path,
            row_count=raw_row_count,
            item_names=list(rows.keys()),
        )

    return rows


# ---------------------------------------------------------------------------
# Modifier CSV helpers
# ---------------------------------------------------------------------------

def _parse_date_col(col_str):
    """Parse a modifier CSV date-column header into a (start, end) date pair.

    Accepted formats
    ----------------
    * Date range : ``MM/DD/YYYY-MM/DD/YYYY``  →  (start_date, end_date)
    * Single date: ``MM/DD/YYYY``              →  (date, date)

    Returns ``(None, None)`` if the string cannot be parsed.
    """
    col_str = col_str.strip()
    # Try date range: "04/06/2026-04/11/2026"
    # Both halves must contain "/" to be valid MM/DD/YYYY tokens.
    if "-" in col_str:
        halves = col_str.split("-", 1)
        left, right = halves[0].strip(), halves[1].strip()
        if "/" in left and "/" in right:
            try:
                start = _dt.strptime(left, "%m/%d/%Y").date()
                end   = _dt.strptime(right, "%m/%d/%Y").date()
                return start, end
            except ValueError:
                pass
    # Try single date: "04/12/2026"
    try:
        d = _dt.strptime(col_str, "%m/%d/%Y").date()
        return d, d
    except ValueError:
        pass
    return None, None


def take_modifiers(csv_file_path, week_start_date, week_end_date):
    """Parse a Square modifier CSV export and return a dict of modifier sales.

    The modifier CSV is expected to have this column layout::

        Modifier Set | Modifier | <date-col-1> | <date-col-2> | ...

    Date columns in the header are either date ranges (``MM/DD/YYYY-MM/DD/YYYY``)
    or single dates (``MM/DD/YYYY``).  Only the column(s) whose range overlaps
    with [*week_start_date*, *week_end_date*] are summed.

    Modifier variants are resolved against :data:`MODIFIER_ITEMS`.  For a row
    with Modifier Set ``"Gatorade Flavor"`` and Modifier ``"Blue"``, this
    function looks for ``"<base> Blue"`` in each variant list, finding
    ``"Gatorade Blue"`` when ``MODIFIER_ITEMS["Gatorade"]`` contains it.

    Args:
        csv_file_path:   Absolute path to the modifier CSV file.
        week_start_date: :class:`datetime.date` - first day of the current week.
        week_end_date:   :class:`datetime.date` - last day of the current week.

    Returns:
        dict mapping item_name -> {"starting": 0, "deliveries": 0,
                                   "sales": int, "spoilage": 0}
    """
    rows = {}

    _logger.info("Reading modifier CSV: %s", csv_file_path)

    with open(csv_file_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        # Normalise header names the same way take_items() does.
        reader.fieldnames = [
            fn.replace("\u00A0", " ")
              .replace("\u200B", "")
              .replace("\u202F", " ")
              .strip()
            for fn in reader.fieldnames
        ]

        all_cols = reader.fieldnames
        # Validate expected structure: first two columns must be "Modifier Set" / "Modifier".
        if len(all_cols) < 2 or all_cols[0] != "Modifier Set" or all_cols[1] != "Modifier":
            _logger.warning(
                "Modifier CSV %r has unexpected header layout %s; "
                "expected first two columns to be 'Modifier Set' and 'Modifier'. "
                "Aborting modifier load.",
                csv_file_path, all_cols[:4],
            )
            return {}
        # First two columns are always "Modifier Set" and "Modifier".
        date_col_names = all_cols[2:]

        # Identify which date columns overlap with the requested week.
        matching_cols = []
        for col in date_col_names:
            col_start, col_end = _parse_date_col(col)
            if col_start is None:
                _logger.debug("Skipping unparseable modifier header column: %r", col)
                continue
            if col_start <= week_end_date and col_end >= week_start_date:
                matching_cols.append(col)

        if not matching_cols:
            _logger.warning(
                "No modifier CSV columns match week %s - %s; no modifier data loaded.",
                week_start_date, week_end_date,
            )
            return {}

        _logger.info("Matching modifier date columns: %s", matching_cols)

        raw_row_count = 0
        for line in reader:
            raw_row_count += 1
            modifier_set = (line.get("Modifier Set") or "").strip()
            modifier_val = (line.get("Modifier") or "").strip()

            if not modifier_set or not modifier_val:
                continue

            # Resolve modifier variant -> sheet item name via MODIFIER_ITEMS.
            # Strategy: for each base item, check if "<base> <modifier>" is a
            # known variant.  This is modifier-set-name-agnostic, which avoids
            # brittle string stripping on "Gatorade Flavor" -> "Gatorade".
            item_name = None
            for base_item, variants in MODIFIER_ITEMS.items():
                candidate = f"{base_item} {modifier_val}"
                if candidate in variants:
                    item_name = candidate
                    break

            if item_name is None:
                _logger.debug(
                    "Modifier %r / %r not found in MODIFIER_ITEMS - skipping",
                    modifier_set, modifier_val,
                )
                continue

            # Sum quantities from all matching date columns.
            # Square exports modifier quantities as integers, but free modifiers
            # may appear as "$0.00" (currency-formatted). Strip currency symbols
            # and try integer parsing first; fall back to float→int for "25.00".
            total_qty = 0
            for col in matching_cols:
                raw = (line.get(col) or "").strip().replace("$", "").replace(",", "")
                if not raw:
                    continue
                try:
                    total_qty += int(raw)
                except ValueError:
                    try:
                        total_qty += int(float(raw))
                    except ValueError:
                        _logger.warning(
                            "Could not parse quantity %r in column %r for item %r",
                            raw, col, item_name,
                        )

            if item_name not in rows:
                rows[item_name] = {
                    "starting": 0,
                    "deliveries": 0,
                    "sales": 0,
                    "spoilage": 0,
                }
            rows[item_name]["sales"] += total_qty

    _logger.info(
        "Modifier CSV read complete: %d raw rows, %d modifier items loaded",
        raw_row_count, len(rows),
    )
    return rows
