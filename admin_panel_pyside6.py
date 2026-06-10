import os
import sys
import sqlite3
import io
import re
import threading
import traceback
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin
import webbrowser

import requests

try:
    from glass_blue_erp_theme import apply_glass_blue_erp_theme, GlassColors, GlassStyles
    THEME_IMPORT_ERROR = None
except Exception as exc:
    THEME_IMPORT_ERROR = exc

    def apply_glass_blue_erp_theme(app) -> None:
        return None

    class _GlassColorMeta(type):
        def __getattr__(cls, _name):
            return "#2B3A4A"

    class GlassColors(metaclass=_GlassColorMeta):
        TEXT_PRIMARY = "#FFFFFF"
        TEXT_SECONDARY = "#D6DEE8"
        TEXT_MUTED = "#A0AEC0"
        BORDER_COLOR = "#3C4B5A"
        PRIMARY_DARK = "#1F2A36"
        PRIMARY_LIGHT = "#2B3A4A"
        PRIMARY_ACCENT = "#4A90E2"

    class _GlassStyleMeta(type):
        def __getattr__(cls, _name):
            def _style_fallback(*_args, **_kwargs):
                return ""

            return _style_fallback

    class GlassStyles(metaclass=_GlassStyleMeta):
        pass

    print(f"[admin_panel_pyside6] Theme import failed: {exc}", file=sys.stderr, flush=True)

try:
    from openpyxl import Workbook
except Exception:
    Workbook = None

try:
    from PIL import Image
except Exception:
    Image = None

try:
    import fitz  # PyMuPDF
except Exception:
    fitz = None

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QTextEdit, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QFileDialog, QMessageBox, QFrame,
    QCheckBox, QScrollArea, QSplitter, QGroupBox, QDialog, QDialogButtonBox,
    QProgressBar, QStatusBar, QGridLayout, QComboBox, QTabWidget,
    QSizePolicy, QSpacerItem, QStackedWidget, QInputDialog
)
from PySide6.QtCore import Qt, QTimer, QSize, Signal, QThread
from PySide6.QtGui import QGuiApplication
from PySide6.QtGui import QFont, QColor, QPalette, QPixmap, QImage
from PySide6.QtGui import QDesktopServices

APP_NAME = "EMDAdminPanel"
DEFAULT_BASE_URL = "https://paymentapproval.onrender.com"


def _report_runtime_exception(title: str, exc_type, exc_value, exc_traceback) -> None:
    if exc_type is SystemExit:
        raise exc_value
    details = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    print(details, file=sys.stderr, flush=True)
    app = QApplication.instance()
    if app is not None:
        QMessageBox.critical(None, title, f"{exc_value}\n\nSee terminal output for details.")


def _threading_excepthook(args) -> None:
    _report_runtime_exception("Admin Panel Background Error", args.exc_type, args.exc_value, args.exc_traceback)


class BillFetchThread(QThread):
    """Fetch bill bytes in the background; render only on the Qt UI thread."""

    loaded = Signal(int, bytes, str, str)
    failed = Signal(int, str)

    def __init__(self, panel: "AdminPanelPySide6", req_id: int, parent=None) -> None:
        super().__init__(parent or panel)
        self.panel = panel
        self.req_id = req_id

    def run(self) -> None:
        if self.isInterruptionRequested():
            return
        resp, filename, err = self.panel._fetch_bill_response(self.req_id, stream=False)
        if self.isInterruptionRequested():
            return
        if err or resp is None:
            self.failed.emit(self.req_id, err or "No bill attached or failed to load.")
            return
        try:
            content = resp.content
            content_type = resp.headers.get("Content-Type", "")
        except Exception as exc:
            self.failed.emit(self.req_id, f"Failed to read bill file: {exc}")
            return
        if self.isInterruptionRequested():
            return
        self.loaded.emit(self.req_id, content, filename, content_type)


class PaymentSummaryThread(QThread):
    """Load payment summary without blocking the popup."""

    loaded = Signal(int, object)
    failed = Signal(int, str)

    def __init__(self, panel: "AdminPanelPySide6", req_id: int) -> None:
        super().__init__(panel)
        self.panel = panel
        self.req_id = req_id

    def run(self) -> None:
        base = DEFAULT_BASE_URL.rstrip("/")
        try:
            resp = self.panel.session.get(f"{base}/requests/{self.req_id}/payment-summary", timeout=20)
            if resp.status_code != 200:
                detail = ""
                try:
                    detail = resp.json().get("detail", "")
                except Exception:
                    pass
                self.failed.emit(self.req_id, detail or "Could not load payment summary.")
                return
            self.loaded.emit(self.req_id, resp.json())
        except Exception as exc:
            self.failed.emit(self.req_id, f"Load error: {exc}")


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


