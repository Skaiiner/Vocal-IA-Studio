from __future__ import annotations

BG = "#14161c"
BG_PANEL = "#1b1f28"
BG_INPUT = "#232833"
BORDER = "#2f3541"
TEXT = "#e8ecf4"
TEXT_DIM = "#8b93a7"
ACCENT = "#5b8cff"
ACCENT_HOVER = "#7aa2ff"
REC = "#ff5160"
OK = "#3ddc97"
WARN = "#ffb84d"
WAVE_SONG = "#4a7fe0"
WAVE_VOCAL = "#3ddc97"
GRID = "#262c38"
PLAYHEAD = "#ffd166"

STYLESHEET = f"""
QWidget {{ background: {BG}; color: {TEXT}; font-size: 13px; }}
/* Sin esto, cada etiqueta pinta su propio fondo y deja recuadros sobre los paneles. */
QLabel, QCheckBox, QGroupBox, QSlider {{ background: transparent; }}
QLabel#Title {{ font-size: 20px; font-weight: 700; letter-spacing: 1px; }}
QLabel#Subtitle {{ color: {TEXT_DIM}; }}
QLabel#SectionTitle {{ font-size: 15px; font-weight: 600; }}
QLabel#Hint {{ color: {TEXT_DIM}; }}
QFrame#Panel {{ background: {BG_PANEL}; border: 1px solid {BORDER}; border-radius: 10px; }}
QTabWidget::pane {{ border: none; background: {BG}; }}
QTabBar::tab {{
    background: transparent; color: {TEXT_DIM}; padding: 9px 16px; margin-right: 4px;
    border-bottom: 2px solid transparent; font-weight: 600;
}}
QTabBar::tab:selected {{ color: {TEXT}; border-bottom: 2px solid {ACCENT}; }}
QTabBar::tab:hover:!selected {{ color: {TEXT}; }}
QTabBar::tab:disabled {{ color: #5a6072; }}
QPushButton {{
    background: {BG_INPUT}; border: 1px solid {BORDER}; border-radius: 7px;
    padding: 7px 14px; font-weight: 600;
}}
QPushButton:hover:!disabled {{ border-color: {ACCENT}; }}
QPushButton:pressed {{ background: {BORDER}; }}
QPushButton:disabled {{ color: #5a6072; }}
QPushButton#Primary {{ background: {ACCENT}; border-color: {ACCENT}; color: #0b1020; }}
QPushButton#Primary:hover:!disabled {{ background: {ACCENT_HOVER}; }}
QPushButton#Record {{ background: {REC}; border-color: {REC}; color: #1a0508; }}
QPushButton#Record:hover:!disabled {{ background: #ff7580; }}
QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {{
    background: {BG_INPUT}; border: 1px solid {BORDER}; border-radius: 6px; padding: 5px 8px;
}}
QComboBox:focus, QLineEdit:focus {{ border-color: {ACCENT}; }}
QComboBox QAbstractItemView {{ background: {BG_INPUT}; selection-background-color: {ACCENT}; border: 1px solid {BORDER}; }}
QListWidget {{ background: {BG_INPUT}; border: 1px solid {BORDER}; border-radius: 6px; }}
QListWidget::item {{ padding: 6px 8px; }}
QListWidget::item:selected {{ background: {ACCENT}; color: #0b1020; }}
QSlider::groove:horizontal {{ height: 4px; background: {BORDER}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    background: {TEXT}; width: 14px; margin: -6px 0; border-radius: 7px;
}}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QCheckBox::indicator {{
    width: 15px; height: 15px; border: 1px solid {BORDER}; border-radius: 4px; background: {BG_INPUT};
}}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QGroupBox {{ border: 1px solid {BORDER}; border-radius: 8px; margin-top: 14px; padding-top: 8px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {TEXT_DIM}; font-weight: 600; }}
QStatusBar {{ background: {BG_PANEL}; border-top: 1px solid {BORDER}; color: {TEXT_DIM}; }}
QMenuBar {{ background: {BG_PANEL}; }}
QMenuBar::item:selected {{ background: {BG_INPUT}; }}
QMenu {{ background: {BG_PANEL}; border: 1px solid {BORDER}; }}
QMenu::item:selected {{ background: {ACCENT}; color: #0b1020; }}
QScrollArea {{ border: none; }}
QToolTip {{ background: {BG_INPUT}; color: {TEXT}; border: 1px solid {BORDER}; padding: 4px; }}
"""
