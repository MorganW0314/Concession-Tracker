import os
import glob
import logging
import threading
import traceback
import tkinter as tk
from tkinter import ttk, font as tkfont

from Take_items import take_items, take_modifiers
from Call_sheets import write_full_week, sync_stand_item_list, merge_modifier_rows
from config import config
from email_summary import send_summary_email
from googleapiclient.discovery import build  # type: ignore
from google.oauth2.service_account import Credentials

# ------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------
SPREADSHEET_ID = config.SPREADSHEET_ID

CREDENTIALS_PATH = os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or os.getenv(
    "CONCESSION_CREDENTIALS_PATH"
)
if not CREDENTIALS_PATH:
    raise ValueError(
        "Google service account credentials are not configured. Set GOOGLE_APPLICATION_CREDENTIALS or CONCESSION_CREDENTIALS_PATH."
    )
# ------------------------------------------------------------
# STANDS
# ------------------------------------------------------------
STANDS = [
    "Bevelhymer Green",
    "Bevelhymer Yellow",
    "BEXLEY",
    "HILLIARD1 (WEST)",
    "PTAC",
    "HILLIARD2 (EAST)",
    "REED ROAD",
    "TREMONT",
    "DEVON",
    "NWSC",
]

CONCESSION_DATA_DIR = os.path.join(os.path.dirname(__file__), "concession_data")


def _emit_log(logger, msg, level="INFO"):
    """Send a log message to an optional logger callback."""
    if not logger:
        return
    try:
        logger(msg, level=level)
    except TypeError:
        logger(msg)


def ensure_stand_folders(base_dir, stands):
    """Create per-stand folders under base_dir and return newly created paths."""
    created = []
    for stand_name in stands:
        folder = os.path.join(base_dir, stand_name)
        if not os.path.isdir(folder):
            os.makedirs(folder, exist_ok=True)
            created.append(folder)
    return created


def resolve_stand_files(folder):
    """Resolve newest sales and modifier CSV files in a stand folder."""
    if not os.path.isdir(folder):
        return {"sales_csv": None, "modifier_csv": None}

    csv_files = [
        os.path.join(folder, name)
        for name in os.listdir(folder)
        if name.lower().endswith(".csv")
    ]
    modifier_candidates = [
        path
        for path in csv_files
        if os.path.basename(path).lower().startswith("modifier-sales-")
    ]
    sales_candidates = [
        path
        for path in csv_files
        if not os.path.basename(path).lower().startswith("modifier-sales-")
    ]

    sales_csv = max(sales_candidates, key=os.path.getmtime) if sales_candidates else None
    modifier_csv = max(modifier_candidates, key=os.path.getmtime) if modifier_candidates else None
    return {"sales_csv": sales_csv, "modifier_csv": modifier_csv}


def process_stand(sheet, service, spreadsheet_id, stand_name, sales_csv, modifier_csv=None, logger=None):
    """Run the standard single-stand processing pipeline and write the week."""
    _emit_log(logger, f"Reading {os.path.basename(sales_csv)}…")
    rows = take_items(sales_csv)

    if modifier_csv:
        _emit_log(logger, f"Reading modifier data from {os.path.basename(modifier_csv)}…")
        modifier_rows = take_modifiers(
            modifier_csv,
            week_start_date=None,
            week_end_date=None,
            stand_name=stand_name,
        )
        merge_modifier_rows(rows, modifier_rows)
        _emit_log(logger, f"Merged modifier sales for {len(modifier_rows)} items.")
    else:
        _emit_log(logger, "No modifier-sales-*.csv file found in same folder — skipping modifier step.")

    _emit_log(logger, "Writing formatted sheet…")
    write_full_week(sheet, service, spreadsheet_id, stand_name, rows)


