"""
Glass Blue ERP Theme for PySide6
A modern glassmorphism theme with deep corporate blue gradients
"""

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPalette
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont


class GlassColors:
    """Color palette for Glass Blue ERP theme."""
    
    # Background gradients
    BG_DARK = "#0A1929"
    BG_MID = "#102A43"
    BG_LIGHT = "#1E3A5F"
    BG_GRADIENT_START = "#0A1929"
    BG_GRADIENT_END = "#1E3A5F"
    
    # Glass card colors
    GLASS_BG = "rgba(255, 255, 255, 0.08)"
    GLASS_BORDER = "rgba(255, 255, 255, 0.15)"
    GLASS_HOVER = "rgba(255, 255, 255, 0.12)"
    
    # Primary colors
    PRIMARY = "#2196F3"
    PRIMARY_LIGHT = "#42A5F5"
    PRIMARY_DARK = "#1976D2"
    PRIMARY_ACCENT = "#64B5F6"
    
    # Text colors
    TEXT_PRIMARY = "#FFFFFF"
    TEXT_SECONDARY = "#B0BEC5"
    TEXT_MUTED = "#78909C"
    TEXT_DARK = "#37474F"
    
    # Status colors
    STATUS_APPROVED = "#4CAF50"
    STATUS_PENDING = "#FF9800"
    STATUS_REJECTED = "#F44336"
    STATUS_PARTIAL = "#FFC107"
    STATUS_SUBMITTED = "#00BCD4"
    STATUS_CLOSED = "#2196F3"
    
    # Border colors
    BORDER_COLOR = "rgba(255, 255, 255, 0.1)"
    BORDER_LIGHT = "rgba(255, 255, 255, 0.2)"
    
    # Shadow colors
    SHADOW_COLOR = "rgba(0, 0, 0, 0.3)"
    SHADOW_LIGHT = "rgba(0, 0, 0, 0.15)"


