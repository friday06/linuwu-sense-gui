# SPDX-License-Identifier: GPL-3.0-or-later
"""
linuwu-sense-gui — welcome.py
First-run welcome dialog shown once after installation.
Explains the three key behaviours new users are most likely to miss.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QDialogButtonBox, QFrame,
)
from PyQt6.QtCore import Qt, QSettings
from PyQt6.QtGui import QIcon

from config.constants import APP_NAME


def should_show() -> bool:
    s = QSettings("linuwu-sense", "linuwu-sense-gui")
    return not s.value("welcome/shown", False, type=bool)


def mark_shown() -> None:
    s = QSettings("linuwu-sense", "linuwu-sense-gui")
    s.setValue("welcome/shown", True)


class WelcomeDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Getting Started")
        self.setMinimumWidth(440)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(24, 20, 24, 16)

        # Heading
        heading = QLabel(f"Welcome to <b>{APP_NAME}</b>")
        heading.setStyleSheet("font-size: 16px;")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(heading)

        sub = QLabel(
            "Here's a quick overview of key features.")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setProperty("secondary", "true")
        layout.addWidget(sub)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(sep)

        for icon_name, title, body in [
            ("preferences-system",
             "Runs in Background",
             "Closing the window hides it to the system tray. "
             "The app keeps monitoring in the background. "
             "Right-click the tray icon to quit."),
            ("cpu",
             "Hardware Shortcut Key",
             "The NitroSense hardware key (Fn + ?) is registered as a "
             "KDE global shortcut. Press it to show or hide the window. "
             "Log out once after installation for it to activate."),
            ("battery",
             "Smart Performance Switching",
             "The profile switches automatically when the charger is "
             "plugged or unplugged, and as the battery drains. "
             "Use the lock button (🔒) in the profile row to disable this."),
        ]:
            row = QHBoxLayout()
            row.setSpacing(12)

            icon_lbl = QLabel()
            icon_lbl.setPixmap(
                QIcon.fromTheme(icon_name).pixmap(32, 32))
            icon_lbl.setFixedSize(36, 36)
            icon_lbl.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
            row.addWidget(icon_lbl)

            text = QVBoxLayout()
            t = QLabel(f"<b>{title}</b>")
            text.addWidget(t)
            b = QLabel(body)
            b.setWordWrap(True)
            b.setProperty("secondary", "true")
            text.addWidget(b)
            row.addLayout(text, 1)

            layout.addLayout(row)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(sep2)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        btns.button(QDialogButtonBox.StandardButton.Ok).setText("Get Started")
        btns.accepted.connect(self.accept)
        layout.addWidget(btns)

    def accept(self) -> None:
        mark_shown()
        super().accept()
