import os
import json
import sqlite3
from datetime import date, datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import tkinter as tk
from urllib.parse import urljoin
import webbrowser

import requests as req_lib

APP_NAME = "EMDFactoryPanel"
DEFAULT_BASE_URL = "https://paymentapproval.onrender.com"

APPROVAL_COLORS = {
    "Approved": ("#1f8a43", "#d4edda"),
    "Rejected":  ("#dc3545", "#f8d7da"),
    "Pending":   ("#0b5ed7", "#e7f0ff"),
    "Partial Approved": ("#856404", "#fff3cd"),
    "Draft":     ("#6c757d", "#f0f0f0"),
}


def normalize_approval_status(status: str | None) -> str:
    value = (status or "Pending").strip()
    if value == "Hold":
        return "Partial Approved"
    return value


def app_data_dir() -> Path:
    root = Path(os.getenv("APPDATA", str(Path.home()))) / APP_NAME
    root.mkdir(parents=True, exist_ok=True)
    return root


def db_path() -> Path:
    return app_data_dir() / "factory_cache.db"


def init_db() -> None:
    with sqlite3.connect(db_path()) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS my_requests (
                id INTEGER PRIMARY KEY,
                request_date TEXT,
                item_category TEXT,
                vendor TEXT,
                item_name TEXT,
                qty REAL,
                unit TEXT,
                rate REAL,
                gst_percent REAL,
                amount REAL,
                final_amount REAL,
                reason TEXT,
                urgent_flag INTEGER,
                requested_by TEXT,
                notes TEXT,
                vendor_id INTEGER,
                factory_id INTEGER,
                vendor_mobile TEXT,
                approval_status TEXT,
                payment_status TEXT,
                approval_remark TEXT,
                bill_image_path TEXT,
                updated_at TEXT,
                synced_at TEXT,
                prev_status TEXT
            )
            """
        )
        cols = {row[1] for row in conn.execute("PRAGMA table_info(my_requests)")}
        for col in ["prev_status", "bill_image_path", "notes", "reason", "urgent_flag",
                    "requested_by", "vendor_id", "factory_id", "vendor_mobile",
                    "qty", "unit", "rate", "gst_percent", "amount", "approval_remark",
                    "request_type", "purpose", "completion_status",
                    "vendor_bill_path", "company_voucher_path"]:
            if col not in cols:
                conn.execute(f"ALTER TABLE my_requests ADD COLUMN {col} TEXT")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS masters_cache (
                type TEXT,
                id INTEGER,
                name TEXT,
                extra TEXT,
                PRIMARY KEY (type, id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pending_uploads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                op_type TEXT NOT NULL,
                method TEXT NOT NULL,
                endpoint TEXT NOT NULL,
                data_json TEXT NOT NULL,
                file_path TEXT,
                retry_count INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        # Seed defaults so dropdowns are populated before first login
        defaults = {
            "factories":  ["Main Factory"],
            "vendors":    ["Local Supplier"],
            "categories": ["Raw Material", "Consumable", "Maintenance", "Packaging", "Utility"],
            "units":      ["pcs", "kg", "ton", "liter", "meter", "box", "nos"],
        }
        existing = {(r[0], r[1]) for r in conn.execute("SELECT type, name FROM masters_cache").fetchall()}
        for mtype, names in defaults.items():
            for i, name in enumerate(names, start=1):
                if (mtype, name) not in existing:
                    conn.execute("INSERT OR IGNORE INTO masters_cache (type,id,name,extra) VALUES (?,?,?,?)",
                                 (mtype, i, name, ""))
        conn.commit()


class FactoryLocalClient:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("EMD Group — Factory Panel")
        self.root.geometry("1280x740")
        self._apply_theme()

        self.session = req_lib.Session()
        self.base_url = tk.StringVar(value=DEFAULT_BASE_URL)
        # Lock base_url — factory panel always connects to the cloud server
        self.base_url.trace_add("write", lambda *_: self.base_url.set(DEFAULT_BASE_URL))
        self.username = tk.StringVar(value="")
        self.password = tk.StringVar(value="")
        self.status_text = tk.StringVar(value="Not logged in")
        self.conn_text = tk.StringVar(value="Offline")
        self._header_factory_var = tk.StringVar(value="Factory: Not selected")
        self._header_user_var = tk.StringVar(value="User: Guest")
        self._header_status_var = tk.StringVar(value="Status: Offline")
        self._header_sync_var = tk.StringVar(value="Last Sync: Never")
        self.auto_sync_enabled = tk.BooleanVar(value=True)
        self.logged_in = False
        self.edit_request_id: int | None = None

        self.f_date = tk.StringVar(value=str(date.today()))
        self.f_factory_id = tk.IntVar(value=0)
        self.f_factory_name = tk.StringVar(value="")
        self.f_request_type = tk.StringVar(value="Material")
        self.f_purpose = tk.StringVar(value="")
        self.f_req_amount = tk.StringVar(value="")
        self.f_remarks = tk.StringVar(value="")
        self.f_quotation_path = tk.StringVar(value="")

        self.b_vendor_name = tk.StringVar(value="")
        self.b_factory_id = tk.IntVar(value=0)
        self.b_factory_name = tk.StringVar(value="")
        self.b_file_path = tk.StringVar(value="")

        self.filt_status = tk.StringVar(value="")
        self.filt_completion = tk.StringVar(value="")
        self._dash_pending_var = tk.StringVar(value="0")
        self._dash_awaiting_var = tk.StringVar(value="0")
        self._dash_submitted_var = tk.StringVar(value="0")
        self._dash_updates_var = tk.StringVar(value="0")
        self._dash_note_var = tk.StringVar(value="No pending operational alerts")
        self._last_sync_text = "Never"

        self.factories: list[dict] = []
        self.bill_paths: dict[int, str] = {}
        self.edit_request_id: int | None = None
        self.login_bar: ttk.Frame | None = None
        self._row_tags: dict[str, tuple[str, ...]] = {}
        self._hover_item: str | None = None

        self._build_ui()
        self._refresh_combos()
        self._load_my_requests_from_cache()
        self._schedule_sync()

    def _should_retry_response(self, status_code: int) -> bool:
        # Retry only transient/server-side failures.
        return status_code in (408, 425, 429, 500, 502, 503, 504)

    def _enqueue_pending_upload(self, op_type: str, method: str, endpoint: str,
                                data: dict[str, str], file_path: str | None,
                                reason: str) -> None:
        safe_file = (file_path or "").strip()
        if safe_file and not Path(safe_file).exists():
            safe_file = ""
        now = datetime.now().isoformat(timespec="seconds")
        with sqlite3.connect(db_path()) as conn:
            conn.execute(
                """
                INSERT INTO pending_uploads (op_type, method, endpoint, data_json, file_path, retry_count, last_error, created_at)
                VALUES (?, ?, ?, ?, ?, 0, ?, ?)
                """,
                (op_type, method, endpoint, json.dumps(data), safe_file or None, reason[:500], now),
            )
            conn.commit()

    def _count_pending_uploads(self) -> int:
        with sqlite3.connect(db_path()) as conn:
            row = conn.execute("SELECT COUNT(*) FROM pending_uploads").fetchone()
        return int(row[0] or 0) if row else 0

    def _retry_pending_uploads(self) -> None:
        if not self.logged_in:
            return
        try:
            base = self._server_url()
        except RuntimeError:
            return

        with sqlite3.connect(db_path()) as conn:
            rows = conn.execute(
                """
                SELECT id, method, endpoint, data_json, file_path, retry_count
                FROM pending_uploads
                ORDER BY id ASC
                """
            ).fetchall()

        if not rows:
            return

        success_count = 0
        for row in rows:
            queue_id = int(row[0])
            method = (row[1] or "POST").upper()
            endpoint = (row[2] or "").strip()
            data_json = row[3] or "{}"
            file_path = (row[4] or "").strip()
            retry_count = int(row[5] or 0)

            try:
                data = json.loads(data_json)
            except Exception:
                data = {}

            files = None
            file_handle = None
            if file_path:
                if not Path(file_path).exists():
                    with sqlite3.connect(db_path()) as conn:
                        conn.execute("UPDATE pending_uploads SET retry_count=?, last_error=? WHERE id=?",
                                     (retry_count + 1, "Queued file not found on disk", queue_id))
                        conn.commit()
                    continue
                try:
                    file_handle = open(file_path, "rb")
                    file_key = "quotation" if endpoint == "/requests/factory" else "bill_image"
                    files = {file_key: file_handle}
                except Exception as exc:
                    with sqlite3.connect(db_path()) as conn:
                        conn.execute("UPDATE pending_uploads SET retry_count=?, last_error=? WHERE id=?",
                                     (retry_count + 1, f"File open failed: {exc}", queue_id))
                        conn.commit()
                    continue

            try:
                resp = self.session.request(method, f"{base}{endpoint}", data=data, files=files, timeout=30)
                if resp.status_code == 200:
                    with sqlite3.connect(db_path()) as conn:
                        conn.execute("DELETE FROM pending_uploads WHERE id=?", (queue_id,))
                        conn.commit()
                    success_count += 1
                else:
                    detail = f"HTTP {resp.status_code}"
                    if self._should_retry_response(resp.status_code):
                        with sqlite3.connect(db_path()) as conn:
                            conn.execute("UPDATE pending_uploads SET retry_count=?, last_error=? WHERE id=?",
                                         (retry_count + 1, detail, queue_id))
                            conn.commit()
                    else:
                        # Keep queued and keep retrying until success as requested.
                        with sqlite3.connect(db_path()) as conn:
                            conn.execute("UPDATE pending_uploads SET retry_count=?, last_error=? WHERE id=?",
                                         (retry_count + 1, detail, queue_id))
                            conn.commit()
            except Exception as exc:
                with sqlite3.connect(db_path()) as conn:
                    conn.execute("UPDATE pending_uploads SET retry_count=?, last_error=? WHERE id=?",
                                 (retry_count + 1, str(exc)[:500], queue_id))
                    conn.commit()
            finally:
                if file_handle is not None:
                    file_handle.close()

        pending_left = self._count_pending_uploads()
        if success_count > 0:
            self.status_text.set(f"Retried uploads: {success_count} sent, {pending_left} pending")
            self.sync_from_server(silent=True)

    def _apply_theme(self) -> None:
        BG, PRIMARY, WHITE = "#f3f5f7", "#1f6fbe", "#ffffff"
        style = ttk.Style(self.root)
        style.theme_use("clam")
        self.root.configure(bg=BG)
        style.configure(".", background=BG, foreground="#1f2937", font=("Segoe UI", 10))
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground="#1f2937", font=("Segoe UI", 10))
        style.configure("TLabelframe", background=BG)
        style.configure("TLabelframe.Label", background=BG, font=("Segoe UI", 10, "bold"), foreground="#1f2937")
        style.configure("TNotebook", background=BG, tabmargins=[2, 5, 2, 0])
        style.configure("TNotebook.Tab", background="#e8edf3", foreground="#334155",
                font=("Segoe UI", 10, "bold"), padding=[16, 7])
        style.map("TNotebook.Tab", background=[("selected", "#1f6fbe")], foreground=[("selected", WHITE)])
        style.configure("Treeview", background="#ffffff", fieldbackground="#ffffff",
            foreground="#111827", font=("Segoe UI", 10), rowheight=32)
        style.configure("Treeview.Heading", background="#1f6fbe", foreground=WHITE,
            font=("Segoe UI", 10, "bold"), relief="flat", borderwidth=0, padding=(10, 8))
        style.map("Treeview", background=[("selected", "#2f74d0")], foreground=[("selected", WHITE)])
        style.configure("TEntry", fieldbackground="#ffffff", foreground="#111827", font=("Segoe UI", 10), padding=5)
        style.configure("TCombobox", fieldbackground="#ffffff", foreground="#111827", font=("Segoe UI", 10))
        style.configure("TCheckbutton", background=BG, font=("Segoe UI", 10))
        style.configure("TScrollbar", background="#d1d5db", troughcolor="#eef2f7", relief="flat")

    def _refresh_header_summary(self) -> None:
        factory_name = self.f_factory_name.get().strip() or self.b_factory_name.get().strip() or "Not selected"
        user_name = self.username.get().strip() or "Guest"
        connection = self.conn_text.get().strip() or "Offline"
        self._header_factory_var.set(f"Factory: {factory_name}")
        self._header_user_var.set(f"User: {user_name}")
        self._header_status_var.set(f"Status: {connection}")
        self._header_sync_var.set(f"Last Sync: {self._last_sync_text}")

    def _collapse_login_bar(self) -> None:
        if self.login_bar is not None:
            self.login_bar.pack_forget()

    def _draw_emd_logo(self, canvas: tk.Canvas) -> None:
        canvas.create_rectangle(0, 0, 190, 65, fill="#1a3a6e", outline="")
        canvas.create_text(95, 20, text="EMD", fill="white", font=("Segoe UI", 22, "bold"), anchor="center")
        canvas.create_line(18, 32, 68, 32, fill="#c8102e", width=2)
        canvas.create_line(122, 32, 172, 32, fill="#c8102e", width=2)
        canvas.create_text(95, 44, text="Group", fill="white", font=("Segoe UI", 12, "bold"), anchor="center")
        canvas.create_rectangle(0, 55, 190, 65, fill="#c8102e", outline="")
        canvas.create_text(95, 60, text="Scaffolding & Form Work", fill="white", font=("Segoe UI", 7), anchor="center")

    def _build_ui(self) -> None:
        # ── Header bar ──────────────────────────────────────────────────────
        hdr = tk.Frame(self.root, bg="#1f6fbe", height=72)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        logo_c = tk.Canvas(hdr, width=190, height=65, bg="#1f6fbe", highlightthickness=0)
        logo_c.pack(side="left", padx=(12, 0), pady=5)
        self._draw_emd_logo(logo_c)
        title_f = tk.Frame(hdr, bg="#1f6fbe")
        title_f.pack(side="left", padx=14, pady=10)
        tk.Label(title_f, text="Factory Panel", bg="#1f6fbe", fg="white",
                 font=("Segoe UI", 18, "bold")).pack(anchor="w")
        tk.Label(title_f, text="Purchase Request Submission  —  Site / Factory",
                 bg="#1f6fbe", fg="#e8f2ff", font=("Segoe UI", 9)).pack(anchor="w")

        right_hdr = tk.Frame(hdr, bg="#1f6fbe")
        right_hdr.pack(side="right", padx=14)

        def _header_chip(parent, label_var: tk.StringVar) -> None:
            chip = tk.Frame(parent, bg="#2f7ec9", padx=10, pady=5,
                            highlightthickness=0,
                            relief="flat", bd=0)
            tk.Label(chip, textvariable=label_var, bg="#2f7ec9", fg="#ffffff",
                     font=("Segoe UI", 8, "bold")).pack()
            chip.pack(side="left", padx=4)

        _header_chip(right_hdr, self._header_factory_var)
        _header_chip(right_hdr, self._header_user_var)
        _header_chip(right_hdr, self._header_status_var)
        _header_chip(right_hdr, self._header_sync_var)

        tk.Frame(self.root, bg="#dbe2ea", height=1).pack(fill="x")

        # ── Connection / login bar ─────────────────────────────────────────
        login_bar = ttk.Frame(self.root, padding=(10, 8, 10, 6))
        login_bar.pack(fill="x")
        self.login_bar = login_bar
        ttk.Label(login_bar, text="Username").grid(row=0, column=0, sticky="w")
        ttk.Entry(login_bar, textvariable=self.username, width=20).grid(row=1, column=0, padx=(0, 8), sticky="w")
        ttk.Label(login_bar, text="Password").grid(row=0, column=1, sticky="w")
        ttk.Entry(login_bar, textvariable=self.password, show="*", width=20).grid(row=1, column=1, padx=(0, 8), sticky="w")

        def _hbtn(parent, text, cmd, bg="#1f6fbe"):
            return tk.Button(parent, text=text, command=cmd, bg=bg, fg="white",
                             font=("Segoe UI", 9, "bold"), relief="flat", cursor="hand2",
                             padx=10, pady=5, activebackground="#2b82d9", activeforeground="white",
                             bd=0, overrelief="ridge")

        _hbtn(login_bar, "\U0001f510  Login", self.login).grid(row=1, column=2, padx=(0, 6))
        _hbtn(login_bar, "\U0001f504  Sync", self.sync_from_server, "#1565a0").grid(row=1, column=3, padx=(0, 6))
        ttk.Checkbutton(login_bar, text="Auto Sync (30s)", variable=self.auto_sync_enabled).grid(
            row=1, column=4, padx=8)
        ttk.Label(login_bar, textvariable=self.status_text, foreground="#334155",
                  font=("Segoe UI", 9, "italic")).grid(row=1, column=5, padx=8, sticky="w")

        # ── Footer ────────────────────────────────────────────────────────────
        footer = tk.Frame(self.root, bg="#f3f5f7", height=22)
        footer.pack(side="bottom", fill="x")
        footer.pack_propagate(False)
        tk.Label(footer, text="Created by Daniyal  •  All Rights Reserved © 2026",
                 bg="#f3f5f7", fg="#64748b", font=("Segoe UI", 8)).pack(side="right", padx=12)

        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.notebook = nb
        self.request_frame = ttk.Frame(nb)
        self.bill_frame = ttk.Frame(nb)
        nb.add(self.request_frame, text="\U0001f4cb  Create Request")
        nb.add(self.bill_frame, text="\U0001f9fe  Simple Bill Upload")
        self._build_request_tab()
        self._build_bill_upload_tab()

    def _build_request_tab(self) -> None:
        outer = self.request_frame
        outer.columnconfigure(0, weight=0, minsize=360)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(0, weight=1)

        left = tk.Frame(outer, bg="#ffffff", padx=10, pady=10,
                highlightthickness=1, highlightbackground="#d9e0e8",
                        relief="flat", bd=0)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=2)
        left.columnconfigure(1, weight=1)
        p = {"padx": 4, "pady": 5, "sticky": "ew"}
        fw = 28

        tk.Label(left, text="Create Purchase Request", bg="#ffffff", fg="#0f172a",
                 font=("Segoe UI", 11, "bold")).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))

        REQUEST_TYPES = ["Material", "Labour", "Transport", "Service", "Utility", "Emergency"]

        r = 1
        tk.Label(left, text="Factory *", bg="#ffffff", fg="#334155", font=("Segoe UI", 9, "bold")).grid(row=r, column=0, padx=4, pady=5, sticky="w")
        self.factory_combo = ttk.Combobox(left, textvariable=self.f_factory_name, state="readonly", width=fw)
        self.factory_combo.grid(row=r, column=1, **p)
        self.factory_combo.bind("<<ComboboxSelected>>", self._on_factory_select)

        r += 1
        tk.Label(left, text="Request Type *", bg="#ffffff", fg="#334155", font=("Segoe UI", 9, "bold")).grid(row=r, column=0, padx=4, pady=5, sticky="w")
        self.type_combo = ttk.Combobox(left, textvariable=self.f_request_type,
                                       values=REQUEST_TYPES, state="readonly", width=fw)
        self.type_combo.grid(row=r, column=1, **p)

        r += 1
        tk.Label(left, text="Purpose *", bg="#ffffff", fg="#334155", font=("Segoe UI", 9, "bold")).grid(row=r, column=0, padx=4, pady=5, sticky="nw")
        self.purpose_text = tk.Text(left, height=5, width=fw + 4, bg="#ffffff", fg="#111827",
                                    insertbackground="#111827", relief="flat",
                        highlightthickness=1, highlightbackground="#cfd8e3",
                                    font=("Segoe UI", 10))
        self.purpose_text.grid(row=r, column=1, padx=4, pady=5, sticky="ew")

        r += 1
        tk.Label(left, text="Amount ₹ *", bg="#ffffff", fg="#334155", font=("Segoe UI", 9, "bold")).grid(row=r, column=0, padx=4, pady=5, sticky="w")
        ttk.Entry(left, textvariable=self.f_req_amount, width=fw).grid(row=r, column=1, **p)

        r += 1
        tk.Label(left, text="Remarks", bg="#ffffff", fg="#334155", font=("Segoe UI", 9, "bold")).grid(row=r, column=0, padx=4, pady=5, sticky="w")
        ttk.Entry(left, textvariable=self.f_remarks, width=fw).grid(row=r, column=1, **p)

        r += 1
        tk.Label(left, text="Quotation *", bg="#ffffff", fg="#334155", font=("Segoe UI", 9, "bold")).grid(row=r, column=0, padx=4, pady=5, sticky="w")
        quot_row = ttk.Frame(left)
        quot_row.grid(row=r, column=1, padx=4, pady=5, sticky="ew")
        quot_row.columnconfigure(0, weight=1)
        self.quotation_entry = ttk.Entry(quot_row, textvariable=self.f_quotation_path, state="readonly")
        self.quotation_entry.pack(side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Button(quot_row, text="Browse", command=self._browse_quotation).pack(side="left")

        r += 1
        self.req_status_var = tk.StringVar(value="")
        self.req_status_label = ttk.Label(left, textvariable=self.req_status_var,
                                          wraplength=330, justify="left")
        self.req_status_label.grid(row=r, column=0, columnspan=2, padx=4, pady=(6, 0), sticky="w")

        r += 1
        btn_row = ttk.Frame(left)
        btn_row.grid(row=r, column=0, columnspan=2, padx=4, pady=10, sticky="w")

        def _fbtn(p, t, c, bg="#1f6fbe"):
            return tk.Button(p, text=t, command=c, bg=bg, fg="white",
                             font=("Segoe UI", 9, "bold"), relief="flat", cursor="hand2",
                             padx=10, pady=5, bd=0, overrelief="ridge")

        self.submit_btn = _fbtn(btn_row, "\U0001f4e4  Submit Request", self.submit_request, "#15803d")
        self.submit_btn.pack(side="left", padx=(0, 6))
        _fbtn(btn_row, "\U0001f504  Reset", self.clear_request_form, "#64748b").pack(side="left")

        # ── My Requests section (right side) ──────────────────────────────
        right = tk.Frame(outer, bg="#ffffff", padx=8, pady=8,
                 highlightthickness=1, highlightbackground="#d9e0e8",
                 relief="flat", bd=0)
        right.grid(row=0, column=1, sticky="nsew", pady=2)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        kpi_row = tk.Frame(right, bg="#ffffff")
        kpi_row.pack(fill="x", pady=(0, 6))

        def _kpi(parent, label: str, var: tk.StringVar, bg: str, fg: str):
            card = tk.Frame(parent, bg=bg, padx=8, pady=6,
                            highlightthickness=1, highlightbackground="#d6dee8",
                            relief="flat", bd=0)
            card.pack(side="left", fill="x", expand=True, padx=(0, 6))
            tk.Label(card, text=label, bg=bg, fg="#475569", font=("Segoe UI", 8, "bold")).pack(anchor="w")
            tk.Label(card, textvariable=var, bg=bg, fg=fg, font=("Segoe UI", 12, "bold")).pack(anchor="w")

        _kpi(kpi_row, "Approved", self._dash_pending_var, "#ecfdf3", "#15803d")
        _kpi(kpi_row, "Pending", self._dash_awaiting_var, "#fff7ed", "#ea580c")
        _kpi(kpi_row, "Partial", self._dash_updates_var, "#fefce8", "#ca8a04")
        _kpi(kpi_row, "Rejected", self._dash_submitted_var, "#fff1f2", "#dc2626")

        fbar = tk.Frame(right, bg="#ffffff")
        fbar.pack(fill="x", pady=(0, 6))
        tk.Label(fbar, text="My Requests", bg="#ffffff", fg="#0f172a", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 4))
        tk.Label(fbar, text="Approval", bg="#ffffff", fg="#334155", font=("Segoe UI", 8, "bold")).grid(row=1, column=0, sticky="w")
        ttk.Combobox(fbar, textvariable=self.filt_status,
                     values=["", "Pending", "Partial Approved", "Approved", "Rejected"],
                     state="readonly", width=14).grid(row=2, column=0, padx=(0, 8), sticky="w")
        tk.Label(fbar, text="Completion", bg="#ffffff", fg="#334155", font=("Segoe UI", 8, "bold")).grid(row=1, column=1, sticky="w")
        ttk.Combobox(fbar, textvariable=self.filt_completion,
                     values=["", "Pending", "Awaiting Completion", "Completion Submitted", "Closed"],
                     state="readonly", width=18).grid(row=2, column=1, padx=(0, 8), sticky="w")
        ttk.Button(fbar, text="Search", command=self._apply_filters).grid(row=2, column=2, padx=(0, 4), sticky="w")
        ttk.Button(fbar, text="Clear", command=self._clear_filters).grid(row=2, column=3, sticky="w")

        tree_card = tk.Frame(right, bg="#ffffff", padx=0, pady=0,
                             highlightthickness=1, highlightbackground="#d9e0e8",
                     relief="flat", bd=0)
        tree_card.pack(fill="both", expand=True)

        cols = ("id", "date", "type", "purpose", "amount", "approval", "completion", "actions")
        self.tree = ttk.Treeview(tree_card, columns=cols, show="headings", height=18)
        self.tree.tag_configure("Approved",          background="#ecfdf3", foreground="#15803d")
        self.tree.tag_configure("Rejected",          background="#fff1f2", foreground="#dc2626")
        self.tree.tag_configure("Partial Approved",  background="#fefce8", foreground="#ca8a04")
        self.tree.tag_configure("Pending",           background="#fff7ed", foreground="#ea580c")
        self.tree.tag_configure("Draft",             background="#f8fafc", foreground="#64748b")
        self.tree.tag_configure("new_status",        background="#eff6ff", foreground="#1f6fbe")
        self.tree.tag_configure("awaiting_comp",     background="#eff6ff", foreground="#1f6fbe")
        for c in cols:
            self.tree.heading(c, text=c.title())
        self.tree.column("id",         width=50,  anchor="center")
        self.tree.column("date",       width=100, anchor="center")
        self.tree.column("type",       width=90,  anchor="center")
        self.tree.column("purpose",    width=220)
        self.tree.column("amount",     width=90,  anchor="e")
        self.tree.column("approval",   width=110, anchor="center")
        self.tree.column("completion", width=130, anchor="center")
        self.tree.column("actions",    width=255, anchor="center")

        vs = ttk.Scrollbar(tree_card, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")

        def _on_tree_click(event):
            region = self.tree.identify_region(event.x, event.y)
            if region != "cell":
                return
            col = self.tree.identify_column(event.x)
            col_index = int(col.replace("#", "")) - 1
            if cols[col_index] != "actions":
                return
            item = self.tree.identify_row(event.y)
            if not item:
                return
            cell_val = self.tree.set(item, "actions")
            self.tree.selection_set(item)
            self.tree.focus(item)
            if "Submit Completion" in cell_val:
                self.completion_selected()
            elif "View Documents" in cell_val or "View Docs" in cell_val:
                self.view_completion_docs(int(item))
            elif "View Bill" in cell_val or "Bill" in cell_val:
                self.view_bill_selected()
            elif "Delete" in cell_val:
                self.delete_selected()

        self.tree.bind("<ButtonRelease-1>", _on_tree_click)

    def _build_bill_upload_tab(self) -> None:
        frame = tk.Frame(self.bill_frame, bg="#ffffff", padx=14, pady=14,
                         highlightthickness=1, highlightbackground="#d9e0e8",
                         relief="flat", bd=0)
        frame.pack(fill="x", padx=20, pady=20)
        frame.columnconfigure(1, weight=1)
        p = {"padx": 6, "pady": 6, "sticky": "w"}

        tk.Label(frame, text="Upload Actual Bill", bg="#ffffff", fg="#0f172a",
                 font=("Segoe UI", 11, "bold")).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))

        r = 1
        ttk.Label(frame, text="Factory *").grid(row=r, column=0, **p)
        self.bill_factory_combo = ttk.Combobox(frame, textvariable=self.b_factory_name, state="readonly", width=30)
        self.bill_factory_combo.grid(row=r, column=1, **p)
        self.bill_factory_combo.bind("<<ComboboxSelected>>", self._on_bill_factory_select)

        r += 1
        ttk.Label(frame, text="Vendor Name *").grid(row=r, column=0, **p)
        ttk.Entry(frame, textvariable=self.b_vendor_name, width=36).grid(row=r, column=1, **p)

        r += 1
        ttk.Label(frame, text="Actual Bill Image *").grid(row=r, column=0, **p)
        ttk.Entry(frame, textvariable=self.b_file_path, state="readonly", width=44).grid(row=r, column=1, **p)
        ttk.Button(frame, text="Browse", command=self._browse_bill).grid(row=r, column=2, **p)

        r += 1
        self.bill_status_var = tk.StringVar(value="")
        self.bill_status_label = ttk.Label(frame, textvariable=self.bill_status_var, wraplength=600, justify="left")
        self.bill_status_label.grid(row=r, column=0, columnspan=3, padx=6, pady=(6, 0), sticky="w")

        r += 1
        btn_row = ttk.Frame(frame)
        btn_row.grid(row=r, column=0, columnspan=3, padx=6, pady=10, sticky="w")
        self.bill_btn = tk.Button(btn_row, text="\U0001f4e4  Upload Bill", command=self.submit_bill_upload,
                                  bg="#1f6fbe", fg="white", font=("Segoe UI", 9, "bold"),
                                  relief="flat", cursor="hand2", padx=10, pady=5, bd=0,
                                  overrelief="ridge")
        self.bill_btn.pack(side="left", padx=(0, 6))
        tk.Button(btn_row, text="\U0001f504  Reset", command=self._reset_bill_form,
                  bg="#64748b", fg="white", font=("Segoe UI", 9, "bold"),
                  relief="flat", cursor="hand2", padx=10, pady=5, bd=0,
                  overrelief="ridge").pack(side="left")

    def _on_factory_select(self, _=None) -> None:
        name = self.f_factory_name.get()
        for f in self.factories:
            if f["name"] == name:
                self.f_factory_id.set(f["id"])
                self._refresh_header_summary()
                return

    def _on_bill_factory_select(self, _=None) -> None:
        name = self.b_factory_name.get()
        for f in self.factories:
            if f["name"] == name:
                self.b_factory_id.set(f["id"])
                self._refresh_header_summary()
                return

    def _browse_bill(self) -> None:
        path = filedialog.askopenfilename(title="Select Bill Image",
            filetypes=[("Images & PDFs", "*.jpg *.jpeg *.png *.pdf"), ("All files", "*.*")])
        if path:
            self.b_file_path.set(path)

    def _browse_quotation(self) -> None:
        path = filedialog.askopenfilename(title="Select Quotation Document",
            filetypes=[("Images & PDFs", "*.jpg *.jpeg *.png *.pdf"), ("All files", "*.*")])
        if path:
            self.f_quotation_path.set(path)

    def _reset_bill_form(self) -> None:
        self.b_vendor_name.set("")
        self.b_file_path.set("")
        self.bill_status_var.set("")

    def login(self) -> None:
        base = DEFAULT_BASE_URL.rstrip("/")
        try:
            r = self.session.post(f"{base}/login",
                data={"username": self.username.get(), "password": self.password.get()},
                allow_redirects=False, timeout=20)
            if r.status_code not in (302, 303):
                self._set_conn(False)
                messagebox.showerror("Login", f"Login failed: HTTP {r.status_code}")
                return
            redirect_to = (r.headers.get("Location") or "").strip()
            if redirect_to.startswith("http"):
                try:
                    from urllib.parse import urlparse
                    redirect_to = urlparse(redirect_to).path or "/"
                except Exception:
                    redirect_to = "/"
            if redirect_to.startswith("/login"):
                self.logged_in = False
                self._set_conn(False)
                messagebox.showerror("Login", "Invalid username or password")
                return

            # Validate that the issued session cookie can access an authenticated API route.
            auth_check = self.session.get(f"{base}/requests", timeout=20)
            if auth_check.status_code != 200:
                self.logged_in = False
                self._set_conn(False)
                messagebox.showerror("Login", "Login succeeded but session validation failed. Please try again.")
                return

            self.logged_in = True
            self._set_conn(True)
            self.f_requested_by.set(self.username.get())
            self.status_text.set("Logged in successfully")
            self._collapse_login_bar()
            self._load_masters()
            self.sync_from_server(silent=True)
            self._refresh_header_summary()
            messagebox.showinfo("Login", "Logged in successfully.")
        except Exception as exc:
            self._set_conn(False)
            messagebox.showerror("Login", f"Error: {exc}")

    def _server_url(self) -> str:
        """Always returns the locked cloud server URL. Raises if something is wrong."""
        url = DEFAULT_BASE_URL.rstrip("/")
        if not url.startswith("https://"):
            raise RuntimeError(f"Refusing to submit: server URL must be HTTPS (got {url!r})")
        return url

    def _set_conn(self, online: bool) -> None:
        self.conn_text.set("Online" if online else "Offline")
        self._header_status_var.set(f"Status: {self.conn_text.get()}")

    def _load_masters(self) -> None:
        base = DEFAULT_BASE_URL.rstrip("/")
        try:
            for mtype in ("factories",):
                r = self.session.get(f"{base}/masters/{mtype}", timeout=15)
                if r.status_code != 200:
                    continue
                data = r.json().get("items", [])
                with sqlite3.connect(db_path()) as conn:
                    conn.execute("DELETE FROM masters_cache WHERE type=?", (mtype,))
                    for item in data:
                        conn.execute("INSERT OR REPLACE INTO masters_cache (type,id,name,extra) VALUES (?,?,?,?)",
                            (mtype, item.get("id", 0), item.get("name", ""), item.get("extra1") or ""))
                    conn.commit()
        except Exception:
            pass
        self._refresh_combos()

    def _refresh_combos(self) -> None:
        with sqlite3.connect(db_path()) as conn:
            rows = conn.execute("SELECT id, name FROM masters_cache WHERE type='factories' ORDER BY name").fetchall()
            self.factories = [{"id": r[0], "name": r[1]} for r in rows]
            fnames = [f["name"] for f in self.factories]
            if hasattr(self, "factory_combo"):
                self.factory_combo["values"] = fnames
            if hasattr(self, "bill_factory_combo"):
                self.bill_factory_combo["values"] = fnames
            if fnames and not self.f_factory_name.get():
                self.f_factory_name.set(fnames[0])
                self._on_factory_select()
                self.b_factory_name.set(fnames[0])
                self._on_bill_factory_select()
        self._refresh_header_summary()

    def sync_from_server(self, silent: bool = False) -> None:
        base = DEFAULT_BASE_URL.rstrip("/")
        try:
            r = self.session.get(f"{base}/requests", timeout=30)
            if r.status_code != 200:
                self._set_conn(False)
                if not silent:
                    messagebox.showerror("Sync", f"Sync failed: HTTP {r.status_code}")
                return
            items = r.json().get("items", [])
            self._save_to_db(items)
            self._load_my_requests_from_cache()
            self._set_conn(True)
            self._last_sync_text = datetime.now().strftime('%H:%M:%S')
            self.status_text.set(f"Synced {len(items)} records at {self._last_sync_text}")
            self._refresh_header_summary()
        except Exception as exc:
            self._set_conn(False)
            if not silent:
                messagebox.showerror("Sync", f"Error: {exc}")

    def _save_to_db(self, items: list[dict]) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        with sqlite3.connect(db_path()) as conn:
            for it in items:
                existing = conn.execute("SELECT approval_status FROM my_requests WHERE id=?", (it.get("id"),)).fetchone()
                prev_status = existing[0] if existing else None
                conn.execute("""
                    INSERT INTO my_requests (id,request_date,item_category,vendor,item_name,
                        qty,unit,rate,gst_percent,amount,final_amount,reason,urgent_flag,
                        requested_by,notes,vendor_id,factory_id,vendor_mobile,approval_status,
                        payment_status,approval_remark,bill_image_path,updated_at,synced_at,prev_status,
                        request_type,purpose,completion_status,vendor_bill_path,company_voucher_path)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET
                        request_date=excluded.request_date, item_category=excluded.item_category,
                        vendor=excluded.vendor, item_name=excluded.item_name, qty=excluded.qty,
                        unit=excluded.unit, rate=excluded.rate, gst_percent=excluded.gst_percent,
                        amount=excluded.amount, final_amount=excluded.final_amount,
                        reason=excluded.reason, urgent_flag=excluded.urgent_flag,
                        requested_by=excluded.requested_by, notes=excluded.notes,
                        vendor_id=excluded.vendor_id, factory_id=excluded.factory_id,
                        vendor_mobile=excluded.vendor_mobile, approval_status=excluded.approval_status,
                        payment_status=excluded.payment_status, approval_remark=excluded.approval_remark,
                        bill_image_path=excluded.bill_image_path, updated_at=excluded.updated_at,
                        synced_at=excluded.synced_at,
                        request_type=excluded.request_type, purpose=excluded.purpose,
                        completion_status=excluded.completion_status,
                        vendor_bill_path=excluded.vendor_bill_path,
                        company_voucher_path=excluded.company_voucher_path,
                        prev_status=CASE WHEN my_requests.approval_status != excluded.approval_status
                                    THEN my_requests.approval_status ELSE my_requests.prev_status END
                    """,
                    (it.get("id"), it.get("request_date"), it.get("item_category"),
                     it.get("vendor"), it.get("item_name"), it.get("qty"), it.get("unit"),
                     it.get("rate"), it.get("gst_percent"), it.get("amount"), it.get("final_amount"),
                     it.get("reason"), 1 if it.get("urgent_flag") else 0, it.get("requested_by"),
                     it.get("notes"), it.get("vendor_id"), it.get("factory_id"), it.get("vendor_mobile"),
                     it.get("approval_status"), it.get("payment_status"), it.get("approval_remark"),
                     it.get("bill_image_path"), it.get("updated_at"), now, prev_status,
                     it.get("request_type") or it.get("item_category"),
                     it.get("purpose") or it.get("item_name"),
                     it.get("completion_status") or "Pending",
                     it.get("vendor_bill_path"), it.get("company_voucher_path")))
            conn.commit()

    def _load_my_requests_from_cache(self) -> None:
        self.bill_paths.clear()
        self._row_tags.clear()
        for row in self.tree.get_children():
            self.tree.delete(row)

        filt_status     = self.filt_status.get().strip()
        filt_completion = self.filt_completion.get().strip()

        status_changed = []
        with sqlite3.connect(db_path()) as conn:
            rows = conn.execute("""
                SELECT id, request_date, request_type, purpose, final_amount,
                       approval_status, completion_status, bill_image_path, prev_status, approval_remark,
                       vendor_bill_path, company_voucher_path
                FROM my_requests ORDER BY id DESC
            """).fetchall()

        approved_count = 0
        awaiting_count = 0
        submitted_count = 0
        pending_count = 0
        for r_all in rows:
            st = normalize_approval_status(r_all[5])
            comp = r_all[6] or "Pending"
            if st == "Approved":
                approved_count += 1
            if comp == "Awaiting Completion":
                awaiting_count += 1
            if comp == "Completion Submitted":
                submitted_count += 1
            if st in ("Pending", "Draft"):
                pending_count += 1

        for r in rows:
            req_id = int(r[0])
            approval_status    = normalize_approval_status(r[5])
            completion_status  = r[6] or "Pending"
            prev_status = normalize_approval_status(r[8]) if r[8] is not None else None
            self.bill_paths[req_id] = r[7] or ""
            vendor_bill_path     = r[10] or ""
            company_voucher_path = r[11] or ""

            if filt_status and approval_status != filt_status:
                continue
            if filt_completion and completion_status != filt_completion:
                continue

            changed = prev_status is not None and prev_status != approval_status
            if changed:
                status_changed.append((req_id, prev_status, approval_status, r[3], r[9]))

            actions = []
            if approval_status in ("Pending", "Draft"):
                actions.append("[Delete]")
            if completion_status == "Awaiting Completion":
                actions.append("[Submit Completion]")
            if vendor_bill_path or company_voucher_path:
                actions.append("[View Docs]")
            elif self.bill_paths[req_id]:
                actions.append("[Bill]")

            req_type = r[2] or ""
            purpose  = r[3] or ""
            row_vals = (req_id, r[1], req_type, purpose[:40],
                        f"{float(r[4]):.2f}" if r[4] else "0.00",
                        approval_status, completion_status, "  ".join(actions))
            tag = "new_status" if changed else ("awaiting_comp" if completion_status == "Awaiting Completion" else approval_status)
            self.tree.insert("", "end", values=row_vals, tags=(tag,), iid=str(req_id))

        if status_changed:
            self._notify_status_changes(status_changed)

        if hasattr(self, "_dash_pending_var"):
            self._dash_pending_var.set(str(approved_count))
            self._dash_awaiting_var.set(str(pending_count))
            self._dash_submitted_var.set(str(submitted_count))
            self._dash_updates_var.set(str(awaiting_count))
            if awaiting_count > 0:
                self._dash_note_var.set(f"{awaiting_count} request(s) waiting for completion proof")
            elif pending_count > 0:
                self._dash_note_var.set(f"{pending_count} request(s) pending approval")
            else:
                self._dash_note_var.set("No pending operational alerts")
            self._refresh_header_summary()

        badge = len(status_changed)
        label = "Create Request" + (f" ({badge} updates)" if badge else "")
        if hasattr(self, "notebook") and self.notebook:
            self.notebook.tab(self.request_frame, text=label)

    def _apply_filters(self) -> None:
        self._load_my_requests_from_cache()

    def _clear_filters(self) -> None:
        self.filt_status.set("")
        self.filt_completion.set("")
        self._load_my_requests_from_cache()

    def _notify_status_changes(self, changes: list) -> None:
        for req_id, old_s, new_s, item_name, remark in changes:
            msg = f"Request #{req_id} ({item_name or 'Item'})\nStatus: {old_s} -> {new_s}"
            if remark:
                msg += f"\nRemark: {remark}"
            self.root.after(0, lambda m=msg: messagebox.showinfo("Status Update!", m))
            with sqlite3.connect(db_path()) as conn:
                conn.execute("UPDATE my_requests SET prev_status=approval_status WHERE id=?", (req_id,))
                conn.commit()

    def submit_request(self) -> None:
        self._do_submit()

    def _do_submit(self) -> None:
        if not self.logged_in:
            messagebox.showerror("Error", "Please login first.")
            return
        try:
            base = self._server_url()
        except RuntimeError as exc:
            messagebox.showerror("Security Error", str(exc))
            return
        if self.f_factory_id.get() <= 0:
            self._req_status("Select a factory.", error=True); return
        if not self.f_request_type.get().strip():
            self._req_status("Select a request type.", error=True); return
        purpose = self.purpose_text.get("1.0", "end").strip()
        if not purpose:
            self._req_status("Purpose is required.", error=True); return
        amt_str = self.f_req_amount.get().strip()
        try:
            amount = float(amt_str)
            if amount <= 0:
                raise ValueError
        except ValueError:
            self._req_status("Amount must be a positive number.", error=True); return

        quotation_path = self.f_quotation_path.get().strip()
        if not quotation_path:
            self._req_status("Quotation document is required. Please browse and select a file.", error=True); return
        if not Path(quotation_path).exists():
            self._req_status("Selected quotation file no longer exists. Please browse again.", error=True); return

        data = {
            "factory_id": str(self.f_factory_id.get()),
            "request_type": self.f_request_type.get().strip(),
            "purpose": purpose,
            "amount": str(amount),
        }
        remarks = self.f_remarks.get().strip()
        if remarks:
            data["remarks"] = remarks

        self.submit_btn.config(state="disabled")
        self._req_status("Submitting, please wait...", error=False)
        file_handle = None
        try:
            file_handle = open(quotation_path, "rb")
            files = {"quotation": file_handle}
            r = self.session.post(f"{base}/requests/factory", data=data, files=files, timeout=30)
            body = r.json() if r.headers.get("Content-Type", "").startswith("application/json") else {}
            if r.status_code != 200:
                detail = body.get("detail", f"HTTP {r.status_code}")
                if isinstance(detail, list):
                    detail = detail[0].get("msg", str(detail))
                if self._should_retry_response(r.status_code):
                    self._enqueue_pending_upload("request", "POST", "/requests/factory", data, None, str(detail))
                    self._req_status("Offline queue: request saved locally and will retry automatically.", error=False)
                    self.clear_request_form()
                else:
                    self._req_status(str(detail), error=True)
            else:
                self._req_status(f"✓ {body.get('message', 'Request submitted!')}", error=False)
                self.clear_request_form()
                self.sync_from_server(silent=True)
        except Exception as exc:
            self._enqueue_pending_upload("request", "POST", "/requests/factory", data, quotation_path, str(exc))
            self._req_status("Offline queue: request saved locally and will retry automatically.", error=False)
            self.clear_request_form()
        finally:
            if file_handle is not None:
                file_handle.close()
            self.submit_btn.config(state="normal")

    def completion_selected(self) -> None:
        item = self.tree.focus()
        if not item:
            messagebox.showwarning("Select", "Select a request to submit completion."); return
        req_id = int(item)
        with sqlite3.connect(db_path()) as conn:
            row = conn.execute("SELECT completion_status FROM my_requests WHERE id=?", (req_id,)).fetchone()
        if not row:
            messagebox.showerror("Error", "Request not found. Sync first."); return
        comp_status = row[0] or "Pending"
        if comp_status != "Awaiting Completion":
            messagebox.showwarning("Completion", f"Cannot submit completion: status is '{comp_status}'.\n"
                                   "Only requests with 'Awaiting Completion' status can be submitted."); return
        self.open_completion_dialog(req_id)

    def open_completion_dialog(self, req_id: int) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Submit Completion — Request #{req_id}")
        dialog.geometry("540x560")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()

        vendor_bill_var  = tk.StringVar(value="")
        voucher_var      = tk.StringVar(value="")

        # ── Autofill summary ──────────────────────────────────────────────
        summary_frame = ttk.LabelFrame(dialog, text="Request Summary", padding=8)
        summary_frame.pack(fill="x", padx=14, pady=(12, 0))
        grid = summary_frame
        lbl_style = {"font": ("Segoe UI", 9, "bold"), "foreground": "#555"}
        val_style = {"font": ("Segoe UI", 10, "bold"), "foreground": "#1a1a1a"}

        req_no_val    = tk.StringVar(value=f"#{req_id}")
        req_type_val  = tk.StringVar(value="…")
        purpose_val   = tk.StringVar(value="…")
        requested_val = tk.StringVar(value="…")
        approved_val  = tk.StringVar(value="…")

        for row_idx, (lbl, var) in enumerate([
            ("Request No",       req_no_val),
            ("Type",             req_type_val),
            ("Purpose",          purpose_val),
            ("Requested (₹)",   requested_val),
            ("Approved (₹)",    approved_val),
        ]):
            tk.Label(grid, text=lbl, **lbl_style).grid(row=row_idx, column=0, sticky="w", padx=(4, 8), pady=1)
            tk.Label(grid, textvariable=var, **val_style).grid(row=row_idx, column=1, sticky="w", pady=1)

        # ── Completion Remark ─────────────────────────────────────────────
        ttk.Label(dialog, text="Completion Remark *", font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=14, pady=(12, 2))
        remark_box = tk.Text(dialog, height=4, wrap="word")
        remark_box.pack(fill="x", padx=14)

        # ── Document Upload ───────────────────────────────────────────────
        doc_frame = ttk.LabelFrame(dialog, text="Documents (at least ONE required)", padding=8)
        doc_frame.pack(fill="x", padx=14, pady=(10, 0))

        ttk.Label(doc_frame, text="Vendor Bill (optional):", font=("Segoe UI", 9, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 4))
        vb_row = ttk.Frame(doc_frame)
        vb_row.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        doc_frame.columnconfigure(0, weight=1)
        vb_row.columnconfigure(0, weight=1)
        ttk.Entry(vb_row, textvariable=vendor_bill_var, state="readonly").pack(side="left", fill="x", expand=True, padx=(0, 4))
        def _browse_vendor_bill():
            p = filedialog.askopenfilename(title="Select Vendor Bill",
                filetypes=[("Images & PDFs", "*.jpg *.jpeg *.png *.pdf"), ("All", "*.*")])
            if p: vendor_bill_var.set(p)
        ttk.Button(vb_row, text="Browse", command=_browse_vendor_bill).pack(side="left")

        ttk.Label(doc_frame, text="Company Voucher (optional):", font=("Segoe UI", 9, "bold")).grid(row=2, column=0, sticky="w", pady=(4, 4))
        cv_row = ttk.Frame(doc_frame)
        cv_row.grid(row=3, column=0, sticky="ew")
        cv_row.columnconfigure(0, weight=1)
        ttk.Entry(cv_row, textvariable=voucher_var, state="readonly").pack(side="left", fill="x", expand=True, padx=(0, 4))
        def _browse_voucher():
            p = filedialog.askopenfilename(title="Select Company Voucher",
                filetypes=[("Images & PDFs", "*.jpg *.jpeg *.png *.pdf"), ("All", "*.*")])
            if p: voucher_var.set(p)
        ttk.Button(cv_row, text="Browse", command=_browse_voucher).pack(side="left")

        # ── Status label ──────────────────────────────────────────────────
        status_var = tk.StringVar(value="")
        status_lbl = ttk.Label(dialog, textvariable=status_var, wraplength=490, justify="left")
        status_lbl.pack(fill="x", padx=14, pady=(8, 0))

        # ── Autofill from server ──────────────────────────────────────────
        def _load_autofill():
            try:
                base = DEFAULT_BASE_URL.rstrip("/")
                r = self.session.get(f"{base}/requests/{req_id}/detail", timeout=10)
                if r.status_code == 200:
                    d = r.json()
                    req_type_val.set(d.get("request_type") or d.get("item_category") or "—")
                    purpose_val.set((d.get("purpose") or d.get("item_name") or "—")[:60])
                    requested_val.set(f"₹{float(d.get('final_amount') or 0):.2f}")
                    approved_val.set(f"₹{float(d.get('approved_amount') or d.get('final_amount') or 0):.2f}")
            except Exception:
                pass
        import threading
        threading.Thread(target=_load_autofill, daemon=True).start()

        # ── Submit ────────────────────────────────────────────────────────
        def on_submit() -> None:
            remark = remark_box.get("1.0", "end").strip()
            if not remark:
                status_var.set("Completion remark is required.")
                status_lbl.configure(foreground="#b02a37"); return

            vb_path = vendor_bill_var.get().strip()
            cv_path = voucher_var.get().strip()
            if not vb_path and not cv_path:
                status_var.set("Please upload Vendor Bill or Company Voucher before submitting completion.")
                status_lbl.configure(foreground="#b02a37"); return

            if not self.logged_in:
                status_var.set("Please login first.")
                status_lbl.configure(foreground="#b02a37"); return
            try:
                base = self._server_url()
            except RuntimeError as exc:
                status_var.set(str(exc))
                status_lbl.configure(foreground="#b02a37"); return

            data = {"completion_remark": remark}
            files = {}
            file_handles = []
            try:
                if vb_path and Path(vb_path).exists():
                    fh = open(vb_path, "rb")
                    file_handles.append(fh)
                    files["vendor_bill"] = fh
                if cv_path and Path(cv_path).exists():
                    fh2 = open(cv_path, "rb")
                    file_handles.append(fh2)
                    files["company_voucher"] = fh2

                status_var.set("Submitting…")
                status_lbl.configure(foreground="#555")
                r = self.session.post(f"{base}/requests/{req_id}/complete",
                                      data=data, files=files or None, timeout=30)
                body = r.json() if r.headers.get("Content-Type", "").startswith("application/json") else {}
                if r.status_code == 200:
                    status_var.set(f"✓ {body.get('message', 'Completion submitted!')}")
                    status_lbl.configure(foreground="#1f8a43")
                    self.sync_from_server(silent=True)
                    self.root.after(1000, dialog.destroy)
                else:
                    detail = body.get("detail", f"HTTP {r.status_code}")
                    if isinstance(detail, list): detail = detail[0].get("msg", str(detail))
                    status_var.set(str(detail))
                    status_lbl.configure(foreground="#b02a37")
            except Exception as exc:
                status_var.set(f"Error: {exc}")
                status_lbl.configure(foreground="#b02a37")
            finally:
                for fh in file_handles:
                    fh.close()

        btn_row = ttk.Frame(dialog)
        btn_row.pack(fill="x", padx=14, pady=12)
        ttk.Button(btn_row, text="Cancel", command=dialog.destroy).pack(side="right", padx=(6, 0))
        ttk.Button(btn_row, text="Submit Completion", command=on_submit).pack(side="right")
        dialog.wait_window()

    def delete_selected(self) -> None:
        item = self.tree.focus()
        if not item:
            messagebox.showwarning("Select", "Select a request to delete."); return
        req_id = int(item)
        with sqlite3.connect(db_path()) as conn:
            row = conn.execute("SELECT approval_status FROM my_requests WHERE id=?", (req_id,)).fetchone()
        if not row:
            return
        if row[0] not in ("Pending", "Draft"):
            messagebox.showwarning("Delete", f"Cannot delete: status is {row[0]}"); return
        if not messagebox.askyesno("Delete", f"Delete request #{req_id}?"):
            return
        if not self.logged_in:
            messagebox.showerror("Error", "Login first."); return
        base = DEFAULT_BASE_URL.rstrip("/")
        try:
            r = self.session.delete(f"{base}/requests/{req_id}", timeout=20)
            body = r.json() if r.headers.get("Content-Type", "").startswith("application/json") else {}
            if r.status_code != 200:
                messagebox.showerror("Delete", body.get("detail", f"HTTP {r.status_code}")); return
            with sqlite3.connect(db_path()) as conn:
                conn.execute("DELETE FROM my_requests WHERE id=?", (req_id,))
                conn.commit()
            self._load_my_requests_from_cache()
            self.status_text.set(f"Request #{req_id} deleted.")
        except Exception as exc:
            messagebox.showerror("Delete", f"Failed: {exc}")

    def view_bill_selected(self) -> None:
        item = self.tree.focus()
        if not item:
            messagebox.showwarning("Select", "Select a request first."); return
        req_id = int(item)
        with sqlite3.connect(db_path()) as conn:
            conn.execute("UPDATE my_requests SET prev_status=approval_status WHERE id=?", (req_id,))
            conn.commit()
        self._load_my_requests_from_cache()
        path = (self.bill_paths.get(req_id) or "").strip()
        if not path:
            messagebox.showinfo("Bill", "No bill attached for this request."); return
        base = DEFAULT_BASE_URL.rstrip("/") + "/"
        bill_url = path if path.startswith("http") else urljoin(base, path.lstrip("/"))
        webbrowser.open_new_tab(bill_url)

    def view_completion_docs(self, req_id: int) -> None:
        """Open a dialog with view/download buttons for vendor bill and company voucher."""
        with sqlite3.connect(db_path()) as conn:
            row = conn.execute(
                "SELECT vendor_bill_path, company_voucher_path FROM my_requests WHERE id=?", (req_id,)
            ).fetchone()
        if not row or (not row[0] and not row[1]):
            messagebox.showinfo("Documents", "No completion documents uploaded for this request.")
            return
        vendor_bill_path, company_voucher_path = row

        dialog = tk.Toplevel(self.root)
        dialog.title(f"Completion Documents — Request #{req_id}")
        dialog.geometry("420x200")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()

        ttk.Label(dialog, text=f"Completion Documents for Request #{req_id}",
                  font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=16, pady=(14, 8))

        def _open_doc(doc_type: str, label: str):
            import tempfile, os, threading
            base = DEFAULT_BASE_URL.rstrip("/")
            endpoint = f"{base}/requests/{req_id}/{doc_type}"
            def _fetch():
                try:
                    r = self.session.get(endpoint, allow_redirects=True, timeout=30)
                    if r.status_code == 200:
                        ct = r.headers.get("Content-Type", "")
                        ext = ".pdf" if "pdf" in ct else (".png" if "png" in ct else ".jpg")
                        import re as _re
                        cd = r.headers.get("Content-Disposition", "")
                        m = _re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', cd, _re.IGNORECASE)
                        if m:
                            ext = Path(m.group(1).strip()).suffix or ext
                        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext,
                                                         prefix=f"req{req_id}_{doc_type}_")
                        tmp.write(r.content); tmp.close()
                        os.startfile(tmp.name)
                    elif r.status_code == 302 and "/login" in r.headers.get("Location", ""):
                        dialog.after(0, lambda: messagebox.showerror("Documents", "Session expired. Please login again."))
                    else:
                        dialog.after(0, lambda: messagebox.showerror("Documents",
                            f"Could not fetch {label} (HTTP {r.status_code})"))
                except Exception as exc:
                    dialog.after(0, lambda: messagebox.showerror("Documents", f"Error: {exc}"))
            threading.Thread(target=_fetch, daemon=True).start()

        def _download_doc(doc_type: str, label: str):
            import threading
            base = DEFAULT_BASE_URL.rstrip("/")
            endpoint = f"{base}/requests/{req_id}/{doc_type}"
            def _fetch():
                try:
                    r = self.session.get(endpoint, allow_redirects=True, timeout=30)
                    if r.status_code == 200:
                        ct = r.headers.get("Content-Type", "")
                        ext = ".pdf" if "pdf" in ct else (".png" if "png" in ct else ".jpg")
                        import re as _re
                        cd = r.headers.get("Content-Disposition", "")
                        m = _re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', cd, _re.IGNORECASE)
                        if m:
                            ext = Path(m.group(1).strip()).suffix or ext
                        def _save():
                            of = filedialog.asksaveasfilename(
                                title=f"Save {label}", defaultextension=ext,
                                initialfile=f"request_{req_id}_{doc_type}{ext}",
                                filetypes=[("All Files", "*.*")])
                            if of:
                                with open(of, "wb") as f: f.write(r.content)
                                messagebox.showinfo("Download", f"Saved:\n{of}")
                        dialog.after(0, _save)
                    else:
                        dialog.after(0, lambda: messagebox.showerror("Download",
                            f"Could not fetch {label} (HTTP {r.status_code})"))
                except Exception as exc:
                    dialog.after(0, lambda: messagebox.showerror("Download", f"Error: {exc}"))
            threading.Thread(target=_fetch, daemon=True).start()

        if vendor_bill_path:
            row1 = ttk.Frame(dialog)
            row1.pack(fill="x", padx=16, pady=4)
            ttk.Label(row1, text="📄 Vendor Bill:", width=18, anchor="w",
                      font=("Segoe UI", 9, "bold")).pack(side="left")
            ttk.Button(row1, text="View", command=lambda: _open_doc("vendor-bill", "Vendor Bill")).pack(side="left", padx=(0, 4))
            ttk.Button(row1, text="Download", command=lambda: _download_doc("vendor-bill", "Vendor Bill")).pack(side="left")
        else:
            row1 = ttk.Frame(dialog)
            row1.pack(fill="x", padx=16, pady=4)
            ttk.Label(row1, text="📄 Vendor Bill:", width=18, anchor="w",
                      font=("Segoe UI", 9, "bold")).pack(side="left")
            ttk.Label(row1, text="Not uploaded", foreground="#888").pack(side="left")

        if company_voucher_path:
            row2 = ttk.Frame(dialog)
            row2.pack(fill="x", padx=16, pady=4)
            ttk.Label(row2, text="🧾 Co. Voucher:", width=18, anchor="w",
                      font=("Segoe UI", 9, "bold")).pack(side="left")
            ttk.Button(row2, text="View", command=lambda: _open_doc("company-voucher", "Company Voucher")).pack(side="left", padx=(0, 4))
            ttk.Button(row2, text="Download", command=lambda: _download_doc("company-voucher", "Company Voucher")).pack(side="left")
        else:
            row2 = ttk.Frame(dialog)
            row2.pack(fill="x", padx=16, pady=4)
            ttk.Label(row2, text="🧾 Co. Voucher:", width=18, anchor="w",
                      font=("Segoe UI", 9, "bold")).pack(side="left")
            ttk.Label(row2, text="Not uploaded", foreground="#888").pack(side="left")

        ttk.Button(dialog, text="Close", command=dialog.destroy).pack(pady=(12, 0))
        dialog.wait_window()

    def submit_bill_upload(self) -> None:
        if not self.logged_in:
            messagebox.showerror("Error", "Please login first."); return
        try:
            base = self._server_url()
        except RuntimeError as exc:
            messagebox.showerror("Security Error", str(exc)); return
        vendor_name = self.b_vendor_name.get().strip()
        if not vendor_name:
            self._bill_status("Vendor name is required.", error=True); return
        bill_path = self.b_file_path.get().strip()
        if not bill_path or not Path(bill_path).exists():
            self._bill_status("Select a valid bill file.", error=True); return
        factory_id = self.b_factory_id.get()
        data = {"vendor_name": vendor_name}
        if factory_id > 0:
            data["factory_id"] = str(factory_id)
        self.bill_btn.config(state="disabled")
        self._bill_status("Uploading, please wait...", error=False)
        try:
            with open(bill_path, "rb") as f:
                r = self.session.post(f"{base}/requests/simple-bill", data=data,
                                      files={"bill_image": f}, timeout=30)
            body = r.json() if r.headers.get("Content-Type", "").startswith("application/json") else {}
            if r.status_code != 200:
                detail = str(body.get("detail", f"HTTP {r.status_code}"))
                if self._should_retry_response(r.status_code):
                    self._enqueue_pending_upload("simple_bill", "POST", "/requests/simple-bill", data, bill_path, detail)
                    self._bill_status("Offline queue: bill saved locally and will retry automatically.", error=False)
                    self._reset_bill_form()
                else:
                    self._bill_status(detail, error=True)
            else:
                success_message = body.get("message", "Uploaded!")
                self._bill_status(f"✓ {success_message}", error=False)
                messagebox.showinfo("Success", success_message)
                self._reset_bill_form()
                self.sync_from_server(silent=True)
        except Exception as exc:
            self._enqueue_pending_upload("simple_bill", "POST", "/requests/simple-bill", data, bill_path, str(exc))
            self._bill_status("Offline queue: bill saved locally and will retry automatically.", error=False)
            self._reset_bill_form()
        finally:
            self.bill_btn.config(state="normal")

    def clear_request_form(self) -> None:
        self.edit_request_id = None
        self.f_request_type.set("Material")
        self.f_req_amount.set("")
        self.f_remarks.set("")
        self.f_quotation_path.set("")
        if hasattr(self, "purpose_text"):
            self.purpose_text.delete("1.0", "end")
        if hasattr(self, "req_status_var"):
            self.req_status_var.set("")

    def _req_status(self, msg: str, error: bool = False) -> None:
        self.req_status_var.set(msg)
        self.req_status_label.configure(foreground="#b02a37" if error else "#1f8a43")

    def _bill_status(self, msg: str, error: bool = False) -> None:
        self.bill_status_var.set(msg)
        self.bill_status_label.configure(foreground="#b02a37" if error else "#1f8a43")

    def _schedule_sync(self) -> None:
        if self.logged_in:
            self._retry_pending_uploads()
            if self.auto_sync_enabled.get():
                self.sync_from_server(silent=True)
        self.root.after(30000, self._schedule_sync)


def main() -> int:
    init_db()
    root = tk.Tk()
    FactoryLocalClient(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
