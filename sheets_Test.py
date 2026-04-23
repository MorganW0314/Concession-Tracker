import os
import glob
import logging
import threading
import tkinter as tk
from tkinter import ttk, font as tkfont

from Take_items import take_items, take_modifiers   # your CSV ingestion functions
from Call_sheets import write_full_week, write_modifier_sales_to_week
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials

# ------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------
SPREADSHEET_ID = "13MhJ9cykz_l89PvV2KrVHHL2-TEos6JWt43dMMYFR1U"

CREDENTIALS_PATH = r"C:\Users\willi\OneDrive\Desktop\inventory_Script\Credentials-personal.json"

# ------------------------------------------------------------
# STANDS
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

# ------------------------------------------------------------
# GUI LOG HANDLER — writes logging records into the text widget
# ------------------------------------------------------------
class _TextWidgetHandler(logging.Handler):
    """Logging handler that appends records to a tkinter Text widget."""

    def __init__(self, text_widget):
        super().__init__()
        self._widget = text_widget

    def emit(self, record):
        msg = self.format(record) + "\n"
        self._widget.after(0, self._append, msg)

    def _append(self, msg):
        self._widget.config(state="normal")
        self._widget.insert(tk.END, msg)
        self._widget.see(tk.END)
        self._widget.config(state="disabled")


