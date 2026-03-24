from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

SPREADSHEET_ID = "13MhJ9cykz_l89PvV2KrVHHL2-TEos6JWt43dMMYFR1U"
CREDENTIALS_PATH = r"C:\Users\willi\OneDrive\Desktop\inventory_Script\Credentials-personal.json"

# Item lists from your code
TOFTS_ICE_CREAM = [
    "Vanilla", "Chocolate", "Strawberry", "Cookie Dough", "Cookies & Cream",
    "Cotton Candy", "Cookie Monster", "Mint Chip", "Peanut Butter Cup",
    "Strawberry Cheesecake", "Super Duper Scoop", "Rainbow Sherbet", "Brownie Bandit"
]

NOVELTY_ICE_CREAM = [
    "Bomb Pop", "Choco Taco", "Drumstick", "Edy's Pie", "King Cone",
    "Push Pop", "Reese's Ice Cream", "Root Beer Float", "Snickers Ice Cream Bar",
    "Sonic The Hedgehog", "Spiderman Ice Cream", "Spongebob Ice Cream",
    "Strawberry Shortcake Bar", "Twix Ice Cream Bar"
]

CANDY = [
    "Airheads 2 for $1", "Cotton Candy", "Cow Tail", "Nerds Clusters",
    "Ring Pop", "Slime Lickers", "Sour Patch Kids", "Starburst", "Swedish Fish", "Xtremes"
]

DRINKS = [
    "Bottled Water", "Coca-Cola", "Dr. Pepper", "Gatorade Blue", "Gatorade Orange",
    "Gatorade Red", "Gatorade White", "Ice + Water", "Razzberry Tea", "Root Beer",
    "Souvenir Cup", "Soda Refill $1"
]

MEALS = [
    "BBQ Pork Sandwich", "Chicken Salad Sandwich", "Chili Cheese Dog",
    "Chili Cheese Nachos", "Hot Dog", "Pizza Slice", "Pulled Pork Nachos",
    "Uncrustable", "Walking Taco", "Cup of Cheese", "Whole Jet's Pizza"
]

SNACKS = [
    "Assorted Chips", "Frozen Grapes", "Hummus and Pita Chips", "Smoothies",
    "String Cheese", "Jumbo Pickle", "Nachos & Cheese", "Soft Pretzel"
]

ALL_ITEMS = (
    [("TOFTS_ICE_CREAM", TOFTS_ICE_CREAM),
    ("NOVELTY_ICE_CREAM", NOVELTY_ICE_CREAM),
    ("CANDY", CANDY),
    ("DRINKS", DRINKS),
    ("MEALS", MEALS),
    ("SNACKS", SNACKS)]
)

# Auth
creds = Credentials.from_service_account_file(
    CREDENTIALS_PATH,
    scopes=["https://www.googleapis.com/auth/spreadsheets"]
)
service = build("sheets", "v4", credentials=creds)

# 1. Create "Template" sheet
requests = [{
    "addSheet": {
        "properties": {
            "title": "Template",
            "index": 0
        }
    }
}]

body = {"requests": requests}
service.spreadsheets().batchUpdate(spreadsheetId=SPREADSHEET_ID, body=body).execute()

# 2. Build data for the sheet
data = [["Item", "Starting", "Deliveries", "Sales", "Spoilage", "Expected", "Actual", "Scoops Used", "Tubs Used"]]

for category_name, items in ALL_ITEMS:
    data.append([category_name])  # Category header
    for item in items:
        data.append([item] + [""] * 8)  # Item with empty cells

# 3. Write data
body = {"values": data}
service.spreadsheets().values().update(
    spreadsheetId=SPREADSHEET_ID,
    range="Template!A1",
    valueInputOption="RAW",
    body=body
).execute()

print("✅ Template sheet created!")