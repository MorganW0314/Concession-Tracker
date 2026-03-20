import csv
import os

COMBO_BREAKDOWN = {
    
    "Chili Cheese Dog Combo Meal": ["Chili Cheese Dog", "Assorted Chips", "Fountain Drink"],
    "Uncrustable Combo Meal": ["Uncrustable", "Assorted Chips", "Fountain Drink"],
    "Chicken Salad Combo Meal": ["Chicken Salad Sandwich", "Assorted Chips", "Fountain Drink"],
    "Hot Dog Combo Meal": ["Hot Dog", "Assorted Chips", "Fountain Drink"],
    "pizza Combo Meal": ["Pizza slice", "Assorted Chips", "Fountain Drink"],
    "Pulled Pork Combo": ["Chicken Tenders", "Fries", "Fountain Drink"],
}

def take_items(csv_file_path):
    csv_path = csv_file_path
    rows = {}


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
            item = (line.get("Item Name") or "").strip()

            sold_raw = (line.get("Units Sold") or "").strip()
            refunded_raw = (line.get("Units Refunded") or "").strip()


            try:
                sold = int(sold_raw) if sold_raw else 0
                refunded = int(refunded_raw) if refunded_raw else 0
            except ValueError:
                sold = refunded = 0

            net_sales = sold - refunded

            if item == "":
                continue

            if item in COMBO_BREAKDOWN:
                for comp in COMBO_BREAKDOWN[item]:
                    if comp not in rows:
                        rows[comp] = {
                            "starting": 0,
                            "deliveries": 0,
                            "sales": 0,
                            "spoilage": 0
                        }
                    rows[comp]["sales"] += net_sales
                continue  # skip adding the combo itself

            if item not in rows:
                rows[item] = {
                    "starting": 0,
                    "deliveries": 0,
                    "sales": 0,
                    "spoilage": 0
                }

            rows[item]["sales"] += net_sales
            
    # DEBUG: Print what was actually loaded from CSV
    print("\n" + "="*50)
    print("ITEMS LOADED FROM CSV:")
    print("="*50)
    for item_name, item_data in rows.items():
         print(f"  {item_name}: sales={item_data['sales']}")
    print("="*50 + "\n")

    return rows
# TEST: Call the function and see output
if __name__ == "__main__":
    rows = take_items("Bevelhymer Green")  # replace with desired stand name
    print("Done!")
    print("\n====================")
    print("FLAVOR KEYS FOUND:")
    for k in rows.keys():
        print(f"• {repr(k)}")
    print("====================\n")