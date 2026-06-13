import importlib
import os
import unittest
from unittest.mock import patch

import config as config_module


class ConfigTests(unittest.TestCase):
    def test_defaults_to_production_spreadsheet_id(self):
        with patch.dict(os.environ, {}, clear=True):
            module = importlib.reload(config_module)
            self.assertEqual(
                module.config.SPREADSHEET_ID,
                module.Config.PRODUCTION_SPREADSHEET_ID,
            )

    def test_uses_test_spreadsheet_id_when_enabled(self):
        with patch.dict(os.environ, {"CONCESSION_TEST_MODE": "true"}):
            module = importlib.reload(config_module)
            self.assertEqual(
                module.config.SPREADSHEET_ID,
                module.Config.TEST_SPREADSHEET_ID,
            )


if __name__ == "__main__":
    unittest.main()
