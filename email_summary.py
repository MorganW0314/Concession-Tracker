import os
import smtplib
from datetime import datetime
from email.message import EmailMessage
from typing import Dict, Iterable, List


EMAIL_SUMMARY_CATEGORIES = {
    "ICE_CREAM_TOFTS", "NOVELTIES", "FOUNTAIN_DRINKS",
    "BOTTLED_DRINKS", "FOOD", "SNACKS", "CANDY"
}

EMAIL_SUMMARY_CATEGORY_ORDER = (
    "ICE_CREAM_TOFTS",
    "NOVELTIES",
    "FOUNTAIN_DRINKS",
    "BOTTLED_DRINKS",
    "FOOD",
    "SNACKS",
    "CANDY",
)

EMAIL_CATEGORY_DISPLAY_NAMES = {
    "ICE_CREAM_TOFTS": "ICE CREAM",
    "NOVELTIES": "NOVELTIES",
    "FOUNTAIN_DRINKS": "FOUNTAIN DRINKS",
    "BOTTLED_DRINKS": "BOTTLED DRINKS",
    "FOOD": "FOOD",
    "SNACKS": "SNACKS",
    "CANDY": "CANDY",
}


def _to_number(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _read_latest_week_rows(sheet, spreadsheet_id: str, stand_name: str) -> List[dict]:
    from Call_sheets import (
        COL_ACTUAL,
        COL_EXPECTED,
        COL_SALES,
        DATA_START_ROW,
        col_letter,
        find_last_week_start_col,
        get_values,
    )

    last_week_start = find_last_week_start_col(sheet, spreadsheet_id, stand_name)
    if last_week_start == 0:
        return []

    last_col = col_letter(last_week_start + COL_ACTUAL)
    rows = get_values(sheet, spreadsheet_id, f"'{stand_name}'!A{DATA_START_ROW}:{last_col}500")
    if not rows:
        return []

    expected_idx = last_week_start + COL_EXPECTED
    sales_idx = last_week_start + COL_SALES
    actual_idx = last_week_start + COL_ACTUAL
    parsed = []
    for row in rows:
        item = row[0].strip() if row and row[0] else ""
        if not item:
            continue
        expected = _to_number(row[expected_idx]) if len(row) > expected_idx else None
        if expected is None:
            continue
        sales = _to_number(row[sales_idx]) if len(row) > sales_idx else None
        actual = _to_number(row[actual_idx]) if len(row) > actual_idx else None
        parsed.append(
            {
                "item": item,
                "sales": sales,
                "expected": expected,
                "actual": actual,
                "variance": (actual - expected) if actual is not None else None,
            }
        )
    return parsed


def _negative_from_rows(rows: List[dict]) -> List[dict]:
    return sorted(
        [r for r in rows if r["actual"] is not None and r["actual"] < r["expected"]],
        key=lambda r: r["variance"],
    )


def get_negative_variance_items(sheet, spreadsheet_id: str, stand_names: Iterable[str]) -> Dict[str, List[dict]]:
    negatives = {}
    for stand_name in stand_names:
        rows = _read_latest_week_rows(sheet, spreadsheet_id, stand_name)
        flagged = _negative_from_rows(rows)
        if flagged:
            negatives[stand_name] = flagged
    return negatives


def get_stands_with_discrepancies(stand_names: Iterable[str], negative_items: Dict[str, List[dict]]) -> Dict[str, str]:
    status = {}
    for stand_name in stand_names:
        count = len(negative_items.get(stand_name, []))
        if count:
            status[stand_name] = f"❌ {count} items flagged"
        else:
            status[stand_name] = "✅ All clear"
    return status


def _get_category_for_item(item_name: str):
    from Call_sheets import (
        _TOFTS_BASE_FLAVORS,
        NOVELTIES,
        FOUNTAIN_DRINKS,
        BOTTLED_DRINKS,
        FOOD,
        SNACKS,
        CANDY,
    )

    category_lists = {
        "ICE_CREAM_TOFTS": _TOFTS_BASE_FLAVORS,
        "NOVELTIES": NOVELTIES,
        "FOUNTAIN_DRINKS": FOUNTAIN_DRINKS,
        "BOTTLED_DRINKS": BOTTLED_DRINKS,
        "FOOD": FOOD,
        "SNACKS": SNACKS,
        "CANDY": CANDY,
    }
    for category_name, items in category_lists.items():
        if category_name in EMAIL_SUMMARY_CATEGORIES and item_name in items:
            return category_name
    return None


def _format_quantity(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:.2f}"


def _format_expected_line(item: str, expected: float, category: str) -> str:
    if category == "ICE_CREAM_TOFTS":
        from Call_sheets import SCOOPS_PER_TUB
        tubs = expected / SCOOPS_PER_TUB
        qty_text = f"{tubs:.2f} tubs expected"
    elif category == "FOUNTAIN_DRINKS":
        qty_text = f"{_format_quantity(expected)} oz expected"
    else:
        qty_text = f"{_format_quantity(expected)} expected"
    return f"  {item.ljust(24, '.')} {qty_text}"


def _get_week_label(sheet, spreadsheet_id: str, stand_names: Iterable[str]) -> str:
    from Call_sheets import HEADER_ROW, col_letter, find_last_week_start_col, get_values

    for stand_name in stand_names:
        last_week_start = find_last_week_start_col(sheet, spreadsheet_id, stand_name)
        if last_week_start == 0:
            continue
        col = col_letter(last_week_start)
        header_rows = get_values(sheet, spreadsheet_id, f"'{stand_name}'!{col}{HEADER_ROW}:{col}{HEADER_ROW}")
        if header_rows and header_rows[0] and header_rows[0][0]:
            raw_label = str(header_rows[0][0]).strip()
            if raw_label.startswith("Week of"):
                return raw_label
    return f"Week of {datetime.today().strftime('%m-%d-%Y')}"


def generate_email_body(
    stand_names: Iterable[str],
    negative_items: Dict[str, List[dict]],
    stand_rows: Dict[str, List[dict]] | None = None,
    week_label: str | None = None,
) -> str:
    from Call_sheets import SCOOPS_PER_TUB

    stand_names = list(stand_names)
    stand_rows = stand_rows or {}
    stands_status = get_stands_with_discrepancies(stand_names, negative_items)
    stands_with_discrepancies = sum(1 for stand in stand_names if stand in negative_items)
    total_flagged_items = sum(len(items) for items in negative_items.values())
    week_label = week_label or f"Week of {datetime.today().strftime('%m-%d-%Y')}"

    lines = [
        f"Weekly Inventory Summary — {week_label}",
        "",
        "Quick Overview",
        f"- Total Stands: {len(stand_names)}",
        f"- Stands with Discrepancies: {stands_with_discrepancies}",
        f"- Items with Negative Variance: {total_flagged_items}",
    ]

    for stand_name in stand_names:
        lines.extend([
            "",
            "════════════════════════════════",
            stand_name,
            "════════════════════════════════",
        ])
        category_groups = {key: [] for key in EMAIL_SUMMARY_CATEGORY_ORDER}
        for row in stand_rows.get(stand_name, []):
            expected = row.get("expected")
            actual = row.get("actual")
            if expected == 0 and (actual is None or actual == 0):
                continue
            category = _get_category_for_item(row.get("item", ""))
            if not category:
                continue
            category_groups[category].append(row)

        has_any_items = any(category_groups[c] for c in EMAIL_SUMMARY_CATEGORY_ORDER)
        if not has_any_items and stands_status[stand_name] == "✅ All clear":
            lines.append("  ✅ All clear")
            continue

        for category in EMAIL_SUMMARY_CATEGORY_ORDER:
            items = category_groups[category]
            if not items:
                continue
            lines.extend(["", EMAIL_CATEGORY_DISPLAY_NAMES.get(category, category)])
            for row in items:
                expected_line = _format_expected_line(row["item"], row["expected"], category)
                actual = row.get("actual")
                if actual is not None and actual < row["expected"]:
                    # For ice cream, convert scoops → tubs for the variance display too
                    if category == "ICE_CREAM_TOFTS":
                        variance_tubs = (actual - row["expected"]) / SCOOPS_PER_TUB
                        expected_line += f"  ⚠️  Variance: {variance_tubs:.2f} tubs"
                    else:
                        variance = actual - row["expected"]
                        expected_line += f"  ⚠️  Variance: {variance:.2f}"
                lines.append(expected_line)

    return "\n".join(lines)


def send_summary_email(
    sheet,
    spreadsheet_id: str,
    stand_names: Iterable[str],
    smtp_host: str | None = None,
    smtp_port: int | None = None,
    smtp_username: str | None = None,
    smtp_password: str | None = None,
    sender: str | None = None,
    recipient: str | None = None,
) -> bool:
    smtp_host = smtp_host or os.getenv("CONCESSION_SMTP_HOST", "")
    smtp_port = int(smtp_port or os.getenv("CONCESSION_SMTP_PORT", "587"))
    smtp_username = smtp_username or os.getenv("CONCESSION_SMTP_USERNAME", "")
    smtp_password = smtp_password or os.getenv("CONCESSION_SMTP_PASSWORD", "")
    sender = sender or os.getenv("CONCESSION_EMAIL_SENDER", "")
    recipient = recipient or os.getenv("CONCESSION_EMAIL_RECIPIENT", "")

    if not smtp_host or not sender or not recipient:
        return False

    # Support comma-separated list of recipients
    # e.g. CONCESSION_EMAIL_RECIPIENT=you@gmail.com,manager@gmail.com
    recipients = [r.strip() for r in recipient.split(",") if r.strip()]

    stand_names = list(stand_names)
    stand_rows = {stand_name: _read_latest_week_rows(sheet, spreadsheet_id, stand_name) for stand_name in stand_names}
    negative_items = {stand_name: _negative_from_rows(rows) for stand_name, rows in stand_rows.items()}
    negative_items = {stand_name: rows for stand_name, rows in negative_items.items() if rows}
    week_label = _get_week_label(sheet, spreadsheet_id, stand_names)
    body = generate_email_body(stand_names, negative_items, stand_rows=stand_rows, week_label=week_label)

    message = EmailMessage()
    message["Subject"] = f"Concession Tracker - Weekly Inventory Summary ({week_label})"
    message["From"] = sender
    message["To"] = ", ".join(recipients)
    message.set_content(body)

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as smtp:
            smtp.starttls()
            if smtp_username and smtp_password:
                smtp.login(smtp_username, smtp_password)
            smtp.send_message(message)
        return True
    except Exception:
        return False
