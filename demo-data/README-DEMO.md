# Demo Data – Concession Tracker Presentation Guide

Two realistic Square POS export CSV files covering back-to-back weeks of concession stand
operations. Use these files to walk an audience through the full end-to-end inventory
tracking system during a live demo.

---

## Files

| File | Dates | Purpose |
|------|-------|---------|
| `square-sales-week1-2025-06-03-to-2025-06-10.csv` | Jun 3–10, 2025 | Clean baseline week – all canonical item names |
| `square-sales-week2-2025-06-10-to-2025-06-17.csv` | Jun 10–17, 2025 | Realistic typos to showcase fuzzy matching |

---

## CSV Column Structure (matches Square POS export)

```
Item Name, Item Variation, SKU, Category,
Items Sold, Gross Sales,
Items Refunded, Refunds, Discounts & Comps, Net Sales, Tax,
Unit, Units Sold, Units Refunded
```

> The system reads **Item Name**, **Units Sold**, and **Units Refunded**.  
> All other columns are preserved for visual authenticity.

---

## Week 1 – Baseline Sales Snapshot

| Category | Notable Volumes |
|----------|-----------------|
| Ice Cream (Toft's) | Vanilla ~92 units, Cotton Candy Ice Cream ~101 units (single+double+triple combined) |
| Candy | Cotton Candy ~178 units *(distinct product from Cotton Candy Ice Cream)* |
| Meals | Pizza Slice ~349, Hot Dog ~228, Soft Pretzel ~482 |
| Drinks | Bottled Water ~225, Soda Refill $1 ~127 |
| Novelty Ice Cream | Spongebob/Spiderman/Ninja Turtles ~70–87 each |

All item names in Week 1 match the canonical names defined in `Call_sheets.py` exactly.

---

## Week 2 – Fuzzy Matching Edge Cases

Week 2 contains **intentional staff entry errors** that the system must resolve
automatically. These are exactly the kind of mistakes that occur in real operations.

| Entered in CSV | Canonical Name | Match Type |
|----------------|----------------|------------|
| ` Vanilla ` (with spaces) | `Vanilla` | **Whitespace strip** – handled by `Take_items.py` before fuzzy logic |
| `cotton candy ice cream` (all lowercase) | `Cotton Candy Ice Cream` | **Case-insensitive** match in `ItemMatcher` |
| `Cookies N Cream` | `Cookies & Cream` | **Fuzzy match** (~0.94 score) via `SequenceMatcher` |
| `Hot dog` (lowercase h) | `Hot Dog` | **Case-insensitive** match |
| `Soft pretzel` (lowercase p) | `Soft Pretzel` | **Case-insensitive** match |

### Why these matter for the presentation

- **`Cookies N Cream`** is the star fuzzy match: a plausible staff shorthand with a
  measurably high similarity score. Show the log entry:
  ```
  Fuzzy match: 'Cookies N Cream' -> 'Cookies & Cream' (score=0.94)
  ```
- **`cotton candy ice cream`** vs **`Cotton Candy`** (candy): demonstrates the
  *category-aware* matching enhancement – the system must not confuse the ice cream
  flavor with the candy product even though both contain "cotton candy".
- **` Vanilla `** (spaces): shows that even simple whitespace issues are silently handled
  before they ever reach the fuzzy matcher.

---

## Loading the Data

### Step 1 – Read Week 1 sales
```python
from Take_items import take_items

sales_w1 = take_items("demo-data/square-sales-week1-2025-06-03-to-2025-06-10.csv",
                       stand_name="MainStand")
```

### Step 2 – Push to Google Sheets (Week 1)
```python
from Call_sheets import write_full_week
# ... authenticate with Google Sheets API ...
write_full_week(sheet, service, SPREADSHEET_ID, "MainStand", sales_w1)
```

### Step 3 – Read Week 2 sales (with typos)
```python
sales_w2 = take_items("demo-data/square-sales-week2-2025-06-10-to-2025-06-17.csv",
                       stand_name="MainStand")
```

The `take_items` function applies `.strip()` to every item name, resolving any leading/
trailing whitespace automatically. The fuzzy matching in `ItemMatcher` / `CategoryAwareItemMatcher`
resolves case differences and close-but-not-exact spellings.

### Step 4 – Check the audit log
```
logs/MainStand_audit.jsonl
```

Each fuzzy match is recorded with the original value, canonical target, and confidence
score. Unmatched items are flagged with a warning so staff can correct the source data.

---

## Expected Variance Between Weeks

Because Week 2 quantities vary from Week 1, the **Variance** column in the Google Sheet
will show realistic green/red highlights:

| Item | Week 1 | Week 2 | Direction |
|------|--------|--------|-----------|
| Pizza Slice | 349 | 375 | ↑ more sold |
| Hot Dog | 228 | 194 (standalone) + 54 (combo) | mixed |
| Soft Pretzel | 482 | 510 | ↑ more sold |
| Bottled Water | 225 | 246 | ↑ more sold |
| Chili Cheese Dog | 88 | 75 | ↓ fewer sold |
| Vanilla (ice cream) | 92 | 101 | ↑ more sold |
| Cotton Candy Ice Cream | 101 | 111 | ↑ more sold |

---

## Combo Meal Expansion

`Hot Dog Combo Meal` is automatically broken into components by `Take_items.py`:

```
Hot Dog Combo Meal (55 sold – 1 refunded = 54 net)
  → Hot Dog:       +54 units
  → Assorted Chips: +54 units
  → Fountain Drink: +54 units
```

This is why `Hot Dog` shows more total units than what was sold individually.

---

## Presentation Flow

1. **Open Week 1 CSV** – point out clean data, real product names, realistic volumes
2. **Run `take_items` on Week 1** – walk through what the dict looks like
3. **Call `write_full_week`** – show the Google Sheet being created with formulas,
   colour-coded headers, variance column
4. **Open Week 2 CSV** – highlight the intentional typos in the raw data
5. **Run `take_items` on Week 2** – show that whitespace is stripped transparently
6. **Run fuzzy matching** – show `ItemMatcher.find_match()` resolving "Cookies N Cream"
   → "Cookies & Cream" with a 0.94 confidence score
7. **Show audit log** – `logs/MainStand_audit.jsonl` contains timestamped records of
   every match decision, CSV read, and any unmatched items
8. **Show Week 2 sheet** – variance column highlights items that moved up (green) or
   down (red) compared to the starting inventory

> *"Even with staff entry errors, our system intelligently resolves them, logs every
> assumption, and ensures inventory counts stay accurate. Nothing is silently lost."*

---

## Notes

- Dollar amounts use `$0.00` format to match Square's default export style.
- SKU column is left blank (common for concession items without barcodes).
- Tax is `$0.00` throughout; adjust if your jurisdiction applies food/beverage tax.
- Refund counts are small (0–3 per item) to stay realistic for a single-week window.
