import os


class Config:
    """Configuration for Concession Tracker inventory system."""

    PRODUCTION_SPREADSHEET_ID = "1yd0zuFYy8m3TZa_NdH0tc7v0tPxgndzAkznVQ9XRUQ"
    TEST_SPREADSHEET_ID = "PASTE_YOUR_TEST_COPY_ID_HERE"
    USE_TEST_MODE = os.getenv("CONCESSION_TEST_MODE", "false").lower() == "true"

    @property
    def SPREADSHEET_ID(self):
        if self.USE_TEST_MODE:
            print("⚠️  RUNNING IN TEST MODE - using test spreadsheet")
            return self.TEST_SPREADSHEET_ID
        return self.PRODUCTION_SPREADSHEET_ID


config = Config()
