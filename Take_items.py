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

    # DEBUG: Print what was actually loaded from CSV
    print("\n" + "=" * 50)
    print("ITEMS LOADED FROM CSV:")
    print("=" * 50)
    for item_name, item_data in rows.items():
        print(f"  {item_name}: sales={item_data['sales']}")
    print("=" * 50 + "\n")

    return rows


# TEST: Call the function and see output
if __name__ == "__main__":
    rows = take_items("Bevelhymer Green")  # replace with desired stand name
    print("Done!")
    print("\n====================")
    print("FLAVOR KEYS FOUND:")
    for k in rows.keys():
        print(f"• {repr(k)}")
    print("====================\n")
