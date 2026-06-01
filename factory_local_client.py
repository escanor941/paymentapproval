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
                    "request_type", "purpose", "completion_status"]:
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
        self.f_request_type = tk.StringVar(value="Material")
        self.f_purpose = tk.StringVar(value="")
        self.f_req_amount = tk.StringVar(value="")
        self.f_remarks = tk.StringVar(value="")

        self.b_vendor_name = tk.StringVar(value="")
        self.b_factory_id = tk.IntVar(value=0)
        self.b_factory_name = tk.StringVar(value="")
        self.b_file_path = tk.StringVar(value="")

        self.filt_status = tk.StringVar(value="")
        self.filt_completion = tk.StringVar(value="")

        self.factories: list[dict] = []
        self.bill_paths: dict[int, str] = {}
        self.edit_request_id: int | None = None

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

        # ── Footer ────────────────────────────────────────────────────────────
        footer = tk.Frame(self.root, bg="#1a3a6e", height=22)
        footer.pack(side="bottom", fill="x")
        footer.pack_propagate(False)
        tk.Label(footer, text="Created by Daniyal  •  All Rights Reserved © 2026",
                 bg="#1a3a6e", fg="#a8c4e0", font=("Segoe UI", 8)).pack(side="right", padx=12)

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
        outer.columnconfigure(0, weight=0, minsize=420)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(0, weight=1)

        left = ttk.LabelFrame(outer, text="Create Purchase Request", padding=10)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6), pady=2)
        left.columnconfigure(1, weight=1)
        p = {"padx": 4, "pady": 5, "sticky": "ew"}
        fw = 28

        REQUEST_TYPES = ["Material", "Labour", "Transport", "Service", "Utility", "Emergency"]

        r = 0
        ttk.Label(left, text="Factory *").grid(row=r, column=0, padx=4, pady=5, sticky="w")
        self.factory_combo = ttk.Combobox(left, textvariable=self.f_factory_name, state="readonly", width=fw)
        self.factory_combo.grid(row=r, column=1, **p)
        self.factory_combo.bind("<<ComboboxSelected>>", self._on_factory_select)

        r += 1
        ttk.Label(left, text="Request Type *").grid(row=r, column=0, padx=4, pady=5, sticky="w")
        self.type_combo = ttk.Combobox(left, textvariable=self.f_request_type,
                                       values=REQUEST_TYPES, state="readonly", width=fw)
        self.type_combo.grid(row=r, column=1, **p)

        r += 1
        ttk.Label(left, text="Purpose *").grid(row=r, column=0, padx=4, pady=5, sticky="nw")
        self.purpose_text = tk.Text(left, height=4, width=fw + 4)
        self.purpose_text.grid(row=r, column=1, padx=4, pady=5, sticky="ew")

        r += 1
        ttk.Label(left, text="Amount ₹ *").grid(row=r, column=0, padx=4, pady=5, sticky="w")
        ttk.Entry(left, textvariable=self.f_req_amount, width=fw).grid(row=r, column=1, **p)

        r += 1
        ttk.Label(left, text="Remarks").grid(row=r, column=0, padx=4, pady=5, sticky="w")
        ttk.Entry(left, textvariable=self.f_remarks, width=fw).grid(row=r, column=1, **p)

        r += 1
        self.req_status_var = tk.StringVar(value="")
        self.req_status_label = ttk.Label(left, textvariable=self.req_status_var,
                                          wraplength=360, justify="left")
        self.req_status_label.grid(row=r, column=0, columnspan=2, padx=4, pady=(6, 0), sticky="w")

        r += 1
        btn_row = ttk.Frame(left)
        btn_row.grid(row=r, column=0, columnspan=2, padx=4, pady=10, sticky="w")

        def _fbtn(p, t, c, bg="#1a3a6e"):
            return tk.Button(p, text=t, command=c, bg=bg, fg="white",
                             font=("Segoe UI", 9, "bold"), relief="flat", cursor="hand2",
                             padx=10, pady=5, bd=0)

        self.submit_btn = _fbtn(btn_row, "\U0001f4e4  Submit Request", self.submit_request, "#1b5e20")
        self.submit_btn.pack(side="left", padx=(0, 6))
        _fbtn(btn_row, "\U0001f504  Reset", self.clear_request_form, "#546e7a").pack(side="left")

        # ── My Requests section (right side) ──────────────────────────────
        right = ttk.LabelFrame(outer, text="My Requests", padding=8)
        right.grid(row=0, column=1, sticky="nsew", pady=2)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        fbar = ttk.Frame(right)
        fbar.pack(fill="x", pady=(0, 6))
        ttk.Label(fbar, text="Approval:").pack(side="left")
        ttk.Combobox(fbar, textvariable=self.filt_status,
                     values=["", "Pending", "Partial Approved", "Approved", "Rejected"],
                     state="readonly", width=14).pack(side="left", padx=(2, 8))
        ttk.Label(fbar, text="Completion:").pack(side="left")
        ttk.Combobox(fbar, textvariable=self.filt_completion,
                     values=["", "Pending", "Awaiting Completion", "Completion Submitted", "Closed"],
                     state="readonly", width=18).pack(side="left", padx=(2, 6))
        ttk.Button(fbar, text="Search", command=self._apply_filters).pack(side="left")
        ttk.Button(fbar, text="Clear", command=self._clear_filters).pack(side="left", padx=(4, 0))

        cols = ("id", "date", "type", "purpose", "amount", "approval", "completion", "actions")
        self.tree = ttk.Treeview(right, columns=cols, show="headings", height=18)
        self.tree.tag_configure("Approved",          background="#d4edda", foreground="#1f8a43")
        self.tree.tag_configure("Rejected",          background="#f8d7da", foreground="#dc3545")
        self.tree.tag_configure("Partial Approved",  background="#fff3cd", foreground="#856404")
        self.tree.tag_configure("Pending",           background="#ffffff", foreground="#0b5ed7")
        self.tree.tag_configure("Draft",             background="#f5f5f5", foreground="#6c757d")
        self.tree.tag_configure("new_status",        background="#ffcccc", foreground="#cc0000")
        self.tree.tag_configure("awaiting_comp",     background="#e8f4fd", foreground="#0369a1")
        for c in cols:
            self.tree.heading(c, text=c.title())
        self.tree.column("id",         width=50,  anchor="center")
        self.tree.column("date",       width=95,  anchor="center")
        self.tree.column("type",       width=90,  anchor="center")
        self.tree.column("purpose",    width=160)
        self.tree.column("amount",     width=90,  anchor="e")
        self.tree.column("approval",   width=110, anchor="center")
        self.tree.column("completion", width=130, anchor="center")
        self.tree.column("actions",    width=160, anchor="center")

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

        _abtn(act_row, "\U0001f5d1  Delete",         self.delete_selected,      "#b71c1c").pack(side="left", padx=(0, 4))
        _abtn(act_row, "\U0001f9fe  View Bill",       self.view_bill_selected,   "#1565a0").pack(side="left", padx=(0, 4))
        _abtn(act_row, "\u2705  Submit Completion",  self.completion_selected,  "#0d5c2e").pack(side="left")

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

    def _on_factory_select(self, _=None) -> None:
        name = self.f_factory_name.get()
        for f in self.factories:
            if f["name"] == name:
                self.f_factory_id.set(f["id"])
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
                        payment_status,approval_remark,bill_image_path,updated_at,synced_at,prev_status,
                        request_type,purpose,completion_status)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
                     it.get("completion_status") or "Pending"))
            conn.commit()

    def _load_my_requests_from_cache(self) -> None:
        self.bill_paths.clear()
        for row in self.tree.get_children():
            self.tree.delete(row)

        filt_status     = self.filt_status.get().strip()
        filt_completion = self.filt_completion.get().strip()

        status_changed = []
        with sqlite3.connect(db_path()) as conn:
            rows = conn.execute("""
                SELECT id, request_date, request_type, purpose, final_amount,
                       approval_status, completion_status, bill_image_path, prev_status, approval_remark
                FROM my_requests ORDER BY id DESC
            """).fetchall()

        for r in rows:
            req_id = int(r[0])
            approval_status    = r[5] or "Pending"
            completion_status  = r[6] or "Pending"
            if approval_status == "Hold":
                approval_status = "Partial Approved"
            prev_status = r[8]
            self.bill_paths[req_id] = r[7] or ""

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
            if self.bill_paths[req_id]:
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
        try:
            r = self.session.post(f"{base}/requests/factory", data=data, timeout=30)
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
            self._enqueue_pending_upload("request", "POST", "/requests/factory", data, None, str(exc))
            self._req_status("Offline queue: request saved locally and will retry automatically.", error=False)
            self.clear_request_form()
        finally:
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
