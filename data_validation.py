"""Data validation and audit logging module for Concession Tracker.

This module provides:
- ItemMatcher: robust fuzzy matching of item names against a canonical list,
  preventing "Cookies N Cream" / "Cookies & Cream" collisions.
- CategoryAwareItemMatcher: extends ItemMatcher to prevent cross-category
  collisions (e.g., "Cotton Candy" vs "Cotton Candy Ice Cream").
- DataValidator: checks data integrity (negatives, duplicates, variance alerts).
- AuditLogger: timestamped audit trail for all major data pipeline operations.
"""

import json
import logging
import os
from datetime import date, datetime
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Logs directory
# ---------------------------------------------------------------------------
LOGS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(LOGS_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Default variance threshold (50 % deviation flags an item for review)
# ---------------------------------------------------------------------------
DEFAULT_VARIANCE_THRESHOLD = 0.50


def _make_logger(name: str) -> logging.Logger:
    """Return a named logger writing to both stderr and a daily rotating log file."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s - %(message)s"
    )

    # Console handler (WARNING+)
    ch = logging.StreamHandler()
    ch.setLevel(logging.WARNING)
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    # Daily file handler (DEBUG+)
    log_file = os.path.join(LOGS_DIR, f"{date.today().isoformat()}.log")
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    return logger


# ---------------------------------------------------------------------------
# ItemMatcher
# ---------------------------------------------------------------------------

class ItemMatcher:
    """Fuzzy item-name matcher that prevents name-collision issues.

    Resolution order for find_match():
    1. Exact-case match.
    2. Case-insensitive exact match.
    3. Fuzzy match (SequenceMatcher ratio) above *threshold*.

    Items that fail all three levels return ``None`` and are logged as warnings.

    Example::

        matcher = ItemMatcher(["Cookies & Cream", "Vanilla", "Mint Chip"])
        matcher.find_match("Cookies N Cream")   # Returns "Cookies & Cream"
        matcher.find_match("vanilla")            # Returns "Vanilla"
        matcher.find_match("Unknown Item")       # Returns None (logged)
    """

    def __init__(self, canonical_items: List[str], threshold: float = 0.85):
        """
        Args:
            canonical_items: Authoritative list of item names.
            threshold: Minimum SequenceMatcher ratio (0–1) required to accept
                       a fuzzy match.  Default 0.85 is deliberately conservative
                       to avoid false positives.
        """
        self.canonical_items = list(canonical_items)
        self.threshold = threshold
        self._logger = _make_logger("concession.ItemMatcher")
        self._cache: Dict[str, Optional[str]] = {}

    @staticmethod
    def _normalize(name: str) -> str:
        """Lightweight normalisation: lowercase, strip, collapse whitespace."""
        return " ".join(name.lower().strip().split())

    def find_match(self, item_name: str) -> Optional[str]:
        """Return the best canonical match for *item_name*, or ``None``."""
        if item_name in self._cache:
            return self._cache[item_name]

        # 1. Exact case match
        if item_name in self.canonical_items:
            self._cache[item_name] = item_name
            return item_name

        norm_input = self._normalize(item_name)

        # 2. Case-insensitive exact match
        for canonical in self.canonical_items:
            if self._normalize(canonical) == norm_input:
                self._cache[item_name] = canonical
                return canonical

        # 3. Fuzzy match
        best_match: Optional[str] = None
        best_score = 0.0
        for canonical in self.canonical_items:
            score = SequenceMatcher(
                None, norm_input, self._normalize(canonical)
            ).ratio()
            if score > best_score:
                best_score = score
                best_match = canonical

        if best_score >= self.threshold:
            if best_score < 1.0:
                self._logger.info(
                    "Fuzzy match: %r -> %r (score=%.2f)",
                    item_name,
                    best_match,
                    best_score,
                )
            self._cache[item_name] = best_match
            return best_match

        self._logger.warning(
            "No match for %r (best candidate=%r, score=%.2f)",
            item_name,
            best_match,
            best_score,
        )
        self._cache[item_name] = None
        return None


# ---------------------------------------------------------------------------
# CategoryAwareItemMatcher
# ---------------------------------------------------------------------------

class CategoryAwareItemMatcher(ItemMatcher):
    """Category-aware fuzzy matcher that prevents cross-category collisions.

    Extends :class:`ItemMatcher` with a *category map* so that items which
    share a prefix (e.g. "Cotton Candy", "Cotton Candy Ice Cream", and
    "Cotton Candy Syrup (decimal estimate)") are matched within their expected
    category context rather than greedily matched to the highest-scoring
    canonical item regardless of category.

    When an expected category is supplied via :meth:`find_match_in_category`,
    the method:

    1. Runs the normal three-level resolution (exact → case-insensitive → fuzzy)
       *restricted to items in that category*.
    2. Falls back to the full-list resolution only when no in-category candidate
       meets the threshold.
    3. Logs every category resolution decision for the audit trail.

    When no category is known (e.g. free-form Deliveries or Spoilage tabs),
    :meth:`find_match` behaves exactly as the base :class:`ItemMatcher`.

    Example::

        category_map = CategoryAwareItemMatcher.build_category_map([
            ("TOFTS_ICE_CREAM", ["Cotton Candy Ice Cream", "Vanilla"]),
            ("CANDY", ["Cotton Candy", "Starburst"]),
        ])
        matcher = CategoryAwareItemMatcher(
            list(category_map.keys()), category_map
        )

        # Restricts to CANDY – returns "Cotton Candy", not "Cotton Candy Ice Cream"
        matcher.find_match_in_category("cotton candy", "CANDY")

        # No category constraint – uses regular fuzzy match
        matcher.find_match("cotton candy")
    """

    def __init__(
        self,
        canonical_items: List[str],
        category_map: Dict[str, str],
        threshold: float = 0.85,
    ):
        """
        Args:
            canonical_items: Authoritative list of item names (all categories).
            category_map:    Mapping of *canonical item name* → *category label*.
                             Build this with :meth:`build_category_map`.
            threshold:       Minimum SequenceMatcher ratio required to accept a
                             fuzzy match.  Default 0.85 matches the base class.
        """
        super().__init__(canonical_items, threshold)
        self.category_map: Dict[str, str] = dict(category_map)
        self._logger = _make_logger("concession.CategoryAwareItemMatcher")
        # Separate cache keyed by (item_name, category) tuples; does not
        # interfere with the parent class's str-keyed _cache.
        self._category_cache: Dict[Tuple[str, str], Optional[str]] = {}

    # ------------------------------------------------------------------
    # Class-level helpers
    # ------------------------------------------------------------------

    @staticmethod
    def build_category_map(
        category_lists: List[Tuple[str, List[str]]]
    ) -> Dict[str, str]:
        """Build a *item → category* mapping from a list of (label, items) pairs.

        Args:
            category_lists: Sequence of ``(category_label, item_names)`` pairs,
                            typically sourced from ``DEFAULT_CATEGORY_ORDER``.

        Returns:
            Dict mapping every item name to its category label.  If an item
            appears in more than one category the *last* occurrence wins (this
            mirrors sheet ordering precedence).

        Example::

            from Call_sheets import DEFAULT_CATEGORY_ORDER
            cmap = CategoryAwareItemMatcher.build_category_map(DEFAULT_CATEGORY_ORDER)
        """
        mapping: Dict[str, str] = {}
        for category_label, items in category_lists:
            for item in items:
                mapping[item] = category_label
        return mapping

    # ------------------------------------------------------------------
    # Category-restricted matching
    # ------------------------------------------------------------------

    def find_match_in_category(
        self, item_name: str, expected_category: str
    ) -> Optional[str]:
        """Return the best canonical match for *item_name* within *expected_category*.

        Resolution order:
        1. Exact-case match within the expected category.
        2. Case-insensitive exact match within the expected category.
        3. Fuzzy match above *threshold* within the expected category.
        4. If no in-category match is found, log a warning and delegate to the
           base :meth:`find_match` (all categories) so data is never silently
           lost.

        All category resolution decisions are logged.

        Args:
            item_name:         Raw item name as entered by staff.
            expected_category: Category label to restrict matching to
                               (e.g. ``"CANDY"`` or ``"TOFTS_ICE_CREAM"``).

        Returns:
            Matched canonical name, or ``None`` when no candidate meets the
            threshold in *any* category.
        """
        cache_key = (item_name, expected_category)
        if cache_key in self._category_cache:
            return self._category_cache[cache_key]

        # Items that belong to the expected category
        category_items = [
            c for c in self.canonical_items
            if self.category_map.get(c) == expected_category
        ]

        if not category_items:
            self._logger.warning(
                "Category %r has no canonical items; falling back to full-list match for %r",
                expected_category,
                item_name,
            )
            result = self.find_match(item_name)
            self._category_cache[cache_key] = result
            return result

        norm_input = self._normalize(item_name)

        # 1. Exact-case match within category
        if item_name in category_items:
            self._logger.info(
                "Category match (exact): %r -> %r (category=%r)",
                item_name, item_name, expected_category,
            )
            self._category_cache[cache_key] = item_name
            return item_name

        # 2. Case-insensitive exact match within category
        for canonical in category_items:
            if self._normalize(canonical) == norm_input:
                self._logger.info(
                    "Category match (case-insensitive): %r -> %r (category=%r)",
                    item_name, canonical, expected_category,
                )
                self._category_cache[cache_key] = canonical
                return canonical

        # 3. Fuzzy match within category
        best_match: Optional[str] = None
        best_score = 0.0
        for canonical in category_items:
            score = SequenceMatcher(
                None, norm_input, self._normalize(canonical)
            ).ratio()
            if score > best_score:
                best_score = score
                best_match = canonical

        if best_score >= self.threshold:
            if best_score < 1.0:
                self._logger.info(
                    "Category match (fuzzy): %r -> %r (score=%.2f, category=%r)",
                    item_name, best_match, best_score, expected_category,
                )
            self._category_cache[cache_key] = best_match
            return best_match

        # 4. No in-category match – fall back to full-list so data is not lost
        self._logger.warning(
            "No in-category match for %r in category %r "
            "(best in-category candidate=%r, score=%.2f); "
            "falling back to full-list match",
            item_name, expected_category, best_match, best_score,
        )
        result = self.find_match(item_name)
        if result:
            result_category = self.category_map.get(result, "<unknown>")
            self._logger.warning(
                "Cross-category resolution: %r -> %r "
                "(expected category=%r, resolved category=%r)",
                item_name, result, expected_category, result_category,
            )
        self._category_cache[cache_key] = result
        return result


# ---------------------------------------------------------------------------
# DataValidator
# ---------------------------------------------------------------------------

class DataValidator:
    """Checks data integrity: negative expected inventory, duplicate deliveries,
    and high-variance items."""

    def __init__(self, variance_threshold: float = DEFAULT_VARIANCE_THRESHOLD):
        """
        Args:
            variance_threshold: |variance| / max(|expected|, 1) above this value
                                 triggers a high-variance flag.  Default 0.50 (50 %).
        """
        self.variance_threshold = variance_threshold
        self._logger = _make_logger("concession.DataValidator")

    def flag_negative_expected(
    self, expected_totals: Dict[str, float]
    ) -> List[str]:
        """Return a list of items whose expected inventory is negative.
        
        SPECIAL HANDLING: Ice cream scoop variants (e.g., "Vanilla Double Scoop")
        are consolidated into their base flavor (e.g., "Vanilla") before checking,
        because the sheet treats all scoop variants as ONE inventory line item.
        
        Args:
            expected_totals: Mapping of item name -> expected quantity.
        
        Returns:
            List of item names with negative expected values (empty if none).
        """
        from Call_sheets import TOFTS_ICE_CREAM, normalize_flavor, SCOOP_VARIANT_TO_BASE, _TOFTS_BASE_FLAVORS

        flagged = []

        # Step 1: Consolidate ice cream flavor variants into their base flavor.
        # Some CSV variant names don't auto-normalize to their base (e.g.
        # "Cotton Candy Double Scoop" → "cotton candy" ≠ "cotton candy ice cream").
        # SCOOP_VARIANT_TO_BASE resolves those before the normalize comparison.
        consolidated = dict(expected_totals)
        items_to_remove = []

        for item in list(expected_totals.keys()):
            # Resolve special variant names to their canonical base
            canonical_item = SCOOP_VARIANT_TO_BASE.get(item, item)
            normalized_item = normalize_flavor(canonical_item)

            # Only iterate over base flavors so we always consolidate variants
            # into the canonical base (not into another variant entry).
            for base_flavor in _TOFTS_BASE_FLAVORS:
                normalized_base = normalize_flavor(base_flavor)

                if normalized_item == normalized_base:
                    # If item is not the exact base flavor itself, it's a variant
                    if item != base_flavor:
                        # Consolidate: fold variant value into base flavor
                        if base_flavor not in consolidated:
                            consolidated[base_flavor] = 0
                        consolidated[base_flavor] += expected_totals[item]
                        items_to_remove.append(item)
                    break

        # Remove variants so we only check base flavors
        for item in items_to_remove:
            if item in consolidated:
                del consolidated[item]

        # Step 2: Check consolidated totals for negatives
        for item, value in consolidated.items():
            if isinstance(value, (int, float)) and value < 0:
                self._logger.warning(
                    "NEGATIVE EXPECTED INVENTORY: %r = %s", item, value
                )
                flagged.append(item)

        return flagged

    def detect_duplicate_deliveries(
        self,
        raw_rows: List[List[str]],
        item_col: int = 1,
        date_col: int = 0,
    ) -> List[Tuple[str, str]]:
        """Detect the same (date, item) combination entered more than once.

        Args:
            raw_rows:  Data rows from the Deliveries sheet (lists of strings).
            item_col:  0-based column index for the item name field.
            date_col:  0-based column index for the date field.

        Returns:
            List of (date, item) pairs that appear more than once.
        """
        seen: Dict[Tuple[str, str], int] = {}
        duplicates: List[Tuple[str, str]] = []

        for row in raw_rows:
            if len(row) <= item_col:
                continue
            date_val = (
                row[date_col].strip() if len(row) > date_col and row[date_col] else ""
            )
            item_val = row[item_col].strip() if row[item_col] else ""
            if not item_val:
                continue

            key = (date_val, item_val)
            seen[key] = seen.get(key, 0) + 1
            if seen[key] == 2:
                self._logger.warning(
                    "DUPLICATE DELIVERY: item=%r on date=%r entered more than once",
                    item_val,
                    date_val,
                )
                duplicates.append(key)

        return duplicates

    def flag_high_variance(
        self,
        expected_totals: Dict[str, float],
        actual_totals: Dict[str, float],
    ) -> List[Tuple[str, float, float, float]]:
        """Flag items whose variance ratio exceeds *variance_threshold*.

        Args:
            expected_totals: Mapping of item name -> expected quantity.
            actual_totals:   Mapping of item name -> actual count (may be partial).

        Returns:
            List of (item, expected, actual, variance_pct) tuples.
        """
        flagged = []
        for item, expected in expected_totals.items():
            actual = actual_totals.get(item)
            if actual is None:
                continue
            variance = actual - expected
            denom = max(abs(expected), 1)
            variance_pct = abs(variance) / denom
            if variance_pct > self.variance_threshold:
                self._logger.warning(
                    "HIGH VARIANCE: %r expected=%.1f actual=%.1f "
                    "variance=%.1f (%.0f%%)",
                    item,
                    expected,
                    actual,
                    variance,
                    variance_pct * 100,
                )
                flagged.append((item, expected, actual, variance_pct))
        return flagged


# ---------------------------------------------------------------------------
# AuditLogger
# ---------------------------------------------------------------------------

class AuditLogger:
    """Records timestamped events for every major read/write in the pipeline.

    Events are written to a stand-specific JSONL file in the ``logs/`` directory.
    Each line is a self-contained JSON object with ``timestamp``, ``stand``,
    and ``event`` fields.
    """

    def __init__(self, stand_name: str):
        self.stand_name = stand_name
        self._logger = _make_logger(f"concession.audit.{stand_name}")
        self._audit_file = os.path.join(
            LOGS_DIR,
            f"{date.today().isoformat()}-audit-{stand_name}.jsonl",
        )

    def _write_event(self, event_type: str, data: dict) -> None:
        event = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "stand": self.stand_name,
            "event": event_type,
            **data,
        }
        with open(self._audit_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
        self._logger.info("EVENT %s | %s", event_type, data)

    def log_csv_read(
        self, csv_path: str, row_count: int, item_names: List[str]
    ) -> None:
        """Log the outcome of reading a Square POS CSV file."""
        self._write_event(
            "csv_read",
            {
                "csv_path": csv_path,
                "row_count": row_count,
                "items_found": item_names,
            },
        )

    def log_deliveries_read(
        self,
        deliveries: Dict[str, float],
        unmatched: List[str],
        duplicates: Optional[List[Tuple[str, str]]] = None,
    ) -> None:
        """Log deliveries that were read and any items without a canonical match."""
        self._write_event(
            "deliveries_read",
            {
                "deliveries": deliveries,
                "unmatched_items": unmatched,
                "duplicate_entries": [list(d) for d in (duplicates or [])],
            },
        )
        if unmatched:
            self._logger.warning(
                "UNMATCHED DELIVERY ITEMS (ignored): %s", unmatched
            )

    def log_spoilage_read(
        self, spoilage: Dict[str, float], unmatched: List[str]
    ) -> None:
        """Log spoilage entries and any items without a canonical match."""
        self._write_event(
            "spoilage_read",
            {"spoilage": spoilage, "unmatched_items": unmatched},
        )
        if unmatched:
            self._logger.warning(
                "UNMATCHED SPOILAGE ITEMS (ignored): %s", unmatched
            )

    def log_spoilage_backup(self, spoilage: Dict[str, float]) -> None:
        """Backup spoilage data before the sheet is cleared (crash protection)."""
        self._write_event(
            "spoilage_backup", {"spoilage_before_clear": spoilage}
        )

    def log_starting_inventory(
        self, actuals: Dict[str, int], unmatched: List[str]
    ) -> None:
        """Log last-week actuals used as this week's starting inventory."""
        self._write_event(
            "starting_inventory",
            {"actuals": actuals, "unmatched_items": unmatched},
        )
        if unmatched:
            self._logger.warning(
                "STARTING INVENTORY: items with no prior-week match "
                "(defaulting to 0): %s",
                unmatched,
            )

    def log_inventory_write(
        self,
        week_label: str,
        negative_items: List[str],
        duplicates: Optional[List[Tuple[str, str]]] = None,
    ) -> None:
        """Log the inventory write event with any data-integrity flags."""
        self._write_event(
            "inventory_write",
            {
                "week_label": week_label,
                "negative_expected_items": negative_items,
                "duplicate_deliveries": [list(d) for d in (duplicates or [])],
            },
        )

    def log_unmatched_items(self, source: str, items: List[str]) -> None:
        """Log items that could not be matched to a canonical name."""
        if items:
            self._write_event(
                "unmatched_items", {"source": source, "items": items}
            )
            self._logger.warning("UNMATCHED in %s: %s", source, items)
