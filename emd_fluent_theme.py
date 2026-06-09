"""
EMD Fluent Blue Theme for PySide6
Premium enterprise ERP dashboard theme inspired by Microsoft Fluent Design
"""

from PySide6.QtGui import QPalette, QColor, QFont
from PySide6.QtCore import Qt

# Color Palette
class EMDColors:
    # Primary gradient colors
    PRIMARY_DARK = "#0B2A5B"      # Deep blue
    PRIMARY_LIGHT = "#0E4DA4"     # Light blue
    PRIMARY_ACCENT = "#1E7BB8"    # Accent blue
    PRIMARY_GLOW = "#3B82F6"      # Glow blue
    
    # Background colors
    BG_DARK = "#0B2A5B"           # Main background dark
    BG_LIGHT = "#0E4DA4"          # Main background light
    BG_CARD = "#0D3A7D"           # Card background
    BG_CARD_HOVER = "#104A9C"     # Card hover
    BG_SIDEBAR = "#0A2450"        # Sidebar background
    
    # Text colors
    TEXT_PRIMARY = "#FFFFFF"      # White primary text
    TEXT_SECONDARY = "#A0B8D6"    # Light gray secondary text
    TEXT_MUTED = "#6B8CAF"        # Muted text
    TEXT_DARK = "#1E3A5F"         # Dark text for light backgrounds
    
    # Status colors
    STATUS_APPROVED = "#10B981"   # Green
    STATUS_PENDING = "#F59E0B"    # Orange
    STATUS_PARTIAL = "#FBBF24"    # Yellow
    STATUS_REJECTED = "#EF4444"   # Red
    STATUS_SUBMITTED = "#06B6D4"  # Cyan
    STATUS_CLOSED = "#3B82F6"      # Blue
    
    # UI Element colors
    BORDER_COLOR = "#1E4A8C"       # Border color
    SHADOW_COLOR = "rgba(0, 0, 0, 0.3)"  # Shadow color
    GLOW_COLOR = "rgba(59, 130, 246, 0.3)"  # Glow color
    
    # Button colors
    BTN_PRIMARY = "#1E7BB8"       # Primary button
    BTN_PRIMARY_HOVER = "#2A8BC9" # Primary button hover
    BTN_SECONDARY = "#0D3A7D"     # Secondary button
    BTN_SECONDARY_HOVER = "#104A9C"  # Secondary button hover
    BTN_SUCCESS = "#10B981"       # Success button
    BTN_DANGER = "#EF4444"        # Danger button
    BTN_WARNING = "#F59E0B"       # Warning button


def apply_emd_fluent_theme(app):
    """Apply the EMD Fluent Blue theme to the application."""
    palette = QPalette()
    
    # Window and background colors
    palette.setColor(QPalette.Window, QColor(EMDColors.BG_DARK))
    palette.setColor(QPalette.WindowText, QColor(EMDColors.TEXT_PRIMARY))
    
    # Base colors (text entry fields, etc.)
    palette.setColor(QPalette.Base, QColor(EMDColors.BG_CARD))
    palette.setColor(QPalette.AlternateBase, QColor(EMDColors.BG_CARD_HOVER))
    
    # Text colors
    palette.setColor(QPalette.Text, QColor(EMDColors.TEXT_PRIMARY))
    palette.setColor(QPalette.ToolTipBase, QColor(EMDColors.TEXT_DARK))
    palette.setColor(QPalette.ToolTipText, QColor(EMDColors.TEXT_PRIMARY))
    
    # Button colors
    palette.setColor(QPalette.Button, QColor(EMDColors.BTN_SECONDARY))
    palette.setColor(QPalette.ButtonText, QColor(EMDColors.TEXT_PRIMARY))
    
    # Bright text (for dark backgrounds)
    palette.setColor(QPalette.BrightText, QColor(EMDColors.TEXT_PRIMARY))
    
    # Link colors
    palette.setColor(QPalette.Link, QColor(EMDColors.PRIMARY_GLOW))
    palette.setColor(QPalette.LinkVisited, QColor(EMDColors.PRIMARY_ACCENT))
    
    # Highlight colors (selection)
    palette.setColor(QPalette.Highlight, QColor(EMDColors.PRIMARY_ACCENT))
    palette.setColor(QPalette.HighlightedText, QColor(EMDColors.TEXT_PRIMARY))
    
    app.setPalette(palette)
    
    # Set default font
    font = QFont("Segoe UI", 10)
    if not font.exactMatch():
        font = QFont("Inter", 10)
    app.setFont(font)


