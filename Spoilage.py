from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from config import config

SPREADSHEET_ID = config.SPREADSHEET_ID
SPOILAGE_RANGE = "Spoilage!A:C"  # Date, Item, Quantity

def load_spoilage():
    """
    Reads the Spoilage sheet and returns:
    { item_name: total_spoiled }
    """

    creds = Credentials.from_service_account_file(
    r"C:\Users\willi\OneDrive\Desktop\inventory_Script\Credentials-personal.json",
    scopes=["https://www.googleapis.com/auth/spreadsheets"]
)


    service = build("sheets", "v4", credentials=creds)
    sheet = service.spreadsheets()

    result = sheet.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=SPOILAGE_RANGE
    ).execute()
    rows = result.get("values", [])

    spoilage = {}

    for row in rows[1:]:
        if len(row) < 3:
            continue

        item = row[1].strip()
        qty_str = row[2].strip()

        try:
            qty = int(qty_str)
        except ValueError:
            continue

        if item not in spoilage:
            spoilage[item] = 0

        spoilage[item] += qty

    return spoilage

