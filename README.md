# Concession Tracker

A Python automation project for processing concession sales exports and syncing inventory data into Google Sheets for inventory tracking and reporting.

## What it does

- Reads CSV sales export files from a Square account
- Normalizes and validates item and modifier data
- Groups product data by stand/location
- Updates Google Sheets inventory tabs with current week information
- Supports test mode and production mode spreadsheet targets
- Sends a summary email after processing

## Tech stack

- Python
- Google Sheets API
- Google service account authentication
- CSV data processing
- Tkinter desktop UI

## Project structure

- `sheets_Test.py` – main desktop app and processing workflow
- `Take_items.py` – parses incoming sales CSV files
- `Call_sheets.py` – writes data to Google Sheets
- `config.py` – spreadsheet configuration and test/production mode toggle
- `email_summary.py` – summary email generation
- `concession_data/` – sample/export data files by week and stand
- `test_*.py` – automated tests for key logic

## How it works

1. Import sales CSV files exported from Square.
2. Clean and validate item names and counts.
3. Merge modifier and sales rows where needed.
4. Update the appropriate stand tab in Google Sheets.
5. Review logs and optionally send a summary email.

## Run the app

Production mode (default):

```bash
python sheets_Test.py
```

Test mode:

```bash
CONCESSION_TEST_MODE=true python sheets_Test.py
```

## Setup requirements

- Python 3.9+
- Required Python packages:

```bash
pip install google-api-python-client google-auth
```

- A Google service account JSON credential file for Google Sheets access
- A configured spreadsheet ID in `config.py`

## Important security note

This project uses a local Google service account credential file. Do not commit or publish credentials to a public repository. Before making the repo public, remove any private credentials and rotate the service account key.

## Notes

This project was built to streamline weekly concession inventory tracking and reduce manual spreadsheet updates.
