import csv
import logging
import os

from data_validation import AuditLogger, _make_logger
from item_name_utils import normalize_item_name

COMBO_BREAKDOWN = {
    "Chili Cheese Dog Combo Meal": ["Chili Cheese Dog", "Assorted Chips"],
    "Chili Cheese Dog COMBO": ["Chili Cheese Dog", "Assorted Chips"],
    "Uncrustable Combo Meal": ["Uncrustable", "Assorted Chips"],
    "Uncrustable COMBO": ["Uncrustable", "Assorted Chips"],
    "Chicken Salad Combo Meal": ["Chicken Salad Sandwich", "Assorted Chips"],
    "Combo Meal 3": ["Chicken Salad Sandwich", "Assorted Chips"],
    # Sandwich quantity comes from the modifier-sales CSV via
    # "Ham Sandwich OR Chicken Salad"; only the chips come from the combo row.
    "Chicken Salad OR Ham Sandwich COMBO": ["Assorted Chips"],
    "Ham and Cheese Combo Meal": ["Ham & Cheese Sandwich", "Assorted Chips"],
    "Hot Dog Combo Meal": ["Hot Dog", "Assorted Chips"],
    "Hot Dog COMBO": ["Hot Dog", "Assorted Chips"],
    "Pizza Combo Meal": ["Pizza Slice", "Assorted Chips"],
    "Pizza COMBO": ["Pizza Slice", "Assorted Chips"],
    "Whole Jet's Pizza": ["Pizza Slice", "Pizza Slice", "Pizza Slice", "Pizza Slice", "Pizza Slice", "Pizza Slice", "Pizza Slice", "Pizza Slice"],
    "Pulled Pork Combo Meal": ["Pulled Pork Sandwich", "Assorted Chips"],
    "Pulled Pork COMBO": ["Pulled Pork Sandwich", "Assorted Chips"],
    "Cannonball!!!": ["Vanilla"],
    "Root Beer Float": ["Root Beer", "Vanilla"],
    "Rainbow Sherbet Float": ["Rainbow Sherbet", "7up"],
}

MODIFIER_ITEMS = {
    "Gatorade": ["Gatorade - Blue", "Gatorade - Red", "Gatorade - Yellow"],
    "Ice Cream Toppings": [],
    "Toppings": [],  # legacy Square naming variant; values come from modifier CSV
    "Topping": [],  # legacy Square naming variant; values come from modifier CSV
    "Fountain Drink Flavor": [],
    "Fountain Drink": [],  # flavors come from modifier CSV
    "Fountain": [],  # variant modifier-set naming
    "Fountain Soda": [],
    "Ham Sandwich OR Chicken Salad": [],
    "Iced Coffee": [],
    "La Colombe": [],  # variant modifier-set naming
    "Chocolate Bar Flavor": [],
    "Chocolate Bars": [],
    "M&Ms Flavor": [],
    "M&Ms": [],
    "Soda Can": [],
    "Soda can": [],
    "Sunflower Seed Flavors": [],
    "Sunflower Seeds": [],
    "Bloom Pop": [],    # Bloom Pop flavors come from modifier CSV
    "Poppi": [],        # Poppi flavors come from modifier CSV
    "Slushie": [],      # slushie flavors come from modifier CSV
    "Flavor": [],       # alternate Square display name for slushie modifiers
    "Crunchy Ra-Ra": [],  # crunchy flavors come from modifier CSV
    "Crunchy Rara": [],   # backward-compatible naming variant
    "Crunchy Ra-Ra Yogurt": [],  # legacy base name kept for backward compatibility
    "Single-Dip": [],
    "Single Dip": [],   # ice cream — flavors come from modifier CSV
    "Double Dip": [],   # ice cream — flavors come from modifier CSV
    "Triple Dip": [],   # ice cream — flavors come from modifier CSV
    # Ice Cream Flavor 1/2/3 modifier sets — the modifier value IS the flavor name
    "Ice Cream Flavor": [],
}

