import os


class Config:
    """Configuration for Concession Tracker inventory system."""

    PRODUCTION_SPREADSHEET_ID = os.getenv(
        "CONCESSION_PRODUCTION_SPREADSHEET_ID",
        "PASTE_YOUR_PRODUCTION_SPREADSHEET_ID_HERE",
    )
    TEST_SPREADSHEET_ID = os.getenv(
        "CONCESSION_TEST_SPREADSHEET_ID",
        "PASTE_YOUR_TEST_SPREADSHEET_ID_HERE",
    )
    USE_TEST_MODE = os.getenv("CONCESSION_TEST_MODE", "false").lower() == "true"

    @property
    def SPREADSHEET_ID(self):
        if self.USE_TEST_MODE:
            if self.TEST_SPREADSHEET_ID == "PASTE_YOUR_TEST_SPREADSHEET_ID_HERE":
                raise ValueError(
                    "CONCESSION_TEST_MODE is enabled but CONCESSION_TEST_SPREADSHEET_ID is not configured."
                )
            print("⚠️  RUNNING IN TEST MODE - using test spreadsheet")
            return self.TEST_SPREADSHEET_ID
        if self.PRODUCTION_SPREADSHEET_ID == "PASTE_YOUR_PRODUCTION_SPREADSHEET_ID_HERE":
            raise ValueError(
                "Production spreadsheet ID is not configured. Set CONCESSION_PRODUCTION_SPREADSHEET_ID."
            )
        return self.PRODUCTION_SPREADSHEET_ID


config = Config()