def run_all_stands(
    sheet,
    service,
    spreadsheet_id,
    stands,
    base_dir,
    per_stand_callback=None,
    logger=None,
):
    """Process all stands from per-stand folders and return success/skip/fail summary."""
    summary = {"succeeded": [], "skipped": [], "failed": []}

    for stand_name in stands:
        folder = os.path.join(base_dir, stand_name)
        _emit_log(logger, f"Processing {stand_name}…")
        if per_stand_callback:
            per_stand_callback(stand_name, "processing", None)

        if not os.path.isdir(folder):
            reason = "missing folder"
            summary["skipped"].append({"stand": stand_name, "reason": reason})
            _emit_log(logger, f"  ⏭ skipped — {reason}")
            if per_stand_callback:
                per_stand_callback(stand_name, "skipped", reason)
            continue

        files = resolve_stand_files(folder)
        sales_csv = files["sales_csv"]
        modifier_csv = files["modifier_csv"]
        if not sales_csv:
            reason = "no sales CSV"
            summary["skipped"].append({"stand": stand_name, "reason": reason})
            _emit_log(logger, f"  ⏭ skipped — {reason}")
            if per_stand_callback:
                per_stand_callback(stand_name, "skipped", reason)
            continue

        try:
            process_stand(
                sheet,
                service,
                spreadsheet_id,
                stand_name,
                sales_csv,
                modifier_csv=modifier_csv,
                logger=logger,
            )
            summary["succeeded"].append(stand_name)
            _emit_log(logger, "  ✓ wrote week")
            if per_stand_callback:
                per_stand_callback(stand_name, "succeeded", None)
        except Exception as exc:
            error_text = str(exc)
            summary["failed"].append({"stand": stand_name, "error": error_text})
            _emit_log(logger, f"  ✗ error: {error_text}", level="ERROR")
            _emit_log(logger, traceback.format_exc(), level="ERROR")
            if per_stand_callback:
                per_stand_callback(stand_name, "failed", error_text)

    return summary

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
        ensure_stand_folders(CONCESSION_DATA_DIR, STANDS)
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

        self._run_all_btn = tk.Button(
            btn_frame,
            text="▶ Run All Stands",
            font=self._font_btn,
            bg="#14508f",
            fg="white",
            activebackground="#114274",
            activeforeground="white",
            relief="flat",
            padx=24,
            pady=8,
            cursor="hand2",
            command=self._on_run_all,
        )
        self._run_all_btn.pack(side="left", padx=(10, 0))

        self._create_folders_btn = tk.Button(
            btn_frame,
            text="📁 Create Stand Folders",
            font=self._font_btn,
            bg="#5a5a5a",
            fg="white",
            activebackground="#474747",
            activeforeground="white",
            relief="flat",
            padx=16,
            pady=8,
            cursor="hand2",
            command=self._on_create_stand_folders,
        )
        self._create_folders_btn.pack(side="left", padx=(10, 0))

        self._sync_btn = tk.Button(
            btn_frame,
            text="🔄 Sync Item List",
            font=self._font_btn,
            bg="#2a6b6b",
            fg="white",
            activebackground="#235959",
            activeforeground="white",
            relief="flat",
            padx=24,
            pady=8,
            cursor="hand2",
            command=self._on_sync,
        )
        self._sync_btn.pack(side="left", padx=(10, 0))

        self._email_btn = tk.Button(
            btn_frame,
            text="📧 Send Summary Email",
            font=self._font_btn,
            bg="#1a3a6b",
            fg="white",
            activebackground="#17315a",
            activeforeground="white",
            relief="flat",
            padx=24,
            pady=8,
            cursor="hand2",
            command=self._on_send_summary_email,
        )
        self._email_btn.pack(side="left", padx=(10, 0))

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
        files = sorted(glob.glob(os.path.join(CONCESSION_DATA_DIR, "*.csv")))
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

    def _disable_controls(self):
        self._run_btn.config(state="disabled")
        self._run_all_btn.config(state="disabled")
        self._create_folders_btn.config(state="disabled")
        self._sync_btn.config(state="disabled")
        self._email_btn.config(state="disabled")
        self._stand_combo.config(state="disabled")
        self._csv_combo.config(state="disabled")

    def _enable_controls(self):
        self._run_btn.config(state="normal")
        self._run_all_btn.config(state="normal")
        self._create_folders_btn.config(state="normal")
        self._sync_btn.config(state="normal")
        self._email_btn.config(state="normal")
        self._stand_combo.config(state="readonly")
        self._csv_combo.config(state="readonly")

    def _clear_log(self):
        self._log_text.config(state="normal")
        self._log_text.delete("1.0", tk.END)
        self._log_text.config(state="disabled")

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
        self._disable_controls()
        self._set_status("⏳  Running…", "#1a6b3a")

        self._clear_log()

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

            folder = os.path.dirname(os.path.abspath(csv_file))
            files = resolve_stand_files(folder)
            process_stand(
                sheet,
                service,
                SPREADSHEET_ID,
                stand_name,
                csv_file,
                modifier_csv=files["modifier_csv"],
                logger=self._log,
            )

            # Success
            self.after(0, self._on_success, stand_name)

        except Exception as exc:
            logging.getLogger(__name__).error("Processing failed:", exc_info=True)
            self.after(0, self._on_error)

    def _on_create_stand_folders(self):
        created = ensure_stand_folders(CONCESSION_DATA_DIR, STANDS)
        if created:
            self._log(f"Created {len(created)} stand folder(s) under concession_data.")
        else:
            self._log("All stand folders already exist.")
        self._set_status("✅ Stand folders ready.", "#1a6b3a")

    def _on_run_all(self):
        self._disable_controls()
        self._set_status("⏳  Running all stands…", "#14508f")
        self._clear_log()
        threading.Thread(target=self._run_all_processing, daemon=True).start()

    def _run_all_processing(self):
        try:
            self._log("Authenticating with Google Sheets…")
            creds = Credentials.from_service_account_file(
                CREDENTIALS_PATH,
                scopes=["https://www.googleapis.com/auth/spreadsheets"],
            )
            service = build("sheets", "v4", credentials=creds)
            sheet = service.spreadsheets()

            summary = run_all_stands(
                sheet,
                service,
                SPREADSHEET_ID,
                STANDS,
                CONCESSION_DATA_DIR,
                logger=self._log,
            )
            self.after(0, self._on_run_all_success, summary)
        except Exception:
            logging.getLogger(__name__).error("Run all stands failed:", exc_info=True)
            self.after(0, self._on_error)

    def _on_run_all_success(self, summary):
        succeeded = summary["succeeded"]
        skipped = summary["skipped"]
        failed = summary["failed"]

        self._append_log(
            (
                f"\nSummary: {len(succeeded)} processed, "
                f"{len(skipped)} skipped, {len(failed)} failed."
            ),
            "INFO",
        )

        if succeeded:
            self._append_log(f"  Processed: {', '.join(succeeded)}", "INFO")
        if skipped:
            skipped_names = ", ".join(entry["stand"] for entry in skipped)
            self._append_log(f"  Skipped: {skipped_names}", "INFO")
        if failed:
            self._append_log("  Failed:", "ERROR")
            for entry in failed:
                self._append_log(f"    - {entry['stand']}: {entry['error']}", "ERROR")

        status_icon = "✅" if not failed else "⚠"
        self._set_status(
            f"{status_icon} {len(succeeded)} processed · {len(skipped)} skipped · {len(failed)} failed",
            "#1a6b3a" if not failed else "#c0392b",
        )
        self._enable_controls()

    def _on_send_summary_email(self):
        self._disable_controls()
        self._set_status("⏳ Sending summary email…", "#1a3a6b")
        self._log("Sending weekly inventory summary email…")
        threading.Thread(target=self._send_email_thread, daemon=True).start()

    # ----------------------------------------------------------
    # SYNC ITEM LIST handler
    # ----------------------------------------------------------
    def _on_sync(self):
        stand_name = self._stand_var.get().strip()
        if not stand_name:
            self._set_status("⚠  Please select a stand.", "#c0392b")
            return

        self._disable_controls()
        self._set_status("⏳ Syncing item list…", "#2a6b6b")
        self._log(f"Syncing item list for: {stand_name}")

        threading.Thread(
            target=self._sync_thread,
            args=(stand_name,),
            daemon=True,
        ).start()

    def _sync_thread(self, stand_name):
        """Background thread: authenticate and run sync_stand_item_list."""
        try:
            self._log("Authenticating with Google Sheets…")
            creds = Credentials.from_service_account_file(
                CREDENTIALS_PATH,
                scopes=["https://www.googleapis.com/auth/spreadsheets"],
            )
            service = build("sheets", "v4", credentials=creds)
            sheet = service.spreadsheets()

            self._log("Comparing item list against Column A…")
            result = sync_stand_item_list(sheet, service, SPREADSHEET_ID, stand_name)

            added = result.get("added", [])
            skipped = result.get("skipped", [])

            if added:
                for item in added:
                    self._log(f"  + Added: {item}")
            else:
                self._log("  No new items to add — sheet is already up to date.")

            self._log(f"Sync complete: {len(added)} added, {len(skipped)} already present.")
            self.after(0, self._on_sync_success, len(added))

        except Exception:
            logging.getLogger(__name__).error("Sync failed:", exc_info=True)
            self.after(0, self._on_sync_error)

    def _on_sync_success(self, n_added):
        self._append_log(
            f"\n✅  Sync complete — {n_added} item(s) added.", "SUCCESS"
        )
        self._set_status(f"✅ Sync complete — {n_added} items added.", "#2a6b6b")
        self._enable_controls()

    def _on_sync_error(self):
        self._set_status("❌ Sync failed — check log.", "#c0392b")
        self._enable_controls()

    def _send_email_thread(self):
        try:
            self._log("Authenticating with Google Sheets…")
            creds = Credentials.from_service_account_file(
                CREDENTIALS_PATH,
                scopes=["https://www.googleapis.com/auth/spreadsheets"],
            )
            service = build("sheets", "v4", credentials=creds)
            sheet = service.spreadsheets()

            sent = send_summary_email(
                sheet,
                SPREADSHEET_ID,
                STANDS,
            )
            if sent:
                self._log("Summary email sent successfully.", "SUCCESS")
                self.after(0, self._on_email_success)
            else:
                self._log("Summary email failed to send.", "ERROR")
                self.after(0, self._on_email_error)
        except Exception:
            logging.getLogger(__name__).error("Summary email failed:", exc_info=True)
            self._log("Summary email failed — check log.", "ERROR")
            self.after(0, self._on_email_error)

    def _on_success(self, stand_name):
        self._append_log(f"\n✅  Success!  Week written to '{stand_name}' tab.", "SUCCESS")
        self._set_status(f"✅  Done — check the {stand_name} tab!", "#1a6b3a")
        self._enable_controls()

    def _on_error(self):
        self._set_status("❌  Error — see log above.", "#c0392b")
        self._enable_controls()

    def _on_email_success(self):
        self._set_status("✅ Summary email sent!", "#1a6b3a")
        self._enable_controls()

    def _on_email_error(self):
        self._set_status("❌ Email failed — check log.", "#c0392b")
        self._enable_controls()


# ------------------------------------------------------------
# ENTRY POINT
# ------------------------------------------------------------
if __name__ == "__main__":
    app = ConcessionApp()
    app.mainloop()
