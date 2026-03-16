from Take_items import take_items   # your CSV ingestion function
from Call_sheets import write_full_week
from Call_sheets import create_weekly_sheet
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials

# ------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------
CSV_PATH = r"C:\Users\willi\Downloads\item-sales-summary-2025-05-20-2025-05-27.csv"

SPREADSHEET_ID = "13MhJ9cykz_l89PvV2KrVHHL2-TEos6JWt43dMMYFR1U"
SHEET_NAME = "TEST_FORMATTING"

# ------------------------------------------------------------
# GOOGLE SHEETS AUTH
# ------------------------------------------------------------
creds = Credentials.from_service_account_file(
    r"C:\Users\willi\OneDrive\Desktop\inventory_Script\Credentials-personal.json",
    scopes=["https://www.googleapis.com/auth/spreadsheets"]
)

service = build("sheets", "v4", credentials=creds)
sheet = service.spreadsheets()

# ------------------------------------------------------------
# 1. READ CSV → rows dict
# ------------------------------------------------------------
print("Reading CSV...")
rows = take_items(CSV_PATH)
print("Parsed rows:")
print(rows)

new_sheet_name = create_weekly_sheet(service, SPREADSHEET_ID)

# ------------------------------------------------------------
# 2. WRITE FULL WEEK SHEET
# ----------------------------------------------------------
print("Writing formatted sheet...")
write_full_week(sheet, service, SPREADSHEET_ID, new_sheet_name, rows)

print("Done — check your new weekly tab!")



