from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# Use your actual file path
creds = Credentials.from_service_account_file(
    r"C:\Users\willi\OneDrive\Desktop\inventory_Script\Credentials-personal.json",
    scopes=["https://www.googleapis.com/auth/spreadsheets"]
)

service = build("sheets", "v4", credentials=creds)
sheet = service.spreadsheets()

# Replace this with your actual Google Sheet ID
SPREADSHEET_ID = "13MhJ9cykz_l89PvV2KrVHHL2-TEos6JWt43dMMYFR1U"

# Try reading cell A1 from the Deliveries tab
result = sheet.values().get(
    spreadsheetId=SPREADSHEET_ID,
    range="Deliveries!A1"
).execute()

print(result)