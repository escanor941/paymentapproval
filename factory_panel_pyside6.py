import os
import json
import sqlite3
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urljoin
import webbrowser
import threading

import requests as req_lib
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QTextEdit, QPushButton, QComboBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QFileDialog, QMessageBox, QFrame,
    QCheckBox, QScrollArea, QSplitter, QGroupBox, QDialog, QDialogButtonBox,
    QProgressBar, QStatusBar, QGridLayout, QTabWidget
)
from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QFont, QColor, QPalette

from glass_blue_erp_theme import apply_glass_blue_erp_theme, GlassColors, GlassStyles

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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS standalone_bills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                factory_id INTEGER,
                factory_name TEXT,
                vendor TEXT,
                amount REAL,
                bill_date TEXT,
                description TEXT,
                file_path TEXT,
                uploaded_by TEXT,
                uploaded_at TEXT
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


class FactoryPanelPySide6(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("EMD Group — Factory Panel")
        self.resize(1280, 680)
        self.setMinimumSize(1024, 600)
        
        # Apply Microsoft Fluent styling
        self._apply_fluent_style()
        
        # Session and state
        self.session = req_lib.Session()
        self.base_url = DEFAULT_BASE_URL
        self.username = ""
        self.password = ""
        self.status_text = "Not logged in"
        self.conn_text = "Offline"
        self.logged_in = False
        self.edit_request_id: int | None = None
        self.auto_sync_enabled = True
        self._last_sync_text = "Never"
        
        # Form variables
        self.f_factory_id = 0
        self.f_factory_name = ""
        self.f_request_type = "Material"
        self.f_req_amount = ""
        self.f_remarks = ""
        self.f_quotation_path = ""
        
        # Bill upload variables
        self.b_vendor_name = ""
        self.b_factory_id = 0
        self.b_factory_name = ""
        self.b_file_path = ""
        
        # Standalone bill upload variables
        self.bill_file_path = ""
        self.bill_factory_id = 0
        
        # Filter variables
        self.filt_status = ""
        self.filt_completion = ""
        
        # Dashboard counts
        self._dash_pending = 0
        self._dash_awaiting = 0
        self._dash_submitted = 0
        self._dash_updates = 0
        
        # Data
        self.factories: list[dict] = []
        self.bill_paths: dict[int, str] = {}
        
        # Build UI
        self._build_ui()
        self._refresh_combos()
        self._load_my_requests_from_cache()
        self._schedule_sync()
    
    def _apply_fluent_style(self) -> None:
        """Apply Glass Blue ERP theme styling."""
        app = QApplication.instance()
        if app is None:
            return
        
        apply_glass_blue_erp_theme(app)
    
    def _build_ui(self) -> None:
        """Build the main UI layout."""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Header
        self._build_header(main_layout)
        
        # Login bar
        self._build_login_bar(main_layout)
        
        # Main content area with scroll
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setStyleSheet(f"""
            QScrollArea {{
                border: none;
                background: transparent;
            }}
            QScrollBar:vertical {{
                background: {GlassColors.GLASS_BG};
                width: 10px;
                border-radius: 5px;
            }}
            QScrollBar::handle:vertical {{
                background: {GlassColors.PRIMARY_ACCENT};
                border-radius: 5px;
                min-height: 20px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            QScrollBar:horizontal {{
                background: {GlassColors.GLASS_BG};
                height: 10px;
                border-radius: 5px;
            }}
            QScrollBar::handle:horizontal {{
                background: {GlassColors.PRIMARY_ACCENT};
                border-radius: 5px;
                min-width: 20px;
            }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
                width: 0px;
            }}
        """)
        
        content_widget = QWidget()
        content_layout = QHBoxLayout(content_widget)
        content_layout.setContentsMargins(12, 12, 12, 12)
        content_layout.setSpacing(16)
        
        # Left panel - Tab widget for Request and Bill Upload
        left_panel = self._create_card("Forms")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(12, 12, 12, 12)
        left_layout.setSpacing(10)
        
        # Tab widget
        self.tab_widget = QTabWidget()
        self.tab_widget.setStyleSheet(f"""
            QTabWidget::pane {{
                border: none;
                background: transparent;
            }}
            QTabBar::tab {{
                background: {GlassColors.GLASS_BG};
                color: {GlassColors.TEXT_SECONDARY};
                padding: 8px 16px;
                border: 1px solid {GlassColors.BORDER_COLOR};
                border-bottom: none;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                margin-right: 2px;
                font-size: 10px;
                font-weight: bold;
            }}
            QTabBar::tab:selected {{
                background: {GlassColors.PRIMARY_ACCENT};
                color: {GlassColors.TEXT_PRIMARY};
            }}
            QTabBar::tab:hover:!selected {{
                background: rgba(255, 255, 255, 0.1);
            }}
        """)
        
        # Purchase Request tab
        request_tab = QWidget()
        request_layout = QVBoxLayout(request_tab)
        request_layout.setContentsMargins(0, 0, 0, 0)
        request_layout.setSpacing(10)
        self._build_request_form(request_layout)
        self.tab_widget.addTab(request_tab, "📝 Purchase Request")
        
        # Bill Upload tab
        bill_upload_tab = QWidget()
        bill_upload_layout = QVBoxLayout(bill_upload_tab)
        bill_upload_layout.setContentsMargins(0, 0, 0, 0)
        bill_upload_layout.setSpacing(10)
        self._build_bill_upload_form(bill_upload_layout)
        self.tab_widget.addTab(bill_upload_tab, "🧾 Bill Upload")
        
        left_layout.addWidget(self.tab_widget)
        
        # Right panel - Dashboard and table
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(16)
        
        # Action Required Dashboard
        dashboard_card = self._create_card("⚠ Action Required")
        dashboard_layout = QVBoxLayout(dashboard_card)
        dashboard_layout.setContentsMargins(12, 12, 12, 12)
        self._build_action_dashboard(dashboard_layout)
        
        # My Requests Table
        table_card = self._create_card("My Requests")
        table_layout = QVBoxLayout(table_card)
        table_layout.setContentsMargins(12, 12, 12, 12)
        table_layout.setSpacing(12)
        self._build_requests_table(table_layout)
        
        right_layout.addWidget(dashboard_card)
        right_layout.addWidget(table_card, 1)  # Table takes remaining space
        
        content_layout.addWidget(left_panel, 0)  # Left panel fixed width
        content_layout.addWidget(right_panel, 1)  # Right panel takes remaining space
        
        scroll_area.setWidget(content_widget)
        main_layout.addWidget(scroll_area, 1)
        
        # Status bar
        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        self.statusBar.showMessage(self.status_text)
        
        # Footer
        footer = QLabel("Created by Daniyal  •  All Rights Reserved © 2026")
        footer.setAlignment(Qt.AlignRight)
        footer.setStyleSheet(f"color: {GlassColors.TEXT_MUTED}; font-size: 11px; padding: 4px 12px;")
        self.statusBar.addPermanentWidget(footer)
    
    def _create_card(self, title: str) -> QFrame:
        """Create a glass card with Glass Blue ERP styling."""
        card = QFrame()
        card.setStyleSheet(GlassStyles.glass_card_style())
        return card

    def _clean_input_style(self, readonly: bool = False) -> str:
        """Single-surface input style for the decluttered ERP UI."""
        bg = "rgba(255, 255, 255, 0.06)" if not readonly else "rgba(255, 255, 255, 0.04)"
        return f"""
            QLineEdit, QTextEdit, QComboBox {{
                background: {bg};
                color: {GlassColors.TEXT_PRIMARY};
                padding: 9px 12px;
                border: none;
                border-radius: 6px;
                selection-background-color: {GlassColors.PRIMARY};
            }}
            QLineEdit:focus, QTextEdit:focus, QComboBox:focus {{
                background: rgba(255, 255, 255, 0.10);
            }}
            QComboBox::drop-down {{
                border: none;
                width: 24px;
            }}
            QComboBox::down-arrow {{
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 5px solid {GlassColors.TEXT_SECONDARY};
            }}
        """

    def _clean_group_style(self) -> str:
        """Group boxes with title only, no decorative frame."""
        return f"""
            QGroupBox {{
                color: {GlassColors.TEXT_PRIMARY};
                font-weight: bold;
                font-size: 11px;
                border: none;
                margin-top: 14px;
                padding-top: 10px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 0px;
                padding: 0px;
            }}
        """
    
    def _build_header(self, parent_layout: QVBoxLayout) -> None:
        """Build the header bar with logo and user info."""
        header = QFrame()
        header.setStyleSheet(GlassStyles.header_style())
        header.setFixedHeight(80)
        
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(12, 10, 12, 10)
        header_layout.setSpacing(16)
        
        # Logo area
        logo_label = QLabel()
        logo_label.setStyleSheet(f"""
            QLabel {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {GlassColors.PRIMARY_DARK},
                    stop:1 {GlassColors.PRIMARY_LIGHT});
                color: {GlassColors.TEXT_PRIMARY};
                font-size: 18px;
                font-weight: bold;
                padding: 0px 14px;
                border-radius: 8px;
                border: 1px solid {GlassColors.PRIMARY_ACCENT};
            }}
        """)
        logo_label.setText("EMD\nGroup")
        logo_label.setAlignment(Qt.AlignCenter)
        logo_label.setFixedSize(100, 56)
        header_layout.addWidget(logo_label)
        
        # Title
        title_widget = QWidget()
        title_layout = QVBoxLayout(title_widget)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(2)
        
        title_label = QLabel("Factory Panel")
        title_label.setStyleSheet(f"color: {GlassColors.TEXT_PRIMARY}; font-size: 18px; font-weight: bold;")
        title_layout.addWidget(title_label)
        
        subtitle_label = QLabel("Purchase Request Submission  —  Site / Factory")
        subtitle_label.setStyleSheet(f"color: {GlassColors.TEXT_SECONDARY}; font-size: 9px;")
        title_layout.addWidget(subtitle_label)
        
        header_layout.addWidget(title_widget)
        
        header_layout.addStretch()
        
        # Info chips
        self.header_factory_label = self._create_header_chip("Factory: Not selected")
        self.header_user_label = self._create_header_chip("User: Guest")
        self.header_status_label = self._create_header_chip("Status: Offline")
        self.header_sync_label = self._create_header_chip("Last Sync: Never")
        
        header_layout.addWidget(self.header_factory_label)
        header_layout.addWidget(self.header_user_label)
        header_layout.addWidget(self.header_status_label)
        header_layout.addWidget(self.header_sync_label)
        
        parent_layout.addWidget(header)
    
    def _create_header_chip(self, text: str) -> QLabel:
        """Create a header info chip."""
        label = QLabel(text)
        label.setStyleSheet(f"""
            QLabel {{
                background-color: {GlassColors.PRIMARY_ACCENT};
                color: {GlassColors.TEXT_PRIMARY};
                font-size: 10px;
                font-weight: bold;
                padding: 6px 12px;
                border-radius: 12px;
            }}
        """)
        return label
    
    def _build_login_bar(self, parent_layout: QVBoxLayout) -> None:
        """Build the login/connection bar."""
        self.login_bar = QFrame()
        self.login_bar.setStyleSheet(f"""
            QFrame {{
                background: {GlassColors.GLASS_BG};
                border: none;
            }}
        """)
        self.login_bar.setFixedHeight(50)
        
        login_layout = QHBoxLayout(self.login_bar)
        login_layout.setContentsMargins(12, 6, 12, 6)
        login_layout.setSpacing(12)
        
        # Username
        username_label = QLabel("Username:")
        username_label.setStyleSheet(f"color: {GlassColors.TEXT_SECONDARY}; font-weight: bold; font-size: 10px;")
        login_layout.addWidget(username_label)
        
        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Enter username")
        self.username_input.setFixedWidth(130)
        self.username_input.setStyleSheet(self._clean_input_style())
        login_layout.addWidget(self.username_input)
        
        # Password
        password_label = QLabel("Password:")
        password_label.setStyleSheet(f"color: {GlassColors.TEXT_SECONDARY}; font-weight: bold; font-size: 10px;")
        login_layout.addWidget(password_label)
        
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.setPlaceholderText("Enter password")
        self.password_input.setFixedWidth(130)
        self.password_input.setStyleSheet(self._clean_input_style())
        login_layout.addWidget(self.password_input)
        
        # Login button
        login_btn = QPushButton("🔐 Login")
        login_btn.setStyleSheet(GlassStyles.button_primary_style())
        login_btn.clicked.connect(self.login)
        login_layout.addWidget(login_btn)
        
        # Sync button
        sync_btn = QPushButton("🔄 Sync")
        sync_btn.setStyleSheet(GlassStyles.button_secondary_style())
        sync_btn.clicked.connect(lambda: self.sync_from_server(silent=False))
        login_layout.addWidget(sync_btn)
        
        # Auto sync checkbox
        self.auto_sync_checkbox = QCheckBox("Auto Sync (30s)")
        self.auto_sync_checkbox.setChecked(True)
        self.auto_sync_checkbox.setStyleSheet(f"color: {GlassColors.TEXT_SECONDARY}; font-size: 10px;")
        login_layout.addWidget(self.auto_sync_checkbox)
        
        login_layout.addStretch()
        
        # Status label
        self.status_label = QLabel(self.status_text)
        self.status_label.setStyleSheet(f"color: {GlassColors.TEXT_MUTED}; font-style: italic; font-size: 10px;")
        login_layout.addWidget(self.status_label)
        
        parent_layout.addWidget(self.login_bar)
    
    def _build_bill_upload_form(self, parent_layout: QVBoxLayout) -> None:
        """Build the standalone bill upload form."""
        # Form title
        title = QLabel("Upload Standalone Bill")
        title.setStyleSheet(f"color: {GlassColors.TEXT_PRIMARY}; font-size: 14px; font-weight: bold;")
        parent_layout.addWidget(title)
        
        # Factory dropdown
        factory_label = QLabel("Factory *")
        factory_label.setStyleSheet(f"color: {GlassColors.TEXT_SECONDARY}; font-weight: bold; font-size: 10px;")
        parent_layout.addWidget(factory_label)
        
        self.bill_factory_combo = QComboBox()
        self.bill_factory_combo.setStyleSheet(self._clean_input_style())
        self.bill_factory_combo.currentTextChanged.connect(self._on_bill_factory_select)
        parent_layout.addWidget(self.bill_factory_combo)
        
        # Vendor input
        vendor_label = QLabel("Vendor Name *")
        vendor_label.setStyleSheet(f"color: {GlassColors.TEXT_SECONDARY}; font-weight: bold; font-size: 10px;")
        parent_layout.addWidget(vendor_label)
        
        self.bill_vendor_input = QLineEdit()
        self.bill_vendor_input.setPlaceholderText("Enter vendor name")
        self.bill_vendor_input.setStyleSheet(self._clean_input_style())
        parent_layout.addWidget(self.bill_vendor_input)
        
        # Bill amount
        amount_label = QLabel("Bill Amount ₹ *")
        amount_label.setStyleSheet(f"color: {GlassColors.TEXT_SECONDARY}; font-weight: bold; font-size: 10px;")
        parent_layout.addWidget(amount_label)
        
        self.bill_amount_input = QLineEdit()
        self.bill_amount_input.setPlaceholderText("Enter bill amount")
        self.bill_amount_input.setStyleSheet(self._clean_input_style())
        parent_layout.addWidget(self.bill_amount_input)
        
        # Bill date
        date_label = QLabel("Bill Date *")
        date_label.setStyleSheet(f"color: {GlassColors.TEXT_SECONDARY}; font-weight: bold; font-size: 10px;")
        parent_layout.addWidget(date_label)
        
        self.bill_date_input = QLineEdit()
        self.bill_date_input.setPlaceholderText("YYYY-MM-DD")
        self.bill_date_input.setStyleSheet(self._clean_input_style())
        parent_layout.addWidget(self.bill_date_input)
        
        # Description
        desc_label = QLabel("Description")
        desc_label.setStyleSheet(f"color: {GlassColors.TEXT_SECONDARY}; font-weight: bold; font-size: 10px;")
        parent_layout.addWidget(desc_label)
        
        self.bill_desc_input = QLineEdit()
        self.bill_desc_input.setPlaceholderText("Optional description")
        self.bill_desc_input.setStyleSheet(self._clean_input_style())
        parent_layout.addWidget(self.bill_desc_input)
        
        # Bill file upload
        file_label = QLabel("Bill File *")
        file_label.setStyleSheet(f"color: {GlassColors.TEXT_SECONDARY}; font-weight: bold; font-size: 10px;")
        parent_layout.addWidget(file_label)
        
        file_layout = QHBoxLayout()
        file_layout.setSpacing(8)
        
        self.bill_file_input = QLineEdit()
        self.bill_file_input.setReadOnly(True)
        self.bill_file_input.setPlaceholderText("No file selected")
        self.bill_file_input.setStyleSheet(self._clean_input_style(readonly=True))
        file_layout.addWidget(self.bill_file_input)
        
        browse_btn = QPushButton("Browse")
        browse_btn.setStyleSheet(GlassStyles.button_secondary_style())
        browse_btn.clicked.connect(self._browse_bill_file)
        file_layout.addWidget(browse_btn)
        
        parent_layout.addLayout(file_layout)
        
        # Status label
        self.bill_status_label = QLabel()
        self.bill_status_label.setWordWrap(True)
        self.bill_status_label.setStyleSheet(f"color: {GlassColors.STATUS_APPROVED}; font-size: 10px;")
        parent_layout.addWidget(self.bill_status_label)
        
        # Submit button
        submit_btn = QPushButton("📤 Upload Bill")
        submit_btn.setStyleSheet(GlassStyles.button_success_style())
        submit_btn.clicked.connect(self.submit_standalone_bill)
        parent_layout.addWidget(submit_btn)
        
        parent_layout.addStretch()
    
    def _build_request_form(self, parent_layout: QVBoxLayout) -> None:
        """Build the request creation form."""
        # Form title
        title = QLabel("Create Purchase Request")
        title.setStyleSheet(f"color: {GlassColors.TEXT_PRIMARY}; font-size: 14px; font-weight: bold;")
        parent_layout.addWidget(title)
        
        # Factory dropdown
        factory_label = QLabel("Factory *")
        factory_label.setStyleSheet(f"color: {GlassColors.TEXT_SECONDARY}; font-weight: bold; font-size: 10px;")
        parent_layout.addWidget(factory_label)
        
        self.factory_combo = QComboBox()
        self.factory_combo.setStyleSheet(self._clean_input_style())
        self.factory_combo.currentTextChanged.connect(self._on_factory_select)
        parent_layout.addWidget(self.factory_combo)
        
        # Request Type dropdown
        type_label = QLabel("Request Type *")
        type_label.setStyleSheet(f"color: {GlassColors.TEXT_SECONDARY}; font-weight: bold; font-size: 10px;")
        parent_layout.addWidget(type_label)
        
        REQUEST_TYPES = ["Material", "Labour", "Transport", "Service", "Utility", "Emergency"]
        self.type_combo = QComboBox()
        self.type_combo.addItems(REQUEST_TYPES)
        self.type_combo.setStyleSheet(self._clean_input_style())
        parent_layout.addWidget(self.type_combo)
        
        # Purpose text area
        purpose_label = QLabel("Purpose *")
        purpose_label.setStyleSheet(f"color: {GlassColors.TEXT_SECONDARY}; font-weight: bold; font-size: 10px;")
        parent_layout.addWidget(purpose_label)
        
        self.purpose_text = QTextEdit()
        self.purpose_text.setPlaceholderText("Enter the purpose of this request...")
        self.purpose_text.setMaximumHeight(100)
        self.purpose_text.setStyleSheet(self._clean_input_style())
        parent_layout.addWidget(self.purpose_text)
        
        # Amount input
        amount_label = QLabel("Amount ₹ *")
        amount_label.setStyleSheet(f"color: {GlassColors.TEXT_SECONDARY}; font-weight: bold; font-size: 10px;")
        parent_layout.addWidget(amount_label)
        
        self.amount_input = QLineEdit()
        self.amount_input.setPlaceholderText("Enter amount")
        self.amount_input.setStyleSheet(self._clean_input_style())
        parent_layout.addWidget(self.amount_input)
        
        # Remarks input
        remarks_label = QLabel("Remarks")
        remarks_label.setStyleSheet(f"color: {GlassColors.TEXT_SECONDARY}; font-weight: bold; font-size: 10px;")
        parent_layout.addWidget(remarks_label)
        
        self.remarks_input = QLineEdit()
        self.remarks_input.setPlaceholderText("Optional remarks")
        self.remarks_input.setStyleSheet(self._clean_input_style())
        parent_layout.addWidget(self.remarks_input)
        
        # Quotation upload
        quotation_label = QLabel("Quotation *")
        quotation_label.setStyleSheet(f"color: {GlassColors.TEXT_SECONDARY}; font-weight: bold; font-size: 10px;")
        parent_layout.addWidget(quotation_label)
        
        quotation_layout = QHBoxLayout()
        quotation_layout.setSpacing(8)
        
        self.quotation_input = QLineEdit()
        self.quotation_input.setReadOnly(True)
        self.quotation_input.setPlaceholderText("No file selected")
        self.quotation_input.setStyleSheet(self._clean_input_style(readonly=True))
        quotation_layout.addWidget(self.quotation_input)
        
        browse_btn = QPushButton("Browse")
        browse_btn.setStyleSheet(GlassStyles.button_secondary_style())
        browse_btn.clicked.connect(self._browse_quotation)
        quotation_layout.addWidget(browse_btn)
        
        parent_layout.addLayout(quotation_layout)
        
        # Status label
        self.req_status_label = QLabel()
        self.req_status_label.setWordWrap(True)
        self.req_status_label.setStyleSheet(f"color: {GlassColors.STATUS_APPROVED}; font-size: 10px; font-weight: bold;")
        parent_layout.addWidget(self.req_status_label)
        
        # Submit and Reset buttons
        button_layout = QHBoxLayout()
        button_layout.setSpacing(8)
        
        self.submit_btn = QPushButton("📤 Submit Request")
        self.submit_btn.setStyleSheet(GlassStyles.button_success_style())
        self.submit_btn.clicked.connect(self.submit_request)
        button_layout.addWidget(self.submit_btn)
        
        reset_btn = QPushButton("🔄 Reset")
        reset_btn.setStyleSheet(GlassStyles.button_secondary_style())
        reset_btn.clicked.connect(self.clear_request_form)
        button_layout.addWidget(reset_btn)
        
        parent_layout.addLayout(button_layout)
        parent_layout.addStretch()
    
    def _build_action_dashboard(self, parent_layout: QVBoxLayout) -> None:
        """Build the action required dashboard."""
        dashboard_layout = QHBoxLayout()
        dashboard_layout.setSpacing(12)
        
        # Dashboard title
        title = QLabel("Action Required")
        title.setStyleSheet(f"color: {GlassColors.TEXT_PRIMARY}; font-size: 14px; font-weight: bold;")
        parent_layout.addWidget(title)
        
        # Approved Requests
        approved_card = self._create_kpi_card("Approved Requests", str(self._dash_pending), "Ready for completion", "#15803d")
        self.approved_label = approved_card.findChild(QLabel, "value_label")
        dashboard_layout.addWidget(approved_card)
        
        # Completion Submitted
        submitted_card = self._create_kpi_card("Completion Submitted", str(self._dash_submitted), "Waiting for admin", "#dc2626")
        self.submitted_label = submitted_card.findChild(QLabel, "value_label")
        dashboard_layout.addWidget(submitted_card)
        
        # Pending Submission
        pending_card = self._create_kpi_card("Pending Submission", str(self._dash_updates), "Needs your update", "#ca8a04")
        self.pending_label = pending_card.findChild(QLabel, "value_label")
        dashboard_layout.addWidget(pending_card)
        
        # Action Required
        action_card = self._create_kpi_card("Action Required", str(self._dash_awaiting), "Operational alerts", "#ea580c")
        self.action_label = action_card.findChild(QLabel, "value_label")
        dashboard_layout.addWidget(action_card)
        
        parent_layout.addLayout(dashboard_layout)
        
        # Note label
        self.dashboard_note = QLabel("No pending operational alerts")
        self.dashboard_note.setStyleSheet(f"color: {GlassColors.TEXT_MUTED}; font-size: 10px; font-style: italic;")
        parent_layout.addWidget(self.dashboard_note)
    
    def _create_kpi_card(self, title: str, value: str, subtitle: str, text_color: str) -> QFrame:
        """Create a clean KPI card with no inner rectangle."""
        card = QFrame()
        card.setObjectName("FactoryKpiCard")
        card.setMinimumHeight(80)
        card.setStyleSheet(f"""
            QFrame#FactoryKpiCard {{
                background: rgba(255, 255, 255, 0.08);
                border: none;
                border-left: 5px solid {text_color};
                border-radius: 8px;
            }}
        """)
        
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(5)
        
        title_label = QLabel(title)
        title_label.setStyleSheet(f"color: {GlassColors.TEXT_PRIMARY}; font-weight: bold; font-size: 10px;")
        title_label.setWordWrap(True)
        layout.addWidget(title_label)
        
        value_label = QLabel(value)
        value_label.setObjectName("value_label")
        value_label.setStyleSheet(f"color: {text_color}; font-weight: bold; font-size: 22px;")
        layout.addWidget(value_label)

        subtitle_label = QLabel(subtitle)
        subtitle_label.setStyleSheet(f"color: {GlassColors.TEXT_SECONDARY}; font-weight: 600; font-size: 9px;")
        subtitle_label.setWordWrap(True)
        layout.addWidget(subtitle_label)
        
        return card
    
    def _build_requests_table(self, parent_layout: QVBoxLayout) -> None:
        """Build the My Requests table with filters."""
        # Filter bar
        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(12)
        
        # Approval filter
        approval_label = QLabel("Approval:")
        approval_label.setStyleSheet(f"color: {GlassColors.TEXT_SECONDARY}; font-weight: bold; font-size: 10px;")
        filter_layout.addWidget(approval_label)
        
        self.approval_filter = QComboBox()
        self.approval_filter.addItem("")
        self.approval_filter.addItems(["Pending", "Partial Approved", "Approved", "Rejected"])
        self.approval_filter.setStyleSheet(self._clean_input_style())
        filter_layout.addWidget(self.approval_filter)
        
        # Completion filter
        completion_label = QLabel("Completion:")
        completion_label.setStyleSheet(f"color: {GlassColors.TEXT_SECONDARY}; font-weight: bold; font-size: 10px;")
        filter_layout.addWidget(completion_label)
        
        self.completion_filter = QComboBox()
        self.completion_filter.addItem("")
        self.completion_filter.addItems(["Pending", "Awaiting Completion", "Completion Submitted", "Closed"])
        self.completion_filter.setStyleSheet(self._clean_input_style())
        filter_layout.addWidget(self.completion_filter)
        
        # Search button
        search_btn = QPushButton("Search")
        search_btn.setStyleSheet(GlassStyles.button_primary_style())
        search_btn.clicked.connect(self._apply_filters)
        filter_layout.addWidget(search_btn)
        
        # Clear button
        clear_btn = QPushButton("Clear")
        clear_btn.setStyleSheet(GlassStyles.button_secondary_style())
        clear_btn.clicked.connect(self._clear_filters)
        filter_layout.addWidget(clear_btn)
        
        filter_layout.addStretch()
        parent_layout.addLayout(filter_layout)
        
        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels(["ID", "Date", "Type", "Purpose", "Amount", "Approval", "Completion", "Actions"])
        self.table.setStyleSheet(GlassStyles.table_style())
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        
        # Set column widths
        self.table.setColumnWidth(0, 50)   # ID
        self.table.setColumnWidth(1, 100)  # Date
        self.table.setColumnWidth(2, 90)   # Type
        self.table.setColumnWidth(3, 220)  # Purpose
        self.table.setColumnWidth(4, 90)   # Amount
        self.table.setColumnWidth(5, 110)  # Approval
        self.table.setColumnWidth(6, 130)  # Completion
        # Actions column stretches
        
        parent_layout.addWidget(self.table)
        
        # Connect click event
        self.table.cellClicked.connect(self._on_table_click)
    
    # ==================== Business Logic Methods ====================
    # These methods preserve the exact logic from the original Tkinter version
    
    def _should_retry_response(self, status_code: int) -> bool:
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
                resp = self.session.request(method, f"{self.base_url}{endpoint}", data=data, files=files, timeout=30)
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
            self.status_text = f"Retried uploads: {success_count} sent, {pending_left} pending"
            self.statusBar.showMessage(self.status_text)
            self.sync_from_server(silent=True)
    
    def _refresh_header_summary(self) -> None:
        factory_name = self.f_factory_name.strip() or self.b_factory_name.strip() or "Not selected"
        user_name = self.username.strip() or "Guest"
        connection = self.conn_text.strip() or "Offline"
        self.header_factory_label.setText(f"Factory: {factory_name}")
        self.header_user_label.setText(f"User: {user_name}")
        self.header_status_label.setText(f"Status: {connection}")
        self.header_sync_label.setText(f"Last Sync: {self._last_sync_text}")
    
    def _collapse_login_bar(self) -> None:
        self.login_bar.hide()
    
    def _on_bill_factory_select(self, text: str) -> None:
        """Handle factory selection for bill upload."""
        if not text:
            self.bill_factory_id = 0
            return
        
        # Find factory ID from cache
        with sqlite3.connect(db_path()) as conn:
            row = conn.execute(
                "SELECT id FROM masters_cache WHERE type='factories' AND name=?",
                (text,)
            ).fetchone()
            if row:
                self.bill_factory_id = int(row[0])
    
    def _browse_bill_file(self) -> None:
        """Browse for bill file to upload."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Bill File",
            "",
            "PDF Files (*.pdf);;Image Files (*.png *.jpg *.jpeg);;All Files (*.*)"
        )
        if file_path:
            self.bill_file_path = file_path
            self.bill_file_input.setText(file_path)
    
    def submit_standalone_bill(self) -> None:
        """Submit standalone bill to server."""
        # Validate inputs
        factory = self.bill_factory_combo.currentText().strip()
        vendor = self.bill_vendor_input.text().strip()
        amount = self.bill_amount_input.text().strip()
        date = self.bill_date_input.text().strip()
        file_path = self.bill_file_input.text().strip()
        
        if not factory:
            self.bill_status_label.setText("Please select a factory.")
            self.bill_status_label.setStyleSheet(f"color: {GlassColors.STATUS_REJECTED}; font-size: 10px;")
            return
        
        if not vendor:
            self.bill_status_label.setText("Please enter vendor name.")
            self.bill_status_label.setStyleSheet(f"color: {GlassColors.STATUS_REJECTED}; font-size: 10px;")
            return
        
        if not amount:
            self.bill_status_label.setText("Please enter bill amount.")
            self.bill_status_label.setStyleSheet(f"color: {GlassColors.STATUS_REJECTED}; font-size: 10px;")
            return
        
        if not date:
            self.bill_status_label.setText("Please enter bill date.")
            self.bill_status_label.setStyleSheet(f"color: {GlassColors.STATUS_REJECTED}; font-size: 10px;")
            return
        
        if not file_path:
            self.bill_status_label.setText("Please select a bill file.")
            self.bill_status_label.setStyleSheet(f"color: {GlassColors.STATUS_REJECTED}; font-size: 10px;")
            return
        try:
            bill_amount = float(amount)
            if bill_amount <= 0:
                raise ValueError
        except ValueError:
            self.bill_status_label.setText("Please enter a valid bill amount.")
            self.bill_status_label.setStyleSheet(f"color: {GlassColors.STATUS_REJECTED}; font-size: 10px;")
            return

        try:
            bill_date = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            self.bill_status_label.setText("Please enter a valid bill date in YYYY-MM-DD format.")
            self.bill_status_label.setStyleSheet(f"color: {GlassColors.STATUS_REJECTED}; font-size: 10px;")
            return

        self.bill_status_label.setText("Uploading bill to server...")
        self.bill_status_label.setStyleSheet(f"color: {GlassColors.STATUS_PENDING}; font-size: 10px;")

        try:
            data = {
                "vendor_name": vendor,
                "bill_amount": f"{bill_amount:.2f}",
                "bill_date": bill_date.isoformat(),
                "bill_description": self.bill_desc_input.text().strip(),
            }
            if self.bill_factory_id > 0:
                data["factory_id"] = str(self.bill_factory_id)

            with open(file_path, "rb") as f:
                response = self.session.post(
                    f"{self.base_url}/requests/simple-bill",
                    data=data,
                    files={"bill_image": f},
                    timeout=30,
                )

            response_body = response.json() if response.headers.get("Content-Type", "").startswith("application/json") else {}
            if response.status_code == 200:
                message = response_body.get("message", "Bill uploaded")
                self.bill_status_label.setText(f"✓ {message}")
                self.bill_status_label.setStyleSheet(f"color: {GlassColors.STATUS_APPROVED}; font-size: 10px;")
                self.clear_bill_form()
                return

            detail = response_body.get("detail", f"HTTP {response.status_code}")
            raise RuntimeError(str(detail))

        except Exception as exc:
            bills_dir = app_data_dir() / "standalone_bills"
            bills_dir.mkdir(parents=True, exist_ok=True)

            bill_filename = f"{vendor}_{date}_{Path(file_path).name}"
            dest_path = bills_dir / bill_filename

            import shutil
            shutil.copy2(file_path, dest_path)

            with sqlite3.connect(db_path()) as conn:
                conn.execute(
                    """
                    INSERT INTO standalone_bills
                    (factory_id, factory_name, vendor, amount, bill_date, description,
                     file_path, uploaded_by, uploaded_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        self.bill_factory_id,
                        factory,
                        vendor,
                        amount,
                        date,
                        self.bill_desc_input.text().strip(),
                        str(dest_path),
                        self.username,
                        datetime.now().isoformat(),
                    ),
                )
                conn.commit()

            self.bill_status_label.setText("Bill saved locally (server upload failed)")
            self.bill_status_label.setStyleSheet(f"color: {GlassColors.STATUS_APPROVED}; font-size: 10px;")
            self.clear_bill_form()

            if isinstance(exc, RuntimeError):
                return

            self.bill_status_label.setText(f"Save failed: {exc}")
            self.bill_status_label.setStyleSheet(f"color: {GlassColors.STATUS_REJECTED}; font-size: 10px;")
    
    def clear_bill_form(self) -> None:
        """Clear bill upload form."""
        self.bill_factory_combo.setCurrentIndex(0)
        self.bill_vendor_input.clear()
        self.bill_amount_input.clear()
        self.bill_date_input.clear()
        self.bill_desc_input.clear()
        self.bill_file_input.clear()
        self.bill_file_path = ""
        self.bill_factory_id = 0
    
    def _on_factory_select(self, text: str) -> None:
        for f in self.factories:
            if f["name"] == text:
                self.f_factory_id = f["id"]
                self.f_factory_name = f["name"]
                self._refresh_header_summary()
                return
    
    def _browse_quotation(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Quotation Document", "",
            "Images & PDFs (*.jpg *.jpeg *.png *.pdf);;All files (*.*)"
        )
        if path:
            self.f_quotation_path = path
            self.quotation_input.setText(path)
    
    def login(self) -> None:
        base = self.base_url.rstrip("/")
        try:
            r = self.session.post(f"{base}/login",
                data={"username": self.username_input.text(), "password": self.password_input.text()},
                allow_redirects=False, timeout=20)
            if r.status_code not in (302, 303):
                self._set_conn(False)
                QMessageBox.critical(self, "Login", f"Login failed: HTTP {r.status_code}")
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
                QMessageBox.critical(self, "Login", "Invalid username or password")
                return
            
            # Validate session
            auth_check = self.session.get(f"{base}/requests", timeout=20)
            if auth_check.status_code != 200:
                self.logged_in = False
                self._set_conn(False)
                QMessageBox.critical(self, "Login", "Login succeeded but session validation failed. Please try again.")
                return
            
            self.logged_in = True
            self.username = self.username_input.text()
            self.password = self.password_input.text()
            self._set_conn(True)
            self.status_text = "Logged in successfully"
            self.statusBar.showMessage(self.status_text)
            self._collapse_login_bar()
            self._load_masters()
            self.sync_from_server(silent=True)
            self._refresh_header_summary()
            QMessageBox.information(self, "Login", "Logged in successfully.")
        except Exception as exc:
            self._set_conn(False)
            QMessageBox.critical(self, "Login", f"Error: {exc}")
    
    def _set_conn(self, online: bool) -> None:
        self.conn_text = "Online" if online else "Offline"
        self.header_status_label.setText(f"Status: {self.conn_text}")
    
    def _load_masters(self) -> None:
        base = self.base_url.rstrip("/")
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
            
            current_factory = self.factory_combo.currentText()
            self.factory_combo.clear()
            self.factory_combo.addItems(fnames)
            
            # Also populate bill factory combo
            current_bill_factory = self.bill_factory_combo.currentText()
            self.bill_factory_combo.clear()
            self.bill_factory_combo.addItems(fnames)
            
            if fnames:
                if current_factory in fnames:
                    self.factory_combo.setCurrentText(current_factory)
                else:
                    self.factory_combo.setCurrentIndex(0)
                    self._on_factory_select(fnames[0])
                
                if current_bill_factory in fnames:
                    self.bill_factory_combo.setCurrentText(current_bill_factory)
                else:
                    self.bill_factory_combo.setCurrentIndex(0)
                    self._on_bill_factory_select(fnames[0])
        
        self._refresh_header_summary()
    
    def sync_from_server(self, silent: bool = False) -> None:
        base = self.base_url.rstrip("/")
        try:
            r = self.session.get(f"{base}/requests", timeout=30)
            if r.status_code != 200:
                self._set_conn(False)
                if not silent:
                    QMessageBox.critical(self, "Sync", f"Sync failed: HTTP {r.status_code}")
                return
            items = r.json().get("items", [])
            self._save_to_db(items)
            self._load_my_requests_from_cache()
            self._set_conn(True)
            self._last_sync_text = datetime.now().strftime('%H:%M:%S')
            self.status_text = f"Synced {len(items)} records at {self._last_sync_text}"
            self.statusBar.showMessage(self.status_text)
            self._refresh_header_summary()
        except Exception as exc:
            self._set_conn(False)
            if not silent:
                QMessageBox.critical(self, "Sync", f"Error: {exc}")
    
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
        self.table.setRowCount(0)
        
        filt_status = self.approval_filter.currentText().strip()
        filt_completion = self.completion_filter.currentText().strip()
        
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
            approval_status = normalize_approval_status(r[5])
            completion_status = r[6] or "Pending"
            prev_status = normalize_approval_status(r[8]) if r[8] is not None else None
            self.bill_paths[req_id] = r[7] or ""
            vendor_bill_path = r[10] or ""
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
            purpose = r[3] or ""
            
            row = self.table.rowCount()
            self.table.insertRow(row)
            
            self.table.setItem(row, 0, QTableWidgetItem(str(req_id)))
            self.table.setItem(row, 1, QTableWidgetItem(r[1]))
            self.table.setItem(row, 2, QTableWidgetItem(req_type))
            self.table.setItem(row, 3, QTableWidgetItem(purpose[:40]))
            self.table.setItem(row, 4, QTableWidgetItem(f"{float(r[4]):.2f}" if r[4] else "0.00"))
            self.table.setItem(row, 5, QTableWidgetItem(approval_status))
            self.table.setItem(row, 6, QTableWidgetItem(completion_status))
            self.table.setItem(row, 7, QTableWidgetItem("  ".join(actions)))
            
            # Apply row coloring
            tag = "new_status" if changed else ("awaiting_comp" if completion_status == "Awaiting Completion" else approval_status)
            self._apply_row_color(row, tag)
        
        if status_changed:
            self._notify_status_changes(status_changed)
        
        # Update dashboard
        self._dash_pending = approved_count
        self._dash_awaiting = awaiting_count
        self._dash_submitted = submitted_count
        self._dash_updates = pending_count
        
        if self.approved_label:
            self.approved_label.setText(str(approved_count))
        if self.submitted_label:
            self.submitted_label.setText(str(submitted_count))
        if self.pending_label:
            self.pending_label.setText(str(pending_count))
        if self.action_label:
            self.action_label.setText(str(awaiting_count))
        
        if awaiting_count > 0:
            self.dashboard_note.setText(f"{awaiting_count} request(s) waiting for completion proof")
        elif pending_count > 0:
            self.dashboard_note.setText(f"{pending_count} request(s) pending approval")
        else:
            self.dashboard_note.setText("No pending operational alerts")
        
        self._refresh_header_summary()
    
    def _apply_row_color(self, row: int, tag: str) -> None:
        """Apply background color based on status tag."""
        colors = {
            "Approved": "#ecfdf3",
            "Rejected": "#fff1f2",
            "Partial Approved": "#fefce8",
            "Pending": "#fff7ed",
            "Draft": "#f8fafc",
            "new_status": "#eff6ff",
            "awaiting_comp": "#eff6ff",
        }
        bg_color = colors.get(tag, "#ffffff")
        text_color = {
            "Approved": "#15803d",
            "Rejected": "#dc2626",
            "Partial Approved": "#ca8a04",
            "Pending": "#ea580c",
            "Draft": "#64748b",
            "new_status": "#1f6fbe",
            "awaiting_comp": "#1f6fbe",
        }.get(tag, "#111827")
        
        for col in range(self.table.columnCount()):
            item = self.table.item(row, col)
            if item:
                item.setBackground(QColor(bg_color))
                item.setForeground(QColor(text_color))
    
    def _apply_filters(self) -> None:
        self._load_my_requests_from_cache()
    
    def _clear_filters(self) -> None:
        self.approval_filter.setCurrentIndex(0)
        self.completion_filter.setCurrentIndex(0)
        self._load_my_requests_from_cache()
    
    def _notify_status_changes(self, changes: list) -> None:
        for req_id, old_s, new_s, item_name, remark in changes:
            msg = f"Request #{req_id} ({item_name or 'Item'})\nStatus: {old_s} -> {new_s}"
            if remark:
                msg += f"\nRemark: {remark}"
            QMessageBox.information(self, "Status Update!", msg)
            with sqlite3.connect(db_path()) as conn:
                conn.execute("UPDATE my_requests SET prev_status=approval_status WHERE id=?", (req_id,))
                conn.commit()
    
    def _on_table_click(self, row: int, column: int) -> None:
        """Handle table cell clicks for action buttons."""
        if column != 7:  # Actions column
            return
        
        actions_item = self.table.item(row, 7)
        if not actions_item:
            return
        
        actions = actions_item.text()
        req_id_item = self.table.item(row, 0)
        if not req_id_item:
            return
        req_id = int(req_id_item.text())
        
        if "Submit Completion" in actions:
            self.completion_selected(req_id)
        elif "View Docs" in actions:
            self.view_completion_docs(req_id)
        elif "Bill" in actions:
            self.view_bill_selected(req_id)
        elif "Delete" in actions:
            self.delete_selected(req_id)
    
    def submit_request(self) -> None:
        self._do_submit()
    
    def _do_submit(self) -> None:
        if not self.logged_in:
            QMessageBox.critical(self, "Error", "Please login first.")
            return
        
        if self.f_factory_id <= 0:
            self._req_status("Select a factory.", error=True)
            return
        
        request_type = self.type_combo.currentText().strip()
        if not request_type:
            self._req_status("Select a request type.", error=True)
            return
        
        purpose = self.purpose_text.toPlainText().strip()
        if not purpose:
            self._req_status("Purpose is required.", error=True)
            return
        
        amt_str = self.amount_input.text().strip()
        try:
            amount = float(amt_str)
            if amount <= 0:
                raise ValueError
        except ValueError:
            self._req_status("Amount must be a positive number.", error=True)
            return
        
        quotation_path = self.f_quotation_path.strip()
        if not quotation_path:
            self._req_status("Quotation document is required. Please browse and select a file.", error=True)
            return
        if not Path(quotation_path).exists():
            self._req_status("Selected quotation file no longer exists. Please browse again.", error=True)
            return
        
        data = {
            "factory_id": str(self.f_factory_id),
            "request_type": request_type,
            "purpose": purpose,
            "amount": str(amount),
        }
        remarks = self.remarks_input.text().strip()
        if remarks:
            data["remarks"] = remarks
        
        self.submit_btn.setEnabled(False)
        self._req_status("Submitting, please wait...", error=False)
        file_handle = None
        try:
            file_handle = open(quotation_path, "rb")
            files = {"quotation": file_handle}
            r = self.session.post(f"{self.base_url}/requests/factory", data=data, files=files, timeout=30)
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
            self.submit_btn.setEnabled(True)
    
    def clear_request_form(self) -> None:
        self.edit_request_id = None
        self.type_combo.setCurrentIndex(0)
        self.amount_input.clear()
        self.remarks_input.clear()
        self.f_quotation_path = ""
        self.quotation_input.clear()
        self.purpose_text.clear()
        self._req_status("")
    
    def _req_status(self, msg: str, error: bool = False) -> None:
        self.req_status_label.setText(msg)
        self.req_status_label.setStyleSheet(f"color: {'#b02a37' if error else '#1f8a43'}; font-size: 10px;")
    
    def completion_selected(self, req_id: int) -> None:
        with sqlite3.connect(db_path()) as conn:
            row = conn.execute("SELECT completion_status FROM my_requests WHERE id=?", (req_id,)).fetchone()
        if not row:
            QMessageBox.warning(self, "Select", "Request not found. Sync first.")
            return
        comp_status = row[0] or "Pending"
        if comp_status != "Awaiting Completion":
            QMessageBox.warning(self, "Completion", f"Cannot submit completion: status is '{comp_status}'.\n"
                                   "Only requests with 'Awaiting Completion' status can be submitted.")
            return
        self.open_completion_dialog(req_id)
    
    def open_completion_dialog(self, req_id: int) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Submit Completion — Request #{req_id}")
        dialog.resize(540, 560)
        dialog.setModal(True)
        
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        
        # Summary frame
        summary_group = QGroupBox("Request Summary")
        summary_group.setStyleSheet(self._clean_group_style())
        summary_layout = QGridLayout()
        summary_layout.setHorizontalSpacing(18)
        summary_layout.setVerticalSpacing(6)
        summary_group.setLayout(summary_layout)
        
        req_no_val = QLabel(f"#{req_id}")
        req_type_val = QLabel("…")
        purpose_val = QLabel("…")
        requested_val = QLabel("…")
        approved_val = QLabel("…")
        
        for row_idx, (lbl, var) in enumerate([
            ("Request No", req_no_val),
            ("Type", req_type_val),
            ("Purpose", purpose_val),
            ("Requested (₹)", requested_val),
            ("Approved (₹)", approved_val),
        ]):
            label = QLabel(lbl)
            label.setStyleSheet("color: #555; font-weight: bold; font-size: 10px;")
            var.setStyleSheet("color: #1a1a1a; font-weight: bold; font-size: 11px;")
            summary_layout.addWidget(label, row_idx, 0)
            summary_layout.addWidget(var, row_idx, 1)
        
        layout.addWidget(summary_group)
        
        # Remark
        remark_label = QLabel("Completion Remark *")
        remark_label.setStyleSheet("color: #334155; font-weight: bold; font-size: 10px;")
        layout.addWidget(remark_label)
        
        remark_box = QTextEdit()
        remark_box.setMaximumHeight(80)
        remark_box.setPlaceholderText("Enter completion remarks...")
        remark_box.setStyleSheet(self._clean_input_style())
        layout.addWidget(remark_box)
        
        # Documents
        doc_group = QGroupBox("Documents (at least ONE required)")
        doc_group.setStyleSheet(self._clean_group_style())
        doc_layout = QVBoxLayout()
        doc_layout.setContentsMargins(0, 8, 0, 0)
        doc_layout.setSpacing(8)
        doc_group.setLayout(doc_layout)
        
        # Vendor Bill
        vb_label = QLabel("Vendor Bill (optional):")
        vb_label.setStyleSheet("color: #334155; font-weight: bold; font-size: 10px;")
        doc_layout.addWidget(vb_label)
        
        vb_layout = QHBoxLayout()
        vendor_bill_var = QLineEdit()
        vendor_bill_var.setReadOnly(True)
        vendor_bill_var.setPlaceholderText("No file selected")
        vendor_bill_var.setStyleSheet(self._clean_input_style(readonly=True))
        vb_layout.addWidget(vendor_bill_var)
        
        vb_browse = QPushButton("Browse")
        vb_browse.setStyleSheet("""
            QPushButton {
                background-color: #64748b;
                color: white;
                font-weight: bold;
                padding: 6px 12px;
                border: none;
                border-radius: 4px;
            }
        """)
        vb_browse.clicked.connect(lambda: self._browse_file(vendor_bill_var, "Select Vendor Bill"))
        vb_layout.addWidget(vb_browse)
        doc_layout.addLayout(vb_layout)
        
        # Company Voucher
        cv_label = QLabel("Company Voucher (optional):")
        cv_label.setStyleSheet("color: #334155; font-weight: bold; font-size: 10px;")
        doc_layout.addWidget(cv_label)
        
        cv_layout = QHBoxLayout()
        voucher_var = QLineEdit()
        voucher_var.setReadOnly(True)
        voucher_var.setPlaceholderText("No file selected")
        voucher_var.setStyleSheet(self._clean_input_style(readonly=True))
        cv_layout.addWidget(voucher_var)
        
        cv_browse = QPushButton("Browse")
        cv_browse.setStyleSheet("""
            QPushButton {
                background-color: #64748b;
                color: white;
                font-weight: bold;
                padding: 6px 12px;
                border: none;
                border-radius: 4px;
            }
        """)
        cv_browse.clicked.connect(lambda: self._browse_file(voucher_var, "Select Company Voucher"))
        cv_layout.addWidget(cv_browse)
        doc_layout.addLayout(cv_layout)
        
        layout.addWidget(doc_group)
        
        # Status label
        status_var = QLabel()
        status_var.setWordWrap(True)
        status_var.setStyleSheet(f"color: {GlassColors.STATUS_APPROVED}; font-size: 10px;")
        layout.addWidget(status_var)
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(GlassStyles.button_secondary_style())
        cancel_btn.clicked.connect(dialog.reject)
        button_layout.addWidget(cancel_btn)
        
        submit_btn = QPushButton("Submit Completion")
        submit_btn.setStyleSheet(GlassStyles.button_primary_style())
        
        def on_submit():
            remark = remark_box.toPlainText().strip()
            if not remark:
                status_var.setText("Completion remark is required.")
                status_var.setStyleSheet(f"color: {GlassColors.STATUS_REJECTED}; font-size: 10px;")
                return
            
            vb_path = vendor_bill_var.text().strip()
            cv_path = voucher_var.text().strip()
            if not vb_path and not cv_path:
                status_var.setText("Please upload Vendor Bill or Company Voucher before submitting completion.")
                status_var.setStyleSheet(f"color: {GlassColors.STATUS_REJECTED}; font-size: 10px;")
                return
            
            if not self.logged_in:
                status_var.setText("Please login first.")
                status_var.setStyleSheet(f"color: {GlassColors.STATUS_REJECTED}; font-size: 10px;")
                return
            
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
                
                status_var.setText("Submitting…")
                status_var.setStyleSheet(f"color: {GlassColors.TEXT_MUTED}; font-size: 10px;")
                r = self.session.post(f"{self.base_url}/requests/{req_id}/complete",
                                      data=data, files=files or None, timeout=30)
                body = r.json() if r.headers.get("Content-Type", "").startswith("application/json") else {}
                if r.status_code == 200:
                    status_var.setText(f"✓ {body.get('message', 'Completion submitted!')}")
                    status_var.setStyleSheet(f"color: {GlassColors.STATUS_APPROVED}; font-size: 10px;")
                    self.sync_from_server(silent=True)
                    QTimer.singleShot(1000, dialog.accept)
                else:
                    detail = body.get("detail", f"HTTP {r.status_code}")
                    if isinstance(detail, list):
                        detail = detail[0].get("msg", str(detail))
                    status_var.setText(str(detail))
                    status_var.setStyleSheet(f"color: {GlassColors.STATUS_REJECTED}; font-size: 10px;")
            except Exception as exc:
                status_var.setText(f"Error: {exc}")
                status_var.setStyleSheet(f"color: {GlassColors.STATUS_REJECTED}; font-size: 10px;")
            finally:
                for fh in file_handles:
                    fh.close()
        
        submit_btn.clicked.connect(on_submit)
        button_layout.addWidget(submit_btn)
        
        layout.addLayout(button_layout)
        
        # Load autofill data
        def _load_autofill():
            try:
                r = self.session.get(f"{self.base_url}/requests/{req_id}/detail", timeout=10)
                if r.status_code == 200:
                    d = r.json()
                    req_type_val.setText(d.get("request_type") or d.get("item_category") or "—")
                    purpose_val.setText((d.get("purpose") or d.get("item_name") or "—")[:60])
                    requested_val.setText(f"₹{float(d.get('final_amount') or 0):.2f}")
                    approved_val.setText(f"₹{float(d.get('approved_amount') or d.get('final_amount') or 0):.2f}")
            except Exception:
                pass
        
        threading.Thread(target=_load_autofill, daemon=True).start()
        
        dialog.exec()
    
    def _browse_file(self, input_field: QLineEdit, title: str) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, title, "",
            "Images & PDFs (*.jpg *.jpeg *.png *.pdf);;All files (*.*)"
        )
        if path:
            input_field.setText(path)
    
    def delete_selected(self, req_id: int) -> None:
        with sqlite3.connect(db_path()) as conn:
            row = conn.execute("SELECT approval_status FROM my_requests WHERE id=?", (req_id,)).fetchone()
        if not row:
            return
        if row[0] not in ("Pending", "Draft"):
            QMessageBox.warning(self, "Delete", f"Cannot delete: status is {row[0]}")
            return
        reply = QMessageBox.question(
            self, "Delete", f"Delete request #{req_id}?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.No:
            return
        if not self.logged_in:
            QMessageBox.critical(self, "Error", "Login first.")
            return
        try:
            r = self.session.delete(f"{self.base_url}/requests/{req_id}", timeout=20)
            body = r.json() if r.headers.get("Content-Type", "").startswith("application/json") else {}
            if r.status_code != 200:
                QMessageBox.critical(self, "Delete", body.get("detail", f"HTTP {r.status_code}"))
                return
            with sqlite3.connect(db_path()) as conn:
                conn.execute("DELETE FROM my_requests WHERE id=?", (req_id,))
                conn.commit()
            self._load_my_requests_from_cache()
            self.status_text = f"Request #{req_id} deleted."
            self.statusBar.showMessage(self.status_text)
        except Exception as exc:
            QMessageBox.critical(self, "Delete", f"Failed: {exc}")
    
    def view_bill_selected(self) -> None:
        current_row = self.table.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "Select", "Select a request first.")
            return
        req_id_item = self.table.item(current_row, 0)
        if not req_id_item:
            return
        req_id = int(req_id_item.text())
        
        with sqlite3.connect(db_path()) as conn:
            conn.execute("UPDATE my_requests SET prev_status=approval_status WHERE id=?", (req_id,))
            conn.commit()
        self._load_my_requests_from_cache()
        
        path = (self.bill_paths.get(req_id) or "").strip()
        if not path:
            QMessageBox.information(self, "Bill", "No bill attached for this request.")
            return
        base = self.base_url.rstrip("/") + "/"
        bill_url = path if path.startswith("http") else urljoin(base, path.lstrip("/"))
        webbrowser.open_new_tab(bill_url)
    
    def view_completion_docs(self, req_id: int) -> None:
        with sqlite3.connect(db_path()) as conn:
            row = conn.execute(
                "SELECT vendor_bill_path, company_voucher_path FROM my_requests WHERE id=?", (req_id,)
            ).fetchone()
        if not row or (not row[0] and not row[1]):
            QMessageBox.information(self, "Documents", "No completion documents uploaded for this request.")
            return
        vendor_bill_path, company_voucher_path = row
        
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Completion Documents — Request #{req_id}")
        dialog.resize(420, 200)
        dialog.setModal(True)
        
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        
        title = QLabel(f"Completion Documents for Request #{req_id}")
        title.setStyleSheet("color: #0f172a; font-size: 14px; font-weight: bold;")
        layout.addWidget(title)
        
        def _open_doc(doc_type: str, label: str):
            def _fetch():
                try:
                    r = self.session.get(f"{self.base_url}/requests/{req_id}/{doc_type}", allow_redirects=True, timeout=30)
                    if r.status_code == 200:
                        ct = r.headers.get("Content-Type", "")
                        ext = ".pdf" if "pdf" in ct else (".png" if "png" in ct else ".jpg")
                        import re as _re
                        cd = r.headers.get("Content-Disposition", "")
                        m = _re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', cd, _re.IGNORECASE)
                        if m:
                            ext = Path(m.group(1).strip()).suffix or ext
                        import tempfile
                        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext,
                                                         prefix=f"req{req_id}_{doc_type}_")
                        tmp.write(r.content)
                        tmp.close()
                        os.startfile(tmp.name)
                    elif r.status_code == 302 and "/login" in r.headers.get("Location", ""):
                        QMessageBox.critical(dialog, "Documents", "Session expired. Please login again.")
                    else:
                        QMessageBox.critical(dialog, "Documents", f"Could not fetch {label} (HTTP {r.status_code})")
                except Exception as exc:
                    QMessageBox.critical(dialog, "Documents", f"Error: {exc}")
            threading.Thread(target=_fetch, daemon=True).start()
        
        def _download_doc(doc_type: str, label: str):
            def _fetch():
                try:
                    r = self.session.get(f"{self.base_url}/requests/{req_id}/{doc_type}", allow_redirects=True, timeout=30)
                    if r.status_code == 200:
                        ct = r.headers.get("Content-Type", "")
                        ext = ".pdf" if "pdf" in ct else (".png" if "png" in ct else ".jpg")
                        import re as _re
                        cd = r.headers.get("Content-Disposition", "")
                        m = _re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', cd, _re.IGNORECASE)
                        if m:
                            ext = Path(m.group(1).strip()).suffix or ext
                        
                        def _save():
                            of, _ = QFileDialog.getSaveFileName(
                                dialog, f"Save {label}", f"request_{req_id}_{doc_type}{ext}",
                                "All Files (*.*)"
                            )
                            if of:
                                with open(of, "wb") as f:
                                    f.write(r.content)
                                QMessageBox.information(dialog, "Download", f"Saved:\n{of}")
                        
                        QTimer.singleShot(0, _save)
                    else:
                        QMessageBox.critical(dialog, "Download", f"Could not fetch {label} (HTTP {r.status_code})")
                except Exception as exc:
                    QMessageBox.critical(dialog, "Download", f"Error: {exc}")
            threading.Thread(target=_fetch, daemon=True).start()
        
        # Vendor Bill row
        if vendor_bill_path:
            vb_row = QHBoxLayout()
            vb_label = QLabel("📄 Vendor Bill:")
            vb_label.setStyleSheet(f"color: {GlassColors.TEXT_SECONDARY}; font-weight: bold; font-size: 10px;")
            vb_label.setFixedWidth(100)
            vb_row.addWidget(vb_label)
            
            view_btn = QPushButton("View")
            view_btn.setStyleSheet(GlassStyles.button_primary_style())
            view_btn.clicked.connect(lambda: _open_doc("vendor-bill", "Vendor Bill"))
            vb_row.addWidget(view_btn)
            
            download_btn = QPushButton("Download")
            download_btn.setStyleSheet(GlassStyles.button_secondary_style())
            download_btn.clicked.connect(lambda: _download_doc("vendor-bill", "Vendor Bill"))
            vb_row.addWidget(download_btn)
            
            vb_row.addStretch()
            layout.addLayout(vb_row)
        else:
            vb_row = QHBoxLayout()
            vb_label = QLabel("📄 Vendor Bill:")
            vb_label.setStyleSheet(f"color: {GlassColors.TEXT_SECONDARY}; font-weight: bold; font-size: 10px;")
            vb_label.setFixedWidth(100)
            vb_row.addWidget(vb_label)
            
            not_uploaded = QLabel("Not uploaded")
            not_uploaded.setStyleSheet(f"color: {GlassColors.TEXT_MUTED}; font-size: 10px;")
            vb_row.addWidget(not_uploaded)
            vb_row.addStretch()
            layout.addLayout(vb_row)
        
        # Company Voucher row
        if company_voucher_path:
            cv_row = QHBoxLayout()
            cv_label = QLabel("🧾 Co. Voucher:")
            cv_label.setStyleSheet(f"color: {GlassColors.TEXT_SECONDARY}; font-weight: bold; font-size: 10px;")
            cv_label.setFixedWidth(100)
            cv_row.addWidget(cv_label)
            
            view_btn = QPushButton("View")
            view_btn.setStyleSheet(GlassStyles.button_primary_style())
            view_btn.clicked.connect(lambda: _open_doc("company-voucher", "Company Voucher"))
            cv_row.addWidget(view_btn)
            
            download_btn = QPushButton("Download")
            download_btn.setStyleSheet(GlassStyles.button_secondary_style())
            download_btn.clicked.connect(lambda: _download_doc("company-voucher", "Company Voucher"))
            cv_row.addWidget(download_btn)
            
            cv_row.addStretch()
            layout.addLayout(cv_row)
        else:
            cv_row = QHBoxLayout()
            cv_label = QLabel("🧾 Co. Voucher:")
            cv_label.setStyleSheet(f"color: {GlassColors.TEXT_SECONDARY}; font-weight: bold; font-size: 10px;")
            cv_label.setFixedWidth(100)
            cv_row.addWidget(cv_label)
            
            not_uploaded = QLabel("Not uploaded")
            not_uploaded.setStyleSheet(f"color: {GlassColors.TEXT_MUTED}; font-size: 10px;")
            cv_row.addWidget(not_uploaded)
            cv_row.addStretch()
            layout.addLayout(cv_row)
        
        close_btn = QPushButton("Close")
        close_btn.setStyleSheet(GlassStyles.button_secondary_style())
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn)
        
        dialog.exec()
    
    def _schedule_sync(self) -> None:
        if self.logged_in and self.auto_sync_checkbox.isChecked():
            self._retry_pending_uploads()
            self.sync_from_server(silent=True)
        QTimer.singleShot(30000, self._schedule_sync)


def main() -> int:
    init_db()
    app = QApplication([])
    window = FactoryPanelPySide6()
    window.show()
    return app.exec()


if __name__ == "__main__":
    import sys
    sys.exit(main())
