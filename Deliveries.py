from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build # type: ignore
from config import config

SPREADSHEET_ID = config.SPREADSHEET_ID
DELIVERIES_RANGE = "Deliveries!A:C"  # Date, Item, Quantity

def load_deliveries():
    """
    Reads the Deliveries sheet and returns:
    { item_name: total_delivered }
    """

    # Authenticate using your service account credentials
    creds = Credentials.from_service_account_file(
    r"C:\Users\willi\OneDrive\Desktop\inventory_Script\Credentials-personal.json",
    scopes=["https://www.googleapis.com/auth/spreadsheets"]
)

    

    # Build the Sheets API client
    service = build("sheets", "v4", credentials=creds)
    sheet = service.spreadsheets()

    # Pull the values from the Deliveries tab
    result = sheet.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=DELIVERIES_RANGE
    ).execute()

    rows = result.get("values", [])

    deliveries = {}

    # Skip header row
    for row in rows[1:]:
        if len(row) < 3:
            continue

        item = row[1].strip()
        qty_str = row[2].strip()

        try:
            qty = int(qty_str)
        except ValueError:
            continue

        if item not in deliveries:
            deliveries[item] = 0

        deliveries[item] += qty

    return deliveries
