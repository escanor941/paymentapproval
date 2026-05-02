import os
import sqlite3
import io
import re
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from urllib.parse import urljoin
import webbrowser

import requests

try:
    from openpyxl import Workbook
except Exception:  # pragma: no cover - optional import safety
    Workbook = None

try:
    from PIL import Image, ImageTk
except Exception:  # pragma: no cover - optional import safety
    Image = None
    ImageTk = None

try:
    import fitz  # PyMuPDF
except Exception:  # pragma: no cover - optional import safety
    fitz = None

APP_NAME = "EMDAdminPanel"
DEFAULT_BASE_URL = "https://paymentapproval.onrender.com"


def app_data_dir() -> Path:
    root = Path(os.getenv("APPDATA", str(Path.home()))) / APP_NAME
    root.mkdir(parents=True, exist_ok=True)
    return root


def db_path() -> Path:
    return app_data_dir() / "admin_cache.db"


def init_db() -> None:
    with sqlite3.connect(db_path()) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS requests_cache (
                id INTEGER PRIMARY KEY,
                request_date TEXT,
                factory_id INTEGER,
                item_category TEXT,
                vendor TEXT,
                item_name TEXT,
                qty REAL,
                unit TEXT,
                final_amount REAL,
                requested_by TEXT,
                approval_status TEXT,
                payment_status TEXT,
                bill_image_path TEXT,
                updated_at TEXT,
                raw_json TEXT,
                synced_at TEXT,
                viewed_at TEXT
            )
            """
        )
        cols = {row[1] for row in conn.execute("PRAGMA table_info(requests_cache)")}
        if "bill_image_path" not in cols:
            conn.execute("ALTER TABLE requests_cache ADD COLUMN bill_image_path TEXT")
        if "item_category" not in cols:
            conn.execute("ALTER TABLE requests_cache ADD COLUMN item_category TEXT")
        if "viewed_at" not in cols:
            conn.execute("ALTER TABLE requests_cache ADD COLUMN viewed_at TEXT")
        conn.commit()


class AdminLocalClient:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("EMD Group — Admin Panel")
        self.root.geometry("1320x740")
        self._apply_theme()

        self.session = requests.Session()

        self.base_url = tk.StringVar(value=DEFAULT_BASE_URL)
        # Lock base_url — admin panel always connects to the cloud server
        self.base_url.trace_add("write", lambda *_: self.base_url.set(DEFAULT_BASE_URL))
        self.username = tk.StringVar(value="admin")
        self.password = tk.StringVar(value="admin123")
        self.status_text = tk.StringVar(value="Not logged in")
        self.conn_text = tk.StringVar(value="Offline")
        self.auto_sync_enabled = tk.BooleanVar(value=True)
        self.logged_in = False
        self.bill_paths: dict[int, str] = {}
        self.factories_cache: dict[int, dict] = {}
        self.factory_name_var = tk.StringVar(value="")
        self.factory_location_var = tk.StringVar(value="")
        self.new_requests_count = 0
        self.new_bills_count = 0
        self.notebook = None
        self.requests_frame = None
        self.bills_frame = None
        self.preview_frame = None
        self.preview_canvas = None
        self.preview_status = tk.StringVar(value="No bill loaded")
        self._preview_photo = None
        self._preview_pil_image = None
        self.preview_req_id: int | None = None
        self.preview_filename = ""
        self._last_bill_url_by_req: dict[int, str] = {}
        self._viewed_ids: set[int] = set()

        self._last_server_items: list[dict] = []

        self._build_ui()
        self.status_text.set("Please login to load data from server")
        self.schedule_auto_sync()

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
        tk.Label(title_f, text="Admin Panel", bg="#1a3a6e", fg="white",
                 font=("Segoe UI", 18, "bold")).pack(anchor="w")
        tk.Label(title_f, text="Purchase Approval System  —  Head Office",
                 bg="#1a3a6e", fg="#a8c4e0", font=("Segoe UI", 9)).pack(anchor="w")
        right_hdr = tk.Frame(hdr, bg="#1a3a6e")
        right_hdr.pack(side="right", padx=14)
        self._conn_dot = tk.Label(right_hdr, text="●", bg="#1a3a6e", fg="#dc3545", font=("Segoe UI", 16))
        self._conn_dot.pack(side="right", padx=(4, 0))
        tk.Label(right_hdr, textvariable=self.conn_text, bg="#1a3a6e", fg="white",
                 font=("Segoe UI", 10, "bold")).pack(side="right")

        # ── Toolbar ──────────────────────────────────────────────────────────
        toolbar = tk.Frame(self.root, bg="#dce6f0", pady=5)
        toolbar.pack(fill="x")

        def _btn(parent, text, cmd, bg="#1a3a6e"):
            return tk.Button(parent, text=text, command=cmd, bg=bg, fg="white",
                             font=("Segoe UI", 9, "bold"), relief="flat", cursor="hand2",
                             padx=10, pady=5, activebackground="#0d2a56", activeforeground="white", bd=0)

        _btn(toolbar, "\U0001f510  Login",        self.login).pack(side="left", padx=(8, 4))
        _btn(toolbar, "\U0001f504  Sync",          self.sync_from_server, "#1565a0").pack(side="left", padx=4)
        _btn(toolbar, "\U0001f9fe  View Bill",     self.view_bill_selected, "#1565a0").pack(side="left", padx=4)
        _btn(toolbar, "\U0001f4e5  Download Bill", self.download_bill_selected, "#1565a0").pack(side="left", padx=4)
        _btn(toolbar, "\u2705  Approve",           self.approve_selected, "#1b5e20").pack(side="left", padx=4)
        _btn(toolbar, "\u274c  Reject",            self.reject_selected, "#b71c1c").pack(side="left", padx=4)
        _btn(toolbar, "\u23f8  Hold",              self.hold_selected, "#e65100").pack(side="left", padx=4)
        _btn(toolbar, "\U0001f5d1  Delete",        self.delete_selected, "#7f1d1d").pack(side="left", padx=4)
        _btn(toolbar, "\U0001f4ca  Export Excel",  self.export_local_excel, "#4a148c").pack(side="left", padx=4)

        # ── Login / connection bar ───────────────────────────────────────────
        login_bar = ttk.Frame(self.root, padding=(8, 4, 8, 2))
        login_bar.pack(fill="x")
        ttk.Label(login_bar, text="Username").grid(row=0, column=0, sticky="w")
        ttk.Entry(login_bar, textvariable=self.username, width=20).grid(row=1, column=0, padx=(0, 8), sticky="w")
        ttk.Label(login_bar, text="Password").grid(row=0, column=1, sticky="w")
        ttk.Entry(login_bar, textvariable=self.password, show="*", width=20).grid(row=1, column=1, padx=(0, 8), sticky="w")
        ttk.Checkbutton(login_bar, text="Auto Sync (10s)", variable=self.auto_sync_enabled).grid(row=1, column=2, padx=8)
        ttk.Label(login_bar, textvariable=self.status_text, foreground="#1a3a6e",
                  font=("Segoe UI", 9, "italic")).grid(row=1, column=3, padx=8, sticky="w")

        cols = (
            "id",
            "request_date",
            "factory_id",
            "vendor",
            "item_name",
            "final_amount",
            "requested_by",
            "approval_status",
            "payment_status",
            "updated_at",
        )
        body = ttk.Notebook(self.root)
        body.pack(fill="both", expand=True, padx=10, pady=10)
        self.notebook = body

        self.requests_frame = ttk.Frame(body)
        self.bills_frame = ttk.Frame(body)
        self.preview_frame = ttk.Frame(body)
        locations_tab = ttk.Frame(body)
        
        body.add(self.requests_frame, text="Requests")
        body.add(self.bills_frame, text="Bill Uploads")
        body.add(self.preview_frame, text="Bill Preview")
        body.add(locations_tab, text="Factory Locations")

        self.tree = ttk.Treeview(self.requests_frame, columns=cols, show="headings")
        self.tree.tag_configure("new_request", background="#ffcccc", foreground="#cc0000")
        for c in cols:
            self.tree.heading(c, text=c.replace("_", " ").title())

        self.tree.column("id", width=70, anchor="center")
        self.tree.column("request_date", width=110, anchor="center")
        self.tree.column("factory_id", width=80, anchor="center")
        self.tree.column("vendor", width=150)
        self.tree.column("item_name", width=170)
        self.tree.column("final_amount", width=110, anchor="e")
        self.tree.column("requested_by", width=140)
        self.tree.column("approval_status", width=120, anchor="center")
        self.tree.column("payment_status", width=120, anchor="center")
        self.tree.column("updated_at", width=170)

        vs = ttk.Scrollbar(self.requests_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        self.tree.pack(side="left", fill="both", expand=True, padx=(0, 0), pady=0)
        vs.pack(side="right", fill="y", padx=(0, 0), pady=0)

        bill_cols = (
            "id",
            "request_date",
            "factory_id",
            "vendor",
            "requested_by",
            "approval_status",
            "updated_at",
        )
        self.bill_tree = ttk.Treeview(self.bills_frame, columns=bill_cols, show="headings")
        self.bill_tree.tag_configure("new_bill", background="#ffcccc", foreground="#cc0000")
        for c in bill_cols:
            self.bill_tree.heading(c, text=c.replace("_", " ").title())

        self.bill_tree.column("id", width=70, anchor="center")
        self.bill_tree.column("request_date", width=110, anchor="center")
        self.bill_tree.column("factory_id", width=80, anchor="center")
        self.bill_tree.column("vendor", width=220)
        self.bill_tree.column("requested_by", width=180)
        self.bill_tree.column("approval_status", width=120, anchor="center")
        self.bill_tree.column("updated_at", width=220)

        bill_vs = ttk.Scrollbar(self.bills_frame, orient="vertical", command=self.bill_tree.yview)
        self.bill_tree.configure(yscrollcommand=bill_vs.set)
        self.bill_tree.pack(side="left", fill="both", expand=True, padx=(0, 0), pady=0)
        bill_vs.pack(side="right", fill="y", padx=(0, 0), pady=0)

        preview_top = ttk.Frame(self.preview_frame, padding=(0, 0, 0, 8))
        preview_top.pack(fill="x")
        ttk.Label(preview_top, textvariable=self.preview_status, foreground="#1a3a6e").pack(side="left")
        ttk.Button(preview_top, text="Load Selected Bill", command=self.view_bill_selected).pack(side="right", padx=(6, 0))
        ttk.Button(preview_top, text="Download", command=self.download_bill_selected).pack(side="right")

        preview_wrap = ttk.Frame(self.preview_frame)
        preview_wrap.pack(fill="both", expand=True)
        self.preview_canvas = tk.Canvas(preview_wrap, bg="#ffffff", highlightthickness=0)
        preview_vs = ttk.Scrollbar(preview_wrap, orient="vertical", command=self.preview_canvas.yview)
        preview_hs = ttk.Scrollbar(preview_wrap, orient="horizontal", command=self.preview_canvas.xview)
        self.preview_canvas.configure(yscrollcommand=preview_vs.set, xscrollcommand=preview_hs.set)
        self.preview_canvas.grid(row=0, column=0, sticky="nsew")
        preview_vs.grid(row=0, column=1, sticky="ns")
        preview_hs.grid(row=1, column=0, sticky="ew")
        preview_wrap.rowconfigure(0, weight=1)
        preview_wrap.columnconfigure(0, weight=1)
        self.preview_canvas.bind("<Configure>", self._on_preview_canvas_resize)

        loc_top = ttk.Frame(locations_tab, padding=(0, 0, 0, 10))
        loc_top.pack(fill="x")
        ttk.Label(loc_top, text="Factory Name").grid(row=0, column=0, sticky="w")
        ttk.Entry(loc_top, textvariable=self.factory_name_var, width=28, state="readonly").grid(row=1, column=0, padx=(0, 8), sticky="w")
        ttk.Label(loc_top, text="Location (lat,long,radius)").grid(row=0, column=1, sticky="w")
        ttk.Entry(loc_top, textvariable=self.factory_location_var, width=44).grid(row=1, column=1, padx=(0, 8), sticky="w")
        ttk.Button(loc_top, text="Refresh Locations", command=self.load_factory_locations).grid(row=1, column=2, padx=(0, 6))
        ttk.Button(loc_top, text="Save Location", command=self.save_factory_location).grid(row=1, column=3, padx=(0, 6))
        ttk.Button(loc_top, text="Open Map", command=self.open_selected_factory_map).grid(row=1, column=4)

        loc_cols = ("id", "name", "location", "preview")
        self.factory_tree = ttk.Treeview(locations_tab, columns=loc_cols, show="headings")
        self.factory_tree.heading("id", text="ID")
        self.factory_tree.heading("name", text="Factory")
        self.factory_tree.heading("location", text="Location")
        self.factory_tree.heading("preview", text="Preview")
        self.factory_tree.column("id", width=70, anchor="center")
        self.factory_tree.column("name", width=220)
        self.factory_tree.column("location", width=420)
        self.factory_tree.column("preview", width=300)
        self.factory_tree.bind("<<TreeviewSelect>>", self.on_factory_row_select)

        loc_vs = ttk.Scrollbar(locations_tab, orient="vertical", command=self.factory_tree.yview)
        self.factory_tree.configure(yscrollcommand=loc_vs.set)
        self.factory_tree.pack(side="left", fill="both", expand=True)
        loc_vs.pack(side="right", fill="y")

    def _server_url(self) -> str:
        url = DEFAULT_BASE_URL.rstrip("/")
        if not url.startswith("https://"):
            raise RuntimeError(f"Server URL must be HTTPS (got {url!r})")
        return url

    def login(self) -> None:
        base = DEFAULT_BASE_URL.rstrip("/")
        try:
            response = self.session.post(
                f"{base}/login",
                data={"username": self.username.get(), "password": self.password.get()},
                allow_redirects=False,
                timeout=20,
            )
            if response.status_code not in (302, 303):
                self.logged_in = False
                self.set_connection_state(False)
                self.status_text.set("Login failed")
                messagebox.showerror("Login", f"Login failed: HTTP {response.status_code}")
                return
            self.logged_in = True
            self.set_connection_state(True)
            self.status_text.set("Login successful")
            self.load_factory_locations(silent=True)
            messagebox.showinfo("Login", "Logged in successfully.")
        except Exception as exc:
            self.logged_in = False
            self.set_connection_state(False)
            messagebox.showerror("Login", f"Login error: {exc}")

    def set_connection_state(self, is_online: bool) -> None:
        self.conn_text.set("Online" if is_online else "Offline")
        color = "#00e676" if is_online else "#dc3545"
        if hasattr(self, "_conn_dot"):
            self._conn_dot.config(fg=color)

    def sync_from_server(self, silent: bool = False) -> bool:
        base = DEFAULT_BASE_URL.rstrip("/")
        try:
            response = self.session.get(f"{base}/requests", timeout=30)
            if response.status_code != 200:
                self.set_connection_state(False)
                if not silent:
                    messagebox.showerror("Sync", f"Failed to sync: HTTP {response.status_code}")
                return False
            data = response.json()
            items = data.get("items", [])
            self._last_server_items = items
            self._populate_from_server_items(items)
            self.load_factory_locations(silent=True)
            self.set_connection_state(True)
            self.status_text.set(f"Synced {len(items)} requests at {datetime.now().strftime('%H:%M:%S')}")
            return True
        except Exception as exc:
            self.set_connection_state(False)
            if not silent:
                messagebox.showerror("Sync", f"Sync error: {exc}")
            return False

    def schedule_auto_sync(self) -> None:
        if self.auto_sync_enabled.get() and self.logged_in:
            self.sync_from_server(silent=True)
        self.root.after(10000, self.schedule_auto_sync)

    def _is_simple_bill_upload_item(self, item: dict) -> bool:
        entry_type = (item.get("entry_type") or "").strip().lower()
        if entry_type:
            return entry_type == "simple_bill_upload"

        # Fallback for older server payloads that don't include entry_type.
        item_category = (item.get("item_category") or "").strip().lower()
        item_name = (item.get("item_name") or "").strip().lower()
        reason = (item.get("reason") or "").strip().lower()
        return (
            item_category == "bill upload"
            and item_name == "actual bill upload"
            and reason == "actual bill uploaded via simple tab"
        )

    def _populate_from_server_items(self, items: list[dict]) -> None:
        """Populate the treeviews directly from server-fetched items. Never reads display data from SQLite."""
        self.bill_paths.clear()
        for row in self.tree.get_children():
            self.tree.delete(row)
        for row in self.bill_tree.get_children():
            self.bill_tree.delete(row)

        new_req_count = 0
        new_bill_count = 0
        first_new_request_added = False
        first_new_bill_added = False

        for it in items:
            req_id = int(it.get("id", 0))
            is_simple_bill = self._is_simple_bill_upload_item(it)
            self.bill_paths[req_id] = it.get("bill_image_path") or ""
            is_new = req_id not in self._viewed_ids

            req_row_values = (req_id, it.get("request_date"), it.get("factory_id"),
                              it.get("vendor"), it.get("item_name"), it.get("final_amount"),
                              it.get("requested_by"), it.get("approval_status"),
                              it.get("payment_status"), it.get("updated_at"))
            bill_row_values = (req_id, it.get("request_date"), it.get("factory_id"),
                               it.get("vendor"), it.get("requested_by"),
                               it.get("approval_status"), it.get("updated_at"))

            if is_simple_bill:
                tag = "new_bill" if (is_new and not first_new_bill_added) else ""
                self.bill_tree.insert("", "end", values=bill_row_values, tags=(tag,) if tag else ())
                if is_new:
                    new_bill_count += 1
                    first_new_bill_added = True
            else:
                tag = "new_request" if (is_new and not first_new_request_added) else ""
                self.tree.insert("", "end", values=req_row_values, tags=(tag,) if tag else ())
                if is_new:
                    new_req_count += 1
                    first_new_request_added = True

        self.new_requests_count = new_req_count
        self.new_bills_count = new_bill_count
        self._update_tab_labels()

    # kept for compatibility but no longer used for display — only viewed_at is written to SQLite
    def save_requests_to_db(self, items: list[dict]) -> None:
        pass

    def _update_tab_labels(self) -> None:
        """Update tab labels with notification badges."""
        if not self.notebook or not self.requests_frame or not self.bills_frame:
            return
        req_label = f"Requests" + (f" ({self.new_requests_count})" if self.new_requests_count > 0 else "")
        bill_label = f"Bill Uploads" + (f" ({self.new_bills_count})" if self.new_bills_count > 0 else "")
        self.notebook.tab(self.requests_frame, text=req_label)
        self.notebook.tab(self.bills_frame, text=bill_label)

    def _mark_item_as_viewed(self, req_id: int) -> None:
        """Track viewed IDs in-memory only and refresh the current server-backed view."""
        self._viewed_ids.add(int(req_id))
        self._populate_from_server_items(self._last_server_items)

    def _preview_location(self, location: str) -> str:
        parsed = self._parse_location_text(location)
        if not parsed:
            return "Not set / invalid"
        lat, lon, radius = parsed
        return f"Lat {lat:.6f}, Lon {lon:.6f}, Radius {radius:.0f}m"

    def _parse_location_text(self, raw: str) -> tuple[float, float, float] | None:
        text = (raw or "").strip()
        if not text:
            return None
        parts = [x.strip() for x in text.split(",") if x.strip()]
        if len(parts) < 2:
            return None
        try:
            lat = float(parts[0])
            lon = float(parts[1])
            radius = float(parts[2]) if len(parts) >= 3 else 250.0
        except ValueError:
            return None
        return (lat, lon, radius)

    def _preview_location(self, location: str) -> str:
        parsed = self._parse_location_text(location)
        if not parsed:
            return "Not set / invalid"
        lat, lon, radius = parsed
        return f"Lat {lat:.6f}, Lon {lon:.6f}, Radius {radius:.0f}m"

    def load_factory_locations(self, silent: bool = False) -> None:
        base = DEFAULT_BASE_URL.rstrip("/")
        try:
            response = self.session.get(f"{base}/masters/factories", timeout=20)
            if response.status_code != 200:
                self.set_connection_state(False)
                if not silent:
                    messagebox.showerror("Factories", f"Failed to load factories: HTTP {response.status_code}")
                return

            data = response.json()
            items = data.get("items", [])
            self.factories_cache = {int(x["id"]): x for x in items if "id" in x}

            for row in self.factory_tree.get_children():
                self.factory_tree.delete(row)

            for it in items:
                fid = int(it.get("id", 0))
                name = it.get("name", "")
                location = (it.get("location") or "").strip()
                self.factory_tree.insert("", "end", iid=str(fid), values=(fid, name, location, self._preview_location(location)))

            self.set_connection_state(True)
        except Exception as exc:
            self.set_connection_state(False)
            if not silent:
                messagebox.showerror("Factories", f"Error loading factories: {exc}")

    def on_factory_row_select(self, _event=None) -> None:
        selected = self.factory_tree.focus()
        if not selected:
            return
        vals = self.factory_tree.item(selected, "values")
        if not vals:
            return
        self.factory_name_var.set(str(vals[1]))
        self.factory_location_var.set(str(vals[2]))

    def save_factory_location(self) -> None:
        selected = self.factory_tree.focus()
        if not selected:
            messagebox.showwarning("Factories", "Select a factory first.")
            return

        factory_id = int(selected)
        row = self.factories_cache.get(factory_id)
        if not row:
            messagebox.showerror("Factories", "Selected factory not found in cache.")
            return

        location = (self.factory_location_var.get() or "").strip()
        if location and not self._parse_location_text(location):
            messagebox.showerror(
                "Factories",
                "Location format must be: latitude,longitude,radiusMeters\nExample: 12.9716,77.5946,250",
            )
            return

        payload = {
            "name": row.get("name", ""),
            "extra1": location,
            "extra2": "",
            "extra3": "",
        }

        base = DEFAULT_BASE_URL.rstrip("/")
        try:
            response = self.session.put(
                f"{base}/masters/factories/{factory_id}",
                json=payload,
                timeout=20,
            )
            body = response.json() if response.headers.get("Content-Type", "").startswith("application/json") else {}
            if response.status_code != 200:
                self.set_connection_state(False)
                messagebox.showerror("Factories", self._extract_error_message(body, response.status_code))
                return

            self.set_connection_state(True)
            self.status_text.set("Factory location updated")
            self.load_factory_locations(silent=True)
            messagebox.showinfo("Factories", body.get("message", "Factory location updated"))
        except Exception as exc:
            self.set_connection_state(False)
            messagebox.showerror("Factories", f"Failed to save location: {exc}")

    def open_selected_factory_map(self) -> None:
        text = (self.factory_location_var.get() or "").strip()
        parsed = self._parse_location_text(text)
        if not parsed:
            messagebox.showwarning("Factories", "Enter valid location first: latitude,longitude,radius")
            return
        lat, lon, _radius = parsed
        webbrowser.open_new_tab(f"https://maps.google.com/?q={lat},{lon}")

    def selected_request_id(self) -> int | None:
        item = self.tree.focus()
        if not item:
            messagebox.showwarning("Select", "Select a request first.")
            return None
        vals = self.tree.item(item, "values")
        if not vals:
            return None
        req_id = int(vals[0])
        self._mark_item_as_viewed(req_id)
        return req_id

    def selected_request_id_any(self) -> int | None:
        req_id = None
        main_item = self.tree.focus()
        bill_item = self.bill_tree.focus()
        if main_item:
            vals = self.tree.item(main_item, "values")
            if vals:
                req_id = int(vals[0])
        elif bill_item:
            vals = self.bill_tree.item(bill_item, "values")
            if vals:
                req_id = int(vals[0])
        if req_id is None:
            messagebox.showwarning("Select", "Select a request or bill upload first.")
            return None
        self._mark_item_as_viewed(req_id)
        return req_id

    def approve_selected(self) -> None:
        req_id = self.selected_request_id()
        if req_id is None:
            return
        self.open_approve_dialog(req_id)

    def open_approve_dialog(self, req_id: int) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("Approve Request")
        dialog.geometry("460x390")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()

        amount_var = tk.StringVar()
        priority_var = tk.StringVar(value="Medium")
        expected_var = tk.StringVar()

        ttk.Label(dialog, text="Approved Amount", font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=14, pady=(14, 4))
        ttk.Entry(dialog, textvariable=amount_var).pack(fill="x", padx=14)

        ttk.Label(dialog, text="Priority", font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=14, pady=(12, 4))
        ttk.Combobox(dialog, textvariable=priority_var, values=["High", "Medium", "Low"], state="readonly").pack(fill="x", padx=14)

        ttk.Label(dialog, text="Expected Payment Date (YYYY-MM-DD, optional)", font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=14, pady=(12, 4))
        ttk.Entry(dialog, textvariable=expected_var).pack(fill="x", padx=14)

        ttk.Label(dialog, text="Remarks (optional)", font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=14, pady=(12, 4))
        remarks_box = tk.Text(dialog, height=4)
        remarks_box.pack(fill="both", padx=14)

        status_var = tk.StringVar(value="")
        status_label = ttk.Label(dialog, textvariable=status_var, wraplength=420, justify="left")
        status_label.pack(fill="x", padx=14, pady=(12, 0))

        def on_submit() -> None:
            amount = amount_var.get().strip()
            if not amount:
                status_var.set("Approved amount is required.")
                status_label.configure(foreground="#b02a37")
                return
            try:
                if float(amount) <= 0:
                    status_var.set("Approved amount must be greater than zero.")
                    status_label.configure(foreground="#b02a37")
                    return
            except ValueError:
                status_var.set("Approved amount must be a valid number.")
                status_label.configure(foreground="#b02a37")
                return

            expected_date = expected_var.get().strip()
            if expected_date:
                try:
                    datetime.strptime(expected_date, "%Y-%m-%d")
                except ValueError:
                    status_var.set("Expected payment date must be in YYYY-MM-DD format.")
                    status_label.configure(foreground="#b02a37")
                    return

            payload = {
                "approved_amount": amount,
                "remarks": remarks_box.get("1.0", "end").strip(),
                "priority": priority_var.get().strip() or "Medium",
            }
            if expected_date:
                payload["expected_payment_date"] = expected_date

            success, message = self._perform_action(f"/requests/{req_id}/approve", payload)
            status_var.set(message)
            status_label.configure(foreground="#1f8a43" if success else "#b02a37")
            if success:
                self.sync_from_server(silent=True)
                self.root.after(900, dialog.destroy)

        btn_row = ttk.Frame(dialog)
        btn_row.pack(fill="x", padx=14, pady=14)
        ttk.Button(btn_row, text="Cancel", command=dialog.destroy).pack(side="right", padx=(6, 0))
        ttk.Button(btn_row, text="Approve", command=on_submit).pack(side="right")

        dialog.wait_window()

    def reject_selected(self) -> None:
        req_id = self.selected_request_id()
        if req_id is None:
            return
        self.open_text_action_dialog(
            title="Reject Request",
            req_id=req_id,
            path_template="/requests/{req_id}/reject",
            field_name="reason",
            field_label="Rejection Reason",
            submit_text="Reject",
            required=True,
        )

    def hold_selected(self) -> None:
        req_id = self.selected_request_id()
        if req_id is None:
            return
        self.open_text_action_dialog(
            title="Hold Request",
            req_id=req_id,
            path_template="/requests/{req_id}/hold",
            field_name="remarks",
            field_label="Hold Remarks",
            submit_text="Move to Hold",
            required=False,
        )

    def _expected_delete_password(self) -> str:
        # Optional deployment override; otherwise use the admin login password entered in this app.
        return (os.getenv("ADMIN_DELETE_PASSWORD") or self.password.get() or "").strip()

    def delete_selected(self) -> None:
        req_id = self.selected_request_id_any()
        if req_id is None:
            return

        if not messagebox.askyesno("Delete Entry", f"Delete entry #{req_id}? This cannot be undone."):
            return

        expected = self._expected_delete_password()
        entered = simpledialog.askstring(
            "Delete Password",
            "Enter delete password to confirm:",
            show="*",
            parent=self.root,
        )
        if entered is None:
            return
        if not expected or entered.strip() != expected:
            messagebox.showerror("Delete Entry", "Invalid delete password.")
            return

        base = DEFAULT_BASE_URL.rstrip("/")
        try:
            response = self.session.delete(f"{base}/requests/{req_id}", timeout=30)
            body = response.json() if response.headers.get("Content-Type", "").startswith("application/json") else {}
            if response.status_code != 200:
                self.set_connection_state(False)
                messagebox.showerror("Delete Entry", self._extract_error_message(body, response.status_code))
                return
            self.set_connection_state(True)
            self.status_text.set(body.get("message", f"Entry #{req_id} deleted"))
            self.sync_from_server(silent=True)
            messagebox.showinfo("Delete Entry", body.get("message", "Deleted"))
        except Exception as exc:
            self.set_connection_state(False)
            messagebox.showerror("Delete Entry", f"Delete failed: {exc}")

    def open_text_action_dialog(
        self,
        title: str,
        req_id: int,
        path_template: str,
        field_name: str,
        field_label: str,
        submit_text: str,
        required: bool,
    ) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.geometry("460x300")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()

        ttk.Label(dialog, text=field_label, font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=14, pady=(14, 4))
        text_box = tk.Text(dialog, height=8)
        text_box.pack(fill="both", expand=True, padx=14)

        status_var = tk.StringVar(value="")
        status_label = ttk.Label(dialog, textvariable=status_var, wraplength=420, justify="left")
        status_label.pack(fill="x", padx=14, pady=(12, 0))

        def on_submit() -> None:
            value = text_box.get("1.0", "end").strip()
            if required and not value:
                status_var.set(f"{field_label} is required.")
                status_label.configure(foreground="#b02a37")
                return

            success, message = self._perform_action(
                path_template.format(req_id=req_id),
                {field_name: value},
            )
            status_var.set(message)
            status_label.configure(foreground="#1f8a43" if success else "#b02a37")
            if success:
                self.sync_from_server(silent=True)
                self.root.after(900, dialog.destroy)

        btn_row = ttk.Frame(dialog)
        btn_row.pack(fill="x", padx=14, pady=14)
        ttk.Button(btn_row, text="Cancel", command=dialog.destroy).pack(side="right", padx=(6, 0))
        ttk.Button(btn_row, text=submit_text, command=on_submit).pack(side="right")

        dialog.wait_window()

    def view_bill_selected(self) -> None:
        req_id = self.selected_request_id_any()
        if req_id is None:
            return
        path = (self.bill_paths.get(req_id) or "").strip()
        if not path:
            messagebox.showinfo("Bill", "No bill file attached for this request.")
            return

        # If the same bill is already loaded in preview, avoid refetching and reuse it.
        if req_id == self.preview_req_id and (self._preview_pil_image is not None or self._preview_photo is not None):
            self.preview_status.set(f"Previewing request #{req_id} - {self.preview_filename}")
            if self.notebook and self.preview_frame:
                self.notebook.select(self.preview_frame)
            return

        resp, filename, err = self._fetch_bill_response(req_id, stream=False)
        if err:
            self.preview_status.set(err)
            self._show_preview_message(err)
            messagebox.showerror("Bill Error", err)
            return

        content = resp.content
        self.preview_req_id = req_id
        self.preview_filename = filename
        self._render_bill_preview(content, filename, resp.headers.get("Content-Type", ""))
        self.preview_status.set(f"Previewing request #{req_id} - {filename}")
        if self.notebook and self.preview_frame:
            self.notebook.select(self.preview_frame)

    def download_bill_selected(self) -> None:
        req_id = self.selected_request_id_any()
        if req_id is None:
            return
        path = (self.bill_paths.get(req_id) or "").strip()
        if not path:
            messagebox.showinfo("Bill", "No bill file attached for this request.")
            return

        resp, filename, err = self._fetch_bill_response(req_id, stream=True)
        if err:
            messagebox.showerror("Download Bill", err)
            return

        ext = Path(filename).suffix or ".bin"
        default_name = f"request_{req_id}_bill{ext}"
        out_file = filedialog.asksaveasfilename(
            title="Save Bill File",
            defaultextension=ext,
            initialfile=default_name,
            filetypes=[("All Files", "*.*")],
        )
        if not out_file:
            return

        try:
            with open(out_file, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1024 * 64):
                    if chunk:
                        f.write(chunk)
            messagebox.showinfo("Download Bill", f"Bill downloaded successfully:\n{out_file}")
        except Exception as exc:
            messagebox.showerror("Download Bill", f"Failed to save file: {exc}")

    def _fetch_bill_response(self, req_id: int, stream: bool) -> tuple[requests.Response | None, str, str | None]:
        base = DEFAULT_BASE_URL.rstrip("/")
        endpoint = f"{base}/requests/{req_id}/bill"

        # Prefer last known-good URL for this request, if any.
        last_url = (self._last_bill_url_by_req.get(req_id) or "").strip()
        if last_url:
            try:
                cached_resp = self.session.get(last_url, timeout=30, stream=stream)
                if cached_resp.status_code == 200:
                    return cached_resp, self._filename_from_response(cached_resp, last_url, req_id), None
            except Exception:
                pass

        try:
            first = self.session.get(endpoint, allow_redirects=False, timeout=20, stream=stream)
        except Exception as exc:
            return None, "", f"Failed to contact server: {exc}"

        if first.status_code in (301, 302, 307, 308):
            location = first.headers.get("Location", "")
            if not location or "/login" in location:
                return None, "", "Session expired. Please login again."
            target = location if location.startswith("http") else urljoin(base + "/", location.lstrip("/"))
            try:
                resp = self.session.get(target, timeout=30, stream=stream)
            except Exception as exc:
                return None, "", f"Failed to fetch bill file: {exc}"
            if resp.status_code != 200:
                return None, "", f"Failed to fetch bill file (HTTP {resp.status_code})"
            self._last_bill_url_by_req[req_id] = target
            return resp, self._filename_from_response(resp, target, req_id), None

        if first.status_code == 200:
            return first, self._filename_from_response(first, endpoint, req_id), None

        if first.status_code in (401, 403):
            return None, "", "Session expired. Please login again."

        detail = ""
        try:
            detail = first.json().get("detail", "")
        except Exception:
            pass
        return None, "", (detail or f"Server returned HTTP {first.status_code}")

    def _filename_from_response(self, resp: requests.Response, source_url: str, req_id: int) -> str:
        cd = resp.headers.get("Content-Disposition", "")
        if cd:
            m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', cd, re.IGNORECASE)
            if m:
                name = m.group(1).strip()
                if name:
                    return Path(name).name
        guessed = Path(source_url.split("?", 1)[0]).name
        if guessed and "." in guessed:
            return guessed
        ctype = (resp.headers.get("Content-Type") or "").lower()
        if "png" in ctype:
            return f"request_{req_id}_bill.png"
        if "jpeg" in ctype or "jpg" in ctype:
            return f"request_{req_id}_bill.jpg"
        if "pdf" in ctype:
            return f"request_{req_id}_bill.pdf"
        return f"request_{req_id}_bill.bin"

    def _show_preview_message(self, message: str) -> None:
        if not self.preview_canvas:
            return
        self.preview_canvas.delete("all")
        self.preview_canvas.create_text(18, 18, anchor="nw", text=message, fill="#1a3a6e", font=("Segoe UI", 11))
        self.preview_canvas.configure(scrollregion=(0, 0, 800, 500))

    def _render_bill_preview(self, content: bytes, filename: str, content_type: str) -> None:
        lower_name = filename.lower()
        ctype = (content_type or "").lower()

        # ── PDF Preview ──
        if lower_name.endswith(".pdf") or "application/pdf" in ctype:
            if fitz is None:
                self._show_preview_message("PDF preview unavailable (PyMuPDF not installed). Use Download Bill to open it.")
                return
            try:
                pdf_doc = fitz.open(stream=content, filetype="pdf")
                if pdf_doc.page_count == 0:
                    self._show_preview_message("PDF is empty.")
                    return
                # Render first page to image
                page = pdf_doc[0]
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))  # 2x zoom for clarity
                img_data = pix.tobytes("ppm")
                img = Image.open(io.BytesIO(img_data))
                self._preview_pil_image = img
                self._redraw_preview_image()
                self.preview_status.set(f"PDF preview (page 1 of {pdf_doc.page_count}) — {filename}")
                pdf_doc.close()
                return
            except Exception as exc:
                self._show_preview_message(f"Failed to render PDF: {exc}")
                return

        # ── Image Preview ──
        if Image is None or ImageTk is None:
            self._show_preview_message("Image preview needs Pillow. Use Download Bill if preview is unavailable.")
            return

        try:
            img = Image.open(io.BytesIO(content))
            self._preview_pil_image = img
            self._redraw_preview_image()
        except Exception:
            self._show_preview_message("This file type is not previewable. Use Download Bill.")

    def _on_preview_canvas_resize(self, _event=None) -> None:
        if self._preview_pil_image is not None:
            self._redraw_preview_image()

    def _redraw_preview_image(self) -> None:
        if not self.preview_canvas or self._preview_pil_image is None or ImageTk is None:
            return
        canvas_w = max(self.preview_canvas.winfo_width() - 20, 200)
        canvas_h = max(self.preview_canvas.winfo_height() - 20, 200)
        img = self._preview_pil_image.copy()
        img.thumbnail((canvas_w, canvas_h))
        self._preview_photo = ImageTk.PhotoImage(img)
        self.preview_canvas.delete("all")
        self.preview_canvas.create_image(10, 10, anchor="nw", image=self._preview_photo)
        self.preview_canvas.configure(scrollregion=(0, 0, self._preview_photo.width() + 20, self._preview_photo.height() + 20))

    def export_local_excel(self) -> None:
        if Workbook is None:
            messagebox.showerror("Export", "openpyxl is not installed. Please rebuild environment with openpyxl.")
            return

        rows = [
            (
                it.get("id"),
                it.get("request_date"),
                it.get("factory_id"),
                it.get("vendor"),
                it.get("item_name"),
                it.get("qty"),
                it.get("unit"),
                it.get("final_amount"),
                it.get("requested_by"),
                it.get("approval_status"),
                it.get("payment_status"),
                it.get("updated_at"),
                datetime.now().isoformat(timespec="seconds"),
            )
            for it in self._last_server_items
        ]

        if not rows:
            messagebox.showwarning("Export", "No server data available to export. Please sync first.")
            return

        default_name = f"admin_server_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        out_file = filedialog.asksaveasfilename(
            title="Save Server Data Excel",
            defaultextension=".xlsx",
            initialdir=str(app_data_dir()),
            initialfile=default_name,
            filetypes=[("Excel Workbook", "*.xlsx")],
        )
        if not out_file:
            return

        wb = Workbook()
        ws = wb.active
        ws.title = "Admin Server Data"
        headers = [
            "ID",
            "Request Date",
            "Factory ID",
            "Vendor",
            "Item Name",
            "Qty",
            "Unit",
            "Final Amount",
            "Requested By",
            "Approval Status",
            "Payment Status",
            "Updated At",
            "Synced At",
        ]
        ws.append(headers)
        for row in rows:
            ws.append(list(row))

        wb.save(out_file)
        messagebox.showinfo("Export", f"Server data exported successfully:\n{out_file}")

    def _perform_action(self, path: str, data: dict[str, str]) -> tuple[bool, str]:
        base = DEFAULT_BASE_URL.rstrip("/")
        try:
            response = self.session.post(f"{base}{path}", data=data, timeout=30)
            body = response.json() if response.headers.get("Content-Type", "").startswith("application/json") else {}
            if response.status_code != 200:
                self.set_connection_state(False)
                return False, self._extract_error_message(body, response.status_code)
            self.set_connection_state(True)
            message = body.get("message", "Updated")
            self.status_text.set(message)
            return True, message
        except Exception as exc:
            self.set_connection_state(False)
            return False, f"Request failed: {exc}"

    def _post_action(self, path: str, data: dict[str, str]) -> None:
        success, message = self._perform_action(path, data)
        if not success:
            messagebox.showerror("Action", message)
            return
        messagebox.showinfo("Action", message)
        self.sync_from_server(silent=True)

    def _extract_error_message(self, body: dict, status_code: int) -> str:
        detail = body.get("detail")
        if isinstance(detail, list) and detail:
            first = detail[0]
            if isinstance(first, dict):
                msg = first.get("msg") or "Validation error"
                loc = first.get("loc") or []
                field = loc[-1] if isinstance(loc, list) and loc else "field"
                return f"{msg} ({field})"
        if isinstance(detail, str) and detail.strip():
            return detail
        return f"Action failed (HTTP {status_code})"


def main() -> int:
    root = tk.Tk()
    AdminLocalClient(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
