# SPDX-License-Identifier: GPL-3.0-or-later
"""
linuwu-sense-gui — main_window.py
Top-level application window.

Layout mirrors KDE System Monitor:
  • Left sidebar — icon + label nav items, Refresh + About at bottom
  • Right content — QStackedWidget, one page per section
  • No tab bar — the sidebar IS the navigation
"""

import os
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget,
    QLabel, QPushButton, QSizePolicy, QDialog, QDialogButtonBox,
    QFrame, QApplication, QStyle, QSystemTrayIcon, QListWidget,
    QListWidgetItem, QSplitter, QAbstractItemView,
)
from PyQt6.QtCore import Qt, QUrl, QSize
from PyQt6.QtGui import QIcon, QDesktopServices, QFont

from ui.thermal_fan_tab import ThermalFanTab
from ui.battery_tab import BatteryTab
from ui.keyboard_tab import KeyboardTab
from ui.advanced_tab import AdvancedTab
from ui.fan_tab import FanTab
from ui.settings_tab import SettingsTab
from controller.feature_detector import FeatureDetector
from controller.sysfs_controller import SysfsController
from config.constants import APP_NAME, APP_VERSION, ICON_PATH
from ui.tray_icon import TrayIcon
from ui.welcome import WelcomeDialog, should_show


def _sp(metric: QStyle.PixelMetric) -> int:
    return QApplication.style().pixelMetric(metric)


def _hline() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setFrameShadow(QFrame.Shadow.Sunken)
    return f


# ── About dialog ──────────────────────────────────────────────────────────────

class AboutDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"About {APP_NAME}")
        self.setMinimumWidth(460)
        self.setModal(True)

        m  = _sp(QStyle.PixelMetric.PM_LayoutLeftMargin) * 2
        sp = _sp(QStyle.PixelMetric.PM_LayoutVerticalSpacing)

        layout = QVBoxLayout(self)
        layout.setSpacing(sp * 2)
        layout.setContentsMargins(m, m, m, sp * 2)

        icon_row = QHBoxLayout()
        icon_row.setSpacing(12)
        icon_row.addStretch()
        if os.path.exists(ICON_PATH):
            icon_lbl = QLabel()
            icon_lbl.setPixmap(QIcon(ICON_PATH).pixmap(64, 64))
            icon_row.addWidget(icon_lbl)
        name_lbl = QLabel(APP_NAME)
        name_lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        name_lbl.setStyleSheet("font-size: 18px; font-weight: bold;")
        icon_row.addWidget(name_lbl)
        icon_row.addStretch()
        layout.addLayout(icon_row)

        ver_lbl = QLabel(f"Version {APP_VERSION}  ·  Acer Predator &amp; Nitro")
        ver_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ver_lbl.setProperty("secondary", "true")
        layout.addWidget(ver_lbl)

        layout.addWidget(_hline())

        desc = QLabel(
            "Hardware control application for Acer Predator and Nitro laptops.\n"
            "Built on the <b>linuwu_sense</b> kernel module."
        )
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setWordWrap(True)
        layout.addWidget(desc)

        layout.addWidget(_hline())
        layout.addWidget(QLabel("<b>Credits</b>",
                                alignment=Qt.AlignmentFlag.AlignCenter))

        for person, role, url in [
            ("friday06",
             "linuwu-sense-gui application",
             "https://github.com/friday06/linuwu-sense-gui"),
            ("0x7375646F (sudo)",
             "linuwu_sense kernel module",
             "https://github.com/0x7375646F/Linuwu-Sense"),
        ]:
            row = QHBoxLayout()
            row.setSpacing(sp)
            name = QLabel(f"<b>{person}</b>")
            name.setMinimumWidth(170)
            row.addWidget(name)
            role_lbl = QLabel(role)
            role_lbl.setProperty("secondary", "true")
            row.addWidget(role_lbl, 1)
            link = QPushButton("↗")
            link.setFixedSize(28, 28)
            link.setToolTip(url)
            link.clicked.connect(lambda _, u=url: QDesktopServices.openUrl(QUrl(u)))
            row.addWidget(link)
            layout.addLayout(row)

        layout.addWidget(_hline())

        paths_lbl = QLabel("<b>Hardware Interface Paths</b>")
        paths_lbl.setStyleSheet("font-size: 11px;")
        layout.addWidget(paths_lbl)

        paths = QLabel(
            "<code>/sys/module/linuwu_sense/drivers/platform:acer-wmi/"
            "acer-wmi/nitro_sense</code><br>"
            "<code>/sys/module/linuwu_sense/drivers/platform:acer-wmi/"
            "acer-wmi/predator_sense</code>"
        )
        paths.setWordWrap(True)
        paths.setProperty("secondary", "true")
        layout.addWidget(paths)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)


# ── Sidebar nav list ──────────────────────────────────────────────────────────