# ------------------------------------------------------------
# MAIN APPLICATION
# ------------------------------------------------------------
class ConcessionApp(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("Concession Tracker")
        self.resizable(True, True)
        self.minsize(720, 560)
        self._configure_styles()
        self._build_ui()
        self._refresh_csv_list()

    # ----------------------------------------------------------
    # Styles / fonts
    # ----------------------------------------------------------
    def _configure_styles(self):
        self._font_label   = tkfont.Font(family="Segoe UI", size=11)
        self._font_header  = tkfont.Font(family="Segoe UI", size=13, weight="bold")
        self._font_log     = tkfont.Font(family="Consolas",  size=9)
        self._font_btn     = tkfont.Font(family="Segoe UI", size=12, weight="bold")
        self._font_success = tkfont.Font(family="Segoe UI", size=12, weight="bold")

        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TCombobox", font=self._font_label, padding=4)
        style.configure("TLabel",    font=self._font_label, background="#f5f5f5")
        style.configure("TFrame",    background="#f5f5f5")

        self.configure(bg="#f5f5f5")

    # ----------------------------------------------------------
    # UI construction
    # ----------------------------------------------------------
    def _build_ui(self):
        pad = {"padx": 18, "pady": 6}

        # ── Title bar ──────────────────────────────────────────
        title_frame = ttk.Frame(self)
        title_frame.pack(fill="x", padx=18, pady=(18, 4))

        tk.Label(
            title_frame,
            text="🏟  Concession Tracker",
            font=self._font_header,
            bg="#1a3a6b",
            fg="white",
            anchor="w",
            padx=14,
            pady=10,
        ).pack(fill="x")

        # ── Selection area ─────────────────────────────────────
        sel_frame = ttk.Frame(self)
        sel_frame.pack(fill="x", **pad)
        sel_frame.columnconfigure(1, weight=1)

        ttk.Label(sel_frame, text="Stand:").grid(
            row=0, column=0, sticky="w", pady=6, padx=(0, 10)
        )
        self._stand_var = tk.StringVar()
        self._stand_combo = ttk.Combobox(
            sel_frame,
            textvariable=self._stand_var,
            values=STANDS,
            state="readonly",
            width=36,
        )
        self._stand_combo.grid(row=0, column=1, sticky="ew", pady=6)
        self._stand_combo.set(STANDS[0])

        ttk.Label(sel_frame, text="CSV File:").grid(
            row=1, column=0, sticky="w", pady=6, padx=(0, 10)
        )
        self._csv_var = tk.StringVar()
        self._csv_combo = ttk.Combobox(
            sel_frame,
            textvariable=self._csv_var,
            state="readonly",
            width=54,
        )
        self._csv_combo.grid(row=1, column=1, sticky="ew", pady=6)

        # Refresh CSV list button (small)
        ttk.Button(
            sel_frame,
            text="↻",
            width=3,
            command=self._refresh_csv_list,
        ).grid(row=1, column=2, padx=(6, 0))

        # ── RUN button ─────────────────────────────────────────
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill="x", padx=18, pady=(4, 8))

        self._run_btn = tk.Button(
            btn_frame,
            text="▶  RUN",
            font=self._font_btn,
            bg="#1a6b3a",
            fg="white",
            activebackground="#155c30",
            activeforeground="white",
            relief="flat",
            padx=24,
            pady=8,
            cursor="hand2",
            command=self._on_run,
        )
        self._run_btn.pack(side="left")

        self._status_label = tk.Label(
            btn_frame,
            text="",
            font=self._font_label,
            bg="#f5f5f5",
            fg="#444",
        )
        self._status_label.pack(side="left", padx=14)

        # ── Log output ─────────────────────────────────────────
        log_frame = ttk.Frame(self)
        log_frame.pack(fill="both", expand=True, padx=18, pady=(0, 18))

        ttk.Label(log_frame, text="Output Log").pack(anchor="w")

        text_frame = tk.Frame(log_frame, bg="#1e1e1e", bd=1, relief="sunken")
        text_frame.pack(fill="both", expand=True)

        self._log_text = tk.Text(
            text_frame,
            font=self._font_log,
            bg="#1e1e1e",
            fg="#d4d4d4",
            insertbackground="white",
            state="disabled",
            wrap="word",
            relief="flat",
            padx=8,
            pady=6,
        )
        scrollbar = ttk.Scrollbar(text_frame, command=self._log_text.yview)
        self._log_text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self._log_text.pack(side="left", fill="both", expand=True)

        # Colour tags for log levels
        self._log_text.tag_configure("WARNING",  foreground="#f0a500")
        self._log_text.tag_configure("ERROR",    foreground="#f44747")
        self._log_text.tag_configure("CRITICAL", foreground="#f44747")
        self._log_text.tag_configure("INFO",     foreground="#9cdcfe")
        self._log_text.tag_configure("SUCCESS",  foreground="#4ec94e", font=self._font_success)

        # Attach logging handler
        self._log_handler = _TextWidgetHandler(self._log_text)
        self._log_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s - %(message)s")
        )
        logging.root.addHandler(self._log_handler)
        logging.root.setLevel(logging.DEBUG)

    # ----------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------
    def _refresh_csv_list(self):
        """Re-scan ~/Downloads for CSV files and populate the combo."""
        concession_data = os.path.join(os.path.dirname(__file__), "Concession data")
        files = sorted(glob.glob(os.path.join(concession_data, "*.csv")))
        names = [os.path.basename(f) for f in files]
        self._csv_files = files
        self._csv_combo["values"] = names
        if names:
            self._csv_combo.current(0)
        else:
            self._csv_var.set("")

    def _log(self, msg, level="INFO"):
        """Append a plain message to the log widget with an optional colour tag."""
        self._log_text.after(0, self._append_log, msg, level)

    def _append_log(self, msg, level="INFO"):
        self._log_text.config(state="normal")
        self._log_text.insert(tk.END, msg + "\n", level)
        self._log_text.see(tk.END)
        self._log_text.config(state="disabled")

    def _set_status(self, msg, color="#444"):
        self._status_label.config(text=msg, fg=color)

    # ----------------------------------------------------------
    # RUN handler
    # ----------------------------------------------------------
    def _on_run(self):
        stand_name = self._stand_var.get().strip()
        csv_index  = self._csv_combo.current()

        if not stand_name:
            self._set_status("⚠  Please select a stand.", "#c0392b")
            return
        if csv_index < 0 or not self._csv_files:
            self._set_status("⚠  Please select a CSV file.", "#c0392b")
            return

        csv_file = self._csv_files[csv_index]

        # Disable controls during processing
        self._run_btn.config(state="disabled")
        self._stand_combo.config(state="disabled")
        self._csv_combo.config(state="disabled")
        self._set_status("⏳  Running…", "#1a6b3a")

        # Clear previous log
        self._log_text.config(state="normal")
        self._log_text.delete("1.0", tk.END)
        self._log_text.config(state="disabled")

        threading.Thread(
            target=self._run_processing,
            args=(stand_name, csv_file),
            daemon=True,
        ).start()

    def _run_processing(self, stand_name, csv_file):
        """Background thread: authenticate, read CSV, write to Sheets."""
        try:
            self._log(f"Processing stand: {stand_name}")
            self._log(f"Using CSV: {os.path.basename(csv_file)}")

            # Google Sheets auth
            self._log("Authenticating with Google Sheets…")
            creds = Credentials.from_service_account_file(
                CREDENTIALS_PATH,
                scopes=["https://www.googleapis.com/auth/spreadsheets"],
            )
            service = build("sheets", "v4", credentials=creds)
            sheet   = service.spreadsheets()

            # Read CSV
            self._log(f"Reading {os.path.basename(csv_file)}…")
            rows = take_items(csv_file)

            # Write item sales to a new week block
            self._log("Writing formatted sheet…")
            write_full_week(sheet, service, SPREADSHEET_ID, stand_name, rows)

            # Check for a matching modifier file and, if found, overwrite the
            # Sales cells in the week block that was just created.
            modifier_file = csv_file.replace("item-sales", "modifier-sales")
            if os.path.exists(modifier_file):
                self._log(f"Reading modifier data from {os.path.basename(modifier_file)}…")
                modifier_rows = take_modifiers(
                    modifier_file,
                    week_start_date=None,
                    week_end_date=None,
                    stand_name=stand_name,
                )
                self._log("Writing modifier sales to existing week columns")
                write_modifier_sales_to_week(
                    sheet, service, SPREADSHEET_ID, stand_name, modifier_rows,
                )
                self._log(f"Modifier sales written for {len(modifier_rows)} items.")
            else:
                self._log(f"No modifier file found (expected: {os.path.basename(modifier_file)})")

            # Success
            self.after(0, self._on_success, stand_name)

        except Exception as exc:
            logging.getLogger(__name__).error("Processing failed:", exc_info=True)
            self.after(0, self._on_error)

    def _on_success(self, stand_name):
        self._append_log(f"\n✅  Success!  Week written to '{stand_name}' tab.", "SUCCESS")
        self._set_status(f"✅  Done — check the {stand_name} tab!", "#1a6b3a")
        self._run_btn.config(state="normal")
        self._stand_combo.config(state="readonly")
        self._csv_combo.config(state="readonly")

    def _on_error(self):
        self._set_status("❌  Error — see log above.", "#c0392b")
        self._run_btn.config(state="normal")
        self._stand_combo.config(state="readonly")
        self._csv_combo.config(state="readonly")


# ------------------------------------------------------------
# ENTRY POINT
# ------------------------------------------------------------
if __name__ == "__main__":
    app = ConcessionApp()
    app.mainloop()

