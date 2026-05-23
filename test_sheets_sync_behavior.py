import sys
import types
import unittest
from unittest.mock import MagicMock, patch


def _install_google_stubs():
    google_mod = types.ModuleType("google")
    oauth2_mod = types.ModuleType("google.oauth2")
    service_account_mod = types.ModuleType("google.oauth2.service_account")

    class _Credentials:
        @staticmethod
        def from_service_account_file(*args, **kwargs):
            return object()

    service_account_mod.Credentials = _Credentials

    googleapiclient_mod = types.ModuleType("googleapiclient")
    discovery_mod = types.ModuleType("googleapiclient.discovery")

    def _build(*args, **kwargs):
        return object()

    discovery_mod.build = _build

    sys.modules.setdefault("google", google_mod)
    sys.modules.setdefault("google.oauth2", oauth2_mod)
    sys.modules.setdefault("google.oauth2.service_account", service_account_mod)
    sys.modules.setdefault("googleapiclient", googleapiclient_mod)
    sys.modules.setdefault("googleapiclient.discovery", discovery_mod)


_install_google_stubs()


def _install_tk_stubs():
    tk_mod = types.ModuleType("tkinter")
    ttk_mod = types.ModuleType("tkinter.ttk")
    font_mod = types.ModuleType("tkinter.font")

    class _Tk:
        pass

    tk_mod.Tk = _Tk
    tk_mod.END = "end"
    tk_mod.Button = object
    tk_mod.Label = object
    tk_mod.Frame = object
    tk_mod.Text = object
    tk_mod.StringVar = object
    ttk_mod.Style = object
    ttk_mod.Frame = object
    ttk_mod.Label = object
    ttk_mod.Combobox = object
    ttk_mod.Button = object
    ttk_mod.Scrollbar = object
    font_mod.Font = object

    sys.modules.setdefault("tkinter", tk_mod)
    sys.modules.setdefault("tkinter.ttk", ttk_mod)
    sys.modules.setdefault("tkinter.font", font_mod)


_install_tk_stubs()

import sheets_Test  # noqa: E402


class SyncButtonBehaviorTests(unittest.TestCase):
    def test_sync_thread_does_not_call_write_full_week(self):
        class DummyApp:
            def __init__(self):
                self.logged = []
                self.after_calls = []

            def _log(self, msg, level="INFO"):
                self.logged.append((msg, level))

            def after(self, *args):
                self.after_calls.append(args)

            def _on_sync_success(self, _n):
                pass

            def _on_sync_error(self):
                pass

        dummy = DummyApp()
        service = MagicMock()
        service.spreadsheets.return_value = MagicMock()

        with (
            patch.object(sheets_Test.Credentials, "from_service_account_file", return_value=object()),
            patch.object(sheets_Test, "build", return_value=service),
            patch.object(sheets_Test, "sync_stand_item_list", return_value={"added": [], "skipped": []}),
            patch.object(sheets_Test, "write_full_week") as mock_write_full_week,
        ):
            sheets_Test.ConcessionApp._sync_thread(dummy, "PTAC")

        mock_write_full_week.assert_not_called()


if __name__ == "__main__":
    unittest.main()