# Prefix used for Toft's ice cream modifier set names in the modifier CSV
# (e.g. "Ice Cream Flavor 1", "Ice Cream Flavor 2", "Ice Cream Flavor 3").
# When a modifier set name contains this prefix the modifier value is used
# directly as the item name rather than being prefixed with the set name.
ICE_CREAM_FLAVOR_SET_PREFIX = "Ice Cream Flavor"
SLUSHIE_FLAVOR_SET_PREFIX = "Slushie"
CRUNCHY_RARA_MODIFIER_PREFIX = "Crunchy"
CRUNCHY_RARA_MODIFIER_KEYS = {"Crunchy Ra-Ra", "Crunchy Rara", "Crunchy Ra-Ra Yogurt"}
BLOOM_POP_FLAVOR_SET_PREFIX = "Bloom Pop"
POPPI_FLAVOR_SET_PREFIX = "Poppi"
ICE_CREAM_TOPPINGS_PREFIX = "Ice Cream Toppings"
HAM_CHICKEN_MODIFIER_SET = "Ham Sandwich OR Chicken Salad"
SLUSHIE_FLAVOR_SET_PREFIX_LOWER = SLUSHIE_FLAVOR_SET_PREFIX.lower()
CRUNCHY_RARA_MODIFIER_PREFIX_LOWER = CRUNCHY_RARA_MODIFIER_PREFIX.lower()
BLOOM_POP_FLAVOR_SET_PREFIX_LOWER = BLOOM_POP_FLAVOR_SET_PREFIX.lower()
POPPI_FLAVOR_SET_PREFIX_LOWER = POPPI_FLAVOR_SET_PREFIX.lower()

# All Toft's ice cream item names that may appear in the item-sales CSV.
# These are skipped in take_items() because ice cream is now tracked entirely
# via the modifier-sales CSV (Double Dip / Triple Dip base items feed into
# Ice Cream Flavor 1/2/3 modifier sets).  Mirrors TOFTS_ICE_CREAM from
# Call_sheets.py — keep in sync when new scoop variants are added.
_TOFTS_ICE_CREAM_SKIP_ITEMS: frozenset = frozenset({
    # Base flavors
    "Brownie Bandit", "Birthday Cake", "Chocolate", "Cookie Dough",
    # Keep both Cotton Candy names because Square/POS exports have used both.
    "Cookie Monster", "Cookies n' Cream", "Vanilla", "Cotton Candy", "Cotton Candy Ice Cream",
    "Mint Chip", "Rainbow Sherbet", "PB S'Mores", "Blueberry Waffle Cone",
    # Scoop variants
    "Brownie Bandit Single Scoop", "Brownie Bandit Double Scoop", "Brownie Bandit Triple Scoop",
    "Birthday Cake Single Scoop", "Birthday Cake Double Scoop", "Birthday Cake Triple Scoop",
    "Chocolate Single Scoop", "Chocolate Double Scoop", "Chocolate Triple Scoop",
    "Cookie Dough Single Scoop", "Cookie Dough Double Scoop", "Cookie Dough Triple Scoop",
    "Cookie Monster Single Scoop", "Cookie Monster Double Scoop", "Cookie Monster Triple Scoop",
    "Cookies n' Cream Single Scoop", "Cookies n' Cream Double Scoop", "Cookies n' Cream Triple Scoop",
    "Cookies N Cream", "Cookies N Cream Single Scoop", "Cookies N Cream Double Scoop", "Cookies N Cream Triple Scoop",
    "Cookies & Cream", "Cookies & Cream Single Scoop", "Cookies & Cream Double Scoop", "Cookies & Cream Triple Scoop",
    "Cotton Candy Single Scoop", "Cotton Candy Double Scoop", "Cotton Candy Triple Scoop",
    "Cotton Candy Ice Cream Single Scoop", "Cotton Candy Ice Cream Double Scoop", "Cotton Candy Ice Cream Triple Scoop",
    "Mint Chip Single Scoop", "Mint Chip Double", "Mint Chip Double Scoop", "Mint Chip Triple Scoop",
    "Rainbow Sherbet Single Scoop", "Rainbow Sherbet Double Scoop", "Rainbow Sherbet Triple Scoop",
    # Backward-compatible CSV spelling variant (common misspelling in POS exports)
    "Rainbow Sherbert", "Rainbow Sherbert Single Scoop", "Rainbow Sherbert Double Scoop", "Rainbow Sherbert Triple Scoop",
    "PB S'Mores Single Scoop", "PB S'Mores Double Scoop", "PB S'Mores Triple Scoop",
    "Blueberry Waffle Cone Single Scoop", "Blueberry Waffle Cone Double Scoop", "Blueberry Waffle Cone Triple Scoop",
    "Blueberry Waffle Cone Cone",
    "Vanilla Single Scoop", "Vanilla Double Scoop", "Vanilla Triple Scoop",
})