class _SideBar(QListWidget):
    """
    KDE System Monitor-style left navigation.
    Each item has a 22×22 icon and a label.
    The selected item drives the QStackedWidget on the right.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setIconSize(QSize(22, 22))
        self.setSpacing(2)
        self.setMinimumWidth(160)
        self.setMaximumWidth(220)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Style: no border, highlight row with Plasma accent colour
        self.setStyleSheet("""
            QListWidget {
                background: transparent;
                border: none;
                padding: 4px 0;
            }
            QListWidget::item {
                padding: 8px 12px;
                border-radius: 6px;
                margin: 1px 6px;
            }
            QListWidget::item:selected {
                background: palette(highlight);
                color: palette(highlighted-text);
            }
            QListWidget::item:hover:!selected {
                background: palette(alternate-base);
            }
        """)

    def add_page(self, icon_name: str, label: str) -> None:
        item = QListWidgetItem(QIcon.fromTheme(icon_name), label)
        item.setSizeHint(QSize(148, 38))
        self.addItem(item)


# ── Main window ───────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self._detector = FeatureDetector()
        self._ctrl = SysfsController(self._detector.get_sense_base())
        self._build_ui()
        self._setup_tray()
        if should_show():
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(400, self._show_welcome)

    def _build_ui(self) -> None:
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(720, 520)

        app_icon = QIcon(ICON_PATH) if os.path.exists(ICON_PATH) \
            else QIcon.fromTheme("computer-laptop",
                                 QIcon.fromTheme("preferences-system"))
        self.setWindowIcon(app_icon)
        QApplication.setWindowIcon(app_icon)

        if screen := QApplication.primaryScreen():
            sg = screen.availableGeometry()
            w = max(760, min(1024, int(sg.width()  * 0.60)))
            h = max(560, min(780, int(sg.height() * 0.70)))
            self.resize(w, h)
            self.move(sg.center().x() - w // 2,
                      sg.center().y() - h // 2)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        # ── Header bar ────────────────────────────────────────────────────
        header = QWidget()
        header.setObjectName("sidebar-header")
        header.setFixedHeight(48)
        header.setStyleSheet("""
            #sidebar-header {
                background: palette(button);
                border-bottom: 1px solid palette(mid);
            }
            #sidebar-header QLabel {
                color: palette(buttontext);
            }
        """)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(16, 0, 12, 0)
        hl.setSpacing(8)

        title_lbl = QLabel(APP_NAME)
        font = QFont()
        font.setPointSize(13)
        font.setBold(True)
        title_lbl.setFont(font)
        # No inline style — inherit from window palette correctly
        hl.addWidget(title_lbl)
        hl.addStretch()

        refresh_btn = QPushButton(QIcon.fromTheme("view-refresh"), "Refresh")
        refresh_btn.setFixedHeight(32)
        refresh_btn.clicked.connect(self._refresh)
        hl.addWidget(refresh_btn)

        about_btn = QPushButton(QIcon.fromTheme("help-about"), "About")
        about_btn.setFixedHeight(32)
        about_btn.clicked.connect(self._about)
        hl.addWidget(about_btn)

        root.addWidget(header)

        # ── Splitter: sidebar | content ───────────────────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)
        splitter.setStyleSheet("QSplitter::handle { background: palette(mid); }")

        # Left sidebar
        sidebar_container = QWidget()
        sidebar_container.setObjectName("sidebar-container")
        sidebar_container.setStyleSheet("""
            #sidebar-container {
                background: palette(window);
                border-right: 1px solid palette(mid);
            }
        """)
        sc_layout = QVBoxLayout(sidebar_container)
        sc_layout.setContentsMargins(0, 8, 0, 8)
        sc_layout.setSpacing(0)

        self._sidebar = _SideBar()
        self._sidebar.currentRowChanged.connect(self._on_nav)
        sc_layout.addWidget(self._sidebar)

        splitter.addWidget(sidebar_container)

        # Right content
        self._stack = QStackedWidget()
        splitter.addWidget(self._stack)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([180, 900])
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)

        root.addWidget(splitter, 1)

        self._populate_pages()

    def _populate_pages(self) -> None:
        self._sidebar.clear()
        while self._stack.count():
            self._stack.removeWidget(self._stack.widget(0))

        self._ctrl.sense_base = self._detector.get_sense_base()

        for key in self._detector.get_available_tabs():
            if key == "thermal_fan":
                self._sidebar.add_page("cpu",            "Overview")
                self._stack.addWidget(ThermalFanTab(self._ctrl))
            elif key == "fan_control":
                self._sidebar.add_page("cpu-symbolic",   "Fan Control")
                self._stack.addWidget(FanTab(self._ctrl))
            elif key == "battery":
                self._sidebar.add_page("battery",        "Battery")
                self._stack.addWidget(BatteryTab(self._ctrl))
            elif key == "keyboard":
                self._sidebar.add_page("input-keyboard", "Keyboard RGB")
                self._stack.addWidget(KeyboardTab(self._ctrl))
            elif key == "advanced":
                self._sidebar.add_page("configure",      "Advanced")
                self._stack.addWidget(AdvancedTab(self._ctrl))

        # Settings always shown
        self._sidebar.add_page("preferences-system", "Settings")
        self._stack.addWidget(SettingsTab())

        if self._stack.count() == 0:
            placeholder = QLabel(
                "No compatible hardware features detected.\n\n"
                "Ensure the linuwu_sense kernel module is loaded:\n"
                "    sudo modprobe linuwu_sense"
            )
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            placeholder.setProperty("secondary", "true")
            self._sidebar.add_page("dialog-warning", "Status")
            self._stack.addWidget(placeholder)

        self._sidebar.setCurrentRow(0)

    def _on_nav(self, row: int) -> None:
        if 0 <= row < self._stack.count():
            self._stack.setCurrentIndex(row)

    def _setup_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self._tray = TrayIcon(self, self._ctrl)
        self._tray.show()
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

    def update_tray(self, cpu_temp: float, profile: str) -> None:
        if hasattr(self, "_tray"):
            self._tray.update(cpu_temp, profile)

    def closeEvent(self, event) -> None:
        if hasattr(self, "_tray") and self._tray.isVisible():
            self.hide()
            event.ignore()
        else:
            event.accept()

    def _show_welcome(self) -> None:
        WelcomeDialog(self).exec()

    def _refresh(self) -> None:
        self._detector.sense_base = self._detector._find_sense_base()
        self._populate_pages()

    def _about(self) -> None:
        AboutDialog(self).exec()
