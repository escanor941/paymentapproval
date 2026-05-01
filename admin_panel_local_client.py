import os
import sqlite3
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from urllib.parse import urljoin
import webbrowser

import requests

try:
    from openpyxl import Workbook
except Exception:  # pragma: no cover - optional import safety
    Workbook = None

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
        self.root.title("EMD Admin Panel - Local EXE")
        self.root.geometry("1220x680")

        self.session = requests.Session()

        self.base_url = tk.StringVar(value=DEFAULT_BASE_URL)
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

        self._build_ui()
        self.load_local_cache()
        self.schedule_auto_sync()

    def _build_ui(self) -> None:
        top = ttk.Frame(self.root, padding=10)
        top.pack(fill="x")

        ttk.Label(top, text="Server URL").grid(row=0, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.base_url, width=44).grid(row=1, column=0, padx=(0, 8), sticky="w")

        ttk.Label(top, text="Username").grid(row=0, column=1, sticky="w")
        ttk.Entry(top, textvariable=self.username, width=18).grid(row=1, column=1, padx=(0, 8), sticky="w")

        ttk.Label(top, text="Password").grid(row=0, column=2, sticky="w")
        ttk.Entry(top, textvariable=self.password, show="*", width=18).grid(row=1, column=2, padx=(0, 8), sticky="w")

        ttk.Button(top, text="Login", command=self.login).grid(row=1, column=3, padx=(0, 6))
        ttk.Button(top, text="Sync From Server", command=self.sync_from_server).grid(row=1, column=4, padx=(0, 6))
        ttk.Button(top, text="View Bill", command=self.view_bill_selected).grid(row=1, column=5, padx=(0, 6))
        ttk.Button(top, text="Approve", command=self.approve_selected).grid(row=1, column=6, padx=(0, 6))
        ttk.Button(top, text="Reject", command=self.reject_selected).grid(row=1, column=7, padx=(0, 6))
        ttk.Button(top, text="Hold", command=self.hold_selected).grid(row=1, column=8, padx=(0, 6))
        ttk.Button(top, text="Export Local Excel", command=self.export_local_excel).grid(row=1, column=9, padx=(0, 6))

        ttk.Label(top, textvariable=self.status_text, foreground="#0b5ed7").grid(
            row=2, column=0, columnspan=7, pady=(8, 0), sticky="w"
        )
        tk.Label(top, textvariable=self.conn_text, fg="#dc3545", font=("Segoe UI", 10, "bold")).grid(
            row=2, column=7, columnspan=1, pady=(8, 0), sticky="w"
        )
        ttk.Checkbutton(top, text="Auto Sync (10s)", variable=self.auto_sync_enabled).grid(
            row=2, column=8, columnspan=2, pady=(8, 0), sticky="w"
        )

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
        locations_tab = ttk.Frame(body)
        
        body.add(self.requests_frame, text="Requests")
        body.add(self.bills_frame, text="Bill Uploads")
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

    def login(self) -> None:
        base = self.base_url.get().rstrip("/")
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
        for child in self.root.winfo_children():
            if isinstance(child, ttk.Frame):
                for widget in child.winfo_children():
                    if isinstance(widget, tk.Label) and widget.cget("textvariable") == str(self.conn_text):
                        widget.config(fg="#1f8a43" if is_online else "#dc3545")
                        return

    def sync_from_server(self, silent: bool = False) -> bool:
        base = self.base_url.get().rstrip("/")
        try:
            response = self.session.get(f"{base}/requests", timeout=30)
            if response.status_code != 200:
                self.set_connection_state(False)
                if not silent:
                    messagebox.showerror("Sync", f"Failed to sync: HTTP {response.status_code}")
                return False
            data = response.json()
            items = data.get("items", [])
            self.save_requests_to_db(items)
            self.load_local_cache()
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

    def save_requests_to_db(self, items: list[dict]) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        with sqlite3.connect(db_path()) as conn:
            for it in items:
                conn.execute(
                    """
                    INSERT INTO requests_cache (
                        id, request_date, factory_id, item_category, vendor, item_name, qty, unit, final_amount,
                        requested_by, approval_status, payment_status, bill_image_path, updated_at, raw_json, synced_at, viewed_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 
                        (SELECT viewed_at FROM requests_cache WHERE id = ?))
                    ON CONFLICT(id) DO UPDATE SET
                        request_date=excluded.request_date,
                        factory_id=excluded.factory_id,
                        item_category=excluded.item_category,
                        vendor=excluded.vendor,
                        item_name=excluded.item_name,
                        qty=excluded.qty,
                        unit=excluded.unit,
                        final_amount=excluded.final_amount,
                        requested_by=excluded.requested_by,
                        approval_status=excluded.approval_status,
                        payment_status=excluded.payment_status,
                        bill_image_path=excluded.bill_image_path,
                        updated_at=excluded.updated_at,
                        raw_json=excluded.raw_json,
                        synced_at=excluded.synced_at
                    """,
                    (
                        it.get("id"),
                        it.get("request_date"),
                        it.get("factory_id"),
                        it.get("item_category"),
                        it.get("vendor"),
                        it.get("item_name"),
                        it.get("qty"),
                        it.get("unit"),
                        it.get("final_amount"),
                        it.get("requested_by"),
                        it.get("approval_status"),
                        it.get("payment_status"),
                        it.get("bill_image_path"),
                        it.get("updated_at"),
                        str(it),
                        now,
                        it.get("id"),
                    ),
                )
            conn.commit()

    def load_local_cache(self) -> None:
        self.bill_paths.clear()
        for row in self.tree.get_children():
            self.tree.delete(row)
        for row in self.bill_tree.get_children():
            self.bill_tree.delete(row)

        new_req_count = 0
        new_bill_count = 0
        first_new_request_added = False
        first_new_bill_added = False

        with sqlite3.connect(db_path()) as conn:
            rows = conn.execute(
                """
                SELECT id, request_date, factory_id, item_category, vendor, item_name,
                       final_amount, requested_by, approval_status, payment_status, updated_at, bill_image_path, viewed_at
                FROM requests_cache
                ORDER BY id DESC
                """
            ).fetchall()

        for r in rows:
            item_category = (r[3] or "").strip()
            req_row_values = (r[0], r[1], r[2], r[4], r[5], r[6], r[7], r[8], r[9], r[10])
            bill_row_values = (r[0], r[1], r[2], r[4], r[7], r[8], r[10])
            req_id = int(r[0])
            self.bill_paths[req_id] = r[11] or ""
            is_new = r[12] is None  # viewed_at is None means not yet viewed
            
            if item_category.lower() == "bill upload":
                # Only apply red tag to the first (most recent) new bill
                tag = "new_bill" if (is_new and not first_new_bill_added) else ""
                self.bill_tree.insert("", "end", values=bill_row_values, tags=(tag,) if tag else ())
                if is_new:
                    new_bill_count += 1
                    if not first_new_bill_added:
                        first_new_bill_added = True
            else:
                # Only apply red tag to the first (most recent) new request
                tag = "new_request" if (is_new and not first_new_request_added) else ""
                self.tree.insert("", "end", values=req_row_values, tags=(tag,) if tag else ())
                if is_new:
                    new_req_count += 1
                    if not first_new_request_added:
                        first_new_request_added = True

        self.new_requests_count = new_req_count
        self.new_bills_count = new_bill_count
        self._update_tab_labels()

    def _update_tab_labels(self) -> None:
        """Update tab labels with notification badges."""
        if not self.notebook or not self.requests_frame or not self.bills_frame:
            return
        req_label = f"Requests" + (f" ({self.new_requests_count})" if self.new_requests_count > 0 else "")
        bill_label = f"Bill Uploads" + (f" ({self.new_bills_count})" if self.new_bills_count > 0 else "")
        self.notebook.tab(self.requests_frame, text=req_label)
        self.notebook.tab(self.bills_frame, text=bill_label)

    def _mark_item_as_viewed(self, req_id: int) -> None:
        """Mark an item as viewed in the database."""
        now = datetime.now().isoformat(timespec="seconds")
        with sqlite3.connect(db_path()) as conn:
            conn.execute(
                "UPDATE requests_cache SET viewed_at = ? WHERE id = ?",
                (now, req_id)
            )
            conn.commit()
        self.load_local_cache()

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
        base = self.base_url.get().rstrip("/")
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

        base = self.base_url.get().rstrip("/")
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
        req_id = None
        main_item = self.tree.focus()
        bill_item = self.bill_tree.focus()
        if main_item:
            vals = self.tree.item(main_item, "values")
            if vals:
                req_id = int(vals[0])
                self._mark_item_as_viewed(req_id)
        elif bill_item:
            vals = self.bill_tree.item(bill_item, "values")
            if vals:
                req_id = int(vals[0])
                self._mark_item_as_viewed(req_id)

        if req_id is None:
            messagebox.showwarning("Select", "Select a request or bill upload first.")
            return

        path = (self.bill_paths.get(req_id) or "").strip()
        if not path:
            messagebox.showinfo("Bill", "No bill file attached for this request.")
            return
        base = self.base_url.get().rstrip("/") + "/"
        bill_url = path if path.startswith("http://") or path.startswith("https://") else urljoin(base, path.lstrip("/"))
        webbrowser.open_new_tab(bill_url)

    def export_local_excel(self) -> None:
        if Workbook is None:
            messagebox.showerror("Export", "openpyxl is not installed. Please rebuild environment with openpyxl.")
            return

        with sqlite3.connect(db_path()) as conn:
            rows = conn.execute(
                """
                SELECT id, request_date, factory_id, vendor, item_name, qty, unit,
                       final_amount, requested_by, approval_status, payment_status,
                       updated_at, synced_at
                FROM requests_cache
                ORDER BY id DESC
                """
            ).fetchall()

        if not rows:
            messagebox.showwarning("Export", "No local data available to export.")
            return

        default_name = f"admin_local_cache_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        out_file = filedialog.asksaveasfilename(
            title="Save Local Cache Excel",
            defaultextension=".xlsx",
            initialdir=str(app_data_dir()),
            initialfile=default_name,
            filetypes=[("Excel Workbook", "*.xlsx")],
        )
        if not out_file:
            return

        wb = Workbook()
        ws = wb.active
        ws.title = "Admin Local Cache"
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
        messagebox.showinfo("Export", f"Local cache exported successfully:\n{out_file}")

    def _perform_action(self, path: str, data: dict[str, str]) -> tuple[bool, str]:
        base = self.base_url.get().rstrip("/")
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
    init_db()
    root = tk.Tk()
    AdminLocalClient(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
