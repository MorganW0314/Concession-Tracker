import os
import smtplib
from email.message import EmailMessage
from typing import Dict, Iterable, List


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
    actual_idx = last_week_start + COL_ACTUAL
    parsed = []
    for row in rows:
        item = row[0].strip() if row and row[0] else ""
        if not item:
            continue
        expected = _to_number(row[expected_idx]) if len(row) > expected_idx else None
        actual = _to_number(row[actual_idx]) if len(row) > actual_idx else None
        if expected is None or actual is None:
            continue
        parsed.append(
            {
                "item": item,
                "expected": expected,
                "actual": actual,
                "variance": actual - expected,
            }
        )
    return parsed


def get_negative_variance_items(sheet, spreadsheet_id: str, stand_names: Iterable[str]) -> Dict[str, List[dict]]:
    negatives = {}
    for stand_name in stand_names:
        rows = _read_latest_week_rows(sheet, spreadsheet_id, stand_name)
        flagged = [r for r in rows if r["actual"] < r["expected"]]
        if flagged:
            negatives[stand_name] = sorted(flagged, key=lambda r: r["variance"])
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


def generate_email_body(stand_names: Iterable[str], negative_items: Dict[str, List[dict]]) -> str:
    stand_names = list(stand_names)
    stands_status = get_stands_with_discrepancies(stand_names, negative_items)
    stands_with_discrepancies = sum(1 for stand in stand_names if stand in negative_items)
    total_flagged_items = sum(len(items) for items in negative_items.values())

    lines = [
        "Weekly Inventory Summary",
        "",
        "Section 1: Quick Overview",
        f"- Total Stands: {len(stand_names)}",
        f"- Stands with Discrepancies: {stands_with_discrepancies}",
        f"- Items with Negative Variance: {total_flagged_items}",
        "",
        "Section 2: Stands Status",
    ]

    for stand_name in stand_names:
        lines.append(f"- {stand_name}: {stands_status[stand_name]}")

    lines.extend(["", "Section 3: Items Flagged as Negative (Discrepancies)"])
    if not negative_items:
        lines.append("- No negative variance items detected.")
    else:
        for stand_name in stand_names:
            flagged = negative_items.get(stand_name, [])
            if not flagged:
                continue
            lines.append(f"- {stand_name}")
            for item in flagged:
                lines.append(
                    f"  • {item['item']}: Expected {item['expected']:.2f}, "
                    f"Actual {item['actual']:.2f}, Variance {item['variance']:.2f}"
                )

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

    stand_names = list(stand_names)
    negative_items = get_negative_variance_items(sheet, spreadsheet_id, stand_names)
    body = generate_email_body(stand_names, negative_items)

    message = EmailMessage()
    message["Subject"] = "Concession Tracker - Weekly Inventory Summary"
    message["From"] = sender
    message["To"] = recipient
    message.set_content(body)

    with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as smtp:
        smtp.starttls()
        if smtp_username and smtp_password:
            smtp.login(smtp_username, smtp_password)
        smtp.send_message(message)

    return True