class GlassStyles:
    """CSS stylesheet methods for Glass Blue ERP theme."""
    
    @staticmethod
    def apply_theme(app: QApplication) -> None:
        """Apply the Glass Blue ERP theme to the application."""
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor(GlassColors.BG_DARK))
        palette.setColor(QPalette.WindowText, QColor(GlassColors.TEXT_PRIMARY))
        palette.setColor(QPalette.Base, QColor(GlassColors.GLASS_BG))
        palette.setColor(QPalette.AlternateBase, QColor(GlassColors.GLASS_HOVER))
        palette.setColor(QPalette.ToolTipBase, QColor(GlassColors.BG_LIGHT))
        palette.setColor(QPalette.ToolTipText, QColor(GlassColors.TEXT_PRIMARY))
        palette.setColor(QPalette.Text, QColor(GlassColors.TEXT_PRIMARY))
        palette.setColor(QPalette.Button, QColor(GlassColors.GLASS_BG))
        palette.setColor(QPalette.ButtonText, QColor(GlassColors.TEXT_PRIMARY))
        palette.setColor(QPalette.BrightText, QColor(GlassColors.TEXT_PRIMARY))
        palette.setColor(QPalette.Link, QColor(GlassColors.PRIMARY_ACCENT))
        palette.setColor(QPalette.Highlight, QColor(GlassColors.PRIMARY))
        palette.setColor(QPalette.HighlightedText, QColor(GlassColors.TEXT_PRIMARY))
        app.setPalette(palette)
        
        # Set default font
        font = QFont("Segoe UI", 10)
        app.setFont(font)
    
    @staticmethod
    def glass_card_style() -> str:
        """Glassmorphism card style."""
        return f"""
            QFrame {{
                background: {GlassColors.GLASS_BG};
                border: 1px solid {GlassColors.GLASS_BORDER};
                border-radius: 16px;
                backdrop-filter: blur(10px);
            }}
        """
    
    @staticmethod
    def glass_card_light_style() -> str:
        """Lighter glass card style for emphasis."""
        return f"""
            QFrame {{
                background: rgba(255, 255, 255, 0.12);
                border: 1px solid {GlassColors.BORDER_LIGHT};
                border-radius: 16px;
                backdrop-filter: blur(10px);
            }}
        """
    
    @staticmethod
    def header_style() -> str:
        """Header bar style."""
        return f"""
            QFrame {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {GlassColors.BG_DARK},
                    stop:1 {GlassColors.BG_MID});
                border: none;
                border-bottom: 1px solid {GlassColors.BORDER_COLOR};
            }}
        """
    
    @staticmethod
    def sidebar_style() -> str:
        """Sidebar style."""
        return f"""
            QFrame {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {GlassColors.BG_DARK},
                    stop:1 {GlassColors.BG_MID});
                border: none;
                border-right: 1px solid {GlassColors.BORDER_COLOR};
            }}
        """
    
    @staticmethod
    def sidebar_button_style(is_active: bool = False) -> str:
        """Sidebar navigation button style."""
        if is_active:
            return f"""
                QPushButton {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 {GlassColors.PRIMARY_DARK},
                        stop:1 {GlassColors.PRIMARY});
                    color: {GlassColors.TEXT_PRIMARY};
                    font-weight: bold;
                    padding: 12px 16px;
                    border: none;
                    border-radius: 8px;
                    text-align: left;
                }}
                QPushButton:hover {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 {GlassColors.PRIMARY},
                        stop:1 {GlassColors.PRIMARY_LIGHT});
                }}
            """
        else:
            return f"""
                QPushButton {{
                    background: transparent;
                    color: {GlassColors.TEXT_SECONDARY};
                    font-weight: normal;
                    padding: 12px 16px;
                    border: none;
                    border-radius: 8px;
                    text-align: left;
                }}
                QPushButton:hover {{
                    background: {GlassColors.GLASS_HOVER};
                    color: {GlassColors.TEXT_PRIMARY};
                }}
            """
    
    @staticmethod
    def button_primary_style() -> str:
        """Primary button style with gradient."""
        return f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {GlassColors.PRIMARY_LIGHT},
                    stop:1 {GlassColors.PRIMARY_DARK});
                color: {GlassColors.TEXT_PRIMARY};
                font-weight: bold;
                padding: 10px 20px;
                border: 1px solid {GlassColors.PRIMARY_ACCENT};
                border-radius: 8px;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {GlassColors.PRIMARY},
                    stop:1 {GlassColors.PRIMARY_DARK});
            }}
            QPushButton:pressed {{
                background: {GlassColors.PRIMARY_DARK};
            }}
        """
    
    @staticmethod
    def button_secondary_style() -> str:
        """Secondary button style."""
        return f"""
            QPushButton {{
                background: {GlassColors.GLASS_BG};
                color: {GlassColors.TEXT_PRIMARY};
                font-weight: bold;
                padding: 10px 20px;
                border: 1px solid {GlassColors.BORDER_COLOR};
                border-radius: 8px;
            }}
            QPushButton:hover {{
                background: {GlassColors.GLASS_HOVER};
                border-color: {GlassColors.BORDER_LIGHT};
            }}
            QPushButton:pressed {{
                background: {GlassColors.GLASS_BG};
            }}
        """
    
    @staticmethod
    def button_success_style() -> str:
        """Success button style."""
        return f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {GlassColors.STATUS_APPROVED},
                    stop:1 #388E3C);
                color: {GlassColors.TEXT_PRIMARY};
                font-weight: bold;
                padding: 10px 20px;
                border: 1px solid #66BB6A;
                border-radius: 8px;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #66BB6A,
                    stop:1 #43A047);
            }}
        """
    
    @staticmethod
    def input_style() -> str:
        """Input field style."""
        return f"""
            QLineEdit, QTextEdit, QComboBox {{
                background: rgba(255, 255, 255, 0.05);
                color: {GlassColors.TEXT_PRIMARY};
                padding: 10px 12px;
                border: 1px solid {GlassColors.BORDER_COLOR};
                border-radius: 8px;
                selection-background-color: {GlassColors.PRIMARY};
            }}
            QLineEdit:focus, QTextEdit:focus, QComboBox:focus {{
                border: 1px solid {GlassColors.PRIMARY};
                background: rgba(255, 255, 255, 0.08);
            }}
            QComboBox::drop-down {{
                border: none;
            }}
            QComboBox::down-arrow {{
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 5px solid {GlassColors.TEXT_SECONDARY};
            }}
        """
    
    @staticmethod
    def table_style() -> str:
        """Modern table style with glass effect."""
        return f"""
            QTableWidget {{
                background: {GlassColors.GLASS_BG};
                border: 1px solid {GlassColors.BORDER_COLOR};
                border-radius: 12px;
                gridline-color: {GlassColors.BORDER_COLOR};
            }}
            QTableWidget::item {{
                padding: 10px;
                border-bottom: 1px solid {GlassColors.BORDER_COLOR};
            }}
            QTableWidget::item:hover {{
                background: {GlassColors.GLASS_HOVER};
            }}
            QHeaderView::section {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {GlassColors.BG_MID},
                    stop:1 {GlassColors.BG_LIGHT});
                color: {GlassColors.TEXT_PRIMARY};
                padding: 12px 10px;
                border: none;
                border-bottom: 2px solid {GlassColors.PRIMARY};
                border-top-left-radius: 12px;
                border-top-right-radius: 12px;
                font-weight: bold;
                font-size: 11px;
            }}
            QTableWidget::item:selected {{
                background: {GlassColors.PRIMARY};
                color: {GlassColors.TEXT_PRIMARY};
            }}
        """
    
    @staticmethod
    def kpi_card_style(status_color: str = None) -> str:
        """KPI card style with glass effect."""
        if status_color:
            return f"""
                QFrame {{
                    background: {GlassColors.GLASS_BG};
                    border: 1px solid {status_color};
                    border-radius: 16px;
                    backdrop-filter: blur(10px);
                }}
            """
        return f"""
            QFrame {{
                background: {GlassColors.GLASS_BG};
                border: 1px solid {GlassColors.BORDER_COLOR};
                border-radius: 16px;
                backdrop-filter: blur(10px);
            }}
        """
    
    @staticmethod
    def label_style() -> str:
        """Label style."""
        return f"""
            QLabel {{
                color: {GlassColors.TEXT_SECONDARY};
                font-size: 10px;
            }}
        """
    
    @staticmethod
    def status_badge_style(status: str) -> str:
        """Status badge style."""
        status_colors = {
            "Approved": GlassColors.STATUS_APPROVED,
            "Pending": GlassColors.STATUS_PENDING,
            "Rejected": GlassColors.STATUS_REJECTED,
            "Partial Approved": GlassColors.STATUS_PARTIAL,
            "Completion Submitted": GlassColors.STATUS_SUBMITTED,
            "Closed": GlassColors.STATUS_CLOSED,
        }
        color = status_colors.get(status, GlassColors.TEXT_SECONDARY)
        return f"""
            QLabel {{
                background: {color};
                color: {GlassColors.TEXT_PRIMARY};
                padding: 4px 12px;
                border-radius: 12px;
                font-weight: bold;
                font-size: 9px;
            }}
        """


def get_status_color(status: str) -> str:
    """Get color for a status."""
    status_colors = {
        "Approved": GlassColors.STATUS_APPROVED,
        "Pending": GlassColors.STATUS_PENDING,
        "Rejected": GlassColors.STATUS_REJECTED,
        "Partial Approved": GlassColors.STATUS_PARTIAL,
        "Completion Submitted": GlassColors.STATUS_SUBMITTED,
        "Closed": GlassColors.STATUS_CLOSED,
    }
    return status_colors.get(status, GlassColors.TEXT_SECONDARY)


def apply_glass_blue_erp_theme(app: QApplication) -> None:
    """Apply the Glass Blue ERP theme to the application."""
    GlassStyles.apply_theme(app)
