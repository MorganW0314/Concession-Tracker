import glob 
from Take_items import take_items   # your CSV ingestion function
from Call_sheets import write_full_week
from Call_sheets import create_weekly_sheet
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials

# ------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------
SPREADSHEET_ID = "13MhJ9cykz_l89PvV2KrVHHL2-TEos6JWt43dMMYFR1U"

CREDENTIALS_PATH = r"C:\Users\willi\OneDrive\Desktop\inventory_Script\Credentials-personal.json"

# ------------------------------------------------------------
# STAND SELECTION
# ------------------------------------------------------------
STANDS = [
    "Bevelhymer Green",
    "Bevelhymer",
    "BEXLEY",
    "HILLIARD1 (WEST)",
    "PTAC",
    "HILLIARD2 (EAST)",
    "REED ROAD",
    "TREMONT",
    "DEVON",
]

print("Which stand are you processing?")
for i, stand in enumerate(STANDS, 1):
    print(f"  {i}. {stand}")

while True:
    choice = input(f"\nEnter stand number (1-{len(STANDS)}): ").strip()
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(STANDS):
            stand_name = STANDS[idx]
            break
        else:
            print(f"Please enter a number between 1 and {len(STANDS)}.")
    except ValueError:
        print("Invalid input. Please enter a number.")

print(f"\nProcessing stand: {stand_name}")

downloads_folder = os.path.expanduser("~/Downloads")
csv_files = glob.glob(os.path.join(downloads_folder, "*.csv"))

if not csv_files:
    print("No CSV files found in Downloads!")
    exit()

print(f"\nAvailable CSV files:")
for i, file in enumerate(csv_files, 1):
    print(f"  {i}. {os.path.basename(file)}")

while True:
    choice = input(f"\nSelect CSV file (1-{len(csv_files)}): ").strip()
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(csv_files):
            csv_file = csv_files[idx]
            break
        else:
            print(f"Please enter a number between 1 and {len(csv_files)}.")
    except ValueError:
        print("Invalid input. Please enter a number.")

print(f"Using: {os.path.basename(csv_file)}\n")

# ------------------------------------------------------------
# GOOGLE SHEETS AUTH
# ------------------------------------------------------------
creds = Credentials.from_service_account_file(
    CREDENTIALS_PATH,
    scopes=["https://www.googleapis.com/auth/spreadsheets"]
)

service = build("sheets", "v4", credentials=creds)
sheet = service.spreadsheets()

# ------------------------------------------------------------
# 1. READ CSV → rows dict
# ------------------------------------------------------------
print(f"Reading purchases_{stand_name}.csv from Downloads...")
rows = take_items(csv_file)
print("Parsed rows:")
print(rows)

# ------------------------------------------------------------
# 2. CREATE WEEKLY SHEET TAB
# ------------------------------------------------------------
new_sheet_name = create_weekly_sheet(service, SPREADSHEET_ID, stand_name)

# ------------------------------------------------------------
# 3. WRITE FULL WEEK SHEET
# ------------------------------------------------------------
print("Writing formatted sheet...")
write_full_week(sheet, service, SPREADSHEET_ID, new_sheet_name, rows, stand_name)

print("Done — check your new weekly tab!")

