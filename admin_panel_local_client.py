import os
import sqlite3
import io
import re
import threading
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
        self.root.geometry("1420x820")
        self.root.minsize(1100, 640)
        self._apply_theme()
        self.root.update_idletasks()
        _w, _h = 1420, 820
        _sw = self.root.winfo_screenwidth()
        _sh = self.root.winfo_screenheight()
        self.root.geometry(f"{_w}x{_h}+{(_sw - _w) // 2}+{(_sh - _h) // 2}")

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
        self._pdf_pages: list = []          # PIL Image per PDF page
        self._pdf_current_page: int = 0
        self._pdf_page_label_var = tk.StringVar(value="")
        self.preview_req_id: int | None = None
        self.preview_filename = ""
        self._last_bill_url_by_req: dict[int, str] = {}
        self._viewed_ids: set[int] = set()

        self._last_server_items: list[dict] = []
        self._status_filter: str = ""

        self._build_ui()
        self.status_text.set("Please login to load data from server")
        self.schedule_auto_sync()

    def _apply_theme(self) -> None:
        BG      = "#f0f4f9"   # main content background (matches _MAIN_BG)
        PRIMARY = "#0B2C5F"   # sidebar / header navy
        ACCENT  = "#c8102e"   # EMD red
        WHITE   = "#ffffff"
        style = ttk.Style(self.root)
        style.theme_use("clam")
        self.root.configure(bg=BG)
        style.configure(".",                background=BG, font=("Segoe UI", 10))
        style.configure("TFrame",           background=BG)
        style.configure("TLabel",           background=BG, font=("Segoe UI", 10))
        style.configure("TLabelframe",      background=BG)
        style.configure("TLabelframe.Label",background=BG, font=("Segoe UI", 10, "bold"), foreground=PRIMARY)
        style.configure("Treeview",         background=WHITE, fieldbackground=WHITE,
                        font=("Segoe UI", 10), rowheight=30)
        style.configure("Treeview.Heading", background=PRIMARY, foreground=WHITE,
                        font=("Segoe UI", 10, "bold"), relief="flat", padding=(6, 6))
        style.map("Treeview",
                  background=[("selected", "#1e5faa")],
                  foreground=[("selected", WHITE)])
        style.configure("TEntry",           fieldbackground=WHITE, font=("Segoe UI", 10), padding=5)
        style.configure("TCombobox",        fieldbackground=WHITE, font=("Segoe UI", 10))
        style.configure("TCheckbutton",     background="#061c3d", foreground="#93c5fd",
                        font=("Segoe UI", 9))
        style.configure("TScrollbar",       background="#c4d4e8", troughcolor="#e2e8f0", relief="flat")
        style.configure("TButton",          background=PRIMARY, foreground=WHITE,
                        font=("Segoe UI", 10, "bold"), padding=(10, 5))
        style.map("TButton",
                  background=[("active", "#163d7a")],
                  foreground=[("active", WHITE)])

    def _draw_emd_logo(self, canvas: tk.Canvas) -> None:
        # Background
        canvas.create_rectangle(0, 0, 210, 72, fill="#0d2b4e", outline="")
        # Top red accent strip
        canvas.create_rectangle(0, 0, 210, 5, fill="#c8102e", outline="")
        # "EMD" large bold text
        canvas.create_text(105, 30, text="EMD", fill="#ffffff",
                           font=("Segoe UI", 26, "bold"), anchor="center")
        # Decorative flanking lines
        canvas.create_line(14, 38, 60, 38, fill="#c8102e", width=2)
        canvas.create_line(150, 38, 196, 38, fill="#c8102e", width=2)
        # "Group" text
        canvas.create_text(105, 51, text="GROUP", fill="#a8c4e0",
                           font=("Segoe UI", 9, "bold"), anchor="center")
        # Bottom tagline bar
        canvas.create_rectangle(0, 62, 210, 72, fill="#c8102e", outline="")
        canvas.create_text(105, 67, text="Scaffolding & Form Work", fill="white",
                           font=("Segoe UI", 7), anchor="center")

    # ─────────────────────────────────────────────────────────────────────────
    # DESIGN CONSTANTS
    # ─────────────────────────────────────────────────────────────────────────
    _S_BG     = "#0B2C5F"   # sidebar navy
    _S_HOVER  = "#163d7a"   # sidebar hover
    _S_ACTIVE = "#1e5faa"   # sidebar active
    _S_TEXT   = "#bfdbfe"   # sidebar nav text
    _MAIN_BG  = "#f0f4f9"   # main content background
    _CARD_BG  = "#ffffff"   # card background
    _HDR_BG   = "#0B2C5F"   # top header (matches sidebar)
    _BORDER   = "#e2e8f0"   # card/panel border

    def _build_ui(self) -> None:
        S_BG    = self._S_BG
        S_HOVER = self._S_HOVER
        S_ACTIVE= self._S_ACTIVE
        S_TEXT  = self._S_TEXT
        MAIN_BG = self._MAIN_BG
        CARD_BG = self._CARD_BG
        HDR_BG  = self._HDR_BG
        BORDER  = self._BORDER

        # ── Footer (packed first so it stays at very bottom) ──────────────
        footer = tk.Frame(self.root, bg="#061c3d", height=24)
        footer.pack(side="bottom", fill="x")
        footer.pack_propagate(False)
        tk.Label(footer,
                 text="EMD Group  ·  Purchase Approval System  ·  Created by Daniyal  ·  © 2026",
                 bg="#061c3d", fg="#475569", font=("Segoe UI", 8)).pack(side="right", padx=14)

        # ── Outer wrapper: sidebar | main ─────────────────────────────────
        outer = tk.Frame(self.root, bg=MAIN_BG)
        outer.pack(fill="both", expand=True)

        # ══════════════════════════════════════════════════════════════════
        # SIDEBAR
        # ══════════════════════════════════════════════════════════════════
        sidebar = tk.Frame(outer, bg=S_BG, width=238)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        # ── Logo pane ─────────────────────────────────────────────────────
        logo_pane = tk.Frame(sidebar, bg="#061c3d", height=78)
        logo_pane.pack(fill="x")
        logo_pane.pack_propagate(False)
        logo_c = tk.Canvas(logo_pane, width=238, height=78, bg="#061c3d", highlightthickness=0)
        logo_c.pack()
        logo_c.create_rectangle(0, 0, 238, 6, fill="#c8102e", outline="")
        logo_c.create_text(119, 35, text="EMD", fill="#ffffff",
                           font=("Segoe UI", 28, "bold"), anchor="center")
        logo_c.create_line(16, 48, 66, 48, fill="#c8102e", width=2)
        logo_c.create_line(172, 48, 222, 48, fill="#c8102e", width=2)
        logo_c.create_text(119, 56, text="GROUP", fill="#7aaad4",
                           font=("Segoe UI", 9, "bold"), anchor="center")
        logo_c.create_rectangle(0, 68, 238, 78, fill="#c8102e", outline="")
        logo_c.create_text(119, 73, text="Scaffolding & Form Work",
                           fill="white", font=("Segoe UI", 7), anchor="center")

        # ── Nav menu ──────────────────────────────────────────────────────
        tk.Frame(sidebar, bg="#1e3f6e", height=1).pack(fill="x")
        nav_pane = tk.Frame(sidebar, bg=S_BG)
        nav_pane.pack(fill="both", expand=True, pady=(6, 0))

        self._active_page = "requests"
        self._nav_btns: dict[str, tk.Button] = {}

        nav_items = [
            ("\U0001f4ca   Dashboard",         "dashboard"),
            ("\U0001f4cb   Requests",          "requests"),
            ("\U0001f9fe   Bill Uploads",      "bills"),
            ("\U0001f5bc   Bill Preview",      "preview"),
            ("\U0001f3ed   Factory Locations", "locations"),
        ]
        for label, page_id in nav_items:
            b = tk.Button(
                nav_pane, text=f"  {label}", anchor="w",
                bg=S_BG, fg=S_TEXT,
                font=("Segoe UI", 10), relief="flat", bd=0, cursor="hand2",
                padx=18, pady=10,
                activebackground=S_HOVER, activeforeground="#ffffff",
                command=lambda p=page_id: self._switch_page(p),
            )
            b.pack(fill="x")
            b.bind("<Enter>",
                   lambda e, btn=b, p=page_id: btn.config(
                       bg=S_ACTIVE if p == self._active_page else S_HOVER,
                       fg="#ffffff"))
            b.bind("<Leave>",
                   lambda e, btn=b, p=page_id: btn.config(
                       bg=S_ACTIVE if p == self._active_page else S_BG,
                       fg="#ffffff" if p == self._active_page else S_TEXT))
            self._nav_btns[page_id] = b

        # ── Sidebar footer: credentials + connection ───────────────────────
        tk.Frame(sidebar, bg="#1e3f6e", height=1).pack(side="bottom", fill="x")
        sb_foot = tk.Frame(sidebar, bg="#061c3d")
        sb_foot.pack(side="bottom", fill="x", padx=12, pady=8)

        def _slbl(t):
            return tk.Label(sb_foot, text=t, bg="#061c3d", fg="#64748b",
                            font=("Segoe UI", 7, "bold"))

        _slbl("USERNAME").grid(row=0, column=0, sticky="w", pady=(0, 1))
        ttk.Entry(sb_foot, textvariable=self.username, width=11).grid(row=1, column=0, padx=(0, 5), sticky="ew")
        _slbl("PASSWORD").grid(row=0, column=1, sticky="w")
        ttk.Entry(sb_foot, textvariable=self.password, show="*", width=10).grid(row=1, column=1, sticky="ew")
        ttk.Checkbutton(sb_foot, text="Auto Sync",
                        variable=self.auto_sync_enabled).grid(row=2, column=0, columnspan=2,
                                                              sticky="w", pady=(4, 0))
        conn_row = tk.Frame(sb_foot, bg="#061c3d")
        conn_row.grid(row=3, column=0, columnspan=2, sticky="w", pady=(4, 0))
        self._conn_dot = tk.Label(conn_row, text="●", bg="#061c3d", fg="#dc3545",
                                  font=("Segoe UI", 13))
        self._conn_dot.pack(side="left")
        tk.Label(conn_row, textvariable=self.conn_text, bg="#061c3d", fg="#93c5fd",
                 font=("Segoe UI", 9, "bold")).pack(side="left", padx=4)

        # ══════════════════════════════════════════════════════════════════
        # MAIN AREA (right of sidebar)
        # ══════════════════════════════════════════════════════════════════
        main_area = tk.Frame(outer, bg=MAIN_BG)
        main_area.pack(side="left", fill="both", expand=True)

        # ── Top header bar ────────────────────────────────────────────────
        hdr = tk.Frame(main_area, bg=HDR_BG, height=58)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        self._page_title_var = tk.StringVar(value="Purchase Requests")
        tk.Label(hdr, textvariable=self._page_title_var,
                 bg=HDR_BG, fg="#ffffff",
                 font=("Segoe UI", 13, "bold")).pack(side="left", padx=20, pady=12)

        # Right side of header
        right_hdr = tk.Frame(hdr, bg=HDR_BG)
        right_hdr.pack(side="right", padx=14, pady=8)

        # Status chip
        tk.Label(right_hdr, textvariable=self.status_text,
                 bg="#163d7a", fg="#bfdbfe",
                 font=("Segoe UI", 8), padx=8, pady=4).pack(side="right", padx=(6, 0))

        # Login button in header
        def _hbtn(parent, text, cmd, bg="#163d7a", hov="#1e5faa"):
            b = tk.Button(parent, text=text, command=cmd, bg=bg, fg="#ffffff",
                          font=("Segoe UI", 9, "bold"), relief="flat", cursor="hand2",
                          padx=10, pady=4, bd=0,
                          activebackground=hov, activeforeground="white")
            b.bind("<Enter>", lambda e: b.config(bg=hov))
            b.bind("<Leave>", lambda e: b.config(bg=bg))
            return b

        _hbtn(right_hdr, "\U0001f510 Login", self.login).pack(side="right", padx=3)

        # Search bar
        srch_frame = tk.Frame(right_hdr, bg="#163d7a")
        srch_frame.pack(side="right", padx=(0, 6))
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._apply_search_filter())
        srch = tk.Entry(srch_frame, textvariable=self._search_var,
                        bg="#1a4a80", fg="#bfdbfe", insertbackground="#bfdbfe",
                        font=("Segoe UI", 9), relief="flat", width=28,
                        highlightthickness=1, highlightbackground="#2a5c9a",
                        highlightcolor="#5b8fd4")
        srch.pack(ipady=5, padx=4)
        _PLACEHOLDER = "\U0001f50d  Search vendor / item / ID..."
        srch.insert(0, _PLACEHOLDER)
        srch.bind("<FocusIn>",  lambda e: (srch.delete(0, "end"), srch.config(fg="white"))
                                           if srch.get() == _PLACEHOLDER else None)
        srch.bind("<FocusOut>", lambda e: (srch.config(fg="#bfdbfe"),
                                            srch.insert(0, _PLACEHOLDER),
                                            self._search_var.set(""))
                                           if not srch.get().strip() else None)

        # ── KPI cards strip ───────────────────────────────────────────────
        self._stats_var_total    = tk.StringVar(value="—")
        self._stats_var_pending  = tk.StringVar(value="—")
        self._stats_var_approved = tk.StringVar(value="—")
        self._stats_var_rejected = tk.StringVar(value="—")
        self._stats_var_hold     = tk.StringVar(value="—")
        self._stats_var_amount   = tk.StringVar(value="\u20b9—")

        kpi_strip = tk.Frame(main_area, bg=MAIN_BG)
        kpi_strip.pack(fill="x", padx=14, pady=(12, 4))

        kpi_defs = [
            ("\U0001f4e6 Total",    self._stats_var_total,    "#e8f0fe", "#1d4ed8"),
            ("\u23f3 Pending",  self._stats_var_pending,  "#fff7ed", "#c2410c"),
            ("\u2705 Approved", self._stats_var_approved, "#f0fdf4", "#15803d"),
            ("\u274c Rejected", self._stats_var_rejected, "#fff1f2", "#be123c"),
            ("\u23f3 Partial Approved", self._stats_var_hold,     "#fff3cd", "#856404"),
            ("\u20b9 Amount",   self._stats_var_amount,   "#f0f9ff", "#0369a1"),
        ]
        for label, var, card_bg, val_fg in kpi_defs:
            card = tk.Frame(kpi_strip, bg=card_bg, padx=16, pady=10,
                            highlightthickness=1, highlightbackground=BORDER,
                            highlightcolor=BORDER)
            card.pack(side="left", fill="x", expand=True, padx=4)
            tk.Label(card, text=label, bg=card_bg, fg="#64748b",
                     font=("Segoe UI", 8, "bold")).pack(anchor="w")
            tk.Label(card, textvariable=var, bg=card_bg, fg=val_fg,
                     font=("Segoe UI", 18, "bold")).pack(anchor="w", pady=(2, 0))

        # ── Action toolbar ────────────────────────────────────────────────
        toolbar_wrap = tk.Frame(main_area, bg=CARD_BG,
                                highlightthickness=1, highlightbackground=BORDER)
        toolbar_wrap.pack(fill="x", padx=14, pady=(0, 6))

        def _tbtn(parent, text, cmd, bg, hov):
            b = tk.Button(parent, text=text, command=cmd, bg=bg, fg="white",
                          font=("Segoe UI", 9, "bold"), relief="flat", cursor="hand2",
                          padx=10, pady=7, bd=0,
                          activebackground=hov, activeforeground="white")
            b.bind("<Enter>", lambda e: b.config(bg=hov))
            b.bind("<Leave>", lambda e: b.config(bg=bg))
            return b

        def _sep(parent):
            tk.Frame(parent, bg=BORDER, width=1).pack(side="left", fill="y", padx=5, pady=7)

        _tbtn(toolbar_wrap, "\U0001f504 Sync",          self.sync_from_server,       "#0B2C5F", "#163d7a").pack(side="left", padx=(8, 2))
        _sep(toolbar_wrap)
        _tbtn(toolbar_wrap, "\U0001f9fe View Bill",      self.view_bill_selected,     "#155c8a", "#1e7ab8").pack(side="left", padx=2)
        _tbtn(toolbar_wrap, "\U0001f4e5 Download",       self.download_bill_selected, "#155c8a", "#1e7ab8").pack(side="left", padx=2)
        _sep(toolbar_wrap)
        _tbtn(toolbar_wrap, "\u2705 Approve",            self.approve_selected,       "#166534", "#15803d").pack(side="left", padx=2)
        _tbtn(toolbar_wrap, "\u274c Reject",             self.reject_selected,        "#991b1b", "#b91c1c").pack(side="left", padx=2)
        _tbtn(toolbar_wrap, "\u23f3 Partial Approved",      self.hold_selected,          "#9a3412", "#c2410c").pack(side="left", padx=2)
        _tbtn(toolbar_wrap, "\U0001f5d1 Delete",         self.delete_selected,        "#6b1e1e", "#7f1d1d").pack(side="left", padx=2)
        _sep(toolbar_wrap)
        _tbtn(toolbar_wrap, "\U0001f4ca Export Excel",   self.export_local_excel,     "#3b0764", "#5b21b6").pack(side="left", padx=2)

        # ── Status filter pills ───────────────────────────────────────────
        filter_wrap = tk.Frame(main_area, bg=CARD_BG,
                               highlightthickness=1, highlightbackground=BORDER)
        filter_wrap.pack(fill="x", padx=14, pady=(0, 6))
        tk.Label(filter_wrap, text="STATUS", bg=CARD_BG, fg="#94a3b8",
                 font=("Segoe UI", 8, "bold")).pack(side="left", padx=(12, 6), pady=7)

        self._filter_btns: dict[str, tk.Button] = {}
        # (label, value, normal_bg, normal_fg, active_bg, active_fg)
        filter_opts = [
            ("  All  ",       "",         "#f1f5f9", "#0B2C5F", "#0B2C5F", "#ffffff"),
            ("  Pending  ",   "Pending",  "#fff7ed", "#9a3412", "#c2410c", "#ffffff"),
            ("  Approved  ",  "Approved", "#f0fdf4", "#15803d", "#16a34a", "#ffffff"),
            ("  Rejected  ",  "Rejected", "#fff1f2", "#be123c", "#dc2626", "#ffffff"),
            ("  Partial Approved  ", "Partial Approved", "#fff3cd", "#856404", "#d97706", "#ffffff"),
        ]
        for label, value, nbg, nfg, abg, afg in filter_opts:
            btn = tk.Button(
                filter_wrap, text=label, bg=nbg, fg=nfg,
                font=("Segoe UI", 9, "bold"), relief="flat", cursor="hand2",
                padx=4, pady=5, bd=0,
                activebackground=abg, activeforeground=afg,
                command=lambda v=value: self._apply_status_filter(v),
            )
            btn.bind("<Enter>",  lambda e, b=btn, c=abg, f=afg: b.config(bg=c, fg=f))
            btn.bind("<Leave>",  lambda e, b=btn, v=value, c=nbg, f=nfg: b.config(
                bg=(abg if v == self._status_filter else c),
                fg=(afg if v == self._status_filter else f),
            ) if True else None)
            btn.pack(side="left", padx=3, pady=5)
            self._filter_btns[value] = btn
        self._highlight_filter_btn("")

        # ── Pages container ───────────────────────────────────────────────
        pages_container = tk.Frame(main_area, bg=MAIN_BG)
        pages_container.pack(fill="both", expand=True, padx=14, pady=(0, 6))

        self.requests_frame = tk.Frame(pages_container, bg=MAIN_BG)
        self.bills_frame    = tk.Frame(pages_container, bg=MAIN_BG)
        self.preview_frame  = tk.Frame(pages_container, bg=MAIN_BG)
        locations_tab       = tk.Frame(pages_container, bg=MAIN_BG)
        dashboard_frame     = tk.Frame(pages_container, bg=MAIN_BG)

        self._pages_map = {
            "dashboard": dashboard_frame,
            "requests":  self.requests_frame,
            "bills":     self.bills_frame,
            "preview":   self.preview_frame,
            "locations": locations_tab,
        }
        self._page_titles = {
            "dashboard": "\U0001f4ca  Dashboard Overview",
            "requests":  "\U0001f4cb  Purchase Requests",
            "bills":     "\U0001f9fe  Bill Uploads",
            "preview":   "\U0001f5bc  Bill Preview",
            "locations": "\U0001f3ed  Factory Locations",
        }

        # Show initial page
        self.requests_frame.pack(fill="both", expand=True)
        self._update_nav_active("requests")

        cols = (
            "id", "request_date", "factory_id", "vendor", "item_name",
            "final_amount", "paid_amount", "balance_amount",
            "requested_by", "approval_status", "payment_status", "updated_at",
        )

        # ── Requests page ─────────────────────────────────────────────────
        tree_card = tk.Frame(self.requests_frame, bg=CARD_BG,
                             highlightthickness=1, highlightbackground=BORDER)
        tree_card.pack(fill="both", expand=True)

        self.tree = ttk.Treeview(tree_card, columns=cols, show="headings")
        self.tree.tag_configure("new_request",     background="#ffe4e4", foreground="#b91c1c")
        self.tree.tag_configure("status_approved", background="#f0fdf4", foreground="#15803d")
        self.tree.tag_configure("status_rejected", background="#fff1f2", foreground="#be123c")
        self.tree.tag_configure("status_pending",  background="#fff7ed", foreground="#c2410c")
        self.tree.tag_configure("status_hold",     background="#fff3cd", foreground="#856404")
        self.tree.tag_configure("status_draft",    background="#f8fafc", foreground="#475569")

        col_hdrs = {
            "id": "ID", "request_date": "Date", "factory_id": "Factory",
            "vendor": "Vendor", "item_name": "Item Name",
            "final_amount": "Total (\u20b9)", "paid_amount": "Paid (\u20b9)",
            "balance_amount": "Balance (\u20b9)",
            "requested_by": "Requested By",
            "approval_status": "Approval", "payment_status": "Payment",
            "updated_at": "Updated At",
        }
        for c in cols:
            self.tree.heading(c, text=col_hdrs.get(c, c))

        self.tree.column("id",              width=60,  anchor="center", minwidth=50)
        self.tree.column("request_date",    width=100, anchor="center", minwidth=80)
        self.tree.column("factory_id",      width=70,  anchor="center", minwidth=55)
        self.tree.column("vendor",          width=140, minwidth=90)
        self.tree.column("item_name",       width=155, minwidth=100)
        self.tree.column("final_amount",    width=90,  anchor="e",      minwidth=70)
        self.tree.column("paid_amount",     width=85,  anchor="e",      minwidth=65)
        self.tree.column("balance_amount",  width=85,  anchor="e",      minwidth=65)
        self.tree.column("requested_by",    width=130, minwidth=90)
        self.tree.column("approval_status", width=110, anchor="center", minwidth=90)
        self.tree.column("payment_status",  width=100, anchor="center", minwidth=80)
        self.tree.column("updated_at",      width=155, minwidth=110)

        vs = ttk.Scrollbar(tree_card, orient="vertical",   command=self.tree.yview)
        hs = ttk.Scrollbar(tree_card, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        vs.pack(side="right", fill="y")
        hs.pack(side="bottom", fill="x")
        self.tree.pack(side="left", fill="both", expand=True)

        # ── Bills page ────────────────────────────────────────────────────
        bill_cols = ("id", "request_date", "factory_id", "vendor",
                     "requested_by", "approval_status", "updated_at")
        bill_card = tk.Frame(self.bills_frame, bg=CARD_BG,
                             highlightthickness=1, highlightbackground=BORDER)
        bill_card.pack(fill="both", expand=True)

        self.bill_tree = ttk.Treeview(bill_card, columns=bill_cols, show="headings")
        self.bill_tree.tag_configure("new_bill", background="#ffe4e4", foreground="#b91c1c")
        bill_hdrs = {"id": "ID", "request_date": "Date", "factory_id": "Factory",
                     "vendor": "Vendor", "requested_by": "Uploaded By",
                     "approval_status": "Status", "updated_at": "Updated At"}
        for c in bill_cols:
            self.bill_tree.heading(c, text=bill_hdrs.get(c, c))
        self.bill_tree.column("id",              width=70,  anchor="center")
        self.bill_tree.column("request_date",    width=110, anchor="center")
        self.bill_tree.column("factory_id",      width=80,  anchor="center")
        self.bill_tree.column("vendor",          width=230)
        self.bill_tree.column("requested_by",    width=190)
        self.bill_tree.column("approval_status", width=120, anchor="center")
        self.bill_tree.column("updated_at",      width=230)

        bill_vs = ttk.Scrollbar(bill_card, orient="vertical", command=self.bill_tree.yview)
        self.bill_tree.configure(yscrollcommand=bill_vs.set)
        bill_vs.pack(side="right", fill="y")
        self.bill_tree.pack(side="left", fill="both", expand=True)

        # ── Preview page ──────────────────────────────────────────────────
        prev_top = tk.Frame(self.preview_frame, bg=CARD_BG, pady=8,
                            highlightthickness=1, highlightbackground=BORDER)
        prev_top.pack(fill="x", pady=(0, 6))
        ttk.Label(prev_top, textvariable=self.preview_status,
                  foreground="#0B2C5F").pack(side="left", padx=10)
        ttk.Button(prev_top, text="Load Bill",  command=self.view_bill_selected).pack(side="right", padx=(6, 10))
        ttk.Button(prev_top, text="Download",   command=self.download_bill_selected).pack(side="right", padx=2)
        ttk.Button(prev_top, text="Next ►",     command=self._pdf_next_page).pack(side="right", padx=(0, 2))
        ttk.Label(prev_top, textvariable=self._pdf_page_label_var,
                  foreground="#0B2C5F", font=("Segoe UI", 9, "bold"),
                  width=12, anchor="center").pack(side="right")
        ttk.Button(prev_top, text="◄ Prev",     command=self._pdf_prev_page).pack(side="right", padx=(10, 0))

        prev_wrap = tk.Frame(self.preview_frame, bg=CARD_BG)
        prev_wrap.pack(fill="both", expand=True)
        self.preview_canvas = tk.Canvas(prev_wrap, bg="#ffffff", highlightthickness=0)
        preview_vs = ttk.Scrollbar(prev_wrap, orient="vertical",   command=self.preview_canvas.yview)
        preview_hs = ttk.Scrollbar(prev_wrap, orient="horizontal", command=self.preview_canvas.xview)
        self.preview_canvas.configure(yscrollcommand=preview_vs.set, xscrollcommand=preview_hs.set)
        self.preview_canvas.grid(row=0, column=0, sticky="nsew")
        preview_vs.grid(row=0, column=1, sticky="ns")
        preview_hs.grid(row=1, column=0, sticky="ew")
        prev_wrap.rowconfigure(0, weight=1)
        prev_wrap.columnconfigure(0, weight=1)
        self.preview_canvas.bind("<Configure>", self._on_preview_canvas_resize)

        # ── Locations page ────────────────────────────────────────────────
        loc_top = tk.Frame(locations_tab, bg=CARD_BG, padx=12, pady=8,
                           highlightthickness=1, highlightbackground=BORDER)
        loc_top.pack(fill="x", pady=(0, 6))
        ttk.Label(loc_top, text="Factory Name").grid(row=0, column=0, sticky="w")
        ttk.Entry(loc_top, textvariable=self.factory_name_var, width=28,
                  state="readonly").grid(row=1, column=0, padx=(0, 8), sticky="w")
        ttk.Label(loc_top, text="Location (lat,long,radius)").grid(row=0, column=1, sticky="w")
        ttk.Entry(loc_top, textvariable=self.factory_location_var,
                  width=44).grid(row=1, column=1, padx=(0, 8), sticky="w")
        ttk.Button(loc_top, text="Refresh",   command=self.load_factory_locations).grid(row=1, column=2, padx=(0, 5))
        ttk.Button(loc_top, text="Save",      command=self.save_factory_location).grid(row=1, column=3, padx=(0, 5))
        ttk.Button(loc_top, text="Open Map",  command=self.open_selected_factory_map).grid(row=1, column=4)

        loc_card = tk.Frame(locations_tab, bg=CARD_BG,
                            highlightthickness=1, highlightbackground=BORDER)
        loc_card.pack(fill="both", expand=True)
        loc_cols = ("id", "name", "location", "preview")
        self.factory_tree = ttk.Treeview(loc_card, columns=loc_cols, show="headings")
        self.factory_tree.heading("id",      text="ID")
        self.factory_tree.heading("name",    text="Factory")
        self.factory_tree.heading("location",text="Location")
        self.factory_tree.heading("preview", text="Preview")
        self.factory_tree.column("id",       width=70,  anchor="center")
        self.factory_tree.column("name",     width=220)
        self.factory_tree.column("location", width=420)
        self.factory_tree.column("preview",  width=310)
        self.factory_tree.bind("<<TreeviewSelect>>", self.on_factory_row_select)
        loc_vs = ttk.Scrollbar(loc_card, orient="vertical", command=self.factory_tree.yview)
        self.factory_tree.configure(yscrollcommand=loc_vs.set)
        loc_vs.pack(side="right", fill="y")
        self.factory_tree.pack(side="left", fill="both", expand=True)

    def _switch_page(self, page_id: str) -> None:
        for frame in self._pages_map.values():
            frame.pack_forget()
        target = self._pages_map.get(page_id)
        if target is not None:
            target.pack(fill="both", expand=True)
        self._active_page = page_id
        self._update_nav_active(page_id)
        title = self._page_titles.get(page_id, page_id.title())
        if hasattr(self, "_page_title_var"):
            self._page_title_var.set(title)

    def _update_nav_active(self, active: str) -> None:
        for pid, btn in self._nav_btns.items():
            if pid == active:
                btn.config(bg=self._S_ACTIVE, fg="#ffffff")
            else:
                btn.config(bg=self._S_BG, fg=self._S_TEXT)

    def _apply_search_filter(self) -> None:
        if not hasattr(self, "_last_server_items"):
            return
        query = self._search_var.get().strip().lower()
        if not query or query.startswith("\U0001f50d"):
            self._populate_from_server_items(self._last_server_items)
            return
        filtered = [
            x for x in self._last_server_items
            if not self._is_simple_bill_upload_item(x) and any(
                query in str(x.get(f) or "").lower()
                for f in ("id", "vendor", "item_name", "requested_by", "approval_status")
            )
        ]
        self._populate_from_server_items(filtered)

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
            redirect_to = (response.headers.get("Location") or "").strip()
            if redirect_to.startswith("http"):
                try:
                    redirect_to = urljoin(base + "/", redirect_to)
                except Exception:
                    redirect_to = "/"
            if str(redirect_to).endswith("/login") or str(redirect_to) == "/login":
                self.set_connection_state(False)
                messagebox.showerror("Login", "Invalid username or password")
                return

            auth_check = self.session.get(f"{base}/requests", timeout=20)
            if auth_check.status_code != 200:
                self.set_connection_state(False)
                messagebox.showerror("Login", "Login succeeded but session validation failed. Please try again.")
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
        bills_to_receive: list[int] = []

        for it in items:
            req_id = int(it.get("id", 0))
            is_simple_bill = self._is_simple_bill_upload_item(it)
            self.bill_paths[req_id] = it.get("bill_image_path") or ""
            is_new = req_id not in self._viewed_ids

            req_row_values = (req_id, it.get("request_date"), it.get("factory_id"),
                              it.get("vendor"), it.get("item_name"),
                              f"{float(it.get('final_amount') or 0):.2f}",
                              f"{float(it.get('total_paid') or 0):.2f}",
                              f"{float(it.get('balance_amount') or 0):.2f}",
                              it.get("requested_by"),
                              approval_status,
                              it.get("payment_status"), it.get("updated_at"))
            # Bill uploads always show "Received" — no approve/reject flow needed
            bill_row_values = (req_id, it.get("request_date"), it.get("factory_id"),
                               it.get("vendor"), it.get("requested_by"),
                               "Received", it.get("updated_at"))

            if is_simple_bill:
                tag = "new_bill" if (is_new and not first_new_bill_added) else ""
                self.bill_tree.insert("", "end", values=bill_row_values, tags=(tag,) if tag else ())
                # Auto-mark on server if not yet received
                if (it.get("approval_status") or "") != "Received":
                    bills_to_receive.append(req_id)
                if is_new:
                    new_bill_count += 1
                    first_new_bill_added = True
            else:
                approval_status = (it.get("approval_status") or "").strip()
                # Backward compat: old server may still return "Hold"
                if approval_status == "Hold":
                    approval_status = "Partial Approved"
                if self._status_filter and approval_status != self._status_filter:
                    continue
                if is_new and not first_new_request_added:
                    row_tag = "new_request"
                else:
                    row_tag = {
                        "Approved":         "status_approved",
                        "Rejected":         "status_rejected",
                        "Pending":          "status_pending",
                        "Partial Approved": "status_hold",
                        "Draft":            "status_draft",
                    }.get(approval_status, "")
                self.tree.insert("", "end", values=req_row_values,
                                 tags=(row_tag,) if row_tag else ())
                if is_new:
                    new_req_count += 1
                    first_new_request_added = True

        self.new_requests_count = new_req_count
        self.new_bills_count = new_bill_count
        self._update_tab_labels()
        self._update_stats_bar(items)

        if bills_to_receive and self.logged_in:
            threading.Thread(
                target=self._mark_bills_received,
                args=(bills_to_receive,),
                daemon=True,
            ).start()

    def _mark_bills_received(self, bill_ids: list[int]) -> None:
        """Background thread: mark bill uploads as Received on the server."""
        base = DEFAULT_BASE_URL.rstrip("/")
        for req_id in bill_ids:
            try:
                self.session.post(f"{base}/requests/{req_id}/receive", timeout=10)
            except Exception:
                pass

    def _apply_status_filter(self, status: str) -> None:
        self._status_filter = status
        self._highlight_filter_btn(status)
        self._populate_from_server_items(self._last_server_items)

    def _highlight_filter_btn(self, active: str) -> None:
        normal = {
            "":                 ("#f1f5f9", "#0B2C5F"),
            "Pending":          ("#fff7ed", "#9a3412"),
            "Approved":         ("#f0fdf4", "#15803d"),
            "Rejected":         ("#fff1f2", "#be123c"),
            "Partial Approved": ("#fff3cd", "#856404"),
        }
        selected = {
            "":                 ("#0B2C5F", "#ffffff"),
            "Pending":          ("#c2410c", "#ffffff"),
            "Approved":         ("#16a34a", "#ffffff"),
            "Rejected":         ("#dc2626", "#ffffff"),
            "Partial Approved": ("#d97706", "#ffffff"),
        }
        for value, btn in self._filter_btns.items():
            if value == active:
                bg, fg = selected.get(value, ("#0B2C5F", "#ffffff"))
            else:
                bg, fg = normal.get(value, ("#f1f5f9", "#0B2C5F"))
            btn.config(bg=bg, fg=fg, relief="flat", bd=0)

    # kept for compatibility but no longer used for display — only viewed_at is written to SQLite
    def save_requests_to_db(self, items: list[dict]) -> None:
        pass

    def _update_tab_labels(self) -> None:
        """Update sidebar nav button labels with notification badges."""
        if not hasattr(self, "_nav_btns"):
            return
        req_btn  = self._nav_btns.get("requests")
        bill_btn = self._nav_btns.get("bills")
        req_suffix  = f" ({self.new_requests_count})" if self.new_requests_count > 0 else ""
        bill_suffix = f" ({self.new_bills_count})"    if self.new_bills_count > 0    else ""
        if req_btn:
            req_btn.config(text=f"  \U0001f4cb   Requests{req_suffix}")
        if bill_btn:
            bill_btn.config(text=f"  \U0001f9fe   Bill Uploads{bill_suffix}")

    def _update_stats_bar(self, items: list[dict]) -> None:
        """Refresh the live stats tiles from the current item list."""
        if not hasattr(self, "_stats_var_total"):
            return
        non_bills = [x for x in items if not self._is_simple_bill_upload_item(x)]
        total    = len(non_bills)
        pending  = sum(1 for x in non_bills if (x.get("approval_status") or "") == "Pending")
        approved = sum(1 for x in non_bills if (x.get("approval_status") or "") == "Approved")
        rejected = sum(1 for x in non_bills if (x.get("approval_status") or "") == "Rejected")
        hold     = sum(1 for x in non_bills if (x.get("approval_status") or "") in ("Partial Approved", "Hold"))

        # Amount reflects only the active filter subset
        active_filter = getattr(self, "_status_filter", "")
        if active_filter:
            amount_items = [x for x in non_bills if (x.get("approval_status") or "") == active_filter]
        else:
            amount_items = non_bills
        amount = sum(float(x.get("final_amount") or 0) for x in amount_items)

        self._stats_var_total.set(str(total))
        self._stats_var_pending.set(str(pending))
        self._stats_var_approved.set(str(approved))
        self._stats_var_rejected.set(str(rejected))
        self._stats_var_hold.set(str(hold))
        self._stats_var_amount.set(f"\u20b9{amount:,.0f}")

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
        # Fallback: use the bill currently loaded in preview
        if req_id is None and self.preview_req_id is not None:
            req_id = self.preview_req_id
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
        self.open_partial_approve_dialog(req_id)

    def open_partial_approve_dialog(self, req_id: int) -> None:
        import threading

        dialog = tk.Toplevel(self.root)
        dialog.title(f"Partial Payment — Request #{req_id}")
        dialog.geometry("560x620")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()

        # ── Summary section ────────────────────────────────────────────────
        summary_frame = ttk.LabelFrame(dialog, text="Payment Summary")
        summary_frame.pack(fill="x", padx=14, pady=(14, 4))

        total_var   = tk.StringVar(value="Loading…")
        paid_var    = tk.StringVar(value="—")
        balance_var = tk.StringVar(value="—")

        for label, var in [("Total Amount (₹):", total_var),
                           ("Already Paid (₹):", paid_var),
                           ("Remaining Balance (₹):", balance_var)]:
            row = ttk.Frame(summary_frame)
            row.pack(fill="x", padx=10, pady=2)
            ttk.Label(row, text=label, width=24, anchor="w").pack(side="left")
            ttk.Label(row, textvariable=var, font=("Segoe UI", 10, "bold")).pack(side="left")

        # ── Payment history table ──────────────────────────────────────────
        hist_frame = ttk.LabelFrame(dialog, text="Payment History")
        hist_frame.pack(fill="both", expand=False, padx=14, pady=4)

        h_cols = ("date", "mode", "paid", "balance", "remark")
        hist_tree = ttk.Treeview(hist_frame, columns=h_cols, show="headings", height=5)
        for col, hdr, w in [("date", "Date", 95), ("mode", "Mode", 100),
                             ("paid", "Paid (₹)", 85), ("balance", "Balance (₹)", 90),
                             ("remark", "Remark", 140)]:
            hist_tree.heading(col, text=hdr)
            hist_tree.column(col, width=w, minwidth=60, anchor="center" if col not in ("remark",) else "w")
        hist_hsb = ttk.Scrollbar(hist_frame, orient="horizontal", command=hist_tree.xview)
        hist_tree.configure(xscrollcommand=hist_hsb.set)
        hist_hsb.pack(side="bottom", fill="x")
        hist_tree.pack(fill="both", expand=True)

        # ── Payment entry form ─────────────────────────────────────────────
        form_frame = ttk.LabelFrame(dialog, text="Record Payment")
        form_frame.pack(fill="x", padx=14, pady=4)

        amount_var  = tk.StringVar()
        mode_var    = tk.StringVar(value="Cash")
        remarks_var = tk.StringVar()

        ttk.Label(form_frame, text="Payment Amount (₹) *", font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=10, pady=(8, 2))
        amount_entry = ttk.Entry(form_frame, textvariable=amount_var, font=("Segoe UI", 11))
        amount_entry.pack(fill="x", padx=10)

        ttk.Label(form_frame, text="Payment Mode *", font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=10, pady=(8, 2))
        ttk.Combobox(form_frame, textvariable=mode_var,
                     values=["Cash", "UPI", "Bank Transfer", "Cheque"],
                     state="readonly").pack(fill="x", padx=10)

        ttk.Label(form_frame, text="Remarks (optional)", font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=10, pady=(8, 2))
        ttk.Entry(form_frame, textvariable=remarks_var).pack(fill="x", padx=10, pady=(0, 10))

        # ── Status label + buttons ─────────────────────────────────────────
        status_var = tk.StringVar(value="")
        status_label = ttk.Label(dialog, textvariable=status_var, wraplength=520, justify="left")
        status_label.pack(fill="x", padx=14, pady=(4, 0))

        btn_row = ttk.Frame(dialog)
        btn_row.pack(fill="x", padx=14, pady=10)

        _remaining = [0.0]   # mutable holder so on_submit can read the loaded value

        def _load_summary() -> None:
            base = DEFAULT_BASE_URL.rstrip("/")
            try:
                resp = self.session.get(f"{base}/requests/{req_id}/payment-summary", timeout=20)
                if resp.status_code != 200:
                    dialog.after(0, lambda: status_var.set("Could not load payment summary."))
                    dialog.after(0, lambda: status_label.configure(foreground="#b02a37"))
                    return
                data = resp.json()
                total    = float(data.get("total_amount") or data.get("approved_amount") or 0)
                paid     = float(data.get("total_paid") or 0)
                balance  = float(data.get("balance") or 0)
                _remaining[0] = balance
                history  = data.get("history", [])

                def _update_ui() -> None:
                    total_var.set(f"{total:,.2f}")
                    paid_var.set(f"{paid:,.2f}")
                    balance_var.set(f"{balance:,.2f}")
                    # pre-fill amount with remaining balance
                    amount_var.set(f"{balance:.2f}" if balance > 0 else "0.00")
                    # populate history
                    for row in hist_tree.get_children():
                        hist_tree.delete(row)
                    for p in history:
                        hist_tree.insert("", "end", values=(
                            p.get("payment_date", ""),
                            p.get("payment_mode", ""),
                            f"{float(p.get('paid_amount') or 0):,.2f}",
                            f"{float(p.get('balance_amount') or 0):,.2f}",
                            p.get("remark", ""),
                        ))
                    if not history:
                        hist_tree.insert("", "end", values=("—", "—", "—", "—", "No payments yet"))

                dialog.after(0, _update_ui)
            except Exception as exc:
                dialog.after(0, lambda: status_var.set(f"Load error: {exc}"))
                dialog.after(0, lambda: status_label.configure(foreground="#b02a37"))

        threading.Thread(target=_load_summary, daemon=True).start()

        def on_submit() -> None:
            amount_str = amount_var.get().strip()
            if not amount_str:
                status_var.set("Payment amount is required.")
                status_label.configure(foreground="#b02a37")
                return
            try:
                amount = float(amount_str)
                if amount <= 0:
                    raise ValueError
            except ValueError:
                status_var.set("Payment amount must be a positive number.")
                status_label.configure(foreground="#b02a37")
                return

            remaining = _remaining[0]
            if remaining > 0 and amount > remaining + 0.01:
                status_var.set(f"Amount ₹{amount:.2f} exceeds remaining balance ₹{remaining:.2f}.")
                status_label.configure(foreground="#b02a37")
                return

            payload = {
                "paid_amount": str(amount),
                "payment_mode": mode_var.get().strip() or "Cash",
            }
            remark = remarks_var.get().strip()
            if remark:
                payload["remarks"] = remark

            submit_btn.configure(state="disabled")
            status_var.set("Submitting…")
            status_label.configure(foreground="#555")

            success, message = self._perform_action(f"/requests/{req_id}/partial-approve", payload)
            status_var.set(message)
            status_label.configure(foreground="#1f8a43" if success else "#b02a37")
            submit_btn.configure(state="normal")
            if success:
                self.sync_from_server(silent=True)
                self.root.after(1000, dialog.destroy)

        ttk.Button(btn_row, text="Cancel", command=dialog.destroy).pack(side="right", padx=(6, 0))
        submit_btn = ttk.Button(btn_row, text="Record Payment", command=on_submit)
        submit_btn.pack(side="right")

        amount_entry.focus_set()
        dialog.wait_window()

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
            self._switch_page("preview")
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
        self._switch_page("preview")

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

        # Reset PDF state for every new load
        self._pdf_pages = []
        self._pdf_current_page = 0
        self._pdf_page_label_var.set("")

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
                # Render all pages up-front
                for page_num in range(pdf_doc.page_count):
                    page = pdf_doc[page_num]
                    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))  # 2x zoom for clarity
                    img = Image.open(io.BytesIO(pix.tobytes("ppm")))
                    img.load()   # force decode before the doc is closed
                    self._pdf_pages.append(img)
                pdf_doc.close()
                self._show_pdf_page(0)
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

    def _show_pdf_page(self, page_num: int) -> None:
        if not self._pdf_pages:
            return
        page_num = max(0, min(page_num, len(self._pdf_pages) - 1))
        self._pdf_current_page = page_num
        total = len(self._pdf_pages)
        self._preview_pil_image = self._pdf_pages[page_num]
        self._pdf_page_label_var.set(f"Page {page_num + 1} / {total}")
        self._redraw_preview_image()
        self.preview_status.set(
            f"PDF — Page {page_num + 1} of {total} — {self.preview_filename}"
        )

    def _pdf_prev_page(self) -> None:
        if self._pdf_pages and self._pdf_current_page > 0:
            self._show_pdf_page(self._pdf_current_page - 1)

    def _pdf_next_page(self) -> None:
        if self._pdf_pages and self._pdf_current_page < len(self._pdf_pages) - 1:
            self._show_pdf_page(self._pdf_current_page + 1)

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
