import os
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, call, patch


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


_install_google_stubs()
_install_tk_stubs()

import sheets_Test  # noqa: E402


class ResolveStandFilesTests(unittest.TestCase):
    def test_picks_most_recent_sales_and_modifier_csvs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sales_old = os.path.join(tmpdir, "item-sales-old.csv")
            sales_new = os.path.join(tmpdir, "item-sales-new.csv")
            mod_old = os.path.join(tmpdir, "modifier-sales-older.csv")
            mod_new = os.path.join(tmpdir, "modifier-sales-newer.csv")

            for path in [sales_old, sales_new, mod_old, mod_new]:
                with open(path, "w", encoding="utf-8") as f:
                    f.write("header\n")  # content is irrelevant; mtime drives selection

            os.utime(sales_old, (100, 100))
            os.utime(sales_new, (200, 200))
            os.utime(mod_old, (150, 150))
            os.utime(mod_new, (300, 300))

            resolved = sheets_Test.resolve_stand_files(tmpdir)
            self.assertEqual(resolved["sales_csv"], sales_new)
            self.assertEqual(resolved["modifier_csv"], mod_new)

    def test_returns_none_sales_when_only_modifier_or_no_csv(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            modifier = os.path.join(tmpdir, "modifier-sales-only.csv")
            with open(modifier, "w", encoding="utf-8") as f:
                f.write("x")
            with open(os.path.join(tmpdir, "notes.txt"), "w", encoding="utf-8") as f:
                f.write("ignore")

            resolved = sheets_Test.resolve_stand_files(tmpdir)
            self.assertIsNone(resolved["sales_csv"])
            self.assertEqual(resolved["modifier_csv"], modifier)

        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "notes.txt"), "w", encoding="utf-8") as f:
                f.write("ignore")

            resolved = sheets_Test.resolve_stand_files(tmpdir)
            self.assertIsNone(resolved["sales_csv"])
            self.assertIsNone(resolved["modifier_csv"])


class StandFolderTests(unittest.TestCase):
    def test_ensure_stand_folders_creates_all_stand_directories(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            stands = ["PTAC", "HILLIARD2 (EAST)", "Bevelhymer Green"]
            sheets_Test.ensure_stand_folders(tmpdir, stands)
            for stand in stands:
                self.assertTrue(os.path.isdir(os.path.join(tmpdir, stand)))


class RunAllStandsTests(unittest.TestCase):
    def test_skips_missing_or_empty_and_continues_after_failure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            stands = ["MISSING", "NO_SALES", "FAILS", "WORKS"]
            os.makedirs(os.path.join(tmpdir, "NO_SALES"), exist_ok=True)
            with open(os.path.join(tmpdir, "NO_SALES", "modifier-sales-a.csv"), "w", encoding="utf-8") as f:
                f.write("x")

            os.makedirs(os.path.join(tmpdir, "FAILS"), exist_ok=True)
            fails_sales_csv = os.path.join(tmpdir, "FAILS", "sales.csv")
            with open(fails_sales_csv, "w", encoding="utf-8") as f:
                f.write("x")

            os.makedirs(os.path.join(tmpdir, "WORKS"), exist_ok=True)
            works_sales_csv = os.path.join(tmpdir, "WORKS", "sales.csv")
            with open(works_sales_csv, "w", encoding="utf-8") as f:
                f.write("x")

            def _side_effect(_sheet, _service, _spreadsheet_id, stand_name, *_args, **_kwargs):
                if stand_name == "FAILS":
                    raise RuntimeError("boom")
                return None

            with patch.object(sheets_Test, "process_stand", side_effect=_side_effect) as mock_process:
                sheet = MagicMock()
                service = MagicMock()
                summary = sheets_Test.run_all_stands(
                    sheet=sheet,
                    service=service,
                    spreadsheet_id="sheet-id",
                    stands=stands,
                    base_dir=tmpdir,
                )

            self.assertEqual(summary["succeeded"], ["WORKS"])
            self.assertEqual(
                [entry["stand"] for entry in summary["skipped"]],
                ["MISSING", "NO_SALES"],
            )
            self.assertEqual(summary["failed"][0]["stand"], "FAILS")
            self.assertEqual(summary["failed"][0]["error"], "boom")
            self.assertEqual(mock_process.call_count, 2)
            mock_process.assert_has_calls(
                [
                    call(sheet, service, "sheet-id", "FAILS", fails_sales_csv, modifier_csv=None, logger=None),
                    call(sheet, service, "sheet-id", "WORKS", works_sales_csv, modifier_csv=None, logger=None),
                ],
                any_order=False,
            )


if __name__ == "__main__":
    unittest.main()