_NORMALIZED_MODIFIER_ITEMS = {normalize_item_name(name) for name in MODIFIER_ITEMS}

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
    modifier_skipped_items = []

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

            normalized_item = normalize_item_name(item)
            if normalized_item in _NORMALIZED_MODIFIER_ITEMS:
                qty = net_sales
                _logger.info(
                    "⏭️  SKIPPING MODIFIER ITEM: %r (qty=%d) — will be populated by modifier-sales CSV",
                    item, qty
                )
                modifier_skipped_items.append((item, qty))
                skipped_rows += 1
                continue

            # Skip legacy Toft's ice cream scoop variants — ice cream is now
            # tracked entirely via the modifier-sales CSV (Ice Cream Flavor
            # 1/2/3 modifier sets).  Base items ("Double Dip", "Triple Dip")
            # are already skipped above via MODIFIER_ITEMS.
            if item in _TOFTS_ICE_CREAM_SKIP_ITEMS:
                _logger.debug(
                    "⏭️  Skipping legacy ice cream item %r — tracked via modifier CSV",
                    item,
                )
                skipped_rows += 1
                continue

            if item in COMBO_BREAKDOWN:
                components = list(COMBO_BREAKDOWN[item])
                if item == "Rainbow Sherbet Float" and stand_name == "PTAC":
                    components = ["Starry" if c == "7up" else c for c in components]
                for comp in components:
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
                    item, components, net_sales,
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

    if modifier_skipped_items:
        _logger.info(
            "🔄 Modifier items skipped: %s — these will be populated when modifier-sales CSV runs",
            ", ".join([f"{item}({qty})" for item, qty in modifier_skipped_items])
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

    Supports two CSV layouts:

    Date-range layout (Gatorade):
        Modifier Set,Modifier,<date-range column(s)...>
        e.g. "Gatorade Flavor,Blue,3"

    Qty-Sold layout (Ice Cream):
        Modifier Set,Modifier,Qty Sold,Gross Sales
        e.g. "Ice Cream Flavor 1,Cookie Monster,2,$0.00"

    All columns other than "Modifier Set" and "Modifier" are treated as
    quantity columns and summed.  Dollar-prefixed values (e.g. "$0.00") are
    stripped of the leading "$" and contribute 0 after rounding, so the
    "Gross Sales" column in the ice cream CSV is safely ignored.

    Item-name construction:
    - For regular modifier sets:
        "{base_name} {modifier}"  (example: "Crunchy Ra-Ra Yogurt Strawberry")
      Special case:
        Gatorade modifiers use a canonical dashed name
        "Gatorade - {modifier}"  →  "Gatorade - Blue"
    - For ice cream flavor sets (modifier set contains ICE_CREAM_FLAVOR_SET_PREFIX):
        "{modifier}"  →  "Cookie Monster"
    - For slushie flavor sets (modifier set contains SLUSHIE_FLAVOR_SET_PREFIX):
        "Slushie - {modifier}"  →  "Slushie - Mango"
      Quantities are accumulated across matching slushie flavor rows.
    - For crunchy ra-ra modifier sets (matched by CRUNCHY_RARA_MODIFIER_KEYS):
        "Crunchy Ra-Ra - {modifier}"  →  "Crunchy Ra-Ra - Strawberry"
      Quantities are accumulated across matching crunchy flavor rows.
    - Ice cream quantities are accumulated across all Ice Cream Flavor N sets so
      the same flavor appearing in Flavor 1, Flavor 2, and Flavor 3 is summed.

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
    _logger.info("🔄 Reading modifier CSV: %s", csv_file_path)

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

            # All columns after "Modifier Set" and "Modifier" are quantity
            # columns (date ranges for Gatorade; "Qty Sold"/"Gross Sales" for
            # ice cream).  Dollar-prefixed values round to 0 and are harmless.
            date_columns = [
                fn for fn in fieldnames
                if fn not in ("Modifier Set", "Modifier")
            ]

            if not date_columns:
                _logger.warning(
                    "Modifier CSV has no quantity columns: %s", csv_file_path
                )
                return {}

            _logger.debug("Modifier CSV quantity columns: %s", date_columns)

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

                # For ice cream flavor sets (e.g. "Ice Cream Flavor 1"),
                # the modifier value IS the flavor name.  Quantities from
                # Flavor 1, Flavor 2, and Flavor 3 are summed into one entry.
                # For all other modifier sets (e.g. "Gatorade Flavor"),
                # the item name is "{base_name} {modifier}".
                modifier_set_lower = modifier_set.lower()
                if ICE_CREAM_FLAVOR_SET_PREFIX in modifier_set:
                    item_name = modifier
                # Some stands export the slushie modifier set as the bare display
                # name "Flavor"; treat it the same as the explicit "Slushie" set.
                elif modifier_set == "Flavor" or SLUSHIE_FLAVOR_SET_PREFIX_LOWER in modifier_set_lower:
                    item_name = f"Slushie - {modifier}"
                elif (
                    base_name in CRUNCHY_RARA_MODIFIER_KEYS
                    and CRUNCHY_RARA_MODIFIER_PREFIX_LOWER in modifier_set_lower
                ):
                    item_name = f"Crunchy Ra-Ra - {modifier}"
                elif BLOOM_POP_FLAVOR_SET_PREFIX_LOWER in modifier_set_lower:
                    item_name = f"Bloom Pop - {modifier}"
                elif POPPI_FLAVOR_SET_PREFIX_LOWER in modifier_set_lower:
                    item_name = f"Poppi - {modifier}"
                elif base_name == "Gatorade":
                    item_name = f"Gatorade - {modifier}"
                elif base_name in {ICE_CREAM_TOPPINGS_PREFIX, "Toppings", "Topping"}:
                    item_name = modifier
                elif base_name in {"Fountain Drink Flavor", "Fountain Drink", "Fountain"}:
                    if modifier == "RC":
                        item_name = "RC Cola"
                    elif modifier == "Coke":
                        item_name = "Coke"
                    else:
                        item_name = modifier
                elif base_name == HAM_CHICKEN_MODIFIER_SET:
                    if modifier == "Ham Sandwich":
                        item_name = "Ham & Cheese Sandwich"
                    else:
                        item_name = modifier
                elif base_name in {"Iced Coffee", "La Colombe"}:
                    item_name = f"Iced Coffee - {modifier}"
                elif base_name in {"Chocolate Bar Flavor", "Chocolate Bars"}:
                    item_name = modifier
                elif base_name in {"M&Ms Flavor", "M&Ms"}:
                    item_name = f"M&M - {modifier}"
                elif base_name in {"Soda Can", "Soda can"}:
                    item_name = modifier
                elif base_name in {"Sunflower Seed Flavors", "Sunflower Seeds"}:
                    item_name = f"Sunflower Seeds - {modifier}"
                else:
                    item_name = f"{base_name} {modifier}"

                # Sum quantities across all quantity/date columns
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

                # Accumulate sales — the same flavor can appear in multiple
                # modifier sets (Ice Cream Flavor 1, 2, 3) and must be summed.
                if item_name not in rows:
                    rows[item_name] = {
                        "starting": 0,
                        "deliveries": 0,
                        "sales": 0,
                        "spoilage": 0,
                    }
                rows[item_name]["sales"] += total_qty
                _logger.debug("Modifier item: %r → sales=%d", item_name, total_qty)

    except Exception as exc:
        _logger.error("Failed to parse modifier CSV %s: %s", csv_file_path, exc)
        return {}

    _logger.info(
        "✅ Modifier CSV read complete: %d modifier items loaded from %s",
        len(rows), os.path.basename(csv_file_path),
    )
    return rows