# CSS Stylesheet Templates
class EMDStyles:
    """CSS stylesheet templates for EMD Fluent Blue theme."""
    
    @staticmethod
    def card_style(border_radius=12, glow=True):
        """Card stylesheet with rounded corners and optional glow."""
        glow_css = f"""
            box-shadow: 0 4px 20px {EMDColors.GLOW_COLOR};
        """ if glow else ""
        
        return f"""
            QFrame {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {EMDColors.BG_CARD},
                    stop:1 {EMDColors.BG_CARD_HOVER});
                border: 1px solid {EMDColors.BORDER_COLOR};
                border-radius: {border_radius}px;
                {glow_css}
            }}
        """
    
    @staticmethod
    def card_light_style(border_radius=12):
        """Lighter card stylesheet for contrast."""
        return f"""
            QFrame {{
                background-color: #0E4A9C;
                border: 1px solid {EMDColors.BORDER_COLOR};
                border-radius: {border_radius}px;
            }}
        """
    
    @staticmethod
    def button_primary_style():
        """Primary button with gradient and glow."""
        return f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {EMDColors.BTN_PRIMARY},
                    stop:1 {EMDColors.PRIMARY_ACCENT});
                color: {EMDColors.TEXT_PRIMARY};
                font-weight: bold;
                padding: 10px 20px;
                border: none;
                border-radius: 8px;
                box-shadow: 0 2px 8px rgba(30, 123, 184, 0.4);
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {EMDColors.BTN_PRIMARY_HOVER},
                    stop:1 {EMDColors.PRIMARY_GLOW});
                box-shadow: 0 4px 12px rgba(59, 130, 246, 0.5);
            }}
            QPushButton:pressed {{
                background: {EMDColors.BTN_PRIMARY};
            }}
            QPushButton:disabled {{
                background: {EMDColors.BG_SIDEBAR};
                color: {EMDColors.TEXT_MUTED};
            }}
        """
    
    @staticmethod
    def button_secondary_style():
        """Secondary button style."""
        return f"""
            QPushButton {{
                background-color: {EMDColors.BTN_SECONDARY};
                color: {EMDColors.TEXT_PRIMARY};
                font-weight: bold;
                padding: 10px 20px;
                border: 1px solid {EMDColors.BORDER_COLOR};
                border-radius: 8px;
            }}
            QPushButton:hover {{
                background-color: {EMDColors.BTN_SECONDARY_HOVER};
                border-color: {EMDColors.PRIMARY_ACCENT};
            }}
            QPushButton:pressed {{
                background-color: {EMDColors.BTN_PRIMARY};
            }}
        """
    
    @staticmethod
    def button_success_style():
        """Success button style."""
        return f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {EMDColors.STATUS_APPROVED},
                    stop:1 #059669);
                color: {EMDColors.TEXT_PRIMARY};
                font-weight: bold;
                padding: 10px 20px;
                border: none;
                border-radius: 8px;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #34D399,
                    stop:1 {EMDColors.STATUS_APPROVED});
            }}
        """
    
    @staticmethod
    def button_danger_style():
        """Danger button style."""
        return f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {EMDColors.STATUS_REJECTED},
                    stop:1 #DC2626);
                color: {EMDColors.TEXT_PRIMARY};
                font-weight: bold;
                padding: 10px 20px;
                border: none;
                border-radius: 8px;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #F87171,
                    stop:1 {EMDColors.STATUS_REJECTED});
            }}
        """
    
    @staticmethod
    def button_warning_style():
        """Warning button style."""
        return f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {EMDColors.STATUS_PARTIAL},
                    stop:1 #D97706);
                color: {EMDColors.TEXT_DARK};
                font-weight: bold;
                padding: 10px 20px;
                border: none;
                border-radius: 8px;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #FCD34D,
                    stop:1 {EMDColors.STATUS_PARTIAL});
            }}
        """
    
    @staticmethod
    def sidebar_style():
        """Sidebar navigation style."""
        return f"""
            QFrame {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {EMDColors.BG_SIDEBAR},
                    stop:1 {EMDColors.BG_DARK});
                border-right: 1px solid {EMDColors.BORDER_COLOR};
            }}
        """
    
    @staticmethod
    def sidebar_button_style(is_active=False):
        """Sidebar button style with active state."""
        if is_active:
            return f"""
                QPushButton {{
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                        stop:0 {EMDColors.PRIMARY_ACCENT},
                        stop:1 {EMDColors.PRIMARY_GLOW});
                    color: {EMDColors.TEXT_PRIMARY};
                    text-align: left;
                    padding: 12px 20px;
                    border: none;
                    border-radius: 8px;
                    font-weight: bold;
                    font-size: 11px;
                    box-shadow: 0 2px 8px rgba(59, 130, 246, 0.4);
                }}
            """
        else:
            return f"""
                QPushButton {{
                    background-color: transparent;
                    color: {EMDColors.TEXT_SECONDARY};
                    text-align: left;
                    padding: 12px 20px;
                    border: none;
                    border-radius: 8px;
                    font-size: 11px;
                }}
                QPushButton:hover {{
                    background-color: {EMDColors.BG_CARD};
                    color: {EMDColors.TEXT_PRIMARY};
                }}
            """
    
    @staticmethod
    def table_style():
        """Modern ERP table style."""
        return f"""
            QTableWidget {{
                background-color: {EMDColors.BG_CARD};
                border: 1px solid {EMDColors.BORDER_COLOR};
                border-radius: 8px;
                gridline-color: {EMDColors.BORDER_COLOR};
                selection-background-color: {EMDColors.PRIMARY_ACCENT};
                selection-color: {EMDColors.TEXT_PRIMARY};
            }}
            QTableWidget::item {{
                padding: 8px;
                border: none;
            }}
            QTableWidget::item:selected {{
                background-color: {EMDColors.PRIMARY_ACCENT};
                color: {EMDColors.TEXT_PRIMARY};
            }}
            QTableWidget::item:hover {{
                background-color: {EMDColors.BG_CARD_HOVER};
            }}
            QHeaderView::section {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {EMDColors.PRIMARY_DARK},
                    stop:1 {EMDColors.PRIMARY_LIGHT});
                color: {EMDColors.TEXT_PRIMARY};
                padding: 12px 8px;
                border: none;
                border-bottom: 2px solid {EMDColors.PRIMARY_ACCENT};
                border-radius: 8px 8px 0 0;
                font-weight: bold;
                font-size: 10px;
            }}
            QHeaderView::section:hover {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {EMDColors.PRIMARY_ACCENT},
                    stop:1 {EMDColors.PRIMARY_GLOW});
            }}
            QScrollBar:vertical {{
                background-color: {EMDColors.BG_SIDEBAR};
                width: 12px;
                border-radius: 6px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {EMDColors.PRIMARY_ACCENT};
                border-radius: 6px;
                min-height: 20px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: {EMDColors.PRIMARY_GLOW};
            }}
        """
    
    @staticmethod
    def kpi_card_style(status_color=None):
        """KPI card style with optional status color."""
        if status_color:
            border_color = status_color
            glow_color = status_color
        else:
            border_color = EMDColors.PRIMARY_ACCENT
            glow_color = EMDColors.PRIMARY_GLOW
        
        return f"""
            QFrame {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {EMDColors.BG_CARD},
                    stop:1 {EMDColors.BG_CARD_HOVER});
                border: 2px solid {border_color};
                border-radius: 12px;
                box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3), 
                            0 0 15px {glow_color}40;
            }}
        """
    
    @staticmethod
    def input_style():
        """Input field style."""
        return f"""
            QLineEdit, QTextEdit, QComboBox {{
                background-color: {EMDColors.BG_CARD};
                color: {EMDColors.TEXT_PRIMARY};
                padding: 10px 14px;
                border: 1px solid {EMDColors.BORDER_COLOR};
                border-radius: 8px;
                font-size: 11px;
            }}
            QLineEdit:hover, QTextEdit:hover, QComboBox:hover {{
                border-color: {EMDColors.PRIMARY_ACCENT};
            }}
            QLineEdit:focus, QTextEdit:focus, QComboBox:focus {{
                border-color: {EMDColors.PRIMARY_GLOW};
                box-shadow: 0 0 8px {EMDColors.GLOW_COLOR};
            }}
            QComboBox::drop-down {{
                border: none;
            }}
            QComboBox::down-arrow {{
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 5px solid {EMDColors.TEXT_SECONDARY};
            }}
        """
    
    @staticmethod
    def label_style(is_header=False, is_secondary=False):
        """Label style."""
        if is_header:
            return f"""
                QLabel {{
                    color: {EMDColors.TEXT_PRIMARY};
                    font-size: 14px;
                    font-weight: bold;
                }}
            """
        elif is_secondary:
            return f"""
                QLabel {{
                    color: {EMDColors.TEXT_SECONDARY};
                    font-size: 10px;
                }}
            """
        else:
            return f"""
                QLabel {{
                    color: {EMDColors.TEXT_PRIMARY};
                    font-size: 11px;
                }}
            """
    
    @staticmethod
    def header_style():
        """Main header style."""
        return f"""
            QFrame {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {EMDColors.PRIMARY_DARK},
                    stop:1 {EMDColors.PRIMARY_LIGHT});
                border: none;
                border-radius: 0px;
            }}
        """
    
    @staticmethod
    def status_badge_style(status):
        """Status badge style based on status."""
        colors = {
            "Approved": EMDColors.STATUS_APPROVED,
            "Pending": EMDColors.STATUS_PENDING,
            "Partial Approved": EMDColors.STATUS_PARTIAL,
            "Rejected": EMDColors.STATUS_REJECTED,
            "Completion Submitted": EMDColors.STATUS_SUBMITTED,
            "Closed": EMDColors.STATUS_CLOSED,
        }
        color = colors.get(status, EMDColors.PRIMARY_ACCENT)
        
        return f"""
            QLabel {{
                background-color: {color};
                color: white;
                padding: 4px 12px;
                border-radius: 12px;
                font-weight: bold;
                font-size: 9px;
            }}
        """
    
    @staticmethod
    def main_window_style():
        """Main window background style."""
        return f"""
            QMainWindow {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 {EMDColors.BG_DARK},
                    stop:1 {EMDColors.BG_LIGHT});
            }}
        """


def get_status_color(status):
    """Get color for a given status."""
    colors = {
        "Approved": EMDColors.STATUS_APPROVED,
        "Pending": EMDColors.STATUS_PENDING,
        "Partial Approved": EMDColors.STATUS_PARTIAL,
        "Rejected": EMDColors.STATUS_REJECTED,
        "Completion Submitted": EMDColors.STATUS_SUBMITTED,
        "Closed": EMDColors.STATUS_CLOSED,
    }
    return colors.get(status, EMDColors.PRIMARY_ACCENT)


def get_row_background_color(row_index, is_alternate=True):
    """Get background color for table row."""
    if is_alternate and row_index % 2 == 1:
        return EMDColors.BG_CARD_HOVER
    return EMDColors.BG_CARD
