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
    "Hold":      ("#856404", "#fff3cd"),
    "Draft":     ("#6c757d", "#f0f0f0"),
}


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
                    "qty", "unit", "rate", "gst_percent", "amount", "approval_remark"]:
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
        self.auto_sync_enabled = tk.BooleanVar(value=True)
        self.logged_in = False
        self.edit_request_id: int | None = None

        self.f_date = tk.StringVar(value=str(date.today()))
        self.f_factory_id = tk.IntVar(value=0)
        self.f_factory_name = tk.StringVar(value="")
        self.f_vendor_id = tk.IntVar(value=0)
        self.f_vendor_name = tk.StringVar(value="")
        self.f_vendor_mobile = tk.StringVar(value="")
        self.f_category = tk.StringVar(value="")
        self.f_item = tk.StringVar(value="")
        self.f_qty = tk.StringVar(value="")
        self.f_unit = tk.StringVar(value="")
        self.f_rate = tk.StringVar(value="")
        self.f_gst = tk.StringVar(value="0")
        self.f_amount = tk.StringVar(value="0.00")
        self.f_final = tk.StringVar(value="0.00")
        self.f_urgent = tk.StringVar(value="false")
        self.f_requested_by = tk.StringVar(value="")
        self.req_bill_path = tk.StringVar(value="")

        self.b_vendor_name = tk.StringVar(value="")
        self.b_factory_id = tk.IntVar(value=0)
        self.b_factory_name = tk.StringVar(value="")
        self.b_file_path = tk.StringVar(value="")

        self.filt_date = tk.StringVar(value="")
        self.filt_vendor = tk.StringVar(value="")
        self.filt_status = tk.StringVar(value="")

        self.factories: list[dict] = []
        self.vendors: list[dict] = []
        self.bill_paths: dict[int, str] = {}

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
                    files = {"bill_image": file_handle}
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
        BG, PRIMARY, WHITE = "#f0f4f8", "#1a3a6e", "#ffffff"
        style = ttk.Style(self.root)
        style.theme_use("clam")
        self.root.configure(bg=BG)
        style.configure(".", background=BG, font=("Segoe UI", 10))
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, font=("Segoe UI", 10))
        style.configure("TLabelframe", background=BG)
        style.configure("TLabelframe.Label", background=BG, font=("Segoe UI", 10, "bold"), foreground=PRIMARY)
        style.configure("TNotebook", background=BG, tabmargins=[2, 5, 2, 0])
        style.configure("TNotebook.Tab", background="#c9d6e8", foreground=PRIMARY,
                        font=("Segoe UI", 10, "bold"), padding=[14, 6])
        style.map("TNotebook.Tab", background=[("selected", PRIMARY)], foreground=[("selected", WHITE)])
        style.configure("Treeview", background=WHITE, fieldbackground=WHITE,
                        font=("Segoe UI", 10), rowheight=28)
        style.configure("Treeview.Heading", background=PRIMARY, foreground=WHITE,
                        font=("Segoe UI", 10, "bold"), relief="flat")
        style.map("Treeview", background=[("selected", "#2563a8")], foreground=[("selected", WHITE)])
        style.configure("TEntry", fieldbackground=WHITE, font=("Segoe UI", 10), padding=4)
        style.configure("TCombobox", fieldbackground=WHITE, font=("Segoe UI", 10))
        style.configure("TCheckbutton", background=BG, font=("Segoe UI", 10))
        style.configure("TScrollbar", background="#c9d6e8", troughcolor="#e0e8f0", relief="flat")

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
        hdr = tk.Frame(self.root, bg="#1a3a6e", height=75)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        logo_c = tk.Canvas(hdr, width=190, height=65, bg="#1a3a6e", highlightthickness=0)
        logo_c.pack(side="left", padx=(12, 0), pady=5)
        self._draw_emd_logo(logo_c)
        title_f = tk.Frame(hdr, bg="#1a3a6e")
        title_f.pack(side="left", padx=14, pady=10)
        tk.Label(title_f, text="Factory Panel", bg="#1a3a6e", fg="white",
                 font=("Segoe UI", 18, "bold")).pack(anchor="w")
        tk.Label(title_f, text="Purchase Request Submission  —  Site / Factory",
                 bg="#1a3a6e", fg="#a8c4e0", font=("Segoe UI", 9)).pack(anchor="w")
        right_hdr = tk.Frame(hdr, bg="#1a3a6e")
        right_hdr.pack(side="right", padx=14)
        self._conn_dot = tk.Label(right_hdr, text="●", bg="#1a3a6e", fg="#dc3545", font=("Segoe UI", 16))
        self._conn_dot.pack(side="right", padx=(4, 0))
        tk.Label(right_hdr, textvariable=self.conn_text, bg="#1a3a6e", fg="white",
                 font=("Segoe UI", 10, "bold")).pack(side="right")
        tk.Label(right_hdr, text=DEFAULT_BASE_URL, bg="#1a3a6e", fg="#7bafd4",
                 font=("Segoe UI", 7)).pack(side="right", padx=(0, 10))

        # ── Connection / login bar ─────────────────────────────────────────
        login_bar = ttk.Frame(self.root, padding=(8, 6, 8, 2))
        login_bar.pack(fill="x")
        ttk.Label(login_bar, text="Username").grid(row=0, column=0, sticky="w")
        ttk.Entry(login_bar, textvariable=self.username, width=20).grid(row=1, column=0, padx=(0, 8), sticky="w")
        ttk.Label(login_bar, text="Password").grid(row=0, column=1, sticky="w")
        ttk.Entry(login_bar, textvariable=self.password, show="*", width=20).grid(row=1, column=1, padx=(0, 8), sticky="w")

        def _hbtn(parent, text, cmd, bg="#1a3a6e"):
            return tk.Button(parent, text=text, command=cmd, bg=bg, fg="white",
                             font=("Segoe UI", 9, "bold"), relief="flat", cursor="hand2",
                             padx=10, pady=5, activebackground="#0d2a56", activeforeground="white", bd=0)

        _hbtn(login_bar, "\U0001f510  Login", self.login).grid(row=1, column=2, padx=(0, 6))
        _hbtn(login_bar, "\U0001f504  Sync",  self.sync_from_server, "#1565a0").grid(row=1, column=3, padx=(0, 6))
        ttk.Checkbutton(login_bar, text="Auto Sync (30s)", variable=self.auto_sync_enabled).grid(
            row=1, column=4, padx=8)
        ttk.Label(login_bar, textvariable=self.status_text, foreground="#1a3a6e",
                  font=("Segoe UI", 9, "italic")).grid(row=1, column=5, padx=8, sticky="w")

        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=10, pady=8)
        self.notebook = nb
        self.request_frame = ttk.Frame(nb)
        self.bill_frame = ttk.Frame(nb)
        nb.add(self.request_frame, text="\U0001f4cb  Create Request")
        nb.add(self.bill_frame, text="\U0001f9fe  Simple Bill Upload")
        self._build_request_tab()
        self._build_bill_upload_tab()

    def _build_request_tab(self) -> None:
        outer = self.request_frame
        outer.columnconfigure(0, weight=0, minsize=490)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(0, weight=1)

        left = ttk.LabelFrame(outer, text="Create Purchase Request", padding=10)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6), pady=2)
        left.columnconfigure(1, weight=1)
        left.columnconfigure(3, weight=1)
        p = {"padx": 4, "pady": 3, "sticky": "w"}
        fw = 22

        r = 0
        ttk.Label(left, text="Request Date *").grid(row=r, column=0, **p)
        ttk.Entry(left, textvariable=self.f_date, width=fw).grid(row=r, column=1, **p)
        ttk.Label(left, text="Factory *").grid(row=r, column=2, **p)
        self.factory_combo = ttk.Combobox(left, textvariable=self.f_factory_name, state="readonly", width=fw)
        self.factory_combo.grid(row=r, column=3, **p)
        self.factory_combo.bind("<<ComboboxSelected>>", self._on_factory_select)

        r += 1
        ttk.Label(left, text="Vendor *").grid(row=r, column=0, **p)
        self.vendor_combo = ttk.Combobox(left, textvariable=self.f_vendor_name, state="readonly", width=fw)
        self.vendor_combo.grid(row=r, column=1, **p)
        self.vendor_combo.bind("<<ComboboxSelected>>", self._on_vendor_select)
        ttk.Label(left, text="Vendor Name").grid(row=r, column=2, **p)
        ttk.Entry(left, textvariable=self.f_vendor_mobile, width=fw).grid(row=r, column=3, **p)

        r += 1
        ttk.Label(left, text="Item Category *").grid(row=r, column=0, **p)
        self.category_combo = ttk.Combobox(left, textvariable=self.f_category, state="readonly", width=fw)
        self.category_combo.grid(row=r, column=1, **p)
        ttk.Label(left, text="Item Name *").grid(row=r, column=2, **p)
        ttk.Entry(left, textvariable=self.f_item, width=fw).grid(row=r, column=3, **p)

        r += 1
        ttk.Label(left, text="Qty *").grid(row=r, column=0, **p)
        ttk.Entry(left, textvariable=self.f_qty, width=12).grid(row=r, column=1, sticky="w", padx=4, pady=3)
        self.f_qty.trace_add("write", self._recalculate)
        ttk.Label(left, text="Unit *").grid(row=r, column=2, **p)
        self.unit_combo = ttk.Combobox(left, textvariable=self.f_unit, width=fw)
        self.unit_combo.grid(row=r, column=3, **p)

        r += 1
        ttk.Label(left, text="Rate *").grid(row=r, column=0, **p)
        ttk.Entry(left, textvariable=self.f_rate, width=12).grid(row=r, column=1, sticky="w", padx=4, pady=3)
        self.f_rate.trace_add("write", self._recalculate)
        ttk.Label(left, text="GST %").grid(row=r, column=2, **p)
        ttk.Entry(left, textvariable=self.f_gst, width=12).grid(row=r, column=3, sticky="w", padx=4, pady=3)
        self.f_gst.trace_add("write", self._recalculate)

        r += 1
        ttk.Label(left, text="Amount").grid(row=r, column=0, **p)
        ttk.Entry(left, textvariable=self.f_amount, state="readonly", width=fw).grid(row=r, column=1, **p)
        ttk.Label(left, text="Final Amount").grid(row=r, column=2, **p)
        ttk.Entry(left, textvariable=self.f_final, state="readonly", width=fw).grid(row=r, column=3, **p)

        r += 1
        ttk.Label(left, text="Reason / Urgency *").grid(row=r, column=0, **p)
        self.reason_text = tk.Text(left, height=3, width=54)
        self.reason_text.grid(row=r, column=1, columnspan=3, padx=4, pady=3, sticky="ew")

        r += 1
        ttk.Label(left, text="Payment Needed Today?").grid(row=r, column=0, **p)
        ttk.Combobox(left, textvariable=self.f_urgent, values=["false", "true"],
                     state="readonly", width=12).grid(row=r, column=1, sticky="w", padx=4, pady=3)
        ttk.Label(left, text="Requested By *").grid(row=r, column=2, **p)
        ttk.Entry(left, textvariable=self.f_requested_by, width=fw).grid(row=r, column=3, **p)

        r += 1
        ttk.Label(left, text="Upload Bill / Quotation *").grid(row=r, column=0, **p)
        ttk.Entry(left, textvariable=self.req_bill_path, state="readonly", width=34).grid(
            row=r, column=1, columnspan=2, **p)
        ttk.Button(left, text="Browse", command=self._browse_req_bill).grid(row=r, column=3, **p)

        r += 1
        ttk.Label(left, text="Notes").grid(row=r, column=0, **p)
        self.notes_text = tk.Text(left, height=3, width=54)
        self.notes_text.grid(row=r, column=1, columnspan=3, padx=4, pady=3, sticky="ew")

        r += 1
        self.req_status_var = tk.StringVar(value="")
        self.req_status_label = ttk.Label(left, textvariable=self.req_status_var, wraplength=460, justify="left")
        self.req_status_label.grid(row=r, column=0, columnspan=4, padx=4, pady=(6, 0), sticky="w")

        r += 1
        btn_row = ttk.Frame(left)
        btn_row.grid(row=r, column=0, columnspan=4, padx=4, pady=10, sticky="w")

        def _fbtn(p, t, c, bg="#1a3a6e"):
            return tk.Button(p, text=t, command=c, bg=bg, fg="white",
                             font=("Segoe UI", 9, "bold"), relief="flat", cursor="hand2",
                             padx=10, pady=5, bd=0)

        self.submit_btn = _fbtn(btn_row, "\U0001f4e4  Submit Request", self.submit_request, "#1b5e20")
        self.submit_btn.pack(side="left", padx=(0, 6))
        self.draft_btn = _fbtn(btn_row, "\U0001f4be  Save Draft", self.save_draft, "#e65100")
        self.draft_btn.pack(side="left", padx=(0, 6))
        _fbtn(btn_row, "\U0001f504  Reset", self.clear_request_form, "#546e7a").pack(side="left")

        right = ttk.LabelFrame(outer, text="My Requests", padding=8)
        right.grid(row=0, column=1, sticky="nsew", pady=2)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        fbar = ttk.Frame(right)
        fbar.pack(fill="x", pady=(0, 6))
        ttk.Label(fbar, text="Date (YYYY-MM-DD):").pack(side="left")
        ttk.Entry(fbar, textvariable=self.filt_date, width=14).pack(side="left", padx=(2, 8))
        ttk.Label(fbar, text="Vendor:").pack(side="left")
        ttk.Entry(fbar, textvariable=self.filt_vendor, width=16).pack(side="left", padx=(2, 8))
        ttk.Label(fbar, text="Status:").pack(side="left")
        ttk.Combobox(fbar, textvariable=self.filt_status,
                     values=["", "Draft", "Pending", "Hold", "Rejected", "Approved"],
                     state="readonly", width=10).pack(side="left", padx=(2, 6))
        ttk.Button(fbar, text="Search", command=self._apply_filters).pack(side="left")

        cols = ("id", "date", "vendor", "item", "amount", "approval", "payment", "actions")
        self.tree = ttk.Treeview(right, columns=cols, show="headings", height=18)
        self.tree.tag_configure("Approved",   background="#d4edda", foreground="#1f8a43")
        self.tree.tag_configure("Rejected",   background="#f8d7da", foreground="#dc3545")
        self.tree.tag_configure("Hold",       background="#fff3cd", foreground="#856404")
        self.tree.tag_configure("Draft",      background="#f5f5f5", foreground="#6c757d")
        self.tree.tag_configure("Pending",    background="#ffffff", foreground="#0b5ed7")
        self.tree.tag_configure("new_status", background="#ffcccc", foreground="#cc0000")
        for c in cols:
            self.tree.heading(c, text=c.title())
        self.tree.column("id",       width=50,  anchor="center")
        self.tree.column("date",     width=100, anchor="center")
        self.tree.column("vendor",   width=130)
        self.tree.column("item",     width=140)
        self.tree.column("amount",   width=90,  anchor="e")
        self.tree.column("approval", width=90,  anchor="center")
        self.tree.column("payment",  width=85,  anchor="center")
        self.tree.column("actions",  width=150, anchor="center")

        vs = ttk.Scrollbar(right, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")

        act_row = ttk.Frame(right)
        act_row.pack(fill="x", pady=(4, 0))

        def _abtn(p, t, c, bg="#1a3a6e"):
            return tk.Button(p, text=t, command=c, bg=bg, fg="white",
                             font=("Segoe UI", 9, "bold"), relief="flat", cursor="hand2",
                             padx=8, pady=4, bd=0)

        _abtn(act_row, "\u270f  Edit",   self.edit_selected).pack(side="left", padx=(0, 4))
        _abtn(act_row, "\U0001f5d1  Delete", self.delete_selected, "#b71c1c").pack(side="left", padx=(0, 4))
        _abtn(act_row, "\U0001f9fe  View Bill", self.view_bill_selected, "#1565a0").pack(side="left")

    def _build_bill_upload_tab(self) -> None:
        frame = ttk.LabelFrame(self.bill_frame, text="Upload Actual Bill (Quick)", padding=14)
        frame.pack(fill="x", padx=20, pady=20)
        frame.columnconfigure(1, weight=1)
        p = {"padx": 6, "pady": 6, "sticky": "w"}

        r = 0
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
                                  bg="#1b5e20", fg="white", font=("Segoe UI", 9, "bold"),
                                  relief="flat", cursor="hand2", padx=10, pady=5, bd=0)
        self.bill_btn.pack(side="left", padx=(0, 6))
        tk.Button(btn_row, text="\U0001f504  Reset", command=self._reset_bill_form,
                  bg="#546e7a", fg="white", font=("Segoe UI", 9, "bold"),
                  relief="flat", cursor="hand2", padx=10, pady=5, bd=0).pack(side="left")

    def _recalculate(self, *_) -> None:
        try:
            qty = float(self.f_qty.get())
            rate = float(self.f_rate.get())
            gst = float(self.f_gst.get() or "0")
        except ValueError:
            self.f_amount.set("0.00")
            self.f_final.set("0.00")
            return
        amount = round(qty * rate, 2)
        final = round(amount + amount * gst / 100, 2)
        self.f_amount.set(f"{amount:.2f}")
        self.f_final.set(f"{final:.2f}")

    def _on_factory_select(self, _=None) -> None:
        name = self.f_factory_name.get()
        for f in self.factories:
            if f["name"] == name:
                self.f_factory_id.set(f["id"])
                return

    def _on_vendor_select(self, _=None) -> None:
        name = self.f_vendor_name.get()
        for v in self.vendors:
            if v["name"] == name:
                self.f_vendor_id.set(v["id"])
                return

    def _on_bill_factory_select(self, _=None) -> None:
        name = self.b_factory_name.get()
        for f in self.factories:
            if f["name"] == name:
                self.b_factory_id.set(f["id"])
                return

    def _browse_bill(self) -> None:
        path = filedialog.askopenfilename(title="Select Bill Image",
            filetypes=[("Images & PDFs", "*.jpg *.jpeg *.png *.pdf"), ("All files", "*.*")])
        if path:
            self.b_file_path.set(path)

    def _browse_req_bill(self) -> None:
        path = filedialog.askopenfilename(title="Select Bill / Quotation",
            filetypes=[("Images & PDFs", "*.jpg *.jpeg *.png *.pdf"), ("All files", "*.*")])
        if path:
            self.req_bill_path.set(path)

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
            self.logged_in = True
            self._set_conn(True)
            self.f_requested_by.set(self.username.get())
            self.status_text.set("Logged in successfully")
            self._load_masters()
            self.sync_from_server(silent=True)
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
        color = "#00e676" if online else "#dc3545"
        if hasattr(self, "_conn_dot"):
            self._conn_dot.config(fg=color)

    def _load_masters(self) -> None:
        base = DEFAULT_BASE_URL.rstrip("/")
        try:
            for mtype in ("factories", "vendors", "categories", "units"):
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
            self.factory_combo["values"] = fnames
            self.bill_factory_combo["values"] = fnames
            if fnames and not self.f_factory_name.get():
                self.f_factory_name.set(fnames[0]); self.b_factory_name.set(fnames[0])
                self._on_factory_select(); self._on_bill_factory_select()

            rows = conn.execute("SELECT id, name FROM masters_cache WHERE type='vendors' ORDER BY name").fetchall()
            self.vendors = [{"id": r[0], "name": r[1]} for r in rows]
            self.vendor_combo["values"] = [v["name"] for v in self.vendors]

            rows = conn.execute("SELECT name FROM masters_cache WHERE type='categories' ORDER BY name").fetchall()
            cats = [r[0] for r in rows]
            self.category_combo["values"] = cats
            if cats and not self.f_category.get():
                self.f_category.set(cats[0])

            rows = conn.execute("SELECT name FROM masters_cache WHERE type='units' ORDER BY name").fetchall()
            units = [r[0] for r in rows]
            self.unit_combo["values"] = units
            if units and not self.f_unit.get():
                self.f_unit.set(units[0])

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
            self.status_text.set(f"Synced {len(items)} records at {datetime.now().strftime('%H:%M:%S')}")
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
                        payment_status,approval_remark,bill_image_path,updated_at,synced_at,prev_status)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
                        prev_status=CASE WHEN my_requests.approval_status != excluded.approval_status
                                    THEN my_requests.approval_status ELSE my_requests.prev_status END
                    """,
                    (it.get("id"), it.get("request_date"), it.get("item_category"),
                     it.get("vendor"), it.get("item_name"), it.get("qty"), it.get("unit"),
                     it.get("rate"), it.get("gst_percent"), it.get("amount"), it.get("final_amount"),
                     it.get("reason"), 1 if it.get("urgent_flag") else 0, it.get("requested_by"),
                     it.get("notes"), it.get("vendor_id"), it.get("factory_id"), it.get("vendor_mobile"),
                     it.get("approval_status"), it.get("payment_status"), it.get("approval_remark"),
                     it.get("bill_image_path"), it.get("updated_at"), now, prev_status))
            conn.commit()

    def _load_my_requests_from_cache(self) -> None:
        self.bill_paths.clear()
        for row in self.tree.get_children():
            self.tree.delete(row)

        filt_date   = self.filt_date.get().strip()
        filt_vendor = self.filt_vendor.get().strip().lower()
        filt_status = self.filt_status.get().strip()

        status_changed = []
        with sqlite3.connect(db_path()) as conn:
            rows = conn.execute("""
                SELECT id, request_date, vendor, item_name, final_amount,
                       approval_status, payment_status, bill_image_path, prev_status, approval_remark
                FROM my_requests ORDER BY id DESC
            """).fetchall()

        for r in rows:
            req_id = int(r[0])
            approval_status = r[5] or "Pending"
            prev_status = r[8]
            self.bill_paths[req_id] = r[7] or ""

            if filt_date and (r[1] or "") and filt_date not in (r[1] or ""):
                continue
            if filt_vendor and filt_vendor not in (r[2] or "").lower():
                continue
            if filt_status and approval_status != filt_status:
                continue

            changed = prev_status is not None and prev_status != approval_status
            if changed:
                status_changed.append((req_id, prev_status, approval_status, r[3], r[9]))

            editable = approval_status in ("Pending", "Draft", "Hold")
            actions = []
            if editable:
                actions += ["[Edit]", "[Delete]"]
            if self.bill_paths[req_id]:
                actions.append("[Bill]")

            row_vals = (req_id, r[1], r[2], r[3],
                        f"{float(r[4]):.2f}" if r[4] else "0.00",
                        approval_status, r[6] or "", "  ".join(actions))
            tag = "new_status" if changed else approval_status
            self.tree.insert("", "end", values=row_vals, tags=(tag,), iid=str(req_id))

        if status_changed:
            self._notify_status_changes(status_changed)

        badge = len(status_changed)
        label = "Create Request" + (f" ({badge} updates)" if badge else "")
        self.notebook.tab(self.request_frame, text=label)

    def _apply_filters(self) -> None:
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
        self._do_submit(save_as_draft=False)

    def save_draft(self) -> None:
        self._do_submit(save_as_draft=True)

    def _do_submit(self, save_as_draft: bool) -> None:
        if not self.logged_in:
            messagebox.showerror("Error", "Please login first.")
            return
        try:
            base = self._server_url()
        except RuntimeError as exc:
            messagebox.showerror("Security Error", str(exc))
            return
        try:
            datetime.strptime(self.f_date.get().strip(), "%Y-%m-%d")
        except ValueError:
            self._req_status("Date must be YYYY-MM-DD", error=True)
            return
        if self.f_factory_id.get() <= 0:
            self._req_status("Select a factory.", error=True); return
        if self.f_vendor_id.get() <= 0:
            self._req_status("Select a vendor.", error=True); return
        if not self.f_category.get().strip():
            self._req_status("Select a category.", error=True); return
        if not self.f_item.get().strip():
            self._req_status("Enter item name.", error=True); return
        try:
            qty = float(self.f_qty.get())
            rate = float(self.f_rate.get())
            gst = float(self.f_gst.get() or "0")
            if qty <= 0 or rate <= 0:
                raise ValueError
        except ValueError:
            self._req_status("Qty and Rate must be valid positive numbers.", error=True); return
        reason = self.reason_text.get("1.0", "end").strip()
        if not reason:
            self._req_status("Reason / Urgency is required.", error=True); return
        if not self.f_requested_by.get().strip():
            self._req_status("Requested By is required.", error=True); return
        bill_path = self.req_bill_path.get().strip()
        if not save_as_draft and not bill_path and not self.edit_request_id:
            self._req_status("Upload Bill / Quotation image is required before submitting.", error=True); return

        amount = round(qty * rate, 2)
        final = round(amount + amount * gst / 100, 2)
        data = {
            "request_date": self.f_date.get().strip(),
            "factory_id": str(self.f_factory_id.get()),
            "vendor_id": str(self.f_vendor_id.get()),
            "vendor_mobile": self.f_vendor_mobile.get().strip(),
            "item_category": self.f_category.get().strip(),
            "item_name": self.f_item.get().strip(),
            "qty": str(qty), "unit": self.f_unit.get().strip(), "rate": str(rate),
            "amount": str(amount), "gst_percent": str(gst), "final_amount": str(final),
            "reason": reason, "urgent_flag": self.f_urgent.get(),
            "requested_by": self.f_requested_by.get().strip(),
            "notes": self.notes_text.get("1.0", "end").strip(),
            "save_as_draft": "true" if save_as_draft else "false",
        }
        files = {}
        if bill_path and Path(bill_path).exists():
            files["bill_image"] = open(bill_path, "rb")
        url = f"{base}/requests/{self.edit_request_id}" if self.edit_request_id else f"{base}/requests"
        method = "PUT" if self.edit_request_id else "POST"

        self.submit_btn.config(state="disabled"); self.draft_btn.config(state="disabled")
        self._req_status("Submitting, please wait...", error=False)
        try:
            r = self.session.request(method, url, data=data, files=files or None, timeout=30)
            body = r.json() if r.headers.get("Content-Type", "").startswith("application/json") else {}
            if r.status_code != 200:
                detail = body.get("detail", f"HTTP {r.status_code}")
                if isinstance(detail, list):
                    detail = detail[0].get("msg", str(detail))
                if self._should_retry_response(r.status_code):
                    endpoint = f"/requests/{self.edit_request_id}" if self.edit_request_id else "/requests"
                    self._enqueue_pending_upload("request", method, endpoint, data, bill_path or None, str(detail))
                    self._req_status("Offline queue: request saved locally and will retry automatically.", error=False)
                    self.clear_request_form()
                else:
                    self._req_status(str(detail), error=True)
            else:
                self._req_status(f"✓ {body.get('message', 'Saved!')}", error=False)
                self.clear_request_form()
                self.sync_from_server(silent=True)
        except Exception as exc:
            endpoint = f"/requests/{self.edit_request_id}" if self.edit_request_id else "/requests"
            self._enqueue_pending_upload("request", method, endpoint, data, bill_path or None, str(exc))
            self._req_status("Offline queue: request saved locally and will retry automatically.", error=False)
            self.clear_request_form()
        finally:
            if "bill_image" in files:
                files["bill_image"].close()
            self.submit_btn.config(state="normal"); self.draft_btn.config(state="normal")

    def edit_selected(self) -> None:
        item = self.tree.focus()
        if not item:
            messagebox.showwarning("Select", "Select a request to edit."); return
        req_id = int(item)
        with sqlite3.connect(db_path()) as conn:
            row = conn.execute("""SELECT request_date, factory_id, vendor_id, vendor_mobile,
                item_category, item_name, qty, unit, rate, gst_percent, reason, urgent_flag,
                requested_by, notes, approval_status FROM my_requests WHERE id=?""", (req_id,)).fetchone()
        if not row:
            messagebox.showerror("Error", "Request not found. Sync first."); return
        if row[14] not in ("Pending", "Draft", "Hold"):
            messagebox.showwarning("Edit", f"Cannot edit: status is {row[14]}"); return

        self.edit_request_id = req_id
        self.f_date.set(row[0] or str(date.today()))
        fid = int(row[1] or 0)
        for f in self.factories:
            if f["id"] == fid:
                self.f_factory_name.set(f["name"]); self.f_factory_id.set(fid); break
        vid = int(row[2] or 0)
        for v in self.vendors:
            if v["id"] == vid:
                self.f_vendor_name.set(v["name"]); self.f_vendor_id.set(vid); break
        self.f_vendor_mobile.set(row[3] or "")
        self.f_category.set(row[4] or "")
        self.f_item.set(row[5] or "")
        self.f_qty.set(str(row[6] or ""))
        self.f_unit.set(row[7] or "")
        self.f_rate.set(str(row[8] or ""))
        self.f_gst.set(str(row[9] or "0"))
        self.reason_text.delete("1.0", "end")
        self.reason_text.insert("1.0", row[10] or "")
        self.f_urgent.set("true" if row[11] else "false")
        self.f_requested_by.set(row[12] or "")
        self.notes_text.delete("1.0", "end")
        self.notes_text.insert("1.0", row[13] or "")
        self.req_bill_path.set("")
        self._recalculate()
        self._req_status(f"Editing Request #{req_id}. Re-upload bill only if changing it.", error=False)
        self.notebook.select(self.request_frame)

    def delete_selected(self) -> None:
        item = self.tree.focus()
        if not item:
            messagebox.showwarning("Select", "Select a request to delete."); return
        req_id = int(item)
        with sqlite3.connect(db_path()) as conn:
            row = conn.execute("SELECT approval_status FROM my_requests WHERE id=?", (req_id,)).fetchone()
        if not row:
            return
        if row[0] not in ("Pending", "Draft", "Hold"):
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
        self.f_date.set(str(date.today()))
        self.f_vendor_mobile.set(""); self.f_item.set("")
        self.f_qty.set(""); self.f_rate.set(""); self.f_gst.set("0")
        self.f_amount.set("0.00"); self.f_final.set("0.00")
        self.reason_text.delete("1.0", "end")
        self.f_urgent.set("false")
        self.notes_text.delete("1.0", "end")
        self.req_bill_path.set(""); self.req_status_var.set("")

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
