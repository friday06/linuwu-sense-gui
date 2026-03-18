# SPDX-License-Identifier: GPL-3.0-or-later
"""
linuwu-sense-gui — main_window.py
Top-level application window.

Design notes (KDE HIG / Breeze):
  • No custom title-bar widget — the OS window decoration shows the app name.
  • Spacing and margins are read from QStyle pixel-metrics so they follow
    the user's configured spacing (compact / normal / relaxed).
  • Tab icons use QIcon.fromTheme() for system-consistent symbols.
  • The footer carries only two actions (Refresh, About) — no decorative text
    that duplicates information already in the window title or About dialog.
"""

import os
from PyQt6.QtWidgets import (
    QMainWindow, QTabWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QSizePolicy, QDialog, QDialogButtonBox,
    QFrame, QApplication, QStyle, QSystemTrayIcon,
)
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QIcon, QDesktopServices

from ui.thermal_fan_tab import ThermalFanTab
from ui.battery_tab import BatteryTab
from ui.keyboard_tab import KeyboardTab
from ui.advanced_tab import AdvancedTab
from controller.feature_detector import FeatureDetector
from controller.sysfs_controller import SysfsController
from config.constants import APP_NAME, APP_VERSION, ICON_PATH
from ui.tray_icon import TrayIcon
from ui.welcome import WelcomeDialog, should_show


def _sp(metric: QStyle.PixelMetric) -> int:
    """Query the current style for a layout pixel metric."""
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

        m  = _sp(QStyle.PixelMetric.PM_LayoutLeftMargin) * 2   # 16-24 px
        sp = _sp(QStyle.PixelMetric.PM_LayoutVerticalSpacing)   # 6-8 px

        layout = QVBoxLayout(self)
        layout.setSpacing(sp * 2)
        layout.setContentsMargins(m, m, m, sp * 2)

        # App name + version
        name_lbl = QLabel(APP_NAME)
        name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_lbl.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(name_lbl)

        ver_lbl = QLabel(f"Version {APP_VERSION}  ·  Acer Predator &amp; Nitro")
        ver_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ver_lbl.setProperty("secondary", "true")
        layout.addWidget(ver_lbl)

        layout.addWidget(_hline())

        desc = QLabel(
            "A native KDE graphical interface for controlling hardware "
            "features on Acer Predator and Nitro laptops via the "
            "<b>linuwu_sense</b> kernel module."
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
        self.setMinimumSize(640, 480)

        # Set window icon
        if os.path.exists(ICON_PATH):
            self.setWindowIcon(QIcon(ICON_PATH))
        else:
            self.setWindowIcon(QIcon.fromTheme("computer-laptop",
                               QIcon.fromTheme("preferences-system")))

        # Size relative to the available screen geometry
        if screen := QApplication.primaryScreen():
            sg = screen.availableGeometry()
            w = max(700, min(920, int(sg.width()  * 0.55)))
            h = max(520, min(700, int(sg.height() * 0.65)))
            self.resize(w, h)
            self.move(sg.center().x() - w // 2,
                      sg.center().y() - h // 2)

        # Style-metric based spacing
        m  = _sp(QStyle.PixelMetric.PM_LayoutLeftMargin)
        sp = _sp(QStyle.PixelMetric.PM_LayoutVerticalSpacing)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(sp)
        root.setContentsMargins(m, m, m, sp)

        # Tab widget
        self._tabs = QTabWidget()
        self._tabs.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._populate_tabs()
        root.addWidget(self._tabs)

        # Footer — two buttons, no decorative credits text
        root.addWidget(_hline())
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)

        refresh_btn = QPushButton(
            QIcon.fromTheme("view-refresh"), "Refresh")
        refresh_btn.clicked.connect(self._refresh)
        footer.addWidget(refresh_btn)

        footer.addStretch()

        about_btn = QPushButton(
            QIcon.fromTheme("help-about"), "About")
        about_btn.clicked.connect(self._about)
        footer.addWidget(about_btn)

        root.addLayout(footer)

    def _setup_tray(self) -> None:
        """Create the system tray icon (if the desktop supports it)."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self._tray = TrayIcon(self, self._ctrl)
        self._tray.show()
        # Close-to-tray: hide window instead of quitting
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

    def update_tray(self, cpu_temp: float, profile: str) -> None:
        """Called by the active tab's poll loop to refresh the tray icon."""
        if hasattr(self, "_tray"):
            self._tray.update(cpu_temp, profile)

    def closeEvent(self, event) -> None:
        """Hide to tray instead of quitting (KDE convention)."""
        if hasattr(self, "_tray") and self._tray.isVisible():
            self.hide()
            event.ignore()
        else:
            event.accept()

    def _populate_tabs(self) -> None:
        self._tabs.clear()
        self._ctrl.sense_base = self._detector.get_sense_base()

        # Use fromTheme() icons — Breeze provides all of these
        for key in self._detector.get_available_tabs():
            if key == "thermal_fan":
                self._tabs.addTab(
                    ThermalFanTab(self._ctrl),
                    QIcon.fromTheme("cpu"),
                    "Thermal & Fan",
                )
            elif key == "battery":
                self._tabs.addTab(
                    BatteryTab(self._ctrl),
                    QIcon.fromTheme("battery"),
                    "Battery",
                )
            elif key == "keyboard":
                self._tabs.addTab(
                    KeyboardTab(self._ctrl),
                    QIcon.fromTheme("input-keyboard"),
                    "Keyboard RGB",
                )
            elif key == "advanced":
                self._tabs.addTab(
                    AdvancedTab(self._ctrl),
                    QIcon.fromTheme("configure"),
                    "Advanced",
                )

        if self._tabs.count() == 0:
            placeholder = QLabel(
                "No linuwu-sense features detected.\n\n"
                "Make sure the kernel module is loaded:\n"
                "    sudo modprobe linuwu_sense"
            )
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            placeholder.setProperty("secondary", "true")
            self._tabs.addTab(placeholder,
                              QIcon.fromTheme("dialog-warning"), "Status")


    def _show_welcome(self) -> None:
        WelcomeDialog(self).exec()

    def _refresh(self) -> None:
        self._detector.sense_base = self._detector._find_sense_base()
        self._populate_tabs()

    def _about(self) -> None:
        AboutDialog(self).exec()