class AdminPanelPySide6(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("EMD Group — Admin Panel")
        self.resize(1420, 820)
        self.setMinimumSize(1100, 640)
        
        # Apply Microsoft Fluent styling
        self._apply_fluent_style()
        
        # Center window on screen
        self._center_window()
        
        # Session and state
        self.session = requests.Session()
        self.base_url = DEFAULT_BASE_URL
        self.username = "admin"
        self.password = "admin123"
        self.status_text = "Not logged in"
        self.conn_text = "Offline"
        self.auto_sync_enabled = True
        self.logged_in = False
        self.bill_paths: dict[int, str] = {}
        self.factories_cache: dict[int, dict] = {}
        self.factory_name_var = ""
        self.factory_location_var = ""
        self.new_requests_count = 0
        self.new_bills_count = 0
        
        # Preview state
        self.preview_req_id: int | None = None
        self.preview_filename = ""
        self._last_bill_url_by_req: dict[int, str] = {}
        self._viewed_ids: set[int] = set()
        self._last_server_items: list[dict] = []
        self._status_filter: str = ""
        self._comp_filter: str = ""
        
        # PDF preview state
        self._pdf_pages: list = []
        self._pdf_current_page: int = 0
        self._pdf_content: bytes = b""
        self._pdf_page_count: int = 0
        self._preview_source_pixmap: QPixmap | None = None
        self._preview_summary_visible: bool = False
        self._open_bill_in_window_for_req: int | None = None
        self._bill_loader: BillFetchThread | None = None
        self._payment_summary_loader: PaymentSummaryThread | None = None
        
        # Build UI
        self._build_ui()
        self.statusBar.showMessage("Please login to load data from server")
        self.schedule_auto_sync()
    
    def _apply_fluent_style(self) -> None:
        """Apply EMD Fluent Blue theme styling."""
        app = QApplication.instance()
        if app is None:
            return
        
        apply_glass_blue_erp_theme(app)
    
    def _center_window(self) -> None:
        """Center the window on the screen."""
        screen = QGuiApplication.primaryScreen()
        if screen:
            frame_geometry = self.frameGeometry()
            center_point = screen.availableGeometry().center()
            frame_geometry.moveCenter(center_point)
            self.move(frame_geometry.topLeft())
    
    def _create_card(self, title: str = "", light: bool = False, glow: bool = True) -> QFrame:
        """Create a glass card with Glass Blue ERP styling."""
        card = QFrame()
        if light:
            card.setStyleSheet(GlassStyles.glass_card_light_style())
        else:
            card.setStyleSheet(GlassStyles.glass_card_style())
        return card
    
    def _build_ui(self) -> None:
        """Build the main UI layout."""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Header
        self._build_header(main_layout)
        
        # Main content area with sidebar
        content_widget = QWidget()
        content_layout = QHBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        
        # Sidebar
        sidebar = self._build_sidebar()
        content_layout.addWidget(sidebar)
        
        # Main area
        main_area = self._build_main_area()
        content_layout.addWidget(main_area, 1)
        
        main_layout.addWidget(content_widget, 1)
        
        # Footer
        self._build_footer(main_layout)
        
        # Status bar
        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        self.statusBar.showMessage(self.status_text)
    
    def _build_header(self, parent_layout: QVBoxLayout) -> None:
        """Build the header bar with logo and title."""
        header = QFrame()
        header.setStyleSheet(GlassStyles.header_style())
        header.setFixedHeight(88)
        
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 10, 16, 10)
        header_layout.setSpacing(16)
        
        # Logo
        logo_label = QLabel()
        logo_label.setStyleSheet(f"""
            QLabel {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {GlassColors.PRIMARY_DARK},
                    stop:1 {GlassColors.PRIMARY_LIGHT});
                color: {GlassColors.TEXT_PRIMARY};
                font-size: 18px;
                font-weight: bold;
                line-height: 1.15;
                padding: 0px 14px;
                border-radius: 8px;
                border: 1px solid {GlassColors.PRIMARY_ACCENT};
            }}
        """)
        logo_label.setText("EMD\nGroup")
        logo_label.setAlignment(Qt.AlignCenter)
        logo_label.setFixedSize(122, 66)
        header_layout.addWidget(logo_label)
        
        # Title
        title_widget = QWidget()
        title_layout = QVBoxLayout(title_widget)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(2)
        
        title_label = QLabel("Admin Panel")
        title_label.setStyleSheet(f"color: {GlassColors.TEXT_PRIMARY}; font-size: 18px; font-weight: bold;")
        title_layout.addWidget(title_label)
        
        subtitle_label = QLabel("Purchase Approval Management  —  EMD Group")
        subtitle_label.setStyleSheet(f"color: {GlassColors.TEXT_SECONDARY}; font-size: 9px;")
        title_layout.addWidget(subtitle_label)
        
        header_layout.addWidget(title_widget)
        
        header_layout.addStretch()
        
        # Status chip
        self.status_chip = QLabel(self.status_text)
        self.status_chip.setStyleSheet(f"""
            QLabel {{
                background-color: {GlassColors.PRIMARY_ACCENT};
                color: {GlassColors.TEXT_PRIMARY};
                font-size: 10px;
                font-weight: bold;
                padding: 6px 12px;
                border-radius: 12px;
            }}
        """)
        header_layout.addWidget(self.status_chip)
        
        # Login button
        login_btn = QPushButton("🔐 Login")
        login_btn.setStyleSheet(GlassStyles.button_primary_style())
        login_btn.clicked.connect(self.login)
        header_layout.addWidget(login_btn)
        
        parent_layout.addWidget(header)
    
    def _build_sidebar(self) -> QFrame:
        """Build the sidebar navigation."""
        sidebar = QFrame()
        sidebar.setStyleSheet(GlassStyles.sidebar_style())
        sidebar.setFixedWidth(238)
        
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)
        
        # Logo pane
        logo_pane = QFrame()
        logo_pane.setStyleSheet(f"""
            QFrame {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {GlassColors.PRIMARY_DARK},
                    stop:1 {GlassColors.PRIMARY_LIGHT});
                border: none;
            }}
        """)
        logo_pane.setFixedHeight(102)
        
        logo_layout = QVBoxLayout(logo_pane)
        logo_layout.setContentsMargins(0, 12, 0, 10)
        logo_layout.setSpacing(2)
        
        logo_label = QLabel("EMD")
        logo_label.setStyleSheet(f"color: {GlassColors.TEXT_PRIMARY}; font-size: 32px; font-weight: bold;")
        logo_label.setAlignment(Qt.AlignCenter)
        logo_layout.addWidget(logo_label)
        
        group_label = QLabel("GROUP")
        group_label.setStyleSheet(f"color: {GlassColors.TEXT_SECONDARY}; font-size: 11px; font-weight: bold;")
        group_label.setAlignment(Qt.AlignCenter)
        logo_layout.addWidget(group_label)
        
        tagline_label = QLabel("Scaffolding & Form Work")
        tagline_label.setStyleSheet(f"color: {GlassColors.TEXT_MUTED}; font-size: 8px;")
        tagline_label.setAlignment(Qt.AlignCenter)
        logo_layout.addWidget(tagline_label)
        
        sidebar_layout.addWidget(logo_pane)
        
        # Divider
        divider = QFrame()
        divider.setStyleSheet(f"background-color: {GlassColors.BORDER_COLOR};")
        divider.setFixedHeight(1)
        sidebar_layout.addWidget(divider)
        
        # Navigation buttons
        nav_container = QWidget()
        nav_layout = QVBoxLayout(nav_container)
        nav_layout.setContentsMargins(0, 6, 0, 0)
        nav_layout.setSpacing(0)
        
        self._active_page = "requests"
        self._nav_btns: dict[str, QPushButton] = {}
        
        nav_items = [
            ("📊 Dashboard", "dashboard"),
            ("📋 Requests", "requests"),
            ("🧾 Bill Uploads", "bills"),
            ("🖼 Bill Preview", "preview"),
            ("🏭 Factory Locations", "locations"),
        ]
        
        for label, page_id in nav_items:
            btn = QPushButton(f"  {label}")
            btn.setStyleSheet(GlassStyles.sidebar_button_style(is_active=(page_id == "requests")))
            btn.setCheckable(True)
            btn.clicked.connect(lambda checked, p=page_id: self._switch_page(p))
            nav_layout.addWidget(btn)
            self._nav_btns[page_id] = btn
        
        nav_layout.addStretch()
        sidebar_layout.addWidget(nav_container)
        
        # Sidebar footer with credentials
        footer_container = QWidget()
        footer_layout = QVBoxLayout(footer_container)
        footer_layout.setContentsMargins(12, 8, 12, 8)
        footer_layout.setSpacing(4)
        
        # Username
        username_label = QLabel("USERNAME")
        username_label.setStyleSheet(f"color: {GlassColors.TEXT_SECONDARY}; font-size: 7px; font-weight: bold;")
        footer_layout.addWidget(username_label)
        
        self.username_input = QLineEdit()
        self.username_input.setText(self.username)
        self.username_input.setStyleSheet(GlassStyles.input_style())
        footer_layout.addWidget(self.username_input)
        
        # Password
        password_label = QLabel("PASSWORD")
        password_label.setStyleSheet(f"color: {GlassColors.TEXT_SECONDARY}; font-size: 7px; font-weight: bold;")
        footer_layout.addWidget(password_label)
        
        self.password_input = QLineEdit()
        self.password_input.setText(self.password)
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.setStyleSheet(GlassStyles.input_style())
        footer_layout.addWidget(self.password_input)
        
        # Auto sync checkbox
        self.auto_sync_checkbox = QCheckBox("Auto Sync")
        self.auto_sync_checkbox.setChecked(True)
        self.auto_sync_checkbox.setStyleSheet(f"color: {GlassColors.TEXT_SECONDARY}; font-size: 9px;")
        footer_layout.addWidget(self.auto_sync_checkbox)
        
        # Connection status
        conn_row = QHBoxLayout()
        self.conn_dot = QLabel("●")
        self.conn_dot.setStyleSheet("color: #dc3545; font-size: 13px;")
        conn_row.addWidget(self.conn_dot)
        
        self.conn_label = QLabel(self.conn_text)
        self.conn_label.setStyleSheet(f"color: {GlassColors.TEXT_PRIMARY}; font-size: 9px; font-weight: bold;")
        conn_row.addWidget(self.conn_label)
        
        footer_layout.addLayout(conn_row)
        
        sidebar_layout.addWidget(footer_container)
        
        divider2 = QFrame()
        divider2.setStyleSheet(f"background-color: {GlassColors.BORDER_COLOR};")
        divider2.setFixedHeight(1)
        sidebar_layout.addWidget(divider2)
        
        return sidebar
    
    def _build_main_area(self) -> QWidget:
        """Build the main content area."""
        main_area = QWidget()
        main_area.setStyleSheet(f"""
            QWidget {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 {GlassColors.BG_DARK},
                    stop:1 {GlassColors.BG_LIGHT});
            }}
        """)
        main_layout = QVBoxLayout(main_area)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Page title bar
        title_bar = QFrame()
        title_bar.setStyleSheet(f"""
            QFrame {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {GlassColors.PRIMARY_DARK},
                    stop:1 {GlassColors.PRIMARY_LIGHT});
            }}
        """)
        title_bar.setFixedHeight(68)
        
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(20, 12, 14, 12)
        
        self.page_title = QLabel("Purchase Requests")
        self.page_title.setStyleSheet(f"color: {GlassColors.TEXT_PRIMARY}; font-size: 13px; font-weight: bold;")
        title_layout.addWidget(self.page_title)
        
        title_layout.addStretch()
        
        # Search bar
        search_frame = QFrame()
        search_frame.setFixedHeight(40)
        search_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {GlassColors.GLASS_BG};
                border: 1px solid {GlassColors.BORDER_COLOR};
                border-radius: 6px;
            }}
        """)
        search_layout = QHBoxLayout(search_frame)
        search_layout.setContentsMargins(10, 4, 10, 4)
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 Search vendor / item / ID...")
        self.search_input.setFixedHeight(30)
        self.search_input.setStyleSheet(f"""
            QLineEdit {{
                background: transparent;
                color: {GlassColors.TEXT_PRIMARY};
                padding: 4px 8px;
                border: none;
                border-radius: 4px;
                font-size: 10px;
                selection-background-color: {GlassColors.PRIMARY};
            }}
            QLineEdit:focus {{
                background: rgba(255, 255, 255, 0.08);
            }}
        """)
        self.search_input.textChanged.connect(self._apply_search_filter)
        search_layout.addWidget(self.search_input)
        
        title_layout.addWidget(search_frame)
        
        main_layout.addWidget(title_bar)
        
        # Divider
        divider = QFrame()
        divider.setStyleSheet(f"background-color: {GlassColors.BORDER_COLOR};")
        divider.setFixedHeight(1)
        main_layout.addWidget(divider)
        
        # KPI Dashboard
        self._build_kpi_dashboard(main_layout)
        
        # Action toolbar
        self._build_action_toolbar(main_layout)
        
        # Filter bar
        self._build_filter_bar(main_layout)
        
        # Pages container
        self.pages_container = QStackedWidget()
        self._build_pages()
        main_layout.addWidget(self.pages_container, 1)
        
        return main_area
    
    def _build_kpi_dashboard(self, parent_layout: QVBoxLayout) -> None:
        """Build the KPI dashboard cards."""
        kpi_container = QWidget()
        kpi_container.setStyleSheet("background-color: #f3f5f7;")
        kpi_layout = QHBoxLayout(kpi_container)
        kpi_layout.setContentsMargins(16, 14, 16, 8)
        kpi_layout.setSpacing(10)
        
        # KPI variables
        self.kpi_total = QLabel("—")
        self.kpi_pending = QLabel("—")
        self.kpi_approved = QLabel("—")
        self.kpi_rejected = QLabel("—")
        self.kpi_partial = QLabel("—")
        self.kpi_awaiting = QLabel("—")
        self.kpi_amount = QLabel("₹—")
        
        kpi_defs = [
            ("📦", "Total", self.kpi_total, "All requests", GlassColors.PRIMARY_ACCENT),
            ("⏳", "Pending", self.kpi_pending, "Needs review", GlassColors.STATUS_PENDING),
            ("✅", "Approved", self.kpi_approved, "Ready to proceed", GlassColors.STATUS_APPROVED),
            ("❌", "Rejected", self.kpi_rejected, "Declined requests", GlassColors.STATUS_REJECTED),
            ("⏸", "Partial Approved", self.kpi_partial, "Part payment", GlassColors.STATUS_PARTIAL),
            ("🧾", "Awaiting Completion", self.kpi_awaiting, "Bills submitted", GlassColors.STATUS_SUBMITTED),
            ("💰", "Amount", self.kpi_amount, "Approved value", GlassColors.PRIMARY_ACCENT),
        ]
        
        for icon_text, title_text, value_label, subtitle_text, status_color in kpi_defs:
            card = QFrame()
            card.setObjectName("KpiCard")
            card.setMinimumHeight(96)
            card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            card.setStyleSheet(f"""
                QFrame#KpiCard {{
                    background: #ffffff;
                    border: 1px solid #d8e2ec;
                    border-left: 5px solid {status_color};
                    border-radius: 8px;
                }}
            """)
            
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(14, 10, 14, 10)
            card_layout.setSpacing(5)
            
            title_row = QHBoxLayout()
            title_row.setContentsMargins(0, 0, 0, 0)
            title_row.setSpacing(6)
            
            icon = QLabel(icon_text)
            icon.setStyleSheet(f"color: {status_color}; font-size: 15px; font-weight: bold;")
            icon.setFixedWidth(20)
            icon.setAlignment(Qt.AlignCenter)
            title_row.addWidget(icon)
            
            title = QLabel(title_text)
            title.setStyleSheet("color: #24364a; font-size: 10px; font-weight: 700;")
            title.setWordWrap(True)
            title_row.addWidget(title, 1)
            card_layout.addLayout(title_row)
            
            value_label.setStyleSheet(f"color: {status_color}; font-size: 21px; font-weight: 800;")
            value_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            card_layout.addWidget(value_label)
            
            subtitle = QLabel(subtitle_text)
            subtitle.setStyleSheet("color: #526273; font-size: 9px; font-weight: 600;")
            subtitle.setWordWrap(True)
            card_layout.addWidget(subtitle)
            
            kpi_layout.addWidget(card)
        
        parent_layout.addWidget(kpi_container)
    
    def _build_action_toolbar(self, parent_layout: QVBoxLayout) -> None:
        """Build the action toolbar."""
        toolbar = self._create_card()
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(8, 6, 8, 6)
        toolbar_layout.setSpacing(4)
        
        def create_action_btn(text: str, color: str, hover_color: str, callback) -> QPushButton:
            btn = QPushButton(text)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 {color},
                        stop:1 {hover_color});
                    color: {GlassColors.TEXT_PRIMARY};
                    font-weight: bold;
                    padding: 7px 10px;
                    border: none;
                    border-radius: 6px;
                    font-size: 9px;
                }}
                QPushButton:hover {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 {hover_color},
                        stop:1 {GlassColors.PRIMARY_ACCENT});
                }}
                QPushButton:pressed {{
                    background: {color};
                }}
            """)
            btn.clicked.connect(callback)
            return btn
        
        def create_separator() -> QFrame:
            sep = QFrame()
            sep.setStyleSheet(f"background-color: {GlassColors.BORDER_COLOR};")
            sep.setFixedWidth(1)
            return sep
        
        toolbar_layout.addWidget(create_action_btn("🔄 Sync", "#0B2C5F", "#163d7a", self.sync_from_server))
        toolbar_layout.addWidget(create_separator())
        toolbar_layout.addWidget(create_action_btn("🧾 View Bill", "#155c8a", "#1e7ab8", self.view_bill_selected))
        toolbar_layout.addWidget(create_action_btn("📥 Download", "#155c8a", "#1e7ab8", self.download_bill_selected))
        toolbar_layout.addWidget(create_separator())
        toolbar_layout.addWidget(create_action_btn("✅ Approve", "#166534", "#15803d", self.approve_selected))
        toolbar_layout.addWidget(create_action_btn("❌ Reject", "#991b1b", "#b91c1c", self.reject_selected))
        toolbar_layout.addWidget(create_action_btn("⏸ Partial Approved", "#9a3412", "#c2410c", self.hold_selected))
        toolbar_layout.addWidget(create_separator())
        toolbar_layout.addWidget(create_action_btn("🔒 Verify & Close", "#065f46", "#047857", self.verify_selected))
        toolbar_layout.addWidget(create_action_btn("↩ Reopen", "#7c2d12", "#9a3412", self.reopen_selected))
        toolbar_layout.addWidget(create_separator())
        toolbar_layout.addWidget(create_action_btn("🗑 Delete", "#6b1e1e", "#7f1d1d", self.delete_selected))
        toolbar_layout.addWidget(create_separator())
        toolbar_layout.addWidget(create_action_btn("📊 Export Excel", "#3b0764", "#5b21b6", self.export_local_excel))
        
        toolbar_layout.addStretch()
        
        parent_layout.addWidget(toolbar)
    
    def _build_filter_bar(self, parent_layout: QVBoxLayout) -> None:
        """Build the filter bar with status and completion filters."""
        # Status filter
        status_filter = self._create_card()
        status_layout = QHBoxLayout(status_filter)
        status_layout.setContentsMargins(12, 5, 12, 5)
        status_layout.setSpacing(4)
        
        status_label = QLabel("STATUS")
        status_label.setStyleSheet(f"color: {GlassColors.TEXT_SECONDARY}; font-size: 8px; font-weight: bold;")
        status_layout.addWidget(status_label)
        
        self._filter_btns: dict[str, QPushButton] = {}
        filter_opts = [
            ("  All  ", "", GlassColors.GLASS_BG, GlassColors.TEXT_PRIMARY, GlassColors.PRIMARY_ACCENT, GlassColors.TEXT_PRIMARY),
            ("  Pending  ", "Pending", GlassColors.GLASS_BG, GlassColors.TEXT_PRIMARY, GlassColors.STATUS_PENDING, GlassColors.TEXT_PRIMARY),
            ("  Approved  ", "Approved", GlassColors.GLASS_BG, GlassColors.TEXT_PRIMARY, GlassColors.STATUS_APPROVED, GlassColors.TEXT_PRIMARY),
            ("  Rejected  ", "Rejected", GlassColors.GLASS_BG, GlassColors.TEXT_PRIMARY, GlassColors.STATUS_REJECTED, GlassColors.TEXT_PRIMARY),
            ("  Partial Approved  ", "Partial Approved", GlassColors.GLASS_BG, GlassColors.TEXT_PRIMARY, GlassColors.STATUS_PARTIAL, GlassColors.TEXT_PRIMARY),
        ]
        
        for label, value, nbg, nfg, abg, afg in filter_opts:
            btn = QPushButton(label)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {nbg};
                    color: {nfg};
                    font-weight: bold;
                    padding: 5px 4px;
                    border: 1px solid {GlassColors.BORDER_COLOR};
                    border-radius: 6px;
                    font-size: 9px;
                }}
                QPushButton:hover {{
                    background-color: {abg};
                    color: {afg};
                }}
                QPushButton:checked {{
                    background-color: {abg};
                    color: {afg};
                }}
            """)
            btn.setCheckable(True)
            btn.clicked.connect(lambda checked, v=value: self._apply_status_filter(v))
            status_layout.addWidget(btn)
            self._filter_btns[value] = btn
        
        self._highlight_filter_btn("")
        
        parent_layout.addWidget(status_filter)
        
        # Completion filter
        comp_filter = self._create_card()
        comp_layout = QHBoxLayout(comp_filter)
        comp_layout.setContentsMargins(12, 4, 12, 4)
        comp_layout.setSpacing(4)
        
        comp_label = QLabel("COMPLETION")
        comp_label.setStyleSheet(f"color: {GlassColors.TEXT_SECONDARY}; font-size: 8px; font-weight: bold;")
        comp_layout.addWidget(comp_label)
        
        self._comp_filter_btns: dict[str, QPushButton] = {}
        comp_opts = [
            ("  All  ", "", GlassColors.GLASS_BG, GlassColors.TEXT_PRIMARY, GlassColors.PRIMARY_ACCENT, GlassColors.TEXT_PRIMARY),
            ("  Pending  ", "Pending", GlassColors.GLASS_BG, GlassColors.TEXT_PRIMARY, GlassColors.STATUS_PENDING, GlassColors.TEXT_PRIMARY),
            ("  Awaiting Compl.  ", "Awaiting Completion", GlassColors.GLASS_BG, GlassColors.TEXT_PRIMARY, GlassColors.STATUS_PARTIAL, GlassColors.TEXT_PRIMARY),
            ("  Compl. Submitted  ", "Completion Submitted", GlassColors.GLASS_BG, GlassColors.TEXT_PRIMARY, GlassColors.STATUS_SUBMITTED, GlassColors.TEXT_PRIMARY),
            ("  Closed  ", "Closed", GlassColors.GLASS_BG, GlassColors.TEXT_PRIMARY, GlassColors.STATUS_CLOSED, GlassColors.TEXT_PRIMARY),
        ]
        
        for label, value, nbg, nfg, abg, afg in comp_opts:
            btn = QPushButton(label)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {nbg};
                    color: {nfg};
                    font-weight: bold;
                    padding: 4px 4px;
                    border: 1px solid {GlassColors.BORDER_COLOR};
                    border-radius: 6px;
                    font-size: 9px;
                }}
                QPushButton:hover {{
                    background-color: {abg};
                    color: {afg};
                }}
                QPushButton:checked {{
                    background-color: {abg};
                    color: {afg};
                }}
            """)
            btn.setCheckable(True)
            btn.clicked.connect(lambda checked, v=value: self._apply_comp_filter(v))
            comp_layout.addWidget(btn)
            self._comp_filter_btns[value] = btn
        
        parent_layout.addWidget(comp_filter)
    
    def _build_pages(self) -> None:
        """Build all pages."""
        # Requests page
        self.requests_page = QWidget()
        self._build_requests_page()
        self.pages_container.addWidget(self.requests_page)
        
        # Bills page
        self.bills_page = QWidget()
        self._build_bills_page()
        self.pages_container.addWidget(self.bills_page)
        
        # Preview page
        self.preview_page = QWidget()
        self._build_preview_page()
        self.pages_container.addWidget(self.preview_page)
        
        # Locations page
        self.locations_page = QWidget()
        self._build_locations_page()
        self.pages_container.addWidget(self.locations_page)
        
        # Dashboard page
        self.dashboard_page = QWidget()
        self._build_dashboard_page()
        self.pages_container.addWidget(self.dashboard_page)
        
        # Show initial page
        self._switch_page("requests")
    
    def _build_requests_page(self) -> None:
        """Build the requests table page."""
        layout = QVBoxLayout(self.requests_page)
        layout.setContentsMargins(14, 6, 14, 6)
        layout.setSpacing(0)
        
        # Table
        table_card = self._create_card()
        table_layout = QVBoxLayout(table_card)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setSpacing(0)
        
        self.requests_table = QTableWidget()
        self.requests_table.setColumnCount(13)
        self.requests_table.setHorizontalHeaderLabels([
            "ID", "Date", "Factory", "Type", "Purpose", "Requested (₹)",
            "Paid (₹)", "Balance (₹)", "Requested By", "Approval",
            "Payment", "Completion", "Updated At"
        ])
        self.requests_table.setStyleSheet(GlassStyles.table_style())
        
        # Set column widths
        self.requests_table.setColumnWidth(0, 55)   # ID
        self.requests_table.setColumnWidth(1, 95)   # Date
        self.requests_table.setColumnWidth(2, 65)   # Factory
        self.requests_table.setColumnWidth(3, 90)   # Type
        self.requests_table.setColumnWidth(4, 160)  # Purpose
        self.requests_table.setColumnWidth(5, 90)   # Requested
        self.requests_table.setColumnWidth(6, 80)   # Paid
        self.requests_table.setColumnWidth(7, 80)   # Balance
        self.requests_table.setColumnWidth(8, 115)  # Requested By
        self.requests_table.setColumnWidth(9, 100)  # Approval
        self.requests_table.setColumnWidth(10, 95)  # Payment
        self.requests_table.setColumnWidth(11, 130) # Completion
        self.requests_table.setColumnWidth(12, 140) # Updated At
        
        self.requests_table.horizontalHeader().setStretchLastSection(True)
        self.requests_table.verticalHeader().setVisible(False)
        self.requests_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.requests_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.requests_table.doubleClicked.connect(self._on_table_double_click)
        
        table_layout.addWidget(self.requests_table)
        layout.addWidget(table_card, 1)
    
    def _build_bills_page(self) -> None:
        """Build the bills table page."""
        layout = QVBoxLayout(self.bills_page)
        layout.setContentsMargins(14, 6, 14, 6)
        layout.setSpacing(0)
        
        # Table
        table_card = self._create_card()
        table_layout = QVBoxLayout(table_card)
        table_layout.setContentsMargins(0, 0, 0, 0)
        
        self.bills_table = QTableWidget()
        self.bills_table.setColumnCount(7)
        self.bills_table.setHorizontalHeaderLabels([
            "ID", "Date", "Factory", "Vendor", "Uploaded By", "Status", "Updated At"
        ])
        self.bills_table.setStyleSheet(GlassStyles.table_style())
        
        # Set column widths
        self.bills_table.setColumnWidth(0, 70)   # ID
        self.bills_table.setColumnWidth(1, 110)  # Date
        self.bills_table.setColumnWidth(2, 80)   # Factory
        self.bills_table.setColumnWidth(3, 230)  # Vendor
        self.bills_table.setColumnWidth(4, 190)  # Uploaded By
        self.bills_table.setColumnWidth(5, 120)  # Status
        self.bills_table.setColumnWidth(6, 230)  # Updated At
        
        self.bills_table.horizontalHeader().setStretchLastSection(True)
        self.bills_table.verticalHeader().setVisible(False)
        self.bills_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.bills_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.bills_table.doubleClicked.connect(self._on_bills_table_double_click)
        
        table_layout.addWidget(self.bills_table)
        layout.addWidget(table_card, 1)
    
    def _build_preview_page(self) -> None:
        """Build the bill preview page."""
        layout = QVBoxLayout(self.preview_page)
        layout.setContentsMargins(14, 6, 14, 6)
        layout.setSpacing(6)
        
        # Top bar
        top_bar = self._create_card()
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(10, 8, 10, 8)
        
        self.preview_status = QLabel("No bill loaded")
        self.preview_status.setStyleSheet(f"color: {GlassColors.TEXT_SECONDARY}; font-size: 10px;")
        top_layout.addWidget(self.preview_status)
        
        top_layout.addStretch()
        
        prev_btn = QPushButton("◄ Prev")
        prev_btn.setStyleSheet(GlassStyles.button_secondary_style())
        prev_btn.clicked.connect(self._pdf_prev_page)
        top_layout.addWidget(prev_btn)
        
        self.pdf_page_label = QLabel("")
        self.pdf_page_label.setStyleSheet(f"color: {GlassColors.TEXT_PRIMARY}; font-size: 9px; font-weight: bold;")
        self.pdf_page_label.setFixedWidth(80)
        self.pdf_page_label.setAlignment(Qt.AlignCenter)
        top_layout.addWidget(self.pdf_page_label)
        
        next_btn = QPushButton("Next ►")
        next_btn.setStyleSheet(GlassStyles.button_secondary_style())
        next_btn.clicked.connect(self._pdf_next_page)
        top_layout.addWidget(next_btn)
        
        load_btn = QPushButton("Load Bill")
        load_btn.setStyleSheet(GlassStyles.button_primary_style())
        load_btn.clicked.connect(self.view_bill_selected)
        top_layout.addWidget(load_btn)
        
        download_btn = QPushButton("Download")
        download_btn.setStyleSheet(GlassStyles.button_secondary_style())
        download_btn.clicked.connect(self.download_bill_selected)
        top_layout.addWidget(download_btn)

        self.preview_summary_toggle_btn = QPushButton("Show Summary")
        self.preview_summary_toggle_btn.setStyleSheet(GlassStyles.button_secondary_style())
        self.preview_summary_toggle_btn.clicked.connect(self._toggle_preview_summary)
        top_layout.addWidget(self.preview_summary_toggle_btn)

        full_view_btn = QPushButton("Full View")
        full_view_btn.setStyleSheet(GlassStyles.button_secondary_style())
        full_view_btn.clicked.connect(self._open_full_bill_view)
        top_layout.addWidget(full_view_btn)
        
        layout.addWidget(top_bar)
        
        # Payment summary section
        self.summary_card = self._create_card()
        summary_layout = QVBoxLayout(self.summary_card)
        summary_layout.setContentsMargins(12, 10, 12, 10)
        summary_layout.setSpacing(8)
        
        summary_title = QLabel("Payment Summary")
        summary_title.setStyleSheet(f"color: {GlassColors.TEXT_PRIMARY}; font-size: 12px; font-weight: bold;")
        summary_layout.addWidget(summary_title)
        
        self.summary_content = QLabel("No payment summary loaded")
        self.summary_content.setStyleSheet(f"color: {GlassColors.TEXT_SECONDARY}; font-size: 10px;")
        self.summary_content.setWordWrap(True)
        summary_layout.addWidget(self.summary_content)
        self.summary_card.setMaximumHeight(140)
        self.summary_card.setVisible(self._preview_summary_visible)
        
        layout.addWidget(self.summary_card)
        
        # Preview canvas
        preview_card = self._create_card()
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        
        self.preview_scroll = QScrollArea()
        self.preview_scroll.setWidgetResizable(False)
        self.preview_scroll.setStyleSheet(f"background-color: {GlassColors.GLASS_BG}; border: none;")
        self.preview_scroll.viewport().installEventFilter(self)
        
        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setStyleSheet(f"background-color: {GlassColors.GLASS_BG};")
        self.preview_label.setMinimumSize(800, 1100)
        self.preview_scroll.setWidget(self.preview_label)
        
        preview_layout.addWidget(self.preview_scroll)
        layout.addWidget(preview_card, 1)
    
    def _build_locations_page(self) -> None:
        """Build the factory locations page."""
        layout = QVBoxLayout(self.locations_page)
        layout.setContentsMargins(14, 6, 14, 6)
        layout.setSpacing(6)
        
        # Top bar
        top_bar = self._create_card()
        top_layout = QGridLayout(top_bar)
        top_layout.setContentsMargins(12, 8, 12, 8)
        top_layout.setSpacing(8)
        
        factory_label = QLabel("Factory Name")
        factory_label.setStyleSheet("color: #334155; font-weight: bold; font-size: 10px;")
        top_layout.addWidget(factory_label, 0, 0)
        
        self.factory_name_display = QLineEdit()
        self.factory_name_display.setReadOnly(True)
        self.factory_name_display.setStyleSheet("""
            QLineEdit {
                padding: 6px 10px;
                border: 1px solid #cbd5e1;
                border-radius: 4px;
                background-color: #f8fafc;
                font-size: 10px;
            }
        """)
        top_layout.addWidget(self.factory_name_display, 1, 0)
        
        location_label = QLabel("Location (lat,long,radius)")
        location_label.setStyleSheet("color: #334155; font-weight: bold; font-size: 10px;")
        top_layout.addWidget(location_label, 0, 1)
        
        self.factory_location_input = QLineEdit()
        self.factory_location_input.setPlaceholderText("12.9716,77.5946,250")
        self.factory_location_input.setStyleSheet("""
            QLineEdit {
                padding: 6px 10px;
                border: 1px solid #cbd5e1;
                border-radius: 4px;
                background-color: white;
                font-size: 10px;
            }
        """)
        top_layout.addWidget(self.factory_location_input, 1, 1)
        
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(lambda: self.load_factory_locations(silent=False))
        top_layout.addWidget(refresh_btn, 1, 2)
        
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self.save_factory_location)
        top_layout.addWidget(save_btn, 1, 3)
        
        map_btn = QPushButton("Open Map")
        map_btn.clicked.connect(self.open_selected_factory_map)
        top_layout.addWidget(map_btn, 1, 4)
        
        layout.addWidget(top_bar)
        
        # Table
        table_card = self._create_card()
        table_layout = QVBoxLayout(table_card)
        table_layout.setContentsMargins(0, 0, 0, 0)
        
        self.factory_table = QTableWidget()
        self.factory_table.setColumnCount(4)
        self.factory_table.setHorizontalHeaderLabels(["ID", "Factory", "Location", "Preview"])
        self.factory_table.setStyleSheet(GlassStyles.table_style())
        
        self.factory_table.setColumnWidth(0, 70)    # ID
        self.factory_table.setColumnWidth(1, 220)   # Factory
        self.factory_table.setColumnWidth(2, 420)   # Location
        self.factory_table.setColumnWidth(3, 310)   # Preview
        
        self.factory_table.horizontalHeader().setStretchLastSection(True)
        self.factory_table.verticalHeader().setVisible(False)
        self.factory_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.factory_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.factory_table.itemSelectionChanged.connect(self.on_factory_row_select)
        
        table_layout.addWidget(self.factory_table)
        layout.addWidget(table_card, 1)
    
    def _build_dashboard_page(self) -> None:
        """Build the dashboard overview page."""
        layout = QVBoxLayout(self.dashboard_page)
        layout.setContentsMargins(14, 6, 14, 6)
        layout.setSpacing(6)
        
        # Dashboard content
        dashboard_card = self._create_card()
        dashboard_layout = QVBoxLayout(dashboard_card)
        dashboard_layout.setContentsMargins(16, 16, 16, 16)
        
        title = QLabel("📊 Dashboard Overview")
        title.setStyleSheet(f"color: {GlassColors.TEXT_PRIMARY}; font-size: 16px; font-weight: bold;")
        dashboard_layout.addWidget(title)
        
        subtitle = QLabel("Welcome to the EMD Group Purchase Approval System")
        subtitle.setStyleSheet(f"color: {GlassColors.TEXT_SECONDARY}; font-size: 12px;")
        dashboard_layout.addWidget(subtitle)
        
        dashboard_layout.addStretch()
        
        # Stats summary
        stats_label = QLabel("Use the navigation sidebar to manage purchase requests, view bills, and configure factory locations.")
        stats_label.setStyleSheet(f"color: {GlassColors.TEXT_SECONDARY}; font-size: 11px;")
        stats_label.setWordWrap(True)
        dashboard_layout.addWidget(stats_label)
        
        layout.addWidget(dashboard_card, 1)
    
    def _build_footer(self, parent_layout: QVBoxLayout) -> None:
        """Build the footer."""
        footer = QFrame()
        footer.setStyleSheet(f"background-color: {GlassColors.BG_MID};")
        footer.setFixedHeight(24)
        
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(0, 0, 14, 0)
        
        footer_layout.addStretch()
        
        footer_label = QLabel("EMD Group  ·  Purchase Approval System  ·  Created by Daniyal  ·  © 2026")
        footer_label.setStyleSheet(f"color: {GlassColors.TEXT_MUTED}; font-size: 8px;")
        footer_layout.addWidget(footer_label)
        
        parent_layout.addWidget(footer)
    
    def _switch_page(self, page_id: str) -> None:
        """Switch to the specified page."""
        page_titles = {
            "dashboard": "📊 Dashboard Overview",
            "requests": "📋 Purchase Requests",
            "bills": "🧾 Bill Uploads",
            "preview": "🖼 Bill Preview",
            "locations": "🏭 Factory Locations",
        }
        
        self.page_title.setText(page_titles.get(page_id, page_id.title()))
        self._active_page = page_id
        
        # Update nav buttons
        for pid, btn in self._nav_btns.items():
            btn.setChecked(pid == page_id)
            btn.setStyleSheet(GlassStyles.sidebar_button_style(is_active=(pid == page_id)))
        
        # Switch stacked widget
        page_map = {
            "requests": 0,
            "bills": 1,
            "preview": 2,
            "locations": 3,
            "dashboard": 4,
        }
        self.pages_container.setCurrentIndex(page_map.get(page_id, 0))
    
    def _update_nav_active(self, active: str) -> None:
        """Update navigation active state."""
        for pid, btn in self._nav_btns.items():
            btn.setChecked(pid == active)
    
    # ==================== BUSINESS LOGIC METHODS ====================
    # These methods are preserved from the original Tkinter implementation
    
    def _server_url(self) -> str:
        url = DEFAULT_BASE_URL.rstrip("/")
        if not url.startswith("https://"):
            raise RuntimeError(f"Server URL must be HTTPS (got {url!r})")
        return url
    
    def login(self) -> None:
        """Login to the server."""
        base = DEFAULT_BASE_URL.rstrip("/")
        try:
            response = self.session.post(
                f"{base}/login",
                data={"username": self.username_input.text(), "password": self.password_input.text()},
                allow_redirects=False,
                timeout=20,
            )
            if response.status_code not in (302, 303):
                self.logged_in = False
                self.set_connection_state(False)
                self.statusBar.showMessage("Login failed")
                QMessageBox.critical(self, "Login", f"Login failed: HTTP {response.status_code}")
                return
            redirect_to = (response.headers.get("Location") or "").strip()
            if redirect_to.startswith("http"):
                try:
                    redirect_to = urljoin(base + "/", redirect_to)
                except Exception:
                    redirect_to = "/"
            if str(redirect_to).endswith("/login") or str(redirect_to) == "/login":
                self.set_connection_state(False)
                QMessageBox.critical(self, "Login", "Invalid username or password")
                return

            auth_check = self.session.get(f"{base}/requests", timeout=20)
            if auth_check.status_code != 200:
                self.set_connection_state(False)
                QMessageBox.critical(self, "Login", "Login succeeded but session validation failed. Please try again.")
                return
            self.logged_in = True
            self.set_connection_state(True)
            self.statusBar.showMessage("Login successful")
            self.status_chip.setText("Logged in")
            self.load_factory_locations(silent=True)
            QMessageBox.information(self, "Login", "Logged in successfully.")
        except Exception as exc:
            self.logged_in = False
            self.set_connection_state(False)
            QMessageBox.critical(self, "Login", f"Login error: {exc}")
    
    def set_connection_state(self, is_online: bool) -> None:
        """Update connection state display."""
        self.conn_text = "Online" if is_online else "Offline"
        self.conn_label.setText(self.conn_text)
        color = "#00e676" if is_online else "#dc3545"
        self.conn_dot.setStyleSheet(f"color: {color}; font-size: 13px;")
    
    def sync_from_server(self, silent: bool = False) -> bool:
        """Sync data from server."""
        base = DEFAULT_BASE_URL.rstrip("/")
        try:
            response = self.session.get(f"{base}/requests", timeout=30)
            if response.status_code != 200:
                self.set_connection_state(False)
                if not silent:
                    QMessageBox.critical(self, "Sync", f"Failed to sync: HTTP {response.status_code}")
                return False
            data = response.json()
            items = data.get("items", [])
            self._last_server_items = items
            self._populate_from_server_items(items)
            self.load_factory_locations(silent=True)
            self.set_connection_state(True)
            self.statusBar.showMessage(f"Synced {len(items)} requests at {datetime.now().strftime('%H:%M:%S')}")
            self.status_chip.setText(f"Synced {len(items)}")
            return True
        except Exception as exc:
            self.set_connection_state(False)
            if not silent:
                QMessageBox.critical(self, "Sync", f"Sync error: {exc}")
            return False
    
    def schedule_auto_sync(self) -> None:
        """Schedule automatic sync."""
        if self.auto_sync_checkbox.isChecked() and self.logged_in:
            self.sync_from_server(silent=True)
        QTimer.singleShot(10000, self.schedule_auto_sync)
    
    def _is_simple_bill_upload_item(self, item: dict) -> bool:
        """Check if item is a simple bill upload."""
        entry_type = (item.get("entry_type") or "").strip().lower()
        if entry_type:
            return entry_type == "simple_bill_upload"

        # Fallback for older server payloads that don't include entry_type
        item_category = (item.get("item_category") or "").strip().lower()
        item_name = (item.get("item_name") or "").strip().lower()
        reason = (item.get("reason") or "").strip().lower()
        
        # Check for simple bill upload pattern
        if (
            item_category == "bill upload"
            and item_name == "actual bill upload"
            and reason == "actual bill uploaded via simple tab"
        ):
            return True
        
        # Additional check: if item_category is "bill upload" and item_name is empty or generic
        if item_category == "bill upload" and (not item_name or item_name in ("actual bill upload", "bill upload")):
            return True
        
        # Check if it's a bill upload by checking if typical request fields are missing
        # Bill uploads typically don't have qty, unit, rate, gst_percent
        has_qty = item.get("qty") is not None and str(item.get("qty")).strip() not in ("", "0", "0.0")
        has_unit = bool(item.get("unit"))
        has_rate = item.get("rate") is not None and float(item.get("rate") or 0) > 0
        has_gst = item.get("gst_percent") is not None and float(item.get("gst_percent") or 0) > 0
        
        # If it lacks typical request fields but has bill_image_path, it's likely a bill upload
        if not has_qty and not has_unit and not has_rate and not has_gst:
            if item.get("bill_image_path"):
                return True
        
        return False
    
    def _populate_from_server_items(self, items: list[dict]) -> None:
        """Populate tables from server items."""
        self.bill_paths.clear()
        self.requests_table.setRowCount(0)
        self.bills_table.setRowCount(0)

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

            if is_simple_bill:
                # Bill uploads
                row_position = self.bills_table.rowCount()
                self.bills_table.insertRow(row_position)
                self.bills_table.setItem(row_position, 0, QTableWidgetItem(str(req_id)))
                self.bills_table.setItem(row_position, 1, QTableWidgetItem(it.get("request_date", "")))
                self.bills_table.setItem(row_position, 2, QTableWidgetItem(str(it.get("factory_id", ""))))
                self.bills_table.setItem(row_position, 3, QTableWidgetItem(it.get("vendor", "")))
                self.bills_table.setItem(row_position, 4, QTableWidgetItem(it.get("requested_by", "")))
                self.bills_table.setItem(row_position, 5, QTableWidgetItem("Received"))
                self.bills_table.setItem(row_position, 6, QTableWidgetItem(it.get("updated_at", "")))
                
                if (it.get("approval_status") or "") != "Received":
                    bills_to_receive.append(req_id)
                if is_new:
                    new_bill_count += 1
                    first_new_bill_added = True
            else:
                # Regular requests
                approval_status = (it.get("approval_status") or "").strip()
                if approval_status == "Hold":
                    approval_status = "Partial Approved"
                if self._status_filter and approval_status != self._status_filter:
                    continue
                comp_filter = self._comp_filter
                comp_status = (it.get("completion_status") or "Pending")
                if comp_filter and comp_status != comp_filter:
                    continue
                
                row_position = self.requests_table.rowCount()
                self.requests_table.insertRow(row_position)
                self.requests_table.setItem(row_position, 0, QTableWidgetItem(str(req_id)))
                self.requests_table.setItem(row_position, 1, QTableWidgetItem(it.get("request_date", "")))
                self.requests_table.setItem(row_position, 2, QTableWidgetItem(str(it.get("factory_id", ""))))
                self.requests_table.setItem(row_position, 3, QTableWidgetItem(it.get("request_type") or it.get("item_category") or ""))
                self.requests_table.setItem(row_position, 4, QTableWidgetItem(it.get("purpose") or it.get("item_name") or ""))
                self.requests_table.setItem(row_position, 5, QTableWidgetItem(f"{float(it.get('final_amount') or 0):.2f}"))
                self.requests_table.setItem(row_position, 6, QTableWidgetItem(f"{float(it.get('total_paid') or 0):.2f}"))
                self.requests_table.setItem(row_position, 7, QTableWidgetItem(f"{float(it.get('balance_amount') or 0):.2f}"))
                self.requests_table.setItem(row_position, 8, QTableWidgetItem(it.get("requested_by", "")))
                self.requests_table.setItem(row_position, 9, QTableWidgetItem(approval_status))
                self.requests_table.setItem(row_position, 10, QTableWidgetItem(it.get("payment_status", "")))
                self.requests_table.setItem(row_position, 11, QTableWidgetItem(comp_status))
                self.requests_table.setItem(row_position, 12, QTableWidgetItem(it.get("updated_at", "")))
                
                # Color code based on status
                self._color_code_row(row_position, approval_status)
                
                if is_new:
                    new_req_count += 1
                    first_new_request_added = True

        self.new_requests_count = new_req_count
        self.new_bills_count = new_bill_count
        self._update_stats_bar(items)
        
        if bills_to_receive and self.logged_in:
            threading.Thread(
                target=self._mark_bills_received,
                args=(bills_to_receive,),
                daemon=True,
            ).start()
    
    def _color_code_row(self, row: int, status: str) -> None:
        """Apply color coding to table row based on status."""
        colors = {
            "Approved": "#ecfdf3",
            "Rejected": "#fff1f2",
            "Pending": "#fff7ed",
            "Partial Approved": "#fefce8",
            "Draft": "#f8fafc",
        }
        bg_color = colors.get(status, "#ffffff")
        for col in range(self.requests_table.columnCount()):
            item = self.requests_table.item(row, col)
            if item:
                item.setBackground(QColor(bg_color))
    
    def _mark_bills_received(self, bill_ids: list[int]) -> None:
        """Mark bill uploads as received on server."""
        base = DEFAULT_BASE_URL.rstrip("/")
        for req_id in bill_ids:
            try:
                self.session.post(f"{base}/requests/{req_id}/receive", timeout=10)
            except Exception:
                pass
    
    def _apply_status_filter(self, status: str) -> None:
        """Apply status filter."""
        self._status_filter = status
        self._highlight_filter_btn(status)
        self._populate_from_server_items(self._last_server_items)
    
    def _apply_comp_filter(self, value: str) -> None:
        """Apply completion filter."""
        self._comp_filter = value
        for v, btn in self._comp_filter_btns.items():
            btn.setChecked(v == value)
        self._populate_from_server_items(self._last_server_items)
    
    def _highlight_filter_btn(self, active: str) -> None:
        """Highlight active filter button."""
        for value, btn in self._filter_btns.items():
            btn.setChecked(value == active)
    
    def _update_stats_bar(self, items: list[dict]) -> None:
        """Update KPI statistics."""
        non_bills = [x for x in items if not self._is_simple_bill_upload_item(x)]
        total = len(non_bills)
        pending = sum(1 for x in non_bills if (x.get("approval_status") or "") == "Pending")
        approved = sum(1 for x in non_bills if (x.get("approval_status") or "") == "Approved")
        rejected = sum(1 for x in non_bills if (x.get("approval_status") or "") == "Rejected")
        hold = sum(1 for x in non_bills if (x.get("approval_status") or "") in ("Partial Approved", "Hold"))
        approved_items = [x for x in non_bills if (x.get("approval_status") or "") == "Approved"]
        pending_completion = sum(
            1
            for x in approved_items
            if (x.get("completion_status") or "Pending") in ("Pending", "Awaiting Completion")
        )

        active_filter = self._status_filter
        if active_filter:
            amount_items = [x for x in non_bills if (x.get("approval_status") or "") == active_filter]
        else:
            amount_items = non_bills
        amount = sum(float(x.get("final_amount") or 0) for x in amount_items)

        self.kpi_total.setText(str(total))
        self.kpi_pending.setText(str(pending))
        self.kpi_approved.setText(str(approved))
        self.kpi_rejected.setText(str(rejected))
        self.kpi_partial.setText(str(hold))
        self.kpi_awaiting.setText(f"{pending_completion}/{approved}")
        self.kpi_amount.setText(f"₹{amount:,.0f}")
    
    def _mark_item_as_viewed(self, req_id: int) -> None:
        """Mark item as viewed."""
        self._viewed_ids.add(int(req_id))
        self._populate_from_server_items(self._last_server_items)
    
    def _apply_search_filter(self) -> None:
        """Apply search filter."""
        if not self._last_server_items:
            return
        query = self.search_input.text().strip().lower()
        if not query or query.startswith("🔍"):
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
    
    def _parse_location_text(self, raw: str) -> tuple[float, float, float] | None:
        """Parse location text."""
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
        """Preview location string."""
        parsed = self._parse_location_text(location)
        if not parsed:
            return "Not set / invalid"
        lat, lon, radius = parsed
        return f"Lat {lat:.6f}, Lon {lon:.6f}, Radius {radius:.0f}m"
    
    def load_factory_locations(self, silent: bool = False) -> None:
        """Load factory locations from server."""
        base = DEFAULT_BASE_URL.rstrip("/")
        try:
            response = self.session.get(f"{base}/masters/factories", timeout=20)
            if response.status_code != 200:
                self.set_connection_state(False)
                if not silent:
                    QMessageBox.critical(self, "Factories", f"Failed to load factories: HTTP {response.status_code}")
                return

            data = response.json()
            items = data.get("items", [])
            self.factories_cache = {int(x["id"]): x for x in items if "id" in x}

            self.factory_table.setRowCount(0)
            for it in items:
                fid = int(it.get("id", 0))
                name = it.get("name", "")
                location = (it.get("location") or "").strip()
                row_position = self.factory_table.rowCount()
                self.factory_table.insertRow(row_position)
                self.factory_table.setItem(row_position, 0, QTableWidgetItem(str(fid)))
                self.factory_table.setItem(row_position, 1, QTableWidgetItem(name))
                self.factory_table.setItem(row_position, 2, QTableWidgetItem(location))
                self.factory_table.setItem(row_position, 3, QTableWidgetItem(self._preview_location(location)))

            self.set_connection_state(True)
        except Exception as exc:
            self.set_connection_state(False)
            if not silent:
                QMessageBox.critical(self, "Factories", f"Error loading factories: {exc}")
    
    def on_factory_row_select(self) -> None:
        """Handle factory row selection."""
        current_row = self.factory_table.currentRow()
        if current_row < 0:
            return
        self.factory_name_display.setText(self.factory_table.item(current_row, 1).text())
        self.factory_location_input.setText(self.factory_table.item(current_row, 2).text())
    
    def save_factory_location(self) -> None:
        """Save factory location."""
        current_row = self.factory_table.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "Factories", "Select a factory first.")
            return

        factory_id = int(self.factory_table.item(current_row, 0).text())
        row = self.factories_cache.get(factory_id)
        if not row:
            QMessageBox.critical(self, "Factories", "Selected factory not found in cache.")
            return

        location = self.factory_location_input.text().strip()
        if location and not self._parse_location_text(location):
            QMessageBox.critical(
                self,
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
                QMessageBox.critical(self, "Factories", self._extract_error_message(body, response.status_code))
                return

            self.set_connection_state(True)
            self.statusBar.showMessage("Factory location updated")
            self.load_factory_locations(silent=True)
            QMessageBox.information(self, "Factories", body.get("message", "Factory location updated"))
        except Exception as exc:
            self.set_connection_state(False)
            QMessageBox.critical(self, "Factories", f"Failed to save location: {exc}")
    
    def open_selected_factory_map(self) -> None:
        """Open factory location in map."""
        text = self.factory_location_input.text().strip()
        parsed = self._parse_location_text(text)
        if not parsed:
            QMessageBox.warning(self, "Factories", "Enter valid location first: latitude,longitude,radius")
            return
        lat, lon, _radius = parsed
        webbrowser.open_new_tab(f"https://maps.google.com/?q={lat},{lon}")
    
    def selected_request_id(self) -> int | None:
        """Get selected request ID from main table."""
        current_row = self.requests_table.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "Select", "Select a request first.")
            return None
        req_id = int(self.requests_table.item(current_row, 0).text())
        self._mark_item_as_viewed(req_id)
        return req_id
    
    def selected_request_id_any(self) -> int | None:
        """Get selected request ID from either table."""
        def _id_from_table(table: QTableWidget) -> int | None:
            selected_rows = table.selectionModel().selectedRows() if table.selectionModel() else []
            if selected_rows:
                row = selected_rows[0].row()
                item = table.item(row, 0)
                if item is not None:
                    return int(item.text())
            current_row = table.currentRow()
            if current_row >= 0 and table.hasFocus():
                item = table.item(current_row, 0)
                if item is not None:
                    return int(item.text())
            return None

        req_id = None
        if self._active_page == "bills":
            req_id = _id_from_table(self.bills_table) or _id_from_table(self.requests_table)
        else:
            req_id = _id_from_table(self.requests_table) or _id_from_table(self.bills_table)
        
        if req_id is None and self.preview_req_id is not None:
            req_id = self.preview_req_id
        
        if req_id is None:
            QMessageBox.warning(self, "Select", "Select a request or bill upload first.")
            return None
        
        self._mark_item_as_viewed(req_id)
        return req_id
    
    def _on_table_double_click(self, item: QTableWidgetItem) -> None:
        """Handle table double-click."""
        try:
            row = item.row()
            if row < 0:
                return
            id_item = self.requests_table.item(row, 0)
            if id_item is None:
                return
            req_id = int(id_item.text())
            self.open_request_detail_window(req_id)
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.critical(self, "Request Summary", f"Failed to open request summary: {exc}")
    
    def _on_bills_table_double_click(self, item: QTableWidgetItem) -> None:
        """Handle bills table double-click to view bill preview."""
        row = item.row()
        req_id = int(self.bills_table.item(row, 0).text())
        self.bills_table.clearSelection()
        self.bills_table.selectRow(row)
        self._view_bill_for_request(req_id)
    
    def approve_selected(self) -> None:
        """Approve selected request."""
        req_id = self.selected_request_id()
        if req_id is None:
            return
        self.open_approve_dialog(req_id)

    def open_approve_dialog(self, req_id: int) -> None:
        """Open approve dialog with amount and remarks."""
        req_data = {}
        for item in self._last_server_items:
            if item.get("id") == req_id:
                req_data = item
                break

        def as_money(v) -> float:
            try:
                return float(v or 0)
            except Exception:
                return 0.0

        default_amount = as_money(
            req_data.get("approved_amount") or req_data.get("final_amount") or req_data.get("amount")
        )
        if default_amount <= 0:
            default_amount = as_money(req_data.get("total_amount"))

        dialog = QDialog(self)
        dialog.setWindowTitle(f"Approve Request - #{req_id}")
        dialog.resize(460, 290)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        amount_label = QLabel("Approved Amount (INR) *")
        amount_label.setStyleSheet("color: #334155; font-weight: bold; font-size: 10px;")
        layout.addWidget(amount_label)

        amount_input = QLineEdit(f"{default_amount:.2f}" if default_amount > 0 else "")
        amount_input.setStyleSheet("padding: 6px 10px; border: 1px solid #cbd5e1; border-radius: 4px; font-size: 11px;")
        layout.addWidget(amount_input)

        remarks_label = QLabel("Remarks (optional)")
        remarks_label.setStyleSheet("color: #334155; font-weight: bold; font-size: 10px;")
        layout.addWidget(remarks_label)

        remarks_input = QTextEdit()
        remarks_input.setMaximumHeight(80)
        remarks_input.setStyleSheet("padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px;")
        layout.addWidget(remarks_input)

        status_label = QLabel("")
        status_label.setWordWrap(True)
        status_label.setStyleSheet("color: #64748b; font-size: 10px;")
        layout.addWidget(status_label)

        button_layout = QHBoxLayout()
        button_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(dialog.reject)
        button_layout.addWidget(cancel_btn)

        submit_btn = QPushButton("Approve")
        submit_btn.setStyleSheet("background-color: #15803d; color: white; font-weight: bold; padding: 8px 16px; border: none; border-radius: 4px;")
        button_layout.addWidget(submit_btn)

        layout.addLayout(button_layout)

        def on_submit():
            amount_str = amount_input.text().strip()
            if not amount_str:
                status_label.setText("Approved amount is required.")
                status_label.setStyleSheet("color: #b02a37;")
                return
            try:
                amount = float(amount_str)
                if amount <= 0:
                    raise ValueError
            except ValueError:
                status_label.setText("Approved amount must be a positive number.")
                status_label.setStyleSheet("color: #b02a37;")
                return

            payload = {"approved_amount": f"{amount:.2f}"}
            remarks = remarks_input.toPlainText().strip()
            if remarks:
                payload["remarks"] = remarks

            success, message = self._perform_action(f"/requests/{req_id}/approve", payload)
            status_label.setText(message)
            status_label.setStyleSheet("color: #1f8a43;" if success else "color: #b02a37;")
            if success:
                self.sync_from_server(silent=True)
                QTimer.singleShot(900, dialog.accept)

        submit_btn.clicked.connect(on_submit)
        dialog.exec()
    
    def reject_selected(self) -> None:
        """Reject selected request."""
        req_id = self.selected_request_id()
        if req_id is None:
            return
        self.open_text_action_dialog(
            title="Reject Request",
            req_id=req_id,
            path_template="/requests/{req_id}/reject",
            field_name="reason",
            alias_field_names=("rejection_reason", "remarks", "comment"),
            field_label="Rejection Reason",
            submit_text="Reject",
            required=True,
        )
    
    def hold_selected(self) -> None:
        """Partial approve selected request."""
        req_id = self.selected_request_id()
        if req_id is None:
            return
        self.open_partial_approve_dialog(req_id)
    
    def verify_selected(self) -> None:
        """Verify and close selected request."""
        req_id = self.selected_request_id()
        if req_id is None:
            return
        self.open_verify_dialog(req_id)
    
    def reopen_selected(self) -> None:
        """Reopen selected request."""
        req_id = self.selected_request_id()
        if req_id is None:
            return
        self.open_reopen_dialog(req_id)
    
    def delete_selected(self) -> None:
        """Delete selected entry."""
        req_id = self.selected_request_id_any()
        if req_id is None:
            return

        reply = QMessageBox.question(
            self,
            "Delete Entry",
            f"Delete entry #{req_id}? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.No:
            return

        expected = self._expected_delete_password()
        entered, ok = QInputDialog.getText(
            self,
            "Delete Password",
            "Enter delete password to confirm:",
            QLineEdit.Password
        )
        if not ok or not entered:
            return
        if not expected or entered.strip() != expected:
            QMessageBox.critical(self, "Delete Entry", "Invalid delete password.")
            return

        base = DEFAULT_BASE_URL.rstrip("/")
        try:
            response = self.session.delete(f"{base}/requests/{req_id}", timeout=30)
            body = response.json() if response.headers.get("Content-Type", "").startswith("application/json") else {}
            if response.status_code != 200:
                self.set_connection_state(False)
                QMessageBox.critical(self, "Delete Entry", self._extract_error_message(body, response.status_code))
                return
            self.set_connection_state(True)
            self.statusBar.showMessage(body.get("message", f"Entry #{req_id} deleted"))
            self.sync_from_server(silent=True)
            QMessageBox.information(self, "Delete Entry", body.get("message", "Deleted"))
        except Exception as exc:
            self.set_connection_state(False)
            QMessageBox.critical(self, "Delete Entry", f"Delete failed: {exc}")
    
    def _expected_delete_password(self) -> str:
        """Get expected delete password."""
        return (os.getenv("ADMIN_DELETE_PASSWORD") or self.password_input.text() or "").strip()
    
    def view_bill_selected(self) -> None:
        """View bill for selected request."""
        req_id = self.selected_request_id_any()
        if req_id is None:
            return
        self._view_bill_for_request(req_id, open_in_window=True)

    def _view_bill_for_request(self, req_id: int, open_in_window: bool = False) -> None:
        """View bill for a specific request ID."""
        path = (self.bill_paths.get(req_id) or "").strip()
        if not path:
            QMessageBox.information(self, "Bill", "No bill file attached for this request.")
            return

        if req_id == self.preview_req_id and self.preview_label.pixmap() is not None:
            self.preview_status.setText(f"Previewing request #{req_id} - {self.preview_filename}")
            self._switch_page("preview")
            if open_in_window:
                self._open_full_bill_view()
            return

        self._open_bill_in_window_for_req = req_id if open_in_window else None

        self.preview_req_id = req_id
        self.preview_filename = ""
        self.preview_label.clear()
        self.summary_content.setText("Loading payment summary...")
        self.preview_status.setText(f"Loading bill for request #{req_id}...")
        self._show_preview_message("Loading bill from server...")
        self._switch_page("preview")

        if self._bill_loader and self._bill_loader.isRunning():
            self._bill_loader.requestInterruption()
            self._bill_loader.wait(500)

        self._bill_loader = BillFetchThread(self, req_id)
        self._bill_loader.loaded.connect(self._on_bill_loaded)
        self._bill_loader.failed.connect(self._on_bill_failed)
        self._bill_loader.start()
        
        # Load payment summary
        self._load_payment_summary(req_id)

    def _on_bill_loaded(self, req_id: int, content: bytes, filename: str, content_type: str) -> None:
        """Render a fetched bill on the UI thread."""
        if req_id != self.preview_req_id:
            return
        self.preview_filename = filename
        self._render_bill_preview(content, filename, content_type)
        self.preview_status.setText(f"Previewing request #{req_id} - {self.preview_filename}")
        if self._open_bill_in_window_for_req == req_id:
            self._open_bill_in_window_for_req = None
            self._open_full_bill_view()

    def _on_bill_failed(self, req_id: int, err: str) -> None:
        """Show bill loading errors on the UI thread."""
        if req_id != self.preview_req_id:
            return
        if self._open_bill_in_window_for_req == req_id:
            self._open_bill_in_window_for_req = None
        self.preview_status.setText(err)
        self._show_preview_message(err)
        QMessageBox.critical(self, "Bill Error", err)
    
    def _load_payment_summary(self, req_id: int) -> None:
        """Load payment summary for the request."""
        # Keep a strong reference to avoid QThread being destroyed while running.
        if self._payment_summary_loader and self._payment_summary_loader.isRunning():
            self._payment_summary_loader.requestInterruption()
            self._payment_summary_loader.wait(500)

        self._payment_summary_loader = PaymentSummaryThread(self, req_id)
        self._payment_summary_loader.loaded.connect(self._on_payment_summary_loaded)
        self._payment_summary_loader.failed.connect(self._on_payment_summary_failed)
        self._payment_summary_loader.finished.connect(self._on_payment_summary_finished)
        self._payment_summary_loader.start()

    def _on_payment_summary_finished(self) -> None:
        """Release summary loader reference after completion."""
        self._payment_summary_loader = None
    
    def _on_payment_summary_loaded(self, req_id: int, summary_data: object) -> None:
        """Display loaded payment summary."""
        if req_id != self.preview_req_id:
            return
        
        if not summary_data:
            self.summary_content.setText("No payment summary available")
            return
        
        # Format summary data
        summary_text = ""
        if isinstance(summary_data, dict):
            for key, value in summary_data.items():
                if value is not None:
                    summary_text += f"<b>{key}:</b> {value}<br>"
        
        if summary_text:
            self.summary_content.setText(summary_text)
        else:
            self.summary_content.setText("No payment summary data available")
    
    def _on_payment_summary_failed(self, req_id: int, err: str) -> None:
        """Handle payment summary loading failure."""
        if req_id != self.preview_req_id:
            return
        self.summary_content.setText(f"Failed to load payment summary: {err}")
    
    def download_bill_selected(self) -> None:
        """Download bill for selected request."""
        req_id = self.selected_request_id_any()
        if req_id is None:
            return
        path = (self.bill_paths.get(req_id) or "").strip()
        if not path:
            QMessageBox.information(self, "Bill", "No bill file attached for this request.")
            return
        self._download_bill_as_pdf(req_id, self)
    
    def _fetch_bill_response(self, req_id: int, stream: bool) -> tuple[requests.Response | None, str, str | None]:
        """Fetch bill response from server."""
        base = DEFAULT_BASE_URL.rstrip("/")
        endpoint = f"{base}/requests/{req_id}/bill"

        def _fetch_from_endpoint(url: str) -> tuple[requests.Response | None, str | None]:
            first = self.session.get(url, allow_redirects=False, timeout=20, stream=stream)
            if first.status_code in (301, 302, 307, 308):
                location = first.headers.get("Location", "")
                if not location or "/login" in location:
                    return None, "Session expired. Please login again."
                target = location if location.startswith("http") else urljoin(base + "/", location.lstrip("/"))
                resp = self.session.get(target, timeout=30, stream=stream)
                if resp.status_code != 200:
                    return None, f"Failed to fetch file (HTTP {resp.status_code})"
                self._last_bill_url_by_req[req_id] = target
                return resp, None
            if first.status_code == 200:
                return first, None
            if first.status_code in (401, 403):
                return None, "Session expired. Please login again."
            detail = ""
            try:
                detail = first.json().get("detail", "")
            except Exception:
                pass
            return None, (detail or f"Server returned HTTP {first.status_code}")

        last_url = (self._last_bill_url_by_req.get(req_id) or "").strip()
        if last_url:
            try:
                cached_resp = self.session.get(last_url, timeout=30, stream=stream)
                if cached_resp.status_code == 200:
                    return cached_resp, self._filename_from_response(cached_resp, last_url, req_id), None
            except Exception:
                pass

        try:
            resp, err = _fetch_from_endpoint(endpoint)
            if resp is not None:
                return resp, self._filename_from_response(resp, endpoint, req_id), None
        except Exception as exc:
            err = f"Failed to contact server: {exc}"

        # Fallback for completion flows where bill is uploaded as vendor bill or voucher.
        for suffix in ("vendor-bill", "company-voucher"):
            alt_endpoint = f"{base}/requests/{req_id}/{suffix}"
            try:
                alt_resp, alt_err = _fetch_from_endpoint(alt_endpoint)
                if alt_resp is not None:
                    return alt_resp, self._filename_from_response(alt_resp, alt_endpoint, req_id), None
                if alt_err and "Session expired" in alt_err:
                    return None, "", alt_err
            except Exception:
                pass

        return None, "", (err or "No previewable request document found.")
    
    def _filename_from_response(self, resp: requests.Response, source_url: str, req_id: int) -> str:
        """Extract filename from response."""
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
        """Show message in preview area."""
        self._preview_source_pixmap = None
        self.preview_label.clear()
        self.preview_label.setText(message)
        self.preview_label.setStyleSheet("color: #1a3a6e; font-size: 11px;")

    def eventFilter(self, obj, event):
        if obj is self.preview_scroll.viewport() and event.type() == event.Type.Resize:
            self._refresh_preview_scaled_pixmap()
        return super().eventFilter(obj, event)

    def _toggle_preview_summary(self) -> None:
        """Toggle payment summary visibility to prioritize bill preview space."""
        self._preview_summary_visible = not self._preview_summary_visible
        self.summary_card.setVisible(self._preview_summary_visible)
        if self._preview_summary_visible:
            self.preview_summary_toggle_btn.setText("Hide Summary")
        else:
            self.preview_summary_toggle_btn.setText("Show Summary")

    def _refresh_preview_scaled_pixmap(self) -> None:
        """Scale preview image to the current viewport for better readability."""
        if self._preview_source_pixmap is None or self._preview_source_pixmap.isNull():
            return
        viewport = self.preview_scroll.viewport().size()
        if viewport.width() < 40 or viewport.height() < 40:
            self.preview_label.setPixmap(self._preview_source_pixmap)
            self.preview_label.resize(self._preview_source_pixmap.size())
            return
        # Fit to available width and allow vertical scrolling for full document height.
        target_width = max(320, viewport.width() - 24)
        scaled = self._preview_source_pixmap.scaledToWidth(target_width, Qt.SmoothTransformation)
        self.preview_label.setPixmap(scaled)
        self.preview_label.resize(scaled.size())

    def _open_full_bill_view(self) -> None:
        """Open current bill preview in a maximized dialog for full-screen viewing."""
        if self._preview_source_pixmap is None or self._preview_source_pixmap.isNull():
            QMessageBox.information(self, "Full View", "Load a bill preview first.")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Bill Preview - Full View")
        dialog.resize(1200, 800)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(8, 8, 8, 8)

        scroll = QScrollArea(dialog)
        scroll.setWidgetResizable(True)
        full_label = QLabel()
        full_label.setAlignment(Qt.AlignCenter)
        full_label.setPixmap(self._preview_source_pixmap)
        scroll.setWidget(full_label)
        layout.addWidget(scroll)

        dialog.showMaximized()
        dialog.exec()

    def _is_pdf_payload(self, content: bytes, filename: str, content_type: str) -> bool:
        """Detect PDF payload even when filename/content-type are generic."""
        lower_name = (filename or "").lower()
        ctype = (content_type or "").lower()
        return (
            lower_name.endswith(".pdf")
            or "application/pdf" in ctype
            or content.startswith(b"%PDF-")
        )

    def _is_image_payload(self, content: bytes, filename: str, content_type: str) -> bool:
        """Detect common image payload signatures for .bin files."""
        lower_name = (filename or "").lower()
        ctype = (content_type or "").lower()
        if any(lower_name.endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff")):
            return True
        if ctype.startswith("image/"):
            return True
        signatures = (
            b"\x89PNG\r\n\x1a\n",  # PNG
            b"\xff\xd8\xff",        # JPEG
            b"GIF87a",                 # GIF87a
            b"GIF89a",                 # GIF89a
            b"BM",                     # BMP
            b"II*\x00",               # TIFF (little-endian)
            b"MM\x00*",               # TIFF (big-endian)
        )
        if any(content.startswith(sig) for sig in signatures):
            return True
        # WEBP container: RIFF....WEBP
        return len(content) > 12 and content.startswith(b"RIFF") and content[8:12] == b"WEBP"

    def _download_bill_as_pdf(self, req_id: int, parent: QWidget | None = None) -> None:
        """Download a request document in PDF format (convert image payloads to PDF)."""
        owner = parent or self
        resp, filename, err = self._fetch_bill_response(req_id, stream=False)
        if err or resp is None:
            QMessageBox.critical(owner, "Download Bill", err or "Failed to fetch bill")
            return

        try:
            content = resp.content
            content_type = resp.headers.get("Content-Type", "")
        except Exception as exc:
            QMessageBox.critical(owner, "Download Bill", f"Failed to read bill content: {exc}")
            return

        stem = Path(filename or f"request_{req_id}_bill").stem or f"request_{req_id}_bill"
        default_name = f"{stem}.pdf"
        out_file, _ = QFileDialog.getSaveFileName(
            owner,
            "Save Bill As PDF",
            default_name,
            "PDF Files (*.pdf)"
        )
        if not out_file:
            return
        if not out_file.lower().endswith(".pdf"):
            out_file = f"{out_file}.pdf"

        if self._is_pdf_payload(content, filename, content_type):
            try:
                with open(out_file, "wb") as f:
                    f.write(content)
                QMessageBox.information(owner, "Download Bill", f"Bill downloaded successfully:\n{out_file}")
            except Exception as exc:
                QMessageBox.critical(owner, "Download Bill", f"Failed to save PDF: {exc}")
            return

        if self._is_image_payload(content, filename, content_type):
            if Image is None:
                QMessageBox.critical(owner, "Download Bill", "Pillow is required to convert image bills to PDF.")
                return
            try:
                img = Image.open(io.BytesIO(content)).convert("RGB")
                img.save(out_file, "PDF")
                QMessageBox.information(owner, "Download Bill", f"Bill downloaded successfully:\n{out_file}")
            except Exception as exc:
                QMessageBox.critical(owner, "Download Bill", f"Failed to convert bill to PDF: {exc}")
            return

        QMessageBox.critical(owner, "Download Bill", "This bill format cannot be converted to PDF.")
    
    def _render_bill_preview(self, content: bytes, filename: str, content_type: str) -> None:
        """Render bill preview."""
        self._pdf_pages = []
        self._pdf_current_page = 0
        self._pdf_content = b""
        self._pdf_page_count = 0
        self.pdf_page_label.setText("")

        if self._is_pdf_payload(content, filename, content_type):
            if fitz is None:
                self._show_preview_message("PDF preview unavailable (PyMuPDF not installed). Use Download Bill to open it.")
                return
            try:
                pdf_doc = fitz.open(stream=content, filetype="pdf")
                if pdf_doc.page_count == 0:
                    self._show_preview_message("PDF is empty.")
                    return
                self._pdf_content = content
                self._pdf_page_count = pdf_doc.page_count
                self._pdf_pages = [None] * self._pdf_page_count
                pdf_doc.close()
                self._show_pdf_page(0)
                return
            except Exception as exc:
                self._show_preview_message(f"Failed to render PDF: {exc}")
                return

        if Image is None:
            self._show_preview_message("Image preview needs Pillow. Use Download Bill if preview is unavailable.")
            return

        if not self._is_image_payload(content, filename, content_type):
            self._show_preview_message("This file type is not previewable. Use Download Bill.")
            return

        try:
            img = Image.open(io.BytesIO(content))
            img = img.convert("RGB")
            qimage = QImage(img.tobytes(), img.width, img.height, QImage.Format_RGB888).copy()
            pixmap = QPixmap.fromImage(qimage)
            self._preview_source_pixmap = pixmap
            self._refresh_preview_scaled_pixmap()
        except Exception:
            self._show_preview_message("This file type is not previewable. Use Download Bill.")
    
    def _show_pdf_page(self, page_num: int) -> None:
        """Show PDF page."""
        if not self._pdf_pages or not self._pdf_content:
            return
        page_num = max(0, min(page_num, len(self._pdf_pages) - 1))
        self._pdf_current_page = page_num
        total = len(self._pdf_pages)
        img = self._pdf_pages[page_num]
        if img is None:
            try:
                pdf_doc = fitz.open(stream=self._pdf_content, filetype="pdf")
                page = pdf_doc[page_num]
                pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
                img = Image.open(io.BytesIO(pix.tobytes("ppm")))
                img.load()
                img = img.convert("RGB")
                self._pdf_pages[page_num] = img
                pdf_doc.close()
            except Exception as exc:
                self._show_preview_message(f"Failed to render PDF page: {exc}")
                return
        qimage = QImage(img.tobytes(), img.width, img.height, QImage.Format_RGB888).copy()
        pixmap = QPixmap.fromImage(qimage)
        self._preview_source_pixmap = pixmap
        self._refresh_preview_scaled_pixmap()
        self.pdf_page_label.setText(f"Page {page_num + 1} / {total}")
        self.preview_status.setText(f"PDF — Page {page_num + 1} of {total} — {self.preview_filename}")
    
    def _pdf_prev_page(self) -> None:
        """Show previous PDF page."""
        if self._pdf_pages and self._pdf_current_page > 0:
            self._show_pdf_page(self._pdf_current_page - 1)
    
    def _pdf_next_page(self) -> None:
        """Show next PDF page."""
        if self._pdf_pages and self._pdf_current_page < len(self._pdf_pages) - 1:
            self._show_pdf_page(self._pdf_current_page + 1)
    
    def export_local_excel(self) -> None:
        """Export data to Excel."""
        if Workbook is None:
            QMessageBox.critical(self, "Export", "openpyxl is not installed. Cannot export to Excel.")
            return
        
        out_file, _ = QFileDialog.getSaveFileName(
            self,
            "Export to Excel",
            "requests_export.xlsx",
            "Excel Files (*.xlsx)"
        )
        if not out_file:
            return
        
        try:
            wb = Workbook()
            ws = wb.active
            ws.title = "Requests"
            
            # Headers
            headers = [
                "ID", "Date", "Factory", "Type", "Purpose", "Requested Amount",
                "Paid Amount", "Balance", "Requested By", "Approval Status",
                "Payment Status", "Completion Status", "Updated At"
            ]
            ws.append(headers)
            
            # Data
            for row in range(self.requests_table.rowCount()):
                data = []
                for col in range(self.requests_table.columnCount()):
                    item = self.requests_table.item(row, col)
                    data.append(item.text() if item else "")
                ws.append(data)
            
            wb.save(out_file)
            QMessageBox.information(self, "Export", f"Data exported successfully to:\n{out_file}")
        except Exception as exc:
            QMessageBox.critical(self, "Export", f"Export failed: {exc}")
    
    def _extract_error_message(self, body: dict, status_code: int) -> str:
        """Extract error message from response body."""
        def _to_text(value) -> str:
            if isinstance(value, str):
                return value
            if isinstance(value, (list, tuple)):
                # FastAPI validation errors are typically a list of dict entries.
                if value and all(isinstance(x, dict) for x in value):
                    lines = []
                    for entry in value:
                        loc = entry.get("loc")
                        msg = entry.get("msg")
                        if isinstance(loc, (list, tuple)):
                            loc_parts = [str(part) for part in loc if str(part) != "body"]
                            loc_text = ".".join(loc_parts)
                        else:
                            loc_text = ""
                        msg_text = str(msg) if msg is not None else str(entry)
                        lines.append(f"{loc_text}: {msg_text}" if loc_text else msg_text)
                    return "\n".join(lines)
                return "\n".join(str(x) for x in value)
            if isinstance(value, dict):
                return ", ".join(f"{k}: {v}" for k, v in value.items())
            if value is None:
                return ""
            return str(value)

        if isinstance(body, dict):
            detail = body.get("detail")
            message = body.get("message")
            text = _to_text(detail) or _to_text(message)
            return text or f"HTTP {status_code}"
        return f"HTTP {status_code}"
    
    def _perform_action(self, endpoint: str, payload: dict) -> tuple[bool, str]:
        """Perform API action."""
        def _to_text(value) -> str:
            if isinstance(value, str):
                return value
            if isinstance(value, (list, tuple)):
                return "\n".join(str(x) for x in value)
            if isinstance(value, dict):
                return ", ".join(f"{k}: {v}" for k, v in value.items())
            if value is None:
                return ""
            return str(value)

        def _json_body(resp) -> dict:
            ctype = (resp.headers.get("Content-Type") or "").lower()
            if "application/json" in ctype:
                try:
                    data = resp.json()
                    return data if isinstance(data, dict) else {"detail": data}
                except Exception:
                    return {}
            return {}

        def _post_json(url: str):
            return self.session.post(
                url,
                json=payload,
                headers={"Accept": "application/json", "Content-Type": "application/json"},
                allow_redirects=False,
                timeout=20,
            )

        def _post_form(url: str):
            return self.session.post(
                url,
                data=payload,
                headers={"Accept": "application/json"},
                allow_redirects=False,
                timeout=20,
            )

        base = self._server_url()
        try:
            action_url = f"{base}{endpoint}"
            response = _post_json(action_url)

            # Preserve POST + JSON body across redirects; some servers emit 302 for POST routes.
            for _ in range(2):
                if response.status_code not in (301, 302, 303, 307, 308):
                    break
                location = (response.headers.get("Location") or "").strip()
                if not location:
                    break
                action_url = urljoin(action_url + "/", location)
                response = _post_json(action_url)

            body = _json_body(response)

            # Compatibility fallback: some deployments expect form fields instead of JSON.
            if response.status_code == 422:
                detail_text = _to_text(body.get("detail")).lower() if isinstance(body, dict) else ""
                if ("required" in detail_text or "missing" in detail_text) and ("body" in detail_text):
                    response = _post_form(action_url)
                    for _ in range(2):
                        if response.status_code not in (301, 302, 303, 307, 308):
                            break
                        location = (response.headers.get("Location") or "").strip()
                        if not location:
                            break
                        action_url = urljoin(action_url + "/", location)
                        response = _post_form(action_url)
                    body = _json_body(response)

            if not (200 <= response.status_code < 300):
                return False, self._extract_error_message(body, response.status_code)

            ok_text = _to_text(body.get("message")) or _to_text(body.get("detail"))
            return True, (ok_text or "Action completed successfully")
        except Exception as exc:
            return False, str(exc)
    
    # ==================== DIALOG METHODS ====================
    
    def open_request_detail_window(self, req_id: int) -> None:
        """Open request detail window with full information and bill preview."""
        # Find cached item data
        item_data = {}
        for it in self._last_server_items:
            if int(it.get("id", -1)) == req_id:
                item_data = it
                break
        
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Request #{req_id} — Full Summary")
        dialog.resize(1050, 650)
        dialog_closed = {"value": False}
        dialog.destroyed.connect(lambda *_: dialog_closed.__setitem__("value", True))
        
        layout = QHBoxLayout(dialog)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Left panel - Summary
        left_panel = QFrame()
        left_panel.setStyleSheet("background-color: #f8fafc;")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        # Header
        header = QLabel(f"Request #{req_id}")
        header.setStyleSheet("background-color: #0B2C5F; color: white; font-size: 13px; font-weight: bold; padding: 10px;")
        header.setAlignment(Qt.AlignCenter)
        left_layout.addWidget(header)
        
        # Scroll area for details
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background-color: #f8fafc; border: none;")
        
        details_widget = QWidget()
        details_layout = QVBoxLayout(details_widget)
        details_layout.setContentsMargins(14, 14, 14, 14)
        details_layout.setSpacing(3)
        
        def add_section(title: str):
            label = QLabel(title)
            label.setStyleSheet("background-color: #e2e8f0; color: #0B2C5F; font-size: 9px; font-weight: bold; padding: 4px 14px;")
            details_layout.addWidget(label)
        
        def add_field(label: str, value):
            row = QHBoxLayout()
            row.setSpacing(0)
            lbl = QLabel(label)
            lbl.setStyleSheet("color: #64748b; font-size: 9px; width: 140px;")
            row.addWidget(lbl)
            val = QLabel(str(value) if value not in (None, "", "None") else "—")
            val.setStyleSheet("color: #0f172a; font-size: 9px; font-weight: bold;")
            val.setWordWrap(True)
            row.addWidget(val)
            details_layout.addLayout(row)
        
        add_section("Basic Info")
        add_field("Request ID", item_data.get("id"))
        add_field("Date", item_data.get("request_date"))
        add_field("Factory", item_data.get("factory_id"))
        add_field("Requested By", item_data.get("requested_by"))
        add_field("Vendor", item_data.get("vendor"))
        add_field("Urgent", "Yes" if item_data.get("urgent_flag") else "No")
        
        add_section("Item Details")
        add_field("Category", item_data.get("item_category"))
        add_field("Item Name", item_data.get("item_name"))
        add_field("Qty", item_data.get("qty"))
        add_field("Unit", item_data.get("unit"))
        add_field("Rate (₹)", item_data.get("rate"))
        add_field("GST %", item_data.get("gst_percent"))
        add_field("Amount (₹)", item_data.get("amount"))
        add_field("Total Amount (₹)", item_data.get("final_amount"))
        add_field("Reason", item_data.get("reason"))
        
        add_section("Approval & Payment")
        add_field("Approval Status", item_data.get("approval_status"))
        add_field("Approved Amount (₹)", item_data.get("approved_amount"))
        add_field("Approved By", item_data.get("approved_by"))
        add_field("Approved At", item_data.get("approved_at"))
        add_field("Approval Remark", item_data.get("approval_remark"))
        add_field("Priority", item_data.get("priority"))
        add_field("Exp. Payment Date", item_data.get("expected_payment_date"))
        add_field("Payment Status", item_data.get("payment_status"))
        add_field("Total Paid (₹)", item_data.get("total_paid"))
        add_field("Balance (₹)", item_data.get("balance_amount"))
        
        add_section("Location")
        add_field("Latitude", item_data.get("geo_latitude"))
        add_field("Longitude", item_data.get("geo_longitude"))
        add_field("Accuracy (m)", item_data.get("geo_accuracy_m"))
        add_field("In Factory", "Yes" if item_data.get("is_in_factory") else "No")
        add_field("Distance (m)", item_data.get("distance_from_factory_m"))
        
        add_section("Timestamps")
        add_field("Created At", item_data.get("created_at"))
        add_field("Updated At", item_data.get("updated_at"))
        
        add_section("Request Workflow")
        add_field("Request Type", item_data.get("request_type"))
        add_field("Purpose", item_data.get("purpose"))
        add_field("Completion Status", item_data.get("completion_status"))
        add_field("Completion Remark", item_data.get("completion_remark"))
        add_field("Submitted By", item_data.get("completion_submitted_by_name"))
        add_field("Submitted At", item_data.get("completion_submitted_at"))
        add_field("Vendor Bill", "Uploaded" if item_data.get("vendor_bill_path") else "—")
        add_field("Company Voucher", "Uploaded" if item_data.get("company_voucher_path") else "—")
        add_field("Reopen Reason", item_data.get("reopen_reason"))
        add_field("Verified By", item_data.get("verified_by"))
        add_field("Verified At", item_data.get("verified_at"))
        add_field("Closing Remark", item_data.get("verified_remark"))
        
        details_layout.addStretch()
        scroll.setWidget(details_widget)
        left_layout.addWidget(scroll)
        
        layout.addWidget(left_panel, 1)

        # Bottom actions - summary only, no preview panel.
        action_bar = QFrame()
        action_bar.setStyleSheet("background-color: #f1f5f9; border-top: 1px solid #d6dee8;")
        action_layout = QHBoxLayout(action_bar)
        action_layout.setContentsMargins(10, 8, 10, 8)

        doc_state = "Bill attached" if (self.bill_paths.get(req_id) or "").strip() else "No bill path on this request"
        doc_label = QLabel(doc_state)
        doc_label.setStyleSheet("color: #334155; font-size: 10px;")
        action_layout.addWidget(doc_label)
        action_layout.addStretch()

        def download_detail_bill() -> None:
            if dialog_closed["value"]:
                return
            self._download_bill_as_pdf(req_id, dialog)

        download_btn = QPushButton("Download Bill")
        download_btn.setStyleSheet("background-color: #155c8a; color: white; border: none; padding: 6px 12px;")
        download_btn.clicked.connect(download_detail_bill)
        action_layout.addWidget(download_btn)

        left_layout.addWidget(action_bar)
        
        dialog.exec()
    
    def _show_pdf_page_d(self, pages: list, idx: list, label: QLabel, preview_area: QLabel, page_num: int) -> None:
        """Show PDF page in detail window."""
        if not pages:
            return
        page_num = max(0, min(page_num, len(pages) - 1))
        idx[0] = page_num
        label.setText(f"Page {page_num + 1} / {len(pages)}")
        img = pages[page_num]
        img = img.convert("RGB")
        qimage = QImage(img.tobytes(), img.width, img.height, QImage.Format_RGB888).copy()
        pixmap = QPixmap.fromImage(qimage)
        target_w = max(preview_area.width(), 640)
        target_h = max(preview_area.height(), 480)
        preview_area.setPixmap(pixmap.scaled(target_w, target_h, Qt.KeepAspectRatio, Qt.SmoothTransformation))
    
    def open_partial_approve_dialog(self, req_id: int) -> None:
        """Open partial approve dialog for recording payments."""
        req_data = {}
        for item in self._last_server_items:
            if int(item.get("id", -1)) == req_id:
                req_data = item
                break

        dialog = QDialog(self)
        dialog.setWindowTitle(f"Partial Payment — Request #{req_id}")
        dialog.resize(560, 720)
        
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)
        
        # Summary section
        summary_group = QGroupBox("Payment Summary")
        summary_layout = QGridLayout(summary_group)
        summary_layout.setSpacing(4)
        
        total_var = QLabel("Loading…")
        paid_var = QLabel("—")
        balance_var = QLabel("—")
        
        summary_layout.addWidget(QLabel("Total Amount (₹):"), 0, 0)
        summary_layout.addWidget(total_var, 0, 1)
        summary_layout.addWidget(QLabel("Already Paid (₹):"), 1, 0)
        summary_layout.addWidget(paid_var, 1, 1)
        summary_layout.addWidget(QLabel("Remaining Balance (₹):"), 2, 0)
        summary_layout.addWidget(balance_var, 2, 1)
        
        layout.addWidget(summary_group)
        
        # Payment history table
        history_group = QGroupBox("Payment History")
        history_layout = QVBoxLayout(history_group)
        
        history_table = QTableWidget()
        history_table.setColumnCount(5)
        history_table.setHorizontalHeaderLabels(["Date", "Mode", "Paid (₹)", "Balance (₹)", "Remark"])
        history_table.setStyleSheet("""
            QTableWidget {
                background-color: white;
                color: #0f172a;
                border: 1px solid #e2e8f0;
                gridline-color: #cbd5e1;
                selection-background-color: #dbeafe;
                selection-color: #0f172a;
            }
            QHeaderView::section {
                background-color: #1f6fbe;
                color: white;
                padding: 6px;
                border: none;
                font-size: 9px;
            }
            QTableWidget::item {
                color: #0f172a;
                padding: 4px 6px;
                border-bottom: 1px solid #e2e8f0;
            }
        """)
        history_table.setColumnWidth(0, 95)
        history_table.setColumnWidth(1, 100)
        history_table.setColumnWidth(2, 85)
        history_table.setColumnWidth(3, 90)
        history_table.setColumnWidth(4, 140)
        history_table.horizontalHeader().setStretchLastSection(True)
        history_table.verticalHeader().setVisible(False)
        history_table.setMaximumHeight(120)
        
        history_layout.addWidget(history_table)
        layout.addWidget(history_group)
        
        # Payment form
        form_group = QGroupBox("Record Payment")
        form_layout = QVBoxLayout(form_group)
        
        amount_label = QLabel("Payment Amount (₹) *")
        amount_label.setStyleSheet("color: #334155; font-weight: bold; font-size: 10px;")
        form_layout.addWidget(amount_label)
        
        amount_input = QLineEdit()
        amount_input.setStyleSheet("padding: 6px 10px; border: 1px solid #cbd5e1; border-radius: 4px; font-size: 11px;")
        form_layout.addWidget(amount_input)
        
        mode_label = QLabel("Payment Mode *")
        mode_label.setStyleSheet("color: #334155; font-weight: bold; font-size: 10px;")
        form_layout.addWidget(mode_label)
        
        mode_combo = QComboBox()
        mode_combo.addItems(["Cash", "UPI", "Bank Transfer", "Cheque"])
        mode_combo.setStyleSheet("padding: 6px 10px; border: 1px solid #cbd5e1; border-radius: 4px;")
        form_layout.addWidget(mode_combo)
        
        remarks_label = QLabel("Remarks (optional)")
        remarks_label.setStyleSheet("color: #334155; font-weight: bold; font-size: 10px;")
        form_layout.addWidget(remarks_label)
        
        remarks_input = QLineEdit()
        remarks_input.setStyleSheet("padding: 6px 10px; border: 1px solid #cbd5e1; border-radius: 4px;")
        form_layout.addWidget(remarks_input)
        
        layout.addWidget(form_group)
        
        # Status
        status_label = QLabel("")
        status_label.setWordWrap(True)
        status_label.setStyleSheet("color: #64748b; font-size: 10px;")
        layout.addWidget(status_label)
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(dialog.reject)
        button_layout.addWidget(cancel_btn)
        
        submit_btn = QPushButton("Record Payment")
        submit_btn.setStyleSheet("background-color: #15803d; color: white; font-weight: bold; padding: 8px 16px; border: none; border-radius: 4px;")
        button_layout.addWidget(submit_btn)
        
        layout.addLayout(button_layout)
        
        remaining = [0.0]

        def as_money(value) -> float:
            try:
                return float(value or 0)
            except (TypeError, ValueError):
                return 0.0

        def apply_summary(data: dict, source: str = "server") -> None:
            total = as_money(data.get("approved_amount") or data.get("total_amount") or data.get("final_amount"))
            paid = as_money(data.get("total_paid"))
            balance = as_money(data.get("balance") if "balance" in data else data.get("balance_amount"))
            if balance <= 0 and total > 0:
                balance = max(total - paid, 0.0)
            remaining[0] = balance

            total_var.setText(f"{total:,.2f}")
            paid_var.setText(f"{paid:,.2f}")
            balance_var.setText(f"{balance:,.2f}")
            amount_input.setText(f"{balance:.2f}" if balance > 0 else "0.00")

            history = data.get("history") or []
            history_table.setRowCount(0)
            for p in history:
                row = history_table.rowCount()
                history_table.insertRow(row)
                values = [
                    p.get("payment_date", ""),
                    p.get("payment_mode", ""),
                    f"{as_money(p.get('paid_amount')):,.2f}",
                    f"{as_money(p.get('balance_amount')):,.2f}",
                    p.get("remark", ""),
                ]
                for col, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    item.setForeground(QColor("#0f172a"))
                    history_table.setItem(row, col, item)

            if not history:
                row = history_table.rowCount()
                history_table.insertRow(row)
                for col in range(5):
                    item = QTableWidgetItem("—")
                    item.setForeground(QColor("#0f172a"))
                    history_table.setItem(row, col, item)

            if source == "cache":
                status_label.setText("Refreshing payment summary...")
                status_label.setStyleSheet("color: #64748b;")
            else:
                status_label.setText("")

        def on_summary_loaded(loaded_req_id: int, data: object) -> None:
            if loaded_req_id == req_id and isinstance(data, dict):
                apply_summary(data)

        def on_summary_failed(loaded_req_id: int, err: str) -> None:
            if loaded_req_id != req_id:
                return
            status_label.setText(err)
            status_label.setStyleSheet("color: #b02a37;")

        if req_data:
            apply_summary(req_data, source="cache")
        
        def on_submit():
            amount_str = amount_input.text().strip()
            if not amount_str:
                status_label.setText("Payment amount is required.")
                status_label.setStyleSheet("color: #b02a37;")
                return
            try:
                amount = float(amount_str)
                if amount <= 0:
                    raise ValueError
            except ValueError:
                status_label.setText("Payment amount must be a positive number.")
                status_label.setStyleSheet("color: #b02a37;")
                return
            
            rem = remaining[0]
            if rem > 0 and amount > rem + 0.01:
                status_label.setText(f"Amount ₹{amount:.2f} exceeds remaining balance ₹{rem:.2f}.")
                status_label.setStyleSheet("color: #b02a37;")
                return
            
            payload = {
                "paid_amount": str(amount),
                "payment_mode": mode_combo.currentText() or "Cash",
            }
            remark = remarks_input.text().strip()
            if remark:
                payload["remarks"] = remark
            
            submit_btn.setEnabled(False)
            status_label.setText("Submitting…")
            status_label.setStyleSheet("color: #555;")
            
            success, message = self._perform_action(f"/requests/{req_id}/partial-approve", payload)
            status_label.setText(message)
            status_label.setStyleSheet("color: #1f8a43;" if success else "color: #b02a37;")
            submit_btn.setEnabled(True)
            if success:
                self.sync_from_server(silent=True)
                QTimer.singleShot(1000, dialog.accept)
        
        submit_btn.clicked.connect(on_submit)

        loader = PaymentSummaryThread(self, req_id)
        loader.loaded.connect(on_summary_loaded)
        loader.failed.connect(on_summary_failed)
        dialog._summary_loader = loader
        loader.start()
        
        dialog.exec()
    
    def open_text_action_dialog(
        self,
        title: str,
        req_id: int,
        path_template: str,
        field_name: str,
        field_label: str,
        submit_text: str,
        required: bool,
        alias_field_names: tuple[str, ...] = (),
    ) -> None:
        """Open dialog for text-based actions (e.g., Reject)."""
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(460, 300)
        
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)
        
        label = QLabel(field_label)
        label.setStyleSheet("color: #334155; font-weight: bold; font-size: 10px;")
        layout.addWidget(label)
        
        text_box = QTextEdit()
        text_box.setStyleSheet("padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px;")
        layout.addWidget(text_box, 1)
        
        status_label = QLabel("")
        status_label.setWordWrap(True)
        status_label.setStyleSheet("color: #64748b; font-size: 10px;")
        layout.addWidget(status_label)
        
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(dialog.reject)
        button_layout.addWidget(cancel_btn)
        
        submit_btn = QPushButton(submit_text)
        submit_btn.setStyleSheet("background-color: #1f6fbe; color: white; font-weight: bold; padding: 8px 16px; border: none; border-radius: 4px;")
        button_layout.addWidget(submit_btn)
        
        layout.addLayout(button_layout)
        
        def on_submit():
            value = text_box.toPlainText().strip()
            if required and not value:
                status_label.setText(f"{field_label} is required.")
                status_label.setStyleSheet("color: #b02a37;")
                return

            payload = {field_name: value}
            for alias in alias_field_names:
                payload[alias] = value
            
            success, message = self._perform_action(
                path_template.format(req_id=req_id),
                payload,
            )
            status_label.setText(message)
            status_label.setStyleSheet("color: #1f8a43;" if success else "color: #b02a37;")
            if success:
                self.sync_from_server(silent=True)
                QTimer.singleShot(900, dialog.accept)
        
        submit_btn.clicked.connect(on_submit)
        
        dialog.exec()
    
    def open_verify_dialog(self, req_id: int) -> None:
        """Open verify and close dialog."""
        # Get request data
        req_data = {}
        for item in self._last_server_items:
            if item.get("id") == req_id:
                req_data = item
                break
        
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Verify & Close — Request #{req_id}")
        dialog.resize(500, 460)
        
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)
        
        # Completion details
        info_group = QGroupBox("Completion Details")
        info_layout = QVBoxLayout(info_group)
        
        def add_info_row(label: str, value: str):
            row = QHBoxLayout()
            lbl = QLabel(f"{label}:")
            lbl.setStyleSheet("color: #334155; font-weight: bold; font-size: 9px; width: 140px;")
            row.addWidget(lbl)
            val = QLabel(value or "—")
            val.setWordWrap(True)
            row.addWidget(val)
            info_layout.addLayout(row)
        
        add_info_row("Completion Remark", req_data.get("completion_remark") or "—")
        add_info_row("Submitted By", req_data.get("completion_submitted_by_name") or "—")
        add_info_row("Submitted At", req_data.get("completion_submitted_at") or "—")
        
        # Document buttons
        doc_row = QHBoxLayout()
        doc_label = QLabel("Documents:")
        doc_label.setStyleSheet("color: #334155; font-weight: bold; font-size: 9px; width: 140px;")
        doc_row.addWidget(doc_label)
        
        doc_btn_layout = QHBoxLayout()
        
        has_vb = bool(req_data.get("vendor_bill_path"))
        has_cv = bool(req_data.get("company_voucher_path"))
        
        def open_doc(doc_type: str):
            base = DEFAULT_BASE_URL.rstrip("/")
            endpoint = f"{base}/requests/{req_id}/{doc_type}"
            try:
                r = self.session.get(endpoint, allow_redirects=True, timeout=30)
                if r.status_code == 200:
                    ct = r.headers.get("Content-Type", "")
                    ext = ".pdf" if "pdf" in ct else (".png" if "png" in ct else ".jpg")
                    cd = r.headers.get("Content-Disposition", "")
                    m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', cd, re.IGNORECASE)
                    if m:
                        ext = Path(m.group(1).strip()).suffix or ext
                    import tempfile
                    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext, prefix=f"req{req_id}_{doc_type}_")
                    tmp.write(r.content)
                    tmp.close()
                    os.startfile(tmp.name)
                else:
                    QMessageBox.critical(dialog, "Document", f"Could not fetch document (HTTP {r.status_code})")
            except Exception as exc:
                QMessageBox.critical(dialog, "Document", f"Error: {exc}")
        
        if has_vb:
            vb_btn = QPushButton("📄 View Vendor Bill")
            vb_btn.clicked.connect(lambda: open_doc("vendor-bill"))
            doc_btn_layout.addWidget(vb_btn)
        else:
            doc_btn_layout.addWidget(QLabel("No vendor bill"))
        
        if has_cv:
            cv_btn = QPushButton("🧾 View Voucher")
            cv_btn.clicked.connect(lambda: open_doc("company-voucher"))
            doc_btn_layout.addWidget(cv_btn)
        else:
            doc_btn_layout.addWidget(QLabel("No company voucher"))
        
        doc_row.addLayout(doc_btn_layout)
        info_layout.addLayout(doc_row)
        
        layout.addWidget(info_group)
        
        # Closing remarks
        remarks_label = QLabel("Closing Remarks (optional)")
        remarks_label.setStyleSheet("color: #334155; font-weight: bold; font-size: 10px;")
        layout.addWidget(remarks_label)
        
        remarks_box = QTextEdit()
        remarks_box.setStyleSheet("padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px;")
        layout.addWidget(remarks_box, 1)
        
        status_label = QLabel("")
        status_label.setWordWrap(True)
        status_label.setStyleSheet("color: #64748b; font-size: 10px;")
        layout.addWidget(status_label)
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(dialog.reject)
        button_layout.addWidget(cancel_btn)
        
        submit_btn = QPushButton("Verify & Close")
        submit_btn.setStyleSheet("background-color: #065f46; color: white; font-weight: bold; padding: 8px 16px; border: none; border-radius: 4px;")
        button_layout.addWidget(submit_btn)
        
        layout.addLayout(button_layout)
        
        def on_submit():
            closing_remarks = remarks_box.toPlainText().strip()
            payload = {}
            if closing_remarks:
                payload["closing_remarks"] = closing_remarks
            
            success, message = self._perform_action(f"/requests/{req_id}/verify", payload)
            status_label.setText(message)
            status_label.setStyleSheet("color: #1f8a43;" if success else "color: #b02a37;")
            if success:
                self.sync_from_server(silent=True)
                QTimer.singleShot(900, dialog.accept)
        
        submit_btn.clicked.connect(on_submit)
        
        dialog.exec()
    
    def open_reopen_dialog(self, req_id: int) -> None:
        """Open reopen completion dialog."""
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Reopen Completion — Request #{req_id}")
        dialog.resize(420, 220)
        
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)
        
        info = QLabel(f"Reopen completion for request #{req_id}.\nThe factory user will need to resubmit completion.")
        info.setWordWrap(True)
        layout.addWidget(info)
        
        reason_label = QLabel("Reason (will be shown to factory user):")
        reason_label.setStyleSheet("color: #334155; font-weight: bold; font-size: 9px;")
        layout.addWidget(reason_label)
        
        reason_box = QTextEdit()
        reason_box.setStyleSheet("padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px;")
        reason_box.setMaximumHeight(80)
        layout.addWidget(reason_box)
        
        status_label = QLabel("")
        status_label.setWordWrap(True)
        status_label.setStyleSheet("color: #64748b; font-size: 10px;")
        layout.addWidget(status_label)
        
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(dialog.reject)
        button_layout.addWidget(cancel_btn)
        
        submit_btn = QPushButton("Reopen")
        submit_btn.setStyleSheet("background-color: #9a3412; color: white; font-weight: bold; padding: 8px 16px; border: none; border-radius: 4px;")
        button_layout.addWidget(submit_btn)
        
        layout.addLayout(button_layout)
        
        def on_confirm():
            reason = reason_box.toPlainText().strip()
            try:
                base = self._server_url()
            except RuntimeError as exc:
                status_label.setText(str(exc))
                status_label.setStyleSheet("color: #b02a37;")
                return
            
            fd = {"reason": reason} if reason else {}
            try:
                r = self.session.post(f"{base}/requests/{req_id}/reopen", data=fd, timeout=15)
                body = r.json() if r.headers.get("Content-Type", "").startswith("application/json") else {}
                if r.status_code == 200:
                    self.sync_from_server(silent=True)
                    dialog.accept()
                    QMessageBox.information(self, "Reopen", body.get("message", "Reopened successfully."))
                else:
                    status_label.setText(body.get("detail", f"HTTP {r.status_code}"))
                    status_label.setStyleSheet("color: #b02a37;")
            except Exception as exc:
                status_label.setText(f"Error: {exc}")
                status_label.setStyleSheet("color: #b02a37;")
        
        submit_btn.clicked.connect(on_confirm)
        
        dialog.exec()


def main() -> int:
    sys.excepthook = lambda exc_type, exc_value, exc_traceback: _report_runtime_exception(
        "Admin Panel Error", exc_type, exc_value, exc_traceback
    )
    threading.excepthook = _threading_excepthook

    try:
        app = QApplication(sys.argv)
        window = AdminPanelPySide6()
        window.show()
        exit_code = app.exec()
        print(f"Admin panel exited with code {exit_code}", flush=True)
        # Some Windows terminal/GUI shutdown paths surface as Qt exit code 1
        # even when no unhandled exception occurred.
        if exit_code == 1:
            print("Normalizing Qt exit code 1 to 0 (clean shutdown).", flush=True)
            return 0
        return exit_code
    except KeyboardInterrupt:
        print("Admin panel interrupted; exiting cleanly.", flush=True)
        return 0
    except Exception:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        _report_runtime_exception("Admin Panel Startup Error", exc_type, exc_value, exc_traceback)
        return 1


if __name__ == "__main__":
    main()
