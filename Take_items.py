import csv
import logging
import os

from data_validation import AuditLogger, _make_logger

COMBO_BREAKDOWN = {
    "Chili Cheese Dog Combo Meal": ["Chili Cheese Dog", "Assorted Chips", "Fountain Drink"],
    "Uncrustable Combo Meal": ["Uncrustable", "Assorted Chips", "Fountain Drink"],
    "Chicken Salad Combo Meal": ["Chicken Salad Sandwich", "Assorted Chips", "Fountain Drink"],
    "Hot Dog Combo Meal": ["Hot Dog", "Assorted Chips", "Fountain Drink"],
    "pizza Combo Meal": ["Pizza slice", "Assorted Chips", "Fountain Drink"],
    "Pulled Pork Combo": ["Chicken Tenders", "Fries", "Fountain Drink"],
}

MODIFIER_ITEMS = {
    "Gatorade": ["Gatorade Blue", "Gatorade Red", "Gatorade Orange"],
    # Add more items here as we scale beyond prototype
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
                _logger.debug("Skipping modifier item: %r", item)
                skipped_rows += 1
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


def take_modifiers(csv_file_path, week_start_date=None, week_end_date=None, stand_name=None):
    """Parse a Square modifier CSV export and return a dict of modifier item sales.

    CSV format:
        Modifier Set,Modifier,<date-range column(s)...>

    The item name is constructed by finding which MODIFIER_ITEMS key is contained
    in the Modifier Set value (e.g. "Gatorade Flavor" contains "Gatorade"), then
    combining that key with the Modifier value (e.g. "Gatorade" + "Blue" →
    "Gatorade Blue").

    Args:
        csv_file_path:   Absolute path to the modifier CSV file.
        week_start_date: Optional start date to filter columns (reserved for future use).
        week_end_date:   Optional end date to filter columns (reserved for future use).
        stand_name:      Optional stand name for audit logging.

    Returns:
        dict mapping item_name -> {"starting": 0, "deliveries": 0,
                                   "sales": int, "spoilage": 0}
        Returns an empty dict if the file is not found or parsing fails.
    """
    if not os.path.exists(csv_file_path):
        _logger.warning("Modifier file not found: %s", csv_file_path)
        return {}

    rows = {}
    _logger.info("Reading modifier CSV: %s", csv_file_path)

    try:
        with open(csv_file_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)

            fieldnames = reader.fieldnames or []
            # Normalize header names (same treatment as take_items)
            fieldnames = [
                fn.replace("\u00A0", " ")
                  .replace("\u200B", "")
                  .replace("\u202F", " ")
                  .strip()
                for fn in fieldnames
            ]
            reader.fieldnames = fieldnames

            # Date columns are every column after "Modifier Set" and "Modifier"
            date_columns = [
                fn for fn in fieldnames
                if fn not in ("Modifier Set", "Modifier")
            ]

            if not date_columns:
                _logger.warning(
                    "Modifier CSV has no date columns: %s", csv_file_path
                )
                return {}

            _logger.debug("Modifier CSV date columns: %s", date_columns)

            for line in reader:
                modifier_set = (line.get("Modifier Set") or "").strip()
                modifier = (line.get("Modifier") or "").strip()

                if not modifier_set or not modifier:
                    continue

                # Find which MODIFIER_ITEMS key is contained in the modifier set name.
                # Use the longest matching key to avoid ambiguity when one key is a
                # substring of another (e.g. "Gatorade" vs "Gatorade Zero").
                base_name = None
                for key in sorted(MODIFIER_ITEMS, key=len, reverse=True):
                    if key in modifier_set:
                        base_name = key
                        break

                if base_name is None:
                    _logger.debug(
                        "Modifier set %r not matched in MODIFIER_ITEMS — skipping",
                        modifier_set,
                    )
                    continue

                item_name = f"{base_name} {modifier}"

                # Sum quantities across all date columns
                total_qty = 0
                for col in date_columns:
                    raw = (line.get(col) or "").strip()
                    if not raw:
                        continue
                    # Handle dollar-prefixed values (Square sometimes exports currency
                    # format like "$5.00") as well as plain integer/float quantities.
                    raw = raw.lstrip("$").replace(",", "")
                    try:
                        total_qty += int(round(float(raw)))
                    except ValueError:
                        _logger.warning(
                            "Could not parse quantity %r for %r in column %r",
                            raw, item_name, col,
                        )

                rows[item_name] = {
                    "starting": 0,
                    "deliveries": 0,
                    "sales": total_qty,
                    "spoilage": 0,
                }
                _logger.debug("Modifier item: %r → sales=%d", item_name, total_qty)

    except Exception as exc:
        _logger.error("Failed to parse modifier CSV %s: %s", csv_file_path, exc)
        return {}

    _logger.info(
        "Modifier CSV read complete: %d modifier items loaded from %s",
        len(rows), os.path.basename(csv_file_path),
    )
    return rows
